"""O modelo de embedding (F6) — infraestrutura, não agente.

Embedding não conversa: transforma texto em vetor. Por isso ele não entra no catálogo
de ferramentas e não passa pelo agente — é a mesma separação que a seção 5 do PROJETO
já declarava: embeddings servem às arestas por similaridade, e não são uma capacidade
do assistente. Quem decide *o que* vira vetor é `engine/similaridade.py`; aqui só mora
a fábrica e a montagem do texto.

Duas fontes de config, na ordem da D031: o que a UI salvou (o bloco `embed_*` do
`model.json`) e, na falta dele, o que o `.env` declara em
``LLM_EMBED=openai|<base_url>|<modelo>|<chave>``.

Um detalhe do mundo real que a tela precisa dizer, e que o app não esconde: **nem todo
provedor de conversa oferece embedding.** A DeepSeek — que é o provedor configurado
neste projeto — não oferece. Quem quer as arestas por similaridade aponta o bloco de
embedding para um modelo local (LM Studio, llama.cpp) ou para outro provedor.
"""

from __future__ import annotations

import hashlib

from langchain_core.embeddings import Embeddings
from langchain_openai import OpenAIEmbeddings

from ..model_store import ModelConfig, load, spec_embed_do_env

# A lib exige o campo de chave preenchido; endereço local ignora o valor.
_CHAVE_LOCAL = "nao-precisa"

# Quanto texto de cada conceito entra no vetor (D061). O sinal está na primeira frase
# de cada trecho: o resto dilui e custa. Medido pelo efeito — o limite existe para o
# embedding não virar "a fonte inteira", que é outro produto.
TEXTO_LIMITE = 1_200

# Quantos trechos do conceito entram (o mesmo número que o documento usa, D061).
TRECHOS = 2

TIMEOUT_S = 60.0


class EmbeddingNaoConfigurado(RuntimeError):
    """Sem endereço/modelo de embedding — o recurso não existe, e a tela diz isso."""


def build(cfg: ModelConfig) -> Embeddings:
    if not cfg.configurado:
        raise EmbeddingNaoConfigurado(
            "Modelo de embedding não configurado: falta "
            + ", ".join(_falta(cfg))
            + ". O bloco \"Embeddings\" no modal de Modelo aponta para um provedor "
            "que ofereça vetores (a DeepSeek não oferece; um servidor local, como o "
            "LM Studio ou o llama.cpp, oferece)."
        )
    return OpenAIEmbeddings(
        base_url=cfg.base_url,
        api_key=cfg.api_key or _CHAVE_LOCAL,
        model=cfg.model,
        # As duas correções que a própria lib recomenda para provedor
        # OpenAI-compatível que não é a OpenAI — e as duas foram descobertas aqui,
        # contra o llama-server local, depois de um erro que não ajuda em nada:
        #
        # 1. `check_embedding_ctx_length=False`. Por padrão a lib **tokeniza o texto
        #    localmente** (com o tokenizador do OpenAI) e manda os IDs no lugar do
        #    texto. Um servidor local recebe IDs que não existem no vocabulário dele e
        #    responde `400 Prompt contains invalid tokens` — que parece defeito do
        #    modelo, é o cliente que está falando a língua errada, e some assim que se
        #    manda texto em vez de ID.
        # 2. `encoding_format: float`. Sem isto o cliente pede base64; o llama-server
        #    aceita, mas nem todo provedor compatível implementa, e float é o que os
        #    dois mundos entendem.
        check_embedding_ctx_length=False,
        model_kwargs={"encoding_format": "float"},
        timeout=TIMEOUT_S,
        max_retries=2,
    )


def _falta(cfg: ModelConfig) -> list[str]:
    falta = []
    if not cfg.base_url:
        falta.append("endereço")
    if not cfg.model:
        falta.append("modelo")
    if cfg.precisa_de_chave and not cfg.api_key:
        falta.append("chave da API")
    return falta


def resolve() -> ModelConfig:
    """Qual modelo embeda: o da UI → o do `.env` → vazio.

    Note que a config do `.env` volta nos campos do CONVERSATION (`base_url`, `model`,
    `api_key`) e não nos `embed_*`: os dois caminhos de config chegam aqui virando a
    mesma coisa — "o modelo que embeda" — e quem chama não precisa saber de onde veio.
    """
    cfg = load()
    if cfg.embed_configurado:
        return ModelConfig(
            base_url=cfg.embed_base_url,
            model=cfg.embed_model,
            api_key=cfg.embed_api_key,
        )
    return spec_embed_do_env() or ModelConfig()


def atual() -> Embeddings:
    """O modelo de embedding que o app deve usar agora."""
    return build(resolve())


def configurado() -> bool:
    """Sem modelo de embedding o recurso não aparece — a tela pergunta antes de tentar."""
    return resolve().configurado


def texto_do_conceito(nome: str, trechos: list[str], *, limite: int = TEXTO_LIMITE) -> str:
    """O texto que vira vetor: **o nome e o que o material diz sobre ele** (D061).

    O nome sozinho não serve neste material: os conceitos são em boa parte códigos
    curtos (`ISO 14230`, `ISO 15765`, `KB1`), e no espaço semântico todos ficam na
    mesma vizinhança — a aresta sairia ligando dois códigos que não têm nada a ver. Os
    trechos são o que separa um código do outro.

    São os MESMOS trechos que sustentam o documento compilado: o que o vetor usa
    também é conferível na fonte.
    """
    partes = [" ".join(str(nome or "").split())]
    for trecho in trechos[:TRECHOS]:
        limpo = " ".join(str(trecho or "").split())
        if limpo:
            partes.append(limpo)
    return " — ".join(p for p in partes if p)[:limite]


def hash_do_texto(texto: str) -> str:
    """A impressão do texto, para decidir se o vetor guardado ainda vale (D062).

    Curto de propósito: não é segurança, é comparação. 16 dígitos hexadecimais de
    SHA-256 já distinguem textos diferentes neste universo, e o banco fica legível.
    """
    return hashlib.sha256(str(texto).encode("utf-8")).hexdigest()[:16]
