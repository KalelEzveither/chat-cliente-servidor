# Sistema de Chat Cliente-Servidor — Redes de Computadores 2

Implementação em **Python 3** (biblioteca padrão apenas — módulos `socket`,
`threading`, `json`, `argparse`, `sqlite3`, `tkinter`), usando **TCP** e um
protocolo de aplicação próprio sobre JSON.

Além dos requisitos obrigatórios, foram implementados três itens opcionais
do enunciado: **interface gráfica** (tanto para o cliente quanto para o
servidor), **persistência do histórico de mensagens** em banco de dados e
**salas/canais temáticos**. Não há sistema de contas/senha: cada cliente é
identificado só pelo apelido, como pede o requisito obrigatório.

## Estrutura de pastas

```
chat_project/
├── comum/
│   ├── __init__.py
│   └── protocolo.py       # protocolo de aplicação compartilhado (formato das mensagens)
├── servidor/
│   ├── servidor.py        # servidor (multi-thread, um thread por cliente)
│   ├── servidor_gui.py    # servidor com interface gráfica (Tkinter) — item opcional do enunciado
│   └── bancodedados.py    # persistência SQLite: histórico de mensagens
├── cliente/
│   ├── cliente.py         # cliente em modo texto/terminal (thread de recepção + thread de envio)
│   └── cliente_gui.py     # cliente com interface gráfica (Tkinter) — item opcional do enunciado
├── iniciar.py              # tela inicial: escolher "Servidor" ou "Cliente" (atalho para as GUIs acima)
└── README.md
```

### Jeito mais rápido de começar

```bash
cd chat_project
python3 iniciar.py
```

Abre uma janela com dois botões, **Servidor** e **Cliente**. Cada clique
abre uma **nova janela independente**, sem fechar a tela inicial nem as
janelas já abertas — dá para, por exemplo, clicar em Servidor uma vez e em
Cliente várias vezes, e testar tudo (um servidor + vários clientes) na
mesma máquina. É só um atalho para não precisar lembrar qual arquivo rodar;
as seções abaixo explicam cada parte em detalhe (inclusive as versões em
modo texto/linha de comando).

Os dois clientes (`cliente.py` e `cliente_gui.py`) falam exatamente o mesmo
protocolo com o mesmo servidor — pode-se misturar à vontade clientes em modo
texto e clientes gráficos na mesma sala de chat.

Requisito: **Python 3.8+** (sem dependências externas — não é necessário
`pip install` nada; `sqlite3` e `tkinter` já vêm com o Python).

## Como executar

### 1. No servidor (uma máquina do laboratório)

Descubra o IP da máquina, por exemplo:

```bash
# Linux
ip addr
# ou
ifconfig

# Windows
ipconfig
```

Depois inicie o servidor (por padrão ele escuta em todas as interfaces,
`0.0.0.0`, então basta escolher a porta):

```bash
cd chat_project
python3 servidor/servidor.py --porta 5000
```

Parâmetros opcionais: `--host` (padrão `0.0.0.0`), `--porta` (padrão `5000`)
e `--banco` (padrão `chat.db`, o arquivo SQLite com o histórico de
mensagens privadas — ver seção **Histórico de mensagens** abaixo).

#### Servidor com interface gráfica (opcional)

Em vez de `servidor/servidor.py` pela linha de comando, dá para usar a
versão gráfica:

```bash
cd chat_project
python3 servidor/servidor_gui.py
```

Preencha host, porta e o caminho do banco (os mesmos parâmetros de antes) e
clique **Iniciar servidor**. A janela mostra em tempo real o log de
atividade — conexões, logins, entrada/saída de salas, erros — e o botão
**Parar servidor** encerra tudo de forma controlada (equivalente a um
Ctrl+C: os clientes conectados são avisados antes da conexão cair).

Essa GUI não reimplementa a lógica de rede: ela só inicia e supervisiona
`servidor.py` como um processo interno, então o comportamento em rede é
idêntico ao da versão em modo texto.

> **Importante sobre privacidade:** o log do servidor (tanto na versão
> texto quanto na gráfica) mostra apenas **que** uma mensagem foi enviada,
> por quem e em qual sala/para quem — nunca o **conteúdo** da mensagem. O
> texto das conversas só aparece na tela dos clientes.

### 2. Em cada máquina cliente

```bash
cd chat_project
python3 cliente/cliente.py --host <IP_DA_MAQUINA_SERVIDORA> --porta 5000 --usuario meu_apelido
```

Se você não passar `--host`, `--porta` ou `--usuario`, o cliente pergunta
interativamente — **o IP nunca é fixo no código**, exatamente como pede o
enunciado, para permitir o teste em máquinas distintas no laboratório.

## Identificação por apelido e histórico de mensagens

- **Sem senha nem conta:** o apelido sozinho identifica o cliente (é o que
  o enunciado exige — "identificação do usuário por um nome/apelido único
  ao entrar no chat"). O login só é recusado se o apelido já estiver em
  uso por uma sessão ativa no momento, ou se for inválido (vazio, com
  espaço, ou começando com `/`).
- **Histórico persistente**, gravado em SQLite (arquivo `chat.db`, criado
  automaticamente ao lado de `servidor.py`), com regras diferentes para
  cada tipo de mensagem:
  - **Privadas:** todas ficam guardadas, e o cliente recebe automaticamente
    as que enviou/recebeu logo após o login, para retomar o contexto.
  - **Gerais (chat da sala/broadcast):** em vez de reenviar "as últimas N
    mensagens" pra qualquer um que entrar (o que inundaria um usuário novo
    com conversa antiga que não diz respeito a ele), o servidor guarda
    quando cada usuário saiu de cada sala pela última vez (troca de sala
    ou desconexão) e, ao voltar a uma sala em que já esteve, manda só as
    mensagens gerais que aconteceram **enquanto ele estava fora** dela.
    Quem entra numa sala pela primeira vez não recebe nada — só passa a
    ver as mensagens dali em diante, ao vivo.
- Para começar um histórico "do zero" (ex.: para gravar o vídeo de
  demonstração), basta apagar o arquivo `chat.db` antes de subir o
  servidor — ele é recriado vazio automaticamente.

## Salas/canais temáticos

- Todo cliente entra automaticamente na sala padrão **`geral`** ao fazer
  login. A qualquer momento é possível trocar de sala com `/entrar <sala>`
  (cliente texto) ou pelo campo "Sala atual" (cliente gráfico).
- Salas usam **auto-criação**, no mesmo espírito do auto-registro de
  usuários: não existe uma lista fixa de salas pré-cadastradas — a primeira
  pessoa a entrar em um nome de sala novo "cria" a sala na hora.
- Mensagens de chat geral (`MSG`, broadcast) e o comando `/lista` valem
  **só para a sala atual** de quem enviou/pediu — quem está em outra sala
  não vê. Mensagens privadas (`/msg`) continuam funcionando entre duas
  pessoas independentemente da sala em que cada uma estiver.
- `/salas` lista as salas que têm pelo menos um usuário conectado agora, e
  quantos usuários há em cada uma.

## Comandos disponíveis no cliente

| Comando | Efeito |
|---|---|
| `<qualquer texto>` | Envia mensagem para a sala atual (broadcast) |
| `/msg <usuario> <mensagem>` | Envia mensagem privada para um usuário específico |
| `/lista` | Lista os usuários conectados na sala atual |
| `/entrar <sala>` | Troca para outra sala/canal (cria se ainda não existir) |
| `/salas` | Lista as salas ativas no momento (com número de usuários) |
| `/sair` | Encerra a conexão de forma controlada |
| `/ajuda` | Mostra novamente a lista de comandos |

### 3. Cliente com interface gráfica (opcional)

Em vez de `cliente/cliente.py`, qualquer máquina pode usar a versão gráfica:

```bash
cd chat_project
python3 cliente/cliente_gui.py
```

Uma janela abre com campos para IP, porta e apelido (sem senha), e um botão
**Entrar** — o login só é recusado se o apelido já estiver em uso por uma
sessão ativa no momento (o IP também nunca é fixo no código aqui). Depois
de conectado:

- Digite no campo de texto e clique **Enviar** (ou tecle Enter) para mandar
  mensagem na sala atual;
- Clique em um usuário na lista à direita para mudar o destino da próxima
  mensagem para **privado** (o rótulo "Enviando para: ..." mostra o modo
  atual); clique em "🌐 Sala atual (broadcast)" para voltar ao modo broadcast;
- No campo **"Sala atual"**, digite o nome de outra sala e clique
  **Trocar** (ou tecle Enter) para mudar de canal — a sala é criada na hora
  se ainda não existir. O botão **"Ver salas ativas"** mostra no chat quais
  salas têm gente conectada agora;
- O botão **↻** atualiza manualmente a lista de usuários da sala atual (a
  lista também se atualiza sozinha quando alguém entra ou sai dela);
- O botão **Sair** (ou fechar a janela) encerra a conexão de forma
  controlada, enviando o comando `SAIR` ao servidor;
- Logo após entrar, o histórico de mensagens anteriores (se houver)
  aparece automaticamente no chat, em um tom mais claro, para diferenciar
  do que está acontecendo ao vivo.

Você também pode pré-preencher os campos por linha de comando (a conexão
ainda assim só é feita ao clicar em "Entrar"):

```bash
python3 cliente/cliente_gui.py --host 192.168.0.10 --porta 5000 --usuario alice
```

> **Requisito do sistema:** o Tkinter faz parte da biblioteca padrão do
> Python, mas em algumas instalações do Linux ele não vem pré-instalado. Se
> aparecer `ModuleNotFoundError: No module named 'tkinter'`, instale com
> `sudo apt install python3-tk` (Ubuntu/Debian) e tente novamente. No Windows
> e no macOS o Tkinter já vem junto com o Python.

## Testando em duas máquinas antes do dia da apresentação

1. Rode o servidor em uma máquina e anote o IP dela.
2. Rode o cliente em outra máquina apontando para esse IP.
3. Se a conexão for recusada, verifique:
   - Se as duas máquinas estão na mesma rede/sub-rede;
   - Se o firewall da máquina servidora está liberando a porta escolhida
     (ex.: `sudo ufw allow 5000/tcp` no Linux, ou liberar no Firewall do
     Windows);
   - Se a porta já não está em uso por outro processo.

## Observações de implementação

- Cada cliente conectado é atendido por uma **thread própria** no servidor
  (`threading.Thread`), permitindo múltiplas conexões simultâneas.
- O acesso à lista compartilhada de clientes conectados é protegido por um
  `threading.Lock`, evitando condições de corrida (ex.: dois usuários
  tentando logar com o mesmo apelido ao mesmo tempo).
- A sala atual de cada cliente é apenas um atributo em memória
  (`ClienteConectado.sala`, protegido pelo mesmo Lock); não existe uma
  tabela de "salas" no banco — a lista de salas ativas é calculada na hora,
  agrupando os clientes conectados pela sala em que cada um está.
- O protocolo de aplicação (formato de cada mensagem trocada) está
  totalmente documentado nos comentários de `comum/protocolo.py`.
- A camada de persistência (`servidor/bancodedados.py`) abre uma conexão
  SQLite curta por operação e usa um `threading.Lock` próprio para
  serializar escritas entre as threads de clientes diferentes.
- Consulte o **relatório técnico** (entregue separadamente em `.docx`) para
  a justificativa da escolha de TCP em vez de UDP, o diagrama de arquitetura,
  os testes realizados e as dificuldades encontradas.
- `servidor_gui.py` roda `servidor.py` como um processo interno (não
  reimplementa a lógica de rede) e le a saída dele em tempo real para
  exibir na janela. No Windows, isso exigiu registrar um handler para
  `SIGBREAK` em `servidor.py` (além do `SIGINT`/Ctrl+C já tratado por
  padrão), já que só é possível sinalizar um encerramento controlado de um
  processo-filho a partir de outro processo via `CTRL_BREAK_EVENT`, que sem
  handler simplesmente mata o processo em vez de virar uma exceção
  tratável.
