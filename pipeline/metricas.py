"""Ingesta de métricas REALES de cada episodio publicado -> state/metricas.jsonl.

Sin este archivo no existe aprendizaje posible: factory/metrics/retention_loop.json lo
dice y pipeline/nichos.py:7 cita un `pipeline.experimentos` que nunca existió. Acá está
el lector que faltaba, hablando con Zernio (los endpoints están en pipeline/zernio.py).

Regla de oro: un dato que la API todavía no tiene se guarda como null con su motivo
(`sincronia`), nunca como 0. Aprender de un cero inventado es peor que no aprender.
"""
from __future__ import annotations

import json
import statistics
from datetime import datetime, timezone

import requests

from . import config, zernio

METRICAS = config.STATE / "metricas.jsonl"
RUTA_LOOP = config.ROOT / "factory" / "metrics" / "retention_loop.json"


def _hoy() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _campos_config() -> list[str]:
    """Los campos que la config del loop pide medir (fuente de verdad, no este archivo)."""
    try:
        datos = json.loads(RUTA_LOOP.read_text(encoding="utf-8"))
        return list(datos["ingesta_minima_viable"]["campos"])
    except (OSError, KeyError, json.JSONDecodeError):
        return []


def _ratio(valor) -> float | None:
    """Normaliza a 0-1: los proveedores mandan porcentajes (37.4) o fracciones (0.374)."""
    if not isinstance(valor, (int, float)):
        return None
    return round(valor / 100.0, 4) if valor > 1.0 else round(float(valor), 4)


def _puntos(curva) -> list[list[float]]:
    """Curva compacta [[ratio_tiempo, ratio_visto], ...] con máximo 30 puntos."""
    if not isinstance(curva, list):
        return []
    out = []
    for p in curva:
        if not isinstance(p, dict):
            continue
        t = p.get("elapsedVideoTimeRatio", p.get("time_ratio"))
        v = p.get("audienceWatchRatio", p.get("retention"))
        if isinstance(t, (int, float)) and isinstance(v, (int, float)):
            out.append([round(float(t), 3), round(float(v), 3)])
    if len(out) > 30:                       # muestreo uniforme: la curva se dibuja igual
        paso = len(out) / 30.0
        out = [out[int(i * paso)] for i in range(30)]
    return out


def _retencion_en(puntos: list[list[float]], segundos: float, duracion: float) -> float | None:
    """Ratio de audiencia que sigue viendo al segundo N (para retencion_30s)."""
    if not puntos or not duracion:
        return None
    objetivo = min(1.0, segundos / duracion)
    mejor = min(puntos, key=lambda p: abs(p[0] - objetivo))
    return round(float(mejor[1]), 4)


def posts_publicados() -> list[dict]:
    """Cada post publicado por la fábrica, con su postId de Zernio y el video de YouTube."""
    out = []
    for archivo in sorted(config.PROJECTS.glob("*/publicacion/zernio.json")):
        try:
            datos = json.loads(archivo.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        slug = archivo.parents[1].name
        for r in datos.get("resultados") or []:
            if not r.get("postId") or r.get("status") in (None, "failed"):
                continue
            out.append({"slug": slug, "plataforma": r.get("plataforma") or "",
                        "postId": r["postId"], "url": r.get("url") or "",
                        "video_id": zernio.video_id_de(r.get("url") or "")})
    return out


def fila_de(cabeza: dict, analitica: dict, retencion: dict | None = None) -> dict:
    """PostAnalytics de Zernio + curva de YouTube -> la fila que pide retention_loop.json."""
    plataformas = analitica.get("platformAnalytics") or []
    plato = next((p for p in plataformas
                  if (p.get("platform") or "").lower() == (cabeza["plataforma"] or "").lower()),
                 {}) if isinstance(plataformas, list) else {}
    origen = {**analitica, **{k: v for k, v in (plato or {}).items()
                              if k in ("views", "impressions", "reach", "engagementRate")}}
    puntos = _puntos(origen.get("retentionCurve") or (retencion or {}).get("points") or [])
    duracion = origen.get("videoDurationSeconds")
    sincronia = analitica.get("_sync") or "ok"
    if retencion is not None and retencion.get("_sync") not in (None, "ok"):
        sincronia = f"{sincronia}+{retencion['_sync']}"
    completion = _ratio(origen.get("completionRate"))
    fila = {
        "slug": cabeza["slug"], "plataforma": cabeza["plataforma"],
        "postId": cabeza["postId"], "video_id": cabeza.get("video_id") or "",
        "platformPostId": (plato or {}).get("platformPostId") or "",
        "fecha": _hoy(),
        "vistas": origen.get("views"), "impresiones": origen.get("impressions"),
        "alcance": origen.get("reach"), "clicks": origen.get("clicks"),
        "ctr_impresiones": (round(origen["clicks"] / origen["impressions"], 4)
                            if isinstance(origen.get("clicks"), (int, float))
                            and isinstance(origen.get("impressions"), (int, float))
                            and origen["impressions"] else None),
        "likes": origen.get("likes"), "comentarios": origen.get("comments"),
        "compartidos": origen.get("shares"), "guardados": origen.get("saves"),
        "duracion_video_s": duracion,
        "retencion_media": completion if completion is not None else _ratio(
            origen.get("engagementRate")),
        "duracion_media_s": (round(completion * duracion, 1)
                             if completion is not None and isinstance(duracion, (int, float))
                             else None),
        "retencion_30s": _retencion_en(puntos, 30.0, duracion or 0),
        "retencion_curva_puntos": puntos,
        "sincronia": sincronia,
    }
    for campo in _campos_config():            # la config manda: ningún campo pedido se pierde
        fila.setdefault(campo, None)
    return fila


def medir(limite: int = 20) -> list[dict]:
    """Pide analítica por post y la appendea a state/metricas.jsonl. Devuelve las filas nuevas."""
    config.load_env()
    if not __import__("os").environ.get("ZERNIO_API_KEY", ""):
        print("  medir: sin ZERNIO_API_KEY, no hay forma de traer métricas reales")
        return []
    filas = []
    for cabeza in posts_publicados()[:limite]:
        try:
            analitica = zernio.analytics(cabeza["postId"])
        except (zernio.ZernioError, config.requests.RequestException) as exc:
            analitica = {"_sync": "error", "_error": str(exc)[:180]}
        retencion = None
        if cabeza.get("video_id") and analitica.get("_sync") == "ok":
            try:
                retencion = zernio.retencion_youtube(cabeza["video_id"])
            except (zernio.ZernioError, config.requests.RequestException) as exc:
                retencion = {"_sync": "error", "_error": str(exc)[:180]}
        fila = fila_de(cabeza, analitica, retencion)
        filas.append(fila)
        print(f"  medir {fila['slug']}/{fila['plataforma']}: vistas={fila['vistas']} "
              f"ret30s={fila['retencion_30s']} sincronia={fila['sincronia']}")
    if filas:
        config.STATE.mkdir(parents=True, exist_ok=True)
        with METRICAS.open("a", encoding="utf-8") as fh:
            for f in filas:
                fh.write(json.dumps(f, ensure_ascii=False) + "\n")
        print(f"  {len(filas)} filas -> state/metricas.jsonl")
    return filas


def leer(ultima_por_episode: bool = True) -> list[dict]:
    """Historial; por defecto sólo el último corte de cada (slug, plataforma)."""
    if not METRICAS.exists():
        return []
    filas = []
    for linea in METRICAS.read_text(encoding="utf-8").splitlines():
        linea = linea.strip()
        if not linea:
            continue
        try:
            filas.append(json.loads(linea))
        except json.JSONDecodeError:
            continue
    if not ultima_por_episode:
        return filas
    mejores: dict[tuple, dict] = {}
    for f in filas:
        clave = (f.get("slug"), f.get("plataforma"))
        actual = mejores.get(clave)
        if actual is None or str(f.get("fecha") or "") >= str(actual.get("fecha") or ""):
            mejores[clave] = f
    return [mejores[k] for k in sorted(mejores)]


def usable(filas: list[dict] | None = None) -> list[dict]:
    """Sólo filas con números reales: lo que sincronia!=ok no entra en ninguna mediana."""
    filas = filas if filas is not None else leer()
    return [f for f in filas if f.get("sincronia") == "ok"
            and any(isinstance(f.get(c), (int, float))
                    for c in ("vistas", "impresiones", "retencion_30s", "retencion_media"))]


def medianas(filas: list[dict] | None = None) -> dict:
    """Mediana del PROPIO canal por plataforma (los umbrales relativos de la config)."""
    por_plataforma: dict[str, dict[str, dict]] = {}
    for fila in (filas if filas is not None else usable()):
        grupo = por_plataforma.setdefault(fila.get("plataforma") or "desconocida", {})
        grupo[fila.get("slug") or ""] = fila          # el último corte manda (ya filtra leer())
    resumen = {}
    for plataforma, por_slug in por_plataforma.items():
        datos = list(por_slug.values())
        resumen[plataforma] = {"episodios": len(datos)}
        for campo in ("vistas", "impresiones", "ctr_impresiones", "retencion_30s",
                      "retencion_media", "duracion_media_s"):
            valores = [d[campo] for d in datos if isinstance(d.get(campo), (int, float))]
            resumen[plataforma][campo] = round(statistics.median(valores), 4) if valores else None
    return resumen
