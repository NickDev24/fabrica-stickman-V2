"""El ciclo diario autónomo: medir -> aprender -> producir -> entregar.

Es el latido que pidió el dueño (2026-11-05): la fábrica produce un episodio por día,
estudia los números de los anteriores y evita repetir historias. Este módulo NO decide
si se publica: respeta `AUTO_PUBLISH` del .env y el gate del dueño
(`tele_revision.autonomia_total()`), y nunca toca el presupuesto de Gemini.

Programación (una línea, sin cron ni dependencias nuevas):

    crontab -e
    17 6 * * * cd /home/facu/Documentos/Documentales-Generator && .venv/bin/python -m pipeline.run diario >> state/diario.log 2>&1

`state/diario.lock` corta un corrida si la anterior todavía está viva: dos `auto` a la
vez compiten por el render y por la cuota de Workers AI.
"""
from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone

from . import config

LOCK = config.STATE / "diario.lock"
HISTORIAL = config.STATE / "diario.jsonl"
# Si factoryd (Docker 24/7) está produciendo, este ciclo cron no lanza un segundo
# `auto`: dos productores compiten por el render y la cuota de Workers AI.
FACTORYD_LOG_MAX_S = int(os.environ.get("FACTORYD_LOG_MAX_S", "900"))
# Una corrida que dura más de esto se considera colgada (el render de un episodio completo
# medido: ~25 min en este equipo). Se puede retomar con el comando por etapa.
LOCK_MAX_S = int(os.environ.get("DIARIO_LOCK_MAX_S", "5400"))


def _libre() -> bool:
    if not LOCK.exists():
        return True
    try:
        datos = json.loads(LOCK.read_text(encoding="utf-8"))
        pid = int(datos.get("pid") or 0)
        os.kill(pid, 0)                     # ¿existe el proceso que la tomó?
        vivo = (time.time() - float(datos.get("ts_epoch") or 0)) < LOCK_MAX_S
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        vivo = (time.time() - LOCK.stat().st_mtime) < LOCK_MAX_S
        return not vivo
    return not vivo


def _tomar_lock() -> None:
    config.STATE.mkdir(parents=True, exist_ok=True)
    LOCK.write_text(json.dumps({"pid": os.getpid(),
                                 "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                                 "ts_epoch": time.time()}), encoding="utf-8")


def _soltar_lock() -> None:
    LOCK.unlink(missing_ok=True)


def _argv_auto(publicar: bool, reciclar: bool) -> list[str]:
    """Argumentos de `auto`. La bandera del CLI NO puede quedar ignorada."""
    argv = ["auto"] if publicar else ["auto", "--no-publicar"]
    if reciclar:
        argv.append("--reciclar-imagenes")
    return argv


def _factoryd_vivo() -> bool:
    """¿El daemon 24/7 está corriendo y escribiendo logs hace poco?

    `factoryd.json` sobrevive reinicios; por eso se exige además un log fresco.
    Así el cron queda como respaldo cuando Docker está caído o pausado.
    """
    try:
        ctrl = json.loads((config.STATE / "factoryd.json").read_text(encoding="utf-8"))
        if str(ctrl.get("modo") or "") not in ("corriendo", "deteniendo"):
            return False
        log = config.STATE / "logs" / "factoryd.log"
        return log.is_file() and (time.time() - log.stat().st_mtime) < FACTORYD_LOG_MAX_S
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return False


def _paso(nombre: str, fn):
    """Cada etapa del ciclo registra su resultado; un fallo no borra lo aprendido antes."""
    try:
        resultado = fn()
        print(f"  diario[{nombre}]: OK")
        return {"paso": nombre, "estado": "ok", "resultado": resultado}
    except SystemExit as exc:                      # los gates cortan con SystemExit
        print(f"  diario[{nombre}]: BLOQUEADO -> {exc}")
        return {"paso": nombre, "estado": "bloqueado", "motivo": str(exc)[:300]}
    except Exception as exc:  # noqa: BLE001 — un día fallido no puede romper el ciclo
        print(f"  diario[{nombre}]: ERROR {exc.__class__.__name__}: {exc}")
        return {"paso": nombre, "estado": "error", "motivo": str(exc)[:300]}


def correr_dia(publicar: bool = False, reciclar: bool = False) -> int:
    """Un día de fábrica. Devuelve 0 si produjo y entregó, 1 si el ciclo se frenó."""
    if not _libre():
        print("diario: hay una corrida en curso (state/diario.lock); salto este día")
        return 1
    _tomar_lock()
    registro = {"ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "publicar": False, "publicar_solicitado": publicar, "pasos": []}
    try:
        if _factoryd_vivo():
            registro["estado"] = "delegado"
            print("diario: factoryd 24/7 está activo; este ciclo no duplica la producción")
            return 0
        from . import aprendizaje, metricas, run

        # 1. métricas REALES de lo publicado (si no hay datos, aprendizaje no inventa nada)
        registro["pasos"].append(_paso("medir", metricas.medir))
        # 2. convertir métricas en los números del próximo episodio
        registro["pasos"].append(_paso("aprender", aprendizaje.aprender))
        # 3. producir y entregar (auto ya manda el paquete a Telegram al final).
        # `diario` sin --no-publicar publica si AUTO_PUBLISH/autonomía lo permiten;
        # con el daemon 24/7 activo, el ciclo se delega arriba y no compite.
        argv = _argv_auto(publicar, reciclar)

        def producir() -> int:
            rc = run.main(argv)
            if rc:
                raise SystemExit(f"auto no ejecutó la producción (rc={rc})")
            return rc

        registro["pasos"].append(_paso("producir", producir))
        registro["estado"] = ("ok" if all(p["estado"] == "ok" for p in registro["pasos"])
                              else "frenado")
    finally:
        _soltar_lock()
        with HISTORIAL.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(registro, ensure_ascii=False) + "\n")
    print(f"diario: {registro['estado']} -> state/diario.jsonl")
    return 0 if registro["estado"] == "ok" else 1
