/* graph.js — o grafo de conhecimento em canvas, sem biblioteca.

   O app não tem CDN e não vai ter: ele é "clone e roda". Uma simulação de forças
   simples cabe em poucas linhas e não pede dependência nenhuma.

   O que o desenho precisa mostrar, em ordem de importância:
     1. o que está ligado a quê (as arestas);
     2. a diferença entre ligação AFIRMADA pelo material e mera co-ocorrência —
        senão o desenho mente por omissão;
     3. o que aparece em mais de um caderno, que é a ponte entre áreas;
     4. o que foi mais mencionado, pelo tamanho do nó.
*/

(function (global) {
  "use strict";

  // Paleta por caderno. Ciano primeiro (a cor do tema), depois tons que contrastam
  // entre si sobre o fundo escuro.
  var PALETA = [
    "#5fe3f0", "#7ce8a8", "#f0b45f", "#c79bf0", "#f08fa8",
    "#8fb8f0", "#d8e87c", "#f0995f", "#9ff0d8", "#e07cf0",
  ];

  function corDoCaderno(titulos) {
    if (!titulos || !titulos.length) return "#8aa0b0";
    var soma = 0;
    for (var i = 0; i < titulos.length; i++) {
      for (var j = 0; j < titulos[i].length; j++) soma += titulos[i].charCodeAt(j);
    }
    return PALETA[soma % PALETA.length];
  }

  function desenhar(canvas, dados, opcoes) {
    var opt = opcoes || {};
    var ctx = canvas.getContext("2d");
    var dpr = global.devicePixelRatio || 1;

    var largura = canvas.clientWidth || 600;
    var altura = canvas.clientHeight || 360;
    canvas.width = Math.round(largura * dpr);
    canvas.height = Math.round(altura * dpr);
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

    var porId = {};
    var nos = (dados.nodes || []).map(function (no, i) {
      var angulo = (i / Math.max(1, dados.nodes.length)) * Math.PI * 2;
      var objeto = {
        id: no.id,
        nome: no.name,
        tipo: no.kind,
        mencoes: no.mentions || 0,
        cadernos: no.notebooks || [],
        ponte: !!no.ponte,
        cor: corDoCaderno(no.notebooks),
        // Espiral inicial: ponto de partida melhor que aleatório, e determinístico
        // (o mesmo grafo cai sempre no mesmo desenho).
        x: largura / 2 + Math.cos(angulo) * Math.min(largura, altura) * 0.32,
        y: altura / 2 + Math.sin(angulo) * Math.min(largura, altura) * 0.32,
        vx: 0,
        vy: 0,
        raio: 6 + Math.min(12, Math.sqrt(no.mentions || 1) * 3.4),
      };
      porId[objeto.id] = objeto;
      return objeto;
    });

    var arestas = (dados.edges || [])
      .map(function (aresta) {
        return {
          a: porId[aresta.a_id],
          b: porId[aresta.b_id],
          afirmada: aresta.kind === "explicit",
          peso: aresta.weight || 1,
        };
      })
      .filter(function (aresta) {
        return aresta.a && aresta.b;
      });

    var selecionado = null;
    var destacado = null;
    var arrastando = null;
    var parado = false;
    var iteracao = 0;
    var MAX_ITERACOES = 420;

    function passo() {
      var n = nos.length;
      if (!n) return;

      // Repulsão entre todos os pares. O(n²) é aceitável no tamanho que este grafo
      // tem hoje (dezenas de nós) e é o que mantém o desenho legível.
      for (var i = 0; i < n; i++) {
        var a = nos[i];
        for (var j = i + 1; j < n; j++) {
          var b = nos[j];
          var dx = b.x - a.x;
          var dy = b.y - a.y;
          var d2 = dx * dx + dy * dy || 0.01;
          var d = Math.sqrt(d2);
          var forca = 5200 / d2;
          var ux = dx / d;
          var uy = dy / d;
          a.vx -= ux * forca;
          a.vy -= uy * forca;
          b.vx += ux * forca;
          b.vy += uy * forca;
        }
      }

      // Mola nas arestas: quanto mais forte a ligação, mais perto.
      arestas.forEach(function (aresta) {
        var dx = aresta.b.x - aresta.a.x;
        var dy = aresta.b.y - aresta.a.y;
        var d = Math.sqrt(dx * dx + dy * dy) || 0.01;
        var alvo = aresta.afirmada ? 110 : 140;
        var forca = (d - alvo) * (aresta.afirmada ? 0.035 : 0.018);
        var ux = dx / d;
        var uy = dy / d;
        aresta.a.vx += ux * forca;
        aresta.a.vy += uy * forca;
        aresta.b.vx -= ux * forca;
        aresta.b.vy -= uy * forca;
      });

      // Puxão para o centro, senão os nós soltos fogem para fora da tela.
      nos.forEach(function (no) {
        no.vx += (largura / 2 - no.x) * 0.004;
        no.vy += (altura / 2 - no.y) * 0.004;
        no.vx *= 0.82;
        no.vy *= 0.82;
        if (no === arrastando) return;
        no.x += no.vx;
        no.y += no.vy;
        // Fica dentro do quadro: nó fora da tela é nó perdido.
        var margem = no.raio + 6;
        no.x = Math.max(margem, Math.min(largura - margem, no.x));
        no.y = Math.max(margem, Math.min(altura - margem, no.y));
      });
    }

    function ligadoA(no) {
      var vizinhos = {};
      arestas.forEach(function (aresta) {
        if (aresta.a === no) vizinhos[aresta.b.id] = true;
        if (aresta.b === no) vizinhos[aresta.a.id] = true;
      });
      return vizinhos;
    }

    function pintar() {
      ctx.clearRect(0, 0, largura, altura);

      var vizinhos = destacado || selecionado ? ligadoA(destacado || selecionado) : null;
      var foco = destacado || selecionado;

      arestas.forEach(function (aresta) {
        var aceso = !foco || aresta.a === foco || aresta.b === foco;
        ctx.beginPath();
        ctx.moveTo(aresta.a.x, aresta.a.y);
        ctx.lineTo(aresta.b.x, aresta.b.y);
        if (aresta.afirmada) {
          // Afirmada pelo material: linha cheia e mais clara.
          ctx.strokeStyle = aceso ? "rgba(160, 240, 255, 0.72)" : "rgba(120, 170, 190, 0.16)";
          ctx.lineWidth = aceso ? 1.9 : 1;
        } else {
          // Co-ocorrência: pontilhada. A diferença precisa ser visível, senão o
          // desenho sugere relação onde só houve proximidade.
          ctx.setLineDash([3, 4]);
          ctx.strokeStyle = aceso ? "rgba(140, 200, 220, 0.36)" : "rgba(120, 170, 190, 0.10)";
          ctx.lineWidth = aceso ? 1.2 : 1;
        }
        ctx.stroke();
        ctx.setLineDash([]);
      });

      nos.forEach(function (no) {
        var aceso = !foco || no === foco || (vizinhos && vizinhos[no.id]);
        ctx.globalAlpha = aceso ? 1 : 0.22;

        // Ponte entre cadernos: um anel, porque é a informação que mais interessa.
        if (no.ponte) {
          ctx.beginPath();
          ctx.arc(no.x, no.y, no.raio + 5, 0, Math.PI * 2);
          ctx.strokeStyle = "rgba(240, 180, 95, 0.85)";
          ctx.lineWidth = 2;
          ctx.stroke();
        }

        ctx.beginPath();
        ctx.arc(no.x, no.y, no.raio, 0, Math.PI * 2);
        ctx.fillStyle = no.cor;
        ctx.globalAlpha = aceso ? 0.9 : 0.2;
        ctx.fill();

        if (no === foco) {
          ctx.beginPath();
          ctx.arc(no.x, no.y, no.raio + 3, 0, Math.PI * 2);
          ctx.strokeStyle = "#ffffff";
          ctx.lineWidth = 1.6;
          ctx.stroke();
        }
        ctx.globalAlpha = aceso ? 1 : 0.2;

        // Rótulo: só nos nós com espaço para respirar, senão vira sopa de letras.
        var mostrar = aceso && (foco || nos.length <= 26 || no.mencoes >= 3 || no.ponte);
        if (mostrar) {
          ctx.font = "600 11px 'Segoe UI', system-ui, sans-serif";
          ctx.textAlign = "center";
          ctx.textBaseline = "top";
          ctx.fillStyle = "rgba(0, 0, 0, 0.55)";
          ctx.fillText(no.nome, no.x + 1, no.y + no.raio + 4);
          ctx.fillStyle = no === foco ? "#ffffff" : "#cfe9f2";
          ctx.fillText(no.nome, no.x, no.y + no.raio + 3);
        }
        ctx.globalAlpha = 1;
      });
    }

    function animar() {
      if (parado) return;
      passo();
      pintar();
      iteracao += 1;
      // Depois de assentar, para de animar: grafo parado não gasta bateria.
      if (iteracao < MAX_ITERACOES) {
        requestAnimationFrame(animar);
      } else {
        pintar();
      }
    }

    function noPonto(x, y) {
      for (var i = nos.length - 1; i >= 0; i--) {
        var no = nos[i];
        var dx = no.x - x;
        var dy = no.y - y;
        if (dx * dx + dy * dy <= (no.raio + 5) * (no.raio + 5)) return no;
      }
      return null;
    }

    function posicao(ev) {
      var r = canvas.getBoundingClientRect();
      return { x: ev.clientX - r.left, y: ev.clientY - r.top };
    }

    function reaquecer() {
      if (parado) return;
      if (iteracao >= MAX_ITERACOES) {
        iteracao = MAX_ITERACOES - 160; // reaquece sem recomeçar do zero
        animar();
      }
    }

    canvas.onmousemove = function (ev) {
      var p = posicao(ev);
      if (arrastando) {
        arrastando.x = p.x;
        arrastando.y = p.y;
        arrastando.vx = 0;
        arrastando.vy = 0;
        reaquecer();
        pintar();
        return;
      }
      var no = noPonto(p.x, p.y);
      if (no !== destacado) {
        destacado = no;
        canvas.style.cursor = no ? "pointer" : "default";
        pintar();
      }
    };

    canvas.onmouseleave = function () {
      if (destacado) {
        destacado = null;
        pintar();
      }
    };

    canvas.onmousedown = function (ev) {
      var p = posicao(ev);
      var no = noPonto(p.x, p.y);
      if (no) {
        arrastando = no;
        ev.preventDefault();
      }
    };

    global.addEventListener("mouseup", function () {
      if (!arrastando) return;
      var tocado = arrastando;
      arrastando = null;
      reaquecer();
      // Clique (sem arrastar longe) abre o conceito.
      if (Math.abs(tocado.vx) < 1 && Math.abs(tocado.vy) < 1) {
        selecionado = tocado;
        pintar();
        if (opt.aoClicar) opt.aoClicar(tocado.id);
      }
    });

    animar();

    return {
      parar: function () {
        parado = true;
      },
      pintar: pintar,
      selecionar: function (id) {
        selecionado = porId[id] || null;
        pintar();
      },
      nos: nos,
    };
  }

  global.GrafoFrutiger = { desenhar: desenhar };
})(window);
