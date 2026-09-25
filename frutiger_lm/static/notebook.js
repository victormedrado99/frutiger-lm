/* notebook.js — página de um caderno: fontes, conversa e outputs */

(function () {
  "use strict";
  var C = window.FrutigerLM;
  var NB_ID = window.location.pathname.split("/").filter(Boolean).pop();

  var els = {
    title: document.getElementById("nb-title"),
    ctxPill: document.getElementById("ctx-pill"),
    enginePill: document.getElementById("engine-pill"),
    sources: document.getElementById("sources"),
    srcCount: document.getElementById("src-count"),
    messages: document.getElementById("messages"),
    input: document.getElementById("input"),
    send: document.getElementById("btn-send"),
    templates: document.getElementById("templates"),
    outputs: document.getElementById("outputs"),
    outTitle: document.getElementById("out-title"),
    outBody: document.getElementById("out-body"),
    dlOut: document.getElementById("btn-dl-out"),
  };

  var state = { notebook: null, streaming: false, currentOutputMd: "" };

  /* ------------------------------------------------------------ helpers */

  function kindLabel(kind) {
    return { url: "link", pdf: "pdf", youtube: "vídeo", text: "texto" }[kind] || kind;
  }

  function hostOf(origin) {
    if (!origin) return "";
    try { return new URL(origin).hostname.replace(/^www\./, ""); }
    catch (e) { return origin.split("/").pop().slice(0, 40); }
  }

  function scrollChatIfNearBottom() {
    var nearBottom = els.messages.scrollHeight - els.messages.scrollTop - els.messages.clientHeight < 140;
    if (nearBottom) els.messages.scrollTop = els.messages.scrollHeight;
  }

  function atBottom() {
    return els.messages.scrollHeight - els.messages.scrollTop - els.messages.clientHeight < 140;
  }

  /* ------------------------------------------------------------- status */

  async function loadStatus() {
    try {
      var s = await C.api("/api/status");
      if (!s.engine || !s.engine.ok) {
        els.enginePill.className = "pill bad";
        els.enginePill.textContent = "motor fora do ar";
        els.enginePill.title = "O API server do Hermes não respondeu em " + s.engine_url;
      } else if (!s.auth_ok) {
        els.enginePill.className = "pill bad";
        els.enginePill.textContent = "chave recusada";
        els.enginePill.title = s.auth_error || "HERMES_KEY não confere com o API_SERVER_KEY.";
        C.toast(s.auth_error || "A chave do motor foi recusada.", "err", 12000);
      } else {
        els.enginePill.className = "pill ok";
        els.enginePill.textContent = "motor ok";
        els.enginePill.title = "Motor respondendo e autenticado.";
      }
    } catch (e) {
      els.enginePill.className = "pill bad";
      els.enginePill.textContent = "motor inacessível";
    }
  }

  function setCtxPill(mode, sourceCount) {
    var labels = {
      inline: "fontes no prompt",
      files: "agente lê os arquivos",
      empty: "sem fontes ativas",
    };
    els.ctxPill.textContent = (labels[mode] || mode) + " · " + sourceCount;
    els.ctxPill.title =
      mode === "inline" ? "As fontes cabem no prompt: vão inteiras em cada pergunta."
      : mode === "files" ? "Caderno grande: o agente consulta os arquivos com as ferramentas de leitura."
      : "Adicione e ligue fontes para o agente ter base.";
  }

  /* ----------------------------------------------------------- caderno */

  async function loadNotebook() {
    var nb = await C.api("/api/notebooks/" + NB_ID);
    state.notebook = nb;
    document.title = nb.title + " · Frutiger LM";
    if (document.activeElement !== els.title) els.title.value = nb.title;
    renderSources(nb.sources);
    renderOutputs(nb.outputs);
    setCtxPill(nb.context_mode, (nb.sources || []).filter(function (s) { return s.active && s.status === "ready"; }).length);
  }

  /* ------------------------------------------------------------ fontes */

  function renderSources(sources) {
    els.srcCount.textContent = sources.length;
    if (!sources.length) {
      els.sources.innerHTML =
        '<div class="empty" style="padding:32px 12px;font-size:13.5px">' +
        "Nenhuma fonte ainda.<br>Adicione um link, um PDF ou cole um texto para o agente ter base.</div>";
      return;
    }
    els.sources.innerHTML = sources.map(function (s) {
      var off = !s.active || s.status !== "ready";
      var sub = C.formatChars(s.chars);
      var host = hostOf(s.origin);
      if (host) sub += " · " + C.escapeHtml(host);
      return (
        '<div class="src' + (off ? " off" : "") + '" data-id="' + s.id + '">' +
          '<div class="src-top">' +
            '<span class="src-kind ' + s.kind + '">' + kindLabel(s.kind) + "</span>" +
            '<div class="src-title">' + C.escapeHtml(s.title) + "</div>" +
            '<div class="src-actions">' +
              '<button class="btn btn-ghost btn-sm" data-del="' + s.id + '" title="Remover fonte">✕</button>' +
            "</div>" +
          "</div>" +
          '<div class="src-sub">' +
            "<span>" + sub + "</span>" +
            '<div style="flex:1"></div>' +
            '<label class="switch" title="' + (s.active ? "Desligar do contexto" : "Ligar no contexto") + '">' +
              '<input type="checkbox" data-toggle="' + s.id + '"' + (s.active ? " checked" : "") + ">" +
              '<span class="track"></span>' +
            "</label>" +
          "</div>" +
        "</div>"
      );
    }).join("");
  }

  els.sources.addEventListener("click", async function (ev) {
    var del = ev.target.closest("[data-del]");
    if (!del) return;
    ev.stopPropagation();
    if (!confirm("Remover esta fonte do caderno?")) return;
    try {
      await C.api("/api/sources/" + del.dataset.del, { method: "DELETE" });
      C.toast("Fonte removida.", "ok");
      loadNotebook();
    } catch (err) { C.toast(err.message, "err"); }
  });

  els.sources.addEventListener("change", async function (ev) {
    var toggle = ev.target.closest("[data-toggle]");
    if (!toggle) return;
    var id = toggle.dataset.toggle;
    try {
      await C.api("/api/sources/" + id, { method: "PATCH", body: { active: toggle.checked } });
      loadNotebook();
    } catch (err) {
      C.toast(err.message, "err");
      toggle.checked = !toggle.checked;
    }
  });

  /* ------------------------------------------- modal adicionar fonte */

  var currentKind = "url";

  document.getElementById("btn-add-source").addEventListener("click", function () {
    document.getElementById("f-title").value = "";
    document.getElementById("f-url").value = "";
    document.getElementById("f-text").value = "";
    document.getElementById("f-file").value = "";
    C.openModal("modal-source");
    setTimeout(function () { document.getElementById("f-url").focus(); }, 40);
  });

  document.querySelectorAll(".tab[data-kind]").forEach(function (tab) {
    tab.addEventListener("click", function () {
      currentKind = tab.dataset.kind;
      document.querySelectorAll(".tab[data-kind]").forEach(function (t) {
        t.classList.toggle("active", t === tab);
      });
      document.querySelectorAll(".src-form").forEach(function (form) {
        form.hidden = form.dataset.form !== currentKind;
      });
    });
  });

  document.getElementById("btn-save-source").addEventListener("click", async function () {
    var btn = this;
    var form = new FormData();
    form.append("kind", currentKind === "url" ? "url" : currentKind);
    form.append("title", document.getElementById("f-title").value.trim());

    if (currentKind === "url") {
      var url = document.getElementById("f-url").value.trim();
      if (!url) { C.toast("Cole o link.", "err"); return; }
      form.append("url", url);
    } else if (currentKind === "pdf") {
      var fileInput = document.getElementById("f-file");
      if (!fileInput.files.length) { C.toast("Escolha um PDF.", "err"); return; }
      form.append("file", fileInput.files[0]);
    } else {
      var text = document.getElementById("f-text").value;
      if (!text.trim()) { C.toast("Cole algum conteúdo.", "err"); return; }
      form.append("text", text);
    }

    btn.disabled = true;
    var original = btn.textContent;
    btn.textContent = currentKind === "pdf" ? "Lendo o PDF…" : currentKind === "text" ? "Salvando…" : "Buscando a fonte…";

    try {
      var source = await C.api("/api/notebooks/" + NB_ID + "/sources", { method: "POST", body: form });
      C.toast('Fonte adicionada: ' + source.title, "ok");
      C.closeModal("modal-source");
      loadNotebook();
    } catch (err) {
      C.toast(err.message, "err", 9000);
    } finally {
      btn.disabled = false;
      btn.textContent = original;
    }
  });

  /* ------------------------------------------------------------- chat */

  function bubble(role, html) {
    var wrap = document.createElement("div");
    wrap.className = "msg " + (role === "assistant" ? "assistant" : "user");
    wrap.innerHTML =
      '<div class="msg-avatar">' + (role === "assistant" ? "◆" : "•") + "</div>" +
      '<div class="msg-content">' +
        '<div class="msg-role">' + (role === "assistant" ? "Frutiger LM" : "Você") + "</div>" +
        '<div class="body md">' + html + "</div>" +
      "</div>";
    els.messages.appendChild(wrap);
    return wrap;
  }

  async function loadMessages() {
    els.messages.innerHTML =
      '<div style="color:var(--muted);text-align:center;padding:40px 20px;font-size:13.5px">' +
      "Carregando a conversa…</div>";
    var messages;
    try {
      messages = await C.api("/api/notebooks/" + NB_ID + "/messages");
    } catch (err) {
      els.messages.innerHTML = "";
      bubble("assistant", "<em>Não consegui carregar o histórico: " + C.escapeHtml(err.message) + "</em>");
      return;
    }
    els.messages.innerHTML = "";
    var shown = messages.filter(function (m) {
      return (m.role === "user" || m.role === "assistant") && String(m.content || "").trim();
    });

    if (!shown.length) {
      var nb = state.notebook || {};
      var active = (nb.sources || []).filter(function (s) { return s.active && s.status === "ready"; });
      var intro = active.length
        ? "<p>Este caderno tem <strong>" + active.length + "</strong> fonte" + (active.length === 1 ? "" : "s") +
          " no contexto. Pergunte o que quiser — eu cito de onde tirei cada coisa.</p>" +
          "<p style='color:var(--muted)'>Ideias: <em>\"faça um resumo do que é mais importante\"</em>, " +
          "<em>\"explique X como se eu tivesse 15 anos\"</em>, <em>\"o que as fontes dizem sobre Y?\"</em></p>"
        : "<p>Nenhuma fonte ativa ainda. Adicione um link, um PDF ou um texto na coluna da esquerda — " +
          "depois eu respondo <strong>com base nelas</strong>, não de memória.</p>";
      bubble("assistant", intro);
      return;
    }

    shown.forEach(function (m) {
      bubble(m.role, m.role === "assistant" ? window.renderMarkdown(m.content) : C.escapeHtml(m.content).replace(/\n/g, "<br>"));
    });
    els.messages.scrollTop = els.messages.scrollHeight;
  }

  function toolNote(name, preview) {
    var div = document.createElement("div");
    div.className = "tool-note";
    div.innerHTML = "⚙ <span class='tname'>" + C.escapeHtml(name || "tool") + "</span>" +
      (preview ? " — " + C.escapeHtml(String(preview).slice(0, 130)) : "");
    els.messages.appendChild(div);
    scrollChatIfNearBottom();
  }

  async function send() {
    var text = els.input.value.trim();
    if (!text || state.streaming) return;

    els.input.value = "";
    autoResize();
    bubble("user", C.escapeHtml(text).replace(/\n/g, "<br>"));

    var node = bubble("assistant", '<span class="typing"></span>');
    var body = node.querySelector(".body");
    var buffer = "";
    var pending = false;
    var stick = atBottom();

    function paint() {
      if (pending) return;
      pending = true;
      requestAnimationFrame(function () {
        pending = false;
        body.innerHTML = window.renderMarkdown(buffer) + '<span class="typing"></span>';
        if (stick) els.messages.scrollTop = els.messages.scrollHeight;
      });
    }

    state.streaming = true;
    els.send.disabled = true;

    try {
      var resp = await C.postStream("/api/notebooks/" + NB_ID + "/chat", { input: text });

      await C.readSSE(resp, function (name, data) {
        if (name === "assistant.delta") {
          buffer += data.delta || "";
          paint();
        } else if (name === "tool.started" || name === "tool.completed") {
          if (name === "tool.started") {
            toolNote(data.tool_name, data.preview || (data.args ? JSON.stringify(data.args).slice(0, 110) : ""));
          }
        } else if (name === "assistant.completed") {
          if (data.content) buffer = data.content;
          body.innerHTML = window.renderMarkdown(buffer);
        } else if (name === "error") {
          body.innerHTML = window.renderMarkdown(buffer) +
            '<p style="color:var(--danger)">⚠ ' + C.escapeHtml(data.message || "erro") + "</p>";
        } else if (name === "done") {
          body.innerHTML = buffer
            ? window.renderMarkdown(buffer)
            : '<span style="color:var(--muted)">(o motor não devolveu texto)</span>';
        }
      });
    } catch (err) {
      body.innerHTML = '<span style="color:var(--danger)">⚠ ' + C.escapeHtml(err.message) + "</span>";
    } finally {
      state.streaming = false;
      els.send.disabled = false;
      els.input.focus();
      if (stick) els.messages.scrollTop = els.messages.scrollHeight;
    }
  }

  function autoResize() {
    els.input.style.height = "auto";
    els.input.style.height = Math.min(els.input.scrollHeight, 220) + "px";
  }

  els.input.addEventListener("input", autoResize);
  els.input.addEventListener("keydown", function (ev) {
    if (ev.key === "Enter" && !ev.shiftKey && !ev.metaKey && !ev.ctrlKey) {
      ev.preventDefault();
      send();
    }
  });
  els.send.addEventListener("click", send);

  document.getElementById("btn-reset").addEventListener("click", async function () {
    if (state.streaming) return;
    if (!confirm("Começar uma conversa nova?\n\nO histórico do chat será apagado. As fontes e os outputs ficam.")) return;
    try {
      await C.api("/api/notebooks/" + NB_ID + "/chat", { method: "DELETE" });
      C.toast("Conversa reiniciada.", "ok");
      loadMessages();
    } catch (err) { C.toast(err.message, "err"); }
  });

  /* ---------------------------------------------------------- outputs */

  async function loadTemplates() {
    var templates = await C.api("/api/outputs/templates");
    els.templates.innerHTML = templates.map(function (t) {
      return '<button class="tpl" data-tpl="' + t.key + '"><b>' + C.escapeHtml(t.label) +
        "</b><span>" + C.escapeHtml(t.hint) + "</span></button>";
    }).join("");
  }

  function renderOutputs(outputs) {
    if (!outputs.length) {
      els.outputs.innerHTML =
        '<div style="color:var(--muted);font-size:13px;padding:6px 2px">' +
        "Nada gerado ainda. Clique num tipo acima para criar um documento a partir das fontes.</div>";
      return;
    }
    els.outputs.innerHTML = outputs.map(function (o) {
      return (
        '<div class="out-item" data-id="' + o.id + '">' +
          '<div style="display:flex;gap:6px;align-items:flex-start">' +
            "<b style='flex:1'>" + C.escapeHtml(o.title) + "</b>" +
            '<button class="btn btn-ghost btn-sm" data-del-out="' + o.id + '" title="Apagar">✕</button>' +
          "</div>" +
          '<div class="src-sub"><span>' + C.timeAgo(o.created_at) + "</span><span>·</span><span>" +
          C.formatChars(o.chars || (o.content_md || "").length) + "</span></div>" +
        "</div>"
      );
    }).join("");
  }

  async function loadOutputs() {
    var outputs = await C.api("/api/notebooks/" + NB_ID + "/outputs");
    renderOutputs(outputs);
  }

  els.templates.addEventListener("click", async function (ev) {
    var btn = ev.target.closest("[data-tpl]");
    if (!btn || btn.disabled) return;
    var key = btn.dataset.tpl;
    var label = btn.querySelector("b").textContent;

    els.templates.querySelectorAll(".tpl").forEach(function (b) { b.disabled = true; });
    var original = btn.querySelector("span").textContent;
    btn.querySelector("span").textContent = "gerando… (pode levar um minuto)";
    C.toast("Gerando " + label + "…", "", 4000);

    try {
      var resp = await C.postStream("/api/notebooks/" + NB_ID + "/outputs", { template: key });
      var got = false;
      await C.readSSE(resp, function (name, data) {
        if (name === "output.completed") {
          got = true;
          C.toast(label + " pronto.", "ok");
          loadNotebook();
          showOutput(data.id, data.title, data.content_md);
        } else if (name === "error") {
          C.toast(data.message || "erro ao gerar", "err", 9000);
        }
      });
      if (!got) C.toast("O motor não devolveu documento.", "err");
    } catch (err) {
      C.toast(err.message, "err", 9000);
    } finally {
      els.templates.querySelectorAll(".tpl").forEach(function (b) { b.disabled = false; });
      btn.querySelector("span").textContent = original;
    }
  });

  els.outputs.addEventListener("click", async function (ev) {
    var del = ev.target.closest("[data-del-out]");
    if (del) {
      ev.stopPropagation();
      if (!confirm("Apagar este output?")) return;
      try {
        await C.api("/api/outputs/" + del.dataset.del, { method: "DELETE" });
        C.toast("Output apagado.", "ok");
        loadOutputs();
      } catch (err) { C.toast(err.message, "err"); }
      return;
    }
    var item = ev.target.closest(".out-item[data-id]");
    if (item) showOutput(item.dataset.id);
  });

  async function showOutput(id, title, contentMd) {
    try {
      if (contentMd === undefined) {
        var out = await C.api("/api/outputs/" + id);
        title = out.title;
        contentMd = out.content_md;
      }
      state.currentOutputMd = contentMd;
      els.outTitle.textContent = title || "Output";
      els.outBody.innerHTML = window.renderMarkdown(contentMd);
      els.dlOut.href = "/api/outputs/" + id + "/download";
      C.openModal("modal-output");
      document.querySelector("#modal-output .modal-body").scrollTop = 0;
    } catch (err) {
      C.toast(err.message, "err");
    }
  }

  document.getElementById("btn-copy-out").addEventListener("click", async function () {
    try {
      await navigator.clipboard.writeText(state.currentOutputMd || "");
      this.textContent = "Copiado!";
      var btn = this;
      setTimeout(function () { btn.textContent = "Copiar"; }, 1600);
    } catch (e) { C.toast("Não consegui copiar.", "err"); }
  });

  /* ------------------------------------------------------ modais/tabs */

  document.querySelectorAll("[data-close]").forEach(function (el) {
    el.addEventListener("click", function () { C.closeModal(el.dataset.close); });
  });
  document.querySelectorAll(".overlay").forEach(function (ov) {
    ov.addEventListener("click", function (ev) { if (ev.target === ov) ov.hidden = true; });
  });
  document.addEventListener("keydown", function (ev) {
    if (ev.key === "Escape") document.querySelectorAll(".overlay").forEach(function (ov) { ov.hidden = true; });
  });

  document.querySelectorAll(".tabs-mobile button").forEach(function (tab) {
    tab.addEventListener("click", function () {
      document.querySelectorAll(".tabs-mobile button").forEach(function (t) {
        t.classList.toggle("active", t === tab);
      });
      document.querySelectorAll(".pane").forEach(function (pane) {
        pane.classList.toggle("visible", pane.dataset.pane === tab.dataset.pane);
      });
    });
  });

  /* ------------------------------------------------ título editável */

  els.title.addEventListener("change", async function () {
    var value = els.title.value.trim();
    if (!value || (state.notebook && value === state.notebook.title)) {
      if (state.notebook) els.title.value = state.notebook.title;
      return;
    }
    try {
      await C.api("/api/notebooks/" + NB_ID, { method: "PATCH", body: { title: value } });
      document.title = value + " · Frutiger LM";
      C.toast("Título atualizado.", "ok");
      if (state.notebook) state.notebook.title = value;
    } catch (err) {
      C.toast(err.message, "err");
      if (state.notebook) els.title.value = state.notebook.title;
    }
  });
  els.title.addEventListener("keydown", function (ev) {
    if (ev.key === "Enter") { ev.preventDefault(); els.title.blur(); }
  });

  /* --------------------------------------------------------- start */

  (async function init() {
    try {
      await loadNotebook();
      await Promise.all([loadTemplates(), loadOutputs(), loadStatus()]);
      await loadMessages();
      els.input.focus();
    } catch (err) {
      C.toast("Erro ao abrir o caderno: " + err.message, "err", 9000);
    }
  })();
})();
