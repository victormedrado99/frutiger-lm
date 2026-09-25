"""Testes do corte "só os conceitos principais" (o que faz um conceito do material).

A regra: um conceito é DO material quando aparece mais de uma vez, **ou** quando
atravessa cadernos (a ponte interessa mesmo citada uma única vez de cada lado).

O que estes testes protegem:

1. **O novelo não volta.** Num caderno com muitos conceitos de passagem, o desenho
   filtrado tem que ficar pequeno — e `ocultos` tem que dizer quantos ficaram fora.
2. **A ponte não se perde.** O corte por menções não pode esconder o único conceito
   que liga dois cadernos: seria esconder a informação mais interessante do grafo.
3. **As lacunas do F4 continuam funcionando.** O corte é do DESENHO: o conceito de
   passagem continua no banco, e `lacunas()` continua vendo ele.
"""

from __future__ import annotations

import asyncio

from frutiger_lm import db, ingest, knowledge

TEXTO = (
    "O protocolo KWP2000 roda sobre a linha K e usa 5 baudes na inicializacao.\n\n"
    "O ISO 14230 descreve o KWP2000 como protocolo de aplicacao da linha K."
)


def caderno(titulo: str = "Caderno") -> str:
    return db.create_notebook(titulo)["id"]


def fonte(notebook_id: str, texto: str = TEXTO, titulo: str = "Fonte") -> dict:
    return asyncio.run(ingest.add_source(notebook_id, kind="text", text=texto, title=titulo))


def mencionar(conceito: str, nb: str, trecho: str, referencia: str, source_id: str) -> dict:
    """Registra uma menção, criando o conceito se ele não existir."""
    dado = knowledge.achar_ou_criar(conceito)
    knowledge.registrar_mencao(
        dado["id"], notebook_id=nb, trecho=trecho, referencia=referencia, source_id=source_id
    )
    return dado


def test_o_conceito_de_passagem_sai_do_desenho():
    nb = caderno()
    src = fonte(nb)
    # duas menções: é conceito do material
    mencionar("KWP2000", nb, "O protocolo KWP2000 roda sobre a linha K", TEXTO, src["id"])
    mencionar("KWP2000", nb, "O ISO 14230 descreve o KWP2000", TEXTO, src["id"])
    # uma menção: passagem
    mencionar("Turbina", nb, "O protocolo KWP2000 roda sobre a linha K", TEXTO, src["id"])

    todos = knowledge.grafo(notebook_id=nb, peso_minimo=1)
    principais = knowledge.grafo(notebook_id=nb, peso_minimo=1, apenas_principais=True)

    assert {n["name"] for n in todos["nodes"]} == {"KWP2000", "Turbina"}
    assert {n["name"] for n in principais["nodes"]} == {"KWP2000"}
    assert principais["ocultos"] == 1


def test_o_conceito_que_atravessa_cadernos_e_principal_mesmo_citado_uma_vez():
    """Uma menção em cada caderno são duas menções — e é a ponte. Não pode sumir."""
    a = caderno("Eletronica")
    b = caderno("Automotivo")
    fonte_a = fonte(a, "O barramento CAN e a ISO 11898 definem a camada fisica.", "CAN")
    fonte_b = fonte(b, TEXTO, "KWP")

    mencionar("Barramento CAN", a, "O barramento CAN e a ISO 11898", "O barramento CAN e a ISO 11898 definem a camada fisica.", fonte_a["id"])
    mencionar("Barramento CAN", b, "O protocolo KWP2000 roda sobre a linha K", TEXTO, fonte_b["id"])

    principais = knowledge.grafo(peso_minimo=1, apenas_principais=True)
    nomes = {n["name"] for n in principais["nodes"]}

    assert "Barramento CAN" in nomes, "a ponte entre cadernos foi escondida pelo corte"
    ponte = [n for n in principais["nodes"] if n["name"] == "Barramento CAN"][0]
    assert ponte["ponte"] is True
    assert sorted(ponte["notebooks"]) == ["Automotivo", "Eletronica"]


def test_as_arestas_do_desenho_filtrado_nao_apontam_para_fora():
    """Aresta para um nó escondido seria uma linha saindo para o nada."""
    nb = caderno()
    src = fonte(nb)
    a = mencionar("KWP2000", nb, "O protocolo KWP2000 roda sobre a linha K", TEXTO, src["id"])
    mencionar("KWP2000", nb, "O ISO 14230 descreve o KWP2000", TEXTO, src["id"])
    b = mencionar("ISO 14230", nb, "O ISO 14230 descreve o KWP2000", TEXTO, src["id"])
    mencionar("ISO 14230", nb, "O protocolo KWP2000 roda sobre a linha K", TEXTO, src["id"])
    # um conceito de passagem ligado aos dois
    solto = mencionar("Turbina", nb, "O protocolo KWP2000 roda sobre a linha K", TEXTO, src["id"])
    knowledge.ligar_explicito(
        a["id"], solto["id"],
        trecho="O protocolo KWP2000 roda sobre a linha K", referencia=TEXTO, quem="modelo",
    )
    knowledge.ligar_explicito(
        b["id"], solto["id"],
        trecho="O ISO 14230 descreve o KWP2000", referencia=TEXTO, quem="modelo",
    )

    filtrado = knowledge.grafo(notebook_id=nb, peso_minimo=1, apenas_principais=True)
    ids = {n["id"] for n in filtrado["nodes"]}

    assert solto["id"] not in ids
    for aresta in filtrado["edges"]:
        assert aresta["a_id"] in ids, f"aresta apontando para fora: {aresta}"
        assert aresta["b_id"] in ids, f"aresta apontando para fora: {aresta}"


def test_o_corte_nao_apaga_o_conceito_nem_quebra_as_lacunas():
    """O corte é do desenho. O F4 continua usando o conceito de passagem."""
    nb = caderno()
    src = fonte(nb)
    mencionar("Turbina", nb, "O protocolo KWP2000 roda sobre a linha K", TEXTO, src["id"])

    assert knowledge.grafo(notebook_id=nb, apenas_principais=True)["nodes"] == []
    assert knowledge.get_conceito(knowledge.achar_ou_criar("Turbina")["id"]) is not None

    nomes = [c["name"] for c in knowledge.lacunas(nb)["nao_desenvolvidos"]]
    assert "Turbina" in nomes, "a lacuna do F4 sumiu junto com o nó do desenho"


def test_sem_o_corte_nada_muda():
    """O padrão do `grafo` continua sendo mostrar tudo — quem filtra é quem pede."""
    nb = caderno()
    src = fonte(nb)
    mencionar("Turbina", nb, "O protocolo KWP2000 roda sobre a linha K", TEXTO, src["id"])

    padrao = knowledge.grafo(notebook_id=nb)
    assert len(padrao["nodes"]) == 1
    assert padrao["ocultos"] == 0


# ----------------------------------------------------------------- a rota


def test_a_rota_aceita_o_corte(cliente):
    nb = caderno()
    src = fonte(nb)
    mencionar("KWP2000", nb, "O protocolo KWP2000 roda sobre a linha K", TEXTO, src["id"])
    mencionar("KWP2000", nb, "O ISO 14230 descreve o KWP2000", TEXTO, src["id"])
    mencionar("Turbina", nb, "O protocolo KWP2000 roda sobre a linha K", TEXTO, src["id"])

    todos = cliente.get(f"/api/grafo?notebook_id={nb}").json()
    cortado = cliente.get(f"/api/grafo?notebook_id={nb}&principalmente=true").json()

    assert len(todos["nodes"]) == 2
    assert [n["name"] for n in cortado["nodes"]] == ["KWP2000"]
    assert cortado["ocultos"] == 1
