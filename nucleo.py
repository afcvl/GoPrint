"""
Núcleo do orçamento em forma de DADOS (para a API / app).
Mesma lógica do orcamento.py (busca, faixa, margem), mas devolve dicionários
em vez de imprimir no terminal.
"""
from __future__ import annotations

from fornecedores.futura import Futura
from orcamento import preco_venda


def orcar_item_dados(futura: Futura, item: dict) -> dict:
    out = {
        "descricao": item.get("descricao_cliente") or item.get("produto") or "item",
        "slug": item.get("slug_futura"),
        "suposicoes": item.get("suposicoes") or [],
        "erro": None,
    }
    slug = item.get("slug_futura")
    if not slug:
        ranking = futura.buscar_produto(item.get("produto", ""))
        slug = ranking[0][0]
        out["slug"] = slug
    try:
        res = futura.encontrar_variacao(slug, item.get("atributos", {}))
    except Exception as e:  # noqa: BLE001
        out["erro"] = f"erro ao consultar a Futura: {e}"
        return out

    p = res.pagina
    out.update({
        "produto": p.nome,
        "combinacao": p.descricao_sku or str(p.id),
        "encontrado": res.completo,
        "alerta": None if res.completo else "COMBINAÇÃO NÃO ENCONTRADA",
        "atributos": [{"atributo": a["chave"], "pedido": a["pedido"],
                       "cotado": a["encontrado"], "ok": a["ok"]} for a in res.atributos],
    })

    qtd = int(item.get("quantidade") or 0)
    faixa, nota = futura.faixa_para(p, qtd)
    out["quantidade_pedida"] = qtd
    if not faixa:
        out["erro"] = nota
        return out
    custo = faixa.preco_total
    venda, markup = preco_venda(custo, p.slug)
    out.update({
        "quantidade_cotada": faixa.quantidade,
        "nota_quantidade": nota,
        "custo": custo,
        "preco_unit_fornecedor": faixa.preco_unit,
        "venda": venda,
        "lucro": round(venda - custo, 2),
        "markup": markup,
        "link": p.url(faixa.sku_id),
        "outras_faixas": [{"quantidade": f.quantidade, "venda": preco_venda(f.preco_total, p.slug)[0]}
                          for f in p.faixas if f.quantidade != faixa.quantidade],
    })
    return out


def orcar_pedido_dados(futura: Futura, pedido: dict) -> dict:
    itens = [orcar_item_dados(futura, it) for it in pedido.get("itens", [])]
    validos = [i for i in itens if i.get("venda") is not None]
    custo = round(sum(i["custo"] for i in validos), 2)
    venda = round(sum(i["venda"] for i in validos), 2)
    return {
        "cliente": pedido.get("cliente"),
        "itens": itens,
        "total": {"custo": custo, "venda": venda, "lucro": round(venda - custo, 2)},
        "perguntas_ao_cliente": pedido.get("perguntas_ao_cliente") or [],
        "revisao_humana": [n for n, i in enumerate(itens, 1) if i.get("erro") or not i.get("encontrado")],
    }
