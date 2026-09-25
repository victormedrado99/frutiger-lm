"""Ferramentas de web.

Por enquanto só `web_extract`. **Não há `web_search`**: buscar na web depende de um
provedor, e isso é decisão em aberto (D036). Quando houver, ela entra aqui e,
seguindo a D025, só é exposta ao modelo se estiver configurada — ninguém deve ser
obrigado a ter uma chave de busca para usar o Frutiger LM.

Estas ferramentas não são presas a caderno (ao contrário das de leitura, D034):
uma URL não pertence a caderno nenhum. O que elas trazem é sempre "fora das
fontes" e o prompt manda dizer isso.
"""

from __future__ import annotations

from langchain_core.tools import BaseTool, tool

from ...ingest import IngestError, fetch_url_text

TAMANHO_PADRAO = 6_000
TAMANHO_MAXIMO = 20_000


def ferramentas_de_web() -> list[BaseTool]:
    """As ferramentas de web disponíveis hoje."""

    @tool
    def web_extract(url: str, inicio: int = 0, tamanho: int = TAMANHO_PADRAO) -> str:
        """Traz o texto de uma página da web, para complementar as fontes.

        Use quando a pessoa indicar um link, ou quando as fontes não cobrirem um
        ponto e a web puder ajudar. O que vier daqui é "fora das fontes", e a
        resposta deve dizer isso. Para página longa, chame de novo com `inicio`
        maior — o cabeçalho diz o tamanho total.
        """
        alvo = (url or "").strip()
        if not alvo:
            return "Informe o endereço da página."
        if not alvo.startswith(("http://", "https://")):
            alvo = "https://" + alvo

        try:
            titulo, texto = fetch_url_text(alvo)
        except IngestError as exc:
            return f"Não consegui ler essa página: {exc}"
        except Exception as exc:  # httpx e companhia: erro de rede é esperado aqui
            return f"Falha ao acessar {alvo}: {type(exc).__name__}: {exc}"

        total = len(texto)
        inicio = max(0, min(int(inicio), total))
        tamanho = max(1, min(int(tamanho), TAMANHO_MAXIMO))
        fim = min(inicio + tamanho, total)

        partes = [
            f'Página "{titulo}" — trecho de {inicio} a {fim} de {total} caracteres. '
            "Conteúdo de fora das fontes do caderno.",
            "",
            texto[inicio:fim],
        ]
        if fim < total:
            partes += ["", f"[continua — chame de novo com inicio={fim}]"]
        return "\n".join(partes)

    return [web_extract]
