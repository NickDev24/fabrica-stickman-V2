"""Portada scroll-stop: el texto es la PREGUNTA gancho, ≤6 palabras, 2 líneas."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pipeline.stages.captacion import _texto_portada_de  # noqa: E402


def test_usa_la_pregunta_del_guion_recortada_a_6_palabras():
    script = ("# Título\n\n"
              "¿Por qué no recordás nada de tu infancia temprana ni un segundo?\n\n"
              "El resto del guion no se usa para el texto de portada.")
    txt = _texto_portada_de(script, "Algún otro título")
    assert len(txt.splitlines()[0].split()) <= 6
    assert txt.splitlines()[0].startswith("Por qué")


def test_si_el_guion_no_abre_con_pregunta_cae_al_titulo():
    script = "# T\n\nLa SEC tuvo las pruebas y no miró.\n\nresto"
    txt = _texto_portada_de(script, "¿Quién apagó su vida por dentro?")
    primera_linea = txt.splitlines()[0]
    assert "Quién apagó" in primera_linea
    assert "SEC" not in txt


def test_sin_pregunta_ni_titulo_devuelve_marca():
    assert _texto_portada_de("", "") == "Pulso Curioso"


def _dimension(path: Path) -> tuple[int, int]:
    import json
    import subprocess
    v = json.loads(subprocess.run(["ffprobe", "-v", "error", "-show_streams", "-of", "json",
                                   str(path)], capture_output=True, text=True).stdout)
    s = next(x for x in v["streams"] if x["codec_type"] == "video")
    return int(s["width"]), int(s["height"])


def test_la_miniatura_horizontal_de_youtube_existe(tmp_path):
    """El GAP de v6: la fábrica no producía NINGÚN 1280x720 y el video largo salía sin miniatura."""
    import subprocess

    from pipeline.stages.captacion import _dibujar_portada
    base = tmp_path / "kf.png"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi",
                    "-i", "testsrc=size=1024x1024:rate=1:duration=1",
                    "-frames:v", "1", str(base)], check=True)
    txt = tmp_path / "portada.txt"
    txt.write_text("¿Quién pagó\nel error?")
    for nombre, w, h in (("portada.jpg", 1080, 1920), ("portada-yt.jpg", 1280, 720),
                         ("portada-fb.jpg", 1080, 1350)):
        out = _dibujar_portada(base, txt, tmp_path / nombre, w, h)
        assert _dimension(out) == (w, h), nombre
        assert out.stat().st_size < 2 * 1024 * 1024, f"{nombre} pasa el techo de 2 MB de YouTube"


def test_youtube_pide_16_9_y_el_codigo_lo_emite():
    from pipeline.stages import captacion
    src = Path(captacion.__file__).read_text(encoding="utf-8")
    assert "portada-yt.jpg" in src and "1280, 720" in src
