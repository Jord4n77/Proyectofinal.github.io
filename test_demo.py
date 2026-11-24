"""
Pruebas del caso demostrativo y ensayo de la demostración en vivo (Enunciado §8).

Además de verificar que el archivo de proyecto se carga y produce las condiciones
previstas, reproduce las acciones que se harán frente al profesor:
  3. agregar una medición y actualizar CR, RL, condición y próxima fecha;
  4. cambiar una variable de diseño y ver su efecto en el espesor calculado;
  5. modificar una consecuencia y ver el cambio en el riesgo / clasificación;
  6. guardar y recuperar el caso.
"""

import base64
import copy
import importlib.util
import os
from datetime import date

import pytest

import calc_engine as ce
import demo_data
import servicios
from models import Medicion, Proyecto

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUTA_DEMO = os.path.join(RAIZ, "data", "proyecto_demo.json")
HOY = demo_data.FECHA_EVALUACION_DEMO


@pytest.fixture(scope="module")
def proyecto():
    with open(RUTA_DEMO, encoding="utf-8") as f:
        return Proyecto.desde_json(f.read())


def _validacion():
    spec = importlib.util.spec_from_file_location(
        "validacion_independiente", os.path.join(RAIZ, "tools", "validacion_independiente.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ----------------------------------------------------------------- contenido
def test_archivo_coincide_con_generador(proyecto):
    """El JSON publicado está sincronizado con demo_data.py."""
    assert proyecto.a_dict() == demo_data.construir_proyecto_demo(incluir_adjuntos=True).a_dict()


def test_alcance_minimo_del_enunciado(proyecto):
    assert proyecto.validar_integridad() == []
    equipos = [e for *_, e in proyecto.iter_equipos()]
    assert {e.familia.value for e in equipos} == set(ce.FAMILIAS)
    for e in equipos:
        cmls = [c for _, c in e.iter_cmls()]
        assert len(cmls) >= 3                                       # ≥ 3 ubicaciones por familia
        fechas = {m.fecha for c in cmls for m in c.mediciones if m.fecha <= HOY}
        assert len(fechas) >= 3                                     # ≥ 3 campañas históricas
        assert e.documentos and e.documentos[0].admite_marcadores  # un esquema por familia
        assert e.rbi is not None
    assert equipos[0].circuito_inspeccion                           # tubería con circuito


def test_adjuntos_incluidos_y_restablecibles(proyecto):
    for *_, e in proyecto.iter_equipos():
        doc = e.documentos[0]
        datos = base64.b64decode(doc.contenido_base64)
        assert datos[:8] == b"\x89PNG\r\n\x1a\n"
        with open(os.path.join(RAIZ, doc.ruta), "rb") as f:          # ruta para restablecerlo
            assert f.read() == datos


def test_validacion_independiente_completa():
    filas, estados = _validacion().comparar()
    assert all(r["ok"] for r in filas), [r for r in filas if not r["ok"]]
    assert all(e["ok"] for e in estados), [e for e in estados if not e["ok"]]


def test_panel_cubre_todas_las_condiciones(proyecto):
    filas = servicios.evaluar_proyecto(proyecto, HOY)["filas"]
    assert {f["estado"] for f in filas} == set(ce.ESTADOS)
    alertas = {a for f in filas for a in f["alertas"]}
    for codigo in (ce.ALERTA_DATOS_INSUFICIENTES, ce.ALERTA_FECHAS_INCONSISTENTES,
                   ce.ALERTA_CORROSION_NULA_O_NEGATIVA, ce.ALERTA_LINEA_BASE_REINICIADA):
        assert codigo in alertas


def test_estado_peor_por_equipo(proyecto):
    ev = servicios.evaluar_proyecto(proyecto, HOY)["equipos"]
    assert ev["L-1001"]["estado"] == ce.ESTADO_ALERTA
    assert ev["V-2001"]["estado"] == ce.ESTADO_BAJO_MINIMO
    assert ev["T-3001"]["estado"] == ce.ESTADO_ALERTA


def test_tanque_declara_alcance_y_pendientes(proyecto):
    eq = proyecto.buscar_equipo("T-3001")
    r = servicios.espesores_componente(eq, eq.componentes[0])
    assert any("virolas del manto" in o for o in r["observaciones"])
    assert len(r["detalle"]["datos_pendientes"]) >= 4


def test_rbi_tres_equipos(proyecto):
    rbi = servicios.evaluar_proyecto(proyecto, HOY)["rbi"]
    assert rbi["L-1001"]["resultado"]["nivel_riesgo"] == "BAJO"
    assert rbi["L-1001"]["detalle"]["referencia"]["cml_id"] == "L-1001-CML-01"
    assert rbi["V-2001"]["resultado"]["nivel_riesgo"] == "ALTO"
    assert rbi["V-2001"]["detalle"]["referencia"]["cml_id"] == "V-2001-CML-02"   # mayor CR
    assert rbi["V-2001"]["unidad"]["R_E"] == "CLP/año"


# ---------------------------------------------------- ensayo de demostración
def test_demo_agregar_medicion_actualiza_evaluacion(proyecto):
    p = copy.deepcopy(proyecto)
    eq, comp, cml = p.buscar_cml("L-1001-CML-04")
    antes = servicios.evaluar_cml(eq, comp, cml, HOY)
    assert ce.ALERTA_DATOS_INSUFICIENTES in antes["alertas"]
    cml.agregar_medicion(Medicion("L-1001-CML-04-M2", date(2026, 11, 20), 6.70))
    despues = servicios.evaluar_cml(eq, comp, cml, HOY)
    assert ce.ALERTA_DATOS_INSUFICIENTES not in despues["alertas"]
    assert despues["resultado"]["cr_gov"] == pytest.approx(0.28 / (157 / 365.25), rel=1e-9)
    assert despues["resultado"]["vida_remanente"] is not None
    assert despues["resultado"]["fecha_proxima"] != antes["resultado"]["fecha_proxima"]


def test_demo_cambiar_variable_de_diseno(proyecto):
    p = copy.deepcopy(proyecto)
    eq = p.buscar_equipo("V-2001")
    t0 = servicios.espesores_componente(eq, eq.componentes[0])["resultado"]["t_req"]
    eq.diseno.presion_MPa = 1.8
    t1 = servicios.espesores_componente(eq, eq.componentes[0])["resultado"]["t_req"]
    # 1.8·753/(117.3 − 1.08) = 11.6623 mm
    assert t1 == pytest.approx(1.8 * 753 / (138 * 0.85 - 0.6 * 1.8))
    assert t1 > t0
    # Subir la temperatura de diseño reduce S(T) y aumenta t
    eq.diseno.temperatura_C = 343.0
    t2 = servicios.espesores_componente(eq, eq.componentes[0])["resultado"]["t_req"]
    assert t2 == pytest.approx(1.8 * 753 / (130 * 0.85 - 0.6 * 1.8))


def test_demo_modificar_consecuencia_cambia_riesgo(proyecto):
    p = copy.deepcopy(proyecto)
    eq = p.buscar_equipo("L-1001")
    r0 = servicios.evaluar_rbi_equipo(eq, HOY)["resultado"]
    eq.rbi.area_consecuencia_m2 = 12000.0                   # C → E
    r1 = servicios.evaluar_rbi_equipo(eq, HOY)["resultado"]
    assert r1["f_F"] == pytest.approx(r0["f_F"])            # la frecuencia no cambia
    assert r1["R_A"] == pytest.approx(r0["R_A"] * 80.0)     # el riesgo de área escala con C_A
    assert r1["R_E"] == pytest.approx(r0["R_E"])            # el riesgo económico no cambia
    assert (r0["nivel_riesgo"], r1["nivel_riesgo"]) == ("BAJO", "MEDIO_ALTO")


def test_demo_guardar_y_recuperar(proyecto, tmp_path):
    p = copy.deepcopy(proyecto)
    _, _, cml = p.buscar_cml("T-3001-CML-02")
    cml.agregar_medicion(Medicion("T-3001-CML-02-M4", date(2026, 11, 22), 8.95))
    ruta = tmp_path / "respaldo.json"
    ruta.write_text(p.a_json(), encoding="utf-8")
    p2 = Proyecto.desde_json(ruta.read_text(encoding="utf-8"))
    assert p2.a_dict() == p.a_dict()
    assert len(p2.buscar_cml("T-3001-CML-02")[2].mediciones) == 4
