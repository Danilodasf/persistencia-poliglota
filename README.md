# Persistência Poliglota: Marketplace

Trabalho Final N3 da disciplina de Banco de Dados.
**Grupo:** Matheus Henrique de Araujo Carneiro, Danilo da Silva Faria e Leonardo Pacheco de Oliveira Vaz.

Um marketplace em que cada requisito é atendido pelo banco cujo modelo de dados resolve aquele problema de forma nativa. São cinco bancos ao mesmo tempo: **PostgreSQL, MongoDB, Redis, Cassandra e Neo4j**. Não há interface nem API. O repositório traz um ambiente Docker que sobe os cinco bancos e scripts Python que **simulam o que a aplicação faria** contra cada um: carga de dados e demonstrações que mostram o comando executado e o retorno obtido.

---

## Qual banco atende cada requisito

| Req. | Necessidade | Banco | Estrutura |
|---|---|---|---|
| R1 | Pedido + itens + baixa de estoque, tudo ou nada | **PostgreSQL** | Tabelas `cliente`, `produto_estoque`, `pedido`, `item_pedido`, `pagamento`, numa transação ACID com `SELECT ... FOR UPDATE` |
| R2 | Catálogo com atributos diferentes por categoria | **MongoDB** | Coleção `produtos` com subdocumento `atributos` |
| R3 | Sessão que expira após 30 min de inatividade | **Redis** | `sessao:{token}` (hash) + `EXPIRE 1800`, renovado a cada acesso |
| R4 | Carrinho com alteração muito frequente | **Redis** | `carrinho:{cliente_id}` (hash produto → quantidade) |
| R5 | Contagem de visualizações + ranking sempre ordenado | **Redis** | `ranking:visualizacoes` (sorted set + `ZINCRBY`) |
| R6 | Centenas de milhares de eventos/hora + histórico do usuário | **Cassandra** | `eventos_por_usuario`, PK `((cliente_id, mes), ocorrido_em DESC, evento_id)` |
| R7 | "Quem comprou também comprou" / clientes parecidos | **Neo4j** | `(:Cliente)-[:COMPROU]->(:Produto)` |
| R8 | Produtos de uma marca, navegação rápida, sem o banco principal | **Redis** | `marca:{slug}` (sorted set) + `produto_resumo:{id}` (hash) |

Todos os bancos usam **os mesmos IDs** (`cliente_id`, `produto_id`), gerados num único dataset com seed fixa. O PostgreSQL é a fonte da verdade transacional; os outros bancos guardam projeções especializadas.

---

## Pré-requisitos

- **Docker Desktop** (ou Docker Engine + Compose v2) com **pelo menos 6 GB de RAM** liberados para o Docker.
  No Docker Desktop: *Settings → Resources → Memory*.
- **Git**, para clonar o repositório.
- Não é preciso instalar Python nem drivers: os scripts rodam dentro do container `app`.

Portas usadas no computador: 5432 (PostgreSQL), 6379 (Redis), 27017 (MongoDB), 9042 (Cassandra), 7474 e 7687 (Neo4j).

---

## Como executar

Na pasta do repositório:

```bash
cp .env.example .env
docker compose up -d                                   # sobe os 5 bancos (E3)
docker compose run --rm app python scripts/carregar_tudo.py
docker compose run --rm app python scripts/demonstrar_tudo.py
docker compose down -v                                 # derruba e apaga os dados
```

1. **`cp .env.example .env`** cria o arquivo de credenciais (no PowerShell, o `cp` também funciona).
2. **`docker compose up -d`** sobe os cinco bancos. Na primeira vez, o Docker baixa as imagens (alguns minutos). Para esperar até todos ficarem prontos, use `docker compose up -d --wait`; leva cerca de 1 minuto, porque o Cassandra é o mais lento. Para conferir o estado: `docker compose ps` (todos devem aparecer como `healthy`).
3. **`carregar_tudo.py`** gera o dataset em `dados/dataset/` (se ainda não existir) e carrega os cinco bancos, mostrando o tempo de cada um. Leva cerca de 30 s. O comando `docker compose run` espera os bancos ficarem saudáveis antes de começar.
4. **`demonstrar_tudo.py`** roda as cinco demonstrações. Cada uma imprime as operações e o retorno e grava `saidas/<banco>.txt`.
5. **`docker compose down -v`** para tudo e apaga os volumes. Sem o `-v`, os dados continuam lá na próxima subida.

### Rodar um banco isolado

Cada banco tem a sua carga e a sua demonstração, e elas podem rodar separadas:

```bash
docker compose run --rm app python bancos/postgres/carga.py
docker compose run --rm app python bancos/postgres/demo.py
```

Troque `postgres` por `mongodb`, `redis`, `cassandra` ou `neo4j`. As cargas recriam as estruturas do zero e podem ser repetidas. As demos também podem ser repetidas.

Outros comandos úteis:

```bash
docker compose run --rm app python scripts/testar_conexoes.py       # testa a conexão com os 5 bancos
docker compose run --rm app python dados/gerar_dataset.py           # gera o dataset de novo
docker compose run --rm app python scripts/carregar_tudo.py --regenerar
```

### Abrir o console de cada banco

Com as credenciais padrão do `.env.example`:

```bash
docker exec -it mp_postgres psql -U marketplace -d marketplace
docker exec -it mp_mongodb mongosh -u marketplace -p marketplace123 --authenticationDatabase admin marketplace
docker exec -it mp_redis redis-cli -a marketplace123
docker exec -it mp_cassandra cqlsh -k marketplace
docker exec -it mp_neo4j cypher-shell -u neo4j -p marketplace123
```

O Neo4j também tem uma interface web em <http://localhost:7474> (usuário `neo4j`, senha `marketplace123`). Um exemplo para ver o grafo: `MATCH (c:Cliente {id: 159})-[r:COMPROU]->(p) RETURN c, r, p`.

---

## O que cada demonstração mostra

O retorno de cada demonstração fica versionado em [`saidas/`](saidas/).

| Banco | Saída | Operações |
|---|---|---|
| PostgreSQL | [saidas/postgres.txt](saidas/postgres.txt) | (1) pedido válido: estoque antes → transação → estoque depois; (2) estoque insuficiente no meio da transação → `ROLLBACK`, nada muda; (3) pedidos de um cliente com itens e pagamento (JOIN); (4) `CHECK (estoque >= 0)` recusa estoque negativo |
| MongoDB | [saidas/mongodb.txt](saidas/mongodb.txt) | (1) celular × livro com atributos diferentes; (2) livros com mais de 300 páginas + plano de execução; (3) celulares por memória e tela; (4) categoria nova "fone" sem alterar esquema; (5) validador recusa produto sem preço |
| Redis | [saidas/redis.txt](saidas/redis.txt) | (1) sessão com TTL renovado a cada acesso e expiração automática; (2) carrinho: adicionar, alterar, remover, listar; (3) ranking: top 10 antes e depois de novas visualizações; (4) produtos de uma marca, ordenados por nome |
| Cassandra | [saidas/cassandra.txt](saidas/cassandra.txt) | (1) inserir eventos de um usuário; (2) histórico completo do mais recente ao mais antigo; (3) eventos de um dia (faixa na clusterização); (4) por que consultar sem a partition key não é o padrão (`ALLOW FILTERING`) |
| Neo4j | [saidas/neo4j.txt](saidas/neo4j.txt) | (1) "quem comprou este produto também comprou"; (2) "clientes com histórico parecido compraram isto"; (3) caminho no grafo que explica a recomendação |

---

## Dados

O arquivo `dados/gerar_dataset.py` gera o dataset com `random.seed(42)` e `Faker('pt_BR')`. Rodar de novo produz exatamente os mesmos arquivos.

| Entidade | Volume | Usado por |
|---|---|---|
| Marcas (fictícias) | 20 | MongoDB, Redis |
| Produtos (celular, livro, camiseta, notebook, tênis) | 500 | MongoDB, PostgreSQL, Redis, Neo4j |
| Clientes | 1.000 | PostgreSQL, Neo4j |
| Pedidos (1 a 5 itens, com pagamento) | 3.000 | PostgreSQL, Neo4j (`COMPROU`) |
| Eventos de navegação (ago–out/2026) | 100.000 | Cassandra, Redis (ranking) |
| Sessões ativas | 300 | Redis |
| Carrinhos | 200 | Redis |

Os pedidos têm afinidade proposital: quem compra um produto de uma marca tende a levar outro da mesma marca. Assim as recomendações do Neo4j fazem sentido. O ranking do Redis é derivado dos eventos de visualização. A pasta `dados/dataset/` não é versionada, porque é recriada pelo gerador.

---

## Estrutura do repositório

```
.
├── docker-compose.yml        # os 5 bancos + o container app (E3)
├── .env.example              # credenciais (copiar para .env)
├── app/                      # Dockerfile e requirements do container Python
├── dados/gerar_dataset.py    # gera dados/dataset/*.json (seed fixa)
├── bancos/                   # um conjunto de scripts por banco (E4, E5)
│   ├── postgres/   schema.sql     carga.py  demo.py
│   ├── mongodb/                   carga.py  demo.py
│   ├── redis/                     carga.py  demo.py
│   ├── cassandra/  schema.cql     carga.py  demo.py
│   └── neo4j/      schema.cypher  carga.py  demo.py
├── scripts/
│   ├── comum.py              # conexões + helper que imprime e grava as saídas
│   ├── carregar_tudo.py      # gera o dataset (se preciso) e carrega os 5 bancos
│   ├── demonstrar_tudo.py    # roda as 5 demonstrações
│   └── testar_conexoes.py    # testa a conexão com os 5 bancos
└── saidas/                   # retorno de cada demonstração (E5)
```

Os comentários dos arquivos `schema.*` e `carga.py` explicam o porquê de cada decisão de modelagem.

---

## Solução de problemas

| Sintoma | Causa provável e solução |
|---|---|
| `docker compose run` fica parado em "Waiting" por 1 a 2 minutos | Normal na primeira subida: o Cassandra demora para aceitar conexões. O comando continua sozinho quando todos ficam `healthy`. |
| Cassandra ou Neo4j aparecem como `unhealthy` ou reiniciam (`Exited (137)`) | Falta de memória. Aumente a RAM do Docker Desktop para 6 GB ou mais (de preferência 8 GB) e feche outros programas pesados. Depois: `docker compose down` e `docker compose up -d`. |
| `docker compose up` diz que a porta já está em uso (`port is already allocated`) | Outro serviço na máquina usa a porta (ex.: um PostgreSQL local na 5432). Pare esse serviço ou troque a porta da esquerda no `docker-compose.yml` (ex.: `"15432:5432"`). Os scripts não são afetados, porque falam com os bancos pela rede interna do Docker. |
| `variable is not set` ou erro de autenticação | O arquivo `.env` não existe. Rode `cp .env.example .env`. |
| Erro "dataset não encontrado" numa carga isolada | Rode `docker compose run --rm app python dados/gerar_dataset.py` (o `carregar_tudo.py` já faz isso sozinho). |
| Algum banco ficou com dados estranhos | Rode a carga dele de novo (ela recria tudo), ou recomece do zero: `docker compose down -v`, `docker compose up -d` e `carregar_tudo.py`. |
| `git` ou `docker` não reconhecido no terminal, logo após instalar | Feche e abra o terminal de novo, para ele ler o PATH atualizado. |

Na máquina de desenvolvimento (Docker com 6 GB), os cinco bancos sobem em cerca de 60 s, a carga completa leva cerca de 30 s (o Cassandra responde por 18 s) e as demonstrações cerca de 7 s. Com os bancos ociosos, o uso de memória fica em torno de 2 GB.
