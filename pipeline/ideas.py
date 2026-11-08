"""Motor editorial: convierte oportunidades medidas en propuestas de video original.

Dos fases, en este orden y no al revs:
  1) PROPONER  -> idea con titulo, gancho, estructura, giro, cierre, CTA y duracion estimada.
                  aun sin fuentes: es una hipotesis editorial, no un guion.
  2) VERIFICAR -> el tema pasa por discover/research/fact-check (gate 1). Si no hay >=2
                  fuentes por afirmacion, la idea se descarta, no se "ajusta".

El guion definitivo se escribe DESPUES de verificar (stages/guion.py), contra las afirmaciones
reales: asi el motor no puede inventar experimentos, estadisticas ni descubrimientos.
"""
from __future__ import annotations

import json
import re
from datetime import datetime

from . import config, formatos, llm, nichos, tendencias


def _canal(categoria: str) -> dict:
    return nichos.canal_de(categoria)
from .episode import Episode

STATE_IDEAS = config.STATE / "ideas.json"
REGISTRO = config.REGISTRY / "ideas.jsonl"

CAMPOS = ["titulo", "gancho", "desarrollo", "giro", "cierre", "cta", "duracion_s",
          "emocion", "miniatura"]


def _obligatorios(card: dict) -> list[str]:
    return [c for c in CAMPOS if not str(card.get(c, "")).strip()]


def proponer(tema: str, categoria: str, formato_clave: str, senal: dict | None = None,
             perfil_clave: str = "short_vertical",
             referencias_youtube: list[dict] | None = None) -> dict:
    """Una ficha editorial: la promesa, no el guion todavia."""
    perfil = formatos.perfil(perfil_clave)
    formato = nichos.FORMATOS[formato_clave]
    canal = _canal(categoria)
    palabras = perfil.palabras_objetivo()
    referencias_youtube = referencias_youtube or []
    titulos_referencia = []
    for video in referencias_youtube:
        titulo = str(video.get("title") or video.get("name") or "")[:160]
        if not titulo:
            continue
        vistas = str(video.get("views") or "vistas no informadas")
        fecha = str(video.get("published") or "fecha no informada")
        titulos_referencia.append(f"{titulo} ({vistas}; {fecha})")
    contexto_youtube = ("\nMUESTRA COMPETITIVA (títulos de YouTube, no son fuentes factuales):\n- "
                        + "\n- ".join(titulos_referencia)
                        + "\nUsalos sólo para detectar enfoques saturados y diferenciar el ángulo. "
                          "Las vistas no están normalizadas por antigüedad ni suscriptores. "
                          "No imites títulos ni afirmes datos que no estén verificados.\n"
                        if titulos_referencia else "")
    prompt = (
        f"Sos el editor de '{canal['canal']}' — nicho: {canal['nombre']} "
        f"(espanol rioplatense; identidad: {canal['identidad']}).\n"
        f"TEMA medido (demanda real observada): {tema}\n"
        f"CATEGORIA: {categoria}\n"
        f"FORMATO SERIE: {formato['nombre']} -- {formato['nota']}\n"
        f"PREGUNTA SEMILLA: {formato['pregunta'].format(tema=tema)}\n"
        f"{contexto_youtube}"
        f"Estructura esperada: {formato['estructura']}\n"
        f"DURACION OBJETIVO: {perfil.segundos_min}-{perfil.segundos_max} s vertical 9:16, "
        f"~{palabras} palabras de narracion (2,78 palabras/segundo medidos con la voz del canal).\n\n"
        "Devolve SOLO JSON con estas claves:\n"
        '{"titulo": "maximo 70 caracteres, sin prometer lo que el video no muestra",\n'
        ' "gancho": "lo que se dice en los primeros 3 segundos, una frase, sin saludar",\n'
        ' "gancho_alternativo": "segunda version del gancho para probar A/B",\n'
        ' "desarrollo": "que bloques de informacion van, en orden, y que dato sostiene cada uno",\n'
        ' "giro": "la revelacion que reordena todo lo anterior",\n'
        ' "cierre": "frase final memorable",\n'
        ' "cta": "invitation natural, nunca suscribite ya",\n'
        ' "emocion": "emocion universal dominante (venganza, miedo, amor, traicion, injusticia, ambicion, supervivencia, humor o curiosidad) — una sola",\n'
        ' "miniatura": "concepto de portada en una frase: que pregunta o conflicto vende (no describir la animacion)",\n'
        ' "preguntas_abiertas": "que hay que verificar si es cierto o no (lista de 3 a 6 preguntas concretas)"}\n\n'
        "PROHIBIDO: inventar investigaciones, cifras, experimentos o descubrimientos; imitar "
        "titulos de otros canales; afirmar algo que no se pueda verificar. Las preguntas_abiertas "
        "son el pedido de verificacion: lo que no se verifique no entra al guion."
    )
    card = llm.chat_json([{"role": "user", "content": prompt}], max_tokens=2048,
                         tag="idea", temperature=0.85)
    card.update({
        "tema": tema, "categoria": categoria, "formato": formato_clave,
        "perfil": perfil_clave, "duracion_s": perfil.segundos_estimados(palabras),
        "palabras_objetivo": palabras,
        "senal_demanda": (senal or {}).get("score"),
        "sostenibilidad": (senal or {}).get("sostenibilidad"),
        "procedencia": (senal or {}).get("procedencia"),
        "referencias_youtube": referencias_youtube,
        "estado": "propuesta", "creada_el": datetime.utcnow().isoformat() + "Z",
    })
    faltan = _obligatorios(card)
    if faltan:
        raise ValueError(f"la idea de {tema!r} vino sin campos obligatorios: {faltan}")
    return card


def verificar(card: dict) -> dict:
    """Gate 1 sobre la hipotesis: fuentes independientes + afirmaciones respaldadas."""
    from .stages import research
    slug = re.sub(r"[^a-z0-9-]+", "-", card["tema"].lower())[:44].strip("-")
    ep = Episode.create(f"idea-{slug}", card["titulo"][:80])
    # Esta carpeta es una SONDA de verificación, no un episodio producido. Se marca para
    # que el anti-repetición (huellas.intentadas) no la cuente: su título es el de la idea
    # y la descartaba a sí misma con similitud 1.0 (fábrica seca sin producir nada).
    sonda = ep.read_state()
    sonda["verificacion_probe"] = True
    ep.write_state(sonda)
    from .stages import descubrir
    try:
        urls = descubrir.descubrir(ep, card["tema"])
        research.research(ep)
        research.factcheck(ep)
    except SystemExit as exc:
        card.update({"estado": "descartada_sin_fuentes", "motivo": str(exc)[:200]})
        return card
    fuentes = ep.read_json("sources.json")
    afirmaciones = [c["claim"] for c in fuentes["claims"] if c.get("verdict") != "refutada"]
    respaldadas = [c for c in fuentes["claims"] if len(c.get("sources", [])) >= 2]
    card.update({
        "estado": "verificada" if len(respaldadas) >= 2 else "verificacion_insuficiente",
        "slug": ep.slug, "fuentes": len({s["url"] for c in fuentes["claims"] for s in c["sources"]}),
        "urls": urls, "afirmaciones": afirmaciones,
        "verificadas": [c["claim"] for c in respaldadas],
    })
    # El veredicto queda en la sonda: las fallidas siguen bloqueando el tema (no se
    # reincide en una historia sin fuentes), las verificadas dejan de bloquear.
    sonda = ep.read_state()
    sonda["verificacion_estado"] = card["estado"]
    ep.write_state(sonda)
    return card


def rankear(cards: list[dict]) -> list[dict]:
    """Orden por potencial editorial (nunca por vistas prometidas: no las sabemos)."""
    for c in cards:
        score, why = nichos.potencial(
            {"categoria": c.get("categoria"), "formato": c.get("formato"),
             "giro": c.get("giro"), "gancho": c.get("gancho"),
             "fuentes": c.get("fuentes", 0)},
            [{"score": c.get("senal_demanda") or 0}])
        c["potencial"], c["potencial_por_que"] = score, why
    return sorted(cards, key=lambda x: -x["potencial"])


def generar(cantidad: int = 6, perfil_clave: str = "short_vertical",
            verificar_las: bool = True) -> list[dict]:
    """Pasada completa: tendencias -> fichas -> verificacion -> ranking."""
    tablero = tendencias.detectar()
    oportunidades = tablero["oportunidades"][:max(cantidad * 3, 12)]
    from . import youtube_mcp
    referencias = youtube_mcp.buscar_varios(
        [o["tema"] for o in oportunidades[:max(cantidad, 1)]], max_consultas=max(cantidad, 1)
    )
    rng_formato = list(nichos.FORMATOS)
    cards: list[dict] = []
    usadas: set[str] = set()
    for i, o in enumerate(oportunidades):
        if len(cards) >= cantidad:
            break
        if o["tema"] in usadas:
            continue
        usadas.add(o["tema"])
        formato = rng_formato[i % len(rng_formato)]
        try:
            card = proponer(o["tema"], o["categoria"], formato, senal=o,
                            perfil_clave=perfil_clave,
                            referencias_youtube=referencias.get(o["tema"], []))
        except (ValueError, llm.AllProvidersFailed) as exc:
            print(f"  idea {o['tema'][:32]} descartada: {exc}")
            continue
        if verificar_las:
            card = verificar(card)
        cards.append(card)
    cards = rankear(cards)
    config.STATE.mkdir(parents=True, exist_ok=True)
    STATE_IDEAS.write_text(json.dumps(
        {"actualizado": datetime.utcnow().isoformat() + "Z", "ideas": cards},
        indent=2, ensure_ascii=False), encoding="utf-8")
    REGISTRO.parent.mkdir(parents=True, exist_ok=True)
    with REGISTRO.open("a", encoding="utf-8") as fh:
        for c in cards:
            fh.write(json.dumps({k: c.get(k) for k in
                                 ("tema", "titulo", "categoria", "formato", "estado",
                                  "potencial", "fuentes", "slug")}, ensure_ascii=False) + "\n")
    ok = sum(1 for c in cards if c["estado"] == "verificada")
    print(f"  ideas: {len(cards)} fichas ({ok} verificadas con >=2 fuentes) -> state/ideas.json")
    return cards
