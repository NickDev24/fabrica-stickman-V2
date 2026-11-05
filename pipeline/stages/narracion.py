"""Etapa 3: narración con Piper (voz propia del canal) + gate de voz (gate 2).

Piper reemplazó a VibeVoice: medido 22,5 s de síntesis para 45 s de audio en el B950.
Fallback declarado: edge-tts es-AR-TomasNeural (si el servicio/volverse a instalar).
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import time
from pathlib import Path

from .. import config, gates
from ..episode import Episode


def _segments(script: str) -> list[str]:
    body = "\n".join(l for l in script.splitlines()
                     if not l.startswith("#") and not l.startswith("Fuentes:"))
    segs = [s.strip() for s in re.split(r"\n\s*\n", body) if s.strip()]
    segs = [s for s in segs if not s.startswith("Fuentes:")]
    return [re.sub(r"\s+", " ", s) for s in segs]


def _marcar_prosodia(text: str) -> str:
    """Añade pausas naturales de TTS según puntuación, sin alterar las palabras."""
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r";\s*", ".  ", text)
    text = re.sub(r":\s*", ":  ", text)
    text = re.sub(r",\s*", ", ", text)
    # Dejar la respiración de Piper en puntos y reforzar el silencio de pregunta/revelación.
    text = re.sub(r"([?!.])\s+", r"\1  ", text)
    return text


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


def _edge(text: str, out: Path, voice: str) -> None:
    """edge-tts (Microsoft neural, CapCut-like) a WAV 22050/mono PCM para el master."""
    if not config.EDGE_TTS_BIN.exists():
        raise SystemExit(f"edge-tts no está en {config.EDGE_TTS_BIN} — "
                         f"instalalo en ~/.local/bin o apuntá EDGE_TTS_BIN")
    tmp = out.with_suffix(".edge.mp3")
    subprocess.run([str(config.EDGE_TTS_BIN), "--voice", voice,
                    "--text", _marcar_prosodia(text),
                    "--write-media", str(tmp)], check=True, timeout=300)
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(tmp),
                    "-ar", "22050", "-ac", "1", "-c:a", "pcm_s16le", str(out)],
                   check=True)
    tmp.unlink(missing_ok=True)


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
    for i, text in enumerate(segs):
        out = seg_dir / f"seg-{i:03d}.wav"
        if voice_ref.startswith("piper:"):
            if not config.PIPER_MODEL_PATH.exists():
                raise SystemExit(f"No existe el modelo Piper {config.PIPER_MODEL_PATH}; instalarlo o definir PIPER_MODEL_PATH.")
            _piper(_marcar_prosodia(text), out)
        else:
            _edge(text, out, voice_ref.split(":", 1)[1])
        durations.append(_dur(out))
        print(f"  seg {i+1}/{len(segs)}: {durations[-1]:.1f}s")
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
    meta.update({
        "voice": voice_ref,
        "narration_engine": "piper" if voice_ref.startswith("piper:") else "edge-tts",
        "narration_path": str(narration.relative_to(ep.dir)),
        "narration_duration_s": round(sum(durations), 2),
        "segment_durations_s": [round(d, 2) for d in durations],
        "segment_gap_s": 0.0,
        "synthetic_content": True,  # GATE 3: siempre, porque la narración es IA
    })
    ep.save_metadata(meta)
    gates.gate_contenido_sintetico(meta)
    ep.write_json("timing-tts.txt.json", {"sintesis_s": synth_s, "audio_s": sum(durations)})
    ep.set_stage("narracion", "done")
    print(f"  narración: {narration.name} {sum(durations):.1f}s (síntesis {synth_s}s) | flag sintético ON")
