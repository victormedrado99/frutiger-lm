"""O passe de compilação: monta o DOCUMENTO a partir do material (F5).

A diferença entre este documento e um ensaio do modelo é de onde vem cada parte — e é
tudo o que importa aqui:

    de FATO (o grafo e o banco respondem)     de TEXTO (o modelo responde)
    ------------------------------------      --------------------------
    capa, sumário                             resumo
    conceitos do material                     desenvolvimento
    lacunas abertas
    fontes
    apêndice de citações

O modelo escreve a **ligação** entre as coisas — nunca os fatos. Toda seção que ele não
escreve é uma seção que ninguém pode inventar: os conceitos existem no grafo, cada um com
o trecho literal que o sustenta; as lacunas são uma consulta, não uma opinião; o apêndice
é a tabela `mentions` impressa, e a contagem dele bate com o banco (tem teste).

O documento sai como uma **lista de seções**, e não como um texto solto. É o que permite
o sumário sair dos títulos reais e o apêndice ser montado por último — sem depender de o
modelo ter cooperado com a forma do que escreveu. Cada seção carrega a própria
procedência (`origem`), para o documento poder dizer de onde veio o que afirma.

Uma chamada de modelo só. As partes de fato e de estrutura somam sozinhas a maior parte
do documento, e o texto corrido precisa ser um só: resumo e desenvolvimento escritos em
chamadas separadas saem com vozes diferentes e se repetem.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, Field

from .. import db, knowledge, study
from . import llm
from .extracao import METODO_ESTRUTURADO, descrever_formato

# Quantos trechos de origem cada conceito mostra na seção de conceitos. O apêndice
# mostra TODOS: aqui é para ler, lá é para conferir.
TRECHOS_POR_CONCEITO = 2

Emissor = Callable[[str, str], Awaitable[None]]


# --------------------------------------------------------------------------- #
# O documento e as seções
# --------------------------------------------------------------------------- #


@dataclass
class Secao:
    """Uma seção, com a procedência declarada.

    `origem` é o que impede o documento de mentir sobre si mesmo: "grafo" e "banco" são
    consulta, "modelo" é texto. Quem lê pode desconfiar do que quiser — desde que saiba
    de quem desconfiar.
    """

    nivel: int
    titulo: str
    corpo: str
    origem: str


@dataclass
class Documento:
    titulo: str
    notebook_id: str
    secoes: list[Secao] = field(default_factory=list)
    resumo_do_modelo: str = ""
    desenvolvimento: str = ""

    @property
    def tem_modelo(self) -> bool:
        return any(s.origem == "modelo" for s in self.secoes)

    def markdown(self) -> str:
        """O documento em Markdown, com o sumário já resolvido."""
        partes: list[str] = []
        for secao in self.secoes:
            partes.append("#" * secao.nivel + " " + secao.titulo)
            if secao.corpo.strip():
                partes.append("")
                partes.append(secao.corpo.strip())
            partes.append("")
        return "\n".join(partes).strip() + "\n"

    def contagem(self) -> dict[str, int]:
        """Quantas seções vieram de cada lugar. É a promessa do F5 em números."""
        conta = {"grafo": 0, "banco": 0, "modelo": 0}
        for secao in self.secoes:
            conta[secao.origem] = conta.get(secao.origem, 0) + 1
        return conta


# --------------------------------------------------------------------------- #
# As seções de FATO — nenhuma linha aqui passa por modelo
# --------------------------------------------------------------------------- #


def _capa(notebook: dict[str, Any], contagens: dict[str, int], fontes: list[dict]) -> Secao:
    """A capa: o que este documento é, em números deste caderno.

    As contagens vêm do RECORTE do caderno, e não do `estatisticas()` — que é global e
    diria "102 conceitos" num documento de um caderno entre dois. Número de capa errado
    é o tipo de erro que ninguém confere depois.
    """
    chars = sum(f["chars"] or 0 for f in fontes)
    corpo = "\n".join(
        [
            f"**Caderno:** {notebook['title']}",
            "",
            f"- {len(fontes)} fonte(s) — {chars:,} caracteres de material".replace(",", "."),
            f"- {contagens['conceitos_no_documento']} conceito(s) neste documento, "
            f"de {contagens['conceitos_no_caderno']} registrados "
            f"({contagens['passagem']} são menção de passagem)",
            f"- {contagens['mencoes']} menção(ões) com trecho de origem",
            f"- {contagens['arestas']} ligação(ões) entre os conceitos",
            "",
            "_Documento compilado pelo Frutiger LM. As seções de conceitos, lacunas, "
            "fontes e citações são consulta ao grafo — cada uma pode ser conferida na "
            "fonte, pelo trecho. As seções de texto são escritas pelo modelo a partir "
            "desse material._",
        ]
    )
    return Secao(1, notebook["title"], corpo, "banco")


def _conceitos(
    grafo: dict[str, Any], por_conceito: dict[str, list[dict[str, Any]]]
) -> list[Secao]:
    """Os conceitos do material, cada um com o trecho literal que o sustenta.

    Esta é a seção que faz o documento ser deste projeto e não de qualquer um: a lista
    não é o que o modelo achou importante, é o que o grafo registrou — e cada item vem
    com o trecho de origem, para quem quiser conferir.
    """
    secoes: list[Secao] = []
    for no in grafo["nodes"]:
        mencoes = por_conceito.get(no["id"]) or []
        if not mencoes:
            continue
        linhas = [f"*{no['mentions']} menção(ões) · {', '.join(no.get('notebooks') or [])}*", ""]
        for mencao in mencoes:
            trecho = " ".join((mencao.get("excerpt") or "").split())
            linhas.append(f"> {trecho}")
            linhas.append("")
            linhas.append(f"— {knowledge.origem_da_mencao(mencao)}")
            linhas.append("")
        secoes.append(Secao(3, no["name"], "\n".join(linhas).strip(), "grafo"))
    return secoes


def _lacunas(notebook_id: str) -> Secao:
    """O que o material cita e não explica — consulta, sem opinião de modelo (D049)."""
    buracos = knowledge.lacunas(notebook_id, limite=40)
    linhas: list[str] = []

    nao_desenvolvidos = buracos["nao_desenvolvidos"]
    if nao_desenvolvidos:
        linhas.append("### Citados e não explicados")
        linhas.append("")
        linhas.append(
            "O material nomeia estes conceitos e nunca os desenvolve. Estão aqui porque "
            "são exatamente o que falta estudar."
        )
        linhas.append("")
        for item in nao_desenvolvidos:
            linhas.append(f"- **{item['name']}**")

    em_outro = buracos["em_outro_caderno"]
    if em_outro:
        linhas.append("")
        linhas.append("### Desenvolvidos em outro caderno")
        linhas.append("")
        linhas.append(
            "Estudados em outro caderno seu e nunca citados aqui. É onde duas matérias "
            "se tocam sem que você tenha ligado uma na outra."
        )
        linhas.append("")
        for item in em_outro:
            linhas.append(f"- **{item['name']}** — aparece em {item.get('onde') or 'outro caderno'}")

    sem_contribuicao = buracos["fontes_sem_contribuicao"]
    if sem_contribuicao:
        linhas.append("")
        linhas.append("### Fontes que não deixaram nada")
        linhas.append("")
        linhas.append(
            "Estas fontes estão no caderno e não sustentam nenhum conceito registrado — "
            "vale conferir se são do assunto, ou se a extração precisa ser refeita."
        )
        linhas.append("")
        for fonte in sem_contribuicao:
            linhas.append(f"- {fonte['title']}")

    if not linhas:
        linhas.append("Nada registrado: todo conceito citado foi desenvolvido, e toda fonte contribuiu.")
    return Secao(2, "Lacunas abertas", "\n".join(linhas), "grafo")


def _fontes(fontes: list[dict], por_fonte: list[dict]) -> Secao:
    """O que cada fonte rendeu — e a que nunca foi citada (D051)."""
    citadas = study.fontes_usadas()
    rendimento = {linha["id"]: linha for linha in por_fonte}
    linhas = ["| # | Fonte | Tipo | Trechos | Conceitos | Vezes citada nas respostas |", "|---|---|---|---|---|---|"]
    for indice, fonte in enumerate(fontes, start=1):
        linha = rendimento.get(fonte["id"], {})
        linhas.append(
            f"| {indice} | {fonte['title']} | {fonte['kind']} | "
            f"{linha.get('mencoes', 0)} | {linha.get('conceitos', 0)} | "
            f"{citadas.get(fonte['id'], 0)} |"
        )
    linhas.append("")
    linhas.append(
        "**Trechos** é quantas menções a fonte sustenta; **conceitos**, quantos conceitos "
        "distintos ela cobre. Zero numa fonte do assunto costuma significar extração a "
        "refazer."
    )
    return Secao(2, "Fontes", "\n".join(linhas), "banco")


def _apendice(notebook_id: str) -> Secao:
    """Todas as menções do caderno, com fonte e trecho: a prova de cada afirmação.

    Agrupado por FONTE, e não por conceito, de propósito: a pergunta que se faz a um
    apêndice é "o que esta fonte disse?", e ela é diferente da pergunta da seção de
    conceitos ("o que sabemos sobre isto?").
    """
    mencoes = knowledge.mencoes_do_caderno(notebook_id)
    if not mencoes:
        return Secao(2, "Apêndice — citações", "Nenhuma menção registrada ainda.", "grafo")

    por_fonte: dict[str, list[dict[str, Any]]] = {}
    for mencao in mencoes:
        por_fonte.setdefault(mencao.get("fonte") or "sem fonte", []).append(mencao)

    linhas: list[str] = [
        f"{len(mencoes)} trechos, agrupados pela fonte de onde vieram. "
        "É a conferência: cada afirmação do documento tem um destes por trás.",
    ]
    for titulo, lista in por_fonte.items():
        linhas.append("")
        linhas.append(f"### {titulo} — {len(lista)} trecho(s)")
        for mencao in lista:
            trecho = " ".join((mencao.get("excerpt") or "").split())
            linhas.append("")
            linhas.append(f"- **{mencao['conceito']}**: “{trecho}”")
    return Secao(2, "Apêndice — citações", "\n".join(linhas), "grafo")


def sumario(secoes: list[Secao]) -> Secao:
    """O sumário, montado dos títulos REAIS das seções.

    Feito depois de o documento existir, e não antes: um sumário escrito à mão mente no
    dia em que uma seção mudar de nome, e ninguém percebe.
    """
    linhas = []
    for secao in secoes:
        if secao.nivel == 1:
            continue
        recuo = "  " * max(0, secao.nivel - 2)
        linhas.append(f"{recuo}- {secao.titulo}")
    return Secao(2, "Sumário", "\n".join(linhas) if linhas else "—", "grafo")


# --------------------------------------------------------------------------- #
# A seção de TEXTO — uma chamada de modelo
# --------------------------------------------------------------------------- #


class Narrativa(BaseModel):
    resumo: str = Field(
        description="Um parágrafo do que o material trata, citando as fontes como [n]."
    )
    desenvolvimento: str = Field(
        description=(
            "De 4 a 8 parágrafos ligando os conceitos entre si, citando as fontes como [n]. "
            "Use SOMENTE os conceitos e trechos fornecidos."
        )
    )


INSTRUCOES_NARRATIVA = """Você escreve as duas seções de texto de um documento compilado.

O documento já existe: as seções de conceitos, de lacunas, de fontes e de citações são
montadas a partir do grafo do caderno, com os trechos literais de origem. O seu papel é
escrever a LIGAÇÃO entre as coisas, não os fatos.

Regras que não se negociam:

- Use **somente** os conceitos e trechos fornecidos. Não acrescente conhecimento externo,
  nem "contexto" que não esteja ali. Se algo não está no material, não está no documento.
- Cite a fonte de cada afirmação como [n], usando a numeração da lista de fontes.
- O resumo diz do que o material trata e o que ele cobre. O desenvolvimento mostra como
  os conceitos se ligam: o que depende do quê, o que contrasta com o quê, o que é
  pré-requisito de quê.
- Se o material for raso em algum ponto, diga isso no próprio texto — não preencha com
  generalidade para parecer completo.
"""


def _mensagens_narrativa(
    notebook: dict[str, Any], fontes: list[dict], conceitos_com_trecho: list[tuple[str, list[dict]]]
) -> list[Any]:
    """O que o modelo recebe: as fontes numeradas e os conceitos COM os trechos.

    Ele não recebe o material bruto. Recebe o grafo — que é o material já conferido
    contra a fonte na extração. Isso é o documento compilado: o modelo escreve sobre o
    que foi registrado, e o que foi registrado tem lastro.
    """
    linhas = ["## Fontes (numere as citações por esta ordem)", ""]
    for indice, fonte in enumerate(fontes, start=1):
        linhas.append(f"[{indice}] {fonte['title']} ({fonte['kind']})")
    linhas.append("")
    linhas.append("## Conceitos do material, com o trecho literal de origem")
    for nome, mencoes in conceitos_com_trecho:
        linhas.append("")
        linhas.append(f"### {nome}")
        for mencao in mencoes:
            trecho = " ".join((mencao.get("excerpt") or "").split())
            linhas.append(f'- "{trecho}"')

    sistema = f"{INSTRUCOES_NARRATIVA}\n{descrever_formato(Narrativa)}"
    usuario = (
        f"Caderno: \"{notebook['title']}\".\n\n" + "\n".join(linhas) + "\n\n"
        "Escreva o resumo e o desenvolvimento deste documento."
    )
    # Import local de propósito: só o pacote `engine/` conhece o LangChain (D018), e o
    # resto do app não deve nem esbarrar na lib.
    from langchain_core.messages import HumanMessage, SystemMessage

    return [SystemMessage(sistema), HumanMessage(usuario)]


async def narrativa(
    notebook_id: str,
    grafo: dict[str, Any],
    *,
    modelo: Any = None,
    trechos: dict[str, list[dict[str, Any]]] | None = None,
) -> Narrativa:
    """A única chamada de modelo do documento."""
    notebook = db.get_notebook(notebook_id)
    if notebook is None:
        raise ValueError(f"caderno inexistente: {notebook_id}")
    fontes = db.list_sources(notebook_id, active_only=True)

    # Os conceitos que entram no prompt são os mesmos que o documento lista — com os
    # trechos que já foram conferidos contra a fonte na extração.
    por_id = trechos if trechos is not None else {}
    pares: list[tuple[str, list[dict]]] = []
    for no in grafo["nodes"]:
        lista = por_id.get(no["id"])
        if lista is None:
            lista = knowledge.mencoes(no["id"], limite=TRECHOS_POR_CONCEITO)
        if lista:
            pares.append((no["name"], lista))

    extrator = (modelo or llm.atual()).with_structured_output(
        Narrativa, method=METODO_ESTRUTURADO
    )
    resultado = await extrator.ainvoke(_mensagens_narrativa(notebook, fontes, pares))
    if isinstance(resultado, Narrativa):
        return resultado
    if isinstance(resultado, dict):
        return Narrativa(**resultado)
    return Narrativa(resumo="", desenvolvimento="")


# --------------------------------------------------------------------------- #
# O passe completo
# --------------------------------------------------------------------------- #


async def compilar(
    notebook_id: str,
    *,
    modelo: Any = None,
    emitir: Emissor | None = None,
    com_narrativa: bool = True,
) -> Documento:
    """Monta o documento: as seções de fato primeiro, o texto do modelo depois.

    A ordem de execução é essa porque o texto precisa dos conceitos, e não o contrário —
    e porque um documento sem a chamada de modelo ainda é útil (conceitos, lacunas,
    fontes e citações), enquanto um texto do modelo sem o grafo não é nada.

    `com_narrativa=False` monta só as seções de fato e **não gasta chamada nenhuma**:
    serve para ver a estrutura do documento antes de pagar por ela.

    `emitir` recebe (passo, mensagem) a cada etapa, para a tela poder acompanhar: a
    compilação tem uma chamada de rede no meio, e um botão que não diz nada por trinta
    segundos parece quebrado.
    """

    async def avisar(passo: str, mensagem: str) -> None:
        if emitir is not None:
            await emitir(passo, mensagem)

    notebook = db.get_notebook(notebook_id)
    if notebook is None:
        raise ValueError(f"caderno inexistente: {notebook_id}")

    await avisar("capa", "Lendo os metadados do caderno…")
    fontes = db.list_sources(notebook_id, active_only=True)
    grafo = knowledge.grafo(notebook_id=notebook_id, peso_minimo=1, apenas_principais=True)
    # A MESMA consulta do apêndice: a contagem da capa e a lista do fim saem do mesmo
    # lugar, então não têm como divergir.
    todas_as_mencoes = knowledge.mencoes_do_caderno(notebook_id)

    # Os trechos de cada conceito são lidos UMA vez e servem aos dois: à seção de
    # conceitos e ao prompt do modelo. Duas leituras dariam dois documentos com fontes
    # de verdade diferentes. E são só as menções DESTE caderno: um conceito-ponte
    # aparece aqui, mas o trecho dele de outro caderno não entra neste documento.
    por_conceito = {
        no["id"]: knowledge.mencoes(
            no["id"], limite=TRECHOS_POR_CONCEITO, notebook_id=notebook_id
        )
        for no in grafo["nodes"]
    }

    await avisar("conceitos", f"Montando {len(grafo['nodes'])} conceito(s) do grafo…")
    conceitos = _conceitos(grafo, por_conceito)

    await avisar("lacunas", "Levantando as lacunas (consulta, sem modelo)…")
    lacunas = _lacunas(notebook_id)

    await avisar("fontes", "Conferindo o que cada fonte rendeu…")
    fontes_secao = _fontes(fontes, knowledge.conceitos_por_fonte(notebook_id))

    # Uma chamada de modelo. Sem conceito no grafo não há sobre o que escrever, e o
    # documento sai só com o que é fato — o que é honesto, e não um erro.
    texto = Narrativa(resumo="", desenvolvimento="")
    if grafo["nodes"] and com_narrativa:
        await avisar("narrativa", "Escrevendo o resumo e o desenvolvimento…")
        texto = await narrativa(notebook_id, grafo, modelo=modelo, trechos=por_conceito)

    await avisar("apendice", "Listando todas as citações…")

    # A ORDEM DO DOCUMENTO, explícita. É a ordem de leitura, e não a de execução.
    contagens = {
        "conceitos_no_documento": len(grafo["nodes"]),
        "conceitos_no_caderno": len(grafo["nodes"]) + grafo.get("ocultos", 0),
        "passagem": grafo.get("ocultos", 0),
        "mencoes": len(todas_as_mencoes),
        "arestas": len(grafo["edges"]),
    }
    secoes: list[Secao] = [_capa(notebook, contagens, fontes)]
    if texto.resumo:
        secoes.append(Secao(2, "Resumo", texto.resumo, "modelo"))
    if conceitos:
        secoes.append(
            Secao(
                2,
                "Conceitos do material",
                "Os conceitos que o material desenvolve, cada um com o trecho de origem "
                "*literal* — conferido contra a fonte na extração. O que estiver aqui "
                "está dito no material, naquelas palavras.",
                "grafo",
            )
        )
        secoes.extend(conceitos)
    if texto.desenvolvimento:
        secoes.append(Secao(2, "Desenvolvimento", texto.desenvolvimento, "modelo"))
    secoes.append(lacunas)
    secoes.append(fontes_secao)
    secoes.append(_apendice(notebook_id))
    # O sumário entra agora, com os títulos reais, e logo depois da capa.
    secoes.insert(1, sumario(secoes))

    documento = Documento(
        titulo=notebook["title"],
        notebook_id=notebook_id,
        secoes=secoes,
        resumo_do_modelo=texto.resumo,
        desenvolvimento=texto.desenvolvimento,
    )
    await avisar("pronto", f"Documento pronto: {len(secoes)} seções.")
    return documento


# --------------------------------------------------------------------------- #
# Os outros formatos — o mesmo pipeline, outra saída
# --------------------------------------------------------------------------- #


def anki(notebook_id: str) -> str:
    """Os cartões do F4 no formato que o Anki importa.

    **Tab-separado**, e não CSV: é o que o Anki entende sem perguntar nada, e uma
    pergunta de verdade contém vírgula. As quebras de linha viram `<br>` porque no
    arquivo **uma linha é um cartão** — e o Anki lê HTML simples no verso.

    O verso leva o trecho de origem junto (D050): o cartão continua tendo a prova ao
    lado, também fora daqui.
    """
    cartoes = study.listar(notebook_id, limite=5000)
    if not cartoes:
        return ""
    linhas = []
    for cartao in cartoes:
        frente = " ".join(cartao["front"].split()).replace("\t", " ")
        verso = " ".join(cartao["back"].split()).replace("\t", " ")
        if cartao.get("excerpt"):
            trecho = " ".join(cartao["excerpt"].split())
            verso += f"<br><br><i>{trecho}</i>"
        linhas.append(f"{frente}\t{verso}")
    return "\n".join(linhas) + "\n"


def obsidian(notebook_id: str) -> str:
    """Os conceitos do caderno como notas ligadas por `[[wikilinks]]`.

    A diferença entre isto e um export qualquer: **a ligação sai das arestas que o
    material afirma**, e não de uma sugestão de proximidade. Se dois conceitos estão
    ligados aqui, é porque existe um trecho dizendo isso — e o trecho vai na nota.

    Cada conceito vira uma seção com o nome dele como título: no Obsidian, `[[Nome]]`
    resolve para um título, então as notas se ligam sozinhas ao entrar no cofre.
    """
    grafo = knowledge.grafo(notebook_id=notebook_id, peso_minimo=1, apenas_principais=True)
    if not grafo["nodes"]:
        return ""

    por_id = {no["id"]: no for no in grafo["nodes"]}
    ligacoes: dict[str, list[str]] = {}
    for aresta in grafo["edges"]:
        if aresta["kind"] != knowledge.EXPLICITA:
            continue
        a = por_id.get(aresta["a_id"])
        b = por_id.get(aresta["b_id"])
        if a is None or b is None:
            continue
        ligacoes.setdefault(a["id"], []).append(b["name"])
        ligacoes.setdefault(b["id"], []).append(a["name"])

    titulo = db.get_notebook(notebook_id)
    linhas = [
        f"# {titulo['title'] if titulo else notebook_id}",
        "",
        "Conceitos ligados pelo que o material afirma. Cada ligação tem um trecho por trás.",
        "",
    ]
    for no in grafo["nodes"]:
        linhas.append(f"## {no['name']}")
        linhas.append("")
        mencoes = knowledge.mencoes(no["id"], limite=TRECHOS_POR_CONCEITO, notebook_id=notebook_id)
        for mencao in mencoes:
            trecho = " ".join((mencao.get("excerpt") or "").split())
            linhas.append(f"> {trecho}")
            linhas.append("")
        vizinhos = sorted(set(ligacoes.get(no["id"], [])))
        if vizinhos:
            linhas.append("Ligações: " + ", ".join(f"[[{nome}]]" for nome in vizinhos))
            linhas.append("")
        for nota in knowledge.notas_do_conceito(no["id"]):
            linhas.append(f"> [!note] {nota['body'].strip()}")
        linhas.append("")
    return "\n".join(linhas).strip() + "\n"
