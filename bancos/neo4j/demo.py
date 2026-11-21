"""
Demonstração do Neo4j (R7): recomendações por travessia do grafo de compras.

    docker compose run --rm app python bancos/neo4j/demo.py

Operações:
  1. "Quem comprou este produto também comprou"
  2. "Clientes com histórico parecido com o seu compraram isto": acha os
     clientes com mais produtos em comum e recomenda o que eles compraram e
     o cliente ainda não comprou
  3. Um caminho concreto do grafo que justifica a 1ª recomendação

Retorno gravado em saidas/neo4j.txt.
"""

from scripts.comum import Saida, conectar_neo4j

CLIENTE_DEMO = 159

# O produto com mais compradores distintos: o exemplo mais "cheio" para a demo.
Q_PRODUTO_DEMO = """
MATCH (p:Produto)<-[:COMPROU]-(c:Cliente)
RETURN p.id AS id, p.nome AS nome, count(c) AS compradores
ORDER BY compradores DESC, id LIMIT 1"""

Q_TAMBEM_COMPROU = """
MATCH (p:Produto {id: $produto})<-[:COMPROU]-(c:Cliente)-[:COMPROU]->(outro:Produto)
WHERE outro <> p
RETURN outro.id AS id, outro.nome AS nome, outro.categoria AS categoria, outro.marca AS marca,
       count(DISTINCT c) AS clientes_em_comum
ORDER BY clientes_em_comum DESC, id
LIMIT 5"""

Q_MEU_HISTORICO = """
MATCH (eu:Cliente {id: $cliente})-[r:COMPROU]->(p:Produto)
RETURN p.marca AS marca, count(p) AS produtos, collect(DISTINCT p.categoria) AS categorias
ORDER BY produtos DESC, marca"""

Q_PARECIDOS = """
MATCH (eu:Cliente {id: $cliente})-[:COMPROU]->(p:Produto)<-[:COMPROU]-(outro:Cliente)
WHERE outro <> eu
RETURN outro.id AS id, outro.nome AS nome, count(DISTINCT p) AS produtos_em_comum
ORDER BY produtos_em_comum DESC, id
LIMIT 10"""

Q_RECOMENDACAO = """
// 1) os 10 clientes mais parecidos: os que têm mais produtos em comum comigo
MATCH (eu:Cliente {id: $cliente})-[:COMPROU]->(p:Produto)<-[:COMPROU]-(outro:Cliente)
WHERE outro <> eu
WITH eu, outro, count(DISTINCT p) AS em_comum
ORDER BY em_comum DESC, outro.id
LIMIT 10
// 2) o que eles compraram e eu ainda não comprei
MATCH (outro)-[:COMPROU]->(rec:Produto)
WHERE NOT (eu)-[:COMPROU]->(rec)
// 3) pontuação: soma da semelhança de quem recomenda
RETURN rec.id AS id, rec.nome AS nome, rec.categoria AS categoria, rec.marca AS marca,
       count(DISTINCT outro) AS recomendado_por, sum(em_comum) AS pontuacao
ORDER BY pontuacao DESC, recomendado_por DESC, id
LIMIT 5"""

Q_CAMINHO = """
MATCH caminho = (eu:Cliente {id: $cliente})-[:COMPROU]->(p:Produto)
                <-[:COMPROU]-(outro:Cliente)-[:COMPROU]->(rec:Produto {id: $rec})
WHERE outro.id IN $parecidos
RETURN eu.nome AS eu, p.nome AS produto_comum, outro.id AS outro_id, outro.nome AS outro,
       rec.nome AS recomendado, length(caminho) AS saltos
ORDER BY outro.id, p.id
LIMIT 1"""


def consultar(driver, cypher, **params):
    registros, _, _ = driver.execute_query(cypher, params, database_="neo4j")
    return registros


def main():
    driver = conectar_neo4j()

    with Saida("neo4j") as s:
        s.nota("""
            Neo4j atende o R7: recomendação é travessia de relacionamentos
            (:Cliente)-[:COMPROU]->(:Produto). A consulta descreve o caminho
            em vez de encadear self-joins.
        """)

        # ------------------------------------------------------------------ 1
        alvo = consultar(driver, Q_PRODUTO_DEMO)[0]
        s.operacao("R7", f"\"Quem comprou este produto também comprou\": produto {alvo['id']} "
                         f"({alvo['nome']}, {alvo['compradores']} compradores)",
                   Q_TAMBEM_COMPROU.replace("$produto", str(alvo["id"])))
        s.tabela(["id", "nome", "categoria", "marca", "clientes_em_comum"],
                 [tuple(r.values()) for r in consultar(driver, Q_TAMBEM_COMPROU, produto=alvo["id"])])
        s.nota("""
            Leitura do caminho: parte do produto, volta pelas setas COMPROU até
            quem o comprou e segue para os outros produtos dessas pessoas,
            contando quantos clientes cada par tem em comum.
            Em SQL seria: item_pedido JOIN pedido JOIN pedido JOIN item_pedido
            (self-join) + GROUP BY. Cada salto a mais seria mais um par de joins.
            Limitação conhecida: a contagem simples favorece produtos populares
            (aparecem com quase tudo). Um sistema real normalizaria, por exemplo
            com similaridade de Jaccard, sem mudar o padrão de caminho.
        """)

        # ------------------------------------------------------------------ 2
        s.operacao("R7", f"\"Clientes com histórico parecido compraram isto\": recomendações para o cliente {CLIENTE_DEMO}",
                   Q_RECOMENDACAO.replace("$cliente", str(CLIENTE_DEMO)))
        s.tabela(["marca", "produtos", "categorias"],
                 [(r["marca"], r["produtos"], ", ".join(r["categorias"]))
                  for r in consultar(driver, Q_MEU_HISTORICO, cliente=CLIENTE_DEMO)],
                 f"Histórico do cliente {CLIENTE_DEMO} (o que ele já comprou, por marca)")
        parecidos = consultar(driver, Q_PARECIDOS, cliente=CLIENTE_DEMO)
        s.tabela(["id", "nome", "produtos_em_comum"], [tuple(r.values()) for r in parecidos],
                 "Os 10 clientes mais parecidos (passo 1 da consulta)")
        recs = consultar(driver, Q_RECOMENDACAO, cliente=CLIENTE_DEMO)
        s.tabela(["id", "nome", "categoria", "marca", "recomendado_por", "pontuacao"],
                 [tuple(r.values()) for r in recs], "Recomendações (produtos que ele ainda não comprou)")
        s.nota("""
            pontuacao = soma dos produtos em comum de cada cliente parecido que
            comprou o item: quanto mais parecido quem recomenda, mais peso.
            O filtro WHERE NOT (eu)-[:COMPROU]->(rec) também é um padrão de
            caminho: "não existe a seta de mim até este produto".
        """)

        # ------------------------------------------------------------------ 3
        top = recs[0]
        ids_parecidos = [r["id"] for r in parecidos]
        s.operacao("R7", f"Por que o produto {top['id']} foi recomendado: um caminho concreto no grafo",
                   Q_CAMINHO.replace("$cliente", str(CLIENTE_DEMO)).replace("$rec", str(top["id"]))
                   .replace("$parecidos", str(ids_parecidos)))
        c = consultar(driver, Q_CAMINHO, cliente=CLIENTE_DEMO, rec=top["id"], parecidos=ids_parecidos)[0]
        s.retorno(
            f"({c['eu']})\n"
            f"   -[:COMPROU]-> ({c['produto_comum']})\n"
            f"   <-[:COMPROU]- (cliente {c['outro_id']}: {c['outro']})\n"
            f"   -[:COMPROU]-> ({c['recomendado']})\n"
            f"{c['saltos']} saltos",
        )
        s.nota("""
            A recomendação é explicável: dá para mostrar ao usuário "porque
            clientes que compraram o mesmo que você também levaram isto".
        """)

    driver.close()


if __name__ == "__main__":
    main()
