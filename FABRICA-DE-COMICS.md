# Fábrica de cómics — diseño y plan de integración

## Propósito

Crear una historieta opcional a partir de cada episodio documental ya investigado y guionado. El cómic amplía el alcance entre quienes prefieren leer, deslizar paneles o compartir una historia visual; no sustituye los videos largos ni los Reels, que siguen siendo la prioridad de publicación.

La meta comercial es aumentar interacciones, seguidores y audiencia con la intención de acercarse a la monetización de YouTube y Facebook en tres meses. Es una meta de trabajo, no una garantía: el crecimiento, la elegibilidad y los ingresos dependen de la respuesta del público y de las reglas vigentes de cada plataforma.

## Estado de integración (actualizado 2026-11-07)

**La producción de video sigue siendo independiente**: ninguna falla del cómic puede bloquear, retrasar o cambiar la publicación del video. Desde el pedido del dueño (2026-11-07) la etapa está conectada al ciclo diario: se ejecuta después de registrar el video y, con `COMICS_ENABLED=1`, genera el libro, pasa el QC v2 y publica el carrusel de páginas en Facebook vía Zernio (sólo con `AUTO_PUBLISH` activo y QC aprobado). Sus artefactos, métricas, errores y publicación viven en `projects/<slug>/comics/` y `state/metricas_comics.jsonl`.

El interruptor sigue existiendo: con `COMICS_ENABLED` apagado o si cualquier paso falla, el video continúa su ruta intacta y el error queda registrado.

## Modelo editorial

**ORDEN DEL DUEÑO (2026-11-06) — el cómic es un LIBRO, no un "PDF de fotos":** mínimo **15 imágenes (viñetas) por capítulo**, repartidas en **páginas con grillas reales de 3 bandas** (ej. **3/4/3**: tres viñetas arriba, cuatro al medio, tres abajo; y sucesivamente), presentadas como libros. Retención de LECTOR (no de reel): ganchos, cliffhanger al cierre de cada página, silencio negro de descompresión, humor negro de ENCUADRE — todo anclado al guion verificado, **nunca hechos inventados**. Variedad de escena obligada: dos viñetas seguidas no comparten composición.

1. Recibir el episodio que ya pasó investigación y verificación de hechos. El guion necesita **≥ 13 oraciones** (si no, la extensión se apaga honesta sin publicar; el video sigue su ruta).
2. Storyboard determinista (`adaptar_guion.py`): oraciones → beats cronológicos consecutivos (13-18), + 2 beats de ritmo: **gancho flash-forward** (cold open que roba la oración de máximo impacto y la paga al menos una página después) y **silencio negro** tras el golpe. Roles por posición: gancho, contexto, escala (claim duro), cliffhanger de página (si el silencio cae en el cierre, el teaser retrocede al penúltimo), remate final. Cada viñeta cita LITERALMENTE su oración de origen (`ancla_guion`) y arrastra el claim verificado más cercano si hay match.
3. Ficha de personajes y guía visual por historia (`personajes.py`) para continuidad: narrador del canal + escena según lo que las fuentes permitan afirmar.
4. `imagen.py`: una imagen por viñeta (1024², flux-1-schnell vía cascada), **variedad real de prompts**: plano por rotación determinista, luz según rol rítmico (gancho contraste duro, escala luz fría, remate acento rojo), composición rota por pool. La viñeta de silencio **no quema cuota** (panel negro en composición). El prompt NUNCA pide texto dibujado.
5. **Texto compuesto FUERA del generador** (`componer.py`): páginas 1080×1620 con la grilla de 3 bandas, viñetas con cover-crop, marco de tinta grueso + tachuelas de esquina, caption tipográfico con narración + encuadre `[entre corchetes]` que SIEMPRE entra completo, número de viñeta, encabezado "PULSO CURIOSO · título", **footer por página con número y fuentes verificadas**. El caption puede pulirse con LLM (`captions.py`, `COMICS_CAPTIONS_LLM=1`): un guard determinista (cifras, nombres propios, negación, atribución y cobertura léxica) y un verificador en la ruta `verificacion` confirman la paridad factual; si algo no cuadra o no hay LLM, queda el caption determinista.
6. Exportar como LIBRO: `comics/pages/pag-NN.png` (la página), `comics/chapter_vertical.png` (páginas apiladas para lectura continua), `comics/carrusel/pag-NN.png` (1 imagen POR PÁGINA, formato libro — no por panel) y `manifest.json`.
7. Archivar en `guion_paneles.json` cada viñeta con su prompt/oración ancla, claim, fuentes y procedencia de imagen — reconstruible de punta a punta.

## Arquitectura propuesta

Mantener un paquete nuevo y aislado, por ejemplo `pipeline/comics/`, con estas responsabilidades:

- `adaptar_guion.py`: transforma el guion verificado en STORYBOARD comics.v2 (beats, grillas de 3 bandas, roles de ritmo, anclas literales), sin cambiar el guion audiovisual.
- `personajes.py`: fichas y referencias de continuidad, por episodio y con procedencia.
- `imagen.py`: adaptador propio para generar o reciclar ilustraciones; reusar bibliotecas y proveedores sólo mediante una interfaz estable.
- `componer.py`: motor de grillas 3 bandas — páginas 1080×1620 con cover-crop, marcos de tinta, tachuelas, captions, footer de fuentes; libro + chapter_vertical + carrusel por página.
- `qc.py`: reglas v2 que BLOQUEAN la salida: ≥ 15 viñetas, grillas reales (3 bandas de 1-4), narración ≤ 120 no vacía, ancla al guion verificado, fuentes en TODA página, imágenes legibles, tamaños del libro correctos.
- `metricas.py`: resultados del cómic separados de los del video.
- `telegram.py`: envío de revisión al dueño (NUNCA publicación).

Los resultados vivirían en `projects/<slug>/comics/`, no en `renders/` ni en las rutas que consumen los publicadores actuales. El video y el cómic compartirían investigación y guion verificado como entradas; no compartirían archivos temporales, estados de publicación ni gates.

## Repositorios de referencia

Se revisaron las páginas y README públicos el 6 de noviembre de 2026. Son referencias para estudiar componentes; no se propone copiar ni conectar ninguno directamente en producción.

| Repositorio | Qué aporta | Decisión para esta fábrica |
|---|---|---|
| [Generador-de-comics---V2](https://github.com/Juanrivera126/Generador-de-comics---V2) | Interfaz web estática, guion estructurado, 3–6 paneles, subpaneles, estilos, idiomas, edición y regeneración por panel. Declara licencia MIT y usa APIs de Pollinations. | Mejor referencia inicial para el flujo de edición por panel y exportación. Revisar la API vigente, límites y atribución antes de integrar. No depender de un endpoint gratuito como garantía de servicio. |
| [make-comics](https://github.com/nutlope/make-comics) | Storyboard y continuidad visual entre páginas, con referencias de personajes. | Buen referente de continuidad y flujo de autoría. Su README requiere Together AI, S3, Neon, Clerk y Upstash; no cumple el objetivo local, autónomo y sin costos como está. La página del repo no muestra licencia, así que no copiar código hasta comprobar derechos. |
| [llamagen](https://github.com/LlamaGenAI/llamagen) | Referencia conceptual de storyboard y API asíncrona de paneles. | El README documenta llamadas REST con API key; no asumir que sea gratuito ni disponible sin límites. Mantener como posible adaptador experimental, nunca como dependencia crítica. Revisar licencia y precios antes de cualquier uso. |
| [comic-generator](https://github.com/Yutarop/comic-generator) | Flujo simple de idea a manga de 1–7 páginas y continuidad mediante imagen de referencia. Declara MIT. | Útil como referencia de estructura y continuidad. Requiere modelos Gemini de texto e imagen; queda fuera de la ruta gratuita principal y sólo podría evaluarse como fallback pago explícitamente limitado. |

Licencias y condiciones de APIs pueden cambiar. Antes de incorporar código se debe fijar un commit, auditar dependencias y licencias, guardar atribuciones requeridas y probar el coste real. “Gratis” de una demo o repo no significa API gratuita para producción.

## Proveedores y fallbacks

Orden objetivo para la etapa de cómics:

1. Generación local o recursos ya archivados cuando el equipo pueda producirlos con calidad y tiempo aceptables.
2. Proveedor gratuito disponible, bajo límite explícito por episodio y con reintentos acotados.
3. Segundo proveedor gratuito desacoplado del primero.
4. Gemini sólo con opt-in explícito, presupuesto máximo por día/mes y saldo confirmado.
5. Si todos fallan, guardar el guion de paneles y un artefacto de error; continuar sin cómic y sin afectar videos ni publicaciones.

No usar una API hasta documentar si necesita clave, sus límites, costo, derechos de uso y política de retención. La ruta gratuita debe seguir funcionando sin credenciales pagas.

## Métricas y mejora continua

Separar los resultados por plataforma y formato. Registrar, cuando estén disponibles: alcance, impresiones, apertura/CTR, paneles vistos o finalización, tiempo de lectura, reacciones, comentarios, compartidos, guardados y seguidores atribuidos. No comparar impresiones de un Reel con lecturas de un carrusel como si fueran la misma medida.

- **Diario:** guardar resultados y detectar fallos de generación o publicación.
- **Semanal:** elegir una sola variable editorial para ajustar (gancho, número de paneles, texto por panel o estilo) y comparar cohortes equivalentes.
- **Mensual:** revisar qué nichos y formatos atraen interacción y seguidores; conservar los que tienen evidencia y descartar cambios sin resultado.

La mejora automática debe dejar registro de la métrica, hipótesis, cambio y comparación. No cambiar prompts, guion, estilo y publicación a la vez; no inventar conclusiones cuando la muestra sea pequeña.

## Fases propuestas

1. **Contrato y prototipo aislado:** esquema JSON del guion de paneles y una historieta de muestra, sin publicar.
2. **Continuidad visual y composición:** personajes consistentes, globos añadidos en postproducción y QC de lectura móvil.
3. **Exportación y archivo:** PNG/JPEG por panel, carrusel, portada y fuentes; todo bajo `projects/<slug>/comics/`.
4. **Medición:** registrar analítica propia del formato, sin alterar el ciclo de videos.
5. **Conexión opcional (HECHA 2026-11-07):** etapa no bloqueante detrás de `COMICS_ENABLED=1`, ejecutada después del video.
6. **Publicación (HECHA 2026-11-07):** carrusel de páginas en Facebook vía Zernio, con idempotencia y errores aislados; no reemplaza Reels/videos.

## Criterios de aceptación antes de conectar

- Una historia factual conserva el vínculo entre cada afirmación visual y sus fuentes.
- El texto se compone de forma legible y nunca queda a merced de letras generadas dentro de la imagen.
- Personajes, ropa y época mantienen continuidad o declaran el cambio intencional.
- Un fallo, timeout, cuota agotada o proveedor caído no impide terminar ni publicar el video.
- El presupuesto pago queda apagado por defecto y el costo por cómic se registra.
- Se puede reconstruir cada página desde el guion estructurado y los artefactos archivados.
- La publicación del cómic sólo se habilita después de una validación separada y explícita.
