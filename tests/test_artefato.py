"""Testes do documento compilado (F5).

O que estes testes protegem:

1. **O documento é do CADERNO, não do grafo inteiro.** Um conceito-ponte aparece nos
   dois cadernos, mas o trecho do outro não entra aqui — nem no texto, nem na contagem
   da capa. Era um vazamento silencioso: o trecho seria real, e estaria no documento
   errado.
2. **O que é fato não passa por modelo.** As lacunas do documento são as mesmas de
   `knowledge.lacunas()`, palavra por palavra; nenhuma parte do texto do modelo entra
   ali.
3. **O apêndice é completo e confere.** Todas as menções do caderno, com a contagem
   batendo com o banco — é a promessa de que cada afirmação tem um trecho por trás.
4. **O modelo recebe o grafo, não o material bruto**, e continua sendo chamado com o
   formato no prompt (D046), sem o que o `json_mode` não devolve nada.
"""

from __future__ import annotations

import asyncio

from frutiger_lm import db, ingest, knowledge
from frutiger_lm.engine import artefato, fake

# Quatro frases, e não duas, por um motivo prático: o corte dos "principais" (2+
# menções) esconde conceito citado uma vez só, e `registrar_mencao` deduplica menção
# idêntica. Para um conceito ter duas menções são precisos dois trechos diferentes.
FRASE_1 = "O protocolo KWP2000 roda sobre a linha K e usa 5 baudes na inicializacao."
FRASE_2 = "O ISO 14230 descreve o KWP2000 como protocolo de aplicacao da linha K."
FRASE_3 = "Na linha K, o KWP2000 troca mensagens curtas com a central eletronica."
FRASE_4 = "O ISO 14230 define dois formatos de mensagem para o KWP2000."

TEXTO = "\n\n".join([FRASE_1, FRASE_2, FRASE_3, FRASE_4])


def caderno(titulo: str = "Caderno") -> str:
    return db.create_notebook(titulo)["id"]


def fonte(notebook_id: str, texto: str = TEXTO, titulo: str = "Fonte") -> dict:
    return asyncio.run(ingest.add_source(notebook_id, kind="text", text=texto, title=titulo))


def mencionar(conceito: str, nb: str, trecho: str, fonte_dada: dict) -> dict:
    dado = knowledge.achar_ou_criar(conceito)
    knowledge.registrar_mencao(
        dado["id"],
        notebook_id=nb,
        trecho=trecho,
        referencia=TEXTO,
        source_id=fonte_dada["id"],
    )
    return dado


def com_caderno() -> dict:
    """Um caderno com dois conceitos ancorados, pronto para virar documento."""
    nb = caderno()
    src = fonte(nb)
    kwp = mencionar("KWP2000", nb, FRASE_1, src)
    mencionar("KWP2000", nb, FRASE_3, src)
    iso = mencionar("ISO 14230", nb, FRASE_2, src)
    mencionar("ISO 14230", nb, FRASE_4, src)
    knowledge.ligar_explicito(
        kwp["id"], iso["id"], trecho=FRASE_2, referencia=TEXTO, quem="modelo"
    )
    return {"nb": nb, "src": src, "kwp": kwp, "iso": iso}


def narrativa(resumo: str = "O material trata de KWP2000.", desenvolvimento: str = "KWP2000 se liga a ISO 14230."):
    return artefato.Narrativa(resumo=resumo, desenvolvimento=desenvolvimento)


def compilar(nb: str, falso=None) -> artefato.Documento:
    return asyncio.run(
        artefato.compilar(nb, modelo=falso or fake.extrai([narrativa()]))
    )


def texto_da(doc: artefato.Documento, titulo: str) -> str:
    for secao in doc.secoes:
        if secao.titulo == titulo:
            return secao.corpo
    raise AssertionError(f"o documento não tem a seção {titulo!r}")


# --------------------------------------------------------------------------- #
# Estrutura e procedência
# --------------------------------------------------------------------------- #


def test_o_documento_tem_as_secoes_na_ordem_de_leitura():
    dados = com_caderno()

    doc = compilar(dados["nb"])
    titulos = [s.titulo for s in doc.secoes if s.nivel == 2]

    assert titulos[0] == "Sumário"
    assert "Resumo" in titulos
    assert "Conceitos do material" in titulos
    assert titulos.index("Resumo") < titulos.index("Conceitos do material")
    assert titulos.index("Conceitos do material") < titulos.index("Desenvolvimento")
    assert titulos.index("Lacunas abertas") < titulos.index("Fontes")
    assert titulos[-1] == "Apêndice — citações"


def test_o_sumario_sai_dos_titulos_reais():
    """Um sumário escrito à mão mente no dia em que uma seção muda de nome."""
    dados = com_caderno()

    doc = compilar(dados["nb"])
    sumario = texto_da(doc, "Sumário")

    assert "Lacunas abertas" in sumario
    assert "Apêndice — citações" in sumario
    assert "KWP2000" in sumario, "os conceitos entram no sumário, indentados"


def test_o_documento_declara_de_onde_veio_cada_secao():
    """É o que impede o documento de mentir sobre si mesmo: `origem` diz quem responde."""
    dados = com_caderno()

    doc = compilar(dados["nb"])
    origens = {s.titulo: s.origem for s in doc.secoes}

    assert origens["Conceitos do material"] == "grafo"
    assert origens["Lacunas abertas"] == "grafo"
    assert origens["Apêndice — citações"] == "grafo"
    assert origens["Fontes"] == "banco"
    assert origens["Resumo"] == "modelo"
    assert origens["Desenvolvimento"] == "modelo"
    assert doc.contagem()["modelo"] == 2, "só duas seções são texto de modelo"


def test_o_conceito_leva_o_trecho_literal_e_a_fonte():
    dados = com_caderno()

    doc = compilar(dados["nb"])
    corpo = texto_da(doc, "KWP2000")

    assert "linha K e usa 5 baudes" in corpo, "o trecho literal de origem"
    assert "Fonte" in corpo, "e de qual fonte ele veio"
    assert corpo.strip().startswith("*2 menção"), "com a contagem de menções"


# --------------------------------------------------------------------------- #
# O escopo: nada de outro caderno
# --------------------------------------------------------------------------- #


def test_o_documento_nao_cita_trecho_de_outro_caderno():
    """O caso da ponte: o conceito é dos dois, o trecho é de cada um.

    Este era um vazamento silencioso — o trecho do outro caderno é verdadeiro, e
    entraria no documento como se fosse deste material. Pior tipo de erro: conferível
    e errado.
    """
    a = caderno("A")
    b = caderno("B")
    fonte_a = fonte(a, TEXTO, "Fonte A")
    outro_texto = (
        "O KWP2000 e um protocolo de diagnostico usado em oficinas.\n\n"
        "Ele define servicos de leitura de codigos de falha."
    )
    fonte_b = fonte(b, outro_texto, "Fonte B")

    compartilhado = mencionar("KWP2000", a, FRASE_1, fonte_a)
    mencionar("KWP2000", a, FRASE_3, fonte_a)
    knowledge.registrar_mencao(
        compartilhado["id"],
        notebook_id=b,
        trecho="O KWP2000 e um protocolo de diagnostico usado em oficinas.",
        referencia=outro_texto,
        source_id=fonte_b["id"],
    )

    doc = compilar(a)
    corpo = texto_da(doc, "KWP2000")

    assert "linha K" in corpo, "o trecho do caderno certo tem que estar lá"
    assert "oficinas" not in corpo, "o trecho do OUTRO caderno não pode entrar neste documento"
    assert "Fonte B" not in doc.markdown(), "nem a fonte do outro caderno"


def test_a_capa_conta_o_caderno_e_nao_o_grafo_inteiro():
    """`estatisticas()` é global: numa capa de documento ele diria o número errado."""
    a = caderno("A")
    b = caderno("B")
    fonte_a = fonte(a, TEXTO, "Fonte A")
    fonte_b = fonte(b, TEXTO, "Fonte B")
    mencionar("KWP2000", a, FRASE_1, fonte_a)
    mencionar("KWP2000", a, FRASE_3, fonte_a)
    mencionar("Entropia", b, FRASE_2, fonte_b)

    capa = texto_da(compilar(a), "A")

    assert "1 fonte(s)" in capa, "só a fonte do caderno A"
    # "Entropia" pode — e deve — aparecer em "Desenvolvidos em outro caderno": essa
    # lacuna é FEITA de conceito de outro caderno. O que não pode é virar conceito
    # deste documento, com trecho e tudo.
    doc = compilar(a)
    assert "Entropia" not in [s.titulo for s in doc.secoes], "não é conceito deste caderno"
    assert "Fonte B" not in doc.markdown()


# --------------------------------------------------------------------------- #
# O que é fato não passa por modelo
# --------------------------------------------------------------------------- #


def test_as_lacunas_do_documento_sao_as_do_grafo_sem_modelo():
    """Consulta, não opinião (D049) — e o documento não pode amaciar isso."""
    nb = caderno()
    src = fonte(nb)
    kwp = mencionar("KWP2000", nb, FRASE_1, src)
    mencionar("KWP2000", nb, FRASE_3, src)
    iso = mencionar("ISO 14230", nb, FRASE_2, src)
    mencionar("ISO 14230", nb, FRASE_4, src)
    knowledge.ligar_explicito(kwp["id"], iso["id"], trecho=FRASE_2, referencia=TEXTO, quem="modelo")
    # "Turbina" é citada uma vez e não se liga a nada: é lacuna.
    mencionar("Turbina", nb, FRASE_2, src)

    esperado = {item["name"] for item in knowledge.lacunas(nb)["nao_desenvolvidos"]}
    corpo = texto_da(compilar(nb), "Lacunas abertas")

    assert esperado == {"Turbina"}
    assert "Turbina" in corpo
    assert "KWP2000" not in corpo, "o que foi desenvolvido não é lacuna"


def test_o_apendice_tem_todas_as_mencoes_e_a_contagem_bate():
    dados = com_caderno()
    no_banco = knowledge.mencoes_do_caderno(dados["nb"])

    corpo = texto_da(compilar(dados["nb"]), "Apêndice — citações")

    assert f"{len(no_banco)} trechos" in corpo
    for mencao in no_banco:
        assert mencao["excerpt"][:40].split()[0] in corpo or mencao["conceito"] in corpo
    assert corpo.count("- **") == len(no_banco), "uma linha por menção, nem mais nem menos"


def test_a_capa_conta_as_mencoes_que_o_apendice_lista():
    """A capa e o apêndice saem da MESMA consulta: não têm como divergir."""
    dados = com_caderno()

    doc = compilar(dados["nb"])

    assert f"{len(knowledge.mencoes_do_caderno(dados['nb']))} menção(ões)" in texto_da(doc, "Caderno")


# --------------------------------------------------------------------------- #
# O modelo
# --------------------------------------------------------------------------- #


def test_o_modelo_recebe_os_conceitos_com_trecho_e_o_formato_no_prompt():
    """D046: `json_mode` exige a palavra 'json' E o formato descrito no prompt."""
    dados = com_caderno()
    falso = fake.extrai([narrativa()])

    compilar(dados["nb"], falso)

    enviado = "\n".join(str(m.content) for m in falso.chamadas[0])
    assert "linha K" in enviado, "o modelo escreve a partir do grafo, não do nada"
    assert "KWP2000" in enviado
    assert "json" in enviado.lower()
    assert '"resumo"' in enviado, "o formato gerado do Pydantic tem que ir no prompt"


def test_o_modelo_nao_recebe_o_material_bruto():
    """Ele recebe o GRAFO — o material já conferido. É o documento compilado."""
    nb = caderno()
    src = fonte(nb)
    mencionar("KWP2000", nb, FRASE_1, src)
    mencionar("KWP2000", nb, FRASE_3, src)
    falso = fake.extrai([narrativa()])

    compilar(nb, falso)

    enviado = "\n".join(str(m.content) for m in falso.chamadas[0])
    assert "linha K" in enviado, "o trecho do grafo vai junto"
    assert "O ISO 14230 descreve o KWP2000" not in enviado, (
        "o trecho que NÃO está no grafo (só no texto da fonte) não é oferecido ao modelo"
    )


def test_caderno_sem_conceito_ainda_gera_documento_e_nao_chama_o_modelo():
    """Sem grafo não há sobre o que escrever — e o documento sai só com o que é fato."""
    nb = caderno("Vazio")
    fonte(nb)
    falso = fake.extrai([narrativa()])

    doc = compilar(nb, falso)

    assert falso.chamadas == [], "não se chama modelo sem material"
    assert doc.contagem()["modelo"] == 0
    assert "Lacunas abertas" in [s.titulo for s in doc.secoes]
    assert "nenhum" in texto_da(doc, "Lacunas abertas").lower() or "nada" in texto_da(doc, "Lacunas abertas").lower()


def test_a_compilacao_avisa_cada_passo():
    """Um botão que não diz nada por trinta segundos parece quebrado."""
    dados = com_caderno()
    passos: list[str] = []

    async def emitir(passo: str, mensagem: str) -> None:
        assert mensagem, "passo sem mensagem não informa nada"
        passos.append(passo)

    asyncio.run(
        artefato.compilar(dados["nb"], modelo=fake.extrai([narrativa()]), emitir=emitir)
    )

    assert passos[0] == "capa"
    assert "narrativa" in passos
    assert passos[-1] == "pronto"


def test_fontes_do_documento_trazem_o_rendimento_de_cada_uma():
    nb = caderno()
    com = fonte(nb, TEXTO, "Com conteúdo")
    fonte(nb, "Nada aqui foi extraido.\n\nSegunda linha.", "Sem conteúdo")
    mencionar("KWP2000", nb, FRASE_1, com)
    mencionar("KWP2000", nb, FRASE_3, com)

    corpo = texto_da(compilar(nb), "Fontes")

    assert "Com conteúdo" in corpo
    assert "Sem conteúdo" in corpo, "a fonte que não rendeu nada aparece — é o que se quer ver"
    assert "| 1 |" in corpo and "| 2 |" in corpo, "numeradas, na ordem em que o modelo cita"
