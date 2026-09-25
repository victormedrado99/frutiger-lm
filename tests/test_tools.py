"""Testes das ferramentas do motor.

Tudo local: banco e arquivos em diretório temporário (o conftest aponta
FRUTIGER_DATA_DIR). Nenhuma rede, nenhuma chave, nenhum modelo.

O que mais importa aqui é **isolamento**: a ferramenta é presa a um caderno
(D034), e o teste da fonte de outro caderno é o que garante que isso vale de
verdade — e não só na intenção.
"""

from __future__ import annotations

import asyncio

from frutiger_lm import db, ingest
from frutiger_lm.engine.tools import leitura


def caderno(titulo: str = "Caderno de teste") -> str:
    return db.create_notebook(titulo)["id"]


def fonte(notebook_id: str, texto: str, titulo: str = "Fonte") -> str:
    """Ingere uma fonte de texto de verdade (grava arquivo + linha no banco)."""
    return asyncio.run(ingest.add_source(notebook_id, kind="text", text=texto, title=titulo))["id"]


def chamar(nome: str, notebook_id: str, **args) -> str:
    """Chama a ferramenta como o agente chamaria."""
    ferramentas = {t.name: t for t in leitura.ferramentas_de_leitura(notebook_id)}
    assert nome in ferramentas, f"ferramenta {nome} não existe no catálogo"
    return ferramentas[nome].invoke(args)


def mil(n: int) -> str:
    """Milhar pt-BR, na mão de propósito: expectativa de teste não deve importar
    o formatador da implementação, senão um bug nele passa batido."""
    return f"{n:,}".replace(",", ".")


def total_de(source_id: str) -> int:
    """Tamanho real do arquivo da fonte — que inclui o cabeçalho `# Título`."""
    fonte_criada = db.get_source(source_id)
    assert fonte_criada is not None
    return fonte_criada["chars"]


# ------------------------------------------------------------------ catálogo


def test_o_catalogo_tem_as_tres_ferramentas():
    nomes = {t.name for t in leitura.ferramentas_de_leitura("nb_qualquer")}
    assert nomes == {"listar_fontes", "ler_fonte", "buscar_nas_fontes"}


def test_o_notebook_id_nao_e_parametro_de_ferramenta():
    """D034: o caderno é preso na construção.

    Se o id fosse parâmetro, o modelo poderia errá-lo ou apontar para outro
    caderno. Aqui a garantia é estrutural, não comportamental.
    """
    for ferramenta in leitura.ferramentas_de_leitura("nb_x"):
        assert "notebook_id" not in ferramenta.args, f"{ferramenta.name} expõe o id"
        assert "caderno_id" not in ferramenta.args


# ------------------------------------------------------------- listar_fontes


def test_listar_fontes_mostra_id_tipo_tamanho_e_titulo():
    nb = caderno()
    sid = fonte(nb, "conteúdo qualquer", "Resumo do professor")
    saida = chamar("listar_fontes", nb)
    assert sid in saida
    assert "Resumo do professor" in saida
    assert "1 ativas de 1" in saida


def test_listar_fontes_marca_a_desligada_sem_numerar():
    nb = caderno()
    sid = fonte(nb, "material", "Anotações soltas")
    db.set_source_active(sid, False)
    saida = chamar("listar_fontes", nb)
    assert "0 ativas de 1" in saida
    assert "Desligadas" in saida
    assert sid in saida
    # sem número: o número é só das ativas, para casar com o contexto inline
    assert f"[1] {sid}" not in saida


def test_listar_fontes_em_caderno_vazio_orienta():
    saida = chamar("listar_fontes", caderno())
    assert "não tem fontes" in saida


# ----------------------------------------------------------------- ler_fonte


def test_ler_fonte_devolve_trecho_com_posicao():
    nb = caderno()
    sid = fonte(nb, "A" * 100, "Curta")
    total = total_de(sid)
    saida = chamar("ler_fonte", nb, source_id=sid)
    assert f"trecho de 0 a {mil(total)} de {mil(total)} caracteres" in saida
    assert "continua" not in saida, "fonte curta não deveria dizer que continua"
    # o arquivo começa com o cabeçalho, então o modelo sabe de onde veio o texto
    assert "# Curta" in saida


def test_ler_fonte_de_fonte_longa_diz_onde_parou_e_como_continuar():
    nb = caderno()
    sid = fonte(nb, "B" * 20_000, "Longa")
    total = total_de(sid)
    assert total > 20_000, "o cabeçalho do ingest entra na conta"
    saida = chamar("ler_fonte", nb, source_id=sid, tamanho=5_000)
    assert f"trecho de 0 a 5.000 de {mil(total)}" in saida
    assert "inicio=5000" in saida, "sem a próxima posição o modelo não sabe continuar"


def test_ler_fonte_respeita_o_teto_de_saida():
    """O ponto que evita estourar o contexto: pedir tudo não devolve tudo."""
    nb = caderno()
    sid = fonte(nb, "C" * 50_000, "Enorme")
    total = total_de(sid)
    saida = chamar("ler_fonte", nb, source_id=sid, tamanho=999_999)
    assert f"a {mil(leitura.TAMANHO_MAXIMO)} de {mil(total)}" in saida
    assert len(saida) < total, "a saída não foi limitada ao teto"
    assert "inicio=" in saida, "e precisa dizer como continuar"


def test_ler_fonte_recusa_fonte_de_OUTRO_caderno():
    """O teste de isolamento — a razão de existir do D034."""
    meu = caderno("Meu caderno")
    outro = caderno("Caderno alheio")
    sid_alheio = fonte(outro, "segredo do outro caderno")

    saida = chamar("ler_fonte", meu, source_id=sid_alheio)
    assert "segredo do outro caderno" not in saida
    assert "não existe fonte" in saida.lower()


def test_ler_fonte_recusa_fonte_desligada_explicando():
    nb = caderno()
    sid = fonte(nb, "material que está desligado", "Desligada")
    db.set_source_active(sid, False)
    saida = chamar("ler_fonte", nb, source_id=sid)
    assert "DESLIGADA" in saida
    assert "religar" in saida, "precisa dizer o que fazer, não só que está desligada"
    assert "material que está desligado" not in saida


def test_ler_fonte_com_id_inexistente_nao_explode():
    saida = chamar("ler_fonte", caderno(), source_id="src_nao_existe")
    assert "não existe fonte" in saida.lower()


# --------------------------------------------------------- buscar_nas_fontes


def test_buscar_encontra_com_numero_de_linha():
    nb = caderno()
    texto = "\n".join(
        [
            "Primeira linha sem nada.",
            "O código do equipamento é BRAVO-7741 e ele é antigo.",
            "Terceira linha.",
        ]
    )
    sid = fonte(nb, texto, "Manual")
    saida = chamar("buscar_nas_fontes", nb, termo="BRAVO-7741")

    assert "1 ocorrência(s)" in saida
    # o trecho devolvido traz a linha inteira, não só o termo casado
    assert "O código do equipamento é BRAVO-7741 e ele é antigo." in saida
    assert "linha" in saida
    assert sid in saida
    # a numeração é a do arquivo, que começa com o cabeçalho `# Manual`
    assert "Manual" in saida


def test_buscar_ignora_fonte_desligada():
    """Com a única fonte desligada, a resposta certa é dizer que não há fonte
    ativa — e não "nada encontrado", que sugeriria que a busca rodou."""
    nb = caderno()
    sid = fonte(nb, "termo-proibido aparece aqui", "Desligada")
    db.set_source_active(sid, False)
    saida = chamar("buscar_nas_fontes", nb, termo="termo-proibido")
    assert "termo-proibido aparece aqui" not in saida
    assert "Não há fontes ativas" in saida


def test_buscar_sem_resultado_sugere_tentar_variacao():
    nb = caderno()
    fonte(nb, "material sobre outra coisa completamente diferente", "Fonte")
    saida = chamar("buscar_nas_fontes", nb, termo="zebra-inexistente")
    assert "Nenhuma ocorrência" in saida
    assert "variação" in saida


def test_buscar_limita_a_quantidade_e_avisa():
    nb = caderno()
    entrada = "\n".join(f"linha {i} com o termo repetido" for i in range(40))
    fonte(nb, entrada, "Repetitiva")
    saida = chamar("buscar_nas_fontes", nb, termo="termo repetido")
    assert f"limite de {leitura.MAX_RESULTADOS} atingido" in saida
    assert "refine o termo" in saida


def test_buscar_com_termo_vazio_nao_explode():
    nb = caderno()
    fonte(nb, "qualquer coisa")
    assert "Informe um termo" in chamar("buscar_nas_fontes", nb, termo="   ")


def test_buscar_sem_fontes_ativas_avisa():
    nb = caderno()
    sid = fonte(nb, "material")
    db.set_source_active(sid, False)
    assert "Não há fontes ativas" in chamar("buscar_nas_fontes", nb, termo="material")


# ------------------------------------------------- integração com o laço


def test_as_ferramentas_rodam_dentro_do_laco_do_agente():
    """`create_agent` + nossas ferramentas, sem LLM nenhum.

    O fake emite a tool call, o agente executa a ferramenta **de verdade** e
    devolve o resultado ao histórico. É o que prova compatibilidade — schema,
    chamada e retorno — antes de existir um modelo real no caminho. Se isto
    quebrar, o problema está na ferramenta ou na integração, nunca no modelo.
    """
    from langchain.agents import create_agent

    from frutiger_lm.engine import fake

    nb = caderno()
    fonte(nb, "O código do equipamento é BRAVO-7741.", "Manual")

    modelo = fake.com_ferramenta("buscar_nas_fontes", {"termo": "BRAVO-7741"}, "encontrei")
    agente = create_agent(
        modelo,
        tools=leitura.ferramentas_de_leitura(nb),
        system_prompt="Você é um assistente de teste.",
    )

    saida = agente.invoke({"messages": [{"role": "user", "content": "procure BRAVO-7741"}]})
    mensagens = saida["messages"]

    # a ferramenta rodou de verdade: o resultado dela entrou no histórico
    resultados = [m for m in mensagens if type(m).__name__ == "ToolMessage"]
    assert resultados, "o agente não registrou resultado de ferramenta"
    assert "BRAVO-7741" in str(resultados[0].content), "a ferramenta não leu a fonte"
    # e o agente fechou com a resposta final do modelo
    assert mensagens[-1].content == "encontrei"


def test_a_ferramenta_presa_a_outro_caderno_nao_vaza_dentro_do_agente():
    """O isolamento vale também pelo caminho do agente, não só na chamada direta."""
    from langchain.agents import create_agent

    from frutiger_lm.engine import fake

    meu = caderno("Meu")
    outro = caderno("Alheio")
    sid_alheio = fonte(outro, "conteúdo secreto do caderno alheio", "Secreto")

    modelo = fake.com_ferramenta("ler_fonte", {"source_id": sid_alheio}, "pronto")
    agente = create_agent(
        modelo,
        tools=leitura.ferramentas_de_leitura(meu),
        system_prompt="Teste.",
    )

    saida = agente.invoke({"messages": [{"role": "user", "content": "leia essa fonte"}]})
    resultados = [m for m in saida["messages"] if type(m).__name__ == "ToolMessage"]
    assert resultados
    assert "conteúdo secreto" not in str(resultados[0].content)
