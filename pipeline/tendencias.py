"""Investigacion de tendencias con numeros REALES y trazables.

Regla del modulo: ninguna cifra entra sin `procedencia` (URL + fecha de lectura). Lo que no
se puede medir desde esta maquina se registra como null en vez de inventarse un numero.

Fuentes verificadas alcanzables SIN API key (medidas 2026-10-29):
  - Wikimedia Pageviews REST: top diario de es/en wikipedia (1000 articulos, vistas reales).
  - Wikimedia Pageviews por articulo: serie diaria -> distingue pico pasajero de demanda estable.
  - Hacker News (Algolia): puntos y comentarios reales, recientes.
  - YouTube RSS por channel_id: titulos, vistas y fecha de publicacion de los ultimos 15 videos.
  - DuckDuckGo lite/html: cobertura del tema (ya la usa stages/descubrir.py).
No funciona aca: busqueda de YouTube por HTML (devuelve shell sin datos) y google trends API.
"""
from __future__ import annotations

import json
import re
import statistics
import time
from datetime import date, datetime, timedelta
from urllib.parse import quote

import requests

from . import config

UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120 Safari/537.36"}
STATE = config.STATE / "tendencias.json"
OMNIBUS = config.REGISTRY / "oportunidades.jsonl"


def _get(url: str, params=None, timeout: int = 25, intentos: int = 3):
    """Un solo punto de red, con reintento: las APIs de métricas fallan a ráfagas y un
    fallo transitorio no debe borrarse una señal de demanda real (devuelve (dato, meta|motivo))."""
    ultimo = "sin intentos"
    for n in range(intentos if url.startswith("https://www.youtube.com") else 2):
        try:
            r = requests.get(url, params=params, headers=UA, timeout=timeout)
            if r.status_code < 400:
                dato = r.json() if "json" in r.headers.get("content-type", "") else r.text
                return dato, {"url": r.url, "fetched": datetime.utcnow().isoformat() + "Z"}
            ultimo = f"HTTP {r.status_code}"
            if r.status_code == 429:
                time.sleep(min(30, 2 ** (n + 2)))
        except requests.RequestException as exc:
            ultimo = f"red: {exc.__class__.__name__}"
        time.sleep(0.6 * (n + 1))
    return None, ultimo


def _proc(url: str) -> dict:
    return {"procedencia": url, "leido_el": datetime.utcnow().isoformat() + "Z"}


# ------------------------------------------------------------------ Wikimedia
def top_wikimedia(proyecto: str = "es.wikipedia", dias: int = 3) -> list[dict]:
    """Los articulos mas vistos del dia: demanda real del mercado hispanohablante."""
    out, errs = [], []
    for d in range(1, dias + 1):
        dia = date.today() - timedelta(days=d)
        url = (f"https://wikimedia.org/api/rest_v1/metrics/pageviews/top/"
               f"{proyecto}/all-access/{dia:%Y/%m/%d}")
        data, meta = _get(url)
        if not isinstance(data, dict):
            errs.append(f"{dia}: {meta}")
            continue
        arts = data["items"][0]["articles"][:300]
        for a in arts:
            out.append({"tema": a["article"].replace("_", " "), "vistas": a["views"],
                        "rank": a["rank"], "dia": str(dia), "proyecto": proyecto,
                        **{"procedencia": url, "leido_el": datetime.utcnow().isoformat() + "Z"}})
    if errs:
        print(f"  tendencias: {len(errs)} dias sin top ({errs[0]})")
    return out


def historial(articulo: str, proyecto: str = "es.wikipedia", dias: int = 60) -> dict | None:
    """Serie diaria de vistas de un articulo -> clasifica pico pasajero vs demanda sostenible."""
    fin = datetime.utcnow()
    url = ("https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article/"
           f"{proyecto}/all-access/user/{quote(articulo, safe='')}/daily/"
           f"{(fin - timedelta(days=dias)):%Y%m%d00}/{fin:%Y%m%d00}")
    data, meta = _get(url)
    if not isinstance(data, dict) or not data.get("items"):
        return None
    # forma real de la respuesta: items -> [{timestamp, views}, ...]
    plano: list[tuple] = []
    for it in data["items"]:
        if "views" in it:
            plano.append((it["timestamp"], it["views"]))
        elif "articles" in it:
            plano = [(a["timestamp"], a["views"]) for a in it["articles"]]
    if len(plano) < 10:
        return None
    valores = [v for _, v in plano]
    ultimos, previos = valores[-7:], valores[-28:-7] or valores[:-7]
    base = statistics.median(previos) or 1
    ratio = round(statistics.mean(ultimos) / base, 2)
    if ratio >= 4:
        tipo = "pico_pasajero"      # noticia que se apaga: sirve para reaccionar, no para la serie
    elif ratio >= 1.5:
        tipo = "en_ascenso"
    elif statistics.median(valores) >= 500:
        tipo = "demanda_estable"    # evergreen: columna vertebral del canal
    else:
        tipo = "residual"
    return {"articulo": articulo, "ratio_7v28": ratio, "tipo": tipo,
            "vistas_promedio_diaria": round(statistics.mean(ultimos), 1),
            "dias_medidos": len(valores), **_proc(url)}


# ------------------------------------------------------------------ Hacker News
def hacker_news(puntos: int = 80) -> list[dict]:
    """Historias recientes con puntos reales: senal temprana de curiosidad tecnica."""
    desde = int((datetime.utcnow() - timedelta(days=14)).timestamp())
    url = "https://hn.algolia.com/api/v1/search_by_date"
    data, meta = _get(url, params={
        "tags": "story", "hitsPerPage": 40,
        "numericFilters": f"points>={puntos},created_at_i>={desde}"})
    if not isinstance(data, dict):
        print(f"  tendencias: HN no disponible ({meta})")
        return []
    out = []
    for h in data.get("hits", []):
        titulo = h.get("title") or ""
        if _fuera_de_nicho(titulo) or _categoria(titulo) is None:
            continue  # sòlo lo que es curiosidad: el resto es agenda tech
        out.append({"tema": titulo, "vistas": h.get("points"), "comentarios": h.get("num_comments"),
                    "fuente": "hackernews", "url": h.get("url") or f"https://news.ycombinator.com/item?id={h['objectID']}",
                    "score": round(min(1.0, (h.get("points") or 0) / 800), 3),
                    **_proc(url)})
    return out


# ------------------------------------------------------------------ YouTube (competencia)
def canal_youtube(canal: str) -> dict | None:
    """RSS publico de un canal: titulos, vistas y fecha reales de sus ultimos 15 videos.

    `canal` acepta channel_id (UC...) o @handle. Sin API key: no hay duraciones ni retention,
    y eso se registra como null, no se estima.
    """
    cid = canal if canal.startswith("UC") else _channel_id(canal)
    if not cid:
        return None
    url = f"https://www.youtube.com/feeds/videos.xml?channel_id={cid}"
    texto, meta = _get(url)
    if not isinstance(texto, str):
        print(f"  tendencias: RSS {canal} no disponible ({meta})")
        return None
    nombre = (re.search(r"<name>(.*?)</name>", texto) or [None, canal])[1]
    videos = []
    for e in re.findall(r"<entry>(.*?)</entry>", texto, re.S):
        def cap(pat):
            m = re.search(pat, e, re.S)
            return m.group(1) if m else None
        pub = cap(r"<published>(.*?)</published>")
        vistas = cap(r'views="(\d+)"')
        dias = max(0.5, (datetime.utcnow() - datetime.fromisoformat((pub or "")[:19])
                         ).total_seconds() / 86400) if pub else None
        videos.append({"titulo": (cap(r"<media:title>(.*?)</media:title>") or "").strip(),
                       "vistas": int(vistas) if vistas else None,
                       "publicado": pub,
                       "vistas_por_dia": round(int(vistas) / dias, 1) if vistas and dias else None,
                       "duracion_s": None})  # no expuesto por RSS: queda null a proposito
    return {"channel_id": cid, "canal": nombre, "videos": videos, **_proc(url)}


def _channel_id(handle: str) -> str | None:
    texto, _ = _get(f"https://www.youtube.com/@{handle.lstrip('@')}/about")
    if not isinstance(texto, str):
        return None
    m = re.search(r'"externalId":"(UC[^"]+)"', texto)
    return m.group(1) if m else None


def patrones_narrativos(videos: list[dict]) -> dict:
    """Que hacen los que corren: longitud del titulo, numero, pregunta, primera persona."""
    vivos = [v for v in videos if v.get("vistas")]
    if not vivos:
        return {"muestra": 0}
    titulos = [v["titulo"] for v in vivos]
    promedio = statistics.mean(v["vistas"] for v in vivos)
    con_numero = [t for t in titulos if re.search(r"\b\d+\b", t)]
    con_pregunta = [t for t in titulos if "?" in t]
    por_estructura = {}
    for v in vivos:
        t = v["titulo"]
        clave = ("numero" if re.search(r"\b\d+\b", t) else
                 "pregunta" if "?" in t else
                 "condicional" if re.search(r"\b(si |what if|que pasa)", t.lower()) else "afirmativo")
        por_estructura.setdefault(clave, []).append(v["vistas"])
    return {
        "muestra": len(vivos),
        "vistas_promedio": round(promedio),
        "titulo_palabras_mediano": statistics.median(len(t.split()) for t in titulos),
        "con_numero_pct": round(100 * len(con_numero) / len(titulos)),
        "con_pregunta_pct": round(100 * len(con_pregunta) / len(titulos)),
        "mejor_estructura": max(((k, round(statistics.mean(v))) for k, v in por_estructura.items()),
                                key=lambda x: x[1], default=(None, None))[0],
        "top_titulos": [v["titulo"][:80] for v in sorted(vivos, key=lambda x: -x["vistas"])[:5]],
    }


# ------------------------------------------------------------------ sintesis
import math

from . import nichos
from .nichos import categoria_de as _categoria

_NOTICIA = re.compile(r"\b(20\d\d)\b|elecciones|seleccion|fallecio|muerte de|clasico|final de|"
                      r"super bowl|world cup|copa|liga|partido|fútbol|del 11 de noviembre", re.I)


def _fuera_de_nicho(tema: str) -> bool:
    """Paginas de proyecto (Wikipedia:...), efemerides y agenda deportiva/politica no son nicho."""
    return ":" in tema or bool(_NOTICIA.search(tema))


def _demanda(vistas_diarias: float | None) -> float:
    """Escala log de vistas promedio diarias: 100/d -> .50, 1000/d -> .75, 10000/d -> 1.0."""
    if not vistas_diarias:
        return 0.0
    return round(min(1.0, math.log10(max(1.0, vistas_diarias) + 1) / 4 * 1.34), 3)


def busqueda_wiki(consulta: str, proyecto: str = "es.wikipedia", limite: int = 6) -> list[str]:
    data, _ = _get(f"https://{proyecto}.org/w/api.php", params={
        "action": "query", "list": "search", "srsearch": consulta, "srlimit": limite, "format": "json"})
    if not isinstance(data, dict):
        return []
    return [h["title"] for h in data.get("query", {}).get("search", [])]


def demanda_semillas(max_articulos: int = 28) -> list[dict]:
    """Demanda REAL de nuestro propio nicho: mide las paginas que devuelven las semillas.

    El top diario de Wikipedia esta dominated por celebridades y agenda; para elegir serie hay
    que medir los articulos de curiosidad, no lo que hoy esta de moda.
    """
    out: list[dict] = []
    vistos: set[str] = set()
    for cat, cfg in nichos.CATEGORIAS.items():
        for semilla in nichos.BUSQUEDAS[cat]:
            for titulo in busqueda_wiki(semilla)[:4]:
                if titulo in vistos or _fuera_de_nicho(titulo):
                    continue
                vistos.add(titulo)
                hist = historial(titulo)
                if not hist:
                    continue
                out.append({"tema": titulo.replace("_", " "), "categoria": cat,
                            "tipo_senal": "pageviews_wikimedia_semilla", "mercado": "hispano",
                            "vistas": hist["vistas_promedio_diaria"], "score": _demanda(hist["vistas_promedio_diaria"]),
                            "sostenibilidad": hist["tipo"], "ratio_7v28": hist["ratio_7v28"],
                            "procedencia": hist["procedencia"], "leido_el": hist["leido_el"]})
                if len(out) >= max_articulos:
                    return out
    return out


def detectar(refresh: bool = True, proyectos: tuple = ("es.wikipedia", "en.wikipedia")) -> dict:
    """Una pasada: junta senales, clasifica pasajero vs sostenible y escribe el tablero."""
    senales: list[dict] = []
    for proyecto in proyectos:
        mercado = "hispano" if proyecto.startswith("es") else "global"
        for s in top_wikimedia(proyecto, dias=2):
            if _fuera_de_nicho(s["tema"]) or _categoria(s["tema"]) is None:
                continue
            senales.append({"tema": s["tema"], "tipo_senal": "pageviews_wikimedia_top", "mercado": mercado,
                            "vistas": s["vistas"], "score": round(max(0.0, 1 - s["rank"] / 300), 3),
                            "procedencia": s["procedencia"], "leido_el": s["leido_el"]})
    senales += [{"tema": s["tema"], "tipo_senal": "hackernews", "mercado": "global",
                 "vistas": s["vistas"], "score": s["score"], "procedencia": s["procedencia"],
                 "leido_el": s["leido_el"]} for s in hacker_news()]
    senales += demanda_semillas()

    candidatos: dict[str, dict] = {}
    for s in senales:
        clave = re.sub(r"\s+", " ", s["tema"].lower().strip())
        if len(clave) < 6:
            continue
        c = candidatos.setdefault(clave, {"tema": s["tema"], "senales": [], "score_max": 0.0,
                                          "mercados": set(), "tipos": set(), "sostenibilidad": None,
                                          "vistas_promedio_diaria": None, "categoria": None})
        c["senales"].append({k: s[k] for k in ("tipo_senal", "mercado", "vistas", "score",
                                               "procedencia", "leido_el") if k in s})
        c["score_max"] = max(c["score_max"], s["score"])
        c["mercados"].add(s.get("mercado", "?"))
        c["tipos"].add(s.get("tipo_senal", "?"))
        c["sostenibilidad"] = c["sostenibilidad"] or s.get("sostenibilidad")
        c["vistas_promedio_diaria"] = c["vistas_promedio_diaria"] or s.get("vistas")
        c["categoria"] = c["categoria"] or _categoria(s["tema"])

    oportunidades = []
    for clave, c in sorted(candidatos.items(), key=lambda x: -x[1]["score_max"])[:60]:
        if not c["categoria"]:
            continue  # fuera de nicho: no es curiosidad, es agenda
        tipo = c["sostenibilidad"] or "sin_serie_de_60_dias"
        if tipo == "pico_pasajero":
            c["score_max"] *= 0.6  # la efemeride no sostiene una serie: se penaliza, no se esconde
        oportunidades.append({
            "tema": c["tema"], "categoria": c["categoria"], "score": round(c["score_max"], 3),
            "sostenibilidad": tipo, "vistas_promedio_diaria": c["vistas_promedio_diaria"],
            "mercados": sorted(c["mercados"]), "tipos": sorted(c["tipos"]),
            "procedencia": [s["procedencia"] for s in c["senales"]][:3],
        })
    tablero = {"actualizado": datetime.utcnow().isoformat() + "Z",
               "senales": len(senales), "fuente_no_disponible": ["youtube_search_html", "google_trends"],
               "oportunidades": oportunidades}
    if refresh:
        config.STATE.mkdir(parents=True, exist_ok=True)
        STATE.write_text(json.dumps(tablero, indent=2, ensure_ascii=False), encoding="utf-8")
        OMNIBUS.parent.mkdir(parents=True, exist_ok=True)
        with OMNIBUS.open("a", encoding="utf-8") as fh:
            for o in oportunidades[:15]:
                fh.write(json.dumps(o, ensure_ascii=False) + "\n")
    print(f"  tendencias: {len(senales)} senales reales -> {len(oportunidades)} oportunidades en nicho")
    return tablero


# ------------------------------------------------------------------ competencia real
CANALES = config.REGISTRY / "canales.json"


def canales_activos() -> list[str]:
    if CANALES.exists():
        return json.loads(CANALES.read_text(encoding="utf-8")).get("canales", [])
    return []


def competencia(canales: list[str] | None = None) -> dict:
    """Retablero de canales de referencia: vistas/dia reales por video y patrones de titulo.

    Se usa SOLO para aprender la formula (estructura, longitud de titulo, formato). Los guiones
    ajenos no se leen ni se copian: el RSS expone titulo, vistas y fecha, nada mas.
    """
    canales = canales or canales_activos()
    if not canales:
        return {"canales": [], "nota": "registry/canales.json vacio: nada que medir"}
    informe = []
    for handle in canales:
        c = canal_youtube(handle)
        if not c:
            informe.append({"canal": handle, "error": "no resuelve channel_id o RSS no disponible"})
            continue
        velocities = [v["vistas_por_dia"] for v in c["videos"] if v.get("vistas_por_dia")]
        informe.append({"canal": c["canal"], "channel_id": c["channel_id"],
                        "videos": len(c["videos"]),
                        "vistas_total_muestra": sum(v["vistas"] or 0 for v in c["videos"]),
                        "vistas_por_dia_mediana": (round(statistics.median(velocities)) if velocities else None),
                        "patrones": patrones_narrativos(c["videos"]),
                        "procedencia": c["procedencia"], "leido_el": c["leido_el"]})
    tab = {"actualizado": datetime.utcnow().isoformat() + "Z", "canales": informe}
    config.REGISTRY.mkdir(parents=True, exist_ok=True)
    (config.REGISTRY / "competencia.json").write_text(
        json.dumps(tab, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"  competencia: {len(informe)} canales medidos con vistas reales")
    return tab
