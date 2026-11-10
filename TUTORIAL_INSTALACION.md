# Guía de instalación — PULSO Curioso (Fábrica Stickman)

Guía paso a paso para **descargar, instalar, configurar y verificar** la fábrica en local con Docker. Diseñada para que puedas levantar el proyecto y ver el panel en pocos minutos.

> Resumen visual (simulación del flujo completo):

![Flujo de instalación paso a paso](assets/docs/tutorial/instalacion-paso-a-paso.gif)

---

## 1. Requisitos previos

| Requisito | Versión recomendada | Para qué se usa |
|---|---|---|
| **Git** | 2.x+ | Clonar el repositorio |
| **Docker Engine** | 24+ | Ejecutar los servicios en contenedores |
| **Docker Compose** | v2 (`docker compose`) | Orquestar `factory` + `dashboard` |
| **Espacio en disco** | ~8–15 GB libres | Imágenes Docker, caché de imágenes, renders |
| **RAM** | 8 GB+ recomendado | Render ffmpeg + procesos de generación |

Comprobación rápida:

```bash
git --version
docker --version
docker compose version
```

> No necesitas instalar Python/ffmpeg en el host para el flujo Docker: la imagen `pulso-factory` ya incluye la pila de ejecución (Python 3.13, ffmpeg, tesseract, etc.).

---

## 2. Descargar el repositorio

```bash
git clone https://github.com/NickDev24/fabrica-stickman-V2.git
cd fabrica-stickman-V2
```

![Paso 1 — Clonar repositorio](assets/docs/tutorial/01-clonar-repo.png)

---

## 3. Crear y configurar el entorno (`.env`)

Crea tu archivo de configuración a partir del ejemplo:

```bash
cp .env.example .env
```

![Paso 2 — Crear .env](assets/docs/tutorial/02-crear-env.png)

Edita `.env` con tu editor (`nano .env`, `code .env`, etc.). Campos principales:

![Paso 3 — Configurar .env](assets/docs/tutorial/03-configurar-env.png)

| Variable | Obligatoria | Descripción |
|---|---:|---|
| `ZERNIO_API_KEY` | Para publicar | API key de Zernio (publicación YouTube/Facebook) |
| `ZERNIO_YOUTUBE_ID` | Para publicar | ID de cuenta/canal YouTube en Zernio |
| `ZERNIO_FACEBOOK_ID` | Para publicar | ID de cuenta/página Facebook en Zernio |
| `FACTORY_PUBLISH` | No | `1` publica automáticamente (default en compose), `0` solo genera/revisa |
| `OLLAMA_BASE_URL` | No | Endpoint Ollama (LLM local). En Docker se usa `host.docker.internal:11434` |
| `GEMINI_API_KEY` / `OPENAI_API_KEY` / `POLLINATIONS_API_KEY` | No | Proveedores opcionales; la cascada prioriza rutas $0/gratis |
| `KF_RECICLADO_CADA` | No | Frecuencia de reciclado de imágenes para reducir costo (ej. `2`) |
| `ALLOW_PAID_LLM` | No | Mantener en `0` para modo $0-first |

**Notas de seguridad:** nunca subas `.env` al repositorio. Puedes levantar la fábrica sin claves para generar contenido localmente; la publicación requiere credenciales válidas.

---

## 4. Instalar y levantar (Docker Compose)

Construye y levanta los servicios en segundo plano:

```bash
docker compose up -d --build
```

![Paso 4 — docker compose up](assets/docs/tutorial/04-docker-compose-up.png)

Servicios que se inician:

| Servicio | Contenedor | Puerto | Rol |
|---|---|---|---|
| `factory` | `pulso-factory` | `8610` | Backend `factoryd` (REST + WebSocket), pipeline 24/7 |
| `dashboard` | `pulso-dashboard` | `8611` | Mission Control (nginx + UI) con proxy a `factory` |

> Primera ejecución: la build puede tardar varios minutos mientras descarga la base e instala dependencias.

---

## 5. Verificar la instalación

Comprueba contenedores y endpoints:

```bash
docker compose ps
curl http://localhost:8610/api/health
curl -s http://localhost:8611/api/estado | head
```

![Paso 5 — Verificación](assets/docs/tutorial/05-verificar.png)

Resultado esperado:
- `pulso-factory` en estado **Up (healthy)**.
- `GET /api/health` responde `{"ok": true}`.
- Panel disponible en **http://localhost:8611**.

---

## 6. Recorrido del panel (Mission Control)

Abre [http://localhost:8611](http://localhost:8611):

![Dashboard — Inicio](assets/docs/dashboard-inicio.png)

| Vista | Qué muestra |
|---|---|
| **Inicio** | Estado general, feed de episodios/capítulos recientes |
| **Fábrica de Video** | Cinta de producción, galería, keyframes, métricas |
| **Fábrica de Cómics** | Prensa de tinta, capítulos y viñetas |
| **Métricas** | Publicación e interacción YT/FB (vía Zernio) |
| **Conectores MCP** | Integraciones y conectores |
| **Oficina 3D** | Visualización 3D de estaciones/agentes |

| Fábrica de Video | Fábrica de Cómics |
|---|---|
| ![Video](assets/docs/dashboard-fabrica-video.png) | ![Cómics](assets/docs/dashboard-fabrica-comics.png) |

| Métricas | Oficina 3D |
|---|---|
| ![Métricas](assets/docs/dashboard-metricas.png) | ![Oficina 3D](assets/docs/dashboard-oficina3d.png) |

📺 Recorrido del panel: [`assets/docs/tutorial-dashboard.mp4`](assets/docs/tutorial-dashboard.mp4)

---

## 7. Operación diaria (comandos útiles)

```bash
# Ver logs en vivo
docker compose logs -f factory

# Reiniciar backend (aplica cambios en procesos como factoryd)
docker restart pulso-factory

# Detener / volver a levantar
docker compose down
docker compose up -d
```

Modos recomendados:
- **Solo generación/revisión:** `FACTORY_PUBLISH=0` en `.env` y reinicia.
- **Autónomo con publicación:** credenciales Zernio configuradas + `FACTORY_PUBLISH=1`.

---

## 8. Solución de problemas

| Síntoma | Causa probable | Acción |
|---|---|---|
| `pulso-factory` no arranca | Error de build/volúmenes o permisos | `docker compose logs factory` y revisar rutas montadas en `docker-compose.yml` |
| `/api/health` no responde | Servicio aún iniciando o puerto ocupado | Esperar `start_period`/healthcheck; verificar `docker compose ps` y puerto `8610` |
| LLM local no conecta | Ollama en host no alcanzable desde contenedor | Verificar `OLLAMA_BASE_URL=http://host.docker.internal:11434/v1` y que Ollama esté activo |
| Cuotas/rate-limit de imágenes (429) | Límite de proveedor gratuito | Normal: la cascada hace fallback y recicla caché/imagenoteca; priorizar `KF_RECICLADO_CADA` e ingesta |
| No publica en redes | Faltan credenciales o publish desactivado | Revisar `ZERNIO_*`, `FACTORY_PUBLISH` y estado en panel `/api/estado` |
| Cambios en `factoryd.py` no aplican | Proceso en memoria | `docker restart pulso-factory` |

---

## 9. Siguientes lecturas

- [`README.md`](README.md): visión general, arquitectura y ejemplos.
- [`MEJORAS-PRO-2026-11-10.md`](MEJORAS-PRO-2026-11-10.md): mejoras recientes (subtítulos, ritmo, comics v3, bucle medir→aprender, costos $0-first).

