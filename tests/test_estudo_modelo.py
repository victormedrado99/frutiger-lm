"""Testes dos usos de modelo do F4: compor card e achar contradição.

O que estes testes protegem:

1. **O card nasce com lastro.** Ele vem de um trecho que já estava validado no grafo, e
   o trecho fica gravado ao lado do verso.
2. **A contradição exige os dois lados, de fontes diferentes.** Um modelo dizendo
   "há conflito" e citando o mesmo trecho duas vezes não entra. É esta checagem que
   separa "o material se contradiz" de "o modelo achou que sim".
"""

from __future__ import annotations

import asyncio

from frutiger_lm import db, ingest, knowledge, study
from frutiger_lm.engine import estudo, fake


def caderno(titulo: str = "Caderno") -> str:
    return db.create_notebook(titulo)["id"]


def fonte(notebook_id: str, texto: str, titulo: str = "Fonte") -> dict:
    return asyncio.run(ingest.add_source(notebook_id, kind="text", text=texto, title=titulo))


TEXTO = (
    "O protocolo KWP2000 roda sobre a linha K e usa 5 baudes na inicializacao.\n\n"
    "O ISO 14230 descreve o KWP2000 como protocolo de aplicacao."
)


def correr(gerador) -> list[dict]:
    async def coletar() -> list[dict]:
        return [evento async for evento in gerador]

    return asyncio.run(coletar())


def card_proposto(pergunta: str = "O que é KWP2000?", resposta: str = "Um protocolo."):
    return estudo.CardProposto(pergunta=pergunta, resposta=resposta)


def conflito(ha: bool, a: str = "", b: str = "", explicacao: str = ""):
    return estudo.Contradicao(ha_conflito=ha, lado_a=a, lado_b=b, explicacao=explicacao)


def com_grafo() -> dict:
    """Um conceito ancorado no caderno, pronto para virar card."""
    nb = caderno()
    src = fonte(nb, TEXTO)
    conceito = knowledge.achar_ou_criar("KWP2000")
    knowledge.registrar_mencao(
        conceito["id"],
        notebook_id=nb,
        trecho="O protocolo KWP2000 roda sobre a linha K e usa 5 baudes na inicializacao.",
        referencia=TEXTO,
        source_id=src["id"],
    )
    return {"nb": nb, "src": src, "conceito": conceito}


# --------------------------------------------------------------- gerar cards


def test_gerar_card_usa_o_trecho_do_grafo_e_grava_o_lastro():
    dados = com_grafo()
    extrator = fake.extrai([card_proposto()])

    eventos = correr(estudo.gerar_cards(dados["nb"], modelo=extrator))
    final = eventos[-1]

    assert final["evento"] == "cards.done"
    assert final["criados"] == 1

    card = study.listar(dados["nb"])[0]
    assert card["front"] == "O que é KWP2000?"
    assert card["concept_id"] == dados["conceito"]["id"]
    assert card["source_id"] == dados["src"]["id"]
    assert "linha K" in card["excerpt"], "o card nasceu sem o lastro ao lado do verso"


def test_o_trecho_oferecido_ao_modelo_vem_do_grafo():
    """O modelo não inventa o material: ele recebe o que já foi ancorado."""
    dados = com_grafo()
    extrator = fake.extrai([card_proposto()])

    correr(estudo.gerar_cards(dados["nb"], modelo=extrator))

    enviado = "\n".join(str(m.content) for m in extrator.chamadas[0])
    assert "linha K" in enviado
    assert "KWP2000" in enviado
    assert "json" in enviado.lower(), "json_mode exige a palavra no prompt"
    assert '"pergunta"' in enviado, "o formato tem que ir no prompt (D046)"


def test_conceito_que_ja_tem_card_nao_ganha_outro():
    dados = com_grafo()
    correr(estudo.gerar_cards(dados["nb"], modelo=fake.extrai([card_proposto()])))
    assert len(study.listar(dados["nb"])) == 1

    eventos = correr(estudo.gerar_cards(dados["nb"], modelo=fake.extrai([card_proposto("Outra?")])))
    final = eventos[-1]

    assert final["criados"] == 0
    assert len(study.listar(dados["nb"])) == 1, "duplicou o card"

def test_a_lacuna_vem_primeiro_na_fila():
    """Conceito nomeado e não desenvolvido é onde o card mais serve."""
    dados = com_grafo()

    # um conceito DESENVOLVIDO: aparece e tem ligação afirmada
    desenvolvido = knowledge.achar_ou_criar("ISO 14230")
    knowledge.registrar_mencao(
        desenvolvido["id"],
        notebook_id=dados["nb"],
        trecho="O ISO 14230 descreve o KWP2000 como protocolo de aplicacao.",
        referencia=TEXTO,
        source_id=dados["src"]["id"],
    )
    knowledge.ligar_explicito(
        dados["conceito"]["id"],
        desenvolvido["id"],
        trecho="O ISO 14230 descreve o KWP2000 como protocolo de aplicacao.",
        referencia=TEXTO,
        quem="modelo",
    )

    # KWP2000 tem 1 menção e nenhuma ligação afirmada? Não: agora tem. Então a única
    # lacuna é... nenhuma. Vamos criar uma de verdade.
    conhecimento = knowledge.achar_ou_criar("Turbina")
    knowledge.registrar_mencao(
        conhecimento["id"],
        notebook_id=dados["nb"],
        trecho="O protocolo KWP2000 roda sobre a linha K e usa 5 baudes na inicializacao.",
        referencia=TEXTO,
        source_id=dados["src"]["id"],
    )

    lacunas = [c["name"] for c in knowledge.lacunas(dados["nb"])["nao_desenvolvidos"]]
    assert "Turbina" in lacunas
    assert "ISO 14230" not in lacunas, "conceito com ligação afirmada não é lacuna"

    extrator = fake.extrai([card_proposto(), card_proposto("E a turbina?")])
    eventos = correr(estudo.gerar_cards(dados["nb"], modelo=extrator))
    itens = [e for e in eventos if e["evento"] == "cards.item"]

    assert itens[0]["conceito"] == "Turbina", "a lacuna não foi a primeira da fila"


def test_sem_trecho_nao_ha_card():
    """Sem lastro não se cria card — nem se chama o modelo."""
    nb = caderno()
    fonte(nb, TEXTO)
    orfao = knowledge.achar_ou_criar("Conceito sem menção")

    eventos = correr(estudo.gerar_cards(nb, modelo=fake.extrai([card_proposto()])))

    assert eventos[-1]["criados"] == 0
    assert study.listar(nb) == []
    assert knowledge.get_conceito(orfao["id"]) is not None


def test_gerar_cards_sem_modelo_configurado_vira_evento_acionavel():
    dados = com_grafo()
    eventos = correr(estudo.gerar_cards(dados["nb"]))
    assert eventos[-1]["evento"] == "error"
    assert "não configurado" in eventos[-1]["message"]


# ----------------------------------------------------------- contradições


def test_conflito_com_os_dois_lados_de_fontes_diferentes_e_aceito():
    dados = com_grafo()
    outra = fonte(
        dados["nb"],
        "O KWP2000 roda sobre a linha K e usa 5 baudes na inicializacao, sempre acima de 10.400.",
        "Segunda",
    )
    # o mesmo conceito ancorado na segunda fonte
    knowledge.registrar_mencao(
        dados["conceito"]["id"],
        notebook_id=dados["nb"],
        trecho="O KWP2000 roda sobre a linha K e usa 5 baudes na inicializacao, sempre acima de 10.400.",
        referencia="O KWP2000 roda sobre a linha K e usa 5 baudes na inicializacao, sempre acima de 10.400.",
        source_id=outra["id"],
    )

    modelo = fake.extrai([
        conflito(
            True,
            "O protocolo KWP2000 roda sobre a linha K e usa 5 baudes na inicializacao.",
            "O KWP2000 roda sobre a linha K e usa 5 baudes na inicializacao, sempre acima de 10.400.",
            "uma diz 5 baudes, a outra diz acima de 10.400",
        )
    ])
    eventos = correr(estudo.detectar_contradicoes(dados["nb"], modelo=modelo))
    itens = [e for e in eventos if e["evento"] == "conflitos.item"]

    assert eventos[0] == {"evento": "conflitos.plano", "candidatos": 1}
    assert itens[0]["conflito"] is True
    assert itens[0]["lado_a"] and itens[0]["lado_b"]
    assert eventos[-1]["achadas"] == 1


def test_conflito_entre_trechos_da_MESMA_fonte_e_recusado():
    """Sem isto, o modelo "acha" um conflito dentro do mesmo documento e ele entra."""
    dados = com_grafo()
    modelo = fake.extrai([
        conflito(
            True,
            "O protocolo KWP2000 roda sobre a linha K e usa 5 baudes na inicializacao.",
            "O protocolo KWP2000 roda sobre a linha K e usa 5 baudes na inicializacao.",
        )
    ])

    # uma segunda fonte, para o conceito ser candidato à comparação
    outra = fonte(dados["nb"], "Material diferente sobre o ISO 14230 e o KWP2000.", "Segunda")
    knowledge.registrar_mencao(
        dados["conceito"]["id"],
        notebook_id=dados["nb"],
        trecho="Material diferente sobre o ISO 14230 e o KWP2000.",
        referencia="Material diferente sobre o ISO 14230 e o KWP2000.",
        source_id=outra["id"],
    )

    eventos = correr(estudo.detectar_contradicoes(dados["nb"], modelo=modelo))
    itens = [e for e in eventos if e["evento"] == "conflitos.item"]

    assert itens[0]["conflito"] is False
    assert "mesma fonte" in itens[0]["motivo"]


def test_conflito_com_trecho_inventado_e_recusado():
    dados = com_grafo()
    outra = fonte(dados["nb"], "Material diferente sobre o ISO 14230 e o KWP2000.", "Segunda")
    knowledge.registrar_mencao(
        dados["conceito"]["id"],
        notebook_id=dados["nb"],
        trecho="Material diferente sobre o ISO 14230 e o KWP2000.",
        referencia="Material diferente sobre o ISO 14230 e o KWP2000.",
        source_id=outra["id"],
    )
    modelo = fake.extrai([
        conflito(
            True,
            "O KWP2000 foi descontinuado em 2015 pela Bosch.",  # não está em fonte nenhuma
            "Material diferente sobre o ISO 14230 e o KWP2000.",
        )
    ])

    eventos = correr(estudo.detectar_contradicoes(dados["nb"], modelo=modelo))
    itens = [e for e in eventos if e["evento"] == "conflitos.item"]

    assert itens[0]["conflito"] is False
    assert "não existe na fonte" in itens[0]["motivo"]


def test_sem_conflito_e_resposta_normal_e_nao_entra():
    dados = com_grafo()
    outra = fonte(dados["nb"], "Outro material sobre KWP2000 e ISO 14230.", "Segunda")
    knowledge.registrar_mencao(
        dados["conceito"]["id"],
        notebook_id=dados["nb"],
        trecho="Outro material sobre KWP2000 e ISO 14230.",
        referencia="Outro material sobre KWP2000 e ISO 14230.",
        source_id=outra["id"],
    )

    eventos = correr(
        estudo.detectar_contradicoes(dados["nb"], modelo=fake.extrai([conflito(False)]))
    )
    itens = [e for e in eventos if e["evento"] == "conflitos.item"]

    assert itens[0]["conflito"] is False
    assert itens[0]["motivo"] == "sem conflito"
    assert eventos[-1]["achadas"] == 0


def test_conceito_em_uma_fonte_so_nao_e_candidato():
    """Só vale comparar onde há o que comparar."""
    com_grafo()
    dados = com_grafo()
    eventos = correr(estudo.detectar_contradicoes(dados["nb"], modelo=fake.extrai([])))
    assert eventos[0] == {"evento": "conflitos.plano", "candidatos": 0}
    assert eventos[-1]["examinados"] == 0


def test_conferir_lados_recusa_lado_unico():
    lados = [{"fonte": "A", "trecho": "o protocolo roda sobre a linha K"}, {"fonte": "B", "trecho": "material diferente"}]
    vale, motivo = estudo.conferir_lados(
        conflito(True, "o protocolo roda sobre a linha K", "trecho que nao existe em lugar nenhum"), lados
    )
    assert vale is False
    assert "não existe" in motivo
