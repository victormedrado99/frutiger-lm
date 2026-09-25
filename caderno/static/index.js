/* index.js — tela de cadernos */

(function () {
  "use strict";
  var C = window.Caderno;
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

  loadStatus();
  load();
})();
