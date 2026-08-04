# -*- coding: utf-8 -*-
"""
comum/protocolo.py

Define o protocolo de aplicacao usado na comunicacao entre cliente e servidor.

FORMATO DE SERIALIZACAO
------------------------
Cada mensagem trocada e um objeto JSON (texto), codificado em UTF-8, seguido
de um caractere de nova linha '\n'. O uso de '\n' como delimitador resolve o
problema de "fronteiras de mensagem" do TCP, que e um protocolo de fluxo de
bytes sem garantia de que um send() do lado do emissor corresponda a um unico
recv() do lado do receptor (mensagens podem chegar fragmentadas ou coladas).

Escolhemos JSON (em vez de um formato binario proprio) porque:
  - e legivel por humanos, o que facilita debug e demonstracao em laboratorio;
  - e nativamente suportado pela biblioteca padrao do Python (modulo json),
    sem dependencias externas;
  - e flexivel o suficiente para representar todos os tipos de mensagem do
    protocolo com um unico esquema (campo "tipo" + payload).

ESTRUTURA GERAL DE UMA MENSAGEM
--------------------------------
{
    "tipo": "<TIPO_DA_MENSAGEM>",
    ... campos especificos do tipo ...
}

TIPOS DE MENSAGEM (cliente -> servidor)
-----------------------------------------
LOGIN        {"tipo": "LOGIN", "usuario": "<nome>", "senha": "<senha>"}
    Enviado logo apos a conexao TCP ser estabelecida, para autenticacao.
    Sistema de autenticacao com AUTO-REGISTRO: se o apelido ainda nao existe
    no banco de dados do servidor, a senha informada e cadastrada na hora
    (primeiro acesso = cadastro); se o apelido ja existe, a senha precisa
    bater com a que foi cadastrada da primeira vez, senao o login e
    recusado (LOGIN_ERRO). As senhas nunca sao guardadas em texto puro no
    servidor (ver servidor/bancodedados.py: hash PBKDF2-HMAC-SHA256 + sal).

MSG          {"tipo": "MSG", "texto": "<conteudo>"}
    Mensagem de broadcast: sera repassada pelo servidor a todos os demais
    clientes que estiverem na MESMA SALA de quem enviou (exceto quem
    enviou, que ja ecoa localmente). Toda conexao comeca na sala padrao
    "geral" (ver SALA_PADRAO) e muda de sala com ENTRAR_SALA. E persistida
    no banco de dados para poder ser recuperada depois como HISTORICO por
    quem ja esteve naquela sala (ver HISTORICO).

PRIVADA      {"tipo": "PRIVADA", "destino": "<usuario>", "texto": "<conteudo>"}
    Mensagem privada endereca a um unico usuario (comando /msg no cliente).
    Independe de sala: chega ao destinatario mesmo que ele esteja em uma
    sala diferente da de quem enviou.

LISTAR       {"tipo": "LISTAR"}
    Solicita ao servidor a lista de usuarios conectados NA MESMA SALA do
    solicitante no momento (comando /lista no cliente).

ENTRAR_SALA  {"tipo": "ENTRAR_SALA", "sala": "<nome>"}
    Pede para trocar da sala atual para a sala indicada (comando /entrar
    no cliente). Assim como o apelido, a sala usa AUTO-CRIACAO: se a sala
    informada nunca foi usada antes, ela passa a existir a partir desse
    momento (nao ha uma lista fixa de salas pre-cadastradas). O cliente
    sai da sala anterior (os demais membros dela recebem SAIU, e o
    servidor marca esse momento como a "ultima saida" do cliente daquela
    sala) e entra na nova (os demais membros dela recebem ENTROU). Em
    seguida, recebe um HISTORICO com as mensagens gerais da nova sala que
    ele perdeu desde a ultima vez que esteve nela (nada, se for a primeira
    vez).

LISTAR_SALAS {"tipo": "LISTAR_SALAS"}
    Solicita ao servidor a lista de salas atualmente com pelo menos um
    usuario conectado, e quantos usuarios ha em cada uma (comando /salas
    no cliente).

SAIR         {"tipo": "SAIR"}
    Informa ao servidor que o cliente deseja encerrar a conexao de forma
    controlada (comando /sair no cliente).

TIPOS DE MENSAGEM (servidor -> cliente)
-----------------------------------------
LOGIN_OK     {"tipo": "LOGIN_OK", "usuario": "<nome>"}
    Confirma que o apelido foi aceito. Logo apos, o cliente e colocado na
    sala padrao "geral" (ver SALA_PADRAO) e pode receber ate dois
    HISTORICO em seguida: o de mensagens privadas, e o de mensagens gerais
    perdidas na sala "geral" (ver HISTORICO).

LOGIN_ERRO   {"tipo": "LOGIN_ERRO", "motivo": "<mensagem>"}
    Apelido invalido, senha incorreta para um apelido ja cadastrado, ou
    apelido com uma sessao ja ativa no momento; a conexao e encerrada apos
    o envio.

HISTORICO    {"tipo": "HISTORICO", "sala": "<nome>" (OPCIONAL), "mensagens": [
                 {"tipo": "PRIVADA"|"MSG", "de": "<usuario>",
                  "destino": "<usuario>" (so em PRIVADA),
                  "texto": "<conteudo>", "quando": "<timestamp ISO-8601>"},
                 ... ]}
    Ha dois tipos de HISTORICO, diferenciados pela presenca do campo
    "sala":
      - SEM "sala": historico de mensagens PRIVADAS (mensagens tipo
        PRIVADA) que o usuario enviou ou recebeu. Enviado uma unica vez,
        logo apos o LOGIN_OK.
      - COM "sala": mensagens GERAIS (tipo MSG) daquela sala que o usuario
        perdeu desde a ULTIMA VEZ que esteve nela (troca de sala ou
        desconexao) -- ver ENTRAR_SALA. Enviado ao entrar numa sala
        (login inicial ou ENTRAR_SALA), mas SO se o usuario ja tiver
        estado nela antes; quem entra pela primeira vez numa sala nao
        recebe HISTORICO nenhum dela, so passa a ver as mensagens dali em
        diante, ao vivo.
    Em ambos os casos, se nao houver nada a mostrar, nenhum HISTORICO e
    enviado (a lista "mensagens" nunca vem vazia).

MSG          {"tipo": "MSG", "de": "<usuario>", "sala": "<nome>", "texto": "<conteudo>"}
    Mensagem de broadcast recebida de outro usuario da mesma sala.

PRIVADA      {"tipo": "PRIVADA", "de": "<usuario>", "texto": "<conteudo>"}
    Mensagem privada recebida de outro usuario.

LISTA        {"tipo": "LISTA", "sala": "<nome>", "usuarios": ["<nome1>", ...]}
    Resposta ao comando LISTAR: usuarios conectados na sala indicada.

LISTA_SALAS  {"tipo": "LISTA_SALAS", "salas": [ {"nome": "<nome>",
                 "usuarios": <quantidade>}, ... ]}
    Resposta ao comando LISTAR_SALAS.

SALA_OK      {"tipo": "SALA_OK", "sala": "<nome>"}
    Confirma que o cliente agora esta na sala indicada (resposta a
    ENTRAR_SALA, ou enviado implicitamente ao entrar na sala padrao
    apos o login).

SALA_ERRO    {"tipo": "SALA_ERRO", "motivo": "<mensagem>"}
    Nome de sala invalido em um pedido de ENTRAR_SALA; o cliente permanece
    na sala em que estava.

ENTROU       {"tipo": "ENTROU", "usuario": "<nome>", "sala": "<nome>"}
    Notificacao, para os demais membros da sala, de que um usuario entrou
    nela (broadcast automatico ao logar ou ao trocar de sala).

SAIU         {"tipo": "SAIU", "usuario": "<nome>", "sala": "<nome>"}
    Notificacao, para os demais membros da sala, de que um usuario saiu
    dela (broadcast automatico ao trocar de sala ou ao desconectar).

ERRO         {"tipo": "ERRO", "mensagem": "<descricao>"}
    Erro generico (ex.: destinatario de mensagem privada nao encontrado,
    comando desconhecido, JSON malformado).

SISTEMA      {"tipo": "SISTEMA", "mensagem": "<texto>"}
    Mensagem informativa do servidor (ex.: boas-vindas, ajuda).
"""

import json
import socket
from datetime import datetime

# Delimitador de mensagens no fluxo de bytes do TCP.
DELIMITADOR = "\n"
CODIFICACAO = "utf-8"

# Tamanho maximo aceito para um nome de usuario.
TAMANHO_MAX_USUARIO = 32
# Tamanho maximo aceito para o corpo de uma mensagem de texto.
TAMANHO_MAX_TEXTO = 2000
# Tamanho minimo/maximo aceito para uma senha.
TAMANHO_MIN_SENHA = 4
TAMANHO_MAX_SENHA = 64
# Tamanho maximo aceito para um nome de sala/canal.
TAMANHO_MAX_SALA = 32
# Sala em que todo cliente e colocado automaticamente ao logar.
SALA_PADRAO = "geral"


def empacotar(mensagem: dict) -> bytes:
    """Serializa um dicionario Python em bytes prontos para envio via socket."""
    texto_json = json.dumps(mensagem, ensure_ascii=False)
    return (texto_json + DELIMITADOR).encode(CODIFICACAO)


def enviar(sock: socket.socket, mensagem: dict) -> None:
    """Envia um dicionario como mensagem do protocolo por um socket TCP."""
    sock.sendall(empacotar(mensagem))


class LeitorDeMensagens:
    """
    Envolve um socket TCP e resolve o problema de fragmentacao/agrupamento de
    mensagens do fluxo de bytes, entregando um dicionario JSON completo por
    chamada de `proxima_mensagem()`.

    Mantem um buffer interno; a cada recv(), procura pelo delimitador '\n'
    para extrair mensagens completas, mesmo que o TCP tenha entregado varias
    mensagens juntas em uma unica leitura, ou apenas um pedaco de uma
    mensagem maior.
    """

    def __init__(self, sock: socket.socket, tamanho_buffer: int = 4096):
        self._sock = sock
        self._tamanho_buffer = tamanho_buffer
        self._buffer = ""

    def proxima_mensagem(self):
        """
        Retorna o proximo dicionario de mensagem recebido, ou None se a
        conexao foi fechada pelo lado remoto.
        Lanca ValueError se os dados recebidos nao forem JSON valido.
        """
        while DELIMITADOR not in self._buffer:
            dados = self._sock.recv(self._tamanho_buffer)
            if not dados:
                return None  # conexao encerrada
            self._buffer += dados.decode(CODIFICACAO, errors="replace")

        linha, self._buffer = self._buffer.split(DELIMITADOR, 1)
        linha = linha.strip()
        if not linha:
            return self.proxima_mensagem()
        dados = json.loads(linha)
        if not isinstance(dados, dict):
            # JSON sintaticamente valido (ex.: uma lista ou um numero), mas
            # fora do formato esperado (objeto com campo "tipo"). Tratado
            # como mensagem malformada, igual a um erro de sintaxe JSON.
            raise ValueError("Mensagem JSON precisa ser um objeto, nao "
                              f"'{type(dados).__name__}'.")
        return dados


def _identificador_valido(valor: str, tamanho_max: int) -> bool:
    """Regra comum de validacao para apelidos e nomes de sala: nao vazio,
    sem espacos, dentro do tamanho maximo e que nao comece com '/' (para
    nao ser confundido com um comando do cliente)."""
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
    """Valida se um apelido e aceitavel: nao vazio, sem espacos, tamanho ok."""
    return _identificador_valido(nome, TAMANHO_MAX_USUARIO)


def validar_nome_sala(nome: str) -> bool:
    """Valida se um nome de sala/canal e aceitavel (mesma regra do apelido)."""
    return _identificador_valido(nome, TAMANHO_MAX_SALA)


def validar_senha(senha: str) -> bool:
    """Valida se uma senha e aceitavel: nao vazia e dentro do tamanho permitido."""
    if not senha:
        return False
    if len(senha) < TAMANHO_MIN_SENHA or len(senha) > TAMANHO_MAX_SENHA:
        return False
    return True


def formatar_quando(timestamp_iso: str) -> str:
    """
    Converte um timestamp ISO-8601 (como os gravados no historico do banco
    de dados, em UTC) para uma string curta e amigavel no horario local do
    cliente, ex.: '04/08 13:25'. Usado pelos clientes ao exibir o HISTORICO.
    """
    try:
        momento = datetime.fromisoformat(timestamp_iso)
        if momento.tzinfo is not None:
            momento = momento.astimezone()  # converte de UTC para o horario local
        return momento.strftime("%d/%m %H:%M")
    except (ValueError, TypeError):
        return timestamp_iso or ""
