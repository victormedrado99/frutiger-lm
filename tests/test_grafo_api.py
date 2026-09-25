"""Testes das ferramentas de grafo e das rotas do F3.

O que estes testes protegem:

1. **As ferramentas não inventam.** `vizinhanca_do_conceito` responde do que está
   registrado; se nada está ligado, ela diz que nada está ligado — em vez de
   preencher com conhecimento de modelo.
2. **A ferramenta de escrita recusa trecho que não existe na fonte.** É a mesma
   ancoragem da extração, agora na mão do agente.
3. **A interface e o agente fazem a mesma coisa** (D024): as rotas passam pelo
   `knowledge`, então mesclar na tela e mesclar por ferramenta são o mesmo código.
"""

from __future__ import annotations

import asyncio

from frutiger_lm import db, ingest, knowledge
from frutiger_lm.engine import fake, llm
from frutiger_lm.engine.extracao import ConceitoExtraido, Extracao
from frutiger_lm.engine.tools.grafo import ferramentas_de_grafo

TEXTO = (
    "O protocolo KWP2000 roda sobre a linha K e e usado no diagnostico.\n\n"
    "O OBD-II exige o conector de 16 pinos.\n\n"
    "O ISO 14230 descreve o KWP2000 como protocolo de aplicacao."
)


def caderno(titulo: str = "Caderno") -> str:
    return db.create_notebook(titulo)["id"]


def fonte(notebook_id: str, texto: str = TEXTO, titulo: str = "Fonte") -> dict:
    return asyncio.run(ingest.add_source(notebook_id, kind="text", text=texto, title=titulo))


def ferramenta(nome: str):
    return {t.name: t for t in ferramentas_de_grafo()}[nome]


def extrai(nome: str, trecho: str) -> Extracao:
    """O objeto que o modelo devolveria, para testar sem rede."""
    return Extracao(conceitos=[ConceitoExtraido(nome=nome, trecho=trecho)])


def com_grafo() -> dict:
    """Um grafo mínimo montado à mão: dois conceitos ancorados e uma ligação."""
    nb = caderno()
    src = fonte(nb)
    kwp = knowledge.achar_ou_criar("KWP2000")
    obd = knowledge.achar_ou_criar("OBD-II")
    knowledge.registrar_mencao(
        kwp["id"],
        notebook_id=nb,
        trecho="O protocolo KWP2000 roda sobre a linha K",
        referencia=TEXTO,
        source_id=src["id"],
    )
    knowledge.registrar_mencao(
        obd["id"],
        notebook_id=nb,
        trecho="O OBD-II exige o conector de 16 pinos.",
        referencia=TEXTO,
        source_id=src["id"],
    )
    knowledge.ligar_explicito(
        kwp["id"],
        obd["id"],
        trecho="O ISO 14230 descreve o KWP2000 como protocolo de aplicacao.",
        referencia=TEXTO,
        quem="modelo",
    )
    return {"nb": nb, "src": src, "kwp": kwp, "obd": obd}


# ------------------------------------------------------------------ as tools


def test_buscar_no_grafo_vazio_explica_que_esta_vazio():
    saida = ferramenta("buscar_no_grafo").invoke({"termo": "qualquer coisa"})
    assert "grafo está vazio" in saida
    assert "extrair" in saida, "não disse o que fazer a respeito"


def test_buscar_no_grafo_acha_por_nome_e_diz_onde_aparece():
    com_grafo()
    saida = ferramenta("buscar_no_grafo").invoke({"termo": "kwp"})

    assert "KWP2000" in saida
    assert "Caderno" in saida
    assert "menção" in saida


def test_buscar_no_grafo_sem_achado_nao_deixa_o_agente_no_vazio():
    com_grafo()
    saida = ferramenta("buscar_no_grafo").invoke({"termo": "turbina"})
    assert "Nada no grafo" in saida
    assert "conceito(s) registrado(s)" in saida


def test_vizinhanca_traz_a_ligacao_e_o_trecho_que_a_sustenta():
    com_grafo()
    saida = ferramenta("vizinhanca_do_conceito").invoke({"conceito": "KWP2000"})

    assert "OBD-II" in saida
    assert "ISO 14230" in saida, "não trouxe o trecho que sustenta a ligação"
    assert "Onde aparece" in saida


def test_vizinhanca_de_conceito_isolado_diz_que_nao_ha_ligacao():
    """A ferramenta não preenche com conhecimento de modelo.

    Um conceito mencionado mas nunca relacionado tem que sair como tal: o grafo não
    inventa aresta, e o agente precisa saber que não há nada registrado.
    """
    nb = caderno()
    src = fonte(nb)
    solto = knowledge.achar_ou_criar("Sensor de oxigênio")
    knowledge.registrar_mencao(
        solto["id"],
        notebook_id=nb,
        trecho="O protocolo KWP2000 roda sobre a linha K",
        referencia=TEXTO,
        source_id=src["id"],
    )

    saida = ferramenta("vizinhanca_do_conceito").invoke({"conceito": "Sensor de oxigênio"})

    assert "Nada ligado" in saida
    assert "não inventa ligação" in saida


def test_vizinhanca_de_conceito_inexistente_manda_buscar_e_nao_inventar():
    com_grafo()
    saida = ferramenta("vizinhanca_do_conceito").invoke({"conceito": "Turbina"})
    assert "não está no grafo" in saida
    assert "buscar_no_grafo" in saida


def test_vizinhanca_separa_afirmado_de_co_ocorrencia():
    nb = caderno()
    src = fonte(nb)
    a = knowledge.achar_ou_criar("ALFA")
    b = knowledge.achar_ou_criar("BETA")
    c = knowledge.achar_ou_criar("GAMA")
    knowledge.registrar_mencao(a["id"], notebook_id=nb, trecho="O protocolo KWP2000 roda", referencia=TEXTO, source_id=src["id"])
    knowledge.ligar(a["id"], b["id"], knowledge.CO_OCORRENCIA)
    knowledge.ligar_explicito(a["id"], c["id"], trecho="O OBD-II exige o conector", referencia=TEXTO, quem="modelo")

    saida = ferramenta("vizinhanca_do_conceito").invoke({"conceito": "ALFA"})

    assert "afirmadas pelo material" in saida
    assert "Aparecem no mesmo trecho" in saida


def test_registrar_relacao_grava_com_o_trecho_da_fonte():
    dados = com_grafo()
    outra = knowledge.achar_ou_criar("ISO 14230")

    saida = ferramenta("registrar_relacao").invoke(
        {
            "de": "KWP2000",
            "para": "ISO 14230",
            "trecho": "O ISO 14230 descreve o KWP2000 como protocolo de aplicacao.",
            "fonte_id": dados["src"]["id"],
        }
    )

    assert "Registrei" in saida
    explicitas = {
        frozenset((e["a_id"], e["b_id"]))
        for e in knowledge.grafo()["edges"]
        if e["kind"] == knowledge.EXPLICITA
    }
    assert frozenset((dados["kwp"]["id"], outra["id"])) in explicitas


def test_registrar_relacao_recusa_trecho_inventado():
    """A ancoragem vale também para o que o agente escreve no grafo."""
    dados = com_grafo()
    knowledge.achar_ou_criar("ISO 14230")
    antes = knowledge.estatisticas()["arestas"]

    saida = ferramenta("registrar_relacao").invoke(
        {
            "de": "KWP2000",
            "para": "ISO 14230",
            "trecho": "O KWP2000 foi substituido pelo ISO 14230 em 2015.",
            "fonte_id": dados["src"]["id"],
        }
    )

    assert "Recusei" in saida
    assert "não existe na fonte" in saida
    assert knowledge.estatisticas()["arestas"] == antes


def test_registrar_relacao_recusa_fonte_inexistente():
    com_grafo()
    saida = ferramenta("registrar_relacao").invoke(
        {"de": "KWP2000", "para": "OBD-II", "trecho": "qualquer", "fonte_id": "src_fantasma"}
    )
    assert "Não achei a fonte" in saida


def test_registrar_relacao_recusa_conceito_que_nao_existe():
    """Nada de criar conceito por conta própria: isso fragmentaria o grafo."""
    dados = com_grafo()
    antes = knowledge.estatisticas()["conceitos"]

    saida = ferramenta("registrar_relacao").invoke(
        {
            "de": "KWP2000",
            "para": "Turbina",
            "trecho": "O protocolo KWP2000 roda sobre a linha K",
            "fonte_id": dados["src"]["id"],
        }
    )

    assert "não está no grafo" in saida
    assert knowledge.estatisticas()["conceitos"] == antes


# ------------------------------------------------------------------ as rotas


def test_a_rota_do_grafo_devolve_nos_arestas_e_estatisticas(cliente):
    com_grafo()
    dados = cliente.get("/api/grafo").json()

    assert len(dados["nodes"]) == 2
    assert len(dados["edges"]) == 1
    assert dados["conceitos"] == 2
    assert dados["orfaos"] == 0, "o grafo não pode ter conceito sem âncora"
    assert {n["name"] for n in dados["nodes"]} == {"KWP2000", "OBD-II"}
    assert dados["notebooks"] == ["Caderno"]


def test_a_rota_do_grafo_aceita_filtro_por_caderno(cliente):
    dados = com_grafo()
    outro = caderno("Outro")
    src2 = fonte(outro, "Material sobre turbinas.", "Turbinas")
    t = knowledge.achar_ou_criar("Turbina")
    knowledge.registrar_mencao(
        t["id"], notebook_id=outro, trecho="Material sobre turbinas.", referencia="Material sobre turbinas.", source_id=src2["id"]
    )

    completo = cliente.get("/api/grafo").json()
    filtrado = cliente.get(f"/api/grafo?notebook_id={dados['nb']}").json()

    assert len(completo["nodes"]) == 3
    assert {n["name"] for n in filtrado["nodes"]} == {"KWP2000", "OBD-II"}


def test_a_rota_do_grafo_404_para_caderno_inexistente(cliente):
    assert cliente.get("/api/grafo?notebook_id=nb_fantasma").status_code == 404


def test_a_rota_do_conceito_traz_mencoes_e_vizinhos(cliente):
    dados = com_grafo()
    corpo = cliente.get(f"/api/conceitos/{dados['kwp']['id']}").json()

    assert corpo["concept"]["name"] == "KWP2000"
    assert len(corpo["mentions"]) == 1
    assert corpo["mentions"][0]["source_title"] == "Fonte"
    assert corpo["neighbors"][0]["concept"]["name"] == "OBD-II"


def test_a_rota_do_conceito_404(cliente):
    assert cliente.get("/api/conceitos/cpt_fantasma").status_code == 404


def test_listar_conceitos_com_e_sem_termo(cliente):
    com_grafo()
    todos = cliente.get("/api/conceitos").json()
    filtrado = cliente.get("/api/conceitos?termo=obd").json()

    assert len(todos) == 2
    assert [c["name"] for c in filtrado] == ["OBD-II"]


def test_mesclar_pela_rota_migra_a_mencao(cliente):
    """A rota e a ferramenta são a mesma implementação (D024)."""
    dados = com_grafo()
    outro = knowledge.achar_ou_criar("OBD2")

    resposta = cliente.post(
        "/api/conceitos/mesclar", json={"de": outro["id"], "para": dados["obd"]["id"]}
    )

    assert resposta.status_code == 200
    assert knowledge.get_conceito(outro["id"]) is None
    assert "OBD2" in resposta.json()["aliases"]


def test_mesclar_com_os_dois_iguais_e_recusado(cliente):
    dados = com_grafo()
    resposta = cliente.post(
        "/api/conceitos/mesclar", json={"de": dados["kwp"]["id"], "para": dados["kwp"]["id"]}
    )
    assert resposta.status_code == 400


def test_renomear_pela_rota(cliente):
    dados = com_grafo()
    resposta = cliente.post(
        f"/api/conceitos/{dados['kwp']['id']}/renomear", json={"nome": "KWP 2000 (ISO 14230)"}
    )
    assert resposta.status_code == 200
    assert resposta.json()["name"] == "KWP 2000 (ISO 14230)"


def test_renomear_sem_nome_e_recusado(cliente):
    dados = com_grafo()
    assert cliente.post(
        f"/api/conceitos/{dados['kwp']['id']}/renomear", json={"nome": "  "}
    ).status_code == 400


def test_apagar_conceito_pela_rota(cliente):
    dados = com_grafo()
    assert cliente.delete(f"/api/conceitos/{dados['kwp']['id']}").status_code == 200
    assert cliente.get(f"/api/conceitos/{dados['kwp']['id']}").status_code == 404
    assert cliente.delete("/api/conceitos/cpt_fantasma").status_code == 404


def test_a_extracao_pela_rota_emite_progresso_e_grava(cliente, monkeypatch):
    nb = caderno()
    fonte(nb, TEXTO)
    monkeypatch.setattr(
        llm,
        "atual",
        lambda: fake.extrai([extrai("KWP2000", "O protocolo KWP2000 roda sobre a linha K")]),
    )

    resposta = cliente.post(f"/api/notebooks/{nb}/extrair")
    corpo = resposta.text

    assert resposta.status_code == 200
    for evento in ("extract.next", "extract.source", "extract.block", "extract.source_done", "extract.done"):
        assert f"event: {evento}" in corpo, f"faltou o evento {evento}"

    conceito = knowledge.buscar("KWP2000")
    assert len(conceito) == 1
    assert conceito[0]["mentions"] == 1


def test_a_extracao_pela_rota_avisa_sem_modelo(cliente):
    nb = caderno()
    fonte(nb, TEXTO)
    resposta = cliente.post(f"/api/notebooks/{nb}/extrair")
    assert "event: error" in resposta.text
    assert "não configurado" in resposta.text


def test_a_extracao_404_para_caderno_inexistente(cliente):
    assert cliente.post("/api/notebooks/nb_fantasma/extrair").status_code == 404
