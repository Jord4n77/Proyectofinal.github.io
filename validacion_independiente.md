# Validación independiente — caso demostrativo

Fecha de evaluación: 2026-11-23 · Tolerancia relativa: 1e-06

El **esperado** se recalcula en `tools/validacion_independiente.py` con las ecuaciones escritas de nuevo, sin importar el motor. El **programa** es la salida de `servicios.evaluar_proyecto` sobre `data/proyecto_demo.json`.

## Cálculos por familia y RBI

| Caso | Magnitud | Entradas | Referencia | Esperado | Programa | Dif. rel. | ✓ |
|---|---|---|---|---|---|---|---|
| Tubería L-1001 / CML-02 | t requerido por presión [mm] | P=5 MPa, D=168.3 mm, S=138 MPa, E=W=1, Y=0.4 | ASME B31.3 §304.1.2 Ec. (3a) | 3.00536 | 3.00536 | 0.0e+00 | ✅ |
| Tubería L-1001 / CML-02 | CR_gov (= CR_ST) [mm/año] | 5.10 → 3.45 mm; 2022-06-14 → 2026-06-16 | API 570 §7.1.1 | 0.41194 | 0.41194 | 0.0e+00 | ✅ |
| Tubería L-1001 / CML-02 | Vida remanente [años] | (3.45 − t_min)/CR_gov | API 570 §7.2.1 | 1.07940 | 1.07940 | 0.0e+00 | ✅ |
| Tubería L-1001 / CML-02 | t_alerta [mm] | t_min + CR_gov·2 años | Criterio del grupo | 3.82923 | 3.82923 | 0.0e+00 | ✅ |
| Tubería L-1001 / CML-02 | Intervalo de espesores [años] | min(RL/2, 10) — Clase 2 | API 570 §6.3.3, Tabla 1 | 0.53970 | 0.53970 | 0.0e+00 | ✅ |
| Recipiente V-2001 / CML-03 | t requerido UG-27(c)(1) [mm] | P=1.5 MPa, R=750+3 mm, S=138 MPa (200 °C), E=0.85 | ASME VIII-1 UG-27(c)(1); II-D Tabla 1A | 9.70361 | 9.70361 | 0.0e+00 | ✅ |
| Recipiente V-2001 / CML-03 | CR_LT [mm/año] | 13.60 → 11.10 mm; 2014-05-20 → 2022-06-14 | API 510 §7.1.1 | 0.30985 | 0.30985 | 0.0e+00 | ✅ |
| Recipiente V-2001 / CML-03 | CR_ST [mm/año] | 12.40 → 11.10 mm; 2018-06-12 → 2022-06-14 | API 510 §7.1.1 | 0.32456 | 0.32456 | 0.0e+00 | ✅ |
| Recipiente V-2001 / CML-03 | Vida remanente [años] | (11.10 − t_req)/max(CR_LT, CR_ST) | API 510 §7.2.1 | 4.30247 | 4.30247 | 0.0e+00 | ✅ |
| Recipiente V-2001 / CML-03 | Intervalo interno/en servicio [años] | RL ≥ 4 → min(RL/2, 10) | API 510 §6.5.1.1 | 2.15124 | 2.15124 | 0.0e+00 | ✅ |
| Tanque T-3001 / Virola 1 / CML-02 | t_d (diseño, 1 pie) [mm] | D=30 m, H=12 m, G=0.85, Sd=160 MPa, CA=1.5 mm | API 650 §5.6.3.2 | 10.63697 | 10.63697 | 0.0e+00 | ✅ |
| Tanque T-3001 / Virola 1 / CML-02 | t_t (prueba hidrostática) [mm] | D=30 m, H=12 m, St=171 MPa | API 650 §5.6.3.2 | 10.05789 | 10.05789 | 0.0e+00 | ✅ |
| Tanque T-3001 / Virola 1 / CML-02 | t_min en servicio [mm] | S=min(0.80·250, 0.429·400)=171.6 MPa, E=1 | API 653 §4.3.3.1, Tabla 4.1 | 8.51932 | 8.51932 | 0.0e+00 | ✅ |
| Tanque T-3001 / Virola 1 / CML-02 | CR_gov (= CR_ST) [mm/año] | 10.60 → 9.00 mm; 2021-09-14 → 2026-09-15 | API 653 §4.3 | 0.31987 | 0.31987 | 0.0e+00 | ✅ |
| Tanque T-3001 / Virola 1 / CML-02 | Intervalo UT del manto [años] | min(RCA/2N, 15) | API 653 §6.3.3.2 | 0.75137 | 0.75137 | 0.0e+00 | ✅ |
| RBI V-2001 (adelgazamiento) | A_rt [—] | CR=0.4619 mm/año, edad=18.730 años, t_ref=16 mm | API RP 581 Parte 2 §4 (simplificado) | 0.54066 | 0.54066 | 0.0e+00 | ✅ |
| RBI V-2001 (adelgazamiento) | SR_P [—] | S=138, E=0.85, YS=260, TS=485 MPa, t_min/t_ref | API RP 581 Parte 2 §4 | 0.20426 | 0.20426 | 0.0e+00 | ✅ |
| RBI V-2001 (adelgazamiento) | D_f (factor de daño) [—] | 1 insp. B + 3 C, confianza ALTA | API RP 581 Parte 2 §4 | 301.01154 | 301.01154 | 0.0e+00 | ✅ |
| RBI V-2001 (adelgazamiento) | f_F = gff·D_f·F_MS [1/año] | gff=3.06E−5, F_MS=10^(−0.02·60+1) | API RP 581 Parte 2 §2 | 5.8117e-03 | 5.8117e-03 | 0.0e+00 | ✅ |
| RBI V-2001 (adelgazamiento) | R_A = f_F·C_A [m²/año] | C_A = 450 m² | Enunciado §5 | 2.61527 | 2.61527 | 0.0e+00 | ✅ |
| RBI V-2001 (adelgazamiento) | R_E = f_F·C_E [CLP/año] | C_E = 1.2E9 CLP | Enunciado §5 | 6.9741e+06 | 6.9741e+06 | 0.0e+00 | ✅ |

## Condición de los 12 CML

| CML | Estado esperado | Alerta esperada | Estado programa | Alertas programa | ✓ |
|---|---|---|---|---|---|
| L-1001-CML-01 | NORMAL | — | NORMAL | — | ✅ |
| L-1001-CML-02 | ALERTA | — | ALERTA | — | ✅ |
| L-1001-CML-03 | NORMAL | LINEA_BASE_REINICIADA | NORMAL | LINEA_BASE_REINICIADA | ✅ |
| L-1001-CML-04 | NORMAL | DATOS_INSUFICIENTES | NORMAL | DATOS_INSUFICIENTES | ✅ |
| V-2001-CML-01 | NORMAL | — | NORMAL | — | ✅ |
| V-2001-CML-02 | BAJO_MINIMO | BAJO_MINIMO | BAJO_MINIMO | BAJO_MINIMO | ✅ |
| V-2001-CML-03 | INSPECCION_VENCIDA | PROYECCION_BAJO_MINIMO | INSPECCION_VENCIDA | PROYECCION_BAJO_MINIMO | ✅ |
| V-2001-CML-04 | NORMAL | CORROSION_NULA_O_NEGATIVA | NORMAL | CORROSION_NULA_O_NEGATIVA | ✅ |
| T-3001-CML-01 | NORMAL | — | NORMAL | — | ✅ |
| T-3001-CML-02 | ALERTA | — | ALERTA | — | ✅ |
| T-3001-CML-03 | NORMAL | FECHAS_INCONSISTENTES | NORMAL | FECHAS_INCONSISTENTES | ✅ |
| T-3001-CML-04 | NORMAL | CORROSION_NULA_O_NEGATIVA | NORMAL | CORROSION_NULA_O_NEGATIVA | ✅ |
