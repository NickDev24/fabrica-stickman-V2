import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROJECTS = ROOT / "projects"
REGISTRY = ROOT / "registry"
STATE = ROOT / "state"

# Constantes de render usadas por montaje/graphics/short/derivados (faltaban -> bug que frenaba todo render)
VIDEO_W, VIDEO_H, VIDEO_FPS = 720, 1280, 24
FFMPEG_PRESET = os.environ.get("FFMPEG_PRESET", "veryfast")
FFMPEG_CRF = int(os.environ.get("FFMPEG_CRF", "23"))

# Piper reemplazó a VibeVoice como motor de narración (medido: 22,5 s para 45 s de audio).
PIPER_BIN = Path.home() / "piper-env" / "bin" / "piper"
# Voz CapCut-like (Microsoft neural): elegida por el dueño 2026-11-04 para todos los
# capítulos; la voz por defecto ahora es edge-tts:es-AR-TomasNeural (allowlist-eada).
EDGE_TTS_BIN = Path(os.environ.get("EDGE_TTS_BIN", str(Path.home() / ".local" / "bin" / "edge-tts")))
EDGE_TTS_VOICE = os.environ.get("EDGE_TTS_VOICE", "es-AR-TomasNeural")
VOZ_PREFERIDA = os.environ.get("VOZ_PREFERIDA", f"edge-tts:{EDGE_TTS_VOICE}")
# Voz argentina de alta calidad para la narración (decisión del dueño, 2026-11-04).
# Costo medido en el B950: 6,5x tiempo real (65 s de audio ≈ 7-8 min de síntesis).
# La x_low queda como fallback rápido vía PIPER_MODEL_NAME en .env.
PIPER_MODEL_NAME = os.environ.get("PIPER_MODEL_NAME", "es_AR-daniela-high")
PIPER_MODEL_PATH = Path(os.environ.get(
    "PIPER_MODEL_PATH", str(ROOT / "models" / "voices" / "es_AR-daniela-high.onnx")))

# Ritmo de la narración: >1 alarga los fonemas; la pausa entre frases evita el
# atropello y da espacio para que respire el relato. Para Daniela 0.95-1.0 suena
# natural; 1.12 era el valor calibrado para carlfm_x_low (medido 2026-11-03).
PIPER_LENGTH_SCALE = float(os.environ.get("PIPER_LENGTH_SCALE", "1.0"))
PIPER_SENTENCE_SILENCE = float(os.environ.get("PIPER_SENTENCE_SILENCE", "0.65"))

# Identidad visual del canal: un solo personaje reutilizable (NO una persona real).
MASCOTA_HERO = ROOT / "assets" / "mascota" / "pulso-hero.png"
MASCOTA_ESTUDIO = ROOT / "assets" / "mascota" / "pulso-estudio.png"

# Vertical 9:16: 25 fps en vez de 30 porque en el B950 costea ~20% mas de render sin ganancia.
SHORT_W, SHORT_H, SHORT_FPS, SHORT_SUB = 1080, 1920, 25, 62
# El presentador nunca puede faltar mas de este tramo (regla medida: 3,5 s).
AUSENCIA_MAX_S = 3.5
# El Short va igual de natural que el documental; subir el ritmo de Daniela la hace apurada.
PIPER_LENGTH_SCALE_SHORT = float(os.environ.get("PIPER_LENGTH_SCALE_SHORT", "1.0"))

EDGE_TTS_VOICE = "es-AR-TomasNeural"

# Gate 2: única voz permitida = narradora propia del canal. Nada de clonación.
VOICE_ALLOWLIST = {
    "piper:es_ES-carlfm-x_low",
    "piper:es_AR-daniela-high",
    "edge-tts:es-AR-TomasNeural",
}

# Gate 4: similitud máxima contra los últimos N guiones publicados.
SIMILARITY_MAX_NGRAM = 0.55
SIMILARITY_MAX_STRUCTURE = 0.75
COMPARE_LAST_N = 5

# Gate 5: cascada multi-proveedor con las claves reales de .env. Endpoints verificados
# contra la documentación oficial (2026-11-03); nada inventado:
#  - Mistral: https://docs.mistral.ai (api.mistral.ai, OpenAI-compatible)
#  - Qwen MaaS compatible-mode (dato del propio .env del usuario)
#  - Cloudflare Workers AI: https://developers.cloudflare.com/workers-ai
#  - Amazon Bedrock OpenAI Chat Completions + Bedrock API key (bearer):
#    https://docs.aws.amazon.com/bedrock/latest/userguide/inference-chat-completions.html
#  - Aion Labs: https://www.aionlabs.ai/docs/api-reference (api.aionlabs.ai/v1, OpenAI-compatible)
QWEN_DEFAULT_BASE_URL = "https://ap-southeast-1.maas.qwencloudapi.com/compatible-mode/v1"

PROVIDER_ORDER = ["ollama", "mistral", "qwen", "aionlabs", "cloudflare", "bedrock", "gemini"]
GEMINI_BUDGET_FILE = STATE / "llm_budget.json"
DISABLED_PROVIDERS: dict = {}

PROVIDERS = {
    "mistral": {
        "url": "https://api.mistral.ai/v1/chat/completions",
        "key_env": "MISTRAL_API_KEY",
        "model": os.environ.get("MISTRAL_MODEL", "mistral-small-latest"),
    },
    "qwen": {
        "url": os.environ.get("QWEN_BASE_URL", QWEN_DEFAULT_BASE_URL).rstrip("/") + "/chat/completions",
        "key_env": "QWEN_API_KEY",
        "model": os.environ.get("QWEN_MODEL", "qwen-plus"),
    },
    "aionlabs": {
        "url": os.environ.get("AIONLABS_BASE_URL", "https://api.aionlabs.ai/v1").rstrip("/") + "/chat/completions",
        "key_env": "AIONLABS_API_KEY",
        # Modelo confirmado vía GET /v1/models (health-check 2026-11-03).
        "model": os.environ.get("AIONLABS_MODEL", "aion-labs/aion-2.0"),
    },
    "bedrock": {
        "url": (f"https://bedrock-runtime.{os.environ.get('BEDROCK_REGION', 'us-east-1')}.amazonaws.com"
                "/openai/v1/chat/completions"),
        "key_env": "BADROCK_API_KEY",  # nombre del .env; es una Amazon Bedrock API key (bearer)
        "model": os.environ.get("BEDROCK_MODEL", "openai.gpt-oss-120b-1:0"),
        # gpt-oss razona DENTRO de "content" (medido: '<reasoning>...' y ninguna respuesta si
        # el presupuesto alcanza sólo para el razonamiento). Con reasoning_effort=low el
        # endpoint responde en 1,3 s y deja el JSON; sin él, cada llamada de la fábrica
        # devolvía razonamiento truncado.
        "params": {"reasoning_effort": os.environ.get("BEDROCK_REASONING_EFFORT", "low")},
    },
    "cloudflare": {"url": "", "key_env": "CLOUDFLARED_WORKER_AI",
                   "model": os.environ.get("CLOUDFLARED_MODEL", "@cf/meta/llama-3.1-8b-instruct"),
                   "api": "cloudflare"},
    # Respaldo PAGADO de último recurso (proyecto con $5 de saldo y billing activado):
    # sólo entra cuando TODAS las rutas gratis fallo (ollama + remores sin cuota).
    # Intro $0.75/1M in, $3.75/1M out hasta 31-dic-2026; desde 1-ene: $1.50/$7.50.
    # Tope duro: estado/llm_budget.json corta el uso al superar GEMINI_PRESUPUESTO_USD_MES.
    "gemini": {
        "url": "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
        "key_env": "GEMINI_API_KEY",
        "model": os.environ.get("GEMINI_MODEL", "gemini-3.8-flash"),
        # gemini-3.8-flash razona por defecto y el razonamiento se come el max_tokens del
        # JSON (demostrado: 19/19 ideas descartadas por truncado). 'low' responde completo.
        "params": {"reasoning_effort": os.environ.get("GEMINI_REASONING_EFFORT", "low")},
        "precio_in_usd_mtok": float(os.environ.get("GEMINI_INPUT_USD_MTOK", "0.75")),
        "precio_out_usd_mtok": float(os.environ.get("GEMINI_OUTPUT_USD_MTOK", "3.75")),
        "presupuesto_usd_mes": float(os.environ.get("GEMINI_PRESUPUESTO_USD_MES", "4.50")),
    },
    # Fallback local sin costo. Usa modelos que ya están instalados en Ollama;
    # no descarga modelos ni llama a Ollama Cloud.
    "ollama": {
        "url": os.environ.get("OLLAMA_BASE_URL", "http://127.0.0.1:11434/v1").rstrip("/")
               + "/chat/completions",
        "key_env": "",
        "model": os.environ.get("OLLAMA_MODEL", "deepseek-r1:1.5b"),
        "api": "ollama",
    },
}


def limites() -> dict:
    """Límites de recursos reales de la fábrica (render-optimization-engineer).

    Hardware objetivo: CPU mínima 4 núcleos, 8 GB RAM. Un render simultáneo,
    720p/24fps para el GLB, serialización de renders, y presupuesto de proveedores.
    """
    return {
        "max_render_simultaneos": int(os.environ.get("MAX_RENDER_SIMULTANEOS", "1")),
        "video_w": VIDEO_W, "video_h": VIDEO_H, "video_fps": VIDEO_FPS,
        "max_ram_render_mb": int(os.environ.get("MAX_RAM_RENDER_MB", "3500")),
        "serializar_ffmpeg": True,
        "llm_max_retries_por_proveedor": LLM_MAX_RETRIES_PER_PROVIDER,
        "llm_timeout_s": LLM_TIMEOUT_S,
        "presupuesto_usd_msj": float(os.environ.get("PRESUPUESTO_USD_MSJ", "0")),
    }


def cloudflare_cfg() -> dict:
    """Workers AI necesita account id + token: se resuelve lazy, no al importar."""
    load_env()
    account = os.environ.get("CLOUDFLARED_ACCOUNTS_ID", "")
    if not account:
        return {}
    cfg = dict(PROVIDERS["cloudflare"])
    cfg["url"] = (f"https://api.cloudflare.com/client/v4/accounts/{account}/ai/run/"
                  f"{cfg['model']}")
    return cfg


# Reparto por tarea: verificación con un proveedor INDEPENDIENTE del que escribió (misión §3).
TASK_ROUTES = {
    # ollama primero siempre (gratis e ilimitado); gemini cierra cada ruta (pago, con tope)
    "default": ["ollama"],
    "investigacion": ["ollama"],
    "guion": ["ollama"],
    "verificacion": ["ollama"],
    "direccion": ["ollama"],
    "prompts_visuales": ["ollama"],
    "evaluacion": ["ollama"],
}

LLM_CACHE_DIR = STATE / "llm_cache"
LLM_CACHE_TTL_H = 24.0
LLM_TIMEOUT_S = 120
# El modelo local corre en 2 núcleos: un timeout corto lo aborta a mitad de una respuesta
# válida y uno de 10 min congela la fábrica. 240 s es el techo operativo; se puede bajar
# con LLM_LOCAL_TIMEOUT_S si el equipo es más lento o se usa un modelo más grande.
LLM_LOCAL_TIMEOUT_S = int(os.environ.get("LLM_LOCAL_TIMEOUT_S", "240"))
# Intentos por proveedor antes de conmutar (lo consume pipeline/llm.py; antes era decorativo).
LLM_MAX_RETRIES_PER_PROVIDER = 3
LLM_RETRY_BASE_S = 1.5      # backoff exponencial: 1.5s, 3s, 6s…
LLM_RETRY_MAX_S = 12.0      # techo por espera, para no congelar una corrida entera

# Telegram como centro de control (nombres reales del .env).
TELEGRAM_TOKEN_ENV = "TELEGRAM_TOKEN_BOT"
TELEGRAM_CHAT_ENV = "TELEGRAM_CHAT_ID"

# Umbrales de formato de salida.
TIKTOK_TEASER_S = 90
IG_TEASER_S = 30
IG_ARTICLE_MIN_WORDS = 1200
IG_ARTICLE_MAX_WORDS = 3000
YT_PARTS = 3

# Publicación siempre manual por defecto. Sólo AUTO_PUBLISH=true habilita Zernio.
TELEGRAM_ENABLED_FOR_REVIEW = True


def auto_publish() -> bool:
    """La publicación externa requiere opt-in explícito, nunca se infiere de una API key."""
    load_env()
    v = os.environ.get("AUTO_PUBLISH", "").strip().lower()
    return v in ("1", "true", "yes", "on")


def zernio_config() -> dict:
    load_env()
    return {
        "api_key": os.environ.get("ZERNIO_API_KEY", ""),
        "account_id": os.environ.get("ZERNIO_ACCOUNT_ID", ""),
        "base_url": os.environ.get("ZERNIO_BASE_URL", "").rstrip("/"),
        "youtube": os.environ.get("ZERNIO_YOUTUBE_ID", os.environ.get("ZERNIO_ID_YOUTUBE", "")),
        "facebook": os.environ.get("ZERNIO_FACEBOOK_ID", os.environ.get("ZERNIO_ID_FACEBOOK", "")),
    }


def load_env(path: Path | None = None) -> None:
    """Carga .env sin dependencias. No pisa variables ya presentes."""
    env_path = path or (ROOT / ".env")
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)
