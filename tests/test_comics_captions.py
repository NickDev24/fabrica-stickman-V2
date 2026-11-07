"""Pulido LLM de captions: guard de paridad factual y fallback determinista."""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from pipeline.comics import captions as C
from pipeline.comics.adaptar_guion import (
    _asignar_ritmo, _determinista, _oraciones, adaptar,
)
from pipeline.comics.qc import ejecutar as qc_ejecutar

GUION = """# El robo del museo

El 18 de marzo de 1990 dos hombres llegaron al museo en Boston.
Dijeron que respondían a un disturbio grave en otra ala del edificio.
El personal del museo los dejó entrar sin verificar nada.
Una vez adentro subieron directo a la galería de pintura europea.
Se llevaron trece obras de arte en poco más de una hora.
Entre ellas había trabajos de Degas, Manet y Rembrandt.
También desapareció una pintura de Vermeer muy valiosa.
La pérdida se estima en más de quinientos millones de dólares.
El caso nunca fue resuelto por la policía ni por el FBI.
Los autores del golpe nunca fueron identificados públicamente.
El museo ofrece desde hace años una recompensa millonaria.
En el museo todavía pueden verse los marcos vacíos colgados.
Esa ausencia se convirtió en parte visible del caso Gardnér.
"""

CLAIMS = [
    {"afirmacion": "El 18 de marzo de 1990 dos hombres entraron disfrazados de policías",
     "fuentes": ["https://www.fbi.gov/caso"], "verdict": "verificada"},
    {"afirmacion": "Se llevaron trece obras incluida una pintura de Vermeer",
     "fuentes": ["https://www.museo.org/theft"], "verdict": "verificada"},
    {"afirmacion": "La pérdida superó quinientos millones de dólares según el FBI",
     "fuentes": ["https://www.fbi.gov/caso"], "verdict": "verificada"},
    {"afirmacion": "El caso sigue sin resolverse más de tres décadas después",
     "fuentes": ["https://www.museo.org/theft"], "verdict": "verificada"},
]


def _datos() -> dict:
    d = _determinista(_oraciones(GUION)[:13], CLAIMS, "El robo del museo")
    _asignar_ritmo(d["paneles"], d["grillas"])
    d["schema"] = "comics.v2"
    return d


def _panel(ancla: str, narracion: str, i: int = 1) -> dict:
    return {"i": i, "rol_ritmico": "contexto", "accion": "explica",
            "ancla_guion": ancla, "narracion": narracion,
            "caption_via": "determinista"}


def _fake_llm(monkeypatch, propuesta, veredicto=None):
    llamadas = []

    def fake(messages, **kw):
        tag = kw.get("tag")
        llamadas.append(tag)
        if tag == "comics-caption":
            return {"captions": propuesta()}
        if tag == "comics-paridad":
            if veredicto is None:
                raise AssertionError("no debía llamar al verificador")
            return {"pares": veredicto()}
        raise AssertionError(f"tag inesperado: {tag}")

    monkeypatch.setattr(C.llm, "chat_json", fake)
    return llamadas


def test_habilitado_lee_la_bandera(monkeypatch):
    monkeypatch.setattr(C.config, "load_env", lambda: None)
    monkeypatch.setenv("COMICS_CAPTIONS_LLM", "1")
    assert C.habilitado() is True
    monkeypatch.setenv("COMICS_CAPTIONS_LLM", "0")
    assert C.habilitado() is False


def test_guard_normaliza_cifras_escritas(monkeypatch):
    """'trece' y '13' son la misma cifra: no es un cambio factual."""
    assert C.revisar_paridad("Se llevaron trece obras de arte.",
                             "Se llevaron 13 obras de arte.") == []


def test_guard_rechaza_cifra_cambiada(monkeypatch):
    monkeypatch.setattr(C, "habilitado", lambda: True)
    panel = _panel("Se llevaron trece obras de arte.", "Se llevaron trece obras de arte.")
    llamadas = _fake_llm(monkeypatch, lambda: [
        {"i": 1, "texto": "Se llevaron doce obras de arte."}])
    res = C.pulir([panel], titulo="El robo", slug="test")
    assert res["aceptadas"] == 0
    assert panel["narracion"] == "Se llevaron trece obras de arte."
    assert any("cifras" in m for m in res["motivos"])
    assert llamadas == ["comics-caption"]


def test_guard_rechaza_negacion_invertida(monkeypatch):
    monkeypatch.setattr(C, "habilitado", lambda: True)
    panel = _panel("El caso nunca fue resuelto por la policía.",
                   "El caso nunca fue resuelto por la policía.")
    llamadas = _fake_llm(monkeypatch, lambda: [
        {"i": 1, "texto": "El caso fue resuelto por la policía."}])
    res = C.pulir([panel], titulo="El robo", slug="test")
    assert res["aceptadas"] == 0
    assert any("negación" in m for m in res["motivos"])
    assert llamadas == ["comics-caption"]


def test_guard_rechaza_nombre_propio_nuevo(monkeypatch):
    monkeypatch.setattr(C, "habilitado", lambda: True)
    panel = _panel("La pintura de Vermeer desapareció del museo.",
                   "La pintura de Vermeer desapareció del museo.")
    llamadas = _fake_llm(monkeypatch, lambda: [
        {"i": 1, "texto": "La pintura de Rembrandt desapareció del museo."}])
    res = C.pulir([panel], titulo="El robo", slug="test")
    assert res["aceptadas"] == 0
    assert any("nombres propios nuevos" in m for m in res["motivos"])
    assert llamadas == ["comics-caption"]


def test_guard_rechaza_atribucion_nueva(monkeypatch):
    monkeypatch.setattr(C, "habilitado", lambda: True)
    panel = _panel("Los autores nunca fueron identificados públicamente.",
                   "Los autores nunca fueron identificados públicamente.")
    llamadas = _fake_llm(monkeypatch, lambda: [
        {"i": 1, "texto": "El FBI confirmó que los autores nunca fueron identificados."}])
    res = C.pulir([panel], titulo="El robo", slug="test")
    assert res["aceptadas"] == 0
    assert any("atribución" in m for m in res["motivos"])
    assert llamadas == ["comics-caption"]


def test_verificador_independiente_puede_rechazar(monkeypatch):
    monkeypatch.setattr(C, "habilitado", lambda: True)
    panel = _panel("Dos hombres entraron al museo.", "Dos hombres entraron al museo.")
    _fake_llm(monkeypatch, lambda: [
        {"i": 1, "texto": "Dos hombres entraron al museo!"}], lambda: [
        {"i": 1, "ok": False, "motivo": "agrega una valoración"}])
    res = C.pulir([panel], titulo="El robo", slug="test")
    assert res["aceptadas"] == 0
    assert panel["narracion"] == "Dos hombres entraron al museo."
    assert any("verificador rechazó" in m for m in res["motivos"])


def test_sin_verificador_no_se_acepta_ningun_caption(monkeypatch):
    monkeypatch.setattr(C, "habilitado", lambda: True)
    panel = _panel("Dos hombres entraron al museo.", "Dos hombres entraron al museo.")

    def fake(messages, **kw):
        if kw.get("tag") == "comics-caption":
            return {"captions": [{"i": 1, "texto": "Dos hombres entraron al museo!"}]}
        raise C.llm.AllProvidersFailed("sin proveedor de verificación")

    monkeypatch.setattr(C.llm, "chat_json", fake)
    res = C.pulir([panel], titulo="El robo", slug="test")
    assert res["aceptadas"] == 0
    assert res["guard"] == "verificador_no_disponible"
    assert panel["caption_via"] == "determinista"


def test_apagado_no_toca_el_llm(monkeypatch):
    monkeypatch.setattr(C, "habilitado", lambda: False)
    panel = _panel("Dos hombres entraron al museo.", "Dos hombres entraron al museo.")
    monkeypatch.setattr(C.llm, "chat_json",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("no debe llamar")))
    res = C.pulir([panel], titulo="El robo", slug="test")
    assert res["via"] == "determinista" and res["propuestas"] == 0


def test_pule_conserva_hechos_y_encuadre(monkeypatch):
    monkeypatch.setattr(C, "habilitado", lambda: True)
    d = _datos()
    paneles = d["paneles"]
    ids = [p["i"] for p in paneles
           if p["rol_ritmico"] != "silencio" and C._partir(p["narracion"])[0].strip()]

    def propuesta():
        out = []
        for p in paneles:
            if p["i"] not in ids:
                continue
            base, _ = C._partir(p["narracion"])
            out.append({"i": p["i"], "texto": base[:-1] + "!" if base else base})
        return out

    llamadas = _fake_llm(monkeypatch, propuesta,
                         lambda: [{"i": i, "ok": True} for i in ids])
    res = C.pulir(paneles, titulo="El robo del museo", slug="test")

    assert llamadas == ["comics-caption", "comics-paridad"]
    assert res["via"] == "llm" and res["aceptadas"] >= 1
    aceptados = [p for p in paneles if p.get("caption_via") == "llm"]
    assert aceptados
    for p in aceptados:
        assert "!" in p["narracion"]
        assert len(p["narracion"]) <= 120
        assert p["paridad"] == {"ok": True, "guard": "determinista+verificador"}
        assert p["ancla_guion"].strip()
    # el encuadre de ritmo no se pierde al reescribir la base
    con_encuadre = [p for p in aceptados if "[" in p["narracion"]]
    assert con_encuadre


def test_qc_bloquea_caption_llm_sin_paridad(tmp_path: Path):
    ep = SimpleNamespace(dir=tmp_path, slug="prueba-caption")
    d = _datos()
    panel = d["paneles"][1]
    panel["caption_via"] = "llm"
    panel["paridad"] = {"ok": False}
    problemas = qc_ejecutar(ep, d, [], {})
    assert any("paridad factual" in p for p in problemas)
    panel["paridad"] = {"ok": True}
    problemas = qc_ejecutar(ep, d, [], {})
    assert not any("paridad factual" in p for p in problemas)


def test_adaptar_registra_la_procedencia_del_pulido(tmp_path: Path, monkeypatch):
    ep = SimpleNamespace(dir=tmp_path, slug="ep-caption",
                         artifacts=tmp_path / "artifacts",
                         metadata=lambda: {"title": "El robo del museo",
                                           "categoria": "misterio"})
    ep.artifacts.mkdir()
    (ep.artifacts / "script.txt").write_text(GUION, encoding="utf-8")
    (ep.artifacts / "sources.json").write_text(json.dumps({"claims": [
        {"claim": c["afirmacion"], "sources": c["fuentes"], "verdict": c["verdict"]}
        for c in CLAIMS]}), encoding="utf-8")
    monkeypatch.setattr("pipeline.comics.captions.pulir",
                        lambda paneles, **kw: {"via": "llm", "aceptadas": 3,
                                               "rechazadas": 1, "guard": "ok"})
    datos = adaptar(ep)
    assert datos["procedencia"]["via_captions"] == "llm"
    assert datos["procedencia"]["captions"]["aceptadas"] == 3
    assert len(datos["paneles"]) >= 15


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
