"""As arestas por similaridade (F6) — o que o material não ligou, o vetor aproxima.

Três passos, e a ordem importa:

1. **embedar o que falta.** O vetor guardado é reusado quando o modelo é o mesmo E o
   texto do conceito é o mesmo (o hash diz isso, D062). A segunda rodada é de graça —
   e é isso que torna o botão clicável mais de uma vez sem culpa.
2. **comparar os pares.** Cosseno entre todos os pares de vetores do caderno. Para 100
   conceitos são ~5 mil comparações: Python puro dá conta, e uma dependência de álgebra
   linear para isto seria peso sem retorno.
3. **ligar só onde acrescenta.** Par que já tem lastro (co-ocorrência ou afirmação)
   fica como está (D063), e a nota tem que passar do limiar (D064).

É lote, como a extração (D044): não é subgrafo do LangGraph, e não precisa ser — um
"grafo de similaridade" seria cerimônia em volta de três passos retos.

O que este módulo **não** decide: o que é "parecido demais para ser o mesmo conceito".
Ele levanta o par e a nota; quem decide mesclar é a pessoa (D066).
"""

from __future__ import annotations

import math
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass
from typing import Any

from .. import knowledge
from . import embed

# O limiar da ARESTA e o dos PARECIDOS DEMAIS (D064, D066). Os dois valores saem de uma
# medição no caderno real (102 conceitos, 5151 pares, `nomic-embed-text-v1.5` local), e
# a medição está no PROJETO.md junto da distribuição que os escolheu.
#
# O que ela mostrou, e que muda a leitura destes números: neste material o cosseno tem
# PISO ALTO — mediana 0,56, p90 0,68 — então "0,5" aqui não quer dizer "parecido". O topo
# é que informa: 0,80 é ~p99, e os pares acima de 0,96 são um punhado.
#
# Chutar aqui tem dois modos de falhar que ninguém percebe: nenhuma aresta nova (limiar
# alto demais) ou um novelo (baixo demais) — e os dois parecem "o F6 não funcionou".
LIMIAR = 0.80

# Mais alto que o da aresta porque a consequência é outra: a aresta só desenha, e isto
# convida a pessoa a olhar dois conceitos como candidatos a serem um só. Medido: com
# 0,93 e com 0,96 o conjunto é o mesmo neste material (5 pares); o teto mais alto é o que
# faz sentido para uma lista que sugere FUNDIR — e fundir não tem volta.
LIMIAR_MESCLAR = 0.96

# Quantos textos vão numa chamada de embedding. Lote pequeno o bastante para a tela
# mostrar progresso, grande o bastante para não fazer uma chamada por conceito.
LOTE = 16

Emitir = Callable[[str, str], Awaitable[None]]


@dataclass
class Resultado:
    """O que o trabalho fez, em números. É o que a tela mostra no fim."""

    conceitos: int = 0
    calculados: int = 0
    reusados: int = 0
    pares: int = 0
    arestas: int = 0
    candidatos: int = 0
    limiar: float = LIMIAR
    limiar_mesclar: float = LIMIAR_MESCLAR
    modelo: str = ""

    def resumo(self) -> dict[str, Any]:
        return asdict(self)


def cosseno(a: list[float], b: list[float]) -> float:
    """Similaridade de cosseno entre dois vetores.

    Dimensões diferentes devolvem 0 e não estouram: vetores de tamanhos diferentes são
    de espaços diferentes, e o lugar de impedir isso é o `model` guardado junto do
    vetor (D062) — aqui, comparar o que não dá é só não comparar.
    """
    if not a or len(a) != len(b):
        return 0.0
    produto = soma_a = soma_b = 0.0
    for x, y in zip(a, b, strict=True):
        produto += x * y
        soma_a += x * x
        soma_b += y * y
    if soma_a <= 0.0 or soma_b <= 0.0:
        return 0.0
    return produto / (math.sqrt(soma_a) * math.sqrt(soma_b))


def _nome_do_modelo(modelo: Any) -> str:
    """Como este modelo vai ficar registrado no vetor e na aresta.

    O nome importa: é ele que impede comparar vetores de espaços diferentes e é ele
    que a aresta mostra como procedência ("inferida por ...").
    """
    for atributo in ("model", "model_name", "model_id"):
        valor = getattr(modelo, atributo, None)
        if valor:
            return str(valor)
    return "modelo sem nome"


async def ligar(
    notebook_id: str,
    *,
    modelo: Any = None,
    limiar: float = LIMIAR,
    limiar_mesclar: float = LIMIAR_MESCLAR,
    emitir: Emitir | None = None,
) -> Resultado:
    """Embeda o caderno, compara os pares e cria as arestas que faltavam.

    `modelo` existe para o teste injetar um embedder falso (sem rede). Em produção é
    `embed.atual()`, resolvido aqui dentro para que a tela não precise conhecer config.
    """
    resultado = Resultado(limiar=limiar, limiar_mesclar=limiar_mesclar)

    async def avisar(passo: str, mensagem: str) -> None:
        if emitir is not None:
            await emitir(passo, mensagem)

    embedder = modelo or embed.atual()
    resultado.modelo = _nome_do_modelo(embedder)

    await avisar("lendo", "Lendo os conceitos do caderno…")
    nos = knowledge.grafo(notebook_id=notebook_id, apenas_principais=False)["nodes"]
    resultado.conceitos = len(nos)
    if len(nos) < 2:
        await avisar("vazio", "Este caderno tem menos de dois conceitos: não há par a comparar.")
        return resultado

    # --- 1. o que embedar -------------------------------------------------- #
    textos: dict[str, str] = {}
    for no in nos:
        trechos = [
            mencao.get("excerpt") or ""
            for mencao in knowledge.mencoes(no["id"], limite=embed.TRECHOS, notebook_id=notebook_id)
        ]
        textos[no["id"]] = embed.texto_do_conceito(no["name"], trechos)

    guardados = knowledge.vetores([no["id"] for no in nos])
    vetores: dict[str, list[float]] = {}
    faltam: list[tuple[str, str]] = []  # (concept_id, texto)
    for no in nos:
        texto = textos[no["id"]]
        anterior = guardados.get(no["id"])
        if (
            anterior
            and anterior["model"] == resultado.modelo
            and anterior["texto_hash"] == embed.hash_do_texto(texto)
        ):
            vetores[no["id"]] = anterior["vetor"]
            resultado.reusados += 1
        else:
            faltam.append((no["id"], texto))

    if faltam:
        await avisar(
            "embeddings",
            f"Calculando {len(faltam)} vetor(es) com {resultado.modelo} "
            f"({resultado.reusados} já estavam calculados)…",
        )
        for inicio in range(0, len(faltam), LOTE):
            fatia = faltam[inicio : inicio + LOTE]
            novos = await embedder.aembed_documents([texto for _, texto in fatia])
            for (concept_id, texto), vetor in zip(fatia, novos, strict=True):
                vetores[concept_id] = list(vetor)
                knowledge.guardar_vetor(
                    concept_id,
                    model=resultado.modelo,
                    texto_hash=embed.hash_do_texto(texto),
                    vetor=list(vetor),
                )
                resultado.calculados += 1
            await avisar(
                "embeddings",
                f"{resultado.calculados} de {len(faltam)} vetor(es) calculados…",
            )
    else:
        await avisar("embeddings", f"Todos os {resultado.reusados} vetores já estavam prontos.")

    # --- 2. comparar os pares ---------------------------------------------- #
    await avisar("comparando", f"Comparando {len(vetores)} vetores dois a dois…")
    ids = [no["id"] for no in nos if no["id"] in vetores]
    # O que conta como "já tem lastro": co-ocorrência e afirmação. As similaridades de
    # uma rodada anterior NÃO contam — senão a nota delas nunca seria atualizada.
    com_lastro = knowledge.pares_ligados(ids, apenas=[knowledge.CO_OCORRENCIA, knowledge.EXPLICITA])

    # --- 3. ligar onde acrescenta ------------------------------------------ #
    suspeitas: list[tuple[str, str, float]] = []
    for i, a in enumerate(ids):
        for b in ids[i + 1 :]:
            par = (a, b) if a < b else (b, a)
            resultado.pares += 1
            nota = cosseno(vetores[a], vetores[b])
            # A suspeita de duplicata é independente de haver aresta (D066): a pergunta
            # "estes dois são o mesmo conceito?" não deixa de existir porque o material
            # já os liga. E são justamente os mais parecidos que costumam já se ligar.
            if nota >= limiar_mesclar:
                suspeitas.append((a, b, nota))
            if par in com_lastro or nota < limiar:
                continue
            knowledge.ligar_similaridade(a, b, score=nota, model=resultado.modelo)
            resultado.arestas += 1

    knowledge.guardar_suspeitas(notebook_id, suspeitas, model=resultado.modelo)
    resultado.candidatos = len(suspeitas)
    await avisar(
        "pronto",
        f"{resultado.arestas} ligação(ões) por similaridade em {resultado.conceitos} conceito(s); "
        f"{resultado.candidatos} par(es) muito parecidos (suspeita de duplicata).",
    )
    return resultado
