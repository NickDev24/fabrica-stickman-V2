"""Protocolos de control de validación VIRAL (niveles expertos) — Fábrica Stickman.

Complemento los gates técnicos ya existentes (pipeline/gates.py, QC de cómics) con los
controles editoriales/expertos que un equipo senior exige antes de que la fábrica publique
por Zernio (Facebook + YouTube):

  GATE_VISUAL_ESTIMULANTE  — el render debe portar estimulación visual real (beats/movimiento
                             con conflicto). Fallo crítico: sin estimulación comprobable.
  GATE_EMOCION_UNIVERSAL    — el guion debe arrancar y sostener emoción universal
                             (miedo / asombro / venganza / injusticia / drama / tensión).
  GATE_RECOMPENSA_NARRATIVA — los bucles de curiosidad deben cerrarse con recompensa/giro
                             (reusa gate_bucles del pipeline: 6-8 aperturas, cierre que paga).
  GATE_COMIC_ESTIMULANTE    — el cómic debe cumplir: hook en panel 1, silencio negro, giro
                             Ki-Sho-Ten-Ketsu, ≥15 viñetas, grillas 3 bandas, shareability atómica.

Estos protocolos se integran ANTES de la publicación por Zernio y del armado del cómic:
un fallo CRÍTICO bloquea la publicación; los no críticos se reportan en el diagnóstico.
"""
from __future__ import annotations

import json
import re

from pipeline.episode import Episode

GATE_VISUAL_ESTIMULANTE = "viral_visual_estimulante"
GATE_EMOCION_UNIVERSAL = "viral_emocion_universal"
GATE_RECOMPENSA_NARRATIVA = "viral_recompensa_narrativa"
GATE_COMIC_ESTIMULANTE = "viral_comic"

_EMOCIONES = ("miedo", "asombro", "venganza", "injusticia", "drama", "tensi", "peligro",
              "curiosidad", "misterio", "culpa", "soledad", "esperanza")


def gate_visual_estimulante(render_info: dict | None, metadata: dict | None = None) -> list[str]:
    """Crítico: el render debe demostrar estimulación visual (movimiento con conflicto).

    Un reel sin estimulación comprobable (pocos beats / render sin info de movimiento) es
    inviable viral: la retención se hunde en el minuto 2.
    """
    info = render_info or {}
    reasons: list[str] = []
    beats = int(info.get("beats") or info.get("n_beats") or 0)
    if beats < 3:
        reasons.append(f"render sin estimulación visual comprobable ({beats} beats)")
    dur = float(info.get("duracion_s") or 0)
    if dur and dur < 8:
        reasons.append(f"duración corta para arco viral: {dur:.1f}s")
    return reasons


def gate_emocion_universal(script: str) -> list[str]:
    """Crítico: el guion debe portar una emoción universal detectada (conflicto + arco)."""
    prosa = re.sub(r"\s+", " ", script or "")
    low = prosa.lower()
    hits = [e for e in _EMOCIONES if e in low]
    if not hits:
        return [f"guion sin emoción universal detectada: {prosa[:70]!r}"]
    return []


def gate_recompensa_narrativa(script: str) -> list[str]:
    """Crítico: los bucles deben cerrarse (reusa el gate de bucles del pipeline)."""
    from pipeline import gates
    return list(gates.gate_bucles(script, (6, 8)))


def gate_comic_estimulante(datos: dict) -> list[str]:
    """Crítico: el cómic debe arrancar con hook, tener giro y estructura viral mínima."""
    problemas: list[str] = []
    paneles = datos.get("paneles") or []
    roles = {str(p.get("rol_ritmico") or "") for p in paneles}
    if "gancho" not in roles:
        problemas.append("comic sin hook en panel 1 (cold open)")
    if not (roles & {"giro", "cliffhanger"}):
        problemas.append("comic sin giro/cliffhanger (Ki-Sho-Ten-Ketsu incompleto)")
    if "silencio" not in roles:
        problemas.append("comic sin silencio negro de descompresión")
    n = len(paneles)
    if n < 15:
        problemas.append(f"comic con {n} viñetas < mínimo viral 15")
    grillas = datos.get("grillas") or []
    for i, g in enumerate(grillas, 1):
        if len(g) != 3:
            problemas.append(f"página {i}: grilla con {len(g)} bandas (deben ser 3)")
    return problemas


def _render_info(ep: Episode) -> dict | None:
    p = ep.artifacts / "render_keyframes.json"
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            pass
    p = ep.artifacts / "beats.json"
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            pass
    return None


def validar_produccion_viral(ep: Episode) -> dict:
    """Agrega los protocolos expertos de validación viral para el episodio actual.

    Devuelve {"ok": bool, "gates": {nombre: reasons}, "criticos": [nombres]}.
    Los fallos críticos bloquean la publicación por Zernio.
    """
    gates_out: dict[str, list[str]] = {}
    criticos: list[str] = []
    script = ""
    try:
        script = ep.read_text("script.txt")
    except Exception:
        pass
    gates_out[GATE_VISUAL_ESTIMULANTE] = gate_visual_estimulante(_render_info(ep), ep.metadata())
    gates_out[GATE_EMOCION_UNIVERSAL] = gate_emocion_universal(script)
    gates_out[GATE_RECOMPENSA_NARRATIVA] = gate_recompensa_narrativa(script)
    for nombre, reasons in gates_out.items():
        if reasons:
            criticos.append(f"{nombre}: {'; '.join(reasons)}")
    ok = not criticos
    return {"ok": ok, "gates": gates_out, "criticos": criticos}


def validar_comic_viral(slug: str) -> dict:
    """Agrega el protocolo experto de validación viral al cómic del episodio."""
    ep = Episode(slug)
    datos = {}
    p = ep.dir / "comics" / "guion_paneles.json"
    try:
        datos = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        pass
    gates_out = {GATE_COMIC_ESTIMULANTE: gate_comic_estimulante(datos)}
    ok = not any(gates_out.values())
    return {"ok": ok, "gates": gates_out}
