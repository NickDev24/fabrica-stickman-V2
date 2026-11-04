---
name: documentary-investigator
grupo: narrativa
estado: operativa
punto_funcional: pipeline.stages.research.research
contrato_salida: fuentes
---

# documentary-investigator

## Objetivo y responsabilidades
Investiga el tema, descubre fuentes primero, resume y contrasta; registros en artifacts/sources.json + factcheck.json.

## Instrucciones operativas
**Operación:** descubrir fuentes (`stages.descubrir`), extraer contenido,
redactar resumen con citas (`stages.research.research`) y verificar con
proveedor INDEPENDIENTE (`factcheck`). Para historia/política/belico:
fuentes因为它 identificables, fechas y no-inventar testimonios.

**Gate 1:** < 4 fuentes únicas => SystemExit (no se publica sin research).

**Ejemplo:** `factory.skills.registry.invocar('documentary-investigator', ep)`
## Entradas (contrato de datos)
- Episodio: `projects/<slug>/` (clase `pipeline.episode.Episode`), con el pre-requisito: episodio seleccionado
- Contexto compartido: `artifacts/` (script.txt, metadata.json, timeline_actuacion.json, lipsync.json)

## Salidas (contrato de datos)
- Contrato `fuentes` validado por `factory/skills/contratos.py`
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
out = registry.invocar('documentary-investigator', ep)   # -> {estado, salida, evaluacion, duracion_s}
```
