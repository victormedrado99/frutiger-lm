"""Cards e repetição espaçada (F4).

Lógica pura: sem modelo, sem rede, testável de ponta a ponta.

O agendamento é um **SM-2 simplificado**, e a simplificação é deliberada (D049). Um
algoritmo elaborado sem uso real é fé — o que importa é que a revisão de hoje seja
curta e que o card difícil volte logo. Se o uso mostrar que não basta, aí se elabora,
com dado.

Duas decisões que valem explicação:

- **O card guarda o próprio trecho.** Ele não depende do conceito para ser conferível:
  se o conceito sair do grafo, o card continua com a prova ao lado do verso. O verso
  é a resposta, o trecho é por que ela é verdade.
- **"Errei" não conta como acerto em dobro.** Ele zera o intervalo e volta na mesma
  sessão. Um card que você erra não deve voltar em três dias só porque a média subiu.
"""

from __future__ import annotations

import re
import time
import uuid
from typing import Any

from .db import connect

NOTAS = ("errei", "dificil", "bom", "facil")
LIMITE_EASE = (1.3, 3.0)
MINUTOS_DO_ERRO = 10


def _id() -> str:
    return f"crd_{uuid.uuid4().hex[:12]}"


def _agora(agora: float | None) -> float:
    return time.time() if agora is None else agora


# --------------------------------------------------------------------------
# O agendamento
# --------------------------------------------------------------------------


def _proximo_intervalo(intervalo: float, ease: float, reps: int) -> float:
    """Os degraus clássicos: 1 dia, 6 dias, e daí o fator assume."""
    if reps <= 0:
        return 1.0
    if reps == 1:
        return 6.0
    return max(1.0, intervalo * ease)


def agendar(card: dict[str, Any], nota: str, *, agora: float | None = None) -> dict[str, Any]:
    """O estado do card depois desta revisão. Não grava nada.

    Separado de `revisar` de propósito: assim a regra é testável sem banco, e a
    gravação vira uma linha.
    """
    if nota not in NOTAS:
        raise ValueError(f"Nota desconhecida: {nota!r}. Use uma de {NOTAS}")

    momento = _agora(agora)
    ease = float(card.get("ease") or 2.5)
    intervalo = float(card.get("interval_days") or 0)
    reps = int(card.get("reps") or 0)
    lapses = int(card.get("lapses") or 0)
    atraso: float  # segundos até a próxima revisão

    if nota == "errei":
        # Volta na mesma sessão e o fator cai. Não conta como acerto.
        lapses += 1
        ease = max(LIMITE_EASE[0], ease - 0.20)
        intervalo = 0.0
        reps = 0
        atraso = MINUTOS_DO_ERRO * 60
    elif nota == "dificil":
        ease = max(LIMITE_EASE[0], ease - 0.15)
        intervalo = max(1.0, intervalo * 1.2)
        reps += 1
        atraso = intervalo * 86400
    elif nota == "facil":
        ease = min(LIMITE_EASE[1], ease + 0.15)
        intervalo = _proximo_intervalo(intervalo, ease, reps) * 1.3
        reps += 1
        atraso = intervalo * 86400
    else:  # bom
        intervalo = _proximo_intervalo(intervalo, ease, reps)
        reps += 1
        atraso = intervalo * 86400

    return {
        "ease": round(ease, 3),
        "interval_days": round(intervalo, 3),
        "due_at": momento + atraso,
        "reps": reps,
        "lapses": lapses,
        "updated_at": momento,
    }


# --------------------------------------------------------------------------
# Gravação
# --------------------------------------------------------------------------


def criar_card(
    notebook_id: str,
    *,
    front: str,
    back: str,
    concept_id: str | None = None,
    source_id: str | None = None,
    excerpt: str = "",
    agora: float | None = None,
) -> dict[str, Any]:
    """Cria um card. Nasce devido: se você criou, é para revisar."""
    momento = _agora(agora)
    card = {
        "id": _id(),
        "notebook_id": notebook_id,
        "concept_id": concept_id,
        "front": front.strip(),
        "back": back.strip(),
        "source_id": source_id,
        "excerpt": excerpt.strip(),
        "ease": 2.5,
        "interval_days": 0.0,
        "due_at": momento,
        "reps": 0,
        "lapses": 0,
        "created_at": momento,
        "updated_at": momento,
    }
    with connect() as conn:
        conn.execute(
            """INSERT INTO cards (id, notebook_id, concept_id, front, back, source_id,
                                  excerpt, ease, interval_days, due_at, reps, lapses,
                                  created_at, updated_at)
               VALUES (:id, :notebook_id, :concept_id, :front, :back, :source_id,
                       :excerpt, :ease, :interval_days, :due_at, :reps, :lapses,
                       :created_at, :updated_at)""",
            card,
        )
    return card


def get_card(card_id: str) -> dict[str, Any] | None:
    with connect() as conn:
        linha = conn.execute("SELECT * FROM cards WHERE id = ?", (card_id,)).fetchone()
    return dict(linha) if linha else None


def revisar(card_id: str, nota: str, *, agora: float | None = None) -> dict[str, Any] | None:
    """Aplica a nota e grava o novo agendamento."""
    card = get_card(card_id)
    if not card:
        return None

    novo = agendar(card, nota, agora=agora)
    with connect() as conn:
        conn.execute(
            """UPDATE cards SET ease = :ease, interval_days = :interval_days,
                                due_at = :due_at, reps = :reps, lapses = :lapses,
                                updated_at = :updated_at
               WHERE id = :id""",
            {**novo, "id": card_id},
        )
    return get_card(card_id)


def devidos(
    notebook_id: str | None = None, *, limite: int = 40, agora: float | None = None
) -> list[dict[str, Any]]:
    """Os cards para revisar agora, do mais atrasado para o menos.

    O mais atrasado primeiro porque é o que você mais esqueceu — e porque uma sessão
    interrompida no meio deve ter coberto o que mais importa.
    """
    momento = _agora(agora)
    sql = """SELECT c.*, n.title AS notebook_title, s.title AS source_title,
                    cc.name AS concept_name
             FROM cards c
             JOIN      notebooks n  ON n.id = c.notebook_id
             LEFT JOIN sources   s  ON s.id = c.source_id
             LEFT JOIN concepts  cc ON cc.id = c.concept_id
             WHERE c.due_at <= ?"""
    parametros: list[Any] = [momento]
    if notebook_id:
        sql += " AND c.notebook_id = ?"
        parametros.append(notebook_id)
    sql += " ORDER BY c.due_at ASC LIMIT ?"
    parametros.append(limite)

    with connect() as conn:
        return [dict(linha) for linha in conn.execute(sql, parametros)]


def listar(notebook_id: str, *, limite: int = 200) -> list[dict[str, Any]]:
    with connect() as conn:
        return [
            dict(linha)
            for linha in conn.execute(
                "SELECT * FROM cards WHERE notebook_id = ? ORDER BY due_at ASC LIMIT ?",
                (notebook_id, limite),
            )
        ]


def apagar_card(card_id: str) -> bool:
    with connect() as conn:
        return conn.execute("DELETE FROM cards WHERE id = ?", (card_id,)).rowcount > 0


def apagar_do_conceito(concept_id: str) -> int:
    """Apaga os cards de um conceito, mas só se ele saiu do grafo de vez.

    Existe para os testes e para a edição em lote; apagar um conceito pela interface
    NÃO apaga os cards dele — o card tem o próprio trecho e continua válido.
    """
    with connect() as conn:
        return conn.execute("DELETE FROM cards WHERE concept_id = ?", (concept_id,)).rowcount


def resumo(notebook_id: str | None = None, *, agora: float | None = None) -> dict[str, int]:
    momento = _agora(agora)
    onde = " WHERE notebook_id = ?" if notebook_id else ""
    parametros = (notebook_id,) if notebook_id else ()
    with connect() as conn:
        total = conn.execute(f"SELECT COUNT(*) n FROM cards{onde}", parametros).fetchone()["n"]
        vencidos = conn.execute(
            f"SELECT COUNT(*) n FROM cards{onde}{' AND' if onde else ' WHERE'} due_at <= ?",
            (*parametros, momento),
        ).fetchone()["n"]
        aprendendo = conn.execute(
            f"""SELECT COUNT(*) n FROM cards{onde}{' AND' if onde else ' WHERE'} reps > 0""",
            parametros,
        ).fetchone()["n"]
    return {"total": total, "vencidos": vencidos, "aprendendo": aprendendo}


# --------------------------------------------------------------------------
# Uso das fontes (D051) — a citação `[n]` vira registro
# --------------------------------------------------------------------------


def registrar_uso(source_id: str, *, thread_id: str = "", agora: float | None = None) -> None:
    momento = _agora(agora)
    with connect() as conn:
        conn.execute(
            "INSERT INTO source_usage (id, source_id, thread_id, created_at) VALUES (?, ?, ?, ?)",
            (f"use_{uuid.uuid4().hex[:12]}", source_id, thread_id, momento),
        )


def fontes_usadas() -> dict[str, int]:
    """Quantas vezes cada fonte foi citada numa resposta."""
    with connect() as conn:
        return {
            linha["source_id"]: linha["n"]
            for linha in conn.execute(
                "SELECT source_id, COUNT(*) n FROM source_usage GROUP BY source_id"
            )
        }


def fontes_nunca_citadas(notebook_id: str) -> list[dict[str, Any]]:
    """Fontes ativas que nunca apareceram citadas numa resposta (D051).

    É o sentido conferível de "fonte órfã": o agente leu o material, escreveu a
    resposta, e não citou esta fonte — então ou ela não foi necessária, ou não foi
    encontrada. As duas hipóteses valem a pena olhar.
    """
    with connect() as conn:
        linhas = conn.execute(
            """SELECT s.id, s.title, s.kind, s.chars
               FROM sources s
               WHERE s.notebook_id = ? AND s.active = 1 AND s.status = 'ready'
                 AND NOT EXISTS (SELECT 1 FROM source_usage u WHERE u.source_id = s.id)
               ORDER BY s.title""",
            (notebook_id,),
        ).fetchall()
    return [dict(linha) for linha in linhas]


def registrar_uso_de_citacoes(
    resposta: str, numeradas: list[dict[str, Any]], *, thread_id: str = ""
) -> list[str]:
    """Lê os `[n]` da resposta e registra o uso das fontes correspondentes.

    A numeração das fontes é determinística (a posição na lista canônica), então o
    `[3]` que o modelo escreveu aponta para uma fonte conhecida. Citação que não
    existe na numeração é ignorada — o modelo às vezes escreve `[7]` num caderno de
    três fontes, e inventar um uso a partir disso seria pior do que não registrar.

    Devolve os ids registrados.
    """
    por_numero = {
        indice: fonte["id"] for indice, fonte in enumerate(numeradas, start=1)
    }
    registrados: list[str] = []
    for achado in re.findall(r"\[(\d{1,3})\]", str(resposta or "")):
        fonte_id = por_numero.get(int(achado))
        if fonte_id and fonte_id not in registrados:
            registrar_uso(fonte_id, thread_id=thread_id)
            registrados.append(fonte_id)
    return registrados
