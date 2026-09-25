"""Os dois usos de modelo do F4: compor cards e achar contradições.

Tudo o mais no painel de estudo é consulta ao grafo e não custa nada. Aqui é onde
custa chamada de modelo, e por isso as duas coisas são **ação explícita** (D042) e
aparecem com progresso na tela.

As duas compartilham a regra herdada do F3:

    o modelo pode propor, mas não pode afirmar o que não tem lastro.

- O card nasce de um trecho que já está no grafo e **validado contra a fonte**. O
  modelo só compõe a pergunta; o verso continua sendo o material.
- A contradição só entra se o modelo citar **os dois lados**, e os dois trechos são
  conferidos contra o que foi oferecido a ele. Sem as duas citações, é descartada.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from pydantic import BaseModel, Field

from .. import db, knowledge, study
from . import llm
from .extracao import METODO_ESTRUTURADO, descrever_formato

# --------------------------------------------------------------------------
# Compor a pergunta de um card
# --------------------------------------------------------------------------


class CardProposto(BaseModel):
    pergunta: str = Field(description="Uma pergunta curta e específica sobre o conceito.")
    resposta: str = Field(
        description=(
            "A resposta em uma ou duas frases, usando SOMENTE o que o trecho diz. "
            "Se o trecho não responder, escreva exatamente: não está no material."
        )
    )


INSTRUCOES_CARD = """Você escreve cartões de estudo a partir de um trecho de material.

Regras:
1. A pergunta tem que se sustentar SOZINHA: quem lê precisa saber de que conceito se
   trata sem ter o material à vista. Nomeie o conceito na pergunta.
   Errado: "Qual é o primeiro campo?" — o primeiro campo de quê?
   Certo: "No quadro CAN, qual é o primeiro campo?"
2. A resposta usa SOMENTE o que o trecho afirma. Não complete com o que você sabe
   sobre o assunto: se o trecho não responde, escreva exatamente: não está no material.
3. Nada de "segundo o texto" ou "o trecho diz": o cartão tem que funcionar sozinho.
4. Pergunta e resposta no mesmo idioma do material.
"""


# Quando o modelo devolve isto, é porque o trecho não responde — e aí não há cartão.
# Aconteceu no material real: 3 de 12 cartões nasceram com esta resposta e iam para a
# fila de revisão como se ensinassem alguma coisa.
SEM_RESPOSTA = ("não está no material", "nao esta no material", "não consta no material")


def vale_a_pena(proposto: CardProposto) -> tuple[bool, str]:
    """O cartão tem pergunta e resposta de verdade?

    Separado da criação de propósito: a regra fica testável e o motivo do descarte
    fica visível na tela, em vez de virar um cartão vazio que ninguém entende.
    """
    if not proposto.pergunta.strip():
        return False, "sem pergunta"
    resposta = proposto.resposta.strip().casefold()
    if not resposta:
        return False, "sem resposta"
    if any(frase in resposta for frase in SEM_RESPOSTA):
        return False, "o trecho não responde ao conceito"
    return True, ""


def _mensagens_card(conceito: str, trecho: str, contexto: str) -> list[Any]:
    from langchain_core.messages import HumanMessage, SystemMessage

    sistema = INSTRUCOES_CARD + "\n\n" + descrever_formato(CardProposto)
    pedido = (
        f"Conceito: {conceito}\n\n"
        f"Trecho do material que menciona o conceito:\n\n{trecho}"
    )
    if contexto:
        pedido += f"\n\nO mesmo conceito também aparece assim:\n\n{contexto}"
    return [SystemMessage(sistema), HumanMessage(pedido)]


async def propor_card(
    conceito: dict[str, Any], trechos: list[str], *, modelo: Any = None
) -> CardProposto:
    """Uma pergunta e uma resposta a partir do que o material diz do conceito."""
    if not trechos:
        raise ValueError("Sem trecho não há card: o verso tem que ter lastro")

    extrator = (modelo or llm.atual()).with_structured_output(
        CardProposto, method=METODO_ESTRUTURADO
    )
    resultado = await extrator.ainvoke(
        _mensagens_card(conceito["name"], trechos[0], trechos[1] if len(trechos) > 1 else "")
    )
    if isinstance(resultado, CardProposto):
        return resultado
    return CardProposto(**resultado) if isinstance(resultado, dict) else CardProposto(
        pergunta="", resposta=""
    )


async def gerar_cards(
    notebook_id: str, *, modelo: Any = None, limite: int = 12
) -> AsyncIterator[dict[str, Any]]:
    """Gera cards para os conceitos que ainda não têm nenhum.

    A ordem de prioridade vem das lacunas: **conceito nomeado e não desenvolvido
    primeiro**. É onde a pessoa viu o termo e não sabe o que ele é — exatamente o que
    um card resolve. Depois os conceitos mais mencionados que ainda não têm card.
    """
    ja_tem = {c["concept_id"] for c in study.listar(notebook_id) if c.get("concept_id")}

    lacuna = knowledge.lacunas(notebook_id)
    fila: list[dict[str, Any]] = list(lacuna["nao_desenvolvidos"])

    vistos = {c["id"] for c in fila}
    for no in knowledge.grafo(notebook_id=notebook_id, peso_minimo=1)["nodes"]:
        if no["id"] not in vistos:
            vistos.add(no["id"])
            fila.append(no)

    alvos = [c for c in fila if c["id"] not in ja_tem][:limite]
    yield {"evento": "cards.plano", "alvos": len(alvos), "ja_tinham": len(ja_tem)}

    criados = 0
    for indice, conceito in enumerate(alvos, start=1):
        mencoes = knowledge.mencoes(conceito["id"])
        trechos = [m["excerpt"] for m in mencoes[:2]]
        if not trechos:
            continue

        try:
            proposto = await propor_card(conceito, trechos, modelo=modelo)
        except Exception as exc:  # noqa: BLE001 — a mensagem vai para a tela
            yield {
                "evento": "error",
                "message": f"{type(exc).__name__}: {exc}{llm.explicar(exc)}",
            }
            return

        if not proposto.pergunta.strip():
            yield {
                "evento": "cards.item",
                "indice": indice,
                "total": len(alvos),
                "conceito": conceito["name"],
                "criado": False,
                "motivo": "o modelo não propôs pergunta",
            }
            continue

        # Cartão sem resposta não é cartão: o trecho não respondia, o modelo disse
        # isso, e criar assim mesmo só encheria a fila de revisão de nada.
        serve, motivo = vale_a_pena(proposto)
        if not serve:
            yield {
                "evento": "cards.item",
                "indice": indice,
                "total": len(alvos),
                "conceito": conceito["name"],
                "criado": False,
                "motivo": motivo,
            }
            continue

        # O card nasce com o trecho ao lado: é o que o torna conferível.
        primeira = mencoes[0]
        card = study.criar_card(
            notebook_id,
            front=proposto.pergunta,
            back=proposto.resposta,
            concept_id=conceito["id"],
            source_id=primeira.get("source_id"),
            excerpt=primeira["excerpt"],
        )
        criados += 1
        yield {
            "evento": "cards.item",
            "indice": indice,
            "total": len(alvos),
            "conceito": conceito["name"],
            "criado": True,
            "card_id": card["id"],
        }

    yield {"evento": "cards.done", "criados": criados, "alvos": len(alvos), **study.resumo(notebook_id)}


# --------------------------------------------------------------------------
# Contradições entre fontes
# --------------------------------------------------------------------------


class Contradicao(BaseModel):
    ha_conflito: bool = Field(description="true somente se as duas fontes se contradizem.")
    lado_a: str = Field(
        default="", description="Trecho LITERAL de uma das fontes, copiado exatamente."
    )
    lado_b: str = Field(
        default="", description="Trecho LITERAL DA OUTRA fonte que conflita com o primeiro."
    )
    explicacao: str = Field(default="", description="Em uma frase, o que conflita.")


INSTRUCOES_CONFLITO = """Você compara como duas ou mais fontes tratam o MESMO conceito.

Regras:
1. Só há conflito quando as fontes afirmam coisas que NÃO PODEM ser verdadeiras ao mesmo
   tempo. Diferença de ênfase, de detalhe ou de nível de profundidade NÃO é conflito.
2. Se houver conflito, copie LITERALMENTE um trecho de cada lado. Os trechos são
   conferidos contra o material: um trecho que não existir derruba a resposta inteira.
3. Se não houver conflito, responda ha_conflito como false e deixe os trechos vazios.
   "Não achei conflito" é a resposta mais comum e está certa."""


def _mensagens_conflito(conceito: str, lados: list[dict[str, Any]]) -> list[Any]:
    from langchain_core.messages import HumanMessage, SystemMessage

    sistema = INSTRUCOES_CONFLITO + "\n\n" + descrever_formato(Contradicao)
    corpo = "\n\n".join(
        f'Fonte "{lado["fonte"]}":\n{lado["trecho"]}' for lado in lados
    )
    return [
        SystemMessage(sistema),
        HumanMessage(f'Conceito: {conceito}\n\n{corpo}'),
    ]


async def _explicar_lados(conceito: str, lados: list[dict[str, Any]], *, modelo: Any = None) -> Contradicao:
    extrator = (modelo or llm.atual()).with_structured_output(
        Contradicao, method=METODO_ESTRUTURADO
    )
    resultado = await extrator.ainvoke(_mensagens_conflito(conceito, lados))
    if isinstance(resultado, Contradicao):
        return resultado
    return Contradicao(**resultado) if isinstance(resultado, dict) else Contradicao(ha_conflito=False)


def conferir_lados(conflito: Contradicao, lados: list[dict[str, Any]]) -> tuple[bool, str]:
    """A contradição só vale se os dois lados vierem de FONTES DIFERENTES e existirem.

    Cada lado é conferido contra o trecho da fonte que ele diz citar. Sem os dois, a
    contradição é descartada — do mesmo jeito que o trecho inventado na extração. É
    esta checagem que separa "o material se contradiz" de "o modelo achou que sim".
    """
    if not conflito.ha_conflito:
        return False, "sem conflito"

    def fonte_do_trecho(trecho: str) -> str | None:
        for lado in lados:
            if knowledge.trecho_existe(trecho, lado["trecho"]):
                return str(lado["fonte"])
        return None

    fonte_a = fonte_do_trecho(conflito.lado_a)
    fonte_b = fonte_do_trecho(conflito.lado_b)

    if not fonte_a or not fonte_b:
        return False, "o trecho citado não existe na fonte"
    if fonte_a == fonte_b:
        return False, "os dois lados vieram da mesma fonte"
    return True, f"{fonte_a} ↔ {fonte_b}"


def _conceitos_em_mais_de_uma_fonte(notebook_id: str) -> list[dict[str, Any]]:
    """Só vale comparar onde há o que comparar: o conceito em 2+ fontes deste caderno."""
    with db.connect() as conn:
        return [
            dict(linha)
            for linha in conn.execute(
                """SELECT c.id, c.name, COUNT(DISTINCT m.source_id) AS fontes
                   FROM concepts c
                   JOIN mentions m ON m.concept_id = c.id
                   WHERE m.notebook_id = ? AND m.source_id IS NOT NULL
                   GROUP BY c.id
                   HAVING COUNT(DISTINCT m.source_id) > 1
                   ORDER BY fontes DESC, c.name""",
                (notebook_id,),
            )
        ]


async def detectar_contradicoes(
    notebook_id: str, *, modelo: Any = None, limite: int = 10
) -> AsyncIterator[dict[str, Any]]:
    """Compara, conceito a conceito, o que duas ou mais fontes dizem (D050).

    Uma chamada por conceito, e não por par de fontes: quase todo par não tem o que
    comparar, e percorrer todos eles seria caro e quase sempre vazio.
    """
    candidatos = _conceitos_em_mais_de_uma_fonte(notebook_id)[:limite]
    yield {"evento": "conflitos.plano", "candidatos": len(candidatos)}

    achadas = 0
    for indice, conceito in enumerate(candidatos, start=1):
        por_fonte: dict[str, str] = {}
        for mencao in knowledge.mencoes(conceito["id"], limite=40):
            if mencao.get("source_id") and mencao["notebook_id"] == notebook_id:
                por_fonte.setdefault(mencao["source_id"], mencao["excerpt"])

        lados = []
        for sid, trecho in por_fonte.items():
            fonte = db.get_source(sid)
            if fonte:
                lados.append({"fonte": fonte["title"], "trecho": trecho, "source_id": sid})
        if len(lados) < 2:
            continue

        try:
            conflito = await _explicar_lados(conceito["name"], lados, modelo=modelo)
        except Exception as exc:  # noqa: BLE001 — a mensagem vai para a tela
            yield {
                "evento": "error",
                "message": f"{type(exc).__name__}: {exc}{llm.explicar(exc)}",
            }
            return

        vale, motivo = conferir_lados(conflito, lados)
        if vale:
            achadas += 1

        yield {
            "evento": "conflitos.item",
            "indice": indice,
            "total": len(candidatos),
            "conceito": conceito["name"],
            "conflito": vale,
            "motivo": motivo,
            **(
                {
                    "lado_a": conflito.lado_a,
                    "lado_b": conflito.lado_b,
                    "explicacao": conflito.explicacao,
                }
                if vale
                else {}
            ),
        }

    yield {"evento": "conflitos.done", "achadas": achadas, "examinados": len(candidatos)}
