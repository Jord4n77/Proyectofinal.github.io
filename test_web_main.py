"""
Prueba de ``web/main.py`` con un DOM simulado.

Se reemplazan los módulos ``js``, ``pyscript`` y ``pyodide.ffi`` por dobles
mínimos para ejecutar la capa de conexión en CPython: arranque, delegación de
clics, formularios (incluido archivo), almacenamiento, exportación e importación.
"""

import asyncio
import importlib.util
import os
import shutil
import sys
import types
from types import SimpleNamespace

import pytest

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PNG = bytes.fromhex("89504e470d0a1a0a0000000d4948445200000001000000010806000000"
                    "1f15c4890000000d49444154789c6360000002000154a24f5d0000000049454e44ae426082")


class JsNull:
    """Doble del null de JavaScript en Pyodide ≥ 0.28 (no es None)."""
    def __repr__(self):
        return "jsnull"


JSNULL = JsNull()


class ListaClases(set):
    def add(self, *xs):
        for x in xs:
            set.add(self, x)


class Elemento:
    def __init__(self, attrs=None, id="", padre=None, form=None):
        self.attrs = dict(attrs or {})
        self.id = id
        self.padre = padre
        self.form = form if form is not None else JSNULL
        self.innerHTML = ""
        self.textContent = ""
        self.value = ""
        self.files = None
        self.clics = 0
        self.href = self.download = ""
        self.classList = ListaClases()
        self.desplazado = False

    def getAttribute(self, k):
        return self.attrs.get(k, JSNULL)

    def hasAttribute(self, k):
        return k in self.attrs

    def closest(self, _sel):
        el = self
        while el is not None:
            if "data-accion" in el.attrs:
                return el
            el = el.padre
        return JSNULL

    def click(self):
        self.clics += 1

    def remove(self):
        pass

    def appendChild(self, _x):
        pass

    def scrollIntoView(self, *_):
        self.desplazado = True

    def getBoundingClientRect(self):
        return SimpleNamespace(left=100, top=50, width=1000, height=500)


class Formulario(Elemento):
    def __init__(self, nombre, entradas, attrs=None):
        super().__init__({"data-form": nombre, **(attrs or {})})
        self.entradas = entradas


class Archivo:
    def __init__(self, contenido: bytes, tipo: str, nombre: str):
        self.size, self.type, self.name, self._c = len(contenido), tipo, nombre, contenido

    async def arrayBuffer(self):
        return SimpleNamespace(to_bytes=lambda: self._c)

    async def text(self):
        return self._c.decode("utf-8")


class Documento:
    def __init__(self):
        self.elementos = {k: Elemento(id=k) for k in
                          ("encabezado", "lateral", "mensajes", "principal", "carga-error", "archivo-proyecto",
                           "detalle-cml")}
        self.body = Elemento()
        self.manejadores = {}
        self.creados = []

    def getElementById(self, k):
        return self.elementos.get(k, JSNULL)

    def createElement(self, _tag):
        el = Elemento()
        self.creados.append(el)
        return el

    def addEventListener(self, tipo, fn):
        self.manejadores[tipo] = fn


class Almacen(dict):
    def getItem(self, k):
        return self.get(k, JSNULL)

    def setItem(self, k, v):
        self[k] = v


class Evento:
    def __init__(self, target, **kw):
        self.target = target
        self.prevenido = False
        self.returnValue = None
        self.__dict__.update(kw)

    def preventDefault(self):
        self.prevenido = True


def _modulos_falsos(documento, almacen):
    js = types.ModuleType("js")
    js.Date = SimpleNamespace(new=lambda: SimpleNamespace(getFullYear=lambda: 2026, getMonth=lambda: 10,
                                                          getDate=lambda: 23))
    js.Blob = SimpleNamespace(new=lambda partes, opciones: SimpleNamespace(partes=partes, opciones=opciones))
    js.URL = SimpleNamespace(createObjectURL=lambda b: "blob:prueba", revokeObjectURL=lambda u: None)
    js.Object = SimpleNamespace(fromEntries=dict)
    js.setTimeout = lambda fn, ms: fn()
    js.FormData = SimpleNamespace(new=lambda form: SimpleNamespace(entries=lambda: [[k, v] for k, v in form.entradas]))
    pyscript = types.ModuleType("pyscript")
    pyscript.document = documento
    pyscript.window = SimpleNamespace(localStorage=almacen, addEventListener=lambda t, f: setattr(documento, "salir", f))
    pyodide = types.ModuleType("pyodide")
    ffi = types.ModuleType("pyodide.ffi")
    ffi.create_proxy = ffi.create_once_callable = lambda f: f
    ffi.to_js = lambda x, **_: x
    ffi.jsnull = JSNULL
    pyodide.ffi = ffi
    return {"js": js, "pyscript": pyscript, "pyodide": pyodide, "pyodide.ffi": ffi}


def cargar_main(tmp_path, monkeypatch, almacen=None):
    shutil.copy(os.path.join(RAIZ, "data", "proyecto_demo.json"), tmp_path / "proyecto_demo.json")
    monkeypatch.chdir(tmp_path)
    documento, almacen = Documento(), almacen if almacen is not None else Almacen()
    for nombre, mod in _modulos_falsos(documento, almacen).items():
        monkeypatch.setitem(sys.modules, nombre, mod)
    spec = importlib.util.spec_from_file_location("web_main_prueba", os.path.join(RAIZ, "web", "main.py"))
    main = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(main)
    return main, documento, almacen


def test_arranque(tmp_path, monkeypatch):
    main, doc, _ = cargar_main(tmp_path, monkeypatch)
    assert "listo" in doc.body.classList
    assert doc.elementos["carga-error"].textContent == ""
    assert "Panel de resultados" in doc.elementos["principal"].innerHTML
    assert set(doc.manejadores) == {"click", "submit", "change"}


def test_clic_delegado(tmp_path, monkeypatch):
    main, doc, _ = cargar_main(tmp_path, monkeypatch)
    fila = Elemento({"data-accion": "ver_cml", "data-tag": "V-2001", "data-cml": "V-2001-CML-02"})
    celda = Elemento(padre=fila)                                  # clic en un hijo de la fila
    ev = Evento(celda)
    doc.manejadores["click"](ev)
    assert ev.prevenido
    assert "V-2001-CML-02" in doc.elementos["principal"].innerHTML
    assert doc.elementos["detalle-cml"].desplazado
    doc.manejadores["click"](Evento(Elemento()))                  # clic sin acción (closest → jsnull)
    doc.manejadores["change"](Evento(Elemento()))                 # cambio fuera de formulario (form → jsnull)
    doc.manejadores["submit"](Evento(Elemento()))                 # formulario sin data-form


def test_ubicar_marcador_por_clic(tmp_path, monkeypatch):
    main, doc, _ = cargar_main(tmp_path, monkeypatch)
    main.ctrl.despachar("iniciar_ubicacion", {"cml": "V-2001-CML-01"})
    esquema = Elemento({"data-accion": "ubicar_marcador", "data-tag": "V-2001", "data-cml": "V-2001-CML-01"})
    doc.manejadores["click"](Evento(esquema, clientX=600, clientY=300))
    cml = main.ctrl.proyecto.buscar_cml("V-2001-CML-01")[2]
    assert (cml.marcador_x, cml.marcador_y) == (0.5, 0.5)


def test_formulario_medicion_y_archivo(tmp_path, monkeypatch):
    main, doc, _ = cargar_main(tmp_path, monkeypatch)
    form = Formulario("agregar_medicion", [("fecha", "2026-11-20"), ("espesor", "6,70"), ("unidad", "mm"),
                                           ("tecnica", "UT"), ("evento", "NORMAL"), ("valida", "1")],
                      {"data-tag": "L-1001", "data-cml": "L-1001-CML-04"})
    asyncio.run(main.enviar_formulario(form, "agregar_medicion"))
    assert len(main.ctrl.proyecto.buscar_cml("L-1001-CML-04")[2].mediciones) == 2
    assert "agregada" in doc.elementos["mensajes"].innerHTML
    form = Formulario("subir_esquema", [("archivo", Archivo(PNG, "image/png", "nuevo.png")), ("nombre", "Nuevo")],
                      {"data-tag": "T-3001"})
    asyncio.run(main.enviar_formulario(form, "subir_esquema"))
    assert main.ctrl.proyecto.buscar_equipo("T-3001").documentos[0].nombre == "Nuevo"


def test_envio_y_cambio_automatico(tmp_path, monkeypatch):
    main, doc, _ = cargar_main(tmp_path, monkeypatch)
    form = Formulario("filtros", [("familia", "TANQUE"), ("area", ""), ("estado", "")], {"data-auto": "1"})
    selector = Elemento(form=form)

    async def flujo():
        doc.manejadores["change"](Evento(selector))
        ev = Evento(Formulario("ver_normas", []))
        doc.manejadores["submit"](ev)
        assert ev.prevenido
        for _ in range(3):
            await asyncio.sleep(0)
    asyncio.run(flujo())
    assert main.ctrl.filtros["familia"] == "TANQUE"
    assert main.ctrl.vista == "normas"


def test_guardar_recuperar_exportar_importar(tmp_path, monkeypatch):
    main, doc, almacen = cargar_main(tmp_path, monkeypatch)
    main.ctrl.despachar("agregar_medicion", {"cml": "T-3001-CML-02", "fecha": "2026-11-22", "espesor": "8.95",
                                             "valida": "1"})
    salir = Evento(None)
    doc.salir(salir)
    assert salir.prevenido                                        # aviso de cambios sin guardar
    doc.manejadores["click"](Evento(Elemento({"data-accion": "guardar_local"})))
    assert main.CLAVE_ALMACEN in almacen and not main.ctrl.sucio
    doc.manejadores["click"](Evento(Elemento({"data-accion": "exportar"})))
    assert doc.creados[-1].clics == 1 and doc.creados[-1].download.endswith(".json")
    doc.manejadores["click"](Evento(Elemento({"data-accion": "importar"})))
    assert doc.elementos["archivo-proyecto"].clics == 1

    # recarga de la página: se recupera desde el almacenamiento
    main2, doc2, _ = cargar_main(tmp_path, monkeypatch, almacen)
    assert len(main2.ctrl.proyecto.buscar_cml("T-3001-CML-02")[2].mediciones) == 4
    assert "recuperó" in doc2.elementos["mensajes"].innerHTML

    # importar archivo
    entrada = doc2.elementos["archivo-proyecto"]
    with open(os.path.join(RAIZ, "data", "proyecto_demo.json"), "rb") as f:
        contenido = f.read()
    entrada.files = SimpleNamespace(item=lambda i: Archivo(contenido, "application/json", "demo.json"))
    asyncio.run(main2.importar_archivo(entrada))
    assert len(main2.ctrl.proyecto.buscar_cml("T-3001-CML-02")[2].mediciones) == 3
    assert "demo.json" in doc2.elementos["mensajes"].innerHTML
