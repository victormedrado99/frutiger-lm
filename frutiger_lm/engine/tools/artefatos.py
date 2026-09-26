"""As ferramentas de artefato (F5): pedir um documento pelo chat.

Uma ferramenta só, e ela **dispara** em vez de construir. Devolve o id do run e sai de
cena; quem constrói é a oficina, fora do turno (D028, D059). É isto que faz o documento
sair pela tela — aparecendo no painel direito enquanto é escrito — em vez de sair
dentro da resposta, reformatado por cima do que já estava pronto.

**Uma** ferramenta, e não um `gerar_documento(template=...)` genérico. O catálogo do
F5 prometia dois (`gerar_documento` e `compilar_pdf`), e nenhum dos dois existe como
prometido: o `pdf` não é uma ferramenta porque não há PDF no servidor — a decisão D014
imprime pelo navegador, e a ferramenta não pode "salvar um PDF" que só o navegador
sabe gerar. Um parâmetro `template` que aceitasse "plano", "faq" e "guia" seria pior:
prometeria à pessoa — e ao modelo — três formatos que ninguém escreveu ainda. Quando
o segundo template existir de verdade, ele entra aqui com o nome dele.
"""

from __future__ import annotations

from langchain_core.tools import BaseTool, tool

from ... import db
from .. import oficina


def ferramentas_de_artefatos(notebook_id: str) -> list[BaseTool]:
    """Presas ao caderno, como as de leitura e as de estudo (D034): o documento é DELE.

    Ficam fora do catálogo global de propósito: no chat global não há caderno, e as
    ferramentas deste projeto não recebem `notebook_id` por parâmetro — é essa
    ausência que garante o isolamento (D034). Deixar a ferramenta no escopo global
    exigiria escolher um caderno por argumento, que é exatamente o que não se faz aqui.
    """

    @tool
    async def compilar_documento() -> str:
        """Compila o documento deste caderno e devolve o id da compilação.

        O documento reúne o que o material tem: os conceitos do grafo, cada um com o
        trecho literal de origem, as lacunas abertas, o rendimento de cada fonte, o
        apêndice com todas as citações e duas seções de texto escrito pelo modelo
        (resumo e desenvolvimento). Leva cerca de meio minuto, porque tem uma chamada
        de modelo no meio.

        Use quando a pessoa pedir "compila o documento", "monta o material deste
        caderno", "junta tudo num documento". **Não copie o conteúdo do documento na
        resposta**: ele é longo, ainda está sendo escrito, e aparece no painel
        "Gerar" para ser lido e impresso. Diga que a compilação começou e que o
        documento aparece ali.
        """
        if db.get_notebook(notebook_id) is None:
            return "Caderno não encontrado."

        # Perguntar antes de disparar é o que permite responder certo: `iniciar`
        # devolve a compilação que já está em curso, e o modelo precisa saber a
        # diferença entre "comecei agora" e "já havia uma, espere".
        ja_em_curso = oficina.oficina.em_curso(notebook_id)
        run = oficina.oficina.iniciar(notebook_id, origem="agente")

        if ja_em_curso is not None:
            return (
                f"Já havia uma compilação em andamento neste caderno (id {run.id}), "
                "e ela continua — não disparei outra. O documento aparece no painel "
                '"Gerar" quando ficar pronto; não repita o conteúdo dele aqui.'
            )

        return (
            f"Compilação iniciada (id {run.id}). O documento está sendo montado — "
            "leva cerca de meio minuto — e aparece no painel \"Gerar\", onde a pessoa "
            "pode lê-lo e imprimi-lo. Não repita o conteúdo dele nesta resposta."
        )

    return [compilar_documento]
