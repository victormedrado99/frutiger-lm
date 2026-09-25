/* index.js — tela de cadernos */

(function () {
  "use strict";
  var C = window.FrutigerLM;
  var grid = document.getElementById("grid");
  var subtitle = document.getElementById("subtitle");

  function cardHtml(nb) {
    return (
      '<div class="card" data-id="' + nb.id + '">' +
        '<button class="btn btn-ghost btn-sm del" data-del="' + nb.id + '" title="Apagar caderno">🗑</button>' +
        "<h3>" + C.escapeHtml(nb.title) + "</h3>" +
        '<div class="desc">' + C.escapeHtml(nb.description || "Sem descrição.") + "</div>" +
        '<div class="meta">' +
          '<span class="pill">' + nb.source_count + (nb.source_count === 1 ? " fonte" : " fontes") + "</span>" +
          (nb.output_count ? '<span class="pill">' + nb.output_count + " output" + (nb.output_count === 1 ? "" : "s") + "</span>" : "") +
          '<span class="pill">' + C.timeAgo(nb.updated_at) + "</span>" +
        "</div>" +
      "</div>"
    );
  }

  async function load() {
    try {
      var notebooks = await C.api("/api/notebooks");
      if (!notebooks.length) {
        grid.innerHTML =
          '<div class="card new" id="card-new"><div class="plus">+</div><div>Criar seu primeiro caderno</div></div>';
      } else {
        grid.innerHTML = notebooks.map(cardHtml).join("") +
          '<div class="card new" id="card-new"><div class="plus">+</div><div>Novo caderno</div></div>';
      }
      subtitle.textContent = notebooks.length
        ? notebooks.length + (notebooks.length === 1 ? " caderno" : " cadernos")
        : "Nenhum caderno ainda.";
    } catch (err) {
      subtitle.textContent = "Erro ao carregar: " + err.message;
      C.toast(err.message, "err");
    }
  }

  async function loadStatus() {
    var pill = document.getElementById("engine-pill");
    try {
      var s = await C.api("/api/status");
      if (!s.engine || !s.engine.ok) {
        pill.className = "pill bad";
        pill.textContent = "motor fora do ar";
        pill.title = "O API server do Hermes não respondeu em " + s.engine_url;
      } else if (!s.auth_ok) {
        pill.className = "pill bad";
        pill.textContent = "chave recusada";
        pill.title = s.auth_error || "HERMES_KEY não confere com o API_SERVER_KEY.";
        C.toast(s.auth_error || "A chave do motor foi recusada.", "err", 12000);
      } else {
        pill.className = "pill ok";
        pill.textContent = "motor ok · " + s.engine_url.replace(/^https?:\/\//, "");
        pill.title = "Motor respondendo e autenticado.";
      }
      // Indicador do modelo: é o que a pessoa vai configurar no botão ao lado.
      var bm = document.getElementById("btn-model");
      bm.classList.toggle("model-on", !!s.model_configured);
      bm.classList.toggle("model-off", !s.model_configured);
      bm.title = s.model_configured
        ? "Modelo configurado"
        : "Nenhum modelo configurado — clique para colocar a sua chave";
    } catch (err) {
      pill.className = "pill bad";
      pill.textContent = "motor inacessível";
    }
  }

  /* ------------------------------- eventos ------------------------------- */

  grid.addEventListener("click", async function (ev) {
    var delBtn = ev.target.closest("[data-del]");
    if (delBtn) {
      ev.stopPropagation();
      var id = delBtn.dataset.del;
      var card = delBtn.closest(".card");
      var title = card.querySelector("h3").textContent;
      if (!confirm('Apagar o caderno "' + title + '"?\n\nAs fontes e outputs dele serão removidos.')) return;
      try {
        await C.api("/api/notebooks/" + id, { method: "DELETE" });
        C.toast("Caderno apagado.", "ok");
        load();
      } catch (err) { C.toast(err.message, "err"); }
      return;
    }

    if (ev.target.closest("#card-new")) { openNew(); return; }

    var card = ev.target.closest(".card[data-id]");
    if (card) window.location.href = "/n/" + card.dataset.id;
  });

  function openNew() {
    document.getElementById("nb-title").value = "";
    document.getElementById("nb-desc").value = "";
    C.openModal("modal-new");
    setTimeout(function () { document.getElementById("nb-title").focus(); }, 40);
  }

  document.getElementById("btn-new").addEventListener("click", openNew);

  document.querySelectorAll("[data-close]").forEach(function (el) {
    el.addEventListener("click", function () { C.closeModal(el.dataset.close); });
  });

  document.querySelectorAll(".overlay").forEach(function (ov) {
    ov.addEventListener("click", function (ev) { if (ev.target === ov) ov.hidden = true; });
  });

  async function create() {
    var title = document.getElementById("nb-title").value.trim();
    var desc = document.getElementById("nb-desc").value.trim();
    if (!title) { C.toast("Dê um título ao caderno.", "err"); return; }
    var btn = document.getElementById("btn-create");
    btn.disabled = true;
    try {
      var nb = await C.api("/api/notebooks", { method: "POST", body: { title: title, description: desc } });
      window.location.href = "/n/" + nb.id;
    } catch (err) {
      C.toast(err.message, "err");
      btn.disabled = false;
    }
  }

  document.getElementById("btn-create").addEventListener("click", create);
  ["nb-title", "nb-desc"].forEach(function (id) {
    document.getElementById(id).addEventListener("keydown", function (ev) {
      if (ev.key === "Enter" && (id === "nb-title" || ev.metaKey || ev.ctrlKey)) create();
    });
  });

  /* --------------------------- modelo / API key --------------------------- */

  var modelState = { presets: {}, hasKey: false };

  function el(id) { return document.getElementById(id); }

  async function openModel() {
    try {
      var s = await C.api("/api/settings/model");
      modelState.presets = s.presets || {};
      modelState.hasKey = !!s.has_key;

      el("md-preset").innerHTML = '<option value="">personalizado</option>' +
        Object.keys(modelState.presets).map(function (nome) {
          return '<option value="' + C.escapeHtml(nome) + '">' + C.escapeHtml(nome) + "</option>";
        }).join("");

      el("md-url").value = s.base_url || "";
      el("md-model").value = s.model || "";
      el("md-temp").value = s.temperature;
      el("md-temp-val").textContent = s.temperature;

      // A chave nunca volta do servidor: o campo sai vazio de propósito e o
      // placeholder avisa que em branco significa "manter a que já está salva".
      el("md-key").value = "";
      el("md-key").placeholder = s.has_key ? "deixe em branco para manter a salva" : "cole a chave aqui";
      el("md-key-state").textContent = s.has_key ? "(salva: " + s.key_hint + ")" : "(nenhuma)";
      el("md-key-hint").textContent = s.needs_key
        ? "Endereço remoto: a chave é obrigatória."
        : "Endereço local (LM Studio, llama.cpp): a chave não é necessária.";

      // Guia em vez de campo vazio: o caminho natural (colar a chave e salvar)
      // produzia uma config inutilizável sem avisar. Endereço e modelo são
      // obrigatórios, e a tela diz isso antes de a pessoa errar.
      var intro = el("md-intro");
      if (s.configured) {
        intro.innerHTML = "Modelo em uso. Troque o que quiser e clique em Salvar — " +
          "a chave fica só na sua máquina e nunca volta para o navegador.";
      } else if (s.has_key) {
        intro.innerHTML = "Sua chave já está salva, mas ainda falta escolher o " +
          "<b>provedor</b> (ou preencher endereço e modelo) para o modelo funcionar.";
      } else {
        intro.innerHTML = "Comece escolhendo um <b>provedor</b> abaixo — ele preenche o " +
          "endereço — depois o nome do modelo e a sua chave. Endereço local " +
          "(LM Studio, llama.cpp) não pede chave.";
      }

      el("md-result").hidden = true;
      C.openModal("modal-model");
      setTimeout(function () { el("md-url").focus(); }, 40);
    } catch (err) { C.toast(err.message, "err"); }
  }

  function aplicarPreset() {
    var p = modelState.presets[el("md-preset").value];
    if (!p) return;
    el("md-url").value = p.base_url;
    if (p.model) el("md-model").value = p.model;
  }

  function corpoDoModelo() {
    var corpo = {
      base_url: el("md-url").value.trim(),
      model: el("md-model").value.trim(),
      temperature: parseFloat(el("md-temp").value)
    };
    var digitada = el("md-key").value.trim();
    if (digitada) corpo.api_key = digitada;  // ausente = preserva a chave salva
    return corpo;
  }

  async function salvarModelo() {
    var btn = el("btn-save-model");
    btn.disabled = true;
    try {
      await C.api("/api/settings/model", { method: "POST", body: corpoDoModelo() });
      C.toast("Configuração de modelo salva.", "ok");
      C.closeModal("modal-model");
      loadStatus();
    } catch (err) { C.toast(err.message, "err"); }
    btn.disabled = false;
  }

  async function testarModelo() {
    var btn = el("btn-test-model");
    var caixa = el("md-result");
    btn.disabled = true;
    caixa.hidden = false;
    caixa.className = "out-item";
    caixa.innerHTML = '<span class="spinner"></span> falando com o modelo…';
    try {
      // Salva antes de testar: senão o teste usaria a config anterior e diria
      // "ok" para uma chave que a pessoa acabou de trocar.
      await C.api("/api/settings/model", { method: "POST", body: corpoDoModelo() });
      var r = await C.api("/api/settings/model/test", { method: "POST" });
      caixa.className = "out-item ok-box";
      caixa.innerHTML = "✓ <b>" + C.escapeHtml(r.model) + "</b> respondeu: " + C.escapeHtml(r.reply || "(vazio)");
    } catch (err) {
      caixa.className = "out-item err-box";
      caixa.innerHTML = "✕ " + C.escapeHtml(err.message);
    }
    btn.disabled = false;
  }

  el("btn-model").addEventListener("click", openModel);
  el("md-preset").addEventListener("change", aplicarPreset);
  el("md-temp").addEventListener("input", function () {
    el("md-temp-val").textContent = el("md-temp").value;
  });
  el("btn-save-model").addEventListener("click", salvarModelo);
  el("btn-test-model").addEventListener("click", testarModelo);
  ["md-url", "md-model", "md-key"].forEach(function (id) {
    el(id).addEventListener("keydown", function (ev) { if (ev.key === "Enter") salvarModelo(); });
  });

  loadStatus();
  load();
})();
