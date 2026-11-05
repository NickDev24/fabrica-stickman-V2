"""Gancho visual: el keyframe de 0-3 s es el flash-forward a la escena más caótica.

Sin red, sin ffmpeg: sólo la lógica determinista de dirección de beats.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from factory.acting import beats as B  # noqa: E402


def test_gancho_copia_escena_del_beat_mas_intenso():
    bs = [
        {"i": 0, "t0": 0.0, "t1": 3.6, "dur_s": 3.6, "texto": "¿Por qué?",
         "pop": "", "escena": "interior", "accion": "mira", "plano": "medio",
         "mov": "fijo", "emocion": "curiosidad", "fx": [], "contexto": "¿Por qué?",
         "oracion": "¿Por qué?", "segmento": 0,
         "direccion": {"idea": "idea gancho", "prop": "prop gancho",
                        "camara": "fijo", "movimiento_local": ""}},
        {"i": 1, "t0": 3.6, "t1": 7.6, "dur_s": 4.0, "texto": "frase plana",
         "pop": "", "escena": "calle", "accion": "mira", "plano": "medio",
         "mov": "push", "emocion": "neutralidad", "fx": [], "contexto": "frase plana",
         "oracion": "frase plana", "segmento": 0},
        {"i": 2, "t0": 7.6, "t1": 11.6, "dur_s": 4.0,
         "texto": "Miles de documentos colapsaron en caos y gritos",
         "pop": "", "escena": "calle", "accion": "grita", "plano": "primer_plano",
         "mov": "push", "emocion": "tension", "fx": ["flash"],
         "contexto": "Miles de documentos colapsaron en caos y gritos",
         "oracion": "Miles de documentos colapsaron en caos y gritos", "segmento": 1},
    ]
    B.fijar_gancho_visual(bs)
    g = bs[0]
    assert g["gancho"] is True
    # el gancho ES el flash-forward: hereda escena y acción del beat más intenso
    assert g["escena"] == bs[2]["escena"]
    assert g["accion"] == bs[2]["accion"]
    assert g["plano"] in {"primer_plano", "detalle", "contrapicado", "cenital"}
    assert "flash" in g["fx"]
    assert g["mov"] in ("shake", "push")
    # el texto NARRADO no se toca: la voz sigue siendo la pregunta del guion
    assert g["texto"] == "¿Por qué?"
    assert "flashforward" in bs[0]["direccion"]["idea"]


def test_gancho_idempotente_y_no_aplica_a_un_solo_beat():
    bs1 = [dict(i=0, texto="x", gancho=True, direccion={})]
    B.fijar_gancho_visual(bs1)  # no rompe
    solo = [{"i": 0, "texto": "única", "escena": "calle", "direccion": {}}]
    B.fijar_gancho_visual(solo)
    assert solo[0].get("gancho") is True
