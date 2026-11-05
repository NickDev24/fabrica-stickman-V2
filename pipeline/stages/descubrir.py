"""Investigación autónoma: el pipeline se busca sus propias fuentes.

Dado el tema (historia), genera consultas de búsqueda, busca en DuckDuckGo/Wikipedia,
prioriza dominios de prestigio (gov/edu/instituciones científicas/medios de referencia),
verifica que las páginas existan y escribe research/urls.txt. No requiere intervención.
"""
from __future__ import annotations

import base64
import json
import re
import unicodedata
from urllib.parse import quote, quote_plus, unquote, urlparse

import requests

from .. import llm, web

UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"}

PRESTIGIO = re.compile(
    r"(?:^|\.)("
    r"sec\.gov|investor\.gov|nasa\.gov|noaa\.gov|nih\.gov|usgs\.gov|energy\.gov|nsf\.gov|loc\.gov|si\.edu"
    r"|\.gov(?:\.[a-z]{2})?|\.edu(?:\.|$)|\.ac\.[a-z]{2}|\.ac\.uk"
    r"|unesco\.org|esa\.int|cern\.eu|who\.int|nature\.com|science\.org|scientificamerican\.com"
    r"|bbc\.com|reuters\.com|ap\.org|apnews\.com|smithsonianmag\.com|britannica\.com"
    r"|phys\.org|arxiv\.org|springer\.com|wiley\.com|pnas\.org|akademia\.pe\.cr"
    r"|historia\.nar\.gov|museum\.org|encyclopedia\..*"
    r")")


def _queries(historia: str, episode: str) -> list[str]:
    prompt = (
        "Para investigar con rigor documental ESTE tema y escribir un guion verificado: "
        f"\"{historia}\". Generá 5 consultas de búsqueda (mezcla español e inglés) apuntando a "
        "fuentes primarias/institucionales (NASA, NOAA, universidades, museos, revistas "
        "científicas, agencias). Las consultas deben ser ESPECÍFICAS: incluí el año y palabras "
        "clave del suceso ('results', 'official', 'report', según corresponda); nada de una sola "
        "palabra como \"midterm\". Devolvé sólo JSON: {\"queries\":[\"...\",\"...\"]}"
    )
    answer = llm.chat([{"role": "user", "content": prompt}], max_tokens=800,
                      tag="queries", episode=episode)
    qs = None
    m = re.search(r"\{.*\}|\[.*\]", answer, re.S)
    if m:
        try:
            data = json.loads(m.group(0))
            qs = data.get("queries") if isinstance(data, dict) else data
        except (json.JSONDecodeError, AttributeError):
            qs = None
    if not qs:
        qs = [historia]
    limpios = [re.sub(r"\s+", " ", str(q)).strip() for q in qs if str(q).strip()]
    return limpios[:5] or [historia]


def _tokens(texto: str) -> set[str]:
    """Palabras significativas (>=5 letras, sin acentos) para medir de qué habla la fuente.

    Sin desacentuar, "Pandémica" nunca coincide con "pandemia" y la fuente pertinente
    pierde contra la home de un ministerio.
    """
    desaccentuada = "".join(c for c in unicodedata.normalize("NFD", texto.casefold())
                            if not unicodedata.combining(c))
    limpio = "".join(c if c.isalnum() else " " for c in desaccentuada)
    return {w for w in limpio.split() if len(w) >= 5}


def _relevancia(query: str, titulo: str, url: str) -> int:
    """Cuántas raíces de la consulta aparecen en el TÍTULO (o en el path, si no hay título).

    Antes el puntaje era sólo prestigio: un tema de zombis terminaba con Medicare y NOAA en
    las fuentes, porque cualquier .gov le ganaba a una fuente pertinente.
    Se comparan raíces de 6 caracteres y no palabras exactas: "pandemia" tiene que contar
    contra "pandemias" (medido: con coincidencia exacta el puntaje era 0 hasta para la CDC).
    """
    q = _tokens(query)
    if not q:
        return 0
    texto = titulo if len(titulo) > 8 else unquote(urlparse(url).path).replace("-", " ")
    return len({w[:6] for w in q} & {w[:6] for w in _tokens(texto)})


def _ddg(query: str) -> list[tuple[str, str]]:
    """(url, título). El título viene gratis en el HTML que ya se baja y es lo único que
    dice de qué trata el resultado: por host no se puede saber."""
    hallados: list[tuple[str, str]] = []
    for base in ("https://html.duckduckgo.com/html/", "https://lite.duckduckgo.com/lite/"):
        try:
            # curl_cffi con huella de Chrome: DDG responde 403 al cliente "python-requests".
            r = web.obtener(base, data={"q": query}, timeout=20)
        except requests.RequestException:
            continue
        pares = web.pares(r.text, "a.result-link, .result__a, a[data-testid='result-title-a']")
        if not pares:  # el DOM de DDG cambia seguido: se vuelve al barrido completo
            pares = [(u, "") for u in re.findall(r'href="(https?://[^"]+)"', r.text)
                     if u.startswith("http")]
        hallados += pares
    # desenredar redirector de ddg
    out = []
    for u, t in hallados:
        m = re.search(r"uddg=([^&]+)", u)
        out.append((unquote(m.group(1)) if m else u, t))
    return out


def _bing(query: str) -> list[tuple[str, str]]:
    """Bing como segunda vía: los resultados traen enlaces útiles de .gov/.edu/medios.

    Los href de Bing vienen envueltos en redirecciones (`/ck/a?...u=a1<base64url>`);
    se decodifica el destino real. Dominios gov/edu institucionales suelen
    alcanzables y son independientes de Wikipedia (gate 1 pide dominios distintos).
    """
    try:
        r = web.obtener("https://www.bing.com/search",
                        params={"q": query, "ensearch": "1", "setlang": "en-US",
                                "mkt": "en-US"},
                        timeout=20)
    except requests.RequestException:
        return []
    out: list[tuple[str, str]] = []
    for href in re.findall(r'<h2><a[^>]*href="([^"]+)"', r.text):
        href = href.replace("&amp;", "&")
        m = re.search(r"[?&]u=a1([^&]+)", href)
        if not m:
            continue
        try:
            b64 = m.group(1)
            b64 += "=" * (-len(b64) % 4)
            url = base64.urlsafe_b64decode(b64).decode("utf-8", "ignore")
        except Exception:
            continue
        if url.startswith("http"):
            out.append((url, ""))
    return out


def _wikipedia(query: str) -> list[tuple[str, str]]:
    """Español + inglés: la enciclopedia rinde en ambos idiomas y es la fuente más estable."""
    out: list[tuple[str, str]] = []
    for sitio in ("es.wikipedia.org", "en.wikipedia.org"):
        try:
            r = requests.get(
                f"https://{sitio}/w/api.php",
                params={"action": "query", "list": "search", "srsearch": query,
                        "srlimit": 5, "format": "json"}, headers=UA, timeout=20)
            base = f"https://{sitio}/wiki/"
            out += [(base + quote(x["title"].replace(" ", "_"), safe="_()':,&"),
                     x["title"]) for x in r.json()["query"]["search"]]
        except (requests.RequestException, KeyError):
            continue
    return out


def _viable(url: str) -> bool:
    if not url.startswith("http") or any(x in url for x in (
            "duckduckgo", "google.", ".pdf", ".doc", ".ppt", "scribd.", "youtub", ".es/scribd")):
        return False
    if not url.startswith("https"):
        return False
    try:
        # mismo cliente que research._fetch: si HEAD dice 403 con requests pelado,
        # la fuente se descartaba aunque _fetch sí pudiera leerla.
        r = web.obtener(url, method="HEAD", timeout=15)
        ctype = r.headers.get("content-type", "")
        return "html" in ctype or "text" in ctype or ctype == ""
    except requests.RequestException:
        return False


def descubrir(ep, historia: str, max_urls: int = 10) -> list[str]:
    vistos: set[str] = set()
    candidatos: list[tuple[int, str]] = []
    for q in _queries(historia, ep.slug):
        for u, titulo in _ddg(q) + _wikipedia(q) + _bing(q):
            u = u.split("#")[0]
            if u in vistos:
                continue
            vistos.add(u)
            host = urlparse(u).netloc
            relevancia = _relevancia(q + " " + historia, titulo, u)
            score = 3 * relevancia + (2 if PRESTIGIO.search(host) else 1)
            if "wikipedia.org" in host:
                score -= 1  # útil pero no cuenta como fuente primaria institucional
            candidatos.append((score, u))
    candidatos.sort(key=lambda x: -x[0])

    elegidas: list[str] = []
    conteo_do: dict[str, int] = {}
    for _, u in candidatos:
        if len(elegidas) >= max_urls:
            break
        # regla editorial: un dominio no puede llenar la lista; el gate de fuentes
        # exige independencia, así que la descubierta mezcla dominios a propósito
        host = urlparse(u).netloc
        if conteo_do.get(host, 0) >= 2:
            continue
        if _viable(u):
            elegidas.append(u)
            conteo_do[host] = conteo_do.get(host, 0) + 1
    if len(elegidas) < 4:
        raise SystemExit(f"descubrir: sólo {len(elegidas)} fuentes alcanzables para '{historia}'. "
                         "El pipeline no publica con investigación insuficiente (gate 1).")
    (ep.dir / "research" / "urls.txt").write_text(
        "# autodescubierto por pipeline/stages/descubrir.py\n" + "\n".join(elegidas) + "\n",
        encoding="utf-8")
    print(f"  {len(elegidas)} fuentes descubiertas y alcanzables -> research/urls.txt")
    return elegidas
