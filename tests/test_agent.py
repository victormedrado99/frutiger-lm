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
import json

from frutiger_lm import db, ingest
from frutiger_lm.engine import agent, checkpoint, fake, llm
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
        # as de grafo (F3), globais por decisão (D045)
        "buscar_no_grafo",
        "vizinhanca_do_conceito",
        "registrar_relacao",
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
            config = checkpoint.config(nb)
            # turno 1 — um agente
            a1 = agent.montar(nb, modelo=fake.responde("primeira resposta"), checkpointer=saver)
            await agent.responder(a1, config, "primeira pergunta")

            # turno 2 — agente NOVO, mesmo thread. Se o histórico aparecer, veio
            # do disco, não da memória do processo.
            a2 = agent.montar(nb, modelo=fake.responde("segunda resposta"), checkpointer=saver)
            await agent.responder(a2, config, "segunda pergunta")

            estado = await a2.aget_state(config)
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
            config = checkpoint.config(nb)
            resposta = await agent.responder(agente, config, "qual é o código?")

            assert resposta == "o código é BRAVO-7741"
            estado = await agente.aget_state(config)
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
            await agent.responder(a, checkpoint.config(nb_a), "pergunta exclusiva do A")

            b = agent.montar(nb_b, modelo=fake.responde("resposta B"), checkpointer=saver)
            await agent.responder(b, checkpoint.config(nb_b), "pergunta do B")

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


# ------------------------------------------------- a rota de conversa (SSE)


def test_o_chat_emite_exatamente_o_que_a_interface_espera(cliente, monkeypatch):
    """O contrato da interface, verificado ponta a ponta num só lugar.

    A interface consome `assistant.delta` (concatena), `tool.started` (mostra o
    rodapé da ferramenta), `assistant.completed` (substitui o texto), `error` e
    `done`. Se o motor mudar um nome de evento, isto quebra — que é o ponto.
    """
    nb = caderno("Conversa")
    fonte(nb, "O codigo do equipamento e BRAVO-7741.", "Manual")
    monkeypatch.setattr(
        llm,
        "atual",
        lambda: fake.com_ferramenta(
            "buscar_nas_fontes", {"termo": "BRAVO-7741"}, "achei o codigo"
        ),
    )

    resp = cliente.post(f"/api/notebooks/{nb}/chat", json={"input": "qual e o codigo?"})

    assert resp.status_code == 200
    corpo = resp.text
    for evento in (
        "run.started",
        "tool.started",
        "assistant.delta",
        "assistant.completed",
        "done",
    ):
        assert f"event: {evento}" in corpo, f"faltou o evento {evento}"

    assert corpo.index("event: run.started") < corpo.index("event: assistant.completed")
    assert corpo.index("event: tool.started") < corpo.index("event: assistant.completed")
    assert "buscar_nas_fontes" in corpo, "a interface não teria o que mostrar no rodapé"
    assert "achei o codigo" in corpo
    # o delta veio partido: streaming de verdade, não um bloco só
    assert corpo.count("event: assistant.delta") >= 2
    assert corpo.rstrip().endswith("data: {}")


def test_o_texto_antes_e_depois_da_ferramenta_nao_cola(cliente, monkeypatch):
    """O defeito que só apareceu na prova com modelo real.

    O agente faz DUAS chamadas ao modelo (a do tool call, com um "vou procurar"
    antes, e a final). Ao vivo os dois textos chegavam colados
    ("...na fonte.**ZULU-90210**") e, ao recarregar, vinham como duas bolhas de
    assistente — ou seja, a tela mudava de forma conforme o momento.

    Este teste prende os dois lados: o stream emenda com linha em branco e o
    histórico junta numa bolha só, com o mesmo texto.
    """
    nb = caderno("Emenda")
    fonte(nb, "O codigo e BRAVO-7741.", "Manual")
    monkeypatch.setattr(
        llm,
        "atual",
        lambda: fake.com_ferramenta(
            "buscar_nas_fontes",
            {"termo": "BRAVO-7741"},
            resposta_final="achei",
            antes="vou procurar",
        ),
    )

    resp = cliente.post(f"/api/notebooks/{nb}/chat", json={"input": "qual?"})

    # o que a interface recebe, remontado como ela remonta
    deltas = [
        json.loads(linha[5:])["delta"]
        for linha in resp.text.splitlines()
        if linha.startswith("data:") and "delta" in linha
    ]
    ao_vivo = "".join(deltas)
    assert ao_vivo == "vou procurar\n\nachei", f"texto colado ou fora de ordem: {ao_vivo!r}"

    # e o que aparece ao recarregar: uma bolha só, com exatamente o mesmo texto
    historico = cliente.get(f"/api/notebooks/{nb}/messages").json()
    assert [m["role"] for m in historico] == ["user", "assistant"], "a resposta veio fatiada"
    assert historico[1]["content"] == ao_vivo, "o recarregado difere do ao vivo"


def test_o_chat_avisa_quando_nao_ha_modelo_configurado(cliente):
    """Sem modelo, o app não finge que sabe responder."""
    nb = caderno("Sem modelo")
    resp = cliente.post(f"/api/notebooks/{nb}/chat", json={"input": "oi"})

    assert resp.status_code == 200  # o stream já começou; o erro vai dentro dele
    assert "event: error" in resp.text
    assert "não configurado" in resp.text


def test_o_historico_vem_do_checkpointer(cliente, monkeypatch):
    """A tela mostra o que o agente lembra — mesma fonte, D019."""
    nb = caderno("Historico")
    fonte(nb, "material", "Fonte")
    monkeypatch.setattr(llm, "atual", lambda: fake.responde("resposta do teste"))

    cliente.post(f"/api/notebooks/{nb}/chat", json={"input": "primeira pergunta"})
    mensagens = cliente.get(f"/api/notebooks/{nb}/messages").json()

    assert [m["role"] for m in mensagens] == ["user", "assistant"]
    assert mensagens[0]["content"] == "primeira pergunta"
    assert mensagens[1]["content"] == "resposta do teste"


def test_limpar_a_conversa_apaga_o_historico(cliente, monkeypatch):
    nb = caderno("Limpar")
    fonte(nb, "material", "Fonte")
    monkeypatch.setattr(llm, "atual", lambda: fake.responde("oi"))

    cliente.post(f"/api/notebooks/{nb}/chat", json={"input": "pergunta"})
    assert cliente.get(f"/api/notebooks/{nb}/messages").json(), "deveria ter conversa"

    assert cliente.delete(f"/api/notebooks/{nb}/chat").status_code == 200
    assert cliente.get(f"/api/notebooks/{nb}/messages").json() == []

    # e as fontes continuam lá: limpar conversa não mexe no caderno
    assert len(db.list_sources(nb)) == 1


def test_apagar_o_caderno_leva_a_conversa_junto(cliente, monkeypatch):
    """Caderno apagado não pode deixar histórico no checkpoints.db."""
    nb = caderno("Vai embora")
    fonte(nb, "material", "Fonte")
    monkeypatch.setattr(llm, "atual", lambda: fake.responde("oi"))

    cliente.post(f"/api/notebooks/{nb}/chat", json={"input": "pergunta"})
    assert cliente.delete(f"/api/notebooks/{nb}").status_code == 200
    assert cliente.get(f"/api/notebooks/{nb}/messages").status_code == 404
