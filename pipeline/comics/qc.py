"""QC del cómic (contrato comics.v2): bloquea la salida si viola las reglas.

Chequeos (FABRICA-DE-COMICS.md, orden del dueño 2026-11-06):
  - mínimo 15 viñetas por capítulo,
  - grillas REALES: exactamente 3 bandas por página, 1-4 viñetas por banda,
    y sum(grillas) == número de viñetas,
  - cada viñeta con narración <= NARRACION_MAX y NO vacía,
  - cada viñeta (excepto silencio) con ancla_guion al guion verificado,
  - cada página con al menos 1 fuente verificada (footer con fuentes),
  - imágenes presentes, decodificables y no sospechosamente chicas
    (la viñeta de silencio es panel negro: no lleva imagen),
  - páginas 1080x1620, chapter_vertical y carrusel 1 imagen por página,
  - personajes declarados en personajes.json.
El reporte va a comics/qc.json y NO bloquea nunca el pipeline de video.
"""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

from PIL import Image

from ..episode import Episode
from .adaptar_guion import NARRACION_MAX, VINETAS_MIN

IMAG_TAM_MIN = 8000
PAG_TAM = (1080, 1620)


def ejecutar(ep: Episode, datos: dict, rutas_imagenes: list, artefactos: dict) -> list[str]:
    """Devuelve la lista de problemas (vacía = aprobado). Registra comics/qc.json."""
    problemas = []
    paneles = sorted(datos.get("paneles", []), key=lambda x: int(x.get("i", 0)))
    grillas = datos.get("grillas") or []
    n_v = len(paneles)

    if datos.get("schema") != "comics.v2":
        problemas.append(f"schema {datos.get('schema')!r} != comics.v2")
    if n_v < VINETAS_MIN:
        problemas.append(f"{n_v} viñetas < mínimo del dueño ({VINETAS_MIN})")

    # grillas reales de 3 bandas
    for n_pag, g in enumerate(grillas, 1):
        if len(g) != 3:
            problemas.append(f"página {n_pag}: grilla con {len(g)} bandas (deben ser 3)")
        for b in g:
            if not (1 <= int(b) <= 4):
                problemas.append(f"página {n_pag}: banda con {b} viñetas (permitido 1-4)")
    if sum(sum(g) for g in grillas) != n_v:
        problemas.append(f"sum(grillas)={sum(sum(g) for g in grillas)} != viñetas {n_v}")

    # narración + ancla + fuentes
    for p in paneles:
        i = p.get("i")
        rol = str(p.get("rol_ritmico", ""))
        narr = str(p.get("narracion", "") or "")
        if not narr.strip():
            problemas.append(f"viñeta {i}: narración vacía")
        elif len(narr) > NARRACION_MAX:
            problemas.append(f"viñeta {i}: narración {len(narr)} chars (> {NARRACION_MAX})")
        if rol != "silencio":
            ancla = str(p.get("ancla_guion", "") or "").strip()
            if not ancla:
                problemas.append(f"viñeta {i}: sin ancla_guion — nada entra al cómic "
                                 "fuera del guion verificado")
        # Un caption pulido por LLM sin paridad aprobada es un hecho sin control:
        # se bloquea el libro, aunque el texto «suene bien».
        if str(p.get("caption_via", "")) == "llm" and not (p.get("paridad") or {}).get("ok"):
            problemas.append(f"viñeta {i}: caption LLM sin paridad factual aprobada")

    # footer de fuentes POR PÁGINA (retención también es credibilidad)
    fuentes_por_pag: dict[int, int] = defaultdict(int)
    for p in paneles:
        fuentes_por_pag[int(p.get("pagina", 1))] += len(p.get("fuentes") or [])
    for n_pag in range(1, len(grillas) + 1):
        if fuentes_por_pag.get(n_pag, 0) == 0:
            problemas.append(f"página {n_pag}: sin fuentes verificadas para el footer")

    # imágenes: presentes, decodificables (excepto silencio — panel negro)
    rutas_por_i = {}
    for pa in rutas_imagenes:
        rutas_por_i[Path(pa).stem.replace("p-", "")] = pa
    for p in paneles:
        i = int(p.get("i", 0))
        ruta = rutas_por_i.get(f"{i:03d}") or (Path(rutas_por_i[str(i)])
                                               if str(i) in rutas_por_i else None)
        if str(p.get("accion", "")) == "silencio":
            continue
        if ruta is None:
            problemas.append(f"viñeta {i}: sin imagen")
            continue
        try:
            if ruta.stat().st_size < IMAG_TAM_MIN:
                problemas.append(f"{ruta.name}: {ruta.stat().st_size} bytes (sospechosa)")
            Image.open(ruta).verify()
        except (OSError, ValueError, FileNotFoundError) as e:
            problemas.append(f"{ruta.name}: imagen ilegible ({type(e).__name__})")

    # artefactos: páginas + chapter vertical + carrusel por página
    rutas_pag = artefactos.get("paginas") or []
    if len(rutas_pag) != len(grillas):
        problemas.append(f"{len(rutas_pag)} imágenes de página != {len(grillas)} grillas")
    for pa in rutas_pag:
        try:
            if Image.open(pa).size != PAG_TAM:
                problemas.append(f"página {Path(pa).name} {Image.open(pa).size} != {PAG_TAM}")
        except OSError as e:
            problemas.append(f"página ilegible: {e}")
    rvert = artefactos.get("chapter_vertical")
    if rvert:
        try:
            esperado = (PAG_TAM[0], PAG_TAM[1] * len(rutas_pag))
            if Image.open(rvert).size != esperado:
                problemas.append(f"chapter_vertical {Image.open(rvert).size} != {esperado}")
        except OSError as e:
            problemas.append(f"chapter_vertical ilegible: {e}")
    carrusel = artefactos.get("carrusel") or []
    if len(carrusel) != len(rutas_pag):
        problemas.append(f"carrusel con {len(carrusel)} imágenes != {len(rutas_pag)} páginas")

    # personajes declarados
    ficha_p = ep.dir / "comics" / "personajes.json"
    try:
        fichas = json.loads(ficha_p.read_text(encoding="utf-8"))
        if not fichas.get("narrador_canal"):
            problemas.append("personajes.json sin ficha del narrador del canal")
    except (OSError, json.JSONDecodeError):
        problemas.append("personajes.json no existe o es inválido")

    reporte = {"slug": ep.slug, "schema": datos.get("schema"),
               "problemas": problemas,
               "aprobado": not problemas,
               "vinetas": n_v,
               "paginas": len(grillas),
               "grillas": grillas,
               "imagenes": len(rutas_imagenes)}
    fuera = ep.dir / "comics"
    fuera.mkdir(parents=True, exist_ok=True)
    (fuera / "qc.json").write_text(
        json.dumps(reporte, ensure_ascii=False, indent=2), encoding="utf-8")
    return problemas
