"""Testes do login (D069).

O que estes testes protegem, e cada um por um motivo diferente:

1. **Sem senha, nada muda.** O app de hoje (local, e o dos outros 343 testes) não pode
   ganhar um obstáculo por causa de uma fase que ainda não foi ligada.
2. **Com senha, a porta fecha de verdade** — página redireciona, API responde 401, e o
   que a tela de login precisa para carregar continua alcançável (senão ninguém entra).
3. **A senha não fica guardada.** O arquivo tem hash e sal, nunca o texto; e é 0600.
4. **Trocar a senha derruba as sessões.** É o que faz "mudei a senha" significar algo.
5. **Tentar demais trava.** `scrypt` já custa ~50 ms, mas 50 ms vezes muitos palpites
   ainda é rápido demais.
"""

from __future__ import annotations

import json

from frutiger_lm import auth, db
from frutiger_lm.__main__ import _e_local

SENHA = "senha-de-teste-123"


def com_senha(usuario: str = "victor", senha: str = SENHA) -> str:
    return auth.definir(usuario, senha)


def entrar(cliente, usuario: str = "victor", senha: str = SENHA):
    return cliente.post("/api/login", json={"usuario": usuario, "senha": senha})


def caderno(titulo: str = "Caderno") -> str:
    return db.create_notebook(titulo)["id"]


# ---------------------------------------------------------------- o modo aberto


def test_sem_senha_o_app_fica_aberto(cliente):
    """O estado de hoje: nada de login, nada de obstáculo."""
    assert auth.habilitado() is False

    assert cliente.get("/").status_code == 200
    assert cliente.get("/api/status").status_code == 200
    # e o /login manda de volta para a home: não há o que entrar
    resposta = cliente.get("/login", follow_redirects=False)
    assert resposta.status_code == 303
    assert resposta.headers["location"] == "/"


def test_a_rota_de_login_avisa_que_o_app_esta_aberto(cliente):
    resposta = entrar(cliente)

    assert resposta.status_code == 400
    assert "aberto" in resposta.json()["detail"]


# ---------------------------------------------------------------- a porta fechada


def test_com_senha_a_raiz_manda_para_a_tela_de_login(cliente):
    com_senha()

    resposta = cliente.get("/", follow_redirects=False)

    assert resposta.status_code == 303
    assert resposta.headers["location"] == "/login"


def test_o_pedido_original_vai_no_next(cliente):
    """Quem foi interrompido no meio do caminho volta para onde estava."""
    com_senha()

    resposta = cliente.get("/n/nb_qualquer", follow_redirects=False)

    assert resposta.status_code == 303
    # A barra não é escapada de propósito: a query é lida por URLSearchParams no
    # navegador, e "/login?next=/n/x" é mais legível no log do que "%2Fn%2Fx".
    assert resposta.headers["location"] == "/login?next=/n/nb_qualquer"


def test_a_api_responde_401_sem_sessao(cliente):
    com_senha()

    resposta = cliente.get("/api/status")

    assert resposta.status_code == 401
    assert "Sessão" in resposta.json()["detail"]


def test_a_tela_de_login_carrega_sem_sessao(cliente):
    """Senão a pessoa fica presa fora: o CSS e o JS dela também precisam passar."""
    com_senha()

    pagina = cliente.get("/login")
    assert pagina.status_code == 200
    assert "Entrar" in pagina.text

    assert cliente.get("/static/app.css").status_code == 200
    assert cliente.get("/static/login.js").status_code == 200


# ---------------------------------------------------------------- entrar e sair


def test_a_senha_errada_nao_abre_sessao(cliente):
    com_senha()

    resposta = entrar(cliente, senha="errada-mas-com-tamanho")

    assert resposta.status_code == 401
    assert auth.COOKIE not in resposta.cookies
    assert cliente.get("/api/status").status_code == 401


def test_o_usuario_errado_nao_abre_sessao(cliente):
    com_senha()

    assert entrar(cliente, usuario="outro").status_code == 401


def test_entrar_abre_a_sessao_e_ela_vale_nas_rotas(cliente):
    com_senha()
    nb = caderno()

    resposta = entrar(cliente)

    assert resposta.status_code == 200
    assert resposta.json()["usuario"] == "victor"
    # o cliente guarda o cookie e o resto do app funciona como sempre funcionou
    assert cliente.get("/api/status").status_code == 200
    assert cliente.get("/api/notebooks").status_code == 200
    assert cliente.get(f"/api/notebooks/{nb}/sources").status_code == 200


def test_o_cookie_e_de_sessao_e_o_js_da_pagina_nao_o_le(cliente):
    com_senha()

    resposta = entrar(cliente)
    cru = resposta.headers["set-cookie"].lower()

    assert "httponly" in cru, "sem isto um XSS no app lê o crachá"
    assert "samesite=lax" in cru, "sem isto um formulário de outro site entra junto"
    assert "path=/" in cru


def test_sair_derruba_a_sessao(cliente):
    com_senha()
    entrar(cliente)
    assert cliente.get("/api/status").status_code == 200

    assert cliente.post("/api/logout").status_code == 200

    assert cliente.get("/api/status").status_code == 401


def test_um_cookie_forjado_nao_vale(cliente):
    """Sem a assinatura certa, o cookie é só um texto que alguém escreveu."""
    com_senha()

    cliente.cookies.set(auth.COOKIE, "eyJ1IjoidmljdG9yIn0.assinatura-inventada")

    assert cliente.get("/api/status").status_code == 401


# ---------------------------------------------------------------- o segredo


def test_a_senha_nao_esta_guardada_em_claro():
    com_senha()

    bruto = auth.arquivo().read_text(encoding="utf-8")
    guardado = json.loads(bruto)

    assert SENHA not in bruto
    assert guardado["usuario"] == "victor"
    assert guardado["hash"] and guardado["sal"] and guardado["segredo"]
    # 0600 é o mesmo contrato do model.json: é segredo, e é desta instalação
    assert oct(auth.arquivo().stat().st_mode)[-3:] == "600"


def test_o_hash_confere_mas_nao_aceita_variacao():
    com_senha()

    assert auth.conferir("victor", SENHA) is True
    assert auth.conferir("victor", SENHA + " ") is False
    assert auth.conferir("VICTOR", SENHA) is False


def test_senha_curta_e_recusada():
    try:
        auth.definir("victor", "curta")
    except ValueError as exc:
        assert "8" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("aceitou uma senha de 5 caracteres")
    assert auth.habilitado() is False, "a recusa não pode deixar um login pela metade"


def test_trocar_a_senha_derruba_as_sessoes(cliente):
    """É isto que faz 'mudei a senha' valer: o crachá antigo para de ser reconhecido."""
    com_senha()
    entrar(cliente)
    assert cliente.get("/api/status").status_code == 200

    auth.definir("victor", "outra-senha-bem-longa")

    assert cliente.get("/api/status").status_code == 401

    # e a senha nova entra
    assert entrar(cliente, senha="outra-senha-bem-longa").status_code == 200
    assert cliente.get("/api/status").status_code == 200


def test_apagar_o_login_volta_ao_modo_aberto(cliente):
    com_senha()

    auth.apagar()

    assert auth.habilitado() is False
    assert cliente.get("/").status_code == 200


# ---------------------------------------------------------------- força bruta


def test_tentar_demais_trava_a_origem(cliente):
    com_senha()

    for _ in range(5):
        assert entrar(cliente, senha="errada-mas-com-tamanho").status_code == 401

    resposta = entrar(cliente, senha="errada-mas-com-tamanho")

    assert resposta.status_code == 429
    assert "Espere" in resposta.json()["detail"]
    # e nem a senha CERTA passa enquanto a espera corre
    assert entrar(cliente).status_code == 429


def test_acertar_a_senha_zera_as_tentativas(cliente):
    com_senha()
    for _ in range(4):
        entrar(cliente, senha="errada-mas-com-tamanho")

    assert entrar(cliente).status_code == 200
    assert auth.bloqueado("testclient") == 0.0


# ---------------------------------------------------------------- a guarda do bind


def test_a_guarda_do_bind_reconhece_o_que_e_local():
    """É ela que recusa subir olhando para a rede sem senha (D069)."""
    assert _e_local("127.0.0.1") is True
    assert _e_local("127.0.0.5") is True
    assert _e_local("localhost") is True
    assert _e_local("::1") is True

    assert _e_local("0.0.0.0") is False
    assert _e_local("::") is False
    assert _e_local("192.168.1.10") is False
    assert _e_local("meu-servidor.com") is False


def test_a_sessao_sobrevive_ao_processo():
    """O cookie é assinado com o segredo do arquivo: reiniciar o app não desloga ninguém."""
    com_senha()
    token = auth.criar_sessao()

    # outro "processo" lê o mesmo arquivo — como faria depois de um restart
    assert auth.sessao_valida(token) is True
    assert auth.sessao_valida(token + "x") is False
    assert auth.sessao_valida(None) is False


def test_o_prazo_desliza_em_vez_de_vencer_seco(monkeypatch):
    """Quem usa não é deslogado; quem abandonou, sim."""
    com_senha()
    monkeypatch.setattr(auth, "TTL", 100)
    token = auth.criar_sessao()

    assert auth.sessao_valida(token) is True
    assert auth.precisa_renovar(token) is False, "recém-emitido não precisa renovar"

    # O prazo maior faz o MESMO token cair na segunda metade da vida dele.
    monkeypatch.setattr(auth, "TTL", 10_000)

    assert auth.sessao_valida(token) is True
    assert auth.precisa_renovar(token) is True


def test_o_middleware_renova_o_cookie_de_quem_esta_usando(cliente, monkeypatch):
    """A renovação acontece sozinha, no pedido — e é isso que a pessoa sente como
    "não preciso entrar de novo"."""
    com_senha()
    monkeypatch.setattr(auth, "TTL", 1000)
    entrar(cliente)
    monkeypatch.setattr(auth, "TTL", 10_000)  # o crachá entrou na segunda metade

    resposta = cliente.get("/api/status")

    assert resposta.status_code == 200
    assert auth.COOKIE in resposta.headers.get("set-cookie", ""), "o prazo tinha que deslizar"

    # e com um crachá recém-emitido, pedido comum não gera cookie nenhum
    assert "set-cookie" not in cliente.get("/api/status").headers
