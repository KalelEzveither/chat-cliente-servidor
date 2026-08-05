# -*- coding: utf-8 -*-
"""
iniciar.py

Tela inicial do sistema de chat "Fala Daí": um menu simples com dois
botoes, "Servidor" e "Cliente". Cada clique abre uma NOVA janela
independente, sem fechar a tela inicial nem as janelas ja abertas -- assim
da para, por exemplo, abrir um servidor e varios clientes ao mesmo tempo,
tudo a partir desta mesma tela. E so um atalho para nao precisar
lembrar/digitar qual arquivo rodar em cada janela; nao reimplementa nada da
logica de rede, autenticacao ou salas, que continua inteiramente em
`comum/`, `servidor/` e `cliente/`.

Uso:
    python3 iniciar.py

Detalhe tecnico: cada nova janela e um `tk.Toplevel` da janela inicial (nao
um novo `tk.Tk()`), pois o Tkinter so suporta um unico loop de eventos por
processo. `ClienteChatGUI` e `ServidorGUI` (definidas em cliente_gui.py e
servidor_gui.py) ja foram escritas recebendo a janela-pai como parametro,
entao funcionam identicamente sejam elas a janela raiz (quando os arquivos
sao rodados diretamente) ou um Toplevel (quando abertas a partir daqui).

O visual (cores, fontes, marca "Fala Daí") vem de `comum/estilo.py`,
compartilhado com as outras duas janelas, para que o app inteiro tenha uma
identidade visual única.
"""

import os
import sys
import tkinter as tk

PASTA_PROJETO = os.path.dirname(os.path.abspath(__file__))
sys.path.append(PASTA_PROJETO)
sys.path.append(os.path.join(PASTA_PROJETO, "cliente"))
sys.path.append(os.path.join(PASTA_PROJETO, "servidor"))

from comum.estilo import (  # noqa: E402  (precisa vir depois do sys.path.append acima)
    COR_PAINEL, COR_TEXTO_SUAVE, FONTE_BASE,
    aplicar_janela_base, ajustar_ao_conteudo, criar_marca, botao,
)

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
    aplicar_janela_base(root)

    card = tk.Frame(root, bg=COR_PAINEL, padx=32, pady=32)
    card.pack(fill="both", expand=True)

    criar_marca(card).pack(pady=(4, 6))
    tk.Label(
        card,
        text="Cada botão abre uma nova janela — dá para ter um servidor e vários clientes ao mesmo tempo.",
        font=FONTE_BASE, bg=COR_PAINEL, fg=COR_TEXTO_SUAVE, justify="center", wraplength=300,
    ).pack(pady=(4, 26))

    botao(card, "Abrir Servidor", lambda: _abrir_servidor(root), height=2).pack(fill="x", pady=(0, 10))
    botao(card, "Abrir Cliente", lambda: _abrir_cliente(root), height=2).pack(fill="x")

    # So depois que TODOS os widgets acima ja foram criados e empacotados
    # e que da para medir o tamanho de verdade que a janela precisa (isso
    # evita chutar um numero de pixels que pode ficar pequeno demais
    # dependendo da fonte real disponivel no sistema operacional de quem
    # esta usando -- Windows, macOS e Linux nao renderizam texto com
    # exatamente o mesmo tamanho).
    ajustar_ao_conteudo(root, margem=24, minimo=(360, 300))
    root.resizable(True, True)

    root.mainloop()


if __name__ == "__main__":
    main()
