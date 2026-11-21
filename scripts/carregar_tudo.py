"""
Carrega os cinco bancos de uma vez (E4).

    docker compose run --rm app python scripts/carregar_tudo.py
    docker compose run --rm app python scripts/carregar_tudo.py --regenerar   # gera o dataset de novo

1. Se dados/dataset/ não existir (ou faltar algum arquivo), roda o gerador
   (dados/gerar_dataset.py, seed fixa: o resultado é sempre o mesmo).
2. Executa a carga de cada banco (bancos/<banco>/carga.py), mostrando o tempo.
   Cada carga recria as estruturas do zero, então pode ser repetida.
"""

import importlib
import subprocess
import sys
import time

from scripts.comum import PASTA_DATASET, RAIZ, formatar_tabela

BANCOS = ["postgres", "mongodb", "redis", "cassandra", "neo4j"]
ARQUIVOS = ["marcas", "produtos", "clientes", "pedidos", "eventos", "sessoes", "carrinhos"]


def garantir_dataset(regenerar=False):
    faltando = [a for a in ARQUIVOS if not (PASTA_DATASET / f"{a}.json").exists()]
    if regenerar or faltando:
        motivo = "--regenerar" if regenerar else f"faltando: {', '.join(faltando)}"
        print(f"== Gerando o dataset ({motivo}) ==")
        subprocess.run([sys.executable, str(RAIZ / "dados" / "gerar_dataset.py")], check=True)
    else:
        print("== Dataset já existe em dados/dataset/ (use --regenerar para gerar de novo) ==")


def main():
    inicio = time.time()
    garantir_dataset(regenerar="--regenerar" in sys.argv)

    resumo, falhas = [], 0
    for banco in BANCOS:
        print(f"\n== Carga: {banco} ==")
        t = time.time()
        try:
            importlib.import_module(f"bancos.{banco}.carga").carregar()
            resumo.append((banco, "ok", f"{time.time() - t:.1f} s"))
        except Exception as erro:  # registra e segue para os outros bancos
            falhas += 1
            print(f"ERRO na carga do {banco}: {type(erro).__name__}: {erro}")
            resumo.append((banco, "ERRO", f"{time.time() - t:.1f} s"))

    print("\n== Resumo da carga ==")
    print(formatar_tabela(["banco", "status", "tempo"], resumo))
    print(f"Tempo total: {time.time() - inicio:.1f} s")
    sys.exit(1 if falhas else 0)


if __name__ == "__main__":
    main()
