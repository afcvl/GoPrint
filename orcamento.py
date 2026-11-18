"""
Protótipo: pedido estruturado (JSON que a IA extrai do WhatsApp) -> orçamento.

Uso:
    python orcamento.py pedido.json      # lê de arquivo
    python orcamento.py                  # cola o JSON no terminal (para sozinho ao fechar o JSON)
    python orcamento.py --catalogo       # lista os produtos da Futura (slugs)
    python orcamento.py --sem-cache ...  # força buscar preço atualizado
"""
from __future__ import annotations

import json
import math
import sys

import config
from fornecedores.futura import Futura, Http

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


def reais(v: float) -> str:
    return "R$ " + f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def ler_json_do_terminal() -> dict:
    print("Cole o JSON do pedido (termina sozinho quando o JSON fechar):")
    buf = ""
    for linha in sys.stdin:
        buf += linha
        try:
            return json.loads(buf)
        except json.JSONDecodeError:
            continue
    return json.loads(buf)


def preco_venda(custo: float, slug: str) -> tuple[float, float]:
    markup = config.MARKUP_PADRAO
    for trecho, m in config.MARKUP_POR_PRODUTO.items():
        if trecho in slug:
            markup = m
    v = max(custo * (1 + markup), config.VENDA_MINIMA)
    if config.ARREDONDAR_90:
        v = math.floor(v) + 0.90 if v - math.floor(v) <= 0.90 else math.floor(v) + 1.90
    return round(v, 2), markup


def orcar_item(futura: Futura, item: dict, n: int) -> dict | None:
    titulo = item.get("descricao_cliente") or item.get("produto") or "item"
    print(f"\n[{n}] {titulo}")
    print("-" * 72)

    slug = item.get("slug_futura")
    if not slug:
        ranking = futura.buscar_produto(item.get("produto", ""))
        slug, conf = ranking[0]
        alt = ", ".join(f"{s} ({c:.2f})" for s, c in ranking[1:])
        print(f"  Produto (busca)  : {slug}  confiança {conf:.2f}")
        print(f"  Alternativas     : {alt}")
    try:
        res = futura.encontrar_variacao(slug, item.get("atributos", {}))
    except Exception as e:  # noqa: BLE001
        print(f"  !! erro ao consultar a Futura: {e}")
        return None

    p = res.pagina
    if not res.completo:
        print("\n⚠ ATENÇÃO: COMBINAÇÃO NÃO ENCONTRADA\n")

    print(f"  Produto Futura   : {p.nome}")
    print(f"  Combinação       : {p.descricao_sku or p.id}  ({res.paginas_visitadas} pág. exploradas)")
    # pedido x cotado lado a lado
    w_chave = max([len("Atributo")] + [len(a["chave"]) for a in res.atributos])
    w_ped = max([len("Pedido")] + [len(a["pedido"]) for a in res.atributos])
    print(f"      {'Atributo':<{w_chave}}   {'Pedido':<{w_ped}}   Cotado")
    for a in res.atributos:
        marca = "OK" if a["ok"] else "!!"
        print(f"   {marca} {a['chave']:<{w_chave}}   {a['pedido']:<{w_ped}}   {a['encontrado'] or '—'}")

    qtd = int(item.get("quantidade") or 0)
    faixa, nota = futura.faixa_para(p, qtd)
    if not faixa:
        print(f"  !! {nota}")
        return None
    custo = faixa.preco_total
    venda, markup = preco_venda(custo, p.slug)
    unit = f"  ({reais(faixa.preco_unit)}/un)" if faixa.preco_unit else ""
    print(f"  Quantidade       : {qtd} -> {faixa.quantidade} un  [{nota}]")
    print(f"  Custo Futura     : {reais(custo)}{unit}")
    print(f"  Preço de venda   : {reais(venda)}   (markup {markup:.0%}, lucro bruto {reais(venda - custo)})")
    print(f"  Link             : {p.url(faixa.sku_id)}")
    vizinhas = [f for f in p.faixas if f.quantidade != faixa.quantidade]
    if vizinhas:
        perto = sorted(vizinhas, key=lambda f: abs(f.quantidade - faixa.quantidade))[:3]
        txt = " | ".join(f"{f.quantidade} un = {reais(preco_venda(f.preco_total, p.slug)[0])}"
                         for f in sorted(perto, key=lambda f: f.quantidade))
        print(f"  Outras faixas    : {txt}  (preço de venda)")
    return {"custo": custo, "venda": venda, "ok": res.completo}


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    http = Http(ttl_horas=config.CACHE_HORAS, usar_cache="--sem-cache" not in sys.argv)
    futura = Futura(http)

    if "--catalogo" in sys.argv:
        for s in futura.catalogo():
            print(s)
        return

    if args:
        with open(args[0], encoding="utf-8") as f:
            pedido = json.load(f)
    else:
        pedido = ler_json_do_terminal()

    print("=" * 72)
    print(f" ORÇAMENTO — cliente: {pedido.get('cliente') or '(não informado)'}   fornecedor: {futura.nome}")
    print("=" * 72)

    resultados = [orcar_item(futura, it, i) for i, it in enumerate(pedido.get("itens", []), 1)]
    validos = [r for r in resultados if r]

    print("\n" + "=" * 72)
    if validos:
        custo = sum(r["custo"] for r in validos)
        venda = sum(r["venda"] for r in validos)
        print(f" TOTAL  custo {reais(custo)}   venda {reais(venda)}   lucro bruto {reais(venda - custo)}")
    pend = [i for i, r in enumerate(resultados, 1) if not r or not r["ok"]]
    if pend:
        print(f" !! Itens para revisão humana: {pend}")
    if pedido.get("perguntas_ao_cliente"):
        print(" Perguntar ao cliente:")
        for q in pedido["perguntas_ao_cliente"]:
            print(f"   - {q}")
    print(f" ({http.requisicoes} requisições ao site, {http.cache_hits} do cache)")
    print("=" * 72)


if __name__ == "__main__":
    main()
