"""
vista_previa.py — Capturas de la interfaz sin PyScript (para revisión y diapositivas).

Renderiza estados de la aplicación con el MISMO ``Controlador`` que usa el
navegador, arma páginas HTML estáticas con ``web/estilos.css`` y toma capturas
con Chrome sin interfaz (Playwright). No requiere conexión a internet.

Uso:  python tools/vista_previa.py [carpeta_salida]      (por defecto: capturas/)
"""

from __future__ import annotations

import os
import re
import shutil
import sys
from datetime import date

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(RAIZ, "src"))
from controlador import Controlador  # noqa: E402

ESCENAS = [
    ("01_panel", [("ver_panel", {})]),
    ("02_tuberia_antecedentes", [("ver_equipo", {"tag": "L-1001"})]),
    ("03_tuberia_espesores", [("ver_equipo", {"tag": "L-1001"}), ("pestana", {"valor": "espesores"})]),
    ("04_cml_alerta", [("ver_cml", {"tag": "L-1001", "cml": "L-1001-CML-02"})]),
    ("05_cml_reemplazo", [("ver_cml", {"tag": "L-1001", "cml": "L-1001-CML-03"})]),
    ("06_recipiente_bajo_minimo", [("ver_cml", {"tag": "V-2001", "cml": "V-2001-CML-02"})]),
    ("07_tanque_espesores", [("ver_equipo", {"tag": "T-3001"}), ("pestana", {"valor": "espesores"})]),
    ("08_tanque_fechas", [("ver_cml", {"tag": "T-3001", "cml": "T-3001-CML-03"})]),
    ("09_rbi_recipiente", [("ver_rbi", {"tag": "V-2001"})]),
    ("10_verificacion", [("ver_verificacion", {})]),
    ("11_nuevo_equipo", [("nuevo_equipo", {})]),
    ("12_normas", [("ver_normas", {})]),
    ("13_medicion_agregada", [("agregar_medicion", {"cml": "L-1001-CML-04", "fecha": "2026-11-20", "espesor": "6,70",
                                                    "unidad": "mm", "tecnica": "UT", "evento": "NORMAL", "valida": "1"})]),
]


def pagina(regiones: dict) -> str:
    with open(os.path.join(RAIZ, "index.html"), encoding="utf-8") as f:
        html = f.read()
    html = re.sub(r'<script type="module"[^>]*></script>', "", html)
    html = re.sub(r'<link rel="stylesheet" href="https://pyscript[^>]*>', "", html)
    html = re.sub(r'<script type="py"[^>]*></script>', "", html)
    html = html.replace("<body>", '<body class="listo">')
    for rid, contenido in regiones.items():
        html = re.sub(rf'(<(?:header|div|aside|main) id="{rid}"[^>]*>)(</(?:header|div|aside|main)>)',
                      lambda m: m.group(1) + contenido.replace("\\", "\\\\") + m.group(2), html, count=1)
    return html


def main(salida: str) -> None:
    from playwright.sync_api import sync_playwright
    os.makedirs(os.path.join(salida, "web"), exist_ok=True)
    shutil.copy(os.path.join(RAIZ, "web", "estilos.css"), os.path.join(salida, "web", "estilos.css"))
    with open(os.path.join(RAIZ, "data", "proyecto_demo.json"), encoding="utf-8") as f:
        demo = f.read()
    with sync_playwright() as pw:
        nav = pw.chromium.launch(executable_path=shutil.which("google-chrome") or None)
        hoja = nav.new_page(viewport={"width": 1440, "height": 900}, device_scale_factor=1)
        for nombre, acciones in ESCENAS:
            c = Controlador(demo, hoy=date(2026, 11, 23))
            for accion, datos in acciones:
                c.despachar(accion, datos)
            ruta = os.path.join(salida, nombre + ".html")
            with open(ruta, "w", encoding="utf-8") as f:
                f.write(pagina(c.renderizar()))
            hoja.goto("file://" + os.path.abspath(ruta))
            hoja.wait_for_timeout(150)
            hoja.screenshot(path=os.path.join(salida, nombre + ".png"), full_page=True)
            print("captura", nombre)
        nav.close()


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else os.path.join(RAIZ, "capturas"))
