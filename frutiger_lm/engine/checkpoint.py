"""Persistência da conversa pelo checkpointer do LangGraph (D019).

Substitui três coisas de uma vez:

- a tabela ``messages`` que eu ia escrever à mão;
- as sessões do Hermes (e a armadilha das sessões órfãs morre junto);
- o versionamento de conversa — o próprio saver guarda o histórico de estados.

Chave natural: **um caderno = um ``thread_id``**.

Arquivo próprio (``checkpoints.db``), e não o mesmo do app (D033): o schema é da
biblioteca, então misturar significaria uma migração dela mexer nas nossas
tabelas. Também evita disputa de lock entre a conexão ``sqlite3`` do app e a
``aiosqlite`` do checkpointer.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from ..config import settings


def caminho() -> str:
    return str(settings.data_dir / "checkpoints.db")


def thread_id(notebook_id: str) -> str:
    """Um caderno, uma linha do tempo (D019).

    O prefixo evita colisão com qualquer outro uso futuro de thread no mesmo
    arquivo, e deixa o id legível ao depurar.
    """
    return f"caderno:{notebook_id}"


def config(notebook_id: str) -> dict[str, Any]:
    """Config do LangGraph para este caderno — o que todo `invoke` precisa.

    Fica aqui, e não no agente, porque é o checkpointer que define a convenção de
    thread. O agente só obedece.
    """
    return {"configurable": {"thread_id": thread_id(notebook_id)}}


@asynccontextmanager
async def aberto() -> AsyncIterator[AsyncSqliteSaver]:
    """Abre, entrega e fecha — para script e teste."""
    async with AsyncSqliteSaver.from_conn_string(caminho()) as saver:
        yield saver


class Checkpoints:
    """Dono do ciclo de vida do saver.

    O lifespan do app manda abrir no start e fechar no shutdown. Fica em objeto,
    e não em global solto, para o teste poder criar instâncias independentes e
    para o erro de "esqueci de abrir" ser explícito em vez de um ``None`` que
    estoura longe da causa.
    """

    def __init__(self) -> None:
        self._cm: object | None = None
        self._saver: AsyncSqliteSaver | None = None

    async def abrir(self) -> None:
        self._cm = AsyncSqliteSaver.from_conn_string(caminho())
        self._saver = await self._cm.__aenter__()  # type: ignore[union-attr]

    async def fechar(self) -> None:
        if self._cm is not None:
            await self._cm.__aexit__(None, None, None)  # type: ignore[union-attr]
        self._cm = self._saver = None

    @property
    def saver(self) -> AsyncSqliteSaver:
        if self._saver is None:
            raise RuntimeError(
                "Checkpointer não foi aberto — quem abre é o lifespan do app "
                "(engine.checkpoint.Checkpoints.abrir)."
            )
        return self._saver

    async def apagar_conversa(self, notebook_id: str) -> None:
        """Esquece a conversa deste caderno — o "limpar chat" da interface."""
        await self.saver.adelete_thread(thread_id(notebook_id))
