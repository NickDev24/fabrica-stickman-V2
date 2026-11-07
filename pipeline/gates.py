"""Gates no negociables de CONTEXTO.md, como checks ejecutables.

Cada gate devuelve (ok: bool, motivos: list[str]). Un gate fallido aborta la etapa.
"""
from __future__ import annotations

import json
import re
from urllib.parse import urlparse

import requests

from . import config


class GateFailure(Exception):
    def __init__(self, gate: str, reasons: list[str]):
        self.gate = gate
        self.reasons = reasons
        super().__init__(f"[{gate}] " + "; ".join(reasons))


def check(ok: bool, gate: str, reasons: list[str]):
    if not ok:
        raise GateFailure(gate, reasons)
    return True


# ---------------------------------------------------------------- Gate 1
def gate_fuentes(sources: dict, ficcion: bool = False, min_fuentes: int | None = None) -> bool:
    """Fáctico: >=2 fuentes independientes por afirmación. Ficción: las afirmaciones son
    ANCLAS de verosimilitud (física, geografía, supervivencia) y admiten >=1 fuente:"""
    from . import web

    if min_fuentes is None:
        min_fuentes = 1 if ficcion else 2
    reasons = []
    claims = sources.get("claims", [])
    if not claims:
        check(False, "fuentes", ["el episodio no tiene ninguna afirmación central"])
    # Una URL se comprueba UNA vez, no una por cada afirmación que la cita: antes el mismo
    # dominio caído aparecía 5 veces en el motivo y la corrida gastaba 5 requests.
    reach: dict[str, str] = {}
    reportadas: set[str] = set()

    def alcanzable(url: str) -> str:
        if url in reach:
            return reach[url]
        estado = ""
        try:
            web.obtener(url, timeout=15, method="HEAD")
        except requests.RequestException:
            # Un HEAD bloqueado (405/406) no prueba que la fuente no exista: muchos
            # servidores lo cortan. Lo que vale es el GET, que es como research la leyó.
            try:
                web.obtener(url, timeout=15)
            except requests.RequestException as exc:
                estado = f"fuente no alcanzable ({str(exc)[:20]})"
        reach[url] = estado
        return estado

    for claim in claims:
        text = claim.get("claim", "?")
        srcs = claim.get("sources", [])
        if len(srcs) < min_fuentes:
            reasons.append(f"afirmación con <{min_fuentes} fuentes: {text[:60]}")
            continue
        if not ficcion:
            hosts = {urlparse(s["url"]).netloc.replace("www.", "") for s in srcs}
            if len(hosts) < 2:
                reasons.append(f"fuentes del mismo dominio ({hosts.pop()}) no son independientes: {text[:60]}")
        for s in srcs:
            url = s.get("url", "")
            if not url.startswith("http"):
                reasons.append(f"fuente sin URL citable en: {text[:60]}")
                continue
            motivo = alcanzable(url)
            if motivo and url not in reportadas:
                reportadas.add(url)
                reasons.append(f"{motivo}: {url}")
    verdicts = {c.get("verdict", "pendiente") for c in claims}
    # El fact-check escribe "refutada" (el prompt lo dice textualmente); el gate históricamente
    # buscaba "refutado" y nunca matcheaba: un hecho REFUTADO pasaba derecho al guion.
    if verdicts & {"refutada", "refutado"}:
        reasons.append("hay afirmaciones refutadas por el fact-check")
    if "pendiente" in verdicts:
        reasons.append("hay afirmaciones sin verdict de fact-check")
    if ficcion:
        invalidos = {v for v in verdicts if v not in ("ancla", "respaldada", "parcial")}
        if invalidos:
            reasons.append(f"verdicts fuera de rango para ficción: {sorted(invalidos)}")
    check(not reasons, "fuentes", reasons or ["ok"])
    return True


# ---------------------------------------------------------------- Gate 1b
def gate_fidelidad(script: str, claims: list[dict], episode: str = "") -> list[str]:
    """Aplica el gate 1 sobre el TEXTO: enumera enunciados del guion sin respaldo en las
    afirmaciones verificadas. Vacío = el guion no inventa nada."""
    from . import llm
    claim_txt = "\n".join(f"- {c['claim']}" for c in claims)
    prompt = (
        "Auditor de hechos de un canal de documentales. Abajo hay AFIRMACIONES VERIFICADAS (en "
        "inglés) y un GUION (en español rioplatense). Un enunciado del guion está RESPALDADO si "
        "afirma lo mismo que alguna verificación, AUNQUE lo parafrasee, traduzca al español o cambie "
        "el orden de las palabras. Una traducción fiel NO es invento.\n\n"
        "Listá como no_respaldado SOLO los enunciados que asserten un HECHO CONCRETO NUEVO que no "
        "esté en ninguna verificación: una cifra, fecha, nombre propio, lugar, testimonio, causa o "
        "escena que las verificaciones no mencionan (por ejemplo 'los modelos de riesgo actuales', "
        "'un cazador declaró', 'a 8 km de altura' si no aparece).\n\n"
        "NO listés (no cuentan como hecho): preguntas retóricas ('¿qué pasó entonces?'), metáforas e "
        "imágenes poéticas ('el cielo se encendió como una hoguera'), frases de.addresso al espectador "
        "('pensá en esto'), reflexión editorial o cierre ('esto nos invita a comprender', 'una lección "
        "para hoy'), ni reformulaciones en otras palabras de un dato que SÍ está verificado. Ante la "
        "duda sobre si es paráfrasis de un dato verificado, consideralo RESPALDADO.\n\n"
        "Devolvé sólo JSON: {\"no_respaldados\":[\"cita textual breve del guion\", ...]} "
        "(lista vacía si todo está respaldado o es retórico).\n\n"
        f"AFIRMACIONES VERIFICADAS:\n{claim_txt}\n\nGUION:\n{script}"
    )
    data = llm.chat_json([{"role": "user", "content": prompt}],
                         max_tokens=3000, tag="fidelidad", episode=episode)
    return [q for q in data.get("no_respaldados", []) if q and q.strip().lower() not in ("ninguno", "n/a")]


# ---------------------------------------------------------------- Gate 2
def gate_voz(voice_ref: str) -> bool:
    """Sólo voces propias del canal (allowlist). Nunca clonación de personas reales."""
    reasons = []
    if voice_ref not in config.VOICE_ALLOWLIST:
        reasons.append(f"voz {voice_ref!r} fuera de la allowlist del canal "
                       f"({sorted(config.VOICE_ALLOWLIST)})")
    lowered = voice_ref.lower()
    for palabra in ("clone", "clonar", "imitación", "imitacion", "persona"):
        if palabra in lowered:
            reasons.append(f"la referencia de voz {voice_ref!r} sugiere clonación/imitación")
    check(not reasons, "voz", reasons or ["ok"])
    return True


# ---------------------------------------------------------------- Gate 3
def gate_contenido_sintetico(metadata: dict) -> bool:
    """Todo episodio con narración/visuales IA debe exportar synthetic_content=true."""
    reasons = []
    if metadata.get("narration_engine") and not metadata.get("synthetic_content", False):
        reasons.append("narración por IA sin flag synthetic_content=true en metadatos")
    if metadata.get("ai_visuals") and not metadata.get("synthetic_content", False):
        reasons.append("visuales generados sin flag synthetic_content=true")
    check(not reasons, "contenido_sintetico", reasons or ["ok"])
    return True


# ---------------------------------------------------------------- Gate 4
_STRIP = re.compile(r"[^a-z0-9áéíóúñü ]+")


def _normalize(text: str) -> str:
    return _STRIP.sub(" ", text.lower().replace("  ", " ").strip())


def _ngrams(text: str, n: int = 4) -> set:
    words = _normalize(text).split()
    return {" ".join(words[i:i + n]) for i in range(max(0, len(words) - n + 1))}


def _structure(script: str) -> list[str]:
    """Esqueleto estructural: tipo de cada bloque del guion."""
    blocks = []
    for para in re.split(r"\n\s*\n", _normalize(script)):
        para = para.strip()
        if not para:
            continue
        first = para.split(" ", 2)[0] if para else ""
        kind = "hook" if first in ("hace", "imagine", "imagina", "y", "pero") else \
               "fuente" if "fuente" in para or "http" in para else \
               "dato" if re.search(r"\d", para[:80]) else "narrativa"
        blocks.append(kind)
    return blocks


def _structure_similarity(a: list[str], b: list[str]) -> float:
    if not a or not b:
        return 0.0
    # Si los dos guiones quedaron reducidos a una sola clase (normalmente "narrativa"),
    # esta etiqueta no contiene información con la que distinguir sus estructuras. La
    # similitud textual de 4-gramas sigue protegiendo contra la repetición real.
    if len(set(a) | set(b)) < 2:
        return 0.0
    la, lb = len(a), len(b)
    ratio_len = min(la, lb) / max(la, lb)
    common = sum(min(a.count(x), b.count(x)) for x in set(a) | set(b))
    jaccard = common / (la + lb - common)
    return round(0.5 * ratio_len + 0.5 * jaccard, 4)


def gate_anti_duplicado(script: str, previos: list[dict]) -> bool:
    """Compara el guion contra los últimos N publicados; rechaza plantillas repetidas."""
    reasons = []
    nuevos = _ngrams(script)
    for prev in previos[:config.COMPARE_LAST_N]:
        old = _ngrams(prev["script"])
        if not nuevos or not old:
            continue
        j = len(nuevos & old) / len(nuevos | old)
        if j > config.SIMILARITY_MAX_NGRAM:
            reasons.append(f"similitud textual {j:.2f} > {config.SIMILARITY_MAX_NGRAM} con episodio {prev.get('slug')}")
        s = _structure_similarity(_structure(script), _structure(prev["script"]))
        if s > config.SIMILARITY_MAX_STRUCTURE:
            reasons.append(f"similitud estructural {s:.2f} > {config.SIMILARITY_MAX_STRUCTURE} con episodio {prev.get('slug')}")
    check(not reasons, "anti_duplicado", reasons or ["ok"])
    return True


# ---------------------------------------------------------------- Gate 7
def gate_publicacion(metadata: dict) -> bool:
    """Antes de que algo salga al exterior: flag sintético puesto (gate 3) y decisión
    de canal explícita. Con AUTO_PUBLISH=true el pipeline postea vía Zernio; sin eso,
    sólo checklist + Telegram. El toggle de YouTube Studio es humano: no existe API."""
    reasons = []
    if not metadata.get("synthetic_content", False):
        reasons.append("se intentó publicar/enviar sin synthetic_content=true (gate 3)")
    check(not reasons, "publicacion", reasons or ["ok"])
    return True


# ---------------------------------------------------------------- Gate 5: extensión
_APERTURA_BUCLE = re.compile(
    r"\b(pero|y|sin embargo|no obstante|ah[íi] es donde|lo que (nadie|no)|la parte que|"
    r"el problema (real|de verdad)|la raz[oó]n (real|verdad)|esto (no|se)|"
    r"y justo ah[íi]|nadie (esperaba|cont[oó]|dijo|vio)|lo extra[ñn]o|el detalle (clave|que))\b",
    re.I)
_CIERRE_BUCLE = re.compile(
    r"(\.\.\.|\u2026|la respuesta|la raz[oó]n era|result[aó] (ser|que)|en realidad|"
    r"lo que (pas[oó]|sucedi[oó])|la verdad (es|era)|el motivo)", re.I)


def gate_ritmo(duracion_s: float, palabras: int, pps_esperado: float,
               tolerancia: float = 0.30) -> list[str]:
    """GATE 8: el ritmo REAL del máster narrado, no el que supone la plantilla.

    Si la voz va más rápida o más lenta de lo que dice `palabras_por_segundo`, el capítulo ya
    no cae en la banda de duración prometida aunque el guion haya pasado el gate de extensión:
    la única cifra honesta es la que sale de medir el audio.
    """
    if duracion_s <= 0 or palabras <= 0:
        return ["no hay audio ni texto para medir el ritmo"]
    pps = palabras / duracion_s
    if abs(pps - pps_esperado) / pps_esperado > tolerancia:
        return [f"ritmo medido {pps:.2f} palabras/s contra {pps_esperado:.2f} esperados "
                f"(±{tolerancia:.0%}): {palabras} palabras dan {duracion_s/60:.1f} min. "
                "O se ajusta la pausa/banda de la voz, o se recalcula el presupuesto de palabras "
                "del template — no se deja que el episodio salga con otra duración de la prometida"]
    return []


def gate_extension(script: str, min_words: int, max_words: int) -> list[str]:
    """El guion tiene que durar lo que promete la plantilla: ni 2 minutos disfrazados de 10."""
    n = len([w for w in script.split() if w])
    if n < min_words:
        return [f"el guion tiene {n} palabras, mínimo {min_words} "
                f"(faltan {min_words - n}: se extiende el bloque más flaco, no el primero que sigue)"]
    if n > max_words:
        return [f"el guion tiene {n} palabras, máximo {max_words} (sobran {n - max_words})"]
    return []


def contar_bucles(script: str) -> int:
    """Aperturas de bucle DISTINTAS: contar la misma muleta veinte veces no mide nada."""
    prosa = re.sub(r"\s+", " ", script)
    return len({m.group(0).lower() for m in _APERTURA_BUCLE.finditer(prosa)})


def gate_bucles(script: str, objetivo: tuple[int, int], minimo_bloqueante: int = 3) -> list[str]:
    """Bucles de curiosidad. Bloquea la ausencia clara; el déficit contra el objetivo avisa."""
    n = contar_bucles(script)
    prosa = re.sub(r"\s+", " ", script)
    cierres = len(_CIERRE_BUCLE.findall(prosa))
    if n < minimo_bloqueante:
        return [f"el guion abre {n} bucles de curiosidad detectables, mínimo {minimo_bloqueante} "
                f"(objetivo {objetivo[0]}-{objetivo[1]}): cada bloque debe abrir una pregunta y cobrarla más adelante"]
    if not cierres:
        return ["el guion abre bucles pero no tiene ningún marcador de cobro "
                "('la respuesta era', 'en realidad', 'el motivo'): son preguntas que no se cierran"]
    if n < objetivo[0]:
        print(f"  BUCLES: {n} detectados, por debajo del objetivo {objetivo[0]}-{objetivo[1]} "
              "(no bloquea, pero es la causa más común de caída en el minuto 2)")
    return []


# ---------------------------------------------------------------- Gate 6: título
_TITULO_PROHIBIDO = re.compile(r"\b(top\s*\d+|\d+\s*(cosas|secretos|datos|hechos|razones)|"
                               r"incre[ií]ble|shocking|sab[ií]as que)\b", re.I)


def gate_titulo(titulo: str, min_chars: int = 45, max_chars: int = 70) -> list[str]:
    """Título: open loop, en el rango que YouTube no corta y que se lee en el feed de móvil."""
    t = (titulo or "").strip()
    reasons = []
    if not t:
        return ["el episodio no tiene título"]
    if len(t) > max_chars:
        reasons.append(f"título de {len(t)} caracteres, máximo {max_chars}")
    if len(t) < min_chars:
        reasons.append(f"título de {len(t)} caracteres, bajo {min_chars}: poco open loop")
    if _TITULO_PROHIBIDO.search(t):
        reasons.append(f"fórmula de lista/sensacionalismo prohibida: {t[:50]!r}")
    return reasons


def run_all_gates(episode_dir) -> dict:
    """Corre todos los gates sobre un episodio y devuelve el resultado."""
    from pathlib import Path
    ep = Path(episode_dir)
    out = {}
    sources_path = ep / "artifacts" / "sources.json"
    script_path = ep / "artifacts" / "script.txt"
    meta_path = ep / "artifacts" / "metadata.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}
    categoria = ""
    episode_json = ep / "episode.json"
    if episode_json.exists():
        categoria = json.loads(episode_json.read_text(encoding="utf-8")).get("categoria", "")
    ficcion = False
    try:
        from . import nichos
        ficcion = bool(categoria) and nichos.es_ficcion(categoria)
    except Exception:
        pass

    for name, fn in [
        ("fuentes", lambda: gate_fuentes(json.loads(sources_path.read_text(encoding="utf-8")), ficcion=ficcion)),
        ("voz", lambda: gate_voz(meta.get("voice", ""))),
        ("contenido_sintetico", lambda: gate_contenido_sintetico(meta)),
        ("anti_duplicado", lambda: gate_anti_duplicado(
            script_path.read_text(encoding="utf-8"), load_publicados())),
    ]:
        try:
            fn()
            out[name] = "pass"
        except (GateFailure, FileNotFoundError, json.JSONDecodeError) as exc:
            out[name] = f"FAIL: {exc}"
    meta["gates"] = out
    meta_path.parent.mkdir(parents=True, exist_ok=True)
    meta_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
    return out


def load_publicados(exclude_slug: str | None = None) -> list[dict]:
    path = config.REGISTRY / "published.jsonl"
    if not path.exists():
        return []
    entries = [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]
    if exclude_slug:
        # Un episodio no compite contra su propia corrida anterior: el gate 4 es para
        # no repetir plantilla entre EPISODIOS DISTINTOS.
        entries = [e for e in entries if e.get("slug") != exclude_slug]
    return list(reversed(entries))
