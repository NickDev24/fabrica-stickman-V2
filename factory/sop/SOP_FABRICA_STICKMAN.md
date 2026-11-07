# SOP FÁBRICA STICKMAN v2 — DE LA IDEA AL VIDEO PUBLICADO

Cada fase tiene **puerta de entrada** y **puerta de salida**. No se avanza con la puerta de salida sin evidencia escrita en el proyecto. Nada de "está bueno": o pasa el check, o vuelve.

Ruta real de código hoy: `pipeline/run.py` → `guion.guion` → `narracion.narrar` → `keyframes.render` → `collage`/`montaje` → `derivados` → `captacion.derivar_captacion` → `publicacion` → `tele_revision.enviar_para_aprobacion`.

---

## FASE 0 · IDEA (antes de gastar un token)
- [ ] Nicho elegido de los 5 operativos: consumibles/deudas · finanzas · documentales-historia-vida silvestre · mascotas · salud-fitness
- [ ] Ángulo = recorte específico con protagonista y conflicto (no "la historia de X")
- [ ] ≥2 fuentes independientes por afirmación (ficción: ≥1 ancla de verosimilitud)
- [ ] Antiduplicado: similitud <0.55 ngram y <0.75 estructural contra los últimos 5 (`gates.py:167`)
- **Salida:** `episode.json` con categoria + título validado por `gate_titulo` (45-70 caracteres, sin fórmulas prohibidas)
- ⚠️ **Hoy faltan 3 de los 5 nichos en `pipeline/nichos.py`** (mascotas, salud/fitness, consumibles/deudas). Ver GAP-11 del informe.

## FASE 1 · GUION (donde se decide la retención)
- [ ] Prompt: `factory/prompts/guion_master.prompt.md` con variables inyectadas desde `nichos.canal_de()`
- [ ] Estructura: `factory/templates/script_template_8_10min.json` (6 bloques = 5 latidos)
- [ ] **1300-1600 palabras** → `gate_extension` (hoy el prompt pide 500-700 y los episodios salen de 312-388)
- [ ] Gancho: primera frase = pregunta de 6-12 palabras (`gate` actual: 4-16, `guion.py:77`)
- [ ] Bucles: 6-8, cada 45-90 s, cierra y encadena → `gate_bucles`
- [ ] `gate_fidelidad` en ≤4 reescrituras (ya corre, `guion.py:183`)
- [ ] Checklist completo `factory/checklists/retencion_checklist.md`, con la tabla de micro-hooks llena
- **Salida:** `artifacts/script.txt` + QC narrativo ≥82 con críticos en verde

## FASE 2 · VOZ
- [ ] Voz canónica única (ver `factory/audio/voice_config.json`: hoy el código sale con `edge-tts:es-AR-TomasNeural` mientras el doc prohíbe Tomas → **decisión del dueño, fase 1 de implementación**)
- [ ] `gate_voz` (allowlist) en verde
- [ ] Perfiles por bloque: gancho 140-150 wpm · exploración 150-165 · revelación 135-148
- [ ] Pausas aplicadas: coma 280 ms · punto 550 ms · interrogación 600 ms · dramatica 600-900 ms antes de la revelación
- [ ] `-14 LUFS ±2`, true peak -1.5
- **Salida:** `narration.wav` + `metadata.narration_duration_s` en 500-600 s → **si el audio dura menos de 500 s, el guion está corto: volver a FASE 1, no estirar la animación**

## FASE 3 · ACTUACIÓN Y KEYFRAMES
- [ ] Beats a 3.5-5.5 s (110-140 por episodio) — `beats.py:21-22`
- [ ] Gancho visual 0-3 s: beat 0 = flash-forward de la escena más intensa + shake + primer plano (`beats.py:356`, ya funciona)
- [ ] Cada bucle de curiosidad nuevo → cambio de escenario o de movimiento de cámara
- [ ] Metáforas por beat desde `stickman_motion_rules.json` (eliminar los literales de Madoff en `beats.py:139-240`)
- [ ] Micro-movimiento obligatorio: respiración, parpadeo, deriva de cámara (ver GAP-05: **hoy no existe en la ruta stickman**)
- [ ] POP de palabra clave reactivado (`keyframes.py:392` está desactivado)
- [ ] Reciclaje validado: misma identidad, escala e iluminación (`assets/image_reuse_policy.json`)
- **Salida:** `artifacts/beats.json` + carpeta `assets/kf/` + presupuesto de imágenes cubierto sin repetir stills más de 2 veces

## FASE 4 · EDICIÓN
- [ ] Composición 16:9 para el episodio largo y 9:16 para reel/short (hoy sólo existe 9:16 → **GAP-01**)
- [ ] Cortes: 11-17 por minuto; 6+ planos en los primeros 30 s
- [ ] Sólo hard cuts (y 0.3 s a negro entre bloques como máximo)
- [ ] Música -24/-18 LUFS relativo, ducking 40/300 ms, **corte de música 0.5 s antes de la revelación**
- [ ] SFX por metáfora, ≤1 cada 2 beats, nunca sobre la voz
- [ ] Subtítulo ≤42 caracteres por línea; POP ≤2 palabras; sin marca de agua
- **Salida:** render con `_qc` técnico en verde + `sin_frames_muertos` en verde

## FASE 5 · PACKAGING
- [ ] Título YouTube 45-70 caracteres, open loop, sin cifras inventadas
- [ ] Título Facebook: el gancho vive en los primeros 40 caracteres
- [ ] Portada 16:9 1280x720 **generada** (no sólo la vertical)
- [ ] Overlay ≤6 palabras, ≤1 palabra compartida con el título
- [ ] Prueba de 320 px y prueba de "¿se entiende el conflicto sin leer el título?"
- **Salida:** `derivadas/portada-yt.jpg`, `portada-fb.jpg`, `portada.jpg`

## FASE 6 · QC FINAL Y APROBACIÓN
- [ ] `qc_stickman_narrative.json`: todos los críticos en verde
- [ ] `qc_score_rubric.json`: score ≥82 sobre 100
- [ ] Telegram recibe VIDEO + TÍTULO + SUBTÍTULO + botones, y además el score y los déficit
- [ ] `synthetic_content=true` (gate 3)

## FASE 7 · PUBLICACIÓN
- [ ] Master mp4 + portada 16:9 entregados al publicador (no sólo los derivados)
- [ ] `AUTO_PUBLISHED` sólo con id de medio devuelto y persistido (**hoy se marca éxito con 0 uploads → GAP-02**)
- [ ] Hora programada respetada o `programacion.json` eliminado
- [ ] Log en `state/iteraciones.jsonl` con UN cambio testeado

## FASE 8 · MEDICIÓN (a los 7 y 28 días)
- [ ] Traer retención 0-30 s, 30-60 s, curva de caída, CTR, duración media
- [ ] Aplicar las reglas R1-R6 de `metrics/retention_loop.json`
- [ ] Escribir la decisión en el log y tocar **una sola** configuración para el próximo episodio
- **Salida:** `state/metricas.jsonl` con una fila más y `state/aprendizaje.json` actualizado

---

## REGLA DE CIERRE DE LA FÁBRICA
**Ningún episodio se publica con un crítico en rojo, aunque el calendario lo pida.** Un video malo publicado enseña menos que uno no publicado, y contamina la mediana con la que se calibran las reglas de iteración.
