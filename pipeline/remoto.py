"""Render distribuido: los planos por beat (encodes ffmpeg independientes) en SSH.

Cada beat es un `k-XXX.mp4` aislado (zoompan sobre una imagen fija); eso permite
repartirlos entre los nodos del laboratorio y consolidar localmente. Dato medido
2026-11-04: 5 nodos vivos (manager1, lab, barto, debian, vps-amazon), 2 cores
c/u -> 10 cores contra los 2 del B950 (≈5x en la etapa de planos, que era la más
gruesa del master).

Diseño conservador: si un nodo falla o no tiene ffmpeg, sus beats vuelven al
render local — nunca se bloquea ni cambia la salida (misma línea de encode que
`keyframes._plano`, byte-por-byte idéntica tras `-vf`).
"""
from __future__ import annotations

import io
import os
import subprocess
import tarfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import config

STAGE = "/tmp/kf-shard-{slug}"
CONEXION = 6  # s de timeout de ssh


def hosts_configuradas() -> list[str]:
    env = os.environ.get("REMOTO_HOSTS", "manager1,lab,barto,debian,vps-amazon")
    return [h.strip() for h in env.split(",") if h.strip()]


def viva(host: str) -> bool:
    try:
        r = subprocess.run(
            ["ssh", "-o", f"ConnectTimeout={CONEXION}", "-o", "BatchMode=yes", host,
             "command -v ffmpeg >/dev/null && true"],
            capture_output=True, timeout=CONEXION + 5)
        return r.returncode == 0
    except (subprocess.TimeoutExpired, OSError):
        return False


def _empujar(host: str, remoto: str, archivos: list[Path]) -> None:
    """tar por stdout sobre ssh: sin dependencia de rsync en los nodos."""
    subprocess.run(
        f'ssh -o ConnectTimeout={CONEXION} {host} "mkdir -p {remoto}"',
        shell=True, check=True, timeout=30)
    ssh = subprocess.Popen(
        f'ssh -o ConnectTimeout={CONEXION} {host} "tar -xf - -C {remoto}"',
        shell=True, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE)
    # mode="w|": tar en streaming sobre el pipe de ssh (sin seek, sin archivo temporal)
    with tarfile.open(fileobj=ssh.stdin, mode="w|") as t:
        for a in archivos:
            t.add(a, arcname=a.name)
    ssh.wait(timeout=120)
    if ssh.returncode != 0:
        raise RuntimeError(f"push a {host} falló: {ssh.stderr.read()!r}"[:160])


def _traer(host: str, remoto: str, nombres: list[str], destino: Path) -> None:
    lista = " ".join(nombres)
    r = subprocess.run(
        f'ssh -o ConnectTimeout={CONEXION} {host} "tar -cf - -C {remoto} {lista}"',
        shell=True, capture_output=True, timeout=600)
    r.check_returncode()
    with tarfile.open(fileobj=io.BytesIO(r.stdout)) as t:
        t.extractall(destino, filter="data")


def _procesar(host: str, remoto: str, cola: list[dict], partes: Path,
              marcas: dict[str, str]) -> list[str]:
    """Todo el trabajo de un nodo: push -> ffmpeg serie -> pull -> marcas."""
    hechos: list[str] = []
    _empujar(host, remoto, [Path(b["_img"]) for b in cola])
    from .stages.keyframes import (CAMARA, KF_FPS, RESPIRACION_MIN_S, RESPIRACION_PX, W, H,
                                   _deriva, _recorte)
    for b in cola:
        nombre_img = Path(b["_img"]).name
        out_rem = f"{remoto}/k-{b['i']:03d}.mp4"
        frames = max(1, int(round(b["dur_s"] * KF_FPS)))
        cam = CAMARA.get(b["mov"], CAMARA["fijo"]).format(n=max(1, frames - 1))
        respira = b["dur_s"] > RESPIRACION_MIN_S
        lienzo = (f"{W + 2 * RESPIRACION_PX}x{H + 2 * RESPIRACION_PX}" if respira
                  else f"{W}x{H}")
        vf = (f"{_recorte()},zoompan={cam}:d={frames}:s={lienzo}:fps={KF_FPS}"
              + (f",crop={W}:{H}:x={RESPIRACION_PX}:y='{_deriva(b['i'])}'" if respira else "")
              + (",fade=t=in:st=0:d=0.10:color=white" if "flash" in (b.get("fx") or []) else ""))
        cmd = (f'ffmpeg -y -v error -loop 1 -i "{remoto}/{nombre_img}" '
               f'-t {b["dur_s"]:.3f} -vf "{vf}" '
               f'-c:v libx264 -preset {config.FFMPEG_PRESET} -crf {config.FFMPEG_CRF} '
               f'-pix_fmt yuv420p -r {KF_FPS} -an "{out_rem}"')
        r = subprocess.run(["ssh", "-o", f"ConnectTimeout={CONEXION}", host, cmd],
                           capture_output=True, timeout=600)
        if r.returncode != 0:
            return hechos  # lo que esté pendiente vuelve al render local
        hechos.append(nombre_img)
    _traer(host, remoto, [f"k-{b['i']:03d}.mp4" for b in cola], partes)
    salidos: list[str] = []
    for b in cola:
        out = partes / f"k-{b['i']:03d}.mp4"
        if out.exists() and out.stat().st_size > 0:
            img = Path(b["_img"])
            marca = f"{img}:{b['dur_s']}:{b['mov']}:{b['plano']}:{','.join(b.get('fx') or [])}"
            marcas[str(out)] = marca
            salidos.append(str(b["i"]))
    return salidos


def repartir_planos(slug: str, bs: list[dict], kfs: list[Path], partes: Path,
                    marcas: dict[str, str]) -> dict:
    """Rinde los beats en el labo; devuelve {'hechos':[i], 'fallidos':[i], 'nodos':[...]}.

    `bs[i]["_img"]` debe cargar la ruta del keyframe correspondiente (la fija el
    llamador). El resto del maestro (concat + subtítulos + mezcla) queda local.
    """
    vivas = [h for h in hosts_configuradas() if viva(h)]
    if not vivas:
        return {"hechos": [], "fallidos": [b["i"] for b in bs], "nodos": []}
    print(f"  render remoto: {len(vivas)} nodos ({', '.join(vivas)})")

    # beat n -> nodo n%len: reparto por cantidad; con duraciones parecidas da cargas parecidas
    colas: dict[str, list[dict]] = {h: [] for h in vivas}
    for n, (b, img) in enumerate(zip(bs, kfs)):
        b = dict(b)
        b["_img"] = str(img)
        colas[vivas[n % len(vivas)]].append(b)

    hechos, fallidos = [], []
    hech_por_nodo: dict[str, list[str]] = {}
    with ThreadPoolExecutor(max_workers=len(vivas)) as ex:
        futuros = {h: ex.submit(_procesar, h, STAGE.format(slug=slug), c, partes, marcas)
                   for h, c in colas.items() if c}
        for h, f in futuros.items():
            try:
                hech_por_nodo[h] = f.result(timeout=900)
            except Exception as exc:
                print(f"  nodo {h}: {str(exc)[:100]} — sus beats van local")
                hech_por_nodo[h] = []
    # contabilidad: un beat está hechoideo solo si su nodo lo confirmó; el resto
    # (abortados por falta de salida o nodos muertos) baja al render local
    for h, cola in colas.items():
        ok = set(hech_por_nodo.get(h, []))
        for b in cola:
            (hechos if str(b["i"]) in ok else fallidos).append(b["i"])
    return {"hechos": sorted(set(int(x) for x in hechos)),
            "fallidos": sorted(set(int(x) for x in fallidos)), "nodos": vivas}
