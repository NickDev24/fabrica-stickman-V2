"""Cutout layer: imágenes reales recortadas estilo papel en el master.

Reglas:
  - Cada recorte tiene licencia rastreable: autor + URL + verdict CHECK DE FUENTE.
  - La fábrica SÓLO aplica recortes aprobados: collage_layer.json en el episode → approve=true
    / artifacts de aprobación explícita del dueñof.
  - Si no hay approve, la fábrica NO llama a esta función (skip, cero coste y cero carga).
  - El reuso de recortes existentes preserva costos y marcas de origen (idempotente por hash).
"""
from __future__ import annotations

import hashlib
import json
import random
import shutil
from pathlib import Path

import requests
from PIL import Image, ImageDraw, ImageFilter, ImageOps

from . import config


def huella(url: str) -> str:
    return hashlib.sha256(url.encode("utf-8")).hexdigest()[:40]


def _recortador(img: Image.Image, crop_pct: float = 0.55, lado: str = "arriba"):
    """Recorta la parte superior (tamaño de retrato) y aplica escalado por LANCZOS."""
    w, h = img.size
    row_top = 0
    if lado == "arriba":
        row_top = 0
    elif lado == "centro":
        row_top = int(h * (1 - crop_pct) / 2)
    else:  # abajo
        row_top = int(h * (1 - crop_pct))
    crop = img.crop((0, row_top, w, row_top + int(h * crop_pct)))
    return crop


def _mascara_papel(size: tuple[int, int], seed: int = 42) -> Image.Image:
    """Máscara alpha: polígono irregular alrededor del rectángulo → textura papel rasgado."""
    w, h = size
    rng = random.Random(seed)
    img = Image.new("L", (w, h), 0)
    d = ImageDraw.Draw(img)
    # 5 lados con jitter; esquinas desfasadas para simular rotura
    pts = []
    n = 24
    # 1) borde superior: izquierda → derecha
    for i in range(n + 1):
        x = int(w * i / n)
        y = int(h * 0.018 + rng.randint(-h // 25, h // 25))
        pts.append((x, y))
    # 2) borde derecho: arriba → abajo
    for i in range(n + 1):
        y = int(h * i / n)
        x = int(w * (1 - 0.018) + rng.randint(-w // 25, w // 25))
        pts.append((x, y))
    # 3) borde inferior: derecha → izquierda
    for i in range(n + 1):
        x = int(w * (1 - i / n))
        y = int(h * (1 - 0.018) + rng.randint(-h // 25, h // 25))
        pts.append((x, y))
    # 4) borde izquierdo: abajo → arriba
    for i in range(n + 1):
        y = int(h * (1 - i / n))
        x = int(w * 0.015 + rng.randint(-w // 25, w // 25))
        pts.append((x, y))
    d.polygon(pts, fill=255)
    return img.filter(ImageFilter.GaussianBlur(1.4))


def _sombra(alfa: Image.Image, offset: tuple[int, int] = (6, 8), blur: int = 10,
            alpha_intenso=110) -> Image.Image:
    """Crea una sombra sutil desplazada sobre la capa final."""
    som = Image.new("L", alfa.size, 0)
    som.paste(alfa, offset)
    return som.filter(ImageFilter.GaussianBlur(blur))


def procesar_recorte(source: Path, destino: Path, *, lado: str = "arriba",
                     crop_pct: float = 0.75, rota: float = -4.0) -> Path:
    """Aplica máscara de papel rasgado + rotación leve + recorte + sombra."""
    src_img = Image.open(source).convert("RGB")
    crop = _recortador(src_img, crop_pct=crop_pct, lado=lado)
    # Barres y filtro "fotocopia" (grano leve, contraste, desbalance de color)
    crop = ImageOps.autocontrast(crop, cutoff=2)
    crop = ImageOps.grayscale(crop)
    alfa = _mascara_papel(crop.size, seed=hash(str(source)) & 0xFFFF)
    rec = Image.new("RGBA", crop.size, (0, 0, 0, 0))
    rec.paste(crop, mask=alfa)
    sombra = Image.new("RGBA", crop.size, (0, 0, 0, 0))
    sombra.putalpha(_sombra(alfa, offset=(5, 6), blur=8))
    rec = Image.alpha_composite(sombra, rec)
    # rot. leve: pizarra con borde rasgado
    rot = rec.rotate(rota, expand=True, resample=Image.BICUBIC,
                     fillcolor=(0, 0, 0, 0))
    destino.parent.mkdir(parents=True, exist_ok=True)
    rot.save(destino, quality=95)
    return destino


def descargar_y_procesar(source_url: str, destino_dir: Path, **procesa_kw) -> Path:
    """Descarga (con huellas → cache reuse) y procesa en un solo paso."""
    h = huella(source_url)
    raw = destino_dir / f"{h}.src"
    out = destino_dir / f"{h}.paper.png"
    if out.exists():
        return out
    if not raw.exists():
        resp = requests.get(source_url, headers={"User-Agent": "PulsoCurioso/1.0"},
                            timeout=60)
        resp.raise_for_status()
        raw.write_bytes(resp.content)
    return procesar_recorte(raw, out, **procesa_kw)


def aplicar_cutouts(ep, master: Path, recortes: list[dict], salida: Path | None = None) -> Path:
    """Re-compone el master agregando los recortes aprobados con overlay + fades.

    Cada recorte: {"png": path, "t_start": 53.4, "t_end": 57.5,
                   "x": 480, "y": 120, "w": 400}
    El audio se copia tal cual (no se re-normaliza).
    """
    if salida is None:
        salida = ep.dir / "renders" / f"{ep.slug}-collage.mp4"
    salida.parent.mkdir(parents=True, exist_ok=True)
    vf_parts = []
    inputs = ["-i", str(master)]
    ind = 1
    for r in recortes:
        inputs += ["-loop", "1", "-i", str(r["png"])]
        w = r.get("w", 400)
        vf_parts.append(
            f"[{ind}:v]scale={w}:-1,format=rgba,"
            f"trim=duration={r['t_end'] + 0.5:.3f},"
            f"fade=t=in:st={r['t_start']}:d=0.35:alpha=1,"
            f"fade=t=out:st={r['t_end'] - 0.35:.3f}:d=0.35:alpha=1[c{ind}]")
        ind += 1
    # cadena de overlays en cascada
    base = "[0:v]"
    for i, r in enumerate(recortes):
        out_label = f"[v{i}]" if i < len(recortes) - 1 else "[vout]"
        base = (f"{base}[c{i + 1}]overlay={r.get('x', 480)}:{r.get('y', 120)}:"
                f"enable='between(t,{r['t_start']},{r['t_end']})'{out_label}")
    filt = ";".join(vf_parts + [base])
    cmd = (["ffmpeg", "-y", "-v", "error"] + inputs +
           ["-filter_complex", filt, "-map", "[vout]", "-map", "0:a",
            "-c:v", "libx264", "-preset", str(config.FFMPEG_PRESET),
            "-crf", str(config.FFMPEG_CRF), "-pix_fmt", "yuv420p", "-r",
            str(getattr(config, "KF_FPS", None) or 30),
            "-c:a", "copy", "-movflags", "+faststart", str(salida)])
    import subprocess
    subprocess.run(cmd, check=True, capture_output=True, text=True)
    # artefacto declarativo: _video_final elige este render sobre el master sin overlay
    art = ep.dir / "artifacts" / "render_collage.json"
    art.parent.mkdir(parents=True, exist_ok=True)
    art.write_text(json.dumps({
        "archivo": salida.name, "master": master.name,
        "recortes": [{"png": str(r["png"]), "t_start": r["t_start"],
                      "t_end": r["t_end"], "x": r.get("x"), "y": r.get("y"),
                      "w": r.get("w")} for r in recortes],
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    return salida


def verificar_licencia(recs: list[dict], sources: list[dict]) -> list[str]:
    """Chequea que cada recorte aprobado tenga fuente rastreable a su licencia.

    Retorna lista de problemas (vacío = todo OK).
    """
    problemas = []
    lookup = {}
    for s in sources:
        if s.get("url"):
            lookup[s["url"]] = s
    for r in recs:
        srcs = r.get("sources") or []
        if not srcs:
            problemas.append(f"recorte '{r.get('tag')}' sin fuentes")
            continue
        for s in srcs:
            if s.get("url") not in lookup:
                problemas.append(f"recorte '{r.get('tag')}': url no encontrada en sources.json")
    return problemas
