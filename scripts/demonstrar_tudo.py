"""
Roda as cinco demonstrações em sequência (E5).

    docker compose run --rm app python scripts/demonstrar_tudo.py

Cada demo imprime as operações e o retorno e grava saidas/<banco>.txt.
Pré-requisito: os bancos carregados (scripts/carregar_tudo.py).
"""

import importlib
import sys
import time

from scripts.comum import PASTA_SAIDAS, formatar_tabela

BANCOS = ["postgres", "mongodb", "redis", "cassandra", "neo4j"]


def main():
    inicio = time.time()
    resumo, falhas = [], 0
    for banco in BANCOS:
        print(f"\n{'#' * 78}\n# DEMONSTRAÇÃO: {banco.upper()}\n{'#' * 78}")
        t = time.time()
        try:
            importlib.import_module(f"bancos.{banco}.demo").main()
            texto = (PASTA_SAIDAS / f"{banco}.txt").read_text(encoding="utf-8")
            operacoes = sum(1 for l in texto.splitlines() if l.startswith("Operação "))
            resumo.append((banco, "ok", operacoes, f"saidas/{banco}.txt", f"{time.time() - t:.1f} s"))
        except Exception as erro:
            falhas += 1
            print(f"ERRO na demo do {banco}: {type(erro).__name__}: {erro}")
            resumo.append((banco, "ERRO", "-", "-", f"{time.time() - t:.1f} s"))

    print("\n== Resumo das demonstrações ==")
    print(formatar_tabela(["banco", "status", "operacoes", "saida", "tempo"], resumo))
    print(f"Tempo total: {time.time() - inicio:.1f} s")
    sys.exit(1 if falhas else 0)


if __name__ == "__main__":
    main()
