"""Tests del paquete comics — sin red, sin tocar el pipeline de video.

Validan el contrato comics.v2 (orden del dueño): >= 15 viñetas, grillas reales
de 3 bandas (1-4 por banda), ritmo (gancho/cliffhanger/silencio/remate),
anclaje al guion verificado, composición en libro y QC bloqueante.
La generación de imagen se mockea/usa miniaturas locales (cuota no se toca).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from PIL import Image

from pipeline.comics.adaptar_guion import (
    MAX_BEATS, MIN_BEATS, NARRACION_MAX, NARRACION_MAX_PALABRAS, VINETAS_MIN,
    _agrupar, _aplicar_presupuesto, _determinista, _grillas_para, _oraciones,
    _asignar_ritmo, _recorte_palabras,
)
from pipeline.comics.componer import PAG_H, PAG_W, componer
from pipeline.comics.qc import _es_panel_negro, ejecutar as qc_ejecutar

GUIION = """# El robo del museo

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
     "fuentes": ["https://www.museo.org/theft", "https://apnews.com/articulo"],
     "verdict": "verificada"},
    {"afirmacion": "La pérdida superó quinientos millones de dólares según el FBI",
     "fuentes": ["https://www.fbi.gov/caso"], "verdict": "verificada"},
    {"afirmacion": "El caso sigue sin resolverse más de tres décadas después",
     "fuentes": ["https://www.museo.org/theft"], "verdict": "verificada"},
]


def _storyboard(n_oraciones: int = 13) -> dict:
    oraciones = _oraciones(GUIION)[:n_oraciones]
    d = _determinista(oraciones, CLAIMS, "El robo del museo")
    _asignar_ritmo(d["paneles"], d["grillas"])
    return d


def test_oraciones_saca_el_headboard_y_vacio():
    oraciones = _oraciones(GUIION)
    assert oraciones and "robo del museo" not in " ".join(oraciones).lower()[:40]
    assert all(len(o) > 3 for o in oraciones)


def test_determinista_exige_min_beats():
    """Sin >= MIN_BEATS oraciones no hay capítulo con oficio — SystemExit honesto."""
    with pytest.raises(SystemExit):
        _determinista(_oraciones(GUIION)[:MIN_BEATS - 1], CLAIMS, "El robo del museo")


def test_agrupar_cubre_todas_las_oraciones_consecutivas():
    muchas = _oraciones(GUIION) * 5          # 65 oraciones
    bloques = _agrupar(muchas)
    assert len(bloques) == MAX_BEATS
    plano = [" ".join(b) for b in bloques]
    assert " ".join(plano) == " ".join(muchas)


def test_determinista_v2_15_vinetas_con_13_oraciones():
    d = _storyboard(13)
    paneles = d["paneles"]
    assert len(paneles) == VINETAS_MIN
    # grillas reales: 3 bandas por página, 1-4 viñetas por banda, suma exacta
    assert d["grillas"] == _grillas_para(len(paneles))
    for g in d["grillas"]:
        assert len(g) == 3 and all(1 <= b <= 4 for b in g)
    assert sum(sum(g) for g in d["grillas"]) == len(paneles)
    # numeración consecutiva y anclaje al guion verificado
    for k, p in enumerate(paneles, 1):
        assert p["i"] == k
        assert p["narracion"].strip()
        assert len(p["narracion"]) <= NARRACION_MAX
        if p["rol_ritmico"] != "silencio":
            assert p["ancla_guion"].strip()
        ci = p["claim_idx"]
        if ci is not None:
            assert 0 <= ci < len(CLAIMS)
            assert p["fuentes"], f"viñeta {k} con claim debe arrastrar fuentes"


def test_ritmo_gancho_pagina_cliffhanger_remate():
    d = _storyboard(13)
    paneles = d["paneles"]
    assert paneles[0]["rol_ritmico"] == "gancho"
    assert paneles[-1]["rol_ritmico"] == "remate"
    roles = [p["rol_ritmico"] for p in paneles]
    assert "silencio" in roles
    # cada página no final cierra en cliffhanger o en silencio (y si es silencio,
    # el teaser retrocede al penúltimo — nunca se pierde el cierre de página)
    cortes, acum = [], 0
    for g in d["grillas"]:
        acum += sum(g)
        cortes.append(acum)
    for cierre in cortes[:-1]:
        fin = paneles[cierre - 1]
        assert fin["rol_ritmico"] in ("cliffhanger", "silencio"), roles
        if fin["rol_ritmico"] == "silencio":
            assert paneles[cierre - 2]["rol_ritmico"] == "cliffhanger"
    # el silencio-caption y cliffhanger llevan ENCUDADRE de ritmo, no de hecho:
    cliff = [p for p in paneles if p["rol_ritmico"] == "cliffhanger"]
    assert cliff and all("[" in p["narracion"] for p in cliff)


def test_vineta_negra_sin_imagen_no_quema_cuota(tmp_path: Path):
    from pipeline.comics.imagen import generar
    from pipeline.comics.personajes import fichas as _fichas

    ep = type("Ep", (), {})()
    ep.dir = tmp_path
    ep.slug = "prueba-negro"
    d = _storyboard(13)
    fichas_map = _fichas(ep, d)

    llamadas = []
    import pipeline.comics.imagen as im_mod
    original = im_mod.imagen.generar
    im_mod.imagen.generar = lambda *a, **k: llamadas.append(a) or None
    try:
        rutas = generar(ep, d, fichas_map)
    finally:
        im_mod.imagen.generar = original
    n_silencio = sum(1 for p in d["paneles"] if p.get("accion") == "silencio")
    assert llamadas and len(llamadas) == len(d["paneles"]) - n_silencio
    assert all(str(p.get("procedencia_imagen", "")).startswith("panel_negro")
               for p in d["paneles"] if p.get("accion") == "silencio")
    assert [Path(r).name for r in rutas] == [f"p-{p['i']:03d}.jpg" for p in d["paneles"]]


def test_componer_v2_libro_paginas_carrusel(tmp_path: Path):
    ep = type("Ep", (), {})()
    ep.dir = tmp_path
    ep.slug = "prueba-libro"
    d = _storyboard(13)
    # imágenes juguetonas: cuadrados decodificables suficientemente grandes
    rutas = {}
    for p in d["paneles"]:
        if p.get("accion") == "silencio":
            continue
        im = Image.new("RGB", (256, 256), (180, 40, 40))
        ruta = tmp_path / f"p-{p['i']:03d}.jpg"
        im.save(ruta, "JPEG")
        rutas[p["i"]] = ruta
    orden = [rutas.get(p["i"], tmp_path / "nada.jpg") for p in d["paneles"]]
    art = componer(ep, d, orden)
    n_pag = len(d["grillas"])
    assert len(art["paginas"]) == n_pag
    for pa in art["paginas"]:
        assert Image.open(pa).size == (PAG_W, PAG_H)
    assert Image.open(art["chapter_vertical"]).size == (PAG_W, PAG_H * n_pag)
    assert len(art["carrusel"]) == n_pag
    assert art["pagina"] == art["paginas"][0]
    manifest = json.loads((tmp_path / "comics" / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["schema"] == "comics.v2"
    assert manifest["vinetas"] == VINETAS_MIN
    assert manifest["texto_fuera_del_generador"] is True


def test_qc_v2_bloquea_lo_que_rompe_el_oficio(tmp_path: Path):
    ep = type("Ep", (), {})()
    ep.dir = tmp_path
    ep.slug = "prueba-qc"
    d = _storyboard(13)
    # 1) capítulo corto: rompe el mínimo del dueño
    corto = {"schema": "comics.v2", "grillas": [[3, 3, 3]], "paneles": d["paneles"][:9]}
    problemas = qc_ejecutar(ep, corto, [], {})
    assert any("mínimo del dueño" in p for p in problemas)
    # 2) grilla malformada: 2 bandas
    mal = dict(d)
    mal["grillas"] = [[9, 6]]
    problemas = qc_ejecutar(ep, mal, [], {})
    assert any("bandas (deben ser 3)" in p for p in problemas)
    # 3) la historiabuena y completa pasa el QC estructural (sin imágenes: EQP solo
    # reclama imágenes, no grillas ni ritmo)
    problemas = qc_ejecutar(ep, d, [], {})
    assert not any("mínimo del dueño" in p or "bandas" in p for p in problemas)
    qc = json.loads((tmp_path / "comics" / "qc.json").read_text(encoding="utf-8"))
    assert qc["vinetas"] == VINETAS_MIN and qc["paginas"] == len(d["grillas"])


def test_qc_v2_exige_fuentes_en_toda_pagina(tmp_path: Path):
    ep = type("Ep", (), {})()
    ep.dir = tmp_path
    ep.slug = "prueba-fuentes"
    d = _storyboard(13)
    for p in d["paneles"]:
        if p.get("pagina") == 1:
            p["fuentes"] = []
            p["claim_idx"] = None
    problemas = qc_ejecutar(ep, d, [], {})
    assert any("página 1: sin fuentes verificadas" in p for p in problemas)


# ------------------------------------------- presupuesto de palabras del caption
def test_recorte_palabras_prefiere_clausulas_completas():
    texto = "Las fuentes públicas confirman la fecha, el disfraz policial, el total de obras"
    assert _recorte_palabras(texto, 13) == texto
    assert _recorte_palabras(texto, 9) == "Las fuentes públicas confirman la fecha, el disfraz policial"


def test_aplicar_presupuesto_recorta_el_caption():
    paneles = [{"i": 1, "rol_ritmico": "contexto",
                "narracion": "Las fuentes públicas confirman la fecha, el disfraz policial, "
                             "el total de obras y que el caso sigue abierto."}]
    ajustadas = _aplicar_presupuesto(paneles)
    assert ajustadas == 1
    assert len(paneles[0]["narracion"].split()) <= NARRACION_MAX_PALABRAS


def test_aplicar_presupuesto_elige_encuadre_mas_corto():
    """El encuadre entra completo: si la suma supera el cupo, se prueba con otro más
    corto del mismo rol antes de recortar la base (caso real: viñeta 8 de Gardner)."""
    paneles = [{"i": 8, "rol_ritmico": "cliffhanger",
                "narracion": "La pérdida se estima en más de 500 millones de dólares. "
                             "[Lo que vino después no estaba en el libreto de nadie.]"}]
    assert len(paneles[0]["narracion"].split()) > NARRACION_MAX_PALABRAS
    _aplicar_presupuesto(paneles)
    assert len(paneles[0]["narracion"].split()) <= NARRACION_MAX_PALABRAS
    assert paneles[0]["narracion"].startswith("La pérdida se estima")
    assert paneles[0]["narracion"].endswith("]")


def test_el_adaptador_deja_los_captions_dentro_del_presupuesto():
    """Sin esto el QC bloquea el book por un caption que el adaptar podía recortar."""
    d = _determinista(_oraciones(GUIION), CLAIMS, "El robo del museo")
    _asignar_ritmo(d["paneles"], d["grillas"])
    _aplicar_presupuesto(d["paneles"])
    for p in d["paneles"]:
        if str(p.get("narracion", "")).strip():
            assert len(p["narracion"].split()) <= NARRACION_MAX_PALABRAS, \
                f"viñeta {p['i']}: {len(p['narracion'].split())} palabras"


def test_es_panel_negro_con_pillow_13(tmp_path: Path):
    """Pillow 13 ya no permite rebanar getdata(): el QC reventaba con TypeError."""
    negro = tmp_path / "negro.png"
    blanco = tmp_path / "blanco.png"
    Image.new("L", (120, 120), 0).save(negro)
    Image.new("L", (120, 120), 255).save(blanco)
    assert _es_panel_negro(negro) is True
    assert _es_panel_negro(blanco) is False
