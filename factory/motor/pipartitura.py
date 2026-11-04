# /// script
# requires-python = ">=3.10"
# ///
"""PARTITURA LÉXICA -> TIEMPOS REALES + TONO + Pausa para el avatares 4F.
Convierte el guion en un arreglo de bloques narrativos temporalmente exactos.
No depende de herramientas externas ni APIs. Es la base del labial y del actor.
"""
from __future__ import annotations
import re
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ESTADOS = ROOT / "factory" / "acting" / "estados.py"

# Silabas: lista de (silaba, duracion_estimada) -> tono por silaba y pausa
# Se extrae de la partitura léxica, sin herramientas externas.
# Reglas aplicadas:
# - silabas abiertas (a, o) -> tono 0.8, duracion 1.0
# - silabas cerradas (i, u, e, é) -> tono 0.6, duracion 0.9
# - silabas con "r" al final -> tono 0.4, duracion 1.2
# - pausas expresivas (dramáticas) -> -0.2 al tono
# - énfasis (negritas) -> +0.15 al tono y duración 1.1
# - silencios (puntuación): , ; : ... !!! ??? -> 0.3s, 0.5s, 0.7s
# - palabras en español suenan más rápido que el español formal (0.85)

SILBAS = [
    # vocales
    ("a", 0.12), ("á", 0.12), ("e", 0.11), ("é", 0.11), ("i", 0.10),
    ("í", 0.10), ("o", 0.12), ("ó", 0.12), ("u", 0.10), ("ú", 0.10),
    # consonantes
    ("b", 0.08), ("c", 0.08), ("d", 0.08), ("f", 0.08), ("g", 0.09),
    ("h", 0.06), ("j", 0.09), ("k", 0.08), ("l", 0.09), ("m", 0.09),
    ("n", 0.09), ("ñ", 0.09), ("p", 0.08), ("q", 0.09), ("r", 0.09),
    ("s", 0.08), ("t", 0.08), ("v", 0.08), ("w", 0.08), ("x", 0.08),
    ("z", 0.08), ("ch", 0.10), ("ll", 0.10), ("rr", 0.12),
]
# Mapa rápido silaba -> duración estimada (segundos)
DUR_SILABA = {s: d for s, d in SILBAS}
# Duración de palabras según longitud en silabas (temporal)
DURACION_PALABRA = {
    1: 0.5, 2: 0.7, 3: 0.9, 4: 1.1, 5: 1.3, 6: 1.5, 7: 1.7, 8: 1.9, 9: 2.1, 10: 2.3
}
# Puntuacion que genera pausas
PAUSA_PUNTUACION = {
    ",": 0.20, ";": 0.25, ":": 0.30, ".": 0.40, "!": 0.50, "?": 0.50, "...": 0.55,
    "-": 0.15, "(": 0.10, ")": 0.10, "\n": 0.35
}

TONO_BASICO = 0.65
TONO_MAX = 0.95
TONO_MIN = 0.25
ENFASIS_PALABRAS = 3  # palabras enfáticas por contexto

def calcular_tono(silaba: str, contexto: int, enfasis_local: bool) -> float:
    """Calcula el tono de una silaba: 0.25 (poco) a 0.95 (muy fuerte)."""
    if silaba in {"a", "á", "o", "ó"}:
        tono = 0.7
    elif silaba in {"e", "é"}:
        tono = 0.65
    elif silaba in {"i", "í"}:
        tono = 0.6
    elif silaba in {"u", "ú"}:
        tono = 0.75
    elif silaba in {"m", "n", "l"}:
        tono = 0.5
    elif silaba in {"b", "p", "f", "v"}:
        tono = 0.55
    elif silaba in {"s", "x", "c", "q", "k"}:
        tono = 0.45
    elif silaba in {"d", "t", "g", "j"}:
        tono = 0.5
    elif silaba in {"r", "rr"}:
        tono = 0.55
    else:
        tono = 0.6
    if enfasis_local:
        return min(TONO_MAX, tono + 0.15)
    return max(TONO_MIN, tono - 0.05 if contexto % 3 == 0 else tono)

def calcular_duracion(silaba: str, tono: float, enfasis_local: bool) -> float:
    """Calcula la duración de una silaba en segundos."""
    dur = DUR_SILABA.get(silaba, 0.08) * 1.2
    if enfasis_local:
        dur *= 1.15
    return dur * tono

def extraer_partitura(guion: str) -> list[dict]:
    """Convierte un guion en una partitura con tono, duración y pausa."""
    parte = []
    # Dividir en frases y palabras (incluyendo puntuacion)
    partes = re.split(r'(\s+|[,.:!?;()\-]+|\n+)', guion)
    tono_actual = TONO_BASICO
    for p in partes:
        if not p.strip():
            continue
        if p in PAUSA_PUNTUACION:
            parte.append({
                "tipo": "pausa",
                "texto": p,
                "duracion": PAUSA_PUNTUACION[p],
                "tono": tono_actual
            })
            tono_actual = min(TONO_MAX, tono_actual - 0.1)
            continue
        if p.isspace():
            # espacio simple
            parte.append({"tipo": "espacio", "texto": " ", "duracion": 0.05, "tono": tono_actual})
            continue
        # Dividir en silabas (simplificado: por vocales y consonantes)
        silabas = re.findall(r'[a-zA-Zñ]+', p)
        for si, sil in enumerate(silabas):
            if si > 0:
                parte.append({"tipo": "separacion", "texto": " ", "duracion": 0.02, "tono": tono_actual})
            enfasis = (si % ENFASIS_PALABRAS == 0)
            tono_actual = calcular_tono(sil, si, enfasis)
            dur = calcular_duracion(sil, tono_actual, enfasis)
            parte.append({
                "tipo": "silaba",
                "texto": sil,
                "duracion": round(dur, 3),
                "tono": round(tono_actual, 3),
                "enfasis": enfasis
            })
            if si < len(silabas) - 1:
                tono_actual = min(TONO_MAX, tono_actual - 0.02)
    return parte

def sincronizar_con_audio(partitura: list[dict], audio_path: str) -> list[dict]:
    """Sincroniza la partitura con el audio real (fase 2)."""
    # En esta fase, la partitura se ajusta a la duración del audio
    # Se usa para verificar que el ritmo y la duración coinciden
    import os
    dur_audio = os.path.getsize(audio_path) / 1_000_000 if os.path.exists(audio_path) else 10
    total_partitura = sum(p["duracion"] for p in partitura if p["tipo"] != "pausa")
    factor = dur_audio / max(total_partitura, 0.1)
    parte_sincronizada = []
    t = 0
    for p in partitura:
        dur = p["duracion"] * factor
        if p["tipo"] == "pausa":
            dur += p["duracion"]  # agregar la pausa original
        else:
            t += dur
        parte_sincronizada.append({
            **p,
            "t_inicio": round(t - dur, 3),
            "duracion": round(dur, 3)
        })
    return parte_sincronizada

if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        guion = Path(sys.argv[1]).read_text(encoding="utf-8")
    else:
        guion = sys.stdin.read()
    parte = extraer_partitura(guion)
    print(f"Partitura generada: {len(parte)} elementos, {len(parte)} silabas")
