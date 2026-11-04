"""Etapa 5 (mínimo determinista): cartelas de intro/título/fuentes con FFmpeg.

Estas cartelas de texto son el fallback barato para CPU débil. Para una intro con
motion graphics real, reemplazarlas generando clips con video-shotcraft /
awesome-opus5-5-videos (Remotion/Canvas/GSAP) y soltarlos en assets/video/
(intro.mp4, transicion-*.mp4, dataviz-*.mp4): montaje.py los usa automáticamente.
Sólo intros, transiciones, títulos y visualizaciones de datos — nunca escenas narrativas.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

from .. import config
from ..episode import Episode

FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"


def _card(ep: Episode, name: str, lines: list[str], seconds: float, bg: str = "0x0a1a2f|0x103055") -> Path:
    out = ep.dir / "assets" / "video" / name
    if out.exists() and out.stat().st_size > 5000:
        return out  # cartela ya generada o provista por shotcraft
    out.parent.mkdir(parents=True, exist_ok=True)
    n = len(lines)
    # Fondo degradado animado + texto con entrada progresiva (fade por línea).
    c0, c1 = bg.split("|")
    filters = [f"gradients=s={config.VIDEO_W}x{config.VIDEO_H}:nb_colors=2:c0={c0}:c1={c1}"
               f":x0=0:y0=0:x1={config.VIDEO_W}:y1={config.VIDEO_H}:d={seconds}:speed=0.02:r={config.VIDEO_FPS}"]
    for i, l in enumerate(lines):
        size = 58 if i == 0 else 34
        y = f"(h-text_h*{n})/2+{i}*(h*0.10)"
        safe = l.replace("\\", "").replace("'", "").replace(":", "\\:")
        fade_start = 0.3 + i * 0.5
        filters.append(
            f"drawtext=fontfile={FONT}:text='{safe}':fontcolor=white:fontsize={size}:"
            f"x=(w-text_w)/2:y={y}:alpha='if(lt(t,{fade_start}),0,min(1,(t-{fade_start})/0.5))'")
    vf = ",".join(filters[1:])
    cmd = ["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", filters[0],
           "-t", str(seconds), "-vf", vf, "-pix_fmt", "yuv420p",
           "-c:v", "libx264", "-preset", str(config.FFMPEG_PRESET), "-crf", str(config.FFMPEG_CRF), str(out)]
    subprocess.run(cmd, check=True)
    return out


def cartelas(ep: Episode) -> None:
    state = ep.read_state()
    meta = ep.metadata()
    sources = ep.read_json("sources.json")
    pubs = sorted({s["publisher"] for c in sources["claims"] for s in c["sources"]})
    _card(ep, "intro.mp4", ["PULSO CURIOSO", state["title"]], 3.0)
    _card(ep, "outro.mp4", ["Fuentes:", ", ".join(pubs)[:60], "Voz sintética (IA)"], 4.0)
    meta["ai_visuals"] = True  # cartelas generadas por el pipeline
    ep.save_metadata(meta)
    print("  cartelas intro/outro listas en assets/video/ (reemplazables por clips de video-shotcraft)")
