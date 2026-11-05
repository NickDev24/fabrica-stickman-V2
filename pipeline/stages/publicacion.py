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
- Miniatura/portada: `derivados/portada.jpg` — imagen del clímax + pregunta gancho;
  subirla como miniatura personalizada (es la imagen que frena el scroll y la que se ve en pausa)
- [ ] Revisar video, fuentes, audio y subtítulos antes de subir
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
                                                     "fuentes": fuentes})
    ep.set_stage("publicacion", "checklist_listo")
    print(f"  checklist -> {path.relative_to(ep.dir)} | publicar sigue BLOQUEADO hasta aprobación humana")
    return path


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
    hashtags = "#PulsoCurioso #curiosidades #documental"
    nicho = str(ep.read_state().get("categoria", "")).replace("-", "")
    if nicho:
        hashtags += f" #{nicho}"
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
    """Deja el guion en el registro para el gate anti-duplicado (gate 4)."""
    script = ep.read_text("script.txt")
    config.REGISTRY.mkdir(parents=True, exist_ok=True)
    with (config.REGISTRY / "published.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({"slug": ep.slug, "estado": estado,
            "ts": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
                             "script": script}, ensure_ascii=False) + "\n")
    print(f"  {ep.slug} registrado en registry/published.jsonl ({estado})")


def publicar_automatico(ep: Episode, no_publish: bool = False, aprobado: str | None = None) -> dict:
    """Sube los derivados a Zernio y publica.

    Con AUTO_PUBLISH activo (hay key en .env) es publishNow; con --no-publicar queda
    como draft. La aprobación explícita del dueño (botón "✅ APROBAR Y PUBLICAR" de
    Telegram, o "/aprobar <slug>") habilita publicar aunque la ruta sea audiovisual:
    justamente esa "revisión humana" es lo que el dueño cambia con su toque.
    """
    from .. import gates, zernio
    meta = ep.metadata()
    gates.gate_publicacion(meta)  # gate 7: flag sintético obligatorio antes de salir al mundo
    manifest_path = ep.artifacts / "derivados-manifest.json"
    if aprobado != "user" and manifest_path.exists() and (ep.read_json("derivados-manifest.json") or {}).get("ruta") in (
            "keyframe", "avatar_fallback"):
        print("  ruta audiovisual en revisión: YouTube/Facebook no se publican automáticamente")
        return {"status": "revision_humana_requerida"}
    if no_publish and aprobado != "user":
        print("  publicación automática OFF (AUTO_PUBLISH=false o --no-publicar): sólo borradores/checklist")
        return {"status": "sin_publicar"}
    if aprobado != "user" and not config.auto_publish():
        print("  AUTO_PUBLISH del .env desactivado: no se publica")
        return {"status": "sin_publicar"}

    z = config.zernio_config()
    if not z["api_key"]:
        raise SystemExit("AUTO_PUBLISH activo pero falta ZERNIO_API_KEY")
    ids = {"youtube": z["youtube"], "facebook": z["facebook"]}
    if not ids["youtube"]:
        raise SystemExit("Falta ZERNIO_ID_YOUTUBE en .env")

    desc = ep.read_json("publicacion/descripciones.json")
    resultados = []
    try:
        for i, parte in enumerate(sorted((ep.dir / "derivados").glob("yt-parte-*.mp4")), 1):
            url = zernio.upload(parte)
            post = zernio.create_post(
                desc["descripcion"], [url],
                [{"platform": "youtube", "accountId": ids["youtube"],
                  "platformSpecificData": {"title": f"{desc['titulo']} (parte {i} de 3)"}}])
            resultados.append({"archivo": parte.name, "postId": post.get("_id"), "status": post.get("status")})
            print(f"  publicado {parte.name} -> youtube ({post.get('status')})")
        if ids["facebook"]:
            for trailer, label in (("tiktok-trailer-90s.mp4", "Adelanto"), ("instagram-trailer-30s.mp4", "Adelanto 30s")):
                f = ep.dir / "derivados" / trailer
                if not f.exists():
                    continue
                url = zernio.upload(f)
                post = zernio.create_post(f"{label}: {desc['descripcion']}", [url],
                                          [{"platform": "facebook", "accountId": ids["facebook"]}])
                resultados.append({"archivo": trailer, "postId": post.get("_id"), "status": post.get("status")})
                print(f"  publicado {trailer} -> facebook ({post.get('status')})")
    except zernio.ZernioError as exc:
        print(f"  ZERNIO ERROR: {exc} — el episodio queda listo en checklist + Telegram")
        resultados.append({"error": str(exc)})

    ep.write_json("publicacion/zernio.json", {"resultados": resultados,
                                              "pendiente_humano": "toggle 'contenido alterado' en YouTube Studio"})
    meta["publish_status"] = "AUTO_PUBLISHED" if all(r.get("status") for r in resultados if "postId" in r) else "AUTO_PUBLISH_FALLÓ"
    ep.save_metadata(meta)
    return {"resultados": resultados}
