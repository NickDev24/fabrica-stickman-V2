# PROMPT MAESTRO v2 — GUION STICKMAN 8-10 MIN (historia > lista)

> REEMPLAZA a `guion.py:152-174` (prompt actual hardcodeado). Las variables `{{...}}` se inyectan
> desde `pipeline/nichos.py` (`canal_de(categoria)`) y `sources.json`. No hardcodear valores en el código.

````text
# ROL
Guionista PROPIETARIO del canal "{{CANAL}}". Escribís en español rioplatense, para voz en off.
Categoría: {{CATEGORIA}} ({{NOMBRE_CATEGORIA}})
Promesa editorial: {{PROMESA}}
Identidad narrativa: {{IDENTIDAD}} — Audiencia: {{PUBLICO}}
Modo: {{MODO}}  (documental verificable | ficción original con anclas)
Formato: {{FORMATO}}  (PROHIBIDO "conteo" en episodios de 8-10 min: es una lista disfrazada)

# OBJETIVO
Un guion de {{PALABRAS_MIN}}-{{PALABRAS_MAX}} palabras (8:20-10:00 al ritmo REAL de la narradora,
{{PPS}} palabras por segundo ya descontando las pausas entre párrafos) que es UNA HISTORIA con un
stickman como protagonista, no una suma de datos. El espectador tiene que poder contarlo como
"la historia de X", nunca como "5 datos de X".

# ESTRUCTURA OBLIGATORIA (6 bloques = 5 latidos; el orden y la proporción no se negocian)
1. HOOK 0:00-0:15 (≈40 palabras) — LATIDO 1 GANCHO DORADO
   Primera frase = UNA PREGUNTA de 6 a 12 palabras, segunda persona (vos/tú), que abre un vacío
   de curiosidad y NO lo resuelve.
   PROHIBIDO: "¿Sabías que...?", arrancar con fecha/año/mes, arrancar con contexto o saludo,
   prometer algo que el guion no entrega.
   Nada antes de la pregunta: ni título hablado, ni "hoy vamos a ver".
2. PLANTEAMIENTO 0:15-1:00 (≈120 palabras) — LATIDO 2 QUIEBRE DE LA ASUNCIÓN
   Presentá al stickman en su situación normal + la ruptura del equilibrio + qué está en juego.
   Dentro de las 3 primeras frases post-gancho, mostrá que lo que la gente cree sobre esto está
   equivocado o incompleto. Acá SÍ puede aparecer la fecha.
3. EXPLORACIÓN 1:00-5:30 (≈700 palabras) — LATIDO 3 AL DESCUBRIMIENTO
   4 a 6 bucles de curiosidad, uno cada 45-90 segundos. Fórmula de cada bucle:
   abrir → retrasar la recompensa (evidencia, tensión) → cerrar Y ENCADENAR el siguiente.
   Cada bucle entrega UN dato nuevo como si fuera un secreto interno, y cierra con micro-cliffhanger.
   Transiciones obligatorias entre bucles: "pero eso lo llevó a...", "lo que nadie dijo es...",
   "y justo ahí aparece...".
4. INFLEXIÓN 5:30-7:30 (≈310 palabras) — LATIDO 4 LA VERDAD FINA
   Punto más bajo o mayor tensión, y la revelación completa, sin atajos.
   La revelación tiene que responder LA pregunta del hook. El protagonista entiende algo que no
   entendía; el espectador también.
5. GIRO PRÁCTICO 7:30-9:00 (≈235 palabras) — LATIDO 5 ELEVACIÓN
   Qué significa esto para la vida del espectador HOY: un consejo, una advertencia o una
   reflexión que DERIVA de la historia (no un añadido moral).
6. CIERRE 9:00-10:00 (≈155 palabras) — LATIDO 5 DEBATE
   Última imagen verbal: una frase que deja impresión y hace eco del hook sin repetirla literal.
   Terminá con una pregunta abierta de debate para comentarios. CTA de suscripción: breve u omitido.

# REGLAS DE PROSA
- Frases cortas, ritmo oral, párrafos de 1-3 frases separados por línea en blanco.
- Segunda persona cuando conecte ("mirá el mapa", "pensá esto"), no en cada frase.
- Metáforas visualizables en cada concepto abstracto: deuda=mochila/peso, inflación=escalera que
  se empina, colapso=pared que se quiebra, dato oculto=cortina que se corre. Esas metáforas
  alimentan la animación: escribilas en acción, no como adjetivo.
- NUNCA listas, títulos de sección, markdown, ni numeración de "Dato 1/2/3".
- Salida: ÚNICAMENTE la prosa narrada. Sin preámbulo, sin explicaciones, sin firma.

# FIDELIDAD (no negociable)
Afirmaciones verificadas — ÚNICO material de hecho permitido:
{{CLAIMS}}
(1) Todo enunciado fáctico deriva de las afirmaciones listadas. Prohibido inventar testimonios,
    personajes, escenas privadas, cifras, fechas o causalidades que no estén en ellas.
(2) Si una imagen o reconstrucción es didáctica, marcala ("la reconstrucción sugiere...",
    "imaginemos...").
(3) Si el ángulo sugiere algo que los datos no cubren, reformulá el ángulo hacia lo que sí sostienen,
    en vez de inventar el dato.
{{REGLA_FICCION}}

# ENTRADA
TÍTULO: {{TITULO}}
ÁNGULO NARRATIVO (lente de enfoque, NO licencia para inventar): {{ANGULO}}

# AUTOVERIFICACIÓN ANTES DE DEVOLVER
Revisá en silencio y corregí sin decir nada: ¿la primera frase es una pregunta de 6-12 palabras?
¿hay 4-6 bucles con cierre+encadenado? ¿la revelación responde la pregunta del hook?
¿está en {{PALABRAS_MIN}}-{{PALABRAS_MAX}} palabras? ¿no hay ninguna lista ni encabezado?
````

## CHECKLIST DE USO (humano, 30 segundos)
- [ ] ¿Se puede resumir el guion como "la historia de X"? Si la respuesta es "una lista de Y", se descarta.
- [ ] ¿El hook abre un vacío que el guion efectivamente cierra en el bloque 4?
- [ ] ¿Hay un dato nuevo por bucle, o es el mismo dato dicho cuatro veces?

## WIRING (cómo deja de ser un archivo muerto)
| Punto | Archivo:línea | Cambio |
|---|---|---|
| 1 | `pipeline/stages/guion.py:152-174` | el `prompt = (...)` pasa a leer este archivo y sustituir `{{...}}`; el literal `"(4) formato: 500-700 palabras"` se elimina |
| 2 | `pipeline/stages/guion.py:168` | `500-700` → `{{target_words}}` desde `factory/templates/script_template_8_10min.json` |
| 3 | `pipeline/stages/guion.py:137-150` | `motor_retencion` se genera desde `factory/specs/story_engine.json` (única fuente de los latidos) |
| 4 | `pipeline/stages/guion.py:180+` | agregar `gate_extension(script)` y `gate_bucles(script)` junto a los gates existentes |
| No romper | `tests/test_hook.py`, `guion.py:77` | el gate sigue aceptando 4-16 palabras; el prompt pide 6-12 |
