"""Motor do Frutiger LM — a fronteira (D018).

Só este pacote importa LangChain / LangGraph. O resto do app (db, knowledge,
app, export) não conhece a biblioteca. Três consequências, todas deliberadas:

- quando a v2 do LangGraph chegar, o trabalho de atualização é aqui dentro;
- o resto do app testa contra funções nossas, sem framework;
- se a lib decepcionar, o loop próprio volta como implementação alternativa
  dentro daqui, sem tocar em mais nada.
"""

from .llm import ModeloNaoConfigurado, atual, build

__all__ = ["ModeloNaoConfigurado", "atual", "build"]
