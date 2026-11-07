"""Regresiones del motor keyframe: banda de beats, contrato de prompt y cámara FFmpeg.

Se protege lo que se rompió de verdad:
  1) beats.plan partía el tiempo sin partir el texto -> cada plano hablaba de otra cosa
     y aparecían planos de 4 s (el formato viral no existe con planos de 4 s).
  2) zoompan con comas entre z/x/y -> ffmpeg: "No option name near '(iw-iw/zoom)*on/59'".
  3) armar_prompt con la clave cruda ("senal_final") condicionaba tan poco que el modelo
     devolvía el mismo byte para beats distintos.
  4) loudnorm de pasada única -> -15,9 LUFS medidos; la promesa del brief es -14.
Nada de esto toca la red: el motor de imágenes se prueba sólo si hay credenciales.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from factory.acting import beats as B              # noqa: E402
from pipeline import config, imagen                # noqa: E402
from pipeline.stages import keyframes as K         # noqa: E402


SEGMENTOS = [
    {"texto": "Durante siglos un error de tres grados mandó flotas enteras al fondo del mar "
              "y nadie lo corrigió porque copiar el mapa del maestro era más rápido que medir",
     "dur_s": 12.0},
    {"texto": "La lección es brutal: hoy los mapas son datos", "dur_s": 3.0},
]


def test_todos_los_beats_entran_en_la_banda():
    bs = B.plan(SEGMENTOS)
    assert bs, "el planificador quedó vacío"
    # El realine final contra el audio puede recortar unas centésimas el piso: se tolera
    # 0,95 s antes que un video que dure más que la narración.
    for b in bs:
        assert b["dur_s"] <= B.BEAT_MAX_S + 0.05, f"beat {b['i']} de {b['dur_s']}s"
        assert b["dur_s"] >= 0.95, f"beat {b['i']} corto de más"


def test_el_texto_se_reparte_con_el_tiempo():
    """Si se parte el tiempo, se parte el texto: si no, el beat miente sobre qué se dice."""
    bs = B.plan(SEGMENTOS)
    unido = " ".join(b["texto"] for b in bs if b["segmento"] == 0)
    original = " ".join(B._clausulas(SEGMENTOS[0]["texto"]))
    assert " ".join(unido.split()) == " ".join(original.split())
    total = sum(b["dur_s"] for b in bs)
    assert abs(total - 15.0) < 0.2


def test_pop_y_camara_no_quedan_ociosos():
    bs = B.plan(SEGMENTOS)
    assert any(b["pop"] for b in bs), "ningún beat destacó palabra"
    assert len({b["mov"] for b in bs}) > 1, "la cámara no se mueve en todo el video"


def test_armar_prompt_resuelve_las_claves():
    e = imagen.estilo()
    p = imagen.armar_prompt("super", "corre", "general")
    # Se compara contra la hoja vigente, no contra una redacción histórica: el contrato
    # es que la clave se resuelva, no que el texto de la hoja nunca cambie.
    assert e["acciones"]["corre"] in p, "la acción quedó como clave cruda"
    assert e["escenarios"]["super"] in p, "el escenario quedó como clave cruda"
    assert e["planos"]["general"] in p
    assert "_" not in p.split("no on-screen")[0], "hay claves sin resolver en el prompt"


def test_identidad_literal_al_principio():
    """El personaje es el único ancla de consistencia: si se reordena, se redrawa distinto."""
    e = imagen.estilo()
    for esc, acc, pla in [("calle", "quieto", "medio"), ("bosque", "corre", "general")]:
        assert imagen.armar_prompt(esc, acc, pla).startswith(e["identidad"])


def test_todas_las_claves_del_beats_existen_en_la_hoja():
    """Una clave huérfana en beats.py cae al prompt como texto literal y degrada la imagen."""
    e = imagen.estilo()
    for _, acc in B.ACCIONES:
        assert acc in e["acciones"], f"acción {acc!r} no está en la hoja de personaje"
    for _, esc in B.ESCENARIOS:
        assert esc in e["escenarios"], f"escenario {esc!r} no está en la hoja de personaje"


@pytest.mark.parametrize("mov", sorted(K.CAMARA))
def test_camara_es_un_filtergraph_valido(mov, tmp_path):
    """Cada movimiento se pasa por ffmpeg de verdad: el parser es parte del contrato."""
    img = tmp_path / "kf.png"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi",
                    "-i", "color=c=teal:s=1024x1024", "-frames:v", "1", str(img)], check=True)
    beat = {"i": 0, "dur_s": 0.2, "mov": mov, "fx": ["flash"]}
    out = tmp_path / "plano.mp4"
    K._plano(beat, img, out)
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=width,height,r_frame_rate",
                        "-of", "json", str(out)], capture_output=True, text=True)
    s = json.loads(r.stdout)["streams"][0]
    assert (s["width"], s["height"]) == (K.W, K.H)


def test_normalizador_usa_dos_pasadas(tmp_path):
    wav = tmp_path / "mezcla.wav"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi",
                    "-i", "sine=frequency=220:duration=2", "-c:a", "pcm_s16le", str(wav)],
                   check=True)
    cadena = K._normalizador(wav)
    assert "measured_I=" in cadena and "linear=true" in cadena, "loudnorm sin segunda pasada"


def test_loudnorm_lineal_clava_los_m14(tmp_path):
    """El número final se mide, no se promete: -14 LUFS ±0,5 sobre el archivo normalizado."""
    wav = tmp_path / "mezcla.wav"
    salida = tmp_path / "norm.wav"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi",
                    "-i", "sine=frequency=220:duration=4:beep_factor=4",
                    "-c:a", "pcm_s16le", str(wav)], check=True)
    nl = K._normalizador(wav)
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(wav), "-af", nl,
                    "-ar", "44100", str(salida)], check=True)
    assert abs(K._qc(salida, 4.0)["lufs"] - K.LUFS) <= 0.5


def test_huella_de_imagen_no_congela_prompts_distintos(tmp_path, monkeypatch):
    """Con seed fijo y prompt ignorado, tres beats devolvían el MISMO byte (md5 idéntico)."""
    clave = imagen.huella("flux", "uno", 1024, 1024, 777, None)
    otra = imagen.huella("flux", "dos", 1024, 1024, 777, None)
    assert clave != otra
    # flux no acepta parámetros: lo que no se manda no puede formar parte de la clave
    assert imagen.huella("dreamshaper", "uno", 1024, 576, 5, 8) != \
           imagen.huella("dreamshaper", "uno", 1024, 576, 7, 8)


# ------------------------------------------------------------------ micro-movimiento
def _fuente(tmp_path: Path) -> Path:
    """Foto fija con detalle vertical: sin detalle la deriva de 8 px no se vería."""
    img = tmp_path / "kf.png"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi",
                    "-i", "testsrc=size=1024x1024:rate=1:duration=1",
                    "-frames:v", "1", str(img)], check=True)
    return img


@pytest.mark.parametrize("mov", sorted(K.CAMARA))
def test_ningun_plano_es_un_frame_muerto(tmp_path, mov):
    """El defecto structural de v5: cámara sobre foto fija y cuadro igualmente quieto.

    Medido: un plano estático codificado da 100% de cuadros bajo el umbral de YDIF; con la
    respiración cableada, el mismo plano (mov "fijo") baja a 16%.
    """
    out = tmp_path / f"pl-{mov}.mp4"
    K._plano({"dur_s": 2.0, "mov": mov, "i": 3, "fx": []}, _fuente(tmp_path), out)
    assert K._frames_muertos(out) < K.QC_PROPORCION_MUERTA, f"el plano '{mov}' está quieto"


def test_la_foto_pegada_si_la_barrera_apesta(tmp_path):
    """La barrera no puede ser decorativa: tiene que atrapar el plano que sí está muerto."""
    estatico = tmp_path / "estatico.mp4"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-loop", "1", "-i", str(_fuente(tmp_path)),
                    "-t", "2", "-vf", f"scale={K.W}:{K.H},fps={K.KF_FPS}",
                    "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
                    "-pix_fmt", "yuv420p", "-an", str(estatico)], check=True)
    assert K._frames_muertos(estatico) == 1.0


def test_la_respiracion_no_late_al_unison(tmp_path):
    """Dos planos consecutivos con la misma fase se leen como temblor de cámara, no como vida."""
    fases = {K._deriva(i) for i in range(5)}
    assert len(fases) == 5


def test_el_master_sale_en_la_resolution_del_contrato(tmp_path):
    """El recorte oscilante renderiza con holgura y vuelve a WxH: si no, todo el pipeline se desalinea."""
    out = tmp_path / "pl.mp4"
    K._plano({"dur_s": 2.0, "mov": "fijo", "i": 0, "fx": []}, _fuente(tmp_path), out)
    v = next(s for s in json.loads(subprocess.run(
        ["ffprobe", "-v", "error", "-show_streams", "-of", "json", str(out)],
        capture_output=True, text=True).stdout)["streams"] if s["codec_type"] == "video")
    assert (v["width"], v["height"]) == (K.W, K.H)


def test_los_numeros_de_camara_viven_en_la_config():
    """El JSON y el dict de FFmpeg no pueden ir cada uno por su lado (así nacieron los docs muertos)."""
    from factory import parametros
    assert sorted(parametros.camara_movs()) == sorted(K.CAMARA)
    assert K.RESPIRACION_PX == parametros.motion()["micro_movement"]["respiracion"]["desplazamiento_px"]


def test_el_piso_de_zoom_deja_holgura_para_oscilar():
    """Con zoom 1,00 el recorte no tiene dónde moverse y la deriva se clampa a 0."""
    from factory import parametros
    piso = float(parametros.motion()["camara"]["piso_zoom"])
    assert piso > 1.0
    holgura_s = K.H * (1 - 1 / piso) / 2
    assert holgura_s >= K.RESPIRACION_PX, f"holgura {holgura_s:.1f}px < deriva {K.RESPIRACION_PX}px"
