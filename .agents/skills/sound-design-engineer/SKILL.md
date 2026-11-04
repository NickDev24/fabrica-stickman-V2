---
name: sound-design-engineer
grupo: produccion
estado: operativa
punto_funcional: factory.skills.adapters.plan_sonoro
contrato_salida: sonoro
---

# sound-design-engineer

## Objetivo y responsabilidades
Plan sonoro por segmento (música, ambientes, impactos) alineado con la partitura emocional; SFX solo donde la narrativa los pide.

## Instrucciones operativas
**Operación:** de la timeline, produzir `artifacts/plan_sonoro.json`
(pistas amb/SFX con tiempo y ganancia, música -18 dB con ducking,
silencios dramáticos en suspenso). Ejecutar mezcla en el montaje con
FFmpeg amix; la música NUNCA competencia de la voz.

**Ejemplo:** `factory.skills.registry.invocar('sound-design-engineer', ep)`
## Entradas (contrato de datos)
- Episodio: `projects/<slug>/` (clase `pipeline.episode.Episode`), con el pre-requisito: timeline de actuación
- Contexto compartido: `artifacts/` (script.txt, metadata.json, timeline_actuacion.json, lipsync.json)

## Salidas (contrato de datos)
- Contrato `sonoro` validado por `factory/skills/contratos.py`
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
out = registry.invocar('sound-design-engineer', ep)   # -> {estado, salida, evaluacion, duracion_s}
```
