"""Prompts: instruções do caderno e templates de output."""

from __future__ import annotations

from typing import Any

from . import db
from .config import settings

BASE_RULES = """
Você é o assistente de estudo deste caderno. Sua função é ajudar a pessoa a
entender, revisar e organizar o material das fontes dela.

REGRAS
1. Responda com base PRIMARIAMENTE nas fontes do caderno. Elas são a verdade.
2. Se o conteúdo das fontes não estiver abaixo, LEIA antes de responder:
   - `listar_fontes` mostra o que existe, com o id de cada fonte;
   - `buscar_nas_fontes` acha um termo específico (número, nome, código) — é mais
     barato do que ler arquivo inteiro;
   - `ler_fonte` lê um trecho, e diz onde parou caso você precise continuar.
   Nunca responda de memória sobre o conteúdo das fontes.
3. Cite a fonte de cada informação usando o número dela entre colchetes: [1], [2].
4. Se a resposta não estiver nas fontes, diga isso com clareza e só então ofereça
   o que você sabe por fora (marcando como "fora das fontes"). Nunca invente.
5. Você tem internet: `web_extract` traz o texto de uma URL que a pessoa indicar.
   Complemente com isso se pedirem, mas deixe claro o que veio de fora das fontes.
6. Responda no idioma da pergunta. Seja direto e bem organizado, em Markdown.
7. Ao final de respostas longas, ofereça 1 ou 2 perguntas de follow-up úteis.
""".strip()


OUTPUT_TEMPLATES: dict[str, dict[str, str]] = {
    "resumo": {
        "label": "Resumo executivo",
        "hint": "O essencial do material em poucos parágrafos.",
        "prompt": (
            "Escreva um RESUMO EXECUTIVO das fontes.\n"
            "- Um parágrafo de abertura dizendo do que trata o material.\n"
            "- Depois, de 4 a 7 pontos-chave em bullets, cada um com citação [n].\n"
            "- Feche com 'O que não está claro nas fontes' (lacunas e contradições).\n"
            "Entre 300 e 600 palavras. Markdown puro, começando com '#'."
        ),
    },
    "guia": {
        "label": "Guia de estudo",
        "hint": "Material de revisão com conceitos e perguntas.",
        "prompt": (
            "Monte um GUIA DE ESTUDO a partir das fontes.\n"
            "1. '## Conceitos-chave' — cada conceito com definição curta e citação [n].\n"
            "2. '## Como as ideias se conectam' — 1 parágrafo explicando a estrutura.\n"
            "3. '## Perguntas de revisão' — 6 perguntas, da mais fácil à mais difícil.\n"
            "4. '## Gabarito resumido' — resposta curta de cada pergunta, com citação.\n"
            "Markdown puro, começando com '#'."
        ),
    },
    "faq": {
        "label": "FAQ",
        "hint": "Perguntas frequentes respondidas com as fontes.",
        "prompt": (
            "Escreva uma FAQ sobre o material das fontes.\n"
            "- De 8 a 12 perguntas que alguém realmente faria sobre este tema.\n"
            "- Cada pergunta como '### pergunta?' e a resposta em 2 a 4 frases com citação [n].\n"
            "- Termine com '### O que as fontes não respondem'.\n"
            "Markdown puro, começando com '#'."
        ),
    },
    "linha-do-tempo": {
        "label": "Linha do tempo",
        "hint": "Eventos e marcos em ordem cronológica.",
        "prompt": (
            "Extraia uma LINHA DO TEMPO das fontes.\n"
            "- Liste os eventos/marcos em ordem cronológica, em bullets com data/período.\n"
            "- Cada item: data, o que aconteceu, por que importa, e citação [n].\n"
            "- Se não houver datas, use a ordem lógica de desenvolvimento e diga isso.\n"
            "- Se as fontes não tiverem material cronológico, diga isso e pare.\n"
            "Markdown puro, começando com '#'."
        ),
    },
    "mapa": {
        "label": "Mapa de conceitos",
        "hint": "Hierarquia dos conceitos, em texto.",
        "prompt": (
            "Construa um MAPA DE CONCEITOS das fontes, em texto estruturado.\n"
            "- Use uma árvore com indentação markdown mostrando o conceito central e seus ramos.\n"
            "- Depois, uma seção '## Relações' listando ligações do tipo 'A → implica → B'.\n"
            "- Cite [n] em cada nó. Sem imagens: só texto/tabela.\n"
            "Markdown puro, começando com '#'."
        ),
    },
    "comparativo": {
        "label": "Tabela comparativa",
        "hint": "Compara o que as fontes dizem sobre os mesmos itens.",
        "prompt": (
            "Monte uma TABELA COMPARATIVA do que as fontes apresentam.\n"
            "- Identifique os itens/opções/casos sendo comparados.\n"
            "- Uma coluna por item, linhas como critérios de comparação.\n"
            "- Inclua uma coluna final com as citações [n] relevantes de cada linha.\n"
            "- Depois da tabela, 1 parágrafo de 'Quando escolher cada um'.\n"
            "Markdown puro, começando com '#'. Se não houver o que comparar, diga isso."
        ),
    },
    "plano": {
        "label": "Plano de aprendizado",
        "hint": "Roteiro de estudo em etapas.",
        "prompt": (
            "Crie um PLANO DE APRENDIZADO com base nas fontes.\n"
            "- Divida em 4 a 6 etapas progressivas, com objetivo de cada uma.\n"
            "- Para cada etapa: o que ler/estudar das fontes (citando [n]), o que praticar,\n"
            "  e como saber que aprendeu (critério de conclusão).\n"
            "- Feche com '## Estimativa de tempo' e '## Pré-requisitos'.\n"
            "Markdown puro, começando com '#'."
        ),
    },
}


def build_notebook_prompt(notebook: dict[str, Any], *, inline_limit: int | None = None) -> str:
    """Prompt de sistema do chat do caderno: regras + fontes ativas."""
    limit = settings.inline_limit if inline_limit is None else inline_limit
    context, sources = db.build_context(notebook, inline_limit=limit)

    parts = [BASE_RULES, "", f"# Caderno: {notebook['title']}"]
    if notebook.get("description"):
        parts.append(notebook["description"])

    if not sources:
        parts.append(
            "\n## Fontes\nEste caderno ainda não tem fontes ativas. Avise a pessoa e "
            "ajude com o que você souber, deixando claro que não há material de base."
        )
    else:
        parts.append(f"\n## Fontes ativas ({len(sources)})\n{context}")

    return "\n".join(parts)


def build_output_prompt(notebook: dict[str, Any], template_key: str) -> tuple[str, str]:
    """Devolve (system_prompt, user_prompt) para gerar um output."""
    template = OUTPUT_TEMPLATES.get(template_key)
    if template is None:
        raise KeyError(template_key)

    context, sources = db.build_context(notebook, inline_limit=settings.inline_limit)

    system = [BASE_RULES, "", f"# Tarefa: {template['label']}", template["prompt"]]
    system.append(
        "\nIMPORTANTE: entregue apenas o documento final em Markdown, sem preâmbulo, "
        "sem comentários sobre o processo e sem cercas de código em volta do Markdown."
    )
    if sources:
        system.append(f"\n## Fontes do caderno ({len(sources)})\n{context}")
    else:
        system.append("\n## Fontes\nNenhuma fonte ativa. Diga que não há material para trabalhar.")

    user = (
        f"Gere o documento '{template['label']}' para o caderno "
        f"\"{notebook['title']}\" usando as fontes fornecidas."
    )
    return "\n".join(system), user
