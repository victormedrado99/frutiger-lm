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

  /* A cor do nó saiu do caderno e virou uma só: azul-claro de vidro (a bolha, no
     `pintar`). A identidade do caderno não se perdeu — no mapa o próprio nó tem o nome
     do caderno escrito nele, e dentro de um caderno todos os conceitos são dele (menos
     as pontes, que ganham a aura). Uma cor por caderno era uma legenda a mais para
     aprender, e a paleta dava laranja e rosa a um app ciano. */

  /* O tipo de aresta, traduzido para o que o desenho decide.

     Mora numa tabela, e não num `if` dentro do laço de desenho, porque é ela que
     garante a regra da D063: a aresta INFERIDA nunca entra na família das que o
     material sustenta. Um tipo que este mapa não conhece cai em "outra" — que o
     desenho desenha como o traço mais fraco. */
  var TIPOS_DE_ARESTA = {
    explicit: "afirmada",
    similarity: "similaridade",
    co_occurrence: "co_ocorrencia",
  };

  function tipoDeAresta(kind) {
    return TIPOS_DE_ARESTA[kind] || "outra";
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
          /* O traço sai do TIPO, e não de "é diferente de co-ocorrência" (D063).

             Aquela forma era um defeito à espera do terceiro tipo: `afirmada =
             kind !== "co_occurrence"` mandava QUALQUER tipo novo para o traço das
             ligações que o material afirma. Com o F6, a aresta por similaridade — que é
             inferida por um modelo e não tem trecho nenhum — apareceria desenhada como
             afirmação do material, que é justamente o que este projeto não faz.

             Tipo desconhecido cai no traço mais fraco, nunca no mais forte. */
          tipo: tipoDeAresta(aresta.kind),
          nota: aresta.score || 0,
          peso: aresta.weight || 1,
        };
      })
      .filter(function (aresta) {
        return aresta.a && aresta.b;
      });

    /* ---- o anel dos cadernos --------------------------------------------------

       No MAPA, cada caderno é um nó e cada nó tem a sua própria "ilha" — o que, na
       prática, é a posição dele no anel. A regra que já existia continua valendo: cada
       nó é puxado para o centro de **cada** caderno dele.

       - No mapa cada nó pertence a um caderno só, então cada um vai para o seu lugar do
         anel, e os cadernos ficam distribuídos.
       - Num grafo de conceitos (dentro de um caderno) o `cadernoFoco` manda: existe um
         centro só, e o desenho volta a ser o círculo de sempre.

       Um conceito que aparece em DOIS cadernos é puxado para os dois centros e assenta
       entre eles — a ponte não tem caso especial: é a soma das forças.
    */
    var ilhas = {};
    var titulosDasIlhas = [];

    /* Quando a vista está presa a UM caderno, não existem ilhas: o grafo É aquele
       caderno, e volta a ser o círculo único de sempre.

       Sem esta trava, um conceito-ponte continuava dizendo que pertence a dois cadernos
       — o que é VERDADE no banco — e o desenho abria duas ilhas dentro de uma vista de
       um caderno só. Quem sabe o escopo é a interface; ela é que diz. */
    var cadernoFoco = opt.cadernoFoco || null;

    function montarIlhas() {
      if (cadernoFoco) {
        titulosDasIlhas = [cadernoFoco];
        ilhas = {};
        ilhas[cadernoFoco] = { x: largura / 2, y: altura / 2 };
        return;
      }

      titulosDasIlhas = [];
      nos.forEach(function (no) {
        (no.cadernos || []).forEach(function (t) {
          if (titulosDasIlhas.indexOf(t) < 0) titulosDasIlhas.push(t);
        });
      });
      titulosDasIlhas.sort();

      var cx = largura / 2;
      var cy = altura / 2;
      ilhas = {};
      if (!titulosDasIlhas.length) return;
      if (titulosDasIlhas.length === 1) {
        // Um caderno só não forma ilha: o grafo É ele. O centro é o do quadro, que é
        // o comportamento redondo de sempre.
        ilhas[titulosDasIlhas[0]] = { x: cx, y: cy };
        return;
      }

      /* Os centros numa roda, e o raio tem que VENCER o tamanho das ilhas.

         O raio de uma ilha cresce com a raiz do número de nós (é o mesmo equilíbrio
         entre gravidade e repulsão do círculo). Com um raio fixo, uma ilha de trinta
         nós engolia uma de quatro — a pequena ficava dentro da grande. Fazendo o anel
         crescer com a raiz do total, a separação acompanha o tamanho das ilhas.

         O valor absoluto não importa: a vista encaixa o conjunto na tela depois. O que
         importa é a razão entre a separação e o tamanho de cada ilha. */
      var raio = Math.sqrt(nos.length) * 34 + 40;
      titulosDasIlhas.forEach(function (t, i) {
        var ang = (i / titulosDasIlhas.length) * Math.PI * 2 - Math.PI / 2;
        ilhas[t] = { x: cx + Math.cos(ang) * raio, y: cy + Math.sin(ang) * raio };
      });
    }

    function alvoDoNo(no) {
      var meus = (no.cadernos || []).filter(function (t) {
        return ilhas[t] !== undefined;
      });
      if (!meus.length) return { x: largura / 2, y: altura / 2 };
      var sx = 0;
      var sy = 0;
      meus.forEach(function (t) {
        sx += ilhas[t].x;
        sy += ilhas[t].y;
      });
      return { x: sx / meus.length, y: sy / meus.length };
    }

    montarIlhas();

    var selecionado = null;
    var destacado = null;
    /* A caixa de cada rótulo aceito, por id de nó. Fica fora do `pintar` porque o
       clique também precisa dela: o rótulo é área de acerto (ver `noPonto`). */
    var caixasDeRotulo = {};
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
        // Quem o material afirma fica mais perto; inferida e co-ocorrência puxam menos.
        var forte = aresta.tipo === "afirmada";
        var alvo = forte ? 96 : 124;
        var forca = (d - alvo) * (forte ? 0.020 : 0.010);
        var ux = dx / d;
        var uy = dy / d;
        aresta.a.vx += ux * forca;
        aresta.a.vy += uy * forca;
        aresta.b.vx -= ux * forca;
        aresta.b.vy -= uy * forca;
      });

      // Gravidade de ilha: cada nó é puxado para o centro de cada caderno dele. O
      // conceito que vive em dois é puxado para os dois e assenta entre eles.
      nos.forEach(function (no) {
        var alvo = alvoDoNo(no);
        no.vx += (alvo.x - no.x) * GRAVIDADE;
        no.vy += (alvo.y - no.y) * GRAVIDADE;
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
      var alvoL = largura / 2 - 5;
      var alvoA = altura / 2 - 5;
      var escala = 1.2;

      /* Duas passadas, e não uma conta fechada, por um motivo: o raio do nó encolhe com
         a RAIZ da escala, o halo é proporcional ao raio e o rótulo não encolhe NADA. As
         três coisas dependem da escala de formas diferentes, então a primeira passada
         estima e a segunda corrige.

         A folga existe porque o nó não é só o círculo: a bolha tem halo em volta, e o
         rótulo fica embaixo dela. Sem contar isso, o desenho encostava na borda e os
         nós das pontas saíam cortados. */
      for (var volta = 0; volta < 2; volta++) {
        var maiorL = 0;
        var maiorA = 0;
        nos.forEach(function (no) {
          var r = Math.max(2.6, no.raio * Math.sqrt(escala));
          var folgaX = r * 0.8;
          var folgaY = r * 0.8 + 17; // o rótulo embaixo do nó
          maiorL = Math.max(maiorL, Math.abs(no.x - cx) * escala + r + folgaX);
          maiorA = Math.max(maiorA, Math.abs(no.y - cy) * escala + r + folgaY);
        });
        var ajuste = Math.min(alvoL / maiorL, alvoA / maiorA);
        // O teto de 1.2 evita que um grafo de três nós vire três bolas gigantes; o piso
        // de 0.3 evita que um grafo enorme vire poeira.
        escala = Math.max(0.3, Math.min(1.2, escala * ajuste));
      }
      return escala;
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
      // As caixas de acerto são recalculadas a cada pintura: o conjunto de rótulos
      // aceitos muda com o foco, e um clique não pode acertar um rótulo que já não
      // está no desenho.
      caixasDeRotulo = {};

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
        caixasDeRotulo[no.id] = caixa;
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
        if (aresta.tipo === "afirmada") {
          // Afirmada pelo material: linha cheia e mais clara.
          ctx.strokeStyle = aceso ? "rgba(160, 240, 255, 0.72)" : "rgba(120, 170, 190, 0.16)";
          ctx.lineWidth = aceso ? 1.9 : 1;
        } else if (aresta.tipo === "similaridade") {
          /* Inferida pelo app (F6): tracejada longa, fina e mais apagada que a afirmada.

             O peso visual foi MEDIDO, e não escolhido a olho: com alfa 0,26+0,34*nota o
             traço ficava com 13 pixels visíveis contra 1428 co-ocorrências por cima —
             ou seja, existia no código e não existia na tela. Agora ele aparece sem
             chegar perto da linha cheia, porque a hierarquia tem que continuar óbvia:
             o que o material afirma é o mais forte; o que o app achou, o mais fraco. */
          ctx.setLineDash([8, 5]);
          ctx.strokeStyle = aceso
            ? "rgba(186, 158, 255, " + (0.40 + 0.45 * Math.max(0, Math.min(1, aresta.nota))) + ")"
            : "rgba(150, 130, 200, 0.10)";
          ctx.lineWidth = aceso ? 1.3 : 1;
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

      /* A BOLHA — o nó desenhado como vidro Frutiger Aero.

         Quatro coisas fazem a leitura de 3D, e são as quatro de um balão de vidro:

         1. a luz vem de cima e da esquerda — o gradiente é deslocado para lá, e é isso
            que decide onde a bolha é clara e onde ela é funda;
         2. o brilho especular — o reflexo da janela, o ponto branco que diz "vidro" e
            não "círculo pintado";
         3. a luz que atravessa e volta por baixo — o arco claro na base, que faz a bolha
            parecer cheia em vez de chapada;
         4. o aro — claro onde bate luz, escuro do outro lado.

         O halo existe por um motivo prático: o fundo é escuro, e sem ele o nó parece um
         adesivo colado no painel em vez de uma bolha sobre ele.
      */
      function bolha(x, y, r, alfa) {
        var g = ctx.createRadialGradient(
          x - r * 0.34, y - r * 0.4, Math.max(0.5, r * 0.08), x, y, r * 1.04
        );
        g.addColorStop(0, "rgba(250, 254, 255, 1)");
        g.addColorStop(0.3, "rgba(178, 235, 250, 1)");
        g.addColorStop(0.66, "rgba(86, 186, 226, 1)");
        g.addColorStop(1, "rgba(36, 106, 150, 1)");

        ctx.globalAlpha = alfa;
        ctx.save();
        ctx.shadowColor = "rgba(118, 220, 255, 0.7)";
        ctx.shadowBlur = r * 1.6;
        ctx.beginPath();
        ctx.arc(x, y, r, 0, Math.PI * 2);
        ctx.fillStyle = g;
        ctx.fill();
        ctx.restore();

        ctx.globalAlpha = alfa;
        var aro = ctx.createLinearGradient(x - r * 0.7, y - r * 0.7, x + r * 0.7, y + r * 0.7);
        aro.addColorStop(0, "rgba(255, 255, 255, 0.95)");
        aro.addColorStop(0.45, "rgba(196, 242, 255, 0.4)");
        aro.addColorStop(1, "rgba(16, 54, 84, 0.6)");
        ctx.beginPath();
        ctx.arc(x, y, Math.max(1, r - 0.7), 0, Math.PI * 2);
        ctx.strokeStyle = aro;
        ctx.lineWidth = 1.4;
        ctx.stroke();

        if (r > 4) {
          ctx.beginPath();
          ctx.ellipse(x - r * 0.32, y - r * 0.42, r * 0.3, r * 0.19, -0.5, 0, Math.PI * 2);
          ctx.fillStyle = "rgba(255, 255, 255, 0.92)";
          ctx.fill();

          ctx.beginPath();
          ctx.ellipse(x + r * 0.06, y + r * 0.48, r * 0.4, r * 0.2, 0, 0, Math.PI * 2);
          ctx.fillStyle = "rgba(214, 248, 255, 0.45)";
          ctx.fill();
        }
        ctx.globalAlpha = 1;
      }

      nos.forEach(function (no) {
        var aceso = !foco || no === foco || (vizinhos && vizinhos[no.id]);

        // Ponte entre cadernos: uma aura em volta da bolha. É a informação que mais
        // interessa no desenho, então ela ganha um sinal que não é cor de preenchimento —
        // a bolha continua azul, e a aura diz que aquele conceito atravessa cadernos.
        if (no.ponte) {
          ctx.save();
          ctx.globalAlpha = aceso ? 0.9 : 0.2;
          ctx.shadowColor = "rgba(150, 235, 255, 0.9)";
          ctx.shadowBlur = 12;
          ctx.beginPath();
          ctx.arc(no._sx, no._sy, no._sr + 5.5, 0, Math.PI * 2);
          ctx.strokeStyle = "rgba(226, 250, 255, 0.9)";
          ctx.lineWidth = 1.8;
          ctx.stroke();
          ctx.restore();
        }

        bolha(no._sx, no._sy, no._sr, aceso ? 1 : 0.2);

        if (no === foco) {
          ctx.beginPath();
          ctx.arc(no._sx, no._sy, no._sr + 3.5, 0, Math.PI * 2);
          ctx.strokeStyle = "rgba(255, 255, 255, 0.85)";
          ctx.lineWidth = 1.6;
          ctx.stroke();
        }

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

    /* Onde o ponteiro acerta um nó.

       Duas folgas, e as duas vêm do que o olho faz na tela:

       1. A bolha tem HALO, e o halo é bem maior que o raio — quem mira na borda
          visível está mirando fora do círculo. O alvo acompanha o que se vê, e não a
          geometria: um alvo que não bate com o desenho é um clique que "não funciona".
       2. O RÓTULO também é clicável. Ele é o pedaço maior e mais óbvio do conjunto, e
          clicar no nome do caderno e não acontecer nada é o que faz parecer quebrado.

       O círculo é testado primeiro (perto do centro manda), e o rótulo depois. */
    function noPonto(x, y) {
      var i;
      var no;
      for (i = nos.length - 1; i >= 0; i--) {
        no = nos[i];
        // O clique é em coordenada de TELA; o nó guarda a posição "de mundo". A
        // conversão está feita em `_sx/_sy`, que `pintar` preenche.
        var sx = no._sx === undefined ? no.x : no._sx;
        var sy = no._sy === undefined ? no.y : no._sy;
        var sr = no._sr === undefined ? no.raio : no._sr;
        var dx = sx - x;
        var dy = sy - y;
        var alcance = sr * 1.35 + 6;
        if (dx * dx + dy * dy <= alcance * alcance) return no;
      }
      for (i = nos.length - 1; i >= 0; i--) {
        var caixa = caixasDeRotulo[nos[i].id];
        if (!caixa) continue;
        if (x >= caixa[0] && x <= caixa[2] && y >= caixa[1] && y <= caixa[3]) return nos[i];
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
        montarIlhas(); // as ilhas dependem do tamanho do quadro
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
