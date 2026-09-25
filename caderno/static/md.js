/* md.js — renderizador Markdown mínimo, autocontido e seguro (sem CDN).
   O texto é escapado ANTES de qualquer transformação, então HTML vindo do
   modelo ou das fontes não é interpretado. */

(function (global) {
  "use strict";

  function esc(s) {
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  var CODE_SLOT = "\u0000CODE";
  var U = "\u0000";

  function inline(text) {
    var out = esc(text);
    var codes = [];

    out = out.replace(/`([^`]+)`/g, function (_m, c) {
      codes.push(c);
      return CODE_SLOT + (codes.length - 1) + U;
    });

    out = out.replace(
      /\[([^\]\n]+)\]\((https?:\/\/[^\s)]+|mailto:[^\s)]+)\)/g,
      '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>'
    );
    out = out.replace(
      /(^|[\s(])(https?:\/\/[^\s<)"']+)/g,
      '$1<a href="$2" target="_blank" rel="noopener noreferrer">$2</a>'
    );
    out = out.replace(/\*\*\*([^*\n]+)\*\*\*/g, "<strong><em>$1</em></strong>");
    out = out.replace(/\*\*([^*\n]+)\*\*/g, "<strong>$1</strong>");
    out = out.replace(/(^|[^\w*])__([^_\n]+)__/g, "$1<strong>$2</strong>");
    out = out.replace(/(^|[^*\w])\*([^*\n]+)\*/g, "$1<em>$2</em>");
    out = out.replace(/(^|[^_\w])_([^_\n]+)_(?!\w)/g, "$1<em>$2</em>");
    out = out.replace(/~~([^~\n]+)~~/g, "<del>$1</del>");
    out = out.replace(/\n/g, "<br>");

    out = out.replace(new RegExp(CODE_SLOT + "(\\d+)" + U, "g"), function (_m, i) {
      return "<code>" + codes[Number(i)] + "</code>";
    });
    return out;
  }

  function isTableSep(line) {
    return /^\s*\|?[\s:|-]*-[\s:|-]*\|?\s*$/.test(line) && line.indexOf("-") !== -1 && line.indexOf("|") !== -1;
  }

  function splitRow(line) {
    var t = line.trim().replace(/^\|/, "").replace(/\|$/, "");
    return t.split("|").map(function (c) { return c.trim(); });
  }

  function render(src) {
    var text = String(src == null ? "" : src).replace(/\r\n?/g, "\n");
    var lines = text.split("\n");
    var html = [];
    var para = [];
    var listStack = []; // {type, indent}
    var i = 0;

    function flushPara() {
      if (para.length) {
        html.push("<p>" + inline(para.join(" ")) + "</p>");
        para = [];
      }
    }
    function flushLists() {
      while (listStack.length) {
        var t = listStack.pop().type;
        html.push("</li>");
        html.push(t === "ol" ? "</ol>" : "</ul>");
      }
    }
    function closeListsTo(indent) {
      while (listStack.length && listStack[listStack.length - 1].indent > indent) {
        var t = listStack.pop().type;
        html.push("</li>");
        html.push(t === "ol" ? "</ol>" : "</ul>");
      }
    }

    while (i < lines.length) {
      var line = lines[i];

      // linha vazia -> fecha parágrafo
      if (!line.trim()) {
        flushPara();
        flushLists();
        i++;
        continue;
      }

      // código cercado
      var fence = line.match(/^\s*```(\S*)\s*$/);
      if (fence) {
        flushPara();
        flushLists();
        var lang = fence[1] || "";
        var buf = [];
        i++;
        while (i < lines.length && !/^\s*```\s*$/.test(lines[i])) {
          buf.push(lines[i]);
          i++;
        }
        i++; // fecha a cerca
        html.push(
          '<pre><code' + (lang ? ' class="lang-' + esc(lang) + '"' : "") + ">" +
            esc(buf.join("\n")) + "</code></pre>"
        );
        continue;
      }

      // cabeçalho
      var head = line.match(/^\s*(#{1,6})\s+(.*)$/);
      if (head) {
        flushPara();
        flushLists();
        var level = head[1].length;
        html.push("<h" + level + ">" + inline(head[2].replace(/\s*#+\s*$/, "")) + "</h" + level + ">");
        i++;
        continue;
      }

      // régua
      if (/^\s*(-{3,}|\*{3,}|_{3,})\s*$/.test(line)) {
        flushPara();
        flushLists();
        html.push("<hr>");
        i++;
        continue;
      }

      // tabela
      if (line.indexOf("|") !== -1 && i + 1 < lines.length && isTableSep(lines[i + 1])) {
        flushPara();
        flushLists();
        var header = splitRow(line);
        i += 2;
        var rows = [];
        while (i < lines.length && lines[i].indexOf("|") !== -1 && lines[i].trim()) {
          rows.push(splitRow(lines[i]));
          i++;
        }
        var tHtml = ["<table><thead><tr>"];
        header.forEach(function (c) { tHtml.push("<th>" + inline(c) + "</th>"); });
        tHtml.push("</tr></thead><tbody>");
        rows.forEach(function (r) {
          tHtml.push("<tr>");
          for (var c = 0; c < header.length; c++) {
            tHtml.push("<td>" + inline(r[c] === undefined ? "" : r[c]) + "</td>");
          }
          tHtml.push("</tr>");
        });
        tHtml.push("</tbody></table>");
        html.push(tHtml.join(""));
        continue;
      }

      // citação
      if (/^\s*>/.test(line)) {
        flushPara();
        flushLists();
        var quote = [];
        while (i < lines.length && /^\s*>/.test(lines[i])) {
          quote.push(lines[i].replace(/^\s*>\s?/, ""));
          i++;
        }
        html.push("<blockquote>" + render(quote.join("\n")) + "</blockquote>");
        continue;
      }

      // listas
      var item = line.match(/^(\s*)([-*+]|\d+[.)])\s+(.*)$/);
      if (item) {
        flushPara();
        var indent = item[1].replace(/\t/g, "  ").length;
        var type = /^\d/.test(item[2]) ? "ol" : "ul";
        closeListsTo(indent);
        if (!listStack.length || listStack[listStack.length - 1].indent < indent) {
          listStack.push({ type: type, indent: indent });
          html.push(type === "ol" ? "<ol>" : "<ul>");
        } else if (listStack[listStack.length - 1].type !== type) {
          var prev = listStack.pop().type;
          html.push("</li>");
          html.push(prev === "ol" ? "</ol>" : "</ul>");
          listStack.push({ type: type, indent: indent });
          html.push(type === "ol" ? "<ol>" : "<ul>");
        } else {
          html.push("</li>");
        }
        // continuação: linhas indentadas que não abrem um novo item
        var content = item[3];
        i++;
        while (
          i < lines.length &&
          /^\s{2,}\S/.test(lines[i]) &&
          !/^\s*([-*+]|\d+[.)])\s+/.test(lines[i])
        ) {
          content += " " + lines[i].trim();
          i++;
        }
        html.push("<li>" + inline(content));
        continue;
      }

      // parágrafo
      para.push(line.trim());
      i++;
    }

    flushPara();
    flushLists();
    return html.join("\n");
  }

  global.renderMarkdown = render;
})(window);
