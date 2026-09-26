"""App FastAPI do Frutiger LM — casca fina sobre o motor."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from typing import Any
from urllib.parse import quote

from fastapi import Body, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from . import auth, db, ingest, knowledge, model_store, prompts, study
from .config import settings
from .engine import (
    agent,
    artefato,
    checkpoint,
    embed,
    estudo,
    extracao,
    llm,
    oficina,
    similaridade,
)

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
# Login (D069) — a checagem mora aqui, e nenhuma rota sabe que ele existe
# --------------------------------------------------------------------------- #

# O que se alcança sem sessão: a tela de login, o que ela precisa para carregar (a rota
# que recebe a senha e os estáticos) e o logout, que só apaga um cookie.
LIVRES = frozenset({"/login", "/api/login", "/api/logout", "/favicon.ico"})


def _livre(caminho: str) -> bool:
    return caminho in LIVRES or caminho.startswith("/static/")


def _plantar_cookie(resposta: Any, token: str, request: Request) -> None:
    """O crachá. `Secure` entra sozinho quando quem fala é um proxy HTTPS (D069).

    O app não faz TLS — quem hospeda põe nginx/Caddy na frente. O jeito de saber se o
    navegador está falando HTTPS é o `X-Forwarded-Proto`, e é por isso que ele é lido.
    """
    seguro = request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https"
    resposta.set_cookie(
        auth.COOKIE,
        token,
        max_age=auth.TTL,
        httponly=True,       # o JS da página não lê o cookie
        samesite="lax",      # formulário de outro site não carrega a sessão junto
        secure=seguro,
        path="/",
    )


@app.middleware("http")
async def exigir_login(request: Request, call_next: Any) -> Any:
    """Sem sessão, ninguém passa — menos a tela de login.

    Um middleware só, e na frente de tudo (o último registrado é o mais externo). Se a
    checagem fosse por rota, a rota que alguém esquecesse de marcar seria a porta.

    Com o app aberto (sem senha definida) isto é um passe livre — e é o `__main__` que
    recusa subir olhando para a rede nesse estado.
    """
    if not auth.habilitado() or _livre(request.url.path):
        return await call_next(request)

    token = request.cookies.get(auth.COOKIE)
    if auth.sessao_valida(token):
        resposta = await call_next(request)
        # Prazo deslizante: quem usa não é deslogado no meio do trabalho.
        if auth.precisa_renovar(token):
            _plantar_cookie(resposta, auth.criar_sessao(), request)
        return resposta

    # A API responde em JSON (o chat e o painel mostram o motivo); página vira tela de login.
    if request.url.path.startswith("/api/"):
        return JSONResponse(
            {"detail": "Sessão expirada ou ausente. Entre de novo."}, status_code=401
        )
    destino = "/login" + (f"?next={quote(request.url.path)}" if request.url.path != "/" else "")
    return RedirectResponse(destino, status_code=303)


@app.get("/login", include_in_schema=False)
async def pagina_login() -> Any:
    """A tela de login — e, sem senha definida, um atalho de volta para a home."""
    if not auth.habilitado():
        return RedirectResponse("/", status_code=303)
    return FileResponse(STATIC_DIR / "login.html")


@app.post("/api/login")
async def entrar(request: Request, payload: dict[str, Any] = Body(...)) -> Any:
    """Confere a senha e devolve a sessão no cookie (D069).

    `scrypt` do lado de dentro custa dezenas de milissegundos — o que já limita quem
    tenta adivinhar. O freio por origem (5 tentativas, e depois espera que dobra até 15
    minutos) existe porque 50 ms × muitos e muitos palpites ainda é rápido demais.
    """
    if not auth.habilitado():
        raise HTTPException(400, "Este app está aberto: não há senha definida para entrar.")
    origem = request.client.host if request.client else "desconhecido"
    espera = auth.bloqueado(origem)
    if espera > 0:
        raise HTTPException(429, f"Tentativas demais. Espere {int(espera) + 1} segundo(s).")

    if not auth.conferir(str(payload.get("usuario", "")), str(payload.get("senha", ""))):
        auth.registrar_falha(origem)
        raise HTTPException(401, "Usuário ou senha incorretos.")

    auth.limpar_tentativas(origem)
    resposta = JSONResponse({"ok": True, "usuario": auth.usuario()})
    _plantar_cookie(resposta, auth.criar_sessao(), request)
    return resposta


@app.post("/api/logout")
async def sair() -> Any:
    """Sair é parar de apresentar o crachá: sem tabela de sessão, não há o que revogar.

    O que existe é a troca da senha, que troca o segredo da assinatura e derruba de uma
    vez todas as sessões emitidas até ali (D069).
    """
    resposta = JSONResponse({"ok": True})
    resposta.delete_cookie(auth.COOKIE, path="/")
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
        # Se há login e quem é o dono. Só se chega aqui com sessão (ou com o app aberto),
        # então isto não conta nada a quem está fora — e é o que a barra usa para decidir
        # se mostra o "sair" (D069).
        "auth": auth.resumo(),
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
    a chave de quem só quis trocar o modelo. Vale igual para a chave do embedding.

    O bloco de embedding (F6) é **opcional**, mas não é meio-configurável: endereço
    sem modelo (ou o contrário) é recusado, pelo mesmo motivo de sempre. Vazio dos
    dois lados significa "não uso essas arestas".
    """
    cfg = model_store.montar(
        base_url=payload.get("base_url", ""),
        model=payload.get("model", ""),
        api_key=payload.get("api_key"),
        temperature=payload.get("temperature"),
        embed_base_url=payload.get("embed_base_url"),
        embed_model=payload.get("embed_model"),
        embed_api_key=payload.get("embed_api_key"),
    )
    falta = model_store.faltando(cfg)
    if falta:
        raise HTTPException(400, "Falta " + ", ".join(falta) + " para o modelo funcionar.")

    # O embedding só é validado se a pessoa começou a configurá-lo — e aí a régua é a
    # mesma do modelo de conversa: falta nomeada, não estado inutilizável em silêncio.
    parcial = bool(cfg.embed_base_url or cfg.embed_model)
    if parcial and not cfg.embed_configurado:
        raise HTTPException(
            400,
            "Falta " + ", ".join(model_store.faltando_embed(cfg)) + " no bloco de embeddings.",
        )

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


@app.post("/api/settings/embed/test")
async def test_embed_settings() -> dict[str, Any]:
    """O mesmo princípio do teste acima, agora para o modelo de embedding (F6).

    Aqui o teste é um vetor de verdade, e não uma conversa: o que pode falhar é o
    provedor não ter endpoint de embedding nenhum (a DeepSeek não tem), o endereço
    estar errado, ou o nome do modelo não existir naquele servidor. Nenhuma das três
    aparece como erro na tela na hora de ligar por similaridade — apareceria como
    "não criou aresta nenhuma", que é bem pior.
    """
    try:
        embedder = embed.atual()
    except embed.EmbeddingNaoConfigurado as exc:
        raise HTTPException(400, str(exc)) from None

    try:
        vetores = await asyncio.wait_for(
            embedder.aembed_documents(["teste de embedding"]), timeout=TESTE_TIMEOUT_S
        )
    except TimeoutError:
        raise HTTPException(
            504, f"O modelo de embedding não respondeu em {TESTE_TIMEOUT_S:.0f}s."
        ) from None
    except Exception as exc:  # noqa: BLE001 - a mensagem do provedor é o que ajuda
        raise HTTPException(
            502, f"{type(exc).__name__}: {str(exc)[:300]}{llm.explicar(exc)}"
        ) from None

    dimensao = len(vetores[0]) if vetores else 0
    return {
        "ok": True,
        "model": embed.resolve().model,
        "dim": dimensao,
        # A dimensão é a informação útil aqui: ela diz que o provedor respondeu um
        # vetor de verdade, e é ela que tem que ser igual para todos os conceitos.
        "reply": f"{len(vetores)} vetor(es) de {dimensao} dimensões",
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
            if evento == "assistant.completed" and dados.get("content"):
                # D051: os `[n]` que o modelo escreveu viram registro de uso. A
                # numeração aqui é a MESMA que foi no prompt — só as fontes ativas,
                # na ordem de `list_sources` (é o que `build_context` e `listar_fontes`
                # usam). Se divergissem, o uso registrado seria de outra fonte.
                study.registrar_uso_de_citacoes(
                    dados["content"],
                    db.list_sources(notebook_id, active_only=True),
                    thread_id=checkpoint.thread_id(notebook_id),
                )
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


@app.post("/api/notebooks/{notebook_id}/conhecimento")
async def virar_conhecimento(notebook_id: str) -> dict[str, Any]:
    """A última conclusão do chat vira conhecimento no grafo (D068).

    O texto vem do **checkpointer**, e não do corpo do pedido — de propósito. Assim o
    `message_id` é exato (é o id da mensagem que está sendo guardada, não um id achado
    por semelhança de texto) e o que entra no grafo é exatamente o que o modelo
    respondeu: o navegador não tem como mandar outro texto para virar "conhecimento".

    Devolve os conceitos que ficaram ancorados. Zero conceito é resposta legítima — uma
    resposta que não cita nada de novo não inventa nó para ter o que guardar.
    """
    _notebook_or_404(notebook_id)
    # Lê o estado pelo SAVER, e não pelo agente: montar o agente exige modelo
    # configurado, e ler a conversa não exige — quem exige é a extração, três linhas
    # abaixo, com a mensagem de config certa. Sem isto, quem não tivesse modelo
    # configurado receberia "configure o modelo" quando o problema era não haver
    # conclusão nenhuma.
    tupla = await checkpoints.saver.aget_tuple(checkpoint.config(notebook_id))
    valores = (tupla.checkpoint or {}).get("channel_values", {}) if tupla else {}
    mensagens = valores.get("messages", [])

    conclusao = None
    for mensagem in reversed(mensagens):
        if getattr(mensagem, "type", "") == "ai" and str(mensagem.content or "").strip():
            conclusao = mensagem
            break
    if conclusao is None:
        raise HTTPException(400, "Não há conclusão nesta conversa para virar conhecimento.")

    try:
        resumo = await extracao.extrair_conversa(
            notebook_id,
            str(conclusao.content),
            thread_id=checkpoint.thread_id(notebook_id),
            message_id=getattr(conclusao, "id", None),
        )
    except llm.ModeloNaoConfigurado as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 — a mensagem vai para a tela
        log.exception("falha ao virar conhecimento")
        # `explicar` devolve a DICA (ver llm.py) — sem ela o 502 não diz o que fazer.
        raise HTTPException(502, f"{type(exc).__name__}: {exc}{llm.explicar(exc)}") from exc

    return {"notebook_id": notebook_id, **resumo}


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
            if evento == "assistant.completed" and dados.get("content"):
                # No escopo global a numeração é a global (por criação), que é a que
                # `fontes_ativas_globais` e o índice do prompt global usam.
                study.registrar_uso_de_citacoes(
                    dados["content"],
                    db.fontes_ativas_globais(),
                    thread_id=checkpoint.THREAD_GLOBAL,
                )
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
    sem_similaridade: bool = False,
    principalmente: bool = False,
) -> dict[str, Any]:
    """O grafo para desenhar.

    **Sem `notebook_id` é o MAPA**: um nó por caderno, ligando os que dividem conceito.
    Ele é o nível de repouso — a tela abre mostrando os seus cadernos, e é clicando num
    deles que se entra.

    **Com `notebook_id` são os conceitos daquele caderno.** `principalmente=1` mostra só
    os conceitos DO material — os que aparecem mais de uma vez, ou atravessam cadernos.
    Os de passagem continuam no banco (são as lacunas do F4) e o quanto ficou de fora
    volta em `ocultos`.

    Os dois `sem_*` são interruptores de FAMÍLIA de aresta (D063/D065): a
    co-ocorrência e a similaridade são as duas que a pessoa pode querer desligar para
    ler o desenho; a afirmada, não — é ela que o material sustenta, e esconder isso
    seria esconder o que o documento afirma. Cada interruptor existe porque o desenho
    diz quantas linhas ele tirou.
    """
    if not notebook_id:
        # `peso_minimo` e `principalmente` são filtros de CONCEITO: no mapa de cadernos
        # não há o que filtrar — o nó é o caderno.
        return knowledge.grafo_de_cadernos()

    tipos = [
        tipo
        for tipo, desligado in (
            (knowledge.CO_OCORRENCIA, sem_co_ocorrencia),
            (knowledge.SIMILARIDADE, sem_similaridade),
            (knowledge.EXPLICITA, False),
        )
        if not desligado
    ]
    _notebook_or_404(notebook_id)
    return {
        **knowledge.grafo(
            notebook_id=notebook_id,
            peso_minimo=max(1, peso_minimo),
            tipos=tipos,
            apenas_principais=principalmente,
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


@app.get("/api/notebooks/{notebook_id}/parecidos")
async def parecidos(notebook_id: str, limiar: float | None = None) -> list[dict[str, Any]]:
    """Os pares muito parecidos (F6/D066) — suspeita de duplicata, não prova.

    Sai do que o trabalho de similaridade gravou, com um corte mais alto que o das
    arestas. E o corte é alto por um motivo que a medição no material real ensinou: dos
    pares acima de 0,96, nenhum era duplicata — eram conceitos diferentes que
    compartilham a mesma frase de origem. Então isto é uma lista para OLHAR, e quem
    decide mesclar (ou não) continua sendo a pessoa.
    """
    _notebook_or_404(notebook_id)
    corte = similaridade.LIMIAR_MESCLAR if limiar is None else limiar
    return knowledge.parecidos(notebook_id, limiar=corte)


@app.get("/api/conceitos/{concept_id}")
async def ver_conceito(concept_id: str) -> dict[str, Any]:
    """O conceito, o que se liga a ele, as menções com o trecho, e as suas notas."""
    dado = knowledge.vizinhanca(concept_id)
    if not dado:
        raise HTTPException(404, "Conceito não encontrado")
    dado["notas"] = knowledge.notas_do_conceito(concept_id)
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
# Estudo (F4): cards, revisão, lacunas, contradições e notas
# --------------------------------------------------------------------------- #


@app.get("/api/notebooks/{notebook_id}/estudo")
async def painel_de_estudo(notebook_id: str) -> dict[str, Any]:
    """O painel inteiro numa chamada: resumo, lacunas e o que cada fonte deu.

    As lacunas são consulta ao grafo, sem modelo (D049) — por isso podem vir junto e
    de graça, e não escondidas atrás de um botão que gasta dinheiro.
    """
    _notebook_or_404(notebook_id)

    por_fonte = knowledge.conceitos_por_fonte(notebook_id)
    nunca_citadas = {f["id"] for f in study.fontes_nunca_citadas(notebook_id)}
    for fonte in por_fonte:
        fonte["nunca_citada"] = fonte["id"] in nunca_citadas

    return {
        "cards": study.resumo(notebook_id),
        "lacunas": knowledge.lacunas(notebook_id),
        "fontes": por_fonte,
        "grafo": knowledge.estatisticas(),
    }


@app.get("/api/cards")
async def listar_cards(notebook_id: str | None = None, devidos: bool = False) -> list[dict[str, Any]]:
    """Os cards, ou só os vencidos quando `devidos=1`."""
    if devidos:
        return study.devidos(notebook_id)
    if not notebook_id:
        raise HTTPException(400, "Informe o caderno")
    _notebook_or_404(notebook_id)
    return study.listar(notebook_id)


@app.post("/api/cards")
async def criar_card(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    """Card criado à mão. O verso é seu, e nasce devido: se você criou, é para revisar."""
    notebook_id = (payload.get("notebook_id") or "").strip()
    frente = (payload.get("front") or "").strip()
    verso = (payload.get("back") or "").strip()
    if not notebook_id or not frente or not verso:
        raise HTTPException(400, "Informe o caderno, a frente e o verso")
    _notebook_or_404(notebook_id)

    return study.criar_card(
        notebook_id,
        front=frente,
        back=verso,
        concept_id=payload.get("concept_id") or None,
        source_id=payload.get("source_id") or None,
        excerpt=payload.get("excerpt") or "",
    )


@app.post("/api/cards/{card_id}/revisar")
async def revisar_card(card_id: str, payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    """Aplica a nota da revisão e devolve o card reagendado."""
    nota = (payload.get("nota") or "").strip()
    revisado = study.revisar(card_id, nota)
    if not revisado:
        raise HTTPException(404, "Card não encontrado")
    return revisado


@app.delete("/api/cards/{card_id}")
async def apagar_card(card_id: str) -> dict[str, Any]:
    if not study.get_card(card_id):
        raise HTTPException(404, "Card não encontrado")
    study.apagar_card(card_id)
    return {"apagado": card_id}


@app.post("/api/notebooks/{notebook_id}/cards/gerar")
async def gerar_cards(notebook_id: str) -> StreamingResponse:
    """Gera cards dos conceitos, com progresso (D042: ação explícita e paga)."""
    _notebook_or_404(notebook_id)

    async def stream() -> AsyncIterator[str]:
        try:
            llm.atual()
        except llm.ModeloNaoConfigurado as exc:
            yield _sse("error", {"message": str(exc)})
            yield _sse("done", {})
            return

        async for evento in estudo.gerar_cards(notebook_id):
            nome = evento.pop("evento")
            yield _sse(nome, evento)

    return StreamingResponse(stream(), media_type="text/event-stream", headers=SSE_HEADERS)


@app.post("/api/notebooks/{notebook_id}/conflitos")
async def achar_conflitos(notebook_id: str) -> StreamingResponse:
    """Compara as fontes sobre os mesmos conceitos, com progresso (D050)."""
    _notebook_or_404(notebook_id)

    async def stream() -> AsyncIterator[str]:
        try:
            llm.atual()
        except llm.ModeloNaoConfigurado as exc:
            yield _sse("error", {"message": str(exc)})
            yield _sse("done", {})
            return

        async for evento in estudo.detectar_contradicoes(notebook_id):
            nome = evento.pop("evento")
            yield _sse(nome, evento)

    return StreamingResponse(stream(), media_type="text/event-stream", headers=SSE_HEADERS)


@app.post("/api/conceitos/{concept_id}/notas")
async def criar_nota(concept_id: str, payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    if not knowledge.get_conceito(concept_id):
        raise HTTPException(404, "Conceito não encontrado")
    corpo = (payload.get("body") or "").strip()
    if not corpo:
        raise HTTPException(400, "Nota vazia")
    return knowledge.criar_nota(concept_id, corpo, notebook_id=payload.get("notebook_id") or None)


@app.delete("/api/notas/{note_id}")
async def apagar_nota(note_id: str) -> dict[str, Any]:
    if not knowledge.apagar_nota(note_id):
        raise HTTPException(404, "Nota não encontrada")
    return {"apagada": note_id}

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


# --------------------------------------------------------------------------- #
# As tarefas longas: o documento compilado (F5) e as arestas por similaridade (F6)
# --------------------------------------------------------------------------- #
# O mesmo passe serve ao botão, ao download e à impressão. A narração é UMA chamada de
# modelo; todo o resto do documento é consulta ao grafo e ao banco — e é a maior parte
# dele (na prática: 36 das 38 seções do caderno de verdade).
#
# A construção NÃO acontece dentro desta requisição: ela é um run da oficina, com id
# (D059) — e a partir do F6 a oficina é o runner de tarefa longa do app, com dois
# trabalhos e um vocabulário de eventos só (D065).


async def _acompanhar_run(run_id: str) -> AsyncIterator[str]:
    """O run em SSE. Quem sabe o que é `Run` é a oficina; aqui só se traduz."""
    async for item in oficina.oficina.acompanhar(run_id):
        yield _sse(item["evento"], item["dados"])


@app.post("/api/notebooks/{notebook_id}/compilar")
async def compilar_documento(notebook_id: str, sem_modelo: bool = False) -> dict[str, Any]:
    """Dispara a compilação e devolve o run — **sem esperar o documento**.

    Disparar e acompanhar são dois verbos: este só cria o run e volta na hora; quem
    quer ver o documento sendo montado segue `GET /api/trabalhos/{run_id}`. Foi de
    propósito que o botão e o chat usam o MESMO caminho de acompanhamento (D024) — se
    o POST transmitisse o progresso, o painel teria dois códigos de seguir run, e o do
    chat seria o segundo a ser esquecido numa mudança.

    `sem_modelo=true` monta só as seções de fato — conceitos, lacunas, fontes e
    citações — e não gasta chamada nenhuma. Serve para ver a estrutura antes de pagar
    por ela.

    Se já houver uma compilação em curso neste caderno, ela é reaproveitada: o segundo
    clique acompanha a primeira em vez de pagar uma segunda chamada de modelo (D059).
    """
    _notebook_or_404(notebook_id)
    run = oficina.oficina.iniciar(
        notebook_id,
        trabalho=oficina.DOCUMENTO,
        origem="botao",
        parametros={"com_narrativa": not sem_modelo},
    )
    return run.resumo()


@app.post("/api/notebooks/{notebook_id}/similaridade")
async def ligar_por_similaridade(notebook_id: str, limiar: float | None = None) -> dict[str, Any]:
    """Dispara a ligação por similaridade e devolve o run (F6).

    Custa chamadas — uma por conceito que ainda não tem vetor — então é ação
    **explícita**, como a extração (D042). A segunda rodada em diante é de graça: o
    vetor guardado é reusado quando o modelo e o texto do conceito são os mesmos
    (D062).

    `limiar` existe para medir: o valor padrão é o que a medição no caderno real
    escolheu, e poder rodar com outro é o que permite medir de novo quando o material
    mudar. A tela usa o padrão.
    """
    _notebook_or_404(notebook_id)
    run = oficina.oficina.iniciar(
        notebook_id,
        trabalho=oficina.SIMILARIDADE,
        origem="botao",
        parametros={"limiar": limiar} if limiar is not None else {},
    )
    return run.resumo()


@app.get("/api/trabalhos")
async def trabalhos(
    notebook_id: str | None = None, trabalho: str | None = None
) -> list[dict[str, Any]]:
    """As tarefas longas que a tela pode mostrar — terminadas inclusive, por um tempo.

    É por aqui que o painel descobre uma tarefa nascida no CHAT: o botão dispara a sua
    e acompanha direto, mas quando quem pediu foi a ferramenta do agente, o painel não
    fica sabendo de nada — ele precisa perguntar.
    """
    return oficina.oficina.ativos(notebook_id, trabalho=trabalho)


@app.get("/api/trabalhos/{run_id}")
async def acompanhar_trabalho(run_id: str) -> StreamingResponse:
    """Acompanha um run pelo id, tenha ele nascido de onde for. O histórico vem junto."""
    if oficina.oficina.obter(run_id) is None:
        raise HTTPException(
            404, "Tarefa não encontrada — ela sai da lista algum tempo depois de terminar."
        )
    return StreamingResponse(
        _acompanhar_run(run_id), media_type="text/event-stream", headers=SSE_HEADERS
    )


@app.get("/api/notebooks/{notebook_id}/exportar/{formato}")
async def exportar(notebook_id: str, formato: str) -> FileResponse:
    """Os formatos extras do F5, do mesmo pipeline: `anki` e `obsidian`."""
    notebook = _notebook_or_404(notebook_id)
    geradores = {
        "anki": (artefato.anki, "txt", "text/tab-separated-values"),
        "obsidian": (artefato.obsidian, "md", "text/markdown"),
    }
    if formato not in geradores:
        raise HTTPException(404, f"Formato desconhecido: {formato!r}")
    gerar, extensao, media = geradores[formato]
    conteudo = gerar(notebook_id)
    if not conteudo.strip():
        raise HTTPException(400, "Não há o que exportar neste formato ainda.")

    simples = "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in notebook["title"])[:60]
    destino = settings.notebook_dir(notebook_id) / "exports" / f"{simples or notebook_id}.{extensao}"
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(conteudo, encoding="utf-8")
    return FileResponse(destino, media_type=media, filename=destino.name)


@app.get("/imprimir/{output_id}", include_in_schema=False)
async def imprimir(output_id: str) -> FileResponse:
    """A versão para imprimir/salvar em PDF (D014).

    Serve uma página PRÓPRIA, e não o app: o tema Aero é escuro e cheio de painel, e
    imprimir aquilo gasta tinta e sai ilegível. O CSS claro está embutido na página.
    """
    if db.get_output(output_id) is None:
        raise HTTPException(404, "Output não encontrado")
    return FileResponse(STATIC_DIR / "imprimir.html", media_type="text/html")
