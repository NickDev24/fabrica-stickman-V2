"""Cómic diario: carrusel en Facebook y aislamiento de fallos (sin red real)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pipeline import zernio  # noqa: E402
from pipeline.comics import ciclo as C  # noqa: E402
from pipeline.comics import publicar as P  # noqa: E402


class _Ep:
    def __init__(self, tmp_path: Path, slug: str = "ep-comic"):
        self.dir = tmp_path
        self.slug = slug

    def read_state(self):
        return {"title": "El robo del museo"}

    def metadata(self):
        return {"angle": "Un giro documental"}


def _comic(tmp_path: Path, aprobado: bool = True) -> _Ep:
    ep = _Ep(tmp_path)
    (tmp_path / "comics" / "carrusel").mkdir(parents=True)
    for n in (1, 2):
        (tmp_path / "comics" / "carrusel" / f"pag-{n:02d}.png").write_bytes(b"png")
    (tmp_path / "comics" / "qc.json").write_text(json.dumps({"aprobado": aprobado}))
    (tmp_path / "comics" / "guion_paneles.json").write_text(json.dumps({
        "titulo": "El robo del museo",
        "grillas": [[3, 3, 3], [2, 2, 2]],
        "paneles": [{"i": 1, "fuentes": ["https://www.fbi.gov/caso"]}],
    }))
    return ep


def _zernio(monkeypatch, estado: str = "published"):
    monkeypatch.setattr(P.config, "auto_publish", lambda: True)
    monkeypatch.setattr(P.config, "zernio_config", lambda: {
        "api_key": "k", "facebook": "fb", "youtube": ""})
    subidos, creado = [], {}

    def fake_upload(p):
        subidos.append(p.name)
        return f"https://cdn.example/{p.name}"

    def fake_post(content, urls, platforms, **kw):
        creado.update(content=content, urls=urls, platforms=platforms, **kw)
        return {"post": {"_id": "p1", "status": estado,
                         "platformPostUrl": "https://facebook.com/p/1"}}

    monkeypatch.setattr(P.zernio, "upload", fake_upload)
    monkeypatch.setattr(P.zernio, "create_post", fake_post)
    return subidos, creado


def test_publica_el_carrusel_en_facebook(tmp_path, monkeypatch):
    ep = _comic(tmp_path)
    subidos, creado = _zernio(monkeypatch)
    out = P.publicar_facebook(ep)
    assert out["status"] == "published"
    assert out["url"] == "https://facebook.com/p/1"
    assert subidos == ["pag-01.png", "pag-02.png"]
    assert creado["platforms"] == [{"platform": "facebook", "accountId": "fb"}]
    assert creado["idempotency_key"] == "ep-comic:comics:facebook"
    assert creado["title"] == "El robo del museo"
    assert "#PulsoCurioso" in creado["content"]


def test_qc_no_aprobado_no_toca_zernio(tmp_path, monkeypatch):
    ep = _comic(tmp_path, aprobado=False)
    _zernio(monkeypatch)
    monkeypatch.setattr(P.zernio, "upload",
                        lambda p: (_ for _ in ()).throw(AssertionError("no debe subir")))
    assert P.publicar_facebook(ep)["status"] == "qc_no_aprobado"


def test_sin_auto_publish_no_publica(tmp_path, monkeypatch):
    ep = _comic(tmp_path)
    _zernio(monkeypatch)
    monkeypatch.setattr(P.config, "auto_publish", lambda: False)
    assert P.publicar_facebook(ep)["status"] == "sin_publicar"


def test_ciclo_no_publica_si_qc_falla(tmp_path, monkeypatch):
    ep = _comic(tmp_path)
    monkeypatch.setattr(C, "habilitado", lambda: True)
    monkeypatch.setattr(C, "adaptar", lambda ep: {"paneles": [], "grillas": []})
    monkeypatch.setattr(C, "fichas", lambda ep, d: {})
    monkeypatch.setattr(C, "generar", lambda ep, d, f: [])
    monkeypatch.setattr(C, "guardar", lambda ep, d: None)
    monkeypatch.setattr(C, "componer", lambda ep, d, r: {"paginas": []})
    monkeypatch.setattr(C, "ejecutar", lambda *a: ["grilla rota"])
    monkeypatch.setattr(C, "registrar", lambda *a, **k: {})
    llamado = []
    monkeypatch.setattr(C, "publicar_facebook", lambda *a, **k: llamado.append(1) or {})
    out = C.producir(ep)
    assert out["status"] == "qc_fallo" and not llamado


def test_ciclo_apagado_por_interruptor(tmp_path, monkeypatch):
    ep = _comic(tmp_path)
    monkeypatch.setattr(C, "habilitado", lambda: False)
    assert C.producir(ep)["status"] == "apagado"


def test_png_se_sube_como_png():
    assert zernio._content_type(Path("pag-01.png")) == "image/png"
    assert zernio._content_type(Path("reel.mp4")) == "video/mp4"
