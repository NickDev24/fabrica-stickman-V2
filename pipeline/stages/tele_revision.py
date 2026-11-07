"""Revisión por Telegram con BOTONES y autonomía desbloqueable.

Flujo pedido por el dueño (2026-11-04):

1. El PRIMER contenido se envía a Telegram para aprobación con dos botones:
   ✅ APROBAR Y PUBLICAR  -> publica YouTube/Facebook (reusa publicar_automatico
      con `aprobado="user"`, saltando el bloqueo de "revisión humana" que existe
      precisamente porque todavía NO lo aprobó nadie) y queda registrada la
      aprobación: a partir de la segunda entrega la fábrica publica sin revisión.
   ❌ NO APROBAR          -> no se publica ningún archivo en YT/FB; el capítulo
      queda en "rechazado" (auditable en registry/published.jsonl).

2. Una vez registrada al menos una aprobación en state/autonomia.json, las
   corridas siguientes publican directamente y sólo avisan por Telegram.

Escucha de los toques: proceso `pipeline.run escuchar-telegram` (long-polling;
no webhook: no abrir puertos entrantes en el B950). Todo responde por el mismo
bot; el offset se persiste en state/tele_offset.json para no reprocesar nada.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

import requests

from .. import config
from ..episode import Episode

REVISIONES = config.STATE / "revisiones.json"
AUTONOMIA = config.STATE / "autonomia.json"
OFFSET = config.STATE / "tele_offset.json"


def _creds() -> tuple[str, str]:
    config.load_env()
    token = (os.environ.get(config.TELEGRAM_TOKEN_ENV, "")
             or os.environ.get("TELEGRAM_TOKEN_BOT", "") or os.environ.get("TOKEN_BOT", ""))
    chat = (os.environ.get(config.TELEGRAM_CHAT_ENV, "")
            or os.environ.get("TELEGRAM_CHAT_ID", "") or os.environ.get("CHAT_ID", ""))
    if not token or not chat:
        raise SystemExit("enviar_revision: faltan credenciales de Telegram en .env")
    return token, chat


def _token() -> str:
    return _creds()[0]


def _base() -> str:
    return f"https://api.telegram.org/bot{_token()}/"


def _video_final(ep: Episode) -> Path:
    """El mp4 núcleo del episodio; busca primero lo declarado, después el disco."""
    # 1) lo declarado por el render del maestro (contrato: ruta/keyframe);
    #    si hay versión collage (recortes aprobados), esa gana: es el master + overlay
    for art in sorted((ep.dir / "artifacts").glob("render_*.json"),
                      key=lambda a: (a.name != "render_collage.json",
                                     a.name != "render_keyframes.json", a.name)):
        nombre = (ep.read_json(art.name) or {}).get("archivo")
        if not nombre:
            continue
        candidatos = [ep.dir / "renders" / nombre, ep.dir / "derivados" / nombre]
        for f in candidatos:
            if f.exists() and f.stat().st_size > 1_000_000:
                return f
    # 2) cualquier video razonable, priorizando el maestro keyframe
    carpetas = [ep.dir / "renders", ep.dir / "derivados"]
    mp4 = [p for c in carpetas if c.is_dir() for p in c.glob("*.mp4")
           if p.stat().st_size > 1_000_000]
    if not mp4:
        raise SystemExit("tele_revision: no hay render terminado")
    maestro = [p for p in mp4 if "keyframe" in p.name]
    return max(maestro or mp4, key=lambda p: p.stat().st_mtime)


def enviar_para_aprobacion(ep: Episode) -> None:
    """Contrato del dueño: video + TÍTULO + SUBTÍTULO + 2 botones. Nada más."""
    _token_, chat = _creds()
    video = _video_final(ep)
    base = _base()
    meta = ep.metadata()
    titulo = ep.read_state().get("title") or ep.slug
    subtitulo = str(meta.get("angle") or "").strip() or "Pulso Curioso"
    caption = f"🎬 {titulo}\n{subtitulo}"[:1024]
    markup = json.dumps({"inline_keyboard": [
        [{"text": "✅ Aprobar", "callback_data": f"pub:{ep.slug}"},
         {"text": "❌ Reprobar", "callback_data": f"nopub:{ep.slug}"}],
    ]}, ensure_ascii=False)
    with video.open("rb") as fh:
        r = requests.post(base + "sendVideo",
                          data={"chat_id": chat, "caption": caption,
                                "supports_streaming": "true",
                                "reply_markup": markup},
                          files={"video": (video.name, fh, "video/mp4")}, timeout=300)
    if not r.ok or not r.json().get("ok"):
        raise RuntimeError(f"sendVideo revisión falló: HTTP {r.status_code} {r.text[:200]}")
    msg = r.json().get("result", {})
    (REVISIONES.parent / "revisiones.jsonl").open("a", encoding="utf-8").write(json.dumps(
        {"slug": ep.slug, "video": str(video), "msg_id": msg.get("message_id"),
         "ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "estado": "pendiente"},
        ensure_ascii=False) + "\n")
    print(f"  telegram REVISIÓN: video {video.name} + título + subtítulo + botones ✅/❌")


def autonomia_total() -> bool:
    """Autonomía sólo tras N aprobaciones revisadas (factory/publish/publish_strategy.json).

    Antes alcanzaba con UNA aprobación y eso convertía un descuido en publicar sin mirar.
    """
    from factory import parametros
    try:
        data = json.loads(AUTONOMIA.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return int(data.get("aprobaciones", 0)) >= parametros.minimo_aprobaciones_humanas()


def _actualizar_autonomia(decision: str, slug: str) -> None:
    from factory import parametros
    AUTONOMIA.parent.mkdir(parents=True, exist_ok=True)
    data: dict = {}
    if AUTONOMIA.exists():
        try:
            data = json.loads(AUTONOMIA.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            data = {}
    if decision == "pub":
        data["aprobaciones"] = int(data.get("aprobaciones", 0)) + 1
    data["ultima_decision"] = {"slug": slug, "decision": decision,
                               "ts": time.strftime("%Y-%m-%dT%H:%M:%S")}
    data["autonomia"] = bool(int(data.get("aprobaciones", 0)) >=
                              parametros.minimo_aprobaciones_humanas())
    AUTONOMIA.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def _registrar_jsonl(slug: str, estado: str) -> None:
    from . import publicacion
    config.REGISTRY.mkdir(parents=True, exist_ok=True)
    (config.REGISTRY / "revisiones.jsonl").open("a", encoding="utf-8").write(json.dumps(
        {"slug": slug, "estado": estado,
         "ts": time.strftime("%Y-%m-%dT%H:%M:%S")}, ensure_ascii=False) + "\n")


def notificar_autonomia(slug: str) -> None:
    _token_, chat = _creds()
    r = requests.post(_base() + "sendMessage",
                      data={"chat_id": chat,
                            "text": (f"✅ {slug}: publicado automáticamente "
                                     f"(autonomía; decisión tuya en una aprobación anterior).")},
                      timeout=60)
    if not r.ok:
        print(f"  aviso Telegram falló: HTTP {r.status_code}")


def _cargar(slug: str) -> Episode:
    ep = Episode(slug)
    ep_dir = config.PROJECTS / slug
    if not ep_dir.is_dir():
        raise SystemExit(f"escuchar: no existe el episodio {slug!r}")
    return ep


def _publicar_aprobado(slug: str) -> str:
    """Tras el toque en ✅: publica de verdad (YouTube por Zernio + Facebook)."""
    from . import publicacion

    os.environ["AUTO_PUBLISH"] = "true"  # la APROBACIÓN HUMANA es el opt-in del portal
    ep = _cargar(slug)
    print(f"  telegram: aprobación humana recibida para {slug} — publicando…")
    resultado = publicacion.publicar_automatico(ep, no_publish=False, aprobado="user")
    _actualizar_autonomia("pub", slug)
    _registrar_jsonl(slug, "aprobado_publicado")
    return json.dumps(resultado, ensure_ascii=False)[:300]


def _rechazar(slug: str) -> None:
    _actualizar_autonomia("nopub", slug)
    _registrar_jsonl(slug, "rechazado")
    print(f"  telegram: {slug} NO SE PUBLICA (decisión del dueño)")


def _responder(chat_id: int | str, text: str) -> None:
    try:
        requests.post(_base() + "sendMessage",
                      data={"chat_id": chat_id, "text": text[:4000]}, timeout=60)
    except requests.RequestException:
        pass


def _handle_callback(cq: dict) -> None:
    token, _chat = _creds()
    base = f"https://api.telegram.org/bot{token}/"
    data = str(cq.get("data") or "")
    cq_id = cq.get("id", "")
    chat_id = (cq.get("message") or {}).get("chat", {}).get("id") or ""
    try:
        if ":" not in data:
            _responder(chat_id, "botón desconocido")
            return
        accion, slug = data.split(":", 1)
        requests.post(base + "answerCallbackQuery",
                      data={"callback_query_id": cq_id,
                            "text": "Procesando…"}, timeout=15)
        if accion == "pub":
            try:
                resumen = _publicar_aprobado(slug)
                _responder(chat_id, (f"✅ Publicado: {slug}\n{resumen}\n\n"
                                     "Autonomía desbloqueada: los próximos "
                                     "contenidos se publican sin revisión."))
            except Exception as exc:  # noqa: BLE001 — nunca morir en pleno callback
                _responder(chat_id, f"⚠️ No se pudo publicar {slug}: {exc}")
        elif accion == "nopub":
            _rechazar(slug)
            _responder(chat_id,
                       f"❌ {slug}: NO se publica en YouTube ni Facebook. "
                       "El capítulo queda rechazado y auditado.")
        else:
            _responder(chat_id, f"acción desconocida: {accion}")
    except Exception as exc:  # noqa: BLE001
        print(f"  callback error: {exc}")


def _init_offset() -> int:
    if OFFSET.exists():
        try:
            return int(OFFSET.read_text(encoding="utf-8").strip())
        except ValueError:
            pass
    # nunca reprocesar el historial: sólo la última actualización queda de referencia
    try:
        r = requests.get(_base() + "getUpdates",
                         params={"offset": -1, "timeout": 0}, timeout=15)
        res = r.json().get("result", [])
        return (res[-1]["update_id"] + 1) if res else 0
    except Exception:
        return 0


def escuchar() -> None:
    """Long-polling: reacciona a ✅/❌ (y /aprobar /rechazar /estado /precio)."""
    token, _chat = _creds()
    base = f"https://api.telegram.org/bot{token}/"
    offset = _init_offset()
    print("escuchar-telegram: escuchando botones de revisión…")
    while True:
        try:
            r = requests.get(base + "getUpdates",
                             params={"offset": offset, "timeout": 40}, timeout=50)
            payload = r.json() if r.ok else {"ok": False, "result": []}
            # tolera que no permita timeout (parámetro del webhook): reduce el fallback
            if payload.get("error_code") == 400:
                r = requests.get(base + "getUpdates",
                                 params={"offset": offset}, timeout=15)
                payload = r.json()
            for u in payload.get("result", []) or []:
                offset = u["update_id"] + 1
                OFFSET.write_text(str(offset), encoding="utf-8")
                cq = u.get("callback_query")
                if cq:
                    _handle_callback(cq)
                    continue
                msg = u.get("message") or {}
                text = str(msg.get("text") or "").strip()
                chat_id = (msg.get("chat") or {}).get("id")
                if text == "/precio":
                    import pipeline.llm as llm
                    _responder(chat_id, f"Gasto Gemini del mes: {llm._gasto_gemini():.4f} USD (tope 4.5)")
                elif text == "/estado":
                    _responder(chat_id, (f"Autonomía total: {'SÍ' if autonomia_total() else 'NO (espero tu ✅ del primer capítulo)'}"))
                elif text.startswith("/aprobar "):
                    try:
                        resumen = _publicar_aprobado(text.split(maxsplit=1)[1].strip())
                        _responder(chat_id, f"✅ publicado: {resumen}")
                    except SystemExit as exc:
                        _responder(chat_id, f"⚠️ {exc}")
                    except Exception as exc:  # noqa: BLE001
                        _responder(chat_id, f"⚠️ {exc}")
                elif text.startswith("/rechazar "):
                    _rechazar(text.split(maxsplit=1)[1].strip())
                    _responder(chat_id, "❌ rechazado: no se publica nada.")
        except requests.RequestException as exc:
            print(f"  escuchar-telegram: {exc} — reintento en 5s")
            time.sleep(5)
