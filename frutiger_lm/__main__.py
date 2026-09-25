"""Ponto de entrada: `uv run frutiger-lm` ou `python -m frutiger_lm`."""

from __future__ import annotations

import argparse

import uvicorn

from .config import settings


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="frutiger-lm",
        description="Frutiger LM — notebooks de estudo com fontes, grafo de conhecimento e outputs",
    )
    parser.add_argument("--host", default="127.0.0.1", help="endereço (default 127.0.0.1)")
    parser.add_argument("--port", type=int, default=settings.port, help=f"porta (default {settings.port})")
    parser.add_argument("--reload", action="store_true", help="recarrega ao editar o código")
    args = parser.parse_args()

    if not settings.hermes_key:
        print(
            "\n  AVISO: HERMES_KEY não está definida.\n"
            "  Copie .env.example para .env e ponha a mesma chave que está em\n"
            "  API_SERVER_KEY no ~/.hermes/.env\n"
        )

    print(f"\n  Frutiger LM  ->  http://{args.host}:{args.port}")
    print(f"  Motor        ->  {settings.hermes_url}")
    print(f"  Dados        ->  {settings.data_dir}\n")

    uvicorn.run(
        "frutiger_lm.app:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level="info",
    )


if __name__ == "__main__":
    main()
