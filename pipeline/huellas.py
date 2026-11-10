"""Anti-repetición de HISTORIAS (no de texto).

El gate 4 (`gates.gate_no_repeticion`, config.SIMILARITY_MAX_NGRAM) compara n-gramas del
guion contra los guiones publicados: detecta copia textual, pero deja pasar la misma
historia contada con otras palabras — que es exactamente como un canal se canibaliza.
Acá la comparación es de raíz temática: "Elecciones 2026 en Florida" y "midterms 2026,
quién controla el Congreso" comparten casi todas las raíces aunque ni una frase igual.

Cero LLM, cero costo: es un conjunto de raíces sobre lo que ya está en registry/.
"""
from __future__ import annotations

import json
import re
import unicodedata

from . import config

PUBLISHED = config.REGISTRY / "published.jsonl"

# Coeficiente de superposición (|A∩B| / min(|A|,|B|)), no Jaccard: un título corto contra
# el guion de un episodio publicado tiene conjuntos de tamaños muy distintos y Jaccard
# siempre daría bajo. 0.5 es el mismo espíritu del gate textual, a nivel de raíces.
UMBRAL_HISTORIA = float(__import__("os").environ.get("ANTI_REPETIR_UMBRAL", "0.5"))


def _raices(texto: str) -> set[str]:
    """Palabras significativas (>=4 letras, sin acentos) recortadas a 6 caracteres.

    La raíz de 6 cuenta "eleccion" contra "elecciones" y "congres" contra "congreso";
    con la palabra exacta no coincidía nada (mismo criterio que pipeline.stages.descubrir).
    """
    sin_acentos = "".join(c for c in unicodedata.normalize("NFKD", (texto or "").casefold())
                          if not unicodedata.combining(c))
    limpio = re.sub(r"[^a-z0-9 ]+", " ", sin_acentos)
    return {w[:6] for w in limpio.split() if len(w) >= 4}


def huella(texto: str) -> list[str]:
    return sorted(_raices(texto))


def similitud(a: str | set[str], b: str | set[str]) -> float:
    ra = _raices(a) if isinstance(a, str) else set(a)
    rb = _raices(b) if isinstance(b, str) else set(b)
    if not ra or not rb:
        return 0.0
    return len(ra & rb) / min(len(ra), len(rb))


def historias() -> list[dict]:
    """Todo lo ya producido/registrado, con su huella (calculada si el registro es viejo)."""
    if not PUBLISHED.exists():
        return []
    out = []
    for linea in PUBLISHED.read_text(encoding="utf-8").splitlines():
        linea = linea.strip()
        if not linea:
            continue
        try:
            fila = json.loads(linea)
        except json.JSONDecodeError:
            continue
        if not fila.get("huella"):
            base = " ".join([str(fila.get("titulo") or ""), str(fila.get("historia") or ""),
                             str(fila.get("script") or "")[:3000]])
            fila["huella"] = huella(base)
        out.append(fila)
    return out


def intentadas() -> list[dict]:
    """Episodios que ya tuvieron carpeta, aunque no hayan llegado a publicarse.

    Medido 2026-11-05: la misma idea de "midterms" murió tres veces en el gate 1 y siguió
    siendo la primera del ranking; la fábrica se congelaba repitiendo el intento fallido.
    Lo que ya se intentó no se vuelve a intentar como si fuera nuevo.
    """
    out = []
    for ruta in sorted(config.PROJECTS.glob("*/episode.json")):
        try:
            dato = json.loads(ruta.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        # `projects/idea-*` son SONDAS de verificación creadas por ideas.verificar(), no
        # episodios producidos. Una sonda VERIFICADA bloqueaba su propia idea (mismo título,
        # huella 1.0) y la fábrica quedaba en verificar -> descartar sin producir nunca.
        # Sólo las sondas con veredicto FALLIDO conservan el anti-reintento; las verificadas
        # y las que no llegaron a escribir veredicto (SIGTERM, re-verificación interrumpida)
        # no bloquean: la sonda se reescribe entera en la próxima verificación.
        es_sonda = ruta.parent.name.startswith("idea-") or bool(dato.get("verificacion_probe"))
        if es_sonda:
            veredicto = str(dato.get("verificacion_estado") or "").strip().lower()
            if veredicto not in ("descartada_sin_fuentes", "verificacion_insuficiente"):
                continue
        else:
            # Esqueleto de producción que nunca avanzó una etapa (corte de cuota, red,
            # SIGTERM): no es una historia contada y no puede vetar su propia idea.
            etapas = (dato.get("stage_status") or {}).values()
            if etapas and all(str(v).strip().lower() in ("", "pending") for v in etapas):
                continue
        texto = " ".join(str(dato.get(clave) or "") for clave in ("title", "historia", "categoria"))
        out.append({"slug": ruta.parent.name, "huella": huella(texto)})
    return out


def ya_contada(texto: str, umbral: float = UMBRAL_HISTORIA) -> tuple[bool, str, float]:
    """(está contada, slug de la más parecida, similitud). Vacío = nada publicado aún."""
    mejor = ("", 0.0)
    for fila in historias() + intentadas():
        s = similitud(set(fila["huella"]), texto)
        if s > mejor[1]:
            mejor = (str(fila.get("slug") or ""), s)
    return (mejor[1] >= umbral, mejor[0], round(mejor[1], 3))
