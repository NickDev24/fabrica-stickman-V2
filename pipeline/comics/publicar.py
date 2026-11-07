"""Publicación del cómic en Facebook vía Zernio (fase 6, pedido del dueño 2026-11-07).

Sólo sale al mundo con `AUTO_PUBLISH` activo y el QC del libro aprobado. Sube el
CARRUSEL (1 imagen por página, no por panel) como post multi-imagen de Facebook.
Un fallo acá se registra y devuelve estado; nunca toca la publicación del video.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from .. import config, zernio
from ..episode import Episode

MAX_IMAGENES = 10  # techo operativo de fotos por post de Facebook


def _caption(ep: Episode, datos: dict) -> str:
    titulo = str(datos.get("titulo") or ep.read_state().get("title") or ep.slug).strip()
    angle = str(ep.metadata().get("angle") or "").strip()
    paneles = datos.get("paneles") or []
    fuentes = len({u for p in paneles for u in (p.get("fuentes") or [])})
    partes = [titulo]
    if angle:
        partes.append(angle)
    if paneles:
        partes.append(f"📖 {len(paneles)} viñetas · {len(datos.get('grillas') or [])} páginas · "
                      f"{fuentes} fuentes verificadas")
    partes.append("#PulsoCurioso #comic #historieta")
    return "\n\n".join(partes)[:2000]


def _guardar(ep: Episode, resultado: dict, urls: list[str]) -> None:
    comics = ep.dir / "comics"
    comics.mkdir(parents=True, exist_ok=True)
    (comics / "publicacion.json").write_text(json.dumps(
        {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), **resultado, "mediaUrls": urls},
        ensure_ascii=False, indent=2), encoding="utf-8")


def _estado(post: dict, respuesta: dict) -> str:
    """published = el mundo lo ve; scheduled/publishing = en curso; el resto, fallo."""
    estado = str((post or {}).get("status") or respuesta.get("status") or "").strip().lower()
    if estado in ("scheduled", "publishing"):
        return "en_curso"
    return estado or "failed"


def publicar_facebook(ep: Episode, datos: dict | None = None) -> dict:
    """Publica el carrusel del cómic en Facebook. No publica si falla cualquier gate."""
    config.load_env()
    if not config.auto_publish():
        return {"status": "sin_publicar", "motivo": "AUTO_PUBLISH desactivado"}
    z = config.zernio_config()
    if not z.get("api_key") or not z.get("facebook"):
        return {"status": "sin_publicar",
                "motivo": "faltan ZERNIO_API_KEY/ZERNIO_FACEBOOK_ID en .env"}

    comics = ep.dir / "comics"
    if datos is None:
        ruta = comics / "guion_paneles.json"
        if not ruta.exists():
            return {"status": "sin_material", "motivo": "no hay guion_paneles.json"}
        datos = json.loads(ruta.read_text(encoding="utf-8"))

    qc: dict = {}
    try:
        qc = json.loads((comics / "qc.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        pass
    if not qc.get("aprobado"):
        return {"status": "qc_no_aprobado", "motivo": "comics/qc.json sin aprobado=true"}

    paginas = sorted((comics / "carrusel").glob("pag-*.png"))[:MAX_IMAGENES]
    if not paginas:
        return {"status": "sin_material", "motivo": "no hay páginas en comics/carrusel"}

    try:
        urls = [zernio.upload(p) for p in paginas]
        respuesta = zernio.create_post(
            _caption(ep, datos), urls,
            [{"platform": "facebook", "accountId": z["facebook"]}],
            title=str(datos.get("titulo") or ep.slug),
            idempotency_key=f"{ep.slug}:comics:facebook")
    except Exception as exc:  # red, presign o API: se registra como fallo, nunca tumba el video
        resultado = {"status": "failed", "error": str(exc)[:300], "paginas": len(paginas)}
        _guardar(ep, resultado, [])
        print(f"  comics facebook: FALLÓ ({exc})")
        return resultado

    post = respuesta.get("post", {}) or {}
    resultado = {"status": _estado(post, respuesta),
                 "postId": post.get("_id") or respuesta.get("existingPostId"),
                 "url": post.get("platformPostUrl"),
                 "paginas": len(paginas)}
    _guardar(ep, resultado, urls)
    print(f"  comics facebook: {resultado['status']} ({len(paginas)} páginas)"
          + (f" {resultado['url']}" if resultado.get("url") else ""))
    return resultado
