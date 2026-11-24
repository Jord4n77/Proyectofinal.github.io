"""Pruebas del modelo de datos: jerarquía, validación y respaldo JSON."""

from datetime import date

import pytest

import calc_engine as ce
from models import (CML, Area, Componente, DatosRBI, Documento, Equipo, EventoMedicion, Familia,
                    Medicion, ParametrosCalculo, Planta, Proyecto, Sistema, TipoComponente,
                    TipoDocumento, UnidadEspesor, CodigoAlerta, EstadoCondicion)


def _proyecto():
    cml = CML(id="L-1001-CML-01", descripcion_ubicacion="Tramo recto aguas abajo de V-2",
              documento_id="ISO-1", marcador_x=0.42, marcador_y=0.31,
              mediciones=[Medicion("M1", date(2015, 1, 1), 7.1),
                          Medicion("M2", "2020-01-01", 6.6),
                          Medicion("M3", date(2025, 1, 1), 0.24, unidad=UnidadEspesor.IN)])
    comp = Componente(id="TR-01", nombre="Tramo recto 1", tipo=TipoComponente.TRAMO_RECTO,
                      t_nom_mm=7.11, diametro_exterior_mm=168.3, nps="6", cedula="40", cmls=[cml])
    eq = Equipo(tag="L-1001", descripcion="Línea de nafta", familia=Familia.TUBERIA,
                material_id="A106-B", circuito_inspeccion="CIR-01",
                parametros=ParametrosCalculo(sobreespesor_corrosion_mm=1.5, clase_tuberia=2),
                documentos=[Documento("ISO-1", "Isométrico L-1001", TipoDocumento.PNG,
                                      ruta="assets/img/L-1001.png")],
                componentes=[comp], rbi=DatosRBI(tipo_componente_gff="TUBERIA",
                                                 inspecciones={"B": 1}, area_consecuencia_m2=120,
                                                 consecuencia_economica=3e5,
                                                 cml_referencia_id="L-1001-CML-01"))
    return Proyecto(nombre="Demo", fecha_evaluacion=date(2026, 11, 23),
                    ediciones_normativas=dict(ce.EDICIONES_NORMATIVAS),
                    plantas=[Planta("P1", "Refinería Demo", [Area("A1", "Unidad 100",
                             [Sistema("S1", "Circuito nafta", [eq])])])])


def test_codigos_por_familia_y_ubicacion():
    p = _proyecto()
    eq = p.buscar_equipo("L-1001")
    assert eq.codigo_diseno == "ASME B31.3" and eq.codigo_inspeccion == "API 570"
    assert p.ubicacion_tecnica("L-1001") == "Refinería Demo / Unidad 100 / Circuito nafta / L-1001"
    assert p.validar_integridad() == []


def test_roundtrip_json_conserva_relaciones():
    p = _proyecto()
    p2 = Proyecto.desde_json(p.a_json())
    assert p2.a_dict() == p.a_dict()
    eq, comp, cml = p2.buscar_cml("L-1001-CML-01")
    assert eq.tag == "L-1001" and comp.id == "TR-01"
    assert isinstance(cml.mediciones[1].fecha, date)
    assert cml.mediciones[2].espesor_mm == pytest.approx(6.096)
    assert eq.rbi.inspecciones == {"B": 1}


def test_medicion_a_motor_y_evaluacion():
    p = _proyecto()
    _, _, cml = p.buscar_cml("L-1001-CML-01")
    r = ce.evaluar_punto_espesor("TUBERIA", cml.mediciones_motor(), 3.0, p.fecha_evaluacion)
    assert r["resultado"]["estado"] in ce.ESTADOS


def test_validaciones_de_modelo():
    with pytest.raises(ValueError):
        Medicion("X", date(2020, 1, 1), -1.0)
    with pytest.raises(ValueError):
        CML(id="C", marcador_x=1.5)
    with pytest.raises(ValueError):
        Componente(id="V1", nombre="Virola 1", tipo=TipoComponente.VIROLA, t_nom_mm=12.0)
    p = _proyecto()
    p.buscar_equipo("L-1001").componentes[0].cmls[0].documento_id = "NO-EXISTE"
    assert any("inexistente" in x for x in p.validar_integridad())


def test_enums_coinciden_con_codigos_del_motor():
    assert {c.value for c in CodigoAlerta} == set(ce.CODIGOS_ALERTA)
    assert {e.value for e in EstadoCondicion} == set(ce.ESTADOS)
    assert {e.value for e in EventoMedicion} == set(ce.EVENTOS_MEDICION)
    assert {f.value for f in Familia} == set(ce.FAMILIAS)
