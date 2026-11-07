"""Etapa 3: narración con Piper (voz propia del canal) + gate de voz (gate 2).

Piper reemplazó a VibeVoice: medido 22,5 s de síntesis para 45 s de audio en el B950.
Fallback declarado: edge-tts es-AR-TomasNeural (si el servicio/volverse a instalar).
"""
from __future__ import annotations

import json
import subprocess
import re
import shutil
import subprocess
import time
from pathlib import Path

from .. import config, gates
from ..episode import Episode
from factory import parametros


def _segments(script: str) -> list[str]:
    body = "\n".join(l for l in script.splitlines()
                     if not l.startswith("#") and not l.startswith("Fuentes:"))
    segs = [s.strip() for s in re.split(r"\n\s*\n", body) if s.strip()]
    segs = [s for s in segs if not s.startswith("Fuentes:")]
    return [re.sub(r"\s+", " ", s) for s in segs]


def _marcar_prosodia(text: str) -> str:
    """Lo que el motor lee mal, escrito como se dice. No toca una sola palabra.

    Medido: edge-tts IGNORA el espaciado extra ("A. B." y "A.  B." dan exactamente la misma
    duración), así que duplicar espacios después de la puntuación — que era lo único que hacía
    esta función — no producía ninguna pausa. Lo que sí cambia el resultado es la notación:
    "12,5%" sale del motor como "doce punto cinco por ciento" en algunas tomas y "3.000" como
    "tres punto cero cero cero". Eso se escribe en limpio acá.
    """
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r";\s*", ". ", text)
    text = re.sub(r"(\d)\s*%", r"\1 por ciento", text)
    # separador de miles es-AR: 3.000 / 1.250.000 -> 3000 / 1250000 (la coma decimal NO se toca)
    while re.search(r"\d\.\d{3}(\.\d{3})*\b", text):
        text = re.sub(r"(\d)\.(\d{3})\b", r"\1\2", text)
    return text


def _respirar(wav: Path, gap_s: float) -> None:
    """Silencio inicial afuera, pausa de bloque adentro, y el archivo queda medible.

    Se hace sobre el WAV (no sobre el texto) porque es lo único que el motor no puede fallar:
    la pausa queda medida en el propio segmento, así `segment_durations_s` ya la incluye y el
    planificador de beats sigue viendo el mismo audio que escucha el espectador.
    """
    af = ["silenceremove=start_periods=1:start_threshold=-45dB"]
    if gap_s > 0:
        af.append(f"apad=pad_dur={gap_s:.3f}")
    tmp = wav.with_suffix(".respira.wav")
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(wav), "-af", ",".join(af),
                    "-c:a", "pcm_s16le", str(tmp)], check=True)
    tmp.replace(wav)


def _gap_de_bloque(bloque: str, i: int, ultimo: bool) -> float:
    if ultimo:
        return 0.0
    pausas = parametros.pausas_ms()
    clave = ("fin_de_bloque_pregunta_ms" if bloque.rstrip().endswith("?")
             else "fin_de_bloque_ms")
    base = int(pausas.get(clave, 650))
    ciclo = parametros.variacion_pausa()
    factor = ciclo[i % len(ciclo)] if ciclo else 1.0
    return round(base * factor, 3) / 1000.0


def _rol_de_bloque(bloque: str, i: int) -> str:
    """Gancho, pregunta o base: el único lugar donde vale la pena bajar el ritmo."""
    if i == 0:
        return "gancho"
    if bloque.rstrip().endswith("?") or bloque.rstrip().endswith("?!"):
        return "pregunta"
    return "base"


def _piper(text: str, out: Path, length_scale: float | None = None,
           sentence_silence: float | None = None) -> None:
    if not config.PIPER_BIN.exists():
        raise SystemExit(f"Piper no está en {config.PIPER_BIN} — reinstalá ~/piper-env o habilitá edge-tts.")
    proc = subprocess.run(
        [str(config.PIPER_BIN), "--model", str(config.PIPER_MODEL_PATH),
         "--length-scale", str(length_scale or config.PIPER_LENGTH_SCALE),
         "--noise-scale", "0.55", "--noise-w-scale", "0.72", "--volume", "0.92",
         "--sentence-silence", str(sentence_silence if sentence_silence is not None
                                   else config.PIPER_SENTENCE_SILENCE),
         "--output_file", str(out)],
        input=text, text=True, capture_output=True, cwd=config.ROOT)
    if proc.returncode != 0:
        raise RuntimeError(f"piper falló: {proc.stderr[:300]}")

def _dur(wav: Path) -> float:
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                        "-of", "json", str(wav)], capture_output=True, text=True)
    return float(json.loads(r.stdout)["format"]["duration"])


def _edge(text: str, out: Path, voice: str, rol: str = "base") -> None:
    """edge-tts (Microsoft neural, CapCut-like) a WAV 22050/mono PCM para el master.

    El rate/pitch vienen de factory/audio/voice_config.json:`prosodia`. Se pasan como
    `--rate=-6%` en un solo token porque argparse toma "-6%" por una opción si va separado.
    """
    if not config.EDGE_TTS_BIN.exists():
        raise SystemExit(f"edge-tts no está en {config.EDGE_TTS_BIN} — "
                         f"instalalo en ~/.local/bin o apuntá EDGE_TTS_BIN")
    pros = parametros.prosodia(rol)
    tmp = out.with_suffix(".edge.mp3")
    subprocess.run([str(config.EDGE_TTS_BIN), "--voice", voice,
                    f"--rate={pros['rate']}", f"--pitch={pros['pitch']}",
                    "--no-progress",
                    "--text", _marcar_prosodia(text),
                    "--write-media", str(tmp)], check=True, timeout=300)
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(tmp),
                    "-ar", "22050", "-ac", "1", "-c:a", "pcm_s16le", str(out)],
                   check=True)
    tmp.unlink(missing_ok=True)


def _silencio(seg_dir: Path, i: int, rol: str) -> None:
    """Sustituir un bloque que el motor no puede leer por una pausa real."""
    out = seg_dir / f"seg-{i:03d}.wav"
    out.unlink(missing_ok=True)
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
                    "anoisesrc=duration=1.2:sample_rate=22050", "-c:a", "pcm_s16le", str(out)],
                    check=True)
    _respirar(out, _gap_de_bloque("", i, i == False))


def narrar(ep: Episode, voice_ref: str | None = None) -> None:
    voice_ref = voice_ref or config.VOZ_PREFERIDA
    gates.gate_voz(voice_ref)  # GATE 2: sólo voces propias del canal

    script = ep.read_text("script.txt")
    segs = _segments(script)
    audio_dir = ep.dir / "assets" / "audio"
    seg_dir = audio_dir / "segments"
    seg_dir.mkdir(parents=True, exist_ok=True)
    for old in seg_dir.glob("seg-*.wav"):
        old.unlink()

    t0 = time.time()
    durations = []
    gaps: list[float] = []
    roles = []
    for i, text in enumerate(segs):
        out = seg_dir / f"seg-{i:03d}.wav"
        rol = _rol_de_bloque(text, i)
        roles.append(rol)
        # Corrección local: el motor edge-tts falla leyendo guiones con l"-\n" y
        # "---" solos (ver mensaje real 2026-11-05). Se convierten en silencio de pausa,
        # no en audio que pueda romper la narración.
        if text in ("-", "--", "---"):
            _silencio(seg_dir, i, rol)
            continue
        if voice_ref.startswith("piper:"):
            if not config.PIPER_MODEL_PATH.exists():
                raise SystemExit(f"No existe el modelo Piper {config.PIPER_MODEL_PATH}; instalarlo o definir PIPER_MODEL_PATH.")
            # El mismo ajuste de rol que el edge-tts, traducido: --rate=-6% equivale a
            # length-scale 1/0,94. Sin esto el fallback se leía igual de rápido en el gancho.
            _piper(_marcar_prosodia(text), out, length_scale=parametros.length_scale(rol))
        else:
            _edge(text, out, voice_ref.split(":", 1)[1], rol=rol)
        # La respiración es del relato, no del motor: la misma pausa sea cual sea la voz.
        gap = _gap_de_bloque(text, i, i == len(segs) - 1)
        gaps.append(gap)
        _respirar(out, gap)
        durations.append(_dur(out))
        print(f"  seg {i+1}/{len(segs)} [{rol}]: {durations[-1]:.1f}s "
              f"(pausa {gap * 1000:.0f} ms)")
    synth_s = round(time.time() - t0, 1)

    concat = audio_dir / "concat.txt"
    concat.write_text("".join(f"file 'segments/seg-{i:03d}.wav'\n" for i in range(len(segs))),
                      encoding="utf-8")
    narration = audio_dir / "narration.wav"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0",
                    "-i", str(concat), "-c:a", "pcm_s16le", str(narration)], check=True)
    # El director/Rhubarb analiza exactamente el audio final: no introducir un retardo
    # artificial que separe los visemas de la voz. Piper ya inserta las pausas declaradas.
    lips_wav = ep.artifacts / "narracion_lips.wav"
    if lips_wav.exists():
        lips_wav.unlink()

    meta = ep.metadata()
    total_s = round(sum(durations), 2)
    palabras = sum(len(re.sub(r"[¿?¡!.,;:—–\"']", " ", s).split()) for s in segs)
    pps = round(palabras / max(0.001, total_s), 3)
    meta.update({
        "voice": voice_ref,
        "narration_engine": "piper" if voice_ref.startswith("piper:") else "edge-tts",
        "narration_path": str(narration.relative_to(ep.dir)),
        "narration_duration_s": total_s,
        "segment_durations_s": [round(d, 2) for d in durations],
        "segment_gaps_s": [round(g, 3) for g in gaps],
        "prosodia": {"roles": roles,
                     "perfiles": {r: parametros.prosodia(r) for r in {"base", *roles}}},
        "palabras_narradas": palabras,
        "palabras_por_segundo_reales": pps,
        "synthetic_content": True,  # GATE 3: siempre, porque la narración es IA
    })
    # GATE 8: el ritmo medido del audio contra el que asume el template. Si afuera, la
    # duración prometida del capítulo ya no es verdad y hay que recalcular, no publicar.
    razones = gates.gate_ritmo(total_s, palabras, parametros.palabras_por_segundo())
    ep.save_metadata(meta)
    if razones:
        raise SystemExit("GATE RITMO: " + razones[0])
    gates.gate_contenido_sintetico(meta)
    ep.write_json("timing-tts.txt.json", {"sintesis_s": synth_s, "audio_s": total_s,
                                          "palabras": palabras, "pps_reales": pps})
    ep.set_stage("narracion", "done")
    print(f"  narración: {narration.name} {total_s/60:.1f} min, {pps:.2f} pal/s "
          f"(objetivo {parametros.palabras_por_segundo():.2f}) | síntesis {synth_s}s | flag sintético ON")
