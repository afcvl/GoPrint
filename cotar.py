"""
Orçamento a partir do pedido do atendente em texto livre.

Uso:
    python cotar.py "1.500 cartões de visita couché brilho"
    python cotar.py                       # pergunta o pedido no terminal
    python cotar.py --json "..."          # mostra também o JSON gerado pela IA
    python cotar.py --sem-cache "..."     # força buscar preço atualizado na Futura

A IA gera o JSON (mesmo formato do orcamento.py) e o sistema calcula o preço.
O JSON gerado fica salvo em pedidos/ para conferência.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

import config
from fornecedores.futura import Futura, Http
from ia.extrator import extrair_pedido
from orcamento import orcar_item, reais

RAIZ = Path(__file__).resolve().parent


def main():
    flags = {a for a in sys.argv[1:] if a.startswith("--")}
    texto = " ".join(a for a in sys.argv[1:] if not a.startswith("--")).strip()
    if not texto:
        texto = input("Pedido do orçamento: ").strip()
    if not texto:
        return

    http = Http(ttl_horas=config.CACHE_HORAS, usar_cache="--sem-cache" not in flags)
    futura = Futura(http)

    print(f"\n» Interpretando o pedido com IA ({config.MODELO_IA})...")
    r = extrair_pedido(texto, futura, config.MODELO_IA)
    if r.erro or not r.pedido:
        print(f"!! Não foi possível gerar o pedido: {r.erro}")
        return
    pedido = r.pedido

    pasta = RAIZ / "pedidos"
    pasta.mkdir(exist_ok=True)
    arq = pasta / f"{datetime.now():%Y%m%d-%H%M%S}.json"
    arq.write_text(json.dumps({"texto": texto, **pedido}, ensure_ascii=False, indent=2), encoding="utf-8")
    if "--json" in flags:
        print(json.dumps(pedido, ensure_ascii=False, indent=2))

    print("=" * 72)
    print(f" ORÇAMENTO — cliente: {pedido.get('cliente') or '(não informado)'}   fornecedor: {futura.nome}")
    print("=" * 72)
    resultados = []
    for i, it in enumerate(pedido.get("itens", []), 1):
        res = orcar_item(futura, it, i)
        if it.get("suposicoes"):
            print("  Suposições da IA :")
            for s in it["suposicoes"]:
                print(f"     - {s}")
        resultados.append(res)
    validos = [x for x in resultados if x]

    print("\n" + "=" * 72)
    if validos:
        custo = sum(x["custo"] for x in validos)
        venda = sum(x["venda"] for x in validos)
        print(f" TOTAL  custo {reais(custo)}   venda {reais(venda)}   lucro bruto {reais(venda - custo)}")
    pend = [i for i, x in enumerate(resultados, 1) if not x or not x["ok"]]
    if pend:
        print(f" !! Itens para revisão humana: {pend}")
    if pedido.get("perguntas_ao_cliente"):
        print(" Perguntar ao cliente:")
        for q in pedido["perguntas_ao_cliente"]:
            print(f"   - {q}")
    print(f" (IA: {r.tokens_entrada} tokens de entrada, {r.tokens_cache_lidos} do cache, "
          f"{r.tokens_saida} de saída | site: {http.requisicoes} requisições, {http.cache_hits} do cache)")
    print(f" Pedido salvo em: {arq.relative_to(RAIZ)}")
    print("=" * 72)


if __name__ == "__main__":
    main()
