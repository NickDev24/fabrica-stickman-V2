"""Composición del cómic FUERA del generador de imágenes (contrato comics.v2).

El modelo de difusión dibuja la ilustración cruda; AQUÍ se arma el LIBRO:
  - páginas 1080x1620 con GRILLAS REALES de 3 bandas (ej. 3/4/3: tres viñetas
    arriba, cuatro al medio, tres abajo) tomadas del storyboard,
  - viñetas con imagen COVER-CROP (nada de thumbnails con relleno),
  - marco de tinta grueso + tachuelas de esquina (oficio de historieta),
  - caption de narración compuesto tipográficamente (texto FUERA del modelo),
  - viñeta de silencio = panel negro con caption (beat de descompresión),
  - número de viñeta pequeño, encabezado "PULSO CURIOSO · título",
  - footer por página: número de página + fuentes verificadas del capítulo,
  - chapter_vertical.png (páginas apiladas) y carrusel POR PÁGINA (1 imagen
    por página, formato libro — no 1 imagen por panel).

Reglas del diseño: sin párrafos que compitan con la imagen; el caption entra
en la viñeta bajando tipografía, nunca se recorta el contenido citado.
"""
from __future__ import annotations

import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from ..episode import Episode

FONT_BOLD = Path(__file__).resolve().parents[2] / "assets" / "comics" / "fonts" / "DejaVuSans-Bold.ttf"
FONT_REG = Path(__file__).resolve().parents[2] / "assets" / "comics" / "fonts" / "DejaVuSans.ttf"

PAG_W, PAG_H = 1080, 1620
MARGEN = 38
GUTTER = 14
FRAME = 6              # marco de tinta por viñeta
TINTA = (18, 16, 14)   # tinta negra cálida
ACENTO = (196, 30, 30)
PAPEL = (238, 232, 224)
SOMBRA_FUENTE = (120, 60, 40)
TITULO_PX = 46
CABECERA_PX = 20
FOOTER_PX = 19
CAP_MAX = 30           # tipografía de caption: arranca acá y baja hasta 18
CAP_MIN = 18

LAZO = "/"


def _fuente(size: int, bold: bool = True):
    ruta = FONT_BOLD if bold else FONT_REG
    if not ruta.exists():
        raise RuntimeError(f"falta la tipografía del cómic: {ruta}")
    return ImageFont.truetype(str(ruta), size)


def _confitar(texto: str, fuente, ancho_max: int, dibujo) -> list[str]:
    """Wrapped determinista por palabras."""
    lineas, actual = [], ""
    for palabra in texto.split():
        prueba = (actual + " " + palabra).strip()
        if dibujo.textlength(prueba, font=fuente) <= ancho_max:
            actual = prueba
        else:
            if actual:
                lineas.append(actual)
            if dibujo.textlength(palabra, font=fuente) > ancho_max:
                while len(palabra) > 1 and dibujo.textlength(palabra, font=fuente) > ancho_max:
                    corte = max(1, len(palabra) - 1)
                    lineas.append(palabra[:corte])
                    palabra = palabra[corte:]
            actual = palabra
    if actual:
        lineas.append(actual)
    return lineas


def _host(url: str) -> str:
    """Hostname corto para el footer (fuentes visibles, sin URLs kilométricas)."""
    limpio = (url or "").replace("https://", "").replace("http://", "").replace("www.", "")
    return limpio.split("/")[0].split("?")[0].strip()


def _tachuelas(d: ImageDraw.ImageDraw, x0: int, y0: int, x1: int, y1: int) -> None:
    """4 tachuelas de esquina sobre el marco (oficio de historieta)."""
    r = 5
    for (cx, cy) in ((x0, y0), (x1, y0), (x0, y1), (x1, y1)):
        d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=SOMBRA_FUENTE, outline=TINTA, width=2)


def _vineta(d: ImageDraw.ImageDraw, page: Image.Image, panel: dict, img: Path,
            x0: int, y0: int, w: int, h: int, participantes: int) -> None:
    """UNA viñeta: cover-crop + marco grueso + tachuelas + caption + número."""
    es_silencio = str(panel.get("accion", "")) == "silencio"
    narracion = str(panel.get("narracion", "")).strip()
    # marco (borde exterior) — se dibuja primero para que la imagen quede adentro
    inner_x0, inner_y0 = x0 + FRAME, y0 + FRAME
    inner_x1, inner_y1 = x0 + w - FRAME, y0 + h - FRAME
    inner_w, inner_h = inner_x1 - inner_x0, inner_y1 - inner_y0
    if inner_w <= 10 or inner_h <= 10:
        return
    # imagen: cover-crop (recorta al centrar, jamás deforma / deja relleno)
    puesta = False
    if not es_silencio and img.exists():
        try:
            im = Image.open(img).convert("RGB")
            escala = max(inner_w / im.width, inner_h / im.height)
            nw, nh = max(1, round(im.width * escala)), max(1, round(im.height * escala))
            im = im.resize((nw, nh), Image.LANCZOS)
            dx = (nw - inner_w) // 2
            dy = (nh - inner_h) // 2
            im = im.crop((dx, dy, dx + inner_w, dy + inner_h))
            page.paste(im, (inner_x0, inner_y0))
            puesta = True
        except (OSError, ValueError):
            puesta = False
    if es_silencio or not puesta:
        # silencio (panel negro con caption) o imagen faltante declarada
        d.rectangle([inner_x0, inner_y0, inner_x1, inner_y1],
                    fill=TINTA if es_silencio else (60, 56, 52))
    # caption tipográfico en la base de la viñeta (con el texto citado)
    if narracion:
        ancho_txt = inner_w - 22
        tamaño, lineas = CAP_MAX, []
        while tamaño >= CAP_MIN:
            f = _fuente(tamaño, bold=False)
            lineas = _confitar(narracion, f, ancho_txt, d)
            if len(lineas) * (tamaño + 6) + 12 <= max(60, int(inner_h * 0.5)):
                break
            tamaño -= 2
        lineas = lineas[:12]
        f = _fuente(tamaño, bold=False)
        alto = len(lineas) * (tamaño + 6) + 10
        cy0 = inner_y1 - alto
        d.rectangle([inner_x0, cy0, inner_x1, inner_y1], fill=PAPEL,
                    outline=TINTA, width=2)
        ty = cy0 + 5
        for ln in lineas:
            d.text((inner_x0 + 11, ty), ln, fill=TINTA, font=f)
            ty += tamaño + 6
    # número de viñeta: ficha chica arriba a la izquierda
    r = 15
    d.ellipse([inner_x0 + 8, inner_y0 + 8, inner_x0 + 8 + 2 * r, inner_y0 + 8 + 2 * r],
              fill=ACENTO, outline=TINTA, width=2)
    num = str(int(panel.get("i", 0)))
    f_num = _fuente(17)
    tw = d.textlength(num, font=f_num)
    d.text((inner_x0 + 8 + r - tw / 2, inner_y0 + 10), num, fill=PAPEL, font=f_num)
    # marco por encima + tachuelas
    d.rectangle([x0, y0, x0 + w, y0 + h], outline=TINTA, width=FRAME)
    _tachuelas(d, x0 + 3, y0 + 3, x0 + w - 3, y0 + h - 3)


def _cabecera(d: ImageDraw.ImageDraw, titulo: str, ancho: int) -> int:
    """Encabezado de capítulo: serie + título (auto-ajustado). Devuelve la Y final."""
    y = MARGEN
    d.text((MARGEN, y), " · ".join(("PULSO", "CURIOSO")).upper(),
           fill=SOMBRA_FUENTE, font=_fuente(CABECERA_PX))
    y += CABECERA_PX + 8
    tamaño = TITULO_PX
    while tamaño >= 28:
        f_t = _fuente(tamaño)
        lineas = _confitar(titulo, f_t, ancho, d)
        if len(lineas) <= 2:
            break
        tamaño -= 3
    for ln in lineas[:2]:
        d.text((MARGEN, y), ln, fill=TINTA, font=f_t)
        y += f_t.size + 6
    d.rectangle([MARGEN, y + 4, MARGEN + 96, y + 9], fill=ACENTO)  # regla roja del capítulo
    return y + 22


def _footer(d: ImageDraw.ImageDraw, pagina: int, total: int, fuentes: list[str]) -> None:
    """Footer por página: número de página (izq) + fuentes verificadas (der)."""
    y = PAG_H - MARGEN - FOOTER_PX - 10
    d.rectangle([MARGEN, y - 8, PAG_W - MARGEN, y - 7], fill=TINTA)
    hosts = sorted({_host(u) for u in fuentes if u})
    texto_f = (f"{len(hosts)} fuente" if len(hosts) == 1 else f"{len(hosts)} fuentes") \
        if hosts else "sin fuentes — no se publica"
    txt_fuentes = ("fuentes: " + LAZO.join(hosts[:3])) if hosts else texto_f
    if len(txt_fuentes) > 64:
        txt_fuentes = f"fuentes: {hosts[0]} +{max(0, len(hosts) - 1)} más"
    f = _fuente(FOOTER_PX, bold=False)
    d.text((MARGEN, y), f"PÁGINA {pagina} DE {total}", fill=SOMBRA_FUENTE, font=_fuente(FOOTER_PX))
    ancho_fuentes = d.textlength(txt_fuentes, font=f)
    d.text((PAG_W - MARGEN - ancho_fuentes, y), txt_fuentes, fill=SOMBRA_FUENTE, font=f)


def _pagina(ep: Episode, datos: dict, grilla: list[int], paneles_pg: list[dict],
            rutas: dict[int, Path], n_pagina: int, total_pag: int) -> Image.Image:
    page = Image.new("RGB", (PAG_W, PAG_H), PAPEL)
    d = ImageDraw.Draw(page)
    y0p = _cabecera(d, str(datos.get("titulo", ep.slug)), PAG_W - 2 * MARGEN)
    y1p = PAG_H - MARGEN - FOOTER_PX - 26
    Ud = y1p - y0p
    h_bandas = [
        int(Ud * [1.0, 1.06, 1.0, 0.96][min(i, 3)] ) for i in range(len(grilla))
    ]
    # normaliza para que las bandas + gutters cierren exactas en Ud
    factor = (Ud - GUTTER * (len(grilla) - 1)) / max(1, sum(h_bandas))
    y, k = y0p, 0
    for bi, en_banda in enumerate(grilla):
        hb = int(h_bandas[bi] * factor)
        w_panel = (PAG_W - 2 * MARGEN - GUTTER * (en_banda - 1)) // en_banda
        x = MARGEN
        banda = paneles_pg[k:k + en_banda]          # ESTA banda consume SU tramo
        k += en_banda
        for pi in range(en_banda):
            panel = banda[pi] if pi < len(banda) else {}
            _vineta(d, page, panel, rutas.get(int(panel.get("i", 0)), Path("/x")),
                    x, y, w_panel, hb, en_banda)
            x += w_panel + GUTTER
        y += hb + GUTTER
    fuentes_pg = [u for p in paneles_pg for u in (p.get("fuentes") or [])]
    _footer(d, n_pagina, total_pag, fuentes_pg)
    return page


def componer(ep: Episode, datos: dict, rutas: list[Path]) -> dict:
    """Arma el libro: pages/pag-NN.png + chapter_vertical.png + carrusel/pag-NN.png."""
    comics = ep.dir / "comics"
    carpeta_pag = comics / "pages"
    carpeta_car = comics / "carrusel"
    carpeta_pag.mkdir(parents=True, exist_ok=True)
    carpeta_car.mkdir(parents=True, exist_ok=True)

    paneles = sorted(datos.get("paneles", []), key=lambda x: int(x.get("i", 0)))
    grillas = datos.get("grillas") or []
    rutas_map = {int(p.get("i", 0)): Path(r) for p, r in zip(paneles, rutas)}

    # reparte los paneles por página según el corte de las grillas
    por_pagina: dict[int, list[dict]] = {}
    k = 0
    for n_pag, g in enumerate(grillas, 1):
        n_pg = sum(g)
        por_pagina[n_pag] = paneles[k:k + n_pg]
        k += n_pg

    rutas_pag = []
    for n_pag, g in enumerate(grillas, 1):
        page = _pagina(ep, datos, g, por_pagina.get(n_pag, []),
                       rutas_map, n_pag, len(grillas))
        out = carpeta_pag / f"pag-{n_pag:02d}.png"
        page.save(out)
        rutas_pag.append(out)

    # carrusel: 1 imagen POR PÁGINA (formato libro), no por panel
    rutas_car = []
    for src in rutas_pag:
        dst = carpeta_car / src.name
        dst.write_bytes(src.read_bytes())
        rutas_car.append(dst)

    # chapter vertical: páginas apiladas para lectura continua
    total_h = PAG_H * len(rutas_pag)
    vertical = Image.new("RGB", (PAG_W, total_h), TINTA)
    for j, src in enumerate(rutas_pag):
        vertical.paste(Image.open(src).convert("RGB"), (0, j * PAG_H))
    ruta_vert = comics / "chapter_vertical.png"
    vertical.save(ruta_vert)

    # huérfanos de formatos anteriores (v1: pagina_vertical / panel-*.png)
    for viejo in comics.glob("pagina_vertical.png"):
        viejo.unlink()
    for hu in carpeta_car.glob("panel-*.png"):
        hu.unlink()
    vigentes = {p.name for p in rutas_pag}
    for hu in carpeta_pag.glob("pag-*.png"):
        if hu.name not in vigentes:
            hu.unlink()
    vigentes_car = {p.name for p in rutas_car}
    for hu in carpeta_car.glob("pag-*.png"):
        if hu.name not in vigentes_car:
            hu.unlink()

    manifest = {
        "schema": "comics.v2",
        "slug": ep.slug,
        "titulo": str(datos.get("titulo", ep.slug)),
        "grillas": grillas,
        "vinetas": len(paneles),
        "paginas": [p.name for p in rutas_pag],
        "chapter_vertical": ruta_vert.name,
        "carrusel": [p.name for p in rutas_car],
        "tipografia": "DejaVu Sans (assets/comics/fonts)",
        "texto_fuera_del_generador": True,
        "fuentes_por_pagina": {
            f"pag-{n:02d}": sorted({_host(u) for p in por_pagina.get(n, [])
                                    for u in (p.get("fuentes") or [])})
            for n in range(1, len(grillas) + 1)
        },
    }
    manifest_p = comics / "manifest.json"
    manifest_p.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"pagina": rutas_pag[0] if rutas_pag else None,
            "paginas": rutas_pag,
            "chapter_vertical": ruta_vert,
            "carrusel": rutas_car,
            "manifest": manifest_p}
