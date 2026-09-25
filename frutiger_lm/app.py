"""App FastAPI do Frutiger LM — casca fina sobre o motor."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from typing import Any

from fastapi import Body, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from . import db, ingest, knowledge, model_store, prompts
from .config import settings
from .engine import agent, checkpoint, extracao, llm

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("frutiger")

STATIC_DIR = Path(__file__).resolve().parent / "static"

# Quanto esperar por uma resposta mínima do modelo no botão "Testar".
TESTE_TIMEOUT_S = 30.0

# Ciclo de vida do checkpointer (D019). O agente ainda não consome isto — mas
# ligar agora prova o ciclo no app real e deixa, para quando o agent.py chegar,
# uma única coisa a mudar em vez de duas.
checkpoints = checkpoint.Checkpoints()


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    db.init_db()
    await checkpoints.abrir()
    log.info(
        "Frutiger LM em %s | dados: %s | modelo: %s",
        settings.port,
        settings.data_dir,
        model_store.load().model or "(nao configurado)",
    )
    try:
        yield
    finally:
        await checkpoints.fechar()


app = FastAPI(title="Frutiger LM", version="0.1.0", docs_url="/api/docs", lifespan=lifespan)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def _notebook_or_404(notebook_id: str) -> dict[str, Any]:
    notebook = db.get_notebook(notebook_id)
    if notebook is None:
        raise HTTPException(404, "Caderno não encontrado")
    return notebook


def _sse(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


SSE_HEADERS = {
    "Cache-Control": "no-cache, no-transform",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}


# --------------------------------------------------------------------------- #
# Páginas
# --------------------------------------------------------------------------- #

@app.get("/", include_in_schema=False)
async def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/n/{notebook_id}", include_in_schema=False)
async def notebook_page(notebook_id: str) -> FileResponse:  # noqa: ARG001 (rota exige o nome)
    return FileResponse(STATIC_DIR / "notebook.html")


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.middleware("http")
async def revalidar_estaticos(request: Any, call_next: Any) -> Any:
    """`no-cache` nos estáticos: revalida sempre pelo etag.

    Descoberto na pele: sem cabeçalho nenhum, o navegador aplica cache heurístico e
    continua servindo o CSS antigo depois de um `git pull`. O sintoma é cruel — a
    correção está no disco, o servidor serve a nova, e a tela mostra a velha, então
    o defeito parece ser do código que você acabou de escrever.

    `no-cache` não significa "não guarde": significa "confirme antes de usar". Com
    etag, a confirmação é um 304 barato.
    """
    resposta = await call_next(request)
    if request.url.path.startswith("/static/"):
        resposta.headers["Cache-Control"] = "no-cache"
    return resposta


# --------------------------------------------------------------------------- #
# Status
# --------------------------------------------------------------------------- #

@app.get("/api/status")
async def status() -> dict[str, Any]:
    """Estado do app.

    Antes isto perguntava ao API server do Hermes se estava de pé. Agora o motor é
    daqui de dentro, então o que importa é outra coisa: **se o modelo está
    configurado**. Quem confirma que a chave presta é o botão "Testar conexão" do
    modal — de propósito, para não gastar uma chamada a cada carregamento de tela.
    """
    cfg = model_store.masked()
    return {
        "app": "frutiger-lm",
        "version": app.version,
        "model": {
            "configured": cfg["configured"],
            "name": cfg["model"],
            "base_url": cfg["base_url"],
        },
        "data_dir": str(settings.data_dir),
        "inline_limit": settings.inline_limit,
        "output_templates": {k: v["label"] for k, v in prompts.OUTPUT_TEMPLATES.items()},
    }


# --------------------------------------------------------------------------- #
# Modelo — a API key (D020, D030)
# --------------------------------------------------------------------------- #

@app.get("/api/settings/model")
async def get_model_settings() -> dict[str, Any]:
    """O que a UI pode saber sobre a config de modelo.

    Não inclui a chave, por construção — ver `model_store.masked()`.
    """
    return model_store.masked()


@app.post("/api/settings/model")
async def set_model_settings(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    """Salva a config vinda do formulário, **recusando config incompleta**.

    Recusar não é preciosismo: salvar só a chave, com endereço e modelo em
    branco, produzia um estado que não funciona e não avisa. A pessoa via
    "salvo", fechava o modal, e o chat não funcionava depois — sem pista do
    motivo. Agora o que falta volta nomeado no erro.

    `api_key` ausente significa "não mexi no campo", e preserva a chave salva —
    o formulário devolve ela mascarada, então tratá-la como novo valor apagaria
    a chave de quem só quis trocar o modelo.
    """
    cfg = model_store.montar(
        base_url=payload.get("base_url", ""),
        model=payload.get("model", ""),
        api_key=payload.get("api_key"),
        temperature=payload.get("temperature"),
    )
    falta = model_store.faltando(cfg)
    if falta:
        raise HTTPException(400, "Falta " + ", ".join(falta) + " para o modelo funcionar.")

    model_store.save(cfg)
    return {"configured": cfg.configurado, **model_store.masked()}


@app.post("/api/settings/model/test")
async def test_model_settings() -> dict[str, Any]:
    """Chamada mínima de verdade, para separar "salvei" de "funciona"."""
    try:
        modelo = llm.atual()
    except llm.ModeloNaoConfigurado as exc:
        raise HTTPException(400, str(exc)) from None

    try:
        resposta = await asyncio.wait_for(
            modelo.ainvoke("Responda apenas com a palavra: ok"), timeout=TESTE_TIMEOUT_S
        )
    except TimeoutError:
        raise HTTPException(
            504, f"O modelo não respondeu em {TESTE_TIMEOUT_S:.0f}s. Se for modelo local, ele está rodando?"
        ) from None
    except Exception as exc:  # noqa: BLE001 - a mensagem do provedor é o que ajuda
        raise HTTPException(
            502, f"{type(exc).__name__}: {str(exc)[:300]}{llm.explicar(exc)}"
        ) from None

    return {
        "ok": True,
        "model": llm.resolve().model,
        "reply": str(resposta.content)[:200],
    }


# --------------------------------------------------------------------------- #
# Cadernos
# --------------------------------------------------------------------------- #

@app.get("/api/notebooks")
async def list_notebooks() -> list[dict[str, Any]]:
    return db.list_notebooks()


@app.post("/api/notebooks", status_code=201)
async def create_notebook(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    title = (payload.get("title") or "").strip()
    if not title:
        raise HTTPException(400, "O caderno precisa de um título")
    return db.create_notebook(title, payload.get("description") or "")


@app.get("/api/notebooks/{notebook_id}")
async def get_notebook(notebook_id: str) -> dict[str, Any]:
    notebook = _notebook_or_404(notebook_id)
    notebook["context_mode"] = db.context_mode(notebook, inline_limit=settings.inline_limit)
    return notebook


@app.patch("/api/notebooks/{notebook_id}")
async def patch_notebook(notebook_id: str, payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    _notebook_or_404(notebook_id)
    return db.update_notebook(
        notebook_id,
        title=(payload.get("title") or "").strip() or None,
        description=payload.get("description"),
    )


@app.delete("/api/notebooks/{notebook_id}")
async def delete_notebook(notebook_id: str) -> dict[str, Any]:
    _notebook_or_404(notebook_id)
    # a conversa vai junto: caderno apagado não pode deixar histórico no disco
    await checkpoints.apagar_conversa(notebook_id)
    db.delete_notebook(notebook_id)  # apaga as linhas E os arquivos (ver db.py)
    return {"deleted": notebook_id}


# --------------------------------------------------------------------------- #
# Fontes
# --------------------------------------------------------------------------- #

@app.get("/api/notebooks/{notebook_id}/sources")
async def list_sources(notebook_id: str) -> list[dict[str, Any]]:
    _notebook_or_404(notebook_id)
    return db.list_sources(notebook_id)


@app.post("/api/notebooks/{notebook_id}/sources", status_code=201)
async def add_source(
    notebook_id: str,
    kind: str = Form(...),
    title: str = Form(""),
    url: str = Form(""),
    text: str = Form(""),
    file: UploadFile | None = File(None),
) -> dict[str, Any]:
    _notebook_or_404(notebook_id)
    kind = (kind or "").strip().lower()

    if kind == "pdf" and file is None:
        raise HTTPException(400, "Envie um arquivo PDF.")

    pdf_bytes = None
    pdf_name = ""
    if kind == "pdf":
        pdf_bytes = await file.read()  # type: ignore[union-attr]
        pdf_name = file.filename or "documento.pdf"  # type: ignore[union-attr]
        if len(pdf_bytes) > 60 * 1024 * 1024:
            raise HTTPException(413, "PDF maior que 60 MB.")

    try:
        return await ingest.add_source(
            notebook_id,
            kind=kind,
            origin=url,
            text=text,
            title=title,
            pdf_bytes=pdf_bytes,
            pdf_name=pdf_name,
        )
    except ingest.IngestError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.patch("/api/sources/{source_id}")
async def patch_source(source_id: str, payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    source = db.get_source(source_id)
    if source is None:
        raise HTTPException(404, "Fonte não encontrada")
    if "active" in payload:
        db.set_source_active(source_id, bool(payload["active"]))
    return db.get_source(source_id)  # type: ignore[return-value]


@app.delete("/api/sources/{source_id}")
async def delete_source(source_id: str) -> dict[str, Any]:
    source = db.get_source(source_id)
    if source is None:
        raise HTTPException(404, "Fonte não encontrada")
    if source.get("path"):
        with suppress(OSError):
            Path(source["path"]).unlink(missing_ok=True)
    db.delete_source(source_id)
    return {"deleted": source_id}


# --------------------------------------------------------------------------- #
# Conversa
# --------------------------------------------------------------------------- #

def _agente(notebook: dict[str, Any]) -> Any:
    """O agente deste caderno, com o checkpointer que o lifespan abriu.

    Traduz "modelo não configurado" em 409, que é o código certo: o pedido está
    bem formado, o app é que não tem o que precisa para atender.
    """
    try:
        return agent.montar(notebook["id"], checkpointer=checkpoints.saver)
    except llm.ModeloNaoConfigurado as exc:
        raise HTTPException(409, str(exc)) from exc


@app.get("/api/notebooks/{notebook_id}/messages")
async def get_messages(notebook_id: str) -> list[dict[str, Any]]:
    """A conversa do caderno, direto do checkpointer (D019).

    Antes isto pedia as mensagens ao Hermes e depois as "simplificava" do formato
    dele. Agora vem do mesmo lugar de onde o agente lembra — ou seja, a tela
    mostra exatamente o que ele tem em contexto.
    """
    notebook = _notebook_or_404(notebook_id)
    return await agent.historico(_agente(notebook), checkpoint.config(notebook_id))


@app.post("/api/notebooks/{notebook_id}/chat")
async def chat(notebook_id: str, payload: dict[str, Any] = Body(...)) -> StreamingResponse:
    """A conversa do caderno, pelo motor de casa.

    A tradução do LangGraph para os eventos que a interface consome mora no
    `engine` (`agent.eventos`) — aqui é só encanamento. A interface não mudou.
    """
    notebook = _notebook_or_404(notebook_id)
    user_input = (payload.get("input") or "").strip()
    if not user_input:
        raise HTTPException(400, "Mensagem vazia")

    async def stream() -> AsyncIterator[str]:
        try:
            agente = agent.montar(notebook["id"], checkpointer=checkpoints.saver)
        except llm.ModeloNaoConfigurado as exc:
            yield _sse("error", {"message": str(exc)})
            yield _sse("done", {})
            return

        config = checkpoint.config(notebook_id)
        async for evento, dados in agent.eventos(agente, config, user_input):
            yield _sse(evento, dados)

    return StreamingResponse(stream(), media_type="text/event-stream", headers=SSE_HEADERS)


@app.delete("/api/notebooks/{notebook_id}/chat")
async def reset_chat(notebook_id: str) -> dict[str, Any]:
    """Começa uma conversa nova, sem tocar nas fontes nem no resto do caderno.

    Antes isto criava outra sessão no Hermes. Agora é apagar o thread do
    checkpointer (D019) — a conversa some porque a memória dela sumiu.
    """
    _notebook_or_404(notebook_id)
    await checkpoints.apagar_conversa(notebook_id)
    return {"reset": notebook_id}


# --------------------------------------------------------------------------- #
# Conversa global — todos os cadernos (D023, D039)
# --------------------------------------------------------------------------- #

def _agente_global() -> Any:
    try:
        return agent.montar_global(checkpointer=checkpoints.saver)
    except llm.ModeloNaoConfigurado as exc:
        raise HTTPException(409, str(exc)) from exc


@app.get("/api/global/messages")
async def get_global_messages() -> list[dict[str, Any]]:
    """A conversa do chat global. Um thread só, no mesmo checkpointer (D019)."""
    return await agent.historico(_agente_global(), checkpoint.config_global())


@app.post("/api/global/chat")
async def global_chat(payload: dict[str, Any] = Body(...)) -> StreamingResponse:
    """O chat que enxerga **todos** os cadernos e liga o conhecimento entre eles.

    Mesmas ferramentas do chat do caderno, com outro escopo (D039) — e mesmo
    formato de eventos, então a interface trata igual.
    """
    user_input = (payload.get("input") or "").strip()
    if not user_input:
        raise HTTPException(400, "Mensagem vazia")

    async def stream() -> AsyncIterator[str]:
        try:
            agente = agent.montar_global(checkpointer=checkpoints.saver)
        except llm.ModeloNaoConfigurado as exc:
            yield _sse("error", {"message": str(exc)})
            yield _sse("done", {})
            return

        config = checkpoint.config_global()
        async for evento, dados in agent.eventos(agente, config, user_input):
            yield _sse(evento, dados)

    return StreamingResponse(stream(), media_type="text/event-stream", headers=SSE_HEADERS)


@app.delete("/api/global/chat")
async def reset_global_chat() -> dict[str, Any]:
    """Começa a conversa global do zero. Não toca em caderno nenhum."""
    await checkpoints.apagar_conversa_global()
    return {"reset": "global"}


# --------------------------------------------------------------------------- #
# Grafo de conhecimento (F3)
# --------------------------------------------------------------------------- #
# Tudo aqui passa pelo `knowledge`: a interface e o agente usam a MESMA
# implementação (D024), então o botão "mesclar" e a ferramenta do agente não podem
# divergir no que fazem.


@app.get("/api/grafo")
async def get_grafo(
    notebook_id: str | None = None,
    peso_minimo: int = 1,
    sem_co_ocorrencia: bool = False,
) -> dict[str, Any]:
    """O grafo para desenhar, com filtros."""
    if notebook_id:
        _notebook_or_404(notebook_id)
    return {
        **knowledge.grafo(
            notebook_id=notebook_id,
            peso_minimo=max(1, peso_minimo),
            incluir_co_ocorrencia=not sem_co_ocorrencia,
        ),
        **knowledge.estatisticas(),
        "orfaos": knowledge.orfaos(),
    }


@app.get("/api/conceitos")
async def listar_conceitos(termo: str = "") -> list[dict[str, Any]]:
    """Busca conceitos, ou lista todos quando não há termo."""
    if termo.strip():
        return knowledge.buscar(termo)
    return knowledge.grafo()["nodes"]


@app.get("/api/conceitos/{concept_id}")
async def ver_conceito(concept_id: str) -> dict[str, Any]:
    """O conceito, o que se liga a ele e as menções com o trecho de origem."""
    dado = knowledge.vizinhanca(concept_id)
    if not dado:
        raise HTTPException(404, "Conceito não encontrado")
    return dado


@app.post("/api/conceitos/mesclar")
async def mesclar_conceitos(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    """Funde dois conceitos. As menções migram — a prova não se perde."""
    de = (payload.get("de") or "").strip()
    para = (payload.get("para") or "").strip()
    if not de or not para:
        raise HTTPException(400, "Informe os dois conceitos")
    if de == para:
        raise HTTPException(400, "Os dois conceitos são o mesmo")

    fundido = knowledge.mesclar(de, para)
    if not fundido:
        raise HTTPException(404, "Conceito não encontrado")
    return fundido


@app.post("/api/conceitos/{concept_id}/renomear")
async def renomear_conceito(concept_id: str, payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    """Renomeia. Se o nome novo já existir, mescla em vez de recusar."""
    nome = (payload.get("nome") or "").strip()
    if not nome:
        raise HTTPException(400, "Informe o nome")

    resultado = knowledge.renomear(concept_id, nome)
    if not resultado:
        raise HTTPException(404, "Conceito não encontrado")
    return resultado


@app.delete("/api/conceitos/{concept_id}")
async def apagar_conceito(concept_id: str) -> dict[str, Any]:
    if not knowledge.get_conceito(concept_id):
        raise HTTPException(404, "Conceito não encontrado")
    knowledge.apagar(concept_id)
    return {"apagado": concept_id}


@app.post("/api/notebooks/{notebook_id}/extrair")
async def extrair_conceitos(notebook_id: str) -> StreamingResponse:
    """Extrai os conceitos das fontes do caderno, com progresso na tela.

    É ação explícita (D042), não efeito de adicionar fonte: uma fonte de 50 mil
    caracteres dá cerca de 7 chamadas de modelo, e a conta é da pessoa.

    Streaming porque a extração é longa — prender isso numa requisição sem retorno
    é pedir para a pessoa achar que travou e recarregar no meio.
    """
    _notebook_or_404(notebook_id)

    async def stream() -> AsyncIterator[str]:
        try:
            llm.atual()
        except llm.ModeloNaoConfigurado as exc:
            yield _sse("error", {"message": str(exc)})
            yield _sse("done", {})
            return

        async for evento in extracao.extrair_caderno(notebook_id):
            nome = evento.pop("evento")
            yield _sse(nome, evento)

    return StreamingResponse(stream(), media_type="text/event-stream", headers=SSE_HEADERS)


# --------------------------------------------------------------------------- #
# Outputs
# --------------------------------------------------------------------------- #

@app.get("/api/outputs/templates")
async def list_templates() -> list[dict[str, str]]:
    return [
        {"key": key, "label": value["label"], "hint": value["hint"]}
        for key, value in prompts.OUTPUT_TEMPLATES.items()
    ]


@app.get("/api/notebooks/{notebook_id}/outputs")
async def list_outputs(notebook_id: str) -> list[dict[str, Any]]:
    _notebook_or_404(notebook_id)
    return [
        {k: v for k, v in out.items() if k != "content_md"} | {"chars": len(out.get("content_md") or "")}
        for out in db.list_outputs(notebook_id)
    ]


@app.post("/api/notebooks/{notebook_id}/outputs")
async def generate_output(notebook_id: str, payload: dict[str, Any] = Body(...)) -> StreamingResponse:
    notebook = _notebook_or_404(notebook_id)
    template_key = (payload.get("template") or "").strip()
    if template_key not in prompts.OUTPUT_TEMPLATES:
        raise HTTPException(400, f"Template desconhecido: {template_key!r}")

    template = prompts.OUTPUT_TEMPLATES[template_key]
    system_prompt, user_prompt = prompts.build_output_prompt(notebook, template_key)

    async def stream() -> AsyncIterator[str]:
        yield _sse("output.started", {"template": template_key, "label": template["label"]})
        try:
            resposta = await llm.atual().ainvoke(
                [("system", system_prompt), ("human", user_prompt)]
            )
            content = resposta.content if isinstance(resposta.content, str) else ""
        except llm.ModeloNaoConfigurado as exc:
            yield _sse("error", {"message": str(exc)})
            yield _sse("done", {})
            return
        except Exception as exc:
            log.exception("falha ao gerar output")
            yield _sse(
                "error",
                {"message": f"{type(exc).__name__}: {str(exc)[:300]}{llm.explicar(exc)}"},
            )
            yield _sse("done", {})
            return

        content = (content or "").strip()
        if not content:
            yield _sse("error", {"message": "O motor devolveu um documento vazio."})
            yield _sse("done", {})
            return

        output = db.create_output(
            notebook_id,
            template=template_key,
            title=f"{template['label']} — {notebook['title']}",
            content_md=content,
        )
        yield _sse("output.completed", {
            "id": output["id"],
            "title": output["title"],
            "template": template_key,
            "content_md": content,
        })
        yield _sse("done", {})

    return StreamingResponse(stream(), media_type="text/event-stream", headers=SSE_HEADERS)


@app.get("/api/outputs/{output_id}")
async def get_output(output_id: str) -> dict[str, Any]:
    output = db.get_output(output_id)
    if output is None:
        raise HTTPException(404, "Output não encontrado")
    return output


@app.get("/api/outputs/{output_id}/download")
async def download_output(output_id: str) -> FileResponse:
    output = db.get_output(output_id)
    if output is None:
        raise HTTPException(404, "Output não encontrado")
    safe = "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in output["title"])[:60]
    directory = settings.notebook_dir(output["notebook_id"]) / "outputs"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{safe or output['id']}.md"
    path.write_text(output["content_md"], encoding="utf-8")
    return FileResponse(path, media_type="text/markdown", filename=path.name)


@app.delete("/api/outputs/{output_id}")
async def delete_output(output_id: str) -> dict[str, Any]:
    if db.get_output(output_id) is None:
        raise HTTPException(404, "Output não encontrado")
    db.delete_output(output_id)
    return {"deleted": output_id}
