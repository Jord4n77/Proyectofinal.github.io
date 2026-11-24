"""
demo_data.py — Caso demostrativo del proyecto (datos FICTICIOS).

Construye un ``Proyecto`` con una tubería, un recipiente y un tanque, cuatro
CML por equipo, tres o cuatro campañas históricas por familia, un esquema PNG por
familia y datos RBI en los tres equipos. Los valores se eligieron para que, con
fecha de evaluación 2026-11-23, aparezcan todas las condiciones y casos de borde
que pide el enunciado (§4.4, §4.5 y §6).

    CML               Condición esperada    Caso que demuestra
    ----------------  --------------------  ---------------------------------------------
    L-1001-CML-01     NORMAL                corrosión baja y uniforme
    L-1001-CML-02     ALERTA                erosión-corrosión aguas abajo de FV-1001 (RL ≤ 2 años)
    L-1001-CML-03     NORMAL                reemplazo de carrete en 2022 (línea base reiniciada)
    L-1001-CML-04     NORMAL                punto nuevo, una sola medición (DATOS_INSUFICIENTES)
    V-2001-CML-01     NORMAL                corrosión general baja
    V-2001-CML-02     BAJO_MINIMO           zona de interfase agua/hidrocarburo
    V-2001-CML-03     INSPECCION_VENCIDA    bajo aislación, sin medición en 2026
    V-2001-CML-04     NORMAL                dispersión de medición (CR_LT < 0)
    T-3001-CML-01     NORMAL                campaña 2016 registrada en pulgadas
    T-3001-CML-02     ALERTA                corrosión interna por agua decantada, virola 1
    T-3001-CML-03     NORMAL                fecha digitada errónea 2062 (FECHAS_INCONSISTENTES)
    T-3001-CML-04     NORMAL                sin pérdida medible (CORROSION_NULA_O_NEGATIVA)

Uso::

    python src/demo_data.py            # escribe data/proyecto_demo.json con adjuntos base64
"""

from __future__ import annotations

import base64
import os
import sys
from datetime import date
from typing import Dict, Iterable, List, Optional, Tuple

if __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import calc_engine as ce  # noqa: E402
from models import (CML, Area, Componente, CondicionesProceso, ConfianzaCR, DatosRBI,  # noqa: E402
                    Documento, Efectividad, Equipo, EventoMedicion, Familia, Intervencion,
                    Medicion, ParametrosCalculo, Planta, Proyecto, Sistema, TecnicaMedicion,
                    TipoComponente, TipoDocumento, TipoIntervencion, UnidadEspesor)

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FECHA_EVALUACION_DEMO = date(2026, 11, 23)

# Tamaño de los esquemas (px) y posición de los marcadores como fracción del
# ancho/alto, con origen en la esquina superior izquierda (convención de models.py).
ANCHO_ESQUEMA, ALTO_ESQUEMA = 1200, 750
ESQUEMAS = {
    "L-1001": ("ISO-L-1001", "assets/img/L-1001_isometrico.png", "Isométrico L-1001 (tramo recto)"),
    "V-2001": ("ESQ-V-2001", "assets/img/V-2001_esquema.png", "Esquema V-2001 (envolvente cilíndrica)"),
    "T-3001": ("ESQ-T-3001", "assets/img/T-3001_elevacion.png", "Elevación T-3001 (virolas del manto)"),
}
MARCADORES: Dict[str, Tuple[float, float]] = {
    "L-1001-CML-01": (0.192, 0.647),
    "L-1001-CML-02": (0.467, 0.487),
    "L-1001-CML-03": (0.713, 0.512),
    "L-1001-CML-04": (0.823, 0.411),
    "V-2001-CML-01": (0.517, 0.320),
    "V-2001-CML-02": (0.600, 0.607),
    "V-2001-CML-03": (0.333, 0.467),
    "V-2001-CML-04": (0.750, 0.320),
    "T-3001-CML-01": (0.300, 0.800),
    "T-3001-CML-02": (0.575, 0.816),
    "T-3001-CML-03": (0.367, 0.684),
    "T-3001-CML-04": (0.492, 0.580),
}

# Campañas de inspección (fechas comunes por familia)
CAMP_TUB = (date(2018, 6, 12), date(2022, 6, 14), date(2026, 6, 16))
CAMP_REC = (date(2014, 5, 20), date(2018, 6, 12), date(2022, 6, 14), date(2026, 6, 16))
CAMP_TAN = (date(2016, 9, 20), date(2021, 9, 14), date(2026, 9, 15))

INSPECTORES = {"TUB": "Insp. A. Rojas (ficticio)", "REC": "Insp. C. Muñoz (ficticio)",
               "TAN": "Contratista END Ltda. (ficticio)"}


def _meds(cml_id: str, datos: Iterable[tuple], inspector: str) -> List[Medicion]:
    """Crea mediciones a partir de tuplas (fecha, espesor[, dict de opciones])."""
    salida = []
    for i, d in enumerate(datos, start=1):
        fecha, espesor = d[0], d[1]
        op = d[2] if len(d) > 2 else {}
        salida.append(Medicion(id=f"{cml_id}-M{i}", fecha=fecha, espesor=espesor,
                               unidad=op.get("unidad", UnidadEspesor.MM),
                               tecnica=op.get("tecnica", TecnicaMedicion.UT),
                               inspector=op.get("inspector", inspector),
                               observaciones=op.get("obs", ""),
                               valida=op.get("valida", True),
                               evento=op.get("evento", EventoMedicion.NORMAL)))
    return salida


def _cml(cml_id: str, ubicacion: str, horaria: Optional[str], distancia: Optional[float],
         doc_id: str, mediciones: List[Medicion], convencion: Optional[str] = None,
         intervenciones: Optional[List[Intervencion]] = None) -> CML:
    x, y = MARCADORES[cml_id]
    kw = {"convencion": convencion} if convencion else {}
    return CML(id=cml_id, descripcion_ubicacion=ubicacion, posicion_horaria=horaria,
               distancia_referencia_mm=distancia, documento_id=doc_id, marcador_x=x,
               marcador_y=y, mediciones=mediciones, intervenciones=intervenciones or [], **kw)


def _documento(tag: str, incluir_adjuntos: bool) -> Documento:
    doc_id, ruta, nombre = ESQUEMAS[tag]
    contenido = None
    ruta_abs = os.path.join(RAIZ, ruta)
    if incluir_adjuntos and os.path.exists(ruta_abs):
        with open(ruta_abs, "rb") as f:
            contenido = base64.b64encode(f.read()).decode("ascii")
    return Documento(id=doc_id, nombre=nombre, tipo=TipoDocumento.PNG,
                     descripcion="Esquema académico sin escala; datos ficticios.",
                     ruta=ruta, contenido_base64=contenido,
                     ancho_px=ANCHO_ESQUEMA, alto_px=ALTO_ESQUEMA)


# =============================================================================
# Tubería L-1001 — ASME B31.3 / API 570
# =============================================================================

def tuberia_demo(incluir_adjuntos: bool = True) -> Equipo:
    doc = _documento("L-1001", incluir_adjuntos)
    d = doc.id
    t1, t2, t3 = CAMP_TUB
    ins = INSPECTORES["TUB"]
    cmls = [
        _cml("L-1001-CML-01", "Tramo recto horizontal, descarga de P-1001 A/B", "6 h", 1200.0, d,
             _meds("L-1001-CML-01", [(t1, 7.02), (t2, 6.90), (t3, 6.78)], ins)),
        _cml("L-1001-CML-02", "Aguas abajo de válvula de control FV-1001 (≈ 3D)", "6 h", 480.0, d,
             _meds("L-1001-CML-02", [(t1, 6.40), (t2, 5.10),
                                     (t3, 3.45, {"obs": "Pérdida acelerada; se recomienda barrido UT."})], ins)),
        _cml("L-1001-CML-03", "Carrete reemplazado en mayo de 2022", "12 h", 650.0, d,
             _meds("L-1001-CML-03", [
                 (t1, 6.95),
                 (date(2021, 11, 8), 4.20, {"obs": "Hallazgo en inspección no programada."}),
                 (t2, 7.10, {"obs": "Primera medición del carrete nuevo (línea base)."}),
                 (t3, 6.95)], ins),
             intervenciones=[Intervencion("L-1001-INT-01", date(2022, 5, 20), TipoIntervencion.REEMPLAZO,
                                          "Reemplazo de carrete NPS 6 Sch 40 por pérdida localizada.",
                                          espesor_nuevo_mm=7.11)]),
        _cml("L-1001-CML-04", "Tramo recto previo a boquilla N1 de V-2001 (punto nuevo 2026)", "6 h",
             900.0, d, _meds("L-1001-CML-04", [(t3, 6.98, {"obs": "Punto incorporado en 2026."})], ins)),
    ]
    comp = Componente(id="L-1001-TR01", nombre="Tramo recto NPS 6 Sch 40",
                      tipo=TipoComponente.TRAMO_RECTO, t_nom_mm=7.11, diametro_exterior_mm=168.3,
                      nps="6", cedula="40", cmls=cmls)
    return Equipo(
        tag="L-1001", descripcion="Línea de nafta, descarga bombas P-1001 A/B a V-2001",
        familia=Familia.TUBERIA, material_id="A106-B", servicio="Nafta liviana",
        fluido="Hidrocarburo líquido", circuito_inspeccion="CIR-100-01",
        fecha_puesta_servicio=date(2012, 1, 15),
        diseno=CondicionesProceso(presion_MPa=5.0, temperatura_C=150.0),
        operacion=CondicionesProceso(presion_MPa=4.2, temperatura_C=120.0),
        parametros=ParametrosCalculo(sobreespesor_corrosion_mm=1.5, eficiencia_junta=1.0,
                                     factor_W=1.0, coeficiente_Y=0.4, tolerancia_fabricacion=0.125,
                                     t_estructural_mm=2.8, clase_tuberia=2, dt_margen_anios=2.0),
        documentos=[doc], componentes=[comp],
        rbi=DatosRBI(tipo_componente_gff="TUBERIA", confianza_cr=ConfianzaCR.MEDIA,
                     inspecciones={"C": 3}, puntaje_sistema_gestion=600,
                     area_consecuencia_m2=150.0, consecuencia_economica=8.0e5, moneda="USD",
                     base_valoracion="Reparación + 3 días de producción diferida; USD de 2026 (ficticio).",
                     cml_referencia_id="L-1001-CML-01",
                     justificacion_cml_referencia=(
                         "CML-01 representa el adelgazamiento generalizado del circuito. CML-02 presenta "
                         "erosión-corrosión localizada aguas abajo de FV-1001: mecanismo local fuera del "
                         "submodelo, gestionado por inspección dirigida y su estado ALERTA."),
                     efectividad_propuesta=Efectividad.B, horizonte_plan_anios=4.0),
    )


# =============================================================================
# Recipiente V-2001 — ASME VIII-1 / API 510
# =============================================================================

def recipiente_demo(incluir_adjuntos: bool = True) -> Equipo:
    doc = _documento("V-2001", incluir_adjuntos)
    d = doc.id
    c0, c1, c2, c3 = CAMP_REC
    ins = INSPECTORES["REC"]
    conv = ("Posición horaria vista desde el cabezal de entrada (lado N1); distancia medida "
            "desde la soldadura circunferencial cabezal-envolvente del lado N1.")
    cmls = [
        _cml("V-2001-CML-01", "Envolvente, generatriz superior, centro", "12 h", 2100.0, d,
             _meds("V-2001-CML-01", [(c0, 15.95), (c1, 15.80), (c2, 15.62), (c3, 15.35)], ins), conv),
        _cml("V-2001-CML-02", "Envolvente inferior junto a bota, zona interfase agua", "6 h", 2700.0, d,
             _meds("V-2001-CML-02", [(c0, 14.60), (c1, 13.20), (c2, 11.40),
                                     (c3, 9.55, {"obs": "Bajo t_min: informar a ingeniería (FFS)."})], ins),
             conv),
        _cml("V-2001-CML-03", "Envolvente lateral bajo aislación", "3 h", 1000.0, d,
             _meds("V-2001-CML-03", [(c0, 13.60), (c1, 12.40),
                                     (c2, 11.10, {"obs": "Requiere retiro de aislación para medir."})], ins),
             conv),
        _cml("V-2001-CML-04", "Envolvente superior junto a boquilla N3", "12 h", 3300.0, d,
             _meds("V-2001-CML-04", [(c0, 16.00), (c1, 15.95), (c2, 16.05), (c3, 16.02)], ins), conv),
    ]
    comp = Componente(id="V-2001-ENV", nombre="Envolvente cilíndrica Ø int. 1500 mm",
                      tipo=TipoComponente.ENVOLVENTE_CILINDRICA, t_nom_mm=16.0,
                      radio_interior_mm=750.0, cmls=cmls)
    return Equipo(
        tag="V-2001", descripcion="Acumulador horizontal de nafta con bota de agua",
        familia=Familia.RECIPIENTE, material_id="SA-516-70", servicio="Nafta con agua libre",
        fluido="Hidrocarburo + agua ácida", fecha_puesta_servicio=date(2008, 3, 1),
        diseno=CondicionesProceso(presion_MPa=1.5, temperatura_C=200.0),
        operacion=CondicionesProceso(presion_MPa=1.2, temperatura_C=170.0),
        parametros=ParametrosCalculo(sobreespesor_corrosion_mm=3.0, eficiencia_junta=0.85,
                                     tolerancia_placa_mm=0.25, regla_rl_menor_4="CONSERVADORA_1_4",
                                     dt_margen_anios=2.0),
        documentos=[doc], componentes=[comp],
        rbi=DatosRBI(tipo_componente_gff="RECIPIENTE", confianza_cr=ConfianzaCR.ALTA,
                     inspecciones={"B": 1, "C": 3}, puntaje_sistema_gestion=600,
                     area_consecuencia_m2=450.0, consecuencia_economica=1.2e9, moneda="CLP",
                     tasa_a_usd=0.00105,
                     base_valoracion=("Reemplazo de virola + 10 días de lucro cesante; CLP nov-2026; "
                                      "tasa referencial 1 CLP = 0.00105 USD (verificar)."),
                     cml_referencia_id=None,
                     justificacion_cml_referencia="Se usa la mayor CR del equipo (criterio conservador).",
                     efectividad_propuesta=Efectividad.A, horizonte_plan_anios=2.0),
    )


# =============================================================================
# Tanque T-3001 — API 650 / API 653 (virolas del manto)
# =============================================================================

def tanque_demo(incluir_adjuntos: bool = True) -> Equipo:
    doc = _documento("T-3001", incluir_adjuntos)
    d = doc.id
    k1, k2, k3 = CAMP_TAN
    ins = INSPECTORES["TAN"]
    conv = ("Posición angular en planta, 0° = norte de planta, sentido horario; altura medida "
            "desde la soldadura horizontal inferior de la virola.")
    v1 = [
        _cml("T-3001-CML-01", "Virola 1, 0°, 300 mm sobre soldadura manto-fondo", "0°", 300.0, d,
             _meds("T-3001-CML-01", [(k1, 0.4665, {"unidad": UnidadEspesor.IN,
                                                  "obs": "Registro original del contratista en pulgadas."}),
                                     (k2, 11.55), (k3, 11.25)], ins), conv),
        _cml("T-3001-CML-02", "Virola 1, 180°, junto a drenaje de agua", "180°", 250.0, d,
             _meds("T-3001-CML-02", [(k1, 11.70), (k2, 10.60), (k3, 9.00)], ins), conv),
    ]
    v2 = [
        _cml("T-3001-CML-03", "Virola 2, 90°, centro de virola", "90°", 1000.0, d,
             _meds("T-3001-CML-03", [(k1, 9.90), (k2, 9.80),
                                     (date(2062, 9, 15), 9.72,
                                      {"obs": "Fecha digitada erróneamente (debió ser 2026-09-15)."})], ins),
             conv),
    ]
    v3 = [
        _cml("T-3001-CML-04", "Virola 3, 270°, centro de virola", "270°", 1000.0, d,
             _meds("T-3001-CML-04", [(k1, 7.95), (k2, 7.97), (k3, 7.98)], ins), conv),
    ]
    comps = [
        Componente(id="T-3001-V1", nombre="Virola 1 (inferior)", tipo=TipoComponente.VIROLA,
                   t_nom_mm=12.0, numero_virola=1, altura_virola_m=2.0, nivel_sobre_fondo_virola_m=12.0,
                   cmls=v1),
        Componente(id="T-3001-V2", nombre="Virola 2", tipo=TipoComponente.VIROLA, t_nom_mm=10.0,
                   numero_virola=2, altura_virola_m=2.0, nivel_sobre_fondo_virola_m=10.0, cmls=v2),
        Componente(id="T-3001-V3", nombre="Virola 3", tipo=TipoComponente.VIROLA, t_nom_mm=8.0,
                   numero_virola=3, altura_virola_m=2.0, nivel_sobre_fondo_virola_m=8.0, cmls=v3),
    ]
    return Equipo(
        tag="T-3001", descripcion="Tanque de techo fijo cónico, almacenamiento de diésel",
        familia=Familia.TANQUE, material_id="A36M", servicio="Diésel", fluido="Diésel (G = 0.85)",
        fecha_puesta_servicio=date(2005, 4, 10),
        diseno=CondicionesProceso(presion_MPa=0.0, temperatura_C=40.0),
        operacion=CondicionesProceso(presion_MPa=0.0, temperatura_C=25.0),
        parametros=ParametrosCalculo(sobreespesor_corrosion_mm=1.5, eficiencia_junta=1.0,
                                     eficiencia_junta_servicio=1.0, diametro_tanque_m=30.0,
                                     altura_liquido_diseno_m=12.0, densidad_relativa_G=0.85,
                                     dt_margen_anios=2.0),
        documentos=[doc], componentes=comps,
        rbi=DatosRBI(tipo_componente_gff="TANQUE_VIROLA", confianza_cr=ConfianzaCR.MEDIA,
                     inspecciones={"C": 3}, puntaje_sistema_gestion=600,
                     area_consecuencia_m2=900.0, consecuencia_economica=2.5e6, moneda="USD",
                     base_valoracion=("Limpieza de derrame contenido en dique + reparación de virola; "
                                      "USD de 2026 (ficticio)."),
                     cml_referencia_id=None,
                     justificacion_cml_referencia="Se usa la mayor CR del equipo (criterio conservador).",
                     efectividad_propuesta=Efectividad.B, horizonte_plan_anios=5.0),
    )


# =============================================================================
# Proyecto
# =============================================================================

def construir_proyecto_demo(incluir_adjuntos: bool = True) -> Proyecto:
    """Proyecto demostrativo con la jerarquía Planta / Área / Sistema / Equipo."""
    planta = Planta("PL-01", "Planta Demo Viña del Mar (ficticia)", [
        Area("A-100", "Unidad 100 — Fraccionamiento", [
            Sistema("S-101", "Circuito CIR-100-01 — Nafta", [tuberia_demo(incluir_adjuntos)]),
            Sistema("S-102", "Acumulación de cabeza", [recipiente_demo(incluir_adjuntos)]),
        ]),
        Area("A-300", "Área 300 — Almacenamiento", [
            Sistema("S-301", "Patio de tanques de diésel", [tanque_demo(incluir_adjuntos)]),
        ]),
    ])
    return Proyecto(
        nombre="Caso demostrativo — Gestión de integridad de equipos estáticos",
        plantas=[planta], fecha_evaluacion=FECHA_EVALUACION_DEMO,
        ediciones_normativas=dict(ce.EDICIONES_NORMATIVAS),
        criterios_grupo=dict(ce.CRITERIOS_GRUPO),
        notas=("Datos ficticios con fines académicos (MAN040-B). Esfuerzos admisibles referenciales: "
               "verificar contra las tablas de la edición declarada."),
    )


def guardar_proyecto_demo(ruta: Optional[str] = None, incluir_adjuntos: bool = True) -> str:
    ruta = ruta or os.path.join(RAIZ, "data", "proyecto_demo.json")
    proyecto = construir_proyecto_demo(incluir_adjuntos)
    problemas = proyecto.validar_integridad()
    if problemas:
        raise ValueError("El caso demostrativo no pasa la validación: " + "; ".join(problemas))
    os.makedirs(os.path.dirname(ruta), exist_ok=True)
    with open(ruta, "w", encoding="utf-8") as f:
        f.write(proyecto.a_json())
    return ruta


if __name__ == "__main__":
    print("Proyecto guardado en", guardar_proyecto_demo())
    # Versión liviana (adjuntos restablecibles por ruta), cómoda para revisar diferencias en Git
    print("Versión sin adjuntos en", guardar_proyecto_demo(
        os.path.join(RAIZ, "data", "proyecto_demo_sin_adjuntos.json"), incluir_adjuntos=False))
