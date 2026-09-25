"""Fábrica de modelo — a única porta para o modelo (D018, D020).

Uma classe cobre todos os provedores porque todos falam OpenAI-compatível:
OpenAI, DeepSeek, OpenRouter, Groq, vLLM, LM Studio (``:1234/v1``),
llama.cpp (``:8080/v1``) e Ollama (via ``/v1``). Trocar de provedor é mudar
configuração, nunca código — é a D020 em uma linha.
"""

from __future__ import annotations

from langchain_core.language_models import BaseChatModel
from langchain_openai import ChatOpenAI

from ..model_store import ModelConfig, load, spec_do_env

# A lib exige o campo de chave preenchido; endereço local ignora o valor.
_CHAVE_LOCAL = "nao-precisa"

TIMEOUT_S = 60.0


class ModeloNaoConfigurado(RuntimeError):
    """Falta base_url, modelo — ou chave, sendo provedor remoto."""


def build(cfg: ModelConfig) -> BaseChatModel:
    if not cfg.configurado:
        falta = [nome for nome, ok in (
            ("base_url", cfg.base_url),
            ("modelo", cfg.model),
            ("chave", cfg.api_key or not cfg.precisa_de_chave),
        ) if not ok]
        raise ModeloNaoConfigurado(
            "Modelo não configurado: falta " + ", ".join(falta) + ". "
            "Use o botão \"Modelo\" na tela inicial."
        )
    return ChatOpenAI(
        base_url=cfg.base_url,
        api_key=cfg.api_key or _CHAVE_LOCAL,
        model=cfg.model,
        temperature=cfg.temperature,
        timeout=TIMEOUT_S,
        max_retries=2,
    )


def resolve() -> ModelConfig:
    """Ordem: o que a UI salvou (model.json) → o que o .env declara → vazio.

    A UI ganha porque foi ela que a pessoa usou por último de forma explícita;
    o .env é o caminho de quem prefere versionar a configuração.
    """
    cfg = load()
    return cfg if cfg.configurado else (spec_do_env() or cfg)


def atual() -> BaseChatModel:
    """O modelo que o app deve usar agora."""
    return build(resolve())
