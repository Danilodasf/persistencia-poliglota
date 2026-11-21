"""
Demonstração do PostgreSQL (R1): transação ACID de pedido + baixa de estoque.

    docker compose run --rm app python bancos/postgres/demo.py

Operações:
  1. Pedido válido: estoque antes -> transação -> estoque depois (COMMIT)
  2. Pedido com estoque insuficiente: o erro acontece no meio da transação,
     depois de já ter gravado o pedido e baixado o estoque de outro item;
     o ROLLBACK desfaz tudo
  3. Pedidos de um cliente com itens e pagamento (JOIN de 4 tabelas)
  4. Garantia extra: o CHECK (estoque >= 0) recusa estoque negativo mesmo
     fora da transação da aplicação

Retorno gravado em saidas/postgres.txt.
"""

import psycopg

from scripts.comum import Saida, conectar_postgres


class EstoqueInsuficiente(Exception):
    pass


# Texto mostrado na saída: é exatamente o que registrar_pedido() executa.
SQL_TRANSACAO = """
BEGIN;
  -- trava as linhas de estoque dos produtos do pedido (em ordem de id, para
  -- dois pedidos concorrentes nunca travarem em ordens diferentes = deadlock)
  SELECT produto_id, preco, estoque FROM produto_estoque
   WHERE produto_id = ANY(:ids) ORDER BY produto_id FOR UPDATE;
  INSERT INTO pedido (cliente_id, status, valor_total) VALUES (:cliente, 'pago', :total) RETURNING id;
  -- para cada item: confere o saldo; se faltar -> erro -> ROLLBACK
  INSERT INTO item_pedido (pedido_id, produto_id, quantidade, preco_unitario) VALUES (...);
  UPDATE produto_estoque SET estoque = estoque - :qtd WHERE produto_id = :id;
  INSERT INTO pagamento (pedido_id, metodo, valor, status, pago_em) VALUES (..., 'aprovado', now());
COMMIT;   -- ou ROLLBACK, se qualquer passo falhar
"""


def registrar_pedido(con, cliente_id, itens, metodo, passos):
    """
    Registra um pedido numa única transação. `itens` é uma lista de
    (produto_id, quantidade). Cada passo executado é anotado em `passos`,
    para a saída mostrar até onde a transação chegou.
    """
    # con.transaction() emite BEGIN; ao sair do bloco emite COMMIT, ou ROLLBACK
    # se alguma exceção escapar de dentro dele.
    with con.transaction(), con.cursor() as cur:
        passos.append("BEGIN")
        ids = sorted(p for p, _ in itens)
        cur.execute(
            "SELECT produto_id, preco, estoque FROM produto_estoque "
            "WHERE produto_id = ANY(%s) ORDER BY produto_id FOR UPDATE",
            (ids,),
        )
        info = {pid: (preco, estoque) for pid, preco, estoque in cur.fetchall()}
        passos.append("SELECT ... FOR UPDATE -> linhas travadas, estoque atual: "
                      + ", ".join(f"produto {pid}={info[pid][1]}" for pid in ids))

        total = sum(info[pid][0] * qtd for pid, qtd in itens)
        cur.execute(
            "INSERT INTO pedido (cliente_id, status, valor_total) VALUES (%s, 'pago', %s) RETURNING id",
            (cliente_id, total),
        )
        pedido_id = cur.fetchone()[0]
        passos.append(f"INSERT pedido -> id {pedido_id}, valor_total {total}")

        for pid, qtd in itens:
            preco, estoque = info[pid]
            if estoque < qtd:
                passos.append(f"produto {pid}: pedido {qtd}, disponível {estoque} -> ERRO (estoque insuficiente)")
                raise EstoqueInsuficiente(f"produto {pid}: pedido {qtd}, disponível {estoque}")
            cur.execute(
                "INSERT INTO item_pedido (pedido_id, produto_id, quantidade, preco_unitario) "
                "VALUES (%s, %s, %s, %s)",
                (pedido_id, pid, qtd, preco),
            )
            cur.execute(
                "UPDATE produto_estoque SET estoque = estoque - %s, atualizado_em = now() "
                "WHERE produto_id = %s",
                (qtd, pid),
            )
            passos.append(f"INSERT item (produto {pid} x{qtd}) + UPDATE estoque {estoque} -> {estoque - qtd}")

        cur.execute(
            "INSERT INTO pagamento (pedido_id, metodo, valor, status, pago_em) "
            "VALUES (%s, %s, %s, 'aprovado', now())",
            (pedido_id, metodo, total),
        )
        passos.append(f"INSERT pagamento ({metodo}, aprovado)")
    passos.append("COMMIT")
    return pedido_id


def estoque_de(con, ids):
    return con.execute(
        "SELECT produto_id, nome, estoque FROM produto_estoque WHERE produto_id = ANY(%s) ORDER BY produto_id",
        (list(ids),),
    ).fetchall()


def main():
    # autocommit=True: cada comando solto é confirmado na hora; as transações
    # de várias etapas são abertas explicitamente com con.transaction().
    con = conectar_postgres(autocommit=True)

    # --- escolha dos dados da demo (consultas determinísticas) ---------------
    cliente_id, cliente_nome, qtd_pedidos = con.execute(
        "SELECT c.id, c.nome, count(*) FROM cliente c JOIN pedido p ON p.cliente_id = c.id "
        "GROUP BY c.id ORDER BY count(*) DESC, c.id LIMIT 1"
    ).fetchone()
    notebook, celular = [r[0] for r in con.execute(
        "(SELECT produto_id FROM produto_estoque WHERE categoria = 'notebook' AND estoque >= 20 ORDER BY produto_id LIMIT 1) "
        "UNION ALL "
        "(SELECT produto_id FROM produto_estoque WHERE categoria = 'celular' AND estoque >= 20 ORDER BY produto_id LIMIT 1)"
    ).fetchall()]
    quase_esgotado, saldo_baixo = con.execute(
        "SELECT produto_id, estoque FROM produto_estoque WHERE estoque BETWEEN 1 AND 5 ORDER BY produto_id LIMIT 1"
    ).fetchone()

    with Saida("postgres") as s:
        s.nota("""
            PostgreSQL atende o R1: pedido + itens + pagamento + baixa de estoque
            numa única transação ACID ("ou tudo acontece ou nada acontece").
        """)

        # ------------------------------------------------------------------ 1
        s.operacao("R1", f"Pedido válido do cliente {cliente_id} ({cliente_nome}): "
                         f"1x produto {notebook} + 2x produto {celular}", SQL_TRANSACAO)
        cab = ["produto_id", "nome", "estoque"]
        s.tabela(cab, estoque_de(con, [notebook, celular]), "Estoque ANTES")
        passos = []
        pedido_id = registrar_pedido(con, cliente_id, [(notebook, 1), (celular, 2)], "pix", passos)
        s.retorno("\n".join(passos), "Passos executados")
        s.tabela(cab, estoque_de(con, [notebook, celular]), "Estoque DEPOIS")
        s.tabela(
            ["pedido", "produto_id", "quantidade", "preco_unitario", "pagamento", "status_pagto"],
            con.execute(
                "SELECT p.id, i.produto_id, i.quantidade, i.preco_unitario, pg.metodo, pg.status "
                "FROM pedido p JOIN item_pedido i ON i.pedido_id = p.id JOIN pagamento pg ON pg.pedido_id = p.id "
                "WHERE p.id = %s ORDER BY i.produto_id", (pedido_id,)
            ).fetchall(),
            "Pedido gravado",
        )

        # ------------------------------------------------------------------ 2
        pedido_ruim = [(notebook, 1), (quase_esgotado, saldo_baixo + 1)]
        s.operacao("R1", f"Pedido com estoque insuficiente: 1x produto {notebook} (tem saldo) + "
                         f"{saldo_baixo + 1}x produto {quase_esgotado} (só há {saldo_baixo})", SQL_TRANSACAO)
        s.nota("""
            O item com saldo é processado PRIMEIRO: quando o erro acontece, o pedido
            já foi inserido e o estoque do notebook já foi baixado dentro da transação.
            O ROLLBACK precisa desfazer essas escritas.
        """)
        contar = "SELECT count(*) AS pedidos, max(id) AS ultimo_id FROM pedido"
        s.tabela(cab, estoque_de(con, [notebook, quase_esgotado]), "Estoque ANTES")
        s.tabela(["pedidos", "ultimo_id"], [con.execute(contar).fetchone()], "Pedidos ANTES")
        passos = []
        try:
            registrar_pedido(con, cliente_id, pedido_ruim, "cartao_credito", passos)
        except EstoqueInsuficiente as erro:
            passos.append(f"ROLLBACK  (motivo: {erro})")
        s.retorno("\n".join(passos), "Passos executados")
        s.tabela(cab, estoque_de(con, [notebook, quase_esgotado]), "Estoque DEPOIS (igual ao ANTES)")
        s.tabela(["pedidos", "ultimo_id"], [con.execute(contar).fetchone()], "Pedidos DEPOIS (igual ao ANTES)")
        s.nota("""
            Nada mudou: nem o pedido, nem o item, nem a baixa do notebook.
            Detalhe: o id que o pedido desfeito recebeu é "perdido" (o próximo pula
            um número), porque sequências não voltam atrás no ROLLBACK. Isso é
            proposital no PostgreSQL, para não serializar todas as transações.
        """)

        # ------------------------------------------------------------------ 3
        sql_join = """
SELECT p.id, p.criado_em, p.status, p.valor_total,
       pg.metodo, pg.parcelas, pg.status AS pagamento,
       string_agg(i.quantidade || 'x ' || pe.nome, '; ' ORDER BY pe.nome) AS itens
  FROM pedido p
  JOIN item_pedido     i  ON i.pedido_id   = p.id
  JOIN produto_estoque pe ON pe.produto_id = i.produto_id
  JOIN pagamento       pg ON pg.pedido_id  = p.id
 WHERE p.cliente_id = %s
 GROUP BY p.id, pg.id
 ORDER BY p.criado_em DESC
 LIMIT 5;"""
        s.operacao("R1", f"Últimos 5 pedidos do cliente {cliente_id} ({cliente_nome}, "
                         f"{qtd_pedidos} pedidos no histórico) com itens e pagamento",
                   sql_join.replace("%s", str(cliente_id)))
        linhas = [
            (pid, criado.strftime("%d/%m/%Y %H:%M"), st, total, met, parc, pagto, itens)
            for pid, criado, st, total, met, parc, pagto, itens in con.execute(sql_join, (cliente_id,)).fetchall()
        ]
        s.tabela(["pedido", "criado_em", "status", "total", "metodo", "parc", "pagto", "itens"], linhas)
        s.nota(f"O pedido {pedido_id}, criado na operação 1, aparece no topo.")

        # ------------------------------------------------------------------ 4
        sql_check = f"UPDATE produto_estoque SET estoque = estoque - 1000 WHERE produto_id = {quase_esgotado};"
        s.operacao("R1", "Garantia extra: tentar deixar o estoque negativo direto no banco", sql_check)
        try:
            con.execute(sql_check)
            s.retorno("(inesperado) o UPDATE foi aceito")
        except psycopg.errors.CheckViolation as erro:
            s.retorno(f"ERRO {erro.sqlstate} (check_violation): {erro.diag.message_primary}")
        s.tabela(cab, estoque_de(con, [quase_esgotado]), "Estoque continua")
        s.nota("""
            Mesmo que um bug na aplicação esqueça de conferir o saldo, o CHECK
            (estoque >= 0) no schema impede a venda sem estoque.
        """)

    con.close()


if __name__ == "__main__":
    main()
