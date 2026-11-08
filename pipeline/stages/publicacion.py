"""Etapa 7: checklist de publicación (gate 7: nunca publicar sin aprobación humana).

Genera títulos/descripciones con las fuentes listas para pegar, recordatorio del toggle
de "contenido alterado o sintético" de YouTube Studio, y opcionalmente envía el corte a
revisión por Telegram. Zernio/YouTube/Facebook NO se tocan jamás desde acá.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

import requests

from .. import config, gates
from ..episode import Episode


def _fuentes_md(sources: dict) -> str:
    seen, lines = set(), []
    for c in sources["claims"]:
        for s in c["sources"]:
            if s["url"] in seen:
                continue
            seen.add(s["url"])
            lines.append(f"- {s.get('publisher', '')} — {s['url']}")
    return "\n".join(lines)


def _creditos_md(ep: Episode) -> str:
    p = ep.artifacts / "licenses.json"
    if not p.exists():
        return ""
    data = json.loads(p.read_text(encoding="utf-8"))
    seen, lines = set(), []
    for l in data.get("licencias", []):
        key = l["source"].split("/")[-1]
        if key in seen:
            continue
        seen.add(key)
        lines.append(f"- {l['file']} — {l['credit']} — {l['source']}")
    return "\n".join(lines)


def checklist(ep: Episode) -> Path:
    sources = ep.read_json("sources.json")
    meta = ep.metadata()
    manifest = ep.read_json("derivados-manifest.json")
    gates_out = meta.get("gates", gates.run_all_gates(ep.dir))
    title = ep.read_state()["title"]
    from factory import parametros
    motivos = gates.gate_titulo(title, *parametros.rango_titulo())
    if motivos:
        raise SystemExit(f"GATE TÍTULO BLOQUEA LA PUBLICACIÓN: {motivos[0]} — corregí el título "
                         "en episode.json y volvé a correr la etapa (el guion ya reescribe el suyo; "
                         "esta barrera atrapa los episodios anteriores a la regla).")
    subtitle = str(meta.get("angle") or "Pulso Curioso").strip()
    desc = f"{title}\n{subtitle}"
    yt_parts = "\n".join(f"  - {p['archivo']} ({p['duration_s']}s)" for p in manifest.get("yt_partes", []))
    if manifest.get("ruta") in ("keyframe", "avatar_fallback") or "youtube_main" in manifest:
        yt = manifest["youtube_main"]
        fb = manifest["facebook_reel"]
        fallback_note = ("\n> Fallback de avatar local: revisar especialmente la apariencia del personaje.\n"
                         if manifest.get("ruta") == "avatar_fallback" else "")
        plataformas = f"""## YouTube — video vertical completo (carga manual tras revisar)
- Archivo: `{yt['archivo']}` ({yt['duration_s']} s)
- Formato: 9:16 — evaluar publicación como Short según duración y reglas vigentes del canal
- Título: `{title}`
- Descripción lista para pegar:
{desc}
- Miniatura: `derivados/portada-yt.jpg` (1280x720) — subir como miniatura personalizada;
  sin ella YouTube elige un frame al azar y eso no frena el scroll
- Portada vertical (Short/pausa): `derivados/portada.jpg`
- [ ] Revisar video, fuentes, audio y legibilidad visual antes de subir
- [ ] Marcar contenido alterado o sintético en YouTube Studio
{fallback_note}

## Facebook Reels — versión vertical
- Archivo: `derivados/{fb['archivo']}` ({fb['duration_s']} s, {fb['resolucion']})
- [ ] Revisar recorte/legibilidad y publicar manualmente si queda aprobado
"""
    else:
        plataformas = f"""## YouTube (3 partes)
{yt_parts}
- [ ] Título sugerido: "{title} (parte N de 3)"
- [ ] Descripción (pegar tal cual):
{desc}
- [ ] **Activar toggle "Contenido alterado o sintético" en YouTube Studio** (este episodio
      usa narración IA Piper y visuales generados: synthetic_content={meta.get('synthetic_content')})
- [ ] Categoría: Educación | Idioma: español

## TikTok (tráiler {manifest['tiktok']['duration_s']}s)
- [ ] Subir {manifest['tiktok']['archivo']} — gancho en los primeros 2 s, texto en pantalla
- [ ] Mencionar que es adelanto y dirigir al documental completo

## Instagram
- [ ] Tráiler vertical {manifest['instagram_video']['duration_s']}s: {manifest['instagram_video']['archivo']}
- [ ] Artículo de feed (1200-3000 palabras): publicacion/articulo-instagram.md
- [ ] Etiquetar contenido con narración sintética según política de la plataforma
"""
    path = ep.dir / "publicacion" / "checklist.md"
    path.parent.mkdir(exist_ok=True)
    path.write_text(f"""# Checklist de publicación — {title}

GENERADO AUTOMÁTICAMENTE. No se publica en redes: el envío a Telegram es para revisión humana.
Estado de gates: {json.dumps(gates_out, ensure_ascii=False, indent=2)}

{plataformas}

## Telegram (aviso de corrida)
- [ ] Los renders y la placa se enviaron al bot al cerrar `auto` (si el envío falló: `.venv/bin/python -m pipeline.run enviar {ep.slug}`)

## Registro anti-duplicado
- [ ] `auto` ya registró el guion en `registry/published.jsonl`; si publicaste una versión
      manually corregida, volvé a registrar con `python3 -m pipeline.run registrar {ep.slug}`

## Umbrales de monetización (verificados 2026-10-29, volver a chequear: cambian)
- YouTube: 1.000 suscriptores + 4.000 h de watch time/365 días (o 10 M de vistas Shorts/90 d)
  https://support.google.com/youtube/answer/72851
- Meta (Facebook/Instagram): los requisitos figuran sólo en el panel de elegibilidad;
  verificar en https://www.facebook.com/business/help/1604287853035214 antes de fijar números.
""", encoding="utf-8")
    ep.write_json("publicacion/descripciones.json", {"titulo": title, "descripcion": desc,
                                                     "fuentes": ep.read_state().get("fuentes", [])})
    ep.set_stage("publicacion", "checklist_listo")
    print(f"  checklist -> {path.relative_to(ep.dir)} | publicar sigue BLOQUEADO hasta aprobación humana")
    return path


def _hashtags(ep: Episode) -> list[str]:
    """Un solo origen para las etiquetas: las mismas que ve el dueño en Telegram.

    Viajan como `#texto` en el caption y, para YouTube, sin el `#` en el campo `tags`
    (documentado: `hashtags` es sólo referencia; las keywords se pasan por `tags`).
    """
    etiquetas = ["#PulsoCurioso", "#curiosidades", "#documental"]
    nicho = str(ep.read_state().get("categoria", "")).replace("-", "").strip()
    if nicho:
        etiquetas.append(f"#{nicho}")
    return etiquetas


def texto_de_envio(ep: Episode) -> str:
    """El copy que el dueño pidió en el envío: título + subtítulo + guion completo + hashtags.

    Sin archivos .md ni .json: el texto viaja como caption del video y como mensaje de
    texto del chat (Telegram corta captions a 1024 y mensajes a 4096 caracteres).
    """
    sources = ep.read_json("sources.json")
    fuentes = _fuentes_md(sources)
    titulo = ep.read_state()["title"]
    meta = ep.metadata()
    subtitulo = str(meta.get("angle") or "").strip() or \
        "Pulso Curioso — historias sorprendentes con contexto y fuentes verificables"
    guion_texto = ep.read_text("script.txt")
    guion_texto = "\n".join(l for l in guion_texto.splitlines()
                            if not l.lstrip().startswith("#")).strip()
    guion_texto = re.sub(r"\n{3,}", "\n\n", guion_texto)
    hashtags = " ".join(_hashtags(ep))
    partes = [
        f"🎬 {titulo}",
        f"— {subtitulo} —",
        "",
        guion_texto,
        "",
        "Fuentes verificables:",
        fuentes,
        "",
        hashtags,
    ]
    return "\n".join(partes)


def _partir_mensaje(texto: str, tope: int = 4000) -> list[str]:
    """Corta por dobles saltos sin romper palabras para el techo de 4096 del sendMessage."""
    cortes: list[str] = []
    pendiente = texto
    while len(pendiente) > tope:
        corte = pendiente.rfind("\n\n", 0, tope)
        if corte < 200:
            corte = pendiente.rfind(" ", 0, tope)
        if corte < 200:  # sin separador útil: corte duro, nunca un slice negativo
            corte = tope
        cortes.append(pendiente[:corte].strip())
        pendiente = pendiente[corte:].strip()
    if pendiente:
        cortes.append(pendiente)
    return cortes


def enviar_solo_video(ep: Episode) -> None:
    """Envío del dueño: el VIDEO terminado (con caption) + el texto completo del capítulo.

    Sin adjuntos .md/.json: el guion completo y los hashtags van como mensajes de texto
    del propio chat, no como documentos.
    """
    config.load_env()
    token = os.environ.get(config.TELEGRAM_TOKEN_ENV, "") or os.environ.get("TOKEN_BOT", "")
    chat = os.environ.get(config.TELEGRAM_CHAT_ENV, "") or os.environ.get("CHAT_ID", "")
    if not token or not chat:
        raise SystemExit(f"Faltan {config.TELEGRAM_TOKEN_ENV}/{config.TELEGRAM_CHAT_ENV} en .env")
    base = f"https://api.telegram.org/bot{token}/"
    finales = []
    for art in sorted((ep.dir / "artifacts").glob("render_*.json")):
        nombre = (ep.read_json(art.name) or {}).get("archivo")
        if nombre:
            finales.append(ep.dir / "renders" / nombre)
    if not finales:
        raise SystemExit("enviar_solo_video: no hay render terminado en artifacts/render_*.json")
    video = max(finales, key=lambda f: f.stat().st_mtime)
    if not video.exists():
        raise SystemExit(f"enviar_solo_video: no existe {video}")
    copia = texto_de_envio(ep)
    lineas = copia.splitlines()
    # caption del video: título + subtítulo + hashtags (guion completo va como mensaje)
    caption_video = "\n".join([lineas[0], lineas[1], "", lineas[-1]])[:1024]
    with video.open("rb") as fh:
        r = requests.post(base + "sendVideo",
                          data={"chat_id": chat, "caption": caption_video,
                                "supports_streaming": "true"},
                          files={"video": (video.name, fh, "video/mp4")}, timeout=300)
    if not r.ok or not r.json().get("ok"):
        raise RuntimeError(f"sendVideo falló: HTTP {r.status_code} {r.text[:200]}")
    for cuerpo in _partir_mensaje(copia):
        r = requests.post(base + "sendMessage",
                          data={"chat_id": chat, "text": cuerpo}, timeout=120)
        if not r.ok or not r.json().get("ok"):
            raise RuntimeError(f"sendMessage falló: HTTP {r.status_code} {r.text[:200]}")
    print(f"  telegram: video {video.name} + texto completo y hashtags enviados (sin adjuntos)")


def enviar_telegram(ep: Episode, caption: str = "") -> None:
    """Manda la pieza terminada a revisión por Telegram (centro de control del canal).

    Antes sólo buscaba en `derivados/`, así que un episodio renderizado por la ruta
    de avatar (`renders/<slug>-avatar.mp4`) no enviaba nada: pasaba el review sin
    que nadie viera el video. Los .mp4 van por sendVideo para que se reproduzcan
    inline en el chat; el checklist y el resto siguen yendo como documento.
    """
    config.load_env()
    token = os.environ.get(config.TELEGRAM_TOKEN_ENV, "") or os.environ.get("TOKEN_BOT", "")
    chat = os.environ.get(config.TELEGRAM_CHAT_ENV, "") or os.environ.get("CHAT_ID", "")
    if not token or not chat:
        raise SystemExit(f"Faltan {config.TELEGRAM_TOKEN_ENV}/{config.TELEGRAM_CHAT_ENV} en .env")
    base = f"https://api.telegram.org/bot{token}/"
    # La pieza final la declara el artefacto del render; los cortes derivados van todos.
    finales = []
    for art in sorted((ep.dir / "artifacts").glob("render_*.json")):
        nombre = (ep.read_json(art.name) or {}).get("archivo")
        if nombre:
            finales.append(ep.dir / "renders" / nombre)
    manifest_path = ep.dir / "artifacts" / "derivados-manifest.json"
    if manifest_path.exists():
        m = ep.read_json("derivados-manifest.json")
        main_rel = (m.get("youtube_main") or {}).get("archivo")
        main_path = ep.dir / main_rel if main_rel else None
        if main_path and main_path.exists():
            finales = [main_path]
    if not finales:  # episodio sin artefacto de render: todo menos el mudo intermedio
        finales = [f for f in sorted((ep.dir / "renders").glob("*.mp4"))
                   if not f.name.endswith("-silent.mp4")]
    files = finales + sorted((ep.dir / "derivados").glob("*.mp4")) + [
        ep.dir / "artifacts" / "contacto.png",
        ep.dir / "artifacts" / "render_keyframes.json",
        ep.dir / "artifacts" / "render_derivados.json",
        ep.dir / "artifacts" / "storyboard.md",
        ep.dir / "publicacion" / "checklist.md",
    ]
    # Título + descripción completa de publicación: el video se manda con el copy real,
    # y además se envía como mensaje para que se pueda copiar entero.
    publicacion_cap = ""
    desc_path = ep.dir / "publicacion" / "descripciones.json"
    if desc_path.exists():
        d = json.loads(desc_path.read_text(encoding="utf-8"))
        titulo = str(d.get("titulo", "")).strip()
        desc = str(d.get("descripcion", "")).strip()
        if titulo and desc.startswith(titulo):
            desc = desc[len(titulo):].lstrip()
        publicacion_cap = f"{titulo}\n\n{desc}".strip() if titulo else desc
    enviados = 0
    for f in files:
        if not f.exists():
            continue
        cap = (publicacion_cap[:1000] if f.suffix.lower() == ".mp4" and publicacion_cap
               else caption or f"{ep.slug}: {f.name} (revisión)")
        metodo = "sendVideo" if f.suffix.lower() == ".mp4" else "sendDocument"
        campo = "video" if metodo == "sendVideo" else "document"
        with f.open("rb") as fh:
            r = requests.post(base + metodo,
                              data={"chat_id": chat, "caption": cap, "supports_streaming": "true"},
                              files={campo: (f.name, fh, "video/mp4" if metodo == "sendVideo"
                                             else "text/markdown")},
                              timeout=300)
        body = r.json()
        print(f"  telegram {metodo} {f.name}: {body.get('ok', r.status_code)}"
              + ("" if body.get("ok") else f" {str(body.get('description'))[:160]}"))
        enviados += 1
    if publicacion_cap:
        r = requests.post(base + "sendMessage",
                          data={"chat_id": chat, "text": publicacion_cap[:4096],
                                "disable_web_page_preview": "true"}, timeout=60)
        print(f"  telegram sendMessage copy completo: {r.json().get('ok', r.status_code)}")
    if not enviados:
        print("  telegram: no hay mp4 en renders/ ni derivados/ para enviar")


def registrar(ep: Episode, estado: str = "producido") -> None:
    """Deja el guion en el registro para el gate anti-duplicado (gate 4).

    El título y la historia van aparte de la huella: pipeline/huellas.py compara raíces
    temáticas, así que la próxima corrida no puede volver a elegir la MISMA historia con
    otras palabras (el gate 4 sólo ve texto y eso no alcanza).
    """
    script = ep.read_text("script.txt")
    estado_actual = ep.read_state() or {}
    from .. import huellas
    titulo = str(estado_actual.get("title") or ep.slug)
    config.REGISTRY.mkdir(parents=True, exist_ok=True)
    with (config.REGISTRY / "published.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({"slug": ep.slug, "estado": estado,
            "ts": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
            "titulo": titulo,
            # La huella del título + el arranque del guion: es lo que compara pipeline/
            # huellas.py cuando la fábrica elige la idea del día, antes de escribir nada.
            "huella": huellas.huella(f"{titulo} {script[:3000]}"),
                             "script": script}, ensure_ascii=False) + "\n")
    print(f"  {ep.slug} registrado en registry/published.jsonl ({estado})")


def _plan_publicacion(ep: Episode, ids: dict, desc: dict) -> list[dict]:
    """Qué hay que subir, a qué plataforma y con qué copy. Vacío = no hay episodio publicable.

    El master (el capítulo completo) era la pieza que nunca entraba al upload: se globaban
    archivos de una ruta de 3 partes que el motor keyframe ya no produce.
    """
    manifest = {}
    if (ep.artifacts / "derivados-manifest.json").exists():
        manifest = ep.read_json("derivados-manifest.json") or {}
    titulo = desc.get("titulo") or (ep.read_state() or {}).get("title") or ep.slug
    from factory import parametros
    motivos = gates.gate_titulo(titulo, *parametros.rango_titulo())
    if motivos:
        raise SystemExit(f"GATE TÍTULO BLOQUEA LA PUBLICACIÓN de {ep.slug}: {motivos[0]}")
    descripcion = desc.get("descripcion") or titulo
    plan: list[dict] = []

    if ids.get("youtube"):
        main = None
        if manifest.get("youtube_main"):
            candidato = ep.dir / manifest["youtube_main"]["archivo"]
            main = candidato if candidato.exists() else None
        if main is None:
            for nombre in (f"{ep.slug}-main.mp4", f"{ep.slug}-collage.mp4", f"{ep.slug}-keyframe.mp4"):
                ruta = ep.dir / "renders" / nombre
                if ruta.exists():
                    main = ruta
                    break
        if main:
            plan.append({"plataforma": "youtube", "archivo": main, "titulo": titulo,
                         "descripcion": descripcion,
                         "tags": [h.lstrip("#") for h in _hashtags(ep)],
                         "plataformas": [{"platform": "youtube", "accountId": ids["youtube"],
                                          "platformSpecificData": {"title": titulo}}]})

    if ids.get("facebook"):
        reel = None
        if manifest.get("facebook_reel"):
            candidato = ep.dir / "derivados" / manifest["facebook_reel"]["archivo"]
            reel = candidato if candidato.exists() else None
        if reel is None:
            for patron in ("facebook-reel.mp4", "trailer-a-facebook-reel.mp4"):
                ruta = ep.dir / "derivados" / patron
                if ruta.exists():
                    reel = ruta
                    break
        if reel:
            plan.append({"plataforma": "facebook", "archivo": reel, "titulo": titulo,
                         "descripcion": descripcion,
                         "plataformas": [{"platform": "facebook", "accountId": ids["facebook"]}]})
    return plan


def _qc_del_master(ep: Episode) -> dict:
    """El control de calidad MEDIDO del máster, venga de la ruta que venga.

    La barrera histórica era el NOMBRE de la ruta ("keyframe" → revisar), que no mide nada:
    lo que tiene que impedir que un video salga al mundo es un defecto real (duración,
    loudness, resolución o cuadros muertos), no la etiqueta del motor que lo produjo.
    """
    for nombre in ("render_collage.json", "render_keyframes.json", "qc.json"):
        if (ep.artifacts / nombre).exists():
            datos = ep.read_json(nombre) or {}
            if datos.get("status"):
                return {**datos, "artifact": nombre}
    return {}


def publicar_automatico(ep: Episode, no_publish: bool = False, aprobado: str | None = None) -> dict:
    """Sube los derivados a Zernio y publica (YouTube máster + Facebook reel).

    Con AUTO_PUBLISH activo (hay key en .env) es publishNow; con --no-publicar queda
    como draft. La aprobación explícita del dueño (botón "✅ APROBAR Y PUBLICAR" de
    Telegram, o "/aprobar <slug>") salta también la barrera de QC, porque el dueño ya
    vio el video con sus propios ojos y eso vale más que el medidor.
    """
    from .. import gates, zernio
    meta = ep.metadata()
    gates.gate_publicacion(meta)  # gate 7: flag sintético obligatorio antes de salir al mundo
    if aprobado != "user":
        qc = _qc_del_master(ep)
        if not qc:
            print("  publicación BLOQUEADA: no hay QC medido del máster, no se publica a ciegas")
            return {"status": "revision_humana_requerida",
                    "motivo": "falta artifacts/render_keyframes.json (o qc.json) con status"}
        if qc.get("status") != "pass":
            print(f"  publicación BLOQUEADA por QC ({qc.get('problemas')})")
            return {"status": "revision_humana_requerida", "motivo": qc.get("problemas"),
                    "qc": qc.get("artifact")}
    if no_publish and aprobado != "user":
        print("  --no-publicar: sólo borradores/checklist (AUTO_PUBLISH no se toca)")
        return {"status": "sin_publicar"}
    if aprobado != "user" and not config.auto_publish():
        print("  AUTO_PUBLISH del .env desactivado: no se publica")
        return {"status": "sin_publicar"}

    z = config.zernio_config()
    if not z["api_key"]:
        raise SystemExit("AUTO_PUBLISH activo pero falta ZERNIO_API_KEY")
    ids = {"youtube": z["youtube"], "facebook": z["facebook"]}
    if not ids["youtube"]:
        raise SystemExit("Falta ZERNIO_YOUTUBE_ID en .env")

    ruta_desc = ep.dir / "publicacion" / "descripciones.json"
    desc = json.loads(ruta_desc.read_text(encoding="utf-8")) if ruta_desc.exists() else {}
    try:
        plan = _plan_publicacion(ep, ids, desc)
    except SystemExit as titulo:
        # Un título que no pasa el gate NO es un error de la corrida: es un episodio que
        # hay que mostrarle al dueño. Si acá cortaba el proceso, run.py lo atrapaba como
        # "keyframe BLOQUEADO" y el episodio jamás llegaba a Telegram.
        print(f"  publicación BLOQUEADA por el gate de título: {titulo}")
        return {"status": "revision_humana_requerida", "motivo": str(titulo)[:300]}
    if not plan:
        # El fallo histórico: se globaba derivados/yt-parte-*.mp4 (que la ruta keyframe no
        # produce), el loop quedaba vacío y `all([])` devolvía True -> AUTO_PUBLISHED con
        # cero uploads y autonomía desbloqueada. Sin plan no hay éxito posible.
        meta["publish_status"] = "SIN_MATERIAL_PUBLICABLE"
        ep.save_metadata(meta)
        print("  publicación: NO hay master ni reel que subir — nada se publicó (no es éxito)")
        return {"status": "sin_material", "resultados": []}

    resultados = []
    for item in plan:
        # Una clave por pieza: si la corrida se interrumpe y vuelve, Zernio devuelve el post
        # original en vez de crear el segundo capítulo publicado del mismo día.
        clave = f"{ep.slug}:{item['plataforma']}:{item['archivo'].name}"
        try:
            url = zernio.upload(item["archivo"])
            respuesta = zernio.create_post(item["descripcion"], [url], item["plataformas"],
                                           title=item["titulo"], idempotency_key=clave,
                                           tags=item.get("tags"))
            post = respuesta.get("post", {})
            registro = {"plataforma": item["plataforma"], "archivo": item["archivo"].name,
                        "postId": post.get("_id"), "status": post.get("status")
                        or respuesta.get("status"), "mediaUrl": url,
                        "url": post.get("platformPostUrl"), "http": respuesta.get("_http")}
            # La platformPostUrl no siempre está en la respuesta de creación (Zernio la
            # resuelve después): un status published POSTERIOR con postId es éxito igual.
            # Se reconcilia al vuelo contra /posts/:id en vez de gritar FALLÓ con post vivo.
            if registro["status"] == "published" and registro["postId"] and not registro["url"]:
                try:
                    st, datos = zernio._get(f"/posts/{registro['postId']}", {})
                    for pp in datos.get("post", {}).get("platforms", []):
                        if pp.get("platformPostUrl"):
                            registro["url"] = pp["platformPostUrl"]
                except Exception:
                    pass
            resultados.append(registro)
            existe_pos = str(registro["postId"] or "")
            cola_url = registro["url"] or f"(URL pendiente de Zernio; postId {existe_pos})"
            print(f"  {item['plataforma']}: {registro['status']} "
                  f"({item['archivo'].name}) {cola_url}")
        except zernio.ZernioError as exc:
            print(f"  ZERNIO ERROR en {item['plataforma']} ({item['archivo'].name}): {exc}")
            resultados.append({"plataforma": item["plataforma"], "archivo": item["archivo"].name,
                               "postId": None, "status": "failed", "error": str(exc)})

    ep.write_json("publicacion/zernio.json", {"plan": [f"{i['plataforma']}:{i['archivo'].name}" for i in plan],
                                              "resultados": resultados,
                                              "pendiente_humano": "toggle 'contenido alterado' en YouTube Studio"})
    # post.status documentado: draft|pending_approval|scheduled|publishing|published|partial|failed|cancelled.
    # Sólo `published` es "el mundo ya lo ve". `scheduled`/`publishing` no son fallo (Zernio
    # reintenta solo) pero tampoco son éxito: contarlos como publicados era el éxito falso.
    publicados = [r for r in resultados if r.get("status") == "published" and r.get("url")]
    en_curso = [r for r in resultados if r.get("status") in ("scheduled", "publishing", "duplicate")]
    if not publicados and not en_curso:
        meta["publish_status"] = "AUTO_PUBLISH_FALLÓ"
    elif publicados and len(publicados) == len(plan):
        meta["publish_status"] = "AUTO_PUBLISHED"
    else:
        meta["publish_status"] = "AUTO_PUBLISHED_PARCIAL"
    meta["publish_urls"] = {r["plataforma"]: r.get("url") for r in resultados if r.get("url")}
    ep.save_metadata(meta)
    print(f"  publicación: {len(publicados)}/{len(plan)} publicados confirmados"
          f"{f', {len(en_curso)} en curso' if en_curso else ''} -> {meta['publish_status']}")
    return {"resultados": resultados, "plan": len(plan), "exitosas": len(publicados),
            "en_curso": len(en_curso), "estado": meta["publish_status"]}
