# Imagenoteca de la fábrica

La fábrica conserva imágenes generadas en `assets/imagenoteca/`. Cada archivo usa un SHA-256 como nombre para deduplicar sin sobrescribir distintas imágenes. Cuando el origen lo permite, el `.json` homónimo guarda prompt, modelo, escena, acción, plano y procedencia.

`pipeline.imagen.importar_imagenes_existentes()` importa de forma no destructiva los archivos de `state/imagen_cache/` y `projects/*/assets/kf/`. Las nuevas imágenes se archivan automáticamente desde `pipeline.imagen.generar()`; el reciclaje usa sólo prompts o composiciones con metadatos válidos. Si falta contexto semántico, genera una imagen nueva en vez de reutilizar una que pudiera no corresponder.

Los originales se mantienen en su ubicación de proyecto/caché; esta carpeta es la biblioteca persistente compartida.

## Imágenes generadas por otra IA (ingesta)

El dueño puede incorporar imágenes producidas fuera de la fábrica dejándolas en
`assets/ingesta/` (ver `assets/ingesta/README.md`). Cada imagen necesita un `.json` o
`.txt` hermano con el `prompt` que describe la escena; sin ese texto no se puede
reciclar por semántica.

```bash
.venv/bin/python -m pipeline.run ingerir [--carpeta RUTA]
```

El comando archiva por SHA-256 (idempotente), escribe el sidecar con `prompt`,
`escena`, `accion`, `plano`, `personaje` y `tags`, y invalida el índice de reciclaje
para que la próxima búsqueda las incluya. El reciclado cross-episodio está habilitado
en la fábrica 24/7 (`--reciclar-imagenes` en `factoryd`); dentro del episodio, la
imagen anterior sólo se reutiliza si el beat es la misma toma o la narración es
prácticamente la misma (`KF_REUTILIZAR_UMBRAL`, `KF_REUTILIZAR_COMPOSICION`).
