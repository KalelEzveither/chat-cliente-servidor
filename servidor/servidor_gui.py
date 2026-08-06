# painel grafico do servidor. nao reimplementa rede: so liga/desliga
# servidor.py como subprocesso e mostra o log dele numa janela

import os
import queue
import signal
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import messagebox

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from comum.estilo import (
    COR_FUNDO, COR_PAINEL, COR_PAINEL_2, COR_CAMPO, COR_TEXTO, COR_TEXTO_SUAVE,
    COR_SUCESSO, COR_ERRO, COR_AVISO,
    FONTE_MARCA_PEQUENA, FONTE_BASE, FONTE_PEQUENA, FONTE_PEQUENA_IT, FONTE_MONO,
    aplicar_janela_base, geometria_ajustada_a_tela, status_dot, tornar_clicavel,
    botao,
)

PASTA_SERVIDOR = os.path.dirname(os.path.abspath(__file__))
CAMINHO_SERVIDOR_PY = os.path.join(PASTA_SERVIDOR, "servidor.py")
PASTA_PROJETO = os.path.dirname(PASTA_SERVIDOR)


class ServidorGUI:
    # formulario de config + botoes iniciar/parar + log em tempo real

    def __init__(self, root: tk.Tk):
        self.root = root
        aplicar_janela_base(self.root)
        geometria_ajustada_a_tela(self.root, largura_alvo=820, altura_alvo=580, largura_min=560, altura_min=380)

        self.processo: "subprocess.Popen | None" = None
        self.rodando = False
        self.fila_log: "queue.Queue[str]" = queue.Queue()

        self._montar_widgets()
        self.root.protocol("WM_DELETE_WINDOW", self._ao_fechar_janela)
        self.root.after(100, self._processar_fila_log)

    def _montar_widgets(self) -> None:
        self._montar_barra_topo()

        corpo = tk.Frame(self.root, bg=COR_FUNDO)
        corpo.pack(fill="both", expand=True)

        self._montar_formulario(corpo)
        self._montar_painel_log(corpo)

    def _montar_barra_topo(self) -> None:
        topo = tk.Frame(self.root, bg=COR_PAINEL, height=58)
        topo.pack(fill="x", side="top")
        topo.pack_propagate(False)

        tk.Label(topo, text="Fala Daí", font=FONTE_MARCA_PEQUENA, bg=COR_PAINEL, fg=COR_TEXTO).pack(side="left", padx=(18, 6), pady=12)
        tk.Label(topo, text="· Servidor", font=FONTE_BASE, bg=COR_PAINEL, fg=COR_TEXTO_SUAVE).pack(side="left", pady=12)

        lado_direito = tk.Frame(topo, bg=COR_PAINEL)
        lado_direito.pack(side="right", padx=18)
        self.bolinha_status = status_dot(lado_direito, COR_PAINEL, COR_ERRO)
        self.bolinha_status.pack(side="left", padx=(0, 6))
        self.rotulo_status = tk.Label(lado_direito, text="Parado", font=FONTE_PEQUENA, bg=COR_PAINEL, fg=COR_TEXTO_SUAVE)
        self.rotulo_status.pack(side="left")

    def _montar_formulario(self, parent) -> None:
        card = tk.Frame(parent, bg=COR_PAINEL, padx=18, pady=16)
        card.pack(fill="x", padx=16, pady=(16, 8))

        # campos numa linha (grid com peso, cresce/encolhe com a janela)
        linha_campos = tk.Frame(card, bg=COR_PAINEL)
        linha_campos.pack(fill="x")
        linha_campos.columnconfigure(0, weight=2)
        linha_campos.columnconfigure(1, weight=1)
        linha_campos.columnconfigure(2, weight=2)

        self.var_host = tk.StringVar(value="0.0.0.0")
        self.var_porta = tk.StringVar(value="5000")
        self.var_banco = tk.StringVar(value="chat.db")

        self.entrada_host = self._campo_grid(linha_campos, "Host", self.var_host, coluna=0)
        self.entrada_porta = self._campo_grid(linha_campos, "Porta", self.var_porta, coluna=1)
        self.entrada_banco = self._campo_grid(linha_campos, "Banco (SQLite)", self.var_banco, coluna=2)

        # botoes numa linha separada, cada um com fill+expand
        linha_botoes = tk.Frame(card, bg=COR_PAINEL)
        linha_botoes.pack(fill="x", pady=(12, 0))

        self.botao_iniciar = botao(linha_botoes, "Iniciar servidor", self._ao_clicar_iniciar)
        self.botao_iniciar.pack(side="left", fill="x", expand=True, padx=(0, 6))
        self.botao_parar = botao(linha_botoes, "Parar servidor", self._ao_clicar_parar, variante="perigo", state="disabled")
        self.botao_parar.pack(side="left", fill="x", expand=True)

        tk.Label(
            card,
            text="O banco é criado/reaproveitado ao lado desta pasta. O endereço de rede (IP/porta) nunca fica fixo no código.",
            font=FONTE_PEQUENA_IT, bg=COR_PAINEL, fg=COR_TEXTO_SUAVE, anchor="w", wraplength=440, justify="left",
        ).pack(fill="x", pady=(10, 0))

    def _campo_grid(self, parent, rotulo, variavel, coluna):
        wrapper = tk.Frame(parent, bg=COR_PAINEL)
        wrapper.grid(row=0, column=coluna, sticky="ew", padx=(0 if coluna == 0 else 12, 0))
        tk.Label(wrapper, text=rotulo, font=FONTE_PEQUENA, bg=COR_PAINEL, fg=COR_TEXTO_SUAVE, anchor="w").pack(fill="x")
        entrada = tk.Entry(
            wrapper, textvariable=variavel, font=FONTE_BASE, bg=COR_CAMPO, fg=COR_TEXTO,
            insertbackground=COR_TEXTO, relief="flat", bd=0,
        )
        entrada.pack(fill="x", ipady=6, pady=(4, 0))
        return entrada

    def _montar_painel_log(self, parent) -> None:
        frame_log = tk.Frame(parent, bg=COR_FUNDO)
        frame_log.pack(fill="both", expand=True, padx=16, pady=(0, 16))

        cabecalho_log = tk.Frame(frame_log, bg=COR_FUNDO)
        cabecalho_log.pack(fill="x")
        botao_limpar = tk.Label(
            cabecalho_log, text="Limpar", font=FONTE_PEQUENA, bg=COR_FUNDO, fg=COR_TEXTO_SUAVE, cursor="hand2",
        )
        botao_limpar.pack(side="right")
        tornar_clicavel([botao_limpar], self._limpar_log, COR_FUNDO, COR_FUNDO)
        tk.Label(cabecalho_log, text="ATIVIDADE DO SERVIDOR", font=("Segoe UI", 8, "bold"), bg=COR_FUNDO, fg=COR_TEXTO_SUAVE).pack(side="left")

        tk.Label(
            frame_log, text="Apenas conexão/login/salas — o conteúdo das mensagens nunca aparece aqui.",
            font=FONTE_PEQUENA_IT, bg=COR_FUNDO, fg=COR_TEXTO_SUAVE, anchor="w", wraplength=440, justify="left",
        ).pack(fill="x", pady=(2, 6))

        painel_texto = tk.Frame(frame_log, bg=COR_PAINEL)
        painel_texto.pack(fill="both", expand=True)

        self.texto_log = tk.Text(
            painel_texto, state="disabled", wrap="word", font=FONTE_MONO,
            bg=COR_PAINEL, fg=COR_TEXTO, relief="flat", bd=0, padx=12, pady=10,
        )
        scroll = tk.Scrollbar(painel_texto, command=self.texto_log.yview, bg=COR_PAINEL_2, troughcolor=COR_PAINEL, bd=0)
        self.texto_log.configure(yscrollcommand=scroll.set)
        self.texto_log.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self.texto_log.tag_config("erro", foreground=COR_ERRO)
        self.texto_log.tag_config("aviso", foreground=COR_AVISO)

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

        # -u desliga o buffer de saida do subprocesso, senao o log so
        # aparece em blocos (pipe nao e terminal, python bufferiza)
        comando = [sys.executable, "-u", CAMINHO_SERVIDOR_PY, "--host", host, "--porta", str(porta), "--banco", banco]

        kwargs = {}
        if os.name == "nt":
            # necessario no windows pra depois poder mandar CTRL_BREAK_EVENT
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
        self.bolinha_status.itemconfig(1, fill=COR_SUCESSO)
        self.rotulo_status.config(text=f"Rodando em {host}:{porta}", fg=COR_SUCESSO)

        threading.Thread(target=self._ler_saida_processo, daemon=True).start()

    def _ler_saida_processo(self) -> None:
        # thread separada: le o stdout do processo linha a linha e empilha na fila
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
        # tenta encerramento controlado (equivalente a ctrl+c), forca se nao responder
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
        self.bolinha_status.itemconfig(1, fill=COR_ERRO)
        self.rotulo_status.config(text="Parado", fg=COR_TEXTO_SUAVE)

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
