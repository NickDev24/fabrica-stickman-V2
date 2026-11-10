# Mejoras PRO — fábrica stickman/comics (2026-11-10)

## Resumen de commits (sesión)
- `8542327` — Autonomía 24/7, ingesta/reciclaje de imágenes y render con subtítulos ASS quemados.
- `16c0faf` — Subtítulos cinéticos/legibles, ritmo visual/cámara más dinámico y cascada de imagen $0-first.
- `84440ab` — Cómics premium v3: portada scroll-stopper, captions legibles en móvil y carrusel con portada.
- `f11d2c3` — Bucle `medir→aprender` post-episodio y portadas A/B para cómics.

`registry/ideas.jsonl`, `registry/oportunidades.jsonl`, `registry/published.jsonl` son datos/runtime y quedan fuera de commit.

## Video (retención y costos)
- **Subtítulos dinámicos (ASS/libass)** por beat, quemados en el máster: estilo de alto contraste/legible en móvil y énfasis de palabra clave/cifra (`pipeline/stages/keyframes.py`). Desactivable con `KF_SUBTITULOS=0`.
- **Ritmo/cámara**: hook y primeros tramos con mayor variedad de plano/movimiento y alternancia para reducir monotonía (`factory/acting/beats.py`).
- **Costo de imagen ~0**: cascada prioriza ruta gratis (Cloudflare primario → Pollinations/HF → Gemini solo último recurso, sujeto a tope/cooldown) (`pipeline/imagen.py`). `factoryd` corre con `--reciclar-imagenes` y `KF_RECICLADO_CADA=2`; maximizar caché/`assets/ingesta`/imagenoteca evita regenerar.
- **Preview validado**: `pipeline.run preview curiosidad-madoff-v5 --segundos 15` → 14.99 s, 720x1280, -13.9 LUFS, `status: pass`, `problemas: []`.

## Cómics premium (scroll-stop y lectura móvil) — `comics.v3`
- **Portada (slide 1) de impacto**: portada 1080x1620 con imagen de gancho de alto contraste, titular corto, branding y CTA “Deslizá y leé la historia”; incluida como primer elemento del carrusel FB (`pipeline/comics/componer.py`).
- **Variantes A/B/C de portada** (hook/acento, sin costo de imagen): se generan `portada_a/b/c.png`, se elige variante y se registra `portada_variante`/`portada_variantes` en `manifest.json` para testeo de CTR.
- **Legibilidad móvil**: captions bold, más grandes, con degradado/sombra y alto contraste; el silencio se trata como beat de tensión (no vacío).
- **Packaging/publicación**: carrusel = portada + páginas, copy de feed con gancho/CTA; QC y publicación aceptan v2/v3 y validan portada (`pipeline/comics/qc.py`, `pipeline/comics/publicar.py`). Tests: `tests/test_comics.py` (14 passed).

## Bucle cerrado de mejora (`medir → aprender`)
- `docker/factory/factoryd.py` ejecuta `pipeline.run medir` y `pipeline.run aprender` (best-effort) tras cada episodio exitoso.
- `pipeline/metricas.py` ingesta analítica real (Zernio/YouTube) a `state/metricas.jsonl`; datos no disponibles se registran como `sincronia`/null (nunca como 0).
- `pipeline/aprendizaje.py` aplica reglas R1–R6 contra la mediana propia del canal y escribe **un solo cambio** por iteración en `state/aprendizaje.json` (overrides/pesos) que consume `factory/parametros.py`. Sin métricas suficientes no simula aprendizaje (`sin_datos_suficientes`).
- **Operación**: tras cambios en `factoryd.py` reiniciar el proceso/contenedor para tomar el bucle en memoria (ej. `docker restart pulso-factory`).

## Estado operativo
- `pulso-factory` reiniciado y healthy (`:8610`), `factoryd` corriendo con el bucle activo; bind-mount sirve el código del repo.
- Episodio en curso avanza por gates (investigación/fact-check). En logs se observó Cloudflare Flux en 429/cuota con fallback a Pollinations/rate-limit: la cascada $0 mantiene salida, con mayor latencia.

## Viabilidad 3D (`img2threejs`)
- **No viable como reemplazo directo ni “entrenable”** del generador 2D actual: reconstruye un objeto como código procedural Three.js (no mesh/fotogrametría) a partir de una referencia, por asset y con costo/tiempo alto; el pipeline produce keyframes 2D por beat en FFmpeg. Ruta acotada posible: generar offline assets 3D reutilizables y mezclarlos como complemento, manteniendo fallback 2D por defecto.

## Próximos pasos (viralidad masiva, continuo)
- Acumular métricas reales (CTR, retención 3s/30s/curva, swipe/guardados) para disparar ajustes automáticos de hook/portada/ritmo.
- A/B de packaging en video (títulos/miniaturas/primer frame) y selección por rendimiento; consistencia visual de personaje/serie.
- Más pattern-interrupts, B-roll/overlays desde ingesta/imagenoteca y voz/mezcla más expresiva, sosteniendo cascada $0 + caché/reciclaje.
