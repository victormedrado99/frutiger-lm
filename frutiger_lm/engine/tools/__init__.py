"""Ferramentas do motor, presas a um caderno (D034).

O catálogo é montado **por caderno**, não global: cada ferramenta já sabe em qual
caderno está operando. Três razões, e a segunda é a que mais importa:

1. O modelo não tem como errar o id do caderno.
2. O modelo **não consegue** ler as fontes de outro caderno. Isolamento real, não
   confiança no comportamento do modelo.
3. O schema fica menor — e schema menor melhora a escolha de ferramenta (D025).
"""

from .leitura import ferramentas_de_leitura

__all__ = ["ferramentas_de_leitura"]
