"""Etapa diaria del cómic: guion verificado -> libro comics.v2 -> QC -> Facebook.

Pedido del dueño (2026-11-07): la fábrica de cómics se conecta al ciclo diario y
publica en Facebook. Se mantiene la regla del diseño: corre después del video y
aislada; cualquier fallo se reporta y el video ya publicado no se toca.
"""
from __future__ import annotations

from ..episode import Episode
from . import habilitado
from .adaptar_guion import adaptar, guardar
from .componer import componer
from .imagen import generar
from .metricas import registrar
from .personajes import fichas
from .publicar import publicar_facebook
from .qc import ejecutar


def producir(ep: Episode, publicar: bool = True) -> dict:
    """Genera el cómic del episodio y, si el QC aprueba, lo publica en Facebook."""
    if not habilitado():
        return {"status": "apagado"}

    datos = adaptar(ep)
    fichas_map = fichas(ep, datos)
    rutas = generar(ep, datos, fichas_map)
    guardar(ep, datos)  # persiste procedencia_imagen de cada viñeta
    artefactos = componer(ep, datos, rutas)
    problemas = ejecutar(ep, datos, rutas, artefactos)
    if problemas:
        registrar(ep, datos, artefactos, qc_ok=False,
                  extra={"problemas": problemas[:8]})
        return {"status": "qc_fallo", "problemas": problemas}

    registrar(ep, datos, artefactos, qc_ok=True)
    salida = {"status": "producido",
              "vinetas": len(datos.get("paneles") or []),
              "paginas": len(artefactos.get("paginas") or [])}
    if publicar:
        salida["publicacion"] = publicar_facebook(ep, datos)
    return salida
