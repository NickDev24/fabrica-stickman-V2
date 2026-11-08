"""Protocolos virales expertos (factory/validacion_viral): control determinista.

Sin red, sin LLM: sólo las verificaciones de control que no requieren juicio semántico
profundo (emoción por palabras clave, recompensa reutilizando gate_bucles, estimulación
visual por metadata de render, estructura del cómic).
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from factory import validacion_viral as VV  # noqa: E402
from pipeline import gates  # noqa: E402


def _script_viral() -> str:
    return (
        "Pero el miedo los paralizó. Y el asombro los siguió. Lo extraño me persigue. ... "
        "La verdad era peor de lo que imaginábamos."
    )


def test_gate_emocion_universal_detecta_miedo_y_asombro():
    assert VV.gate_emocion_universal(_script_viral()) == []
    assert VV.gate_emocion_universal("Hablamos de turnos y horarios sin emoción.") != []


def test_gate_recompensa_narrativa_reutiliza_gate_bucles():
    # 3 aperturas de bucle distintas + cierre -> sin problemas (no bloquea)
    assert VV.gate_recompensa_narrativa(_script_viral()) == []
    # sin bucles detectables -> el gate de recompensa falla (bloqueante)
    assert VV.gate_recompensa_narrativa("Un hombre caminó a la nevera. Luego se durmió.") != []


def test_gate_visual_estimulante_con_render_con_movimiento():
    assert VV.gate_visual_estimulante({"beats": 168, "duracion_s": 555.5}) == []
    assert VV.gate_visual_estimulante({"beats": 2, "duracion_s": 12.0}) != []


def _paneles_viral_comicos() -> list[dict]:
    return [
        {"i": i, "rol_ritmico": rol, "narracion": "texto", "pagina": 1, "accion": "mira",
         "ancla_guion": "x"}
        for i, rol in enumerate(
            ["gancho", "contexto", "escala", "contexto", "inflexión", "remate",
             "contexto", "escala", "contexto", "inflexión", "giro", "escala",
             "contexto", "giro", "silencio"], start=1)
    ]


def test_gate_comic_estimulante_ok_con_estructura_viral():
    assert VV.gate_comic_estimulante(
        {"paneles": _paneles_viral_comicos(),
         "grillas": [[4, 4, 4], [1, 1, 1]]}) == []


def test_gate_comic_estimulante_falla_sin_hook():
    datos = {"paneles": [{"i": 1, "rol_ritmico": "contexto", "narracion": "x"}],
             "grillas": [[1]]}
    assert VV.gate_comic_estimulante(datos) != []


def test_validar_produccion_viral_retorna_ok_o_criticos():
    from pipeline.episode import Episode
    ep = Episode("pulso-el-archivo-no-olvida")
    out = VV.validar_produccion_viral(ep)
    assert isinstance(out, dict)
    assert isinstance(out.get("gates"), dict)
    assert isinstance(out.get("criticos"), list)
    assert isinstance(out.get("ok"), bool)
