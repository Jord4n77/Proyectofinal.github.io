"""
servicios.py — Integración entre el modelo de datos (``models``) y el motor de
cálculo (``calc_engine``).

Esta capa traduce un ``Equipo`` / ``Componente`` / ``CML`` a las entradas
primitivas del motor. No contiene ecuaciones normativas (viven en
``calc_engine``) ni código de interfaz (vivirá en ``web/``). La interfaz solo
debe llamar a estas funciones y mostrar los diccionarios que devuelven.

Funciones principales
---------------------
* ``espesores_componente``  — cuadro t_nom / t_req / t_min / t_alerta del componente.
* ``evaluar_cml``           — serie → CR → RL → próxima inspección → estado.
* ``evaluar_equipo``        — todos los CML del equipo y su estado peor.
* ``evaluar_rbi_equipo``    — RBI por adelgazamiento con la CR del CML de referencia.
* ``evaluar_proyecto``      — filas del panel de resultados (filtrables).
"""

from __future__ import annotations

from datetime import date
from typing import Any, Dict, List, Optional, Tuple

import calc_engine as ce
from models import CML, Componente, Equipo, Familia, Proyecto

ORDEN_SEVERIDAD = ce.ESTADOS  # NORMAL < ALERTA < INSPECCION_VENCIDA < BAJO_MINIMO


def estado_peor(estados: List[str]) -> Optional[str]:
    """Estado más severo de una lista (None si la lista está vacía)."""
    return max(estados, key=ORDEN_SEVERIDAD.index) if estados else None


def _catalogo(familia: Familia) -> Dict[str, Dict[str, Any]]:
    return {Familia.TUBERIA: ce.MATERIALES_TUBERIA,
            Familia.RECIPIENTE: ce.MATERIALES_RECIPIENTE,
            Familia.TANQUE: ce.MATERIALES_TANQUE}[familia]


def material_componente(eq: Equipo, comp: Componente) -> Dict[str, Any]:
    mat_id = comp.material_id or eq.material_id
    cat = _catalogo(eq.familia)
    if mat_id not in cat:
        raise ValueError(f"{eq.tag}: material {mat_id!r} no está en el catálogo de "
                         f"{eq.familia.value} ({sorted(cat)}).")
    return {"id": mat_id, **cat[mat_id]}


# =============================================================================
# Espesores del componente
# =============================================================================

def espesores_componente(eq: Equipo, comp: Componente,
                         cr_gov: Optional[float] = None) -> Dict[str, Any]:
    """Cuadro de espesores del componente según su familia (salida estándar del motor).

    ``cr_gov`` solo afecta a ``t_alerta``; ``t_min`` es independiente de la corrosión.
    Si el componente declara ``t_min_mm_override`` ese valor reemplaza al t_min
    calculado (y se deja constancia en las observaciones).
    """
    p = eq.parametros
    mat = material_componente(eq, comp)
    T = eq.diseno.temperatura_C
    P = eq.diseno.presion_MPa

    if eq.familia == Familia.TUBERIA:
        rS = ce.esfuerzo_admisible(mat["id"], T, ce.MATERIALES_TUBERIA)
        r = ce.evaluar_espesores_tuberia(
            P, comp.diametro_exterior_mm, rS["resultado"], p.eficiencia_junta, comp.t_nom_mm,
            p.sobreespesor_corrosion_mm, p.factor_W, p.coeficiente_Y, p.tolerancia_fabricacion,
            p.t_estructural_mm, cr_gov, p.dt_margen_anios)
    elif eq.familia == Familia.RECIPIENTE:
        rS = ce.esfuerzo_admisible(mat["id"], T, ce.MATERIALES_RECIPIENTE)
        r = ce.evaluar_espesores_recipiente(
            P, comp.radio_interior_mm, rS["resultado"], p.eficiencia_junta, comp.t_nom_mm,
            p.sobreespesor_corrosion_mm, p.tolerancia_placa_mm, cr_gov, p.dt_margen_anios)
    else:
        faltan = [n for n in ("diametro_tanque_m", "densidad_relativa_G") if getattr(p, n) is None]
        if faltan:
            raise ValueError(f"{eq.tag}: faltan parámetros de tanque {faltan}.")
        rS = None
        r = ce.evaluar_espesores_virola(
            p.diametro_tanque_m, comp.nivel_sobre_fondo_virola_m, p.densidad_relativa_G, mat["id"],
            comp.t_nom_mm, p.sobreespesor_corrosion_mm, comp.numero_virola, p.eficiencia_junta,
            p.eficiencia_junta_servicio, cr_gov, p.dt_margen_anios)
        if T > mat["temperatura_max_C"]:
            r["alertas"].append(ce.ALERTA_FUERA_DE_ALCANCE)
            r["observaciones"].append(f"T de diseño {T} °C > {mat['temperatura_max_C']} °C: "
                                      "aplicaría API 650 Anexo M (fuera de alcance).")

    if rS is not None:
        r["detalle"]["esfuerzo_admisible"] = rS
        r["resultado"]["S"] = rS["resultado"]
        r["unidad"]["S"] = "MPa"
    if comp.t_min_mm_override:
        r["observaciones"].append(f"t_min calculado = {r['resultado']['t_min']:.3f} mm reemplazado "
                                  f"por t_min declarado = {comp.t_min_mm_override:.3f} mm.")
        r["resultado"]["t_min"] = float(comp.t_min_mm_override)
    return r


# =============================================================================
# Evaluación de CML / equipo / proyecto
# =============================================================================

def evaluar_cml(eq: Equipo, comp: Componente, cml: CML, fecha_evaluacion: date,
                cuadro_espesores: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Evaluación completa de un CML con los parámetros de su equipo y componente."""
    cuadro = cuadro_espesores or espesores_componente(eq, comp)
    t_min = cuadro["resultado"]["t_min"]
    p = eq.parametros
    regla = p.regla_rl_menor_4 if eq.familia == Familia.RECIPIENTE else "POR_DEFECTO"
    r = ce.evaluar_punto_espesor(
        eq.familia.value, cml.mediciones_motor(), t_min, fecha_evaluacion,
        intervenciones=cml.intervenciones_motor(), dt_margen_anios=p.dt_margen_anios,
        clase_tuberia=p.clase_tuberia, regla_rl_menor_4=regla)
    r["identificacion"] = {"tag": eq.tag, "familia": eq.familia.value, "componente_id": comp.id,
                           "componente": comp.nombre, "cml_id": cml.id,
                           "ubicacion": cml.descripcion_ubicacion}
    return r


def evaluar_equipo(eq: Equipo, fecha_evaluacion: date) -> Dict[str, Any]:
    """Evalúa todos los componentes y CML del equipo.

    Devuelve ``{"tag", "familia", "estado", "cr_gov_max", "componentes": [...]}``
    donde cada componente trae su cuadro de espesores y la lista de CML evaluados.
    """
    componentes = []
    estados: List[str] = []
    crs: List[float] = []
    for comp in eq.componentes:
        cuadro = espesores_componente(eq, comp)
        cmls = [evaluar_cml(eq, comp, cml, fecha_evaluacion, cuadro) for cml in comp.cmls]
        estados += [c["resultado"]["estado"] for c in cmls]
        crs += [c["resultado"]["cr_para_calculo"] for c in cmls
                if c["resultado"]["cr_para_calculo"] is not None]
        componentes.append({"componente_id": comp.id, "nombre": comp.nombre,
                            "espesores": cuadro, "cmls": cmls})
    return {"tag": eq.tag, "familia": eq.familia.value, "estado": estado_peor(estados),
            "cr_gov_max": max(crs) if crs else None, "componentes": componentes}


def _buscar_cml_en_evaluacion(ev_eq: Dict[str, Any], cml_id: str) -> Tuple[Dict, Dict]:
    for c in ev_eq["componentes"]:
        for m in c["cmls"]:
            if m["identificacion"]["cml_id"] == cml_id:
                return c, m
    raise ValueError(f"CML de referencia {cml_id!r} no encontrado en {ev_eq['tag']}.")


def evaluar_rbi_equipo(eq: Equipo, fecha_evaluacion: date,
                       evaluacion_equipo: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    """RBI por adelgazamiento generalizado de un equipo con ``eq.rbi`` definido.

    CR de entrada: la CR de cálculo del CML de referencia (``rbi.cml_referencia_id``)
    o, si no se declara, la mayor CR de cálculo del equipo (criterio conservador).
    t_ref = t_nom y t_min del componente de ese CML; edad desde la puesta en servicio.
    """
    if eq.rbi is None:
        return None
    if eq.fecha_puesta_servicio is None:
        raise ValueError(f"{eq.tag}: se requiere fecha de puesta en servicio para el RBI.")
    rbi = eq.rbi
    ev = evaluacion_equipo or evaluar_equipo(eq, fecha_evaluacion)

    if rbi.cml_referencia_id:
        comp_ev, cml_ev = _buscar_cml_en_evaluacion(ev, rbi.cml_referencia_id)
        criterio_ref = f"CML de referencia declarado: {rbi.cml_referencia_id}."
    else:
        candidatos = [(c, m) for c in ev["componentes"] for m in c["cmls"]
                      if m["resultado"]["cr_para_calculo"] is not None]
        if not candidatos:
            raise ValueError(f"{eq.tag}: ningún CML tiene CR determinable para el RBI.")
        comp_ev, cml_ev = max(candidatos, key=lambda cm: cm[1]["resultado"]["cr_para_calculo"])
        criterio_ref = f"CML con mayor CR del equipo: {cml_ev['identificacion']['cml_id']} (conservador)."

    comp = next(c for c in eq.componentes if c.id == comp_ev["componente_id"])
    mat = material_componente(eq, comp)
    cuadro = comp_ev["espesores"]["resultado"]
    if eq.familia == Familia.TANQUE:
        S, E = cuadro["S_servicio"], eq.parametros.eficiencia_junta_servicio
        tipo = rbi.tipo_componente_gff or "TANQUE_VIROLA"
    else:
        S, E = cuadro["S"], eq.parametros.eficiencia_junta
        tipo = rbi.tipo_componente_gff or eq.familia.value
    cr = cml_ev["resultado"]["cr_para_calculo"] or 0.0

    r = ce.evaluar_rbi_adelgazamiento(
        cr_gov=cr, edad_anios=eq.edad_servicio_anios(fecha_evaluacion), t_ref=comp.t_nom_mm,
        t_min=cuadro["t_min"], S=S, E=E, YS=mat["smys_MPa"], TS=mat["smts_MPa"],
        tipo_componente=tipo, gff=rbi.gff_1_anio, inspecciones=rbi.inspecciones,
        confianza=rbi.confianza_cr.value, puntaje_sistema_gestion=rbi.puntaje_sistema_gestion,
        factor_ajuste=rbi.factor_ajuste, CA_m2=rbi.area_consecuencia_m2,
        CE=rbi.consecuencia_economica, moneda=rbi.moneda, base_valoracion=rbi.base_valoracion,
        tasa_a_usd=rbi.tasa_a_usd, efectividad_propuesta=rbi.efectividad_propuesta.value,
        horizonte_plan_anios=rbi.horizonte_plan_anios)
    r["detalle"]["referencia"] = {
        "cml_id": cml_ev["identificacion"]["cml_id"], "componente_id": comp.id,
        "criterio": criterio_ref, "justificacion": rbi.justificacion_cml_referencia,
        "fecha_puesta_servicio": eq.fecha_puesta_servicio.isoformat()}
    r["observaciones"].insert(0, criterio_ref)
    if rbi.justificacion_cml_referencia:
        r["observaciones"].insert(1, rbi.justificacion_cml_referencia)
    return r


def evaluar_proyecto(proyecto: Proyecto, fecha_evaluacion: Optional[date] = None,
                     tolerante: bool = False) -> Dict[str, Any]:
    """Evalúa el proyecto completo y arma las filas del panel de resultados.

    Devuelve ``{"fecha_evaluacion", "filas", "equipos", "rbi", "integridad", "errores"}``.
    Cada fila (una por CML) trae ubicación, familia, estado y magnitudes clave,
    lista para filtrar por planta/área/sistema, familia o condición.

    Con ``tolerante=True`` (uso en la interfaz) un equipo con datos incompletos o
    inválidos no detiene la evaluación del resto: su mensaje queda en
    ``errores[tag]`` (y en ``errores[tag + ' (RBI)']`` para el RBI).
    """
    f_eval = fecha_evaluacion or proyecto.fecha_evaluacion or date.today()
    filas: List[Dict[str, Any]] = []
    equipos: Dict[str, Dict[str, Any]] = {}
    rbis: Dict[str, Any] = {}
    errores: Dict[str, str] = {}
    for planta, area, sistema, eq in proyecto.iter_equipos():
        try:
            ev = evaluar_equipo(eq, f_eval)
        except (ValueError, TypeError, KeyError) as exc:
            if not tolerante:
                raise
            errores[eq.tag] = str(exc)
            continue
        equipos[eq.tag] = ev
        if eq.rbi is not None:
            try:
                rbis[eq.tag] = evaluar_rbi_equipo(eq, f_eval, ev)
            except (ValueError, TypeError, KeyError) as exc:
                if not tolerante:
                    raise
                errores[eq.tag + " (RBI)"] = str(exc)
        for c in ev["componentes"]:
            for m in c["cmls"]:
                res = m["resultado"]
                filas.append({
                    "planta": planta.nombre, "area": area.nombre, "sistema": sistema.nombre,
                    "tag": eq.tag, "familia": eq.familia.value,
                    "componente": c["nombre"], "cml_id": m["identificacion"]["cml_id"],
                    "estado": res["estado"], "t_ultimo": res["t_ultimo"], "t_min": res["t_min"],
                    "t_alerta": res["t_alerta"], "cr_gov": res["cr_gov"],
                    "vida_remanente": res["vida_remanente"], "fecha_proxima": res["fecha_proxima"],
                    "criterio": res["criterio_gobernante"], "alertas": m["alertas"]})
    return {"fecha_evaluacion": f_eval, "filas": filas, "equipos": equipos, "rbi": rbis,
            "integridad": proyecto.validar_integridad(), "errores": errores}
