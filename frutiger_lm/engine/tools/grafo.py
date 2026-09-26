"""Ferramentas do grafo de conhecimento (F3, D027).

Duas de leitura e uma de escrita, e a superfície é pequena de propósito (D025):
o agente precisa achar um conceito, ver o que se liga a ele **com o trecho que
sustenta a ligação**, e poder afirmar uma relação nova com fundamento.

Uma decisão que vale registrar: estas ferramentas são **globais**, sem escopo. As
de leitura são presas ao caderno (D034), mas o grafo é a camada de cima — é
justamente ele que liga um caderno ao outro, e onde um conceito aparece em dois
cadernos é a informação mais interessante que ele tem. Restringir o grafo ao
caderno esconderia isso. E toda menção diz de qual caderno veio, então nada fica
sem procedência.

A exceção é a ferramenta do F6, `ligar_por_similaridade`, que vem presa ao caderno:
ela embeda e liga os conceitos de UM caderno, e sem saber qual não há o que fazer.
"""

from __future__ import annotations

from typing import Any

from langchain_core.tools import BaseTool, tool

from ... import db, knowledge
from .. import embed, oficina

LIMITE_CONCEITOS = 15
LIMITE_VIZINHOS = 25
LIMITE_TRECHO = 220


def _recorte(texto: str, limite: int = LIMITE_TRECHO) -> str:
    limpo = " ".join(str(texto or "").split())
    return limpo if len(limpo) <= limite else limpo[: limite - 1] + "…"


def _onde_aparece(conceito: dict[str, Any]) -> str:
    mencoes = knowledge.mencoes(conceito["id"], limite=6)
    if not mencoes:
        return "  (sem menção registrada)"
    linhas = []
    for mencao in mencoes:
        linhas.append(
            f'   · {knowledge.origem_da_mencao(mencao)} '
            f'(caderno "{mencao.get("notebook_title", "?")}"): "{_recorte(mencao["excerpt"])}"'
        )
    return "\n".join(linhas)


def ferramentas_de_grafo() -> list[BaseTool]:
    """As três ferramentas de grafo, presas a nada — o grafo é global."""

    @tool
    def buscar_no_grafo(termo: str) -> str:
        """Procura conceitos no grafo de conhecimento e diz onde cada um aparece.

        Use antes de `vizinhanca_do_conceito`: é aqui que você descobre o nome exato
        do conceito e em quais cadernos ele já foi registrado.
        """
        if not (termo or "").strip():
            return "Informe um termo para buscar."

        achados = knowledge.buscar(termo, limite=LIMITE_CONCEITOS)
        if not achados:
            total = knowledge.estatisticas()["conceitos"]
            if total == 0:
                return (
                    "O grafo está vazio: nenhum conceito foi extraído ainda. "
                    "A pessoa pode extrair pelo botão no caderno."
                )
            return (
                f'Nada no grafo para "{termo}". Há {total} conceito(s) registrado(s) — '
                "tente outro termo, ou a pessoa pode extrair de novo pelo caderno."
            )

        linhas = [f'{len(achados)} conceito(s) no grafo para "{termo}":', ""]
        for conceito in achados:
            onde = ", ".join(conceito.get("notebooks") or [])
            pontes = " (em mais de um caderno)" if conceito.get("ponte") else ""
            linhas.append(
                f"- {conceito['name']} · {conceito['mentions']} menção(ões)"
                + (f" · cadernos: {onde}" if onde else "")
                + pontes
            )
        return "\n".join(linhas)

    @tool
    def vizinhanca_do_conceito(conceito: str) -> str:
        """O que se liga a este conceito, com o trecho que sustenta cada ligação.

        É a ferramenta que responde "com o que isso se relaciona?" **a partir do
        que já foi registrado**, e não de memória. As ligações vêm em três famílias,
        e a diferença importa para o que você pode afirmar:

        - `afirmada` — o material disse, e há trecho de origem. É a única que você
          pode apresentar como afirmação do material;
        - `co-ocorrência` — os dois apareceram juntos no mesmo trecho do material;
        - `igual a`/`parecido` (similaridade) — **inferida** pelo app a partir dos
          vetores, sem trecho nenhum. Diga que é uma aproximação, nunca uma afirmação.
        """
        if not (conceito or "").strip():
            return "Informe o conceito."

        exato = knowledge.buscar(conceito, limite=1)
        if not exato:
            return (
                f'"{conceito}" não está no grafo. Use `buscar_no_grafo` para ver o que '
                "existe — e não invente um conceito: o grafo só tem o que foi extraído "
                "do material da pessoa."
            )

        dado = knowledge.vizinhanca(exato[0]["id"])
        if not dado:
            return f'"{conceito}" não está no grafo.'

        alvo = dado["concept"]
        cadernos = sorted({m.get("notebook_title", "?") for m in dado["mentions"]})
        linhas = [
            f'{alvo["name"]} · {len(dado["mentions"])} menção(ões) · '
            f'cadernos: {", ".join(cadernos) or "nenhum"}',
            "",
        ]

        afirmadas = [v for v in dado["neighbors"] if v["kind"] == knowledge.EXPLICITA]
        inferidas = [v for v in dado["neighbors"] if v["kind"] == knowledge.SIMILARIDADE]
        coocorrencia = [v for v in dado["neighbors"] if v["kind"] == knowledge.CO_OCORRENCIA]

        if afirmadas:
            linhas.append(f"Ligações afirmadas pelo material ({len(afirmadas)}):")
            for vizinho in afirmadas[:LIMITE_VIZINHOS]:
                origem = _recorte(vizinho["provenance"], 200)
                linhas.append(f'- {vizinho["concept"]["name"]} — {origem}')
            linhas.append("")

        if inferidas:
            # A nota vai junto porque é ela que a pessoa (e o modelo) podem ponderar:
            # 0,81 e 0,96 são coisas bem diferentes quando o assunto é "parece o mesmo".
            nomes = ", ".join(
                f'{v["concept"]["name"]} ({float(v.get("score") or 0):.2f})'
                for v in inferidas[:LIMITE_VIZINHOS]
            )
            linhas.append(
                f"Parecidos por similaridade ({len(inferidas)}) — **inferido pelo app a "
                f"partir dos vetores, sem trecho que sustente**: {nomes}"
            )
            linhas.append("")

        if coocorrencia:
            nomes = ", ".join(
                f'{v["concept"]["name"]} ({v["weight"]}x)' for v in coocorrencia[:LIMITE_VIZINHOS]
            )
            linhas.append(
                f"Aparecem no mesmo trecho do material ({len(coocorrencia)}), sem "
                f"relação afirmada: {nomes}"
            )
            linhas.append("")

        if not dado["neighbors"]:
            linhas.append(
                "Nada ligado a este conceito ainda. O material menciona o conceito, "
                "mas não o relaciona a outro — e o grafo não inventa ligação."
            )
            linhas.append("")

        linhas.append("Onde aparece:")
        linhas.append(_onde_aparece(alvo))
        return "\n".join(linhas)

    @tool
    def registrar_relacao(de: str, para: str, trecho: str, fonte_id: str) -> str:
        """Registra no grafo uma relação que o material AFIRMA entre dois conceitos.

        Os dois conceitos já precisam existir no grafo (use `buscar_no_grafo` para os
        nomes). O `trecho` tem que ser **literal** de uma das fontes, e o `fonte_id`
        diz de qual — o trecho é conferido contra a fonte, e um trecho que não existir
        é recusado. Só registre o que o material afirma; semelhança de assunto não é
        relação.
        """
        fonte = db.get_source((fonte_id or "").strip())
        if not fonte:
            return (
                f'Não achei a fonte "{fonte_id}". Use `listar_fontes` para ver os ids — '
                "a relação precisa apontar para o material que a sustenta."
            )

        ids = {}
        for nome in (de, para):
            achados = knowledge.buscar(nome, limite=1)
            if not achados:
                return (
                    f'"{nome}" não está no grafo. Use `buscar_no_grafo` para achar o nome '
                    "exato; o grafo só tem conceitos extraídos do material."
                )
            ids[nome] = achados[0]["id"]

        if ids[de] == ids[para]:
            return "Os dois nomes apontam para o mesmo conceito."

        texto = db.read_source_text(fonte)
        if not knowledge.ligar_explicito(
            ids[de], ids[para], trecho=trecho, referencia=texto, quem="agente"
        ):
            return (
                "Recusei: este trecho não existe na fonte. Copie o trecho literalmente "
                "como está no material."
            )

        return f'Registrei: {de} — {para}, sustentado por "{_recorte(trecho, 160)}".'

    return [buscar_no_grafo, vizinhanca_do_conceito, registrar_relacao]


def ferramentas_de_similaridade(notebook_id: str) -> list[BaseTool]:
    """A ligação por similaridade, presa ao caderno (F6/D065).

    Presa, e não global como as três acima, por um motivo prático: ela embeda os
    conceitos de UM caderno e escreve arestas entre eles — sem saber de qual caderno
    é, não há o que fazer. E a ferramenta não recebe `notebook_id` por parâmetro
    (D034): quem já sabe é quem a construiu.
    """

    @tool
    async def ligar_por_similaridade() -> str:
        """Liga conceitos que falam da mesma coisa, por comparação de vetores (F6).

        Serve para achar o que o material NÃO ligou: dois conceitos que nunca
        apareceram juntos num trecho e que ninguém afirmou serem relacionados, mas
        que tratam do mesmo assunto. Também levanta os pares que parecem ser o MESMO
        conceito — duplicatas que a pessoa pode mesclar.

        Custa chamadas de embedding (uma por conceito que ainda não tem vetor), então
        é ação explícita: use quando a pessoa pedir "liga os parecidos", "acha
        duplicatas" ou "aproxima os conceitos". A segunda vez em diante é de graça —
        o vetor já está guardado.

        A ligação que ela cria é **inferida**, e não afirmação do material: não tem
        trecho que a sustente. Ao falar dela, diga que é uma aproximação.
        """
        try:
            embed.atual()
        except embed.EmbeddingNaoConfigurado as exc:
            # Tentar montar o modelo é a única checagem de "está configurado?" que não
            # mente: ela usa o mesmo caminho que o trabalho vai usar. Uma checagem
            # paralela (ler a config e decidir) divergiria dela um dia, e no dia da
            # divergência o agente dispararia um trabalho que já nasce falhando.
            return (
                f"{exc} Não invente a ligação por conta própria: proximidade de assunto "
                "não é relação."
            )

        ja_em_curso = oficina.oficina.em_curso(notebook_id, oficina.SIMILARIDADE)
        run = oficina.oficina.iniciar(
            notebook_id, trabalho=oficina.SIMILARIDADE, origem="agente"
        )
        if ja_em_curso is not None:
            return (
                f"Já havia uma ligação por similaridade em andamento (id {run.id}), e ela "
                "continua — não disparei outra. O resultado aparece no painel do grafo."
            )
        return (
            f"Ligação por similaridade iniciada (id {run.id}). Os números saem no painel "
            "do grafo quando terminar. Não repita o resultado aqui: o desenho mostra "
            "melhor do que uma lista."
        )

    return [ligar_por_similaridade]
