# API de orçamentos — contrato para o app (Lovable)

Base URL: o endereço público do Railway (ex.: `https://projeto-grafica-production.up.railway.app`)

## POST /orcar

Envia o pedido em texto (vindo do microfone ou da caneta) e recebe o orçamento.

Headers:
- `Content-Type: application/json`
- `X-Codigo-Acesso: <código>` — só se a variável `CODIGO_ACESSO` estiver definida no Railway

Body:
```json
{ "texto": "1.500 cartões de visita couché brilho" }
```

Leva de 5 a 40 s (IA + consulta ao fornecedor). Mostre um estado de carregamento e use timeout de pelo menos 90 s.

Resposta 200:
```json
{
  "ok": true,
  "texto": "1.500 cartões de visita couché brilho",
  "cliente": null,
  "itens": [
    {
      "descricao": "1.500 cartões de visita couché brilho",
      "produto": "Cartão de Visita em Couché Brilho",
      "combinacao": "4556 - 500 Cartão de Visita - 88x48mm em Couché Brilho 300g - 4x0 - ...",
      "encontrado": true,
      "alerta": null,
      "atributos": [
        { "atributo": "material", "pedido": "Couché Brilho 300g", "cotado": "Couché Brilho 300g", "ok": true }
      ],
      "quantidade_pedida": 1500,
      "quantidade_cotada": 5000,
      "nota_quantidade": "sem faixa de 1500; usando a próxima (5000 un)",
      "custo": 329.99,
      "preco_unit_fornecedor": 0.07,
      "venda": 527.9,
      "lucro": 197.91,
      "markup": 0.6,
      "link": "https://www.futuraim.com.br/produto/...",
      "outras_faixas": [ { "quantidade": 1000, "venda": 127.9 } ],
      "suposicoes": [ "Impressão não informada: usado 4x0 (só frente)" ],
      "erro": null
    }
  ],
  "total": { "custo": 329.99, "venda": 527.9, "lucro": 197.91 },
  "perguntas_ao_cliente": [ "Impressão só na frente ou frente e verso?" ],
  "revisao_humana": [],
  "uso": { "modelo": "claude-haiku-5-5", "segundos": 12.3 }
}
```
(valores ilustrativos)

Como exibir cada item:
- `alerta` não nulo → faixa de destaque "⚠ ATENÇÃO: COMBINAÇÃO NÃO ENCONTRADA" no topo do cartão.
- `atributos` → tabela Atributo | Pedido | Cotado, marcando as linhas com `ok: false`.
- `venda` em destaque; `custo` e `lucro` menores.
- Se `quantidade_cotada` ≠ `quantidade_pedida`, mostre `nota_quantidade`.
- `erro` não nulo → o item não pôde ser cotado; mostre a mensagem.
- `suposicoes` e `perguntas_ao_cliente` → listas abaixo dos cartões.

Erros:
- `401` — código de acesso inválido
- `422` — texto vazio ou muito longo
- `502` — a IA não conseguiu interpretar o pedido (`detail` traz o motivo)

## GET /saude
`{"ok": true, "modelo": "...", "chave_configurada": true}` — para checar se o servidor está no ar e com a chave.

## GET /teste-futura
Verifica se o servidor consegue abrir o site da Futura. `{"ok": true, ...}` = tudo certo.

## GET /docs
Página interativa para testar a API pelo navegador.
