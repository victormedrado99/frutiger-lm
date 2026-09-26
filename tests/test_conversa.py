"""Testes do "virar conhecimento" (F3/D068) — a conclusão do chat que entra no grafo.

O que estes testes protegem:

1. **A âncora continua sendo literal.** A menção da conversa passa pela MESMA conferência
   das fontes: trecho que não existe no texto é descartado e contado. Sem isso, "virar
   conhecimento" seria a porta por onde o modelo entra no grafo sem lastro — o oposto do
   que o F3 inteiro existe para garantir.
2. **O que entra é o que o modelo disse, e o `message_id` é o certo.** O texto vem do
   checkpointer, não do navegador: o teste confere o id contra a mensagem real do estado.
3. **A origem é a conversa, e o grafo sabe disso.** `source_id` vazio, `thread_id` e
   `message_id` preenchidos, e a aresta afirmada que sai daí diz `conversa:` na procedência
   — um trecho do MODELO não pode passar por trecho de material.
4. **A mesma frase em duas conclusões são duas menções.** O `message_id` entra na
   deduplicação, senão a segunda conclusão sumiria e a contagem de menções (que decide o
   que é conceito do material, D054) ficaria errada.
"""

from __future__ import annotations

import asyncio

from frutiger_lm import db, ingest, knowledge
from frutiger_lm.engine import checkpoint, extracao, fake, llm


def caderno(titulo: str = "Caderno") -> str:
    return db.create_notebook(titulo)["id"]


def fonte(notebook_id: str, texto: str, titulo: str = "Fonte") -> dict:
    return asyncio.run(ingest.add_source(notebook_id, kind="text", text=texto, title=titulo))


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


CONCLUSAO = (
    "O KWP2000 roda sobre a linha K e o ISO 14230 o descreve. "
    "Na pratica voce vai precisar do conector de 16 pinos."
)


def virar(notebook_id: str, texto: str = CONCLUSAO, *, modelo, thread: str = "t1", msg: str = "m1"):
    return asyncio.run(
        extracao.extrair_conversa(
            notebook_id, texto, thread_id=thread, message_id=msg, modelo=modelo
        )
    )


# ---------------------------------------------------------------- o extrator


def test_a_conclusao_vira_mencao_ancorada_com_id_da_mensagem():
    nb = caderno()
    extrator = fake.extrai([
        extracao_de(
            ("KWP2000", "O KWP2000 roda sobre a linha K"),
            ("ISO 14230", "o ISO 14230 o descreve"),
        )
    ])

    resumo = virar(nb, modelo=extrator, thread="thread-7", msg="msg-42")

    assert sorted(resumo["conceitos"]) == ["ISO 14230", "KWP2000"]
    assert resumo["mencionadas"] == 2 and resumo["descartadas"] == 0

    conceito = knowledge.achar_ou_criar("KWP2000")
    mencoes = knowledge.mencoes(conceito["id"])
    assert len(mencoes) == 1
    mencao = mencoes[0]
    assert mencao["source_id"] is None, "a origem da conversa não é uma fonte"
    assert mencao["output_id"] is None
    assert mencao["thread_id"] == "thread-7"
    assert mencao["message_id"] == "msg-42"
    assert mencao["excerpt"] == "O KWP2000 roda sobre a linha K", "o trecho é literal"


def test_trecho_que_nao_esta_na_resposta_e_descartado():
    """O modelo não pode entrar no grafo sem lastro — nem quando o texto é dele mesmo."""
    nb = caderno()
    extrator = fake.extrai([
        extracao_de(
            ("KWP2000", "O KWP2000 roda sobre a linha K"),
            ("Protocolo inventado", "isso nao esta na resposta"),
        )
    ])

    resumo = virar(nb, modelo=extrator)

    assert resumo["mencionadas"] == 1
    assert resumo["descartadas"] == 1
    assert "Protocolo inventado" not in knowledge.vocabulario(), (
        "o conceito inventado não entrou no grafo — nem pendurado, sem âncora"
    )


def test_a_relacao_da_conversa_se_declara_como_da_conversa():
    """A procedência tem que dizer de onde a afirmação saiu: aqui, da conversa."""
    nb = caderno()
    extrator = fake.extrai([
        extracao_de(
            ("KWP2000", "O KWP2000 roda sobre a linha K"),
            ("ISO 14230", "o ISO 14230 o descreve"),
            relacoes=[("KWP2000", "ISO 14230", "o ISO 14230 o descreve")],
        )
    ])

    resumo = virar(nb, modelo=extrator)

    assert resumo["relacoes"] == 1
    vizinhos = knowledge.vizinhanca(knowledge.achar_ou_criar("KWP2000")["id"])["neighbors"]
    afirmadas = [v for v in vizinhos if v["kind"] == knowledge.EXPLICITA]
    assert len(afirmadas) == 1
    assert afirmadas[0]["provenance"].startswith("conversa: "), afirmadas[0]["provenance"]


def test_a_mesma_frase_em_duas_conclusoes_sao_duas_mencoes():
    """Duas respostas diferentes ditas pelo modelo = duas menções, não uma."""
    nb = caderno()
    extrator = fake.extrai([extracao_de(("KWP2000", "O KWP2000 roda sobre a linha K"))])

    virar(nb, modelo=extrator, msg="msg-1")
    virar(nb, modelo=extrator, msg="msg-2")

    conceito = knowledge.achar_ou_criar("KWP2000")
    mencoes = knowledge.mencoes(conceito["id"])
    assert len(mencoes) == 2
    assert {m["message_id"] for m in mencoes} == {"msg-1", "msg-2"}


def test_o_mesmo_trecho_na_mesma_conclusao_nao_duplica():
    nb = caderno()
    extrator = fake.extrai([extracao_de(("KWP2000", "O KWP2000 roda sobre a linha K"))])

    virar(nb, modelo=extrator, msg="msg-1")
    virar(nb, modelo=extrator, msg="msg-1")

    assert len(knowledge.mencoes(knowledge.achar_ou_criar("KWP2000")["id"])) == 1


def test_resposta_vazia_nao_chama_modelo_nem_cria_nada():
    nb = caderno()
    extrator = fake.extrai([])

    resumo = virar(nb, texto="   ", modelo=extrator)

    assert resumo == {"conceitos": [], "mencionadas": 0, "descartadas": 0, "relacoes": 0, "blocos": 0}
    assert extrator.chamadas == []
    assert knowledge.estatisticas()["conceitos"] == 0


# ---------------------------------------------------------------- a rota


def test_sem_conclusao_a_rota_recusa(cliente):
    """Antes de qualquer conversa não há o que guardar — e a mensagem diz isso."""
    nb = caderno()

    resp = cliente.post(f"/api/notebooks/{nb}/conhecimento")

    assert resp.status_code == 400
    assert "conclusão" in resp.json()["detail"]


def test_a_rota_guarda_a_conclusao_do_checkpointer(cliente, monkeypatch):
    """A prova de ponta a ponta — e a prova de que o texto vem da CONVERSA, não do corpo.

    O pedido vai sem corpo nenhum; o que entra no grafo é a resposta que está no
    checkpointer, com o `message_id` exato daquela mensagem.
    """
    nb = caderno("Conversa")
    fonte(nb, "O codigo do equipamento e BRAVO-7741.", "Manual")
    monkeypatch.setattr(
        llm,
        "atual",
        lambda: fake.com_ferramenta("buscar_nas_fontes", {"termo": "BRAVO-7741"}, "O KWP2000 roda sobre a linha K."),
    )
    cliente.post(f"/api/notebooks/{nb}/chat", json={"input": "qual e o codigo?"})

    # A extração é outra chamada de modelo: outro fake, como em produção (o mesmo
    # provedor, outro pedido).
    monkeypatch.setattr(
        llm,
        "atual",
        lambda: fake.extrai([extracao_de(("KWP2000", "O KWP2000 roda sobre a linha K"))]),
    )

    resp = cliente.post(f"/api/notebooks/{nb}/conhecimento")

    assert resp.status_code == 200, resp.text
    dados = resp.json()
    assert dados["conceitos"] == ["KWP2000"]

    mencoes = knowledge.mencoes(knowledge.achar_ou_criar("KWP2000")["id"])
    assert len(mencoes) == 1
    mencao = mencoes[0]
    assert mencao["thread_id"] == checkpoint.thread_id(nb)
    assert mencao["message_id"], "o id da mensagem do assistente tem que estar gravado"
    assert mencao["source_id"] is None and mencao["output_id"] is None


def test_a_rota_ignora_texto_vindo_do_navegador(cliente, monkeypatch):
    """O corpo do pedido não tem como escolher o que vira conhecimento (D068)."""
    nb = caderno("Conversa")
    monkeypatch.setattr(
        llm, "atual", lambda: fake.responde("O KWP2000 roda sobre a linha K.")
    )
    cliente.post(f"/api/notebooks/{nb}/chat", json={"input": "fala do protocolo"})

    espiao = fake.extrai([extracao_de(("KWP2000", "O KWP2000 roda sobre a linha K"))])
    monkeypatch.setattr(llm, "atual", lambda: espiao)

    resp = cliente.post(
        f"/api/notebooks/{nb}/conhecimento",
        json={"texto": "ISTO NAO E A CONCLUSAO", "notebook_id": "outro"},
    )

    assert resp.status_code == 200
    # O bloco que foi ao extrator é a resposta do chat, e não o que o navegador mandou.
    assert "ISTO NAO E A CONCLUSAO" not in espiao.chamadas[0][-1].content
    assert "O KWP2000 roda sobre a linha K" in espiao.chamadas[0][-1].content
