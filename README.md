# Integridad de Equipos Estáticos — prototipo académico

Proyecto Final MAN040-B. Aplicación web estática (GitHub Pages + PyScript/Pyodide)
para gestionar e inspeccionar equipos estáticos, inspirada en UltraPIPE.

**Estado:** aplicación completa: motor de cálculo, modelo de datos, caso demostrativo validado e interfaz web con PyScript (PyScript 2025.11.2, Pyodide). No se cargan paquetes externos: los gráficos son SVG generados en Python, así la página carga más rápido.

## Ejecutar y publicar

```bash
# Local (PyScript necesita servidor HTTP; no funciona abriendo index.html con file://)
python -m http.server 8000      # luego abrir http://localhost:8000
```

**GitHub Pages:** suba el repositorio y active *Settings → Pages → Deploy from a branch → main / (root)*.
El archivo `.nojekyll` evita que Jekyll procese el sitio. La primera carga descarga Pyodide (entre 10 y 30 s); después queda en la caché del navegador.

## Estructura

```
integridad-estaticos/
├── index.html           # página (PyScript); se publica tal cual en GitHub Pages
├── pyscript.toml        # copia src/*.py, la verificación y el proyecto demo al sistema de archivos de Pyodide
├── web/
│   ├── main.py          # conexión con el DOM: eventos, localStorage, descarga/carga de archivos
│   └── estilos.css
├── src/
│   ├── calc_engine.py   # funciones puras de cálculo normativo (sin DOM, solo stdlib)
│   ├── models.py        # jerarquía planta→equipo→componente→CML→medición, RBI, JSON
│   ├── servicios.py     # integración modelo↔motor
│   ├── vistas.py        # HTML y gráficos SVG (puro, probado con pytest)
│   ├── controlador.py   # estado de la interfaz y acciones del usuario
│   └── demo_data.py     # definición trazable del caso demostrativo
├── tools/
│   ├── generar_esquemas.py          # dibuja los PNG de assets/img/
│   ├── validacion_independiente.py  # recálculo sin el motor (también se muestra en la app)
│   └── vista_previa.py              # capturas de la interfaz con Chrome sin conexión → capturas/
├── data/                # proyecto_demo.json (con adjuntos), versión sin adjuntos, validación .md/.csv
├── assets/img/          # esquemas base y vistas previas *_marcadores.png
├── capturas/            # 13 capturas de la interfaz, listas para las diapositivas
└── tests/               # 125 pruebas: motor, modelo, demo, controlador y web/main.py con DOM simulado
```

```bash
python -m pip install pytest pillow        # (playwright solo para tools/vista_previa.py)
python tools/generar_esquemas.py           # 1) esquemas PNG
python src/demo_data.py                    # 2) data/proyecto_demo*.json
python tools/validacion_independiente.py   # 3) 33/33 comprobaciones
python -m pytest                           # 125 pruebas
```

## Arquitectura de la interfaz

`web/main.py` (DOM) → `Controlador.despachar(acción, datos)` → `servicios` → `calc_engine`.
`Controlador.renderizar()` → `vistas` (HTML/SVG) → `innerHTML` de las regiones de la página.

Los clics usan `data-accion` y los formularios `data-form`. Una prueba verifica que cada acción presente en el HTML tenga su manejador.
Los números aceptan coma o punto decimal. El proyecto se guarda en `localStorage` (botón «Guardar») o se exporta e importa como `.json`, con adjuntos y relaciones incluidos.
`web/main.py` trata el `null` de JavaScript como `jsnull` (Pyodide ≥ 0.28) o como `None` (versiones anteriores).

## Guion sugerido para la demostración (§8 del enunciado)

1. **Panel:** las tres familias, los contadores por condición y la matriz de riesgo. Filtrar por familia o condición.
2. **Equipo y esquema:** abrir L-1001 → «Esquema y CML» → ubicación técnica y marcadores coloreados por condición.
3. **Agregar una medición:** en L-1001-CML-04 (que hoy tiene datos insuficientes), agregar 6,70 mm al 2026-11-20. Se recalculan CR, RL, condición y próxima fecha, y se actualiza el gráfico.
4. **Variable de diseño:** en V-2001 → Antecedentes, cambiar la presión de diseño de 1,5 a 1,8 MPa. t_req pasa de 9,70 a 11,66 mm y CML-03 cambia de inspección vencida a bajo mínimo.
5. **Consecuencia:** en L-1001 → RBI, cambiar C_A de 150 a 12 000 m². El riesgo pasa de Bajo a Medio-alto y R_A se multiplica por 80, mientras f_F no cambia.
6. **Guardar y recuperar:** Guardar → recargar la página (se recupera) → Exportar `.json` → Restablecer demo → Importar. Cerrar con la pestaña «Verificación» (33/33).

## Caso demostrativo (datos ficticios, evaluado al 2026-11-23)

| CML | Condición | Qué demuestra |
|---|---|---|
| L-1001-CML-01 | NORMAL | corrosión baja y uniforme (0.03 mm/año) |
| L-1001-CML-02 | **ALERTA** | erosión aguas abajo de FV-1001; RL = 1.08 años ≤ Δt_margen |
| L-1001-CML-03 | NORMAL | reemplazo de carrete en 2022, con la línea base reiniciada |
| L-1001-CML-04 | NORMAL | punto nuevo con 1 sola medición (**DATOS_INSUFICIENTES**) |
| V-2001-CML-01 | NORMAL | corrosión general baja |
| V-2001-CML-02 | **BAJO_MINIMO** | interfase agua: 9.55 mm < t_min 9.70 mm |
| V-2001-CML-03 | **INSPECCION_VENCIDA** | bajo aislación, sin medición desde 2022 (venció el 2024-08-08) |
| V-2001-CML-04 | NORMAL | dispersión de medición (CR_LT < 0) |
| T-3001-CML-01 | NORMAL | campaña de 2016 registrada en pulgadas |
| T-3001-CML-02 | **ALERTA** | corrosión por agua decantada; RL = 1.50 años |
| T-3001-CML-03 | NORMAL | fecha mal digitada (2062) (**FECHAS_INCONSISTENTES**) |
| T-3001-CML-04 | NORMAL | sin pérdida medible (**CORROSION_NULA_O_NEGATIVA**) |

RBI: L-1001 queda en riesgo BAJO (P4); V-2001 en ALTO (P1, con la consecuencia económica en CLP); T-3001 en ALTO (P1).
Para la demostración en vivo, `tests/test_demo.py` ensaya los pasos 3 a 6 del §8 del enunciado.

## Unidades (SI coherente)

MPa · mm (espesor, D de tubería, R de recipiente) · m (D y H de tanque, forma SI de API 650/653) · años (365.25 d) · mm/año · °C · m² · moneda declarada.

Cada función devuelve `{entradas, ecuacion_texto, referencia_normativa, resultado, unidad, observaciones, alertas[, detalle]}`.

## Alcance y ediciones declaradas

| Familia | Diseño | En servicio | Geometría |
|---|---|---|---|
| Tuberías | ASME B31.3-2022 §304.1.2 Ec. (3a) | API 570 4.ª ed. §6.3, §7.1, Tabla 1 | Tramo recto |
| Recipientes | ASME VIII-1 2023 UG-27(c)(1), UG-16; II-D Tabla 1A | API 510 11.ª ed. §6.4, §6.5.1.1, §7.1 | Envolvente cilíndrica |
| Tanques | API 650 13.ª ed. §5.6.1.1, §5.6.3.2, Tabla 5-2a | API 653 5.ª ed. §4.3.3.1, Tabla 4.1, §6.3 | Virolas del manto |
| RBI | API RP 580 3.ª ed. (proceso) | API RP 581 3.ª ed. Parte 1 y Parte 2 §4 | Adelgazamiento generalizado |

Catálogo de materiales (acotado): A106 Gr. B (−29 a 343 °C), SA-516-70 y SA-240-304L (−29 a 371 °C), y A36M / A516M-485 para tanques (≤ 93 °C).
**Los valores de esfuerzo son referenciales y se transcribieron para uso académico: hay que verificarlos contra la tabla de la edición declarada.**

## Criterios del grupo (no normativos, configurables)

- **Espesor de alerta:** `t_alerta = t_min + CR_gov·Δt_margen`, con Δt_margen = 2 años como plazo de intervención. Equivale a declarar ALERTA cuando RL ≤ Δt_margen.
- **CR_gov = max(CR_LT, CR_ST):** se adopta el criterio conservador.
- **API 510 con RL < 4 años:** por defecto `min(RL/4, 2 años)`, que es la regla solicitada y es más restrictiva que el texto de API 510 §6.5.1.1. El texto normativo permite `min(RL, 2 años)`, disponible con `regla_rl_menor_4="API_TEXTUAL"`.
- **CR desconocida (< 2 mediciones) en API 510/570:** se usan 2 años para establecer la tasa. En API 653 (manto) se usan 5 años, que es el valor normativo.
- **Matriz de riesgo 5×5:** tiene la forma de API RP 581 Parte 1; la asignación de niveles es del grupo.

## RBI: modelo académico simplificado

`A_rt = CR·edad/t_ref` → `D_f` por confiabilidad estructural con actualización bayesiana (API 581 3.ª ed., estados de daño 1/2/4, COV 0.20/0.20/0.05, normalización 1.56E−4, mínimo 0.1) → `f_F = gff·D_f·F_MS` → `R_A = f_F·C_A` [m²/año] y `R_E = f_F·C_E` [moneda/año].
**La inspección reduce la incertidumbre sobre D_f, pero no recupera el espesor perdido (A_rt no cambia).**

Simplificaciones: un solo mecanismo de daño, factores de ajuste agrupados en uno solo y consecuencias ingresadas por el usuario.

> Prototipo académico. No reemplaza a un inspector autorizado ni una evaluación de ingeniería.
