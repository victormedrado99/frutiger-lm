"""A oficina — onde uma tarefa longa roda FORA do turno que a pediu (D059, D065).

O problema que isto resolve é o D028 inteiro. Se a ferramenta do agente chamasse
`artefato.compilar()` (ou a ligação por similaridade) e devolvesse o resultado, três
coisas ruins aconteceriam de uma vez:

1. a tela ficaria parada por dezenas de segundos — as duas tarefas têm chamada de
   modelo/rede no meio, e dentro de uma ferramenta não há como transmitir nada;
2. o trabalho não poderia ser acompanhado enquanto acontece (ferramenta não emite
   delta: o streaming do agente passa por cima dela, não por dentro);
3. o agente ainda passaria o resultado por cima — reformatando um documento pronto, ou
   resumindo um número que a tela mostra melhor.

A saída: a ferramenta **dispara e sai de cena**. Quem constrói é uma tarefa própria, com
id — e o id é o contrato entre os três que precisam se encontrar:

    quem pediu (botão ou agente)  ─┐
                                   ├─▶ oficina.iniciar() ──▶ Run (id, passos, resultado)
    quem acompanha (o painel)     ─┤                              │
                                   │                              ▼
    o que fica gravado (o output) ─┘        oficina.acompanhar(id) ──▶ SSE ──▶ painel

**Dois trabalhos, um runner** (D065). O F6 precisava exatamente do que o F5 tinha
construído — tarefa longa com progresso, disparável pelo botão e pela ferramenta — e
escrever isso de novo seria a segunda implementação de uma coisa só (D024). Então o
`trabalho` é um campo, os eventos são genéricos (`trabalho.passo`, `trabalho.pronto`) e
o que muda entre eles é o que o trabalho devolve: o documento grava um `output`; a
ligação por similaridade devolve números.

O que a oficina **não** faz: não decide o que o trabalho faz (isso é `artefato.py` e
`similaridade.py`), não escreve na conversa e não conhece HTTP. Ela guarda runs e
publica eventos; quem traduz evento em SSE é a rota, e quem desenha é a tela.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import suppress
from dataclasses import dataclass, field
from typing import Any

from .. import db
from . import artefato, embed, llm, similaridade

log = logging.getLogger("frutiger.oficina")

# Um run terminado continua na lista por isto, e só então sai. Não é só faxina: a tela
# pode recarregar no meio de uma tarefa, e quem chega atrasado precisa do histórico
# dos passos — sem isso, o acompanhamento voltaria vazio e pareceria travado.
TTL_SEGUNDOS = 15 * 60

# Teto de runs guardados (a lista é de memória). O TTL limpa a maioria; isto é para o
# caso de uso intenso num período curto.
MAX_RUNS = 24

# Os trabalhos que a oficina sabe fazer. Um nome aqui é um nome que a tela conhece.
DOCUMENTO = "documento"
SIMILARIDADE = "similaridade"
TRABALHOS = (DOCUMENTO, SIMILARIDADE)

Emissor = Callable[[str, str], Awaitable[None]]


@dataclass
class Run:
    """Uma tarefa longa em andamento, com o estado que a tela precisa ver."""

    id: str
    notebook_id: str
    trabalho: str
    origem: str  # "botao" | "agente" — de onde veio o pedido
    parametros: dict[str, Any] = field(default_factory=dict)
    estado: str = "rodando"  # rodando | pronto | erro
    passo: str = ""
    mensagem: str = ""
    resultado: dict[str, Any] = field(default_factory=dict)
    output_id: str | None = None  # só o trabalho "documento" grava um
    erro: str | None = None
    criado_em: float = field(default_factory=time.time)
    terminado_em: float | None = None
    eventos: list[dict[str, Any]] = field(default_factory=list)
    ouvintes: list[asyncio.Queue] = field(default_factory=list)
    tarefa: asyncio.Task | None = None

    def resumo(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "notebook_id": self.notebook_id,
            "trabalho": self.trabalho,
            "origem": self.origem,
            "estado": self.estado,
            "passo": self.passo,
            "mensagem": self.mensagem,
            "resultado": self.resultado,
            "output_id": self.output_id,
            "erro": self.erro,
            "criado_em": self.criado_em,
            "terminado_em": self.terminado_em,
        }


class Oficina:
    """As tarefas longas em construção — **um de cada trabalho por caderno**.

    Dois trabalhos DIFERENTES podem rodar ao mesmo tempo no mesmo caderno (compilar e
    ligar por similaridade mexem em coisas distintas: um grava um documento, o outro
    escreve arestas). O que a regra impede é a repetição do mesmo trabalho: dois
    documentos ao mesmo tempo gastariam duas chamadas de modelo para produzir dois
    quase iguais — e o caso real é o clique duplo, ou "compila isso" no chat enquanto
    o botão já está rodando. Quem pede de novo **acompanha o que existe**.
    """

    def __init__(self) -> None:
        self._runs: dict[str, Run] = {}

    # --------------------------------------------------------------- disparar

    def iniciar(
        self,
        notebook_id: str,
        *,
        trabalho: str = DOCUMENTO,
        origem: str = "botao",
        parametros: dict[str, Any] | None = None,
    ) -> Run:
        """Cria o run e devolve o id — **sem esperar a tarefa**.

        Precisa de um laço de eventos rodando (`asyncio`), e falha com mensagem clara
        sem ele: o trabalho é assíncrono por natureza, e devolver um run que nunca vai
        rodar seria pior que recusar.

        `parametros` é do trabalho: o documento recebe `com_narrativa` e `modelo`; a
        similaridade recebe `modelo` e `limiar`. Os dois `modelo` existem para o teste
        injetar o falso; em produção ninguém passa.
        """
        if trabalho not in TRABALHOS:
            raise ValueError(f"trabalho desconhecido: {trabalho!r} (conhecidos: {TRABALHOS})")
        if db.get_notebook(notebook_id) is None:
            raise ValueError(f"caderno inexistente: {notebook_id}")

        try:
            laco = asyncio.get_running_loop()
        except RuntimeError as exc:  # pragma: no cover - erro de uso, não de app
            raise RuntimeError(
                "oficina.iniciar precisa de um laço de eventos rodando: "
                "chame de dentro de uma corrotina."
            ) from exc

        em_curso = self.em_curso(notebook_id, trabalho)
        if em_curso is not None:
            log.info("%s já em curso em %s: reaproveitando %s", trabalho, notebook_id, em_curso.id)
            return em_curso

        run = Run(
            id=f"run_{uuid.uuid4().hex[:10]}",
            notebook_id=notebook_id,
            trabalho=trabalho,
            origem=origem,
            parametros=dict(parametros or {}),
        )
        self._runs[run.id] = run
        self._podar()
        run.tarefa = laco.create_task(self._executar(run))
        return run

    def em_curso(self, notebook_id: str, trabalho: str | None = None) -> Run | None:
        for run in self._runs.values():
            if run.notebook_id != notebook_id or run.estado != "rodando":
                continue
            if trabalho is None or run.trabalho == trabalho:
                return run
        return None

    async def _executar(self, run: Run) -> None:
        """O trabalho de verdade. Roda como tarefa própria, fora de quem pediu."""

        async def avisar(passo: str, mensagem: str) -> None:
            run.passo, run.mensagem = passo, mensagem
            self._publicar(
                run, "trabalho.passo", {"run_id": run.id, "trabalho": run.trabalho,
                                        "passo": passo, "mensagem": mensagem}
            )

        try:
            if run.trabalho == DOCUMENTO:
                await self._documento(run, avisar)
            else:
                await self._similaridade(run, avisar)
        except (llm.ModeloNaoConfigurado, embed.EmbeddingNaoConfigurado) as exc:
            # Erro de configuração, não de execução: a mensagem já diz o que falta.
            run.erro = str(exc)
            run.estado = "erro"
            self._publicar(run, "error", {"run_id": run.id, "message": str(exc)})
        except Exception as exc:  # noqa: BLE001 — a falha é do run, e ela é reportada
            log.exception("falha no trabalho %s (%s)", run.trabalho, run.id)
            run.erro = f"{type(exc).__name__}: {str(exc)[:300]}"
            run.estado = "erro"
            self._publicar(
                run, "error", {"run_id": run.id, "message": run.erro + llm.explicar(exc)}
            )
        finally:
            run.terminado_em = time.time()
            self._publicar(run, "done", {"run_id": run.id, "estado": run.estado})

    async def _documento(self, run: Run, avisar: Emissor) -> None:
        documento = await artefato.compilar(
            run.notebook_id,
            modelo=run.parametros.get("modelo"),
            emitir=avisar,
            com_narrativa=run.parametros.get("com_narrativa", True),
        )
        saida = db.create_output(
            run.notebook_id,
            template="compilado",
            title=f"Documento compilado — {documento.titulo}",
            content_md=documento.markdown(),
        )
        run.output_id = saida["id"]
        run.resultado = {
            "secoes": len(documento.secoes),
            "contagem": documento.contagem(),
            "titulo": saida["title"],
        }
        run.estado = "pronto"
        self._publicar(
            run,
            "trabalho.pronto",
            {
                "run_id": run.id,
                "trabalho": run.trabalho,
                "resultado": run.resultado,
                # O corpo do documento vai no evento para a tela abrir sem uma segunda
                # requisição — é o que o botão faz desde o F5.
                "output": {
                    "id": saida["id"],
                    "title": saida["title"],
                    "template": saida["template"],
                    "content_md": saida["content_md"],
                },
            },
        )

    async def _similaridade(self, run: Run, avisar: Emissor) -> None:
        resultado = await similaridade.ligar(
            run.notebook_id,
            modelo=run.parametros.get("modelo"),
            limiar=run.parametros.get("limiar") or similaridade.LIMIAR,
            limiar_mesclar=run.parametros.get("limiar_mesclar") or similaridade.LIMIAR_MESCLAR,
            emitir=avisar,
        )
        run.resultado = resultado.resumo()
        run.estado = "pronto"
        self._publicar(
            run,
            "trabalho.pronto",
            {"run_id": run.id, "trabalho": run.trabalho, "resultado": run.resultado, "output": None},
        )

    # ------------------------------------------------------------- acompanhar

    def obter(self, run_id: str) -> Run | None:
        return self._runs.get(run_id)

    def ativos(
        self, notebook_id: str | None = None, *, trabalho: str | None = None
    ) -> list[dict[str, Any]]:
        """Os runs que a tela pode querer mostrar, do mais novo para o mais antigo.

        É por aqui que o painel descobre uma tarefa nascida numa ferramenta do agente:
        ele não sabe que ela existe até perguntar.
        """
        self._podar()
        escolhidos = [
            run
            for run in self._runs.values()
            if (notebook_id is None or run.notebook_id == notebook_id)
            and (trabalho is None or run.trabalho == trabalho)
        ]
        return [run.resumo() for run in sorted(escolhidos, key=lambda r: r.criado_em, reverse=True)]

    async def acompanhar(self, run_id: str) -> AsyncIterator[dict[str, Any]]:
        """O run em eventos, para quem pedir a qualquer momento. `KeyError` se não existe.

        O histórico vem **antes** do ao vivo, e isso não é detalhe: quem chega atrasado
        (a tela recarregou, ou a tarefa nasceu de uma ferramenta do agente) precisa ver
        os passos que já aconteceram. Sem o histórico, o acompanhamento começaria no
        meio e a tela mostraria um resultado sem procedência.
        """
        run = self._runs[run_id]
        for item in run.eventos:
            yield item
            if item["evento"] == "done":
                return
        if run.estado != "rodando":
            return

        fila: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        run.ouvintes.append(fila)
        try:
            while True:
                item = await fila.get()
                yield item
                if item["evento"] == "done":
                    return
        finally:
            with suppress(ValueError):
                run.ouvintes.remove(fila)

    async def esperar(self, run_id: str, *, timeout: float = 120.0) -> Run:
        """Bloqueia até o run terminar. A tela não usa isto — o teste usa."""
        run = self._runs[run_id]
        if run.tarefa is not None:
            await asyncio.wait_for(asyncio.shield(run.tarefa), timeout)
        return run

    # ------------------------------------------------------------- manutenção

    def _publicar(self, run: Run, evento: str, dados: dict[str, Any]) -> None:
        item = {"evento": evento, "dados": dados}
        run.eventos.append(item)
        for fila in list(run.ouvintes):
            fila.put_nowait(item)

    def _podar(self) -> None:
        agora = time.time()
        for run_id, run in list(self._runs.items()):
            if run.estado == "rodando":
                continue
            if run.terminado_em is not None and agora - run.terminado_em > TTL_SEGUNDOS:
                self._runs.pop(run_id, None)

        if len(self._runs) > MAX_RUNS:
            antigos = sorted(self._runs.items(), key=lambda par: par[1].criado_em)
            for run_id, run in antigos:
                if len(self._runs) <= MAX_RUNS:
                    break
                if run.estado != "rodando":
                    self._runs.pop(run_id, None)

    def limpar(self) -> None:
        """Zera a oficina (o `conftest` chama entre testes; o app nunca precisa).

        Cancela o que estiver rodando, e engole o `RuntimeError` de cancelar tarefa de
        laço já fechado: em teste, `asyncio.run` fecha o laço no fim, e um run que
        ficou pela metade não tem mais a quem voltar. Recusar aqui só quebraria a
        limpeza por causa de algo que já não existe.
        """
        for run in self._runs.values():
            if run.tarefa is not None and not run.tarefa.done():
                with suppress(RuntimeError):
                    run.tarefa.cancel()
        self._runs.clear()


# A oficina do processo. Uma só: o app é de uma máquina e de um usuário (seção 1), e
# uma segunda instância seria uma segunda lista de runs sem nada a sincronizar.
oficina = Oficina()
