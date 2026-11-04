"""Contrato MIXTO v9: cara (ojos+boca) sólo en primeros planos, silueta en anchos."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pipeline import imagen  # noqa: E402


def _beat(plano: str) -> dict:
    return {"escena": "pasillo", "accion": "mira", "plano": plano, "mov": "push",
            "contexto": "Parece un registro perfecto",
            "direccion": {"prop": "ledger with even returns", "acting": "mira la lupa",
                          "idea": "Parece un registro perfecto"}}


def test_plano_detallado_muestra_cara():
    p = imagen.armar_prompt_dirigido(_beat("detalle"))
    assert "oval eyes" in p
    p2 = imagen.armar_prompt_dirigido(_beat("primer_plano"))
    assert "oval eyes" in p2


def test_plano_ancho_mantiene_silueta_sin_rostro():
    for plano in ("medio", "general", "cenital"):
        p = imagen.armar_prompt_dirigido(_beat(plano))
        assert "no face" in p, plano
        assert "oval eyes" not in p, plano


def test_identidades_caben_en_la_truncacion():
    e = imagen.estilo()
    assert len(e["identidad"]) <= 95
    if e.get("identidad_cara"):
        assert len(e["identidad_cara"]) <= 95


def test_expresion_se_mapea_por_accion():
    p = imagen.armar_prompt("interior", "grita", "primer_plano")
    assert "shouting" in p
    p2 = imagen.armar_prompt("interior", "asustado", "detalle")
    assert "wide eyes" in p2


def test_prompts_no_revientan_techo_600():
    for plano in ("general", "medio", "primer_plano", "detalle"):
        assert len(imagen.armar_prompt_dirigido(_beat(plano))) <= 600
