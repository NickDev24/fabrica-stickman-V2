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
    config.ROOT / "assets" / "imagenoteca",
    config.STATE / "imagen_cache",
]
REUTILIZAR_MIN_BYTES = 8_000   # ignorar thumbnail basura
UMBRAL_SIMILITUD = 0.94        # recicla escenas equivalentes; el tema general no alcanza
_INDICE_CACHE: list[dict] | None = None
TOKENS_GENERICOS = {
    "solid", "black", "stickman", "round", "head", "thick", "white", "outline",
    "slim", "limbs", "hand", "drawn", "documentary", "ink", "warm", "paper",
    "faint", "gray", "grid", "evidence", "centered", "scene", "key", "object",
    "action", "reveal", "motion", "clear", "readable", "shapes", "no", "generated",
    "lettering", "text", "captions", "watermark", "logo", "extra", "face", "eyes",
    "expressive", "mouth", "medium", "shot", "close", "up", "from", "the", "knees",
    "shoulders", "camera", "slow", "push", "in", "pull", "back", "pan", "lateral",
}


def _tokens(texto: str) -> list[str]:
    limpio = unicodedata.normalize("NFKD", texto.lower())
    limpio = "".join(c for c in limpio if unicodedata.category(c) != "Mn")
    return [t for t in re.findall(r"[a-záéíóúñü0-9]+", limpio)
            if len(t) > 2 and t not in TOKENS_GENERICOS]


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
    """Construye el índice de biblioteca, caché y keyframes históricos."""
    indice: list[dict] = []
    vistos: set[str] = set()

    def añadir(img: Path, prompt: str = "", escena: str = "", accion: str = "",
               plano: str = "", origen: str = "biblioteca") -> None:
        try:
            img = _path_segura(img)
            if not img.is_file() or img.stat().st_size < REUTILIZAR_MIN_BYTES:
                return
            key = str(img.resolve())
            if key in vistos:
                return
            vistos.add(key)
            indice.append({"ruta": str(img), "prompt": prompt,
                           "escenario": escena, "accion": accion,
                           "plano": plano, "origen": origen})
        except (OSError, SystemExit):
            return

    # Biblioteca oficial: los metadatos viajan junto a cada imagen.
    for root in REUTILIZAR_DIRS:
        if not root.is_dir():
            continue
        for meta_path in root.glob("*.json"):
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
                if meta.get("reutilizable") is False:
                    continue
                img = root / str(meta.get("archivo") or meta_path.with_suffix(".jpg").name)
                añadir(img, str(meta.get("prompt", "")), str(meta.get("escena", "")),
                       str(meta.get("accion", "")), str(meta.get("plano", "")),
                       str(meta.get("origen", "imagenoteca")))
            except (OSError, ValueError):
                continue
        # Caché histórica sin prompt: queda indexada para deduplicación futura, pero el
        # umbral semántico evita reciclarla hasta que se asocien metadatos válidos.
        for img in root.glob("*.*"):
            if img.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp"):
                añadir(img, origen="imagenoteca" if root.name == "imagenoteca" else "cache")

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
            # La fábrica guarda keyframes con y sin slug, jpg/png/webp.
            folder = d / "assets" / "kf"
            candidates = [folder / f"kf-{i:03d}.{ext}" for ext in ("jpg", "jpeg", "png", "webp")]
            candidates += sorted(folder.glob(f"*-{i:03d}.*")) if folder.is_dir() else []
            for img in candidates:
                if img.exists():
                    añadir(img, str(b.get("prompt", "")), str(b.get("escena", "")),
                           str(b.get("accion", "")), str(b.get("plano", "")), d.name)
    return indice


def reutilizar(prompt: str, *, escena: str = "", accion: str = "",
                plano: str = "", limit: int = 1) -> list[Path]:
    """Devuelve 0..limit imágenes ACEPTABLES; de lo contrario no fuerza imagen incongruente."""
    if not escena or not accion or not plano:
        if not prompt.strip():
            return []  # sin datos para evaluar: no fuerzo nada
    global _INDICE_CACHE
    if _INDICE_CACHE is None:
        _INDICE_CACHE = construir_indice()
    indice = _INDICE_CACHE
    candidatos: list[tuple[float, Path]] = []
    for e in indice:
        # regla dura: misma puesta en escena (escena+acción+plano) → la imagen
        # es la misma para el propósito del corte; reuso inmediato sin cálculo de texto
        misma_composicion = (escena and accion and plano and e.get("prompt") and
                             e.get("escenario") and e.get("accion") and e.get("plano") and
                             e["escenario"] == escena and
                             e["accion"] == accion and
                             e["plano"] == plano)
        p = Path(e["ruta"])
        sc = 1.0 if misma_composicion else _coseno(prompt, e["prompt"])
        # Un término compartido no basta; hacen falta dos tokens temáticos en común.
        overlap = set(_tokens(prompt)) & set(_tokens(e.get("prompt", "")))
        if not misma_composicion and len(overlap) < 2:
            continue
        if sc >= UMBRAL_SIMILITUD:
            candidatos.append((sc, p))
    candidatos.sort(reverse=True, key=lambda x: x[0])
    return [p for _sc, p in candidatos[:limit]]
