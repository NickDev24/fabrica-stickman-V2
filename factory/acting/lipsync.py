"""Lip-sync fonético con Rhubarb (correct: MIT) + fallback declarado.

Motor obligatorio de la fábrica (misión §5 animation): alineación por FONEMA,
no por amplitud. Salida: cues de visemas (A,B,C,D,E,F,G,X) con tiempos reales
sobre el WAV de Piper. Rhubarb `-r phonetic` funciona bien para español sin
diccionario propio; fallback: distribución silábica determinista (marcada
`motor: silabico` en la metadata; NUNCA se declara como alineación fonética).
"""
from __future__ import annotations

import bisect
import json
import shutil
import subprocess
from pathlib import Path

RHUBARB = Path(__file__).resolve().parents[2] / "tools" / "rhubarb" / "rhubarb"
VISemas = {"A", "B", "C", "D", "E", "F", "G", "H", "X"}


def rhubarb_disponible() -> bool:
    return RHUBARB.exists()


def _silencios(wav: Path, umbral_db: float = -40.0, min_s: float = 0.25) -> list[tuple[float, float]]:
    """Intervalos de silencio real del WAV (ffmpeg silencedetect), para medir alineación."""
    r = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(wav),
                        "-af", f"silencedetect=n={umbral_db}dB:d={min_s}", "-f", "null", "-"],
                       capture_output=True, text=True)
    out, abierto = [], None
    for line in (r.stderr or "").splitlines():
        if "silence_start:" in line:
            abierto = float(line.split("silence_start:")[1].strip().split()[0])
        elif "silence_end:" in line and abierto is not None:
            fin = float(line.split("silence_end:")[1].strip().split()[0])
            out.append((abierto, fin))
            abierto = None
    return out


def medir_alineacion(wav: Path, cues: list[dict], dur: float,
                     tolerancia_s: float = 0.18) -> dict:
    """Grado en que la boca se muece MIENTRAS suena la voz, medido sobre el WAV real.

    No mide la confianza de Rhubarb (que es una estimación acústica en inglés): mide el
    hecho observable sobre el audio del canal. `cubrimiento` es la fracción de tiempo de
    habla que tiene un cue a menos de `tolerancia_s`; `en_silencio` son cues fuera de la
    voz (boca moviéndose cuando nadie habla).
    """
    sil = _silencios(wav)
    habla, t = [], 0.0
    for a, b in sil:
        if a > t:
            habla.append((t, min(a, dur)))
        t = max(t, b)
    if t < dur:
        habla.append((t, dur))
    habla = [(a, b) for a, b in habla if b - a > 0.05]
    segundos_habla = round(sum(b - a for a, b in habla), 2)
    ts = sorted(float(c["t"]) for c in cues)
    cubiertos, en_silencio = 0.0, 0
    for a, b in habla:
        paso = 0.05
        x = a
        while x < b:
            i = bisect.bisect_left(ts, x)
            cerca = any(abs(ts[j] - x) <= tolerancia_s for j in (i - 1, i) if 0 <= j < len(ts))
            if cerca:
                cubiertos += paso
            x += paso
    for t_c in ts:
        if not any(a <= t_c <= b for a, b in habla):
            en_silencio += 1
    return {"habla_s": segundos_habla,
            "cubrimiento": round(cubiertos / max(segundos_habla, 0.1), 3),
            "cues": len(ts),
            "densidad": round(len(ts) / max(segundos_habla, 0.1), 2),
            "cues_en_silencio": en_silencio,
            "tolerancia_s": tolerancia_s}


def _dialogo_por_segmento(segs: list[str], out: Path) -> Path:
    """Formato dialogFile de Rhubarb: `actor - texto` por línea; un solo actor."""
    out.write_text("\n".join(f"narrador - {s}" for s in segs), encoding="utf-8")
    return out


def filtrar_sobre_silencio(wav: Path, cues: list[dict], dur: float,
                           margen: float = 0.06) -> tuple[list[dict], int]:
    """Descarta visemas que caen dentro de silencio detectado: boca que se mueve en vano.

    Rhubarb corre un modelo acústico en-US sobre español y marca fonemas donde no hay sonido;
    la relajación de mandíbula del renderer (0,22 s) no alcanza cuando el cue falso cae justo
    después de una palabra real. Se conservan los X (reposo explícito), que sí son correctos.
    """
    sil = _silencios(wav)
    if not sil:
        return cues, 0
    def callado(t: float) -> bool:
        return any(a - margen <= t <= b + margen for a, b in sil)
    keep = [c for c in cues if c["visema"] == "X" or not callado(c["t"])]
    return keep, len(cues) - len(keep)


def cue_wav(wav: Path, segs: list[str], out_json: Path) -> dict:
    """Roda el WAV por Rhubarb y devuelve {motor, cues:[{t, visema}...], duracion}."""
    if not rhubarb_disponible():
        return fallback_silabico(wav, segs, out_json)
    dlg = _dialogo_por_segmento(segs, out_json.parent / "dialogo.txt")
    cmd = [
        str(RHUBARB), "-q", "-f", "json", "-r", "phonetic",
        "--extendedShapes", "GHX", "--dialogFile", str(dlg),
        "--threads", "2", "-o", str(out_json), str(wav),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    if proc.returncode != 0 or not out_json.exists():
        return fallback_silabico(wav, segs, out_json, motivo=proc.stderr[-200:])
    data = json.loads(out_json.read_text(encoding="utf-8"))
    cues = [{"t": round(c["start"], 3), "visema": c["value"]}
            for c in data["mouthCues"] if c["value"] in VISemas]
    dur = data["metadata"]["duration"]
    cues, descartados = filtrar_sobre_silencio(wav, cues, dur)
    if descartados:
        # El JSON en disco es lo que lee el renderer: filtrar sólo el return dejaría
        # la boca moviéndose en silencio igual. Una verdad, un archivo.
        data["mouthCues"] = [{"start": c["t"], "end": round(c["t"] + 0.05, 3),
                              "value": c["visema"]} for c in cues]
        out_json.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return {"motor": "rhubarb", "cues": cues, "duracion_s": dur,
            "descartados_en_silencio": descartados}


def _silabas(texto: str) -> list[str]:
    """Silabeo español simple: agrupa vocales con consonantes contiguas de forma determinista."""
    text = "".join(ch for ch in texto if ch.isalpha() or ch.isspace()).lower()
    chunks, syl = [], ""
    for ch in text:
        if ch.isspace():
            if syl:
                chunks.append(syl)
            chunks.append(" ")
            syl = ""
        else:
            syl += ch
            if ch in "aeiouáéíóúü" and len(syl) > 1:
                chunks.append(syl)
                syl = "" if chunks and chunks[-1] != syl else ""
    if syl:
        chunks.append(syl)
    return [c for c in chunks if c.strip()]


_LETTER_VIS = {  # aprox: vocal abierta A, media C/E, cerrada B/D, labial F, alveolar densa B
    "a": "A", "á": "A", "e": "C", "é": "C", "i": "B", "í": "B", "o": "D", "ó": "D",
    "u": "B", "ú": "B", "ü": "B", "m": "F", "b": "F", "p": "F", "f": "F", "v": "F",
}


def fallback_silabico(wav: Path, segs: list[str], out_json: Path, motivo: str = "") -> dict:  # noqa: C901
    """Determinista con duración real via ffprobe; metadata declara `fallback`."""
    import re as _re
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                        "-of", "json", str(wav)], capture_output=True, text=True)
    dur = float(json.loads(r.stdout)["format"]["duration"])
    total_chars = sum(len(s) for s in segs)
    cues, t, sps = [], 0.0, total_chars / max(dur, 0.1)
    for seg in segs:
        for syl in _silabas(seg):
            v = next((_LETTER_VIS.get(ch) for ch in reversed(syl) if ch in _LETTER_VIS), None)
            if v is None:
                continue
            cues.append({"t": round(t, 3), "visema": v})
            t += len(syl) / max(sps, 0.5)
    body = {"motor": "silabico", "fallback_de": "rhubarb", "motivo": motivo, "cues": cues,
            "duracion_s": dur}
    out_json.write_text(json.dumps({"mouthCues": [{"start": c["t"], "end": c["t"] + 0.05,
                                                   "value": c["visema"]} for c in cues]},
                                  ensure_ascii=False, indent=1), encoding="utf-8")
    return body


if __name__ == "__main__":
    import sys
    wav = Path(sys.argv[1])
    segs = Path(sys.argv[2]).read_text(encoding="utf-8").split("\n\n")
    print(json.dumps(cue_wav(wav, segs, Path(sys.argv[3])), ensure_ascii=False)[:400])
