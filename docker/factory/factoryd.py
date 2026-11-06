"""factoryd — supervisor de la fábrica de contenido PULSO (24/7, dentro de Docker).

Un solo proceso HTTP: REST para control y estado, WebSocket /ws para eventos en vivo.
Corre `python -m pipeline.run auto` de punta a punta, en loop 24/7, y emite:

  - cada línea del stdout/stderr clasificada (info/idea/keyframe/audio/gate/error...),
  - el estado por etapa leído de projects/<slug>/episode.json (fuente de verdad del disco),
  - métricas del contenedor (CPU/RAM/disco), cuota de Workers AI y resultado por episodio.

Reglas (CODEX.md):
  - No borra nada. No publica al mundo salvo FACTORY_PUBLISH=1 (--no-publicar por defecto).
  - Al agotarse ideas verificadas (SystemExit del auto), backoff y reintento. Nunca spam.
  - El modo vive en state/factoryd.json para sobrevivir reinicios del contenedor.
"""
from __future__ import annotations

import asyncio
import collections
import json
import os
import re
import shutil
import time
from pathlib import Path

import aiohttp
import psutil
from aiohttp import web

ROOT = Path("/app")
STATE = ROOT / "state"
PROJECTS = ROOT / "projects"
LOG_FILE = STATE / "logs" / "factoryd.log"
CTRL = STATE / "factoryd.json"
CONECTORES_FILE = STATE / "conectores.json"

PUERTO = int(os.environ.get("FACTORYD_PORT", "8610"))
COOLDOWN_S = int(os.environ.get("FACTORY_COOLDOWN_S", "60"))
BACKOFF_IDEAS_S = int(os.environ.get("FACTORY_BACKOFF_IDEAS_S", "900"))
PUBLISH = os.environ.get("FACTORY_PUBLISH", "").strip().lower() in ("1", "true", "yes", "on")
AUTOSTART = os.environ.get("FACTORY_AUTOSTART", "1").strip().lower() in ("1", "true", "yes", "on")

RING_LEN = 600  # líneas de log en memoria para el replay a clientes nuevos

PAT_EPISODIO = re.compile(r"== episodio (\S+)")
PAT_IDEA = re.compile(r"idea elegida")
PAT_KF = re.compile(r"keyframes: (\d+) imágenes \((\d+) nuevas, (\d+) recicladas")
PAT_TOTAL = re.compile(r"TOTAL: (\d+)s")
PAT_MALO = re.compile(r"ERROR|BLOQUEADO|Traceback")
SLUG_OK = re.compile(r"^[a-z0-9-]+$")
NOMBRE_OK = re.compile(r"^[A-Za-z0-9_.-]+$")


def clase_de(linea: str) -> str:
    if PAT_MALO.search(linea):
        return "error"
    if PAT_IDEA.search(linea):
        return "idea"
    if "imagen:" in linea or "keyframes:" in linea or "placa" in linea:
        return "keyframe"
    if "piper" in linea.lower() or "narración" in linea.lower() or "voz" in linea.lower():
        return "audio"
    if "telegram" in linea.lower():
        return "publicar"
    if "gate" in linea.lower():
        return "gate"
    if "fábrica:" in linea:
        return "fab"
    if linea.startswith("== episodio"):
        return "episodio"
    return "info"


def log_local(msg: str) -> None:
    try:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with LOG_FILE.open("a", encoding="utf-8") as fh:
            fh.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}\n")
    except OSError:
        pass


estado = {
    "modo": "idle",           # idle | corriendo | deteniendo
    "ep": None,
    "ep_inicio": 0.0,
    "episodios_hoy": 0,
    "arranque": time.time(),
    "ultima_salida": None,
    "fallas": 0,
}

RING: collections.deque = collections.deque(maxlen=RING_LEN)
CLIENTES: set = set()
ciclo: dict = {}  # {"salto": Event, "proc": proc}


def cargar_ctrl() -> dict:
    try:
        return json.loads(CTRL.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def guardar_ctrl() -> None:
    try:
        CTRL.parent.mkdir(parents=True, exist_ok=True)
        CTRL.write_text(json.dumps({"modo": estado["modo"], "ep": estado["ep"]},
                                   ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass


# ----------------------------------------------------------------- eventos y WS
async def emitir(evento: dict) -> None:
    evento = {"ts": time.strftime("%H:%M:%S"), **evento}
    if evento.get("t") == "log":
        RING.append(evento)
    for ws in tuple(CLIENTES):
        try:
            await ws.send_json(evento)
        except (ConnectionError, RuntimeError):
            CLIENTES.discard(ws)


async def snapshot(wsr: web.WebSocketResponse) -> None:
    await wsr.send_json({"t": "hello", "modo": estado["modo"], "ep": estado["ep"],
                         "ep_inicio": estado["ep_inicio"],
                         "episodios_hoy": estado["episodios_hoy"],
                         "arranque": estado["arranque"], "publish": PUBLISH,
                         "recientes": list(RING)})


def metricas_sistema() -> dict:
    quota = {}
    try:
        uso = json.loads((STATE / "workers_ai_usage.json").read_text(encoding="utf-8"))
        hoy = time.strftime("%Y-%m-%d")
        if str(uso.get("dia_utc", "")).startswith(hoy):
            quota = {"usadas": int(uso.get("solicitudes_exitosas", 0)),
                     "limite": int(uso.get("limite_local", 0)),
                     "costo_usd": float(uso.get("costo_usd_estimado", 0.0))}
    except (OSError, ValueError, json.JSONDecodeError):
        pass
    disco = shutil.disk_usage(ROOT if ROOT.exists() else "/")
    memoria = psutil.virtual_memory()
    carga = os.getloadavg()[0] if hasattr(os, "getloadavg") else 0.0
    return {"cpu": round(psutil.cpu_percent(interval=None), 1),
            "ram": {"pct": round(memoria.percent, 1),
                    "usada_gb": round(memoria.used / 1e9, 2),
                    "total_gb": round(memoria.total / 1e9, 2)},
            "disco": {"pct": round(100 * disco.used / max(1, disco.total), 1),
                      "libre_gb": round(disco.free / 1e9, 2)},
            "quota": quota, "carga": round(carga, 2)}


def titulo_ep(slug: str) -> str:
    try:
        return json.loads((PROJECTS / slug / "episode.json").read_text(
            encoding="utf-8")).get("title", "")
    except (OSError, json.JSONDecodeError):
        return ""


def metrics_ep(slug: str) -> dict:
    salida = {}
    for nombre in ("render_keyframes.json", "render_corto.json", "qc.json"):
        p = PROJECTS / slug / "artifacts" / nombre
        if p.is_file():
            try:
                salida[nombre.removesuffix(".json")] = json.loads(p.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                pass
    return salida


def episodios() -> list[dict]:
    lista = []
    if not PROJECTS.is_dir():
        return lista
    for d in sorted(PROJECTS.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True)[:30]:
        meta = d / "episode.json"
        if not meta.is_file():
            continue
        try:
            dat = json.loads(meta.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        lista.append({"slug": dat.get("slug", d.name), "titulo": dat.get("title", ""),
                      "categoria": dat.get("categoria", ""),
                      "stages": dat.get("stage_status", {}),
                      "mtime": int(meta.stat().st_mtime)})
    return lista


# ------------------------------------------------------------------ bucle 24/7
async def poll_etapas() -> None:
    """Emite cambios de stage_status del episodio actual (projects/<slug>/episode.json)."""
    previo: dict = {}
    while True:
        slug = estado["ep"]
        if slug and SLUG_OK.match(slug):
            try:
                st = json.loads((PROJECTS / slug / "episode.json").read_text(
                    encoding="utf-8")).get("stage_status", {})
            except (OSError, json.JSONDecodeError):
                st = {}
            if st != previo:
                for etapa, valor in st.items():
                    if previo.get(etapa) != valor:
                        await emitir({"t": "stage", "ep": slug, "stage": etapa, "status": valor})
                previo = dict(st)
        await asyncio.sleep(1.5)


async def correr_proceso(cmd: list[str]) -> tuple[int, str]:
    """Lanza el pipeline, emite cada línea, devuelve (rc, línea TOTAL)."""
    proc = await asyncio.subprocess.create_subprocess_exec(
        *cmd, cwd=str(ROOT), env={**os.environ, "PYTHONUNBUFFERED": "1"},
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
        bufsize=0)
    ciclo["proc"] = proc
    linea_total = ""

    async def bombear(stream):
        nonlocal linea_total
        buf = b""
        while True:
            pedazo = await stream.read(4096)
            if not pedazo:
                break
            buf += pedazo
            while b"\n" in buf:
                cruda, buf = buf.split(b"\n", 1)
                linea = cruda.decode("utf-8", "replace").rstrip()
                if not linea:
                    continue
                await emitir({"t": "log", "linea": linea, "clase": clase_de(linea)})
                log_local(linea)
                m = PAT_KF.search(linea)
                if m:
                    await emitir({"t": "imgs", "total": int(m.group(1)),
                                  "nuevas": int(m.group(2)), "recicladas": int(m.group(3))})
                m = PAT_EPISODIO.search(linea)
                if m and m.group(1) != estado["ep"]:
                    estado["ep"] = m.group(1)
                    estado["ep_inicio"] = time.time()
                    await emitir({"t": "ep_ini", "ep": estado["ep"],
                                  "titulo": titulo_ep(estado["ep"])})
                    guardar_ctrl()
                m = PAT_TOTAL.search(linea)
                if m:
                    linea_total = m.group(0)
        # cola sin salto de línea al final del proceso
        resto = buf.decode("utf-8", "replace").strip()
        if resto:
            await emitir({"t": "log", "linea": resto, "clase": clase_de(resto)})

    lector = asyncio.ensure_future(bombear(proc.stdout))
    try:
        rc = await proc.wait()
    finally:
        ciclo.pop("proc", None)
        lector.cancel()
        try:
            await lector
        except asyncio.CancelledError:
            pass
    return rc, linea_total


async def bucle_247() -> None:
    """El motor 24/7: episodio tras episodio con `pipeline.run auto`; pausa ece entre etapas."""
    estado["modo"] = "corriendo"
    guardar_ctrl()
    await emitir({"t": "status", "modo": estado["modo"]})
    try:
        while estado["modo"] == "corriendo":
            cmd = ["/usr/local/bin/python", "-m", "pipeline.run", "auto"]
            if not PUBLISH:
                cmd.append("--no-publicar")
            salto: asyncio.Event = ciclo["salto"]
            salto.clear()
            corredor = asyncio.ensure_future(correr_proceso(cmd))
            esperador = asyncio.ensure_future(salto.wait())
            hechos, _ = await asyncio.wait({corredor, esperador},
                                           return_when=asyncio.FIRST_COMPLETED)
            if corredor in hechos:
                rc, total = corredor.result()
            else:
                # salto (skip/stop) aborta el episodio en curso y sigo con el próximo
                esperador.cancel()
                proc = ciclo.get("proc")
                if proc is not None:
                    try:
                        proc.terminate()
                        await asyncio.wait_for(proc.wait(), timeout=15)
                    except (ProcessLookupError, asyncio.TimeoutError):
                        pass
                rc, total = await corredor
            slug = estado["ep"] or ""
            metrics = metrics_ep(slug) if slug else {}
            estado["ultima_salida"] = {"rc": rc, "total": total, "ep": slug,
                                       "ts": time.time(), "metrics": metrics}
            if rc == 0:
                estado["episodios_hoy"] += 1
                estado["fallas"] = 0
            else:
                estado["fallas"] += 1
            await emitir({"t": "ep_fin", "ep": slug, "rc": rc, "total": total,
                          "metrics": metrics})
            guardar_ctrl()
            if estado["modo"] != "corriendo":
                break
            if rc != 0:
                # sin ideas nuevas verificadas o fallo duro: backoff y reintento, sin spam
                pausa = BACKOFF_IDEAS_S if estado["fallas"] >= 2 else 60
                await emitir({"t": "status", "modo": "corriendo",
                              "msg": f"backoff {pausa}s antes del próximo episodio"})
                await asyncio.sleep(pausa)
                if estado["modo"] != "corriendo":
                    break
                continue
            # 24/7 sin pausa (decisión del dueño): cooldown corto sólo para asentar disco
            await asyncio.sleep(COOLDOWN_S)
    finally:
        estado["modo"] = "idle"
        estado["ep"] = None
        guardar_ctrl()
        await emitir({"t": "status", "modo": "idle"})


# ------------------------------------------------------------------------ REST
async def api_estado(req: web.Request) -> web.Response:
    return web.json_response({"modo": estado["modo"], "ep": estado["ep"],
                              "ep_inicio": estado["ep_inicio"],
                              "uptime_s": int(time.time() - estado["arranque"]),
                              "episodios_hoy": estado["episodios_hoy"],
                              "ultima_salida": estado["ultima_salida"],
                              "publish": PUBLISH,
                              "sys": metricas_sistema(),
                              "episodios": episodios()})


async def api_episodios(req: web.Request) -> web.Response:
    return web.json_response(episodios())


async def api_logs(req: web.Request) -> web.Response:
    n = max(1, min(len(RING) or 1, int(req.query.get("n", "200"))))
    return web.json_response(list(RING)[-n:])


def _imgs_keyframes(slug: str, limite: int = 8) -> list[str]:
    carpeta = PROJECTS / slug / "assets" / "kf"
    if not (SLUG_OK.match(slug) and carpeta.is_dir()):
        return []
    archs = [p for p in carpeta.glob("kf-*")
             if p.suffix.lower() in (".jpg", ".jpeg", ".png") and p.is_file()]
    return [f"/img/{slug}/{p.name}" for p in archs[-limite:]]


async def api_kfs(req: web.Request) -> web.Response:
    return web.json_response(_imgs_keyframes(req.match_info["slug"],
                                             int(req.query.get("n", "8"))))


def _comics_de(slug: str) -> dict | None:
    """Resumen del capítulo comics.v2 del episodio (si existe)."""
    base = PROJECTS / slug / "comics"
    if not (SLUG_OK.match(slug) and base.is_dir()):
        return None
    salida = {"paginas": [], "vinetas": 0, "paginas_n": 0, "grillas": [],
              "qc_aprobado": False, "titulo_chapter": ""}
    try:
        dat = json.loads((base / "guion_paneles.json").read_text(encoding="utf-8"))
        salida["vinetas"] = len(dat.get("paneles", []))
        salida["grillas"] = dat.get("grillas", [])
        salida["titulo_chapter"] = dat.get("titulo", "")
    except (OSError, json.JSONDecodeError):
        pass
    try:
        qc = json.loads((base / "qc.json").read_text(encoding="utf-8"))
        salida["qc_aprobado"] = bool(qc.get("aprobado"))
        salida["paginas_n"] = int(qc.get("paginas", 0))
    except (OSError, json.JSONDecodeError):
        pass
    d = base / "pages"
    if d.is_dir():
        salida["paginas"] = [f"/img/{slug}/{p.name}"
                             for p in sorted(d.glob("pag-*.png"))]
    d = base / "paneles"
    if d.is_dir():
        salida["vinetas_imgs"] = [f"/img/{slug}/{p.name}" for p in sorted(d.glob("p-*.jpg"))]
    if not (salida["paginas"] or salida["vinetas_imgs"]):
        return None
    return salida


def _pub_de(slug: str) -> dict:
    """URLs publicadas (zernio + reconciliación) para los badges del feed."""
    try:
        dat = json.loads((PROJECTS / slug / "artifacts" / "publicacion" /
                          "zernio.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    pub = {}
    for r in dat.get("resultados", []):
        if isinstance(r, dict) and r.get("url"):
            pub[str(r.get("plataforma", "")).lower()] = str(r["url"])
    return pub


def _videos_de(slug: str) -> list[dict]:
    """Reproducciones disponibles: master + derivados, con etiqueta legible."""
    bases = (("-main.mp4", "Episodio completo"),
             ("-keyframe.mp4", "Capítulo con comentarios"))
    sufijos = (("trailer-a", "Trailer → Facebook"),
               ("trailer-b", "Trailer → YouTube"),
               ("facebook-reel", "Facebook Reel"),
               ("youtube-short", "YouTube Short"),
               ("kf-silent", "Preview sin música"),
               ("preview", "Preview"))
    videos = []
    vistos = set()
    for sub in ("renders", "derivados"):
        d = PROJECTS / slug / sub
        if not d.is_dir():
            continue
        for p in sorted(d.glob("*.mp4")):
            if p.name in vistos or p.stat().st_size < 50_000:
                continue
            vistos.add(p.name)
            base = p.name[:-4].lower() if p.name.lower().endswith(".mp4") else p.name.lower()
            lab = next((l for s, l in bases if p.name.lower().endswith(s)),
                       next((l for s, l in sufijos if base.endswith(s)),
                            base.replace("-", " ")))
            videos.append({"archivo": p.name, "url": f"/media/{slug}/{p.name}", "label": lab})
    videos.sort(key=lambda v: 0 if "completo" in v["label"] else 1)
    return videos


def galeria() -> list[dict]:
    """Feed de la red social: Qué se publicó, qué videos hay, qué viñetas hay."""
    items = []
    for ep in episodios():
        slug = ep["slug"]
        portada = ""
        for candidato in ("portada-yt.jpg", "portada.jpg"):
            if (PROJECTS / slug / "derivados" / candidato).is_file():
                portada = f"/img/{slug}/{candidato}"
                break
        items.append({
            **ep,
            "portada": portada,
            "videos": _videos_de(slug),
            "pub": _pub_de(slug),
            "comics": _comics_de(slug),
            "kfs": _imgs_keyframes(slug, 24),
        })
    return items


async def api_galeria(req: web.Request) -> web.Response:
    return web.json_response(galeria())


def _leer_rango(rango: str, total: int) -> tuple[int, int]:
    """bytes=START- | bytes=START-END | bytes=-N (RFC 7233 mínimo)."""
    mx = re.match(r"bytes=(\d*)-(\d*)$", rango.strip())
    inicio, fin = 0, total - 1
    if mx:
        if mx.group(1):
            inicio = int(mx.group(1))
            if mx.group(2):
                fin = min(int(mx.group(2)), total - 1)
        elif mx.group(2):                     # bytes=-N: últimos N bytes
            inicio = max(0, total - int(mx.group(2)))
    return inicio, fin


async def media(req: web.Request) -> web.Response:
    """Streaming de video con soporte de Range (el <video> puede buscar)."""
    slug, nombre = req.match_info["slug"], req.match_info["nombre"]
    if not (SLUG_OK.match(slug) and NOMBRE_OK.match(nombre)) \
            or not nombre.lower().endswith(".mp4"):
        return web.Response(status=404, text="no")
    ruta = None
    for base in ("renders", "derivados"):
        c = PROJECTS / slug / base / nombre
        if c.is_file() and c.stat().st_size > 0:
            ruta = c
            break
    if ruta is None:
        return web.Response(status=404, text="nada")
    total = ruta.stat().st_size
    rango = req.headers.get("Range", "")
    inicio, fin = _leer_rango(rango, total)
    if inicio > fin or inicio >= total:
        resp = web.Response(status=416)
        resp.headers["Content-Range"] = f"bytes */{total}"
        return resp
    parcial = rango.startswith("bytes=")
    fin = min(fin, total - 1)
    with ruta.open("rb") as fh:
        fh.seek(inicio)
        data = fh.read(fin - inicio + 1)
    resp = web.Response(body=data, status=206 if parcial else 200,
                        content_type="video/mp4")
    resp.headers["Accept-Ranges"] = "bytes"
    if parcial:
        resp.headers["Content-Range"] = f"bytes {inicio}-{fin}/{total}"
    return resp


async def img(req: web.Request) -> web.Response:
    slug, nombre = req.match_info["slug"], req.match_info["nombre"]
    if not (SLUG_OK.match(slug) and NOMBRE_OK.match(nombre)):
        return web.Response(status=404, text="no")
    for ruta in (PROJECTS / slug / "derivados" / nombre,
                 PROJECTS / slug / "comics" / "pages" / nombre,
                 PROJECTS / slug / "comics" / "carrusel" / nombre,
                 PROJECTS / slug / "comics" / "paneles" / nombre,
                 PROJECTS / slug / "assets" / "kf" / nombre,
                 PROJECTS / slug / "artifacts" / nombre):
        if ruta.is_file():
            tipo = "image/png" if ruta.suffix.lower() == ".png" else "image/jpeg"
            return web.Response(body=ruta.read_bytes(), content_type=tipo)
    return web.Response(status=404, text="nada")


async def api_control(req: web.Request) -> web.Response:
    global PUBLISH
    try:
        body = await req.json()
    except (json.JSONDecodeError, aiohttp.ClientError):
        body = {}
    accion = str(body.get("accion", "")).lower()
    salto: asyncio.Event | None = ciclo.get("salto")

    if accion == "play":
        if estado["modo"] == "idle":
            ciclo["salto"] = asyncio.Event()
            asyncio.ensure_future(bucle_247())
            return web.json_response({"ok": True, "modo": "corriendo"})
        return web.json_response({"ok": False, "modo": estado["modo"]})

    if accion == "pausa" and estado["modo"] == "corriendo":
        # pausa limpia: termina el episodio en curso y no lanza otro
        estado["modo"] = "deteniendo"
        guardar_ctrl()
        return web.json_response({"ok": True, "modo": estado["modo"]})

    if accion == "stop":
        estado["modo"] = "deteniendo"
        guardar_ctrl()
        if salto is not None:
            salto.set()  # aborta también el episodio actual
        return web.json_response({"ok": True, "modo": estado["modo"]})

    if accion == "skip":
        if salto is not None and estado["modo"] == "corriendo":
            salto.set()
        return web.json_response({"ok": True})

    if accion == "publicar_on":
        PUBLISH = True
        guardar_ctrl()
        return web.json_response({"ok": True, "publica": True})

    if accion == "publicar_off":
        PUBLISH = False
        guardar_ctrl()
        return web.json_response({"ok": True, "publica": False})

    return web.json_response({"ok": False, "error": "acción desconocida"}, status=400)


async def api_health(req: web.Request) -> web.Response:
    return web.json_response({"ok": True})


# ------------------------------------------------------------------ métricas reales (YT + FB)
def _leer_metricas() -> dict:
    """Agrega state/metricas.jsonl (último corte por plataforma) para el panel de métricas."""
    ruta = STATE / "metricas.jsonl"
    filas = []
    if ruta.exists():
        for linea in ruta.read_text(encoding="utf-8").splitlines():
            linea = linea.strip()
            if not linea:
                continue
            try:
                filas.append(json.loads(linea))
            except json.JSONDecodeError:
                continue
    vacios = [[0, 0], [1, 0], [2, 0], [3, 0], [4, 0], [5, 0], [6, 0]]
    out = {"yt": None, "fb": None,
           "emocion": {"predominante": None, "reacciones": {}},
           "seguidores": 200, "seguidores_dia": [[i, 200] for i in range(7)],
           "disponible": bool(filas), "ultima_actualizacion": None}
    por_plataforma = {"youtube": "yt", "facebook": "fb"}
    mejores = {}
    for f in filas:
        clave = (f.get("slug"), f.get("plataforma"))
        act = mejores.get(clave)
        if act is None or str(f.get("fecha") or "") >= str(act.get("fecha") or ""):
            mejores[clave] = f
    for (slug, plataforma), f in mejores.items():
        clave = por_plataforma.get(str(plataforma).lower())
        if not clave:
            continue
        prev = out[clave]
        if prev is None or (f.get("fecha") or "") >= (prev.get("fecha") or ""):
            out[clave] = f
    for clave in ("yt", "fb"):
        f = out[clave]
        if f:
            v = f.get("vistas") or 0
            out[clave] = {"vistas": v, "reacciones": f.get("likes") or 0,
                          "comentarios": f.get("comentarios") or 0,
                          "compartidos": f.get("compartidos") or 0,
                          "fecha": f.get("fecha")}
            pts = [[i, (x.get("vistas") or 0)] for i, x in enumerate(
                [z for z in filas if (z.get("plataforma") or "").lower() == ("youtube" if clave == "yt" else "facebook")])]
            out[clave + "_puntos"] = pts or vacios
        else:
            out[clave + "_puntos"] = vacios
    emociones = {}
    for f in filas:
        extra = f.get("extra") or {}
        emo = extra.get("emocion") or f.get("emocion")
        if emo:
            emociones[emo] = emociones.get(emo, 0) + 1
    if emociones:
        out["emocion"] = {"predominante": max(emociones, key=emociones.get), "reacciones": emociones}
    seg = None
    for f in reversed(filas):
        if isinstance(f.get("seguidores"), (int, float)):
            seg = int(f["seguidores"]); break
    if seg is not None:
        out["seguidores"] = seg
        out["seguidores_dia"] = [[i, seg] for i in range(7)]
    if filas:
        out["ultima_actualizacion"] = filas[-1].get("fecha")
    return out


async def api_metricas(req: web.Request) -> web.Response:
    return web.json_response(_leer_metricas())


# ------------------------------------------------------------------ conectores MCP (REAL)
_CONECTORES_CACHE: dict | None = None


def _conectores_cargar() -> dict:
    """Carga la configuración de conectores desde state/conectores.json."""
    global _CONECTORES_CACHE
    if _CONECTORES_CACHE is not None:
        return _CONECTORES_CACHE
    try:
        datos = json.loads(CONECTORES_FILE.read_text(encoding="utf-8"))
        if isinstance(datos, dict) and "conectores" in datos:
            _CONECTORES_CACHE = datos["conectores"]
            return _CONECTORES_CACHE
    except (OSError, json.JSONDecodeError):
        pass
    _CONECTORES_CACHE = {}
    return _CONECTORES_CACHE


def _conectores_guardar(conectores: dict) -> None:
    """Persiste la configuración de conectores en state/conectores.json."""
    global _CONECTORES_CACHE
    CONECTORES_FILE.parent.mkdir(parents=True, exist_ok=True)
    CONECTORES_FILE.write_text(
        json.dumps({"conectores": conectores}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    _CONECTORES_CACHE = conectores


def _mascarar_token(token: str | None) -> str:
    """Devuelve el token mascarado para exposiciones seguras (GET)."""
    if not token:
        return ""
    if len(token) <= 8:
        return "*" * len(token)
    return token[:4] + "*" * (len(token) - 8) + token[-4:]


def _conectores_publicos() -> list[dict]:
    """Lista conectores con datos de configuración (tokens mascarados) para el front."""
    conectores = _conectores_cargar()
    salida = []
    for platform, c in conectores.items():
        salida.append({
            "platform": platform,
            "nombre": c.get("nombre", platform),
            "tipo": c.get("tipo", "mcp"),
            "endpoint": c.get("endpoint", ""),
            "auth_tipo": c.get("auth_tipo", "none"),
            "token": _mascarar_token(c.get("token", "")),
            "scopes": c.get("scopes", []),
            "headers_extra": c.get("headers_extra", {}),
            "estado": c.get("estado", "pend"),
            "ultimo_test": c.get("ultimo_test"),
            "ultimo_error": c.get("ultimo_error"),
            "capacidades": c.get("capacidades", []),
            "origen": c.get("origen", "configurado"),
        })
    return salida


async def _mcp_handshake(endpoint: str, auth_tipo: str, token: str,
                         headers_extra: dict, timeout: float = 10.0) -> tuple[bool, str | None, list[str]]:
    """Handshake MCP real contra el endpoint configurado.

    Ejecuta JSON-RPC `initialize` y `tools/list` para validar que el servidor
    MCP responde y devuelve sus capacidades/tools. Devuelve (ok, error, capacidades).
    """
    import aiohttp
    headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
    if auth_tipo == "bearer" and token:
        headers["Authorization"] = f"Bearer {token}"
    elif auth_tipo == "api_key" and token:
        headers["X-API-Key"] = token
    elif auth_tipo == "custom" and token:
        headers["Authorization"] = token
    headers.update(headers_extra or {})

    payload_init = {
        "jsonrpc": "2.0", "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "pulso-factory", "version": "1.0.0"},
        },
    }
    payload_tools = {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}

    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=timeout)) as session:
            async with session.post(endpoint, headers=headers, json=payload_init) as r:
                if r.status not in (200, 201):
                    return False, f"initialize HTTP {r.status}", []
                datos = await r.json()
                caps = []
                if isinstance(datos, dict):
                    result = datos.get("result") or {}
                    server_caps = result.get("capabilities") or {}
                    if isinstance(server_caps, dict):
                        caps = [k for k, v in server_caps.items() if v]
            # tools/list (opcional: algunos servidores solo exponen initialize)
            try:
                async with session.post(endpoint, headers=headers, json=payload_tools) as r2:
                    if r2.status in (200, 201):
                        d2 = await r2.json()
                        tools = (d2 or {}).get("result", {}).get("tools", [])
                        if isinstance(tools, list):
                            caps += [str(t.get("name", "tool")) for t in tools]
            except Exception:
                pass
            return True, None, sorted(set(caps))
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        return False, str(exc)[:200], []


async def api_conectores(req: web.Request) -> web.Response:
    return web.json_response(_conectores_publicos())


async def api_conectores_agregar(req: web.Request) -> web.Response:
    """Registra un conector MCP con su configuración real (endpoint, auth, token, scopes)."""
    try:
        body = await req.json()
    except Exception:
        body = {}
    platform = str(body.get("platform", "")).strip().lower()
    nombre = str(body.get("nombre", platform)).strip()
    endpoint = str(body.get("endpoint", "")).strip()
    auth_tipo = str(body.get("auth_tipo", "none")).strip().lower()
    token = str(body.get("token", "")).strip()
    scopes = body.get("scopes") or []
    headers_extra = body.get("headers_extra") or {}

    if not platform:
        return web.json_response({"ok": False, "error": "platform requerido"}, status=400)
    if auth_tipo not in ("none", "bearer", "api_key", "custom"):
        return web.json_response({"ok": False, "error": "auth_tipo inválido"}, status=400)

    conectores = _conectores_cargar()
    conectores[platform] = {
        "nombre": nombre,
        "tipo": "mcp",
        "endpoint": endpoint,
        "auth_tipo": auth_tipo,
        "token": token,
        "scopes": list(scopes) if isinstance(scopes, list) else [],
        "headers_extra": headers_extra if isinstance(headers_extra, dict) else {},
        "estado": "pend",
        "ultimo_test": None,
        "ultimo_error": None,
        "capacidades": [],
        "origen": "configurado",
    }
    _conectores_guardar(conectores)
    return web.json_response({"ok": True, "platform": platform, "nombre": nombre})


async def api_conectores_actualizar(req: web.Request) -> web.Response:
    """Actualiza la configuración de un conector MCP existente."""
    platform = req.match_info.get("platform", "").strip().lower()
    if not platform:
        return web.json_response({"ok": False, "error": "platform requerido"}, status=400)
    conectores = _conectores_cargar()
    if platform not in conectores:
        return web.json_response({"ok": False, "error": "conector no encontrado"}, status=404)
    try:
        body = await req.json()
    except Exception:
        body = {}
    c = conectores[platform]
    for campo in ("nombre", "endpoint", "auth_tipo", "token", "scopes", "headers_extra"):
        if campo in body:
            val = body[campo]
            if campo == "auth_tipo" and str(val).lower() not in ("none", "bearer", "api_key", "custom"):
                return web.json_response({"ok": False, "error": "auth_tipo inválido"}, status=400)
            if campo == "scopes" and not isinstance(val, list):
                val = []
            if campo == "headers_extra" and not isinstance(val, dict):
                val = {}
            c[campo] = val
    c["estado"] = "pend"
    c["ultimo_test"] = None
    c["ultimo_error"] = None
    c["capacidades"] = []
    _conectores_guardar(conectores)
    return web.json_response({"ok": True, "platform": platform})


async def api_conectores_eliminar(req: web.Request) -> web.Response:
    """Elimina un conector MCP configurado."""
    platform = req.match_info.get("platform", "").strip().lower()
    if not platform:
        return web.json_response({"ok": False, "error": "platform requerido"}, status=400)
    conectores = _conectores_cargar()
    if platform not in conectores:
        return web.json_response({"ok": False, "error": "conector no encontrado"}, status=404)
    del conectores[platform]
    _conectores_guardar(conectores)
    return web.json_response({"ok": True, "platform": platform})


async def api_conectores_probar(req: web.Request) -> web.Response:
    """Prueba de conexión REAL contra el endpoint MCP configurado (handshake JSON-RPC)."""
    platform = req.match_info.get("platform", "").strip().lower()
    if not platform:
        try:
            body = await req.json()
            platform = str(body.get("platform", "")).strip().lower()
        except Exception:
            pass
    if not platform:
        return web.json_response({"ok": False, "error": "platform requerido"}, status=400)
    conectores = _conectores_cargar()
    c = conectores.get(platform)
    if not c:
        return web.json_response({"ok": False, "error": "conector no configurado"}, status=404)

    ok, error, caps = await _mcp_handshake(
        c.get("endpoint", ""),
        c.get("auth_tipo", "none"),
        c.get("token", ""),
        c.get("headers_extra", {}),
    )
    c["estado"] = "ok" if ok else "err"
    c["ultimo_test"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    c["ultimo_error"] = error
    c["capacidades"] = caps
    _conectores_guardar(conectores)
    return web.json_response({
        "ok": ok,
        "platform": platform,
        "estado": c["estado"],
        "error": error,
        "capacidades": caps,
        "mensaje": "Conexión MCP establecida" if ok else (error or "Sin respuesta"),
    })


async def api_conectores_refrescar(req: web.Request) -> web.Response:
    """Refresca (re-prueba) la conexión de un conector MCP."""
    return await api_conectores_probar(req)


# ------------------------------------------------------------------ agentes del pipeline
_AGENTES_PROMPTS: dict = {}


def _agentes() -> list[dict]:
    """Cada función del pipeline como agente autónomo con sus habilidades y prompt."""
    ags = [
        {"id": "research", "nombre": "Descubrimiento", "tipo": "fuente", "ico": "🔎",
         "desc": "Busca y verifica temas del día para el documental.",
         "habilidades": ["rss", "redes", "noticias", "fact-check"]},
        {"id": "guion", "nombre": "Guionista", "tipo": "escritura", "ico": "📝",
         "desc": "Escribe el guion del documental con gancho y estructura verificada.",
         "habilidades": ["narrativa", "gancho", "guion", "verificación"]},
        {"id": "visuales", "nombre": "Dirección de arte", "tipo": "imagen", "ico": "🎨",
         "desc": "Diseña keyframes, estilo visual y decide generar o reciclar imágenes.",
         "habilidades": ["flux", "imagenoteca", "reciclaje", "keyframes"]},
        {"id": "narracion", "nombre": "Narrador", "tipo": "voz", "ico": "🎙",
         "desc": "Síntesis de voz del canal (Piper / edge-tts).",
         "habilidades": ["piper", "edge-tts", "modulación"]},
        {"id": "montaje", "nombre": "Montajista", "tipo": "video", "ico": "🎞",
         "desc": "Arma el video final, cortes y colores.",
         "habilidades": ["ffmpeg", "cortes", "colores", "qc"]},
        {"id": "publicacion", "nombre": "Publicador", "tipo": "salida", "ico": "🚀",
         "desc": "Publica en YouTube y Facebook vía Zernio.",
         "habilidades": ["zernio", "youtube", "facebook", "presign"]},
    ]
    for a in ags:
        a["prompt"] = _AGENTES_PROMPTS.get(a["id"], f"[prompt del sistema de {a['nombre']}]")
    return ags


async def api_agentes(req: web.Request) -> web.Response:
    return web.json_response(_agentes())


async def api_agentes_prompt(req: web.Request) -> web.Response:
    try:
        body = await req.json()
    except Exception:
        body = {}
    aid = str(body.get("id", ""))
    prompt = body.get("prompt", "")
    if not aid:
        return web.json_response({"ok": False, "error": "id requerido"}, status=400)
    _AGENTES_PROMPTS[aid] = str(prompt)
    return web.json_response({"ok": True, "id": aid})


async def api_agentes_habilidad(req: web.Request) -> web.Response:
    try:
        body = await req.json()
    except Exception:
        body = {}
    aid = str(body.get("id", ""))
    if not aid:
        return web.json_response({"ok": False, "error": "id requerido"}, status=400)
    return web.json_response({"ok": True, "id": aid, "habilidad": "reinstalada"})


# ------------------------------------------------------------------ websocket
async def ws(req: web.Request) -> web.WebSocketResponse:
    wsr = web.WebSocketResponse(heartbeat=30)
    await wsr.prepare(req)
    CLIENTES.add(wsr)
    await snapshot(wsr)
    try:
        async for msg in wsr:
            if msg.type == aiohttp.WSMsgType.ERROR:
                break
    finally:
        CLIENTES.discard(wsr)
    return wsr


async def tarea_sistema() -> None:
    while True:
        await emitir({"t": "sys", **metricas_sistema()})
        await asyncio.sleep(3.0)


def armar_app() -> web.Application:
    app = web.Application()
    r = app.router
    r.add_get("/api/estado", api_estado)
    r.add_get("/api/episodios", api_episodios)
    r.add_get("/api/galeria", api_galeria)
    r.add_get("/api/logs", api_logs)
    r.add_get("/api/kfs/{slug}", api_kfs)
    r.add_post("/api/control", api_control)
    r.add_get("/api/health", api_health)
    r.add_get("/api/metricas", api_metricas)
    r.add_get("/api/conectores", api_conectores)
    r.add_post("/api/conectores/probar", api_conectores_probar)
    r.add_post("/api/conectores/agregar", api_conectores_agregar)
    r.add_put("/api/conectores/{platform}", api_conectores_actualizar)
    r.add_delete("/api/conectores/{platform}", api_conectores_eliminar)
    r.add_post("/api/conectores/{platform}/probar", api_conectores_probar)
    r.add_post("/api/conectores/{platform}/refrescar", api_conectores_refrescar)
    r.add_get("/api/agentes", api_agentes)
    r.add_post("/api/agentes/prompt", api_agentes_prompt)
    r.add_post("/api/agentes/habilidad", api_agentes_habilidad)
    r.add_get("/img/{slug}/{nombre}", img)
    r.add_get("/media/{slug}/{nombre}", media)
    r.add_get("/ws", ws)
    return app


async def principal() -> None:
    previo = cargar_ctrl()
    runner = web.AppRunner(armar_app(), access_log=None)
    await runner.setup()
    await web.TCPSite(runner, host="0.0.0.0", port=PUERTO).start()
    log_local(f"factoryd arriba en :{PUERTO} (publish={PUBLISH})")
    asyncio.ensure_future(tarea_sistema())
    asyncio.ensure_future(poll_etapas())
    if AUTOSTART and previo.get("modo") != "pausado":
        ciclo["salto"] = asyncio.Event()
        asyncio.ensure_future(bucle_247())
    while True:
        await asyncio.sleep(3600)


if __name__ == "__main__":
    asyncio.run(principal())
