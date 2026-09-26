/* common.js — utilidades compartilhadas pelas páginas */

(function (global) {
  "use strict";

  async function api(path, options) {
    var opts = Object.assign({ headers: {} }, options || {});
    if (opts.body && !(opts.body instanceof FormData)) {
      opts.headers["Content-Type"] = "application/json";
      opts.body = JSON.stringify(opts.body);
    }
    var resp = await fetch(path, opts);
    var text = await resp.text();
    var data = null;
    try { data = text ? JSON.parse(text) : null; } catch (e) { data = { detail: text }; }
    if (!resp.ok) {
      var msg = (data && (data.detail || data.message)) || ("HTTP " + resp.status);
      if (typeof msg !== "string") msg = JSON.stringify(msg);
      throw new Error(msg);
    }
    return data;
  }

  function toast(message, kind, ms) {
    var box = document.querySelector(".toasts");
    if (!box) {
      box = document.createElement("div");
      box.className = "toasts";
      document.body.appendChild(box);
    }
    var el = document.createElement("div");
    el.className = "toast " + (kind || "");
    el.textContent = message;
    box.appendChild(el);
    setTimeout(function () {
      el.style.transition = "opacity .3s";
      el.style.opacity = "0";
      setTimeout(function () { el.remove(); }, 320);
    }, ms || (kind === "err" ? 7000 : 3200));
  }

  function escapeHtml(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function timeAgo(ts) {
    if (!ts) return "";
    var seconds = Date.now() / 1000 - Number(ts);
    if (seconds < 90) return "agora";
    var minutes = seconds / 60;
    if (minutes < 60) return Math.round(minutes) + " min";
    var hours = minutes / 60;
    if (hours < 24) return Math.round(hours) + " h";
    var days = hours / 24;
    if (days < 30) return Math.round(days) + " d";
    return new Date(Number(ts) * 1000).toLocaleDateString("pt-BR");
  }

  function formatChars(n) {
    n = Number(n) || 0;
    if (n < 1000) return n + " car.";
    if (n < 1000000) return (n / 1000).toFixed(n < 10000 ? 1 : 0) + "k car.";
    return (n / 1000000).toFixed(1) + "M car.";
  }

  /* Lê um stream SSE (text/event-stream) e chama onEvent(nome, dados). */
  async function readSSE(response, onEvent) {
    var reader = response.body.getReader();
    var decoder = new TextDecoder();
    var buffer = "";
    var eventName = "message";

    while (true) {
      var chunk = await reader.read();
      if (chunk.done) break;
      buffer += decoder.decode(chunk.value, { stream: true });

      var parts = buffer.split("\n");
      buffer = parts.pop();

      for (var i = 0; i < parts.length; i++) {
        var line = parts[i];
        if (line.indexOf("event:") === 0) {
          eventName = line.slice(6).trim();
        } else if (line.indexOf("data:") === 0) {
          var raw = line.slice(5).trim();
          var payload = {};
          try { payload = raw ? JSON.parse(raw) : {}; } catch (e) { payload = { raw: raw }; }
          onEvent(eventName, payload);
        }
      }
    }
  }

  /* Abre uma conexão e devolve o stream para readSSE. */
  async function stream(path, options) {
    var resp = await fetch(path, options || {});
    if (!resp.ok) {
      var text = await resp.text();
      var msg = "HTTP " + resp.status;
      try { msg = JSON.parse(text).detail || msg; } catch (e) {}
      throw new Error(msg);
    }
    return resp;
  }

  /* Abre um POST e devolve o stream para readSSE. */
  function postStream(path, body) {
    return stream(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
  }

  /* ----------------------------------------------------------- conversa
     Os dois chats do app — o de um caderno e o global — fazem exatamente a
     mesma coisa: abrir o SSE do motor, acumular os pedaços numa bolha e anotar
     as ferramentas usadas.

     Isto mora num lugar só porque é a parte com INVARIANTE. Duas cópias
     divergiriam do jeito previsível: uma anotaria a ferramenta e a outra não,
     uma trataria o `assistant.completed` e a outra deixaria o texto pela metade.
     O que muda entre os chats é o endereço e o texto de boas-vindas.
  */
  function conversa(opcoes) {
    var caixa = opcoes.messages;
    var input = opcoes.input;
    var botao = opcoes.send;
    var ocupado = false;

    function pertoDoFim() {
      return caixa.scrollHeight - caixa.scrollTop - caixa.clientHeight < 140;
    }

    function bolha(papel, html) {
      var wrap = document.createElement("div");
      wrap.className = "msg " + (papel === "assistant" ? "assistant" : "user");
      wrap.innerHTML =
        '<div class="msg-avatar">' + (papel === "assistant" ? "◆" : "•") + "</div>" +
        '<div class="msg-content">' +
          '<div class="msg-role">' + (papel === "assistant" ? "Frutiger LM" : "Você") + "</div>" +
          '<div class="body md">' + html + "</div>" +
        "</div>";
      caixa.appendChild(wrap);
      return wrap;
    }

    function notaDeFerramenta(nome, previa) {
      var div = document.createElement("div");
      div.className = "tool-note";
      div.innerHTML = "⚙ <span class='tname'>" + escapeHtml(nome || "ferramenta") + "</span>" +
        (previa ? " — " + escapeHtml(String(previa).slice(0, 130)) : "");
      caixa.appendChild(div);
      if (pertoDoFim()) caixa.scrollTop = caixa.scrollHeight;
    }

    function historico(mensagens, quandoVazio) {
      caixa.innerHTML = "";
      var visiveis = (mensagens || []).filter(function (m) {
        return (m.role === "user" || m.role === "assistant") && String(m.content || "").trim();
      });
      if (!visiveis.length) {
        if (quandoVazio) bolha("assistant", quandoVazio());
        return;
      }
      visiveis.forEach(function (m) {
        bolha(m.role, m.role === "assistant"
          ? window.renderMarkdown(m.content)
          : escapeHtml(m.content).replace(/\n/g, "<br>"));
      });
      caixa.scrollTop = caixa.scrollHeight;
    }

    async function enviar(texto) {
      texto = String(texto || "").trim();
      if (!texto || ocupado) return false;

      input.value = "";
      autoResize();
      bolha("user", escapeHtml(texto).replace(/\n/g, "<br>"));

      var no = bolha("assistant", '<span class="typing"></span>');
      var corpo = no.querySelector(".body");
      var acumulado = "";
      var agendado = false;
      var grudar = pertoDoFim();

      // Um requestAnimationFrame por lote de deltas: pintar a cada pedaço
      // travaria o navegador num texto longo.
      function pintar() {
        if (agendado) return;
        agendado = true;
        requestAnimationFrame(function () {
          agendado = false;
          corpo.innerHTML = window.renderMarkdown(acumulado) + '<span class="typing"></span>';
          if (grudar) caixa.scrollTop = caixa.scrollHeight;
        });
      }

      ocupado = true;
      if (botao) botao.disabled = true;
      try {
        var resp = await postStream(opcoes.url, { input: texto });
        await readSSE(resp, function (nome, dados) {
          if (nome === "assistant.delta") {
            acumulado += dados.delta || "";
            pintar();
          } else if (nome === "tool.started") {
            notaDeFerramenta(dados.tool_name, dados.preview ||
              (dados.args ? JSON.stringify(dados.args).slice(0, 110) : ""));
          } else if (nome === "assistant.completed") {
            if (dados.content) acumulado = dados.content;
            corpo.innerHTML = window.renderMarkdown(acumulado);
          } else if (nome === "error") {
            corpo.innerHTML = window.renderMarkdown(acumulado) +
              '<p style="color:var(--danger)">⚠ ' + escapeHtml(dados.message || "erro") + "</p>";
          } else if (nome === "done") {
            corpo.innerHTML = acumulado
              ? window.renderMarkdown(acumulado)
              : '<span style="color:var(--muted)">(o motor não devolveu texto)</span>';
          }
        });
        return true;
      } catch (err) {
        corpo.innerHTML = '<span style="color:var(--danger)">⚠ ' + escapeHtml(err.message) + "</span>";
        return false;
      } finally {
        ocupado = false;
        if (botao) botao.disabled = false;
        if (input) input.focus();
        if (grudar) caixa.scrollTop = caixa.scrollHeight;
        // Gancho para a página: é assim que o painel do caderno descobre uma
        // compilação que o CHAT mandou fazer (a ferramenta do agente dispara um run
        // que a tela não vê nascer). A falha aqui não pode derrubar o chat.
        if (typeof opcoes.aoTerminar === "function") {
          try { opcoes.aoTerminar(); } catch (e) { /* o chat não é do painel */ }
        }
      }
    }

    function autoResize() {
      if (!input) return;
      input.style.height = "auto";
      input.style.height = Math.min(input.scrollHeight, 220) + "px";
    }

    if (input) input.addEventListener("input", autoResize);

    return {
      bolha: bolha,
      nota: notaDeFerramenta,
      historico: historico,
      enviar: enviar,
      autoResize: autoResize,
      ocupado: function () { return ocupado; },
    };
  }

  function openModal(id) {
    var el = document.getElementById(id);
    if (el) el.hidden = false;
  }
  function closeModal(id) {
    var el = document.getElementById(id);
    if (el) el.hidden = true;
  }

  global.FrutigerLM = {
    api: api,
    toast: toast,
    escapeHtml: escapeHtml,
    timeAgo: timeAgo,
    formatChars: formatChars,
    readSSE: readSSE,
    stream: stream,
    postStream: postStream,
    conversa: conversa,
    openModal: openModal,
    closeModal: closeModal,
  };
})(window);
