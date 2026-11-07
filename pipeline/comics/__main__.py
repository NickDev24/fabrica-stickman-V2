"""CLI de la extensión cómics — APAGADA por defecto.

python -m pipeline.comics <slug>            # construye adaptación + personajes
python -m pipeline.comics <slug> --render   # + imágenes de paneles (cuota flux)
python -m pipeline.comics <slug> --componer # + página vertical + carrusel + qc

Requiere COMICS_ENABLED=1 en .env (fase 5 del diseño). Nada aquí publica; la
publicación de cómics se validará aparte (fase 6).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import habilitado
from .adaptar_guion import adaptar, guardar
from ..episode import Episode
from .metricas import registrar
from .personajes import fichas


def _cargar_datos(ep: Episode) -> dict:
    p = ep.dir / "comics" / "guion_paneles.json"
    return json.loads(p.read_text(encoding="utf-8"))


def main(argv=None) -> int:
    ### apagado por defecto: interruptor explícito
    if not habilitado():
        print("comics: COMICS_ENABLED no está en 1 — la extensión está apagada por diseño "
              "(el video no se ve afectado)")
        return 2
    ap = argparse.ArgumentParser(prog="pipeline.comics")
    ap.add_argument("slug")
    ap.add_argument("--render", action="store_true", help="genera imágenes de paneles")
    ap.add_argument("--componer", action="store_true", help="página + carrusel + qc")
    ap.add_argument("--renovar", type=str, default="",
                    help="índices de panel a redraw (ej: 2,4)")
    args = ap.parse_args(argv)

    ep = Episode(args.slug)
    renovar = {int(x) for x in args.renovar.split(",") if x.strip().isdigit()}

    datos = adaptar(ep)
    fichas_map = fichas(ep, datos)
    print(f"  comics: {len(datos.get('paneles', []))} viñetas en "
          f"{len(datos.get('grillas', []))} páginas | "
          f"personajes: {[k for k in fichas_map if not k.startswith('__')]}")

    artefactos_extra = {}
    if args.render or args.componer:
        from .imagen import generar
        from .componer import componer
        from .qc import ejecutar
        rutas = generar(ep, datos, fichas_map, renovar=renovar)
        guardar(ep, datos)  # persiste procedencia_imagen de cada panel
        print(f"  comics: {len(rutas)} viñetas listas (el silencio es panel negro)")
        artefactos = componer(ep, datos, rutas)
        print(f"  comics: {len(artefactos['paginas'])} páginas de libro "
              f"+ {artefactos.get('chapter_vertical', Path('-')).name} + "
              f"carrusel {len(artefactos['carrusel'])} piezas")
        problemas = ejecutar(ep, datos, rutas, artefactos)
        if problemas:
            print("  comics QC BLOQUEA:")
            for p in problemas:
                print(f"    - {p}")
            return 1
        print("  comics QC: aprobado")
        artefactos_extra = artefactos
        if artefactos_extra:
            fila = registrar(ep, datos, artefactos_extra, qc_ok=True)
            print(f"  comics métricas: {fila['slug']} · {len(datos.get('paneles', []))} viñetas / "
                  f"{len(datos.get('grillas', []))} páginas -> state/metricas_comics.jsonl")
    return 0


if __name__ == "__main__":
    sys.exit(main())
