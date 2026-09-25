"""Motor do Frutiger LM — a fronteira (D018).

Só este pacote importa LangChain / LangGraph. O resto do app (db, knowledge,
app, export) não conhece a biblioteca. Três consequências, todas deliberadas:

1. Atualizar a lib mexe em um pacote só.
2. O resto do app testa com banco e arquivos de verdade, sem rede (engine/fake.py).
3. Se o LangGraph decepcionar, um laço próprio entra como implementação
   alternativa **aqui dentro** — o app não precisa saber.

Mapa:

    llm.py         fábrica de modelo (D020); a única porta para o modelo
    fake.py        modelos falsos para teste, sem rede/chave/custo
    checkpoint.py  persistência da conversa; 1 caderno = 1 thread_id (D019, D033)
    agent.py       o agente do caderno: modelo + ferramentas + memória
    tools/         o catálogo, preso ao caderno (D034) e com saída limitada (D035)
"""

__all__ = ["agent", "checkpoint", "fake", "llm"]
