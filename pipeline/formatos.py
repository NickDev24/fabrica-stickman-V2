"""Perfiles de formato: un mismo guion puede vivir en vertical corto o en pilar horizontal.

Medido en esta maquina (docs/capacidad.md + corrida Piper 2026-10-29): 387 palabras -> 139,0 s
de audio con PIPER_LENGTH_SCALE=1.3, o sea 2,78 palabras por segundo de narracion. Ese numero
es el que convierte duracion-objetivo en presupuesto de palabras: sin el, el corte se pasa
o se queda corto.

El vertical es 1080x1920 a 25 fps: 30 fps costo ~20% mas de render en el B950 sin ganancia
visible en Shorts.
"""
from __future__ import annotations

from dataclasses import dataclass, field

PALABRAS_POR_SEGUNDO = 2.78


@dataclass
class Perfil:
    clave: str
    nombre: str
    ancho: int
    alto: int
    fps: int
    segundos_min: int
    segundos_max: int
    bloques: int
    # Zona segura: subtitles y numero no se apoyan contra el borde (UI de la plataforma).
    margen_superior: int = 0
    margen_inferior: int = 0
    fuente_titulo: int = 96
    fuente_sub: int = 62
    presentador: bool = True
    music_bed: bool = True

    def palabras_objetivo(self, segundos: int | None = None) -> int:
        seg = segundos or round((self.segundos_min + self.segundos_max) / 2)
        return max(20, round(seg * PALABRAS_POR_SEGUNDO))

    def segundos_estimados(self, palabras: int) -> float:
        return round(palabras / PALABRAS_POR_SEGUNDO, 1)

    def dentro(self, palabras: int) -> bool:
        seg = self.segundos_estimados(palabras)
        return self.segundos_min - 4 <= seg <= self.segundos_max + 4


PERFILES: dict[str, Perfil] = {
    "short_vertical": Perfil(
        clave="short_vertical", nombre="Shorts / Reels vertical 9:16",
        ancho=1080, alto=1920, fps=25, segundos_min=20, segundos_max=60, bloques=4,
        margen_superior=210, margen_inferior=420),
    "docu_horizontal": Perfil(
        clave="docu_horizontal", nombre="Pilar documental 16:9",
        ancho=1280, alto=720, fps=24, segundos_min=360, segundos_max=600, bloques=14,
        margen_superior=40, margen_inferior=90, fuente_titulo=58, fuente_sub=46),
}

# Gramática de retención medida en 27 reels top de Nate Herk (marzo-septiembre 2026), leída en
# github.com/nateherkai/herk-edit-kit (docs/EDITING-PLAYBOOK.md) el 2026-10-29. No es gusto
# propio: son los números de un canal que funciona, usados como punto de partida.
REGLAS_CORTE = {
    "arranque_voz_s": 0.1,          # la voz arranca ya: sin cartela de intro
    "pausa_entre_frases_s": 0.2,    # dead air > 0,2 s mata el ritmo
    "plano_min_s": 1.1, "plano_max_s": 2.8, "plano_promedio_s": 1.4,
    "primer_corte_s": (0.6, 1.0),   # el primer cambio cae en la primera palabra cargada
    "presentador_en_pantalla_pct": 45,
    "presentador_ausencia_max_s": 3.5,
    "reparto": {"b_roll_completo": (50, 55), "split": (30, 42), "punch_in": (5, 15)},
    "palabras_por_plano": (3, 6),
    "regla": "todo plano se mueve: no existe el cuadro congelado",
}


def plano_de(palabras: int) -> float:
    """Duración de un plano: palabras / 2,78 w/s, recortado a la ventana medida 1,1-2,8 s."""
    seg = palabras / PALABRAS_POR_SEGUNDO
    return round(min(REGLAS_CORTE["plano_max_s"], max(REGLAS_CORTE["plano_min_s"], seg)), 3)


def cortes(bloque: str) -> list[str]:
    """Un bloque de narración se parte en planos de 3-6 palabras (uno por sintagma nominal)."""
    minw, maxw = REGLAS_CORTE["palabras_por_plano"]
    words, shots, cur = bloque.split(), [], []
    for w in words:
        cur.append(w)
        if len(cur) >= maxw or (len(cur) >= minw and len(" ".join(cur)) > 34):
            shots.append(" ".join(cur))
            cur = []
    if cur:
        if shots and len(cur) < minw:
            shots[-1] += " " + " ".join(cur)
        else:
            shots.append(" ".join(cur))
    return shots


def perfil(clave: str) -> Perfil:
    if clave not in PERFILES:
        raise KeyError(f"perfil {clave!r} inexistente; opciones: {sorted(PERFILES)}")
    return PERFILES[clave]
