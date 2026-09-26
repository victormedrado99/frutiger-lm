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

  var state = { notebook: null, currentOutputMd: "" };

  /* ------------------------------------------------------------ helpers */

  function kindLabel(kind) {
    return { url: "link", pdf: "pdf", youtube: "vídeo", text: "texto" }[kind] || kind;
  }

  function hostOf(origin) {
    if (!origin) return "";
    try { return new URL(origin).hostname.replace(/^www\./, ""); }
    catch (e) { return origin.split("/").pop().slice(0, 40); }
  }

  /* ------------------------------------------------------------- status */

  async function loadStatus() {
    try {
      var s = await C.api("/api/status");
      var m = s.model || {};
      if (m.configured) {
        els.enginePill.className = "pill ok";
        els.enginePill.textContent = "modelo: " + (m.name || "pronto");
        els.enginePill.title = "Modelo configurado em " + (m.base_url || "?");
      } else {
        els.enginePill.className = "pill bad";
        els.enginePill.textContent = "sem modelo";
        els.enginePill.title = "Configure o modelo na tela inicial para poder conversar.";
      }
    } catch (e) {
      els.enginePill.className = "pill bad";
      els.enginePill.textContent = "app sem resposta";
      els.enginePill.title = e.message;
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

  /* -------------------------------------------------------------- conversa
     A renderização e o streaming moram em `C.conversa` (common.js) — o chat
     global faz exatamente o mesmo. Aqui só fica o que é deste caderno.
  */

  var conversa = C.conversa({
    messages: els.messages,
    input: els.input,
    send: els.send,
    url: "/api/notebooks/" + NB_ID + "/chat",
    // Depois de cada turno o painel pergunta se há compilação neste caderno: é assim
    // que o documento pedido PELO CHAT aparece na tela (a ferramenta dispara o run
    // sem passar por aqui).
    aoTerminar: function () { procurarCompilacao(); },
  });

  function introDoCaderno() {
    var nb = state.notebook || {};
    var ativas = (nb.sources || []).filter(function (s) { return s.active && s.status === "ready"; });
    return ativas.length
      ? "<p>Este caderno tem <strong>" + ativas.length + "</strong> fonte" + (ativas.length === 1 ? "" : "s") +
        " no contexto. Pergunte o que quiser — eu cito de onde tirei cada coisa.</p>" +
        "<p style='color:var(--muted)'>Ideias: <em>\"faça um resumo do que é mais importante\"</em>, " +
        "<em>\"explique X como se eu tivesse 15 anos\"</em>, <em>\"o que as fontes dizem sobre Y?\"</em></p>"
      : "<p>Nenhuma fonte ativa ainda. Adicione um link, um PDF ou um texto na coluna da esquerda — " +
        "depois eu respondo <strong>com base nelas</strong>, não de memória.</p>";
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
      conversa.bolha("assistant", "<em>Não consegui carregar o histórico: " + C.escapeHtml(err.message) + "</em>");
      return;
    }
    conversa.historico(messages, introDoCaderno);
  }

  function send() {
    conversa.enviar(els.input.value);
  }

  els.input.addEventListener("keydown", function (ev) {
    if (ev.key === "Enter" && !ev.shiftKey && !ev.metaKey && !ev.ctrlKey) {
      ev.preventDefault();
      send();
    }
  });
  els.send.addEventListener("click", send);

  document.getElementById("btn-reset").addEventListener("click", async function () {
    if (conversa.ocupado()) return;
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
      // A folha de impressão abre em aba nova e traz o botão que chama a impressão do
      // navegador. Ela busca o documento salvo por id: o que se imprime é o mesmo que
      // ficou gravado, e não uma remontagem.
      document.getElementById("btn-pdf-out").href = "/imprimir/" + id;
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

  /* ------------------------------------------- o documento compilado (F5)

     A compilação pode nascer de dois lugares: do botão abaixo ou de uma ferramenta do
     chat ("compila o documento deste caderno"). Nos dois casos quem constrói é a
     OFICINA do motor, fora do turno, com um id — e é por isso que acompanhar é um
     código só aqui.

     O progresso importa mais do que nos outros botões: a compilação tem uma chamada de
     modelo no meio, e sem retorno na tela ela parece morta por meio minuto. */

  var runSeguido = null;
  var passosDaCompilacao = [];
  var vigia = null;

  function pintarCompilacao(extra) {
    var caixa = document.getElementById("compilar-progresso");
    caixa.hidden = false;
    caixa.innerHTML = passosDaCompilacao.map(C.escapeHtml).join("<br>") +
      (extra ? "<br>" + extra : "");
  }

  function eventoDaCompilacao(nome, dados) {
    if (nome === "compilando.passo") {
      passosDaCompilacao.push("· " + dados.mensagem);
      pintarCompilacao("");
    } else if (nome === "output.completed") {
      var c = dados.contagem || {};
      pintarCompilacao(
        "<b>Pronto:</b> " + dados.secoes + " seções — " +
        (c.grafo || 0) + " do grafo, " + (c.banco || 0) + " do banco e " +
        (c.modelo || 0) + " do modelo.<br>" +
        '<a href="#" id="abrir-compilado">Abrir o documento</a>'
      );
      document.getElementById("abrir-compilado").addEventListener("click", function (ev) {
        ev.preventDefault();
        showOutput(dados.id, dados.title, dados.content_md);
      });
      loadOutputs();
    } else if (nome === "error") {
      pintarCompilacao('<span style="color:var(--danger)">' + C.escapeHtml(dados.message) + "</span>");
    }
  }

  /* Segue um run até o fim, venha ele do botão ou do chat.

     O stream traz o histórico ANTES do ao vivo (é o que a oficina faz), então chegar
     atrasado não perde passo: quem abre a página no meio de uma compilação vê os
     passos que já passaram, e não uma caixa vazia. */
  async function acompanharCompilacao(runId) {
    if (runSeguido === runId) return;
    runSeguido = runId;
    passosDaCompilacao = [];
    pintarCompilacao("");
    try {
      var resp = await C.stream("/api/artefatos/" + runId);
      await C.readSSE(resp, eventoDaCompilacao);
    } catch (err) {
      pintarCompilacao('<span style="color:var(--danger)">' + C.escapeHtml(err.message) + "</span>");
    } finally {
      runSeguido = null;
      loadOutputs();
    }
  }

  /* O vigia: o painel PERGUNTANDO se há compilação neste caderno.

     Ele existe por um motivo estreito: quando o pedido nasce no chat, a ferramenta do
     agente dispara um run que esta aba não vê nascer. O botão não precisa de vigia —
     ele já sabe o id. Perguntar é uma consulta barata, e o ciclo se encerra sozinho
     quando não há mais nada rodando. */
  async function procurarCompilacao() {
    if (runSeguido) return;
    try {
      var runs = await C.api("/api/artefatos?notebook_id=" + encodeURIComponent(NB_ID));
      var emCurso = (runs || []).filter(function (r) { return r.estado === "rodando"; })[0];
      if (!emCurso) return;
      await acompanharCompilacao(emCurso.id);
      clearTimeout(vigia);
      vigia = setTimeout(procurarCompilacao, 3000);
    } catch (err) {
      /* sem vigia o app continua utilizável: só não se descobre a compilação do chat */
    }
  }

  document.getElementById("btn-compilar").addEventListener("click", async function () {
    var botao = this;
    botao.disabled = true;
    try {
      // Dispara e volta na hora: o id vem daqui e o acompanhamento é o mesmo caminho
      // que o vigia usa.
      var run = await C.api("/api/notebooks/" + NB_ID + "/compilar", { method: "POST" });
      acompanharCompilacao(run.id);
    } catch (err) {
      passosDaCompilacao = [];
      pintarCompilacao('<span style="color:var(--danger)">' + C.escapeHtml(err.message) + "</span>");
    } finally {
      botao.disabled = false;
    }
  });

  /* Os formatos extras: o download é a própria rota, não precisa de estado aqui. */
  [["btn-anki", "anki"], ["btn-obsidian", "obsidian"]].forEach(function (par) {
    var el = document.getElementById(par[0]);
    if (!el) return;
    el.addEventListener("click", function () {
      window.open("/api/notebooks/" + NB_ID + "/exportar/" + par[1], "_blank");
    });
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

  /* --------------------------------------------------------- extrair (F3)
     Ação explícita (D042): extrair custa chamadas de modelo, então quem manda é a
     pessoa. O progresso aparece porque uma fonte grande leva minutos — sem retorno
     na tela, a pessoa acha que travou e recarrega no meio.
  */

  var btnExtrair = document.getElementById("btn-extrair");
  var caixaProgresso = document.getElementById("extrair-progresso");

  function progresso(html) {
    caixaProgresso.hidden = false;
    caixaProgresso.innerHTML = html;
  }

  btnExtrair.addEventListener("click", async function () {
    btnExtrair.disabled = true;
    progresso("Lendo as fontes…");

    var descartadas = 0;
    try {
      var resp = await C.postStream("/api/notebooks/" + NB_ID + "/extrair", {});
      await C.readSSE(resp, function (nome, dados) {
        if (nome === "extract.next") {
          progresso("Fonte " + dados.indice + " de " + dados.total + ": <b>" +
            C.escapeHtml(dados.fonte) + "</b>");
        } else if (nome === "extract.source") {
          progresso("Fonte <b>" + C.escapeHtml(dados.fonte) + "</b> — analisando " +
            dados.blocos + " bloco(s)…");
        } else if (nome === "extract.block") {
          progresso("Analisando o bloco " + dados.bloco + " de " + dados.total +
            (dados.conceitos ? " · " + dados.conceitos + " conceito(s) neste" : ""));
        } else if (nome === "extract.source_done") {
          descartadas += dados.descartadas || 0;
          progresso("✓ <b>" + C.escapeHtml(dados.fonte) + "</b>: " +
            dados.mencionadas + " menção(ões)" +
            (dados.descartadas ? " · " + dados.descartadas + " descartado(s)" : ""));
        } else if (nome === "extract.done") {
          var partes = [
            "Pronto: <b>" + (dados.conceitos || 0) + "</b> conceito(s), " +
            (dados.arestas || 0) + " ligação(ões), " + (dados.mencoes || 0) + " menção(ões).",
          ];
          if (descartadas) {
            partes.push(
              descartadas + " trecho(s) descartado(s) por não existirem mesmo na fonte — " +
              "é a conferência da ancoragem funcionando."
            );
          }
          partes.push('<a href="/">ver o grafo →</a>');
          progresso(partes.join("<br>"));
          C.toast("Conceitos extraídos.", "ok");
        } else if (nome === "error") {
          progresso('<span style="color:var(--danger)">' + C.escapeHtml(dados.message) + "</span>");
          C.toast("A extração falhou.", "err");
        }
      });
    } catch (err) {
      progresso('<span style="color:var(--danger)">' + C.escapeHtml(err.message) + "</span>");
    } finally {
      btnExtrair.disabled = false;
    }
  });

  /* --------------------------------------------------------- estudar (F4)
     O painel de estudo inteiro. As lacunas e o resumo vêm numa chamada só e não custam
     modelo (D049); gerar cards e procurar contradições custam, então são botões (D042)
     com progresso.
  */

  var estudoUI = {
    resumo: document.getElementById("estudo-resumo"),
    revisao: document.getElementById("revisao"),
    lacunas: document.getElementById("lacunas"),
    conflitos: document.getElementById("conflitos"),
    fontes: document.getElementById("fontes-estudo"),
  };

  var revisao = { fila: [], revelado: false };

  function notaBtn(nota, rotulo, titulo) {
    return '<button class="btn btn-sm" data-nota="' + nota + '" title="' + titulo + '">' +
      rotulo + "</button>";
  }

  function pintarRevisao() {
    if (!revisao.fila.length) {
      estudoUI.revisao.innerHTML =
        '<div class="hint" style="font-size:13px">Nada vencido agora. ' +
        "Gere cartões dos conceitos ou volte mais tarde.</div>";
      return;
    }

    var card = revisao.fila[0];
    var html =
      '<div class="card-revisao">' +
        '<div class="pergunta">' + C.escapeHtml(card.front) + "</div>";

    if (!revisao.revelado) {
      html += '<button class="btn btn-primary" id="btn-revelar" style="width:100%">Mostrar resposta</button>';
    } else {
      html += '<div class="resposta">' + window.renderMarkdown(card.back || "—") + "</div>";
      if (card.excerpt) {
        // O lastro ao lado do verso: é o que faz o SRS valer algo.
        html += '<div class="lastro">' + C.escapeHtml(card.excerpt) +
          (card.source_title ? " — " + C.escapeHtml(card.source_title) : "") + "</div>";
      }
      html += '<div class="notas">' +
        notaBtn("errei", "Errei", "Volta nesta sessão") +
        notaBtn("dificil", "Difícil", "Intervalo curto") +
        notaBtn("bom", "Bom", "Espaça") +
        notaBtn("facil", "Fácil", "Espaça mais") +
        "</div>";
    }

    html += '<div style="margin-top:10px;color:var(--muted);font-size:11.5px">' +
      (revisao.fila.length > 1 ? (revisao.fila.length - 1) + " depois deste" : "último da fila") +
      "</div>";
    html += "</div>";

    estudoUI.revisao.innerHTML = html;

    var revelar = document.getElementById("btn-revelar");
    if (revelar) {
      revelar.addEventListener("click", function () {
        revisao.revelado = true;
        pintarRevisao();
      });
    }
    estudoUI.revisao.querySelectorAll("[data-nota]").forEach(function (botao) {
      botao.addEventListener("click", function () {
        responderCard(card.id, botao.dataset.nota);
      });
    });
  }

  async function responderCard(cardId, nota) {
    try {
      await C.api("/api/cards/" + cardId + "/revisar", { method: "POST", body: { nota: nota } });
    } catch (err) { C.toast(err.message, "err"); return; }

    // "Errei" volta na mesma sessão: em vez de sair da fila, vai para o fim dela.
    if (nota === "errei") {
      revisao.fila.push(revisao.fila.shift());
    } else {
      revisao.fila.shift();
    }
    revisao.revelado = false;
    pintarRevisao();
    carregarEstudo();
  }

  function pintarLacunas(lacunas, grafo) {
    if (!grafo.conceitos) {
      estudoUI.lacunas.innerHTML =
        '<div class="hint" style="font-size:13px">Nada extraído ainda. Use ' +
        "<b>Extrair conceitos</b>, na coluna das fontes — as lacunas saem do grafo.</div>";
      return;
    }

    var partes = [];

    if (lacunas.nao_desenvolvidos.length) {
      partes.push(
        '<div class="lacuna-grupo"><h5>O material citou e não explicou</h5><ul>' +
        lacunas.nao_desenvolvidos.slice(0, 12).map(function (c) {
          return "<li><b>" + C.escapeHtml(c.name) + "</b> <span>· 1 menção, sem ligação</span></li>";
        }).join("") + "</ul></div>"
      );
    }

    if (lacunas.em_outro_caderno.length) {
      partes.push(
        '<div class="lacuna-grupo"><h5>Você estudou em outro caderno e aqui não aparece</h5><ul>' +
        lacunas.em_outro_caderno.slice(0, 12).map(function (c) {
          return "<li><b>" + C.escapeHtml(c.name) + "</b> <span>· em " +
            C.escapeHtml(c.onde || "") + "</span></li>";
        }).join("") + "</ul></div>"
      );
    }

    if (lacunas.fontes_sem_contribuicao.length) {
      partes.push(
        '<div class="lacuna-grupo"><h5>Fontes que não geraram conhecimento</h5><ul>' +
        lacunas.fontes_sem_contribuicao.map(function (f) {
          return "<li><b>" + C.escapeHtml(f.title) + "</b> <span>· " +
            C.formatChars(f.chars) + "</span></li>";
        }).join("") + "</ul></div>"
      );
    }

    if (!partes.length) {
      partes.push('<div class="hint" style="font-size:13px">Nenhuma lacuna conferível: ' +
        "todo conceito registrado se liga a algo.</div>");
    }

    partes.push('<div class="hint" style="font-size:11.5px;margin-top:10px">' +
      "São fatos do seu material, não opinião sobre o que falta — cada um você confere na fonte." +
      "</div>");

    estudoUI.lacunas.innerHTML = partes.join("");
  }

  function pintarFontes(fontes) {
    if (!fontes.length) {
      estudoUI.fontes.innerHTML = '<div class="hint" style="font-size:13px">Sem fontes.</div>';
      return;
    }
    estudoUI.fontes.innerHTML = fontes.map(function (f) {
      return '<div class="fonte-linha"><b>' + C.escapeHtml(f.title) + "</b>" +
        (f.nunca_citada ? '<span class="etiqueta-alerta">nunca citada</span>' : "") +
        '<span class="conta">' + f.conceitos + " conceito(s)</span></div>";
    }).join("");
  }

  async function carregarEstudo() {
    var dados;
    try {
      dados = await C.api("/api/notebooks/" + NB_ID + "/estudo");
    } catch (err) {
      estudoUI.resumo.textContent = "Erro ao carregar o painel: " + err.message;
      return;
    }

    estudoUI.resumo.innerHTML = [
      '<span><b style="color:var(--accent)">' + dados.cards.vencidos + "</b> para revisar</span>",
      "<span>" + dados.cards.total + " cartão(ões)</span>",
      "<span>" + dados.grafo.conceitos + " conceito(s)</span>",
      "<span>" + dados.grafo.arestas + " ligação(ões)</span>",
    ].join("");

    if (!revisao.fila.length) {
      revisao.fila = await C.api("/api/cards?devidos=1&notebook_id=" + NB_ID);
      revisao.revelado = false;
    }
    pintarRevisao();
    pintarLacunas(dados.lacunas, dados.grafo);
    pintarFontes(dados.fontes);
  }

  document.querySelectorAll(".tabs-inline button").forEach(function (botao) {
    botao.addEventListener("click", function () {
      document.querySelectorAll(".tabs-inline button").forEach(function (b) {
        b.classList.toggle("active", b === botao);
      });
      document.getElementById("aba-gerar").hidden = botao.dataset.aba !== "gerar";
      document.getElementById("aba-estudar").hidden = botao.dataset.aba !== "estudar";
      if (botao.dataset.aba === "estudar") carregarEstudo();
    });
  });

  document.getElementById("btn-gerar-cards").addEventListener("click", async function () {
    var botao = this;
    var caixa = document.getElementById("cards-progresso");
    botao.disabled = true;
    caixa.hidden = false;
    caixa.textContent = "Olhando os conceitos…";

    try {
      var resp = await C.postStream("/api/notebooks/" + NB_ID + "/cards/gerar", {});
      await C.readSSE(resp, function (nome, dados) {
        if (nome === "cards.plano") {
          caixa.textContent = dados.alvos + " conceito(s) sem cartão para compor…";
        } else if (nome === "cards.item") {
          caixa.textContent = dados.indice + " de " + dados.total + ": " +
            C.escapeHtml(dados.conceito) +
            (dados.criado ? " ✓" : " — pulado (" + C.escapeHtml(dados.motivo || "") + ")");
        } else if (nome === "cards.done") {
          var texto = "Pronto: <b>" + dados.criados + "</b> cartão(ões) criados.";
          if (dados.alvos !== undefined && dados.criados < (dados.alvos || 0)) {
            texto += "<br>Os pulados não tinham o que responder no material — e um cartão " +
              "sem resposta não é cartão.";
          }
          caixa.innerHTML = texto;
          C.toast("Cartões criados.", "ok");
          carregarEstudo();
        } else if (nome === "error") {
          caixa.innerHTML = '<span style="color:var(--danger)">' + C.escapeHtml(dados.message) + "</span>";
        }
      });
    } catch (err) {
      caixa.innerHTML = '<span style="color:var(--danger)">' + C.escapeHtml(err.message) + "</span>";
    } finally {
      botao.disabled = false;
    }
  });

  document.getElementById("btn-conflitos").addEventListener("click", async function () {
    var botao = this;
    var caixa = document.getElementById("conflitos-progresso");
    botao.disabled = true;
    caixa.hidden = false;
    caixa.textContent = "Procurando conceitos em mais de uma fonte…";
    estudoUI.conflitos.innerHTML = "";

    var achadas = [];
    try {
      var resp = await C.postStream("/api/notebooks/" + NB_ID + "/conflitos", {});
      await C.readSSE(resp, function (nome, dados) {
        if (nome === "conflitos.plano") {
          caixa.textContent = dados.candidatos
            ? dados.candidatos + " conceito(s) em 2+ fontes para comparar…"
            : "Nenhum conceito aparece em duas fontes — não há o que comparar.";
        } else if (nome === "conflitos.item") {
          caixa.textContent = dados.indice + " de " + dados.total + ": " +
            C.escapeHtml(dados.conceito) + " — " + C.escapeHtml(dados.motivo);
          if (dados.conflito) achadas.push(dados);
        } else if (nome === "conflitos.done") {
          caixa.innerHTML = dados.achadas
            ? "<b>" + dados.achadas + "</b> contradição(ões) em " + dados.examinados + " conceito(s) examinado(s)."
            : "Nenhuma contradição nos " + dados.examinados + " conceito(s) examinado(s). O material está coerente.";
          pintarConflitos(achadas);
        } else if (nome === "error") {
          caixa.innerHTML = '<span style="color:var(--danger)">' + C.escapeHtml(dados.message) + "</span>";
        }
      });
    } catch (err) {
      caixa.innerHTML = '<span style="color:var(--danger)">' + C.escapeHtml(err.message) + "</span>";
    } finally {
      botao.disabled = false;
    }
  });

  function pintarConflitos(lista) {
    if (!lista.length) return;
    estudoUI.conflitos.innerHTML = lista.map(function (c) {
      return '<div class="conflito"><b>' + C.escapeHtml(c.conceito) + "</b> — " +
        C.escapeHtml(c.explicacao || "") +
        '<div class="lado"><em>uma fonte:</em> "' + C.escapeHtml(c.lado_a) + '"</div>' +
        '<div class="lado"><em>outra fonte:</em> "' + C.escapeHtml(c.lado_b) + '"</div>' +
        "</div>";
    }).join("");
  }

  /* --------------------------------------------------------- start */

  (async function init() {
    try {
      await loadNotebook();
      await Promise.all([loadTemplates(), loadOutputs(), loadStatus()]);
      await loadMessages();
      els.input.focus();
      // Se a página foi aberta (ou recarregada) no meio de uma compilação, ela é
      // retomada: o run vive no motor, não nesta aba.
      procurarCompilacao();
    } catch (err) {
      C.toast("Erro ao abrir o caderno: " + err.message, "err", 9000);
    }
  })();
})();
