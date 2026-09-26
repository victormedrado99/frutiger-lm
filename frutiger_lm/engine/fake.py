"""Modelos falsos para teste: sem rede, sem chave, sem custo.

Comecei usando os fakes do ``langchain-core``, para não duplicar o que a lib dá.
Duas descobertas empíricas mostraram que **não servem** para este projeto, e as
duas foram achadas testando, não usanda:

1. ``bind_tools`` (herdado de ``BaseChatModel``) levanta ``NotImplementedError``,
   e o ``create_agent`` liga as ferramentas no modelo antes de rodar.
2. O ``_stream`` do ``GenericFakeChatModel`` não produz chunk para mensagem cujo
   ``content`` é vazio — que é justamente uma mensagem que só carrega tool call.
   Resultado: ``ValueError: No generations found in stream``. Conduzia o
   ``ainvoke`` e não conduzia o ``astream``, e o app inteiro é streaming.

Então o fake é nosso, e pequeno: roteiro de mensagens, com **paridade entre bloco
e stream** — as mesmas mensagens saem tanto de ``invoke`` quanto de ``astream``.
É essa paridade que permite testar o caminho que o app realmente usa.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
from pydantic import Field

TEXTO_PADRAO = "resposta de teste"


class _RoteiroFalso(BaseChatModel):
    """Devolve (e transmite) uma sequência roteirizada de mensagens."""

    roteiro: list[AIMessage] = Field(default_factory=list)

    @property
    def _llm_type(self) -> str:
        return "roteiro-falso"

    def _proxima(self) -> AIMessage:
        if not self.roteiro:
            raise RuntimeError(
                "O roteiro do modelo falso acabou: o teste pediu mais respostas do "
                "que roteirizou. Costuma significar que o agente deu uma volta a "
                "mais do que o esperado."
            )
        return self.roteiro.pop(0)

    def bind_tools(self, tools: Any, *, tool_choice: Any = None, **kwargs: Any) -> Any:
        """Aceita a ligação sem fazer nada: o roteiro já traz as tool calls."""
        return self

    def _generate(self, messages: Any, stop: Any = None, run_manager: Any = None, **kw: Any) -> ChatResult:
        return ChatResult(generations=[ChatGeneration(message=self._proxima())])

    async def _astream(self, messages: Any, stop: Any = None, run_manager: Any = None, **kw: Any):
        mensagem = self._proxima()

        # Texto antes da tool call, quando houver: é o que o modelo real faz
        # ("vou procurar isso na fonte") antes de chamar a ferramenta.
        if mensagem.content:
            texto = mensagem.content
            meio = max(1, len(texto) // 2)
            for parte in (texto[:meio], texto[meio:]):
                if parte:
                    yield ChatGenerationChunk(message=AIMessageChunk(content=parte))

        # Tool call: o chunk vai com `tool_call_chunks`, que é como os provedores
        # reais transmitem — e é o que o LangChain remonta em `tool_calls`.
        if mensagem.tool_calls:
            yield ChatGenerationChunk(
                message=AIMessageChunk(
                    content="",
                    tool_call_chunks=[
                        {
                            "name": tc["name"],
                            "args": json.dumps(tc["args"]),
                            "id": tc.get("id") or f"call_{i}",
                            "index": i,
                            "type": "tool_call_chunk",
                        }
                        for i, tc in enumerate(mensagem.tool_calls)
                    ],
                )
            )


def responde(texto: str = TEXTO_PADRAO) -> BaseChatModel:
    """Uma resposta só, sem tocar ferramenta. Não toca a rede."""
    return _RoteiroFalso(roteiro=[AIMessage(texto)])


def com_ferramenta(
    nome: str,
    argumentos: dict,
    resposta_final: str = TEXTO_PADRAO,
    antes: str = "",
) -> BaseChatModel:
    """Chama uma ferramenta na primeira volta e responde na segunda.

    É assim que se testa o laço do agente (modelo → ferramenta → modelo) sem
    rede: alimentando o fake com a sequência que um modelo real produziria.

    ``antes`` é o texto que o modelo escreve **antes** de chamar a ferramenta —
    o caso real ("vou procurar isso na fonte"). Existe para poder testar a emenda
    entre as duas falas, que é onde aparece o defeito de texto colado.
    """
    return _RoteiroFalso(
        roteiro=[
            AIMessage(
                antes,
                tool_calls=[
                    {"name": nome, "args": argumentos, "id": "call_teste_1", "type": "tool_call"}
                ],
            ),
            AIMessage(resposta_final),
        ]
    )


class _ExtratorFalso:
    """Devolve objetos já prontos, no lugar do que o modelo devolveria.

    Não herda de `BaseChatModel` de propósito: a extração só usa
    `with_structured_output(...).ainvoke(...)`, e herdar exigiria implementar
    `_generate` e `_stream` para não usar nenhum dos dois. Um objeto que faz o que
    é usado é mais honesto — e se um dia a extração passar a usar mais da
    interface, este fake quebra, o que é o aviso que se quer.

    `pausa` é o tempo que ele demora para responder, e existe por um motivo estreito:
    sem ela o fake responde **sem devolver o controle ao laço**, a construção inteira
    termina num passo só, e o teste não consegue observar quem NÃO esperou por ela.
    Uma chamada de modelo de verdade leva segundos; a pausa é o que dá ao teste o
    mesmo mundo que a produção tem (ver o teste da ferramenta que dispara e sai).
    """

    def __init__(self, objetos: list, pausa: float = 0.0) -> None:
        self.objetos = list(objetos)
        self.chamadas: list[list] = []
        self.pausa = pausa
        self._i = 0

    def with_structured_output(self, schema: type, **kw: object) -> _ExtratorFalso:
        return self

    def _proximo(self, mensagens: list) -> object:
        self.chamadas.append(mensagens)
        if not self.objetos:
            raise AssertionError("o extrator falso ficou sem objetos para devolver")
        objeto = self.objetos[min(self._i, len(self.objetos) - 1)]
        self._i += 1
        return objeto

    def invoke(self, mensagens: list, **kw: object) -> object:
        return self._proximo(mensagens)

    async def ainvoke(self, mensagens: list, **kw: object) -> object:
        if self.pausa:
            await asyncio.sleep(self.pausa)
        return self._proximo(mensagens)


def extrai(objetos: list, pausa: float = 0.0) -> _ExtratorFalso:
    """Um extrator falso para testar sem rede e sem custo.

    `pausa` (segundos) simula a demora de uma chamada real — é o que permite testar
    que quem DISPARA um artefato não fica esperando por ele.
    """
    return _ExtratorFalso(objetos, pausa=pausa)


class _EmbedderFalso:
    """Vetores determinísticos, sem rede — e o teste pode ditar alguns (F6).

    `vetores` mapeia o COMEÇO do texto para o vetor que ele deve produzir: como o texto
    de um conceito começa pelo nome dele (D061), o teste diz "estes dois conceitos são
    parecidos" e deixa a similaridade fazer o resto. Sem mapa, o vetor sai de um hash do
    próprio texto — determinístico, e dois textos diferentes dão vetores diferentes. Não
    finge semântica: finge um provedor.

    `model` existe porque o app grava o nome do modelo junto do vetor e na aresta
    (D062) — e o teste precisa poder dizer que o modelo MUDOU (o que obriga a
    recomputar em vez de comparar espaços diferentes).
    """

    def __init__(
        self,
        vetores: dict[str, list[float]] | None = None,
        *,
        dim: int = 8,
        model: str = "fake-embed",
        pausa: float = 0.0,
    ) -> None:
        self.vetores = dict(vetores or {})
        self.dim = dim
        self.model = model
        self.pausa = pausa
        self.chamadas: list[list[str]] = []

    def _vetor(self, texto: str) -> list[float]:
        """O mapa casa pelo **começo** do texto, que é onde o nome do conceito está.

        Casar por "contém" era o erro óbvio e foi cometido: o trecho de um conceito cita
        o nome do outro, então o vetor de BRAVO vinha do mapa de ALFA e os dois saíam
        idênticos — o teste então afirmava o que ele mesmo tinha fabricado.
        """
        alvo = texto.lstrip()
        for chave, vetor in self.vetores.items():
            if alvo.startswith(chave):
                return [float(x) for x in vetor]
        semente = int(hashlib.sha256(texto.encode("utf-8")).hexdigest()[:8], 16)
        valores = []
        for _ in range(self.dim):
            semente, resto = divmod(semente * 6364136223846793005 + 1442695040888963407, 2**64)
            valores.append((resto / 2**63) - 1.0)
        return valores

    def _proximos(self, textos: list[str]) -> list[list[float]]:
        self.chamadas.append(list(textos))
        return [self._vetor(texto) for texto in textos]

    def embed_documents(self, textos: list[str]) -> list[list[float]]:
        return self._proximos(textos)

    async def aembed_documents(self, textos: list[str]) -> list[list[float]]:
        if self.pausa:
            await asyncio.sleep(self.pausa)
        return self._proximos(textos)

    def embed_query(self, texto: str) -> list[float]:
        return self._vetor(texto)

    async def aembed_query(self, texto: str) -> list[float]:
        return self._vetor(texto)


def embeda(
    vetores: dict[str, list[float]] | None = None,
    *,
    dim: int = 8,
    model: str = "fake-embed",
    pausa: float = 0.0,
) -> _EmbedderFalso:
    """Um embedder falso para testar as arestas por similaridade sem rede e sem custo."""
    return _EmbedderFalso(vetores, dim=dim, model=model, pausa=pausa)
