"""Modelos falsos para teste: sem rede, sem chave, sem custo.

Não reimplementamos um fake — ``langchain-core`` já traz ``FakeListChatModel`` e
``GenericFakeChatModel``, e duplicar o que a lib dá seria trabalho a mais para
manter. O que este módulo acrescenta é o que os testes precisam e a lib não tem
pronto: um fake que **emite tool call**, que é o único jeito de exercitar o laço
do agente offline.
"""

from __future__ import annotations

from langchain_core.language_models import BaseChatModel
from langchain_core.language_models.fake_chat_models import (
    FakeListChatModel,
    GenericFakeChatModel,
)
from langchain_core.messages import AIMessage

TEXTO_PADRAO = "resposta de teste"


def responde(texto: str = TEXTO_PADRAO) -> BaseChatModel:
    """Sempre a mesma resposta. Não toca a rede."""
    return FakeListChatModel(responses=[texto])


def com_ferramenta(
    nome: str,
    argumentos: dict,
    resposta_final: str = TEXTO_PADRAO,
) -> BaseChatModel:
    """Chama uma ferramenta na primeira volta e responde na segunda.

    É assim que se testa o laço do agente (modelo → ferramenta → modelo) sem
    rede: alimentando o fake com a sequência de mensagens que um modelo real
    produziria.
    """
    return GenericFakeChatModel(
        messages=iter(
            [
                AIMessage(
                    "",
                    tool_calls=[
                        {
                            "name": nome,
                            "args": argumentos,
                            "id": "call_teste_1",
                            "type": "tool_call",
                        }
                    ],
                ),
                AIMessage(resposta_final),
            ]
        )
    )
