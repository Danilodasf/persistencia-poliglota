"""
Funções compartilhadas por todos os scripts de carga e demonstração.

- Uma função de conexão por banco, todas lendo as credenciais das variáveis de
  ambiente (o docker-compose injeta o .env no container "app").
- A classe Saida, que imprime cada operação e o retorno no terminal e grava
  tudo em saidas/<banco>.txt (entregável E5).

Uso típico num demo.py:

    from scripts.comum import conectar_redis, Saida

    r = conectar_redis()
    with Saida("redis") as s:
        s.operacao("R5", "Top 10 mais vistos", "ZREVRANGE ranking:visualizacoes 0 9 WITHSCORES")
        s.retorno(r.zrevrange("ranking:visualizacoes", 0, 9, withscores=True))
"""

import json
import os
import pprint
from datetime import datetime
from pathlib import Path

# Raiz do repositório (pasta acima de scripts/), usada para achar saidas/ e dados/.
RAIZ = Path(__file__).resolve().parent.parent
PASTA_SAIDAS = RAIZ / "saidas"


PASTA_DATASET = RAIZ / "dados" / "dataset"


def env(nome, padrao=None):
    """Lê uma variável de ambiente; o padrão é o valor do .env.example."""
    return os.environ.get(nome, padrao)


def ler_dataset(nome):
    """Lê dados/dataset/<nome>.json, com uma mensagem clara se o dataset ainda não foi gerado."""
    caminho = PASTA_DATASET / f"{nome}.json"
    if not caminho.exists():
        raise SystemExit(
            f"Arquivo {caminho.relative_to(RAIZ)} não encontrado. Gere o dataset antes:\n"
            "    docker compose run --rm app python dados/gerar_dataset.py"
        )
    with caminho.open(encoding="utf-8") as f:
        return json.load(f)


def formatar_tabela(cabecalho, linhas):
    """Monta uma tabela em texto (colunas alinhadas) para mostrar resultados de consultas."""
    linhas = [["" if v is None else str(v) for v in linha] for linha in linhas]
    larguras = [max(len(str(c)), *(len(l[i]) for l in linhas)) if linhas else len(str(c))
                for i, c in enumerate(cabecalho)]
    fmt = " | ".join(f"{{:<{w}}}" for w in larguras)
    saida = [fmt.format(*cabecalho).rstrip(), "-+-".join("-" * w for w in larguras)]
    saida += [fmt.format(*l).rstrip() for l in linhas]
    saida.append(f"({len(linhas)} linha{'s' if len(linhas) != 1 else ''})")
    return "\n".join(saida)


# ---------------------------------------------------------------------------
# Conexões
# ---------------------------------------------------------------------------

def conectar_postgres(autocommit=False):
    """Retorna uma conexão psycopg 3. Sem autocommit: as transações ficam explícitas (R1)."""
    import psycopg

    return psycopg.connect(
        host=env("POSTGRES_HOST", "postgres"),
        port=int(env("POSTGRES_PORT", "5432")),
        user=env("POSTGRES_USER", "marketplace"),
        password=env("POSTGRES_PASSWORD", "marketplace123"),
        dbname=env("POSTGRES_DB", "marketplace"),
        autocommit=autocommit,
        # datas TIMESTAMPTZ voltam no horário de Brasília (o servidor usa UTC)
        options="-c timezone=America/Sao_Paulo",
    )


def conectar_redis():
    """Retorna um cliente Redis que já devolve str em vez de bytes."""
    import redis

    return redis.Redis(
        host=env("REDIS_HOST", "redis"),
        port=int(env("REDIS_PORT", "6379")),
        password=env("REDIS_PASSWORD", "marketplace123"),
        decode_responses=True,
    )


def conectar_mongo():
    """Retorna o objeto Database do marketplace (o usuário root é autenticado no banco admin)."""
    from pymongo import MongoClient

    cliente = MongoClient(
        host=env("MONGO_HOST", "mongodb"),
        port=int(env("MONGO_PORT", "27017")),
        username=env("MONGO_USER", "marketplace"),
        password=env("MONGO_PASSWORD", "marketplace123"),
        authSource="admin",
    )
    return cliente[env("MONGO_DB", "marketplace")]


def conectar_cassandra(keyspace=None):
    """
    Retorna uma Session do Cassandra. Sem keyspace, serve para criar o keyspace
    (schema.cql); com keyspace, para carga e consultas.
    """
    from cassandra.cluster import Cluster

    cluster = Cluster(
        [env("CASSANDRA_HOST", "cassandra")],
        port=int(env("CASSANDRA_PORT", "9042")),
        protocol_version=5,
    )
    return cluster.connect(keyspace)


def conectar_neo4j():
    """Retorna um Driver do Neo4j (use: with driver.session() as s: ...)."""
    from neo4j import GraphDatabase

    uri = f"bolt://{env('NEO4J_HOST', 'neo4j')}:{env('NEO4J_PORT', '7687')}"
    return GraphDatabase.driver(
        uri, auth=(env("NEO4J_USER", "neo4j"), env("NEO4J_PASSWORD", "marketplace123"))
    )


# ---------------------------------------------------------------------------
# Saída das demonstrações (E5)
# ---------------------------------------------------------------------------

class Saida:
    """
    Imprime no terminal e grava em saidas/<nome>.txt ao mesmo tempo.
    Use como context manager: o arquivo é (re)escrito ao sair do bloco.
    """

    def __init__(self, nome):
        self.arquivo = PASTA_SAIDAS / f"{nome}.txt"
        self.linhas = []
        self.contador = 0

    def __enter__(self):
        agora = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
        self.escrever(f"Demonstração: {self.arquivo.stem}  (gerado em {agora})")
        return self

    def __exit__(self, *exc):
        PASTA_SAIDAS.mkdir(exist_ok=True)
        self.arquivo.write_text("\n".join(self.linhas) + "\n", encoding="utf-8")
        print(f"\n>> Saída gravada em {self.arquivo.relative_to(RAIZ)}")
        return False  # não engole exceções

    def escrever(self, texto=""):
        print(texto)
        self.linhas.append(texto)

    def operacao(self, requisito, descricao, comando=None):
        """Abre uma nova operação numerada, citando o requisito e o comando executado."""
        self.contador += 1
        self.escrever()
        self.escrever("=" * 78)
        self.escrever(f"Operação {self.contador} [{requisito}] {descricao}")
        self.escrever("=" * 78)
        if comando:
            self.escrever("Comando:")
            for linha in comando.strip().splitlines():
                self.escrever(f"    {linha}")

    def retorno(self, valor, rotulo="Retorno"):
        """Mostra o resultado; dicts/listas são formatados para ficar legíveis."""
        self.escrever(f"{rotulo}:")
        if isinstance(valor, str):
            texto = valor
        else:
            try:
                texto = json.dumps(valor, ensure_ascii=False, indent=2, default=str)
            except TypeError:
                texto = pprint.pformat(valor, width=100)
        for linha in texto.splitlines() or [""]:
            self.escrever(f"    {linha}")

    def tabela(self, cabecalho, linhas, rotulo="Retorno"):
        """Mostra o resultado de uma consulta como tabela alinhada."""
        self.retorno(formatar_tabela(cabecalho, linhas), rotulo)

    def nota(self, texto):
        """Comentário explicativo (o "porquê") que também vai para o arquivo."""
        for linha in texto.strip().splitlines():
            self.escrever(f"  # {linha.strip()}")
