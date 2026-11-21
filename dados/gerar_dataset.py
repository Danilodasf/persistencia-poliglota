"""
Gera o dataset único do marketplace em dados/dataset/*.json.

Todos os bancos são carregados a partir destes arquivos, e por isso os IDs
(cliente_id, produto_id, pedido_id) são os mesmos em todos eles. A seed é
fixa: rodar de novo produz exatamente os mesmos dados.

    docker compose run --rm --no-deps app python dados/gerar_dataset.py

Arquivos gerados e quem os usa:
    marcas.json     20 marcas                       -> MongoDB, Redis (R8)
    produtos.json   500 produtos, 5 categorias      -> MongoDB (R2), PostgreSQL (estoque), Redis (R8), Neo4j
    clientes.json   1.000 clientes                  -> PostgreSQL, Neo4j
    pedidos.json    3.000 pedidos + itens + pagto   -> PostgreSQL (R1), Neo4j (COMPROU, R7)
    eventos.json    100.000 eventos de navegação    -> Cassandra (R6), Redis (ranking, R5)
    sessoes.json    300 sessões ativas              -> Redis (R3)
    carrinhos.json  200 carrinhos                   -> Redis (R4)

Afinidade proposital nos pedidos (para as recomendações do Neo4j fazerem sentido):
  - cada cliente tem categorias e marcas preferidas;
  - depois do primeiro item, o próximo tende a ser da MESMA MARCA (inclusive de
    outra categoria: quem compra notebook Nexa leva celular Nexa; quem compra
    camiseta Trilha leva tênis Trilha; quem compra livro de uma editora leva
    outro da mesma editora);
  - alguns produtos são muito mais populares que outros (cauda longa).
"""

import json
import random
import unicodedata
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from faker import Faker

SEED = 42
random.seed(SEED)
Faker.seed(SEED)
fake = Faker("pt_BR")

PASTA = Path(__file__).resolve().parent / "dataset"

QTD_PRODUTOS_POR_CATEGORIA = 100   # 5 categorias x 100 = 500 produtos
QTD_CLIENTES = 1_000
QTD_PEDIDOS = 3_000
QTD_EVENTOS = 100_000
QTD_SESSOES = 300
QTD_CARRINHOS = 200

# Período dos dados: 3 meses (ago, set e out/2026), em horário de Brasília.
FUSO = timezone(timedelta(hours=-3))
INICIO = datetime(2026, 8, 1, tzinfo=FUSO)
FIM = datetime(2026, 11, 1, tzinfo=FUSO)


# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------

def slug(texto):
    """'Editora Aurora' -> 'editora-aurora' (sem acento, para usar em chaves do Redis)."""
    sem_acento = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    return "-".join(sem_acento.lower().split())


def data_aleatoria(inicio=INICIO, fim=FIM):
    segundos = random.randint(0, int((fim - inicio).total_seconds()) - 1)
    return inicio + timedelta(seconds=segundos)


def iso(dt):
    return dt.isoformat(timespec="seconds")


def uuid_seed():
    """UUID v4 derivado do random com seed (uuid.uuid4() não seria reproduzível)."""
    return str(uuid.UUID(int=random.getrandbits(128), version=4))


def isbn13():
    """ISBN-13 com prefixo brasileiro (978-65) e dígito verificador válido."""
    corpo = "97865" + "".join(str(random.randint(0, 9)) for _ in range(7))
    soma = sum(int(d) * (1 if i % 2 == 0 else 3) for i, d in enumerate(corpo))
    return corpo + str((10 - soma % 10) % 10)


def escolher_ponderado(itens, pesos):
    return random.choices(itens, weights=pesos, k=1)[0]


def salvar(nome, dados, compacto=False):
    caminho = PASTA / f"{nome}.json"
    with caminho.open("w", encoding="utf-8") as f:
        if compacto:  # eventos: 100 mil linhas, sem indentação para o arquivo ficar menor
            json.dump(dados, f, ensure_ascii=False, separators=(",", ":"))
        else:
            json.dump(dados, f, ensure_ascii=False, indent=1)
    return caminho


# ---------------------------------------------------------------------------
# Marcas (20) e categorias (5)
# ---------------------------------------------------------------------------
# Marcas fictícias. Várias vendem duas categorias; é isso que permite a
# afinidade "mesma marca, outra categoria" nos pedidos.
MARCAS_BASE = [
    # tecnologia: celular + notebook
    ("Nexa", ["celular", "notebook"]),
    ("Vortex", ["celular", "notebook"]),
    ("Lumio", ["celular", "notebook"]),
    ("Orbita", ["celular", "notebook"]),
    ("Kairo", ["celular"]),
    ("Zenit", ["notebook"]),
    # editoras: livro
    ("Editora Aurora", ["livro"]),
    ("Editora Sextante Azul", ["livro"]),
    ("Editora Pindorama", ["livro"]),
    ("Editora Ipê", ["livro"]),
    # moda: camiseta + tênis
    ("Trilha", ["camiseta", "tenis"]),
    ("Brisa", ["camiseta", "tenis"]),
    ("Pulso", ["camiseta", "tenis"]),
    ("Raiz", ["camiseta", "tenis"]),
    ("Maré", ["camiseta"]),
    ("Cacto", ["camiseta"]),
    ("Atlas", ["tenis"]),
    ("Passo Firme", ["tenis"]),
    ("Corre Já", ["tenis"]),
    ("Urbe", ["camiseta", "tenis"]),
]

marcas = [
    {"id": i, "nome": nome, "slug": slug(nome), "categorias": cats}
    for i, (nome, cats) in enumerate(MARCAS_BASE, start=1)
]

CATEGORIAS = ["celular", "livro", "camiseta", "notebook", "tenis"]

CORES = ["preto", "branco", "azul", "vermelho", "verde", "cinza", "amarelo", "rosa"]
FAIXA_PRECO = {
    "celular": (899, 7999),
    "livro": (29, 149),
    "camiseta": (39, 199),
    "notebook": (2499, 12999),
    "tenis": (149, 899),
}


# ---------------------------------------------------------------------------
# Produtos (500): campos comuns + "atributos" que muda por categoria (R2)
# ---------------------------------------------------------------------------

# O fake.sentence() do Faker pt_BR gera lorem ipsum em latim; montamos títulos em português.
_SUBST = ["O Segredo", "A Casa", "O Caminho", "A Última Carta", "O Silêncio", "A Ilha",
          "O Guardião", "A Memória", "O Rio", "A Cidade", "O Jardim", "A Noite", "O Mapa",
          "A Herança", "O Inverno", "A Promessa"]
# complementos neutros em gênero, para combinar com "O ..." e "A ..."
_COMPL = ["do Sertão", "das Águas", "da Serra", "de Vidro", "do Tempo", "sem Nome",
          "dos Ventos", "do Mar", "do Norte", "de Papel", "de Outono", "das Estrelas"]
_TECNICO = ["Python", "Banco de Dados", "Redes", "Estatística", "Algoritmos", "Engenharia de Software",
            "Arquitetura de Sistemas", "Finanças Pessoais", "Liderança", "Marketing Digital"]


def titulo_livro():
    if random.random() < 0.25:
        return random.choice(["Introdução a", "Guia Prático de", "Fundamentos de", "Dominando"]) + \
            " " + random.choice(_TECNICO)
    return f"{random.choice(_SUBST)} {random.choice(_COMPL)}"


def atributos_e_nome(categoria, marca):
    """Cada categoria tem um conjunto de atributos completamente diferente."""
    if categoria == "celular":
        a = {
            "memoria_gb": random.choice([64, 128, 256, 512]),
            "ram_gb": random.choice([4, 6, 8, 12]),
            "tela_polegadas": round(random.uniform(6.1, 6.9), 1),
            "cor": random.choice(CORES[:6]),
            "dual_chip": random.random() < 0.7,
            "camera_mp": random.choice([12, 48, 50, 64, 108]),
        }
        modelo = random.choice(["X", "Pro", "Lite", "Max", "Neo"]) + str(random.randint(5, 20))
        nome = f"Celular {marca['nome']} {modelo} {a['memoria_gb']}GB"
    elif categoria == "notebook":
        a = {
            "processador": random.choice(["Core i3 13a ger.", "Core i5 13a ger.", "Core i7 13a ger.",
                                          "Ryzen 5 7530U", "Ryzen 7 7730U"]),
            "ram_gb": random.choice([8, 16, 32]),
            "armazenamento_gb": random.choice([256, 512, 1024]),
            "tela_polegadas": random.choice([13.3, 14.0, 15.6, 16.0]),
            "placa_video": random.choice(["integrada", "integrada", "RTX 3050", "RTX 4060"]),
            "peso_kg": round(random.uniform(1.1, 2.4), 2),
        }
        linha = random.choice(["Air", "Book", "Studio", "Gamer", "Slim"]) + " " + str(random.randint(3, 9))
        nome = f"Notebook {marca['nome']} {linha} {a['tela_polegadas']}\""
    elif categoria == "livro":
        titulo = titulo_livro()
        a = {
            "isbn": isbn13(),
            "paginas": random.randint(80, 900),
            "autor": fake.name(),
            "editora": marca["nome"],
            "genero": random.choice(["romance", "fantasia", "biografia", "tecnico",
                                     "autoajuda", "suspense", "historia"]),
            "idioma": random.choice(["portugues"] * 4 + ["ingles"]),
            "ano_publicacao": random.randint(1995, 2026),
        }
        nome = titulo
    elif categoria == "camiseta":
        a = {
            "tamanho": random.choice(["P", "M", "G", "GG"]),
            "cor": random.choice(CORES),
            "material": random.choice(["algodao", "algodao", "poliester", "dry-fit", "linho"]),
            "genero": random.choice(["masculino", "feminino", "unissex"]),
            "manga": random.choice(["curta", "curta", "longa", "regata"]),
        }
        estilo = random.choice(["Basica", "Estampada", "Oversized", "Polo", "Esportiva"])
        nome = f"Camiseta {marca['nome']} {estilo} {a['cor']} {a['tamanho']}"
    else:  # tenis
        a = {
            "numero": random.randint(34, 45),
            "cor": random.choice(CORES),
            "tipo": random.choice(["corrida", "casual", "skate", "treino", "caminhada"]),
            "material": random.choice(["tecido", "couro", "sintetico", "knit"]),
            "genero": random.choice(["masculino", "feminino", "unissex"]),
        }
        modelo = random.choice(["Run", "Street", "Flow", "Classic", "Air"]) + " " + str(random.randint(1, 9))
        nome = f"Tenis {marca['nome']} {modelo} {a['tipo']} n{a['numero']}"
    return a, nome


def estoque_inicial():
    """Maioria com estoque folgado; alguns quase esgotados ou esgotados (útil na demo do R1)."""
    r = random.random()
    if r < 0.03:
        return 0
    if r < 0.08:
        return random.randint(1, 5)
    return random.randint(10, 300)


produtos = []
for categoria in CATEGORIAS:
    marcas_da_categoria = [m for m in marcas if categoria in m["categorias"]]
    lo, hi = FAIXA_PRECO[categoria]
    for _ in range(QTD_PRODUTOS_POR_CATEGORIA):
        marca = random.choice(marcas_da_categoria)
        atributos, nome = atributos_e_nome(categoria, marca)
        produtos.append({
            "id": len(produtos) + 1,
            "nome": nome,
            "categoria": categoria,
            "marca": marca["nome"],
            "marca_slug": marca["slug"],
            "preco": round(random.uniform(lo, hi), 2),
            "estoque": estoque_inicial(),
            "atributos": atributos,
        })

# Popularidade (cauda longa): peso 1/(posição^0.8) numa ordem aleatória.
ordem = list(range(len(produtos)))
random.shuffle(ordem)
popularidade = {produtos[i]["id"]: 1 / (pos + 1) ** 0.8 for pos, i in enumerate(ordem)}

# Índices auxiliares para sortear produtos com filtro (listas: ordem determinística).
por_categoria = {c: [p for p in produtos if p["categoria"] == c] for c in CATEGORIAS}
por_marca = {m["slug"]: [p for p in produtos if p["marca_slug"] == m["slug"]] for m in marcas}


def sortear_produto(candidatos, excluir=()):
    candidatos = [p for p in candidatos if p["id"] not in excluir] or \
                 [p for p in produtos if p["id"] not in excluir]
    return escolher_ponderado(candidatos, [popularidade[p["id"]] for p in candidatos])


# ---------------------------------------------------------------------------
# Clientes (1.000) e o "perfil" de preferência de cada um
# ---------------------------------------------------------------------------

def email_de(nome, id_):
    partes = slug(nome).replace("-", " ").split()
    partes = [p for p in partes if p not in ("dr.", "dra.", "sr.", "sra.", "srta.", "da", "de", "do", "dos", "das")]
    return f"{partes[0]}.{partes[-1]}{id_}@exemplo.com.br"


clientes = []
perfil = {}  # usado só aqui na geração; não vai para o dataset
for i in range(1, QTD_CLIENTES + 1):
    nome = fake.name()
    clientes.append({
        "id": i,
        "nome": nome,
        "email": email_de(nome, i),
        "cpf": fake.cpf(),
        "cidade": fake.city(),
        "uf": fake.estado_sigla(),
        "criado_em": iso(data_aleatoria(datetime(2024, 1, 1, tzinfo=FUSO), INICIO)),
    })
    cats = random.sample(CATEGORIAS, k=random.choice([1, 1, 2]))
    marcas_possiveis = [m["slug"] for m in marcas if set(m["categorias"]) & set(cats)]
    perfil[i] = {
        "categorias": cats,
        "marcas": random.sample(marcas_possiveis, k=min(2, len(marcas_possiveis))),
        # atividade: poucos clientes compram/navegam muito, a maioria pouco
        "atividade": min(random.paretovariate(1.5), 15),
    }

ids_clientes = [c["id"] for c in clientes]
pesos_atividade = [perfil[i]["atividade"] for i in ids_clientes]


# ---------------------------------------------------------------------------
# Pedidos (3.000) com itens (1 a 5) e pagamento (R1 e base do R7)
# ---------------------------------------------------------------------------

def primeiro_item(p):
    if random.random() < 0.75:
        marca = random.choice(p["marcas"])
        cands = [x for x in por_marca[marca] if x["categoria"] in p["categorias"]] or por_marca[marca]
        return sortear_produto(cands)
    return sortear_produto(produtos)


def proximo_item(p, anterior, ja):
    r = random.random()
    if r < 0.55:   # mesma marca do item anterior (pode ser outra categoria)
        return sortear_produto(por_marca[anterior["marca_slug"]], ja)
    if r < 0.85:   # uma das categorias preferidas do cliente
        return sortear_produto(por_categoria[random.choice(p["categorias"])], ja)
    return sortear_produto(produtos, ja)  # compra por impulso


METODOS = ["pix", "cartao_credito", "cartao_debito", "boleto"]

pedidos = []
for pid in range(1, QTD_PEDIDOS + 1):
    cliente_id = escolher_ponderado(ids_clientes, pesos_atividade)
    p = perfil[cliente_id]
    criado_em = data_aleatoria()

    qtd_itens = escolher_ponderado([1, 2, 3, 4, 5], [30, 30, 20, 12, 8])
    escolhidos = [primeiro_item(p)]
    while len(escolhidos) < qtd_itens:
        escolhidos.append(proximo_item(p, escolhidos[-1], {x["id"] for x in escolhidos}))

    itens = [{
        "produto_id": prod["id"],
        "quantidade": escolher_ponderado([1, 2, 3], [80, 15, 5]),
        "preco_unitario": prod["preco"],  # preço congelado no momento da compra
    } for prod in escolhidos]
    valor_total = round(sum(i["quantidade"] * i["preco_unitario"] for i in itens), 2)

    metodo = escolher_ponderado(METODOS, [45, 35, 10, 10])
    aprovado = random.random() < 0.95
    pedidos.append({
        "id": pid,
        "cliente_id": cliente_id,
        "criado_em": iso(criado_em),
        # pagamento recusado => pedido cancelado (e não entra como COMPROU no Neo4j)
        "status": random.choice(["pago", "enviado", "entregue", "entregue"]) if aprovado else "cancelado",
        "valor_total": valor_total,
        "itens": itens,
        "pagamento": {
            "metodo": metodo,
            "valor": valor_total,
            "parcelas": random.choice([1, 1, 2, 3, 6, 10]) if metodo == "cartao_credito" else 1,
            "status": "aprovado" if aprovado else "recusado",
            "pago_em": iso(criado_em + timedelta(minutes=random.randint(1, 120))) if aprovado else None,
        },
    })


# ---------------------------------------------------------------------------
# Eventos de navegação (100.000) em 3 meses (R6; as visualizações alimentam o R5)
# ---------------------------------------------------------------------------
TERMOS = {
    "celular": ["celular", "smartphone 128gb", "celular barato", "celular camera boa"],
    "notebook": ["notebook", "notebook gamer", "notebook i5", "notebook leve"],
    "livro": ["livro romance", "livro fantasia", "biografia", "livro tecnico"],
    "camiseta": ["camiseta", "camiseta oversized", "camiseta algodao", "polo"],
    "tenis": ["tenis corrida", "tenis casual", "tenis branco", "tenis skate"],
}
TIPOS_EVENTO = ["visualizacao", "clique", "busca"]

eventos = []
for cliente_id in random.choices(ids_clientes, weights=pesos_atividade, k=QTD_EVENTOS):
    p = perfil[cliente_id]
    tipo = escolher_ponderado(TIPOS_EVENTO, [60, 25, 15])
    evento = {
        "evento_id": uuid_seed(),
        "cliente_id": cliente_id,
        "tipo": tipo,
        "produto_id": None,
        "termo": None,
        "dispositivo": escolher_ponderado(["web", "android", "ios"], [45, 35, 20]),
        "ocorrido_em": data_aleatoria(),
    }
    if tipo == "busca":
        cat = random.choice(p["categorias"]) if random.random() < 0.7 else random.choice(CATEGORIAS)
        termo = random.choice(TERMOS[cat])
        if random.random() < 0.3:  # às vezes busca pela marca
            termo = f"{termo} {random.choice(por_categoria[cat])['marca'].lower()}"
        evento["termo"] = termo
    else:
        cands = por_categoria[random.choice(p["categorias"])] if random.random() < 0.6 else produtos
        evento["produto_id"] = sortear_produto(cands)["id"]
    eventos.append(evento)

eventos.sort(key=lambda e: e["ocorrido_em"])
for e in eventos:
    e["ocorrido_em"] = iso(e["ocorrido_em"])


# ---------------------------------------------------------------------------
# Sessões ativas (300) e carrinhos (200) — o TTL e o "agora" são aplicados na carga
# ---------------------------------------------------------------------------
sessoes = [{
    "token": f"{random.getrandbits(128):032x}",
    "cliente_id": cid,
    "dispositivo": escolher_ponderado(["web", "android", "ios"], [45, 35, 20]),
    "ip": f"177.{random.randint(0, 255)}.{random.randint(0, 255)}.{random.randint(1, 254)}",
} for cid in sorted(random.sample(ids_clientes, QTD_SESSOES))]

carrinhos = []
for cid in sorted(random.sample(ids_clientes, QTD_CARRINHOS)):
    itens = {}
    for _ in range(random.randint(1, 6)):
        prod = primeiro_item(perfil[cid])  # o carrinho também segue o perfil do cliente
        itens[str(prod["id"])] = escolher_ponderado([1, 2, 3], [75, 20, 5])
    carrinhos.append({"cliente_id": cid, "itens": itens})


# ---------------------------------------------------------------------------
# Gravação
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    PASTA.mkdir(exist_ok=True)
    arquivos = [
        ("marcas", marcas, False),
        ("produtos", produtos, False),
        ("clientes", clientes, False),
        ("pedidos", pedidos, False),
        ("eventos", eventos, True),
        ("sessoes", sessoes, False),
        ("carrinhos", carrinhos, False),
    ]
    print(f"Gerando dataset em {PASTA} (seed {SEED})")
    for nome, dados, compacto in arquivos:
        caminho = salvar(nome, dados, compacto)
        print(f"  {nome + '.json':<15} {len(dados):>7} registros  {caminho.stat().st_size / 1024:>8.0f} KB")
    print(f"  (itens de pedido: {sum(len(p['itens']) for p in pedidos)})")
