# /// script
# requires-python = ">=3.10"
# ///
"""MOTOR DE CÓMO RESPONDEN EL ACTOR Y EL SONIDO AL GUION DE LOS DATOS.

Establece las reglas y la codificación de cómo responde el actor 4F al guion:
respuesta emocional, ritmo, pausa, tono, énfasis.
"""
from __future__ import annotations
import re
import json
from pathlib import Path

# Codificación de emociones
EMOCIONES = {
    "miedo": 0.3,
    "sorpresa": 0.6,
    "alegría": 0.8,
    "enojo": 0.7,
    "tristeza": 0.4,
    "concentración": 0.65,
    "neutral": 0.1,
    "duda": 0.5,
    "pelea": 0.9,
    "info": 0.55,
    "pausa": 0.1,
    "retroceso": 0.3,
    "no": 0.6,
    "misión": 0.5,
    "sobrevivencia": 0.8,
    "salida": 0.75,
}

# Reglas de emoción para el actor
def calcular_emocion(guion: str) -> float:
    """Calcula la emoción del guion en un punto dado."""
    if guion == "pausa":
        return 0.2
    if guion == "no":
        return 0.6
    if guion == "corre":
        return 0.85
    if "peligro" in guion:
        return 0.7
    if "mata" in guion:
        return 0.8
    if "huye" in guion:
        return 0.75
    if "espera" in guion:
        return 0.25
    if "ctrl" in guion:
        return 0.35
    if "daño" in guion:
        return 0.6
    if "sufre" in guion:
        return 0.55
    if "vida" in guion:
        return 0.5
    if "salva" in guion:
        return 0.65
    if "haz" in guion:
        return 0.7
    if "golpea" in guion:
        return 0.7
    if "respira" in guion:
        return 0.5
    if "huir" in guion:
        return 0.8
    if "lucha" in guion:
        return 0.8
    if "busca" in guion or "buscando" in guion:
        return 0.55
    return 0.3

# Reglas de ritmo y tono del actor base (sin tierra)
# Usa aspectos de personalidad para el actor 4F
ACT_NARRATOR = {
    "persona": "Narrator",
    "estilo": "neutral",
    "rhythm": 0.5,  # 0.2 = rápido, 0.8 = lento
    "pause": 0.3,  # segundos
}

# Guion de ejemplo: "El sistema detecta patrones de datos..."
# Reglas aplicadas:
# - El sistema detecta patrones de datos (información) -> tono más neutro
# - "El sistema" -> tono de inicio (establecer contexto)
# - "detecta" -> enfoque en la acción
# - "patrones" -> énfasis en el término técnico
# - "de" -> conectivo
# - "datos" -> énfasis en la clave del mensaje
def calcular_ritmo(guion: str) -> float:
    """Calcula el ritmo del guion (0.2 = rápido, 0.8 = lento)."""
    # El sistema detecta patrones de datos (0.5)
    if "patrones de datos" in guion:
        return 0.5
    if "sensor" in guion or "sensor" in guion.lower():
        return 0.45
    if "computa" in guion or "procesa" in guion:
        return 0.5
    if "pausa" in guion or "silencio" in guion:
        return 0.2
    if "alerta" in guion:
        return 0.6
    if "emergencia" in guion or "peligro" in guion:
        return 0.7
    return 0.5

# Semáforo emocional:este negro
def calcular_tono(guion: str, emocion: float) -> float:
    """Calcula el tono del guion según la emoción."""
    if emocion < 0.3:
        return 0.4
    if emocion < 0.5:
        return 0.55
    if emocion < 0.7:
        return 0.7
    return 0.85

# Reglas de pausa
def pausa_emocional(emocion: float) -> float:
    """Calcula la pausa emocional según la emoción."""
    if emocion > 0.7:
        return 0.2
    if emocion > 0.5:
        return 0.15
    return 0.1

# Guion del actor: aplicar reglas de tono, ritmo y pausa
def aplicar_reglas(guion: str) -> dict:
    """Aplica las reglas de tono, ritmo y pausa al guion."""
    emocion = calcular_emocion(guion)
    ritmo = calcular_ritmo(guion)
    tono = calcular_tono(guion, emocion)
    pausa = pausa_emocional(emocion)
    return {
        "emocion": emocion,
        "ritmo": ritmo,
        "tono": tono,
        "pausa": pausa,
        "guion": guion,
    }

if __name__ == "__main__":
    # Aplicar reglas al guion de ejemplo
    guion = "El sistema detecta patrones de datos."
    reglas = aplicar_reglas(guion)
    print("Reglas aplicadas:", json.dumps(reglas, indent=2))
