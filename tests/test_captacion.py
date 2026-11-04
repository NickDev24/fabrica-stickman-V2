"""Regresiones de captación: selección de 2 escenas NO solapadas y CTA fijo.

No toca la red ni ffmpeg: sólo la lógica de selección por potencial de hook y el
contrato de texto del CTA (idéntico en texto y horario para las 3 piezas).
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pipeline.stages import captacion as C        # noqa: E402


def _beats(n: int = 20) -> list[dict]:
    bs = []
    for i in range(n):
        bs.append({
            "i": i, "t0": i * 3.0, "t1": i * 3.0 + 1.5, "dur_s": 1.5,
            "texto": f"frase {i}", "pop": "ALERTA" if i == 7 else "",
            "escena": "interior", "accion": ["mira", "corre", "senala", "grita"][i % 4],
            "plano": ["medio", "primer_plano", "general", "contrapicado"][i % 4],
            "mov": "push", "emocion": "neutralidad", "fx": ["flash"] if i == 7 else [],
            "segmento": i // 5, "contexto": f"El informe fue la prueba definitiva{i and ''}",
            "direccion": {"idea": f"idea {i}", "prop": f"prop {i}"},
        })
    return bs


def test_el_cta_es_unico_y_con_horario_del_capitulo():
    assert C.CTA == "Capítulo completo hoy 23:00 hs en YouTube"
    assert C.HORA_CAPITULO in C.CTA


def test_seleccion_devuelve_dos_escenas_distintas():
    a, b = C.elegir_escenas(_beats())
    assert a is not b
    assert a["i"] != b["i"]


def test_los_cortes_de_los_trailers_no_solapan():
    """Nunca el mismo cut: los t0 elegidos quedan al menos 10 s de distancia."""
    bs = _beats()
    a, b = C.elegir_escenas(bs)
    assert abs(a["t0"] - b["t0"]) >= 10.0


def test_el_hook_prefiere_climax():
    bs = _beats()
    a, b = C.elegir_escenas(bs)
    # El beat 7 tiene flash + pop + acción grita + contrapicado: hook máximo del capítulo
    assert C.score_beat(bs[7]) >= 5
    # Y entre las dos escenas elegidas tiene que estar el beat con mayor potencial
    assert bs[7]["i"] in (a["i"], b["i"])
