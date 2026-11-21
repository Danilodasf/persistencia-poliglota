"""
Carga do Redis: sessões (R3), carrinhos (R4), ranking de visualizações (R5) e
projeção de produtos por marca (R8).

    docker compose run --rm app python bancos/redis/carga.py

Chaves criadas (o Redis é chave-valor: a "modelagem" é escolher a estrutura
de cada chave conforme a operação que ela precisa suportar):

  sessao:{token}           HASH        cliente_id, nome, dispositivo, ip, login_em, ultimo_acesso
                                       + EXPIRE 1800 -> some sozinha após 30 min sem acesso (R3)
  carrinho:{cliente_id}    HASH        produto_id -> quantidade (HINCRBY/HDEL atômicos) (R4)
  ranking:visualizacoes    SORTED SET  membro = produto_id, score = nº de visualizações (R5)
  marca:{slug}             SORTED SET  membro = produto_id, score = posição alfabética do nome (R8)
  produto_resumo:{id}      HASH        nome, preco, categoria, marca: só o que a tela mostra (R8)
  marcas                   HASH        slug -> nome da marca (menu da tela de marcas) (R8)
"""

import time
from collections import Counter
from datetime import datetime

from scripts.comum import conectar_redis, ler_dataset

TTL_SESSAO = 1800  # 30 minutos, em segundos


def carregar():
    inicio = time.time()
    clientes = {c["id"]: c for c in ler_dataset("clientes")}
    produtos = ler_dataset("produtos")
    marcas = ler_dataset("marcas")
    sessoes = ler_dataset("sessoes")
    carrinhos = ler_dataset("carrinhos")
    eventos = ler_dataset("eventos")

    r = conectar_redis()
    # Este Redis é exclusivo do projeto: FLUSHDB zera tudo e a carga pode ser repetida.
    r.flushdb()

    # Pipeline: junta milhares de comandos e envia de uma vez (sem esperar a
    # resposta de cada um). transaction=False porque aqui não precisamos de MULTI/EXEC.
    p = r.pipeline(transaction=False)

    # --- R3: sessões com TTL --------------------------------------------------
    # O horário de login é o da carga; o TTL começa a contar agora.
    agora = datetime.now().isoformat(timespec="seconds")
    for s in sessoes:
        chave = f"sessao:{s['token']}"
        p.hset(chave, mapping={
            "cliente_id": s["cliente_id"],
            "nome": clientes[s["cliente_id"]]["nome"],
            "dispositivo": s["dispositivo"],
            "ip": s["ip"],
            "login_em": agora,
            "ultimo_acesso": agora,
        })
        p.expire(chave, TTL_SESSAO)

    # --- R4: carrinhos --------------------------------------------------------
    for c in carrinhos:
        p.hset(f"carrinho:{c['cliente_id']}", mapping=c["itens"])

    # --- R5: ranking derivado dos eventos de visualização (R6) ----------------
    # Na aplicação real cada visualização faz um ZINCRBY. Na carga já temos o
    # total por produto, então gravamos a contagem pronta com ZADD (mesmo resultado).
    visualizacoes = Counter(e["produto_id"] for e in eventos if e["tipo"] == "visualizacao")
    p.zadd("ranking:visualizacoes", {str(pid): n for pid, n in visualizacoes.items()})

    # --- R8: projeção por marca ----------------------------------------------
    p.hset("marcas", mapping={m["slug"]: m["nome"] for m in marcas})
    for m in marcas:
        da_marca = sorted((x for x in produtos if x["marca_slug"] == m["slug"]), key=lambda x: x["nome"])
        # score = posição na ordem alfabética: ZRANGE já devolve ordenado por nome
        p.zadd(f"marca:{m['slug']}", {str(x["id"]): pos for pos, x in enumerate(da_marca)})
    for x in produtos:
        p.hset(f"produto_resumo:{x['id']}", mapping={
            "nome": x["nome"],
            "preco": f"{x['preco']:.2f}",  # Redis guarda texto: já formatado para exibir
            "categoria": x["categoria"],
            "marca": x["marca"],
        })

    p.execute()

    # Conferência: conta as chaves por prefixo (SCAN percorre sem travar o servidor).
    por_tipo = Counter(chave.split(":")[0] for chave in r.scan_iter(count=1000))
    print("Redis: carga concluída")
    for prefixo, n in sorted(por_tipo.items()):
        print(f"  {prefixo:<22} {n:>6} chaves")
    print(f"  ranking:visualizacoes  {r.zcard('ranking:visualizacoes'):>6} produtos, "
          f"{sum(visualizacoes.values())} visualizações")
    print(f"  total (DBSIZE)         {r.dbsize():>6} chaves")
    print(f"  tempo: {time.time() - inicio:.1f} s")
    return dict(por_tipo)


if __name__ == "__main__":
    carregar()
