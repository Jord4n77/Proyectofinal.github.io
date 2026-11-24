"""
models.py — Estructuras de datos del prototipo de gestión de integridad.

Jerarquía (ubicación técnica)::

    Proyecto
     └─ Planta
         └─ Area
             └─ Sistema            (sistema, línea o circuito de inspección)
                 └─ Equipo         (TAG; familia TUBERIA | RECIPIENTE | TANQUE)
                     ├─ Documento  (isométrico, esquema o foto PNG/JPG; PDF de consulta)
                     ├─ DatosRBI   (opcional, entradas del módulo RBI)
                     └─ Componente (tramo recto, envolvente cilíndrica, virola n)
                         └─ CML    (ubicación de monitoreo / TML)
                             ├─ Medicion      (fecha, espesor, unidad, técnica, ...)
                             └─ Intervencion  (cambio de punto, reparación, reemplazo)

Principios
----------
* Solo datos: este módulo NO importa ``calc_engine`` ni el DOM. Los métodos
  ``a_dict_motor()`` entregan diccionarios primitivos que el motor consume, de
  modo que cálculo, modelo e interfaz quedan desacoplados.
* Unidades SI coherentes con el motor: MPa, mm, m (diámetro y altura de tanque),
  °C, años, m². Los espesores medidos conservan su unidad original ('mm' o 'in')
  y se convierten con ``Medicion.espesor_mm``.
* Serialización: ``Proyecto.a_json()`` / ``Proyecto.desde_json()`` generan un
  archivo de proyecto importable/exportable. La estructura anidada conserva las
  relaciones equipo → componente → CML → mediciones; los adjuntos se guardan en
  base64 dentro del mismo archivo (o como ruta, para restablecerlos).

Convención de marcadores CML sobre esquemas
-------------------------------------------
``marcador_x`` y ``marcador_y`` son fracciones (0–1) del ancho y alto de la
imagen del ``Documento`` asociado, con origen en la esquina SUPERIOR IZQUIERDA
(x hacia la derecha, y hacia abajo). Así el marcador no depende de la resolución
con que se muestre la imagen.

Convención de identificación de CML (sugerida, se declara por punto)
--------------------------------------------------------------------
``<TAG>-CML-<nn>``; posición horaria 12-3-6-9 vista en el sentido del flujo
(tuberías) o desde el exterior con 0° al norte de planta (recipientes/tanques);
distancia axial desde la soldadura o línea de referencia indicada.
"""

from __future__ import annotations

import json
import typing
from dataclasses import dataclass, field, fields, is_dataclass
from datetime import date, datetime
from enum import Enum
from typing import Any, Dict, Iterator, List, Optional, Tuple

ESQUEMA_VERSION = "1.0"
MM_POR_PULGADA = 25.4


# =============================================================================
# Enumeraciones (sus valores coinciden con los códigos de texto del motor)
# =============================================================================

class Familia(str, Enum):
    TUBERIA = "TUBERIA"
    RECIPIENTE = "RECIPIENTE"
    TANQUE = "TANQUE"


class TipoComponente(str, Enum):
    TRAMO_RECTO = "TRAMO_RECTO"                     # tubería, ASME B31.3
    ENVOLVENTE_CILINDRICA = "ENVOLVENTE_CILINDRICA"  # recipiente, ASME VIII-1 UG-27
    VIROLA = "VIROLA"                               # tanque, API 650/653


class EventoMedicion(str, Enum):
    """Evento asociado a la medición. Los tres últimos reinician la línea base."""
    NORMAL = "NORMAL"
    CAMBIO_PUNTO = "CAMBIO_PUNTO"
    REPARACION = "REPARACION"
    REEMPLAZO = "REEMPLAZO"


class TipoIntervencion(str, Enum):
    CAMBIO_PUNTO = "CAMBIO_PUNTO"
    REPARACION = "REPARACION"
    REEMPLAZO = "REEMPLAZO"


class UnidadEspesor(str, Enum):
    MM = "mm"
    IN = "in"


class TecnicaMedicion(str, Enum):
    UT = "UT"                    # ultrasonido de contacto (palpador dual)
    UT_ESCANEO = "UT_ESCANEO"    # barrido / mapeo C-scan
    RT_PERFIL = "RT_PERFIL"      # radiografía de perfil
    OTRA = "OTRA"


class Efectividad(str, Enum):
    """Efectividad de inspección para adelgazamiento (API RP 581)."""
    A = "A"   # altamente efectiva
    B = "B"   # usualmente efectiva
    C = "C"   # medianamente efectiva
    D = "D"   # poco efectiva
    E = "E"   # inefectiva / sin inspección


class ConfianzaCR(str, Enum):
    BAJA = "BAJA"
    MEDIA = "MEDIA"
    ALTA = "ALTA"


class TipoDocumento(str, Enum):
    PNG = "PNG"
    JPG = "JPG"
    PDF = "PDF"


class EstadoCondicion(str, Enum):
    NORMAL = "NORMAL"
    ALERTA = "ALERTA"
    INSPECCION_VENCIDA = "INSPECCION_VENCIDA"
    BAJO_MINIMO = "BAJO_MINIMO"


class CodigoAlerta(str, Enum):
    DATOS_INSUFICIENTES = "DATOS_INSUFICIENTES"
    FECHAS_INCONSISTENTES = "FECHAS_INCONSISTENTES"
    CORROSION_NULA_O_NEGATIVA = "CORROSION_NULA_O_NEGATIVA"
    LINEA_BASE_REINICIADA = "LINEA_BASE_REINICIADA"
    BAJO_MINIMO = "BAJO_MINIMO"
    FUERA_DE_ALCANCE = "FUERA_DE_ALCANCE"
    NOMINAL_INSUFICIENTE = "NOMINAL_INSUFICIENTE"
    PROYECCION_BAJO_MINIMO = "PROYECCION_BAJO_MINIMO"


CODIGOS_POR_FAMILIA: Dict[Familia, Tuple[str, str]] = {
    Familia.TUBERIA: ("ASME B31.3", "API 570"),
    Familia.RECIPIENTE: ("ASME BPVC Sec. VIII Div. 1", "API 510"),
    Familia.TANQUE: ("API 650", "API 653"),
}

TIPO_COMPONENTE_POR_FAMILIA: Dict[Familia, TipoComponente] = {
    Familia.TUBERIA: TipoComponente.TRAMO_RECTO,
    Familia.RECIPIENTE: TipoComponente.ENVOLVENTE_CILINDRICA,
    Familia.TANQUE: TipoComponente.VIROLA,
}


# =============================================================================
# Datos de proceso y parámetros de cálculo
# =============================================================================

@dataclass
class CondicionesProceso:
    """Presión manométrica [MPa] y temperatura [°C] (diseño u operación)."""
    presion_MPa: float = 0.0
    temperatura_C: float = 20.0

    def __post_init__(self) -> None:
        if self.presion_MPa < 0:
            raise ValueError("La presión no puede ser negativa (use presión manométrica).")


@dataclass
class ParametrosCalculo:
    """Parámetros de cálculo del equipo (aplican a todos sus componentes salvo indicación).

    Campos generales
        sobreespesor_corrosion_mm (CA), eficiencia_junta (E), dt_margen_anios
        (plazo de intervención para t_alerta).
    Tuberías (B31.3 / API 570)
        factor_W, coeficiente_Y, tolerancia_fabricacion (fracción, 0.125 = 12.5 %),
        t_estructural_mm, clase_tuberia (1, 2, 3 o 'PUNTO_INYECCION').
    Recipientes (VIII-1 / API 510)
        tolerancia_placa_mm, regla_rl_menor_4 ('CONSERVADORA_1_4' | 'API_TEXTUAL').
    Tanques (API 650 / 653)
        diametro_tanque_m, altura_liquido_diseno_m, densidad_relativa_G,
        eficiencia_junta_servicio (API 653 Tabla 4.2).
    """
    sobreespesor_corrosion_mm: float = 0.0
    eficiencia_junta: float = 1.0
    dt_margen_anios: float = 2.0
    # Tuberías
    factor_W: float = 1.0
    coeficiente_Y: float = 0.4
    tolerancia_fabricacion: float = 0.125
    t_estructural_mm: float = 0.0
    clase_tuberia: Any = 2
    # Recipientes
    tolerancia_placa_mm: float = 0.0
    regla_rl_menor_4: Optional[str] = "CONSERVADORA_1_4"
    # Tanques
    diametro_tanque_m: Optional[float] = None
    altura_liquido_diseno_m: Optional[float] = None
    densidad_relativa_G: Optional[float] = None
    eficiencia_junta_servicio: float = 1.0

    def __post_init__(self) -> None:
        if self.sobreespesor_corrosion_mm < 0:
            raise ValueError("CA no puede ser negativo.")
        if not (0 < self.eficiencia_junta <= 1):
            raise ValueError("E debe estar en (0, 1].")
        if not (0 <= self.tolerancia_fabricacion < 1):
            raise ValueError("La tolerancia de fabricación es una fracción en [0, 1).")


# =============================================================================
# Documentos, mediciones e intervenciones
# =============================================================================

@dataclass
class Documento:
    """Isométrico, esquema o fotografía (PNG/JPG) o PDF de consulta.

    ``contenido_base64`` permite incluir el adjunto en el archivo de proyecto;
    alternativamente ``ruta`` apunta a un archivo publicado en el repositorio
    (p. ej. 'assets/img/L-1001.png') para restablecerlo explícitamente.
    """
    id: str
    nombre: str
    tipo: TipoDocumento = TipoDocumento.PNG
    descripcion: str = ""
    ruta: Optional[str] = None
    contenido_base64: Optional[str] = None
    ancho_px: Optional[int] = None
    alto_px: Optional[int] = None

    @property
    def admite_marcadores(self) -> bool:
        return self.tipo in (TipoDocumento.PNG, TipoDocumento.JPG)


@dataclass
class Medicion:
    """Medición de espesor en un CML/TML.

    ``valida = False`` la conserva en el historial pero la excluye del cálculo
    (p. ej. lectura dudosa). ``evento`` distinto de NORMAL reinicia la línea base
    comparable a partir de esta medición.
    """
    id: str
    fecha: date
    espesor: float
    unidad: UnidadEspesor = UnidadEspesor.MM
    tecnica: TecnicaMedicion = TecnicaMedicion.UT
    inspector: str = ""
    observaciones: str = ""
    valida: bool = True
    evento: EventoMedicion = EventoMedicion.NORMAL

    def __post_init__(self) -> None:
        if isinstance(self.fecha, str):
            self.fecha = date.fromisoformat(self.fecha[:10])
        if self.espesor <= 0:
            raise ValueError(f"Medición {self.id}: el espesor debe ser > 0.")

    @property
    def espesor_mm(self) -> float:
        return self.espesor * MM_POR_PULGADA if self.unidad == UnidadEspesor.IN else float(self.espesor)

    def a_dict_motor(self) -> Dict[str, Any]:
        """Formato de entrada de ``calc_engine.preparar_serie_espesores``."""
        return {"id": self.id, "fecha": self.fecha, "espesor": self.espesor,
                "unidad": self.unidad.value, "valida": self.valida, "evento": self.evento.value}


@dataclass
class Intervencion:
    """Cambio de punto, reparación o reemplazo que rompe la comparabilidad de la serie."""
    id: str
    fecha: date
    tipo: TipoIntervencion
    descripcion: str = ""
    espesor_nuevo_mm: Optional[float] = None

    def __post_init__(self) -> None:
        if isinstance(self.fecha, str):
            self.fecha = date.fromisoformat(self.fecha[:10])

    def a_dict_motor(self) -> Dict[str, Any]:
        return {"id": self.id, "fecha": self.fecha, "tipo": self.tipo.value}


@dataclass
class CML:
    """Ubicación de monitoreo de condición (CML) / punto de medición de espesor (TML)."""
    id: str
    descripcion_ubicacion: str = ""
    convencion: str = ("Posición horaria 12-3-6-9 vista en sentido del flujo; distancia axial "
                       "desde la soldadura de referencia aguas arriba.")
    posicion_horaria: Optional[str] = None
    distancia_referencia_mm: Optional[float] = None
    documento_id: Optional[str] = None
    marcador_x: Optional[float] = None    # fracción 0–1 del ancho (origen arriba-izquierda)
    marcador_y: Optional[float] = None    # fracción 0–1 del alto
    mediciones: List[Medicion] = field(default_factory=list)
    intervenciones: List[Intervencion] = field(default_factory=list)

    def __post_init__(self) -> None:
        for nombre in ("marcador_x", "marcador_y"):
            v = getattr(self, nombre)
            if v is not None and not (0.0 <= v <= 1.0):
                raise ValueError(f"CML {self.id}: {nombre} debe ser fracción entre 0 y 1.")

    def agregar_medicion(self, medicion: Medicion) -> None:
        if any(m.id == medicion.id for m in self.mediciones):
            raise ValueError(f"Ya existe una medición con id {medicion.id!r} en {self.id}.")
        self.mediciones.append(medicion)
        self.mediciones.sort(key=lambda m: m.fecha)

    def mediciones_motor(self) -> List[Dict[str, Any]]:
        return [m.a_dict_motor() for m in self.mediciones]

    def intervenciones_motor(self) -> List[Dict[str, Any]]:
        return [i.a_dict_motor() for i in self.intervenciones]


@dataclass
class Componente:
    """Componente evaluado de un equipo. Los campos geométricos usados dependen del tipo:

    * TRAMO_RECTO: ``diametro_exterior_mm``, ``t_nom_mm`` (NPS/cédula informativos).
    * ENVOLVENTE_CILINDRICA: ``radio_interior_mm``, ``t_nom_mm``.
    * VIROLA: ``numero_virola`` (1 = inferior), ``altura_virola_m``,
      ``nivel_sobre_fondo_virola_m`` (H para API 650/653, desde el fondo de esta
      virola al nivel de diseño), ``t_nom_mm``.
    ``t_min_mm_override`` permite fijar un t_min declarado (p. ej. de una
    evaluación FFS) en lugar del calculado.
    """
    id: str
    nombre: str
    tipo: TipoComponente
    t_nom_mm: float
    diametro_exterior_mm: Optional[float] = None
    nps: Optional[str] = None
    cedula: Optional[str] = None
    radio_interior_mm: Optional[float] = None
    numero_virola: Optional[int] = None
    altura_virola_m: Optional[float] = None
    nivel_sobre_fondo_virola_m: Optional[float] = None
    material_id: Optional[str] = None      # si difiere del material del equipo
    t_min_mm_override: Optional[float] = None
    cmls: List[CML] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.t_nom_mm <= 0:
            raise ValueError(f"Componente {self.id}: t_nom debe ser > 0.")
        requeridos = {
            TipoComponente.TRAMO_RECTO: ("diametro_exterior_mm",),
            TipoComponente.ENVOLVENTE_CILINDRICA: ("radio_interior_mm",),
            TipoComponente.VIROLA: ("numero_virola", "nivel_sobre_fondo_virola_m"),
        }[self.tipo]
        faltantes = [c for c in requeridos if getattr(self, c) is None]
        if faltantes:
            raise ValueError(f"Componente {self.id} ({self.tipo.value}): faltan {faltantes}.")


# =============================================================================
# RBI
# =============================================================================

@dataclass
class DatosRBI:
    """Entradas del módulo RBI por adelgazamiento generalizado (modelo académico).

    ``inspecciones``: conteo de inspecciones previas por efectividad, p. ej.
    {'B': 2, 'C': 1}. ``area_consecuencia_m2`` (C_A) y ``consecuencia_economica``
    (C_E) son datos de entrada del usuario, para el mismo escenario agregado y
    base anual. ``base_valoracion`` documenta qué incluye C_E (reparación,
    producción diferida, ambiente, ...) y su fecha.
    """
    tipo_componente_gff: str = "RECIPIENTE"
    gff_1_anio: Optional[float] = None
    confianza_cr: ConfianzaCR = ConfianzaCR.BAJA
    inspecciones: Dict[str, int] = field(default_factory=dict)
    puntaje_sistema_gestion: Optional[float] = None
    factor_ajuste: float = 1.0
    area_consecuencia_m2: float = 0.0
    consecuencia_economica: float = 0.0
    moneda: str = "USD"
    tasa_a_usd: Optional[float] = None
    base_valoracion: str = ""
    cml_referencia_id: Optional[str] = None   # CML cuya CR_gov alimenta el RBI (None = máx. del equipo)
    justificacion_cml_referencia: str = ""
    efectividad_propuesta: Efectividad = Efectividad.A
    horizonte_plan_anios: Optional[float] = None

    def __post_init__(self) -> None:
        for k, v in self.inspecciones.items():
            if k not in Efectividad.__members__ or int(v) < 0:
                raise ValueError(f"Inspecciones RBI inválidas: {k!r}: {v!r}.")
        if self.area_consecuencia_m2 < 0 or self.consecuencia_economica < 0:
            raise ValueError("Las consecuencias no pueden ser negativas.")


# =============================================================================
# Equipo y jerarquía de planta
# =============================================================================

@dataclass
class Equipo:
    """Equipo estático identificado por TAG.

    ``codigo_diseno`` y ``codigo_inspeccion`` se completan por familia si se
    dejan vacíos. Para tuberías, ``circuito_inspeccion`` identifica el circuito
    API 570 y ``parametros.clase_tuberia`` su clase.
    """
    tag: str
    descripcion: str
    familia: Familia
    material_id: str
    servicio: str = ""
    fluido: str = ""
    codigo_diseno: str = ""
    codigo_inspeccion: str = ""
    circuito_inspeccion: Optional[str] = None
    fecha_puesta_servicio: Optional[date] = None
    diseno: CondicionesProceso = field(default_factory=CondicionesProceso)
    operacion: CondicionesProceso = field(default_factory=CondicionesProceso)
    parametros: ParametrosCalculo = field(default_factory=ParametrosCalculo)
    documentos: List[Documento] = field(default_factory=list)
    componentes: List[Componente] = field(default_factory=list)
    rbi: Optional[DatosRBI] = None

    def __post_init__(self) -> None:
        if not self.tag.strip():
            raise ValueError("El TAG del equipo es obligatorio.")
        if isinstance(self.fecha_puesta_servicio, str):
            self.fecha_puesta_servicio = date.fromisoformat(self.fecha_puesta_servicio[:10])
        dis, ins = CODIGOS_POR_FAMILIA[self.familia]
        self.codigo_diseno = self.codigo_diseno or dis
        self.codigo_inspeccion = self.codigo_inspeccion or ins

    def edad_servicio_anios(self, fecha_evaluacion: date) -> Optional[float]:
        if self.fecha_puesta_servicio is None:
            return None
        return (fecha_evaluacion - self.fecha_puesta_servicio).days / 365.25

    def iter_cmls(self) -> Iterator[Tuple[Componente, CML]]:
        for comp in self.componentes:
            for cml in comp.cmls:
                yield comp, cml

    def documento(self, doc_id: str) -> Optional[Documento]:
        return next((d for d in self.documentos if d.id == doc_id), None)


@dataclass
class Sistema:
    """Sistema, línea o circuito dentro de un área."""
    id: str
    nombre: str
    equipos: List[Equipo] = field(default_factory=list)


@dataclass
class Area:
    id: str
    nombre: str
    sistemas: List[Sistema] = field(default_factory=list)


@dataclass
class Planta:
    id: str
    nombre: str
    areas: List[Area] = field(default_factory=list)


@dataclass
class Proyecto:
    """Contenedor raíz: archivo de proyecto importable/exportable (JSON)."""
    nombre: str
    plantas: List[Planta] = field(default_factory=list)
    fecha_evaluacion: Optional[date] = None
    ediciones_normativas: Dict[str, str] = field(default_factory=dict)
    criterios_grupo: Dict[str, Any] = field(default_factory=dict)
    notas: str = ""
    version_esquema: str = ESQUEMA_VERSION

    # ------------------------------------------------------------------ consulta
    def iter_equipos(self) -> Iterator[Tuple[Planta, Area, Sistema, Equipo]]:
        for p in self.plantas:
            for a in p.areas:
                for s in a.sistemas:
                    for e in s.equipos:
                        yield p, a, s, e

    def buscar_equipo(self, tag: str) -> Optional[Equipo]:
        return next((e for *_, e in self.iter_equipos() if e.tag == tag), None)

    def ubicacion_tecnica(self, tag: str) -> Optional[str]:
        """Ruta 'Planta / Área / Sistema / TAG' del equipo."""
        for p, a, s, e in self.iter_equipos():
            if e.tag == tag:
                return f"{p.nombre} / {a.nombre} / {s.nombre} / {e.tag}"
        return None

    def buscar_cml(self, cml_id: str) -> Optional[Tuple[Equipo, Componente, CML]]:
        for *_, e in self.iter_equipos():
            for comp, cml in e.iter_cmls():
                if cml.id == cml_id:
                    return e, comp, cml
        return None

    def filtrar_equipos(self, familia: Optional[Familia] = None, planta_id: Optional[str] = None,
                        area_id: Optional[str] = None, sistema_id: Optional[str] = None) -> List[Equipo]:
        """Filtro por ubicación y familia (el filtro por condición se hace con resultados del motor)."""
        salida = []
        for p, a, s, e in self.iter_equipos():
            if familia is not None and e.familia != familia:
                continue
            if planta_id and p.id != planta_id:
                continue
            if area_id and a.id != area_id:
                continue
            if sistema_id and s.id != sistema_id:
                continue
            salida.append(e)
        return salida

    def validar_integridad(self) -> List[str]:
        """Revisa unicidad de TAG/CML/medición y referencias a documentos."""
        problemas: List[str] = []
        tags, cmls = set(), set()
        for *_, e in self.iter_equipos():
            if e.tag in tags:
                problemas.append(f"TAG duplicado: {e.tag}")
            tags.add(e.tag)
            esperado = TIPO_COMPONENTE_POR_FAMILIA[e.familia]
            for comp in e.componentes:
                if comp.tipo != esperado:
                    problemas.append(f"{e.tag}/{comp.id}: tipo {comp.tipo.value} no corresponde "
                                     f"a la familia {e.familia.value} (alcance: {esperado.value}).")
                for cml in comp.cmls:
                    if cml.id in cmls:
                        problemas.append(f"CML duplicado: {cml.id}")
                    cmls.add(cml.id)
                    if cml.documento_id:
                        doc = e.documento(cml.documento_id)
                        if doc is None:
                            problemas.append(f"{cml.id}: documento {cml.documento_id!r} inexistente.")
                        elif not doc.admite_marcadores:
                            problemas.append(f"{cml.id}: el documento {doc.id} es PDF (sin marcadores).")
                    ids = [m.id for m in cml.mediciones]
                    if len(ids) != len(set(ids)):
                        problemas.append(f"{cml.id}: ids de medición duplicados.")
            if e.rbi and e.rbi.cml_referencia_id and e.rbi.cml_referencia_id not in \
                    {c.id for _, c in e.iter_cmls()}:
                problemas.append(f"{e.tag}: CML de referencia RBI inexistente.")
        return problemas

    # ----------------------------------------------------------- serialización
    def a_dict(self) -> Dict[str, Any]:
        return _a_primitivo(self)

    def a_json(self, indent: int = 2) -> str:
        return json.dumps(self.a_dict(), ensure_ascii=False, indent=indent)

    @classmethod
    def desde_dict(cls, datos: Dict[str, Any]) -> "Proyecto":
        version = datos.get("version_esquema", ESQUEMA_VERSION)
        if version.split(".")[0] != ESQUEMA_VERSION.split(".")[0]:
            raise ValueError(f"Versión de esquema incompatible: {version} (se espera {ESQUEMA_VERSION}).")
        return _construir(cls, datos)

    @classmethod
    def desde_json(cls, texto: str) -> "Proyecto":
        return cls.desde_dict(json.loads(texto))


# =============================================================================
# Serialización genérica dataclass ⇄ primitivos JSON
# =============================================================================

def _a_primitivo(obj: Any) -> Any:
    if is_dataclass(obj) and not isinstance(obj, type):
        return {f.name: _a_primitivo(getattr(obj, f.name)) for f in fields(obj)}
    if isinstance(obj, Enum):
        return obj.value
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()[:10]
    if isinstance(obj, (list, tuple)):
        return [_a_primitivo(x) for x in obj]
    if isinstance(obj, dict):
        return {str(k): _a_primitivo(v) for k, v in obj.items()}
    return obj


def _construir(tipo: Any, valor: Any) -> Any:
    """Reconstruye un valor tipado a partir de primitivos JSON usando las anotaciones."""
    if valor is None:
        return None
    origen = typing.get_origin(tipo)
    args = typing.get_args(tipo)
    if origen is typing.Union:                       # Optional[X]
        no_nulos = [a for a in args if a is not type(None)]
        return _construir(no_nulos[0], valor) if len(no_nulos) == 1 else valor
    if origen in (list, List):
        return [_construir(args[0], v) for v in valor] if args else list(valor)
    if origen in (dict, Dict):
        return {k: _construir(args[1], v) for k, v in valor.items()} if args else dict(valor)
    if origen in (tuple, Tuple):
        return tuple(valor)
    if tipo is Any:
        return valor
    if isinstance(tipo, type) and is_dataclass(tipo):
        hints = typing.get_type_hints(tipo)
        kwargs = {f.name: _construir(hints[f.name], valor[f.name])
                  for f in fields(tipo) if f.name in valor}
        return tipo(**kwargs)
    if isinstance(tipo, type) and issubclass(tipo, Enum):
        return tipo(valor)
    if tipo is date:
        return date.fromisoformat(str(valor)[:10])
    if tipo is float:
        return float(valor)
    if tipo is int:
        return int(valor)
    return valor
