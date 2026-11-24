"""
Pruebas unitarias del núcleo de cálculo (pytest).

Cada valor esperado se obtuvo por cálculo manual independiente, documentado en
el comentario de la prueba, para servir como "comparación independiente" en la
presentación (Enunciado §6).
"""

from datetime import date

import pytest

import calc_engine as ce

CLAVES_SALIDA = {"entradas", "ecuacion_texto", "referencia_normativa", "resultado",
                 "unidad", "observaciones"}


def _m(fecha, espesor, **kw):
    return {"fecha": fecha, "espesor": espesor, **kw}


# =============================================================================
# Estructura común de salida
# =============================================================================

@pytest.mark.parametrize("salida", [
    ce.espesor_requerido_tuberia(5.0, 168.3, 138.0, 1.0),
    ce.espesor_requerido_envolvente(1.5, 750.0, 138.0, 1.0),
    ce.espesor_virola_api650(30.0, 12.0, 0.85, 160.0, 171.0, 1.5),
    ce.vida_remanente(8.0, 5.0, 0.2),
    ce.intervalo_inspeccion_api510(30.0),
    ce.factor_dano_adelgazamiento(0.2, 0.3),
    ce.esfuerzo_admisible("SA-516-70", 100.0),
])
def test_estructura_salida(salida):
    assert CLAVES_SALIDA <= set(salida)
    assert isinstance(salida["observaciones"], list)
    assert isinstance(salida["alertas"], list)
    assert salida["referencia_normativa"]


# =============================================================================
# 1. Tuberías — ASME B31.3 / API 570
# =============================================================================

def test_b31_3_ecuacion_3a():
    # NPS 6 Sch 40: D = 168.3 mm; P = 5 MPa; S = 138 MPa; E = W = 1; Y = 0.4
    # t = 5·168.3 / [2·(138 + 5·0.4)] = 841.5 / 280 = 3.005357 mm
    r = ce.espesor_requerido_tuberia(5.0, 168.3, 138.0, 1.0, 1.0, 0.4)
    assert r["resultado"] == pytest.approx(3.005357, rel=1e-6)
    assert r["unidad"] == "mm"
    assert r["alertas"] == []


def test_b31_3_cuadro_de_espesores():
    # t_presion = 3.005357; CA = 1.5 → t_m = 4.505357
    # t_nom,req = 4.505357/0.875 = 5.148980 ; t_nom = 7.11 → t_fab_min = 6.22125
    # t_min = t_presion (t_estructural = 0) ; t_alerta = 3.005357 + 0.1·2 = 3.205357
    r = ce.evaluar_espesores_tuberia(5.0, 168.3, 138.0, 1.0, t_nom=7.11, CA=1.5,
                                     cr_gov=0.1, dt_margen_anios=2.0)
    res = r["resultado"]
    assert res["t_m"] == pytest.approx(4.505357, rel=1e-6)
    assert res["t_nom_requerido"] == pytest.approx(5.148980, rel=1e-6)
    assert res["t_fab_min"] == pytest.approx(6.22125, rel=1e-9)
    assert res["t_min"] == pytest.approx(3.005357, rel=1e-6)
    assert res["t_alerta"] == pytest.approx(3.205357, rel=1e-6)
    assert res["cumple_nominal"] is True


def test_b31_3_espesor_estructural_gobierna_y_nominal_insuficiente():
    r = ce.evaluar_espesores_tuberia(5.0, 168.3, 138.0, 1.0, t_nom=4.0, CA=1.5,
                                     t_estructural=3.5)
    assert r["resultado"]["t_min"] == 3.5
    assert ce.ALERTA_NOMINAL_INSUFICIENTE in r["alertas"]


def test_b31_3_mawp_inversa():
    t = ce.espesor_requerido_tuberia(5.0, 168.3, 138.0, 1.0)["resultado"]
    assert ce.presion_maxima_tuberia(t, 168.3, 138.0, 1.0)["resultado"] == pytest.approx(5.0)


def test_b31_3_fuera_de_alcance():
    r = ce.espesor_requerido_tuberia(60.0, 100.0, 138.0, 1.0)
    assert ce.ALERTA_FUERA_DE_ALCANCE in r["alertas"]


def test_coeficiente_y():
    assert ce.coeficiente_y_b31_3(200, "FERRITICO")["resultado"] == 0.4
    assert ce.coeficiente_y_b31_3(510, "FERRITICO")["resultado"] == pytest.approx(0.5)
    assert ce.coeficiente_y_b31_3(600, "FERRITICO")["resultado"] == 0.7


@pytest.mark.parametrize("kwargs", [
    dict(P=-1, D=168.3, S=138, E=1), dict(P=5, D=0, S=138, E=1),
    dict(P=5, D=168.3, S=138, E=1.2), dict(P=5, D=168.3, S=138, E=1, W=0),
])
def test_b31_3_entradas_invalidas(kwargs):
    with pytest.raises(ValueError):
        ce.espesor_requerido_tuberia(**kwargs)


def test_intervalo_api570():
    # Clase 2: máx. 10 años. RL = 12 → min(6, 10) = 6 ; RL = 30 → 10
    assert ce.intervalo_inspeccion_api570(12.0, 2)["resultado"]["intervalo_espesor"] == 6.0
    r = ce.intervalo_inspeccion_api570(30.0, 2)["resultado"]
    assert r["intervalo_espesor"] == 10.0 and r["intervalo_visual_externa"] == 5.0
    # Clase 1: máx. 5 años
    assert ce.intervalo_inspeccion_api570(30.0, 1)["resultado"]["intervalo_espesor"] == 5.0
    # Punto de inyección: 3 años
    assert ce.intervalo_inspeccion_api570(30.0, "PUNTO_INYECCION")["resultado"]["intervalo_espesor"] == 3.0
    # Bajo mínimo → 0
    assert ce.intervalo_inspeccion_api570(0.0, 2)["resultado"]["intervalo_espesor"] == 0.0


def test_intervalo_api570_tabla_configurable():
    tabla = {"X": {"espesor": 4.0, "visual_externa": 2.0}}
    r = ce.intervalo_inspeccion_api570(100.0, "X", intervalos_max=tabla)
    assert r["resultado"]["intervalo_espesor"] == 4.0


# =============================================================================
# 2. Recipientes — ASME VIII-1 / II-D / API 510
# =============================================================================

def test_ug27_circunferencial():
    # t = 1.5·750 / (138·1 − 0.6·1.5) = 1125 / 137.1 = 8.205689 mm
    r = ce.espesor_requerido_envolvente(1.5, 750.0, 138.0, 1.0)
    assert r["resultado"] == pytest.approx(8.205689, rel=1e-6)
    # MAWP inversa
    assert ce.presion_maxima_envolvente(r["resultado"], 750.0, 138.0, 1.0)["resultado"] == pytest.approx(1.5)


def test_ug27_cuadro_espesores_recipiente():
    # R_corr = 750 + 3 = 753 ; t_req = 1.5·753/(138·0.85 − 0.9) = 1129.5/116.4 = 9.703608
    # t_diseno = 12.703608 ; t_nom = 16 ; tolerancia 0.25 ≤ min(0.25, 0.96) → ignorada
    r = ce.evaluar_espesores_recipiente(1.5, 750.0, 138.0, 0.85, t_nom=16.0, CA=3.0,
                                        tolerancia_placa_mm=0.25, cr_gov=0.25)
    res = r["resultado"]
    assert res["t_req"] == pytest.approx(9.703608, rel=1e-6)
    assert res["t_diseno"] == pytest.approx(12.703608, rel=1e-6)
    assert res["t_fab_min"] == 16.0
    assert res["t_alerta"] == pytest.approx(9.703608 + 0.5, rel=1e-6)
    assert res["cumple_nominal"] is True


def test_ug16_minimo():
    r = ce.evaluar_espesores_recipiente(0.05, 100.0, 138.0, 1.0, t_nom=3.0, CA=0.0)
    assert r["resultado"]["t_req"] == ce.UG16_ESPESOR_MINIMO_MM


def test_esfuerzo_admisible_interpolado():
    # SA-516-70: 138 MPa a 260 °C y 134 MPa a 316 °C → a 288 °C: 138 − 4·28/56 = 136
    assert ce.esfuerzo_admisible("SA-516-70", 288.0)["resultado"] == pytest.approx(136.0)
    # SA-240-304L: 115 a 149 °C, 109 a 204 °C → a 176.5 °C: 112
    assert ce.esfuerzo_admisible("SA-240-304L", 176.5)["resultado"] == pytest.approx(112.0)
    with pytest.raises(ValueError):
        ce.esfuerzo_admisible("SA-516-70", 450.0)   # fuera de rango: no se extrapola
    with pytest.raises(ValueError):
        ce.esfuerzo_admisible("NO-EXISTE", 100.0)


@pytest.mark.parametrize("rl, esperado", [
    (30.0, 10.0),     # min(15, 10)
    (12.0, 6.0),      # min(6, 10)
    (4.0, 2.0),       # RL = 4 → regla general: 4/2
    (3.0, 0.75),      # RL < 4 conservadora: min(3/4, 2)
    (0.0, 0.0),       # bajo mínimo
])
def test_intervalo_api510_conservador(rl, esperado):
    r = ce.intervalo_inspeccion_api510(rl)
    assert r["resultado"]["intervalo_espesor"] == pytest.approx(esperado)


def test_intervalo_api510_textual():
    # API 510 §6.5.1.1: RL < 4 → vida remanente completa con máximo 2 años
    r = ce.intervalo_inspeccion_api510(3.0, regla_rl_menor_4=ce.REGLA_RL4_API_TEXTUAL)
    assert r["resultado"]["intervalo_espesor"] == 2.0
    r = ce.intervalo_inspeccion_api510(1.5, regla_rl_menor_4=ce.REGLA_RL4_API_TEXTUAL)
    assert r["resultado"]["intervalo_espesor"] == 1.5
    # Visual externa = min(5, interno)
    assert ce.intervalo_inspeccion_api510(30.0)["resultado"]["intervalo_visual_externa"] == 5.0


# =============================================================================
# 3. Tanques — API 650 / API 653
# =============================================================================

def test_api650_un_pie():
    # D = 30 m, H = 12 m, G = 0.85, Sd = 160, St = 171, E = 1, CA = 1.5
    # 4.9·30·11.7 = 1719.9
    # t_d = 1719.9·0.85/160 + 1.5 = 9.136969 + 1.5 = 10.636969 mm
    # t_t = 1719.9/171 = 10.057895 mm ; t_const (15 ≤ D < 36) = 6 mm
    r = ce.espesor_virola_api650(30.0, 12.0, 0.85, 160.0, 171.0, CA=1.5)
    res = r["resultado"]
    assert res["t_d"] == pytest.approx(10.636969, rel=1e-6)
    assert res["t_t"] == pytest.approx(10.057895, rel=1e-6)
    assert res["t_constructivo"] == 6.0
    assert res["t_requerido"] == pytest.approx(10.636969, rel=1e-6)
    assert any("virolas del manto" in o for o in r["observaciones"])


def test_api650_minimo_constructivo_y_alcance():
    assert ce.espesor_constructivo_minimo_api650(10)["resultado"] == 5.0
    assert ce.espesor_constructivo_minimo_api650(40)["resultado"] == 8.0
    assert ce.espesor_constructivo_minimo_api650(70)["resultado"] == 10.0
    r = ce.espesor_virola_api650(65.0, 15.0, 1.0, 160.0, 171.0)
    assert ce.ALERTA_FUERA_DE_ALCANCE in r["alertas"]


def test_api653_tmin_virola():
    # A36: Y = 250, T = 400. Virola 1: S = min(200, 171.6) = 171.6
    # t_min = 4.9·30·11.7·0.85/171.6 = 1461.915/171.6 = 8.519318 mm
    S = ce.esfuerzo_admisible_api653(250.0, 400.0, 1)["resultado"]
    assert S == pytest.approx(171.6)
    assert ce.esfuerzo_admisible_api653(250.0, 400.0, 3)["resultado"] == pytest.approx(188.8)
    r = ce.espesor_minimo_virola_api653(30.0, 12.0, 0.85, S)
    assert r["resultado"] == pytest.approx(8.519318, rel=1e-6)
    # mínimo absoluto 2.5 mm
    assert ce.espesor_minimo_virola_api653(5.0, 1.0, 0.8, 171.6)["resultado"] == 2.5


def test_virola_compuesta_con_datos_pendientes():
    r = ce.evaluar_espesores_virola(30.0, 12.0, 0.85, "A36M", t_nom=12.0, CA=1.5, cr_gov=0.1)
    assert r["resultado"]["t_min"] == pytest.approx(8.519318, rel=1e-6)
    assert r["resultado"]["t_alerta"] == pytest.approx(8.719318, rel=1e-6)
    assert len(r["detalle"]["datos_pendientes"]) >= 4


@pytest.mark.parametrize("t, tmin, cr, ut, vis", [
    (12.0, 8.0, 0.1, 15.0, 5.0),    # RCA = 4: RCA/2N = 20 → 15 ; RCA/4N = 10 → 5
    (12.0, 8.0, 0.5, 4.0, 2.0),     # RCA/2N = 4 ; RCA/4N = 2
    (12.0, 8.0, None, 5.0, 5.0),    # CR desconocida → 5 años
])
def test_intervalos_api653(t, tmin, cr, ut, vis):
    r = ce.intervalos_inspeccion_api653_manto(t, tmin, cr)["resultado"]
    assert r["intervalo_espesor"] == pytest.approx(ut)
    assert r["intervalo_visual_externa"] == pytest.approx(vis)


# =============================================================================
# 4. Corrosión, vida remanente y validación de datos
# =============================================================================

SERIE_BASE = [_m("2015-01-01", 10.0), _m("2020-01-01", 9.0), _m("2025-01-01", 7.5)]


def test_velocidades_lt_st_y_gobernante():
    # Δt LT = 3653 d / 365.25 = 10.001369 a ; CR_LT = 2.5/10.001369 = 0.249966 mm/a
    # Δt ST = 1827 d / 365.25 = 5.002053 a ;  CR_ST = 1.5/5.002053 = 0.299877 mm/a
    serie = ce.preparar_serie_espesores(SERIE_BASE, "2026-01-01")["resultado"]["serie"]
    r = ce.velocidades_corrosion(serie)["resultado"]
    assert r["cr_lt"] == pytest.approx(0.249966, rel=1e-5)
    assert r["cr_st"] == pytest.approx(0.299877, rel=1e-5)
    assert r["cr_gov"] == r["cr_st"]
    assert "CR_ST" in r["criterio"]


def test_vida_remanente():
    assert ce.vida_remanente(7.5, 5.0, 0.25)["resultado"] == pytest.approx(10.0)
    r = ce.vida_remanente(4.0, 5.0, 0.25)
    assert r["resultado"] == 0.0 and ce.ALERTA_BAJO_MINIMO in r["alertas"]
    assert ce.vida_remanente(7.5, 5.0, None)["resultado"] is None
    assert ce.vida_remanente(7.5, 5.0, -0.1)["resultado"] is None


def test_datos_insuficientes():
    r = ce.preparar_serie_espesores([_m("2024-01-01", 9.0)], "2026-01-01")
    assert ce.ALERTA_DATOS_INSUFICIENTES in r["alertas"]
    v = ce.velocidades_corrosion(r["resultado"]["serie"])
    assert v["resultado"]["cr_gov"] is None
    assert ce.ALERTA_DATOS_INSUFICIENTES in v["alertas"]


def test_mediciones_invalidas_excluidas():
    meds = [_m("2015-01-01", 10.0), _m("2020-01-01", 9.0, valida=False), _m("2025-01-01", 8.0)]
    r = ce.preparar_serie_espesores(meds, "2026-01-01")["resultado"]
    assert r["n_comparables"] == 2
    assert r["excluidas"][0]["motivo"] == "MARCADA_NO_VALIDA"


def test_fechas_inconsistentes_duplicada_y_futura():
    meds = [_m("2015-01-01", 10.0), _m("2025-01-01", 9.0), _m("2025-01-01", 8.9)]
    r = ce.preparar_serie_espesores(meds, "2026-01-01")
    assert ce.ALERTA_FECHAS_INCONSISTENTES in r["alertas"]
    v = ce.velocidades_corrosion(r["resultado"]["serie"])
    assert v["resultado"]["cr_st"] is None           # Δt = 0
    assert v["resultado"]["cr_lt"] is not None
    futura = ce.preparar_serie_espesores([_m("2015-01-01", 10.0), _m("2030-01-01", 9.0)], "2026-01-01")
    assert ce.ALERTA_FECHAS_INCONSISTENTES in futura["alertas"]
    assert futura["resultado"]["n_comparables"] == 1


def test_corrosion_nula_o_negativa():
    meds = [_m("2015-01-01", 10.0), _m("2020-01-01", 10.1)]
    serie = ce.preparar_serie_espesores(meds, "2026-01-01")["resultado"]["serie"]
    v = ce.velocidades_corrosion(serie)
    assert ce.ALERTA_CORROSION_NULA_O_NEGATIVA in v["alertas"]
    assert v["resultado"]["cr_para_calculo"] is None
    v2 = ce.velocidades_corrosion(serie, cr_minima=0.05)
    assert v2["resultado"]["cr_para_calculo"] == 0.05


def test_reemplazo_reinicia_linea_base():
    meds = [_m("2010-01-01", 10.0), _m("2015-01-01", 7.0),
            _m("2018-01-01", 10.2, evento="REEMPLAZO"), _m("2023-01-01", 9.7)]
    r = ce.preparar_serie_espesores(meds, "2026-01-01")
    assert ce.ALERTA_LINEA_BASE_REINICIADA in r["alertas"]
    serie = r["resultado"]["serie"]
    assert [s["espesor_mm"] for s in serie] == [10.2, 9.7]
    # CR = 0.5 / (1826/365.25) = 0.100014 (no la de 0.6 mm/a previa al reemplazo)
    assert ce.velocidades_corrosion(serie)["resultado"]["cr_gov"] == pytest.approx(0.100014, rel=1e-5)


def test_intervencion_registrada_reinicia_linea_base():
    meds = [_m("2010-01-01", 10.0), _m("2015-01-01", 9.0), _m("2020-01-01", 9.8), _m("2024-01-01", 9.4)]
    interv = [{"fecha": "2019-06-01", "tipo": "REPARACION"}]
    r = ce.preparar_serie_espesores(meds, "2026-01-01", interv)["resultado"]
    assert r["n_comparables"] == 2
    assert r["fecha_linea_base"] == date(2019, 6, 1)


def test_conversion_pulgadas():
    r = ce.preparar_serie_espesores([_m("2020-01-01", 0.5, unidad="in")], "2026-01-01")
    assert r["resultado"]["serie"][0]["espesor_mm"] == pytest.approx(12.7)


def test_espesor_alerta_equivale_a_rl_menor_margen():
    # Un punto con RL exactamente = Δt_margen está en t_alerta.
    t_min, cr, dt = 5.0, 0.25, 2.0
    t_alerta = ce.espesor_alerta(t_min, cr, dt)["resultado"]
    assert t_alerta == pytest.approx(5.5)
    assert ce.vida_remanente(t_alerta, t_min, cr)["resultado"] == pytest.approx(dt)


# =============================================================================
# 4.1 Clasificación de estado e integración por CML
# =============================================================================

def test_clasificar_estado_cuatro_condiciones():
    hoy = "2026-01-01"
    assert ce.clasificar_estado(9.0, 5.0, 5.5, "2028-01-01", hoy)["resultado"] == ce.ESTADO_NORMAL
    assert ce.clasificar_estado(5.4, 5.0, 5.5, "2028-01-01", hoy)["resultado"] == ce.ESTADO_ALERTA
    assert ce.clasificar_estado(4.9, 5.0, 5.5, "2028-01-01", hoy)["resultado"] == ce.ESTADO_BAJO_MINIMO
    assert ce.clasificar_estado(9.0, 5.0, 5.5, "2025-06-01", hoy)["resultado"] == ce.ESTADO_INSPECCION_VENCIDA
    # Bajo mínimo prevalece sobre vencida
    assert ce.clasificar_estado(4.9, 5.0, 5.5, "2025-06-01", hoy)["resultado"] == ce.ESTADO_BAJO_MINIMO


def test_evaluar_punto_recipiente_normal():
    # CR_gov = 0.299877 ; t_min = 5.0 ; RL = 2.5/0.299877 = 8.3368 → I = 4.1684 años
    r = ce.evaluar_punto_espesor("RECIPIENTE", SERIE_BASE, 5.0, "2026-01-01")
    res = r["resultado"]
    assert res["vida_remanente"] == pytest.approx(8.3368, rel=1e-4)
    assert res["intervalo"] == pytest.approx(4.1684, rel=1e-4)
    assert res["fecha_proxima"] == date(2029, 3, 3)    # 2025-01-01 + round(4.1684·365.25)=1523 d
    assert res["estado"] == ce.ESTADO_NORMAL
    assert res["t_alerta"] == pytest.approx(5.0 + 2 * 0.299877, rel=1e-5)


def test_evaluar_punto_tuberia_alerta():
    # t_min = 7.0: RL = 0.5/0.299877 = 1.667 años ≤ 2 → ALERTA ; I = RL/2 = 0.834
    r = ce.evaluar_punto_espesor("TUBERIA", SERIE_BASE, 7.0, "2025-03-01", clase_tuberia=2)
    assert r["resultado"]["estado"] == ce.ESTADO_ALERTA
    assert r["resultado"]["intervalo"] == pytest.approx(0.8337, rel=1e-3)


def test_evaluar_punto_bajo_minimo_y_vencida():
    r = ce.evaluar_punto_espesor("TUBERIA", SERIE_BASE, 8.0, "2026-01-01")
    assert r["resultado"]["estado"] == ce.ESTADO_BAJO_MINIMO
    assert r["resultado"]["intervalo"] == 0.0
    r2 = ce.evaluar_punto_espesor("RECIPIENTE", SERIE_BASE, 5.0, "2030-01-01")
    assert r2["resultado"]["estado"] == ce.ESTADO_INSPECCION_VENCIDA


def test_evaluar_punto_sin_datos_y_una_medicion():
    r0 = ce.evaluar_punto_espesor("TANQUE", [], 8.0, "2026-01-01")
    assert r0["resultado"]["estado"] == ce.ESTADO_INSPECCION_VENCIDA
    assert ce.ALERTA_DATOS_INSUFICIENTES in r0["alertas"]
    r1 = ce.evaluar_punto_espesor("TANQUE", [_m("2024-01-01", 11.0)], 8.0, "2026-01-01")
    assert r1["resultado"]["intervalo"] == 5.0               # API 653: CR desconocida
    assert r1["resultado"]["estado"] == ce.ESTADO_NORMAL
    assert ce.ALERTA_DATOS_INSUFICIENTES in r1["alertas"]


def test_evaluar_punto_tanque_cr_nula_usa_maximos():
    meds = [_m("2015-01-01", 12.0), _m("2020-01-01", 12.05)]
    r = ce.evaluar_punto_espesor("TANQUE", meds, 8.0, "2021-01-01")
    assert r["resultado"]["intervalo"] == 15.0
    assert ce.ALERTA_CORROSION_NULA_O_NEGATIVA in r["alertas"]


# =============================================================================
# 5. RBI — adelgazamiento generalizado (API RP 580 / 581)
# =============================================================================

def test_art():
    # A_rt = 0.25·12/16 = 0.1875
    assert ce.parametro_art(0.25, 12.0, 16.0)["resultado"] == pytest.approx(0.1875)
    assert ce.parametro_art(-0.1, 12.0, 16.0)["resultado"] == 0.0


def test_relacion_resistencia():
    # FS = 1.1·0.85·(260+485)/2 = 348.2875
    # SR = (117.3/348.2875)·(9.7/16) = 0.3367907·0.60625 = 0.204179
    r = ce.relacion_resistencia(138.0, 0.85, 260.0, 485.0, 9.7, 16.0)
    assert r["detalle"]["FS_MPa"] == pytest.approx(348.2875)
    assert r["resultado"] == pytest.approx(0.204179, rel=1e-5)


def test_posteriores_sin_inspeccion_igual_previas():
    assert ce.probabilidades_posteriores({}, "BAJA")["resultado"] == pytest.approx((0.5, 0.3, 0.2))


def test_posteriores_bayes_manual():
    # 2 inspecciones A, confianza BAJA:
    # no normalizado = 0.5·0.81, 0.3·0.0081, 0.2·0.0001 = 0.405, 0.00243, 0.00002
    post = ce.probabilidades_posteriores({"A": 2}, "BAJA")["resultado"]
    total = 0.405 + 0.00243 + 0.00002
    assert post == pytest.approx((0.405 / total, 0.00243 / total, 0.00002 / total))


def test_df_caso_manual():
    # A_rt = 0.3, SR = 0.23, sin inspección, confianza BAJA
    # β1 = 0.47/√(0.0036+0.0196+0.00013225) = 3.07700 → Φ(−β1) = 1.0453E−3
    # β2 = 0.17/√(0.0144+0.0064+0.00013225) = 1.17501 → Φ(−β2) = 0.12000
    # β3 = −0.43/√(0.0576+0.0016+0.00013225) = −1.76533 → Φ(−β3) = 0.96125
    # D_f = (0.5·1.0453E−3 + 0.3·0.12000 + 0.2·0.96125)/1.56E−4 ≈ 1466
    r = ce.factor_dano_adelgazamiento(0.3, 0.23, {}, "BAJA")
    b1, b2, b3 = r["detalle"]["betas"]
    assert b1 == pytest.approx(3.07700, rel=1e-4)
    assert b2 == pytest.approx(1.17501, rel=1e-4)
    assert b3 == pytest.approx(-1.76533, rel=1e-4)
    assert r["resultado"] == pytest.approx(1466, rel=5e-3)


def test_df_monotono_y_efecto_inspeccion():
    sr = 0.25
    dfs = [ce.factor_dano_adelgazamiento(a, sr)["resultado"] for a in (0.0, 0.1, 0.2, 0.3, 0.4)]
    assert dfs == sorted(dfs)
    sin = ce.factor_dano_adelgazamiento(0.3, sr)["resultado"]
    con_c = ce.factor_dano_adelgazamiento(0.3, sr, {"C": 1})["resultado"]
    con_a = ce.factor_dano_adelgazamiento(0.3, sr, {"A": 1})["resultado"]
    assert sin > con_c > con_a
    assert ce.factor_dano_adelgazamiento(0.0, 0.01)["resultado"] >= ce.DF_MINIMO_581


def test_fms_y_frecuencia():
    assert ce.factor_sistema_gestion(500)["resultado"] == pytest.approx(1.0)
    assert ce.factor_sistema_gestion(1000)["resultado"] == pytest.approx(0.1)
    assert ce.frecuencia_falla(3.06e-5, 100.0, 1.0)["resultado"] == pytest.approx(3.06e-3)


@pytest.mark.parametrize("ff, cat", [(1e-5, 1), (3.06e-5, 1), (1e-4, 2), (1e-3, 3), (1e-2, 4), (0.1, 5)])
def test_categoria_probabilidad(ff, cat):
    assert ce.categoria_probabilidad(ff)["resultado"] == cat


def test_categorias_consecuencia():
    assert ce.categoria_consecuencia_area(5.0)["resultado"] == "A"
    assert ce.categoria_consecuencia_area(500.0)["resultado"] == "C"
    assert ce.categoria_consecuencia_area(1e5)["resultado"] == "E"
    assert ce.categoria_consecuencia_economica(5e5)["resultado"] == "C"
    # CLP con tasa declarada: 500 000 000 CLP · 0.00105 = 525 000 USD → C
    assert ce.categoria_consecuencia_economica(5e8, "CLP", 0.00105)["resultado"] == "C"
    with pytest.raises(ValueError):
        ce.categoria_consecuencia_economica(5e8, "CLP")


def test_matriz_riesgo():
    assert ce.nivel_riesgo_matriz(5, "E")["resultado"]["nivel"] == "ALTO"
    assert ce.nivel_riesgo_matriz(1, "A")["resultado"]["prioridad"] == 4


def test_rbi_completo_riesgos_separados():
    r = ce.evaluar_rbi_adelgazamiento(
        cr_gov=0.30, edad_anios=15.0, t_ref=16.0, t_min=9.7, S=138.0, E=0.85, YS=260.0, TS=485.0,
        tipo_componente="RECIPIENTE", inspecciones={"C": 1}, confianza="MEDIA",
        CA_m2=250.0, CE=2.0e6, moneda="USD", base_valoracion="Reparación + lucro cesante 2026",
        horizonte_plan_anios=4.0)
    res = r["resultado"]
    assert res["A_rt"] == pytest.approx(0.30 * 15 / 16)
    assert res["f_F"] == pytest.approx(3.06e-5 * res["D_f"] * 1.0)
    assert res["R_A"] == pytest.approx(res["f_F"] * 250.0)
    assert res["R_E"] == pytest.approx(res["f_F"] * 2.0e6)
    assert res["cat_consecuencia_area"] == "C" and res["cat_consecuencia_economica"] == "D"
    assert res["cat_consecuencia_global"] == "D"
    assert r["unidad"]["R_A"] == "m²/año" and r["unidad"]["R_E"] == "USD/año"
    # La inspección adicional baja D_f pero NO cambia A_rt (no recupera espesor)
    ef = res["efecto_inspeccion_adicional"]
    assert ef["A_rt_sin_cambio"] == res["A_rt"]
    assert ef["D_f_con_inspeccion"] < res["D_f"]
    assert any("no recupera" in o.lower() for o in r["observaciones"])
    # Proyección sin inspección: D_f aumenta con la edad
    assert res["proyeccion"]["D_f"] > res["D_f"]


def test_rbi_cambio_consecuencia_cambia_riesgo():
    base = dict(cr_gov=0.30, edad_anios=15.0, t_ref=16.0, t_min=9.7, S=138.0, E=0.85,
                YS=260.0, TS=485.0, CE=5.0e3)
    r1 = ce.evaluar_rbi_adelgazamiento(CA_m2=5.0, **base)["resultado"]
    r2 = ce.evaluar_rbi_adelgazamiento(CA_m2=20000.0, **base)["resultado"]
    assert r2["R_A"] == pytest.approx(r1["R_A"] * 4000.0)
    assert ce._ORDEN_RIESGO.index(r2["nivel_riesgo"]) > ce._ORDEN_RIESGO.index(r1["nivel_riesgo"])
