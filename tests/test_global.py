"""Testes do chat global — o que enxerga todos os cadernos (F2, D039).

O que estes testes protegem, em ordem de importância:

1. **Escopo.** O chat de um caderno continua sem alcançar as fontes de outro; o
   global alcança todas. Se os dois vazassem um para o outro, a garantia da D034
   deixaria de existir.
2. **Numeração.** As citações `[n]` do chat global têm que casar entre o índice do
   prompt e a ferramenta de listagem. Quando não casaram (no chat do caderno), o
   modelo citava `[2]` apontando para a fonte errada.
3. **Cross-relação.** O valor do chat global é ler em mais de um caderno na mesma
   resposta — então há teste de que a ferramenta alcança o segundo caderno.
"""

from __future__ import annotations

import asyncio

from langchain_core.tools import BaseTool

from frutiger_lm import db, ingest
from frutiger_lm.engine import agent, fake, llm
from frutiger_lm.engine.tools.leitura import Escopo, ferramentas_de_leitura


def caderno(titulo: str) -> str:
    return db.create_notebook(titulo)["id"]


def fonte(notebook_id: str, texto: str, titulo: str = "Fonte") -> str:
    return asyncio.run(ingest.add_source(notebook_id, kind="text", text=texto, title=titulo))["id"]


def ferramenta(nome: str, escopo: Escopo) -> BaseTool:
    return {t.name: t for t in ferramentas_de_leitura(escopo)}[nome]


# -------------------------------------------------------------------- escopo


def test_o_escopo_do_caderno_nao_alcanca_outro_caderno():
    """A garantia da D034 continua de pé depois do escopo virar um tipo."""
    meu = caderno("Meu")
    outro = caderno("Alheio")
    sid_alheio = fonte(outro, "conteudo secreto do outro caderno", "Secreto")

    saida = ferramenta("ler_fonte", Escopo.do_caderno(meu)).invoke({"source_id": sid_alheio})
    assert "conteudo secreto" not in saida
    assert "não existe" in saida.lower()


def test_o_escopo_global_alcanca_qualquer_caderno():
    """O que o chat global existe para fazer: ler fora do próprio quintal."""
    a = caderno("Automotivo")
    b = caderno("Eletronica")
    sid_a = fonte(a, "O protocolo KWP2000 usa 5 baudes no inicio.", "KWP2000")
    sid_b = fonte(b, "O barramento CAN opera em par trançado.", "CAN")

    ler = ferramenta("ler_fonte", Escopo.todos())
    assert "KWP2000" in ler.invoke({"source_id": sid_a})
    assert "CAN" in ler.invoke({"source_id": sid_b})


def test_o_escopo_global_diz_de_qual_caderno_veio():
    """Sem isso a pessoa não sabe onde ir conferir — e conferir é o ponto."""
    a = caderno("Caderno A")
    sid = fonte(a, "material do caderno A", "Fonte do A")
    saida = ferramenta("ler_fonte", Escopo.todos()).invoke({"source_id": sid})
    assert "Caderno A" in saida


def test_aceita_o_id_direto_para_o_caso_comum():
    """`ferramentas_de_leitura("nb_x")` continua valendo: o caso comum é um caderno."""
    assert ferramentas_de_leitura("nb_x")[0].name == "listar_fontes"
    assert Escopo.de("nb_x").notebook_id == "nb_x"
    assert Escopo.de(Escopo.todos()).e_global is True


# ----------------------------------------------------------------- listagem


def test_a_listagem_global_mostra_os_cadernos_e_as_fontes():
    a = caderno("Sistemas Embarcados")
    b = caderno("Direito")
    fonte(a, "material sobre protocolo", "Protocolo")
    fonte(b, "material sobre contratos", "Contratos")

    saida = ferramenta("listar_fontes", Escopo.todos()).invoke({})

    assert "Sistemas Embarcados" in saida
    assert "Direito" in saida
    assert "Protocolo" in saida
    assert "Contratos" in saida
    assert "2 caderno(s)" in saida


def test_a_listagem_global_marca_caderno_vazio():
    caderno("Vazio")
    assert "(sem fontes ativas)" in ferramenta("listar_fontes", Escopo.todos()).invoke({})


def test_a_busca_global_alcanca_o_segundo_caderno_e_diz_qual_e():
    """Cross-relação: o dado pode estar em qualquer caderno."""
    a = caderno("Automotivo")
    b = caderno("Normas")
    fonte(a, "material irrelevante sobre pintura", "Pintura")
    fonte(b, "O codigo de homologacao exigido e ZULU-90210.", "Resolucao")

    saida = ferramenta("buscar_nas_fontes", Escopo.todos()).invoke({"termo": "ZULU-90210"})

    assert "ZULU-90210" in saida
    assert "Normas" in saida, "não disse de qual caderno veio"


def test_a_busca_do_caderno_nao_vaza_para_outro():
    a = caderno("A")
    b = caderno("B")
    fonte(b, "termo-proibido mora aqui", "Do B")
    saida = ferramenta("buscar_nas_fontes", Escopo.do_caderno(a)).invoke({"termo": "termo-proibido"})
    assert "termo-proibido mora aqui" not in saida


# ---------------------------------------------------------------- numeração


def test_a_numeracao_global_casa_entre_o_indice_do_prompt_e_a_ferramenta():
    """A armadilha que já custou uma correção no chat do caderno.

    O índice vai no prompt e a ferramenta lista por chamada: se os dois numerarem
    diferente, o modelo cita `[2]` e a pessoa confere na fonte errada.
    """
    a = caderno("Primeiro")
    b = caderno("Segundo")
    fonte(a, "material A1", "A1")
    fonte(b, "material B1", "B1")
    fonte(a, "material A2", "A2")

    listagem = ferramenta("listar_fontes", Escopo.todos()).invoke({})
    indice = db.build_global_index()

    # A verdade é a ordem canônica; o que se verifica é que os DOIS consumidores
    # concordam com ela. Foi a divergência entre eles que fez o chat do caderno
    # citar [2] apontando para a fonte errada.
    canonica = [(i, f["id"]) for i, f in enumerate(db.fontes_ativas_globais(), start=1)]
    assert len(canonica) == 3

    for posicao, sid in canonica:
        assert f"[{posicao}] {sid}" in listagem, f"[{posicao}] deveria ser {sid} na listagem"
        linha = next(x for x in indice.splitlines() if x.startswith(f"[{posicao}] "))
        assert sid in linha, f"[{posicao}] deveria ser {sid} no índice"


def test_a_numeracao_global_nao_muda_quando_um_caderno_e_editado():
    """Ordem de criação, não de `updated_at`: senão citação antiga passaria a
    apontar para outra fonte."""
    a = caderno("Primeiro")
    b = caderno("Segundo")
    fonte(a, "material A", "A")
    sid_b = fonte(b, "material B", "B")

    antes = db.build_global_index()
    db.update_notebook(b, title="Segundo (renomeado)")  # mexe no updated_at
    depois = db.build_global_index()

    assert db.fontes_ativas_globais()[1]["id"] == sid_b, "a posição da fonte mudou"
    assert antes.count("[2] B") == depois.count("[2] B") == 1


def test_a_listagem_global_limita_e_avisa():
    """D035 vale também para o escopo global."""
    a = caderno("Grande")
    for i in range(12):
        fonte(a, f"material {i}", f"Fonte {i}")

    saida = ferramenta("listar_fontes", Escopo.todos()).invoke({})
    assert "e mais" in saida
    assert "buscar_nas_fontes" in saida, "precisa dizer como chegar nas que não listou"


# ------------------------------------------------------------------- catálogo


def test_o_catalogo_global_tem_as_mesmas_ferramentas():
    """D039: nenhuma ferramenta nova de LEITURA — a diferença é o escopo.

    As três de grafo entram nos dois catálogos (D045), sem escopo: o grafo é a
    camada que liga, e um conceito em dois cadernos é o que ele tem de melhor.
    """
    nomes = {t.name for t in agent.catalogo_global()}
    assert nomes == {
        "listar_fontes",
        "ler_fonte",
        "buscar_nas_fontes",
        "web_extract",
        "buscar_no_grafo",
        "vizinhanca_do_conceito",
        "registrar_relacao",
    }
    assert nomes == {t.name for t in agent.catalogo(caderno("X"))}


def test_o_prompt_global_cita_todos_os_cadernos():
    from frutiger_lm.prompts import build_global_prompt

    caderno("Sistemas Embarcados")
    caderno("Direito Constitucional")
    prompt = build_global_prompt()
    assert "Sistemas Embarcados" in prompt
    assert "Direito Constitucional" in prompt
    assert "ligar os conhecimentos" in prompt, "o valor do chat global é a ligação"


def test_o_prompt_global_sem_cadernos_orienta():
    from frutiger_lm.prompts import build_global_prompt

    assert "Não há cadernos ainda" in build_global_prompt()


# ---------------------------------------------------------------- rota global


def test_o_chat_global_responde_e_le_fora_do_caderno(cliente, monkeypatch):
    """Ponta a ponta: o agente global alcança a fonte do outro caderno."""
    fonte(caderno("Automotivo"), "material sobre pintura", "Pintura")
    fonte(caderno("Normas"), "O codigo exigido e ZULU-90210.", "Resolucao")

    monkeypatch.setattr(
        llm,
        "atual",
        lambda: fake.com_ferramenta(
            "buscar_nas_fontes", {"termo": "ZULU-90210"}, "achei no caderno Normas"
        ),
    )

    resp = cliente.post("/api/global/chat", json={"input": "qual o codigo exigido?"})

    assert resp.status_code == 200
    corpo = resp.text
    for evento in ("run.started", "tool.started", "assistant.delta", "assistant.completed", "done"):
        assert f"event: {evento}" in corpo, f"faltou o evento {evento}"
    assert "achei no caderno Normas" in corpo


def test_o_chat_global_avisa_sem_modelo(cliente):
    resp = cliente.post("/api/global/chat", json={"input": "oi"})
    assert resp.status_code == 200
    assert "event: error" in resp.text
    assert "não configurado" in resp.text


def test_o_historico_global_vem_do_checkpointer(cliente, monkeypatch):
    monkeypatch.setattr(llm, "atual", lambda: fake.responde("resposta global"))

    cliente.post("/api/global/chat", json={"input": "pergunta global"})
    mensagens = cliente.get("/api/global/messages").json()

    assert [m["role"] for m in mensagens] == ["user", "assistant"]
    assert mensagens[0]["content"] == "pergunta global"
    assert mensagens[1]["content"] == "resposta global"


def test_a_conversa_global_nao_se_mistura_com_a_do_caderno(cliente, monkeypatch):
    """Threads diferentes, memórias diferentes (D019).

    O modelo é o mesmo nas duas conversas de propósito: o que se verifica aqui é
    o isolamento dos threads, não a resposta. Se as conversas se misturassem, as
    perguntas de uma apareceriam no histórico da outra.
    """
    nb = caderno("Um caderno")
    fonte(nb, "material", "Fonte")
    monkeypatch.setattr(llm, "atual", lambda: fake.responde("mesma resposta"))

    cliente.post(f"/api/notebooks/{nb}/chat", json={"input": "pergunta do caderno"})
    cliente.post("/api/global/chat", json={"input": "pergunta global"})

    do_caderno = [m["content"] for m in cliente.get(f"/api/notebooks/{nb}/messages").json()]
    do_global = [m["content"] for m in cliente.get("/api/global/messages").json()]

    assert do_caderno == ["pergunta do caderno", "mesma resposta"]
    assert do_global == ["pergunta global", "mesma resposta"]


def test_limpar_a_conversa_global_so_apaga_a_global(cliente, monkeypatch):
    nb = caderno("Fica")
    fonte(nb, "material", "Fonte")
    monkeypatch.setattr(llm, "atual", lambda: fake.responde("oi"))

    cliente.post(f"/api/notebooks/{nb}/chat", json={"input": "do caderno"})
    cliente.post("/api/global/chat", json={"input": "global"})

    assert cliente.delete("/api/global/chat").status_code == 200

    assert cliente.get("/api/global/messages").json() == []
    assert cliente.get(f"/api/notebooks/{nb}/messages").json(), "apagou a do caderno junto"


def test_o_chat_global_nao_explode_sem_caderno_nenhum(cliente, monkeypatch):
    monkeypatch.setattr(llm, "atual", lambda: fake.responde("não há nada ainda"))
    resp = cliente.post("/api/global/chat", json={"input": "o que eu tenho?"})
    assert resp.status_code == 200
    assert "não há nada ainda" in resp.text
