"""Etapa de visuales autónoma: fotos reales por segmento desde Wikimedia Commons
(licencias PD/CC BY/CC BY-SA, nada NC/ND) y NASA Images como secundario.

Sin esto el render queda en cartelas planas: un documental de hechos reales necesita
material de época, mapas y fotografías. Los créditos quedan en assets/img/licenses.json
para pegar en la descripción (gate de fuentes + atribuciones).
"""
from __future__ import annotations

import json
import os
import re
import shutil
import time
from pathlib import Path
from urllib.parse import quote

import requests
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont, ImageOps, ImageStat

from .. import llm
from ..episode import Episode
from .narracion import _segments

UA = {"User-Agent": "PulsoCuriosoPipeline/1.0 (canal de documentales; contacto: pipeline@pulsocurioso.example)"}

PD_OK = re.compile(r"public\s*domain|\bPD\b|CC0|CC\s*BY(\s*-SA)?\b|GNU\s*FDL|Attribution", re.I)
PROHIBIDO = re.compile(r"\bNC\b|NonCommercial|NoDeriv|\bND\b|mark as non-commercial", re.I)

# Términos de archivo que casi nunca son una escena del evento (instalaciones, mapas
# modernos de ciudades, íconos): se descartan para que no ensucien el relato.
RUIDO = re.compile(r"logo|icon|.svg|thumb|Locating\son\sa\smap|Locator map|flag of", re.I)
# Material "etiquetado con el evento" pero que NO retrata la escena: instalaciones
# universitarias modernas, sellos postales, exhibiciones (no fotos históricas reales).
MODERNO = re.compile(r"universit|\buniv\b|\bcpa\b|postage|\bstamp\b|exhibit|museum.*\d{4}", re.I)


def _wiki_images(topic: str, limit: int = 14) -> list[dict]:
    """Imágenes REALMENTE usadas en el artículo de Wikipedia del tema: la foto icónica del
    bosque arrasado, el mapa del epicentro, el retrato del científico. Mucho más fiables que
    el full-text de Commons, que devuelve series ajenas (ej. una muestra universitaria)."""
    try:
        sr = requests.get("https://en.wikipedia.org/w/api.php", params={
            "action": "query", "list": "search", "srsearch": topic, "srlimit": 1,
            "format": "json"}, headers=UA, timeout=25).json()
        hit = (sr.get("query", {}).get("search") or [{}])
        if not hit or "title" not in hit[0]:
            return []
        title = hit[0]["title"]
        pg = requests.get("https://en.wikipedia.org/w/api.php", params={
            "action": "query", "titles": title, "prop": "images", "imlimit": limit * 3,
            "format": "json"}, headers=UA, timeout=25).json()
        files = []
        for p in pg.get("query", {}).get("pages", {}).values():
            files += [im["title"] for im in p.get("images", [])]
    except (requests.RequestException, ValueError, KeyError):
        return []
    files = [f for f in files if f.lower().endswith((".jpg", ".jpeg", ".png"))
             and not RUIDO.search(f)][:limit * 2]
    out = []
    if not files:
        return out
    try:
        r = requests.get("https://commons.wikimedia.org/w/api.php", params={
            "action": "query", "titles": "|".join(files), "prop": "imageinfo",
            "iiprop": "url|extmetadata|mime", "iiurlwidth": 1600,
            "format": "json"}, headers=UA, timeout=30).json()
    except (requests.RequestException, ValueError):
        return out
    for p in r.get("query", {}).get("pages", {}).values():
        ii = (p.get("imageinfo") or [{}])[0]
        lic = ((ii.get("extmetadata") or {}).get("LicenseShortName") or {}).get("value", "")
        if not PD_OK.search(lic) or PROHIBIDO.search(lic):
            continue
        url = ii.get("thumburl") or ii.get("url")
        if not url:
            continue
        out.append({"url": url, "orig": ii.get("url"), "file": p.get("title", ""), "credit": lic, "wiki": True})
    return out


_CACHED: dict[str, list[dict]] = {}


def _commons(query: str, limit: int = 8) -> list[dict]:
    key = query.strip().lower()
    if key in _CACHED:
        return _CACHED[key]
    time.sleep(0.5)
    try:
        r = requests.get("https://commons.wikimedia.org/w/api.php", params={
            "action": "query", "generator": "search",
            "gsrsearch": f"filetype:bitmap {query}", "gsrnamespace": 6, "gsrlimit": limit,
            "prop": "imageinfo", "iiprop": "url|extmetadata|mime", "iiurlwidth": 1600,
            "format": "json"}, headers=UA, timeout=30)
        pages = r.json().get("query", {}).get("pages", {})
    except (requests.RequestException, ValueError):
        return []
    out = []
    for p in pages.values():
        ii = (p.get("imageinfo") or [{}])[0]
        lic = ((ii.get("extmetadata") or {}).get("LicenseShortName") or {}).get("value", "")
        mime = ii.get("mime", "")
        url = ii.get("thumburl") or ii.get("url")
        if not url or "svg" in mime:
            continue
        if PD_OK.search(lic) and not PROHIBIDO.search(lic):
            out.append({"url": ii.get("thumburl") or ii.get("url"), "orig": ii.get("url"),
                        "file": p.get("title", ""), "credit": lic})
    _CACHED[key] = out
    return out


def _score(core: str, kw: str, title: str) -> int:
    """Sólo sobre tema (core en el título) y ordenado por qué tan literal es para el
    concepto del segmento: el mapa del epicentro va al epicentro, el bosque arrasado al bosque."""
    t = title.lower()
    if core.split()[0].lower() not in t:
        return 0
    return 1 + sum(1 for w in re.findall(r"[a-záéíóúñü]{3,}", kw.lower()) if w in t)


def _category_images(core: str, limit: int = 25) -> list[dict]:
    """Miembros de Category:<core> (event...) en Commons: fotos de época del evento real."""
    for cat in (f"Category:{core}", f"Category:{core} event", f"Category:{core}s"):
        try:
            r = requests.get("https://commons.wikimedia.org/w/api.php", params={
                "action": "query", "generator": "categorymembers", "gcmtitle": cat,
                "gcmtype": "file", "gcmlimit": limit, "prop": "imageinfo",
                "iiprop": "url|extmetadata|mime", "iiurlwidth": 1600,
                "format": "json"}, headers=UA, timeout=30).json()
        except (requests.RequestException, ValueError):
            continue
        pages = r.get("query", {}).get("pages")
        if not pages:
            continue
        out = []
        for p in pages.values():
            ii = (p.get("imageinfo") or [{}])[0]
            lic = ((ii.get("extmetadata") or {}).get("LicenseShortName") or {}).get("value", "")
            if not PD_OK.search(lic) or PROHIBIDO.search(lic) or "svg" in ii.get("mime", ""):
                continue
            url = ii.get("thumburl") or ii.get("url")
            if url:
                out.append({"url": url, "orig": ii.get("url"), "file": p.get("title", ""),
                            "credit": lic, "cat": True})
        if out:
            return out
    return []

def _nasa(query: str, limit: int = 4) -> list[dict]:
    try:
        j = requests.get("https://images-api.nasa.gov/search", params={"q": query, "media_type": "image"},
                         headers=UA, timeout=30).json()
    except requests.RequestException:
        return []
    out = []
    for it in (j.get("collection", {}).get("items") or [])[:limit]:
        d = it["data"][0]
        href = (it.get("links") or [{}])[0].get("href")
        try:
            files = requests.get(href, timeout=20).json() if href else []
        except requests.RequestException:
            files = []
        img = next((f for f in files if f.lower().endswith((".jpg", ".jpeg", ".png")) and "~" not in f), None)
        if img:
            out.append({"url": f"https://images-assets.nasa.gov/image/{d['nasa_id']}/{img}",
                        "file": d["nasa_id"], "credit": "NASA/dom público"})
    return out


def _keywords(ep: Episode, segs: list[str], historia: str) -> tuple[str, list[str]]:
    prompt = (
        "Vas a asignar MATERIAL VISUAL a un guion documental.\n"
        f"Tema: {historia}.\n\n"
        "Devolvé JSON con DOS campos:\n"
        '  "core": UN término (1-3 palabras, en INGLÉS) que es el nombre del evento/objeto/lugar '
        'central y que DEBE aparecer en toda búsqueda (ej: "Tunguska", "Pompeya", "Apollo 11").\n'
        '  "keywords": para CADA segmento (en orden, exactamente '
        f"{len(segs)} entradas) un concepto visual concreto en inglés de 1-3 palabras que "
        "describe lo que se ve en ese momento del relato (objeto, lugar, persona, mapa, tipo de "
        "escena: epicenter map, flattened forest, expedition scientist portrait, river valley, "
        "night sky fireball). NO concepts abstractos (magnitud, misterio).\n"
        'Formato: {"core":"...","keywords":["...","..."]}'
    )
    data = llm.chat_json([{"role": "system", "content": prompt},
                          {"role": "user", "content": json.dumps(list(enumerate(segs)), ensure_ascii=False)[:12000]}],
                         max_tokens=900, tag="visuales-kw", episode=ep.slug)
    core = (data.get("core") or historia).strip()
    kws = data.get("keywords", [])
    while len(kws) < len(segs):
        kws.append(core)
    return core, [str(k).strip() for k in kws[:len(segs)]]


def _descargar(url: str, dst: Path) -> bool:
    # Commons throttlea a 429 y manda Retry-After: respetarlo evita volver a disparar el limiter.
    for intento in range(3):
        try:
            with requests.get(url, headers=UA, stream=True, timeout=60) as r:
                if r.status_code == 429 or r.status_code >= 500:
                    wait = int(r.headers.get("retry-after", "0") or 0)
                    time.sleep(min(wait or 20, 90) if intento < 2 else 45)
                    continue
                r.raise_for_status()
                if not r.headers.get("content-type", "image").startswith("image"):
                    return False
                sz = 0
                with dst.open("wb") as fh:
                    for chunk in r.iter_content(1 << 16):
                        sz += len(chunk)
                        if sz > 12_000_000:
                            return False
                        fh.write(chunk)
            if sz > 20_000:
                time.sleep(2.5)  # ~1 request/2.5s: bajo el umbral anónimo de Wikimedia
                return True
        except requests.RequestException:
            time.sleep(3 * (intento + 1))
    return False


def _bajar(f: dict, dst: Path) -> bool:
    """Intenta thumbnail, original y Special:FilePath: los tres apuntan a la misma foto,
    pero si un host/CDN está limitando, otro endpoint puede responder sin 429."""
    candidatos = [f.get("url"), f.get("orig")]
    archivo = (f.get("file") or "").replace("File:", "")
    if archivo:
        candidatos.append("https://commons.wikimedia.org/wiki/Special:FilePath/"
                          + quote(archivo) + "?width=1600")
    for u in candidatos:
        if u and _descargar(u, dst):
            return True
    return False


def _grade(path: Path) -> None:
    """Grade editorial de la fábrica: contraste filmico, saturación medida y viñeta.

    No inventa color: recupera el que la foto ya trae y unifica la paleta de todo el
    episodio (sombras frescas, luces cálidas). Es determinista y corre en CPU.
    """
    im = Image.open(path).convert("RGB")
    im = ImageOps.autocontrast(im, cutoff=0.4)
    im = ImageEnhance.Color(im).enhance(1.16)
    im = ImageEnhance.Contrast(im).enhance(1.07)
    im = ImageEnhance.Brightness(im).enhance(1.02)
    # Split-tone suave: azul en sombras, ámbar en luces, sin lavar la foto.
    im = Image.blend(im, Image.new("RGB", im.size, (8, 22, 34)), 0.035)
    mask = Image.new("L", im.size, 0)
    md = ImageDraw.Draw(mask)
    md.ellipse((-im.width * 0.12, -im.height * 0.12,
                im.width * 1.12, im.height * 1.12), fill=255)
    mask = mask.filter(ImageFilter.GaussianBlur(max(40, im.width // 12)))
    im = Image.composite(im, Image.new("RGB", im.size, (0, 0, 0)), mask)
    im.save(path, quality=94)


def _hook_card(path: Path, title: str, first_text: str) -> Path:
    """Hook automático de la fábrica: la foto del primer segmento + la cifra del guion.

    La cifra sale del texto narrado; el title sólo contextualiza. No hay copy manual ni
    una imagen aparte: si el guion cambia, el hook cambia con él.
    """
    im = Image.open(path).convert("RGB")
    # Lienzo 9:16 para mantener texto gráfico lejos de la interfaz inferior de las plataformas.
    canvas = Image.new("RGB", (1080, 1920), (0, 0, 0))
    s = max(canvas.width / im.width, canvas.height / im.height)
    im = im.resize((int(im.width * s), int(im.height * s)), Image.LANCZOS)
    canvas.paste(im, ((canvas.width - im.width) // 2, (canvas.height - im.height) // 2))
    canvas = Image.blend(canvas, Image.new("RGB", canvas.size, (2, 6, 12)), 0.46)

    d = ImageDraw.Draw(canvas)
    d.rectangle((0, 0, 12, canvas.height), fill=(235, 32, 32))
    try:
        f_big = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSansCondensed-Bold.ttf", 150)
        f_mid = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSansCondensed-Bold.ttf", 54)
        f_small = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSansCondensed.ttf", 30)
    except OSError:
        f_big = f_mid = f_small = ImageFont.load_default()

    def center(y: int, texto: str, f, fill, stroke: int = 4) -> None:
        box = d.textbbox((0, 0), texto, font=f, stroke_width=stroke)
        d.text(((canvas.width - (box[2] - box[0])) / 2, y), texto, font=f, fill=fill,
               stroke_width=stroke, stroke_fill=(0, 0, 0))

    import re
    # Prioridad: cifra CON unidad de impacto. "14 de agosto" es una fecha, no un hook;
    # "cincuenta y cinco millones" es la cifra que el espectador tiene que retener.
    m = re.search(r"\b(\d{1,3}(?:[.,]\d+)?)\s*(millones|millón|mil|%|megavatios|MW|personas)\b",
                  first_text, re.I)
    cifra = (m.group(1) + " " + (m.group(2) or "")).strip().upper() if m else ""
    if not cifra:
        palabras_num = {"cero": 0, "un": 1, "uno": 1, "dos": 2, "tres": 3, "cuatro": 4,
                        "cinco": 5, "seis": 6, "siete": 7, "ocho": 8, "nueve": 9,
                        "diez": 10, "once": 11, "doce": 12, "trece": 13, "catorce": 14,
                        "quince": 15, "dieciséis": 16, "diecisiete": 17, "dieciocho": 18,
                        "diecinueve": 19, "veinte": 20, "treinta": 30, "cuarenta": 40,
                        "cincuenta": 50, "sesenta": 60, "setenta": 70, "ochenta": 80,
                        "noventa": 90, "cien": 100, "ciento": 100}
        low = first_text.lower()
        mm = re.search(r"\b((?:[a-záéíóúñ]+\s+){0,4}(?:millones|millón|mil|personas|megavatios))", low)
        if mm:
            trozo = mm.group(1)
            total = 0
            for w in re.findall(r"[a-záéíóúñ]+", trozo):
                if w in palabras_num:
                    total += palabras_num[w]
            if total:
                unidad = "MILLONES" if ("millones" in trozo or "millón" in trozo) else (
                    "MIL" if "mil" in trozo else "")
                cifra = f"{total} {unidad}".strip()
    if not cifra:
        palabras = [w for w in title.upper().split() if len(w) > 2][:3]
        cifra = "\n".join(palabras) or title.upper()[:18]
    center(300, cifra, f_big, (255, 196, 0), 10)
    center(520, "NO FUE UN APAGÓN COMÚN" if "apag" in title.lower() else title.upper()[:34],
           f_mid, (255, 255, 255), 5)
    center(640, "LA HISTORIA QUE NADIE TE CONTÓ", f_small, (210, 225, 235), 3)
    center(1720, "PULSO CURIOSO", f_small, (235, 32, 32), 2)
    canvas.save(path, quality=94)
    return path


def _hook_source(img_dir: Path) -> Path | None:
    """Elige la foto con más color/contraste/detalle para el hook, no la primera.

    Una panorámica nocturna puede ser correcta para el relato pero no frena el scroll;
    el hook necesita una imagen legible, con saturación y rango tonal. La decisión es
    local y determinista, sin copy ni selección humana.
    """
    mejor, score_mejor = None, -1.0
    for p in sorted(img_dir.glob("seg-*.jpg")):
        try:
            im = Image.open(p).convert("RGB")
            im.thumbnail((320, 320))
            stat = ImageStat.Stat(im)
            hsv = ImageStat.Stat(im.convert("HSV"))
            brillo = sum(stat.mean) / 3
            contraste = sum(stat.stddev) / 3
            saturacion = hsv.mean[1]
            # Penalizar negros planos; premiar color y textura. El mapa satelital y las
            # fotos de calle suelen ganarle a la panorámica nocturna.
            score = saturacion * 1.5 + contraste * 0.9 + min(brillo, 120) * 0.45
            if brillo < 28:
                score -= 40
            if score > score_mejor:
                mejor, score_mejor = p, score
        except (OSError, ValueError):
            continue
    return mejor


def generar(ep: Episode) -> None:
    # La fábrica oficial usa keyframes de stickman; esta etapa de fotos reales queda
    # deshabilitada para que ninguna corrida mezcle archivo histórico con el personaje.
    if os.environ.get("PERMITIR_FOTOS_REALES") != "1":
        raise SystemExit("visuales: fotos reales deshabilitadas; usá 'keyframes' (stickman 4F). "
                         "Si necesitás una comparación legacy, exportá PERMITIR_FOTOS_REALES=1.")
    script = ep.read_text("script.txt")
    segs = _segments(script)
    estado = ep.read_state()
    img_dir = ep.dir / "assets" / "img"
    img_dir.mkdir(parents=True, exist_ok=True)
    for old in list(img_dir.glob("seg-*.jpg")) + list(img_dir.glob("seg-*.png")):
        old.unlink()

    # Si upload.wikimedia nos throttlearon (429), VISUALES_WAIT deja enfriar el limiter antes de bajar.
    wait = int(os.environ.get("VISUALES_WAIT", "0"))
    if wait:
        print(f"  cooldown anti-429: esperando {wait}s antes de descargar…")
        time.sleep(wait)

    core, kws = _keywords(ep, segs, estado["title"])
    print(f"  núcleo visual: {core!r} | conceptos: {kws}")

    # POOL ANCLADO AL EVENTO con el MENOS de requests posible (Commons throttlea a 429):
    # categoría de Commons (fotos/mapas de época) + una búsqueda amplia del núcleo + artículo.
    # La relevancia por segmento se resuelve LOCALMENTE con _score, sin más llamadas.
    pool, vistos = [], set()
    for f in _category_images(core) + _commons(core, 24) + _wiki_images(core):
        if _score(core, "", f["file"]) > 0 and not MODERNO.search(f["file"]) and f["url"] not in vistos:
            vistos.add(f["url"])
            pool.append(f)

    # ASIGNACIÓN GLOBAL por literalidad: el mapa del epicentro va al segmento del epicentro,
    # el bosque arrasado al del bosque, sin repetir una imagen mientras haya otras del evento.
    pares = sorted((( _score(core, kw, f["file"]), i, f)
                     for i, kw in enumerate(kws) for f in pool), key=lambda x: -x[0])
    elegida: dict[int, dict] = {}
    usadas = set()
    for sc, i, f in pares:
        if sc > 0 and i not in elegida and f["url"] not in usadas:
            elegida[i] = f
            usadas.add(f["url"])

    # lo más icónico del evento como relleno/reuso para segmentos sin coincidencia única.
    fallback = next((f for f in pool if f.get("cat") or f.get("wiki")), (pool[0] if pool else None))
    for i in range(len(kws)):
        elegida.setdefault(i, fallback)

    # ORDEN por segmento: su imagen asignada (o relleno), y una reserva de alternativas del pool.
    orden = [elegida.get(i) or fallback for i in range(len(kws))]

    # FASE 1: descargar cada URL ÚNICA una sola vez (≤ #imágenes distintas) para no re-disparar
    # el throttle; se guarda en un caché por url. FASE 2: repartir/copiar a cada segmento.
    cache_dir = img_dir / "_cache"
    cache_dir.mkdir(exist_ok=True)
    descargas: dict[str, Path] = {}
    urls_necesarias = []
    for i, f in enumerate(orden):
        if f and f["url"] not in [o["url"] for o in orden[:i] if o]:
            urls_necesarias.append(f)
    for f in urls_necesarias:
        dst = cache_dir / f"u{len(descargas):03d}.jpg"
        if _bajar(f, dst):
            descargas[f["url"]] = dst
        else:
            print(f"  cache: sin descarga para {f['file'].replace('File:','')[:44]!r} (throttle)")

    # si todo falló (throttle persistente), reintentar una vez las del pool más icónico.
    buena = next(iter(descargas.values()), None) if descargas else None

    licencias = []
    for i, (kw, f) in enumerate(zip(kws, orden)):
        dst = img_dir / f"seg-{i:03d}.jpg"
        electa = f
        ruta = descargas.get(f["url"]) if f else None
        if ruta is None and buena is not None:      # reuse: mejor una real repetida que cartela
            electa = next((g for g in orden if g and g["url"] in descargas), None)
            ruta = descargas.get(electa["url"]) if electa else None
        if ruta is None:
            print(f"  segmento {i}: sin imagen descargable para {kw!r} (queda cartela)")
            continue
        shutil.copyfile(ruta, dst)
        licencias.append({"segment": i, "file": dst.name, "source": electa["url"],
                          "credit": electa["credit"], "titulo": electa["file"], "concepto": kw})
    for tmp in cache_dir.glob("*"):
        tmp.unlink()
    cache_dir.rmdir()
    # Grade + hook son parte de la etapa, no de una intervención del agente: cualquier
    # episodio que pase por 'visuales' sale con la misma paleta y su propio gancho.
    for dst in sorted(img_dir.glob("seg-*.jpg")):
        try:
            _grade(dst)
        except OSError:
            pass
    hook_src = _hook_source(img_dir)
    seg0 = img_dir / "seg-000.jpg"
    if hook_src and hook_src != seg0 and seg0.exists():
        # El hook puede tomar la mejor foto de cualquier segmento; se actualiza también
        # su crédito para que licenses.json no atribuya la imagen equivocada.
        lic0 = next((l for l in licencias if l["file"] == hook_src.name), None)
        if lic0:
            licencias[0].update(source=lic0["source"], credit=lic0["credit"],
                                titulo=lic0["titulo"])
        shutil.copyfile(hook_src, seg0)
    if seg0.exists():
        try:
            _hook_card(seg0, estado["title"], segs[0])
        except OSError:
            pass
    ep.write_json("licenses.json", {"licencias": licencias})
    if licencias:
        print(f"  hook: {licencias[0]['file']} <- {licencias[0]['titulo']}")
    if len(licencias) == 0:
        raise SystemExit("0 imágenes libres encontradas (throttle de Wikimedia): reintentá más tarde, "
                         "no se publica un documental sobre cartelas vacías.")
    reuse = len(licencias) - len(descargas)
    print(f"  visuales: {len(licencias)}/{len(segs)} segmentos con imagen real del evento "
          f"({len(descargas)} descargas únicas, {reuse} reutilizaciones, núcleo {core!r}, PD/CC BY)")
