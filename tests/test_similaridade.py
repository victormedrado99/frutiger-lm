"""Testes das arestas por similaridade (F6) e dos vetores.

O que estes testes protegem, e cada um por um motivo diferente:

1. **A aresta inferida só entra onde não há nada** (D063). Onde o material já afirma, ou
   onde os dois já apareceram juntos, uma ligação *que um modelo deduziu* não acrescenta
   informação — e no desenho competiria com a que tem lastro.
2. **A nota não é peso** (D064). `weight` é contagem e vive numa coluna de inteiro: a
   nota de similaridade perdida ali viraria 1, e com ela a única informação que a aresta
   carrega.
3. **O vetor tem procedência** (D062). Sem o modelo e o hash do texto gravados juntos, o
   app compararia espaços de vetores diferentes (número plausível e errado) ou usaria o
   vetor de um texto que não existe mais. E o cache é o que torna o botão clicável duas
   vezes sem culpa.
4. **Nada disso se disfarça de afirmação.** Uma ligação inferida apresentada como
   "afirmada pelo material" seria o pior defeito possível neste projeto: a pessoa
   confiaria nela como se tivesse lastro.
"""

from __future__ import annotations

import asyncio

from frutiger_lm import db, ingest, knowledge
from frutiger_lm.engine import agent, checkpoint, embed, fake, llm, oficina, similaridade
from frutiger_lm.engine.tools.grafo import ferramentas_de_grafo, ferramentas_de_similaridade

TEXTO = (
    "ALFA e um protocolo de diagnostico automotivo.\n\n"
    "BRAVO descreve o ALFA como protocolo de aplicacao.\n\n"
    "CHARLIE trata de motores eletricos.\n\n"
    "DELTA fala de motores eletricos e inversores."
)

# Os vetores ditam quem é parecido com quem — é o que permite testar a lógica sem
# fingir semântica. ALFA~BRAVO (0.999) e CHARLIE~DELTA (0.999); o resto é ortogonal.
VETORES = {
    "ALFA": [1.0, 0.0, 0.0],
    "BRAVO": [1.0, 0.03, 0.0],
    "CHARLIE": [0.0, 1.0, 0.0],
    "DELTA": [0.0, 1.0, 0.03],
}


def caderno(titulo: str = "Caderno") -> str:
    return db.create_notebook(titulo)["id"]


def fonte(notebook_id: str, texto: str = TEXTO, titulo: str = "Fonte") -> dict:
    return asyncio.run(ingest.add_source(notebook_id, kind="text", text=texto, title=titulo))


def conceito(nome: str, nb: str, trecho: str, fonte_dada: dict) -> dict:
    """Um conceito ancorado num trecho — sem âncora ele não entra no grafo."""
    dado = knowledge.achar_ou_criar(nome)
    knowledge.registrar_mencao(
        dado["id"], notebook_id=nb, trecho=trecho, referencia=TEXTO, source_id=fonte_dada["id"]
    )
    return dado


def com_quatro() -> dict:
    """Quatro conceitos: ALFA e BRAVO se parecem, CHARLIE e DELTA também."""
    nb = caderno()
    src = fonte(nb)
    alfa = conceito("ALFA", nb, "ALFA e um protocolo de diagnostico automotivo.", src)
    bravo = conceito("BRAVO", nb, "BRAVO descreve o ALFA como protocolo de aplicacao.", src)
    charlie = conceito("CHARLIE", nb, "CHARLIE trata de motores eletricos.", src)
    delta = conceito("DELTA", nb, "DELTA fala de motores eletricos e inversores.", src)
    return {"nb": nb, "alfa": alfa, "bravo": bravo, "charlie": charlie, "delta": delta}


def rodar(nb: str, *, model: str = "fake-embed", limiar: float | None = None, **kw) -> tuple:
    """Roda a ligação com o embedder falso e devolve (resultado, embedder)."""
    embedder = fake.embeda(VETORES, dim=3, model=model)
    resultado = asyncio.run(
        similaridade.ligar(
            nb,
            modelo=embedder,
            **({"limiar": limiar} if limiar is not None else {}),
            **kw,
        )
    )
    return resultado, embedder


def arestas(kind: str) -> list[dict]:
    with db.connect() as conn:
        return [
            dict(linha)
            for linha in conn.execute("SELECT * FROM edges WHERE kind = ? ORDER BY a_id", (kind,))
        ]


def par(a: dict, b: dict) -> tuple[str, str]:
    return tuple(sorted([a["id"], b["id"]]))  # type: ignore[return-value]


# --------------------------------------------------------------------------- #
# O que a ligação faz — e onde ela NÃO entra (D063)
# --------------------------------------------------------------------------- #


def test_liga_os_parecidos_que_o_material_nunca_ligou():
    dados = com_quatro()

    resultado, _ = rodar(dados["nb"])

    assert resultado.conceitos == 4
    assert resultado.calculados == 4, "os quatro conceitos foram embedados"
    assert resultado.arestas == 2, "ALFA~BRAVO e CHARLIE~DELTA"
    ligadas = {tuple(sorted([e["a_id"], e["b_id"]])) for e in arestas(knowledge.SIMILARIDADE)}
    assert ligadas == {par(dados["alfa"], dados["bravo"]), par(dados["charlie"], dados["delta"])}


def test_a_similaridade_nao_entra_onde_ja_ha_lastro():
    """Uma aresta inferida não disputa o desenho com a que o material sustenta."""
    dados = com_quatro()
    # ALFA e BRAVO aparecem no mesmo bloco: já têm co-ocorrência.
    knowledge.co_ocorrencia([dados["alfa"]["id"], dados["bravo"]["id"]])

    resultado, _ = rodar(dados["nb"])

    ligadas = {tuple(sorted([e["a_id"], e["b_id"]])) for e in arestas(knowledge.SIMILARIDADE)}
    assert par(dados["alfa"], dados["bravo"]) not in ligadas, (
        "criou aresta inferida sobre um par que já tinha co-ocorrência"
    )
    assert ligadas == {par(dados["charlie"], dados["delta"])}
    assert resultado.arestas == 1
    assert resultado.pares == 6, "os pares continuam sendo comparados — só não viram aresta"


def test_a_similaridade_nao_entra_sobre_aresta_afirmada():
    """A afirmada é a mais forte de todas: o material disse, e há trecho."""
    dados = com_quatro()
    knowledge.ligar_explicito(
        dados["alfa"]["id"],
        dados["bravo"]["id"],
        trecho="BRAVO descreve o ALFA como protocolo de aplicacao.",
        referencia=TEXTO,
        quem="teste",
    )

    _, _ = rodar(dados["nb"])

    ligadas = {tuple(sorted([e["a_id"], e["b_id"]])) for e in arestas(knowledge.SIMILARIDADE)}
    assert par(dados["alfa"], dados["bravo"]) not in ligadas


# --------------------------------------------------------------------------- #
# A nota e o peso (D064)
# --------------------------------------------------------------------------- #


def test_a_nota_vai_para_a_coluna_score_e_o_peso_fica_em_um():
    dados = com_quatro()

    rodar(dados["nb"])

    alfa_bravo = next(
        e for e in arestas(knowledge.SIMILARIDADE) if par(dados["alfa"], dados["bravo"]) ==
        tuple(sorted([e["a_id"], e["b_id"]]))
    )
    assert alfa_bravo["weight"] == 1, "peso é contagem, e aqui não há contagem"
    assert alfa_bravo["score"] > 0.99, f"a nota real ficou em {alfa_bravo['score']}"
    assert alfa_bravo["score"] != 1.0, "a nota não é arredondada para 1 (era o defeito do INTEGER)"
    assert "fake-embed" in alfa_bravo["provenance"], "a procedência diz qual modelo inferiu"


def test_o_limiar_deixa_de_fora_o_que_e_fraco():
    """Com limiar alto nada entra; com o limiar no chão, todos os pares entram."""
    dados = com_quatro()

    resultado, _ = rodar(dados["nb"], limiar=1.01)
    assert resultado.arestas == 0
    assert arestas(knowledge.SIMILARIDADE) == []

    # -1,01 é abaixo do cosseno mínimo possível (-1): assim o teste mede o LIMIAR, e não
    # a geometria dos vetores do fake (que são quase ortogonais e às vezes negativos).
    resultado, _ = rodar(dados["nb"], limiar=-1.01)
    assert resultado.arestas == 6, "todos os pares passam de um limiar no chão"
    assert len(arestas(knowledge.SIMILARIDADE)) == 6


def test_cosseno_e_o_que_o_nome_diz():
    assert similaridade.cosseno([1.0, 0.0], [1.0, 0.0]) == 1.0
    assert similaridade.cosseno([1.0, 0.0], [0.0, 1.0]) == 0.0
    assert similaridade.cosseno([1.0, 0.0], [1.0, 0.0, 0.0]) == 0.0, (
        "dimensões diferentes não são comparáveis — e não estoura"
    )
    assert similaridade.cosseno([0.0, 0.0], [1.0, 1.0]) == 0.0, "vetor nulo não tem direção"


# --------------------------------------------------------------------------- #
# O vetor tem procedência, e o cache (D062)
# --------------------------------------------------------------------------- #


def test_o_vetor_guarda_o_modelo_e_o_texto_que_o_produziram():
    dados = com_quatro()

    _, _ = rodar(dados["nb"], model="modelo-a")

    guardados = knowledge.vetores([dados["alfa"]["id"]])
    guardado = guardados[dados["alfa"]["id"]]
    assert guardado["model"] == "modelo-a"
    assert guardado["vetor"] == VETORES["ALFA"]
    revisado = similaridade.embed.texto_do_conceito(
        "ALFA",
        ["ALFA e um protocolo de diagnostico automotivo."],
    )
    assert guardado["texto_hash"] == embed.hash_do_texto(revisado), (
        "o hash não corresponde ao texto de onde o vetor saiu"
    )


def test_a_segunda_rodada_nao_gasta_chamada_nenhuma():
    """Clicar duas vezes é o que as pessoas fazem — e a segunda tem que ser de graça."""
    dados = com_quatro()

    _, primeiro = rodar(dados["nb"])
    assert sum(len(c) for c in primeiro.chamadas) == 4

    resultado, segundo = rodar(dados["nb"])

    assert segundo.chamadas == [], "chamou o provedor de novo sem o texto ter mudado"
    assert resultado.reusados == 4
    assert resultado.calculados == 0
    assert resultado.arestas == 2, "as arestas continuam as mesmas"


def test_trocar_de_modelo_recomputa_em_vez_de_comparar_espacos_diferentes():
    """Vetores de modelos diferentes não são comparáveis — o app não finge que são."""
    dados = com_quatro()
    rodar(dados["nb"], model="modelo-a")

    resultado, segundo = rodar(dados["nb"], model="modelo-b")

    assert segundo.chamadas != [], "reusou vetor de outro modelo"
    assert resultado.calculados == 4
    assert knowledge.vetores([dados["alfa"]["id"]])[dados["alfa"]["id"]]["model"] == "modelo-b"


def test_mudar_o_texto_do_conceito_recomputa_so_ele():
    """O hash é o que faz o vetor acompanhar o material, e não ficar para trás."""
    dados = com_quatro()
    rodar(dados["nb"])

    # Uma menção nova muda o texto do conceito (e o hash).
    knowledge.registrar_mencao(
        dados["charlie"]["id"],
        notebook_id=dados["nb"],
        trecho="CHARLIE trata de motores eletricos.",
        referencia=TEXTO,
        source_id=db.list_sources(dados["nb"])[0]["id"],
    )
    mencionados = knowledge.mencoes(dados["charlie"]["id"], limite=2, notebook_id=dados["nb"])
    assert len(mencionados) == 1, "a menção idêntica é deduplicada — o texto não mudou"

    # Com um trecho DIFERENTE, o texto muda e só esse conceito é recomputado.
    with db.connect() as conn:
        conn.execute(
            "UPDATE mentions SET excerpt = ? WHERE concept_id = ?",
            ("Motores eletricos aparecem em CHARLIE.", dados["charlie"]["id"]),
        )
    resultado, embedder = rodar(dados["nb"])

    assert resultado.calculados == 1, "recomputou mais do que o conceito cujo texto mudou"
    assert resultado.reusados == 3
    assert any("CHARLIE" in texto for chamada in embedder.chamadas for texto in chamada)


# --------------------------------------------------------------------------- #
# Os candidatos a mesclar (D066)
# --------------------------------------------------------------------------- #


def test_parecidos_demais_viram_candidatos_e_quase_iguais_não():
    """A suspeita convida a pessoa a olhar dois conceitos como candidatos a serem um só."""
    dados = com_quatro()

    resultado, _ = rodar(dados["nb"])

    # ALFA~BRAVO tem 0,9996: é suspeita. CHARLIE~DELTA também (0,9996).
    assert resultado.candidatos == 2
    candidatos = knowledge.parecidos(dados["nb"])
    assert len(candidatos) == 2
    assert candidatos[0]["score"] >= similaridade.LIMIAR_MESCLAR
    nomes = {frozenset([c["a_name"], c["b_name"]]) for c in candidatos}
    assert frozenset(["ALFA", "BRAVO"]) in nomes
    assert candidatos[0]["a_mentions"] >= 1, "a tela precisa das menções para a pessoa decidir"


def test_a_vizinhanca_traz_a_nota_da_inferida():
    """Sem a nota, a tela do conceito escreve "parecido 0%" — pior do que não escrever nada.

    O defeito apareceu na prova real, não no teste: o painel do conceito mostrava "parecido
    0%" para as duas ligações inferidas do SAE J1979, porque `vizinhanca()` lia peso e
    procedência da aresta e deixava a nota de fora. A nota é o único número que a pessoa
    pode ponderar numa ligação que nenhum trecho sustenta.
    """
    dados = com_quatro()
    rodar(dados["nb"])

    vizinhanca = knowledge.vizinhanca(dados["alfa"]["id"])

    inferidas = [v for v in vizinhanca["neighbors"] if v["kind"] == knowledge.SIMILARIDADE]
    assert inferidas, "ALFA tem a inferida com BRAVO"
    assert inferidas[0]["score"] > 0.9, "a nota vem com o valor real, não zerada"
    assert "inferid" in inferidas[0]["provenance"], "e a procedência diz que é inferência"


def test_a_suspeita_sobrevive_ao_lastro_que_impede_a_aresta():
    """O caso que a medição no material real expôs — e ele é o caso comum.

    No caderno de verdade, dos 48 pares acima de 0,80, **41 já tinham ligação** (D063):
    são justamente os que compartilham a mesma frase de origem, e é por isso que se
    parecem. Se a lista de suspeitas saísse das arestas de similaridade, ela ficaria
    VAZIA exatamente nos pares que mais importam. Por isso a suspeita tem tabela própria.
    """
    dados = com_quatro()
    knowledge.co_ocorrencia([dados["alfa"]["id"], dados["bravo"]["id"]])

    resultado, _ = rodar(dados["nb"])

    assert resultado.arestas == 1, "só CHARLIE~DELTA vira aresta: ALFA~BRAVO já tem lastro"
    assert resultado.candidatos == 2, "e as duas suspeitas ficam registradas mesmo assim"
    pares = knowledge.parecidos(dados["nb"])
    assert {frozenset([p["a_name"], p["b_name"]]) for p in pares} == {
        frozenset(["ALFA", "BRAVO"]),
        frozenset(["CHARLIE", "DELTA"]),
    }


def test_a_suspeita_nao_acumula_entre_rodadas():
    """Lista que só cresce vira lista de coisas que já não são verdade."""
    dados = com_quatro()
    rodar(dados["nb"])
    assert len(knowledge.parecidos(dados["nb"])) == 2

    # Uma rodada com limiar de suspeita inalcançável não deixa as antigas para trás.
    rodar(dados["nb"], limiar=1.01, limiar_mesclar=1.01)

    assert knowledge.parecidos(dados["nb"], limiar=0.5) == []


def test_o_candidato_nao_mistura_cadernos():
    """Ponte entre cadernos é a informação mais interessante do grafo, não duplicata."""
    a = com_quatro()
    b = caderno("Outro")
    src = fonte(b, "ALFA tambem aparece aqui, num outro caderno.", "Fonte B")
    conhecimento_b = conceito(
        "ALFA", b, "ALFA tambem aparece aqui, num outro caderno.", src
    )
    assert conhecimento_b["id"] == a["alfa"]["id"], "é o MESMO conceito, nos dois cadernos"

    rodar(a["nb"])

    assert all(c["a_id"] != c["b_id"] for c in knowledge.parecidos(a["nb"]))
    assert knowledge.parecidos(b) == [], "o caderno B não tem par próprio"


# --------------------------------------------------------------------------- #
# Nada se disfarça de afirmação
# --------------------------------------------------------------------------- #


def test_a_vizinhanca_separa_inferida_de_afirmada():
    """O defeito que quase foi entregue: a ferramenta dizia "afirmadas" para tudo."""
    dados = com_quatro()
    rodar(dados["nb"])
    ferramenta = {t.name: t for t in ferramentas_de_grafo()}["vizinhanca_do_conceito"]

    texto = ferramenta.invoke({"conceito": "ALFA"})

    assert "Parecidos por similaridade" in texto
    assert "inferido pelo app" in texto
    assert "sem trecho que sustente" in texto
    assert "Ligações afirmadas pelo material" not in texto, (
        "a similaridade apareceu como afirmação do material"
    )


def test_o_grafo_do_desenho_marca_a_aresta_inferida_com_a_nota():
    dados = com_quatro()
    rodar(dados["nb"])

    # Sem o corte dos "principais": cada conceito do teste tem UMA menção, e o corte da
    # D054 (2+ menções) deixaria o grafo vazio — o teste passaria a não provar nada.
    grafo = knowledge.grafo(notebook_id=dados["nb"])

    inferidas = [e for e in grafo["edges"] if e["kind"] == knowledge.SIMILARIDADE]
    assert len(inferidas) == 2
    assert all(e["score"] > 0.99 for e in inferidas)

    sem = knowledge.grafo(
        notebook_id=dados["nb"],
        tipos=[knowledge.CO_OCORRENCIA, knowledge.EXPLICITA],
    )
    assert not [e for e in sem["edges"] if e["kind"] == knowledge.SIMILARIDADE]


# --------------------------------------------------------------------------- #
# Sem embedding configurado, o app diz o que falta (e a ferramenta não inventa)
# --------------------------------------------------------------------------- #


def test_sem_modelo_de_embedding_a_ferramenta_avisa_e_nao_liga_nada():
    dados = com_quatro()
    assert not embed.configurado(), "o teste começa sem embedding configurado"
    ferramenta = ferramentas_de_similaridade(dados["nb"])[0]

    resposta = asyncio.run(ferramenta.ainvoke({}))

    assert "Modelo de embedding não configurado" in resposta
    assert "não invente a ligação" in resposta.lower()
    assert oficina.oficina.ativos(dados["nb"], trabalho=oficina.SIMILARIDADE) == []


def test_o_trabalho_sem_embedding_termina_em_erro_com_a_mensagem_certa(monkeypatch):
    """A falha de configuração é do run, e ela aparece na tela — não em silêncio."""

    def sem_modelo():
        raise embed.EmbeddingNaoConfigurado("Modelo de embedding não configurado: falta modelo.")

    monkeypatch.setattr(embed, "atual", sem_modelo)
    dados = com_quatro()

    async def cenario() -> list[dict]:
        run = oficina.oficina.iniciar(dados["nb"], trabalho=oficina.SIMILARIDADE)
        await oficina.oficina.esperar(run.id)
        return [item async for item in oficina.oficina.acompanhar(run.id)]

    eventos = asyncio.run(cenario())
    erro = next(item["dados"] for item in eventos if item["evento"] == "error")

    assert "não configurado" in erro["message"]
    assert eventos[-1]["dados"]["estado"] == "erro"
    assert eventos[-1]["evento"] == "done"


# --------------------------------------------------------------------------- #
# A ferramenta dispara e sai de cena (D028/D065), e as rotas
# --------------------------------------------------------------------------- #


def test_a_ferramenta_dispara_e_devolve_o_id(monkeypatch):
    dados = com_quatro()
    monkeypatch.setattr(embed, "atual", lambda: fake.embeda(VETORES, dim=3, pausa=0.05))
    ferramenta = ferramentas_de_similaridade(dados["nb"])[0]

    async def cenario() -> tuple[str, list[dict]]:
        resposta = await ferramenta.ainvoke({})
        ativos = oficina.oficina.ativos(dados["nb"], trabalho=oficina.SIMILARIDADE)
        await oficina.oficina.esperar(ativos[0]["id"])
        return resposta, ativos

    resposta, ativos = asyncio.run(cenario())

    assert "iniciada" in resposta
    assert "Não repita o resultado" in resposta
    assert ativos[0]["estado"] == "rodando", "a ferramenta esperou o trabalho terminar"
    assert ativos[0]["origem"] == "agente"
    assert len(arestas(knowledge.SIMILARIDADE)) == 2


def test_o_agente_dispara_a_ligacao_pelo_laco(monkeypatch):
    """No laço de verdade: o agente chama a ferramenta e responde curto."""
    dados = com_quatro()
    monkeypatch.setattr(embed, "atual", lambda: fake.embeda(VETORES, dim=3))
    modelo = fake.com_ferramenta("ligar_por_similaridade", {}, "Liguei os parecidos.")

    async def cenario() -> tuple[str, list[str]]:
        async with checkpoint.aberto() as saver:
            agente = agent.montar(dados["nb"], modelo=modelo, checkpointer=saver)
            resposta = await agente.ainvoke(
                {"messages": [{"role": "user", "content": "liga os conceitos parecidos"}]},
                checkpoint.config(dados["nb"]),
            )
            ativos = oficina.oficina.ativos(dados["nb"], trabalho=oficina.SIMILARIDADE)
            await oficina.oficina.esperar(ativos[0]["id"])
            return resposta["messages"][-1].content, [r["estado"] for r in ativos]

    resposta, estados = asyncio.run(cenario())

    assert resposta == "Liguei os parecidos."
    assert estados == ["pronto"]
    assert len(arestas(knowledge.SIMILARIDADE)) == 2


def test_ligar_pelas_rotas(cliente, monkeypatch):
    """O contrato da tela: POST dispara, GET transmite o trabalho inteiro."""
    dados = com_quatro()
    monkeypatch.setattr(embed, "atual", lambda: fake.embeda(VETORES, dim=3))

    disparo = cliente.post(f"/api/notebooks/{dados['nb']}/similaridade")

    assert disparo.status_code == 200
    run = disparo.json()
    assert run["trabalho"] == oficina.SIMILARIDADE
    assert run["estado"] == "rodando"

    corpo = cliente.get(f"/api/trabalhos/{run['id']}").text
    assert "event: trabalho.passo" in corpo
    assert "event: trabalho.pronto" in corpo
    pronto = next(
        linha for linha in corpo.splitlines() if "similaridade" in linha and "resultado" in linha
    )
    assert '"arestas": 2' in pronto
    assert '"candidatos": 2' in pronto
    assert corpo.index("event: trabalho.passo") < corpo.index("event: trabalho.pronto")

    lista = cliente.get(f"/api/trabalhos?notebook_id={dados['nb']}").json()
    assert [r["id"] for r in lista] == [run["id"]]
    assert lista[0]["resultado"]["calculados"] == 4


def test_a_rota_do_grafo_pode_desligar_as_inferidas(cliente, monkeypatch):
    """O interruptor que informa sem omitir: a tela diz quantas linhas tirou."""
    dados = com_quatro()
    monkeypatch.setattr(embed, "atual", lambda: fake.embeda(VETORES, dim=3))
    cliente.post(f"/api/notebooks/{dados['nb']}/similaridade")
    run = cliente.get(f"/api/trabalhos?notebook_id={dados['nb']}").json()[0]
    cliente.get(f"/api/trabalhos/{run['id']}")  # consome o stream até o fim

    com = cliente.get(f"/api/grafo?notebook_id={dados['nb']}").json()
    sem = cliente.get(f"/api/grafo?notebook_id={dados['nb']}&sem_similaridade=true").json()

    assert com["similaridades"] == 2
    assert not [e for e in sem["edges"] if e["kind"] == knowledge.SIMILARIDADE]
    assert com["vetores"] == 4, "os vetores ficam guardados depois da rodada"


def test_a_similaridade_de_caderno_inexistente_e_404(cliente):
    assert cliente.post("/api/notebooks/nb_fantasma/similaridade").status_code == 404


def test_o_teste_de_embedding_sem_config_avisa_o_que_falta(cliente):
    """O botão de testar separa "salvei" de "funciona" — e aqui ele diz o que falta."""
    resposta = cliente.post("/api/settings/embed/test")

    assert resposta.status_code == 400
    assert "não configurado" in resposta.json()["detail"]


def test_a_config_do_embedding_vai_e_volta_sem_vazar_a_chave(cliente):
    """Mesma disciplina da chave do chat (D030): o navegador nunca recebe o valor."""
    resposta = cliente.post(
        "/api/settings/model",
        json={
            "base_url": "https://api.deepseek.com/v1",
            "model": "deepseek-v4-flash",
            "api_key": "sk-do-chat",
            "embed_base_url": "http://127.0.0.1:8080/v1",
            "embed_model": "nomic-embed-text-v1.5",
        },
    )

    assert resposta.status_code == 200
    corpo = resposta.json()
    assert corpo["embed_configured"] is True
    assert corpo["embed_model"] == "nomic-embed-text-v1.5"
    assert "sk-do-chat" not in resposta.text
    assert corpo["embed_has_key"] is False

    # Vazio dos dois lados é o pedido de tirar o embedding — e a chave do chat fica.
    limpo = cliente.post(
        "/api/settings/model",
        json={
            "base_url": "https://api.deepseek.com/v1",
            "model": "deepseek-v4-flash",
            "embed_base_url": "",
            "embed_model": "",
        },
    ).json()
    assert limpo["embed_configured"] is False
    assert limpo["configured"] is True, "tirar o embedding não pode derrubar o modelo do chat"
    assert llm.resolve().api_key == "sk-do-chat"


def test_config_de_embedding_pela_metade_e_recusada(cliente):
    """Endereço sem modelo é estado inutilizável — a mesma régua da D032."""
    resposta = cliente.post(
        "/api/settings/model",
        json={
            "base_url": "https://api.deepseek.com/v1",
            "model": "deepseek-v4-flash",
            "api_key": "sk",
            "embed_base_url": "http://127.0.0.1:8080/v1",
            "embed_model": "",
        },
    )

    assert resposta.status_code == 400
    assert "embeddings" in resposta.json()["detail"]
    assert "modelo" in resposta.json()["detail"]
