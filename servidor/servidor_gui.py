# -*- coding: utf-8 -*-
"""
servidor/servidor_gui.py

Interface grafica (Tkinter) para operar o servidor de chat, como alternativa
a rodar `servidor.py` diretamente pela linha de comando.

Esta GUI NAO reimplementa a logica de rede: ela apenas inicia e supervisiona
`servidor.py` como um subprocesso (com os parametros escolhidos na tela) e
exibe, em uma janela, o mesmo log que apareceria no terminal. Isso garante
que o comportamento de rede seja identico ao do servidor em modo texto --
so muda a forma de operar (host/porta/banco por formulario, iniciar/parar
por botao, log em uma janela em vez do terminal).

Privacidade: o servidor (servidor.py) so registra QUE uma mensagem foi
enviada, por quem e em qual sala/destinatario -- nunca o conteudo da
mensagem em si. O texto das conversas so aparece na tela dos clientes
(cliente.py / cliente_gui.py), nunca aqui.

Uso:
    python3 servidor_gui.py

Arquitetura:
    - Thread principal: roda o loop de eventos do Tkinter.
    - Thread de leitura de log: fica bloqueada lendo a saida (stdout) do
      subprocesso do servidor, linha a linha, e empilha cada linha numa fila
      (queue.Queue) -- nunca mexe em widgets diretamente.
    - A thread principal consome essa fila periodicamente (root.after) e so
      ai atualiza o widget de log, respeitando a regra do Tkinter de que
      apenas a thread principal pode tocar nos widgets.
"""

import os
import queue
import signal
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import messagebox, scrolledtext, ttk

PASTA_SERVIDOR = os.path.dirname(os.path.abspath(__file__))
CAMINHO_SERVIDOR_PY = os.path.join(PASTA_SERVIDOR, "servidor.py")
PASTA_PROJETO = os.path.dirname(PASTA_SERVIDOR)


class ServidorGUI:
    """Janela principal: formulario de configuracao + botoes iniciar/parar
    + painel de log em tempo real do servidor."""

    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Servidor de Chat")
        self.root.geometry("700x480")
        self.root.minsize(520, 320)

        self.processo: subprocess.Popen | None = None
        self.rodando = False
        self.fila_log: "queue.Queue[str]" = queue.Queue()

        self._montar_widgets()
        self.root.protocol("WM_DELETE_WINDOW", self._ao_fechar_janela)
        self.root.after(100, self._processar_fila_log)

    # ------------------------------------------------------------------ #
    # Montagem da interface
    # ------------------------------------------------------------------ #

    def _montar_widgets(self) -> None:
        frame_config = ttk.Frame(self.root, padding=8)
        frame_config.pack(side="top", fill="x")

        ttk.Label(frame_config, text="Host:").grid(row=0, column=0, padx=(0, 4))
        self.var_host = tk.StringVar(value="0.0.0.0")
        self.entrada_host = ttk.Entry(frame_config, textvariable=self.var_host, width=14)
        self.entrada_host.grid(row=0, column=1, padx=(0, 10))

        ttk.Label(frame_config, text="Porta:").grid(row=0, column=2, padx=(0, 4))
        self.var_porta = tk.StringVar(value="5000")
        self.entrada_porta = ttk.Entry(frame_config, textvariable=self.var_porta, width=7)
        self.entrada_porta.grid(row=0, column=3, padx=(0, 10))

        ttk.Label(frame_config, text="Banco (SQLite):").grid(row=0, column=4, padx=(0, 4))
        self.var_banco = tk.StringVar(value="chat.db")
        self.entrada_banco = ttk.Entry(frame_config, textvariable=self.var_banco, width=18)
        self.entrada_banco.grid(row=0, column=5, padx=(0, 10))

        self.botao_iniciar = ttk.Button(frame_config, text="Iniciar servidor", command=self._ao_clicar_iniciar)
        self.botao_iniciar.grid(row=0, column=6, padx=(0, 4))
        self.botao_parar = ttk.Button(
            frame_config, text="Parar servidor", command=self._ao_clicar_parar, state="disabled"
        )
        self.botao_parar.grid(row=0, column=7)

        self.rotulo_status = ttk.Label(frame_config, text="Parado", foreground="#a33")
        self.rotulo_status.grid(row=1, column=0, columnspan=8, sticky="w", pady=(6, 0))
        self.rotulo_dica = ttk.Label(
            frame_config,
            text="Dica: o banco é criado/reaproveitado ao lado desta pasta. O caminho de rede (IP/porta) nunca fica fixo no código.",
            foreground="#888888",
            font=("TkDefaultFont", 8),
        )
        self.rotulo_dica.grid(row=2, column=0, columnspan=8, sticky="w")

        frame_log = ttk.Frame(self.root, padding=(8, 4, 8, 8))
        frame_log.pack(side="top", fill="both", expand=True)

        cabecalho_log = ttk.Frame(frame_log)
        cabecalho_log.pack(fill="x")
        ttk.Label(cabecalho_log, text="Atividade do servidor", font=("TkDefaultFont", 9, "bold")).pack(side="left")
        ttk.Label(
            cabecalho_log,
            text="(apenas eventos de conexão/login/salas — o conteúdo das mensagens nunca aparece aqui)",
            foreground="#888888",
            font=("TkDefaultFont", 8),
        ).pack(side="left", padx=(6, 0))
        ttk.Button(cabecalho_log, text="Limpar", command=self._limpar_log).pack(side="right")

        self.texto_log = scrolledtext.ScrolledText(
            frame_log, state="disabled", wrap="word", font=("Consolas", 9), background="#111318", foreground="#d8dee9"
        )
        self.texto_log.pack(fill="both", expand=True, pady=(4, 0))
        self.texto_log.tag_config("erro", foreground="#ff6b6b")
        self.texto_log.tag_config("aviso", foreground="#e0af68")

    # ------------------------------------------------------------------ #
    # Iniciar / parar o subprocesso do servidor
    # ------------------------------------------------------------------ #

    def _ao_clicar_iniciar(self) -> None:
        if self.rodando:
            return

        host = self.var_host.get().strip()
        porta_texto = self.var_porta.get().strip()
        banco = self.var_banco.get().strip() or "chat.db"

        if not host or not porta_texto:
            messagebox.showwarning("Dados incompletos", "Preencha host e porta antes de iniciar.")
            return
        try:
            porta = int(porta_texto)
        except ValueError:
            messagebox.showwarning("Porta inválida", "A porta deve ser um número inteiro.")
            return

        # "-u": desliga o buffer de saida do subprocesso. Sem isso, como o
        # stdout esta ligado a um pipe (nao a um terminal), o Python usa
        # buffer em bloco por padrao e as linhas de log so apareceriam na
        # tela quando o buffer enchesse ou o processo terminasse -- nada em
        # tempo real.
        comando = [sys.executable, "-u", CAMINHO_SERVIDOR_PY, "--host", host, "--porta", str(porta), "--banco", banco]

        kwargs = {}
        if os.name == "nt":
            # Necessario no Windows para depois conseguir mandar CTRL_BREAK_EVENT
            # ao parar (equivalente a um Ctrl+C, para o servidor encerrar de
            # forma controlada em vez de ser simplesmente morto).
            kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP

        try:
            self.processo = subprocess.Popen(
                comando,
                cwd=PASTA_PROJETO,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                **kwargs,
            )
        except OSError as erro:
            messagebox.showerror("Erro ao iniciar", f"Não foi possível iniciar o servidor: {erro}")
            return

        self.rodando = True
        self.entrada_host.config(state="disabled")
        self.entrada_porta.config(state="disabled")
        self.entrada_banco.config(state="disabled")
        self.botao_iniciar.config(state="disabled")
        self.botao_parar.config(state="normal")
        self.rotulo_status.config(text=f"Rodando em {host}:{porta}", foreground="#1a7a1a")

        threading.Thread(target=self._ler_saida_processo, daemon=True).start()

    def _ler_saida_processo(self) -> None:
        """Roda em thread separada: le a saida do subprocesso linha a linha
        e empilha na fila (nunca mexe na tela diretamente)."""
        processo = self.processo
        try:
            for linha in processo.stdout:
                self.fila_log.put(linha.rstrip("\n"))
        except (OSError, ValueError):
            pass
        codigo = processo.wait()
        self.fila_log.put(f"[GUI] Processo do servidor terminou (código {codigo}).")
        self.fila_log.put("_PROCESSO_ENCERRADO_")

    def _ao_clicar_parar(self) -> None:
        if not self.rodando or self.processo is None:
            return
        self.botao_parar.config(state="disabled")
        threading.Thread(target=self._parar_processo, daemon=True).start()

    def _parar_processo(self) -> None:
        """Tenta um encerramento controlado (equivalente a Ctrl+C, que o
        servidor trata para avisar os clientes conectados antes de fechar);
        se nao encerrar a tempo, forca o encerramento."""
        processo = self.processo
        try:
            if os.name == "nt":
                processo.send_signal(signal.CTRL_BREAK_EVENT)
            else:
                processo.send_signal(signal.SIGINT)
            processo.wait(timeout=3)
        except subprocess.TimeoutExpired:
            self.fila_log.put("[GUI] Servidor não respondeu ao pedido de encerramento; forçando parada.")
            processo.terminate()
            try:
                processo.wait(timeout=2)
            except subprocess.TimeoutExpired:
                processo.kill()
        except (OSError, ValueError):
            pass

    # ------------------------------------------------------------------ #
    # Fila de log (produzida pela thread de leitura, consumida aqui)
    # ------------------------------------------------------------------ #

    def _processar_fila_log(self) -> None:
        try:
            while True:
                linha = self.fila_log.get_nowait()
                if linha == "_PROCESSO_ENCERRADO_":
                    self._ao_processo_encerrado()
                else:
                    self._exibir_log(linha)
        except queue.Empty:
            pass
        self.root.after(100, self._processar_fila_log)

    def _exibir_log(self, linha: str) -> None:
        tag = ""
        if "ERRO" in linha:
            tag = "erro"
        elif "AVISO" in linha:
            tag = "aviso"
        self.texto_log.config(state="normal")
        self.texto_log.insert("end", linha + "\n", tag)
        self.texto_log.see("end")
        self.texto_log.config(state="disabled")

    def _limpar_log(self) -> None:
        self.texto_log.config(state="normal")
        self.texto_log.delete("1.0", "end")
        self.texto_log.config(state="disabled")

    def _ao_processo_encerrado(self) -> None:
        self.rodando = False
        self.processo = None
        self.entrada_host.config(state="normal")
        self.entrada_porta.config(state="normal")
        self.entrada_banco.config(state="normal")
        self.botao_iniciar.config(state="normal")
        self.botao_parar.config(state="disabled")
        self.rotulo_status.config(text="Parado", foreground="#a33")

    # ------------------------------------------------------------------ #
    # Encerramento da janela
    # ------------------------------------------------------------------ #

    def _ao_fechar_janela(self) -> None:
        if self.rodando and self.processo is not None:
            try:
                if os.name == "nt":
                    self.processo.send_signal(signal.CTRL_BREAK_EVENT)
                else:
                    self.processo.send_signal(signal.SIGINT)
                self.processo.wait(timeout=2)
            except Exception:
                try:
                    self.processo.kill()
                except OSError:
                    pass
        self.root.destroy()


def main():
    root = tk.Tk()
    ServidorGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
