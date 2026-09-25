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
    var inicioDoArraste = null;
    var arrastou = false;
    var parado = false;
    var iteracao = 0;
    var escala = 1;
    var MAX_ITERACOES = 420;

    /* ---- os parâmetros da simulação -------------------------------------------

       O círculo NÃO é desenhado: ele é o EQUILÍBRIO entre duas forças. A gravidade
       puxa cada nó para o centro proporcionalmente à distância; a repulsão empurra
       todos os pares para longe. Num disco de N nós o raio de equilíbrio cresce com
       a raiz cúbica de N, então o desenho fica redondo sozinho — nem vira retângulo,
       nem vira linha, e cresce para acomodar mais conceitos.

       Antes disto, quem dava a forma ao desenho era o `clamp` do retângulo do
       quadro: os nós eram empurrados para fora pela repulsão até bater na borda e
       ficavam ali. A forma final era a do quadro, não a da física. Agora o limite é
       circular, e o retângulo não participa mais.

       Gravidade LINEAR de propósito. Com 1/d² o nó distante seria puxado fraco
       demais, e a borda do círculo ficaria frouxa e tremida.
    */
    var GRAVIDADE = 0.021;
    var REPULSAO = 3300;
    var DIST_MIN = 24;
    var AMORTECIMENTO = 0.86;
    var VELOCIDADE_MAX = 6;

    function passo() {
      var n = nos.length;
      if (!n) return;

      var cx = largura / 2;
      var cy = altura / 2;

      // Repulsão entre todos os pares. O(n²) é aceitável no tamanho que este grafo
      // tem (dezenas a poucas centenas de nós) e é o que mantém o desenho legível.
      for (var i = 0; i < n; i++) {
        var a = nos[i];
        for (var j = i + 1; j < n; j++) {
          var b = nos[j];
          var dx = b.x - a.x;
          var dy = b.y - a.y;
          var d2 = dx * dx + dy * dy;
          if (d2 < 0.01) {
            // Dois nós exatamente no mesmo ponto: separa num sentido qualquer.
            dx = (i % 2 ? 1 : -1) * 0.5;
            dy = (j % 2 ? 1 : -1) * 0.5;
            d2 = 0.5;
          }
          var d = Math.sqrt(d2);
          // Piso na distância: sem ele, dois nós vizinhos recebem um empurrão
          // gigante e o desenho inteiro treme.
          var forca = REPULSAO / Math.max(d2, DIST_MIN * DIST_MIN);
          var ux = dx / d;
          var uy = dy / d;
          a.vx -= ux * forca;
          a.vy -= uy * forca;
          b.vx += ux * forca;
          b.vy += uy * forca;
        }
      }

      // Mola nas arestas: mais fraca que a gravidade, senão a estrutura das ligações
      // vence e o desenho deixa de ser redondo. Aqui ela só aproxima quem se liga.
      arestas.forEach(function (aresta) {
        var dx = aresta.b.x - aresta.a.x;
        var dy = aresta.b.y - aresta.a.y;
        var d = Math.sqrt(dx * dx + dy * dy) || 0.01;
        var alvo = aresta.afirmada ? 96 : 124;
        var forca = (d - alvo) * (aresta.afirmada ? 0.020 : 0.010);
        var ux = dx / d;
        var uy = dy / d;
        aresta.a.vx += ux * forca;
        aresta.a.vy += uy * forca;
        aresta.b.vx -= ux * forca;
        aresta.b.vy -= uy * forca;
      });

      // Gravidade ao centro: é ela que fecha o círculo.
      nos.forEach(function (no) {
        no.vx += (cx - no.x) * GRAVIDADE;
        no.vy += (cy - no.y) * GRAVIDADE;
      });

      /* Não existe mais limite de raio.

         A gravidade cresce com a distância e a repulsão cai com ela, então existe um
         raio de equilíbrio e o desenho se limita sozinho — não precisa de cerca. E
         uma cerca era justamente o que estragava tudo: com `raioMax` calculado do
         quadro (min(largura, altura)/2 - margem), um grafo de 102 nós num canvas de
         238px de altura ficava com uma cerca MENOR do que o espaço que os nós
         precisam para não se sobrepor. A física vencia a cerca, os nós transbordavam
         por cima e por baixo, e o formato deixava de ser redondo.

         Agora quem acomoda o tamanho é a vista (ver `calcularEscala`). */

      // Integração, com teto de velocidade para o desenho não explodir.
      nos.forEach(function (no) {
        no.vx *= AMORTECIMENTO;
        no.vy *= AMORTECIMENTO;
        if (no === arrastando) return;
        var v = Math.sqrt(no.vx * no.vx + no.vy * no.vy);
        if (v > VELOCIDADE_MAX) {
          no.vx *= VELOCIDADE_MAX / v;
          no.vy *= VELOCIDADE_MAX / v;
        }
        no.x += no.vx;
        no.y += no.vy;
      });
    }

    /* A vista encaixa o desenho no quadro.

       A física decide o TAMANHO RELATIVO (o equilíbrio entre gravidade e repulsão,
       que cresce com o número de nós). A vista decide quanto disso cabe na tela.

       Sem esta separação, o tamanho do quadro decidia o desenho: num canvas baixo o
       grafo transbordava, num canvas grande ficava perdido num canto. Com ela, o
       mesmo grafo parece o mesmo círculo em qualquer tamanho de barra.

       A escala é aplicada à mão (e não com `ctx.scale`) por um motivo: o texto do
       rótulo não pode encolher junto. Num grafo apertado a escala fica em ~0,5, e um
       rótulo de 11px viraria 5px ilegível.
    */
    function calcularEscala() {
      var cx = largura / 2;
      var cy = altura / 2;
      var maior = 0;
      nos.forEach(function (no) {
        var d = Math.sqrt((no.x - cx) * (no.x - cx) + (no.y - cy) * (no.y - cy)) + no.raio;
        if (d > maior) maior = d;
      });
      if (maior < 1) return 1;
      var alvo = Math.min(largura, altura) / 2 - 8;
      // O teto de 1.2 evita que um grafo de três nós vire três bolas gigantes; o piso
      // de 0.3 evita que um grafo enorme vire poeira.
      return Math.max(0.3, Math.min(1.2, alvo / maior));
    }

    function atualizarTela() {
      var cx = largura / 2;
      var cy = altura / 2;
      nos.forEach(function (no) {
        no._sx = cx + (no.x - cx) * escala;
        no._sy = cy + (no.y - cy) * escala;
        // O raio encolhe com a raiz da escala: com a escala cheia os nós sumiriam
        // antes das arestas, e o desenho perderia justamente os pontos.
        no._sr = Math.max(2.6, no.raio * Math.sqrt(escala));
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

      escala = calcularEscala();
      atualizarTela();

      var vizinhos = destacado || selecionado ? ligadoA(destacado || selecionado) : null;
      var foco = destacado || selecionado;

      /* Quais rótulos entram — decidido por COLISÃO, não por contagem.

         Contar não resolve: num grafo em círculo os dez conceitos mais mencionados
         ficam todos no miolo, e um teto de dez rótulos põe exatamente esses dez um
         em cima do outro. Aqui os candidatos são ordenados por importância e cada um
         só entra se a caixa do texto não bater na de nenhum já aceito. Efeito
         colateral bem-vindo: quanto mais espalhado o nó, mais chance ele tem de
         ganhar rótulo — que é o que se quer.

         O foco (ponteiro ou seleção) entra PRIMEIRO, então ele nunca perde o rótulo
         para outro nó: é assim que se lê o nome de qualquer ponto do desenho. */
      ctx.font = "600 11px 'Segoe UI', system-ui, sans-serif";
      var caixas = [];
      var rotulos = {};
      var pendentes = [];

      function posicionarRotulo(no) {
        // O rótulo é centrado no nó, e o nó pode estar na borda do círculo — então um
        // nome comprido sairia cortado. Aqui ele é deslocado só o suficiente para
        // caber: rótulo cortado não é rótulo.
        var meio = ctx.measureText(no.nome).width / 2;
        var tx = Math.max(4 + meio, Math.min(largura - 4 - meio, no._sx));
        var ty = Math.min(altura - 15, no._sy + no._sr + 3);
        // A folga é generosa de propósito: uma caixa do tamanho exato do texto deixa
        // duas linhas vizinhas passarem raspando, e o resultado na tela é texto
        // encostado. 18px de altura para uma linha de 11px dá o respiro que falta.
        var caixa = [tx - meio - 4, ty - 3, tx + meio + 4, ty + 15];
        for (var i = 0; i < caixas.length; i++) {
          var b = caixas[i];
          if (caixa[0] < b[2] && caixa[2] > b[0] && caixa[1] < b[3] && caixa[3] > b[1]) {
            return null;
          }
        }
        caixas.push(caixa);
        return { tx: tx, ty: ty };
      }

      var candidatos = [];
      if (foco) candidatos.push(foco);
      nos
        .slice()
        .sort(function (a, b) { return b.mencoes - a.mencoes; })
        .forEach(function (no) {
          if (no === foco) return;
          var aceso = !foco || (vizinhos && vizinhos[no.id]);
          if (aceso) candidatos.push(no);
        });
      candidatos.forEach(function (no) {
        if (no._sx !== undefined) rotulos[no.id] = posicionarRotulo(no);
      });

      arestas.forEach(function (aresta) {
        var aceso = !foco || aresta.a === foco || aresta.b === foco;
        ctx.beginPath();
        ctx.moveTo(aresta.a._sx, aresta.a._sy);
        ctx.lineTo(aresta.b._sx, aresta.b._sy);
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
          ctx.arc(no._sx, no._sy, no._sr + 5, 0, Math.PI * 2);
          ctx.strokeStyle = "rgba(240, 180, 95, 0.85)";
          ctx.lineWidth = 2;
          ctx.stroke();
        }

        ctx.beginPath();
        ctx.arc(no._sx, no._sy, no._sr, 0, Math.PI * 2);
        ctx.fillStyle = no.cor;
        ctx.globalAlpha = aceso ? 0.9 : 0.2;
        ctx.fill();

        if (no === foco) {
          ctx.beginPath();
          ctx.arc(no._sx, no._sy, no._sr + 3, 0, Math.PI * 2);
          ctx.strokeStyle = "#ffffff";
          ctx.lineWidth = 1.6;
          ctx.stroke();
        }
        ctx.globalAlpha = aceso ? 1 : 0.2;

        // Rótulo: só para quem ganhou lugar na decisão de colisão, no topo do
        // `pintar` — e nunca num nó apagado pelo foco. A pintura fica para o fim, numa
        // passada só de texto: assim nenhum nó desenhado depois passa por cima de um
        // rótulo, e o texto fica sempre por cima do desenho.
        var rotulo = aceso ? rotulos[no.id] : null;
        if (rotulo) pendentes.push({ nome: no.nome, tx: rotulo.tx, ty: rotulo.ty, foco: no === foco });
        ctx.globalAlpha = 1;
      });

      // Passada do texto, por último.
      ctx.textAlign = "center";
      ctx.textBaseline = "top";
      pendentes.forEach(function (r) {
        ctx.fillStyle = "rgba(0, 0, 0, 0.55)";
        ctx.fillText(r.nome, r.tx + 1, r.ty + 1);
        ctx.fillStyle = r.foco ? "#ffffff" : "#cfe9f2";
        ctx.fillText(r.nome, r.tx, r.ty);
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
        // O clique é em coordenada de TELA; o nó guarda a posição "de mundo". A
        // conversão está feita em `_sx/_sy`, que `pintar` preenche.
        var sx = no._sx === undefined ? no.x : no._sx;
        var sy = no._sy === undefined ? no.y : no._sy;
        var sr = no._sr === undefined ? no.raio : no._sr;
        var dx = sx - x;
        var dy = sy - y;
        if (dx * dx + dy * dy <= (sr + 5) * (sr + 5)) return no;
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
        // Da tela para o mundo: a escala da vista é desfeita, senão o nó arrastado
        // andaria mais rápido (ou mais devagar) que o ponteiro.
        arrastando.x = largura / 2 + (p.x - largura / 2) / escala;
        arrastando.y = altura / 2 + (p.y - altura / 2) / escala;
        arrastando.vx = 0;
        arrastando.vy = 0;
        if (!arrastou && inicioDoArraste) {
          var mexeu = Math.hypot(p.x - inicioDoArraste.x, p.y - inicioDoArraste.y);
          if (mexeu > 4) arrastou = true;
        }
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
        inicioDoArraste = p;
        arrastou = false;
        ev.preventDefault();
      }
    };

    global.addEventListener("mouseup", function () {
      if (!arrastando) return;
      var tocado = arrastando;
      arrastando = null;
      reaquecer();
      /* Clique é clique; arrastar é arrastar.

         A checagem antiga era `Math.abs(vx) < 1`, e nunca falhava: o arraste zera a
         velocidade a cada movimento do ponteiro, então TODO arraste também abria o
         conceito — quem tentava reorganizar o desenho via o painel abrir por cima.
         Agora o que decide é a distância percorrida desde o `mousedown`. */
      if (!arrastou) {
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
      /* Re-mede o canvas e redesenha sem recompor a simulação do zero.

         Precisa existir porque o painel pode ficar escondido — e um canvas escondido
         tem clientWidth 0. Desenhar assim daria um grafo de tamanho errado que só
         apareceria quando a pessoa abrisse a aba. Se o tamanho mudou de verdade
         (uma janela redimensionada), aí sim reaquece, porque os nós estão nas
         coordenadas antigas. */
      reajustar: function () {
        var l = canvas.clientWidth;
        var a = canvas.clientHeight;
        if (!l || !a) return;
        if (l === largura && a === altura) {
          pintar();
          return;
        }
        largura = l;
        altura = a;
        canvas.width = Math.round(l * dpr);
        canvas.height = Math.round(a * dpr);
        ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
        reaquecer();
        pintar();
      },
      selecionar: function (id) {
        selecionado = porId[id] || null;
        pintar();
      },
      nos: nos,
    };
  }

  global.GrafoFrutiger = { desenhar: desenhar };
})(window);
