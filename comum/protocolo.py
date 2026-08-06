# protocolo de aplicacao do chat.
# cada mensagem e um JSON de uma linha, terminado em \n.
#
# cliente -> servidor:
#   LOGIN        {tipo, usuario}
#   MSG          {tipo, texto}                          -> broadcast na sala atual
#   PRIVADA      {tipo, destino, texto}
#   LISTAR       {tipo}                                 -> usuarios da sala atual
#   ENTRAR_SALA  {tipo, sala}                            -> troca de sala (cria se nao existe)
#   LISTAR_SALAS {tipo}
#   DIGITANDO    {tipo, destino?}                        -> destino ausente = aviso pra sala
#   SAIR         {tipo}
#
# servidor -> cliente:
#   LOGIN_OK     {tipo, usuario}
#   LOGIN_ERRO   {tipo, motivo}
#   HISTORICO    {tipo, sala?, mensagens}                -> com sala = geral perdida, sem sala = privadas
#   MSG          {tipo, de, sala, texto}
#   PRIVADA      {tipo, de, texto}
#   LISTA        {tipo, sala, usuarios}
#   LISTA_SALAS  {tipo, salas: [{nome, usuarios}]}
#   SALA_OK      {tipo, sala}
#   SALA_ERRO    {tipo, motivo}
#   ENTROU/SAIU  {tipo, usuario, sala}
#   DIGITANDO    {tipo, de, sala?}
#   ERRO         {tipo, mensagem}
#   SISTEMA      {tipo, mensagem}

import json
import socket
from datetime import datetime

DELIMITADOR = "\n"
CODIFICACAO = "utf-8"

TAMANHO_MAX_USUARIO = 32
TAMANHO_MAX_TEXTO = 2000
TAMANHO_MAX_SALA = 32
SALA_PADRAO = "geral"


def empacotar(mensagem: dict) -> bytes:
    # dict -> bytes prontos pra mandar no socket
    texto_json = json.dumps(mensagem, ensure_ascii=False)
    return (texto_json + DELIMITADOR).encode(CODIFICACAO)


def enviar(sock: socket.socket, mensagem: dict) -> None:
    sock.sendall(empacotar(mensagem))


class LeitorDeMensagens:
    # le do socket ate achar o \n e devolve o dict.
    # resolve o problema de o TCP poder juntar ou fatiar mensagens

    def __init__(self, sock: socket.socket, tamanho_buffer: int = 4096):
        self._sock = sock
        self._tamanho_buffer = tamanho_buffer
        self._buffer = ""

    def proxima_mensagem(self):
        # retorna None se a conexao fechou. lanca ValueError se nao for JSON valido
        while DELIMITADOR not in self._buffer:
            dados = self._sock.recv(self._tamanho_buffer)
            if not dados:
                return None
            self._buffer += dados.decode(CODIFICACAO, errors="replace")

        linha, self._buffer = self._buffer.split(DELIMITADOR, 1)
        linha = linha.strip()
        if not linha:
            return self.proxima_mensagem()
        dados = json.loads(linha)
        if not isinstance(dados, dict):
            raise ValueError(f"mensagem precisa ser um objeto JSON, veio '{type(dados).__name__}'")
        return dados


def _identificador_valido(valor: str, tamanho_max: int) -> bool:
    # regra usada tanto pra apelido quanto pra nome de sala
    if not valor:
        return False
    if len(valor) > tamanho_max:
        return False
    if any(c.isspace() for c in valor):
        return False
    if valor.startswith("/"):
        return False
    return True


def validar_nome_usuario(nome: str) -> bool:
    return _identificador_valido(nome, TAMANHO_MAX_USUARIO)


def validar_nome_sala(nome: str) -> bool:
    return _identificador_valido(nome, TAMANHO_MAX_SALA)


def formatar_quando(timestamp_iso: str) -> str:
    # timestamp ISO em UTC -> string curta no horario local, ex '04/08 13:25'
    try:
        momento = datetime.fromisoformat(timestamp_iso)
        if momento.tzinfo is not None:
            momento = momento.astimezone()
        return momento.strftime("%d/%m %H:%M")
    except (ValueError, TypeError):
        return timestamp_iso or ""
