# 🎬 PULSO Curioso — Fábrica Autónoma de Contenido

> Genera **videos estilo documental** (YouTube + Facebook Reels) y **cómics** de forma
> autónoma, 24/7, con un límite diario gratuito respetado. Un solo `docker compose up`
> y la fábrica empieza a producir.

[![Docker](https://img.shields.io/badge/docker-compose-2496ED?logo=docker&logoColor=white)](#instalación)
[![Python](https://img.shields.io/badge/python-3.13-3776AB?logo=python&logoColor=white)](#)
[![Frontend](https://img.shields.io/badge/dashboard-nginx%20%2B%20vanilla%20JS-10b981)](#frontend)
[![Licencia](https://img.shields.io/badge/licencia-MIT-f59e0b)](#licencia)

![Dashboard — Inicio](assets/docs/dashboard-inicio.png)

---

## ✨ Qué hace

- **Fábrica de Video:** descubre temas, escribe guion, genera keyframes (IA), narra con TTS,
  monta el video máster (9:16) con cama musical sintetizada (sin copyright) y deriva
  YouTube Short + Facebook Reel, publica vía Zernio.
- **Fábrica de Cómics:** convierte guiones en capítulos con viñetas, portadas y QC duro
  (paneles negros, captions duplicados, ritmo, cold open). Personajes con cara expresiva
  en primeros planos.
- **Panel web (Mission Control):** cinta de producción en vivo, galería, métricas YT/FB
  (vía Zernio), conectores MCP, Oficina 3D (carrusel 3D de agentes).
- **Reciclado inteligente de imágenes:** consume caché antes de pedir nuevas (≈ mitad de costo).
- **Publicación autónoma diaria** con gates de QC, título y flag sintético como cinturón de seguridad.
- **Validación viral experta:** antes de publicar por Zernio se corrigen, con protocolos propios
  (`factory/validacion_viral.py`), los controles de creatividad/retención — estimulación visual,
  emoción universal, recompensa narrativa en el guion; hook + giro + Ki-Sho-Ten-Ketsu + ≥15
  viñetas + grillas 3 bandas en el cómic.
- **Identidad visual viral:** emoción universal + miniatura (packaging) + hook de 3 segundos
  en cada idea; ritmo Ki-Sho-Ten-Ketsu en cómics.

## 🚀 Instalación (primera vez)

### Requisitos

- Docker + Docker Compose
- Git
- (Opcional) claves de proveedores LLM y `ZERNIO_API_KEY` para publicación

### Pasos

```bash
# 1. Clonar
git clone https://github.com/NickDev24/fabrica-stickman.git
cd fabrica-stickman

# 2. Configurar entorno
cp .env.example .env
# edita .env: ZERNIO_API_KEY, ZERNIO_YOUTUBE_ID, ZERNIO_FACEBOOK_ID, claves LLM...

# 3. Levantar todo
docker compose up -d

# 4. Abrir el panel
# http://localhost:8611
```

📺 **Video tutorial — instalación completa:**

<video src="assets/docs/tutorial-install.mp4" controls width="720"></video>

> Archivo: [`assets/docs/tutorial-install.mp4`](assets/docs/tutorial-install.mp4)

---

## ⚙️ Configuración

Variables principales en `.env`:

| Variable | Descripción |
|---|---|
| `ZERNIO_API_KEY` | API key de Zernio (publicación YT/FB) |
| `ZERNIO_YOUTUBE_ID` / `ZERNIO_FACEBOOK_ID` | IDs de cuenta |
| `FACTORY_PUBLISH` | `1` publica de forma autónoma (default en compose) |
| `KF_RECICLADO_CADA` | cada cuántas escenas se recicla imagen (`2` = mitad) |
| `OLLAMA_BASE_URL` | endpoint de Ollama (LLM local, gratis) |
| `OPENAI_API_KEY` | API key OpenAI (GPT Image) — nuevo salvapantallas de la cascada de imágenes |
| `PORT` (factory) | `8610` (REST + WebSocket) |

El panel permite autorizar/desautorizar publicación en caliente
(`POST /api/control` con `publicar_on` / `publicar_off`).

---

## 🖥️ Frontend (Mission Control)

Servido por nginx en `http://localhost:8611`, proxy a `factoryd:8610`.

📺 **Video tutorial — recorrido del panel:**

<video src="assets/docs/tutorial-dashboard.mp4" controls width="720"></video>

Vistas del riel lateral:

| Vista | Contenido |
|---|---|
| Inicio | Banner de fábrica, feed de últimos episodios y capítulos |
| Fábrica de Video | Cinta de producción (10 estaciones), galería, keyframes, métricas |
| Fábrica de Cómics | Prensa de tinta, galería de capítulos, viñetas |
| Métricas | Publicación YT/FB (vía Zernio), interacción por día, emoción, seguidores |
| Conectores MCP | Zernio, YouTube, Facebook, Telegram, LLM + registrar nuevos |
| Oficina 3D | Central de operaciones: carrusel 3D de estaciones por agente (giro auto, drag, foco) |

Screenshots:

| Inicio | Fábrica de Video |
|---|---|
| ![Inicio](assets/docs/dashboard-inicio.png) | ![Video](assets/docs/dashboard-fabrica-video.png) |
| **Cómics** | **Oficina 3D** |
| ![Cómics](assets/docs/dashboard-fabrica-comics.png) | ![Oficina 3D](assets/docs/dashboard-oficina3d.png) |
| **Métricas** | **Conectores** |
| ![Métricas](assets/docs/dashboard-metricas.png) | ![Conectores](assets/docs/dashboard-conectores.png) |

---

## 🎞️ Ejemplos de lo que genera la fábrica

Videos y cómics producidos de forma autónoma (límite diario respetado, costo mínimo).

- 📹 **Reel Facebook:** [`assets/docs/examples/ejemplo-reel-facebook.mp4`](assets/docs/examples/ejemplo-reel-facebook.mp4)
- 📹 **YouTube Short:** [`assets/docs/examples/ejemplo-youtube-short.mp4`](assets/docs/examples/ejemplo-youtube-short.mp4)
- 📹 **Collage (portada):** [`assets/docs/examples/ejemplo-collage.mp4`](assets/docs/examples/ejemplo-collage.mp4)
- 🖼️ **Cómic (capítulo vertical):** [`assets/docs/examples/ejemplo-comic.png`](assets/docs/examples/ejemplo-comic.png)

![Ejemplo de cómic generado](assets/docs/examples/ejemplo-comic.png)

---

## 🏢 Oficina 3D (vista en vivo)

El panel incluye una **Oficina 3D interactiva** (`http://localhost:8611/#oficina3d`):
escena Three.js con personajes GLB, mobiliario, iluminación y sombras. Cada agente
del pipeline aparece como personaje cuyo color indica estado (verde=ok, azul=trabajando,
rojo=error, ámbar=sin turno). Se actualiza en tiempo real vía `/api/oficina` + WebSocket.

![Oficina 3D](assets/docs/dashboard-oficina3d.png)

## 🏗️ Arquitectura

```
fabrica-stickman/
├── docker/                 # Dockerfiles (factory + dashboard)
├── docker-compose.yml      # factory :8610 + dashboard :8611
├── pipeline/               # motor de producción (stages, config, gates)
├── factory/                # acting, render, motor, skills
├── state/                  # métricas, conectores, agentes, logs
├── projects/               # salidas por proyecto (videos, cómics, artefactos)
├── assets/                 # assets estáticos + docs (screenshots/videos)
└── tests/                  # suite de regresión
```

- **Backend:** Python 3.13 + `factoryd` (REST `:8610` + WebSocket `/ws`).
- **Frontend:** nginx + HTML/CSS/JS vanilla (sin build step).
- **Render:** ffmpeg + TTS (Piper/edge-tts) + generación de imágenes (reciclado).

## 🧪 Verificación

```bash
# salud del backend
curl http://localhost:8610/api/health

# estado de la fábrica
curl http://localhost:8611/api/estado
```

Suite de tests:

```bash
.venv/bin/python -m pytest -q
```

## 📄 Licencia

MIT — úsalo, fórkalo, mejóralo.

---

> Construido para ser un repositorio completo, profesional y listo para viralizar:
> instalación en un comando, panel visual, métricas reales y contenido autónomo diario.
