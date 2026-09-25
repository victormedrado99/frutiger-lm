# Caderno

Notebooks de estudo com as suas fontes, conversa e outputs — usando o
[Hermes Agent](https://github.com/NousResearch/hermes-agent) como motor.

Se você já usou o NotebookLM do Google, a ideia é a mesma, mas sem imagens e sem
áudio: só **organizar cadernos de estudo, juntar fontes e conversar com elas**.
A diferença é que o motor é um agente de verdade — ele tem terminal, leitura de
arquivos, busca na web e transcrição de vídeo, então pode ir muito além de
"responder sobre um PDF".

## Como funciona

```
   ┌──────────────────────┐         HTTP / SSE          ┌────────────────────┐
   │  Caderno (este app)  │  ───────────────────────▶   │  Hermes Agent      │
   │  FastAPI + UI        │   /api/sessions/{id}/chat   │  API server        │
   │  cadernos, fontes,   │  ◀───────────────────────   │  (o motor)         │
   │  outputs, SQLite     │        streaming            │  modelo + tools    │
   └──────────────────────┘                             └────────────────────┘
```

O app é uma **casca fina**. Todo o trabalho de agente — loop de conversação,
ferramentas, memória, streaming, histórico — é feito pelo Hermes. O Caderno
cuida só do que é seu: os cadernos, as fontes em disco e os documentos gerados.

Mapeamento dos conceitos:

| Caderno        | Sessão do Hermes (`/api/sessions/...`)                    |
| Fontes         | arquivos `.txt` em `data/notebooks/<id>/fontes/` + SQLite |
| Chat do meio   | `POST /api/sessions/{id}/chat/stream` (SSE)               |
| Outputs        | `POST /v1/chat/completions` sem estado + Markdown salvo   |

## Requisitos

- Linux, macOS ou Windows
- [uv](https://docs.astral.sh/uv/) (ou Python 3.11+ e pip)
- Um **Hermes Agent instalado e configurado** com um provedor de modelo
  (`hermes setup` ou `hermes model`)

## Instalação

### 1. Ligue o API server do Hermes

Adicione ao `~/.hermes/.env`:

```bash
API_SERVER_ENABLED=true
API_SERVER_PORT=8642
API_SERVER_HOST=127.0.0.1
API_SERVER_KEY=escolha-uma-chave-boa
```

E reinicie o gateway:

```bash
hermes gateway restart
```

Confirme que subiu:

```bash
curl http://127.0.0.1:8642/health
# {"status": "ok", "platform": "hermes-agent", ...}
```

> Esse endpoint dá acesso total às ferramentas do agente, **incluindo o
> terminal**. Nunca exponha a porta 8642 na internet. O Caderno fala com ela
> por loopback.

### 2. Rode o Caderno

```bash
git clone <este-repo> caderno && cd caderno
cp .env.example .env      # e ponha a MESMA chave do API_SERVER_KEY em HERMES_KEY
uv sync
uv run caderno
```

Abra http://127.0.0.1:8765.

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
     `.md`.

### Como o agente "lê" as fontes

Duas estratégias, escolhidas automaticamente:

- **Caderno pequeno** (padrão: até 24.000 caracteres ≈ 6k tokens de fontes):
  o conteúdo inteiro das fontes vai no prompt. Resposta mais rápida e barata.
- **Caderno grande**: o prompt leva só o índice (título, tipo, tamanho e o
  caminho do arquivo) e o agente usa `read_file` / `search_files` / `grep` para
  consultar o que precisa, quando precisa.

O limite fica em `CADERNO_INLINE_LIMIT` no `.env`. Suba se seu modelo tiver
contexto grande; desça se quiser economizar.

### Custo

O agente carrega o prompt de sistema inteiro do Hermes (descrição de todas as
ferramentas) em cada turno — na casa de **15 a 20 mil tokens de entrada**, mesmo
para uma pergunta trivial. Se isso pesar, enxugue as ferramentas do agente:

```bash
hermes tools disable browser
hermes tools disable vision
hermes tools disable image_gen
```

Ou aponte o Caderno para um [profile](https://hermes-agent.nousresearch.com/docs/user-guide/profiles)
dedicado, com toolset menor e o modelo que você quiser.

## Configuração

Veja `.env.example`. As principais:

| Variável | Padrão | Para que serve |
|---|---|---|
| `HERMES_URL` | `http://127.0.0.1:8642` | onde está o motor |
| `HERMES_KEY` | — | a chave do `API_SERVER_KEY` |
| `CADERNO_DATA_DIR` | `./data` | banco SQLite e arquivos das fontes |
| `CADERNO_PORT` | `8765` | porta do app |
| `CADERNO_INLINE_LIMIT` | `24000` | quando parar de inlinar e passar a usar tools |
| `CADERNO_SESSION_KEY` | `caderno:local:` | escopo da memória de longo prazo no Hermes |

## Multi-usuário

O Caderno nasceu **self-host**: cada pessoa clona, roda o seu Hermes e usa a
própria chave de modelo. Não há login nem tabela de usuários.

Para servir várias pessoas a partir de uma instalação, o caminho natural é
[criar um profile do Hermes por pessoa](https://hermes-agent.nousresearch.com/docs/user-guide/profiles)
(com `API_SERVER_PORT` e `API_SERVER_KEY` próprios), rodar uma instância do
Caderno por profile, e colocar autenticação na frente (nginx + basic auth, ou o
proxy de sua preferência). A camada de estado do app já é isolada por diretório
de dados, então isso é configuração, não reescrita.

## Notas de arquitetura

- **Uma sessão do Hermes por caderno.** O histórico fica no `state.db` do Hermes
  e é recarregado pelo próprio motor — o Caderno não duplica conversa.
- **As fontes entram por `system_message`**, que é *efêmero* no API server do
  Hermes: vale para o turno, não é persistido no histórico, e portanto não
  invalida o cache de prompt nem polui a conversa.
- **Outputs não passam por sessão.** Usam `/v1/chat/completions`, que é sem
  estado — assim gerar um guia de estudo não suja o histórico do chat e não
  gasta contexto acumulado.
- **As fontes são arquivos de verdade em disco.** Você pode abrir, grepar,
  versionar com git ou jogar num backup sem falar com o app.

## Licença

MIT. O Hermes Agent é um projeto separado, do Nous Research, com licença própria.
