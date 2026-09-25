# Hermes LM — projeto

Documento-vivo de arquitetura. Toda decisão estrutural entra aqui com status.
Este arquivo é a fonte da verdade: se o código divergir dele, um dos dois está
errado e precisa ser corrigido.

Última atualização: 2026-09-25

---

## 1. Posicionamento

O NotebookLM é um **consumidor de fontes**: você joga material, conversa, gera um
output e aquilo morre ali.

O Hermes LM é um **construtor de conhecimento que persiste e se liga**: o que
você estuda vira conceito ancorado, os conceitos se conectam entre cadernos, e o
conjunto fica navegável e verificável.

Essa frase é o filtro de todas as decisões. Se uma funcionalidade não empurra o
app para "construtor de conhecimento", ela provavelmente não é para aqui.

Três consequências práticas:

1. **Só texto.** Sem imagem, sem áudio. Foco em estrutura de estudo.
2. **Ancoragem é obrigatória.** Nada de afirmação sem rastro até a fonte.
3. **O cliente traz a própria chave.** Clonar, instalar, colar a API key, usar.
   Modelo local não precisa nem de chave.

O nome "Hermes LM" é histórico (o motor original era o Hermes Agent) e o produto
se chama assim; não há afiliação com o Nous Research. Ver D004 e D017.

---

## 2. Registo de decisões

Status: `DECIDIDO` · `PROPOSTO` (falta seu OK) · `ABERTO` (a discutir) ·
`REVERTIDO`

| # | Decisão | Status |
|---|---------|--------|
| D001 | App web local-first: FastAPI + SQLite + UI vanilla sem build | DECIDIDO |
| D002 | Fonte = arquivo em disco + linha no SQLite; output = markdown versionado | DECIDIDO |
| D003 | Motor fica atrás de uma interface; dois tipos de rota (agente / conversa) | DECIDIDO |
| D004 | O motor do agente é NOSSO; o Hermes vira backend opcional | **REVERTIDO** |
| D005 | O nó do grafo é **conceito**, não caderno nem fonte | DECIDIDO |
| D006 | Todo nó é **ancorado**: aponta para o trecho exato que o originou | DECIDIDO |
| D007 | Extração automática ao ingerir fonte e ao gerar output; botão manual na resposta do chat | DECIDIDO |
| D008 | Chat do caderno pode usar ferramenta de leitura; **chat global não usa ferramenta** | DECIDIDO |
| D009 | Nó canônico com aliases + edição pelo usuário (mesclar/renomear/apagar) | DECIDIDO |
| D010 | Modelo local (LM Studio / llama.cpp) para tarefas estruturadas; API para síntese | DECIDIDO |
| D011 | **Nenhuma ferramenta de terminal.** O app nunca expõe shell | DECIDIDO |
| D012 | Nome do produto: Hermes LM. Rename nível 1 feito; nível 2 pendente | DECIDIDO |
| D013 | Estética: Frutiger Aero | DECIDIDO |
| D014 | Export PDF via CSS de impressão + `window.print()` | PROPOSTO |
| D015 | Fase 1 (alicerce) antes de qualquer funcionalidade visível | DECIDIDO |
| D016 | Régua de verificação: `uv run ruff check .` + `uv run pytest` | DECIDIDO |
| D017 | **Motor = LangGraph, via `langchain.agents.create_agent`.** Hermes sai de vez | DECIDIDO |
| D018 | Só o pacote `engine/` importa LangChain. O resto do app não conhece a lib | DECIDIDO |
| D019 | Persistência de conversa pelo `checkpointer` (AsyncSqliteSaver), não por tabela própria | DECIDIDO |
| D020 | Um único cliente de modelo OpenAI-compatível cobre API e local | DECIDIDO |
| D021 | Extração de conceito por `response_format` (structured output), não por JSON solto | DECIDIDO |
| D022 | Versões do stack LangChain **pinadas** | DECIDIDO |

### D004 — REVERTIDO (mantido para registro)

Decisão original: motor próprio, ~400 linhas de loop, Hermes como backend
opcional. O **raciocínio continua válido** e é a base da D017 — só mudou *como*
fazer o motor: em vez de escrever o loop à mão, usamos LangGraph.

O que motivou a reversão: escrever o loop à mão nos daria a obrigação de
implementar e manter normalização de tool call entre provedores, reparo de tool
call emitida como texto, streaming, retry e compactação de contexto. LangGraph
entrega tudo isso, e mais o checkpointer e o structured output.

O diagnóstico que **permanece** (medido em 2026-09-25, máquina de referência):

```
Hermes instalado ............. 1,9 GB
dependências Python .......... 138
arquivos .py ................. 10.139
API server ................... gateway/platforms/api_server.py
                               (ao lado de signal.py, bluebubbles.py, qqbot/,
                               com um ADDING_A_PLATFORM.md na pasta)
```

As três razões para tirar o Hermes do caminho crítico seguem de pé e são o que
sustenta a D017:

1. **Adoção.** 1,9 GB antes do primeiro "olá" mata a promessa de "com uma API
   key, qualquer pessoa usa". Medido, o stack LangGraph completo é **89 MB e 49
   pacotes** — ~21× menor.
2. **Superfície errada.** O API server é adaptador de plataforma de mensagem, não
   API de biblioteca. Dependíamos de `/api/sessions/{id}/chat/stream`. Se muda,
   o app quebra.
3. **Controle do contexto é o produto.** Citação, ancoragem e extração de
   conceito *são* o valor do app.

### D017 — por que LangGraph (e não loop próprio)

Comparação das três opções, com o que foi medido:

| | Hermes como motor | Loop próprio | LangGraph |
|---|---|---|---|
| peso | 1,9 GB / 138 deps | ~0 | 89 MB / 49 deps |
| loop de agente | pronto | escrever e manter | pronto |
| tool call entre provedores | resolvido | **nosso problema** | resolvido pela lib |
| persistência de conversa | sessões do gateway | tabela nossa | `checkpointer` |
| streaming | SSE do gateway | escrever | `astream_events` |
| saída estruturada p/ extração | não tem | escrever | `response_format` |
| controle do prompt/contexto | baixo | total | total |
| risco de churn | contrato de gateway | nenhum | **real, já comprovado** |

O churn não é teoria: na verificação desta sessão, o `create_react_agent` do
LangGraph 1.2.12 já emite `LangGraphDeprecatedSinceV10` dizendo que mudou para
`langchain.agents.create_agent` e será **removido na v2**. Foi por isso que a
D022 (pinagem) existe.

E o motivo pelo qual LangGraph substitui o loop próprio sem perder o argumento
"controle do contexto": o grafo **expõe** o estado em vez de esconder. O
`system_prompt` é montado por nós, o estado é nosso (`state_schema`), e as
ferramentas são nossas. Não é uma caixa-preta — é a nossa caixa, com as partes
chatas já feitas.

### D018 — a fronteira é obrigatória

Todo o contato com LangChain vive em `engine/`. Nenhum outro módulo importa
`langchain`, `langgraph` ou `langchain_openai`. Três motivos:

1. **Churn contido**: quando a v2 chegar, o trabalho de atualização é um pacote.
2. **Teste sem framework**: o resto do app testa contra as nossas funções, com
   um modelo falso. Sem rede, sem chave, sem custo.
3. **Troca possível**: se LangGraph decepcionar, o loop próprio da D004 volta
   como uma implementação alternativa dentro de `engine/`, sem tocar no resto.

### D019 — o checkpointer faz o trabalho

`AsyncSqliteSaver` guarda o estado do grafo no **SQLite que já usamos**. Isso
substitui três coisas de uma vez:

- a tabela `messages` que eu tinha planejado escrever à mão;
- as sessões do Hermes (e a armadilha das sessões órfãs morre junto);
- o versionamento de conversa — `aget_state_history` dá o histórico de estados,
  que é base para "voltar a uma resposta anterior".

Chave natural: **um caderno = um `thread_id`**. Um caderno, uma linha do tempo.

### D020 — um cliente para tudo

`ChatOpenAI(base_url=..., api_key=..., model=...)` cobre, com a mesma classe:
OpenAI, DeepSeek, OpenRouter, Groq, vLLM, **LM Studio** (`:1234/v1`),
**llama.cpp** (`:8080/v1`) e Ollama (via `/v1`). Verificado nesta sessão: `base_url`,
`api_key` e `model` são aceitos e chegam ao lugar certo (são aliases do pydantic
para `openai_api_base`, `openai_api_key` e `model_name`).

Consequência: **"colocar a API key" é literalmente uma linha**, e modelo local não
precisa de chave nenhuma.

---

## 3. Arquitetura em camadas

```
┌──────────────────────────────────────────────────────┐
│ static/  UI vanilla (sem build)                      │
│   index / notebook / graph.js (canvas) / md.js       │
└───────────────────────┬──────────────────────────────┘
                        │ JSON + SSE
┌───────────────────────┴──────────────────────────────┐
│ app.py   rotas FastAPI                               │
└───────────────────────┬──────────────────────────────┘
     ┌──────────┬───────┴────────┬──────────────┐
     ▼          ▼                ▼              ▼
 knowledge.py export.py      ingest.py      engine/   ◄── FRONTEIRA
 conceitos,   compilação     link/PDF/      (único que
 arestas,     do doc + PDF   YouTube/texto  importa
 ancoragem                                   LangChain)
     │          │                │              │
     └──────────┴────────┬───────┴──────────────┘
                         ▼
                    db.py  (SQLite)
                    + checkpointer do LangGraph
                         │
                         ▼
              modelo: API (chave do cliente)
                      ou local (LM Studio / llama.cpp)
```

Dentro de `engine/`:

```
engine/
  llm.py         fábrica de modelo a partir do .env (OpenAI-compatível)
  agent.py       create_agent(system_prompt nosso, tools nossas, checkpointer)
  tools.py       as 5 ferramentas fixas
  checkpoint.py  AsyncSqliteSaver no mesmo SQLite
  fake.py        modelo falso p/ teste, sem rede
```

Estrutura de arquivos alvo do projeto:

```
caderno/
  config.py      ← existe; ganha a config de backends
  db.py          ← existe; ganha concepts, mentions, edges, notes, index_cache
  ingest.py      ← existe
  prompts.py     ← existe
  app.py         ← existe; ganha as rotas novas
  knowledge.py   ← NOVO  extração, nó canônico, arestas, ancoragem
  export.py      ← NOVO  compilação do documento, PDF, Anki, Obsidian
  engine/        ← NOVO  a fronteira (D018)
  static/
    app.css      ← existe
    graph.js     ← NOVO  force-directed em canvas, sem dependência
```

Regra de ouro: **`engine/` é a única porta para modelo.** Trocar de provedor é
mudar configuração, nunca código.

---

## 4. Roteamento de modelo

```
tarefa                             rota   como
chat dentro do caderno             A      create_agent + ferramentas + checkpointer
chat global                        B      ChatOpenAI direto, sem grafo
extrair conceitos de uma fonte     B      response_format (Pydantic) — D021
resumir fonte para o índice        B      ChatOpenAI direto
compilar o documento / PDF         B      ChatOpenAI direto
título e descrição do caderno      B      ChatOpenAI direto
arestas por similaridade           C      modelo de embedding
```

A rota A é a única que usa grafo. A rota B é chamada direta no modelo — mais
barata, mais rápida, e sem o overhead de um grafo quando não há ferramenta.

Configuração (uma linha por uso):

```
LLM_CHAT  = openai|https://api.deepseek.com/v1|deepseek-chat|<key>
LLM_FAST  = openai|http://127.0.0.1:1234/v1|qwen2.5-7b-instruct|
LLM_EMBED = openai|http://127.0.0.1:1234/v1|nomic-embed-text|
```

Padrão a respeitar: **tarefa barata e estruturada vai para local; síntese com
fontes vai para API.** Extrair conceito com modelo local = grafo de graça.

---

## 5. Ferramentas fixas (D011 aplicada)

Superfície mínima, e é para continuar pequena:

| ferramenta | o que faz |
|---|---|
| `list_sources` | o que existe neste caderno, com id e tamanho |
| `read_source` | lê um trecho de uma fonte (offset/limit) |
| `search_sources` | busca textual nas fontes deste caderno |
| `web_search` | busca na web (enriquecer) |
| `web_extract` | extrai o texto de uma URL |

**Nenhuma ferramenta de terminal.** O agente lê arquivos e a web, e nada além.
Não é só economia de prompt: é o que torna o app seguro de colocar na VPS.

---

## 6. Modelo de dados

Já existe:

```
notebooks(id, title, description, created_at, updated_at)
sources(id, notebook_id, kind, title, url, file_path, chars, active, created_at)
outputs(id, notebook_id, template, title, body, created_at)
```

Novo:

```
concepts(id, name, canonical, aliases, kind, created_at, updated_at)
  → canonical = forma normalizada p/ deduplicar; aliases = "ADI" ↔ nome completo

mentions(id, concept_id, notebook_id, source_id, output_id, thread_id,
         message_id, excerpt, created_at)
  → É o mecanismo da ancoragem: cada menção guarda o TRECHO de origem

edges(id, a_id, b_id, kind, weight, provenance, created_at)
  → kind: co_occurrence | explicit | similarity
  → UNIQUE(a_id, b_id, kind)

notes(id, concept_id, notebook_id, body, created_at)
  → nota do usuário presa a um conceito (o "estilo Obsidian" de verdade)

index_cache(notebook_id, summary, concepts_blob, built_at)
  → alimenta o chat global sem recarregar tudo
```

Não criamos tabela de mensagens: o `checkpointer` do LangGraph cuida disso
(D019). As tabelas dele convivem no mesmo arquivo SQLite.

Índices obrigatórios: `mentions(concept_id)`, `edges(a_id)`, `edges(b_id)`,
`concepts(canonical)`.

---

## 7. Roadmap

Cada fase é utilizável sozinha. Nada de fase que só serve se a próxima existir.

### F1 — Alicerce (motor LangGraph)  ← PRÓXIMA
- [ ] dependências pinadas: `langgraph`, `langchain`, `langchain-openai`,
      `langgraph-checkpoint-sqlite` (D022)
- [ ] `engine/llm.py`: fábrica de modelo a partir do `.env` (D020)
- [ ] `engine/checkpoint.py`: `AsyncSqliteSaver` no mesmo SQLite, 1 caderno =
      1 `thread_id` (D019)
- [ ] `engine/fake.py`: modelo falso para teste sem rede
- [ ] `engine/tools.py`: as 5 ferramentas fixas (D011)
- [ ] `engine/agent.py`: `create_agent` com `system_prompt` nosso (D018)
- [ ] rota B: chamada direta, sem grafo
- [ ] extração de conceito com `response_format` (D021)
- [ ] rotas do app passando por `engine/` em vez do Hermes
- [ ] remover a configuração do API server do Hermes e a dependência do gateway
- [ ] **Critério de pronto:** o chat do caderno funciona **sem Hermes instalado**

### F2 — Chat global + índice
- [ ] `index_cache` e geração automática quando o caderno muda
- [ ] rota do chat global (rota B, sem ferramenta)
- [ ] barra inferior que expande na home
- [ ] botão "virar conhecimento" numa conclusão da conversa

### F3 — Grafo de conhecimento
- [ ] `knowledge.py`: extração de conceitos de fonte e de output
- [ ] nó canônico, aliases e normalização
- [ ] arestas de co-ocorrência (de graça) e explícitas (1 chamada por output)
- [ ] `graph.js`: force-directed em canvas + filtros (caderno, peso, recência)
- [ ] painel do grafo global na home
- [ ] tela do conceito: menções, trecho de origem, cadernos onde aparece
- [ ] edição: mesclar, renomear, apagar nó

### F4 — Painel direito do caderno
- [ ] cards com repetição espaçada (SRS)
- [ ] lacunas: o que as fontes NÃO cobrem
- [ ] contradições entre fontes, lado a lado
- [ ] fontes órfãs (nunca usadas numa resposta)
- [ ] notas do usuário por conceito

### F5 — Export
- [ ] passe de compilação (conversa + outputs → documento coeso)
- [ ] `export.py` + CSS de impressão claro (o tema Aero escuro gasta tinta)
- [ ] estrutura: capa, sumário, resumo, conceitos citados, desenvolvimento,
      lacunas abertas, fontes resumidas, apêndice de citações
- [ ] mesmo pipeline → Markdown, Anki, Obsidian com `[[wikilinks]]`

### F6 — Arestas por similaridade
- [ ] embeddings por conceito
- [ ] arestas `similarity` acima de limiar (a aresta que *descobre* relação)

---

## 8. Fora de escopo (por decisão, não por esquecimento)

- Imagem, áudio, vídeo generativo
- Ferramenta de terminal no agente
- Colaboração multiusuário em tempo real
- Reimplementar RAG vetorial antes do grafo por conceito provar valor
- Kubernetes, fila, microsserviço — é um app de uma máquina
- O Hermes Agent como dependência de runtime (D017)

---

## 9. Riscos conhecidos

| risco | mitigação |
|---|---|
| **Churn do LangChain/LangGraph** (comprovado: depreciação na v1) | D022 pinagem + D018 fronteira num só pacote |
| Tool call de modelo local vem quebrada ou como texto | rota B para tarefas estruturadas; testar local antes de prometer |
| Extração de conceito vira ruído | `response_format` (D021) + nó canônico + aliases + edição pelo usuário |
| Grafo vira bola de pelo (~200 nós) | filtros por caderno, peso e recência desde o primeiro dia |
| Custo da extração automática | tarefa pequena, modelo local, cache por hash da fonte |
| Escopo de 6 fases / semanas | cada fase entrega valor sozinha; nada de fase-ponte |
| 89 MB de dependências | aceito: é `pip install`, e 21× menor que o Hermes |
| Conversa longa estoura contexto | middleware de compactação do próprio LangGraph |

---

## 10. Como verificamos

Regra canônica, sem exceção:

```
uv run ruff check .
uv run pytest
```

- Todo teste que tocaria LLM usa o **modelo falso** (`engine/fake.py`): sem rede,
  sem chave, sem custo. É o que já permite 48 testes rodarem em 0,2s.
- Funcionalidade de UI se verifica **renderizando e olhando**, não por suposição.
- Toda decisão de arquitetura ganha entrada na seção 2 **antes** do código.
- Antes de escrever código contra uma API de terceiro, **verificar a assinatura
  real** na versão instalada. Foi assim que descobrimos a depreciação do
  `create_react_agent` em vez de escrever código morto.
- Commit por tarefa, não por fase.

---

## 11. Ritual de acompanhamento

O que "me atualize em cada decisão de arquitetura" significa na prática:

1. Decisão nova → vira linha na seção 2 (`D0NN`), com status e o porquê.
2. Mudança de decisão antiga → a antiga vira `REVERTIDO` com a data, não é
   apagada. Histórico do raciocínio vale mais que a lista limpa.
3. Fase em andamento → checkbox marcado no roadmap **no mesmo commit** que a
   implementação.
4. Divergência entre código e este documento → é bug, e é o documento que decide
   qual dos dois muda.

---

## 12. Estado atual (2026-09-25)

Já funcionando, com 48 testes e ruff limpo:

- cadernos, fontes (link, PDF, YouTube, texto), chat com streaming e citação,
  7 templates de output, UI em três painéis com tema Frutiger Aero
- motor atual: **Hermes via API server — é exatamente o que a D017 remove**
- serviços: `caderno.service` (app, 8765) e `hermes-gateway.service` (motor, 8642)

Verificado nesta sessão, sobre o stack que vamos adotar:

```
langgraph 1.2.12 · langchain 1.x · langchain-openai 1.6.6
langgraph-checkpoint-sqlite 3.1.1 · 89 MB · 49 pacotes

OK  langchain.agents.create_agent(model, tools, system_prompt, checkpointer,
                                  response_format, middleware, state_schema, ...)
OK  langgraph.checkpoint.sqlite.aio.AsyncSqliteSaver
OK  ChatOpenAI(base_url=..., api_key=..., model=...)  -> LM Studio e llama.cpp
OK  astream / astream_events / aget_state / aget_state_history
ATENÇÃO  langgraph.prebuilt.create_react_agent DEPRECIADO (sai na v2)
```

Primeiro trabalho: **F1**, começando por `engine/llm.py` + `engine/fake.py`,
porque é o par que permite todo o resto ser testado sem rede e sem chave.
