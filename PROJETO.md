# Frutiger LM — projeto

Documento-vivo de arquitetura. Toda decisão estrutural entra aqui com status.
Este arquivo é a fonte da verdade: se o código divergir dele, um dos dois está
errado e precisa ser corrigido.

Última atualização: 2026-09-25

---

## 1. Posicionamento

O NotebookLM é um **consumidor de fontes**: você joga material, conversa, gera um
output e aquilo morre ali.

O Frutiger LM é um **construtor de conhecimento que persiste e se liga**: o que
você estuda vira conceito ancorado, os conceitos se conectam entre cadernos, e o
conjunto fica navegável e verificável.

Essa frase é o filtro de todas as decisões. Se uma funcionalidade não empurra o
app para "construtor de conhecimento", ela provavelmente não é para aqui.

Três consequências práticas:

1. **Só texto.** Sem imagem, sem áudio. Foco em estrutura de estudo.
2. **Ancoragem é obrigatória.** Nada de afirmação sem rastro até a fonte.
3. **O cliente traz a própria chave.** Clonar, instalar, colar a API key, usar.
   Modelo local não precisa nem de chave.

O nome "Frutiger" se refere à linhagem estética que inspira a interface (Frutiger
Aero). Não há afiliação com o Nous Research nem com a Monotype — ver D029.

---

## 2. Registo de decisões

Status: `DECIDIDO` · `PROPOSTO` (falta seu OK) · `ABERTO` (a discutir) ·
`REVERTIDO`

| # | Decisão | Status |
|---|---------|--------|
| D001 | App web local-first: FastAPI + SQLite + UI vanilla sem build | DECIDIDO |
| D002 | Fonte = arquivo em disco + linha no SQLite; output = markdown versionado | DECIDIDO |
| D003 | Motor atrás de uma interface, dividido em duas rotas (agente / conversa) | **REVERTIDO** |
| D004 | O motor do agente é NOSSO; o Hermes vira backend opcional | **REVERTIDO** |
| D005 | O nó do grafo é **conceito**, não caderno nem fonte | DECIDIDO |
| D006 | Todo nó é **ancorado**: aponta para o trecho exato que o originou | DECIDIDO |
| D007 | Extração automática ao ingerir fonte e ao gerar output; botão manual na resposta do chat | DECIDIDO |
| D008 | O chat global não usa ferramenta | **REVERTIDO** |
| D009 | Nó canônico com aliases + edição pelo usuário (mesclar/renomear/apagar) | DECIDIDO |
| D010 | Modelo local (LM Studio / llama.cpp) suportado de primeira classe | DECIDIDO |
| D011 | **Nenhuma ferramenta de terminal.** O app nunca expõe shell | DECIDIDO |
| D012 | Nome do produto: Frutiger LM | DECIDIDO |
| D013 | Estética: Frutiger Aero | DECIDIDO |
| D014 | Export PDF via CSS de impressão + `window.print()` | PROPOSTO |
| D015 | Fase 1 (alicerce) antes de funcionalidade visível | DECIDIDO |
| D016 | Régua de verificação: `uv run ruff check .` + `uv run pytest` | DECIDIDO |
| D017 | Motor = LangGraph, via `langchain.agents.create_agent`. Hermes sai de vez | DECIDIDO |
| D018 | Só o pacote `engine/` importa LangChain. O resto do app não conhece a lib | DECIDIDO |
| D019 | Persistência de conversa pelo `checkpointer` (AsyncSqliteSaver) | DECIDIDO |
| D020 | Um único cliente de modelo OpenAI-compatível cobre API e local | DECIDIDO |
| D021 | Extração de conceito por `response_format` (structured output) | DECIDIDO |
| D022 | Versões do stack LangChain **pinadas** | DECIDIDO |
| D023 | **Arquitetura unificada: UM agente principal com catálogo de ferramentas.** Sem divisão em rotas | DECIDIDO |
| D024 | Cada capacidade tem UMA implementação e DOIS pontos de entrada: botão na UI e ferramenta do agente | DECIDIDO |
| D025 | O catálogo pode crescer, mas o conjunto **exposto por turno** é curado | DECIDIDO |
| D026 | Rename completo executado: pacote, env vars, unit, banco | DECIDIDO |
| D027 | O grafo é populado por ferramentas do agente **e** por edição manual na UI | DECIDIDO |
| D028 | Ferramenta do agente que produz documento roda como **subgrafo**, não como chamada aninhada | **REVISTA pela D059** |
| D029 | Nome "Frutiger": verificar conflito de marca antes de publicar | ABERTO |
| D030 | A chave da API mora em `<data_dir>/model.json` (0600) e **nunca** volta ao navegador | DECIDIDO |
| D031 | Config de modelo vem da UI; `.env` (`LLM_AGENT`) é o fallback de quem prefere versionar | DECIDIDO |
| D032 | Config de modelo incompleta é **recusada** com o que falta nomeado — validar antes de gravar | DECIDIDO |
| D033 | O checkpointer vive em `checkpoints.db`, arquivo **próprio**, não no banco do app | DECIDIDO |
| D034 | Ferramenta é **presa ao caderno** na construção; o `notebook_id` não é parâmetro | DECIDIDO |
| D035 | Ferramenta que lê arquivo **limita a própria saída** e diz onde parou | DECIDIDO |
| D036 | Provedor de `web_search` do agente | ADIADO |
| D037 | Apagar caderno/fonte apaga os arquivos: a invariante mora no `db`, não na rota | DECIDIDO |
| D038 | A tradução LangGraph → eventos da interface mora em `engine/agent.py`; a UI não sabe o que é LangGraph | DECIDIDO |
| D039 | Chat global e chat do caderno usam **as mesmas ferramentas**; o que muda é o `Escopo`. Não há ferramenta de "busca entre cadernos" | DECIDIDO |
| D040 | O índice dos cadernos é calculado **ao vivo**, sem cache — e sem resumo gerado por modelo | DECIDIDO |
| D041 | Conceito canônico por chave normalizada; o extrator recebe o vocabulário existente e reusa o nome | DECIDIDO |
| D042 | Extração é ação **explícita** (botão/ferramenta), não efeito de adicionar fonte | DECIDIDO |
| D043 | Aresta de co-ocorrência sai do bloco; aresta explícita **exige trecho** | DECIDIDO |
| D044 | Extração é lote, não subgrafo do LangGraph (`graphs/` fica para o F5) | DECIDIDO |
| D045 | As ferramentas de grafo são **globais**, sem escopo: o grafo é a camada que liga | DECIDIDO |
| D046 | Saída estruturada por `json_mode`, com o formato **no prompt, gerado do Pydantic** | DECIDIDO |
| D047 | ~~O peso mínimo padrão do desenho é **2**~~ **SUPERSEDIDA pela D056** | REVERTIDA |
| D048 | O painel de estudo são **abas** na coluna que já existe ("Gerar" \| "Estudar") | DECIDIDO |
| D049 | SRS é um SM-2 **simplificado**; as lacunas são **fatos do grafo**, nunca opinião de modelo | DECIDIDO |
| D050 | Contradição é comparação sobre o **mesmo conceito**, e exige **os dois trechos** | DECIDIDO |
| D051 | A citação `[n]` na resposta é o **registro de uso** da fonte | DECIDIDO |
| D052 | Na home, grafo e chat moram numa **barra lateral à direita**, em abas | DECIDIDO |
| D053 | O grafo se forma por **gravidade + repulsão**; a vista é que **encaixa** no quadro | DECIDIDO |
| D054 | O desenho mostra só os conceitos **do material** (2+ menções, ou ponte); o dado fica | DECIDIDO |
| D055 | O repouso é o **mapa**: nó = caderno, aresta = conceito em comum; clicar no nó entra | DECIDIDO |
| D056 | O desenho mostra **todas** as conexões (peso 1); o corte que sobra é de **nó** | DECIDIDO |
| D057 | O nó é uma **bolha de vidro azul-clara** (Frutiger Aero); a cor por caderno saiu | DECIDIDO |
| D058 | `[hidden]` é regra **global** no CSS; clique só se prova por `elementFromPoint` | DECIDIDO |
| D059 | O artefato é um **run com id**, fora do turno — e o LangGraph não entra nisso (revê o mecanismo do D028) | DECIDIDO |
| D060 | **UMA** ferramenta de artefato: a que existe (`compilar_documento`), e não um `gerar_documento(template)` | DECIDIDO |

### D003 e D008 — REVERTIDAS (mantidas para registro)

**D003** dizia para dividir o motor em duas rotas: uma agente (com ferramentas) e
uma de conversa pura (barata, sem ferramentas). O raciocínio era econômico:
o Hermes cobrava ~15-20 mil tokens de system prompt por turno, então tudo que
pudesse evitar o agente valia.

**D008** era consequência: o chat global ficaria sem ferramentas por ser caro.

Com D017, o motivo econômico desapareceu — o prompt de sistema passa a ser nosso e
o catálogo de ferramentas é pequeno. E a D008 tinha um custo que eu já havia
apontado: sem ferramenta, o chat global vira "bibliotecário que não pode abrir os
livros". Com ferramenta de leitura ele responde de verdade.

### D023 — arquitetura unificada (a decisão desta rodada)

Um agente principal, um catálogo de ferramentas, um caminho de execução. Razões:

1. **O motivo da divisão evaporou.** Sem o prompt gigante do Hermes, o custo
   marginal de dar ferramentas a qualquer conversa é pequeno.
2. **Previsibilidade.** Um caminho só é mais fácil de depurar, testar e explicar
   do que dois com regras de quando usar qual.
3. **O produto é conversa com ferramentas.** Perguntar "o que eu já estudei sobre
   X" precisa alcançar os cadernos, não só um resumo deles.

Custo aceito: tarefa boba (gerar um título) passa a poder custar um passo de
agente. Mitigação: o agente pode resolver sem chamar ferramenta nenhuma — o loop
só gasta mais quando a tarefa realmente precisa.

### D024 — uma implementação, dois pontos de entrada

Regra que evita o pior tipo de duplicação: gerar um "plano de aprendizado" pelo
botão do painel direito **e** pedindo no chat tem de ser o mesmo código, não duas
implementações que divergem com o tempo.

```
                         ┌──────────────────────┐
   botão na UI ─────────▶│  gerar_plano(...)    │◀───────── ferramenta do
                         │  uma implementação   │           agente (chat)
                         └──────────────────────┘
```

### D025 — catálogo grande, exposição curada

Ferramenta demais degrada a escolha do modelo. Se o catálogo chegar a 25
ferramentas sempre visíveis, o agente começa a errar a escolha. Então:

- o **catálogo** pode crescer à vontade;
- o **conjunto exposto em cada turno** é curado (por contexto: no caderno expõe
  leitura + grafo; na home expõe busca entre cadernos + grafo global);
- implementação via `middleware` do `create_agent`.

### D028 — artefato é subgrafo, não chamada aninhada

Uma ferramenta que gera um documento longo **não pode** chamar o modelo dentro dela
e devolver o texto ao agente: dá chamada aninhada, sem streaming para o usuário,
risco de timeout, e o agente ainda reformata o resultado por cima.

O certo: a ferramenta **dispara o subgrafo** do artefato e devolve um
identificador; o painel direito acompanha aquele subgrafo e mostra o documento
sendo escrito. Assim o botão e o chat compartilham a mesma implementação (D024) sem
pagar o preço da aninhagem.

> **O mecanismo desta decisão foi revisto na D059.** O princípio — a ferramenta não
> aninha a chamada de modelo — é o que ficou de pé, e é o que importa. O *subgrafo do
> LangGraph* foi trocado por um **run da oficina**: a razão está medida lá, e é a mesma
> conta que a D044 já tinha feito para a extração.

### D030 — onde a chave da API mora

```
<data_dir>/model.json     modo 0600, escrita atômica
```

Três regras que valem para sempre:

1. **A chave nunca sai inteira daqui.** O navegador recebe `has_key` e uma dica
   mascarada (`sk-f••••••7890`). Há teste de rota que falha se a chave aparecer no
   corpo HTTP.
2. **Campo de chave vazio significa "não mexi".** O formulário devolve o campo em
   branco de propósito; tratá-lo como valor novo apagaria a chave de quem só quis
   trocar o modelo. Há teste para isso.
3. **`data/` contém segredo e não se compartilha.** O arquivo fica no diretório de
   dados para preservar "um diretório = uma instância", que é o que permite rodar
   várias na VPS. É o preço consciente dessa escolha — documentado no README.

Ficou no diretório de dados, e não em `~/.config`, exatamente por causa da
propriedade de instância. Se um dia virar multiusuário de verdade, a chave sai
daqui para um cofre por usuário.

### D031 — ordem de precedência da config de modelo

```
UI (data/model.json)  →  .env (LLM_AGENT)  →  vazio
```

A UI ganha porque foi o caminho que a pessoa usou por último de forma explícita.
O `.env` existe para quem prefere versionar a configuração em vez de clicar — e
cobre o caso de VPS, onde você quer a config no ambiente.

Formato do `.env`: `LLM_AGENT=openai|<base_url>|<modelo>|<chave>`. O prefixo
`openai` está lá para deixar espaço a outros protocolos sem quebrar o formato
depois (D020).

### D032 — config incompleta é recusada, não engolida

Esta nasceu de um uso real, não de teoria. O caminho natural do formulário era:
abrir o modal, colar a chave, clicar em Salvar. Endereço e modelo ficavam em
branco, o app dizia **"salvo"**, e a configuração resultante não funcionava.

Três correções, e a terceira é a que importa:

1. A rota **valida antes de gravar** (`montar` → `faltando` → `save`), então uma
   tentativa inválida não deixa estado meio-configurado no disco — e não
   sobrescreve uma configuração boa que já existia.
2. O erro **nomeia o que falta** ("Falta endereço, modelo"), em vez de só dizer
   que está incompleto.
3. A tela **guia em vez de só recusar**: com chave salva e sem provedor, o texto
   de abertura diz exatamente isso — antes de a pessoa errar, não depois.

A lição geral, que vale para o resto do projeto: **um formulário que aceita um
estado inutilizável em silêncio é pior do que um que recusa.** O usuário perde
tempo procurando o problema num lugar onde ele não está.

### D033 — o checkpointer tem arquivo próprio

```
data/frutiger_lm.db     ← nossas tabelas (cadernos, fontes, outputs, conceitos)
data/checkpoints.db     ← o estado das conversas, schema do LangGraph
```

Dois motivos, e o primeiro é o que importa:

1. **O schema é da biblioteca.** Misturar significaria uma migração do LangGraph
   mexer nas nossas tabelas — e a D022 já reconheceu que essa lib tem churn.
   Contenção é o mesmo princípio da D018, aplicado ao disco.
2. **Lock.** O app usa `sqlite3` e o checkpointer usa `aiosqlite`. Em arquivos
   separados, uma escrita do agente nunca concorre com uma escrita do app.

O preço é um arquivo a mais para fazer backup. Aceito: são dois arquivos por
instalação, e a separação é o que impede um problema de virar o outro.

### D034 — a ferramenta é presa ao caderno

```python
ferramentas = ferramentas_de_leitura(notebook_id)   # o id entra AQUI
```

O `notebook_id` **não** é parâmetro de nenhuma ferramenta. Três razões, e a
segunda é a que justifica a decisão:

1. O modelo não tem como errar o id.
2. O modelo **não consegue** ler as fontes de outro caderno. É isolamento
   estrutural, não confiança no comportamento do modelo — e há teste dos dois
   lados: na chamada direta e dentro do laço do agente.
3. O schema fica menor. Schema menor melhora a escolha de ferramenta (D025).

Detalhe relacionado: quando o id pertence a outro caderno, a ferramenta responde
"não existe fonte com esse id" em vez de "existe, mas é de outro caderno". Para
quem pergunta, é como se não existisse — e isso evita que a ferramenta vire
oráculo de ids alheios.

### D035 — ferramenta que lê arquivo limita a saída

Uma ferramenta que pode despejar 400 mil caracteres no contexto quebra o turno, e
o modelo não tem como prever isso. Então:

- `ler_fonte` corta em pedaços (padrão 8k, teto 20k) e o cabeçalho diz o total e a
  **próxima posição** — continuar virou decisão do modelo, não acidente;
- `buscar_nas_fontes` para em 25 ocorrências e avisa que truncou;
- a saída inclui sempre o id e o título da fonte, para a resposta poder citar.

É a mesma disciplina de saída limitada que vai valer para toda ferramenta futura:
o agente decide o que trazer, nunca recebe um balde.

### D036 — `web_search` fica adiada, e a razão importa

Não é esquecimento. O `web_extract` já cobre o caso real — "a pessoa me deu um
link" — e busca na web sem provedor escolhido significa escolher um dos três
caminhos ruins:

- **SearxNG próprio**: sem chave e sem custo, mas é mais um serviço para rodar e
  manter na VPS;
- **API paga** (Tavily, Brave, Serper): funciona bem, mas é uma chave a mais que o
  usuário final precisa configurar;
- **DuckDuckGo raspado**: grátis e sem chave, mas quebra quando eles mudam algo, e
  é contra os termos deles.

Nenhuma das três se paga hoje, porque não há caso de uso pedindo. Quando houver, o
enquadramento já está pronto: a ferramenta só é **exposta se estiver configurada**
(D025) — ninguém é obrigado a ter chave de busca para usar o Frutiger LM.

Adiar é diferente de não decidir: a decisão é *não construir agora*, com o critério
de quando construir escrito.

### D037 — apagar é uma operação só

`db.delete_notebook` apaga as linhas **e a pasta**; `db.delete_source` apaga a
linha **e o arquivo**. A remoção de arquivo estava na rota (`shutil.rmtree` dentro
do handler HTTP), e o resultado é o de sempre quando uma operação fica partida
entre camadas: **algum chamador vaza**. Aconteceu de verdade — um teste com modelo
real apagou o caderno pelo `db`, e a pasta ficou no disco.

O `unlink` tem uma guarda: só apaga se o caminho estiver dentro do diretório de
dados. `path` vem do banco, e sem a guarda um registro corrompido viraria remoção
em qualquer lugar do disco.

A regra geral, que vale além deste caso: **se a operação tem um nome, ela tem um
dono.** "Apagar caderno" é uma coisa, e não duas metades em dois arquivos.

### D038 — a interface não sabe o que é LangGraph

Trocar o motor não mexeu **em uma linha de UI**. O `notebook.js` continua
consumindo `run.started`, `assistant.delta`, `tool.started`, `assistant.completed`,
`error` e `done` — os mesmos eventos de antes. Quem traduz é `agent.eventos()`,
e é o único lugar que conhece `astream_events`, `on_chat_model_stream` e
`on_tool_start`.

Os nomes de evento do LangGraph foram **descobertos rodando** (`astream_events(v2)`
com o modelo falso), não deduzidos da documentação. Vale registrar o método: uma
sonda que imprime o evento, as chaves do `data` e o tipo do chunk custa um minuto e
elimina o ciclo de "escreve, roda, adivinha por que não apareceu na tela".

Dois detalhes que a tradução precisa acertar, e os dois têm teste:

1. **Chunk de conteúdo vazio é tool call, não texto.** Sem filtrar, o front recebe
   delta vazio. É o chunk que carrega `tool_call_chunks`.
2. **O agente faz duas chamadas ao modelo** (a do tool call e a final), então o
   texto chega em dois pedaços. Na prova com modelo real isso apareceu como texto
   colado ao vivo (`"...na fonte.**ZULU-90210**"`) e como duas bolhas ao recarregar
   — a tela mudava conforme o momento. Agora o stream emenda com linha em branco e
   o histórico junta numa bolha só, e há teste afirmando que os dois textos são
   **idênticos**.

### D039 — a diferença entre os dois chats é o escopo, não as ferramentas

O F2 previa um `engine/tools/cadernos.py` com um `buscar_cadernos`. Não foi feito,
e não deve ser: `listar_fontes` no escopo global **já é** o mapa de todos os
cadernos, e `buscar_nas_fontes` já procura em todos.

Uma ferramenta a mais com o mesmo trabalho seria pior por dois motivos:

- o modelo passaria a ter duas listagens parecidas para escolher, e às vezes
  escolheria a errada (D025);
- a checagem de acesso ficaria duplicada — e é justamente ela que garante o
  isolamento da D034.

Então a diferença entre os dois chats virou **um tipo**:

```python
Escopo.do_caderno(notebook_id)   # o chat do caderno
Escopo.todos()                   # o chat global
```

`escopo.permite(fonte)` é a única checagem, num lugar só. Testado dos dois lados: o
chat de um caderno continua sem alcançar as fontes de outro, e o global alcança
todas — nomeando de qual caderno veio. Sem isso, o F2 teria enfraquecido uma
garantia que o F1 tinha conquistado.

### D040 — o índice é calculado ao vivo

O F2 previa um `index_cache` com resumo gerado por modelo, invalidado quando o
caderno muda. Não foi feito, de propósito.

O índice é uma consulta e uma formatação de texto. Um cache traria invalidação,
incoerência possível e um estado a mais para depurar, e o custo ao vivo é
desprezível.

O resumo **gerado** por caderno é outra história: custa uma chamada de modelo por
caderno e precisa de invalidação. Ele só se paga se a lista de títulos não bastar
para o modelo decidir onde procurar. Enquanto bastar, não entra.

E note o que a prova real mostrou: com só o índice ao vivo, o agente decidiu
sozinho procurar nos dois cadernos e leu as quatro fontes. O que existia bastou —
que é a única evidência que interessa para não construir o cache.

---

## 3. Arquitetura em camadas

```
┌──────────────────────────────────────────────────────────┐
│ static/  UI vanilla (sem build)                          │
│   index / notebook / graph.js (canvas) / md.js           │
└────────────────────────┬─────────────────────────────────┘
                         │ JSON + SSE
┌────────────────────────┴─────────────────────────────────┐
│ app.py   rotas FastAPI                                    │
└────────────────────────┬─────────────────────────────────┘
   ┌──────────┬──────────┴─────────┬──────────────┐
   ▼          ▼                    ▼              ▼
knowledge.py export.py          ingest.py      engine/  ◄── FRONTEIRA
conceitos,   compilação         link/PDF/      (único que
arestas,     do doc + PDF       YouTube/texto  importa
ancoragem                                       LangChain)
   │          │                    │              │
   └──────────┴──────────┬─────────┴──────────────┘
                         ▼
                    db.py  (SQLite)
                    + checkpointer do LangGraph
                    + subgrafos de artefato
                         │
                         ▼
              modelo: API (chave do cliente)
                      ou local (LM Studio / llama.cpp)
```

Dentro de `engine/`:

```
engine/                                       (✅ = pronto, ⬜ = a fazer)
  llm.py           ✅ fábrica de modelo (UI ou .env, OpenAI-compatível)
  agent.py         ✅ o agente: create_agent + catálogo curado + checkpointer
                     (montar() para um caderno, montar_global() para todos)
  checkpoint.py    ✅ AsyncSqliteSaver em arquivo próprio (D033)
  fake.py          ✅ modelo falso para teste, sem rede
  extracao.py      ⬜ conceitos a partir de um texto, via response_format (F3/D021)
  tools/
    leitura.py      ✅ listar_fontes, ler_fonte, buscar_nas_fontes — presas a um Escopo
    web.py          ✅ web_extract  ·  ⬜ web_search (espera a D036)
    grafo.py        ⬜ buscar no grafo, vizinhança, registrar relação (F3/D027)
    artefatos.py    ⬜ gerar_plano, gerar_faq, compilar_pdf → disparam subgrafos (F5)
  graphs/
    artefato.py     ⬜ o subgrafo que produz um documento (D028, F5)
```

Fora de `engine/`, junto do `db.py` (não fala com modelo, então não é do `engine` —
D018):

```
knowledge.py       ⬜ a loja do grafo: a ÚNICA porta de leitura e escrita (F3/D024)
```

`tools/cadernos.py` **não existe e não deve existir** (D039): o chat global usa as
mesmas ferramentas de leitura com outro escopo.

Regra de ouro: **`engine/` é a única porta para modelo.** Trocar de provedor é
mudar configuração, nunca código.

---

## 4. O agente e suas ferramentas

Um agente, três famílias de ferramenta. O que existe hoje e o que vem:

**Leitura** — o agente precisa alcançar as fontes
| ferramenta | o que faz |
|---|---|
| `list_sources` | o que existe neste caderno, com id e tamanho |
| `read_source` | lê um trecho de uma fonte (offset/limit) |
| `search_sources` | busca textual nas fontes |

**Contextualização / grafo** — o coração do diferencial (D005, D027)
| ferramenta | o que faz |
|---|---|
| `mapear_conhecimento` | extrai conceitos de um texto e ancora cada um numa citação |
| `criar_conceito` | cria nó explícito, por decisão do usuário ou do agente |
| `ligar_conceitos` | cria aresta com rótulo ("é instrumento de", "contradiz") |
| `mesclar_conceitos` | resolve duplicata ("ADI" ↔ nome completo) |
| `vizinhanca` | o que se liga a este conceito, e onde apareceu |

**Gerais / produção** — os artefatos (D024, D028)
| ferramenta | o que faz |
|---|---|
| `gerar_documento` | dispara o subgrafo de um template (plano, FAQ, guia...) |
| `compilar_pdf` | dispara o subgrafo de compilação do caderno |
| `buscar_cadernos` | o que existe entre todos os cadernos (chat global) |

**Nenhuma ferramenta de terminal** (D011). O agente lê arquivos e a web, e nada
além. Não é só economia de prompt: é o que torna o app seguro de colocar na VPS.

---

## 5. Modelo

Um modelo configurável para o agente, mais um de embedding para o grafo. A
config vem da **UI** (botão "Modelo" na tela inicial) e cai no `.env` como
fallback (D030, D031):

```
LLM_AGENT = openai|https://api.deepseek.com/v1|deepseek-chat|<key>
LLM_AGENT = openai|http://127.0.0.1:1234/v1|qwen2.5-7b-instruct|     # local
LLM_EMBED = openai|http://127.0.0.1:1234/v1|nomic-embed-text|
```

A mesma classe (`ChatOpenAI`) cobre OpenAI, DeepSeek, OpenRouter, Groq, vLLM,
LM Studio (`:1234/v1`), llama.cpp (`:8080/v1`) e Ollama (via `/v1`). Modelo local
não precisa de chave — e a UI sabe disso: endereço local não exige o campo.

A tela tem **botão de testar conexão**, porque "salvei" e "funciona" são coisas
diferentes. As falhas comuns viram dica acionável em vez de mensagem crua do
provedor (esqueceu o LM Studio ligado → a mensagem diz isso e aponta a porta).

Embeddings são **infraestrutura**, não agente: servem às arestas por similaridade
(F6) e não passam pelo agente.

---

## 6. Modelo de dados

Já existe (como está no código; esta seção chegou a citar `url` e `file_path`, que
não existem — a seção foi corrigida para bater com o `SCHEMA`):

```
notebooks(id, title, description, created_at, updated_at)
sources(id, notebook_id, title, kind, origin, path, chars, active, status, error, created_at)
outputs(id, notebook_id, template, title, content_md, created_at)
```

Novo:

```
concepts(id, name, canonical, aliases, kind, created_at, updated_at)
mentions(id, concept_id, notebook_id, source_id, output_id, thread_id,
         message_id, excerpt, created_at)
  → É o mecanismo da ancoragem: cada menção guarda o TRECHO de origem
edges(id, a_id, b_id, kind, weight, provenance, created_at)
  → kind: co_occurrence | explicit | similarity · UNIQUE(a_id, b_id, kind)
notes(id, concept_id, notebook_id, body, created_at)
index_cache(notebook_id, summary, concepts_blob, built_at)
```

Não criamos tabela de mensagens: o `checkpointer` do LangGraph cuida disso (D019),
em **arquivo próprio** (`data/checkpoints.db`, D033). As tabelas dele não
convivem com as nossas.

Índices obrigatórios: `mentions(concept_id)`, `edges(a_id)`, `edges(b_id)`,
`concepts(canonical)`.

---

## 7. Roadmap

Cada fase é utilizável sozinha. Nada de fase que só serve se a próxima existir.

### F1 — Alicerce (motor LangGraph)  ← CONCLUÍDA
- [x] rename completo para Frutiger LM (pacote, env, unit, banco) — D026
- [x] dependências pinadas: `langchain==1.4.2`, `langgraph==1.2.12`,
      `langchain-openai==1.6.6`, `langgraph-checkpoint-sqlite==3.1.1` (D022)
- [x] `model_store.py`: onde a chave mora, 0600, nunca devolve o valor (D030, D031)
- [x] `engine/llm.py`: fábrica de modelo a partir da UI ou do `.env` (D020)
- [x] `engine/fake.py`: modelo falso para teste sem rede
- [x] rotas e UI de configuração de modelo (botão "Modelo" na tela inicial)
- [x] `engine/checkpoint.py`: `AsyncSqliteSaver` em arquivo próprio, 1 caderno =
      1 `thread_id`, ligado no lifespan do app (D019, D033)
- [x] `engine/tools/leitura.py`: `listar_fontes`, `ler_fonte`, `buscar_nas_fontes`
      presas ao caderno (D034) e com saída limitada (D035)
- [x] `engine/tools/web.py`: `web_extract` (reusa o `ingest`) — o `web_search`
      fica para quando houver provedor (D036)
- [x] `engine/agent.py`: `create_agent` com `system_prompt` nosso e catálogo curado
      (D018, D023, D025)
- [x] prompt e contexto falando a língua do motor: `BASE_RULES` e
      `db.build_context` mencionavam `read_file`/`search_files`/`grep` e entregavam
      **caminho de arquivo**; agora citam as ferramentas do motor e entregam **id**
- [x] rotas de chat do app passando por `engine/` em vez do Hermes — `agent.eventos()`
      traduz LangGraph → os eventos que a UI já consumia (D038)
- [x] `hermes.py` **apagado**, com os testes dele, as variáveis `HERMES_*` da config,
      o handler de erro da rota e a coluna `hermes_session_id` (com migração)
- [x] **Critério de pronto:** o chat funciona **sem Hermes instalado** — provado com
      modelo real, pelo serviço, com a interface inalterada

### F2 — Home: chat global  ← CONCLUÍDA
- [x] escopo nas ferramentas: `Escopo.do_caderno(id)` / `Escopo.todos()` (D039) —
      nenhuma ferramenta nova
- [x] `listar_fontes` no escopo global vira o mapa de todos os cadernos
- [x] `ler_fonte` e `buscar_nas_fontes` alcançam qualquer caderno, **dizendo de
      qual caderno veio**; o escopo do caderno segue isolado (D034)
- [x] índice global no prompt com a **mesma numeração** da ferramenta, e estável
      por ordem de criação (não por `updated_at`)
- [x] `agent.montar_global()` + thread próprio (`global`) + `/api/global/*`
- [x] dock na home que expande, em Frutiger Aero, reusando `C.conversa`
- [x] **Critério de pronto:** pergunta respondida com material de **dois** cadernos,
      com a relação explícita e a origem de cada parte — provado com modelo real
- [ ] busca global por FTS5 (para a pessoa procurar, não para o agente — pequena,
      fica para quando pedir)
- [ ] `web_search` segue adiada (D036)

**Fora do F2, por decisão:**

- `index_cache` com resumo gerado por caderno: **não fazer agora** (D040).
- "virar conhecimento" numa conclusão da conversa: vai para o **F3** — precisa de
  conceito para existir, e conceito é do F3.
- `engine/tools/cadernos.py`: **não existe**, e não deve existir (D039).

### F3 — Grafo de conhecimento  ← CONCLUÍDA (um item pendente)
- [x] `knowledge.py`: a loja do grafo (normalizar, achar-ou-criar, mencionar, ligar,
      mesclar, vizinhança)
- [x] `extracao.py`: extração de conceitos (D021), com validação do trecho
- [x] nó canônico por chave normalizada + vocabulário existente entregue ao extrator
      (D041), **relido a cada bloco**
- [x] arestas de co-ocorrência (de graça) e explícitas, estas exigindo trecho (D043)
- [x] `engine/tools/grafo.py`: as ferramentas de grafo (D027, D045)
- [x] `graph.js`: force-directed em canvas, sem biblioteca + filtros
- [x] painel do grafo na home, com legenda que explica o desenho
- [x] tela do conceito: menções, trecho de origem, cadernos onde aparece
- [x] edição na UI: mesclar, renomear, apagar (mesma implementação das tools — D024)
- [ ] "virar conhecimento" numa conclusão do chat — **pendente**: a tabela `mentions`
      já aceita `thread_id`/`message_id`, mas o botão não foi feito. É o único item
      que ficou de fora, e é o menos importante dos dez.
- [x] **Critério de pronto:** 102 conceitos extraídos do caderno real, com 156
      menções ancoradas em trecho; painel do conceito com os trechos; 0 conceito sem
      âncora

---

## 7.1 Plano do F3 — o grafo ancorado

### O que a fase entrega

Um grafo de conceitos que **sobrevive à conversa**. É a tese do produto: o
NotebookLM é um consumidor de fontes (joga material, conversa, gera documento,
morre); o Frutiger LM quer ser um construtor de conhecimento que **persiste e se
liga**. O grafo é o que materializa essa diferença.

### A regra que faz o grafo valer

Um grafo bonito não presta. O que faz ele valer é a **ancoragem**: toda menção
guarda o trecho, o caderno e a fonte de onde saiu.

Daí a regra mais importante desta fase:

> **A menção só é gravada se o trecho existir, de fato, no texto da fonte.**

O extrator devolve o trecho verbatim e nós conferimos contra o material. Trecho que
não casa é descartado — e contado, para não escondermos a taxa de descarte. Sem
essa checagem, o grafo viraria um desenho plausível de coisas que ninguém disse, que
é o modo mais fácil de um projeto desses fracassar em silêncio.

### As peças, na ordem

1. **`db.py`** — as quatro tabelas da seção 6 (`concepts`, `mentions`, `edges`,
   `notes`), com `_migrar()` idempotente, como as migrações anteriores.
2. **`knowledge.py`** — a loja do grafo. Toda leitura e escrita do grafo passa por
   aqui: é a única porta, e é o que faz o botão da UI e a ferramenta do agente
   serem a mesma implementação (D024).
3. **`extracao.py`** — o pipeline: fatiar a fonte em blocos, chamar o modelo com
   `response_format` (D021), validar os trechos, gravar por `knowledge`.
4. **`engine/tools/grafo.py`** — as ferramentas do agente (D027).
5. **`/api/grafo/*`** — o grafo inteiro, a tela do conceito, e as ações de edição.
6. **`graph.js` + painel na home** — force-directed em canvas, **sem biblioteca**
   (o app não tem CDN e não vai ter).
7. **"virar conhecimento"** — uma conclusão da conversa vira menção
   (`thread_id` + `message_id`, que já estão previstos no schema).

### Decisões do plano

**D041 — o conceito é canônico por chave normalizada, e o extrator vê o vocabulário
que já existe.**
Normalizar (minúsculas, sem acento, pontuação virando espaço, espaços colapsados)
resolve as variantes triviais: `OBD-II` / `OBD II` / `obd ii` caem todos em
`obd ii`.

Correção, ao implementar: **`OBD2` NÃO cai junto** — normaliza para `obd2`, que é
outra chave. Este plano chegou a afirmar que resolvia, e não resolve. Não vou forçar
equivalência entre dígito e número romano: isso quebraria `ISO 14230-4` e casos
legítimos de nome distinto.

Quem resolve `OBD2` é a segunda metade da decisão, por isso ela é a que importa:
**antes de extrair, entregamos ao modelo a lista dos conceitos que já existem**, com
a instrução de reusar o nome. O modelo vê `OBD-II` na lista e não inventa `OBD2`.
Sem isso o grafo fragmenta em variantes e o F6 (embeddings) viraria obrigatório só
para deduplicar — ou seja, uma fase futura passaria a ser pré-requisito de uma
anterior. O resto é a mesclagem manual na UI.

**D042 — extração é uma ação explícita, não um efeito de adicionar fonte.**
O roadmap dizia "extração automática ao adicionar fonte". Isso custa chamadas de
modelo: uma fonte de 50 mil caracteres dá cerca de 7 blocos. Automático significa uma
conta que cresce sem a pessoa pedir, e adicionar uma fonte deixaria de ser
instantâneo.
Então: **botão "Extrair conceitos"** no caderno, e o agente também pode disparar pela
ferramenta (D024). Se você preferir automático, é um interruptor — mas o padrão é
você mandar.

**D043 — co-ocorrência sai do bloco; aresta explícita exige trecho.**
Co-ocorrência: dois conceitos no mesmo bloco → aresta, com peso = número de blocos em
que aparecem juntos. Sai de graça da extração, sem custo extra.
Explícita: o modelo (ou você, na UI) afirma uma relação entre dois conceitos — e aí
ela **exige o trecho que a sustenta**, com a mesma validação. Aresta sem rastro não
entra: é ela que faz a diferença entre um grafo e um emaranhado de palpites.

**D044 — a extração não é um subgrafo do LangGraph.**
`graphs/` fica para o F5, que tem passe de compilação com acompanhamento na tela
(D028). Extração é lote: fatiar → chamar → validar → gravar. Um grafo do LangGraph
aqui seria cerimônia sem ganho.

### O que só o provedor real ensinou (D046)

O plano dizia "extração por `response_format` (D021)" e parava aí. Medindo contra a
DeepSeek, as três alternativas se comportaram assim:

| método | resultado |
|---|---|
| `json_schema` (o padrão da lib) | 400 — "This response_format type is unavailable now" |
| `function_calling` | 400 — "Thinking mode does not support this tool_choice" |
| `json_mode` | funciona — **mas o schema NÃO chega ao provedor** |

O último detalhe é o que importa. `json_mode` manda apenas
`response_format: json_object`: o modelo não recebe o schema, só o que o prompt
disser. Sem descrever o formato, ele devolveu `{"conceito": ...}` no lugar de
`{"nome": ...}` e a validação falhou — um erro que nenhum teste com fake pegaria,
porque o fake não fala com o provedor.

Solução: **o formato vai no prompt, gerado do próprio Pydantic**. Descrever à mão
divergiria do validador em silêncio, e o sintoma seria uma extração que "não acha
nada", sem erro nenhum na tela. Há teste que trava isso, e outro que confirma que um
campo novo no modelo aparece no prompt sozinho.

### D047 — co-ocorrência de peso 1 não é relação

Medido no caderno real: das 1521 arestas, **1266 tinham peso 1** — dois conceitos
que apareceram juntos *uma vez* num bloco de 6 mil caracteres. Com ~18 conceitos por
bloco, isso é praticamente todo par possível. O grafo saía um novelo.

Peso 1 num bloco grande é vizinhança, não relação. Então o desenho filtra em 2 por
padrão, e as 93 afirmadas (com trecho) continuam sendo o sinal de ouro.

E um defeito que os números denunciaram: o filtro de peso valia para os dois tipos de
aresta, e como toda afirmada tem peso 1, a tela escondia as **afirmadas** e mostrava
as fracas — exatamente ao contrário. A afirmada é afirmação do material; não se
filtra por frequência. Há teste.

### O que o F3 não faz

- embeddings e arestas por similaridade — F6
- SRS, lacunas, contradições, fontes órfãs — F4
- o PDF e a compilação — F5

### Critério de pronto

- extrair os conceitos do caderno real (~150 mil caracteres) e o grafo aparecer na
  home, com arestas
- abrir um conceito e ver os **trechos de origem**, com fonte e caderno
- perguntar ao agente *"o que se liga com KWP2000?"* e ele responder **pelo grafo**,
  citando onde
- mesclar dois conceitos na UI e o grafo refletir
- **zero trecho gravado que não exista na fonte** (com a taxa de descarte visível)

### Ordem de execução

1. tabelas + migração + `knowledge.py` + testes — lógica pura, sem modelo
2. `extracao.py` + fake que devolve conceitos + testes — testável sem rede
3. `tools/grafo.py` + rotas
4. UI: painel na home e tela do conceito
5. prova real, no caderno de verdade

### F4 — Painel de estudo  ← CONCLUÍDA
- [x] `study.py`: cards e a repetição espaçada (SM-2 simplificado), lógica pura
- [x] `knowledge.py`: `lacunas()`, `fontes_que_nao_contribuiram()`, `conceitos_por_fonte()`
- [x] `engine/estudo.py`: gerar card (do conceito + trecho) e achar contradição
- [x] `engine/tools/estudo.py`: o agente respondendo "o que meu material não cobre"
- [x] abas no painel direito: **Gerar** | **Estudar** (D048)
- [x] a revisão do dia (grade: errei · difícil · bom · fácil)
- [x] notas por conceito (a tabela `notes` já existia desde o F3)
- [x] `source_usage`: a citação `[n]` na resposta vira registro de uso da fonte (D051)
- [x] **Critério de pronto:** 9 cartões gerados no caderno real, com o trecho de origem
      no verso; revisão pelo painel; lacunas conferíveis na fonte; o agente responde
      "o que meu material não cobre" pelos fatos do grafo

**Resultado honesto da detecção de contradições, no material real:** examinou 5
conceitos que aparecem em duas ou mais fontes (CAN, DTC, ISO 15765, OBD, Read Freeze
Frame Data) e **achou 0**. Um detector que se recusa a inventar devolvendo zero é bom
sinal, mas o **caminho positivo não está provado com dado real** — só com fake, nos
testes. Para provar, seria preciso um material com duas fontes que de fato conflitam.

### Os dois defeitos que só o uso real mostrou

**1. Cartão sem resposta.** Na primeira geração de verdade, 3 de 12 cartões nasceram
com *"não está no material"* como resposta. O modelo foi **honesto** — o trecho não
respondia ao conceito — e o código criava o cartão assim mesmo. Um cartão sem resposta
não ensina nada e ainda ocupa a fila de revisão.
Corrigido com `vale_a_pena()`: pergunta vazia, resposta vazia ou resposta que diz que
o material não responde → o cartão **não nasce**, e o motivo aparece na tela. Na
regeneração, os mesmos 3 conceitos foram pulados com o motivo, e saíram 9 cartões
úteis em vez de 12 com 3 inúteis.

**2. Pergunta que não se sustenta sozinha.** A primeira leva saiu com fronts como
*"Qual é o primeiro campo?"* — o primeiro campo **de quê?** Um cartão ambíguo é pior
que nenhum, porque a pessoa marca "bom" sem ter recuperado nada. O prompt passou a
exigir que a pergunta **nomeie o conceito**. Na segunda leva:
*"In the frame structure, where does the 11-bit identifier appear?"*.

E fica registrado o que **não** foi resolvido: numa transcrição de podcast, os trechos
vêm sem contexto suficiente (*"tem que ser Java"*) e o cartão sai raso. É o mesmo
problema da taxa de descarte na extração, e continua pendente.

---

## 7.2 Plano do F4 — o painel de estudo

### O que a fase entrega

Transformar o painel direito de **gerador de documentos** em **instrumento de
estudo**. O F3 deixou a matéria-prima (conceitos ancorados em trecho); o F4 usa essa
matéria-prima para dizer o que você sabe, o que você não sabe, e o que o seu material
não cobre.

### A regra que esta fase herda do F3

O F3 estabeleceu: **não afirmar o que não se pode conferir**. O F4 leva a mesma régua
para um terreno onde é muito fácil trapacear — "lacunas" e "contradições".

> **Lacuna é fato verificável, não opinião do modelo sobre o que falta.**

Um modelo listando "tópicos que faltam no seu material" é opinião: ele não leu o que
você não tem, ele comparou com o que ele já sabe. Seria o único lugar deste app onde
ele afirmaria algo sem lastro — e é justamente o tipo de coisa que soa mais
impressionante e é menos confiável.

Então as lacunas do F4 são três fatos, todos computáveis do grafo, sem chamada de
modelo e sem chute:

1. **Conceito nomeado e não desenvolvido** — aparece uma vez e não tem nenhuma
   ligação afirmada. O material citou e não explicou.
2. **Conceito que existe em outro caderno e não neste** — você estudou ali e aqui ele
   nunca aparece. Só é possível porque o grafo é global (D045).
3. **Fonte que não contribuiu** — não gerou menção nenhuma: o material entrou e não
   virou conhecimento.

O que a pessoa pode fazer com isso é conferir cada uma na fonte. Uma "lacuna" que ela
não pode conferir seria exatamente o que este projeto não faz.

### As peças, na ordem

1. **`db.py`** — tabelas `cards` e `source_usage` (a de `notes` já existe do F3).
2. **`study.py`** — o card e o agendamento. Lógica pura, sem modelo, testável.
3. **`knowledge.py`** — `lacunas()`, `fontes_que_nao_contribuiram()`, `cards_devidos()`.
4. **`engine/estudo.py`** — os dois usos de modelo: **compor a pergunta** de um card a
   partir do trecho, e **comparar duas fontes** sobre o mesmo conceito.
5. **`engine/tools/estudo.py`** — o agente respondendo "o que meu material não cobre?"
   e "o que eu tenho para revisar hoje?".
6. **Rotas e UI** — abas no painel direito, a revisão e as notas.

### Decisões do plano

**D048 — o painel de estudo são abas na coluna que já existe, não uma quarta coluna.**
O caderno já tem três colunas e a soma delas ocupa a tela. "Gerar" e "Estudar" são as
duas a mesma natureza — coisa derivada das fontes — então dividem a coluna.

**D049 — o agendamento é um SM-2 simplificado, e a simplificação é deliberada.**
Quatro notas (errei · difícil · bom · fácil), fator de facilidade partindo de 2.5,
intervalo que cresce pelo fator. Um algoritmo elaborado sem uso real é fé: o que
importa é que a revisão de hoje seja curta e que o card difícil volte logo. Se o uso
mostrar que não basta, aí se elabora — com dado.

**D050 — contradição é comparação sobre o MESMO conceito, e exige as duas citações.**
Percorrer todos os pares de fontes seria caro e quase todo par não tem o que comparar.
O caminho: conceitos que aparecem em **duas ou mais fontes**, os trechos de cada um
lado, uma chamada por conceito, e o modelo responde se alguma dupla conflita —
citando as duas. Contradição sem as duas citações é descartada, como o trecho
inventado na extração. É ação explícita (D042): custa chamadas de modelo.

**D051 — a citação `[n]` na resposta é o registro de uso da fonte.**
"Fonte órfã" só é verdade se eu souber o que foi usado. Em vez de instrumentar o
agente, uso o que ele já escreve: os marcadores `[n]` no texto, que apontam para a
numeração determinística das fontes (feita no F1 justamente para casar). A resposta
vira registro em `source_usage`, e "órfã" passa a significar "nunca citada numa
resposta" — conferível, em vez de suposto.

**D052 — a barra lateral.**
Grafo e chat saíram do meio da página e da gaveta de baixo para uma **barra fixa à
direita**, com abas (o mesmo padrão do painel do caderno, D048). O motivo é o de
sempre: os dois exigiam rolar até eles e sumiam da vista assim que se mexia nos
cadernos. Um grafo de conhecimento serve para ser olhado **de relance enquanto se lê
outra coisa** — no meio da página ele não fazia isso.

Duas regras que a barra aprendeu depois de quebrar:

**A barra encosta na DIREITA, e quem acompanha a largura é o conteúdo.** O `max-width`
estava na caixa da página, então numa janela de 1920px a página parava em 1180 e a
barra começava ali — **340px de vazio à direita dela**, a barra flutuando no meio.
Medido: `lateral 1180..1580` num `home` de 1920. Agora não há teto nem na caixa nem no
conteúdo: a grade de cadernos já é fluida (`auto-fill`) e só ganha colunas (2 em 1280,
5 em 1920, 7 em 2560), com a barra sempre na borda.

**Redimensionar a janela recompõe o desenho.** Faltava o `resize` do grafo: o canvas só
se media ao ser criado e na troca de aba, então maximizar deixava o desenho no tamanho
antigo — desenhado para uma caixa que já não existia. Com espera de 140ms, porque o
`resize` dispara dezenas de vezes por segundo durante o arraste.

**E o grafo abre no contexto de UM caderno.** O padrão era "todos os cadernos", que é
justamente onde os conceitos de duas matérias viram um borrão. A mistura continua na
lista — serve para ver as pontes — mas o normal é estar estudando um caderno e querer o
mapa dele.

**D053 — o desenho do grafo tem física, e a vista tem outra função.**
Antes, quem dava forma ao desenho era o `clamp` do retângulo do quadro: a repulsão
empurrava os nós para fora, eles batiam na borda e ficavam ali. O formato final era o
**do quadro**, não o da física — e num quadro estreito isso fica evidente.

Agora o desenho sai do **equilíbrio** entre a gravidade ao centro (linear na distância,
para a borda não ficar frouxa) e a repulsão entre todos os pares (com piso de distância,
senão dois nós vizinhos explodem). Num disco de N nós o raio de equilíbrio cresce com a
raiz cúbica de N: o desenho fica redondo sozinho e cresce para acomodar mais conceitos.
Não existe mais limite de raio — a física já se limita.

E **a vista encaixa**: a física decide o tamanho relativo, a vista decide quanto cabe na
tela. Sem essa separação o tamanho da barra decidia o desenho (num quadro baixo o grafo
transbordava). A escala é aplicada à mão, e não com `ctx.scale`, porque **o texto do
rótulo não pode encolher junto** — a escala fica em ~0,8 aqui, e um rótulo de 11px
viraria 9px se fosse escalado.

**D054 — o desenho mostra só os conceitos do material.**

O caderno de verdade tinha **102 conceitos e 255 arestas** — um novelo onde não se
seguia uma linha. O dado que decidiu o corte:

    conceitos ....................... 102
    com 2+ menções ..................  30
    com 3+ menções ..................  12
    citados 1 vez, sem ligação alguma  22
    com ligação afirmada ............  78

Filtrar por "tem ligação afirmada" quase não ajuda (78 de 102). O que separa é a
**repetição**: num material de 150 mil caracteres, um termo citado **uma única vez** é
menção de passagem, não conceito daquele material.

    Conceito DO material = aparece 2+ vezes, OU atravessa cadernos.

A segunda parte é a exceção que não pode faltar: um conceito citado uma vez em cada um
de dois cadernos tem duas menções e é **a ponte entre áreas** — esconder ele seria
esconder justamente a informação mais interessante do grafo.

Resultado: **30 conceitos** no lugar de 102, com 199 arestas no lugar de 255 — e, o que
importa, um desenho onde dá para seguir uma linha.

**O corte é do DESENHO, não do banco.** Os 72 conceitos de passagem continuam
guardados, e são eles que o painel de estudo usa nas lacunas ("o material citou e não
explicou"): apagar do banco destruiria uma funcionalidade do F4 para resolver um
problema de desenho. `ocultos` diz quantos ficaram fora, e o interruptor **principais**
os traz de volta — a decisão continua sendo sua.

Fica registrada a alternativa que **não** foi escolhida: mandar o extrator salvar menos
conceitos. Ela também diminuiria o novelo, mas é irreversível (o conceito filtrado não
volta sem pagar a extração de novo) e custaria as lacunas. Filtrar no desenho é
reversível e não custa nada.

**D055 — o nível de repouso é o MAPA: os nós são CADERNOS.**

A tela abre no mapa. Cada nó é um caderno — e não um conceito. A aresta liga dois
cadernos que **dividem** um conceito: o mesmo `concepts.id` com menção registrada nas
fontes dos dois. `motivos` traz os nomes que sustentam a ligação, porque a aresta é
conferível e não uma impressão.

    mapa   -> no = caderno      tamanho = quantos conceitos ele tem
                              aresta = quantos conceitos dois cadernos dividem
    clique -> no = conceito     as relações ancoradas em trecho daquele caderno
    Voltar -> volta ao mapa

**A primeira versão disto estava errada, e o erro vale o registro.** Eu tinha entendido
"um grafo por caderno" como *agrupar os conceitos por caderno*: desenhei os 102 conceitos
em ilhas separadas, cada ilha com o nome do caderno. O usuário foi direto ao ponto:

> *"ele ainda mostra todos os conhecimentos como grafos, e não os cadernos como grafos"*

É a diferença entre **agrupar** e **ser**. Ilha de conceitos continua sendo um grafo de
conceitos — só arrumado. O que ele queria era o nó SER o caderno: 102 conceitos viram UM
nó. Dois níveis, e o de cima responde "o que eu tenho e o que se liga a quê".

A única coisa que sobreviveu dos dois desenhos foi **a regra das forças**, que já estava
certa: cada nó é puxado para o centro de cada caderno dele. No mapa, cada nó pertence a
um caderno, então cada um vai para o seu lugar no anel e os cadernos ficam distribuídos.
Dentro de um caderno, o foco manda e volta a ser o círculo de sempre.

**Os rótulos de ilha (chips) foram removidos.** Eles existiam para dar nome às ilhas
quando os nós eram conceitos. Com o nó sendo o caderno, o nome do nó JÁ é o nome do
caderno — e o chip era o mesmo texto escrito duas vezes. Saíram ~95 linhas de desenho,
de detecção de clique e de estado: código que, depois desta mudança, nunca mais rodava.

**Um erro de nome, três sintomas que não pareciam ter a mesma causa.** No mapa eu
nomeei o campo `cadernos`; o desenho lê `notebooks` (o contrato da API). Sem o campo, o
desenho não achava caderno nenhum em cada nó, e daí saíram as três coisas ao mesmo tempo:
nós **cinzas** (caiu no fallback de cor), os dois nós **colados no centro** (nenhuma ilha,
todos puxados para o mesmo ponto) e **um rótulo sumido** (a colisão de caixa derrubou o
segundo, porque estavam sobrepostos). Nenhum dos três sintomas se parece com "o nome do
campo está errado". Ficou um teste que prende o nome do campo.

**D056 — o desenho mostra TODAS as conexões.**

A D047 tinha posto o peso mínimo em 2 (dois conceitos juntos uma vez, num bloco de seis
mil caracteres, não é relação). O problema é o que isso esconde em silêncio: no caderno de
verdade, peso 2 mostrava 199 das **275** ligações — 74 invisíveis, e a pessoa não tem como
saber que faltam 74. O número na tela não mente, mas também não avisa.

Regra nova: **o corte que sobra é de NÓ, e é o único que a pessoa controla.** O filtro
"principais" (D054) tira nó, e diz quantos tirou (`30 de 102`). A aresta não se esconde
mais: se dois conceitos do desenho aparecem juntos, a linha está lá. A diferença entre
afirmada e co-ocorrência continua no TRAÇO (cheia × pontilhada), que informa sem omitir.

**D057 — o nó é uma bolha de vidro azul-clara.**

Pedido direto: *"mudar a cor de laranja para um azul claro, dando a impressão de 3D, como
se fosse uma bolha para entrar no tema Frutiger Aero"*.

Quatro coisas fazem a leitura de 3D, e são as quatro de um balão de vidro: **a luz vem de
cima e da esquerda** (o gradiente deslocado para lá), **o brilho especular** (o reflexo, o
ponto branco que diz "vidro" e não "círculo pintado"), **a luz que atravessa e volta por
baixo** (o arco claro na base, que faz a bolha parecer cheia) e **o aro** (claro onde bate
luz, escuro do outro lado). O halo existe por um motivo prático: o fundo é escuro, e sem
ele o nó parece um adesivo colado no painel em vez de uma bolha sobre ele.

**A cor por caderno saiu.** A paleta indexada por hash do título dava laranja e rosa a um
app ciano — e era uma legenda a mais para aprender. A identidade do caderno não se perdeu:
no mapa o nó tem o nome do caderno escrito nele, e dentro de um caderno todos os conceitos
são dele. A ponte entre cadernos passou de anel laranja para **aura clara** em volta da
bolha: a cor do preenchimento não é mais usada para informar, então o sinal ganhou o
próprio lugar em vez de competir com a identidade do nó.

**Um encaixe que só apareceu com as bolhas:** o cálculo da escala reservava 8px de margem,
mas o halo e o rótulo embaixo do nó não encolhem junto com o desenho. Os nós das pontas
saíam cortados na borda. Agora a escala é calculada em **duas passadas** — o raio encolhe
com a raiz da escala, o halo é proporcional ao raio e o rótulo não encolhe nada, então as
três dependem da escala de formas diferentes e a conta fechada não existe. Verificado
varrendo as quatro bordas do canvas: zero pixel encostando.

**D058 — o clique: um `div` invisível estava engolindo tudo.**

O sintoma do usuário foi o mais direto possível: *"não clica, nada acontece quando clico
nelas"*. E o meu teste de clique passava.

A causa: `#grafo-vazio` (o aviso de "grafo vazio") tem `display: flex`, `position:
absolute` e **cobre o canvas inteiro**. Ele estava com `hidden: true`, e **`display` vence
o atributo `hidden`** — então ficava invisível e engolia todo clique real. O grafo parecia
morto ao toque, e nenhum evento chegava ao canvas.

O que fez o defeito passar despercebido foi o TESTE: eu disparava o evento **direto no
canvas**, e **`dispatchEvent` não faz hit-test**. O caminho que eu testava não era o
caminho do usuário. Um clique de verdade é: o navegador escolhe o elemento do topo
(`elementFromPoint`) → o evento nasce nele → sobe. Testar clique é testar essas três
coisas, e a partir de agora é assim aqui: `elementFromPoint` primeiro, evento disparado
**nesse** elemento.

**Este foi o QUARTO round do mesmo defeito** (`display` vencendo `hidden`), e o mais caro:
os três anteriores eram de visibilidade, este matou a interação. As correções pontuais
(`.overlay`, `.lateral-painel`, `.conceito`, `.grafo-toggle`) foram todas removidas e
substituídas por uma regra só, no topo do CSS:

    [hidden] { display: none !important; }

**E duas fragilidades que o clique revelou**, corrigidas junto:

- **o alvo era menor que a bolha visível.** O halo é bem maior que o raio, então quem
  mirava na borda luminosa mirava fora do círculo. O alcance agora é `raio * 1.35 + 6`.
- **o rótulo não era clicável.** Ele é o pedaço maior e mais óbvio do conjunto, e clicar
  no nome do caderno sem nada acontecer é o que faz parecer quebrado. A caixa do rótulo
  entrou como área de acerto (medida junto com a decisão de colisão, que já calculava a
  caixa). A área clicável da bolha pequena foi de ~19px para **44px** de faixa.

### D059 — o artefato roda fora do turno, e o id é o contrato

O D028 acertou o princípio e errou o mecanismo, e a diferença só apareceu na hora de
implementar.

O princípio continua inteiro: **a ferramenta do agente não pode construir o documento
dentro de si.** Três coisas ruins acontecem de uma vez quando ela constrói — a tela fica
parada por meio minuto (a compilação tem uma chamada de modelo no meio), o documento não
pode ser escrito na tela enquanto é escrito (ferramenta não emite delta: o streaming do
agente passa por cima dela, não por dentro), e o agente ainda passa o resultado por cima,
reformatando um documento que já estava pronto.

O que mudou foi o *como*. O subgrafo do LangGraph seria **cerimônia em volta de uma
sequência linear de passos**: o LangGraph ganha quando há ramificação, reentrada ou estado
que precisa ser retomável, e a compilação não tem nenhum dos três — é uma linha reta que
termina num output gravado. O preço seriam três nós, um checkpointer para uma tarefa que
dura segundos e um `thread_id` a mais para administrar; e o valor que ele traria (eventos
nomeados de progresso) nós já temos de graça, porque o feed da oficina é exatamente isso.
É a mesma conta da D044, e vale aqui pelo mesmo motivo.

Então o artefato virou um **run**. `oficina.iniciar()` cria a tarefa e devolve um id na
hora; quem constrói é o run; quem quer ver segue `oficina.acompanhar(id)`. O id é o
contrato entre os três que precisam se encontrar — quem pediu, quem acompanha (a tela) e o
que fica no disco (o output) — e é ele que faz o botão e a ferramenta do agente serem o
**mesmo caminho** (D024) sem pagar a aninhagem.

Três consequências que ficaram no código, e as três têm teste:

1. **Disparar e acompanhar são dois verbos.** `POST /compilar` devolve o run e volta na
   hora; seguir é `GET /api/artefatos/{id}`. Se o POST transmitisse o progresso, a tela
   teria **dois** códigos de seguir run — o do botão e o do run nascido no chat — e o
   segundo seria o esquecido na primeira mudança.
2. **O histórico vem antes do ao vivo.** `acompanhar` entrega os eventos que já
   aconteceram e só então entra na fila. Quem abre a página no meio da compilação (ou
   descobre um run já pronto) vê os passos todos; sem isso, a caixa de progresso nasceria
   vazia e pareceria travada.
3. **Um caderno, uma compilação.** Pedir de novo enquanto uma está em curso devolve a
   mesma — e a ferramenta do agente **diz** que já havia uma em vez de disparar outra.
   Duas ao mesmo tempo gastariam duas chamadas de modelo para produzir dois documentos
   quase iguais, e o caso real é o clique duplo e o "compila isso" no chat durante uma
   compilação.

E o que a oficina **não** é: um job runner. Não há fila em disco, não há retomada depois de
reiniciar o app, não há paralelismo. Um run vive na memória do processo e some com ele — o
que sobrevive é o que importa, e é o documento gravado como output.

### D060 — uma ferramenta de artefato, e só a que existe

O catálogo do F5 prometia duas ferramentas: `gerar_documento` e `compilar_pdf`. Nenhuma
entrou com esse nome, e as duas razões são as de sempre neste projeto:

- **`compilar_pdf` não faz sentido como ferramenta.** Não há PDF no servidor: a D014
  decidiu imprimir pelo navegador. Uma ferramenta que prometesse "salvar o PDF" estaria
  prometendo o que só o navegador de quem está olhando sabe fazer.
- **`gerar_documento(template=...)` prometeria o que não existe.** Há **um** template — o
  documento compilado. Um parâmetro aceitando "plano", "faq" e "guia" seria um convite ao
  modelo para pedir formatos que ninguém escreveu, e à pessoa para esperar por eles.

Então entrou `compilar_documento`, sem parâmetros, presa ao caderno (D034) e **só no
catálogo do caderno**: no chat global não há caderno, e a alternativa — receber
`notebook_id` por argumento — é exatamente o que a D034 proíbe.

Entrou também, na docstring que o modelo lê, a instrução que fecha o D028 pelo outro lado:
**não repita o conteúdo do documento na resposta.** Sem ela o modelo copia o resumo e o
desenvolvimento para o chat — que é a segunda metade do problema (o texto reformatado por
cima). Na prova real ele obedeceu: devolveu o id, disse em que painel o documento aparece,
e não colou o texto.

### O que o F4 não faz

- **geração de mídia**: nem áudio, nem imagem, nem vídeo. Nunca esteve no escopo.
- embeddings e arestas por similaridade — F6
- o PDF e a compilação — F5

### Critério de pronto

- revisar os cards devidos do dia no caderno real, com as quatro notas
- cada card mostra o **trecho de origem** no verso: o card é conferível como tudo
- as lacunas listadas são conferíveis uma a uma nas fontes
- uma contradição encontrada no material real, com as duas citações lado a lado
- perguntar no chat *"o que meu material não cobre?"* e ele responder pelos fatos do
  grafo, não por opinião

### Ordem de execução

1. tabelas + `study.py` + SRS + testes — lógica pura
2. `knowledge.lacunas()` + testes — consultas, sem modelo
3. `engine/estudo.py` (card e contradição) + fake + testes
4. tools + rotas
5. UI: abas, a revisão, as notas
6. prova real, no caderno de verdade

### F5 — Export  ← CONCLUÍDA
- [x] `engine/artefato.py`: o passe de compilação — em **lista de seções**, e não como texto
      solto, que é o que permite o sumário sair dos títulos reais e o apêndice ser montado
      por último. Não virou `graphs/`: o subgrafo do LangGraph aqui seria cerimônia sem
      ganho (D044), e o mecanismo do D028 foi revisto na D059
- [x] `engine/oficina.py`: o **run com id**, fora do turno que o pediu, com feed de eventos
      — disparar e acompanhar viram dois verbos (D059)
- [x] `engine/tools/artefatos.py`: `compilar_documento` — dispara o run e devolve o id, sem
      esperar o documento. A dupla prometida (`gerar_documento`/`compilar_pdf`) não entrou,
      com o porquê medido na D060
- [x] CSS de impressão claro (o tema Aero escuro gasta tinta)
- [x] estrutura: capa, sumário, resumo, conceitos citados, desenvolvimento,
      lacunas abertas, fontes resumidas, apêndice de citações
- [x] mesmo pipeline → Markdown (o próprio documento), **Anki** (TSV) e **Obsidian**
      (`[[wikilinks]]`)
- [x] **Critério de pronto:** 38 seções no caderno real (34 do grafo, 2 do banco e 2 do
      modelo), 34.722 caracteres; folha de impressão clara; o documento pedido pelo **chat**
      aparece no painel (provado no log do servidor: o painel pergunta, descobre o run e
      segue); Anki e Obsidian saem do mesmo passe

### F6 — Arestas por similaridade
- [ ] embeddings por conceito (`LLM_EMBED`)
- [ ] arestas `similarity` acima de limiar

---

## 7.3 Plano do F5 — o documento compilado

### O que a fase entrega

Um documento que **não é um ensaio do modelo sobre o material**: é o material COMPILADO.
A diferença inteira está em de onde vem cada parte.

| Parte | De onde vem | Chama modelo? |
|---|---|---|
| Capa | metadados do caderno (título, data, contagens) | não |
| Sumário | dos títulos das próprias seções | não |
| Resumo | modelo, ancorado nas fontes, citando `[n]` | **SIM** |
| Conceitos do material | **o grafo**: cada conceito com o trecho literal de origem | não |
| Desenvolvimento | modelo, escrito **a partir dos conceitos do grafo** | **SIM** (mesma chamada) |
| Lacunas abertas | `knowledge.lacunas()` — citado e nunca explicado | não |
| Fontes | banco + registro de uso (D051): o que cada uma rendeu, e a órfã | não |
| Apêndice de citações | a tabela `mentions` impressa: fonte, trecho e ordem | não |

**A regra do F3 outra vez, agora no papel: o que está no documento é conferível.** Os
conceitos listados existem no grafo, cada um com o trecho que o sustenta; as lacunas são
uma consulta, não uma opinião; o apêndice é a tabela de menções. O modelo escreve a
**ligação** entre as coisas — nunca os fatos. Toda seção que ele não escreve é uma seção
que ninguém pode inventar.

Por que **uma** chamada de modelo, e não uma por seção: as partes de fato e de estrutura
somam sozinhas a maior parte do documento, e o texto corrido precisa ser um só — resumo e
desenvolvimento escritos em chamadas separadas saem com vozes diferentes e se repetem.

### O que a fase NÃO é

- **Não é um PDF montado no servidor.** A D014 decidiu: **CSS de impressão +
  `window.print()`**. Zero dependência, tipografia de verdade, paginação pelo navegador
  (quebra de página e cabeçalho são CSS). Um PDF nativo pediria biblioteca de renderização
  — e as boas pedem `cairo`/`pango` no sistema, o que quebraria o "clone e roda".
- **Não é o subgrafo do D028.** Este plano entrega o **botão** (a UI) com o passe de
  compilação acompanhado na tela. O D028 vale para a **ferramenta do agente**, que tem que
  disparar o subgrafo em vez de aninhar a chamada — e essa é a etapa seguinte, com o
  `engine/tools/artefatos.py`. O que fica pronto agora é a implementação única que os dois
  pontos de entrada vão compartilhar (D024).

  > **Feito, e a etapa 2 mudou o mecanismo.** A ferramenta existe (`compilar_documento`) e
  > dispara um **run da oficina**, com id, em vez de um subgrafo do LangGraph. O princípio
  > do D028 é o que ficou de pé — a ferramenta não constrói o documento dentro de si — e a
  > razão da troca está medida na **D059**. O que o botão entrega continua sendo a
  > implementação única, e é ela que a ferramenta usa.

### As peças, na ordem

1. `engine/artefato.py` — o passe de compilação. Monta o documento como uma lista de
   seções (`{nivel, titulo, corpo, origem}`), e não como um texto solto: é o que permite
   ao sumário sair dos títulos reais e ao apêndice ser gerado por último.
2. Testes com **backend falso** (a regra do projeto): o documento tem o caderno de
   verdade, e cada seção de fato é conferida contra o grafo.
3. Rotas: compilar (SSE, com o passo atual), ler, baixar `.md`, e a **versão imprimível**.
4. O CSS de impressão **claro** — o tema Aero escuro gasta tinta e sai ilegível no papel.
5. Formatos extras, do mesmo pipeline: **Anki** (os cartões do F4 em TSV) e **Obsidian**
   (os conceitos com `[[wikilinks]]`).

E a **etapa 2**, que o plano deixou como "a seguir" e agora está feita:

6. `engine/oficina.py` — o run com id, fora do turno, e o feed de eventos (D059).
7. `engine/tools/artefatos.py` — `compilar_documento`, que dispara e devolve o id (D060).
8. As rotas de acompanhamento: `GET /api/artefatos` (o painel pergunta) e
   `GET /api/artefatos/{id}` (o painel segue) — o MESMO caminho para o run do botão e o
   do chat, porque disparar e acompanhar são dois verbos.

### Critério de pronto

- [x] O documento compilado abre no navegador e imprime em PDF sem cortar seção
- [x] Cada conceito listado traz o **trecho literal** que o sustenta, com a fonte
- [x] As lacunas do documento são **as mesmas** de `knowledge.lacunas()` (nenhuma palavra
      do modelo ali)
- [x] O apêndice tem **todas** as menções, e a contagem bate com o banco
- [x] Imprimir em preto no branco não tem fundo escuro nem texto claro
- [x] Saída Anki importa com pergunta e resposta; Obsidian gera os `[[links]]`
- [x] `ruff` limpo e os testes passando, com backend falso (sem rede, sem chave)

Medido no caderno real: **38 seções — 34 do grafo, 2 do banco e 2 do modelo** — e 34.722
caracteres de documento. O contador da tela é essa promessa em números: as seções de fato
são a maior parte, e o modelo escreve duas.

## 8. Fora de escopo (por decisão, não por esquecimento)

- Imagem, áudio, vídeo generativo
- Ferramenta de terminal no agente
- Colaboração multiusuário em tempo real
- RAG vetorial antes do grafo por conceito provar valor
- Kubernetes, fila, microsserviço — é um app de uma máquina
- O Hermes Agent como dependência de runtime (D017)

---

## 9. Riscos conhecidos

| risco | mitigação |
|---|---|
| Churn do LangChain/LangGraph (comprovado: depreciação na v1) | D022 pinagem + D018 fronteira num só pacote |
| Ferramenta demais degrada a escolha do modelo | D025 conjunto exposto curado por contexto |
| Tool call de modelo local vem quebrada ou como texto | testar local antes de prometer; `response_format` onde der |
| Extração de conceito vira ruído | D021 + nó canônico + aliases + edição pelo usuário |
| Grafo vira bola de pelo (~200 nós) | filtros por caderno, peso e recência desde o primeiro dia |
| Custo de extração automática | tarefa pequena, cache por hash da fonte, local dá conta |
| Escopo de 6 fases / semanas | cada fase entrega valor sozinha |
| Conversa longa estoura contexto | `middleware` de compactação do LangGraph |
| 89 MB de dependências | aceito: é `pip install`, 21× menor que o Hermes |
| Conflito de marca com "Frutiger" (Monotype) | D029 — verificar antes de publicar |

---

## 10. Como verificamos

Regra canônica, sem exceção:

```
uv run ruff check .
uv run pytest
```

- Todo teste que tocaria LLM usa o **modelo falso** (`engine/fake.py`): sem rede,
  sem chave, sem custo. É o que permite 48 testes rodarem em 0,2s.
- Funcionalidade de UI se verifica **renderizando e olhando**.
- **O DOM é a fonte da verdade, não o snapshot de acessibilidade.** A árvore de
  acessibilidade colapsa inline em alguns casos e já produziu dois falsos alarmes
  nesta sessão (pareciam `<strong>` vazios; não havia nenhum). Antes de acusar bug
  de renderização, conferir `document.querySelector` / `innerHTML`.
- Toda decisão de arquitetura ganha entrada na seção 2 **antes** do código.
- Antes de escrever código contra API de terceiro, **verificar a assinatura real**
  na versão instalada. Foi assim que se descobriu a depreciação do
  `create_react_agent`.
- **O fake pronto da lib não conduz o laço do agente.** O `bind_tools` herdado de
  `BaseChatModel` levanta `NotImplementedError`, e o `create_agent` liga as
  ferramentas no modelo antes de rodar. O nosso `engine/fake.py` implementa um
  `bind_tools` no-op justamente por isso — descoberto ao tentar testar,
  não ao tentar usar.
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

## 12. Estado atual (2026-09-25 — F1 a F5 concluídas)

Funcionando, com **307 testes** e ruff limpo:

- cadernos, fontes (link, PDF, YouTube, texto), chat com streaming e citação,
  7 templates de output, UI em três painéis com tema Frutiger Aero
- **home com barra lateral**: o grafo e o chat moram numa barra fixa à direita, em
  abas — visíveis o tempo todo, sem rolar até eles (D052)
- **o grafo tem física**: gravidade ao centro e repulsão entre os nós formam um
  círculo, e a vista encaixa o desenho no quadro (D053). Medido: 6% de variação de
  raio entre 24 setores
- **o grafo mostra só os conceitos do material** — 30 no lugar de 102 (D054), com o
  interruptor para ver os de passagem e o dado preservado para as lacunas do F4
- **o nível de repouso é o mapa** (D055): um nó por caderno, ligando os que dividem
  um conceito (a ligação é conferível e diz quais conceitos a sustentam); clicar no
  nó entra no caderno, e o **← Voltar** traz de volta ao mapa
- **chat do caderno** e **chat global**, com as mesmas ferramentas e escopos diferentes
- **grafo de conhecimento ancorado**: 102 conceitos e 156 menções no caderno de
  verdade, cada menção com o trecho literal de origem; painel na home com filtros,
  tela do conceito e edição
- **painel de estudo**: 9 cartões com o trecho no verso, revisão com quatro notas,
  lacunas conferíveis (sem opinião de modelo), contradições entre fontes e o registro
  de qual fonte cada resposta citou
- **documento compilado** (F5): 38 seções no caderno de verdade — **34 do grafo, 2 do
  banco e 2 do modelo** — com cada conceito trazendo o trecho literal de origem, as
  lacunas saindo de `knowledge.lacunas()`, o rendimento de cada fonte e o apêndice com
  todas as citações. O documento não é ensaio do modelo sobre o material: é o material
  compilado, e cada seção diz de onde veio (`origem`)
- **a compilação é um run, fora do turno** (D059): o botão dispara e volta, o painel
  segue pelo id, e o documento pedido **no chat** aparece na tela — provado pelo log do
  servidor (o painel pergunta em `/api/artefatos`, descobre o run e segue). Um caderno,
  uma compilação: o segundo pedido acompanha o primeiro em vez de pagar outra chamada
- **leva para fora**: folha de impressão clara (o tema Aero gasta tinta), Anki (TSV) e
  Obsidian com `[[wikilinks]]` — os três do mesmo passe
- motor: **agente LangGraph próprio**, dentro do app. O Hermes saiu de tudo
- o chat responde com o modelo que **você** configura; hoje, `deepseek-v4-flash`
- `frutiger-lm.service` (app, 8765) ativo e habilitado — `NRestarts=0`

Pendências conhecidas, e nenhuma bloqueia o uso:

- **a transcrição de podcast**: 31 de 47 trechos descartados na extração, e cartões
  rasos porque o trecho vem sem contexto. É o mesmo problema nas duas pontas
- "virar conhecimento" numa conclusão do chat (o único item do F3 que ficou de fora)
- `web_search` não existe (D036, adiada com critério)
- busca global por FTS5 (para a pessoa procurar; o agente já procura)
- a detecção de contradições teve resultado zero no material real — o caminho positivo
  está provado só com fake, não com dado

Verificado, sobre o stack adotado:

```
langgraph 1.2.12 · langchain 1.4.2 · langchain-openai 1.6.6
langgraph-checkpoint-sqlite 3.1.1 · venv completo 196 MB

OK  langchain.agents.create_agent(model, tools, system_prompt, checkpointer, ...)
OK  langgraph.checkpoint.sqlite.aio.AsyncSqliteSaver
OK  ChatOpenAI(base_url=..., api_key=..., model=...)  -> LM Studio e llama.cpp
OK  astream / astream_events / aget_state / aget_state_history
ATENÇÃO  langgraph.prebuilt.create_react_agent DEPRECIADO (sai na v2)
```

**F1 a F5 estão concluídas.** O app não depende de nenhum motor externo: o agente
LangGraph vive dentro dele, o histórico é o nosso checkpointer, o Hermes foi removido do
código, da configuração e do unit do systemd, e o que ele tem de diferente — o grafo
ancorado e o documento que sai dele — está de pé e provado no material real.

O que ficou de fora, por decisão: `web_search` (D036, adiada com critério) e, do F3, o
botão "virar conhecimento" numa conclusão do chat. O `AGENTS.md` registra as armadilhas
que as fases pagaram para descobrir — e ele cresce a cada fase, de propósito.

**Próximo: F6** — embeddings por conceito (`LLM_EMBED`) e as arestas por similaridade
acima de limiar. É a única fase que ainda não existe, e ela **não é pré-requisito de
nada**: o grafo se liga hoje por co-ocorrência e por aresta afirmada com trecho.

A ordem importa menos do que parece: cada fase é utilizável sozinha. A tese do produto
— o grafo como camada que liga, e o documento que se pode conferir — está entregue; o
que vier depois é afinação.
