"""
Análisis bromatológico espectral para gramíneas tropicales colombianas.

Convierte un índice espectral de imagen de dron (NGRDI u otro) en un perfil
nutricional completo: proteína, energía, fibra y 11 minerales.

Arquitectura de dos capas:
  - Proteína: regresión directa  ngrdi → proteína
              Proteína = A_CALIBRACION × NGRDI + B_CALIBRACION
  - FDA/FDN/Energía: modelo espectral con indice_vigor clipped a [34, 41]
                     para evitar extrapolaciones fuera del dominio del modelo.

Calibración (4 lotes de campo, R²=0.988):
  Proteína = 16.866 × NGRDI + 12.026
  Válida para NGRDI ∈ [-0.5, 0.65], Proteína ∈ [4%, 24%]

Nota: los parámetros A/B se reutilizan también para calcular vigor_raw, cuyo
valor sirve únicamente como entrada al modelo espectral de fibra/energía
(clipped internamente). El valor de proteína siempre viene de la regresión
directa, no del modelo espectral.

Minerales: interpolación lineal desde la tabla de calibración de campo
           (Datos_Proteínas_y_Minerales.xlsx, 38 puntos, rango Proteína 3–22.75%).
           Clip aplicado en [6.5, 22.75] — fuera de este rango los minerales
           se congelan en el valor del extremo más cercano de la tabla.

# fórmulas derivadas de modelo propietario de análisis espectral de pastos
"""

from __future__ import annotations

import bisect
import math
from typing import Dict, Tuple

# ---------------------------------------------------------------------------
# Parámetros de calibración lineal
# ---------------------------------------------------------------------------

A_CALIBRACION: float = 16.866  # pendiente calibrada con 4 lotes de campo
B_CALIBRACION: float = 12.026  # intercepto calibrado con 4 lotes de campo
# Calibración: Proteína = A × NGRDI + B  (R²=0.988, n=4, rango NGRDI [-0.5, 0.65])

# Parámetros del modelo espectral de fibra/energía (2ARGB).
# Estos mapean NGRDI → indice_vigor en el dominio [34, 41] del modelo.
# Son distintos de A/B_CALIBRACION y no deben modificarse.
_A_VIGOR: float = 13.33
_B_VIGOR: float = 35.33

INDICE_VIGOR_RANGO_VALIDO: Tuple[float, float] = (34.0, 41.0)

# ---------------------------------------------------------------------------
# Constantes internas del modelo bromatológico
# # fórmulas derivadas de modelo propietario de análisis espectral de pastos
# ---------------------------------------------------------------------------

_L = 41.035
_E = 0.2733
_D = 3.3
_S1 = 0.3082
_S2 = 26.866
_S3 = 3.720
_K0 = 7.0
_C5 = 5.8995750
_C6 = 4.7740220

# ---------------------------------------------------------------------------
# Tabla de calibración mineral (interpolación lineal)
# Fuente: Datos_Proteínas_y_Minerales.xlsx — 38 filas, paso ≈0.5% Proteína
# Clip: [PROT_MIN_CLIP, PROT_MAX_CLIP]
# ---------------------------------------------------------------------------

PROT_MIN_CLIP: float = 6.5  # primer punto con datos completos de todos los minerales
PROT_MAX_CLIP: float = 22.75  # máximo de la tabla

# Estructura: {proteina_pct: {mineral_key: valor}}
_TABLA: Dict[float, Dict[str, float]] = {
    6.5: {
        "N": 1.04,
        "K": 1.26,
        "P": 0.21,
        "Mg": 0.20,
        "Ca": 0.45,
        "Cu": 3.45,
        "Fe": 134.0,
        "Zn": 32.0,
        "Mn": 177.0,
        "B": 3.33,
        "S": 0.11,
    },
    7.0: {
        "N": 1.12,
        "K": 1.32,
        "P": 0.22,
        "Mg": 0.20,
        "Ca": 0.44,
        "Cu": 3.51,
        "Fe": 128.0,
        "Zn": 31.0,
        "Mn": 165.0,
        "B": 3.31,
        "S": 0.12,
    },
    7.5: {
        "N": 1.20,
        "K": 1.39,
        "P": 0.22,
        "Mg": 0.20,
        "Ca": 0.43,
        "Cu": 3.56,
        "Fe": 122.0,
        "Zn": 31.0,
        "Mn": 153.0,
        "B": 3.28,
        "S": 0.12,
    },
    8.0: {
        "N": 1.28,
        "K": 1.46,
        "P": 0.23,
        "Mg": 0.20,
        "Ca": 0.42,
        "Cu": 3.62,
        "Fe": 116.0,
        "Zn": 30.0,
        "Mn": 143.0,
        "B": 3.26,
        "S": 0.12,
    },
    8.5: {
        "N": 1.36,
        "K": 1.53,
        "P": 0.23,
        "Mg": 0.20,
        "Ca": 0.41,
        "Cu": 3.69,
        "Fe": 112.0,
        "Zn": 30.0,
        "Mn": 133.0,
        "B": 3.23,
        "S": 0.13,
    },
    9.0: {
        "N": 1.44,
        "K": 1.61,
        "P": 0.24,
        "Mg": 0.20,
        "Ca": 0.40,
        "Cu": 3.76,
        "Fe": 108.0,
        "Zn": 29.0,
        "Mn": 123.0,
        "B": 3.20,
        "S": 0.13,
    },
    9.5: {
        "N": 1.52,
        "K": 1.70,
        "P": 0.24,
        "Mg": 0.20,
        "Ca": 0.40,
        "Cu": 3.84,
        "Fe": 104.0,
        "Zn": 29.0,
        "Mn": 114.0,
        "B": 3.18,
        "S": 0.14,
    },
    10.0: {
        "N": 1.60,
        "K": 1.79,
        "P": 0.25,
        "Mg": 0.20,
        "Ca": 0.39,
        "Cu": 3.92,
        "Fe": 101.0,
        "Zn": 29.0,
        "Mn": 105.0,
        "B": 3.15,
        "S": 0.14,
    },
    10.5: {
        "N": 1.68,
        "K": 1.89,
        "P": 0.26,
        "Mg": 0.20,
        "Ca": 0.38,
        "Cu": 4.01,
        "Fe": 99.0,
        "Zn": 28.0,
        "Mn": 97.0,
        "B": 3.12,
        "S": 0.15,
    },
    11.0: {
        "N": 1.76,
        "K": 1.98,
        "P": 0.26,
        "Mg": 0.20,
        "Ca": 0.38,
        "Cu": 4.11,
        "Fe": 98.0,
        "Zn": 28.0,
        "Mn": 90.0,
        "B": 3.09,
        "S": 0.15,
    },
    11.5: {
        "N": 1.84,
        "K": 2.09,
        "P": 0.27,
        "Mg": 0.20,
        "Ca": 0.37,
        "Cu": 4.20,
        "Fe": 97.0,
        "Zn": 28.0,
        "Mn": 83.0,
        "B": 3.06,
        "S": 0.16,
    },
    12.0: {
        "N": 1.92,
        "K": 2.20,
        "P": 0.28,
        "Mg": 0.20,
        "Ca": 0.36,
        "Cu": 4.31,
        "Fe": 96.0,
        "Zn": 28.0,
        "Mn": 77.0,
        "B": 3.03,
        "S": 0.17,
    },
    12.5: {
        "N": 2.00,
        "K": 2.31,
        "P": 0.28,
        "Mg": 0.20,
        "Ca": 0.36,
        "Cu": 4.42,
        "Fe": 97.0,
        "Zn": 28.0,
        "Mn": 71.0,
        "B": 2.99,
        "S": 0.17,
    },
    13.0: {
        "N": 2.08,
        "K": 2.43,
        "P": 0.29,
        "Mg": 0.20,
        "Ca": 0.35,
        "Cu": 4.53,
        "Fe": 98.0,
        "Zn": 27.0,
        "Mn": 66.0,
        "B": 2.96,
        "S": 0.18,
    },
    13.5: {
        "N": 2.16,
        "K": 2.55,
        "P": 0.30,
        "Mg": 0.20,
        "Ca": 0.35,
        "Cu": 4.65,
        "Fe": 99.0,
        "Zn": 27.0,
        "Mn": 61.0,
        "B": 2.92,
        "S": 0.19,
    },
    14.0: {
        "N": 2.24,
        "K": 2.68,
        "P": 0.31,
        "Mg": 0.20,
        "Ca": 0.34,
        "Cu": 4.77,
        "Fe": 101.0,
        "Zn": 27.0,
        "Mn": 57.0,
        "B": 2.89,
        "S": 0.20,
    },
    14.5: {
        "N": 2.32,
        "K": 2.81,
        "P": 0.32,
        "Mg": 0.20,
        "Ca": 0.34,
        "Cu": 4.90,
        "Fe": 104.0,
        "Zn": 27.0,
        "Mn": 53.0,
        "B": 2.85,
        "S": 0.21,
    },
    15.0: {
        "N": 2.40,
        "K": 2.95,
        "P": 0.32,
        "Mg": 0.20,
        "Ca": 0.34,
        "Cu": 5.04,
        "Fe": 108.0,
        "Zn": 27.0,
        "Mn": 50.0,
        "B": 2.82,
        "S": 0.22,
    },
    15.5: {
        "N": 2.48,
        "K": 3.09,
        "P": 0.33,
        "Mg": 0.20,
        "Ca": 0.33,
        "Cu": 5.18,
        "Fe": 112.0,
        "Zn": 27.0,
        "Mn": 48.0,
        "B": 2.78,
        "S": 0.23,
    },
    16.0: {
        "N": 2.56,
        "K": 3.24,
        "P": 0.34,
        "Mg": 0.20,
        "Ca": 0.33,
        "Cu": 5.32,
        "Fe": 116.0,
        "Zn": 27.0,
        "Mn": 46.0,
        "B": 2.74,
        "S": 0.24,
    },
    16.5: {
        "N": 2.64,
        "K": 3.39,
        "P": 0.35,
        "Mg": 0.20,
        "Ca": 0.33,
        "Cu": 5.47,
        "Fe": 121.0,
        "Zn": 28.0,
        "Mn": 44.0,
        "B": 2.70,
        "S": 0.25,
    },
    17.0: {
        "N": 2.72,
        "K": 3.54,
        "P": 0.36,
        "Mg": 0.20,
        "Ca": 0.32,
        "Cu": 5.63,
        "Fe": 127.0,
        "Zn": 28.0,
        "Mn": 43.0,
        "B": 2.66,
        "S": 0.26,
    },
    17.5: {
        "N": 2.80,
        "K": 3.70,
        "P": 0.37,
        "Mg": 0.20,
        "Ca": 0.32,
        "Cu": 5.79,
        "Fe": 134.0,
        "Zn": 28.0,
        "Mn": 43.0,
        "B": 2.62,
        "S": 0.27,
    },
    18.0: {
        "N": 2.88,
        "K": 3.87,
        "P": 0.38,
        "Mg": 0.20,
        "Ca": 0.32,
        "Cu": 5.95,
        "Fe": 141.0,
        "Zn": 28.0,
        "Mn": 43.0,
        "B": 2.58,
        "S": 0.29,
    },
    18.5: {
        "N": 2.96,
        "K": 4.04,
        "P": 0.39,
        "Mg": 0.20,
        "Ca": 0.32,
        "Cu": 6.12,
        "Fe": 149.0,
        "Zn": 28.0,
        "Mn": 44.0,
        "B": 2.54,
        "S": 0.30,
    },
    19.0: {
        "N": 3.04,
        "K": 4.21,
        "P": 0.40,
        "Mg": 0.20,
        "Ca": 0.32,
        "Cu": 6.30,
        "Fe": 157.0,
        "Zn": 29.0,
        "Mn": 46.0,
        "B": 2.50,
        "S": 0.31,
    },
    19.5: {
        "N": 3.12,
        "K": 4.39,
        "P": 0.41,
        "Mg": 0.20,
        "Ca": 0.32,
        "Cu": 6.48,
        "Fe": 166.0,
        "Zn": 29.0,
        "Mn": 48.0,
        "B": 2.45,
        "S": 0.33,
    },
    20.0: {
        "N": 3.20,
        "K": 4.58,
        "P": 0.42,
        "Mg": 0.10,
        "Ca": 0.32,
        "Cu": 6.67,
        "Fe": 175.0,
        "Zn": 30.0,
        "Mn": 50.0,
        "B": 2.41,
        "S": 0.34,
    },
    21.5: {
        "N": 3.44,
        "K": 5.15,
        "P": 0.46,
        "Mg": 0.10,
        "Ca": 0.32,
        "Cu": 7.26,
        "Fe": 208.0,
        "Zn": 31.0,
        "Mn": 61.0,
        "B": 2.27,
        "S": 0.39,
    },
    22.0: {
        "N": 3.52,
        "K": 5.36,
        "P": 0.47,
        "Mg": 0.10,
        "Ca": 0.32,
        "Cu": 7.46,
        "Fe": 220.0,
        "Zn": 31.0,
        "Mn": 65.0,
        "B": 2.23,
        "S": 0.40,
    },
    22.75: {
        "N": 3.64,
        "K": 5.49,
        "P": 0.48,
        "Mg": 0.09,
        "Ca": 0.32,
        "Cu": 7.59,
        "Fe": 224.0,
        "Zn": 32.0,
        "Mn": 63.0,
        "B": 2.19,
        "S": 0.41,
    },
}

# Índices precalculados para búsqueda binaria O(log n)
_PROT_KEYS: list[float] = sorted(_TABLA.keys())
_MINERAL_KEYS = ("N", "K", "P", "Mg", "Ca", "Cu", "Fe", "Zn", "Mn", "B", "S")

# Mapeo a claves de salida con unidades
_MINERAL_OUTPUT_KEY = {
    "N": "N_pct",
    "K": "K_pct",
    "P": "P_pct",
    "Mg": "Mg_pct",
    "Ca": "Ca_pct",
    "S": "S_pct",
    "Cu": "Cu_ppm",
    "Fe": "Fe_ppm",
    "Zn": "Zn_ppm",
    "Mn": "Mn_ppm",
    "B": "B_ppm",
}

# Minerales con baja correlación espectral — informar confianza reducida
_MINERALES_BAJA_CONFIANZA = frozenset({"Mg", "Ca", "Fe", "Zn", "Mn"})


# ---------------------------------------------------------------------------
# Interpolación lineal de la tabla
# ---------------------------------------------------------------------------


def _interpolar_mineral(proteina: float, mineral: str) -> float:
    """Interpola linealmente el valor de un mineral desde _TABLA.
    Aplica clip en [PROT_MIN_CLIP, PROT_MAX_CLIP].
    """
    p = max(PROT_MIN_CLIP, min(PROT_MAX_CLIP, proteina))
    keys = _PROT_KEYS

    # Búsqueda del intervalo
    idx = bisect.bisect_left(keys, p)

    if idx == 0:
        return _TABLA[keys[0]][mineral]
    if idx >= len(keys):
        return _TABLA[keys[-1]][mineral]
    if keys[idx] == p:
        return _TABLA[p][mineral]

    p0, p1 = keys[idx - 1], keys[idx]
    v0 = _TABLA[p0].get(mineral)
    v1 = _TABLA[p1].get(mineral)
    if v0 is None or v1 is None:
        # Buscar intervalo con datos completos hacia afuera
        return _TABLA[p1].get(mineral, _TABLA[p0].get(mineral, 0.0))

    t = (p - p0) / (p1 - p0)
    return v0 + t * (v1 - v0)


# ---------------------------------------------------------------------------
# Núcleo del modelo bromatológico
# # fórmulas derivadas de modelo propietario de análisis espectral de pastos
# ---------------------------------------------------------------------------


# 2ARGB-V3-cal: LEGACY — modelo espectral 2ARGB con regresiones internas sobre
# vigor clipped. Sus salidas (fda_pct, fdn_pct, energia_mcal, energia_mj) ya NO
# se usan en perfil_desde_ngrdi: son reemplazadas por las funciones calibradas
# _fdn_desde_pc / _fda_desde_pc / _energia_desde_pc abajo. Se conserva como
# referencia histórica (firma y resultados documentados en tests previos).
def _calcular_perfil(vigor: float) -> Dict:
    """Cadena de regresiones espectrales → outputs nutricionales."""
    alpha = (_L - vigor) / _E
    x0 = round(vigor - _D, 3)
    I1 = alpha * _S1 + _S2 + _S3
    I2 = -0.0742 * x0**2 + 0.8917 * x0 + 32.505

    proteina = 0.1724613 * x0 - 0.1255499 * I2 + 5.047594
    energia_mcal = (
        -2.129859 * x0 - 1.891161 * I1 - 0.0068728 * I2 + 0.0404106 * proteina + 138.611
    )
    I5 = (
        5.222629 * x0
        + 4.614769 * I1
        + 0.0076719 * I2
        + 0.4273812 * proteina
        + 0.0006189 * energia_mcal
        - 337.7922
    )
    I6 = (
        163.2403 * x0
        + 156.2262 * I1
        + 10.64045 * I2
        + 79.23085 * proteina
        + 18.15547 * energia_mcal
        + 0.0415153 * I5
        - 11858.52
    )
    B = (
        26.16059 * x0
        + 23.40839 * I1
        + 0.2921685 * I2
        + 1.977762 * proteina
        + 1.942678 * energia_mcal
        + 0.0043322 * I5
        - 5.185382 * I6
        - 1723.328
        - 0.02
    )

    fda_pct = _C5 * I5 - _K0
    fdn_pct = _C5 * I5 - _C6 * I6
    energia_mj = (
        energia_mcal * 4.184
    )  # 1 Mcal = 4.184 MJ (factor de conversión estándar)

    return {
        "proteina_pct": round(proteina, 4),
        "energia_mcal": round(energia_mcal, 4),
        "fda_pct": round(fda_pct, 4),
        "fdn_pct": round(fdn_pct, 4),
        "energia_mj": round(energia_mj, 4),
    }


# ---------------------------------------------------------------------------
# 2ARGB-V3-cal: Derivaciones calibradas desde Proteína%
# Coeficientes calibrados con 21 muestras; fuente: hoja ENERGÍA del Excel
# de calibración. Se aplican post-cálculo de proteína en perfil_desde_ngrdi.
# Rango válido de calibración: PC ∈ [PC_MIN, PC_MAX].
# ---------------------------------------------------------------------------


class _CoefsCalibrados:
    """Coeficientes calibrados para derivar FDN/FDA/Energía/AFORO desde PC%."""

    # Energía Metabolizable (EM) en Mcal/kg MS  —  lineal, R² ≈ 1.000
    EM_A0: float = 3.044402
    EM_A1: float = 0.124211

    # Energía Neta de Lactación (ENL) en Mcal/kg MS  —  lineal, R² ≈ 1.000
    E2_A0: float = 0.727269
    E2_A1: float = 0.029688

    # FDN (%)  —  lineal, R² ≈ 1.000
    FDN_A0: float = 73.142087
    FDN_A1: float = -1.127595

    # FDA (%)  —  cuadrática (cae rápido con PC alto), RMSE ≈ 0.004%
    FDA_A2: float = -0.078074
    FDA_A1: float = 0.981619
    FDA_A0: float = 32.502456

    # AFORO estimado (UA/ha)  —  cuadrática; es estimación ESPECTRAL,
    # no el AFORO real de campo/SQL. RMSE ≈ 0.163 UA/ha.
    AFORO_A2: float = -0.003553
    AFORO_A1: float = 0.215793
    AFORO_A0: float = -1.201203

    # Rango válido de la calibración (PC%)
    PC_MIN: float = 3.81
    PC_MAX: float = 24.02


def _energia_desde_pc(pc: float) -> float:
    """2ARGB-V3-cal: Energía Metabolizable (Mcal/kg MS) desde Proteína%."""
    k = _CoefsCalibrados
    return k.EM_A0 + k.EM_A1 * pc


def _energia2_desde_pc(pc: float) -> float:
    """2ARGB-V3-cal: Energía Neta de Lactación (Mcal/kg MS) desde Proteína%."""
    k = _CoefsCalibrados
    return k.E2_A0 + k.E2_A1 * pc


def _fdn_desde_pc(pc: float) -> float:
    """2ARGB-V3-cal: Fibra Detergente Neutra (%) desde Proteína%."""
    k = _CoefsCalibrados
    return k.FDN_A0 + k.FDN_A1 * pc


def _fda_desde_pc(pc: float) -> float:
    """2ARGB-V3-cal: Fibra Detergente Ácida (%) desde Proteína% — cuadrática."""
    k = _CoefsCalibrados
    return k.FDA_A2 * pc**2 + k.FDA_A1 * pc + k.FDA_A0


def _aforo_estimado_desde_pc(pc: float) -> float:
    """2ARGB-V3-cal: AFORO estimado (UA/ha) desde Proteína%.

    ⚠ Es una estimación ESPECTRAL — el AFORO real de campo debe venir de
    la fuente SQL correspondiente (ISAFORO en sistemas externos). Aquí
    se usa como fallback cuando no hay valor de aforo disponible.
    """
    k = _CoefsCalibrados
    return k.AFORO_A2 * pc**2 + k.AFORO_A1 * pc + k.AFORO_A0


# ---------------------------------------------------------------------------
# API pública
# ---------------------------------------------------------------------------


def minerales_desde_proteina(proteina_pct: float) -> Dict[str, float]:
    """
    Estima el perfil mineral interpolando desde la tabla de calibración.

    Clip aplicado en [PROT_MIN_CLIP=6.5, PROT_MAX_CLIP=22.75].
    Minerales con confianza reducida (R²<0.90): Mg, Ca, Fe, Zn, Mn.

    Retorna claves con sufijo de unidad: N_pct, K_pct, P_pct, S_pct,
    Mg_pct, Ca_pct, Cu_ppm, Fe_ppm, Zn_ppm, Mn_ppm, B_ppm.
    """
    return {
        _MINERAL_OUTPUT_KEY[m]: round(_interpolar_mineral(proteina_pct, m), 4)
        for m in _MINERAL_KEYS
    }


def aforo_desde_proteina(proteina_pct: float) -> float:
    """AFORO estimado (UA/ha) desde Proteína% — estimación espectral.

    Aplica el mismo clip [PROT_MIN_CLIP, PROT_MAX_CLIP] que el resto de
    derivaciones para mantener la cuadrática dentro del rango calibrado.
    """
    pc = max(PROT_MIN_CLIP, min(PROT_MAX_CLIP, proteina_pct))
    return round(_aforo_estimado_desde_pc(pc), 4)


def perfil_desde_ngrdi(
    ngrdi: float,
    a: float = A_CALIBRACION,
    b: float = B_CALIBRACION,
) -> Dict:
    """
    Pipeline principal: NGRDI de región → perfil bromatológico completo.

    Arquitectura de dos capas:
      - Proteína: regresión directa ``proteina = a * ngrdi + b`` (más precisa,
        calibrada con datos de campo, R²=0.988).
      - FDA/FDN/Energía: modelo espectral con ``vigor_raw`` clipped a
        ``INDICE_VIGOR_RANGO_VALIDO`` para evitar extrapolaciones físicamente
        imposibles en lotes extremos (NGRDI fuera de [-0.1, 0.55] aprox.).

    Args:
        ngrdi: valor medio de NGRDI sobre la región de análisis (rango [-1, 1]).
        a: pendiente de la calibración lineal ngrdi → proteína/vigor.
           Por defecto ``A_CALIBRACION`` (16.866).
        b: intercepto de la calibración lineal ngrdi → proteína/vigor.
           Por defecto ``B_CALIBRACION`` (12.026).

    Returns:
        Dict con las claves:
            indice_vigor (float): valor raw de ``a * ngrdi + b``.
            en_rango_valido (bool): True si indice_vigor ∈ [34, 41].
            proteina_pct (float): Proteína% por regresión directa.
            energia_mcal (float): Energía Mcal/kg del modelo espectral (vigor clipped).
            fda_pct (float): FDA% del modelo espectral (vigor clipped).
            fdn_pct (float): FDN% del modelo espectral (vigor clipped).
            energia_mj (float): Energía MJ/kg del modelo espectral (vigor clipped).
            minerales (dict): 11 minerales interpolados de la tabla de campo.
            minerales_confianza (str): ``"alta"`` si en_rango_valido, ``"extrapolacion"``
                si vigor_raw cae fuera del dominio del modelo.
    """
    # Proteína: regresión directa calibrada con datos de campo
    proteina_real: float = a * ngrdi + b

    # Vigor espectral: parámetros del modelo 2ARGB (dominio [34, 41])
    # Usa _A_VIGOR / _B_VIGOR — independientes de la calibración de proteína.
    vigor_raw: float = _A_VIGOR * ngrdi + _B_VIGOR
    en_rango: bool = (
        INDICE_VIGOR_RANGO_VALIDO[0] <= vigor_raw <= INDICE_VIGOR_RANGO_VALIDO[1]
    )

    # FDA/FDN/Energía: vigor clipped al dominio del modelo para evitar extrapolaciones
    vigor_fibra: float = max(
        INDICE_VIGOR_RANGO_VALIDO[0], min(INDICE_VIGOR_RANGO_VALIDO[1], vigor_raw)
    )
    perfil = _calcular_perfil(vigor_fibra)

    # Sobreescribir proteína con el valor de la regresión directa (más preciso que el modelo)
    perfil["proteina_pct"] = round(proteina_real, 4)

    # 2ARGB-V3-cal: Sobrescribir FDN/FDA/Energía con valores calibrados desde PC.
    # La salida de _calcular_perfil(vigor_fibra) se IGNORA para estas 4 claves;
    # se mantiene la llamada arriba únicamente por simetría histórica.
    pc = proteina_real
    perfil["fdn_pct"] = round(_fdn_desde_pc(pc), 4)
    perfil["fda_pct"] = round(_fda_desde_pc(pc), 4)
    perfil["energia_mcal"] = round(_energia_desde_pc(pc), 4)
    perfil["energia_mj"] = round(_energia_desde_pc(pc) * 4.184, 4)
    # 2ARGB-V3-cal: Nuevas claves — Energía Neta de Lactación y AFORO estimado.
    perfil["energia2_mcal"] = round(_energia2_desde_pc(pc), 4)
    perfil["aforo_ua_ha"] = round(_aforo_estimado_desde_pc(pc), 4)
    perfil["aforo_fuente"] = "estimacion_espectral"

    # Minerales desde proteína real (no desde la del modelo espectral)
    mineral = minerales_desde_proteina(proteina_real)

    return {
        "indice_vigor": round(vigor_raw, 4),
        "en_rango_valido": en_rango,
        **perfil,
        "minerales": mineral,
        "minerales_confianza": "alta" if en_rango else "extrapolacion",
    }


def perfil_desde_vi(
    vi: float,
    a: float = A_CALIBRACION,
    b: float = B_CALIBRACION,
) -> Dict:
    """Igual que perfil_desde_ngrdi pero acepta el pseudo-NDVI combinado (vi)."""
    return perfil_desde_ngrdi(vi, a=a, b=b)
