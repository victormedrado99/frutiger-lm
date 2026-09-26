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
      guardarCadernos(notebooks);
      carregarGrafo();
      // Uma ligação por similaridade pode ter sido disparada pelo CHAT de um caderno —
      // um run que esta aba não vê nascer. Perguntar na abertura é o que a retoma.
      retomarSimilaridade();
    } catch (err) {
      subtitle.textContent = "Erro ao carregar: " + err.message;
      C.toast(err.message, "err");
    }
  }

  async function loadStatus() {
    var pill = document.getElementById("engine-pill");
    try {
      var s = await C.api("/api/status");
      var m = s.model || {};
      // O motor agora é aqui dentro, então a pastilha fala do MODELO — não de um
      // serviço externo. "motor fora do ar" não existe mais como estado.
      if (m.configured) {
        pill.className = "pill ok";
        pill.textContent = "modelo: " + (m.name || "pronto");
        pill.title = "Modelo configurado em " + (m.base_url || "?");
      } else {
        pill.className = "pill bad";
        pill.textContent = "sem modelo";
        pill.title = "Clique em Modelo para escolher o provedor e colocar a sua chave.";
      }
      var bm = document.getElementById("btn-model");
      bm.classList.toggle("model-on", !!m.configured);
      bm.classList.toggle("model-off", !m.configured);
      bm.title = m.configured
        ? "Modelo configurado — clique para trocar"
        : "Nenhum modelo configurado — clique para colocar a sua chave";
      mostrarSair(s.auth);
    } catch (err) {
      pill.className = "pill bad";
      pill.textContent = "app sem resposta";
      pill.title = err.message;
    }
  }

  /* O "sair" existe só quando há login (D069) — e nasce aqui, e não no HTML, para
     aparecer numa página que é servida com ou sem senha sem precisar de dois arquivos.
     Sem senha definida não há sessão para encerrar, e um botão que não faz nada é
     exatamente o tipo de ruído que este app evita. */
  function mostrarSair(auth) {
    var atual = document.getElementById("btn-sair");
    if (!auth || !auth.habilitado) {
      if (atual) atual.remove();
      return;
    }
    if (atual) {
      atual.title = "Sair da sessão de " + (auth.usuario || "?") + " neste navegador";
      return;
    }
    var botao = document.createElement("button");
    botao.className = "btn btn-ghost";
    botao.id = "btn-sair";
    botao.textContent = "sair";
    botao.title = "Sair da sessão de " + (auth.usuario || "?") + " neste navegador";
    botao.addEventListener("click", async function () {
      botao.disabled = true;
      try {
        await C.api("/api/logout", { method: "POST" });
      } catch (err) {
        /* mesmo que falhe, a página de entrada é o estado honesto: o cookie foi tirado */
      }
      window.location.href = "/login";
    });
    var modelo = document.getElementById("btn-model");
    modelo.parentNode.insertBefore(botao, modelo);
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

      /* O bloco de embeddings (F6). Mesma disciplina da chave do chat (D030): o campo
         sai vazio com a dica ao lado, e vazio significa "não mexi". A dica também diz
         se está configurado — é o que separa "eu configurei" de "eu acho que sim". */
      el("md-embed-url").value = s.embed_base_url || "";
      el("md-embed-model").value = s.embed_model || "";
      el("md-embed-key").value = "";
      el("md-embed-key").placeholder = s.embed_has_key
        ? "deixe em branco para manter a salva"
        : "(local não precisa)";
      el("md-embed-estado").textContent = s.embed_configured
        ? "(configurado: " + (s.embed_key_hint ? "chave salva " + s.embed_key_hint : "sem chave") + ")"
        : "(opcional, não configurado)";

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
      temperature: parseFloat(el("md-temp").value),
      // Os campos do embedding vão SEMPRE, inclusive vazios: aqui vazio é um pedido
      // explícito de tirar o embedding (é o que a rota entende). Só a CHAVE segue a
      // regra do "ausente = preserva" — ela volta mascarada do servidor.
      embed_base_url: el("md-embed-url").value.trim(),
      embed_model: el("md-embed-model").value.trim(),
    };
    var digitada = el("md-key").value.trim();
    if (digitada) corpo.api_key = digitada;  // ausente = preserva a chave salva
    var digitadaEmbed = el("md-embed-key").value.trim();
    if (digitadaEmbed) corpo.embed_api_key = digitadaEmbed;
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

  async function testarEmbeddings() {
    var btn = el("btn-test-embed");
    var caixa = el("md-result");
    btn.disabled = true;
    caixa.hidden = false;
    caixa.className = "out-item";
    caixa.innerHTML = '<span class="spinner"></span> pedindo um vetor ao modelo de embeddings…';
    try {
      await C.api("/api/settings/model", { method: "POST", body: corpoDoModelo() });
      var r = await C.api("/api/settings/embed/test", { method: "POST" });
      caixa.className = "out-item ok-box";
      caixa.innerHTML = "✓ <b>" + C.escapeHtml(r.model) + "</b> respondeu " +
        C.escapeHtml(r.reply || "") + ". As arestas por similaridade já podem ser ligadas.";
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
  el("btn-test-embed").addEventListener("click", testarEmbeddings);
  ["md-url", "md-model", "md-key"].forEach(function (id) {
    el(id).addEventListener("keydown", function (ev) { if (ev.key === "Enter") salvarModelo(); });
  });

  /* ------------------------------------------------------- chat global (F2)
     A barra de baixo conversa com TODOS os cadernos: o agente procura em cada um
     e mostra o que se liga com o quê, dizendo de onde veio cada informação.
     Mesma renderização do chat do caderno (C.conversa) — só muda o endereço.
  */

  var dock = {
    messages: document.getElementById("dock-messages"),
    input: document.getElementById("dock-input"),
    send: document.getElementById("dock-send"),
  };

  var conversaGlobal = C.conversa({
    messages: dock.messages,
    input: dock.input,
    send: dock.send,
    url: "/api/global/chat",
  });

  function introGlobal() {
    return "<p>Pergunte sobre <strong>todos</strong> os seus cadernos de uma vez — " +
      "eu procuro em cada um e mostro o que se liga com o quê, dizendo de qual " +
      "caderno veio cada coisa.</p>" +
      "<p style='color:var(--muted)'>Ideias: <em>\"o que os meus cadernos têm em comum?\"</em>, " +
      "<em>\"como o que eu estudei num se relaciona com o outro?\"</em>, " +
      "<em>\"onde eu já vi esse conceito?\"</em></p>";
  }

  async function loadConversaGlobal() {
    try {
      conversaGlobal.historico(await C.api("/api/global/messages"), introGlobal);
    } catch (err) {
      conversaGlobal.historico([], function () {
        return "<em>Não consegui carregar a conversa: " + C.escapeHtml(err.message) + "</em>";
      });
    }
  }

  /* O histórico é carregado uma vez, e guardado como promise.
     Sem esta guarda havia uma corrida real: focar a barra dispara o carregamento,
     e enviar em seguida começava a conversa antes de o histórico chegar. Quando
     ele chegava, reconstruía a área de mensagens e **apagava a resposta que
     estava sendo escrita** — o usuário via a bolha de boas-vindas e nada mais. */
  var historicoCarregado = null;

  function abrirDock() {
    // A conversa é a outra aba da barra lateral: pedir o chat é pedir para vê-lo.
    mostrarPainel("chat");
    if (!historicoCarregado) historicoCarregado = loadConversaGlobal();
  }

  function enviarGlobal() {
    var texto = dock.input.value.trim();
    if (!texto) return;
    abrirDock();
    // só manda depois do histórico: quem chega por último não pode limpar a tela
    historicoCarregado.then(function () {
      conversaGlobal.enviar(texto);
    });
  }

  // Focar a barra já abre a conversa: quem clicou ali veio conversar.
  dock.input.addEventListener("focus", abrirDock);
  dock.input.addEventListener("keydown", function (ev) {
    if (ev.key === "Enter" && !ev.shiftKey && !ev.metaKey && !ev.ctrlKey) {
      ev.preventDefault();
      enviarGlobal();
    }
  });
  dock.send.addEventListener("click", enviarGlobal);

  document.getElementById("btn-dock-reset").addEventListener("click", async function () {
    if (conversaGlobal.ocupado()) return;
    if (!confirm("Começar a conversa global do zero?\n\n" +
                 "Os cadernos e as conversas de cada caderno não são tocados.")) return;
    try {
      await C.api("/api/global/chat", { method: "DELETE" });
      C.toast("Conversa global reiniciada.", "ok");
      historicoCarregado = loadConversaGlobal();
    } catch (err) { C.toast(err.message, "err"); }
  });

  /* ------------------------------------------------- grafo de conhecimento (F3)
     O desenho é do graph.js (canvas, sem biblioteca). Aqui é só ligar os filtros,
     buscar os dados e abrir o conceito clicado.
  */

  var grafoUI = {
    canvas: document.getElementById("grafo-canvas"),
    stats: document.getElementById("grafo-stats"),
    voltar: document.getElementById("grafo-voltar"),
    vazio: document.getElementById("grafo-vazio"),
    busca: document.getElementById("grafo-busca"),
    principais: document.getElementById("grafo-principais"),
    similares: document.getElementById("grafo-similares"),
    similaresLabel: document.getElementById("grafo-similares-label"),
    btnSimilaridade: document.getElementById("btn-similaridade"),
    progressoSim: document.getElementById("similaridade-progresso"),
    parecidos: document.getElementById("grafo-parecidos"),
  };

  /* Peso mínimo das co-ocorrências, e o número veio do material real.

     Medido no caderno do usuário: das 1521 arestas, 1266 tinham peso 1 — dois
     conceitos que apareceram juntos UMA vez num bloco de 6 mil caracteres. Com ~18
     conceitos por bloco, isso é praticamente todo par possível: virou novelo, e
     novelo não informa nada.

     Peso 1 num bloco grande não é relação, é coincidência de vizinhança. Então o
     padrão filtra em 2, e as afirmadas (com trecho) continuam sendo o sinal de ouro.
  */
  var grafoDesenho = null;
  var conceitoAberto = null;
  /* Quantas vezes dois conceitos precisam aparecer juntos para o desenho ligá-los.

     1 = todas as conexões. Com 2, o desenho escondia 74 das 275 ligações do caderno de
     verdade — e uma ligação escondida é informação que a pessoa não tem como saber que
     falta. Entrar num caderno agora mostra TUDO o que o material liga; o corte que
     sobra é de NÓ (o filtro "principais"), esse sim visível e controlável na tela. */
  var PESO_MINIMO_PADRAO = 1;

  function desenharGrafo(dados) {
    var total = (dados.nodes || []).length;
    var ocultos = dados.ocultos || 0;
    // Sem escopo, o grafo é o MAPA: os nós são cadernos, não conceitos. Quase tudo
    // abaixo muda de texto por causa disso — e é só texto: o desenho é o mesmo.
    var mapa = !escopoAtual;

    /* "30 de 102 conceitos" — o número escondido junto, e não só o mostrado.

       O resto é diagnóstico da extração (menções, trechos descartados), que não é
       informação do desenho: vai para o `title`, para não roubar a linha. */
    if (mapa) {
      grafoUI.stats.textContent =
        total + (total === 1 ? " caderno · " : " cadernos · ") +
        (dados.edges || []).length + " ligação(ões)";
      grafoUI.stats.title =
        "Cada nó é um caderno. Clique num deles para ver os conceitos dele.";
    } else {
      grafoUI.stats.textContent =
        (ocultos ? total + " de " + (total + ocultos) : total) +
        " conceito(s) · " + (dados.edges || []).length + " ligação(ões)";
      grafoUI.stats.title =
        dados.mencoes + " menção(ões) registradas" +
        (dados.descartadas ? " · " + dados.descartadas + " trecho(s) descartado(s) por não existirem na fonte" : "") +
        (ocultos ? " · " + ocultos + " conceito(s) de passagem oculto(s)" : "");
    }

    // O filtro é de CONCEITO: no mapa de cadernos não há o que filtrar.
    var etiqueta = grafoUI.principais.closest("label");
    if (etiqueta) etiqueta.hidden = mapa;
    // O interruptor das inferidas só existe se houver inferidas — e o botão de ligar
    // só faz sentido dentro de um caderno (o mapa não tem conceitos para comparar).
    grafoUI.similaresLabel.hidden = mapa || !dados.similaridades;
    grafoUI.btnSimilaridade.hidden = mapa;
    // O número das inferidas fica no quadro: é ele que o interruptor usa para dizer
    // quantas linhas saíram do desenho quando a pessoa o desliga (D056).
    grafoUI.canvas.dataset.similares = dados.similaridades || 0;
    grafoUI.canvas.title = mapa
      ? "Cada bolha é um caderno — o tamanho é quantos conceitos ele tem. A linha liga dois " +
        "cadernos que dividem um conceito, e a grossura é quantos. Clique numa bolha para " +
        "ver os conceitos dela."
      : "Linha cheia = ligação que o material afirma, com trecho de origem. Pontilhada = dois " +
        "conceitos que aparecem juntos no mesmo trecho. Tracejada = parecidos para o app " +
        "(comparação de vetores: inferido, sem trecho no material). O tamanho da bolha é " +
        "quantas vezes o conceito aparece, e a aura diz que ele também existe em outro caderno.";

    if (!total) {
      grafoUI.canvas.hidden = true;
      grafoUI.vazio.hidden = false;
      if (ocultos) {
        grafoUI.vazio.innerHTML =
          "<div>Deste caderno, os " + ocultos + " conceito(s) registrados são todos " +
          "<strong>menções de passagem</strong> — aparecem uma vez só. Desmarque " +
          "<strong>principais</strong> para vê-los.</div>";
      } else {
        grafoUI.vazio.innerHTML = dados.notebooks && dados.notebooks.length
          ? "<div>O grafo está vazio. Abra um caderno e use <strong>Extrair conceitos</strong> — " +
            "eu leio as fontes e registro o que elas <em>realmente</em> dizem, com o trecho de origem " +
            "de cada coisa.</div>"
          : "<div>Nenhum caderno ainda. Crie um, adicione fontes e extraia os conceitos.</div>";
      }
      return;
    }

    grafoUI.canvas.hidden = false;
    grafoUI.vazio.hidden = true;

    if (grafoDesenho) grafoDesenho.parar();
    grafoDesenho = window.GrafoFrutiger.desenhar(grafoUI.canvas, dados, {
      // O significado do clique depende do nível, e quem sabe o nível é esta camada:
      // no mapa o nó É um caderno (clicar entra nele); dentro, o nó é um conceito.
      aoClicar: function (id) {
        if (mapa) {
          entrarNoCaderno(id, tituloPorId[id]);
          return;
        }
        abrirConceito(id);
      },
      // Com o escopo preso a um caderno não há ilha a desenhar: o grafo é ele.
      cadernoFoco: escopoTitulo || null,
    });
    // Os candidatos a mesclar são do caderno, não do mapa: perguntar sem escopo traria
    // pares de outro caderno para uma tela que está mostrando todos.
    mostrarParecidos(mapa ? null : escopoAtual);
  }

  async function carregarGrafo() {
    /* Sem escopo, a URL vai limpa: o `/api/grafo` sem `notebook_id` é o MAPA, e
       `peso_minimo`/`principalmente` são filtros de conceito — não há o que filtrar
       num grafo cujos nós são cadernos. */
    var parametros = [];
    if (escopoAtual) {
      parametros.push("notebook_id=" + encodeURIComponent(escopoAtual));
      parametros.push("peso_minimo=" + PESO_MINIMO_PADRAO);
      if (grafoUI.principais.checked) parametros.push("principalmente=1");
      // Desligar as inferidas tira linha do desenho — e o interruptor diz quantas, no
      // `title`. Esconder sem avisar seria esconder informação (D056).
      if (!grafoUI.similares.checked) parametros.push("sem_similaridade=1");
    }

    var dados;
    try {
      dados = await C.api("/api/grafo" + (parametros.length ? "?" + parametros.join("&") : ""));
    } catch (err) {
      grafoUI.canvas.hidden = true;
      grafoUI.vazio.hidden = false;
      grafoUI.vazio.textContent = "Não consegui carregar o grafo: " + err.message;
      return;
    }

    desenharGrafo(dados);
  }

  /* ------------------------------------------------ entrar e sair de um caderno

     Em repouso o grafo é o MAPA: um nó por caderno, e uma linha entre os que dividem
     um conceito (o mesmo conceito com menção nas fontes dos dois). O nó é o CADERNO,
     não o conceito — é por isso que ele é clicável, e clicar entra.

     Dentro, o grafo é o de conceitos daquele caderno: os nós viram conceitos, as
     linhas viram relações ancoradas em trecho, e o `Voltar` aparece.

     O `<select>` de caderno saiu: com o clique no nó e o voltar, ele era um segundo
     controle para o mesmo estado — e a cabeça desta barra é estreita, cada linha ali
     é altura roubada do desenho.
  */
  var escopoAtual = "";
  var escopoTitulo = "";
  var tituloPorId = {};

  function guardarCadernos(cadernos) {
    tituloPorId = {};
    cadernos.forEach(function (n) {
      tituloPorId[n.id] = n.title;
    });
  }

  /* O nó do mapa É um caderno, e o `id` do nó é o dele: é isso que o clique traz. O
     título vai junto porque o desenho precisa dele para saber que está dentro de UM
     caderno (`cadernoFoco`) — e para isso o id não serve. */
  function entrarNoCaderno(id, titulo) {
    if (!id || id === escopoAtual) return;
    escopoAtual = id;
    escopoTitulo = titulo || tituloPorId[id] || "";
    mostrarVoltar();
    carregarGrafo();
  }

  function voltarAoGeral() {
    if (!escopoAtual) return;
    escopoAtual = "";
    escopoTitulo = "";
    mostrarVoltar();
    carregarGrafo();
  }

  function mostrarVoltar() {
    grafoUI.voltar.hidden = !escopoAtual;
  }

  /* ------------------------------------------- as arestas por similaridade (F6)

     A ligação roda na OFICINA do motor, fora do turno (D065): o botão dispara e segue
     pelo id — e é o mesmo caminho que acompanha um trabalho nascido no chat. Enquanto
     roda, os passos aparecem aqui; no fim, os números e, o que importa, os pares que
     parecem ser o MESMO conceito, com o botão de mesclar que já existe desde o F3. */

  var simSeguido = null;
  var simPassos = [];

  function pintarSim(extra) {
    grafoUI.progressoSim.hidden = false;
    grafoUI.progressoSim.innerHTML =
      simPassos.map(C.escapeHtml).join("<br>") + (extra ? "<br>" + extra : "");
  }

  function seguirSimilaridade(runId) {
    if (simSeguido === runId) return;
    simSeguido = runId;
    simPassos = [];
    C.stream("/api/trabalhos/" + runId)
      .then(function (resp) {
        return C.readSSE(resp, function (nome, dados) {
          if (nome === "trabalho.passo") {
            simPassos.push("· " + dados.mensagem);
            pintarSim("");
          } else if (nome === "trabalho.pronto") {
            var r = dados.resultado || {};
            pintarSim(
              "<b>Pronto:</b> " + r.conceitos + " conceito(s), " +
              r.calculados + " vetor(es) calculado(s)" +
              (r.reusados ? " (" + r.reusados + " já estavam prontos)" : "") + ", " +
              r.arestas + " ligação(ões) por similaridade."
            );
            // O desenho e os candidatos são consequência do trabalho — não faz sentido
            // pedir para a pessoa recarregar a página.
            if (escopoAtual) carregarGrafo();
          } else if (nome === "error") {
            pintarSim('<span style="color:var(--danger)">' + C.escapeHtml(dados.message) + "</span>");
          }
        });
      })
      .catch(function (err) {
        pintarSim('<span style="color:var(--danger)">' + C.escapeHtml(err.message) + "</span>");
      })
      .then(function () {
        simSeguido = null;
        mostrarParecidos(escopoAtual);
      });
  }

  async function ligarPorSimilaridade() {
    if (!escopoAtual) return;
    grafoUI.btnSimilaridade.disabled = true;
    simPassos = [];
    pintarSim("");
    try {
      var run = await C.api("/api/notebooks/" + escopoAtual + "/similaridade", { method: "POST" });
      seguirSimilaridade(run.id);
    } catch (err) {
      pintarSim('<span style="color:var(--danger)">' + C.escapeHtml(err.message) + "</span>");
    } finally {
      grafoUI.btnSimilaridade.disabled = false;
    }
  }

  /* Os pares que se parece DEMAIS (D066). O payoff do F6 num app de estudo não é a
     linha no desenho: é descobrir que o grafo pode estar contando duas vezes o mesmo
     conceito.

     A medição no material real obrigou a mudar esta tela, e vale dizer por quê: dos
     cinco pares acima de 0,96, NENHUM era duplicata. São conceitos diferentes que
     compartilham a mesma frase de origem — é a frase que os aproxima, não a identidade.
     Então a lista não tem botão de mesclar: clicar num par abre o conceito, onde os
     dois aparecem lado a lado e onde o mesclar sempre morou. A sugestão virou convite a
     OLHAR, e não atalho para uma ação sem volta. */
  async function mostrarParecidos(notebookId) {
    if (!notebookId) {
      grafoUI.parecidos.hidden = true;
      return;
    }
    var lista;
    try {
      lista = await C.api("/api/notebooks/" + encodeURIComponent(notebookId) + "/parecidos");
    } catch (err) {
      grafoUI.parecidos.hidden = true;
      return;
    }
    if (!lista || !lista.length) {
      grafoUI.parecidos.hidden = true;
      return;
    }
    grafoUI.parecidos.hidden = false;
    grafoUI.parecidos.innerHTML =
      '<div class="parecidos-titulo">' + lista.length +
      " par(es) muito parecidos " +
      '<span class="parecidos-nota">o app achou pelo texto — confira se são o MESMO ' +
      "conceito antes de mesclar. Parecido não é igual: dois conceitos diferentes podem " +
      "compartilhar a mesma frase de origem.</span></div>" +
      lista.map(function (p) {
        return '<div class="parecido" data-a="' + p.a_id + '" title="Abrir ' +
          C.escapeHtml(p.a_name) + " para comparar com " + C.escapeHtml(p.b_name) + '">' +
          '<div class="parecido-nomes"><b>' + C.escapeHtml(p.a_name) + "</b> (" +
          p.a_mentions + " menções) ≈ <b>" + C.escapeHtml(p.b_name) + "</b> (" +
          p.b_mentions + " menções) " +
          '<span class="parecidos-nota">' + (p.score * 100).toFixed(1) + "%</span></div></div>";
      }).join("");
  }

  grafoUI.parecidos.addEventListener("click", function (ev) {
    var linha = ev.target.closest(".parecido");
    if (!linha) return;
    // Abre o conceito: a comparação e a decisão acontecem lá, com as menções à vista.
    abrirConceito(linha.dataset.a);
  });

  grafoUI.btnSimilaridade.addEventListener("click", ligarPorSimilaridade);

  grafoUI.similares.addEventListener("change", function () {
    // Ao desligar, o interruptor DIZ quantas linhas saíram: nada some calado (D056).
    var quantas = Number(grafoUI.canvas.dataset.similares || 0);
    grafoUI.similaresLabel.title = grafoUI.similares.checked
      ? "Ligações que o app ACHOU parecidas, comparando os vetores dos conceitos. São " +
        "inferidas: nenhum trecho do material as sustenta. Desmarque para tirá-las do desenho."
      : quantas + " ligação(ões) inferidas estão fora do desenho.";
    carregarGrafo();
  });

  /* Um trabalho de similaridade pode ter nascido no CHAT do caderno: a ferramenta do
     agente dispara um run que esta aba não vê nascer. Ao abrir a home (ou voltar do
     caderno), o painel pergunta — e retoma o acompanhamento se ainda estiver rodando. */
  async function retomarSimilaridade() {
    if (simSeguido) return;
    try {
      var lista = await C.api("/api/trabalhos?trabalho=similaridade");
      var rodando = (lista || []).filter(function (r) { return r.estado === "rodando"; })[0];
      if (rodando) {
        seguirSimilaridade(rodando.id);
        return;
      }
      var pronto = (lista || []).filter(function (r) { return r.estado === "pronto"; })[0];
      if (pronto && pronto.resultado && pronto.resultado.conceitos) {
        var r = pronto.resultado;
        simPassos = [
          "· último trabalho neste app: " + r.conceitos + " conceito(s) vetorizado(s), " +
          r.arestas + " ligação(ões) por similaridade.",
        ];
        pintarSim("");
      }
    } catch (err) {
      /* sem isto o painel continua utilizável: só não retoma um trabalho em curso */
    }
  }

  /* ------------------------------------------------------------ o conceito */

  function blocoDeMencoes(mencoes) {
    if (!mencoes.length) {
      return "<p style='color:var(--muted);font-size:13px'>Sem menção registrada.</p>";
    }
    return mencoes.map(function (m) {
      /* A menção que veio da CONVERSA tem que se distinguir da que veio do material
         (D068): o trecho dela é fala do MODELO. Um trecho de modelo com a mesma cara
         de trecho de fonte é o defeito que este projeto mais evita — a mesma
         disciplina que separa a aresta inferida da afirmada (D063). */
      var daConversa = !m.source_id && !m.output_id;
      var onde = m.source_id
        ? 'fonte "' + C.escapeHtml(m.source_title || "?") + '"'
        : m.output_id
          ? 'output "' + C.escapeHtml(m.output_title || "?") + '"'
          : "conversa — dita pelo modelo";
      return '<div class="mencao' + (daConversa ? " da-conversa" : "") + '">' +
        '<span class="de-onde">' + onde +
        " · caderno “" + C.escapeHtml(m.notebook_title || "?") + "”</span>" +
        C.escapeHtml(m.excerpt) + "</div>";
    }).join("");
  }

  function blocoDeVizinhos(vizinhos) {
    if (!vizinhos.length) {
      return "<p style='color:var(--muted);font-size:13px'>Nada ligado a este conceito ainda. " +
        "O material o menciona, mas não o relaciona a outro — e o grafo não inventa ligação.</p>";
    }
    var ordem = vizinhos.slice().sort(function (a, b) {
      return ((b.score || 0) + b.weight) - ((a.score || 0) + a.weight);
    });
    return ordem.map(function (v) {
      /* Três famílias, três etiquetas (D063). A inferida diz que é inferida e diz
         QUANTO — a nota é a única coisa que a pessoa pode ponderar numa ligação que
         nenhum trecho sustenta. Etiquetá-la como "afirmada" seria o defeito mais grave
         possível aqui: a pessoa confiaria nela como se o material tivesse dito. */
      var etiqueta = "mesmo trecho" + (v.weight > 1 ? " · " + v.weight + "x" : "");
      var classe = "";
      var prova = "";
      if (v.kind === "explicit") {
        etiqueta = "afirmada";
        classe = " afirmada";
        prova = v.provenance.replace(/^[^:]*:\s*/, "");
      } else if (v.kind === "similarity") {
        etiqueta = "parecido " + Math.round((v.score || 0) * 100) + "%";
        classe = " inferida";
      }
      return '<div class="vizinho">' +
        '<span class="etiqueta' + classe + '">' + etiqueta + "</span>" +
        '<span><b style="color:' + C.escapeHtml("#cfe9f2") + '">' + C.escapeHtml(v.concept.name) + "</b>" +
        (prova ? '<br><span class="prova">“' + C.escapeHtml(prova) + "”</span>" : "") +
        "</span></div>";
    }).join("");
  }

  async function abrirConceito(id) {
    conceitoAberto = id;
    var painel = document.getElementById("conceito");
    painel.hidden = false;

    var dados;
    try {
      dados = await C.api("/api/conceitos/" + id);
    } catch (err) {
      C.toast(err.message, "err");
      painel.hidden = true;
      return;
    }

    var c = dados.concept;
    document.getElementById("conceito-nome").textContent = c.name;
    var cadernos = [];
    dados.mentions.forEach(function (m) { if (cadernos.indexOf(m.notebook_title) < 0) cadernos.push(m.notebook_title); });
    document.getElementById("conceito-meta").textContent =
      dados.mentions.length + " menção(ões) · " + dados.neighbors.length + " ligação(ões)" +
      (cadernos.length ? " · em " + cadernos.join(", ") : "");

    var corpo = document.getElementById("conceito-corpo");
    corpo.innerHTML =
      '<div class="conceito-secao"><h4>De onde veio</h4>' + blocoDeMencoes(dados.mentions) + "</div>" +
      '<div class="conceito-secao"><h4>O que se liga</h4>' + blocoDeVizinhos(dados.neighbors) + "</div>" +
      '<div class="conceito-secao"><h4>Suas notas</h4>' + blocoDeNotas(dados.notas || []) + "</div>";

    if (grafoDesenho) grafoDesenho.selecionar(id);
  }

  function blocoDeNotas(notas) {
    var lista = notas.map(function (n) {
      return '<div class="mencao"><span class="de-onde">' +
        new Date(n.created_at * 1000).toLocaleDateString("pt-BR") +
        ' <button class="btn btn-ghost btn-sm" data-apagar-nota="' + n.id + '">apagar</button>' +
        "</span>" + C.escapeHtml(n.body) + "</div>";
    }).join("");

    return (lista || "") +
      '<textarea id="nota-nova" rows="2" placeholder="Uma observação sua sobre este conceito…"' +
      ' style="width:100%;margin-top:8px"></textarea>' +
      '<button class="btn btn-sm" id="btn-salvar-nota" style="margin-top:6px">Salvar nota</button>';
  }

  async function salvarNota() {
    var caixa = document.getElementById("nota-nova");
    var texto = caixa ? caixa.value.trim() : "";
    if (!texto || !conceitoAberto) return;
    try {
      await C.api("/api/conceitos/" + conceitoAberto + "/notas", {
        method: "POST",
        body: { body: texto },
      });
      C.toast("Nota salva.", "ok");
      abrirConceito(conceitoAberto);
    } catch (err) { C.toast(err.message, "err"); }
  }

  function fecharConceito() {
    document.getElementById("conceito").hidden = true;
    conceitoAberto = null;
  }

  document.getElementById("btn-conceito-fechar").addEventListener("click", fecharConceito);

  // A nota é criada e apagada de dentro do painel, que é redesenhado a cada ação —
  // então os cliques são delegados no corpo, e não presos a cada botão.
  document.getElementById("conceito-corpo").addEventListener("click", async function (ev) {
    var apagar = ev.target.closest("[data-apagar-nota]");
    if (apagar) {
      try {
        await C.api("/api/notas/" + apagar.dataset.apagarNota, { method: "DELETE" });
        abrirConceito(conceitoAberto);
      } catch (err) { C.toast(err.message, "err"); }
      return;
    }
    if (ev.target.id === "btn-salvar-nota") salvarNota();
  });

  document.getElementById("btn-conceito-renomear").addEventListener("click", async function () {
    if (!conceitoAberto) return;
    var nome = prompt("Novo nome do conceito:\n\nSe já existir um conceito com este nome, os dois são juntados.");
    if (!nome || !nome.trim()) return;
    try {
      await C.api("/api/conceitos/" + conceitoAberto + "/renomear", { method: "POST", body: { nome: nome.trim() } });
      C.toast("Conceito renomeado.", "ok");
      abrirConceito(conceitoAberto);
      carregarGrafo();
    } catch (err) { C.toast(err.message, "err"); }
  });

  document.getElementById("btn-conceito-mesclar").addEventListener("click", async function () {
    if (!conceitoAberto) return;
    var termo = prompt("Juntar com qual conceito? (escreva o nome)");
    if (!termo || !termo.trim()) return;
    try {
      var achados = await C.api("/api/conceitos?termo=" + encodeURIComponent(termo.trim()));
      var outros = achados.filter(function (c) { return c.id !== conceitoAberto; });
      if (!outros.length) {
        C.toast("Não achei nenhum conceito com esse nome.", "err");
        return;
      }
      if (outros.length > 1) {
        C.toast("Achei mais de um: " + outros.map(function (c) { return c.name; }).join(", ") + ". Seja mais específico.", "err", 9000);
        return;
      }
      if (!confirm('Juntar este conceito com "' + outros[0].name + '"?\n\nAs menções e ligações passam para o outro, e o nome antigo fica como apelido. Nada se perde.')) return;
      await C.api("/api/conceitos/mesclar", { method: "POST", body: { de: conceitoAberto, para: outros[0].id } });
      C.toast("Conceitos juntados.", "ok");
      abrirConceito(outros[0].id);
      carregarGrafo();
    } catch (err) { C.toast(err.message, "err"); }
  });

  document.getElementById("btn-conceito-apagar").addEventListener("click", async function () {
    if (!conceitoAberto) return;
    var nome = document.getElementById("conceito-nome").textContent;
    if (!confirm('Apagar "' + nome + '" do grafo?\n\nAs menções e ligações dele somem. As fontes não são tocadas.')) return;
    try {
      await C.api("/api/conceitos/" + conceitoAberto, { method: "DELETE" });
      C.toast("Conceito apagado.", "ok");
      fecharConceito();
      carregarGrafo();
    } catch (err) { C.toast(err.message, "err"); }
  });

  /* ------------------------------------------- abas da barra lateral (F4)

     Grafo e chat dividem a barra. Dois cuidados que a troca de aba exige:

     1. **Canvas escondido tem clientWidth 0.** Se a aba do grafo fosse desenhada
        enquanto escondida, o grafo sairia com o tamanho errado e só se perceberia ao
        abrir a aba. Por isso `reajustar()` na volta — e dentro de dois quadros de
        animação, porque o layout só assenta depois que o `hidden` sai.
     2. **A barra lateral mora abaixo do cabeçalho.** A altura vai para a variável
        `--topbar`, medida em vez de fixada: o cabeçalho cresce com a fonte do
        sistema, e um número errado deixaria a barra por baixo dele.
  */
  var abasLaterais = document.querySelectorAll(".lateral-abas button");

  function mostrarPainel(nome) {
    abasLaterais.forEach(function (botao) {
      botao.classList.toggle("active", botao.dataset.painel === nome);
    });
    document.getElementById("painel-grafo").hidden = nome !== "grafo";
    document.getElementById("painel-chat").hidden = nome !== "chat";

    if (nome !== "grafo") return;
    requestAnimationFrame(function () {
      requestAnimationFrame(function () {
        if (grafoDesenho) grafoDesenho.reajustar();
        else carregarGrafo();
      });
    });
  }

  abasLaterais.forEach(function (botao) {
    botao.addEventListener("click", function () {
      mostrarPainel(botao.dataset.painel);
    });
  });

  function medirTopbar() {
    var cabecalho = document.querySelector(".topbar");
    if (cabecalho) {
      document.documentElement.style.setProperty("--topbar", cabecalho.offsetHeight + "px");
    }
  }

  /* Redimensionar a janela tem que ATUALIZAR o desenho.

     Faltava: o canvas só se media ao ser criado e na troca de aba. Maximizar a janela
     mudava a barra de lugar e o grafo continuava com o tamanho antigo — desenhado para
     uma caixa que já não existia.

     Com espera de 140ms porque o `resize` dispara dezenas de vezes por segundo durante
     o arraste, e recompor a simulação a cada disparo deixaria o desenho tremendo. */
  var esperaDoResize = null;
  window.addEventListener("resize", function () {
    medirTopbar();
    clearTimeout(esperaDoResize);
    esperaDoResize = setTimeout(function () {
      if (grafoDesenho) grafoDesenho.reajustar();
    }, 140);
  });

  medirTopbar();

  grafoUI.voltar.addEventListener("click", voltarAoGeral);
  grafoUI.principais.addEventListener("change", carregarGrafo);

  var buscaPendente = null;
  grafoUI.busca.addEventListener("input", function () {
    clearTimeout(buscaPendente);
    var termo = grafoUI.busca.value.trim();
    buscaPendente = setTimeout(async function () {
      if (!termo) {
        carregarGrafo();
        return;
      }
      try {
        var achados = await C.api("/api/conceitos?termo=" + encodeURIComponent(termo));
        if (achados.length === 1) abrirConceito(achados[0].id);
        else if (!achados.length) C.toast("Nenhum conceito com esse nome.", "err", 2500);
        else C.toast(achados.length + " conceitos encontrados — clique num nó do grafo.", "", 2500);
      } catch (err) { C.toast(err.message, "err"); }
    }, 320);
  });

  loadStatus();
  load();
})();
