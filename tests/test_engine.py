"""Testes do motor e da configuração de modelo.

Nada aqui toca a rede: os modelos falsos vêm de `engine.fake`, e é justamente
por isso que a config de modelo precisa ser um arquivo isolado (o conftest aponta
FRUTIGER_DATA_DIR para um diretório temporário).
"""

from __future__ import annotations

import asyncio
import json
import os
import stat

import pytest

from frutiger_lm import model_store
from frutiger_lm.config import settings
from frutiger_lm.engine import checkpoint, fake, llm


@pytest.fixture(autouse=True)
def estado_limpo():
    """Cada teste começa sem config de modelo e sem checkpoints."""
    alvos = [
        settings.data_dir / "model.json",
        settings.data_dir / "checkpoints.db",
        settings.data_dir / "checkpoints.db-wal",
        settings.data_dir / "checkpoints.db-shm",
    ]
    for alvo in alvos:
        alvo.unlink(missing_ok=True)
    yield
    for alvo in alvos:
        alvo.unlink(missing_ok=True)


# ------------------------------------------------------------------ model_store


def test_salvar_e_ler_redondo():
    cfg = model_store.apply("https://api.exemplo.com/v1", "modelo-x", "sk-chave", 0.5)
    lido = model_store.load()
    assert lido.base_url == "https://api.exemplo.com/v1"
    assert lido.model == "modelo-x"
    assert lido.temperature == 0.5
    assert cfg.api_key == "sk-chave"


def test_arquivo_fica_com_permissao_0600():
    """A chave é segredo: o arquivo não pode ser legível por outros usuários."""
    model_store.apply("https://api.exemplo.com/v1", "m", "sk-segredo", None)
    modo = stat.S_IMODE(os.stat(settings.data_dir / "model.json").st_mode)
    assert modo == 0o600, f"esperado 0600, veio {oct(modo)}"


def test_a_chave_nao_sai_para_a_ui():
    """Regra 1 do model_store: o navegador nunca recebe o valor."""
    model_store.apply("https://api.exemplo.com/v1", "m", "sk-segredo-123456", None)
    visivel = model_store.masked()
    assert visivel["has_key"] is True
    assert "sk-segredo-123456" not in json.dumps(visivel)
    assert visivel["key_hint"].startswith("sk-s")
    assert visivel["key_hint"].endswith("3456")
    assert "•" in visivel["key_hint"]


def test_salvar_sem_tocar_na_chave_preserva_a_chave():
    """Pegadinha real: o campo vem mascarado da UI.

    Se `api_key=None` apagasse a chave, salvar o formulário sem redigitar
    destruiria a configuração de quem só quis mudar o modelo.
    """
    model_store.apply("https://api.exemplo.com/v1", "m", "sk-guardada", None)
    model_store.apply("https://api.exemplo.com/v1", "outro-modelo", None, None)
    lido = model_store.load()
    assert lido.api_key == "sk-guardada"
    assert lido.model == "outro-modelo"


def test_base_url_local_nao_exige_chave():
    """LM Studio e llama.cpp ignoram chave (D020)."""
    local = model_store.ModelConfig(base_url="http://127.0.0.1:1234/v1", model="qwen")
    assert local.precisa_de_chave is False
    assert local.configurado is True

    remoto = model_store.ModelConfig(base_url="https://api.exemplo.com/v1", model="gpt")
    assert remoto.precisa_de_chave is True
    assert remoto.configurado is False  # falta a chave


def test_barra_final_da_url_e_normalizada():
    cfg = model_store.apply("https://api.exemplo.com/v1/", "m", "k", None)
    assert cfg.base_url == "https://api.exemplo.com/v1"


def test_arquivo_corrompido_nao_explode():
    (settings.data_dir / "model.json").write_text("{isso não é json", encoding="utf-8")
    assert model_store.load().configurado is False


def test_presets_cobrem_api_e_local():
    nomes = set(model_store.PRESETS)
    assert {"deepseek", "openai", "lmstudio", "llamacpp"} <= nomes
    for _, (url, _modelo) in model_store.PRESETS.items():
        assert url.startswith("http")


# ------------------------------------------------------------------------ llm


def test_build_sem_config_reclama_dizendo_o_que_falta():
    with pytest.raises(llm.ModeloNaoConfigurado) as exc:
        llm.build(model_store.ModelConfig())
    msg = str(exc.value)
    assert "base_url" in msg and "modelo" in msg


def test_build_local_funciona_sem_chave():
    """O caminho do llama.cpp: endereço local, nenhuma chave."""
    modelo = llm.build(model_store.ModelConfig(base_url="http://127.0.0.1:8080/v1", model="local"))
    assert modelo.model_name == "local"


def test_build_remoto_sem_chave_reclama():
    with pytest.raises(llm.ModeloNaoConfigurado, match="chave"):
        llm.build(model_store.ModelConfig(base_url="https://api.exemplo.com/v1", model="gpt"))


def test_resolve_prefere_o_que_a_ui_salvou(monkeypatch):
    monkeypatch.setenv("LLM_AGENT", "openai|http://do-env/v1|modelo-do-env|k")
    model_store.apply("https://api.exemplo.com/v1", "modelo-da-ui", "k2", None)
    assert llm.resolve().model == "modelo-da-ui"


def test_resolve_cai_no_env_quando_a_ui_esta_vazia(monkeypatch):
    monkeypatch.setenv("LLM_AGENT", "openai|http://do-env/v1|modelo-do-env|chave-do-env")
    cfg = llm.resolve()
    assert cfg.base_url == "http://do-env/v1"
    assert cfg.model == "modelo-do-env"
    assert cfg.api_key == "chave-do-env"


def test_spec_do_env_ignora_string_malformada(monkeypatch):
    monkeypatch.setenv("LLM_AGENT", "openai|só-duas-partes")
    assert model_store.spec_do_env() is None


# ----------------------------------------------------------------------- fake


def test_fake_responde_o_texto_pedido():
    modelo = fake.responde("eco")
    assert modelo.invoke("oi").content == "eco"


def test_fake_emite_tool_call_antes_da_resposta():
    """O teste que valida a premissa do `com_ferramenta`.

    Se o GenericFakeChatModel não propagasse `tool_calls`, todo teste de laço de
    agente que a gente escrever seria falso-verde.
    """
    modelo = fake.com_ferramenta("buscar", {"q": "x"}, "achei")
    primeira = modelo.invoke("pergunta")
    assert primeira.tool_calls, "o fake não emitiu tool call"
    assert primeira.tool_calls[0]["name"] == "buscar"
    assert primeira.tool_calls[0]["args"] == {"q": "x"}
    assert modelo.invoke("continua").content == "achei"


# ------------------------------------------------------------------- rotas


def test_rota_de_modelo_nao_vaza_a_chave(cliente):
    """A regra de segurança, verificada pela borda HTTP."""
    cliente.post(
        "/api/settings/model",
        json={"base_url": "https://api.exemplo.com/v1", "model": "m", "api_key": "sk-super-secreta"},
    )
    resp = cliente.get("/api/settings/model")
    assert resp.status_code == 200
    corpo = resp.json()
    assert corpo["has_key"] is True
    assert corpo["configured"] is True
    assert "sk-super-secreta" not in resp.text


def test_rota_de_modelo_traz_os_presets(cliente):
    presets = cliente.get("/api/settings/model").json()["presets"]
    assert {"deepseek", "openai", "lmstudio", "llamacpp"} <= set(presets)
    assert presets["lmstudio"]["base_url"].startswith("http://127.0.0.1")


def test_salvar_pela_rota_sem_chave_preserva_a_que_existe(cliente):
    """O formulário devolve o campo de chave vazio; salvar não pode apagar."""
    cliente.post(
        "/api/settings/model",
        json={"base_url": "https://api.exemplo.com/v1", "model": "m", "api_key": "sk-guardada"},
    )
    cliente.post(
        "/api/settings/model",
        json={"base_url": "https://api.exemplo.com/v1", "model": "outro"},  # sem api_key
    )
    assert model_store.load().api_key == "sk-guardada"
    assert model_store.load().model == "outro"


def test_testar_sem_configuracao_responde_400_explicando(cliente):
    resp = cliente.post("/api/settings/model/test")
    assert resp.status_code == 400
    assert "base_url" in resp.json()["detail"]


def test_testar_usa_o_modelo_configurado(cliente, monkeypatch):
    """Com um modelo falso no lugar do real: a rota é exercitada de verdade."""
    monkeypatch.setattr("frutiger_lm.engine.llm.atual", lambda: fake.responde("ok"))
    cliente.post(
        "/api/settings/model",
        json={"base_url": "http://127.0.0.1:1234/v1", "model": "local"},
    )
    resp = cliente.post("/api/settings/model/test")
    assert resp.status_code == 200
    assert resp.json() == {"ok": True, "model": "local", "reply": "ok"}


def test_testar_propaga_o_erro_do_provedor(cliente, monkeypatch):
    """Chave errada tem de aparecer na tela com a mensagem do provedor."""

    class Explode:
        async def ainvoke(self, *_a, **_k):
            raise RuntimeError("401 Incorrect API key provided")

    monkeypatch.setattr("frutiger_lm.engine.llm.atual", Explode)
    cliente.post(
        "/api/settings/model",
        json={"base_url": "https://api.exemplo.com/v1", "model": "m", "api_key": "k"},
    )
    resp = cliente.post("/api/settings/model/test")
    assert resp.status_code == 502
    detalhe = resp.json()["detail"]
    assert "401" in detalhe
    assert "RuntimeError" in detalhe
    assert "recusada" in detalhe, "a mensagem crua do provedor não ajuda ninguém"


def test_dica_de_falha_aponta_o_servidor_local_quando_o_endereco_e_local(cliente):
    """O erro mais comum de todos: esqueceu o LM Studio desligado."""
    cliente.post(
        "/api/settings/model",
        json={"base_url": "http://127.0.0.1:1234/v1", "model": "local"},
    )
    dica = llm.explicar(RuntimeError("Connection error."))
    assert ":1234" in dica and "LM Studio" in dica


def test_faltando_nomeia_o_que_falta():
    assert model_store.faltando(model_store.ModelConfig()) == ["endereço", "modelo", "chave da API"]
    assert model_store.faltando(
        model_store.ModelConfig(base_url="http://127.0.0.1:1234/v1", model="m")
    ) == []
    assert model_store.faltando(
        model_store.ModelConfig(base_url="https://api.exemplo.com/v1", model="m")
    ) == ["chave da API"]


def test_salvar_so_a_chave_e_recusado_e_NAO_grava(cliente):
    """O bug que apareceu no uso real.

    O caminho natural — abrir o modal, colar a chave, clicar em Salvar — deixava
    endereço e modelo em branco. Antes: salvava em silêncio e o chat não
    funcionava depois. Agora: recusa nomeando o que falta, e **nada é gravado**,
    para não deixar um estado meio-configurado no disco.
    """
    resp = cliente.post("/api/settings/model", json={"api_key": "sk-so-a-chave-123456"})
    assert resp.status_code == 400
    detalhe = resp.json()["detail"]
    assert "endereço" in detalhe and "modelo" in detalhe

    # nem a chave foi gravada: validar vem antes de escrever
    assert model_store.load().api_key == ""
    assert (settings.data_dir / "model.json").exists() is False


def test_config_incompleta_nao_deixa_o_arquivo_pela_metade(cliente):
    """Uma config boa seguida de uma tentativa incompleta não pode estragar a boa."""
    cliente.post(
        "/api/settings/model",
        json={"base_url": "https://api.exemplo.com/v1", "model": "m", "api_key": "sk-boa"},
    )
    resp = cliente.post("/api/settings/model", json={"model": "outro"})  # sem endereço
    assert resp.status_code == 400
    # a config boa continua intacta
    assert model_store.load().base_url == "https://api.exemplo.com/v1"
    assert model_store.load().api_key == "sk-boa"
    assert model_store.load().model == "m"


def test_config_completa_pela_rota_e_aceita(cliente):
    resp = cliente.post(
        "/api/settings/model",
        json={
            "base_url": "https://api.deepseek.com/v1",
            "model": "deepseek-chat",
            "api_key": "sk-completa",
            "temperature": 0.3,
        },
    )
    assert resp.status_code == 200
    corpo = resp.json()
    assert corpo["configured"] is True
    assert corpo["temperature"] == 0.3
    assert "sk-completa" not in resp.text


# --------------------------------------------------------------- checkpointer


def _grafo_minimo(saver):
    """Grafo de um nó só, sem LLM: existe para exercitar a persistência (D019)."""
    from typing import TypedDict

    from langgraph.graph import END, START, StateGraph

    class Estado(TypedDict):
        n: int

    def somar(estado: Estado) -> Estado:
        return {"n": estado["n"] + 1}

    g = StateGraph(Estado)
    g.add_node("somar", somar)
    g.add_edge(START, "somar")
    g.add_edge("somar", END)
    return g.compile(checkpointer=saver)


def test_thread_id_e_por_caderno():
    assert checkpoint.thread_id("nb_1") == "caderno:nb_1"
    assert checkpoint.thread_id("nb_1") != checkpoint.thread_id("nb_2")


def test_o_arquivo_do_checkpointer_e_separado_do_app():
    """D033: o schema é da biblioteca; não se mistura com as nossas tabelas."""
    assert checkpoint.caminho().endswith("checkpoints.db")
    assert checkpoint.caminho() != str(settings.db_path)


def test_saver_reclama_se_ninguem_abriu():
    """Erro explícito em vez de `None` estourando longe da causa."""
    with pytest.raises(RuntimeError, match="lifespan"):
        _ = checkpoint.Checkpoints().saver


def test_estado_persiste_entre_conexoes():
    """O teste central da D019: a conversa sobrevive à reconexão.

    Sem LLM nenhum — se isto passa, a persistência funciona e o problema que
    sobrar (se sobrar) está no agente, não aqui.
    """

    async def ida_e_volta() -> None:
        cfg = {"configurable": {"thread_id": checkpoint.thread_id("nb_1")}}

        async with checkpoint.aberto() as saver:
            grafo = _grafo_minimo(saver)
            await grafo.ainvoke({"n": 41}, cfg)
            assert (await grafo.aget_state(cfg)).values["n"] == 42

        # conexão NOVA, mesmo arquivo: é isto que prova durabilidade
        async with checkpoint.aberto() as saver:
            grafo = _grafo_minimo(saver)
            assert (await grafo.aget_state(cfg)).values["n"] == 42

    asyncio.run(ida_e_volta())


def test_cadernos_diferentes_nao_se_misturam():
    """Um caderno = um thread. Se vazar, uma conversa aparece na outra."""

    async def dois_cadernos() -> None:
        async with checkpoint.aberto() as saver:
            grafo = _grafo_minimo(saver)
            a = {"configurable": {"thread_id": checkpoint.thread_id("nb_a")}}
            b = {"configurable": {"thread_id": checkpoint.thread_id("nb_b")}}
            await grafo.ainvoke({"n": 10}, a)
            await grafo.ainvoke({"n": 500}, b)
            assert (await grafo.aget_state(a)).values["n"] == 11
            assert (await grafo.aget_state(b)).values["n"] == 501

    asyncio.run(dois_cadernos())
