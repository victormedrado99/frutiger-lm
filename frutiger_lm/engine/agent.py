"""O agente do caderno — modelo + ferramentas + memória.

É a peça que substitui o Hermes. Um agente só, sem as duas rotas antigas (D003 e
D008 revertidas): o catálogo de ferramentas cresce à vontade e o que se expõe é
curado por caderno (D025).

O que este módulo **não** faz, de propósito:

- não escolhe o modelo — isso é `llm.atual()`, que lê a config da UI (D020/D031);
- não gera documento por conta própria — isso é subgrafo, com id e acompanhamento
  no painel direito (D028);
- não monta o prompt do zero — reusa `prompts.build_notebook_prompt`, que já
  decide entre inlinar as fontes ou mandar o agente lê-las (D035).
"""

from __future__ import annotations

from typing import Any

from langchain.agents import create_agent
from langchain_core.language_models import BaseChatModel
from langchain_core.tools import BaseTool

from ..db import get_notebook
from ..prompts import build_notebook_prompt
from . import checkpoint, llm
from .tools.leitura import ferramentas_de_leitura
from .tools.web import ferramentas_de_web


def catalogo(notebook_id: str) -> list[BaseTool]:
    """O que este caderno expõe ao modelo (D025).

    Hoje: as três de leitura (presas ao caderno, D034) e `web_extract`. As de
    escrita e as de documento entram aqui quando existirem — e é este ponto único
    que decide exposição, para não virar 25 ferramentas sempre visíveis.
    """
    return [*ferramentas_de_leitura(notebook_id), *ferramentas_de_web()]


def montar(
    notebook_id: str,
    *,
    modelo: BaseChatModel | None = None,
    checkpointer: Any = None,
) -> Any:
    """Monta o agente deste caderno.

    `modelo` e `checkpointer` existem para o teste injetar: nos testes o modelo é
    falso (sem rede, sem chave) e o checkpointer é um arquivo temporário. Em
    produção os dois vêm do app.
    """
    notebook = get_notebook(notebook_id)
    if notebook is None:
        raise ValueError(f"Caderno '{notebook_id}' não existe.")

    return create_agent(
        modelo or llm.atual(),
        tools=catalogo(notebook_id),
        system_prompt=build_notebook_prompt(notebook),
        checkpointer=checkpointer,
    )


async def responder(agente: Any, notebook_id: str, texto: str) -> str:
    """Uma volta completa: manda a mensagem e devolve o texto final.

    O histórico não é passado aqui — quem guarda é o checkpointer, por thread
    (D019). O chamador só entrega o que a pessoa acabou de escrever.
    """
    saida = await agente.ainvoke(
        {"messages": [{"role": "user", "content": texto}]},
        checkpoint.config(notebook_id),
    )
    return saida["messages"][-1].content
