"""
web/main.py — Conexión entre la página (DOM) y el controlador Python.

Se ejecuta en el navegador con PyScript (Pyodide). Responsabilidades:

* delegar clics (``data-accion``), envíos de formulario (``data-form``) y cambios
  de formularios automáticos (``data-auto="1"``) al ``Controlador``;
* insertar en la página las regiones HTML que devuelve ``Controlador.renderizar``;
* resolver lo propio del navegador: ``localStorage`` (guardar/recuperar),
  descarga del archivo de proyecto, carga de archivos (.json y PNG/JPG) y la
  fecha local "hoy".

Toda la lógica de cálculo y de interfaz vive en ``src/`` y se prueba con pytest.
"""

import asyncio
import base64
import traceback
from datetime import date

import js
from pyodide.ffi import create_once_callable, create_proxy, to_js
from pyscript import document, window

try:  # Pyodide ≥ 0.28 (PyScript ≥ 2025.8) convierte el null de JS en jsnull, no en None
    from pyodide.ffi import jsnull as _JSNULL
except ImportError:  # versiones anteriores: null → None
    _JSNULL = None

from controlador import Controlador

CLAVE_ALMACEN = "integridad-estaticos/proyecto/v1"
ATRIBUTOS = ("tag", "cml", "med", "comp", "valor")
ctrl = None
_proxies = []


def nulo(x) -> bool:
    """True si x es None o el null de JavaScript (jsnull)."""
    return x is None or (_JSNULL is not None and x is _JSNULL) or type(x).__name__ == "JsNull"


def _obj(diccionario):
    """dict de Python → objeto JS plano."""
    return to_js(diccionario, dict_converter=js.Object.fromEntries)


def hoy_local() -> date:
    d = js.Date.new()
    return date(int(d.getFullYear()), int(d.getMonth()) + 1, int(d.getDate()))


# --------------------------------------------------------------------- almacenamiento
def leer_almacen():
    try:
        valor = window.localStorage.getItem(CLAVE_ALMACEN)
        return None if nulo(valor) else str(valor)
    except Exception:  # navegación privada o almacenamiento bloqueado
        return None


def guardar_almacen() -> None:
    try:
        window.localStorage.setItem(CLAVE_ALMACEN, ctrl.exportar_json())
        ctrl.marcar_guardado()
        ctrl.mensaje("ok", "Proyecto guardado en el almacenamiento de este navegador.")
    except Exception as exc:
        ctrl.mensaje("error", f"No se pudo guardar en el navegador ({exc}). Use «Exportar» para descargar el archivo.")


def descargar(texto: str, nombre: str) -> None:
    blob = js.Blob.new(to_js([texto]), _obj({"type": "application/json"}))
    url = js.URL.createObjectURL(blob)
    enlace = document.createElement("a")
    enlace.href = url
    enlace.download = nombre
    document.body.appendChild(enlace)
    enlace.click()
    enlace.remove()
    js.setTimeout(create_once_callable(lambda: js.URL.revokeObjectURL(url)), 2000)


# --------------------------------------------------------------------- pintado
def pintar() -> None:
    regiones = ctrl.renderizar()
    for rid, html in regiones.items():
        el = document.getElementById(rid)
        if not nulo(el):
            el.innerHTML = html
    if ctrl.desplazar_a:
        destino = document.getElementById(ctrl.desplazar_a)
        if not nulo(destino):
            destino.scrollIntoView(_obj({"behavior": "smooth", "block": "start"}))
        ctrl.desplazar_a = None


def ejecutar(accion: str, datos: dict) -> None:
    """Acciones propias del navegador o despacho al controlador; luego repinta."""
    if accion == "importar":
        document.getElementById("archivo-proyecto").click()
        return
    if accion == "guardar_local":
        ctrl.mensajes = []
        guardar_almacen()
    elif accion == "exportar":
        ctrl.mensajes = []
        descargar(ctrl.exportar_json(), ctrl.nombre_archivo())
        ctrl.mensaje("ok", f"Archivo {ctrl.nombre_archivo()} descargado (incluye adjuntos y relaciones).")
    else:
        ctrl.despachar(accion, datos)
    pintar()


def datos_de(el) -> dict:
    return {k: str(el.getAttribute("data-" + k)) for k in ATRIBUTOS if el.hasAttribute("data-" + k)}


# --------------------------------------------------------------------- eventos
def al_click(evt) -> None:
    el = evt.target.closest("[data-accion]")
    if nulo(el):
        return
    evt.preventDefault()
    accion = str(el.getAttribute("data-accion"))
    datos = datos_de(el)
    if accion == "ubicar_marcador":
        rect = el.getBoundingClientRect()
        datos["x"] = str((evt.clientX - rect.left) / rect.width)
        datos["y"] = str((evt.clientY - rect.top) / rect.height)
    try:
        ejecutar(accion, datos)
    except Exception:
        traceback.print_exc()


async def enviar_formulario(form, nombre: str) -> None:
    datos = datos_de(form)
    for par in js.FormData.new(form).entries():
        clave, valor = str(par[0]), par[1]
        if isinstance(valor, str):
            datos[clave] = valor
        elif getattr(valor, "size", 0):                       # archivo
            contenido = await valor.arrayBuffer()
            datos[clave + "_base64"] = base64.b64encode(contenido.to_bytes()).decode("ascii")
            datos[clave + "_tipo"] = str(valor.type)
            datos[clave + "_nombre"] = str(valor.name)
    try:
        ejecutar(nombre, datos)
    except Exception:
        traceback.print_exc()


def al_enviar(evt) -> None:
    form = evt.target
    nombre = form.getAttribute("data-form")
    if nulo(nombre) or not nombre:
        return
    evt.preventDefault()
    asyncio.ensure_future(enviar_formulario(form, str(nombre)))


async def importar_archivo(entrada) -> None:
    archivo = entrada.files.item(0)
    if nulo(archivo):
        return
    texto = await archivo.text()
    ctrl.importar_json(str(texto), f"el archivo {archivo.name}")
    entrada.value = ""
    pintar()


def al_cambiar(evt) -> None:
    t = evt.target
    if t.id == "archivo-proyecto":
        asyncio.ensure_future(importar_archivo(t))
        return
    form = t.form
    if not nulo(form) and form.getAttribute("data-auto") == "1":
        asyncio.ensure_future(enviar_formulario(form, str(form.getAttribute("data-form"))))


def antes_de_salir(evt) -> None:
    if ctrl is not None and ctrl.sucio:
        evt.preventDefault()
        evt.returnValue = ""


# --------------------------------------------------------------------- inicio
def iniciar() -> None:
    global ctrl
    with open("proyecto_demo.json", encoding="utf-8") as f:
        demo = f.read()
    ctrl = Controlador(demo, demo_json=demo, hoy=hoy_local())
    guardado = leer_almacen()
    if guardado and ctrl.importar_json(guardado, "el almacenamiento del navegador"):
        ctrl.mensajes = [("ok", "Se recuperó el proyecto guardado en este navegador. "
                                "«Restablecer demo» vuelve al caso original.")]
    for tipo, fn in (("click", al_click), ("submit", al_enviar), ("change", al_cambiar)):
        proxy = create_proxy(fn)
        _proxies.append(proxy)
        document.addEventListener(tipo, proxy)
    proxy = create_proxy(antes_de_salir)
    _proxies.append(proxy)
    window.addEventListener("beforeunload", proxy)
    pintar()
    document.body.classList.add("listo")


try:
    iniciar()
except Exception as exc:  # muestra el error en la pantalla de carga
    traceback.print_exc()
    caja = document.getElementById("carga-error")
    if not nulo(caja):
        caja.textContent = f"No se pudo iniciar la aplicación: {exc}"
