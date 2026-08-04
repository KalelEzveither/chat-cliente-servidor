# -*- coding: utf-8 -*-
"""
cliente/cliente_gui.py

Cliente de chat cliente-servidor com INTERFACE GRAFICA (Tkinter), implementando
o item opcional do enunciado ("Interface grafica (GUI) em vez de terminal").

Usa exatamente o mesmo protocolo de aplicacao definido em `comum/protocolo.py`
e o mesmo servidor de `servidor/servidor.py` -- ou seja, este e apenas um
"front-end" alternativo ao `cliente/cliente.py` (modo texto), sem nenhuma
mudanca no protocolo nem no servidor.

Bibliotecas usadas: apenas a biblioteca padrao do Python (tkinter, socket,
threading, queue, argparse), sem dependencias externas.

Uso:
    python3 cliente_gui.py [--host <IP_DO_SERVIDOR>] [--porta <PORTA>] [--usuario <APELIDO>]

    Os argumentos sao opcionais e servem apenas para pre-preencher os campos
    da tela de conexao (a senha nunca e pre-preenchida por argumento, por
    seguranca) -- a conexao so acontece quando o usuario clica em
    "Conectar" na interface. O IP nunca fica fixo no codigo, atendendo ao
    requisito do trabalho de testar em maquinas distintas do laboratorio.

    A conexao exige apelido + senha (autenticacao com auto-registro: se o
    apelido for novo, a senha digitada e cadastrada na hora). Logo apos o
    login, o cliente entra na sala padrao "geral" e o histórico de
    mensagens anteriores relevantes para o usuario naquela sala e exibido
    automaticamente no chat. E possivel trocar de sala/canal a qualquer
    momento pelo campo "Sala atual" no painel direito (a sala e criada na
    hora, caso ainda nao exista).

Arquitetura da GUI:
    - Thread principal: roda o loop de eventos do Tkinter (mainloop) e e a
      UNICA thread que pode mexer nos widgets (regra do Tkinter).
    - Thread de conexao: dispara a conexao/login em segundo plano para nao
      travar a janela enquanto espera resposta do servidor.
    - Thread de recepcao: fica bloqueada em recv() esperando mensagens do
      servidor durante toda a sessao, e as coloca numa fila (queue.Queue).
    - A thread principal consome essa fila periodicamente (root.after) e so
      ai atualiza a tela -- assim nunca se mexe em widget fora da thread
      principal, o que evitaria comportamento indefinido/crash no Tkinter.
"""

import argparse
import os
import queue
import socket
import sys
import threading
import tkinter as tk
from tkinter import messagebox, scrolledtext, ttk

# Garante que a pasta raiz do projeto (que contem o pacote `comum`) esteja no
# path, independente de onde o script for executado.
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from comum import protocolo

# Rotulo usado no primeiro item da lista de usuarios, representando o modo
# de envio "broadcast para a sala atual", em oposicao a uma mensagem privada.
# (Nao confundir com a sala chamada "geral": este item significa "a sala em
# que eu estiver agora", seja ela qual for.)
ITEM_GERAL = "🌐  Sala atual (broadcast)"


class ClienteChatGUI:
    """Janela principal do cliente de chat gráfico."""

    def __init__(self, root: tk.Tk, host: str, porta, usuario: str):
        self.root = root
        self.root.title("Chat Cliente-Servidor")
        self.root.geometry("760x520")
        self.root.minsize(560, 380)

        # --- Estado de conexao ---------------------------------------- #
        self.sock: socket.socket | None = None
        self.leitor: protocolo.LeitorDeMensagens | None = None
        self.usuario: str | None = None
        self.conectado = False
        self.rodando = False
        self.fila_mensagens: "queue.Queue[dict]" = queue.Queue()
        self.alvo_privado: str | None = None  # None = broadcast
        self._fechando = False  # True quando o usuario ja pediu pra fechar a janela
        self.sala: str = protocolo.SALA_PADRAO

        self._montar_widgets(host, porta, usuario)

        # Fecha a conexao de forma controlada se o usuario fechar a janela.
        self.root.protocol("WM_DELETE_WINDOW", self._sair)

        # Loop de consumo da fila de mensagens vindas da thread de recepcao.
        self.root.after(100, self._processar_fila)

    # ------------------------------------------------------------------ #
    # Montagem da interface
    # ------------------------------------------------------------------ #

    def _montar_widgets(self, host: str, porta, usuario: str) -> None:
        # ---- Barra superior: dados de conexao ---- #
        frame_conexao = ttk.Frame(self.root, padding=8)
        frame_conexao.pack(side="top", fill="x")

        ttk.Label(frame_conexao, text="IP do servidor:").grid(row=0, column=0, padx=(0, 4))
        self.var_host = tk.StringVar(value=host or "")
        self.entrada_host = ttk.Entry(frame_conexao, textvariable=self.var_host, width=16)
        self.entrada_host.grid(row=0, column=1, padx=(0, 10))

        ttk.Label(frame_conexao, text="Porta:").grid(row=0, column=2, padx=(0, 4))
        self.var_porta = tk.StringVar(value=str(porta) if porta else "")
        self.entrada_porta = ttk.Entry(frame_conexao, textvariable=self.var_porta, width=7)
        self.entrada_porta.grid(row=0, column=3, padx=(0, 10))

        ttk.Label(frame_conexao, text="Apelido:").grid(row=0, column=4, padx=(0, 4))
        self.var_usuario = tk.StringVar(value=usuario or "")
        self.entrada_usuario = ttk.Entry(frame_conexao, textvariable=self.var_usuario, width=14)
        self.entrada_usuario.grid(row=0, column=5, padx=(0, 10))

        ttk.Label(frame_conexao, text="Senha:").grid(row=0, column=6, padx=(0, 4))
        self.var_senha = tk.StringVar(value="")
        self.entrada_senha = ttk.Entry(frame_conexao, textvariable=self.var_senha, width=14, show="•")
        self.entrada_senha.grid(row=0, column=7, padx=(0, 10))

        self.botao_conectar = ttk.Button(frame_conexao, text="Conectar", command=self._ao_clicar_conectar)
        self.botao_conectar.grid(row=0, column=8)

        for entrada in (self.entrada_host, self.entrada_porta, self.entrada_usuario, self.entrada_senha):
            entrada.bind("<Return>", lambda evento: self._ao_clicar_conectar())

        self.rotulo_status = ttk.Label(frame_conexao, text="Desconectado", foreground="#a33")
        self.rotulo_status.grid(row=1, column=0, columnspan=9, sticky="w", pady=(4, 0))
        self.rotulo_dica = ttk.Label(
            frame_conexao,
            text="Dica: se o apelido for novo, a senha digitada é cadastrada automaticamente.",
            foreground="#888888",
            font=("TkDefaultFont", 8),
        )
        self.rotulo_dica.grid(row=2, column=0, columnspan=9, sticky="w")

        # ---- Area central: chat (esquerda) + lista de usuarios (direita) ---- #
        frame_central = ttk.Frame(self.root, padding=(8, 0))
        frame_central.pack(side="top", fill="both", expand=True)

        # Chat (log de mensagens, somente leitura)
        frame_chat = ttk.Frame(frame_central)
        frame_chat.pack(side="left", fill="both", expand=True)

        self.texto_chat = scrolledtext.ScrolledText(
            frame_chat, state="disabled", wrap="word", font=("TkDefaultFont", 10)
        )
        self.texto_chat.pack(fill="both", expand=True)
        self._configurar_tags()

        # Lista de usuarios / escolha do destinatario
        frame_usuarios = ttk.Frame(frame_central, width=200)
        frame_usuarios.pack(side="right", fill="y", padx=(8, 0))
        frame_usuarios.pack_propagate(False)

        # ---- Sala/canal atual + troca de sala ---- #
        frame_sala = ttk.Frame(frame_usuarios)
        frame_sala.pack(fill="x", pady=(0, 6))
        ttk.Label(frame_sala, text="Sala atual:", font=("TkDefaultFont", 9, "bold")).pack(anchor="w")
        self.rotulo_sala = ttk.Label(frame_sala, text=self.sala, foreground="#1a7a1a")
        self.rotulo_sala.pack(anchor="w", pady=(0, 4))

        linha_troca_sala = ttk.Frame(frame_sala)
        linha_troca_sala.pack(fill="x")
        self.var_sala = tk.StringVar()
        self.entrada_sala = ttk.Entry(linha_troca_sala, textvariable=self.var_sala, state="disabled")
        self.entrada_sala.pack(side="left", fill="x", expand=True)
        self.entrada_sala.bind("<Return>", self._ao_trocar_sala)
        self.botao_trocar_sala = ttk.Button(
            linha_troca_sala, text="Entrar", width=7, command=self._ao_trocar_sala, state="disabled"
        )
        self.botao_trocar_sala.pack(side="left", padx=(4, 0))

        self.botao_listar_salas = ttk.Button(
            frame_sala, text="Ver salas ativas", command=self._solicitar_lista_salas, state="disabled"
        )
        self.botao_listar_salas.pack(fill="x", pady=(4, 0))

        cabecalho_usuarios = ttk.Frame(frame_usuarios)
        cabecalho_usuarios.pack(fill="x", pady=(8, 0))
        self.rotulo_cabecalho_usuarios = ttk.Label(
            cabecalho_usuarios, text=f"Usuários em '{self.sala}'", font=("TkDefaultFont", 9, "bold")
        )
        self.rotulo_cabecalho_usuarios.pack(side="left")
        ttk.Button(cabecalho_usuarios, text="↻", width=3, command=self._solicitar_lista).pack(side="right")

        self.lista_usuarios = tk.Listbox(frame_usuarios, exportselection=False, activestyle="none")
        self.lista_usuarios.pack(fill="both", expand=True, pady=(4, 4))
        self.lista_usuarios.insert("end", ITEM_GERAL)
        self.lista_usuarios.select_set(0)
        self.lista_usuarios.bind("<<ListboxSelect>>", self._ao_selecionar_usuario)

        self.rotulo_alvo = ttk.Label(frame_usuarios, text=f"Enviando para: sala '{self.sala}' (todos)", wraplength=190)
        self.rotulo_alvo.pack(fill="x", pady=(0, 4))

        # ---- Barra inferior: digitar e enviar mensagem ---- #
        frame_envio = ttk.Frame(self.root, padding=8)
        frame_envio.pack(side="bottom", fill="x")

        self.var_mensagem = tk.StringVar()
        self.entrada_mensagem = ttk.Entry(frame_envio, textvariable=self.var_mensagem, state="disabled")
        self.entrada_mensagem.pack(side="left", fill="x", expand=True, padx=(0, 6))
        self.entrada_mensagem.bind("<Return>", self._enviar)

        self.botao_enviar = ttk.Button(frame_envio, text="Enviar", command=self._enviar, state="disabled")
        self.botao_enviar.pack(side="left")

        self.botao_sair = ttk.Button(frame_envio, text="Sair", command=self._sair, state="disabled")
        self.botao_sair.pack(side="left", padx=(6, 0))

    def _configurar_tags(self) -> None:
        """Define as cores/estilos usados para cada tipo de mensagem no log."""
        self.texto_chat.tag_config("recebida", foreground="#111111")
        self.texto_chat.tag_config("propria", foreground="#1a4fa0")
        self.texto_chat.tag_config("privada", foreground="#7a1fa2")
        self.texto_chat.tag_config("propria_privada", foreground="#7a1fa2", font=("TkDefaultFont", 10, "italic"))
        self.texto_chat.tag_config("sistema", foreground="#777777", font=("TkDefaultFont", 9, "italic"))
        self.texto_chat.tag_config("erro", foreground="#c0392b", font=("TkDefaultFont", 10, "bold"))
        self.texto_chat.tag_config("historico", foreground="#5a5a7a", font=("TkDefaultFont", 9))

    # ------------------------------------------------------------------ #
    # Conexao / login (roda em thread separada para nao travar a janela)
    # ------------------------------------------------------------------ #

    def _ao_clicar_conectar(self) -> None:
        if self.conectado:
            return

        host = self.var_host.get().strip()
        usuario = self.var_usuario.get().strip()
        porta_texto = self.var_porta.get().strip()
        senha = self.var_senha.get()

        if not host or not porta_texto or not usuario or not senha:
            messagebox.showwarning("Dados incompletos", "Preencha IP, porta, apelido e senha antes de conectar.")
            return
        try:
            porta = int(porta_texto)
        except ValueError:
            messagebox.showwarning("Porta inválida", "A porta deve ser um número inteiro.")
            return
        if not protocolo.validar_nome_usuario(usuario):
            messagebox.showwarning(
                "Apelido inválido",
                f"Use um apelido sem espaços, com até {protocolo.TAMANHO_MAX_USUARIO} "
                "caracteres, que não comece com '/'.",
            )
            return
        if not protocolo.validar_senha(senha):
            messagebox.showwarning(
                "Senha inválida",
                f"Use entre {protocolo.TAMANHO_MIN_SENHA} e {protocolo.TAMANHO_MAX_SENHA} caracteres.",
            )
            return

        self.botao_conectar.config(state="disabled", text="Conectando...")
        self.rotulo_status.config(text=f"Conectando a {host}:{porta}...", foreground="#a67c00")

        thread = threading.Thread(
            target=self._conectar_em_thread, args=(host, porta, usuario, senha), daemon=True
        )
        thread.start()

    def _conectar_em_thread(self, host: str, porta: int, usuario: str, senha: str) -> None:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(5)  # evita que a janela fique travada indefinidamente se o servidor nao responder
        try:
            sock.connect((host, porta))
        except (ConnectionRefusedError, socket.timeout, OSError) as erro:
            self.root.after(0, self._erro_conexao, f"Não foi possível conectar a {host}:{porta} -> {erro}")
            return

        leitor = protocolo.LeitorDeMensagens(sock)
        try:
            protocolo.enviar(sock, {"tipo": "LOGIN", "usuario": usuario, "senha": senha})
            resposta = leitor.proxima_mensagem()
        except (ConnectionResetError, OSError, ValueError) as erro:
            sock.close()
            self.root.after(0, self._erro_conexao, f"Falha ao efetuar login -> {erro}")
            return

        if resposta is None:
            sock.close()
            self.root.after(0, self._erro_conexao, "O servidor encerrou a conexão durante o login.")
            return
        if resposta.get("tipo") == "LOGIN_ERRO":
            sock.close()
            self.root.after(0, self._erro_conexao, resposta.get("motivo", "Login recusado pelo servidor."))
            return
        if resposta.get("tipo") != "LOGIN_OK":
            sock.close()
            self.root.after(0, self._erro_conexao, f"Resposta inesperada do servidor: {resposta}")
            return

        # Login aceito: volta o socket para modo bloqueante normal (o timeout
        # de 5s valia apenas para a fase de conexao/login).
        sock.settimeout(None)
        self.sock = sock
        self.leitor = leitor
        self.usuario = usuario
        self.root.after(0, self._ao_conectar_sucesso, host, porta)

    def _erro_conexao(self, motivo: str) -> None:
        self.botao_conectar.config(state="normal", text="Conectar")
        self.rotulo_status.config(text="Desconectado", foreground="#a33")
        messagebox.showerror("Erro de conexão", motivo)

    def _ao_conectar_sucesso(self, host: str, porta: int) -> None:
        self.conectado = True
        self.rodando = True

        self.entrada_host.config(state="disabled")
        self.entrada_porta.config(state="disabled")
        self.entrada_usuario.config(state="disabled")
        self.entrada_senha.config(state="disabled")
        self.botao_conectar.config(text="Conectado ✓")
        self.rotulo_status.config(text=f"Conectado como '{self.usuario}' em {host}:{porta}", foreground="#1a7a1a")

        self.entrada_mensagem.config(state="normal")
        self.botao_enviar.config(state="normal")
        self.botao_sair.config(state="normal")
        self.entrada_sala.config(state="normal")
        self.botao_trocar_sala.config(state="normal")
        self.botao_listar_salas.config(state="normal")
        self.entrada_mensagem.focus_set()

        self._exibir("sistema", f"Conectado como '{self.usuario}' na sala '{self.sala}'. Selecione um usuário à direita para conversa privada, ou digite outra sala à esquerda para trocar de canal.")

        thread_recepcao = threading.Thread(target=self._loop_recepcao, daemon=True)
        thread_recepcao.start()

        self._solicitar_lista()

    # ------------------------------------------------------------------ #
    # Thread de recepcao: apenas empilha mensagens na fila (nao mexe em
    # widget nenhum -- quem mexe na tela e sempre a thread principal).
    # ------------------------------------------------------------------ #

    def _loop_recepcao(self) -> None:
        while self.rodando:
            try:
                mensagem = self.leitor.proxima_mensagem()
            except (ConnectionResetError, ConnectionAbortedError, OSError):
                break
            except ValueError:
                continue

            if mensagem is None:
                break

            self.fila_mensagens.put(mensagem)

        self.rodando = False
        # Avisa a tela em QUALQUER caso de saida do loop (conexao fechada de
        # forma limpa, erro de rede, ou o socket ter sido fechado por outra
        # thread) -- antes, esse aviso so acontecia no caso "limpo", entao um
        # ConnectionResetError deixava a tela presa mostrando "Conectado".
        self.fila_mensagens.put({"tipo": "_DESCONECTADO"})

    def _processar_fila(self) -> None:
        """Roda periodicamente na thread principal (via root.after) e aplica
        na tela as mensagens que a thread de recepção acumulou na fila."""
        if self._fechando:
            return  # janela ja foi fechada pelo usuario; nao ha mais widgets pra atualizar
        try:
            while True:
                mensagem = self.fila_mensagens.get_nowait()
                self._tratar_mensagem(mensagem)
        except queue.Empty:
            pass
        self.root.after(100, self._processar_fila)

    def _tratar_mensagem(self, mensagem: dict) -> None:
        tipo = mensagem.get("tipo")

        if tipo == "MSG":
            self._exibir("recebida", f"[{mensagem.get('de')}] {mensagem.get('texto')}")
        elif tipo == "PRIVADA":
            self._exibir("privada", f"[Privada de {mensagem.get('de')}] {mensagem.get('texto')}")
        elif tipo == "ENTROU":
            self._exibir("sistema", f"'{mensagem.get('usuario')}' entrou na sala '{mensagem.get('sala', '?')}'.")
            if mensagem.get("sala") == self.sala:
                self._solicitar_lista()
        elif tipo == "SAIU":
            self._exibir("sistema", f"'{mensagem.get('usuario')}' saiu da sala '{mensagem.get('sala', '?')}'.")
            if mensagem.get("sala") == self.sala:
                self._solicitar_lista()
        elif tipo == "LISTA":
            self._atualizar_lista_usuarios(mensagem.get("usuarios", []))
        elif tipo == "LISTA_SALAS":
            self._exibir_lista_salas(mensagem.get("salas", []))
        elif tipo == "SALA_OK":
            self._ao_entrar_sala(mensagem.get("sala", self.sala))
        elif tipo == "SALA_ERRO":
            self._exibir("erro", f"Não foi possível trocar de sala: {mensagem.get('motivo')}")
        elif tipo == "HISTORICO":
            self._exibir_historico(mensagem.get("mensagens", []), mensagem.get("sala"))
        elif tipo == "ERRO":
            self._exibir("erro", f"Erro: {mensagem.get('mensagem')}")
        elif tipo == "SISTEMA":
            self._exibir("sistema", mensagem.get("mensagem", ""))
        elif tipo == "_DESCONECTADO":
            self._exibir("erro", "Conexão com o servidor foi encerrada.")
            self._ao_desconectar()
        else:
            self._exibir("erro", f"Mensagem de tipo desconhecido recebida: {mensagem}")

    def _exibir_historico(self, mensagens: list, sala: str | None) -> None:
        if not mensagens:
            return
        titulo = f"Mensagens que você perdeu na sala '{sala}'" if sala else "Histórico de mensagens privadas"
        self._exibir("sistema", f"── {titulo} ──")
        for item in mensagens:
            quando = protocolo.formatar_quando(item.get("quando", ""))
            if item.get("tipo") == "PRIVADA":
                texto = f"[{quando}] [Privada] {item.get('de')} → {item.get('destino')}: {item.get('texto')}"
            else:
                texto = f"[{quando}] {item.get('de')}: {item.get('texto')}"
            self._exibir("historico", texto)
        self._exibir("sistema", "── Fim do histórico ──")

    def _exibir_lista_salas(self, salas: list) -> None:
        if not salas:
            self._exibir("sistema", "Nenhuma sala com usuários conectados no momento.")
            return
        resumo = ", ".join(f"{s['nome']} ({s['usuarios']})" for s in salas)
        self._exibir("sistema", f"Salas ativas: {resumo}")

    # ------------------------------------------------------------------ #
    # Lista de usuarios / escolha de destinatario
    # ------------------------------------------------------------------ #

    def _solicitar_lista(self) -> None:
        if self.conectado:
            try:
                protocolo.enviar(self.sock, {"tipo": "LISTAR"})
            except OSError:
                pass

    def _solicitar_lista_salas(self) -> None:
        if self.conectado:
            try:
                protocolo.enviar(self.sock, {"tipo": "LISTAR_SALAS"})
            except OSError:
                pass

    def _ao_trocar_sala(self, evento=None) -> None:
        if not self.conectado:
            return
        sala = self.var_sala.get().strip()
        if not sala:
            return
        if not protocolo.validar_nome_sala(sala):
            messagebox.showwarning(
                "Nome de sala inválido",
                f"Use um nome sem espaços, com até {protocolo.TAMANHO_MAX_SALA} "
                "caracteres, que não comece com '/'.",
            )
            return
        try:
            protocolo.enviar(self.sock, {"tipo": "ENTRAR_SALA", "sala": sala})
        except OSError:
            pass

    def _ao_entrar_sala(self, sala: str) -> None:
        """Chamado ao receber SALA_OK: atualiza o estado local da sala atual
        e refaz a lista de usuarios/alvo privado, ja que agora dizem
        respeito a uma sala diferente."""
        self.sala = sala
        self.var_sala.set("")
        self.rotulo_sala.config(text=sala)
        self.rotulo_cabecalho_usuarios.config(text=f"Usuários em '{sala}'")
        self._exibir("sistema", f"Você entrou na sala '{sala}'.")
        self.alvo_privado = None
        self.rotulo_alvo.config(text=f"Enviando para: sala '{self.sala}' (todos)")
        self._solicitar_lista()

    def _atualizar_lista_usuarios(self, usuarios: list) -> None:
        nomes = sorted(nome for nome in usuarios if nome != self.usuario)

        self.lista_usuarios.delete(0, "end")
        self.lista_usuarios.insert("end", ITEM_GERAL)
        for nome in nomes:
            self.lista_usuarios.insert("end", nome)

        if self.alvo_privado in nomes:
            self.lista_usuarios.select_set(nomes.index(self.alvo_privado) + 1)
        else:
            # O usuario que estava selecionado como alvo privado saiu da sala:
            # volta automaticamente para o modo "Geral".
            if self.alvo_privado is not None:
                self._exibir("sistema", f"'{self.alvo_privado}' não está mais disponível; voltando para a sala atual.")
            self.alvo_privado = None
            self.rotulo_alvo.config(text=f"Enviando para: sala '{self.sala}' (todos)")
            self.lista_usuarios.select_set(0)

    def _ao_selecionar_usuario(self, evento=None) -> None:
        selecionados = self.lista_usuarios.curselection()
        if not selecionados:
            return
        valor = self.lista_usuarios.get(selecionados[0])
        if valor == ITEM_GERAL:
            self.alvo_privado = None
            self.rotulo_alvo.config(text=f"Enviando para: sala '{self.sala}' (todos)")
        else:
            self.alvo_privado = valor
            self.rotulo_alvo.config(text=f"Enviando para: {valor}  (mensagem privada)")

    # ------------------------------------------------------------------ #
    # Envio de mensagens
    # ------------------------------------------------------------------ #

    def _enviar(self, evento=None) -> None:
        if not self.conectado:
            return
        texto = self.var_mensagem.get().strip()
        if not texto:
            return

        payload = (
            {"tipo": "MSG", "texto": texto}
            if self.alvo_privado is None
            else {"tipo": "PRIVADA", "destino": self.alvo_privado, "texto": texto}
        )
        try:
            protocolo.enviar(self.sock, payload)
        except OSError as erro:
            self._exibir("erro", f"Não foi possível enviar: conexão com o servidor perdida ({erro}).")
            self._ao_desconectar()
            return

        if self.alvo_privado is None:
            self._exibir("propria", f"[Você] {texto}")
        else:
            self._exibir("propria_privada", f"[Você → {self.alvo_privado}] {texto}")

        self.var_mensagem.set("")

    # ------------------------------------------------------------------ #
    # Exibicao no log de chat
    # ------------------------------------------------------------------ #

    def _exibir(self, tag: str, texto: str) -> None:
        self.texto_chat.config(state="normal")
        self.texto_chat.insert("end", texto + "\n", tag)
        self.texto_chat.see("end")
        self.texto_chat.config(state="disabled")

    # ------------------------------------------------------------------ #
    # Encerramento
    # ------------------------------------------------------------------ #

    def _ao_desconectar(self) -> None:
        """Volta a janela para um estado "pronto para conectar de novo":
        alem de desligar os controles de chat, reabilita os campos de
        conexao e o botao Conectar (que ficam desabilitados durante uma
        sessao ativa) -- sem isso, depois de cair a conexao nao havia como
        tentar de novo, nem para o mesmo servidor nem para outro."""
        self.conectado = False
        self.rodando = False
        try:
            if self.sock:
                self.sock.close()
        except OSError:
            pass

        self.entrada_mensagem.config(state="disabled")
        self.botao_enviar.config(state="disabled")
        self.botao_sair.config(state="disabled")
        self.entrada_sala.config(state="disabled")
        self.botao_trocar_sala.config(state="disabled")
        self.botao_listar_salas.config(state="disabled")

        self.entrada_host.config(state="normal")
        self.entrada_porta.config(state="normal")
        self.entrada_usuario.config(state="normal")
        self.entrada_senha.config(state="normal")
        self.botao_conectar.config(state="normal", text="Conectar")
        self.rotulo_status.config(text="Desconectado", foreground="#a33")

        # Limpa o estado da sessao anterior (sala, alvo de privado, lista de
        # usuarios) para nao carregar informacao velha para a proxima
        # conexao, que pode ser a outro servidor completamente diferente.
        self.sala = protocolo.SALA_PADRAO
        self.alvo_privado = None
        self.rotulo_sala.config(text=self.sala)
        self.rotulo_cabecalho_usuarios.config(text=f"Usuários em '{self.sala}'")
        self.rotulo_alvo.config(text=f"Enviando para: sala '{self.sala}' (todos)")
        self.lista_usuarios.delete(0, "end")
        self.lista_usuarios.insert("end", ITEM_GERAL)
        self.lista_usuarios.select_set(0)

    def _sair(self) -> None:
        self._fechando = True
        if self.conectado:
            try:
                protocolo.enviar(self.sock, {"tipo": "SAIR"})
            except OSError:
                pass
            self.rodando = False
            try:
                self.sock.close()
            except OSError:
                pass
        self.root.destroy()


def main():
    parser = argparse.ArgumentParser(description="Cliente gráfico (Tkinter) de chat cliente-servidor (TCP).")
    parser.add_argument("--host", default="", help="IP do servidor para pré-preencher o campo (opcional).")
    parser.add_argument("--porta", type=int, default=None, help="Porta do servidor para pré-preencher o campo (opcional).")
    parser.add_argument("--usuario", default="", help="Apelido para pré-preencher o campo (opcional).")
    args = parser.parse_args()

    root = tk.Tk()
    ClienteChatGUI(root, host=args.host, porta=args.porta, usuario=args.usuario)
    root.mainloop()


if __name__ == "__main__":
    main()
