"""Deploy: un solo `auto` a la vez y el ciclo `diario` sin banderas ignoradas."""
import json
import time

from pipeline import config, diario, run


def test_lock_produccion_serializa(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "STATE", tmp_path)
    assert run._tomar_lock_produccion() is True
    assert run._tomar_lock_produccion() is False
    run._soltar_lock_produccion()
    assert not (tmp_path / "produccion.lock").exists()


def test_lock_huerfano_no_bloquea(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "STATE", tmp_path)
    (tmp_path / "produccion.lock").write_text(
        json.dumps({"pid": 2**31 - 1, "ts_epoch": time.time()}), encoding="utf-8")
    assert run._tomar_lock_produccion() is True
    run._soltar_lock_produccion()


def test_lock_viejo_no_bloquea(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "STATE", tmp_path)
    (tmp_path / "produccion.lock").write_text(
        json.dumps({"pid": 1, "ts_epoch": time.time() - 20_000}), encoding="utf-8")
    assert run._tomar_lock_produccion() is True
    run._soltar_lock_produccion()


def test_diario_respeta_publicar():
    assert diario._argv_auto(True, False) == ["auto"]
    assert diario._argv_auto(False, False) == ["auto", "--no-publicar"]
    assert diario._argv_auto(True, True) == ["auto", "--reciclar-imagenes"]


def test_diario_delega_si_factoryd_esta_vivo(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "STATE", tmp_path)
    (tmp_path / "logs").mkdir()
    (tmp_path / "logs" / "factoryd.log").write_text("linea\n", encoding="utf-8")
    (tmp_path / "factoryd.json").write_text(json.dumps({"modo": "corriendo"}),
                                            encoding="utf-8")
    assert diario._factoryd_vivo() is True
    (tmp_path / "factoryd.json").write_text(json.dumps({"modo": "idle"}),
                                            encoding="utf-8")
    assert diario._factoryd_vivo() is False
