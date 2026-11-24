"""
generar_esquemas.py — Dibuja los esquemas PNG del caso demostrativo (Pillow).

Genera, en ``assets/img/``:
  * ``L-1001_isometrico.png``, ``V-2001_esquema.png``, ``T-3001_elevacion.png``:
    imágenes base SIN marcadores (la aplicación dibuja los CML encima a partir de
    las coordenadas guardadas en el proyecto).
  * ``*_marcadores.png``: vista previa con los CML superpuestos, para verificar
    las coordenadas y para usar en las diapositivas.

Uso:  python tools/generar_esquemas.py
"""

from __future__ import annotations

import math
import os
import sys

from PIL import Image, ImageDraw, ImageFont

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(RAIZ, "src"))
import demo_data as dd  # noqa: E402

W, H = dd.ANCHO_ESQUEMA, dd.ALTO_ESQUEMA
K = 2  # sobremuestreo para antialias
TINTA = (31, 41, 55)
GRIS = (120, 128, 140)
GRIS_CLARO = (226, 230, 236)
ACERO = (203, 213, 225)
AGUA = (191, 219, 254)
PRODUCTO = (254, 243, 199)
ACENTO = (180, 83, 9)
FUENTES = "/usr/share/fonts/truetype/dejavu/"


def _f(tam: int, negrita: bool = False) -> ImageFont.FreeTypeFont:
    nombre = "DejaVuSans-Bold.ttf" if negrita else "DejaVuSans.ttf"
    try:
        return ImageFont.truetype(os.path.join(FUENTES, nombre), tam * K)
    except OSError:  # pragma: no cover
        return ImageFont.load_default()


def _s(*pts):
    """Escala coordenadas lógicas (1200×750) al lienzo sobremuestreado."""
    return [v * K for v in pts]


class Lienzo:
    def __init__(self):
        self.img = Image.new("RGB", (W * K, H * K), "white")
        self.d = ImageDraw.Draw(self.img)

    def linea(self, pts, color=TINTA, ancho=2, discontinua=False):
        if not discontinua:
            self.d.line(_s(*[c for p in pts for c in p]), fill=color, width=ancho * K, joint="curve")
            return
        for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
            largo = math.hypot(x1 - x0, y1 - y0)
            n = max(int(largo // 10), 1)
            for i in range(0, n, 2):
                a, b = i / n, min((i + 1) / n, 1)
                self.d.line(_s(x0 + (x1 - x0) * a, y0 + (y1 - y0) * a,
                               x0 + (x1 - x0) * b, y0 + (y1 - y0) * b), fill=color, width=ancho * K)

    def rect(self, x0, y0, x1, y1, relleno=None, borde=TINTA, ancho=2):
        self.d.rectangle(_s(x0, y0, x1, y1), fill=relleno, outline=borde, width=ancho * K)

    def poligono(self, pts, relleno=None, borde=TINTA, ancho=2):
        self.d.polygon(_s(*[c for p in pts for c in p]), fill=relleno, outline=borde, width=ancho * K)

    def elipse(self, x0, y0, x1, y1, relleno=None, borde=TINTA, ancho=2):
        self.d.ellipse(_s(x0, y0, x1, y1), fill=relleno, outline=borde, width=ancho * K)

    def arco(self, x0, y0, x1, y1, ini, fin, color=TINTA, ancho=2):
        self.d.arc(_s(x0, y0, x1, y1), ini, fin, fill=color, width=ancho * K)

    def texto(self, x, y, t, tam=14, color=TINTA, negrita=False, ancla="la"):
        self.d.text(_s(x, y), t, fill=color, font=_f(tam, negrita), anchor=ancla)

    def flecha(self, x0, y0, x1, y1, color=TINTA, ancho=2):
        self.linea([(x0, y0), (x1, y1)], color, ancho)
        ang = math.atan2(y1 - y0, x1 - x0)
        p1 = (x1 - 14 * math.cos(ang - 0.4), y1 - 14 * math.sin(ang - 0.4))
        p2 = (x1 - 14 * math.cos(ang + 0.4), y1 - 14 * math.sin(ang + 0.4))
        self.poligono([(x1, y1), p1, p2], relleno=color, borde=color, ancho=1)

    def rotulo(self, tag, titulo, subtitulo):
        self.rect(820, 650, 1180, 735, relleno=(248, 250, 252), borde=TINTA, ancho=2)
        self.linea([(820, 678), (1180, 678)], TINTA, 1)
        self.texto(830, 656, f"{tag} — {titulo}", 15, negrita=True)
        self.texto(830, 686, subtitulo, 12, GRIS)
        self.texto(830, 708, "Esquema académico sin escala · datos ficticios", 11, GRIS)

    def guardar(self, ruta):
        self.img.resize((W, H), Image.LANCZOS).save(ruta, optimize=True)


def _iso(p, largo, direccion):
    dx, dy = {"NE": (0.866, -0.5), "SE": (0.866, 0.5)}[direccion]
    return (p[0] + dx * largo, p[1] + dy * largo)


def _soldadura(lz, p, direccion, tam=9):
    dx, dy = {"NE": (0.866, -0.5), "SE": (0.866, 0.5), "V": (0, 1)}[direccion]
    nx, ny = -dy, dx
    lz.linea([(p[0] - nx * tam, p[1] - ny * tam), (p[0] + nx * tam, p[1] + ny * tam)], TINTA, 2)


# =============================================================================
def esquema_tuberia() -> Lienzo:
    lz = Lienzo()
    P0 = (100, 560)
    P1 = _iso(P0, 300, "NE")
    P2 = (P1[0], 250)
    P3 = _iso(P2, 420, "SE")
    P4 = _iso(P3, 380, "NE")
    # Bomba (origen) y recipiente (destino)
    lz.rect(40, 575, 160, 640, relleno=GRIS_CLARO)
    lz.texto(100, 607, "P-1001 A/B", 12, negrita=True, ancla="mm")
    lz.linea([(100, 575), P0], TINTA, 6)
    lz.rect(P4[0] - 10, P4[1] - 60, P4[0] + 110, P4[1] + 20, relleno=GRIS_CLARO)
    lz.texto(P4[0] + 50, P4[1] - 35, "V-2001", 13, negrita=True, ancla="mm")
    lz.texto(P4[0] + 50, P4[1] - 13, "boquilla N1", 11, GRIS, ancla="mm")
    # Línea (doble trazo para dar cuerpo)
    tramo = [P0, P1, P2, P3, P4]
    lz.linea(tramo, TINTA, 9)
    lz.linea(tramo, (255, 255, 255), 5)
    # Carrete reemplazado 2022 (entre 20 % y 60 % del último tramo)
    a, b = _iso(P3, 0.2 * 380, "NE"), _iso(P3, 0.6 * 380, "NE")
    lz.linea([a, b], ACENTO, 5)
    _soldadura(lz, a, "NE"), _soldadura(lz, b, "NE")
    lz.texto(b[0] - 40, b[1] + 50, "Carrete reemplazado 05-2022", 12, ACENTO)
    # Codos y soldaduras
    for p, dirc in ((P1, "NE"), (P2, "SE"), (P3, "NE")):
        lz.elipse(p[0] - 6, p[1] - 6, p[0] + 6, p[1] + 6, relleno=TINTA)
    for p, dirc in ((_iso(P0, 60, "NE"), "NE"), ((P1[0], 330), "V"), (_iso(P2, 80, "SE"), "SE")):
        _soldadura(lz, p, dirc)
    # Válvula de control FV-1001 (40 % del tramo P2–P3)
    v = _iso(P2, 0.40 * 420, "SE")
    e1, e2 = _iso(v, -18, "SE"), _iso(v, 18, "SE")
    lz.poligono([e1, (v[0] - 9, v[1] + 16), (v[0] + 9, v[1] - 16)], relleno="white")
    lz.poligono([e2, (v[0] - 9, v[1] + 16), (v[0] + 9, v[1] - 16)], relleno="white")
    lz.linea([v, (v[0], v[1] - 34)], TINTA, 2)
    lz.rect(v[0] - 14, v[1] - 50, v[0] + 14, v[1] - 34, relleno="white")
    lz.texto(v[0] - 20, v[1] - 74, "FV-1001", 12, negrita=True)
    # Flujo
    f0 = _iso(P0, 110, "NE")
    lz.flecha(f0[0], f0[1] + 26, *_iso((f0[0], f0[1] + 26), 70, "NE"), color=GRIS)
    lz.texto(f0[0] + 8, f0[1] + 34, "FLUJO", 11, GRIS, negrita=True)
    # Rosa de orientación
    lz.flecha(70, 120, *_iso((70, 120), 60, "NE"))
    lz.texto(128, 78, "N", 13, negrita=True)
    lz.texto(40, 30, "Tramo recto NPS 6 Sch 40 · A106 Gr. B · t_nom 7.11 mm · CIR-100-01", 14, negrita=True)
    lz.texto(40, 52, "Convención CML: posición horaria vista en sentido del flujo; distancia desde soldadura aguas arriba",
             11, GRIS)
    lz.rotulo("L-1001", "Isométrico de tubería", "ASME B31.3 / API 570 · Tramo recto")
    return lz


def esquema_recipiente() -> Lienzo:
    lz = Lienzo()
    x0, x1, y0, y1 = 200, 1000, 220, 470
    # Agua y producto
    lz.rect(x0, 400, x1, y1, relleno=AGUA, borde=None, ancho=0)
    lz.rect(x0, 300, x1, 400, relleno=PRODUCTO, borde=None, ancho=0)
    # Bota
    lz.rect(760, y1 - 4, 860, 600, relleno=AGUA)
    lz.texto(810, 612, "Bota de agua", 12, GRIS, ancla="ma")
    # Envolvente y cabezales elípticos 2:1
    lz.rect(x0, y0, x1, y1, relleno=None, ancho=3)
    lz.arco(x0 - 70, y0, x0 + 70, y1, 90, 270, ancho=3)
    lz.arco(x1 - 70, y0, x1 + 70, y1, 270, 90, ancho=3)
    for x in (x0, x1):
        lz.linea([(x, y0), (x, y1)], GRIS, 1, discontinua=True)
    lz.texto(x0 - 40, y1 + 14, "Cabezal N1", 11, GRIS)
    # Soldaduras circunferenciales intermedias
    for x in (467, 733):
        lz.linea([(x, y0), (x, y1)], GRIS, 1)
    # Aislación (zona del CML-03)
    for i in range(300, 500, 14):
        lz.linea([(i, y0 + 2), (i + 30, y0 + 40)], (148, 163, 184), 1)
        lz.linea([(i, y1 - 40), (i + 30, y1 - 2)], (148, 163, 184), 1)
    lz.rect(300, y0, 500, y1, relleno=None, borde=(148, 163, 184), ancho=2)
    lz.texto(400, y0 - 26, "Zona aislada", 12, (100, 116, 139), ancla="ma")
    # Niveles
    lz.linea([(x0, 400), (x1, 400)], (37, 99, 235), 1, discontinua=True)
    lz.texto(x1 + 80, 393, "Interfase agua", 11, (37, 99, 235))
    lz.linea([(x0, 300), (x1, 300)], ACENTO, 1, discontinua=True)
    lz.texto(x1 + 80, 293, "NLL producto", 11, ACENTO)
    # Boquillas
    for x, nombre in ((290, "N1 entrada"), (900, "N3 venteo")):
        lz.rect(x - 14, y0 - 50, x + 14, y0, relleno="white")
        lz.rect(x - 24, y0 - 58, x + 24, y0 - 50, relleno=TINTA)
        lz.texto(x, y0 - 82, nombre, 12, ancla="ma")
    lz.rect(586, y1, 614, y1 + 40, relleno="white")
    lz.texto(630, y1 + 18, "N2 salida", 11, GRIS)
    # Silletas
    for x in (330, 930):
        lz.poligono([(x - 50, 560), (x + 50, 560), (x + 30, y1), (x - 30, y1)], relleno=GRIS_CLARO)
    lz.linea([(150, 560), (1050, 560)], TINTA, 3)
    # Cotas
    lz.linea([(x0, 150), (x1, 150)], GRIS, 1)
    lz.texto(600, 128, "Envolvente cilíndrica · Ø int. 1500 mm · t_nom 16 mm · SA-516 Gr. 70", 13, ancla="ma")
    lz.texto(40, 30, "V-2001 Acumulador horizontal de nafta con bota de agua", 15, negrita=True)
    lz.texto(40, 52, "Convención CML: posición horaria vista desde el cabezal N1; distancia desde soldadura cabezal-envolvente N1",
             11, GRIS)
    lz.rotulo("V-2001", "Esquema del recipiente", "ASME VIII Div. 1 / API 510 · Envolvente cilíndrica")
    return lz


def esquema_tanque() -> Lienzo:
    lz = Lienzo()
    x0, x1, yb = 260, 760, 630
    alto = 78
    xc = (x0 + x1) / 2
    # Producto hasta el nivel de diseño y agua decantada en el fondo
    lz.rect(x0, yb - 6 * alto + 8, x1, yb, relleno=PRODUCTO, borde=None, ancho=0)
    lz.rect(x0, yb - 25, x1, yb, relleno=AGUA, borde=None, ancho=0)
    espesores = [12, 10, 8, 8, 8, 8]
    for i in range(6):
        y_inf = yb - i * alto
        y_sup = y_inf - alto
        lz.rect(x0, y_sup, x1, y_inf, relleno=None, ancho=3 if i < 3 else 2)
        for xs in ((x0 + 125, x1 - 125) if i % 2 == 0 else (xc,)):   # costuras verticales desfasadas
            lz.linea([(xs, y_sup), (xs, y_inf)], GRIS, 1)
        lz.texto(x0 - 18, (y_sup + y_inf) / 2, f"Virola {i + 1} · {espesores[i]} mm", 12,
                 TINTA if i < 3 else GRIS, negrita=i < 3, ancla="rm")
    # Techo cónico
    ytop = yb - 6 * alto
    lz.poligono([(x0 - 6, ytop), (xc, ytop - 55), (x1 + 6, ytop)], relleno=GRIS_CLARO)
    # Fondo y fundación
    lz.linea([(x0 - 30, yb), (x1 + 30, yb)], TINTA, 4)
    lz.poligono([(x0 - 55, yb + 28), (x1 + 55, yb + 28), (x1 + 30, yb + 2), (x0 - 30, yb + 2)],
                relleno=(231, 229, 228))
    # Nivel de diseño
    yn = ytop + 8
    lz.linea([(x0, yn), (x1, yn)], ACENTO, 1, discontinua=True)
    lz.texto(x1 + 20, yn - 8, "Nivel de diseño H = 12.0 m", 12, ACENTO)
    # Diámetro
    lz.flecha(x0, yb + 48, x1, yb + 48, GRIS, 1)
    lz.flecha(x1, yb + 48, x0, yb + 48, GRIS, 1)
    lz.texto(xc, yb + 54, "D = 30.0 m", 12, GRIS, ancla="ma")
    # Drenaje de agua (180°) y boquilla de entrada
    lz.rect(x1, yb - 35, x1 + 40, yb - 15, relleno="white")
    lz.texto(x1 + 46, yb - 34, "Drenaje de agua (180°)", 11, GRIS)
    ye = yb - 3.5 * alto
    lz.rect(x1, ye - 12, x1 + 40, ye + 12, relleno="white")
    lz.texto(x1 + 46, ye - 7, "Entrada de producto", 11, GRIS)
    # Encabezado y alcance
    lz.texto(40, 30, "T-3001 Tanque de techo fijo · Diésel G = 0.85 · A36M · 6 virolas × 2.0 m", 15, negrita=True)
    lz.texto(40, 52, "Convención CML: ángulo en planta (0° = norte, horario); altura desde soldadura inferior de la virola",
             11, GRIS)
    lz.rect(880, 220, 1180, 330, relleno=(255, 251, 235), borde=ACENTO, ancho=1)
    lz.texto(895, 232, "Alcance del cálculo", 13, ACENTO, negrita=True)
    lz.texto(895, 256, "Virolas del manto: API 650 (diseño)", 11, ACENTO)
    lz.texto(895, 274, "y API 653 (evaluación en servicio).", 11, ACENTO)
    lz.texto(895, 298, "Fondo y techo: datos pendientes.", 11, ACENTO)
    lz.rotulo("T-3001", "Elevación del manto", "API 650 / API 653 · Virolas del manto")
    return lz


def con_marcadores(ruta_base: str, tag: str, ruta_salida: str) -> None:
    img = Image.open(ruta_base).convert("RGB")
    d = ImageDraw.Draw(img)
    fuente = ImageFont.truetype(os.path.join(FUENTES, "DejaVuSans-Bold.ttf"), 13)
    for cml_id, (fx, fy) in dd.MARCADORES.items():
        if not cml_id.startswith(tag):
            continue
        x, y = fx * W, fy * H
        d.ellipse((x - 11, y - 11, x + 11, y + 11), fill=(220, 38, 38), outline="white", width=3)
        etiqueta = cml_id.replace(tag + "-", "")
        caja = d.textbbox((x + 15, y - 22), etiqueta, font=fuente)
        d.rectangle((caja[0] - 4, caja[1] - 3, caja[2] + 4, caja[3] + 3), fill="white", outline=(220, 38, 38))
        d.text((x + 15, y - 22), etiqueta, fill=(153, 27, 27), font=fuente)
    img.save(ruta_salida, optimize=True)


def main() -> None:
    carpeta = os.path.join(RAIZ, "assets", "img")
    os.makedirs(carpeta, exist_ok=True)
    for tag, fn in (("L-1001", esquema_tuberia), ("V-2001", esquema_recipiente), ("T-3001", esquema_tanque)):
        ruta = os.path.join(RAIZ, dd.ESQUEMAS[tag][1])
        fn().guardar(ruta)
        con_marcadores(ruta, tag, ruta.replace(".png", "_marcadores.png"))
        print("Generado", os.path.relpath(ruta, RAIZ))


if __name__ == "__main__":
    main()
