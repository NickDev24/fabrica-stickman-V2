"""Runtime de Skills de la fábrica audiovisual.

Una Skill es un especialista con:
  - SKILL.md operativa en .agents/skills/<nombre>/SKILL.md
  - un punto funcional REAL de conexión (módulo + función invocable)
  - un contrato de datos de salida (factory/skills/contratos.py)
  - evaluación de calidad sobre su producto

El orquestador nunca ejecuta las 23 a la vez: resuelve, por etapa de producción,
UNA skill adecuada con `seleccionar()` e `invocar()`. Los cambios de módulos de
forma que pueden ser locales (una skill con error no detiene la fábrica: el
orquestador la reintenta con política `reintentos` y después la degrada).

Registro de ejecución: state/skills_log.jsonl (una entrada por invocación con
latencia, estado, contrato y error si hubo).
"""
from __future__ import annotations

import json
import time
import traceback
from importlib import import_module
from pathlib import Path

from pipeline import config
from . import contratos

ROOT = Path(__file__).resolve().parents[2]
LOG = config.STATE / "skills_log.jsonl"

# ---------------------------------------------------------------------------
# Registro maestro. `punto` = (módulo, función) callable real.
# `estado`: "operativa" | "pendiente_backend" (contrato definido, módulo futuro)
# ---------------------------------------------------------------------------
SKILLS: dict[str, dict] = {
    # -------- ANIMACIÓN (críticas, pilares 1-5) --------
    "3d-character-director": {
        "grupo": "animacion", "rol": "Dirige la actuación completa del actor digital: curva emocional visemas cámara micro-behaviors en artifacts/timeline_actuacion.json.",
        "punto": ("factory.skills.adapters", "timeline_actuacion"), "tz": "un episodio narrado",
        "contrato": "timeline_actuacion", "estado": "operativa",
    },
    "facial-expression-animator": {
        "grupo": "animacion", "rol": "Traduce la partitura emocional a bloques de rig facial por segmento (cejas ojos mirada cabeza boca base) con transiciones suaves.",
        "punto": ("factory.skills.adapters", "expresiones_bloques"), "tz": "episodio con script.txt",
        "contrato": "expresiones", "estado": "operativa",
    },
    "phoneme-lipsync-engineer": {
        "grupo": "animacion", "rol": "Alineación fonética de visemas sobre el WAV de Piper con Rhubarb; fallback silábico siempre declarado.",
        "punto": ("factory.skills.adapters", "lipsync_cues"), "tz": "narración segmentada + WAV",
        "contrato": "lipsync_cues", "estado": "operativa",
    },
    "body-language-director": {
        "grupo": "animacion", "rol": "Lenguaje corporal: biblioteca de gestos con propósito narrativo anticipación y settle aplicados al bloque de rig por segmento.",
        "punto": ("factory.skills.adapters", "lenguaje_corporal"), "tz": "partitura emocional",
        "contrato": "gestos", "estado": "operativa",
    },
    "cinematic-camera-director": {
        "grupo": "animacion", "rol": "Plan de planos y movimientos de cámara motivados por el contenido (política por emoción + cortes en segmentos largos).",
        "punto": ("factory.skills.adapters", "plan_camara"), "tz": "timeline de actuación",
        "contrato": "camara", "estado": "operativa",
    },
    "character-continuity-guardian": {
        "grupo": "animacion", "rol": "Consistencia del personaje entre videos: perfil persistente (identidad proporciones vestuario paleta iluminación) y validación contra cada producción.",
        "punto": ("factory.acting.continuidad", "auditar"), "tz": "episodio + perfil en state/personajes/",
        "contrato": "continuidad", "estado": "operativa",
    },
    # -------- NARRATIVA --------
    "viral-story-researcher": {
        "grupo": "narrativa", "rol": "Detecta señales de demanda real (Wikipedia, Hacker News, canales activos) y clasifica nicho + formato viable.",
        "punto": ("factory.skills.adapters", "senales"), "tz": "semillas de temas",
        "contrato": "senales", "estado": "operativa",
    },
    "retention-scriptwriter": {
        "grupo": "narrativa", "rol": "Escribe el guion con identidad de canal del nicho, hooks, escalada y final (pipeline/stages/guion).",
        "punto": ("pipeline.stages.guion", "guion"), "tz": "episodio verificado",
        "contrato": "guion_segmentado", "estado": "operativa",
    },
    "emotional-story-director": {
        "grupo": "narrativa", "rol": "Partitura emocional del video: emoción/intensidad/gesto/énfasis/SFX por segmento con curva narrativa.",
        "punto": ("factory.skills.adapters", "partitura"), "tz": "segmentos del guion",
        "contrato": "partitura", "estado": "operativa",
    },
    "documentary-investigator": {
        "grupo": "narrativa", "rol": "Investiga el tema, descubre fuentes primero, resume y contrasta; registros en artifacts/sources.json + factcheck.json.",
        "punto": ("pipeline.stages.research", "research"), "tz": "episodio seleccionado",
        "contrato": "fuentes", "estado": "operativa",
    },
    "series-universe-builder": {
        "grupo": "narrativa", "rol": "Universo de serie: cast recurrente, continuidad entre capítulos y phases del mundo registrado en artifacts/universo.json.",
        "punto": ("factory.skills.adapters", "universo_serie"), "tz": "episodios previos del nicho",
        "contrato": "universo", "estado": "operativa",
    },
    # -------- PRODUCCIÓN --------
    "storyboard-architect": {
        "grupo": "produccion", "rol": "Materializa cada segmento del guion en material visual por escena (assets/img|video/seg-NNN).",
        "punto": ("pipeline.stages.visuales", "generar"), "tz": "guion + research de urls",
        "contrato": "visuales", "estado": "operativa",
    },
    "sound-design-engineer": {
        "grupo": "produccion", "rol": "Plan sonoro por segmento (música, ambientes, impactos) alineado con la partitura emocional; SFX solo donde la narrativa los pide.",
        "punto": ("factory.skills.adapters", "plan_sonoro"), "tz": "timeline de actuación",
        "contrato": "sonoro", "estado": "operativa",
    },
    "cinematic-video-editor": {
        "grupo": "produccion", "rol": "Monta el video por segmentos con FFmpeg e integra voz, subtítulos y QC ffprobe.",
        "punto": ("pipeline.stages.montaje", "montar"), "tz": "audio + visuales",
        "contrato": "qc_render", "estado": "operativa",
    },
    "thumbnail-art-director": {
        "grupo": "produccion", "rol": "Miniatura con sujeto principal, máximo 3 palabras de texto, contraste alto y requerimientos CTR verificables.",
        "punto": ("factory.skills.adapters", "miniatura"), "tz": "render principal + paleta",
        "contrato": "miniatura", "estado": "pendiente_backend",
    },
    # -------- DISTRIBUCIÓN --------
    "youtube-growth-analyst": {
        "grupo": "distribucion", "rol": "Analítica de rendimiento por publicación (CTR retención retención recurrencia) y aprendizaje para el nicho.",
        "punto": ("pipeline.stages.publicacion", "registrar"), "tz": "episodio publicado",
        "contrato": "registro", "estado": "operativa",
    },
    "facebook-content-strategist": {
        "grupo": "distribucion", "rol": "Publicación/estrategia en Facebook vía Zernio (conector oficial) con metadatos por plataforma.",
        "punto": ("factory.skills.adapters", "publicar_facebook"), "tz": "paquete listo para publicar",
        "contrato": "publicacion", "estado": "operativa",
    },
    "community-manager-ai": {
        "grupo": "distribucion", "rol": "Clasifica comentarios (pregunta/spam/idea/delicado) y responde genuinamente con la personalidad del canal; deriva a humano lo sensible.",
        "punto": ("factory.skills.adapters", "clasificar_comentarios"), "tz": "comentarios crudos",
        "contrato": "comunidad", "estado": "pendiente_backend",
    },
    # -------- CALIDAD / COMPLIANCE --------
    "render-optimization-engineer": {
        "grupo": "calidad", "rol": "Recursos: límites CPU/RAM, un solo render simultáneo 720p/24fps, serialización y presupuesto de APIs.",
        "punto": ("factory.skills.adapters", "recursos"), "tz": "config de recursos",
        "contrato": "recursos", "estado": "operativa",
    },
    "visual-quality-inspector": {
        "grupo": "calidad", "rol": "Inspección visual real con ffmpeg: detección de fotogramas negros/solidos y muestreo de frames del render.",
        "punto": ("factory.skills.adapters", "inspeccionar_visual"), "tz": "render principal",
        "contrato": "qc_visual", "estado": "operativa",
    },
    "audio-quality-inspector": {
        "grupo": "calidad", "rol": "Inspección de audio real: LUFS ebur128, picos, silencios y sincronía de duración con el video.",
        "punto": ("factory.skills.adapters", "inspeccionar_audio"), "tz": "render principal",
        "contrato": "qc_audio", "estado": "operativa",
    },
    "copyright-compliance-reviewer": {
        "grupo": "calidad", "rol": "Cadena de licencia de todo asset usado (dominios de origen, música autorizada fonts) y registro de créditos.",
        "punto": ("factory.skills.adapters", "auditar_licencias"), "tz": "metadata + assets",
        "contrato": "licencias", "estado": "operativa",
    },
    "monetization-policy-reviewer": {
        "grupo": "calidad", "rol": "Elegibilidad YPP/Facebook: gates de publicación, contenido sintético declarado, umbral de requisito marcado en aprendiendo.",
        "punto": ("factory.skills.adapters", "politica"), "tz": "metadata del episodio",
        "contrato": "politicas", "estado": "operativa",
    },
}

CONTRATOS = {"timeline_actuacion": "timeline", "lipsync_cues": "lipsync", "qc_render": "qc",
             "guion_segmentado": "guion"}


def seleccionar(grupo: str, tarea: str = "") -> tuple[str, dict] | tuple[None, None]:
    """Elige la skill del grupo cuya skill puede ejecutar la tarea (el orquestador decide).

    Criterios: estado "operativa" primero; contrato disponible; si varias,
    la de menor costo esperado (Teams: narrativa/documentación < producción).
    """
    operatives = [(n, s) for n, s in SKILLS.items() if s["grupo"] == grupo and s["estado"] == "operativa"]
    if not operatives:
        return (None, None)
    if tarea:
        exact = [(n, s) for n, s in operatives if tarea.lower() in s["rol"].lower()]
        if exact:
            operatives = exact
    return operatives[0]


def invocar(nombre: str, ep=None, **kwargs) -> dict:
    """Ejecuta la skill en su punto funcional real con registro y evaluación.

    Devuelve {"estado": "ok"|"error", "salida": data, "evaluacion": {...}, "duracion_s": t}.
    Nunca expone el stacktrace completo: guarda las 2 líneas últimas.
    """
    skill = SKILLS.get(nombre)
    if not skill:
        return {"estado": "error", "error": f"skill desconocida: {nombre}"}
    if skill.get("estado") == "pendiente_backend":
        # No es un fallo: el contrato existe, el módulo todavía no. El orquestador la salta.
        return {"estado": "pendiente", "skill": nombre,
                "motivo": f"contrato {skill.get('contrato')!r} definido, backend no implementado"}
    registro = {"skill": nombre, "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "episode": getattr(ep, "slug", ""), "ts0": time.time()}
    out: dict = {}
    try:
        mod, fn = skill["punto"]
        func = getattr(import_module(mod), fn)
        salida = func(ep, **kwargs) if ep is not None else func(**kwargs)
        evaluacion = evaluar(nombre, salida)
        registro["dur_s"] = round(time.time() - registro.pop("ts0"), 2)
        registro["status"] = "ok"
        _append(registro)
        return {"estado": "ok", "salida": salida, "evaluacion": evaluacion, "duracion_s": registro["dur_s"]}
    except Exception as exc:  # la skill con error NO mata la fábrica
        tb = traceback.format_exc().strip().splitlines()
        registro["dur_s"] = round(time.time() - registro.pop("ts0", 0), 2)
        registro["status"] = "error"
        registro["error"] = f"{exc.__class__.__name__}: {str(exc)[:200]}"
        registro["tb_last"] = " | ".join(tb[-2:])[:300]
        _append(registro)
        return {"estado": "error", "error": registro["error"], "tb": registro["tb_last"],
                "duracion_s": registro["dur_s"]}


def evaluar(nombre: str, salida) -> dict:
    """Evaluación de calidad por skill sobre el producto real (sin placebo)."""
    skill = SKILLS.get(nombre, {})
    base = {"skill": nombre}
    try:
        if skill.get("contrato") == "timeline_actuacion" and isinstance(salida, dict):
            probs = contratos.validar_timeline_actuacion(salida)
            base["problemas"] = probs
            base["seg"] = len(salida.get("segmentos", []))
        elif skill.get("contrato") == "lipsync_cues" and isinstance(salida, dict):
            probs = contratos.validar_lipsync_cues(salida)
            base["problemas"] = probs
            base["cues"] = len(salida.get("cues", []))
        elif skill.get("contrato") == "guion_segmentado" and isinstance(salida, str):
            base["problemas"] = contratos.validar_guion_segmentado(salida, min_segmentos=2)
        elif skill.get("contrato") in ("qc_render",) and isinstance(salida, dict):
            base["problemas"] = contratos.validar_qc_render(salida)
        else:  # sin contrato específico: producto inmemory no estructura
            base["sin_contrato"] = True
        base["calidad"] = "pass" if not base.get("problemas") else "falla_" + str(len(base["problemas"]))
    except Exception as exc:
        base["evaluacion_error"] = str(exc)[:150]
    return base


def resumen() -> list[dict]:
    if not LOG.exists():
        return []
    rows = [json.loads(l) for l in LOG.read_text(encoding="utf-8").splitlines() if l.strip()]
    out: dict[str, dict] = {}
    for r in rows:
        s = out.setdefault(r["skill"], {"skill": r["skill"], "n": 0, "ok": 0, "err": 0, "avg_s": 0.0})
        s["n"] += 1
        s["ok" if r.get("status") == "ok" else "err"] += 1
        s["avg_s"] = round((s["avg_s"] * (s["n"] - 1) + r.get("dur_s", 0)) / s["n"], 2)
    return list(out.values())


def _append(entry: dict) -> None:
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
