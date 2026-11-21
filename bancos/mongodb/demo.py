"""
Demonstração do MongoDB (R2): catálogo com atributos diferentes por categoria.

    docker compose run --rm app python bancos/mongodb/demo.py

Operações:
  1. Buscar um celular e um livro: mesma coleção, atributos completamente diferentes
  2. Consulta por atributo específico de uma categoria: livros com mais de 300
     páginas (com o plano de execução mostrando o índice usado)
  3. Outro atributo, outra categoria: celulares com 256 GB ou mais e tela >= 6.5"
  4. Inserir uma categoria nova ("fone") sem alterar esquema nenhum
  5. Esquema flexível, mas com regra: o validador recusa produto sem preço

Retorno gravado em saidas/mongodb.txt.
"""

from pymongo.errors import WriteError

from scripts.comum import Saida, conectar_mongo

# Produto novo da operação 3. _id 501 vem logo depois dos 500 do dataset.
FONE = {
    "_id": 501,
    "nome": "Fone Nexa Pulse ANC",
    "categoria": "fone",
    "marca": "Nexa",
    "marca_slug": "nexa",
    "preco": 499.90,
    "atributos": {
        "tipo": "bluetooth",
        "cancelamento_ruido": True,
        "bateria_horas": 30,
        "driver_mm": 40,
        "microfone": True,
    },
}


def main():
    db = conectar_mongo()
    produtos = db.produtos

    with Saida("mongodb") as s:
        s.nota("""
            MongoDB atende o R2: cada produto é um documento; os campos comuns ficam
            no topo e o subdocumento "atributos" muda conforme a categoria.
        """)

        # ------------------------------------------------------------------ 1
        s.operacao("R2", "Um celular e um livro: mesma coleção, atributos diferentes", """
db.produtos.find({ categoria: "celular" }).sort({ _id: 1 }).limit(1)
db.produtos.find({ categoria: "livro" }).sort({ _id: 1 }).limit(1)""")
        celular = produtos.find_one({"categoria": "celular"}, sort=[("_id", 1)])
        livro = produtos.find_one({"categoria": "livro"}, sort=[("_id", 1)])
        s.retorno(celular, "Celular")
        s.retorno(livro, "Livro")
        s.nota(f"""
            Campos comuns iguais (nome, categoria, marca, preco). Em "atributos", o celular
            tem {sorted(celular['atributos'])}
            e o livro tem {sorted(livro['atributos'])}.
            Nenhuma coluna vazia, nenhuma tabela extra.
        """)

        # ------------------------------------------------------------------ 2
        filtro_livros = {"categoria": "livro", "atributos.paginas": {"$gt": 300}}
        s.operacao("R2", "Consulta por atributo específico: livros com mais de 300 páginas", """
db.produtos.countDocuments({ categoria: "livro", "atributos.paginas": { $gt: 300 } })
db.produtos.find(
    { categoria: "livro", "atributos.paginas": { $gt: 300 } },
    { nome: 1, marca: 1, preco: 1, "atributos.paginas": 1, "atributos.autor": 1 }
).sort({ "atributos.paginas": -1 }).limit(5)""")
        s.retorno(produtos.count_documents(filtro_livros), "Total de livros com mais de 300 páginas")
        s.retorno(list(produtos.find(
            filtro_livros,
            {"nome": 1, "marca": 1, "preco": 1, "atributos.paginas": 1, "atributos.autor": 1},
        ).sort("atributos.paginas", -1).limit(5)), "Os 5 mais longos")

        plano = produtos.find(filtro_livros).explain()["queryPlanner"]["winningPlan"]
        estagios = []
        while plano:  # percorre o plano (ex.: FETCH -> IXSCAN) para mostrar o índice usado
            estagios.append(plano["stage"] + (f" ({plano['indexName']})" if "indexName" in plano else ""))
            plano = plano.get("inputStage")
        s.retorno(" -> ".join(estagios), "Plano de execução (explain)")
        s.nota("""
            O índice idx_categoria reduz a busca aos 100 livros (IXSCAN); o filtro
            em atributos.paginas é aplicado sobre eles (FETCH).
        """)

        filtro_cel = {"categoria": "celular", "atributos.memoria_gb": {"$gte": 256},
                      "atributos.tela_polegadas": {"$gte": 6.5}}
        s.operacao("R2", "Outro atributo, outra categoria: celulares com 256 GB ou mais e tela >= 6.5\"", """
db.produtos.find(
    { categoria: "celular", "atributos.memoria_gb": { $gte: 256 }, "atributos.tela_polegadas": { $gte: 6.5 } },
    { nome: 1, preco: 1, "atributos.memoria_gb": 1, "atributos.tela_polegadas": 1 }
).sort({ preco: 1 }).limit(5)""")
        s.retorno(produtos.count_documents(filtro_cel), "Total encontrado")
        s.retorno(list(produtos.find(
            filtro_cel, {"nome": 1, "preco": 1, "atributos.memoria_gb": 1, "atributos.tela_polegadas": 1},
        ).sort("preco", 1).limit(5)), "Os 5 mais baratos")

        # ------------------------------------------------------------------ 3
        # Remove antes, para a demo poder ser executada várias vezes.
        produtos.delete_one({"_id": FONE["_id"]})
        s.operacao("R2", "Categoria nova (\"fone\") sem alterar esquema", """
db.produtos.distinct("categoria")          // antes
db.produtos.insertOne({
    _id: 501, nome: "Fone Nexa Pulse ANC", categoria: "fone", marca: "Nexa",
    preco: 499.90,
    atributos: { tipo: "bluetooth", cancelamento_ruido: true, bateria_horas: 30,
                 driver_mm: 40, microfone: true }
})
db.produtos.distinct("categoria")          // depois
db.produtos.find({ categoria: "fone" })""")
        s.retorno(sorted(produtos.distinct("categoria")), "Categorias ANTES")
        resultado = produtos.insert_one(FONE)
        s.retorno(f"insertOne -> acknowledged={resultado.acknowledged}, insertedId={resultado.inserted_id}")
        s.retorno(sorted(produtos.distinct("categoria")), "Categorias DEPOIS")
        s.retorno(list(produtos.find({"categoria": "fone"})), "Produto novo")
        s.nota("""
            Nenhum ALTER TABLE, nenhuma migração: os documentos antigos continuam
            iguais e o fone já pode ser consultado pelos atributos dele
            (ex.: { "atributos.cancelamento_ruido": true }). No relacional seria
            preciso criar colunas ou uma tabela nova.
        """)

        # ------------------------------------------------------------------ 4
        s.operacao("R2", "Flexível, mas com regra: o validador $jsonSchema recusa produto sem preço", """
db.produtos.insertOne({ _id: 999, nome: "Produto sem preço", categoria: "fone",
                        marca: "Nexa", atributos: {} })""")
        try:
            produtos.insert_one({"_id": 999, "nome": "Produto sem preço", "categoria": "fone",
                                 "marca": "Nexa", "atributos": {}})
            s.retorno("(inesperado) o documento foi aceito")
        except WriteError as erro:
            detalhes = erro.details.get("errInfo", {}).get("details", {})
            faltando = [r.get("missingProperties") for r in detalhes.get("schemaRulesNotSatisfied", [])
                        if r.get("missingProperties")]
            # código 121 = DocumentValidationFailure
            s.retorno(f"ERRO {erro.code} (DocumentValidationFailure): Document failed validation; "
                      f"campos obrigatórios ausentes: {faltando}")
        s.nota("""
            O validador exige os campos comuns (nome, categoria, marca, preco,
            atributos) e deixa o conteúdo de "atributos" livre: a flexibilidade fica
            só onde o requisito pede.
        """)


if __name__ == "__main__":
    main()
