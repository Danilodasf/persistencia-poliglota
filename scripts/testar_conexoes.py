"""
Teste rápido do ambiente: conecta nos cinco bancos e imprime a versão de cada um.

    docker compose run --rm app python scripts/testar_conexoes.py
"""

import sys

from scripts.comum import (
    conectar_cassandra,
    conectar_mongo,
    conectar_neo4j,
    conectar_postgres,
    conectar_redis,
)


def postgres():
    with conectar_postgres() as con:
        return con.execute("SELECT version()").fetchone()[0].split(",")[0]


def redis():
    r = conectar_redis()
    r.ping()
    return "Redis " + r.info("server")["redis_version"]


def mongodb():
    db = conectar_mongo()
    return "MongoDB " + db.client.server_info()["version"]


def cassandra():
    sessao = conectar_cassandra()
    versao = sessao.execute("SELECT release_version FROM system.local").one()[0]
    sessao.cluster.shutdown()
    return "Cassandra " + versao


def neo4j():
    driver = conectar_neo4j()
    with driver.session() as s:
        reg = s.run("CALL dbms.components() YIELD name, versions RETURN name, versions[0] AS v").single()
    driver.close()
    return f"{reg['name']} {reg['v']}"


falhas = 0
for nome, teste in [("postgres", postgres), ("redis", redis), ("mongodb", mongodb),
                    ("cassandra", cassandra), ("neo4j", neo4j)]:
    try:
        print(f"[ok]    {nome:<10} {teste()}")
    except Exception as erro:  # mostra o erro e segue para o próximo banco
        falhas += 1
        print(f"[falha] {nome:<10} {type(erro).__name__}: {erro}")

sys.exit(1 if falhas else 0)
