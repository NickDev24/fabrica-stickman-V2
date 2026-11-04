"""Regresión del bug de pulso-001-main.mp4: subtítulos quemados con ",0,0,0,," delante.

Causa raíz: el header [Events] Format: declaraba 5 campos (Layer, Start, End, Style, Text)
mientras cada Dialogue escribía 10. libass asigna "Text" al resto de la línea, así que el
prefijo de campos sobraba y terminaba pintado en pantalla.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from pipeline.stages import montaje, short

# El archivo tal como lo generaba la versión bugueada (Format de 5 campos).
ROTO = """[Script Info]
ScriptType: v4.00+

[V4+ Styles]
Format: Name, Fontname, Fontsize
Style: Default, DejaVu Sans, 46

[Events]
Format: Layer, Start, End, Style, Text
Dialogue: 0,0:00:00.00,0:00:04.60,Default,,0,0,0,,¿Sabías que un imperio entero se
"""


def test_validador_detecta_el_formato_viejo():
    with pytest.raises(ValueError):
        montaje.validar_ass(ROTO, "seg-000.ass histórico")


def test_el_writer_actual_es_valido(tmp_path):
    p = montaje._ass("¿Sabías que un imperio entero se cayó por un mapa mal dibujado?", 9.2,
                     tmp_path / "ok.ass")
    texto = p.read_text(encoding="utf-8")
    montaje.validar_ass(texto, str(p))
    lineas = [l for l in texto.splitlines() if l.startswith("Dialogue:")]
    for l in lineas:
        campos = l[len("Dialogue:"):].split(",")
        assert campos[9].startswith("¿Sabías") or campos[9].startswith("cayó"), campos[9]


def test_libass_no_quema_los_campos(tmp_path):
    """Prueba de píxel: lo único que vale es lo que libass dibuja realmente."""
    ffmpeg = subprocess.run(["ffmpeg", "-version"], capture_output=True)
    if ffmpeg.returncode != 0:
        pytest.skip("ffmpeg no disponible")
    bueno = tmp_path / "bueno.ass"
    montaje._ass("¿Sabías que un imperio entero se cayó?", 4.6, bueno)
    malo = tmp_path / "malo.ass"
    malo.write_text(ROTO, encoding="utf-8")

    def frame(ass: Path) -> bytes:
        png = tmp_path / f"chk-{ass.stem}.png"
        subprocess.run(
            ["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "color=c=gray:s=640x200:r=10",
             "-t", "0.3", "-vf", f"subtitles={ass}", "-frames:v", "1", str(png)], check=True)
        return png.read_bytes()

    assert frame(bueno) != frame(malo), "libass renderiza igual el ASS roto y el bueno: test inútil"
    # El bueno debe producir menos píxeles (el prefijo ",0,0,0,," añade glifos)
    assert len(frame(bueno)) < len(frame(malo))


def test_short_tambien_valida(tmp_path, monkeypatch):
    from pipeline import config
    monkeypatch.setattr(config, "SHORT_W", 1080)
    monkeypatch.setattr(config, "SHORT_H", 1920)
    monkeypatch.setattr(config, "SHORT_SUB", 60)
    shots = [{"texto": "una prueba de subtulos con muchas palabras para dos chunks", "dur": 2.0}]
    p = short._captions(shots, 1920, 300, tmp_path / "short.ass")
    montaje.validar_ass(p.read_text(encoding="utf-8"), str(p))
