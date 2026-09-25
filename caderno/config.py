"""Configuração do Caderno — lida de variáveis de ambiente / .env."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _load_dotenv() -> None:
    """Carrega .env do projeto sem depender de python-dotenv."""
    for name in (".env", ".env.local"):
        path = PROJECT_ROOT / name
        if not path.exists():
            continue
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            # não sobrescreve o ambiente real
            os.environ.setdefault(key, value)


_load_dotenv()


def _env(name: str, default: str = "") -> str:
    return (os.environ.get(name) or default).strip()


def _env_int(name: str, default: int) -> int:
    try:
        return int(_env(name) or default)
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    hermes_url: str
    hermes_key: str
    session_key: str
    data_dir: Path
    port: int
    inline_limit: int
    output_model: str

    @property
    def db_path(self) -> Path:
        return self.data_dir / "caderno.db"

    @property
    def notebooks_dir(self) -> Path:
        return self.data_dir / "notebooks"

    def notebook_dir(self, notebook_id: str) -> Path:
        return self.notebooks_dir / notebook_id

    def sources_dir(self, notebook_id: str) -> Path:
        return self.notebook_dir(notebook_id) / "fontes"

    def ensure_dirs(self) -> None:
        self.notebooks_dir.mkdir(parents=True, exist_ok=True)


def load_settings() -> Settings:
    data_dir = Path(_env("CADERNO_DATA_DIR", "./data"))
    if not data_dir.is_absolute():
        data_dir = (PROJECT_ROOT / data_dir).resolve()

    settings = Settings(
        hermes_url=_env("HERMES_URL", "http://127.0.0.1:8642").rstrip("/"),
        hermes_key=_env("HERMES_KEY"),
        session_key=_env("CADERNO_SESSION_KEY", "caderno:local:"),
        data_dir=data_dir,
        port=_env_int("CADERNO_PORT", 8765),
        inline_limit=_env_int("CADERNO_INLINE_LIMIT", 24000),
        output_model=_env("CADERNO_OUTPUT_MODEL"),
    )
    settings.ensure_dirs()
    return settings


settings = load_settings()
