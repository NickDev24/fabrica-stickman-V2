# Tutorial de instalación, configuración y deploy — Stickman Factory V2

Guía práctica para desplegar **Stickman Factory V2** en local con Docker Compose, configurar secretos/cuentas y poner la fábrica en funcionamiento.

**Repositorio:** https://github.com/NickDev24/fabrica-stickman-V2

---

## Videos tutoriales (incluidos en el repositorio)

### Instalación y puesta en marcha
<video src="assets/docs/tutorial-install.mp4" controls width="960"></video>

[Descargar / abrir: `assets/docs/tutorial-install.mp4`](assets/docs/tutorial-install.mp4)

### Configuración y recorrido (dashboard / operación)
<video src="assets/docs/tutorial-dashboard.mp4" controls width="960"></video>

[Descargar / abrir: `assets/docs/tutorial-dashboard.mp4`](assets/docs/tutorial-dashboard.mp4)

---

## 1. Requisitos previos

- **Git** 2.x+
- **Docker Engine** 24+ y **Docker Compose v2** (`docker compose`)
- **Disco:** ~8–15 GB libres (imágenes, caché, renders). **RAM:** 8 GB+ recomendado
- **Puertos libres:** `8610` (API/backend) y `8611` (dashboard)
- (Opcional) **Ollama** en el host para LLM local
- (Opcional) Claves de proveedores LLM/imágenes y credenciales **Zernio** para publicación

Verificación:
```bash
git --version
docker --version
docker compose version
```

### Nota sobre `docker-compose.yml` (rutas y entorno)

La configuración incluida (`docker-compose.yml`) asume un entorno de referencia:
- `user: "1000:1000"`, `HOME=/home/facu`
- Monta el repositorio en `/app` y rutas del host: `/home/facu/piper-env`, `/home/facu/.local/bin`
- `OLLAMA_BASE_URL=http://host.docker.internal:11434/v1` (Ollama en el host)

**Si tu usuario o rutas difieren, ajusta `user`, `HOME` y los volúmenes** en `docker-compose.yml` antes del deploy para que TTS/herramientas y permisos funcionen correctamente.

---

## 2. Instalación (descarga)

```bash
git clone https://github.com/NickDev24/fabrica-stickman-V2.git
cd fabrica-stickman-V2
```

---

## 3. Configuración (`.env`)

Crea el archivo de entorno y edítalo con tus valores:

```bash
cp .env.example .env
# edita .env (nano, vim, code, etc.)
```

Variables definidas en `.env.example`:

| Variable | Propósito |
|---|---|
| `MISTRAL_API_KEY`, `QWEN_API_KEY` | Proveedores LLM |
| `CLOUDFLARED_ACCOUNTS_ID`, `CLOUDFLARED_WORKER_AI` | Cloudflare / Workers AI (imágenes, si aplica) |
| `BADROCK_API_KEY`, `AIONLABS_API_KEY` | Proveedores adicionales |
| `TELEGRAM_TOKEN_BOT`, `TELEGRAM_CHAT_ID` | Telegram (integración/notificaciones) |
| `ZERNIO_API_KEY`, `ZERNIO_ACCOUNT_ID`, `ZERNIO_FACEBOOK_ID`, `ZERNIO_YOUTUBE_ID` | Publicación vía Zernio: API y **IDs de cuentas/canales** |
| `AUTO_PUBLISH`, `FACTORY_PUBLISH` | Publicación automática (`compose` usa `FACTORY_PUBLISH`, default `1`) |
| `KF_RECICLADO_CADA` | Frecuencia de reciclado de imágenes (default `2`) |
| `COMICS_ENABLED`, `COMICS_CAPTIONS_LLM` | Módulo cómics |
| `KAGGLE_API_KEY`, `HUGGINFACE_TOKEN` | Tokens de plataformas |
| `GEMINI_API_KEY`, `GOOGLE_GEMINI_API_KEY`, `NAME_PROJECT`, `NUMBER_PROJECT`, `ID_PROJECT` | Google/Gemini y proyecto |
| `ALLOW_PAID_LLM`, `GEMINI_PRESUPUESTO_USD_MES`, `ALLOW_REMOTE_LLM` | Control de costos / LLM pago o remoto |
| `CF_MAX_IMAGENES_DIA`, `POLLINATIONS_API_KEY` | Límites y proveedor de imagen |

**Recomendaciones:**
- **No** versionar `.env` ni compartir secretos.
- **Canales/cuentas:** configura `ZERNIO_API_KEY`, `ZERNIO_ACCOUNT_ID` y los IDs de destino (`ZERNIO_YOUTUBE_ID`, `ZERNIO_FACEBOOK_ID`) con tus cuentas reales.
- **Modo revisión:** para no publicar automáticamente, ajusta `FACTORY_PUBLISH`/`AUTO_PUBLISH` (p.ej. `0`) y reinicia tras el cambio.
- **Sin claves:** el arranque local es posible según componentes/proveedores disponibles; la publicación requiere credenciales válidas.

---

## 4. Deploy (Docker Compose)

Construir y levantar servicios:

```bash
docker compose up -d --build
```

Servicios levantados:
- **`factory`** (`pulso-factory`, puerto `8610`): backend `factoryd` (REST + WebSocket `/ws`), healthcheck en `/api/health`.
- **`dashboard`** (`pulso-dashboard`, puerto `8611`): Mission Control (nginx) con proxy a la API.

Comandos útiles:
```bash
docker compose ps
docker compose logs -f factory
docker restart pulso-factory
docker compose down
```

---

## 5. Verificación

```bash
curl http://localhost:8610/api/health
# esperado: {"ok": true}
```

- **Dashboard:** http://localhost:8611
- **API:** http://localhost:8610

Estado (`docker compose ps`) debe mostrar `factory` **healthy**.

---

## 6. Recorrido del panel (capturas reales)

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

## 7. Solución de problemas

| Problema | Revisión |
|---|---|
| Contenedor no arranca/healthy | `docker compose logs factory`, rutas/volúmenes y `user`/`HOME` en compose, puertos `8610/8611` |
| No conecta a Ollama | Ollama activo en host y acceso por `host.docker.internal` |
| No publica | `ZERNIO_*`, IDs de canales/cuentas y `FACTORY_PUBLISH`/`AUTO_PUBLISH` |
| Rate-limit de imágenes/LLM | Cuotas/proveedores, `CF_MAX_IMAGENES_DIA`, reciclado (`KF_RECICLADO_CADA`) |

Para arquitectura, ejemplos y operación avanzada consulta [`README.md`](README.md).
