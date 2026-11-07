"""Regresión del ciclo de aprendizaje: medir -> aprender -> no repetir la historia.

Es la promesa del dueño (2026-11-05): la fábrica estudia sus propios números y la próxima
pieza sale mejor y distinta. Cuatro invariantes:
  1. sin métricas reales no hay pesos movidos ni cambios simulados;
  2. UN solo cambio por episodio;
  3. lo escrito en state/aprendizaje.json llega a los números reales del guion;
  4. una historia ya contada no se vuelve a elegir, aunque el texto sea otro.
"""
from __future__ import annotations

import json
import statistics

import pytest

from factory import parametros
from pipeline import aprendizaje, config, huellas, metricas

# a-uno es el episodio malo a propósito: la mediana del canal la fijan a-dos y a-tres, y
# este queda muy por debajo en gancho, CTR y duración media. Sin un caso así ninguna regla
# dispara, y una prueba verde no probaría nada.
FILA_1 = {"slug": "a-uno", "plataforma": "youtube", "postId": "p1", "video_id": "v1",
          "fecha": "2026-11-01", "vistas": 1000, "impresiones": 10000, "clicks": 50,
          "ctr_impresiones": 0.005, "retencion_30s": 0.45, "retencion_media": 0.5,
          "duracion_media_s": 150.0, "duracion_video_s": 600.0,
          "retencion_curva_puntos": [[i / 20, 1.0 - i / 40] for i in range(21)],
          "sincronia": "ok"}
FILA_2 = {**FILA_1, "slug": "a-dos", "fecha": "2026-11-02", "clicks": 350,
          "ctr_impresiones": 0.035, "retencion_30s": 0.85, "duracion_media_s": 320.0,
          "retencion_media": 0.55}
FILA_3 = {**FILA_2, "slug": "a-tres", "fecha": "2026-11-03", "clicks": 400,
          "ctr_impresiones": 0.04, "retencion_30s": 0.90, "duracion_media_s": 340.0,
          "retencion_media": 0.6}


@pytest.fixture
def isolation(tmp_path, monkeypatch):
    """Ninguna prueba toca state/ real: hay una fábrica corriendo mientras tanto."""
    monkeypatch.setattr(metricas, "METRICAS", tmp_path / "metricas.jsonl")
    monkeypatch.setattr(aprendizaje, "APRENDIZAJE", tmp_path / "aprendizaje.json")
    monkeypatch.setattr(aprendizaje, "ITERACIONES", tmp_path / "iteraciones.jsonl")
    monkeypatch.setattr(parametros, "APRENDIZAJE", tmp_path / "aprendizaje.json")
    parametros.recargar()
    yield tmp_path
    parametros.recargar()


def _volcar(filas):
    with metricas.METRICAS.open("a", encoding="utf-8") as fh:
        for fila in filas:
            fh.write(json.dumps(fila) + "\n")


# ------------------------------------------------------------------ métricas

def test_un_post_202_no_se_registra_como_cero():
    fila = metricas.fila_de({"slug": "s", "plataforma": "youtube", "postId": "p",
                             "url": "", "video_id": ""}, {"_sync": "pendiente"})
    assert fila["sincronia"] == "pendiente"
    assert fila["vistas"] is None
    assert {"retencion_30s", "ctr_impresiones", "comentarios"} <= set(fila), \
        "los campos que pide retention_loop.json tienen que existir siempre"


def test_la_analitica_de_youtube_se_traduce_a_las_senales_de_la_config():
    fila = metricas.fila_de(
        {"slug": "s", "plataforma": "youtube", "postId": "p", "url": "u", "video_id": "v"},
        {"views": 500, "impressions": 10000, "clicks": 250, "completionRate": 40,
         "videoDurationSeconds": 600,
         "retentionCurve": [{"elapsedVideoTimeRatio": 0.05, "audienceWatchRatio": 0.9},
                            {"elapsedVideoTimeRatio": 0.1, "audienceWatchRatio": 0.7}]})
    assert fila["vistas"] == 500
    assert fila["ctr_impresiones"] == 0.025
    assert fila["retencion_media"] == 0.4           # 40 % -> 0,40
    assert fila["duracion_media_s"] == 240.0        # 0,40 x 600 s
    assert fila["retencion_30s"] == 0.9             # punto más cercano a los 30 s


def test_medianas_por_plataforma_usando_el_ultimo_corte(isolation):
    _volcar([FILA_1, {**FILA_2, "vistas": 50}, {**FILA_2, "vistas": 900}])
    mediana = metricas.medianas(metricas.usable())["youtube"]
    assert mediana["episodios"] == 2                 # a-dos cuenta una vez (el último corte)
    assert mediana["vistas"] == statistics.median([1000, 900])


def test_una_fila_sin_numeros_reales_no_entra_en_ninguna_mediana(isolation):
    _volcar([FILA_1, {**FILA_2, "sincronia": "pendiente"}])
    assert [f["slug"] for f in metricas.usable()] == ["a-uno"]


# ------------------------------------------------------------------ aprendizaje

def test_sin_datos_suficientes_no_inventa_pesos(isolation):
    _volcar([FILA_1])
    estado = aprendizaje.aprender()
    assert estado["episodios_medidos"] == 1
    assert estado["pesos"] == {} and estado["overrides"] == {}
    assert "sin_datos_suficientes" in estado["estado"]
    assert not aprendizaje.ITERACIONES.exists()


def test_tres_episodios_un_cambio_y_nada_mas(isolation, monkeypatch):
    _volcar([FILA_1, FILA_2, FILA_3])
    monkeypatch.setattr(aprendizaje, "MIN_EPISODIOS", 3)
    estado = aprendizaje.aprender()
    assert estado["overrides"], "el episodio por debajo de la mediana tenía que dejar un cambio"
    assert len(estado["overrides"]) == 1, "UN cambio por episodio: dos variables no enseñan nada"
    assert estado["pesos"] == {}, "con 3 episodios aún no se mueven los pesos (piden 10)"
    fila = json.loads(aprendizaje.ITERACIONES.read_text(encoding="utf-8").splitlines()[-1])
    requeridos = set(aprendizaje.loop_config()["registro_de_iteracion"]["campos_requeridos"])
    assert requeridos <= set(fila), f"faltan campos del registro: {requeridos - set(fila)}"


def test_gana_la_regla_que_mas_episodios_afecta_no_el_ultimo_numero(isolation, monkeypatch):
    """El cambio se elige con la evidencia de TODOS los medidos, no con el último episodio."""
    filas = [{**FILA_2, "slug": slug, "fecha": fecha,
              "retencion_30s": r30, "ctr_impresiones": ctr}
             for slug, fecha, r30, ctr in
             [("m-uno", "2026-11-01", 0.30, 0.030), ("m-dos", "2026-11-02", 0.40, 0.030),
              ("b-uno", "2026-11-03", 0.85, 0.035), ("b-dos", "2026-11-04", 0.90, 0.005)]]
    _volcar(filas)
    monkeypatch.setattr(aprendizaje, "MIN_EPISODIOS", 3)
    estado = aprendizaje.aprender()
    resumen = {r["id"]: r["episodios_afectados"] for r in estado["reglas_disparadas"]}
    assert resumen["R1_gancho"] == 2, "dos episodios con el gancho bajo son la evidencia"
    assert resumen["R5_ctr_bajo"] == 1, "el CTR hundido es de UN solo episodio"
    assert estado["cambio_activo"]["regla"].startswith("R1"), \
        "con más evidencia encima, el peor número suelto no puede ganar"
    assert estado["cambio_activo"]["episodios_afectados"] == 2
    assert list(estado["overrides"]) == ["hook_palabras"]


def test_el_cambio_escrito_es_el_numero_que_usa_el_guion(isolation):
    _volcar([FILA_1, FILA_2, FILA_3])
    estado = aprendizaje.aprender()
    clave, valor = next(iter(estado["overrides"].items()))
    if clave == "hook_palabras":
        assert parametros.hook_palabras() == tuple(valor)
    elif clave == "bucle_intervalo_segundos":
        assert parametros.bucles_config()[0] == tuple(valor)
    elif clave == "directiva_guion":
        assert valor in parametros.directiva_aprendida()
    else:
        assert clave == "recorte_palabras"
        assert any(b.get("ajustado_por_aprendizaje") for b in parametros.bloques())


def test_el_override_de_gancho_aprieta_sin_tocar_lo_demas(isolation):
    ruta = isolation / "aprendizaje.json"
    ruta.write_text(json.dumps({"overrides": {"hook_palabras": [4, 8]}}), encoding="utf-8")
    parametros.recargar()
    antes = parametros.palabras_objetivo()
    assert parametros.hook_palabras() == (4, 8)
    assert parametros.palabras_objetivo() == antes       # sólo se tocó lo que dice la regla


def test_el_recorte_de_bloques_es_idempotente_y_no_toca_el_json(isolation):
    (isolation / "aprendizaje.json").write_text(
        json.dumps({"overrides": {"recorte_palabras": {"planteamiento": 20}}}), encoding="utf-8")
    parametros.recargar()
    objetivos = [next(b["words_target"] for b in parametros.bloques()
                      if b.get("block_id") == "planteamiento") for _ in range(2)]
    assert objetivos[0] == [88, 112], "20 palabras menos sobre [108, 132]"
    assert objetivos[0] == objetivos[1], "el recorte se aplica dos veces: está mutando la cache"


def test_los_pesos_de_nichos_vienen_de_aprendizaje_json(monkeypatch, tmp_path):
    from pipeline import nichos
    archivo = tmp_path / "aprendizaje.json"
    monkeypatch.setattr(nichos, "APRENDIZAJE", archivo)
    assert set(nichos.pesos().values()) == {1.0}, "sin archivo los pesos arrancamos parejos"
    archivo.write_text(json.dumps({"pesos": {"politica": 1.32}}), encoding="utf-8")
    assert nichos.pesos()["politica"] == 1.32


# ------------------------------------------------------------------ anti-repetición

@pytest.fixture
def proyectos_vacios(tmp_path, monkeypatch):
    """Sin esto la comparación tocaría los episodios reales de projects/ (no hermético)."""
    monkeypatch.setattr(config, "PROJECTS", tmp_path / "projects-sin")


def _publicado(tmp_path, monkeypatch, **fila):
    archivo = tmp_path / "published.jsonl"
    archivo.write_text(json.dumps(fila), encoding="utf-8")
    monkeypatch.setattr(huellas, "PUBLISHED", archivo)
    return archivo


def test_la_misma_historia_con_otras_palabras_se_reconoce(monkeypatch, tmp_path, proyectos_vacios):
    _publicado(tmp_path, monkeypatch, slug="midterms-2026",
               script="Las elecciones de medio término de 2022 en "
               "Estados Unidos definieron el control de la Cámara de "
               "Representantes y del Congreso completo, partido demócrata "
               "y partido republicano disputaron cada escaño.")
    contada, slug, similitud = huellas.ya_contada(
        "Quién controló el Congreso en las elecciones de medio término de 2022 y cómo "
        "reaccionó el partido demócrata frente al partido republicano")
    assert contada and slug == "midterms-2026", f"no detectó la historia repetida ({similitud})"


def test_un_tema_distinto_no_se_frena(monkeypatch, tmp_path, proyectos_vacios):
    _publicado(tmp_path, monkeypatch, slug="midterms-2026",
               script="las elecciones de medio término del congreso")
    assert not huellas.ya_contada("Cómo un pulpo reconoce su propio cuerpo en un acuario")[0]


def test_sin_registro_no_hay_nada_contado(monkeypatch, tmp_path):
    monkeypatch.setattr(huellas, "PUBLISHED", tmp_path / "ausente.jsonl")
    monkeypatch.setattr(config, "PROJECTS", tmp_path / "projects-sin")
    assert huellas.ya_contada("cualquier cosa") == (False, "", 0.0)


def test_una_idea_que_ya_tiene_carpeta_no_se_vuelve_a_elegir(monkeypatch, tmp_path):
    """La idea que murió 3 veces en el gate 1 seguía siendo la primera del ranking.

    Publicarla o no es irrelevante: si ya tuvo episodio, no es una historia nueva.
    """
    projects = tmp_path / "projects"
    (projects / "elecciones-de-medio-termino-2026").mkdir(parents=True)
    (projects / "elecciones-de-medio-termino-2026" / "episode.json").write_text(
        json.dumps({"title": "Elecciones de medio término 2026: quién controla el Congreso"}),
        encoding="utf-8")
    monkeypatch.setattr(huellas, "PUBLISHED", tmp_path / "ausente.jsonl")
    monkeypatch.setattr(config, "PROJECTS", projects)
    contada, slug, similitud = huellas.ya_contada(
        "Qué partido controla el Congreso tras las elecciones de medio término")
    assert contada and slug == "elecciones-de-medio-termino-2026", similitud


def test_una_carpeta_rota_no_tumba_el_anti_repeticion(monkeypatch, tmp_path):
    projects = tmp_path / "projects"
    (projects / "malo").mkdir(parents=True)
    (projects / "malo" / "episode.json").write_text("{no es json", encoding="utf-8")
    monkeypatch.setattr(config, "PROJECTS", projects)
    assert huellas.intentadas() == []


def test_las_filas_viejas_sin_huella_la_calculan_del_script(monkeypatch, tmp_path):
    archivo = tmp_path / "published.jsonl"
    archivo.write_text(json.dumps({"slug": "viejo",
                                   "script": "el apagón de 2003 dejó a cincuenta millones "
                                   "de personas sin luz en Canadá"}), encoding="utf-8")
    monkeypatch.setattr(huellas, "PUBLISHED", archivo)
    monkeypatch.setattr(config, "PROJECTS", tmp_path / "projects-sin")
    assert huellas.historias()[0]["huella"], "la fila legacy tenía que calcular su huella"
