"""CLI del pipeline de Pulso Curioso — producción automática y revisión por Telegram.

  python3 -m pipeline.run auto --historia "el asteroide que apago a los dinosaurios"

`auto` ejecuta la producción hasta entregar el paquete para revisión: elige slug y título, descubrimiento de fuentes,
research + fact-check (gate 1), ángulo narrativo (gate 4), guion, narración Piper
(gates 2 y 3), montaje + QC, derivados multi-formato, checklist con fuentes y flag
sintético, envío por Telegram y registro anti-duplicado. La publicación en YouTube o
Facebook requiere `AUTO_PUBLISH=true` explícito; por defecto se entrega para revisión humana.

Comandos por etapa (para re-corridas o revisión puntual):
  nuevo <slug> --titulo "..." | research | factcheck | guion [--angulo] | narrar
  keyframes <slug> [--contacto|--forzar] | derivados | publicar |
  enviar | registrar <slug> | gates | estado

Rutas DESCARTADAS por decisión del dueño (ya no son comandos válidos): `avatar`
(3D GLB con ojos y lipsync), `visuales` (fotos reales de Wikimedia) y `montar`
(Ken Burns sobre fotos). La fábrica sólo produce videos stickman keyframe.
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
from .stages import (captacion, descubrir, derivados, guion, keyframes, narracion,
                     publicacion, research, tele_revision)


def _slugify(texto: str) -> str:
    return re.sub(r"[^a-z0-9-]", "-", re.sub(r"\s+", "-", texto.lower().strip()))[:60].strip("-")


def _historia_del_dia() -> tuple[str, str]:
    """Autonomía total: la fábrica se elige SOLA la idea del día.

    Orden: ranking existente en state/ideas.json (generado hoy por tendencias +
    fact-check) -> si no existe, ideas.generar() -> gana la de mejor puntaje;
    a igualdad, la de rank menor. Todo queda auditable: el registro de la idea
    elegida está en state/ideas.json bajo 'elegido_auto'.
    """
    config.load_env()
    ruta = config.STATE / "ideas.json"
    cards: list[dict] = []
    try:
        crudo = json.loads(ruta.read_text(encoding="utf-8"))
        cards = crudo if isinstance(crudo, list) else (
            crudo.get("ideas") or crudo.get("cards") or [])
    except Exception:
        cards = []
    if not cards:
        from pipeline import ideas
        print("  fábrica: no hay ranking del día — genero ideas y verifico antes de decidir")
        cards = ideas.generar(cantidad=6)
    if not cards:
        raise SystemExit("auto: la fábrica no pudo generar ninguna idea hoy")
    # la fábrica NUNCA produce contenido sin fuentes verificadas
    verificadas = [c for c in cards
                   if str(c.get("estado") or "").strip().lower() == "verificada"]
    if not verificadas:
        raise SystemExit(
            "auto: 0 ideas verificadas hoy (mínimo 2 fuentes por afirmación) — "
            "no se produce contenido sin fuentes; revisar tendencias/descubrir")

    def _num(c, clave, default=0.0):
        try:
            return float(c.get(clave, default) or default)
        except (TypeError, ValueError):
            return default

    def _clave(c):
        return (_num(c, "score"), -int(_num(c, "rank", 99)))

    elegida = sorted(verificadas, key=_clave, reverse=True)[0]
    titulo = str(elegida.get("titulo") or elegida.get("gancho") or "").strip()
    if not titulo:
        raise SystemExit("auto: la idea elegida no tiene título utilizable")
    categoria = str(elegida.get("categoria") or elegida.get("nicho") or "")
    try:
        crudo = json.loads(ruta.read_text(encoding="utf-8")) if ruta.exists() else {}
        if not isinstance(crudo, dict):
            crudo = {"ideas": crudo}
        crudo["elegido_auto"] = {"titulo": titulo, "categoria": categoria,
                                 "rank": elegida.get("rank"), "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
                                 "fuente": "ideas.json (ranking verificado del día)"}
        ruta.write_text(json.dumps(crudo, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass
    print(f"  fábrica: idea elegida por ella misma -> {titulo}")
    if categoria:
        print(f"  fábrica: nicho -> {categoria}")
    return titulo, categoria


def run_auto(args) -> None:
    historia = args.historia
    categoria_autonoma = ""
    if not historia:
        historia, categoria_autonoma = _historia_del_dia()
    slug = args.slug or _slugify(historia.split(",")[0][:48])
    if (config.PROJECTS / slug).exists():
        raise SystemExit(f"el episodio {slug!r} ya existe; pasá --slug distinto o re-usable con sus comandos por etapa")
    t0 = time.time()
    categoria = getattr(args, "categoria", "") or categoria_autonoma
    ep = Episode.create(slug, historia[0].upper() + historia[1:], categoria=categoria)
    print(f"== episodio {slug} ==")
    config.load_env()
    categoria_curada = bool(getattr(args, "categoria", ""))
    if categoria_curada:
        # Evita que el descubrimiento autónomo sobrescriba fuentes oficiales precuradas.
        paquete = config.PROJECTS / "_fuentes" / f"{slug}.txt"
        if not paquete.is_file():
            raise SystemExit(f"con --categoria falta el paquete curado {paquete.relative_to(config.ROOT)}")
        (ep.dir / "research" / "urls.txt").write_text(paquete.read_text(encoding="utf-8"), encoding="utf-8")
    descubrir.descubrir(ep, historia) if not categoria_curada else print("  fuentes institucionales curadas preservadas")
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
        # Piezas de captación del día (trailers A/B + historieta) sobre el capítulo ya renderizado.
        import pipeline.stages.captacion as captacion
        try:
            captacion.derivar_captacion(ep)
        except SystemExit as cta_err:
            print(f"  captacion no generó piezas: {cta_err}")
        publicacion.checklist(ep)
        publicacion.publicar_automatico(ep, no_publish=True)
        from pipeline.stages import tele_revision
        if tele_revision.autonomia_total():
            # autonomía desbloqueada por una aprobación previa del dueño:
            # publica y avisa por Telegram, sin pedir revisión
            print("  autonomía total: publico sin revisión (desbloqueada por tu aprobación)")
            os.environ["AUTO_PUBLISH"] = "true"
            publicacion.publicar_automatico(ep, no_publish=False, aprobado="user")
            tele_revision.notificar_autonomia(ep.slug)
            estado_registro = "producido_autopublicado"
        else:
            tele_revision.enviar_para_aprobacion(ep)
            estado_registro = "revision_pendiente"
        publicacion.registrar(ep, estado=estado_registro)
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

    sp = sub.add_parser("auto"); sp.add_argument("--historia", nargs="?", default=None,
                                                 help="tema explícito; si falta, la fábrica elijo el suyo del ranking verificado del día")
    sp.add_argument("--slug"); sp.add_argument("--angulo"); sp.add_argument("--no-publicar", action="store_true")
    sp.add_argument("--motor", choices=["keyframe"], default="keyframe",
                    help="único motor: keyframe = imágenes generadas + cámara 2.5D (stickman)")
    sp.add_argument("--modelo", default="flux", choices=["flux", "gemini-imagen"],
                    help="modelo de imagen de Workers AI (único admitido: flux)")
    sp.add_argument("--categoria", choices=sorted(__import__("pipeline.nichos", fromlist=["CATEGORIAS"]).CATEGORIAS),
                    help="categoría editorial; auto conserva research/urls.txt curado al crear el episodio")

    sub.add_parser("escuchar-telegram",
                   help="long-polling: reacciona a los botones de revisión y a /aprobar /rechazar /estado /precio")
    sp = sub.add_parser("nuevo"); sp.add_argument("slug"); sp.add_argument("--titulo", required=True)
    for name in ("research", "factcheck", "narrar", "keyframes", "preview",
                 "derivados", "captacion", "publicar",
                 "enviar", "registrar", "gates", "estado"):
        sp = sub.add_parser(name); sp.add_argument("slug")
        if name == "keyframes":
            sp.add_argument("--modelo", default="flux", choices=["flux", "gemini-imagen"],
                            help="modelo de imagen de Workers AI (único admitido: flux)")
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

    if args.cmd == "escuchar-telegram":
        tele_revision.escuchar()
        return 0

    if args.cmd == "nuevo":
        ep = Episode.create(args.slug, args.titulo)
        print(f"episodio creado: {ep.dir}")
        return 0

    ep = Episode(args.slug)
    # Rutas de video NO-stickman (avatar 3D, fotos reales, Ken Burns) descartadas por el
    # dueño: no existen en este dispatch. La única ruta de render es `keyframes`.
    dispatch = {
        "research": lambda: research.research(ep),
        "factcheck": lambda: research.factcheck(ep),
        "guion": lambda: guion.guion(ep, args.angulo),
        "narrar": lambda: narracion.narrar(ep),
        "keyframes": lambda: keyframes.render(ep, modelo=args.modelo,
                                               forzar=bool(args.forzar),
                                               solo_contacto=bool(args.contacto)),
        "preview": lambda: keyframes.preview(ep, modelo=args.modelo, segundos=args.segundos),
        "derivados": lambda: derivados.derivar(ep),
        "captacion": lambda: captacion.derivar_captacion(ep),
        "publicar": lambda: publicacion.checklist(ep),
        # envio del canal: VIDEO + texto (titulo/subtitulo/guion/hashtags), sin adjuntos
        "enviar": lambda: publicacion.enviar_solo_video(ep),
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
