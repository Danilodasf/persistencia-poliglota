"""
Carga do Neo4j (R7): nós Cliente e Produto e relações COMPROU derivadas dos
pedidos (R1).

    docker compose run --rm app python bancos/neo4j/carga.py

Tudo em lote com UNWIND: uma lista de mapas é enviada como parâmetro e o
Cypher cria um nó/relação por elemento, em vez de uma ida ao servidor por
registro.
"""

import time
from pathlib import Path

from scripts.comum import conectar_neo4j, ler_dataset

SCHEMA = Path(__file__).with_name("schema.cypher")
LOTE = 1000


def comandos_cypher(texto):
    """Separa o schema.cypher em comandos (ignora linhas de comentário //)."""
    sem_comentarios = "\n".join(l for l in texto.splitlines() if not l.strip().startswith("//"))
    return [c.strip() for c in sem_comentarios.split(";") if c.strip()]


def em_lotes(lista, tamanho=LOTE):
    for i in range(0, len(lista), tamanho):
        yield lista[i:i + tamanho]


def carregar():
    inicio = time.time()
    clientes = ler_dataset("clientes")
    produtos = ler_dataset("produtos")
    pedidos = ler_dataset("pedidos")

    # Agrega os pedidos em uma compra por (cliente, produto).
    compras = {}
    for p in pedidos:
        if p["status"] == "cancelado":  # pagamento recusado: não houve compra
            continue
        for item in p["itens"]:
            chave = (p["cliente_id"], item["produto_id"])
            c = compras.setdefault(chave, {"cliente_id": chave[0], "produto_id": chave[1],
                                           "vezes": 0, "quantidade": 0, "ultima_compra": ""})
            c["vezes"] += 1
            c["quantidade"] += item["quantidade"]
            c["ultima_compra"] = max(c["ultima_compra"], p["criado_em"])
    compras = list(compras.values())

    driver = conectar_neo4j()
    with driver.session() as s:
        # Recomeça do zero: a carga pode ser repetida.
        s.run("MATCH (n) DETACH DELETE n").consume()
        for comando in comandos_cypher(SCHEMA.read_text(encoding="utf-8")):
            s.run(comando).consume()

        for lote in em_lotes([{"id": c["id"], "nome": c["nome"], "cidade": c["cidade"], "uf": c["uf"]}
                              for c in clientes]):
            s.run("UNWIND $linhas AS l CREATE (:Cliente {id: l.id, nome: l.nome, cidade: l.cidade, uf: l.uf})",
                  linhas=lote).consume()

        for lote in em_lotes([{"id": p["id"], "nome": p["nome"], "categoria": p["categoria"], "marca": p["marca"]}
                              for p in produtos]):
            s.run("UNWIND $linhas AS l "
                  "CREATE (:Produto {id: l.id, nome: l.nome, categoria: l.categoria, marca: l.marca})",
                  linhas=lote).consume()

        # MATCH usa o índice das constraints para achar as duas pontas de cada relação.
        for lote in em_lotes(compras):
            s.run("UNWIND $linhas AS l "
                  "MATCH (c:Cliente {id: l.cliente_id}) "
                  "MATCH (p:Produto {id: l.produto_id}) "
                  "CREATE (c)-[:COMPROU {vezes: l.vezes, quantidade: l.quantidade, "
                  "ultima_compra: datetime(l.ultima_compra)}]->(p)",
                  linhas=lote).consume()

        n_clientes = s.run("MATCH (c:Cliente) RETURN count(c) AS n").single()["n"]
        n_produtos = s.run("MATCH (p:Produto) RETURN count(p) AS n").single()["n"]
        n_rel = s.run("MATCH ()-[r:COMPROU]->() RETURN count(r) AS n").single()["n"]
        constraints = [r["name"] for r in s.run("SHOW CONSTRAINTS YIELD name RETURN name ORDER BY name")]
    driver.close()

    print("Neo4j: carga concluída")
    print(f"  (:Cliente)       {n_clientes:>6} nós")
    print(f"  (:Produto)       {n_produtos:>6} nós")
    print(f"  [:COMPROU]       {n_rel:>6} relações (pares cliente-produto, sem pedidos cancelados)")
    print(f"  constraints: {', '.join(constraints)}")
    print(f"  tempo: {time.time() - inicio:.1f} s")
    return {"Cliente": n_clientes, "Produto": n_produtos, "COMPROU": n_rel}


if __name__ == "__main__":
    carregar()
