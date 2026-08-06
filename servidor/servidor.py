# servidor de chat cliente-servidor. aceita varios clientes via TCP,
# uma thread por cliente. roteia broadcast (por sala), privadas, salas
# e historico. uso: python3 servidor.py --host 0.0.0.0 --porta 5000 --banco chat.db

import argparse
import os
import signal
import socket
import sys
import threading
from datetime import datetime

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from comum import protocolo
import bancodedados

if sys.platform == "win32":
    # ctrl+break no windows nao vira KeyboardInterrupt sozinho.
    # precisa disso pra servidor_gui.py conseguir pedir encerramento controlado
    signal.signal(signal.SIGBREAK, signal.default_int_handler)


def log(msg: str) -> None:
    agora = datetime.now().strftime("%H:%M:%S")
    print(f"[{agora}] {msg}")


class ClienteConectado:
    # um cliente conectado: socket, apelido e sala atual

    def __init__(self, sock: socket.socket, endereco):
        self.sock = sock
        self.endereco = endereco
        self.usuario = None
        self.sala = protocolo.SALA_PADRAO
        self.leitor = protocolo.LeitorDeMensagens(sock)
        self.ativo = True


class ServidorChat:
    # guarda os clientes conectados e roteia as mensagens entre eles.
    # self.clientes e compartilhado entre threads, por isso o Lock

    def __init__(self, host: str, porta: int, caminho_banco: str):
        self.host = host
        self.porta = porta
        self.caminho_banco = caminho_banco
        self.clientes = {}  # usuario -> ClienteConectado
        self.trava = threading.Lock()
        self.socket_servidor = None

    def iniciar(self) -> None:
        bancodedados.inicializar_banco(self.caminho_banco)
        log(f"Banco de dados pronto em '{self.caminho_banco}' (historico de mensagens).")

        self.socket_servidor = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.socket_servidor.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            self.socket_servidor.bind((self.host, self.porta))
        except OSError as erro:
            log(f"ERRO ao vincular o servidor em {self.host}:{self.porta} -> {erro}")
            log("Verifique se a porta ja esta em uso ou se ha permissao de firewall.")
            sys.exit(1)

        self.socket_servidor.listen()
        # timeout no accept pra nao travar o ctrl+c no windows
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

    def _atender_cliente(self, sock: socket.socket, endereco) -> None:
        # roda numa thread propria por conexao
        cliente = ClienteConectado(sock, endereco)
        log(f"Nova conexao de {endereco[0]}:{endereco[1]}")

        try:
            if not self._processar_login(cliente):
                return

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
                    break

                self._rotear_mensagem(cliente, mensagem)
                if not cliente.ativo:
                    break

        finally:
            self._remover_cliente(cliente)

    def _processar_login(self, cliente: ClienteConectado) -> bool:
        # espera LOGIN como primeira mensagem, valida apelido e checa duplicidade
        try:
            mensagem = cliente.leitor.proxima_mensagem()
        except (ConnectionResetError, ConnectionAbortedError, OSError, ValueError):
            mensagem = None

        if not mensagem or mensagem.get("tipo") != "LOGIN":
            self._recusar_login(cliente, "Esperava-se mensagem LOGIN como primeira mensagem.")
            return False

        nome = str(mensagem.get("usuario", "")).strip()

        if not protocolo.validar_nome_usuario(nome):
            self._recusar_login(
                cliente,
                "Apelido invalido. Use um nome sem espacos, nao vazio, ate "
                f"{protocolo.TAMANHO_MAX_USUARIO} caracteres e que nao comece com '/'.",
            )
            return False

        with self.trava:
            if nome in self.clientes:
                self._recusar_login(cliente, f"O usuario '{nome}' ja tem uma sessao ativa agora.")
                return False
            cliente.usuario = nome
            self.clientes[nome] = cliente

        protocolo.enviar(cliente.sock, {"tipo": "LOGIN_OK", "usuario": nome})

        usuario_ja_conhecido = bancodedados.registrar_login_e_verificar_se_conhecido(self.caminho_banco, nome)
        if usuario_ja_conhecido:
            self._enviar_historico_privado(cliente)
            self._enviar_historico_geral(cliente)

        log(f"Usuario '{nome}' entrou ({cliente.endereco[0]}:{cliente.endereco[1]}).")
        return True

    def _enviar_historico_privado(self, cliente: ClienteConectado) -> None:
        historico = bancodedados.buscar_privadas(self.caminho_banco, cliente.usuario)
        if historico:
            protocolo.enviar(cliente.sock, {"tipo": "HISTORICO", "mensagens": historico})

    def _enviar_historico_geral(self, cliente: ClienteConectado) -> None:
        # so manda o que foi perdido desde a ultima saida dessa sala
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

        elif tipo == "DIGITANDO":
            destino = mensagem.get("destino")
            if destino:
                self._notificar_digitando_privado(cliente, str(destino))
            else:
                self._notificar_digitando_sala(cliente)

        elif tipo == "SAIR":
            cliente.ativo = False

        else:
            protocolo.enviar(
                cliente.sock,
                {"tipo": "ERRO", "mensagem": f"Tipo de mensagem desconhecido: '{tipo}'."},
            )

    def _notificar_digitando_privado(self, cliente: ClienteConectado, destino: str) -> None:
        # efemero, nao salva no banco. se o destino sumiu, so ignora
        with self.trava:
            alvo = self.clientes.get(destino)
        if alvo is None:
            return
        try:
            protocolo.enviar(alvo.sock, {"tipo": "DIGITANDO", "de": cliente.usuario})
        except OSError:
            pass

    def _notificar_digitando_sala(self, cliente: ClienteConectado) -> None:
        with self.trava:
            destinatarios = [
                c for nome, c in self.clientes.items()
                if nome != cliente.usuario and c.sala == cliente.sala
            ]
        payload = {"tipo": "DIGITANDO", "de": cliente.usuario, "sala": cliente.sala}
        self._enviar_para_varios(destinatarios, payload)

    def _broadcast(self, cliente: ClienteConectado, texto: str) -> None:
        # log nao guarda o conteudo, so que uma mensagem foi enviada
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
        # so salas com gente conectada agora
        with self.trava:
            contagem = {}
            for c in self.clientes.values():
                contagem[c.sala] = contagem.get(c.sala, 0) + 1
        salas = [{"nome": nome, "usuarios": n} for nome, n in sorted(contagem.items())]
        protocolo.enviar(cliente.sock, {"tipo": "LISTA_SALAS", "salas": salas})

    def _entrar_sala(self, cliente: ClienteConectado, sala: str) -> None:
        # sala e auto-criada: o primeiro a entrar "cria" ela
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
                        f"Bem-vindo(a) ao chat! Voce esta na sala '{cliente.sala}'"
                    ),
                },
            )
        except OSError:
            pass

    def _remover_cliente(self, cliente: ClienteConectado) -> None:
        removido = False
        with self.trava:
            if cliente.usuario and self.clientes.get(cliente.usuario) is cliente:
                del self.clientes[cliente.usuario]
                removido = True
            destinatarios = [c for c in self.clientes.values() if c.sala == cliente.sala]

        if cliente.usuario:
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
                pass


def main():
    parser = argparse.ArgumentParser(description="Servidor de chat cliente-servidor (TCP).")
    parser.add_argument("--host", default="0.0.0.0", help="Endereco/interface em que o servidor vai escutar.")
    parser.add_argument("--porta", type=int, default=5000, help="Porta TCP em que o servidor vai escutar.")
    parser.add_argument("--banco", default="chat.db", help="Caminho do arquivo SQLite para o historico.")
    args = parser.parse_args()

    servidor = ServidorChat(host=args.host, porta=args.porta, caminho_banco=args.banco)
    servidor.iniciar()


if __name__ == "__main__":
    main()
