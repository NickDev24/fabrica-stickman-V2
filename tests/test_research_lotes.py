"""Regresión del chunking de research y del gate 1 (2026-11-05).

El factcheck se mandaba entero (30.000 caracteres ≈ 5.730 tokens) y Ollama lo rechazaba
con exceed_context_size_error: AllProvidersFailed cortaba la corrida antes del guion.
Y en la corrida real 3 de 7 afirmaciones quedaron "pendiente" porque el verificador numeró
1..k dentro del lote: el índice se tiraba afuera en silencio y el episodio moría en el gate.
"""
from __future__ import annotations

import pytest
import requests

from pipeline import gates
from pipeline import web
from pipeline.stages import research as r


def test_los_lotes_no_pasan_el_techo_de_contexto():
    bloques = [f"AFIRMACIÓN {i}: " + "x" * 2800 for i in range(8)]
    lotes = r._lotes(bloques)
    assert len(lotes) > 1, "8 bloques de 2.800 caracteres no pueden caber en un solo pedido"
    for lote in lotes:
        assert sum(len(b) for b in lote) + 2 * (len(lote) - 1) <= r.MAX_CHARS_BODY


def test_un_bloque_descomunal_se_recorta_en_vez_de_romper():
    assert r._lotes(["z" * 40000]) == [["z" * r.MAX_CHARS_BODY]]


def test_nada_de_nada_es_ningun_lote():
    assert r._lotes([]) == []


# ------------------------------------------------------------------ lotes con índice

def test_el_lote_devuelve_quienes_estan_adentro():
    blocks = ["A" * 5000, "B" * 5000, "C" * 100]
    assert r._lotes_de([0, 1], blocks) == [[0], [1]], "5.000 + 5.000 no caben en 6.000"
    assert r._lotes_de([0, 2], blocks) == [[0, 2]], "el bloque chico entra en el mismo lote"
    assert r._lotes_de([], blocks) == []


def test_un_indice_del_lote_se_traduce_al_episodio():
    lote = [4, 5, 6]
    assert r._indice_de({"index": 5}, lote) == 5      # el AFIRMACIÓN n del texto
    assert r._indice_de({"index": "3"}, lote) == 6    # vino como string
    assert r._indice_de({"index": 99}, lote) is None  # inventado: no se aplica a nadie
    assert r._indice_de({}, lote) is None


def test_numerar_desde_cero_dentro_del_lote_tambien_se_entiende():
    """El modelo a veces ignora el AFIRMACIÓN n y numera sus propios ítems: no se pierde."""
    lote = [4, 5, 6]
    assert r._indice_de({"index": 0}, lote) == 4
    assert r._indice_de({"index": 2}, lote) == 6      # 2 también es un índice del episodio


# ------------------------------------------------------------------ gate 1

def _sources(verdict="respaldada", urls=("https://a.com/x", "https://b.com/y"), n=1):
    return {"modo": "real", "claims": [
        {"claim": f"afirmación {i}", "verdict": verdict,
         "sources": [{"url": u, "title": "T"} for u in urls]} for i in range(n)]}


@pytest.fixture(autouse=True)
def sin_red(monkeypatch):
    """El gate comprueba que la fuente responda; acá eso se simula, nunca se sale a la red."""
    monkeypatch.setattr(web, "obtener",
                        lambda *a, **kw: type("R", (), {"status_code": 200})())


def test_una_afirmacion_verificada_pasa_el_gate():
    assert gates.gate_fuentes(_sources()) is True


def test_refutada_bloquea_el_gate():
    """El gate buscaba 'refutado' y el verificador escribe 'refutada': pasaba derecho."""
    with pytest.raises(gates.GateFailure) as exc:
        gates.gate_fuentes(_sources(verdict="refutada"))
    assert "refutadas" in str(exc.value)


def test_pendiente_bloquea_el_gate():
    with pytest.raises(gates.GateFailure) as exc:
        gates.gate_fuentes(_sources(verdict="pendiente"))
    assert "sin verdict" in str(exc.value)


def test_dos_fuentes_del_mismo_dominio_no_son_independientes():
    with pytest.raises(gates.GateFailure) as exc:
        gates.gate_fuentes(_sources(urls=["https://a.com/x", "https://a.com/y"]))
    assert "mismo dominio" in str(exc.value)


def test_una_fuente_que_no_responde_frena_el_gate(monkeypatch):
    def morir(*a, **kw):
        raise requests.RequestException("HTTP 406")

    monkeypatch.setattr(web, "obtener", morir)
    with pytest.raises(gates.GateFailure) as exc:
        gates.gate_fuentes(_sources())
    assert "no alcanzable" in str(exc.value)


def test_la_fuente_rota_se_dice_una_vez_aunque_la_citen_cinco_afirmaciones(monkeypatch):
    def selective(url, timeout=None, method=None, **kw):
        if "muerta" in url:
            raise requests.RequestException("HTTP 406")
        return type("R", (), {"status_code": 200})()

    monkeypatch.setattr(web, "obtener", selective)
    with pytest.raises(gates.GateFailure) as exc:
        gates.gate_fuentes(_sources(urls=["https://a.com/x", "https://muerta.com/y"], n=5))
    motivos = str(exc.value)
    assert motivos.count("no alcanzable") == 1, \
        "una sola fuente caída no puede tapar el diagnóstico con 5 líneas iguales"


def test_un_HEAD_bloqueado_no_es_fuente_muerta(monkeypatch):
    """informacion.es contestó 406 al HEAD del gate y la corrida murió con la fuente viva."""
    visto = []

    def solo_get(url, timeout=None, method=None, **kw):
        visto.append(method or "GET")
        if method == "HEAD":
            raise requests.RequestException("HTTP 406")
        return type("R", (), {"status_code": 200})()

    monkeypatch.setattr(web, "obtener", solo_get)
    assert gates.gate_fuentes(_sources()) is True
    assert "HEAD" in visto and "GET" in visto, "el gate tiene que probar el GET antes de rendirse"
