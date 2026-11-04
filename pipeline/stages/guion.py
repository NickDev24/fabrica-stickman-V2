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


def reparar_hook(script: str, titulo: str, angulo: str) -> str:
    """Reescribe la PRIMERA oración con el LLM, manteniendo el resto del guion intacto."""
    prosa = "\n".join(l for l in script.splitlines() if not l.lstrip().startswith("#"))
    prosa = re.sub(r"\s+", " ", prosa).strip()
    primera, resto = re.split(r"(?<=[.!?])\s+", prosa, maxsplit=1) or (prosa, "")
    prompt = (
        f"Canal de documentales animados. Título: {titulo}. Ángulo: {angulo}.\n"
        "La PRIMERA oración del guion arranca con fecha/contexto (anti-patrón: no frena el "
        "scroll). Reescribí SOLO esa oración para que abra con el conflicto o el dato más "
        "fuerte (sujeto + hecho + consecuencia), sin fecha al inicio, máximo 18 palabras, "
        "español rioplatense. La fecha-contexto puede aparecer recién en la segunda oración.\n\n"
        f"ORACIÓN ACTUAL: {primera}\n"
        f"CONTEXTOS DEL GUION (para no inventar hechos): {resto[:600]}\n\n"
        "Devolvé SOLO la nueva oración, sin comillas ni preámbulos."
    )
    nueva = ""
    try:
        nueva = llm.chat([{"role": "user", "content": prompt}], max_tokens=90,
                         temperature=0.6, tag="hook-fix", episode="")[:400].strip()
    except Exception:  # noqa: BLE001 — sin LLM no se repara; que decida el gate
        return script
    nueva = re.split(r"(?<=[.!?])\s+", nueva)[0].strip()
    if not nueva or hook_violado(nueva + " " + resto):
        return script  # no se pisa el guion con algo peor; el gate decide el destino
    return script.replace(primera, nueva, 1)


def guion(ep: Episode, angulo: str | None = None) -> None:
    previos = gates.load_publicados(exclude_slug=ep.slug)
    if not angulo:
        angulo = elegir_angulo(ep, previos)
    if len(angulo.strip()) < 15:
        raise SystemExit("ángulo demasiado débil para cumplir el gate 4; reintentando la próxima corrida.")

    sources = ep.read_json("sources.json")
    claims = "\n".join(f"- {c['claim']} (veredicto: {c['verdict']})" for c in sources["claims"])
    estado = ep.read_state()
    titulo = estado["title"]
    categoria = estado.get("categoria", "")
    perfil = nichos.canal_de(categoria)
    es_fic = bool(perfil["ficción"])
    modo = ("FICCIÓN ORIGINAL (propiedad intelectual propia; prohibido copiar canales, "
            "guiones ni personajes existentes; referencias externas solo como inspiración "
            "de formato)" if es_fic
            else "documental verificable (cada hecho sale de las fuentes)")
    regla_ficcion = ("(3) la historia es FICCIÓN: los personajes y sucesos propios se "
                     "inventan libremente pero respetando las ANCLAS listadas " if es_fic else "")

    prompt = (
        f"Guionista PROPIETARIO del canal paraguas '{perfil['canal']}' — categoría: {perfil['nombre']}.\n"
        f"Promesa editorial: {perfil.get('promesa', 'curiosidades sorprendentes verificadas y explicadas con claridad')}.\n"
        f"Modo: {modo}\n"
        f"Identidad narrativa del canal: {perfil['identidad']}. Audiencia: {perfil['público']}.\n"
        "Español rioplatense. El gancho promete una respuesta concreta, nunca oculta un dato esencial "
        "ni inventa una escena. Evitá llamadas a suscribirse en todos los videos: CTA breve y pertinente.\n"
        f"Título: {titulo}\n"
        f"ÁNGULO NARRATIVO (lente de enfoque, NO licencia para inventar): {angulo}\n"
        f"Afirmaciones verificadas — ÚNICO material de hecho permitido:\n{claims}\n\n"
        "Reglas estrictas: (1) todo enunciado fáctico debe derivar de las afirmaciones listadas; "
        "prohibido inventar testimonios, personajes, escenas privadas, cifras o fechas que no estén "
        "en ellas — si el ángulo sugiere algo que los datos no cubren, reformulá el ángulo hacia lo "
        "que sí sostienen. (2) si usás una imagen o reconstrucción didáctica, marcala como tal "
        "('la imaginación reconstruye...', 'los testigos de la época describían...' sólo si una "
        "afirmación lo respalda) " + regla_ficcion + " (4) formato de retención: 500-700 palabras en 3 actos — "
        "ACTO 1 gancho: la PRIMERA FRASE es el conflicto o el resultado más fuerte (ej.: 'la SEC "
        "tuvo las pruebas y las ignoró durante años'), NUNCA una fecha ni contexto ('En 2005...'). "
        "Nombrá al sujeto y el hecho en esa frase; recién después ordená cronológicamente. "
        "Máximo 4 frases para plantar el misterio; ACTO 2 desarrollo: cada bloque suma UN dato nuevo y termina con un micro-cliffhanger "
        "que tire al siguiente; ACTO 3 giro/cierre: qué significa hoy + una pregunta abierta final. "
        "Frases cortas, ritmo oral, segunda persona cuando aporte ('mirá el mapa', 'pensá esto'). "
        "Bloques de 1-3 frases separados por línea en blanco. "
        "NUNCA uses listas, títulos de sección ni markdown: prosa narrada, lista para texto-a-voz."
    )
    script = llm.chat(
        [{"role": "system", "content": prompt},
         {"role": "user", "content": "Escribí el guion ahora, sin preámbulos."}],
        temperature=0.8, tag="guion", episode=ep.slug).strip()

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
              + "\nReescribí el guion completo quitando o reformulando sólo eso, sin perder el resto."}],
            temperature=0.5, tag="guion-fix", episode=ep.slug).strip()
        gates.gate_anti_duplicado(script, previos)

    razon = hook_violado(script)
    if razon:
        print(f"  GATE HOOK: violado ({razon[:90]}) — reescribiendo la primera oración…")
        try:
            script = reparar_hook(script, titulo, angulo)
        except Exception as llm_exc:  # noqa: BLE001 — el LLM puede estar sin cuota
            print(f"  hook: no se pudo reparar con LLM ({str(llm_exc)[:90]})")
        razon2 = hook_violado(script)
        if razon2:
            raise SystemExit(f"GATE HOOK BLOQUEA EL EPISODIO: {razon2}\n"
                             "El reto de retención empieza en el segundo 0: se re-corre "
                             "la etapa guion con el LLM disponible (regla ACTO 1).")
        print(f"  GATE HOOK: PASS (primera oración reescrita)")
    ep.write_text("script.txt", f"# {titulo}\n\n{script}\n")
    meta = ep.metadata()
    meta["angle"] = angulo
    meta["word_count"] = len(script.split())
    ep.save_metadata(meta)
    ep.set_stage("guion", "gate_pass")
    print(f"  GATE ANTI-DUPLICADO: PASS (comparado contra {len(previos)} episodios publicados)")
    print(f"  guion -> artifacts/script.txt ({meta['word_count']} palabras, ángulo: {angulo[:60]}...)")
