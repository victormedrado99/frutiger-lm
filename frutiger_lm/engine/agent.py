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

import logging
from collections.abc import AsyncIterator
from typing import Any

from langchain.agents import create_agent
from langchain_core.language_models import BaseChatModel
from langchain_core.tools import BaseTool

from ..db import get_notebook
from ..prompts import build_global_prompt, build_notebook_prompt
from . import llm
from .tools.artefatos import ferramentas_de_artefatos
from .tools.estudo import ferramentas_de_estudo
from .tools.grafo import ferramentas_de_grafo
from .tools.leitura import Escopo, ferramentas_de_leitura
from .tools.web import ferramentas_de_web

log = logging.getLogger("frutiger.engine")


def catalogo(notebook_id: str) -> list[BaseTool]:
    """O que o chat **de um caderno** expõe ao modelo (D025).

    As três de leitura presas àquele caderno (D034), `web_extract`, as de grafo e as
    de estudo. As de escrita e as de documento entram aqui quando existirem — e é este
    ponto único que decide exposição, para não virar 25 ferramentas sempre visíveis.

    As de grafo entram nos dois catálogos sem escopo: o grafo é a camada que liga, e o
    conceito que aparece em dois cadernos é o que há de mais interessante nele (D045).
    As de estudo são presas ao caderno, porque a pergunta é sobre ele. A de artefato
    também é presa — e só existe aqui: documento é de um caderno (D034).
    """
    return [
        *ferramentas_de_leitura(Escopo.do_caderno(notebook_id)),
        *ferramentas_de_web(),
        *ferramentas_de_grafo(),
        *ferramentas_de_estudo(notebook_id),
        *ferramentas_de_artefatos(notebook_id),
    ]


def catalogo_global() -> list[BaseTool]:
    """O que o chat **global** expõe: as mesmas ferramentas, outro escopo.

    Nenhuma ferramenta nova de leitura (D039). `listar_fontes` no escopo global vira
    o mapa de todos os cadernos, e `ler_fonte`/`buscar_nas_fontes` alcançam qualquer
    um. Duas listagens parecidas só dariam ao modelo a chance de escolher a errada.

    As de estudo ficam de fora: "o que meu material não cobre" só faz sentido amarrado
    a um caderno, e um card é revisão de UMA matéria. A de artefato também fica: um
    documento é de um caderno, e a ferramenta não recebe `notebook_id` por parâmetro
    (D034) — oferecê-la aqui exigiria inventar um jeito de escolher o caderno por
    argumento, que é justamente o que a decisão proíbe.
    """
    return [
        *ferramentas_de_leitura(Escopo.todos()),
        *ferramentas_de_web(),
        *ferramentas_de_grafo(),
    ]


def _montar(modelo, ferramentas, prompt: str, checkpointer) -> Any:
    return create_agent(
        modelo or llm.atual(),
        tools=ferramentas,
        system_prompt=prompt,
        checkpointer=checkpointer,
    )


def montar(
    notebook_id: str,
    *,
    modelo: BaseChatModel | None = None,
    checkpointer: Any = None,
) -> Any:
    """Monta o agente do caderno.

    `modelo` e `checkpointer` existem para o teste injetar: nos testes o modelo é
    falso (sem rede, sem chave) e o checkpointer é um arquivo temporário.
    """
    notebook = get_notebook(notebook_id)
    if notebook is None:
        raise ValueError(f"Caderno '{notebook_id}' não existe.")

    return _montar(
        modelo,
        catalogo(notebook_id),
        build_notebook_prompt(notebook),
        checkpointer,
    )


def montar_global(
    *,
    modelo: BaseChatModel | None = None,
    checkpointer: Any = None,
) -> Any:
    """Monta o agente do chat global — o que enxerga todos os cadernos."""
    return _montar(modelo, catalogo_global(), build_global_prompt(), checkpointer)


async def responder(agente: Any, config: dict[str, Any], texto: str) -> str:
    """Uma volta completa: manda a mensagem e devolve o texto final.

    O histórico não é passado aqui — quem guarda é o checkpointer, por thread
    (D019). O chamador só entrega o que a pessoa acabou de escrever. O `config` é
    de quem chama porque é ele que sabe *qual conversa* é esta: o thread de um
    caderno (`checkpoint.config`) ou o do chat global (`checkpoint.config_global`).
    """
    saida = await agente.ainvoke(
        {"messages": [{"role": "user", "content": texto}]},
        config,
    )
    return saida["messages"][-1].content


async def eventos(
    agente: Any, config: dict[str, Any], texto: str
) -> AsyncIterator[tuple[str, dict[str, Any]]]:
    """A conversa em eventos, no formato que a interface **já** consome.

    A interface não sabe o que é LangGraph: ela espera `assistant.delta`,
    `tool.started`, `assistant.completed`, `error` e `done`. Este gerador é a
    fronteira de tradução — trocar o motor por baixo não mexeu em uma linha de UI.

    Os nomes de evento do LangGraph foram **descobertos rodando**
    (`astream_events(v2)` com o modelo falso), não deduzidos da documentação.
    """
    yield "run.started", {}

    acumulado: list[str] = []
    apos_ferramenta = False
    try:
        async for evento in agente.astream_events(
            {"messages": [{"role": "user", "content": texto}]},
            config,
            version="v2",
        ):
            nome = evento["event"]

            if nome == "on_chat_model_stream":
                # Chunk de conteúdo vazio é o que carrega tool call: é maquinaria,
                # não texto para a tela. Filtrar aqui evita delta vazio no front.
                pedaco = getattr(evento["data"].get("chunk"), "content", "") or ""
                if pedaco:
                    # Texto que vem DEPOIS de uma ferramenta pertence a outra
                    # chamada ao modelo. Sem separador, as duas falas chegam
                    # coladas na tela ("...na fonte.**ZULU-90210**").
                    if apos_ferramenta and acumulado:
                        acumulado.append("\n\n")
                        yield "assistant.delta", {"delta": "\n\n"}
                    apos_ferramenta = False
                    acumulado.append(pedaco)
                    yield "assistant.delta", {"delta": pedaco}

            elif nome == "on_tool_start":
                yield "tool.started", {
                    "tool_name": evento["name"],
                    "args": evento["data"].get("input") or {},
                }

            elif nome == "on_tool_end":
                apos_ferramenta = True
                yield "tool.completed", {"tool_name": evento["name"]}

    except Exception as exc:
        log.exception("falha no stream do agente")
        yield "error", {"message": f"{type(exc).__name__}: {exc}{llm.explicar(exc)}"}
        yield "done", {}
        return

    yield "assistant.completed", {"content": "".join(acumulado)}
    yield "done", {}


# tipo LangChain -> papel na interface
_PAPEIS = {"human": "user", "ai": "assistant"}


async def historico(agente: Any, config: dict[str, Any]) -> list[dict[str, Any]]:
    """A conversa como a interface mostra: só o que a pessoa vê.

    Sai do **checkpointer** (D019), a mesma fonte que o agente usa para lembrar —
    então o que está na tela é exatamente o que ele tem em contexto. Mensagem de
    ferramenta e resposta sem texto ficam de fora: são maquinaria, não conversa.
    """
    estado = await agente.aget_state(config)
    mensagens = (estado.values or {}).get("messages", []) if estado else []

    conversa: list[dict[str, Any]] = []
    for mensagem in mensagens:
        papel = _PAPEIS.get(getattr(mensagem, "type", ""))
        conteudo = mensagem.content if isinstance(mensagem.content, str) else ""
        if not (papel and conteudo.strip()):
            continue
        # Duas chamadas ao modelo (a do tool call e a final) produzem duas
        # AIMessage. Na tela isso é UMA resposta — e o stream também as junta,
        # então separar aqui faria o recarregamento mostrar diferente do ao vivo.
        if conversa and papel == "assistant" and conversa[-1]["role"] == "assistant":
            conversa[-1]["content"] += "\n\n" + conteudo
        else:
            conversa.append({"role": papel, "content": conteudo, "created_at": None})
    return conversa
