"""Explicit unit handling for dose and contribution calculations.

The dose bug in fase 4 (833 kg/ha of a powder with 6% N) was caused by
silently mixing magnitudes from different unit systems: foliar
concentration (% or ppm) and product contribution (% p/p) and
application dose (kg/ha or L/ha). This module makes every conversion
explicit and rejects incompatible ones with a clear error.

The unit vocabulary is small and closed:

  Concentration of a nutrient IN a product (per kg or per L of product):
    'pct_p_p'     fraction weight/weight (e.g. 0.33 = 33% K in Kn32;
                  stored as 0.33 in product_contribution_nutrients.
                  Equals 330 g K per kg product).
    'pct_p_v'     fraction weight/volume (e.g. 0.21 = 21% N in Nitra-n
                  liquid, with density 1.2 kg/L = 252 g N per L of
                  product).
    'g_per_kg'    grams of nutrient per kg of product (e.g. 330 g K/kg Kn32)
    'g_per_L'     grams of nutrient per L of product
    'mg_per_kg'   milligrams of nutrient per kg of product
    'mg_per_L'    milligrams of nutrient per L of product

  IMPORTANT: 'pct_p_p' and 'pct_p_v' are FRACTIONS (0-1), NOT
  percent values (0-100). This matches how the values are stored
  in product_contribution_nutrients.contribution (Kn32 has
  contribution=0.33 for K, not 33). To convert: 0.33 fraction ->
  330 g/kg.

  Application dose per hectare:
    'kg_per_ha'   kilograms of product per hectare
    'L_per_ha'    liters of product per hectare

Conversion rules:
  pct_p_p  <-> g_per_kg     (1% p/p = 10 g/kg, no factor needed)
  pct_p_v  <-> g_per_L      (1% p/v = 10 g/L, no factor needed)
  g_per_kg <-> g_per_L      via density_kg_per_l (g/L = g/kg × density)
  mg_per_kg<-> mg_per_L     via density_kg_per_l
  kg_per_ha<-> L_per_ha     via density_kg_per_l

Anything else (e.g. pct_p_p -> L_per_ha) raises ``UnitConversionError``.
"""

from decimal import Decimal
from typing import Optional, Union

# Concentration of a nutrient IN a product
CONCENTRATION_UNITS = {
    "pct_p_p",
    "pct_p_v",
    "g_per_kg",
    "g_per_L",
    "mg_per_kg",
    "mg_per_L",
}

# Application dose per hectare
DOSE_UNITS = {
    "kg_per_ha",
    "L_per_ha",
}


class UnitConversionError(ValueError):
    """Raised when a unit conversion is invalid or missing data."""


def _mass_in_product(
    value: Union[float, Decimal, int],
    source_unit: str,
    density_kg_per_l: Optional[Union[float, Decimal, int]] = None,
) -> tuple[Decimal, str]:
    """Convert a value to a canonical form: (g_per_kg, value_in_g_per_kg).

    For liquids without density, the function refuses to cross the
    mass/volume boundary and raises UnitConversionError.
    """
    if source_unit not in CONCENTRATION_UNITS:
        raise UnitConversionError(
            "Unidad de concentración desconocida: '{}'".format(source_unit)
            + ". Válidas: {}".format(sorted(CONCENTRATION_UNITS))
        )

    v = Decimal(str(value))

    if source_unit == "pct_p_p":
        # The number is the FRACTION (e.g. 0.33 = 33% p/p = 330 g/kg).
        # 1 fraction unit = 1000 g/kg. This matches how the values are
        # stored in product_contribution_nutrients.contribution
        # (Kn32 has contribution=0.33 for K, not 33).
        return v * Decimal("1000"), "g_per_kg"
    if source_unit == "pct_p_v":
        # Same fraction convention: 0.21 = 21% p/v = 210 g/L.
        if density_kg_per_l is None:
            raise UnitConversionError(
                "Conversión '{}' → 'g_per_kg' requiere density_kg_per_l"
                " (no se puede pasar de masa/volumen a masa/masa sin densidad)".format(
                    source_unit
                )
            )
        # 1000 g/L × density kg/L = g/kg
        return v * Decimal("1000") * Decimal(str(density_kg_per_l)), "g_per_kg"
    if source_unit == "g_per_kg":
        return v, "g_per_kg"
    if source_unit == "g_per_L":
        if density_kg_per_l is None:
            raise UnitConversionError(
                "Conversión 'g_per_L' → 'g_per_kg' requiere density_kg_per_l"
            )
        return v / Decimal(str(density_kg_per_l)), "g_per_kg"
    if source_unit == "mg_per_kg":
        return v / Decimal("1000"), "g_per_kg"
    if source_unit == "mg_per_L":
        if density_kg_per_l is None:
            raise UnitConversionError(
                "Conversión 'mg_per_L' → 'g_per_kg' requiere density_kg_per_l"
            )
        return v / Decimal("1000") / Decimal(str(density_kg_per_l)), "g_per_kg"

    # Unreachable (CONCENTRATION_UNITS guard arriba)
    raise UnitConversionError(f"Unidad no soportada: {source_unit}")


def _dose_to_kg_per_ha(
    value: Union[float, Decimal, int],
    source_unit: str,
    density_kg_per_l: Optional[Union[float, Decimal, int]] = None,
) -> Decimal:
    """Convert a dose value to kg_per_ha (canonical dose unit)."""
    if source_unit not in DOSE_UNITS:
        raise UnitConversionError(
            "Unidad de dosis desconocida: '{}'".format(source_unit)
            + ". Válidas: {}".format(sorted(DOSE_UNITS))
        )

    v = Decimal(str(value))

    if source_unit == "kg_per_ha":
        return v
    if source_unit == "L_per_ha":
        if density_kg_per_l is None:
            raise UnitConversionError(
                "Conversión 'L_per_ha' → 'kg_per_ha' requiere "
                "density_kg_per_l (líquido sin densidad)"
            )
        return v * Decimal(str(density_kg_per_l))
    raise UnitConversionError(f"Unidad de dosis no soportada: {source_unit}")


def convert(
    value: Union[float, Decimal, int],
    source_unit: str,
    target_unit: str,
    density_kg_per_l: Optional[Union[float, Decimal, int]] = None,
) -> Decimal:
    """Convert a numeric value between two compatible units.

    Two conversion families are supported:

      Family A — concentration of nutrient in product
        ('pct_p_p', 'pct_p_v', 'g_per_kg', 'g_per_L', 'mg_per_kg', 'mg_per_L')
        ↔ within family. May need density_kg_per_l when crossing
        mass-mass ↔ mass-volume or mg ↔ g boundaries.

      Family B — application dose per hectare
        ('kg_per_ha', 'L_per_ha'). May need density_kg_per_l when
        crossing kg ↔ L.

    Crossing between families (e.g. 'pct_p_p' → 'kg_per_ha') is
    rejected: you cannot derive an application dose from a
    concentration alone; you also need the application dose
    separately (which is the whole point of the *_dose_kg_per_ha
    columns).

    Args:
        value: numeric value to convert.
        source_unit: unit of ``value``.
        target_unit: unit to convert to.
        density_kg_per_l: required for any conversion that crosses
            the mass/volume boundary in either family.

    Returns:
        Decimal value in ``target_unit``.

    Raises:
        UnitConversionError: if the conversion is invalid or if
            required data is missing.
    """
    if source_unit == target_unit:
        return Decimal(str(value))

    # Family B: application dose
    if source_unit in DOSE_UNITS and target_unit in DOSE_UNITS:
        canonical = _dose_to_kg_per_ha(value, source_unit, density_kg_per_l)
        if target_unit == "kg_per_ha":
            return canonical
        if target_unit == "L_per_ha":
            if density_kg_per_l is None:
                raise UnitConversionError(
                    "Conversión 'kg_per_ha' → 'L_per_ha' requiere " "density_kg_per_l"
                )
            return canonical / Decimal(str(density_kg_per_l))
        raise UnitConversionError(
            f"Unidad de dosis destino no soportada: '{target_unit}'"
        )

    # Family A: concentration
    if source_unit in CONCENTRATION_UNITS and target_unit in CONCENTRATION_UNITS:
        canonical, _ = _mass_in_product(value, source_unit, density_kg_per_l)
        # canonical is in g_per_kg
        if target_unit == "g_per_kg":
            return canonical
        if target_unit == "pct_p_p":
            # fraction (0-1) from g/kg
            return canonical / Decimal("1000")
        if target_unit == "g_per_L":
            if density_kg_per_l is None:
                raise UnitConversionError(
                    "Conversión 'g_per_kg' → 'g_per_L' requiere " "density_kg_per_l"
                )
            return canonical * Decimal(str(density_kg_per_l))
        if target_unit == "pct_p_v":
            if density_kg_per_l is None:
                raise UnitConversionError(
                    "Conversión 'g_per_kg' → 'pct_p_v' requiere " "density_kg_per_l"
                )
            return canonical * Decimal(str(density_kg_per_l)) / Decimal("1000")
        if target_unit == "mg_per_kg":
            return canonical * Decimal("1000")
        if target_unit == "mg_per_L":
            if density_kg_per_l is None:
                raise UnitConversionError(
                    "Conversión 'g_per_kg' → 'mg_per_L' requiere " "density_kg_per_l"
                )
            return canonical * Decimal(str(density_kg_per_l)) * Decimal("1000")
        raise UnitConversionError(
            f"Unidad de concentración destino no soportada: '{target_unit}'"
        )

    # Cross-family or unknown
    raise UnitConversionError(
        f"Conversión inválida '{source_unit}' → '{target_unit}'. "
        f"Solo se permiten conversiones dentro de la familia de "
        f"concentración {sorted(CONCENTRATION_UNITS)} o de dosis "
        f"{sorted(DOSE_UNITS)}; no se puede cruzar entre familias "
        f"sin datos adicionales (yield_kg_per_ha, caldo_L_por_ha, etc)."
    )
