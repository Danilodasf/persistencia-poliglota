"""
Demonstração do Redis: sessão (R3), carrinho (R4), ranking (R5) e marca (R8).

    docker compose run --rm app python bancos/redis/demo.py

Operações:
  1. Sessão: criar com TTL de 30 min, ver o TTL cair, renovar ao "acessar" e
     ver uma sessão de teste expirar sozinha (R3)
  2. Carrinho: adicionar, alterar quantidade, remover item e listar (R4)
  3. Ranking: top 10, registrar visualizações e ver o produto subir (R5)
  4. Produtos de uma marca, ordenados por nome, sem tocar no banco principal (R8)

Retorno gravado em saidas/redis.txt.
"""

import time
from datetime import datetime

from scripts.comum import Saida, conectar_redis

TOKEN_DEMO = "demo0000000000000000000000000001"
CLIENTE_DEMO = 159
MARCA_DEMO = "nexa"


def resumos(r, ids):
    """Busca nome/preço dos produtos num único pipeline (1 ida ao servidor)."""
    p = r.pipeline(transaction=False)
    for pid in ids:
        p.hgetall(f"produto_resumo:{pid}")
    return p.execute()


def tabela_ranking(r, n=10):
    top = r.zrevrange("ranking:visualizacoes", 0, n - 1, withscores=True)
    nomes = resumos(r, [pid for pid, _ in top])
    return [(i + 1, pid, int(score), info["nome"]) for i, ((pid, score), info) in enumerate(zip(top, nomes))]


def main():
    r = conectar_redis()

    with Saida("redis") as s:
        s.nota("""
            Redis atende R3, R4, R5 e R8: dados em memória, estruturas prontas
            (hash, sorted set) e TTL nativo.
        """)

        # ------------------------------------------------------------------ 1
        chave = f"sessao:{TOKEN_DEMO}"
        s.operacao("R3", "Sessão com expiração por inatividade (TTL de 30 min)", f"""
HSET {chave} cliente_id {CLIENTE_DEMO} nome "..." dispositivo web login_em ... ultimo_acesso ...
EXPIRE {chave} 1800
TTL {chave}                      -- logo após o login
(3 s sem acesso) TTL {chave}
(usuário faz uma requisição) HSET {chave} ultimo_acesso ...  +  EXPIRE {chave} 1800
TTL {chave}                      -- voltou para 1800""")
        agora = datetime.now().isoformat(timespec="seconds")
        r.hset(chave, mapping={"cliente_id": CLIENTE_DEMO, "nome": "João Felipe Cassiano",
                               "dispositivo": "web", "login_em": agora, "ultimo_acesso": agora})
        r.expire(chave, 1800)
        s.retorno(r.hgetall(chave), "HGETALL (sessão criada)")
        s.retorno(r.ttl(chave), "TTL logo após o login (s)")
        time.sleep(3)
        s.retorno(r.ttl(chave), "TTL depois de 3 s sem acesso (s)")
        # Cada requisição do usuário renova o prazo: é isso que faz a sessão
        # expirar por INATIVIDADE (30 min sem acesso) e não 30 min após o login.
        p = r.pipeline()  # MULTI/EXEC: atualiza e renova juntos
        p.hset(chave, "ultimo_acesso", datetime.now().isoformat(timespec="seconds"))
        p.expire(chave, 1800)
        p.execute()
        s.retorno(r.ttl(chave), "TTL depois do acesso (renovado, s)")

        s.nota("Agora uma sessão de teste com TTL de 2 s, para ver a expiração acontecer:")
        teste = "sessao:demo-expira"
        r.hset(teste, mapping={"cliente_id": 1})
        r.expire(teste, 2)
        s.retorno(f"EXISTS {teste} -> {r.exists(teste)}   TTL -> {r.ttl(teste)}", "Logo após criar")
        time.sleep(3)
        s.retorno(f"EXISTS {teste} -> {r.exists(teste)}   TTL -> {r.ttl(teste)}  (-2 = chave não existe)",
                  "3 s depois")
        exemplo = next(k for k in r.scan_iter(match="sessao:*", count=100) if "demo" not in k)
        s.retorno(f"{exemplo} -> TTL {r.ttl(exemplo)} s", "Uma das 300 sessões da carga")
        s.nota("""
            A chave sumiu sozinha: nenhum job de limpeza, nenhum DELETE.
            O próprio Redis remove as chaves expiradas.
        """)

        # ------------------------------------------------------------------ 2
        car = f"carrinho:{CLIENTE_DEMO}"
        s.operacao("R4", f"Carrinho do cliente {CLIENTE_DEMO}: adicionar, alterar, remover, listar", f"""
DEL {car}                        -- a demo começa com o carrinho vazio
HINCRBY {car} 1 1                -- adiciona 1x produto 1
HINCRBY {car} 301 1              -- adiciona 1x produto 301
HINCRBY {car} 205 1              -- adiciona 1x produto 205
HINCRBY {car} 1 2                -- muda a quantidade do produto 1 (1 -> 3)
HINCRBY {car} 1 -1               -- diminui 1 (3 -> 2)
HDEL {car} 301                   -- remove o produto 301
HGETALL {car}
HLEN {car}""")
        r.delete(car)
        passos = []
        passos.append(f"HINCRBY 1 1     -> {r.hincrby(car, '1', 1)}")
        passos.append(f"HINCRBY 301 1   -> {r.hincrby(car, '301', 1)}")
        passos.append(f"HINCRBY 205 1   -> {r.hincrby(car, '205', 1)}")
        passos.append(f"HINCRBY 1 2     -> {r.hincrby(car, '1', 2)}")
        passos.append(f"HINCRBY 1 -1    -> {r.hincrby(car, '1', -1)}")
        passos.append(f"HDEL 301        -> {r.hdel(car, '301')} (item removido)")
        s.retorno("\n".join(passos), "Retorno de cada comando (quantidade resultante)")
        itens = r.hgetall(car)
        s.retorno(itens, "HGETALL (produto_id -> quantidade)")
        s.retorno(r.hlen(car), "HLEN (itens distintos)")
        info = resumos(r, itens)
        s.tabela(["produto_id", "qtd", "nome", "preco"],
                 [(pid, q, i["nome"], i["preco"]) for (pid, q), i in zip(itens.items(), info)],
                 "Carrinho com os nomes (de produto_resumo:*)")
        s.nota("""
            Cada HINCRBY/HDEL é atômico e roda em memória: dois cliques simultâneos
            não perdem atualização. No checkout, este hash vira um pedido no
            PostgreSQL (R1), e lá entra a transação ACID.
        """)

        # ------------------------------------------------------------------ 3
        rank = "ranking:visualizacoes"
        # O produto que está em 11º lugar recebe visualizações até entrar no top 10.
        alvo, score_alvo = r.zrevrange(rank, 10, 10, withscores=True)[0]
        _, score_10 = r.zrevrange(rank, 9, 9, withscores=True)[0]
        novas = int(score_10 - score_alvo) + 5
        s.operacao("R5", "Ranking dos mais vistos: top 10, novas visualizações, top 10 de novo", f"""
ZREVRANGE {rank} 0 9 WITHSCORES             -- top 10
ZREVRANK {rank} {alvo}  /  ZSCORE {rank} {alvo}
ZINCRBY {rank} 1 {alvo}                     -- uma vez por visualização ({novas}x)
ZREVRANK {rank} {alvo}  /  ZSCORE {rank} {alvo}
ZREVRANGE {rank} 0 9 WITHSCORES""")
        cab = ["pos", "produto_id", "visualizacoes", "nome"]
        s.tabela(cab, tabela_ranking(r), "Top 10 ANTES")
        s.retorno(f"produto {alvo}: posição {r.zrevrank(rank, alvo) + 1}, {int(r.zscore(rank, alvo))} visualizações",
                  "Produto alvo ANTES")
        p = r.pipeline(transaction=False)
        for _ in range(novas):  # simula {novas} visualizações, cada uma um ZINCRBY
            p.zincrby(rank, 1, alvo)
        p.execute()
        s.retorno(f"produto {alvo}: posição {r.zrevrank(rank, alvo) + 1}, {int(r.zscore(rank, alvo))} visualizações",
                  f"Produto alvo DEPOIS de {novas} ZINCRBY")
        s.tabela(cab, tabela_ranking(r), "Top 10 DEPOIS")
        s.nota("""
            ZINCRBY conta e reposiciona ao mesmo tempo (O(log n)); o ZREVRANGE
            devolve o top 10 já ordenado, sem ORDER BY na hora da consulta.
        """)

        # ------------------------------------------------------------------ 4
        chave_marca = f"marca:{MARCA_DEMO}"
        s.operacao("R8", f"Produtos da marca \"{MARCA_DEMO}\" para a tela de navegação (1ª página)", f"""
HGETALL marcas                -- menu de marcas
ZCARD {chave_marca}            -- total de produtos da marca
ZRANGE {chave_marca} 0 9       -- 1ª página, já em ordem de nome
HGETALL produto_resumo:<id>   -- para cada id, num único pipeline""")
        marcas = r.hgetall("marcas")
        p = r.pipeline(transaction=False)
        for slug in sorted(marcas):
            p.zcard(f"marca:{slug}")
        s.tabela(["slug", "marca", "produtos"],
                 [(slug, marcas[slug], n) for slug, n in zip(sorted(marcas), p.execute())],
                 "Marcas")
        ids = r.zrange(chave_marca, 0, 9)
        s.retorno(f"{r.zcard(chave_marca)} produtos; 1ª página: {ids}", "ZCARD / ZRANGE")
        s.tabela(["produto_id", "nome", "categoria", "preco"],
                 [(pid, i["nome"], i["categoria"], i["preco"]) for pid, i in zip(ids, resumos(r, ids))],
                 "Página 1 (ordenada por nome)")
        s.nota("""
            Tudo sai da memória do Redis: o MongoDB (catálogo) e o PostgreSQL não
            são consultados. A projeção é remontada na carga, quando o catálogo muda.
            Página seguinte: ZRANGE marca:nexa 10 19.
        """)


if __name__ == "__main__":
    main()
