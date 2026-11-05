"""Generación de keyframes con Cloudflare Workers AI (gratis, sin GPU en el lab).

Por qué acá: el brief pide un motor que compita con lo viral, y lo viral de este formato
son 30-40 IMÁGENES POR MINUTO con cámara encima. Dibujar esas imágenes con primitivas
(SVG/canvas) da un maniquí; generarlas con un modelo de difusión da iluminación, textura,
atmósfera y silueta de miniatura.

Medido en esta máquina con las credenciales que ya estaban en el .env:
  @cf/black-forest-labs/flux-1-schnell      2,0 s/imagen  (responde JSON con base64)
  @cf/lykon/dreamshaper-8-lcm               4,4 s/imagen  (responde PNG crudo)
  @cf/stabilityai/stable-diffusion-xl-...  40,2 s/imagen  (responde PNG crudo)

Todo se cachea en state/imagen_cache por huella (modelo + prompt + tamaño + seed): la
identidad del personaje queda congelada en disco, así una re-corrida no redrawa al
protagonista ni gasta free tier de más. El reintento transitorio reutiliza el mismo
`llm._post` (backoff exponencial, Retry-After, y nunca reintentar un 4xx de credencial).
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path
from datetime import datetime, timezone

from . import config, llm

CACHE = config.STATE / "imagen_cache"
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
}


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


def huella(modelo: str, prompt: str, w: int, h: int, seed: int, steps: int | None) -> str:
    # Sólo entran los parámetros que el modelo de verdad usa. flux los ignora todos: si
    # formaran parte de la clave, cada re-corrida con otro seed sería un cache-miss y
    # redrawaría el mismo personaje, gastando free tier y cambiando la cara.
    cfg = MODELOS[modelo]
    extras = cfg["params"](w, h, steps, seed)
    semilla = json.dumps([cfg["nombre"], prompt, sorted(extras.items())],
                         ensure_ascii=False)
    return hashlib.sha256(semilla.encode("utf-8")).hexdigest()[:40]


def _fallback_pagado_ok(err) -> bool:
    """Cloudflare sin cuota y opt-in pago habilitado -> usar Gemini en este corte."""
    if os.environ.get("ALLOW_PAID_LLM", "").strip().lower() not in ("1", "true", "yes", "on"):
        return False
    if not os.environ.get("GEMINI_API_KEY", "").strip():
        return False
    try:
        cap = float(os.environ.get("GEMINI_PRESUPUESTO_USD_MES", "4.5"))
        if llm._gasto_gemini() + float(MODELOS["gemini-imagen"]["precio_usd"]) > cap:
            return False
    except Exception:
        return False
    low = str(err or "").lower()
    return "daily free allocation" in low or "429" in low


def _disponible_gemini() -> tuple[bool, str]:
    """El opt-in pago es explícito: sin ALLOW_PAID_LLM=1 ni GEMINI_API_KEY, no."""
    config.load_env()
    if os.environ.get("ALLOW_PAID_LLM", "").strip().lower() not in ("1", "true", "yes", "on"):
        return False, "ALLOW_PAID_LLM no habilitado (gemini-imagen es pago)"
    if not os.environ.get("GEMINI_API_KEY", "").strip():
        return False, "sin GEMINI_API_KEY en .env"
    return True, ""


def disponible() -> tuple[bool, str]:
    import os
    config.load_env()
    if not os.environ.get("CLOUDFLARED_WORKER_AI", ""):
        return False, "sin CLOUDFLARED_WORKER_AI en .env"
    if not os.environ.get("CLOUDFLARED_ACCOUNTS_ID", ""):
        return False, "sin CLOUDFLARED_ACCOUNTS_ID en .env"
    return True, ""


def generar(prompt: str, salida: Path, *, modelo: str = "flux", w: int = 1024,
            h: int = 1024, seed: int = 777, steps: int | None = None,
            forzar: bool = False, escena: str = "", accion: str = "",
            plano: str = "") -> Path:
    """Un keyframe a disco. Devuelve la ruta; si ya existe en caché no llama a la red."""
    if modelo not in MODELOS:
        raise KeyError(f"modelo de imagen desconocido: {modelo}")
    if modelo == "gemini-imagen":
        ok, por = _disponible_gemini()
    else:
        ok, por = disponible()
    if not ok:
        raise RuntimeError(f"motor de imágenes no configurado: {por}")
    CACHE.mkdir(parents=True, exist_ok=True)
    huella_img = huella(modelo, prompt, w, h, seed, steps)
    # reciclaje: reutiliza imagen equivalente ya producida; coste 0 y sin imágenes duplicadas
    if not forzar:
        try:
            from .stages import reciclaje
            recs = reciclaje.reutilizar(prompt, escena=escena, accion=accion,
                                        plano=plano, limit=1)
        except Exception:
            recs = []
        if recs:
            salida.parent.mkdir(parents=True, exist_ok=True)
            salida.write_bytes(recs[0].read_bytes())
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
        return salida
    if forzar and clave.exists():
        clave.unlink()

    if modelo == "gemini-imagen":
        cfg = MODELOS[modelo]
        cap = float(os.environ.get("GEMINI_PRESUPUESTO_USD_MES", "4.5"))
        gasto = llm._gasto_gemini()
        if gasto + cfg["precio_usd"] > cap:
            raise RuntimeError(
                f"imagen gemini: presupuesto mensual agotado "
                f"({gasto:.2f} USD tope {cap:.2f} USD)")
        body_payload = {"contents": [{"role": "user",
                                      "parts": [{"text": prompt}]}],
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
    else:
        usage_path, usage = _cuota_diaria()
        cfg = MODELOS[modelo]
        cuerpo = {"prompt": prompt, **cfg["params"](w, h, steps, seed)}
        r, err = llm._post(_url(modelo), cuerpo,
                           {"Authorization": f"Bearer {_token()}",
                            "Content-Type": "application/json"}, f"workers_ai:{modelo}")
        if r is None:
            if _fallback_pagado_ok(err):
                print("  cloudflare sin cuota -> fallback pago a gemini-imagen (un corte)")
                return generar(prompt, salida, modelo="gemini-imagen", w=w, h=h,
                               seed=seed, steps=steps, forzar=forzar)
            raise RuntimeError(f"imagen falló ({modelo}): {err}")
        if cfg["respuesta"] == "json":
            datos = r.json()
            b64 = ((datos.get("result") or {}).get("image")
                   or (datos.get("result") or {}).get("b64_json"))
            if not b64:
                raise RuntimeError(f"respuesta sin imagen: {str(datos)[:200]}")
            crudos = base64.b64decode(b64)
        else:
            crudos = r.content
    if len(crudos) < 8000:
        raise RuntimeError(f"imagen sospechosamente chica ({len(crudos)} bytes) en {modelo}")
    es_jpeg = crudos.startswith(b"\xff\xd8\xff")
    es_png = crudos.startswith(b"\x89PNG\r\n\x1a\n")
    if not (es_jpeg or es_png):
        raise RuntimeError(f"formato de imagen desconocido en {modelo}; no se guardó en caché")
    ext_real = "jpg" if es_jpeg else "png"
    if ext_real != ext:
        raise RuntimeError(f"Workers AI devolvió {ext_real.upper()} para {modelo}, se esperaba .{ext}")
    clave.write_bytes(crudos)
    if modelo != "gemini-imagen":
        # el tope diario es una regla de Cloudflare; el pago nunca debe toparse con él
        usage_path, usage = _cuota_diaria()
        _contabilizar_cuota(usage_path, usage)
    salida.parent.mkdir(parents=True, exist_ok=True)
    salida.write_bytes(crudos)
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
    return ", ".join(p for p in partes if p)


def armar_prompt_dirigido(beat: dict) -> str:
    """Prompt breve y dirigido: conserva identidad, escena y acción con campos de evidencia."""
    e = estilo()
    d = beat.get("direccion") or {}
    escenario = e["escenarios"].get(beat.get("escena", ""), beat.get("escena", ""))
    accion = e["acciones"].get(beat.get("accion", ""), beat.get("accion", ""))
    # La oración completa es la unidad de sentido. Antes se recortaba a 34 caracteres
    # y la actuación a 10 ("el persona"): eso produjo las 4-5 poses idénticas seguidas.
    idea = str(beat.get("contexto", d.get("idea", beat.get("texto", ""))))[:78]
    prop = str(d.get("prop", ""))[:52]
    reveal = str(d.get("reveal", ""))[:30]
    acting = str(d.get("acting", ""))[:40]
    movimiento = str(d.get("movimiento_local", ""))[:24]
    # El encuadre sale del contrato en inglés de personaje.json, no de una etiqueta
    # interna en español que Flux no interpreta igual.
    plano_txt = e["planos"].get(beat.get("plano", "medio"), "medium shot")
    cam = {"push": "slow push-in", "push_lento": "slow push-in",
           "pull": "slow pull-back", "pan": "lateral pan",
           "shake": "handheld"}.get(beat.get("mov", ""), "static")
    # Orden del contrato visual: identidad, estilo, escenario, acción, dirección, negativos.
    # Contrato MIXTO v9: primer_plano/detalle usan la variante cara (ojos+boca) con la
    # emoción del beat; el resto usa la silueta sin rostro de la v8.
    accion_txt = e["acciones"].get(beat.get("accion", ""), beat.get("accion", ""))
    ident = _variante_identidad(e, accion_txt, beat.get("plano", "medio"))
    cara = ""
    if beat.get("plano") in ("primer_plano", "detalle"):
        expr = _expresion(e, accion_txt)
        if expr:
            cara = f"face: {expr}"[:48]
    partes = [ident[:95], e["estilo"][:62], cara, escenario[:34],
              f"evidence-centered, {accion}"[:40], f"{plano_txt}; {cam}"[:46],
              f"scene: {idea}; key object: {prop}; action: {acting}; reveal: {reveal}; motion: {movimiento}",
              "black ink, warm white, red accent, clear readable shapes, no generated lettering",
              e["negativos"][:48]]
    return ", ".join(p for p in partes if p)

