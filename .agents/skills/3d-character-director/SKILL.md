---
name: 3d-character-director
grupo: animacion
estado: operativa
punto_funcional: factory.acting.director.construir_timeline
contrato_salida: timeline_actuacion
---

# 3d-character-director

## Objetivo y responsabilidades
Dirige la actuación completa del actor digital: curva emocional visemas cámara micro-behaviors en artifacts/timeline_actuacion.json.

## Instrucciones operativas
**Operación:** correr después de `narrar` (necesita `segment_durations_s`).
1. Segmentar `artifacts/script.txt` igual que la voz (`narracion._segments`).
2. Pedir partitura emocional al LLM (`pipeline.llm.chat_json`, task `direccion`); si
   el LLM falla usar fallback determinista y MARCARLO en el log.
3. Compilar: transición suave prev->nuevo (0.45 s, smootherstep, escalada por
   intensidad) + gesto (anticipación en `gesto_t0`) + blinks + micro.
4. Cámara con política por emoción; corte interior si el plano dura > 8 s.
5. Escribir `artifacts/timeline_actuacion.json` y validar contra
   `factory/specs/timeline_actuacion.schema.json`.

**Error y recuperación:** si Rhubarb no está instalado, el lip-sync cae a modo
silábico (declarado); el director igualmente produce timeline y el orquestador
decide si aceptarla. Si no hay narración: SystemExit con instrucción clara.

**Ejemplo (CLI):** `python -c "from pathlib import Path; from
factory.acting.director import construir_timeline; construir_timeline(Path('projects/<slug>'))"`
## Entradas (contrato de datos)
- Episodio: `projects/<slug>/` (clase `pipeline.episode.Episode`), con el pre-requisito: un episodio narrado
- Contexto compartido: `artifacts/` (script.txt, metadata.json, timeline_actuacion.json, lipsync.json)

## Salidas (contrato de datos)
- Contrato `timeline_actuacion` validado por `factory/skills/contratos.py`
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
out = registry.invocar('3d-character-director', ep)   # -> {estado, salida, evaluacion, duracion_s}
```
