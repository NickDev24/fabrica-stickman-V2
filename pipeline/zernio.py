"""Cliente Zernio (https://docs.zernio.com) para publicación autónoma.

Flujo documentado: POST /v1/media/presign -> PUT del archivo a uploadUrl ->
POST /v1/posts con mediaItems=[{url: publicUrl}] y publishNow.
Credenciales desde .env (ZERNIO_API_KEY, ZERNIO_YOUTUBE_ID, ZERNIO_FACEBOOK_ID).
"""
from __future__ import annotations

from pathlib import Path

import requests

from . import config

BASE = "https://zernio.com/api/v1"


class ZernioError(Exception):
    pass


def _headers() -> dict:
    config.load_env()
    key = __import__("os").environ.get("ZERNIO_API_KEY", "")
    if not key:
        raise ZernioError("ZERNIO_API_KEY ausente en .env")
    return {"Authorization": f"Bearer {key}"}


def accounts() -> list[dict]:
    r = requests.get(f"{BASE}/accounts", headers=_headers(), timeout=60)
    if r.status_code != 200:
        raise ZernioError(f"GET /accounts -> {r.status_code}: {r.text[:200]}")
    return r.json().get("accounts", [])


_CONTENT_TYPES = {".mp4": "video/mp4", ".png": "image/png", ".jpg": "image/jpeg",
                  ".jpeg": "image/jpeg", ".webp": "image/webp"}


def _content_type(path: Path) -> str:
    """El presign tiene que declarar el tipo REAL: las páginas del cómic son PNG."""
    return _CONTENT_TYPES.get(path.suffix.lower(), "application/octet-stream")


def upload(path: Path) -> str:
    ctype = _content_type(path)
    r = requests.post(f"{BASE}/media/presign", headers={**_headers(), "Content-Type": "application/json"},
                      json={"filename": path.name, "contentType": ctype, "size": path.stat().st_size},
                      timeout=60)
    if r.status_code != 200:
        raise ZernioError(f"presign {path.name} -> {r.status_code}: {r.text[:200]}")
    presigned = r.json()
    with path.open("rb") as fh:
        up = requests.put(presigned["uploadUrl"], data=fh,
                          headers={"Content-Type": ctype}, timeout=1800)
    if up.status_code not in (200, 201):
        raise ZernioError(f"PUT upload {path.name} -> {up.status_code}")
    return presigned["publicUrl"]


def _json(r) -> dict:
    try:
        return r.json() or {}
    except ValueError:
        return {}


def create_post(content: str, media_urls: list[str], platforms: list[dict],
                publish_now: bool = True, title: str = "",
                idempotency_key: str = "", tags: list[str] | None = None) -> dict:
    """Crea (y opcionalmente publica) el post. Devuelve la respuesta COMPLETA de Zernio.

    `tags` son las keywords de YouTube: el campo `hashtags` NO se agrega al caption ni se
    usa como keyword —documentado—, así que los hashtags tienen que ir escritos en `content`.
    """
    body = {
        "content": content,
        "mediaItems": [{"url": u, "type": "video" if u.endswith(".mp4") else "image"}
                       for u in media_urls],
        "platforms": platforms,
        "timezone": "America/Argentina/Buenos_Aires",
    }
    if title:
        body["title"] = title
    if tags:
        # YouTube: 100 chars por tag, 500 en total (recorte duro, no inventado).
        limpiados, total = [], 0
        for t in tags:
            t = str(t).strip()[:100]
            if not t or t in limpiados or total + len(t) + 1 > 500:
                continue
            limpiados.append(t)
            total += len(t) + 1
        body["tags"] = limpiados
    if publish_now:
        body["publishNow"] = True
    else:
        body["isDraft"] = True
    headers = {**_headers(), "Content-Type": "application/json"}
    if idempotency_key:
        headers["Idempotency-Key"] = idempotency_key
    r = requests.post(f"{BASE}/posts", headers=headers, json=body, timeout=120)

    # 409 DOBLE: (a) `idempotency_conflict` = la primera petición sigue procesándose, hay que
    # reintentar tras Retry-After; (b) dedup por hash de contenido = ESE post ya está creado en
    # las últimas 24 h. (b) NO es un fallo: publicar dos veces el capítulo es el fallo real.
    if r.status_code == 409:
        datos = _json(r)
        if datos.get("code") == "idempotency_conflict":
            raise ZernioError(f"POST /posts en curso (retry en "
                              f"{datos.get('retryAfter') or r.headers.get('Retry-After')}s)")
        return {"_http": 409, "status": "duplicate",
                "post": {"_id": datos.get("existingPostId")}, "raw": datos}

    # 207 es 2xx: `.ok` es True en cualquier cliente perezoso y el post se lee como publicado.
    # Se ramifica a propósito; el estado real está en post.status (documentado).
    if r.status_code not in (200, 201, 207):
        raise ZernioError(f"POST /posts -> {r.status_code}: {r.text[:300]}")
    datos = _json(r)
    datos["_http"] = r.status_code
    if r.status_code == 207:
        post = datos.get("post", {})
        print(f"  zernio 207: post.status={post.get('status')} "
              f"por-plataforma={[(p.get('platform'), p.get('status')) for p in
                                 datos.get('platformResults') or []]} "
              f"{(datos.get('error') or '')[:160]}")
    for aviso in datos.get("warnings") or []:
        print(f"  zernio AVISO: {aviso}")
    return datos


# --- analítica post-publicación (GET /v1/analytics, /v1/analytics/youtube/video-retention) ---
# Contratos verificados contra docs.zernio.com el 2026-11-05:
#   202 = Zernio todavía está sincronizando con la plataforma -> todavía no hay números.
#   424 = todas las plataformas fallaron la sincronización. 412 = falta el scope de
#   YouTube Analytics (devuelve reauthorizeUrl). Ninguno es un 0: registrarse como 0
#   sería aprender de un dato inventado.

def _get(ruta: str, params: dict) -> tuple[int, dict]:
    r = requests.get(f"{BASE}{ruta}", headers=_headers(), params=params, timeout=120)
    return r.status_code, _json(r)


def analytics(post_id: str) -> dict:
    """Métricas acumuladas de un post publicado (impresiones, views, retención, engagement)."""
    status, datos = _get("/analytics", {"postId": post_id})
    if status == 202:
        return {"_sync": "pendiente", "postId": post_id}
    if status == 424:
        return {"_sync": " fallo_en_plataforma", "postId": post_id,
                "_error": str(datos.get("error") or datos)[:200]}
    if status not in (200, 201):
        raise ZernioError(f"GET /analytics?postId={post_id} -> {status}: {str(datos)[:200]}")
    datos.setdefault("_sync", "ok")
    return datos


def retencion_youtube(video_id: str, account_id: str = "") -> dict:
    """Curva de retención real de YouTube (points: elapsedVideoTimeRatio / audienceWatchRatio).

    Tarda 2-3 días en finalizar; antes de eso la curva llega vacía o parcial, y eso se
    registra como tal. 412 = hay que reautorizar el scope de Analytics (viene reauthorizeUrl).
    """
    params = {"videoId": video_id}
    if account_id:
        params["accountId"] = account_id
    status, datos = _get("/analytics/youtube/video-retention", params)
    if status == 412:
        return {"_sync": "scope_faltante",
                "_reauthorize": (datos.get("error") or {}).get("reauthorizeUrl", "")
                                 if isinstance(datos.get("error"), dict) else ""}
    if status == 202:
        return {"_sync": "pendiente"}
    if status not in (200, 201):
        raise ZernioError(f"GET video-retention {video_id} -> {status}: {str(datos)[:200]}")
    datos.setdefault("_sync", "ok")
    return datos


def video_id_de(url: str) -> str:
    """El ID de un video de YouTube desde cualquier forma de su URL pública."""
    import re
    for patron in (r"[?&]v=([\w-]{6,})", r"youtu\.be/([\w-]{6,})", r"shorts/([\w-]{6,})"):
        m = re.search(patron, url or "")
        if m:
            return m.group(1)
    return ""
