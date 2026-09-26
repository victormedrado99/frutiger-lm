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
from typing import Any

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

# Sugestão de modelo de embedding por provedor. Vazio onde não há como saber: num
# servidor local o nome é o do modelo que está carregado. A DeepSeek não está na
# lista de propósito — ela não oferece endpoint de embedding, e sugerir um nome ali
# só faria a pessoa perder tempo.
PRESETS_EMBED: dict[str, str] = {
    "openai": "text-embedding-3-small",
    "lmstudio": "text-embedding-nomic-embed-text-v1.5",
}


def precisa_de_chave(base_url: str) -> bool:
    """Endereço local não pede chave — é o caso do LM Studio / llama.cpp."""
    return not any(host in (base_url or "") for host in _LOCAIS)


@dataclass
class ModelConfig:
    """O que o motor precisa para falar com um modelo.

    São **dois** modelos, e por isso dois blocos de campos: o de conversa (o agente,
    os documentos) e o de embedding (o F6, que só produz vetores). O de embedding é
    opcional — sem ele o app funciona inteiro, menos as arestas por similaridade.

    Os dois moram no MESMO arquivo por causa da regra de instância (D030): um
    diretório de dados é uma instância, e um segundo arquivo de segredo seria uma
    segunda coisa a lembrar de não compartilhar.
    """

    base_url: str = ""
    model: str = ""
    api_key: str = ""
    temperature: float = 0.2
    embed_base_url: str = ""
    embed_model: str = ""
    embed_api_key: str = ""

    @property
    def precisa_de_chave(self) -> bool:
        return precisa_de_chave(self.base_url)

    @property
    def embed_precisa_de_chave(self) -> bool:
        return precisa_de_chave(self.embed_base_url)

    @property
    def configurado(self) -> bool:
        return not faltando(self)

    @property
    def embed_configurado(self) -> bool:
        return not faltando_embed(self)

    def dica_da_chave(self) -> str:
        """Máscara para a UI: nunca o valor, só o suficiente para reconhecer."""
        return _mascara(self.api_key)

    def dica_da_chave_embed(self) -> str:
        return _mascara(self.embed_api_key)


def _mascara(chave: str) -> str:
    if not chave:
        return ""
    if len(chave) <= 8:
        return "•" * len(chave)
    return f"{chave[:4]}{'•' * 6}{chave[-4:]}"


def faltando(cfg: ModelConfig) -> list[str]:
    """O que impede este modelo de funcionar, nomeado para mostrar na tela.

    Existe porque salvar só a chave (com endereço e modelo em branco) produzia
    uma configuração inutilizável **em silêncio** — o app dizia "salvo" e o chat
    não funcionava depois. Nomear o que falta é a diferença entre um erro que a
    pessoa resolve em dez segundos e um mistério.
    """
    falta = []
    if not cfg.base_url:
        falta.append("endereço")
    if not cfg.model:
        falta.append("modelo")
    if cfg.precisa_de_chave and not cfg.api_key:
        falta.append("chave da API")
    return falta


def faltando_embed(cfg: ModelConfig) -> list[str]:
    """O mesmo rigor para o modelo de embedding (F6).

    Endereço e modelo são obrigatórios quando a pessoa começa a configurar o
    embedding; sem nada preenchido, o recurso simplesmente não existe — e a tela diz
    isso em vez de falhar no meio do cálculo.
    """
    if not cfg.embed_base_url and not cfg.embed_model:
        return ["endereço", "modelo"]
    falta = []
    if not cfg.embed_base_url:
        falta.append("endereço")
    if not cfg.embed_model:
        falta.append("modelo")
    if cfg.embed_precisa_de_chave and not cfg.embed_api_key:
        falta.append("chave da API")
    return falta


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
    """O que a UI pode ver. Note: sem as chaves, por construção (regra 1)."""
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
        # O bloco do embedding (F6), pelo MESMO contrato: a chave nunca sai daqui.
        "embed_configured": cfg.embed_configurado,
        "embed_base_url": cfg.embed_base_url,
        "embed_model": cfg.embed_model,
        "embed_has_key": bool(cfg.embed_api_key),
        "embed_key_hint": cfg.dica_da_chave_embed(),
        "embed_needs_key": cfg.embed_precisa_de_chave,
        "embed_presets": PRESETS_EMBED,
        "embed_faltando": faltando_embed(cfg) if cfg.embed_configurado else [],
    }


def montar(
    base_url: str,
    model: str,
    api_key: str | None,
    temperature: float | None,
    *,
    embed_base_url: str | None = None,
    embed_model: str | None = None,
    embed_api_key: str | None = None,
) -> ModelConfig:
    """Monta a config a partir do formulário, **sem gravar**.

    Separado de `save` para que a rota valide antes de escrever. Foi justamente
    gravar primeiro e nunca validar que deixou passar uma config inutilizável.

    ``api_key=None`` significa "não mexi no campo" e preserva a chave que já
    estava salva — sem isso, salvar o formulário com o campo mascarado apagaria
    a chave do usuário. Vale igual para a chave do embedding (F6).

    O endereço e o modelo do embedding são strings comuns (o formulário manda o que
    está lá): campo apagado é pedido explícito de tirar o embedding. Já a chave,
    não — ela volta mascarada, e vazia significa "não mexi".
    """
    atual = load()
    return ModelConfig(
        base_url=(base_url or "").strip().rstrip("/"),
        model=(model or "").strip(),
        api_key=atual.api_key if api_key is None else str(api_key).strip(),
        temperature=atual.temperature if temperature is None else float(temperature),
        embed_base_url=(
            atual.embed_base_url if embed_base_url is None else embed_base_url.strip().rstrip("/")
        ),
        embed_model=(atual.embed_model if embed_model is None else embed_model.strip()),
        embed_api_key=(
            atual.embed_api_key if embed_api_key is None else str(embed_api_key).strip()
        ),
    )


def apply(
    base_url: str,
    model: str,
    api_key: str | None,
    temperature: float | None,
    **extras: Any,
) -> ModelConfig:
    """Conveniência: montar e gravar. Use `montar` quando precisar validar antes."""
    cfg = montar(base_url, model, api_key, temperature, **extras)
    save(cfg)
    return cfg


def _spec(prefixo: str) -> ModelConfig | None:
    """Lê o formato `openai|<base_url>|<modelo>|<chave>` de uma variável de ambiente."""
    bruto = os.environ.get(prefixo, "").strip()
    if not bruto:
        return None
    partes = [p.strip() for p in bruto.split("|")]
    if len(partes) < 3:
        return None
    _, base_url, model, *resto = partes
    return ModelConfig(base_url=base_url, model=model, api_key=(resto[0] if resto else ""))


def spec_do_env() -> ModelConfig | None:
    """Fallback de quem prefere versionar a config em vez de usar a UI.

    Formato: ``LLM_AGENT=openai|<base_url>|<modelo>|<chave>``
    O prefixo ``openai`` existe para deixar espaço a outros protocolos sem
    quebrar o formato depois.
    """
    return _spec("LLM_AGENT")


def spec_embed_do_env() -> ModelConfig | None:
    """O mesmo, para o modelo de embedding (F6): ``LLM_EMBED=openai|<url>|<modelo>|<chave>``.

    Devolve a config no campo do CONVERSATION de propósito, e não no do embedding:
    quem chama (`engine/embed.py`) quer saber qual modelo usar para embedar, e o nome
    do bloco é um detalhe de armazenamento. Assim as duas fontes de config (UI e .env)
    chegam ao mesmo lugar antes de virar modelo.
    """
    return _spec("LLM_EMBED")
