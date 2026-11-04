"""Beats: el guion se parte en unidades visuales de 1,4-2,2 s.

Es la diferencia entre "video de archivo" y retención de scroll: los canales virales de
este formato muestran 30-40 imágenes por minuto, no una por párrafo. Cada beat lleva
qué se ve (escena + acción), cómo se ve (plano + movimiento de cámara) y qué palabra
queda escrita en pantalla.

Determinista a propósito: la dirección por LLM sigue disponible arriba (el LLM puede
pisar cualquier campo del beat), pero el pipeline no se frena si los proveedores están
sin cuota, y un mapa por palabras clave es auditable escena por escena.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

BEAT_MIN_S = 1.35
BEAT_MAX_S = 2.20

# orden = prioridad; la primera regla que pega gana
ACCIONES: list[tuple[str, str]] = [
    (r"\b(corred?|corrimos|huir|huía|escap|persig|detrás de)\b", "corre"),
    (r"\b(salt|brinc|cayó|caía|tropez|derrumb|colaps)\b", "salta"),
    (r"\b(golpe|puñetazo|pele|dispar|ataque|mordió)\b", "golpea"),
    (r"\b(mir|vi|veía|apareció|asom|ojo)\b", "mira"),
    (r"\b(señal|apunt|indic|mostr|dedo)\b", "senala"),
    (r"\b(grité|grito|grita|aull|berreo)\b", "grita"),
    (r"\b(asust|miedo|terror|tembl|pánico|encog)\b", "asustado"),
    (r"\b(pens|dud|pregunt|razón|calcul)\b", "piensa"),
    (r"\b(cansad|agot|respir|jade|no daba más)\b", "respira"),
    (r"\b(levant|carg|pesaba|mochila|bulto)\b", "levanta"),
    (r"\b(empuj|puerta|abrí|cerro|tranca)\b", "empuja"),
    (r"\b(agach|escond|debajo|silencio|callate)\b", "agachado"),
    (r"\b(gir|volví la cara|miré atrás|espaldas)\b", "gira"),
    (r"\b(abraz|solo|nadie|perdí)\b", "abraza"),
    (r"\b(sorpren|increí|no lo creí|explot|revent)\b", "sorprendido"),
    (r"\b(nada|nunca|jamás|regla|verdad|recordá)\b", "alto"),
    (r"\b(camin|salí|entré|subí|bajé|cruce)\b", "camina"),
]

ESCENARIOS: list[tuple[str, str]] = [
    (r"\b(supermercado|helader|comida|despensa|alimento|conserva)\b", "super"),
    (r"\b(azotea|techo|edificio arriba|borde del edificio)\b", "azotea"),
    (r"\b(cocina|living|casa|puerta de|cuarto|sala)\b", "interior"),
    (r"\b(auto|camion|manubrio|butaca|ruta)\b", "auto"),
    (r"\b(multitud|gente|vecinos|fila|refugio)\b", "multitud"),
    (r"\b(campo|bosque|arbol|pasto|niebla|río)\b", "campo"),
    (r"\b(montana|valle|ruta larga|guardarraya|curva)\b", "montana"),
    (r"\b(pasillo|corredor|escalera|sótano|garaje)\b", "pasillo"),
    (r"\b(tienda|counter|mostrador|kiosco)\b", "tienda"),
    (r"\b(calle|ciudad|vereda|semáforo|neón|barrio)\b", "calle"),
]

FUERTE = re.compile(r"(\d[\d.,]*|nunca|jamás|todos|nadie|muerte|mor|explos|terror|"
                    r"pánico|secreto|mentira|error|regla|brutal|últim)", re.I)

# Fallback de puesta en escena para líneas abstractas: conserva claves de personaje.json.
ACCIONES_ARCO = ["mira", "camina", "piensa", "gira", "senala", "agachado",
                 "respira", "alto", "asustado", "empuja", "sorprendido", "quieto"]
ESCENAS_ARCO = ["interior", "calle", "hospital", "super", "pasillo", "azotea",
                "multitud", "auto", "campo", "tienda"]


def _evitar_tercera_repeticion(valor: str, historial: list[str], alternativas: list[str], indice: int) -> str:
    if len(historial) >= 2 and historial[-1] == historial[-2] == valor:
        for salto in range(len(alternativas)):
            candidato = alternativas[(indice + salto) % len(alternativas)]
            if candidato != valor and candidato != historial[-1]:
                return candidato
    return valor


def _clausulas(texto: str) -> list[str]:
    """Corta por puntuación y por conjunciones largas, sin partir números ni iniciales."""
    limpio = re.sub(r"\s+", " ", texto).strip()
    trozos = re.split(r"(?<=[.:;—])\s+|,\s+(?=(?:y|pero|entonces|así que|porque|después)\b)",
                      limpio)
    out = [t.strip(" .") for t in trozos if t and t.strip(" .")]
    return out or [limpio]


def _trozos(texto: str, dur: float) -> list[tuple[str, float]]:
    """Parte una cláusula por la mitad (palabras y tiempo al 50 %) hasta entrar en la banda.

    Partir sólo el tiempo y dejar el texto entero era el bug: los beats siguientes
    quedaban emparejados con la frase equivocada y un plano de 4 s rompía la retención.
    """
    if dur <= BEAT_MAX_S or len(texto.split()) < 4:
        return [(texto, max(BEAT_MIN_S * 0.8, dur))]
    palabras = texto.split()
    k = len(palabras) // 2
    a, b = " ".join(palabras[:k]), " ".join(palabras[k:])
    wa, wb = max(1, len(a)), max(1, len(b))
    return (_trozos(a, dur * wa / (wa + wb)) + _trozos(b, dur * wb / (wa + wb)))


def _regla(tabla: list[tuple[str, str]], texto: str, defecto: str) -> str:
    for patron, valor in tabla:
        if re.search(patron, texto, re.I):
            return valor
    return defecto


def _pop(texto: str) -> str:
    """La palabra que queda gigante en pantalla: un número si hay, si no la más larga."""
    num = re.search(r"\b\d[\d.,%]*\b", texto)
    if num:
        return num.group(0)
    palabras = [w for w in re.findall(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ]{5,}", texto)]
    return max(palabras, key=lambda w: (len(w), w.isupper()), default="")


def _plano(i: int, n: int, emocion: str, texto: str) -> str:
    if i == 0:
        return "general"
    if emocion in ("sorpresa", "suspenso") or FUERTE.search(texto):
        return "primer_plano"
    if emocion == "tension":
        return "contrapicado"
    if i == n - 1:
        return "detalle"
    return "medio"


def _mov(plano: str, emocion: str, i: int) -> str:
    if i == 0:
        return "push"
    if plano in ("primer_plano", "detalle"):
        return "push_lento"
    if emocion in ("sorpresa", "tension"):
        return "shake"
    return "pan" if i % 2 else "pull"


def _direccion(texto: str, accion: str, escena: str, emocion: str, indice: int,
               contexto: str = "") -> dict:
    """Dirección concreta del beat: idea, metáfora/prop, actuación, cámara y payoff."""
    t = f"{texto} {contexto}".casefold()
    # La idea es la ORACIÓN completa, no el fragmento de 1,5 s: si se corta en 34
    # caracteres, Flux recibe "En 2005, un" y dibuja lo que sea. El foco del beat
    # queda como segundo plano para dar progresión dentro de la misma oración.
    idea_base = re.sub(r"\s+", " ", contexto or texto).strip()[:88]
    foco = re.sub(r"\s+", " ", texto).strip()[:44]
    idea = f"{idea_base} | beat: {foco}"[:115]
    f = texto.casefold()
    t_norm = re.sub(r"\s+", " ", t)
    # Casos documentales: elegir el plano por la idea del beat y su contexto completo,
    # no por una palabra aislada como "operaciones".
    if any(k in t for k in ("ponzi", "inversores nuevos", "dinero nuevo", "inversores anteriores")):
        return {"idea":idea, "prop":"clear three-part Ponzi flow diagram: new investors, central fund, earlier investors",
                "acting":"el personaje conecta fichas desde inversores nuevos hacia el fondo y luego a inversores anteriores",
                "reveal":"el dinero entra por un extremo y sale hacia los pagos anteriores",
                "movimiento_local":"fichas recorren las flechas en secuencia", "camara":"cenital al flujo"}
    if any(k in t for k in ("opciones", "volumen", "negociaba", "negociar", "mercado")):
        return {"idea":idea, "prop":"options market volume chart beside a trade ledger and magnifying glass",
                "acting":"el personaje contrasta la altura de las barras con el libro de operaciones",
                "reveal":"la escala de volumen queda visualmente fuera de proporción",
                "movimiento_local":"la lupa se detiene sobre la barra más alta", "camara":"cenital a la gráfica"}
    if any(k in t for k in ("rendimiento", "consistente", "rentabilidad", "resultados")):
        return {"idea":idea, "prop":"investment returns chart with an unnaturally smooth line beside a volatile market line",
                "acting":"el personaje compara dos curvas sobre la mesa de análisis",
                "reveal":"una línea permanece demasiado uniforme frente a la referencia irregular",
                "movimiento_local":"la regla recorre ambas curvas y se detiene en la diferencia", "camara":"push a las curvas"}
    if any(k in t for k in ("treinta", "casi 30", "cerca de 30", "30 señales", "30 alertas", "informe de 2005", "markopolos")):
        return {"idea":idea, "prop":"2005 analyst report opened to a page covered with about thirty red-flag marks",
                "acting":"el personaje despliega el informe y señala el conjunto de alertas",
                "reveal":"la cámara muestra que son muchas señales acumuladas, no una sola sospecha",
                "movimiento_local":"el informe se abre y las marcas rojas quedan a la vista", "camara":"cenital al informe"}
    if any(k in t for k in ("seis quejas", "seis denuncias", "1992", "2008", "queja sustantiva")):
        return {"idea":idea, "prop":"timeline from 1992 to 2008 with six complaint folders spaced along it",
                "acting":"el personaje coloca seis expedientes sobre una línea de tiempo larga",
                "reveal":"las quejas aparecen en distintos momentos durante años",
                "movimiento_local":"seis carpetas se apoyan una por una sobre la línea", "camara":"paneo por la línea de tiempo"}
    if any(k in t for k in ("no investigó", "investigación competente", "inspector general", "revisión interna")):
        return {"idea":idea, "prop":"oversight review desk with a thick complaint file left unopened beside an empty investigation board",
                "acting":"el personaje abre el informe de revisión y compara el expediente con el tablero vacío",
                "reveal":"el tablero no muestra una investigación suficiente de la hipótesis",
                "movimiento_local":"el expediente se abre frente al tablero sin conexiones", "camara":"sobre hombro al informe"}
    if any(k in t for k in ("diciembre de 2008", "acusó", "acusación", "fraude de valores")):
        return {"idea":idea, "prop":"official securities fraud charge document dated December 2008 beside a courthouse icon",
                "acting":"el personaje coloca la acusación oficial al final de la línea temporal",
                "reveal":"la fecha de la acusación cierra la secuencia de alertas previas",
                "movimiento_local":"el documento se fija en el último punto de la línea", "camara":"push a la fecha final"}
    if any(k in t for k in ("quién verificó", "quien verifico", "pregunta que abre", "cierra el caso")):
        return {"idea":idea, "prop":"the 2005 analyst report closed on the desk, with the verification question marked in red",
                "acting":"el personaje vuelve a la primera página del informe y señala la pregunta",
                "reveal":"la pregunta final devuelve al objeto del primer plano: el informe ignorado",
                "movimiento_local":"el informe se cierra y la marca roja queda visible", "camara":"push al informe"}
    if any(k in f for k in ("alerta", "señal", "queja", "advert")):
        return {"idea":idea, "prop":"complaint file with red-flag marks",
                "acting":"el stickman entrega el sobre; una mano institucional lo aparta",
                "reveal":"el sobre queda fuera del campo mientras pasan hojas de calendario",
                "movimiento_local":"mano acerca y sobre se desliza fuera de cuadro", "camara":"push al sobre"}
    if any(k in f for k in ("rendimiento", "inversión", "inversores", "dinero", "ponzi", "fraude")):
        return {"idea":idea, "prop":"ledger beside an unusually even returns chart",
                "acting":"el personaje compara la gráfica con las anotaciones del registro",
                "reveal":"la gráfica y el registro no muestran el mismo nivel de detalle",
                "movimiento_local":"ficha recorre una curva y vuelve al inicio", "camara":"cenital al diagrama"}
    if any(k in f for k in ("opciones", "operaciones", "negociar", "mercado", "volumen")):
        return {"idea":idea,
                "prop":"trade ledger, magnifying glass and volume chart", "acting":"el personaje compara una columna con una lupa",
                "reveal":"la lupa revela el volumen descrito junto a un registro sin confirmar",
                "movimiento_local":"lupa cruza dos columnas y se detiene", "camara":"desplazamiento lateral"}
    if any(k in f for k in ("sec", "comisión", "inspector", "investigación", "concluyó")):
        return {"idea":idea,
                "prop":"SEC-style office file, complaint pages and desk lamp", "acting":"el personaje abre el expediente y señala una página",
                "reveal":"el expediente queda abierto sobre una investigación incompleta", "movimiento_local":"página pasa y dedo marca la línea",
                "camara":"sobre hombro y acercamiento"}
    if "alerta" in t or "señal" in t or "queja" in t:
        return {"idea":idea, "prop":"complaint file with red-flag marks",
                "acting":"el personaje compara páginas marcadas", "reveal":"las señales se acumulan en un mismo expediente",
                "movimiento_local":"una nueva marca roja aparece en la página", "camara":"push al expediente"}
    if any(k in t for k in ("rendimiento", "inversión", "inversores", "dinero", "ponzi", "fraude")):
        return {"idea":idea, "prop":"ledger beside an unusually even returns chart",
                "acting":"el personaje compara la gráfica con el libro de cuentas",
                "reveal":"el registro requiere verificación independiente", "movimiento_local":"la lupa cruza dos columnas",
                "camara":"cenital al diagrama"}
    if any(k in t for k in ("opciones", "operaciones", "negociar", "mercado", "volumen")):
        return {"idea":idea, "prop":"trade ledger, magnifying glass and volume chart",
                "acting":"el personaje compara una columna con una lupa",
                "reveal":"la escala de operaciones necesita contraste con registros",
                "movimiento_local":"la lupa cruza dos columnas y se detiene", "camara":"desplazamiento lateral"}
    if accion in ("sorprendido", "asustado", "piensa"):
        acting = f"el personaje {accion} ante la evidencia; la mirada conduce al objeto principal"
    else:
        acting = f"el personaje {accion} con contacto visible con el objeto principal"
    props = {
        "interior":"escritorio con expediente y lámpara", "calle":"fachada institucional y puerta", 
        "hospital":"corredor con panel de datos", "super":"estantes como barras de gráfica", 
        "pasillo":"archivo con cajones abiertos", "azotea":"vista urbana con edificios institucionales",
        "multitud":"siluetas frente a una institución", "auto":"carpeta sobre el asiento",
        "campo":"mesa de archivo bajo una luz puntual", "tienda":"mostrador con papeles y lupa"}
    return {"idea":t_norm[:100],"prop":props.get(escena,"objeto de evidencia relacionado con la frase"),
            "acting":acting,"reveal":"el objeto o dato cambia de estado y prepara el beat siguiente",
            "movimiento_local":"mano, prop o marca gráfica realiza una acción corta", 
            "camara":"plano detalle" if indice % 3 == 2 else "paneo motivado"}


def _arco_escenas(texto: str) -> list[str]:
    """Selecciona una secuencia de lugares por el asunto dominante, no al azar por beat."""
    t = texto.casefold()
    if re.search(r"\b(neurona|cerebro|memoria|sueño|ansiedad|conducta|psicolog|dopamina)\w*", t):
        return ["interior", "hospital", "pasillo", "interior"]
    if re.search(r"\b(laboratorio|experimento|científic|átomo|partícula|fósil|planeta|espacio)\w*", t):
        return ["campo", "hospital", "interior", "montana"]
    if re.search(r"\b(empresa|negocio|mercado|invers|dinero|banco|finanza|acciones|fraude|ponzi|madoff)\w*", t):
        # Seis actos coherentes: escritorio -> análisis -> archivo -> mecanismo ->
        # acusación -> cierre que vuelve al informe inicial. Nada de "tienda" ni de
        # una calle genérica para un caso financiero.
        return ["interior", "interior", "interior", "pasillo", "interior", "interior"]
    if re.search(r"\b(código|software|internet|comput|tecnolog|algoritmo|inteligencia artificial)\w*", t):
        return ["interior", "tienda", "pasillo", "calle"]
    return ["interior", "calle", "tienda", "pasillo"]


def _accion_documental(texto: str, indice: int) -> str:
    """Gestos legibles que responden a la frase, con variedad cuando el texto es abstracto."""
    t = texto.casefold()
    if "?" in texto or re.search(r"\b(por qué|cómo|quién|cuál)\b", t):
        return "piensa"
    if re.search(r"\b(señal|dato|cifra|lista|informe|prueba|registro|evidencia|gráfic)\w*", t):
        return "senala"
    if re.search(r"\b(alerta|advirtió|queja|denuncia|riesgo|falló|ignoró)\w*", t):
        return "senala"
    return ("mira", "camina", "gira", "senala", "piensa", "mira")[indice % 6]


# Variantes de pose por familia de objeto. La rotación es deliberada: el render recibe
# una acción distinta cada 1,5 s y nunca tres cortes con la misma figura.
POSES_DOCUMENTO = [
    "abre el expediente y señala una marca roja",
    "compara dos páginas del informe",
    "levanta la hoja hacia la lámpara",
    "marca una línea con un lápiz",
    "cierra la carpeta y la aparta",
]
POSES_GRAFICO = [
    "traza la curva con el dedo",
    "compara la gráfica con el registro",
    "señala el punto más alto del eje",
    "gira la hoja para leer la escala",
    "deja la lupa sobre la cifra",
]
POSES_FLUJO = [
    "conecta una ficha de inversores nuevos con el fondo",
    "mueve una ficha del fondo hacia los inversores anteriores",
    "señala la flecha que cierra el circuito",
    "retira una ficha y muestra que el flujo se corta",
]
POSES_ARCHIVO = [
    "camina con la carpeta bajo el brazo",
    "se detiene y abre un cajón del archivo",
    "señala una etiqueta del estante",
    "compara dos carpetas abiertas",
    "cierra el cajón y sigue caminando",
]
POSES_CALLE = [
    "sostiene el documento oficial contra el pecho",
    "señala la fecha del documento",
    "camina hacia la fachada institucional",
    "se detiene frente a la puerta y mira el edificio",
]
POSES_GENERICAS = [
    "señala el objeto principal",
    "se inclina para leer el detalle",
    "compara dos elementos sobre la mesa",
    "se aparta un paso y mira el conjunto",
]
MICRO_MOV = ["la mano entra en cuadro", "el dedo recorre el borde",
             "la hoja gira", "el objeto se desliza", "la mirada vuelve al centro"]


def _poses_para(prop: str, escena: str) -> list[str]:
    p = prop.casefold()
    if "ponzi" in p or "flow" in p:
        return POSES_FLUJO
    if any(k in p for k in ("file", "report", "complaint")):
        return POSES_DOCUMENTO
    if any(k in p for k in ("ledger", "chart", "timeline", "volume")):
        return POSES_GRAFICO
    if any(k in p for k in ("charge", "courthouse", "official")):
        return POSES_CALLE
    if escena == "pasillo":
        return POSES_ARCHIVO
    if escena == "calle":
        return POSES_CALLE
    return POSES_GENERICAS


def _rotar_pose(d: dict, i: int, escena: str, historial: list[str]) -> None:
    poses = _poses_para(d["prop"], escena)
    elegida = poses[i % len(poses)]
    if len(historial) >= 2 and historial[-1] == historial[-2] == elegida:
        elegida = next((poses[(i + k) % len(poses)] for k in range(1, len(poses))
                       if poses[(i + k) % len(poses)] != historial[-1]), elegida)
    d["acting"] = elegida
    d["movimiento_local"] = MICRO_MOV[i % len(MICRO_MOV)]
    historial.append(elegida)


def dirigir(beats: list[dict]) -> None:
    """Añade progresión de escena, pose y continuidad serial al storyboard determinista."""
    historial_poses: list[str] = []
    for i, b in enumerate(beats):
        d = _direccion(b["texto"], b["accion"], b["escena"], b["emocion"], i,
                       b.get("contexto", ""))
        _rotar_pose(d, i, b["escena"], historial_poses)
        # Si tres cortes seguidos comparten encuadre, se fuerza un plano de detalle.
        if i >= 2 and beats[i-1]["plano"] == beats[i-2]["plano"] == b["plano"]:
            b["plano"] = {"medio": "detalle", "detalle": "medio",
                          "primer_plano": "general", "general": "medio"}.get(b["plano"], b["plano"])
            b["mov"] = _mov(b["plano"], b["emocion"], i)
        b["direccion"] = d
        b["camara"] = d["camara"]
        b["movimiento_local"] = d["movimiento_local"]
        if i:
            prev = beats[i-1]
            b["continuidad"] = {"desde":prev["direccion"]["prop"],
                                "transicion":"match cut por forma/objeto; conservar dirección de movimiento",
                                "hacia":d["prop"]}
        else:
            b["continuidad"] = {"desde":"gancho visual inmediato", "transicion":"entrada directa al objeto", "hacia":d["prop"]}


def plan(segments: list[dict], emociones: list[str] | None = None,
         escena_base: str = "calle") -> list[dict]:
    """segments: [{texto, dur_s}] de la narración real de Piper. Devuelve beats con t0/t1."""
    emociones = emociones or []
    beats: list[dict] = []
    t = 0.0
    acciones_previas: list[str] = []
    arco = _arco_escenas(" ".join(str(s.get("texto", "")) for s in segments))
    for si, seg in enumerate(segments):
        dur = float(seg.get("dur_s") or 0.0)
        if dur <= 0:
            continue
        clausulas = _clausulas(seg["texto"])
        pesos = [max(1, len(c)) for c in clausulas]
        total = sum(pesos)
        trozos: list[tuple[str, float, str]] = []
        for texto_c, p in zip(clausulas, pesos):
            trozos += [(t, d, texto_c) for t, d in _trozos(texto_c, dur * p / total)]
        for ci, (texto, d, oracion) in enumerate(trozos):
            emocion = (emociones[si] if si < len(emociones)
                       else _regla([(r"nunca|jamás|nadie|secreto", "suspenso"),
                                    (r"\d|por qué|qué pasaría", "curiosidad"),
                                    (r"brutal|error|muerte", "tension")], texto, "neutralidad"))
            accion = _regla(ACCIONES, texto, "") or _accion_documental(texto, len(beats))
            acciones_validas = list(dict.fromkeys(v for _, v in ACCIONES)) + ACCIONES_ARCO
            accion = _evitar_tercera_repeticion(accion, acciones_previas, acciones_validas, len(beats))
            etapa = min(len(arco) - 1, int(si * len(arco) / max(1, len(segments))))
            escena = _regla(ESCENARIOS, texto, "") or arco[etapa]
            plano = "medio"  # se asigna con el total real al terminar de construir los beats
            fx = []
            if FUERTE.search(texto):
                fx.append("flash")
            if accion in ("corre", "salta", "golpea"):
                fx.append("lineas")
            beats.append({
                "i": len(beats), "t0": round(t, 3), "t1": round(t + d, 3), "dur_s": round(d, 3),
                "texto": texto, "pop": _pop(texto), "escena": escena, "accion": accion,
                "plano": plano, "mov": _mov(plano, emocion, len(beats)),
                "emocion": emocion, "fx": fx, "segmento": si, "contexto": oracion,
                "oracion": oracion,
            })
            acciones_previas.append(accion)
            t += d
    for i, beat in enumerate(beats):
        beat["plano"] = _plano(i, len(beats), beat["emocion"], beat["texto"])
        beat["mov"] = _mov(beat["plano"], beat["emocion"], i)
    # recorte final: el plan debe medir EXACTAMENTE lo que mide el audio. El piso de
    # BEAT_MIN_S*0.8 por cláusula corta infla el total (medido: +0,27 s en 15 s), y ese
    # exceso queda como un final mudo después de la última palabra.
    objetivo = sum(float(s.get("dur_s") or 0.0) for s in segments)
    if beats and objetivo > 0 and abs(t - objetivo) > 0.005:
        factor = objetivo / t
        acum = 0.0
        for b in beats:
            b["dur_s"] = round(b["dur_s"] * factor, 3)
            b["t0"] = round(acum, 3)
            acum += b["dur_s"]
            b["t1"] = round(acum, 3)
    dirigir(beats)
    return beats


def escribir(ep, beats: list[dict]) -> Path:
    path = ep.dir / "artifacts" / "beats.json"
    path.write_text(json.dumps({"beats": beats,
                                "densidad": round(len(beats) / max(0.001, sum(b["dur_s"] for b in beats)) * 60, 1)},
                               ensure_ascii=False, indent=1), encoding="utf-8")
    return path
