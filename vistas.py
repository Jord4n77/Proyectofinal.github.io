"""
vistas.py — Generación de HTML y gráficos SVG (Python puro, sin DOM).

Cada función recibe datos del modelo y salidas del motor/servicios y devuelve
una cadena HTML. No modifica estado ni accede al navegador: el controlador
decide QUÉ mostrar y ``web/main.py`` solo inserta las cadenas en la página.
Así toda la interfaz se puede probar con pytest.

Convenciones de la interfaz
---------------------------
* Elementos clicables: atributo ``data-accion`` y datos ``data-tag``, ``data-cml``,
  ``data-med``, ``data-comp``, ``data-valor``.
* Formularios: atributo ``data-form`` (nombre de la acción). ``data-auto="1"``
  envía el formulario en cada cambio (filtros, fecha).
* Los gráficos son SVG generados aquí (no se carga Matplotlib, para reducir el
  tiempo de carga de Pyodide en GitHub Pages).
"""

from __future__ import annotations

import math
from datetime import date, timedelta
from html import escape
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import calc_engine as ce
from models import Efectividad, Equipo, Familia, Proyecto

# =============================================================================
# Etiquetas y utilidades
# =============================================================================

ETIQUETA_ESTADO = {
    "NORMAL": "Normal",
    "ALERTA": "Alerta",
    "INSPECCION_VENCIDA": "Inspección vencida",
    "BAJO_MINIMO": "Bajo mínimo",
}
ETIQUETA_FAMILIA = {"TUBERIA": "Tubería", "RECIPIENTE": "Recipiente", "TANQUE": "Tanque"}
NORMAS_FAMILIA = {"TUBERIA": "ASME B31.3 / API 570", "RECIPIENTE": "ASME VIII-1 / API 510",
                  "TANQUE": "API 650 / API 653"}
DESCRIPCION_ALERTA = {
    "DATOS_INSUFICIENTES": "Menos de 2 mediciones comparables: CR no determinable.",
    "FECHAS_INCONSISTENTES": "Fechas repetidas o posteriores a la evaluación.",
    "CORROSION_NULA_O_NEGATIVA": "CR ≤ 0: sin pérdida medible o dispersión de medición.",
    "LINEA_BASE_REINICIADA": "Serie reiniciada por cambio de punto, reparación o reemplazo.",
    "BAJO_MINIMO": "Espesor bajo el mínimo requerido.",
    "FUERA_DE_ALCANCE": "Fuera del alcance de la ecuación implementada.",
    "NOMINAL_INSUFICIENTE": "El espesor nominal no cubre el espesor de diseño.",
    "PROYECCION_BAJO_MINIMO": "El espesor proyectado a hoy ya estaría bajo t_min.",
}
ETIQUETA_NIVEL = {"BAJO": "Bajo", "MEDIO": "Medio", "MEDIO_ALTO": "Medio-alto", "ALTO": "Alto"}
ETIQUETA_EVENTO = {"NORMAL": "Normal", "CAMBIO_PUNTO": "Cambio de punto",
                   "REPARACION": "Reparación", "REEMPLAZO": "Reemplazo"}
MOTIVO_EXCLUSION = {
    "MARCADA_NO_VALIDA": "Marcada no válida",
    "ESPESOR_NO_POSITIVO": "Espesor ≤ 0",
    "FECHA_POSTERIOR_A_EVALUACION": "Fecha posterior a la evaluación",
    "ANTERIOR_A_LINEA_BASE": "Anterior a la línea base",
}
COLOR_ESTADO = {"NORMAL": "#15803d", "ALERTA": "#b45309",
                "INSPECCION_VENCIDA": "#6d28d9", "BAJO_MINIMO": "#b91c1c"}


def e(x: Any) -> str:
    """Escapa texto para HTML (None → cadena vacía)."""
    return "" if x is None else escape(str(x), quote=True)


def num(x: Any, d: int = 3) -> str:
    if x is None:
        return "—"
    if isinstance(x, bool):
        return "Sí" if x else "No"
    if isinstance(x, (int, float)):
        if isinstance(x, float) and not math.isfinite(x):
            return "∞"
        if x != 0 and (abs(x) < 10 ** (-d) or abs(x) >= 1e7):
            return f"{x:.3e}"
        return f"{x:,.{d}f}".replace(",", " ")
    return e(x)


def fecha(x: Any) -> str:
    if x is None:
        return "—"
    return x.isoformat() if isinstance(x, date) else e(x)


def _valor(v: Any) -> str:
    """Formato genérico para tablas de entradas/resultados."""
    if v is None:
        return "—"
    if isinstance(v, bool):
        return "Sí" if v else "No"
    if isinstance(v, float):
        return num(v, 4)
    if isinstance(v, int):
        return str(v)
    if isinstance(v, date):
        return v.isoformat()
    if isinstance(v, dict):
        if not v:
            return "—"
        return ", ".join(f"{e(k)}: {_valor(x)}" for k, x in v.items()) if len(v) <= 6 else f"{len(v)} elementos"
    if isinstance(v, (list, tuple)):
        if len(v) <= 6 and all(isinstance(x, (int, float, str)) for x in v):
            return "(" + ", ".join(_valor(x) for x in v) + ")"
        return f"{len(v)} elementos"
    return e(v)


def _data(**kw: Any) -> str:
    return " ".join(f'data-{k}="{e(v)}"' for k, v in kw.items() if v is not None)


def boton(texto: str, accion: str, clase: str = "", titulo: str = "", **data: Any) -> str:
    t = f' title="{e(titulo)}"' if titulo else ""
    return f'<button type="button" class="btn {clase}" data-accion="{e(accion)}" {_data(**data)}{t}>{texto}</button>'


def chip_estado(estado: Optional[str]) -> str:
    if not estado:
        return '<span class="chip est-sin">Sin evaluar</span>'
    return f'<span class="chip est-{estado.lower()}">{e(ETIQUETA_ESTADO.get(estado, estado))}</span>'


def chip_familia(familia: str) -> str:
    return f'<span class="chip fam">{e(ETIQUETA_FAMILIA.get(familia, familia))}</span>'


def chips_alertas(alertas: Iterable[str]) -> str:
    return "".join(f'<span class="chip alerta" title="{e(DESCRIPCION_ALERTA.get(a, ""))}">{e(a)}</span>'
                   for a in alertas)


def chip_nivel(nivel: Optional[str]) -> str:
    if not nivel:
        return "—"
    return f'<span class="chip riesgo-{nivel.lower()}">{e(ETIQUETA_NIVEL.get(nivel, nivel))}</span>'


def campo(nombre: str, etiqueta: str, valor: Any = "", tipo: str = "number", unidad: str = "",
          ayuda: str = "", requerido: bool = False, opciones: Optional[Sequence[Tuple[str, str]]] = None,
          clase: str = "", paso: str = "any", minimo: Optional[float] = None,
          maximo: Optional[float] = None, lista: Optional[str] = None) -> str:
    """Campo de formulario con etiqueta, unidad y ayuda."""
    req = " required" if requerido else ""
    if opciones is not None:
        ops = "".join(f'<option value="{e(v)}"{" selected" if str(v) == str(valor) else ""}>{e(t)}</option>'
                      for v, t in opciones)
        control = f'<select name="{e(nombre)}"{req}>{ops}</select>'
    elif tipo == "checkbox":
        marcado = " checked" if valor else ""
        return (f'<label class="campo check {clase}"><input type="checkbox" name="{e(nombre)}" value="1"{marcado}>'
                f'<span>{e(etiqueta)}</span></label>')
    elif tipo == "textarea":
        control = f'<textarea name="{e(nombre)}" rows="2"{req}>{e(valor)}</textarea>'
    else:
        extra = ""
        if tipo == "number":
            extra += f' step="{paso}" inputmode="decimal"'
            if minimo is not None:
                extra += f' min="{minimo}"'
            if maximo is not None:
                extra += f' max="{maximo}"'
        if lista:
            extra += f' list="{e(lista)}"'
        v = "" if valor is None else (valor.isoformat() if isinstance(valor, date) else valor)
        control = f'<input type="{tipo}" name="{e(nombre)}" value="{e(v)}"{extra}{req}>'
    u = f'<span class="u">{e(unidad)}</span>' if unidad else ""
    a = f'<small>{e(ayuda)}</small>' if ayuda else ""
    return f'<label class="campo {clase}"><span>{e(etiqueta)}</span><div class="ctl">{control}{u}</div>{a}</label>'


def _kpi(titulo: str, valor: str, sub: str = "", clase: str = "") -> str:
    s = f'<div class="kpi-sub">{sub}</div>' if sub else ""
    return f'<div class="kpi {clase}"><div class="kpi-t">{e(titulo)}</div><div class="kpi-v">{valor}</div>{s}</div>'


# =============================================================================
# Bloque de cálculo (entradas, ecuación, referencia, resultado, unidad, observaciones)
# =============================================================================

def bloque_calculo(titulo: str, r: Optional[Dict[str, Any]], abierto: bool = False,
                   principal: Optional[str] = None) -> str:
    """Muestra un resultado estándar del motor de forma trazable."""
    if not r:
        return ""
    res, uni = r.get("resultado"), r.get("unidad")
    if principal is None:
        if isinstance(res, dict):
            principal = ""
        else:
            principal = f"{_valor(res)} {e(uni) if isinstance(uni, str) else ''}"
    if isinstance(res, dict):
        filas_res = "".join(
            f'<tr><th>{e(k)}</th><td>{_valor(v)}</td><td class="u">{e(uni.get(k, "")) if isinstance(uni, dict) else ""}</td></tr>'
            for k, v in res.items() if not isinstance(v, (list,)) or len(v) <= 6)
    else:
        filas_res = f'<tr><th>resultado</th><td>{_valor(res)}</td><td class="u">{e(uni)}</td></tr>'
    filas_ent = "".join(f"<tr><th>{e(k)}</th><td>{_valor(v)}</td></tr>" for k, v in r.get("entradas", {}).items())
    obs = "".join(f"<li>{e(o)}</li>" for o in r.get("observaciones", []))
    obs_html = f'<ul class="obs">{obs}</ul>' if obs else ""
    alertas = chips_alertas(r.get("alertas", []))
    return f"""
<details class="calc"{" open" if abierto else ""}>
  <summary><span class="calc-t">{e(titulo)}</span><span class="calc-r">{principal}</span></summary>
  <div class="calc-c">
    <div class="calc-ec"><span class="lbl">Ecuación</span><code>{e(r.get("ecuacion_texto"))}</code></div>
    <div class="calc-ref"><span class="lbl">Referencia</span>{e(r.get("referencia_normativa"))}</div>
    <div class="calc-tablas">
      <div><div class="lbl">Entradas</div><table class="kv">{filas_ent}</table></div>
      <div><div class="lbl">Resultado</div><table class="kv">{filas_res}</table></div>
    </div>
    {obs_html}
    <div class="chips">{alertas}</div>
  </div>
</details>"""


# =============================================================================
# Encabezado, mensajes y barra lateral
# =============================================================================

def encabezado(proyecto: Proyecto, fecha_eval: date, vista: str, sucio: bool) -> str:
    def nav(texto: str, accion: str, activa: bool) -> str:
        return boton(texto, accion, "nav" + (" activo" if activa else ""))
    estado_guardado = ('<span class="sucio" title="Hay cambios que no se han guardado en este navegador">'
                       '● Cambios sin guardar</span>' if sucio else '<span class="limpio">✓ Guardado</span>')
    return f"""
<div class="marca">
  <div class="logo">⌀</div>
  <div><div class="app">Integridad de Equipos Estáticos</div>
  <div class="proy">{e(proyecto.nombre)}</div></div>
</div>
<nav class="nav-principal">
  {nav("Panel", "ver_panel", vista == "panel")}
  {nav("+ Equipo", "nuevo_equipo", vista == "nuevo_equipo")}
  {nav("Verificación", "ver_verificacion", vista == "verificacion")}
  {nav("Normas y supuestos", "ver_normas", vista == "normas")}
</nav>
<div class="herramientas">
  <form data-form="fecha" data-auto="1" class="fecha-eval">
    <label>Fecha de evaluación <input type="date" name="fecha" value="{fecha_eval.isoformat()}" required></label>
    {boton("Hoy", "fecha_hoy", "chico")}
  </form>
  {estado_guardado}
  {boton("Guardar", "guardar_local", "chico", "Guardar en el almacenamiento del navegador")}
  {boton("Exportar", "exportar", "chico", "Descargar archivo de proyecto .json")}
  {boton("Importar", "importar", "chico", "Cargar archivo de proyecto .json")}
  {boton("Restablecer demo", "restablecer_demo", "chico peligro", "Volver al caso demostrativo original")}
</div>"""


def mensajes(lista: Sequence[Tuple[str, str]]) -> str:
    if not lista:
        return ""
    items = "".join(f'<div class="msg msg-{e(t)}">{e(m)}</div>' for t, m in lista)
    return items + boton("Cerrar", "cerrar_mensajes", "chico")


def opciones_areas(proyecto: Proyecto) -> List[Tuple[str, str]]:
    return [("", "Todas las áreas")] + [(a.id, f"{p.nombre} · {a.nombre}") for p in proyecto.plantas for a in p.areas]


def lateral(proyecto: Proyecto, ev: Dict[str, Any], filtros: Dict[str, str], tag_sel: Optional[str]) -> str:
    fam_ops = [("", "Todas las familias")] + [(f.value, ETIQUETA_FAMILIA[f.value]) for f in Familia]
    est_ops = [("", "Todas las condiciones")] + [(k, v) for k, v in ETIQUETA_ESTADO.items()]
    filtros_html = f"""
<form data-form="filtros" data-auto="1" class="filtros">
  {campo("familia", "Familia", filtros.get("familia", ""), opciones=fam_ops)}
  {campo("area", "Ubicación", filtros.get("area", ""), opciones=opciones_areas(proyecto))}
  {campo("estado", "Condición", filtros.get("estado", ""), opciones=est_ops)}
</form>"""
    partes = []
    for p in proyecto.plantas:
        areas_html = []
        for a in p.areas:
            if filtros.get("area") and a.id != filtros["area"]:
                continue
            sist_html = []
            for s in a.sistemas:
                eqs = []
                for eq in s.equipos:
                    estado = ev["equipos"].get(eq.tag, {}).get("estado")
                    if filtros.get("familia") and eq.familia.value != filtros["familia"]:
                        continue
                    if filtros.get("estado") and estado != filtros["estado"]:
                        continue
                    error = eq.tag in ev.get("errores", {})
                    punto = (f'<span class="punto" style="background:{COLOR_ESTADO.get(estado, "#94a3b8")}"></span>')
                    eqs.append(
                        f'<a href="#" class="eq{" activo" if eq.tag == tag_sel else ""}" data-accion="ver_equipo" '
                        f'data-tag="{e(eq.tag)}">{punto}<b>{e(eq.tag)}</b>'
                        f'<span class="eq-d">{e(ETIQUETA_FAMILIA[eq.familia.value])}{" · ⚠ datos" if error else ""}</span></a>')
                if eqs:
                    sist_html.append(f'<div class="sist"><div class="sist-n">{e(s.nombre)}</div>{"".join(eqs)}</div>')
            if sist_html:
                areas_html.append(f'<div class="area"><div class="area-n">{e(a.nombre)}</div>{"".join(sist_html)}</div>')
        cuerpo = "".join(areas_html) or '<p class="vacio">Sin equipos para el filtro.</p>'
        partes.append(f'<details class="planta" open><summary>{e(p.nombre)}</summary>{cuerpo}</details>')
    return filtros_html + f'<nav class="arbol">{"".join(partes)}</nav>'


# =============================================================================
# Panel de resultados
# =============================================================================

def filtrar_filas(filas: List[Dict[str, Any]], proyecto: Proyecto, filtros: Dict[str, str]) -> List[Dict[str, Any]]:
    areas = {a.id: a.nombre for p in proyecto.plantas for a in p.areas}
    salida = []
    for f in filas:
        if filtros.get("familia") and f["familia"] != filtros["familia"]:
            continue
        if filtros.get("area") and f["area"] != areas.get(filtros["area"]):
            continue
        if filtros.get("estado") and f["estado"] != filtros["estado"]:
            continue
        salida.append(f)
    return salida


def matriz_riesgo(marcas: Dict[Tuple[int, str], List[str]], titulo: str = "") -> str:
    """Matriz 5×5 (probabilidad 5→1 en filas, consecuencia A→E en columnas)."""
    cab = "".join(f"<th>{c}</th>" for c in ce.CATEGORIAS_CONSECUENCIA)
    filas = []
    for p in (5, 4, 3, 2, 1):
        celdas = []
        for i, c in enumerate(ce.CATEGORIAS_CONSECUENCIA):
            nivel = ce.MATRIZ_RIESGO_5X5[p][i]
            contenido = "".join(f'<span class="marca-m">{e(t)}</span>' for t in marcas.get((p, c), []))
            celdas.append(f'<td class="riesgo-{nivel.lower()}" title="P{p}/{c}: {ETIQUETA_NIVEL[nivel]}">{contenido}</td>')
        filas.append(f'<tr><th>{p}</th>{"".join(celdas)}</tr>')
    t = f'<div class="lbl">{e(titulo)}</div>' if titulo else ""
    leyenda = "".join(f'<span class="chip riesgo-{k.lower()}">{v}</span>' for k, v in ETIQUETA_NIVEL.items())
    return f"""{t}<div class="matriz-w"><div class="eje-y">Probabilidad (categoría por f_F)</div>
<table class="matriz"><thead><tr><th></th>{cab}</tr></thead><tbody>{"".join(filas)}</tbody></table></div>
<div class="eje-x">Consecuencia (A–E)</div><div class="chips leyenda">{leyenda}</div>"""


def vista_panel(proyecto: Proyecto, ev: Dict[str, Any], filtros: Dict[str, str]) -> str:
    filas = filtrar_filas(ev["filas"], proyecto, filtros)
    conteo = {k: sum(1 for f in filas if f["estado"] == k) for k in ETIQUETA_ESTADO}
    kpis = "".join(
        f'<div class="kpi est-borde-{k.lower()}"><div class="kpi-t">{v}</div><div class="kpi-v">{conteo[k]}</div>'
        f'<div class="kpi-sub">CML</div></div>' for k, v in ETIQUETA_ESTADO.items())
    equipos_fam = {f.value: 0 for f in Familia}
    for *_, eq in proyecto.iter_equipos():
        equipos_fam[eq.familia.value] += 1
    fam_txt = " · ".join(f"{ETIQUETA_FAMILIA[k]}: {v}" for k, v in equipos_fam.items())

    cuerpo = []
    for f in filas:
        cuerpo.append(
            f'<tr class="clic" data-accion="ver_cml" data-tag="{e(f["tag"])}" data-cml="{e(f["cml_id"])}">'
            f'<td class="nw"><b>{e(f["tag"])}</b></td><td>{e(ETIQUETA_FAMILIA[f["familia"]])}</td>'
            f'<td class="sec" title="{e(f["planta"])} / {e(f["area"])}">{e(f["sistema"])}</td><td>{e(f["componente"])}</td>'
            f'<td class="nw">{e(f["cml_id"].replace(f["tag"] + "-", ""))}</td><td class="n">{num(f["t_ultimo"], 2)}</td><td class="n">{num(f["t_min"], 2)}</td>'
            f'<td class="n">{num(f["t_alerta"], 2)}</td><td class="n">{num(f["cr_gov"], 3)}</td>'
            f'<td class="n">{num(f["vida_remanente"], 1)}</td><td>{fecha(f["fecha_proxima"])}</td>'
            f'<td>{chip_estado(f["estado"])}</td><td>{chips_alertas(f["alertas"])}</td></tr>')
    tabla = f"""
<div class="tabla-w"><table class="tabla">
<thead><tr><th>Equipo</th><th>Familia</th><th>Sistema</th><th>Componente</th><th>CML</th>
<th class="n">t último<br><small>mm</small></th><th class="n">t_min<br><small>mm</small></th>
<th class="n">t_alerta<br><small>mm</small></th><th class="n">CR_gov<br><small>mm/año</small></th>
<th class="n">RL<br><small>años</small></th><th>Próxima</th><th>Condición</th><th>Alertas</th></tr></thead>
<tbody>{"".join(cuerpo) or '<tr><td colspan="13" class="vacio">Sin CML para el filtro seleccionado.</td></tr>'}</tbody>
</table></div>"""

    # RBI
    marcas: Dict[Tuple[int, str], List[str]] = {}
    filas_rbi = []
    for tag, r in ev["rbi"].items():
        res = r["resultado"]
        marcas.setdefault((res["cat_probabilidad"], res["cat_consecuencia_global"]), []).append(tag)
        mon = r["entradas"]["moneda"]
        filas_rbi.append(
            f'<tr class="clic" data-accion="ver_rbi" data-tag="{e(tag)}"><td class="nw"><b>{e(tag)}</b></td>'
            f'<td class="n">{num(res["D_f"], 2)}</td><td class="n">{num(res["f_F"], 3)}</td>'
            f'<td class="n">{num(res["R_A"], 3)}</td><td class="n">{num(res["R_E"], 0)} <small>{e(mon)}</small></td>'
            f'<td>{res["cat_probabilidad"]}{res["cat_consecuencia_global"]}</td><td>{chip_nivel(res["nivel_riesgo"])}</td>'
            f'<td class="n">P{res["prioridad"]}</td></tr>')
    rbi_html = f"""
<div class="tabla-w"><table class="tabla">
<thead><tr><th>Equipo</th><th class="n">D_f</th><th class="n">f_F<br><small>1/año</small></th>
<th class="n">R_A<br><small>m²/año</small></th><th class="n">R_E<br><small>moneda/año</small></th>
<th>Celda</th><th>Riesgo</th><th class="n">Prior.</th></tr></thead>
<tbody>{"".join(filas_rbi) or '<tr><td colspan="8" class="vacio">Sin equipos con RBI.</td></tr>'}</tbody></table></div>"""

    avisos = ""
    if ev.get("errores"):
        avisos += "".join(f'<div class="msg msg-error">{e(k)}: {e(v)}</div>' for k, v in ev["errores"].items())
    if ev.get("integridad"):
        avisos += "".join(f'<div class="msg msg-aviso">{e(x)}</div>' for x in ev["integridad"])

    return f"""
<section class="vista">
  <div class="tit-vista"><h1>Panel de resultados</h1>
    <p class="sec">Evaluación al {fecha(ev["fecha_evaluacion"])} · {len(filas)} CML mostrados · Equipos — {e(fam_txt)}</p></div>
  {avisos}
  <div class="kpis">{kpis}</div>
  <div class="tarjeta"><h2>Ubicaciones de monitoreo (CML/TML)</h2>
    <p class="sec">Haga clic en una fila para abrir el CML. Condición por severidad: bajo mínimo &gt; inspección vencida &gt; alerta &gt; normal.</p>
    {tabla}</div>
  <div class="grid2">
    <div class="tarjeta"><h2>RBI por adelgazamiento generalizado</h2>
      <p class="sec">Modelo académico simplificado (API RP 580/581). R_A = f_F·C_A; R_E = f_F·C_E; base anual.</p>{rbi_html}</div>
    <div class="tarjeta"><h2>Matriz de riesgo 5×5</h2>{matriz_riesgo(marcas)}</div>
  </div>
</section>"""


# =============================================================================
# Gráficos SVG
# =============================================================================

def _ordinal(d: date) -> int:
    return d.toordinal()


def _paso_lindo(rango: float, n: int = 5) -> float:
    bruto = rango / max(n, 1)
    mag = 10 ** math.floor(math.log10(bruto)) if bruto > 0 else 1
    for m in (1, 2, 2.5, 5, 10):
        if bruto <= m * mag:
            return m * mag
    return 10 * mag


def grafico_espesor(ev_cml: Dict[str, Any], t_nom: Optional[float], fecha_eval: date,
                    ancho: int = 760, alto: int = 330) -> str:
    """Espesor vs tiempo: serie comparable, excluidas, t_nom, t_alerta, t_min y proyección con CR_gov."""
    res = ev_cml["resultado"]
    det_serie = ev_cml["detalle"]["serie"]["resultado"]
    serie = det_serie["serie"]
    excl = [x for x in det_serie["excluidas"] if "fecha" in x and "espesor_mm" in x]
    excl_rango = [x for x in excl if x["fecha"] <= fecha_eval]
    t_min, t_alerta = res["t_min"], res["t_alerta"]
    cr = res["cr_para_calculo"]
    f_prox = res["fecha_proxima"]
    if not serie and not excl_rango:
        return '<div class="vacio grafico-vacio">Sin mediciones para graficar.</div>'

    fechas = [p["fecha"] for p in serie] + [p["fecha"] for p in excl_rango] + [fecha_eval]
    if f_prox:
        fechas.append(f_prox)
    proy = None
    if serie and cr:
        ult = serie[-1]
        anios_cruce = (ult["espesor_mm"] - t_min) / cr if ult["espesor_mm"] > t_min else 0.0
        fin = max(fecha_eval, f_prox or fecha_eval)
        f_cruce = ult["fecha"] + timedelta(days=round(anios_cruce * 365.25))
        f_fin = min(f_cruce, ult["fecha"] + timedelta(days=round(15 * 365.25)))
        f_fin = max(f_fin, min(fin, f_cruce))
        t_fin = ult["espesor_mm"] - cr * (f_fin - ult["fecha"]).days / 365.25
        proy = (ult["fecha"], ult["espesor_mm"], f_fin, t_fin, f_cruce)
        fechas.append(f_fin)
    x0 = _ordinal(min(fechas)) - 150
    x1 = _ordinal(max(fechas)) + 150
    ys = [p["espesor_mm"] for p in serie] + [p["espesor_mm"] for p in excl_rango] + [t_min, t_alerta]
    if t_nom:
        ys.append(t_nom)
    if proy:
        ys.append(proy[3])
    y0, y1 = min(ys), max(ys)
    margen = max((y1 - y0) * 0.12, 0.3)
    y0, y1 = y0 - margen, y1 + margen
    izq, der, sup, inf = 58, 128, 22, 36
    W, H = ancho - izq - der, alto - sup - inf

    def X(d: date) -> float:
        return izq + (_ordinal(d) - x0) / (x1 - x0) * W

    def Y(t: float) -> float:
        return sup + (y1 - t) / (y1 - y0) * H

    s = [f'<svg class="graf" viewBox="0 0 {ancho} {alto}" role="img" aria-label="Espesor versus tiempo">']
    # grilla y ejes
    paso = _paso_lindo(y1 - y0, 7)
    v = math.ceil(y0 / paso) * paso
    while v <= y1:
        s.append(f'<line x1="{izq}" x2="{izq + W}" y1="{Y(v):.1f}" y2="{Y(v):.1f}" class="g-grilla"/>'
                 f'<text x="{izq - 8}" y="{Y(v) + 4:.1f}" class="g-eje" text-anchor="end">{v:g}</text>')
        v += paso
    a0, a1 = date.fromordinal(x0).year + 1, date.fromordinal(x1).year
    salto = max(1, math.ceil((a1 - a0 + 1) / 10))
    for a in range(a0, a1 + 1, salto):
        xa = X(date(a, 1, 1))
        s.append(f'<line x1="{xa:.1f}" x2="{xa:.1f}" y1="{sup}" y2="{sup + H}" class="g-grilla"/>'
                 f'<text x="{xa:.1f}" y="{sup + H + 18}" class="g-eje" text-anchor="middle">{a}</text>')
    s.append(f'<rect x="{izq}" y="{sup}" width="{W}" height="{H}" class="g-marco"/>')
    s.append(f'<text x="14" y="{sup + H / 2}" class="g-eje" transform="rotate(-90 14 {sup + H / 2})" '
             f'text-anchor="middle">Espesor [mm]</text>')
    # zonas y líneas de referencia
    s.append(f'<rect x="{izq}" y="{Y(t_min):.1f}" width="{W}" height="{max(sup + H - Y(t_min), 0):.1f}" class="z-bajo"/>')
    s.append(f'<rect x="{izq}" y="{Y(t_alerta):.1f}" width="{W}" height="{max(Y(t_min) - Y(t_alerta), 0):.1f}" class="z-alerta"/>')
    refs = [(t_min, "t_min", "l-min"), (t_alerta, "t_alerta", "l-alerta")]
    if t_nom:
        refs.append((t_nom, "t_nom", "l-nom"))
    ult_y = -99.0
    for t, nombre, cls in sorted(refs, key=lambda r: -r[0]):
        yy = Y(t)
        ly = max(yy + 4, ult_y + 13)
        ult_y = ly
        s.append(f'<line x1="{izq}" x2="{izq + W}" y1="{yy:.1f}" y2="{yy:.1f}" class="{cls}"/>'
                 f'<text x="{izq + W + 6}" y="{ly:.1f}" class="g-ref {cls}-t">{nombre} = {t:.2f}</text>')
    # verticales: línea base, evaluación, próxima
    if det_serie.get("fecha_linea_base"):
        xb = X(det_serie["fecha_linea_base"])
        s.append(f'<line x1="{xb:.1f}" x2="{xb:.1f}" y1="{sup}" y2="{sup + H}" class="l-base"/>'
                 f'<text x="{xb + 4:.1f}" y="{sup + H - 20}" class="g-nota">línea base</text>')
    xe = X(fecha_eval)
    s.append(f'<line x1="{xe:.1f}" x2="{xe:.1f}" y1="{sup}" y2="{sup + H}" class="l-eval"/>'
             f'<text x="{xe - 4:.1f}" y="{sup + H - 6}" class="g-nota" text-anchor="end">evaluación</text>')
    if f_prox:
        xp = X(f_prox)
        cls = "l-prox-vencida" if f_prox < fecha_eval else "l-prox"
        derecha = xp > izq + 0.6 * W
        s.append(f'<line x1="{xp:.1f}" x2="{xp:.1f}" y1="{sup}" y2="{sup + H}" class="{cls}"/>'
                 f'<text x="{xp + (-5 if derecha else 5):.1f}" y="{sup + 14}" class="g-nota g-prox" '
                 f'text-anchor="{"end" if derecha else "start"}">próxima inspección {f_prox.isoformat()}</text>')
    # proyección
    if proy:
        fa, ta, fb, tb, fc = proy
        s.append(f'<line x1="{X(fa):.1f}" y1="{Y(ta):.1f}" x2="{X(fb):.1f}" y2="{Y(tb):.1f}" class="l-proy"/>')
        if fb >= fc and ta > t_min:
            s.append(f'<circle cx="{X(fc):.1f}" cy="{Y(t_min):.1f}" r="4" class="p-cruce"><title>Alcanza t_min el '
                     f'{fc.isoformat()}</title></circle>')
    # serie comparable
    if len(serie) > 1:
        pts = " ".join(f"{X(p['fecha']):.1f},{Y(p['espesor_mm']):.1f}" for p in serie)
        s.append(f'<polyline points="{pts}" class="l-serie"/>')
    for p in serie:
        s.append(f'<circle cx="{X(p["fecha"]):.1f}" cy="{Y(p["espesor_mm"]):.1f}" r="4.5" class="p-serie">'
                 f'<title>{p["fecha"].isoformat()}: {p["espesor_mm"]:.2f} mm</title></circle>')
    for p in excl_rango:
        s.append(f'<circle cx="{X(p["fecha"]):.1f}" cy="{Y(p["espesor_mm"]):.1f}" r="4.5" class="p-excl">'
                 f'<title>{p["fecha"].isoformat()}: {p["espesor_mm"]:.2f} mm — excluida '
                 f'({MOTIVO_EXCLUSION.get(p["motivo"], p["motivo"])})</title></circle>')
    s.append("</svg>")
    fuera = [x for x in excl if x["fecha"] > fecha_eval]
    nota = ""
    if fuera:
        nota = ('<p class="sec">No graficadas (fecha posterior a la evaluación): ' +
                ", ".join(f'{x["fecha"].isoformat()} = {x["espesor_mm"]:.2f} mm' for x in fuera) + "</p>")
    leyenda = ('<div class="leyenda-g"><span><i class="lg-serie"></i>serie comparable</span>'
               '<span><i class="lg-excl"></i>excluida</span><span><i class="lg-proy"></i>proyección con CR_gov</span>'
               '<span><i class="lg-min"></i>t_min</span><span><i class="lg-alerta"></i>t_alerta</span></div>')
    return "".join(s) + leyenda + nota


def escala_espesores(niveles: List[Tuple[str, float, str]], t_min: float, t_alerta: float,
                     medidos: List[Tuple[str, float, str]], ancho: int = 760) -> str:
    """Regla horizontal que distingue nominal, diseño, mínimo, alerta y medidos.

    niveles: (etiqueta, valor, clase) mostrados sobre la regla.
    medidos: (cml_id, espesor, estado) mostrados bajo la regla.
    """
    valores = [v for _, v, _ in niveles] + [v for _, v, _ in medidos] + [t_min, t_alerta]
    xmin = max(0.0, min(valores) - 1.0)
    xmax = max(valores) + 0.6
    izq, der = 20, 20
    W = ancho - izq - der
    alto_reg = 16

    def X(t: float) -> float:
        return izq + (t - xmin) / (xmax - xmin) * W

    def asignar(items, sep):
        filas: List[List[float]] = [[], [], [], []]
        salida = []
        for it in sorted(items, key=lambda n: n[1]):
            x = X(it[1])
            fila = next((i for i, ocup in enumerate(filas) if all(abs(x - o) > sep for o in ocup)), 3)
            filas[fila].append(x)
            salida.append((it, x, fila))
        return salida
    niv_pos = asignar(niveles, 120)
    med_pos = asignar(medidos, 110)
    filas_niv = max([f for *_, f in niv_pos], default=0) + 1
    filas_med = max([f for *_, f in med_pos], default=0) + 1
    y_reg = 14 + 18 * filas_niv
    alto = y_reg + alto_reg + 38 + 16 * filas_med

    s = [f'<svg class="graf escala" viewBox="0 0 {ancho} {alto}" role="img" aria-label="Escala de espesores">']
    s.append(f'<rect x="{X(xmin):.1f}" y="{y_reg}" width="{X(t_min) - X(xmin):.1f}" height="{alto_reg}" class="z-bajo-f"/>')
    s.append(f'<rect x="{X(t_min):.1f}" y="{y_reg}" width="{max(X(t_alerta) - X(t_min), 0):.1f}" height="{alto_reg}" class="z-alerta-f"/>')
    s.append(f'<rect x="{X(t_alerta):.1f}" y="{y_reg}" width="{X(xmax) - X(t_alerta):.1f}" height="{alto_reg}" class="z-normal-f"/>')
    paso = _paso_lindo(xmax - xmin, 8)
    v = math.ceil(xmin / paso) * paso
    while v <= xmax:
        s.append(f'<line x1="{X(v):.1f}" x2="{X(v):.1f}" y1="{y_reg + alto_reg}" y2="{y_reg + alto_reg + 4}" class="g-eje-l"/>'
                 f'<text x="{X(v):.1f}" y="{y_reg + alto_reg + 13}" class="g-eje" text-anchor="middle">{v:g}</text>')
        v += paso
    s.append(f'<text x="{ancho - der}" y="{y_reg + alto_reg + 15}" class="g-eje" text-anchor="end">mm</text>')
    # niveles arriba, escalonados para no superponer
    for (etiqueta, valor, cls), x, fila in niv_pos:
        yt = y_reg - 8 - fila * 18
        s.append(f'<line x1="{x:.1f}" x2="{x:.1f}" y1="{yt + 3}" y2="{y_reg + alto_reg}" class="{cls}"/>'
                 f'<text x="{x:.1f}" y="{yt:.1f}" class="g-ref {cls}-t" text-anchor="middle">{e(etiqueta)} {valor:.2f}</text>')
    # medidos abajo
    for (cml_id, valor, estado), x, fila in med_pos:
        yt = y_reg + alto_reg + 46 + fila * 16
        color = COLOR_ESTADO.get(estado, "#334155")
        etiqueta = "CML-" + cml_id.split("-CML-")[-1] if "-CML-" in cml_id else cml_id
        s.append(f'<line x1="{x:.1f}" x2="{x:.1f}" y1="{y_reg}" y2="{y_reg + alto_reg + 19}" stroke="{color}" stroke-width="1.5"/>'
                 f'<path d="M{x:.1f},{y_reg + alto_reg + 19} l-5,9 l10,0 z" fill="{color}"/>'
                 f'<text x="{x:.1f}" y="{yt}" class="g-med" fill="{color}" text-anchor="middle">'
                 f'{e(etiqueta)} {valor:.2f}</text>')
    s.append("</svg>")
    return "".join(s)


# =============================================================================
# Vista de equipo
# =============================================================================

PESTANAS = (("antecedentes", "Antecedentes"), ("espesores", "Espesores"),
            ("esquema", "Esquema y CML"), ("rbi", "RBI"))


def _buscar_ev_cml(ev_eq: Optional[Dict[str, Any]], cml_id: Optional[str]):
    if not ev_eq or not cml_id:
        return None, None
    for c in ev_eq["componentes"]:
        for m in c["cmls"]:
            if m["identificacion"]["cml_id"] == cml_id:
                return c, m
    return None, None


def vista_equipo(proyecto: Proyecto, eq: Equipo, ev_eq: Optional[Dict[str, Any]],
                 rbi_r: Optional[Dict[str, Any]], pestana: str, cml_id: Optional[str],
                 ubicando: bool, fecha_eval: date, error: Optional[str] = None,
                 error_rbi: Optional[str] = None) -> str:
    ubic = proyecto.ubicacion_tecnica(eq.tag) or eq.tag
    estado = ev_eq["estado"] if ev_eq else None
    tabs = "".join(
        f'<button type="button" class="tab{" activo" if k == pestana else ""}" data-accion="pestana" '
        f'data-valor="{k}">{v}</button>' for k, v in PESTANAS)
    aviso = f'<div class="msg msg-error">No se pudo evaluar el equipo: {e(error)}</div>' if error else ""
    if pestana == "antecedentes":
        cuerpo = tab_antecedentes(proyecto, eq)
    elif pestana == "espesores":
        cuerpo = tab_espesores(eq, ev_eq) if ev_eq else ""
    elif pestana == "esquema":
        cuerpo = tab_esquema(eq, ev_eq, cml_id, ubicando, fecha_eval)
    else:
        cuerpo = tab_rbi(eq, rbi_r, ev_eq, error_rbi)
    return f"""
<section class="vista">
  <div class="cab-eq">
    <div><div class="ruta">{e(ubic)}</div>
      <h1>{e(eq.tag)} <span class="desc">{e(eq.descripcion)}</span></h1>
      <div class="chips">{chip_familia(eq.familia.value)}<span class="chip">{e(eq.codigo_diseno)}</span>
        <span class="chip">{e(eq.codigo_inspeccion)}</span>{chip_estado(estado)}</div></div>
  </div>
  <div class="tabs">{tabs}</div>
  {aviso}
  {cuerpo}
</section>"""


# --------------------------------------------------------------- antecedentes
def _opciones_material(familia: Familia) -> List[Tuple[str, str]]:
    cat = {Familia.TUBERIA: ce.MATERIALES_TUBERIA, Familia.RECIPIENTE: ce.MATERIALES_RECIPIENTE,
           Familia.TANQUE: ce.MATERIALES_TANQUE}[familia]
    return [(k, f"{k} — {v['descripcion'].split('—')[0].strip()}") for k, v in cat.items()]


OPCIONES_CLASE = [("1", "Clase 1"), ("2", "Clase 2"), ("3", "Clase 3"), ("PUNTO_INYECCION", "Punto de inyección")]
OPCIONES_REGLA = [("CONSERVADORA_1_4", "min(RL/4, 2 años) — criterio del grupo"),
                  ("API_TEXTUAL", "min(RL, 2 años) — texto API 510 §6.5.1.1")]


def tab_antecedentes(proyecto: Proyecto, eq: Equipo) -> str:
    p = eq.parametros
    f = eq.familia
    especificos = ""
    if f == Familia.TUBERIA:
        especificos = (campo("factor_W", "Factor W", p.factor_W, ayuda="B31.3 §302.3.5(e)", minimo=0, maximo=1)
                       + campo("coeficiente_Y", "Coeficiente Y", p.coeficiente_Y, ayuda="Tabla 304.1.1")
                       + campo("tolerancia_pct", "Tolerancia de fabricación", round(p.tolerancia_fabricacion * 100, 3),
                               "number", "%", "Tubo sin costura A106: 12.5 %")
                       + campo("t_estructural_mm", "t mínimo estructural", p.t_estructural_mm, unidad="mm",
                               ayuda="API 574 (adoptado por el grupo)")
                       + campo("clase_tuberia", "Clase de tubería (API 570)", p.clase_tuberia, opciones=OPCIONES_CLASE)
                       + campo("circuito_inspeccion", "Circuito de inspección", eq.circuito_inspeccion or "", "text"))
    elif f == Familia.RECIPIENTE:
        especificos = (campo("tolerancia_placa_mm", "Tolerancia negativa de placa", p.tolerancia_placa_mm,
                             unidad="mm", ayuda="UG-16(c): ignorable si ≤ min(0.25 mm, 6 % t_nom)")
                       + campo("regla_rl_menor_4", "Regla API 510 con RL < 4 años", p.regla_rl_menor_4 or "",
                               opciones=OPCIONES_REGLA))
    else:
        especificos = (campo("diametro_tanque_m", "Diámetro nominal D", p.diametro_tanque_m, unidad="m")
                       + campo("altura_liquido_diseno_m", "Nivel de diseño del líquido", p.altura_liquido_diseno_m,
                               unidad="m", ayuda="Informativo; H por virola se define en cada componente")
                       + campo("densidad_relativa_G", "Densidad relativa G", p.densidad_relativa_G)
                       + campo("eficiencia_junta_servicio", "E en servicio (API 653 Tabla 4.2)",
                               p.eficiencia_junta_servicio, minimo=0, maximo=1))
    form_eq = f"""
<form data-form="editar_equipo" data-tag="{e(eq.tag)}" class="tarjeta">
  <h2>Identificación y condiciones</h2>
  <div class="grid-campos">
    {campo("descripcion", "Descripción", eq.descripcion, "text", requerido=True, clase="ancho2")}
    {campo("servicio", "Servicio", eq.servicio, "text")}
    {campo("fluido", "Fluido", eq.fluido, "text")}
    {campo("material_id", "Material", eq.material_id, opciones=_opciones_material(f))}
    {campo("fecha_puesta_servicio", "Puesta en servicio", eq.fecha_puesta_servicio, "date")}
  </div>
  <h3>Diseño y operación</h3>
  <div class="grid-campos">
    {campo("P_dis", "Presión de diseño", eq.diseno.presion_MPa, unidad="MPa", minimo=0)}
    {campo("T_dis", "Temperatura de diseño", eq.diseno.temperatura_C, unidad="°C")}
    {campo("P_op", "Presión de operación", eq.operacion.presion_MPa, unidad="MPa", minimo=0)}
    {campo("T_op", "Temperatura de operación", eq.operacion.temperatura_C, unidad="°C")}
  </div>
  <h3>Parámetros de cálculo</h3>
  <div class="grid-campos">
    {campo("CA", "Sobreespesor por corrosión CA", p.sobreespesor_corrosion_mm, unidad="mm", minimo=0)}
    {campo("E", "Eficiencia de junta / factor de calidad E", p.eficiencia_junta, minimo=0, maximo=1)}
    {campo("dt_margen_anios", "Plazo de intervención Δt_margen", p.dt_margen_anios, unidad="años",
           ayuda="t_alerta = t_min + CR_gov·Δt_margen", minimo=0)}
    {especificos}
  </div>
  <div class="acciones"><button type="submit" class="btn primario">Guardar y recalcular</button></div>
</form>"""
    comps = "".join(_form_componente(eq, c) for c in eq.componentes)
    return f"""<div class="grid-eq">{form_eq}<div>{comps}{_form_nuevo_componente(eq)}</div></div>"""


def _campos_geometria(eq: Equipo, c: Any = None) -> str:
    g = (lambda a: getattr(c, a) if c is not None else None)
    if eq.familia == Familia.TUBERIA:
        return (campo("diametro_exterior_mm", "Diámetro exterior D", g("diametro_exterior_mm"), unidad="mm", requerido=True)
                + campo("nps", "NPS", g("nps") or "", "text") + campo("cedula", "Cédula", g("cedula") or "", "text"))
    if eq.familia == Familia.RECIPIENTE:
        return campo("radio_interior_mm", "Radio interior R (nuevo)", g("radio_interior_mm"), unidad="mm", requerido=True)
    return (campo("numero_virola", "N.º de virola (1 = inferior)", g("numero_virola"), paso="1", minimo=1, requerido=True)
            + campo("nivel_sobre_fondo_virola_m", "H sobre fondo de la virola", g("nivel_sobre_fondo_virola_m"),
                    unidad="m", requerido=True, ayuda="Desde el fondo de la virola al nivel de diseño")
            + campo("altura_virola_m", "Altura de la virola", g("altura_virola_m"), unidad="m"))


def _form_componente(eq: Equipo, c: Any) -> str:
    return f"""
<form data-form="editar_componente" data-tag="{e(eq.tag)}" data-comp="{e(c.id)}" class="tarjeta">
  <h2>{e(c.nombre)} <small class="sec">{e(c.id)} · {e(c.tipo.value)}</small></h2>
  <div class="grid-campos">
    {campo("nombre", "Nombre", c.nombre, "text", requerido=True)}
    {campo("t_nom_mm", "Espesor nominal t_nom", c.t_nom_mm, unidad="mm", requerido=True, minimo=0)}
    {_campos_geometria(eq, c)}
    {campo("t_min_mm_override", "t_min declarado (opcional)", c.t_min_mm_override or "", unidad="mm",
           ayuda="Reemplaza el t_min calculado (p. ej. resultado FFS)")}
  </div>
  <div class="acciones"><button type="submit" class="btn">Guardar componente</button></div>
</form>"""


def _form_nuevo_componente(eq: Equipo) -> str:
    return f"""
<details class="tarjeta plegable"><summary>+ Agregar componente</summary>
<form data-form="agregar_componente" data-tag="{e(eq.tag)}">
  <div class="grid-campos">
    {campo("id", "Identificador", f"{eq.tag}-C{len(eq.componentes) + 1:02d}", "text", requerido=True)}
    {campo("nombre", "Nombre", "", "text", requerido=True)}
    {campo("t_nom_mm", "Espesor nominal t_nom", "", unidad="mm", requerido=True, minimo=0)}
    {_campos_geometria(eq)}
  </div>
  <div class="acciones"><button type="submit" class="btn">Agregar componente</button></div>
</form></details>"""


# --------------------------------------------------------------- espesores
def tab_espesores(eq: Equipo, ev_eq: Dict[str, Any]) -> str:
    partes = []
    for c in ev_eq["componentes"]:
        cuadro = c["espesores"]
        r = cuadro["resultado"]
        comp = next(x for x in eq.componentes if x.id == c["componente_id"])
        crs = [m["resultado"]["cr_para_calculo"] for m in c["cmls"] if m["resultado"]["cr_para_calculo"]]
        cr_max = max(crs) if crs else None
        t_alerta = r["t_min"] + (cr_max or 0) * eq.parametros.dt_margen_anios
        medidos = [(m["identificacion"]["cml_id"], m["resultado"]["t_ultimo"], m["resultado"]["estado"])
                   for m in c["cmls"] if m["resultado"]["t_ultimo"] is not None]
        if eq.familia == Familia.TUBERIA:
            niveles = [("t_nom", r["t_nom"], "l-nom"), ("t_fab,min", r["t_fab_min"], "l-fab"),
                       ("t_m = t+CA", r["t_m"], "l-dis")]
            kpis = (_kpi("t_nom (cédula)", f"{num(r['t_nom'], 2)} mm", f"t_fab,min = {num(r['t_fab_min'], 2)} mm")
                    + _kpi("t presión (Ec. 3a)", f"{num(r['t_presion'], 3)} mm", f"S = {num(r.get('S'), 0)} MPa")
                    + _kpi("t_m = t + CA", f"{num(r['t_m'], 3)} mm", f"t_nom,req = {num(r['t_nom_requerido'], 3)} mm"))
            detalle = (bloque_calculo("Esfuerzo admisible S(T)", cuadro["detalle"].get("esfuerzo_admisible"))
                       + bloque_calculo("Ec. (3a) B31.3", cuadro["detalle"]["presion"], abierto=True))
        elif eq.familia == Familia.RECIPIENTE:
            niveles = [("t_nom", r["t_nom"], "l-nom"), ("t_req + CA", r["t_diseno"], "l-dis")]
            kpis = (_kpi("t_nom (placa)", f"{num(r['t_nom'], 2)} mm", f"t_fab,min = {num(r['t_fab_min'], 2)} mm")
                    + _kpi("t_req UG-27(c)(1)", f"{num(r['t_req'], 3)} mm", f"S = {num(r.get('S'), 0)} MPa")
                    + _kpi("t_req + CA", f"{num(r['t_diseno'], 3)} mm",
                           f"MAWP nuevo corroído = {num(r['MAWP_nuevo_corroido'], 3)} MPa"))
            detalle = (bloque_calculo("Esfuerzo admisible S(T) — ASME II-D", cuadro["detalle"].get("esfuerzo_admisible"))
                       + bloque_calculo("UG-27(c)(1) circunferencial", cuadro["detalle"]["ug27"], abierto=True))
        else:
            niveles = [("t_nom", r["t_nom"], "l-nom"), ("t req. API 650", r["t_requerido"], "l-dis")]
            kpis = (_kpi("t_nom (virola)", f"{num(r['t_nom'], 2)} mm", f"virola {comp.numero_virola}")
                    + _kpi("t_d / t_t (API 650)", f"{num(r['t_d'], 3)} / {num(r['t_t'], 3)} mm",
                           f"t constructivo = {num(r['t_constructivo'], 1)} mm")
                    + _kpi("S en servicio (API 653)", f"{num(r['S_servicio'], 1)} MPa", "Tabla 4.1"))
            detalle = (bloque_calculo("API 650 — método de 1 pie", cuadro["detalle"]["api650"])
                       + bloque_calculo("API 653 — esfuerzo admisible", cuadro["detalle"]["esfuerzo_api653"])
                       + bloque_calculo("API 653 — t_min en servicio", cuadro["detalle"]["api653"]))
        kpis += _kpi("t_min en servicio", f"{num(r['t_min'], 3)} mm", "sin CA", "kpi-min")
        kpis += _kpi("t_alerta (CR máx. del componente)", f"{num(t_alerta, 3)} mm",
                     f"CR = {num(cr_max, 3)} mm/año · Δt = {num(eq.parametros.dt_margen_anios, 1)} años", "kpi-alerta")
        escala = escala_espesores(niveles, r["t_min"], t_alerta, medidos)
        partes.append(f"""
<div class="tarjeta">
  <h2>{e(c["nombre"])}</h2>
  <div class="kpis kpis-chicos">{kpis}</div>
  <div class="lbl">Escala de espesores — nominal, diseño, mínimo, alerta y último medido por CML</div>
  {escala}
  <p class="sec">CA es el metal disponible para corrosión: t_min no lo incluye. La tolerancia de fabricación reduce
  el espesor real respecto del nominal. t_alerta se justifica como la pérdida prevista durante el plazo de intervención.</p>
  {bloque_calculo("Cuadro de espesores del componente", cuadro)}
  {detalle}
</div>""")
    if eq.familia == Familia.TANQUE:
        pend = "".join(f"<li>{e(x)}</li>" for x in ce.DATOS_PENDIENTES_TANQUE)
        partes.insert(0, f'<div class="aviso-alcance"><b>{e(ce.ALCANCE_TANQUE)}</b> Datos pendientes para otras '
                         f'inspecciones:<ul>{pend}</ul></div>')
    return "".join(partes)


# --------------------------------------------------------------- esquema y CML
def _src_documento(doc: Any) -> Optional[str]:
    if doc is None:
        return None
    if doc.contenido_base64:
        mime = "image/jpeg" if doc.tipo.value == "JPG" else "image/png"
        return f"data:{mime};base64,{doc.contenido_base64}"
    return doc.ruta


def tab_esquema(eq: Equipo, ev_eq: Optional[Dict[str, Any]], cml_id: Optional[str],
                ubicando: bool, fecha_eval: date) -> str:
    doc = next((d for d in eq.documentos if d.admite_marcadores), None)
    estados = {}
    if ev_eq:
        for c in ev_eq["componentes"]:
            for m in c["cmls"]:
                estados[m["identificacion"]["cml_id"]] = m["resultado"]["estado"]
    src = _src_documento(doc)
    if src:
        marcadores = []
        for comp, cml in eq.iter_cmls():
            if cml.marcador_x is None or cml.marcador_y is None:
                continue
            est = estados.get(cml.id, "")
            etiqueta = cml.id.replace(eq.tag + "-", "")
            marcadores.append(
                f'<button type="button" class="marcador est-{est.lower()}{" sel" if cml.id == cml_id else ""}" '
                f'style="left:{cml.marcador_x * 100:.2f}%;top:{cml.marcador_y * 100:.2f}%" data-accion="ver_cml" '
                f'data-tag="{e(eq.tag)}" data-cml="{e(cml.id)}" title="{e(cml.id)} — {e(ETIQUETA_ESTADO.get(est, ""))}">'
                f'<span>{e(etiqueta)}</span></button>')
        acc = f' data-accion="ubicar_marcador" data-tag="{e(eq.tag)}" data-cml="{e(cml_id)}"' if ubicando and cml_id else ""
        banda = ""
        if ubicando and cml_id:
            banda = (f'<div class="msg msg-aviso">Haga clic en el esquema para ubicar <b>{e(cml_id)}</b>. '
                     f'{boton("Cancelar", "cancelar_ubicacion", "chico")}</div>')
        esquema = f"""{banda}
<div class="esquema{" ubicando" if ubicando else ""}"{acc}>
  <img src="{e(src)}" alt="{e(doc.nombre)}">
  {"".join(marcadores)}
</div>
<p class="sec">{e(doc.nombre)} · Coordenadas de marcador como fracción del ancho/alto, origen arriba-izquierda.</p>"""
    else:
        esquema = '<div class="vacio grafico-vacio">Este equipo no tiene esquema. Suba un PNG o JPG.</div>'
    subir = f"""
<details class="plegable"><summary>{"Reemplazar" if doc else "Subir"} esquema (PNG/JPG)</summary>
<form data-form="subir_esquema" data-tag="{e(eq.tag)}" class="fila-form">
  <input type="file" name="archivo" accept="image/png,image/jpeg" required>
  {campo("nombre", "Nombre del documento", doc.nombre if doc else f"Esquema {eq.tag}", "text")}
  <button type="submit" class="btn">Subir</button>
</form></details>"""

    filas = []
    varios = len(eq.componentes) > 1
    for comp, cml in eq.iter_cmls():
        _, m = _buscar_ev_cml(ev_eq, cml.id)
        res = m["resultado"] if m else {}
        sub = f'<br><small>{e(comp.nombre)}</small>' if varios else ""
        filas.append(
            f'<tr class="clic{" sel" if cml.id == cml_id else ""}" data-accion="ver_cml" data-tag="{e(eq.tag)}" '
            f'data-cml="{e(cml.id)}"><td class="nw"><b>{e(cml.id.replace(eq.tag + "-", ""))}</b>{sub}</td>'
            f'<td class="sec">{e(cml.descripcion_ubicacion)}</td><td class="n">{num(res.get("t_ultimo"), 2)}</td>'
            f'<td class="nw">{fecha(res.get("fecha_proxima"))}</td><td>{chip_estado(res.get("estado"))}</td></tr>')
    lista = f"""<div class="tabla-w"><table class="tabla tabla-chica"><thead><tr><th>CML</th><th>Ubicación</th>
<th class="n">t último<br><small>mm</small></th><th>Próxima</th><th>Condición</th></tr></thead>
<tbody>{"".join(filas) or '<tr><td colspan="5" class="vacio">Sin CML.</td></tr>'}</tbody></table></div>"""

    detalle = ""
    if cml_id:
        comp_ev, m = _buscar_ev_cml(ev_eq, cml_id)
        hallado = next(((c, x) for c, x in eq.iter_cmls() if x.id == cml_id), None)
        if hallado and m:
            detalle = detalle_cml(eq, hallado[0], hallado[1], m, fecha_eval)
    return f"""
<div class="grid-esq">
  <div class="tarjeta">{esquema}{subir}</div>
  <div class="tarjeta"><h2>CML del equipo</h2>{lista}{_form_nuevo_cml(eq)}</div>
</div>
{detalle}"""


def _form_nuevo_cml(eq: Equipo) -> str:
    n = sum(1 for _ in eq.iter_cmls()) + 1
    comps = [(c.id, c.nombre) for c in eq.componentes]
    if not comps:
        return '<p class="sec">Agregue un componente en Antecedentes antes de crear CML.</p>'
    return f"""
<details class="plegable"><summary>+ Nuevo CML</summary>
<form data-form="agregar_cml" data-tag="{e(eq.tag)}">
  <div class="grid-campos">
    {campo("componente_id", "Componente", comps[0][0], opciones=comps)}
    {campo("id", "Identificador", f"{eq.tag}-CML-{n:02d}", "text", requerido=True)}
    {campo("descripcion_ubicacion", "Ubicación", "", "text", clase="ancho2")}
    {campo("posicion_horaria", "Posición (h / °)", "", "text")}
    {campo("distancia_referencia_mm", "Distancia a referencia", "", unidad="mm")}
    {campo("marcador_x", "Marcador x", "", ayuda="Fracción 0–1 (o ubíquelo con clic luego)", minimo=0, maximo=1)}
    {campo("marcador_y", "Marcador y", "", minimo=0, maximo=1)}
  </div>
  <div class="acciones"><button type="submit" class="btn">Crear CML</button></div>
</form></details>"""


def detalle_cml(eq: Equipo, comp: Any, cml: Any, m: Dict[str, Any], fecha_eval: date) -> str:
    res = m["resultado"]
    det = m["detalle"]
    excl = {x.get("id"): x["motivo"] for x in det["serie"]["resultado"]["excluidas"] if x.get("id")}
    base = det["serie"]["resultado"]["fecha_linea_base"]
    crit_cr = det["corrosion"]["resultado"]["criterio"]
    kpis = (
        _kpi("Último espesor", f"{num(res['t_ultimo'], 2)} mm", fecha(res["fecha_ultima"]))
        + _kpi("t_min / t_alerta", f"{num(res['t_min'], 2)} / {num(res['t_alerta'], 2)} mm",
               f"Δt_margen = {num(eq.parametros.dt_margen_anios, 1)} años")
        + _kpi("CR_LT / CR_ST", f"{num(res['cr_lt'], 3)} / {num(res['cr_st'], 3)}", "mm/año")
        + _kpi("CR_gov", f"{num(res['cr_gov'], 3)} mm/año", e(crit_cr))
        + _kpi("Vida remanente", f"{num(res['vida_remanente'], 2)} años" if res["vida_remanente"] is not None
               else "Indeterminada", "RL = (t_último − t_min)/CR_gov")
        + _kpi("Próxima inspección", fecha(res["fecha_proxima"]),
               f"{e(res['tipo_inspeccion'])} · intervalo {num(res['intervalo'], 2)} años")
    )
    filas = []
    for med in sorted(cml.mediciones, key=lambda x: x.fecha):
        motivo = excl.get(med.id)
        uso = (f'<span class="chip excl">{e(MOTIVO_EXCLUSION.get(motivo, motivo))}</span>' if motivo
               else '<span class="chip ok">Comparable</span>')
        filas.append(
            f'<tr class="{"fila-excl" if motivo else ""}"><td class="nw">{fecha(med.fecha)}</td><td class="n">{num(med.espesor, 4 if med.unidad.value == "in" else 2)}</td>'
            f'<td>{e(med.unidad.value)}</td><td class="n">{num(med.espesor_mm, 2)}</td><td>{e(med.tecnica.value)}</td>'
            f'<td>{e(med.inspector)}</td><td>{e(ETIQUETA_EVENTO[med.evento.value])}</td><td>{uso}</td>'
            f'<td class="acc">'
            + boton("Validez", "alternar_validez", "chico", "Marcar como válida / no válida",
                    tag=eq.tag, cml=cml.id, med=med.id)
            + boton("✕", "eliminar_medicion", "chico peligro", "Eliminar medición", tag=eq.tag, cml=cml.id, med=med.id)
            + "</td></tr>"
            + (f'<tr class="fila-obs"><td></td><td colspan="8">↳ {e(med.observaciones)}</td></tr>'
               if med.observaciones else ""))
    intervenciones = "".join(f"<li>{fecha(i.fecha)} — {e(ETIQUETA_EVENTO.get(i.tipo.value, i.tipo.value))}: "
                             f"{e(i.descripcion)}</li>" for i in cml.intervenciones)
    interv_html = f'<div class="lbl">Intervenciones registradas</div><ul class="obs">{intervenciones}</ul>' if intervenciones else ""
    base_html = f'<p class="sec">Línea base comparable desde {fecha(base)}.</p>' if base else ""
    obs = "".join(f"<li>{e(o)}</li>" for o in m["observaciones"])
    return f"""
<div class="tarjeta detalle-cml" id="detalle-cml">
  <div class="cab-cml"><div><div class="ruta">{e(eq.tag)} / {e(comp.nombre)}</div>
    <h2>{e(cml.id)} <span class="desc">{e(cml.descripcion_ubicacion)}</span></h2>
    <div class="sec">Convención: {e(cml.convencion)}{(" · Posición " + e(cml.posicion_horaria)) if cml.posicion_horaria else ""}</div></div>
    <div class="estado-grande">{chip_estado(res["estado"])}<div class="chips">{chips_alertas(m["alertas"])}</div></div>
  </div>
  <div class="kpis kpis-chicos">{kpis}</div>
  <p class="criterio"><b>Criterio gobernante:</b> {e(res["criterio_gobernante"])}</p>
  {grafico_espesor(m, comp.t_nom_mm, fecha_eval)}
  {base_html}
  <div class="grid2">
    <div>
      <div class="lbl">Historial de mediciones</div>
      <div class="tabla-w"><table class="tabla tabla-chica"><thead><tr><th>Fecha</th><th class="n">Espesor</th><th>Unidad</th>
      <th class="n">mm</th><th>Técnica</th><th>Inspector</th><th>Evento</th><th>Uso en cálculo</th><th></th></tr></thead>
      <tbody>{"".join(filas) or '<tr><td colspan="9" class="vacio">Sin mediciones.</td></tr>'}</tbody></table></div>
      {interv_html}
      <div class="lbl">Observaciones del cálculo</div><ul class="obs">{obs}</ul>
    </div>
    <div>{_form_medicion(eq, cml, fecha_eval)}{_form_intervencion(eq, cml, fecha_eval)}{_form_editar_cml(eq, cml)}</div>
  </div>
  {bloque_calculo("Serie comparable y validación de datos", det["serie"])}
  {bloque_calculo("Velocidades de corrosión", det["corrosion"])}
  {bloque_calculo("Vida remanente", det["vida_remanente"])}
  {bloque_calculo("Espesor de alerta", det["alerta"])}
  {bloque_calculo("Intervalo de próxima inspección", det["intervalo"])}
  {bloque_calculo("Clasificación de condición", det["estado"])}
</div>"""


def _form_medicion(eq: Equipo, cml: Any, fecha_eval: date) -> str:
    return f"""
<form data-form="agregar_medicion" data-tag="{e(eq.tag)}" data-cml="{e(cml.id)}" class="caja-form">
  <h3>Agregar medición</h3>
  <div class="grid-campos">
    {campo("fecha", "Fecha", fecha_eval, "date", requerido=True)}
    {campo("espesor", "Espesor medido", "", requerido=True, minimo=0)}
    {campo("unidad", "Unidad", "mm", opciones=[("mm", "mm"), ("in", "in")])}
    {campo("tecnica", "Técnica", "UT", opciones=[("UT", "UT contacto"), ("UT_ESCANEO", "UT barrido"),
                                                ("RT_PERFIL", "RT perfil"), ("OTRA", "Otra")])}
    {campo("evento", "Evento", "NORMAL", opciones=list(ETIQUETA_EVENTO.items()),
           ayuda="Cambio de punto, reparación o reemplazo reinician la línea base")}
    {campo("inspector", "Inspector", "", "text")}
    {campo("observaciones", "Observaciones", "", "text", clase="ancho2")}
    {campo("valida", "Medición válida", True, "checkbox")}
  </div>
  <div class="acciones"><button type="submit" class="btn primario">Agregar y recalcular</button></div>
</form>"""


def _form_intervencion(eq: Equipo, cml: Any, fecha_eval: date) -> str:
    return f"""
<details class="plegable"><summary>Registrar intervención (reinicia la línea base)</summary>
<form data-form="agregar_intervencion" data-tag="{e(eq.tag)}" data-cml="{e(cml.id)}">
  <div class="grid-campos">
    {campo("fecha", "Fecha", fecha_eval, "date", requerido=True)}
    {campo("tipo", "Tipo", "REPARACION", opciones=[("CAMBIO_PUNTO", "Cambio de punto"),
                                                   ("REPARACION", "Reparación"), ("REEMPLAZO", "Reemplazo")])}
    {campo("descripcion", "Descripción", "", "text", clase="ancho2")}
  </div>
  <div class="acciones"><button type="submit" class="btn">Registrar</button></div>
</form></details>"""


def _form_editar_cml(eq: Equipo, cml: Any) -> str:
    return f"""
<details class="plegable"><summary>Editar CML y marcador</summary>
<form data-form="editar_cml" data-tag="{e(eq.tag)}" data-cml="{e(cml.id)}">
  <div class="grid-campos">
    {campo("descripcion_ubicacion", "Ubicación", cml.descripcion_ubicacion, "text", clase="ancho2")}
    {campo("posicion_horaria", "Posición (h / °)", cml.posicion_horaria or "", "text")}
    {campo("distancia_referencia_mm", "Distancia a referencia", cml.distancia_referencia_mm, unidad="mm")}
    {campo("marcador_x", "Marcador x (0–1)", cml.marcador_x, minimo=0, maximo=1)}
    {campo("marcador_y", "Marcador y (0–1)", cml.marcador_y, minimo=0, maximo=1)}
    {campo("convencion", "Convención", cml.convencion, "textarea", clase="ancho2")}
  </div>
  <div class="acciones"><button type="submit" class="btn">Guardar CML</button>
  {boton("Ubicar con clic en el esquema", "iniciar_ubicacion", "", tag=eq.tag, cml=cml.id)}</div>
</form></details>"""


# --------------------------------------------------------------- RBI
def tab_rbi(eq: Equipo, r: Optional[Dict[str, Any]], ev_eq: Optional[Dict[str, Any]],
            error: Optional[str] = None) -> str:
    if eq.rbi is None:
        return (f'<div class="tarjeta"><p>Este equipo no tiene datos RBI.</p>'
                f'{boton("Activar RBI", "activar_rbi", "primario", tag=eq.tag)}</div>')
    d = eq.rbi
    cmls = [("", "Mayor CR del equipo (conservador)")] + [(c.id, c.id) for _, c in eq.iter_cmls()]
    gff_ops = [(k, f"{k} — {v:.2e}/año") for k, v in ce.GFF_TOTAL_581.items()]
    insp = "".join(campo(f"insp_{k}", f"Insp. {k}", d.inspecciones.get(k, 0), paso="1", minimo=0)
                   for k in ("A", "B", "C", "D"))
    form = f"""
<form data-form="editar_rbi" data-tag="{e(eq.tag)}" class="tarjeta">
  <h2>Entradas RBI</h2>
  <h3>Probabilidad</h3>
  <div class="grid-campos">
    {campo("cml_referencia_id", "CML de referencia (CR)", d.cml_referencia_id or "", opciones=cmls, clase="ancho2")}
    {campo("justificacion_cml_referencia", "Justificación de la referencia", d.justificacion_cml_referencia, "textarea", clase="ancho2")}
    {campo("tipo_componente_gff", "Tipo de componente (gff)", d.tipo_componente_gff, opciones=gff_ops, clase="ancho2")}
    {campo("gff_1_anio", "gff declarado (opcional)", d.gff_1_anio or "", unidad="1/año")}
    {campo("confianza_cr", "Confianza en la CR", d.confianza_cr.value,
           opciones=[("BAJA", "Baja"), ("MEDIA", "Media"), ("ALTA", "Alta")])}
    {insp}
    {campo("puntaje_sistema_gestion", "Puntaje sistema de gestión", d.puntaje_sistema_gestion or "",
           ayuda="0–1000; vacío → F_MS = 1", minimo=0, maximo=1000)}
    {campo("factor_ajuste", "Factor de ajuste agrupado", d.factor_ajuste, minimo=0)}
  </div>
  <h3>Consecuencia (datos de entrada)</h3>
  <div class="grid-campos">
    {campo("area_consecuencia_m2", "Área de consecuencia C_A", d.area_consecuencia_m2, unidad="m²", minimo=0)}
    {campo("consecuencia_economica", "Consecuencia económica C_E", d.consecuencia_economica, minimo=0)}
    {campo("moneda", "Moneda", d.moneda, opciones=[("USD", "USD"), ("CLP", "CLP"), ("UF", "UF"), ("EUR", "EUR")])}
    {campo("tasa_a_usd", "Tasa a USD (si no es USD)", d.tasa_a_usd or "", unidad="USD/unidad")}
    {campo("base_valoracion", "Base de valoración", d.base_valoracion, "textarea", clase="ancho2")}
  </div>
  <h3>Plan</h3>
  <div class="grid-campos">
    {campo("efectividad_propuesta", "Efectividad de la próxima inspección", d.efectividad_propuesta.value,
           opciones=[(x.value, x.value) for x in Efectividad if x.value != "E"])}
    {campo("horizonte_plan_anios", "Horizonte de proyección", d.horizonte_plan_anios or "", unidad="años")}
  </div>
  <div class="acciones"><button type="submit" class="btn primario">Guardar y recalcular riesgo</button></div>
</form>"""
    if error or r is None:
        return f'<div class="grid-eq">{form}<div class="tarjeta"><div class="msg msg-error">{e(error or "Sin resultado RBI.")}</div></div></div>'
    res = r["resultado"]
    det = r["detalle"]
    mon = r["entradas"]["moneda"]
    ef = res["efecto_inspeccion_adicional"]
    proy = res["proyeccion"]
    marcas = {}
    marcas.setdefault((res["cat_probabilidad"], res["cat_consecuencia_area"]), []).append("Área")
    marcas.setdefault((res["cat_probabilidad"], res["cat_consecuencia_economica"]), []).append("Econ.")
    kpis = (_kpi("A_rt", num(res["A_rt"], 4), "CR·edad/t_ref")
            + _kpi("D_f (factor de daño)", num(res["D_f"], 2), "adimensional")
            + _kpi("f_F = gff·D_f·F_MS", f"{num(res['f_F'], 3)} /año", f"P(1 año) = {num(res['P_1_anio'], 3)}")
            + _kpi("Riesgo de área R_A", f"{num(res['R_A'], 4)} m²/año", f"C_A = {num(d.area_consecuencia_m2, 0)} m²")
            + _kpi("Riesgo económico R_E", f"{num(res['R_E'], 0)} {e(mon)}/año",
                   f"C_E = {num(d.consecuencia_economica, 0)} {e(mon)}")
            + _kpi("Riesgo / prioridad", f"{chip_nivel(res['nivel_riesgo'])} P{res['prioridad']}",
                   f"Celda {res['cat_probabilidad']}{res['cat_consecuencia_global']}"))
    post = det["df"]["detalle"]["posteriores"]
    betas = det["df"]["detalle"]["betas"]
    estados_dano = "".join(f"<tr><td>D_S{i + 1} = {ds:g}</td><td class='n'>{num(post[i], 4)}</td>"
                           f"<td class='n'>{num(betas[i], 3)}</td></tr>" for i, ds in enumerate(ce.ESTADOS_DANO_581))
    proy_html = ""
    if proy:
        proy_html = (f'<p><b>Proyección a {num(proy["horizonte_anios"], 1)} años sin nueva inspección:</b> '
                     f'A_rt = {num(proy["A_rt"], 4)}, D_f = {num(proy["D_f"], 2)}, f_F = {num(proy["f_F"], 3)}/año, '
                     f'categoría de probabilidad {proy["cat_probabilidad"]}.</p>')
    ref = det["referencia"]
    resultados = f"""
<div class="tarjeta">
  <h2>Resultado RBI <small class="sec">modelo académico simplificado</small></h2>
  <p class="sec">CR de entrada: {e(ref["criterio"])} {e(ref["justificacion"])}</p>
  <div class="kpis kpis-chicos">{kpis}</div>
  <div class="grid2">
    <div>{matriz_riesgo(marcas, "Posición del equipo (área y económica por separado)")}
      <p class="sec">Riesgo por área: {chip_nivel(res["nivel_riesgo_area"])} · Riesgo económico:
      {chip_nivel(res["nivel_riesgo_economico"])} · Global (peor consecuencia): {chip_nivel(res["nivel_riesgo"])}</p>
      <p><b>{e(res["accion"])}</b></p></div>
    <div>
      <div class="lbl">Efecto de una inspección adicional de efectividad {e(ef["efectividad"])}</div>
      <p class="efecto">D_f: <b>{num(ef["D_f_actual"], 2)}</b> → <b>{num(ef["D_f_con_inspeccion"], 2)}</b>
        (−{num(ef["reduccion_relativa_D_f"] * 100, 1)} %) · A_rt sin cambio = {num(ef["A_rt_sin_cambio"], 4)}</p>
      <div class="aviso-alcance">{e(ce.NOTA_INSPECCION_RBI)}</div>
      {proy_html}
      <div class="lbl">Estados de daño (probabilidad posterior e índice β)</div>
      <table class="tabla tabla-chica"><thead><tr><th>Estado</th><th class="n">Po</th><th class="n">β</th></tr></thead>
      <tbody>{estados_dano}</tbody></table>
    </div>
  </div>
  {bloque_calculo("Evaluación RBI completa", r)}
  {bloque_calculo("A_rt", det["art"])}
  {bloque_calculo("Relación de resistencia SR_P", det["sr"])}
  {bloque_calculo("Factor de daño D_f", det["df"])}
  {bloque_calculo("Frecuencia de falla f_F", det["ff"])}
  {bloque_calculo("Categoría de probabilidad", det["cat_probabilidad"])}
  {bloque_calculo("Categoría de consecuencia — área", det["cat_area"])}
  {bloque_calculo("Categoría de consecuencia — económica", det["cat_economica"])}
</div>"""
    return f'<div class="grid-eq">{form}{resultados}</div>'


# =============================================================================
# Nuevo equipo, verificación y normas
# =============================================================================

def vista_nuevo_equipo(proyecto: Proyecto) -> str:
    plantas = sorted({p.nombre for p in proyecto.plantas})
    areas = sorted({a.nombre for p in proyecto.plantas for a in p.areas})
    sistemas = sorted({s.nombre for p in proyecto.plantas for a in p.areas for s in a.sistemas})
    dl = lambda i, xs: f'<datalist id="{i}">' + "".join(f'<option value="{e(x)}">' for x in xs) + "</datalist>"
    mats = ([("TUBERIA:" + k, f"Tubería — {k}") for k in ce.MATERIALES_TUBERIA]
            + [("RECIPIENTE:" + k, f"Recipiente — {k}") for k in ce.MATERIALES_RECIPIENTE]
            + [("TANQUE:" + k, f"Tanque — {k}") for k in ce.MATERIALES_TANQUE])
    fam = [(f.value, ETIQUETA_FAMILIA[f.value]) for f in Familia]
    return f"""
<section class="vista">
  <div class="tit-vista"><h1>Nuevo equipo</h1>
  <p class="sec">Se crea con un componente; los CML se agregan luego en la pestaña Esquema y CML.
  Los campos marcados por familia solo se usan para esa familia.</p></div>
  <form data-form="crear_equipo" class="tarjeta form-nuevo">
    {dl("dl-plantas", plantas)}{dl("dl-areas", areas)}{dl("dl-sistemas", sistemas)}
    <h3>Ubicación técnica</h3>
    <div class="grid-campos">
      {campo("planta", "Planta", plantas[0] if plantas else "", "text", requerido=True, lista="dl-plantas")}
      {campo("area", "Área", "", "text", requerido=True, lista="dl-areas")}
      {campo("sistema", "Sistema / línea / circuito", "", "text", requerido=True, lista="dl-sistemas")}
    </div>
    <h3>Identificación</h3>
    <div class="grid-campos">
      {campo("tag", "TAG", "", "text", requerido=True)}
      {campo("familia", "Familia", "TUBERIA", opciones=fam)}
      {campo("material", "Material", mats[0][0], opciones=mats, ayuda="Debe corresponder a la familia")}
      {campo("descripcion", "Descripción", "", "text", requerido=True, clase="ancho2")}
      {campo("servicio", "Servicio", "", "text")}
      {campo("fluido", "Fluido", "", "text")}
      {campo("fecha_puesta_servicio", "Puesta en servicio", "", "date")}
      {campo("circuito_inspeccion", "Circuito (tubería)", "", "text", clase="solo-tub")}
    </div>
    <h3>Diseño</h3>
    <div class="grid-campos">
      {campo("P_dis", "Presión de diseño", 0, unidad="MPa", minimo=0, clase="no-tan")}
      {campo("T_dis", "Temperatura de diseño", 40, unidad="°C", requerido=True)}
      {campo("CA", "CA", 1.5, unidad="mm", minimo=0)}
      {campo("E", "E", 1.0, minimo=0, maximo=1)}
      {campo("clase_tuberia", "Clase (tubería)", "2", opciones=OPCIONES_CLASE, clase="solo-tub")}
      {campo("diametro_tanque_m", "D del tanque", "", unidad="m", clase="solo-tan")}
      {campo("densidad_relativa_G", "G", "", clase="solo-tan")}
    </div>
    <h3>Componente inicial</h3>
    <div class="grid-campos">
      {campo("t_nom_mm", "t_nom", "", unidad="mm", requerido=True, minimo=0)}
      {campo("diametro_exterior_mm", "D exterior (tubería)", "", unidad="mm", clase="solo-tub")}
      {campo("radio_interior_mm", "R interior (recipiente)", "", unidad="mm", clase="solo-rec")}
      {campo("nivel_sobre_fondo_virola_m", "H sobre fondo de virola 1 (tanque)", "", unidad="m", clase="solo-tan")}
    </div>
    <div class="acciones"><button type="submit" class="btn primario">Crear equipo</button></div>
  </form>
</section>"""


def vista_verificacion(filas: List[Dict[str, Any]], estados: List[Dict[str, Any]],
                       error: Optional[str] = None) -> str:
    if error:
        return f'<section class="vista"><h1>Verificación</h1><div class="msg msg-error">{e(error)}</div></section>'
    ok = sum(r["ok"] for r in filas) + sum(x["ok"] for x in estados)
    total = len(filas) + len(estados)
    cuerpo = "".join(
        f'<tr><td>{e(r["caso"])}</td><td>{e(r["magnitud"])} <small>[{e(r["unidad"])}]</small></td>'
        f'<td class="sec">{e(r["entradas"])}</td><td class="sec">{e(r["referencia"])}</td>'
        f'<td class="n">{num(r["esperado"], 5)}</td><td class="n">{num(r["programa"], 5)}</td>'
        f'<td class="n">{r["dif_relativa"]:.1e}</td><td>{"✅" if r["ok"] else "❌"}</td></tr>' for r in filas)
    cuerpo_e = "".join(
        f'<tr><td><b>{e(x["cml"])}</b></td><td>{chip_estado(x["estado_esperado"])}</td><td>{e(x["alerta_esperada"])}</td>'
        f'<td>{chip_estado(x["estado_programa"])}</td><td class="sec">{e(x["alertas_programa"])}</td>'
        f'<td>{"✅" if x["ok"] else "❌"}</td></tr>' for x in estados)
    return f"""
<section class="vista">
  <div class="tit-vista"><h1>Verificación independiente</h1>
  <p class="sec">Los valores <b>esperados</b> se recalculan en <code>tools/validacion_independiente.py</code> con las
  ecuaciones escritas de nuevo y los datos transcritos a mano, sin usar el motor. El <b>programa</b> evalúa el caso
  demostrativo ORIGINAL (no las modificaciones hechas en esta sesión) con fecha 2026-11-23.</p></div>
  <div class="kpis"><div class="kpi {"est-borde-normal" if ok == total else "est-borde-bajo_minimo"}">
    <div class="kpi-t">Comprobaciones</div><div class="kpi-v">{ok}/{total}</div><div class="kpi-sub">OK</div></div></div>
  <div class="tarjeta"><h2>Un cálculo por familia y uno del módulo RBI</h2>
  <div class="tabla-w"><table class="tabla"><thead><tr><th>Caso</th><th>Magnitud</th><th>Entradas</th><th>Referencia</th>
  <th class="n">Esperado</th><th class="n">Programa</th><th class="n">Dif. rel.</th><th></th></tr></thead>
  <tbody>{cuerpo}</tbody></table></div></div>
  <div class="tarjeta"><h2>Condiciones demostrativas (normal, alerta, bajo mínimo, vencida, datos insuficientes)</h2>
  <div class="tabla-w"><table class="tabla"><thead><tr><th>CML</th><th>Esperado</th><th>Alerta esperada</th>
  <th>Programa</th><th>Alertas del programa</th><th></th></tr></thead><tbody>{cuerpo_e}</tbody></table></div></div>
</section>"""


def vista_normas() -> str:
    ed = "".join(f"<tr><th>{e(k)}</th><td>{e(v)}</td></tr>" for k, v in ce.EDICIONES_NORMATIVAS.items())
    crit = "".join(f"<tr><th>{e(k)}</th><td>{_valor(v)}</td></tr>" for k, v in ce.CRITERIOS_GRUPO.items())

    def tabla_mat(cat: Dict[str, Dict[str, Any]]) -> str:
        filas = []
        for k, m in cat.items():
            if "temperaturas_C" in m:
                st = ", ".join(f"{t:g} °C: {s:g}" for t, s in zip(m["temperaturas_C"], m["S_MPa"]))
            else:
                st = f"Sd = {m['Sd_MPa']:g} · St = {m['St_MPa']:g} (≤ {m['temperatura_max_C']:g} °C)"
            filas.append(f"<tr><td><b>{e(k)}</b><br><small>{e(m['descripcion'])}</small></td><td>{e(m['norma_tabla'])}</td>"
                         f"<td class='n'>{m['smys_MPa']:g} / {m['smts_MPa']:g}</td><td class='sec'>{e(st)}</td></tr>")
        return "".join(filas)

    mats = tabla_mat(ce.MATERIALES_TUBERIA) + tabla_mat(ce.MATERIALES_RECIPIENTE) + tabla_mat(ce.MATERIALES_TANQUE)
    return f"""
<section class="vista">
  <div class="tit-vista"><h1>Normas, alcance y supuestos</h1>
  <p class="sec">Prototipo académico. No reemplaza a un inspector autorizado ni una evaluación de ingeniería.</p></div>
  <div class="grid2">
    <div class="tarjeta"><h2>Ediciones declaradas</h2><table class="kv">{ed}</table></div>
    <div class="tarjeta"><h2>Alcance por familia</h2><table class="kv">
      <tr><th>Tuberías</th><td>Tramo recto, presión interna: B31.3 §304.1.2 Ec. (3a); API 570 §6.3, §7.1, Tabla 1.</td></tr>
      <tr><th>Recipientes</th><td>Envolvente cilíndrica: VIII-1 UG-27(c)(1), UG-16; II-D Tabla 1A; API 510 §6.4, §6.5.1.1.</td></tr>
      <tr><th>Tanques</th><td>{e(ce.ALCANCE_TANQUE)}</td></tr>
      <tr><th>RBI</th><td>Adelgazamiento generalizado, API RP 580 (proceso) y RP 581 3.ª ed. Parte 2 §4; consecuencias como datos de entrada.</td></tr>
    </table></div>
  </div>
  <div class="tarjeta"><h2>Catálogo de materiales (acotado)</h2>
    <div class="msg msg-aviso">{e(ce._NOTA_VERIFICACION)}</div>
    <div class="tabla-w"><table class="tabla"><thead><tr><th>Material</th><th>Tabla</th><th class="n">SMYS / SMTS [MPa]</th>
    <th>Esfuerzo admisible [MPa]</th></tr></thead><tbody>{mats}</tbody></table></div></div>
  <div class="grid2">
    <div class="tarjeta"><h2>Criterios del grupo (no normativos)</h2><table class="kv">{crit}</table>
      <ul class="obs">
        <li>t_alerta = t_min + CR_gov·Δt_margen (equivale a RL ≤ Δt_margen).</li>
        <li>CR_gov = max(CR_LT, CR_ST), criterio conservador.</li>
        <li>API 510 con RL &lt; 4 años: por defecto min(RL/4, 2 años), más restrictivo que el texto de §6.5.1.1, que permite min(RL, 2 años).</li>
        <li>Matriz 5×5: forma de API RP 581 Parte 1; la asignación de niveles es del grupo.</li>
      </ul></div>
    <div class="tarjeta"><h2>Simplificaciones del RBI</h2><ul class="obs">
      <li>A_rt = CR·edad/t_ref, con t_ref = t_nom y la edad desde la puesta en servicio.</li>
      <li>D_f por confiabilidad estructural con actualización bayesiana (estados de daño 1/2/4; COV 0.20/0.20/0.05; normalización 1.56E−4; mínimo 0.1).</li>
      <li>Factores de ajuste agrupados en uno solo (por defecto 1.0).</li>
      <li>f_F = gff·D_f·F_MS (anual); R_A = f_F·C_A [m²/año]; R_E = f_F·C_E [moneda/año].</li>
      <li>{e(ce.NOTA_INSPECCION_RBI)}</li>
    </ul></div>
  </div>
</section>"""
