"""Regresión del reintento transitorio de la cascada LLM.

Patrón tomado de Stickman-Studio (tenacity: RETRY_MAX_ATTEMPTS / RETRY_BASE_DELAY), pero
sin el SDK de Google. Antes un 429 tiraba al proveedor y la cascada saltaba al siguiente
modelo; ahora se reintenta el MISMO proveedor con backoff exponencial, y un 401/403/400
no se reintenta nunca (una key rechazada no se arregla esperando).
"""
from __future__ import annotations

import json

import pytest
import requests

from pipeline import config, llm


class Resp:
    def __init__(self, status, body=None, headers=None):
        self.status_code = status
        self._body = body or {}
        self.headers = headers or {}
        self.text = json.dumps(self._body)

    def json(self):
        return self._body


OK = Resp(200, {"choices": [{"message": {"content": "hola"}}]})


@pytest.fixture
def fake(monkeypatch):
    """Proveedor sintético: sin red, sin caché, sin sleep real."""
    monkeypatch.setitem(config.PROVIDERS, "fake",
                        {"url": "http://proveedor.test/chat", "key_env": "FAKE_KEY", "model": "m"})
    monkeypatch.setenv("FAKE_KEY", "k")
    # hermético: el .env real tiene ALLOW_PAID_LLM=1 y sus llaves pagan;
    # sin esto la ruta sintética se pisa con la ruta de producción y el conteo cambia
    for k in ("ALLOW_REMOTE_LLM", "ALLOW_PAID_LLM", "ALLOW_AIONLABS"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(llm, "_health_record", lambda *a, **k: None)
    monkeypatch.setattr(llm, "cache_get", lambda *a, **k: None)
    monkeypatch.setattr(llm, "cache_put", lambda *a, **k: None)
    slept: list[float] = []
    monkeypatch.setattr(llm.time, "sleep", lambda s: slept.append(s))
    return slept


def _secuencia(monkeypatch, respuestas):
    llamadas = {"n": 0}

    def post(url, json=None, headers=None, timeout=None):
        i = llamadas["n"]
        llamadas["n"] += 1
        r = respuestas[min(i, len(respuestas) - 1)]
        if isinstance(r, Exception):
            raise r
        return r

    monkeypatch.setattr(llm.requests, "post", post)
    return llamadas


def test_429_se_reintenta_el_mismo_proveedor_y_gana(monkeypatch, fake):
    llamadas = _secuencia(monkeypatch, [Resp(429), Resp(429), OK])
    res, err = llm._call_provider("fake", [{"role": "user", "content": "x"}], 0.3, 100)
    assert err is None and res["text"] == "hola", err
    assert llamadas["n"] == config.LLM_MAX_RETRIES_PER_PROVIDER
    assert len(fake) == 2, f"esperaba 2 esperas, hubo {fake}"
    assert fake[1] > fake[0], f"el backoff no crece: {fake}"


def test_401_no_se_reintenta(monkeypatch, fake):
    llamadas = _secuencia(monkeypatch, [Resp(401, {"error": "bad key"})])
    res, err = llm._call_provider("fake", [{"role": "user", "content": "x"}], 0.3, 100)
    assert res is None and "key rechazada" in err
    assert llamadas["n"] == 1, "una key inválida no debe gastar 3 llamadas"
    assert fake == []


def test_cae_la_red_se_agota_el_presupuesto_de_intentos(monkeypatch, fake):
    llamadas = _secuencia(monkeypatch, [requests.ConnectionError("corte")])
    res, err = llm._call_provider("fake", [{"role": "user", "content": "x"}], 0.3, 100)
    assert res is None and "error de red" in err and "intentos" in err
    assert llamadas["n"] == config.LLM_MAX_RETRIES_PER_PROVIDER


def test_retry_after_de_429_se_respeta(monkeypatch, fake):
    _secuencia(monkeypatch, [Resp(429, headers={"Retry-After": "9"}), OK])
    res, err = llm._call_provider("fake", [{"role": "user", "content": "x"}], 0.3, 100)
    assert res["text"] == "hola"
    assert fake[0] >= 9.0, f"ignoró Retry-After: {fake}"


def test_chat_no_multiplica_los_intentos(monkeypatch, fake):
    """Un solo dueño del reintento: _post. chat sólo conmuta de proveedor.

    Con los dos bucles superpuestos eran (LLM_MAX_RETRIES+2) x LLM_MAX_RETRIES llamadas
    por proveedor: 15 HTTP y ~40 s de sleep para nada en una máquina de 2 núcleos.
    """
    monkeypatch.setitem(config.PROVIDERS, "otro",
                        {"url": "http://otro.test/chat", "key_env": "OTRO_KEY", "model": "m2"})
    monkeypatch.setenv("OTRO_KEY", "k")
    monkeypatch.setitem(config.TASK_ROUTES, "prueba", ["fake", "otro"])
    llamadas = _secuencia(monkeypatch, [Resp(429)])
    with pytest.raises(llm.AllProvidersFailed):
        llm.chat([{"role": "user", "content": "x"}], task="prueba")
    assert llamadas["n"] == 2 * config.LLM_MAX_RETRIES_PER_PROVIDER


# --- routing por tarea (2026-11-05: ALLOW_PAID_LLM=1 mandaba Gemini al frente de TODAS
# las tareas y las ~90 llamadas baratas de una corrida se comieron los 6 USD del mes) ---

def test_tag_se_traduce_a_tarea_de_config():
    assert config.tarea_para_tag("guion-1") == "guion"
    assert config.tarea_para_tag("factcheck") == "verificacion"
    assert config.tarea_para_tag("queries") == "investigacion"
    assert config.tarea_para_tag("nada_conocido") == "default"


def test_gemini_solo_encabeza_tareas_premium(monkeypatch):
    for k in ("ALLOW_REMOTE_LLM", "ALLOW_PAID_LLM", "ALLOW_AIONLABS"):
        monkeypatch.setenv(k, "1")
    assert llm.ruta_de("guion")[0] == "gemini"
    for barata in ("investigacion", "prompts_visuales", "direccion", "default"):
        assert "gemini" not in llm.ruta_de(barata), barata


def test_verificacion_no_usa_el_mismo_proveedor_que_el_guion(monkeypatch):
    """Misión §3: aunque guion sea premium, quien valida tiene que ser otro modelo."""
    for k in ("ALLOW_REMOTE_LLM", "ALLOW_PAID_LLM"):
        monkeypatch.setenv(k, "1")
    assert llm.ruta_de("verificacion")[0] != llm.ruta_de("guion")[0]


def test_sin_banderas_la_ruta_queda_local(monkeypatch):
    for k in ("ALLOW_REMOTE_LLM", "ALLOW_PAID_LLM", "ALLOW_AIONLABS"):
        monkeypatch.delenv(k, raising=False)
    assert llm.ruta_de("guion") == ["ollama"]
    assert llm.ruta_de("default") == ["ollama"]


def test_el_techo_local_recorta_la_salida_sin_reventar(monkeypatch):
    """Ollama /v1 ignora options.num_ctx: el payload tiene que caber en 4096 tokens."""
    monkeypatch.setenv("OLLAMA_CONTEXTO_TOKENS", "4096")
    mensajes = [{"role": "system", "content": "x" * 30000},
                {"role": "user", "content": "y" * 300}]
    assert llm._techo_local(2600, mensajes) == 120    # no entra: baja al piso, no revienta
    intermedios = [{"role": "system", "content": "x" * 9000}]
    assert llm._techo_local(2600, intermedios) < 2600  # recorte proporcional al prompt
    assert llm._techo_local(900, [{"role": "user", "content": "chico"}]) == 900


def test_el_contenido_de_un_choice_puede_venir_como_objeto():
    assert llm._contenido_de({"message": {"content": "hola"}}) == "hola"
    assert llm._contenido_de({"message": {"content": {"content": "hola"}}}) == "hola"
    assert llm._contenido_de({"message": {"content": ["hola"]}}) == ""   # nunca revienta
    assert llm._contenido_de({}) == ""


def test_sin_razonamiento_no_revienta_con_un_dict():
    """TypeError en plena corrida = episodio perdido (medido 2026-11-05)."""
    assert llm._sin_razonamiento({"respuesta": "x"}) == ""
    assert llm._sin_razonamiento("<reasoning>a</reasoning>b") == "b"


def test_el_tiempo_local_es_proporcional_al_pedido(monkeypatch):
    """240 s FIJOS por lote de factcheck congelaron 40 minutos de corrida (medido 2026-11-05)."""
    monkeypatch.setattr(config, "LLM_LOCAL_TIMEOUT_S", 240)
    chico = {"messages": [{"role": "user", "content": "x" * 800}]}
    lote = {"messages": [{"role": "system", "content": "x" * 6000},
                         {"role": "user", "content": "y" * 500}]}
    assert llm._timeout_local(chico) >= 45, "un prompt chico tiene su chance local"
    assert llm._timeout_local(lote) < 90, "un lote grande no puede tener secos 4 minutos"
    assert llm._timeout_local({"messages": [{"content": "x" * 400000}]}) == 240, "respeta el techo"
    assert llm._timeout_local({}) == 45
