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
from ..gates import GateFailure

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

# Ruido que una corrida real metió como "fuente documental" (medido 2026-11-05: el episodio
# del Congreso terminó con merriam-webster.com/dictionary/u, dictionary.cambridge.org y
# simple.wikipedia.org/wiki/U). Son páginas de una letra, diccionarios y granjas de estudio.
BASURA = re.compile(
    r"(?:^|\.)(?:"
    r"merriam-webster\.com|dictionary\.com|dictionary\.cambridge\.org|dictionary\.bubble\.com"
    r"|thefreedictionary\.com|wordreference\.com|urbandictionary\.com|dict\.cc|collinsdictionary\.com"
    r"|wiktionary\.org|simple\.wikipedia\.org|genius\.com|imdb\.com|quizlet\.com|coursehero\.com"
    r"|studocu\.com|chegg\.com|cliffsnotes\.com|sparknotes\.com|gradesaver\.com"
    r"|pinterest\..*|facebook\.com|instagram\.com|tiktok\.com|x\.com|twitter\.com"
    r")")


def _basura(url: str, titulo: str) -> bool:
    """Host de relleno o página sin cuerpo temático (una letra, un dígito, vacío)."""
    if BASURA.search(urlparse(url).netloc):
        return True
    if len(re.sub(r"[^A-Za-zÀ-ÿ0-9]", "", titulo)) <= 3:
        return True
    ultimo = [s for s in urlparse(url).path.split("/") if s]
    return bool(ultimo) and len(ultimo[-1]) <= 2 and not ultimo[-1].isdigit()


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
    # Una consulta de relleno ("u", "midterm", una sola palabra) devuelve diccionarios y
    # páginas de una letra: se descarta antes de gastar 3 búsquedas y 7 fetch en basura.
    # El piso de 2 raíces largas es lo que no rompe el fallback de temas cortos.
    utiles = [q for q in limpios if len(_tokens(q)) >= 2]
    base = (utiles or limpios)[:5] or [historia]
    # Dos consultas institucionales fijas: el modelo tiende a proponer variantes del
    # mismo enfoque y con eso los lotes quedaban sin fuentes primarias que cumplan el
    # gate de 2+ dominios por afirmación. No dependen del LLM (siempre suman).
    for q in (f"{historia} informe oficial", f"{historia} official report"):
        if q not in base:
            base.append(q)
    return base[:7]


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


def _referencias_wikipedia(url: str, limite: int = 12) -> list[tuple[str, str]]:
    """Enlaces externos citados por una página de Wikipedia (fuentes primarias).

    Es la palanca contra el sesgo de dominio: el descubrimiento terminaba con casi
    todo en wikipedia.org, y el gate 1 exige 2+ dominios independientes por
    afirmación. Las referencias de la enciclopedia son justamente los informes,
    agencias y museos que el artículo usa para afirmar lo que afirma.
    """
    m = re.match(r"https?://([a-z]{2})\.wikipedia\.org/wiki/(.+)$", url)
    if not m:
        return []
    sitio, titulo = m.group(1), unquote(m.group(2)).replace("_", " ")
    try:
        r = requests.get(f"https://{sitio}.wikipedia.org/w/api.php",
                         params={"action": "parse", "page": titulo,
                                 "prop": "externallinks", "format": "json",
                                 "redirects": 1},
                         headers=UA, timeout=20)
        enlaces = r.json().get("parse", {}).get("externallinks", []) or []
    except (requests.RequestException, ValueError, AttributeError):
        return []
    out: list[tuple[str, str]] = []
    vistos: set[str] = set()
    for u in enlaces:
        u = str(u).strip()
        host = urlparse(u).netloc.lower()
        if not u.startswith("https://") or u in vistos:
            continue
        if any(w in host for w in ("wikipedia.org", "wikimedia.org", "wikidata.org")):
            continue
        if re.search(r"\.(?:pdf|docx?|pptx?|xlsx?|zip|jpe?g|png|gif|svg)$",
                     urlparse(u).path, re.I):
            continue  # research sólo lee HTML: un PDF no es fuente utilizable
        if re.match(r"^(?:www\.)?(?:facebook|instagram|twitter|x|tiktok|youtube|"
                    r"pinterest|reddit)\.", host):
            continue
        vistos.add(u)
        out.append((u, ""))
        if len(out) >= limite:
            break
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
    except requests.RequestException:
        # Muchos servidores rechazan HEAD (405/403) pero entregan el GET que research
        # usa de verdad. Descartar por el HEAD era perder fuentes válidas.
        try:
            r = web.obtener(url, timeout=15)
        except requests.RequestException:
            return False
    ctype = r.headers.get("content-type", "")
    return "html" in ctype or "text" in ctype or ctype == ""


def descubrir(ep, historia: str, max_urls: int = 10, consulta: str | None = None) -> list[str]:
    vistos: set[str] = set()
    candidatos: list[tuple[int, str, int]] = []
    # Se busca por el TEMA verificado (`consulta`), no por el título-gancho: el gancho
    # puede ser una pregunta que no devuelve ni una fuente aunque el tema tenga diez.
    texto = (consulta or "").strip() or historia
    for q in _queries(texto, ep.slug):
        for u, titulo in _ddg(q) + _wikipedia(q) + _bing(q):
            u = u.split("#")[0]
            if u in vistos:
                continue
            vistos.add(u)
            host = urlparse(u).netloc
            if _basura(u, titulo):
                continue
            relevancia = _relevancia(q + " " + texto, titulo, u)
            score = 3 * relevancia + (2 if PRESTIGIO.search(host) else 1)
            if "wikipedia.org" in host:
                score -= 1  # útil pero no cuenta como fuente primaria institucional
            candidatos.append((score, u, relevancia))

    # Wikipedia cita fuentes primarias: expandir las 3 páginas con mejor puntaje suma
    # dominios independientes (informes, agencias, museos) que el gate 1 necesita.
    candidatos.sort(key=lambda x: -x[0])
    expandidas = 0
    for _, u, _ in list(candidatos[:12]):
        if "wikipedia.org" not in urlparse(u).netloc:
            continue
        for ru, rt in _referencias_wikipedia(u):
            if ru in vistos:
                continue
            vistos.add(ru)
            if _basura(ru, rt or "referencia"):
                continue
            host = urlparse(ru).netloc
            relevancia = _relevancia(texto, rt or "", ru)
            candidatos.append((3 * relevancia + (2 if PRESTIGIO.search(host) else 1),
                               ru, relevancia))
        expandidas += 1
        if expandidas >= 3:
            break
    candidatos.sort(key=lambda x: -x[0])

    def _tomar(pool: list[tuple[int, str, int]], techo: int) -> list[str]:
        out: list[str] = []
        conteo_do: dict[str, int] = {}
        for _, u, _r in pool:
            if len(out) >= techo:
                break
            # regla editorial: un dominio no puede llenar la lista; el gate de fuentes
            # exige independencia, así que la descubierta mezcla dominios a propósito
            host = urlparse(u).netloc
            if conteo_do.get(host, 0) >= 2:
                continue
            if _viable(u):
                out.append(u)
                conteo_do[host] = conteo_do.get(host, 0) + 1
        return out

    # Piso de pertinencia: sin él, cualquier .gov o artículo de pago con una sola palabra
    # en común entraba como "fuente" del tema (medido: Barron's de opciones sobre oro).
    elegidas = _tomar([c for c in candidatos if c[2] >= 1], max_urls)
    if len(elegidas) < 4:
        # Temas cortos sin raíces en común con ningún título: se completa con lo mejor que
        # quedó (basura ya filtrada por host) antes de declarar el episodio inviable.
        elegidas += _tomar([c for c in candidatos if c[2] < 1 and c[1] not in elegidas],
                           4 - len(elegidas))
    if len(elegidas) < 4:
        # Rechazo de gate, no una caída de infraestructura: rc=2 y la fábrica pasa a la
        # siguiente idea en vez de reintentar la misma con backoff de 15 min.
        raise GateFailure("fuentes", [
            f"descubrir: sólo {len(elegidas)} fuentes alcanzables para '{texto}'. "
            "El pipeline no publica con investigación insuficiente (gate 1)."])
    (ep.dir / "research" / "urls.txt").write_text(
        "# autodescubierto por pipeline/stages/descubrir.py\n" + "\n".join(elegidas) + "\n",
        encoding="utf-8")
    print(f"  {len(elegidas)} fuentes descubiertas y alcanzables -> research/urls.txt")
    return elegidas
