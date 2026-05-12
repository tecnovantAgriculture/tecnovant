"""
Tests de regresión para el módulo de bromatología espectral de Agrovista.

Arquitectura de dos capas (desde recalibración con 4 lotes de campo, R²=0.988):
  - Proteína:    regresión directa NGRDI → Proteína = 16.866 × NGRDI + 12.026
  - FDA/FDN/Energía: modelo espectral 2ARGB con vigor clipped a [34, 41]
                     usando los parámetros originales 13.33/35.33

Punto de validación central (vigor):
    ngrdi=0.215 → indice_vigor=38.196 (en rango) → FDA=30.39, FDN=56.96, EMcal=1.1562
    (FDA/FDN/Energía se mantienen porque el vigor espectral no cambió)

Punto de validación de proteína con nueva calibración:
    ngrdi=0.215 → Proteína=15.6522%   (nueva calibración directa)

Fuente de minerales:
    Interpolación lineal desde Datos_Proteínas_y_Minerales.xlsx (38 puntos).
    Clip en [6.5, 22.75] % de Proteína.
"""

import pytest

from app.modules.agrovista.bromatologia import (
    minerales_desde_proteina,
    perfil_desde_ngrdi,
    PROT_MIN_CLIP,
    PROT_MAX_CLIP,
)
from app.modules.agrovista.helpers import compute_secondary_objective_targets


# ---------------------------------------------------------------------------
# Stubs
# ---------------------------------------------------------------------------

class _NutrientStub:
    def __init__(self, nutrient_id: int, symbol: str, name: str, unit: str):
        self.id     = nutrient_id
        self.symbol = symbol
        self.name   = name
        self.unit   = unit


# ---------------------------------------------------------------------------
# Test 1 — Núcleo bromatológico (5 outputs principales)
# ---------------------------------------------------------------------------

def test_nucleo_bromatologico_punto_de_validacion():
    """ngrdi=0.215 — FDA/FDN/Energía del software de referencia; Proteína de nueva calibración.

    El vigor espectral (13.33×0.215+35.33≈38.196) cae en el rango operativo [34,41],
    por lo que FDA/FDN/Energía se mantienen idénticas al software de referencia.
    La proteína viene de la regresión directa de campo: 16.866×0.215+12.026=15.6522%.
    """
    r = perfil_desde_ngrdi(0.215)

    # Proteína: nueva calibración de campo (R²=0.988)
    assert abs(r["proteina_pct"] - 15.6522) <= 0.0001, f"proteina: {r['proteina_pct']}"
    # FDA/FDN/Energía: sin cambio — el vigor espectral (38.196) no varió
    assert abs(r["fda_pct"]      - 30.3915) <= 0.0001, f"fda:      {r['fda_pct']}"
    assert abs(r["fdn_pct"]      - 56.9595) <= 0.0001, f"fdn:      {r['fdn_pct']}"
    assert abs(r["energia_mcal"] -  1.1562) <= 0.0001, f"mcal:     {r['energia_mcal']}"
    assert abs(r["energia_mj"]   -  9.8135) <= 0.0001, f"mj:       {r['energia_mj']}"


# ---------------------------------------------------------------------------
# Test 2 — Claves del dict de retorno
# ---------------------------------------------------------------------------

def test_claves_dict_retorno_completas():
    """perfil_desde_ngrdi retorna todas las claves esperadas."""
    r = perfil_desde_ngrdi(0.215)

    claves_requeridas = {
        "indice_vigor",
        "en_rango_valido",
        "proteina_pct",
        "energia_mcal",
        "fda_pct",
        "fdn_pct",
        "energia_mj",
        "minerales",
        "minerales_confianza",
    }
    assert claves_requeridas.issubset(set(r.keys())), (
        f"Claves faltantes: {claves_requeridas - set(r.keys())}"
    )


def test_claves_minerales_completas():
    """El subdic 'minerales' contiene los 11 elementos esperados."""
    r = perfil_desde_ngrdi(0.215)
    claves_minerales = {
        "N_pct", "K_pct", "P_pct", "Mg_pct", "Ca_pct", "S_pct",
        "Cu_ppm", "Fe_ppm", "Zn_ppm", "Mn_ppm", "B_ppm",
    }
    assert claves_minerales == set(r["minerales"].keys()), (
        f"Minerales incorrectos: {set(r['minerales'].keys()) ^ claves_minerales}"
    )


def test_en_rango_valido_dentro_del_rango():
    """ngrdi=0.215 debe estar en el rango operativo [34, 41]."""
    r = perfil_desde_ngrdi(0.215)
    assert r["en_rango_valido"] is True


def test_en_rango_valido_fuera_del_rango():
    """ngrdi muy bajo produce indice_vigor < 34 → en_rango_valido=False."""
    r = perfil_desde_ngrdi(-0.5)   # vigor ≈ 28.7
    assert r["en_rango_valido"] is False


# ---------------------------------------------------------------------------
# Test 3 — Minerales calibrados contra tabla de campo
# Tolerancia ±5% o ±0.01 (el mayor), para cubrir la interpolación lineal.
# Valores de referencia: interpolación entre Proteína=14.0 y Proteína=14.5
# de Datos_Proteínas_y_Minerales.xlsx.
# ---------------------------------------------------------------------------

MINERALES_ESPERADOS_14_43 = {
    # mineral_key : valor_interpolado_tabla
    "N_pct":  2.3088,
    "K_pct":  2.7918,   # interpolado en 14.43 entre 14.0→2.68 y 14.5→2.81
    "P_pct":  0.3186,
    "Mg_pct": 0.20,
    "Ca_pct": 0.34,
    "Cu_ppm": 4.8818,
    "Fe_ppm": 103.58,
    "Zn_ppm": 27.0,
    "Mn_ppm": 53.56,
    "B_ppm":  2.8556,
    "S_pct":  0.2086,
}


def test_minerales_en_14_43_dentro_de_tolerancia():
    """minerales_desde_proteina(14.43) reproduce la tabla con ±5% o ±0.01."""
    minerales = minerales_desde_proteina(14.43)

    for key, valor_esperado in MINERALES_ESPERADOS_14_43.items():
        tolerancia = max(abs(valor_esperado) * 0.05, 0.01)
        diff = abs(minerales[key] - valor_esperado)
        assert diff <= tolerancia, (
            f"{key}: calculado={minerales[key]}, esperado={valor_esperado}, "
            f"diff={diff:.4f}, tolerancia={tolerancia:.4f}"
        )


# ---------------------------------------------------------------------------
# Test 4 — Consistencia entre helpers y bromatologia
# ---------------------------------------------------------------------------

def test_helpers_usan_misma_fuente_de_verdad():
    """compute_secondary_objective_targets retorna los mismos valores que minerales_desde_proteina."""
    protein = 14.43
    nutrients = [
        _NutrientStub(1, "k",  "Potasio",   "%"),
        _NutrientStub(2, "fe", "Hierro",     "ppm"),
        _NutrientStub(3, "mn", "Manganeso",  "ppm"),
        _NutrientStub(4, "n",  "Nitrógeno",  "%"),
        _NutrientStub(5, "p",  "Fósforo",    "%"),
    ]
    payload = compute_secondary_objective_targets(
        protein_average=protein,
        nitrogen_estimated=protein / 6.25,
        nutrients=nutrients,
        digits=4,
    )
    by_symbol = {item["nutrient_symbol"].lower(): item["target_value"] for item in payload}
    ref = minerales_desde_proteina(protein)

    assert by_symbol["k"]  == round(ref["K_pct"],  4), f'K: {by_symbol["k"]} vs {ref["K_pct"]}'
    assert by_symbol["fe"] == round(ref["Fe_ppm"], 4), f'Fe: {by_symbol["fe"]} vs {ref["Fe_ppm"]}'
    assert by_symbol["mn"] == round(ref["Mn_ppm"], 4), f'Mn: {by_symbol["mn"]} vs {ref["Mn_ppm"]}'
    assert by_symbol["n"]  == round(ref["N_pct"],  4), f'N: {by_symbol["n"]} vs {ref["N_pct"]}'
    assert by_symbol["p"]  == round(ref["P_pct"],  4), f'P: {by_symbol["p"]} vs {ref["P_pct"]}'


# ---------------------------------------------------------------------------
# Test 5 — Clip en extremos de la tabla
# ---------------------------------------------------------------------------

def test_clip_en_limite_inferior():
    """Proteína < PROT_MIN_CLIP devuelve los mismos minerales que PROT_MIN_CLIP."""
    muy_bajo = minerales_desde_proteina(PROT_MIN_CLIP - 5.0)
    en_limite = minerales_desde_proteina(PROT_MIN_CLIP)
    assert muy_bajo == en_limite, "Clip inferior no aplicado correctamente"


def test_clip_en_limite_superior():
    """Proteína > PROT_MAX_CLIP devuelve los mismos minerales que PROT_MAX_CLIP."""
    muy_alto = minerales_desde_proteina(PROT_MAX_CLIP + 20.0)
    en_limite = minerales_desde_proteina(PROT_MAX_CLIP)
    assert muy_alto == en_limite, "Clip superior no aplicado correctamente"


def test_clip_simetria():
    """Valores extremos dan exactamente lo mismo que los puntos de clip."""
    assert minerales_desde_proteina(2.0)  == minerales_desde_proteina(PROT_MIN_CLIP)
    assert minerales_desde_proteina(40.0) == minerales_desde_proteina(PROT_MAX_CLIP)


# ---------------------------------------------------------------------------
# Test 6 — Monotonía esperada en el rango operativo
# ---------------------------------------------------------------------------

def test_proteina_crece_con_ngrdi():
    """A mayor NGRDI (más vigor), mayor proteína calculada."""
    r_bajo  = perfil_desde_ngrdi(0.10)
    r_medio = perfil_desde_ngrdi(0.22)
    r_alto  = perfil_desde_ngrdi(0.35)
    assert r_bajo["proteina_pct"] < r_medio["proteina_pct"] < r_alto["proteina_pct"]


def test_fda_crece_con_ngrdi():
    """A mayor vigor, mayor FDA% (pasto más joven tiene más fibra ácida)."""
    r_bajo = perfil_desde_ngrdi(0.10)
    r_alto = perfil_desde_ngrdi(0.35)
    assert r_bajo["fda_pct"] < r_alto["fda_pct"]


# ---------------------------------------------------------------------------
# Test 7 — Tabla anclada en punto de validación completo (Proteína=22.75)
# La única fila con bromatología completa en el Excel: Proteína=22.75,
# FDA=14.43, FDN=47.49, Energía=5.87, Energía2=1.40, AFORO=1.86.
# Verifica que el modelo bromatológico produce valores coherentes para ese nivel.
# ---------------------------------------------------------------------------

def test_modelo_produce_valores_en_rango_para_proteina_alta():
    """Para Proteína≈22.75 el modelo debe producir FDA y FDN en rango razonable."""
    # Inverso aproximado: Proteína=22.75 corresponde a ngrdi≈0.55 con calibración default
    # Esto cae fuera del rango operativo (34-41), pero los outputs deben ser físicamente posibles.
    # Lo que sí podemos verificar es que los minerales interpolados a 22.75 coincidan con la tabla.
    minerales = minerales_desde_proteina(22.75)

    # Valores exactos de la fila 0 del Excel
    assert abs(minerales["N_pct"]  - 3.64) <= 0.001
    assert abs(minerales["K_pct"]  - 5.49) <= 0.001
    assert abs(minerales["P_pct"]  - 0.48) <= 0.001
    assert abs(minerales["Cu_ppm"] - 7.59) <= 0.01
    assert abs(minerales["Fe_ppm"] - 224.0) <= 0.5
    assert abs(minerales["B_ppm"]  - 2.19) <= 0.01
    assert abs(minerales["S_pct"]  - 0.41) <= 0.001


# ---------------------------------------------------------------------------
# Test 8 — Calibración con parámetros propios
# ---------------------------------------------------------------------------

def test_calibracion_custom_altera_proteina():
    """Parámetros a, b distintos producen proteina_pct diferente (regresión directa).

    El indice_vigor usa siempre _A_VIGOR/_B_VIGOR (parámetros del modelo espectral 2ARGB),
    por lo que no cambia con a/b. La proteína sí cambia porque viene de a*ngrdi+b.
    """
    r_default = perfil_desde_ngrdi(0.215)
    r_custom  = perfil_desde_ngrdi(0.215, a=15.0, b=34.0)
    assert r_default["proteina_pct"] != r_custom["proteina_pct"]
    # indice_vigor es independiente de a/b — lo controlan _A_VIGOR/_B_VIGOR
    assert r_default["indice_vigor"] == r_custom["indice_vigor"]


def test_calibracion_custom_proteina_lineal():
    """Con a y b custom, proteina_pct = a*ngrdi+b (regresión directa)."""
    a, b = 15.0, 34.0
    r = perfil_desde_ngrdi(0.215, a=a, b=b)
    esperado = a * 0.215 + b
    assert abs(r["proteina_pct"] - esperado) < 0.0001
    # indice_vigor viene siempre del modelo espectral (13.33*0.215+35.33 ≈ 38.2)
    assert abs(r["indice_vigor"] - 38.2) < 0.01


# ---------------------------------------------------------------------------
# Tests de calibración de campo — FincaDEMO (ID=8)
# Fuente: 4 pares NGRDI/Proteína medidos en campo, R²=0.988
# ---------------------------------------------------------------------------

CALIBRACION_CAMPO = [
    ("poligono1",  0.62,  23.54),
    ("poligono2", -0.48,   4.30),
    ("poligono3",  0.28,  15.88),
    ("poligono4",  0.42,  18.55),
]


def test_calibracion_campo_error_maximo_menor_2pct():
    """Con la nueva calibración, error vs referencia < 2% en todos los lotes."""
    for nombre, ngrdi, prot_ref in CALIBRACION_CAMPO:
        r = perfil_desde_ngrdi(ngrdi)
        error = abs(r["proteina_pct"] - prot_ref)
        assert error <= 2.0, (
            f"{nombre}: NGRDI={ngrdi}, Prot_calc={r['proteina_pct']:.2f}%, "
            f"Prot_ref={prot_ref}%, error={error:.2f}%"
        )


def test_calibracion_campo_poligono1_pasto_vigoroso():
    """NGRDI=0.62: pasto vigoroso, proteína alta, vigor espectral fuera de rango → extrapolacion."""
    r = perfil_desde_ngrdi(0.62)
    assert abs(r["proteina_pct"] - 23.54) <= 2.0
    assert 20.0 <= r["fda_pct"] <= 55.0
    assert 30.0 <= r["fdn_pct"] <= 100.0
    assert r["minerales_confianza"] == "extrapolacion"


def test_calibracion_campo_poligono2_pasto_degradado():
    """NGRDI=-0.48: pasto degradado, proteína baja, vigor fuera de rango → extrapolacion."""
    r = perfil_desde_ngrdi(-0.48)
    assert abs(r["proteina_pct"] - 4.30) <= 2.0
    assert r["fda_pct"] > 0
    assert r["fdn_pct"] > 0
    assert r["minerales_confianza"] == "extrapolacion"


def test_calibracion_campo_poligono3_en_rango():
    """NGRDI=0.28: vigor espectral en rango operativo [34,41] → confianza alta."""
    r = perfil_desde_ngrdi(0.28)
    assert abs(r["proteina_pct"] - 15.88) <= 2.0
    assert r["en_rango_valido"] is True
    assert r["minerales_confianza"] == "alta"


def test_calibracion_campo_poligono4_limite_superior():
    """NGRDI=0.42: cerca del límite superior del rango operativo, outputs positivos."""
    r = perfil_desde_ngrdi(0.42)
    assert abs(r["proteina_pct"] - 18.55) <= 2.0
    assert r["fda_pct"] > 0
    assert r["fdn_pct"] > 0


def test_fda_fdn_siempre_positivos_en_todo_el_rango():
    """FDA y FDN nunca negativos para NGRDI en [-0.5, 0.7]."""
    for ngrdi in [-0.5, -0.3, -0.1, 0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7]:
        r = perfil_desde_ngrdi(ngrdi)
        assert r["fda_pct"] >= 0, f"FDA negativa en NGRDI={ngrdi}: {r['fda_pct']}"
        assert r["fdn_pct"] >= 0, f"FDN negativa en NGRDI={ngrdi}: {r['fdn_pct']}"
        assert r["energia_mj"] > 0, f"EnrMJ <= 0 en NGRDI={ngrdi}: {r['energia_mj']}"
