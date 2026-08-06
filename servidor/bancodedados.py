# persistencia do historico usando sqlite (sem dependencia externa).
#
# mensagens: tudo que foi mandado (geral e privada, ver coluna tipo)
# ultima_saida_sala: quando cada usuario saiu de cada sala pela ultima vez,
#   usado pra saber o que ele perdeu quando volta
# usuarios_conhecidos: quem ja logou aqui alguma vez. so quem ja e
#   conhecido recebe historico ao logar de novo
#
# nao ha conta/senha, apelido e so identificacao (requisito do trabalho).
# usuarios_conhecidos nao e autenticacao, e so pra decidir se manda historico.
#
# cada funcao abre/fecha sua propria conexao. um Lock global serializa
# escrita porque sqlite so aceita uma escrita por vez.

import sqlite3
import threading
from datetime import datetime, timezone

_TRAVA = threading.Lock()

_SQL_CRIAR_TABELAS = """
CREATE TABLE IF NOT EXISTS mensagens (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    tipo         TEXT NOT NULL,
    remetente    TEXT NOT NULL,
    destinatario TEXT,
    texto        TEXT NOT NULL,
    quando       TEXT NOT NULL,
    sala         TEXT
);

CREATE TABLE IF NOT EXISTS ultima_saida_sala (
    usuario  TEXT NOT NULL,
    sala     TEXT NOT NULL,
    quando   TEXT NOT NULL,
    PRIMARY KEY (usuario, sala)
);

CREATE TABLE IF NOT EXISTS usuarios_conhecidos (
    usuario         TEXT PRIMARY KEY,
    primeiro_login  TEXT NOT NULL
);
"""


def inicializar_banco(caminho: str) -> None:
    with _TRAVA, sqlite3.connect(caminho) as conexao:
        conexao.executescript(_SQL_CRIAR_TABELAS)
        # migracao: banco antigo sem a coluna sala
        colunas = [linha[1] for linha in conexao.execute("PRAGMA table_info(mensagens)").fetchall()]
        if "sala" not in colunas:
            conexao.execute("ALTER TABLE mensagens ADD COLUMN sala TEXT")


def registrar_login_e_verificar_se_conhecido(caminho: str, usuario: str) -> bool:
    # retorna True se ja era conhecido (recebe historico). se for a
    # primeira vez, cadastra agora e retorna False (nao recebe nada)
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


def salvar_mensagem_privada(caminho: str, remetente: str, destinatario: str, texto: str) -> None:
    with _TRAVA, sqlite3.connect(caminho) as conexao:
        conexao.execute(
            "INSERT INTO mensagens (tipo, remetente, destinatario, texto, quando, sala) "
            "VALUES ('PRIVADA', ?, ?, ?, ?, NULL)",
            (remetente, destinatario, texto, datetime.now(timezone.utc).isoformat()),
        )


def buscar_privadas(caminho: str, usuario: str, limite: int = 30) -> list:
    # ultimas mensagens privadas enviadas ou recebidas por esse usuario,
    # mais antiga primeiro
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


def salvar_mensagem_geral(caminho: str, remetente: str, sala: str, texto: str) -> None:
    with _TRAVA, sqlite3.connect(caminho) as conexao:
        conexao.execute(
            "INSERT INTO mensagens (tipo, remetente, destinatario, texto, quando, sala) "
            "VALUES ('MSG', ?, NULL, ?, ?, ?)",
            (remetente, texto, datetime.now(timezone.utc).isoformat(), sala),
        )


def registrar_saida_sala(caminho: str, usuario: str, sala: str) -> None:
    # marca agora como o momento da saida, pra saber depois o que foi perdido
    agora = datetime.now(timezone.utc).isoformat()
    with _TRAVA, sqlite3.connect(caminho) as conexao:
        conexao.execute(
            "INSERT INTO ultima_saida_sala (usuario, sala, quando) VALUES (?, ?, ?) "
            "ON CONFLICT (usuario, sala) DO UPDATE SET quando = excluded.quando",
            (usuario, sala, agora),
        )


def buscar_gerais_perdidas(caminho: str, usuario: str, sala: str, limite: int = 100) -> list:
    # mensagens da sala enviadas depois da ultima saida do usuario.
    # se nunca esteve na sala (sem registro), retorna vazio
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
