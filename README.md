# Stickman Factory V2 — Fábrica Autónoma de Video y Cómics

Pipeline automatizado para producir **videos** (máster 9:16, derivados YouTube/Facebook) y **cómics** de forma continua en local. Incluye backend de orquestación, dashboard web (Mission Control) y despliegue con Docker Compose.

**Repositorio:** https://github.com/NickDev24/fabrica-stickman-V2

[![Docker](https://img.shields.io/badge/Docker-Compose_2496ED?logo=docker&logoColor=white)](docker-compose.yml)
[![Python](https://img.shields.io/badge/Backend-Python_3.13-3776AB?logo=python&logoColor=white)](docker/factory)
[![Dashboard](https://img.shields.io/badge/Dashboard-nginx%20%2B%20vanilla%20JS-10b981)](#dashboard-mission-control)
[![License: MIT](https://img.shields.io/badge/License-MIT-f59e0b.svg)](#licencia)

---

## Tabla de contenidos

- [Descripción general](#descripción-general)
- [Arquitectura y stack](#arquitectura-y-stack)
- [Requisitos](#requisitos)
- [Instalación](#instalación)
- [Configuración (.env)](#configuración-env)
- [Deploy (producción local)](#deploy-producción-local)
- [Verificación](#verificación)
- [Tutoriales en video (instalación, configuración y deploy)](#tutoriales-en-video-instalación-configuración-y-deploy)
- [Dashboard (Mission Control)](#dashboard-mission-control)
- [Ejemplos generados (video y cómic)](#ejemplos-generados-video-y-cómic)
- [Operación y mantenimiento](#operación-y-mantenimiento)
- [Seguridad y buenas prácticas](#seguridad-y-buenas-prácticas)
- [Solución de problemas](#solución-de-problemas)
- [Estructura del repositorio](#estructura-del-repositorio)
- [Documentación](#documentación)
- [Licencia](#licencia)

---

## Descripción general

| Módulo | Descripción |
|---|---|
| **Fábrica de Video** | Pipeline de producción: ideación/guion → keyframes/actuación → TTS y montaje (ffmpeg) → máster 9:16 y derivados (YouTube Short / Facebook Reel), con control de publicación. |
| **Fábrica de Cómics** | Generación y composición de capítulos/viñetas, QC y salida lista para publicación según configuración. |
| **Mission Control (Dashboard)** | Interfaz web para monitorear estado, producción, galería, métricas y conectores en tiempo real (API + WebSocket). |
| **Orquestación 24/7** | `factoryd` ejecuta el ciclo de producción en loop con controles de publicación y reciclado de recursos. |

> Base técnica documentada en el repo: `docker-compose.yml`, `.env.example`, `MEJORAS-PRO-2026-11-10.md`.

---

## Arquitectura y stack

- **Backend (`factory`)**: Python 3.13 + ffmpeg + tesseract. Ejecuta `factoryd` (REST `:8610`, WebSocket `/ws`) y el pipeline (`pipeline/`, `factory/`). Loop 24/7 con reciclado de imágenes (`KF_RECICLADO_CADA`).
- **Dashboard (`dashboard`)**: nginx sirviendo UI estática en `:8611` con proxy a la API del backend.
- **Contenedores**: definidos en [`docker-compose.yml`](docker-compose.yml) (`pulso-factory`, `pulso-dashboard`).
- **Datos/artefactos (runtime, locales)**: `state/`, `projects/`, cachés e imagenoteca (no versionados como código fuente).

```text
[Dashboard :8611 (nginx)]  <—HTTP/WS—>  [factoryd/API :8610 (Python)]
                                              │
                                              ├─ pipeline/ + factory/ (producción video/cómics)
                                              ├─ ffmpeg / TTS / generación de imágenes
                                              └─ state/, projects/, assets/ (runtime local)
```

---

## Requisitos

- **Git** 2.x+
- **Docker Engine** 24+ y **Docker Compose v2** (`docker compose`)
- **Recursos**: ~8–15 GB de disco libre (imágenes, caché, renders) y **8 GB+ RAM** recomendado
- **Puertos libres**: `8610` (API) y `8611` (dashboard)
- **Opcional**: Ollama en el host (LLM local), claves de proveedores LLM/imágenes y credenciales de publicación Zernio

> **Importante (volúmenes/rutas):** `docker-compose.yml` monta el repo en `/app` y rutas del host `/home/facu/piper-env` y `/home/facu/.local/bin`, ejecuta con `user: "1000:1000"` y `HOME=/home/facu` para resolver Piper/edge-tts según `pipeline/config.py`. **Ajusta `user`, `HOME` y estos volúmenes** a tu usuario/rutas si tu entorno difiere antes de desplegar.

---

## Instalación

```bash
# 1. Clonar el repositorio
git clone https://github.com/NickDev24/fabrica-stickman-V2.git
cd fabrica-stickman-V2

# 2. Crear archivo de entorno
cp .env.example .env

# 3. Editar configuración (secretos, cuentas/canales, proveedores)
# nano .env   # o tu editor preferido

# 4. Construir y levantar servicios
docker compose up -d --build
```

Comandos de verificación rápida:

```bash
git --version
docker --version
docker compose version
docker compose ps
curl http://localhost:8610/api/health
```

Guía detallada paso a paso: [`TUTORIAL_INSTALACION.md`](TUTORIAL_INSTALACION.md) · [`docs/INSTALACION.md`](docs/INSTALACION.md)

---

## Configuración (.env)

Crea `.env` desde [`.env.example`](.env.example) y completa los valores necesarios. **Nunca subas `.env` al repositorio.**

| Variable | Descripción / uso |
|---|---|
| `MISTRAL_API_KEY`, `QWEN_API_KEY` | Claves de proveedores LLM (opcionales) |
| `CLOUDFLARED_ACCOUNTS_ID`, `CLOUDFLARED_WORKER_AI` | Cloudflare (Workers AI / imágenes, si aplica) |
| `BADROCK_API_KEY`, `AIONLABS_API_KEY` | Proveedores adicionales (opcionales) |
| `TELEGRAM_TOKEN_BOT`, `TELEGRAM_CHAT_ID` | Integración/notificaciones Telegram (opcional) |
| `ZERNIO_API_KEY`, `ZERNIO_ACCOUNT_ID`, `ZERNIO_FACEBOOK_ID`, `ZERNIO_YOUTUBE_ID` | Publicación vía Zernio: API y **IDs de cuentas/canales destino** |
| `AUTO_PUBLISH`, `FACTORY_PUBLISH` | Control de publicación automática (`docker-compose` usa `FACTORY_PUBLISH`, default `1`) |
| `KF_RECICLADO_CADA` | Frecuencia de reciclado de imágenes (default `2`) |
| `COMICS_ENABLED`, `COMICS_CAPTIONS_LLM` | Opciones del módulo de cómics |
| `KAGGLE_API_KEY`, `HUGGINFACE_TOKEN` | Tokens de plataformas (opcionales) |
| `GEMINI_API_KEY`, `GOOGLE_GEMINI_API_KEY`, `NAME_PROJECT`, `NUMBER_PROJECT`, `ID_PROJECT` | Configuración/proyectos Google/Gemini (opcional) |
| `ALLOW_PAID_LLM`, `GEMINI_PRESUPUESTO_USD_MES`, `ALLOW_REMOTE_LLM` | Control de costos y uso de LLM remoto/pago |
| `CF_MAX_IMAGENES_DIA`, `POLLINATIONS_API_KEY` | Límites y proveedores de imagen |

**Notas de configuración:**
- **Publicación:** configura `ZERNIO_*` con tus credenciales y los IDs reales de tus canales/cuentas (`ZERNIO_YOUTUBE_ID`, `ZERNIO_FACEBOOK_ID`). Para revisar antes de publicar, desactiva la publicación automática (`FACTORY_PUBLISH`/`AUTO_PUBLISH`) en `.env` y reinicia.
- **LLM local (Ollama):** el contenedor usa `OLLAMA_BASE_URL=http://host.docker.internal:11434/v1` (definido en compose) para alcanzar Ollama en el host.
- **Costos:** ajusta `ALLOW_PAID_LLM`, `ALLOW_REMOTE_LLM`, presupuestos y límites según tu política.

---

## Deploy (producción local)

Despliegue con Docker Compose (servicios `factory` y `dashboard`):

```bash
# Build y arranque en segundo plano
docker compose up -d --build

# Estado de servicios
docker compose ps

# Logs del backend
docker compose logs -f factory

# Reinicio (aplica cambios de configuración/proceso)
docker restart pulso-factory

# Parada / arranque
docker compose down
docker compose up -d
```

- **Endpoints:** Dashboard `http://localhost:8611` · API `http://localhost:8610` · Health `http://localhost:8610/api/health`
- **Healthcheck:** `factory` expone chequeo HTTP a `/api/health` (compose). Espera estado `healthy` en `docker compose ps`.
- **Persistencia/runtime:** el código se monta en `/app`; salidas y estado se generan en el workspace (`state/`, `projects/`, cachés). Asegura espacio en disco y permisos coherentes con `user`/volúmenes configurados.

---

## Verificación

```bash
docker compose ps
curl http://localhost:8610/api/health
# esperado: {"ok": true}
```

Accede al panel: **http://localhost:8611**

---

## Tutoriales en video (instalación, configuración y deploy)

Recursos en video incluidos en el repositorio (reproducción en navegadores compatibles con `<video>`; también disponibles como descarga directa):

### Instalación y puesta en marcha
<video src="assets/docs/tutorial-install.mp4" controls width="960"></video>

[Descargar / abrir: `assets/docs/tutorial-install.mp4`](assets/docs/tutorial-install.mp4)

### Configuración y recorrido de deploy (dashboard/operación)
<video src="assets/docs/tutorial-dashboard.mp4" controls width="960"></video>

[Descargar / abrir: `assets/docs/tutorial-dashboard.mp4`](assets/docs/tutorial-dashboard.mp4)

> La guía escrita detallada (instalación → `.env`/secretos/canales → deploy y verificación) está en [`TUTORIAL_INSTALACION.md`](TUTORIAL_INSTALACION.md).

---

## Dashboard (Mission Control)

UI web en `http://localhost:8611` (proxy a `factoryd:8610`). Vistas incluidas:

| Vista | Descripción |
|---|---|
| **Inicio** | Estado general y actividad reciente |
| **Fábrica de Video** | Pipeline/estaciones, galería y recursos de video |
| **Fábrica de Cómics** | Producción y galería de cómics/viñetas |
| **Métricas** | Publicación e interacción (según conectores/configuración) |
| **Conectores** | Integraciones y estado de conectores |
| **Oficina 3D** | Visualización 3D de agentes/estaciones |

| Inicio | Fábrica de Video |
|---|---|
| ![Inicio](assets/docs/dashboard-inicio.png) | ![Fábrica de Video](assets/docs/dashboard-fabrica-video.png) |

| Fábrica de Cómics | Métricas |
|---|---|
| ![Fábrica de Cómics](assets/docs/dashboard-fabrica-comics.png) | ![Métricas](assets/docs/dashboard-metricas.png) |

| Conectores | Oficina 3D |
|---|---|
| ![Conectores](assets/docs/dashboard-conectores.png) | ![Oficina 3D](assets/docs/dashboard-oficina3d.png) |

---

## Ejemplos generados (video y cómic)

### Videos

**Facebook Reel**
<video src="assets/docs/examples/ejemplo-reel-facebook.mp4" controls width="420"></video>

[Archivo: `assets/docs/examples/ejemplo-reel-facebook.mp4`](assets/docs/examples/ejemplo-reel-facebook.mp4)

**YouTube Short**
<video src="assets/docs/examples/ejemplo-youtube-short.mp4" controls width="420"></video>

[Archivo: `assets/docs/examples/ejemplo-youtube-short.mp4`](assets/docs/examples/ejemplo-youtube-short.mp4)

**Collage**
<video src="assets/docs/examples/ejemplo-collage.mp4" controls width="720"></video>

[Archivo: `assets/docs/examples/ejemplo-collage.mp4`](assets/docs/examples/ejemplo-collage.mp4)

### Cómic

![Ejemplo de cómic generado](assets/docs/examples/ejemplo-comic.png)

[Archivo: `assets/docs/examples/ejemplo-comic.png`](assets/docs/examples/ejemplo-comic.png)

---

## Operación y mantenimiento

```bash
# Observabilidad
docker compose logs -f factory
docker compose logs -f dashboard

# Reinicios controlados
docker restart pulso-factory
docker restart pulso-dashboard

# Actualización del código (repo montado en /app) y reinicio de proceso
git pull
docker restart pulso-factory

# Limpieza (con precaución: elimina contenedores/red del compose)
docker compose down
```

- Tras cambios en procesos de larga vida (p.ej. `factoryd`), reinicia el contenedor correspondiente.
- Monitorea espacio en disco (renders, cachés, imagenoteca) y cuotas/rate-limits de proveedores externos.

---

## Seguridad y buenas prácticas

- **Secretos:** `.env` contiene credenciales; no lo publiques ni lo versionas. Rota claves si se exponen.
- **Publicación automática:** `FACTORY_PUBLISH`/`AUTO_PUBLISH` controlan la salida a canales; valida configuración y usa modo revisión (`0`) cuando corresponda.
- **Costos:** usa `ALLOW_PAID_LLM`, `ALLOW_REMOTE_LLM`, `GEMINI_PRESUPUESTO_USD_MES`, `CF_MAX_IMAGENES_DIA` para acotar gasto.
- **Principio de mínimo privilegio:** ajusta `user`/permisos y alcance de tokens/API a lo estrictamente necesario.

---

## Solución de problemas

| Síntoma | Causa probable | Acción |
|---|---|---|
| `factory` no arranca / unhealthy | Volúmenes/rutas inexistentes, permisos, build fallido | `docker compose logs factory`; verifica montajes (`/home/facu/...`), `user`/`HOME` y puertos libres |
| `/api/health` no responde | Servicio iniciando o puerto ocupado | Esperar healthcheck, revisar `docker compose ps` y `8610` |
| Dashboard sin datos | Backend caído o proxy | Confirmar `factory` healthy y logs de `dashboard` |
| Ollama no conecta | Host no accesible desde contenedor | Verificar Ollama en host y `host.docker.internal` / `OLLAMA_BASE_URL` |
| Fallos de publicación | Credenciales/IDs Zernio o flags | Revisar `ZERNIO_*`, IDs de canales/cuentas y `FACTORY_PUBLISH`/`AUTO_PUBLISH` |
| 429 / rate-limit en imágenes | Cuotas de proveedor | Ajustar límites/proveedores, reciclado y claves en `.env` |

---

## Estructura del repositorio

```text
.
├─ docker/                 # Dockerfiles y runtime (factory, dashboard)
├─ docker-compose.yml      # Orquestación local (factory + dashboard)
├─ pipeline/               # Stages y lógica de pipeline
├─ factory/                # Componentes de producción/orquestación
├─ assets/                 # Assets y documentación visual
│  └─ docs/                # Capturas, tutoriales en video y ejemplos
├─ docs/                   # Documentación (p.ej. instalación)
├─ tests/                  # Pruebas
├─ .env.example            # Plantilla de configuración
├─ README.md               # Este documento
└─ TUTORIAL_INSTALACION.md # Guía detallada de instalación/config/deploy
```

---

## Documentación

- [`TUTORIAL_INSTALACION.md`](TUTORIAL_INSTALACION.md) — instalación, configuración y deploy paso a paso
- [`docs/INSTALACION.md`](docs/INSTALACION.md) — guía de instalación
- [`MEJORAS-PRO-2026-11-10.md`](MEJORAS-PRO-2026-11-10.md) — mejoras y notas técnicas
- [`PROTOCOLOS-VIRALES-FACTORY.md`](PROTOCOLOS-VIRALES-FACTORY.md), [`DEPENDENCIAS.md`](DEPENDENCIAS.md), [`FABRICA-DE-COMICS.md`](FABRICA-DE-COMICS.md)

---

## Licencia

MIT.
