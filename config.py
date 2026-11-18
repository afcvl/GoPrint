# Regras de preço do protótipo — ajuste à vontade.

# Markup sobre o custo do fornecedor (0.60 = custo x 1,60).
MARKUP_PADRAO = 0.60

# Markup por tipo de produto (casa por trecho do slug da Futura). Opcional.
MARKUP_POR_PRODUTO = {
    # "cartao-de-visita": 0.80,
    # "banner": 0.50,
}

# Valor mínimo de venda por item (R$). 0 = sem mínimo.
VENDA_MINIMA = 0.0

# Arredondar preço de venda para terminar em ,90 (True/False)
ARREDONDAR_90 = True

# Cache das páginas do fornecedor (horas). Preço muda pouco no dia.
CACHE_HORAS = 6

# Modelo da IA que interpreta o pedido (cotar.py).
# Opções: "claude-haiku-5-5" (mais barato), "claude-sonnet-5-5" (mais preciso)
MODELO_IA = "claude-haiku-5-5"
