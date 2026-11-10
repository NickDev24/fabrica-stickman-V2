# Ingesta de imágenes (generadas por otra IA)

Carpeta de entrada: dejá acá las imágenes que generaste con otra IA y querés que la
fábrica use en sus escenas. La fábrica **no borra** los originales.

## Cómo se incorporan

```bash
.venv/bin/python -m pipeline.run ingerir
```

Cada imagen se archiva en `assets/imagenoteca/` con un nombre SHA-256 (no se duplican)
y queda disponible para el reciclado semántico.

## Metadatos (obligatorios para que funcione la coincidencia)

Para que la fábrica sepa **qué escena representa** la imagen, necesita su prompt.
Ponelo en un `.json` o un `.txt` con el **mismo nombre base**:

```
assets/ingesta/mi-escena.png
assets/ingesta/mi-escena.json
```

`mi-escena.json`:

```json
{
  "prompt": "solid black stickman silhouette, round head, thick white outline, museum gallery at night, empty gilded frames, medium shot, hand-drawn documentary ink, warm-white paper",
  "escena": "galeria",
  "accion": "senala",
  "plano": "medio",
  "personaje": "4F",
  "tags": ["museo", "cuadros vacíos", "noir"]
}
```

- `prompt` — **clave**: es el texto con el que se compara la narración de cada beat.
  Copiá el prompt que usaste para generar la imagen (o describí la escena en inglés,
  que es el idioma del contrato visual del canal).
- `escena`, `accion`, `plano` — opcionales pero recomendados: si coinciden con la
  puesta en escena del beat, el reciclado es inmediato (misma composición).
- `personaje` — opcional. Si la imagen es del personaje del canal, poné `"4F"` (el
  valor de `state/estilo/personaje.json`). Si declarás un personaje distinto, la
  fábrica **no** la recicla, para no mezclar personajes.
- `tags` — palabras clave extra que se suman a la búsqueda semántica.

También acepta un `.txt` con sólo el prompt (menos preciso, pero útil):

```
assets/ingesta/mi-escena.png
assets/ingesta/mi-escena.txt   -> el prompt en texto plano
```

## Sin prompt

Si la imagen no tiene `.json` ni `.txt`, se archiva igual pero **no se recicla**:
la fábrica no inventa la descripción de una imagen que no generó.

## Notas

- Formatos: `.jpg`, `.jpeg`, `.png`, `.webp`. Mínimo 8 KB.
- Para quitar una imagen de la biblioteca, borrala de `assets/imagenoteca/` (el
  original de `assets/ingesta/` se puede quitar después de ingresar).
