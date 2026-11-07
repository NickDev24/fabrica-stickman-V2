"""Acceso opcional al servidor youtube-mcp para contexto competitivo, vía MCP stdio."""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from . import config

MCP_ROOT = config.ROOT / "youtube-mcp"
CLIENT = MCP_ROOT / "factory_client.py"
PYTHON = MCP_ROOT / ".venv" / "bin" / "python"


def buscar_varios(consultas: list[str], max_consultas: int = 8) -> dict[str, list[dict]]:
    """Busca títulos de referencia. Los resultados no son evidencia ni métricas de vistas."""
    if not consultas or not CLIENT.is_file() or not PYTHON.is_file():
        return {}
    payload = json.dumps(consultas[:max_consultas], ensure_ascii=False)
    try:
        proc = subprocess.run(
            [str(PYTHON), str(CLIENT)], input=payload, text=True,
            capture_output=True, timeout=float(os.getenv("YOUTUBE_MCP_TIMEOUT_S", "90")),
            check=False,
        )
        if proc.returncode:
            print(f"  youtube-mcp no disponible ({proc.stderr[-300:].strip()})")
            return {}
        filas = json.loads(proc.stdout)
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError) as exc:
        print(f"  youtube-mcp no disponible ({type(exc).__name__})")
        return {}

    salida: dict[str, list[dict]] = {}
    for fila in filas:
        texto = fila.get("text", "")
        try:
            datos = json.loads(texto)
        except json.JSONDecodeError:
            datos = []
        if isinstance(datos, dict):
            datos = [datos]
        if isinstance(datos, list):
            salida[fila.get("query", "")] = [x for x in datos if isinstance(x, dict)]
    return salida
