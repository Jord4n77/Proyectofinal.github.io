"""Pruebas del controlador de la interfaz (sin navegador)."""

import base64
import json
import os
import re
from datetime import date

import pytest

import calc_engine as ce
import servicios
from controlador import Controlador

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
with open(os.path.join(RAIZ, "data", "proyecto_demo.json"), encoding="utf-8") as _f:
    DEMO = _f.read()
HOY = date(2026, 11, 23)
ACCIONES_NAVEGADOR = {"guardar_local", "exportar", "importar"}   # resueltas en web/main.py
PNG_1PX = base64.b64encode(bytes.fromhex(
    "89504e470d0a1a0a0000000d4948445200000001000000010806000000"
    "1f15c4890000000d49444154789c6360000002000154a24f5d0000000049454e44ae426082")).decode()


@pytest.fixture
def c():
    return Controlador(DEMO, hoy=HOY)


def _ok(c):
    assert not [m for m in c.mensajes if m[0] == "error"], c.mensajes


def _error(c, texto=""):
    errores = [m for t, m in c.mensajes if t == "error"]
    assert errores, c.mensajes
    assert texto in errores[0]


def datos_equipo(eq):
    p = eq.parametros
    d = {"tag": eq.tag, "descripcion": eq.descripcion, "servicio": eq.servicio, "fluido": eq.fluido,
         "material_id": eq.material_id, "fecha_puesta_servicio": eq.fecha_puesta_servicio.isoformat(),
         "P_dis": str(eq.diseno.presion_MPa), "T_dis": str(eq.diseno.temperatura_C),
         "P_op": str(eq.operacion.presion_MPa), "T_op": str(eq.operacion.temperatura_C),
         "CA": str(p.sobreespesor_corrosion_mm), "E": str(p.eficiencia_junta), "dt_margen_anios": str(p.dt_margen_anios),
         "factor_W": str(p.factor_W), "coeficiente_Y": str(p.coeficiente_Y),
         "tolerancia_pct": str(p.tolerancia_fabricacion * 100), "t_estructural_mm": str(p.t_estructural_mm),
         "clase_tuberia": str(p.clase_tuberia), "circuito_inspeccion": eq.circuito_inspeccion or "",
         "tolerancia_placa_mm": str(p.tolerancia_placa_mm), "regla_rl_menor_4": p.regla_rl_menor_4 or "",
         "diametro_tanque_m": str(p.diametro_tanque_m or ""), "altura_liquido_diseno_m": str(p.altura_liquido_diseno_m or ""),
         "densidad_relativa_G": str(p.densidad_relativa_G or ""), "eficiencia_junta_servicio": str(p.eficiencia_junta_servicio)}
    return d


# ------------------------------------------------------------------ renderizado
ESCENAS = [
    [("ver_panel", {})],
    [("ver_equipo", {"tag": "L-1001"})],
    [("ver_equipo", {"tag": "V-2001"}), ("pestana", {"valor": "espesores"})],
    [("ver_equipo", {"tag": "T-3001"}), ("pestana", {"valor": "espesores"})],
    [("ver_cml", {"cml": "L-1001-CML-03"})],
    [("ver_cml", {"cml": "T-3001-CML-03"})],
    [("ver_cml", {"cml": "V-2001-CML-02"}), ("iniciar_ubicacion", {"cml": "V-2001-CML-02"})],
    [("ver_rbi", {"tag": "V-2001"})],
    [("ver_verificacion", {})], [("ver_normas", {})], [("nuevo_equipo", {})],
]


@pytest.mark.parametrize("acciones", ESCENAS)
def test_todas_las_vistas_renderizan(c, acciones):
    for a, d in acciones:
        c.despachar(a, d)
        _ok(c)
    r = c.renderizar()
    assert set(r) == set(Controlador.REGIONES)
    assert "Error al mostrar" not in r["principal"]


def test_toda_accion_del_html_tiene_manejador(c):
    """Cada data-accion / data-form generado corresponde a un método o a una acción del navegador."""
    encontradas = set()
    for acciones in ESCENAS:
        cc = Controlador(DEMO, hoy=HOY)
        for a, d in acciones:
            cc.despachar(a, d)
        html = "".join(cc.renderizar().values())
        encontradas |= set(re.findall(r'data-(?:accion|form)="([a-z_]+)"', html))
    assert len(encontradas) > 25
    faltantes = {a for a in encontradas if a not in ACCIONES_NAVEGADOR and not hasattr(c, f"_a_{a}")}
    assert not faltantes, faltantes


def test_verificacion_en_la_interfaz(c):
    filas, estados, error = c.verificacion()
    assert error is None
    assert all(r["ok"] for r in filas) and all(e["ok"] for e in estados)
    c.despachar("ver_verificacion")
    assert "33/33" in c.renderizar()["principal"]


def test_filtros(c):
    c.despachar("filtros", {"familia": "TANQUE", "area": "", "estado": ""})
    r = c.renderizar()
    assert "T-3001" in r["lateral"] and "L-1001" not in r["lateral"]
    c.despachar("filtros", {"familia": "", "area": "", "estado": "BAJO_MINIMO"})
    assert "V-2001-CML-02" in c.renderizar()["principal"] and "L-1001-CML-01" not in c.renderizar()["principal"]


def test_accion_desconocida_y_pestana_invalida(c):
    c.despachar("no_existe")
    _error(c, "desconocida")
    c.despachar("pestana", {"valor": "xx"})
    _error(c)


# ------------------------------------------------------------------ mediciones
def test_agregar_medicion_con_coma_decimal(c):
    c.despachar("agregar_medicion", {"cml": "L-1001-CML-04", "fecha": "2026-11-20", "espesor": "6,70",
                                     "unidad": "mm", "tecnica": "UT", "evento": "NORMAL", "valida": "1"})
    _ok(c)
    assert "CR_gov = 0.651" in c.mensajes[0][1]
    assert c.sucio and c.cml_id == "L-1001-CML-04" and c.pestana == "esquema"
    fila = next(f for f in c.evaluacion()["filas"] if f["cml_id"] == "L-1001-CML-04")
    assert ce.ALERTA_DATOS_INSUFICIENTES not in fila["alertas"]


@pytest.mark.parametrize("espesor", ["abc", "", "-1", "0"])
def test_medicion_invalida_no_modifica(c, espesor):
    antes = len(c.proyecto.buscar_cml("L-1001-CML-04")[2].mediciones)
    c.despachar("agregar_medicion", {"cml": "L-1001-CML-04", "fecha": "2026-11-20", "espesor": espesor, "valida": "1"})
    _error(c)
    assert len(c.proyecto.buscar_cml("L-1001-CML-04")[2].mediciones) == antes


def test_validez_eliminar_e_intervencion(c):
    c.despachar("alternar_validez", {"cml": "L-1001-CML-02", "med": "L-1001-CML-02-M3"})
    _ok(c)
    fila = next(f for f in c.evaluacion()["filas"] if f["cml_id"] == "L-1001-CML-02")
    # Sin la lectura de 2026 la última válida es la de 2022 (5.10 mm): RL ≈ 6.4 años, intervalo
    # ≈ 3.2 años → la inspección venció en 2025.
    assert fila["estado"] == ce.ESTADO_INSPECCION_VENCIDA
    c.despachar("eliminar_medicion", {"cml": "L-1001-CML-02", "med": "L-1001-CML-02-M3"})
    assert len(c.proyecto.buscar_cml("L-1001-CML-02")[2].mediciones) == 2
    c.despachar("agregar_intervencion", {"cml": "L-1001-CML-01", "fecha": "2023-01-10", "tipo": "REPARACION"})
    _ok(c)
    fila = next(f for f in c.evaluacion()["filas"] if f["cml_id"] == "L-1001-CML-01")
    assert ce.ALERTA_LINEA_BASE_REINICIADA in fila["alertas"]


# ------------------------------------------------------------------ equipo y componentes
def test_editar_equipo_cambia_espesor(c):
    eq = c.proyecto.buscar_equipo("V-2001")
    d = datos_equipo(eq)
    d["P_dis"] = "1,8"
    c.despachar("editar_equipo", d)
    _ok(c)
    assert "t requerido = 11.662" in c.mensajes[0][1]
    assert eq.diseno.presion_MPa == 1.8


def test_editar_equipo_material_ajeno_y_valor_fuera_de_rango(c):
    eq = c.proyecto.buscar_equipo("L-1001")
    d = datos_equipo(eq)
    d["material_id"] = "SA-516-70"
    c.despachar("editar_equipo", d)
    _error(c, "no pertenece")
    d = datos_equipo(eq)
    d["E"] = "1.3"
    c.despachar("editar_equipo", d)
    _error(c, "≤ 1")
    d = datos_equipo(eq)
    d["T_dis"] = "500"                                            # fuera de la tabla S(T): no se aplica
    c.despachar("editar_equipo", d)
    _error(c, "no son válidos")
    assert eq.diseno.temperatura_C == 150.0


def test_editar_y_agregar_componente(c):
    c.despachar("editar_componente", {"tag": "T-3001", "comp": "T-3001-V1", "nombre": "Virola 1", "t_nom_mm": "12",
                                      "numero_virola": "1", "nivel_sobre_fondo_virola_m": "11", "altura_virola_m": "2",
                                      "t_min_mm_override": ""})
    _ok(c)
    c.despachar("agregar_componente", {"tag": "T-3001", "id": "T-3001-V4", "nombre": "Virola 4", "t_nom_mm": "8",
                                       "numero_virola": "4", "nivel_sobre_fondo_virola_m": "6", "altura_virola_m": "2"})
    _ok(c)
    assert len(c.proyecto.buscar_equipo("T-3001").componentes) == 4
    c.despachar("agregar_componente", {"tag": "T-3001", "id": "T-3001-V4", "nombre": "x", "t_nom_mm": "8",
                                       "numero_virola": "4", "nivel_sobre_fondo_virola_m": "6"})
    _error(c, "Ya existe")


@pytest.mark.parametrize("datos", [
    {"familia": "TUBERIA", "material": "TUBERIA:A106-B", "P_dis": "2", "diametro_exterior_mm": "114.3", "t_nom_mm": "6.02"},
    {"familia": "RECIPIENTE", "material": "RECIPIENTE:SA-240-304L", "P_dis": "0.8", "radio_interior_mm": "500",
     "t_nom_mm": "8"},
    {"familia": "TANQUE", "material": "TANQUE:A516M-485", "P_dis": "", "diametro_tanque_m": "12",
     "densidad_relativa_G": "1.0", "nivel_sobre_fondo_virola_m": "9", "t_nom_mm": "8"},
])
def test_crear_equipo_por_familia(c, datos):
    base = {"planta": "Planta Demo Viña del Mar (ficticia)", "area": "Área nueva", "sistema": "Sistema nuevo",
            "tag": "x-900", "descripcion": "Equipo de prueba", "T_dis": "60", "CA": "1.0", "E": "1"}
    c.despachar("crear_equipo", {**base, **datos})
    _ok(c)
    eq = c.proyecto.buscar_equipo("X-900")
    assert eq is not None and c.tag == "X-900"
    assert c.proyecto.ubicacion_tecnica("X-900").endswith("Área nueva / Sistema nuevo / X-900")
    servicios.espesores_componente(eq, eq.componentes[0])
    c.renderizar()


def test_crear_equipo_errores(c):
    base = {"planta": "P", "area": "A", "sistema": "S", "tag": "L-1001", "descripcion": "d", "familia": "TUBERIA",
            "material": "TUBERIA:A106-B", "P_dis": "2", "T_dis": "60", "CA": "1", "E": "1",
            "diametro_exterior_mm": "114.3", "t_nom_mm": "6"}
    c.despachar("crear_equipo", base)
    _error(c, "Ya existe")
    c.despachar("crear_equipo", {**base, "tag": "N-1", "material": "TANQUE:A36M"})
    _error(c, "material")
    n = sum(1 for _ in c.proyecto.iter_equipos())
    assert n == 3


# ------------------------------------------------------------------ CML, marcadores y esquema
def test_cml_marcador_y_esquema(c):
    c.despachar("agregar_cml", {"tag": "V-2001", "componente_id": "V-2001-ENV", "id": "V-2001-CML-05",
                                "descripcion_ubicacion": "Nuevo", "marcador_x": "", "marcador_y": ""})
    _ok(c)
    c.despachar("iniciar_ubicacion", {"cml": "V-2001-CML-05"})
    assert c.ubicando
    assert 'data-accion="ubicar_marcador"' in c.renderizar()["principal"]
    c.despachar("ubicar_marcador", {"cml": "V-2001-CML-05", "x": "0.25", "y": "1.4"})
    _ok(c)
    cml = c.proyecto.buscar_cml("V-2001-CML-05")[2]
    assert (cml.marcador_x, cml.marcador_y) == (0.25, 1.0) and not c.ubicando
    c.despachar("editar_cml", {"cml": "V-2001-CML-05", "marcador_x": "2"})
    _error(c, "≤ 1")
    c.despachar("subir_esquema", {"tag": "V-2001", "archivo_base64": PNG_1PX, "archivo_tipo": "image/png",
                                  "archivo_nombre": "nuevo.png", "nombre": "Esquema nuevo"})
    _ok(c)
    doc = c.proyecto.buscar_equipo("V-2001").documentos[0]
    assert doc.nombre == "Esquema nuevo" and doc.contenido_base64 == PNG_1PX
    c.despachar("subir_esquema", {"tag": "V-2001", "archivo_base64": PNG_1PX, "archivo_tipo": "application/pdf"})
    _error(c, "PNG o JPG")


# ------------------------------------------------------------------ RBI
def test_rbi_consecuencia_y_validaciones(c):
    eq = c.proyecto.buscar_equipo("L-1001")
    r0 = servicios.evaluar_rbi_equipo(eq, HOY)["resultado"]
    base = {"tag": "L-1001", "cml_referencia_id": "L-1001-CML-01", "tipo_componente_gff": "TUBERIA",
            "confianza_cr": "MEDIA", "insp_A": "0", "insp_B": "0", "insp_C": "3", "insp_D": "0",
            "puntaje_sistema_gestion": "600", "factor_ajuste": "1", "area_consecuencia_m2": "12000",
            "consecuencia_economica": "800000", "moneda": "USD", "efectividad_propuesta": "B",
            "horizonte_plan_anios": "4"}
    c.despachar("editar_rbi", base)
    _ok(c)
    assert "Medio-alto" in c.mensajes[0][1]
    r1 = c.evaluacion()["rbi"]["L-1001"]["resultado"]
    assert r1["R_A"] == pytest.approx(r0["R_A"] * 80)
    c.despachar("editar_rbi", {**base, "moneda": "CLP", "tasa_a_usd": ""})
    _error(c, "tasa")


def test_activar_rbi_en_equipo_nuevo(c):
    c.despachar("crear_equipo", {"planta": "P2", "area": "A2", "sistema": "S2", "tag": "R-1", "descripcion": "d",
                                 "familia": "RECIPIENTE", "material": "RECIPIENTE:SA-516-70", "P_dis": "1",
                                 "T_dis": "100", "CA": "1", "E": "1", "radio_interior_mm": "400", "t_nom_mm": "10",
                                 "fecha_puesta_servicio": "2015-01-01"})
    c.despachar("activar_rbi", {"tag": "R-1"})
    _ok(c)
    ev = c.evaluacion()
    assert "R-1 (RBI)" in ev["errores"]           # sin CML con CR: error informado, la app sigue
    c.despachar("ver_rbi", {"tag": "R-1"})
    assert "ningún CML" in c.renderizar()["principal"]


# ------------------------------------------------------------------ archivo y fecha
def test_exportar_importar_y_restablecer(c):
    c.despachar("agregar_medicion", {"cml": "T-3001-CML-02", "fecha": "2026-11-22", "espesor": "8.95", "valida": "1"})
    texto = c.exportar_json()
    otro = Controlador(DEMO, hoy=HOY)
    assert otro.importar_json(texto, "archivo")
    assert len(otro.proyecto.buscar_cml("T-3001-CML-02")[2].mediciones) == 4
    assert not otro.importar_json("{no es json", "archivo")
    assert len(otro.proyecto.buscar_cml("T-3001-CML-02")[2].mediciones) == 4   # sin cambios
    otro.despachar("restablecer_demo")
    assert len(otro.proyecto.buscar_cml("T-3001-CML-02")[2].mediciones) == 3
    assert json.loads(otro.exportar_json())["fecha_evaluacion"] == "2026-11-23"


def test_cambio_de_fecha_recalcula(c):
    c.despachar("fecha", {"fecha": "2030-01-01"})
    _ok(c)
    fila = next(f for f in c.evaluacion()["filas"] if f["cml_id"] == "L-1001-CML-02")
    assert fila["estado"] == ce.ESTADO_INSPECCION_VENCIDA
    c.despachar("fecha", {"fecha": "no-fecha"})
    _error(c)
    c.despachar("fecha_hoy")
    assert c.fecha_evaluacion == HOY
