"""Métricas del formato cómic — APARTADAS de las del video (regla del diseño).

Siempre append a state/metricas_comics.jsonl: por episodio se registra qué se
produjo, qué costó (llamadas API declaradas por imagen.generar vía
procedencia_imagen) y el paso de QC. Nada toca el diario de los videos.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from .. import config
from ..episode import Episode

ARCHIVO = "metricas_comics.jsonl"


def registrar(ep: Episode, datos: dict, artefactos: dict, qc_ok: bool,
              extra: dict | None = None) -> dict:
    fila = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "slug": ep.slug,
        "schema": datos.get("schema"),
        "vinetas": len(datos.get("paneles", [])),
        "paginas": len(datos.get("grillas", [])),
        "via": (datos.get("procedencia") or {}).get("via", ""),
        "pagina": str(artefactos.get("pagina", "")).split("/")[-1],
        "chapter_vertical": Path(str(artefactos.get("chapter_vertical", ""))).name
        if artefactos.get("chapter_vertical") else "",
        "carrusel": len(artefactos.get("carrusel", []) or []),
        "qc_aprobado": qc_ok,
        "extra": extra or {},
    }
    ruta = config.STATE / ARCHIVO
    ruta.parent.mkdir(parents=True, exist_ok=True)
    with ruta.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(fila, ensure_ascii=False) + "\n")
    return fila
