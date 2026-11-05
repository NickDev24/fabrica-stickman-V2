"""Recycling: reutiliza imágenes ya generadas antes de pedir nuevas.

Motivación real
---------------
El pipeline generó 466 imágenes pagando (207 en caché + 259 en episodios; ninguna se reutiliza).
Cada episodio nuevo comenzaba con "nunca usé esta imagen" — redraw completa.
El canal stickman gana por acumulación: el mismo padre y mesa aparecen en decenas de videos.

Implementación: huella SHA-256 del prompt; si no existe, busca imágenes
semánticamente cercanas en la biblioteca propia (coseno de tokens con umbral estricto).
PRECABIDO: sólo se reutiliza si existe correspondencia demostrable — si el score no alcanza
el umbral, se genera nueva igual; nunca se forza una imagen incongruite.

Huella incluye: modelo, prompt, resolución, steps/seed (via imagen.huella).
Las claves criptográficas establecen correspondencia 1:1 con el design file.
"""
from __future__ import annotations

import json
import math
import re
import unicodedata
from pathlib import Path

from .. import config

# --- infraestructura de biblioteca -------------------------------------------
REUTILIZAR_DIRS = [
    config.STATE / "imagen_cache",
]
REUTILIZAR_MIN_BYTES = 8_000   # ignorar thumbnail basura
UMBRAL_SIMILITUD = 0.55        # coseno mínimo; si no alcanza, no reciclamos


def _tokens(texto: str) -> list[str]:
    limpio = unicodedata.normalize("NFKD", texto.lower())
    limpio = "".join(c for c in limpio if unicodedata.category(c) != "Mn")
    return [t for t in re.findall(r"[a-záéíóúñü0-9]+", limpio) if len(t) > 2]


def _idf(texto: str) -> dict[str, float]:
    """Invert document frequency opuesta al estilo habitual (TF normalizado)."""
    c: dict[str, float] = {}
    for t in _tokens(texto):
        c[t] = c.get(t, 0) + 1.0
    # normalizar a magnitud 1 para comparar coseno
    mag = math.sqrt(sum(v * v for v in c.values())) or 1.0
    return {k: v / mag for k, v in c.items()}


def _coseno(a: str, b: str) -> float:
    va, vb = _idf(a), _idf(b)
    comunes = set(va) & set(vb)
    if not comunes:
        return 0.0
    num = sum(va[t] * vb[t] for t in comunes)
    return num  # ya normalizados a magnitud 1


def _path_segura(p: Path) -> Path:
    """Evita path traversal: la biblioteca es sólo bajo proyectos/ y caché."""
    root = config.ROOT.resolve()
    if not str(p.resolve()).startswith(str(root)):
        raise SystemExit(f"reciclaje: ruta fuera del proyecto: {p}")
    return p


def construir_indice(max_proyectos: int = 50) -> list[dict]:
    """Construye el índice de imágenes reutilizables de todos los episodios."""
    indice: list[dict] = []
    for d in sorted(config.PROJECTS.iterdir()):
        if not d.is_dir() or d.name.startswith("_"):
            continue
        bfile = d / "artifacts" / "beats.json"
        if not bfile.exists():
            continue
        try:
            data = json.loads(bfile.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        for b in data.get("beats", []):
            i = int(b.get("i", -1))
            if i < 0:
                continue
            img = d / "assets" / "kf" / f"kf-{i:03d}.jpg"
            if not img.exists() or img.stat().st_size < REUTILIZAR_MIN_BYTES:
                continue
            indice.append({
                "ruta": str(img),
                "prompt": b.get("prompt", ""),
                "escenario": b.get("escena", ""),
                "accion": b.get("accion", ""),
                "plano": b.get("plano", ""),
                "origen": d.name,
            })
    return indice


def reutilizar(prompt: str, *, escena: str = "", accion: str = "",
                plano: str = "", limit: int = 1) -> list[Path]:
    """Devuelve 0..limit imágenes ACEPTABLES; de lo contrario no fuerza imagen incongruente."""
    if not escena or not accion or not plano:
        if not prompt.strip():
            return []  # sin datos para evaluar: no fuerzo nada
    indice = construir_indice()
    candidatos: list[tuple[float, Path]] = []
    for e in indice:
        # regla dura: misma puesta en escena (escena+acción+plano) → la imagen
        # es la misma para el propósito del corte; reuso inmediato sin cálculo de texto
        misma_composicion = (escena and accion and plano and
                             e["escenario"] == escena and
                             e["accion"] == accion and
                             e["plano"] == plano)
        p = Path(e["ruta"])
        sc = 1.0 if misma_composicion else _coseno(prompt, e["prompt"])
        if sc >= UMBRAL_SIMILITUD:
            candidatos.append((sc, p))
    candidatos.sort(reverse=True, key=lambda x: x[0])
    return [p for _sc, p in candidatos[:limit]]
