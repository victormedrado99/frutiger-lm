"""Testes da oficina (F5): o artefato construído fora do turno que o pediu.

O que estes testes protegem, e por que cada um existe:

1. **A ferramenta do agente NÃO espera o documento.** É o D028 inteiro: se ela
   construísse o documento dentro de si, a tela ficaria parada, o texto não teria como
   ser transmitido (ferramenta não emite delta) e o agente reformataria o resultado por
   cima. O teste prova o "volta antes" — e prova que o documento sai do mesmo jeito.
2. **O run vive FORA de quem pediu.** Depois de pronto, `acompanhar` entrega o
   histórico completo para quem chega atrasado. Sem isso, o painel que descobre uma
   compilação nascida no chat abriria uma caixa vazia.
3. **Um caderno, uma compilação.** Dois pedidos enquanto uma está em curso
   acompanham a mesma — e não pagam duas chamadas de modelo.
4. **Ele é do caderno.** Compilar caderno inexistente é recusado, e a lista de runs
   não mistura cadernos.
"""

from __future__ import annotations

import asyncio
import json

from frutiger_lm import db, ingest, knowledge
from frutiger_lm.engine import agent, artefato, checkpoint, fake, llm, oficina
from frutiger_lm.engine.tools.artefatos import ferramentas_de_artefatos

FRASE_1 = "O protocolo KWP2000 roda sobre a linha K e usa 5 baudes na inicializacao."
FRASE_2 = "O ISO 14230 descreve o KWP2000 como protocolo de aplicacao da linha K."
FRASE_3 = "Na linha K, o KWP2000 troca mensagens curtas com a central eletronica."
FRASE_4 = "O ISO 14230 define dois formatos de mensagem para o KWP2000."
# Quatro frases, e não duas, por um motivo prático: o corte dos "principais" (2+
# menções, D054) esconde conceito citado uma vez só — e `registrar_mencao` deduplica
# menção idêntica. Para um conceito ter duas menções são precisos dois trechos
# diferentes. Um caderno sem conceito "principal" não gera documento narrativo, e o
# teste passaria a provar outra coisa sem avisar.
TEXTO = "\n\n".join([FRASE_1, FRASE_2, FRASE_3, FRASE_4])


def caderno(titulo: str = "Caderno") -> str:
    return db.create_notebook(titulo)["id"]


def fonte(notebook_id: str, texto: str = TEXTO, titulo: str = "Fonte") -> dict:
    return asyncio.run(ingest.add_source(notebook_id, kind="text", text=texto, title=titulo))


def com_grafo() -> dict:
    """Um caderno com dois conceitos DO material (2 menções cada) e uma ligação afirmada."""
    nb = caderno()
    src = fonte(nb)
    kwp = knowledge.achar_ou_criar("KWP2000")
    iso = knowledge.achar_ou_criar("ISO 14230")
    for conceito, trecho in ((kwp, FRASE_1), (kwp, FRASE_3), (iso, FRASE_2), (iso, FRASE_4)):
        knowledge.registrar_mencao(
            conceito["id"], notebook_id=nb, trecho=trecho, referencia=TEXTO, source_id=src["id"]
        )
    knowledge.ligar_explicito(kwp["id"], iso["id"], trecho=FRASE_2, referencia=TEXTO, quem="modelo")
    return {"nb": nb, "src": src}


def narrativa(resumo: str = "O material trata de KWP2000.") -> artefato.Narrativa:
    return artefato.Narrativa(resumo=resumo, desenvolvimento="KWP2000 se liga a ISO 14230.")


def extrator(texto: str = "O material trata de KWP2000.", pausa: float = 0.0):
    """O fake com `pausa` simula a demora da chamada real — sem ela, a construção
    inteira termina num passo só do laço e não há como observar quem NÃO esperou."""
    return fake.extrai([narrativa(texto)], pausa=pausa)


def id_do_run(texto: str) -> str:
    """O id que a ferramenta devolve no texto — é o contrato com a tela."""
    for pedaco in texto.replace("(", " ").replace(")", " ").split():
        if pedaco.startswith("run_"):
            return pedaco.rstrip(".,")
    raise AssertionError(f"a ferramenta não devolveu um id de run: {texto!r}")


# --------------------------------------------------------------------------- #
# A ferramenta dispara e sai de cena (D028)
# --------------------------------------------------------------------------- #


def test_a_ferramenta_dispara_e_volta_antes_de_o_documento_ficar_pronto(monkeypatch):
    """O coração do D028: quem chama recebe um id, e não o documento."""
    dados = com_grafo()
    monkeypatch.setattr(llm, "atual", lambda: extrator(pausa=0.05))
    ferramenta = ferramentas_de_artefatos(dados["nb"])[0]

    async def cenario() -> tuple[str, str]:
        resposta = await ferramenta.ainvoke({})
        run_id = id_do_run(resposta)
        # A ferramenta já voltou e o documento NÃO está pronto: é exatamente isto que
        # evita a tela parada e o texto reformatado por cima.
        if oficina.oficina.obter(run_id).estado != "rodando":
            raise AssertionError("a ferramenta esperou o documento — isso é a aninhagem que o D028 proíbe")
        await oficina.oficina.esperar(run_id)
        return resposta, run_id

    resposta, run_id = asyncio.run(cenario())

    assert "Compilação iniciada" in resposta
    assert "não repita" in resposta.lower(), "a instrução de não repetir o documento vai para o modelo"
    run = oficina.oficina.obter(run_id)
    assert run.estado == "pronto"
    assert run.origem == "agente"
    assert run.output_id is not None

    saida = db.get_output(run.output_id)
    assert saida is not None
    assert "Conceitos do material" in saida["content_md"]
    assert "linha K" in saida["content_md"], "o trecho literal do grafo está no documento"


def test_o_agente_chama_a_ferramenta_e_nao_repete_o_documento(monkeypatch):
    """No laço de verdade: o agente dispara, diz que começou, e a resposta fica curta."""
    dados = com_grafo()
    monkeypatch.setattr(llm, "atual", lambda: extrator())
    modelo = fake.com_ferramenta("compilar_documento", {}, "Pronto, compilei o documento.")

    async def cenario() -> tuple[str, list[str], str]:
        async with checkpoint.aberto() as saver:
            agente = agent.montar(dados["nb"], modelo=modelo, checkpointer=saver)
            config = checkpoint.config(dados["nb"])
            resposta = await agent.responder(agente, config, "compila o documento deste caderno")
            estado = await agente.aget_state(config)
            tipos = [type(m).__name__ for m in estado.values["messages"]]

            runs = oficina.oficina.ativos(dados["nb"])
            await oficina.oficina.esperar(runs[0]["id"])
            return resposta, tipos, [r["estado"] for r in oficina.oficina.ativos(dados["nb"])]

    resposta, tipos, estados = asyncio.run(cenario())

    assert resposta == "Pronto, compilei o documento.", "o documento entrou na resposta"
    assert "ToolMessage" in tipos, "a ferramenta não foi chamada"
    assert "Conceitos do material" not in resposta, "o agente repetiu o documento"
    assert estados == ["pronto"], "o documento não terminou de ser construído"
    assert len(db.list_outputs(dados["nb"])) == 1


def test_o_run_existe_fora_de_quem_pediu_e_entrega_o_historico_a_quem_chega_atrasado():
    """Chegar depois não pode dar caixa vazia: o histórico vem antes do ao vivo."""
    dados = com_grafo()

    async def cenario() -> list[dict]:
        run = oficina.oficina.iniciar(dados["nb"], origem="botao", modelo=extrator())
        await oficina.oficina.esperar(run.id)
        # Ninguém estava escutando quando o run rodou. Agora alguém chega.
        return [item async for item in oficina.oficina.acompanhar(run.id)]

    eventos = asyncio.run(cenario())
    nomes = [item["evento"] for item in eventos]

    assert nomes[0] == "compilando.passo"
    assert "output.completed" in nomes
    assert nomes[-1] == "done"
    assert "Conceitos do material" in eventos[nomes.index("output.completed")]["dados"]["content_md"]
    passos = [item["dados"]["mensagem"] for item in eventos if item["evento"] == "compilando.passo"]
    assert passos, "o acompanhamento não trouxe nenhum passo"
    assert all(p for p in passos), "passo sem mensagem não informa nada"


def test_acompanhar_run_inexistente_e_erro_de_quem_pede():
    """A oficina não inventa um run que não existe (a rota traduz em 404)."""

    async def cenario() -> None:
        async for _ in oficina.oficina.acompanhar("run_fantasma"):
            pass

    try:
        asyncio.run(cenario())
    except KeyError:
        pass
    else:
        raise AssertionError("deveria ter recusado um run inexistente")


# --------------------------------------------------------------------------- #
# Um caderno, uma compilação
# --------------------------------------------------------------------------- #


def test_dois_pedidos_seguidos_acompanham_a_MESMA_compilacao():
    """O segundo clique não paga uma segunda chamada de modelo."""
    dados = com_grafo()
    extrator_unico = extrator()

    async def cenario() -> tuple[str, str]:
        primeiro = oficina.oficina.iniciar(dados["nb"], modelo=extrator_unico)
        segundo = oficina.oficina.iniciar(dados["nb"], modelo=extrator_unico)
        await oficina.oficina.esperar(primeiro.id)
        return primeiro.id, segundo.id

    primeiro, segundo = asyncio.run(cenario())

    assert primeiro == segundo, "o segundo pedido abriu uma compilação nova"
    assert len(db.list_outputs(dados["nb"])) == 1
    assert len(extrator_unico.chamadas) == 1, "o modelo foi chamado duas vezes"


def test_a_ferramenta_avisa_quando_ja_havia_compilacao_em_curso():
    dados = com_grafo()

    async def cenario() -> str:
        oficina.oficina.iniciar(dados["nb"], modelo=extrator(pausa=0.05))
        return await ferramentas_de_artefatos(dados["nb"])[0].ainvoke({})

    resposta = asyncio.run(cenario())

    assert "Já havia uma compilação em andamento" in resposta
    assert "não disparei outra" in resposta


# --------------------------------------------------------------------------- #
# Ele é DO caderno
# --------------------------------------------------------------------------- #


def test_compilar_caderno_inexistente_e_recusado():
    try:
        oficina.oficina.iniciar("nb_fantasma")
    except ValueError as exc:
        assert "nb_fantasma" in str(exc)
    else:
        raise AssertionError("deveria ter recusado")


def test_a_ferramenta_responde_texto_quando_o_caderno_sumiu():
    """Erro de uso vira texto de retorno, nunca exceção (regra do catálogo)."""

    async def cenario() -> str:
        ferramenta = ferramentas_de_artefatos("nb_fantasma")[0]
        return await ferramenta.ainvoke({})

    assert "não encontrado" in asyncio.run(cenario())


def test_a_lista_de_runs_nao_mistura_cadernos():
    a = com_grafo()["nb"]
    b = com_grafo()["nb"]

    async def cenario() -> None:
        oficina.oficina.iniciar(a, modelo=extrator())
        await asyncio.sleep(0)

    asyncio.run(cenario())

    assert [r["notebook_id"] for r in oficina.oficina.ativos(a)] == [a]
    assert oficina.oficina.ativos(b) == []


# --------------------------------------------------------------------------- #
# As rotas
# --------------------------------------------------------------------------- #


def test_disparar_e_acompanhar_pelas_rotas(cliente, monkeypatch):
    """O contrato da tela: o POST devolve o id e o GET transmite o run inteiro."""
    dados = com_grafo()
    monkeypatch.setattr(llm, "atual", lambda: extrator("O material trata de KWP2000."))

    disparo = cliente.post(f"/api/notebooks/{dados['nb']}/compilar")

    assert disparo.status_code == 200
    run = disparo.json()
    assert run["id"].startswith("run_")
    assert run["notebook_id"] == dados["nb"]
    assert run["origem"] == "botao"

    stream = cliente.get(f"/api/artefatos/{run['id']}")
    assert stream.status_code == 200
    corpo = stream.text
    assert "event: compilando.passo" in corpo
    assert "event: output.completed" in corpo
    assert corpo.index("event: compilando.passo") < corpo.index("event: output.completed")
    assert "event: done" in corpo, "o stream precisa fechar o run"
    assert json.loads(corpo.rstrip().split("data: ")[-1])["estado"] == "pronto"

    # o documento ficou gravado, e a lista de artefatos conta a história dele
    assert len(db.list_outputs(dados["nb"])) == 1
    lista = cliente.get(f"/api/artefatos?notebook_id={dados['nb']}").json()
    assert [r["id"] for r in lista] == [run["id"]]
    assert lista[0]["estado"] == "pronto"
    assert lista[0]["output_id"] is not None


def test_o_documento_compilado_pela_rota_e_imprimivel(cliente, monkeypatch):
    """A ponta que a pessoa usa: o output do run tem o documento, e ele tem folha de imprimir."""
    dados = com_grafo()
    monkeypatch.setattr(llm, "atual", lambda: extrator())

    run_id = cliente.post(f"/api/notebooks/{dados['nb']}/compilar").json()["id"]
    cliente.get(f"/api/artefatos/{run_id}")

    saida = db.list_outputs(dados["nb"])[0]
    assert cliente.get(f"/api/outputs/{saida['id']}").status_code == 200
    assert cliente.get(f"/imprimir/{saida['id']}").status_code == 200


def test_acompanhar_run_inexistente_e_404(cliente):
    assert cliente.get("/api/artefatos/run_fantasma").status_code == 404


def test_compilar_caderno_inexistente_e_404(cliente):
    assert cliente.post("/api/notebooks/nb_fantasma/compilar").status_code == 404


def test_o_disparo_sem_modelo_nao_gasta_chamada(cliente, monkeypatch):
    """`sem_modelo=true` monta só as seções de fato — e o run diz que terminou."""
    dados = com_grafo()
    extrator_espiao = extrator()
    monkeypatch.setattr(llm, "atual", lambda: extrator_espiao)

    run = cliente.post(f"/api/notebooks/{dados['nb']}/compilar?sem_modelo=true").json()
    corpo = cliente.get(f"/api/artefatos/{run['id']}").text

    assert extrator_espiao.chamadas == [], "gastou chamada de modelo com sem_modelo=true"
    assert "event: output.completed" in corpo
    contagem = json.loads(
        [linha for linha in corpo.splitlines() if '"contagem"' in linha][0][5:]
    )["contagem"]
    assert contagem["modelo"] == 0, "as duas seções de texto do modelo entraram sem modelo"
    assert contagem["grafo"] > 0, "as seções de grafo não entraram"
