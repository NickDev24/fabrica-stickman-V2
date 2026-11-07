"""La puerta de publicación: qué cuenta como "publicado" y qué no.

Regla que estos tests fijan: sólo `post.status == "published"` con URL de plataforma es
capítulo publicado. `scheduled`, `publishing` y el 409 por dedup NO son éxito (Zernio los
reintenta o ya existen) y contarlos como publicados fue el "éxito falso" histórico de la fábrica.
Todo corre contra respuestas simuladas: ningún test toca la red ni sube nada.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from pipeline import config
from pipeline.episode import Episode
from pipeline.stages import publicacion as P

TITULO = "Madoff y las seis señales que la SEC decidió no mirar dos veces"  # 65 chars


@pytest.fixture
def ep(tmp_path, monkeypatch):
    projects = tmp_path / "projects"
    projects.mkdir()
    monkeypatch.setattr(config, "PROJECTS", projects)
    episodio = Episode.create("prueba-publicar", TITULO, categoria="crimen")
    meta = episodio.metadata()
    meta.update({"synthetic_content": True, "voice": "edge-tts:es-AR-TomasNeural"})
    episodio.save_metadata(meta)
    (episodio.artifacts / "render_keyframes.json").write_text(
        json.dumps({"status": "pass", "problemas": []}), encoding="utf-8")
    (episodio.dir / "renders").mkdir(exist_ok=True)
    (episodio.dir / "renders" / "prueba-publicar-keyframe.mp4").write_bytes(b"master")
    (episodio.dir / "derivados").mkdir(exist_ok=True)
    (episodio.dir / "derivados" / "facebook-reel.mp4").write_bytes(b"reel")
    return episodio


@pytest.fixture
def zernio_simulado(monkeypatch, ep):
    """zernio.upload y zernio.create_post falsos: registran lo que se les pidió."""
    from pipeline import zernio
    llamado = {"upload": [], "post": []}

    def setear(respuestas: dict):
        """respuestas: plataforma -> cuerpo de la respuesta de Zernio."""
        def _upload(path: Path) -> str:
            llamado["upload"].append(path.name)
            return f"https://cdn/{path.name}"

        def _create(content, media_urls, platforms, publish_now=True, title="",
                    idempotency_key="", tags=None):
            plata = platforms[0]["platform"]
            llamado["post"].append({"plataforma": plata, "clave": idempotency_key,
                                    "tags": tags, "title": title,
                                    "psd": platforms[0].get("platformSpecificData")})
            return respuestas[plata]
        monkeypatch.setattr(zernio, "upload", _upload)
        monkeypatch.setattr(zernio, "create_post", _create)
        monkeypatch.setattr(config, "auto_publish", lambda: True)
        monkeypatch.setattr(config, "zernio_config",
                            lambda: {"api_key": "k", "youtube": "yt", "facebook": "fb"})
        return llamado

    return setear


_PUB = {"post": {"_id": "p1", "status": "published",
                 "platformPostUrl": "https://youtube.com/watch?v=1"}}
_SCHED = {"post": {"_id": "p2", "status": "scheduled"}}
_FAIL = {"_http": 207, "post": {"_id": "p3", "status": "failed"},
         "error": "meta rechazó el archivo"}


def test_los_dos_lados_publicados_es_el_unico_autopublicado_completo(ep, zernio_simulado):
    llamado = zernio_simulado({"youtube": _PUB,
                               "facebook": {"post": {"_id": "p4", "status": "published",
                                                     "platformPostUrl": "https://fb.com/4"}}})
    resultado = P.publicar_automatico(ep)
    assert resultado["exitosas"] == 2 and resultado["plan"] == 2
    assert resultado["estado"] == "AUTO_PUBLISHED"
    assert ep.metadata()["publish_status"] == "AUTO_PUBLISHED"
    assert llamado["upload"] == ["prueba-publicar-keyframe.mp4", "facebook-reel.mp4"]


def test_scheduled_no_es_publicado_episodio_parcial_y_avisa(ep, zernio_simulado):
    """Zernio reintenta solo: no es fallo, pero decir "publicado" con este estado es mentira."""
    llamado = zernio_simulado({"youtube": _PUB, "facebook": _SCHED})
    resultado = P.publicar_automatico(ep)
    assert resultado["exitosas"] == 1
    assert resultado["en_curso"] == 1
    assert resultado["estado"] == "AUTO_PUBLISHED_PARCIAL"
    assert llamado["post"][1]["plataforma"] == "facebook"


def test_failed_terminal_bloquea_el_autopublicado(ep, zernio_simulado):
    zernio_simulado({"youtube": _PUB, "facebook": _FAIL})
    resultado = P.publicar_automatico(ep)
    assert resultado["exitosas"] == 1 and resultado["en_curso"] == 0
    assert resultado["estado"] == "AUTO_PUBLISHED_PARCIAL"


def test_sin_ningun_publicado_no_hay_exito_que_registrar(ep, zernio_simulado):
    zernio_simulado({"youtube": _FAIL, "facebook": _FAIL})
    resultado = P.publicar_automatico(ep)
    assert resultado["exitosas"] == 0
    assert resultado["estado"] == "AUTO_PUBLISH_FALLÓ"
    assert ep.metadata()["publish_status"] == "AUTO_PUBLISH_FALLÓ"


def test_duplicado_por_dedup_cuenta_como_en_curso_no_como_fallo(ep, zernio_simulado):
    """409 por hash de contenido: el capítulo YA está subido; marcarlo falló invita a resubirlo."""
    zernio_simulado({"youtube": {"status": "duplicate", "post": {"_id": "p-orig"}},
                     "facebook": {"post": {"_id": "p5", "status": "published",
                                           "platformPostUrl": "https://fb.com/5"}}})
    resultado = P.publicar_automatico(ep)
    assert resultado["exitosas"] == 1
    assert resultado["en_curso"] == 1


def test_titulo_y_keywords_viajan_como_pide_la_api(ep, zernio_simulado):
    """`title` de arriba es decorativo: el título de YouTube es platformSpecificData.title."""
    llamado = zernio_simulado({"youtube": _PUB,
                               "facebook": {"post": {"_id": "p6", "status": "published",
                                                     "platformPostUrl": "https://fb.com/6"}}})
    P.publicar_automatico(ep)
    yt = next(p for p in llamado["post"] if p["plataforma"] == "youtube")
    assert yt["psd"] == {"title": TITULO}
    assert yt["tags"] and all(not t.startswith("#") for t in yt["tags"])
    fb = next(p for p in llamado["post"] if p["plataforma"] == "facebook")
    assert fb["tags"] is None


def test_idempotency_key_es_distinta_por_pieza_y_estable_por_corrida(ep, zernio_simulado):
    llamado = zernio_simulado({"youtube": _PUB, "facebook": _FAIL})
    P.publicar_automatico(ep)
    claves = {p["clave"] for p in llamado["post"]}
    assert len(claves) == 2
    assert all("prueba-publicar" in c for c in claves)


def test_sin_qc_medido_no_se_publica_a_ciegas(ep, zernio_simulado):
    llamado = zernio_simulado({"youtube": _PUB, "facebook": _PUB})
    (ep.artifacts / "render_keyframes.json").unlink()
    resultado = P.publicar_automatico(ep)
    assert resultado["status"] == "revision_humana_requerida"
    assert llamado["upload"] == []


def test_qc_malo_bloquea_aunque_auto_publish_este_on(ep, zernio_simulado):
    llamado = zernio_simulado({"youtube": _PUB, "facebook": _PUB})
    (ep.artifacts / "render_keyframes.json").write_text(
        json.dumps({"status": "fail", "problemas": ["audio bajo de -14 LUFS"]}),
        encoding="utf-8")
    resultado = P.publicar_automatico(ep)
    assert resultado["status"] == "revision_humana_requerida"
    assert "audio bajo de -14 LUFS" in str(resultado["motivo"])
    assert llamado["upload"] == []


def test_la_aprobacion_del_dueno_salta_el_qc_pero_no_el_gate_de_fuentes(ep, zernio_simulado):
    llamado = zernio_simulado({"youtube": _PUB, "facebook": _PUB})
    (ep.artifacts / "render_keyframes.json").write_text(
        json.dumps({"status": "fail", "problemas": ["frame muerto"]}), encoding="utf-8")
    P.publicar_automatico(ep, aprobado="user")
    assert len(llamado["upload"]) == 2


def test_no_publicar_no_toca_zernio(ep, zernio_simulado):
    llamado = zernio_simulado({"youtube": _PUB, "facebook": _PUB})
    resultado = P.publicar_automatico(ep, no_publish=True)
    assert resultado["status"] == "sin_publicar"
    assert llamado["upload"] == []


def test_titulo_invalido_bloquea_pero_el_dueno_lo_ve_por_telegram(ep, zernio_simulado):
    """Un título fuera de banda es un episodio a mostrarle al dueño, no un error de corrida.

    cortar con SystemExit hacía que run.py lo atrapara como "keyframe BLOQUEADO" y el paquete
    jamás llegaba a Telegram: el dueño se quedaba sin ver nada. Ahora devuelve `status`.
    """
    llamado = zernio_simulado({"youtube": _PUB, "facebook": _PUB})
    (ep.dir / "publicacion").mkdir(exist_ok=True)
    (ep.dir / "publicacion" / "descripciones.json").write_text(
        json.dumps({"titulo": "título corto", "descripcion": "d"}), encoding="utf-8")
    resultado = P.publicar_automatico(ep)
    assert resultado["status"] == "revision_humana_requerida"
    assert "GATE TÍTULO" in resultado["motivo"]
    assert llamado["upload"] == []


def test_un_titulo_fuera_de_banda_bloquea_el_plan_entero(ep, zernio_simulado):
    """El gate de título corre antes de armar el plan: no se sube nada con título inválido."""
    zernio_simulado({"youtube": _PUB, "facebook": _PUB})
    with pytest.raises(SystemExit) as exc:
        P._plan_publicacion(ep, {"youtube": "yt", "facebook": "fb"},
                            {"titulo": "título corto", "descripcion": "d"})
    assert "GATE TÍTULO" in str(exc.value)
