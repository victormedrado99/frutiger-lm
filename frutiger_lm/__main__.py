"""Ponto de entrada: `uv run frutiger-lm` ou `python -m frutiger_lm`."""

from __future__ import annotations

import argparse
import getpass

import uvicorn

from . import auth, model_store
from .config import settings


def _e_local(host: str) -> bool:
    h = (host or "").strip().lower()
    if h in ("localhost", "::1"):
        return True
    # 0.0.0.0 e :: escutam TODAS as interfaces: é o caso de hospedar, não o local.
    if h in ("0.0.0.0", "::", ""):
        return False
    return h.startswith("127.")


def _definir_senha(usuario: str) -> None:
    """Pergunta a senha duas vezes, sem eco, e grava o hash (D069).

    A senha **não** entra por argumento de linha de comando de propósito: argumento fica
    no histórico do shell e na lista de processos, para qualquer um que olhe.
    """
    atual = auth.usuario()
    if not usuario:
        resposta = input(f"  Usuário [{atual or 'dono'}]: ").strip()
        usuario = resposta or atual or "dono"

    senha = getpass.getpass("  Senha (mínimo 8 caracteres): ")
    if senha != getpass.getpass("  Repita a senha: "):
        print("\n  As senhas não conferem — nada foi alterado.\n")
        raise SystemExit(1)

    try:
        nome = auth.definir(usuario, senha)
    except ValueError as exc:
        print(f"\n  {exc} — nada foi alterado.\n")
        raise SystemExit(1) from exc

    print(f"\n  Login definido para \"{nome}\".")
    print(f"  Guardado (hash, nunca a senha) em {auth.arquivo()}")
    print("  As sessões antigas foram derrubadas: trocar a senha troca o segredo da assinatura.\n")


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="frutiger-lm",
        description="Frutiger LM — notebooks de estudo com fontes, grafo de conhecimento e outputs",
    )
    parser.add_argument("--host", default="127.0.0.1", help="endereço (default 127.0.0.1)")
    parser.add_argument("--port", type=int, default=settings.port, help=f"porta (default {settings.port})")
    parser.add_argument("--reload", action="store_true", help="recarrega ao editar o código")
    parser.add_argument(
        "--senha",
        action="store_true",
        help="define (ou troca) o usuário e a senha do dono, e sai",
    )
    parser.add_argument(
        "--usuario",
        default="",
        help="usuário do dono (com --senha; default: o atual, ou 'dono')",
    )
    parser.add_argument(
        "--sem-login",
        action="store_true",
        help="remove a senha e volta ao modo aberto (só use em máquina local)",
    )
    args = parser.parse_args()

    if args.senha:
        _definir_senha(args.usuario)
        return

    if args.sem_login:
        auth.apagar()
        print("\n  Login removido — o app está aberto outra vez (aceitável só em loopback).\n")
        return

    # A guarda do D069: olhar para a rede sem senha não sobe. Segurança que depende de
    # alguém lembrar de ligar não é segurança — e a mensagem diz o comando que resolve.
    if not _e_local(args.host) and not auth.habilitado():
        print(
            f"\n  RECUSADO: --host {args.host} olha para a rede e não há senha definida.\n"
            f"  Neste estado, qualquer um que alcance a porta lê os seus cadernos,\n"
            f"  as suas conversas e a chave da API do modelo.\n\n"
            f"  Defina a senha primeiro:\n\n"
            f"      uv run frutiger-lm --senha\n\n"
            f"  (ou use --host 127.0.0.1, que é o uso local)\n"
        )
        raise SystemExit(2)

    print(f"\n  Frutiger LM  ->  http://{args.host}:{args.port}")
    cfg = model_store.load()
    if cfg.configurado:
        onde = f"{cfg.model} em {cfg.base_url}"
    else:
        onde = "NENHUM — configure no botão \"Modelo\" da tela inicial"
    print(f"  Modelo       ->  {onde}")
    if auth.habilitado():
        print(f"  Login        ->  usuário \"{auth.usuario()}\"")
    else:
        print("  Login        ->  NENHUM (só aceitável em 127.0.0.1; --senha define)")
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
