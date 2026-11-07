"""Pulido LLM de captions del cómic con guard de paridad factual.

El caption determinista de `adaptar_guion` es la base auditable y el fallback.
El LLM sólo puede MEJORAR la redacción de una viñeta; nunca agregar, quitar ni
cambiar un hecho. Tres capas, en orden:

  1) propuesta: una sola llamada por episodio, JSON por índice, temperatura baja;
  2) guard determinista: cifras/fechas, nombres propios, negación, atribución y
     cobertura léxica deben coincidir con el `ancla_guion` (la oración literal
     del guion verificado);
  3) verificador LLM en la RUTA DE VERIFICACIÓN (proveedor independiente del que
     redactó, regla del proyecto): confirma equivalencia semántica por viñeta.

Si cualquiera falla, la viñeta conserva el caption determinista. Sin red, la
extensión sigue funcionando igual: este módulo nunca lanza hacia `adaptar`.
"""
from __future__ import annotations

import json
import os
import re
import unicodedata

from .. import config, llm
from .adaptar_guion import NARRACION_MAX

_BRACKET = re.compile(r"^(?P<base>.*?)\s*\[(?P<encuadre>[^\]]*)\]\s*$", re.S)

# Números escritos con palabra: se normalizan a dígitos para comparar de verdad.
# "un/una/uno" quedan afuera a propósito: son artículos, no cantidades.
_NUM_PALABRA = {
    "cero": "0", "dos": "2", "tres": "3", "cuatro": "4", "cinco": "5",
    "seis": "6", "siete": "7", "ocho": "8", "nueve": "9", "diez": "10",
    "once": "11", "doce": "12", "trece": "13", "catorce": "14", "quince": "15",
    "dieciseis": "16", "diecisiete": "17", "dieciocho": "18", "diecinueve": "19",
    "veinte": "20", "veintiuno": "21", "veintidos": "22", "veintitres": "23",
    "veinticuatro": "24", "veinticinco": "25", "veintiseis": "26",
    "veintisiete": "27", "veintiocho": "28", "veintinueve": "29",
    "treinta": "30", "cuarenta": "40", "cincuenta": "50", "sesenta": "60",
    "setenta": "70", "ochenta": "80", "noventa": "90", "cien": "100",
    "ciento": "100", "doscientos": "200", "trescientos": "300",
    "cuatrocientos": "400", "quinientos": "500", "seiscientos": "600",
    "setecientos": "700", "ochocientos": "800", "novecientos": "900",
    "mil": "1000", "millon": "1000000", "millones": "1000000",
}

# Mayúsculas que NO son nombres propios (artículos, conectores, arranques comunes).
_STOP_CAP = {
    "el", "la", "los", "las", "un", "una", "unos", "unas", "y", "o", "pero",
    "en", "de", "del", "al", "a", "que", "se", "su", "sus", "lo", "le", "les",
    "por", "para", "con", "sin", "no", "ni", "era", "fue", "es", "son", "como",
    "cuando", "donde", "tras", "ante", "sobre", "entre", "hasta", "desde",
    "mas", "ya", "todo", "toda", "todos", "todas", "otro", "otra", "este",
    "esta", "estos", "estas", "ese", "esa", "eso", "aquello", "nada", "nadie",
    "nunca", "siempre", "tambien", "segun", "durante", "mientras", "aunque",
}

_NEG = ("no", "nunca", "jamas", "sin", "ni", "tampoco", "nadie", "nada",
        "ningun", "ninguna", "ninguno")

# Atribuciones y matices: cambiarlos cambia el hecho, aunque el resto coincida.
_MODAL = ("segun", "presuntamente", "supuestamente", "al parecer", "podria",
          "podrian", "habria", "habrian", "de acuerdo con", "afirmo",
          "afirmaron", "confirmo", "confirmaron", "admitio", "admitieron",
          "revelo", "revelaron", "denuncio", "denunciaron", "sostuvo",
          "sostuvieron", "aseguro", "aseguraron", "indico", "indicaron")

_STOP_CONT = {
    "para", "como", "pero", "porque", "cuando", "donde", "desde", "hasta",
    "entre", "sobre", "tras", "ante", "este", "esta", "estos", "estas",
    "esto", "otro", "otra", "otros", "otras", "todo", "toda", "todos",
    "todas", "tambien", "solo", "mas", "muy", "sin", "con", "por", "del",
    "las", "los", "una", "unos", "unas", "que", "sus", "era", "fue", "son",
    "han", "habia", "hay", "ser", "estaba", "estaban", "haber", "hace",
    "hacia", "poco", "gran", "mismo", "misma", "cada", "otra", "tras",
}


def habilitado() -> bool:
    config.load_env()
    return os.environ.get("COMICS_CAPTIONS_LLM", "").strip().lower() in (
        "1", "true", "yes", "on")


def _plano(texto: str) -> str:
    """Minúsculas y sin acentos: comparar sin falsos negativos por tilde."""
    return "".join(c for c in unicodedata.normalize("NFD", str(texto or "").lower())
                   if unicodedata.category(c) != "Mn")


def _partir(narracion: str) -> tuple[str, str]:
    """Separa el caption factual del encuadre `[entre corchetes]` del compositor."""
    m = _BRACKET.match(str(narracion or ""))
    if not m:
        return str(narracion or "").strip(), ""
    return m.group("base").rstrip(), f" [{m.group('encuadre')}]"


def _numeros(texto: str) -> list[str]:
    plano = _plano(texto)
    # separador de miles (1.500 / 1,500) -> 1500 antes de tokenizar
    plano = re.sub(r"(?<!\d)(\d{1,3}(?:[.,]\d{3})+)(?!\d)",
                   lambda m: re.sub(r"[.,]", "", m.group(1)), plano)
    for palabra in sorted(_NUM_PALABRA, key=len, reverse=True):
        plano = re.sub(rf"\b{palabra}\b", _NUM_PALABRA[palabra], plano)
    out = []
    for v in re.findall(r"\d+(?:[.,]\d+)?", plano):
        try:
            n = float(v.replace(",", "."))
        except ValueError:
            out.append(v)
            continue
        out.append(str(int(n)) if n.is_integer() else f"{n:g}")
    return sorted(out)


def _entidades(texto: str) -> set[str]:
    """Nombres propios: mayúsculas que no abren oración (ahí no se distinguen)."""
    out: set[str] = set()
    limpio = str(texto or "")
    for m in re.finditer(r"[A-ZÁÉÍÓÚÜÑ][\wáéíóúüñ'-]+", limpio):
        antes = limpio[:m.start()].rstrip()
        if not antes or antes[-1] in ".!?…:;\n\"'«“(":
            continue
        palabra = _plano(m.group(0))
        if palabra in _STOP_CAP:
            continue
        out.add(palabra)
    return out


def _niega(texto: str) -> bool:
    plano = _plano(texto)
    return any(re.search(rf"(?<!\w){re.escape(w)}(?!\w)", plano) for w in _NEG)


def _modal(texto: str) -> set[str]:
    plano = _plano(texto)
    return {m for m in _MODAL
            if re.search(rf"(?<!\w){re.escape(m)}(?!\w)", plano)}


def _contenido(texto: str) -> set[str]:
    return {p for p in re.findall(r"[a-z0-9áéíóúüñ]{4,}", _plano(texto))
            if p not in _STOP_CONT}


def revisar_paridad(ancla: str, caption: str,
                    *, limite: int = NARRACION_MAX) -> list[str]:
    """Motivos por los que un caption NO conserva la paridad factual (vacío = OK)."""
    razones: list[str] = []
    texto = " ".join(str(caption or "").split()).strip()
    if len(texto) < 15:
        razones.append("caption demasiado corto para ser una afirmación")
    if len(texto) > limite:
        razones.append(f"caption {len(texto)} chars (> {limite})")
    if "[" in texto or "]" in texto:
        razones.append("el caption no puede traer corchetes (el encuadre lo pone el compositor)")

    na, nc = _numeros(ancla), _numeros(texto)
    if na != nc:
        razones.append(f"cifras/fechas distintas: ancla={na} caption={nc}")

    nuevas = _entidades(texto) - _entidades(ancla)
    if nuevas:
        razones.append("nombres propios nuevos: " + ", ".join(sorted(nuevas)))

    if _niega(ancla) != _niega(texto):
        razones.append("polaridad de negación cambiada")

    ma, mc = _modal(ancla), _modal(texto)
    if mc - ma:
        razones.append("atribución/matiz nuevo: " + ", ".join(sorted(mc - ma)))
    if ma - mc:
        razones.append("atribución/matiz perdido: " + ", ".join(sorted(ma - mc)))

    ca, cc = _contenido(ancla), _contenido(texto)
    if ca and len(ca & cc) / len(ca) < 0.30:
        razones.append("cobertura léxica insuficiente: el caption habla de otra cosa")
    return razones


def _limpiar(texto: str) -> str:
    return " ".join(str(texto or "").replace("\n", " ").split()).strip().strip('"“”')


def _por_indice(items) -> dict[int, str]:
    if isinstance(items, dict):
        items = [{"i": k, "texto": v} for k, v in items.items()]
    out: dict[int, str] = {}
    for it in items or []:
        if not isinstance(it, dict):
            continue
        try:
            i = int(it.get("i"))
        except (TypeError, ValueError):
            continue
        texto = _limpiar(it.get("texto") or it.get("caption") or "")
        if texto:
            out[i] = texto
    return out


def _veredictos(respuesta) -> dict[int, tuple[bool, str]]:
    items = respuesta.get("pares") if isinstance(respuesta, dict) else respuesta
    out: dict[int, tuple[bool, str]] = {}
    for it in items or []:
        if not isinstance(it, dict):
            continue
        try:
            i = int(it.get("i"))
        except (TypeError, ValueError):
            continue
        out[i] = (it.get("ok") is True, str(it.get("motivo") or "")[:160])
    return out


def _mensajes_propuesta(titulo: str, candidatos: list[dict]) -> list[dict]:
    sistema = (
        "Sos editor de captions de un cómic documental en español rioplatense. "
        "Reescribís cada caption para que sea más filoso y legible, pero afirmando "
        "EXACTAMENTE lo mismo. Reglas duras: no agregues ni quites hechos, nombres, "
        "lugares, cifras, fechas, negaciones ni atribuciones; no cambies quién hizo "
        "qué; no interpretes ni opines; nada de hashtags, emojis ni corchetes; "
        "respetá el máximo de caracteres de cada viñeta. Devolvé sólo JSON válido."
    )
    usuario = (
        f"Título del capítulo: {titulo or '(sin título)'}\n\n"
        "Viñetas (ancla = oración verificada de origen; caption = texto actual; "
        "max = caracteres disponibles):\n"
        + json.dumps(candidatos, ensure_ascii=False, indent=1)
        + '\n\nDevolvé {"captions":[{"i":1,"texto":"..."}]} con una entrada por viñeta.'
    )
    return [{"role": "system", "content": sistema},
            {"role": "user", "content": usuario}]


def _mensajes_verificacion(validos: list[dict]) -> list[dict]:
    sistema = (
        "Sos auditor factual independiente. Para cada par ANCLA/CAPTION decidí si el "
        "CAPTION afirma lo mismo que el ANCLA. Es correcto que parafrasee, comprima o "
        "cambie el orden; NO es correcto que agregue, quite o cambie hechos, cifras, "
        "nombres, lugares, fechas, negaciones, atribuciones o quién hizo qué. Ante la "
        'duda, ok=false. Devolvé sólo JSON: {"pares":[{"i":1,"ok":true,"motivo":""}]}.'
    )
    usuario = "Pares:\n" + json.dumps(
        [{"i": c["i"], "ancla": c["ancla"], "caption": c["nuevo"]} for c in validos],
        ensure_ascii=False, indent=1)
    return [{"role": "system", "content": sistema},
            {"role": "user", "content": usuario}]


def pulir(paneles: list[dict], *, titulo: str = "", slug: str = "") -> dict:
    """Pule los captions que pasan el guard; devuelve el resumen de procedencia."""
    resumen = {"via": "determinista", "propuestas": 0, "aceptadas": 0,
               "rechazadas": 0, "sin_cambios": 0, "guard": "no_ejecutado",
               "motivos": []}
    for p in paneles:
        p.setdefault("caption_via", "determinista")

    if not habilitado():
        resumen["motivo"] = "COMICS_CAPTIONS_LLM apagado"
        return resumen

    candidatos: list[dict] = []
    for p in paneles:
        if str(p.get("rol_ritmico")) == "silencio" or str(p.get("accion")) == "silencio":
            continue
        base, bracket = _partir(p.get("narracion", ""))
        ancla = str(p.get("ancla_guion", "") or "").strip()
        limite = NARRACION_MAX - len(bracket)
        if len(base.strip()) < 8 or not ancla or limite < 20:
            continue
        candidatos.append({"i": int(p.get("i", 0)), "ancla": ancla,
                           "caption": base.strip(), "max": limite})

    resumen["propuestas"] = len(candidatos)
    if not candidatos:
        resumen["guard"] = "sin_candidatos"
        return resumen

    try:
        respuesta = llm.chat_json(_mensajes_propuesta(titulo, candidatos),
                                  max_tokens=1400, temperature=0.3,
                                  tag="comics-caption", episode=slug)
    except Exception as exc:  # noqa: BLE001 — sin LLM se queda el determinista
        resumen["rechazadas"] = len(candidatos)
        resumen["guard"] = "propuesta_no_disponible"
        resumen["motivos"].append(f"LLM no disponible: {str(exc)[:160]}")
        return resumen

    propuestas = _por_indice(respuesta.get("captions")
                             if isinstance(respuesta, dict) else respuesta)
    validos: list[dict] = []
    rechazos: list[str] = []
    for c in candidatos:
        nuevo = propuestas.get(c["i"], "")
        if not nuevo:
            rechazos.append(f"viñeta {c['i']}: el LLM no devolvió propuesta")
            continue
        if nuevo == c["caption"]:
            resumen["sin_cambios"] += 1
            continue
        razones = revisar_paridad(c["ancla"], nuevo, limite=c["max"])
        if razones:
            rechazos.extend(f"viñeta {c['i']}: {r}" for r in razones)
            continue
        validos.append({**c, "nuevo": nuevo})

    if not validos:
        resumen["rechazadas"] = len(rechazos)
        resumen["guard"] = "determinista"
        resumen["motivos"] = rechazos[:8]
        return resumen

    try:
        respuesta = llm.chat_json(_mensajes_verificacion(validos),
                                  max_tokens=900, temperature=0.0,
                                  tag="comics-paridad", task="verificacion",
                                  episode=slug)
    except Exception as exc:  # noqa: BLE001 — sin verificador no se acepta nada
        resumen["rechazadas"] = len(rechazos) + len(validos)
        resumen["guard"] = "verificador_no_disponible"
        resumen["motivos"] = (rechazos + [f"verificador no disponible: {str(exc)[:160]}"])[:8]
        return resumen

    veredictos = _veredictos(respuesta)
    por_i = {int(p.get("i", 0)): p for p in paneles}
    for c in validos:
        ok, motivo = veredictos.get(c["i"], (False, "sin veredicto del verificador"))
        if not ok:
            resumen["rechazadas"] += 1
            resumen["motivos"].append(
                f"viñeta {c['i']}: el verificador rechazó la paridad"
                + (f" ({motivo})" if motivo else ""))
            continue
        panel = por_i.get(c["i"])
        if panel is None:
            continue
        _, bracket = _partir(panel.get("narracion", ""))
        final = f"{c['nuevo']}{bracket}"
        if len(final) > NARRACION_MAX:
            resumen["rechazadas"] += 1
            resumen["motivos"].append(
                f"viñeta {c['i']}: caption final {len(final)} > {NARRACION_MAX}")
            continue
        panel["narracion"] = final
        panel["caption_via"] = "llm"
        panel["paridad"] = {"ok": True, "guard": "determinista+verificador"}
        resumen["aceptadas"] += 1

    resumen["rechazadas"] += len(rechazos)
    resumen["motivos"] = (resumen["motivos"] + rechazos)[:8]
    resumen["guard"] = "determinista+verificador"
    if resumen["aceptadas"]:
        resumen["via"] = "llm"
    return resumen
