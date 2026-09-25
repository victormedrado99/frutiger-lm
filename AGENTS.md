# AGENTS.md — como mexer neste repositório

Guia para quem for trabalhar no Frutiger LM (pessoa ou agente). O **`PROJETO.md` é
a fonte da verdade sobre decisões** — este arquivo é o atalho operacional. Se os
dois divergirem, o PROJETO.md ganha.

## O que é

App de estudo com fontes próprias: você joga PDF/link/YouTube/texto, conversa com
o material, gera documentos, e (a partir do F3) constrói um grafo de conhecimento
ancorado nas fontes. FastAPI + SQLite + UI vanilla, sem build. O agente é um grafo
LangGraph que vive **dentro** do app — não há motor externo.

## Comandos

```bash
uv sync                      # dependências
uv run ruff check .          # lint (é o linter canônico)
uv run pytest                # testes: sem rede, sem chave, ~1 s
uv run frutiger-lm           # sobe o app em http://127.0.0.1:8765
systemctl --user restart frutiger-lm.service   # se estiver rodando como serviço
```

**Rode `pytest` SEM pipe.** `uv run pytest | tail` não é capturado como evidência de
verificação pelo harness — o run parece "stale" mesmo verde. Se precisar do
resumo, rode puro e leia a saída.

## Regras que não se negociam

1. **Só `engine/` importa LangChain/LangGraph** (D018). O resto do app — `db`,
   `ingest`, `prompts`, `app`, a UI — não conhece a biblioteca. Isso contém o churn
   dela num pacote e permite que todo o resto seja testado com banco e arquivos de
   verdade.
2. **Teste nunca toca a rede.** Modelo real não é determinístico; use
   `engine/fake.py`. O fake tem **paridade entre bloco e stream**, e é isso que
   permite testar o caminho que o app realmente usa.
3. **Não use os fakes do `langchain-core`.** Você vai perder tempo. Duas limitações
   descobertas na prática:
   - `bind_tools` (herdado de `BaseChatModel`) levanta `NotImplementedError`, e o
     `create_agent` liga as ferramentas no modelo antes de rodar;
   - o `_stream` do `GenericFakeChatModel` não produz chunk para mensagem de
     `content` vazio — que é exatamente uma mensagem que só carrega tool call.
     Dá `ValueError: No generations found in stream`.
4. **Ferramenta é presa ao escopo na construção** (D034, D039):
   `ferramentas_de_leitura(Escopo.do_caderno(id))` ou `Escopo.todos()`. O
   `notebook_id` **nunca** é parâmetro de ferramenta — é o que garante que o chat
   de um caderno não leia as fontes de outro. E o mesmo catálogo serve aos dois
   chats: **não crie ferramenta de "busca entre cadernos"**, o escopo já resolve.
5. **Ferramenta que lê arquivo limita a própria saída** (D035) e diz onde parou. Uma
   ferramenta capaz de despejar 400 mil caracteres no contexto quebra o turno.
6. **Decisão nova, decisão registrada.** Toda decisão estrutural entra no
   `PROJETO.md` com status (DECIDIDO / PROPOSTO / ABERTO / REVERTIDO). Decisão
   revertida **não é apagada** — ela explica por que o caminho atual não é o óbvio.
   Marque os checkboxes da fase no mesmo commit da implementação.
7. **Se a operação tem um nome, ela tem um dono** (D037). "Apagar caderno" apaga as
   linhas *e* os arquivos *e* a conversa, numa função só. Não divida uma operação
   entre camadas: algum chamador vai vazar.

## Mapa

```
frutiger_lm/
  app.py            rotas FastAPI + lifespan (abre o checkpointer)
  db.py             SQLite: cadernos, fontes, outputs; contexto; migrações
  ingest.py         extração (PDF, URL, YouTube, texto)
  prompts.py        BASE_RULES + os 7 templates de output
  model_store.py    a chave da API e a config do modelo (data/model.json, 0600)
  engine/           A FRONTEIRA — só aqui entra LangChain
    llm.py            fábrica de modelo + tradução de erro do provedor
    fake.py           modelo falso, com paridade bloco/stream
    checkpoint.py     AsyncSqliteSaver; 1 caderno = 1 thread_id
    agent.py          o agente; prompt, catálogo, eventos e histórico —
                      `montar()` para um caderno, `montar_global()` para todos
    tools/leitura.py  listar_fontes, ler_fonte, buscar_nas_fontes — presas a um
                      `Escopo` (um caderno ou todos)
    tools/web.py      web_extract
  static/           UI vanilla (sem build). Se mexer no tema, o CSS é o único
                    lugar: os seletores são os mesmos desde antes.
                    `common.js` tem o `conversa()` — o chat do caderno e o dock da
                    home usam o MESMO, para não divergirem
```

## Como adicionar uma ferramenta

1. Escreva em `engine/tools/<área>.py` como uma factory que recebe o que ela precisa
   saber (o caderno, um provedor configurado) e devolve `list[BaseTool]`.
2. Escreva a **docstring como se fosse para o modelo ler** — é o schema que ele vê.
   Diga o que faz, quando usar e o que devolve.
3. Limite a saída. Se ela pode devolver muito texto, corte e diga onde parou.
4. Erro de uso vira **texto de retorno**, não exceção. O modelo precisa poder
   corrigir o rumo (ex.: "não existe fonte com esse id neste caderno").
5. Exponha em `agent.catalogo()` — ponto único de exposição. O catálogo pode
   crescer; o que se expõe por turno é curado (D025).
6. Teste: chamada direta **e** dentro do laço (`create_agent` com o fake).

## Armadilhas que custaram tempo

- **O `ingest` grava um cabeçalho `# Título` no arquivo da fonte.** Então `chars` e
  números de linha incluem esse cabeçalho. Se um teste afirmar "linha 2" contando o
  texto puro, ele está errado — não a ferramenta.
- **O DOM é a fonte da verdade, não o snapshot de acessibilidade.** `<strong>`
  aparece "vazio" no snapshot e o conteúdo está lá. Confira `innerHTML` antes de
  acusar bug de renderização.
- **O agente faz DUAS chamadas ao modelo** (a do tool call e a final). O texto
  chega em dois pedaços: o stream precisa emendar e o histórico precisa juntar, e
  os dois têm que dar o **mesmo** texto — senão a tela muda conforme o momento.
- **Chunk de conteúdo vazio é tool call, não texto.** É o que carrega
  `tool_call_chunks`. Filtrar, ou o front recebe delta vazio.
- **O `.env` contém a chave de API.** Não edite esse arquivo com uma ferramenta que
  imprime o diff — você vaza o segredo no próprio log. Use um script que reporte só
  nomes de chave.
- **Verifique o serviço de outra pessoa DEPOIS de mexer nele.** Reiniciar o app não
  deve alterar `MainPID` nem `NRestarts` de nada mais.
- **A saída estruturada depende do provedor, e o teste com fake NÃO pega isso**
  (D046). O default do `with_structured_output` (`json_schema`) tomou 400 na DeepSeek;
  `function_calling` também (modelo de raciocínio recusa `tool_choice` forçado);
  `json_mode` funciona, **mas o schema não chega** — o modelo só sabe o que o prompt
  disser, e sem o formato descrito ele inventa os nomes dos campos. Por isso o
  formato é gerado do Pydantic e vai no prompt. Se for trocar de provedor, meça os
  três métodos antes de supor.
- **Toda tabela nova precisa entrar na limpeza do `conftest`**, filhas antes das
  mães. Sem isso o estado vaza entre testes e o sintoma é um teste vendo o dado do
  anterior — foi assim que o grafo escapou, e antes a conversa.
- **Nunca abra uma conexão nova dentro de um `with connect()` aberto.** Trava no
  SQLite quando as duas escrevem. Extraia uma função que recebe a conexão (é o que
  `knowledge._ligar` faz).
- **`display: flex` vence o atributo `hidden`.** Um painel "escondido" que aparece é
  isso. Precisa da regra `.seletor[hidden] { display: none; }`.
- **O tema tinha o fundo preso ao viewport.** `background-attachment: fixed` no
  `body` + qualquer filho com `backdrop-filter` = o Chromium deixa de pintar aquele
  fundo no backdrop root, e a tela branca do navegador aparece. A cor-base (opaca)
  mora no `html`, e a aurora pertence ao documento.
- **Estático sem `cache-control` vira CSS velho depois de um `git pull`.** O
  sintoma é o pior possível: a correção está no disco, o servidor serve a nova, e a
  tela mostra a antiga — então o defeito parece ser do código que você acabou de
  escrever. O app manda `no-cache` em `/static` (revalidação por etag, 304 barato).

## Validar com o modelo real

Comportamento de LLM não é testável de forma determinística, então valide à parte —
mas **sem sujar os dados do usuário**:

```python
# caderno descartável, fonte grande o bastante para forçar o modo "files"
nb = db.create_notebook("zzz_prova")["id"]
await ingest.add_source(nb, kind="text", text=grande, title="Material")
...
db.delete_notebook(nb)                            # apaga linhas, arquivos
await checkpoints.apagar_conversa(nb)             # e a conversa
```

Confirme a limpeza no fim. E lembre-se: o que prova o motor é a **ferramenta sendo
chamada** — um caderno pequeno vai inteiro no prompt e o modelo responde sem
tocá-la.
