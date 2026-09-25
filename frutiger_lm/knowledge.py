"""A loja do grafo de conhecimento (F3).

Nó = conceito, aresta = relação, e a **menção** é o que ancora o nó à fonte.

A regra da fase, e a única coisa que faz este grafo valer alguma coisa:

    A menção só é gravada se o trecho existir, de fato, no texto de referência.

O extrator devolve o trecho verbatim e `registrar_mencao` confere contra o texto que
o chamador tem em mãos. Trecho que não casa **não é gravado**. Sem isso o grafo
seria um desenho plausível de coisas que ninguém disse — e ninguém perceberia, que é
o pior tipo de defeito.

Toda leitura e escrita do grafo passa por aqui: é o que faz o botão da interface e a
ferramenta do agente serem a mesma implementação (D024).
"""

from __future__ import annotations

import json
import re
import time
import unicodedata
import uuid
from typing import Any

from .db import connect

# --------------------------------------------------------------------------
# Tipos de aresta. `co_occurrence` sai de graça do bloco; `explicit` é afirmada
# (pelo modelo ou pela pessoa) e exige trecho; `similarity` é do F6.
# --------------------------------------------------------------------------
CO_OCORRENCIA = "co_occurrence"
EXPLICITA = "explicit"
SIMILARIDADE = "similarity"

TIPOS = (CO_OCORRENCIA, EXPLICITA, SIMILARIDADE)


def _id(prefixo: str) -> str:
    return f"{prefixo}_{uuid.uuid4().hex[:12]}"


def _now() -> float:
    return time.time()


# --------------------------------------------------------------------------
# Normalização e conferência — o coração desta fase
# --------------------------------------------------------------------------


def normalizar(nome: str) -> str:
    """A chave canônica de um conceito.

    Minúsculas, sem acento, pontuação virando espaço, espaços colapsados. É o que
    deduplica de graça, sem modelo: `OBD-II`, `OBD II` e `obd ii` caem todos em
    `obd ii`.

    O que isto NÃO resolve, de propósito: `OBD2` normaliza para `obd2`, que é outra
    chave. Forçar equivalência entre dígito e número romano quebraria `ISO 14230-4`
    e outros nomes que legitimamente diferem. Quem resolve esse caso é o extrator,
    que recebe a lista dos conceitos existentes e reusa o nome (D041), e a
    mesclagem manual na interface.
    """
    sem_acento = unicodedata.normalize("NFKD", str(nome or ""))
    sem_acento = "".join(c for c in sem_acento if not unicodedata.combining(c))
    apenas = re.sub(r"[^\w\s]", " ", sem_acento.casefold())
    return re.sub(r"\s+", " ", apenas).strip()


def _para_conferir(texto: str) -> str:
    """Forma comparável: sem espaços repetidos, sem caixa.

    O modelo costuma reproduzir o trecho certo com espaçamento ou quebra de linha
    levemente diferente. Comparar a forma crua reprovaria trechos legítimos e a
    taxa de descarte viraria ruído em vez de sinal.
    """
    return re.sub(r"\s+", " ", str(texto or "").casefold()).strip()


def trecho_existe(trecho: str, referencia: str) -> bool:
    """O trecho aparece no texto de referência? É a checagem da ancoragem."""
    alvo = _para_conferir(trecho)
    if not alvo:
        return False
    return alvo in _para_conferir(referencia)


# --------------------------------------------------------------------------
# Conceitos
# --------------------------------------------------------------------------


def _aliases(bruto: str) -> list[str]:
    try:
        valor = json.loads(bruto or "[]")
    except (ValueError, TypeError):
        return []
    return [str(a) for a in valor] if isinstance(valor, list) else []


def achar_ou_criar(nome: str, kind: str = "conceito") -> dict[str, Any]:
    """Devolve o conceito daquele nome, criando se for novo.

    Se o nome for uma variante gráfica de um conceito que já existe (`OBD II` para
    `OBD-II`), o existente volta e a variante entra em `aliases` — a variante é
    informação, não lixo.
    """
    limpo = re.sub(r"\s+", " ", str(nome or "").strip())
    if not limpo:
        raise ValueError("Conceito sem nome")

    chave = normalizar(limpo)
    if not chave:
        raise ValueError(f"Nome sem conteúdo utilizável: {nome!r}")

    with connect() as conn:
        linha = conn.execute("SELECT * FROM concepts WHERE canonical = ?", (chave,)).fetchone()
        if linha:
            conceito = dict(linha)
            alias = _aliases(conceito["aliases"])
            if limpo != conceito["name"] and limpo not in alias:
                alias.append(limpo)
                conn.execute(
                    "UPDATE concepts SET aliases = ?, updated_at = ? WHERE id = ?",
                    (json.dumps(alias, ensure_ascii=False), _now(), conceito["id"]),
                )
                conceito["aliases"] = alias
            return conceito

        conceito = {
            "id": _id("cpt"),
            "name": limpo,
            "canonical": chave,
            "aliases": [],
            "kind": (kind or "conceito").strip() or "conceito",
            "created_at": _now(),
            "updated_at": _now(),
        }
        conn.execute(
            """INSERT INTO concepts (id, name, canonical, aliases, kind, created_at, updated_at)
               VALUES (:id, :name, :canonical, '[]', :kind, :created_at, :updated_at)""",
            conceito,
        )
    return conceito


def get_conceito(concept_id: str) -> dict[str, Any] | None:
    with connect() as conn:
        linha = conn.execute("SELECT * FROM concepts WHERE id = ?", (concept_id,)).fetchone()
    return dict(linha) if linha else None


def vocabulario(limite: int = 120) -> list[str]:
    """Os nomes dos conceitos que já existem, para o extrator reusar (D041).

    É o que impede o grafo de fragmentar em `OBD2` / `OBD-II` / `OBD II`: o modelo
    vê o nome na lista e usa o que já está lá, em vez de inventar uma variante.
    """
    with connect() as conn:
        linhas = conn.execute(
            """SELECT name FROM concepts
               ORDER BY (SELECT COUNT(*) FROM mentions m WHERE m.concept_id = concepts.id) DESC,
                        name ASC
               LIMIT ?""",
            (limite,),
        ).fetchall()
    return [linha["name"] for linha in linhas]


# --------------------------------------------------------------------------
# Menções — a ancoragem
# --------------------------------------------------------------------------


def registrar_mencao(
    concept_id: str,
    *,
    notebook_id: str,
    trecho: str,
    referencia: str,
    source_id: str | None = None,
    output_id: str | None = None,
    thread_id: str | None = None,
    message_id: str | None = None,
) -> bool:
    """Grava a menção — **desde que o trecho exista em `referencia`**.

    `referencia` é o texto de onde a menção saiu (o bloco), que o chamador já tem
    em mãos: a conferência custa zero de rede e de banco, e por isso não há
    desculpa para não fazê-la.

    Devolver `False` significa que o trecho não existe no material — ou seja, que o
    extrator inventou. Isso é contado, não escondido.
    """
    if not trecho_existe(trecho, referencia):
        return False

    recorte = re.sub(r"\s+", " ", str(trecho).strip())[:600]

    with connect() as conn:
        # Re-extrair a mesma fonte não pode duplicar: a mesma menção (conceito,
        # origem, trecho) só entra uma vez.
        repetida = conn.execute(
            """SELECT 1 FROM mentions
               WHERE concept_id = ? AND excerpt = ?
                 AND IFNULL(source_id, '') = IFNULL(?, '')
                 AND IFNULL(output_id, '') = IFNULL(?, '')""",
            (concept_id, recorte, source_id, output_id),
        ).fetchone()
        if repetida:
            return True

        conn.execute(
            """INSERT INTO mentions
               (id, concept_id, notebook_id, source_id, output_id, thread_id, message_id,
                excerpt, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                _id("men"),
                concept_id,
                notebook_id,
                source_id,
                output_id,
                thread_id,
                message_id,
                recorte,
                _now(),
            ),
        )
    return True


def mencoes(concept_id: str, limite: int = 200) -> list[dict[str, Any]]:
    """As menções com a origem legível: de qual fonte (ou conversa) cada uma veio."""
    with connect() as conn:
        linhas = conn.execute(
            """SELECT m.*,
                      s.title AS source_title, s.kind AS source_kind, s.origin AS source_origin,
                      o.title AS output_title, o.template AS output_template,
                      n.title AS notebook_title
               FROM mentions m
               LEFT JOIN sources   s ON s.id = m.source_id
               LEFT JOIN outputs   o ON o.id = m.output_id
               JOIN      notebooks n ON n.id = m.notebook_id
               WHERE m.concept_id = ?
               ORDER BY m.created_at ASC
               LIMIT ?""",
            (concept_id, limite),
        ).fetchall()
    return [dict(linha) for linha in linhas]


def origem_da_mencao(mencao: dict[str, Any]) -> str:
    """Como nomear a origem de uma menção, em uma linha."""
    if mencao.get("source_id"):
        return f'fonte "{mencao.get("source_title") or mencao["source_id"]}"'
    if mencao.get("output_id"):
        return f'output "{mencao.get("output_title") or mencao["output_id"]}"'
    if mencao.get("thread_id"):
        return "conversa"
    return "origem desconhecida"


# --------------------------------------------------------------------------
# Arestas
# --------------------------------------------------------------------------


def _ligar(
    conn: Any,
    a_id: str,
    b_id: str,
    kind: str,
    provenance: str = "",
) -> dict[str, Any] | None:
    """A ligação, numa conexão que já está aberta.

    Existe separado de `ligar` porque `mesclar` precisa ligar DENTRO da transação
    dela: abrir uma segunda conexão no meio de uma transação de escrita trava no
    SQLite, e o erro só aparece quando duas operações se cruzam.
    """
    if not a_id or not b_id or a_id == b_id:
        return None

    a, b = sorted([a_id, b_id])
    existente = conn.execute(
        "SELECT * FROM edges WHERE a_id = ? AND b_id = ? AND kind = ?", (a, b, kind)
    ).fetchone()

    if existente:
        # Co-ocorrência aparece muitas vezes e o peso é a informação; a aresta
        # explícita é binária — repetir não a torna mais verdadeira.
        if kind == CO_OCORRENCIA:
            conn.execute("UPDATE edges SET weight = weight + 1 WHERE id = ?", (existente["id"],))
        elif provenance and not existente["provenance"]:
            conn.execute(
                "UPDATE edges SET provenance = ? WHERE id = ?", (provenance, existente["id"])
            )
        return dict(conn.execute("SELECT * FROM edges WHERE id = ?", (existente["id"],)).fetchone())

    aresta = {
        "id": _id("edg"),
        "a_id": a,
        "b_id": b,
        "kind": kind,
        "weight": 1,
        "provenance": provenance,
        "created_at": _now(),
    }
    conn.execute(
        """INSERT INTO edges (id, a_id, b_id, kind, weight, provenance, created_at)
           VALUES (:id, :a_id, :b_id, :kind, :weight, :provenance, :created_at)""",
        aresta,
    )
    return aresta


def ligar(
    a_id: str,
    b_id: str,
    kind: str = CO_OCORRENCIA,
    *,
    provenance: str = "",
) -> dict[str, Any] | None:
    """Liga dois conceitos. Co-ocorrência soma peso; o resto mantém.

    A ordem entre `a_id` e `b_id` é canônica (menor primeiro) para que `(A,B)` e
    `(B,A)` sejam a MESMA aresta — senão o `UNIQUE(a_id, b_id, kind)` não protege
    nada e o grafo ganha arestas espelhadas.
    """
    with connect() as conn:
        return _ligar(conn, a_id, b_id, kind, provenance)


def co_ocorrencia(concept_ids: list[str]) -> int:
    """Liga todos os pares de conceitos que apareceram juntos no mesmo bloco.

    É a aresta que sai de graça: já temos os conceitos do bloco em mãos, então a
    relação não custa nem uma chamada de modelo a mais.
    """
    unicos = sorted({c for c in concept_ids if c})
    total = 0
    for i, a in enumerate(unicos):
        for b in unicos[i + 1 :]:
            if ligar(a, b, CO_OCORRENCIA):
                total += 1
    return total


def ligar_explicito(
    a_id: str,
    b_id: str,
    *,
    trecho: str,
    referencia: str,
    quem: str,
) -> bool:
    """Aresta afirmada (pelo modelo ou pela pessoa) — e ela **exige o trecho**.

    Mesma conferência da menção: sem o trecho que a sustenta, a aresta não entra.
    É esta exigência que separa um grafo de um emaranhado de palpites.
    """
    if not trecho_existe(trecho, referencia):
        return False
    recorte = re.sub(r"\s+", " ", str(trecho).strip())[:600]
    return bool(ligar(a_id, b_id, EXPLICITA, provenance=f"{quem}: {recorte}"))


def vizinhanca(concept_id: str) -> dict[str, Any] | None:
    """O conceito, o que está ligado a ele, e com que fundamento."""
    conceito = get_conceito(concept_id)
    if not conceito:
        return None

    with connect() as conn:
        arestas = [
            dict(linha)
            for linha in conn.execute(
                "SELECT * FROM edges WHERE a_id = ? OR b_id = ? ORDER BY weight DESC",
                (concept_id, concept_id),
            )
        ]
        vizinhos: list[dict[str, Any]] = []
        for aresta in arestas:
            outro_id = aresta["b_id"] if aresta["a_id"] == concept_id else aresta["a_id"]
            outro = conn.execute("SELECT * FROM concepts WHERE id = ?", (outro_id,)).fetchone()
            if not outro:
                continue
            quantas = conn.execute(
                "SELECT COUNT(*) AS n FROM mentions WHERE concept_id = ?", (outro_id,)
            ).fetchone()["n"]
            vizinhos.append({
                "concept": dict(outro),
                "kind": aresta["kind"],
                "weight": aresta["weight"],
                "provenance": aresta["provenance"],
                "mentions": quantas,
            })

    return {"concept": conceito, "neighbors": vizinhos, "mentions": mencoes(concept_id)}


# --------------------------------------------------------------------------
# Leitura para a interface
# --------------------------------------------------------------------------


def _cadernos_por_conceito(ids: list[str] | None = None) -> dict[str, list[str]]:
    """Em quais cadernos cada conceito aparece.

    É a informação mais interessante do grafo: um conceito em dois cadernos é uma
    ponte entre áreas, e é o que a tela usa para colorir o desenho.
    """
    sql = """SELECT DISTINCT m.concept_id AS cid, n.title AS titulo
             FROM mentions m JOIN notebooks n ON n.id = m.notebook_id"""
    parametros: tuple = ()
    if ids is not None:
        if not ids:
            return {}
        sql += f" WHERE m.concept_id IN ({','.join('?' * len(ids))})"
        parametros = tuple(ids)

    with connect() as conn:
        linhas = conn.execute(sql, parametros).fetchall()

    mapa: dict[str, list[str]] = {}
    for linha in linhas:
        mapa.setdefault(linha["cid"], []).append(linha["titulo"])
    return {cid: sorted(set(titulos)) for cid, titulos in mapa.items()}


def criar_nota(concept_id: str, body: str, *, notebook_id: str | None = None) -> dict[str, Any]:
    """Uma nota sua sobre um conceito. É o que o grafo não pode ter: a sua voz."""
    nota = {
        "id": _id("not"),
        "concept_id": concept_id,
        "notebook_id": notebook_id,
        "body": body.strip(),
        "created_at": _now(),
    }
    with connect() as conn:
        conn.execute(
            """INSERT INTO notes (id, concept_id, notebook_id, body, created_at)
               VALUES (:id, :concept_id, :notebook_id, :body, :created_at)""",
            nota,
        )
    return nota


def notas_do_conceito(concept_id: str) -> list[dict[str, Any]]:
    with connect() as conn:
        return [
            dict(linha)
            for linha in conn.execute(
                "SELECT * FROM notes WHERE concept_id = ? ORDER BY created_at ASC",
                (concept_id,),
            )
        ]


def apagar_nota(note_id: str) -> bool:
    with connect() as conn:
        return conn.execute("DELETE FROM notes WHERE id = ?", (note_id,)).rowcount > 0


def buscar(termo: str, limite: int = 20) -> list[dict[str, Any]]:
    """Busca por nome ou alias, já dizendo em quais cadernos o conceito aparece.

    É o que a pessoa usa para achar um conceito — e o que o agente usa antes de
    pedir a vizinhança, então a lista precisa bastar para ele decidir.
    """
    alvo = f"%{normalizar(termo)}%"
    if not termo or alvo == "%%":
        return []
    with connect() as conn:
        linhas = conn.execute(
            """SELECT c.*, (SELECT COUNT(*) FROM mentions m WHERE m.concept_id = c.id) AS mentions
               FROM concepts c
               WHERE c.canonical LIKE ? OR LOWER(c.aliases) LIKE ?
               ORDER BY mentions DESC, c.name ASC
               LIMIT ?""",
            (alvo, f"%{str(termo).casefold()}%", limite),
        ).fetchall()

    achados = [dict(linha) for linha in linhas]
    cadernos = _cadernos_por_conceito([c["id"] for c in achados])
    for conceito in achados:
        titulos = cadernos.get(conceito["id"], [])
        conceito["notebooks"] = titulos
        conceito["ponte"] = len(titulos) > 1
    return achados


def grafo(
    *,
    notebook_id: str | None = None,
    peso_minimo: int = 1,
    incluir_co_ocorrencia: bool = True,
) -> dict[str, Any]:
    """Os nós e as arestas do grafo, para desenhar.

    Filtrado por caderno, o grafo mostra só os conceitos mencionados ali e as
    arestas **entre eles** — uma aresta para um conceito fora do filtro seria uma
    linha saindo para o nada.
    """
    with connect() as conn:
        if notebook_id:
            conceitos = [
                dict(linha)
                for linha in conn.execute(
                    """SELECT c.*, COUNT(m.id) AS mentions
                       FROM concepts c JOIN mentions m ON m.concept_id = c.id
                       WHERE m.notebook_id = ?
                       GROUP BY c.id
                       ORDER BY mentions DESC""",
                    (notebook_id,),
                )
            ]
        else:
            conceitos = [
                dict(linha)
                for linha in conn.execute(
                    """SELECT c.*, (SELECT COUNT(*) FROM mentions m WHERE m.concept_id = c.id) AS mentions
                       FROM concepts c
                       ORDER BY mentions DESC"""
                )
            ]

        ids = {c["id"] for c in conceitos}
        if not ids:
            return {"nodes": [], "edges": [], "notebooks": []}

        tipos = [CO_OCORRENCIA, EXPLICITA] if incluir_co_ocorrencia else [EXPLICITA]
        marcadores = ",".join("?" * len(tipos))
        # O peso filtra SÓ a co-ocorrência. A aresta afirmada é uma afirmação do
        # material, não uma coincidência de vizinhança: filtrá-la por peso esconderia
        # justamente as ligações com trecho, que são as que valem.
        arestas = [
            dict(linha)
            for linha in conn.execute(
                f"""SELECT * FROM edges
                    WHERE kind IN ({marcadores})
                      AND (kind = ? OR weight >= ?)
                      AND a_id IN ({",".join("?" * len(ids))})
                      AND b_id IN ({",".join("?" * len(ids))})""",
                (*tipos, EXPLICITA, peso_minimo, *ids, *ids),
            )
        ]

    # Fora do bloco de propósito: conexão aninhada dentro de outra aberta é o padrão
    # que trava no SQLite — foi o que me pegou no `mesclar`.
    por_conceito = _cadernos_por_conceito(list(ids))
    cadernos = sorted({t for titulos in por_conceito.values() for t in titulos})

    for conceito in conceitos:
        titulos = por_conceito.get(conceito["id"], [])
        conceito["notebooks"] = titulos
        # Um conceito pode estar em mais de um caderno: é o que a interface chama
        # de "ponte", e é a informação mais interessante do grafo.
        conceito["ponte"] = len(titulos) > 1

    return {"nodes": conceitos, "edges": arestas, "notebooks": cadernos}


def lacunas(notebook_id: str, *, limite: int = 60) -> dict[str, list[dict[str, Any]]]:
    """O que o material deste caderno não cobre — em fatos, não em opinião (D049).

    Nenhuma consulta aqui usa modelo, de propósito. Um modelo listando "tópicos que
    faltam" compararia o seu material com o que ele já sabe, e não com o que você
    não tem: seria a única coisa neste app afirmada sem lastro. Cada item abaixo pode
    ser conferido na fonte pela pessoa.
    """
    return {
        "nao_desenvolvidos": _nao_desenvolvidos(notebook_id, limite),
        "em_outro_caderno": _em_outro_caderno(notebook_id, limite),
        "fontes_sem_contribuicao": fontes_que_nao_contribuiram(notebook_id),
    }


def _nao_desenvolvidos(notebook_id: str, limite: int) -> list[dict[str, Any]]:
    """O material nomeou uma vez e nunca explicou: aparição única e sem ligação.

    É o candidato mais útil a virar card, porque é exatamente onde a pessoa viu o
    termo e não sabe o que ele é.
    """
    with connect() as conn:
        linhas = conn.execute(
            """SELECT c.id, c.name, COUNT(m.id) AS mentions
               FROM concepts c
               JOIN mentions m ON m.concept_id = c.id
               WHERE m.notebook_id = ?
                 AND NOT EXISTS (
                     SELECT 1 FROM edges e
                     WHERE e.kind = ? AND (e.a_id = c.id OR e.b_id = c.id)
                 )
               GROUP BY c.id
               HAVING COUNT(m.id) = 1
               ORDER BY c.name
               LIMIT ?""",
            (notebook_id, EXPLICITA, limite),
        ).fetchall()
    return [dict(linha) for linha in linhas]


def _em_outro_caderno(notebook_id: str, limite: int) -> list[dict[str, Any]]:
    """Conceitos que você estudou em outro caderno e que aqui nunca aparecem.

    Só é possível saber isto porque o grafo é global (D045): é o cruzamento entre
    cadernos que dá a lacuna, e é a informação que mais rende a quem estuda em
    matérias separadas que na verdade se tocam.
    """
    with connect() as conn:
        linhas = conn.execute(
            """SELECT c.id, c.name,
                      COUNT(DISTINCT m.notebook_id) AS cadernos,
                      GROUP_CONCAT(DISTINCT n.title)  AS onde
               FROM concepts c
               JOIN mentions m  ON m.concept_id = c.id
               JOIN notebooks n ON n.id = m.notebook_id
               WHERE c.id NOT IN (SELECT concept_id FROM mentions WHERE notebook_id = ?)
               GROUP BY c.id
               ORDER BY cadernos DESC, c.name
               LIMIT ?""",
            (notebook_id, limite),
        ).fetchall()
    return [dict(linha) for linha in linhas]


def fontes_que_nao_contribuiram(notebook_id: str) -> list[dict[str, Any]]:
    """Fontes ativas que não geraram menção nenhuma: entraram e não viraram saber."""
    with connect() as conn:
        linhas = conn.execute(
            """SELECT s.id, s.title, s.kind, s.chars
               FROM sources s
               WHERE s.notebook_id = ? AND s.active = 1 AND s.status = 'ready'
                 AND NOT EXISTS (SELECT 1 FROM mentions m WHERE m.source_id = s.id)
               ORDER BY s.title""",
            (notebook_id,),
        ).fetchall()
    return [dict(linha) for linha in linhas]


def conceitos_por_fonte(notebook_id: str) -> list[dict[str, Any]]:
    """Quantos conceitos cada fonte do caderno sustenta.

    Serve à pergunta "o que este material me deu?", e denuncia a fonte que gerou
    pouquíssimo — que costuma ser material fora do assunto ou transcrição ruim.
    """
    with connect() as conn:
        linhas = conn.execute(
            """SELECT s.id, s.title, s.kind, s.chars,
                      COUNT(DISTINCT m.concept_id) AS conceitos,
                      COUNT(m.id) AS mencoes
               FROM sources s
               LEFT JOIN mentions m ON m.source_id = s.id
               WHERE s.notebook_id = ? AND s.active = 1
               GROUP BY s.id
               ORDER BY conceitos DESC""",
            (notebook_id,),
        ).fetchall()
    return [dict(linha) for linha in linhas]


def estatisticas() -> dict[str, int]:
    with connect() as conn:
        return {
            "conceitos": conn.execute("SELECT COUNT(*) AS n FROM concepts").fetchone()["n"],
            "mencoes": conn.execute("SELECT COUNT(*) AS n FROM mentions").fetchone()["n"],
            "arestas": conn.execute("SELECT COUNT(*) AS n FROM edges").fetchone()["n"],
            "explicitas": conn.execute(
                "SELECT COUNT(*) AS n FROM edges WHERE kind = ?", (EXPLICITA,)
            ).fetchone()["n"],
        }


# --------------------------------------------------------------------------
# Edição — as mesmas operações para a interface e para o agente (D024)
# --------------------------------------------------------------------------


def renomear(concept_id: str, novo_nome: str) -> dict[str, Any] | None:
    """Renomeia. Se o novo nome colide com outro conceito, **mescla** em vez de
    estourar: colidir é o caso comum (`OBD2` para `OBD-II`), não o excepcional."""
    limpo = re.sub(r"\s+", " ", str(novo_nome or "").strip())
    if not limpo:
        return None

    conceito = get_conceito(concept_id)
    if not conceito:
        return None

    chave = normalizar(limpo)
    with connect() as conn:
        colide = conn.execute(
            "SELECT id FROM concepts WHERE canonical = ? AND id != ?", (chave, concept_id)
        ).fetchone()
    if colide:
        return mesclar(concept_id, colide["id"], apelido=conceito["name"])

    with connect() as conn:
        conn.execute(
            "UPDATE concepts SET name = ?, canonical = ?, updated_at = ? WHERE id = ?",
            (limpo, chave, _now(), concept_id),
        )
    return get_conceito(concept_id)


def mesclar(de_id: str, para_id: str, *, apelido: str = "") -> dict[str, Any] | None:
    """Funde dois conceitos: menções e arestas migram, o nome antigo vira alias.

    A menção migra, não some: o trecho de origem é a prova, e prova não se apaga
    numa fusão.
    """
    if de_id == para_id:
        return get_conceito(para_id)

    origem = get_conceito(de_id)
    destino = get_conceito(para_id)
    if not origem or not destino:
        return None

    with connect() as conn:
        # Menções: evita duplicar a mesma menção após a fusão.
        existentes = {
            (linha["source_id"], linha["output_id"], linha["excerpt"])
            for linha in conn.execute("SELECT * FROM mentions WHERE concept_id = ?", (para_id,))
        }
        for linha in conn.execute("SELECT * FROM mentions WHERE concept_id = ?", (de_id,)):
            marca = (linha["source_id"], linha["output_id"], linha["excerpt"])
            if marca in existentes:
                conn.execute("DELETE FROM mentions WHERE id = ?", (linha["id"],))
            else:
                conn.execute(
                    "UPDATE mentions SET concept_id = ? WHERE id = ?", (para_id, linha["id"])
                )

        # Arestas: as do conceito que sai migram; as que ficariam em laço (o outro
        # lado é o destino) somem, porque um conceito não se liga a si mesmo.
        for linha in conn.execute(
            "SELECT * FROM edges WHERE a_id = ? OR b_id = ?", (de_id, de_id)
        ):
            a = para_id if linha["a_id"] == de_id else linha["a_id"]
            b = para_id if linha["b_id"] == de_id else linha["b_id"]
            conn.execute("DELETE FROM edges WHERE id = ?", (linha["id"],))
            _ligar(conn, a, b, linha["kind"], linha["provenance"])

        alias = _aliases(destino["aliases"])
        for nome in [origem["name"], apelido, *(_aliases(origem["aliases"]))]:
            if nome and nome != destino["name"] and nome not in alias:
                alias.append(nome)
        conn.execute(
            "UPDATE concepts SET aliases = ?, updated_at = ? WHERE id = ?",
            (json.dumps(alias, ensure_ascii=False), _now(), para_id),
        )
        conn.execute("DELETE FROM concepts WHERE id = ?", (de_id,))

    return get_conceito(para_id)


def apagar(concept_id: str) -> bool:
    """Apaga o conceito. Menções e arestas vão junto (CASCADE) — o nó sem prova
    deixa de existir, e é assim que deve ser: sem âncora, não há conhecimento."""
    with connect() as conn:
        cursor = conn.execute("DELETE FROM concepts WHERE id = ?", (concept_id,))
    return cursor.rowcount > 0


def limpar_fonte(source_id: str) -> dict[str, int]:
    """Remove as menções de uma fonte antes de re-extrair, e poda o que ficou solto.

    Re-extrair precisa substituir, não acumular. E conceito que ficou sem menção
    nenhuma perdeu a âncora: sai também, junto com as arestas dele.
    """
    with connect() as conn:
        cursor = conn.execute("DELETE FROM mentions WHERE source_id = ?", (source_id,))
        mencoes_removidas = cursor.rowcount
        sem_ancora = conn.execute(
            """SELECT c.id FROM concepts c
               WHERE NOT EXISTS (SELECT 1 FROM mentions m WHERE m.concept_id = c.id)"""
        ).fetchall()
        for linha in sem_ancora:
            conn.execute("DELETE FROM concepts WHERE id = ?", (linha["id"],))
    return {"mentions": mencoes_removidas, "concepts": len(sem_ancora)}


def orfaos() -> int:
    """Quantos conceitos estão sem nenhuma menção — não deveria haver nenhum."""
    with connect() as conn:
        return conn.execute(
            """SELECT COUNT(*) AS n FROM concepts c
               WHERE NOT EXISTS (SELECT 1 FROM mentions m WHERE m.concept_id = c.id)"""
        ).fetchone()["n"]


__all__ = [
    "CO_OCORRENCIA",
    "EXPLICITA",
    "SIMILARIDADE",
    "achar_ou_criar",
    "apagar",
    "buscar",
    "co_ocorrencia",
    "estatisticas",
    "get_conceito",
    "grafo",
    "ligar",
    "ligar_explicito",
    "limpar_fonte",
    "mencoes",
    "mesclar",
    "normalizar",
    "orfaos",
    "origem_da_mencao",
    "registrar_mencao",
    "renomear",
    "trecho_existe",
    "vizinhanca",
    "vocabulario",
]
