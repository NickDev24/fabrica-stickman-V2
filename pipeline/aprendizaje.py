"""Aprendizaje: de las métricas reales a los números del PRÓXIMO episodio.

Lee `state/metricas.jsonl` (pipeline/metricas.py), aplica las reglas R1-R6 de
`factory/metrics/retention_loop.json` contra la MEDIANA DEL PROPIO canal, y escribe:

  state/aprendizaje.json   -> pesos por categoría (los que ya lee pipeline/nichos.py:498)
                              + `overrides`, que factory/parametros.py aplica a los rangos
                              del gancho, de los bucles y de los bloques del próximo guion
  state/iteraciones.jsonl  -> el registro con los campos que exige la propia config

Tres inquebrantables de la config, acá en código:
  1. UN cambio por episodio (dos variables a la vez no enseñan nada);
  2. sin datos reales no hay aprendizaje: con menos de MIN_EPISODIOS los pesos siguen en
     1.0 y overrides queda vacío — se documenta, no se simula;
  3. comparar contra lo propio, nunca contra números de canales ajenos.
"""
from __future__ import annotations

import json
import os
import statistics
from datetime import datetime, timezone

from factory import parametros

from . import config, metricas

APRENDIZAJE = config.STATE / "aprendizaje.json"
ITERACIONES = config.STATE / "iteraciones.jsonl"
RUTA_LOOP = config.ROOT / "factory" / "metrics" / "retention_loop.json"

# 3 episodios es lo mínimo para que una mediana no sea el propio número mirándose al
# ombligo; 10 es el criterio de aceptación que fijó la config para mover los pesos.
MIN_EPISODIOS = int(os.environ.get("APRENDIZAJE_MIN_EPISODIOS", "3"))
PESOS_MIN = 10


def loop_config() -> dict:
    return json.loads(RUTA_LOOP.read_text(encoding="utf-8"))


def reglas() -> dict:
    """Sólo las reglas R1..Rn: 'principio' y 'mediana_base' no son reglas."""
    return {k: v for k, v in loop_config()["reglas_de_decision"].items() if k.startswith("R")}


def _ratio_propio(valor, mediana) -> float | None:
    if not isinstance(valor, (int, float)) or not isinstance(mediana, (int, float)) or not mediana:
        return None
    return round(valor / mediana, 4)


def _punto(puntos: list, seg: float, duracion: float) -> float:
    objetivo = min(1.0, seg / duracion)
    return float(min(puntos, key=lambda p: abs(p[0] - objetivo))[1])


def _curva(fila: dict) -> tuple[list, float] | None:
    puntos = fila.get("retencion_curva_puntos") or []
    duracion = fila.get("duracion_video_s") or 0
    return (puntos, duracion) if puntos and duracion else None


def _caida(fila: dict, inicio_s: int, ancho_s: int = 30) -> float | None:
    curva = _curva(fila)
    if not curva:
        return None
    puntos, duracion = curva
    return round(_punto(puntos, inicio_s, duracion) - _punto(puntos, inicio_s + ancho_s, duracion), 4)


def _ventanas(filas: list[dict]) -> dict[int, float]:
    """Caida mediana del canal en cada ventana de 30 s (así se ve DÓNDE se va la gente)."""
    acum: dict[int, list[float]] = {}
    for fila in filas:
        for inicio in range(0, int(fila.get("duracion_video_s") or 0), 30):
            caida = _caida(fila, inicio)
            if caida is not None:
                acum.setdefault(inicio // 30, []).append(caida)
    return {ventana: round(statistics.median(valores), 4)
            for ventana, valores in sorted(acum.items()) if valores}


def _peor_ventana(fila: dict) -> int | None:
    """El índice de la ventana de 30 s donde ESTE episodio pierde más audiencia."""
    duracion = int(fila.get("duracion_video_s") or 0)
    caidas = {inicio // 30: _caida(fila, inicio) for inicio in range(0, duracion, 30)}
    caidas = {k: v for k, v in caidas.items() if v is not None}
    return max(caidas, key=lambda k: caidas[k]) if caidas else None


def evaluar(fila: dict, medianas: dict, historial: list[dict] | None = None) -> list[dict]:
    """Qué reglas R1-R6 disparan para UN episodio, contra la mediana de su plataforma."""
    m = medianas.get(fila.get("plataforma")) or {}
    historial = historial if historial is not None else metricas.usable()
    mismos_del_canal = [f for f in historial if f.get("plataforma") == fila.get("plataforma")]
    disparadas: list[dict] = []

    def chequeo(rid: str, cierto: bool, evidencia: str, gravedad=None) -> None:
        """`gravedad`: número donde MÁS BAJO = MÁS DOLOR (ratio vs mediana, o caída neta)."""
        if cierto:
            regla = reglas().get(rid) or {}
            disparadas.append({"id": rid, "si": regla.get("si"), "entonces": regla.get("entonces"),
                               "variable_a_tocar": regla.get("variable_a_tocar"),
                               "evidencia": evidencia, "gravedad": gravedad})

    r30 = _ratio_propio(fila.get("retencion_30s"), m.get("retencion_30s"))
    chequeo("R1_gancho", r30 is not None and r30 < 0.90,
            f"retencion_30s={fila.get('retencion_30s')} vs mediana {m.get('retencion_30s')} "
            f"({r30} x mediana)", r30)

    # R2: la fuga 30-60 s tiene que ser LA peor del episodio, y no la típica del canal
    peor = _peor_ventana(fila)
    canal_peor = _ventanas(mismos_del_canal)
    chequeo("R2_intro", peor == 1 and bool(canal_peor) and max(canal_peor, key=lambda k: canal_peor[k]) != 1,
            f"la peor caída de este episodio es la ventana 30-60 s "
            f"({_caida(fila, 30)}), y en el canal gana otra ventana", _caida(fila, 30))

    propia = _caida(fila, 60, 120)
    valores_canal = [_caida(f, 60, 120) for f in mismos_del_canal]
    valores_canal = [v for v in valores_canal if v is not None]
    media_canal = round(statistics.median(valores_canal), 4) if valores_canal else None
    chequeo("R3_valle_medio",
            propia is not None and media_canal is not None and media_canal < 0 \
            and propia < media_canal * 1.15,
            f"caída 1:00-3:00 = {propia} vs mediana del canal {media_canal}", propia)

    duracion = fila.get("duracion_video_s") or 0
    # SUPUESTO declarado por la propia métrica: la inflexión vive entre el 55% y el 80%
    # del capítulo. La métrica de Zernio no conoce los bloques del guion, así que R4 se
    # evalúa sobre la posición relativa de la fuga más grande.
    chequeo("R4_revelacion_tarde",
            bool(duracion) and peor is not None and 0.55 <= (peor * 30) / duracion <= 0.80,
            f"la mayor fuga está en el {round((peor or 0) * 30 / max(duracion, 1) * 100)}% "
            "del video (SUPUESTO: ahí cae la inflexión del template)",
            _caida(fila, (peor or 0) * 30))

    ctr = _ratio_propio(fila.get("ctr_impresiones"), m.get("ctr_impresiones"))
    chequeo("R5_ctr_bajo", ctr is not None and ctr < 0.85,
            f"ctr={fila.get('ctr_impresiones')} vs mediana {m.get('ctr_impresiones')} ({ctr} x mediana)",
            ctr)

    visto = _ratio_propio(fila.get("duracion_media_s"), m.get("duracion_media_s"))
    chequeo("R6_final_corto", visto is not None and visto < 0.90,
            f"duración media {fila.get('duracion_media_s')}s vs mediana "
            f"{m.get('duracion_media_s')}s ({visto} x mediana)", visto)
    return disparadas


def _aplicacion(rid: str) -> tuple[str, object] | None:
    """Regla -> UN número o UNA instrucción del próximo episodio (nunca las dos)."""
    gancho = tuple(parametros.hook_palabras())
    intervalo = parametros.bucles_config()[0]
    if rid.startswith("R1"):
        return "hook_palabras", [gancho[0], max(gancho[0] + 2, gancho[1] - 2)]
    if rid.startswith("R2"):
        return "recorte_palabras", {"planteamiento": 20}
    if rid.startswith("R3"):
        return "bucle_intervalo_segundos", [max(30, intervalo[0] - 15), max(45, intervalo[1] - 15)]
    if rid.startswith("R4"):
        return "directiva_guion", (
            "La promesa se está cobrando demasiado tarde: adelantá un asomo de la revelación "
            "al cierre de la exploración (cierre parcial + bucle nuevo) y recién después "
            "developá el resto.")
    if rid.startswith("R5"):
        return "directiva_guion", (
            "El problema medido es el PAR título+miniatura, no el video: el título tiene que "
            "abrir la pregunta sin prometer la respuesta y la miniatura mostrar el conflicto.")
    if rid.startswith("R6"):
        return "directiva_guion", (
            "Ritmo: la audiencia se va antes del final. Subí los cortes por minuto en el tramo "
            "caliente y acortá el giro práctico.")
    return None


def _valor_actual(clave: str):
    return {"hook_palabras": list(parametros.hook_palabras()),
            "bucle_intervalo_segundos": list(parametros.bucles_config()[0]),
            "recorte_palabras": {}, "directiva_guion": ""}.get(clave)


def _categoria_de(slug: str) -> str:
    ruta = config.PROJECTS / slug / "episode.json"
    try:
        return str(json.loads(ruta.read_text(encoding="utf-8")).get("categoria") or "")
    except (OSError, json.JSONDecodeError):
        return ""


def _pesos(filas: list[dict], medianas: dict) -> dict[str, float]:
    """Rendimiento relativo por categoría contra la mediana de su propia plataforma."""
    por_categoria: dict[str, list[float]] = {}
    for fila in filas:
        m = medianas.get(fila.get("plataforma")) or {}
        senal = [x for x in (_ratio_propio(fila.get("retencion_media"), m.get("retencion_media")),
                             _ratio_propio(fila.get("vistas"), m.get("vistas")),
                             _ratio_propio(fila.get("duracion_media_s"), m.get("duracion_media_s")))
                 if x is not None]
        categoria = _categoria_de(fila.get("slug") or "")
        if senal and categoria:
            por_categoria.setdefault(categoria, []).append(sum(senal) / len(senal))
    if len(por_categoria) < 2:
        return {}                     # con una sola categoría no hay contraste que aprender
    return {cat: round(min(1.6, max(0.6, sum(v) / len(v))), 3)
            for cat, v in sorted(por_categoria.items())}


def _registro_iteracion(fila: dict, disparada: dict, aplicacion: tuple) -> dict:
    """Fila con los campos que exige registro_de_iteracion.campos_requeridos de la config."""
    clave, valor = aplicacion
    return {
        "fecha": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "video_id": fila.get("video_id") or fila.get("postId") or "",
        "slug": fila.get("slug"), "plataforma": fila.get("plataforma"),
        "cambio_testeado": disparada["id"], "hipotesis": disparada.get("si"),
        "variable": clave, "valor_anterior": _valor_actual(clave), "valor_nuevo": valor,
        "evidencia": disparada.get("evidencia"),
        "medida_a_los_7d": None, "medida_a_los_28d": None,
        "decision": "aplicada al próximo episodio",
    }


def _severidad(disparada: dict) -> float:
    """Más negativo = más duele. Las reglas sin número propio (R2/R4) aportan su caída."""
    gravedad = disparada.get("gravedad")
    return float(gravedad) if isinstance(gravedad, (int, float)) else 0.0


def _resumen_reglas(candidatos: list) -> list[dict]:
    """Cuánto pesa cada regla: episodios afectados primero, severidad después."""
    grupos: dict[str, list] = {}
    for fila, disparada, _ in candidatos:
        grupos.setdefault(disparada["id"], []).append((fila, disparada))
    resumen = []
    for rid, grupo in grupos.items():
        resumen.append({
            "id": rid,
            "episodios_afectados": len({f.get("slug") or f.get("postId") for f, _ in grupo}),
            "severidad": round(sum(_severidad(d) for _, d in grupo) / len(grupo), 4),
            "entonces": grupo[0][1].get("entonces"),
            "slugs": sorted({str(f.get("slug") or f.get("postId") or "") for f, _ in grupo}),
        })
    return sorted(resumen, key=lambda r: (-r["episodios_afectados"], r["severidad"]))


def _peor_evidencia(candidatos: list) -> list:
    """Los episodios de la regla ganadora, del peor al mejor. UN solo cambio: esta regla."""
    if not candidatos:
        return []
    ganadora = _resumen_reglas(candidatos)[0]["id"]
    grupo = [c for c in candidatos if c[1]["id"] == ganadora]
    return sorted(grupo, key=lambda c: _severidad(c[1]))


def _escribir(estado: dict) -> None:
    config.STATE.mkdir(parents=True, exist_ok=True)
    APRENDIZAJE.write_text(json.dumps(estado, indent=2, ensure_ascii=False) + "\n",
                           encoding="utf-8")
    parametros.recargar()             # el próximo import ya ve los números nuevos


def aprender() -> dict:
    """Escribe state/aprendizaje.json (+ iteraciones.jsonl si hay cambio) y devuelve el estado."""
    filas = metricas.usable()
    episodios = sorted({f.get("slug") for f in filas if f.get("slug")})
    estado = {
        "actualizado": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "fuente": "state/metricas.jsonl (Zernio) + factory/metrics/retention_loop.json",
        "episodios_medidos": len(episodios),
        "medianas": metricas.medianas(filas),
        "pesos": {}, "overrides": {}, "reglas_disparadas": [], "estado": "",
    }
    if len(episodios) < MIN_EPISODIOS:
        estado["estado"] = (f"sin_datos_suficientes ({len(episodios)} episodios medidos de "
                            f"{MIN_EPISODIOS}): los pesos siguen en 1.0 y no se cambia nada")
        _escribir(estado)
        print(f"  aprender: {estado['estado']}")
        return estado

    pesos = _pesos(filas, estado["medianas"])
    if len(episodios) >= PESOS_MIN and pesos:
        estado["pesos"] = pesos
    else:
        estado["pesos_nota"] = (f"para mover los pesos hacen falta {PESOS_MIN} episodios; "
                                f"hoy hay {len(episodios)}")

    # UN solo cambio, elegido con la evidencia de TODOS los episodios medidos: la regla que
    # más episodios afectó (y, empatada, la que más los afectó). Mirar nada más el último
    # episodio sería aprender de una muestra de uno, que es justo lo que la config prohíbe.
    candidatos = []
    for fila in filas:
        for disparada in evaluar(fila, estado["medianas"], filas):
            aplicacion = _aplicacion(disparada["id"])
            if aplicacion:
                candidatos.append((fila, disparada, aplicacion))
    estado["reglas_disparadas"] = _resumen_reglas(candidatos)
    if candidatos:
        ganadores = _peor_evidencia(candidatos)
        fila, disparada, aplicacion = ganadores[0]
        estado["overrides"] = {aplicacion[0]: aplicacion[1]}
        estado["cambio_activo"] = {"regla": disparada["id"],
                                   "episodios_afectados": len(ganadores),
                                   "slug_origen": fila.get("slug"),
                                   "evidencia": [d.get("evidencia") for _, d, _ in ganadores],
                                   "entonces": disparada.get("entonces")}
        estado["estado"] = "iterando_un_cambio"
        with ITERACIONES.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(_registro_iteracion(fila, disparada, aplicacion),
                                ensure_ascii=False) + "\n")
    else:
        estado["estado"] = ("sin_reglas_disparadas: ningún episodio rindió por debajo del "
                            "umbral relativo del canal; se conserva la configuración actual")
    _escribir(estado)
    print(f"  aprender: {estado['estado']} · episodios={len(episodios)} · "
          f"pesos={estado['pesos'] or 'sin cambios'} · overrides={estado['overrides']}")
    return estado


def resumen_corto() -> str:
    """Para el mensaje de Telegram: qué se aprendió y qué se prueba mañana."""
    if not APRENDIZAJE.exists():
        return "aprendizaje: todavía no corrió (no existe state/aprendizaje.json)"
    estado = json.loads(APRENDIZAJE.read_text(encoding="utf-8"))
    cambio = estado.get("cambio_activo") or {}
    lineas = [f"aprendizaje: {estado.get('estado')} · "
              f"{estado.get('episodios_medidos')} episodios medidos"]
    if cambio:
        lineas.append(f"regla {cambio.get('regla')} desde {cambio.get('slug_origen')}: "
                      f"{(cambio.get('entonces') or '')[:120]}")
        lineas.append(f"override activo: {estado.get('overrides')}")
    return "\n".join(lineas)
