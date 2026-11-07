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


def _recortar_margenes(img: Image.Image, umbral: int = 6) -> Image.Image:
    """Trims bordes uniformes (escaneos con marco blanco/negro) ANTES de encuadrar.

    "Excesivamente prolijo": un recorte que viene con el marco del escaneo alrededor
    parece sticker con placa invertida. Se recorta fila por fila/columna mientras la
    desviación estándar de la franja sea casi cero (fondo plano).
    """
    gris = img.convert("L")
    w, h = gris.size
    if w < 40 or h < 40:
        return img
    import statistics

    def franja_std(datos: list[int]) -> float:
        return statistics.pstdev(datos) if len(datos) > 1 else 0.0

    def fila(i: int) -> list[int]:
        return list(gris.crop((0, i, w, i + 1)).getdata())

    def col(j: int) -> list[int]:
        return list(gris.crop((j, 0, j + 1, h)).getdata())

    top, bottom, left, right = 0, h, 0, w
    while top < bottom - 2 and franja_std(fila(top)) < umbral:
        top += 1
    while bottom > top + 2 and franja_std(fila(bottom - 1)) < umbral:
        bottom -= 1
    while left < right - 2 and franja_std(col(left)) < umbral:
        left += 1
    while right > left + 2 and franja_std(col(right - 1)) < umbral:
        right -= 1
    if (top, bottom, left, right) == (0, h, 0, w):
        return img  # nada uniforme sobrante: no se toca
    return img.crop((left, top, right, bottom))


def _recortador(img: Image.Image, crop_pct: float = 0.75, lado: str = "arriba",
                tema: str = "persona") -> Image.Image:
    """Encuadre inicial por TEMA (el recorte debe TENER SENTIDO dentro de la escena).

    - persona: retrato desde arriba (cabeza/hombros), ventana horizontal centrada.
    - documento: rectángulo completo (proporciones del original), foco al centro.
    - lugar: paisaje/edificio, 85 % del alto, centro (aire de escena).
    - objeto: cuadrado del centro (estatuillas, artefactos…).
    """
    if tema == "objeto":
        w, h = img.size
        lado_c = min(w, h)
        return img.crop(((w - lado_c) // 2, (h - lado_c) // 2,
                         (w + lado_c) // 2, (h + lado_c) // 2))
    if tema in ("documento", "lugar"):
        pct = 0.85 if tema == "lugar" else 1.0
        w, h = img.size
        nh = int(h * pct)
        y0 = (h - nh) // 2
        return img.crop((0, y0, w, y0 + nh))
    return _retrato_arriba(img, crop_pct=crop_pct)


def _retrato_arriba(img: Image.Image, crop_pct: float = 0.75) -> Image.Image:
    """Retrato de persona: franja superior, ventana horizontal centrada (cabeza/hombros)."""
    w, h = img.size
    nh = int(h * crop_pct)
    nw = min(w, int(nh * 0.86))   # la cabeza casi siempre está arriba y no usa todo el ancho
    x0 = (w - nw) // 2
    return img.crop((x0, 0, x0 + nw, nh))


def _tinte_papel(img: Image.Image) -> Image.Image:
    """Sepia suave acoplado al papel cálido del stickman (no el gris muerto de fotocopia)."""
    gris = ImageOps.autocontrast(img.convert("L"), cutoff=2)
    return ImageOps.colorize(gris, black=(52, 38, 24), mid=(150, 128, 100),
                             white=(242, 230, 205)).convert("RGB")


def _grano(img: Image.Image, sigma: int = 13, mezcla: float = 0.10) -> Image.Image:
    """Grano de película vieja: 'vintage' visible de cerca, invisible en scroll."""
    ruido = Image.effect_noise(img.size, sigma).convert("RGB")
    return Image.blend(img, ruido, mezcla)


def _vigneta(img: Image.Image, fuerza: int = 60) -> Image.Image:
    """Viñeta suave: los bordes se apagan apenas y el ojo va al centro del recorte."""
    w, h = img.size
    dom = Image.new("L", (w, h))
    dx = [abs(w / 2 - x) / (w / 2) for x in range(w)]
    for y in range(h):
        fy = abs(h / 2 - y) / (h / 2)
        fila = Image.new("L", (w, 1))
        fila.putdata([min(255, int(255 - (fx + fy) * fuerza)) for fx in dx])
        dom.paste(fila, (0, y))
    oscuro = Image.new("RGB", (w, h), (28, 22, 16))
    return Image.composite(img, oscuro, dom)


def _mascara_papel(size: tuple[int, int], seed: int = 42,
                   tema: str = "persona") -> Image.Image:
    """Máscara de papel rasgado: reusa las plantillas de assets/masks cuando existen.

    Las plantillas se generaron una sola vez para todo el canal: los bordes son los
    mismos en cada episodio = vocabulario visual del estilo. El polígono determinista
    queda como respaldo si las plantillas no están.
    """
    w, h = size
    plantillas = sorted(Path(__file__).resolve().parent.parent.glob("assets/masks/paper-*.png"))
    if plantillas:  # elige por seed: variedad dentro de un vocabulario fijo
        try:
            plantilla = Image.open(plantillas[seed % len(plantillas)]).convert("L")
            margen = 4  # respiro para que el borde de la plantilla no corte contenido
            fit = ImageOps.fit(plantilla, (w + margen * 2, h + margen * 2),
                               centering=(0.5, 0.5))
            return fit.crop((margen, margen, margen + w, margen + h))
        except OSError:
            pass  # plantilla corrupta → polígono determinista
    rng = random.Random(seed)
    img = Image.new("L", (w, h), 0)
    d = ImageDraw.Draw(img)
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


ROTA_POSES = (-4.0, -2.5, 2.0, 3.5)   # pierde la manía del siempre-idéntico -4°


def procesar_recorte(source: Path, destino: Path, *, lado: str = "arriba",
                     crop_pct: float = 0.75, rota: float | None = None,
                     tema: str = "persona") -> Path:
    """Tratamiento collage vintage v2 (el "excesivamente prolijo" del dueño):

      1. trim de márgenes del escaneo → 2. encuadre según tema (persona/documento/
      lugar/objeto) → 3. sepia acoplado al papel del stickman → 4. grano → viñeta →
      6. máscara de papel rasgado (plantillas del canal) → 7. sombra →
      8. rotación leve variada.

    Idempotente: si el destino ya existe, no reprocesa (coste cero en re-ciclos).
    """
    if destino.exists() and destino.stat().st_size > 8000:
        return destino
    seed = hash(str(source)) & 0xFFFF
    if rota is None:
        rota = ROTA_POSES[seed % len(ROTA_POSES)]
    src_img = Image.open(source).convert("RGB")
    limpio = _recortar_margenes(src_img)
    crop = _recortador(limpio, crop_pct=crop_pct, lado=lado, tema=tema)
    crop = _tinte_papel(crop)
    crop = _grano(crop)
    crop = _vigneta(crop)
    alfa = _mascara_papel(crop.size, seed=seed, tema=tema)
    rec = Image.new("RGBA", crop.size, (0, 0, 0, 0))
    rec.paste(crop, mask=alfa)
    sombra = Image.new("RGBA", crop.size, (0, 0, 0, 0))
    sombra.putalpha(_sombra(alfa, offset=(5, 6), blur=8))
    rec = Image.alpha_composite(sombra, rec)
    # rot. leve: cartel con borde rasgado
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
