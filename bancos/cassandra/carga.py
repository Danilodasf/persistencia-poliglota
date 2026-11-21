"""
Carga do Cassandra (R6): cria o keyspace/tabelas e grava os 100 mil eventos.

    docker compose run --rm app python bancos/cassandra/carga.py

As escritas são feitas com execute_concurrent_with_args: o driver mantém
muitas requisições em voo ao mesmo tempo (em vez de esperar a resposta de
cada INSERT), que é como uma aplicação real alimenta o Cassandra. Não usamos
BATCH para carga em massa: no Cassandra, BATCH serve para atomicidade entre
tabelas, não para desempenho, e batches grandes sobrecarregam o coordenador.
"""

import time
import uuid
from datetime import datetime
from pathlib import Path

from cassandra.concurrent import execute_concurrent_with_args

from scripts.comum import conectar_cassandra, env, ler_dataset

SCHEMA = Path(__file__).with_name("schema.cql")
KEYSPACE = env("CASSANDRA_KEYSPACE", "marketplace")


def comandos_cql(texto):
    """Separa o schema.cql em comandos (ignora linhas de comentário)."""
    sem_comentarios = "\n".join(l for l in texto.splitlines() if not l.strip().startswith("--"))
    return [c.strip() for c in sem_comentarios.split(";") if c.strip()]


def carregar():
    inicio = time.time()
    eventos = ler_dataset("eventos")

    sessao = conectar_cassandra()
    sessao.default_timeout = 120  # DROP/CREATE e o count(*) final podem demorar
    for comando in comandos_cql(SCHEMA.read_text(encoding="utf-8")):
        sessao.execute(comando)
    sessao.set_keyspace(KEYSPACE)

    # Prepared statement: o Cassandra analisa o comando uma vez; depois só os
    # valores trafegam.
    inserir_evento = sessao.prepare(
        "INSERT INTO eventos_por_usuario "
        "(cliente_id, mes, ocorrido_em, evento_id, tipo, produto_id, termo, dispositivo) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)"
    )
    inserir_mes = sessao.prepare("INSERT INTO meses_por_usuario (cliente_id, mes) VALUES (?, ?)")

    linhas = []
    meses = set()
    for e in eventos:
        quando = datetime.fromisoformat(e["ocorrido_em"])  # com fuso -03:00; o driver grava em UTC
        mes = quando.strftime("%Y-%m")
        linhas.append((e["cliente_id"], mes, quando, uuid.UUID(e["evento_id"]),
                       e["tipo"], e["produto_id"], e["termo"], e["dispositivo"]))
        meses.add((e["cliente_id"], mes))

    t = time.time()
    resultados = execute_concurrent_with_args(sessao, inserir_evento, linhas, concurrency=150,
                                              raise_on_first_error=True)
    tempo_eventos = time.time() - t
    execute_concurrent_with_args(sessao, inserir_mes, sorted(meses), concurrency=150,
                                 raise_on_first_error=True)

    total = sessao.execute("SELECT count(*) FROM eventos_por_usuario").one()[0]
    particoes = len(meses)
    print("Cassandra: carga concluída")
    print(f"  eventos_por_usuario {total:>7} linhas em {particoes} partições (cliente, mês)")
    print(f"  meses_por_usuario   {particoes:>7} linhas")
    print(f"  escrita dos eventos: {tempo_eventos:.1f} s ({len(resultados) / tempo_eventos:,.0f} inserts/s)")
    print(f"  tempo total: {time.time() - inicio:.1f} s")
    sessao.cluster.shutdown()
    return {"eventos_por_usuario": total, "meses_por_usuario": particoes}


if __name__ == "__main__":
    carregar()
