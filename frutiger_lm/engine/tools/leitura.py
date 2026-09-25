"""Ferramentas de leitura das fontes.

Três ferramentas, e a superfície continua pequena (D011, D025):

    listar_fontes      o que existe, com id, tipo, tamanho e se está ligada
    ler_fonte          um trecho, com posição — nunca o arquivo inteiro
    buscar_nas_fontes  procura um termo e devolve os trechos com a fonte

**As mesmas três servem aos dois chats**, e a única diferença é o `Escopo`:

- no caderno, o escopo é aquele caderno;
- no chat global, o escopo é **todos** os cadernos, e `listar_fontes` vira o mapa
  de tudo (caderno → suas fontes).

Isso foi decidido em vez de criar ferramentas de "busca entre cadernos": uma
ferramenta a mais com o mesmo trabalho seria pior para o modelo escolher (D025) e
duplicaria a checagem de acesso. Duas listagens parecidas é o começo de o modelo
usar a errada.

O ponto de engenharia que importa é **limitar a saída**. Uma ferramenta que pode
despejar 400 mil caracteres no contexto quebra o turno, e o modelo não tem como
saber disso. Por isso `ler_fonte` corta em pedaços e diz onde parou, de modo que
continuar seja uma decisão dele, não um acidente.
"""

from __future__ import annotations

from dataclasses import dataclass

from langchain_core.tools import BaseTool, tool

from ...db import (
    fontes_ativas_globais,
    get_source,
    list_notebooks_por_criacao,
    list_sources,
    read_source_text,
)

TAMANHO_PADRAO = 8_000
TAMANHO_MAXIMO = 20_000
MAX_RESULTADOS = 25
LINHAS_DE_CONTEXTO = 1
FONTES_POR_CADERNO = 8


@dataclass(frozen=True)
class Escopo:
    """O que o agente deste chat pode ler.

    Um caderno, ou todos (o chat global). É a **única** diferença entre os dois
    chats no lado das ferramentas: o catálogo é o mesmo, e a checagem de acesso é
    uma só — o que garante que o chat de um caderno não consiga ler as fontes de
    outro (D034), e que o global consiga ler todas.
    """

    notebook_id: str | None = None

    @classmethod
    def do_caderno(cls, notebook_id: str) -> Escopo:
        return cls(notebook_id=notebook_id)

    @classmethod
    def todos(cls) -> Escopo:
        return cls(notebook_id=None)

    @classmethod
    def de(cls, valor: Escopo | str) -> Escopo:
        """Aceita o id direto, para o caso comum: o chat de um caderno."""
        return cls.do_caderno(valor) if isinstance(valor, str) else valor

    @property
    def e_global(self) -> bool:
        return self.notebook_id is None

    def permite(self, fonte: dict) -> bool:
        return self.e_global or fonte["notebook_id"] == self.notebook_id


def _mil(n: int) -> str:
    """Milhar no padrão pt-BR: 18.221."""
    return f"{n:,}".replace(",", ".")


def _fonte_do_escopo(source_id: str, escopo: Escopo) -> tuple[dict | None, str]:
    """Resolve a fonte dentro do escopo. Devolve (fonte, erro legível)."""
    fonte = get_source(source_id)
    if fonte is None or not escopo.permite(fonte):
        # Não revelar "existe, mas é de outro caderno": para quem pergunta, é
        # como se não existisse. Evita virar oráculo de ids alheios.
        return None, f"Não existe fonte com id '{source_id}' no material disponível."
    if not fonte["active"] or fonte["status"] != "ready":
        return None, (
            f"A fonte '{fonte['title']}' está DESLIGADA do contexto. Avise a "
            "pessoa de que ela precisa religar a fonte na coluna da esquerda."
        )
    return fonte, ""


def ferramentas_de_leitura(escopo: Escopo | str) -> list[BaseTool]:
    """Monta as ferramentas de leitura para este escopo (D034)."""
    escopo = Escopo.de(escopo)

    @tool
    def listar_fontes() -> str:
        """Lista o material disponível: id, tipo, tamanho e se está ligada.

        Use primeiro, quando não souber o que existe. O id devolvido é o que
        `ler_fonte` espera. Num caderno, lista as fontes dele; no chat global,
        lista os cadernos e as fontes de cada um.
        """
        return _listar(escopo)

    @tool
    def ler_fonte(source_id: str, inicio: int = 0, tamanho: int = TAMANHO_PADRAO) -> str:
        """Lê um trecho de uma fonte. Devolve o texto e onde o trecho parou.

        Para fonte longa, leia em pedaços: o cabeçalho diz o total de caracteres
        e a próxima posição. Se o que você procura não aparecer, use
        `buscar_nas_fontes` — é mais barato do que varrer o arquivo inteiro.
        """
        fonte, erro = _fonte_do_escopo(source_id, escopo)
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

        onde = f'"{fonte["title"]}" (id {fonte["id"]}, tipo {fonte["kind"]})'
        if escopo.e_global and fonte.get("notebook_title"):
            onde += f' — do caderno "{fonte["notebook_title"]}"'

        partes = [
            f"Fonte {onde} — trecho de {_mil(inicio)} a {_mil(fim)} "
            f"de {_mil(total)} caracteres.",
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
        um código) sem ler arquivos inteiros. No chat global, procura em **todos**
        os cadernos e diz de qual caderno veio cada trecho.
        """
        return _buscar(termo, escopo)

    return [listar_fontes, ler_fonte, buscar_nas_fontes]


# --------------------------------------------------------------------------- #
# Implementação, separada para o corpo das ferramentas ficar só na docstring
# --------------------------------------------------------------------------- #

def _listar(escopo: Escopo) -> str:
    if escopo.e_global:
        return _listar_global()
    return _listar_do_caderno(escopo.notebook_id or "")


def _listar_do_caderno(notebook_id: str) -> str:
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


def _listar_global() -> str:
    cadernos = list_notebooks_por_criacao()
    if not cadernos:
        return "Não há cadernos ainda. Avise a pessoa e ofereça ajuda para criar o primeiro."

    fontes = fontes_ativas_globais()
    numeradas = {f["id"]: i for i, f in enumerate(fontes, start=1)}
    desligadas = _desligadas_globais()

    linhas = [
        f"Cadernos e fontes ({len(cadernos)} caderno(s), "
        f"{len(fontes)} fonte(s) ativa(s)):",
        "",
    ]
    for caderno in cadernos:
        minhas = [f for f in fontes if f["notebook_id"] == caderno["id"]]
        linhas.append(f"━ {caderno['title']}  (id {caderno['id']})")
        if caderno.get("description"):
            linhas.append(f"    {caderno['description']}")
        if not minhas:
            linhas.append("    (sem fontes ativas)")
        for fonte in minhas[:FONTES_POR_CADERNO]:
            linhas.append(
                f"    [{numeradas[fonte['id']]}] {fonte['id']}  {fonte['kind']:<6} "
                f"{_mil(fonte['chars']):>10} car.  \"{fonte['title']}\""
            )
        if len(minhas) > FONTES_POR_CADERNO:
            linhas.append(
                f"    … e mais {len(minhas) - FONTES_POR_CADERNO} fonte(s) neste "
                "caderno — use `buscar_nas_fontes` para chegar nelas"
            )
        for fonte in [d for d in desligadas if d["notebook_id"] == caderno["id"]]:
            linhas.append(f"    (desligada) {fonte['id']}  \"{fonte['title']}\"")
        linhas.append("")

    linhas += [
        "O número entre colchetes é como você cita ([1], [2]) na resposta.",
        "`ler_fonte` e `buscar_nas_fontes` alcançam qualquer uma destas fontes.",
    ]
    return "\n".join(linhas)


def _desligadas_globais() -> list[dict]:
    """Fontes fora do contexto, para o mapa mostrar o que existe mas não conta."""
    fora = []
    for caderno in list_notebooks_por_criacao():
        for fonte in list_sources(caderno["id"]):
            if not fonte["active"] or fonte["status"] != "ready":
                fora.append({**fonte, "notebook_id": caderno["id"]})
    return fora


def _buscar(termo: str, escopo: Escopo) -> str:
    alvo = termo.strip()
    if not alvo:
        return "Informe um termo para buscar."
    agulha = alvo.casefold()

    # Como rotular cada bloco: no global, dizer de qual caderno veio é obrigatório
    # (é o que permite à pessoa ir conferir); no caderno, o nome basta.
    def rotulo(fonte: dict) -> str:
        if escopo.e_global:
            return f'"{fonte["title"]}" (do caderno "{fonte["notebook_title"]}", id {fonte["id"]})'
        return f'"{fonte["title"]}" (id {fonte["id"]})'

    if escopo.e_global:
        fontes = fontes_ativas_globais()
    else:
        fontes = list_sources(escopo.notebook_id or "", active_only=True)

    if not fontes:
        return "Não há fontes ativas para buscar."

    blocos: list[str] = []
    achados = 0
    truncado = False

    for fonte in fontes:
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
            blocos.append(f"{rotulo(fonte)}, linha {i + 1}\n{trecho}")
        if truncado:
            break

    if not blocos:
        return (
            f"Nenhuma ocorrência de '{alvo}' nas {len(fontes)} fontes ativas. "
            "Talvez o material não cubra esse ponto, ou o termo esteja escrito "
            "de outra forma — vale tentar uma variação."
        )

    cauda = (
        f"\n\n[limite de {MAX_RESULTADOS} atingido — refine o termo para ver mais]"
        if truncado
        else ""
    )
    return f"{achados} ocorrência(s) de '{alvo}':\n\n" + "\n\n".join(blocos) + cauda
