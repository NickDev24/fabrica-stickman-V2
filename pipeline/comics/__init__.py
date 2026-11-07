"""Fábrica de cómics — extensión aislada del pipeline de video (FABRICA-DE-COMICS.md).

Regla madre del diseño: la producción de video sigue su ruta intacta. Este paquete:
  - vive en projects/<slug>/comics/ (NUNCA en renders/ ni las rutas de los publicadores),
  - está APAGADO por defecto: sólo corre con COMICS_ENABLED=1 en .env,
  - comparte con el video la investigación y el guion verificado, nothing más.
"""
from __future__ import annotations

import os
from pathlib import Path

from .. import config


def habilitado() -> bool:
    config.load_env()
    return os.environ.get("COMICS_ENABLED", "").strip().lower() in ("1", "true", "yes", "on")


def comics_dir(slug: str) -> Path:
    return config.PROJECTS / slug / "comics"
