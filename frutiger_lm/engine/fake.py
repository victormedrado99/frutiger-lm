"""Modelos falsos para teste: sem rede, sem chave, sem custo.

Usamos os fakes do ``langchain-core`` em vez de escrever um do zero — duplicar o
que a lib dá seria trabalho a mais para manter.

**Mas o fake da lib não basta**, e isso foi descoberto testando: o ``bind_tools``
herdado de ``BaseChatModel`` levanta ``NotImplementedError``, e o ``create_agent``
liga as ferramentas no modelo antes de rodar. Ou seja, o fake pronto não conduz o
laço do agente. O que este módulo acrescenta é exatamente isso: um ``bind_tools``
que aceita a ligação e devolve a si mesmo, porque as mensagens canônicas já
trazem as tool calls que queremos simular.
"""

from __future__ import annotations

from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.language_models.fake_chat_models import (
    FakeListChatModel,
    GenericFakeChatModel,
)
from langchain_core.messages import AIMessage

TEXTO_PADRAO = "resposta de teste"


class _AceitaFerramentas:
    """Aceita `bind_tools` como no-op.

    Necessário porque `create_agent` chama `bind_tools` no modelo, e o default do
    `BaseChatModel` é `NotImplementedError`. Como o roteiro do fake já está nas
    mensagens, a ligação não precisa fazer nada além de ser aceita.
    """

    def bind_tools(
        self,
        tools: Any,
        *,
        tool_choice: Any = None,
        **kwargs: Any,
    ) -> Any:
        return self


class _Responde(_AceitaFerramentas, FakeListChatModel):
    """Sempre a mesma resposta, e compatível com o laço do agente."""


class _ComFerramenta(_AceitaFerramentas, GenericFakeChatModel):
    """Roteiro de mensagens, e compatível com o laço do agente."""


def responde(texto: str = TEXTO_PADRAO) -> BaseChatModel:
    """Sempre a mesma resposta. Não toca a rede."""
    return _Responde(responses=[texto])


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
    return _ComFerramenta(
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
