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
3. **Local ou VPS com a mesma base.** Um `.env`, sem serviço externo obrigatório.

---

## 2. Registo de decisões

Status: `DECIDIDO` · `PROPOSTO` (falta seu OK) · `ABERTO` (a discutir) ·
`REVERTIDO`

| # | Decisão | Status |
|---|---------|--------|
| D001 | App web local-first: FastAPI + SQLite + UI vanilla sem build | DECIDIDO |
| D002 | Fonte = arquivo em disco + linha no SQLite; output = markdown versionado | DECIDIDO |
| D003 | Motor fica atrás de uma interface; dois tipos de rota (agente / conversa) | DECIDIDO |
| D004 | **O motor do agente é NOSSO.** O Hermes vira backend opcional, não o motor | DECIDIDO |
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

### D004 — por que motor próprio (a decisão maior)

Medido em 2026-09-25, na máquina de referência:

```
Hermes instalado ............. 1,9 GB
dependências Python .......... 138
arquivos .py ................. 10.139
API server ................... gateway/platforms/api_server.py
                               (ao lado de signal.py, bluebubbles.py, qqbot/)
```

Três razões para não usar o Hermes como motor:

1. **Adoção.** O projeto é open source e a promessa original é "com uma API key,
   qualquer pessoa usa". Exigir 1,9 GB, 138 dependências e um gateway
   configurado antes do primeiro "olá" mata isso. Com motor próprio, o requisito
   vira uma chave de API — ou um modelo local.
2. **Superfície errada.** O API server é um *adaptador de plataforma de
   mensagem*, desenhado como integração de chat, não como API de biblioteca. A
   gente depende hoje de `/api/sessions/{id}/chat/stream`. Isso é um contrato de
   integração com o gateway, não uma promessa de estabilidade para terceiros.
3. **Controle do contexto é o produto.** Citação, ancoragem, extração de conceito
   e montagem de prompt por tarefa **são** o valor do app. Um agente que gerencia
   o próprio histórico por baixo nos tira exatamente o que precisamos controlar.

Custo honesto de assumir isso: herdamos o "80% chato" — formato de tool call
variando entre provedores, streaming, retry, timeout, compactação de conversa
longa, e reparo de tool call emitida como texto (modelo local faz muito isso).
Estimativa: ~400 linhas para o loop, e é a parte que dá trabalho de verdade.

O que **não** fazemos: jogar o Hermes fora. Ele fica como **backend opcional** da
rota A, para quem já tem. E o código dele está no disco (`~/.hermes/hermes-agent`)
como implementação de referência — dá para ler como ele trata tool call antes de
escrever o nosso.

### D008 — por que o chat global não usa ferramenta

"Conversação" sem ferramenta tem uma consequência que precisa ficar explícita: ele
só sabe o que estiver no contexto. Então ele é alimentado por um **índice de
conhecimento** gerado automaticamente (título, descrição, conceitos e um resumo
curto por caderno). Ele é um bibliotecário que conhece a biblioteca — não um
sintetizador que leu tudo. Para "o que eu já estudei sobre X" resolve; para
"compare A com B em detalhe" ele manda você para o caderno, e está certo.

---

## 3. Arquitetura em camadas

```
┌─────────────────────────────────────────────────────┐
│ static/  UI vanilla (sem build)                     │
│   index / notebook / graph.js (canvas) / md.js      │
└──────────────────────┬──────────────────────────────┘
                       │ JSON + SSE
┌──────────────────────┴──────────────────────────────┐
│ app.py   rotas FastAPI                              │
└──────────────────────┬──────────────────────────────┘
        ┌──────────────┼───────────────┬──────────────┐
        ▼              ▼               ▼              ▼
   knowledge.py    agent.py       export.py      ingest.py
   conceitos,      loop de        compilação     link/PDF/
   arestas,        ferramentas    do doc + PDF   YouTube/texto
   ancoragem       (rota A)
        │              │               │
        └──────────────┴───────┬───────┘
                               ▼
                    llm.py   (a única porta para modelo)
                    rota B: qualquer OpenAI-compatível
                    embeddings
                               │
                       ┌───────┴────────┐
                       ▼                ▼
                  API (DeepSeek,   Local (LM Studio
                  OpenRouter...)   :1234, llama.cpp :8080)
```

Regra de ouro: **`llm.py` é a única porta para modelo.** Nenhum outro módulo fala
com provedor. Trocar de modelo é mudar configuração, nunca código.

Estrutura de arquivos alvo:

```
caderno/
  config.py      ← existe; ganha a config de backends
  llm.py         ← NOVO  rota B + embeddings (OpenAI-compat universal)
  agent.py       ← NOVO  loop de ferramentas próprio (rota A)
  tools.py       ← NOVO  as ferramentas fixas
  knowledge.py   ← NOVO  extração, nó canônico, arestas, ancoragem
  export.py      ← NOVO  compilação do documento, PDF, Anki, Obsidian
  db.py          ← existe; ganha concepts, mentions, edges, notes, messages
  ingest.py      ← existe
  prompts.py     ← existe
  app.py         ← existe; ganha as rotas novas
  static/
    app.css      ← existe
    graph.js     ← NOVO  force-directed em canvas, sem dependência
```

---

## 4. Roteamento de modelo

```
tarefa                             rota   por quê
chat dentro do caderno             A      precisa ler as fontes
chat global                        B      sem ferramenta, por definição
extrair conceitos de uma fonte     B      pequeno e estruturado
resumir fonte para o índice        B      idem
compilar o documento / PDF         B      síntese sobre texto já reunido
título e descrição do caderno      B      trivial
arestas por similaridade           C      modelo de embedding (local serve)
```

Configuração (uma linha por uso):

```
LLM_AGENT = hermes:http://127.0.0.1:8642            # opcional
LLM_CHAT  = openai:https://api.deepseek.com/v1|deepseek-chat
LLM_FAST  = openai:http://127.0.0.1:1234/v1|qwen2.5-7b-instruct
LLM_EMBED = openai:http://127.0.0.1:1234/v1|nomic-embed-text
```

O padrão a respeitar: **tarefa barata e estruturada vai para local; síntese com
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
Isso não é só economia de prompt: é o que torna o app seguro de colocar na VPS.

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
messages(id, notebook_id, role, body, created_at, tool_note, meta)
  → histórico próprio. Substitui as sessões do Hermes (e a armadilha
    das sessões órfãs desaparece junto)

concepts(id, name, canonical, aliases, kind, created_at, updated_at)
  → canonical = forma normalizada p/ deduplicar; aliases = "ADI" ↔ nome completo

mentions(id, concept_id, notebook_id, source_id, output_id, message_id,
         excerpt, created_at)
  → É o mecanismo da ancoragem: cada menção guarda o TRECHO de origem

edges(id, a_id, b_id, kind, weight, provenance, created_at)
  → kind: co_occurrence | explicit | similarity
  → UNIQUE(a_id, b_id, kind)

notes(id, concept_id, notebook_id, body, created_at)
  → nota do usuário presa a um conceito (o "estilo Obsidian" de verdade)

index_cache(notebook_id, summary, concepts_blob, built_at)
  → alimenta o chat global sem recarregar tudo
```

Índices obrigatórios: `mentions(concept_id)`, `edges(a_id)`, `edges(b_id)`,
`concepts(canonical)`.

---

## 7. Roadmap

Cada fase é utilizável sozinha. Nada de fase que só serve se a próxima existir.

### F1 — Alicerce (motor próprio)  ← PRÓXIMA
- [ ] `llm.py`: rota B (OpenAI-compatível) com streaming
- [ ] `llm.py`: embeddings
- [ ] tabela `messages` + migrar o chat para histórico próprio
- [ ] `agent.py`: loop de ferramentas com limite de passos e timeout
- [ ] `tools.py`: as 5 ferramentas fixas
- [ ] *Além do OpenAI nativo*: reparo de tool call emitida como texto
- [ ] backend Hermes como opcional (mantém o que já funciona hoje)
- [ ] config dos backends + roteamento por tarefa
- [ ] **Critério de pronto:** o chat do caderno funciona sem Hermes instalado

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

---

## 9. Riscos conhecidos

| risco | mitigação |
|---|---|
| Tool call de modelo local vem quebrada ou como texto | camada de reparo + tarefas estruturadas sempre na rota B |
| Extração de conceito vira ruído | nó canônico + aliases + edição pelo usuário + limiar de aresta |
| Grafo vira bola de pelo (~200 nós) | filtros por caderno, peso e recência desde o primeiro dia |
| Custo da extração automática | tarefa pequena, modelo local, cache por hash da fonte |
| Escopo de 6 fases / semanas | cada fase entrega valor sozinha; nada de fase-ponte |
| Depender do Hermes de novo por conveniência | o Hermes é OPCIONAL: se o app não roda sem ele, é bug |
| Conversa longa estoura contexto | compactação própria na rota A (F1) |

---

## 10. Como verificamos

Regra canônica, sem exceção:

```
uv run ruff check .
uv run pytest
```

- Todo teste que tocaria LLM usa **backend falso**: sem rede, sem chave, sem
  custo. É o que já permite 48 testes rodarem em 0,2s.
- Funcionalidade de UI se verifica **renderizando e olhando**, não por suposição.
- Toda decisão de arquitetura ganha entrada na seção 2 **antes** do código.
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
- motor atual: Hermes via API server — é exatamente o que a D004 substitui
- serviços: `caderno.service` (app, 8765) e `hermes-gateway.service` (motor, 8642)

Primeiro trabalho daqui: **F1**. A D004 é a decisão que define o resto do
projeto, então é ela que entra em execução primeiro.
