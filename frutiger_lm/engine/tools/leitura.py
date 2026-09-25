"""Ferramentas de leitura das fontes de um caderno.

Três ferramentas, e a superfície é para continuar pequena (D011, D025):

    listar_fontes      o que existe, com id, tipo, tamanho e se está ligada
    ler_fonte          um trecho, com posição — nunca o arquivo inteiro
    buscar_nas_fontes  procura um termo e devolve os trechos com a fonte

O ponto de engenharia que importa aqui é **limitar a saída**. Uma ferramenta que
pode despejar 400 mil caracteres no contexto quebra o turno, e o modelo não tem
como saber disso. Por isso `ler_fonte` corta em pedaços e diz onde parou, de modo
que continuar seja uma decisão dele, não um acidente.
"""

from __future__ import annotations

from langchain_core.tools import BaseTool, tool

from ...db import get_source, list_sources, read_source_text

TAMANHO_PADRAO = 8_000
TAMANHO_MAXIMO = 20_000
MAX_RESULTADOS = 25
LINHAS_DE_CONTEXTO = 1


def _mil(n: int) -> str:
    """Milhar no padrão pt-BR: 18.221."""
    return f"{n:,}".replace(",", ".")


def _fonte_do_caderno(source_id: str, notebook_id: str) -> tuple[dict | None, str]:
    """Resolve a fonte **dentro deste caderno**. Devolve (fonte, erro legível)."""
    fonte = get_source(source_id)
    if fonte is None:
        return None, f"Não existe fonte com id '{source_id}'."
    if fonte["notebook_id"] != notebook_id:
        # Não revelar "existe, mas é de outro caderno": para quem pergunta, é
        # como se não existisse. Evita virar oráculo de ids alheios.
        return None, f"Não existe fonte com id '{source_id}' neste caderno."
    if not fonte["active"] or fonte["status"] != "ready":
        return None, (
            f"A fonte '{fonte['title']}' está DESLIGADA do contexto. Avise a "
            "pessoa de que ela precisa religar a fonte na coluna da esquerda."
        )
    return fonte, ""


def ferramentas_de_leitura(notebook_id: str) -> list[BaseTool]:
    """Monta as ferramentas de leitura deste caderno (D034)."""

    @tool
    def listar_fontes() -> str:
        """Lista as fontes deste caderno: id, tipo, tamanho e se está ligada.

        Use primeiro, quando não souber o que existe disponível. O id devolvido
        é o que `ler_fonte` espera.
        """
        fontes = list_sources(notebook_id)
        if not fontes:
            return (
                "Este caderno ainda não tem fontes. Avise a pessoa e ofereça "
                "ajuda para adicionar a primeira."
            )

        ativas = [f for f in fontes if f["active"] and f["status"] == "ready"]
        desligadas = [f for f in fontes if f not in ativas]

        # A numeração conta SÓ as ativas, para casar com a do contexto inline
        # (db.build_context). Se a desligada entrasse na conta, o modelo citaria
        # [3] apontando para a fonte errada.
        linhas = [f"Fontes deste caderno ({len(ativas)} ativas de {len(fontes)}):", ""]
        for i, fonte in enumerate(ativas, start=1):
            linhas.append(
                f"[{i}] {fonte['id']}  {fonte['kind']:<6} "
                f"{_mil(fonte['chars']):>10} car.  \"{fonte['title']}\""
            )
        if desligadas:
            linhas += ["", "Desligadas (fora do contexto — a pessoa precisa religar):"]
            for fonte in desligadas:
                linhas.append(
                    f"      {fonte['id']}  {fonte['kind']:<6} "
                    f"{_mil(fonte['chars']):>10} car.  \"{fonte['title']}\""
                )
        linhas += [
            "",
            "Use `ler_fonte` com o id para ler um trecho, ou `buscar_nas_fontes` "
            "para procurar um termo ou número específico.",
        ]
        return "\n".join(linhas)

    @tool
    def ler_fonte(source_id: str, inicio: int = 0, tamanho: int = TAMANHO_PADRAO) -> str:
        """Lê um trecho de uma fonte. Devolve o texto e onde o trecho parou.

        Para fonte longa, leia em pedaços: o cabeçalho diz o total de caracteres
        e a próxima posição. Se o que você procura não aparecer, use
        `buscar_nas_fontes` — é mais barato do que varrer o arquivo inteiro.
        """
        fonte, erro = _fonte_do_caderno(source_id, notebook_id)
        if fonte is None:
            return erro

        texto = read_source_text(fonte)
        if not texto:
            return (
                f"A fonte '{fonte['title']}' está registrada, mas o arquivo de "
                "texto não pôde ser lido."
            )

        total = len(texto)
        inicio = max(0, min(int(inicio), total))
        tamanho = max(1, min(int(tamanho), TAMANHO_MAXIMO))
        fim = min(inicio + tamanho, total)

        partes = [
            f"Fonte \"{fonte['title']}\" (id {fonte['id']}, tipo {fonte['kind']}) — "
            f"trecho de {_mil(inicio)} a {_mil(fim)} de {_mil(total)} caracteres.",
            "",
            texto[inicio:fim],
        ]
        if fim < total:
            partes += [
                "",
                f"[continua — próxima leitura com inicio={fim}, "
                f"ou buscar_nas_fontes para achar o trecho exato]",
            ]
        return "\n".join(partes)

    @tool
    def buscar_nas_fontes(termo: str) -> str:
        """Procura um termo nas fontes ativas e devolve os trechos encontrados.

        É a ferramenta certa para achar um dado específico (um número, um nome,
        um código) sem ler arquivos inteiros.
        """
        alvo = termo.strip()
        if not alvo:
            return "Informe um termo para buscar."
        agulha = alvo.casefold()

        ativas = list_sources(notebook_id, active_only=True)
        if not ativas:
            return "Não há fontes ativas neste caderno para buscar."

        blocos: list[str] = []
        achados = 0
        truncado = False

        for fonte in ativas:
            texto = read_source_text(fonte)
            if not texto:
                continue
            linhas = texto.splitlines()
            for i, linha in enumerate(linhas):
                if agulha not in linha.casefold():
                    continue
                if achados >= MAX_RESULTADOS:
                    truncado = True
                    break
                achados += 1
                de = max(0, i - LINHAS_DE_CONTEXTO)
                ate = min(len(linhas), i + LINHAS_DE_CONTEXTO + 1)
                trecho = "\n".join(f"  {n + 1:>5}│ {linhas[n]}" for n in range(de, ate))
                blocos.append(
                    f"\"{fonte['title']}\" (id {fonte['id']}, linha {i + 1})\n{trecho}"
                )
            if truncado:
                break

        if not blocos:
            return (
                f"Nenhuma ocorrência de '{alvo}' nas {len(ativas)} fontes ativas. "
                "Talvez o material não cubra esse ponto, ou o termo esteja escrito "
                "de outra forma — vale tentar uma variação."
            )

        cauda = (
            f"\n\n[limite de {MAX_RESULTADOS} atingido — refine o termo para ver mais]"
            if truncado
            else ""
        )
        return f"{achados} ocorrência(s) de '{alvo}':\n\n" + "\n\n".join(blocos) + cauda

    return [listar_fontes, ler_fonte, buscar_nas_fontes]
