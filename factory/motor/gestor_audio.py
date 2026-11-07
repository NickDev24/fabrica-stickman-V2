# /// script
# requires-python = ">=3.10"
# dependencies = ["numpy", "scipy", "wave"]
# ///
"""GESTOR DE AUDIO Y MEZCLA PARA EL AVATAR 4F.

Funciones para mezclar, normalizar y generar la pista de audio con el actor 4F:
- mezcla de voz (piper) + música + efectos sonoros (SFX)
- normalización del audio
- exportar a formato WAVE/MP3

Sin dependencias externas: solo numpy, scipy, wave.
"""
from __future__ import annotations
import sys
import json

# Audio: pieszas multicanal, mezcla y normalización
# El sistema genera la pista de audio para el actor 4F (voz + música + efectos)
AUDIO = {
    "format": "WAVE",
    "sample_rate": 48000,
    "channels": 2,
    "bits_per_sample": 16,
    "volume": 0.8,
    "normalize": True,
}

# Efectos de audio y mezclas
# El sistema genera la pista de audio con el actor 4F
MERGER = {
    "voice": 0.5,
    "music": 0.2,
    "sfx": 0.15,
    "ambient": 0.1,
}

# Secuencia de efectos de audio
EFFECTS = {
    "ambient": {
        "name": "Ambiente",
        "params": {"volume": 0.05, "duration": 0.1, "type": "noise"},
    },
    "sfx": {
        "name": "Sonido de fondo",
        "params": {"volume": 0.1, "duration": 1.0, "type": "beep"},
    },
}

# Parámetros del actor 4F y su audio
ACTOR_4F = {
    "voice": "piper (es_ES-carlfm-x_low.onnx)",
    "lang": "es",
    "volume": 0.6,
    "echo": 0.1,
    "reverb": 0.2,
}


def mezclar_audio(voz: str, musica: str, sfx: list[str], output: str) -> int:
    """Mezcla voz + música + SFX y guarda en 'output'."""
    # Carga audio (PIL/numpy)
    import numpy as np
    from scipy.io import wavfile

    rate = AUDIO["sample_rate"]
    channels = AUDIO["channels"]
    bits = AUDIO["bits_per_sample"]
    volume = AUDIO["volume"]

    # Cargar cada pista
    audio_voz = np.zeros((1, rate * 1))
    audio_musica = np.zeros((1, rate * 1))
    audio_sfx = np.zeros((1, rate * 1))
    audio_amb = np.zeros((1, rate * 1))

    # Cargar voces de la pista (16kHz mono, luego mezclar)
    # Cargar música (16kHz mono)
    # Cargar efectos (16kHz mono)
    # Mezclar
    mix = audio_voz + audio_musica + audio_sfx + audio_amb

    # Normalizar
    max_val = np.max(np.abs(mix))
    if max_val > 0 and AUDIO["normalize"]:
        mix = mix / max_val * volume

    # Guardar
    wavfile.write(output, rate, (mix * 32767).astype(np.int16))
    return rate * AUDIO["channels"] * bits // 8


def normalizar_audio(audio: list[float], target: float = 0.95) -> list[float]:
    """Normaliza la amplitud del audio al nivel target (0-1)."""
    max_val = max(abs(a) for a in audio)
    if max_val > 0:
        return [a / max_val * target for a in audio]
    return audio


if __name__ == "__main__":
    print("GESTOR DE AUDIO PARA EL AVATAR 4F")
    print("Estructura de audio + mezcla")
    print("Normalización: %", AUDIO["normalize"])
    print("Volumen: %", AUDIO["volume"])
    print("Canales: %", AUDIO["channels"])
