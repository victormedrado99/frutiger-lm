"""Testes do núcleo do Frutiger LM.

Só a lógica que é nossa: banco, montagem de contexto, ingestão e prompts.
Nada aqui toca a rede nem o motor — por isso roda em milissegundos.
"""

import asyncio
from pathlib import Path

import pytest

from frutiger_lm import db, ingest, prompts
from frutiger_lm.config import settings


def fonte(notebook_id: str, texto: str, titulo: str = "Fonte"):
    """Ingere uma fonte de texto de verdade (grava arquivo + linha)."""
    return asyncio.run(ingest.add_source(notebook_id, kind="text", text=texto, title=titulo))


def ler(notebook_id: str) -> dict:
    """get_notebook com a garantia de que existe (nos testes, sempre existe)."""
    notebook = db.get_notebook(notebook_id)
    assert notebook is not None
    return notebook


def pdf_minimo(texto: str) -> bytes:
    """PDF mínimo mas válido, com texto extraível."""
    stream = f"BT /F1 12 Tf 72 720 Td ({texto}) Tj ET".encode("latin-1")
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
        b"/Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, corpo in enumerate(objs, 1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + corpo + b"\nendobj\n"
    xref_at = len(out)
    out += f"xref\n0 {len(objs) + 1}\n".encode() + b"0000000000 65535 f \n"
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += (
        f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref_at}\n%%EOF\n"
    ).encode()
    return bytes(out)


# --------------------------------------------------------------------- caderno

def test_cria_e_le_caderno():
    nb = db.create_notebook("Direito Constitucional", "prova de novembro")
    assert nb["id"].startswith("nb_")

    lido = ler(nb["id"])
    assert lido["title"] == "Direito Constitucional"
    assert lido["description"] == "prova de novembro"
    assert lido["sources"] == []
    assert lido["outputs"] == []


def test_titulo_em_branco_vira_nome_padrao():
    assert db.create_notebook("   ")["title"] == "Caderno sem nome"


def test_caderno_inexistente_devolve_none():
    assert db.get_notebook("nb_nao_existe") is None


def test_listar_traz_contagens():
    nb = db.create_notebook("X")
    fonte(nb["id"], "um texto curto")
    db.create_output(nb["id"], "resumo", "R", "conteudo")

    [listado] = db.list_notebooks()
    assert listado["source_count"] == 1
    assert listado["output_count"] == 1


def test_apagar_caderno_leva_junto_fontes_e_outputs():
    nb = db.create_notebook("X")
    fonte(nb["id"], "texto")
    db.create_output(nb["id"], "resumo", "R", "conteudo")

    db.delete_notebook(nb["id"])

    assert db.get_notebook(nb["id"]) is None
    assert db.list_sources(nb["id"]) == []
    assert db.list_outputs(nb["id"]) == []


# ---------------------------------------------------------------------- fontes

def test_alternar_fonte_no_contexto():
    nb = db.create_notebook("X")
    src = fonte(nb["id"], "texto")

    assert src["active"] == 1
    assert db.set_source_active(src["id"], False)["active"] == 0
    assert db.list_sources(nb["id"], active_only=True) == []
    assert db.set_source_active(src["id"], True)["active"] == 1


def test_apagar_fonte_devolve_o_caderno():
    nb = db.create_notebook("X")
    src = fonte(nb["id"], "texto")

    assert db.delete_source(src["id"]) == nb["id"]
    assert db.delete_source(src["id"]) is None


def test_chars_da_fonte_e_o_tamanho_real_do_arquivo():
    """Invariante que faz `context_mode` e `build_context` medirem o mesmo."""
    nb = db.create_notebook("X")
    src = fonte(nb["id"], "conteudo curto")

    no_disco = Path(src["path"]).read_text(encoding="utf-8")
    assert src["chars"] == len(no_disco)
    assert src["chars"] > len("conteudo curto")  # o cabeçalho conta


# -------------------------------------------------------------------- contexto

def test_modo_vazio_sem_fontes():
    nb = db.create_notebook("X")
    assert db.context_mode(nb, inline_limit=24000) == "empty"


def test_modo_inline_com_fonte_pequena():
    nb = db.create_notebook("X")
    fonte(nb["id"], "texto pequeno")
    assert db.context_mode(ler(nb["id"]), inline_limit=24000) == "inline"


def test_modo_files_com_fonte_grande():
    nb = db.create_notebook("X")
    fonte(nb["id"], "x" * 30000)
    assert db.context_mode(ler(nb["id"]), inline_limit=24000) == "files"


def test_fonte_desligada_sai_do_contexto():
    nb = db.create_notebook("X")
    src = fonte(nb["id"], "x" * 30000)
    db.set_source_active(src["id"], False)

    assert db.context_mode(ler(nb["id"]), inline_limit=24000) == "empty"
    assert db.build_context(ler(nb["id"]), inline_limit=24000) == ("", [])


def test_contexto_inline_traz_o_texto_e_o_indice():
    nb = db.create_notebook("X")
    fonte(nb["id"], "A capital da Australia e Canberra.")

    ctx, usadas = db.build_context(ler(nb["id"]), inline_limit=24000)

    assert len(usadas) == 1
    assert "[1] Fonte" in ctx
    assert "Canberra" in ctx


def test_contexto_de_modo_files_entrega_o_id_e_nao_o_texto():
    """Mudou na migração para o motor próprio.

    Antes o contexto entregava o CAMINHO do arquivo, porque quem lia era o Hermes
    (read_file/grep). As ferramentas do motor aceitam **id de fonte**, então
    caminho virou ruído: o modelo não tem o que fazer com ele.
    """
    nb = db.create_notebook("X")
    src = fonte(nb["id"], "x" * 30000)

    ctx, usadas = db.build_context(ler(nb["id"]), inline_limit=24000)

    assert len(usadas) == 1
    assert src["id"] in ctx  # o agente recebe o ID
    assert src["path"] not in ctx  # e não o caminho no disco
    assert "x" * 200 not in ctx  # e não o conteúdo
    assert "buscar_nas_fontes" in ctx  # e sabe por onde ler


def test_ler_fonte_ausente_devolve_vazio():
    assert db.read_source_text({"path": ""}) == ""
    assert db.read_source_text({"path": "/caminho/que/nao/existe.txt"}) == ""


# -------------------------------------------- apagar leva os arquivos junto


def test_apagar_caderno_apaga_os_arquivos_dele():
    """A invariante que estava partida entre camadas.

    As linhas saíam no db e os arquivos ficavam para trás, porque quem os removia
    era a rota. Qualquer outro chamador (script, rotina de limpeza) vazava pasta —
    o que aconteceu de verdade, num teste com modelo real.
    """
    nb = db.create_notebook("Some inteiro")["id"]
    info = fonte(nb, "material da fonte")
    arquivo = Path(info["path"])
    assert arquivo.exists()

    db.delete_notebook(nb)

    assert db.get_notebook(nb) is None
    assert not arquivo.exists()
    assert not arquivo.parent.parent.exists(), "a pasta do caderno ficou no disco"


def test_apagar_fonte_apaga_o_arquivo_dela():
    nb = db.create_notebook("Caderno que fica")["id"]
    info = fonte(nb, "material que vai embora")
    arquivo = Path(info["path"])
    assert arquivo.exists()

    db.delete_source(info["id"])

    assert not arquivo.exists()
    assert db.get_notebook(nb) is not None, "o caderno não deveria sumir junto"


def test_o_apagador_recusa_caminho_fora_do_diretorio_de_dados(tmp_path):
    """A guarda: `path` vem do banco. Um registro corrompido não pode virar
    `unlink` em qualquer lugar do disco."""
    fora = tmp_path / "importante.txt"
    fora.write_text("não era para ser apagado", encoding="utf-8")

    db._apagar_arquivo(str(fora))

    assert fora.exists(), "apagou arquivo fora do diretório de dados"


def test_clean_text_colapsa_espacos_e_linhas():
    assert ingest.clean_text("a\r\n\r\n\r\n\r\nb") == "a\n\nb"
    assert ingest.clean_text("muito     espaço") == "muito espaço"


@pytest.mark.parametrize(
    "url",
    [
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        "https://youtu.be/dQw4w9WgXcQ",
        "https://www.youtube.com/shorts/dQw4w9WgXcQ",
        "https://www.youtube.com/embed/dQw4w9WgXcQ",
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=42s",
    ],
)
def test_reconhece_link_de_video(url):
    assert ingest.is_youtube(url)


@pytest.mark.parametrize(
    "url",
    ["https://exemplo.com/video", "https://youtube.com/", "https://en.wikipedia.org/wiki/X"],
)
def test_nao_confunde_pagina_comum_com_video(url):
    assert not ingest.is_youtube(url)


def test_ingere_texto_e_grava_arquivo():
    nb = db.create_notebook("X")
    src = asyncio.run(ingest.add_source(nb["id"], kind="text", text="Um fato importante."))

    assert src["kind"] == "text"
    assert src["title"] == "Um fato importante."
    assert "Um fato importante." in Path(src["path"]).read_text(encoding="utf-8")


def test_titulo_longo_e_encurtado():
    nb = db.create_notebook("X")
    src = asyncio.run(ingest.add_source(nb["id"], kind="text", text="palavra " * 40))
    assert len(src["title"]) <= 61


def test_recusa_texto_vazio():
    nb = db.create_notebook("X")
    with pytest.raises(ingest.IngestError, match="Texto vazio"):
        asyncio.run(ingest.add_source(nb["id"], kind="text", text="   \n  "))


def test_recusa_link_vazio():
    nb = db.create_notebook("X")
    with pytest.raises(ingest.IngestError, match="Informe o link"):
        asyncio.run(ingest.add_source(nb["id"], kind="url", origin=""))


def test_recusa_tipo_desconhecido():
    nb = db.create_notebook("X")
    with pytest.raises(ingest.IngestError, match="desconhecido"):
        asyncio.run(ingest.add_source(nb["id"], kind="planilha"))


def test_recusa_pdf_sem_arquivo():
    nb = db.create_notebook("X")
    with pytest.raises(ingest.IngestError, match="Nenhum arquivo"):
        asyncio.run(ingest.add_source(nb["id"], kind="pdf"))


def test_extrai_texto_de_pdf():
    _, texto = ingest._extract_pdf_text(pdf_minimo("O indice de conversao subiu para 37 por cento"))
    assert "37" in texto


def test_ingere_pdf_usa_o_nome_do_arquivo_como_titulo():
    nb = db.create_notebook("X")
    src = asyncio.run(
        ingest.add_source(
            nb["id"],
            kind="pdf",
            pdf_bytes=pdf_minimo("O indice de conversao subiu para 42 por cento em julho."),
            pdf_name="relatorio.pdf",
        )
    )

    assert src["kind"] == "pdf"
    assert src["title"] == "relatorio"
    assert "42" in Path(src["path"]).read_text(encoding="utf-8")


def test_recusa_pdf_digitalizado_com_mensagem_certa():
    """PDF sem texto extraível precisa dizer que é caso de OCR, não 'deu erro'."""
    nb = db.create_notebook("X")
    with pytest.raises(ingest.IngestError, match="OCR"):
        asyncio.run(
            ingest.add_source(nb["id"], kind="pdf", pdf_bytes=pdf_minimo("x"), pdf_name="scan.pdf")
        )


# --------------------------------------------------------------------- prompts

def test_sete_templates():
    assert set(prompts.OUTPUT_TEMPLATES) == {
        "resumo",
        "guia",
        "faq",
        "linha-do-tempo",
        "mapa",
        "comparativo",
        "plano",
    }
    for tpl in prompts.OUTPUT_TEMPLATES.values():
        assert tpl["label"] and tpl["hint"] and tpl["prompt"]


def test_prompt_do_caderno_traz_regras_e_fontes():
    nb = db.create_notebook("Constituicao")
    fonte(nb["id"], "A capital da Australia e Canberra.")

    prompt = prompts.build_notebook_prompt(ler(nb["id"]))

    assert "Canberra" in prompt
    assert "## Fontes ativas (1)" in prompt
    assert "[1]" in prompt
    assert "Nunca invente" in prompt


def test_prompt_do_caderno_avisa_quando_nao_ha_fonte():
    prompt = prompts.build_notebook_prompt(db.create_notebook("Vazio"))
    assert "ainda não tem fontes ativas" in prompt


def test_prompt_de_output_pede_so_o_documento_e_leva_as_fontes():
    nb = db.create_notebook("X")
    fonte(nb["id"], "A capital da Australia e Canberra.")

    system, user = prompts.build_output_prompt(ler(nb["id"]), "resumo")

    assert "apenas o documento final" in system
    assert "## Fontes do caderno (1)" in system
    assert "Canberra" in system
    assert "Resumo executivo" in user


def test_template_desconhecido_levanta_keyerror():
    nb = db.create_notebook("X")
    with pytest.raises(KeyError):
        prompts.build_output_prompt(nb, "nao-existe")


# --------------------------------------------------------------------- config


def test_defaults_de_configuracao():
    assert settings.inline_limit == 24000
    assert settings.db_path.parent == settings.data_dir
    assert settings.notebook_dir("nb_x") == settings.notebooks_dir / "nb_x"
