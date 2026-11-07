"""Descubrimiento de fuentes: URLs de Wikipedia, consultas y diversidad de dominios.

Regresión original: URLs bien formadas (404 por %2B). Ampliado 2026-11-07: el
gate 1 exige 2+ dominios independientes por afirmación y los lotes morían casi
todo en wikipedia.org. Se fijan las dos palancas: referencias primarias de
Wikipedia y no descartar una fuente sólo porque rechaza HEAD.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pipeline.stages import descubrir as d  # noqa: E402

RESP = {"query": {"search": [
    {"title": "Elecciones intermedias en los Estados Unidos"},
    {"title": "2026 United States elections"},
]}}


class _Resp:
    def json(self):
        return RESP


def test_wikipedia_nunca_emite_mas_en_las_urls(monkeypatch):
    monkeypatch.setattr(d.requests, "get", lambda *a, **k: _Resp())
    urls = [u for u, _t in d._wikipedia("elecciones")]
    assert urls, "esperaba resultados mockeados"
    for u in urls:
        assert "+" not in u
        assert " " not in u
        assert "%20" not in u
        assert "%2B" not in u
    assert any(u.startswith("https://en.wikipedia.org/wiki/2026_United_States_elections")
               for u in urls)


def test_fallback_sin_red_devuelve_la_consulta(monkeypatch):
    monkeypatch.setattr(d.llm, "chat", lambda *a, **k: "")  # sin JSON útil
    qs = d._queries("tema x", "ep-test")
    assert qs == ["tema x", "tema x informe oficial", "tema x official report"]


def test_queries_dedup_y_recorte(monkeypatch):
    monkeypatch.setattr(d.llm, "chat",
                        lambda *a, **k: '{"queries":["uno", "dos", "", "tres", "cuatro", "cinco", "seis"]}')
    qs = d._queries("tema x", "ep-test")
    # 5 del LLM (la sexta se recorta) + las 2 institucionales que nunca se pierden
    assert qs[:5] == ["uno", "dos", "tres", "cuatro", "cinco"]
    assert "seis" not in qs
    assert qs[-2:] == ["tema x informe oficial", "tema x official report"]


class _Respuesta:
    def __init__(self, datos):
        self._datos = datos

    def json(self):
        return self._datos


def test_referencias_wikipedia_trae_primarias_y_descarta_ruido(monkeypatch):
    enlaces = [
        "https://www.fbi.gov/news/story/robo",
        "https://commons.wikimedia.org/wiki/File:Robo.jpg",
        "https://es.wikipedia.org/wiki/Otro_articulo",
        "https://www.facebook.com/post/1",
        "https://www.museo.org/informe.pdf",
        "https://apnews.com/article/robo",
    ]
    monkeypatch.setattr(d.requests, "get", lambda *a, **k: _Respuesta(
        {"parse": {"externallinks": enlaces}}))
    out = [u for u, _ in d._referencias_wikipedia(
        "https://es.wikipedia.org/wiki/Robo_al_museo")]
    assert out == ["https://www.fbi.gov/news/story/robo", "https://apnews.com/article/robo"]


def test_viable_cae_a_get_cuando_head_falla(monkeypatch):
    llamadas = []

    class _R:
        headers = {"content-type": "text/html; charset=utf-8"}

    def falso(url, **kw):
        llamadas.append(kw.get("method"))
        if kw.get("method") == "HEAD":
            raise d.requests.RequestException("405")
        return _R()

    monkeypatch.setattr(d.web, "obtener", falso)
    assert d._viable("https://www.fbi.gov/x") is True
    assert llamadas == ["HEAD", None]


def test_queries_agrega_pedidos_institucionales(monkeypatch):
    monkeypatch.setattr(d.llm, "chat", lambda *a, **k: (
        '{"queries": ["midterms 2026", "elecciones 2026", "senado 2026", '
        '"house 2026", "congreso 2026"]}'))
    qs = d._queries("midterms 2026", "slug")
    assert any("informe oficial" in q for q in qs)
    assert any("official report" in q for q in qs)
    assert len(qs) <= 7
