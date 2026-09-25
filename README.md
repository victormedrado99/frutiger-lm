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

> **Estado: em migração de motor.** O motor atual é o Hermes Agent; ele está sendo
> substituído por um agente LangGraph próprio, com ferramentas fixas (F1 do
> PROJETO.md). Quando F1 terminar, o requisito deixa de ser "um Hermes instalado"
> e passa a ser apenas uma **API key** de modelo — ou nada, se você usar modelo
> local.

## Como funciona (hoje)

```
   ┌───────────────────────┐        HTTP / SSE         ┌────────────────────┐
   │  Frutiger LM (o app)  │  ──────────────────────▶  │  motor             │
   │  FastAPI + UI vanilla │   /api/sessions/{id}/chat │  Hermes hoje       │
   │  cadernos, fontes,    │  ◀──────────────────────   │  LangGraph na F1   │
   │  outputs, SQLite      │        streaming          │  modelo + tools    │
   └───────────────────────┘                           └────────────────────┘
```

Mapeamento dos conceitos:

| Conceito       | Onde vive                                                  |
|---|---|
| Caderno        | linha no SQLite + um `thread_id` no motor                    |
| Fontes         | arquivos `.txt` em `data/notebooks/<id>/fontes/` + SQLite    |
| Chat           | streaming (SSE) do motor                                     |
| Outputs        | documento Markdown gerado e salvo, versionado                |

## Requisitos

- Linux, macOS ou Windows
- [uv](https://docs.astral.sh/uv/) (ou Python 3.11+ e pip)
- **Hoje:** um Hermes Agent instalado e configurado com um provedor de modelo.
  **Depois da F1:** apenas uma API key de modelo (ou um modelo local).

## Instalação

### 1. Ligue o API server do Hermes (etapa temporária)

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

> Esta etapa desaparece na F1, quando o motor passa a ser nosso.

Confirme que subiu:

```bash
curl http://127.0.0.1:8642/health
# {"status": "ok", "platform": "hermes-agent", ...}
```

> Esse endpoint dá acesso às ferramentas do agente. Nunca exponha a porta 8642
> na internet — o app fala com ela por loopback.

### 2. Rode o app

```bash
git clone <este-repo> frutiger-lm && cd frutiger-lm
cp .env.example .env      # e ponha a MESMA chave do API_SERVER_KEY em HERMES_KEY
uv sync
uv run frutiger-lm
```

Abra http://127.0.0.1:8765.

### 3. (Opcional, Linux) Deixar sempre no ar

O unit está versionado em `deploy/frutiger-lm.service`:

```bash
install -m 644 deploy/frutiger-lm.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now frutiger-lm.service
```

Ele declara `After=hermes-gateway.service`, então o app espera o motor subir, e
`Restart=always` faz ele voltar sozinho se cair (testado com `kill -9`).

Ajuste o caminho do projeto no unit se você não clonou em `~/Projetos/caderno`.
Para sobreviver ao logout, o linger precisa estar ativo:

```bash
loginctl enable-linger $USER
```

> **Não use `Wants=hermes-gateway.service`** neste unit — só `After=`. Motivo: o
> gateway pode ter sido iniciado fora do systemd (por `hermes gateway restart`,
> que sobe o processo sem o systemd rastreá-lo). Com `Wants=`, cada start do app
> dispara uma tentativa de subir o gateway, que falha com
> `Gateway already running` e entra em **loop de restart** (o
> `hermes-gateway.service` tem `Restart=always`). O sintoma é `NRestarts` subindo
> sem parar e o journal repetindo "already running".
>
> Para sair do loop:
> ```bash
> systemctl --user stop hermes-gateway.service
> hermes gateway stop
> systemctl --user start hermes-gateway.service
> ```
> Depois disso o processo passa a ser o que o systemd rastreia e o contador
> estabiliza em zero.

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

### Custo (hoje)

O agente carrega o prompt de sistema do Hermes (descrição de todas as ferramentas)
em cada turno — na casa de **15 a 20 mil tokens de entrada**, mesmo para uma
pergunta trivial. Esse custo **desaparece na F1**, quando o prompt de sistema passa
a ser nosso e as ferramentas ficam restritas às do app.

Se pesar enquanto isso, enxugue as ferramentas do agente:

```bash
hermes tools disable browser
hermes tools disable vision
hermes tools disable image_gen
hermes tools disable terminal
```

## Configuração

Veja `.env.example`. As principais:

| Variável | Padrão | Para que serve |
|---|---|---|
| `HERMES_URL` | `http://127.0.0.1:8642` | onde está o motor (temporário) |
| `HERMES_KEY` | — | a chave do `API_SERVER_KEY` (temporário) |
| `FRUTIGER_DATA_DIR` | `./data` | banco SQLite e arquivos das fontes |
| `FRUTIGER_PORT` | `8765` | porta do app |
| `FRUTIGER_INLINE_LIMIT` | `24000` | quando parar de inlinar e passar a usar tools |
| `FRUTIGER_SESSION_KEY` | `frutiger:local:` | escopo da memória de longo prazo no motor |

Na F1 entram as variáveis de modelo (`LLM_CHAT`, `LLM_FAST`, `LLM_EMBED`), que é
como se escolhe API ou modelo local.

## Multi-usuário

O app nasceu **self-host**: cada pessoa clona, roda com a própria chave de modelo.
Não há login nem tabela de usuários. A camada de estado já é isolada por diretório
de dados, então virar multiusuário é configuração, não reescrita.

Para servir várias pessoas, o caminho é autenticação na frente (nginx + basic
auth, ou o proxy de sua preferência) e uma instância por pessoa.

## Notas de arquitetura

- **As fontes são arquivos de verdade em disco.** Você pode abrir, grepar,
  versionar com git ou jogar num backup sem falar com o app.
- **As fontes entram por `system_message`**, que é *efêmero* no motor atual: vale
  para o turno, não é persistido no histórico, e portanto não invalida o cache de
  prompt nem polui a conversa.
- **Outputs não passam pela sessão do chat.** São gerados fora dela, para que gerar
  um guia de estudo não suje o histórico nem gaste contexto acumulado.
- **Apagar `data/` na mão órfã as sessões no motor.** O lado do app é quem guarda o
  id da sessão; apagar o banco sem passar pelo app deixa conversas sem dono. Apague
  cadernos pelo botão do app. (Isso desaparece na F1, quando o estado da conversa
  vem para o nosso SQLite.)

## Desenvolvimento

```bash
uv sync                    # dependências + ferramentas de dev
uv run ruff check .        # lint
uv run pytest              # testes (48, rodam em ~0,2 s, sem rede)
uv run frutiger-lm --reload # servidor com recarga automática
```

Os testes cobrem o que é nosso: banco, montagem do contexto (incluindo a fronteira
entre injetar o texto e mandar o agente ler o arquivo), ingestão (texto, PDF,
detecção de YouTube) e os prompts. Nada neles toca a rede nem o motor —
comportamento de LLM não é testável de forma determinística e é validado à parte.

## Licença

MIT. O Hermes Agent é um projeto separado, do Nous Research, com licença própria.
