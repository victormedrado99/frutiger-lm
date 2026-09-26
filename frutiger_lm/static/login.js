/* A tela de entrada (D069).

   Três decisões, e todas são sobre não confundir quem está tentando entrar:

   1. o erro é dito por extenso (o do servidor, que já diz "Usuário ou senha
      incorretos" ou "Espere N segundos") — nunca um "algo deu errado" genérico;
   2. o botão fica ocupado enquanto a resposta não chega, porque `scrypt` leva dezenas de
      milissegundos e clicar de novo é o reflexo de quem acha que não foi;
   3. ao entrar, a pessoa volta para onde ela QUERIA ir (`?next=`), e só para dentro
      deste site — `//outro-site` é redirecionamento aberto e não passa. */

(function () {
  "use strict";

  var C = window.FrutigerLM;
  var form = document.getElementById("login-form");
  var campoUsuario = document.getElementById("login-usuario");
  var campoSenha = document.getElementById("login-senha");
  var botao = document.getElementById("login-entrar");
  var erro = document.getElementById("login-erro");

  function mostrarErro(mensagem) {
    erro.hidden = false;
    erro.textContent = mensagem;
  }

  function destino() {
    var pedido = new URLSearchParams(window.location.search).get("next") || "";
    // Só caminho interno: "/x" sim, "//evil.com" e "https://..." não.
    if (pedido.charAt(0) !== "/" || pedido.charAt(1) === "/") return "/";
    return pedido;
  }

  form.addEventListener("submit", async function (ev) {
    ev.preventDefault();
    erro.hidden = true;
    botao.disabled = true;
    botao.textContent = "entrando…";
    try {
      await C.api("/api/login", {
        method: "POST",
        body: { usuario: campoUsuario.value.trim(), senha: campoSenha.value },
      });
      window.location.href = destino();
    } catch (err) {
      mostrarErro(err.message || "Não foi possível entrar.");
      botao.disabled = false;
      botao.textContent = "Entrar";
      campoSenha.select();
    }
  });

  campoSenha.addEventListener("input", function () {
    if (!erro.hidden) erro.hidden = true;
  });
})();
