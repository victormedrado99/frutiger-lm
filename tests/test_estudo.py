"""Testes do estudo (F4): cards, agendamento e lacunas.

O que estes testes protegem:

1. **O agendamento faz o que promete.** Card errado volta rápido; card bom espaça.
   Se isto quebrar, a revisão do dia vira aleatória e o SRS perde a função.
2. **O card é conferível sozinho.** Ele guarda o próprio trecho: se o conceito sair
   do grafo, o verso continua tendo prova ao lado.
3. **Lacuna é fato, não opinião.** Cada item das lacunas é uma consulta ao grafo —
   e há teste de que um material completo NÃO produz lacuna falsa.
"""

from __future__ import annotations

import asyncio

from frutiger_lm import db, ingest, knowledge, study

DIA = 86400.0


def caderno(titulo: str = "Caderno") -> str:
    return db.create_notebook(titulo)["id"]


def fonte(notebook_id: str, texto: str, titulo: str = "Fonte") -> dict:
    return asyncio.run(ingest.add_source(notebook_id, kind="text", text=texto, title=titulo))


TEXTO = (
    "O protocolo KWP2000 roda sobre a linha K.\n\n"
    "O ISO 14230 descreve o KWP2000 como protocolo de aplicacao."
)


# --------------------------------------------------------------- agendamento


def test_card_novo_nasce_devido():
    """Se você criou, é para revisar — não para revisar amanhã."""
    nb = caderno()
    card = study.criar_card(nb, front="O que é KWP2000?", back="Um protocolo.")

    assert card["reps"] == 0
    assert card["due_at"] <= card["created_at"] + 1
    assert [c["id"] for c in study.devidos(nb)] == [card["id"]]


def test_acertar_espaca_a_revisao():
    nb = caderno()
    card = study.criar_card(nb, front="p", back="r")
    momento = card["created_at"]

    primeiro = study.agendar(card, "bom", agora=momento)
    assert primeiro["interval_days"] == 1.0
    assert primeiro["due_at"] == momento + DIA

    segundo = study.agendar({**card, **primeiro}, "bom", agora=momento)
    assert segundo["interval_days"] == 6.0

    terceiro = study.agendar({**card, **segundo}, "bom", agora=momento)
    assert terceiro["interval_days"] == 6.0 * 2.5
    assert terceiro["due_at"] > momento + 14 * DIA


def test_errar_volta_na_mesma_sessao_e_derruba_o_fator():
    """Um card que você erra não pode voltar em três dias só porque a média subiu."""
    nb = caderno()
    card = study.criar_card(nb, front="p", back="r")
    adiantado = study.agendar(card, "bom", agora=card["created_at"])
    maduro = {**card, **adiantado}

    errado = study.agendar(maduro, "errei", agora=card["created_at"])

    assert errado["interval_days"] == 0.0
    assert errado["due_at"] <= card["created_at"] + 15 * 60
    assert errado["reps"] == 0, "errar não pode contar como acerto"
    assert errado["lapses"] == 1
    assert errado["ease"] < maduro["ease"]


def test_facil_espaca_mais_que_bom_e_dificil_menos():
    nb = caderno()
    card = study.criar_card(nb, front="p", back="r")
    primeiro = study.agendar(card, "bom", agora=card["created_at"])
    base = {**card, **primeiro}

    facil = study.agendar(base, "facil", agora=card["created_at"])
    bom = study.agendar(base, "bom", agora=card["created_at"])
    dificil = study.agendar(base, "dificil", agora=card["created_at"])

    assert facil["due_at"] > bom["due_at"] > dificil["due_at"]


def test_o_fator_de_facilidade_tem_piso_e_teto():
    """Sem piso, um card errado muitas vezes nunca mais sai da revisão de hoje."""
    nb = caderno()
    card = study.criar_card(nb, front="p", back="r")

    atual = card
    for _ in range(30):
        atual = {**atual, **study.agendar(atual, "errei", agora=card["created_at"])}
    assert atual["ease"] == 1.3

    for _ in range(30):
        atual = {**atual, **study.agendar(atual, "facil", agora=card["created_at"])}
    assert atual["ease"] == 3.0


def test_nota_desconhecida_e_recusada():
    nb = caderno()
    card = study.criar_card(nb, front="p", back="r")
    try:
        study.agendar(card, "mais_ou_menos")
    except ValueError as exc:
        assert "Nota desconhecida" in str(exc)
        return
    raise AssertionError("aceitou uma nota que não existe")


def test_revisar_grava_e_reagenda():
    nb = caderno()
    card = study.criar_card(nb, front="p", back="r")

    revisado = study.revisar(card["id"], "bom", agora=card["created_at"])

    assert revisado["reps"] == 1
    assert revisado["interval_days"] == 1.0
    assert study.devidos(nb, agora=card["created_at"] + 3600) == []
    assert len(study.devidos(nb, agora=card["created_at"] + 2 * DIA)) == 1


def test_devidos_traz_o_mais_atrasado_primeiro():
    """Sessão interrompida no meio tem que ter coberto o que mais importa."""
    nb = caderno()
    novo = study.criar_card(nb, front="novo", back="r")
    antigo = study.criar_card(nb, front="antigo", back="r")
    with db.connect() as conn:
        conn.execute("UPDATE cards SET due_at = ? WHERE id = ?", (1.0, antigo["id"]))
        conn.execute("UPDATE cards SET due_at = ? WHERE id = ?", (2.0, novo["id"]))

    ordem = [c["front"] for c in study.devidos(nb)]
    assert ordem == ["antigo", "novo"]


def test_devidos_respeita_o_caderno():
    a = caderno("A")
    b = caderno("B")
    study.criar_card(a, front="do A", back="r")
    study.criar_card(b, front="do B", back="r")

    assert [c["front"] for c in study.devidos(a)] == ["do A"]
    assert study.resumo(a)["vencidos"] == 1


def test_o_card_guarda_o_proprio_trecho():
    """Ele não depende do conceito para continuar conferível."""
    nb = caderno()
    src = fonte(nb, TEXTO)
    conceito = knowledge.achar_ou_criar("KWP2000")

    card = study.criar_card(
        nb,
        front="O que é KWP2000?",
        back="Um protocolo de diagnóstico.",
        concept_id=conceito["id"],
        source_id=src["id"],
        excerpt="O protocolo KWP2000 roda sobre a linha K.",
    )
    knowledge.apagar(conceito["id"])

    relido = study.get_card(card["id"])
    assert relido is not None, "o card sumiu junto com o conceito"
    assert "linha K" in relido["excerpt"], "perdeu a prova ao lado do verso"


def test_apagar_o_caderno_recolhe_os_conceitos_que_ficaram_sos():
    """Um conceito vive nas menções; sem menção nenhuma, é resto — e resto suja a conta."""
    nb = caderno()
    src = asyncio.run(ingest.add_source(nb, kind="text", text=TEXTO, title="Fonte"))
    so = knowledge.achar_ou_criar("KWP2000")
    knowledge.registrar_mencao(
        so["id"],
        notebook_id=nb,
        trecho="O protocolo KWP2000 roda sobre a linha K",
        referencia=TEXTO,
        source_id=src["id"],
    )
    conhecimento = knowledge.achar_ou_criar("ISO 14230")
    knowledge.registrar_mencao(
        conhecimento["id"],
        notebook_id=nb,
        trecho="O ISO 14230 descreve o KWP2000",
        referencia=TEXTO,
        source_id=src["id"],
    )
    knowledge.ligar_explicito(
        so["id"], conhecimento["id"],
        trecho="O ISO 14230 descreve o KWP2000", referencia=TEXTO, quem="modelo",
    )

    db.delete_notebook(nb)

    assert knowledge.get_conceito(so["id"]) is None, "o conceito ficou sem menção e não foi recolhido"
    assert knowledge.get_conceito(conhecimento["id"]) is None
    assert knowledge.estatisticas()["conceitos"] == 0
    assert knowledge.estatisticas()["arestas"] == 0


def test_apagar_um_caderno_nao_dana_o_grafo_do_outro():
    """O caso que mais importa: o que é compartilhado sobrevive ao caderno que sai.

    Um conceito com menção nos DOIS cadernos não pode ser recolhido quando um deles é
    apagado — ele continua vivo no outro, e é justamente a ponte entre os dois.

    (A variante "preserva o conceito que tem nota" não faz sentido como teste: a nota
    tem `notebook_id` e sai junto com o caderno pelo cascade, então ela nunca chega a
    proteger nada. A condição fica no código porque uma nota SEM caderno — criada por
    outro caminho — deve segurar o nome.)
    """
    a = caderno("A")
    b = caderno("B")
    fonte_a = asyncio.run(ingest.add_source(a, kind="text", text=TEXTO, title="Fonte A"))
    fonte_b = asyncio.run(ingest.add_source(b, kind="text", text=TEXTO, title="Fonte B"))

    compartilhado = knowledge.achar_ou_criar("KWP2000")
    for nb, src in ((a, fonte_a), (b, fonte_b)):
        knowledge.registrar_mencao(
            compartilhado["id"],
            notebook_id=nb,
            trecho="O protocolo KWP2000 roda sobre a linha K",
            referencia=TEXTO,
            source_id=src["id"],
        )
    so_do_a = knowledge.achar_ou_criar("Turbina")
    knowledge.registrar_mencao(
        so_do_a["id"],
        notebook_id=a,
        trecho="O protocolo KWP2000 roda sobre a linha K",
        referencia=TEXTO,
        source_id=fonte_a["id"],
    )

    db.delete_notebook(a)

    assert knowledge.get_conceito(compartilhado["id"]) is not None, "dano no grafo do outro caderno"
    assert knowledge.get_conceito(so_do_a["id"]) is None, "o conceito que só existia no apagado ficou"
    assert knowledge.estatisticas()["conceitos"] == 1


def test_apagar_o_caderno_leva_os_cards():
    nb = caderno()
    study.criar_card(nb, front="p", back="r")
    db.delete_notebook(nb)
    assert study.resumo()["total"] == 0


def test_resumo_conta_total_vencidos_e_aprendendo():
    nb = caderno()
    a = study.criar_card(nb, front="a", back="r")
    study.criar_card(nb, front="b", back="r")
    study.revisar(a["id"], "bom", agora=a["created_at"])

    r = study.resumo(nb, agora=a["created_at"] + 3600)
    assert r["total"] == 2
    assert r["vencidos"] == 1, "o revisado ainda não venceu"
    assert r["aprendendo"] == 1


# ------------------------------------------------------------ uso das fontes


def test_a_citacao_registra_o_uso_da_fonte():
    """D051: o `[n]` que o modelo já escreve é o registro de uso."""
    nb = caderno()
    a = fonte(nb, TEXTO, "Primeira")
    b = fonte(nb, "Material sobre sensores.", "Segunda")
    numeradas = db.list_sources(nb)  # a ordem canônica da numeração

    registrados = study.registrar_uso_de_citacoes(
        "O protocolo roda sobre a linha K [1]. E o sensor mede [2].", numeradas
    )

    assert set(registrados) == {a["id"], b["id"]}
    assert study.fontes_usadas() == {a["id"]: 1, b["id"]: 1}


def test_citacao_inexistente_e_ignorada():
    """O modelo às vezes escreve `[7]` num caderno de três fontes.

    Inventar um uso a partir disso seria pior do que não registrar.
    """
    nb = caderno()
    fonte(nb, TEXTO, "Única")
    numeradas = db.list_sources(nb)

    assert study.registrar_uso_de_citacoes("conferir [7] e [0]", numeradas) == []
    assert study.fontes_usadas() == {}


def test_a_mesma_fonte_citada_duas_vezes_conta_uma():
    nb = caderno()
    fonte(nb, TEXTO, "Primeira")
    numeradas = db.list_sources(nb)
    study.registrar_uso_de_citacoes("isso [1] e aquilo [1]", numeradas)
    assert list(study.fontes_usadas().values()) == [1]


def test_fonte_nunca_citada_e_listada():
    nb = caderno()
    a = fonte(nb, TEXTO, "Usada")
    fonte(nb, "Outro material.", "Esquecida")
    numeradas = db.list_sources(nb)

    study.registrar_uso_de_citacoes("conforme [1]", numeradas)

    orfas = study.fontes_nunca_citadas(nb)
    assert [f["title"] for f in orfas] == ["Esquecida"]
    assert a["id"] not in [f["id"] for f in orfas]


# ------------------------------------------------------------------- lacunas


def test_conceito_nomeado_e_nao_desenvolvido_e_lacuna():
    nb = caderno()
    src = fonte(nb, TEXTO)

    # O material citou uma vez e nunca ligou a nada
    from frutiger_lm.engine import extracao

    eventos = asyncio.run(
        _rodar_extracao(
            src["id"],
            extracao.ConceitoExtraido(nome="Turbina", trecho="O protocolo KWP2000 roda sobre a linha K."),
        )
    )
    assert eventos[-1]["evento"] == "extract.source_done"

    nomes = [x["name"] for x in knowledge.lacunas(nb)["nao_desenvolvidos"]]
    assert "Turbina" in nomes


def test_conceito_bem_ligado_nao_e_lacuna():
    """O material explicou: não pode aparecer como buraco."""
    nb = caderno()
    src = fonte(nb, TEXTO)
    a = knowledge.achar_ou_criar("KWP2000")
    b = knowledge.achar_ou_criar("ISO 14230")
    knowledge.registrar_mencao(
        a["id"], notebook_id=nb, trecho="O protocolo KWP2000 roda sobre a linha K.",
        referencia=TEXTO, source_id=src["id"],
    )
    knowledge.ligar_explicito(
        a["id"], b["id"],
        trecho="O ISO 14230 descreve o KWP2000 como protocolo de aplicacao.",
        referencia=TEXTO, quem="modelo",
    )

    nomes = [x["name"] for x in knowledge.lacunas(nb)["nao_desenvolvidos"]]
    assert "KWP2000" not in nomes, "o material desenvolveu e virou lacuna"


def test_conceito_de_outro_caderno_e_lacuna():
    """Só é possível saber porque o grafo é global (D045)."""
    outro = caderno("Eletronica")
    src_outro = fonte(outro, "Material sobre o barramento CAN.", "CAN")
    la = knowledge.achar_ou_criar("Barramento CAN")
    knowledge.registrar_mencao(
        la["id"], notebook_id=outro, trecho="Material sobre o barramento CAN.",
        referencia="Material sobre o barramento CAN.", source_id=src_outro["id"],
    )

    nb = caderno("Automotivo")
    fonte(nb, TEXTO)

    lacuna = knowledge.lacunas(nb)["em_outro_caderno"]
    assert [x["name"] for x in lacuna] == ["Barramento CAN"]
    assert "Eletronica" in lacuna[0]["onde"]


def test_conceito_que_esta_neste_caderno_nao_e_lacuna_dele():
    nb = caderno("Automotivo")
    src = fonte(nb, TEXTO)
    c = knowledge.achar_ou_criar("KWP2000")
    knowledge.registrar_mencao(
        c["id"], notebook_id=nb, trecho="O protocolo KWP2000 roda sobre a linha K.",
        referencia=TEXTO, source_id=src["id"],
    )

    assert knowledge.lacunas(nb)["em_outro_caderno"] == []


def test_fonte_sem_contribuicao_e_lacuna():
    nb = caderno()
    fonte(nb, TEXTO, "Contribuiu")
    fonte(nb, "Material que ninguem extraiu.", "Não contribuiu")
    c = knowledge.achar_ou_criar("KWP2000")
    knowledge.registrar_mencao(
        c["id"], notebook_id=nb, trecho="O protocolo KWP2000 roda sobre a linha K.",
        referencia=TEXTO, source_id=db.list_sources(nb)[0]["id"],
    )

    nomes = [f["title"] for f in knowledge.lacunas(nb)["fontes_sem_contribuicao"]]
    assert nomes == ["Não contribuiu"], "a fonte que gerou menção não pode ser lacuna"


def test_conceitos_por_fonte_conta_o_que_cada_material_deu():
    nb = caderno()
    src1 = fonte(nb, TEXTO, "Rica")
    fonte(nb, "Material curto sobre sensores.", "Pobre")
    a = knowledge.achar_ou_criar("KWP2000")
    b = knowledge.achar_ou_criar("ISO 14230")
    for conceito, trecho in ((a, "O protocolo KWP2000 roda"), (b, "O ISO 14230 descreve")):
        knowledge.registrar_mencao(
            conceito["id"], notebook_id=nb, trecho=trecho, referencia=TEXTO, source_id=src1["id"],
        )

    por_fonte = {f["title"]: f["conceitos"] for f in knowledge.conceitos_por_fonte(nb)}
    assert por_fonte["Rica"] == 2
    assert por_fonte["Pobre"] == 0


async def _rodar_extracao(source_id: str, *conceitos):
    """Roda a extração com o objeto já pronto, para o teste de lacuna."""
    from frutiger_lm.engine import extracao, fake

    extrator = fake.extrai([extracao.Extracao(conceitos=list(conceitos))])
    return [evento async for evento in extracao.extrair_fonte(source_id, modelo=extrator)]
