---
name: phoneme-lipsync-engineer
grupo: animacion
estado: operativa
punto_funcional: factory.skills.adapters.lipsync_cues
contrato_salida: lipsync_cues
---

# phoneme-lipsync-engineer

## Objetivo y responsabilidades
Alineación fonética de visemas sobre el WAV de Piper con Rhubarb; fallback silábico siempre declarado.

## Instrucciones operativas
**Operación:** pasar el WAV de Piper a Rhubarb (`tools/rhubarb/rhubarb`,
`-r phonetic --extendedShapes GHX`), recortar cues de visemas y guardar
`artifacts/lipsync.json`. Para español, Rhubarb funciona sin diccionario
(rutas fonéticas); NUNCA presentar cues silábicos como fonéticos — el motor
`silabico` es fallback declarado y exige QC reforzado.

**Criterios:** cues monótonos, visemas en {A B C D E F G H X}, densidad
esperada 6..16 cues/s. Si el WAV no existe: fallar con instrucción ('narrar').

**Ejemplo:** `tools/rhubarb/rhubarb -f json -r phonetic -o lipsync.json dialogo.wav`
## Entradas (contrato de datos)
- Episodio: `projects/<slug>/` (clase `pipeline.episode.Episode`), con el pre-requisito: narración segmentada + WAV
- Contexto compartido: `artifacts/` (script.txt, metadata.json, timeline_actuacion.json, lipsync.json)

## Salidas (contrato de datos)
- Contrato `lipsync_cues` validado por `factory/skills/contratos.py`
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
out = registry.invocar('phoneme-lipsync-engineer', ep)   # -> {estado, salida, evaluacion, duracion_s}
```
