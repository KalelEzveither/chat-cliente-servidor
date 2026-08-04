# -*- coding: utf-8 -*-
"""
iniciar.py

Tela inicial do sistema de chat: um menu simples com dois botoes, "Servidor"
e "Cliente". Cada clique abre uma NOVA janela independente, sem fechar a
tela inicial nem as janelas ja abertas -- assim da para, por exemplo, abrir
um servidor e varios clientes ao mesmo tempo, tudo a partir desta mesma
tela. E so um atalho para nao precisar lembrar/digitar qual arquivo rodar
em cada janela; nao reimplementa nada da logica de rede, autenticacao ou
salas, que continua inteiramente em `comum/`, `servidor/` e `cliente/`.

Uso:
    python3 iniciar.py

Detalhe tecnico: cada nova janela e um `tk.Toplevel` da janela inicial (nao
um novo `tk.Tk()`), pois o Tkinter so suporta um unico loop de eventos por
processo. `ClienteChatGUI` e `ServidorGUI` (definidas em cliente_gui.py e
servidor_gui.py) ja foram escritas recebendo a janela-pai como parametro,
entao funcionam identicamente sejam elas a janela raiz (quando os arquivos
sao rodados diretamente) ou um Toplevel (quando abertas a partir daqui).
"""

import os
import sys
import tkinter as tk
from tkinter import ttk

PASTA_PROJETO = os.path.dirname(os.path.abspath(__file__))
sys.path.append(os.path.join(PASTA_PROJETO, "cliente"))
sys.path.append(os.path.join(PASTA_PROJETO, "servidor"))

import cliente_gui  # cliente/cliente_gui.py
import servidor_gui  # servidor/servidor_gui.py


def _abrir_servidor(root: tk.Tk) -> None:
    janela = tk.Toplevel(root)
    servidor_gui.ServidorGUI(janela)


def _abrir_cliente(root: tk.Tk) -> None:
    janela = tk.Toplevel(root)
    cliente_gui.ClienteChatGUI(janela, host="", porta=None, usuario="")


def main() -> None:
    root = tk.Tk()
    root.title("Chat Cliente-Servidor")
    root.geometry("380x260")
    root.resizable(False, False)

    frame = ttk.Frame(root, padding=28)
    frame.pack(fill="both", expand=True)

    ttk.Label(
        frame, text="Sistema de Chat Cliente-Servidor", font=("TkDefaultFont", 13, "bold")
    ).pack(pady=(0, 4))
    ttk.Label(
        frame,
        text="Cada clique abre uma nova janela — dá para\nter um servidor e vários clientes ao mesmo tempo.",
        foreground="#666666",
        justify="center",
    ).pack(pady=(0, 18))

    ttk.Button(
        frame, text="🖥️   Servidor", command=lambda: _abrir_servidor(root)
    ).pack(fill="x", pady=(0, 10), ipady=10)
    ttk.Button(
        frame, text="💬   Cliente", command=lambda: _abrir_cliente(root)
    ).pack(fill="x", ipady=10)

    root.mainloop()


if __name__ == "__main__":
    main()
