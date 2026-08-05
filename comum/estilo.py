# -*- coding: utf-8 -*-
"""
comum/estilo.py

Sistema de estilo COMPARTILHADO por todas as janelas do projeto: o cliente
gráfico, o servidor gráfico e a tela inicial (launcher). Existe para
garantir uma identidade visual única e consistente -- mesma paleta de
cores, mesma tipografia, mesmos componentes -- em vez de cada tela ter o
seu próprio estilo isolado.

Qualquer alteração de cor/fonte/marca feita aqui se propaga automaticamente
para as três janelas.
"""

import sys
import time
import tkinter as tk
from tkinter import ttk

# Nome do aplicativo (usado como marca dentro das janelas). Propositalmente
# NÃO é usado como texto da barra de título do sistema operacional -- ver
# `aplicar_janela_base()` abaixo.
NOME_APP = "Fala Daí"
SUBTITULO_APP = "REDES DE COMPUTADORES II"

# Reconhecimento de DPI no Windows: sem isso, o Windows pode escalar a
# janela toda (ex.: 125%/150%) sem o Tkinter saber, fazendo partes da
# janela "vazarem" para fora da tela visível. Roda uma única vez, na
# primeira vez que qualquer janela do app importa este módulo -- sempre
# antes de qualquer janela Tk ser criada.
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
# Paleta
#
# Grafite quente (não azul-marinho) + um único par de cores de destaque com
# significado próprio: verde-azulado (teal) = ação principal/"público",
# âmbar = privado/atenção. Fundo de conteúdo em papel creme, não branco frio.
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
COR_AVISO = "#c98a1a"
COR_CONTEUDO_FUNDO = "#faf7f1"
COR_CONTEUDO_TXT = "#28241d"
COR_AVATAR_NEUTRO = "#57503f"
COR_PERIGO_BG = "#3a2621"
COR_PERIGO_FG = "#f0b6a4"
COR_PERIGO_BG_HOVER = "#4a2f28"

# ------------------------------------------------------------------------ #
# Tipografia: serifada (Georgia) para a marca/títulos, Segoe UI para
# interface/corpo, Consolas para conteúdo tipo log/console.
# ------------------------------------------------------------------------ #
FONTE_DISPLAY = ("Georgia", 22, "bold")
FONTE_MARCA_PEQUENA = ("Georgia", 15, "bold")
FONTE_NOME_TOPO = ("Georgia", 14, "bold")
FONTE_NOME_CHIP = ("Segoe UI", 10, "bold")
FONTE_BASE = ("Segoe UI", 10)
FONTE_NEGRITO = ("Segoe UI", 10, "bold")
FONTE_PEQUENA = ("Segoe UI", 8)
FONTE_PEQUENA_IT = ("Segoe UI", 8, "italic")
FONTE_MENSAGEM = ("Segoe UI", 10)
FONTE_ROTULO_ABA = ("Segoe UI", 8, "bold")
FONTE_MONO = ("Consolas", 9)

_ESTILO_CONFIGURADO = False


def configurar_estilo_ttk() -> None:
    """Configura estilos ttk nomeados ('Fala.*'), usados pelas poucas
    situações em que um widget ttk é necessário (abas/Notebook, Scrollbar,
    barra de progresso). Não altera o tema padrão do ttk globalmente além
    do necessário, então é seguro chamar em qualquer uma das janelas."""
    global _ESTILO_CONFIGURADO
    if _ESTILO_CONFIGURADO:
        return
    _ESTILO_CONFIGURADO = True

    estilo = ttk.Style()
    try:
        estilo.theme_use("clam")
    except tk.TclError:
        pass

    estilo.configure("Fala.TNotebook", background=COR_PAINEL, borderwidth=0)
    estilo.configure(
        "Fala.TNotebook.Tab",
        background=COR_PAINEL_2, foreground=COR_TEXTO_SUAVE,
        padding=(12, 7), font=("Segoe UI", 9, "bold"), borderwidth=0,
    )
    estilo.map(
        "Fala.TNotebook.Tab",
        background=[("selected", COR_DESTAQUE)],
        foreground=[("selected", "white")],
    )
    estilo.configure("Fala.TFrame", background=COR_PAINEL)
    estilo.configure(
        "Fala.Vertical.TScrollbar",
        background=COR_PAINEL_2, troughcolor=COR_PAINEL, borderwidth=0, arrowsize=12,
    )
    estilo.configure(
        "Fala.Horizontal.TProgressbar",
        background=COR_DESTAQUE, troughcolor=COR_PAINEL_2, borderwidth=0,
    )


def aplicar_janela_base(root, tamanho=None, centralizar=True) -> None:
    """Aplica o essencial que toda janela do app deve ter: SEM nome extra
    na barra de título do sistema operacional (apenas o ícone padrão),
    fundo consistente e tema ttk configurado. Se `tamanho` for informado
    (largura, altura), redimensiona e opcionalmente centraliza a janela
    na tela do usuário."""
    root.title("")
    root.configure(bg=COR_FUNDO)
    configurar_estilo_ttk()

    if tamanho:
        largura, altura = tamanho
        if centralizar:
            largura_tela = root.winfo_screenwidth()
            altura_tela = root.winfo_screenheight()
            x = max(0, (largura_tela - largura) // 2)
            y = max(0, (altura_tela - altura) // 2)
            root.geometry(f"{largura}x{altura}+{x}+{y}")
        else:
            root.geometry(f"{largura}x{altura}")


def geometria_ajustada_a_tela(root, largura_alvo, altura_alvo, largura_min=760, altura_min=480, margem=100, margem_v=140):
    """Calcula (e aplica) um tamanho de janela que cabe confortavelmente
    na tela do usuário -- nunca maior do que ela --, e centraliza. Evita
    usar um tamanho fixo que pode ultrapassar telas menores ou telas com
    escala de DPI diferente."""
    largura_tela = root.winfo_screenwidth()
    altura_tela = root.winfo_screenheight()
    largura = max(largura_min, min(largura_alvo, largura_tela - margem))
    altura = max(altura_min, min(altura_alvo, altura_tela - margem_v))
    x = max(0, (largura_tela - largura) // 2)
    y = max(0, (altura_tela - altura) // 2)
    root.geometry(f"{largura}x{altura}+{x}+{y}")
    root.minsize(min(largura_min, largura), min(altura_min, altura))
    return largura, altura


def ajustar_ao_conteudo(root, margem=20, minimo=(0, 0)) -> None:
    """Redimensiona e centraliza a janela para caber exatamente o que foi
    montado nela (mais uma pequena margem de folga), em vez de usar um
    tamanho fixo "chutado" na hora de escrever o código. Isso importa
    porque fontes diferentes (Windows/macOS/Linux têm métricas um pouco
    diferentes para a mesma fonte, e podem até substituir por outra se a
    fonte pedida não existir) podem precisar de mais ou menos espaço do
    que o esperado -- um tamanho fixo que "coube" num sistema pode cortar
    botões em outro. Deve ser chamada DEPOIS que todos os widgets da
    janela já foram criados e empacotados.

    Só é confiável em janelas que não usam `pack_propagate(False)` (que
    "esconde" o tamanho real dos filhos do cálculo) -- é o caso do
    launcher, que é só uma pilha simples de rótulos e botões."""
    root.update_idletasks()
    largura = max(root.winfo_reqwidth() + margem, minimo[0])
    altura = max(root.winfo_reqheight() + margem, minimo[1])
    largura_tela = root.winfo_screenwidth()
    altura_tela = root.winfo_screenheight()
    x = max(0, (largura_tela - largura) // 2)
    y = max(0, (altura_tela - altura) // 2)
    root.geometry(f"{largura}x{altura}+{x}+{y}")
    root.minsize(largura, altura)


def criar_marca(parent, tamanho="grande", com_subtitulo=True):
    """Cria e devolve um Frame com o "wordmark" do app (nome em serifada +
    barrinha de destaque + subtítulo opcional). Reaproveitado na tela de
    login do cliente, no servidor e no launcher, para a marca ficar sempre
    idêntica em todo o app."""
    fonte = FONTE_DISPLAY if tamanho == "grande" else FONTE_MARCA_PEQUENA
    wrapper = tk.Frame(parent, bg=parent.cget("bg"))
    tk.Label(wrapper, text=NOME_APP, font=fonte, bg=parent.cget("bg"), fg=COR_TEXTO).pack()
    tk.Frame(wrapper, bg=COR_DESTAQUE, width=36, height=3).pack(pady=(7, 0))
    if com_subtitulo:
        tk.Label(
            wrapper, text=SUBTITULO_APP, font=("Segoe UI", 8, "bold"),
            bg=parent.cget("bg"), fg=COR_TEXTO_SUAVE,
        ).pack(pady=(9, 0))
    return wrapper


def hora_agora() -> str:
    return time.strftime("%H:%M")


def inicial(nome: str) -> str:
    return (nome[:1] or "?").upper()


def criar_avatar(parent, nome: str, bg_pai: str, tamanho: int = 30, destaque: bool = False) -> tk.Canvas:
    """Desenha um avatar circular simples (iniciais) num Canvas pequeno.
    Evita depender de emojis/ícones prontos para identificar pessoas."""
    canvas = tk.Canvas(parent, width=tamanho, height=tamanho, bg=bg_pai, highlightthickness=0, bd=0)
    cor = COR_DESTAQUE if destaque else COR_AVATAR_NEUTRO
    canvas.create_oval(1, 1, tamanho - 1, tamanho - 1, fill=cor, outline="")
    canvas.create_text(
        tamanho / 2, tamanho / 2 + 1, text=inicial(nome), fill="white",
        font=("Segoe UI", max(9, int(tamanho * 0.4)), "bold"),
    )
    return canvas


def status_dot(parent, bg_pai: str, cor: str, tamanho: int = 8) -> tk.Canvas:
    """Bolinha de status (ex.: 'servidor rodando', 'conectado')."""
    canvas = tk.Canvas(parent, width=tamanho, height=tamanho, bg=bg_pai, highlightthickness=0, bd=0)
    canvas.create_oval(0, 0, tamanho, tamanho, fill=cor, outline="")
    return canvas


def tornar_clicavel(widgets, ao_clicar, cor_normal, cor_hover) -> None:
    """Vincula clique + destaque ao passar o mouse a um conjunto de widgets
    que formam uma única "linha"/"cartão" clicável."""
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


def botao(parent, texto, comando, primario=True, **kwargs):
    """Botão padronizado (cor de destaque por padrão, ou 'perigo' para
    ações destrutivas/de saída) -- para não reimplementar as mesmas cores
    de hover em cada tela."""
    variante = kwargs.pop("variante", "primario" if primario else "secundario")
    if variante == "perigo":
        bg, fg, bg_hover = COR_PERIGO_BG, COR_PERIGO_FG, COR_PERIGO_BG_HOVER
    elif variante == "secundario":
        bg, fg, bg_hover = COR_PAINEL_2, COR_TEXTO, COR_CAMPO
    else:
        bg, fg, bg_hover = COR_DESTAQUE, "white", COR_DESTAQUE_HOVER

    opcoes = dict(
        text=texto, command=comando, font=FONTE_NEGRITO, bg=bg, fg=fg,
        activebackground=bg_hover, activeforeground=fg, relief="flat", bd=0,
        cursor="hand2", padx=16, pady=8,
    )
    opcoes.update(kwargs)
    return tk.Button(parent, **opcoes)


def campo_com_rotulo(parent, rotulo, variavel, bg=None):
    """Rótulo + Entry padronizados (usado nos formulários de login e de
    configuração do servidor)."""
    bg = bg or COR_PAINEL
    tk.Label(parent, text=rotulo, font=FONTE_BASE, bg=bg, fg=COR_TEXTO, anchor="w").pack(fill="x")
    entrada = tk.Entry(
        parent, textvariable=variavel, font=FONTE_BASE, bg=COR_CAMPO, fg=COR_TEXTO,
        insertbackground=COR_TEXTO, relief="flat", bd=0,
    )
    entrada.pack(fill="x", ipady=8, pady=(4, 6))
    tk.Frame(parent, bg=COR_BORDA, height=1).pack(fill="x", pady=(0, 12))
    return entrada


class ListaRolavel(tk.Frame):
    """Painel com rolagem vertical para empilhar linhas customizadas (ex.:
    usuários, salas, conversas privadas). Tk não tem um widget de lista
    "rica" pronto -- este é o padrão comum para simular um, com Canvas +
    Frame interno + Scrollbar."""

    def __init__(self, parent, bg: str):
        super().__init__(parent, bg=bg)
        self._bg = bg
        self.canvas = tk.Canvas(self, bg=bg, highlightthickness=0, bd=0)
        self.scrollbar = ttk.Scrollbar(
            self, orient="vertical", command=self.canvas.yview, style="Fala.Vertical.TScrollbar"
        )
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
