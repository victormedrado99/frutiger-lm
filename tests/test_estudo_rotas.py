"""Testes das rotas do estudo (F4) e do registro de uso das fontes (D051).

O que estes testes protegem:

1. **A citação registra o uso da fonte certa.** Se a numeração do prompt e a que eu
   uso para mapear os `[n]` divergissem, o app diria que a fonte X nunca foi usada
   quando na verdade foi — e a pessoa "consertaria" o que não está quebrado.
2. **O painel não esconde as lacunas atrás de nada.** Elas são consulta ao grafo:
   vêm na mesma chamada, sem custo.
"""

from __future__ import annotations

import asyncio

from frutiger_lm import db, ingest, knowledge, study
from frutiger_lm.engine import estudo, fake, llm

TEXTO = (
    "O protocolo KWP2000 roda sobre a linha K e usa 5 baudes na inicializacao.\n\n"
    "O ISO 14230 descreve o KWP2000 como protocolo de aplicacao."
)


def caderno(titulo: str = "Caderno") -> str:
    return db.create_notebook(titulo)["id"]


def fonte(notebook_id: str, texto: str = TEXTO, titulo: str = "Fonte") -> dict:
    return asyncio.run(ingest.add_source(notebook_id, kind="text", text=texto, title=titulo))


def com_grafo(nb: str | None = None) -> dict:
    nb = nb or caderno()
    src = fonte(nb)
    conceito = knowledge.achar_ou_criar("KWP2000")
    knowledge.registrar_mencao(
        conceito["id"],
        notebook_id=nb,
        trecho="O protocolo KWP2000 roda sobre a linha K e usa 5 baudes na inicializacao.",
        referencia=TEXTO,
        source_id=src["id"],
    )
    return {"nb": nb, "src": src, "conceito": conceito}


# ------------------------------------------------------------------- painel


def test_o_painel_traz_cards_lacunas_e_fontes(cliente):
    dados = com_grafo()
    corpo = cliente.get(f"/api/notebooks/{dados['nb']}/estudo").json()

    assert corpo["cards"] == {"total": 0, "vencidos": 0, "aprendendo": 0}
    assert "nao_desenvolvidos" in corpo["lacunas"]
    assert corpo["grafo"]["conceitos"] == 1
    assert [f["title"] for f in corpo["fontes"]] == ["Fonte"]


def test_o_painel_marca_a_fonte_nunca_citada(cliente):
    dados = com_grafo()
    corpo = cliente.get(f"/api/notebooks/{dados['nb']}/estudo").json()
    assert corpo["fontes"][0]["nunca_citada"] is True

    study.registrar_uso(dados["src"]["id"])
    corpo = cliente.get(f"/api/notebooks/{dados['nb']}/estudo").json()
    assert corpo["fontes"][0]["nunca_citada"] is False


def test_o_painel_404_para_caderno_inexistente(cliente):
    assert cliente.get("/api/notebooks/nb_fantasma/estudo").status_code == 404


# -------------------------------------------------------------------- cards


def test_criar_card_pela_rota(cliente):
    nb = caderno()
    resposta = cliente.post(
        "/api/cards", json={"notebook_id": nb, "front": "O que é?", "back": "Isso."}
    )

    assert resposta.status_code == 200
    card = resposta.json()
    assert card["front"] == "O que é?"
    assert cliente.get(f"/api/cards?notebook_id={nb}").json() != []


def test_criar_card_incompleto_e_recusado(cliente):
    nb = caderno()
    for corpo in (
        {"notebook_id": nb, "front": "só frente"},
        {"notebook_id": nb, "back": "só verso"},
        {"front": "f", "back": "v"},
    ):
        assert cliente.post("/api/cards", json=corpo).status_code == 400


def test_revisar_pela_rota_reagenda(cliente):
    nb = caderno()
    card = cliente.post(
        "/api/cards", json={"notebook_id": nb, "front": "f", "back": "v"}
    ).json()

    revisado = cliente.post(f"/api/cards/{card['id']}/revisar", json={"nota": "bom"}).json()

    assert revisado["reps"] == 1
    assert revisado["interval_days"] == 1.0
    assert cliente.get("/api/cards?devidos=1").json() == []


def test_revisar_card_inexistente_404(cliente):
    assert cliente.post("/api/cards/crd_fantasma/revisar", json={"nota": "bom"}).status_code == 404


def test_apagar_card_pela_rota(cliente):
    nb = caderno()
    card = cliente.post(
        "/api/cards", json={"notebook_id": nb, "front": "f", "back": "v"}
    ).json()

    assert cliente.delete(f"/api/cards/{card['id']}").status_code == 200
    assert cliente.delete(f"/api/cards/{card['id']}").status_code == 404


def test_listar_cards_sem_caderno_e_recusado(cliente):
    assert cliente.get("/api/cards").status_code == 400


def test_gerar_cards_pela_rota_emite_progresso(cliente, monkeypatch):
    dados = com_grafo()
    monkeypatch.setattr(
        llm, "atual", lambda: fake.extrai([estudo.CardProposto(pergunta="E?", resposta="R.")])
    )

    resposta = cliente.post(f"/api/notebooks/{dados['nb']}/cards/gerar")
    corpo = resposta.text

    assert "event: cards.plano" in corpo
    assert "event: cards.item" in corpo
    assert "event: cards.done" in corpo
    assert len(study.listar(dados["nb"])) == 1


def test_gerar_cards_sem_modelo_avisa(cliente):
    dados = com_grafo()
    assert "event: error" in cliente.post(f"/api/notebooks/{dados['nb']}/cards/gerar").text


def test_conflitos_sem_candidato_avisa_e_nao_gasta_chamada(cliente, monkeypatch):
    """Um conceito numa fonte só não tem com o que comparar.

    A rota checa o modelo antes (consistente com a extração), então o teste dá um
    modelo de mentira para chegar ao caminho que interessa: o plano vazio.
    """
    dados = com_grafo()
    extrator = fake.extrai([])
    monkeypatch.setattr(llm, "atual", lambda: extrator)

    corpo = cliente.post(f"/api/notebooks/{dados['nb']}/conflitos").text

    assert "event: conflitos.plano" in corpo
    assert "event: conflitos.done" in corpo
    assert extrator.chamadas == [], "chamou o modelo sem ter o que comparar"


def test_conflitos_sem_modelo_avisa(cliente):
    dados = com_grafo()
    assert "event: error" in cliente.post(f"/api/notebooks/{dados['nb']}/conflitos").text


# -------------------------------------------------------------------- notas


def test_nota_pela_rota(cliente):
    dados = com_grafo()
    resposta = cliente.post(
        f"/api/conceitos/{dados['conceito']['id']}/notas",
        json={"body": "Lembrar: isso cai na prova.", "notebook_id": dados["nb"]},
    )

    assert resposta.status_code == 200
    notas = knowledge.notas_do_conceito(dados["conceito"]["id"])
    assert len(notas) == 1
    assert "cai na prova" in notas[0]["body"]

    assert cliente.delete(f"/api/notas/{notas[0]['id']}").status_code == 200
    assert knowledge.notas_do_conceito(dados["conceito"]["id"]) == []


def test_nota_vazia_e_recusada(cliente):
    dados = com_grafo()
    resposta = cliente.post(
        f"/api/conceitos/{dados['conceito']['id']}/notas", json={"body": "   "}
    )
    assert resposta.status_code == 400


def test_nota_de_conceito_inexistente_404(cliente):
    assert cliente.post("/api/conceitos/cpt_fantasma/notas", json={"body": "x"}).status_code == 404


# ------------------------------------------- registro de uso (D051, ponta a ponta)


def test_a_resposta_do_chat_registra_o_uso_da_fonte_citada(cliente, monkeypatch):
    """Ponta a ponta: o agente cita [1] e a fonte 1 fica marcada como usada.

    É o teste que garante que a numeração do prompt e a do registro são a mesma.
    """
    nb = caderno()
    primeira = fonte(nb, TEXTO, "Primeira")
    segunda = fonte(nb, "Material sobre a segunda fonte.", "Segunda")

    monkeypatch.setattr(llm, "atual", lambda: fake.responde("Segundo a fonte [1], sim."))

    cliente.post(f"/api/notebooks/{nb}/chat", json={"input": "o que diz a fonte?"})

    usadas = study.fontes_usadas()
    assert usadas == {primeira["id"]: 1}
    assert segunda["id"] not in usadas

    nunca = study.fontes_nunca_citadas(nb)
    assert [f["title"] for f in nunca] == ["Segunda"]


def test_a_fonte_desligada_nao_entra_na_numeracao(cliente, monkeypatch):
    """A numeração conta SÓ as ativas — é o que o prompt faz, e o registro tem que casar.

    Com uma fonte desligada no meio, um `[1]` que apontasse para ela registraria uso
    da fonte errada. Este teste existe porque essa conta já errou uma vez (no F1).
    """
    nb = caderno()
    desligada = fonte(nb, "Material desligado.", "Desligada")
    ativa = fonte(nb, TEXTO, "Ativa")
    with db.connect() as conn:
        conn.execute("UPDATE sources SET active = 0 WHERE id = ?", (desligada["id"],))

    monkeypatch.setattr(llm, "atual", lambda: fake.responde("Conforme [1], sim."))
    cliente.post(f"/api/notebooks/{nb}/chat", json={"input": "e aí?"})

    usadas = study.fontes_usadas()
    assert usadas == {ativa["id"]: 1}, "registrou uso da fonte desligada (numeração divergiu)"


def test_o_chat_global_tambem_registra_uso(cliente, monkeypatch):
    nb = caderno()
    unica = fonte(nb, TEXTO, "Única")
    monkeypatch.setattr(llm, "atual", lambda: fake.responde("Conforme [1]."))

    cliente.post("/api/global/chat", json={"input": "o que eu tenho?"})

    assert study.fontes_usadas() == {unica["id"]: 1}
