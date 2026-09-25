"""Testes da loja do grafo (F3).

O que estes testes protegem, em ordem de importância:

1. **A ancoragem.** Menção com trecho que não existe no material não é gravada. Se
   este teste cair, o grafo passa a ser um desenho plausível de coisas que ninguém
   disse — e nada na tela denuncia.
2. **A aresta explícita exige trecho.** Mesma razão.
3. **Fusão não perde prova.** Menção migra numa mesclagem; nunca é apagada.
4. **Aresta não é espelhada.** `(A,B)` e `(B,A)` têm que ser a mesma aresta, senão o
   peso da co-ocorrência fica pela metade e o desenho fica com linhas duplas.
"""

from __future__ import annotations

import asyncio

from frutiger_lm import db, ingest, knowledge


def caderno(titulo: str = "Caderno") -> str:
    return db.create_notebook(titulo)["id"]


def fonte(notebook_id: str, texto: str, titulo: str = "Fonte") -> dict:
    return asyncio.run(
        ingest.add_source(notebook_id, kind="text", text=texto, title=titulo)
    )


TEXTO = "O protocolo KWP2000 roda sobre a linha K. O OBD-II exige o conector de 16 pinos."


# ------------------------------------------------------------- normalização


def test_as_variantes_triviais_caem_na_mesma_chave():
    assert knowledge.normalizar("OBD-II") == knowledge.normalizar("OBD II")
    assert knowledge.normalizar("OBD-II") == knowledge.normalizar("  obd   ii  ")
    assert knowledge.normalizar("Barramento CAN") == "barramento can"


def test_acento_e_pontuacao_nao_separam_o_mesmo_conceito():
    assert knowledge.normalizar("Análise!") == knowledge.normalizar("analise")
    assert knowledge.normalizar("Nó-canônico") == "no canonico"


def test_obd2_NAO_e_o_mesmo_que_obd_ii_e_isso_e_assumido():
    """O limite da normalização, registrado como teste.

    Não forçamos equivalência entre dígito e número romano: isso quebraria
    `ISO 14230-4` e outros nomes que legitimamente diferem. Quem resolve este caso
    é o vocabulário entregue ao extrator (D041) e a mesclagem manual na interface.
    """
    assert knowledge.normalizar("OBD2") != knowledge.normalizar("OBD-II")


def test_achar_ou_criar_e_idempotente_e_guarda_a_variante_como_alias():
    a = knowledge.achar_ou_criar("OBD-II")
    b = knowledge.achar_ou_criar("OBD II")

    assert a["id"] == b["id"], "criou dois conceitos para o mesmo nome"
    assert "OBD II" in b["aliases"], "a variante gráfica não foi registrada"
    assert b["name"] == "OBD-II", "o nome de exibição mudou sozinho"


def test_nome_vazio_e_recusado():
    for ruim in ("", "   ", "!!!"):
        try:
            knowledge.achar_ou_criar(ruim)
        except ValueError:
            continue
        raise AssertionError(f"aceitou nome inutilizável: {ruim!r}")


# ----------------------------------------------------------------- ancoragem


def test_trecho_existe_tolera_espaco_e_caixa():
    assert knowledge.trecho_existe("O protocolo  KWP2000", TEXTO)
    assert knowledge.trecho_existe("o protocolo kwp2000", TEXTO)
    assert knowledge.trecho_existe("O protocolo\nKWP2000", TEXTO)


def test_a_mencao_com_trecho_inventado_NAO_e_gravada():
    """O teste mais importante da fase.

    O modelo devolve um trecho bonito que não está no material. A menção é
    recusada — e a recusa é informada, para poder ser contada.
    """
    nb = caderno()
    src = fonte(nb, TEXTO)
    conceito = knowledge.achar_ou_criar("KWP2000")

    gravou = knowledge.registrar_mencao(
        conceito["id"],
        notebook_id=nb,
        trecho="O KWP2000 foi criado pela Bosch em 1998 para carros elétricos.",
        referencia=TEXTO,
        source_id=src["id"],
    )

    assert gravou is False
    assert knowledge.mencoes(conceito["id"]) == [], "gravou um trecho que não existe"
    assert knowledge.estatisticas()["mencoes"] == 0


def test_a_mencao_com_trecho_real_e_gravada_com_a_origem():
    nb = caderno()
    src = fonte(nb, TEXTO)
    conceito = knowledge.achar_ou_criar("KWP2000")

    assert knowledge.registrar_mencao(
        conceito["id"],
        notebook_id=nb,
        trecho="O protocolo KWP2000 roda sobre a linha K.",
        referencia=TEXTO,
        source_id=src["id"],
    )

    guardadas = knowledge.mencoes(conceito["id"])
    assert len(guardadas) == 1
    assert guardadas[0]["source_id"] == src["id"]
    assert guardadas[0]["source_title"] == "Fonte"
    assert "KWP2000" in guardadas[0]["excerpt"]


def test_re_extrair_nao_duplica_a_mesma_mencao():
    nb = caderno()
    src = fonte(nb, TEXTO)
    conceito = knowledge.achar_ou_criar("KWP2000")
    dados = dict(
        notebook_id=nb,
        trecho="O protocolo KWP2000 roda sobre a linha K.",
        referencia=TEXTO,
        source_id=src["id"],
    )

    for _ in range(3):
        assert knowledge.registrar_mencao(conceito["id"], **dados)

    assert len(knowledge.mencoes(conceito["id"])) == 1


# -------------------------------------------------------------------- arestas


def test_a_aresta_nao_espelha():
    a = knowledge.achar_ou_criar("KWP2000")
    b = knowledge.achar_ou_criar("OBD-II")

    knowledge.ligar(a["id"], b["id"])
    knowledge.ligar(b["id"], a["id"])  # a mesma, na ordem inversa

    assert knowledge.estatisticas()["arestas"] == 1, "gravou a aresta duas vezes"
    vizinhos = knowledge.vizinhanca(a["id"])["neighbors"]
    assert len(vizinhos) == 1


def test_co_ocorrencia_soma_peso_e_explicita_nao():
    a = knowledge.achar_ou_criar("KWP2000")
    b = knowledge.achar_ou_criar("OBD-II")

    for _ in range(4):
        knowledge.ligar(a["id"], b["id"], knowledge.CO_OCORRENCIA)
    vizinhos = knowledge.vizinhanca(a["id"])["neighbors"]
    assert vizinhos[0]["weight"] == 4

    knowledge.ligar_explicito(
        a["id"], b["id"], trecho="O protocolo KWP2000 roda sobre a linha K.", referencia=TEXTO, quem="modelo"
    )
    tipos = {v["kind"]: v["weight"] for v in knowledge.vizinhanca(a["id"])["neighbors"]}
    assert tipos[knowledge.EXPLICITA] == 1


def test_a_aresta_explicita_sem_trecho_real_nao_entra():
    a = knowledge.achar_ou_criar("KWP2000")
    b = knowledge.achar_ou_criar("OBD-II")

    entrou = knowledge.ligar_explicito(
        a["id"],
        b["id"],
        trecho="O KWP2000 substituiu o OBD-II nos carros elétricos.",
        referencia=TEXTO,
        quem="modelo",
    )

    assert entrou is False
    assert knowledge.vizinhanca(a["id"])["neighbors"] == []


def test_a_aresta_explicita_guarda_quem_afirmou_e_o_que_sustenta():
    a = knowledge.achar_ou_criar("KWP2000")
    b = knowledge.achar_ou_criar("OBD-II")
    trecho = "O protocolo KWP2000 roda sobre a linha K."

    knowledge.ligar_explicito(a["id"], b["id"], trecho=trecho, referencia=TEXTO, quem="modelo")

    vizinho = knowledge.vizinhanca(a["id"])["neighbors"][0]
    assert vizinho["kind"] == knowledge.EXPLICITA
    assert "modelo" in vizinho["provenance"]
    assert "linha K" in vizinho["provenance"]


def test_co_ocorrencia_liga_todos_os_pares_do_bloco():
    ids = [knowledge.achar_ou_criar(n)["id"] for n in ("A", "B", "C", "D")]
    assert knowledge.co_ocorrencia(ids) == 6  # C(4,2)
    assert knowledge.estatisticas()["arestas"] == 6


def test_co_ocorrencia_ignora_repetido_e_um_so():
    a = knowledge.achar_ou_criar("A")["id"]
    assert knowledge.co_ocorrencia([a, a, a]) == 0
    assert knowledge.co_ocorrencia([a]) == 0


# ---------------------------------------------------------------------- grafo


def test_o_grafo_filtrado_por_caderno_nao_mostra_aresta_saindo_para_fora():
    nb1 = caderno("Um")
    nb2 = caderno("Dois")
    s1 = fonte(nb1, TEXTO)
    s2 = fonte(nb2, "Outro material sobre sensores.")

    a = knowledge.achar_ou_criar("KWP2000")
    b = knowledge.achar_ou_criar("OBD-II")
    c = knowledge.achar_ou_criar("Sensor de oxigênio")
    knowledge.registrar_mencao(a["id"], notebook_id=nb1, trecho="KWP2000 roda sobre a linha K.", referencia=TEXTO, source_id=s1["id"])
    knowledge.registrar_mencao(b["id"], notebook_id=nb1, trecho="O OBD-II exige o conector", referencia=TEXTO, source_id=s1["id"])
    knowledge.registrar_mencao(c["id"], notebook_id=nb2, trecho="material sobre sensores", referencia="Outro material sobre sensores.", source_id=s2["id"])

    knowledge.ligar(a["id"], b["id"])
    knowledge.ligar(b["id"], c["id"])  # atravessa cadernos

    g = knowledge.grafo(notebook_id=nb1)
    ids = {n["id"] for n in g["nodes"]}
    assert ids == {a["id"], b["id"]}
    assert len(g["edges"]) == 1
    assert {g["edges"][0]["a_id"], g["edges"][0]["b_id"]} == {a["id"], b["id"]}


def test_o_grafo_marca_o_conceito_que_aparece_em_mais_de_um_caderno():
    """É a informação mais interessante do desenho: a ponte entre cadernos."""
    nb1 = caderno("Um")
    nb2 = caderno("Dois")
    s1 = fonte(nb1, TEXTO)
    texto2 = "O OBD-II também aparece aqui."
    s2 = fonte(nb2, texto2)

    b = knowledge.achar_ou_criar("OBD-II")
    knowledge.registrar_mencao(b["id"], notebook_id=nb1, trecho="O OBD-II exige o conector", referencia=TEXTO, source_id=s1["id"])
    knowledge.registrar_mencao(b["id"], notebook_id=nb2, trecho="O OBD-II também aparece aqui.", referencia=texto2, source_id=s2["id"])

    no = next(n for n in knowledge.grafo()["nodes"] if n["id"] == b["id"])
    assert no["ponte"] is True
    assert len(no["notebooks"]) == 2


def test_grafo_vazio_nao_quebra():
    assert knowledge.grafo() == {"nodes": [], "edges": [], "notebooks": []}


# ---------------------------------------------------------------------- edição


def test_mesclar_migra_as_mencoes_e_nao_perde_prova():
    """Fusão move a prova; nunca apaga. O trecho é a razão de o grafo valer."""
    nb = caderno()
    src = fonte(nb, TEXTO)
    velho = knowledge.achar_ou_criar("OBD2")
    novo = knowledge.achar_ou_criar("OBD-II")

    knowledge.registrar_mencao(velho["id"], notebook_id=nb, trecho="O OBD-II exige o conector", referencia=TEXTO, source_id=src["id"])

    fundido = knowledge.mesclar(velho["id"], novo["id"])

    assert fundido["id"] == novo["id"]
    assert knowledge.get_conceito(velho["id"]) is None
    guardadas = knowledge.mencoes(novo["id"])
    assert len(guardadas) == 1, "a menção do conceito fundido se perdeu"
    assert "OBD2" in fundido["aliases"], "o nome antigo virou alias"
    assert knowledge.orfaos() == 0


def test_mesclar_nao_deixa_aresta_em_laco():
    a = knowledge.achar_ou_criar("A")
    b = knowledge.achar_ou_criar("B")
    c = knowledge.achar_ou_criar("C")
    knowledge.ligar(a["id"], c["id"])
    knowledge.ligar(b["id"], c["id"])

    knowledge.mesclar(b["id"], a["id"])

    arestas = knowledge.estatisticas()["arestas"]
    assert arestas == 1, f"esperava 1 aresta (A-C), achei {arestas}"
    for vizinho in knowledge.vizinhanca(a["id"])["neighbors"]:
        assert vizinho["concept"]["id"] != a["id"], "criou uma aresta do conceito com ele mesmo"


def test_renomear_para_um_nome_que_ja_existe_mescla_em_vez_de_estourar():
    """Colidir é o caso comum (OBD2 → OBD-II), não o excepcional."""
    nb = caderno()
    src = fonte(nb, TEXTO)
    velho = knowledge.achar_ou_criar("OBD2")
    knowledge.achar_ou_criar("OBD-II")
    knowledge.registrar_mencao(velho["id"], notebook_id=nb, trecho="O OBD-II exige o conector", referencia=TEXTO, source_id=src["id"])

    resultado = knowledge.renomear(velho["id"], "OBD-II")

    assert resultado["canonical"] == knowledge.normalizar("OBD-II")
    assert knowledge.get_conceito(velho["id"]) is None
    assert len(knowledge.mencoes(resultado["id"])) == 1


def test_renomear_para_nome_novo_troca_o_nome_e_a_chave():
    c = knowledge.achar_ou_criar("KWP 2000")
    novo = knowledge.renomear(c["id"], "KWP2000")
    assert novo["name"] == "KWP2000"
    assert novo["canonical"] == "kwp2000"


def test_apagar_leva_mencoes_e_arestas():
    nb = caderno()
    src = fonte(nb, TEXTO)
    a = knowledge.achar_ou_criar("KWP2000")
    b = knowledge.achar_ou_criar("OBD-II")
    knowledge.registrar_mencao(a["id"], notebook_id=nb, trecho="O protocolo KWP2000 roda sobre a linha K.", referencia=TEXTO, source_id=src["id"])
    knowledge.ligar(a["id"], b["id"])

    assert knowledge.apagar(a["id"]) is True
    assert knowledge.get_conceito(a["id"]) is None
    assert knowledge.estatisticas()["mencoes"] == 0
    assert knowledge.estatisticas()["arestas"] == 0


def test_limpar_fonte_poda_o_conceito_que_ficou_sem_ancora():
    """Conceito sem menção perdeu a âncora — e sem âncora não é conhecimento."""
    nb = caderno()
    src = fonte(nb, TEXTO)
    a = knowledge.achar_ou_criar("KWP2000")
    b = knowledge.achar_ou_criar("OBD-II")
    knowledge.registrar_mencao(a["id"], notebook_id=nb, trecho="O protocolo KWP2000 roda sobre a linha K.", referencia=TEXTO, source_id=src["id"])
    knowledge.registrar_mencao(b["id"], notebook_id=nb, trecho="O OBD-II exige o conector", referencia=TEXTO, source_id=src["id"])

    resultado = knowledge.limpar_fonte(src["id"])

    assert resultado["mentions"] == 2
    assert resultado["concepts"] == 2
    assert knowledge.estatisticas()["conceitos"] == 0
    assert knowledge.orfaos() == 0


def test_limpar_fonte_preserva_o_conceito_mencionado_em_outra_fonte():
    nb = caderno()
    s1 = fonte(nb, TEXTO, "Primeira")
    s2 = fonte(nb, "Mais sobre KWP2000 aqui.", "Segunda")
    a = knowledge.achar_ou_criar("KWP2000")
    knowledge.registrar_mencao(a["id"], notebook_id=nb, trecho="O protocolo KWP2000 roda sobre a linha K.", referencia=TEXTO, source_id=s1["id"])
    knowledge.registrar_mencao(a["id"], notebook_id=nb, trecho="Mais sobre KWP2000 aqui.", referencia="Mais sobre KWP2000 aqui.", source_id=s2["id"])

    knowledge.limpar_fonte(s1["id"])

    assert knowledge.get_conceito(a["id"]) is not None
    assert len(knowledge.mencoes(a["id"])) == 1
    assert knowledge.mencoes(a["id"])[0]["source_title"] == "Segunda"


# ------------------------------------------------------------------ integração


def test_apagar_a_fonte_no_banco_leva_as_mencoes_junto():
    """D037 vale para o grafo: apagar é uma operação só."""
    nb = caderno()
    src = fonte(nb, TEXTO)
    a = knowledge.achar_ou_criar("KWP2000")
    knowledge.registrar_mencao(a["id"], notebook_id=nb, trecho="O protocolo KWP2000 roda sobre a linha K.", referencia=TEXTO, source_id=src["id"])
    assert knowledge.estatisticas()["mencoes"] == 1

    db.delete_source(src["id"])

    assert knowledge.estatisticas()["mencoes"] == 0, "a menção sobreviveu à fonte"


def test_apagar_o_caderno_no_banco_leva_as_mencoes_junto():
    nb = caderno()
    src = fonte(nb, TEXTO)
    a = knowledge.achar_ou_criar("KWP2000")
    knowledge.registrar_mencao(a["id"], notebook_id=nb, trecho="O protocolo KWP2000 roda sobre a linha K.", referencia=TEXTO, source_id=src["id"])

    db.delete_notebook(nb)

    assert knowledge.estatisticas()["mencoes"] == 0


def test_vizinhanca_traz_o_conceito_o_vizinho_e_a_prova():
    nb = caderno()
    src = fonte(nb, TEXTO)
    a = knowledge.achar_ou_criar("KWP2000")
    b = knowledge.achar_ou_criar("OBD-II")
    knowledge.registrar_mencao(a["id"], notebook_id=nb, trecho="O protocolo KWP2000 roda sobre a linha K.", referencia=TEXTO, source_id=src["id"])
    knowledge.ligar_explicito(a["id"], b["id"], trecho="O OBD-II exige o conector", referencia=TEXTO, quem="modelo")

    v = knowledge.vizinhanca(a["id"])

    assert v["concept"]["name"] == "KWP2000"
    assert v["neighbors"][0]["concept"]["name"] == "OBD-II"
    assert v["neighbors"][0]["mentions"] == 0
    assert len(v["mentions"]) == 1
    assert v["mentions"][0]["notebook_title"] == "Caderno"


def test_vizinhanca_de_conceito_inexistente_e_nula():
    assert knowledge.vizinhanca("cpt_nao_existe") is None


def test_buscar_acha_por_nome_e_por_alias():
    knowledge.achar_ou_criar("OBD-II")
    knowledge.achar_ou_criar("OBD II")  # entra como alias

    assert [c["name"] for c in knowledge.buscar("obd")] == ["OBD-II"]
    assert knowledge.buscar("kwp2000") == []


def test_o_vocabulario_traz_os_nomes_para_o_extrator():
    """D041: é isto que impede o grafo de fragmentar em variantes."""
    nb = caderno()
    src = fonte(nb, TEXTO)
    a = knowledge.achar_ou_criar("KWP2000")
    b = knowledge.achar_ou_criar("OBD-II")
    knowledge.registrar_mencao(a["id"], notebook_id=nb, trecho="KWP2000 roda sobre a linha K.", referencia=TEXTO, source_id=src["id"])

    vocab = knowledge.vocabulario()

    assert vocab == ["KWP2000", "OBD-II"], "ordena pelo mais mencionado primeiro"
    assert b["name"] in vocab


def test_origem_da_mencao_e_legivel():
    nb = caderno()
    src = fonte(nb, TEXTO, "Manual do veículo")
    a = knowledge.achar_ou_criar("KWP2000")
    knowledge.registrar_mencao(a["id"], notebook_id=nb, trecho="O protocolo KWP2000 roda sobre a linha K.", referencia=TEXTO, source_id=src["id"])

    assert "Manual do veículo" in knowledge.origem_da_mencao(knowledge.mencoes(a["id"])[0])
