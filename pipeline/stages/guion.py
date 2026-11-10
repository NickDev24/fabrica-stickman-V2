"""Etapa 2: guion con ángulo narrativo propio + gate anti-duplicado (gate 4)."""
from __future__ import annotations

import json
import re

from .. import gates, llm, nichos
from ..episode import Episode


def elegir_angulo(ep: Episode, previos: list[dict]) -> str:
    """El pipeline propone y ELIGE su ángulo: descarta los que huelan a episodios previos."""
    sources = ep.read_json("sources.json")
    claims = "\n".join(f"- {c['claim']}" for c in sources["claims"])
    prompt = (
        f"Canal 'Pulso Curioso'. Tema con estas afirmaciones verificadas:\n{claims}\n\n"
        "Proponé 5 ÁNGULOS NARRATIVOS distintos (una frase cada uno: el recorte específico "
        "que hace única esta historia — el cómo, la paradoja, el error, el contexto olvidado). "
        "IMPORTANTE: el ángulo debe derivar SOLO de las afirmaciones listadas; no introduzcas "
        "hechos, personas ni escenas que no estén en ellas. Evitá ángulos genéricos tipo "
        "'la historia de X'. Devolvé sólo JSON: {\"angulos\":[\"...\",\"...\"]}"
    )
    answer = llm.chat([{"role": "user", "content": prompt}], max_tokens=600,
                      temperature=0.9, tag="angulos", episode=ep.slug)
    angulos = re.findall(r'"([^"]{15,200})"', answer) or json.loads(answer)["angulos"]
    best, best_score = angulos[0], float("inf")
    for a in angulos[:5]:
        score = max((gates._structure_similarity(gates._structure(a), gates._structure(p["script"]))
                     for p in previos[:gates.config.COMPARE_LAST_N]), default=0.0)
        if score < best_score:
            best, best_score = a, score
    print(f"  ángulo elegido automáticamente (similitud {best_score:.2f} con lo ya producido): {best[:80]}")
    return best


def hook_violado(script: str) -> str | None:
    """Deteca el anti-patrón de hook en la PRIMERA oración del guion (sin LLM).

    El contrato editorial (ACTO 1 del prompt) exige arrancar en el conflicto/dato más
    fuerte: "la SEC tuvo las pruebas y las ignoró ocho años". Un hook que arranca con
    fecha o contexto ("En 2005, un...") no frena el scroll — así salió el primer
    episodio generado, y ningún chequeo lo partaba: se escribe el chequeo que falta.
    """
    prosa = "\n".join(l for l in script.splitlines() if not l.lstrip().startswith("#"))
    prosa = re.sub(r"\s+", " ", prosa).strip()
    if not prosa:
        return "el guion no tiene prosa (sólo título)"
    primera = re.split(r"(?<=[.!?])\s+", prosa, maxsplit=1)[0]
    if re.match(r"^En\s+(el a[ñn]o\s+)?(1[5-9]\d{2}|20\d{2})\b", primera, re.I):
        return f"hook arranca con fecha/contexto: {primera[:80]!r}"
    if re.match(r"^En\s+(enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|"
                r"setiembre|octubre|noviembre|diciembre)\b", primera, re.I):
        return f"hook arranca con fecha/contexto: {primera[:80]!r}"
    if re.match(r"^(la historia|este es el caso|en un mundo|hay una|\barcamos\b)",
                primera, re.I):
        return f"hook de contexto, no de conflicto: {primera[:80]!r}"
    return None


def hook_pregunta(script: str) -> str | None:
    """Contrato del GANCHO DORADO (stickman-video-director, latido 1): pregunta que retiene.

    Los primeros 3 segundos narrados deben ser una PREGUNTA en segunda persona que abra
    un vacío de curiosidad: concreta, contraintuitiva, SIN resolverla. Las medias reglas:
    - 4 a 16 palabras (Tomas narra 2,36 palabras/segundo medido: 3 segundos ≈ 7 palabras).
    - Debe cerrar con signo de interrogación.
    - Prohibida la platitud genérica "¿Sabías que...?" (no abre vacío: invita a scroll).
    """
    prosa = "\n".join(l for l in script.splitlines() if not l.lstrip().startswith("#"))
    prosa = re.sub(r"\s+", " ", prosa).strip()
    if not prosa:
        return "el guion no tiene prosa (sólo título)"
    primera = re.split(r"(?<=[.!?])\s+", prosa, maxsplit=1)[0]
    if not primera.rstrip().endswith("?"):
        return f"el gancho no es pregunta: {primera[:80]!r}"
    palabras = [w for w in re.sub(r"[¿?¡!.,;:—–]", " ", primera).split() if w]
    if not 4 <= len(palabras) <= 16:
        return f"pregunta gancho fuera de rango ({len(palabras)} palabras): {primera[:70]!r}"
    if re.search(r"^\s*[¿?]\s*sab[ií](as|es)\s+que\b", primera, re.I):
        return "platitud prohibida '¿Sabías que...?': no abre vacío, invita a scroll"
    return None


def reparar_hook(script: str, titulo: str, angulo: str) -> str:
    """Reescribe la PRIMERA oración con el LLM, manteniendo el resto del guion intacto."""
    prosa = "\n".join(l for l in script.splitlines() if not l.lstrip().startswith("#"))
    prosa = re.sub(r"\s+", " ", prosa).strip()
    primera, resto = re.split(r"(?<=[.!?])\s+", prosa, maxsplit=1) or (prosa, "")
    prompt = (
        f"Canal de documentales animados. Título: {titulo}. Ángulo: {angulo}.\n"
        "La PRIMERA oración del guion viola el GANCHO DORADO (latido 1 del motor de 5 "
        "latidos): arranca con fecha/contexto o es una afirmación plana, y eso no frena "
        "el scroll. Reescribí SOLO esa oración como una PREGUNTA que retiene: segunda "
        "persona (vos/tú), apuntada al vacío de curiosidad de esta historia, concreta y "
        "contraintuitiva, máximo 14 palabras, cerrada con signo ?, español rioplatense. "
        "Prohibido '¿Sabías que...?', prohibido arrancar con fecha, prohibido resolver la "
        "pregunta. La fecha-contexto puede aparecer recién en la segunda oración.\n\n"
        f"ORACIÓN ACTUAL: {primera}\n"
        f"CONTEXTOS DEL GUION (para no inventar hechos): {resto[:600]}\n\n"
        "Devolvé SOLO la nueva pregunta, sin comillas ni preámbulos."
    )
    nueva = ""
    try:
        nueva = llm.chat([{"role": "user", "content": prompt}], max_tokens=90,
                         temperature=0.6, tag="hook-fix", episode="")[:400].strip()
    except Exception:  # noqa: BLE001 — sin LLM no se repara; que decida el gate
        return script
    nueva = re.split(r"(?<=[.!?])\s+", nueva)[0].strip()
    # la reparación DEBE devolver pregunta: si no, no se pisa el guion (decide el gate)
    if not nueva or not nueva.rstrip().endswith("?") or hook_violado(nueva + " " + resto):
        return script  # no se pisa el guion con algo peor; el gate decide el destino
    return script.replace(primera, nueva, 1)


def asegurar_titulo(ep: Episode, titulo: str, angulo: str) -> str:
    """GATE 6 antes de gastar render: el título entra al prompt, a la portada y a YouTube.

    Fuera de rango o con fórmula de lista se corrige acá, que cuesta 60 tokens, y no después
    de tres minutos de TTS y 140 planos. El título aprobado se escribe en el estado del
    episodio: publicacion.py y captacion.py leen de ahí, así el arreglo no se pierde.
    """
    from factory import parametros
    lo, hi = parametros.rango_titulo()
    vigente = (titulo or "").strip()
    for intento in range(3):
        motivos = gates.gate_titulo(vigente, lo, hi)
        if not motivos:
            estado = ep.read_state()
            if estado.get("title") != vigente:
                estado["title"] = vigente
                ep.write_state(estado)
                print(f"  GATE TÍTULO: reparado → {vigente!r} ({len(vigente)} caracteres)")
            else:
                print(f"  GATE TÍTULO: PASS ({len(vigente)} caracteres)")
            return vigente
        print(f"  GATE TÍTULO: {motivos[0]} — reescribiendo (intento {intento + 1}/3)…")
        try:
            nuevo = llm.chat(
                [{"role": "user", "content":
                  "Canal de documentales animados estilo stickman, curiosidades verificadas.\n"
                  f"Historia: {angulo}\nTítulo actual: {vigente}\n"
                  f"Motivo de rechazo: {motivos[0]}\n"
                  f"Reescribí el título con {lo}-{hi} caracteres: sujeto concreto y promesa de "
                  "revelación SIN resolverla, español rioplatense. Prohibido 'top N', 'N cosas', "
                  "'N secretos', 'N datos', 'increíble', 'sabías que'. Devolvé sólo el título."}],
                max_tokens=60, temperature=0.7, tag="titulo-fix", episode=ep.slug).strip()
        except Exception as exc:  # noqa: BLE001 — sin LLM no hay reescritura posible
            raise SystemExit(f"GATE TÍTULO BLOQUEA EL EPISODIO: {motivos[0]} "
                             f"(y no se pudo reescribir: {str(exc)[:70]})")
        vigente = nuevo.strip('"').splitlines()[0].strip() if nuevo else vigente
    # La tercera reescritura puede haber quedado válida: se evalúa ANTES de rendirse.
    # Antes se indexaba motivos[0] de un título que ya pasaba (lista vacía) → IndexError
    # que mataba el episodio justo después de arreglar el título.
    motivos = gates.gate_titulo(vigente, lo, hi)
    if not motivos:
        estado = ep.read_state()
        if estado.get("title") != vigente:
            estado["title"] = vigente
            ep.write_state(estado)
        print(f"  GATE TÍTULO: reparado tras reescrituras → {vigente!r} ({len(vigente)} caracteres)")
        return vigente
    raise SystemExit(f"GATE TÍTULO BLOQUEA EL EPISODIO: tres reescrituras y ningún título pasó "
                     f"{lo}-{hi} caracteres sin fórmula de lista ({motivos[0]})")


def _guion_en_dos_pasos(prompt: str, ep: Episode, lo_palabras: int, hi_palabras: int) -> str:
    """El guion completo, escrito por mitades.

    Un disparo único no da 1500 palabras: el techo de tokens del proveedor corta el texto
    y el episodio sale de dos minutos. Cada mitad pide la suya y la segunda continúa sobre
    la primera, así el gancho queda arriba y la revelación abajo, donde van.
    """
    mitad = (lo_palabras + hi_palabras) // 2
    primero = llm.chat(
        [{"role": "system", "content": prompt},
         {"role": "user", "content":
             f"Escribí SOLO la primera mitad del guion: el gancho, el planteamiento y la "
             f"exploración con sus bucles (≈{mitad} palabras). Cortá en mitad del viaje, con un "
             "bucle abierto: todavía no cobres la promesa ni saques la revelación. "
             "La PRIMERA frase es la pregunta del LATIDO 1; nada antes."}],
        temperature=0.8, max_tokens=1100, tag="guion-1", episode=ep.slug).strip()
    segundo = llm.chat(
        [{"role": "system", "content": prompt},
         {"role": "assistant", "content": primero},
         {"role": "user", "content":
             f"Seguí EXACTAMENTE donde quedaste, sin repetir ni una frase de lo anterior "
             f"(≈{mitad} palabras): punto de inflexión con la revelación que responde la pregunta "
             "del gancho, giro práctico y cierre memorable con debate abierto. "
             "Devolvé sólo la prosa de esta segunda mitad."}],
        temperature=0.7, max_tokens=1100, tag="guion-2", episode=ep.slug).strip()
    return f"{primero}\n\n{segundo}".strip()


def guion(ep: Episode, angulo: str | None = None) -> None:
    previos = gates.load_publicados(exclude_slug=ep.slug)
    if not angulo:
        angulo = elegir_angulo(ep, previos)
    if len(angulo.strip()) < 15:
        raise SystemExit("ángulo demasiado débil para cumplir el gate 4; reintentando la próxima corrida.")

    sources = ep.read_json("sources.json")
    claims = "\n".join(f"- {c['claim']} (veredicto: {c['verdict']})" for c in sources["claims"])
    estado = ep.read_state()
    titulo = asegurar_titulo(ep, estado["title"], angulo)
    categoria = estado.get("categoria", "")
    perfil = nichos.canal_de(categoria)
    es_fic = bool(perfil["ficción"])
    modo = ("FICCIÓN ORIGINAL (propiedad intelectual propia; prohibido copiar canales, "
            "guiones ni personajes existentes; referencias externas solo como inspiración "
            "de formato)" if es_fic
            else "documental verificable (cada hecho sale de las fuentes)")
    regla_ficcion = ("(3) la historia es FICCIÓN: los personajes y sucesos propios se "
                     "inventan libremente pero respetando las ANCLAS listadas " if es_fic else "")

    # La metodología vive en factory/prompts/guion_master.prompt.md, no en este archivo: así
    # se corrige el motor narrativo (gancho, bucles, historia > lista) sin tocar Python.
    from factory import parametros
    lo_palabras, hi_palabras = parametros.palabras_objetivo()
    prompt = parametros.prompt_guion(
        CANAL=perfil["canal"], CATEGORIA=categoria or "general", NOMBRE_CATEGORIA=perfil["nombre"],
        PROMESA=perfil.get("promesa") or "curiosidades verificadas explicadas con claridad",
        MODO=modo, IDENTIDAD=perfil["identidad"], PUBLICO=perfil["público"],
        FORMATO=", ".join(perfil.get("formatos") or []) or "historia con protagonista",
        CLAIMS=claims, REGLA_FICCION=regla_ficcion, TITULO=titulo, ANGULO=angulo,
        PALABRAS_MIN=lo_palabras, PALABRAS_MAX=hi_palabras,
        PPS=f"{parametros.palabras_por_segundo():.2f}")
    # El cambio aprendido del episodio anterior (una sola variable por corrida): llega acá
    # porque state/aprendizaje.json lo escribió desde métricas reales de Zernio.
    directiva = parametros.directiva_aprendida()
    if directiva:
        prompt = (f"{prompt}\n\nITERACIÓN APRENDIDA DE LA MÉTRICA PROPIA (aplicala, es el único "
                  f"cambio de este episodio):\n{directiva}")
        print(f"  aprendizaje aplicado: {directiva[:90]}…")
    script = _guion_en_dos_pasos(prompt, ep, lo_palabras, hi_palabras)

    gates.gate_anti_duplicado(script, previos)  # GATE 4

    # GATE 1 sobre el texto: nada de testimonios ni escenas inventadas; reescribe solo.
    for intento in range(1, 5):
        faltantes = gates.gate_fidelidad(script, sources["claims"], episode=ep.slug)
        if not faltantes:
            print("  GATE FIDELIDAD: PASS (ningún enunciado sin respaldo)")
            break
        print(f"  fidelidad (intento {intento}): {len(faltantes)} enunciados sin respaldo, reescribiendo…")
        for q in faltantes[:6]:
            print(f"    - {q[:90]}")
        if intento == 4:
            raise SystemExit("El guion no pasó el auditor de fidelidad en 4 reescrituras; "
                             "no pasa a narración (regla 1: sólo hechos verificables).")
        script = llm.chat(
            [{"role": "system", "content": prompt},
             {"role": "assistant", "content": script},
             {"role": "user", "content":
              "El auditor rechazó estos enunciados no respaldados por las afirmaciones verificadas:\n"
              + "\n".join(f"- {q}" for q in faltantes)
              + "\nReescribí el guion completo quitando o reformulando sólo eso, sin perder el resto "
              f"y SIN acortar: el guion tiene que seguir en {lo_palabras}-{hi_palabras} palabras."}],
            temperature=0.5, max_tokens=2000, tag="guion-fix", episode=ep.slug).strip()
        gates.gate_anti_duplicado(script, previos)

    # GATE EXTENSIÓN + BUCLES: la fábrica entregaba episodios de ~320 palabras con promesa
    # de 10 minutos. O entra al rango del template con bucles verificables, o no se anima.
    _min_bucles, _max_bucles = parametros.bucles_config()[1]
    for intento_ext in range(1, 6):
        motivos = (gates.gate_extension(script, lo_palabras, hi_palabras)
                   + gates.gate_bucles(script, (_min_bucles, _max_bucles)))
        if not motivos:
            print(f"  GATE EXTENSIÓN/BUCLES: PASS ({len(script.split())} palabras, "
                  f"{gates.contar_bucles(script)} aperturas de bucle)")
            break
        print(f"  extensión/bucles (intento {intento_ext}/5): {motivos[0][:120]}")
        if intento_ext == 5:
            raise SystemExit(f"El guion no llegó a {lo_palabras}-{hi_palabras} palabras con bucles "
                             "verificables en 5 "
                             "reescrituras: no pasa a narración. Un corto de 2 minutos no cumple "
                             "la promesa del capítulo.")
        script = llm.chat(
            [{"role": "system", "content": prompt},
             {"role": "assistant", "content": script},
             {"role": "user", "content":
              "Diagnóstico del guion: " + motivos[0] + ". Reescribilo COMPLETO corrigiendo sólo eso. "
              "Si falta extensión, expandí el bloque más flaco con hechos que ya estén en las fuentes; "
              "sumá por lo menos 120 palabras para no quedar debajo del mínimo. Si sobra extensión, "
              "recortá lo repetido sin borrar la revelación. "
              "Los bucles que faltan van en la exploración: uno cada 45-90 segundos, que abre una "
              "pregunta, retrasa la recompensa, la cierra y encadena la siguiente. Nada de rellenar "
              "repitiendo lo ya dicho: cada bucle trae un dato nuevo de las afirmaciones verificadas."}],
            temperature=0.6, max_tokens=1800, tag="guion-ext", episode=ep.slug).strip()
        gates.gate_anti_duplicado(script, previos)

    # Crecer no puede inventar hechos: el texto expandido vuelve a pasar por el auditor.
    sobrantes = gates.gate_fidelidad(script, sources["claims"], episode=ep.slug)
    if sobrantes:
        raise SystemExit(f"La expansión introdujo enunciados sin respaldo ({sobrantes[0][:80]}); "
                         "recorré la etapa guion con las fuentes bajo control.")

    # --- GANCHO DORADO (0-3 s): anti-patrón + pregunta que retiene, con 2 intentos de
    # reparación (si el LLM está vivo). Sin pregunta, no hay episodio: todo el resto del
    # guion es invisible si el espectador scrollea en el segundo 2.
    for intento_hook in range(2):
        razon = hook_violado(script) or hook_pregunta(script)
        if not razon:
            print("  GATE GANCHO DORADO: PASS (primera oración = pregunta de retención)")
            break
        print(f"  GATE GANCHO DORADO: violado ({razon[:90]}) — reparando la primera oración…")
        try:
            script = reparar_hook(script, titulo, angulo)
        except Exception as llm_exc:  # noqa: BLE001 — el LLM puede estar sin cuota
            print(f"  hook: no se pudo reparar con LLM ({str(llm_exc)[:90]})")
    else:
        razon_final = hook_violado(script) or hook_pregunta(script) or "razón desconocida"
        raise SystemExit(f"GATE GANCHO DORADO BLOQUEA EL EPISODIO: {razon_final}\n"
                         "La retención empieza en el segundo 0: re-corré la etapa guion "
                         "con el LLM disponible (motor de 5 latidos, LATIDO 1).")
    ep.write_text("script.txt", f"# {titulo}\n\n{script}\n")
    meta = ep.metadata()
    meta["angle"] = angulo
    meta["word_count"] = len(script.split())
    ep.save_metadata(meta)
    ep.set_stage("guion", "gate_pass")
    print(f"  GATE ANTI-DUPLICADO: PASS (comparado contra {len(previos)} episodios publicados)")
    print(f"  guion -> artifacts/script.txt ({meta['word_count']} palabras, ángulo: {angulo[:60]}...)")
