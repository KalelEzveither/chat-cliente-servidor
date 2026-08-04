# -*- coding: utf-8 -*-
"""
servidor/bancodedados.py

Camada de persistencia do servidor, usando SQLite (modulo `sqlite3` da
biblioteca padrao do Python -- nao precisa instalar nada).

Implementa tres requisitos opcionais do trabalho:
  1. "Sistema de autenticacao com senha": tabela `usuarios`, com senha
     protegida por hash + sal (nunca em texto puro), e AUTO-REGISTRO no
     primeiro login com um apelido novo;
  2. "Persistencia do historico de mensagens em arquivo ou banco de dados":
     tabela `mensagens`. Duas categorias, com regras diferentes:
       - PRIVADAS: sempre entram no historico de quem enviou/recebeu,
         reenviadas uma unica vez logo apos o login (independem de sala);
       - GERAIS (broadcast): NAO reenviadas de uma vez so pra todo mundo
         que entra numa sala (isso inundaria um usuario novo com conversa
         antiga que nao diz respeito a ele). Em vez disso, usa-se um
         esquema de "ultima vez visto": a tabela `ultima_saida_sala` marca
         quando cada usuario saiu de cada sala pela ultima vez (troca de
         sala ou desconexao); ao (re)entrar numa sala, o servidor manda so
         as mensagens gerais daquela sala enviadas DEPOIS desse momento.
         Quem nunca esteve numa sala antes (sem registro de saida) nao
         recebe nada -- so passa a ver as mensagens dali em diante, ao
         vivo.
  3. "Criacao de salas/canais tematicos": ver `servidor/servidor.py`
     (roteamento de broadcast/lista por sala).

Sincronizacao: cada funcao abre e fecha sua propria conexao sqlite3 (o
arquivo de banco e local, em disco). Um Lock global (`_TRAVA`) serializa o
acesso, ja que o SQLite permite varias leituras simultaneas mas apenas uma
escrita por vez -- sem o lock, threads concorrentes de clientes diferentes
poderiam esbarrar em erros de "database is locked".
"""

import hashlib
import secrets
import sqlite3
import threading
from datetime import datetime, timezone

_TRAVA = threading.Lock()

_SQL_CRIAR_TABELAS = """
CREATE TABLE IF NOT EXISTS usuarios (
    usuario     TEXT PRIMARY KEY,
    sal         TEXT NOT NULL,
    hash_senha  TEXT NOT NULL,
    criado_em   TEXT NOT NULL
);

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
"""

# Numero de iteracoes do PBKDF2: alto o suficiente para dificultar ataque de
# forca bruta offline, mas rapido o bastante para nao atrasar o login.
_ITERACOES_PBKDF2 = 100_000


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


def _gerar_hash(senha: str, sal: bytes) -> str:
    """Deriva o hash de uma senha usando PBKDF2-HMAC-SHA256 com sal."""
    derivado = hashlib.pbkdf2_hmac("sha256", senha.encode("utf-8"), sal, _ITERACOES_PBKDF2)
    return derivado.hex()


def autenticar_ou_registrar(caminho: str, usuario: str, senha: str):
    """
    Autentica um usuario existente, ou cadastra automaticamente um usuario
    novo com a senha informada (auto-registro no primeiro login).

    Retorna uma tupla (sucesso: bool, motivo: str | None). `motivo` so vem
    preenchido quando sucesso e False, para ser exibido ao usuario.
    """
    with _TRAVA, sqlite3.connect(caminho) as conexao:
        linha = conexao.execute(
            "SELECT sal, hash_senha FROM usuarios WHERE usuario = ?", (usuario,)
        ).fetchone()

        if linha is None:
            # Apelido nunca visto antes: cadastra a senha informada agora.
            sal = secrets.token_bytes(16)
            hash_senha = _gerar_hash(senha, sal)
            conexao.execute(
                "INSERT INTO usuarios (usuario, sal, hash_senha, criado_em) VALUES (?, ?, ?, ?)",
                (usuario, sal.hex(), hash_senha, datetime.now(timezone.utc).isoformat()),
            )
            return True, None

        sal_hex, hash_esperado = linha
        hash_recebido = _gerar_hash(senha, bytes.fromhex(sal_hex))
        # Comparacao em tempo constante, para nao vazar informacao sobre a
        # senha correta atraves do tempo de resposta (timing attack).
        if not secrets.compare_digest(hash_recebido, hash_esperado):
            return False, "Senha incorreta para esse apelido."
        return True, None


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
