# -*- coding: utf-8 -*-
"""
cliente/cliente_gui.py

Cliente de chat cliente-servidor com INTERFACE GRAFICA (Tkinter), implementando
o item opcional do enunciado ("Interface grafica (GUI) em vez de terminal").

Usa exatamente o mesmo protocolo de aplicacao definido em `comum/protocolo.py`
e o mesmo servidor de `servidor/servidor.py` -- ou seja, este e apenas um
"front-end" alternativo ao `cliente/cliente.py` (modo texto), sem nenhuma
mudanca no protocolo nem no servidor alem do aviso efemero de "digitando...".

Bibliotecas usadas: apenas a biblioteca padrao do Python (tkinter, socket,
threading, queue, time, argparse), sem dependencias externas.

Uso:
    python3 cliente_gui.py [--host <IP_DO_SERVIDOR>] [--porta <PORTA>] [--usuario <APELIDO>]

    Os argumentos sao opcionais e servem apenas para pre-preencher os campos
    da tela de conexao -- a conexao so acontece quando o usuario clica em
    "Entrar" na interface. O IP nunca fica fixo no codigo, atendendo ao
    requisito do trabalho de testar em maquinas distintas do laboratorio.

Recursos desta interface:
    - Aba "Usuários": lista de quem está na sala atual; clicar em alguém
      abre (ou volta para) a conversa PRIVADA com essa pessoa.
    - Aba "Salas ativas": lista as salas com gente conectada agora (com a
      contagem de usuários), e permite entrar em qualquer uma delas, ou
      digitar o nome de uma sala nova para criá-la na hora.
    - Aba "Privadas": lista de conversas privadas já iniciadas, com um
      indicador de quantas mensagens não lidas há em cada uma.
    - O histórico de cada conversa privada fica isolado da conversa da
      sala: cada uma tem sua própria "linha do tempo"; trocar de aba/
      contato só troca o que é exibido, nunca mistura as duas.
    - Indicador de "fulano está digitando..." relativo à conversa aberta
      no momento (sala ou privada).
    - Notificação (toast) quando chega uma mensagem privada de uma
      conversa que não é a que está aberta no momento, com um contador de
      não lidas na aba "Privadas".

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
import time
import tkinter as tk
from tkinter import messagebox, ttk

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from comum import protocolo

COR_FUNDO = "#0f172a"
COR_PAINEL = "#1a2333"
COR_PAINEL_2 = "#212c42"
COR_CAMPO = "#28324a"
COR_BORDA = "#334155"
COR_TEXTO = "#e2e8f0"
COR_TEXTO_SUAVE = "#8b98b3"
COR_DESTAQUE = "#6366f1"
COR_DESTAQUE_HOVER = "#4f46e5"
COR_PRIVADA = "#a855f7"
COR_SUCESSO = "#22c55e"
COR_ERRO = "#ef4444"
COR_CHAT_FUNDO = "#f8fafc"
COR_BOLHA_TXT = "#1e293b"

FONTE_BASE = ("Segoe UI", 10)
FONTE_NEGRITO = ("Segoe UI", 10, "bold")
FONTE_TITULO = ("Segoe UI", 15, "bold")
FONTE_SUBTITULO = ("Segoe UI", 10, "bold")
FONTE_PEQUENA = ("Segoe UI", 8)
FONTE_PEQUENA_IT = ("Segoe UI", 8, "italic")
FONTE_MENSAGEM = ("Segoe UI", 10)

SEGUNDOS_EXPIRAR_DIGITANDO = 3.0
INTERVALO_MINIMO_ENVIO_DIGITANDO = 1.2

_ESTILO_CONFIGURADO = False


def _configurar_estilo_ttk():
    global _ESTILO_CONFIGURADO
    if _ESTILO_CONFIGURADO:
        return
    _ESTILO_CONFIGURADO = True
    estilo = ttk.Style()
    try:
        estilo.theme_use("clam")
    except tk.TclError:
        pass
    estilo.configure("Chat.TNotebook", background=COR_PAINEL, borderwidth=0)
    estilo.configure(
        "Chat.TNotebook.Tab",
        background=COR_PAINEL_2, foreground=COR_TEXTO_SUAVE,
        padding=(12, 7), font=("Segoe UI", 9, "bold"), borderwidth=0,
    )
    estilo.map(
        "Chat.TNotebook.Tab",
        background=[("selected", COR_DESTAQUE)],
        foreground=[("selected", "white")],
    )
    estilo.configure("Chat.TFrame", background=COR_PAINEL)


def _hora_agora() -> str:
    return time.strftime("%H:%M")


class ClienteChatGUI:
    """Janela principal do cliente de chat gráfico."""

    def __init__(self, root, host: str, porta, usuario: str):
        self.root = root
        self.root.title("Chat Cliente-Servidor")
        self.root.geometry("1040x650")
        self.root.minsize(860, 500)
        self.root.configure(bg=COR_FUNDO)
        _configurar_estilo_ttk()

        self.sock = None
        self.leitor = None
        self.usuario = None
        self.conectado = False
        self.rodando = False
        self.fila_mensagens = queue.Queue()
        self._fechando = False
        self._host_prefill, self._porta_prefill, self._usuario_prefill = host, porta, usuario

        self.sala = protocolo.SALA_PADRAO
        self.conversa_atual = ("sala", self.sala)
        self.conversas = {}
        self.contatos_privados = {}
        self.ordem_privados = []
        self.digitando = {}
        self._ultimo_envio_digitando = 0.0
        self._toasts_ativos = []
        self._cache_usuarios = []
        self._cache_salas = []

        self.container = tk.Frame(self.root, bg=COR_FUNDO)
        self.container.pack(fill="both", expand=True)

        self.frame_login = None
        self.frame_chat = None
        self._montar_tela_login()

        self.root.protocol("WM_DELETE_WINDOW", self._sair)
        self.root.after(100, self._processar_fila)
        self.root.after(500, self._atualizar_indicador_digitando)

    # ====================================================================
    # TELA DE LOGIN
    # ====================================================================

    def _montar_tela_login(self) -> None:
        self.frame_login = tk.Frame(self.container, bg=COR_FUNDO)
        self.frame_login.pack(fill="both", expand=True)

        card = tk.Frame(self.frame_login, bg=COR_PAINEL, padx=40, pady=34)
        card.place(relx=0.5, rely=0.45, anchor="center")

        tk.Label(card, text="💬", font=("Segoe UI Emoji", 30), bg=COR_PAINEL, fg=COR_DESTAQUE).pack(pady=(0, 4))
        tk.Label(card, text="Chat Cliente-Servidor", font=FONTE_TITULO, bg=COR_PAINEL, fg="white").pack()
        tk.Label(card, text="Redes de Computadores II", font=FONTE_BASE, bg=COR_PAINEL, fg=COR_TEXTO_SUAVE).pack(pady=(0, 22))

        self.var_host = tk.StringVar(value=self._host_prefill or "127.0.0.1")
        self.var_porta = tk.StringVar(value=str(self._porta_prefill) if self._porta_prefill else "5000")
        self.var_usuario = tk.StringVar(value=self._usuario_prefill or "")

        self.entrada_host = self._campo_login(card, "IP do servidor", self.var_host)
        self.entrada_porta = self._campo_login(card, "Porta", self.var_porta)
        self.entrada_usuario = self._campo_login(card, "Seu apelido", self.var_usuario)

        self.rotulo_status_login = tk.Label(
            card, text="", font=FONTE_PEQUENA, bg=COR_PAINEL, fg=COR_ERRO, wraplength=300, justify="left"
        )
        self.rotulo_status_login.pack(pady=(2, 8), anchor="w")

        self.botao_conectar = tk.Button(
            card, text="Entrar", font=FONTE_NEGRITO, bg=COR_DESTAQUE, fg="white",
            activebackground=COR_DESTAQUE_HOVER, activeforeground="white",
            relief="flat", bd=0, cursor="hand2", height=2,
            command=self._ao_clicar_conectar,
        )
        self.botao_conectar.pack(fill="x", pady=(10, 0))

        for entrada in (self.entrada_host, self.entrada_porta, self.entrada_usuario):
            entrada.bind("<Return>", lambda e: self._ao_clicar_conectar())

    def _campo_login(self, parent, rotulo, variavel):
        tk.Label(parent, text=rotulo, font=FONTE_BASE, bg=COR_PAINEL, fg=COR_TEXTO, anchor="w").pack(fill="x")
        entrada = tk.Entry(
            parent, textvariable=variavel, font=FONTE_BASE, bg=COR_CAMPO, fg="white",
            insertbackground="white", relief="flat", bd=0,
        )
        entrada.pack(fill="x", ipady=8, pady=(4, 6))
        tk.Frame(parent, bg=COR_BORDA, height=1).pack(fill="x", pady=(0, 12))
        return entrada

    # ------------------------------------------------------------------ #
    # Conexao / login (roda em thread separada para nao travar a janela)
    # ------------------------------------------------------------------ #

    def _ler_e_validar_campos(self):
        host = self.var_host.get().strip()
        usuario = self.var_usuario.get().strip()
        porta_texto = self.var_porta.get().strip()

        if not host or not porta_texto or not usuario:
            self.rotulo_status_login.config(text="Preencha IP, porta e apelido.")
            return None
        try:
            porta = int(porta_texto)
        except ValueError:
            self.rotulo_status_login.config(text="A porta deve ser um número inteiro.")
            return None
        if not protocolo.validar_nome_usuario(usuario):
            self.rotulo_status_login.config(
                text=f"Apelido inválido: sem espaços, até {protocolo.TAMANHO_MAX_USUARIO} "
                "caracteres, e que não comece com '/'."
            )
            return None
        return host, porta, usuario

    def _ao_clicar_conectar(self) -> None:
        if self.conectado:
            return
        campos = self._ler_e_validar_campos()
        if campos is None:
            return
        host, porta, usuario = campos

        self.rotulo_status_login.config(text="")
        self.botao_conectar.config(state="disabled", text="Conectando...")

        thread = threading.Thread(target=self._conectar_em_thread, args=(host, porta, usuario), daemon=True)
        thread.start()

    def _conectar_em_thread(self, host: str, porta: int, usuario: str) -> None:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(5)
        try:
            sock.connect((host, porta))
        except (ConnectionRefusedError, socket.timeout, OSError) as erro:
            self.root.after(0, self._erro_conexao, f"Não foi possível conectar a {host}:{porta} -> {erro}")
            return

        leitor = protocolo.LeitorDeMensagens(sock)
        try:
            protocolo.enviar(sock, {"tipo": "LOGIN", "usuario": usuario})
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

        sock.settimeout(None)
        self.sock = sock
        self.leitor = leitor
        self.usuario = usuario
        self._host_prefill, self._porta_prefill, self._usuario_prefill = host, porta, usuario
        self.root.after(0, self._ao_conectar_sucesso, host, porta)

    def _erro_conexao(self, motivo: str) -> None:
        self.botao_conectar.config(state="normal", text="Entrar")
        self.rotulo_status_login.config(text=motivo)

    def _ao_conectar_sucesso(self, host: str, porta: int) -> None:
        self.conectado = True
        self.rodando = True

        self.frame_login.destroy()
        self.frame_login = None
        self._montar_tela_chat(host, porta)

        thread_recepcao = threading.Thread(target=self._loop_recepcao, daemon=True)
        thread_recepcao.start()

        self._solicitar_lista()
        self._solicitar_lista_salas()

    # ====================================================================
    # TELA PRINCIPAL DO CHAT
    # ====================================================================

    def _montar_tela_chat(self, host, porta) -> None:
        self.frame_chat = tk.Frame(self.container, bg=COR_FUNDO)
        self.frame_chat.pack(fill="both", expand=True)

        self._montar_barra_topo(host, porta)

        corpo = tk.Frame(self.frame_chat, bg=COR_FUNDO)
        corpo.pack(fill="both", expand=True)

        self._montar_sidebar(corpo)
        self._montar_area_conversa(corpo)

        self._renderizar_conversa(self.conversa_atual)
        self.entrada_mensagem.focus_set()

    def _montar_barra_topo(self, host, porta) -> None:
        topo = tk.Frame(self.frame_chat, bg=COR_PAINEL, height=54)
        topo.pack(fill="x", side="top")
        topo.pack_propagate(False)

        tk.Label(topo, text=f"💬  {self.usuario}", font=FONTE_TITULO, bg=COR_PAINEL, fg="white").pack(side="left", padx=18)
        tk.Label(
            topo, text=f"conectado a {host}:{porta}", font=FONTE_PEQUENA, bg=COR_PAINEL, fg=COR_SUCESSO
        ).pack(side="right", padx=18)

    def _montar_sidebar(self, parent) -> None:
        painel = tk.Frame(parent, bg=COR_PAINEL, width=310)
        painel.pack(side="left", fill="y")
        painel.pack_propagate(False)

        self.notebook = ttk.Notebook(painel, style="Chat.TNotebook")
        self.notebook.pack(fill="both", expand=True, padx=6, pady=8)

        self.aba_usuarios = tk.Frame(self.notebook, bg=COR_PAINEL)
        self.aba_salas = tk.Frame(self.notebook, bg=COR_PAINEL)
        self.aba_privadas = tk.Frame(self.notebook, bg=COR_PAINEL)

        self.notebook.add(self.aba_usuarios, text="Usuários")
        self.notebook.add(self.aba_salas, text="Salas")
        self.notebook.add(self.aba_privadas, text="Privadas")

        self._montar_aba_usuarios(self.aba_usuarios)
        self._montar_aba_salas(self.aba_salas)
        self._montar_aba_privadas(self.aba_privadas)

    def _montar_aba_usuarios(self, aba) -> None:
        cabecalho = tk.Frame(aba, bg=COR_PAINEL)
        cabecalho.pack(fill="x", pady=(6, 2))
        tk.Label(cabecalho, text="SALA ATUAL", font=("Segoe UI", 8, "bold"), bg=COR_PAINEL, fg=COR_TEXTO_SUAVE).pack(side="left")
        tk.Button(
            cabecalho, text="↻", font=FONTE_PEQUENA, bg=COR_PAINEL, fg=COR_TEXTO_SUAVE,
            relief="flat", bd=0, cursor="hand2", command=self._solicitar_lista,
        ).pack(side="right")

        self.rotulo_sala_atual = tk.Label(
            aba, text=self.sala, font=FONTE_SUBTITULO, bg=COR_PAINEL, fg=COR_DESTAQUE, anchor="w"
        )
        self.rotulo_sala_atual.pack(fill="x", pady=(0, 8))

        self.lista_usuarios = tk.Listbox(
            aba, font=FONTE_BASE, bg=COR_PAINEL_2, fg=COR_TEXTO, selectbackground=COR_DESTAQUE,
            selectforeground="white", relief="flat", bd=0, highlightthickness=0, activestyle="none",
        )
        self.lista_usuarios.pack(fill="both", expand=True)
        self.lista_usuarios.bind("<<ListboxSelect>>", self._ao_selecionar_usuario)

        tk.Label(
            aba, text="Clique em alguém para abrir uma conversa privada.",
            font=FONTE_PEQUENA, bg=COR_PAINEL, fg=COR_TEXTO_SUAVE, wraplength=230, justify="left", anchor="w",
        ).pack(fill="x", pady=(6, 4))

    def _montar_aba_salas(self, aba) -> None:
        cabecalho = tk.Frame(aba, bg=COR_PAINEL)
        cabecalho.pack(fill="x", pady=(6, 6))
        tk.Label(cabecalho, text="SALAS COM GENTE CONECTADA", font=("Segoe UI", 8, "bold"), bg=COR_PAINEL, fg=COR_TEXTO_SUAVE).pack(side="left")
        tk.Button(
            cabecalho, text="↻", font=FONTE_PEQUENA, bg=COR_PAINEL, fg=COR_TEXTO_SUAVE,
            relief="flat", bd=0, cursor="hand2", command=self._solicitar_lista_salas,
        ).pack(side="right")

        self.lista_salas = tk.Listbox(
            aba, font=FONTE_BASE, bg=COR_PAINEL_2, fg=COR_TEXTO, selectbackground=COR_DESTAQUE,
            selectforeground="white", relief="flat", bd=0, highlightthickness=0, activestyle="none",
        )
        self.lista_salas.pack(fill="both", expand=True)
        self.lista_salas.bind("<<ListboxSelect>>", self._ao_selecionar_sala)

        tk.Label(
            aba, text="Clique numa sala para entrar nela.", font=FONTE_PEQUENA,
            bg=COR_PAINEL, fg=COR_TEXTO_SUAVE, anchor="w",
        ).pack(fill="x", pady=(6, 8))

        linha_nova_sala = tk.Frame(aba, bg=COR_PAINEL)
        linha_nova_sala.pack(fill="x", pady=(0, 4))
        self.var_nova_sala = tk.StringVar()
        entrada_nova_sala = tk.Entry(
            linha_nova_sala, textvariable=self.var_nova_sala, font=FONTE_BASE, bg=COR_CAMPO, fg="white",
            insertbackground="white", relief="flat", bd=0,
        )
        entrada_nova_sala.pack(side="left", fill="x", expand=True, ipady=6)
        entrada_nova_sala.bind("<Return>", self._ao_trocar_sala)
        tk.Button(
            linha_nova_sala, text="Entrar", font=("Segoe UI", 9, "bold"), bg=COR_DESTAQUE, fg="white",
            activebackground=COR_DESTAQUE_HOVER, activeforeground="white", relief="flat", bd=0,
            cursor="hand2", command=self._ao_trocar_sala,
        ).pack(side="left", padx=(6, 0))

        tk.Label(
            aba, text="Nome de sala nova = ela é criada na hora.", font=FONTE_PEQUENA_IT,
            bg=COR_PAINEL, fg=COR_TEXTO_SUAVE, anchor="w",
        ).pack(fill="x")

    def _montar_aba_privadas(self, aba) -> None:
        tk.Label(
            aba, text="SUAS CONVERSAS PRIVADAS", font=("Segoe UI", 8, "bold"), bg=COR_PAINEL, fg=COR_TEXTO_SUAVE,
        ).pack(fill="x", pady=(6, 6), anchor="w")

        self.lista_privadas = tk.Listbox(
            aba, font=FONTE_BASE, bg=COR_PAINEL_2, fg=COR_TEXTO, selectbackground=COR_DESTAQUE,
            selectforeground="white", relief="flat", bd=0, highlightthickness=0, activestyle="none",
        )
        self.lista_privadas.pack(fill="both", expand=True)
        self.lista_privadas.bind("<<ListboxSelect>>", self._ao_selecionar_privado)

        tk.Label(
            aba, text="Uma conversa aparece aqui assim que você ou a outra pessoa mandarem a primeira mensagem privada.",
            font=FONTE_PEQUENA, bg=COR_PAINEL, fg=COR_TEXTO_SUAVE, wraplength=230, justify="left", anchor="w",
        ).pack(fill="x", pady=(6, 4))

    def _montar_area_conversa(self, parent) -> None:
        area = tk.Frame(parent, bg=COR_FUNDO)
        area.pack(side="left", fill="both", expand=True)

        cabecalho = tk.Frame(area, bg=COR_FUNDO)
        cabecalho.pack(fill="x")

        self.rotulo_cabecalho = tk.Label(
            cabecalho, text="", font=FONTE_NEGRITO, bg=COR_FUNDO, fg=COR_DESTAQUE, anchor="w", padx=16, pady=8,
        )
        self.rotulo_cabecalho.pack(side="left", fill="x", expand=True)

        self.botao_voltar = tk.Button(
            cabecalho, text="← Voltar para a sala", font=FONTE_PEQUENA, bg=COR_FUNDO, fg=COR_TEXTO_SUAVE,
            relief="flat", bd=0, cursor="hand2", command=self._voltar_para_sala,
        )

        self.rotulo_digitando = tk.Label(
            area, text="", font=FONTE_PEQUENA_IT, bg=COR_FUNDO, fg=COR_TEXTO_SUAVE, anchor="w", padx=16,
        )
        self.rotulo_digitando.pack(fill="x")

        frame_mensagens = tk.Frame(area, bg=COR_CHAT_FUNDO)
        frame_mensagens.pack(fill="both", expand=True)

        self.texto_chat = tk.Text(
            frame_mensagens, font=FONTE_MENSAGEM, bg=COR_CHAT_FUNDO, fg=COR_BOLHA_TXT,
            relief="flat", bd=0, wrap="word", state="disabled", padx=16, pady=12, spacing3=6,
        )
        scroll = ttk.Scrollbar(frame_mensagens, command=self.texto_chat.yview)
        self.texto_chat.configure(yscrollcommand=scroll.set)
        self.texto_chat.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self._configurar_tags_texto()

        rodape = tk.Frame(area, bg=COR_PAINEL, height=64)
        rodape.pack(fill="x", side="bottom")
        rodape.pack_propagate(False)

        self.var_mensagem = tk.StringVar()
        self.entrada_mensagem = tk.Entry(
            rodape, textvariable=self.var_mensagem, font=FONTE_BASE, bg=COR_CAMPO, fg="white",
            insertbackground="white", relief="flat", bd=0,
        )
        self.entrada_mensagem.pack(side="left", fill="both", expand=True, padx=(16, 8), pady=14, ipady=6)
        self.entrada_mensagem.bind("<Return>", self._enviar)
        self.entrada_mensagem.bind("<KeyRelease>", self._ao_digitar)

        tk.Button(
            rodape, text="Enviar ➤", font=FONTE_NEGRITO, bg=COR_DESTAQUE, fg="white",
            activebackground=COR_DESTAQUE_HOVER, activeforeground="white", relief="flat", bd=0,
            cursor="hand2", command=self._enviar, padx=18,
        ).pack(side="right", padx=(0, 10), pady=14)

        tk.Button(
            rodape, text="Sair", font=FONTE_NEGRITO, bg="#3f2937", fg="#fca5a5",
            activebackground="#552a37", activeforeground="#fca5a5", relief="flat", bd=0,
            cursor="hand2", command=self._sair, padx=14,
        ).pack(side="right", padx=(0, 4), pady=14)

    def _configurar_tags_texto(self) -> None:
        t = self.texto_chat
        t.tag_configure("propria_nome", justify="right", foreground=COR_DESTAQUE, font=FONTE_NEGRITO, spacing1=8)
        t.tag_configure("propria_texto", justify="right", foreground=COR_BOLHA_TXT, font=FONTE_MENSAGEM)
        t.tag_configure("outro_nome", justify="left", foreground="#334155", font=FONTE_NEGRITO, spacing1=8)
        t.tag_configure("outro_texto", justify="left", foreground=COR_BOLHA_TXT, font=FONTE_MENSAGEM)
        t.tag_configure("propria_privada_nome", justify="right", foreground=COR_PRIVADA, font=FONTE_NEGRITO, spacing1=8)
        t.tag_configure("outro_privada_nome", justify="left", foreground=COR_PRIVADA, font=FONTE_NEGRITO, spacing1=8)
        t.tag_configure("sistema", justify="center", foreground="#94a3b8", font=("Segoe UI", 9, "italic"), spacing1=6)
        t.tag_configure("erro", justify="center", foreground=COR_ERRO, font=("Segoe UI", 9, "italic"), spacing1=6)

    # ====================================================================
    # Rede: thread de recepção -> fila -> GUI (thread principal)
    # ====================================================================

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
        self.fila_mensagens.put({"tipo": "_DESCONECTADO"})

    def _processar_fila(self) -> None:
        if self._fechando:
            return
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
            sala = mensagem.get("sala", self.sala)
            self._bolha(("sala", sala), mensagem.get("de"), mensagem.get("texto"), _hora_agora(), propria=False)

        elif tipo == "PRIVADA":
            de = mensagem.get("de")
            conversa_id = ("privada", de)
            self._registrar_contato_privado(de)
            self._bolha(conversa_id, de, mensagem.get("texto"), _hora_agora(), propria=False)
            if self.conversa_atual != conversa_id:
                self._incrementar_nao_lidas(de)
                self._mostrar_toast(
                    f"📩  Nova mensagem privada de {de}",
                    ao_clicar=lambda nm=de: self._ao_clicar_toast_privada(nm),
                )

        elif tipo == "ENTROU":
            sala = mensagem.get("sala", "?")
            self._linha(("sala", sala), f"'{mensagem.get('usuario')}' entrou na sala '{sala}'.", "sistema")
            if sala == self.sala:
                self._solicitar_lista()

        elif tipo == "SAIU":
            sala = mensagem.get("sala", "?")
            self._linha(("sala", sala), f"'{mensagem.get('usuario')}' saiu da sala '{sala}'.", "sistema")
            if sala == self.sala:
                self._solicitar_lista()

        elif tipo == "LISTA":
            self._atualizar_lista_usuarios(mensagem.get("usuarios", []))

        elif tipo == "LISTA_SALAS":
            self._atualizar_lista_salas(mensagem.get("salas", []))

        elif tipo == "SALA_OK":
            self._ao_entrar_sala(mensagem.get("sala", self.sala))

        elif tipo == "SALA_ERRO":
            self._mostrar_toast(f"⚠️  {mensagem.get('motivo')}", cor=COR_ERRO)

        elif tipo == "HISTORICO":
            self._processar_historico(mensagem.get("sala"), mensagem.get("mensagens", []))

        elif tipo == "ERRO":
            self._linha(self.conversa_atual, f"Erro: {mensagem.get('mensagem')}", "erro")

        elif tipo == "SISTEMA":
            self._linha(("sala", self.sala), mensagem.get("mensagem", ""), "sistema")

        elif tipo == "DIGITANDO":
            de = mensagem.get("de")
            sala = mensagem.get("sala")
            chave = ("sala", sala) if sala else ("privada", de)
            self.digitando.setdefault(chave, {})[de] = time.monotonic() + SEGUNDOS_EXPIRAR_DIGITANDO

        elif tipo == "_DESCONECTADO":
            self._linha(self.conversa_atual, "Conexão com o servidor foi encerrada.", "erro")
            self._ao_desconectar()

    def _processar_historico(self, sala, mensagens: list) -> None:
        if not mensagens:
            return
        if sala:
            for item in mensagens:
                quando = protocolo.formatar_quando(item.get("quando", ""))
                self._bolha(("sala", sala), item.get("de"), item.get("texto"), quando, propria=False)
        else:
            for item in mensagens:
                if item.get("tipo") != "PRIVADA":
                    continue
                de = item.get("de")
                destino = item.get("destino")
                outro = destino if de == self.usuario else de
                propria = de == self.usuario
                quando = protocolo.formatar_quando(item.get("quando", ""))
                self._registrar_contato_privado(outro, marcar_recente=False)
                self._bolha(("privada", outro), de, item.get("texto"), quando, propria=propria)
            self._atualizar_lista_privados_widget()

    # ====================================================================
    # Troca de sala
    # ====================================================================

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
        sala = self.var_nova_sala.get().strip()
        if not sala:
            return
        if not protocolo.validar_nome_sala(sala):
            messagebox.showwarning(
                "Nome de sala inválido",
                f"Use um nome sem espaços, com até {protocolo.TAMANHO_MAX_SALA} caracteres, que não comece com '/'.",
            )
            return
        try:
            protocolo.enviar(self.sock, {"tipo": "ENTRAR_SALA", "sala": sala})
        except OSError:
            pass

    def _ao_selecionar_sala(self, evento=None) -> None:
        selecao = self.lista_salas.curselection()
        if not selecao:
            return
        idx = selecao[0]
        if idx >= len(self._cache_salas):
            return
        nome = self._cache_salas[idx]["nome"]
        if nome != self.sala:
            try:
                protocolo.enviar(self.sock, {"tipo": "ENTRAR_SALA", "sala": nome})
            except OSError:
                pass

    def _ao_entrar_sala(self, sala: str) -> None:
        sala_antiga = self.sala
        estava_vendo_sala = self.conversa_atual == ("sala", sala_antiga)
        self.sala = sala
        self.var_nova_sala.set("")
        self.rotulo_sala_atual.config(text=sala)

        self._linha(("sala", sala), f"Você entrou na sala '{sala}'.", "sistema")

        if estava_vendo_sala or sala_antiga == sala:
            self._selecionar_conversa(("sala", sala))

        self._solicitar_lista()
        self._solicitar_lista_salas()

    def _voltar_para_sala(self) -> None:
        self._selecionar_conversa(("sala", self.sala))

    # ====================================================================
    # Lista de usuários da sala / seleção de conversa privada
    # ====================================================================

    def _atualizar_lista_usuarios(self, usuarios: list) -> None:
        self._cache_usuarios = sorted(nome for nome in usuarios if nome != self.usuario)
        self.lista_usuarios.delete(0, "end")
        for nome in self._cache_usuarios:
            self.lista_usuarios.insert("end", f"●  {nome}")

    def _ao_selecionar_usuario(self, evento=None) -> None:
        selecao = self.lista_usuarios.curselection()
        if not selecao:
            return
        idx = selecao[0]
        if idx >= len(self._cache_usuarios):
            return
        nome = self._cache_usuarios[idx]
        self._registrar_contato_privado(nome)
        self._selecionar_conversa(("privada", nome))
        self.notebook.select(self.aba_privadas)

    def _atualizar_lista_salas(self, salas: list) -> None:
        self._cache_salas = salas
        self.lista_salas.delete(0, "end")
        for i, s in enumerate(salas):
            marcador = "●  " if s["nome"] == self.sala else "○  "
            rotulo = f"{marcador}{s['nome']}   ({s['usuarios']})"
            self.lista_salas.insert("end", rotulo)
            if s["nome"] == self.sala:
                self.lista_salas.itemconfig(i, fg=COR_DESTAQUE)

    # ====================================================================
    # Conversas privadas: registro de contatos, não lidas, seleção
    # ====================================================================

    def _registrar_contato_privado(self, nome: str, marcar_recente: bool = True) -> None:
        if nome not in self.contatos_privados:
            self.contatos_privados[nome] = 0
        if marcar_recente:
            if nome in self.ordem_privados:
                self.ordem_privados.remove(nome)
            self.ordem_privados.insert(0, nome)
        elif nome not in self.ordem_privados:
            self.ordem_privados.append(nome)
        self._atualizar_lista_privados_widget()

    def _incrementar_nao_lidas(self, nome: str) -> None:
        self.contatos_privados[nome] = self.contatos_privados.get(nome, 0) + 1
        if nome in self.ordem_privados:
            self.ordem_privados.remove(nome)
        self.ordem_privados.insert(0, nome)
        self._atualizar_lista_privados_widget()
        self._atualizar_titulo_aba_privadas()

    def _marcar_como_lida(self, nome: str) -> None:
        if self.contatos_privados.get(nome, 0) != 0:
            self.contatos_privados[nome] = 0
            self._atualizar_lista_privados_widget()
            self._atualizar_titulo_aba_privadas()

    def _atualizar_titulo_aba_privadas(self) -> None:
        total = sum(self.contatos_privados.values())
        texto = "Privadas ●" if total > 0 else "Privadas"
        self.notebook.tab(self.aba_privadas, text=texto)

    def _atualizar_lista_privados_widget(self) -> None:
        self.lista_privadas.delete(0, "end")
        for i, nome in enumerate(self.ordem_privados):
            n = self.contatos_privados.get(nome, 0)
            rotulo = f"🔒 {nome}" + (f"   ● {n}" if n > 0 else "")
            self.lista_privadas.insert("end", rotulo)
            self.lista_privadas.itemconfig(i, fg=(COR_PRIVADA if n > 0 else COR_TEXTO))

    def _ao_selecionar_privado(self, evento=None) -> None:
        selecao = self.lista_privadas.curselection()
        if not selecao:
            return
        idx = selecao[0]
        if idx >= len(self.ordem_privados):
            return
        nome = self.ordem_privados[idx]
        self._selecionar_conversa(("privada", nome))

    def _ao_clicar_toast_privada(self, nome: str) -> None:
        self._registrar_contato_privado(nome)
        self._selecionar_conversa(("privada", nome))
        self.notebook.select(self.aba_privadas)

    # ====================================================================
    # Seleção / renderização da conversa aberta no momento
    # ====================================================================

    def _selecionar_conversa(self, conversa_id) -> None:
        self.conversa_atual = conversa_id
        if conversa_id[0] == "sala":
            self.rotulo_cabecalho.config(text=f"💬  Sala: {conversa_id[1]}", fg=COR_DESTAQUE)
            self.botao_voltar.pack_forget()
        else:
            nome = conversa_id[1]
            self.rotulo_cabecalho.config(text=f"🔒  Conversa privada com {nome}", fg=COR_PRIVADA)
            self.botao_voltar.pack(side="right")
            self._marcar_como_lida(nome)

        self._renderizar_conversa(conversa_id)
        if self.conectado:
            self.entrada_mensagem.focus_set()

    def _renderizar_conversa(self, conversa_id) -> None:
        self.texto_chat.config(state="normal")
        self.texto_chat.delete("1.0", "end")
        self.texto_chat.config(state="disabled")
        for item in self.conversas.get(conversa_id, []):
            tag, quem, texto, hora = item
            if tag in ("propria", "outro"):
                self._inserir_bolha_widget(quem, texto, hora, propria=(tag == "propria"), privada=(conversa_id[0] == "privada"))
            else:
                self._inserir_linha_widget(texto, tag)

    def _bolha(self, conversa_id, quem, texto, hora, propria: bool) -> None:
        cache = self.conversas.setdefault(conversa_id, [])
        cache.append(("propria" if propria else "outro", quem, texto, hora))
        if conversa_id == self.conversa_atual:
            self._inserir_bolha_widget(quem, texto, hora, propria, privada=(conversa_id[0] == "privada"))

    def _linha(self, conversa_id, texto, tag) -> None:
        cache = self.conversas.setdefault(conversa_id, [])
        cache.append((tag, None, texto, None))
        if conversa_id == self.conversa_atual:
            self._inserir_linha_widget(texto, tag)

    def _inserir_bolha_widget(self, quem, texto, hora, propria: bool, privada: bool) -> None:
        t = self.texto_chat
        t.config(state="normal")
        if propria:
            tag_nome = "propria_privada_nome" if privada else "propria_nome"
            t.insert("end", f"Você · {hora}\n", tag_nome)
            t.insert("end", f"{texto}\n\n", "propria_texto")
        else:
            tag_nome = "outro_privada_nome" if privada else "outro_nome"
            t.insert("end", f"{quem} · {hora}\n", tag_nome)
            t.insert("end", f"{texto}\n\n", "outro_texto")
        t.config(state="disabled")
        t.see("end")

    def _inserir_linha_widget(self, texto, tag) -> None:
        t = self.texto_chat
        t.config(state="normal")
        t.insert("end", f"{texto}\n\n", tag)
        t.config(state="disabled")
        t.see("end")

    # ====================================================================
    # Envio de mensagens e indicador de "digitando..."
    # ====================================================================

    def _enviar(self, evento=None) -> None:
        if not self.conectado:
            return
        texto = self.var_mensagem.get().strip()
        if not texto:
            return

        conversa = self.conversa_atual
        if conversa[0] == "privada":
            payload = {"tipo": "PRIVADA", "destino": conversa[1], "texto": texto}
        else:
            payload = {"tipo": "MSG", "texto": texto}

        try:
            protocolo.enviar(self.sock, payload)
        except OSError as erro:
            self._linha(conversa, f"Não foi possível enviar: conexão perdida ({erro}).", "erro")
            self._ao_desconectar()
            return

        self._bolha(conversa, self.usuario, texto, _hora_agora(), propria=True)
        self.var_mensagem.set("")

    def _ao_digitar(self, evento=None) -> None:
        if not self.conectado:
            return
        if evento is not None and evento.keysym in ("Return", "Tab"):
            return
        agora = time.monotonic()
        if agora - self._ultimo_envio_digitando < INTERVALO_MINIMO_ENVIO_DIGITANDO:
            return
        self._ultimo_envio_digitando = agora

        conversa = self.conversa_atual
        payload = {"tipo": "DIGITANDO"}
        if conversa[0] == "privada":
            payload["destino"] = conversa[1]
        try:
            protocolo.enviar(self.sock, payload)
        except OSError:
            pass

    def _atualizar_indicador_digitando(self) -> None:
        if self._fechando:
            return
        if hasattr(self, "rotulo_digitando"):
            agora = time.monotonic()
            ativos = self.digitando.get(self.conversa_atual, {})
            for usuario_ativo in list(ativos):
                if ativos[usuario_ativo] <= agora:
                    del ativos[usuario_ativo]
            nomes = list(ativos.keys())
            if not nomes:
                texto = ""
            elif len(nomes) == 1:
                texto = f"{nomes[0]} está digitando..."
            else:
                texto = f"{', '.join(nomes[:-1])} e {nomes[-1]} estão digitando..."
            self.rotulo_digitando.config(text=texto)
        self.root.after(500, self._atualizar_indicador_digitando)

    # ====================================================================
    # Notificações (toast)
    # ====================================================================

    def _mostrar_toast(self, texto: str, ao_clicar=None, cor=None) -> None:
        cor = cor or COR_DESTAQUE
        cursor = "hand2" if ao_clicar else "arrow"

        toast = tk.Frame(self.container, bg=cor, cursor=cursor)
        rotulo = tk.Label(
            toast, text=texto, bg=cor, fg="white", font=FONTE_NEGRITO,
            padx=16, pady=12, wraplength=260, justify="left", cursor=cursor,
        )
        rotulo.pack()
        self._toasts_ativos.append(toast)
        self._reempilhar_toasts()

        def _remover(*_args):
            if toast in self._toasts_ativos:
                self._toasts_ativos.remove(toast)
            if toast.winfo_exists():
                toast.destroy()
            self._reempilhar_toasts()

        if ao_clicar:
            def _ao_clique(_evento):
                ao_clicar()
                _remover()
            rotulo.bind("<Button-1>", _ao_clique)
            toast.bind("<Button-1>", _ao_clique)

        toast.after(4200, _remover)

    def _reempilhar_toasts(self) -> None:
        for i, toast in enumerate(self._toasts_ativos):
            if toast.winfo_exists():
                toast.place(in_=self.container, relx=1.0, rely=1.0, anchor="se", x=-18, y=-18 - (64 * i))

    # ====================================================================
    # Encerramento / reconexão
    # ====================================================================

    def _ao_desconectar(self) -> None:
        self.conectado = False
        self.rodando = False
        try:
            if self.sock:
                self.sock.close()
        except OSError:
            pass

        if self._fechando:
            return

        if self.frame_chat is not None:
            self.frame_chat.destroy()
            self.frame_chat = None

        self.sala = protocolo.SALA_PADRAO
        self.conversa_atual = ("sala", self.sala)
        self.conversas = {}
        self.contatos_privados = {}
        self.ordem_privados = []
        self.digitando = {}
        self._toasts_ativos = []

        self._montar_tela_login()
        self.rotulo_status_login.config(text="A conexão com o servidor foi encerrada.")

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
