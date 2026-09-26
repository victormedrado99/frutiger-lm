"""O login: um dono, uma senha, e uma sessão em cookie assinado (D069).

O app nasceu local — escuta em `127.0.0.1` e quem está na máquina já é o dono. Hospedar muda
a premissa: a partir do momento em que a porta olha para a rede, tudo o que estava protegido
por "só quem alcança de dentro" passa a estar protegido por nada. E o que este app guarda não
é só leitura: são os cadernos, as fontes, as conversas e a **chave da API do modelo**.

Aqui mora só o que é do segredo — conferir a senha, assinar e validar o cookie. **A checagem
de sessão mora num middleware em `app.py`**, na frente de todas as rotas: login espalhado por
rota é login com buraco esquecido.

Sem senha definida (`habilitado()` é False), o app roda aberto — o que só é aceitável em
loopback, e é o `__main__` que recusa subir fora dele sem senha.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import tempfile
import time
from pathlib import Path
from typing import Any

from .config import settings

COOKIE = "frutiger_sessao"
DIAS = 30
TTL = DIAS * 24 * 3600

# Parâmetros do scrypt: 2**14 (~16 MB de memória), r=8, p=1. É o perfil recomendado para
# senha de gente e leva dezenas de milissegundos — caro o bastante para forçar, barato o
# bastante para quem digita a senha uma vez. Mora na stdlib: nenhuma dependência nova.
CRIPTO = {"n": 2**14, "r": 8, "p": 1, "dklen": 32}

# Freio de força bruta. Na memória, por processo — o que basta para um app de uma pessoa:
# não há cluster, e reiniciar o processo não ajuda quem está tentando adivinhar.
TENTATIVAS_LIMITE = 5
ESPERA_BASE = 60.0
ESPERA_MAXIMA = 900.0
_tentativas: dict[str, tuple[int, float]] = {}


def arquivo() -> Path:
    return settings.data_dir / "auth.json"


# --------------------------------------------------------------------------- #
# O segredo em disco
# --------------------------------------------------------------------------- #

def _ler() -> dict[str, Any] | None:
    path = arquivo()
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        # Arquivo corrompido não é senha válida nem senha nenhuma: trata como ausente,
        # que é o estado honesto (e o app continua utilizável em loopback).
        return None


def _gravar(dados: dict[str, Any]) -> None:
    """Grava com 0600, de forma atômica — mesma disciplina do `model_store`."""
    path = arquivo()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".auth-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(dados, fh, ensure_ascii=False, indent=2)
            fh.flush()
            os.fsync(fh.fileno())
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def _derivar(senha: str, sal: bytes) -> bytes:
    return hashlib.scrypt(senha.encode("utf-8"), salt=sal, **CRIPTO)


def habilitado() -> bool:
    dados = _ler()
    return bool(dados and dados.get("usuario") and dados.get("hash"))


def usuario() -> str:
    return str((_ler() or {}).get("usuario", ""))


def definir(novo_usuario: str, senha: str) -> str:
    """Define o dono e a senha. **Troca o segredo da sessão** — e derruba todas as sessões.

    É isso que faz "mudar a senha" significar algo: se o segredo de assinatura continuasse o
    mesmo, um cookie roubado antes da troca continuaria valendo depois dela.
    """
    nome = (novo_usuario or "").strip() or "dono"
    if len(senha) < 8:
        raise ValueError("A senha precisa de pelo menos 8 caracteres.")
    sal = secrets.token_bytes(16)
    _gravar(
        {
            "usuario": nome,
            "sal": base64.b64encode(sal).decode("ascii"),
            "hash": base64.b64encode(_derivar(senha, sal)).decode("ascii"),
            "cripto": CRIPTO,
            "segredo": secrets.token_urlsafe(32),
            "criado_em": time.time(),
        }
    )
    return nome


def apagar() -> None:
    """Volta ao modo aberto (só aceitável em loopback)."""
    arquivo().unlink(missing_ok=True)


def conferir(nome: str, senha: str) -> bool:
    dados = _ler()
    if not dados or not dados.get("hash"):
        return False
    if not hmac.compare_digest(str(nome or ""), str(dados.get("usuario", ""))):
        # Mesmo assim deriva o hash: sem isto, errar o usuário responderia na hora e
        # acertar erraria a senha devagar — o tempo de resposta diria qual dos dois existe.
        _derivar(senha, base64.b64decode(dados.get("sal") or base64.b64encode(b"x" * 16)))
        return False
    sal = base64.b64decode(dados["sal"])
    esperado = base64.b64decode(dados["hash"])
    return hmac.compare_digest(_derivar(senha, sal), esperado)


# --------------------------------------------------------------------------- #
# A sessão (cookie assinado — sem tabela)
# --------------------------------------------------------------------------- #

def _assinar(pedaco: str) -> str:
    dados = _ler() or {}
    segredo = str(dados.get("segredo", "")).encode("utf-8")
    return base64.urlsafe_b64encode(
        hmac.new(segredo, pedaco.encode("ascii"), hashlib.sha256).digest()
    ).decode("ascii").rstrip("=")


def criar_sessao() -> str:
    dados = _ler() or {}
    corpo = {
        "u": dados.get("usuario", ""),
        "exp": int(time.time()) + TTL,
        "n": secrets.token_urlsafe(8),  # dois logins do mesmo usuário não são o mesmo token
    }
    pedaco = base64.urlsafe_b64encode(
        json.dumps(corpo, separators=(",", ":")).encode("utf-8")
    ).decode("ascii").rstrip("=")
    return f"{pedaco}.{_assinar(pedaco)}"


def _abrir(token: str | None) -> dict[str, Any] | None:
    """O corpo do cookie, quando a assinatura confere e não venceu. Senão, None."""
    if not token or "." not in token:
        return None
    pedaco, assinatura = token.rsplit(".", 1)
    if not hmac.compare_digest(assinatura, _assinar(pedaco)):
        return None
    try:
        # O padding voltou a ser necessário: `urlsafe_b64decode` exige múltiplo de 4.
        corpo = json.loads(base64.urlsafe_b64decode(pedaco + "=" * (-len(pedaco) % 4)))
    except (ValueError, TypeError):
        return None
    if int(corpo.get("exp", 0)) < time.time():
        return None
    return corpo


def sessao_valida(token: str | None) -> bool:
    return _abrir(token) is not None


def precisa_renovar(token: str | None) -> bool:
    """Passou de metade do prazo? Então vale reemitir — quem usa não é deslogado."""
    corpo = _abrir(token)
    if corpo is None:
        return False
    return int(corpo["exp"]) - time.time() < TTL / 2


# --------------------------------------------------------------------------- #
# Freio de força bruta
# --------------------------------------------------------------------------- #

def bloqueado(chave: str) -> float:
    """Segundos que ainda faltam de espera para esta origem (0 = liberado)."""
    quantas, ate = _tentativas.get(chave, (0, 0.0))
    if quantas < TENTATIVAS_LIMITE:
        return 0.0
    return max(0.0, ate - time.time())


def registrar_falha(chave: str) -> None:
    quantas, _ = _tentativas.get(chave, (0, 0.0))
    quantas += 1
    if quantas >= TENTATIVAS_LIMITE:
        espera = min(ESPERA_BASE * 2 ** (quantas - TENTATIVAS_LIMITE), ESPERA_MAXIMA)
        _tentativas[chave] = (quantas, time.time() + espera)
    else:
        _tentativas[chave] = (quantas, 0.0)


def limpar_tentativas(chave: str) -> None:
    _tentativas.pop(chave, None)


def _esquecer_tudo() -> None:  # pragma: no cover - usado pelos testes
    _tentativas.clear()


def resumo() -> dict[str, Any]:
    """O que a UI pode saber (e nada além): se há login e quem é o dono."""
    dados = _ler() or {}
    return {"habilitado": habilitado(), "usuario": str(dados.get("usuario", "")) or None}
