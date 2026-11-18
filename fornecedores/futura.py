"""
Cliente da FuturaIM (www.futuraim.com.br).

Como o site funciona (investigado em 17/11/2026):
- Páginas renderizadas no servidor; preço visível sem login.
- Cada combinação de opções (material, formato, cor, enobrecimento,
  acabamento, quantidade) é um SKU com id próprio: /produto/<slug>?id=<id>
- A página traz a tabela COMPLETA de quantidades x preço (table#table-variacoes).
- As opções são links ocultos: <a href="/produto/<slug>?id=N" title="Ver produto no <Grupo> <Valor>">
- ATENÇÃO: clicar numa opção NÃO preserva as outras escolhas. Por isso
  a busca explora o grafo de variações (best-first) até achar a combinação.
- /sitemap.xml lista ~600 produtos (/produto/<slug>).
"""
from __future__ import annotations

import hashlib
import heapq
import json
import re
import time
import unicodedata
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path

import requests
from bs4 import BeautifulSoup

BASE = "https://www.futuraim.com.br"
CACHE_DIR = Path(__file__).resolve().parent.parent / ".cache" / "futura"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/130.0 Safari/537.36",
    "Accept-Language": "pt-BR,pt;q=0.9",
}
PREFIXO_TITULO = "Ver produto no "
STOPWORDS = {"de", "em", "com", "para", "e", "o", "a", "do", "da", "no", "na", "un", "unidades"}

# Sinônimos que a IA (ou humano) pode usar para os grupos de opções do site
ALIASES_GRUPO = {
    "material": "material", "papel": "material", "substrato": "material", "gramatura": "material",
    "formato": "formato", "tamanho": "formato", "dimensao": "formato", "medida": "formato",
    "cor": "cor", "cores": "cor", "impressao": "cor", "cor de impressao": "cor",
    "enobrecimento": "enobrecimento", "laminacao": "enobrecimento", "verniz": "enobrecimento",
    "acabamento": "acabamento", "corte": "acabamento",
}


# ----------------------------------------------------------------------------
# Texto
# ----------------------------------------------------------------------------
def normalizar(txt: str) -> str:
    txt = str(txt).replace("×", "x")
    txt = unicodedata.normalize("NFKD", txt).encode("ascii", "ignore").decode().lower()
    txt = re.sub(r"(\d+)\s*x\s*(\d+)", r"\1x\2", txt)              # 4 x 4 -> 4x4
    txt = re.sub(r"(\d+)\s+(g|mm|cm|m|ml)\b", r"\1\2", txt)         # 300 g -> 300g
    txt = re.sub(r"[^a-z0-9]+", " ", txt)
    return re.sub(r"\s+", " ", txt).strip()


def tokens(txt: str) -> set[str]:
    return {t for t in normalizar(txt).split() if t not in STOPWORDS}


def similaridade(pedido: str, opcao: str) -> float:
    """0..1 — quanto 'opcao' (texto do site) atende 'pedido' (texto da IA)."""
    tp, to = tokens(pedido), tokens(opcao)
    if not tp or not to:
        return 0.0
    cobertura = len(tp & to) / len(tp)
    precisao = len(tp & to) / len(to)
    ratio = SequenceMatcher(None, normalizar(pedido), normalizar(opcao)).ratio()
    score = 0.55 * cobertura + 0.2 * precisao + 0.25 * ratio
    # números (gramatura, medidas, 4x4) são decisivos: se o pedido tem um número
    # que a opção não tem, penaliza forte
    num_p = {t for t in tp if re.search(r"\d", t)}
    if num_p and not num_p <= to:
        score *= 0.5
    return round(score, 3)


def brl(txt: str) -> float:
    return float(txt.replace(".", "").replace(",", "."))


# ----------------------------------------------------------------------------
# HTTP com cache em disco
# ----------------------------------------------------------------------------
class Http:
    def __init__(self, ttl_horas: float = 6, pausa_s: float = 0.7, usar_cache: bool = True):
        self.ttl = ttl_horas * 3600
        self.pausa = pausa_s
        self.usar_cache = usar_cache
        self.s = requests.Session()
        self.s.headers.update(HEADERS)
        self._ultimo = 0.0
        self.requisicoes = 0
        self.cache_hits = 0
        CACHE_DIR.mkdir(parents=True, exist_ok=True)

    def get(self, caminho: str, ttl_horas: float | None = None) -> str:
        url = caminho if caminho.startswith("http") else BASE + caminho
        arq = CACHE_DIR / (hashlib.sha1(url.encode()).hexdigest() + ".html")
        ttl = self.ttl if ttl_horas is None else ttl_horas * 3600
        if self.usar_cache and arq.exists() and time.time() - arq.stat().st_mtime < ttl:
            self.cache_hits += 1
            return arq.read_text(encoding="utf-8")
        espera = self.pausa - (time.time() - self._ultimo)
        if espera > 0:
            time.sleep(espera)
        r = self.s.get(url, timeout=25)
        self._ultimo = time.time()
        self.requisicoes += 1
        r.raise_for_status()
        arq.write_text(r.text, encoding="utf-8")
        return r.text


# ----------------------------------------------------------------------------
# Página de produto
# ----------------------------------------------------------------------------
@dataclass
class Opcao:
    grupo: str
    valor: str
    slug: str
    id: int


@dataclass
class Faixa:
    quantidade: int
    preco_total: float
    preco_unit: float | None
    sku_id: int


@dataclass
class Pagina:
    slug: str
    id: int | None
    nome: str
    descricao_sku: str
    opcoes: list[Opcao]
    faixas: list[Faixa]
    selecionado: dict[str, str] = field(default_factory=dict)

    @property
    def ids_da_combinacao(self) -> set[int]:
        ids = {f.sku_id for f in self.faixas}
        if self.id:
            ids.add(self.id)
        return ids

    def url(self, sku_id: int | None = None) -> str:
        i = sku_id or self.id
        return f"{BASE}/produto/{self.slug}" + (f"?id={i}" if i else "")


RE_HREF = re.compile(r"/produto/([^?\"'\s]+)\?id=(\d+)")


def parse_pagina(html: str, slug: str) -> Pagina:
    soup = BeautifulSoup(html, "lxml")

    nome, sku, descricao = slug, None, ""
    for sc in soup.find_all("script", type="application/ld+json"):
        try:
            dado = json.loads(sc.string or "")
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(dado, dict) and dado.get("@type") == "Product":
            nome = dado.get("name", nome)
            sku = int(dado["sku"]) if str(dado.get("sku", "")).isdigit() else None
            descricao = (dado.get("description") or "").replace("\r", "").split("\n")[-1].strip()
            break

    opcoes: list[Opcao] = []
    for a in soup.select(f'a[title^="{PREFIXO_TITULO}"]'):
        m = RE_HREF.search(a.get("href", ""))
        if not m:
            continue
        valor = a.get_text(" ", strip=True)
        titulo = a["title"][len(PREFIXO_TITULO):].strip()
        grupo = titulo[: -len(valor)].strip() if valor and titulo.endswith(valor) else titulo.split(" ")[0]
        opcoes.append(Opcao(grupo, valor, m.group(1), int(m.group(2))))

    faixas: list[Faixa] = []
    tabela = soup.select_one("table#table-variacoes")
    if tabela:
        for tr in tabela.select("tbody tr"):
            inp = tr.find("input")
            if not inp or not str(inp.get("id", "")).isdigit():
                continue
            qtd = int(inp["id"])
            m = re.search(r"trocarProduto\('[^']+',\s*(\d+)\)", tr.get("onclick", ""))
            sku_id = int(m.group(1)) if m else (sku or 0)
            texto = tr.get_text(" ", strip=True)
            unit = re.search(r"R\$\s*([\d.]+,\d{2})\s*/\s*un", texto)
            precos = re.findall(r"R\$\s*([\d.]+,\d{2})", texto)
            if not precos:
                continue
            faixas.append(Faixa(qtd, brl(precos[-1]), brl(unit.group(1)) if unit else None, sku_id))
    faixas.sort(key=lambda f: f.quantidade)

    pag = Pagina(slug, sku, nome, descricao, opcoes, faixas)
    pag.selecionado = detectar_selecionado(pag)
    return pag


def detectar_selecionado(pag: Pagina) -> dict[str, str]:
    """
    Qual valor de cada grupo esta página representa.
    1) Opção cujo link aponta para um SKU desta mesma combinação (prova forte).
    2) Senão, opção cujo texto aparece na descrição do SKU
       ex.: "138116 - 100 Adesivo Redondo - 50x50mm em BOPP ... - 4x0 - Sem Enobrecimento - ..."
       (necessário: em alguns produtos os links dos outros grupos apontam para
       uma variação 'canônica', não para a combinação atual)
    """
    ids = pag.ids_da_combinacao
    desc = f" {normalizar(pag.descricao_sku)} "
    por_grupo: dict[str, list[Opcao]] = {}
    for o in pag.opcoes:
        por_grupo.setdefault(o.grupo, []).append(o)

    sel: dict[str, str] = {}
    for g, ops in por_grupo.items():
        por_id = [o for o in ops if o.id in ids]
        if por_id:
            sel[g] = por_id[0].valor
            continue
        # chave do texto: "4x0 - Colorido Frente" -> "4x0"
        casadas = []
        for o in ops:
            chave = normalizar(o.valor.split(" - ")[0])
            if chave and f" {chave} " in desc:
                casadas.append((len(chave), o.valor))
        if casadas:
            sel[g] = max(casadas)[1]          # a mais longa/específica
        elif len(ops) == 1:
            sel[g] = ops[0].valor
    return sel


# ----------------------------------------------------------------------------
# Cliente
# ----------------------------------------------------------------------------
@dataclass
class ResultadoVariacao:
    pagina: Pagina
    atributos: list[dict]        # [{chave, grupo, pedido, encontrado, score, ok}]
    paginas_visitadas: int
    completo: bool
    paginas: list[Pagina] = field(default_factory=list)   # combinações vistas na busca

    def alternativas(self) -> list[str]:
        """
        Para cada opção pedida que não entrou na combinação final, descreve o que
        existe com ela nas páginas visitadas (outras opções e faixa de quantidade).
        Ex.: "Couché Brilho 170g -> Formato: 105x148mm, 148x210mm | quantidades: 25 a 500 un"
        """
        linhas = []
        outros_grupos = [a["grupo"] for a in self.atributos if a["grupo"]]
        for a in self.atributos:
            if a["ok"] or not a["grupo"] or not a["alvo"]:
                continue
            g, v = a["grupo"], a["alvo"]
            com_v = [p for p in self.paginas if p.selecionado.get(g) == v]
            if not com_v:
                linhas.append(f"{v}: nenhuma variação com essa opção foi encontrada")
                continue
            partes = []
            for g2 in outros_grupos:
                if g2 == g:
                    continue
                valores = []
                for p in com_v:
                    for o in p.opcoes:
                        if o.grupo == g2 and o.valor not in valores:
                            valores.append(o.valor)
                if valores:
                    partes.append(f"{g2}: {', '.join(valores)}")
            qtds = sorted({f.quantidade for p in com_v for f in p.faixas})
            if qtds:
                partes.append(f"quantidades: {qtds[0]} a {qtds[-1]} un")
            linhas.append(f"{v} -> " + " | ".join(partes))
        return linhas


class Futura:
    nome = "FuturaIM"

    def __init__(self, http: Http | None = None):
        self.http = http or Http()
        self._paginas: dict[tuple[str, int | None], Pagina] = {}

    # ---- catálogo --------------------------------------------------------
    def catalogo(self) -> list[str]:
        xml = self.http.get("/sitemap.xml", ttl_horas=24 * 7)
        slugs = re.findall(r"<loc>https://www\.futuraim\.com\.br/produto/([^<?]+)</loc>", xml)
        return sorted(set(slugs))

    def buscar_produto(self, texto: str, n: int = 3) -> list[tuple[str, float]]:
        ranking = [(s, similaridade(texto, s.replace("-", " "))) for s in self.catalogo()]
        ranking.sort(key=lambda x: -x[1])
        return ranking[:n]

    # ---- páginas ---------------------------------------------------------
    def pagina(self, slug: str, sku_id: int | None = None) -> Pagina:
        chave = (slug, sku_id)
        if chave not in self._paginas:
            html = self.http.get(f"/produto/{slug}" + (f"?id={sku_id}" if sku_id else ""))
            self._paginas[chave] = parse_pagina(html, slug)
        return self._paginas[chave]

    # ---- mapeamento pedido -> grupos do site -----------------------------
    @staticmethod
    def _grupo_para(chave: str, valor: str, opcoes: list[Opcao]) -> str | None:
        grupos = sorted({o.grupo for o in opcoes})
        alvo = ALIASES_GRUPO.get(normalizar(chave), normalizar(chave))
        for g in grupos:
            ng = normalizar(g)
            if ng == alvo or ng.startswith(alvo) or alvo.startswith(ng):
                return g
        # fallback: o grupo cujas opções melhor casam com o valor pedido
        melhor = max(opcoes, key=lambda o: similaridade(valor, o.valor), default=None)
        if melhor and similaridade(valor, melhor.valor) >= 0.6:
            return melhor.grupo
        return None

    def encontrar_variacao(self, slug: str, atributos: dict[str, str],
                           max_paginas: int = 40, limiar_confianca: float = 0.6) -> ResultadoVariacao:
        """
        Best-first sobre o grafo de variações. Para cada atributo pedido, o
        'alvo' é a opção do site mais parecida com o texto pedido (entre todas
        as opções já vistas daquele grupo). Para quando a página tem todos os alvos.
        """
        inicio = self.pagina(slug)
        pedidos = []  # (chave, grupo, valor_pedido)
        for chave, valor in (atributos or {}).items():
            if valor in (None, ""):
                continue
            pedidos.append((chave, self._grupo_para(chave, str(valor), inicio.opcoes), str(valor)))
        validos = [(c, g, v) for c, g, v in pedidos if g]

        opcoes_vistas: dict[str, set[str]] = {}

        def registrar(p: Pagina):
            for o in p.opcoes:
                opcoes_vistas.setdefault(o.grupo, set()).add(o.valor)

        def alvos() -> dict[str, str]:
            return {g: max(opcoes_vistas.get(g, {""}), key=lambda x: similaridade(v, x))
                    for _, g, v in validos}

        def acertos(p: Pagina, alv: dict[str, str]) -> int:
            return sum(1 for g, a in alv.items() if p.selecionado.get(g) == a)

        registrar(inicio)
        heap: list[tuple[float, int, str, int | None]] = [(0.0, 0, slug, None)]
        contador, visitadas = 0, 0
        vistos_ids: set[int] = set()
        melhor, melhor_score = inicio, -1

        while heap and visitadas < max_paginas:
            _, _, s, i = heapq.heappop(heap)
            if i is not None and i in vistos_ids:
                continue
            p = self.pagina(s, i)
            visitadas += 1
            vistos_ids |= p.ids_da_combinacao
            registrar(p)
            alv = alvos()
            sc = acertos(p, alv)
            if sc > melhor_score:
                melhor, melhor_score = p, sc
            if sc == len(alv):
                break
            for o in p.opcoes:
                if o.id in vistos_ids or o.slug != slug:
                    continue
                melhora = alv.get(o.grupo) == o.valor and p.selecionado.get(o.grupo) != o.valor
                # links que trazem um atributo-alvo vêm primeiro; os demais são
                # exploração (o site não preserva as outras escolhas ao trocar)
                prioridade = -(sc + 1) if melhora else -(sc - 0.5)
                contador += 1
                heapq.heappush(heap, (prioridade, contador, o.slug, o.id))

        # os alvos podem ter mudado durante a busca: reavalia tudo o que foi visto
        alv = alvos()
        visitadas_pags = [pg for (s_, _), pg in self._paginas.items()
                          if s_ == slug and pg.ids_da_combinacao & vistos_ids]
        if visitadas_pags:
            melhor = max(visitadas_pags, key=lambda pg: acertos(pg, alv))
        resumo = []
        for chave, g, v in pedidos:
            enc = melhor.selecionado.get(g) if g else None
            conf = similaridade(v, alv[g]) if g else 0.0
            resumo.append({"chave": chave, "grupo": g, "pedido": v, "alvo": alv.get(g) if g else None,
                           "encontrado": enc, "confianca": conf,
                           "ok": bool(g) and enc == alv.get(g) and conf >= limiar_confianca})
        return ResultadoVariacao(melhor, resumo, visitadas, all(r["ok"] for r in resumo), visitadas_pags)

    # ---- preço -----------------------------------------------------------
    @staticmethod
    def faixa_para(pagina: Pagina, quantidade: int) -> tuple[Faixa | None, str]:
        if not pagina.faixas:
            return None, "produto sem tabela de quantidades (tamanho personalizado?)"
        for f in pagina.faixas:
            if f.quantidade == quantidade:
                return f, "faixa exata"
        maiores = [f for f in pagina.faixas if f.quantidade > quantidade]
        if maiores:
            f = maiores[0]
            return f, f"sem faixa de {quantidade}; usando a próxima ({f.quantidade} un)"
        f = pagina.faixas[-1]
        return f, f"acima da maior faixa ({f.quantidade} un) — avaliar múltiplos pedidos"
