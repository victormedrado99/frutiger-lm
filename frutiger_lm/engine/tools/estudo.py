"""Ferramentas de estudo do agente (F4).

Duas ferramentas, e as duas respondem a partir de **fatos**, não de opinião:

- `lacunas_do_caderno` responde "o que meu material não cobre?" com o que o grafo
  sabe. O que ele NÃO pode saber é o que o material não tem e ninguém escreveu — e
  por isso a ferramenta não chuta tópicos. Ela lista o que está registrado e
  desconectado, e diz que é isso.
- `cards_para_revisar` responde "o que eu tenho para estudar hoje?".

O agente não cria nem revisa card por ferramenta, de propósito. Card é decisão da
pessoa sobre o próprio estudo: um assistente que cria cartões sozinho enche a fila de
revisão com o que ele achou interessante.
"""

from __future__ import annotations

from langchain_core.tools import BaseTool, tool

from ... import db, knowledge, study

LIMITE = 12


def _recorte(texto: str, limite: int = 160) -> str:
    limpo = " ".join(str(texto or "").split())
    return limpo if len(limpo) <= limite else limpo[: limite - 1] + "…"


def ferramentas_de_estudo(notebook_id: str) -> list[BaseTool]:
    """Presas ao caderno, como as de leitura (D034): a pergunta é sobre ELE."""

    @tool
    def lacunas_do_caderno() -> str:
        """O que este caderno tem de buraco — em fatos conferíveis, não em opinião.

        Três listas: conceitos que o material nomeou uma vez e nunca explicou,
        conceitos que a pessoa estudou em OUTRO caderno e que aqui não aparecem, e
        fontes que não geraram conhecimento nenhum.

        Não pergunte a esta ferramenta "que tópicos faltam sobre X": ela não sabe o
        que ninguém escreveu. Ela responde o que está registrado e ficou solto.
        """
        notebook = db.get_notebook(notebook_id)
        if not notebook:
            return "Caderno não encontrado."

        dados = knowledge.lacunas(notebook_id)
        estatisticas = knowledge.estatisticas()

        if not estatisticas["conceitos"]:
            return (
                "O grafo está vazio: nada foi extraído deste caderno ainda. A pessoa "
                "pode usar o botão Extrair conceitos, e aí eu tenho o que analisar."
            )

        linhas: list[str] = []

        soltos = dados["nao_desenvolvidos"]
        if soltos:
            linhas.append(f"O material citou e não explicou ({len(soltos)}):")
            linhas.extend(f"- {c['name']} (1 menção, nenhuma ligação)" for c in soltos[:LIMITE])
            linhas.append("")
        else:
            linhas.append("Nada citado-e-não-explicado: todo conceito registrado se liga a algo.")
            linhas.append("")

        fora = dados["em_outro_caderno"]
        if fora:
            linhas.append(f"Você estudou em outro caderno e aqui não aparece ({len(fora)}):")
            linhas.extend(
                f"- {c['name']} (em {c['onde']})" for c in fora[:LIMITE]
            )
            linhas.append("")

        sem = dados["fontes_sem_contribuicao"]
        if sem:
            linhas.append(f"Fontes que não geraram conhecimento nenhum ({len(sem)}):")
            linhas.extend(f'- "{f["title"]}" ({f["kind"]}, {f["chars"]} caracteres)' for f in sem)
            linhas.append("")

        linhas.append(
            "Lembrete de rigor: isto é o que o material registrado NÃO liga. Tópicos que "
            "não estão aqui e ninguém escreveu eu não tenho como saber — e não vou listar."
        )
        return "\n".join(linhas)

    @tool
    def cards_para_revisar() -> str:
        """Quantos cartões de estudo estão vencidos hoje, e quais são."""
        resumo = study.resumo(notebook_id)
        devidos = study.devidos(notebook_id, limite=LIMITE)

        if not resumo["total"]:
            return (
                "Nenhum cartão criado ainda. A pessoa pode gerar pelo painel Estudar — "
                "os cartões nascem dos conceitos, com o trecho de origem no verso."
            )
        if not devidos:
            return (
                f"Nada vencido agora. {resumo['total']} cartão(ões) no total, "
                f"{resumo['aprendendo']} já em estudo."
            )

        linhas = [f"{resumo['vencidos']} de {resumo['total']} cartão(ões) vencido(s):", ""]
        for card in devidos:
            linhas.append(f"- {card['front']}")
            if card.get("concept_name"):
                linhas.append(f"  (conceito: {card['concept_name']})")
        linhas.append("")
        linhas.append("As respostas ficam no painel: eu não entrego o verso, senão não é revisão.")
        return "\n".join(linhas)

    return [lacunas_do_caderno, cards_para_revisar]
