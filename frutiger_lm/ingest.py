"""Ingestão de fontes: link, PDF, vídeo do YouTube e texto colado.

Tudo vira um arquivo .txt em data/notebooks/<nb>/fontes/<src>.txt. O agente
lê esses arquivos (ou recebe o texto inline, se o caderno for pequeno).
"""

from __future__ import annotations

import asyncio
import io
import re
from pathlib import Path
from typing import Any

import httpx

from . import db
from .config import settings

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0 Safari/537.36 Caderno/0.1"
)
HTTP_TIMEOUT = httpx.Timeout(connect=15.0, read=60.0, write=30.0, pool=10.0)


class IngestError(RuntimeError):
    pass


# --------------------------------------------------------------------------- #
# Utilidades
# --------------------------------------------------------------------------- #

def clean_text(text: str) -> str:
    text = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _youtube_id(url: str) -> str | None:
    patterns = [
        r"(?:youtube\.com/watch\?[^#]*v=)([A-Za-z0-9_-]{11})",
        r"(?:youtu\.be/)([A-Za-z0-9_-]{11})",
        r"(?:youtube\.com/(?:embed|shorts|live)/)([A-Za-z0-9_-]{11})",
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return None


def is_youtube(url: str) -> bool:
    return _youtube_id(url) is not None


# --------------------------------------------------------------------------- #
# Extratores (bloqueantes — rodam em thread)
# --------------------------------------------------------------------------- #

def _fetch_url_text(url: str) -> tuple[str, str]:
    """Devolve (titulo, texto) de uma página."""
    with httpx.Client(timeout=HTTP_TIMEOUT, follow_redirects=True, headers={"User-Agent": USER_AGENT}) as client:
        resp = client.get(url)
        resp.raise_for_status()
        html = resp.text

    title = ""
    text = ""
    try:
        import trafilatura

        extracted = trafilatura.extract(html, include_comments=False, include_tables=True)
        if extracted:
            text = extracted
        meta = trafilatura.extract_metadata(html)
        if meta and getattr(meta, "title", None):
            title = meta.title
    except Exception:
        pass

    if not text:
        try:
            from bs4 import BeautifulSoup

            soup = BeautifulSoup(html, "html.parser")
            if not title:
                title = (soup.title.string or "").strip() if soup.title and soup.title.string else ""
            for tag in soup(["script", "style", "nav", "footer", "header", "aside", "form"]):
                tag.decompose()
            text = soup.get_text("\n")
        except Exception as exc:  # pragma: no cover
            raise IngestError(f"Não consegui extrair o texto da página: {exc}") from exc

    text = clean_text(text)
    if len(text) < 80:
        raise IngestError(
            "A página devolveu quase nada de texto (talvez seja um app em JS ou um paywall). "
            "Tente copiar o conteúdo e colar como fonte de texto."
        )
    return title or url, text


def _fetch_youtube_text(url: str) -> tuple[str, str]:
    """Devolve (titulo, transcrição) de um vídeo do YouTube."""
    video_id = _youtube_id(url)
    if not video_id:
        raise IngestError("Link do YouTube não reconhecido.")

    title = f"YouTube {video_id}"
    try:
        with httpx.Client(timeout=HTTP_TIMEOUT, follow_redirects=True, headers={"User-Agent": USER_AGENT}) as client:
            resp = client.get(
                "https://www.youtube.com/oembed",
                params={"url": f"https://www.youtube.com/watch?v={video_id}", "format": "json"},
            )
            if resp.status_code == 200:
                title = resp.json().get("title") or title
    except Exception:
        pass

    try:
        from youtube_transcript_api import YouTubeTranscriptApi
    except ImportError as exc:  # pragma: no cover
        raise IngestError("Falta a dependência youtube-transcript-api.") from exc

    snippets: list[dict[str, Any]] = []
    try:  # API 1.x (instância)
        api = YouTubeTranscriptApi()
        fetched = api.fetch(video_id)
        snippets = [
            {"start": getattr(s, "start", None), "text": getattr(s, "text", "")} for s in fetched
        ]
    except AttributeError:
        pass
    except Exception as exc:
        # tenta idiomas específicos antes de desistir
        try:
            api = YouTubeTranscriptApi()
            fetched = api.fetch(video_id, languages=["pt", "pt-BR", "en", "es"])
            snippets = [
                {"start": getattr(s, "start", None), "text": getattr(s, "text", "")} for s in fetched
            ]
        except Exception:
            raise IngestError(
                f"Vídeo sem transcrição disponível ({type(exc).__name__}). "
                "Legendas automáticas desligadas ou vídeo privado."
            ) from exc

    if not snippets:
        try:  # API antiga (estática)
            raw = YouTubeTranscriptApi.get_transcript(video_id, languages=["pt", "pt-BR", "en"])
            snippets = [{"start": s.get("start"), "text": s.get("text", "")} for s in raw]
        except Exception as exc:
            raise IngestError(f"Vídeo sem transcrição disponível: {exc}") from exc

    parts: list[str] = []
    for snippet in snippets:
        text = clean_text(snippet.get("text") or "")
        if not text:
            continue
        start = snippet.get("start")
        if isinstance(start, (int, float)):
            minutes, seconds = divmod(int(start), 60)
            parts.append(f"[{minutes:02d}:{seconds:02d}] {text}")
        else:
            parts.append(text)

    body = "\n".join(parts)
    if len(body) < 80:
        raise IngestError("A transcrição veio vazia.")
    return title, body


def _extract_pdf_text(data: bytes) -> tuple[str, str]:
    try:
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(data))
        pages: list[str] = []
        for index, page in enumerate(reader.pages, 1):
            try:
                content = page.extract_text() or ""
            except Exception:
                content = ""
            if content.strip():
                pages.append(f"--- página {index} ---\n{content}")
        title = ""
        try:
            meta_title = (reader.metadata or {}).get("/Title")
            if meta_title:
                title = str(meta_title).strip()
        except Exception:
            pass
        text = clean_text("\n\n".join(pages))
        if len(text) < 20:
            raise IngestError(
                f"O PDF devolveu quase nada de texto ({len(text)} caracteres), o que normalmente "
                "significa digitalizado/imagem e precisaria de OCR. Se o documento for curto de "
                "verdade, cole o texto como fonte de texto."
            )
        return title, text
    except IngestError:
        raise
    except Exception as exc:
        raise IngestError(f"Falha ao ler o PDF: {exc}") from exc


# --------------------------------------------------------------------------- #
# Persistência
# --------------------------------------------------------------------------- #

def _write_source_file(
    notebook_id: str, source_id: str, title: str, origin: str, text: str
) -> tuple[Path, int]:
    """Grava a fonte e devolve (caminho, tamanho em caracteres do arquivo).

    O tamanho devolvido é o que vai para a coluna `chars`, para que
    `context_mode` e `build_context` meçam exatamente a mesma coisa.
    """
    directory = settings.sources_dir(notebook_id)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{source_id}.txt"
    content = f"# {title}\n\n" + (f"Origem: {origin}\n\n" if origin else "") + text
    path.write_text(content, encoding="utf-8")
    return path, len(content)


async def add_source(
    notebook_id: str,
    *,
    kind: str,
    origin: str = "",
    text: str = "",
    title: str = "",
    pdf_bytes: bytes | None = None,
    pdf_name: str = "",
) -> dict[str, Any]:
    """Ingere uma fonte e devolve a linha criada."""
    kind = (kind or "").strip().lower()
    origin = origin.strip()
    title = title.strip()

    # um link de vídeo é detectado sozinho: o usuário não precisa escolher
    if kind == "url" and is_youtube(origin):
        kind = "youtube"

    if kind == "text":
        body = clean_text(text)
        if not body:
            raise IngestError("Texto vazio.")
        title = title or body[:60] + ("…" if len(body) > 60 else "")

    elif kind == "url":
        if not origin:
            raise IngestError("Informe o link.")
        fetched_title, body = await asyncio.to_thread(_fetch_url_text, origin)
        title = title or fetched_title

    elif kind == "youtube":
        if not origin:
            raise IngestError("Informe o link do vídeo.")
        fetched_title, body = await asyncio.to_thread(_fetch_youtube_text, origin)
        title = title or fetched_title

    elif kind == "pdf":
        if not pdf_bytes:
            raise IngestError("Nenhum arquivo enviado.")
        extracted_title, body = await asyncio.to_thread(_extract_pdf_text, pdf_bytes)
        title = title or extracted_title or Path(pdf_name).stem or "Documento PDF"

    else:
        raise IngestError(f"Tipo de fonte desconhecido: {kind!r}")

    source_id = db.new_id("src")
    path, chars = _write_source_file(notebook_id, source_id, title, origin or pdf_name, body)

    return db.create_source(
        notebook_id,
        source_id=source_id,
        title=title,
        kind=kind,
        origin=origin or pdf_name,
        path=str(path),
        chars=chars,
    )
