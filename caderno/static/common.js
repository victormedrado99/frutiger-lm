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

  /* Abre um POST e devolve o stream para readSSE. */
  async function postStream(path, body) {
    var resp = await fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!resp.ok) {
      var text = await resp.text();
      var msg = "HTTP " + resp.status;
      try { msg = JSON.parse(text).detail || msg; } catch (e) {}
      throw new Error(msg);
    }
    return resp;
  }

  function openModal(id) {
    var el = document.getElementById(id);
    if (el) el.hidden = false;
  }
  function closeModal(id) {
    var el = document.getElementById(id);
    if (el) el.hidden = true;
  }

  global.Caderno = {
    api: api,
    toast: toast,
    escapeHtml: escapeHtml,
    timeAgo: timeAgo,
    formatChars: formatChars,
    readSSE: readSSE,
    postStream: postStream,
    openModal: openModal,
    closeModal: closeModal,
  };
})(window);
