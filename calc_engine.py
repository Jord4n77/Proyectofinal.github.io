"""
calc_engine.py — Núcleo de cálculo normativo para integridad de equipos estáticos.

Prototipo académico (MAN040-B, Proyecto Final) inspirado en las funciones de
gestión de integridad de herramientas tipo UltraPIPE.

Diseño del módulo
-----------------
* Python puro (biblioteca estándar: ``math``, ``datetime``). Sin dependencias del
  DOM, de PyScript ni de NumPy, de modo que el mismo archivo se ejecuta en
  ``pytest`` local y dentro de Pyodide en GitHub Pages.
* Funciones puras: no leen ni modifican estado global; los catálogos son
  constantes de solo lectura que pueden reemplazarse pasando argumentos.
* Toda función pública de cálculo devuelve un diccionario con la estructura::

      {
        "entradas":             {...},   # valores usados, en unidades SI declaradas
        "ecuacion_texto":       str,     # ecuación en texto plano
        "referencia_normativa": str,     # norma, edición y párrafo/tabla
        "resultado":            float | dict | None,
        "unidad":               str | dict,
        "observaciones":        [str, ...],
        "alertas":              [str, ...],   # códigos de alerta (puede ir vacío)
        "detalle":              {...},        # solo en funciones compuestas
      }

* Los errores de **entrada física** (p. ej. presión negativa, E > 1) levantan
  ``ValueError``: la interfaz debe capturarlos y mostrarlos. Los problemas de
  **calidad de datos** (pocas mediciones, fechas inconsistentes, CR ≤ 0) no
  levantan excepción: se informan como alertas.

Sistema de unidades (SI coherente)
----------------------------------
=====================  ===========  ============================================
Magnitud               Unidad       Nota
=====================  ===========  ============================================
Presión                MPa          manométrica
Esfuerzo admisible     MPa
Espesor, diámetro de   mm
tubería, radio de
recipiente
Diámetro y altura de   m            forma SI de API 650 §5.6.3.2 / API 653 §4.3.3
tanque
Tiempo                 años         1 año = 365.25 días
Velocidad de corrosión mm/año
Temperatura            °C
Área de consecuencia   m²
Consecuencia económica moneda       declarada por el usuario (USD, CLP, ...)
=====================  ===========  ============================================

Ediciones normativas declaradas
-------------------------------
Ver ``EDICIONES_NORMATIVAS``. La numeración de párrafos citada corresponde a
esas ediciones; el grupo debe confirmarla con la edición que tenga disponible.

Advertencia
-----------
Los valores de esfuerzo admisible de los catálogos son **valores referenciales
transcritos para uso académico** (ver campo ``estado_verificacion``). Antes de
presentar resultados deben contrastarse con la tabla de la edición declarada.
Este módulo no reemplaza el juicio de un inspector autorizado ni de un ingeniero.
"""

from __future__ import annotations

import math
from datetime import date, datetime, timedelta
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

__version__ = "0.1.0"

# =============================================================================
# 0. CONSTANTES GENERALES, CÓDIGOS Y UTILIDADES
# =============================================================================

DIAS_POR_ANIO: float = 365.25
MM_POR_PULGADA: float = 25.4

EDICIONES_NORMATIVAS: Dict[str, str] = {
    "ASME B31.3": "2022 (Process Piping)",
    "ASME BPVC Sec. VIII Div. 1": "2023",
    "ASME BPVC Sec. II Parte D": "2023 (Tablas 1A, métricas)",
    "API 650": "13.ª ed. (2020) + adendas",
    "API 653": "5.ª ed. (2014) + adendas",
    "API 570": "4.ª ed. (2016) + adendas",
    "API 510": "11.ª ed. (2022)",
    "API RP 580": "3.ª ed. (2016)",
    "API RP 581": "3.ª ed. (2016) + adendas — Parte 1 (planificación), "
                  "Parte 2 (POF, §4 adelgazamiento)",
}

# --- Familias -----------------------------------------------------------------
FAMILIA_TUBERIA = "TUBERIA"
FAMILIA_RECIPIENTE = "RECIPIENTE"
FAMILIA_TANQUE = "TANQUE"
FAMILIAS = (FAMILIA_TUBERIA, FAMILIA_RECIPIENTE, FAMILIA_TANQUE)

# --- Códigos de alerta (calidad de datos y condición) -------------------------
ALERTA_DATOS_INSUFICIENTES = "DATOS_INSUFICIENTES"
ALERTA_FECHAS_INCONSISTENTES = "FECHAS_INCONSISTENTES"
ALERTA_CORROSION_NULA_O_NEGATIVA = "CORROSION_NULA_O_NEGATIVA"
ALERTA_LINEA_BASE_REINICIADA = "LINEA_BASE_REINICIADA"
ALERTA_BAJO_MINIMO = "BAJO_MINIMO"
ALERTA_FUERA_DE_ALCANCE = "FUERA_DE_ALCANCE"
ALERTA_NOMINAL_INSUFICIENTE = "NOMINAL_INSUFICIENTE"
ALERTA_PROYECCION_BAJO_MINIMO = "PROYECCION_BAJO_MINIMO"
CODIGOS_ALERTA = (
    ALERTA_DATOS_INSUFICIENTES,
    ALERTA_FECHAS_INCONSISTENTES,
    ALERTA_CORROSION_NULA_O_NEGATIVA,
    ALERTA_LINEA_BASE_REINICIADA,
    ALERTA_BAJO_MINIMO,
    ALERTA_FUERA_DE_ALCANCE,
    ALERTA_NOMINAL_INSUFICIENTE,
    ALERTA_PROYECCION_BAJO_MINIMO,
)

# --- Estados de condición (orden = severidad creciente) -----------------------
ESTADO_NORMAL = "NORMAL"
ESTADO_ALERTA = "ALERTA"
ESTADO_INSPECCION_VENCIDA = "INSPECCION_VENCIDA"
ESTADO_BAJO_MINIMO = "BAJO_MINIMO"
ESTADOS = (ESTADO_NORMAL, ESTADO_ALERTA, ESTADO_INSPECCION_VENCIDA, ESTADO_BAJO_MINIMO)

# --- Eventos que rompen la comparabilidad de una serie de espesores -----------
EVENTO_NORMAL = "NORMAL"
EVENTO_CAMBIO_PUNTO = "CAMBIO_PUNTO"
EVENTO_REPARACION = "REPARACION"
EVENTO_REEMPLAZO = "REEMPLAZO"
EVENTOS_MEDICION = (EVENTO_NORMAL, EVENTO_CAMBIO_PUNTO, EVENTO_REPARACION, EVENTO_REEMPLAZO)
EVENTOS_REINICIO = (EVENTO_CAMBIO_PUNTO, EVENTO_REPARACION, EVENTO_REEMPLAZO)

# --- Criterios del grupo (NO normativos; declarados y configurables) ----------
CRITERIOS_GRUPO: Dict[str, Any] = {
    # Plazo de intervención usado para el espesor de alerta: tiempo que se estima
    # necesario para planificar y ejecutar una reparación o reemplazo.
    "dt_margen_anios": 2.0,
    # Margen mínimo absoluto sobre t_min para la alerta cuando CR no es positiva.
    "margen_min_mm": 0.0,
    # Intervalo cuando no se puede establecer CR (menos de 2 mediciones válidas)
    # en API 510/570. API 653 §6.3.3.2 fija 5 años para el manto (normativo).
    "intervalo_cr_desconocida_anios": 2.0,
}


def _resultado(
    entradas: Mapping[str, Any],
    ecuacion_texto: str,
    referencia_normativa: str,
    resultado: Any,
    unidad: Any,
    observaciones: Optional[Iterable[str]] = None,
    alertas: Optional[Iterable[str]] = None,
    detalle: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Construye el diccionario de salida estándar de todas las funciones."""
    salida: Dict[str, Any] = {
        "entradas": dict(entradas),
        "ecuacion_texto": ecuacion_texto,
        "referencia_normativa": referencia_normativa,
        "resultado": resultado,
        "unidad": unidad,
        "observaciones": list(observaciones or []),
        "alertas": _sin_duplicados(alertas or []),
    }
    if detalle is not None:
        salida["detalle"] = dict(detalle)
    return salida


def _sin_duplicados(items: Iterable[str]) -> List[str]:
    """Elimina duplicados conservando el orden de aparición."""
    vistos: List[str] = []
    for item in items:
        if item not in vistos:
            vistos.append(item)
    return vistos


def _positivo(nombre: str, valor: float) -> float:
    if valor is None or not isinstance(valor, (int, float)) or not math.isfinite(valor) or valor <= 0:
        raise ValueError(f"{nombre} debe ser un número finito > 0 (recibido: {valor!r}).")
    return float(valor)


def _no_negativo(nombre: str, valor: float) -> float:
    if valor is None or not isinstance(valor, (int, float)) or not math.isfinite(valor) or valor < 0:
        raise ValueError(f"{nombre} debe ser un número finito ≥ 0 (recibido: {valor!r}).")
    return float(valor)


def _fraccion(nombre: str, valor: float, incluir_cero: bool = False) -> float:
    """Valida un factor adimensional en (0, 1] o [0, 1]."""
    if valor is None or not isinstance(valor, (int, float)) or not math.isfinite(valor):
        raise ValueError(f"{nombre} debe ser numérico (recibido: {valor!r}).")
    minimo_ok = valor >= 0 if incluir_cero else valor > 0
    if not (minimo_ok and valor <= 1):
        rango = "[0, 1]" if incluir_cero else "(0, 1]"
        raise ValueError(f"{nombre} debe estar en {rango} (recibido: {valor!r}).")
    return float(valor)


def a_fecha(valor: Any) -> date:
    """Convierte ``date``, ``datetime`` o texto ISO 'AAAA-MM-DD' a ``date``."""
    if isinstance(valor, datetime):
        return valor.date()
    if isinstance(valor, date):
        return valor
    if isinstance(valor, str):
        return date.fromisoformat(valor.strip()[:10])
    raise ValueError(f"Fecha no reconocida: {valor!r} (use date o 'AAAA-MM-DD').")


def anios_entre(fecha_inicial: Any, fecha_final: Any) -> float:
    """Diferencia en años decimales (días / 365.25). Puede ser ≤ 0."""
    return (a_fecha(fecha_final) - a_fecha(fecha_inicial)).days / DIAS_POR_ANIO


def sumar_anios(fecha: Any, anios: float) -> date:
    """Suma un intervalo en años decimales a una fecha (redondeo al día)."""
    return a_fecha(fecha) + timedelta(days=round(anios * DIAS_POR_ANIO))


def a_mm(valor: float, unidad: str = "mm") -> float:
    """Convierte un espesor a mm. Unidades admitidas: 'mm', 'in'."""
    u = (unidad or "mm").strip().lower()
    if u == "mm":
        return float(valor)
    if u in ("in", "pulg", "pulgada", "\""):
        return float(valor) * MM_POR_PULGADA
    raise ValueError(f"Unidad de espesor no admitida: {unidad!r} (use 'mm' o 'in').")


def interpolar_lineal(xs: Sequence[float], ys: Sequence[float], x: float) -> float:
    """Interpolación lineal en una tabla ordenada; fuera de rango levanta ValueError."""
    if len(xs) != len(ys) or len(xs) < 2:
        raise ValueError("Tabla de interpolación inválida.")
    if x < xs[0] or x > xs[-1]:
        raise ValueError(f"x = {x} fuera del rango tabulado [{xs[0]}, {xs[-1]}].")
    for i in range(1, len(xs)):
        if x <= xs[i]:
            x0, x1, y0, y1 = xs[i - 1], xs[i], ys[i - 1], ys[i]
            if x1 == x0:
                return float(y1)
            return float(y0 + (y1 - y0) * (x - x0) / (x1 - x0))
    return float(ys[-1])  # pragma: no cover


# =============================================================================
# 1. CATÁLOGOS DE MATERIALES (acotados, uso académico)
# =============================================================================
# Los puntos de temperatura corresponden a las columnas de las tablas ASME
# (−20…100 °F, 200 °F, 300 °F, ...) convertidas a °C; los esfuerzos están en MPa.
# Entre puntos se interpola linealmente (ASME B31.3 Tabla A-1M y ASME II-D
# admiten interpolación lineal entre temperaturas tabuladas).

_NOTA_VERIFICACION = (
    "Valores referenciales transcritos para uso académico; verificar contra la "
    "tabla de la edición declarada antes de su uso en la presentación."
)

MATERIALES_TUBERIA: Dict[str, Dict[str, Any]] = {
    "A106-B": {
        "descripcion": "ASTM A106 Gr. B — tubo sin costura de acero al carbono",
        "norma_tabla": "ASME B31.3-2022, Apéndice A, Tabla A-1M",
        "tipo_y": "FERRITICO",          # para Tabla 304.1.1 (coeficiente Y)
        "smys_MPa": 240.0,
        "smts_MPa": 415.0,
        "E_tipico": 1.0,                # Tabla A-1A: tubo sin costura, E = 1.00
        "temperaturas_C": [-29.0, 38.0, 93.0, 149.0, 204.0, 260.0, 316.0, 343.0],
        "S_MPa":          [138.0, 138.0, 138.0, 138.0, 138.0, 130.0, 119.0, 114.0],
        "estado_verificacion": _NOTA_VERIFICACION,
    },
}

MATERIALES_RECIPIENTE: Dict[str, Dict[str, Any]] = {
    "SA-516-70": {
        "descripcion": "SA-516 Gr. 70 — plancha de acero al carbono para recipientes",
        "norma_tabla": "ASME BPVC Sec. II Parte D-2023, Tabla 1A",
        "smys_MPa": 260.0,
        "smts_MPa": 485.0,
        "temperaturas_C": [-29.0, 38.0, 93.0, 149.0, 204.0, 260.0, 316.0, 343.0, 371.0],
        "S_MPa":          [138.0, 138.0, 138.0, 138.0, 138.0, 138.0, 134.0, 130.0, 125.0],
        "estado_verificacion": _NOTA_VERIFICACION,
    },
    "SA-240-304L": {
        "descripcion": "SA-240 Tipo 304L — plancha de acero inoxidable austenítico",
        "norma_tabla": "ASME BPVC Sec. II Parte D-2023, Tabla 1A "
                       "(fila de esfuerzo sin nota G5)",
        "smys_MPa": 170.0,
        "smts_MPa": 485.0,
        "temperaturas_C": [-29.0, 38.0, 93.0, 149.0, 204.0, 260.0, 316.0, 343.0, 371.0],
        "S_MPa":          [115.0, 115.0, 115.0, 115.0, 109.0, 101.0, 97.0, 94.0, 93.0],
        "estado_verificacion": _NOTA_VERIFICACION,
    },
}

# API 650 Tabla 5-2a (SI): Sd = min(2/3·Y, 2/5·T); St = min(3/4·Y, 3/7·T).
# Válido para temperatura de diseño ≤ 93 °C (sobre eso, API 650 Anexo M).
MATERIALES_TANQUE: Dict[str, Dict[str, Any]] = {
    "A36M": {
        "descripcion": "ASTM A36M — plancha de acero estructural",
        "norma_tabla": "API 650 13.ª ed., Tabla 5-2a",
        "smys_MPa": 250.0,
        "smts_MPa": 400.0,
        "Sd_MPa": 160.0,
        "St_MPa": 171.0,
        "temperatura_max_C": 93.0,
        "estado_verificacion": _NOTA_VERIFICACION,
    },
    "A516M-485": {
        "descripcion": "ASTM A516M Gr. 485 (Gr. 70) — plancha de acero al carbono",
        "norma_tabla": "API 650 13.ª ed., Tabla 5-2a",
        "smys_MPa": 260.0,
        "smts_MPa": 485.0,
        "Sd_MPa": 173.0,
        "St_MPa": 195.0,
        "temperatura_max_C": 93.0,
        "estado_verificacion": _NOTA_VERIFICACION,
    },
}


def esfuerzo_admisible(material_id: str, temperatura_C: float,
                       catalogo: Optional[Mapping[str, Mapping[str, Any]]] = None) -> Dict[str, Any]:
    """Esfuerzo admisible S(T) por interpolación lineal en el catálogo.

    Busca ``material_id`` en el catálogo indicado o, si es ``None``, en los
    catálogos de tubería (B31.3 Tabla A-1M) y recipientes (ASME II-D Tabla 1A).
    Fuera del rango tabulado levanta ``ValueError`` (no se extrapola).

    Parámetros
    ----------
    material_id : str     Clave del catálogo, p. ej. 'SA-516-70'.
    temperatura_C : float Temperatura de diseño del metal [°C].
    """
    cat = catalogo if catalogo is not None else {**MATERIALES_TUBERIA, **MATERIALES_RECIPIENTE}
    if material_id not in cat:
        raise ValueError(f"Material {material_id!r} no está en el catálogo: {sorted(cat)}.")
    m = cat[material_id]
    if "temperaturas_C" not in m:
        raise ValueError(f"El material {material_id!r} no tiene tabla S(T).")
    S = interpolar_lineal(m["temperaturas_C"], m["S_MPa"], float(temperatura_C))
    return _resultado(
        entradas={"material_id": material_id, "temperatura_C": temperatura_C},
        ecuacion_texto="S(T) = S_i + (S_i+1 − S_i)·(T − T_i)/(T_i+1 − T_i)  (interpolación lineal)",
        referencia_normativa=m["norma_tabla"],
        resultado=S,
        unidad="MPa",
        observaciones=[m["descripcion"], m["estado_verificacion"],
                       f"Rango tabulado: {m['temperaturas_C'][0]} a {m['temperaturas_C'][-1]} °C."],
    )


# =============================================================================
# 2. TUBERÍAS DE PROCESO — ASME B31.3 (diseño) / API 570 (en servicio)
#    Geometría: tramo recto bajo presión interna.
# =============================================================================

# ASME B31.3 Tabla 304.1.1 — coeficiente Y para t < D/6.
_TABLA_Y_B31_3: Dict[str, Tuple[List[float], List[float]]] = {
    "FERRITICO":   ([482.0, 510.0, 538.0], [0.4, 0.5, 0.7]),
    "AUSTENITICO": ([566.0, 593.0, 621.0], [0.4, 0.5, 0.7]),
    "OTROS_DUCTILES": ([482.0, 621.0], [0.4, 0.4]),
}


def coeficiente_y_b31_3(temperatura_C: float, tipo_material: str = "FERRITICO") -> Dict[str, Any]:
    """Coeficiente Y de ASME B31.3 Tabla 304.1.1 (válido para t < D/6).

    Por debajo del primer punto tabulado Y = 0.4; por encima del último se usa el
    último valor; entre puntos se interpola (la tabla lo permite).
    """
    tipo = tipo_material.upper()
    if tipo not in _TABLA_Y_B31_3:
        raise ValueError(f"tipo_material debe ser uno de {sorted(_TABLA_Y_B31_3)}.")
    xs, ys = _TABLA_Y_B31_3[tipo]
    T = float(temperatura_C)
    Y = ys[0] if T <= xs[0] else ys[-1] if T >= xs[-1] else interpolar_lineal(xs, ys, T)
    return _resultado(
        entradas={"temperatura_C": T, "tipo_material": tipo},
        ecuacion_texto="Y = f(T, material) según tabla; interpolación lineal entre columnas",
        referencia_normativa="ASME B31.3-2022, Tabla 304.1.1",
        resultado=Y,
        unidad="adimensional",
    )


def espesor_requerido_tuberia(P: float, D: float, S: float, E: float,
                              W: float = 1.0, Y: float = 0.4) -> Dict[str, Any]:
    """Espesor de diseño por presión interna de un tramo recto (ASME B31.3).

    Ecuación (3a) de §304.1.2:   t = P·D / [2·(S·E·W + P·Y)]

    Parámetros
    ----------
    P : presión interna de diseño [MPa]
    D : diámetro exterior [mm]
    S : esfuerzo admisible a la temperatura de diseño [MPa] (Tabla A-1M)
    E : factor de calidad longitudinal (Tabla A-1A / A-1B), 0 < E ≤ 1
    W : factor de reducción de resistencia de la soldadura (§302.3.5(e)), 0 < W ≤ 1
    Y : coeficiente de Tabla 304.1.1

    Notas
    -----
    * El resultado ``t`` NO incluye sobreespesor por corrosión ni tolerancia de
      fabricación; ver ``evaluar_espesores_tuberia``.
    * Válida para t < D/6. Si t ≥ D/6 o P/(S·E) > 0.385, §304.1.2(b) exige
      consideraciones especiales (alerta FUERA_DE_ALCANCE).
    """
    P = _positivo("P [MPa]", P)
    D = _positivo("D [mm]", D)
    S = _positivo("S [MPa]", S)
    E = _fraccion("E", E)
    W = _fraccion("W", W)
    if not (0.0 <= Y <= 0.7):
        raise ValueError("Y debe estar entre 0 y 0.7 (Tabla 304.1.1).")
    t = P * D / (2.0 * (S * E * W + P * Y))
    obs = ["Espesor de presión sin CA ni tolerancia de fabricación."]
    alertas: List[str] = []
    if t >= D / 6.0 or P / (S * E) > 0.385:
        alertas.append(ALERTA_FUERA_DE_ALCANCE)
        obs.append("t ≥ D/6 o P/(S·E) > 0.385: fuera del alcance de Ec. (3a); "
                   "§304.1.2(b) requiere consideraciones especiales.")
    return _resultado(
        entradas={"P_MPa": P, "D_mm": D, "S_MPa": S, "E": E, "W": W, "Y": Y},
        ecuacion_texto="t = P·D / [2·(S·E·W + P·Y)]",
        referencia_normativa="ASME B31.3-2022, §304.1.2, Ec. (3a)",
        resultado=t,
        unidad="mm",
        observaciones=obs,
        alertas=alertas,
    )


def presion_maxima_tuberia(t: float, D: float, S: float, E: float,
                           W: float = 1.0, Y: float = 0.4) -> Dict[str, Any]:
    """Presión interna máxima admisible para un espesor dado (Ec. 3a despejada).

    P = 2·t·S·E·W / (D − 2·t·Y). Útil para evaluar el espesor medido (API 570
    §7.3 / re-rating), usando el espesor remanente descontada la pérdida prevista.
    """
    t = _positivo("t [mm]", t)
    D = _positivo("D [mm]", D)
    S = _positivo("S [MPa]", S)
    E = _fraccion("E", E)
    W = _fraccion("W", W)
    denominador = D - 2.0 * t * Y
    if denominador <= 0:
        raise ValueError("D − 2·t·Y ≤ 0: geometría fuera del alcance de la ecuación.")
    P = 2.0 * t * S * E * W / denominador
    return _resultado(
        entradas={"t_mm": t, "D_mm": D, "S_MPa": S, "E": E, "W": W, "Y": Y},
        ecuacion_texto="P = 2·t·S·E·W / (D − 2·t·Y)",
        referencia_normativa="ASME B31.3-2022, §304.1.2, Ec. (3a) despejada para P; API 570 §7.3",
        resultado=P,
        unidad="MPa",
    )


def espesor_alerta(t_min: float, cr_gov: Optional[float],
                   dt_margen_anios: float = CRITERIOS_GRUPO["dt_margen_anios"],
                   margen_min_mm: float = CRITERIOS_GRUPO["margen_min_mm"]) -> Dict[str, Any]:
    """Espesor de alerta (criterio del grupo, común a las tres familias).

        t_alerta = t_min + max(CR_gov · Δt_margen, margen_min)

    Justificación: con la velocidad de corrosión gobernante, un punto que llega
    a ``t_alerta`` alcanzará ``t_min`` en ``Δt_margen`` años, que es el plazo
    estimado para planificar y ejecutar la intervención. Equivale a declarar
    ALERTA cuando la vida remanente RL ≤ Δt_margen.

    Si CR_gov es ``None`` o ≤ 0 se usa solo ``margen_min``.
    """
    t_min = _positivo("t_min [mm]", t_min)
    dt_margen_anios = _no_negativo("Δt_margen [años]", dt_margen_anios)
    margen_min_mm = _no_negativo("margen_min [mm]", margen_min_mm)
    obs = [f"Δt_margen = {dt_margen_anios} años: plazo de intervención declarado por el grupo."]
    if cr_gov is None or cr_gov <= 0:
        margen = margen_min_mm
        obs.append("CR_gov no disponible o ≤ 0: el margen por pérdida prevista es nulo; "
                   "se aplica solo el margen mínimo declarado.")
    else:
        margen = max(cr_gov * dt_margen_anios, margen_min_mm)
    return _resultado(
        entradas={"t_min_mm": t_min, "CR_gov_mm_anio": cr_gov,
                  "dt_margen_anios": dt_margen_anios, "margen_min_mm": margen_min_mm},
        ecuacion_texto="t_alerta = t_min + max(CR_gov·Δt_margen, margen_min)",
        referencia_normativa="Criterio del grupo (no normativo), coherente con el uso de "
                             "CR_gov y RL de API 510 §7.1 / API 570 §7.1 / API 653 §4.3",
        resultado=t_min + margen,
        unidad="mm",
        observaciones=obs,
    )


def evaluar_espesores_tuberia(P: float, D: float, S: float, E: float, t_nom: float,
                              CA: float, W: float = 1.0, Y: float = 0.4,
                              tolerancia_fabricacion: float = 0.125,
                              t_estructural: float = 0.0,
                              cr_gov: Optional[float] = None,
                              dt_margen_anios: float = CRITERIOS_GRUPO["dt_margen_anios"],
                              margen_min_mm: float = CRITERIOS_GRUPO["margen_min_mm"]) -> Dict[str, Any]:
    """Cuadro completo de espesores de un tramo recto (B31.3 diseño + API 570 servicio).

    Distingue:

    * ``t_presion``         — Ec. (3a) B31.3 §304.1.2 (sin CA ni tolerancia).
    * ``t_m``               — espesor mínimo de diseño = t_presion + CA (§304.1.1, Ec. 2).
    * ``t_nom_requerido``   — nominal mínimo a comprar: t_m / (1 − tol). La tolerancia
      de fabricación (p. ej. −12.5 % en tubo sin costura ASTM A106) implica que el
      tubo puede llegar con t_nom·(1 − tol).
    * ``t_fab_min``         — espesor mínimo garantizado de fábrica = t_nom·(1 − tol).
    * ``t_min``             — espesor mínimo requerido en servicio (API 570 "required
      thickness") = max(t_presion, t_estructural). No incluye CA: el CA es
      precisamente el metal que se consume en servicio.
    * ``t_alerta``          — ver ``espesor_alerta``.

    Parámetros adicionales
    ----------------------
    t_nom : espesor nominal (cédula) [mm]
    CA : sobreespesor por corrosión de diseño [mm]
    tolerancia_fabricacion : fracción (0.125 = 12.5 %)
    t_estructural : espesor mínimo estructural (API 574) [mm], 0 si no se declara.
    """
    t_nom = _positivo("t_nom [mm]", t_nom)
    CA = _no_negativo("CA [mm]", CA)
    tol = _fraccion("tolerancia_fabricacion", tolerancia_fabricacion, incluir_cero=True)
    if tol >= 1:
        raise ValueError("tolerancia_fabricacion debe ser < 1.")
    t_estructural = _no_negativo("t_estructural [mm]", t_estructural)

    r_p = espesor_requerido_tuberia(P, D, S, E, W, Y)
    t_p = r_p["resultado"]
    t_m = t_p + CA
    t_nom_req = t_m / (1.0 - tol)
    t_fab_min = t_nom * (1.0 - tol)
    t_min = max(t_p, t_estructural)
    gobierna_tmin = "ESTRUCTURAL (API 574)" if t_estructural > t_p else "PRESION (B31.3 Ec. 3a)"
    r_a = espesor_alerta(t_min, cr_gov, dt_margen_anios, margen_min_mm)

    alertas = list(r_p["alertas"])
    obs = [
        "t_m = t_presion + CA corresponde al espesor mínimo de diseño de §304.1.1.",
        f"La tolerancia de fabricación ({tol*100:.1f} %) se descuenta del nominal: "
        f"t_fab_min = {t_fab_min:.3f} mm.",
        f"t_min en servicio gobernado por: {gobierna_tmin}.",
    ]
    if t_fab_min < t_m:
        alertas.append(ALERTA_NOMINAL_INSUFICIENTE)
        obs.append(f"t_nom·(1 − tol) = {t_fab_min:.3f} mm < t_m = {t_m:.3f} mm: el nominal "
                   f"no cumple el diseño; se requiere t_nom ≥ {t_nom_req:.3f} mm.")
    return _resultado(
        entradas={"P_MPa": P, "D_mm": D, "S_MPa": S, "E": E, "W": W, "Y": Y,
                  "t_nom_mm": t_nom, "CA_mm": CA, "tolerancia_fabricacion": tol,
                  "t_estructural_mm": t_estructural, "CR_gov_mm_anio": cr_gov,
                  "dt_margen_anios": dt_margen_anios},
        ecuacion_texto=("t_presion = P·D/[2(S·E·W + P·Y)];  t_m = t_presion + CA;  "
                        "t_nom,req = t_m/(1 − tol);  t_min = max(t_presion, t_estructural);  "
                        "t_alerta = t_min + CR_gov·Δt_margen"),
        referencia_normativa=("ASME B31.3-2022 §304.1.1 Ec. (2) y §304.1.2 Ec. (3a); "
                              "API 570 4.ª ed. §7.1 (espesor requerido); API 574 (t estructural)"),
        resultado={
            "t_presion": t_p,
            "t_m": t_m,
            "t_nom": t_nom,
            "t_nom_requerido": t_nom_req,
            "t_fab_min": t_fab_min,
            "t_min": t_min,
            "t_alerta": r_a["resultado"],
            "cumple_nominal": t_fab_min >= t_m,
        },
        unidad={"t_presion": "mm", "t_m": "mm", "t_nom": "mm", "t_nom_requerido": "mm",
                "t_fab_min": "mm", "t_min": "mm", "t_alerta": "mm", "cumple_nominal": "bool"},
        observaciones=obs + r_a["observaciones"],
        alertas=alertas,
        detalle={"presion": r_p, "alerta": r_a},
    )


# =============================================================================
# 3. RECIPIENTES A PRESIÓN — ASME VIII Div. 1 + II-D (diseño) / API 510 (servicio)
#    Geometría: envolvente cilíndrica, esfuerzo circunferencial.
# =============================================================================

UG16_ESPESOR_MINIMO_MM = 1.5  # UG-16(b): 1/16 in (1.5 mm) sin incluir CA


def espesor_requerido_envolvente(P: float, R: float, S: float, E: float) -> Dict[str, Any]:
    """Espesor requerido de envolvente cilíndrica por esfuerzo circunferencial.

    ASME VIII Div. 1, UG-27(c)(1):   t = P·R / (S·E − 0.6·P)

    Parámetros
    ----------
    P : presión interna de diseño [MPa]
    R : radio INTERIOR en condición corroída [mm]
    S : esfuerzo admisible a la temperatura de diseño (ASME II-D Tabla 1A) [MPa]
    E : eficiencia de junta (UW-12), 0 < E ≤ 1

    Validez: t ≤ R/2 y P ≤ 0.385·S·E; fuera de ese rango aplican las ecuaciones
    del Apéndice Obligatorio 1-2 (alerta FUERA_DE_ALCANCE).
    """
    P = _positivo("P [MPa]", P)
    R = _positivo("R [mm]", R)
    S = _positivo("S [MPa]", S)
    E = _fraccion("E", E)
    denominador = S * E - 0.6 * P
    if denominador <= 0:
        raise ValueError("S·E − 0.6·P ≤ 0: presión excesiva para la ecuación UG-27(c)(1).")
    t = P * R / denominador
    alertas: List[str] = []
    obs = ["Resultado sin CA. R debe ser el radio interior en condición corroída (R_int + CA)."]
    if P > 0.385 * S * E or t > R / 2.0:
        alertas.append(ALERTA_FUERA_DE_ALCANCE)
        obs.append("P > 0.385·S·E o t > R/2: usar Apéndice Obligatorio 1-2.")
    return _resultado(
        entradas={"P_MPa": P, "R_mm": R, "S_MPa": S, "E": E},
        ecuacion_texto="t = P·R / (S·E − 0.6·P)",
        referencia_normativa="ASME BPVC Sec. VIII Div. 1-2023, UG-27(c)(1)",
        resultado=t,
        unidad="mm",
        observaciones=obs,
        alertas=alertas,
    )


def presion_maxima_envolvente(t: float, R: float, S: float, E: float) -> Dict[str, Any]:
    """MAWP de envolvente cilíndrica: P = S·E·t / (R + 0.6·t)  (UG-27(c)(1) despejada)."""
    t = _positivo("t [mm]", t)
    R = _positivo("R [mm]", R)
    S = _positivo("S [MPa]", S)
    E = _fraccion("E", E)
    P = S * E * t / (R + 0.6 * t)
    return _resultado(
        entradas={"t_mm": t, "R_mm": R, "S_MPa": S, "E": E},
        ecuacion_texto="P = S·E·t / (R + 0.6·t)",
        referencia_normativa="ASME BPVC Sec. VIII Div. 1-2023, UG-27(c)(1); API 510 §7.3 (re-rating)",
        resultado=P,
        unidad="MPa",
    )


def evaluar_espesores_recipiente(P: float, R_int: float, S: float, E: float, t_nom: float,
                                 CA: float, tolerancia_placa_mm: float = 0.0,
                                 cr_gov: Optional[float] = None,
                                 dt_margen_anios: float = CRITERIOS_GRUPO["dt_margen_anios"],
                                 margen_min_mm: float = CRITERIOS_GRUPO["margen_min_mm"]) -> Dict[str, Any]:
    """Cuadro completo de espesores de una envolvente cilíndrica (VIII-1 + API 510).

    * ``t_req``    — UG-27(c)(1) con R = R_int + CA (condición corroída), con
      mínimo UG-16(b) de 1.5 mm.
    * ``t_diseno`` — t_req + CA (espesor mínimo a especificar).
    * ``t_fab_min``— t_nom − tolerancia de placa. UG-16(c) permite ignorar una
      tolerancia negativa ≤ min(0.25 mm, 6 % t_nom).
    * ``t_min``    — espesor requerido en servicio (API 510 §7.1) = t_req.
      Simplificación declarada: se evalúa con R corroído de diseño (conservador).
    * ``t_alerta`` — ver ``espesor_alerta``.

    ``S`` puede obtenerse con ``esfuerzo_admisible(material_id, T)``.
    """
    R_int = _positivo("R_int [mm]", R_int)
    t_nom = _positivo("t_nom [mm]", t_nom)
    CA = _no_negativo("CA [mm]", CA)
    tol = _no_negativo("tolerancia_placa [mm]", tolerancia_placa_mm)
    R_corr = R_int + CA
    r_t = espesor_requerido_envolvente(P, R_corr, S, E)
    t_req_calc = r_t["resultado"]
    t_req = max(t_req_calc, UG16_ESPESOR_MINIMO_MM)
    t_diseno = t_req + CA
    tol_ignorables = min(0.25, 0.06 * t_nom)
    tol_efectiva = 0.0 if tol <= tol_ignorables else tol
    t_fab_min = t_nom - tol_efectiva
    r_a = espesor_alerta(t_req, cr_gov, dt_margen_anios, margen_min_mm)

    alertas = list(r_t["alertas"])
    obs = [f"R corroído = R_int + CA = {R_corr:.2f} mm.",
           f"Tolerancia de placa ignorable por UG-16(c): ≤ {tol_ignorables:.3f} mm."]
    if t_req_calc < UG16_ESPESOR_MINIMO_MM:
        obs.append("Gobierna el espesor mínimo UG-16(b) = 1.5 mm.")
    if t_fab_min < t_diseno:
        alertas.append(ALERTA_NOMINAL_INSUFICIENTE)
        obs.append(f"t_nom − tol = {t_fab_min:.3f} mm < t_req + CA = {t_diseno:.3f} mm.")
    # MAWP de la envolvente nueva en condición corroída (t disponible = t_fab_min − CA)
    mawp_nuevo = (presion_maxima_envolvente(t_fab_min - CA, R_corr, S, E)["resultado"]
                  if t_fab_min - CA > 0 else None)
    return _resultado(
        entradas={"P_MPa": P, "R_int_mm": R_int, "S_MPa": S, "E": E, "t_nom_mm": t_nom,
                  "CA_mm": CA, "tolerancia_placa_mm": tol, "CR_gov_mm_anio": cr_gov,
                  "dt_margen_anios": dt_margen_anios},
        ecuacion_texto=("t_req = max[P·(R_int + CA)/(S·E − 0.6·P), 1.5 mm];  t_diseno = t_req + CA;  "
                        "t_min = t_req;  t_alerta = t_min + CR_gov·Δt_margen;  "
                        "MAWP = S·E·t/(R + 0.6·t)"),
        referencia_normativa=("ASME VIII Div. 1-2023 UG-16(b)(c), UG-27(c)(1); "
                              "ASME II-D-2023 Tabla 1A; API 510 11.ª ed. §7.1"),
        resultado={"t_req": t_req, "t_diseno": t_diseno, "t_nom": t_nom, "t_fab_min": t_fab_min,
                   "t_min": t_req, "t_alerta": r_a["resultado"],
                   "MAWP_nuevo_corroido": mawp_nuevo, "cumple_nominal": t_fab_min >= t_diseno},
        unidad={"t_req": "mm", "t_diseno": "mm", "t_nom": "mm", "t_fab_min": "mm", "t_min": "mm",
                "t_alerta": "mm", "MAWP_nuevo_corroido": "MPa", "cumple_nominal": "bool"},
        observaciones=obs + r_a["observaciones"],
        alertas=alertas,
        detalle={"ug27": r_t, "alerta": r_a},
    )


# =============================================================================
# 4. TANQUES ATMOSFÉRICOS — API 650 (diseño) / API 653 (servicio)
#    Alcance: virolas del manto. Fondo y techo: solo se listan datos pendientes.
# =============================================================================

ALCANCE_TANQUE = ("Alcance: virolas del manto (método de 1 pie, API 650 §5.6.3; "
                  "evaluación en servicio API 653 §4.3.3). No cubre fondo, techo, "
                  "boquillas ni unión manto-fondo.")

DATOS_PENDIENTES_TANQUE: Tuple[str, ...] = (
    "Fondo: espesor mínimo remanente (MRT) y velocidades de corrosión del lado producto y "
    "del lado suelo — API 653 §4.4 y §6.4 (intervalo de inspección interna).",
    "Fondo: existencia de barrera de prevención de liberación (RPB), revestimiento interno o "
    "protección catódica — modifican el intervalo interno (API 653 §6.4).",
    "Fondo: mediciones de asentamiento (planitud y borde) — API 653 Anexo B.",
    "Techo: espesor promedio de planchas, estructura, sellos y drenajes — API 653 §4.2.",
    "Placa anular / soldadura manto-fondo y boquillas del manto — API 653 §4.3 y §4.4.",
    "Fecha, efectividad y hallazgos de la última inspección interna (fuera de servicio).",
)


def espesor_constructivo_minimo_api650(D: float) -> Dict[str, Any]:
    """Espesor nominal mínimo de virola por diámetro (API 650 §5.6.1.1).

    D < 15 m → 5 mm;  15 ≤ D < 36 m → 6 mm;  36 ≤ D ≤ 60 m → 8 mm;  D > 60 m → 10 mm.
    """
    D = _positivo("D [m]", D)
    t = 5.0 if D < 15 else 6.0 if D < 36 else 8.0 if D <= 60 else 10.0
    return _resultado(
        entradas={"D_m": D},
        ecuacion_texto="t_const = f(D) según tabla",
        referencia_normativa="API 650 13.ª ed., §5.6.1.1",
        resultado=t,
        unidad="mm",
    )


def espesor_virola_api650(D: float, H: float, G: float, Sd: float, St: float,
                          CA: float = 0.0, E: float = 1.0) -> Dict[str, Any]:
    """Espesor de virola por el método de 1 pie (API 650 §5.6.3.2, unidades SI).

        t_d = 4.9·D·(H − 0.3)·G / (S_d·E) + CA
        t_t = 4.9·D·(H − 0.3) / (S_t·E)
        t_requerido = max(t_d, t_t, t_constructivo)

    Parámetros
    ----------
    D  : diámetro nominal del tanque [m] (línea media de la virola inferior)
    H  : nivel de diseño del líquido medido desde el fondo de la virola evaluada [m]
    G  : densidad relativa de diseño del líquido (agua = 1.0)
    Sd : esfuerzo admisible de diseño (Tabla 5-2a) [MPa]
    St : esfuerzo admisible de prueba hidrostática (Tabla 5-2a) [MPa]
    CA : sobreespesor por corrosión [mm]
    E  : eficiencia de junta. En API 650 cuerpo principal E = 1 (implícito);
         E < 1 corresponde al Anexo A o a evaluación API 653 (Tabla 4.2).

    El método de 1 pie no se permite para D > 61 m (§5.6.3.1): alerta FUERA_DE_ALCANCE.
    """
    D = _positivo("D [m]", D)
    H = _positivo("H [m]", H)
    G = _positivo("G", G)
    Sd = _positivo("Sd [MPa]", Sd)
    St = _positivo("St [MPa]", St)
    CA = _no_negativo("CA [mm]", CA)
    E = _fraccion("E", E)
    if H <= 0.3:
        raise ValueError("H debe ser > 0.3 m para el método de 1 pie.")
    td = 4.9 * D * (H - 0.3) * G / (Sd * E) + CA
    tt = 4.9 * D * (H - 0.3) / (St * E)
    t_const = espesor_constructivo_minimo_api650(D)["resultado"]
    t_req = max(td, tt, t_const)
    gobierna = "t_d (diseño)" if t_req == td else "t_t (prueba hidrostática)" if t_req == tt \
        else "t constructivo §5.6.1.1"
    alertas: List[str] = []
    obs = [ALCANCE_TANQUE, f"Gobierna: {gobierna}.",
           "t_t no incluye CA ni G (prueba con agua)."]
    if D > 61.0:
        alertas.append(ALERTA_FUERA_DE_ALCANCE)
        obs.append("D > 61 m: API 650 §5.6.3.1 no permite el método de 1 pie (usar punto variable).")
    if E < 1.0:
        obs.append("E < 1: formulación propia del Anexo A / evaluación API 653, no del cuerpo de API 650.")
    return _resultado(
        entradas={"D_m": D, "H_m": H, "G": G, "Sd_MPa": Sd, "St_MPa": St, "CA_mm": CA, "E": E},
        ecuacion_texto=("t_d = 4.9·D·(H − 0.3)·G/(S_d·E) + CA;  t_t = 4.9·D·(H − 0.3)/(S_t·E);  "
                        "t = max(t_d, t_t, t_const)"),
        referencia_normativa="API 650 13.ª ed., §5.6.1.1, §5.6.3.1 y §5.6.3.2 (SI); Tabla 5-2a",
        resultado={"t_d": td, "t_t": tt, "t_constructivo": t_const, "t_requerido": t_req},
        unidad={"t_d": "mm", "t_t": "mm", "t_constructivo": "mm", "t_requerido": "mm"},
        observaciones=obs,
        alertas=alertas,
    )


def esfuerzo_admisible_api653(Y: float, T: float, numero_virola: int = 1) -> Dict[str, Any]:
    """Esfuerzo admisible de producto para evaluación en servicio (API 653 Tabla 4.1).

    Virolas 1 y 2 (las dos inferiores):  S = min(0.80·Y, 0.429·T)
    Virolas superiores:                  S = min(0.88·Y, 0.472·T)
    """
    Y = _positivo("Y (fluencia) [MPa]", Y)
    T = _positivo("T (tracción) [MPa]", T)
    if int(numero_virola) < 1:
        raise ValueError("numero_virola se cuenta desde 1 (virola inferior).")
    inferior = int(numero_virola) <= 2
    S = min(0.80 * Y, 0.429 * T) if inferior else min(0.88 * Y, 0.472 * T)
    return _resultado(
        entradas={"Y_MPa": Y, "T_MPa": T, "numero_virola": int(numero_virola)},
        ecuacion_texto="S = min(0.80·Y, 0.429·T) [virolas 1-2];  S = min(0.88·Y, 0.472·T) [superiores]",
        referencia_normativa="API 653 5.ª ed., Tabla 4.1 (esfuerzo de producto)",
        resultado=S,
        unidad="MPa",
    )


def espesor_minimo_virola_api653(D: float, H: float, G: float, S: float,
                                 E: float = 1.0) -> Dict[str, Any]:
    """Espesor mínimo aceptable en servicio de una virola completa (API 653 §4.3.3.1, SI).

        t_min = 4.9·D·(H − 0.3)·G / (S·E),   con t_min ≥ 2.5 mm

    ``S`` según ``esfuerzo_admisible_api653``; ``E`` según API 653 Tabla 4.2
    (1.0 para plancha alejada de soldaduras o soldaduras radiografiadas).
    Para áreas localmente adelgazadas H se mide desde el borde inferior del área
    evaluada (no implementado: alcance de virola completa).
    """
    D = _positivo("D [m]", D)
    H = _positivo("H [m]", H)
    G = _positivo("G", G)
    S = _positivo("S [MPa]", S)
    E = _fraccion("E", E)
    if H <= 0.3:
        raise ValueError("H debe ser > 0.3 m.")
    t_calc = 4.9 * D * (H - 0.3) * G / (S * E)
    t_min = max(t_calc, 2.5)
    obs = [ALCANCE_TANQUE]
    if t_calc < 2.5:
        obs.append("Gobierna el mínimo absoluto de 2.5 mm (API 653 §4.3.3.1).")
    return _resultado(
        entradas={"D_m": D, "H_m": H, "G": G, "S_MPa": S, "E": E},
        ecuacion_texto="t_min = max[4.9·D·(H − 0.3)·G/(S·E), 2.5 mm]",
        referencia_normativa="API 653 5.ª ed., §4.3.3.1 (SI), Tablas 4.1 y 4.2",
        resultado=t_min,
        unidad="mm",
        observaciones=obs,
    )


def evaluar_espesores_virola(D: float, H: float, G: float, material_id: str,
                             t_nom: float, CA: float, numero_virola: int = 1,
                             E_diseno: float = 1.0, E_servicio: float = 1.0,
                             cr_gov: Optional[float] = None,
                             dt_margen_anios: float = CRITERIOS_GRUPO["dt_margen_anios"],
                             margen_min_mm: float = CRITERIOS_GRUPO["margen_min_mm"],
                             catalogo: Optional[Mapping[str, Mapping[str, Any]]] = None) -> Dict[str, Any]:
    """Cuadro completo de espesores de una virola (API 650 diseño + API 653 servicio).

    * ``t_d``, ``t_t``, ``t_requerido`` — API 650 §5.6.3.2.
    * ``t_min`` — mínimo en servicio API 653 §4.3.3.1 (sin CA).
    * ``t_alerta`` — ver ``espesor_alerta``.
    Incluye la declaración de alcance y la lista de datos pendientes (fondo/techo).
    """
    cat = catalogo if catalogo is not None else MATERIALES_TANQUE
    if material_id not in cat:
        raise ValueError(f"Material {material_id!r} no está en el catálogo de tanques: {sorted(cat)}.")
    m = cat[material_id]
    t_nom = _positivo("t_nom [mm]", t_nom)
    r650 = espesor_virola_api650(D, H, G, m["Sd_MPa"], m["St_MPa"], CA, E_diseno)
    rS = esfuerzo_admisible_api653(m["smys_MPa"], m["smts_MPa"], numero_virola)
    r653 = espesor_minimo_virola_api653(D, H, G, rS["resultado"], E_servicio)
    t_min = r653["resultado"]
    r_a = espesor_alerta(t_min, cr_gov, dt_margen_anios, margen_min_mm)
    alertas = list(r650["alertas"])
    obs = [ALCANCE_TANQUE, f"Material: {m['descripcion']} ({m['norma_tabla']}).",
           m["estado_verificacion"]]
    if t_nom < r650["resultado"]["t_requerido"]:
        alertas.append(ALERTA_NOMINAL_INSUFICIENTE)
        obs.append("t_nom < t requerido por API 650.")
    return _resultado(
        entradas={"D_m": D, "H_m": H, "G": G, "material_id": material_id, "t_nom_mm": t_nom,
                  "CA_mm": CA, "numero_virola": numero_virola, "E_diseno": E_diseno,
                  "E_servicio": E_servicio, "CR_gov_mm_anio": cr_gov},
        ecuacion_texto=r650["ecuacion_texto"] + ";  " + r653["ecuacion_texto"] +
                       ";  t_alerta = t_min + CR_gov·Δt_margen",
        referencia_normativa=r650["referencia_normativa"] + "; " + r653["referencia_normativa"],
        resultado={**r650["resultado"], "t_nom": t_nom, "S_servicio": rS["resultado"],
                   "t_min": t_min, "t_alerta": r_a["resultado"]},
        unidad={"t_d": "mm", "t_t": "mm", "t_constructivo": "mm", "t_requerido": "mm",
                "t_nom": "mm", "S_servicio": "MPa", "t_min": "mm", "t_alerta": "mm"},
        observaciones=obs + r_a["observaciones"],
        alertas=alertas,
        detalle={"api650": r650, "esfuerzo_api653": rS, "api653": r653, "alerta": r_a,
                 "datos_pendientes": list(DATOS_PENDIENTES_TANQUE)},
    )


# =============================================================================
# 5. VELOCIDAD DE CORROSIÓN, VIDA REMANENTE Y VALIDACIÓN DE DATOS (común)
# =============================================================================

def preparar_serie_espesores(mediciones: Iterable[Mapping[str, Any]],
                             fecha_evaluacion: Any = None,
                             intervenciones: Optional[Iterable[Mapping[str, Any]]] = None) -> Dict[str, Any]:
    """Valida, normaliza y recorta la serie de espesores a la línea base comparable.

    Cada medición es un mapping con:
        ``fecha`` (date | 'AAAA-MM-DD'), ``espesor`` (float), ``unidad`` ('mm'|'in',
        defecto 'mm'), ``valida`` (bool, defecto True), ``evento`` (NORMAL |
        CAMBIO_PUNTO | REPARACION | REEMPLAZO, defecto NORMAL), ``id`` opcional.
    Cada intervención: ``fecha`` y ``tipo`` (CAMBIO_PUNTO | REPARACION | REEMPLAZO).

    Reglas
    ------
    1. Se excluyen mediciones marcadas no válidas o con espesor ≤ 0.
    2. Mediciones con fecha posterior a ``fecha_evaluacion`` → excluidas y alerta
       FECHAS_INCONSISTENTES.
    3. Línea base comparable: la última fecha entre (a) mediciones con evento de
       reinicio y (b) intervenciones registradas ≤ fecha de evaluación. Las
       mediciones anteriores quedan en el historial pero no se comparan
       (alerta LINEA_BASE_REINICIADA). Una medición con evento de reinicio es la
       primera de la nueva serie.
    4. Dos mediciones comparables con la misma fecha → FECHAS_INCONSISTENTES.
    5. Menos de 2 mediciones comparables → DATOS_INSUFICIENTES.
    """
    f_eval = a_fecha(fecha_evaluacion) if fecha_evaluacion is not None else date.today()
    normalizadas: List[Dict[str, Any]] = []
    excluidas: List[Dict[str, Any]] = []
    alertas: List[str] = []
    obs: List[str] = []

    for i, m in enumerate(mediciones):
        try:
            f = a_fecha(m["fecha"])
            t = a_mm(float(m["espesor"]), m.get("unidad", "mm"))
        except (KeyError, TypeError, ValueError) as exc:
            excluidas.append({"indice": i, "id": m.get("id") if hasattr(m, "get") else None,
                              "motivo": f"DATO_ILEGIBLE: {exc}"})
            continue
        evento = str(m.get("evento", EVENTO_NORMAL) or EVENTO_NORMAL).upper()
        if evento not in EVENTOS_MEDICION:
            raise ValueError(f"Evento de medición no reconocido: {evento!r}.")
        reg = {"indice": i, "id": m.get("id"), "fecha": f, "espesor_mm": t, "evento": evento}
        if not m.get("valida", True):
            excluidas.append({**reg, "motivo": "MARCADA_NO_VALIDA"})
        elif t <= 0:
            excluidas.append({**reg, "motivo": "ESPESOR_NO_POSITIVO"})
        elif f > f_eval:
            excluidas.append({**reg, "motivo": "FECHA_POSTERIOR_A_EVALUACION"})
            alertas.append(ALERTA_FECHAS_INCONSISTENTES)
            obs.append(f"Medición del {f.isoformat()} posterior a la fecha de evaluación "
                       f"{f_eval.isoformat()}: excluida.")
        else:
            normalizadas.append(reg)

    normalizadas.sort(key=lambda r: (r["fecha"], r["indice"]))

    # Línea base comparable
    fechas_reinicio = [r["fecha"] for r in normalizadas if r["evento"] in EVENTOS_REINICIO]
    for iv in intervenciones or []:
        tipo = str(iv.get("tipo", "")).upper()
        f_iv = a_fecha(iv["fecha"])
        if tipo in EVENTOS_REINICIO and f_iv <= f_eval:
            fechas_reinicio.append(f_iv)
    fecha_base = max(fechas_reinicio) if fechas_reinicio else None

    serie: List[Dict[str, Any]] = []
    for r in normalizadas:
        if fecha_base is not None and r["fecha"] < fecha_base:
            excluidas.append({**r, "motivo": "ANTERIOR_A_LINEA_BASE"})
        else:
            serie.append(r)
    if fecha_base is not None:
        alertas.append(ALERTA_LINEA_BASE_REINICIADA)
        obs.append(f"Línea base comparable reiniciada el {fecha_base.isoformat()} "
                   "(cambio de punto, reparación o reemplazo).")

    for a, b in zip(serie, serie[1:]):
        if (b["fecha"] - a["fecha"]).days <= 0:
            alertas.append(ALERTA_FECHAS_INCONSISTENTES)
            obs.append(f"Mediciones repetidas en la fecha {b['fecha'].isoformat()} (Δt = 0).")
    if len(serie) < 2:
        alertas.append(ALERTA_DATOS_INSUFICIENTES)
        obs.append(f"Solo {len(serie)} medición(es) comparable(s): se requieren ≥ 2 para CR.")

    return _resultado(
        entradas={"n_mediciones": len(normalizadas) + len(excluidas),
                  "fecha_evaluacion": f_eval.isoformat()},
        ecuacion_texto="Serie comparable = mediciones válidas con fecha ≥ última intervención",
        referencia_normativa="API 570 §7.1 / API 510 §7.1 / API 653 §4.3 (datos comparables)",
        resultado={"serie": serie, "excluidas": excluidas,
                   "fecha_linea_base": fecha_base, "n_comparables": len(serie)},
        unidad={"espesor_mm": "mm"},
        observaciones=obs,
        alertas=alertas,
    )


def velocidades_corrosion(serie: Sequence[Mapping[str, Any]],
                          cr_minima: Optional[float] = None) -> Dict[str, Any]:
    """Velocidades de corrosión de largo y corto plazo y la gobernante.

        CR_LT = (t_inicial − t_último) / Δt(inicial → último)
        CR_ST = (t_penúltimo − t_último) / Δt(penúltimo → último)
        CR_gov = max(CR_LT, CR_ST)

    ``serie``: lista ordenada por fecha con claves ``fecha`` y ``espesor_mm``
    (salida de ``preparar_serie_espesores``).

    Criterio de CR_gov: API 510/570 piden adoptar la tasa que mejor represente el
    proceso actual. Se adopta el máximo por ser conservador: si el proceso se
    aceleró, CR_ST lo refleja; si hubo un período inicial más agresivo, CR_LT.
    Con solo dos mediciones CR_LT = CR_ST.

    ``cr_minima`` (opcional, mm/año): valor mínimo de diseño a usar cuando la
    CR medida es nula o negativa (p. ej. similar servicio). Si no se entrega,
    ``cr_para_calculo`` queda en ``None`` y RL es indeterminada.
    """
    alertas: List[str] = []
    obs: List[str] = []
    cr_lt = cr_st = None
    n = len(serie)
    if n < 2:
        alertas.append(ALERTA_DATOS_INSUFICIENTES)
        obs.append("Menos de 2 mediciones comparables: CR no determinable.")
    else:
        t0, f0 = serie[0]["espesor_mm"], serie[0]["fecha"]
        tp, fp = serie[-2]["espesor_mm"], serie[-2]["fecha"]
        tu, fu = serie[-1]["espesor_mm"], serie[-1]["fecha"]
        dt_lt = anios_entre(f0, fu)
        dt_st = anios_entre(fp, fu)
        if dt_lt > 0:
            cr_lt = (t0 - tu) / dt_lt
        else:
            alertas.append(ALERTA_FECHAS_INCONSISTENTES)
            obs.append("Δt de largo plazo ≤ 0: CR_LT no determinable.")
        if dt_st > 0:
            cr_st = (tp - tu) / dt_st
        else:
            alertas.append(ALERTA_FECHAS_INCONSISTENTES)
            obs.append("Δt de corto plazo ≤ 0: CR_ST no determinable.")
        if n == 2:
            obs.append("Con 2 mediciones, CR_LT y CR_ST usan el mismo par (son iguales).")

    disponibles = [c for c in (cr_lt, cr_st) if c is not None]
    cr_gov = max(disponibles) if disponibles else None
    criterio = "No determinable"
    if cr_gov is not None:
        criterio = ("CR_gov = max(CR_LT, CR_ST): criterio conservador; "
                    + ("gobierna CR_ST (proceso reciente más agresivo)."
                       if cr_st is not None and cr_gov == cr_st and cr_st != cr_lt
                       else "gobierna CR_LT."))
    for nombre, c in (("CR_LT", cr_lt), ("CR_ST", cr_st)):
        if c is not None and c <= 0:
            alertas.append(ALERTA_CORROSION_NULA_O_NEGATIVA)
            obs.append(f"{nombre} = {c:.4f} mm/año ≤ 0: sin pérdida medible o dispersión de "
                       "medición (verificar técnica, calibración y ubicación exacta del punto).")

    cr_calc = cr_gov if (cr_gov is not None and cr_gov > 0) else None
    if cr_calc is None and cr_gov is not None and cr_minima is not None and cr_minima > 0:
        cr_calc = float(cr_minima)
        obs.append(f"Se adopta CR mínima declarada = {cr_minima} mm/año para RL e intervalo.")
    return _resultado(
        entradas={"n_comparables": n, "cr_minima": cr_minima},
        ecuacion_texto=("CR_LT = (t_inicial − t_último)/Δt;  CR_ST = (t_penúltimo − t_último)/Δt;  "
                        "CR_gov = max(CR_LT, CR_ST)"),
        referencia_normativa="API 570 4.ª ed. §7.1.1; API 510 11.ª ed. §7.1.1; API 653 §4.3 / §6.3.3",
        resultado={"cr_lt": cr_lt, "cr_st": cr_st, "cr_gov": cr_gov,
                   "cr_para_calculo": cr_calc, "criterio": criterio},
        unidad={"cr_lt": "mm/año", "cr_st": "mm/año", "cr_gov": "mm/año",
                "cr_para_calculo": "mm/año", "criterio": "texto"},
        observaciones=obs,
        alertas=alertas,
    )


def vida_remanente(t_actual: float, t_min: float, cr: Optional[float]) -> Dict[str, Any]:
    """Vida remanente RL = (t_actual − t_min) / CR_gov.

    * t_actual < t_min → RL = 0 y alerta BAJO_MINIMO.
    * CR ``None`` o ≤ 0 → RL indeterminada (``None``) con alerta.
    """
    t_actual = _positivo("t_actual [mm]", t_actual)
    t_min = _positivo("t_min [mm]", t_min)
    alertas: List[str] = []
    obs: List[str] = []
    if t_actual < t_min:
        rl: Optional[float] = 0.0
        alertas.append(ALERTA_BAJO_MINIMO)
        obs.append("t_actual < t_min: requiere evaluación de aptitud para el servicio "
                   "(API 579-1/ASME FFS-1), reparación, re-rating o retiro.")
    elif cr is None:
        rl = None
        alertas.append(ALERTA_DATOS_INSUFICIENTES)
        obs.append("CR no determinada: RL indeterminada.")
    elif cr <= 0:
        rl = None
        alertas.append(ALERTA_CORROSION_NULA_O_NEGATIVA)
        obs.append("CR ≤ 0: RL no acotada por corrosión (gobiernan intervalos máximos).")
    else:
        rl = (t_actual - t_min) / cr
    return _resultado(
        entradas={"t_actual_mm": t_actual, "t_min_mm": t_min, "CR_mm_anio": cr},
        ecuacion_texto="RL = (t_actual − t_min) / CR_gov",
        referencia_normativa="API 570 §7.2.1; API 510 §7.2.1; API 653 §4.3 (RCA/N)",
        resultado=rl,
        unidad="años",
        observaciones=obs,
        alertas=alertas,
    )


# --- 5.1 Intervalos de próxima inspección -------------------------------------

# API 570 4.ª ed., Tabla 1 (intervalos máximos recomendados, años). Configurable.
INTERVALOS_MAX_API570: Dict[Any, Dict[str, Optional[float]]] = {
    1: {"espesor": 5.0, "visual_externa": 5.0},
    2: {"espesor": 10.0, "visual_externa": 5.0},
    3: {"espesor": 10.0, "visual_externa": 10.0},
    "PUNTO_INYECCION": {"espesor": 3.0, "visual_externa": None},  # visual: según clase
}

REGLA_RL4_CONSERVADORA = "CONSERVADORA_1_4"   # min(RL/4, 2 años) — criterio solicitado
REGLA_RL4_API_TEXTUAL = "API_TEXTUAL"          # min(RL, 2 años) — texto API 510 §6.5.1.1


def _aplicar_regla_rl_menor_4(rl: float, regla: Optional[str]) -> Tuple[Optional[float], str]:
    if regla is None:
        return None, ""
    if regla == REGLA_RL4_CONSERVADORA:
        return min(rl / 4.0, 2.0), ("RL < 4 años: intervalo = min(RL/4, 2 años) — criterio "
                                    "conservador del grupo, más restrictivo que el texto de "
                                    "API 510 §6.5.1.1.")
    if regla == REGLA_RL4_API_TEXTUAL:
        return min(rl, 2.0), ("RL < 4 años: intervalo = vida remanente completa con máximo de "
                              "2 años (API 510 §6.5.1.1).")
    raise ValueError(f"Regla RL<4 no reconocida: {regla!r}.")


def intervalo_inspeccion_api570(rl: Optional[float], clase: Any = 2,
                                cr_conocida: bool = True,
                                intervalos_max: Optional[Mapping[Any, Mapping[str, Optional[float]]]] = None,
                                regla_rl_menor_4: Optional[str] = None,
                                intervalo_cr_desconocida: float = CRITERIOS_GRUPO["intervalo_cr_desconocida_anios"]
                                ) -> Dict[str, Any]:
    """Intervalo de medición de espesores (y visual externa) para tuberías (API 570).

        intervalo_espesor = min(RL/2, intervalo máximo de la clase)   (§6.3.3, Tabla 1)

    * ``clase``: 1, 2, 3 o 'PUNTO_INYECCION' (clave de ``intervalos_max``).
    * ``regla_rl_menor_4``: ``None`` (por defecto, regla solicitada: solo
      min(RL/2, máx. clase)), o una de ``REGLA_RL4_*`` para el tratamiento de RL < 4.
    * RL = 0 (bajo mínimo) → intervalo 0 (acción inmediata).
    * RL ``None`` con CR conocida ≤ 0 → gobierna el máximo de la clase.
    * CR desconocida → ``intervalo_cr_desconocida`` (criterio del grupo) acotado por la clase.
    """
    tabla = intervalos_max if intervalos_max is not None else INTERVALOS_MAX_API570
    if clase not in tabla:
        raise ValueError(f"Clase de tubería {clase!r} no definida en la tabla: {list(tabla)}.")
    i_max = tabla[clase]["espesor"]
    i_vis = tabla[clase].get("visual_externa")
    if i_max is None:
        raise ValueError("Intervalo máximo de espesor no definido para la clase (Clase 4: "
                         "definir por el propietario-usuario).")
    obs: List[str] = []
    alertas: List[str] = []
    if rl is not None and rl <= 0:
        intervalo, criterio = 0.0, "BAJO_MINIMO: acción inmediata (FFS / reparación / reemplazo)."
        alertas.append(ALERTA_BAJO_MINIMO)
    elif not cr_conocida:
        intervalo = min(intervalo_cr_desconocida, i_max)
        criterio = (f"CR desconocida: intervalo = min({intervalo_cr_desconocida}, máx. clase) — "
                    "criterio del grupo para establecer la tasa.")
        alertas.append(ALERTA_DATOS_INSUFICIENTES)
    elif rl is None:
        intervalo, criterio = i_max, f"CR ≤ 0: gobierna el máximo de la Clase {clase} ({i_max} años)."
    else:
        mitad = rl / 2.0
        intervalo, criterio = (mitad, "Gobierna RL/2.") if mitad < i_max else \
            (i_max, f"Gobierna el máximo de la Clase {clase} ({i_max} años).")
        if rl < 4.0 and regla_rl_menor_4 is not None:
            alt, txt = _aplicar_regla_rl_menor_4(rl, regla_rl_menor_4)
            intervalo, criterio = min(alt, i_max), txt
    visual = None if i_vis is None else i_vis
    if visual is None:
        obs.append("Visual externa del punto de inyección: según la clase del circuito.")
    return _resultado(
        entradas={"RL_anios": rl, "clase": clase, "cr_conocida": cr_conocida,
                  "regla_rl_menor_4": regla_rl_menor_4, "intervalo_max_clase": i_max},
        ecuacion_texto="I_espesor = min(RL/2, I_max,clase);  I_visual = I_max,visual,clase",
        referencia_normativa="API 570 4.ª ed., §6.3.3 y Tabla 1 (intervalos máximos por clase)",
        resultado={"intervalo_espesor": intervalo, "intervalo_visual_externa": visual,
                   "criterio_gobernante": criterio, "tipo_inspeccion": "MEDICION_ESPESOR"},
        unidad={"intervalo_espesor": "años", "intervalo_visual_externa": "años",
                "criterio_gobernante": "texto", "tipo_inspeccion": "texto"},
        observaciones=obs + ["Tabla de intervalos máximos configurable; verificar con la edición declarada."],
        alertas=alertas,
    )


def intervalo_inspeccion_api510(rl: Optional[float], cr_conocida: bool = True,
                                regla_rl_menor_4: Optional[str] = REGLA_RL4_CONSERVADORA,
                                intervalo_max: float = 10.0,
                                intervalo_cr_desconocida: float = CRITERIOS_GRUPO["intervalo_cr_desconocida_anios"]
                                ) -> Dict[str, Any]:
    """Intervalo de inspección interna / en servicio (espesores) para recipientes (API 510).

        RL ≥ 4 años:  I = min(RL/2, 10 años)                       (§6.5.1.1)
        RL < 4 años:  I = min(RL/4, 2 años)   [CONSERVADORA_1_4 — por defecto, solicitado]
                      I = min(RL, 2 años)     [API_TEXTUAL — texto de §6.5.1.1]
        Visual externa: I_ext = min(5 años, I)                     (§6.4.1)

    Nota del especialista: el texto de API 510 §6.5.1.1 indica que con RL < 4
    años el intervalo *puede* ser la vida remanente completa hasta 2 años. La
    regla por defecto (RL/4) es más restrictiva y queda declarada como criterio
    del grupo; se puede cambiar con ``regla_rl_menor_4``.
    """
    obs: List[str] = []
    alertas: List[str] = []
    if rl is not None and rl <= 0:
        intervalo, criterio = 0.0, "BAJO_MINIMO: acción inmediata (FFS API 579 / reparación / re-rating)."
        alertas.append(ALERTA_BAJO_MINIMO)
    elif not cr_conocida:
        intervalo = min(intervalo_cr_desconocida, intervalo_max)
        criterio = (f"CR desconocida: intervalo = {intervalo} años — criterio del grupo para "
                    "establecer la tasa.")
        alertas.append(ALERTA_DATOS_INSUFICIENTES)
    elif rl is None:
        intervalo, criterio = intervalo_max, f"CR ≤ 0: gobierna el máximo de {intervalo_max} años."
    elif rl < 4.0:
        intervalo, criterio = _aplicar_regla_rl_menor_4(rl, regla_rl_menor_4 or REGLA_RL4_API_TEXTUAL)
    else:
        mitad = rl / 2.0
        intervalo, criterio = (mitad, "Gobierna RL/2.") if mitad < intervalo_max else \
            (intervalo_max, f"Gobierna el máximo de {intervalo_max} años.")
    visual = min(5.0, intervalo) if intervalo > 0 else 0.0
    if regla_rl_menor_4 == REGLA_RL4_CONSERVADORA:
        obs.append("Regla RL<4 configurada como CONSERVADORA_1_4 (criterio del grupo; "
                   "API 510 §6.5.1.1 permite min(RL, 2 años)).")
    return _resultado(
        entradas={"RL_anios": rl, "cr_conocida": cr_conocida,
                  "regla_rl_menor_4": regla_rl_menor_4, "intervalo_max": intervalo_max},
        ecuacion_texto=("RL ≥ 4: I = min(RL/2, 10);  RL < 4: I = min(RL/4, 2) [conservadora] "
                        "o min(RL, 2) [API];  I_ext = min(5, I)"),
        referencia_normativa="API 510 11.ª ed., §6.4.1 (externa) y §6.5.1.1 (interna/en servicio)",
        resultado={"intervalo_espesor": intervalo, "intervalo_visual_externa": visual,
                   "criterio_gobernante": criterio,
                   "tipo_inspeccion": "INTERNA_O_EN_SERVICIO (MEDICION_ESPESOR)"},
        unidad={"intervalo_espesor": "años", "intervalo_visual_externa": "años",
                "criterio_gobernante": "texto", "tipo_inspeccion": "texto"},
        observaciones=obs,
        alertas=alertas,
    )


def intervalos_inspeccion_api653_manto(t_actual: float, t_min: float,
                                       cr: Optional[float]) -> Dict[str, Any]:
    """Intervalos de inspección del manto de tanques (API 653 §6.3).

        RCA = t_actual − t_min ;  N = CR del manto [mm/año]
        UT externa del manto:  CR desconocida → 5 años
                               CR conocida    → min(RCA/(2N), 15 años)     (§6.3.3.2)
        Visual externa (inspector autorizado): min(RCA/(4N), 5 años)        (§6.3.2.1)
        Rutinaria en servicio (operador): ≤ 1 mes                           (§6.3.1.2)

    Con N ≤ 0 (sin pérdida medible) gobiernan los máximos (15 y 5 años).
    Alcance limitado al manto; los datos pendientes de fondo y techo se listan
    en ``detalle['datos_pendientes']``.
    """
    t_actual = _positivo("t_actual [mm]", t_actual)
    t_min = _positivo("t_min [mm]", t_min)
    rca = t_actual - t_min
    alertas: List[str] = []
    obs = [ALCANCE_TANQUE]
    if rca < 0:
        ut, vis = 0.0, 0.0
        crit = "BAJO_MINIMO: RCA < 0, acción inmediata (evaluación API 653 §4.3 / reparación)."
        alertas.append(ALERTA_BAJO_MINIMO)
    elif cr is None:
        ut, vis = 5.0, 5.0
        crit = "CR desconocida: UT del manto a 5 años (API 653 §6.3.3.2)."
        alertas.append(ALERTA_DATOS_INSUFICIENTES)
    elif cr <= 0:
        ut, vis = 15.0, 5.0
        crit = "CR ≤ 0: gobiernan los máximos (UT 15 años; visual externa 5 años)."
        alertas.append(ALERTA_CORROSION_NULA_O_NEGATIVA)
    else:
        ut_rl = rca / (2.0 * cr)
        vis_rl = rca / (4.0 * cr)
        ut = min(ut_rl, 15.0)
        vis = min(vis_rl, 5.0)
        crit = "UT: gobierna RCA/(2N)." if ut_rl < 15.0 else "UT: gobierna el máximo de 15 años."
        crit += " Visual: gobierna RCA/(4N)." if vis_rl < 5.0 else " Visual: gobierna el máximo de 5 años."
    return _resultado(
        entradas={"t_actual_mm": t_actual, "t_min_mm": t_min, "N_mm_anio": cr},
        ecuacion_texto=("RCA = t_actual − t_min;  I_UT = 5 (N desconocida) o min(RCA/2N, 15);  "
                        "I_visual = min(RCA/4N, 5);  rutinaria ≤ 1 mes"),
        referencia_normativa="API 653 5.ª ed., §6.3.1.2, §6.3.2.1 y §6.3.3.2",
        resultado={"RCA": rca, "intervalo_espesor": ut, "intervalo_visual_externa": vis,
                   "intervalo_rutinaria": 1.0 / 12.0, "criterio_gobernante": crit,
                   "tipo_inspeccion": "UT_EXTERNA_MANTO"},
        unidad={"RCA": "mm", "intervalo_espesor": "años", "intervalo_visual_externa": "años",
                "intervalo_rutinaria": "años", "criterio_gobernante": "texto",
                "tipo_inspeccion": "texto"},
        observaciones=obs,
        alertas=alertas,
        detalle={"datos_pendientes": list(DATOS_PENDIENTES_TANQUE)},
    )


# --- 5.2 Clasificación de condición -------------------------------------------

def clasificar_estado(t_actual: Optional[float], t_min: float, t_alerta: float,
                      fecha_proxima: Any, fecha_evaluacion: Any) -> Dict[str, Any]:
    """Clasifica la condición de un punto, por severidad decreciente:

    1. BAJO_MINIMO         — t_actual < t_min.
    2. INSPECCION_VENCIDA  — fecha_evaluacion > fecha_proxima (o sin línea base).
    3. ALERTA              — t_min ≤ t_actual ≤ t_alerta (equivale a RL ≤ Δt_margen).
    4. NORMAL              — en otro caso.
    """
    f_eval = a_fecha(fecha_evaluacion)
    f_prox = a_fecha(fecha_proxima) if fecha_proxima is not None else None
    if t_actual is not None and t_actual < t_min:
        estado, just = ESTADO_BAJO_MINIMO, f"t_actual = {t_actual:.3f} mm < t_min = {t_min:.3f} mm."
    elif f_prox is None:
        estado, just = ESTADO_INSPECCION_VENCIDA, "Sin medición de línea base: inspección requerida."
    elif f_eval > f_prox:
        estado, just = ESTADO_INSPECCION_VENCIDA, (f"Fecha de evaluación {f_eval.isoformat()} posterior "
                                                   f"a la próxima inspección {f_prox.isoformat()}.")
    elif t_actual is not None and t_actual <= t_alerta:
        estado, just = ESTADO_ALERTA, (f"t_min ≤ t_actual = {t_actual:.3f} mm ≤ "
                                       f"t_alerta = {t_alerta:.3f} mm.")
    else:
        estado, just = ESTADO_NORMAL, "Espesor sobre t_alerta e inspección vigente."
    return _resultado(
        entradas={"t_actual_mm": t_actual, "t_min_mm": t_min, "t_alerta_mm": t_alerta,
                  "fecha_proxima": f_prox.isoformat() if f_prox else None,
                  "fecha_evaluacion": f_eval.isoformat()},
        ecuacion_texto=("BAJO_MINIMO si t < t_min; INSPECCION_VENCIDA si f_eval > f_próx; "
                        "ALERTA si t ≤ t_alerta; NORMAL en otro caso"),
        referencia_normativa="Criterio del grupo basado en t_min (API 510/570/653) y fecha de próxima inspección",
        resultado=estado,
        unidad="categoría",
        observaciones=[just],
        alertas=[ALERTA_BAJO_MINIMO] if estado == ESTADO_BAJO_MINIMO else [],
    )


# --- 5.3 Evaluación integrada de un CML/TML -----------------------------------

def evaluar_punto_espesor(familia: str, mediciones: Iterable[Mapping[str, Any]], t_min: float,
                          fecha_evaluacion: Any, *,
                          intervenciones: Optional[Iterable[Mapping[str, Any]]] = None,
                          dt_margen_anios: float = CRITERIOS_GRUPO["dt_margen_anios"],
                          margen_min_mm: float = CRITERIOS_GRUPO["margen_min_mm"],
                          cr_minima: Optional[float] = None,
                          clase_tuberia: Any = 2,
                          intervalos_api570: Optional[Mapping[Any, Mapping[str, Optional[float]]]] = None,
                          regla_rl_menor_4: Optional[str] = "POR_DEFECTO",
                          intervalo_cr_desconocida: float = CRITERIOS_GRUPO["intervalo_cr_desconocida_anios"]
                          ) -> Dict[str, Any]:
    """Evaluación completa de un CML/TML: serie → CR → RL → intervalo → estado.

    Parámetros
    ----------
    familia : 'TUBERIA' | 'RECIPIENTE' | 'TANQUE'
    mediciones : ver ``preparar_serie_espesores``
    t_min : espesor mínimo requerido en servicio del componente [mm]
    fecha_evaluacion : fecha "hoy" del análisis
    regla_rl_menor_4 : 'POR_DEFECTO' usa None para API 570 y CONSERVADORA_1_4
        para API 510; o un valor explícito (None | REGLA_RL4_*).

    La fecha de referencia de la próxima inspección es la fecha de la última
    medición comparable. Sin mediciones comparables el punto queda como
    INSPECCION_VENCIDA (se requiere línea base).
    """
    if familia not in FAMILIAS:
        raise ValueError(f"familia debe ser una de {FAMILIAS}.")
    t_min = _positivo("t_min [mm]", t_min)
    f_eval = a_fecha(fecha_evaluacion)
    alertas: List[str] = []
    obs: List[str] = []

    r_serie = preparar_serie_espesores(mediciones, f_eval, intervenciones)
    serie = r_serie["resultado"]["serie"]
    alertas += r_serie["alertas"]
    obs += r_serie["observaciones"]

    r_cr = velocidades_corrosion(serie, cr_minima)
    alertas += r_cr["alertas"]
    obs += [o for o in r_cr["observaciones"] if o not in obs]
    cr_gov = r_cr["resultado"]["cr_gov"]
    cr_calc = r_cr["resultado"]["cr_para_calculo"]
    cr_conocida = cr_gov is not None

    r_alerta = espesor_alerta(t_min, cr_calc, dt_margen_anios, margen_min_mm)
    t_alerta = r_alerta["resultado"]

    ultima = serie[-1] if serie else None
    t_ult = ultima["espesor_mm"] if ultima else None
    f_ult = ultima["fecha"] if ultima else None

    # Con CR medida ≤ 0 se pasa la CR medida (RL no acotada), no None (que significa "sin datos").
    cr_rl = cr_calc if cr_calc is not None else cr_gov
    r_rl = vida_remanente(t_ult, t_min, cr_rl) if t_ult is not None else None
    rl = r_rl["resultado"] if r_rl else None
    if r_rl:
        alertas += r_rl["alertas"]

    # Intervalo según la familia
    if familia == FAMILIA_TUBERIA:
        regla = None if regla_rl_menor_4 == "POR_DEFECTO" else regla_rl_menor_4
        r_int = intervalo_inspeccion_api570(rl, clase_tuberia, cr_conocida, intervalos_api570,
                                            regla, intervalo_cr_desconocida)
    elif familia == FAMILIA_RECIPIENTE:
        regla = REGLA_RL4_CONSERVADORA if regla_rl_menor_4 == "POR_DEFECTO" else regla_rl_menor_4
        r_int = intervalo_inspeccion_api510(rl, cr_conocida, regla,
                                            intervalo_cr_desconocida=intervalo_cr_desconocida)
    else:
        # CR para API 653: la de cálculo si es positiva; si la CR medida es ≤ 0 se
        # pasa tal cual (gobiernan máximos); si no hay CR, None (5 años).
        cr_653 = cr_calc if cr_calc is not None else (cr_gov if cr_conocida else None)
        r_int = intervalos_inspeccion_api653_manto(t_ult, t_min, cr_653) \
            if t_ult is not None else None

    if r_int is not None:
        alertas += r_int["alertas"]
        intervalo = r_int["resultado"]["intervalo_espesor"]
        criterio = r_int["resultado"]["criterio_gobernante"]
        tipo = r_int["resultado"]["tipo_inspeccion"]
    else:
        intervalo, criterio, tipo = 0.0, "Sin línea base: medición inmediata.", "MEDICION_ESPESOR"
    f_prox = sumar_anios(f_ult, intervalo) if f_ult is not None else None

    r_estado = clasificar_estado(t_ult, t_min, t_alerta, f_prox, f_eval)
    estado = r_estado["resultado"]
    alertas += r_estado["alertas"]
    obs += r_estado["observaciones"]

    # Proyección del espesor a la fecha de evaluación
    t_proy = None
    if t_ult is not None and cr_calc is not None:
        t_proy = t_ult - cr_calc * max(anios_entre(f_ult, f_eval), 0.0)
        if t_proy < t_min <= t_ult:
            alertas.append(ALERTA_PROYECCION_BAJO_MINIMO)
            obs.append(f"Espesor proyectado a {f_eval.isoformat()} = {t_proy:.3f} mm < t_min: "
                       "medir con prioridad.")

    referencia = {FAMILIA_TUBERIA: "API 570 4.ª ed. §6.3, §7.1, §7.2",
                  FAMILIA_RECIPIENTE: "API 510 11.ª ed. §6.4, §6.5, §7.1, §7.2",
                  FAMILIA_TANQUE: "API 653 5.ª ed. §4.3.3, §6.3"}[familia]
    return _resultado(
        entradas={"familia": familia, "t_min_mm": t_min, "fecha_evaluacion": f_eval.isoformat(),
                  "dt_margen_anios": dt_margen_anios, "clase_tuberia": clase_tuberia,
                  "regla_rl_menor_4": regla_rl_menor_4, "cr_minima": cr_minima},
        ecuacion_texto=("CR_gov = max(CR_LT, CR_ST);  RL = (t_último − t_min)/CR_gov;  "
                        "t_alerta = t_min + CR_gov·Δt_margen;  f_próx = f_última + I"),
        referencia_normativa=referencia,
        resultado={
            "t_ultimo": t_ult,
            "fecha_ultima": f_ult,
            "cr_lt": r_cr["resultado"]["cr_lt"],
            "cr_st": r_cr["resultado"]["cr_st"],
            "cr_gov": cr_gov,
            "cr_para_calculo": cr_calc,
            "t_min": t_min,
            "t_alerta": t_alerta,
            "vida_remanente": rl,
            "intervalo": intervalo,
            "fecha_proxima": f_prox,
            "tipo_inspeccion": tipo,
            "criterio_gobernante": criterio,
            "estado": estado,
            "t_proyectado_a_fecha_evaluacion": t_proy,
        },
        unidad={"t_ultimo": "mm", "fecha_ultima": "fecha", "cr_lt": "mm/año", "cr_st": "mm/año",
                "cr_gov": "mm/año", "cr_para_calculo": "mm/año", "t_min": "mm", "t_alerta": "mm",
                "vida_remanente": "años", "intervalo": "años", "fecha_proxima": "fecha",
                "tipo_inspeccion": "texto", "criterio_gobernante": "texto", "estado": "categoría",
                "t_proyectado_a_fecha_evaluacion": "mm"},
        observaciones=obs,
        alertas=alertas,
        detalle={"serie": r_serie, "corrosion": r_cr, "alerta": r_alerta, "vida_remanente": r_rl,
                 "intervalo": r_int, "estado": r_estado},
    )


# =============================================================================
# 6. RBI SIMPLIFICADO — ADELGAZAMIENTO GENERALIZADO (API RP 580 / API RP 581)
# =============================================================================
# Modelo académico simplificado. Proceso según API RP 580; cálculo cuantitativo
# según la formulación de confiabilidad estructural con actualización bayesiana
# del factor de daño por adelgazamiento de API RP 581 3.ª ed., Parte 2, §4.
# Simplificaciones declaradas:
#   * A_rt = CR_gov·edad/t_ref (t_ref = t_nom o espesor de la última inspección
#     confiable t_rdi, con edad medida desde esa fecha).
#   * Factores de ajuste (F_IP, F_DL, F_WD, F_AM, F_SM, F_OM) agrupados en uno
#     solo, por defecto 1.0.
#   * Solo adelgazamiento generalizado; no se combinan otros mecanismos.
#   * Las consecuencias C_A y C_E son datos de entrada (no se modela la liberación).

NOTA_INSPECCION_RBI = (
    "La inspección reduce la incertidumbre estadística sobre el estado de daño real "
    "(actualiza las probabilidades de los estados de daño y, con ello, D_f), pero NO "
    "recupera el espesor físico perdido: A_rt no cambia por inspeccionar. Solo una "
    "reparación, reemplazo o mitigación de la corrosión reduce el daño."
)

# Probabilidades previas de los 3 estados de daño según confianza en la CR.
PROB_PREVIAS_581: Dict[str, Tuple[float, float, float]] = {
    "BAJA": (0.50, 0.30, 0.20),   # CR de literatura o sin mediciones propias
    "MEDIA": (0.70, 0.20, 0.10),  # CR de servicio similar o pocas mediciones
    "ALTA": (0.80, 0.15, 0.05),   # CR medida con historial suficiente
}
# Probabilidades condicionales por efectividad de inspección (estado 1, 2, 3).
PROB_CONDICIONALES_581: Dict[str, Tuple[float, float, float]] = {
    "A": (0.90, 0.09, 0.01),
    "B": (0.70, 0.20, 0.10),
    "C": (0.50, 0.30, 0.20),
    "D": (0.40, 0.33, 0.27),
    "E": (0.33, 0.33, 0.33),
}
ESTADOS_DANO_581: Tuple[float, float, float] = (1.0, 2.0, 4.0)  # D_S1, D_S2, D_S3
COV_DT_581 = 0.20   # COV del adelgazamiento
COV_SF_581 = 0.20   # COV de la resistencia al flujo
COV_P_581 = 0.05    # COV de la presión
NORMALIZACION_DF_581 = 1.56e-4
DF_MINIMO_581 = 0.1

# Frecuencias genéricas de falla totales (suma de los 4 tamaños de agujero) [1/año].
GFF_TOTAL_581: Dict[str, float] = {
    "TUBERIA": 3.06e-5,
    "RECIPIENTE": 3.06e-5,
    "TANQUE_VIROLA": 1.0e-4,
    "TANQUE_FONDO": 7.2e-4,
}

# Categorías de probabilidad (API RP 581 Parte 1, tabla de categorías) [1/año].
LIMITES_CATEGORIA_PROBABILIDAD: Tuple[float, float, float, float] = (3.06e-5, 3.06e-4, 3.06e-3, 3.06e-2)
# Categorías de consecuencia por área [m²] (A..E).
LIMITES_CONSECUENCIA_AREA_M2: Tuple[float, float, float, float] = (9.29, 92.9, 929.0, 9290.0)
# Categorías de consecuencia financiera [USD] (A..E).
LIMITES_CONSECUENCIA_USD: Tuple[float, float, float, float] = (1.0e4, 1.0e5, 1.0e6, 1.0e7)

CATEGORIAS_CONSECUENCIA = ("A", "B", "C", "D", "E")

# Matriz de riesgo 5×5 (criterio del grupo con la forma de la matriz de API RP 581
# Parte 1). Filas: categoría de probabilidad 1..5; columnas: consecuencia A..E.
MATRIZ_RIESGO_5X5: Dict[int, Tuple[str, str, str, str, str]] = {
    5: ("MEDIO", "MEDIO_ALTO", "ALTO", "ALTO", "ALTO"),
    4: ("MEDIO", "MEDIO", "MEDIO_ALTO", "ALTO", "ALTO"),
    3: ("BAJO", "MEDIO", "MEDIO", "MEDIO_ALTO", "ALTO"),
    2: ("BAJO", "BAJO", "MEDIO", "MEDIO", "MEDIO_ALTO"),
    1: ("BAJO", "BAJO", "BAJO", "MEDIO", "MEDIO_ALTO"),
}
PRIORIDAD_POR_RIESGO: Dict[str, Tuple[int, str]] = {
    "ALTO": (1, "Prioridad 1: inspección de efectividad A/B a la brevedad y evaluar mitigación."),
    "MEDIO_ALTO": (2, "Prioridad 2: programar inspección de efectividad ≥ B en el próximo ciclo."),
    "MEDIO": (3, "Prioridad 3: mantener plan; inspección de efectividad ≥ C según intervalo."),
    "BAJO": (4, "Prioridad 4: plan de rutina según intervalos normativos."),
}
_ORDEN_RIESGO = ("BAJO", "MEDIO", "MEDIO_ALTO", "ALTO")


def _phi(x: float) -> float:
    """Función de distribución normal estándar acumulada Φ(x)."""
    return 0.5 * math.erfc(-x / math.sqrt(2.0))


def parametro_art(cr_gov: float, edad_anios: float, t_ref: float) -> Dict[str, Any]:
    """Parámetro de pérdida relativa de pared A_rt = CR_gov · edad / t_ref.

    Representa la fracción de pared que se habría perdido con la CR gobernante
    desde la fecha de referencia. ``t_ref`` = t_nom (simplificación académica)
    o t_rdi (espesor de la última inspección confiable, con edad desde esa fecha).
    CR ≤ 0 se trata como 0 (sin adelgazamiento activo).
    """
    edad = _no_negativo("edad [años]", edad_anios)
    t_ref = _positivo("t_ref [mm]", t_ref)
    obs: List[str] = []
    cr = float(cr_gov) if cr_gov is not None else 0.0
    if cr <= 0:
        obs.append("CR ≤ 0 o no disponible: se adopta A_rt = 0.")
        cr = 0.0
    art = cr * edad / t_ref
    if art >= 1.0:
        obs.append("A_rt ≥ 1: pérdida prevista igual o mayor a la pared de referencia.")
    return _resultado(
        entradas={"CR_gov_mm_anio": cr_gov, "edad_anios": edad, "t_ref_mm": t_ref},
        ecuacion_texto="A_rt = CR_gov · edad / t_ref",
        referencia_normativa="API RP 581 3.ª ed., Parte 2, §4 (adelgazamiento) — forma simplificada",
        resultado=art,
        unidad="adimensional",
        observaciones=obs,
    )


def relacion_resistencia(S: float, E: float, YS: float, TS: float,
                         t_min: float, t_ref: float) -> Dict[str, Any]:
    """Relación de resistencia SR_P = (S·E / FS) · t_min / t_ref, con FS = 1.1·E·(YS + TS)/2.

    FS es la resistencia al flujo plástico; SR_P compara el esfuerzo admisible
    con la resistencia al flujo, escalado por el espesor mínimo requerido.
    """
    S = _positivo("S [MPa]", S)
    E = _fraccion("E", E)
    YS = _positivo("YS [MPa]", YS)
    TS = _positivo("TS [MPa]", TS)
    t_min = _positivo("t_min [mm]", t_min)
    t_ref = _positivo("t_ref [mm]", t_ref)
    FS = 1.1 * E * (YS + TS) / 2.0
    sr = (S * E / FS) * (t_min / t_ref)
    return _resultado(
        entradas={"S_MPa": S, "E": E, "YS_MPa": YS, "TS_MPa": TS, "t_min_mm": t_min, "t_ref_mm": t_ref},
        ecuacion_texto="FS = 1.1·E·(YS + TS)/2;  SR_P = (S·E/FS)·(t_min/t_ref)",
        referencia_normativa="API RP 581 3.ª ed., Parte 2, §4 (resistencia al flujo y relación de resistencia)",
        resultado=sr,
        unidad="adimensional",
        detalle={"FS_MPa": FS},
    )


def probabilidades_posteriores(inspecciones: Optional[Mapping[str, int]] = None,
                               confianza: str = "BAJA") -> Dict[str, Any]:
    """Actualización bayesiana de las probabilidades de los 3 estados de daño.

        Po_i = Pr_i · Π_k (Co_i^k)^{N_k} / Σ_j [Pr_j · Π_k (Co_j^k)^{N_k}],   k ∈ {A, B, C, D, E}

    ``inspecciones``: conteo por efectividad, p. ej. {'A': 1, 'B': 2}.
    """
    conf = confianza.upper()
    if conf not in PROB_PREVIAS_581:
        raise ValueError(f"confianza debe ser una de {list(PROB_PREVIAS_581)}.")
    insp = {k.upper(): int(v) for k, v in (inspecciones or {}).items() if int(v) != 0}
    for k, v in insp.items():
        if k not in PROB_CONDICIONALES_581:
            raise ValueError(f"Efectividad {k!r} no reconocida (A, B, C, D, E).")
        if v < 0:
            raise ValueError("El número de inspecciones no puede ser negativo.")
    previas = PROB_PREVIAS_581[conf]
    sin_norm = []
    for i in range(3):
        p = previas[i]
        for k, n in insp.items():
            p *= PROB_CONDICIONALES_581[k][i] ** n
        sin_norm.append(p)
    total = sum(sin_norm)
    post = tuple(p / total for p in sin_norm)
    return _resultado(
        entradas={"inspecciones": insp, "confianza": conf},
        ecuacion_texto="Po_i = Pr_i·Π(Co_i^k)^N_k / Σ_j Pr_j·Π(Co_j^k)^N_k",
        referencia_normativa="API RP 581 3.ª ed., Parte 2, §4 (probabilidades previas y condicionales)",
        resultado=post,
        unidad="probabilidad",
        observaciones=[f"Previas ({conf}): {previas}.", NOTA_INSPECCION_RBI],
    )


def factor_dano_adelgazamiento(art: float, sr_p: float,
                               inspecciones: Optional[Mapping[str, int]] = None,
                               confianza: str = "BAJA",
                               factor_ajuste: float = 1.0) -> Dict[str, Any]:
    """Factor de daño por adelgazamiento generalizado D_f,thin.

        β_i = (1 − D_Si·A_rt − SR_P) /
              √[D_Si²·A_rt²·COV_Δt² + (1 − D_Si·A_rt)²·COV_Sf² + SR_P²·COV_P²]
        D_f,base = [Po_1·Φ(−β_1) + Po_2·Φ(−β_2) + Po_3·Φ(−β_3)] / 1.56·10⁻⁴
        D_f = max(D_f,base · F_ajuste, 0.1)

    con D_S = (1, 2, 4), COV_Δt = 0.20, COV_Sf = 0.20, COV_P = 0.05.

    D_f es un factor ADIMENSIONAL que multiplica a la frecuencia genérica de
    falla; NO es una probabilidad ni una frecuencia. Las inspecciones entran
    solo a través de Po_i (incertidumbre), no a través de A_rt (daño físico).
    """
    art = _no_negativo("A_rt", art)
    sr_p = _no_negativo("SR_P", sr_p)
    factor_ajuste = _positivo("factor_ajuste", factor_ajuste)
    r_post = probabilidades_posteriores(inspecciones, confianza)
    post = r_post["resultado"]
    betas, pfs = [], []
    for ds in ESTADOS_DANO_581:
        num = 1.0 - ds * art - sr_p
        den = math.sqrt((ds * art * COV_DT_581) ** 2 + ((1.0 - ds * art) * COV_SF_581) ** 2
                        + (sr_p * COV_P_581) ** 2)
        beta = num / den if den > 0 else (math.inf if num > 0 else -math.inf)
        betas.append(beta)
        pfs.append(_phi(-beta))
    df_base = sum(p * pf for p, pf in zip(post, pfs)) / NORMALIZACION_DF_581
    df = max(df_base * factor_ajuste, DF_MINIMO_581)
    return _resultado(
        entradas={"A_rt": art, "SR_P": sr_p, "inspecciones": r_post["entradas"]["inspecciones"],
                  "confianza": confianza.upper(), "factor_ajuste": factor_ajuste},
        ecuacion_texto=("β_i = (1 − D_Si·A_rt − SR_P)/√(D_Si²A_rt²COV_Δt² + (1 − D_Si·A_rt)²COV_Sf² + "
                        "SR_P²COV_P²);  D_f = max(ΣPo_i·Φ(−β_i)/1.56E−4 · F_aj, 0.1)"),
        referencia_normativa="API RP 581 3.ª ed., Parte 2, §4 (factor de daño por adelgazamiento)",
        resultado=df,
        unidad="adimensional",
        observaciones=["D_f es un factor de daño (multiplicador de gff), distinto de la frecuencia "
                       "de falla f_F.", NOTA_INSPECCION_RBI,
                       "Modelo académico simplificado: factores de ajuste agrupados en F_aj."],
        detalle={"betas": tuple(betas), "pf_estados": tuple(pfs), "posteriores": post,
                 "df_base": df_base},
    )


def factor_sistema_gestion(puntaje: float) -> Dict[str, Any]:
    """Factor de sistema de gestión F_MS = 10^(−0.02·pscore + 1), pscore = puntaje/1000·100 [%].

    ``puntaje`` de la evaluación de sistema de gestión, 0 a 1000 puntos.
    pscore = 50 % → F_MS = 1.0; 100 % → 0.1; 0 % → 10.
    """
    if not (0 <= puntaje <= 1000):
        raise ValueError("El puntaje del sistema de gestión debe estar entre 0 y 1000.")
    pscore = puntaje / 1000.0 * 100.0
    fms = 10.0 ** (-0.02 * pscore + 1.0)
    return _resultado(
        entradas={"puntaje": puntaje},
        ecuacion_texto="pscore = puntaje/1000·100 %;  F_MS = 10^(−0.02·pscore + 1)",
        referencia_normativa="API RP 581 3.ª ed., Parte 2, §2 (factor de sistema de gestión)",
        resultado=fms,
        unidad="adimensional",
    )


def frecuencia_falla(gff: float, df: float, fms: float = 1.0) -> Dict[str, Any]:
    """Frecuencia anual de falla f_F = gff · D_f · F_MS  [1/año].

    Se informa también la probabilidad equivalente en 1 año, P = 1 − exp(−f_F),
    para dejar explícito el horizonte temporal.
    """
    gff = _positivo("gff [1/año]", gff)
    df = _positivo("D_f", df)
    fms = _positivo("F_MS", fms)
    ff = gff * df * fms
    return _resultado(
        entradas={"gff_1_anio": gff, "D_f": df, "F_MS": fms},
        ecuacion_texto="f_F = gff · D_f · F_MS;  P(1 año) = 1 − exp(−f_F)",
        referencia_normativa="API RP 581 3.ª ed., Parte 2, §2 (frecuencia de falla) y Tabla de gff",
        resultado=ff,
        unidad="1/año",
        observaciones=[f"Probabilidad equivalente en un horizonte de 1 año: {1 - math.exp(-ff):.3e}.",
                       "gff total = suma de los cuatro tamaños de agujero (escenario agregado)."],
    )


def categoria_probabilidad(ff: float,
                           limites: Sequence[float] = LIMITES_CATEGORIA_PROBABILIDAD) -> Dict[str, Any]:
    """Categoría de probabilidad 1–5 a partir de f_F [1/año] (límites decádicos desde 3.06E−5)."""
    ff = _no_negativo("f_F", ff)
    cat = 1 + sum(1 for lim in limites if ff > lim)
    return _resultado(
        entradas={"f_F_1_anio": ff, "limites": tuple(limites)},
        ecuacion_texto="1: f ≤ 3.06E−5; 2: ≤ 3.06E−4; 3: ≤ 3.06E−3; 4: ≤ 3.06E−2; 5: > 3.06E−2",
        referencia_normativa="API RP 581 3.ª ed., Parte 1, categorías de probabilidad",
        resultado=cat,
        unidad="categoría 1–5",
    )


def _categoria_por_limites(valor: float, limites: Sequence[float]) -> str:
    return CATEGORIAS_CONSECUENCIA[sum(1 for lim in limites if valor > lim)]


def categoria_consecuencia_area(CA_m2: float,
                                limites: Sequence[float] = LIMITES_CONSECUENCIA_AREA_M2) -> Dict[str, Any]:
    """Categoría de consecuencia por área A–E (límites 9.29 / 92.9 / 929 / 9290 m²)."""
    CA_m2 = _no_negativo("C_A [m²]", CA_m2)
    return _resultado(
        entradas={"C_A_m2": CA_m2, "limites_m2": tuple(limites)},
        ecuacion_texto="A ≤ 9.29; B ≤ 92.9; C ≤ 929; D ≤ 9290; E > 9290 [m²]",
        referencia_normativa="API RP 581 3.ª ed., Parte 1, categorías de consecuencia (área)",
        resultado=_categoria_por_limites(CA_m2, limites),
        unidad="categoría A–E",
    )


def categoria_consecuencia_economica(CE: float, moneda: str = "USD",
                                     tasa_a_usd: Optional[float] = None,
                                     limites_usd: Sequence[float] = LIMITES_CONSECUENCIA_USD) -> Dict[str, Any]:
    """Categoría de consecuencia económica A–E (límites 1E4 / 1E5 / 1E6 / 1E7 USD).

    Si ``moneda`` ≠ 'USD' se requiere ``tasa_a_usd`` (USD por unidad de moneda,
    p. ej. CLP→USD ≈ 0.00105) para comparar con los límites; la tasa y su fecha
    deben declararse como base de valoración.
    """
    CE = _no_negativo("C_E", CE)
    mon = moneda.upper()
    if mon == "USD":
        ce_usd, obs = CE, []
    else:
        if tasa_a_usd is None or tasa_a_usd <= 0:
            raise ValueError(f"Para moneda {mon} se requiere tasa_a_usd > 0.")
        ce_usd = CE * tasa_a_usd
        obs = [f"C_E convertida con tasa {tasa_a_usd} USD/{mon}: {ce_usd:,.0f} USD."]
    return _resultado(
        entradas={"C_E": CE, "moneda": mon, "tasa_a_usd": tasa_a_usd, "limites_usd": tuple(limites_usd)},
        ecuacion_texto="A ≤ 1E4; B ≤ 1E5; C ≤ 1E6; D ≤ 1E7; E > 1E7 [USD]",
        referencia_normativa="API RP 581 3.ª ed., Parte 1, categorías de consecuencia (financiera)",
        resultado=_categoria_por_limites(ce_usd, limites_usd),
        unidad="categoría A–E",
        observaciones=obs,
    )


def nivel_riesgo_matriz(cat_probabilidad: int, cat_consecuencia: str,
                        matriz: Mapping[int, Sequence[str]] = MATRIZ_RIESGO_5X5) -> Dict[str, Any]:
    """Nivel de riesgo y prioridad de inspección en la matriz 5×5."""
    if cat_probabilidad not in matriz:
        raise ValueError("Categoría de probabilidad debe ser 1–5.")
    if cat_consecuencia not in CATEGORIAS_CONSECUENCIA:
        raise ValueError("Categoría de consecuencia debe ser A–E.")
    nivel = matriz[cat_probabilidad][CATEGORIAS_CONSECUENCIA.index(cat_consecuencia)]
    prioridad, accion = PRIORIDAD_POR_RIESGO[nivel]
    return _resultado(
        entradas={"cat_probabilidad": cat_probabilidad, "cat_consecuencia": cat_consecuencia},
        ecuacion_texto="Nivel = Matriz[probabilidad][consecuencia]",
        referencia_normativa="API RP 580 3.ª ed. (presentación de riesgo); API RP 581 Parte 1 "
                             "(matriz 5×5) — asignación de niveles: criterio del grupo",
        resultado={"nivel": nivel, "prioridad": prioridad, "accion": accion},
        unidad={"nivel": "categoría", "prioridad": "1 (máx.) – 4", "accion": "texto"},
    )


def evaluar_rbi_adelgazamiento(*, cr_gov: float, edad_anios: float, t_ref: float, t_min: float,
                               S: float, E: float, YS: float, TS: float,
                               tipo_componente: str = "RECIPIENTE",
                               gff: Optional[float] = None,
                               inspecciones: Optional[Mapping[str, int]] = None,
                               confianza: str = "BAJA",
                               fms: Optional[float] = None,
                               puntaje_sistema_gestion: Optional[float] = None,
                               factor_ajuste: float = 1.0,
                               CA_m2: float, CE: float, moneda: str = "USD",
                               base_valoracion: str = "",
                               tasa_a_usd: Optional[float] = None,
                               efectividad_propuesta: str = "A",
                               horizonte_plan_anios: Optional[float] = None) -> Dict[str, Any]:
    """Evaluación RBI completa por adelgazamiento generalizado (modelo académico).

    Flujo: A_rt → SR_P → D_f(t) → F_MS → f_F → R_A y R_E → matriz 5×5 → prioridad.

        A_rt = CR_gov·edad/t_ref
        f_F  = gff · D_f(t) · F_MS                      [1/año]
        R_A  = f_F · C_A                                [m²/año]
        R_E  = f_F · C_E                                [moneda/año]

    Base temporal y escenario: f_F es anual y agrega los cuatro tamaños de
    agujero de gff; C_A y C_E deben corresponder al mismo escenario agregado
    (consecuencia ponderada) para que R_A y R_E sean consistentes.

    Además informa el efecto de UNA inspección adicional de efectividad
    ``efectividad_propuesta`` con el mismo A_rt (demuestra que la inspección
    reduce D_f vía incertidumbre sin recuperar espesor) y, opcionalmente, D_f
    proyectado a ``horizonte_plan_anios`` sin nueva inspección.
    """
    tipo = tipo_componente.upper()
    if gff is None:
        if tipo not in GFF_TOTAL_581:
            raise ValueError(f"tipo_componente {tipo!r} sin gff tabulado; entregue gff.")
        gff = GFF_TOTAL_581[tipo]
    if fms is None:
        fms = factor_sistema_gestion(puntaje_sistema_gestion)["resultado"] \
            if puntaje_sistema_gestion is not None else 1.0

    r_art = parametro_art(cr_gov, edad_anios, t_ref)
    art = r_art["resultado"]
    r_sr = relacion_resistencia(S, E, YS, TS, t_min, t_ref)
    sr = r_sr["resultado"]
    r_df = factor_dano_adelgazamiento(art, sr, inspecciones, confianza, factor_ajuste)
    df = r_df["resultado"]
    r_ff = frecuencia_falla(gff, df, fms)
    ff = r_ff["resultado"]

    CA_m2 = _no_negativo("C_A [m²]", CA_m2)
    CE = _no_negativo("C_E", CE)
    RA = ff * CA_m2
    RE = ff * CE

    r_cp = categoria_probabilidad(ff)
    r_ca = categoria_consecuencia_area(CA_m2)
    r_ce = categoria_consecuencia_economica(CE, moneda, tasa_a_usd)
    cat_p = r_cp["resultado"]
    cat_cons = max(r_ca["resultado"], r_ce["resultado"])  # 'A' < ... < 'E'
    r_m_area = nivel_riesgo_matriz(cat_p, r_ca["resultado"])
    r_m_econ = nivel_riesgo_matriz(cat_p, r_ce["resultado"])
    r_m = nivel_riesgo_matriz(cat_p, cat_cons)

    # Efecto de una inspección adicional (mismo A_rt: no se recupera espesor)
    insp_mas = dict((k.upper(), int(v)) for k, v in (inspecciones or {}).items())
    ef = efectividad_propuesta.upper()
    insp_mas[ef] = insp_mas.get(ef, 0) + 1
    df_mas = factor_dano_adelgazamiento(art, sr, insp_mas, confianza, factor_ajuste)["resultado"]
    efecto = {"efectividad": ef, "A_rt_sin_cambio": art, "D_f_actual": df, "D_f_con_inspeccion": df_mas,
              "f_F_con_inspeccion": gff * df_mas * fms,
              "reduccion_relativa_D_f": (df - df_mas) / df if df > 0 else 0.0}

    proyeccion = None
    if horizonte_plan_anios is not None:
        art_fut = parametro_art(cr_gov, edad_anios + horizonte_plan_anios, t_ref)["resultado"]
        df_fut = factor_dano_adelgazamiento(art_fut, sr, inspecciones, confianza, factor_ajuste)["resultado"]
        ff_fut = gff * df_fut * fms
        proyeccion = {"horizonte_anios": horizonte_plan_anios, "A_rt": art_fut, "D_f": df_fut,
                      "f_F": ff_fut, "R_A": ff_fut * CA_m2, "R_E": ff_fut * CE,
                      "cat_probabilidad": categoria_probabilidad(ff_fut)["resultado"]}

    mon = moneda.upper()
    return _resultado(
        entradas={"cr_gov_mm_anio": cr_gov, "edad_anios": edad_anios, "t_ref_mm": t_ref,
                  "t_min_mm": t_min, "S_MPa": S, "E": E, "YS_MPa": YS, "TS_MPa": TS,
                  "tipo_componente": tipo, "gff_1_anio": gff, "inspecciones": dict(inspecciones or {}),
                  "confianza": confianza.upper(), "F_MS": fms, "factor_ajuste": factor_ajuste,
                  "C_A_m2": CA_m2, "C_E": CE, "moneda": mon, "base_valoracion": base_valoracion,
                  "tasa_a_usd": tasa_a_usd},
        ecuacion_texto=("A_rt = CR·edad/t_ref;  D_f = f(A_rt, SR_P, inspecciones);  "
                        "f_F = gff·D_f·F_MS;  R_A = f_F·C_A;  R_E = f_F·C_E"),
        referencia_normativa=("API RP 580 3.ª ed. (proceso RBI); API RP 581 3.ª ed., Parte 1 (matriz), "
                              "Parte 2 §2 y §4 (POF por adelgazamiento) — modelo académico simplificado"),
        resultado={"A_rt": art, "SR_P": sr, "D_f": df, "gff": gff, "F_MS": fms, "f_F": ff,
                   "P_1_anio": 1.0 - math.exp(-ff), "R_A": RA, "R_E": RE,
                   "cat_probabilidad": cat_p, "cat_consecuencia_area": r_ca["resultado"],
                   "cat_consecuencia_economica": r_ce["resultado"], "cat_consecuencia_global": cat_cons,
                   "nivel_riesgo_area": r_m_area["resultado"]["nivel"],
                   "nivel_riesgo_economico": r_m_econ["resultado"]["nivel"],
                   "nivel_riesgo": r_m["resultado"]["nivel"],
                   "prioridad": r_m["resultado"]["prioridad"],
                   "accion": r_m["resultado"]["accion"],
                   "efecto_inspeccion_adicional": efecto,
                   "proyeccion": proyeccion},
        unidad={"A_rt": "adimensional", "SR_P": "adimensional", "D_f": "adimensional (factor)",
                "gff": "1/año", "F_MS": "adimensional", "f_F": "1/año", "P_1_anio": "probabilidad (1 año)",
                "R_A": "m²/año", "R_E": f"{mon}/año", "cat_probabilidad": "1–5",
                "cat_consecuencia_area": "A–E", "cat_consecuencia_economica": "A–E",
                "cat_consecuencia_global": "A–E", "nivel_riesgo": "categoría", "prioridad": "1–4"},
        observaciones=[
            "Modelo académico simplificado de adelgazamiento generalizado (un solo mecanismo).",
            "D_f (factor de daño, adimensional) ≠ f_F (frecuencia de falla, 1/año).",
            NOTA_INSPECCION_RBI,
            f"Base temporal anual; C_E en {mon}; base de valoración: {base_valoracion or 'no declarada'}.",
            "Consecuencias ingresadas por el usuario; no se modela la liberación ni sus efectos.",
            "La categoría de consecuencia global es la peor entre área y económica.",
        ],
        detalle={"art": r_art, "sr": r_sr, "df": r_df, "ff": r_ff, "cat_probabilidad": r_cp,
                 "cat_area": r_ca, "cat_economica": r_ce, "matriz_area": r_m_area,
                 "matriz_economica": r_m_econ, "matriz_global": r_m},
    )
