# Projeto Gráfica — protótipo de orçamento automático

Fluxo validado aqui:

```
WhatsApp (texto)  ->  IA extrai pedido em JSON  ->  orcamento.py  ->  consulta FuturaIM  ->  custo + margem no terminal
```

Neste protótipo, a etapa da IA é feita no chat: você cola a mensagem do cliente, o Claude devolve o JSON, e você roda o script.

## Instalação (Windows)

```
cd "Projeto Grafica"
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

## Uso com IA (cotar.py)

1. Crie um arquivo `.env` na raiz do projeto com a linha `ANTHROPIC_API_KEY=sk-ant-...` (sua chave).
2. `pip install -r requirements.txt`
3. Rode:

```
python cotar.py "1.500 cartões de visita couché brilho"
python cotar.py --json "1000 folhetos 150g frente e verso"   # mostra também o JSON gerado
```

A IA consulta o catálogo real da Futura (ferramentas `buscar_produtos` e `opcoes_produto`) antes de montar o pedido. O JSON gerado fica salvo em `pedidos/`. As regras da IA ficam em `ia/prompt.md`, e o modelo é escolhido em `config.py` (`MODELO_IA`).

## API para o app (api.py)

```
uvicorn api:app --reload --port 8000     # local; teste em http://localhost:8000/docs
```

Deploy no Railway: conecte o repositório. O `railway.json` já define o comando de start e o healthcheck. Em *Variables*, crie `ANTHROPIC_API_KEY` e, opcionalmente, `CODIGO_ACESSO`. Depois gere o domínio público em *Settings > Networking*. O contrato da API está em `API.md`.

## Uso manual (orcamento.py, colando o JSON)

```
python orcamento.py exemplo_pedido.json   # a partir de um arquivo
python orcamento.py                       # cola o JSON no terminal (o script para sozinho quando o JSON fecha)
python orcamento.py --catalogo            # lista os ~600 produtos da Futura (slugs)
python orcamento.py --sem-cache pedido.json  # ignora o cache e busca o preço atualizado
```

As margens ficam em `config.py`.

## Formato do JSON (o que a IA deve devolver)

```json
{
  "cliente": "nome / empresa (se aparecer)",
  "itens": [
    {
      "descricao_cliente": "o que o cliente pediu, com as palavras dele",
      "produto": "descrição do produto (usada na busca se não houver slug)",
      "slug_futura": "folheto-em-couche-brilho",
      "quantidade": 1000,
      "atributos": {
        "material": "Couché Brilho 150g",
        "formato": "200x280mm",
        "cor": "4x4",
        "enobrecimento": "Sem Enobrecimento",
        "acabamento": "Refile"
      },
      "suposicoes": ["A4 tratado como 200x280mm, o formato mais próximo da Futura"]
    }
  ],
  "perguntas_ao_cliente": ["o que faltou para fechar o orçamento"]
}
```

- `slug_futura` é opcional. Sem ele, o script procura o produto pelo texto de `produto` no catálogo.
- Em `atributos`, preencha só o que o cliente especificou ou o que dá para deduzir com segurança. O que ficar de fora fica com o padrão do site.
- Chaves aceitas: material/papel, formato/tamanho, cor/impressão, enobrecimento/laminação/verniz, acabamento/corte.

## Como funciona a consulta à Futura (`fornecedores/futura.py`)

- Cada combinação de opções é um SKU com id próprio (`/produto/<slug>?id=<n>`). A página já traz a tabela completa de quantidade x preço.
- Ao trocar uma opção, o site **não** preserva as outras escolhas. Por isso o código explora as variações (busca best-first, até 40 páginas) até achar a combinação pedida.
- As páginas ficam em cache local (`.cache/`) por 6 h, e há uma pausa de 0,7 s entre requisições.
- Quantidade fora das faixas: usa a próxima faixa acima e avisa.

## Limitações conhecidas

- Produtos com tamanho personalizado (cm²) ainda não são cotados: o preço vem de um formulário.
- Só a Futura por enquanto. Novos fornecedores entram como novos módulos em `fornecedores/`.
- Frete, criação de arte e revisão de arquivo não entram no custo.
