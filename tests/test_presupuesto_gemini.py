"""Tope DIARIO de Gemini y enfriamiento de proveedores con 429.

Pedido del dueño (2026-11-08): habilitar Gemini para generar contenido con un máximo de
0,50 USD por día. Antes el único freno era mensual (6 USD) y se agotó con 91 llamadas
sin que nada lo avisara hasta el día siguiente. Estos tests fijan el contrato:
- el gasto se anota por día UTC y por mes en el mismo ledger;
- al llegar al tope la llamada NO sale a la red (no se gasta de más) y la cascada sigue;
- un 429 reciente pone al proveedor en espera para no reintentar una cuota muerta.
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timedelta, timezone

import pytest

from pipeline import config, llm


@pytest.fixture
def ledger(tmp_path, monkeypatch):
    """Ledger aislado en tmp: nunca tocar el state/llm_budget.json real."""
    ruta = tmp_path / "llm_budget.json"
    monkeypatch.setattr(config, "GEMINI_BUDGET_FILE", ruta)
    monkeypatch.setattr(llm, "HEALTH", tmp_path / "proveedores.json")
    return ruta


def _hoy() -> str:
    return time.strftime("%Y-%m-%d")


def _mes() -> str:
    return time.strftime("%Y-%m")


def test_tope_diario_bloquea_al_llegar(ledger, monkeypatch):
    monkeypatch.setenv("GEMINI_PRESUPUESTO_USD_DIA", "0.50")
    monkeypatch.setenv("GEMINI_PRESUPUESTO_USD_MES", "15.00")
    ledger.write_text(json.dumps({
        "dias": {_hoy(): {"usd": 0.50, "llamadas": 12}},
        _mes(): {"usd": 6.0},
    }), encoding="utf-8")

    ok, motivo = llm.gasto_gemini_permitido(0.001)
    assert ok is False
    assert "tope diario" in motivo
    assert llm.gasto_gemini_hoy() == pytest.approx(0.50)


def test_bajo_el_tope_deja_pasar(ledger, monkeypatch):
    monkeypatch.setenv("GEMINI_PRESUPUESTO_USD_DIA", "0.50")
    monkeypatch.setenv("GEMINI_PRESUPUESTO_USD_MES", "15.00")
    ledger.write_text(json.dumps({"dias": {_hoy(): {"usd": 0.10}}}), encoding="utf-8")

    ok, motivo = llm.gasto_gemini_permitido(0.02)
    assert ok is True and motivo == ""


def test_tope_en_cero_desactiva_gemini(ledger, monkeypatch):
    monkeypatch.setenv("GEMINI_PRESUPUESTO_USD_DIA", "0")
    ok, motivo = llm.gasto_gemini_permitido()
    assert ok is False and "desactivado" in motivo


def test_llamada_no_sale_a_la_red_con_el_tope_agotado(ledger, monkeypatch):
    """Lo caro no es el error: es la llamada que se hace igual y se factura."""
    monkeypatch.setenv("GEMINI_PRESUPUESTO_USD_DIA", "0.50")
    ledger.write_text(json.dumps({"dias": {_hoy(): {"usd": 0.55}}}), encoding="utf-8")
    monkeypatch.setenv("GEMINI_API_KEY", "clave-de-prueba")

    def prohibido(*a, **k):  # pragma: no cover - sólo falla si se llama
        raise AssertionError("no debía llamarse a Gemini con el tope diario agotado")

    monkeypatch.setattr(llm.requests, "post", prohibido)
    resultado, err = llm._call_provider("gemini", [{"role": "user", "content": "hola"}], 0.0, 100)
    assert resultado is None
    assert "tope diario" in err


def test_el_gasto_se_anota_en_el_dia_y_en_el_mes(ledger):
    llm._registrar_gasto_gemini({"precio_in_usd_mtok": 1_000_000.0,
                                 "precio_out_usd_mtok": 0.0},
                                {"usage": {"prompt_tokens": 10, "completion_tokens": 0}})
    data = json.loads(ledger.read_text(encoding="utf-8"))
    assert data[_mes()]["usd"] == pytest.approx(10.0)
    assert data["dias"][_hoy()]["usd"] == pytest.approx(10.0)
    assert data["dias"][_hoy()]["llamadas"] == 1


def test_imagen_tambien_descuenta_del_dia(ledger):
    llm._registrar_gasto_extra(0.0336, "gemini-3.1-flash-lite-image")
    data = json.loads(ledger.read_text(encoding="utf-8"))
    assert data["dias"][_hoy()]["usd"] == pytest.approx(0.0336)
    assert data["dias"][_hoy()]["imagenes"] == 1


def test_rutas_gemini_primero_salvo_verificacion(monkeypatch):
    monkeypatch.setenv("ALLOW_PAID_LLM", "1")
    monkeypatch.setenv("ALLOW_REMOTE_LLM", "1")
    assert llm.ruta_de("guion")[0] == "gemini"
    assert llm.ruta_de("investigacion")[0] == "gemini"
    # la verificación conserva al proveedor gratis e independiente delante
    ruta = llm.ruta_de("verificacion")
    assert ruta[0] == "cloudflare" and "gemini" in ruta


def test_rate_limit_reciente_pone_en_espera(ledger, monkeypatch):
    monkeypatch.setenv("LLM_COOLDOWN_RATE_LIMIT_S", "1800")
    llm.HEALTH.write_text(json.dumps({"cloudflare": {
        "estado": "rate_limit",
        "detalle": "HTTP 429: cuota diaria",
        "visto": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }}), encoding="utf-8")
    assert "rate-limit" in llm._en_espera("cloudflare")

    llamadas = {"n": 0}
    monkeypatch.setattr(llm.requests, "post",
                        lambda *a, **k: llamadas.__setitem__("n", llamadas["n"] + 1))
    r, err = llm._post("http://x.test", {}, {}, "cloudflare")
    assert r is None and "rate-limit" in err and llamadas["n"] == 0


def test_rate_limit_viejo_ya_no_espera(ledger, monkeypatch):
    monkeypatch.setenv("LLM_COOLDOWN_RATE_LIMIT_S", "60")
    viejo = (datetime.now(timezone.utc) - timedelta(hours=3)).isoformat().replace("+00:00", "Z")
    llm.HEALTH.write_text(json.dumps({"cloudflare": {"estado": "rate_limit",
                                                     "detalle": "429", "visto": viejo}}),
                          encoding="utf-8")
    assert llm._en_espera("cloudflare") == ""
