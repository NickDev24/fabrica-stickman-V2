---
name: viral-story-researcher
grupo: narrativa
estado: operativa
punto_funcional: factory.skills.adapters.senales
contrato_salida: senales
---

# viral-story-researcher

## Objetivo y responsabilidades
Detecta señales de demanda real (Wikipedia, Hacker News, canales activos) y clasifica nicho + formato viable.

## Instrucciones operativas
**Operación:** `pipeline.tendencias.detectar` sobre semillas del nicho
(Wikipedia热度, Hacker News, canales en vivo) + `pipeline.ideas.generar`
para proponer episodios rankeados. No se adopta idea por grabbing viral
aislado: exigir señal sostenida (demanda, comentarios reales).

**Ejemplo:** `factory.skills.registry.invocar('viral-story-researcher')`
## Entradas (contrato de datos)
- Episodio: `projects/<slug>/` (clase `pipeline.episode.Episode`), con el pre-requisito: semillas de temas
- Contexto compartido: `artifacts/` (script.txt, metadata.json, timeline_actuacion.json, lipsync.json)

## Salidas (contrato de datos)
- Contrato `senales` validado por `factory/skills/contratos.py`
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
out = registry.invocar('viral-story-researcher', ep)   # -> {estado, salida, evaluacion, duracion_s}
```
