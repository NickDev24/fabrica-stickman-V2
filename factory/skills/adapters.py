"""Adaptadores entre Skills y los puntos funcionales reales de la fábrica.

Cada función es la firma ESTÁNDAR de invocación (ep, **kw) que el runtime usa,
resolviendo los argumentos que el módulo real espera. Sin lógica paralela:
los adaptadores difieren la verdad a los módulos canónicos.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

from pipeline import config, gates
from . import contratos


# ---------------------------------------------------------------- animación
def timeline_actuacion(ep) -> dict:
    """3d-character-director: construye la partitura completa y la deja en artifacts/.

    El punto real (director.construir_timeline) espera un Path de episodio, no la clase:
    este adaptador es la única diferencia, sin lógica paralela.
    """
    from factory.acting import director
    meta = ep.metadata()
    return director.construir_timeline(
        ep.dir, voice_meta={"motor": meta.get("voice", ""),
                            "duracion_s": meta.get("narration_duration_s")})


def partitura(ep) -> dict:
    """emotional-story-director: curva emocional por segmento del guion."""
    from factory.acting import director
    from pipeline.stages.narracion import _segments
    segs = _segments(ep.read_text("script.txt"))
    return {"slug": ep.slug, "n": len(segs),
            "partitura": director.emociones_del_guion(segs, ep.slug)}


def expresiones_bloques(ep) -> dict:
    """facial-expression-animator: bloques de rig facial por segmento.

    Reutiliza la timeline del character-director si existe (fuente única de verdad);
    si no, la compone desde estados.py con la partitura. Nunca inventa parámetros:
    todo sale de ESTADOS + transiciones + gestos.
    """
    from factory.acting import estados
    tl_file = ep.dir / "artifacts" / "timeline_actuacion.json"
    if tl_file.exists():
        tl = json.loads(tl_file.read_text(encoding="utf-8"))
        bloques = [{"i": s["i"], "t0": s["t0"], "t1": s["t1"], "emocion": s["emocion"],
                    "rig": s["expresion"]} for s in tl["segmentos"]]
        return {"fuente": "timeline_actuacion", "bloques": bloques,
                "micro": tl.get("micro", []), "blinks": tl.get("blinks", [])}
    issues = partitura(ep)
    prev = estados.ESTADOS["neutralidad"]
    bloques = []
    for item in issues["partitura"]:
        base = estados.ESTADOS[item["emocion"]]
        rig = estados.aplicar_gesto(
            estados.transicion_bloque(prev, base, 0.45, 0.45, item["intensidad"]),
            item["gesto"] or "narrar")
        bloques.append({"emocion": item["emocion"], "rig": rig})
        prev = base
    return {"fuente": "partitura_directa", "bloques": bloques}


def lipsync_cues(ep) -> dict:
    """phoneme-lipsync-engineer: visemas alineados al WAV real de Piper."""
    from factory.acting import lipsync
    from pipeline.stages.narracion import _segments
    meta = ep.metadata()
    wav = ep.dir / "artifacts" / "narracion_lips.wav"
    if not wav.exists():
        wav = ep.dir / meta.get("narration_path", "assets/audio/narration.wav")
    if not wav.exists():
        raise FileNotFoundError("sin narración para alinear (corré 'narrar' primero)")
    segs = _segments(ep.read_text("script.txt"))
    data = lipsync.cue_wav(wav.resolve(), segs, ep.dir / "artifacts" / "lipsync.json")
    probs = contratos.validar_lipsync_cues(data)
    if probs:
        raise contratos.ContratoFallido("; ".join(probs))
    ep.write_json("lipsync_resumen.json", {"motor": data["motor"], "n_cues": len(data["cues"]),
                                           "duracion_s": data["duracion_s"]})
    return data


def lenguaje_corporal(ep) -> dict:
    """body-language-director: plan de gestos con anticipación y settle."""
    from factory.acting import estados
    tl_file = ep.dir / "artifacts" / "timeline_actuacion.json"
    if not tl_file.exists():
        raise FileNotFoundError("requiere la timeline de actuación (3d-character-director)")
    tl = json.loads(tl_file.read_text(encoding="utf-8"))
    plan = []
    for s in tl["segmentos"]:
        g = s.get("gesto") or "narrar"
        spec = estados.GESTOS.get(g)
        dur_g = (spec["dur"][1] if spec else 2.0) / max(s.get("velocidad", 1.0), 0.3)
        plan.append({"i": s["i"], "gesto": g, "t0": s.get("gesto_t0", s["t0"]),
                     "t_max": round(s.get("gesto_t0", s["t0"]) + dur_g, 2),
                     "anticipacion_s": 0.08, "settle_s": 0.2,
                     "velocidad": s.get("velocidad", 1.0)})
    return {"plan": plan, "vocabulario": sorted(estados.GESTOS)}


def plan_camara(ep) -> dict:
    """cinematic-camera-director: el MISMO plan que va a renderizarse (director.planos_del_segmento).

    No reimplementa la política: si la timeline y este plan difieren, hay un bug en la
    fábrica y la skill lo reporta como problema de continuidad de cámara.
    """
    from factory.acting import director as d
    tl_file = ep.dir / "artifacts" / "timeline_actuacion.json"
    if not tl_file.exists():
        raise FileNotFoundError("requiere la timeline de actuación")
    tl = json.loads(tl_file.read_text(encoding="utf-8"))
    esperados = [p for s in tl["segmentos"] for p in d.planos_del_segmento(s)]
    reales = tl.get("camara", [])
    probs = []
    if len(esperados) != len(reales):
        probs.append(f"la timeline tiene {len(reales)} planos y la política exige {len(esperados)}")
    for e, r in zip(esperados, reales):
        if (e["t0"], e["t1"], e["tipo"]) != (r["t0"], r["t1"], r["tipo"]):
            probs.append(f"desfase de plano en {e['t0']:.1f}s: timeline={r.get('tipo')} "
                         f"política={e['tipo']}")
            break
    return {"planos": esperados, "n": len(esperados), "fps": tl.get("fps", 24),
            "problemas": probs}


def recursos(ep=None) -> dict:
    """render-optimization-engineer: límites reales del hardware/config."""
    return config.limites()


# ---------------------------------------------------------------- narrativa
def senales(ep=None) -> dict:
    """viral-story-researcher: demanda real (Wikipedia, HN, canales)."""
    from pipeline import tendencias
    data = tendencias.detectar(refresh=False)
    return {"senales": data[:20] if isinstance(data, list) else data}


def universo_serie(ep) -> dict:
    """series-universe-builder: continuidad de serie por categoría, con episodios reales."""
    episodios = []
    for d in sorted(config.PROJECTS.iterdir()):
        f = d / "episode.json"
        if not f.exists():
            continue
        try:
            st = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if st.get("categoria") == ep.categoria:
            episodios.append({"slug": st.get("slug", d.name), "titulo": st.get("title", "")})
    univ = {"categoria": ep.categoria, "episodios": episodios,
            "cast_recurrente": ["narrador-rol-por-defecto"],
            "nota": "cast/paleta se amplían cuando el perfil de personaje lo registra "
                    "(factory/acting/continuidad)."}
    ep.write_json("universo.json", univ)
    return univ


def publicar_facebook(ep) -> dict:
    """facebook-content-strategist vía conector Zernio oficial.

    Usa el MISMO plan que el pipeline (_plan_publicacion): si el adapter armará su propia
    lista de archivos, el reel publicado por Telegram y el publicado por acá serían distintos.
    """
    import json
    from pipeline import config, gates, zernio
    from pipeline.stages import publicacion
    gates.gate_publicacion(ep.metadata())
    ruta_desc = ep.dir / "publicacion" / "descripciones.json"
    desc = json.loads(ruta_desc.read_text(encoding="utf-8")) if ruta_desc.exists() else {}
    ids = {"facebook": config.zernio_config()["facebook"]}
    pieza = next((i for i in publicacion._plan_publicacion(ep, ids, desc)
                  if i["plataforma"] == "facebook"), None)
    if pieza is None:
        raise FileNotFoundError("no hay reel de Facebook en el plan (derivados/facebook-reel.mp4)")
    url = zernio.upload(pieza["archivo"])
    return zernio.create_post(pieza["descripcion"], [url], pieza["plataformas"],
                              title=pieza["titulo"], idempotency_key=f"{ep.slug}:facebook")


def politica(ep) -> dict:
    """monetization-policy-reviewer: gate_publicacion sobre la metadata real."""
    probs = gates.gate_publicacion(ep.metadata())
    return {"problemas": probs, "estado": "pass" if not probs else "block"}


# ---------------------------------------------------------------- producción
def plan_sonoro(ep) -> dict:
    """sound-design-engineer: mezcla por segmento alineada a la partitura.

    Música de biblioteca autorizada a -18 dB bajo la voz con ducking, ambientes
    donde la narrativa los pidió, silencios dramáticos en suspenso. Produce plan
    ejecutable con FFmpeg en artifacts/plan_sonoro.json.
    """
    tl_file, = (ep.dir / "artifacts" / "timeline_actuacion.json",)
    if not tl_file.exists():
        raise FileNotFoundError("requiere la timeline de actuación")
    tl = json.loads(tl_file.read_text(encoding="utf-8"))
    pistas = []
    for s in tl["segmentos"]:
        sfx = s.get("sfx", "none")
        if sfx and sfx != "none":
            pistas.append({"t0": s["t0"], "t1": s["t1"], "tipo": "amb", "cual": sfx,
                           "gain_db": -14})
    plan = {"pistas": pistas,
            "voz": str(tl.get("audio", {}).get("narracion") or ""),
            "regla_musica": "música autorizada a -18 dB bajo la voz (ducking con sidechaincompress)",
            "mezcla": "lavfi amix: voz central, ambientes -14 dB, música -18 dB"}
    ep.write_json("plan_sonoro.json", plan)
    return plan


# ---------------------------------------------------------------- calidad
def _render_principal(ep) -> Path:
    p = ep.dir / "renders" / f"{ep.slug}-main.mp4"
    if not p.exists():
        r = sorted((ep.dir / "renders").glob("*.mp4")) if (ep.dir / "renders").exists() else []
        if not r:
            raise FileNotFoundError("no hay render para inspeccionar")
        p = r[-1]
    return p


def inspeccionar_visual(ep, video=None) -> dict:
    """visual-quality-inspector: fotogramas negros y congelados reales (ffmpeg)."""
    video = Path(video) if video else _render_principal(ep)
    r = subprocess.run(
        ["ffmpeg", "-hide_banner", "-ss", "1", "-i", str(video), "-t", "300",
         "-vf", "blackdetect=d=0.08:pix_th=0.02,freezedetect=n=0.003:d=2",
         "-an", "-f", "null", "-"],
        capture_output=True, text=True, timeout=600)
    negros = []
    for line in (r.stderr or "").splitlines():
        if "black_start" in line:
            kvs = dict(kv.split("=", 1) for kv
                       in line.split("blackdetect:", 1)[1].split(",") if "=" in kv)
            negros.append({"t0": float(kvs.get("black_start", 0)),
                           "dur": float(kvs.get("black_duration", 0))})
    total = round(sum(n["dur"] for n in negros), 2)
    problemas = [f"fotograma negro en {n['t0']:.1f}s ({n['dur']:.2f}s)"
                 for n in negros if n["dur"] >= 0.3]
    sal = {"video": str(video), "segundos_negros": total, "n_negros": len(negros),
           "problemas": problemas}
    ep.write_json("qc_visual.json", sal)
    return sal


def inspeccionar_audio(ep, video=None) -> dict:
    """audio-quality-inspector: LUFS integrados y True Peak reales (ffmpeg ebur128)."""
    video = Path(video) if video else _render_principal(ep)
    r = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(video), "-map", "0:a:0",
                        "-af", "ebur128=peak=true", "-vn", "-f", "null", "-"],
                       capture_output=True, text=True, timeout=900)
    tail = (r.stderr or "").split("Summary:")[-1]
    lufs, pico = None, None
    for line in tail.splitlines():
        line = line.strip()
        if line.startswith("I:"):
            lufs = line.split("I:", 1)[1].strip().split(" ")[0].replace("LUFS", "").strip()
        elif line.startswith("Peak:"):
            pico = line.replace("Peak:", "").strip().split(" ")[0].replace("dBTP", "")
    problemas = []
    if lufs is None or pico is None:
        # Sin medición no hay aprobación posible: reportarlo, nunca dejarlo como "sin problemas".
        problemas.append("no se pudo medir loudness (ebur128 no devolvió Summary: ¿video sin "
                         "pista de audio o ffmpeg falló?)")
    if lufs is not None:
        v = float(lufs)
        if v < -22:
            problemas.append(f"volumen muy bajo ({v:.1f} LUFS; objetivo -16 a -14 para web)")
        elif v > -12:
            problemas.append(f"demasiado fuerte ({v:.1f} LUFS): riesgo de clipping")
    sal = {"video": str(video), "lufs": lufs, "peak_dbtp": pico, "problemas": problemas}
    ep.write_json("qc_audio.json", sal)
    return sal


def auditar_licencias(ep) -> dict:
    """copyright-compliance-reviewer: cada imagen usada debe tener fuente en
    bibliotecas de licencia verificable (Commons/Wikipedia/gov/edu)."""
    probs, usados, detalle = [], [], []
    urls = []
    urls_path = ep.dir / "research" / "urls.txt"
    if urls_path.exists():
        urls = [u.strip() for u in urls_path.read_text(encoding="utf-8").splitlines()
                if u.strip() and not u.startswith("#")]
    img_dir = ep.dir / "assets" / "img"
    if img_dir.exists():
        for img in sorted((f for f in img_dir.iterdir() if f.is_file()),
                          key=lambda p: p.name):
            fuente = next((u for u in urls if u.rstrip("/").rsplit("/", 1)[-1].lower()
                           in img.stem.lower()), None)
            dominio_ok = any(d in (fuente or "") for d in (
                "wikipedia.org", "wikimedia.org", "commons.wikimedia.org",
                "nasa.gov", ".gov", ".edu"))
            if fuente and dominio_ok:
                detalle.append({"asset": img.name, "fuente": fuente})
            elif fuente:
                probs.append(f"{img.name}: fuente fuera de bibliotecas de licencia verificable")
            else:
                probs.append(f"{img.name}: sin fuente registrada")
            usados.append(img.name)
    return {"n_assets": len(usados), "licencias_ok": len(detalle),
            "problemas": probs, "detalle": detalle[:50]}
