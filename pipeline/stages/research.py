"""Etapa 1: research + fact-check multi-proveedor, con gate de fuentes (gate 1)."""
from __future__ import annotations

import json
import re
import unicodedata
from urllib.parse import urlparse

import requests

from .. import config, gates, llm, nichos, web
from ..episode import Episode


def _fetch(url: str) -> str:
    """Extracto legible de una fuente. Ver pipeline.web para el porqué de scrapling/curl_cffi."""
    r = web.obtener(url, timeout=30)
    ctype = r.headers.get("content-type", "")
    if ctype and "html" not in ctype and "text" not in ctype:
        raise ValueError(f"no es HTML ({ctype})")
    return web.texto(r.text)


def _parse_json(text: str):
    m = re.search(r"\{.*\}|\[.*\]", text, re.S)
    if not m:
        raise ValueError(f"respuesta sin JSON: {text[:200]}")
    return json.loads(m.group(0))


def _llm_json(messages, **kw):
    """El gate de fuentes no puede depender de un JSON bien formado de un solo intento."""
    last = None
    for _ in range(3):
        answer = llm.chat(messages, **kw)
        try:
            return _parse_json(answer)
        except (ValueError, json.JSONDecodeError) as exc:
            last = exc
            kw["temperature"] = min(1.0, kw.get("temperature", 0.4) + 0.2)
    raise SystemExit(f"el LLM no devolvió JSON parseable en 3 intentos: {last}")


# El modelo local tiene 4096 de contexto ÚTIL (medido 2026-11-05: un pedido de 5.730
# tokens fue rechazado con exceed_context_size_error y cortó la corrida entera en
# factcheck). 6.000 caracteres ≈ 2.000 tokens de entrada, deja margen para el system
# prompt y para la respuesta. En vez de un megaprompt, se manda en lotes.
MAX_CHARS_BODY = 6000
MAX_CHARS_EXCERPT = 1400
# Piso del guion: con menos anclas verificadas no hay capítulo (era un 4 suelto en dos lados).
MIN_AFIRMACIONES = 4


def _raices_de(texto: str) -> set[str]:
    """Raíces de 6 caracteres, sin acentos ni símbolos: 'elecciones' ≈ 'eleccion'."""
    sin_acentos = "".join(c for c in unicodedata.normalize("NFKD", (texto or "").casefold())
                          if not unicodedata.combining(c))
    limpio = re.sub(r"[^a-z0-9 ]+", " ", sin_acentos)
    return {w[:6] for w in limpio.split() if len(w) >= 5}


def _numeros_de(texto: str) -> set[str]:
    """Los números crudos de un texto (sin puntos ni comas): 50.000 y 50000 son el mismo dato."""
    return {n for n in re.findall(r"\d+", texto or "") if len(n) >= 2}


def _corroboran(candidato: dict, fetched: dict[int, dict]) -> list[int]:
    """Índices de fuentes NO citadas que contienen el mismo dato, comparando texto, no opinión.

    Criterio: todos los números de la afirmación tienen que aparecer en el otro extracto
    (un "222 escaños" sin el 222 adentro no es el mismo hecho) y al menos 4 raíces
    distintivas compartidas. Es conservador: prefiere descartar una afirmación antes que
    atribuirla a una fuente que no la dice.
    """
    base = f"{candidato.get('claim', '')} {candidato.get('quote', '')}"
    raices = _raices_de(base)
    numeros = _numeros_de(base)
    citados = set(candidato.get("source_indices") or [])
    if not raices:
        return []
    extra = []
    for i, fuente in fetched.items():
        if i in citados:
            continue
        texto = fuente.get("excerpt") or ""
        if numeros and not numeros <= _numeros_de(texto):
            continue    # el dato numérico tiene que estar dicho, no sólo la temática
        if len(raices & _raices_de(texto)) < 4:
            continue
        extra.append(i)
    return sorted(extra)


def _lotes(bloques: list[str], max_chars: int = MAX_CHARS_BODY) -> list[list[str]]:
    """Agrupa bloques sin pasar el techo; un bloque individual más grande se recorta."""
    lotes: list[list[str]] = []
    actual: list[str] = []
    largo = 0
    for b in bloques:
        b = b[:max_chars]
        if actual and largo + len(b) > max_chars:
            lotes.append(actual)
            actual, largo = [], 0
        actual.append(b)
        largo += len(b) + 2
    if actual:
        lotes.append(actual)
    return lotes


def research(ep: Episode) -> None:
    urls = [l.strip() for l in (ep.dir / "research" / "urls.txt").read_text(encoding="utf-8").splitlines()
            if l.strip() and not l.strip().startswith("#")]
    if len(urls) < 2:
        raise SystemExit("research/urls.txt necesita al menos 2 URLs de fuentes independientes.")
    fetched = {}
    for i, url in enumerate(urls):
        try:
            fetched[i] = {"url": url, "excerpt": _fetch(url)}
            print(f"  fetch OK [{i}] {url}")
        except (requests.RequestException, ValueError) as exc:
            print(f"  fetch descartado [{i}] {url}: {exc}")
    if len(fetched) < 2:
        raise SystemExit("menos de 2 fuentes legibles: el gate 1 no se puede cumplir con este material.")

    estado = ep.read_state()
    ficcion = bool(estado.get("categoria")) and nichos.es_ficcion(estado["categoria"])
    if ficcion:
        prompt = (
            "Sos el investigador de una historia DE FICCIÓN original (el guion será inventado, "
            "pero verosímil). De estas fuentes extractá hasta 3 ANCLAS DE VEROSIMILITUD por fuente: "
            "dados reales (física, geografía, fisiología, tecnología, contexto social) que la "
            "historia ficticia debe respetar para sonar creíble. Ejemplo: cuánto sobrevive una "
            "persona sin agua, cuánto alarga una falla sísmica, cómo se comporta la gente en pánico. "
            "Cada ancla necesita al menos 1 fuente (por índice). "
            "Devolvé sólo JSON: {\"claims\":[{\"claim\":\"...\",\"source_indices\":[0],\"quote\":\"fragmento textual\"}]}"
        )
    else:
        prompt = (
            "Sos el investigador de un canal de documentales. De estas fuentes, extraé hasta "
            "3 AFIRMACIONES CENTRALES verificables que una historia real pueda apoyar. "
            "Cita SIEMPRE el índice [n] de la fuente de donde sale cada afirmación. "
            "Devolvé sólo JSON: {\"claims\":[{\"claim\":\"...\",\"source_indices\":[0,1],\"quote\":\"fragmento textual de una fuente\"}]}"
        )

    bloques = [f"[{i}] {f['url']}\n{f['excerpt'][:MAX_CHARS_EXCERPT]}" for i, f in fetched.items()]
    candidatos: list[dict] = []
    for lote in _lotes(bloques):
        data = _llm_json([{"role": "system", "content": prompt},
                          {"role": "user", "content": "\n\n".join(lote)}],
                         tag="research", episode=ep.slug)
        candidatos += [c for c in (data.get("claims") or []) if str(c.get("claim", "")).strip()]
    if not candidatos:
        raise SystemExit("research: el LLM no extrajo ninguna afirmación de las fuentes.")

    # Selección determinista: cuántas fuentes DISTINTAS (por dominio) respaldan cada
    # afirmación. Es el criterio del gate 1, así que aplica mejor acá que un reranking
    # del mismo modelo que las escribió.
    # Un modelo libre cita UNA fuente por dato; el gate 1 exige dos dominios. La
    # corrobora­ción no se le pide al LLM (inventory de texto, no de opinión): si otro
    # fetch tiene los mismos números y las mismas raíces, es soporte real y queda a la
    # vista en `sources`. Lo que no se corrobora se descarta, no se maquilla.
    def _dominios(c: dict) -> int:
        return len({urlparse(fetched[i]["url"]).netloc.removeprefix("www.")
                    for i in c.get("source_indices", []) if i in fetched})

    vistos: set[str] = set()
    unicas = []
    for c in candidatos:
        if not _dominios(c):
            continue  # sin índice citable no hay fuente que el gate pueda verificar
        c["source_indices"] = sorted(set(c.get("source_indices") or [])
                                     | set(_corroboran(c, fetched)))
        firma = re.sub(r"\W+", " ", str(c["claim"]).casefold()).strip()
        if firma in vistos:
            continue
        vistos.add(firma)
        unicas.append(c)
    unicas = [c for c in unicas if _dominios(c) >= 2]
    unicas.sort(key=lambda c: (-min(_dominios(c), 3), -len(str(c["claim"]))))
    seleccion = unicas[:8]
    if len(seleccion) < 4:
        raise SystemExit(f"research: sólo {len(seleccion)} afirmaciones con 2+ dominios que las "
                         "respalden (el guion necesita 4-8 anclas). Gate 1: no se publica con "
                         "investigación de una sola fuente.")

    sources = {"slug": ep.slug, "claims": [], "modo": "ficcion" if ficcion else "factico"}
    for c in seleccion:
        srcs = [{"url": fetched[i]["url"], "publisher": urlparse(fetched[i]["url"]).netloc.removeprefix("www.")}
                for i in c.get("source_indices", []) if i in fetched]
        sources["claims"].append({"claim": c["claim"], "quote": c.get("quote", ""),
                                  "sources": srcs, "verdict": "pendiente"})
    ep.write_json("sources.json", sources)
    ep.set_stage("research", "done")
    print(f"  {len(sources['claims'])} afirmaciones centrales "
          f"(de {len(candidatos)} candidatas) -> artifacts/sources.json")


def _lotes_de(ids: list[int], blocks: list[str],
              max_chars: int = MAX_CHARS_BODY) -> list[list[int]]:
    """Misma tanda de _lotes, pero devolviendo QUÉ afirmaciones hay en cada lote."""
    lotes: list[list[int]] = []
    actual: list[int] = []
    largo = 0
    for i in ids:
        tamaño = len(blocks[i][:max_chars])
        if actual and largo + tamaño > max_chars:
            lotes.append(actual)
            actual, largo = [], 0
        actual.append(i)
        largo += tamaño
    if actual:
        lotes.append(actual)
    return lotes


def _indice_de(veredicto: dict, lote: list[int]) -> int | None:
    """A qué afirmación del episodio responde este veredicto, aunque el modelo numere mal.

    Un índice fuera de rango se tiraba en silencio y la afirmación quedaba "pendiente",
    que es la forma más tonta de perder un episodio: el trabajo estaba hecho.
    """
    raw = veredicto.get("index", veredicto.get("id"))
    if isinstance(raw, str):
        raw = raw.strip().strip("[]#").split(".")[0]
        try:
            raw = int(raw)
        except ValueError:
            return None
    if not isinstance(raw, int) or isinstance(raw, bool):
        return None
    if raw in lote:                          # numeró con el AFIRMACIÓN n del texto
        return raw
    if 0 <= raw < len(lote):                 # numeró 0..k-1 dentro del lote
        return lote[raw]
    if 1 <= raw <= len(lote):                # numeró 1..k dentro del lote
        return lote[raw - 1]
    return None


def factcheck(ep: Episode) -> None:
    sources = ep.read_json("sources.json")
    excerpts = {}
    for claim in sources["claims"]:
        for s in claim["sources"]:
            if s["url"] not in excerpts:
                try:
                    excerpts[s["url"]] = _fetch(s["url"])
                except (requests.RequestException, ValueError) as exc:
                    print(f"  excerpt no disponible {s['url']}: {exc}")
                    excerpts[s["url"]] = ""
    blocks = []
    for i, c in enumerate(sources["claims"]):
        txt = "\n".join(f"FUENTE {s['url']}: {excerpts[s['url']][:MAX_CHARS_EXCERPT]}"
                        for s in c["sources"])
        blocks.append(f"AFIRMACIÓN {i}: {c['claim']}\n{txt}")
    modo_ficcion = sources.get("modo") == "ficcion"
    if modo_ficcion:
        prompt = (
            "Verificación de ANCLAS DE VEROSIMILITUD para una historia de ficción. Para cada "
            "ancla evaluá si la fuente provista la respalda como dato real del mundo. "
            "verdict: 'ancla' (la fuente la respalda) o 'refutada' (la contradice). "
            "Devolvé sólo JSON: {\"verdicts\":[{\"index\":0,\"verdict\":\"...\",\"motivo\":\"...\"}]}"
        )
    else:
        prompt = (
            "Fact-check estricto. Para cada afirmación, evaluá si las fuentes provistas la respaldan. "
            "verdict: 'respaldada' (2+ fuentes la apoyan directamente), 'parcial' (apoyo indirecto o "
            "con reconstrucción didáctica) o 'refutada' (las fuentes la contradicen o no la apoyan). "
            "Usá en 'index' el número que aparece en AFIRMACIÓN n, sin renumerar. "
            "Devolvé sólo JSON: {\"verdicts\":[{\"index\":0,\"verdict\":\"...\",\"motivo\":\"...\"}]}"
        )
    # Un lote por llamada: el cuerpo de 30.000 caracteres que se mandaba junto superaba
    # el contexto del modelo local y AllProvidersFailed cortaba la corrida.
    permitidos = {"ancla", "refutada"} if modo_ficcion else {"respaldada", "parcial", "refutada"}
    sin_veredicto = set(range(len(blocks)))
    for pasada in (1, 2):
        if not sin_veredicto:
            break
        if pasada == 2:
            print(f"  factcheck: {len(sin_veredicto)} afirmaciones sin veredicto, "
                  "se vuelven a preguntar una por una")
        lotes = (_lotes_de(sorted(sin_veredicto), blocks) if pasada == 1
                 else [[i] for i in sorted(sin_veredicto)])
        for lote in lotes:
            data = _llm_json(
                [{"role": "system", "content": prompt},
                 {"role": "user", "content": "\n\n".join(blocks[i][:MAX_CHARS_BODY] for i in lote)}],
                tag="factcheck", episode=ep.slug)
            for v in data.get("verdicts") or []:
                i = _indice_de(v, lote)
                veredicto = str(v.get("verdict") or "").strip().lower()
                if i is None or veredicto not in permitidos:
                    continue
                sources["claims"][i]["verdict"] = veredicto
                sources["claims"][i]["factcheck_motivo"] = str(v.get("motivo", ""))[:300]
                sin_veredicto.discard(i)
    if sin_veredicto:
        # Acá no se inventa un veredicto para pasar el gate: se marca y el gate frena el
        # episodio, que es exactamente lo que tiene que pasar con un hecho sin verificar.
        for i in sorted(sin_veredicto):
            sources["claims"][i]["factcheck_motivo"] = "el verificador no devolvió veredicto"
        print(f"  factcheck: {len(sin_veredicto)} afirmaciones siguen sin veredicto")
    # Una afirmación refutada o sin veredicto NO entra al guion: se saca del episodio y queda
    # auditada en claims_descartadas. Lo que no puede pasar es que UN veredicto ruidoso del
    # verificador gratuito tumbe la corrida entera: medido 2026-11-05, 5 afirmaciones bien
    # respaldadas y 1 marcada "refutada" que las fuentes sí apoyan = cero episodio del día.
    ok = {"ancla", "respaldada", "parcial"} if modo_ficcion else {"respaldada", "parcial"}
    aprobadas: list[dict] = []
    descartadas: list[dict] = []
    for c in sources["claims"]:
        (aprobadas if c.get("verdict") in ok else descartadas).append(c)
    if len(aprobadas) >= MIN_AFIRMACIONES:
        sources["claims"] = aprobadas
        sources["claims_descartadas"] = [
            {"claim": c["claim"], "verdict": c.get("verdict"),
             "motivo": c.get("factcheck_motivo", "")} for c in descartadas]
        print(f"  factcheck: {len(descartadas)} afirmaciones refutadas o sin veredicto quedan "
              f"fuera del guion; se escriben {len(aprobadas)} con respaldo")
    elif descartadas:
        print(f"  factcheck: sólo {len(aprobadas)} afirmaciones superan el veredicto y hacen "
              f"falta {MIN_AFIRMACIONES}: el material no da para un episodio")
    ep.write_json("sources.json", sources)

    gates.gate_fuentes(sources, ficcion=modo_ficcion)  # GATE 1 (modo ficción: anclas)
    ep.set_stage("factcheck", "gate_pass")
    print("  GATE FUENTES: PASS" + (" (modo ficción: anclas de verosimilitud)" if modo_ficcion else ""))
