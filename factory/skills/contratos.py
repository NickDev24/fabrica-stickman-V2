"""Contratos de datos de la fábrica (validación entre Skills).

Cada contrato es un esquema verificable de entrada/salida. El runtime de Skills
NO deja pasar datos malformados de un especialista a otro: si el contrato falla,
la skill se marca con error y el orquestador decide reintentarla o derivarla.

Contratos registrados:
- timeline_actuacion: artifacts/timeline_actuacion.json (schema JSON en factory/specs)
- lipsync_cues: artifacts/lipsync.json (visemas Rhubarb/silábico con tiempos)
- qc_render: qc.json del montaje (streams, duración, problems)
- guion_segmentado: bloques de texto separados por doble salto (fuente de voz)

TODO del orquestador pasa por estos validadores; nada se asume.
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCHEMA_TIMELINE = ROOT / "factory" / "specs" / "timeline_actuacion.schema.json"

ESTADOS_VALIDOS = {
    "neutralidad", "alegria", "sorpresa", "curiosidad", "miedo", "terror",
    "tristeza", "enojo", "confusion", "ironia", "suspenso", "determinacion",
    "tranquilidad",
}
VIS = {"A", "B", "C", "D", "E", "F", "G", "H", "X"}


class ContratoFallido(ValueError):
    """El payload no cumple el contrato de datos registrado."""


def validar_timeline_actuacion(tl: dict) -> list[str]:
    """Valida la timeline de actuación contra el schema JSON + reglas de dominio.

    Devuelve lista de problemas (vacía = válida). Sin dependencias externas:
    check manual de los campos críticos para correr en CPU mínima.
    """
    probs: list[str] = []
    schema = json.loads(SCHEMA_TIMELINE.read_text(encoding="utf-8"))
    for req in schema["required"]:
        if req not in tl:
            probs.append(f"falta campo raíz {req!r}")
    emociones_validas = set(schema["properties"]["segmentos"]["items"]["properties"]["emocion"]["enum"])
    if tl.get("duracion_s", 0) <= 0:
        probs.append("duracion_s <= 0: timeline sin audio real")
    segs = tl.get("segmentos", [])
    if not segs:
        probs.append("sin segmentos")
        return probs
    for i, s in enumerate(segs):
        if s.get("emocion") not in emociones_validas:
            probs.append(f"seg {i}: emoción {s.get('emocion')!r} fuera del vocabulario de estados")
        if not 0.0 <= float(s.get("intensidad", 0)) <= 1.0:
            probs.append(f"seg {i}: intensidad fuera de [0,1]")
        # la expresión debe tener parámetros del rig (no chasquidos ni vacío)
        e = s.get("expresion") or {}
        for p in ("ojo_apertura", "ceja_izq"):
            if p not in e:
                probs.append(f"seg {i}: expresión sin parámetro {p!r}")
        # continuidad temporal
        if i > 0 and s["t0"] < segs[i - 1].get("t0", 0):
            probs.append(f"seg {i}: t0 no monótono")
    motor = (tl.get("lipsync") or {}).get("motor")
    if motor == "silabico":
        # se permite como fallback declarado, pero se marca para QC reforzado
        probs.append("lipsync silábico (fallback declarado; QC reforzado de sincronía requerido)")
    return probs


def validar_lipsync_cues(data: dict) -> list[str]:
    probs = []
    cues = data.get("cues") or []
    if not cues:
        probs.append("sin cues de visema")
    motor = data.get("motor")
    if motor not in ("rhubarb", "silabico"):
        probs.append(f"motor desconocido: {motor!r}")
    prev = -1.0
    for c in cues:
        t = float(c.get("t", -1))
        if t < prev:
            probs.append("cues no monótonos")
            break
        if c.get("visema") not in VIS:
            probs.append(f"visema no estándar: {c.get('visema')!r}")
            break
        prev = t
    return probs


def validar_qc_render(qc: dict) -> list[str]:
    probs = []
    if qc.get("status") != "pass":
        probs.extend(qc.get("problems") or ["status != pass"])
    streams = qc.get("streams") or []
    for st in ("video", "audio"):
        if st not in streams:
            probs.append(f"falta stream {st}")
    if not qc.get("duration_s"):
        probs.append("duration_s ausente")
    return probs


def validar_guion_segmentado(texto: str, min_segmentos: int = 1) -> list[str]:
    segs = [s for s in texto.strip().split("\n\n") if s.strip()]
    probs = []
    if len(segs) < min_segmentos:
        probs.append(f"sólo {len(segs)} segmentos (< {min_segmentos})")
    if any(len(s.split()) > 120 for s in segs):
        probs.append("un segmento supera 120 palabras: rompe la modulación de voz/gestos")
    return probs
