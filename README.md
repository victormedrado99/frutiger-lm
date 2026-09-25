# Frutiger LM

Notebooks de estudo com as suas fontes, conversa, outputs e um **grafo de
conhecimento ancorado** — o que você estuda vira conceito ligado a conceito, com
rastro até a fonte.

> **Projeto independente**, sem afiliação com o Nous Research ou com a Monotype.
> "Frutiger" aqui se refere à linhagem estética que inspira a interface.
>
> **Arquitetura e roadmap:** veja [PROJETO.md](PROJETO.md). É o documento-vivo do
> projeto — toda decisão estrutural está registrada lá, com status e justificativa.

Se você já usou o NotebookLM do Google, a ideia parte da mesma base, mas com uma
diferença de fundo: o NotebookLM é um **consumidor de fontes** (joga material,
conversa, gera um output, e aquilo morre ali). O Frutiger LM é um **construtor
de conhecimento que persiste e se liga**. Sem imagens e sem áudio — só estrutura
de estudo.

> **Estado: motor próprio.** O agente é um grafo LangGraph que vive dentro do app
> (F1 do PROJETO.md, concluída). Não é preciso instalar Hermes nem nenhum motor
> externo — só uma **API key** de modelo, ou nada, se você usar modelo local.

## Como funciona (hoje)

```
   ┌──────────────────────────────────────────────────────────┐
   │  Frutiger LM                                             │
   │                                                          │
   │  FastAPI + UI vanilla        ┌────────────────────────┐  │
   │  cadernos, fontes,           │  agente (engine/)      │  │
   │  outputs, SQLite             │  LangGraph + tools     │  │
   │                              │  + checkpointer        │  │
   │                              └───────────┬────────────┘  │
   └──────────────────────────────────────────┼───────────────┘
                                              │ OpenAI-compatível
                                              ▼
                              OpenAI · DeepSeek · OpenRouter · Groq
                              LM Studio · llama.cpp · vLLM · Ollama
```

Mapeamento dos conceitos:

| Conceito       | Onde vive                                                  |
|---|---|
| Caderno        | linha no SQLite + um `thread_id` no checkpointer             |
| Fontes         | arquivos `.txt` em `data/notebooks/<id>/fontes/` + SQLite    |
| Chat           | streaming (SSE) do agente, traduzido em `engine/agent.py`    |
| Outputs        | documento Markdown gerado e salvo, versionado                |
| Modelo + chave | `data/model.json` (0600) ou `LLM_AGENT` no `.env`            |

## Requisitos

- Linux, macOS ou Windows
- [uv](https://docs.astral.sh/uv/) (ou Python 3.11+ e pip)
- Uma **API key** de um provedor OpenAI-compatível — ou um modelo local
  (LM Studio, llama.cpp). Sem chave nenhuma o app funciona para organizar
  cadernos; só o chat é que avisa que falta configurar o modelo.

## Instalação

### 1. Rode o app

```bash
git clone <este-repo> frutiger-lm && cd frutiger-lm
uv sync
uv run frutiger-lm
```

Abra http://127.0.0.1:8765.

### 2. Configure o modelo

Clique em **Modelo** na barra da tela inicial: escolha o provedor no select (ele
preenche o endereço), confirme o nome do modelo, cole a sua chave e clique em
**Testar conexão**. O teste faz uma chamada mínima de verdade — é a diferença
entre "salvei" e "funciona".

A chave fica em `data/model.json` com permissão `600` e **nunca** é devolvida para
o navegador. Se preferir versionar a configuração, use `LLM_AGENT` no `.env`
(veja `.env.example`) — a UI ganha quando as duas existem.

### 3. (Opcional, Linux) Deixar sempre no ar

O unit está versionado em `deploy/frutiger-lm.service`:

```bash
install -m 644 deploy/frutiger-lm.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now frutiger-lm.service
```

Ele não depende de nenhum outro serviço, e `Restart=always` faz o app voltar
sozinho se cair (testado com `kill -9`).

Ajuste o caminho do projeto no unit se você não clonou em `~/Projetos/caderno`.
Para sobreviver ao logout, o linger precisa estar ativo:

```bash
loginctl enable-linger $USER
```

> **Nota histórica, ainda útil.** Enquanto o motor era o Hermes, este unit tinha
> `After=hermes-gateway.service` e a versão anterior tinha `Wants=`. Isso causou um
> loop de restart real: o gateway pode ter sido iniciado **fora** do systemd (por
> `hermes gateway restart`), e aí cada start do app disparava um start do gateway
> que falhava com `Gateway already running` — e o `Restart=always` do gateway
> reiniciava para sempre. Fica registrado porque o mesmo padrão aparece em
> qualquer serviço que dependa de outro capaz de subir fora do systemd.

No macOS e no Windows não há systemd — lá o caminho é launchd / Task Scheduler,
ou simplesmente rodar `uv run frutiger-lm` quando precisar.

## Usando

1. **Cadernos** — a primeira tela lista seus cadernos. "Novo caderno" cria um.
2. Ao abrir um caderno você tem três colunas:
   - **Fontes** (esquerda): adicione link, PDF, vídeo do YouTube ou texto colado.
     Cada fonte tem um interruptor: desligue para tirá-la do contexto sem apagar.
   - **Chat** (meio): pergunte. As respostas citam as fontes (`[1]`, `[2]`) e você
     vê quais ferramentas o agente usou enquanto trabalha.
   - **Outputs** (direita): gere um documento a partir das fontes — resumo
     executivo, guia de estudo, FAQ, linha do tempo, mapa de conceitos, tabela
     comparativa ou plano de aprendizado. Fica salvo, versionado e exportável em
     `.md`. É este painel que a F4 reformula.

### Como o agente "lê" as fontes

Duas estratégias, escolhidas automaticamente:

- **Caderno pequeno** (padrão: até 24.000 caracteres ≈ 6k tokens de fontes): o
  conteúdo inteiro das fontes vai no prompt. Resposta mais rápida e barata.
- **Caderno grande**: o prompt leva só o índice (título, tipo, tamanho e o caminho
  do arquivo) e o agente usa as ferramentas de leitura para consultar o que
  precisa, quando precisa.

O limite fica em `FRUTIGER_INLINE_LIMIT` no `.env`.

### Custo

O prompt de sistema é **nosso** e pequeno: as regras de conduta, o contexto do
caderno e o schema das quatro ferramentas expostas (`listar_fontes`, `ler_fonte`,
`buscar_nas_fontes`, `web_extract`). Não há catálogo de ferramentas genéricas
carregado a cada turno — o conjunto exposto é curado por caderno.

O que domina o custo, então, é o tamanho das suas fontes: caderno pequeno vai
inteiro no prompt; caderno grande manda só o índice e o agente lê por ferramenta.

## Configuração

O modelo (endereço, nome, chave) é configurado pelo botão **Modelo** na tela
inicial e fica em `data/model.json`. O resto está em `.env.example`:

| Variável | Padrão | Para que serve |
|---|---|---|
| `LLM_AGENT` | — | configuração do modelo pelo `.env` (alternativa à UI) |
| `FRUTIGER_DATA_DIR` | `./data` | banco, arquivos das fontes e a config do modelo |
| `FRUTIGER_PORT` | `8765` | porta do app |
| `FRUTIGER_INLINE_LIMIT` | `24000` | quando parar de inlinar e passar a usar as ferramentas |

> `data/` contém a sua chave de API. Não versione nem compartilhe esse diretório.

Os modelos de embedding (`LLM_EMBED`, para as arestas por similaridade da F6)
entram quando essa fase chegar.

## Multi-usuário

O app nasceu **self-host**: cada pessoa clona, roda com a própria chave de modelo.
Não há login nem tabela de usuários. A camada de estado já é isolada por diretório
de dados (`FRUTIGER_DATA_DIR`), então virar multiusuário é configuração, não
reescrita.

Para servir várias pessoas, o caminho é autenticação na frente (nginx + basic
auth, ou o proxy de sua preferência) e uma instância por pessoa — justamente
porque cada instância tem o seu diretório, o seu banco e a sua chave.

## Notas de arquitetura

- **As fontes são arquivos de verdade em disco.** Você pode abrir, grepar,
  versionar com git ou jogar num backup sem falar com o app.
- **A conversa vive no nosso SQLite**, não em serviço externo: um caderno é um
  `thread_id` no checkpointer (`data/checkpoints.db`). Apagar o caderno apaga a
  conversa junto, e "Nova conversa" apaga só a conversa.
- **As fontes não entram no histórico da conversa.** O contexto do caderno é
  remontado a cada turno a partir do banco e dos arquivos; o que é persistido é a
  conversa. Assim, ligar/desligar uma fonte muda o que o agente sabe **sem**
  invalidar a memória da conversa.
- **Outputs não passam pelo agente do chat.** São gerados fora dele, para que
  gerar um guia de estudo não suje o histórico nem gaste contexto acumulado.
- **Toda ferramenta que lê arquivo limita a própria saída** e diz onde parou. Uma
  ferramenta capaz de despejar 400 mil caracteres no contexto quebra o turno.

## Desenvolvimento

```bash
uv sync                     # dependências + ferramentas de dev
uv run ruff check .         # lint
uv run pytest               # testes: 109, em ~1 s, sem rede e sem chave
uv run frutiger-lm --reload # servidor com recarga automática
```

Os testes cobrem o que é nosso: banco, montagem de contexto, ingestão, prompts,
persistência da conversa, as ferramentas, a tradução de eventos do agente e as
rotas. Nada toca a rede: o modelo é falso (`engine/fake.py`) e **tem paridade
entre bloco e stream**, que é o que permite testar o caminho real do app — o
streaming.

O fake é nosso, e não o da biblioteca, porque o da biblioteca não conduz o laço do
agente (o `bind_tools` dele levanta `NotImplementedError`) nem sobrevive ao
streaming de uma mensagem que só carrega tool call. As duas limitações foram
descobertas testando.

Comportamento de LLM real não é testável de forma determinística — isso é validado
à parte, com o provedor de verdade.

## Licença

MIT.
