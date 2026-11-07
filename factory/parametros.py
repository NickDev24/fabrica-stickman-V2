"""Parámetros quirúrgicos de la fábrica: la única fuente de los números.

Los JSON de `factory/` describían la metodología pero ningún módulo los leía: el pipeline
producía con literales hardcodeados y editar una configuración no cambiaba el render. Este
módulo cierra ese cable. Reglas:

- Todo valor tiene default = el número que el código ya usaba, así importar no cambia
  el comportamiento de lo que hoy funciona.
- Si un archivo falta o está roto, se avisa en stderr y se usa el default: una fábrica
  que se detiene por un JSON mal formateado pierde el episodio, y el default no es un
  número inventado, es el que estaba en el código.
- `validar()` (usado por los tests) falla duro: obliga a que los archivos existan y
  tengan las claves que el pipeline consume.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

BASE = Path(__file__).resolve().parent

_CACHE: dict[str, dict] = {}
_AVISADO: set[str] = set()


def _avisar(archivo: str, por_que: str) -> None:
    if archivo not in _AVISADO:
        _AVISADO.add(archivo)
        print(f"  ⚠ parámetros: {archivo} no usable ({por_que}); se toma el valor del código",
              file=sys.stderr)


def cargar(archivo: str, default: dict | None = None) -> dict:
    """Lee factory/<archivo>.json con cache y merge superficial sobre el default."""
    if archivo in _CACHE:
        return _CACHE[archivo]
    ruta = BASE / archivo
    datos: dict = dict(default or {})
    try:
        leido = json.loads(ruta.read_text(encoding="utf-8"))
        if not isinstance(leido, dict):
            raise ValueError("no es un objeto JSON")
        datos.update(leido)
    except FileNotFoundError:
        _avisar(archivo, "archivo ausente")
    except (json.JSONDecodeError, ValueError) as exc:
        _avisar(archivo, f"JSON inválido: {str(exc)[:80]}")
    _CACHE[archivo] = datos
    return datos


def recargar() -> None:
    """Para los tests y para poder cambiar un número sin reiniciar el proceso."""
    _CACHE.clear()
    _AVISADO.clear()
    global _APRENDIDO
    _APRENDIDO = None


# --------------------------------------------------------------- capa aprendida
# state/aprendizaje.json lo escribe pipeline/aprendizaje.py desde métricas REALES de
# Zernio (nunca a mano y nunca simulado). Acá es donde el aprendizaje se convierte en
# un número del próximo episodio: sin este lector, R1-R6 serían decoración.
APRENDIZAJE = BASE.parent / "state" / "aprendizaje.json"
_APRENDIDO: tuple[float, dict] | None = None


def overrides() -> dict:
    if not APRENDIZAJE.exists():
        return {}
    mtime = APRENDIZAJE.stat().st_mtime
    global _APRENDIDO
    if _APRENDIDO is not None and _APRENDIDO[0] == mtime:
        return _APRENDIDO[1]
    try:
        datos = json.loads(APRENDIZAJE.read_text(encoding="utf-8"))
        valor = datos.get("overrides") or {}
    except (OSError, json.JSONDecodeError) as exc:
        _avisar("state/aprendizaje.json", f"no usable: {str(exc)[:60]}")
        valor = {}
    _APRENDIDO = (mtime, valor)
    return valor


def _rango(clave: str, default: tuple) -> tuple:
    """Un rango [lo, hi] aprendido; si no hay override, el del archivo de config."""
    valor = overrides().get(clave)
    if isinstance(valor, (list, tuple)) and len(valor) == 2:
        try:
            return (type(default[0])(valor[0]), type(default[1])(valor[1]))
        except (TypeError, ValueError):
            _avisar("state/aprendizaje.json", f"override {clave} no es un par de números")
    return default


# --------------------------------------------------------------- narrativa
_CLAVES_TEMPLATE = {"palabras_por_segundo", "target_words", "target_duration_s", "bloques"}
_DEFAULT_TEMPLATE: dict[str, Any] = {
    "palabras_por_segundo": 2.24,
    "target_words": [1300, 1600],
    "target_duration_s": [500, 600],
    "bloques": [],
}

_CLAVES_ENGINE = {"golden_hook", "curiosity_loop", "mapeo_latidos_bloques"}
_DEFAULT_ENGINE: dict[str, Any] = {
    "golden_hook": {"words_objetivo": [6, 12], "words_tolerancia": [4, 16]},
    "curiosity_loop": {"interval_seconds": [45, 90], "count_objetivo_por_episodio": [6, 8]},
    "mapeo_latidos_bloques": [],
}


def template_guion() -> dict:
    return cargar("templates/script_template_8_10min.json", _DEFAULT_TEMPLATE)


def motor_narrativo() -> dict:
    return cargar("specs/story_engine.json", _DEFAULT_ENGINE)


def palabras_objetivo() -> tuple[int, int]:
    lo, hi = template_guion()["target_words"]
    return _rango("palabras_objetivo", (int(lo), int(hi)))


def duracion_objetivo_s() -> tuple[int, int]:
    lo, hi = template_guion()["target_duration_s"]
    return _rango("duracion_objetivo_s", (int(lo), int(hi)))


def palabras_por_segundo() -> float:
    return float(template_guion()["palabras_por_segundo"])


def bloques() -> list[dict]:
    """Los bloques del template, con el recorte de palabras que haya dictado el aprendizaje.

    `recorte_palabras` ({block_id: n}) es la vía de R2 (achicar el planteamiento) y R4
    (mover la revelación): se aplica a una copia, nunca al JSON cacheado, para que dos
    getters en la misma corrida vean exactamente los mismos números.
    """
    recorte = overrides().get("recorte_palabras") or {}
    salida = []
    for bloque in template_guion()["bloques"]:
        resta = recorte.get(bloque.get("block_id")) if isinstance(recorte, dict) else None
        if isinstance(resta, (int, float)) and resta:
            bloque = dict(bloque)
            lo, hi = bloque.get("words_target") or [0, 0]
            bloque["words_target"] = [max(1, int(lo - resta)), max(2, int(hi - resta))]
            bloque["words_nominal"] = max(1, int(bloque.get("words_nominal", hi) - resta))
            bloque["ajustado_por_aprendizaje"] = int(resta)
        salida.append(bloque)
    return salida


def hook_palabras() -> tuple[int, int]:
    lo, hi = motor_narrativo()["golden_hook"].get("words_tolerancia", [4, 16])
    return _rango("hook_palabras", (int(lo), int(hi)))


def bucles_config() -> tuple[tuple[int, int], tuple[int, int]]:
    loop = motor_narrativo()["curiosity_loop"]
    lo, hi = loop.get("interval_seconds", [45, 90])
    clo, chi = loop.get("count_objetivo_por_episodio", [6, 8])
    intervalo = _rango("bucle_intervalo_segundos", (int(lo), int(hi)))
    cantidad = _rango("bucle_cantidad_objetivo", (int(clo), int(chi)))
    return intervalo, cantidad


def directiva_aprendida() -> str:
    """La instrucción textual del último cambio aprendido (R4/R5 no son un número).

    Se inyecta en el prompt del guion del próximo episodio, una sola por corrida:
    tocar dos variables a la vez hace que el resultado no enseñe nada.
    """
    return str(overrides().get("directiva_guion") or "").strip()


# --------------------------------------------------------------- guion: prompt maestro
_BLOQUE_CODIGO = re.compile(r"````text\n(.*?)\n````", re.S)


def prompt_guion(**variables: str) -> str:
    """El prompt maestro de `factory/prompts/guion_master.prompt.md`, con las variables puestas.

    El archivo es markdown legible por humanos con el prompt dentro de un bloque ````text.
    Si queda una {{VARIABLE}} sin reemplazar, revienta: un prompt a medio sustituir
    produce guiones silenciosamente peores que es lo que esta fábrica viene sufriendo.
    """
    ruta = BASE / "prompts" / "guion_master.prompt.md"
    texto = ruta.read_text(encoding="utf-8")
    coincidencia = _BLOQUE_CODIGO.search(texto)
    if not coincidencia:
        raise ValueError(f"{ruta} no contiene el bloque ````text con el prompt")
    prompt = coincidencia.group(1).strip()
    for clave, valor in variables.items():
        prompt = prompt.replace("{{" + clave.upper() + "}}", str(valor))
    sobrantes = sorted(set(re.findall(r"\{\{([A-Z_]+)\}\}", prompt)))
    if sobrantes:
        raise KeyError(f"prompt maestro con variables sin valor: {sobrantes}")
    return prompt


# --------------------------------------------------------------- animación
_DEFAULT_MOTION: dict[str, Any] = {
    "ritmo_real_medido": {"beat_min_s": 3.5, "beat_max_s": 5.5},
    "micro_movement": {"required": True},
    "camara": {"movs": {}},
    "sincronizacion_palabra_clave": {"pop": {"palabras_max": 2, "caracteres_max": 14,
                                             "duracion_s": [0.6, 1.2]},
                                     "cobertura_minima": {"beats_con_pop": 0.35}},
    "metaforas": {"mapeo": {}},
}


def motion() -> dict:
    return cargar("acting/stickman_motion_rules.json", _DEFAULT_MOTION)


def beat_segundos() -> tuple[float, float]:
    r = motion()["ritmo_real_medido"]
    return float(r["beat_min_s"]), float(r["beat_max_s"])


def camara_movs() -> dict:
    return dict(motion()["camara"].get("movs", {}))


def pop_config() -> dict:
    return dict(motion()["sincronizacion_palabra_clave"].get("pop", {}))


def metaforas() -> dict:
    return dict(motion()["metaforas"].get("mapeo", {}))


# --------------------------------------------------------------- edición
_DEFAULT_EDITING: dict[str, Any] = {"texto_en_pantalla": {"pop_de_palabra_clave": {"activo": False}}}


def editing() -> dict:
    return cargar("render/editing_config.json", _DEFAULT_EDITING)


def pop_activo() -> bool:
    return bool(editing().get("texto_en_pantalla", {}).get("pop_de_palabra_clave", {}).get("activo", False))


# --------------------------------------------------------------- voz
_DEFAULT_VOZ: dict[str, Any] = {
    "voz_canonica": "edge-tts:es-AR-TomasNeural",
    "voz_fallback": "piper:es_AR-daniela-high",
    "ritmo": {"palabras_por_segundo": {"edge_tomas_voz_sola": 2.834,
                                       "edge_tomas_con_pausas_de_bloque": 2.668,
                                       "piper_daniela": 2.6}},
    "pausas_ms": {"coma": 280, "punto": 550, "signo_de_interrogacion": 600,
                  "dramatica_antes_de_revelacion": [600, 900]},
    "profiles": {},
}


def voz() -> dict:
    return cargar("audio/voice_config.json", _DEFAULT_VOZ)


def voz_canonica() -> str:
    return str(voz().get("voz_canonica") or _DEFAULT_VOZ["voz_canonica"])


def pausas_ms() -> dict:
    return dict(voz().get("pausas_ms", {}))


def prosodia(rol: str = "base") -> dict:
    """rate/pitch del motor de voz para un rol narrativo (base | gancho | pregunta)."""
    tabla = voz().get("prosodia") or {}
    bloque = dict(tabla.get("base") or {})
    bloque.update((tabla.get(rol) or {}))
    bloque.pop("nota", None)
    return {"rate": str(bloque.get("rate", "+0%")), "pitch": str(bloque.get("pitch", "+0Hz"))}


def length_scale(rol: str = "base") -> float:
    """El --rate del config traducido al `--length-scale` de Piper: una sola fuente de verdad.

    Piper no tiene rate; estirar los fonemas es lo equivalente. -6% de velocidad = 1/0,94
    de largo, así que el gancho se frena la misma cantidad sea cual sea el motor.
    """
    rate = prosodia(rol)["rate"].strip().rstrip("%")
    try:
        pct = float(rate) / 100.0
    except ValueError:
        return 1.0
    return round(1.0 / (1.0 + pct), 3)


def variacion_pausa() -> list[float]:
    """Factor por bloque de la pausa final: la cadencia perfecta se escucha de máquina."""
    ciclo = (pausas_ms().get("variacion_ciclo") or [])
    try:
        vals = [float(v) for v in ciclo]
    except (TypeError, ValueError):
        return []
    return vals if len(vals) >= 2 else []


# --------------------------------------------------------------- empaque / publicar / qc
def titulos() -> dict:
    return cargar("packaging/title_rules.json", {})


def rango_titulo() -> tuple[int, int]:
    """Ventana de caracteres del máster: la que YouTube no corta y se lee en el feed móvil."""
    yt = (titulos().get("titulo") or {}).get("youtube") or {}
    piso, techo = yt.get("caracteres") or [45, 65]
    return int(piso), int(yt.get("duros_max") or max(techo, 70))


def portadas() -> dict:
    return cargar("packaging/thumbnail_rules.json", {})


def publicacion() -> dict:
    return cargar("publish/publish_strategy.json", {"autonomia": {}})


def minimo_aprobaciones_humanas() -> int:
    """Sólo el dueño autoriza, y la autonomía total llega tras N aprobaciones, no tras 1."""
    datos = publicacion().get("autonomia") or {}
    return int(datos.get("aprobaciones_humanas_minimas", 5))


def qc_rubrica() -> dict:
    return cargar("metrics/qc_score_rubric.json", {"umbral_de_aprobacion": 82, "pesos": []})


def umbral_qc() -> int:
    return int(qc_rubrica().get("umbral_de_aprobacion", 82))


def qc_narrativo() -> dict:
    return cargar("specs/qc_stickman_narrative.json", {"checks": []})


def metricas() -> dict:
    return cargar("metrics/retention_loop.json", {})


# --------------------------------------------------------------- contrato
_CLAVES: dict[str, set[str]] = {
    "templates/script_template_8_10min.json": _CLAVES_TEMPLATE,
    "specs/story_engine.json": _CLAVES_ENGINE,
    "acting/stickman_motion_rules.json": {"ritmo_real_medido", "camara", "metaforas",
                                          "sincronizacion_palabra_clave", "micro_movement"},
    "audio/voice_config.json": {"voz_canonica", "pausas_ms", "ritmo"},
    "render/editing_config.json": {"texto_en_pantalla", "rhythm"},
    "packaging/title_rules.json": {"titulo", "miniatura"},
    "packaging/thumbnail_rules.json": {"salidas"},
    "publish/publish_strategy.json": {"youtube", "facebook", "autonomia"},
    "metrics/qc_score_rubric.json": {"pesos", "umbral_de_aprobacion"},
    "specs/qc_stickman_narrative.json": {"checks", "pass_criteria"},
}


def validar() -> list[str]:
    """Problemas concretos de las configuraciones. Vacío = la fábrica está cableada y sana."""
    problemas: list[str] = []
    for archivo, claves in _CLAVES.items():
        ruta = BASE / archivo
        if not ruta.exists():
            problemas.append(f"{archivo}: no existe")
            continue
        try:
            datos = json.loads(ruta.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            problemas.append(f"{archivo}: JSON inválido ({exc})")
            continue
        faltan = sorted(claves - set(datos))
        if faltan:
            problemas.append(f"{archivo}: faltan las claves {faltan}")
    rubrica = BASE / "metrics" / "qc_score_rubric.json"
    if rubrica.exists():
        pesos = json.loads(rubrica.read_text(encoding="utf-8")).get("pesos", [])
        suma = sum(int(p.get("puntos", 0)) for p in pesos)
        if suma != 100:
            problemas.append(f"qc_score_rubric.json: los pesos suman {suma}, no 100")
    plantilla = BASE / "templates" / "script_template_8_10min.json"
    if plantilla.exists():
        datos = json.loads(plantilla.read_text(encoding="utf-8"))
        pps = float(datos.get("palabras_por_segundo", 2.24))
        total = sum(int(b["time_end_s"] - b["time_start_s"]) * pps for b in datos.get("bloques", []))
        lo, hi = datos.get("target_words", [0, 0])
        if datos.get("bloques") and not (lo * 0.8 <= total <= hi * 1.2):
            problemas.append(f"script_template: los bloques dan {total:.0f} palabras, "
                             f"fuera de {lo}-{hi}")
    return problemas
