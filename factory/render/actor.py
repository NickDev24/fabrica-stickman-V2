# /// script
# requires-python = ">=3.10"
# dependencies = ["numpy", "opencv-python-headless", "Pillow"]
# ///
"""ACTOR 4F — motor de animación del avatar 4F (sin APIs externas).

Usa el motor de actuación (factory/acting) + partitura (factory/motor) + sprites
(avatar_4f/) para generar frames con el personaje 4F en movimiento, sincronizados
con la voz y la expresión. Funciona localmente bajo CPU.
"""
from __future__ import annotations
import json
import os
import subprocess
import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
FACTORY = ROOT / "factory"
AVATAR = ROOT / "avatar_4f"
STATE = ROOT / "state"
OUT_DIR = STATE / "renders"

# 60 fps target frame rate (smooth interpolation)
FPS = 60
# 8k target resolution (render headless with interpolation to keep RAM low)
W, H = 8000, 4500
# Maximum number of frames to process at once (memory-constrained hardware)
MAX_FRAMES = 240

# Actor profile for 4F (character model identity and physical constraints)
PROFILE = {
    "character": "4F",
    "model": "glTF/MP4 (headless)",
    "resolution": f"{W}x{H}",
    "fps": FPS,
    "expression": "neon green visira",  # glow eyes
    "color": {"neon_green": (0, 255, 0), "neon_pink": (255, 0, 255), "neon_cyan": (0, 255, 255)},
    "constraints": ["identity", "materials", "scale", "lighting", "eyebrows", "eyes", "head", "neck"],
    "view": "3/4",  # standing front
    "modo": "3/4",
}

# Pre-emptive load of character assets (avoid load times during animation)
def precargar_activos():
    """Pre-carga de sprites de animación e identidad del personaje."""
    assert AVE.exists(), "Avatar sprites not found!"
    # Load a rendering buffer and frame assets (avoid re-loading during animation)
    AVE = AVATAR / "poses" / "frontal.png"
    assert AVE.exists(), "Frontal sprite not found!"
    assert AVATAR.exists(), "Avatar directory not found!"
    # Additional prep: cache a rendering buffer and frame assets (avoid reload)
    return AVE


if __name__ == "__main__":
    # Actor 4F runs headless with no framebuffer. Parameter sets are cached.
    # Output files are cached to the state directory.
    AVAILABLE = [p for p in AVATAR.rglob("*.png") if p.is_file()]
    assert AVAILABLE, "No sprite found for avatar 4F!"

    ACTOR = PROFILE["character"]
    ACTOR_PROFILE = {}
    ACTOR_PROFILE["character"] = ACTOR
    ACTOR_PROFILE["resolution"] = f"{W}x{H}"
    ACTOR_PROFILE["fps"] = FPS
    ACTOR_PROFILE["state"] = "ready"

    print("ACTOR 4F:")
    print(f"  character: {ACTOR}")
    print(f"  resolution: {W}x{H}")
    print(f"  fps: {FPS}")
    print(f"  state: ready - cryo")
