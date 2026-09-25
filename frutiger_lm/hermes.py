"""Cliente do motor: o API server do gateway do Hermes Agent.

Contrato usado (confirmado no código do Hermes v0.18.x):

  POST /api/sessions                      -> cria sessão (vira "notebook")
  GET  /api/sessions/{id}/messages        -> histórico persistido
  DELETE /api/sessions/{id}
  POST /api/sessions/{id}/chat/stream     -> SSE: run.started, assistant.delta,
                                             tool.started/completed, tool.progress,
                                             assistant.completed, run.completed, error, done
  POST /v1/chat/completions               -> one-shot SEM estado (usado nos outputs)
  GET  /health, /v1/capabilities, /v1/toolsets

O `system_message` do chat/stream é efêmero: entra no prompt do turno mas não é
persistido no histórico. É exatamente por onde injetamos as fontes do caderno.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import httpx

from .config import settings

TIMEOUT = httpx.Timeout(connect=10.0, read=600.0, write=60.0, pool=10.0)


class HermesError(RuntimeError):
    """Erro vindo do motor, já com mensagem legível."""


def _offline(exc: Exception) -> HermesError:
    return HermesError(
        f"Não consegui falar com o motor em {settings.hermes_url} ({type(exc).__name__}). "
        "O gateway do Hermes está rodando? Veja com `hermes gateway status`."
    )


@asynccontextmanager
async def _client() -> AsyncIterator[httpx.AsyncClient]:
    """Cliente HTTP que traduz falha de transporte em HermesError.

    Sem isso, gateway fora do ar vira `httpx.ConnectError` cru e explode como
    500 em quem só queria mostrar "motor fora do ar" na tela.
    """
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            yield client
    except httpx.HTTPError as exc:
        raise _offline(exc) from None


def _headers() -> dict[str, str]:
    headers = {
        "Authorization": f"Bearer {settings.hermes_key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    if settings.session_key:
        headers["X-Hermes-Session-Key"] = settings.session_key
    return headers


def _explain(status: int, body: str) -> str:
    if status == 401:
        return (
            "Motor recusou a chave (401). Confira se HERMES_KEY no .env do Caderno "
            "é igual ao API_SERVER_KEY em ~/.hermes/.env."
        )
    if status == 404:
        return "Rota não encontrada no motor — confira a versão do Hermes e HERMES_URL."
    try:
        payload = json.loads(body)
        msg = payload.get("error", {}).get("message") if isinstance(payload.get("error"), dict) else None
        msg = msg or payload.get("message") or payload.get("detail")
    except Exception:
        msg = None
    return msg or f"Motor respondeu HTTP {status}: {body[:300]}"


async def health() -> dict[str, Any]:
    """Nunca levanta: é daqui que a UI tira o "motor fora do ar"."""
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            resp = await client.get(f"{settings.hermes_url}/health")
            return {"ok": resp.status_code == 200, "status": resp.status_code, "body": resp.text[:400]}
    except httpx.HTTPError as exc:
        return {
            "ok": False,
            "status": None,
            "url": settings.hermes_url,
            "error": f"{type(exc).__name__}: {exc}"[:200],
        }


async def capabilities() -> dict[str, Any]:
    async with _client() as client:
        resp = await client.get(f"{settings.hermes_url}/v1/capabilities", headers=_headers())
        if resp.status_code != 200:
            raise HermesError(_explain(resp.status_code, resp.text))
        return resp.json()


# --------------------------------------------------------------------------- #
# Sessões (um caderno = uma sessão)
# --------------------------------------------------------------------------- #

async def create_session(title: str) -> str:
    async with _client() as client:
        resp = await client.post(
            f"{settings.hermes_url}/api/sessions", headers=_headers(), json={"title": title}
        )
        if resp.status_code >= 300:
            raise HermesError(_explain(resp.status_code, resp.text))
        data = resp.json()
    session = data.get("session") or data
    sid = session.get("id") or session.get("session_id")
    if not sid:
        raise HermesError(f"Motor não devolveu id de sessão: {json.dumps(data)[:300]}")
    return sid


async def delete_session(session_id: str) -> None:
    async with _client() as client:
        await client.delete(f"{settings.hermes_url}/api/sessions/{session_id}", headers=_headers())


async def rename_session(session_id: str, title: str) -> None:
    async with _client() as client:
        await client.patch(
            f"{settings.hermes_url}/api/sessions/{session_id}",
            headers=_headers(),
            json={"title": title},
        )


async def list_messages(session_id: str) -> list[dict[str, Any]]:
    async with _client() as client:
        resp = await client.get(
            f"{settings.hermes_url}/api/sessions/{session_id}/messages", headers=_headers()
        )
        if resp.status_code == 404:
            return []
        if resp.status_code >= 300:
            raise HermesError(_explain(resp.status_code, resp.text))
        data = resp.json()
    if isinstance(data, list):
        return data
    return data.get("messages") or data.get("data") or []


# --------------------------------------------------------------------------- #
# Conversa com streaming
# --------------------------------------------------------------------------- #

async def chat_stream(
    session_id: str, user_input: str, system_message: str | None = None
) -> AsyncIterator[tuple[str, dict[str, Any]]]:
    """Consome o SSE do motor e devolve (evento, payload) par a par."""
    payload: dict[str, Any] = {"input": user_input}
    if system_message:
        payload["system_message"] = system_message

    async with _client() as client, client.stream(
        "POST",
        f"{settings.hermes_url}/api/sessions/{session_id}/chat/stream",
        headers=_headers(),
        json=payload,
    ) as resp:
        if resp.status_code >= 300:
            body = (await resp.aread()).decode("utf-8", "replace")
            raise HermesError(_explain(resp.status_code, body))

        event = "message"
        async for raw in resp.aiter_lines():
            line = raw.strip()
            if not line:
                continue
            if line.startswith("event:"):
                event = line[6:].strip() or event
            elif line.startswith("data:"):
                chunk = line[5:].strip()
                try:
                    data = json.loads(chunk)
                except json.JSONDecodeError:
                    data = {"raw": chunk}
                yield event, data


# --------------------------------------------------------------------------- #
# One-shot sem estado — usado para gerar os outputs
# --------------------------------------------------------------------------- #

async def complete(
    system_prompt: str, user_prompt: str, *, model: str | None = None
) -> str:
    """Uma resposta completa, sem sessão e sem histórico (não polui o caderno)."""
    body: dict[str, Any] = {
        "model": model or settings.output_model or "hermes-agent",
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "stream": False,
    }
    async with _client() as client:
        resp = await client.post(
            f"{settings.hermes_url}/v1/chat/completions", headers=_headers(), json=body
        )
        if resp.status_code >= 300:
            raise HermesError(_explain(resp.status_code, resp.text))
        data = resp.json()
    try:
        return data["choices"][0]["message"]["content"] or ""
    except (KeyError, IndexError, TypeError):
        raise HermesError(f"Resposta inesperada do motor: {json.dumps(data)[:300]}") from None
