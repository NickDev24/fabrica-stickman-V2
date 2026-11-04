"""Regresiones del motor de actuación: partitura, cámara y medición de lip-sync.

Nada de esto toca LLM ni Rhubarb (son lentos y de red): se prueba la lógica determinista
que el render consume, que es donde estaban los desfases reales entre contrato y renderer.
"""
from __future__ import annotations

import json
import subprocess
import sys
import wave
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from factory.acting import director, estados, lipsync  # noqa: E402

SEG_6 = [
    "¿Sabías que un imperio entero se cayó por un mapa mal dibujado?",
    "Todo empezó con un error de navegación de apenas tres grados.",
    "Los barcos llegaron semanas tarde, con poca comida y tripulación enferma.",
    "Cuando por fin regresaron, el imperio había perdido su aliado más importante.",
    "La lección es brutal: en historia, en guerras y en negocios, el detalle gana.",
    "¿Te imaginás cuántos imperios modernos caerán por un error parecido?",
]


def test_partitura_determinista_tiene_arco_y_estados_validos():
    p = director._partitura_determinista(SEG_6)
    assert len(p) == len(SEG_6)
    assert {x["emocion"] for x in p} <= set(estados.ESTADOS)
    assert all(0.2 <= x["intensidad"] <= 1.0 for x in p)
    assert len({x["emocion"] for x in p}) >= 3, "la red de seguridad no puede ser todo neutral"
    assert p[0]["emocion"] == "curiosidad" and p[-1]["origen"] == "determinista"


def test_planos_sin_solaparse_y_cubren_el_segmento():
    seg = {"t0": 10.0, "t1": 20.0, "emocion": "suspenso", "intensidad": 0.6}
    planos = director.planos_del_segmento(seg)
    assert len(planos) == 2, "un tramo de 10 s exige corte interior"
    assert planos[0]["t0"] == 10.0 and planos[-1]["t1"] == 20.0
    for a, b in zip(planos, planos[1:]):
        assert a["t1"] == b["t0"], "el renderer toma el PRIMER match: solaparse mata el corte"
        assert a["tipo"] != b["tipo"], "el corte interior debe cambiar de plano, no de etiqueta"
    corto = {"t0": 0.0, "t1": 5.0, "emocion": "neutralidad", "intensidad": 0.4}
    assert len(director.planos_del_segmento(corto)) == 1


def test_el_guion_y_el_audio_deben_coincidir(tmp_path):
    """Si script.txt y segment_durations_s difieren, los tiempos absolutos se caen a 0."""
    ep = tmp_path / "projects" / "x"
    (ep / "artifacts").mkdir(parents=True)
    (ep / "assets" / "audio").mkdir(parents=True)
    (ep / "artifacts" / "script.txt").write_text("\n\n".join(SEG_6), encoding="utf-8")
    (ep / "artifacts" / "metadata.json").write_text(
        json.dumps({"segment_durations_s": [3.0, 3.0], "narration_path": "assets/audio/n.wav"}),
        encoding="utf-8")
    (ep / "episode.json").write_text(json.dumps({"slug": "x", "categoria": ""}), encoding="utf-8")
    with pytest.raises(SystemExit, match="guion y audio no coinciden"):
        director.construir_timeline(ep)


@pytest.fixture(scope="module")
def wav_con_silencio(tmp_path_factory):
    """2 s de tono (habla) + 1 s de silencio + 1 s de tono, para medir alineación de verdad."""
    from array import array
    d = tmp_path_factory.mktemp("wav")
    p = d / "voz.wav"
    sr = 16000

    def tramo(n, amplitude=6000):
        muestras = [amplitude if int(880 * i / sr) % 2 == 0 else -amplitude
                    for i in range(n * sr)]
        return array("h", muestras).tobytes()

    with wave.open(str(p), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr)
        w.writeframes(tramo(2) + tramo(1, 0) + tramo(1))
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                        "-of", "default=nw=1:nk=1", str(p)], capture_output=True, text=True)
    return p, float(r.stdout.strip())


def test_medir_alineacion_detecta_boca_fuera_de_voz(wav_con_silencio):
    wav, dur = wav_con_silencio
    ts = [round(0.1 + i * 0.2, 2) for i in range(10)] + [round(3.1 + i * 0.2, 2) for i in range(5)]
    cues = [{"t": t, "visema": "A"} for t in ts]
    cues.append({"t": 2.6, "visema": "B"})          # boca moviéndose en el silencio
    m = lipsync.medir_alineacion(wav, cues, dur)
    assert m["habla_s"] < dur, "el silencio no es tiempo de habla"
    assert m["cubrimiento"] > 0.9, f"con cues sobre toda la voz el cubrimiento debe ser alto: {m}"
    assert m["cues_en_silencio"] == 1, "un visema durante el silencio es boca moviéndose en vano"


def test_medir_alineacion_castiga_boca_quieta(wav_con_silencio):
    wav, dur = wav_con_silencio
    m = lipsync.medir_alineacion(wav, [{"t": 0.5, "visema": "A"}], dur)
    assert m["cubrimiento"] < 0.3
