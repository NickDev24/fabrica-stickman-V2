"""Cascada editorial con Ollama local por defecto y servicios remotos opt-in.

Reglas (misión §3):
- Cada proveedor es un adaptador independiente; si falla (key ausente, 401/403, 429,
  5xx, timeout) se pasa al siguiente dejando rastro en state/llm_log.jsonl.
- La verificación de hechos usa una RUTA independiente del proveedor que escribió
  (TASK_ROUTES["verificacion"]) para no validar al mismo modelo que inventó.
- Caché en disco (state/llm_cache) por huella SHA-256 del payload, con TTL;
  evita repetir consultas idénticas dentro del mismo ciclo de producción.
- Health-check: state/proveedores.json guarda el estado por proveedor (sin exponer keys).
"""
from __future__ import annotations

import hashlib
import json
import os
import random
import re
import shutil
import subprocess
import time
from datetime import datetime, timedelta, timezone

import requests

from . import config

STATE_DIR = config.STATE
STATE_LOG = STATE_DIR / "llm_log.jsonl"
HEALTH = STATE_DIR / "proveedores.json"

# gpt-oss (Bedrock) escribe su cadena de pensamiento dentro de "content".
_REASONING = re.compile(r"<(?:reasoning|think)>.*?</(?:reasoning|think)>", re.S)


class AllProvidersFailed(Exception):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _ensure_dir() -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)


def _log(entry: dict) -> None:
    _ensure_dir()
    with STATE_LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def _health_record(provider: str, status: str, detail: str = "") -> None:
    _ensure_dir()
    data = {}
    if HEALTH.exists():
        try:
            data = json.loads(HEALTH.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            data = {}
    data[provider] = {"estado": status, "detalle": detail[:200], "visto": _now()}
    HEALTH.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def health() -> dict:
    """Estado por proveedor sin exponer claves (para dashboard/Telegram)."""
    _ensure_dir()
    if HEALTH.exists():
        try:
            return json.loads(HEALTH.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
    # Sin corrida previa: estado por disponibilidad de key (sin llamar a la red).
    out = {}
    for name in ("mistral", "qwen", "aionlabs", "bedrock", "cloudflare", "ollama"):
        out[name] = _key_available(name)
    return out


def _key_available(name: str) -> dict:
    import os
    cfg = config.PROVIDERS.get(name, {})
    if name == "ollama":
        return {"estado": "fallback local", "detalle": f"modelo {cfg.get('model', '')}; se verifica al usarlo"}
    key = os.environ.get(cfg.get("key_env", ""), "")
    if name == "cloudflare":
        cfg = cfg or {}
        url_ok = bool(config.cloudflare_cfg())
        return {"estado": "listo" if (key and url_ok) else "pendiente",
                "detalle": "cuenta+token" if url_ok else "falta CLOUDFLARED_ACCOUNTS_ID" if key else "sin token"}
    if key:
        return {"estado": "listo (sin verificar en vivo)", "detalle": ""}
    return {"estado": "pendiente", "detalle": f"sin {cfg.get('key_env', 'key')}"}


# ------------------------------------------------------------------ caché
def _cache_key(provider: str, payload: dict) -> str:
    canon = json.dumps({"provider": provider, "model": payload.get("model"),
                        "messages": payload.get("messages"),
                        "temperature": payload.get("temperature"),
                        "max_tokens": payload.get("max_tokens")}, sort_keys=True)
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()[:32]


def cache_get(provider: str, payload: dict) -> str | None:
    config.LLM_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    p = config.LLM_CACHE_DIR / f"{_cache_key(provider, payload)}.json"
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        p.unlink()
        return None
    if datetime.fromisoformat(data["ts"].replace("Z", "")) < datetime.utcnow() - timedelta(hours=config.LLM_CACHE_TTL_H):
        return None
    return data["text"]


def cache_put(provider: str, payload: dict, text: str) -> None:
    config.LLM_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    (config.LLM_CACHE_DIR / f"{_cache_key(provider, payload)}.json").write_text(
        json.dumps({"ts": _now(), "text": text}, ensure_ascii=False), encoding="utf-8")


# ------------------------------------------------------------------ llamada
TRANSITORIOS = {429, 500, 502, 503, 504}


def _timeout_local(payload: dict) -> int:
    """Tiempo del modelo local, proporcional al pedido (no un techo fijo de 4 minutos).

    Medido 2026-11-05 en la corrida diaria: factcheck manda lotes de ~6.000 caracteres y
    deepseek-r1:1.5b en 2 núcleos NO los termina nunca; cada lote agotaba los 240 s y
    terminaba respondiendo Cloudflare en 1 s. Diez lotes = 40 minutos de reloj para
    exactamente nada. Con un techo proporcional, un prompt chico local sigue teniendo su
    chance y un prompt grande pasa al siguiente proveedor en un minuto.
    """
    caracteres = sum(len(str(m.get("content") or "")) for m in payload.get("messages") or [])
    segundos = 30 + caracteres // 200               # ~30 s base + 5 s cada 1.000 caracteres
    return int(max(45, min(config.LLM_LOCAL_TIMEOUT_S, segundos)))


def _post(url: str, payload: dict, headers: dict, name: str) -> tuple:
    """(Response|None, error). Reintenta SOLO fallos transitorios con backoff exponencial.

    Un 429/5xx o un corte de red se reintenta en el MISMO proveedor (conmutar de modelo
    ante un rate-limit sólo dilapida la ruta y empeora el resultado). Un 401/403/400 NO:
    la key está mal o el pedido es inválido, y esperar no lo arregla.
    """
    intentos = (1 if name == "ollama" or name.startswith("workers_ai:") else
                max(1, int(getattr(config, "LLM_MAX_RETRIES_PER_PROVIDER", 1))))
    espera = float(getattr(config, "LLM_RETRY_BASE_S", 1.5))
    techo = float(getattr(config, "LLM_RETRY_MAX_S", 12.0))
    ultimo = ""
    for n in range(intentos):
        retry_after = 0.0
        try:
            timeout = (_timeout_local(payload) if name == "ollama"
                       else config.LLM_TIMEOUT_S)
            r = requests.post(url, json=payload, headers=headers, timeout=timeout)
        except requests.RequestException as exc:
            ultimo = f"error de red: {exc.__class__.__name__}"
            if name == "ollama":
                # Sin esta línea el corte del modelo local era invisible: la fábrica
                # tardaba minutos de más y state/proveedores.json no decía por qué.
                _health_record(name, "lento", f"sin respuesta en {timeout}s ({ultimo})")
        else:
            if r.status_code < 400:
                return r, ""
            ultimo = f"HTTP {r.status_code}: {r.text[:200]}"
            if r.status_code not in TRANSITORIOS:
                if r.status_code in (401, 403):
                    ultimo += " (key rechazada)"
                _health_record(name, "error", ultimo)
                return None, ultimo
            if r.status_code == 429:
                _health_record(name, "rate_limit", ultimo)
                try:
                    retry_after = float(r.headers.get("Retry-After", "") or 0)
                except ValueError:
                    retry_after = 0.0
        if n + 1 < intentos:
            time.sleep(min(max(espera, retry_after), techo) + random.random() * 0.4)
            espera *= 2
    return None, f"{ultimo} (tras {intentos} intentos)"


def _contenido_de(choice: dict):
    """El texto de un choice, venga como venga.

    OpenAI/Cloudflare: message.content = str. Ollama con modelos de razonamiento lo
    devuelve como objeto (content/reasoning_content) y un regex sobre un dict revienta
    la corrida entera (TypeError en factcheck, medido 2026-11-05).
    """
    texto = (choice.get("message") or {}).get("content", "")
    if isinstance(texto, dict):
        texto = texto.get("content") or texto.get("text") or ""
    if not isinstance(texto, str):
        return ""
    return texto


def _sin_razonamiento(texto: str) -> str:
    """Saca el bloque <reasoning>...</reasoning> que gpt-oss escribe dentro de "content".

    Un <reasoning> sin cierre significa que max_tokens se agotó razonando y la respuesta
    nunca empezó: eso no es texto útil, es una llamada que hay que volver a pedir.
    """
    if not isinstance(texto, str):
        return ""
    limpio = _REASONING.sub("", texto)
    if "<reasoning>" in limpio or "<think>" in limpio:
        return ""
    return limpio.strip()


def _iniciar_ollama_si_hace_falta() -> str:
    """Levanta el daemon local una vez si el endpoint por defecto todavía no responde."""
    cfg = config.PROVIDERS["ollama"]
    raiz = cfg["url"].split("/v1/chat/completions", 1)[0].rstrip("/")
    try:
        r = requests.get(raiz + "/api/tags", timeout=2)
        if r.ok:
            return ""
    except requests.RequestException:
        pass
    from urllib.parse import urlparse
    host = urlparse(raiz).hostname
    if host not in ("127.0.0.1", "localhost"):
        return f"Ollama remoto no responde en {raiz}"
    exe = shutil.which("ollama")
    if not exe:
        return "Ollama local no está instalado"
    try:
        # El daemon que levanta la fábrica hereda el contexto pedido: /v1 no acepta
        # options.num_ctx por request, así que la única vía es arrancarlo con el valor.
        entorno = {**os.environ,
                   "OLLAMA_CONTEXT_LENGTH": os.environ.get("OLLAMA_CONTEXTO_TOKENS", "4096")}
        subprocess.Popen([exe, "serve"], stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         env=entorno, start_new_session=True)
    except OSError as exc:
        return f"no se pudo iniciar Ollama ({exc.__class__.__name__})"
    for _ in range(60):
        time.sleep(0.5)
        try:
            r = requests.get(raiz + "/api/tags", timeout=2)
            if r.ok:
                return ""
        except requests.RequestException:
            continue
    return "Ollama está instalado pero el servicio local no inició"


def _gasto_gemini() -> float:
    """USD gastados en el mes con el fallback pagado (estado/llm_budget.json)."""
    try:
        mes = time.strftime("%Y-%m")
        d = json.loads(config.GEMINI_BUDGET_FILE.read_text(encoding="utf-8"))
        return float(d.get(mes, {}).get("usd", 0.0))
    except Exception:
        return 0.0


def _registrar_gasto_gemini(cfg: dict, body: dict) -> None:
    """Estima tokens y actualiza el ledger mensual; nunca lanza (el gasto ya ocurrió)."""
    try:
        usage = body.get("usage") or body.get("usageMetadata") or {}
        tin = int(usage.get("prompt_tokens") or usage.get("promptTokenCount") or 0)
        tout = int(usage.get("completion_tokens") or usage.get("candidatesTokenCount") or 0)
        costo = tin * cfg["precio_in_usd_mtok"] / 1e6 + tout * cfg["precio_out_usd_mtok"] / 1e6
        mes = time.strftime("%Y-%m")
        saldo = {"usd": round(_gasto_gemini() + costo, 6),
                 "llamadas": 0, "tokens_in": tin, "tokens_out": tout}
        p = config.GEMINI_BUDGET_FILE
        data = {}
        if p.exists():
            data = json.loads(p.read_text(encoding="utf-8"))
        prev = data.get(mes, {})
        saldo["llamadas"] = int(prev.get("llamadas", 0)) + 1
        saldo["tokens_in"] = int(prev.get("tokens_in", 0)) + tin
        saldo["tokens_out"] = int(prev.get("tokens_out", 0)) + tout
        data[mes] = saldo
        p.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception:  # noqa: BLE001 — jamás romper una respuesta por bookkeeping
        pass


def _registrar_gasto_extra(costo_usd: float, detalle: str) -> None:
    """Ledger compartido de costo Pro (texto + imágenes) en state/llm_budget.json.

    Los gastos de imagen se suman a `usd` del mes, así el tope GEMINI_PRESUPUESTO_USD_MES
    cubre TODO lo pago del canal — no es por sesión ni por modelo.
    """
    try:
        mes = time.strftime("%Y-%m")
        p = config.GEMINI_BUDGET_FILE
        data = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
        prev = data.get(mes, {})
        data[mes] = {
            "usd": round(float(prev.get("usd", 0.0)) + costo_usd, 6),
            "llamadas": int(prev.get("llamadas", 0)),
            "tokens_in": int(prev.get("tokens_in", 0)),
            "tokens_out": int(prev.get("tokens_out", 0)),
            "imagenes": int(prev.get("imagenes", 0)) + 1,
            "ultimo_detalle": detalle[:80],
        }
        p.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception:  # noqa: BLE001 — jamás romper una respuesta por bookkeeping
        pass


def _tokens_aprox(mensajes: list[dict]) -> int:
    """Estimación basta (español ≈ 3,2 caracteres/token) para no pedir lo que no entra."""
    return sum(len(str(m.get("content", ""))) for m in mensajes) // 3 + 8 * len(mensajes)


def _techo_local(max_tokens: int, mensajes: list[dict]) -> int:
    """Recorta la salida pedida al contexto REAL del modelo local.

    Ollama por /v1 ignora options.num_ctx (medido: 7.209 tokens -> HTTP 400 con
    n_ctx=4096), así que el único que puede respetar el techo es quien arma el payload.
    Sin esto cualquier guion largo moría en el fallback local.
    """
    techo = int(os.environ.get("OLLAMA_CONTEXTO_TOKENS", "4096"))
    disponible = techo - _tokens_aprox(mensajes) - 32
    return max(120, min(max_tokens, disponible))


def _call_provider(name: str, messages: list[dict], temperature: float,
                   max_tokens: int) -> tuple[dict | None, str]:
    cfg = config.PROVIDERS[name]
    if name == "cloudflare":
        cfg = config.cloudflare_cfg()
        if not cfg.get("url"):
            return None, "sin CLOUDFLARED_ACCOUNTS_ID"
        config.PROVIDERS["cloudflare"] = cfg
    if config.DISABLED_PROVIDERS.get(name):
        return None, config.DISABLED_PROVIDERS[name]
    if name == "ollama":
        error = _iniciar_ollama_si_hace_falta()
        if error:
            return None, error
    local = name == "ollama"
    key = os.environ.get(cfg.get("key_env", ""), "") if cfg.get("key_env") else ""
    # Bedrock acepta tanto BADROCK_API_KEY (nombre histórico del .env) como
    # AWS_BEARER_TOKEN_BEDROCK (nombre estándar de AWS). Se prueba el primero y,
    # si falta, el segundo: así el usuario puede pegar el token con cualquiera de
    # los dos nombres sin tocar config.
    if not key and cfg.get("key_env") == "BADROCK_API_KEY":
        key = os.environ.get("AWS_BEARER_TOKEN_BEDROCK", "")
    if not key and not local:
        _health_record(name, "pendiente", f"sin {cfg.get('key_env', 'key')}")
        return None, f"sin {cfg.get('key_env', 'key')}"
    if name == "aionlabs" and os.environ.get("ALLOW_AIONLABS", "").strip().lower() not in ("1", "true", "yes", "on"):
        return None, "proveedor remoto desactivado por costo potencial (ALLOW_AIONLABS no está habilitado)"
    if name == "ollama":
        pedido = max_tokens
        max_tokens = _techo_local(max_tokens, messages)
        if max_tokens < pedido:
            print(f"  ollama: salida recortada {pedido} -> {max_tokens} tokens "
                  f"(contexto {os.environ.get('OLLAMA_CONTEXTO_TOKENS', '4096')})")
    payload = {"model": cfg["model"], "messages": messages,
               "temperature": temperature, "max_tokens": max_tokens,
               **(cfg.get("params") or {})}
    hit = cache_get(name, payload)
    if hit:
        texto = _sin_razonamiento(hit)
        if not texto:
            return None, "cache con sólo razonamiento (se vuelve a pedir)"
        return {"text": texto, "latency": 0.0, "cost": 0.0, "cache": True}, None
    if name == "gemini":
        tope = float(os.environ.get("GEMINI_PRESUPUESTO_USD_MES", "4.50"))
        gasto = _gasto_gemini()
        if gasto >= tope:
            return None, (f"presupuesto mensual de Gemini agotado "
                          f"({gasto:.2f} USD >= {tope:.2f} USD)")
    headers = {"Content-Type": "application/json"}
    if key:
        headers["Authorization"] = f"Bearer {key}"
    t0 = time.time()
    r, err = _post(cfg["url"], payload, headers, name)
    if r is None:
        return None, err
    latency = round(time.time() - t0, 2)
    body = r.json()
    if cfg.get("api") == "cloudflare":
        if not body.get("success"):
            return None, f"cloudflare sin success: {str(body.get('errors'))[:150]}"
        result = body.get("result") or {}
        # Workers AI cambió de formato: @cf/meta/llama-3.1-8b-* devuelve adentro de result
        # un chat.completion de OpenAI (medido 2026-11-05). Leer sólo result.response daba
        # vacío y tiraba toda la corrida al modelo local de 1.5B.
        if isinstance(result, dict) and result.get("choices"):
            text = _contenido_de(result["choices"][0])
        else:
            text = result.get("response", "") if isinstance(result, dict) else ""
    else:
        choices = body.get("choices") or []
        if not choices:
            return None, "respuesta sin choices"
        text = _contenido_de(choices[0])
    text = _sin_razonamiento(text)
    if not text or not text.strip():
        return None, "respuesta vacía (el presupuesto se fue en razonamiento)"
    if name == "gemini":
        _registrar_gasto_gemini(cfg, body)
    _health_record(name, "ok", "respondió chat completions")
    cache_put(name, payload, text)
    return {"text": text, "latency": latency, "cost": 0.0, "cache": False}, None


def _habilitado(nombre: str) -> bool:
    """Si la bandera de entorno del proveedor está prendida; los que no la tienen no piden permiso."""
    bandera = config.HABILITADOR.get(nombre)
    if bandera is None:
        return True
    return os.environ.get(bandera, "").strip().lower() in ("1", "true", "yes", "on")


def ruta_de(task: str) -> list[str]:
    """La ruta declarada en config, filtrada por lo que el entorno permite usar hoy."""
    route = [p for p in (config.TASK_ROUTES.get(task) or config.TASK_ROUTES["default"])
             if _habilitado(p)]
    if task in config.TAREAS_PREMIUM and _habilitado("gemini") and "gemini" not in route:
        route = ["gemini", *route]
    return route or ["ollama"]


def chat(messages: list[dict], *, temperature: float = 0.4, max_tokens: int = 1500,
         tag: str = "", episode: str = "", task: str = "") -> str:
    """Recorre la ruta de la tarea y devuelve el texto de la primera respuesta exitosa.

    Acá sólo se conmuta de proveedor; el reintento de lo transitorio vive en `_post`
    (mismo proveedor, backoff exponencial). Antes había un segundo bucle de reintento
    encima y se multiplicaban las llamadas (5 x 3 = 15 por proveedor), congelando una
    corrida entera en una máquina de 2 núcleos.

    El dinero es la excepción, no el default: la ruta la manda config.TASK_ROUTES y las
    banderas de entorno sólo deciden si un nombre del listado existe. Gemini encabeza
    únicamente las tareas premium (config.TAREAS_PREMIUM); para el resto la corrida es
    gratis de punta a punta y se corta antes que seguir gastando.
    """
    task = task or config.tarea_para_tag(tag)
    route = ruta_de(task)
    failures = []
    for name in route:
        result, err = _call_provider(name, messages, temperature, max_tokens)
        if result:
            _log({
                "ts": _now(), "episode": episode, "task": task, "tag": tag,
                "provider": name, "model": config.PROVIDERS[name]["model"],
                "latency_s": result["latency"],
                "desde_cache": result.get("cache", False),
                "fallback_de": [f["provider"] for f in failures],
                "status": "ok",
            })
            return result["text"]
        failures.append({"provider": name, "reason": err})
    _log({"ts": _now(), "episode": episode, "task": task, "tag": tag,
          "status": "all_failed", "failures": failures})
    raise AllProvidersFailed(
        f"Todos los proveedores fallaron: {json.dumps(failures, ensure_ascii=False)}")


def chat_json(messages: list[dict], **kw):
    """chat() + parseo JSON con reintentos: los gates no pueden depender de un formateo perfecto."""
    import json as _json
    import re as _re
    task = kw.pop("task", "")
    last = None
    for _ in range(3):
        answer = chat(messages, task=task, **kw)
        m = _re.search(r"\{.*\}|\[.*\]", answer, _re.S)
        if m:
            try:
                return _json.loads(m.group(0))
            except _json.JSONDecodeError as exc:
                last = exc
        else:
            last = ValueError(f"sin JSON: {answer[:150]}")
        kw["temperature"] = min(1.0, kw.get("temperature", 0.4) + 0.2)
    raise AllProvidersFailed(f"JSON inválido en 3 intentos: {last}")


def verificar_disponibilidad() -> dict:
    """Health-check en vivo: una llamada mínima por proveedor y registra el estado."""
    _ensure_dir()
    out = {}
    for name in config.PROVIDER_ORDER:
        # min_tokens generoso: los modelos de razonamiento (aion) devuelven vacío con cortes chicos.
        result, err = _call_provider(name, [{"role": "user", "content": "Respondé con la palabra: ok"}],
                                     temperature=0.0, max_tokens=200)
        out[name] = {"ok": result is not None, "detalle": err or "respondió",
                     "model": config.PROVIDERS[name]["model"]}
    _health_log = STATE_DIR / "proveedores_healthcheck.json"
    _health_log.write_text(json.dumps({"ts": _now(), "resultado": out},
                                      indent=2, ensure_ascii=False), encoding="utf-8")
    return out
