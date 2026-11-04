"""Etapa 6: recorte de los formatos de salida definidos en CONTEXTO.md.

- YouTube: 1 documental dividido en 3 videos completos (cortes en bordes de segmento).
- TikTok: tráiler vertical de 1:30.
- Instagram: tráiler vertical de 30 s + artículo de 1200-3000 palabras para el feed.
"""
from __future__ import annotations

import json
import os
import resource
import subprocess
import time
from pathlib import Path

from .. import config, llm
from ..episode import Episode


def _run(cmd: list[str]) -> None:
    subprocess.run(cmd, check=True, capture_output=True, text=True)


def _duration(path: Path) -> float:
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                        "-of", "default=nw=1:nk=1", str(path)], capture_output=True, text=True)
    return float(r.stdout.strip())


def partes_youtube(ep: Episode, main: Path, timeline: dict) -> list[Path]:
    segs = timeline["segments"]
    total = timeline["total_s"]
    # 3 cortes snapped a bordes de segmento, lo más cerca posible de tercios.
    targets = [total / 3, 2 * total / 3]
    boundaries, prev = [], 0.0
    for tgt in targets:
        best = min(segs, key=lambda s: abs(s["start"] - tgt))
        cut = max(prev + 1.0, best["start"])
        boundaries.append(cut)
        prev = cut
    ranges = list(zip([0.0] + boundaries, boundaries + [total]))
    outs = []
    for i, (a, b) in enumerate(ranges, 1):
        dst = ep.dir / "derivados" / f"yt-parte-{i}.mp4"
        _run(["ffmpeg", "-y", "-v", "error", "-ss", f"{a}", "-i", str(main), "-t", f"{b - a}",
              "-c:v", "libx264", "-preset", str(config.FFMPEG_PRESET), "-crf", str(config.FFMPEG_CRF),
              "-c:a", "aac", "-movflags", "+faststart", str(dst)])
        outs.append(dst)
    return outs


def trailer_vertical(ep: Episode, main: Path, seconds: float, dst: Path, label: str) -> None:
    dur = min(seconds, _duration(main) - 3.0)
    _run(["ffmpeg", "-y", "-v", "error", "-ss", "3.0", "-i", str(main), "-t", f"{dur}",
          "-vf", (f"scale=1080:1920:force_original_aspect_ratio=decrease,"
                  f"pad=1080:1920:(ow-iw)/2:(oh-ih)/2:black,"
                  f"drawtext=fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf:"
                  f"text='{label}':fontcolor=white:fontsize=52:x=(w-text_w)/2:y=140:"
                  f"box=1:boxcolor=black@0.5"),
          "-c:v", "libx264", "-preset", config.FFMPEG_PRESET, "-crf", "23",
          "-c:a", "aac", "-ac", "1", str(dst)])


def articulo_instagram(ep: Episode) -> Path:
    script = ep.read_text("script.txt")
    sources = ep.read_json("sources.json")
    src_list = "\n".join(f"- {s['url']}" for c in sources["claims"] for s in c["sources"])
    title = ep.read_state()["title"]
    prompt = (
        f"Redactá un artículo de Instagram (feed) en español rioplatense sobre: {title}. "
        "Expandí el guion con contexto, método y por qué importa; sólo hechos respaldados por "
        "las fuentes; separá reconstrucciones didácticas. 1200 a 3000 palabras, markdown con "
        "3-6 subtítulos, cierre con lista de fuentes.\n\nGUION:\n" + script + "\n\nFUENTES:\n" + src_list
    )
    for attempt in range(3):
        text = llm.chat([{"role": "user", "content": prompt}], temperature=0.7,
                        max_tokens=6000, tag="articulo", episode=ep.slug)
        n = len(text.split())
        if config.IG_ARTICLE_MIN_WORDS <= n <= config.IG_ARTICLE_MAX_WORDS:
            dst = ep.dir / "publicacion" / "articulo-instagram.md"
            dst.parent.mkdir(exist_ok=True)
            dst.write_text(text, encoding="utf-8")
            print(f"  artículo: {n} palabras -> publicacion/articulo-instagram.md")
            return dst
        print(f"  artículo {n} palabras fuera de rango (intento {attempt+1}/3), regenerando…")
        prompt += f"\n\nCORRECCIÓN: la versión anterior tuvo {n} palabras; apuntá a 1800-2400."
    raise SystemExit("No se logró un artículo de 1200-3000 palabras en 3 intentos.")


def _derivar_keyframe(ep: Episode, main: Path, ruta: str = "keyframe") -> None:
    """Paquete de revisión YouTube/Facebook para un render audiovisual completo."""
    t0 = time.time()
    cpu0 = resource.getrusage(resource.RUSAGE_SELF).ru_utime + resource.getrusage(resource.RUSAGE_SELF).ru_stime
    child0 = resource.getrusage(resource.RUSAGE_CHILDREN).ru_utime + resource.getrusage(resource.RUSAGE_CHILDREN).ru_stime
    out_dir = ep.dir / "derivados"
    out_dir.mkdir(exist_ok=True)
    reel = out_dir / "facebook-reel.mp4"
    # La ruta keyframe ya es vertical: ampliar cuadro completo conserva personaje y tipografía.
    # Para renders horizontales antiguos, mantener el fallback de fondo difuminado.
    probe_in = json.loads(subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
         "stream=width,height", "-of", "json", str(main)],
        capture_output=True, text=True, check=True).stdout)
    vin = next((s for s in probe_in.get("streams", []) if s.get("width") and s.get("height")), {})
    if vin.get("height", 0) > vin.get("width", 0):
        cmd = ["ffmpeg", "-y", "-v", "error", "-i", str(main), "-vf",
               "scale=1080:1920:flags=lanczos,setsar=1", "-map", "0:v:0", "-map", "0:a?",
               "-c:v", "libx264", "-preset", str(config.FFMPEG_PRESET), "-crf",
               str(config.FFMPEG_CRF), "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k",
               "-ar", "44100", "-shortest", "-movflags", "+faststart", str(reel)]
    else:
        vf = ("[0:v]scale=480:854:force_original_aspect_ratio=increase,"
              "crop=480:854,boxblur=10:2,scale=1080:1920,eq=brightness=-0.28[bg];"
              "[0:v]scale=1080:-2[fg];"
              "[bg][fg]overlay=(W-w)/2:(H-h)/2,setsar=1[v]")
        cmd = ["ffmpeg", "-y", "-v", "error", "-i", str(main), "-filter_complex", vf,
          "-map", "[v]", "-map", "0:a?", "-c:v", "libx264", "-preset",
          str(config.FFMPEG_PRESET), "-crf", str(config.FFMPEG_CRF), "-pix_fmt", "yuv420p",
          "-c:a", "aac", "-b:a", "128k", "-ar", "44100", "-shortest", "-movflags",
          "+faststart", str(reel)]
    _run(cmd)
    dur = _duration(reel)
    probe = json.loads(subprocess.run(
        ["ffprobe", "-v", "error", "-show_streams", "-of", "json", str(reel)],
        capture_output=True, text=True, check=True).stdout)
    video = next((s for s in probe["streams"] if s["codec_type"] == "video"), {})
    tipos = {s["codec_type"] for s in probe["streams"]}
    problemas = []
    if (video.get("width"), video.get("height")) != (1080, 1920):
        problemas.append(f"resolución {video.get('width')}x{video.get('height')} != 1080x1920")
    if "audio" not in tipos:
        problemas.append("falta audio")
    if abs(dur - _duration(main)) > 0.8:
        problemas.append("duración vertical no coincide con el master")
    wall = max(0.001, time.time() - t0)
    cpu1 = resource.getrusage(resource.RUSAGE_SELF).ru_utime + resource.getrusage(resource.RUSAGE_SELF).ru_stime
    child1 = resource.getrusage(resource.RUSAGE_CHILDREN).ru_utime + resource.getrusage(resource.RUSAGE_CHILDREN).ru_stime
    cpu_s = max(0.0, (cpu1 - cpu0) + (child1 - child0))
    cpus = max(1, os.cpu_count() or 1)
    ram_kb = max(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                 resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss)
    render_info = {
        "archivo": reel.name, "ruta": ruta, "duracion_s": round(dur, 2),
        "resolucion": f"{video.get('width')}x{video.get('height')}",
        "peso_mb": round(reel.stat().st_size / 1048576, 2),
        "segundos_total": round(wall, 1), "cpu_segundos": round(cpu_s, 1),
        "cpu_porcentaje_un_nucleo": round(100 * cpu_s / wall, 1),
        "cpu_porcentaje_maquina": round(100 * cpu_s / (wall * cpus), 1),
        "ram_pico_mb": round(ram_kb / 1024, 1), "problemas": problemas,
        "status": "pass" if not problemas else "FAIL",
    }
    ep.write_json("render_derivados.json", render_info)
    manifest = {
        "ruta": ruta,
        "youtube_main": {"archivo": str(main.relative_to(ep.dir)),
                         "duration_s": round(_duration(main), 1)},
        "facebook_reel": {"archivo": reel.name, "duration_s": round(_duration(reel), 1),
                           "resolucion": "1080x1920"},
        "yt_partes": [],
        "vertical": "9:16",
    }
    render_k = ep.artifacts / "render_keyframes.json"
    if render_k.exists():
        datos = ep.read_json("render_keyframes.json")
        if datos.get("archivo_storyboard"):
            manifest["storyboard_video"] = {"archivo": datos["archivo_storyboard"],
                                             "contacto": datos.get("contacto")}
    ep.write_json("derivados-manifest.json", manifest)
    ep.set_stage("derivados", "done")
    print(f"  derivados keyframe: YouTube completo + Facebook vertical -> {reel.name} | "
          f"{render_info['duracion_s']}s, {render_info['peso_mb']} MB, "
          f"RAM {render_info['ram_pico_mb']} MB, {render_info['segundos_total']}s, "
          f"CPU {render_info['cpu_porcentaje_maquina']}% máquina")


def derivar(ep: Episode) -> None:
    main = ep.dir / "renders" / f"{ep.slug}-main.mp4"
    if not main.exists():
        keyframe = ep.dir / "renders" / f"{ep.slug}-keyframe.mp4"
        if keyframe.exists():
            _derivar_keyframe(ep, keyframe)
            return
        avatar = ep.dir / "renders" / f"{ep.slug}-avatar.mp4"
        if avatar.exists():
            _derivar_keyframe(ep, avatar, ruta="avatar_fallback")
            return
        raise SystemExit(f"No existe render principal ni keyframe para {ep.slug}.")
    timeline = ep.read_json("timeline.json")
    out_dir = ep.dir / "derivados"
    out_dir.mkdir(exist_ok=True)

    partes = partes_youtube(ep, main, timeline)
    tt = out_dir / "tiktok-trailer-90s.mp4"
    ig = out_dir / "instagram-trailer-30s.mp4"
    trailer_vertical(ep, main, config.TIKTOK_TEASER_S, tt, "PULSO CURIOSO - adelanto")
    trailer_vertical(ep, main, config.IG_TEASER_S, ig, "PULSO CURIOSO - adelanto")
    articulo_instagram(ep)

    manifest = {
        "yt_partes": [{"archivo": str(p.name), "duration_s": round(_duration(p), 1)} for p in partes],
        "tiktok": {"archivo": tt.name, "duration_s": round(_duration(tt), 1)},
        "instagram_video": {"archivo": ig.name, "duration_s": round(_duration(ig), 1)},
        "instagram_articulo": "publicacion/articulo-instagram.md",
        "vertical": "1080x1920", "youtube": f"{config.VIDEO_W}x{config.VIDEO_H}",
    }
    ep.write_json("derivados-manifest.json", manifest)
    ep.set_stage("derivados", "done")
    print(f"  derivados: {len(partes)} partes YT + TikTok 90s + IG 30s + artículo")
