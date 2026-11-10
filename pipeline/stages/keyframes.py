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
plano con cámara -> hoja de contactos -> concat -> subtítulos dinámicos quemados
(ASS) -> voz + cama musical + SFX por corte -> loudnorm -14 LUFS.

CPU-only, sin GPU, sin Blender, sin librerías de pago.
"""
from __future__ import annotations

import json
import math
import os
import re
import resource
import subprocess
import time
from pathlib import Path

from .. import config, imagen
from ..episode import Episode
from . import reciclaje
from factory import parametros

# El máster documental nace en 9:16. Se conserva el presupuesto de píxeles
# del anterior 1280x720 para que el B950 no multiplique el costo del render.
W, H = 720, 1280
# 30 fps y no 60: en el B950 el zoompan duplica el costo de encode por cada fps extra y el
# movimiento sobre foto fija no gana nada visible pasados los 30. KF_FPS=60 igual funciona.
KF_FPS = int(config.os.environ.get("KF_FPS", "30"))
BASE_W, BASE_H = 810, 1440       # lienzo interno vertical antes de la cámara
KF_S = 1024                       # flux devuelve 1024x1024
KF_916_W = 576                    # recorte 9:16 nativo del cuadrado

# La foto fija del stickman no se mueve sola: sin respiración el cuadro es un frame muerto
# a 2,24 palabras/segundo. Los números viven en factory/acting/stickman_motion_rules.json.
_MICRO = parametros.motion().get("micro_movement", {})
_RESPIRAR = _MICRO.get("respiracion", {})
RESPIRACION_PX = int(_RESPIRAR.get("desplazamiento_px", 8))
RESPIRACION_S = float(_RESPIRAR.get("ciclo_s", 4.0))
RESPIRACION_MIN_S = float(_RESPIRAR.get("aplicar_cuando_duracion_sMayor_a", 1.0))
_QC_MICRO = _MICRO.get("qc", {})
QC_MUESTREO_FPS = float(_QC_MICRO.get("muestreo_fps", 5.0))
QC_UMBRAL_YDIF = float(_QC_MICRO.get("umbral_ydif", 0.005))
QC_PROPORCION_MUERTA = float(_QC_MICRO.get("proporcion_max_muerta", 0.9))

# Cámara: cada movimiento es una expresión de zoompan sobre la foto fija.
# Los separadores SON dos puntos: dentro de un filtro, la coma cerraría zoompan y abriría
# otro filtro, y ffmpeg revienta con "No option name near ..." (medido).
# Piso de zoom 1,05 (antes 1,0 en push/pull): el recorte necesita holgura para poder oscilar.
# Con zoom=1,0 la deriva de la respiración se clampa a 0 y el cuadro vuelve a ser un frame
# muerto, que es justo lo que esta sección existe para evitar.
# Reutilización dentro del episodio. Antes la imagen anterior se copiaba SÓLO por
# compartir escena: dos momentos distintos del episodio terminaban con la misma
# ilustración (reportado por el dueño: "escenas que reusan la misma imagen").
# Ahora la imagen sólo se reusa si el beat es la MISMA toma (escena+acción+plano)
# o si la idea/narración es prácticamente la misma.
KF_REUTILIZAR_UMBRAL = float(os.environ.get("KF_REUTILIZAR_UMBRAL", "0.80"))
KF_REUTILIZAR_COMPOSICION = os.environ.get("KF_REUTILIZAR_COMPOSICION", "1").strip().lower() \
    not in ("0", "false", "no", "off")

CAMARA = {
    "push":       "z='1.05+0.03*on/{n}'",
    "push_lento": "z='1.05+0.01*on/{n}'",
    "pull":       "z='1.08-0.03*on/{n}'",
    "pan":        "z='1.06':x='(iw-iw/zoom)*on/{n}':y='ih/2-(ih/zoom/2)'",
    "shake":      "z='1.06':x='iw/2-(iw/zoom/2)+18*sin(on/2.2)':y='ih/2-(ih/zoom/2)+12*sin(on/1.4)'",
    "fijo":       "z='1.05'",
}


def _run(cmd: list[str]) -> None:
    subprocess.run(cmd, check=True, capture_output=True, text=True)


def _dur(path: Path) -> float:
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                        "-of", "json", str(path)], capture_output=True, text=True)
    return float(json.loads(r.stdout)["format"]["duration"])


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
        beats_guardados = json.loads(guardado.read_text(encoding="utf-8"))["beats"]
        meta_guardada = ep.metadata()
        contexto = " | ".join(str(meta_guardada.get(k, ""))
                               for k in ("title", "angle", "categoria"))[:240]
        for beat in beats_guardados:
            beat["contexto_historia"] = contexto
        return beats_guardados
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
    contexto_historia = " | ".join(str(meta.get(k, "")) for k in ("title", "angle", "categoria"))
    planeados = beats.plan(segmentos, escena_base=meta.get("escena_base", "calle"),
                           contexto_historia=contexto_historia)
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
def _idea_de(b: dict) -> str:
    """Texto que representa el contenido visual del beat (narración + idea de dirección)."""
    d = b.get("direccion") or {}
    return " ".join(str(b.get(k) or "") for k in ("texto", "contexto", "oracion")) \
        + " " + str(d.get("idea", ""))


def _reutilizable(b: dict, comp_ultima: tuple[str, str, str], texto_ultimo: str) -> bool:
    """True sólo si la imagen anterior representa este beat.

    Regla: misma toma (escena+acción+plano) o idea/narración casi idéntica.
    """
    if not comp_ultima or not texto_ultimo:
        return False
    if KF_REUTILIZAR_COMPOSICION and comp_ultima == (
            str(b.get("escena", "")), str(b.get("accion", "")), str(b.get("plano", ""))):
        return True
    if KF_REUTILIZAR_UMBRAL > 0:
        return reciclaje.similitud(_idea_de(b), texto_ultimo) >= KF_REUTILIZAR_UMBRAL
    return False


def _preparar_keyframes(ep: Episode, bs: list[dict], *, modelo: str = "flux",
                       forzar: bool = False, reciclar: bool = False,
                       renovar: set[int] | None = None) -> tuple[list[dict], dict]:
    """Un keyframe por beat. Re-corrida no redrawa: la caché en disco congela al personaje.

    Modo ahorro (decisión del dueño, fábrica 24/7): KF_RECICLADO_CADA=N (default 2) genera
    una imagen NUEVA cada N beats y al beat intermedio le copia la última imagen viva del
    MISMO escenario. La calidad audiovisual no baja porque cada beat conserva su propio
    movimiento de cámara (zoompan/deriva por beat): la misma ilustración con dos cámaras
    distintas se lee como dos tomas. Se fuerza imagen nueva en: beat gancho, cambio de
    escenario, forzado --forzar/--renovar, o sin imagen previa reciclable."""
    carpeta = ep.dir / "assets" / "kf"
    carpeta.mkdir(parents=True, exist_ok=True)
    ruta: list[Path] = []
    renovar = renovar or set()
    t0, nuevos = time.time(), 0
    reciclados = 0
    cada = max(1, int(os.environ.get("KF_RECICLADO_CADA", "2")))
    ultima_viva: Path | None = None
    escena_ultima = ""
    desde_ultima = 0
    ultima_comp: tuple[str, str, str] = ("", "", "")
    ultimo_texto = ""
    for b in bs:
        prompt = imagen.armar_prompt_dirigido(b)
        out = carpeta / f"kf-{b['i']:03d}.{imagen.extension(modelo)}"
        b["prompt"] = prompt
        renovar_este = forzar or int(b["i"]) in renovar
        escena = str(b.get("escena", ""))
        comp = (escena, str(b.get("accion", "")), str(b.get("plano", "")))
        if out.exists() and not renovar_este:
            ruta.append(out)
            ultima_viva = out
            escena_ultima = escena
            ultima_comp = comp
            ultimo_texto = _idea_de(b)
            continue
        genera = (bool(b.get("gancho")) or renovar_este or ultima_viva is None
                  or escena != escena_ultima or desde_ultima >= cada
                  or not ultima_viva.exists())
        if not genera and not _reutilizable(b, ultima_comp, ultimo_texto):
            # Mismo escenario pero otra toma o contenido distinto: copiar la imagen
            # repetiría una ilustración que no corresponde a lo narrado.
            genera = True
        if not genera:
            out.write_bytes(ultima_viva.read_bytes())
            reciclados += 1
            desde_ultima += 1
            ruta.append(out)
            # NO se actualizan ultima_comp/ultimo_texto: describen la imagen en uso.
            continue
        imagen.generar(prompt, out, modelo=modelo, forzar=renovar_este, reciclar=reciclar,
                       escena=escena,
                       accion=str(b.get("accion", "")),
                       plano=str(b.get("plano", "")))
        nuevos += 1
        desde_ultima = 0
        escena_ultima = escena
        ultima_viva = out
        ultima_comp = comp
        ultimo_texto = _idea_de(b)
        ruta.append(out)
    return bs, {"frames": len(ruta), "generados_nuevos": nuevos, "reciclados": reciclados,
                "segundos_api": round(time.time() - t0, 1), "modelo": modelo, "rutas": ruta}


def generar_keyframes(ep: Episode, bs: list[dict], *, modelo: str = "flux",
                      forzar: bool = False, reciclar: bool = False,
                      renovar: set[int] | None = None) -> tuple[list[Path], dict]:
    dirigidos, info = _preparar_keyframes(ep, bs, modelo=modelo, forzar=forzar,
                                          reciclar=reciclar, renovar=renovar)
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


def preview(ep: Episode, *, modelo: str = "flux", segundos: float = 35.0,
            reciclar: bool = False, renovar: set[int] | None = None) -> dict:
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
    meta = ep.metadata()
    contexto = " | ".join(str(meta.get(k, "")) for k in ("title", "angle", "categoria"))
    bs = planner.plan([{"texto": txt, "dur_s": d} for txt, d in zip(script_segs, duraciones)],
                      contexto_historia=contexto)
    kfs = []
    stats = {"generados_nuevos": 0}
    renovar = renovar or set()
    for b in bs:
        prompt = imagen.armar_prompt_dirigido(b)
        out = ep.dir / "assets/kf" / f"{ep.slug}-preview-{b['i']:03d}.{imagen.extension(modelo)}"
        out.parent.mkdir(parents=True, exist_ok=True)
        # Reusar el caché del motor; una vista previa repetida no debe gastar cuota dos veces.
        imagen.generar(prompt, out, modelo=modelo, forzar=int(b["i"]) in renovar,
                       reciclar=reciclar, escena=str(b.get("escena", "")),
                       accion=str(b.get("accion", "")), plano=str(b.get("plano", "")))
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
    normal=_normalizador(mezcla)
    salida=ep.dir / "renders" / f"{ep.slug}-preview.mp4"
    _run(["ffmpeg","-y","-v","error","-i",str(silent),"-i",str(mezcla),"-filter_complex",
          f"[1:a]{normal}[a]","-map","0:v:0","-map","[a]",
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
def _deriva(i: int) -> str:
    """Expresión de desplazamiento vertical (px) para la respiración del plano.

    La fase se corre por índice de beat: si dos planos seguidos respiran al unísono el
    cerebro lo lee como temblor de cámara, no como vida.
    """
    ciclo = max(2.0, RESPIRACION_S) * KF_FPS
    fase = (i % 5) * (2 * math.pi / 5)
    return f"{RESPIRACION_PX}+{RESPIRACION_PX}*sin(2*PI*n/{ciclo:.0f}+{fase:.3f})"


def _plano(b: dict, img: Path, out: Path) -> None:
    frames = max(1, int(round(b["dur_s"] * KF_FPS)))
    cam = CAMARA.get(b["mov"], CAMARA["fijo"]).format(n=max(1, frames - 1))
    respira = b["dur_s"] > RESPIRACION_MIN_S
    lienzo = (f"{W + 2 * RESPIRACION_PX}x{H + 2 * RESPIRACION_PX}" if respira else f"{W}x{H}")
    vf = f"{_recorte()},zoompan={cam}:d={frames}:s={lienzo}:fps={KF_FPS}"
    if respira:
        # Se renderiza con 8 px de holgura por lado y se recorta el máster WxH desde una
        # ventana que oscila: el cuadro termina exactamente en WxH y nunca está quieto.
        vf += f",crop={W}:{H}:x={RESPIRACION_PX}:y='{_deriva(b['i'])}'"
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



def _ass_tiempo(s: float) -> str:
    s = max(0.0, float(s))
    h = int(s // 3600)
    m = int((s % 3600) // 60)
    sec = s % 60
    return f"{h}:{m:02d}:{sec:05.2f}"


def _ass_escape(texto: str) -> str:
    # ASS usa llaves para overrides; saltos de línea y backslashes rompen el parseo.
    return (texto.replace("\\", "/").replace("{", "(").replace("}", ")")
            .replace("\n", " ").replace("\r", " ").strip())


def _frase_sub(t: str, max_chars: int = 34) -> str:
    """Parte en 1-2 líneas legibles en móvil sin cortar palabras."""
    t = re.sub(r"\s+", " ", (t or "").strip())
    if len(t) <= max_chars:
        return t
    palabras = t.split()
    mejor, mejor_d = t, 10**9
    for i in range(1, len(palabras)):
        a, b = " ".join(palabras[:i]), " ".join(palabras[i:])
        d = abs(len(a) - len(b)) + (0 if max(len(a), len(b)) <= max_chars else 20)
        if d < mejor_d:
            mejor_d, mejor = d, a + r"\N" + b
    return mejor


def _palabras_clave(t: str) -> list[str]:
    """2-4 palabras con peso visual (números o léxico largo), para resaltar en subtítulo."""
    stop = {"sobre","desde","hasta","donde","cuando","porque","entre","tambien","también",
            "contra","luego","entonces","después","despues","antes","había","habia",
            "estaba","fueron","tiene","tenía","tenia","hacer","puede","quedó","quedo",
            "según","segun","todos","todas","parte","lugar","forma","mismo","misma"}
    claves = []
    for w in re.findall(r"\w+", t or "", flags=re.U):
        wl = w.lower()
        if (any(ch.isdigit() for ch in w) or (len(w) >= 6 and wl not in stop)):
            if wl not in {k.lower() for k in claves}:
                claves.append(w)
        if len(claves) >= 4:
            break
    return claves


def _subtitulo_resaltado(texto: str, pop: str = "") -> str:
    """Texto ASS con énfasis en palabra clave/POP (alto contraste, legible en scroll)."""
    base = _ass_escape(_frase_sub(texto))
    claves = _palabras_clave(pop) + _palabras_clave(texto)
    vistos = set()
    for c in claves:
        cl = c.lower()
        if cl in vistos:
            continue
        vistos.add(cl)
        patron = re.compile(rf"(?<!\w)({re.escape(_ass_escape(c))})(?!\w)", re.I)
        # Resalte “pop”: amarillo cálido + negrita + leve escala para fijar la mirada.
        nuevo = patron.sub(r"{\\c&H00D7FF&\\b1\\fscx108\\fscy108}\1{\\r}", base, count=1)
        if nuevo != base:
            base = nuevo
            break
    return base


def _generar_subtitulos_ass(ep: "Episode", bs: list[dict]) -> Path | None:
    """Subtítulos dinámicos (1 evento por beat) quemados en el máster para retención móvil.

    Desactivable con KF_SUBTITULOS=0. No altera duración ni resolución (QC intacto).
    """
    if os.environ.get("KF_SUBTITULOS", "1").strip().lower() in ("0", "false", "no", "off"):
        return None
    eventos = []
    for b in bs:
        txt = str(b.get("texto") or "").strip()
        t0, t1 = float(b.get("t0", 0.0)), float(b.get("t1", 0.0))
        if not txt or t1 <= t0:
            continue
        eventos.append((t0, t1, _subtitulo_resaltado(txt, str(b.get("pop") or ""))))
    if not eventos:
        return None
    # Subtítulo cinético/legible en móvil (retención): grande, contorno fuerte, sombra y
    # caja semitransparente para contraste sobre cualquier fondo.
    estilo = ("Style: Sub,DejaVu Sans,64,&H00FFFFFF,&H000000FF,&H00000000,&H78000000,"
              "-1,0,0,0,100,100,0,0,3,4.5,2.0,2,48,48,190,1")
    cab = ("[Script Info]\nScriptType: v4.00+\nPlayResX: 720\nPlayResY: 1280\n"
           "ScaledBorderAndShadow: yes\n\n[V4+ Styles]\n"
           "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour,"
           " BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle,"
           " BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
           f"{estilo}\n\n[Events]\n"
           "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n")
    lineas = [cab]
    for t0, t1, txt in eventos:
        lineas.append(f"Dialogue: 0,{_ass_tiempo(t0)},{_ass_tiempo(max(t0 + 0.2, t1 - 0.03))},Sub,,0,0,0,,{txt}\n")
    ruta = ep.artifacts / "subtitulos.ass"
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text("".join(lineas), encoding="utf-8")
    return ruta


# ----------------------------------------------------------------------------- render
def render(ep: Episode, *, modelo: str = "flux", forzar: bool = False,
           solo_contacto: bool = False, reciclar: bool = False,
           renovar: set[int] | None = None) -> dict:
    """De script.txt + narración ya hecha a un MP4 keyframe terminado (o sólo la placa de contactos)."""
    t0 = time.time()
    uso_cpu_antes = resource.getrusage(resource.RUSAGE_SELF).ru_utime + resource.getrusage(resource.RUSAGE_SELF).ru_stime
    hijos_cpu_antes = resource.getrusage(resource.RUSAGE_CHILDREN).ru_utime + resource.getrusage(resource.RUSAGE_CHILDREN).ru_stime
    bs = beats_de(ep, forzar=forzar)
    if not bs:
        raise SystemExit("keyframes: el planificador no devolvió beats")
    # "pop" se conserva para resaltar palabras clave en subtítulos (si aplica).
    storyboard = storyboard_md(ep, bs)
    bs, stats = _preparar_keyframes(ep, bs, modelo=modelo, forzar=forzar,
                                    reciclar=reciclar, renovar=renovar)
    kfs = stats.pop("rutas")
    sheet = hoja_contactos(ep, bs, kfs)
    densidad = round(60 * len(bs) / max(0.001, sum(b["dur_s"] for b in bs)), 1)
    print(f"  keyframes: {len(kfs)} imágenes ({stats['generados_nuevos']} nuevas, "
          f"{stats.get('reciclados', 0)} recicladas, {stats['segundos_api']}s de API) "
          f"| densidad {densidad}/min")
    print(f"  hoja de contactos: {sheet.relative_to(ep.dir)} — se adjunta al paquete de revisión")
    print(f"  storyboard: {storyboard.relative_to(ep.dir)}")
    ep.write_json("beats.json", {"beats": bs,
                                  "densidad": round(len(bs) / max(0.001, sum(b["dur_s"] for b in bs)) * 60, 1)})
    if solo_contacto:
        ep.write_json("contacto.json", {"hoja": str(sheet.relative_to(ep.dir)),
                                        "beats": len(bs), "densidad_por_min": densidad,
                                        "listo_para_render": False})
        return {"contacto": str(sheet), "beats": len(bs), "renderizado": False}

    # Único maestro de producción: keyframe 2.5D (stickman + cámara FFmpeg + mezcla).
    # La ruta del brief: 30-40 imágenes/min, sin render 3D por
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
        st = img.stat()
        marca = f"{img}:{st.st_mtime_ns}:{st.st_size}:{b['dur_s']}:{b['mov']}:{b['plano']}:{','.join(b.get('fx', []))}"
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
    meza = _mezcla(ep, voz, cama, sfx, bs)
    nl = _normalizador(meza)

    salida = ep.dir / "renders" / f"{ep.slug}-keyframe.mp4"
    ass = _generar_subtitulos_ass(ep, bs)
    if ass:
        # Escapar para filter_complex: ruta con : ' \ debe ir protegida.
        ass_f = str(ass).replace("\\", "/").replace(":", "\\:").replace("'", "\\'")
        fc = f"[0:v]ass='{ass_f}'[v];[1:a]{nl}[a]"
        maps = ["-map", "[v]", "-map", "[a]"]
    else:
        fc = f"[1:a]{nl}[a]"
        maps = ["-map", "0:v:0", "-map", "[a]"]
    _run(["ffmpeg", "-y", "-v", "error", "-i", str(mudo), "-i", str(meza),
          "-filter_complex", fc, *maps,
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
        "imagenes_recicladas": stats.get("reciclados", 0),
        "segundos_api": stats["segundos_api"], "segundos_planos": planos_s,
        "segundos_total": round(wall_s, 1),
        "cpu_segundos": round(cpu_s, 1),
        "cpu_porcentaje_un_nucleo": round(100 * cpu_s / wall_s, 1),
        "cpu_porcentaje_maquina": round(100 * cpu_s / (wall_s * nucleos), 1),
        "peso_mb": round(salida.stat().st_size / 1048576, 2),
        "ram_pico_mb": round(ram_kb / 1024, 1),
        "loudness_lufs": medidos["lufs"], "problemas": medidos["problemas"],
        "contacto": str(sheet.relative_to(ep.dir)),
        "subtitulos": str(ass.relative_to(ep.dir)) if ass else None,
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


def _frames_muertos(path: Path) -> float:
    """Proporción de cuadros muestreados sin cambio de luma alguno.

    Medido: un plano codificado con la foto realmente pegada no pasa de YDIF 0,0008 (piso de
    ruido del códec); con la deriva de 8 px el mismo plano llega a 9,8. Por eso el umbral está
    en 0,005 y la barrera en la PROPORCIÓN: el arte plano con zonas lisas tiene cuadros bajos
    legítimos, y lo que aquí queremos atrapar es el episodio entero sin movimiento.
    """
    r = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(path), "-vf",
                        f"fps={QC_MUESTREO_FPS:g},signalstats,"
                        f"metadata=print:key=lavfi.signalstats.YDIF", "-f", "null", "-"],
                       capture_output=True, text=True)
    valores = [float(x) for x in re.findall(r"YDIF=([0-9.eE+-]+)", r.stderr)]
    if not valores:
        return 1.0
    return round(sum(v <= QC_UMBRAL_YDIF for v in valores) / len(valores), 3)


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
    muertos = _frames_muertos(path)
    if muertos > QC_PROPORCION_MUERTA:
        problemas.append(f"frame muerto: {muertos:.0%} de los cuadros muestreados sin movimiento")
    if (v.get("width"), v.get("height")) != (W, H):
        problemas.append(f"resolución {v.get('width')}x{v.get('height')} != {W}x{H}")
    if abs(dur - esperado) > 0.8:
        problemas.append(f"duración {dur:.2f}s vs {esperado:.2f}s esperados")
    if lufs is None:
        problemas.append("no se pudo medir loudness")
    elif not (-16.0 <= lufs <= -12.0):
        problemas.append(f"loudness {lufs} LUFS fuera de -14 ±2")
    return {"duracion_s": round(dur, 2), "ancho": v.get("width"), "alto": v.get("height"),
            "lufs": lufs, "frames_muertos": muertos, "problemas": problemas}
