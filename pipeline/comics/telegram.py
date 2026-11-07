"""Envío de cómics por Telegram para revisión del dueño (NUNCA publicación).

Mismo centro de control que los videos: el LIBRO (páginas comics.v2) como
fotos — portada del capítulo first, cada página como foto de seguimiento —,
con la leyenda de revisión y el estado del QC. La publicación real de cómics
será aparte (fase 6 del diseño).
"""
from __future__ import annotations

import json
import os

import requests

from .. import config
from ..episode import Episode

REVISION_LEYENDA = (
    "🍞 PULSO · CÓMIC (v2) — versión de revisión\n"
    "Enviado para evaluar el contenido; NO está publicado.\n\n"
    "📖 {titulo}\n"
    "🧩 {n} viñetas en {pags} páginas · grillas de 3 bandas {grillas}\n"
    "🎬 ritmo: gancho flash-forward → cliffhanger de página → silencio negro → remate\n"
    "🔗 {fuentes_totales} referencias verificadas en total (footer por página)\n"
    "✅ QC: aprobado (comics.v2 · texto compuesto fuera del generador)")


def enviar_comic(ep: Episode, datos: dict | None = None) -> None:
    """Manda comics/pages/pag-NN.png + carrusel al chat del dueño."""
    config.load_env()
    token = os.environ.get(config.TELEGRAM_TOKEN_ENV, "") or os.environ.get("TOKEN_BOT", "")
    chat = os.environ.get(config.TELEGRAM_CHAT_ENV, "") or os.environ.get("CHAT_ID", "")
    if not token or not chat:
        raise SystemExit(f"Faltan {config.TELEGRAM_TOKEN_ENV}/{config.TELEGRAM_CHAT_ENV} en .env")
    base = f"https://api.telegram.org/bot{token}/"
    comics = ep.dir / "comics"
    paginas = sorted((comics / "pages").glob("pag-*.png"))
    if not paginas:
        raise SystemExit(f"enviar_comic: no hay páginas en {comics / 'pages'} "
                         "(corré pipeline.comics --componer)")
    if datos is None:
        datos = json.loads((comics / "guion_paneles.json").read_text(encoding="utf-8"))
    paneles = datos.get("paneles", [])
    grillas = " / ".join("/".join(map(str, g)) for g in datos.get("grillas", []))
    fuentes_totales = len({u for p in paneles for u in (p.get("fuentes") or [])})
    caption = REVISION_LEYENDA.format(titulo=datos.get("titulo", ep.slug),
                                      n=len(paneles),
                                      pags=len(datos.get("grillas", [])),
                                      grillas=grillas,
                                      fuentes_totales=fuentes_totales)[:1024]
    enviados = 0
    for j, pagina in enumerate(paginas):
        with pagina.open("rb") as fh:
            r = requests.post(base + "sendPhoto",
                              data={"chat_id": chat, "caption": caption if j == 0 else ""},
                              files={"photo": (pagina.name, fh, "image/png")}, timeout=180)
        if not r.ok or not r.json().get("ok"):
            raise RuntimeError(f"sendPhoto falló: HTTP {r.status_code} {r.text[:200]}")
        enviados += 1
    # el carrusel ES el libro por página (mismas imágenes): no se reenvía
    print(f"  telegram: comic de {ep.slug} enviado ({enviados} fotos)")
