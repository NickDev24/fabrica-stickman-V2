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
