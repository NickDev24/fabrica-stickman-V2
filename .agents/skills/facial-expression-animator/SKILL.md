---
name: facial-expression-animator
grupo: animacion
estado: operativa
punto_funcional: factory.skills.adapters.expresiones_bloques
contrato_salida: expresiones
---

# facial-expression-animator

## Objetivo y responsabilidades
Traduce la partitura emocional a bloques de rig facial por segmento (cejas ojos mirada cabeza boca base) con transiciones suaves.

## Instrucciones operativas
**Operación:** leer la timeline del character-director (fuente única de verdad)
y exponer los bloques de rig facial listos para el backend. Si no hay timeline,
componer bloques desde la partitura con `estados.transicion_bloque`.

**Reglas de calidad facial (pilar 1):** cejas independientes, micro-exposición
ocular 0.85..1.4, mirada con intención (dx/dy), transiciones nunca lineales.
Prohibido: valores fuera del contratado por `estados.PARAMS`; simpular
"emoción" solo con boca abierta.

**Ejemplo:** `factory.skills.registry.invocar('facial-expression-animator', ep)`
## Entradas (contrato de datos)
- Episodio: `projects/<slug>/` (clase `pipeline.episode.Episode`), con el pre-requisito: episodio con script.txt
- Contexto compartido: `artifacts/` (script.txt, metadata.json, timeline_actuacion.json, lipsync.json)

## Salidas (contrato de datos)
- Contrato `expresiones` validado por `factory/skills/contratos.py`
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
out = registry.invocar('facial-expression-animator', ep)   # -> {estado, salida, evaluacion, duracion_s}
```
