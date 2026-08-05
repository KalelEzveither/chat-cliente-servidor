# -*- coding: utf-8 -*-
"""
cliente/cliente_gui.py

Cliente de chat cliente-servidor com INTERFACE GRAFICA (Tkinter), implementando
o item opcional do enunciado ("Interface grafica (GUI) em vez de terminal").

Usa exatamente o mesmo protocolo de aplicacao definido em `comum/protocolo.py`
e o mesmo servidor de `servidor/servidor.py` -- este e apenas um "front-end"
alternativo ao `cliente/cliente.py` (modo texto).

Bibliotecas usadas: apenas a biblioteca padrao do Python (tkinter, socket,
threading, queue, time, argparse), sem dependencias externas.

Uso:
    python3 cliente_gui.py [--host <IP_DO_SERVIDOR>] [--porta <PORTA>] [--usuario <APELIDO>]

    Os argumentos sao opcionais e servem apenas para pre-preencher os campos
    da tela de conexao -- a conexao so acontece quando o usuario clica em
    "Entrar". O IP nunca fica fixo no codigo, atendendo ao requisito de
    testar em maquinas distintas do laboratorio.

Recursos desta interface:
    - Aba "Usuários": quem está na sala atual; clicar em alguém abre uma
      conversa PRIVADA com essa pessoa.
    - Aba "Salas": todas as salas com gente conectada agora, com contagem
      de usuários; clicar entra nela (ou cria uma nova, se o nome digitado
      ainda não existir).
    - Aba "Privadas": conversas privadas já iniciadas, com indicador de
      quantas mensagens não lidas há em cada uma.
    - Navegação por "breadcrumb" no topo da conversa (# sala / › contato)
      -- sempre visível, um clique volta para a sala a qualquer momento.
    - Histórico de cada conversa privada isolado da conversa da sala: cada
      uma tem sua própria linha do tempo.
    - Indicador de "fulano está digitando..." e notificação (toast) de
      mensagem privada nova, com contador de não lidas.
    - Janela dimensionada dinamicamente com base na resolução real da
      tela (e com reconhecimento de DPI no Windows), para nunca abrir
      maior do que a tela do usuário.

Arquitetura da GUI:
    - Thread principal: roda o loop de eventos do Tkinter (mainloop) e e a
      UNICA thread que pode mexer nos widgets (regra do Tkinter).
    - Thread de conexao: dispara a conexao/login em segundo plano para nao
      travar a janela enquanto espera resposta do servidor.
    - Thread de recepcao: fica bloqueada em recv() esperando mensagens do
      servidor durante toda a sessao, e as coloca numa fila (queue.Queue).
    - A thread principal consome essa fila periodicamente (root.after) e so
      ai atualiza a tela -- assim nunca se mexe em widget fora da thread
      principal.
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

# Reconhecimento de DPI no Windows: sem isso, o Windows pode escalar a
# janela toda (ex.: 125%/150%) sem o Tkinter saber, fazendo a janela
# "vazar" para baixo da tela visivel -- e foi exatamente esse o motivo do
# campo de mensagem parecer sumir, obrigando a redimensionar a janela na
# mao. Isso precisa rodar ANTES de qualquer janela Tk ser criada.
if sys.platform == "win32":
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


# ------------------------------------------------------------------------ #
# Paleta e tipografia
#
# Grafite quente (nao azul-marinho) + um unico par de cores de destaque com
# significado proprio: verde-azulado (teal) = "publico" (sala/voce), ambar
# = "privado". Fundo do chat em papel creme, nao branco/azulado frio.
# ------------------------------------------------------------------------ #
COR_FUNDO = "#211f1b"
COR_PAINEL = "#2a2823"
COR_PAINEL_2 = "#34312a"
COR_CAMPO = "#3d392f"
COR_BORDA = "#4a4638"
COR_TEXTO = "#efe9dc"
COR_TEXTO_SUAVE = "#a39d8a"
COR_DESTAQUE = "#0d9488"
COR_DESTAQUE_HOVER = "#0f766e"
COR_PRIVADA = "#b45309"
COR_PRIVADA_HOVER = "#92400e"
COR_SUCESSO = "#65a30d"
COR_ERRO = "#dc2626"
COR_CHAT_FUNDO = "#faf7f1"
COR_BOLHA_TXT = "#28241d"
COR_AVATAR_NEUTRO = "#57503f"
COR_SAIR_BG = "#3a2621"
COR_SAIR_FG = "#f0b6a4"
COR_SAIR_BG_HOVER = "#4a2f28"

FONTE_DISPLAY = ("Georgia", 22, "bold")
FONTE_NOME_TOPO = ("Georgia", 14, "bold")
FONTE_NOME_CHIP = ("Segoe UI", 10, "bold")
FONTE_BASE = ("Segoe UI", 10)
FONTE_NEGRITO = ("Segoe UI", 10, "bold")
FONTE_PEQUENA = ("Segoe UI", 8)
FONTE_PEQUENA_IT = ("Segoe UI", 8, "italic")
FONTE_MENSAGEM = ("Segoe UI", 10)
FONTE_ROTULO_ABA = ("Segoe UI", 8, "bold")

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
    estilo.configure("Chat.Vertical.TScrollbar", background=COR_PAINEL_2, troughcolor=COR_PAINEL, borderwidth=0, arrowsize=12)


def _hora_agora() -> str:
    return time.strftime("%H:%M")


def _inicial(nome: str) -> str:
    return (nome[:1] or "?").upper()


def _criar_avatar(parent, nome: str, bg_pai: str, tamanho: int = 30, destaque: bool = False) -> tk.Canvas:
    """Desenha um avatar circular simples (iniciais) num Canvas pequeno.
    Evita depender de emojis/ícones prontos para identificar pessoas."""
    canvas = tk.Canvas(parent, width=tamanho, height=tamanho, bg=bg_pai, highlightthickness=0, bd=0)
    cor = COR_DESTAQUE if destaque else COR_AVATAR_NEUTRO
    canvas.create_oval(1, 1, tamanho - 1, tamanho - 1, fill=cor, outline="")
    canvas.create_text(
        tamanho / 2, tamanho / 2 + 1, text=_inicial(nome), fill="white",
        font=("Segoe UI", max(9, int(tamanho * 0.4)), "bold"),
    )
    return canvas


def _tornar_clicavel(widgets, ao_clicar, cor_normal, cor_hover) -> None:
    """Vincula clique + destaque ao passar o mouse a um conjunto de widgets
    que formam uma única "linha" clicável (usado nas listas da barra
    lateral)."""
    def _entrar(_evento=None):
        for w in widgets:
            try:
                w.configure(bg=cor_hover)
            except tk.TclError:
                pass

    def _sair(_evento=None):
        for w in widgets:
            try:
                w.configure(bg=cor_normal)
            except tk.TclError:
                pass

    def _clicar(_evento=None):
        ao_clicar()

    for w in widgets:
        w.bind("<Enter>", _entrar)
        w.bind("<Leave>", _sair)
        w.bind("<Button-1>", _clicar)
        try:
            w.configure(cursor="hand2")
        except tk.TclError:
            pass


class ListaRolavel(tk.Frame):
    """Painel com rolagem vertical para empilhar linhas customizadas
    (usado nas três listas da barra lateral: usuários, salas e privadas).
    Tk não tem um widget de lista "rica" pronto -- isso é o padrão comum
    para simular um com Canvas + Frame interno + Scrollbar."""

    def __init__(self, parent, bg: str):
        super().__init__(parent, bg=bg)
        self._bg = bg
        self.canvas = tk.Canvas(self, bg=bg, highlightthickness=0, bd=0)
        self.scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview, style="Chat.Vertical.TScrollbar")
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        self.scrollbar.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)

        self.frame_interno = tk.Frame(self.canvas, bg=bg)
        self._janela = self.canvas.create_window((0, 0), window=self.frame_interno, anchor="nw")
        self.frame_interno.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfig(self._janela, width=e.width))
        self.canvas.bind("<Enter>", lambda e: self.canvas.bind_all("<MouseWheel>", self._rolar))
        self.canvas.bind("<Leave>", lambda e: self.canvas.unbind_all("<MouseWheel>"))

    def _rolar(self, evento) -> None:
        self.canvas.yview_scroll(int(-1 * (evento.delta / 120)), "units")

    def limpar(self) -> None:
        for w in self.frame_interno.winfo_children():
            w.destroy()


class ClienteChatGUI:
    """Janela principal do cliente de chat gráfico."""

    def __init__(self, root, host: str, porta, usuario: str):
        self.root = root
        self.root.title("Sala de Chat")
        self._ajustar_geometria_a_tela()
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

        self.container = tk.Frame(self.root, bg=COR_FUNDO)
        self.container.pack(fill="both", expand=True)

        self.frame_login = None
        self.frame_chat = None
        self._montar_tela_login()

        self.root.protocol("WM_DELETE_WINDOW", self._sair)
        self.root.after(100, self._processar_fila)
        self.root.after(500, self._atualizar_indicador_digitando)

    def _ajustar_geometria_a_tela(self) -> None:
        """Calcula um tamanho de janela que cabe confortavelmente na tela
        do usuário (com folga para barra de tarefas etc.) e centraliza,
        em vez de usar um tamanho fixo que pode ultrapassar telas menores
        ou telas com escala de DPI diferente."""
        largura_tela = self.root.winfo_screenwidth()
        altura_tela = self.root.winfo_screenheight()
        largura = max(760, min(1020, largura_tela - 100))
        altura = max(480, min(640, altura_tela - 140))
        x = max(0, (largura_tela - largura) // 2)
        y = max(0, (altura_tela - altura) // 2)
        self.root.geometry(f"{largura}x{altura}+{x}+{y}")
        self.root.minsize(min(720, largura), min(440, altura))

    # ====================================================================
    # TELA DE LOGIN
    # ====================================================================

    def _montar_tela_login(self) -> None:
        self.frame_login = tk.Frame(self.container, bg=COR_FUNDO)
        self.frame_login.pack(fill="both", expand=True)

        card = tk.Frame(self.frame_login, bg=COR_PAINEL, padx=42, pady=36)
        card.place(relx=0.5, rely=0.45, anchor="center")

        tk.Label(card, text="Sala de Chat", font=FONTE_DISPLAY, bg=COR_PAINEL, fg=COR_TEXTO).pack()
        tk.Frame(card, bg=COR_DESTAQUE, width=38, height=3).pack(pady=(8, 12))
        tk.Label(
            card, text="REDES DE COMPUTADORES II", font=("Segoe UI", 8, "bold"),
            bg=COR_PAINEL, fg=COR_TEXTO_SUAVE,
        ).pack(pady=(0, 26))

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
        self.entrada_host.focus_set()

    def _campo_login(self, parent, rotulo, variavel):
        tk.Label(parent, text=rotulo, font=FONTE_BASE, bg=COR_PAINEL, fg=COR_TEXTO, anchor="w").pack(fill="x")
        entrada = tk.Entry(
            parent, textvariable=variavel, font=FONTE_BASE, bg=COR_CAMPO, fg=COR_TEXTO,
            insertbackground=COR_TEXTO, relief="flat", bd=0,
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
        topo = tk.Frame(self.frame_chat, bg=COR_PAINEL, height=58)
        topo.pack(fill="x", side="top")
        topo.pack_propagate(False)

        av = _criar_avatar(topo, self.usuario, bg_pai=COR_PAINEL, tamanho=34, destaque=True)
        av.pack(side="left", padx=(18, 10), pady=12)
        tk.Label(topo, text=self.usuario, font=FONTE_NOME_TOPO, bg=COR_PAINEL, fg=COR_TEXTO).pack(side="left", pady=12)

        lado_direito = tk.Frame(topo, bg=COR_PAINEL)
        lado_direito.pack(side="right", padx=18)
        pontinho = tk.Canvas(lado_direito, width=8, height=8, bg=COR_PAINEL, highlightthickness=0, bd=0)
        pontinho.create_oval(0, 0, 8, 8, fill=COR_SUCESSO, outline="")
        pontinho.pack(side="left", padx=(0, 6))
        tk.Label(lado_direito, text=f"{host}:{porta}", font=FONTE_PEQUENA, bg=COR_PAINEL, fg=COR_TEXTO_SUAVE).pack(side="left")

    def _montar_sidebar(self, parent) -> None:
        painel = tk.Frame(parent, bg=COR_PAINEL, width=300)
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

    def _cabecalho_aba(self, aba, texto, com_atualizar=None):
        cabecalho = tk.Frame(aba, bg=COR_PAINEL)
        cabecalho.pack(fill="x", padx=10, pady=(10, 6))
        tk.Label(cabecalho, text=texto, font=FONTE_ROTULO_ABA, bg=COR_PAINEL, fg=COR_TEXTO_SUAVE).pack(side="left")
        if com_atualizar:
            tk.Button(
                cabecalho, text="↻", font=FONTE_PEQUENA, bg=COR_PAINEL, fg=COR_TEXTO_SUAVE,
                relief="flat", bd=0, cursor="hand2", command=com_atualizar,
            ).pack(side="right")
        return cabecalho

    def _montar_aba_usuarios(self, aba) -> None:
        self._cabecalho_aba(aba, "SALA ATUAL", com_atualizar=self._solicitar_lista)
        self.rotulo_sala_atual_aba = tk.Label(
            aba, text=f"# {self.sala}", font=("Georgia", 12, "bold"), bg=COR_PAINEL, fg=COR_DESTAQUE, anchor="w"
        )
        self.rotulo_sala_atual_aba.pack(fill="x", padx=12, pady=(0, 8))

        tk.Label(
            aba, text="Clique em alguém para abrir uma conversa privada.",
            font=FONTE_PEQUENA, bg=COR_PAINEL, fg=COR_TEXTO_SUAVE, wraplength=230, justify="left", anchor="w",
        ).pack(side="bottom", fill="x", padx=12, pady=(6, 10))

        self.lista_usuarios = ListaRolavel(aba, bg=COR_PAINEL)
        self.lista_usuarios.pack(fill="both", expand=True, padx=8)

    def _montar_aba_salas(self, aba) -> None:
        self._cabecalho_aba(aba, "SALAS COM GENTE CONECTADA", com_atualizar=self._solicitar_lista_salas)

        tk.Label(
            aba, text="Nome de sala nova = ela é criada na hora.", font=FONTE_PEQUENA_IT,
            bg=COR_PAINEL, fg=COR_TEXTO_SUAVE, anchor="w",
        ).pack(side="bottom", fill="x", padx=12, pady=(0, 10))

        linha_nova_sala = tk.Frame(aba, bg=COR_PAINEL)
        linha_nova_sala.pack(side="bottom", fill="x", padx=12, pady=(10, 4))
        self.var_nova_sala = tk.StringVar()
        entrada_nova_sala = tk.Entry(
            linha_nova_sala, textvariable=self.var_nova_sala, font=FONTE_BASE, bg=COR_CAMPO, fg=COR_TEXTO,
            insertbackground=COR_TEXTO, relief="flat", bd=0,
        )
        entrada_nova_sala.pack(side="left", fill="x", expand=True, ipady=6)
        entrada_nova_sala.bind("<Return>", self._ao_trocar_sala)
        tk.Button(
            linha_nova_sala, text="Entrar", font=("Segoe UI", 9, "bold"), bg=COR_DESTAQUE, fg="white",
            activebackground=COR_DESTAQUE_HOVER, activeforeground="white", relief="flat", bd=0,
            cursor="hand2", command=self._ao_trocar_sala,
        ).pack(side="left", padx=(6, 0))

        self.lista_salas = ListaRolavel(aba, bg=COR_PAINEL)
        self.lista_salas.pack(fill="both", expand=True, padx=8)

    def _montar_aba_privadas(self, aba) -> None:
        self._cabecalho_aba(aba, "SUAS CONVERSAS PRIVADAS")

        tk.Label(
            aba, text="Uma conversa aparece aqui assim que você ou a outra pessoa mandarem a primeira mensagem privada.",
            font=FONTE_PEQUENA, bg=COR_PAINEL, fg=COR_TEXTO_SUAVE, wraplength=230, justify="left", anchor="w",
        ).pack(side="bottom", fill="x", padx=12, pady=(6, 10))

        self.lista_privadas = ListaRolavel(aba, bg=COR_PAINEL)
        self.lista_privadas.pack(fill="both", expand=True, padx=8)

    # ---- Área de conversa (direita) -------------------------------------

    def _montar_area_conversa(self, parent) -> None:
        area = tk.Frame(parent, bg=COR_FUNDO)
        area.pack(side="left", fill="both", expand=True)

        barra_nav = tk.Frame(area, bg=COR_FUNDO)
        barra_nav.pack(fill="x")

        self.chip_sala = tk.Label(
            barra_nav, text=f"# {self.sala}", font=FONTE_NOME_CHIP, padx=14, pady=6, cursor="hand2",
        )
        self.chip_sala.pack(side="left", padx=(18, 0), pady=12)
        self.chip_sala.bind("<Button-1>", lambda e: self._voltar_para_sala())

        self.separador_nav = tk.Label(barra_nav, text="›", font=("Segoe UI", 12), bg=COR_FUNDO, fg=COR_TEXTO_SUAVE)
        self.chip_privada = tk.Label(barra_nav, text="", font=FONTE_NOME_CHIP, padx=14, pady=6)

        self.rotulo_digitando = tk.Label(
            area, text="", font=FONTE_PEQUENA_IT, bg=COR_FUNDO, fg=COR_TEXTO_SUAVE, anchor="w", padx=18,
        )
        self.rotulo_digitando.pack(fill="x")

        # IMPORTANTE: o rodapé (caixa de mensagem) é empacotado ANTES da
        # área de texto que se expande (fill="both", expand=True). Um
        # widget com expand=True reivindica toda a área ainda livre no
        # momento em que é empacotado -- se ele for empacotado primeiro,
        # não sobra espaço reservado para quem vem depois, mesmo usando
        # side="bottom". Empacotar o rodapé primeiro garante que o espaço
        # dele já fique reservado, e a área de texto simplesmente preenche
        # o que sobrar -- assim a caixa de mensagem nunca fica escondida
        # abaixo da borda da janela, mesmo em telas pequenas.
        rodape = tk.Frame(area, bg=COR_PAINEL, height=64)
        rodape.pack(fill="x", side="bottom")
        rodape.pack_propagate(False)

        self.var_mensagem = tk.StringVar()
        self.entrada_mensagem = tk.Entry(
            rodape, textvariable=self.var_mensagem, font=FONTE_BASE, bg=COR_CAMPO, fg=COR_TEXTO,
            insertbackground=COR_TEXTO, relief="flat", bd=0,
        )
        self.entrada_mensagem.pack(side="left", fill="both", expand=True, padx=(16, 8), pady=14, ipady=6)
        self.entrada_mensagem.bind("<Return>", self._enviar)
        self.entrada_mensagem.bind("<KeyRelease>", self._ao_digitar)

        tk.Button(
            rodape, text="Enviar", font=FONTE_NEGRITO, bg=COR_DESTAQUE, fg="white",
            activebackground=COR_DESTAQUE_HOVER, activeforeground="white", relief="flat", bd=0,
            cursor="hand2", command=self._enviar, padx=18,
        ).pack(side="right", padx=(0, 10), pady=14)

        tk.Button(
            rodape, text="Sair", font=FONTE_NEGRITO, bg=COR_SAIR_BG, fg=COR_SAIR_FG,
            activebackground=COR_SAIR_BG_HOVER, activeforeground=COR_SAIR_FG, relief="flat", bd=0,
            cursor="hand2", command=self._sair, padx=14,
        ).pack(side="right", padx=(0, 4), pady=14)

        frame_mensagens = tk.Frame(area, bg=COR_CHAT_FUNDO)
        frame_mensagens.pack(fill="both", expand=True)

        self.texto_chat = tk.Text(
            frame_mensagens, font=FONTE_MENSAGEM, bg=COR_CHAT_FUNDO, fg=COR_BOLHA_TXT,
            relief="flat", bd=0, wrap="word", state="disabled", padx=18, pady=14, spacing3=6,
        )
        scroll = ttk.Scrollbar(frame_mensagens, command=self.texto_chat.yview, style="Chat.Vertical.TScrollbar")
        self.texto_chat.configure(yscrollcommand=scroll.set)
        self.texto_chat.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self._configurar_tags_texto()

    def _configurar_tags_texto(self) -> None:
        t = self.texto_chat
        t.tag_configure("propria_nome", justify="right", foreground=COR_DESTAQUE, font=FONTE_NEGRITO, spacing1=10)
        t.tag_configure("propria_texto", justify="right", foreground=COR_BOLHA_TXT, font=FONTE_MENSAGEM)
        t.tag_configure("outro_nome", justify="left", foreground="#57503f", font=FONTE_NEGRITO, spacing1=10)
        t.tag_configure("outro_texto", justify="left", foreground=COR_BOLHA_TXT, font=FONTE_MENSAGEM)
        t.tag_configure("outro_privada_nome", justify="left", foreground=COR_PRIVADA, font=FONTE_NEGRITO, spacing1=10)
        t.tag_configure("sistema", justify="center", foreground="#8a8371", font=("Segoe UI", 9, "italic"), spacing1=6)
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
                    f"Nova mensagem de {de}", avatar_nome=de, cor=COR_PRIVADA,
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
            self._mostrar_toast(mensagem.get("motivo", "Não foi possível trocar de sala."), cor=COR_ERRO)

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

    def _ao_clicar_sala(self, nome: str) -> None:
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
        self.rotulo_sala_atual_aba.config(text=f"# {sala}")

        self._linha(("sala", sala), f"Você entrou na sala '{sala}'.", "sistema")

        if estava_vendo_sala or sala_antiga == sala:
            self._selecionar_conversa(("sala", sala))
        else:
            self.chip_sala.config(text=f"# {self.sala}")

        self._solicitar_lista()
        self._solicitar_lista_salas()

    def _voltar_para_sala(self) -> None:
        self._selecionar_conversa(("sala", self.sala))

    # ====================================================================
    # Lista de usuários da sala / lista de salas / lista de privadas
    # (listas customizadas com avatar, não Listbox nativo)
    # ====================================================================

    def _atualizar_lista_usuarios(self, usuarios: list) -> None:
        self.lista_usuarios.limpar()
        nomes = sorted(nome for nome in usuarios if nome != self.usuario)
        pai = self.lista_usuarios.frame_interno
        for nome in nomes:
            linha = tk.Frame(pai, bg=COR_PAINEL)
            av = _criar_avatar(linha, nome, bg_pai=COR_PAINEL, tamanho=28)
            av.pack(side="left", padx=(8, 8), pady=7)
            lbl = tk.Label(linha, text=nome, font=FONTE_BASE, bg=COR_PAINEL, fg=COR_TEXTO, anchor="w")
            lbl.pack(side="left", fill="x", expand=True, pady=7)
            linha.pack(fill="x")
            _tornar_clicavel([linha, av, lbl], lambda nm=nome: self._ao_clicar_usuario(nm), COR_PAINEL, COR_PAINEL_2)

    def _ao_clicar_usuario(self, nome: str) -> None:
        self._registrar_contato_privado(nome)
        self._selecionar_conversa(("privada", nome))
        self.notebook.select(self.aba_privadas)

    def _atualizar_lista_salas(self, salas: list) -> None:
        self.lista_salas.limpar()
        pai = self.lista_salas.frame_interno
        for s in salas:
            nome, n = s["nome"], s["usuarios"]
            ativa = nome == self.sala
            linha = tk.Frame(pai, bg=COR_PAINEL)
            marca = tk.Label(
                linha, text="#", font=("Georgia", 13, "bold"), bg=COR_PAINEL,
                fg=(COR_DESTAQUE if ativa else COR_TEXTO_SUAVE), width=2,
            )
            marca.pack(side="left", padx=(8, 0), pady=7)
            lbl = tk.Label(
                linha, text=nome, font=(FONTE_NEGRITO if ativa else FONTE_BASE), bg=COR_PAINEL,
                fg=(COR_DESTAQUE if ativa else COR_TEXTO), anchor="w",
            )
            lbl.pack(side="left", fill="x", expand=True, pady=7)
            badge = tk.Label(linha, text=str(n), font=FONTE_PEQUENA, bg=COR_PAINEL_2, fg=COR_TEXTO_SUAVE, padx=6)
            badge.pack(side="right", padx=(0, 8))
            linha.pack(fill="x")
            _tornar_clicavel([linha, marca, lbl], lambda nm=nome: self._ao_clicar_sala(nm), COR_PAINEL, COR_PAINEL_2)

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
        self.lista_privadas.limpar()
        pai = self.lista_privadas.frame_interno
        for nome in self.ordem_privados:
            n = self.contatos_privados.get(nome, 0)
            linha = tk.Frame(pai, bg=COR_PAINEL)
            av = _criar_avatar(linha, nome, bg_pai=COR_PAINEL, tamanho=28)
            av.pack(side="left", padx=(8, 8), pady=7)
            lbl = tk.Label(
                linha, text=nome, font=(FONTE_NEGRITO if n > 0 else FONTE_BASE), bg=COR_PAINEL,
                fg=(COR_PRIVADA if n > 0 else COR_TEXTO), anchor="w",
            )
            lbl.pack(side="left", fill="x", expand=True, pady=7)
            widgets_linha = [linha, av, lbl]
            if n > 0:
                badge = tk.Label(linha, text=str(n), font=("Segoe UI", 8, "bold"), bg=COR_PRIVADA, fg="white", padx=6, pady=1)
                badge.pack(side="right", padx=(0, 8))
                widgets_linha.append(badge)
            linha.pack(fill="x")
            _tornar_clicavel(widgets_linha, lambda nm=nome: self._ao_clicar_privado(nm), COR_PAINEL, COR_PAINEL_2)

    def _ao_clicar_privado(self, nome: str) -> None:
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
        self.chip_sala.config(text=f"# {self.sala}")

        if conversa_id[0] == "sala":
            self.chip_sala.config(bg=COR_DESTAQUE, fg="white")
            self.separador_nav.pack_forget()
            self.chip_privada.pack_forget()
        else:
            nome = conversa_id[1]
            self.chip_sala.config(bg=COR_FUNDO, fg=COR_DESTAQUE)
            self.chip_privada.config(text=nome, bg=COR_PRIVADA, fg="white")
            self.separador_nav.pack(side="left", pady=12)
            self.chip_privada.pack(side="left", pady=12)
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
            t.insert("end", f"Você · {hora}\n", "propria_nome")
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

    def _mostrar_toast(self, texto: str, ao_clicar=None, cor=None, avatar_nome=None) -> None:
        cor = cor or COR_DESTAQUE
        cursor = "hand2" if ao_clicar else "arrow"

        toast = tk.Frame(self.container, bg=COR_PAINEL, highlightbackground=cor, highlightthickness=1, cursor=cursor)
        barra = tk.Frame(toast, bg=cor, width=4)
        barra.pack(side="left", fill="y")
        conteudo = tk.Frame(toast, bg=COR_PAINEL, cursor=cursor)
        conteudo.pack(side="left", fill="both", expand=True)

        widgets = [toast, barra, conteudo]
        if avatar_nome:
            av = _criar_avatar(conteudo, avatar_nome, bg_pai=COR_PAINEL, tamanho=26)
            av.pack(side="left", padx=(10, 8), pady=10)
            widgets.append(av)
        rotulo = tk.Label(
            conteudo, text=texto, bg=COR_PAINEL, fg=COR_TEXTO, font=FONTE_BASE,
            padx=(0 if avatar_nome else 14), pady=10, wraplength=230, justify="left", cursor=cursor,
        )
        rotulo.pack(side="left", fill="both", expand=True, padx=(0, 12))
        widgets.append(rotulo)

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
            for w in widgets:
                w.bind("<Button-1>", _ao_clique)

        toast.after(4200, _remover)

    def _reempilhar_toasts(self) -> None:
        for i, toast in enumerate(self._toasts_ativos):
            if toast.winfo_exists():
                toast.place(in_=self.container, relx=1.0, rely=1.0, anchor="se", x=-18, y=-18 - (60 * i))

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
