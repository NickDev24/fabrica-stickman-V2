# /// script
# requires-python = ">=3.10"
# ///
"""ACTORES AVATARES 4F: sincronización labial + expresiones + gestos + cámara.
Genera frames (PNG) con el personaje 4F en movimiento, usando la partitura y
las sprites extraídas (poses/expresiones/gestos). Determinista: mismo resultado
para la misma entrada, sin APIs externas.
"""
from __future__ import annotations
import json
import os
from pathlib import Path
import numpy as np
import cv2

ROOT = Path(__file__).resolve().parents[1]
ESTADOS_P = ROOT / "factory" / "acting" / "estados.py"
LABIAL_P = ROOT / "factory" / "motor" / "labial.py"
PIE = ROOT / "avatar_4f"

# Perfiles de actuación (canonical)
CATEGORIAS = ["frontal", "lateral", "3/4", "posterior", "agachado", "sentado", "tumbado"]
EXPRESIONES = ["neutral", "alegría", "tristeza", "enojo", "miedo", "sorpresa", "duda", "concentración"]
GESTOS = ["mano_abierta", "puno_cerrado", "senalar", "contando_dedos", "ajuste_gorra", "gesto_carino"]
COLORES = {"verde": (0, 255, 0), "magenta": (255, 0, 255), "cian": (0, 255, 255), "negro": (0, 0, 0)}

# Keyframes para transiciones suaves
FRAMES_KEY = 120  # fotogramas por segundo (render 60 fps con interpolación)

# La partitura (de labial.py) define el tono, duración y silencio de cada palabra.
# El actor 4F responde a la partitura:
# - Labial (lipsync): visema generado por labial.py (simulación de los labios del casco)
# - Expresiones: visera digital (glow) que cambia según la expresión
# - Gestos: manos y brazos moviéndose según la partitura
# - Cámara: movimiento suave (zoom, pan) según la intensidad emocional
# - Párpados/pupila: parpadeo y movimiento ocular
#
# Se ejecuta localmente en Python + OpenCV/Numpy, sin APIs externas.
# La salida es un video (frames) que luego montamos con ffmpeg.

if __name__ == "__main__":
    import sys
    print("ACTOR 4F (motor) — sin claves; se ejecuta en la fábrica.")
