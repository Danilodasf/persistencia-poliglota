"""
Carga do PostgreSQL (R1): cria o schema e carrega clientes, estoque, pedidos,
itens e pagamentos a partir do dataset.

    docker compose run --rm app python bancos/postgres/carga.py

Usa COPY (carga em lote do PostgreSQL) em vez de milhares de INSERTs: é a
forma recomendada para volume, porque manda os dados num fluxo só.
"""

import time
from pathlib import Path

from scripts.comum import conectar_postgres, ler_dataset

SCHEMA = Path(__file__).with_name("schema.sql")


def carregar():
    inicio = time.time()
    clientes = ler_dataset("clientes")
    produtos = ler_dataset("produtos")
    pedidos = ler_dataset("pedidos")

    # "with conectar_postgres()" abre UMA transação para a carga inteira:
    # se qualquer etapa falhar, nada fica pela metade.
    with conectar_postgres() as con, con.cursor() as cur:
        cur.execute(SCHEMA.read_text(encoding="utf-8"))

        with cur.copy("COPY cliente (id, nome, email, cpf, cidade, uf, criado_em) FROM STDIN") as cp:
            for c in clientes:
                cp.write_row((c["id"], c["nome"], c["email"], c["cpf"], c["cidade"], c["uf"], c["criado_em"]))

        with cur.copy("COPY produto_estoque (produto_id, nome, categoria, preco, estoque) FROM STDIN") as cp:
            for p in produtos:
                cp.write_row((p["id"], p["nome"], p["categoria"], p["preco"], p["estoque"]))

        with cur.copy("COPY pedido (id, cliente_id, criado_em, status, valor_total) FROM STDIN") as cp:
            for p in pedidos:
                cp.write_row((p["id"], p["cliente_id"], p["criado_em"], p["status"], p["valor_total"]))

        with cur.copy("COPY item_pedido (pedido_id, produto_id, quantidade, preco_unitario) FROM STDIN") as cp:
            for p in pedidos:
                for i in p["itens"]:
                    cp.write_row((p["id"], i["produto_id"], i["quantidade"], i["preco_unitario"]))

        with cur.copy("COPY pagamento (pedido_id, metodo, valor, parcelas, status, pago_em) FROM STDIN") as cp:
            for p in pedidos:
                pg = p["pagamento"]
                cp.write_row((p["id"], pg["metodo"], pg["valor"], pg["parcelas"], pg["status"], pg["pago_em"]))

        # Os ids de pedido vieram do dataset; ajusta a sequência do IDENTITY para
        # o próximo pedido novo (da demo) receber 3001, e não 1 (que já existe).
        cur.execute("SELECT setval(pg_get_serial_sequence('pedido', 'id'), (SELECT max(id) FROM pedido))")

        # Atualiza as estatísticas do planejador depois da carga em lote.
        cur.execute("ANALYZE")

        contagens = {}
        for tabela in ["cliente", "produto_estoque", "pedido", "item_pedido", "pagamento"]:
            cur.execute(f"SELECT count(*) FROM {tabela}")
            contagens[tabela] = cur.fetchone()[0]

    print("PostgreSQL: carga concluída")
    for tabela, n in contagens.items():
        print(f"  {tabela:<16} {n:>6} linhas")
    print(f"  tempo: {time.time() - inicio:.1f} s")
    return contagens


if __name__ == "__main__":
    carregar()
