# Imagenoteca de la fábrica

La fábrica conserva imágenes generadas en `assets/imagenoteca/`. Cada archivo usa un SHA-256 como nombre para deduplicar sin sobrescribir distintas imágenes. Cuando el origen lo permite, el `.json` homónimo guarda prompt, modelo, escena, acción, plano y procedencia.

`pipeline.imagen.importar_imagenes_existentes()` importa de forma no destructiva los archivos de `state/imagen_cache/` y `projects/*/assets/kf/`. Las nuevas imágenes se archivan automáticamente desde `pipeline.imagen.generar()`; el reciclaje usa sólo prompts o composiciones con metadatos válidos. Si falta contexto semántico, genera una imagen nueva en vez de reutilizar una que pudiera no corresponder.

Los originales se mantienen en su ubicación de proyecto/caché; esta carpeta es la biblioteca persistente compartida.
