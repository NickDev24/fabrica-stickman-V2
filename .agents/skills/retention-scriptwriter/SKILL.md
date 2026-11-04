---
name: retention-scriptwriter
grupo: narrativa
estado: operativa
punto_funcional: pipeline.stages.guion.guion
contrato_salida: guion_segmentado
---

# retention-scriptwriter

## Objetivo y responsabilidades
Escribe el guion con identidad de canal del nicho, hooks, escalada y final (pipeline/stages/guion).

## Instrucciones operativas
**Operación:** escribir el guion segmentado (`pipeline/stages/guion.guion`)
con identidad del canal por nicho (`pipeline.nichos.canal_de`),
hook < 15 s, escalada, giros y final. Respetar transformación de ideas
(gate anti-duplicado contra los últimos 5 guiones).

**Criterios:** bloques 20..120 palabras; preguntas abiertas repartidas;
zero clickbait; cumplimiento del modo ficción/documental del nicho.

**Ejemplo:** `factory.skills.registry.invocar('retention-scriptwriter', ep)`
## Entradas (contrato de datos)
- Episodio: `projects/<slug>/` (clase `pipeline.episode.Episode`), con el pre-requisito: episodio verificado
- Contexto compartido: `artifacts/` (script.txt, metadata.json, timeline_actuacion.json, lipsync.json)

## Salidas (contrato de datos)
- Contrato `guion_segmentado` validado por `factory/skills/contratos.py`
- Artefactos escritos en `artifacts/` (ver Operación)

## Herramientas y repositorios compatibles
- pipeline/ (stages, llm multiproveedor con caché y rutas por tarea), factory/acting/ (estado/gestos/lipsync)
- Rhubarb Lip Sync (MIT, visemas), Piper TTS (VOX, voz del canal), FFmpeg (montaje y QC ebur128/blackdetect)
- mesh-avatar-studio / OpenMontage para representación visual y variante editorial

## Criterios de calidad
- Producto REAL medible (no placebo): la evaluación `registry.evaluar` marca pass/falla_N sobre el contrato.
- Hardware limitado: un solo render simultáneo, 720p/24fps GLB, serialización FFmpeg (config.limites).
- Siempre declarar el motor real usado (rhubarb/silabico, rhubarb debe ser el objetivo).

## Validaciones
- Entrada: exige episódio con pre-requisitos; contratos produccion (`contratos.py`) aplicados automáticamente.
- Salida: `evaluacion` en el retorno de `invocar` con problemas concretos.

## Condiciones de error y recuperación
- La skill NO mata la fábrica: `invocar` registra `status=error` en `state/skills_log.jsonl`
  con las últimas 2 líneas del traceback, y el orquestador decide reintentar o degradar.
- Fallbacks declarados en metadata (nunca se presenta un fallback como la vía óptima).

## Ejemplo de ejecución
```python
from pipeline import episode
from factory.skills import registry
ep = episode.Episode('<slug>')
out = registry.invocar('retention-scriptwriter', ep)   # -> {estado, salida, evaluacion, duracion_s}
```
