"""Regresión de autonomía 24/7 (2026-11-08).

Dos fallas reales dejaron la fábrica en bucle de tracebacks durante un día:

1. `ideas.verificar` sólo atrapaba `SystemExit`, pero el gate 1 rechaza con `GateFailure`
   (afirmaciones refutadas / fuentes sin independencia). Cada idea refutada mataba el lote
   completo y `auto` volvía a empezar sin producir nada.
2. `guion.asegurar_titulo` reescribía el título tres veces y, si la tercera quedaba válida,
   salía del bucle e indexaba `motivos[0]` de una lista vacía: `IndexError` justo después
   de haber arreglado el título.
"""
from __future__ import annotations

import pytest

from pipeline import gates, ideas
from pipeline.stages import guion as guion_stage


class _Sonda:
    """Sustituto del episodio-sonda que crea ideas.verificar (no toca projects/)."""

    slug = "idea-tema-de-prueba"

    def __init__(self):
        self.state = {"title": "Un título de prueba"}

    def read_state(self) -> dict:
        return dict(self.state)

    def write_state(self, estado: dict) -> None:
        self.state = dict(estado)

    def read_json(self, nombre: str) -> dict:
        return {"claims": []}


def test_una_idea_refutada_por_el_gate_se_descarta_y_el_lote_sigue(monkeypatch):
    sonda = _Sonda()
    monkeypatch.setattr(ideas.Episode, "create",
                        staticmethod(lambda slug, titulo: sonda))
    monkeypatch.setattr("pipeline.stages.descubrir.descubrir", lambda ep, tema: [])
    monkeypatch.setattr("pipeline.stages.research.research", lambda ep: None)
    monkeypatch.setattr(
        "pipeline.stages.research.factcheck",
        lambda ep: (_ for _ in ()).throw(
            gates.GateFailure("fuentes", ["hay afirmaciones refutadas por el fact-check"])),
    )

    card = ideas.verificar({"tema": "tema de prueba", "titulo": "Un título de prueba"})

    assert card["estado"] == "descartada_sin_fuentes"
    assert "refutadas" in card["motivo"]


def test_una_sonda_de_verificacion_no_bloquea_su_propia_idea(tmp_path, monkeypatch):
    """La sonda `idea-*` se reescribe en cada re-verificación: no puede vetar el tema."""
    import json

    from pipeline import config, huellas

    sonda = tmp_path / "idea-tema-de-prueba"
    sonda.mkdir()
    (sonda / "episode.json").write_text(json.dumps({
        "slug": "idea-tema-de-prueba",
        "title": "El misterio de la sonda",
        "verificacion_probe": True,          # sin verificacion_estado: re-verificación fallida
        "stage_status": {"research": "pending", "factcheck": "pending"},
    }), encoding="utf-8")
    monkeypatch.setattr(config, "PROJECTS", tmp_path)
    monkeypatch.setattr(huellas, "PUBLISHED", tmp_path / "no-existe.jsonl")

    assert huellas.intentadas() == []
    contada, _, _ = huellas.ya_contada("El misterio de la sonda")
    assert contada is False


def test_un_esqueleto_sin_etapas_no_quema_la_idea_verificada(tmp_path, monkeypatch):
    """Un corte de cuota deja una carpeta vacía: debe poder reutilizarse, no vetar la idea."""
    import json

    from pipeline import config, run

    monkeypatch.setattr(config, "PROJECTS", tmp_path)
    proyecto = tmp_path / "el-misterio"
    proyecto.mkdir()
    (proyecto / "episode.json").write_text(json.dumps({
        "slug": "el-misterio", "title": "x",
        "stage_status": {"research": "pending", "guion": "pending"},
    }), encoding="utf-8")

    assert run._carpeta_vacia("el-misterio") is True
    assert run._carpeta_vacia("no-existe") is False

    (proyecto / "episode.json").write_text(json.dumps({
        "stage_status": {"research": "done", "guion": "pending"},
    }), encoding="utf-8")
    assert run._carpeta_vacia("el-misterio") is False


class _EpTitulo:
    slug = "titulo-de-prueba"

    def __init__(self):
        self.state = {"title": "x"}

    def read_state(self) -> dict:
        return dict(self.state)

    def write_state(self, estado: dict) -> None:
        self.state = dict(estado)


def test_el_titulo_que_pasa_en_la_tercera_reescritura_no_revienta(monkeypatch):
    from factory import parametros

    monkeypatch.setattr(parametros, "rango_titulo", lambda: (10, 45))
    respuestas = iter(["corto", "muy corto", "El giro que nadie esperaba en 1986"])
    monkeypatch.setattr(guion_stage.llm, "chat", lambda *a, **k: next(respuestas))

    ep = _EpTitulo()
    titulo = guion_stage.asegurar_titulo(ep, "x", "un ángulo con sustancia suficiente")

    assert titulo == "El giro que nadie esperaba en 1986"
    assert ep.state["title"] == titulo


def test_un_titulo_irreparable_se_reporta_como_gate_y_no_como_indexerror(monkeypatch):
    from factory import parametros

    monkeypatch.setattr(parametros, "rango_titulo", lambda: (10, 45))
    monkeypatch.setattr(guion_stage.llm, "chat", lambda *a, **k: "corto")

    with pytest.raises(SystemExit) as excinfo:
        guion_stage.asegurar_titulo(_EpTitulo(), "x", "un ángulo con sustancia suficiente")

    assert "GATE TÍTULO" in str(excinfo.value)


def test_el_gate_de_fuentes_con_una_sola_fuente_es_rechazo_y_no_fallo_duro(tmp_path, monkeypatch):
    """Gate 1 sin 2 dominios por afirmación: rc=2 (descarta y sigue), no rc=1 con backoff.

    Pasó en vivo con "El misterio de Clayface" (2026-11-08): las 4 fuentes eran 2 páginas
    del mismo archive.org más dos notas; el gate lo rechazó con SystemExit y factoryd lo
    trató como caída del motor, dejando la fábrica 15 minutos parada por un rechazo normal.
    """
    from pipeline.stages import research as research_stage

    proj = tmp_path / "ep-prueba"
    (proj / "research").mkdir(parents=True)
    (proj / "research" / "urls.txt").write_text(
        "https://ejemplo.test/a\nhttps://ejemplo.test/b\n", encoding="utf-8")

    class Ep:
        dir = proj
        slug = "ep-prueba"

        def read_state(self):
            return {"categoria": "historia"}

        def write_json(self, nombre, datos):  # pragma: no cover - no debe llegar
            raise AssertionError("no debía escribirse sources.json con el gate roto")

    monkeypatch.setattr(research_stage, "_fetch", lambda url: "texto de fuente " * 40)
    monkeypatch.setattr(research_stage, "_llm_json",
                        lambda *a, **k: {"claims": [{"claim": "algo verificable",
                                                     "source_indices": [0], "quote": "q"}]})

    with pytest.raises(gates.GateFailure) as excinfo:
        research_stage.research(Ep())

    assert excinfo.value.gate == "fuentes"
    assert "2+ dominios" in " ".join(excinfo.value.reasons)


def test_la_idea_rechazada_por_un_gate_se_marca_para_no_repetirla(tmp_path, monkeypatch):
    """Bucle medido 2026-11-08: el gate 1 tumbaba la idea, la carpeta quedaba
    reutilizable y la fábrica volvía a elegir la MISMA ficha ("La bola negra", 0
    fuentes). Ahora la ficha queda descartada y el próximo ciclo elige otra.
    """
    import json

    from pipeline import config, run

    monkeypatch.setattr(config, "STATE", tmp_path)
    ruta = tmp_path / "ideas.json"
    ruta.write_text(json.dumps({"ideas": [
        {"titulo": "¿Qué le pasa a tu cuerpo si jugás a La bola negra?",
         "estado": "verificada"},
        {"titulo": "Otra historia verificada", "estado": "verificada"},
    ]}, ensure_ascii=False), encoding="utf-8")

    class _Ep:
        title = "¿Qué le pasa a tu cuerpo si jugás a La bola negra?"

    run._descartar_idea(_Ep(), "[fuentes] descubrir: sólo 0 fuentes alcanzables")

    cards = json.loads(ruta.read_text(encoding="utf-8"))["ideas"]
    assert cards[0]["estado"] == "descartada_gate"
    assert "0 fuentes" in cards[0]["motivo"]
    assert cards[1]["estado"] == "verificada", "no debe tocar las demás fichas"
