"""GATE 6 (empaquetado): el título se valida y se reescribe antes de gastar render.

Diagnóstico v6: `pipeline/ideas.py` pedía "máximo 70 caracteres" al LLM y nada lo verificaba;
`gate_titulo` existía como función sin llamador. Un título de lista ("Top 10 …") o de 200
caracteres llegaba igual a YouTube, a la portada y al reel de Facebook.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from factory import parametros                      # noqa: E402
from pipeline import config, gates                  # noqa: E402
from pipeline.episode import Episode                # noqa: E402
from pipeline.stages import guion as G              # noqa: E402

BUENO = "El stickman que firmó un préstamo que no podía pagar y lo perdió todo"


def test_la_ventana_de_caracteres_sale_de_la_config():
    assert parametros.rango_titulo() == (45, 70)


@pytest.mark.parametrize("titulo", [
    "Top 10 deudas que la gente ignora",
    "Increíble",
    "¿Sabías que la SEC ignoró ocho años las pruebas de un fraude que terminó en 2008 y "
    "destruyó los ahorros de miles de familias en todo el país?",
])
def test_gate_titulo_apesta_lo_que_apesta(titulo):
    assert gates.gate_titulo(titulo, *parametros.rango_titulo())


def test_el_buen_titulo_pasa():
    assert gates.gate_titulo(BUENO, *parametros.rango_titulo()) == []


@pytest.fixture
def ep(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "PROJECTS", tmp_path)
    return Episode.create("prueba-titulo", "Top 5 deudas", "finanzas")


def test_asegurar_titulo_reescribe_y_lo_persiste(ep, monkeypatch):
    """El título nuevo tiene que quedar en episode.json: publicación y portada leen de ahí."""
    called = {"n": 0}

    def fake_chat(messages, **kw):
        called["n"] += 1
        return f'  "{BUENO}"  \n'

    monkeypatch.setattr(G.llm, "chat", fake_chat)
    assert G.asegurar_titulo(ep, ep.read_state()["title"], "ángulo") == BUENO
    assert ep.read_state()["title"] == BUENO
    assert called["n"] == 1


def test_sin_llm_no_se_deja_passar_un_titulo_invalido(ep, monkeypatch):
    def boom(messages, **kw):
        raise RuntimeError("sin cuota")

    monkeypatch.setattr(G.llm, "chat", boom)
    with pytest.raises(SystemExit):
        G.asegurar_titulo(ep, "Top 5 deudas", "ángulo")


def test_un_titulo_valido_no_gasta_llm(ep, monkeypatch):
    def boom(messages, **kw):
        raise AssertionError("no hay que reescribir lo que ya está bien")

    monkeypatch.setattr(G.llm, "chat", boom)
    assert G.asegurar_titulo(ep, BUENO, "ángulo") == BUENO
