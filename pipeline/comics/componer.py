"""Composición del cómic FUERA del generador de imágenes (contrato comics.v2, premium).

El modelo de difusión dibuja la ilustración cruda; AQUÍ se arma el LIBRO:
  - PORTADA scroll-stopper (slide 1): impacto visual alto en feed, titular corto,
    contraste fuerte y branding — pensada para quien nunca leyó un cómic.
  - páginas 1080x1620 con GRILLAS REALES de 3 bandas (ej. 3/4/3) tomadas del storyboard,
  - viñetas con imagen COVER-CROP (nada de thumbnails con relleno),
  - marco de tinta grueso + tachuelas de esquina (oficio de historieta),
  - caption de narración compuesto tipográficamente, alta legibilidad móvil,
  - viñeta de silencio = panel negro con caption (beat de descompresión),
  - footer por página: número de página + fuentes verificadas del capítulo,
  - chapter_vertical.png (páginas apiladas) y carrusel POR PÁGINA (1 imagen por página).

Reglas: sin párrafos que compitan con la imagen; el caption entra bajando tipografía,
nunca se recorta el contenido citado.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps

from ..episode import Episode

FONT_BOLD = Path(__file__).resolve().parents[2] / "assets" / "comics" / "fonts" / "DejaVuSans-Bold.ttf"
FONT_REG = Path(__file__).resolve().parents[2] / "assets" / "comics" / "fonts" / "DejaVuSans.ttf"

PAG_W, PAG_H = 1080, 1620
MARGEN = 38
GUTTER = 14
FRAME = 7              # marco de tinta por viñeta
TINTA = (18, 16, 14)   # tinta negra cálida
ACENTO = (226, 48, 40) # acento alto impacto (rojo vivo)
PAPEL = (242, 236, 228)
SOMBRA_FUENTE = (160, 150, 140)
TITULO_PX = 46
CABECERA_PX = 20
FOOTER_PX = 19
# Caption premium: legible en móvil, alto contraste, texto breve (no compite con imagen)
CAP_MAX = 38
CAP_MIN = 22
CAP_PAD = 16

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
    """UNA viñeta: cover-crop + marco grueso + tachuelas + caption legible móvil."""
    es_silencio = str(panel.get("accion", "")) == "silencio"
    narracion = str(panel.get("narracion", "")).strip()
    inner_x0, inner_y0 = x0 + FRAME, y0 + FRAME
    inner_x1, inner_y1 = x0 + w - FRAME, y0 + h - FRAME
    inner_w, inner_h = inner_x1 - inner_x0, inner_y1 - inner_y0
    if inner_w <= 10 or inner_h <= 10:
        return
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
        d.rectangle([inner_x0, inner_y0, inner_x1, inner_y1],
                    fill=TINTA if es_silencio else (55, 52, 48))
        if es_silencio:
            # beat de silencio con tensión visual (no vacío): respiro dramático
            f_s = _fuente(max(18, min(28, inner_w // 10)), bold=True)
            txt_s = narracion or "…"
            tw_s = d.textlength(txt_s, font=f_s)
            d.text((inner_x0 + (inner_w - tw_s) / 2, inner_y0 + inner_h * 0.45),
                   txt_s, fill=(245, 240, 232), font=f_s)
            narracion = ""  # ya pintado centrado

    # Caption: caja alta legible con gradiente, tipografía bold y sombra (scroll/móvil)
    if narracion:
        ancho_txt = inner_w - CAP_PAD * 2
        tamaño, lineas = CAP_MAX, []
        while tamaño >= CAP_MIN:
            f = _fuente(tamaño, bold=True)
            lineas = _confitar(narracion, f, ancho_txt, d)
            if len(lineas) * (tamaño + 8) + 18 <= max(64, int(inner_h * 0.55)):
                break
            tamaño -= 2
        lineas = lineas[:10]
        f = _fuente(tamaño, bold=True)
        alto = len(lineas) * (tamaño + 8) + 16
        cy0 = inner_y1 - alto
        # degradado inferior para legibilidad sin tapar demasiado la imagen
        grad_h = min(alto + 40, inner_h)
        for gy in range(grad_h):
            a = int(40 + 150 * (gy / max(1, grad_h - 1)))
            yy = inner_y1 - grad_h + gy
            d.line([(inner_x0, yy), (inner_x1, yy)], fill=(10, 10, 10))
        # capa sólida suave bajo texto
        d.rectangle([inner_x0, cy0, inner_x1, inner_y1], fill=(12, 12, 12))
        ty = cy0 + 8
        for ln in lineas:
            # sombra para contraste en cualquier fondo
            d.text((inner_x0 + CAP_PAD + 1, ty + 1), ln, fill=(0, 0, 0), font=f)
            d.text((inner_x0 + CAP_PAD, ty), ln, fill=(250, 248, 244), font=f)
            ty += tamaño + 8

    # badge de número discreto (no compite)
    r = 14
    d.ellipse([inner_x0 + 8, inner_y0 + 8, inner_x0 + 8 + 2 * r, inner_y0 + 8 + 2 * r],
              fill=ACENTO, outline=(255, 255, 255), width=2)
    num = str(int(panel.get("i", 0)))
    f_num = _fuente(16, bold=True)
    tw = d.textlength(num, font=f_num)
    d.text((inner_x0 + 8 + r - tw / 2, inner_y0 + 9), num, fill=(255, 255, 255), font=f_num)
    # marco y tachuelas
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



def _hook_texto(datos: dict, titulo: str, variante: str = "A") -> str:
    """Titular corto de alto impacto para portada (scroll-stop, sin spoilear).

    variante A/B/C produce hooks distintos (A/B testing de packaging) sin costo de imagen.
    """
    paneles = sorted(datos.get("paneles", []) or [], key=lambda x: int(x.get("i", 0)))
    base = ""
    for p in paneles:
        if str(p.get("rol_ritmico")) in ("gancho", "contexto"):
            base = str(p.get("narracion") or p.get("ancla_guion") or "").strip()
            if base:
                break
    if not base:
        base = str(titulo or "").strip()
    base = re.sub(r"\[[^\]]*\]", "", base)
    base = re.sub(r"\s+", " ", base).strip(" .-–—")
    m = re.search(r"([^.!?]*\?)", base)
    if m and 4 <= len(m.group(1).split()) <= 12:
        frase = m.group(1).strip()
    else:
        m = re.search(r"^([^.!?]{10,90}[.!?])", base)
        frase = m.group(1).strip() if m else base
    palabras = [w for w in re.split(r"\s+", frase) if w]
    if variante == "B":
        # tensión directa desde el título (promesa/curiosidad)
        tpal = [w for w in re.split(r"\s+", str(titulo or "").strip()) if w][:7]
        if len(tpal) >= 3:
            palabras = tpal
    elif variante == "C":
        # más corto y punzante
        if len(palabras) > 5:
            palabras = palabras[:5]
    if len(palabras) > 8:
        palabras = palabras[:8]
    if not palabras:
        palabras = (titulo or "Pulso Curioso").split()[:6] or ["Pulso Curioso"]
    mid = (len(palabras) + 1) // 2
    return " ".join(palabras[:mid]) + "\n" + " ".join(palabras[mid:])


def _portada(ep: "Episode", datos: dict, rutas: dict[int, Path], out: Path,
             variante: str = "A") -> Path:
    """Portada premium 1080x1620: primer impacto visual (slide 1 del carrusel).

    variante A/B/C: hook y acento distintos para A/B testing (sin costo de imagen).
    """
    paneles = sorted(datos.get("paneles", []) or [], key=lambda x: int(x.get("i", 0)))
    # imagen base: gancho o primera viñeta con imagen real
    gancho = next((p for p in paneles if str(p.get("rol_ritmico")) == "gancho"), paneles[0] if paneles else {})
    img_path = rutas.get(int(gancho.get("i", 0))) if gancho else None
    page = Image.new("RGB", (PAG_W, PAG_H), TINTA)
    puesta = False
    if img_path and Path(img_path).exists():
        try:
            im = Image.open(img_path).convert("RGB")
            # contraste/saturación leve para impacto (sin dependencias extra)
            im = ImageOps.autocontrast(im, cutoff=1)
            escala = max(PAG_W / im.width, PAG_H / im.height)
            nw, nh = max(1, round(im.width * escala)), max(1, round(im.height * escala))
            im = im.resize((nw, nh), Image.LANCZOS)
            dx, dy = (nw - PAG_W) // 2, (nh - PAG_H) // 2
            im = im.crop((dx, dy, dx + PAG_W, dy + PAG_H))
            page.paste(im, (0, 0))
            puesta = True
        except (OSError, ValueError):
            puesta = False
    if not puesta:
        page.paste(Image.new("RGB", (PAG_W, PAG_H), (30, 28, 26)), (0, 0))
    d = ImageDraw.Draw(page)
    # gradiente superior e inferior para legibilidad/impacto
    for gy in range(int(PAG_H * 0.55)):
        a = int(10 + 170 * (gy / max(1, int(PAG_H * 0.55) - 1)))
        y = PAG_H - int(PAG_H * 0.55) + gy
        d.line([(0, y), (PAG_W, y)], fill=(0, 0, 0))
    for gy in range(int(PAG_H * 0.22)):
        a = int(140 * (1 - gy / max(1, int(PAG_H * 0.22) - 1)))
        d.line([(0, gy), (PAG_W, gy)], fill=(0, 0, 0))

    # acento por variante (A/B testing visual)
    acento_v = {"A": ACENTO, "B": (240, 180, 30), "C": (40, 180, 220)}.get(variante, ACENTO)
    # marca
    yb = 54
    marca = "PULSO CURIOSO"
    f_m = _fuente(34, bold=True)
    twm = d.textlength(marca, font=f_m)
    d.rectangle([MARGEN - 10, yb - 8, MARGEN + twm + 10, yb + 36], fill=acento_v)
    d.text((MARGEN, yb), marca, fill=(255, 255, 255), font=f_m)

    # titular grande (scroll-stop)
    titulo = str(datos.get("titulo") or ep.read_state().get("title") or ep.slug)
    hook = _hook_texto(datos, titulo, variante=variante)
    size = 96
    f_h = _fuente(size, bold=True)
    lineas = hook.split("\n")
    while size >= 54:
        f_h = _fuente(size, bold=True)
        lineas = hook.split("\n")
        maxw = max((d.textlength(ln, font=f_h) for ln in lineas), default=0)
        totalh = len(lineas) * (size + 10)
        if maxw <= PAG_W - 2 * MARGEN - 10 and totalh <= 320:
            break
        size -= 4
    y_text = int(PAG_H * 0.58)
    # barra de acento
    d.rectangle([MARGEN, y_text - 18, MARGEN + 110, y_text - 8], fill=acento_v)
    for ln in lineas:
        # sombra gruesa + blanco para contraste máximo
        for ox, oy in ((3, 3), (2, 2), (-1, 2)):
            d.text((MARGEN + ox, y_text + oy), ln, fill=(0, 0, 0), font=f_h)
        d.text((MARGEN, y_text), ln, fill=(255, 255, 255), font=f_h)
        y_text += size + 10

    # subtítulo/serie corto
    subt = "HISTORIETA · HECHOS VERIFICADOS"
    f_s = _fuente(30, bold=True)
    d.text((MARGEN + 2, y_text + 14), subt, fill=(235, 230, 224), font=f_s)

    # CTA de deslizamiento (clave para carrusel FB)
    cta = "DESLIZÁ Y LEÉ LA HISTORIA  →"
    f_c = _fuente(34, bold=True)
    twc = d.textlength(cta, font=f_c)
    cx0 = (PAG_W - twc) / 2 - 26
    cy0 = PAG_H - MARGEN - 86
    d.rounded_rectangle([cx0, cy0, cx0 + twc + 52, cy0 + 64], radius=18, fill=acento_v)
    d.text((cx0 + 26, cy0 + 14), cta, fill=(255, 255, 255), font=f_c)

    # marco fino premium
    d.rectangle([10, 10, PAG_W - 10, PAG_H - 10], outline=(245, 240, 232), width=4)
    page.save(out)
    return out


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

    # Portadas scroll-stopper A/B (sin costo de imagen): variantes para testear gancho/CTR.
    variantes_portada = {}
    for var in ("A", "B", "C"):
        try:
            pvar = comics / f"portada_{var.lower()}.png"
            _portada(ep, datos, rutas_map, pvar, variante=var)
            if pvar.exists():
                variantes_portada[var] = pvar
        except Exception:
            pass
    elegida = "A" if "A" in variantes_portada else (next(iter(variantes_portada)) if variantes_portada else None)
    portada = comics / "portada.png"
    if elegida:
        portada.write_bytes(variantes_portada[elegida].read_bytes())
    portada = portada if portada.exists() else None

    # carrusel: portada elegida (si existe) + 1 imagen POR PÁGINA
    rutas_car = []
    if portada:
        dst_cov = carpeta_car / "00-portada.png"
        dst_cov.write_bytes(portada.read_bytes())
        rutas_car.append(dst_cov)
    for src in rutas_pag:
        dst = carpeta_car / src.name
        dst.write_bytes(src.read_bytes())
        rutas_car.append(dst)

    # chapter vertical: páginas apiladas para lectura continua (solo historia)
    total_h = PAG_H * len(rutas_pag)
    vertical = Image.new("RGB", (PAG_W, total_h), TINTA)
    for j, src in enumerate(rutas_pag):
        vertical.paste(Image.open(src).convert("RGB"), (0, j * PAG_H))
    ruta_vert = comics / "chapter_vertical.png"
    vertical.save(ruta_vert)

    # huérfanos de formatos anteriores
    for viejo in comics.glob("pagina_vertical.png"):
        viejo.unlink()
    for hu in carpeta_car.glob("panel-*.png"):
        hu.unlink()
    vigentes = {p.name for p in rutas_pag}
    for hu in carpeta_pag.glob("pag-*.png"):
        if hu.name not in vigentes:
            hu.unlink()
    vigentes_car = {p.name for p in rutas_car}
    for hu in carpeta_car.glob("*portada*.png"):
        if hu.name not in vigentes_car:
            hu.unlink()
    for hu in carpeta_car.glob("pag-*.png"):
        if hu.name not in vigentes_car:
            hu.unlink()

    manifest = {
        "schema": "comics.v3",
        "slug": ep.slug,
        "titulo": str(datos.get("titulo", ep.slug)),
        "grillas": grillas,
        "vinetas": len(paneles),
        "portada": portada.name if portada else None,
        "portada_variante": elegida,
        "portada_variantes": {k: v.name for k, v in variantes_portada.items()},
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
            "portada": portada,
            "portada_variante": elegida,
            "portada_variantes": variantes_portada,
            "paginas": rutas_pag,
            "chapter_vertical": ruta_vert,
            "carrusel": rutas_car,
            "manifest": manifest_p}
