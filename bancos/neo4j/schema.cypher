// =============================================================================
// Neo4j: grafo de compras para recomendação (R7)
//
// Modelo:
//   (:Cliente {id, nome, cidade, uf})
//   (:Produto {id, nome, categoria, marca})
//   (:Cliente)-[:COMPROU {vezes, quantidade, ultima_compra}]->(:Produto)
//
// Por que grafo: as duas perguntas do R7 são caminhos.
//   "quem comprou X também comprou"   (X)<-[:COMPROU]-(c)-[:COMPROU]->(outro)
//   "clientes parecidos compraram"    (eu)-[:COMPROU]->(p)<-[:COMPROU]-(parecido)-[:COMPROU]->(rec)
// No Neo4j cada nó guarda ponteiros diretos para os seus relacionamentos
// (index-free adjacency): percorrer um salto custa o mesmo com mil ou com um
// bilhão de nós, porque só a vizinhança visitada é lida.
//
// Uma relação COMPROU por par (cliente, produto), mesmo que ele tenha comprado
// o produto em vários pedidos: "vezes" conta os pedidos e "quantidade" soma as
// unidades. Pedidos cancelados (pagamento recusado) não geram COMPROU.
//
// (Comentários só em linhas próprias: o carga.py separa os comandos por ";".)
// =============================================================================

// Unicidade dos ids (os mesmos do PostgreSQL/MongoDB/Redis). A constraint
// também cria um índice, usado pelo MATCH (c:Cliente {id: ...}) da carga e
// das consultas, para achar o nó de partida sem varrer o grafo.
CREATE CONSTRAINT cliente_id_unico IF NOT EXISTS
FOR (c:Cliente) REQUIRE c.id IS UNIQUE;

CREATE CONSTRAINT produto_id_unico IF NOT EXISTS
FOR (p:Produto) REQUIRE p.id IS UNIQUE;
