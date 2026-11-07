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

from . import config, huellas
from .episode import Episode, STAGES
from .gates import GateFailure, run_all_gates
from .stages import (captacion, descubrir, derivados, guion, keyframes, narracion,
                     publicacion, research, tele_revision, collage)


PRODUCCION_LOCK_MAX_S = int(os.environ.get("PRODUCCION_LOCK_MAX_S", "14400"))


def _lock_produccion() -> Path:
    return config.STATE / "produccion.lock"


def _lock_vivo(ruta: Path) -> bool:
    """Lock con dueño vivo y reciente. Un lock huérfano (proceso muerto) no bloquea."""
    try:
        datos = json.loads(ruta.read_text(encoding="utf-8"))
        pid = int(datos.get("pid") or 0)
        edad = time.time() - float(datos.get("ts_epoch") or 0)
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        try:
            edad = time.time() - ruta.stat().st_mtime
            pid = 0
        except OSError:
            return False
    if edad >= PRODUCCION_LOCK_MAX_S:
        return False
    if pid <= 0:
        return True
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _tomar_lock_produccion() -> bool:
    """Un solo `auto` a la vez, venga de factoryd, del cron o de una corrida manual."""
    config.STATE.mkdir(parents=True, exist_ok=True)
    ruta = _lock_produccion()
    for _ in range(2):
        try:
            fd = os.open(ruta, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        except FileExistsError:
            if _lock_vivo(ruta):
                return False
            try:
                ruta.unlink()
            except FileNotFoundError:
                pass
            continue
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump({"pid": os.getpid(),
                       "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
                       "ts_epoch": time.time()}, fh)
        return True
    return False


def _soltar_lock_produccion() -> None:
    ruta = _lock_produccion()
    try:
        datos = json.loads(ruta.read_text(encoding="utf-8"))
        if int(datos.get("pid") or 0) != os.getpid():
            return
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        pass
    ruta.unlink(missing_ok=True)


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
        from pipeline import ideas
        print("  fábrica: ranking vencido sin ideas verificadas — genero un lote nuevo y verifico fuentes")
        cards = ideas.generar(cantidad=8)
        verificadas = [c for c in cards
                       if str(c.get("estado") or "").strip().lower() == "verificada"]
    if not verificadas:
        raise SystemExit(
            "auto: 0 ideas verificadas en el ranking actualizado (mínimo 2 fuentes por afirmación); "
            "se detiene sin publicar afirmaciones sin respaldo")

    def _num(c, clave, default=0.0):
        try:
            return float(c.get(clave, default) or default)
        except (TypeError, ValueError):
            return default

    def _clave(c):
        return (_num(c, "score"), -int(_num(c, "rank", 99)))

    # Anti-repetición de HISTORIAS: el gate 4 compara texto, y acá se frena la misma
    # historia contada con otras palabras (huella temática contra registry/published.jsonl).
    # Sin esto, un canal que funcionó con "midterms" repite el tema hasta canibalizarse.
    def sin_contar(ordenadas: list[dict]) -> tuple[dict | None, list]:
        elegida, descartadas = None, []
        for candidata in ordenadas:
            texto = " ".join(str(candidata.get(clave) or "")
                             for clave in ("titulo", "gancho", "historia", "resumen"))
            # Un proyecto con ese slug ya existe: `auto` se negaría a crearlo y la
            # fábrica quedaría en un bucle de "episodio ya existe". Se descarta y se
            # pasa a la siguiente idea verificada (el proyecto previo queda intacto).
            posible = _slugify(str(candidata.get("titulo") or "").split(",")[0][:48])
            if (config.PROJECTS / posible).exists():
                descartadas.append((texto[:60], posible, 1.0))
                continue
            contada, slug_previo, similitud = huellas.ya_contada(texto)
            if contada:
                descartadas.append((texto[:60], slug_previo, similitud))
                continue
            elegida = candidata
            break
        return elegida, descartadas

    ordenadas = sorted(verificadas, key=_clave, reverse=True)
    elegida, descartadas = sin_contar(ordenadas)
    if elegida is None:
        # El ranking del día ya está todo contado (o las carpetas de episodios anteriores lo
        # taparon). Sin ideas nuevas la fábrica no produce episodio: se generan y se vuelven
        # a filtrar acá mismo, antes de rendirse.
        from pipeline import ideas
        print("  fábrica: las ideas de hoy ya están contadas — genero un lote nuevo y lo verifico")
        nuevas = [c for c in ideas.generar(cantidad=8)
                  if str(c.get("estado") or "").strip().lower() == "verificada"]
        if nuevas:
            ordenadas = sorted(nuevas, key=_clave, reverse=True)
            elegida, descartadas = sin_contar(ordenadas)
    if elegida is None:
        raise SystemExit(
            f"auto: ni las {len(verificadas)} ideas de hoy ni las {len(ordenadas)} nuevas superan "
            f"la huella temática del canal (umbral {huellas.UMBRAL_HISTORIA}). Nada nuevo que "
            "producir; no se publica una historia repetida.")
    for titulo_repetido, slug_previo, similitud in descartadas:
        print(f"  fábrica: descartada por repetida ({similitud} con {slug_previo}): {titulo_repetido}")
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
        info_render = keyframes.render(ep, modelo=args.modelo,
                                       reciclar=bool(getattr(args, "reciclar_imagenes", False)))
        keyframes_final = ep.dir / "renders" / info_render["archivo"]
        derivados._derivar_keyframe(ep, keyframes_final)
        # Piezas de captación del día (trailers A/B + historieta) sobre el capítulo ya renderizado.
        import pipeline.stages.captacion as captacion
        try:
            captacion.derivar_captacion(ep)
        except SystemExit as cta_err:
            print(f"  captacion no generó piezas: {cta_err}")
        publicacion.checklist(ep)
        from pipeline.stages import tele_revision
        if args.no_publicar:
            # El flag existía pero no se leía: --no-publicar publicaba igual.
            print("  --no-publicar: nada sale al mundo, sólo checklist y revisión")
            publicacion.publicar_automatico(ep, no_publish=True)
            tele_revision.enviar_para_aprobacion(ep)
            estado_registro = "revision_pendiente"
        elif config.auto_publish() or tele_revision.autonomia_total():
            # Decisión del dueño 2026-11-05 (.env AUTO_PUBLISH=true): la fábrica publica sola.
            # La barrera ya no es "paso por Telegram" sino el QC medido del máster y el gate
            # de título; el aviso por Telegram sigue yendo, pero como registro de lo publicado.
            print("  AUTO_PUBLISH ON: publico YouTube + Facebook por Zernio (QC del máster aprobado)")
            resultado = publicacion.publicar_automatico(ep, no_publish=False)
            tele_revision.notificar_autonomia(ep.slug)
            if resultado.get("status"):
                estado_registro = "revision_pendiente"   # QC o título lo frenaron: no se publicó nada
                tele_revision.enviar_para_aprobacion(ep)  # y el dueño sí lo ve antes de decidir
            elif resultado.get("exitosas") == resultado.get("plan"):
                estado_registro = "producido_autopublicado"
            else:
                estado_registro = "producido_publicacion_parcial"
                tele_revision.enviar_para_aprobacion(ep)
        else:
            publicacion.publicar_automatico(ep, no_publish=True)
            tele_revision.enviar_para_aprobacion(ep)
            estado_registro = "revision_pendiente"
        publicacion.registrar(ep, estado=estado_registro)
        # Cómic diario (pedido del dueño 2026-11-07): se produce DESPUÉS del video y se
        # publica en Facebook. Va aislado: si falla, el video ya salió y la corrida no cambia.
        try:
            from pipeline.comics import ciclo as comics
            comic = comics.producir(ep, publicar=not args.no_publicar)
            detalle = f" · {comic['paginas']} páginas" if comic.get("paginas") else ""
            pub = comic.get("publicacion") or {}
            if pub.get("status"):
                detalle += f" · facebook: {pub['status']}"
            print(f"  comics: {comic.get('status')}{detalle}")
        except (Exception, SystemExit) as exc:
            print(f"  comics NO publicado ({str(exc)[:180]}): el video sigue su ruta")
        print(f"\nTOTAL: {round(time.time() - t0)}s. Checklist en {ep.dir}/publicacion/checklist.md")
        print("Paquete y resultado enviados a Telegram; la publicación requiere ejecutar `auto` sin --no-publicar.")
        return
    except (Exception, SystemExit) as exc:
        motivo = str(exc)[:500]
        # No todo fallo es de keyframes: antes cualquier excepción (research, guion,
        # narración) se reportaba como "keyframe bloqueado" y dejaba evidencia falsa.
        etapa_en_curso = ""
        try:
            estados = (ep.read_state().get("stage_status") or {})
            for nombre in ("keyframes", "guion", "narracion", "research", "visuales", "montaje"):
                if estados.get(nombre) not in ("done", "gate_pass", "pending", None):
                    etapa_en_curso = nombre
                    break
        except Exception:
            pass
        if etapa_en_curso == "keyframes" or "keyframe bloqueado" in motivo.lower():
            # La ruta oficial es keyframe. Si Flux está sin cuota, se bloquea con evidencia;
            # no se entrega un avatar ni un video de fotos reales como si fuera el stickman.
            print(f"  keyframe BLOQUEADO ({motivo[:180]}): no se genera avatar ni fotos reales")
            ep.write_json("keyframe_bloqueado.json", {
                "motivo": motivo, "motor_esperado": "keyframe_stickman",
                "fallback_usado": None,
                "nota": "Reintentar cuando Workers AI tenga cuota; no sustituir por avatar/fotos.",
            })
            ep.set_stage("keyframes", "blocked")
            raise SystemExit(f"keyframe bloqueado: {motivo}") from exc
        print(f"  producción BLOQUEADA ({motivo[:180]})")
        raise


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="pipeline.run")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("auto"); sp.add_argument("--historia", nargs="?", default=None,
                                                 help="tema explícito; si falta, la fábrica elijo el suyo del ranking verificado del día")
    sp.add_argument("--slug"); sp.add_argument("--angulo"); sp.add_argument("--no-publicar", action="store_true")
    sp.add_argument("--motor", choices=["keyframe"], default="keyframe",
                    help="único motor: keyframe = imágenes generadas + cámara 2.5D (stickman)")
    sp.add_argument("--modelo", default="flux",
                    choices=["flux", "pollinations", "hf-space", "gemini-imagen"],
                    help="modelo de imagen: flux (Cloudflare primario con cascada de fallbacks)")
    sp.add_argument("--categoria", choices=sorted(__import__("pipeline.nichos", fromlist=["CATEGORIAS"]).CATEGORIAS),
                    help="categoría editorial; auto conserva research/urls.txt curado al crear el episodio")
    sp.add_argument("--reciclar-imagenes", action="store_true",
                    help="opt-in: permite reciclar imágenes similares en lugar de generar nuevas")

    sub.add_parser("escuchar-telegram",
                   help="long-polling: reacciona a los botones de revisión y a /aprobar /rechazar /estado /precio")
    sub.add_parser("medir",
                   help="trae la analítica REAL de cada post publicado (Zernio) a state/metricas.jsonl")
    sub.add_parser("aprender",
                   help="convierte state/metricas.jsonl en pesos + UN cambio para el próximo episodio")
    sp = sub.add_parser("diario",
                        help="el ciclo completo del día: medir -> aprender -> producir -> entregar")
    sp.add_argument("--no-publicar", action="store_true",
                    help="no sube nada a YouTube/Facebook; igual manda el paquete a Telegram")
    sp.add_argument("--reciclar-imagenes", action="store_true",
                    help="opt-in: permite reciclar imágenes similares en la producción diaria")
    sp = sub.add_parser("nuevo"); sp.add_argument("slug"); sp.add_argument("--titulo", required=True)
    for name in ("research", "factcheck", "narrar", "keyframes", "preview",
                 "derivados", "captacion", "publicar",
                 "enviar", "registrar", "gates", "estado",
                 "collage-propuesto", "collage-aprobar", "collage-render"):
        sp = sub.add_parser(name); sp.add_argument("slug")
        if name == "collage-aprobar":
            sp.add_argument("indices", nargs="*", type=int,
                            help="índices de recortes de cutout_propuesta.json a aprobar "
                                 "(vacío = todos)")
        if name == "keyframes":
            sp.add_argument("--modelo", default="flux",
                            choices=["flux", "pollinations", "hf-space", "gemini-imagen"],
                            help="modelo de imagen: flux (Cloudflare primario con cascada de fallbacks)")
            sp.add_argument("--contacto", action="store_true",
                            help="sólo beats + keyframes + hoja de contactos, sin renderizar")
            sp.add_argument("--forzar", action="store_true",
                            help="redrawea los keyframes y re-planifica los beats")
            sp.add_argument("--reciclar-imagenes", action="store_true",
                            help="opcional: permite reutilizar imágenes similares de la biblioteca")
            sp.add_argument("--renovar-imagenes", nargs="*", type=int, default=[], metavar="BEAT",
                            help="genera imágenes nuevas sólo para esos índices de beat")
        if name == "preview":
            sp.add_argument("--modelo", default="flux")
            sp.add_argument("--segundos", type=float, default=35.0)
            sp.add_argument("--reciclar-imagenes", action="store_true")
            sp.add_argument("--renovar-imagenes", nargs="*", type=int, default=[], metavar="BEAT")
    sp = sub.add_parser("guion"); sp.add_argument("slug"); sp.add_argument("--angulo")

    args = p.parse_args(argv)

    if args.cmd == "auto":
        if not _tomar_lock_produccion():
            print("auto: ya hay una producción en curso; no se lanza una segunda "
                  "(evita episodios y publicaciones duplicadas)")
            return 1
        try:
            run_auto(args)
        finally:
            _soltar_lock_produccion()
        return 0

    if args.cmd == "medir":
        from . import metricas      # import tardío: métricas sólo pesa cuando se pide
        filas = metricas.medir()
        print(json.dumps(metricas.medianas(filas), indent=2, ensure_ascii=False))
        return 0

    if args.cmd == "aprender":
        from . import aprendizaje
        print(json.dumps(aprendizaje.aprender(), indent=2, ensure_ascii=False)[:2000])
        return 0

    if args.cmd == "diario":
        from . import diario        # diario importa este módulo: sería círculo si fuera arriba
        return diario.correr_dia(publicar=not args.no_publicar,
                                 reciclar=args.reciclar_imagenes)

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
                                               solo_contacto=bool(args.contacto),
                                               reciclar=bool(args.reciclar_imagenes),
                                               renovar=set(args.renovar_imagenes)),
        "preview": lambda: keyframes.preview(ep, modelo=args.modelo, segundos=args.segundos,
                                              reciclar=bool(args.reciclar_imagenes),
                                              renovar=set(args.renovar_imagenes)),
        "derivados": lambda: derivados.derivar(ep),
        "captacion": lambda: captacion.derivar_captacion(ep),
        "publicar": lambda: publicacion.checklist(ep),
        # envio del canal: VIDEO + TITULO + SUBTITULO + botones Aprobar/Reprobar
        "enviar": lambda: tele_revision.enviar_para_aprobacion(ep),
        "registrar": lambda: publicacion.registrar(ep, estado=args.__dict__.get("estado", "producido")),
        "collage-propuesto": lambda: collage.proponer(ep),
        "collage-aprobar": lambda: collage.aprobar(ep,
                                                    indices=getattr(args, "indices", [])),
        "collage-render": lambda: collage.render(ep),
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
