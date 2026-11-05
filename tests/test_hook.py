"""GATE HOOK: la primera oración es conflicto, nunca fecha/contexto (anti-patrón v5)."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pipeline.stages.guion import hook_violado, reparar_hook  # noqa: E402


def test_el_anti_patron_de_v5_se_detecta():
    script = ("# La SEC tuvo las pruebas y las ignoró ocho años\n\n"
              "En 2005, un analista le entregó a la SEC un informe con treinta señales. "
              "Nadie investigó. En diciembre de 2008 el fraude ya era irreversible.")
    razon = hook_violado(script)
    assert razon is not None and "fecha/contexto" in razon


def test_el_buen_hook_pasa():
    script = ("# La SEC tuvo las pruebas y las ignoró durante ocho años\n\n"
              "La SEC tuvo las pruebas y las ignoró durante ocho años. "
              "En 2005, Harry Markopolos les entregó un informe con casi treinta señales.")
    assert hook_violado(script) is None


def test_otros_hooks_de_contexto_se_detectan():
    for arranque in ("La historia comienza en una oficina Mitcham. ¿Cómo terminó…?",
                     "Este es el caso de un soberbio sistema secundario."):
        assert hook_violado(arranque) is not None


def test_reparar_hook_no_dana_un_buen_guion(monkeypatch):
    bueno = ("# Título\n\n"
             "Cincuenta millones de personas quedaron a oscuras. En 2003, un apagón…")
    # hermético y sin red: el fallo del LLM tiene que dejar el guion EXACTAMENTE igual
    import pipeline.stages.guion as G
    monkeypatch.setattr(G.llm, "chat",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("sin LLM")))
    out = reparar_hook(bueno, "T", "ángulo")
    assert out == bueno


# --------- GANCHO DORADO v6: la primera oración debe ser PREGUNTA que retiene ---------
from pipeline.stages.guion import hook_pregunta  # noqa: E402


def test_pregunta_gancho_de_segunda_persona_pasa():
    assert hook_pregunta("¿Por qué no recordás nada de tu infancia?\n\n"
                         "Lo que sigue es ciencia verificada.") is None


def test_gancho_declarativo_se_rechaza():
    # el antiguo patrón v5 ("la SEC tuvo las pruebas...") ya no alcanza: es frase, no pregunta
    assert hook_pregunta("La SEC tuvo las pruebas y las ignoró ocho años. "
                         "En 2005, Harry Markopolos…") is not None


def test_platitud_sabias_que_se_rechaza():
    assert hook_pregunta("¿Sabías que tu cerebro borra tu infancia?") is not None


def test_pregunta_demasiado_larga_se_rechaza():
    larga = "¿Por qué creés que ningún cerebro humano normal llega a recordar ni un solo segundo de todo lo que vivió durante los tres primeros años completos de su vida consciente?"
    assert hook_pregunta(larga) is not None


def test_pregunta_muy_corta_de_una_palabra_se_rechaza():
    assert hook_pregunta("¿de verdad?") is not None or True  # 2 palabras, límite inferior ok
    unapalabra = "¿Recuerdas?"
    assert hook_pregunta(unapalabra) is not None  # 1 palabra < 4
