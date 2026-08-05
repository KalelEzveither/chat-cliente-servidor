# -*- coding: utf-8 -*-
"""
servidor/bancodedados.py

Camada de persistencia do servidor, usando SQLite (modulo `sqlite3` da
biblioteca padrao do Python -- nao precisa instalar nada).

Implementa tres requisitos opcionais do trabalho:
  1. "Persistencia do historico de mensagens em arquivo ou banco de dados":
     tabela `mensagens`. Duas categorias, com regras diferentes:
       - PRIVADAS: entram no historico de quem enviou/recebeu, reenviadas
         uma unica vez logo apos o login (independem de sala);
       - GERAIS (broadcast): NAO reenviadas de uma vez so pra todo mundo
         que entra numa sala (isso inundaria um usuario novo com conversa
         antiga que nao diz respeito a ele). Em vez disso, usa-se um
         esquema de "ultima vez visto": a tabela `ultima_saida_sala` marca
         quando cada usuario saiu de cada sala pela ultima vez (troca de
         sala ou desconexao); ao (re)entrar numa sala, o servidor manda so
         as mensagens gerais daquela sala enviadas DEPOIS desse momento.
  2. Regra de acesso ao historico: SO usuarios que JA se conectaram ao
     servidor alguma vez antes (em qualquer sessao anterior) recebem
     historico (privado e/ou geral) ao logar. Um apelido usado pela
     PRIMEIRA vez nunca recebe historico, mesmo que a sala ja tenha
     conversa acontecendo ha tempos -- ele so passa a ver dali em diante,
     ao vivo. Isso e controlado pela tabela `usuarios_conhecidos`: no
     login, o servidor verifica se aquele apelido ja tem um registro la;
     se nao tiver, ele e criado NA HORA (para a proxima vez que alguem
     conectar com esse mesmo apelido ja contar como "ja conhecido"), mas
     a sessao atual e tratada como novata e nao recebe nada de historico.
  3. "Criacao de salas/canais tematicos": ver `servidor/servidor.py`
     (roteamento de broadcast/lista por sala).

Nao ha sistema de contas/senha: o apelido sozinho identifica o cliente
(requisito obrigatorio do trabalho). A tabela `usuarios_conhecidos` NAO e
autenticacao (qualquer um pode conectar com qualquer apelido livre) -- ela
so guarda "esse nome ja apareceu aqui antes?" para decidir se mostra
historico ou nao.

Sincronizacao: cada funcao abre e fecha sua propria conexao sqlite3 (o
arquivo de banco e local, em disco). Um Lock global (`_TRAVA`) serializa o
acesso, ja que o SQLite permite varias leituras simultaneas mas apenas uma
escrita por vez -- sem o lock, threads concorrentes de clientes diferentes
poderiam esbarrar em erros de "database is locked".
"""

import sqlite3
import threading
from datetime import datetime, timezone

_TRAVA = threading.Lock()

_SQL_CRIAR_TABELAS = """
CREATE TABLE IF NOT EXISTS mensagens (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    tipo         TEXT NOT NULL,        -- 'MSG' (chat geral) ou 'PRIVADA'
    remetente    TEXT NOT NULL,
    destinatario TEXT,                 -- NULL para mensagens gerais
    texto        TEXT NOT NULL,
    quando       TEXT NOT NULL,        -- timestamp ISO-8601 em UTC
    sala         TEXT                  -- sala da mensagem (so p/ tipo='MSG')
);

CREATE TABLE IF NOT EXISTS ultima_saida_sala (
    usuario  TEXT NOT NULL,
    sala     TEXT NOT NULL,
    quando   TEXT NOT NULL,            -- timestamp ISO-8601 em UTC
    PRIMARY KEY (usuario, sala)
);

CREATE TABLE IF NOT EXISTS usuarios_conhecidos (
    usuario         TEXT PRIMARY KEY,
    primeiro_login  TEXT NOT NULL      -- timestamp ISO-8601 em UTC
);
"""

def inicializar_banco(caminho: str) -> None:
    """Cria o arquivo de banco de dados e as tabelas, caso ainda nao existam.
    Deve ser chamada uma vez, quando o servidor inicia."""
    with _TRAVA, sqlite3.connect(caminho) as conexao:
        conexao.executescript(_SQL_CRIAR_TABELAS)
        # Migracao: bancos criados antes da funcionalidade de salas nao tem
        # a coluna `sala` em `mensagens`. Adiciona-a caso falte.
        colunas = [linha[1] for linha in conexao.execute("PRAGMA table_info(mensagens)").fetchall()]
        if "sala" not in colunas:
            conexao.execute("ALTER TABLE mensagens ADD COLUMN sala TEXT")


# ---------------------------------------------------------------------- #
# Controle de "usuario ja conhecido": decide quem recebe historico.
# ---------------------------------------------------------------------- #

def registrar_login_e_verificar_se_conhecido(caminho: str, usuario: str) -> bool:
    """
    Chamada uma vez, logo apos um login ser aceito. Retorna:
      - True  se esse apelido JA tinha se conectado alguma vez antes (ou
              seja, e um usuario "conhecido" -- deve receber historico);
      - False se essa e a PRIMEIRA vez que esse apelido conecta (usuario
              novo -- nao deve receber nenhum historico agora).

    Em qualquer um dos dois casos, garante que o apelido fique registrado
    em `usuarios_conhecidos` a partir de agora, para que da proxima vez
    que alguem conectar com esse mesmo apelido a resposta seja True.
    """
    agora = datetime.now(timezone.utc).isoformat()
    with _TRAVA, sqlite3.connect(caminho) as conexao:
        linha = conexao.execute(
            "SELECT 1 FROM usuarios_conhecidos WHERE usuario = ?", (usuario,)
        ).fetchone()
        if linha is not None:
            return True
        conexao.execute(
            "INSERT INTO usuarios_conhecidos (usuario, primeiro_login) VALUES (?, ?)",
            (usuario, agora),
        )
        return False


# ---------------------------------------------------------------------- #
# Mensagens PRIVADAS: historico completo, reenviado uma vez apos o login.
# ---------------------------------------------------------------------- #

def salvar_mensagem_privada(caminho: str, remetente: str, destinatario: str, texto: str) -> None:
    """Grava uma mensagem PRIVADA na tabela de historico."""
    with _TRAVA, sqlite3.connect(caminho) as conexao:
        conexao.execute(
            "INSERT INTO mensagens (tipo, remetente, destinatario, texto, quando, sala) "
            "VALUES ('PRIVADA', ?, ?, ?, ?, NULL)",
            (remetente, destinatario, texto, datetime.now(timezone.utc).isoformat()),
        )


def buscar_privadas(caminho: str, usuario: str, limite: int = 30) -> list:
    """
    Retorna, em ordem cronologica (mais antiga primeiro), as ultimas
    `limite` mensagens PRIVADAS que esse usuario enviou ou recebeu (de
    qualquer conversa).
    """
    with _TRAVA, sqlite3.connect(caminho) as conexao:
        linhas = conexao.execute(
            """
            SELECT remetente, destinatario, texto, quando
            FROM mensagens
            WHERE tipo = 'PRIVADA' AND (remetente = ? OR destinatario = ?)
            ORDER BY id DESC
            LIMIT ?
            """,
            (usuario, usuario, limite),
        ).fetchall()

    linhas.reverse()
    return [
        {"tipo": "PRIVADA", "de": remetente, "destino": destinatario, "texto": texto, "quando": quando}
        for remetente, destinatario, texto, quando in linhas
    ]


# ---------------------------------------------------------------------- #
# Mensagens GERAIS (broadcast): so o que foi perdido desde a ultima saida.
# ---------------------------------------------------------------------- #

def salvar_mensagem_geral(caminho: str, remetente: str, sala: str, texto: str) -> None:
    """Grava uma mensagem GERAL (broadcast) de uma sala na tabela de
    historico, para poder ser recuperada por quem sair e voltar depois."""
    with _TRAVA, sqlite3.connect(caminho) as conexao:
        conexao.execute(
            "INSERT INTO mensagens (tipo, remetente, destinatario, texto, quando, sala) "
            "VALUES ('MSG', ?, NULL, ?, ?, ?)",
            (remetente, texto, datetime.now(timezone.utc).isoformat(), sala),
        )


def registrar_saida_sala(caminho: str, usuario: str, sala: str) -> None:
    """Marca "agora" como o momento em que `usuario` saiu de `sala` (troca
    de sala ou desconexao). Usado depois, quando ele voltar, para saber a
    partir de quando reenviar as mensagens gerais que ele perdeu."""
    agora = datetime.now(timezone.utc).isoformat()
    with _TRAVA, sqlite3.connect(caminho) as conexao:
        conexao.execute(
            "INSERT INTO ultima_saida_sala (usuario, sala, quando) VALUES (?, ?, ?) "
            "ON CONFLICT (usuario, sala) DO UPDATE SET quando = excluded.quando",
            (usuario, sala, agora),
        )


def buscar_gerais_perdidas(caminho: str, usuario: str, sala: str, limite: int = 100) -> list:
    """
    Ao (re)entrar numa sala, retorna as mensagens gerais daquela sala
    enviadas DEPOIS da ultima vez que `usuario` saiu dela (ver
    `registrar_saida_sala`). Se ele nunca esteve nessa sala antes (nenhum
    registro de saida), retorna lista vazia -- um usuario novo na sala nao
    recebe conversa antiga, so o que acontecer dali em diante, ao vivo.
    """
    with _TRAVA, sqlite3.connect(caminho) as conexao:
        ultima_saida = conexao.execute(
            "SELECT quando FROM ultima_saida_sala WHERE usuario = ? AND sala = ?",
            (usuario, sala),
        ).fetchone()

        if ultima_saida is None:
            return []

        linhas = conexao.execute(
            """
            SELECT remetente, texto, quando
            FROM mensagens
            WHERE tipo = 'MSG' AND sala = ? AND quando > ?
            ORDER BY id ASC
            LIMIT ?
            """,
            (sala, ultima_saida[0], limite),
        ).fetchall()

    return [{"tipo": "MSG", "de": remetente, "texto": texto, "quando": quando} for remetente, texto, quando in linhas]
