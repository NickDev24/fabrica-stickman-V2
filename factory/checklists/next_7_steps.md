# PRÓXIMOS 7 PASOS (en orden de apriete, no de facilidad)

Cada paso nombra el archivo exacto y cómo se valida que efectivamente pasó. El orden importa: el paso 3 no tiene sentido sin el 1, y el 7 no tiene sentido sin videos de 8 minutos que medir.

---

### PASO 1 · Tapar el fallo que publica sin subir nada (0.5 día) — **riesgo activo**
**Qué:** `publicacion.py:332-359` marca `AUTO_PUBLISHED` cuando la lista de archivos a subir está vacía (`all([]) == True`), y `tele_revision.py:109-129` usa ese estado para habilitar autonomía total tras 1 aprobación.
**Archivos:** `pipeline/stages/publicacion.py`, `pipeline/stages/tele_revision.py`
**Cambio:** exigir lista no vacía antes de iterar + incluir el master mp4 y la portada 16:9 + registrar el id devuelto por la plataforma + umbral de autonomía explícito.
**Validación:** test que corra `publicar_automatico` sin archivos derivados y **afirme `FAILED`, no `AUTO_PUBLISHED`**.

## PASO 2 · Convertir las 14 configs en parámetros que el código lee (1 día)
**Qué:** crear el loader único de `factory/**` y reemplazar los literales del pipeline por esos parámetros. Hoy ningún `.py` lee estas configuraciones.
**Archivos:** nuevo `factory/parametros.py`; consumidores `pipeline/stages/guion.py`, `pipeline/acting/beats.py`, `pipeline/stages/keyframes.py`, `pipeline/config.py`
**Validación:** `grep -rn "parametros\." --include=*.py pipeline` devuelve hits en las 4 etapas críticas; al cambiar un número en el JSON, el render cambia.

## PASO 3 · Decidir formato y duración objetivo, y hacerlo cumplir (1 día + 1 corrida)
**Decisión del dueño, no la tomo yo:** ¿el episodio de referencia es **8-10 min en 16:9** (YouTube long-form real) o **2-3 min vertical**? La fábrica hoy sólo sabe hacer lo segundo y los docs prometen lo primero.
**Qué:** con la decisión tomada, agregar `gate_extension` (1300-1600 palabras) y `gate_duracion` (500-600 s de audio real) en la cadena de gates de `guion.py:180-221`, y alinear el prompt de `guion.py:168` (hoy "500-700 palabras").
**Archivos:** `pipeline/stages/guion.py`, `pipeline/gates.py`, `factory/templates/script_template_8_10min.json`
**Validación:** un episodio cuyo `metadata.narration_duration_s` caiga en 500-600 s. Con 116.9 s, la fábrica está produciendo shorts con ambición de documental.

## PASO 4 · Ruta 16:9 y portada horizontal (1.5 días)
**Qué:** canvas horizontal para el episodio, dos composiciones (personaje a la izquierda, dato a la derecha), y `portada-yt.jpg` 1280x720 generada de verdad.
**Archivos:** `pipeline/config.py` (VIDEO_W/H/FPS), `pipeline/stages/keyframes.py:35,38,39,302` (canvas y `_plano`), `pipeline/stages/captacion.py:219`
**Validación:** `_qc` en verde para 1920x1080 y un archivo 1280x720 en `derivadas/`. Sin esto no existe la miniatura que todo el material de "nichos que funcionan" da por supuesta.

## PASO 5 · Muerte del frame estático (2 días) — **el gap más visible**
**Qué:** capa de micro-movimiento sobre el still (respiración 1.000→1.012 a 0.25 Hz, balanceo ±3 px, parpadeo cada 3-6 s, deriva de cámara), reactivar el POP de palabra clave y agregar el gate anti-frame-muerto.
**Archivos:** `pipeline/stages/keyframes.py` (`_plano`, línea 392 donde el POP está apagado, `_qc` línea 635), `factory/acting/stickman_motion_rules.json` como fuente
**Validación:** `ffmpeg signalstats YDIF` sin ventanas de 2 s con delta <0.1%; ≥35% de los beats con POP. Test nuevo en `tests/test_keyframes.py`.

## PASO 6 · Packaging YT/FB diferenciado y validado (1 día)
**Qué:** `gate_titulo` (45-70 caracteres, fórmulas prohibidas, 0 superposición con el overlay), títulos separados por plataforma en el paquete que se envía, y eliminar la ruta que finge métricas (`pipeline/stories.py` no se importa: borrarlo o marcarlo experimental).
**Archivos:** `pipeline/ideas.py:42-64`, `pipeline/gates.py`, `pipeline/stages/publicacion.py:51-53`, `pipeline/stages/captacion.py:146-162`
**Validación:** el mismo episodio sale con título y portada distintos en YT y FB, y ningún título de más de 70 caracteres o con "TOP/5 COSAS" llega a aprobación.

## PASO 7 · Cerrar el loop de aprendizaje (2 días)
**Qué:** ingesta real de métricas (`pipeline/metricas.py` nuevo), `state/metricas.jsonl`, reglas R1-R6 sobre la mediana propia, y `state/aprendizaje.json` escrito desde datos para que los pesos de `nichos.py` dejen de ser decorativos.
**Archivos:** nuevo `pipeline/metricas.py`, `pipeline/run.py` (comando `medir`), `pipeline/nichos.py:412`
**Validación:** después de 10 episodios publicados, la fábrica cambia **una** variable por episodio con hipótesis y resultado escritos en `state/iteraciones.jsonl`. Sin esto, "iterar" no existe.

---

## DECISIONES QUE NECESITO DEL DUEÑO ANTES DE LOS PASOS 3-5
1. **Duración y aspect objetivo** (8-10 min 16:9 vs 2-3 min vertical). Impacta costo: un episodio de 600 s necesita ~130 imágenes con la cuota de Flux que ya dio 429 a 41 imágenes.
2. **Voz canónica**: `piper:es_AR-daniela-high` (que dice el doc CFG-07) o `edge-tts:es-AR-TomasNeural` (que usa el código hoy). Mientras convivan, cada corrida cambia el ritmo y descalibra los tiempos del template.
3. **Presupuesto por episodio**: cuántos stills y cuántos tokens se pueden gastar antes de que el reciclaje de imágenes sea obligatorio en vez de opcional.
