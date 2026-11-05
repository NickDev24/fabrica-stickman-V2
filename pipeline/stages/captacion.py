"""Piezas derivadas de captación: Trailer A (Facebook Reel), Trailer B (YouTube Short)
e Historieta de texto (Facebook), todas apuntando al capítulo completo de 23:00.

Qué hace y por qué acá
----------------------
El capítulo completo sale y queda en `renders/<slug>-keyframe.mp4`; el propio
`derivados._derivar_keyframe` arma el paquete de revisión. Este módulo toma el master
YA renderizado + `artifacts/beats.json` (escenas conMetadata de timing) y produce las
3 piezas de captación del día, sin tocar la generación del capítulo:

1. TRAILER A  -> `derivados/trailer-a-facebook-reel.mp4`  (programado 14:38)
2. TRAILER B  -> `derivados/trailer-b-youtube-short.mp4`  (programado 18:28)
3. HISTORIETA -> `publicacion/historieta-facebook.md`     (mismo horario que A)

Reglas del contrato editorial (ver brief de captación):
- A y B usan ESCENAS DISTINTAS: selección por potencial de hook sobre `beats`
  (clímax/conflicto visual), sin solapar cortes.
- El hook arranca DENTRO de la acción/conflicto: el corte empieza en el t0 del beat
  ganador, nunca antes (nada de context previo).
- CTA idéntico en texto y horario en las tres piezas:
  "Capítulo completo hoy 23:00 hs en YouTube".
- Metadata de programación lista para el sistema de publicación:
  `publicacion/programacion.json` (horario + plataforma por pieza).
- Salida previa para revisión humana: nada se publica acá; se imprime un resumen y se
  dejan los archivos + manifest, mismo patrón que el resto del pipeline.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

from .. import config
from ..episode import Episode

# Horarios de publicación (día del capítulo)
HORA_TRAILER_FB = "14:38"
HORA_SHORT_YT = "18:28"
HORA_HISTORIETA_FB = HORA_TRAILER_FB   # mismo slot que Trailer A salvo decisión contraria
HORA_CAPITULO = "23:00"

# CTA EXACTO (idéntico en las 3 piezas, en texto y horario)
CTA = f"Capítulo completo hoy {HORA_CAPITULO} hs en YouTube"

# Duración objetivo del hook de cada trailer: arranca en el beat ganador y dura hasta
# cerrar un mini-arco (cliffhanger), respetando el loop estructural de 8-15 s.
SEGUNDOS_TRAILER = 15.0

# Acciones corporales de conflicto (alternan el personaje con la evidencia)
_ACC_CLIMAX = {"corre", "grita", "golpea", "sorprendido", "empuja", "salta", "cae"}

_PLANO_CLIMAX = {"primer_plano", "detalle", "contrapicado", "cenital"}


def _run(cmd: list[str]) -> None:
    subprocess.run(cmd, check=True, capture_output=True, text=True)


def _dur(path: Path) -> float:
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                        "-of", "default=nw=1:nk=1", str(path)], capture_output=True, text=True)
    return float(r.stdout.strip())


# ------------------------------------------------------------------- selección de escenas
def score_beat(b: dict) -> int:
    """Potencial de hook de una escena: conflicto/clímax visual, no contexto."""
    d = b.get("direccion") or {}
    puntos = 0
    if "flash" in b.get("fx", []):
        puntos += 3
    if b.get("accion") in _ACC_CLIMAX:
        puntos += 2
    if b.get("plano") in _PLANO_CLIMAX:
        puntos += 1
    texto = str(b.get("contexto", "") or d.get("idea", "")).lower()
    if any(p in texto for p in ("pero", "nadie", "nunca", "terminó", "brutal", "colapso",
                                "imposible", "falló", "fraude", "única", "primera")):
        puntos += 1
    if b.get("pop"):
        puntos += 1
    return puntos


def elegir_escenas(bs: list[dict]) -> tuple[dict, dict] | None:
    """Dos escenas NO solapadas, priorizando el máximo hook de cada una.

    Devuelve (trailer_a, trailer_b): el ganador absoluto y el mejor beat quedando al
    menos 10 s de distancia temporal del corte del primero (nunca el mismo cut).
    """
    if len(bs) < 2:
        return None
    ordenados = sorted(bs, key=score_beat, reverse=True)
    a = ordenados[0]
    b = None
    for cand in ordenados[1:]:
        if abs(cand["t0"] - a["t0"]) >= 10.0:
            b = cand
            break
    if b is None:
        # Fallback: el mejor hook de la mitad de tiempo más alejada de A
        mitad = a["t0"]
        lejos = [x for x in bs if abs(x["t0"] - mitad) >= 10.0] or bs
        b = max(lejos, key=score_beat)
    if a is b:
        return None
    # A arranca en la escena más temprana para que el reel no empiece a mitad de nada
    primero, segundo = (a, b) if a["t0"] <= b["t0"] else (b, a)
    return primero, segundo


# ---------------------------------------------------------------------- trailers
def _corte_trailer(ep: Episode, main: Path, t0: float, segundos: float,
                   dst: Path, rótulo_cta: bool = True) -> dict:
    """Un corte vertical del master: arranca EN la escena ganadora + CTA idéntico al final.

    El master keyframe ya es 720x1280 (9:16); el reel/short va a 1080x1920. El CTA entra
    con fade en los últimos 3 s (cierre en cliffhanger con la cita del capítulo).
    """
    total = max(1.5, min(segundos, max(0.0, _dur(main) - t0 - 0.1)))
    dur = total
    fade_en = max(0.0, dur - 3.0)
    # El CTA va por textfile: embeberlo en text='...' rompe el parseo del filtergraph en
    # cuanto el texto tiene un dos puntos ("hoy 23:00 hs"). Mismo texto, en 2 líneas para
    # que no desborde el ancho.
    carpeta = ep.dir / "artifacts" / "captacion"
    carpeta.mkdir(parents=True, exist_ok=True)
    txt_cta = carpeta / "cta.txt"
    txt_cta.write_text("Capítulo completo\nhoy 23:00 hs en YouTube", encoding="utf-8")
    vf = (f"scale=1080:1920:flags=lanczos,setsar=1,"
          f"drawtext=textfile={txt_cta}:fontfile=/usr/share/fonts/truetype/dejavu/"
          f"DejaVuSans-Bold.ttf:fontcolor=white:fontsize=46:x=(w-text_w)/2:y=h-text_h-200:"
          f"line_spacing=8:box=1:boxcolor=black@0.55:boxborderw=18:alpha='if(lt(t,{fade_en}),0,"
          f"min((t-{fade_en})/0.4,1))'")
    cmd = ["ffmpeg", "-y", "-v", "error", "-ss", f"{t0:.3f}", "-i", str(main),
           "-t", f"{dur:.3f}", "-vf", vf, "-map", "0:v:0", "-map", "0:a?",
           "-c:v", "libx264", "-preset", str(config.FFMPEG_PRESET), "-crf",
           str(config.FFMPEG_CRF), "-pix_fmt", "yuv420p",
           "-c:a", "aac", "-b:a", "128k", "-ar", "44100", "-ac", "2",
           "-movflags", "+faststart", str(dst)]
    _run(cmd)
    return {"archivo": dst.name, "desde_s": round(t0, 2), "duracion_s": round(dur, 2),
            "peso_mb": round(dst.stat().st_size / 1048576, 2)}


def _texto_portada_de(script: str, titulo: str) -> str:
    """Texto de la portada scroll-stopper: la PREGUNTA gancho, máximo 6 palabras.

    La pregunta del guion (primer oración) es el gancho dorado exacto que narra el
    video; si no es pregunta (episodios viejos), cae al título. Sin cerrar el giro:
    la portada pregunta, el video responde (curiosity gap para el scroll).
    """
    import re
    prosa = "\n".join(l for l in script.splitlines() if not l.lstrip().startswith("#"))
    prosa = re.sub(r"\s+", " ", prosa).strip()
    primera = re.split(r"(?<=[.!?])\s+", prosa, maxsplit=1)[0] if prosa else ""
    base = primera if primera.rstrip().endswith("?") else (titulo or "")
    palabras = [w for w in re.sub(r"[¿?¡!.,;:—–\"']", " ", base).split() if w][:6]
    if not palabras:
        return (titulo or "").strip() or "Pulso Curioso"
    mid = (len(palabras) + 1) // 2
    return " ".join(palabras[:mid]) + "\n" + " ".join(palabras[mid:])


def _texto_portada(ep: Episode) -> str:
    return _texto_portada_de(ep.read_text("script.txt"), ep.read_state().get("title", ""))


def _imagen_portada_ia(ep: Episode, beat: dict) -> Path | None:
    """Portada generada IClusive con el motor de imágenes (sólo si PORTADA_LLM=1).

    El keyframe del clímax ya existe y suele bastar (coste cero); la imagen dedicada
    es pago (~$0.034) y sólo se pide si el dueño la habilita explícitamente. Con
    presupuesto agotado o sin env, se usa el keyframe existente: la portada NUNCA
    bloquea la etapa.
    """
    import os
    if os.environ.get("PORTADA_LLM", "").strip().lower() not in ("1", "true", "yes", "on"):
        return None
    from .. import imagen
    beat_portada = dict(beat)
    beat_portada["gancho"] = True
    beat_portada["plano"] = "primer_plano"
    beat_portada["fx"] = list(dict.fromkeys(list(beat.get("fx", [])) + ["flash"]))
    prompt = imagen.armar_prompt_dirigido(beat_portada)
    for modelo in ("flux", "gemini-imagen"):  # flux gratis si hay cuota; gemini de respaldo
        try:
            out = ep.dir / "assets" / "kf" / f"portada-ia.{imagen.extension(modelo)}"
            return imagen.generar(prompt, out, modelo=modelo,
                                  escena=str(beat.get("escena", "")),
                                  accion=str(beat.get("accion", "")),
                                  plano="primer_plano")
        except Exception:  # noqa: BLE001 — el respaldo pasa al keyframe del clímax
            continue
    return None


def _portada_scroll(ep: Episode, kf_dir: Path, beat: dict, dst: Path) -> Path | None:
    """PORTADA del episodio: lo que YouTube/Facebook muestran en pausa/scroll.

    Receta (thumbnail kit de stickman-video-director + brief del dueño): la imagen del
    beat más intenso de la historia + la PREGUNTA gancho en amarillo con borde negro,
    texto grande arriba (zona segura de móvil), rara vez >6 palabras. Si se pidió una
    imagen generada a medida (PORTADA_LLM=1) y salió, esa es la base.
    """
    imagen_beat = kf_dir / f"kf-{beat['i']:03d}.jpg"
    if not imagen_beat.exists():
        imagen_beat = kf_dir / f"kf-{beat['i']:03d}.png"
    base_ia = _imagen_portada_ia(ep, beat)
    if base_ia is not None and base_ia.exists():
        imagen_beat = base_ia
    if not imagen_beat.exists():
        return None
    txt = ep.dir / "artifacts" / "portada.txt"
    txt.parent.mkdir(parents=True, exist_ok=True)
    txt.write_text(_texto_portada(ep), encoding="utf-8")
    # el texto vive en el tercio superior: los controles de pausa y el título del feed
    # de YouTube están abajo, y el face del stickman queda visible al centro.
    vf = ("scale=1080:1920:flags=lanczos,eq=contrast=1.08:saturation=1.1,"
          "drawtext=textfile=" + str(txt) + ":fontfile=/usr/share/fonts/truetype/dejavu/"
          "DejaVuSans-Bold.ttf:fontcolor=yellow:fontsize=110:x=(w-text_w)/2:y=170:"
          "line_spacing=18:borderw=8:bordercolor=black:box=1:boxcolor=black@0.25:boxborderw=24")
    _run(["ffmpeg", "-y", "-v", "error", "-i", str(imagen_beat), "-vf", vf,
          "-frames:v", "1", str(dst)])
    return dst


# ---------------------------------------------------------------------- historieta
def _historieta(ep: Episode, bs: list[dict], escenas: tuple[dict, dict]) -> dict:
    """Tira de viñetas para el feed de Facebook: no canibaliza views del video.

    Regla: resumen en viñetas SIN los dos beats usados por los trailers (esas escenas
    se muestran en video), y cierre con el CTA exacto (texto y horario) de los trailers.
    """
    idx_reservados = {escenas[0]["i"], escenas[1]["i"]}
    vinetas = []
    viñeta_actual = ""
    for b in bs:
        oracion = str(b.get("contexto", b.get("texto", ""))).strip()
        if not oracion or oracion == viñeta_actual:
            continue
        viñeta_actual = oracion
        vinetas.append(oracion)
    resumen = vinetas[:9] or [str(b.get("contexto", "")) for b in bs[:3]]
    lineas = [f"#{i+1}. {v}{'…' if not v.endswith(('.', '!', '?', '…')) else ''}"
              for i, v in enumerate(resumen)]
    titulo = ep.read_state()["title"]
    texto = "\n\n".join([
        f"🧵 {titulo} — en viñetas, sin ninguna imagen:",
        "", "\n\n".join(lineas),
        "", "---", "", f"▶️ {CTA}",
        "(Los trailers aparecieron hoy a las "
        f"{HORA_TRAILER_FB} y {HORA_SHORT_YT} hs; el capítulo completo entra noche.)",
    ])
    dst = ep.dir / "publicacion" / "historieta-facebook.md"
    dst.parent.mkdir(exist_ok=True)
    dst.write_text(texto + "\n", encoding="utf-8")
    return {"archivo": str(dst.relative_to(ep.dir)), "vinetas": len(lineas),
            "escenas_excluidas": sorted(idx_reservados)}


# ------------------------------------------------------------------------- módulo
def derivar_captacion(ep: Episode) -> dict:
    """Las 3 piezas de captación del día + metadata de programación (sin publicar)."""
    main = ep.dir / "renders" / f"{ep.slug}-keyframe.mp4"
    if not main.exists():
        raise SystemExit(f"captacion: falta el render keyframe del capítulo ({main.name}). "
                         "Corré primero 'keyframes <slug>'.")
    beats_json = ep.artifacts / "beats.json"
    if not beats_json.exists():
        raise SystemExit("captacion: falta artifacts/beats.json (corré keyframes).")
    bs = json.loads(beats_json.read_text(encoding="utf-8"))["beats"]
    escenas = elegir_escenas(bs)
    if escenas is None:
        raise SystemExit("captacion: no se pudieron elegir 2 escenas no solapadas")
    esc_a, esc_b = escenas
    kf_dir = ep.dir / "assets" / "kf"

    out = ep.dir / "derivados"
    out.mkdir(exist_ok=True)
    a = _corte_trailer(ep, main, esc_a["t0"], SEGUNDOS_TRAILER,
                       out / "trailer-a-facebook-reel.mp4")
    b = _corte_trailer(ep, main, esc_b["t0"], SEGUNDOS_TRAILER,
                       out / "trailer-b-youtube-short.mp4")
    miniatura = _portada_scroll(ep, kf_dir, esc_a, out / "portada.jpg")

    hist = _historieta(ep, bs, escenas)
    programacion = {
        "fecha_referencia": "hoy",
        "cto": CTA,
        "piezas": [
            {"pieza": "trailer_a_facebook_reel", "archivo": a["archivo"],
             "plataforma": "Facebook Reel", "hora": HORA_TRAILER_FB,
             "desde_s": a["desde_s"], "duracion_s": a["duracion_s"],
             "texto_cta": CTA},
            {"pieza": "trailer_b_youtube_short", "archivo": b["archivo"],
             "plataforma": "YouTube Short", "hora": HORA_SHORT_YT,
             "desde_s": b["desde_s"], "duracion_s": b["duracion_s"],
             "texto_cta": CTA},
            {"pieza": "historieta_facebook", "archivo": hist["archivo"],
             "plataforma": "Facebook (post de texto)", "hora": HORA_HISTORIETA_FB,
             "texto_cta": CTA},
            {"pieza": "portada_scroll", "archivo": miniatura.name if miniatura else None,
             "plataforma": "Miniatura YouTube / tapa de pausa (Facebook/Telegram)",
             "hora": None, "texto_cta": None,
             "nota": "imagen del beat más intenso + pregunta gancho; subir como thumbnail "
                     "en YouTube Studio y portada del Reel"},
            {"pieza": "capitulo_completo_youtube", "archivo": str(main.relative_to(ep.dir)),
             "plataforma": "YouTube", "hora": HORA_CAPITULO, "texto_cta": None},
        ],
        "preview_previo_a_envio": f"{ep.dir}/publicacion/programacion.json",
        "publicado": False,
    }
    dst = ep.dir / "publicacion" / "programacion.json"
    dst.parent.mkdir(exist_ok=True)
    dst.write_text(json.dumps(programacion, indent=2, ensure_ascii=False) + "\n",
                   encoding="utf-8")

    ep.set_stage("captacion", "listo_para_revision")
    print(f"  captacion: A={a['archivo']} (hook @{a['desde_s']}s, {a['duracion_s']}s) "
          f"-> Facebook Reel {HORA_TRAILER_FB}")
    print(f"  captacion: B={b['archivo']} (hook @{b['desde_s']}s, {b['duracion_s']}s) "
          f"-> YouTube Short {HORA_SHORT_YT}")
    print(f"  captacion: historieta {hist['archivo']} ({hist['vinetas']} viñetas) -> FB {HORA_HISTORIETA_FB}")
    if miniatura:
        print(f"  captacion: PORTADA scroll-stop -> {miniatura.relative_to(ep.dir)} "
              f"(imagen del clímax + pregunta gancho, 1080×1920)")
    print(f"  captacion: programación -> publicacion/programacion.json (revisar antes de enviar)")
    return programacion
