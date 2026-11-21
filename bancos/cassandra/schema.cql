-- =============================================================================
-- Cassandra: eventos de navegação (R6)
--
-- R6: registrar todo evento de navegação (visualização, clique, busca), em
-- volume de centenas de milhares por hora, e consultar o histórico completo
-- de um usuário.
--
-- No Cassandra a modelagem parte da CONSULTA, não das entidades: cada tabela
-- é desenhada para responder uma pergunta lendo uma única partição.
--
-- Script idempotente: recria as tabelas a cada carga.
-- (Comentários só em linhas próprias: o carga.py separa os comandos por ";".)
-- =============================================================================

-- Keyspace com SimpleStrategy e fator de replicação 1 porque o ambiente tem
-- um único nó. Em produção seria NetworkTopologyStrategy, com RF 3 por
-- datacenter (ex.: {'class': 'NetworkTopologyStrategy', 'dc1': 3}), para
-- tolerar a queda de nós e ler/gravar com QUORUM.
CREATE KEYSPACE IF NOT EXISTS marketplace
  WITH replication = {'class': 'SimpleStrategy', 'replication_factor': 1};

DROP TABLE IF EXISTS marketplace.eventos_por_usuario;
DROP TABLE IF EXISTS marketplace.meses_por_usuario;

-- -----------------------------------------------------------------------------
-- eventos_por_usuario: responde "histórico de navegação do usuário X",
-- do mais recente para o mais antigo.
--
-- Chave de partição (cliente_id, mes):
--   - todos os eventos de um usuário num mês ficam juntos, no mesmo nó, e são
--     lidos de uma vez;
--   - o "mes" limita o tamanho da partição: um usuário muito ativo não cria
--     uma partição infinita (o recomendado é ficar abaixo de ~100 MB).
-- Colunas de clusterização (ocorrido_em DESC, evento_id):
--   - dentro da partição, as linhas já ficam gravadas em ordem decrescente de
--     data, então a leitura sai ordenada sem nenhum ORDER BY;
--   - evento_id (UUID) desempata dois eventos no mesmo milissegundo e torna a
--     chave primária única (no Cassandra, INSERT com a mesma chave sobrescreve).
-- -----------------------------------------------------------------------------
CREATE TABLE marketplace.eventos_por_usuario (
    cliente_id   int,
    mes          text,
    ocorrido_em  timestamp,
    evento_id    uuid,
    tipo         text,
    produto_id   int,
    termo        text,
    dispositivo  text,
    PRIMARY KEY ((cliente_id, mes), ocorrido_em, evento_id)
) WITH CLUSTERING ORDER BY (ocorrido_em DESC, evento_id ASC);

-- -----------------------------------------------------------------------------
-- meses_por_usuario: responde "em quais meses o usuário X tem eventos?".
-- É o índice que a aplicação lê primeiro para montar o histórico completo:
-- 1 partição aqui + 1 partição por mês em eventos_por_usuario.
-- Desnormalizar assim (uma tabela por consulta) é o padrão no Cassandra.
-- -----------------------------------------------------------------------------
CREATE TABLE marketplace.meses_por_usuario (
    cliente_id  int,
    mes         text,
    PRIMARY KEY ((cliente_id), mes)
) WITH CLUSTERING ORDER BY (mes DESC);
