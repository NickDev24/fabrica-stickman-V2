"""Generación de keyframes con Cloudflare Workers AI (gratis, sin GPU en el lab).

Por qué acá: el brief pide un motor que compita con lo viral, y lo viral de este formato
son 30-40 IMÁGENES POR MINUTO con cámara encima. Dibujar esas imágenes con primitivas
(SVG/canvas) da un maniquí; generarlas con un modelo de difusión da iluminación, textura,
atmósfera y silueta de miniatura.

Medido en esta máquina con las credenciales que ya estaban en el .env:
  @cf/black-forest-labs/flux-1-schnell      2,0 s/imagen  (responde JSON con base64)
  @cf/lykon/dreamshaper-8-lcm               4,4 s/imagen  (responde PNG crudo)
  @cf/stabilityai/stable-diffusion-xl-...  40,2 s/imagen  (responde PNG crudo)

La caché exacta vive en state/imagen_cache. El reciclaje semántico de imágenes parecidas
es opcional y está apagado por defecto; las escenas nuevas pueden generar y archivar sus
propias imágenes. El reintento transitorio reutiliza `llm._post` (backoff exponencial,
Retry-After, y nunca reintenta un 4xx de credencial).
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
from pathlib import Path
from datetime import datetime, timezone

from . import config, llm

CACHE = config.STATE / "imagen_cache"
IMAGENOTECA = config.ROOT / "assets" / "imagenoteca"
ESTILO = config.STATE / "estilo" / "personaje.json"

# perfil por modelo: cómo se pasan los parámetros y cómo viene la respuesta
MODELOS = {
    "flux": {
        "nombre": "@cf/black-forest-labs/flux-1-schnell",
        "respuesta": "json",
        "extension": "jpg",
        # El run simple de flux-1-schnell SÓLO acepta "prompt": width/height/steps/seed
        # devuelven 400 "Additional or unevaluated properties". Fijo 1024x1024; el
        # recorte 16:9 se hace en el armado, no acá.
        "params": lambda w, h, steps, seed: {},
    },
    "dreamshaper": {
        "nombre": "@cf/lykon/dreamshaper-8-lcm",
        "respuesta": "png",
        "extension": "png",
        "params": lambda w, h, steps, seed: {"width": w, "height": h,
                                             "steps": steps or 4, "seed": seed},
    },
    "gemini-imagen": {
        # Nano Banana 2 Lite (2026): $0.0336/imagen 1K; recomendado por Google para proyectos nuevos
        "nombre": "gemini-3.1-flash-lite-image",
        "respuesta": "gemini",
        "extension": "jpg",
        "params": lambda w, h, steps, seed: {},
        "precio_usd": float(os.environ.get("GEMINI_IMAGE_PRICE_USD", "0.0336")),
    },
    "sdxl": {
        "nombre": "@cf/stabilityai/stable-diffusion-xl-base-1.0",
        "respuesta": "png",
        "extension": "png",
        "params": lambda w, h, steps, seed: {"width": w, "height": h,
                                             "steps": steps or 25, "seed": seed},
    },
    # ---- Fallbacks ante Cloudflare sin cuota (429), medidos 2026-11-05 --------------
    "pollinations": {
        # Gratis, sin key: GET directo https://image.pollinations.ai/prompt/{prompt}.
        # Anónimo admite ~1 pedido cada 15 s; con POLLINATIONS_API_KEY (sk_) sube el
        # rate limit y saca la marca de agua — PERO una sk_ sin saldo responde 402,
        # así que el propio proveedor recae en modo anónimo (ver _crudos_pollinations).
        "nombre": "image.pollinations.ai",
        "respuesta": "url_get",
        "extension": "jpg",
        "params": lambda w, h, steps, seed: {"w": w, "h": h, "seed": seed},
    },
    "hf-space": {
        # Espacios públicos de Hugging Face vía gradio_client (SDXL / Flux.1-schnell):
        # sigue gratis y legítimo, sin key, pero depende de la cola de la comunidad →
        # no es para tráfico garantizado, es el segundo salvaguardado de la cadena.
        "nombre": os.environ.get("HF_SPACE_IMAGEN", "black-forest-labs/FLUX.1-schnell"),
        "respuesta": "hf",
        "extension": "png",
        "params": lambda w, h, steps, seed: {"w": w, "h": h, "seed": seed},
    },
}

# Cadena de fallbacks: el primario es el que pidió el guion (flux/Cloudflare por
# velocidad y coste $0 medido); si Cloudflare corta por 429/cuota, Pollinations
# cubre el 90% del caso; si la cola de la comunidad también falla, HF Space; y
# Gemini (pagado, con ALLOW_PAID_LLM + presupuesto) queda como último recurso
# igual que ya estaba. Cada eslabón decide con su propia disponibilidad — la
# cascada no exige las credenciales del primario si no las va a usar.
CADENA = {
    "flux": ["pollinations", "hf-space", "gemini-imagen"],
    "dreamshaper": ["pollinations", "hf-space", "gemini-imagen"],
    "sdxl": ["pollinations", "hf-space", "gemini-imagen"],
    "pollinations": ["hf-space", "gemini-imagen"],
    "hf-space": ["pollinations", "gemini-imagen"],
    "gemini-imagen": [],
}

# Los primarios trabajadores van contra la cuota gratuita de Workers AI.
_PRIMARIOS_CLOUDFLARE = ("flux", "dreamshaper", "sdxl")


def extension(modelo: str) -> str:
    return MODELOS[modelo].get("extension", "png")


def _cuota_diaria() -> tuple[Path, dict]:
    """Tope local de solicitudes para mantener Flux por debajo de la cuota gratuita diaria."""
    limite = max(1, int(os.environ.get("CF_MAX_IMAGENES_DIA", "50")))
    ruta = config.STATE / "workers_ai_usage.json"
    hoy = datetime.now(timezone.utc).date().isoformat()
    try:
        datos = json.loads(ruta.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        datos = {}
    if datos.get("dia_utc") != hoy:
        datos = {"dia_utc": hoy, "solicitudes_exitosas": 0, "limite_local": limite,
                 "costo_usd_estimado": 0.0}
    datos["limite_local"] = limite
    if int(datos.get("solicitudes_exitosas", 0)) >= limite:
        raise RuntimeError(f"tope local gratuito de Workers AI alcanzado ({limite} imágenes hoy); "
                           "sin cuota no hay motor de imágenes y el keyframe queda bloqueado "
                           "(no hay motor alternativo activo)")
    return ruta, datos


def _contabilizar_cuota(ruta: Path, datos: dict) -> None:
    datos["solicitudes_exitosas"] = int(datos.get("solicitudes_exitosas", 0)) + 1
    datos["costo_usd_estimado"] = round(float(datos.get("costo_usd_estimado", 0.0)) + 0.005, 4)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(json.dumps(datos, indent=2), encoding="utf-8")


def _url(modelo: str) -> str:
    import os
    config.load_env()
    acc = os.environ.get("CLOUDFLARED_ACCOUNTS_ID", "")
    if not acc:
        raise RuntimeError("sin CLOUDFLARED_ACCOUNTS_ID en .env: no hay motor de imágenes")
    return (f"https://api.cloudflare.com/client/v4/accounts/{acc}/ai/run/"
            f"{MODELOS[modelo]['nombre']}")


def _token() -> str:
    import os
    config.load_env()
    return os.environ.get("CLOUDFLARED_WORKER_AI", "")


def _webp_a_jpg(crudos: bytes) -> bytes:
    """FLUX.1-schnell y otros Spaces devuelven .webp; downstream espera JPEG/PNG."""
    from io import BytesIO
    from PIL import Image
    im = Image.open(BytesIO(crudos)).convert("RGB")
    buf = BytesIO()
    im.save(buf, format="JPEG", quality=92)
    return buf.getvalue()


def _crudos_pollinations(prompt: str, w: int, h: int, seed: int) -> bytes:
    """GET directo; sin key funciona anónimo (~1 req / 15 s). Con sk_ SIN SALDO (402)
    el mismo proveedor cae a modo anónimo en lugar de bloquear el keyframe."""
    import time
    import urllib.parse
    config.load_env()
    base = os.environ.get("POLLINATIONS_URL",
                           "https://image.pollinations.ai/prompt").rstrip("/")
    qs = {"model": os.environ.get("POLLINATIONS_IMAGEN_MODEL", "flux"),
          "width": w, "height": h, "seed": seed, "nologo": "true"}
    key = os.environ.get("POLLINATIONS_API_KEY", "").strip()
    headers = {"User-Agent": "pulso-curioso-fabrica/1.0"}

    def pedir(partes: dict) -> bytes:
        url = f"{base}/{urllib.parse.quote(prompt, safe='')}?{urllib.parse.urlencode(partes)}"
        r = llm.requests.get(url, timeout=240, headers=headers)
        if r.status_code >= 400:
            raise RuntimeError(f"HTTP {r.status_code}: {r.text[:160]}")
        crudos = r.content
        if not (crudos.startswith(b"\xff\xd8\xff") or crudos.startswith(b"\x89PNG")):
            raise RuntimeError(f"respuesta no es jpg/png (bytes: {crudos[:16]!r})")
        if len(crudos) < 8000:
            raise RuntimeError(f"imagen sospechosamente chica ({len(crudos)} B)")
        return crudos

    error_con_key = ""
    if key:
        try:
            return pedir({**qs, "key": key})
        except RuntimeError as exc:
            error_con_key = str(exc)
            print(f"  pollinations: con POLLINATIONS_API_KEY falló ({error_con_key[:110]}); "
                  "reintento anónimo")
    # cadencia anónima: ~1 pedido cada POLLINATIONS_MIN_INTERVAL_S
    intervalo = max(1.0, float(os.environ.get("POLLINATIONS_MIN_INTERVAL_S", "16")))
    uso = config.STATE / "pollinations_usage.json"
    try:
        ultimo = float(json.loads(uso.read_text(encoding="utf-8")).get("ultimo_ts", 0.0))
    except (OSError, ValueError):
        ultimo = 0.0
    espera = ultimo + intervalo - time.time()
    if espera > 0:
        time.sleep(espera)
    uso.parent.mkdir(parents=True, exist_ok=True)
    uso.write_text(json.dumps({"ultimo_ts": time.time(), "intervalo_s": intervalo}),
                   encoding="utf-8")
    try:
        return pedir(qs)
    except RuntimeError as exc:
        if error_con_key:
            raise RuntimeError(f"con key: {error_con_key} | anónimo: {exc}") from exc
        raise


def _crudos_hf_space(prompt: str, w: int, h: int, seed: int, steps: int | None) -> bytes:
    """Un Space público de la comunidad vía gradio_client. Sin key, sin cuota local;
    el límite real que es la cola del Space → puede tardar mucho o fallar de cola llena."""
    try:
        from gradio_client import Client
    except ImportError as exc:  # depende del intérprete que corre la fábrica
        raise RuntimeError(f"gradio_client no está instalado en este python: {exc}") from exc
    space = str(MODELOS["hf-space"]["nombre"])
    try:
        client = Client(space, verbose=False)
        result = client.predict(prompt=prompt, seed=int(seed), randomize_seed=False,
                                width=int(w), height=int(h),
                                num_inference_steps=int(steps or 4), api_name="/infer")
    except Exception as exc:
        raise RuntimeError(f"hf-space {space}: {exc.__class__.__name__}: {str(exc)[:180]}") from exc
    ruta = result[0] if isinstance(result, (list, tuple)) and result else result
    if not ruta or not Path(str(ruta)).exists():
        raise RuntimeError(f"hf-space devolvió algo inesperado: {str(result)[:120]}")
    crudos = Path(str(ruta)).read_bytes()
    if crudos[:4] == b"RIFF" and b"WEBP" in crudos[:16]:
        crudos = _webp_a_jpg(crudos)
    return crudos


def _crudos_cloudflare(modelo: str, prompt: str, w: int, h: int, seed: int,
                       steps: int | None) -> bytes:
    """Primario Workers AI. AGOTA la cuota pre-check (antes de pedir) para que la
    cascada escale sin quemar intentos; el error 429 sube hacia el caller."""
    cfg = MODELOS[modelo]
    usage_path, usage = _cuota_diaria()   # tope local alcanzado => RuntimeError que escala a la cascada
    cuerpo = {"prompt": prompt, **cfg["params"](w, h, steps, seed)}
    r, err = llm._post(_url(modelo), cuerpo,
                       {"Authorization": f"Bearer {_token()}",
                        "Content-Type": "application/json"}, f"workers_ai:{modelo}")
    if r is None:
        raise RuntimeError(f"cloudflare/{modelo}: {err}")
    if cfg["respuesta"] == "json":
        datos = r.json()
        b64 = ((datos.get("result") or {}).get("image")
               or (datos.get("result") or {}).get("b64_json"))
        if not b64:
            raise RuntimeError(f"respuesta sin imagen: {str(datos)[:200]}")
        return base64.b64decode(b64)
    return r.content


def _crudos_gemini(prompt: str) -> bytes:
    """Último recurso pagado: presupuesto mensual pega, gasto registrado por imagen."""
    cfg = MODELOS["gemini-imagen"]
    cap = float(os.environ.get("GEMINI_PRESUPUESTO_USD_MES", "4.5"))
    gasto = llm._gasto_gemini()
    if gasto + cfg["precio_usd"] > cap:
        raise RuntimeError(
            f"imagen gemini: presupuesto mensual agotado "
            f"({gasto:.2f} USD tope {cap:.2f} USD)")
    body_payload = {"contents": [{"role": "user", "parts": [{"text": prompt}]}],
                    "generationConfig": {"responseModalities": ["IMAGE"]}}
    url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
           f"{cfg['nombre']}:generateContent")
    rr = llm.requests.post(url, timeout=180,
                           headers={"X-goog-api-key": os.environ["GEMINI_API_KEY"],
                                    "Content-Type": "application/json"},
                           json=body_payload)
    if rr.status_code != 200:
        raise RuntimeError(f"imagen gemini falló: HTTP {rr.status_code} {rr.text[:200]}")
    raw_b64 = None
    for c in rr.json().get("candidates", []):
        for p in (c.get("content") or {}).get("parts", []):
            inl = p.get("inlineData") or p.get("inline_data")
            if inl and inl.get("data"):
                raw_b64 = inl["data"]
                break
        if raw_b64:
            break
    if not raw_b64:
        raise RuntimeError(f"gemini no devolvió imagen: {str(rr.json())[:200]}")
    crudos = base64.b64decode(raw_b64)
    llm._registrar_gasto_extra(cfg["precio_usd"], cfg["nombre"])
    return crudos


def _crudos_por_proveedor(modelo_proveedor: str, prompt: str, w: int, h: int,
                          seed: int, steps: int | None) -> bytes:
    if modelo_proveedor == "gemini-imagen":
        return _crudos_gemini(prompt)
    if modelo_proveedor == "pollinations":
        return _crudos_pollinations(prompt, w, h, seed)
    if modelo_proveedor == "hf-space":
        return _crudos_hf_space(prompt, w, h, seed, steps)
    return _crudos_cloudflare(modelo_proveedor, prompt, w, h, seed, steps)


def huella(modelo: str, prompt: str, w: int, h: int, seed: int, steps: int | None) -> str:
    # Sólo entran los parámetros que el modelo de verdad usa. flux los ignora todos: si
    # formaran parte de la clave, cada re-corrida con otro seed sería un cache-miss y
    # redrawaría el mismo personaje, gastando free tier y cambiando la cara.
    cfg = MODELOS[modelo]
    extras = cfg["params"](w, h, steps, seed)
    semilla = json.dumps([cfg["nombre"], prompt, sorted(extras.items())],
                         ensure_ascii=False)
    return hashlib.sha256(semilla.encode("utf-8")).hexdigest()[:40]


def _archivar(img: Path, *, prompt: str = "", modelo: str = "", escena: str = "",
              accion: str = "", plano: str = "", origen: str = "") -> Path:
    """Persiste una imagen lista para buscar y reciclar en assets/imagenoteca."""
    import shutil
    if not img.is_file() or img.stat().st_size < 8_000:
        return img
    IMAGENOTECA.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(img.read_bytes()).hexdigest()
    destino = IMAGENOTECA / f"{digest}{img.suffix.lower()}"
    if not destino.exists():
        shutil.copy2(img, destino)
    sidecar = destino.with_suffix(".json")
    if not sidecar.exists():
        sidecar.write_text(json.dumps({
            "archivo": destino.name, "sha256": digest, "prompt": prompt,
            "modelo": modelo, "escena": escena, "accion": accion, "plano": plano,
            "origen": origen, "resolucion": None,
        }, ensure_ascii=False, indent=2), encoding="utf-8")
    return destino


def importar_imagenes_existentes() -> dict:
    """Importa caché y keyframes existentes sin mover ni alterar sus originales."""
    import shutil
    IMAGENOTECA.mkdir(parents=True, exist_ok=True)
    archivos = [p for p in CACHE.glob("*.*")
                if p.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp")]
    if config.PROJECTS.is_dir():
        archivos.extend(p for p in config.PROJECTS.glob("*/assets/kf/*")
                        if p.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp"))
    nuevos = 0
    for src in archivos:
        if not src.is_file() or src.stat().st_size < 8_000:
            continue
        digest = hashlib.sha256(src.read_bytes()).hexdigest()
        dst = IMAGENOTECA / f"{digest}{src.suffix.lower()}"
        if not dst.exists():
            shutil.copy2(src, dst)
            nuevos += 1
        meta = dst.with_suffix(".json")
        if not meta.exists():
            # Una huella/hash no revela el prompt. No inventar metadatos: los keyframes
            # obtienen sidecar en el paso posterior cuando se enlazan con beats.json.
            continue
    return {"imagenes_vistas": len(archivos), "imagenes_nuevas": nuevos,
            "directorio": str(IMAGENOTECA.relative_to(config.ROOT))}


def _disponible_gemini() -> tuple[bool, str]:
    """El opt-in pago es explícito: sin ALLOW_PAID_LLM=1 ni GEMINI_API_KEY, no."""
    config.load_env()
    if os.environ.get("ALLOW_PAID_LLM", "").strip().lower() not in ("1", "true", "yes", "on"):
        return False, "ALLOW_PAID_LLM no habilitado (gemini-imagen es pago)"
    if not os.environ.get("GEMINI_API_KEY", "").strip():
        return False, "sin GEMINI_API_KEY en .env"
    return True, ""


def disponible(modelo: str = "flux") -> tuple[bool, str]:
    """Disponibilidad DEL PROVEEDOR pedido: cada eslabón de la cadena se evalúa solo."""
    import os
    if modelo == "gemini-imagen":
        return _disponible_gemini()
    if modelo == "pollinations":
        # GET anónimo no necesita nada: la key es opcional (y con saldo cero 402 cae a anónimo).
        import urllib.parse
        base = os.environ.get("POLLINATIONS_URL", "https://image.pollinations.ai/prompt")
        urllib.parse.urlparse(base)   # validación barata del URL
        return True, ""
    if modelo == "hf-space":
        try:
            import gradio_client  # noqa: F401
        except ImportError:
            return False, "gradio_client no instalado (pip install gradio_client)"
        return True, ""
    config.load_env()
    if not os.environ.get("CLOUDFLARED_WORKER_AI", ""):
        return False, "sin CLOUDFLARED_WORKER_AI en .env"
    if not os.environ.get("CLOUDFLARED_ACCOUNTS_ID", ""):
        return False, "sin CLOUDFLARED_ACCOUNTS_ID en .env"
    return True, ""


def generar(prompt: str, salida: Path, *, modelo: str = "flux", w: int = 1024,
            h: int = 1024, seed: int = 777, steps: int | None = None,
            forzar: bool = False, escena: str = "", accion: str = "",
            plano: str = "", reciclar: bool = False) -> Path:
    """Un keyframe a disco. Devuelve la ruta; si ya existe en caché no llama a la red.

    Cadena CASCADE (CADENA arriba): primero el modelo pedido; ante fallo, Pollinations
    -> HF Space -> Gemini (pagado opt-in). Reciclar una imagen semánticamente parecida
    es opcional; por defecto sólo se usa caché exacta del mismo prompt."""
    if modelo not in MODELOS:
        raise KeyError(f"modelo de imagen desconocido: {modelo}")
    CACHE.mkdir(parents=True, exist_ok=True)
    huella_img = huella(modelo, prompt, w, h, seed, steps)
    # reciclaje: reutiliza imagen equivalente ya producida; coste 0 y sin imágenes duplicadas
    if reciclar and not forzar:
        try:
            from .stages import reciclaje
            recs = reciclaje.reutilizar(prompt, escena=escena, accion=accion,
                                        plano=plano, limit=1)
        except Exception:
            recs = []
        if recs:
            salida.parent.mkdir(parents=True, exist_ok=True)
            salida.write_bytes(recs[0].read_bytes())
            _archivar(salida, prompt=prompt, modelo=modelo, escena=escena,
                      accion=accion, plano=plano, origen="reciclaje:" + str(recs[0]))
            return salida
    ext = extension(modelo)
    clave = CACHE / f"{huella_img}.{ext}"
    # Migración no destructiva: las primeras versiones guardaban el JPEG de Flux
    # con .png. Reutilizarlo si su firma confirma JPEG, sin volver a llamar al servicio.
    legado = CACHE / f"{huella_img}.png"
    if not clave.exists() and ext == "jpg" and legado.exists():
        datos_legado = legado.read_bytes()
        if datos_legado.startswith(b"\xff\xd8\xff"):
            clave.write_bytes(datos_legado)
    if clave.exists() and clave.stat().st_size > 8000:
        salida.parent.mkdir(parents=True, exist_ok=True)
        salida.write_bytes(clave.read_bytes())
        _archivar(salida, prompt=prompt, modelo=modelo, escena=escena,
                  accion=accion, plano=plano, origen="cache:" + str(clave))
        return salida
    if forzar and clave.exists():
        clave.unlink()

    candidatos = [modelo] + list(CADENA.get(modelo, []))
    crudos, usado, fallos_reportados = None, modelo, []
    for candidato in candidatos:
        ok_c, por_c = disponible(candidato)
        if not ok_c:
            fallos_reportados.append(f"{candidato} ({por_c})")
            print(f"  imagen: {candidato} no disponible ({por_c}); eslabón siguiente")
            continue
        try:
            crudos = _crudos_por_proveedor(candidato, prompt, w, h, seed, steps)
            usado = candidato
        except (RuntimeError, ValueError) as exc:
            fallos_reportados.append(f"{candidato}: {str(exc)[:140]}")
            print(f"  imagen: {candidato} falló -> {str(exc)[:140]}; eslabón siguiente")
            continue
        if usado != modelo:
            print(f"  imagen: responde {usado} como respaldo de {modelo}")
        break
    if crudos is None:
        raise RuntimeError("cascada de imagen agotada: " + " | ".join(fallos_reportados))
    if len(crudos) < 8000:
        raise RuntimeError(f"imagen sospechosamente chica ({len(crudos)} bytes) en {usado}")
    es_jpeg = crudos.startswith(b"\xff\xd8\xff")
    es_png = crudos.startswith(b"\x89PNG\r\n\x1a\n")
    if not (es_jpeg or es_png):
        raise RuntimeError(f"formato de imagen desconocido en {usado}; no se guardó en caché")
    ext_real = "jpg" if es_jpeg else "png"
    # la validación estricta de formato es regla de Workers AI; los respaldo sólo convierten su salida
    if ext_real != ext and usado == modelo and usado in _PRIMARIOS_CLOUDFLARE:
        raise RuntimeError(f"Workers AI devolvió {ext_real.upper()} para {modelo}, se esperaba .{ext}")
    clave.write_bytes(crudos)
    if usado in _PRIMARIOS_CLOUDFLARE:
        # el tope diario es una regla de Cloudflare: sólo se cuenta lo que respondió Cloudflare
        usage_path, usage = _cuota_diaria()
        _contabilizar_cuota(usage_path, usage)
    salida.parent.mkdir(parents=True, exist_ok=True)
    salida.write_bytes(crudos)
    _archivar(salida, prompt=prompt, modelo=usado, escena=escena,
              accion=accion, plano=plano, origen="generada")
    return salida


# --------------------------------------------------------------- hoja de personaje
def estilo() -> dict:
    if not ESTILO.exists():
        raise RuntimeError(f"no existe la hoja de personaje: {ESTILO}")
    return json.loads(ESTILO.read_text(encoding="utf-8"))


def _variante_identidad(e: dict, accion: str, plano: str) -> str:
    """Contrato MIXTO v9: en primer plano/detalle el personaje muestra cara.

    El cuerpo en planos anchos sigue siendo la silueta sin rostro de la v8; la
    cara expresiva (ojos + boca blancos) sólo entra cuando la cámara está cerca
    de la cabeza — es lo que retiene el scroll en los canales virales de stickman.
    """
    if plano in ("primer_plano", "detalle") and e.get("identidad_cara"):
        return e["identidad_cara"]
    return e["identidad"]


def _expresion(e: dict, accion: str) -> str:
    """Emoción codificada para la variante cara (determinística, auditable)."""
    cara = e.get("expresiones") or {}
    for clave in cara:
        if clave in accion:
            return cara[clave]
    return ""


def armar_prompt(escena: str, accion: str, plano: str = "medio") -> str:
    """IDENTIDAD + ESTILO + escenario + acción + plano + negativos, siempre en ese orden.

    El orden fijo y el bloque de identidad literal son lo que mantiene al personaje
    igual entre escenas: si cada beat redacta su prompt a mano, al beat 7 ya es otro.
    Las claves de acción/escenario/plano se resuelven contra la hoja; pasar la clave
    cruda ("senal_final") condiciona casi nada y el modelo devuelve siempre lo mismo.
    """
    e = estilo()
    ident = _variante_identidad(e, e["acciones"].get(accion, accion), plano)
    cara = f"face: {_expresion(e, accion)}" if plano in ("primer_plano", "detalle") else ""
    partes = [
        ident,
        e["estilo"],
        cara,
        e["escenarios"].get(escena, escena),
        e["acciones"].get(accion, accion),
        e["planos"].get(plano, plano),
        e["negativos"],
    ]
    out = ", ".join(p for p in partes if p)
    if len(out) > 600:
        out = out[:600].rsplit(" ", 1)[0]
    return out


def armar_prompt_dirigido(beat: dict) -> str:
    """Prompt breve y dirigido: conserva identidad, escena y acción con campos de evidencia."""
    e = estilo()
    d = beat.get("direccion") or {}
    escenario = e["escenarios"].get(beat.get("escena", ""), beat.get("escena", ""))
    accion = e["acciones"].get(beat.get("accion", ""), beat.get("accion", ""))
    # La oración completa es la unidad de sentido. Antes se recortaba a 34 caracteres
    # y la actuación a 10 ("el persona"): eso produjo las 4-5 poses idénticas seguidas.
    def corto(texto: str, maximo: int) -> str:
        limpio = re.sub(r"\s+", " ", str(texto or "")).strip()
        if len(limpio) <= maximo:
            return limpio
        return limpio[:maximo].rsplit(" ", 1)[0]

    prop = corto(d.get("prop", ""), 90)
    reveal = corto(d.get("reveal", ""), 36)
    acting = corto(d.get("acting", ""), 44)
    movimiento = corto(d.get("movimiento_local", ""), 26)
    foco = corto(beat.get("texto", "") or d.get("idea", ""), 105)
    contexto = corto(beat.get("contexto_historia", ""), 100)
    palabras = f"{foco} {contexto} {d.get('prop', '')}".casefold()
    if any(k in palabras for k in ("investigador", "investigación", "investigacion", "detective",
                                    "fbi", "policía", "policia", "inspector")):
        sujeto = "make the case-specific investigator the scene's subject, not a generic channel narrator: distinct expressive stick-figure face and period-appropriate detective clothing"
    elif any(k in palabras for k in ("ladrón", "ladron", "robo", "robber", "thief", "criminal",
                                      "criminales", "asaltante", "intruso")):
        sujeto = "make the case-specific suspect the scene's subject, not a generic channel narrator: distinct expressive stick-figure face and clothing appropriate to the case; keep unidentified suspects anonymous"
    elif any(k in palabras for k in ("guardia", "guard", "vigilante", "seguridad")):
        sujeto = "make the case-specific museum/security guard the scene's subject: a stick figure with a distinct uniform and expressive face, separate from any narrator"
    else:
        sujeto = "depict the specific person or role named in the narration as the scene's subject, not a generic channel narrator; use a distinct expressive face and period-appropriate clothing; for a named public figure, use a stylized recognizable likeness without inventing biographical details"
    # El encuadre sale del contrato en inglés de personaje.json, no de una etiqueta
    # interna en español que Flux no interpreta igual.
    plano_txt = e["planos"].get(beat.get("plano", "medio"), "medium shot")
    cam = {"push": "slow push-in", "push_lento": "slow push-in",
           "pull": "slow pull-back", "pan": "lateral pan",
           "shake": "handheld"}.get(beat.get("mov", ""), "static")
    # Orden del contrato visual: identidad, estilo, escenario, acción, dirección, negativos.
    # La identidad ya incorpora la variante facial cuando el plano es cercano.
    accion_txt = e["acciones"].get(beat.get("accion", ""), beat.get("accion", ""))
    ident = _variante_identidad(e, accion_txt, beat.get("plano", "medio"))
    # KEYFRAME GANCHO (0-3 s): flash-forward al momento de máxima intensidad. El "\n"
    # literal instruye composición dense; el prompt de cabecera pega el impacto primero,
    # que es lo único que el ojo lee en el scroll.
    cabecera = ("chaotic striking flash-forward shot" if beat.get("gancho")
                else "")
    partes = [cabecera, ident, e["estilo"], sujeto, escenario, accion,
              f"{plano_txt}; {cam}",
              f"narrative focus: {foco}; visual object: {prop}; action: {acting}; reveal: {reveal}; motion: {movimiento}",
              f"story context: {contexto}" if contexto else "",
              "black ink, warm white, red accent, absolutely no text, letters, numbers, captions, typography, labels, or watermark; blank uncluttered illustration; no extra limbs"]
    out = ", ".join(p for p in partes if p)
    if len(out) > 600:
        out = out[:600].rsplit(" ", 1)[0]
    return out

