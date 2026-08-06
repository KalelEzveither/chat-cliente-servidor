# tela inicial: dois botoes que abrem servidor/cliente em janelas novas.
# nao reimplementa nada de rede, so evita ter que lembrar qual arquivo rodar

import os
import sys
import tkinter as tk

PASTA_PROJETO = os.path.dirname(os.path.abspath(__file__))
sys.path.append(PASTA_PROJETO)
sys.path.append(os.path.join(PASTA_PROJETO, "cliente"))
sys.path.append(os.path.join(PASTA_PROJETO, "servidor"))

from comum.estilo import (  # noqa: E402
    COR_PAINEL, COR_TEXTO_SUAVE, FONTE_BASE,
    aplicar_janela_base, ajustar_ao_conteudo, criar_marca, botao,
)

import cliente_gui
import servidor_gui


def _abrir_servidor(root: tk.Tk) -> None:
    janela = tk.Toplevel(root)
    servidor_gui.ServidorGUI(janela)


def _abrir_cliente(root: tk.Tk) -> None:
    janela = tk.Toplevel(root)
    cliente_gui.ClienteChatGUI(janela, host="", porta=None, usuario="")


def main() -> None:
    root = tk.Tk()
    aplicar_janela_base(root)

    card = tk.Frame(root, bg=COR_PAINEL, padx=32, pady=32)
    card.pack(fill="both", expand=True)

    criar_marca(card).pack(pady=(4, 6))

    botao(card, "Abrir Servidor", lambda: _abrir_servidor(root), height=2).pack(fill="x", pady=(0, 10))
    botao(card, "Abrir Cliente", lambda: _abrir_cliente(root), height=2).pack(fill="x")

    # so mede o tamanho real depois de tudo montado, evita chutar pixel
    ajustar_ao_conteudo(root, margem=24, minimo=(360, 300))
    root.resizable(True, True)

    root.mainloop()


if __name__ == "__main__":
    main()
