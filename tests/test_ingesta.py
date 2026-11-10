"""Ingesta de imágenes externas y reciclado semántico (sin red, sin cuota).

Cubre el pedido del dueño 2026-11-10: poder agregar imágenes generadas por otra IA a la
imagenoteca y que la fábrica las reutilice por coincidencia semántica con la narración.
La imagenoteca real tiene ~1600 archivos: los tests usan una tmp aislada.
"""
from __future__ import annotations

import json
import random
import sys
from pathlib import Path

import pytest
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pipeline import config, imagen               # noqa: E402
from pipeline.stages import reciclaje             # noqa: E402


def _png(path: Path, size: int = 128) -> Path:
    """PNG con ruido: un color plano quedaría por debajo del mínimo de 8 KB."""
    path.parent.mkdir(parents=True, exist_ok=True)
    rng = random.Random(7)
    img = Image.new("RGB", (size, size))
    img.putdata([(rng.randint(0, 255), rng.randint(0, 255), rng.randint(0, 255))
                 for _ in range(size * size)])
    img.save(path)
    return path


@pytest.fixture()
def biblioteca(tmp_path, monkeypatch):
    lib = tmp_path / "imagenoteca"
    lib.mkdir()
    proyectos = tmp_path / "projects"
    proyectos.mkdir()
    monkeypatch.setattr(imagen, "IMAGENOTECA", lib)
    monkeypatch.setattr(reciclaje, "REUTILIZAR_DIRS", [lib])
    # _path_segura limita la biblioteca al root del repo; el tmp está en /tmp.
    monkeypatch.setattr(reciclaje, "_path_segura", lambda p: p)
    # construir_indice también lee los keyframes de projects/: se aísla para que el
    # test no dependa de los 81 episodios reales (ni tarde 2 min escaneándolos).
    monkeypatch.setattr(config, "PROJECTS", proyectos)
    reciclaje.invalidar_cache()
    yield lib
    reciclaje.invalidar_cache()


def test_ingerir_archiva_con_prompt_y_el_reciclaje_la_encuentra(tmp_path, biblioteca):
    ingesta = tmp_path / "ingesta"
    _png(ingesta / "escena.png")
    (ingesta / "escena.json").write_text(json.dumps({
        "prompt": "solid black stickman silhouette museum gallery empty gilded frames",
        "escena": "galeria", "accion": "senala", "plano": "medio",
        "personaje": "4F", "tags": ["museo"],
    }), encoding="utf-8")

    salida = imagen.ingerir(ingesta)
    assert salida["archivadas"] == 1
    assert salida["sin_prompt"] == 0
    assert len(list(biblioteca.glob("*.png"))) == 1

    meta = json.loads(next(biblioteca.glob("*.json")).read_text(encoding="utf-8"))
    assert meta["prompt"].startswith("solid black stickman")
    assert meta["personaje"] == "4F"
    assert meta["origen"] == "externa"

    reciclaje.invalidar_cache()
    hallada = reciclaje.reutilizar(
        "solid black stickman silhouette museum gallery empty gilded frames",
        escena="galeria", accion="senala", plano="medio")
    assert hallada, "la imagen ingresada no se encontró por coincidencia semántica"


def test_ingerir_con_txt_de_prompt(tmp_path, biblioteca):
    ingesta = tmp_path / "ingesta"
    _png(ingesta / "escena.png")
    (ingesta / "escena.txt").write_text(
        "stickman detective office folder lamp", encoding="utf-8")
    salida = imagen.ingerir(ingesta)
    assert salida["archivadas"] == 1
    assert salida["sin_prompt"] == 0
    meta = json.loads(next(biblioteca.glob("*.json")).read_text(encoding="utf-8"))
    assert "detective office" in meta["prompt"]


def test_sin_prompt_se_archiva_pero_no_se_recicla(tmp_path, biblioteca):
    ingesta = tmp_path / "ingesta"
    _png(ingesta / "sin-datos.png")
    salida = imagen.ingerir(ingesta)
    assert salida["archivadas"] == 1
    assert salida["sin_prompt"] == 1
    reciclaje.invalidar_cache()
    assert reciclaje.reutilizar("anything", escena="x", accion="y", plano="z") == []


def test_imagen_chica_o_corrupta_se_reporta(tmp_path, biblioteca):
    ingesta = tmp_path / "ingesta"
    ingesta.mkdir(parents=True)
    (ingesta / "chica.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 100)
    (ingesta / "rota.png").write_bytes(b"no es una imagen")
    salida = imagen.ingerir(ingesta)
    assert salida["archivadas"] == 0
    assert len(salida["errores"]) == 2


def test_personaje_distinto_no_se_recicla(tmp_path, biblioteca):
    ingesta = tmp_path / "ingesta"
    _png(ingesta / "otro.png")
    (ingesta / "otro.json").write_text(json.dumps({
        "prompt": "solid black stickman silhouette museum gallery empty gilded frames",
        "escena": "galeria", "accion": "senala", "plano": "medio",
        "personaje": "OTRO",
    }), encoding="utf-8")
    imagen.ingerir(ingesta)
    reciclaje.invalidar_cache()
    assert reciclaje.reutilizar(
        "solid black stickman silhouette museum gallery empty gilded frames",
        escena="galeria", accion="senala", plano="medio") == []


def test_etiquetas_suman_a_la_busqueda(tmp_path, biblioteca):
    ingesta = tmp_path / "ingesta"
    _png(ingesta / "etiquetada.png")
    (ingesta / "etiquetada.json").write_text(json.dumps({
        "prompt": "stickman standing beside a wall",
        "escena": "galeria", "accion": "senala", "plano": "medio",
        "personaje": "4F", "tags": ["marcos vacíos", "museo"],
    }), encoding="utf-8")
    imagen.ingerir(ingesta)
    reciclaje.invalidar_cache()
    # El prompt del beat no dice "museo", pero el tag sí: alcanza para matchear.
    hallada = reciclaje.reutilizar(
        "stickman wall museum empty frames", escena="galeria",
        accion="senala", plano="medio")
    assert hallada, "las etiquetas no entraron al texto buscable"
