"""SQLite: notebooks, fontes e outputs.

Uma conexão por chamada (sqlite3 é baratinho) para não brigar com threads
do uvicorn. WAL ligado para leitura concorrente durante escrita.
"""

from __future__ import annotations

import json
import sqlite3
import time
import uuid
from typing import Any, Iterable

from .config import settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS notebooks (
    id                TEXT PRIMARY KEY,
    title             TEXT NOT NULL,
    description       TEXT NOT NULL DEFAULT '',
    hermes_session_id TEXT,
    created_at        REAL NOT NULL,
    updated_at        REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS sources (
    id           TEXT PRIMARY KEY,
    notebook_id  TEXT NOT NULL REFERENCES notebooks(id) ON DELETE CASCADE,
    title        TEXT NOT NULL,
    kind         TEXT NOT NULL,
    origin       TEXT NOT NULL DEFAULT '',
    path         TEXT NOT NULL DEFAULT '',
    chars        INTEGER NOT NULL DEFAULT 0,
    active       INTEGER NOT NULL DEFAULT 1,
    status       TEXT NOT NULL DEFAULT 'ready',
    error        TEXT NOT NULL DEFAULT '',
    created_at   REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS outputs (
    id           TEXT PRIMARY KEY,
    notebook_id  TEXT NOT NULL REFERENCES notebooks(id) ON DELETE CASCADE,
    template     TEXT NOT NULL,
    title        TEXT NOT NULL,
    content_md   TEXT NOT NULL DEFAULT '',
    created_at   REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_sources_notebook ON sources(notebook_id);
CREATE INDEX IF NOT EXISTS idx_outputs_notebook ON outputs(notebook_id);
"""


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(settings.db_path, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db() -> None:
    with connect() as conn:
        conn.executescript(SCHEMA)


def _now() -> float:
    return time.time()


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def _rows(cursor: sqlite3.Cursor) -> list[dict[str, Any]]:
    return [dict(r) for r in cursor.fetchall()]


# --------------------------------------------------------------------------- #
# Notebooks
# --------------------------------------------------------------------------- #

def create_notebook(title: str, description: str = "") -> dict[str, Any]:
    nb_id = new_id("nb")
    ts = _now()
    with connect() as conn:
        conn.execute(
            "INSERT INTO notebooks (id, title, description, created_at, updated_at)"
            " VALUES (?,?,?,?,?)",
            (nb_id, title.strip() or "Caderno sem nome", description.strip(), ts, ts),
        )
    return get_notebook(nb_id)  # type: ignore[return-value]


def list_notebooks() -> list[dict[str, Any]]:
    with connect() as conn:
        rows = _rows(conn.execute(
            """
            SELECT n.*,
                   (SELECT COUNT(*) FROM sources s WHERE s.notebook_id = n.id) AS source_count,
                   (SELECT COUNT(*) FROM outputs o WHERE o.notebook_id = n.id) AS output_count
            FROM notebooks n
            ORDER BY n.updated_at DESC
            """
        ))
    return rows


def get_notebook(notebook_id: str) -> dict[str, Any] | None:
    with connect() as conn:
        row = conn.execute("SELECT * FROM notebooks WHERE id = ?", (notebook_id,)).fetchone()
        if row is None:
            return None
        data = dict(row)
        data["sources"] = _rows(conn.execute(
            "SELECT * FROM sources WHERE notebook_id = ? ORDER BY created_at ASC", (notebook_id,)
        ))
        data["outputs"] = _rows(conn.execute(
            "SELECT id, notebook_id, template, title, created_at,"
            " length(content_md) AS chars FROM outputs WHERE notebook_id = ?"
            " ORDER BY created_at DESC",
            (notebook_id,),
        ))
    return data


def update_notebook(notebook_id: str, **fields: Any) -> dict[str, Any] | None:
    allowed = {"title", "description", "hermes_session_id"}
    updates = {k: v for k, v in fields.items() if k in allowed and v is not None}
    with connect() as conn:
        if updates:
            sets = ", ".join(f"{k} = ?" for k in updates)
            conn.execute(
                f"UPDATE notebooks SET {sets}, updated_at = ? WHERE id = ?",
                (*updates.values(), _now(), notebook_id),
            )
        else:
            conn.execute("UPDATE notebooks SET updated_at = ? WHERE id = ?", (_now(), notebook_id))
    return get_notebook(notebook_id)


def touch_notebook(notebook_id: str) -> None:
    with connect() as conn:
        conn.execute("UPDATE notebooks SET updated_at = ? WHERE id = ?", (_now(), notebook_id))


def delete_notebook(notebook_id: str) -> None:
    with connect() as conn:
        conn.execute("DELETE FROM notebooks WHERE id = ?", (notebook_id,))


# --------------------------------------------------------------------------- #
# Fontes
# --------------------------------------------------------------------------- #

def create_source(
    notebook_id: str,
    *,
    source_id: str | None = None,
    title: str,
    kind: str,
    origin: str = "",
    path: str = "",
    chars: int = 0,
    status: str = "ready",
    error: str = "",
) -> dict[str, Any]:
    src_id = source_id or new_id("src")
    with connect() as conn:
        conn.execute(
            "INSERT INTO sources (id, notebook_id, title, kind, origin, path, chars,"
            " active, status, error, created_at) VALUES (?,?,?,?,?,?,?,1,?,?,?)",
            (src_id, notebook_id, title, kind, origin, path, chars, status, error, _now()),
        )
    touch_notebook(notebook_id)
    return get_source(src_id)  # type: ignore[return-value]


def get_source(source_id: str) -> dict[str, Any] | None:
    with connect() as conn:
        row = conn.execute("SELECT * FROM sources WHERE id = ?", (source_id,)).fetchone()
    return dict(row) if row else None


def list_sources(notebook_id: str, *, active_only: bool = False) -> list[dict[str, Any]]:
    sql = "SELECT * FROM sources WHERE notebook_id = ?"
    if active_only:
        sql += " AND active = 1 AND status = 'ready'"
    sql += " ORDER BY created_at ASC"
    with connect() as conn:
        return _rows(conn.execute(sql, (notebook_id,)))


def set_source_active(source_id: str, active: bool) -> dict[str, Any] | None:
    with connect() as conn:
        conn.execute("UPDATE sources SET active = ? WHERE id = ?", (1 if active else 0, source_id))
    return get_source(source_id)


def set_source_status(source_id: str, status: str, error: str = "", chars: int | None = None) -> None:
    with connect() as conn:
        if chars is None:
            conn.execute("UPDATE sources SET status = ?, error = ? WHERE id = ?", (status, error, source_id))
        else:
            conn.execute(
                "UPDATE sources SET status = ?, error = ?, chars = ? WHERE id = ?",
                (status, error, chars, source_id),
            )


def delete_source(source_id: str) -> str | None:
    src = get_source(source_id)
    if not src:
        return None
    with connect() as conn:
        conn.execute("DELETE FROM sources WHERE id = ?", (source_id,))
    touch_notebook(src["notebook_id"])
    return src["notebook_id"]


# --------------------------------------------------------------------------- #
# Outputs
# --------------------------------------------------------------------------- #

def create_output(notebook_id: str, template: str, title: str, content_md: str) -> dict[str, Any]:
    out_id = new_id("out")
    with connect() as conn:
        conn.execute(
            "INSERT INTO outputs (id, notebook_id, template, title, content_md, created_at)"
            " VALUES (?,?,?,?,?,?)",
            (out_id, notebook_id, template, title, content_md, _now()),
        )
    touch_notebook(notebook_id)
    return get_output(out_id)  # type: ignore[return-value]


def list_outputs(notebook_id: str) -> list[dict[str, Any]]:
    with connect() as conn:
        return _rows(conn.execute(
            "SELECT * FROM outputs WHERE notebook_id = ? ORDER BY created_at DESC", (notebook_id,)
        ))


def get_output(output_id: str) -> dict[str, Any] | None:
    with connect() as conn:
        row = conn.execute("SELECT * FROM outputs WHERE id = ?", (output_id,)).fetchone()
    return dict(row) if row else None


def delete_output(output_id: str) -> None:
    with connect() as conn:
        conn.execute("DELETE FROM outputs WHERE id = ?", (output_id,))


# --------------------------------------------------------------------------- #
# Contexto para o agente
# --------------------------------------------------------------------------- #

def read_source_text(source: dict[str, Any], *, limit: int | None = None) -> str:
    """Lê o .txt extraído da fonte. Tolerante a arquivo ausente."""
    path = source.get("path") or ""
    if not path:
        return ""
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            text = fh.read()
    except OSError:
        return ""
    if limit is not None and len(text) > limit:
        return text[:limit]
    return text


def build_context(
    notebook: dict[str, Any], *, inline_limit: int
) -> tuple[str, list[dict[str, Any]]]:
    """Monta as fontes ativas.

    Retorna (bloco_de_contexto, lista_de_fontes_usadas).
    Se o total couber em `inline_limit`, o texto vai inteiro no prompt.
    Caso contrário devolve só o índice e o agente consulta os arquivos com as
    tools de leitura dele (read_file / search_files / terminal).
    """
    sources: Iterable[dict[str, Any]] = list_sources(notebook["id"], active_only=True)
    sources = list(sources)
    if not sources:
        return "", []

    texts = [(s, read_source_text(s)) for s in sources]
    total = sum(len(t) for _, t in texts)

    lines: list[str] = []
    if total and total <= inline_limit:
        lines.append("## Conteúdo das fontes (íntegra)\n")
        for i, (src, text) in enumerate(texts, 1):
            lines.append(f"### [{i}] {src['title']}  ({src['kind']})\n{text}\n")
        mode = "inline"
    else:
        lines.append(
            "## Fontes em disco\n"
            "O conteúdo é grande demais para caber aqui. Leia os arquivos com as"
            " ferramentas de leitura (read_file, search_files) ou shell (grep/wc)"
            " antes de responder. NUNCA responda de memória.\n"
        )
        for i, (src, text) in enumerate(texts, 1):
            lines.append(f"- [{i}] {src['title']}  ({src['kind']}, {len(text)} chars) -> {src['path']}")
        mode = "files"

    return "\n".join(lines), sources


def context_mode(notebook: dict[str, Any], *, inline_limit: int) -> str:
    sources = list_sources(notebook["id"], active_only=True)
    total = sum(read_source_text(s, limit=inline_limit + 1).__len__() for s in sources)
    if not sources:
        return "empty"
    return "inline" if total <= inline_limit else "files"
