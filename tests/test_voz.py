"""Regresión de la narración: lo que el oído escucha tiene que seguir siendo lo que se midió.

Cada test fija una cifra MEDIDA en vivo (2026-11-05). Si alguien cambia el rate, la pausa o la
tabla de prosodia sin recalcular, estos tests rompen antes de que el episodio salga con otra
duración de la prometida.
"""
from __future__ import annotations

import wave

import pytest

from factory import parametros
from pipeline.stages import narracion as N


# ---------------------------------------------------------------- pronunciación
def test_miles_se_leen_como_numero_no_como_punto():
    assert N._marcar_prosodia("ganó $3.000 en 12 meses") == "ganó $3000 en 12 meses"
    assert N._marcar_prosodia("1.250.000 personas") == "1250000 personas"


def test_porcentaje_sale_en_letra_y_coma_decimal_no_se_toca():
    assert N._marcar_prosodia("el 12,5% del total") == "el 12,5 por ciento del total"


def test_punto_y_como_se_vuelve_punto_y_el_motor_no_ve_punto_como():
    assert N._marcar_prosodia("dos cosas; ninguna funciona") == "dos cosas. ninguna funciona"


def test_el_marcado_no_reescribe_el_guion():
    """Normalizar notación no puede tocar el contenido: las palabras son el presupuesto.

    Lo único que el marcado agrega son las letras que el motor iba a decir igual ("por ciento").
    """
    original = "Madoff dijo: «$65.000 millones»; era el 40% del fondo."
    marcado = N._marcar_prosodia(original)
    con_letras = lambda t: [w for w in t.split() if any(c.isalpha() for c in w)]
    # "+0% → +por ciento" son 2 tokens; ningún otro puede aparecer.
    assert len(con_letras(marcado)) - len(con_letras(original)) == 2
    for palabra in ("Madoff", "millones", "fondo"):
        assert palabra in marcado
    assert "$65.000" not in marcado and "40%" not in marcado


def test_espacios_duplicados_no_son_pausa_real():
    """Medido: edge-tts ignora el espaciado. Nada del código puede volver a depender de eso."""
    assert N._marcar_prosodia("A.   B") == N._marcar_prosodia("A. B")


# ---------------------------------------------------------------- respiración
def test_la_pausa_de_pregunta_es_mas_larga_que_la_de_base():
    base = N._gap_de_bloque("un dato suelto", 0, False)
    pregunta = N._gap_de_bloque("¿y entonces quién avisó?", 0, False)
    assert pregunta > base > 0


def test_el_ultimo_bloque_no_pausa():
    assert N._gap_de_bloque("cierre", 5, True) == 0.0


def test_la_variacion_de_pausa_no_mueve_la_media():
    """El ciclo humaniza la cadencia pero deja intacto el 2,668 pal/s del presupuesto.

    Si la media se corre, target_words del template (1340-1600) deja de derivar de nada.
    """
    ciclo = parametros.variacion_pausa()
    assert len(ciclo) >= 2, "sin ciclo no hay variación que justificar"
    base = parametros.pausas_ms()["fin_de_bloque_ms"]
    gaps = [N._gap_de_bloque("bloque", i, False) for i in range(len(ciclo))]
    assert round(sum(gaps) / len(gaps) * 1000, 1) == float(base)


def test_la_pausa_de_bloque_no_es_todos_los_bloques_iguales():
    ciclo = [N._gap_de_bloque("x", i, False) for i in range(6)]
    assert len(set(ciclo)) > 1, "pausa idéntica en todos los bloques = cadencia de reloj"


# ---------------------------------------------------------------- prosodia por rol
def test_gancho_y_pregunta_bajan_el_rate_y_solo_el_pitch_se_diferencia():
    assert parametros.prosodia("gancho")["rate"] == "-6%"
    assert parametros.prosodia("base")["rate"] == "+0%"
    assert parametros.prosodia("pregunta")["pitch"] != parametros.prosodia("base")["pitch"]


def test_los_roles_de_bloque_reconocen_gancho_y_pregunta():
    assert N._rol_de_bloque("cualquier cosa", 0) == "gancho"
    assert N._rol_de_bloque("¿cuánto faltaba?", 3) == "pregunta"
    assert N._rol_de_bloque("un dato más", 3) == "base"


def test_piper_traduce_el_mismo_rate_a_length_scale():
    """El fallback Piper no tiene --rate: sin esta traducción el gancho se leía igual de rápido."""
    assert parametros.length_scale("base") == 1.0
    assert parametros.length_scale("gancho") == pytest.approx(1 / 0.94, abs=0.002)
    assert parametros.length_scale("pregunta") > 1.0


def test_la_voz_canonica_del_config_manda_en_el_codigo():
    """Cambiar la voz tiene que ser editar JSON, no Python. Si esto se rompe, el config es decorativo."""
    from pipeline import config
    assert config.VOZ_PREFERIDA == parametros.voz_canonica()
    assert config.VOZ_PREFERIDA in config.VOICE_ALLOWLIST


# ---------------------------------------------------------------- gate 8
def test_gate_ritmo_deja_pasar_lo_medido_en_vivo():
    """314 palabras / 117,7 s = el episodio real que calibró la voz."""
    assert N.gates.gate_ritmo(117.7, 314, parametros.palabras_por_segundo()) == []


def test_gate_ritmo_bloca_una_voz_mas_rapida_de_la_prometida():
    """Mismo guion, voz acelerada: la duración prometida de 8-10 min se cae a pedazos."""
    razones = N.gates.gate_ritmo(80.0, 314, parametros.palabras_por_segundo())
    assert razones and "palabras/s" in razones[0]


def test_gate_ritmo_sin_audio_no_finge_aprobado():
    assert N.gates.gate_ritmo(0.0, 300, 2.668)


# ---------------------------------------------------------------- el wav respira
def test_respirar_recorta_el_silencio_inicial_y_suelta_la_pausa(tmp_path):
    """Silencio de adelante = duda; silencio de atrás = información. Se corta lo primero."""
    wav = tmp_path / "seg.wav"
    with wave.open(str(wav), "w") as fh:
        fh.setnchannels(1)
        fh.setsampwidth(2)
        fh.setframerate(22050)
        fh.writeframes(b"\x00\x00" * 22050 * 2)          # 2 s de puro silencio
    N._respirar(wav, 0.65)
    with wave.open(str(wav), "rb") as fh:
        dur = fh.getnframes() / fh.getframerate()
    assert 0.5 < dur < 1.0, f"el silencio inicial no se recortó ({dur:.2f} s)"
    assert wav.with_suffix(".respira.wav").exists() is False
