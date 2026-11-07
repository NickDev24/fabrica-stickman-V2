# CHECKLIST DE ACEPTACIÓN DE LA FÁBRICA v2

No es una lista de deseos: cada ítem tiene la prueba que lo demuestra. Si no se puede mostrar la evidencia, el ítem está en rojo.

## 🔴 BLOQUEANTES (la fábrica no está terminada sin esto)
- [ ] **Las configuraciones se leen en código.** Prueba: `grep -rn "story_engine\|script_template_8\|stickman_motion_rules\|voice_config\|editing_config\|title_rules\|publish_strategy\|retention_loop\|qc_score_rubric" --include=*.py pipeline factory` devuelve ≥1 hit por archivo. *(Hoy: 0 hits. Este es el ítem que define todo lo demás.)*
- [ ] **Episodio real de 8-10 minutos.** Prueba: `metadata.narration_duration_s` entre 500 y 600 s y `word_count` entre 1300 y 1600 en un episodio producido de punta a punta. *(Hoy: 116.9 s con 312 palabras.)*
- [ ] **Ruta 16:9 existente.** Prueba: un mp4 1920x1080 y una portada 1280x720 en `derivadas/`. *(Hoy: todo sale 720x1280 / 1080x1920.)*
- [ ] **Publish honesto.** Prueba: ningún episodio con `publish_status=AUTO_PUBLISHED` sin un id de plataforma persistido. *(Hoy: `all([])` == True marca éxito con 0 uploads.)*
- [ ] **Sin frames muertos.** Prueba: `signalstats YDIF` > 0 sobre ventanas de 2 s en el 100% del video. *(Hoy: el personaje es una imagen fija; sólo se mueve la cámara.)*

## 🟡 NARRATIVA
- [ ] Gancho = pregunta de 6-12 palabras en primera frase, gate + tests en verde
- [ ] Historia con protagonista verificada (resumible como "la historia de X")
- [ ] 6-8 bucles de curiosidad con cierre y encadenado, gate ejecutándose
- [ ] Revelación que responde la pregunta del gancho
- [ ] Formato "conteo" bloqueado para episodios largos
- [ ] Score QC ≥82 sobre 100 con base que suma 100

## 🟡 PRESENTACIÓN
- [ ] Micro-movimiento (respiración/parpadeo/deriva) aplicado en la ruta stickman
- [ ] POP de palabra clave reactivado, ≥35% de los beats
- [ ] Metáforas abstracto→visual cargadas desde JSON, sin literales de episodio en el código
- [ ] 6+ planos en los primeros 30 s, sin 3 beats consecutivos con el mismo movimiento
- [ ] Voz canónica única, con pausas en ms reales y perfil por bloque
- [ ] Música con ducking y silencio de 0.5 s antes de la revelación

## 🟡 PACKAGING Y DISTRIBUCIÓN
- [ ] Portada con conflicto, overlay ≤6 palabras, legible a 320 px
- [ ] Par título/miniatura sin superposición de palabras
- [ ] YouTube y Facebook con título, duración y formato distintos en el paquete que se envía
- [ ] Horario de publicación realmente respetado (o el plan se borra)
- [ ] El reel/short con gancho propio, no un corte heredado del minuto 2

## 🟢 MEJORA CONTINUA
- [ ] Ingesta de métricas de YouTube/Facebook funcionando y persistida
- [ ] Reglas R1-R6 aplicadas sobre la mediana propia
- [ ] `state/iteraciones.jsonl` con UN cambio por episodio, documentado antes de publicar
- [ ] `state/aprendizaje.json` alimentado por métricas reales (pesos ≠ 1.0 decorativo)
- [ ] 3 nichos operativos restantes cubiertos en `nichos.py` (mascotas, salud/fitness, consumibles/deudas)

## Criterio de "fábrica aceptada"
**Todos los 🔴 + ≥80% de los 🟡 + una medición real posterior a 10 episodios.** Con los 🔴 en rojo, cualquier mejora de prompt o checklist es decoración sobre un video de 2 minutos.
