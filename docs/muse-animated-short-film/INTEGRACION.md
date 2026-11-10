# Integración: Muse Animated Short Film (metodología)

Fuente original: [sonlovinbot-team/Muse-animated-short-film](https://github.com/sonlovinbot-team/Muse-animated-short-film) (MIT, © Đặng Hữu Sơn).  
Contenido vendorizado en este directorio: `SKILL.md`, `references/`, `examples/the-last-lantern/`, `LICENSE`.

## Qué aporta a Stickman Factory V2

Workflow probado para cortos animados de alta consistencia, complementario al pipeline existente:

1. **Intake cerrado (tiempo/idioma/ratio):** duración → nº de escenas (~10 s/clip), idioma de VO y **aspect ratio lock** (9:16/16:9) aplicado a *todos* los assets/ref.
2. **Character sheets on-model:** hoja de personaje multi-vista/expresión como “candado” de identidad antes de generar.
3. **Story bible (`STORY.md`):** logline, character/style lock, continuidad y beats por escena aprobados antes de producir.
4. **Keyframes con match-cut:** K1..K(N+1) donde el último frame de escena N = primero de N+1 (cortes invisibles).
5. **Mega prompts por escena:** global/style/character lock + refs (sheet → first → last) + FIRST/MOTION/CAMERA/LAST/SOUND/MUSIC/VO y chequeo de realismo físico.
6. **Generación, VO y montaje:** clips por keyframes, VO narrada (~50–60% del tiempo), normalización (mismo fps/res/codec) y concat/mix con ffmpeg.

## Cómo usarlo en esta fábrica

- **Planificación de episodios/capítulos:** usar `SKILL.md` y `references/02-story-and-script.md` + `03-keyframes.md` + `04-mega-prompts.md` para producir `STORY.md`, plan de keyframes y prompts por escena antes de ejecutar stages.
- **Consistencia visual:** alinear con `factory/acting/continuidad` y assets de personaje; las character sheets/locks refuerzan continuidad entre clips.
- **Montaje:** aplicar `references/07-assembly.md` (normalize → concat → mix VO con `adelay`, verify con `ffprobe`) coherente con el render ffmpeg del pipeline.
- **Plantillas:** ver `examples/the-last-lantern/` (`STORY.md`, `MEGA_PROMPTS.md`, `VO_SCRIPT.md`, `FLOW.md`).

## Nota

Este material es una **skill/metodología de producción** (prompts y flujo). Los comandos CLI citados en el upstream (`media-generation`, `tts`) son específicos de Muse AI; en esta fábrica se mapean a los stages/proveedores y herramientas locales equivalentes.
