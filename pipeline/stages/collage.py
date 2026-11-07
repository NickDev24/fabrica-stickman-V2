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
import subprocess
import time
from pathlib import Path
from typing import Any

import requests

from .. import config, cutout, llm
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
    for intento in range(2):
        try:
            r = requests.get(url, params=params,
                             headers={"User-Agent": "PulsoCurioso/1.0 (contact mediastudio)"},
                             timeout=25)
            if r.status_code == 429 and intento == 0:
                time.sleep(3)   # rate limit momentáneo de Commons: un re-intento y listo
                continue
            if r.status_code != 200:
                return []
            pages = r.json().get("query", {}).get("pages", [])
            break
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


def aprobar(ep: Episode, indices: list[int] | None = None) -> dict:
    """Aprobación del dueño: baja/recicla las imágenes de la propuesta y marca qué entra.

    `indices` vacío = todos los recortes viables. Cada imagen baja UNA vez y queda en
    assets/cutouts con su licencia registrada en collage_layer.json (dinero real: cero).
    """
    propuesta = ep.read_json("cutout_propuesta.json") or {}
    recs = buscar_y_bajar(ep, propuesta)
    sel = {int(i) for i in (indices or range(len(recs)))}
    for j, r in enumerate(recs):
        r["aprobado"] = j in sel
    ep.write_json("collage_layer.json", {"recortes": recs,
                                          "fecha": time.strftime("%Y-%m-%d %H:%M:%S")})
    ok = sum(1 for r in recs if r.get("aprobado") and str(r.get("estado", "")).startswith("ok"))
    print(f"  collage: {ok}/{len(recs)} recortes aprobados con imagen local lista")
    return {"recortes": recs, "aprobados": ok}


# mapeo tipo (LLM) → tema de encuadre (cutout.procesar_recorte) → ancho/banda en pantalla
_TEMA = {"personaje": "persona", "persona": "persona", "gente": "persona",
         "retrato": "persona", "documento": "documento", "carta": "documento",
         "papel": "documento", "lugar": "lugar", "edificio": "lugar", "escena": "lugar",
         "objeto": "objeto", "estatua": "objeto", "artefacto": "objeto"}
_ANCHO = {"persona": 320, "documento": 430, "lugar": 460, "objeto": 290}


def render(ep: Episode) -> Path | None:
    """Compone los recortes aprobados sobre el master → renders/<slug>-collage.mp4.

    Colocación que respeta la escena stickman: banda superior (y=130) o tercio inferior
    (y=690, zona baja segura de la plataforma), siempre AL LADO del centro para no
    tapar al personaje principal. Idempotente: si el collage ya está renderizado y
    collage_layer.json no cambió, no re-codifica.
    """
    layer = ep.read_json("collage_layer.json") or {}
    recs = [r for r in layer.get("recortes", [])
            if r.get("aprobado") and str(r.get("estado", "")).startswith("ok")
            and r.get("archivo_local")]
    if not recs:
        print("  collage: no hay recortes aprobados — no-op (el master queda igual)")
        return None
    master = ep.dir / "renders" / f"{ep.slug}-keyframe.mp4"
    if not master.exists():
        raise SystemExit("collage: falta el master (corré 'keyframes' primero)")
    total = json.loads(subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json",
         str(master)], capture_output=True, text=True).stdout)["format"]["duration"]
    overlays = []
    for j, r in enumerate(recs):
        tema = _TEMA.get(str(r.get("tipo", "personaje")).lower(), "persona")
        src = Path(r["archivo_local"])
        png = cutout.procesar_recorte(src, src.with_suffix(".paper.png"), tema=tema)
        w = min(int(r.get("w", 0)) or _ANCHO[tema], 300)
        # banda superior compacta al costado de la cabeza del stickman (alternando
        # lado por recorte); el dueño puede afinar x/y/w por recorte en collage_layer.json
        if str(r.get("posicion", "arriba")) == "abajo":
            x, y = (720 - w - 28), 660   # tercio inferior, fuera del área de controles
        else:
            lado_izq = j % 2 == 0
            x = 28 if lado_izq else (720 - w - 28)
            y = 64
        x = int(r.get("x", x)); y = int(r.get("y", y)); w = int(r.get("w", w))
        dur = max(2.0, min(float(r.get("dur_s", 5.0)), 8.0))
        t0 = max(0.0, min(float(r.get("start_s", 0.0)), float(total) - dur))
        overlays.append({"png": png, "t_start": round(t0, 2),
                         "t_end": round(t0 + dur, 2), "x": x, "y": y, "w": w})
    salida = cutout.aplicar_cutouts(ep, master, overlays)
    print(f"  collage: {len(overlays)} recortes compuestos -> {salida.name} "
          f"(licencias en collage_layer.json)")
    return salida


def buscar_y_bajar(ep: Episode, confirmado: dict[str, Any]) -> list[dict]:
    """Para cada recorte confirmado, busca en Commons candidatos y descarga el mejor."""
    if not confirmado.get("recortes"):
        return []
    recs: list[dict] = []
    for rec in confirmado["recortes"]:
        query = str(rec.get("query", "")).strip()
        if not query:
            continue
        out = ep.dir / "assets" / "cutouts"
        out.mkdir(parents=True, exist_ok=True)
        # 1) reciclaje local PRIMERO (cero red, cero coste): si el dueño ya preparó
        #    el archivo (archivo_local_hint) y existe, no se busca en Commons.
        hint = str(rec.get("archivo_local_hint", "")).strip()
        if hint:
            local = out / hint
            if local.exists() and local.stat().st_size > 8000:
                recs.append({**rec, "estado": "ok_reciclado", "archivo_local": str(local),
                             "license": "PD (archivo local del episodio)",
                             "title": local.stem, "width": 0, "height": 0})
                continue
        hits = _wikimedia_search(query, max_results=20)
        if not hits:
            recs.append({**rec, "estado": "sin_resultados"})
            continue
        # mejor hit: mayor resolución con licencia saneada
        hits.sort(key=lambda h: h["width"] * h["height"], reverse=True)
        best = hits[0]
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
