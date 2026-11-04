---
name: thumbnail-art-director
grupo: produccion
estado: pendiente_backend
punto_funcional: factory.skills.adapters.miniatura
contrato_salida: miniatura
---

# thumbnail-art-director

## Objetivo y responsabilidades
Miniatura con sujeto principal, máximo 3 palabras de texto, contraste alto y requerimientos CTR verificables.

## Instrucciones operativas
**PENDING (backend futuro).** Contrato FIRMADO que el módulo debe cumplir:
entradas = render principal + paleta + título; salida = `thumbnail.jpg`
1280x720 con sujeto principal + <=3 palabras + contraste alto; QC =
tamaño de texto relativo > 0.08 del alto y UI textual mínima. El
orquestador NO debe llamarla hasta que exista el módulo real.
Estado en registry: `pendiente_backend`.
## Entradas (contrato de datos)
- Episodio: `projects/<slug>/` (clase `pipeline.episode.Episode`), con el pre-requisito: render principal + paleta
- Contexto compartido: `artifacts/` (script.txt, metadata.json, timeline_actuacion.json, lipsync.json)

## Salidas (contrato de datos)
- Contrato `miniatura` validado por `factory/skills/contratos.py`
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
out = registry.invocar('thumbnail-art-director', ep)   # -> {estado, salida, evaluacion, duracion_s}
```
