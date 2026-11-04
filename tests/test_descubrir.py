"""_descubrir: URLs de Wikipedia bien formadas (regresión del 404 por %2B)."""
from __future__ import annotations

import json
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
    assert qs == ["tema x"]


def test_queries_dedup_y_recorte(monkeypatch):
    monkeypatch.setattr(d.llm, "chat",
                        lambda *a, **k: '{"queries":["uno", "dos", "", "tres", "cuatro", "cinco", "seis"]}')
    qs = d._queries("tema x", "ep-test")
    assert qs[0] == "uno" and qs[-1] == "seis"
    assert len(qs) <= 5
