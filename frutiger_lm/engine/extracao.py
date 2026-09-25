"""Extração de conceitos de um texto (F3).

Não é subgrafo do LangGraph (D044): é lote — fatiar, chamar, validar, gravar. Um
grafo de nós e arestas aqui seria cerimônia sem ganho.

O que este módulo faz de mais valioso é **entregar ao modelo o vocabulário que já
existe**, com instrução de reusar o nome (D041). Sem isso o grafo fragmenta em
`OBD2` / `OBD-II` / `OBD II` e a única saída seria deduplicar por embedding — ou
seja, o F6 viraria pré-requisito de uma fase anterior.

E o que ele **não** faz, de propósito: não decide o que é conceito importante. O
modelo aponta, a validação confere, e a curadoria é da pessoa, na tela do conceito.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from pydantic import BaseModel, Field

from .. import db, knowledge
from . import llm

# --------------------------------------------------------------------------
# O que pedimos ao modelo — e a forma exata, validada pelo provedor (D021)
# --------------------------------------------------------------------------


class ConceitoExtraido(BaseModel):
    """Um conceito e o trecho que o ancora."""

    nome: str = Field(description="O nome do conceito, curto e específico.")
    trecho: str = Field(
        description=(
            "Trecho LITERAL do texto que menciona este conceito. Copie exatamente, "
            "sem corrigir, resumir ou reescrever. Será conferido contra o material."
        )
    )
    tipo: str = Field(
        default="conceito",
        description="conceito · tecnologia · norma · organizacao · metrica · pessoa",
    )


class RelacaoExtraida(BaseModel):
    """Duas coisas que o texto liga explicitamente — e o que sustenta a ligação."""

    de: str = Field(description="Nome de um dos conceitos extraídos.")
    para: str = Field(description="Nome do outro conceito.")
    trecho: str = Field(
        description="Trecho LITERAL do texto que afirma esta relação."
    )


class Extracao(BaseModel):
    conceitos: list[ConceitoExtraido] = Field(default_factory=list)
    relacoes: list[RelacaoExtraida] = Field(default_factory=list)


INSTRUCOES = """Você extrai conhecimento estruturado de um trecho de material de estudo.

1. Extraia os CONCEITOS que o trecho realmente trata: tecnologias, normas, processos,
   métricas, técnicas. Não liste palavras frequentes nem termos genéricos.
2. Para cada conceito, devolva um TRECHO LITERAL do texto que o menciona. Copie
   exatamente, sem corrigir, sem resumir, sem reescrever. O trecho é conferido
   contra o material e um trecho que não existir é descartado — então não invente.
3. Prefira reusar os nomes da lista de conceitos que já existem, quando for o mesmo
   conceito. Não invente variações gráficas do mesmo nome.
4. Relações: apenas as que o próprio texto AFIRMA. Cada relação precisa do trecho
   literal que a sustenta. Não deduza, não complete, não relacione por semelhança
   de assunto — isso é do F6, não é seu trabalho aqui.
5. Se o trecho não tiver conceito nenhum que valha registrar, devolva listas vazias.
   Extração vazia é uma resposta correta."""


# --------------------------------------------------------------------------
# O formato da resposta, em texto
# --------------------------------------------------------------------------
#
# Por que isto existe, e por que não é redundante com o Pydantic:
#
# O `with_structured_output` do langchain-openai tenta, por padrão, mandar o schema
# como `response_format: json_schema` — e a DeepSeek recusa ("This response_format
# type is unavailable now"). As alternativas foram medidas contra a API real:
#
#   method="function_calling" → o modelo de raciocínio recusa: "Thinking mode does
#                               not support this tool_choice"
#   method="json_mode"        → funciona, MAS o provedor recebe apenas
#                               `response_format: json_object`: o schema NÃO chega.
#                               O modelo só sabe o que o prompt disser — e sem a
#                               descrição ele chutou `{"conceito": ...}` no lugar de
#                               `{"nome": ...}` e a validação falhou.
#
# Então o formato tem que estar no prompt. Ele é GERADO do próprio Pydantic para não
# envelhecer: descrição escrita à mão divergiria do validador em silêncio, que é
# exatamente o tipo de defeito que este projeto tenta não ter.
#
# E `json_mode` exige a palavra "json" em algum lugar do prompt. Está no texto final.


def _interno(anotacao: Any) -> type[BaseModel] | None:
    """O modelo dentro de um `list[Modelo]`, ou None."""
    if getattr(anotacao, "__origin__", None) is not list:
        return None
    argumentos = getattr(anotacao, "__args__", ())
    if len(argumentos) != 1:
        return None
    interno = argumentos[0]
    if isinstance(interno, type) and issubclass(interno, BaseModel):
        return interno
    return None


def _tipo_legivel(anotacao: Any) -> str:
    interno = _interno(anotacao)
    if interno is not None:
        return "lista de objetos com " + ", ".join(interno.model_fields)
    if getattr(anotacao, "__origin__", None) is list:
        return "lista de texto"
    if isinstance(anotacao, type) and issubclass(anotacao, BaseModel):
        return "objeto com " + ", ".join(anotacao.model_fields)
    return "texto"


def _descricao_do_formato(modelo: type[BaseModel]) -> str:
    linhas = ["Responda APENAS com um JSON, sem texto em volta, neste formato:", "{"]
    for nome, campo in modelo.model_fields.items():
        linhas.append(
            f'  "{nome}": {_tipo_legivel(campo.annotation)} — '
            f"{(campo.description or '').strip()}"
        )
        interno = _interno(campo.annotation)
        if interno is not None:
            for subnome, subcampo in interno.model_fields.items():
                linhas.append(
                    f'      "{subnome}": {_tipo_legivel(subcampo.annotation)} — '
                    f"{(subcampo.description or '').strip()}"
                )
    linhas.append("}")
    return "\n".join(linhas)


FORMATO = _descricao_do_formato(Extracao)

# Medido contra a API real: `function_calling` não serve nos modelos de raciocínio, e
# `json_schema` não é aceito. `json_mode` é o modo compatível — e o mais suportado
# entre provedores OpenAI-compatíveis.
METODO_ESTRUTURADO = "json_mode"


# --------------------------------------------------------------------------
# Fatiamento
# --------------------------------------------------------------------------

TAMANHO_BLOCO = 6000
SOBREPOSICAO = 400


def blocos(texto: str, *, tamanho: int = TAMANHO_BLOCO, sobreposicao: int = SOBREPOSICAO) -> list[str]:
    """Fatia o texto em blocos, cortando em fim de parágrafo sempre que dá.

    Cortar no meio de uma frase faz o extrator perder o conceito que atravessa a
    junta. A sobreposição cobre o caso, e é pequena o bastante para não pagar um
    bloco extra nas fetiações comuns.
    """
    if not texto:
        return []
    if len(texto) <= tamanho:
        return [texto]

    pedacos: list[str] = []
    inicio = 0
    while inicio < len(texto):
        fim = min(inicio + tamanho, len(texto))
        if fim < len(texto):
            # Recua até o último fim de parágrafo dentro da janela; se não houver um
            # razoavelmente próximo, corta onde está para não criar blocos minúsculos.
            corte = texto.rfind("\n\n", inicio + tamanho // 2, fim)
            if corte > 0:
                fim = corte
        pedacos.append(texto[inicio:fim])
        if fim >= len(texto):
            break
        inicio = max(fim - sobreposicao, inicio + 1)
    return pedacos


def _mensagens(bloco: str, vocabulario: list[str]) -> list[Any]:
    from langchain_core.messages import HumanMessage, SystemMessage

    # O formato vai no prompt porque `json_mode` não envia o schema ao provedor, e a
    # palavra "JSON" tem que aparecer para o modo ser aceito.
    sistema = INSTRUCOES + "\n\n" + FORMATO
    if vocabulario:
        # D041 em ação: o modelo vê o que já existe antes de nomear o que achou.
        lista = "\n".join(f"- {nome}" for nome in vocabulario)
        sistema += (
            "\n\nConceitos que JÁ EXISTEM no grafo. Reuse estes nomes quando for o "
            "mesmo conceito, em vez de criar uma variação:\n" + lista
        )
    return [SystemMessage(sistema), HumanMessage(f"Trecho a analisar:\n\n{bloco}")]


async def extrair_bloco(bloco: str, vocabulario: list[str], *, modelo: Any = None) -> Extracao:
    """Uma chamada de modelo, com o JSON validado pelo Pydantic (D021).

    O método é `json_mode` por medição, não por preferência: ver a nota acima de
    METODO_ESTRUTURADO.
    """
    extrator = (modelo or llm.atual()).with_structured_output(
        Extracao, method=METODO_ESTRUTURADO
    )
    resultado = await extrator.ainvoke(_mensagens(bloco, vocabulario))
    if isinstance(resultado, Extracao):
        return resultado
    return Extracao(**resultado) if isinstance(resultado, dict) else Extracao()


# --------------------------------------------------------------------------
# O pipeline
# --------------------------------------------------------------------------


async def extrair_fonte(source_id: str, *, modelo: Any = None) -> AsyncIterator[dict[str, Any]]:
    """Extrai os conceitos de uma fonte, emitindo progresso a cada bloco.

    É gerador porque a extração é longa: uma fonte de 50 mil caracteres dá cerca de
    7 chamadas de modelo. Prender isso numa requisição sem retorno é pedir para a
    pessoa achar que travou e recarregar a página no meio.
    """
    fonte = db.get_source(source_id)
    if not fonte:
        yield {"evento": "error", "message": f"Fonte {source_id} não existe"}
        return

    texto = db.read_source_text(fonte)
    if not texto.strip():
        yield {
            "evento": "extract.source_done",
            "fonte": fonte["title"],
            "mencionadas": 0,
            "descartadas": 0,
            "motivo": "a fonte não tem texto legível",
        }
        return

    fatias = blocos(texto)
    yield {
        "evento": "extract.source",
        "fonte": fonte["title"],
        "source_id": source_id,
        "blocos": len(fatias),
    }

    # Re-extrair SUBSTITUI: sem isto, cada extração somaria menções às antigas.
    knowledge.limpar_fonte(source_id)

    mencionadas = descartadas = 0
    for indice, bloco in enumerate(fatias, start=1):
        # O vocabulário é relido a cada bloco de propósito: o conceito criado no
        # bloco 2 já existe no bloco 3. É o que faz o reuso acontecer de verdade.
        try:
            resultado = await extrair_bloco(bloco, knowledge.vocabulario(), modelo=modelo)
        except Exception as exc:  # noqa: BLE001 — a mensagem vai para a tela
            # Mesmo formato do chat: `explicar` devolve a DICA para apensar, não a
            # mensagem. Usá-la sozinha dava um evento de erro com texto vazio.
            yield {
                "evento": "error",
                "message": f"{type(exc).__name__}: {exc}{llm.explicar(exc)}",
            }
            return

        # O nome normalizado → id, mas SÓ dos conceitos que ficaram ancorados. As
        # relações procuram aqui: assim uma relação que cite um conceito inventado
        # não cria um nó órfão para poder apontar para ele.
        ancorados: dict[str, str] = {}
        ids_do_bloco: list[str] = []

        for extraido in resultado.conceitos:
            if not extraido.nome.strip():
                continue
            # Confere o trecho ANTES de criar o conceito. Criar primeiro deixaria no
            # grafo, pendurado e sem âncora, exatamente o que o extrator inventou.
            # A conferência se repete dentro de `registrar_mencao` de propósito: a
            # invariante precisa morar na loja, não na boa vontade do chamador.
            if not knowledge.trecho_existe(extraido.trecho, bloco):
                descartadas += 1
                continue

            conceito = knowledge.achar_ou_criar(extraido.nome, extraido.tipo)
            gravou = knowledge.registrar_mencao(
                conceito["id"],
                notebook_id=fonte["notebook_id"],
                trecho=extraido.trecho,
                referencia=bloco,          # a conferência da ancoragem
                source_id=source_id,
            )
            if gravou:
                mencionadas += 1
                ids_do_bloco.append(conceito["id"])
                ancorados[knowledge.normalizar(extraido.nome)] = conceito["id"]
            else:
                descartadas += 1

        # A ligação que sai de graça: os conceitos do bloco já estão em mãos.
        knowledge.co_ocorrencia(ids_do_bloco)

        for relacao in resultado.relacoes:
            de = ancorados.get(knowledge.normalizar(relacao.de))
            para = ancorados.get(knowledge.normalizar(relacao.para))
            if de and para:
                knowledge.ligar_explicito(
                    de, para, trecho=relacao.trecho, referencia=bloco, quem="modelo"
                )

        yield {
            "evento": "extract.block",
            "source_id": source_id,
            "bloco": indice,
            "total": len(fatias),
            "conceitos": len(ids_do_bloco),
            "descartadas": descartadas,
        }

    yield {
        "evento": "extract.source_done",
        "fonte": fonte["title"],
        "source_id": source_id,
        "mencionadas": mencionadas,
        "descartadas": descartadas,
        "blocos": len(fatias),
    }


async def extrair_caderno(notebook_id: str, *, modelo: Any = None) -> AsyncIterator[dict[str, Any]]:
    """Extrai de todas as fontes ativas do caderno, uma a uma."""
    fontes = [f for f in db.list_sources(notebook_id) if f["active"] and f["status"] == "ready"]
    if not fontes:
        yield {"evento": "extract.done", "message": "Nenhuma fonte ativa para extrair."}
        return

    total_mencionadas = total_descartadas = 0
    for numero, fonte in enumerate(fontes, start=1):
        yield {
            "evento": "extract.next",
            "fonte": fonte["title"],
            "indice": numero,
            "total": len(fontes),
        }
        async for evento in extrair_fonte(fonte["id"], modelo=modelo):
            if evento["evento"] == "error":
                yield evento
                return
            if evento["evento"] == "extract.source_done":
                total_mencionadas += evento.get("mencionadas", 0)
                total_descartadas += evento.get("descartadas", 0)
            yield evento

    estatisticas = knowledge.estatisticas()
    yield {
        "evento": "extract.done",
        "mencionadas": total_mencionadas,
        "descartadas": total_descartadas,
        **estatisticas,
    }
