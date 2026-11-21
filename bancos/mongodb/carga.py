"""
Carga do MongoDB (R2): catálogo de produtos com atributos diferentes por categoria.

    docker compose run --rm app python bancos/mongodb/carga.py

Modelagem (coleção `produtos`, um documento por produto):

    {
      "_id": 1,                         <- mesmo produto_id do PostgreSQL/Redis/Neo4j
      "nome": "Celular Nexa X18 64GB",
      "categoria": "celular",
      "marca": "Nexa", "marca_slug": "nexa",
      "preco": 1124.66,
      "atributos": { "memoria_gb": 64, "tela_polegadas": 6.3, ... }   <- muda por categoria
    }

Por que assim:
  - Campos comuns a todo produto ficam no nível de cima (dá para filtrar e
    indexar do mesmo jeito em qualquer categoria).
  - O que é específico de cada categoria fica no subdocumento `atributos`. Um
    livro tem isbn/paginas, um celular tem memoria_gb/tela, e nenhum carrega
    campos vazios do outro. Uma categoria nova não exige alterar esquema.
  - O estoque NÃO fica aqui: ele muda a cada venda e precisa de transação
    junto com o pedido, então mora no PostgreSQL (R1).
  - Esquema flexível não quer dizer sem regra: um validador $jsonSchema exige
    os campos comuns e deixa `atributos` livre.
"""

import time
from collections import Counter

from pymongo import ASCENDING

from scripts.comum import conectar_mongo, ler_dataset

# Validador: obriga os campos comuns e o tipo de cada um; não diz nada sobre o
# conteúdo de `atributos`, que é justamente a parte que varia por categoria.
VALIDADOR = {
    "$jsonSchema": {
        "bsonType": "object",
        "required": ["nome", "categoria", "marca", "preco", "atributos"],
        "properties": {
            "nome": {"bsonType": "string"},
            "categoria": {"bsonType": "string"},
            "marca": {"bsonType": "string"},
            "marca_slug": {"bsonType": "string"},
            "preco": {"bsonType": ["double", "int", "decimal"], "minimum": 0},
            "atributos": {"bsonType": "object"},
        },
    }
}


def carregar():
    inicio = time.time()
    produtos = ler_dataset("produtos")
    db = conectar_mongo()

    # Recria a coleção do zero: a carga pode ser repetida sem duplicar dados.
    db.drop_collection("produtos")
    db.create_collection("produtos", validator=VALIDADOR)

    documentos = [
        {
            "_id": p["id"],
            "nome": p["nome"],
            "categoria": p["categoria"],
            "marca": p["marca"],
            "marca_slug": p["marca_slug"],
            "preco": p["preco"],
            "atributos": p["atributos"],
        }
        for p in produtos
    ]
    db.produtos.insert_many(documentos)  # um único lote, em vez de 500 idas ao servidor

    # Índices para as navegações mais comuns do catálogo.
    db.produtos.create_index([("categoria", ASCENDING)], name="idx_categoria")
    db.produtos.create_index([("marca_slug", ASCENDING)], name="idx_marca")

    total = db.produtos.count_documents({})
    por_categoria = Counter(d["categoria"] for d in db.produtos.find({}, {"categoria": 1}))
    print("MongoDB: carga concluída")
    print(f"  produtos         {total:>6} documentos")
    for cat, n in sorted(por_categoria.items()):
        print(f"    {cat:<14} {n:>6}")
    print(f"  índices: {', '.join(sorted(db.produtos.index_information()))}")
    print(f"  tempo: {time.time() - inicio:.1f} s")
    return {"produtos": total}


if __name__ == "__main__":
    carregar()
