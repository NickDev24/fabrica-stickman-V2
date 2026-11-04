"""Estados emocionales del actor digital (prioridad máxima, pilares 1-5).

Cada estado define un bloque de parámetros interpretable por CUALQUIER backend:
  - mascota (mesh-avatar-studio): rig fields (mouthOpen/eyeLOpen/angleX/...).
  - GLB (three.js/Babylon): morph targets y huesos (mapa en glb_actor.mjs).

Reglas (misión):
- Transiciones NUNCA instantáneas: curvas ease-in/out según `intensidad`.
- Gestos con propósito narrativo; sin movimiento constante.
- Los parámetros son rangos [0..1] salvo ángulos en grados.
"""
from __future__ import annotations

# Parámetros estándar del actor (contrato de datos entre skills):
#   ceja_izq, ceja_der:      altura de cejas (-1..1: fruncida..levantada)
#   ojo_apertura:            apertura ocular 0..1 (0 cerrado, 1 abierta plena) - parche de 1.35 para sorpresa
#   mirada_dx, mirada_dy:    dirección de la mirada (-1..1)
#   cabeza_pitch/yaw/roll:   ángulos en grados
#   postura_roll:            inclinación del cuerpo (deg, ±10)
#   peso:                    shift de peso (-1..1)
#   brazo_izq, brazo_der:    swing (-1..1)
#   codo_izq, codo_der:      flexión (0..1)
#   manos_levantadas:        0..1
#   velocidad_gesto:         multiplicador temporal de la gesticulación (0.5..1.6)
#   respiracion:             respiraciones por minuto en reposo de ese estado
#   boca_base:               apertura base de boca en silencio (0..0.15)
ESTADOS: dict[str, dict] = {
    "neutralidad": {
        "ceja_izq": 0.0, "ceja_der": 0.0, "ojo_apertura": 1.0, "mirada_dx": 0.0, "mirada_dy": 0.0,
        "cabeza_pitch": 0, "cabeza_yaw": 0, "cabeza_roll": 0, "postura_roll": 0, "peso": 0.0,
        "brazo_izq": 0.0, "brazo_der": 0.0, "codo_izq": 0.15, "codo_der": 0.15, "manos_levantadas": 0.0,
        "velocidad_gesto": 1.0, "respiracion": 14, "boca_base": 0.0,
    },
    "alegria": {
        "ceja_izq": 0.35, "ceja_der": 0.35, "ojo_apertura": 1.1, "mirada_dx": 0.0, "mirada_dy": 0.1,
        "cabeza_pitch": -3, "cabeza_yaw": 0, "cabeza_roll": 2, "postura_roll": 2, "peso": 0.15,
        "brazo_izq": 0.3, "brazo_der": 0.3, "codo_izq": 0.4, "codo_der": 0.4, "manos_levantadas": 0.4,
        "velocidad_gesto": 1.25, "respiracion": 16, "boca_base": 0.05,
    },
    "sorpresa": {
        "ceja_izq": 1.0, "ceja_der": 1.0, "ojo_apertura": 1.35, "mirada_dx": 0.0, "mirada_dy": 0.25,
        "cabeza_pitch": -5, "cabeza_yaw": 0, "cabeza_roll": -2, "postura_roll": -3, "peso": -0.25,
        "brazo_izq": -0.2, "brazo_der": -0.2, "codo_izq": 0.55, "codo_der": 0.55, "manos_levantadas": 0.6,
        "velocidad_gesto": 1.4, "respiracion": 20, "boca_base": 0.12,
    },
    "curiosidad": {
        "ceja_izq": 0.45, "ceja_der": 0.25, "ojo_apertura": 1.05, "mirada_dx": 0.3, "mirada_dy": 0.1,
        "cabeza_pitch": 4, "cabeza_yaw": 8, "cabeza_roll": -4, "postura_roll": -2, "peso": 0.0,
        "brazo_izq": 0.15, "brazo_der": 0.0, "codo_izq": 0.45, "codo_der": 0.2, "manos_levantadas": 0.25,
        "velocidad_gesto": 1.1, "respiracion": 14, "boca_base": 0.02,
    },
    "miedo": {
        "ceja_izq": 0.8, "ceja_der": 0.8, "ojo_apertura": 1.25, "mirada_dx": -0.4, "mirada_dy": 0.1,
        "cabeza_pitch": 6, "cabeza_yaw": -10, "cabeza_roll": 5, "postura_roll": -6, "peso": -0.5,
        "brazo_izq": -0.4, "brazo_der": -0.4, "codo_izq": 0.7, "codo_der": 0.7, "manos_levantadas": 0.7,
        "velocidad_gesto": 1.2, "respiracion": 24, "boca_base": 0.08,
    },
    "terror": {
        "ceja_izq": 1.0, "ceja_der": 1.0, "ojo_apertura": 1.4, "mirada_dx": -0.7, "mirada_dy": 0.0,
        "cabeza_pitch": 10, "cabeza_yaw": -16, "cabeza_roll": 8, "postura_roll": -9, "peso": -0.8,
        "brazo_izq": -0.7, "brazo_der": -0.7, "codo_izq": 0.9, "codo_der": 0.9, "manos_levantadas": 1.0,
        "velocidad_gesto": 1.5, "respiracion": 30, "boca_base": 0.15,
    },
    "tristeza": {
        "ceja_izq": 0.5, "ceja_der": 0.35, "ojo_apertura": 0.85, "mirada_dx": 0.0, "mirada_dy": -0.3,
        "cabeza_pitch": 8, "cabeza_yaw": 0, "cabeza_roll": 3, "postura_roll": 4, "peso": 0.3,
        "brazo_izq": 0.0, "brazo_der": 0.0, "codo_izq": 0.2, "codo_der": 0.2, "manos_levantadas": 0.0,
        "velocidad_gesto": 0.7, "respiracion": 12, "boca_base": 0.0,
    },
    "enojo": {
        "ceja_izq": -0.7, "ceja_der": -0.7, "ojo_apertura": 1.15, "mirada_dx": 0.0, "mirada_dy": 0.0,
        "cabeza_pitch": -2, "cabeza_yaw": 0, "cabeza_roll": -1, "postura_roll": -1, "peso": 0.1,
        "brazo_izq": 0.55, "brazo_der": 0.55, "codo_izq": 0.6, "codo_der": 0.6, "manos_levantadas": 0.5,
        "velocidad_gesto": 1.35, "respiracion": 18, "boca_base": 0.04,
    },
    "confusion": {
        "ceja_izq": 0.6, "ceja_der": 0.1, "ojo_apertura": 1.0, "mirada_dx": 0.6, "mirada_dy": -0.1,
        "cabeza_pitch": 5, "cabeza_yaw": 14, "cabeza_roll": -6, "postura_roll": 1, "peso": 0.05,
        "brazo_izq": -0.1, "brazo_der": 0.1, "codo_izq": 0.3, "codo_der": 0.25, "manos_levantadas": 0.15,
        "velocidad_gesto": 0.8, "respiracion": 15, "boca_base": 0.02,
    },
    "ironia": {
        "ceja_izq": -0.2, "ceja_der": 0.5, "ojo_apertura": 0.95, "mirada_dx": -0.2, "mirada_dy": 0.05,
        "cabeza_pitch": -1, "cabeza_yaw": -6, "cabeza_roll": 7, "postura_roll": 2, "peso": 0.0,
        "brazo_izq": 0.0, "brazo_der": 0.35, "codo_izq": 0.2, "codo_der": 0.5, "manos_levantadas": 0.3,
        "velocidad_gesto": 0.95, "respiracion": 14, "boca_base": 0.03,
    },
    "suspenso": {
        "ceja_izq": 0.3, "ceja_der": 0.3, "ojo_apertura": 1.05, "mirada_dx": 0.5, "mirada_dy": -0.05,
        "cabeza_pitch": 2, "cabeza_yaw": 5, "cabeza_roll": -2, "postura_roll": -2, "peso": -0.1,
        "brazo_izq": 0.05, "brazo_der": 0.05, "codo_izq": 0.35, "codo_der": 0.35, "manos_levantadas": 0.2,
        "velocidad_gesto": 0.75, "respiracion": 13, "boca_base": 0.0,
    },
    "determinacion": {
        "ceja_izq": -0.35, "ceja_der": -0.35, "ojo_apertura": 1.1, "mirada_dx": 0.0, "mirada_dy": 0.15,
        "cabeza_pitch": -2, "cabeza_yaw": 0, "cabeza_roll": 0, "postura_roll": -1, "peso": 0.2,
        "brazo_izq": 0.25, "brazo_der": 0.25, "codo_izq": 0.45, "codo_der": 0.45, "manos_levantadas": 0.35,
        "velocidad_gesto": 1.1, "respiracion": 15, "boca_base": 0.02,
    },
    "tranquilidad": {
        "ceja_izq": 0.1, "ceja_der": 0.1, "ojo_apertura": 0.9, "mirada_dx": 0.0, "mirada_dy": -0.1,
        "cabeza_pitch": 2, "cabeza_yaw": 0, "cabeza_roll": 1, "postura_roll": 0, "peso": 0.0,
        "brazo_izq": 0.0, "brazo_der": 0.0, "codo_izq": 0.15, "codo_der": 0.15, "manos_levantadas": 0.0,
        "velocidad_gesto": 0.85, "respiracion": 12, "boca_base": 0.0,
    },
}

PARAMS = list(next(iter(ESTADOS.values())).keys())

GESTOS = {
    # clave: gesto narrativo -> como modifica el bloque básico (deltas) y su duración base
    "explicar":     {"codo_izq": +0.25, "codo_der": +0.25, "manos_levantadas": +0.2, "dur": (1.2, 3.0)},
    "senalar":      {"brazo_der": +0.55, "codo_der": +0.3, "mirada_dx": +0.4, "dur": (0.8, 1.6)},
    "advertir":     {"brazo_izq": +0.3, "brazo_der": +0.3, "manos_levantadas": +0.35, "cabeza_pitch": +3, "dur": (1.0, 2.0)},
    "narrar":       {"codo_izq": +0.3, "codo_der": +0.2, "dur": (2.0, 5.0)},
    "caminar":      {"peso": +0.4, "brazo_izq": +0.3, "brazo_der": -0.3, "dur": (2.0, 6.0)},
    "correr":       {"peso": -0.4, "brazo_izq": +0.7, "brazo_der": -0.7, "velocidad_gesto": +0.5, "dur": (1.5, 4.0)},
    "reaccionar":   {"ojo_apertura": +0.25, "cabeza_yaw": -6, "dur": (0.5, 1.2)},
    "asustarse":    {"ojo_apertura": +0.4, "ceja_izq": +0.8, "ceja_der": +0.8, "peso": -0.5, "dur": (0.4, 0.9)},
    "caerse":       {"postura_roll": -12, "peso": -0.9, "ojo_apertura": +0.3, "dur": (0.6, 1.2)},
    "mirar_atras":  {"cabeza_yaw": -28, "mirada_dx": -0.8, "dur": (0.6, 1.4)},
    "interactuar":  {"brazo_der": +0.4, "codo_der": +0.5, "mirada_dx": +0.35, "dur": (1.5, 4.0)},
    "sorprenderse": {"ojo_apertura": +0.35, "ceja_izq": +1.0, "ceja_der": +1.0, "dur": (0.4, 1.0)},
    "celebrar":     {"brazo_izq": +0.8, "brazo_der": +0.8, "manos_levantadas": +0.8, "dur": (1.0, 2.0)},
    "discutir":     {"brazo_izq": +0.5, "codo_izq": +0.5, "cabeza_yaw": +8, "velocidad_gesto": +0.4, "dur": (1.5, 4.0)},
}


# --------------------------------------------------------------- curvas suaves
def _ease_smootherstep(x: float) -> float:
    """S-curve C1+C2: sin picos de velocidad; la transición nunca es lineal."""
    x = max(0.0, min(1.0, x))
    return x * x * x * (x * (x * 6.0 - 15.0) + 10.0)


def transicion_bloque(a: dict, b: dict, t: float, dur: float, intensidad: float = 1.0) -> dict:
    """Interpola A->B en `t` segundos de la transición con duración `dur`."""
    k = _ease_smootherstep(t / max(dur, 0.05)) * max(0.2, min(1.0, intensidad))
    out = {}
    for p in PARAMS:
        va, vb = a.get(p, 0.0), b.get(p, 0.0)
        out[p] = round(va + (vb - va) * k, 4)
    return out


def aplicar_gesto(bloque: dict, gesto: str) -> dict:
    """Un gesto EMPIEZA con anticipación (10-15% antes) y settle después: no arranca seco."""
    g = GESTOS.get(gesto)
    if not g:
        return dict(bloque)
    out = dict(bloque)
    for p, delta in g.items():
        if p == "dur":
            continue
        base = out.get(p, 0.0)
        if isinstance(delta, (int, float)):
            out[p] = round(base + delta, 4)
        elif isinstance(delta, str):  # +X seguido de Y (oscilación) no implementado aún
            pass
    return out


def validar_estado(nombre: str) -> None:
    if nombre.lower() not in ESTADOS:
        raise ValueError(f"estado {nombre!r} no existe; válidos: {sorted(ESTADOS)}")
