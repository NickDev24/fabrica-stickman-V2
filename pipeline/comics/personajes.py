"""Fichas de personajes del cómic + guía visual por historia (continuidad).

Reglas del diseño (FABRICA-DE-COMICS.md):
  - El narrador es la mascota del canal (identidad silueta de person.json).
  - Los personajes de escena se DIFERENCIAN por rol según lo que las fuentes
    permitan afirmar (investigador, sospechoso anónimo, figura histórica, testigo).
  - Cada ficha declara procedencia: de qué panel del guion de paneles salió.
Todo determinista; se guarda en comics/personajes.json para auditar y reusar.
"""
from __future__ import annotations

import json
import re

from .. import imagen as motor  # hoja de personaje del canal (state/estilo/personaje.json)
from ..episode import Episode

ROLES = (
    (("investigador", "investigación", "investigacion", "detective", "fbi", "policía",
      "policia", "fiscal", "agente"), "investigador"),
    (("sospechoso", "ladrón", "ladron", "asaltante", "intruso", "criminal", "robo",
      "bandido", "encapuchado"), "sospechoso"),
    (("guardia", "seguridad", "vigilante", "custodio"), "guardia"),
    (("testigo", "vecino", "afirma", "según", "segun"), "testigo"),
)

GUIAS = {
    "investigador": "investigador de escena: abrigo de tela, libreta, gorra de ala; "
                    "rostro simple y definido, distinto del narrador del canal",
    "sospechoso": "sospechoso anónimo: figura con capucha oscura sin rostro visible, "
                  "presencia grande y sombra; anonimato por diseño",
    "guardia": "guardia de seguridad: uniforme simple con gorra y linterna",
    "testigo": "testigo: figura casual con sudadera, rostro simple pero expresivo",
    "figura_historica": "figura de época: ropa del período que menciona el guion, "
                        "rasgos generales, sin detalles biográficos inventados",
}


def _rol_de(texto: str) -> str:
    t = (texto or "").lower()
    for claves, rol in ROLES:
        if any(k in t for k in claves):
            return rol
    return "figura_historica"


def fichas(ep: Episode, datos_comic: dict) -> dict:
    """Devuelve (y archiva) {actor: {rol, guia_visual, procedencia}} del episodio."""
    try:
        hoja = motor.estilo()
    except Exception:
        hoja = {}
    salida = {
        "narrador_canal": {
            "rol": "narrador",
            "guia": str(hoja.get("identidad", "silueta negra de contorno blanco grueso, sin cara")),
            "procedencia": "state/estilo/personaje.json (contrato del canal)",
        },
        "__estilo_visual": {"estilo": str(datos_comic.get("estilo_visual",
                                                        "stickman noir, tinta negra, acento rojo")),
                            "sin_texto_dibujado": True},
    }
    for p in datos_comic.get("paneles", []):
        actor = str(p.get("actor") or "").strip() or "narrador_canal"
        if actor in salida:
            continue
        contenido = (str(p.get("narracion", "") or p.get("ancla_guion", ""))).lower()
        rol = _rol_de(contenido)
        salida[actor] = {"rol": rol, "guia": GUIAS[rol],
                         "procedencia": f"viñeta {p.get('i')} del storyboard (comics.v2)"}
    fuera = ep.dir / "comics" / "personajes.json"
    fuera.parent.mkdir(parents=True, exist_ok=True)
    fuera.write_text(json.dumps(salida, ensure_ascii=False, indent=2), encoding="utf-8")
    return salida
