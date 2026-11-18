"""
IA que transforma o pedido do atendente (texto livre) no JSON de pedido
usado pelo sistema de orçamento.

A IA (Claude, via API) usa ferramentas que consultam o catálogo REAL da Futura
antes de montar o pedido, para só escolher combinações que existem.

Requer ANTHROPIC_API_KEY no arquivo .env (raiz do projeto).
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

from fornecedores.futura import Futura

RAIZ = Path(__file__).resolve().parent.parent
PROMPT = (Path(__file__).resolve().parent / "prompt.md").read_text(encoding="utf-8")
MAX_RODADAS = 12

# ----------------------------------------------------------------------------
# Ferramentas oferecidas à IA
# ----------------------------------------------------------------------------
SCHEMA_PEDIDO = {
    "type": "object",
    "properties": {
        "cliente": {"type": ["string", "null"], "description": "Nome do cliente, se o atendente informou"},
        "itens": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "descricao_cliente": {"type": "string", "description": "O pedido nas palavras do atendente"},
                    "produto": {"type": "string", "description": "Nome curto do produto"},
                    "slug_futura": {"type": "string", "description": "Slug exato do produto na Futura"},
                    "quantidade": {"type": "integer"},
                    "atributos": {
                        "type": "object",
                        "description": "grupo -> valor, copiados exatamente das opções do site",
                        "additionalProperties": {"type": "string"},
                    },
                    "informados": {"type": "array", "items": {"type": "string"},
                                   "description": "Chaves de atributos ditas explicitamente pelo atendente"},
                    "suposicoes": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["descricao_cliente", "produto", "slug_futura", "quantidade", "atributos",
                             "informados", "suposicoes"],
            },
        },
        "perguntas_ao_cliente": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["cliente", "itens", "perguntas_ao_cliente"],
}

FERRAMENTAS = [
    {
        "name": "buscar_produtos",
        "description": "Busca produtos no catálogo da FuturaIM por texto. Retorna até 10 slugs com nota de semelhança.",
        "input_schema": {
            "type": "object",
            "properties": {"termo": {"type": "string", "description": "ex.: 'cartão de visita couché', 'adesivo bopp'"}},
            "required": ["termo"],
        },
    },
    {
        "name": "opcoes_produto",
        "description": (
            "Consulta as opções reais de um produto da Futura a partir de uma seleção parcial. "
            "Diz se a combinação existe, quais opções existem a partir dela e as quantidades disponíveis. "
            "Chaves de 'selecao' podem ser: modelo, material, formato, cor, enobrecimento, acabamento."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "slug": {"type": "string"},
                "selecao": {"type": "object", "additionalProperties": {"type": "string"}},
            },
            "required": ["slug", "selecao"],
        },
    },
    {
        "name": "registrar_pedido",
        "description": "Entrega o pedido final estruturado. Chame uma única vez, no fim.",
        "input_schema": SCHEMA_PEDIDO,
    },
]


def _buscar_produtos(futura: Futura, termo: str) -> dict:
    return {"resultados": [{"slug": s, "nota": n} for s, n in futura.buscar_produto(termo, n=10)]}


def _opcoes_produto(futura: Futura, slug: str, selecao: dict) -> dict:
    if slug not in futura.catalogo():
        return {"erro": f"slug '{slug}' não existe no catálogo. Use buscar_produtos."}
    res = futura.encontrar_variacao(slug, selecao or {})
    p = res.pagina
    disponiveis: dict[str, list[str]] = {}
    for o in p.opcoes:
        disponiveis.setdefault(o.grupo, [])
        if o.valor not in disponiveis[o.grupo]:
            disponiveis[o.grupo].append(o.valor)
    return {
        "produto": p.nome,
        "slug": slug,
        "bateu_tudo": res.completo,
        "comparacao": [{"pedido": a["pedido"], "chave": a["chave"], "cotado": a["encontrado"], "ok": a["ok"]}
                       for a in res.atributos],
        "combinacao_encontrada": p.selecionado,
        "opcoes_disponiveis": disponiveis,
        "quantidades": [f.quantidade for f in p.faixas],
        "observacao": None if p.faixas else "produto sem tabela de quantidades (tamanho personalizado?)",
    }


# ----------------------------------------------------------------------------
# Loop com a API
# ----------------------------------------------------------------------------
@dataclass
class ResultadoIA:
    pedido: dict | None
    tokens_entrada: int = 0
    tokens_saida: int = 0
    tokens_cache_lidos: int = 0
    chamadas_ferramentas: list[str] = field(default_factory=list)
    erro: str | None = None


def carregar_env():
    try:
        from dotenv import load_dotenv
        load_dotenv(RAIZ / ".env")
    except ImportError:
        pass


def extrair_pedido(texto: str, futura: Futura, modelo: str, cliente_api=None, verbose: bool = True) -> ResultadoIA:
    if cliente_api is None:
        carregar_env()
        if not os.environ.get("ANTHROPIC_API_KEY"):
            return ResultadoIA(None, erro="ANTHROPIC_API_KEY não encontrada no .env")
        import anthropic
        cliente_api = anthropic.Anthropic()

    system = [{"type": "text", "text": PROMPT, "cache_control": {"type": "ephemeral"}}]
    mensagens = [{"role": "user", "content": texto}]
    r = ResultadoIA(None)

    for _ in range(MAX_RODADAS):
        resp = cliente_api.messages.create(
            model=modelo, max_tokens=2000, system=system, tools=FERRAMENTAS, messages=mensagens,
        )
        u = resp.usage
        r.tokens_entrada += getattr(u, "input_tokens", 0) or 0
        r.tokens_saida += getattr(u, "output_tokens", 0) or 0
        r.tokens_cache_lidos += getattr(u, "cache_read_input_tokens", 0) or 0

        mensagens.append({"role": "assistant", "content": resp.content})
        usos = [b for b in resp.content if getattr(b, "type", None) == "tool_use"]
        if not usos:
            r.erro = "a IA terminou sem registrar o pedido"
            return r

        resultados = []
        for uso in usos:
            r.chamadas_ferramentas.append(uso.name)
            if uso.name == "registrar_pedido":
                r.pedido = uso.input
                return r
            try:
                if uso.name == "buscar_produtos":
                    saida = _buscar_produtos(futura, uso.input.get("termo", ""))
                elif uso.name == "opcoes_produto":
                    if verbose:
                        print(f"   … consultando {uso.input.get('slug')} {uso.input.get('selecao')}")
                    saida = _opcoes_produto(futura, uso.input.get("slug", ""), uso.input.get("selecao") or {})
                else:
                    saida = {"erro": f"ferramenta desconhecida: {uso.name}"}
            except Exception as e:  # noqa: BLE001
                saida = {"erro": str(e)}
            resultados.append({"type": "tool_result", "tool_use_id": uso.id,
                               "content": json.dumps(saida, ensure_ascii=False)})
        mensagens.append({"role": "user", "content": resultados})

    r.erro = f"limite de {MAX_RODADAS} rodadas atingido"
    return r
