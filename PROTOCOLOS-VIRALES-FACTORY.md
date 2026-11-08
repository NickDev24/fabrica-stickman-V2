# Protocolos virales de la fábrica — Factory Stickman (Pulso Curioso)

**Fecha:** 2026-11-08
**Alcance:** protocolos de control de validación viral de nivel experto para reels y cómics, integración en el flujo autónomo de publicación y decisión de canal (Zernio vs Telegram).

## 1. Cambios implementados en esta sesión

### 1.1 Nuevo módulo de validación viral experta — `factory/validacion_viral.py`

Complemento los gates técnicos existentes (`pipeline/gates.py`, QC de cómics) con controles
editoriales de nivel experto. Expone:

| Gate | Función | Tipo |
|---|---|---|
| `viral_visual_estimulante` | `gate_visual_estimulante(render_info, metadata)` — exige estimulación visual comprobable (beats/movimiento ≥3, duración mínima para arco). Se alimenta de `artifacts/render_keyframes.json` / `beats.json`. | Crítico |
| `viral_emocion_universal` | `gate_emocion_universal(script)` — exige presencia de emoción universal (miedo, asombro, venganza, injusticia, drama, tensión, etc.). | Crítico |
| `viral_recompensa_narrativa` | `gate_recompensa_narrativa(script)` — reusa `gates.gate_bucles` (6-8 aperturas de bucle, cierre que paga). | Crítico |
| `viral_comic` | `gate_comic_estimulante(datos)` + `validar_comic_viral(slug)` — hook en panel 1, silencio negro, giro/cliffhanger (Ki-Sho-Ten-Ketsu), ≥15 viñetas, grillas 3 bandas. | Crítico |

`validar_produccion_viral(ep) -> {"ok", "gates", "criticos"}` y `validar_comic_viral(slug) ->
{"ok", "gates"}` consolidan el diagnóstico.

### 1.2 Integración en el flujo autónomo — `pipeline/run.py`

- En la rama de publicación autónoma (`AUTO_PUBLISH=true` o autonomía por aprobaciones):
  se corrigen los protocolos virales expertos ANTES de publicar por Zernio; si `criticos`
  no está vacío, la corrida se detiene (`SystemExit` con los motivos).
- En la producción de cómics: se corrigen los protocolos virales expertos ANTES de
  componer/publicar el cómic; si falla, se bloquea la salida.

### 1.3 Decisión de canal: publicación por Zernio (Facebook + YouTube)

- `AUTO_PUBLISH=true` (en `.env`) habilita la publicación autónoma directa por Zernio
  (`pipeline/zernio.py`: presign → PUT → post con `publishNow`).
- Telegram deja de ser canal de contenido: `enviar_para_aprobacion` (video + título + subtítulo
  + botones) queda en el flujo no-autónomo / de revisión humana; en el modo autónomo el aviso
  es solo `notificar_autonomia`.

### 1.4 Fix de ejecución detectado — `pipeline/stages/publicacion.py`

- Corregido `ep.read_state("fuentes", [])` → `ep.read_state().get("fuentes", [])` (bloqueaba
  el checklist de publicación con `TypeError`).

## 2. Estado de la producción actual

- **Episodio actual:** `pulso-el-archivo-no-olvida` (IP "PULSO", Acto I, Concepto 1 — "El
  archivo no olvida").
- **Guion:** aprobado por todos los gates (título reparado a *"La historia que no termina: un
  archivo sin fin"*; gancho dorado; anti-duplicado; extensión; fidelidad).
- **Validación viral experta:** OK (visual, emoción, recompensa) — sin críticos.
- **Cómic:** storyboard generado por el pipeline (20 viñetas, 2 páginas); validación viral
  comic OK en el guion paneles preliminar.
- **TTS / render / derivados / captación / checklist / Telegram / registro:** completados.
- **Cómic render:** BLOQUEADO por cuota de imágenes (flux/pollinations/gemini agotadas).

## 3. Resultado de la corrida autónoma completa (`pipeline.run auto`)

- **Falló** en la fase de generación de la idea del día (`ideas.generar` → LLM): proveedores
  agotados (`cloudflare` HTTP 429 daily free allocation; `ollama` timeout).
- No llegó a publicación (bloqueo por cuota, no por validación).

## 4. Próximos pasos sugeridos

1. Recargar/recuperar cuota de proveedores LLM (Cloudflare Workers Paid / Ollama) para re-correr
   `pipeline.run auto` completo con publicación por Zernio.
2. Re-correr cómics con cuota de imágenes (`python -m pipeline.comics <slug> --render --componer`).
3. Medir métricas reales → aplicar reglas R1-R6 (`retention_loop.json`) → iterar.

## 5. Archivos tocados en esta sesión

- `factory/validacion_viral.py` (nuevo).
- `pipeline/run.py` (integración de validación viral en publicación y cómics).
- `pipeline/stages/publicacion.py` (fix `read_state`).
- `registry/published.jsonl` (registro del episodio producido).
