"""Anti-repetición: las sondas de verificación no pueden bloquear su propia idea.

Bug medido 2026-11-06/07: `ideas.verificar()` crea `projects/idea-<tema>/` con el título
de la idea; `huellas.intentadas()` contaba esas carpetas como episodios ya producidos y
`ya_contada()` devolvía 1.0, así que la fábrica verificaba una idea y la descartaba acto
seguido. El resultado fue tres días encendida sin producir ni publicar nada.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pipeline import huellas  # noqa: E402
from pipeline.episode import STAGES  # noqa: E402


def _estado(slug: str, title: str, **extra) -> dict:
    return {"slug": slug, "title": title, "categoria": "",
            "stage_status": {s: "pending" for s in STAGES}, **extra}


def _proyecto(projects: Path, datos: dict) -> None:
    d = projects / datos["slug"]
    d.mkdir(parents=True)
    (d / "episode.json").write_text(json.dumps(datos), encoding="utf-8")


def _preparar(tmp_path: Path, monkeypatch) -> Path:
    projects = tmp_path / "projects"
    projects.mkdir()
    monkeypatch.setattr(huellas, "PUBLISHED", tmp_path / "published.jsonl")
    monkeypatch.setattr(huellas.config, "PROJECTS", projects)
    return projects


TITULO = "Clayface: El caso del villano que nunca se materializó"


def test_una_sonda_verificada_no_bloquea_su_idea(tmp_path, monkeypatch):
    projects = _preparar(tmp_path, monkeypatch)
    _proyecto(projects, _estado("idea-clayface-film", TITULO,
                                verificacion_probe=True,
                                verificacion_estado="verificada"))
    contada, _, similitud = huellas.ya_contada(TITULO)
    assert contada is False, f"la idea se bloqueó a sí misma (similitud {similitud})"


def test_una_sonda_fallida_si_conserva_el_anti_reintento(tmp_path, monkeypatch):
    projects = _preparar(tmp_path, monkeypatch)
    _proyecto(projects, _estado("idea-clayface-film", TITULO,
                                verificacion_probe=True,
                                verificacion_estado="descartada_sin_fuentes"))
    contada, slug, _ = huellas.ya_contada(TITULO)
    assert contada is True and slug == "idea-clayface-film"


def test_sondas_viejas_sin_marca_tampoco_bloquean(tmp_path, monkeypatch):
    projects = _preparar(tmp_path, monkeypatch)
    _proyecto(projects, _estado("idea-clayface-film", TITULO))
    assert huellas.ya_contada(TITULO)[0] is False


def test_un_episodio_producido_sigue_bloqueando_la_repeticion(tmp_path, monkeypatch):
    projects = _preparar(tmp_path, monkeypatch)
    datos = _estado("clayface-film", TITULO)
    datos["stage_status"]["guion"] = "done"
    _proyecto(projects, datos)
    contada, slug, _ = huellas.ya_contada(TITULO)
    assert contada is True and slug == "clayface-film"
