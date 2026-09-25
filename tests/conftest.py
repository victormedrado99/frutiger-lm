"""Ambiente dos testes.

O FRUTIGER_DATA_DIR precisa estar definido ANTES de importar o pacote, porque
`frutiger_lm.config` resolve os caminhos no import. Por isso os imports ficam
depois do setup, com noqa.
"""

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

os.environ["FRUTIGER_DATA_DIR"] = tempfile.mkdtemp(prefix="frutiger-tests-")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from frutiger_lm import db  # noqa: E402

db.init_db()


@pytest.fixture(autouse=True)
def banco_limpo():
    """Isola os testes: zera as tabelas antes de cada um."""
    with db.connect() as conn:
        for tabela in ("outputs", "sources", "notebooks"):
            conn.execute(f"DELETE FROM {tabela}")  # noqa: S608 (nome fixo, não vem de fora)
    yield


@pytest.fixture
def cliente():
    """Cliente HTTP do app, com o lifespan rodando de verdade.

    O `with` importa: é ele que abre o checkpointer, então os testes de rota
    exercitam o mesmo ciclo de vida que o app tem em produção.
    """
    from frutiger_lm.app import app

    with TestClient(app) as c:
        yield c
