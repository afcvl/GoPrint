"""
API do sistema de orçamentos (para o app no Lovable).

Rodar localmente:
    uvicorn api:app --reload --port 8000
    (abra http://localhost:8000/docs para testar no navegador)

Variáveis de ambiente (no Railway: aba Variables; localmente: .env):
    ANTHROPIC_API_KEY   obrigatória
    CODIGO_ACESSO       opcional. Se definida, o app precisa mandar o header
                        X-Codigo-Acesso com esse valor.
    MODELO_IA           opcional. Sobrescreve config.MODELO_IA.
"""
from __future__ import annotations

import os
import time

from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

import config
from fornecedores.futura import Futura, Http
from ia.extrator import carregar_env, extrair_pedido
from nucleo import orcar_pedido_dados

carregar_env()

app = FastAPI(title="Orçamentos Gráfica", version="0.1")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],   # demo: libera o app do Lovable (preview e publicado)
    allow_methods=["*"],
    allow_headers=["*"],
)

# um cliente da Futura compartilhado: reaproveita cache de páginas entre pedidos
_http = Http(ttl_horas=config.CACHE_HORAS)
_futura = Futura(_http)


def _checar_acesso(codigo: str | None):
    esperado = os.environ.get("CODIGO_ACESSO")
    if esperado and codigo != esperado:
        raise HTTPException(status_code=401, detail="código de acesso inválido")


class PedidoTexto(BaseModel):
    texto: str = Field(..., min_length=3, max_length=2000,
                       examples=["1.500 cartões de visita couché brilho"])


@app.get("/saude")
def saude():
    return {"ok": True, "modelo": os.environ.get("MODELO_IA", config.MODELO_IA),
            "chave_configurada": bool(os.environ.get("ANTHROPIC_API_KEY"))}


@app.get("/teste-futura")
def teste_futura():
    """Verifica se este servidor consegue abrir o site da Futura."""
    t = time.time()
    try:
        pag = _futura.pagina("cartao-de-visita-em-couche-brilho")
        return {"ok": bool(pag.faixas), "produto": pag.nome, "faixas": len(pag.faixas),
                "segundos": round(time.time() - t, 2)}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "erro": str(e), "segundos": round(time.time() - t, 2)}


@app.post("/orcar")
def orcar(body: PedidoTexto, x_codigo_acesso: str | None = Header(default=None)):
    _checar_acesso(x_codigo_acesso)
    t = time.time()
    req0, cache0 = _http.requisicoes, _http.cache_hits
    modelo = os.environ.get("MODELO_IA", config.MODELO_IA)

    r = extrair_pedido(body.texto.strip(), _futura, modelo, verbose=False)
    if r.erro or not r.pedido:
        raise HTTPException(status_code=502, detail=f"não foi possível interpretar o pedido: {r.erro}")

    resultado = orcar_pedido_dados(_futura, r.pedido)
    return {
        "ok": True,
        "texto": body.texto,
        **resultado,
        "pedido_ia": r.pedido,
        "uso": {
            "modelo": modelo,
            "tokens_entrada": r.tokens_entrada,
            "tokens_cache": r.tokens_cache_lidos,
            "tokens_saida": r.tokens_saida,
            "requisicoes_site": _http.requisicoes - req0,
            "cache_site": _http.cache_hits - cache0,
            "segundos": round(time.time() - t, 1),
        },
    }
