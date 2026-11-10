# PULSO Curioso — Fábrica Autónoma de Contenido (V2)

Genera **videos** (máster 9:16 + derivados YouTube/Facebook) y **cómics** con un pipeline automatizado. Se ejecuta en local con Docker Compose (backend + dashboard).

- **Repo:** https://github.com/NickDev24/fabrica-stickman-V2
- **Panel:** http://localhost:8611 (Mission Control)
- **API/health:** http://localhost:8610/api/health

![Mission Control](assets/docs/dashboard-inicio.png)

---

## Requisitos

- **Git**
- **Docker Engine** y **Docker Compose v2** (`docker compose`)
- ~8–15 GB de disco libre (imágenes Docker, caché/renders) y 8 GB+ RAM recomendado
- (Opcional) Claves/API para publicación y proveedores LLM/imágenes (ver `.env.example`)

> Nota: `docker-compose.yml` monta rutas del host (`/home/facu/piper-env`, `/home/facu/.local/bin` y el propio repo en `/app`) y fija `HOME=/home/facu` para que el pipeline resuelva TTS/herramientas como en el entorno esperado. Ajusta esos volúmenes/rutas si tu usuario o instalación difiere.

---

## Instalación (local)

### 1. Clonar

```bash
git clone https://github.com/NickDev24/fabrica-stickman-V2.git
cd fabrica-stickman-V2
```

### 2. Configurar entorno

```bash
cp .env.example .env
```

Edita `.env` con tus valores. Las variables disponibles (según `.env.example`) son:

| Variable | Descripción / uso |
|---|---|
| `MISTRAL_API_KEY`, `QWEN_API_KEY` | Claves de proveedores LLM (opcionales, según tu stack) |
| `CLOUDFLARED_ACCOUNTS_ID`, `CLOUDFLARED_WORKER_AI` | Cloudflare (Workers AI / imágenes, si aplica) |
| `BADROCK_API_KEY`, `AIONLABS_API_KEY` | Proveedores adicionales (opcionales) |
| `TELEGRAM_TOKEN_BOT`, `TELEGRAM_CHAT_ID` | Integración/notificaciones Telegram (opcional) |
| `ZERNIO_API_KEY`, `ZERNIO_ACCOUNT_ID`, `ZERNIO_FACEBOOK_ID`, `ZERNIO_YOUTUBE_ID` | Publicación vía Zernio (IDs de cuentas/canales destino) |
| `AUTO_PUBLISH`, `FACTORY_PUBLISH` | Control de publicación automática (compose usa `FACTORY_PUBLISH`, default `1`) |
| `KF_RECICLADO_CADA` | Frecuencia de reciclado de imágenes (default `2`) |
| `COMICS_ENABLED`, `COMICS_CAPTIONS_LLM` | Opciones del módulo cómics |
| `KAGGLE_API_KEY`, `HUGGINFACE_TOKEN` | Tokens de plataformas (opcionales) |
| `GEMINI_API_KEY`, `GOOGLE_GEMINI_API_KEY`, `NAME_PROJECT`, `NUMBER_PROJECT`, `ID_PROJECT` | Configuración/proyectos Google/Gemini (opcional) |
| `ALLOW_PAID_LLM`, `GEMINI_PRESUPUESTO_USD_MES`, `ALLOW_REMOTE_LLM` | Control de costos/LLM remoto o de pago |
| `CF_MAX_IMAGENES_DIA`, `POLLINATIONS_API_KEY` | Límites/proveedores de imagen |

- **No subas `.env`** al repositorio (contiene secretos).
- Puedes iniciar sin claves para ejecución/generación local según disponibilidad de proveedores; para publicar configura `ZERNIO_*` y los IDs de tus cuentas/canales (`ZERNIO_YOUTUBE_ID`, `ZERNIO_FACEBOOK_ID`, etc.).
- Si no quieres publicar automáticamente, ajusta `FACTORY_PUBLISH`/`AUTO_PUBLISH` según tu flujo antes de levantar.

### 3. Levantar

```bash
docker compose up -d --build
```

Servicios (`docker-compose.yml`):
- **factory** (`pulso-factory`): Python 3.13 + ffmpeg/tesseract, ejecuta `factoryd` (REST/WebSocket `:8610`), loop 24/7. Monta `.:/app`, `~/piper-env`, `~/.local/bin`; usa `host.docker.internal` para Ollama (`OLLAMA_BASE_URL=http://host.docker.internal:11434/v1`).
- **dashboard** (`pulso-dashboard`): nginx sirviendo Mission Control en `:8611` (proxy a la API interna).

### 4. Verificar

```bash
docker compose ps
curl http://localhost:8610/api/health
# esperado: {"ok": true}
```

Abre el panel: http://localhost:8611

---

## Panel (Mission Control)

Capturas reales del dashboard incluido:

| Inicio | Fábrica de Video |
|---|---|
| ![Inicio](assets/docs/dashboard-inicio.png) | ![Video](assets/docs/dashboard-fabrica-video.png) |

| Fábrica de Cómics | Métricas |
|---|---|
| ![Cómics](assets/docs/dashboard-fabrica-comics.png) | ![Métricas](assets/docs/dashboard-metricas.png) |

| Conectores | Oficina 3D |
|---|---|
| ![Conectores](assets/docs/dashboard-conectores.png) | ![Oficina 3D](assets/docs/dashboard-oficina3d.png) |

Recorridos grabados (existentes en el repo):  
- `assets/docs/tutorial-install.mp4`  
- `assets/docs/tutorial-dashboard.mp4`

---

## Ejemplos generados

- Reel Facebook: `assets/docs/examples/ejemplo-reel-facebook.mp4`
- YouTube Short: `assets/docs/examples/ejemplo-youtube-short.mp4`
- Collage: `assets/docs/examples/ejemplo-collage.mp4`
- Cómic: `assets/docs/examples/ejemplo-comic.png`

---

## Operación

```bash
docker compose logs -f factory   # logs
docker restart pulso-factory     # reiniciar backend
docker compose down              # detener
docker compose up -d             # levantar
```

- `FACTORY_PUBLISH` controla publicación autónoma (default `1` en compose). Para revisar antes de publicar, desactívalo en `.env` y reinicia.
- Estado/artefactos de runtime se generan en `state/`, `projects/`, cachés, etc. (no son parte del código fuente).

---

## Estructura

- `docker/`, `docker-compose.yml`: despliegue local
- `pipeline/`, `factory/`: motor y stages de producción
- `assets/`: assets y documentación visual
- `tests/`: pruebas
- `.env.example`: plantilla de configuración/secretos

---

## Licencia

MIT.
