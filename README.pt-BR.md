# Frutiger LM

**Português** · [English](README.md)

Notebooks de estudo com as suas fontes, conversa, outputs e um **grafo de
conhecimento ancorado** — o que você estuda vira conceito ligado a conceito, com
rastro até a fonte.

> **Projeto independente**, sem afiliação com a Monotype. "Frutiger" aqui se
> refere à linhagem estética que inspira a interface.
>
> **Arquitetura e roadmap:** veja [PROJETO.md](PROJETO.md). É o documento-vivo do
> projeto — toda decisão estrutural está registrada lá, com status e justificativa.
> Está em português, como o [AGENTS.md](AGENTS.md) (o guia de quem mexe no código).
>
> **Vai mexer no código?** Leia [AGENTS.md](AGENTS.md): comandos, as regras que não
> se negociam, o mapa dos arquivos e as armadilhas que já custaram tempo.

Se você já usou o NotebookLM do Google, a ideia parte da mesma base, mas com uma
diferença de fundo: o NotebookLM é um **consumidor de fontes** (joga material,
conversa, gera um output, e aquilo morre ali). O Frutiger LM é um **construtor
de conhecimento que persiste e se liga**. Sem imagens e sem áudio — só estrutura
de estudo.

> **Estado: motor próprio.** O agente é um grafo LangGraph que vive dentro do app:
> nada de motor ou serviço externo para subir — só uma **API key** de um provedor, ou
> um modelo local rodando na sua máquina.

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
| Conhecimento   | a conclusão do chat pode virar conceito no grafo, ancorada no trecho literal da própria resposta |
| Outputs        | documento Markdown salvo; o compilado sai do grafo, não do modelo |
| Modelo + chave | `data/model.json` (0600) ou `LLM_AGENT` no `.env`            |
| Embeddings     | mesmo arquivo (`embed_*`), opcional — só para as arestas por similaridade |
| Login          | `data/auth.json` (0600): hash da senha e o segredo da sessão |

As **arestas por similaridade** são a única coisa do grafo que o app **infere** em vez
de ler do material: ele vetoriza cada conceito (nome + trechos) e liga o que fala da mesma
coisa **sem o material ter ligado**. Por isso a inferida nunca se disfarça de afirmação —
traço tracejado, etiqueta lilás dizendo a nota ("parecido 87%") e procedência
`inferida por <modelo>`. O limiar foi medido no material real, não escolhido: com cosseno de
mediana 0,56 neste domínio, só o topo da distribuição informa. E o vetor é guardado com o
modelo e o texto que o produziram, então rodar de novo é instantâneo.

## Requisitos

- Linux, macOS ou Windows
- [uv](https://docs.astral.sh/uv/) (ou Python 3.11+ e pip)
- Uma **API key** de um provedor OpenAI-compatível — ou um modelo local
  (LM Studio, llama.cpp). Sem chave nenhuma o app funciona para organizar
  cadernos; só o chat é que avisa que falta configurar o modelo.

## Instalação

### 1. Rode o app

```bash
git clone https://github.com/victormedrado99/frutiger-lm.git && cd frutiger-lm
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

> **Nota histórica, ainda útil.** Este unit já teve `After=` e `Wants=` para o
> serviço do motor antigo, e isso causou um loop de restart real: aquele serviço
> podia ter sido iniciado **fora** do systemd, e aí cada start do app disparava um
> start que falhava com `already running` — e o `Restart=always` do outro
> reiniciava para sempre. Fica registrado porque o mesmo padrão aparece em
> qualquer serviço que dependa de outro capaz de subir fora do systemd.

No macOS e no Windows não há systemd — lá o caminho é launchd / Task Scheduler,
ou simplesmente rodar `uv run frutiger-lm` quando precisar.

## Hospedando num servidor (login)

O app nasceu local: escuta em `127.0.0.1`, e quem está na máquina já é o dono. Hospedado,
ele passa a precisar de uma porta fechada — porque o que está aqui dentro não é só leitura:
são os seus cadernos, as suas conversas e a **chave da API do modelo**.

Defina o usuário e a senha (a senha é pedida sem eco e **não** entra na linha de comando):

```bash
uv run frutiger-lm --senha
#   Usuário [dono]: victor
#   Senha (mínimo 8 caracteres):
#   Repita a senha:
```

Isso grava o hash — nunca a senha — em `data/auth.json`, com permissão `0600`, o mesmo
contrato do `model.json`. Depois é só subir olhando para fora:

```bash
uv run frutiger-lm --host 0.0.0.0 --port 8765
```

**Sem senha definida, o app recusa subir em endereço que não seja loopback**, e diz o
comando que resolve. Não existe "esqueci de ligar a segurança".

Como funciona:

- **Sessão em cookie assinado** (`HttpOnly`, `SameSite=Lax`, 30 dias), com prazo que
  desliza enquanto você usa: o navegador lembra de você, e não há token em tabela.
- **Cinco tentativas erradas** da mesma origem e a espera começa a dobrar, até 15 minutos.
- **Trocar a senha derruba todas as sessões** — é assim que se tira alguém de dentro, sem
  precisar de tabela de revogação.
- Para voltar ao modo aberto (só faz sentido em máquina local): `uv run frutiger-lm --sem-login`.

**TLS não é do app.** Quem hospeda põe nginx/Caddy na frente, e é lá que o certificado vive.
O app lê o `X-Forwarded-Proto` e marca o cookie como `Secure` sozinho — um exemplo de nginx:

```nginx
location / {
    proxy_pass http://127.0.0.1:8765;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_buffering off;          # o chat é SSE: sem isto a resposta chega de uma vez
    proxy_read_timeout 300s;
}
```

O que fica **fora de propósito**: multiusuário, cadastro, convite, papéis e OAuth/SSO — o
público é uma pessoa. Para servir várias, o caminho é uma instância por pessoa (cada uma com
o seu diretório de dados e a sua chave), e o login de cada uma protege a sua.

## Usando

1. **Cadernos** — a primeira tela lista seus cadernos. "Novo caderno" cria um.
   Na barra de baixo, **"Pergunte a todos os seus cadernos"**: um chat que enxerga
   tudo de uma vez, procura em cada caderno e mostra o que se liga com o quê —
   sempre dizendo de qual caderno veio cada informação.
2. Ao abrir um caderno você tem três colunas:
   - **Fontes** (esquerda): adicione link, PDF, vídeo do YouTube ou texto colado.
     Cada fonte tem um interruptor: desligue para tirá-la do contexto sem apagar.
   - **Chat** (meio): pergunte. As respostas citam as fontes (`[1]`, `[2]`) e você
     vê quais ferramentas o agente usou enquanto trabalha. Quando uma resposta vale,
     embaixo dela há **"virar conhecimento"**: o modelo relê a resposta, extrai os
     conceitos e cada um entra no grafo com o **trecho literal da própria resposta** por
     âncora. A resposta deixa de morrer no chat — e a tela do conceito marca essas
     menções como **"dita pelo modelo"**, para nunca passarem por trecho de fonte.
   - **Painel** (direita), em duas abas:
     - **Gerar** — o **documento compilado**: o material reunido num documento, com
       cada conceito acompanhado do trecho literal que o sustenta, as lacunas, o
       rendimento de cada fonte e o apêndice com todas as citações. Só o resumo e o
       desenvolvimento são escritos pelo modelo; o resto é consulta ao grafo, e cada
       seção diz de onde veio. Também saem daqui a folha de impressão (para salvar em
       PDF pelo navegador), os cartões para o **Anki** e as notas para o **Obsidian**.
       Os sete modelos de texto abaixo são o que o modelo escreve sozinho.
       A compilação roda **fora do turno**: você pode pedir pelo botão ou pelo chat, e
       ela aparece aqui enquanto é escrita — a mesma compilação, o mesmo código.
     - **Estudar** — os cartões gerados dos conceitos (com o trecho no verso), a
       revisão do dia com quatro notas, as lacunas conferíveis e as notas por conceito.

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
caderno e o schema das ferramentas expostas naquele contexto (`listar_fontes`,
`ler_fonte`, `buscar_nas_fontes`, `web_extract`, as três do grafo, as de estudo e a
compilação). Não há catálogo de ferramentas genéricas carregado a cada turno — o
conjunto exposto é curado por caderno.

O que domina o custo, então, é o tamanho das suas fontes: caderno pequeno vai
inteiro no prompt; caderno grande manda só o índice e o agente lê por ferramenta.

## Configuração

O modelo (endereço, nome, chave) é configurado pelo botão **Modelo** na tela
inicial e fica em `data/model.json`. O resto está em `.env.example`:

| Variável | Padrão | Para que serve |
|---|---|---|
| `LLM_AGENT` | — | configuração do modelo pelo `.env` (alternativa à UI) |
| `LLM_EMBED` | — | o modelo de **embedding** pelo `.env` (opcional; o mesmo formato `openai\|url\|modelo\|chave`) |
| `FRUTIGER_DATA_DIR` | `./data` | banco, arquivos das fontes, a config do modelo e o login |
| `FRUTIGER_PORT` | `8765` | porta do app |
| `FRUTIGER_INLINE_LIMIT` | `24000` | quando parar de inlinar e passar a usar as ferramentas |

> `data/` contém a sua chave de API e o hash da sua senha. Não versione nem compartilhe
> esse diretório.

O **embedding é opcional** e o app diz isso em vez de fingir: sem ele tudo funciona, só não
há arestas por similaridade (o botão explica o que falta em vez de falhar em silêncio). Ele
é configurado no mesmo modal, no bloco "Embeddings", com um botão de testar que devolve a
dimensão do vetor. E ele **não precisa ser o mesmo provedor do chat**: a DeepSeek, por
exemplo, não oferece embeddings — quem quer a fase usa um servidor local:

```bash
# llama.cpp servindo um modelo de embedding, do jeito que foi provado aqui
llama-server --embeddings --pooling mean \
  --model nomic-embed-text-v1.5.Q4_K_M.gguf --port 8080 --ctx-size 4096
# e no modal: http://127.0.0.1:8080/v1 · nomic-embed-text-v1.5 · (sem chave)
```

O unit `frutiger-embed.service` (systemd --user) existe e nasce **desligado** — ligar é
decisão de quem usa a máquina, porque consome memória e ocupa a porta:

```bash
pkill -f 'llama-server.*--embeddings'          # se já houver um na 8080
systemctl --user enable --now frutiger-embed.service
```

Se preferir o LM Studio (interface gráfica), não ligue o unit: aponte o bloco "Embeddings"
para a porta dele. O app não sabe a diferença.

O bloco de embedding tem uma armadilha de cliente que vale saber, porque o erro acusa o
modelo errado: o cliente do LangChain, por padrão, tokeniza o texto **com o tokenizador da
OpenAI** e manda IDs no lugar do texto — servidor local devolve
`400 Prompt contains invalid tokens`. O app já manda texto
(`check_embedding_ctx_length=False`); se você escrever um cliente seu, mande texto.

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
- **O login é um middleware só**, na frente de todas as rotas: nenhuma rota sabe que ele
  existe, e a que alguém esquecesse de marcar não vira porta.

## Desenvolvimento

```bash
uv sync                     # dependências + ferramentas de dev
uv run ruff check .         # lint
uv run pytest               # testes: 366, em ~5 s, sem rede e sem chave
uv run frutiger-lm --reload # servidor com recarga automática
```

Os testes cobrem o que é nosso: banco, montagem de contexto, ingestão, prompts,
persistência da conversa, as ferramentas, a tradução de eventos do agente, as
rotas e o login. Nada toca a rede: o modelo é falso (`engine/fake.py`) e **tem
paridade entre bloco e stream**, que é o que permite testar o caminho real do app —
o streaming.

O fake é nosso, e não o da biblioteca, porque o da biblioteca não conduz o laço do
agente (o `bind_tools` dele levanta `NotImplementedError`) nem sobrevive ao
streaming de uma mensagem que só carrega tool call. As duas limitações foram
descobertas testando.

Comportamento de LLM real não é testável de forma determinística — isso é validado
à parte, com o provedor de verdade.

## Licença

MIT — veja [LICENSE](LICENSE).
