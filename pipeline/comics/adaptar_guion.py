"""Guion verificado -> STORYBOARD de cómic con oficio (contrato comics.v2).

Orden del dueño (2026-11-06): NO más "PDF de fotos con captions". El cómic es
un libro: mínimo 15 viñetas por capítulo, repartidas en PÁGINAS con grillas
reales de 3 bandas (ej.: 3/4/3 — tres arriba, cuatro al medio, tres abajo),
gancho de apertura, silencio negro de descompresión, cliffhanger de página y
remate final. La retención en cómic es de LECTURA: cada página se cierra
dejando la latencia de "¿qué viene?" para girar la página.

Reglas duras:
  - Nada entra fuera del guion verificado: cada viñeta cita LITERALMENTE la
    oración de origen (ancla_guion) y arrastra el claim verificado más cercano.
  - El humor negro es de ENCUADRE (framing del narrador sobre hechos ya
    citados): un remate jamás introduce un hecho nuevo.
  - El texto se compone FUERA del generador (globos/captions en componer.py).
"""
from __future__ import annotations

import json
import os
import re
import time

from ..episode import Episode

NARRACION_MAX = 120
# Presupuesto de palabras del caption (regla del QC: "no se lee de un vistazo").
# Vive acá para que adaptar y qc compartan el mismo número: antes el QC lo tenía
# hardcodeado y el adaptar no lo aplicaba, así que el book quedaba bloqueado.
NARRACION_MAX_PALABRAS = int(os.environ.get("COMICS_CAPTIONS_MAX_PALABRAS", "18"))
MIN_BEATS = 13            # oraciones mínimas para sostener 15 viñetas con ritmo
MAX_BEATS = 18            # techo de beats por capítulo -> 20 viñetas con ritmo
VINETAS_MIN = 15

ROLES_RITMO = ("gancho", "contexto", "escala", "silencio", "giro",
               "cliffhanger", "remate")
PLANOS = ("establecido", "general", "medio", "primer_plano", "detalle",
          "contrapicado")
ACCIONES = ("establece", "explica", "avanza", "descubre", "conecta", "alerta",
            "comprueba", "infiltra", "revisa", "imputa", "paga", "cierra")

# grillas de página: EXACTAMENTE 3 bandas horizontales, 1-4 viñetas por banda.
# Índice = total de la página. Ej. GRILLAS[10] = (3,4,3) -> 3/4/3 como pide el dueño.
GRILLAS = {
    4: (1, 2, 1), 5: (1, 2, 2), 6: (2, 2, 2), 7: (2, 3, 2), 8: (3, 2, 3),
    9: (3, 3, 3), 10: (3, 4, 3), 11: (4, 4, 3), 12: (4, 4, 4),
}
GRILLAS_FALLBACK = (10, 9, 8, 7, 6, 5, 4)

# Pool de encuadres (humor negro / tensión de encuadre). Determinista por índice.
ENCUADRES = {
    "gancho":      ["Spoiler: nada de esto termina bien. Seguí leyendo.",
                    "La noche recién arrancaba."],
    "giro":        ["Detalle: nadie lo vio venir. O todos lo vieron y nadie dijo nada.",
                    "Eso no tiene segundo lectura."],
    "silencio":    ["(Silencio. Hasta la placa del edificio dejó de hablar.)",
                    "(…)"],
    "cliffhanger": ["Y faltaba lo peor. Girá la página.",
                    "Lo que vino después no estaba en el libreto de nadie."],
    "remate":      ["Caso cerrado. La pregunta, no.",
                    "Fin del capítulo. El interrogante sigue colgado en otra pared."],
}


def _oraciones(script: str) -> list[str]:
    limpio = re.sub(r"^#.*$", "", script, flags=re.MULTILINE)
    bruto = re.sub(r"\s+", " ", limpio).strip()
    partes = re.split(r"(?<=[.!?])\s+", bruto)
    return [p.strip() for p in partes if len(p.strip()) > 3]


def fuentes_de(ep: Episode) -> list[dict]:
    """Claims ya verificados por el gate del episodio."""
    p = ep.artifacts / "sources.json"
    try:
        datos = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    claims = datos.get("claims") if isinstance(datos, dict) else datos
    vistas = []
    for c in claims or []:
        if not isinstance(c, dict):
            continue
        urls = []
        for u in c.get("sources") or []:
            # sources.json guarda {url, publisher} — resolvemos SIEMPRE al url
            if isinstance(u, dict):
                u = u.get("url") or u.get("fuente") or ""
            u = str(u).strip()
            if u:
                urls.append(u)
        vistas.append({"afirmacion": str(c.get("claim", "")).strip(),
                       "fuentes": urls,
                       "verdict": str(c.get("verdict", ""))})
    return [v for v in vistas if v["afirmacion"]]


def asignar_afirmacion(texto: str, claims: list[dict]) -> int | None:
    """Índice del claim más parecido por overlap de tokens (None si nada pega)."""
    pal = set(re.findall(r"\w{5,}", (texto or "").lower()))
    mejor, mejor_n = None, 1
    for idx, c in enumerate(claims):
        toks = set(re.findall(r"\w{5,}", c["afirmacion"].lower()))
        n = len(pal & toks)
        if n > mejor_n:
            mejor, mejor_n = idx, n
    return mejor


def _recorte(texto: str, limite: int) -> str:
    """Recorte editorial: oración completa si entra; palabra + '…' si no."""
    texto = re.sub(r"\s+", " ", texto or "").strip()
    if len(texto) <= limite:
        return texto
    corte = texto[:limite]
    abbrs = ["U.S.", "St.", "Dr.", "Mt.", "Sr.", "Sra."]
    escaneo = corte
    for a in abbrs:
        escaneo = escaneo.replace(a, a[:-1] + "\x00")   # mismo largo, punto camuflado
    puntos = [m.end() for m in re.finditer(r"[.!?](?=\s|$)", escaneo)]
    if puntos:
        return corte[:puntos[-1]].strip()
    return corte.rsplit(" ", 1)[0].rstrip(",;:") + "…"


def _recorte_palabras(texto: str, maximo: int) -> str:
    """Recorta por presupuesto de palabras, preferiendo frases completas.

    1) oraciones completas que entren; 2) cláusulas separadas por , : ; que entren;
    3) corte en palabra con '…'. Nunca deja una cláusula a mitad sin marcar.
    """
    limpio = re.sub(r"\s+", " ", texto or "").strip()
    if len(limpio.split()) <= maximo:
        return limpio
    for sep in (r"(?<=[.!?])\s+", r"(?<=[:,;])\s+"):
        partes = re.split(sep, limpio)
        acc, n = [], 0
        for parte in partes:
            w = len(parte.split())
            if n + w > maximo:
                break
            acc.append(parte)
            n += w
        if acc:
            return " ".join(acc).rstrip(",;:")
    return " ".join(limpio.split()[:maximo]).rstrip(",;:") + "…"


def _aplicar_presupuesto(paneles: list[dict], maximo: int = NARRACION_MAX_PALABRAS) -> int:
    """Deja cada caption (base + encuadre) dentro del presupuesto de palabras del QC.

    El encuadre `[...]` es parte del diseño y entra completo: si la suma supera el
    cupo, primero se prueba con un encuadre más corto del mismo rol y sólo después
    se recorta la base. Devuelve cuántas viñetas se ajustaron.
    """
    ajustadas = 0
    for p in paneles:
        narr = re.sub(r"\s+", " ", str(p.get("narracion") or "")).strip()
        if len(narr.split()) <= maximo:
            continue
        m = re.match(r"^(?P<base>.*?)\s*\[(?P<encuadre>[^\]]*)\]\s*$", narr, re.S)
        if not m:
            p["narracion"] = _recorte_palabras(narr, maximo)
            ajustadas += 1
            continue
        base, encuadre = m.group("base"), m.group("encuadre")
        rol = str(p.get("rol_ritmico") or "")
        pool = ENCUADRES.get(rol) or []
        alternativa = next((e for e in sorted(pool, key=lambda x: len(x.split()))
                            if len(f"{base} [{e}]".split()) <= maximo), None)
        if alternativa:
            p["narracion"] = f"{base} [{alternativa}]"
            ajustadas += 1
            continue
        sobran = len(narr.split()) - maximo
        p["narracion"] = f"{_recorte_palabras(base, max(1, len(base.split()) - sobran))} [{encuadre}]"
        ajustadas += 1
    return ajustadas


def _fijo(pool: tuple[str, ...], k: int) -> str:
    """Elección determinista de pool (nada de azar)."""
    return pool[k % len(pool)]


def _impacto(oracion: str, claims: list[dict]) -> int:
    """Puntuación de golpe dramático determinista (elige giro/silencio)."""
    t = oracion.lower()
    g = sum(1 for kw in ("nunca", "jamás", "sigue", "resuelto", "millones",
                         "pérdida", "perdida", "dólares", "noche", "protección",
                         "police", "policí", "crimen", "mayor", "tsky", "vermeer")
            if kw in t)
    if asignar_afirmacion(oracion, claims) is not None:
        g += 2
    return g


def _agrupar(oraciones: list[str]) -> list[list[str]]:
    """1 oración por beat si hay <= MAX_BEATS; si no, bloques consecutivos."""
    if len(oraciones) <= MAX_BEATS:
        return [[o] for o in oraciones]
    n = MAX_BEATS
    bloques: list[list[str]] = [[] for _ in range(n)]
    i = 0
    for j, o in enumerate(oraciones):
        destino = min(n - 1, (j * n) // len(oraciones))
        while destino > 0 and len(bloques[destino]) > len(bloques[destino - 1]) + 1:
            destino = destino - 1  # repartija pareja (determinista aprox)
        bloques[destino].append(o)
        i += 1
    return [b for b in bloques if b]


def _grillas_para(n: int) -> list[list[int]]:
    """Páginas con grillas de 3 bandas que suman EXACTAMENTE n viñetas."""
    paginas = 2
    # primer intento: repartija 60/40 con grillas reales
    for t1 in sorted(GRILLAS, key=lambda t: abs(t - n * 0.6)):
        restante = n - t1
        if restante in GRILLAS:
            return [list(GRILLAS[t1]), list(GRILLAS[restante])]
    # fallback: cascada determinista (n<=12 cabe en una página; si no, mejor-reparto)
    for t1 in GRILLAS_FALLBACK:
        restante = n - t1
        if restante in GRILLAS:
            return [list(GRILLAS[t1]), list(GRILLAS[restante])]
    return [list(GRILLAS[min(GRILLAS, key=lambda t: abs(t - n))])]


def _determinista(oraciones: list[str], claims: list[dict], titulo: str) -> dict:
    """Storyboard sin LLM: ritmo de cómic construido con reglas, auditable."""
    if len(oraciones) < MIN_BEATS:
        raise SystemExit(
            f"comics: el guion tiene {len(oraciones)} oraciones; un capítulo de oficio "
            f"necesita >= {MIN_BEATS} beats para {VINETAS_MIN}+ viñetas con ritmo y "
            "cliffhangers. Se apaga sin publicar; el video sigue su ruta.")
    beats = _agrupar(oraciones)
    n_beats = len(beats)
    # viñetas = beats + 2 de ritmo: gancho flash-forward (cold open) + silencio negro
    n_v = min(MAX_BEATS + 2, n_beats + 2)
    if n_v < VINETAS_MIN:
        raise SystemExit(
            f"comics: {n_v} viñetas < mínimo del dueño ({VINETAS_MIN}) — se apaga sin publicar")

    # golpe dramático determinista (para elegir el silencio Y el flash-forward)
    idx_golpe = max(range(n_beats - 1),
                    key=lambda k: _impacto(beats[k][0] if len(beats[k]) == 1
                                           else " ".join(beats[k]), claims))
    # el gancho ROBA la oración de máximo impacto y la muestra AL ABRIR (cold
    # open, dispositivo clásico de historieta): después reaparece en su lugar
    # cronológico como set-up/payoff. Cero repetición de caption, cero hecho nuevo.
    orden: list[str | int] = ["gancho_ff"]
    for b in range(n_beats):
        if b == idx_golpe + 1:
            orden.append("silencio")
        orden.append(b)
    orden = orden[:n_v]

    # del gancho flash-forward: roba una oración que reaparezca AL MENOS una
    # página después (payoff cruzado) — nunca dos veces en la misma página
    grillas = _grillas_para(n_v)
    n_pg1 = sum(grillas[0])
    beats_pg1 = sum(1 for c in orden[:n_pg1] if isinstance(c, int))
    if beats_pg1 < n_beats - 1:
        idx_gancho = max(range(beats_pg1, n_beats - 1),
                         key=lambda k: _impacto(" ".join(beats[k]), claims))
    else:
        idx_gancho = idx_golpe

    paneles = []
    pg, fila, pos_r = 1, 1, 1
    for k, clave in enumerate(orden, 1):
        if clave == "gancho_ff":
            cita = " ".join(beats[idx_gancho])
            credo = _recorte(cita, NARRACION_MAX - 34)
            accion, plano = "gancho", "detalle"      # flash-forward: primerísimo plano
            actor = "escena"
        elif clave == "silencio":
            cita = " ".join(beats[max(0, idx_golpe)])
            credo, accion, plano = "", "silencio", "detalle"
            actor = "escena"
        else:
            b = int(clave)
            cita = " ".join(beats[b])
            credo = _recorte(cita, NARRACION_MAX)
            accion = ACCIONES[b % len(ACCIONES)]
            plano = PLANOS[(b * 2 + 1) % len(PLANOS)]
            actor = "narrador_canal"
        claim = asignar_afirmacion(cita, claims)
        paneles.append({
            "i": k, "pagina": pg, "fila": fila, "pos": pos_r,
            "rol_ritmico": "",             # se asigna en _asignar_ritmo
            "actor": actor, "escena": "", "accion": accion, "plano": plano,
            "narracion": credo, "dialogo": None,
            "caption_via": "determinista",
            "ancla_guion": _recorte(cita, 200),
            "claim_idx": claim,
            "fuentes": list(claims[claim]["fuentes"]) if claim is not None else [],
        })
        bp = grillas[pg - 1]
        pos_r += 1
        if pos_r > bp[fila - 1]:
            pos_r = 1
            fila += 1
            if fila > len(bp):
                fila = 1
                pg += 1
    datos = {"titulo": titulo, "estilo_visual":
             "stickman noir: silueta negra, contorno blanco grueso, tinta negra cálida, "
             "acento rojo, marco grueso con tachuelas, absolutamente sin texto dibujado",
             "grillas": grillas, "paneles": paneles}
    return datos


def _encuadre_para(espacio: int, rol: str, k: int) -> str:
    """Encuadre de ritmo que entra COMPLETO en el espacio disponible del caption
    (nunca un corchete cortado a mitad — eso grita bug ante el lector)."""
    pool = ENCUADRES.get(rol) or []
    if espacio < 8 or not pool:
        return ""
    candidatos = [e for e in pool if len(e) <= espacio]
    if candidatos:
        return candidatos[(k - 1) % len(candidatos)]
    e = min(pool, key=len)          # incluso cortada, gana la más corta del pool
    return e[:max(0, espacio - 3)].rstrip() + "…"


def _asignar_ritmo(paneles: list[dict], grillas: list[list[int]]) -> None:
    """Roles de ritmo por posición + encuadres de humor negro (sobre facts citados).

    Clave de oficio: el cierre de página lleva cliffhanger (teaser de "¿qué
    viene?"). Si la viñeta negra de silencio cayó exactamente en el cierre,
    el cliffhanger NO se pierde: retrocede al panel anterior de esa página
    (tensión + silencio = beat clásico de historieta).
    """
    cortes = []
    acum = 0
    for g in grillas:
        acum += sum(g)
        cortes.append(acum)
    fin_por_pagina = cortes[:-1]            # índice (1-based) del último panel de cada página
    n = len(paneles)
    cierres = set()
    for c in fin_por_pagina:
        c = min(max(1, c), n)
        if str(paneles[c - 1].get("narracion", "")).strip() == "" and c >= 2:
            cierres.add(c - 1)              # el silencio es la BOCA del teaser: retrocede
        else:
            cierres.add(c)
    for k, p in enumerate(paneles, 1):
        if str(p.get("narracion", "")).strip() == "":
            rol = "silencio"                # viñeta negra: cierre de descompresión
        elif k == 1:
            rol = "gancho"
        elif k == n:
            rol = "remate"
        elif k in cierres:
            rol = "cliffhanger"
        else:
            rol = "escala" if p.get("claim_idx") is not None else "contexto"
        p["rol_ritmico"] = rol
        # encuadre (entre corchetes, le entra corto al caption — es de ritmo, no de hecho)
        if rol == "silencio":
            p["narracion"] = _fijo(ENCUADRES["silencio"], k)
        elif rol in ENCUADRES:
            base = _recorte(str(p["narracion"]), NARRACION_MAX - 34)
            if base:
                espacio = NARRACION_MAX - len(base) - 3
                p["narracion"] = f"{base} [{_encuadre_para(espacio, rol, k)}]"


def adaptar(ep: Episode, *, forzar: bool = False) -> dict:
    """Construye comics/guion_paneles.json (v2) del episodio."""
    script_path = ep.artifacts / "script.txt"
    if not script_path.exists():
        raise SystemExit("comics: sin script.txt — corre primero la etapa guion del video")
    script = script_path.read_text(encoding="utf-8")
    meta = ep.metadata()
    claims = fuentes_de(ep)
    if not claims:
        raise SystemExit("comics: sin claims verificados en artifacts/sources.json")
    datos = _determinista(_oraciones(script), claims, str(meta.get("title") or ep.slug))
    datos.setdefault("titulo", str(meta.get("title") or ep.slug))
    datos["schema"] = "comics.v2"
    datos["slug"] = ep.slug
    datos["categoria"] = meta.get("categoria", "")
    _asignar_ritmo(datos["paneles"], datos["grillas"])
    # Pulido opcional con LLM (COMICS_CAPTIONS_LLM=1): nunca cambia un hecho y
    # cualquier fallo deja el caption determinista. Va después del ritmo para
    # conservar el encuadre `[...]` que compone el libro.
    try:
        from .captions import pulir
        resumen_captions = pulir(datos["paneles"], titulo=datos["titulo"], slug=ep.slug)
    except Exception as exc:  # noqa: BLE001 — el cómic jamás tumba la corrida
        resumen_captions = {"via": "determinista", "guard": "error",
                            "propuestas": 0, "aceptadas": 0,
                            "motivos": [str(exc)[:160]]}
    vacias = [p["i"] for p in datos["paneles"] if not str(p.get("narracion", "")).strip()]
    if vacias:
        raise SystemExit(f"comics: viñetas sin narración ({vacias}) — no se publica a ciegas")
    # Presupuesto de palabras del QC: sin esto el book queda bloqueado aunque el
    # caption sea bueno (medido 2026-11-10: robo-gardner-13-obras, viñetas 8 y 13).
    _aplicar_presupuesto(datos["paneles"])
    datos["procedencia"] = {"adaptado_el": time.strftime("%Y-%m-%d %H:%M:%S"),
                            "via": "determinista",
                            "via_captions": resumen_captions.get("via", "determinista"),
                            "captions": resumen_captions,
                            "n_claims": len(claims),
                            "vinetas": len(datos["paneles"]),
                            "paginas": len(datos["grillas"])}
    fuera = ep.dir / "comics" / "guion_paneles.json"
    fuera.parent.mkdir(parents=True, exist_ok=True)
    fuera.write_text(json.dumps(datos, ensure_ascii=False, indent=2), encoding="utf-8")
    return datos


def guardar(ep: Episode, datos: dict) -> None:
    fuera = ep.dir / "comics" / "guion_paneles.json"
    fuera.parent.mkdir(parents=True, exist_ok=True)
    fuera.write_text(json.dumps(datos, ensure_ascii=False, indent=2), encoding="utf-8")
