"""Estructura de un episodio y su estado por etapa (resume-friendly)."""
from __future__ import annotations

import json
import re
from pathlib import Path

from . import config

STAGES = ["research", "factcheck", "guion", "visuales", "narracion", "keyframes",
          "avatar", "montaje", "corto", "derivados", "publicacion"]

SUBDIRS = ["research", "artifacts", "assets/audio", "assets/img", "assets/video",
           "renders", "derivados", "publicacion"]


class Episode:
    def __init__(self, slug: str, categoria: str = ""):
        self.slug = slug
        self.categoria = categoria
        self.dir = config.PROJECTS / slug
        if not self.dir.exists():
            raise FileNotFoundError(f"no existe el episodio {slug!r} en projects/")

    @classmethod
    def create(cls, slug: str, title: str, categoria: str = "") -> "Episode":
        slug = re.sub(r"[^a-z0-9-]", "-", slug.lower().strip())
        d = config.PROJECTS / slug
        for sub in SUBDIRS:
            (d / sub).mkdir(parents=True, exist_ok=True)
        ep = cls(slug, categoria=categoria)
        ep.write_state({"slug": slug, "title": title, "categoria": categoria,
                        "stage_status": {s: "pending" for s in STAGES}})
        (d / "research" / "urls.txt").write_text(
            "# Pegá aquí una URL de fuente por línea (el gate 1 exige >=2 por afirmación).\n",
            encoding="utf-8")
        return ep

    # ---- estado
    @property
    def state_path(self) -> Path:
        return self.dir / "episode.json"

    def read_state(self) -> dict:
        if not self.state_path.exists():  # episodios legacy (pre-pipeline)
            return {"slug": self.slug, "title": self.slug, "categoria": "",
                    "stage_status": {s: "pending" for s in STAGES}}
        return json.loads(self.state_path.read_text(encoding="utf-8"))

    def write_state(self, data: dict) -> None:
        self.state_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    def set_stage(self, stage: str, status: str, **extra) -> None:
        st = self.read_state()
        st["stage_status"].setdefault(stage, "pending")
        st["stage_status"][stage] = status
        st.update(extra)
        self.write_state(st)

    # ---- artefactos
    @property
    def artifacts(self) -> Path:
        return self.dir / "artifacts"

    def read_text(self, name: str) -> str:
        p = self.artifacts / name
        if not p.exists():
            raise FileNotFoundError(f"falta {name} en {self.dir}")
        return p.read_text(encoding="utf-8")

    def write_text(self, name: str, content: str) -> Path:
        p = self.artifacts / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return p

    def read_json(self, name: str):
        return json.loads(self.read_text(name))

    def write_json(self, name: str, data) -> Path:
        return self.write_text(name, json.dumps(data, indent=2, ensure_ascii=False))

    def metadata(self) -> dict:
        meta_path = self.artifacts / "metadata.json"
        if meta_path.exists():
            return json.loads(meta_path.read_text(encoding="utf-8"))
        return {"slug": self.slug, "title": self.read_state()["title"]}

    def save_metadata(self, meta: dict) -> None:
        self.write_json("metadata.json", meta)
