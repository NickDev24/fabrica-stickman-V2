"""Lectura de páginas para la etapa de investigación.

Scrapling (BSD-3) parsea con lxml y extrae por selectores; el regex que sacaba
etiquetas terminaba metiendo banners, JS inline y basura de <noscript> en el
prompt del LLM. curl_cffi (MIT) presta la huella TLS de Chrome: es lo que evita
el 403 del sitio que filtra clientes "no-navegador".

Sin navegador: Playwright/Patchright/Camoufox piden un Chromium de ~300 MB y
1 GB por pestaña, y esta máquina son 2 núcleos y 11 GB compartidos con el render
(ver VIABILIDAD.md). Si falta alguno de los dos paquetes, se vuelve al camino
viejo de requests + regex, que es lento pero nunca rompió una corrida.
"""
from __future__ import annotations

import re

import requests

try:
    from curl_cffi import requests as _curl
    from scrapling.parser import Selector as _Selector
    DISPONIBLE = True
except ImportError:
    _curl = _Selector = None
    DISPONIBLE = False

IMPERSONATE = "chrome"
UA_VIEJO = "Mozilla/5.0 (X11; Linux x86_64)"
MAX_EXCERPT_CHARS = 6000
# lo que un lector no quiere leer nunca
_SALTAR = ("script", "style", "noscript", "nav", "footer", "header", "aside",
           "form", "svg", "iframe")
_CONTENIDO = ("article", "main", "[role=main]", "body")


def obtener(url: str, *, timeout: int = 30, params: dict | None = None,
            data: dict | None = None, method: str | None = None):
    """Petición y respuesta cruda. Todo fallo de red se traduce a RequestException.

    Traducir es el punto: quien llama a research/descubrir ya captura
    requests.RequestException, y curl_cffi lanza su propia jerarquía de errores.
    Sin esto, un timeout de una fuente muerta mataría la corrida entera.
    """
    metodo = method or ("POST" if data is not None else "GET")
    try:
        if DISPONIBLE:
            r = _curl.request(metodo, url, params=params, data=data,
                              impersonate=IMPERSONATE, timeout=timeout,
                              allow_redirects=True)
        else:
            r = requests.request(metodo, url, params=params, data=data,
                                 timeout=timeout, headers={"User-Agent": UA_VIEJO})
    except requests.RequestException:
        raise
    except Exception as exc:
        raise requests.RequestException(f"{exc.__class__.__name__}: {exc}") from exc
    if r.status_code >= 400:
        raise requests.HTTPError(f"HTTP {r.status_code}", response=r)
    return r


def _limpio(texto: str) -> str:
    texto = re.sub(r"\s+", " ", texto)
    # sólo imprimibles: sin basura binaria hacia el LLM
    return "".join(c for c in texto if c.isprintable() or c in " \n")


def _por_regex(html: str) -> str:
    html = re.sub(r"(?is)<(script|style|noscript)[^>]*>.*?</\1>", " ", html)
    return _limpio(re.sub(r"(?s)<[^>]+>", " ", html))


def texto(html: str, limite: int = MAX_EXCERPT_CHARS) -> str:
    """Texto legible de una página: primero el contenedor de contenido, no el chrome."""
    if DISPONIBLE:
        sel = _Selector(html)
        for css in _CONTENIDO:
            nodo = sel.css(css).first
            if nodo is None:
                continue
            txt = _limpio(str(nodo.get_all_text(separator=" ", strip=True,
                                                ignore_tags=_SALTAR)))
            if len(txt) >= 400 or css == _CONTENIDO[-1]:
                return txt[:limite]
    return _por_regex(html)[:limite]


def enlaces(html: str, css: str, atributo: str = "href") -> list[str]:
    """Valores de un atributo para un selector.

    Sin scrapling no hay traducción de CSS a regex: se devuelve TODO el atributo
    del documento, que es el comportamiento viejo de descubrir.py (sus filtros de
    dominio hacen el resto).
    """
    if DISPONIBLE:
        return [str(nodo.attrib.get(atributo, ""))
                for nodo in _Selector(html).css(css)
                if nodo.attrib.get(atributo)]
    return re.findall(rf'{atributo}="([^"]+)"', html)


def pares(html: str, css: str, atributo: str = "href") -> list[tuple[str, str]]:
    """(valor del atributo, texto del enlace) por coincidencia.

    El texto es lo que hace falta para saber de qué trata un resultado de búsqueda:
    por host no se puede distinguir una fuente pertinente de la home de Medicare.
    """
    if not DISPONIBLE:
        return []
    out = []
    for nodo in _Selector(html).css(css):
        valor = nodo.attrib.get(atributo)
        if valor:
            out.append((str(valor), " ".join(str(nodo.text or "").split())))
    return out
