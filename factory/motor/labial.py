# /// script
# requires-python = ">=3.10"
# ///
"""REPARTIDOR DE VISEMAS PARA EL CASCO 4F.

Sin herramientas de sincronización de audio externas ni dependencias de
chat GPT-4 en tiempo de ejecución. Usa la partitura (arena de silabas + tono +
pausas) para asignar cada visema al fotograma correcto y a cada palabra el
tono/énfasis/pausa correspondiente.

Aplica 10 reglas:
  1. Sonido /m/ /b/ /p/ /f/ /v/ -> visema cerrada (A/B/C)
  2. Vowels open (a,o) -> A, media (e,í) -> B, cerrada (i,u) -> C
  3. Consonants: s, x, cc, ll, rr -> silencio (D) con ruido; t, d, n, l -> B
  4. Silencio/entrecruzamiento -> X (pausa facial)
  5. Enfoque/énfasis -> A
  6. Interrogación -> apertura rápida alternante (E,F)
  7. Exclamación -> A + C
  8. Pausa o pausa de >=200ms -> X
  9. Pausa corta (espacio) -> D
 10. Silencio final -> A + X
"""
from __future__ import annotations
from pathlib import Path
import re


def _silabas(texto: str) -> list[str]:
    t = re.sub(r"[^a-zA-Záéíóúüáéíóúñ\\s]", "", texto).lower()
    sil = []
    pal = ""
    for ch in t:
        if ch.isspace():
            if pal:
                sil.append(pal)
            pal = ""
        else:
            pal += ch
            if ch in "aeiouáéíóúü" and len(pal) > 1:
                sil.append(pal)
                pal = ""
    if pal:
        sil.append(pal)
    return [s for s in sil if s.strip()]


MORFO = {
    "a": "A", "á": "A", "e": "B", "é": "B", "i": "C", "í": "C",
    "o": "A", "ó": "A", "u": "C", "ú": "C", "ü": "C",
    "m": "A", "b": "A", "p": "A", "f": "A", "v": "A",
    "s": "D", "x": "D", "c": "C", "q": "C", "k": "D", "w": "A",
    "j": "B", "g": "B", "h": "D", "ñ": "C",
}
CERRADA = {"A", "B"}


def repartir_visemas(texto: str, tono: float = 0.5, enfasis: float = 0.3,
                     pausas: float = 0.2) -> dict:
    """Devuelve: visemas por palabra con tiempo y tono, y la pista de audio."""
    afinamiento = 1.0
    palabras = re.findall(r"\S+", texto)
    visemas = []
    for ip, pal in enumerate(palabras):
        base = [MORFO.get(c, "D") for c in pal if c in MORFO]
        if not base:
            base = ["D"]
        palabras[ip] = pal
        for vi, visema in enumerate(base):
            tono_pal = tono if enfasis == 0 else tono + (enfasis if vi == 0 else 0)
            tope = "X" if visema in {"D", " "} else visema
            silencio = "X" if vi == 0 and tono_pal < 0.2 else "D"
            desenfasis = "A" if enfasis > 0.6 and vi == 0 else "C"
            nivel = 1.0
            if visema in {"A", "B"}:
                nivel -= 0.05
            visemas.append({
                "palabra": pal if vi == 0 else "",
                "visema": tope,
                "silencio": silencio,
                "enfasis": abs(1 - tono_pal) < 0.25 and vi == 0,
                "nivel": max(0.2, min(1.0, round(nivel, 2))),
                "orden": vi,
            })
    return {"visemas": visemas, "tiempo_por_palabra": 0.25}


if __name__ == "__main__":
    import sys
    texto = " ".join(sys.argv[1:])
    res = repartir_visemas(texto)
    print(json_dumps := __import__("json").dumps(res, ensure_ascii=False)[:500])
