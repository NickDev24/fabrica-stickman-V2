# DEPENDENCIAS

Licencias y estado real de cada pieza que usa la fábrica de documentales.
Verificado el 2026-11-03 sobre esta máquina (Pentium B950, 2 núcleos, 11 GiB, sin GPU).

## Binarios / librerías que ya están en el repo

| Pieza | Versión | Licencia | Rol | Estado verificado |
|---|---|---|---|---|
| `tools/rhubarb/rhubarb` | 1.14.0 | MIT (deps: Boost, BSD-2 cmusphinx, cppformat) | lip-sync por fonema desde el WAV de Piper | `--version` OK, `ldd` resuelto, modelos PocketSphinx incluidos (`res/sphinx/`), no requiere fitlation externo |
| `factory/render/vendor/three.module.js` | r169 | MIT | motor de render 3D headless | cargado y renderizando vía Chrome+SwiftShader |
| `factory/render/vendor/GLTFLoader.js` | r169 | MIT | carga del GLB del avatar | presente, se usa con importmap local |
| FFmpeg (`/usr/bin`) | 7.1.5 | LGPL/GPL según build | composición final, mezcla, subtítulos | operativo |
| Piper TTS (`/usr/bin/piper`) | — | BSD-3 (voz es_ES-carlfm: CC-BY-4.0, autor Carlfm) | voz en español | operativo |
| Voz Piper `es_AR-daniela-high` | — | Modelo distribuido por Piper; dataset OpenSLR 61 bajo CC BY-SA 4.0 (atribución y compartir igual; ver tarjeta de modelo) | voz argentina de mayor calidad para narración | descargada/verificada por SHA-256 en `models/voices/` |
| Google Chrome (`/usr/bin`) | 155 | propietario (uso como motor de render local) | WebGL por software (SwiftShader) | operativo con `--enable-unsafe-swiftshader` |
| Node.js (`/usr/bin/node`) | 22.23 | MIT | driver CDP sin dependencias npm | `WebSocket`/`fetch` globales disponibles |
| Ollama local | 0.30.8 | MIT (servidor); `deepseek-r1:1.5b` MIT, derivado de Qwen 2.5-Math Apache-2.0 | fallback LLM sin API ni costo por llamada | binario y modelo presentes; el pipeline inicia el daemon local si hace falta |

## Repos externos presentes en el árbol

| Repo | Licencia | Decisión |
|---|---|---|
| `mesh-avatar-studio/` | MIT (Yuki Shindo) | **No se usa para el avatar GLB.** Es un motor WebGL2 propio de mallas 2D deformadas en CPU, no carga GLB. Su `npm run render-poses` (Playwright) sirve como referencia de captura por poses si algún día se pivotea a 2.5D con ese motor. Requiere `npm install` (hoy no está instalado). |
| `avatarstudio/` | BSD-3 | **Descartado.** Es el repo del paper (3D desde texto sobre threestudio/GET3D); sin código utilitable y exige GPU NVIDIA. |
| `OpenMontage/` | **AGPLv3** | **Descartado para el pipeline de producción.** Licencia viral de red: importarlo obligaría a abrir el código del proyecto. Solo se usa como lectura de patrones. |
| `awesome-opus5-5-videos/` | MIT | Catálogo de prompts; no aporta render. |
| `Scrapling/` | BSD-3 | **Integrado como librería instalada** (`scrapling` 0.5 en el venv) para la lectura de fuentes. Ver "Integraciones de esta sesión". |
| `OpenCreator/` | ver su LICENSE | Ajeno a la fábrica de avatar; no se toca. |
| `Stickman-Studio/` | Apache-2.0 | **No se importa código.** Se copia el patrón de reintento (tenacity: `RETRY_MAX_ATTEMPTS`/`RETRY_BASE_DELAY`) a `pipeline/llm.py`. Su `tts_engine.py` usa edge-tts y sus fases usan Gemini/Imagen/Veo (pagos): fuera del objetivo "100 % free". Su `.env` tiene un service-account JSON en claro al lado del repo (`stickman-studio-key.json`): riesgo de credencial, no de licencia. |
| `stick/` | GPL-3.0-or-later | **Editor autónomo; no se copia ni importa código** en la fábrica. Puede utilizarse manualmente para crear/editar animaciones y exportarlas como material propio. El repositorio es un editor interactivo, no un renderizador por lotes autónomo. |
| `stick-gen/` | Prosocial Public License PPL-3% actual; contiene licencia MIT para versiones históricas identificadas explícitamente | **No se integra al pipeline ni se instala.** No hay checkpoint de modelo en el clon; la inferencia declara uso procedural y la integración de motion generado con su renderer sigue incompleta. La PPL incluye una participación de 3% para usuarios comerciales que superen USD 1M de ingresos globales anuales; revisar la licencia vinculante antes de uso comercial. |

## Integraciones de esta sesión (investigación + resiliencia LLM)

| Paquete | Versión | Licencia | Rol | Costo medido |
|---|---|---|---|---|
| `scrapling` | 0.5 | BSD-3 (LICENSE verificado en el repo clonado) | parseo con lxml y extracción por selectores del HTML de las fuentes (`pipeline/web.py`) | 186 kB wheel |
| `curl_cffi` | 0.17.0 | MIT | huella TLS de Chrome para las peticiones: DDG respondía 403 al cliente `python-requests` | libcurl compilado, sin navegador |
| deps de scrapling | — | `lxml` 6.1.3 (BSD-3), `cssselect` 1.6.0 (Apache-2.0), `orjson` (Apache-2.0/MIT), `tld`, `w3lib` (MIT), `typing_extensions` (PSF) | parsing | 5.2 MB (lxml) |

- **Patchright / Playwright / Camoufox: NO instalados.** `scrapling.fetchers` importa
  `patchright` a nivel de módulo (48,5 MB de wheel + un Chromium de ~300 MB y ~1 GB de RAM por
  pestaña). Se usa sólo `scrapling.parser` + `curl_cffi`, que cubre el caso real de la fábrica
  (fuentes estáticas de `.gov`/`.edu`/prensa) sin tocar el presupuesto de RAM del render.
- **Sin credenciales nuevas:** ninguna de estas dos integraciones llama a un servicio pago.

## Decididas en FASE 1

- **Babylon.js: NO se instala.** Three.js r169 ya está vendorizado, resuelve la carga de GLB, morph targets y skinning, y ya está probado headless en esta máquina. Añadir Babylon sería duplicar motor.
- **whisper.cpp: NO se instala (por ahora).** Rhubarb entrega alineación por fonema con tiempos
  reales y medidos sobre el audio del canal: **95,5 % del tiempo de habla tiene un visema a menos
  de 180 ms**, 7,6 cues/s (banda esperada 6-16). Con ese número, whisper.cpp queda en ROADMAP como
  mejora de precisión, no como necesidad.
- **glTF-Transform: PENDIENTE de instalación** (npm, MIT). Hoy el único GLB del repo es
  `assets/characters/cloakman.glb`, generado por `tools/make_character_glb.py` con 7144 triángulos
  y 0,17 MB: no hay nada que optimizar. Se corre el día que llegue el GLB real del "cloak man"
  (todavía no existe en esta máquina), y con la consigna de no romper esqueleto/animaciones/morphs.
- **El avatar actual es propio, no del usuario.** `cloakman.glb` es original de este repo (mallas
  generadas por el script), así que no arrastra licencia de terceros. El rig es por nodos nombrados
  (sin skinning ni morph targets), documentado en `state/personajes/rig_cloakman.json`.
- **OpenTimelineIO: NO se instala.** La línea de tiempo multi-clip se arma con `filter_complex`/concat de FFmpeg y alcanza.
- **Blender: prohibido** por consigna del proyecto. No se instala ni se invoca.

## Riesgo de licencia a vigilar

- Voz Piper `es_ES-carlfm-x_low`: el JSON del modelo **no declara licencia ni dataset** (campos `dataset_name` y `voice` vacíos). Antes de publicar hay que confirmar la licencia upstream en Hugging Face `rhasspy/piper-voices`; mientras, los videos mantienen el cartel "Voz sintética (IA)".
- Rhubarb usa un modelo acústico **en-us**: sobre audio en español la detección de fonemas es
  aproximada. Medido (`medir_alineacion` sobre los 58,4 s de pulso-001): 95,5 % de cubrimiento de
  la voz y **33 cues cayendo en silencio** (boca que se mueve entre frases). Es un límite técnico
  declarado, no un problema de licencia.

## Referencias externas revisadas (no incorporadas como runtime)

| Proyecto | Licencia/compatibilidad | Decisión |
|---|---|---|
| `kaomei/stickman-video-director` | MIT; Director Mode requiere generadores de video externos opcionales; Autopilot dibuja/ilustra y anima con pan/zoom | Se adoptan como dirección editorial los conceptos visuales por categoría y metáforas específicas; no se instala código ni se añade API paga. |
| `MvRicciutelli/SAM-Stickman-Animation-Maker` | PolyForm Strict 1.0.0 con permiso comercial para contenido, pero no permite redistribuir/modificar sin permiso escrito; Windows 10/11 | No se integra al pipeline Linux. Puede servir manualmente en una PC Windows para diseñar una actuación original, tras revisar términos completos. |

## Repositorios añadidos (2026-11-04)

| Repo | Licencia / disponibilidad | Decisión técnica |
|---|---|---|
| `stick/` | GPL-3.0-or-later | Se mantiene aislado como editor manual; no se copia código a la fábrica. Sus proyectos/exportaciones pueden servir para escenas originales creadas manualmente. |
| `stick-gen/` | PPL-3%; `LICENSE-MIT-LEGACY` aplica solo a versiones/archivos históricos identificados | No hay checkpoint de inferencia en el clon y `generator.py` documenta que el movimiento ML todavía no se integra al renderer. No se instala Torch/Transformers ni se entrena en el B950. El motor actual queda fuera del build automático; revisar obligaciones PPL antes de cualquier integración comercial. |
