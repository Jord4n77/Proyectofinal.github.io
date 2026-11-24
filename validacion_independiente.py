"""
validacion_independiente.py — Comparación independiente (Enunciado §6).

Los valores ESPERADOS se recalculan aquí desde cero, con las ecuaciones escritas
de nuevo y los datos del caso demostrativo transcritos a mano, SIN importar
``calc_engine``. Los valores del PROGRAMA se obtienen cargando
``data/proyecto_demo.json`` y evaluándolo con ``servicios`` (motor + modelo).

Se incluye un cálculo por familia y uno del módulo RBI, más la condición esperada
de los 12 CML. Genera ``data/validacion_independiente.md`` y ``.csv``.

Uso:  python tools/validacion_independiente.py
"""

from __future__ import annotations

import csv
import math
import os
import sys
from datetime import date

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(RAIZ, "src"))

TOL_REL = 1e-6
HOY = date(2026, 11, 23)


def anios(f0: date, f1: date) -> float:
    return (f1 - f0).days / 365.25


def phi(x: float) -> float:
    return 0.5 * math.erfc(-x / math.sqrt(2.0))


# =============================================================================
# Valores esperados (cálculo independiente)
# =============================================================================

def esperados():
    E = []  # (caso, magnitud, unidad, entradas, referencia, esperado, clave_programa)

    # ---------- 1. Tubería L-1001, CML-02 ----------------------------------
    P, D, S, Ej, W, Y = 5.0, 168.3, 138.0, 1.0, 1.0, 0.4
    t_p = P * D / (2 * (S * Ej * W + P * Y))                      # 841.5/280
    cr = (5.10 - 3.45) / anios(date(2022, 6, 14), date(2026, 6, 16))
    rl = (3.45 - t_p) / cr
    t_al = t_p + cr * 2.0
    inter = min(rl / 2, 10.0)
    caso = "Tubería L-1001 / CML-02"
    E += [
        (caso, "t requerido por presión", "mm", "P=5 MPa, D=168.3 mm, S=138 MPa, E=W=1, Y=0.4",
         "ASME B31.3 §304.1.2 Ec. (3a)", t_p, ("esp", "L-1001", "L-1001-TR01", "t_presion")),
        (caso, "CR_gov (= CR_ST)", "mm/año", "5.10 → 3.45 mm; 2022-06-14 → 2026-06-16",
         "API 570 §7.1.1", cr, ("cml", "L-1001-CML-02", "cr_gov")),
        (caso, "Vida remanente", "años", "(3.45 − t_min)/CR_gov", "API 570 §7.2.1", rl,
         ("cml", "L-1001-CML-02", "vida_remanente")),
        (caso, "t_alerta", "mm", "t_min + CR_gov·2 años", "Criterio del grupo", t_al,
         ("cml", "L-1001-CML-02", "t_alerta")),
        (caso, "Intervalo de espesores", "años", "min(RL/2, 10) — Clase 2", "API 570 §6.3.3, Tabla 1",
         inter, ("cml", "L-1001-CML-02", "intervalo")),
    ]

    # ---------- 2. Recipiente V-2001, CML-03 -------------------------------
    P, R, CA, S, Ej = 1.5, 750.0, 3.0, 138.0, 0.85
    t_req = P * (R + CA) / (S * Ej - 0.6 * P)                      # 1129.5/116.4
    cr_lt = (13.60 - 11.10) / anios(date(2014, 5, 20), date(2022, 6, 14))
    cr_st = (12.40 - 11.10) / anios(date(2018, 6, 12), date(2022, 6, 14))
    cr = max(cr_lt, cr_st)
    rl = (11.10 - t_req) / cr
    inter = min(rl / 2, 10.0) if rl >= 4 else min(rl / 4, 2.0)
    caso = "Recipiente V-2001 / CML-03"
    E += [
        (caso, "t requerido UG-27(c)(1)", "mm", "P=1.5 MPa, R=750+3 mm, S=138 MPa (200 °C), E=0.85",
         "ASME VIII-1 UG-27(c)(1); II-D Tabla 1A", t_req, ("esp", "V-2001", "V-2001-ENV", "t_req")),
        (caso, "CR_LT", "mm/año", "13.60 → 11.10 mm; 2014-05-20 → 2022-06-14", "API 510 §7.1.1",
         cr_lt, ("cml", "V-2001-CML-03", "cr_lt")),
        (caso, "CR_ST", "mm/año", "12.40 → 11.10 mm; 2018-06-12 → 2022-06-14", "API 510 §7.1.1",
         cr_st, ("cml", "V-2001-CML-03", "cr_st")),
        (caso, "Vida remanente", "años", "(11.10 − t_req)/max(CR_LT, CR_ST)", "API 510 §7.2.1", rl,
         ("cml", "V-2001-CML-03", "vida_remanente")),
        (caso, "Intervalo interno/en servicio", "años", "RL ≥ 4 → min(RL/2, 10)", "API 510 §6.5.1.1",
         inter, ("cml", "V-2001-CML-03", "intervalo")),
    ]

    # ---------- 3. Tanque T-3001, virola 1 / CML-02 ------------------------
    Dt, Hl, G, Sd, St, CA = 30.0, 12.0, 0.85, 160.0, 171.0, 1.5
    td = 4.9 * Dt * (Hl - 0.3) * G / Sd + CA
    tt = 4.9 * Dt * (Hl - 0.3) / St
    S653 = min(0.80 * 250.0, 0.429 * 400.0)
    tmin = max(4.9 * Dt * (Hl - 0.3) * G / S653, 2.5)
    cr = (10.60 - 9.00) / anios(date(2021, 9, 14), date(2026, 9, 15))
    rca = 9.00 - tmin
    ut = min(rca / (2 * cr), 15.0)
    caso = "Tanque T-3001 / Virola 1 / CML-02"
    E += [
        (caso, "t_d (diseño, 1 pie)", "mm", "D=30 m, H=12 m, G=0.85, Sd=160 MPa, CA=1.5 mm",
         "API 650 §5.6.3.2", td, ("esp", "T-3001", "T-3001-V1", "t_d")),
        (caso, "t_t (prueba hidrostática)", "mm", "D=30 m, H=12 m, St=171 MPa",
         "API 650 §5.6.3.2", tt, ("esp", "T-3001", "T-3001-V1", "t_t")),
        (caso, "t_min en servicio", "mm", "S=min(0.80·250, 0.429·400)=171.6 MPa, E=1",
         "API 653 §4.3.3.1, Tabla 4.1", tmin, ("esp", "T-3001", "T-3001-V1", "t_min")),
        (caso, "CR_gov (= CR_ST)", "mm/año", "10.60 → 9.00 mm; 2021-09-14 → 2026-09-15",
         "API 653 §4.3", cr, ("cml", "T-3001-CML-02", "cr_gov")),
        (caso, "Intervalo UT del manto", "años", "min(RCA/2N, 15)", "API 653 §6.3.3.2", ut,
         ("cml", "T-3001-CML-02", "intervalo")),
    ]

    # ---------- 4. RBI V-2001 ---------------------------------------------
    cr = (11.40 - 9.55) / anios(date(2022, 6, 14), date(2026, 6, 16))   # CML-02, mayor CR del equipo
    edad = anios(date(2008, 3, 1), HOY)
    art = cr * edad / 16.0
    FS = 1.1 * 0.85 * (260.0 + 485.0) / 2
    sr = (138.0 * 0.85 / FS) * (t_req / 16.0)
    prev = (0.80, 0.15, 0.05)                                           # confianza ALTA
    cond = {"B": (0.70, 0.20, 0.10), "C": (0.50, 0.30, 0.20)}
    sin = [prev[i] * cond["B"][i] ** 1 * cond["C"][i] ** 3 for i in range(3)]
    post = [x / sum(sin) for x in sin]
    pf = []
    for ds in (1.0, 2.0, 4.0):
        num = 1 - ds * art - sr
        den = math.sqrt((ds * art * 0.20) ** 2 + ((1 - ds * art) * 0.20) ** 2 + (sr * 0.05) ** 2)
        pf.append(phi(-num / den))
    df = max(sum(p * q for p, q in zip(post, pf)) / 1.56e-4, 0.1)
    fms = 10 ** (-0.02 * 60 + 1)                                        # puntaje 600 → 60 %
    ff = 3.06e-5 * df * fms
    caso = "RBI V-2001 (adelgazamiento)"
    E += [
        (caso, "A_rt", "—", f"CR={cr:.4f} mm/año, edad={edad:.3f} años, t_ref=16 mm",
         "API RP 581 Parte 2 §4 (simplificado)", art, ("rbi", "V-2001", "A_rt")),
        (caso, "SR_P", "—", "S=138, E=0.85, YS=260, TS=485 MPa, t_min/t_ref", "API RP 581 Parte 2 §4",
         sr, ("rbi", "V-2001", "SR_P")),
        (caso, "D_f (factor de daño)", "—", "1 insp. B + 3 C, confianza ALTA", "API RP 581 Parte 2 §4",
         df, ("rbi", "V-2001", "D_f")),
        (caso, "f_F = gff·D_f·F_MS", "1/año", "gff=3.06E−5, F_MS=10^(−0.02·60+1)", "API RP 581 Parte 2 §2",
         ff, ("rbi", "V-2001", "f_F")),
        (caso, "R_A = f_F·C_A", "m²/año", "C_A = 450 m²", "Enunciado §5", ff * 450.0,
         ("rbi", "V-2001", "R_A")),
        (caso, "R_E = f_F·C_E", "CLP/año", "C_E = 1.2E9 CLP", "Enunciado §5", ff * 1.2e9,
         ("rbi", "V-2001", "R_E")),
    ]
    return E


ESTADOS_ESPERADOS = {
    "L-1001-CML-01": ("NORMAL", None),
    "L-1001-CML-02": ("ALERTA", None),
    "L-1001-CML-03": ("NORMAL", "LINEA_BASE_REINICIADA"),
    "L-1001-CML-04": ("NORMAL", "DATOS_INSUFICIENTES"),
    "V-2001-CML-01": ("NORMAL", None),
    "V-2001-CML-02": ("BAJO_MINIMO", "BAJO_MINIMO"),
    "V-2001-CML-03": ("INSPECCION_VENCIDA", "PROYECCION_BAJO_MINIMO"),
    "V-2001-CML-04": ("NORMAL", "CORROSION_NULA_O_NEGATIVA"),
    "T-3001-CML-01": ("NORMAL", None),
    "T-3001-CML-02": ("ALERTA", None),
    "T-3001-CML-03": ("NORMAL", "FECHAS_INCONSISTENTES"),
    "T-3001-CML-04": ("NORMAL", "CORROSION_NULA_O_NEGATIVA"),
}


# =============================================================================
# Valores del programa
# =============================================================================

def valores_programa(proyecto=None):
    """Evalúa el caso demostrativo con el programa. ``proyecto``: objeto ya cargado
    (uso en el navegador); si es None se lee ``data/proyecto_demo.json``."""
    import servicios
    from models import Proyecto
    if proyecto is None:
        with open(os.path.join(RAIZ, "data", "proyecto_demo.json"), encoding="utf-8") as f:
            proyecto = Proyecto.desde_json(f.read())
    ev = servicios.evaluar_proyecto(proyecto, HOY)
    esp, cml = {}, {}
    for tag, e in ev["equipos"].items():
        for c in e["componentes"]:
            esp[(tag, c["componente_id"])] = c["espesores"]["resultado"]
            for m in c["cmls"]:
                cml[m["identificacion"]["cml_id"]] = m
    rbi = {tag: r["resultado"] for tag, r in ev["rbi"].items()}
    return esp, cml, rbi


def comparar(proyecto=None):
    esp, cml, rbi = valores_programa(proyecto)
    filas = []
    for caso, mag, uni, ent, ref, esperado, clave in esperados():
        if clave[0] == "esp":
            prog = esp[(clave[1], clave[2])][clave[3]]
        elif clave[0] == "cml":
            prog = cml[clave[1]]["resultado"][clave[2]]
        else:
            prog = rbi[clave[1]][clave[2]]
        dif = abs(prog - esperado) / abs(esperado) if esperado else abs(prog)
        filas.append({"caso": caso, "magnitud": mag, "unidad": uni, "entradas": ent,
                      "referencia": ref, "esperado": esperado, "programa": prog,
                      "dif_relativa": dif, "ok": dif <= TOL_REL})
    estados = []
    for cml_id, (est, alerta) in ESTADOS_ESPERADOS.items():
        m = cml[cml_id]
        ok = m["resultado"]["estado"] == est and (alerta is None or alerta in m["alertas"])
        estados.append({"cml": cml_id, "estado_esperado": est, "alerta_esperada": alerta or "—",
                        "estado_programa": m["resultado"]["estado"],
                        "alertas_programa": ", ".join(m["alertas"]) or "—", "ok": ok})
    return filas, estados


def _fmt(x: float) -> str:
    if abs(x) >= 1e5 or (abs(x) < 1e-2 and x != 0):
        return f"{x:.4e}"
    return f"{x:.5f}"


def escribir(filas, estados) -> None:
    ruta_csv = os.path.join(RAIZ, "data", "validacion_independiente.csv")
    with open(ruta_csv, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(filas[0]))
        w.writeheader()
        w.writerows(filas)
    lineas = [
        "# Validación independiente — caso demostrativo",
        "",
        f"Fecha de evaluación: {HOY.isoformat()} · Tolerancia relativa: {TOL_REL:g}",
        "",
        "El **esperado** se recalcula en `tools/validacion_independiente.py` con las ecuaciones "
        "escritas de nuevo, sin importar el motor. El **programa** es la salida de "
        "`servicios.evaluar_proyecto` sobre `data/proyecto_demo.json`.",
        "",
        "## Cálculos por familia y RBI",
        "",
        "| Caso | Magnitud | Entradas | Referencia | Esperado | Programa | Dif. rel. | ✓ |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for r in filas:
        lineas.append(f"| {r['caso']} | {r['magnitud']} [{r['unidad']}] | {r['entradas']} | {r['referencia']} | "
                      f"{_fmt(r['esperado'])} | {_fmt(r['programa'])} | {r['dif_relativa']:.1e} | "
                      f"{'✅' if r['ok'] else '❌'} |")
    lineas += ["", "## Condición de los 12 CML", "",
               "| CML | Estado esperado | Alerta esperada | Estado programa | Alertas programa | ✓ |",
               "|---|---|---|---|---|---|"]
    for e in estados:
        lineas.append(f"| {e['cml']} | {e['estado_esperado']} | {e['alerta_esperada']} | {e['estado_programa']} | "
                      f"{e['alertas_programa']} | {'✅' if e['ok'] else '❌'} |")
    with open(os.path.join(RAIZ, "data", "validacion_independiente.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lineas) + "\n")


if __name__ == "__main__":
    filas, estados = comparar()
    escribir(filas, estados)
    n_ok = sum(r["ok"] for r in filas) + sum(e["ok"] for e in estados)
    print(f"{n_ok}/{len(filas) + len(estados)} comprobaciones OK")
    for r in filas + estados:
        if not r["ok"]:
            print("FALLA:", r)
    sys.exit(0 if n_ok == len(filas) + len(estados) else 1)
