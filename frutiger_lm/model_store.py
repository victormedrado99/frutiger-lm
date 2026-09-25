"""Configuração de modelo — escrita pela UI, lida pelo motor (D020, D030).

Fica em ``<data_dir>/model.json`` com permissão ``0600``. Duas regras de
segurança que valem para sempre:

1. A chave **nunca** sai inteira daqui. O navegador recebe ``configured`` e uma
   dica mascarada, jamais o valor.
2. Modelo local não precisa de chave (D020) — ``127.0.0.1`` e ``localhost`` são
   reconhecidos, então não se exige chave de quem roda LM Studio ou llama.cpp.

O arquivo mora no diretório de dados para preservar a propriedade de "um
diretório = uma instância", que é o que permite rodar várias na VPS. A
contrapartida, documentada no README: **`data/` contém segredo e não se
compartilha**.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path

from .config import settings

# Presets de provedor: (base_url, modelo sugerido). Todos OpenAI-compatíveis
# (D020) — é isso que permite cobrir API e local com a mesma classe.
PRESETS: dict[str, tuple[str, str]] = {
    "deepseek": ("https://api.deepseek.com/v1", "deepseek-chat"),
    "openai": ("https://api.openai.com/v1", "gpt-4o-mini"),
    "openrouter": ("https://openrouter.ai/api/v1", ""),
    "groq": ("https://api.groq.com/openai/v1", ""),
    "lmstudio": ("http://127.0.0.1:1234/v1", ""),
    "llamacpp": ("http://127.0.0.1:8080/v1", ""),
}

_LOCAIS = ("127.0.0.1", "localhost", "0.0.0.0", "::1")


@dataclass
class ModelConfig:
    """O que o motor precisa para falar com um modelo."""

    base_url: str = ""
    model: str = ""
    api_key: str = ""
    temperature: float = 0.2

    @property
    def precisa_de_chave(self) -> bool:
        """Endereço local não pede chave — é o caso do LM Studio / llama.cpp."""
        return not any(host in self.base_url for host in _LOCAIS)

    @property
    def configurado(self) -> bool:
        return bool(
            self.base_url
            and self.model
            and (self.api_key or not self.precisa_de_chave)
        )

    def dica_da_chave(self) -> str:
        """Máscara para a UI: nunca o valor, só o suficiente para reconhecer."""
        if not self.api_key:
            return ""
        if len(self.api_key) <= 8:
            return "•" * len(self.api_key)
        return f"{self.api_key[:4]}{'•' * 6}{self.api_key[-4:]}"


def _caminho() -> Path:
    return settings.data_dir / "model.json"


def load() -> ModelConfig:
    """Lê do disco. Arquivo ausente ou corrompido vira config vazia, não exceção."""
    path = _caminho()
    if not path.exists():
        return ModelConfig()
    try:
        dados = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ModelConfig()
    permitido = {f for f in ModelConfig.__dataclass_fields__}
    return ModelConfig(**{k: v for k, v in dados.items() if k in permitido})


def save(cfg: ModelConfig) -> None:
    """Grava com 0600, de forma atômica — sem janela de arquivo pela metade."""
    path = _caminho()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".model-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(asdict(cfg), fh, ensure_ascii=False, indent=2)
            fh.flush()
            os.fsync(fh.fileno())
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def masked() -> dict:
    """O que a UI pode ver. Note: sem a chave, por construção (regra 1)."""
    cfg = load()
    return {
        "configured": cfg.configurado,
        "base_url": cfg.base_url,
        "model": cfg.model,
        "temperature": cfg.temperature,
        "has_key": bool(cfg.api_key),
        "key_hint": cfg.dica_da_chave(),
        "needs_key": cfg.precisa_de_chave,
        "presets": {nome: {"base_url": url, "model": mod} for nome, (url, mod) in PRESETS.items()},
    }


def apply(base_url: str, model: str, api_key: str | None, temperature: float | None) -> ModelConfig:
    """Atualiza a config vindo da UI.

    ``api_key=None`` significa "não mexi no campo" e preserva a chave que já
    estava salva — sem isso, salvar o formulário com o campo mascarado apagaria
    a chave do usuário.
    """
    atual = load()
    cfg = ModelConfig(
        base_url=(base_url or "").strip().rstrip("/"),
        model=(model or "").strip(),
        api_key=atual.api_key if api_key is None else api_key.strip(),
        temperature=atual.temperature if temperature is None else float(temperature),
    )
    save(cfg)
    return cfg


def spec_do_env() -> ModelConfig | None:
    """Fallback de quem prefere versionar a config em vez de usar a UI.

    Formato: ``LLM_AGENT=openai|<base_url>|<modelo>|<chave>``
    O prefixo ``openai`` existe para deixar espaço a outros protocolos sem
    quebrar o formato depois.
    """
    bruto = os.environ.get("LLM_AGENT", "").strip()
    if not bruto:
        return None
    partes = [p.strip() for p in bruto.split("|")]
    if len(partes) < 3:
        return None
    _, base_url, model, *resto = partes
    return ModelConfig(base_url=base_url, model=model, api_key=(resto[0] if resto else ""))
