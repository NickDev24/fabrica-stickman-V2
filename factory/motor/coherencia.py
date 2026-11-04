# /// script
# requires-python = ">=3.10"
# ///
"""COHERENCIA EMOCIONAL DEL ACTOR 4F.

Verifica que las emociones, gestos, labial y cámara estén coherentes con el
guion del actor, y que el actor 4F responda de forma coherente.
"""
from __future__ import annotations
import json
import sys

# Coherencia emocional del actor
COHERENCIA_ACTOR_4F = {
    "identity": "4F",
    "mode": "coherencia",
    "expressividad": {
        "miedo": 0.6,
        "sorpresa": 0.7,
        "alegría": 0.75,
        "enojo": 0.7,
        "tristeza": 0.55,
        "concentración": 0.6,
        "neutral": 0.3,
        "duda": 0.5,
    },
    "gestos": ["mano_abierta", "puno_cerrado", "senalar", "contando_dedos", "ajuste_gorra", "gesto_carino"],
    "lipsync": "labial (simulada)",
    "cámara": ["zoom narrativo", "movimiento lateral suave", "parpadeo", "respiración"],
}

# Reglas de coherencia para el actor 4F
def verificar_coherencia(guion: str, emocion: float, tono: float, ritmo: float) -> dict:
    """Verifica que la emoción, tono y ritmo del guion sean coherentes para el actor 4F."""
    errores = []
    if guion == "no":
        if emocion < 0.4:
            errores.append("Emoción muy baja para 'no'")
    if "mata" in guion or "peligro" in guion:
        if emocion < 0.6:
            errores.append("Emoción muy baja para peligro")
    if "bueno" in guion or "si" in guion:
        if emocion > 0.5:
            errores.append("Emoción muy alta para algo positivo")
    if emocion < 0.2 and tono > 0.7:
        errores.append("Tonos muy alta para emoción baja")
    if emocion > 0.8 and ritmo > 0.6:
        errores.append("Ritmo demasiado rápido para emoción extrema")

    return {
        "coherente": len(errores) == 0,
        "errores": errores,
        "emocion": emocion,
        "tono": tono,
        "ritmo": ritmo,
    }

if __name__ == "__main__":
    print("COHERENCIA EMOCIONAL DEL ACTOR 4F")
    print("Verificación de coherencia entre emoción, labial, gestos y cámara")
    print("Personaje: 4F")

    guion = "El sistema detecta patrones de datos."
    emocion = 0.5
    tono = 0.65
    ritmo = 0.5
    res = verificar_coherencia(guion, emocion, tono, ritmo)
    print(json.dumps(res, indent=2))
