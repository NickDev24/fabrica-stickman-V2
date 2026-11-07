# CHECKLIST RETENCIÓN v2 — SE CORRE ANTES DE ANIMAR

> Se pasa sobre `artifacts/script.txt`, con el cronómetro mental del ritmo real: **2,24 palabras/segundo** (ritmo efectivo medido de es-AR-TomasNeural ya descontando las pausas entre párrafos).
> 40 palabras ≈ 15 s · 120 palabras ≈ 46 s · 700 palabras ≈ 4:30.

## A) GANCHO 0:00-0:15 — decide el 70% del resultado
- [ ] La primera frase del archivo es la pregunta (nada antes: ni título hablado, ni saludo, ni fecha)
- [ ] Termina en `?`
- [ ] 6-12 palabras (el gate tolera 4-16: `pipeline/stages/guion.py:77`)
- [ ] Segunda persona: vos/tú
- [ ] Es concreta y contraintuitiva (hay un objeto, una cifra o una acción, no una categoría)
- [ ] Abre un vacío que el guion **cierra en el bloque D**, no en el A
- [ ] No dice "¿Sabías que...?" ni promete algo que el material no muestra
- [ ] Prueba de scroll: si esto suena en un reel con audio apagado y sólo se ve el frame 0, ¿igualmente frena?

## B) PLANTEAMIENTO 0:15-1:00
- [ ] Aparece el stickman como protagonista (no "la gente", no "los expertos")
- [ ] Situación inicial normal + ruptura del equilibrio
- [ ] Hay algo medible en juego (dinero, tiempo, salud, libertad)
- [ ] **LATIDO 2**: dentro de las 3 primeras frases post-gancho se rompe una asunción del espectador
- [ ] La fecha/contexto, si existe, aparece acá y no antes

## C) EXPLORACIÓN 1:00-5:30 — el bloque donde más se cae
- [ ] 4 a 6 bucles identificables (6-8 en todo el episodio)
- [ ] Ningún bucle dura más de 90 s sin abrir el siguiente
- [ ] Cada bucle: abre → retrasa (evidencia/tensión) → cierra → **encadena**
- [ ] Cada bucle entrega UN dato que no estaba antes (si no hay dato nuevo, es relleno)
- [ ] Cada cierre de bucle tiene micro-cliffhanger
- [ ] Cero enumeraciones ("el primero", "el segundo", "5 secretos")
- [ ] Cada párrafo tiene una metáfora convertida en acción visual, no en adjetivo

**Mapa de micro-hooks (completar a mano sobre el guion, 3 minutos):**
| # | Tiempo | Palabras acumuladas | Bucle que abre | Bucle que cierra | Dato nuevo |
|---|---|---|---|---|---|
| 1 | 0:15 | 40 | | | |
| 2 | 1:00 | | | | |
| 3 | | | | | |
| 4 | | | | | |
| 5 | | | | | |
| 6 | | | | | |

## D) INFLEXIÓN 5:30-7:30
- [ ] Hay un punto más bajo o de máxima tensión
- [ ] La revelación responde **la pregunta exacta del gancho**
- [ ] Se cobra la promesa sin atajos ni vaguedades
- [ ] El protagonista entiende algo que no entendía (transformación visible)
- [ ] Nada de la revelación se dijo antes en forma de resumen

## E) GIRO PRÁCTICO 7:30-9:00
- [ ] Conecta con la vida del espectador hoy
- [ ] Consejo / advertencia / reflexión que **deriva** de la historia (no moraleja pegada)
- [ ] Es accionable: el espectador puede hacer algo con esto

## F) CIERRE 9:00-10:00
- [ ] Una frase final que deja imagen mental
- [ ] No es "y eso es todo", ni resumen de lo dicho
- [ ] Pregunta abierta de debate (combustible de comentarios)
- [ ] CTA de suscripción breve o inexistente
- [ ] Hace eco del gancho sin repetirlo literal

## G) MEDICIONES DURANTE LA LECTURA (2 minutos con cronómetro)
- [ ] Total 1300-1600 palabras (`metadata.word_count`)
- [ ] Lectura en voz alta: 8:20-10:00
- [ ] Los primeros 30 s: ¿hay 2 cambios de escena además del gancho?
- [ ] ¿Se puede resumir en una línea como "la historia de X"? Si sale "una lista de Y", se descarta

## H) MANO A LA ANIMACIÓN (sólo si A-G pasaron)
- [ ] Palabras clave marcadas en el guion para sincronizar gesto/POP
- [ ] Metáforas asignadas por beat (ver `factory/acting/stickman_motion_rules.json`)
- [ ] El beat 0 hereda la escena más intensa (flash-forward) — esto ya lo hace `beats.py:356`

**FALLA UNO CRÍTICO (A, C, D o la prueba de 'historia vs lista') → SE REESCRIBE ANTES DE ANIMAR. Animar un guion malo cuesta 130 imágenes y una hora de render.**
