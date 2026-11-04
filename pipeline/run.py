"""CLI del pipeline de Pulso Curioso — producción automática y revisión por Telegram.

  python3 -m pipeline.run auto --historia "el asteroide que apago a los dinosaurios"

`auto` ejecuta la producción hasta entregar el paquete para revisión: elige slug y título, descubrimiento de fuentes,
research + fact-check (gate 1), ángulo narrativo (gate 4), guion, narración Piper
(gates 2 y 3), montaje + QC, derivados multi-formato, checklist con fuentes y flag
sintético, envío por Telegram y registro anti-duplicado. La publicación en YouTube o
Facebook requiere `AUTO_PUBLISH=true` explícito; por defecto se entrega para revisión humana.

Comandos por etapa (para re-corridas o revisión puntual):
  nuevo <slug> --titulo "..." | research | factcheck | guion [--angulo] | narrar
  avatar <slug> [--glb Ruta] [--segundos N] [--reanudar] | montar | derivados | publicar |
  enviar | registrar <slug> | gates | estado

`avatar` es la etapa de actuación 3D: timeline del director + visemas de Rhubarb -> frames
headless (960x540, 24 fps) -> upscale 720p + subtítulos ASS + mezcla normalizada a -16 LUFS.
Renders de 30 s ≈ 7 min en esta caja; `--reanudar` conserva los frames ya escritos.
Orquestación por skills (decide qué skill usar y reanuda por artefactos):
  python3 -c "from factory import orchestrador as o; o.correr(o.Episode('<slug>'))"
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

from . import config
from .episode import Episode, STAGES
from .gates import GateFailure, run_all_gates
from .stages import (avatar, descubrir, derivados, guion, keyframes, montaje, narracion,
                     publicacion, research, visuales)


def _slugify(texto: str) -> str:
    return re.sub(r"[^a-z0-9-]", "-", re.sub(r"\s+", "-", texto.lower().strip()))[:60].strip("-")


def run_auto(args) -> None:
    historia = args.historia
    slug = args.slug or _slugify(historia.split(",")[0][:48])
    if (config.PROJECTS / slug).exists():
        raise SystemExit(f"el episodio {slug!r} ya existe; pasá --slug distinto o re-usable con sus comandos por etapa")
    t0 = time.time()
    categoria = getattr(args, "categoria", "") or ""
    ep = Episode.create(slug, historia[0].upper() + historia[1:], categoria=categoria)
    print(f"== episodio {slug} ==")
    config.load_env()
    if categoria:
        # Evita que el descubrimiento autónomo sobrescriba fuentes oficiales precuradas.
        paquete = config.PROJECTS / "_fuentes" / f"{slug}.txt"
        if not paquete.is_file():
            raise SystemExit(f"con --categoria falta el paquete curado {paquete.relative_to(config.ROOT)}")
        (ep.dir / "research" / "urls.txt").write_text(paquete.read_text(encoding="utf-8"), encoding="utf-8")
    descubrir.descubrir(ep, historia) if not categoria else print("  fuentes institucionales curadas preservadas")
    research.research(ep)
    research.factcheck(ep)
    guion.guion(ep, args.angulo)
    narracion.narrar(ep)
    if args.motor != "keyframe":
        raise SystemExit("ruta de fotos reales deshabilitada: la fábrica produce con --motor keyframe "
                         "(stickman 4F). No se descargan imágenes de Wikimedia.")
    # El motor visual del formato viral: 1 imagen generada cada ~1,6 s con cámara encima.
    # Se fuerza el maestro keyframe: el avatar 3D queda como línea experimental aparte y
    # nunca reemplaza al stickman de Codex sin una decisión explícita.
    os.environ["KF_MASTER"] = "keyframe"
    try:
        info_render = keyframes.render(ep, modelo=args.modelo)
        keyframes_final = ep.dir / "renders" / info_render["archivo"]
        derivados._derivar_keyframe(ep, keyframes_final)
        publicacion.checklist(ep)
        publicacion.publicar_automatico(ep, no_publish=True)
        publicacion.enviar_telegram(ep)
        publicacion.registrar(ep, estado="producido")
        print(f"\nTOTAL: {round(time.time() - t0)}s. Checklist en {ep.dir}/publicacion/checklist.md")
        print("Revisá el paquete recibido por Telegram antes de publicarlo manualmente.")
        return
    except (Exception, SystemExit) as exc:
        # La ruta oficial es keyframe. Si Flux está sin cuota, se bloquea con evidencia;
        # no se entrega un avatar ni un video de fotos reales como si fuera el stickman.
        motivo = str(exc)[:500]
        print(f"  keyframe BLOQUEADO ({motivo[:180]}): no se genera avatar ni fotos reales")
        ep.write_json("keyframe_bloqueado.json", {
            "motivo": motivo, "motor_esperado": "keyframe_stickman",
            "fallback_usado": None,
            "nota": "Reintentar cuando Workers AI tenga cuota; no sustituir por avatar/fotos.",
        })
        ep.set_stage("keyframes", "blocked")
        raise SystemExit(f"keyframe bloqueado: {motivo}") from exc


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="pipeline.run")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("auto"); sp.add_argument("--historia", required=True)
    sp.add_argument("--slug"); sp.add_argument("--angulo"); sp.add_argument("--no-publicar", action="store_true")
    sp.add_argument("--motor", choices=["keyframe", "montaje"], default="keyframe",
                    help="keyframe = imágenes generadas + cámara 2.5D (motor viral del formato)")
    sp.add_argument("--modelo", default="flux", help="modelo de imagen de Workers AI")
    sp.add_argument("--categoria", choices=sorted(__import__("pipeline.nichos", fromlist=["CATEGORIAS"]).CATEGORIAS),
                    help="categoría editorial; auto conserva research/urls.txt curado al crear el episodio")

    sp = sub.add_parser("nuevo"); sp.add_argument("slug"); sp.add_argument("--titulo", required=True)
    for name in ("research", "factcheck", "visuales", "narrar", "avatar", "montar", "keyframes", "preview",
                 "derivados", "publicar",
                 "enviar", "registrar", "gates", "estado"):
        sp = sub.add_parser(name); sp.add_argument("slug")
        if name == "avatar":
            sp.add_argument("--glb", help="GLB del personaje (default: state/personajes o assets/**/*.glb)")
            sp.add_argument("--segundos", type=float, help="render only this many seconds (prueba corta)")
            sp.add_argument("--reanudar", action="store_true",
                            help="conserva los frames ya renderizados y sigue desde ahí")
        if name == "keyframes":
            sp.add_argument("--modelo", default="flux", help="modelo de imagen de Workers AI")
            sp.add_argument("--contacto", action="store_true",
                            help="sólo beats + keyframes + hoja de contactos, sin renderizar")
            sp.add_argument("--forzar", action="store_true",
                            help="redrawea los keyframes y re-planifica los beats")
        if name == "preview":
            sp.add_argument("--modelo", default="flux")
            sp.add_argument("--segundos", type=float, default=35.0)
    sp = sub.add_parser("guion"); sp.add_argument("slug"); sp.add_argument("--angulo")

    args = p.parse_args(argv)

    if args.cmd == "auto":
        run_auto(args)
        return 0

    if args.cmd == "nuevo":
        ep = Episode.create(args.slug, args.titulo)
        print(f"episodio creado: {ep.dir}")
        return 0

    ep = Episode(args.slug)
    dispatch = {
        "research": lambda: research.research(ep),
        "factcheck": lambda: research.factcheck(ep),
        "visuales": lambda: visuales.generar(ep),
        "guion": lambda: guion.guion(ep, args.angulo),
        "narrar": lambda: narracion.narrar(ep),
        "avatar": lambda: avatar.render(ep, glb=Path(args.glb) if getattr(args, "glb", None) else None,
                                        reanudar=bool(getattr(args, "reanudar", False)),
                                        forzar_frames=(int(args.segundos * avatar.FPS) + 1
                                                       if getattr(args, "segundos", None) else None)),
        "montar": lambda: montaje.montar(ep),
        "keyframes": lambda: keyframes.render(ep, modelo=args.modelo,
                                               forzar=bool(args.forzar),
                                               solo_contacto=bool(args.contacto)),
        "preview": lambda: keyframes.preview(ep, modelo=args.modelo, segundos=args.segundos),
        "derivados": lambda: derivados.derivar(ep),
        "publicar": lambda: publicacion.checklist(ep),
        "enviar": lambda: publicacion.enviar_telegram(ep),
        "registrar": lambda: publicacion.registrar(ep, estado=args.__dict__.get("estado", "producido")),
        "gates": lambda: print(run_all_gates(ep.dir)),
        "estado": lambda: print(ep.read_state()["stage_status"]),
    }
    try:
        dispatch[args.cmd]()
        return 0
    except GateFailure as g:
        print(f"\nGATE {g.gate.upper()} BLOCKÓ EL EPISODIO:\n  " + "\n  ".join(g.reasons))
        return 2
    except Exception as e:
        print(f"\nERROR en {args.cmd}: {e}", file=sys.stderr)
        raise


if __name__ == "__main__":
    sys.exit(main())
