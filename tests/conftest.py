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
from frutiger_lm.config import settings  # noqa: E402
from frutiger_lm.engine import oficina  # noqa: E402

db.init_db()

# Estado que não mora nas tabelas e por isso escapava da limpeza.
ARQUIVOS_DE_ESTADO = (
    "model.json",  # a config do modelo (e a chave)
    "checkpoints.db",  # a conversa
    "checkpoints.db-wal",
    "checkpoints.db-shm",
)


@pytest.fixture(autouse=True)
def estado_limpo():
    """Isola os testes: zera as tabelas **e** os arquivos de estado.

    Os dois lados importam. Limpar só as tabelas deixa a conversa viva no
    `checkpoints.db`, e aí um teste enxerga o histórico do anterior — aconteceu de
    verdade quando esta limpeza morava só no arquivo de testes do motor, e o
    arquivo novo não a tinha.
    """
    alvos = [settings.data_dir / nome for nome in ARQUIVOS_DE_ESTADO]

    def limpar() -> None:
        with db.connect() as conn:
            # Ordem: filhas antes das mães, para não depender do CASCADE.
            for tabela in (
                "source_usage",
                "cards",
                "notes",
                "edges",
                "mentions",
                # F6: as duas filhas de `concepts` que nasceram depois
                "suspeitas",
                "embeddings",
                "concepts",
                "outputs",
                "sources",
                "notebooks",
            ):
                conn.execute(f"DELETE FROM {tabela}")  # noqa: S608 (nome fixo)
        for alvo in alvos:
            alvo.unlink(missing_ok=True)
        # A oficina guarda runs em MEMÓRIA (não em tabela), então ela também precisa
        # ser zerada — é o mesmo vazamento que o `checkpoints.db` causava, só que sem
        # arquivo para denunciar.
        oficina.oficina.limpar()

    limpar()
    yield
    limpar()


@pytest.fixture
def cliente():
    """Cliente HTTP do app, com o lifespan rodando de verdade.

    O `with` importa: é ele que abre o checkpointer, então os testes de rota
    exercitam o mesmo ciclo de vida que o app tem em produção.
    """
    from frutiger_lm.app import app

    with TestClient(app) as c:
        yield c
