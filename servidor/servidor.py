# -*- coding: utf-8 -*-
"""
servidor/servidor.py

Servidor de chat cliente-servidor (Trabalho Pratico - Redes de Computadores 2).

Responsabilidades do servidor:
  - Aceitar conexoes TCP de multiplos clientes simultaneamente (uma thread
    por cliente conectado);
  - Autenticar usuarios por apelido + senha, com auto-registro no primeiro
    login (ver servidor/bancodedados.py), e apenas uma sessao ativa por vez
    por apelido;
  - Rotear mensagens: broadcast por sala/canal, mensagens privadas, listagem
    de usuarios conectados (por sala) e notificacoes de entrada/saida;
  - Gerenciar salas/canais tematicos: todo cliente comeca na sala "geral" e
    pode trocar de sala a qualquer momento (comando /entrar), com as salas
    sendo criadas automaticamente pelo primeiro usuario que entrar nelas;
  - Persistir o historico de mensagens em um banco de dados SQLite: as
    PRIVADAS sao sempre reenviadas ao usuario logo apos o login; as GERAIS
    (broadcast) so sao reenviadas, ao entrar numa sala, se o usuario ja
    tiver estado naquela sala antes -- e so as que ele perdeu desde entao
    (ver servidor/bancodedados.py);
  - Encerrar conexoes de forma controlada.

Uso:
    python3 servidor.py [--host 0.0.0.0] [--porta 5000] [--banco chat.db]

O endereco/porta NAO sao fixos no codigo (requisito do trabalho): podem ser
configurados via argumentos de linha de comando, e por padrao o servidor
escuta em 0.0.0.0 (todas as interfaces de rede da maquina), o que permite
que ele seja acessado por outras maquinas do laboratorio a partir do IP real
da maquina servidora.
"""

import argparse
import os
import signal
import socket
import sys
import threading
from datetime import datetime

# Garante que a pasta raiz do projeto (que contem o pacote `comum`) esteja no
# path, independente de onde o script for executado.
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from comum import protocolo
import bancodedados  # modulo servidor/bancodedados.py (mesma pasta deste arquivo)

if sys.platform == "win32":
    # No Windows, Ctrl+C (SIGINT) ja vira KeyboardInterrupt por padrao, mas
    # Ctrl+Break (SIGBREAK) nao tem handler Python associado por padrao --
    # sem isso, um CTRL_BREAK_EVENT mata o processo direto (o Windows nunca
    # chega a levantar KeyboardInterrupt), o que impede o encerramento
    # controlado (aviso aos clientes, fechamento do banco etc.). Isso e
    # usado por servidor_gui.py para poder pedir um encerramento controlado
    # de fora, ja que so e possivel mandar CTRL_BREAK_EVENT (nao CTRL_C
    # normal) para um subprocesso a partir de outro processo no Windows.
    signal.signal(signal.SIGBREAK, signal.default_int_handler)


def log(msg: str) -> None:
    agora = datetime.now().strftime("%H:%M:%S")
    print(f"[{agora}] {msg}")


class ClienteConectado:
    """Representa um cliente conectado ao servidor, com seu socket, apelido
    e a sala/canal em que se encontra no momento."""

    def __init__(self, sock: socket.socket, endereco):
        self.sock = sock
        self.endereco = endereco
        self.usuario = None
        self.sala = protocolo.SALA_PADRAO
        self.leitor = protocolo.LeitorDeMensagens(sock)
        self.ativo = True


class ServidorChat:
    """
    Encapsula o estado do servidor: lista de clientes conectados, socket de
    escuta e a logica de roteamento de mensagens entre eles.

    Sincronizacao: como cada cliente e atendido por uma thread propria, o
    dicionario compartilhado de clientes conectados e protegido por um Lock
    para evitar condicoes de corrida (ex.: dois clientes fazendo login com o
    mesmo apelido ao mesmo tempo, ou um broadcast ocorrendo enquanto um
    cliente esta sendo removido da lista).
    """

    def __init__(self, host: str, porta: int, caminho_banco: str):
        self.host = host
        self.porta = porta
        self.caminho_banco = caminho_banco
        self.clientes = {}  # usuario (str) -> ClienteConectado
        self.trava = threading.Lock()
        self.socket_servidor = None

    # ------------------------------------------------------------------ #
    # Ciclo de vida do servidor
    # ------------------------------------------------------------------ #

    def iniciar(self) -> None:
        bancodedados.inicializar_banco(self.caminho_banco)
        log(f"Banco de dados pronto em '{self.caminho_banco}' (contas + historico de mensagens).")

        self.socket_servidor = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        # Permite reiniciar o servidor rapidamente na mesma porta (evita
        # "Address already in use" logo apos um encerramento anterior).
        self.socket_servidor.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            self.socket_servidor.bind((self.host, self.porta))
        except OSError as erro:
            log(f"ERRO ao vincular o servidor em {self.host}:{self.porta} -> {erro}")
            log("Verifique se a porta ja esta em uso ou se ha permissao de firewall.")
            sys.exit(1)

        self.socket_servidor.listen()
        # Timeout no accept(): sem isso, a thread principal fica bloqueada
        # indefinidamente dentro de uma chamada C, e o Windows em particular
        # pode nao entregar o KeyboardInterrupt (Ctrl+C) a tempo -- com o
        # timeout, o loop volta ao interpretador Python a cada 1s, momento
        # em que um Ctrl+C pendente e processado prontamente.
        self.socket_servidor.settimeout(1.0)
        log(f"Servidor de chat escutando em {self.host}:{self.porta}")
        log("Aguardando conexoes de clientes... (Ctrl+C para encerrar)")

        try:
            while True:
                try:
                    sock_cliente, endereco = self.socket_servidor.accept()
                except socket.timeout:
                    continue
                thread = threading.Thread(
                    target=self._atender_cliente,
                    args=(sock_cliente, endereco),
                    daemon=True,
                )
                thread.start()
        except KeyboardInterrupt:
            log("Encerramento solicitado pelo teclado (Ctrl+C).")
        finally:
            self._encerrar_servidor()

    def _encerrar_servidor(self) -> None:
        with self.trava:
            for cliente in list(self.clientes.values()):
                try:
                    protocolo.enviar(
                        cliente.sock,
                        {"tipo": "SISTEMA", "mensagem": "Servidor sendo encerrado."},
                    )
                    cliente.sock.close()
                except OSError:
                    pass
            self.clientes.clear()
        if self.socket_servidor:
            self.socket_servidor.close()
        log("Servidor encerrado.")

    # ------------------------------------------------------------------ #
    # Tratamento de cada cliente (uma thread por cliente)
    # ------------------------------------------------------------------ #

    def _atender_cliente(self, sock: socket.socket, endereco) -> None:
        cliente = ClienteConectado(sock, endereco)
        log(f"Nova conexao de {endereco[0]}:{endereco[1]}")

        try:
            if not self._processar_login(cliente):
                return  # login falhou; socket ja foi fechado em _processar_login

            self._notificar_entrada(cliente)

            while cliente.ativo:
                try:
                    mensagem = cliente.leitor.proxima_mensagem()
                except (ConnectionResetError, ConnectionAbortedError, OSError):
                    break
                except ValueError:
                    protocolo.enviar(
                        cliente.sock,
                        {"tipo": "ERRO", "mensagem": "JSON malformado recebido."},
                    )
                    continue

                if mensagem is None:
                    break  # cliente fechou a conexao abruptamente

                self._rotear_mensagem(cliente, mensagem)
                if not cliente.ativo:
                    break

        finally:
            self._remover_cliente(cliente)

    def _processar_login(self, cliente: ClienteConectado) -> bool:
        """Le a mensagem LOGIN inicial, valida o apelido e autentica a senha
        (com auto-registro no banco de dados, caso o apelido seja novo)."""
        try:
            mensagem = cliente.leitor.proxima_mensagem()
        except (ConnectionResetError, ConnectionAbortedError, OSError, ValueError):
            mensagem = None

        if not mensagem or mensagem.get("tipo") != "LOGIN":
            self._recusar_login(cliente, "Esperava-se mensagem LOGIN como primeira mensagem.")
            return False

        nome = str(mensagem.get("usuario", "")).strip()
        senha = str(mensagem.get("senha", ""))

        if not protocolo.validar_nome_usuario(nome):
            self._recusar_login(
                cliente,
                "Apelido invalido. Use um nome sem espacos, nao vazio, ate "
                f"{protocolo.TAMANHO_MAX_USUARIO} caracteres e que nao comece com '/'.",
            )
            return False

        if not protocolo.validar_senha(senha):
            self._recusar_login(
                cliente,
                f"Senha invalida. Use entre {protocolo.TAMANHO_MIN_SENHA} e "
                f"{protocolo.TAMANHO_MAX_SENHA} caracteres.",
            )
            return False

        # Autenticacao contra o banco de dados: se o apelido ja existe, a
        # senha precisa bater; se nao existe, e cadastrado agora (auto-registro).
        autenticado, motivo = bancodedados.autenticar_ou_registrar(self.caminho_banco, nome, senha)
        if not autenticado:
            self._recusar_login(cliente, motivo)
            return False

        with self.trava:
            if nome in self.clientes:
                self._recusar_login(cliente, f"O usuario '{nome}' ja tem uma sessao ativa agora.")
                return False
            cliente.usuario = nome
            self.clientes[nome] = cliente

        protocolo.enviar(cliente.sock, {"tipo": "LOGIN_OK", "usuario": nome})
        self._enviar_historico_privado(cliente)
        self._enviar_historico_geral(cliente)
        log(f"Usuario '{nome}' autenticado ({cliente.endereco[0]}:{cliente.endereco[1]}).")
        return True

    def _enviar_historico_privado(self, cliente: ClienteConectado) -> None:
        """Envia ao cliente, logo apos o login, o historico de mensagens
        PRIVADAS que ele enviou ou recebeu (independe de sala)."""
        historico = bancodedados.buscar_privadas(self.caminho_banco, cliente.usuario)
        if historico:
            protocolo.enviar(cliente.sock, {"tipo": "HISTORICO", "mensagens": historico})

    def _enviar_historico_geral(self, cliente: ClienteConectado) -> None:
        """Envia ao cliente, ao entrar numa sala (login ou ENTRAR_SALA), as
        mensagens gerais daquela sala que ele perdeu desde a ultima vez que
        esteve nela (ver bancodedados.registrar_saida_sala/
        buscar_gerais_perdidas). Quem nunca esteve na sala nao recebe nada
        -- so passa a ver as mensagens dali em diante, ao vivo."""
        perdidas = bancodedados.buscar_gerais_perdidas(self.caminho_banco, cliente.usuario, cliente.sala)
        if perdidas:
            protocolo.enviar(cliente.sock, {"tipo": "HISTORICO", "sala": cliente.sala, "mensagens": perdidas})

    def _recusar_login(self, cliente: ClienteConectado, motivo: str) -> None:
        try:
            protocolo.enviar(cliente.sock, {"tipo": "LOGIN_ERRO", "motivo": motivo})
        except OSError:
            pass
        finally:
            cliente.sock.close()

    # ------------------------------------------------------------------ #
    # Roteamento de mensagens apos login
    # ------------------------------------------------------------------ #

    def _rotear_mensagem(self, cliente: ClienteConectado, mensagem: dict) -> None:
        tipo = mensagem.get("tipo")

        if tipo == "MSG":
            texto = str(mensagem.get("texto", ""))[: protocolo.TAMANHO_MAX_TEXTO]
            self._broadcast(cliente, texto)

        elif tipo == "PRIVADA":
            destino = str(mensagem.get("destino", ""))
            texto = str(mensagem.get("texto", ""))[: protocolo.TAMANHO_MAX_TEXTO]
            self._enviar_privada(cliente, destino, texto)

        elif tipo == "LISTAR":
            self._enviar_lista(cliente)

        elif tipo == "ENTRAR_SALA":
            sala = str(mensagem.get("sala", ""))
            self._entrar_sala(cliente, sala)

        elif tipo == "LISTAR_SALAS":
            self._enviar_lista_salas(cliente)

        elif tipo == "SAIR":
            cliente.ativo = False

        else:
            protocolo.enviar(
                cliente.sock,
                {"tipo": "ERRO", "mensagem": f"Tipo de mensagem desconhecido: '{tipo}'."},
            )

    def _broadcast(self, cliente: ClienteConectado, texto: str) -> None:
        # O CONTEUDO da mensagem nao e logado no servidor (privacidade): o
        # log so registra que uma mensagem foi enviada, por quem e em qual
        # sala. O texto em si so aparece na tela dos clientes.
        log(f"[{cliente.sala}] {cliente.usuario} enviou uma mensagem para a sala.")
        bancodedados.salvar_mensagem_geral(self.caminho_banco, cliente.usuario, cliente.sala, texto)
        payload = {"tipo": "MSG", "de": cliente.usuario, "sala": cliente.sala, "texto": texto}
        with self.trava:
            destinatarios = [
                c for nome, c in self.clientes.items()
                if nome != cliente.usuario and c.sala == cliente.sala
            ]
        self._enviar_para_varios(destinatarios, payload)

    def _enviar_privada(self, cliente: ClienteConectado, destino: str, texto: str) -> None:
        with self.trava:
            alvo = self.clientes.get(destino)
        if alvo is None:
            protocolo.enviar(
                cliente.sock,
                {"tipo": "ERRO", "mensagem": f"Usuario '{destino}' nao encontrado ou offline."},
            )
            return
        # Idem: so registra QUE uma privada foi enviada e entre quem, nunca o
        # conteudo (isso e assunto exclusivo dos dois clientes envolvidos).
        log(f"[PRIVADA] {cliente.usuario} -> {destino} (mensagem privada enviada).")
        bancodedados.salvar_mensagem_privada(self.caminho_banco, cliente.usuario, destino, texto)
        try:
            protocolo.enviar(alvo.sock, {"tipo": "PRIVADA", "de": cliente.usuario, "texto": texto})
        except OSError:
            protocolo.enviar(
                cliente.sock,
                {"tipo": "ERRO", "mensagem": f"Falha ao entregar mensagem para '{destino}'."},
            )

    def _enviar_lista(self, cliente: ClienteConectado) -> None:
        with self.trava:
            usuarios = sorted(nome for nome, c in self.clientes.items() if c.sala == cliente.sala)
        protocolo.enviar(cliente.sock, {"tipo": "LISTA", "sala": cliente.sala, "usuarios": usuarios})

    def _enviar_lista_salas(self, cliente: ClienteConectado) -> None:
        """Lista as salas que tem pelo menos um usuario conectado agora, com
        a contagem de usuarios em cada uma (salas sem ninguem conectado nao
        aparecem, mas continuam existindo em termos de historico salvo, e
        voltam a aparecer assim que alguem entrar nelas de novo)."""
        with self.trava:
            contagem = {}
            for c in self.clientes.values():
                contagem[c.sala] = contagem.get(c.sala, 0) + 1
        salas = [{"nome": nome, "usuarios": n} for nome, n in sorted(contagem.items())]
        protocolo.enviar(cliente.sock, {"tipo": "LISTA_SALAS", "salas": salas})

    def _entrar_sala(self, cliente: ClienteConectado, sala: str) -> None:
        """Move o cliente da sala atual para a sala pedida. Assim como o
        apelido, a sala usa auto-criacao: nao precisa existir previamente,
        basta ser um nome valido -- o primeiro a entrar "cria" a sala."""
        if not protocolo.validar_nome_sala(sala):
            protocolo.enviar(
                cliente.sock,
                {
                    "tipo": "SALA_ERRO",
                    "motivo": "Nome de sala invalido. Use um nome sem espacos, nao vazio, ate "
                    f"{protocolo.TAMANHO_MAX_SALA} caracteres e que nao comece com '/'.",
                },
            )
            return

        sala_antiga = cliente.sala
        if sala == sala_antiga:
            protocolo.enviar(cliente.sock, {"tipo": "SALA_OK", "sala": sala})
            return

        # Marca "agora" como o momento em que o cliente saiu da sala antiga,
        # para que, se ele voltar a ela depois, saibamos a partir de onde
        # reenviar as mensagens gerais que ele perdeu enquanto esteve fora.
        bancodedados.registrar_saida_sala(self.caminho_banco, cliente.usuario, sala_antiga)

        with self.trava:
            destinatarios_antiga = [
                c for nome, c in self.clientes.items()
                if nome != cliente.usuario and c.sala == sala_antiga
            ]
            cliente.sala = sala
            destinatarios_nova = [
                c for nome, c in self.clientes.items()
                if nome != cliente.usuario and c.sala == sala
            ]

        log(f"'{cliente.usuario}' saiu da sala '{sala_antiga}' e entrou na sala '{sala}'.")
        self._enviar_para_varios(destinatarios_antiga, {"tipo": "SAIU", "usuario": cliente.usuario, "sala": sala_antiga})
        self._enviar_para_varios(destinatarios_nova, {"tipo": "ENTROU", "usuario": cliente.usuario, "sala": sala})
        protocolo.enviar(cliente.sock, {"tipo": "SALA_OK", "sala": sala})
        self._enviar_historico_geral(cliente)

    def _notificar_entrada(self, cliente: ClienteConectado) -> None:
        log(f"'{cliente.usuario}' entrou na sala '{cliente.sala}'.")
        payload = {"tipo": "ENTROU", "usuario": cliente.usuario, "sala": cliente.sala}
        with self.trava:
            destinatarios = [
                c for nome, c in self.clientes.items()
                if nome != cliente.usuario and c.sala == cliente.sala
            ]
        self._enviar_para_varios(destinatarios, payload)
        try:
            protocolo.enviar(
                cliente.sock,
                {
                    "tipo": "SISTEMA",
                    "mensagem": (
                        f"Bem-vindo(a) ao chat! Voce esta na sala '{cliente.sala}'. Comandos disponiveis: "
                        "/lista, /msg <usuario> <mensagem>, /salas, /entrar <sala>, /sair"
                    ),
                },
            )
        except OSError:
            pass  # cliente ja desconectou entre o login e este envio; a limpeza ocorrera no loop principal

    def _remover_cliente(self, cliente: ClienteConectado) -> None:
        removido = False
        with self.trava:
            if cliente.usuario and self.clientes.get(cliente.usuario) is cliente:
                del self.clientes[cliente.usuario]
                removido = True
            destinatarios = [c for c in self.clientes.values() if c.sala == cliente.sala]

        if cliente.usuario:
            # Registra o momento da desconexao como "saida" da sala em que
            # estava, pelo mesmo motivo do ENTRAR_SALA: permitir reenviar,
            # numa proxima conexao, so as mensagens gerais perdidas.
            bancodedados.registrar_saida_sala(self.caminho_banco, cliente.usuario, cliente.sala)

        try:
            cliente.sock.close()
        except OSError:
            pass

        if removido:
            log(f"'{cliente.usuario}' saiu da sala '{cliente.sala}'.")
            payload = {"tipo": "SAIU", "usuario": cliente.usuario, "sala": cliente.sala}
            self._enviar_para_varios(destinatarios, payload)

    @staticmethod
    def _enviar_para_varios(clientes, payload: dict) -> None:
        for c in clientes:
            try:
                protocolo.enviar(c.sock, payload)
            except OSError:
                pass  # a limpeza da conexao morta ocorrera quando a thread dela detectar a falha


def main():
    parser = argparse.ArgumentParser(description="Servidor de chat cliente-servidor (TCP).")
    parser.add_argument(
        "--host",
        default="0.0.0.0",
        help="Endereco/interface em que o servidor vai escutar (padrao: 0.0.0.0, todas as interfaces).",
    )
    parser.add_argument(
        "--porta",
        type=int,
        default=5000,
        help="Porta TCP em que o servidor vai escutar (padrao: 5000).",
    )
    parser.add_argument(
        "--banco",
        default="chat.db",
        help="Caminho do arquivo SQLite para contas e historico de mensagens (padrao: chat.db).",
    )
    args = parser.parse_args()

    servidor = ServidorChat(host=args.host, porta=args.porta, caminho_banco=args.banco)
    servidor.iniciar()


if __name__ == "__main__":
    main()
