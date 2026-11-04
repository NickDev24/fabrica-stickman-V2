"""Etapa 4: montaje segmento-a-segmento con FFmpeg tuneado + QC ffprobe.

Cada segmento del guion tiene su audio (assets/audio/segments/seg-NNN.wav). Visual por
segmento: assets/img/seg-NNN.{jpg,png} (Ken Burns), assets/video/seg-NNN.mp4 (clip de
video-shotcraft o material propio) o cartela neutra de respaldo.
Hook de OpenMontage: si existe projects/<slug>/openmontage/, se deja marcado para que el
agente lo procese con la skill; el render FFmpeg determinista siempre ocurre igual
(garantía de salida en CPU débil).
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

from .. import config
from ..episode import Episode
from . import graphics


def _run(cmd: list[str]) -> None:
    subprocess.run(cmd, check=True, capture_output=True, text=True)


def _ts(s: float) -> str:
    h, r = divmod(s, 3600)
    m, sec = divmod(r, 60)
    return f"{int(h)}:{int(m):02d}:{sec:05.2f}"


ASS_FORMAT = "Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text"


def validar_ass(texto: str, donde: str) -> None:
    """Cada Dialogue debe traer tantos campos como declara el Format de [Events].

    Si Format enlista menos campos que el diálogo, libass toma el resto de la línea como
    texto y quema ",0,0,0,,palabra" en pantalla (el bug de pulso-001-main.mp4).
    """
    eventos = texto.split("[Events]")[-1]
    fmt = next((l for l in eventos.splitlines() if l.startswith("Format:")), None)
    if fmt is None:
        raise ValueError(f"{donde}: ASS sin Format: en [Events]")
    n = len(fmt[len("Format:"):].split(","))
    if n != len(ASS_FORMAT.split(",")):
        raise ValueError(f"{donde}: Format declara {n} campos, se esperan {ASS_FORMAT.count(',') + 1}")
    for l in eventos.splitlines():
        if not l.startswith("Dialogue:"):
            continue
        k = len(l[len("Dialogue:"):].split(","))
        if k < n:
            raise ValueError(f"{donde}: Dialogue con {k} campos < Format {n}: {l[:60]!r}")


def _ass(seg_text: str, dur: float, path: Path) -> Path:
    """Subtítulos en chunks de ~6 palabras repartidos sobre la duración del segmento."""
    words = seg_text.split()
    chunks = [" ".join(words[i:i + 6]) for i in range(0, len(words), 6)] or [""]
    step = dur / len(chunks)
    path.parent.mkdir(parents=True, exist_ok=True)
    events = "\n".join(
        f"Dialogue: 0,{_ts(i * step)},{_ts((i + 1) * step)},Default,,0,0,0,,{c.replace('{', '').replace('}', '')}"
        for i, c in enumerate(chunks))
    texto = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {config.VIDEO_W}
PlayResY: {config.VIDEO_H}

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, OutlineColour, BackColour, Bold, Italic, BorderStyle, Outline, Shadow, Alignment, MarginV, Encoding
Style: Default, DejaVu Sans, 46, &H00FFFFFF, &H00101010, &H80000000, 1, 0, 1, 3, 1, 2, 55, 1

[Events]
Format: {ASS_FORMAT}
{events}
"""
    validar_ass(texto, str(path))
    path.write_text(texto, encoding="utf-8")
    return path


def _probe(path: Path) -> dict:
    r = subprocess.run(["ffprobe", "-v", "error", "-show_streams", "-show_format",
                        "-of", "json", str(path)], capture_output=True, text=True)
    return json.loads(r.stdout)


def _segment_visual(ep: Episode, i: int, dur: float, out: Path, seg_text: str) -> str:
    sub = _ass(seg_text, dur, ep.dir / "assets" / "sub" / f"seg-{i:03d}.ass")
    subf = f",subtitles={sub}"
    used = "cartela"
    img = next((p for p in ep.dir.glob(f"assets/img/seg-{i:03d}.*") if p.suffix in (".jpg", ".jpeg", ".png")), None)
    vid = ep.dir / "assets" / "video" / f"seg-{i:03d}.mp4"
    base = ["ffmpeg", "-y", "-v", "error"]
    enc = ["-c:v", "libx264", "-preset", str(config.FFMPEG_PRESET), "-crf", str(config.FFMPEG_CRF),
           "-pix_fmt", "yuv420p", "-r", str(config.VIDEO_FPS), "-an", str(out)]
    W, H = f"{config.VIDEO_W}", f"{config.VIDEO_H}"
    if vid.exists():
        _run(base + ["-i", str(vid), "-t", f"{dur}",
                     "-vf", f"scale={W}:{H}:force_original_aspect_ratio=decrease,pad={W}:{H}:(ow-iw)/2:(oh-ih)/2" + subf] + enc)
        used = "video"
    elif img:
        frames = int(dur * config.VIDEO_FPS)
        _run(base + ["-loop", "1", "-framerate", str(config.VIDEO_FPS), "-i", str(img), "-t", f"{dur}",
                     "-vf", (f"scale=3200:1800:force_original_aspect_ratio=increase,crop=3200:1800,"
                             f"zoompan=z='min(zoom+0.0006,1.12)':d={frames}:s={W}x{H}:fps={config.VIDEO_FPS}" + subf),
                     ] + enc)
        used = "imagen"
    else:
        _run(base + ["-f", "lavfi", "-i", f"color=c=0x1c222a:s={W}x{H}:r={config.VIDEO_FPS}",
                     "-t", f"{dur}", "-vf", "format=yuv420p" + subf] + enc)
    return used


def montar(ep: Episode) -> None:
    meta = ep.metadata()
    durations = meta.get("segment_durations_s")
    if not durations:
        raise SystemExit("Falta la narración: corré primero 'narrar'.")
    graphics.cartelas(ep)

    from .narracion import _segments
    seg_texts = _segments(ep.read_text("script.txt"))

    parts = ep.dir / "renders" / "parts"
    parts.mkdir(parents=True, exist_ok=True)
    timeline, used_kinds = [], []
    t = 3.0  # offset de la intro
    for i, d in enumerate(durations):
        out = parts / f"seg-{i:03d}.mp4"
        text = seg_texts[i] if i < len(seg_texts) else ""
        used_kinds.append(_segment_visual(ep, i, d, out, text))
        timeline.append({"segment": i, "start": round(t, 2), "duration": round(d, 2),
                         "visual": used_kinds[-1]})
        t += d
    outro = ep.dir / "assets" / "video" / "outro.mp4"
    total_video = t + 4.0

    order = [ep.dir / "assets" / "video" / "intro.mp4"] + [parts / f"seg-{i:03d}.mp4" for i in range(len(durations))] + [outro]
    listfile = parts / "order.txt"
    listfile.write_text("".join(f"file '{p}'\n" for p in order), encoding="utf-8")
    silent = ep.dir / "renders" / "video-silent.mp4"
    _run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(listfile),
          "-c", "copy", str(silent)])

    narration = ep.dir / meta["narration_path"]
    main = ep.dir / "renders" / f"{ep.slug}-main.mp4"
    _run(["ffmpeg", "-y", "-v", "error", "-i", str(silent), "-i", str(narration),
          "-filter_complex", "[1:a]adelay=3000|3000,apad,aformat=sample_fmts=fltp:channel_layouts=mono[a]",
          "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-b:a", "96k",
          "-shortest", str(main)])

    # QC determinista (reemplazo local de ffmpeg-skill: mismos checks con ffprobe)
    info = _probe(main)
    streams = {s["codec_type"] for s in info["streams"]}
    got = float(info["format"]["duration"])
    problems = []
    if "video" not in streams:
        problems.append("sin stream de video")
    if "audio" not in streams:
        problems.append("sin stream de audio")
    if abs(got - total_video) > 1.0 and abs(got - sum(durations) - 3.0) > 1.0:
        problems.append(f"duración {got:.1f}s inesperada (esperada ~{total_video:.1f}s)")
    qc = {"file": str(main.relative_to(ep.dir)), "duration_s": round(got, 2),
          "streams": sorted(streams), "problems": problems, "status": "pass" if not problems else "FAIL"}
    ep.write_json("qc.json", qc)
    ep.write_json("timeline.json", {"segments": timeline, "intro_s": 3.0,
                                    "outro_s": 4.0, "total_s": round(total_video, 2)})
    if (ep.dir / "openmontage").exists():
        print("  nota: openmontage/ presente — procesalo con la skill OpenMontage para una variante")
    if problems:
        ep.set_stage("montaje", "qc_fail")
        raise SystemExit(f"QC FALLÓ: {problems}")
    meta["synthetic_content"] = True
    ep.save_metadata(meta)
    ep.set_stage("montaje", "done")
    print(f"  render: {main.name} {got:.1f}s | visuales: {dict((k, used_kinds.count(k)) for k in set(used_kinds))}")
    print("  QC ffprobe: PASS")
