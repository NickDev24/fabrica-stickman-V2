# Guía de instalación — PULSO Curioso (Fábrica Stickman V2)

Instrucciones basadas en la configuración real del repositorio (`.env.example`, `docker-compose.yml`) para desplegar la fábrica localmente y configurar secretos/canales.

**Repositorio:** https://github.com/NickDev24/fabrica-stickman-V2

---

## 1. Requisitos previos

- Git
- Docker Engine + Docker Compose v2 (`docker compose`)
- ~8–15 GB de disco libre y 8 GB+ RAM recomendado
- (Opcional, según tu entorno) Ollama en el host si usarás LLM local; el compose apunta a `http://host.docker.internal:11434/v1`
- (Opcional) Claves de proveedores (LLM/imágenes) y credenciales de publicación Zernio

Comprobación:
```bash
git --version
docker --version
docker compose version
```

### Nota importante sobre rutas/volúmenes (Docker Compose)

`docker-compose.yml` está configurado para el entorno del proyecto y:
- ejecuta como `user: "1000:1000"` con `HOME=/home/facu`
- monta el repo en `/app` y, además, rutas del host: `/home/facu/piper-env` y `/home/facu/.local/bin`
- expone `factory` en `8610` y `dashboard` en `8611`

Si tu máquina/usuario/rutas difieren, ajusta `user`, `HOME` y los volúmenes en `docker-compose.yml` antes de levantar para que Piper/edge-tts y permisos funcionen correctamente.

---

## 2. Descargar

```bash
git clone https://github.com/NickDev24/fabrica-stickman-V2.git
cd fabrica-stickman-V2
```

---

## 3. Configurar `.env` (secretos, cuentas y canales)

Crea el archivo de entorno desde la plantilla:

```bash
cp .env.example .env
```

Edita `.env` y completa los valores que necesites. Variables definidas en `.env.example`:

```dotenv
# LLM / proveedores
MISTRAL_API_KEY=
QWEN_API_KEY=
CLOUDFLARED_ACCOUNTS_ID=
CLOUDFLARED_WORKER_AI=
BADROCK_API_KEY=
AIONLABS_API_KEY=
GEMINI_API_KEY=
GOOGLE_GEMINI_API_KEY=
NAME_PROJECT=
NUMBER_PROJECT=
ID_PROJECT=
KAGGLE_API_KEY=
HUGGINFACE_TOKEN=
POLLINATIONS_API_KEY=

# Integraciones
TELEGRAM_TOKEN_BOT=
TELEGRAM_CHAT_ID=

# Publicación Zernio (cuentas/canales destino)
ZERNIO_API_KEY=
ZERNIO_ACCOUNT_ID=
ZERNIO_FACEBOOK_ID=
ZERNIO_YOUTUBE_ID=

# Control de publicación y producción
AUTO_PUBLISH=
FACTORY_PUBLISH=
KF_RECICLADO_CADA=2
COMICS_ENABLED=
COMICS_CAPTIONS_LLM=

# Costos / límites
ALLOW_PAID_LLM=
GEMINI_PRESUPUESTO_USD_MES=
ALLOW_REMOTE_LLM=
CF_MAX_IMAGENES_DIA=
```

**Guía rápida:**
- **Secretos:** nunca commitees `.env`. Guárdalo solo en tu máquina.
- **Publicación (Zernio):** configura `ZERNIO_API_KEY`, `ZERNIO_ACCOUNT_ID` y los IDs de destino `ZERNIO_YOUTUBE_ID` / `ZERNIO_FACEBOOK_ID` (tus canales/cuentas). Controla el modo automático con `FACTORY_PUBLISH` (compose lo toma, default `1`) y/o `AUTO_PUBLISH`.
- **LLM/Imágenes:** agrega las claves de los proveedores que vayas a usar; variables de costo/límites (`ALLOW_PAID_LLM`, `ALLOW_REMOTE_LLM`, `GEMINI_PRESUPUESTO_USD_MES`, `CF_MAX_IMAGENES_DIA`) te permiten controlar gasto/rutas.
- **Ollama local:** el contenedor usa `OLLAMA_BASE_URL=http://host.docker.internal:11434/v1` (definido en compose) para llegar al Ollama del host.

---

## 4. Levantar la fábrica

```bash
docker compose up -d --build
```

Qué levanta:
- `factory` (puerto **8610**): backend `factoryd` (REST + WebSocket), pipeline en loop 24/7.
- `dashboard` (puerto **8611**): Mission Control (nginx) con proxy a la API.

Revisa estado:
```bash
docker compose ps
```

---

## 5. Verificar

```bash
curl http://localhost:8610/api/health
# esperado: {"ok": true}

curl -s http://localhost:8611/api/estado | head
```

Abre el panel: **http://localhost:8611**

Capturas reales del panel incluido en el repositorio:

![Inicio](assets/docs/dashboard-inicio.png)
![Fábrica de Video](assets/docs/dashboard-fabrica-video.png)
![Fábrica de Cómics](assets/docs/dashboard-fabrica-comics.png)
![Métricas](assets/docs/dashboard-metricas.png)

---

## 6. Operación

```bash
docker compose logs -f factory   # ver logs
docker restart pulso-factory     # reiniciar backend
docker compose down              # detener
docker compose up -d             # iniciar
```

- Ajusta `FACTORY_PUBLISH`/`AUTO_PUBLISH` en `.env` según si deseas publicar automáticamente o solo generar/revisar, y reinicia servicios tras cambios.
- Datos y salidas de ejecución se guardan en runtime (`state/`, `projects/`, cachés) en tu máquina.

---

## 7. Solución de problemas

- **Factory no healthy / errores de arranque:** `docker compose logs factory`. Revisa que las rutas montadas en `docker-compose.yml` existan en tu host o ajústalas.
- **Puertos ocupados:** cambia el mapeo `8610:8610` / `8611:80` si ya están en uso.
- **Ollama no conecta:** asegúrate de tener Ollama corriendo en el host y accesible vía `host.docker.internal`.
- **No publica:** verifica `ZERNIO_API_KEY`, IDs de cuentas/canales (`ZERNIO_*`) y flags de publicación en `.env`.
- **Cuotas/rate-limit de proveedores:** depende de tus claves/planes; ajusta límites/costos en `.env`.

