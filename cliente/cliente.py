# -*- coding: utf-8 -*-
"""
cliente/cliente.py

Cliente de chat cliente-servidor (Trabalho Pratico - Redes de Computadores 2).

Responsabilidades do cliente:
  - Conectar-se ao servidor em um IP/porta configuraveis (nunca fixos em
    localhost/127.0.0.1 no codigo, conforme exigido pelo trabalho);
  - Autenticar-se com apelido + senha (primeiro login com um apelido novo
    cadastra a senha automaticamente no servidor);
  - Exibir o historico de mensagens anteriores enviado pelo servidor logo
    apos o login;
  - Enviar mensagens de broadcast (sala atual) e mensagens privadas;
  - Listar usuarios conectados na sala atual, e trocar de sala/canal;
  - Receber mensagens de outros usuarios em tempo real, em uma thread
    separada da thread que le a entrada do teclado (para nao bloquear a
    recepcao enquanto o usuario digita);
  - Encerrar a conexao de forma controlada.

Uso:
    python3 cliente.py --host <IP_DO_SERVIDOR> --porta <PORTA>

    Se --host/--porta nao forem passados, o cliente pergunta interativamente
    (nunca assume localhost por padrao), atendendo ao requisito de que o IP
    do servidor deve ser configuravel no dia do teste em laboratorio.

Comandos disponiveis apos conectar:
    <texto>                       envia mensagem para a sala atual (broadcast)
    /msg <usuario> <mensagem>     envia mensagem privada para um usuario
    /lista                        lista os usuarios conectados na sala atual
    /entrar <sala>                troca para outra sala/canal (cria se nao existir)
    /salas                        lista as salas ativas no momento
    /sair                         encerra a conexao de forma controlada
    /ajuda                        mostra novamente os comandos disponiveis
"""

import argparse
import getpass
import os
import socket
import sys
import threading

# Garante que a pasta raiz do projeto (que contem o pacote `comum`) esteja no
# path, independente de onde o script for executado.
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from comum import protocolo


AJUDA = """
Comandos disponiveis:
  <texto>                       envia mensagem para a sala atual
  /msg <usuario> <mensagem>     envia mensagem privada
  /lista                        lista usuarios conectados na sala atual
  /entrar <sala>                troca de sala/canal (cria se nao existir)
  /salas                        lista as salas ativas no momento
  /sair                         encerra a conexao
  /ajuda                        mostra esta ajuda novamente
"""


class ClienteChat:
    def __init__(self, host: str, porta: int, usuario: str, senha: str):
        self.host = host
        self.porta = porta
        self.usuario = usuario
        self.senha = senha
        self.sock = None
        self.leitor = None
        self.rodando = threading.Event()
        self.sala = protocolo.SALA_PADRAO
        self._saida_solicitada = False

    def conectar(self) -> bool:
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            self.sock.connect((self.host, self.porta))
        except (ConnectionRefusedError, socket.timeout, OSError) as erro:
            print(f"[ERRO] Nao foi possivel conectar a {self.host}:{self.porta} -> {erro}")
            return False

        self.leitor = protocolo.LeitorDeMensagens(self.sock)
        protocolo.enviar(
            self.sock, {"tipo": "LOGIN", "usuario": self.usuario, "senha": self.senha}
        )

        try:
            resposta = self.leitor.proxima_mensagem()
        except (ConnectionResetError, OSError, ValueError) as erro:
            print(f"[ERRO] Falha ao ler resposta de login -> {erro}")
            self.sock.close()
            return False

        if resposta is None:
            print("[ERRO] Servidor encerrou a conexao durante o login.")
            return False

        if resposta.get("tipo") == "LOGIN_ERRO":
            print(f"[LOGIN RECUSADO] {resposta.get('motivo')}")
            self.sock.close()
            return False

        if resposta.get("tipo") != "LOGIN_OK":
            print(f"[ERRO] Resposta inesperada do servidor: {resposta}")
            self.sock.close()
            return False

        print(f"Conectado como '{self.usuario}' em {self.host}:{self.porta}.")
        print(AJUDA)
        return True

    def executar(self) -> None:
        self.rodando.set()
        thread_recepcao = threading.Thread(target=self._loop_recepcao, daemon=True)
        thread_recepcao.start()

        try:
            self._loop_envio()
        except (KeyboardInterrupt, EOFError):
            self._enviar_saida()
        finally:
            self.rodando.clear()
            try:
                self.sock.close()
            except OSError:
                pass
            # Espera a thread de recepcao perceber o socket fechado e
            # encerrar sozinha, antes do processo principal terminar. Sem
            # isso, a thread (daemon) pode ainda estar no meio de um print()
            # exatamente quando o interpretador comeca a finalizar, o que
            # produz o erro fatal "_enter_buffered_busy" no encerramento.
            thread_recepcao.join(timeout=1)

    # ------------------------------------------------------------------ #
    # Thread de recepcao: fica bloqueada em recv() esperando mensagens do
    # servidor, independente do que o usuario esta digitando.
    # ------------------------------------------------------------------ #

    def _loop_recepcao(self) -> None:
        erro_rede = None
        while self.rodando.is_set():
            try:
                mensagem = self.leitor.proxima_mensagem()
            except (ConnectionResetError, ConnectionAbortedError, OSError) as erro:
                erro_rede = erro
                break
            except ValueError:
                continue

            if mensagem is None:
                break

            self._exibir_mensagem(mensagem)

        self.rodando.clear()
        if not self._saida_solicitada:
            if erro_rede is not None:
                print(f"\n[SISTEMA] Conexao com o servidor foi perdida -> {erro_rede}\n{self._prompt()}", end="", flush=True)
            else:
                print(f"\n[SISTEMA] Conexao com o servidor foi encerrada.\n{self._prompt()}", end="", flush=True)

    def _exibir_mensagem(self, mensagem: dict) -> None:
        tipo = mensagem.get("tipo")

        if tipo == "MSG":
            print(f"\n[{mensagem.get('de')}] {mensagem.get('texto')}\n{self._prompt()}", end="", flush=True)
        elif tipo == "PRIVADA":
            print(f"\n[PRIVADA de {mensagem.get('de')}] {mensagem.get('texto')}\n{self._prompt()}", end="", flush=True)
        elif tipo == "ENTROU":
            print(f"\n[SISTEMA] '{mensagem.get('usuario')}' entrou na sala '{mensagem.get('sala', '?')}'.\n{self._prompt()}", end="", flush=True)
        elif tipo == "SAIU":
            print(f"\n[SISTEMA] '{mensagem.get('usuario')}' saiu da sala '{mensagem.get('sala', '?')}'.\n{self._prompt()}", end="", flush=True)
        elif tipo == "LISTA":
            usuarios = mensagem.get("usuarios", [])
            sala = mensagem.get("sala", self.sala)
            print(f"\n[USUARIOS NA SALA '{sala}' ({len(usuarios)})]: {', '.join(usuarios)}\n{self._prompt()}", end="", flush=True)
        elif tipo == "LISTA_SALAS":
            salas = mensagem.get("salas", [])
            if salas:
                texto = ", ".join(f"{s['nome']} ({s['usuarios']})" for s in salas)
            else:
                texto = "(nenhuma sala com usuarios conectados no momento)"
            print(f"\n[SALAS ATIVAS]: {texto}\n{self._prompt()}", end="", flush=True)
        elif tipo == "SALA_OK":
            self.sala = mensagem.get("sala", self.sala)
            print(f"\n[SISTEMA] Voce agora esta na sala '{self.sala}'.\n{self._prompt()}", end="", flush=True)
        elif tipo == "SALA_ERRO":
            print(f"\n[ERRO] {mensagem.get('motivo')}\n{self._prompt()}", end="", flush=True)
        elif tipo == "HISTORICO":
            self._exibir_historico(mensagem.get("mensagens", []), mensagem.get("sala"))
        elif tipo == "ERRO":
            print(f"\n[ERRO] {mensagem.get('mensagem')}\n{self._prompt()}", end="", flush=True)
        elif tipo == "SISTEMA":
            print(f"\n[SISTEMA] {mensagem.get('mensagem')}\n{self._prompt()}", end="", flush=True)
        else:
            print(f"\n[DESCONHECIDO] {mensagem}\n{self._prompt()}", end="", flush=True)

    def _prompt(self) -> str:
        return f"[{self.sala}]> "

    def _exibir_historico(self, mensagens: list, sala: str | None) -> None:
        if not mensagens:
            return
        titulo = f"Mensagens que você perdeu na sala '{sala}'" if sala else "Histórico de mensagens privadas"
        print(f"\n----- {titulo} -----")
        for item in mensagens:
            quando = protocolo.formatar_quando(item.get("quando", ""))
            if item.get("tipo") == "PRIVADA":
                print(f"[{quando}] {item.get('de')} -> {item.get('destino')}: {item.get('texto')}")
            else:
                print(f"[{quando}] {item.get('de')}: {item.get('texto')}")
        print(f"----- Fim do histórico -----\n{self._prompt()}", end="", flush=True)

    # ------------------------------------------------------------------ #
    # Thread principal: le comandos do teclado e envia ao servidor.
    # ------------------------------------------------------------------ #

    def _loop_envio(self) -> None:
        while self.rodando.is_set():
            try:
                entrada = input(self._prompt())
            except (EOFError, KeyboardInterrupt):
                self._enviar_saida()
                break

            entrada = entrada.strip()
            if not entrada:
                continue

            if entrada == "/sair":
                self._enviar_saida()
                break
            elif entrada == "/lista":
                if not self._enviar_seguro({"tipo": "LISTAR"}):
                    break
            elif entrada == "/salas":
                if not self._enviar_seguro({"tipo": "LISTAR_SALAS"}):
                    break
            elif entrada == "/ajuda":
                print(AJUDA)
            elif entrada.startswith("/msg "):
                if not self._enviar_privada(entrada):
                    break
            elif entrada.startswith("/entrar "):
                sala = entrada[len("/entrar "):].strip()
                if not sala:
                    print("[CLIENTE] Uso correto: /entrar <sala>")
                elif not self._enviar_seguro({"tipo": "ENTRAR_SALA", "sala": sala}):
                    break
            elif entrada.startswith("/"):
                print(f"[CLIENTE] Comando desconhecido: '{entrada}'. Digite /ajuda para ver os comandos.")
            else:
                if not self._enviar_seguro({"tipo": "MSG", "texto": entrada}):
                    break

    def _enviar_seguro(self, mensagem: dict) -> bool:
        """Envia uma mensagem tratando a possibilidade de a conexao ja ter
        caido (ex.: servidor encerrado); retorna False nesse caso, para o
        chamador poder parar o loop de envio em vez de continuar tentando."""
        try:
            protocolo.enviar(self.sock, mensagem)
            return True
        except OSError as erro:
            print(f"\n[ERRO] Conexao com o servidor perdida ao enviar -> {erro}")
            self.rodando.clear()
            return False

    def _enviar_privada(self, entrada: str) -> bool:
        # formato: /msg <usuario> <mensagem...>
        partes = entrada.split(" ", 2)
        if len(partes) < 3:
            print("[CLIENTE] Uso correto: /msg <usuario> <mensagem>")
            return True
        _, destino, texto = partes
        return self._enviar_seguro({"tipo": "PRIVADA", "destino": destino, "texto": texto})

    def _enviar_saida(self) -> None:
        self._saida_solicitada = True
        try:
            protocolo.enviar(self.sock, {"tipo": "SAIR"})
        except OSError:
            pass
        print("Encerrando conexao...")
        self.rodando.clear()


def main():
    parser = argparse.ArgumentParser(description="Cliente de chat cliente-servidor (TCP).")
    parser.add_argument("--host", default=None, help="Endereco IP do servidor (ex.: 192.168.0.10).")
    parser.add_argument("--porta", type=int, default=None, help="Porta TCP do servidor (ex.: 5000).")
    parser.add_argument("--usuario", default=None, help="Apelido a ser usado no chat.")
    parser.add_argument(
        "--senha",
        default=None,
        help="Senha da conta (evite usar em maquinas compartilhadas: fica visivel no historico "
        "do shell). Se omitida, e pedida de forma oculta no terminal.",
    )
    args = parser.parse_args()

    host = args.host or input("IP do servidor: ").strip()
    porta_str = str(args.porta) if args.porta else input("Porta do servidor: ").strip()
    try:
        porta = int(porta_str)
    except ValueError:
        print("[ERRO] Porta invalida.")
        sys.exit(1)
    usuario = args.usuario or input("Escolha seu apelido: ").strip()
    senha = args.senha or getpass.getpass(
        "Senha (se for a primeira vez com esse apelido, ela sera cadastrada agora): "
    )

    cliente = ClienteChat(host=host, porta=porta, usuario=usuario, senha=senha)
    if cliente.conectar():
        cliente.executar()


if __name__ == "__main__":
    main()
