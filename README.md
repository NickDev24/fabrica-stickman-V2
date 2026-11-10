# Stickman Factory V2 — Fábrica Autónoma de Video y Cómics

Plataforma local (Docker) para producir **videos** en formato 9:16 (máster y derivados: Shorts/Reels/trailers) y **cómics** con pipeline automatizado, dashboard **Mission Control** y publicación configurable.

**Repositorio:** https://github.com/NickDev24/fabrica-stickman-V2  
**Dashboard:** `http://localhost:8611` · **API/health:** `http://localhost:8610/api/health`

[![Docker Compose](https://img.shields.io/badge/Docker-Compose-2496ED?logo=docker&logoColor=white)](docker-compose.yml)
[![Backend](https://img.shields.io/badge/Backend-Python_3.13%20%2B%20ffmpeg-3776AB?logo=python&logoColor=white)](docker/factory)
[![Dashboard](https://img.shields.io/badge/Dashboard-nginx%20%2B%20JS-10b981)](#dashboard-mission-control)
[![License: MIT](https://img.shields.io/badge/License-MIT-f59e0b.svg)](#licencia)

---

## Índice

- [Descripción](#descripción)
- [Arquitectura](#arquitectura)
- [Requisitos](#requisitos)
- [Instalación rápida](#instalación-rápida)
- [Configuración (.env y secretos/canales)](#configuración-env-y-secretoscanales)
- [Deploy local](#deploy-local)
- [Verificación](#verificación)
- [Tutoriales en video (instalación, configuración y deploy)](#tutoriales-en-video-instalación-configuración-y-deploy)
- [Dashboard (Mission Control)](#dashboard-mission-control)
- [Galería de producción: videos y cómics](#galería-de-producción-videos-y-cómics)
- [Operación](#operación)
- [Seguridad y costos](#seguridad-y-costos)
- [Solución de problemas](#solución-de-problemas)
- [Estructura del repositorio](#estructura-del-repositorio)
- [Documentación](#documentación)
- [Licencia](#licencia)

---

## Descripción

| Módulo | Función |
|---|---|
| **Fábrica de Video** | Pipeline automatizado: guion/actuación → keyframes e imágenes → TTS/mezcla → render con ffmpeg → derivados 9:16 (Reels, YouTube Shorts, trailers) y artefactos por proyecto. |
| **Fábrica de Cómics** | Composición de capítulos/viñetas y portadas con controles de calidad y publicación configurable. |
| **Mission Control** | Dashboard web para estado, producción, galería, métricas y conectores (REST + WebSocket). |
| **Orquestación** | `factoryd` en loop 24/7 con controles de publicación (`FACTORY_PUBLISH`/`AUTO_PUBLISH`) y reciclado/caché de imágenes. |

> Detalles de mejoras y operación: [`MEJORAS-PRO-2026-11-10.md`](MEJORAS-PRO-2026-11-10.md).

## Arquitectura

- **`factory`** (`pulso-factory`, `:8610`): Python 3.13 + ffmpeg + tesseract. Ejecuta `python /app/docker/factory/factoryd.py` (API/WebSocket) y el pipeline (`pipeline/`, `factory/`).
- **`dashboard`** (`pulso-dashboard`, `:8611`): nginx sirviendo la UI con proxy al backend.
- **Orquestación:** [`docker-compose.yml`](docker-compose.yml) (build, healthcheck `/api/health`, volúmenes, env).

```text
Browser → Dashboard :8611 (nginx) → API/WS :8610 (factoryd) → Pipeline (video/cómics) → projects/ state/ assets/
```

## Requisitos

- Git, Docker Engine 24+ y Docker Compose v2 (`docker compose`)
- ~8–15 GB de disco libre (imágenes/caché/renders), 8 GB+ RAM recomendado
- Puertos `8610` y `8611` disponibles
- (Opcional) Ollama en host, claves LLM/imágenes y credenciales Zernio para publicación

> **Nota de entorno (`docker-compose.yml`):** monta `.:/app`, `/home/facu/piper-env`, `/home/facu/.local/bin`; usa `user: "1000:1000"` y `HOME=/home/facu` (rutas esperadas por `pipeline/config.py`). Si tu sistema difiere, ajusta `user`, `HOME` y volúmenes antes de desplegar.

## Instalación rápida

```bash
git clone https://github.com/NickDev24/fabrica-stickman-V2.git
cd fabrica-stickman-V2
cp .env.example .env
# editar .env (secretos, cuentas/canales, proveedores)
docker compose up -d --build
```

## Configuración (.env y secretos/canales)

Plantilla: [`.env.example`](.env.example). **No versionar `.env`.**

| Variable | Uso |
|---|---|
| `MISTRAL_API_KEY`, `QWEN_API_KEY` | Proveedores LLM |
| `CLOUDFLARED_ACCOUNTS_ID`, `CLOUDFLARED_WORKER_AI` | Cloudflare / Workers AI (imágenes) |
| `BADROCK_API_KEY`, `AIONLABS_API_KEY` | Proveedores adicionales |
| `TELEGRAM_TOKEN_BOT`, `TELEGRAM_CHAT_ID` | Integración Telegram |
| `ZERNIO_API_KEY`, `ZERNIO_ACCOUNT_ID`, `ZERNIO_FACEBOOK_ID`, `ZERNIO_YOUTUBE_ID` | Publicación Zernio (API y **IDs de cuentas/canales destino**) |
| `AUTO_PUBLISH`, `FACTORY_PUBLISH` | Publicación automática (`compose`: `FACTORY_PUBLISH`, default `1`) |
| `KF_RECICLADO_CADA` | Reciclado/caché de imágenes (default `2`) |
| `COMICS_ENABLED`, `COMICS_CAPTIONS_LLM` | Módulo cómics |
| `KAGGLE_API_KEY`, `HUGGINFACE_TOKEN` | Tokens de plataformas |
| `GEMINI_API_KEY`, `GOOGLE_GEMINI_API_KEY`, `NAME_PROJECT`, `NUMBER_PROJECT`, `ID_PROJECT` | Google/Gemini y proyecto |
| `ALLOW_PAID_LLM`, `GEMINI_PRESUPUESTO_USD_MES`, `ALLOW_REMOTE_LLM` | Control de costos / LLM pago o remoto |
| `CF_MAX_IMAGENES_DIA`, `POLLINATIONS_API_KEY` | Límites y proveedor de imágenes |

- **Canales:** define tus IDs reales en `ZERNIO_FACEBOOK_ID` / `ZERNIO_YOUTUBE_ID`.
- **Modo revisión (sin publicar):** `FACTORY_PUBLISH=0` (y/o `AUTO_PUBLISH=0`) y reinicia.
- **Ollama local:** `OLLAMA_BASE_URL=http://host.docker.internal:11434/v1` (compose).

## Deploy local

```bash
docker compose up -d --build   # build + arranque
docker compose ps              # estado (factory healthy)
docker compose logs -f factory # logs
docker restart pulso-factory   # reinicio backend
docker compose down            # parada
```

## Verificación

```bash
curl http://localhost:8610/api/health   # {"ok": true}
```
Abrir dashboard: **http://localhost:8611**

## Tutoriales en video (instalación, configuración y deploy)

### Instalación y puesta en marcha
<video src="assets/docs/tutorial-install.mp4" controls width="960"></video>

[`assets/docs/tutorial-install.mp4`](assets/docs/tutorial-install.mp4)

### Configuración y recorrido / deploy (dashboard y operación)
<video src="assets/docs/tutorial-dashboard.mp4" controls width="960"></video>

[`assets/docs/tutorial-dashboard.mp4`](assets/docs/tutorial-dashboard.mp4)

Guía escrita: [`TUTORIAL_INSTALACION.md`](TUTORIAL_INSTALACION.md) · [`docs/INSTALACION.md`](docs/INSTALACION.md)

## Dashboard (Mission Control)

| Inicio | Fábrica de Video |
|---|---|
| ![Inicio](assets/docs/dashboard-inicio.png) | ![Fábrica de Video](assets/docs/dashboard-fabrica-video.png) |

| Fábrica de Cómics | Métricas |
|---|---|
| ![Fábrica de Cómics](assets/docs/dashboard-fabrica-comics.png) | ![Métricas](assets/docs/dashboard-metricas.png) |

| Conectores | Oficina 3D |
|---|---|
| ![Conectores](assets/docs/dashboard-conectores.png) | ![Oficina 3D](assets/docs/dashboard-oficina3d.png) |

## Galería de producción: videos y cómics

Ejemplos reales de salida del pipeline (derivados por proyecto en `projects/<slug>/derivados/`). La fábrica genera además artefactos intermedios y renderizados según el flujo del episodio.

### Reel corto (YouTube Short)
<video src="assets/docs/examples/reel-corto-youtube-short.mp4" controls width="420"></video>

[`assets/docs/examples/reel-corto-youtube-short.mp4`](assets/docs/examples/reel-corto-youtube-short.mp4)

### Reel Facebook
<video src="assets/docs/examples/reel-facebook.mp4" controls width="420"></video>

[`assets/docs/examples/reel-facebook.mp4`](assets/docs/examples/reel-facebook.mp4)

### Trailer (Facebook Reel)
<video src="assets/docs/examples/trailer-facebook-reel.mp4" controls width="420"></video>

[`assets/docs/examples/trailer-facebook-reel.mp4`](assets/docs/examples/trailer-facebook-reel.mp4)

### Otros formatos de ejemplo (short/reel/collage)
<video src="assets/docs/examples/ejemplo-youtube-short.mp4" controls width="420"></video>

[`assets/docs/examples/ejemplo-youtube-short.mp4`](assets/docs/examples/ejemplo-youtube-short.mp4)

<video src="assets/docs/examples/ejemplo-reel-facebook.mp4" controls width="420"></video>

[`assets/docs/examples/ejemplo-reel-facebook.mp4`](assets/docs/examples/ejemplo-reel-facebook.mp4)

<video src="assets/docs/examples/ejemplo-collage.mp4" controls width="720"></video>

[`assets/docs/examples/ejemplo-collage.mp4`](assets/docs/examples/ejemplo-collage.mp4)

### Cómic (capítulo/viñetas)
![Ejemplo de cómic generado](assets/docs/examples/ejemplo-comic.png)

[`assets/docs/examples/ejemplo-comic.png`](assets/docs/examples/ejemplo-comic.png)

## Operación

```bash
docker compose logs -f factory
docker restart pulso-factory
docker compose down && docker compose up -d
```
- Reinicia tras cambios en procesos de larga vida o configuración de entorno.
- Artefactos runtime: `state/`, `projects/`, cachés (locales, no fuente).

## Seguridad y costos

- No publicar `.env` ni secretos. Rotar credenciales si se exponen.
- Controlar publicación con `FACTORY_PUBLISH`/`AUTO_PUBLISH`.
- Limitar gasto: `ALLOW_PAID_LLM`, `ALLOW_REMOTE_LLM`, `GEMINI_PRESUPUESTO_USD_MES`, `CF_MAX_IMAGENES_DIA`.

## Solución de problemas

| Problema | Acción |
|---|---|
| Factory no healthy / no inicia | `docker compose logs factory`; validar volúmenes/rutas/`user`/`HOME`, puertos `8610/8611` |
| Sin acceso al dashboard/API | Verificar `docker compose ps`, healthcheck y proxy nginx |
| Ollama inaccesible | Ollama activo en host, `host.docker.internal` y `OLLAMA_BASE_URL` |
| No publica | Revisar `ZERNIO_*`, IDs de canales y flags de publicación |
| 429 / cuotas imágenes | Ajustar proveedores/límites y reciclado (`KF_RECICLADO_CADA`) |

## Estructura del repositorio

```text
docker/ docker-compose.yml    # despliegue
pipeline/ factory/            # motor y orquestación
assets/docs/                  # capturas, tutoriales y ejemplos (video/cómic)
docs/                         # documentación
tests/                        # pruebas
.env.example                  # plantilla de configuración
```

## Documentación

- [`TUTORIAL_INSTALACION.md`](TUTORIAL_INSTALACION.md) — instalación, configuración y deploy
- [`docs/INSTALACION.md`](docs/INSTALACION.md) — guía de instalación
- [`MEJORAS-PRO-2026-11-10.md`](MEJORAS-PRO-2026-11-10.md) — notas técnicas
- [`DEPENDENCIAS.md`](DEPENDENCIAS.md) · [`FABRICA-DE-COMICS.md`](FABRICA-DE-COMICS.md) · [`PROTOCOLOS-VIRALES-FACTORY.md`](PROTOCOLOS-VIRALES-FACTORY.md)

## Licencia

MIT.
