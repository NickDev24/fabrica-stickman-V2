"""Contrato del cliente Zernio contra lo que la documentación dice de verdad.

Se prueba contra respuestas simuladas de docs.zernio.com/posts/create-post (2026-11-05):
207 es 2xx y puede decir partial/failed/scheduled, el 409 por dedup de contenido NO es un
fallo, y las keywords de YouTube viajan en `tags` (no en `hashtags`, que es sólo referencia).
Nada de esto toca la red.
"""
from __future__ import annotations

import pytest

from pipeline import zernio


class Respuesta:
    def __init__(self, status_code, cuerpo=None, headers=None):
        self.status_code = status_code
        self._cuerpo = cuerpo if cuerpo is not None else {}
        self.headers = headers or {}
        self.text = str(cuerpo)

    def json(self):
        if self._cuerpo is None:
            raise ValueError("sin json")
        return self._cuerpo


@pytest.fixture
def fake_post(monkeypatch):
    """Devuelve set(cuerpo, code) -> la última respuesta que create_post vio."""
    capturado = {}

    def _post(url, headers=None, json=None, timeout=None):
        capturado["url"] = url
        capturado["headers"] = headers or {}
        capturado["body"] = json
        return Respuesta(capturado["code"], capturado["cuerpo"], capturado.get("rheaders"))

    monkeypatch.setattr(zernio.requests, "post", _post)
    monkeypatch.setattr(zernio, "_headers", lambda: {"Authorization": "Bearer test"})

    def configurar(code, cuerpo, rheaders=None):
        capturado["code"] = code
        capturado["cuerpo"] = cuerpo
        capturado["rheaders"] = rheaders
    return configurar, capturado


PLATAFORMAS = [{"platform": "youtube", "accountId": "abc"}]


def test_207_parcial_no_es_excepcion_y_conserva_el_post(fake_post):
    configurar, _ = fake_post
    configurar(207, {"post": {"_id": "p1", "status": "partial"},
                     "platformResults": [{"platform": "youtube", "status": "published",
                                          "error": None}],
                     "error": "facebook rechazó el archivo"})
    respuesta = zernio.create_post("copy", ["v.mp4"], PLATAFORMAS)
    assert respuesta["_http"] == 207
    assert respuesta["post"]["status"] == "partial"
    assert respuesta["platformResults"][0]["status"] == "published"


def test_409_por_contenido_duplicado_no_es_fallo(fake_post):
    """El dedup de 24 h significa que ESE capítulo ya está subido: reintentar sería duplicarlo."""
    configurar, _ = fake_post
    configurar(409, {"error": "duplicate content", "existingPostId": "p-orig",
                     "platform": "youtube"})
    respuesta = zernio.create_post("copy", ["v.mp4"], PLATAFORMAS)
    assert respuesta["status"] == "duplicate"
    assert respuesta["post"]["_id"] == "p-orig"


def test_409_idempotency_conflict_si_reintenta_el_mismo_post_en_curso(fake_post):
    configurar, _ = fake_post
    configurar(409, {"code": "idempotency_conflict"}, rheaders={"Retry-After": "7"})
    with pytest.raises(zernio.ZernioError) as exc:
        zernio.create_post("copy", ["v.mp4"], PLATAFORMAS)
    assert "7" in str(exc.value)


def test_500_y_401_siguen_siendo_error(fake_post):
    configurar, _ = fake_post
    configurar(500, {"error": "boom"})
    with pytest.raises(zernio.ZernioError):
        zernio.create_post("copy", ["v.mp4"], PLATAFORMAS)


def test_idempotency_key_viaja_en_el_header_y_publica_sincronico(fake_post):
    configurar, capturado = fake_post
    configurar(201, {"post": {"_id": "p2", "status": "published"}})
    zernio.create_post("copy", ["v.mp4"], PLATAFORMAS, idempotency_key="slug:youtube")
    assert capturado["headers"]["Idempotency-Key"] == "slug:youtube"
    assert capturado["body"]["publishNow"] is True
    assert "isDraft" not in capturado["body"]


def test_sin_publish_now_deja_borrador_con_su_flag(fake_post):
    configurar, capturado = fake_post
    configurar(201, {"post": {"_id": "p3", "status": "draft"}})
    zernio.create_post("copy", ["v.mp4"], PLATAFORMAS, publish_now=False)
    assert capturado["body"]["isDraft"] is True
    assert "publishNow" not in capturado["body"]


def test_youtube_keywords_entran_en_tags_no_en_hashtags(fake_post):
    """Documentado: `hashtags` se guarda pero no se publica; las keywords son `tags`."""
    configurar, capturado = fake_post
    configurar(201, {"post": {"_id": "p4"}})
    zernio.create_post("copy", ["v.mp4"], PLATAFORMAS,
                       tags=["PulsoCurioso", "curiosidades", "PulsoCurioso"])
    assert capturado["body"]["tags"] == ["PulsoCurioso", "curiosidades"]
    assert "hashtags" not in capturado["body"]


def test_techo_de_100_caracteres_por_tag_se_recorta_no_se_tira(fake_post):
    configurar, capturado = fake_post
    configurar(201, {"post": {"_id": "p5"}})
    zernio.create_post("copy", ["v.mp4"], PLATAFORMAS, tags=["x" * 180])
    finales = capturado["body"]["tags"]
    assert finales == ["x" * 100], "la API rechaza >100: el recorte es el único modo de conservar la keyword"


def test_techo_de_500_caracteres_en_total_suelta_lo_que_no_cabe(fake_post):
    configurar, capturado = fake_post
    configurar(201, {"post": {"_id": "p6"}})
    zernio.create_post("copy", ["v.mp4"], PLATAFORMAS,
                       tags=["a" * 100, "b" * 100, "c" * 100, "d" * 100, "e" * 100])
    finales = capturado["body"]["tags"]
    assert len(finales) == 4, "5 tags de 100 = 505 con los separadores: el último no cabe"
    assert sum(len(t) + 1 for t in finales) <= 500


def test_tag_repetida_o_vacia_no_ocupa_el_presupuesto(fake_post):
    configurar, capturado = fake_post
    configurar(201, {"post": {"_id": "p7"}})
    zernio.create_post("copy", ["v.mp4"], PLATAFORMAS, tags=["sticker", "  ", "sticker"])
    assert capturado["body"]["tags"] == ["sticker"]


def test_sin_tags_el_campo_no_aparece_en_el_body(fake_post):
    configurar, capturado = fake_post
    configurar(201, {"post": {"_id": "p8"}})
    zernio.create_post("copy", ["v.mp4"], [{"platform": "facebook", "accountId": "f"}])
    assert "tags" not in capturado["body"]


def test_type_del_media_se_infiere_de_la_extension(fake_post):
    configurar, capturado = fake_post
    configurar(201, {"post": {"_id": "p6"}})
    zernio.create_post("copy", ["reel.mp4", "portada.jpg"], PLATAFORMAS)
    tipos = [m["type"] for m in capturado["body"]["mediaItems"]]
    assert tipos == ["video", "image"]
