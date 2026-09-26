# AGENTS.md — como mexer neste repositório

Guia para quem for trabalhar no Frutiger LM (pessoa ou agente). O **`PROJETO.md` é
a fonte da verdade sobre decisões** — este arquivo é o atalho operacional. Se os
dois divergirem, o PROJETO.md ganha.

## O que é

App de estudo com fontes próprias: você joga PDF/link/YouTube/texto, conversa com
o material, gera documentos, e (a partir do F3) constrói um grafo de conhecimento
ancorado nas fontes. É do grafo (F5) que sai o **documento compilado**: conceitos com
o trecho literal de origem, lacunas e apêndice de citações, com só duas seções escritas
pelo modelo. FastAPI + SQLite + UI vanilla, sem build. O agente é um grafo LangGraph que
vive **dentro** do app — não há motor externo.

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
  knowledge.py      a loja do grafo: conceitos, menções, arestas, lacunas
  study.py          cartões e o SRS, lógica pura (sem modelo)
  engine/           A FRONTEIRA — só aqui entra LangChain
    llm.py            fábrica de modelo + tradução de erro do provedor
    fake.py           modelo falso, com paridade bloco/stream (e `pausa`)
    checkpoint.py     AsyncSqliteSaver; 1 caderno = 1 thread_id
    agent.py          o agente; prompt, catálogo, eventos e histórico —
                      `montar()` para um caderno, `montar_global()` para todos
    extracao.py       conceitos a partir de um texto (F3)
    estudo.py         o card a partir do conceito e a comparação entre fontes (F4)
    artefato.py       o passe de compilação do documento (F5), em lista de seções
    oficina.py        os artefatos EM CONSTRUÇÃO: run com id, fora do turno (D059)
    tools/leitura.py  listar_fontes, ler_fonte, buscar_nas_fontes — presas a um
                      `Escopo` (um caderno ou todos)
    tools/web.py      web_extract
    tools/grafo.py    as ferramentas do grafo (globais, D045)
    tools/estudo.py   lacunas e cards (presas ao caderno)
    tools/artefatos.py compilar_documento — dispara o run e devolve o id (D060)
  static/           UI vanilla (sem build). Se mexer no tema, o CSS é o único
                    lugar: os seletores são os mesmos desde antes.
                    `common.js` tem o `conversa()` — o chat do caderno e o dock da
                    home usam o MESMO, para não divergirem
                    `imprimir.html` + `imprimir.css` são a folha de papel (F5):
                    tema CLARO, porque o Aero escuro imprime ilegível
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
- **O modelo pode ser honesto e o código estragar a honestidade.** Pedimos ao extrator
  de cartões que escrevesse "não está no material" quando o trecho não respondesse — e
  ele escreveu, corretamente, em 3 de 12 casos. O código criava o cartão assim mesmo,
  e a fila de revisão enchia de cartões sem resposta. **Antes de guardar a saída do
  modelo, pergunte se ela é guardável**: `vale_a_pena()` existe por isso.
- **Pergunta de cartão tem que nomear o conceito.** "Qual é o primeiro campo?" não
  ensina nada: o primeiro campo *de quê?* Um cartão ambíguo é pior que nenhum, porque
  a pessoa marca "bom" sem ter recuperado coisa alguma.
- **`display: flex` ganha de `[hidden]`.** Uma classe vence o atributo na
  especificidade, então todo painel escondido com `hidden` precisa de um
  `[hidden] { display: none }` explícito. Já custou tempo duas vezes (o painel do
  conceito e as abas da barra lateral).
- **Um `<canvas>` tem largura INTRÍNSECA** (o atributo `width`, que o desenho define
  como a largura de tela). Como item flex ele nasce com `min-width: auto` = o
  min-content, então **inflava a barra lateral** de 400 para ~482px — e como a barra
  maior dava um canvas maior, que dava uma barra maior, ela crescia sozinha a cada
  desenho. A cura é `min-width: 0` no item flex.
- **A forma do grafo vinha do `clamp` do quadro**, não da física: a repulsão empurrava
  os nós até a borda e eles ficavam ali, então o desenho era retangular. Foi trocar o
  clamp por gravidade + repulsão que produziu o círculo. **Medido**: o raio por setor
  angular (24 setores) caiu de 60% de variação para 6%.
- **Contar rótulos não evita sobreposição.** Num grafo em círculo os dez conceitos
  mais mencionados ficam todos no miolo, e um teto de dez rótulos põe exatamente esses
  dez um em cima do outro. A decisão tem que ser por **caixa de colisão**, com folga
  generosa (18px de altura para uma linha de 11px) — e o texto desenhado numa passada
  final, para nenhum nó passar por cima.
- **Clique e arraste se confundiam.** A checagem era `Math.abs(vx) < 1` no `mouseup`,
  e nunca falhava: o arraste zera a velocidade a cada movimento, então todo arraste
  abria o conceito. O que decide é a distância percorrida desde o `mousedown`.
- **Conceito DO material = aparece 2+ vezes, ou atravessa cadernos (D054).** É o que o
  desenho mostra. **O banco continua guardando todos**, porque os de passagem são o
  que as lacunas do F4 usam — cortar na extração seria irreversível e custaria uma
  funcionalidade para resolver um problema de desenho. Filtre na vista, não no dado.
- **`max-width` num item flex que devia encostar na borda é um vazio fantasma.** Numa
  janela larga o item para onde o teto manda e todo o espaço restante fica DEPOIS dele:
  a barra parecia "presa no meio" com 340px de nada à direita. O teto tem que ir no
  conteúdo (ou em nada), nunca na caixa que precisa alcançar a borda. **Meça em 1280,
  1920 e 2560** — o defeito só aparece na janela grande, e é onde o usuário está.
- **Nada se redimensiona sozinho.** Se um canvas (ou qualquer coisa com tamanho
  calculado) não escuta o `resize`, ele fica com o tamanho de quando nasceu e desenha
  para uma caixa que já não existe. Com espera de ~140ms, senão o arraste da janela
  recompõe a simulação dezenas de vezes por segundo.
- **O desenho não sabe em que escopo está — e não deve adivinhar.** Um conceito-ponte
  pertence a dois cadernos NO BANCO (é verdade), então ao desenhar só um caderno o
  código achava que havia duas ilhas: abria dois rótulos, sendo que um deles nem estava
  na vista. Quem sabe o escopo é a interface, e ela é que diz (`cadernoFoco`).
  **Regra geral: o que a tela sabe, a tela passa; o desenho não deduz do dado.**
- **Um conceito não pertence a um caderno — ele vive nas MENÇÕES.** Apagar o caderno
  leva as menções pelo cascade e deixa o NOME: um conceito invisível, inalcançável, que
  não passa pelo corte dos "principais" mas suja toda contagem (`estatisticas`,
  `ocultos`, `vocabulario`). Apareceu como "76 ocultos" onde deviam ser 72.
  `delete_notebook` recolhe o que ficou sem menção nenhuma.
- **`dispatchEvent` NÃO faz hit-test — ele não prova que um clique funciona.** Disparar
  `mousedown`/`mouseup` direto no canvas passou por cima de um `div` invisível que cobria
  o quadro inteiro e engolia todo clique de verdade. O teste "passava" e o app estava
  morto ao toque. Para testar clique, testes dois: **`document.elementFromPoint(x, y)`**
  diz quem o navegador escolheria (é o mesmo hit-test que ele usa), e o evento deve ser
  disparado **nesse** elemento, com `bubbles: true` — não no alvo que você espera.
- **`hidden` vs `display`: use a regra GLOBAL, nunca a pontual.** `[hidden] { display:
  none !important; }` uma vez, no topo do CSS. Este defeito voltou QUATRO vezes (painel do
  conceito, rótulo do filtro, `.lateral-painel`, e por fim o aviso de grafo vazio — que
  tinha `position: absolute` sobre o canvas e matou o clique). Cada correção pontual
  resolvia um caso e deixava o próximo. Se algum dia parecer que precisa de
  `.alguma-coisa[hidden]`, a resposta é não precisa.
- **A área de acerto tem que bater com o que o OLHO vê.** A bolha tem halo maior que o
  raio: quem mira na borda visível mira fora do círculo. E o rótulo é o pedaço maior e
  mais óbvio do conjunto — clicar no nome e não acontecer nada é o que faz parecer
  quebrado. Alvo generoso (`raio * 1.35 + 6`) **mais** a caixa do rótulo.
- **Vários sintomas visuais ao mesmo tempo? Suspeite do CONTRATO, não do desenho.**
  No mapa de cadernos eu nomeei o campo `cadernos`; o desenho lê `notebooks`. Um nome
  errado produziu três defeitos que não parecem ter a mesma causa: nós **cinzas**
  (fallback de cor), os nós **colados no centro** (sem ilha, todos para o mesmo ponto) e
  **um rótulo sumido** (a colisão de caixa derrubou o segundo, sobreposto ao primeiro).
  Quando o desenho se comporta como se não tivesse dado, o problema costuma estar no
  nome do que ele lê — confira a chave antes de mexer na geometria.
- **`registrar_mencao` deduplica** menção idêntica (mesmo conceito + fonte + trecho).
  Repetir a mesma frase N vezes dá UMA menção — o que importa ao montar dado de teste à
  mão: para um conceito ter 2 menções, são precisos 2 trechos diferentes.
- **O fake que responde sem devolver o controle ao laço esconde o defeito que você quer
  testar.** Sem pausa, o extrator falso responde sem nenhum `await` que ceda o laço — e a
  compilação inteira (uma chamada de modelo inclusa) termina **num passo só do
  agendador**. O teste da ferramenta que "dispara e sai de cena" passava a ver o documento
  pronto no instante seguinte ao disparo e acusava o OPOSTO do que ele queria provar. Use
  `fake.extrai([...], pausa=0.05)`: é o que dá ao teste o mesmo mundo que a produção tem.
- **Caderno de teste sem conceito "principal" não gera documento narrativo.** O corte da
  D054 (2+ menções) é aplicado antes da chamada de modelo, então um caderno de teste com
  uma menção por conceito faz o passe **pular o modelo** — e aí o teste que devia provar
  "o documento é escrito pelo modelo" prova outra coisa, em silêncio. Monte o dado de
  teste com dois trechos por conceito.
- **Disparar e acompanhar são dois verbos (D059).** `POST /compilar` devolve o run e
  volta; seguir é `GET /api/artefatos/{run_id}`. A tela tem UM caminho de acompanhar, e o
  vigia que pergunta por compilação em curso existe por um motivo estreito: uma
  compilação disparada **pelo chat** nasce sem que a aba saiba. Se você criar um segundo
  caminho de acompanhamento (um POST que transmite, por exemplo), o do chat é o que vai
  ser esquecido na primeira mudança.
- **Abrir um run no meio não perde passo, e isso é do `acompanhar`.** O gerador entrega o
  histórico **antes** de entrar na fila. Se você mexer nele, mantenha essa ordem: sem ela
  o painel que chega atrasado mostra uma caixa vazia e parece que a compilação travou.

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
