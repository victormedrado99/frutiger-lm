"""Testes do agente e das guardas de regressão da migração.

O teste que importa aqui é o de **memória entre turnos**: dois agentes
diferentes, o mesmo thread, um agente novo por turno. Se o histórico sobrevive, é
porque quem guarda é o checkpointer (D019) — e não porque o objeto do agente
ficou vivo com a conversa na RAM.

O resto do arquivo são guardas contra a volta da linguagem do Hermes: o prompt e o
contexto falavam de `read_file`, `search_files`, `grep` e caminhos de arquivo, que
não existem no motor novo. Isso não dá erro de execução — dá um agente que chama
ferramenta inexistente e responde mal, que é bem pior.
"""

from __future__ import annotations

import asyncio

from frutiger_lm import db, ingest
from frutiger_lm.engine import agent, checkpoint, fake
from frutiger_lm.engine.tools.leitura import ferramentas_de_leitura
from frutiger_lm.prompts import BASE_RULES, build_notebook_prompt


def caderno(titulo: str = "Caderno") -> str:
    return db.create_notebook(titulo)["id"]


def fonte(notebook_id: str, texto: str, titulo: str = "Fonte") -> str:
    return asyncio.run(ingest.add_source(notebook_id, kind="text", text=texto, title=titulo))["id"]


# ------------------------------------------------------------------ catálogo


def test_o_catalogo_do_caderno_tem_leitura_e_web():
    nomes = {t.name for t in agent.catalogo(caderno())}
    assert nomes == {
        "listar_fontes",
        "ler_fonte",
        "buscar_nas_fontes",
        "web_extract",
    }


def test_nao_existe_ferramenta_de_busca_na_web_ainda():
    """D036 em aberto: sem provedor escolhido, a ferramenta não é exposta."""
    assert not any("search" in t.name for t in agent.catalogo(caderno()))


def test_montar_recusa_caderno_inexistente():
    try:
        agent.montar("nb_que_nao_existe", modelo=fake.responde())
    except ValueError as exc:
        assert "não existe" in str(exc)
    else:
        raise AssertionError("deveria ter recusado")


# ------------------------------------------------------------------- memória


def test_o_agente_lembra_entre_turnos():
    """Dois agentes, o mesmo thread: quem guarda o histórico é o checkpointer."""
    nb = caderno()
    fonte(nb, "O código do equipamento é BRAVO-7741.", "Manual")

    def textos(estado) -> str:
        return " ".join(str(m.content) for m in estado.values["messages"])

    async def duas_voltas() -> None:
        async with checkpoint.aberto() as saver:
            # turno 1 — um agente
            a1 = agent.montar(nb, modelo=fake.responde("primeira resposta"), checkpointer=saver)
            await agent.responder(a1, nb, "primeira pergunta")

            # turno 2 — agente NOVO, mesmo thread. Se o histórico aparecer, veio
            # do disco, não da memória do processo.
            a2 = agent.montar(nb, modelo=fake.responde("segunda resposta"), checkpointer=saver)
            await agent.responder(a2, nb, "segunda pergunta")

            estado = await a2.aget_state(checkpoint.config(nb))
            tudo = textos(estado)
            assert "primeira pergunta" in tudo
            assert "primeira resposta" in tudo, "o turno 1 não foi lembrado"
            assert "segunda pergunta" in tudo
            assert "segunda resposta" in tudo

    asyncio.run(duas_voltas())


def test_o_resultado_da_ferramenta_fica_na_memoria():
    """O agente leu a fonte por ferramenta — e isso ficou gravado."""
    nb = caderno()
    fonte(nb, "O código do equipamento é BRAVO-7741.", "Manual")

    async def com_ferramenta() -> None:
        async with checkpoint.aberto() as saver:
            modelo = fake.com_ferramenta(
                "buscar_nas_fontes", {"termo": "BRAVO-7741"}, "o código é BRAVO-7741"
            )
            agente = agent.montar(nb, modelo=modelo, checkpointer=saver)
            resposta = await agent.responder(agente, nb, "qual é o código?")

            assert resposta == "o código é BRAVO-7741"
            estado = await agente.aget_state(checkpoint.config(nb))
            tipos = [type(m).__name__ for m in estado.values["messages"]]
            assert "ToolMessage" in tipos, "a leitura da fonte não foi registrada"
            assert "BRAVO-7741" in " ".join(
                str(m.content) for m in estado.values["messages"]
            )

    asyncio.run(com_ferramenta())

    # e o caderno continua com as suas fontes — o agente só leu
    assert len(db.list_sources(nb)) == 1


def test_cadernos_diferentes_nao_compartilham_memoria():
    nb_a = caderno("A")
    nb_b = caderno("B")

    async def dois() -> None:
        async with checkpoint.aberto() as saver:
            a = agent.montar(nb_a, modelo=fake.responde("resposta A"), checkpointer=saver)
            await agent.responder(a, nb_a, "pergunta exclusiva do A")

            b = agent.montar(nb_b, modelo=fake.responde("resposta B"), checkpointer=saver)
            await agent.responder(b, nb_b, "pergunta do B")

            estado_b = await b.aget_state(checkpoint.config(nb_b))
            tudo_b = " ".join(str(m.content) for m in estado_b.values["messages"])
            assert "exclusiva do A" not in tudo_b

    asyncio.run(dois())


# ------------------------------------------- guardas da migração (Hermes -> engine)


def test_o_prompt_nao_manda_usar_ferramentas_que_nao_existem():
    """O prompt falava de `read_file`/`search_files`/`grep` do Hermes.

    Sem esta guarda, a migração deixa o modelo instruído a chamar ferramenta
    inexistente — falha silenciosa, das piores de achar.
    """
    for morta in ("read_file", "search_files", "grep", "terminal"):
        assert morta not in BASE_RULES, f"o prompt ainda cita {morta}"

    for nossa in ("listar_fontes", "buscar_nas_fontes", "ler_fonte", "web_extract"):
        assert nossa in BASE_RULES, f"o prompt não menciona {nossa}"


def test_contexto_grande_entrega_id_de_fonte_e_nao_caminho_de_arquivo():
    """As ferramentas aceitam id. Caminho de arquivo só confunde o modelo."""
    nb = caderno()
    sid = fonte(nb, "x" * 30_000, "Grande")
    notebook = db.get_notebook(nb)
    assert notebook is not None

    contexto, fontes = db.build_context(notebook, inline_limit=1_000)
    assert fontes, "deveria listar a fonte no índice"
    assert sid in contexto
    assert ".txt" not in contexto, "não deve vazar caminho de arquivo"
    assert "ler_fonte" in contexto
    assert "read_file" not in contexto


def test_o_prompt_do_caderno_aponta_para_as_ferramentas_do_motor():
    nb = caderno("Sistemas")
    fonte(nb, "material", "Fonte")
    notebook = db.get_notebook(nb)
    assert notebook is not None

    prompt = build_notebook_prompt(notebook, inline_limit=1)
    assert "Sistemas" in prompt
    assert "buscar_nas_fontes" in prompt


def test_a_numeracao_das_fontes_casa_com_a_do_contexto():
    """Se divergir, o modelo cita [2] apontando para a fonte errada.

    A desligada não pode ocupar número: o contexto inline numera só as ativas, e a
    listagem tem que numerar igual.
    """
    nb = caderno()
    a = fonte(nb, "material A", "Primeira")
    b = fonte(nb, "material B", "Segunda")
    c = fonte(nb, "material C", "Terceira")
    db.set_source_active(b, False)

    listagem = {t.name: t for t in ferramentas_de_leitura(nb)}["listar_fontes"].invoke({})
    assert f"[1] {a}" in listagem
    assert f"[2] {c}" in listagem
    assert f"[2] {b}" not in listagem
    assert b in listagem, "a desligada ainda deve aparecer, só sem número"

    notebook = db.get_notebook(nb)
    assert notebook is not None
    contexto, _ = db.build_context(notebook, inline_limit=10**9)
    assert "### [1] Primeira" in contexto
    assert "### [2] Terceira" in contexto
    assert "### [2] Segunda" not in contexto
