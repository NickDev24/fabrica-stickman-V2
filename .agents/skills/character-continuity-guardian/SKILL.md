---
name: character-continuity-guardian
grupo: animacion
estado: operativa
punto_funcional: factory.acting.continuidad.auditar
contrato_salida: continuidad
---

# character-continuity-guardian

## Objetivo y responsabilidades
Consistencia del personaje entre videos: perfil persistente (identidad proporciones vestuario paleta iluminación) y validación contra cada producción.

## Instrucciones operativas
**Operación:** persistir perfil del personaje en `state/personajes/`
(paleta, iluminación, backend GLB, voz) y auditar cada episodio: backend
estable, GLB idéntico, voz en allowlist. Bloquea aprobación con problemas.

**Criterios (pilar 7):** un solo GLB por personaje; cambios de vestuario
requieren registrarlos; iluminación del perfil nunca desviada.

**Ejemplo:** `factory.skills.registry.invocar('character-continuity-guardian', ep)`
## Entradas (contrato de datos)
- Episodio: `projects/<slug>/` (clase `pipeline.episode.Episode`), con el pre-requisito: episodio + perfil en state/personajes/
- Contexto compartido: `artifacts/` (script.txt, metadata.json, timeline_actuacion.json, lipsync.json)

## Salidas (contrato de datos)
- Contrato `continuidad` validado por `factory/skills/contratos.py`
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
out = registry.invocar('character-continuity-guardian', ep)   # -> {estado, salida, evaluacion, duracion_s}
```
