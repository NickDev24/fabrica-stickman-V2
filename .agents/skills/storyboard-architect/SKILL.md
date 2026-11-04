---
name: storyboard-architect
grupo: produccion
estado: operativa
punto_funcional: pipeline.stages.visuales.generar
contrato_salida: visuales
---

# storyboard-architect

## Objetivo y responsabilidades
Materializa cada segmento del guion en material visual por escena (assets/img|video/seg-NNN).

## Instrucciones operativas
**Operación:** para cada segmento del guion materializar el visual:
imágenes/archivo libre (Commons/Wikipedia/NASA filtrado por domínio) o
clip propio; guardar en `assets/img|video/seg-NNN.*`. PROHIBIDO usar
recreaciones como foto documental real; siempre score tree + crédito.

**Ejemplo:** `factory.skills.registry.invocar('storyboard-architect', ep)`
## Entradas (contrato de datos)
- Episodio: `projects/<slug>/` (clase `pipeline.episode.Episode`), con el pre-requisito: guion + research de urls
- Contexto compartido: `artifacts/` (script.txt, metadata.json, timeline_actuacion.json, lipsync.json)

## Salidas (contrato de datos)
- Contrato `visuales` validado por `factory/skills/contratos.py`
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
out = registry.invocar('storyboard-architect', ep)   # -> {estado, salida, evaluacion, duracion_s}
```
