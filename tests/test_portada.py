"""Portada scroll-stop: el texto es la PREGUNTA gancho, ≤6 palabras, 2 líneas."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pipeline.stages.captacion import _texto_portada_de  # noqa: E402


def test_usa_la_pregunta_del_guion_recortada_a_6_palabras():
    script = ("# Título\n\n"
              "¿Por qué no recordás nada de tu infancia temprana ni un segundo?\n\n"
              "El resto del guion no se usa para el texto de portada.")
    txt = _texto_portada_de(script, "Algún otro título")
    assert len(txt.splitlines()[0].split()) <= 6
    assert txt.splitlines()[0].startswith("Por qué")


def test_si_el_guion_no_abre_con_pregunta_cae_al_titulo():
    script = "# T\n\nLa SEC tuvo las pruebas y no miró.\n\nresto"
    txt = _texto_portada_de(script, "¿Quién apagó su vida por dentro?")
    primera_linea = txt.splitlines()[0]
    assert "Quién apagó" in primera_linea
    assert "SEC" not in txt


def test_sin_pregunta_ni_titulo_devuelve_marca():
    assert _texto_portada_de("", "") == "Pulso Curioso"
