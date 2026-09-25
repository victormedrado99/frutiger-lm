"""Testes da extração de conceitos (F3).

O que estes testes protegem:

1. **O vocabulário chega ao modelo e se atualiza entre blocos.** É o mecanismo da
   D041 — sem ele o grafo fragmenta e o F6 vira pré-requisito de uma fase anterior.
2. **O trecho inventado é descartado e contado.** A taxa de descarte é sinal, não
   ruído: se subir, o extrator está alucinando.
3. **Re-extrair substitui, não acumula.**
"""

from __future__ import annotations

import asyncio

from frutiger_lm import db, ingest, knowledge
from frutiger_lm.engine import extracao, fake


def caderno(titulo: str = "Caderno") -> str:
    return db.create_notebook(titulo)["id"]


def fonte(notebook_id: str, texto: str, titulo: str = "Fonte") -> dict:
    return asyncio.run(ingest.add_source(notebook_id, kind="text", text=texto, title=titulo))


def correr(gerador) -> list[dict]:
    async def coletar() -> list[dict]:
        return [evento async for evento in gerador]

    return asyncio.run(coletar())


TEXTO = (
    "O protocolo KWP2000 roda sobre a linha K e é usado no diagnostico.\n\n"
    "O OBD-II exige o conector de 16 pinos e a leitura de codigos de falha.\n\n"
    "O ISO 14230 descreve o KWP2000 como protocolo de nivel de aplicacao."
)


def extracao_de(*conceitos: tuple[str, str], relacoes: list[tuple[str, str, str]] | None = None):
    """Monta um objeto `Extracao` como o modelo devolveria."""
    return extracao.Extracao(
        conceitos=[
            extracao.ConceitoExtraido(nome=nome, trecho=trecho) for nome, trecho in conceitos
        ],
        relacoes=[
            extracao.RelacaoExtraida(de=de, para=para, trecho=trecho)
            for de, para, trecho in (relacoes or [])
        ],
    )


# ---------------------------------------------------------------- fatiamento


def test_texto_curto_vira_um_bloco():
    assert extracao.blocos("conteudo curto") == ["conteudo curto"]


def test_texto_vazio_nao_vira_bloco():
    assert extracao.blocos("") == []


def test_texto_longo_e_fatiado_sem_perder_conteudo():
    texto = "\n\n".join(f"Paragrafo {i} com algum conteudo relevante." * 12 for i in range(40))
    fatias = extracao.blocos(texto, tamanho=2000, sobreposicao=100)

    assert len(fatias) > 1
    assert fatias[0].startswith("Paragrafo 0")
    assert "Paragrafo 39" in fatias[-1]
    for fatia in fatias:
        assert len(fatia) <= 2000 + 200


def test_o_bloco_corta_em_fim_de_paragrafo_quando_da():
    texto = "A" * 800 + "\n\n" + "B" * 800 + "\n\n" + "C" * 800
    fatias = extracao.blocos(texto, tamanho=1000, sobreposicao=50)

    assert fatias[0].endswith("A" * 800), "cortou no meio do paragrafo sem precisar"


def test_o_fatiamento_termina_mesmo_com_sobreposicao_grande():
    """Guarda contra laço infinito: a sobreposição não pode desfazer o avanço."""
    texto = "palavra " * 4000
    fatias = extracao.blocos(texto, tamanho=200, sobreposicao=190)
    assert len(fatias) > 1
    assert len(fatias) < 5000


# ------------------------------------------------------- vocabulário (D041)


def test_o_vocabulario_existente_vai_para_o_modelo():
    # Conceito vindo de OUTRA fonte e de OUTRO caderno: a extração limpa as menções
    # da fonte que vai re-extrair, então ancorar no mesmo lugar não serviria.
    outro = fonte(caderno("Outro caderno"), "material anterior sobre KW P", "Anterior")
    conhecimento = knowledge.achar_ou_criar("KW P")
    knowledge.registrar_mencao(
        conhecimento["id"],
        notebook_id=outro["notebook_id"],
        trecho="material anterior sobre KW P",
        referencia="material anterior sobre KW P",
        source_id=outro["id"],
    )

    nb = caderno()
    src = fonte(nb, TEXTO)
    extrator = fake.extrai([extracao_de()])
    correr(extracao.extrair_fonte(src["id"], modelo=extrator))

    enviadas = "\n".join(str(m.content) for m in extrator.chamadas[0])
    assert "KW P" in enviadas, "o vocabulário existente não chegou ao modelo"
    assert "Reuse estes nomes" in enviadas


def test_o_vocabulario_se_atualiza_entre_blocos():
    """O conceito criado no bloco 1 tem que existir no contexto do bloco 2.

    Sem isto o reuso só acontece dentro de um bloco, e a fragmentação volta — que é
    exatamente o que a D041 existe para evitar.
    """
    texto = ("O protocolo ALFA-1 aparece aqui.\n\n" + "texto de enchimento. " * 600)
    nb = caderno()
    src = fonte(nb, texto)
    extrator = fake.extrai(
        [
            extracao_de(("ALFA-1", "O protocolo ALFA-1 aparece aqui.")),
            extracao_de(),
        ]
    )

    correr(extracao.extrair_fonte(src["id"], modelo=extrator))

    assert len(extrator.chamadas) >= 2, "não chegou a fazer o segundo bloco"
    segundo = "\n".join(str(m.content) for m in extrator.chamadas[1])
    assert "ALFA-1" in segundo, "o conceito do bloco 1 não foi oferecido no bloco 2"


# --------------------------------------------------------------- ancoragem


def test_extrair_grava_as_mencoes_com_origem():
    nb = caderno()
    src = fonte(nb, TEXTO)
    extrator = fake.extrai(
        [
            extracao_de(
                ("KWP2000", "O protocolo KWP2000 roda sobre a linha K"),
                ("OBD-II", "O OBD-II exige o conector de 16 pinos"),
            )
        ]
    )

    eventos = correr(extracao.extrair_fonte(src["id"], modelo=extrator))

    assert eventos[-1]["evento"] == "extract.source_done"
    assert eventos[-1]["mencionadas"] == 2
    assert eventos[-1]["descartadas"] == 0

    conceito = next(c for c in knowledge.grafo()["nodes"] if c["name"] == "KWP2000")
    guardadas = knowledge.mencoes(conceito["id"])
    assert len(guardadas) == 1
    assert guardadas[0]["source_id"] == src["id"]
    assert "linha K" in guardadas[0]["excerpt"]


def test_extrair_descarta_o_trecho_inventado_e_conta():
    """O defeito invisível: o grafo fica bonito e é ficção."""
    nb = caderno()
    src = fonte(nb, TEXTO)
    extrator = fake.extrai(
        [
            extracao_de(
                ("KWP2000", "O protocolo KWP2000 roda sobre a linha K"),
                ("CAN FD", "O CAN FD permite 64 bytes por quadro."),  # não está no texto
            )
        ]
    )

    eventos = correr(extracao.extrair_fonte(src["id"], modelo=extrator))

    assert eventos[-1]["mencionadas"] == 1
    assert eventos[-1]["descartadas"] == 1


def test_o_conceito_inventado_nao_sobra_sem_ancora():
    """Descartado o trecho, o conceito não pode ficar pendurado no grafo."""
    nb = caderno()
    src = fonte(nb, TEXTO)
    extrator = fake.extrai([extracao_de(("CAN FD", "O CAN FD permite 64 bytes por quadro."))])

    correr(extracao.extrair_fonte(src["id"], modelo=extrator))

    assert knowledge.orfaos() == 0
    assert knowledge.grafo()["nodes"] == []


# ------------------------------------------------------------------ arestas


def test_a_co_ocorrencia_sai_de_graca_do_bloco():
    nb = caderno()
    src = fonte(nb, TEXTO)
    extrator = fake.extrai(
        [
            extracao_de(
                ("KWP2000", "O protocolo KWP2000 roda sobre a linha K"),
                ("OBD-II", "O OBD-II exige o conector de 16 pinos"),
                ("ISO 14230", "O ISO 14230 descreve o KWP2000 como protocolo"),
            )
        ]
    )

    correr(extracao.extrair_fonte(src["id"], modelo=extrator))

    assert knowledge.estatisticas()["arestas"] == 3  # C(3,2)


def test_a_relacao_explicita_e_gravada_com_o_trecho_que_a_sustenta():
    nb = caderno()
    src = fonte(nb, TEXTO)
    extrator = fake.extrai(
        [
            extracao_de(
                ("KWP2000", "O protocolo KWP2000 roda sobre a linha K"),
                ("ISO 14230", "O ISO 14230 descreve o KWP2000 como protocolo"),
                relacoes=[("ISO 14230", "KWP2000", "O ISO 14230 descreve o KWP2000 como protocolo")],
            )
        ]
    )

    correr(extracao.extrair_fonte(src["id"], modelo=extrator))

    explicitas = [e for e in knowledge.grafo()["edges"] if e["kind"] == knowledge.EXPLICITA]
    assert len(explicitas) == 1
    assert "modelo" in explicitas[0]["provenance"]


def test_a_relacao_com_trecho_inventado_nao_entra():
    nb = caderno()
    src = fonte(nb, TEXTO)
    extrator = fake.extrai(
        [
            extracao_de(
                ("KWP2000", "O protocolo KWP2000 roda sobre a linha K"),
                ("OBD-II", "O OBD-II exige o conector de 16 pinos"),
                relacoes=[("KWP2000", "OBD-II", "O KWP2000 substituiu o OBD-II nos carros novos")],
            )
        ]
    )

    correr(extracao.extrair_fonte(src["id"], modelo=extrator))

    explicitas = [e for e in knowledge.grafo()["edges"] if e["kind"] == knowledge.EXPLICITA]
    assert explicitas == []


# ------------------------------------------------------------------ pipeline


def test_re_extrair_substitui_em_vez_de_acumular():
    nb = caderno()
    src = fonte(nb, TEXTO)
    uma_vez = fake.extrai(
        [extracao_de(("KWP2000", "O protocolo KWP2000 roda sobre a linha K"))]
    )
    correr(extracao.extrair_fonte(src["id"], modelo=uma_vez))
    assert knowledge.estatisticas()["mencoes"] == 1

    de_novo = fake.extrai(
        [extracao_de(("KWP2000", "O protocolo KWP2000 roda sobre a linha K"))]
    )
    correr(extracao.extrair_fonte(src["id"], modelo=de_novo))

    assert knowledge.estatisticas()["mencoes"] == 1, "duplicou na re-extração"
    assert knowledge.estatisticas()["conceitos"] == 1


def test_o_progresso_e_emitido_por_bloco():
    texto = "O protocolo ALFA aparece aqui.\n\n" + "enchimento. " * 600
    nb = caderno()
    src = fonte(nb, texto)
    extrator = fake.extrai([extracao_de(("ALFA", "O protocolo ALFA aparece aqui."))])

    eventos = correr(extracao.extrair_fonte(src["id"], modelo=extrator))
    nomes = [e["evento"] for e in eventos]

    assert nomes[0] == "extract.source"
    assert eventos[0]["blocos"] >= 2
    assert nomes.count("extract.block") >= 2
    assert nomes[-1] == "extract.source_done"


def test_extrair_caderno_passa_por_todas_as_fontes():
    nb = caderno()
    fonte(nb, TEXTO, "Primeira")
    fonte(nb, "Material sobre sensores.\n\nO sensor de oxigenio mede a mistura.", "Segunda")
    extrator = fake.extrai(
        [
            extracao_de(("KWP2000", "O protocolo KWP2000 roda sobre a linha K")),
            extracao_de(("Sensor de oxigênio", "O sensor de oxigenio mede a mistura.")),
        ]
    )

    eventos = correr(extracao.extrair_caderno(nb, modelo=extrator))
    final = eventos[-1]

    assert final["evento"] == "extract.done"
    assert final["mencionadas"] == 2
    assert final["conceitos"] == 2
    assert [e["fonte"] for e in eventos if e["evento"] == "extract.next"] == [
        "Primeira",
        "Segunda",
    ]


def test_extrair_caderno_sem_fonte_ativa_avisa_e_nao_quebra():
    nb = caderno()
    eventos = correr(extracao.extrair_caderno(nb))
    assert eventos[-1]["evento"] == "extract.done"
    assert "Nenhuma fonte ativa" in eventos[-1]["message"]


def test_fonte_inexistente_avisa():
    eventos = correr(extracao.extrair_fonte("src_nao_existe"))
    assert eventos[0]["evento"] == "error"


def test_sem_modelo_configurado_o_erro_vira_evento_acionavel():
    nb = caderno()
    src = fonte(nb, TEXTO)

    eventos = correr(extracao.extrair_fonte(src["id"]))

    assert eventos[-1]["evento"] == "error"
    assert "não configurado" in eventos[-1]["message"].lower()


def test_a_fonte_sem_texto_legivel_nao_chama_o_modelo():
    """Fonte cadastrada mas com arquivo ausente: avisa, não estoura."""
    nb = caderno()
    vazia = db.create_source(nb, kind="text", title="Vazia", path="", chars=0)

    eventos = correr(extracao.extrair_fonte(vazia["id"], modelo=fake.extrai([])))

    assert eventos[-1]["evento"] == "extract.source_done"
    assert eventos[-1]["mencionadas"] == 0
    assert "não tem texto legível" in eventos[-1]["motivo"]
