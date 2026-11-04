"""Regresión del lector de fuentes (pipeline.web).

Pruebas sin red: el HTML se arma acá. Lo que se protege es la extracción — el
extracto va crudo al prompt del LLM, y si entra el menú del sitio en lugar del
artículo, el fact-check alucina sobre publicidad.
"""
from __future__ import annotations

import pytest

from pipeline import web

BASURA = """
<html><body>
<nav>Menú Inicio Contacto Boletín Suscribite</nav>
<div class="cookie">You are using an outdated browser. Please upgrade your browser.</div>
<main><article>
""" + "El glaciar retrocedió once kilómetros entre 1998 y 2020 según la campaña de relevamiento. " * 12 + """
</article></main>
<footer>Copyright 2026 Todos los derechos reservados</footer>
</body></html>
"""


def test_extrae_el_articulo_no_el_menu():
    t = web.texto(BASURA)
    assert "glaciar retrocedió" in t
    assert "outdated browser" not in t
    assert "Suscribite" not in t
    assert "Copyright" not in t


def test_respeta_el_tope_de_caracteres():
    assert len(web.texto(BASURA, limite=300)) <= 300


def test_sin_article_cae_al_body():
    t = web.texto("<html><body><p>" + "texto útil. " * 100 + "</p></body></html>")
    assert "texto útil." in t


def test_enlaces_por_selector():
    html = '<ul><li><a class="result-link" href="https://a.gov/x">x</a><a href="/rel">y</a></li></ul>'
    assert web.enlaces(html, "a.result-link") == ["https://a.gov/x"]


def test_obtener_traduce_error_de_cliente(monkeypatch):
    """curl_cffi lanza sus propias excepciones; quien llama sólo conoce RequestException."""
    def revienta(*a, **k):
        raise RuntimeError("curl: (28) Operation timed out")
    monkeypatch.setattr(web._curl, "request", revienta)
    with pytest.raises(web.requests.RequestException):
        web.obtener("https://fuente.test/articulo")


def test_obtener_no_devuelve_un_4xx_silencioso(monkeypatch):
    class R:
        status_code = 403
        headers = {"content-type": "text/html"}
        text = "<html>acceso denegado</html>"
    monkeypatch.setattr(web._curl, "request", lambda *a, **k: R())
    with pytest.raises(web.requests.RequestException):
        web.obtener("https://fuente.test/articulo")


def test_sin_scrapling_sigue_legible(monkeypatch):
    """El fallback regex es viejo pero es lo que sostiene una corrida si el paquete falta."""
    monkeypatch.setattr(web, "DISPONIBLE", False)
    t = web.texto(BASURA)
    assert "glaciar retrocedió" in t
