"""Collage layer: integra fotos/imágenes reales como recortes de "papel" dentro del master.

Dos comandos, por ciclo de aprobación humana obligatorio:

  pipeline.run collage-propuesto <slug>   -> LLM lee guion y propone entidades
  pipeline.run collage-aprobar <slug>     -> marca aprobadas las propuestas (doc/decision del dueño)
  pipeline.run collage-render <slug>      -> compone el collage en el master

Contrato:
  - Sólo se incrusta lo que el dueño aprueba en `artifacts/collage_layer.json`.
  - Wikimedia Commons API elige candidatos; filtros estrictos de licencia.
  - Si una imagen no encuentra hit razonable se DESCARTA silenciosamente.
  - El collage NO repunta la narración ni los keyframes; se superpone al master.
  - Si falla, se loguea warning y el video sigue saliendo igual que antes (no-op total).
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from pathlib import Path
from typing import Any

import requests

from .. import config, llm
from ..episode import Episode

# ---------------------------------------------------------------- radios de licencia
LICENCIA_OK = ("Public domain", "CC0", "CC BY", "CC BY-SA", "CC BY 2.0", "CC BY-SA 2.0",
               "CC BY 3.0", "CC BY-SA 3.0", "CC BY 4.0", "CC BY-SA 4.0", "FAL")
LICENCIA_MALO = ("Fair use", "GFDL")


def _query_hash(q: str, n: int = 12) -> str:
    return hashlib.sha256(q.encode("utf-8")).hexdigest()[:n]


def _wikimedia_search(query: str, ns: int = 6, max_results: int = 12) -> list[dict[str, Any]]:
    """Busca en Wikimedia Commons sólo archivos; filtra por licencia generosa."""
    url = "https://commons.wikimedia.org/w/api.php"
    params = {
        "action": "query", "generator": "search", "gsrsearch": query,
        "gsrnamespace": ns, "gsrlimit": max_results,
        "prop": "imageinfo", "iiprop": "url|extmetadata|size",
        "iiurlwidth": 1200, "format": "json", "formatversion": 2,
    }
    try:
        r = requests.get(url, params=params,
                         headers={"User-Agent": "PulsoCurioso/1.0 (contact mediastudio)"},
                         timeout=25)
        if r.status_code != 200:
            return []
        pages = r.json().get("query", {}).get("pages", [])
    except requests.RequestException:
        return []
    out: list[dict[str, Any]] = []
    for p in pages:
        title = p.get("title", "")
        for ii in (p.get("imageinfo") or []):
            ext = ii.get("extmetadata") or {}
            lic = (ext.get("LicenseShortName", {}).get("value") or "").strip()
            url_full = ii.get("url")
            if not lic or any(lic.lower().startswith(b.lower()) for b in LICENCIA_MALO):
                continue
            if LICENCIA_OK and not any(lic.lower().startswith(ok.lower())
                                       for ok in LICENCIA_OK):
                continue
            out.append({
                "title": title,
                "license": lic,
                "url": url_full,
                "width": int(ii.get("width") or 0),
                "height": int(ii.get("height") or 0),
                "source": "wikimedia",
            })
    return out


def _primeras_palabras(s: str, n: int = 30) -> str:
    return " ".join(s.split()[:n]) + ("…" if len(s.split()) > n else "")


def _normalizar_file(t: str) -> str:
    return re.sub(r"^File:\s*", "", t).strip()


_LOCAL_PROMPT = (
    "Auditoria de entidades visuales de este guion de documental:\n\n"
    "# Guion\n{script}\n\n"
    "# Beatmap de tiempos (segundos)\n{beats}\n\n"
    "Para cada ENTIDAD con cara o ubicación física que le dé al espectador contexto sobre "
    "QUIÉNES/QUÉ hablamos (personajes públicos, lugares, momentos icónicos), hacé UNA fila "
    "con: query de búsqueda para Wikimedia Commons, tipo, tiempo de aparición (segundos), "
    "duración (segundos), posición (arriba/abajo), razón corta.\n"
    "Reglas estrictas:\n"
    "- Solo personajes/lugares/objetos con imágenes de libre uso en Commons.\n"
    "- NO inventes; si hay duda, no propongas.\n"
    "- Máx 4 recortes total en todo el video.\n"
    "Devolvé SOLO JSON: {{\"recortes\":[{{\"query\":\"...\",\"tipo\":\"...\",\"start_s\":a,\"dur_s\":b,\"posicion\":\"arriba\",\"razon\":\"...\"}}, ...]}}"
)


def proponer(ep: Episode) -> dict:
    """Propone recortes vía LLM; no toca el master. Devuelve el dict y lo guarda en artifacts."""
    script = ep.read_text("script.txt")
    beats_json = ep.read_text("beats.json") if (ep.artifacts / "beats.json").exists() else ""
    beats_str = "n/d"
    if beats_json and "beats" in beats_json:
        try:
            bs = json.loads(beats_json)["beats"]
            beats_str = "\n".join(f"  {b['t0']:.1f}s i={b['i']}: {b['texto'][:60]}"
                                  for b in bs[:80])
        except (json.JSONDecodeError, KeyError):
            pass
    prompt = _LOCAL_PROMPT.format(script=script, beats=beats_str)
    try:
        raw = llm.chat([{"role": "user", "content": prompt}],
                       max_tokens=900, tag="cutout-propuesta", episode=ep.slug)
    except Exception as exc:  # noqa: BLE001
        (ep.artifacts / "cutout_propuesta_error.txt").write_text(str(exc), encoding="utf-8")
        return {"recortes": [], "error": str(exc)}
    m = re.search(r"\{.*\}|\[.*\]", raw, re.S)
    recortes: list[dict[str, Any]] = []
    if m:
        try:
            parsed = json.loads(m.group(0))
            recortes = parsed.get("recortes", parsed if isinstance(parsed, list) else [])
        except json.JSONDecodeError:
            recortes = []
    # filtrar recortes sin query razonable
    validos = [c for c in recortes
               if isinstance(c, dict) and c.get("query") and str(c["query"]).strip()]
    out = {"recortes": validos, "query_ts": time.strftime("%Y-%m-%dT%H:%M:%S")}
    (ep.artifacts / "cutout_propuesta.json").write_text(
        json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    return out


def buscar_y_bajar(ep: Episode, confirmado: dict[str, Any]) -> list[dict]:
    """Para cada recorte confirmado, busca en Commons candidatos y descarga el mejor."""
    if not confirmado.get("recortes"):
        return []
    recs: list[dict] = []
    for rec in confirmado["recortes"]:
        query = str(rec.get("query", "")).strip()
        if not query:
            continue
        hits = _wikimedia_search(query, max_results=20)
        if not hits:
            recs.append({**rec, "estado": "sin_resultados"})
            continue
        # mejor hit: mayor resolución con licencia saneada
        hits.sort(key=lambda h: h["width"] * h["height"], reverse=True)
        best = hits[0]
        out = ep.dir / "assets" / "cutouts"
        out.mkdir(parents=True, exist_ok=True)
        destino = out / f"{_query_hash(query)}.{best['url'].rsplit('.', 1)[-1][:6]}"
        if destino.exists() and destino.stat().st_size > 8000:
            print(f"  cutout cache: {destino.name}")
            rec = {**rec, "estado": "ok", "archivo_local": str(destino),
                   **best}
            recs.append(rec)
            continue
        try:
            r = requests.get(best["url"],
                             headers={"User-Agent": "PulsoCurioso/1.0"},
                             timeout=120, stream=True)
            if r.status_code != 200:
                recs.append({**rec, "estado": f"http_{r.status_code}"})
                continue
            destino.write_bytes(r.content)
        except requests.RequestException as exc:
            recs.append({**rec, "estado": f"error_descarga:{exc}"})
            continue
        rec = {**rec, "estado": "ok", "archivo_local": str(destino),
               "query": query, **best}
        recs.append(rec)
    ep.write_json("collage_layer.json", {"recortes": recs,
                                          "fecha": time.strftime("%Y-%m-%dT%H:%M:%S")})
    return recs
