"""Etapa de video vertical 9:16 (Shorts / Reels) con gramatica de corte medida.

Diferencia con montaje.py: aca el plano NO es el parrafo. Un plano es un sintagma nominal de
3-6 palabras (1,1-2,8 s) y el presentador vuelve cada <=3,5 s. Eso es lo que el pipeline viejo
hacia mal: 8 parrafos = 8 planos de 15-25 segundos congelados, y un Short no sobrevive a eso.

Layoutes (percentiles medidos en herpes-edit-kit, docs/EDITING-PLAYBOOK.md):
  - b-roll completo 50-55%   -> imagen del hecho con empuje de camara (zoompan)
  - presentador    ~45%      -> Pulso en el estudio, el personaje recurrente del canal
  - tarjeta de numero        -> el conteo del formato "cuenta regresiva", en pantalla
Todo plano se mueve: no se emite ningun cuadro congelado.

Sin GPU y sin modelos pesados: FFmpeg + la voz Piper del canal. La cama musical se sintetiza
localmente (lavfi), es autoría propia y no necesita licencia ajena.
"""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

from .. import config, formatos
from ..episode import Episode

FUENTE = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
TIPOS = ("broll", "presentador", "numero")


def _run(cmd: list[str]) -> None:
    subprocess.run(cmd, check=True, capture_output=True, text=True)


def _dur(path: Path) -> float:
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                        "-of", "default=nw=1:nk=1", str(path)], capture_output=True, text=True)
    return float(r.stdout.strip() or 0)


def _esc(texto: str) -> str:
    return (texto.replace("\\", "").replace("'", "").replace(":", "\\:")
            .replace("%", "\\%").replace(",", "\\,"))


def _asignar(shots: list[dict], hay_imagen: bool) -> None:
    """Reparte layouts para clavar ~45% de presentador y ningun hueco >3,5 s sin él."""
    for i, s in enumerate(shots):
        tiene_numero = bool(re.search(r"\b\d+\b", s["texto"]))
        if tiene_numero and hay_imagen is False:
            s["tipo"] = "numero"
        elif not hay_imagen:
            s["tipo"] = "presentador"
        else:
            s["tipo"] = "presentador" if i % 2 == 0 else "broll"
        if s["tipo"] == "broll" and i and shots[i - 1]["tipo"] == "broll" \
                and sum(x["dur"] for x in shots[max(0, i - 2):i]) > config.AUSENCIA_MAX_S:
            s["tipo"] = "presentador"  # el presentador nunca esta ausente mas de 3,5 s


def _plano(shots: list[dict], idx: int, img: Path | None, out: Path) -> None:
    s = shots[idx]
    W, H, FPS = config.SHORT_W, config.SHORT_H, config.SHORT_FPS
    base = ["ffmpeg", "-y", "-v", "error", "-t", f"{s['dur']}"]
    enc = ["-c:v", "libx264", "-preset", str(config.FFMPEG_PRESET), "-crf", str(config.FFMPEG_CRF),
           "-pix_fmt", "yuv420p", "-r", str(FPS), "-an", str(out)]
    marcos = int(s["dur"] * FPS)
    empuje = (f"zoompan=z='min(zoom+0.0035,1.14)':d={marcos}:s={W}x{H}:fps={FPS}")

    if s["tipo"] == "presentador":
        fondo = config.MASCOTA_ESTUDIO if config.MASCOTA_ESTUDIO.exists() else None
        capa = (f"[0:v]scale={W}x{H}:force_original_aspect_ratio=increase,crop={W}:{H},{empuje}[bg];"
                f"[1:v]scale={int(W*0.86)}:-1:m=laplacens:flags=lanczos[pp];[bg][pp]overlay=(W-w)/2:H*0.16")
        _run(base + ["-loop", "1", "-framerate", str(FPS), "-i", str(fondo or config.MASCOTA_HERO),
                     "-loop", "1", "-framerate", str(FPS), "-i", str(config.MASCOTA_HERO),
                     "-filter_complex", capa + "[v]", "-map", "[v]"] + enc)
        return

    if img is not None:
        _run(base + ["-loop", "1", "-framerate", str(FPS), "-i", str(img),
                     "-vf", (f"scale=2600:4620:force_original_aspect_ratio=increase,crop=2600:4620,"
                             f"{empuje}")] + enc)
        return

    # sin imagen: tarjeta de dato puro, movimiento de entrada + fondo degradado (nunca congelado)
    grande = s["numero"] or s["texto"][:34]
    _run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi",
          "-i", f"gradients=s={W}x{H}:nb_colors=2:c0=0x0a1a2f:c1=0x103055"
                f":x0=0:y0=0:x1={W}:y1={H}:d={s['dur']}:speed=0.05:r={FPS}",
          "-t", f"{s['dur']}", "-vf",
          (f"drawtext=fontfile={FUENTE}:text='{_esc(grande)}':fontcolor=white:fontsize=150:"
           f"x=(w-text_w)/2:y=(h-text_h)/2:alpha='min(1,t/0.35)',"
           f"zoompan=z='min(zoom+0.002,1.06)':d={marcos}:s={W}x{H}:fps={FPS}")] + enc)


def narracion_corta(ep: Episode, bloques: list[str], pad_entre_s: float = 0.12) -> Path:
    """Piper por bloque + concat con gap corto (la pausa larga de 0,35 s era del documental)."""
    from . import narracion
    d = ep.dir / "assets" / "audio" / "short"
    d.mkdir(parents=True, exist_ok=True)
    for old in d.glob("*.wav"):
        old.unlink()
    wavs = []
    for i, texto in enumerate(bloques):
        out = d / f"bloq-{i:02d}.wav"
        narracion._piper(texto, out, length_scale=config.PIPER_LENGTH_SCALE_SHORT,
                         sentence_silence=pad_entre_s)
        wavs.append(out)
    joined = d / "voz.wav"
    pads = []
    cmd = ["ffmpeg", "-y", "-v", "error"]
    for i, w in enumerate(wavs):
        cmd += ["-i", str(w)]
        delay = int(pad_entre_s * 1000) if i else 0
        pads.append(f"[{i}:a]adelay={delay}|{delay}[a{i}]")
    cmd += ["-filter_complex", ";".join(pads) + ";" + "".join(f"[a{i}]" for i in range(len(wavs)))
            + "concat=n=%d:v=0:a=1[out]" % len(wavs), "-map", "[out]",
            "-ar", "22050", "-ac", "1", str(joined)]
    _run(cmd)
    return joined


def _cama(out: Path, segundos: float) -> None:
    """Cama musical sintetizada localmente (lavfi): autoría propia, sin licencia ajena.

    Progresión Am-F-C-G (la más usada en contenido emocional/viral) rotando
    cada 4 s, con un drone grave y ruido marrón como textura. Sin copyright,
    sin APIs externas, sin costo. El volumen final queda bajo la voz (0.12)
    para no competir con la narración.
    """
    chord_expr = ("if(between(t,0,4),sin(2*PI*220*t)+sin(2*PI*261.63*t)+sin(2*PI*329.63*t),"
                  "if(between(t,4,8),sin(2*PI*174.61*t)+sin(2*PI*220*t)+sin(2*PI*261.63*t),"
                  "if(between(t,8,12),sin(2*PI*261.63*t)+sin(2*PI*329.63*t)+sin(2*PI*392*t),"
                  "sin(2*PI*196*t)+sin(2*PI*246.94*t)+sin(2*PI*293.66*t))))*0.06")
    bass_expr = "sin(2*PI*55*t)*0.08"
    fade_out_st = max(0.1, segundos - 2.0)
    cmd = ["ffmpeg", "-y", "-v", "error",
           "-f", "lavfi", "-i", "aevalsrc=exprs='{}':s=22050".format(chord_expr),
           "-f", "lavfi", "-i", "aevalsrc=exprs='{}':s=22050".format(bass_expr),
           "-f", "lavfi", "-i", "anoisesrc=color=brown:amplitude=0.04",
           "-t", str(segundos),
           "-filter_complex",
           "[0:a]lowpass=f=1200,tremolo=f=0.3:d=0.25,afade=t=in:d=2.0,afade=t=out:st={:.2f}:d=2.0,aresample=22050[a0];"
           "[1:a]lowpass=f=200,afade=t=in:d=2.0,afade=t=out:st={:.2f}:d=2.0,aresample=22050[a1];"
           "[2:a]lowpass=f=300,volume=0.5,afade=t=in:d=2.0,afade=t=out:st={:.2f}:d=2.0,aresample=22050[a2];"
           "[a0][a1][a2]amix=inputs=3:duration=first[a]".format(
               fade_out_st, fade_out_st, fade_out_st),
           "-map", "[a]", "-ar", "22050", "-ac", "1", "-c:a", "aac", "-b:a", "64k",
           "-t", str(segundos), str(out)]
    _run(cmd)


def render(ep: Episode, perfil_clave: str = "short_vertical") -> dict:
    """De `script.txt` (bloques ya narrados o por narrar) a un MP4 vertical terminado."""
    perfil = formatos.perfil(perfil_clave)
    W, H, FPS = perfil.ancho, perfil.alto, perfil.fps
    config.SHORT_W, config.SHORT_H, config.SHORT_FPS = W, H, FPS
    script = ep.read_text("script.txt")
    from .narracion import _segments
    bloques = _segments(script)
    if not bloques:
        raise SystemExit("short: script.txt sin bloques narrables")

    voz = narracion_corta(ep, bloques)
    total = _dur(voz)

    # presupuesto de planos: las duraciones reales de cada bloque mandan sobre la teoria
    d_bloque = []
    d = ep.dir / "assets" / "audio" / "short"
    for i in range(len(bloques)):
        w = d / f"bloq-{i:02d}.wav"
        d_bloque.append(_dur(w))
    shots: list[dict] = []
    for texto, dur_real in zip(bloques, d_bloque):
        trozos = formatos.cortes(texto)
        pesoss = [max(1, len(t.split())) for t in trozos]
        suma = sum(pesoss) or 1
        for j, t in enumerate(trozos):
            shots.append({"texto": t, "dur": round(dur_real * pesoss[j] / suma, 3),
                          "numero": (t[:24] if re.search(r"\b\d+\b", t) else ""), "tipo": "broll"})

    imagenes = sorted(ep.dir.glob("assets/img/*.jpg")) + sorted(ep.dir.glob("assets/img/*.png"))
    hay_imagen = bool(imagenes)
    _asignar(shots, hay_imagen)

    partes = ep.dir / "renders" / "short-parts"
    partes.mkdir(parents=True, exist_ok=True)
    for old in partes.glob("*.mp4"):
        old.unlink()
    for i, s in enumerate(shots):
        img = imagenes[i % len(imagenes)] if (hay_imagen and s["tipo"] == "broll") else None
        _plano(shots, i, img, partes / f"p-{i:03d}.mp4")

    lista = partes / "order.txt"
    lista.write_text("".join(f"file '{partes / f'p-{i:03d}.mp4'}'\n" for i in range(len(shots))),
                     encoding="utf-8")
    mudo = ep.dir / "renders" / "short-silent.mp4"
    _run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(lista),
          "-c", "copy", str(mudo)])

    lecho = ep.dir / "assets" / "audio" / "short" / "cama.m4a"
    if perfil.music_bed:
        _cama(lecho, total)
    salida = ep.dir / "renders" / f"{ep.slug}-short-9x16.mp4"
    mezcla = (f"[1:a]volume=1.0[vo];[2:a]volume=0.9[mu];[vo][mu]amix=inputs=2:duration=first:"
              f"dynaudnorm=f=200[a]") if perfil.music_bed else "[1:a][a]"
    cmd = ["ffmpeg", "-y", "-v", "error", "-i", str(mudo), "-i", str(voz)]
    if perfil.music_bed:
        cmd += ["-i", str(lecho)]
    cmd += ["-filter_complex", mezcla if perfil.music_bed else "[1:a]aformat=channel_layouts=mono[a]",
            "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-b:a", "96k",
            "-shortest", "-movflags", "+faststart", str(salida)]
    _run(cmd)

    info = json.loads(subprocess.run(
        ["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(salida)],
        capture_output=True, text=True).stdout)
    tipos = {}
    for s in shots:
        tipos[s["tipo"]] = tipos.get(s["tipo"], 0) + 1
    streams = {s["codec_type"]: s for s in info["streams"]}
    got = float(info["format"]["duration"])
    problemas = []
    if "video" not in streams or "audio" not in streams:
        problemas.append("faltan streams de video/audio")
    if (streams.get("video", {}).get("width"), streams.get("video", {}).get("height")) != (W, H):
        problemas.append(f"resolucion {streams.get('video',{}).get('width')}x"
                         f"{streams.get('video',{}).get('height')} != {W}x{H}")
    if not (perfil.segundos_min - 6 <= got <= perfil.segundos_max + 8):
        problemas.append(f"duracion {got:.1f}s fuera del perfil {perfil.segundos_min}-{perfil.segundos_max}s")
    plano_max = max(s["dur"] for s in shots)
    if plano_max > formatos.REGLAS_CORTE["plano_max_s"] + 0.6:
        problemas.append(f"plano de {plano_max:.1f}s: mas largo que la ventana medida (2,8s)")

    qc = {"file": salida.name, "duracion_s": round(got, 2), "planos": len(shots),
          "plano_max_s": round(plano_max, 2), "layoutes": tipos,
          "presentador_pct": round(100 * tipos.get("presentador", 0) / len(shots)),
          "problemas": problemas, "status": "pass" if not problemas else "FAIL"}
    ep.write_json("qc-short.json", qc)
    ep.write_json("timeline-short.json", {"segments": shots, "total_s": round(got, 2),
                                          "voz_s": round(total, 2),
                                          "reglas": formatos.REGLAS_CORTE})
    if problemas:
        ep.set_stage("corto", "qc_fail")
        raise SystemExit(f"QC SHORT FALLÓ: {problemas}")
    meta = ep.metadata()
    meta.update({"short_path": str(salida.relative_to(ep.dir)), "short_duration_s": round(got, 2),
                 "short_planos": len(shots), "synthetic_content": True})
    ep.save_metadata(meta)
    ep.set_stage("corto", "done")
    print(f"  short: {salida.name} {got:.1f}s | {len(shots)} planos (max {plano_max:.1f}s) | "
          f"presentador {qc['presentador_pct']}% | QC PASS")
    return qc
