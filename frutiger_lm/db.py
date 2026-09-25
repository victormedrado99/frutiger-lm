"""SQLite: notebooks, fontes e outputs.

Uma conexão por chamada (sqlite3 é baratinho) para não brigar com threads
do uvicorn. WAL ligado para leitura concorrente durante escrita.
"""

from __future__ import annotations

import shutil
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any

from .config import settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS notebooks (
    id                TEXT PRIMARY KEY,
    title             TEXT NOT NULL,
    description       TEXT NOT NULL DEFAULT '',
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


def _migrar(conn: sqlite3.Connection) -> None:
    """Ajustes de schema para bancos que já existem.

    Sem framework de migração, de propósito: é um banco, um dono, e as mudanças
    são poucas. Uma DDL idempotente por mudança resolve — e como o SQLite não tem
    ``DROP COLUMN IF EXISTS``, a checagem é explícita.
    """
    colunas = {linha["name"] for linha in _rows(conn.execute("PRAGMA table_info(notebooks)"))}
    if "hermes_session_id" in colunas:
        # a sessão do Hermes morreu com o motor próprio: o histórico agora é o
        # thread do checkpointer (D019)
        conn.execute("ALTER TABLE notebooks DROP COLUMN hermes_session_id")


def init_db() -> None:
    with connect() as conn:
        conn.executescript(SCHEMA)
        _migrar(conn)


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
        return _rows(conn.execute(
            """
            SELECT n.*,
                   (SELECT COUNT(*) FROM sources s WHERE s.notebook_id = n.id) AS source_count,
                   (SELECT COUNT(*) FROM outputs o WHERE o.notebook_id = n.id) AS output_count
            FROM notebooks n
            ORDER BY n.updated_at DESC
            """
        ))


def list_notebooks_por_criacao() -> list[dict[str, Any]]:
    """Cadernos em ordem de criação — a ordem canônica da citação no chat global.

    Diferente de `list_notebooks`, que ordena por `updated_at` (o que a home quer:
    o que você mexeu por último primeiro). Aqui a ordem tem que ser **estável**:
    se ela mudasse ao editar um caderno, uma citação `[3]` numa mensagem antiga
    passaria a apontar para outra fonte.
    """
    with connect() as conn:
        return _rows(conn.execute("SELECT * FROM notebooks ORDER BY created_at ASC"))


def fontes_ativas_globais() -> list[dict[str, Any]]:
    """Todas as fontes ativas de todos os cadernos, em ordem canônica.

    A numeração `[n]` do chat global é a **posição nesta lista**. Quem monta o
    índice do prompt e quem lista por ferramenta usam esta mesma função — se
    divergissem, o modelo citaria `[3]` apontando para a fonte errada.
    """
    with connect() as conn:
        return _rows(conn.execute(
            """
            SELECT s.*, n.title AS notebook_title
            FROM sources s
            JOIN notebooks n ON n.id = s.notebook_id
            WHERE s.active = 1 AND s.status = 'ready'
            ORDER BY n.created_at ASC, s.created_at ASC
            """
        ))


def build_global_index(*, por_caderno: int = 8) -> str:
    """O mapa de todos os cadernos, para o prompt do chat global.

    Calculado na hora, sem cache: é uma consulta e formatação de texto. Um cache
    com invalidação só se pagaria se isto crescesse muito — e crescer é sinal de
    que a ferramenta de busca é o caminho, não o índice.

    ``por_caderno`` limita quantas fontes aparecem de cada caderno (D035: saída
    limitada); o número entre colchetes é a posição real, então truncar não
    desloca citação.
    """
    cadernos = list_notebooks_por_criacao()
    if not cadernos:
        return ""

    fontes = fontes_ativas_globais()
    numeradas = {f["id"]: i for i, f in enumerate(fontes, start=1)}

    linhas = [f"## Seus cadernos ({len(cadernos)})\n"]
    for caderno in cadernos:
        minhas = [f for f in fontes if f["notebook_id"] == caderno["id"]]
        linhas.append(f"### {caderno['title']}")
        if caderno.get("description"):
            linhas.append(caderno["description"])
        if not minhas:
            linhas.append("(sem fontes ativas)")
        else:
            for fonte in minhas[:por_caderno]:
                linhas.append(
                    f"[{numeradas[fonte['id']]}] {fonte['title']} "
                    f"({fonte['kind']}, {fonte['chars']} chars) id: {fonte['id']}"
                )
            if len(minhas) > por_caderno:
                linhas.append(f"(e mais {len(minhas) - por_caderno} fontes neste caderno)")
        linhas.append("")

    return "\n".join(linhas)


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
    allowed = {"title", "description"}
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


def _apagar_arquivo(caminho: str) -> None:
    """Apaga um arquivo nosso — e só se estiver dentro do diretório de dados.

    A guarda não é paranoia: `path` vem do banco, e sem ela um registro
    corrompido viraria um `unlink` em qualquer lugar do disco.
    """
    if not caminho:
        return
    alvo = Path(caminho)
    if not alvo.resolve().is_relative_to(settings.data_dir.resolve()):
        return
    alvo.unlink(missing_ok=True)


def delete_notebook(notebook_id: str) -> None:
    """Apaga o caderno **e os arquivos dele**.

    Os arquivos saem aqui, e não na rota, por um motivo aprendido na prática:
    apagar um caderno é uma operação só, e deixá-la partida entre camadas garante
    que algum chamador — script, rotina futura, código de limpeza — apague as
    linhas e deixe a pasta no disco. Foi exatamente o que aconteceu.
    """
    with connect() as conn:
        conn.execute("DELETE FROM notebooks WHERE id = ?", (notebook_id,))
    shutil.rmtree(settings.notebook_dir(notebook_id), ignore_errors=True)


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
    """A fonte, com o título do caderno junto.

    O título do caderno vem **sempre**, e não só quando pedido: o chat global
    precisa dizer de qual caderno veio a fonte que ele leu, e uma consulta extra a
    cada leitura não se paga. É um join por chave primária.
    """
    with connect() as conn:
        row = conn.execute(
            """
            SELECT s.*, n.title AS notebook_title
            FROM sources s
            JOIN notebooks n ON n.id = s.notebook_id
            WHERE s.id = ?
            """,
            (source_id,),
        ).fetchone()
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


def delete_source(source_id: str) -> str | None:
    """Apaga a fonte **e o arquivo de texto dela**. Devolve o id do caderno."""
    src = get_source(source_id)
    if not src:
        return None
    with connect() as conn:
        conn.execute("DELETE FROM sources WHERE id = ?", (source_id,))
    _apagar_arquivo(src["path"])
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

def read_source_text(source: dict[str, Any]) -> str:
    """Lê o .txt extraído da fonte. Tolerante a arquivo ausente."""
    try:
        with open(source.get("path") or "", encoding="utf-8", errors="replace") as fh:
            return fh.read()
    except OSError:
        return ""


def build_context(
    notebook: dict[str, Any], *, inline_limit: int
) -> tuple[str, list[dict[str, Any]]]:
    """Monta as fontes ativas.

    Retorna (bloco_de_contexto, lista_de_fontes_usadas).
    Se o total couber em `inline_limit`, o texto vai inteiro no prompt.
    Caso contrário devolve só o índice das fontes — **com o id delas** — e o
    agente lê pelas ferramentas de leitura do motor (D034).

    O índice entrega o **id**, não o caminho no disco: as ferramentas aceitam id,
    e caminho de arquivo não serve para nada além de confundir o modelo.
    """
    sources = list_sources(notebook["id"], active_only=True)
    if not sources:
        return "", []

    texts = [(s, read_source_text(s)) for s in sources]
    total = sum(len(t) for _, t in texts)

    lines: list[str] = []
    if total and total <= inline_limit:
        lines.append("## Conteúdo das fontes (íntegra)\n")
        for i, (src, text) in enumerate(texts, 1):
            lines.append(f"### [{i}] {src['title']}  ({src['kind']})\n{text}\n")
    else:
        lines.append(
            "## Fontes deste caderno\n"
            "O conteúdo é grande demais para caber aqui, então ele NÃO está "
            "abaixo. Use `buscar_nas_fontes` para achar um termo e `ler_fonte` "
            "para ler o trecho — essas ferramentas já sabem de qual caderno se "
            "trata. NUNCA responda de memória sobre o conteúdo das fontes.\n"
        )
        for i, (src, text) in enumerate(texts, 1):
            lines.append(
                f"- [{i}] {src['title']}  ({src['kind']}, {len(text)} chars)  id: {src['id']}"
            )

    return "\n".join(lines), sources


def context_mode(notebook: dict[str, Any], *, inline_limit: int) -> str:
    """Mesma régua que build_context usa, sem tocar no disco.

    `chars` é gravado como o tamanho exato do arquivo da fonte, então somar a
    coluna dá o mesmo total que build_context lê.
    """
    sources = list_sources(notebook["id"], active_only=True)
    if not sources:
        return "empty"
    return "inline" if sum(s["chars"] for s in sources) <= inline_limit else "files"
