"""Cliente Zernio (https://docs.zernio.com) para publicación autónoma.

Flujo documentado: POST /v1/media/presign -> PUT del archivo a uploadUrl ->
POST /v1/posts con mediaItems=[{url: publicUrl}] y publishNow.
Credenciales desde .env (ZERNIO_API_KEY, ZERNIO_ID_YOUTUBE, ZERNIO_ID_FACEBOOK).
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


def upload(path: Path) -> str:
    ctype = "video/mp4" if path.suffix == ".mp4" else "image/jpeg"
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


def create_post(content: str, media_urls: list[str], platforms: list[dict],
                publish_now: bool = True, title: str = "") -> dict:
    body = {
        "content": content,
        "mediaItems": [{"url": u, "type": "video" if u.endswith(".mp4") else "image"}
                       for u in media_urls],
        "platforms": platforms,
        "timezone": "America/Argentina/Buenos_Aires",
    }
    if title:
        body["title"] = title
    if publish_now:
        body["publishNow"] = True
    else:
        body["isDraft"] = True
    r = requests.post(f"{BASE}/posts", headers={**_headers(), "Content-Type": "application/json"},
                      json=body, timeout=120)
    if r.status_code not in (200, 201):
        raise ZernioError(f"POST /posts -> {r.status_code}: {r.text[:300]}")
    return r.json().get("post", {})
