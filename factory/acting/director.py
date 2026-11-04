"""Director de actuación: convierte guion narrado + audio en una timeline executable.

Entradas:
  - artifacts/script.txt segmentado (igual que narracion._segments)
  - metadata con segment_durations_s (timing real de Piper)
  - opt: emoción declarada por IA (factory/skills: emotional-story-director)

Salidas (contrato de datos factory/timeline-schema.json):
  artifacts/timeline_actuacion.json con:
    - curva emocional por segmento (13 estados, transiciones suaves)
    - visemas (motor rhubarb) con tiempos reales
    - parpadeos, respiración, micro-reacciones, pausas expresivas
    - planos de cámara motivados por el contenido
    - acciones corporales contextuales (GESTOS de estados.py)

La IA NO actúa: propone la partitura. La ejecución la hace el backend de render
(GLB renderer o mascota mesh-avatar) leyendo ESTA timeline — un solo contrato.
"""
from __future__ import annotations

import json
import math
import subprocess
from pathlib import Path

from . import estados
from .lipsync import cue_wav

FPS = 24

# Política de cámara por emoción (pilar 4: dirección cinematográfica con propósito).
CAMARA_POR_EMOCION = {
    "neutralidad":  ("medio", "fijo"),
    "alegria":      ("medio", "leve_travelling"),
    "sorpresa":     ("contrapicado", "rapida"),
    "curiosidad":   ("medio", "zoom_lento"),
    "miedo":        ("primer_plano", "lento_lateral"),
    "terror":       ("primerisimo_primer_plano", "titubeo"),
    "tristeza":     ("medio", "fijo"),
    "enojo":        ("medio", "energica"),
    "confusion":    ("medio", "leve_travelling"),
    "ironia":       ("medio", "fijo"),
    "suspenso":     ("primer_plano", "acercamiento_lento"),
    "determinacion":("primer_plano", "fijo"),
    "tranquilidad": ("general", "fijo"),
}


OSCURO = ("grito", "sangre", "muerte", "desapareci", "noche", "silencio", "colapso",
          "perdi", "tarde", "hambre", "enfermedad", "guerra", "error", "fracaso", "brutal")
CIERRE = ("leccion", "lección", "imagina", "imaginás", "futuro", "nos pasa", "aprend", "hoy")


def _partitura_determinista(segs: list[str]) -> list[dict]:
    """Arco por posición + señales del texto. No es la IA actuando: es la red de seguridad
    para que el motor nunca se quede sin partitura. Marca cada bloque con origen=determinista.

    Desarrollo (primera mitad) -> curiosidad sostenida; giro (segunda mitad con contenido
    oscuro) -> suspenso creciente; cierre -> determinacion si hay lección/pregunta abierta.
    """
    n = len(segs)
    out = []
    for i, s in enumerate(segs):
        low = s.lower()
        oscuro = sum(1 for w in OSCURO if w in low)
        if i == 0:
            if s.rstrip().endswith("?") or low.startswith("¿"):
                e, g, inten = "curiosidad", "senalar", 0.65
            elif s.rstrip().endswith("!"):
                e, g, inten = "sorpresa", "sorprenderse", 0.7
            else:
                e, g, inten = "curiosidad", "narrar", 0.6
        elif i == n - 1:
            if oscuro or any(w in low for w in CIERRE):
                e, g, inten = "determinacion", "advertir", 0.7
            else:
                e, g, inten = "tranquilidad", "narrar", 0.5
        elif oscuro >= 2:
            e, g, inten = "suspenso", "advertir", round(min(0.85, 0.55 + 0.1 * (i - n / 2)), 2)
        elif i < n / 2:
            e, g, inten = "curiosidad", "narrar", round(0.5 + 0.05 * i, 2)
        elif oscuro == 1:
            e, g, inten = "confusion", "narrar", 0.55
        else:
            e, g, inten = "neutralidad", "narrar", 0.5
        out.append({"emocion": e, "intensidad": inten, "gesto": g,
                    "enfatiza": [], "sfx": "none", "origen": "determinista"})
    return out


CORTE_INTERIOR_S = 8.0   # un plano sostenido más de 8 s en 30-60 s de pieza mata el ritmo
COMPLEMENTARIO = {"primerisimo_primer_plano": "primer_plano", "primer_plano": "medio",
                  "medio": "primer_plano", "general": "medio", "contrapicado": "medio"}


def planos_del_segmento(seg: dict) -> list[dict]:
    """Política de cámara de la fábrica: plano motivado por la emoción + corte interior.

    Fuente única: la consume el timeline real y la skill cinematic-camera-director, que
    audita exactamente lo mismo que se va a renderizar (sin lógica paralela entre ambas).
    """
    tipo, mov = CAMARA_POR_EMOCION.get(seg["emocion"], ("medio", "fijo"))
    out = [{"t0": seg["t0"], "t1": seg["t1"], "tipo": tipo, "mov": mov,
            "motivo": f"emoción {seg['emocion']} (int {seg.get('intensidad', 0.5):.2f})"}]
    dur = seg["t1"] - seg["t0"]
    if dur > CORTE_INTERIOR_S:
        tc = round(seg["t0"] + dur / 2, 2)
        out[0]["t1"] = tc          # tramos SIN solaparse: el renderer toma el primer match
        out.append({"t0": tc, "t1": seg["t1"], "tipo": COMPLEMENTARIO.get(tipo, "medio"),
                    "mov": "fijo", "motivo": f"corte interior: tramo de {dur:.1f} s"})
    return out


def emociones_del_guion(segs: list[str], slug: str) -> list[dict]:
    """La IA propone emoción/intensidad/gesto/énfasis por segmento (skill emotional-story-director).

    Fallback determinista si el LLM falla: mapa por signos de puntuación/exclamación
    para que el motor nunca quede sin partitura.

    Por defecto NO se llama al LLM: en el B950 un modelo local tarda minutos y puede
    congelar la corrida. La partitura determinista es la ruta operativa; `DIRECTOR_LLM=1`
    habilita la propuesta por IA cuando haya un proveedor con cuota y latencia útil.
    """
    import os
    if os.environ.get("DIRECTOR_LLM", "0").strip().lower() not in ("1", "true", "yes", "on"):
        print("  partitura emocional determinista (DIRECTOR_LLM desactivado)")
        return _partitura_determinista(segs)
    try:
        from pipeline import llm as _llm
        prompt = (
            "Dirección emocional de un documental/historia narrada. Dada la lista de segmentos "
            "numerados, elegí para cada uno: emocion (UNA de: " + ", ".join(estados.ESTADOS) + "), "
            "intensidad (0.2-1.0), gesto (UNO de: " + ", ".join(estados.GESTOS) + " o none), "
            "palabras enfatizadas (índices de palabras del segmento, 1-3), y sfx sugerido "
            "(amb_noche|amb_mar|amb_ciudad|impacto|none). Devolvé SOLO JSON: "
            '{"segmentos":[{"i":0,"emocion":"...","intensidad":0.5,"gesto":"...","enfatiza":[0],"sfx":"none"}]}. '
            "La escalada emocional debe tener sentido narrativo (curva, no uniformidad)."
        )
        body = "\n".join(f"[{i}] {s[:600]}" for i, s in enumerate(segs))
        data = _llm.chat_json([{"role": "system", "content": prompt},
                               {"role": "user", "content": body}],
                              max_tokens=1600, tag="actuacion", episode=slug, task="direccion")
        n_out = len(data.get("segmentos", []))
        print(f"  partitura emocional via LLM ({n_out} segmentos)")
        out = []
        for item in data.get("segmentos", []):
            i = int(item.get("i", len(out)))
            if i != len(out) or i >= len(segs):
                continue
            e = str(item.get("emocion", "neutralidad")).lower()
            if e not in estados.ESTADOS:
                e = "neutralidad"
            g = str(item.get("gesto", "narrar"))
            if g not in estados.GESTOS:
                g = "narrar"
            out.append({"emocion": e,
                        "intensidad": max(0.2, min(1.0, float(item.get("intensidad", 0.5)))),
                        "gesto": None if g in ("none", "null") else g,
                        "enfatiza": [int(x) for x in (item.get("enfatiza") or [])][:3],
                        "sfx": str(item.get("sfx", "none")), "origen": "llm"})
        while len(out) < len(segs):
            out.append({"emocion": "neutralidad", "intensidad": 0.5, "gesto": "narrar",
                        "enfatiza": [], "sfx": "none", "origen": "relleno"})
        return out[:len(segs)]
    except Exception as exc:
        print(f"  partitura emocional FALLÓ a fallback determinista: {exc.__class__.__name__}: {exc}")
        return _partitura_determinista(segs)
        return out


def parpadeos(dur: float, k0: int, rng=None) -> list[float]:
    """Parpadeos naturales: 12-20 por minuto, con agrupamiento humano (2-3 seguidos)."""
    import random
    rng = rng or random.Random(k0)
    out, t = [], 0.5
    while t < dur:
        out.append(round(t, 3))
        if rng.random() < 0.25:  # a veces doble parpadeo
            out.append(round(t + 0.25, 3))
            t += 0.5
        t += rng.uniform(2.5, 5.5)
    return out


def micro_comportamientos(t_start: float, dur: float, estado: str, k0: int) -> list[dict]:
    """Comportamientos sutiles por segmento: miradas al costado, inclinaciones rítmicas,
    respiración y pausas expresivas (pilares 1/3/6)."""
    import random
    rng = random.Random(k0)
    evs = []
    n = max(1, int(dur / 4))
    for i in range(n):
        t = t_start + rng.uniform(0.2, max(0.3, dur - 0.6))
        tipo = rng.choice(["mirada_lateral", "inclinacion_ritmica", "respiracion", "pausa_expresiva"])
        evs.append({"t": round(t, 3), "tipo": tipo, "estado": estado, "d": round(rng.uniform(0.2, 0.5), 3)})
    return evs


def construir_timeline(dir_ep: Path, voice_meta: dict | None = None) -> dict:
    """Full timeline: guion + audio + física temporal -> JSON determinista y renderizable."""
    from pipeline.stages.narracion import _segments  # mismo segmentado que la voz
    script = (dir_ep / "artifacts" / "script.txt").read_text(encoding="utf-8")
    segs = _segments(script)
    meta_path = dir_ep / "artifacts" / "metadata.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    durs = meta.get("segment_durations_s") or []
    if not durs:
        raise SystemExit("sin narración previa: corré primero la etapa 'narrar' (Piper)")
    if len(durs) != len(segs):
        # El audio y el guion son la misma partitura: si difieren, los tiempos absolutos
        # de los segmentos sobrantes caerían a 0 y el lip-sync se desalinearía todo.
        raise SystemExit(f"guion y audio no coinciden: {len(segs)} segmentos en script.txt vs "
                         f"{len(durs)} audios en metadata; re-corré la etapa 'narrar'")
    try:
        episodio_json = json.loads((dir_ep / "episode.json").read_text(encoding="utf-8"))
        categoria = episodio_json.get("categoria", "")
    except (OSError, json.JSONDecodeError):
        categoria = ""

    # Una única fuente temporal para voz, visemas y timeline: el WAV que se mezcla al video.
    wav = dir_ep / meta.get("narration_path", "assets/audio/narration.wav")
    lips_path = dir_ep / "artifacts" / "lipsync.json"
    lips = cue_wav(wav.resolve(), segs, lips_path)

    partitura = emociones_del_guion(segs, dir_ep.name)

    # TIEMPOS: cada segmento arranca donde empieza su audio (concat + pausas ya en el WAV).
    # Calcula offsets reales con ffprobe sobre los segmentos de audio.
    seg_dir = dir_ep / "assets" / "audio" / "segments"
    offsets = []
    t = 0.0
    for i in range(len(segs)):
        offsets.append(round(t, 3))
        d_i = durs[i] if i < len(durs) else 0.0
        if i < len(segs) - 1:
            seg_file = seg_dir / f"seg-{i:03d}.wav"
            if seg_file.exists():
                from pipeline.stages.narracion import _dur as _dur_wav
                d_i = _dur_wav(seg_file)
        # Cada segmento ya contiene las pausas que Piper agregó al final de sus frases.
        t += d_i

    timeline = {
        "fps": FPS,
        "personaje": {"integracion": detectar_backend(dir_ep), "categoria": categoria},
        "duracion_s": round(sum(durs), 2),
        "voice": voice_meta or {},
        "lipsync": {"motor": lips["motor"], "n_cues": len(lips["cues"])},
        "partitura": partitura[0].get("origen", "llm") if partitura else "determinista",
        "segmentos": [],
        "blinks": [],
        "micro": [],
        "camara": [],
        "audio": {"narracion": str(wav), "musica": None, "sfx": []},
    }

    prev_estado = "neutralidad"
    for i, seg in enumerate(segs):
        part = partitura[i]
        dur = durs[i] if i < len(durs) else 0.0
        t0 = offsets[i]
        base = estados.ESTADOS[part["emocion"]]
        # Transición suave desde el estado previo (0.45 s + intensidad)
        trans = estados.transicion_bloque(estados.ESTADOS[prev_estado], base, 0.45, 0.45,
                                         part["intensidad"])
        bloque = estados.aplicar_gesto(trans, part["gesto"] or "narrar")
        gesto_t0 = t0 + 0.3
        timeline["segmentos"].append({
            "i": i, "t0": t0, "t1": round(t0 + dur, 3), "texto": seg,
            "emocion": part["emocion"], "intensidad": part["intensidad"],
            "gesto": part["gesto"], "gesto_t0": round(gesto_t0, 3),
            "enfatiza": part["enfatiza"], "velocidad": round(base["velocidad_gesto"], 2),
            "expresion": bloque, "sfx": part["sfx"],
        })
        prev_estado = part["emocion"]

    # Parpadeos globales: no más de 18 por minuto real
    timeline["blinks"] = parpadeos(timeline["duracion_s"], 7)
    for seg in timeline["segmentos"]:
        timeline["micro"] += micro_comportamientos(seg["t0"], seg["t1"] - seg["t0"],
                                                   seg["emocion"], 5000 + seg["i"])
    # Cámara: política única (planos_del_segmento), la misma que audita la skill de cámara
    for seg in timeline["segmentos"]:
        timeline["camara"] += planos_del_segmento(seg)
    # Trim de parpadeos/micro a la duración
    timeline["blinks"] = [b for b in timeline["blinks"] if b < timeline["duracion_s"]]
    timeline["micro"] = [m for m in timeline["micro"] if m["t"] < timeline["duracion_s"]]
    out = dir_ep / "artifacts" / "timeline_actuacion.json"
    out.write_text(json.dumps(timeline, ensure_ascii=False, indent=1), encoding="utf-8")
    return timeline


def detectar_backend(dir_ep: Path) -> str:
    root = dir_ep.parents[1]
    glbs = sorted(glob_glb(root / "assets"))
    if glbs:
        return "glb:" + str(glbs[0].relative_to(root))
    mascota_rig = root / "assets" / "mascota" / "rig.json"
    if mascota_rig.exists():
        return "mascota:" + str(mascota_rig.relative_to(root))
    return "pendiente"


def glob_glb(dir_path: Path):
    return list(dir_path.glob("**/*.glb")) if dir_path.exists() else []
