"""
Demonstração do Cassandra (R6): eventos de navegação e histórico do usuário.

    docker compose run --rm app python bancos/cassandra/demo.py

Operações:
  1. Inserir eventos de navegação de um usuário (visualização, clique, busca)
  2. Histórico completo do usuário, do mais recente para o mais antigo
     (1 leitura em meses_por_usuario + 1 leitura por mês)
  3. Faixa de tempo dentro da partição: eventos de um dia específico
  4. Por que consultar sem a partition key não é o padrão (ALLOW FILTERING)

Retorno gravado em saidas/cassandra.txt.
"""

import time
import uuid
from datetime import datetime, timedelta, timezone

from cassandra import InvalidRequest

from scripts.comum import Saida, conectar_cassandra, env

CLIENTE_DEMO = 159
FUSO = timezone(timedelta(hours=-3))


def local(dt):
    """O driver devolve timestamp em UTC sem fuso; converte para o horário de Brasília."""
    return dt.replace(tzinfo=timezone.utc).astimezone(FUSO).strftime("%d/%m/%Y %H:%M:%S")


def main():
    sessao = conectar_cassandra(env("CASSANDRA_KEYSPACE", "marketplace"))
    sessao.default_timeout = 120

    sel_mes = sessao.prepare(
        "SELECT ocorrido_em, tipo, produto_id, termo, dispositivo FROM eventos_por_usuario "
        "WHERE cliente_id = ? AND mes = ?"
    )
    cab = ["ocorrido_em", "tipo", "produto_id", "termo", "dispositivo"]

    def linha(r):
        return (local(r.ocorrido_em), r.tipo, r.produto_id, r.termo, r.dispositivo)

    with Saida("cassandra") as s:
        s.nota("""
            Cassandra atende o R6: escrita massiva e distribuída. A tabela foi
            modelada a partir da consulta "histórico do usuário":
            PRIMARY KEY ((cliente_id, mes), ocorrido_em DESC, evento_id).
        """)

        # ------------------------------------------------------------------ 1
        agora = datetime.now(FUSO).replace(microsecond=0)
        mes_atual = agora.strftime("%Y-%m")
        novos = [
            (agora - timedelta(minutes=2), "busca", None, "notebook gamer", "web"),
            (agora - timedelta(minutes=1), "visualizacao", 383, None, "web"),
            (agora, "clique", 383, None, "web"),
        ]
        s.operacao("R6", f"Inserir 3 eventos de navegação do cliente {CLIENTE_DEMO} (mês {mes_atual})", f"""
INSERT INTO eventos_por_usuario (cliente_id, mes, ocorrido_em, evento_id, tipo, produto_id, termo, dispositivo)
VALUES ({CLIENTE_DEMO}, '{mes_atual}', <agora-2min>, uuid(), 'busca', null, 'notebook gamer', 'web');
INSERT ... VALUES ({CLIENTE_DEMO}, '{mes_atual}', <agora-1min>, uuid(), 'visualizacao', 383, null, 'web');
INSERT ... VALUES ({CLIENTE_DEMO}, '{mes_atual}', <agora>,      uuid(), 'clique',       383, null, 'web');
INSERT INTO meses_por_usuario (cliente_id, mes) VALUES ({CLIENTE_DEMO}, '{mes_atual}');

SELECT ocorrido_em, tipo, produto_id, termo, dispositivo FROM eventos_por_usuario
 WHERE cliente_id = {CLIENTE_DEMO} AND mes = '{mes_atual}';""")
        # Apaga a partição do mês atual antes, para a demo poder ser repetida.
        sessao.execute("DELETE FROM eventos_por_usuario WHERE cliente_id = %s AND mes = %s",
                       (CLIENTE_DEMO, mes_atual))
        ins = sessao.prepare(
            "INSERT INTO eventos_por_usuario (cliente_id, mes, ocorrido_em, evento_id, tipo, produto_id, termo, dispositivo) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)"
        )
        for quando, tipo, produto, termo, disp in novos:
            sessao.execute(ins, (CLIENTE_DEMO, mes_atual, quando, uuid.uuid4(), tipo, produto, termo, disp))
        # Um mês novo para o usuário: registra também na tabela de meses (idempotente:
        # no Cassandra, INSERT com a mesma chave só sobrescreve).
        sessao.execute("INSERT INTO meses_por_usuario (cliente_id, mes) VALUES (%s, %s)", (CLIENTE_DEMO, mes_atual))
        s.tabela(cab, [linha(r) for r in sessao.execute(sel_mes, (CLIENTE_DEMO, mes_atual))])
        s.nota("""
            Foram inseridos em ordem cronológica e voltaram do mais recente para o mais
            antigo: a ordem vem do CLUSTERING ORDER BY (ocorrido_em DESC), não da consulta.
            Gravação no Cassandra = commit log + memtable, sem ler antes de escrever:
            por isso aguenta centenas de milhares de eventos por hora.
        """)

        # ------------------------------------------------------------------ 2
        s.operacao("R6", f"Histórico completo do cliente {CLIENTE_DEMO}, do mais recente ao mais antigo", f"""
-- 1) em quais meses o usuário tem eventos (1 partição)
SELECT mes FROM meses_por_usuario WHERE cliente_id = {CLIENTE_DEMO};
-- 2) para cada mês, em ordem decrescente (1 partição por mês)
SELECT ocorrido_em, tipo, produto_id, termo, dispositivo FROM eventos_por_usuario
 WHERE cliente_id = {CLIENTE_DEMO} AND mes = ?;""")
        t = time.perf_counter()
        meses = [r.mes for r in sessao.execute(
            "SELECT mes FROM meses_por_usuario WHERE cliente_id = %s", (CLIENTE_DEMO,))]
        historico, por_mes = [], []
        for mes in meses:
            linhas_mes = list(sessao.execute(sel_mes, (CLIENTE_DEMO, mes)))
            por_mes.append((mes, len(linhas_mes)))
            historico.extend(linhas_mes)
        ms = (time.perf_counter() - t) * 1000
        s.retorno(meses, "Meses (já em ordem decrescente)")
        s.tabela(["mes", "eventos"], por_mes, "Eventos por mês")
        ordenado = all(a.ocorrido_em >= b.ocorrido_em for a, b in zip(historico, historico[1:]))
        s.retorno(f"{len(historico)} eventos em {len(meses)} leituras de partição + 1, {ms:.0f} ms; "
                  f"ordem decrescente conferida: {ordenado}", "Resumo")
        s.tabela(cab, [linha(r) for r in historico[:8]], "8 mais recentes")
        s.tabela(cab, [linha(r) for r in historico[-3:]], "3 mais antigos")

        # ------------------------------------------------------------------ 3
        ultimo = next(r for r in historico if r.ocorrido_em.strftime("%Y-%m") != mes_atual)
        dia = ultimo.ocorrido_em.replace(tzinfo=timezone.utc).astimezone(FUSO)
        inicio_dia = dia.replace(hour=0, minute=0, second=0, microsecond=0)
        fim_dia = inicio_dia + timedelta(days=1)
        mes_dia = inicio_dia.strftime("%Y-%m")
        s.operacao("R6", f"Faixa de tempo dentro da partição: eventos do cliente {CLIENTE_DEMO} "
                         f"em {inicio_dia:%d/%m/%Y}", f"""
SELECT ocorrido_em, tipo, produto_id, termo, dispositivo FROM eventos_por_usuario
 WHERE cliente_id = {CLIENTE_DEMO} AND mes = '{mes_dia}'
   AND ocorrido_em >= '{inicio_dia:%Y-%m-%d} 00:00:00-0300'
   AND ocorrido_em <  '{fim_dia:%Y-%m-%d} 00:00:00-0300';""")
        dia_linhas = sessao.execute(
            "SELECT ocorrido_em, tipo, produto_id, termo, dispositivo FROM eventos_por_usuario "
            "WHERE cliente_id = %s AND mes = %s AND ocorrido_em >= %s AND ocorrido_em < %s",
            (CLIENTE_DEMO, mes_dia, inicio_dia, fim_dia),
        )
        s.tabela(cab, [linha(r) for r in dia_linhas])
        s.nota("""
            Filtro por faixa na coluna de clusterização é eficiente: dentro da
            partição as linhas estão ordenadas por data, então o Cassandra lê só o
            trecho contínuo daquele dia.
        """)

        # ------------------------------------------------------------------ 4
        s.operacao("R6", "Consulta SEM a partition key: todos os eventos de busca, de qualquer usuário", """
SELECT cliente_id, ocorrido_em, termo FROM eventos_por_usuario WHERE tipo = 'busca';
SELECT count(*) FROM eventos_por_usuario WHERE tipo = 'busca' ALLOW FILTERING;""")
        try:
            sessao.execute("SELECT cliente_id, ocorrido_em, termo FROM eventos_por_usuario WHERE tipo = 'busca'")
            s.retorno("(inesperado) a consulta foi aceita")
        except InvalidRequest as erro:
            msg = str(erro).split('message="')[-1].rstrip('"}')
            s.retorno(f"InvalidRequest: {msg}", "Sem ALLOW FILTERING")

        t = time.perf_counter()
        total_buscas = sessao.execute(
            "SELECT count(*) FROM eventos_por_usuario WHERE tipo = 'busca' ALLOW FILTERING").one()[0]
        ms_filtro = (time.perf_counter() - t) * 1000
        t = time.perf_counter()
        n_part = len(list(sessao.execute(sel_mes, (CLIENTE_DEMO, meses[-1]))))
        ms_part = (time.perf_counter() - t) * 1000
        s.tabela(
            ["consulta", "linhas", "tempo"],
            [("com ALLOW FILTERING (varre todas as partições)", f"{total_buscas} buscas", f"{ms_filtro:.0f} ms"),
             (f"pela partition key ({CLIENTE_DEMO}, '{meses[-1]}')", f"{n_part} eventos", f"{ms_part:.0f} ms")],
            "Comparação",
        )
        s.nota("""
            Sem a chave de partição o Cassandra não sabe em qual nó estão os dados:
            ele recusa a consulta, e com ALLOW FILTERING passa a ler TODAS as
            partições de TODOS os nós e filtrar depois. Com 100 mil linhas num nó só
            ainda responde; com bilhões de eventos num cluster, derrubaria o desempenho.
            O padrão do Cassandra é outro: criar uma tabela nova modelada para essa
            pergunta, por exemplo
              buscas_por_termo ((termo, mes), ocorrido_em DESC, evento_id)
            e gravar o evento nas duas tabelas (desnormalização).
        """)

    sessao.cluster.shutdown()


if __name__ == "__main__":
    main()
