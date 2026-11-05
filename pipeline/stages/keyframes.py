"""Etapa keyframe: el motor visual del formato viral (1 imagen cada ~1,6 s + cámara encima).

Qué reemplaza y por qué
----------------------
Las rutas anteriores dibujaban al personaje con primitivas (SVG/canvas) o con un avatar 3D
en SwiftShader. Medido en el B950: ambas dan un maniquí o un muñeco de plástico, y ningún
ajuste de "look" lo arregla — el problema es la fuente de imagen, no el estilo.

Este formato viral no renderiza fotogramas: muestra 30-40 IMÁGENES POR MINUTO y la cámara
se las mueve encima. Acá esa imagen la genera un modelo de difusión hosted gratis
(pipeline/imagen.py, medido 2,1 s/frame con flux-1-schnell) y el movimiento lo hace FFmpeg
sobre la foto fija (zoom/paneo/tumbo), que es exactamente lo que hace el formato.

Cadena: script narrado -> beats (factory/acting/beats.py) -> 1 keyframe por beat ->
plano con cámara -> hoja de contactos (antes de renderizar, para aprobar) -> concat ->
subtítulos + palabra pop -> voz + cama musical + SFX por corte -> loudnorm -14 LUFS.

CPU-only, sin GPU, sin Blender, sin librerías de pago.
"""
from __future__ import annotations

import json
import math
import os
import resource
import subprocess
import time
from pathlib import Path

from .. import config, imagen
from ..episode import Episode

# El máster documental nace en 9:16. Se conserva el presupuesto de píxeles
# del anterior 1280x720 para que el B950 no multiplique el costo del render.
W, H = 720, 1280
# 30 fps y no 60: en el B950 el zoompan duplica el costo de encode por cada fps extra y el
# movimiento sobre foto fija no gana nada visible pasados los 30. KF_FPS=60 igual funciona.
KF_FPS = int(config.os.environ.get("KF_FPS", "30"))
BASE_W, BASE_H = 810, 1440       # lienzo interno vertical antes de la cámara
KF_S = 1024                       # flux devuelve 1024x1024
KF_916_W = 576                    # recorte 9:16 nativo del cuadrado

# Cámara: cada movimiento es una expresión de zoompan sobre la foto fija.
# Los separadores SON dos puntos: dentro de un filtro, la coma cerraría zoompan y abriría
# otro filtro, y ffmpeg revienta con "No option name near ..." (medido).
CAMARA = {
    "push":       "z='min(zoom+0.0007,1.08)'",
    "push_lento": "z='min(zoom+0.0003,1.04)'",
    "pull":       "z='if(eq(on,1),1.08,max(zoom-0.0007,1.0))'",
    "pan":        "z='1.06':x='(iw-iw/zoom)*on/{n}':y='ih/2-(ih/zoom/2)'",
    "shake":      "z='1.06':x='iw/2-(iw/zoom/2)+18*sin(on/2.2)':y='ih/2-(ih/zoom/2)+12*sin(on/1.4)'",
    "fijo":       "z='1.03'",
}


def _run(cmd: list[str]) -> None:
    subprocess.run(cmd, check=True, capture_output=True, text=True)


def _dur(path: Path) -> float:
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                        "-of", "json", str(path)], capture_output=True, text=True)
    return float(json.loads(r.stdout)["format"]["duration"])


def _ts(s: float) -> str:
    h, r = divmod(max(0.0, s), 3600)
    m, sec = divmod(r, 60)
    return f"{int(h)}:{int(m):02d}:{sec:05.2f}"


def _recorte(fps: bool = True) -> str:
    """9:16 centrado para CUALQUIER fuente (flux 1024², gemini 1408×768…) al lienzo 810×1440."""
    base = ("crop=w='min(iw,ih*9/16)':h='min(ih,iw*16/9)'"
            ":x='(iw-ow)/2':y='(ih-oh)/2',scale={BASE_W}:{BASE_H}").format(BASE_W=BASE_W, BASE_H=BASE_H)
    return f"{base},fps={KF_FPS}" if fps else base


# --------------------------------------------------------------------------- beats
def beats_de(ep: Episode, forzar: bool = False) -> list[dict]:
    """Beats desde el audio REAL de la narración; quedan en artifacts/beats.json."""
    guardado = ep.artifacts / "beats.json"
    if guardado.exists() and not forzar:
        return json.loads(guardado.read_text(encoding="utf-8"))["beats"]
    meta = ep.metadata()
    durations = meta.get("segment_durations_s")
    if not durations:
        raise SystemExit("keyframes: falta la narración — corré primero 'narrar'.")
    from .narracion import _segments
    segs = _segments(ep.read_text("script.txt"))
    import sys
    if str(config.ROOT) not in sys.path:
        sys.path.insert(0, str(config.ROOT))
    from factory.acting import beats
    segmentos = [{"texto": t, "dur_s": d} for t, d in zip(segs, durations)]
    planeados = beats.plan(segmentos, escena_base=meta.get("escena_base", "calle"))
    beats.escribir(ep, planeados)
    if any("direccion" not in b for b in planeados):
        beats.dirigir(planeados)
        beats.escribir(ep, planeados)
    return planeados


def storyboard_md(ep: Episode, bs: list[dict]) -> Path:
    """Guarda la dirección por plano para revisión editorial junto a la hoja de contactos."""
    filas = ["# Storyboard — " + ep.read_state().get("title", ep.slug), "",
             "| Tiempo | Voz | Idea / prop | Actuación | Escena / plano / cámara | Reveal |",
             "|---|---|---|---|---|---|"]
    for b in bs:
        d = b.get("direccion", {})
        clean = lambda value: str(value or "").replace("|", "/").replace("\n", " ")
        filas.append("| {t0:.1f}–{t1:.1f}s | {voz} | {idea}; **{prop}** | {acting} | {scene} / {shot} / {cam} | {reveal} |".format(
            t0=b["t0"], t1=b["t1"], voz=clean(b.get("texto")), idea=clean(d.get("idea")),
            prop=clean(d.get("prop")), acting=clean(d.get("acting")), scene=clean(b.get("escena")),
            shot=clean(b.get("plano")), cam=clean(d.get("camara")), reveal=clean(d.get("reveal"))))
    path = ep.artifacts / "storyboard.md"
    path.write_text("\n".join(filas) + "\n", encoding="utf-8")
    return path


# ----------------------------------------------------------------------- keyframes
def _preparar_keyframes(ep: Episode, bs: list[dict], *, modelo: str = "flux",
                       forzar: bool = False) -> tuple[list[dict], dict]:
    """Un keyframe por beat. Re-corrida no redrawa: la caché en disco congela al personaje."""
    ok, por = imagen.disponible()
    if not ok:
        raise SystemExit(f"keyframes: motor de imágenes no configurado ({por})")
    carpeta = ep.dir / "assets" / "kf"
    carpeta.mkdir(parents=True, exist_ok=True)
    ruta: list[Path] = []
    t0, nuevos = time.time(), 0
    for b in bs:
        prompt = imagen.armar_prompt_dirigido(b)
        out = carpeta / f"kf-{b['i']:03d}.{imagen.extension(modelo)}"
        b["prompt"] = prompt
        if out.exists() and not forzar:
            ruta.append(out)
            continue
        imagen.generar(prompt, out, modelo=modelo, forzar=forzar)
        nuevos += 1
        ruta.append(out)
    return bs, {"frames": len(ruta), "generados_nuevos": nuevos,
                "segundos_api": round(time.time() - t0, 1), "modelo": modelo, "rutas": ruta}


def generar_keyframes(ep: Episode, bs: list[dict], *, modelo: str = "flux",
                      forzar: bool = False) -> tuple[list[Path], dict]:
    dirigidos, info = _preparar_keyframes(ep, bs, modelo=modelo, forzar=forzar)
    return info["rutas"], info


# ----------------------------------------------------------------- hoja de contactos
def hoja_contactos(ep: Episode, bs: list[dict], kfs: list[Path]) -> Path:
    """Placa de contactos ANTES de renderizar: aprobar el guion visual, no un video ya codificado.

    Cada celda trae beat, tiempos, escena/acción/plano/cámara y la palabra pop.
    """
    celdas = []
    carpeta = ep.dir / "artifacts" / "contacto"
    carpeta.mkdir(parents=True, exist_ok=True)
    for b, img in zip(bs, kfs):
        celda = carpeta / f"c-{b['i']:03d}.png"
        etiqueta = (f"beat {b['i']}  {b['t0']:.1f}-{b['t1']:.1f}s  {b['escena']}/"
                    f"{b['accion']}/{b['plano']}/{b['mov']}  pop:{b['pop'] or '-'}")
        # La etiqueta va por textfile: incrustarla en drawtext=text='...' rompe el parseo
        # del filtergraph en cuanto el texto tiene un dos puntos (pop:palabra).
        txt = carpeta / f"e-{b['i']:03d}.txt"
        txt.write_text(etiqueta, encoding="utf-8")
        prop = str((b.get("direccion") or {}).get("prop", ""))[:86]
        resumen = carpeta / f"v-{b['i']:03d}.txt"
        resumen.write_text(prop, encoding="utf-8")
        vf = (_recorte(fps=False) + ",scale=270:480,pad=270:506:0:26:black,"
              f"drawtext=textfile={resumen}:x=5:y=30:fontsize=11:fontcolor=yellow:box=1:boxcolor=black@0.7,"
              f"drawtext=textfile={txt}:x=6:y=5:fontsize=18:fontcolor=white")
        _run(["ffmpeg", "-y", "-v", "error", "-i", str(img), "-vf", vf,
              "-frames:v", "1", str(celda)])
        celdas.append(celda)
    columnas = 4
    filas = math.ceil(len(celdas) / columnas)
    lista = carpeta / "orden.txt"
    lista.write_text("".join(f"file '{p}'\n" for p in celdas), encoding="utf-8")
    sheet = ep.dir / "artifacts" / "contacto.png"
    _run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(lista),
          "-vf", f"tile={columnas}x{filas}", "-frames:v", "1", str(sheet)])
    return sheet


def shotcard(ep: Episode, beats: list[dict], kfs: list[Path], nombre: str = "contacto") -> Path:
    """Crea una hoja de revisión de imágenes para un corte parcial sin sobrescribir la placa base."""
    carpeta = ep.dir / "artifacts" / "contacto"
    carpeta.mkdir(parents=True, exist_ok=True)
    celdas = []
    for b, img in zip(beats, kfs):
        celda = carpeta / f"{nombre}-{b['i']:03d}.png"
        etiqueta = f"{b['t0']:.1f}-{b['t1']:.1f}s {b['escena']}/{b['accion']}/{b['plano']}"
        txt = carpeta / f"{nombre}-{b['i']:03d}.txt"
        txt.write_text(etiqueta, encoding="utf-8")
        prop = str((b.get("direccion") or {}).get("prop", ""))[:86]
        resumen = carpeta / f"{nombre}-v-{b['i']:03d}.txt"
        resumen.write_text(prop, encoding="utf-8")
        vf = (_recorte(fps=False) + ",scale=270:480,pad=270:506:0:26:black,"
              f"drawtext=textfile={resumen}:x=5:y=30:fontsize=11:fontcolor=yellow:box=1:boxcolor=black@0.7,"
              f"drawtext=textfile={txt}:x=6:y=5:fontsize=18:fontcolor=white")
        _run(["ffmpeg", "-y", "-v", "error", "-i", str(img), "-vf", vf,
              "-frames:v", "1", str(celda)])
        celdas.append(celda)
    columnas = 3
    filas = math.ceil(len(celdas) / columnas)
    orden = carpeta / f"{nombre}-orden.txt"
    orden.write_text("".join(f"file '{p}'\n" for p in celdas), encoding="utf-8")
    sheet = ep.dir / "artifacts" / f"{nombre}.png"
    _run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(orden),
          "-vf", f"tile={columnas}x{filas}", "-frames:v", "1", str(sheet)])
    return sheet


def preview(ep: Episode, *, modelo: str = "flux", segundos: float = 35.0) -> dict:
    """Render de revisión breve, conserva el master y sus artefactos independientes."""
    from .narracion import _segments
    t0 = time.time()
    antes = resource.getrusage(resource.RUSAGE_CHILDREN)
    audio = ep.dir / "assets/audio/narration.wav"
    if not audio.exists():
        raise SystemExit("preview: falta narración")
    # Primeros segmentos completos para conservar sintaxis y sentido narrativo.
    from .narracion import _dur
    segs_dir = ep.dir / "assets/audio/segments"
    seleccion, dur = [], 0.0
    for f in sorted(segs_dir.glob("seg-*.wav")):
        d = _dur(f)
        if seleccion and dur + d > segundos:
            break
        seleccion.append(f)
        dur += d
    if not seleccion:
        raise SystemExit("preview: no hay segmentos de voz terminados")
    audio_preview = ep.dir / "assets/audio/preview.wav"
    lista = ep.dir / "assets/audio/preview-concat.txt"
    lista.write_text("".join(f"file '{p.relative_to(ep.dir / 'assets/audio')}'\n" for p in seleccion),
                     encoding="utf-8")
    _run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(lista),
          "-c:a", "pcm_s16le", str(audio_preview)])
    # Recalcular beats contra los segmentos del preview sin tocar el guion maestro.
    script_segs = _segments(ep.read_text("script.txt"))[:len(seleccion)]
    duraciones = [_dur(p) for p in seleccion]
    from factory.acting import beats as planner
    bs = planner.plan([{"texto": txt, "dur_s": d} for txt, d in zip(script_segs, duraciones)])
    kfs = []
    stats = {"generados_nuevos": 0}
    for b in bs:
        prompt = imagen.armar_prompt_dirigido(b)
        out = ep.dir / "assets/kf" / f"{ep.slug}-preview-{b['i']:03d}.{imagen.extension(modelo)}"
        out.parent.mkdir(parents=True, exist_ok=True)
        imagen.generar(prompt, out, modelo=modelo)
        b["prompt"] = prompt
        kfs.append(out)
    stats["frames"] = len(kfs)
    sheet = shotcard(ep, bs, kfs, nombre="contacto-preview")
    parts = ep.dir / "renders/preview-parts"
    parts.mkdir(parents=True, exist_ok=True)
    paths=[]
    for b, img in zip(bs, kfs):
        out=parts / f"k-{b['i']:03d}.mp4"
        _plano(b,img,out); paths.append(out)
    order=parts / "orden.txt"
    order.write_text("".join(f"file '{p}'\n" for p in paths),encoding="utf-8")
    silent=ep.dir / "renders/preview-silent.mp4"
    _run(["ffmpeg","-y","-v","error","-f","concat","-safe","0","-i",str(order),"-c","copy",str(silent)])
    cama=_cama(ep,dur); sfx=_sfx(ep,bs); mezcla=_mezcla(ep,audio_preview,cama,sfx)
    from .montaje import validar_ass
    subs=ep.dir / "assets/sub" / "preview.ass"
    subs.parent.mkdir(parents=True,exist_ok=True)
    subs.write_text(_ass_texto(bs),encoding="utf-8")
    validar_ass(subs)
    normal=_normalizador(mezcla)
    salida=ep.dir / "renders" / f"{ep.slug}-preview.mp4"
    _run(["ffmpeg","-y","-v","error","-i",str(silent),"-i",str(mezcla),"-filter_complex",
          f"[0:v]subtitles={subs}[v];[1:a]{normal}[a]","-map","[v]","-map","[a]",
          "-c:v","libx264","-preset",str(config.FFMPEG_PRESET),"-crf",str(config.FFMPEG_CRF),
          "-pix_fmt","yuv420p","-r",str(KF_FPS),"-c:a","aac","-b:a","128k","-ar","44100",
          "-shortest","-movflags","+faststart",str(salida)])
    qc=_qc(salida,dur)
    wall=time.time()-t0
    hijos=resource.getrusage(resource.RUSAGE_CHILDREN)
    cpu=(hijos.ru_utime-antes.ru_utime)+(hijos.ru_stime-antes.ru_stime)
    info={"archivo":salida.name,"duracion_s":qc["duracion_s"],"resolucion":f"{qc['ancho']}x{qc['alto']}",
          "peso_mb":round(salida.stat().st_size/1048576,2),"loudness_lufs":qc["lufs"],
          "problemas":qc["problemas"],"beats":len(bs),"imagenes_nuevas":stats["generados_nuevos"],
          "ram_pico_mb":round(max(antes.ru_maxrss,hijos.ru_maxrss)/1024,1),"cpu_segundos":round(cpu,1),
          "cpu_porcentaje_un_nucleo":round(cpu/max(.001,wall)*100,1),"segundos_total":round(wall,1),
          "contacto":str(sheet.relative_to(ep.dir)),"status":"pass" if not qc["problemas"] else "FAIL",
          "nota":"preview parcial; no reemplaza el master ni implica aprobación de publicación"}
    ep.write_json("preview.json",info)
    print(f"  preview {salida.name}: {info['duracion_s']}s, {info['peso_mb']} MB, {info['loudness_lufs']} LUFS, {info['segundos_total']}s")
    return info


# ------------------------------------------------------------------------- planos
def _plano(b: dict, img: Path, out: Path) -> None:
    frames = max(1, int(round(b["dur_s"] * KF_FPS)))
    cam = CAMARA.get(b["mov"], CAMARA["fijo"]).format(n=max(1, frames - 1))
    vf = f"{_recorte()},zoompan={cam}:d={frames}:s={W}x{H}:fps={KF_FPS}"
    if "flash" in b.get("fx", []):
        vf += ",fade=t=in:st=0:d=0.10:color=white"
    _run(["ffmpeg", "-y", "-v", "error", "-loop", "1", "-i", str(img),
          "-t", f"{b['dur_s']:.3f}", "-vf", vf,
          "-c:v", "libx264", "-preset", str(config.FFMPEG_PRESET), "-crf", str(config.FFMPEG_CRF),
          "-pix_fmt", "yuv420p", "-r", str(KF_FPS), "-an", str(out)])


LUFS, TP = -14.0, -1.5


def _mezcla(ep: Episode, voz: Path, cama: Path, sfx: Path, bs: list[dict] | None = None) -> Path:
    """Voz + cama al 22 % + un SFX por corte, con headroom y SIN normalizar todavía.

    El alimiter NO es decorativo: Piper escupe la voz clavada en 0 dBFS (medido:
    max_volume -0,0 dB). Con esa cresta de 17 dB no existe ganancia lineal que lleve el
    material a -14 LUFS sin pasar de -1,5 dBFS de pico, y loudnorm cae al modo dinámico y
    se queda en -15,9. Limitando a -9 dB la cresta baja a 12,6 dB y la segunda pasada
    lineal sí llega a la meta.
    """
    out = ep.dir / "assets" / "audio" / "mezcla.wav"
    perfil = str(ep.metadata().get("music_mood", "suspenso"))
    # Sintetizador musical local, seleccionado por curva editorial. No usa loops ajenos.
    presets = {
        "suspenso": (55, 82, 0.11), "emocionante": (98, 147, 0.10),
        "pop": (110, 165, 0.09), "electro": (65, 130, 0.07),
        "cumbia": (92, 138, 0.08), "rock": (73, 110, 0.045),
        "blues": (82, 123, 0.07),
    }
    f0, f1, nivel = presets.get(perfil, presets["suspenso"])
    segundos = max(0.1, _dur(voz))
    segundos = max(0.1, _dur(voz))
    # Rampa editorial sobria: intro, cuerpo, y respiración musical bajo la voz.
    cmd = ["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", f"aevalsrc={nivel}*sin(2*PI*{f0}*t)*exp(-mod(t*2\\,1)*5):s=22050:d={segundos}",
           "-f", "lavfi", "-i", f"aevalsrc={nivel*0.55}*sin(2*PI*{f1}*t)*exp(-mod(t*2\\,1)*5):s=22050:d={segundos}",
           "-filter_complex", f"[0:a][1:a]amix=inputs=2:normalize=0,lowpass=f=1800,afade=t=in:d=1.2,afade=t=out:st={max(0.1,segundos-1.4)}:d=1.4,volume=0.45[m]",
           "-map", "[m]", "-ar", "44100", "-ac", "1", "-c:a", "pcm_s16le", str(cama)]
    _run(cmd)
    # Ducking de música bajo la voz: preserva inteligibilidad sin una base fija constante.
    _run(["ffmpeg", "-y", "-v", "error", "-i", str(voz), "-i", str(cama), "-i", str(sfx),
          "-filter_complex",
          "[0:a]aformat=channel_layouts=mono,asplit=2[vo][vosc];[1:a]volume=0.24[side];"
          "[side][vosc]sidechaincompress=threshold=0.025:ratio=8:attack=25:release=420[mu];"
          "[2:a]volume=0.45[sf];[vo][mu][sf]amix=inputs=3:duration=first:normalize=0,"
          "alimiter=level_in=1:level_out=1:limit=0.35:attack=5:release=80:level=0,"
          # Haas barato (2-3 ms entre canales) antes del loudnorm: abre la imagen sin
          # tocar la cadena de -14 LUFS. La voz sigue centrada y la música gana aire.
          "haas=side_gain=0.45:middle_source=mid,aformat=channel_layouts=stereo[a]",
          "-map", "[a]", "-ar", "44100", "-ac", "2", "-c:a", "pcm_s16le", str(out)])
    return out


def _normalizador(meza: Path) -> str:
    """loudnorm en DOS pasadas: la única forma de clavar -14 LUFS.

    La pasada única (dynamic mode) quedó en -15,9 LUFS medido en este mismo audio: el
    normalizador dinámico persigue la meta en vez de alcanzarla. Acá se mide primero y
    se aplica con linear=true, que es un ganancia fija y no come la dinámica.
    """
    p = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(meza),
                        "-af", f"loudnorm=I={LUFS}:TP={TP}:LRA=11:print_format=json",
                        "-f", "null", "-"], capture_output=True, text=True)
    crudo = p.stderr[p.stderr.rfind("{"):]
    datos = json.loads(crudo[:crudo.rfind("}") + 1])
    return (f"loudnorm=I={LUFS}:TP={TP}:LRA=11"
            f":measured_I={datos['input_i']}:measured_TP={datos['input_tp']}"
            f":measured_LRA={datos['input_lra']}:measured_thresh={datos['input_thresh']}"
            f":offset={datos['target_offset']}:linear=true:print_format=summary")


def _subtulos(ep: Episode, bs: list[dict]) -> Path:
    """Un ASS global: la frase del beat abajo y la palabra pop gigante arriba.

    Se quema en una sola pasada sobre el video concatenado, por eso los tiempos son
    absolutos. Pasar por montaje.validar_ass no es decorativo: un Format corto quema
    ",0,0,0,,palabra" en pantalla (el bug de pulso-001-main.mp4).
    """
    from .montaje import validar_ass
    path = ep.dir / "assets" / "sub" / "keyframes.ass"
    path.parent.mkdir(parents=True, exist_ok=True)
    ev = []
    for b in bs:
        t0, t1 = _ts(b["t0"]), _ts(min(b["t1"], b["t0"] + b["dur_s"]))
        frase = (b["texto"][:42] + "…") if len(b["texto"]) > 42 else b["texto"]
        frase = r"{\q2}" + frase.replace("\\", "\\\\").replace("{", "").replace("}", "")
        ev.append(f"Dialogue: 0,{t0},{t1},Default,,0,0,0,,{frase}")
        # Sin POP: el texto queda sólo abajo, sin duplicar la frase arriba.
    texto = f"""[Script Info]
ScriptType: v4.00+
WrapStyle: 2
PlayResX: {W}
PlayResY: {H}

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, OutlineColour, BackColour, Bold, Italic, BorderStyle, Outline, Shadow, Alignment, MarginV, Encoding
Style: Default, DejaVu Sans, 39, &H00FFFFFF, &H00101010, &H80000000, 1, 0, 1, 3, 1, 2, 220, 1
Style: POP, DejaVu Sans, 102, &H0000FFFF, &H00101010, &H80000000, 1, 0, 1, 7, 2, 8, 280, 1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
{chr(10).join(ev)}
"""
    validar_ass(texto, str(path))
    path.write_text(texto, encoding="utf-8")
    return path


def _ass_texto(bs: list[dict]) -> str:
    """ASS autocontenido para previews; no toca el subtítulo del master."""
    ev=[]
    for b in bs:
        t0,t1=_ts(b["t0"]),_ts(min(b["t1"],b["t0"]+b["dur_s"]))
        frase=(b["texto"][:42]+"…") if len(b["texto"])>42 else b["texto"]
        frase=r"{\q2}"+frase.replace("\\","\\\\").replace("{","").replace("}","")
        ev.append(f"Dialogue: 0,{t0},{t1},Default,,0,0,0,,{frase}")
        # Sin POP: el texto queda sólo abajo, sin duplicar la frase arriba.
    return f"""[Script Info]
ScriptType: v4.00+
WrapStyle: 2
PlayResX: {W}
PlayResY: {H}

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, OutlineColour, BackColour, Bold, Italic, BorderStyle, Outline, Shadow, Alignment, MarginV, Encoding
Style: Default, DejaVu Sans, 39, &H00FFFFFF, &H00101010, &H80000000, 1, 0, 1, 3, 1, 2, 220, 1
Style: POP, DejaVu Sans, 102, &H0000FFFF, &H00101010, &H80000000, 1, 0, 1, 7, 2, 8, 280, 1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
{chr(10).join(ev)}
"""


# ---------------------------------------------------------------------------- audio
def _sfx(ep: Episode, bs: list[dict]) -> Path:
    """Un golpe/whoosh sintetizado por corte (duración exacta del beat, sonido en t=0).

    Se generan acá, con lavfi: autoría propia, sin biblioteca de sonido ajena ni licencia.
    """
    d = ep.dir / "assets" / "audio" / "sfx"
    d.mkdir(parents=True, exist_ok=True)
    trozos = []
    for b in bs:
        dur = b["dur_s"]
        fuerte = "flash" in b.get("fx", [])
        nombre = d / f"sfx-{b['i']:03d}.wav"
        if fuerte:
            fc = ("[0:a][1:a]amix=inputs=2:duration=first:weights=2 1,"
                  "afade=t=out:st=0:d=0.22,volume=0.55,apad")
            ins = ["-f", "lavfi", "-i", f"sine=frequency=64:duration={dur}",
                   "-f", "lavfi", "-i", f"anoisesrc=color=pink:amplitude=0.5:duration={min(dur,0.3)}"]
        else:
            fc = "highpass=f=500,afade=t=in:st=0:d=0.05,afade=t=out:st=0.05:d=0.16,volume=0.30,apad"
            ins = ["-f", "lavfi", "-i", f"anoisesrc=color=pink:amplitude=0.6:duration={min(dur,0.24)}"]
        _run(["ffmpeg", "-y", "-v", "error"] + ins +
             ["-filter_complex", fc, "-t", f"{dur:.3f}", "-ar", "22050", "-ac", "1",
              "-c:a", "pcm_s16le", str(nombre)])
        trozos.append(nombre)
    lista = d / "orden.txt"
    lista.write_text("".join(f"file '{p}'\n" for p in trozos), encoding="utf-8")
    out = ep.dir / "assets" / "audio" / "sfx-track.wav"
    _run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(lista),
          "-c:a", "pcm_s16le", str(out)])
    return out


def _cama(ep: Episode, segundos: float) -> Path:
    out = ep.dir / "assets" / "audio" / "cama.wav"
    perfil = str(ep.metadata().get("music_mood", "suspenso"))
    presets = {
        "suspenso": (55, 82, 0.11), "emocionante": (98, 147, 0.10),
        "pop": (110, 165, 0.09), "electro": (65, 130, 0.07),
        "cumbia": (92, 138, 0.08), "rock": (73, 110, 0.045), "blues": (82, 123, 0.07),
    }
    f0, f1, nivel = presets.get(perfil, presets["suspenso"])
    _run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
          f"aevalsrc={nivel}*sin(2*PI*{f0}*t)*exp(-mod(t*2\\,1)*5):s=22050:d={segundos}",
          "-f", "lavfi", "-i",
          f"aevalsrc={nivel*0.55}*sin(2*PI*{f1}*t)*exp(-mod(t*2\\,1)*5):s=22050:d={segundos}",
          "-filter_complex", f"[0:a][1:a]amix=inputs=2:normalize=0,lowpass=f=1800,afade=t=in:d=1.2,afade=t=out:st={max(0.1,segundos-1.4)}:d=1.4[m]",
          "-map", "[m]", "-ar", "44100", "-ac", "1", "-c:a", "pcm_s16le", str(out)])
    return out


# ----------------------------------------------------------------------------- render
def render(ep: Episode, *, modelo: str = "flux", forzar: bool = False,
           solo_contacto: bool = False) -> dict:
    """De script.txt + narración ya hecha a un MP4 keyframe terminado (o sólo la placa de contactos)."""
    t0 = time.time()
    uso_cpu_antes = resource.getrusage(resource.RUSAGE_SELF).ru_utime + resource.getrusage(resource.RUSAGE_SELF).ru_stime
    hijos_cpu_antes = resource.getrusage(resource.RUSAGE_CHILDREN).ru_utime + resource.getrusage(resource.RUSAGE_CHILDREN).ru_stime
    bs = beats_de(ep, forzar=forzar)
    if not bs:
        raise SystemExit("keyframes: el planificador no devolvió beats")
    # Rótulos editoriales legibles se fijan antes de crear las imágenes de revisión.
    for b in bs:
        prop = str((b.get("direccion") or {}).get("prop", ""))
        if prop.startswith("2005 analyst report"): b["pop"] = "~30 ALERTAS"
        elif prop.startswith("timeline from 1992"): b["pop"] = "6 QUEJAS"
        elif prop.startswith("options market volume"): b["pop"] = "VOLUMEN IRREAL"
        elif prop.startswith("investment returns chart"): b["pop"] = "DEMASIADO PERFECTO"
        elif prop.startswith("clear three-part Ponzi"): b["pop"] = "NUEVOS → ANTERIORES"
        elif prop.startswith("official securities fraud"): b["pop"] = "DICIEMBRE 2008"
    storyboard = storyboard_md(ep, bs)
    bs, stats = _preparar_keyframes(ep, bs, modelo=modelo, forzar=forzar)
    kfs = stats.pop("rutas")
    sheet = hoja_contactos(ep, bs, kfs)
    densidad = round(60 * len(bs) / max(0.001, sum(b["dur_s"] for b in bs)), 1)
    print(f"  keyframes: {len(kfs)} imágenes ({stats['generados_nuevos']} nuevas, "
          f"{stats['segundos_api']}s de API) | densidad {densidad}/min")
    print(f"  hoja de contactos: {sheet.relative_to(ep.dir)} — se adjunta al paquete de revisión")
    print(f"  storyboard: {storyboard.relative_to(ep.dir)}")
    ep.write_json("beats.json", {"beats": bs,
                                  "densidad": round(len(bs) / max(0.001, sum(b["dur_s"] for b in bs)) * 60, 1)})
    if solo_contacto:
        ep.write_json("contacto.json", {"hoja": str(sheet.relative_to(ep.dir)),
                                        "beats": len(bs), "densidad_por_min": densidad,
                                        "listo_para_render": False})
        return {"contacto": str(sheet), "beats": len(bs), "renderizado": False}

    # Único maestro de producción: keyframe 2.5D (silueta stickman + cámara FFmpeg +
    # subtítulos + mezcla). La ruta del brief: 30-40 imágenes/min, sin render 3D por
    # fotograma. El maestro avatar (GLB con ojos y lipsync) fue DESCARTADO de esta ruta
    # por decisión del dueño: la fábrica sólo genera videos stickman.
    partes = ep.dir / "renders" / "kf-parts"
    partes.mkdir(parents=True, exist_ok=True)
    t_planos = time.time()
    # recorte: sólo los planos cuyo keyframe cambió (o que faltan). En el B950 renderizar
    # los 18 otra vez cuesta ~2 min por nada.
    huellas = partes / "huellas.json"
    previos = json.loads(huellas.read_text()) if huellas.exists() else {}
    pendientes = []
    for b, img in zip(bs, kfs):
        marca = f"{img}:{b['dur_s']}:{b['mov']}:{b['plano']}:{','.join(b.get('fx', []))}"
        out = partes / "k-{:03d}.mp4".format(b["i"])
        if previos.get(str(out)) == marca and out.exists():
            continue
        pendientes.append((b, img, marca))
    hechos = 0
    if pendientes and os.environ.get("RENDER_REMOTO", "1") != "0":
        # Laboratorio SSH habilitado (decisión del dueño 2026-11-04): los encodes
        # por beat se reparten en los nodos vivos; lo que un nodo dropea se rinde
        # local, y con las nodas caídas la ruta es idéntica a la de siempre.
        from .. import remoto
        try:
            r = remoto.repartir_planos(ep.slug, [p[0] for p in pendientes],
                                       [Path(p[1]) for p in pendientes], partes, previos)
            hechos += len(r["hechos"])
            caidos = set(r["fallidos"])
        except Exception as exc:  # noqa: BLE001 — el lab ES una mejora, no un requisito
            print(f"  remoto no disponible ({str(exc)[:80]}): todo local")
            caidos = {b["i"] for b, _f, _m in pendientes}
    else:
        caidos = {b["i"] for b, _f, _m in pendientes}
    for b, img, marca in pendientes:
        out = partes / "k-{:03d}.mp4".format(b["i"])
        if b["i"] not in caidos and out.exists() and out.stat().st_size > 0:
            continue
        _plano(b, img, out)
        previos[str(out)] = marca
        hechos += 1
    huellas.write_text(json.dumps(previos, indent=1), encoding="utf-8")
    planos_s = round(time.time() - t_planos, 1)

    nombres = [partes / "k-{:03d}.mp4".format(b["i"]) for b in bs]
    orden = partes / "orden.txt"
    orden.write_text("".join(f"file '{p}'\n" for p in nombres), encoding="utf-8")
    mudo = ep.dir / "renders" / f"{ep.slug}-kf-silent.mp4"
    _run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(orden),
          "-c", "copy", str(mudo)])

    meta = ep.metadata()
    voz = ep.dir / meta["narration_path"]
    total = sum(b["dur_s"] for b in bs)
    sfx = _sfx(ep, bs)
    cama = _cama(ep, total)
    sub = _subtulos(ep, bs)
    meza = _mezcla(ep, voz, cama, sfx, bs)
    nl = _normalizador(meza)

    salida = ep.dir / "renders" / f"{ep.slug}-keyframe.mp4"
    _run(["ffmpeg", "-y", "-v", "error", "-i", str(mudo), "-i", str(meza),
          "-filter_complex", f"[0:v]subtitles={sub}[v];[1:a]{nl}[a]",
          "-map", "[v]", "-map", "[a]",
          "-c:v", "libx264", "-preset", str(config.FFMPEG_PRESET), "-crf", str(config.FFMPEG_CRF),
          "-pix_fmt", "yuv420p", "-r", str(KF_FPS), "-c:a", "aac", "-b:a", "128k",
          "-ar", "44100", "-ac", "2", "-shortest", "-movflags", "+faststart", str(salida)])

    medidos = _qc(salida, total)
    wall_s = max(0.001, time.time() - t0)
    uso_cpu_despues = resource.getrusage(resource.RUSAGE_SELF).ru_utime + resource.getrusage(resource.RUSAGE_SELF).ru_stime
    hijos_cpu_despues = resource.getrusage(resource.RUSAGE_CHILDREN).ru_utime + resource.getrusage(resource.RUSAGE_CHILDREN).ru_stime
    cpu_s = max(0.0, (uso_cpu_despues - uso_cpu_antes) + (hijos_cpu_despues - hijos_cpu_antes))
    nucleos = max(1, os.cpu_count() or 1)
    ram_kb = max(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                 resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss)
    info = {
        "archivo": salida.name, "duracion_s": medidos["duracion_s"],
        "esperado_s": round(total, 2), "resolucion": f"{medidos['ancho']}x{medidos['alto']}",
        "fps": KF_FPS, "beats": len(bs), "densidad_por_min": densidad,
        "modelo_imagen": modelo, "llamadas_api": stats["generados_nuevos"],
        "segundos_api": stats["segundos_api"], "segundos_planos": planos_s,
        "segundos_total": round(wall_s, 1),
        "cpu_segundos": round(cpu_s, 1),
        "cpu_porcentaje_un_nucleo": round(100 * cpu_s / wall_s, 1),
        "cpu_porcentaje_maquina": round(100 * cpu_s / (wall_s * nucleos), 1),
        "peso_mb": round(salida.stat().st_size / 1048576, 2),
        "ram_pico_mb": round(ram_kb / 1024, 1),
        "loudness_lufs": medidos["lufs"], "problemas": medidos["problemas"],
        "contacto": str(sheet.relative_to(ep.dir)),
        "pendientes": ["motion blur por promedio de 4 muestras (no implementado: el zoompan "
                       "no lo da y minterpolate no cuesta poco en 2 núcleos)",
                       "60 fps (KF_FPS=60 funciona, medido a 30 por costo en el B950)"],
        "status": "pass" if not medidos["problemas"] else "FAIL",
    }
    ep.write_json("render_keyframes.json", info)
    meta.update({"keyframe_path": f"renders/{salida.name}",
                 "keyframe_duration_s": medidos["duracion_s"], "synthetic_content": True})
    ep.save_metadata(meta)
    if medidos["problemas"]:
        ep.set_stage("keyframes", "qc_fail")
        raise SystemExit(f"QC KEYFRAME FALLÓ: {medidos['problemas']}")
    ep.set_stage("keyframes", "done")
    print(f"  render: {salida.name} {medidos['duracion_s']}s {info['resolucion']}@{KF_FPS} | "
          f"{info['peso_mb']} MB | {medidos['lufs']} LUFS | RAM {info['ram_pico_mb']} MB | "
          f"{info['segundos_total']}s totales | CPU {info['cpu_porcentaje_maquina']}% máquina")
    return info


def _qc(path: Path, esperado: float) -> dict:
    """ffprobe + medición ebur128 real (no la promesa del filtro)."""
    info = json.loads(subprocess.run(
        ["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)],
        capture_output=True, text=True).stdout)
    v = next((s for s in info["streams"] if s["codec_type"] == "video"), {})
    tipos = {s["codec_type"] for s in info["streams"]}
    dur = float(info["format"]["duration"])
    p = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(path), "-af", "ebur128",
                        "-vn", "-f", "null", "-"], capture_output=True, text=True)
    lufs = None
    lineas = p.stderr.splitlines()
    for n, linea in enumerate(lineas):
        # ebur128 imprime "Integrated loudness:" y el valor en la línea de abajo ("I: -14.0 LUFS")
        if "Integrated loudness:" in linea and n + 1 < len(lineas):
            try:
                lufs = float(lineas[n + 1].split("I:")[1].split()[0])
            except (ValueError, IndexError):
                pass
    problemas = []
    if "video" not in tipos or "audio" not in tipos:
        problemas.append("faltan streams")
    if (v.get("width"), v.get("height")) != (W, H):
        problemas.append(f"resolución {v.get('width')}x{v.get('height')} != {W}x{H}")
    if abs(dur - esperado) > 0.8:
        problemas.append(f"duración {dur:.2f}s vs {esperado:.2f}s esperados")
    if lufs is None:
        problemas.append("no se pudo medir loudness")
    elif not (-16.0 <= lufs <= -12.0):
        problemas.append(f"loudness {lufs} LUFS fuera de -14 ±2")
    return {"duracion_s": round(dur, 2), "ancho": v.get("width"), "alto": v.get("height"),
            "lufs": lufs, "problemas": problemas}
