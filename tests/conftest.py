"""Ambiente dos testes.

O CADERNO_DATA_DIR precisa estar definido ANTES de importar o pacote, porque
`caderno.config` resolve os caminhos no import. Por isso os imports ficam
depois do setup, com noqa.
"""

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

os.environ["CADERNO_DATA_DIR"] = tempfile.mkdtemp(prefix="caderno-tests-")
os.environ["HERMES_URL"] = "http://127.0.0.1:1"  # o motor nunca é chamado aqui
os.environ.setdefault("HERMES_KEY", "chave-de-teste")

import pytest  # noqa: E402

from caderno import db  # noqa: E402

db.init_db()


@pytest.fixture(autouse=True)
def banco_limpo():
    """Isola os testes: zera as tabelas antes de cada um."""
    with db.connect() as conn:
        for tabela in ("outputs", "sources", "notebooks"):
            conn.execute(f"DELETE FROM {tabela}")  # noqa: S608 (nome fixo, não vem de fora)
    yield
