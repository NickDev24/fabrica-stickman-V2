"""Etapa de avatar: guion narrado -> actuación 3D renderizada -> video con mezcla.

Diferencia con montaje.py: acá el plano NO es una imagen quieta ni una cartela. Cada frame se
genera con el motor de actuación (Three.js headless vía factory/render/cdp.mjs) leyendo la
timeline que produce factory/acting/director.py. Es la ruta que la FASE 0 declaró viable:
960x540 con upscale a 720p, 24 fps, una sola sesión de Chrome por video.

Contratos de datos:
  entrada   artifacts/script.txt + metadata.segment_durations_s + assets/audio/narration.wav
            artifacts/timeline_actuacion.json (factory/specs/timeline_actuacion.schema.json)
            artifacts/lipsync.json (mouthCues de Rhubarb, o fallback silábico declarado)
  salida    renders/<slug>-avatar.mp4 + artifacts/render_avatar.json (métricas reales)
"""
from __future__ import annotations

import json
import os
import resource
import shutil
import subprocess
import sys
import time
from pathlib import Path

from .. import config
from ..episode import Episode

ROOT = Path(__file__).resolve().parents[2]
CDP = ROOT / "factory" / "render" / "cdp.mjs"
W_RENDER, H_RENDER = 540, 960          # composición vertical nativa; mismo presupuesto de píxeles
FPS = 24                               # factory/acting/director.py fija FPS = 24


def _run(cmd, **kw) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, check=True, capture_output=True, text=True, **kw)


def dur(path: Path) -> float:
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                        "-of", "default=nw=1:nk=1", str(path)], capture_output=True, text=True)
    return float(r.stdout.strip() or 0)


def _glb(ep: Episode) -> Path | None:
    """El GLB del personaje: primero el declarado en state/personajes, después cualquier assets/*.glb."""
    personaje = ROOT / "state" / "personajes" / "principal.json"
    if personaje.exists():
        ref = json.loads(personaje.read_text(encoding="utf-8")).get("backend_glb")
        if ref:
            p = (ROOT / ref).resolve()
            if p.exists():
                return p
    encontrados = sorted((ROOT / "assets").glob("**/*.glb"))
    return encontrados[0] if encontrados else None


def _rig_map(glb: Path) -> dict:
    """Rig del GLB real, cacheado en state/personajes/rig_<stem>.json (los nombres cambian por modelo).

    Dos formas de sidecar: el mapa de rig completo que emite tools/make_character_glb.py
    (nodos + visemas, para personajes sin skinning) o el registro de nombres que reporta el
    motor al cargar un GLB ajeno (morph targets + huesos), del que se deriva un mapa.
    """
    registro = ep_rig_path(glb)
    if not registro.exists() and glb.stem == "cloakman":
        registro = ROOT / "state" / "personajes" / "rigmap_cloakman.json"
    if registro.exists():
        data = json.loads(registro.read_text(encoding="utf-8"))
        if data.get("nodos") or data.get("visema_nodos"):
            return data
        if data.get("morfos") or data.get("huesos"):
            return _desde_registro(data)
    return {}


def ep_rig_path(glb: Path) -> Path:
    return ROOT / "state" / "personajes" / f"rig_{glb.stem}.json"


def _desde_registro(reg: dict) -> dict:
    morfos, huesos = {}, {}
    for m in reg.get("morfos", []):
        bajo = m.lower()
        if "mouth" in bajo or "boca" in bajo or "jaw" in bajo:
            morfos.setdefault("boca_base", []).append(m)
        if "eye" in bajo or "ojo" in bajo:
            morfos.setdefault("ojo_apertura", []).append(m)
    for h in reg.get("huesos", []):
        bajo = h.lower()
        if "head" in bajo or "cabeza" in bajo:
            huesos.setdefault("cabeza_pitch", []).append([h, "x", 1])
            huesos.setdefault("cabeza_yaw", []).append([h, "y", 1])
        elif "chest" in bajo or "spine" in bajo:
            huesos.setdefault("postura_roll", []).append([h, "z", 1])
    return {"morfos": morfos, "huesos": huesos, "visema_morphs": ["mouthOpen"]}


def _huella(tl_path: Path, lips_path: Path, glb: Path | None, n: int) -> str:
    """Identifica UNA sola campana de render: reanudar sólo es válido si nada cambió."""
    import hashlib
    h = hashlib.sha256()
    for p in (tl_path, lips_path, glb, ROOT / "factory" / "render" / "actor_page.html"):
        if p and Path(p).exists():
            h.update(Path(p).read_bytes())     # contenido, no mtime: el director reescribe
            h.update(b"\0")                    #   la timeline idéntica en cada corrida
    h.update(f"|{n}|{W_RENDER}x{H_RENDER}@{FPS}".encode())
    return h.hexdigest()[:16]


def frames(ep: Episode, tl_path: Path, lips_path: Path, glb: Path | None, n: int,
           reanudar: bool = False) -> tuple[Path, dict]:
    salida = ep.dir / "renders" / "avatar-frames"
    salida.mkdir(parents=True, exist_ok=True)
    sello = _huella(tl_path, lips_path, glb, n)
    marca = salida / ".huella"
    existentes = len(list(salida.glob("frame_*.png")))
    if existentes and (not reanudar or not marca.exists()
                       or marca.read_text(encoding="utf-8") != sello):
        for viejo in salida.glob("frame_*.png"):
            viejo.unlink()
        existentes = 0
    marca.write_text(sello, encoding="utf-8")
    cmd = ["node", str(CDP), "--frames", str(n), "--fps", str(FPS),
           "--w", str(W_RENDER), "--h", str(H_RENDER),
           "--timeline", str(tl_path), "--out", str(salida)]
    if existentes:
        cmd += ["--desde", str(existentes)]
        print(f"  avatar: reanudo desde el frame {existentes}/{n}")
    if lips_path.exists():
        cmd += ["--lipsync", str(lips_path)]
    if glb:
        cmd += ["--glb", str(glb), "--rigmap", str(_escribir_rigmap(glb))]
    t0 = time.time()
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=7200)
    if proc.returncode != 0:
        raise SystemExit(f"render headless falló:\n{proc.stderr[-1500:]}")
    informe = json.loads((salida / "benchmark.json").read_text(encoding="utf-8"))
    informe["pared_ms"] = round((time.time() - t0) * 1000)
    return salida, informe


def _escribir_rigmap(glb: Path) -> Path:
    p = ROOT / "state" / "personajes" / f"rigmap_{glb.stem}.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(_rig_map(glb), ensure_ascii=False), encoding="utf-8")
    return p


def mezclar(ep: Episode, frames_dir: Path, voz: Path, total: float) -> Path:
    """Frames 540x960 -> master vertical 720x1280 + mezcla normalizada."""
    silent = ep.dir / "renders" / "avatar-silent.mp4"
    _run(["ffmpeg", "-y", "-v", "error", "-framerate", str(FPS),
          "-i", str(frames_dir / "frame_%05d.png"),
          "-vf", f"scale={config.VIDEO_W}:{config.VIDEO_H}:flags=lanczos",
          "-c:v", "libx264", "-preset", str(config.FFMPEG_PRESET), "-crf", str(config.FFMPEG_CRF),
          "-pix_fmt", "yuv420p", "-r", str(FPS), "-an", str(silent)])
    salida = ep.dir / "renders" / f"{ep.slug}-avatar.mp4"
    cama = ep.dir / "assets" / "audio" / "cama.wav"
    if not cama.exists():
        from .keyframes import _cama
        cama = _cama(ep, total)
    _run(["ffmpeg", "-y", "-v", "error", "-i", str(silent), "-i", str(voz),
          "-i", str(cama),
          "-filter_complex",
          "[1:a]aresample=48000,highpass=f=80,acompressor=threshold=0.09:ratio=3:attack=20:release=250,"
          "asplit=2[vomix][vosc];"
          "[2:a]volume=0.22[side];[side][vosc]sidechaincompress=threshold=0.025:ratio=8:attack=25:release=420[mu];"
          "[vomix][mu]amix=inputs=2:duration=first:normalize=0,alimiter=limit=0.35:level=0,"
          # Haas estéreo antes del loudnorm: percepción de espacio sin cambiar el target.
          "haas=side_gain=0.35:middle_source=mid,aformat=channel_layouts=stereo,"
          "loudnorm=I=-14:TP=-1.5:LRA=11[a]",
          "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-b:a", "128k", "-ac", "2", "-ar", "48000",
          "-shortest", "-movflags", "+faststart", str(salida)])
    return salida


def render(ep: Episode, glb: Path | None = None, forzar_frames: int | None = None,
           reanudar: bool = False) -> dict:
    from factory.acting import director
    from .narracion import _segments

    t0 = time.monotonic()
    cpu0 = resource.getrusage(resource.RUSAGE_SELF).ru_utime + resource.getrusage(resource.RUSAGE_SELF).ru_stime
    child0 = resource.getrusage(resource.RUSAGE_CHILDREN).ru_utime + resource.getrusage(resource.RUSAGE_CHILDREN).ru_stime
    meta = ep.metadata()
    durs = meta.get("segment_durations_s")
    if not durs:
        raise SystemExit("avatar: falta la narración (corré 'narrar' primero)")
    voz = ep.dir / meta.get("narration_path", "assets/audio/narration.wav")
    if not voz.exists():
        raise SystemExit(f"avatar: no existe {voz}")
    segs = _segments(ep.read_text("script.txt"))
    total = sum(durs)
    # El perfil declara un GLB que no existe en esta instalación; usar el personaje
    # original del repositorio para poder actuar con ojos, cejas y mandíbula.
    glb = glb if glb is not None else _glb(ep)
    if glb is None or not glb.exists():
        candidato = ROOT / "assets" / "characters" / "cloakman.glb"
        glb = candidato if candidato.exists() else glb

    print(f"  avatar: {total:.1f}s de voz | {len(segs)} segmentos | "
          f"modelo: {glb.name if glb else 'NINGUNO (fallback procedural)'}")

    lips_path = ep.dir / "artifacts" / "lipsync.json"
    tl = director.construir_timeline(ep.dir, voice_meta={"piper": True, "duracion_s": round(total, 2)})
    tl["fps"] = FPS
    tl_path = ep.dir / "artifacts" / "timeline_actuacion.json"
    if glb:
        # El render usa ESTE GLB; el perfil de continuidad se audita contra lo que realmente
        # se renderizó, no contra lo que había en assets/ cuando el director armó la timeline.
        try:
            ref = str(glb.resolve().relative_to(ROOT))
        except ValueError:
            ref = str(glb.resolve())
        tl.setdefault("personaje", {}).update({"integracion": "glb:" + ref, "glb_usado": ref})
        tl_path.write_text(json.dumps(tl, ensure_ascii=False, indent=1), encoding="utf-8")
    lips = json.loads(lips_path.read_text(encoding="utf-8")) if lips_path.exists() else {"mouthCues": []}
    from factory.acting import lipsync as _lipsync
    cues = [{"t": c["start"], "visema": c["value"]} for c in (lips.get("mouthCues") or [])]
    alineacion = _lipsync.medir_alineacion(voz, cues, total) if cues else {}

    n = forzar_frames or int(round(total * FPS)) + 1
    frames_dir, informe = frames(ep, tl_path, lips_path, glb, n, reanudar=reanudar)

    salida = mezclar(ep, frames_dir, voz, total)

    info = json.loads(_run(["ffprobe", "-v", "error", "-show_streams", "-show_format",
                            "-of", "json", str(salida)]).stdout)
    streams = {s["codec_type"]: s for s in info["streams"]}
    got = float(info["format"]["duration"])
    problemas = []
    boca = informe.get("boca") or {}
    if boca.get("muestreada") and boca["activas"] / boca["muestreada"] < 0.08:
        problemas.append(f"la boca casi no se abre en el render: {boca}")
    esperado = total if forzar_frames is None else min(total, n / FPS)
    transiciones = sum(1 for a, b in zip(tl["segmentos"], tl["segmentos"][1:])
                       if a["emocion"] != b["emocion"])
    planos = [f"{c['tipo']}/{c['mov']}" for c in tl["camara"]]
    con_movimiento = any(c["mov"] not in ("fijo",) for c in tl["camara"])
    if "video" not in streams or "audio" not in streams:
        problemas.append("faltan streams de video/audio")
    if (streams.get("video", {}).get("width"), streams.get("video", {}).get("height")) != (config.VIDEO_W, config.VIDEO_H):
        problemas.append(f"resolución final distinta de {config.VIDEO_W}x{config.VIDEO_H}")
    if abs(got - esperado) > 1.5:
        problemas.append(f"duración {got:.1f}s vs esperado {esperado:.1f}s")
    if informe.get("modo_render") not in ("glb", "mascota4f_procedural"):
        problemas.append(f"modo de render inesperado: {informe.get('modo_render')}")
    if glb and informe.get("modo_render") != "glb":
        problemas.append("se pasó GLB pero el motor no lo cargó")
    if not glb:
        problemas.append("sin modelo GLB: el plano sale con el personaje procedural (placeholder)")
    if transiciones < 2:
        problemas.append(f"sólo {transiciones} cambios de estado emocional en toda la pieza (se piden 2)")
    if len(set(planos)) < 2 and not con_movimiento:
        problemas.append("cámara estática: ningún plano cambia y ningún movimiento es distinto de fijo")
    if (tl.get("lipsync") or {}).get("motor") != "rhubarb":
        problemas.append(f"lip-sync sin alineación fonética real: motor={(tl.get('lipsync') or {}).get('motor')}")
    if alineacion and alineacion["cubrimiento"] < 0.6:
        problemas.append(f"boca quieta durante la voz: cubrimiento "
                         f"{alineacion['cubrimiento']:.0%} de {alineacion['habla_s']}s hablados")

    wall_s = max(0.001, time.monotonic() - t0)
    cpu1 = resource.getrusage(resource.RUSAGE_SELF).ru_utime + resource.getrusage(resource.RUSAGE_SELF).ru_stime
    child1 = resource.getrusage(resource.RUSAGE_CHILDREN).ru_utime + resource.getrusage(resource.RUSAGE_CHILDREN).ru_stime
    cpu_s = max(0.0, (cpu1 - cpu0) + (child1 - child0))
    resumen = {
        "archivo": salida.name, "duracion_s": round(got, 2),
        "modo_render": informe.get("modo_render"), "glb": str(glb) if glb else None,
        "morfos_detectados": informe.get("morfos_detectados", 0),
        "huesos_detectados": informe.get("huesos_detectados", 0),
        "frames": informe.get("frames"), "fps_target": FPS,
        "boca": informe.get("boca"),
        "frame_ms_mediana": informe.get("frame_ms_mediana"),
        "render_min": round(informe.get("pared_ms", 0) / 60000, 1),
        "segundos_total": round(wall_s, 1), "cpu_segundos": round(cpu_s, 1),
        "cpu_porcentaje_un_nucleo": round(100 * cpu_s / wall_s, 1),
        "cpu_porcentaje_maquina": round(100 * cpu_s / (wall_s * max(1, os.cpu_count() or 1)), 1),
        "ram_pico_render_mb": informe.get("ram_pico_mb"),
        "ram_pico_python_mb": resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss / 1024,
        "peso_mb": round(salida.stat().st_size / 1e6, 2),
        "motor_lipsync": (tl.get("lipsync") or {}).get("motor"),
        "cues_lipsync": (tl.get("lipsync") or {}).get("n_cues"),
        "alineacion_labial": alineacion,
        "partitura": tl.get("partitura"),
        "cambios_emocionales": sorted({s["emocion"] for s in tl["segmentos"]}),
        "transiciones_emocionales": transiciones,
        "planos": planos,
        "problemas": problemas,
        "status": "pass" if not problemas else "FAIL",
    }
    ep.write_json("render_avatar.json", resumen)
    print("  " + json.dumps(resumen, ensure_ascii=False, indent=1).replace("\n", "\n  "))
    if problemas:
        raise SystemExit(f"QC AVATAR FALLÓ: {problemas}")
    return resumen
