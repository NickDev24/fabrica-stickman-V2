"""Etapa 1: research + fact-check multi-proveedor, con gate de fuentes (gate 1)."""
from __future__ import annotations

import json
import re
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

    listing = "\n".join(f"[{i}] {f['url']}\n{f['excerpt'][:2500]}" for i, f in fetched.items())
    estado = ep.read_state()
    ficcion = bool(estado.get("categoria")) and nichos.es_ficcion(estado["categoria"])
    if ficcion:
        prompt = (
            "Sos el investigador de una historia DE FICCIÓN original (el guion será inventado, "
            "pero verosímil). De estas fuentes extractá entre 4 y 8 ANCLAS DE VEROSIMILITUD: "
            "dados reales (física, geografía, fisiología, tecnología, contexto social) que la "
            "historia ficticia debe respetar para sonar creíble. Ejemplo: cuánto sobrevive una "
            "persona sin agua, cuánto alarga una falla sísmica, cómo se comporta la gente en pánico. "
            "Cada ancla necesita al menos 1 fuente (por índice). "
            "Devolvé sólo JSON: {\"claims\":[{\"claim\":\"...\",\"source_indices\":[0],\"quote\":\"fragmento textual\"}]}"
        )
    else:
        prompt = (
            "Sos el investigador de un canal de documentales. De estas fuentes, extraé "
            "entre 4 y 8 AFIRMACIONES CENTRALES verificables que una historia real pueda apoyar. "
            "Cada afirmación DEBE tener al menos 2 fuentes distintas (por índice). "
            "Devolvé sólo JSON: {\"claims\":[{\"claim\":\"...\",\"source_indices\":[0,1],\"quote\":\"fragmento textual de una fuente\"}]}"
        )
    data = _llm_json(
        [{"role": "system", "content": prompt},
         {"role": "user", "content": listing[:30000]}],
        tag="research", episode=ep.slug)

    sources = {"slug": ep.slug, "claims": [], "modo": "ficcion" if ficcion else "factico"}
    for c in data.get("claims", []):
        srcs = [{"url": fetched[i]["url"], "publisher": urlparse(fetched[i]["url"]).netloc.removeprefix("www.")}
                for i in c["source_indices"] if i in fetched]
        sources["claims"].append({"claim": c["claim"], "quote": c.get("quote", ""),
                                  "sources": srcs, "verdict": "pendiente"})
    ep.write_json("sources.json", sources)
    ep.set_stage("research", "done")
    print(f"  {len(sources['claims'])} afirmaciones centrales -> artifacts/sources.json")


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
        txt = "\n".join(f"FUENTE {s['url']}: {excerpts[s['url']][:2000]}" for s in c["sources"])
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
            "Devolvé sólo JSON: {\"verdicts\":[{\"index\":0,\"verdict\":\"...\",\"motivo\":\"...\"}]}"
        )
    data = _llm_json(
        [{"role": "system", "content": prompt},
         {"role": "user", "content": "\n\n".join(blocks)[:30000]}],
        tag="factcheck", episode=ep.slug)
    for v in data["verdicts"]:
        idx = v["index"]
        if 0 <= idx < len(sources["claims"]):
            sources["claims"][idx]["verdict"] = v["verdict"]
            sources["claims"][idx]["factcheck_motivo"] = v.get("motivo", "")
    ep.write_json("sources.json", sources)

    gates.gate_fuentes(sources, ficcion=modo_ficcion)  # GATE 1 (modo ficción: anclas)
    ep.set_stage("factcheck", "gate_pass")
    print("  GATE FUENTES: PASS" + (" (modo ficción: anclas de verosimilitud)" if modo_ficcion else ""))
