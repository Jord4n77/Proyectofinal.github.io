"""
controlador.py — Estado de la interfaz y acciones del usuario (Python puro).

``Controlador`` guarda el proyecto en memoria y el estado de navegación
(vista, equipo, pestaña, CML seleccionado, filtros, fecha de evaluación). La
capa ``web/main.py`` solo:

1. traduce un clic (``data-accion``) o un formulario (``data-form``) en
   ``controlador.despachar(accion, datos)``;
2. inserta en la página las regiones HTML de ``controlador.renderizar()``;
3. resuelve lo que requiere el navegador (almacenamiento, descarga y carga de
   archivos) llamando a ``exportar_json`` / ``importar_json`` / ``marcar_guardado``.

Todos los datos de formularios llegan como texto. Los números aceptan coma o
punto decimal ("3,45" o "3.45"). Un error de entrada no modifica el proyecto y
se informa como mensaje.
"""

from __future__ import annotations

import os
import sys
import traceback
from dataclasses import replace
from datetime import date
from typing import Any, Callable, Dict, List, Optional, Tuple

import calc_engine as ce
import servicios
import vistas
from models import (CML, Area, Componente, CondicionesProceso, ConfianzaCR, DatosRBI, Documento,
                    Efectividad, Equipo, EventoMedicion, Familia, Intervencion, Medicion,
                    ParametrosCalculo, Planta, Proyecto, Sistema, TecnicaMedicion,
                    TIPO_COMPONENTE_POR_FAMILIA, TipoDocumento, TipoIntervencion, UnidadEspesor)

MAX_ADJUNTO_BYTES = 2_500_000   # el proyecto completo debe caber en localStorage (~5 MB)


class ErrorEntrada(ValueError):
    """Dato de formulario inválido (se muestra al usuario sin traza)."""


# =============================================================================
# Lectura de datos de formulario
# =============================================================================

def _txt(d: Dict[str, Any], k: str, requerido: bool = False, etiqueta: str = "") -> str:
    v = d.get(k)
    v = "" if v is None else str(v).strip()
    if requerido and not v:
        raise ErrorEntrada(f"El campo «{etiqueta or k}» es obligatorio.")
    return v


def _num(d: Dict[str, Any], k: str, etiqueta: str = "", opcional: bool = False,
         minimo: Optional[float] = None, maximo: Optional[float] = None) -> Optional[float]:
    v = _txt(d, k)
    if v == "":
        if opcional:
            return None
        raise ErrorEntrada(f"El campo «{etiqueta or k}» es obligatorio.")
    try:
        x = float(v.replace(" ", "").replace(",", "."))
    except ValueError:
        raise ErrorEntrada(f"«{etiqueta or k}» debe ser numérico (recibido: {v!r}).") from None
    if minimo is not None and x < minimo:
        raise ErrorEntrada(f"«{etiqueta or k}» debe ser ≥ {minimo:g}.")
    if maximo is not None and x > maximo:
        raise ErrorEntrada(f"«{etiqueta or k}» debe ser ≤ {maximo:g}.")
    return x


def _ent(d: Dict[str, Any], k: str, etiqueta: str = "", opcional: bool = False, minimo: int = 0) -> Optional[int]:
    x = _num(d, k, etiqueta, opcional, minimo)
    if x is None:
        return None
    if abs(x - round(x)) > 1e-9:
        raise ErrorEntrada(f"«{etiqueta or k}» debe ser entero.")
    return int(round(x))


def _fec(d: Dict[str, Any], k: str, etiqueta: str = "", opcional: bool = False) -> Optional[date]:
    v = _txt(d, k)
    if not v:
        if opcional:
            return None
        raise ErrorEntrada(f"El campo «{etiqueta or k}» es obligatorio.")
    try:
        return date.fromisoformat(v[:10])
    except ValueError:
        raise ErrorEntrada(f"«{etiqueta or k}» debe ser una fecha AAAA-MM-DD.") from None


def _bool(d: Dict[str, Any], k: str) -> bool:
    return str(d.get(k, "")).lower() in ("1", "on", "true", "si", "sí")


def _clase(v: str) -> Any:
    return int(v) if v.isdigit() else v


# =============================================================================
# Controlador
# =============================================================================

class Controlador:
    REGIONES = ("encabezado", "lateral", "mensajes", "principal")

    def __init__(self, proyecto_json: str, demo_json: Optional[str] = None, hoy: Optional[date] = None):
        self.demo_json = demo_json or proyecto_json
        self.proyecto = Proyecto.desde_json(proyecto_json)
        self.hoy = hoy or date.today()
        self.fecha_evaluacion: date = self.proyecto.fecha_evaluacion or self.hoy
        self.vista = "panel"
        self.tag: Optional[str] = None
        self.pestana = "antecedentes"
        self.cml_id: Optional[str] = None
        self.filtros: Dict[str, str] = {"familia": "", "area": "", "estado": ""}
        self.mensajes: List[Tuple[str, str]] = []
        self.sucio = False
        self.ubicando = False
        self.desplazar_a: Optional[str] = None
        self._ev: Optional[Dict[str, Any]] = None
        self._verif: Optional[Tuple[Any, Any, Optional[str]]] = None

    # ------------------------------------------------------------- utilidades
    def mensaje(self, tipo: str, texto: str) -> None:
        self.mensajes.append((tipo, texto))

    def _cambio(self) -> None:
        self.sucio = True
        self._ev = None

    def evaluacion(self) -> Dict[str, Any]:
        if self._ev is None:
            self._ev = servicios.evaluar_proyecto(self.proyecto, self.fecha_evaluacion, tolerante=True)
        return self._ev

    def _equipo(self, tag: Optional[str]) -> Equipo:
        eq = self.proyecto.buscar_equipo(tag or "")
        if eq is None:
            raise ErrorEntrada(f"Equipo {tag!r} no encontrado.")
        return eq

    def _cml(self, cml_id: Optional[str]) -> Tuple[Equipo, Componente, CML]:
        r = self.proyecto.buscar_cml(cml_id or "")
        if r is None:
            raise ErrorEntrada(f"CML {cml_id!r} no encontrado.")
        return r

    def _resumen_cml(self, cml_id: str) -> str:
        eq, comp, cml = self._cml(cml_id)
        try:
            r = servicios.evaluar_cml(eq, comp, cml, self.fecha_evaluacion)["resultado"]
        except (ValueError, TypeError) as exc:
            return f"(no evaluable: {exc})"
        rl = "indeterminada" if r["vida_remanente"] is None else f"{r['vida_remanente']:.2f} años"
        cr = "—" if r["cr_gov"] is None else f"{r['cr_gov']:.3f} mm/año"
        return (f"CR_gov = {cr}; RL = {rl}; próxima inspección = {vistas.fecha(r['fecha_proxima'])}; "
                f"condición = {vistas.ETIQUETA_ESTADO.get(r['estado'], r['estado'])}.")

    # ------------------------------------------------------------- despacho
    def despachar(self, accion: str, datos: Optional[Dict[str, Any]] = None) -> None:
        """Ejecuta una acción de la interfaz. Nunca levanta excepción: informa en mensajes."""
        datos = dict(datos or {})
        self.mensajes = []
        metodo: Optional[Callable[[Dict[str, Any]], None]] = getattr(self, f"_a_{accion}", None)
        if metodo is None:
            self.mensaje("error", f"Acción desconocida: {accion}")
            return
        try:
            metodo(datos)
        except (ErrorEntrada, ValueError, TypeError, KeyError) as exc:
            self._ev = None
            self.mensaje("error", str(exc) if isinstance(exc, (ErrorEntrada, ValueError)) else
                         f"Dato faltante o inválido: {exc}")
        except Exception as exc:  # pragma: no cover - salvaguarda de la demostración
            self._ev = None
            self.mensaje("error", f"Error inesperado en «{accion}»: {exc}")
            traceback.print_exc()

    # ------------------------------------------------------------- navegación
    def _a_ver_panel(self, d):
        self.vista, self.ubicando = "panel", False

    def _a_ver_equipo(self, d):
        eq = self._equipo(d.get("tag"))
        if eq.tag != self.tag:
            self.pestana, self.cml_id = "antecedentes", None
        self.vista, self.tag, self.ubicando = "equipo", eq.tag, False

    def _a_ver_cml(self, d):
        eq, _, cml = self._cml(d.get("cml"))
        self.vista, self.tag, self.pestana, self.cml_id = "equipo", eq.tag, "esquema", cml.id
        self.ubicando = False
        self.desplazar_a = "detalle-cml"

    def _a_ver_rbi(self, d):
        eq = self._equipo(d.get("tag"))
        self.vista, self.tag, self.pestana, self.ubicando = "equipo", eq.tag, "rbi", False

    def _a_pestana(self, d):
        valor = d.get("valor")
        if valor not in {k for k, _ in vistas.PESTANAS}:
            raise ErrorEntrada(f"Pestaña desconocida: {valor}")
        self.pestana, self.ubicando = valor, False

    def _a_nuevo_equipo(self, d):
        self.vista = "nuevo_equipo"

    def _a_ver_verificacion(self, d):
        self.vista = "verificacion"

    def _a_ver_normas(self, d):
        self.vista = "normas"

    def _a_cerrar_mensajes(self, d):
        self.mensajes = []

    def _a_filtros(self, d):
        self.filtros = {k: _txt(d, k) for k in ("familia", "area", "estado")}

    def _a_fecha(self, d):
        self.fecha_evaluacion = _fec(d, "fecha", "Fecha de evaluación")
        self.proyecto.fecha_evaluacion = self.fecha_evaluacion
        self._cambio()
        self.mensaje("ok", f"Fecha de evaluación: {self.fecha_evaluacion.isoformat()}. Resultados recalculados.")

    def _a_fecha_hoy(self, d):
        self._a_fecha({"fecha": self.hoy.isoformat()})

    def _a_restablecer_demo(self, d):
        self.proyecto = Proyecto.desde_json(self.demo_json)
        self.fecha_evaluacion = self.proyecto.fecha_evaluacion or self.hoy
        self.vista, self.tag, self.cml_id, self.pestana, self.ubicando = "panel", None, None, "antecedentes", False
        self.filtros = {"familia": "", "area": "", "estado": ""}
        self._cambio()
        self.mensaje("ok", "Caso demostrativo restablecido. Use «Guardar» para conservarlo en el navegador.")

    # ------------------------------------------------------------- equipo
    def _a_editar_equipo(self, d):
        eq = self._equipo(d.get("tag"))
        f = eq.familia
        material = _txt(d, "material_id", True, "Material")
        if material not in servicios._catalogo(f):
            raise ErrorEntrada(f"El material {material} no pertenece al catálogo de {f.value}.")
        cambios: Dict[str, Any] = {
            "sobreespesor_corrosion_mm": _num(d, "CA", "CA", minimo=0),
            "eficiencia_junta": _num(d, "E", "E", minimo=0, maximo=1),
            "dt_margen_anios": _num(d, "dt_margen_anios", "Δt_margen", minimo=0),
        }
        circuito = eq.circuito_inspeccion
        if f == Familia.TUBERIA:
            cambios.update(factor_W=_num(d, "factor_W", "W", minimo=0, maximo=1),
                           coeficiente_Y=_num(d, "coeficiente_Y", "Y", minimo=0, maximo=0.7),
                           tolerancia_fabricacion=_num(d, "tolerancia_pct", "Tolerancia", minimo=0, maximo=99) / 100,
                           t_estructural_mm=_num(d, "t_estructural_mm", "t estructural", True, 0) or 0.0,
                           clase_tuberia=_clase(_txt(d, "clase_tuberia", True, "Clase")))
            circuito = _txt(d, "circuito_inspeccion") or None
        elif f == Familia.RECIPIENTE:
            cambios.update(tolerancia_placa_mm=_num(d, "tolerancia_placa_mm", "Tolerancia de placa", True, 0) or 0.0,
                           regla_rl_menor_4=_txt(d, "regla_rl_menor_4") or "CONSERVADORA_1_4")
        else:
            cambios.update(diametro_tanque_m=_num(d, "diametro_tanque_m", "D del tanque", minimo=0),
                           altura_liquido_diseno_m=_num(d, "altura_liquido_diseno_m", "Nivel de diseño", True, 0),
                           densidad_relativa_G=_num(d, "densidad_relativa_G", "G", minimo=0),
                           eficiencia_junta_servicio=_num(d, "eficiencia_junta_servicio", "E en servicio", minimo=0, maximo=1))
        nuevos_param = replace(eq.parametros, **cambios)          # valida en __post_init__
        diseno = CondicionesProceso(_num(d, "P_dis", "Presión de diseño", minimo=0), _num(d, "T_dis", "T de diseño"))
        operacion = CondicionesProceso(_num(d, "P_op", "Presión de operación", True, 0) or 0.0,
                                       _num(d, "T_op", "T de operación", True) or diseno.temperatura_C)
        anterior = (eq.parametros, eq.diseno, eq.operacion, eq.material_id)
        eq.parametros, eq.diseno, eq.operacion, eq.material_id = nuevos_param, diseno, operacion, material
        try:
            for comp in eq.componentes:                            # verifica que el equipo siga evaluable
                servicios.espesores_componente(eq, comp)
        except ValueError as exc:
            eq.parametros, eq.diseno, eq.operacion, eq.material_id = anterior
            raise ErrorEntrada(f"Los datos no son válidos para el cálculo: {exc}") from None
        eq.descripcion = _txt(d, "descripcion", True, "Descripción")
        eq.servicio, eq.fluido = _txt(d, "servicio"), _txt(d, "fluido")
        eq.fecha_puesta_servicio = _fec(d, "fecha_puesta_servicio", opcional=True)
        eq.circuito_inspeccion = circuito
        self._cambio()
        resumen = []
        for comp in eq.componentes:
            r = servicios.espesores_componente(eq, comp)["resultado"]
            t_req = r.get("t_presion", r.get("t_req", r.get("t_requerido")))
            resumen.append(f"{comp.nombre}: t requerido = {t_req:.3f} mm, t_min = {r['t_min']:.3f} mm")
        self.mensaje("ok", f"{eq.tag} actualizado. " + "; ".join(resumen) + ".")

    def _geometria(self, eq: Equipo, d: Dict[str, Any]) -> Dict[str, Any]:
        if eq.familia == Familia.TUBERIA:
            return {"diametro_exterior_mm": _num(d, "diametro_exterior_mm", "D exterior", minimo=0),
                    "nps": _txt(d, "nps") or None, "cedula": _txt(d, "cedula") or None}
        if eq.familia == Familia.RECIPIENTE:
            return {"radio_interior_mm": _num(d, "radio_interior_mm", "R interior", minimo=0)}
        return {"numero_virola": _ent(d, "numero_virola", "N.º de virola", minimo=1),
                "nivel_sobre_fondo_virola_m": _num(d, "nivel_sobre_fondo_virola_m", "H sobre fondo", minimo=0),
                "altura_virola_m": _num(d, "altura_virola_m", "Altura de virola", True, 0)}

    def _a_editar_componente(self, d):
        eq = self._equipo(d.get("tag"))
        idx = next((i for i, c in enumerate(eq.componentes) if c.id == d.get("comp")), None)
        if idx is None:
            raise ErrorEntrada("Componente no encontrado.")
        anterior = eq.componentes[idx]
        nuevo = replace(anterior, nombre=_txt(d, "nombre", True, "Nombre"),
                        t_nom_mm=_num(d, "t_nom_mm", "t_nom", minimo=0),
                        t_min_mm_override=_num(d, "t_min_mm_override", "t_min declarado", True, 0) or None,
                        **self._geometria(eq, d))
        eq.componentes[idx] = nuevo
        try:
            r = servicios.espesores_componente(eq, nuevo)["resultado"]
        except ValueError as exc:
            eq.componentes[idx] = anterior
            raise ErrorEntrada(f"Componente no evaluable: {exc}") from None
        self._cambio()
        self.mensaje("ok", f"{nuevo.nombre} actualizado: t_min = {r['t_min']:.3f} mm.")

    def _a_agregar_componente(self, d):
        eq = self._equipo(d.get("tag"))
        cid = _txt(d, "id", True, "Identificador")
        if any(c.id == cid for *_, e in self.proyecto.iter_equipos() for c in e.componentes):
            raise ErrorEntrada(f"Ya existe un componente con id {cid}.")
        comp = Componente(id=cid, nombre=_txt(d, "nombre", True, "Nombre"),
                          tipo=TIPO_COMPONENTE_POR_FAMILIA[eq.familia],
                          t_nom_mm=_num(d, "t_nom_mm", "t_nom", minimo=0), **self._geometria(eq, d))
        servicios.espesores_componente(eq, comp)
        eq.componentes.append(comp)
        self._cambio()
        self.mensaje("ok", f"Componente {cid} agregado a {eq.tag}.")

    def _a_crear_equipo(self, d):
        tag = _txt(d, "tag", True, "TAG").upper()
        if self.proyecto.buscar_equipo(tag):
            raise ErrorEntrada(f"Ya existe un equipo con TAG {tag}.")
        familia = Familia(_txt(d, "familia", True, "Familia"))
        fam_mat, _, material = _txt(d, "material", True, "Material").partition(":")
        if fam_mat != familia.value:
            raise ErrorEntrada(f"El material elegido es de {fam_mat}; elija uno de {familia.value}.")
        params: Dict[str, Any] = {"sobreespesor_corrosion_mm": _num(d, "CA", "CA", minimo=0),
                                  "eficiencia_junta": _num(d, "E", "E", minimo=0, maximo=1)}
        geom: Dict[str, Any] = {}
        if familia == Familia.TUBERIA:
            params["clase_tuberia"] = _clase(_txt(d, "clase_tuberia") or "2")
            geom = {"diametro_exterior_mm": _num(d, "diametro_exterior_mm", "D exterior", minimo=0)}
        elif familia == Familia.RECIPIENTE:
            geom = {"radio_interior_mm": _num(d, "radio_interior_mm", "R interior", minimo=0)}
        else:
            params.update(diametro_tanque_m=_num(d, "diametro_tanque_m", "D del tanque", minimo=0),
                          densidad_relativa_G=_num(d, "densidad_relativa_G", "G", minimo=0))
            geom = {"numero_virola": 1,
                    "nivel_sobre_fondo_virola_m": _num(d, "nivel_sobre_fondo_virola_m", "H sobre fondo", minimo=0)}
            params["altura_liquido_diseno_m"] = geom["nivel_sobre_fondo_virola_m"]
        comp = Componente(id=f"{tag}-C01", nombre={"TUBERIA": "Tramo recto", "RECIPIENTE": "Envolvente cilíndrica",
                                                   "TANQUE": "Virola 1 (inferior)"}[familia.value],
                          tipo=TIPO_COMPONENTE_POR_FAMILIA[familia],
                          t_nom_mm=_num(d, "t_nom_mm", "t_nom", minimo=0), **geom)
        eq = Equipo(tag=tag, descripcion=_txt(d, "descripcion", True, "Descripción"), familia=familia,
                    material_id=material, servicio=_txt(d, "servicio"), fluido=_txt(d, "fluido"),
                    circuito_inspeccion=(_txt(d, "circuito_inspeccion") or None) if familia == Familia.TUBERIA else None,
                    fecha_puesta_servicio=_fec(d, "fecha_puesta_servicio", opcional=True),
                    diseno=CondicionesProceso(_num(d, "P_dis", "Presión de diseño", familia == Familia.TANQUE, 0) or 0.0,
                                              _num(d, "T_dis", "T de diseño")),
                    parametros=ParametrosCalculo(**params), componentes=[comp])
        eq.operacion = CondicionesProceso(eq.diseno.presion_MPa, eq.diseno.temperatura_C)
        if familia != Familia.TANQUE and eq.diseno.presion_MPa <= 0:
            raise ErrorEntrada("La presión de diseño debe ser > 0 para tuberías y recipientes.")
        servicios.espesores_componente(eq, comp)                   # verifica que sea evaluable
        sistema = self._buscar_o_crear_sistema(_txt(d, "planta", True, "Planta"), _txt(d, "area", True, "Área"),
                                               _txt(d, "sistema", True, "Sistema"))
        sistema.equipos.append(eq)
        self._cambio()
        self.vista, self.tag, self.pestana, self.cml_id = "equipo", tag, "antecedentes", None
        self.mensaje("ok", f"Equipo {tag} creado en {self.proyecto.ubicacion_tecnica(tag)}. "
                           "Agregue CML en la pestaña «Esquema y CML».")

    def _buscar_o_crear_sistema(self, planta: str, area: str, sistema: str) -> Sistema:
        def nuevo_id(prefijo: str, existentes: List[str]) -> str:
            n = 1
            while f"{prefijo}-{n:02d}" in existentes:
                n += 1
            return f"{prefijo}-{n:02d}"
        p = next((x for x in self.proyecto.plantas if x.nombre == planta), None)
        if p is None:
            p = Planta(nuevo_id("PL", [x.id for x in self.proyecto.plantas]), planta)
            self.proyecto.plantas.append(p)
        a = next((x for x in p.areas if x.nombre == area), None)
        if a is None:
            a = Area(nuevo_id("A", [x.id for pl in self.proyecto.plantas for x in pl.areas]), area)
            p.areas.append(a)
        s = next((x for x in a.sistemas if x.nombre == sistema), None)
        if s is None:
            s = Sistema(nuevo_id("S", [x.id for pl in self.proyecto.plantas for ar in pl.areas for x in ar.sistemas]),
                        sistema)
            a.sistemas.append(s)
        return s

    # ------------------------------------------------------------- CML y mediciones
    def _a_agregar_cml(self, d):
        eq = self._equipo(d.get("tag"))
        comp = next((c for c in eq.componentes if c.id == d.get("componente_id")), None)
        if comp is None:
            raise ErrorEntrada("Seleccione un componente válido.")
        cid = _txt(d, "id", True, "Identificador")
        if self.proyecto.buscar_cml(cid):
            raise ErrorEntrada(f"Ya existe un CML con id {cid}.")
        doc = next((x for x in eq.documentos if x.admite_marcadores), None)
        cml = CML(id=cid, descripcion_ubicacion=_txt(d, "descripcion_ubicacion"),
                  posicion_horaria=_txt(d, "posicion_horaria") or None,
                  distancia_referencia_mm=_num(d, "distancia_referencia_mm", "Distancia", True),
                  documento_id=doc.id if doc else None,
                  marcador_x=_num(d, "marcador_x", "Marcador x", True, 0, 1),
                  marcador_y=_num(d, "marcador_y", "Marcador y", True, 0, 1))
        comp.cmls.append(cml)
        self._cambio()
        self.vista, self.tag, self.pestana, self.cml_id = "equipo", eq.tag, "esquema", cid
        self.mensaje("ok", f"CML {cid} creado. Agregue su primera medición (línea base).")

    def _a_editar_cml(self, d):
        eq, comp, cml = self._cml(d.get("cml"))
        nuevo = replace(cml, descripcion_ubicacion=_txt(d, "descripcion_ubicacion"),
                        posicion_horaria=_txt(d, "posicion_horaria") or None,
                        distancia_referencia_mm=_num(d, "distancia_referencia_mm", "Distancia", True),
                        marcador_x=_num(d, "marcador_x", "Marcador x", True, 0, 1),
                        marcador_y=_num(d, "marcador_y", "Marcador y", True, 0, 1),
                        convencion=_txt(d, "convencion") or cml.convencion)
        comp.cmls[comp.cmls.index(cml)] = nuevo
        self._cambio()
        self.mensaje("ok", f"CML {cml.id} actualizado.")

    def _a_iniciar_ubicacion(self, d):
        eq, _, cml = self._cml(d.get("cml"))
        if not any(x.admite_marcadores for x in eq.documentos):
            raise ErrorEntrada("Primero suba un esquema PNG/JPG para el equipo.")
        self.vista, self.tag, self.pestana, self.cml_id, self.ubicando = "equipo", eq.tag, "esquema", cml.id, True

    def _a_cancelar_ubicacion(self, d):
        self.ubicando = False

    def _a_ubicar_marcador(self, d):
        eq, comp, cml = self._cml(d.get("cml"))
        x = min(max(_num(d, "x", "x"), 0.0), 1.0)
        y = min(max(_num(d, "y", "y"), 0.0), 1.0)
        doc = next((x_ for x_ in eq.documentos if x_.admite_marcadores), None)
        comp.cmls[comp.cmls.index(cml)] = replace(cml, marcador_x=round(x, 4), marcador_y=round(y, 4),
                                                  documento_id=doc.id if doc else cml.documento_id)
        self.ubicando = False
        self._cambio()
        self.mensaje("ok", f"Marcador de {cml.id} ubicado en ({x:.3f}, {y:.3f}).")

    def _a_agregar_medicion(self, d):
        eq, comp, cml = self._cml(d.get("cml"))
        n = len(cml.mediciones) + 1
        ids = {m.id for m in cml.mediciones}
        while f"{cml.id}-M{n}" in ids:
            n += 1
        med = Medicion(id=f"{cml.id}-M{n}", fecha=_fec(d, "fecha", "Fecha"),
                       espesor=_num(d, "espesor", "Espesor", minimo=0),
                       unidad=UnidadEspesor(_txt(d, "unidad") or "mm"),
                       tecnica=TecnicaMedicion(_txt(d, "tecnica") or "UT"),
                       inspector=_txt(d, "inspector"), observaciones=_txt(d, "observaciones"),
                       valida=_bool(d, "valida"), evento=EventoMedicion(_txt(d, "evento") or "NORMAL"))
        if med.espesor <= 0:
            raise ErrorEntrada("El espesor debe ser > 0.")
        cml.agregar_medicion(med)
        self._cambio()
        self.vista, self.tag, self.pestana, self.cml_id = "equipo", eq.tag, "esquema", cml.id
        aviso = " (posterior a la fecha de evaluación: quedará excluida)" if med.fecha > self.fecha_evaluacion else ""
        self.mensaje("ok", f"Medición {med.espesor_mm:.2f} mm del {med.fecha.isoformat()} agregada a {cml.id}{aviso}. "
                           + self._resumen_cml(cml.id))

    def _medicion(self, d) -> Tuple[CML, Medicion]:
        _, _, cml = self._cml(d.get("cml"))
        med = next((m for m in cml.mediciones if m.id == d.get("med")), None)
        if med is None:
            raise ErrorEntrada("Medición no encontrada.")
        return cml, med

    def _a_alternar_validez(self, d):
        cml, med = self._medicion(d)
        med.valida = not med.valida
        self._cambio()
        self.mensaje("ok", f"Medición del {med.fecha.isoformat()} marcada como "
                           f"{'válida' if med.valida else 'no válida'}. " + self._resumen_cml(cml.id))

    def _a_eliminar_medicion(self, d):
        cml, med = self._medicion(d)
        cml.mediciones.remove(med)
        self._cambio()
        self.mensaje("ok", f"Medición del {med.fecha.isoformat()} eliminada. " + self._resumen_cml(cml.id))

    def _a_agregar_intervencion(self, d):
        _, _, cml = self._cml(d.get("cml"))
        n = len(cml.intervenciones) + 1
        iv = Intervencion(id=f"{cml.id}-INT-{n}", fecha=_fec(d, "fecha", "Fecha"),
                          tipo=TipoIntervencion(_txt(d, "tipo", True, "Tipo")), descripcion=_txt(d, "descripcion"))
        cml.intervenciones.append(iv)
        self._cambio()
        self.mensaje("ok", f"Intervención registrada en {cml.id}: la línea base se reinicia el "
                           f"{iv.fecha.isoformat()}. " + self._resumen_cml(cml.id))

    def _a_subir_esquema(self, d):
        eq = self._equipo(d.get("tag"))
        contenido = _txt(d, "archivo_base64", True, "Archivo")
        tipo_mime = _txt(d, "archivo_tipo").lower()
        tipo = {"image/png": TipoDocumento.PNG, "image/jpeg": TipoDocumento.JPG,
                "image/jpg": TipoDocumento.JPG}.get(tipo_mime)
        if tipo is None:
            raise ErrorEntrada("Solo se admiten imágenes PNG o JPG.")
        if len(contenido) * 3 / 4 > MAX_ADJUNTO_BYTES:
            raise ErrorEntrada(f"La imagen supera {MAX_ADJUNTO_BYTES / 1e6:.1f} MB; redúzcala para que el "
                               "proyecto quepa en el almacenamiento del navegador.")
        nombre = _txt(d, "nombre") or _txt(d, "archivo_nombre") or f"Esquema {eq.tag}"
        previo = next((x for x in eq.documentos if x.admite_marcadores), None)
        doc_id = previo.id if previo else f"ESQ-{eq.tag}"
        doc = Documento(id=doc_id, nombre=nombre, tipo=tipo, descripcion=_txt(d, "archivo_nombre"),
                        ruta=None, contenido_base64=contenido)
        if previo:
            eq.documentos[eq.documentos.index(previo)] = doc
        else:
            eq.documentos.append(doc)
        for comp in eq.componentes:
            comp.cmls = [replace(c, documento_id=doc_id) if c.documento_id in (None, doc_id) else c for c in comp.cmls]
        self._cambio()
        self.vista, self.tag, self.pestana = "equipo", eq.tag, "esquema"
        self.mensaje("ok", f"Esquema «{nombre}» cargado en {eq.tag}. Los marcadores conservan sus coordenadas.")

    # ------------------------------------------------------------- RBI
    def _a_activar_rbi(self, d):
        eq = self._equipo(d.get("tag"))
        eq.rbi = DatosRBI(tipo_componente_gff="TANQUE_VIROLA" if eq.familia == Familia.TANQUE else eq.familia.value)
        self._cambio()
        self.pestana = "rbi"
        self.mensaje("ok", f"RBI activado para {eq.tag}. Ingrese las consecuencias C_A y C_E.")

    def _a_editar_rbi(self, d):
        eq = self._equipo(d.get("tag"))
        insp = {}
        for k in ("A", "B", "C", "D"):
            n = _ent(d, f"insp_{k}", f"Inspecciones {k}", True, 0)
            if n:
                insp[k] = n
        moneda = _txt(d, "moneda") or "USD"
        tasa = _num(d, "tasa_a_usd", "Tasa a USD", True, 0)
        if moneda != "USD" and not tasa:
            raise ErrorEntrada(f"Para {moneda} indique la tasa a USD (y su fecha en la base de valoración).")
        nuevo = DatosRBI(
            tipo_componente_gff=_txt(d, "tipo_componente_gff") or eq.rbi.tipo_componente_gff,
            gff_1_anio=_num(d, "gff_1_anio", "gff", True, 0) or None,
            confianza_cr=ConfianzaCR(_txt(d, "confianza_cr") or "BAJA"), inspecciones=insp,
            puntaje_sistema_gestion=_num(d, "puntaje_sistema_gestion", "Puntaje", True, 0, 1000),
            factor_ajuste=_num(d, "factor_ajuste", "Factor de ajuste", True, 0) or 1.0,
            area_consecuencia_m2=_num(d, "area_consecuencia_m2", "C_A", minimo=0),
            consecuencia_economica=_num(d, "consecuencia_economica", "C_E", minimo=0),
            moneda=moneda, tasa_a_usd=tasa if moneda != "USD" else None,
            base_valoracion=_txt(d, "base_valoracion"),
            cml_referencia_id=_txt(d, "cml_referencia_id") or None,
            justificacion_cml_referencia=_txt(d, "justificacion_cml_referencia"),
            efectividad_propuesta=Efectividad(_txt(d, "efectividad_propuesta") or "A"),
            horizonte_plan_anios=_num(d, "horizonte_plan_anios", "Horizonte", True, 0))
        anterior = eq.rbi
        eq.rbi = nuevo
        try:
            r = servicios.evaluar_rbi_equipo(eq, self.fecha_evaluacion)["resultado"]
        except ValueError as exc:
            eq.rbi = anterior
            raise ErrorEntrada(f"RBI no evaluable con esos datos: {exc}") from None
        self._cambio()
        self.pestana = "rbi"
        self.mensaje("ok", f"RBI de {eq.tag}: D_f = {r['D_f']:.2f}; f_F = {r['f_F']:.3e}/año; "
                           f"R_A = {r['R_A']:.4g} m²/año; R_E = {r['R_E']:,.0f} {nuevo.moneda}/año; riesgo "
                           f"{vistas.ETIQUETA_NIVEL[r['nivel_riesgo']]} (P{r['prioridad']}).")

    # ------------------------------------------------------------- archivo
    def nombre_archivo(self) -> str:
        return f"proyecto_integridad_{self.fecha_evaluacion.isoformat()}.json"

    def exportar_json(self) -> str:
        self.proyecto.fecha_evaluacion = self.fecha_evaluacion
        return self.proyecto.a_json()

    def importar_json(self, texto: str, origen: str = "archivo") -> bool:
        self.mensajes = []
        try:
            p = Proyecto.desde_json(texto)
        except Exception as exc:
            self.mensaje("error", f"No se pudo leer el proyecto ({origen}): {exc}")
            return False
        problemas = p.validar_integridad()
        self.proyecto = p
        self.fecha_evaluacion = p.fecha_evaluacion or self.hoy
        self.vista, self.tag, self.cml_id, self.ubicando = "panel", None, None, False
        self._ev = None
        self.sucio = origen != "almacenamiento"
        n = sum(1 for _ in p.iter_equipos())
        self.mensaje("ok", f"Proyecto «{p.nombre}» cargado desde {origen}: {n} equipos.")
        for x in problemas:
            self.mensaje("aviso", x)
        return True

    def marcar_guardado(self) -> None:
        self.sucio = False

    # ------------------------------------------------------------- verificación
    def verificacion(self):
        if self._verif is None:
            try:
                try:
                    import validacion_independiente as vi
                except ImportError:
                    sys.path.append(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))
                    import validacion_independiente as vi
                filas, estados = vi.comparar(Proyecto.desde_json(self.demo_json))
                self._verif = (filas, estados, None)
            except Exception as exc:
                self._verif = ([], [], f"No se pudo ejecutar la verificación: {exc}")
        return self._verif

    # ------------------------------------------------------------- render
    def renderizar(self) -> Dict[str, str]:
        ev = self.evaluacion()
        regiones = {
            "encabezado": vistas.encabezado(self.proyecto, self.fecha_evaluacion, self.vista, self.sucio),
            "lateral": vistas.lateral(self.proyecto, ev, self.filtros, self.tag if self.vista == "equipo" else None),
            "mensajes": vistas.mensajes(self.mensajes),
        }
        try:
            regiones["principal"] = self._principal(ev)
        except Exception as exc:  # pragma: no cover - salvaguarda de la demostración
            traceback.print_exc()
            regiones["principal"] = (f'<section class="vista"><div class="msg msg-error">Error al mostrar la vista: '
                                     f'{vistas.e(exc)}</div></section>')
        return regiones

    def _principal(self, ev: Dict[str, Any]) -> str:
        if self.vista == "equipo":
            eq = self.proyecto.buscar_equipo(self.tag or "")
            if eq is None:
                self.vista = "panel"
            else:
                return vistas.vista_equipo(self.proyecto, eq, ev["equipos"].get(eq.tag), ev["rbi"].get(eq.tag),
                                           self.pestana, self.cml_id, self.ubicando, self.fecha_evaluacion,
                                           ev["errores"].get(eq.tag), ev["errores"].get(eq.tag + " (RBI)"))
        if self.vista == "nuevo_equipo":
            return vistas.vista_nuevo_equipo(self.proyecto)
        if self.vista == "verificacion":
            return vistas.vista_verificacion(*self.verificacion())
        if self.vista == "normas":
            return vistas.vista_normas()
        return vistas.vista_panel(self.proyecto, ev, self.filtros)
