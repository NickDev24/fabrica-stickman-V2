"""Orquestador de la fábrica: decide qué skill usar, en qué orden, y reanuda lo interrumpido.

Reglas de diseño (misión §FASE 3):
  - Un solo contrato de contexto: `projects/<slug>/artifacts/*.json`. Las skills no se
    pasan datos por memoria ni por el orquestador; leen y escriben esos artefactos.
  - `estado()` responde con hechos del disco (existe el artefacto o no), no con intenciones.
    Por eso una corrida interrumpida se reanuda sola: lo hecho está en el disco.
  - Una skill con error NO detiene la producción: el paso queda `failed` en
    artifacts/orchestrador.json y `correr()` reintenta sólo ese paso.
  - El render es el paso caro (FASE 0: ~1.3 s/frame en este hardware). Se reanuda por
    frames ya escritos, no se repite nunca un frame.

No reemplaza a `pipeline.run auto` (que descubre tema, investiga y publica): este módulo
orquesta la parte de producción audiovisual con avatar, desde el guion ya escrito.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from pipeline.episode import Episode
from .skills import registry

ROOT = Path(__file__).resolve().parents[1]

# Plan maestro. `skills` se invocan en orden; `arte` es el artefacto que prueba que el paso
# está hecho (ruta relativa al episodio o al repo); `etapa` es la stage del pipeline que lo
# produce cuando todavía no existe.
PLAN = [
    {"paso": "guion", "skills": [], "arte": "artifacts/script.txt", "etapa": "guion"},
    {"paso": "voz", "skills": [], "arte": "assets/audio/narration.wav", "etapa": "narrar"},
    {"paso": "visemas", "skills": ["phoneme-lipsync-engineer"],
     "arte": "artifacts/lipsync.json"},
    {"paso": "actuacion", "skills": ["3d-character-director"],
     "arte": "artifacts/timeline_actuacion.json"},
    {"paso": "direccion", "skills": ["facial-expression-animator", "body-language-director",
                                     "cinematic-camera-director", "character-continuity-guardian"],
     "arte": "artifacts/direccion.json"},
    {"paso": "render", "skills": [], "arte": "RENDER_AVATAR"},
    {"paso": "qc", "skills": ["visual-quality-inspector", "audio-quality-inspector"],
     "arte": "artifacts/qc_avatar.json"},
]


def _ruta(ep: Episode, arte: str) -> Path | None:
    return None if arte.startswith("RENDER") else ep.dir / arte


def estado(ep: Episode) -> list[dict]:
    """Qué está hecho en disco y qué falta. No ejecuta nada."""
    log = _log(ep)
    filas = []
    for paso in PLAN:
        p = _ruta(ep, paso["arte"])
        hecho = (p.exists() and p.stat().st_size > 0) if p else _render_hecho(ep)
        prev = log.get(paso["paso"], {})
        filas.append({"paso": paso["paso"],
                      "estado": "failed" if prev.get("estado") == "error" and not hecho
                                else "done" if hecho else "pending",
                      "skills": paso["skills"], "artefacto": str(p.relative_to(ep.dir)) if p
                      else paso["arte"],
                      "ultimo": prev.get("ts", ""), "errores": prev.get("errores", [])})
    return filas


def _render_hecho(ep: Episode) -> bool:
    v = ep.dir / "renders" / f"{ep.slug}-avatar.mp4"
    return v.exists() and v.stat().st_size > 10_000


def _log(ep: Episode) -> dict:
    f = ep.artifacts / "orchestrador.json"
    return json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}


def _guardar(ep: Episode, log: dict) -> None:
    ep.write_json("orchestrador.json", log)


def correr(ep: Episode, hasta: str | None = None, forzar: bool = False,
           glb: Path | None = None, reanudar: bool = True) -> dict:
    """Ejecuta los pasos pending del plan. Devuelve el estado final por paso."""
    log = _log(ep)
    resumen = []
    for paso in PLAN:
        if forzar:
            p = _ruta(ep, paso["arte"])
            if p and p.exists():
                p.unlink()
            elif paso["arte"] == "RENDER_AVATAR":
                v = ep.dir / "renders" / f"{ep.slug}-avatar.mp4"
                v.unlink(missing_ok=True)
        hecho = estado(ep)
        actual = next(f for f in hecho if f["paso"] == paso["paso"])
        if actual["estado"] == "done":
            resumen.append({"paso": paso["paso"], "estado": "done (salteado)"})
            continue
        t0 = time.time()
        errores: list[str] = []
        salida: dict = {}

        if paso.get("etapa"):
            from pipeline.stages import guion as _guion, narracion as _narr
            if paso["paso"] == "guion":
                _guion.guion(ep, None)
            else:
                _narr.narrar(ep)

        for nombre in paso["skills"]:
            r = registry.invocar(nombre, ep)
            if r["estado"] == "error":
                errores.append(f"{nombre}: {r['error']}")
            elif r["estado"] == "pendiente":
                errores.append(f"{nombre}: PENDIENTE ({r['motivo']})")
            else:
                salida[nombre] = r["salida"]
                ev = r.get("evaluacion") or {}
                if ev.get("problemas"):
                    errores.append(f"{nombre}: {ev['problemas']}")

        if paso["paso"] == "direccion":
            ep.write_json("direccion.json", salida)
        if paso["paso"] == "render":
            from pipeline.stages import avatar
            try:
                resumen_render = avatar.render(ep, glb=glb, reanudar=reanudar)
                salida["render"] = resumen_render
                if resumen_render.get("problemas"):
                    errores.append(f"render: {resumen_render['problemas']}")
            except SystemExit as exc:
                errores.append(f"render: {exc}")
        if paso["paso"] == "qc":
            video = ep.dir / "renders" / f"{ep.slug}-avatar.mp4"
            for nombre in paso["skills"]:
                registry.invocar(nombre, ep, video=video)
            qc = {"visual": _leer(ep, "qc_visual.json"), "audio": _leer(ep, "qc_audio.json"),
                  "avatar": _leer(ep, "render_avatar.json")}
            ep.write_json("qc_avatar.json", qc)
            for clave in ("visual", "audio"):
                errores += [f"qc_{clave}: {p}" for p in (qc[clave] or {}).get("problemas", [])]

        log[paso["paso"]] = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
                             "estado": "error" if errores else "ok",
                             "s": round(time.time() - t0, 1), "errores": errores[:6]}
        _guardar(ep, log)
        resumen.append({"paso": paso["paso"],
                        "estado": "failed" if errores else "ok",
                        "s": log[paso["paso"]]["s"], "errores": errores[:3]})
        print(f"  [{paso['paso']}] {log[paso['paso']]['estado']} en "
              f"{log[paso['paso']]['s']}s" + (f" | {errores[:2]}" if errores else ""))
        if hasta == paso["paso"]:
            break
    return {"episodio": ep.slug, "pasos": resumen,
            "listo": all(r["estado"].startswith(("ok", "done")) for r in resumen)}


def _leer(ep: Episode, nombre: str):
    f = ep.artifacts / nombre
    return json.loads(f.read_text(encoding="utf-8")) if f.exists() else None
