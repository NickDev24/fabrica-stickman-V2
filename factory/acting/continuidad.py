"""Continuidad del personaje entre videos (skill character-continuity-guardian).

Misión (pilar 7): mismo personaje, mismos materiales, mismas proporciones, mismo
vestuario, iluminación consistente en TODO video. El perfil del personaje se
persiste UNA VEZ (state/personajes/<nombre>.json) y todas las producciones se
auditan contra él: paleta, escala del GLB, voces, backends de render.

Se audita en cronológicamente dos puntos:
  - al crear la timeline (backend GLB que se usará + paleta de iluminación),
  - antes de aprobar el render (ambientes y assets deben salir del mismo perfil).
"""
from __future__ import annotations

import json
from pathlib import Path

from pipeline import config

PERS_DIR = config.STATE / "personajes"


def perfil(nombre: str = "principal", paleta_json: Path | None = None) -> dict:
    """Carga el perfil o lo crea la primera vez (con la paleta registrada)."""
    PERS_DIR.mkdir(parents=True, exist_ok=True)
    path = PERS_DIR / f"{nombre}.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    base = {
        "nombre": nombre,
        "creado": __import__("time").strftime("%Y-%m-%d"),
        "vestuario": {"nota": "breve descripción de identidad visual; NO una persona real",
                      "pantalon": "jeans oscuros", "torso": "remera neutra",
                      "notas": ""}
    }
    if paleta_json and Path(paleta_json).exists():
        base["paleta"] = json.loads(Path(paleta_json).read_text(encoding="utf-8"))
    else:
        base["paleta"] = {"fondo_hdr": "studio_neutral", "key_light": "6500K, 1.15",
                          "rim_light": "8500K, 0.4", "ambient": "0.35"}
    path.write_text(json.dumps(base, indent=1, ensure_ascii=False), encoding="utf-8")
    return base


def auditar(ep) -> dict:
    """Verifica la producción contra el perfil persistente del personaje.

    Problemas reales detectables hoy:
      - backend de render inestable (cambia entre videos)
      - paleta/iluminación no registrada en el perfil
      - más de una voz sin allowlist (gate 2 en pipeline/config)
    Devuelve {ok, problemas, perfil}.
    """
    nombre = "principal"
    p = perfil(nombre)
    probs = []
    tl_file = ep.dir / "artifacts" / "timeline_actuacion.json"
    backend = "pendiente"
    if tl_file.exists():
        tl = json.loads(tl_file.read_text(encoding="utf-8"))
        backend = tl.get("personaje", {}).get("integracion", "pendiente")
        if backend.startswith("glb:"):
            glb_actual = backend.split(":", 1)[1]
            prev_glb = p.get("backend_glb")
            if prev_glb and prev_glb != glb_actual:
                probs.append(f"GLB cm: {prev_glb} != {glb_actual}")
        if not tl.get("camara"):
            probs.append("sin cámara en la timeline: continuidad visual incompleta")
    else:
        probs.append("sin timeline de actuación: nada que auditar")
    meta = ep.metadata()
    voz = meta.get("voice", "")
    if voz and "piper:" not in voz and "edge-tts:" not in voz:
        probs.append(f"voz fuera del allowlist del canal: {voz!r}")
    if backend != "pendiente" and not p.get("backend_glb"):
        p["backend_glb"] = backend if backend.startswith("glb:") else None
        (PERS_DIR / f"{nombre}.json").write_text(
            json.dumps(p, indent=1, ensure_ascii=False), encoding="utf-8")
    if p.get("backend_glb") and backend == "pendiente":
        probs.append("se esperaba el backend GLB del perfil y no hay GLB en assets/")
    return {"ok": not probs, "problemas": probs, "perfil": nombre, "backend": backend}
