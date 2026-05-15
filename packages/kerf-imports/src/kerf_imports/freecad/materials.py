"""
materials.py — FreeCAD App::MaterialObject → Kerf .material translator.

FreeCAD stores material data in ``App::MaterialObject`` objects.  The
material properties live in a ``Material`` property typed
``App::PropertyMap`` — a flat key→value string dict.  Common keys follow
the FreeCAD material-card convention (defined in
``Mod/Material/StandardMaterial.py``).

We extract the following fields and emit a Kerf ``.material`` JSON::

    {
      "version": 1,
      "name": "Steel",
      "density": 7800,               # kg/m³ (converted from FreeCAD units)
      "youngs_modulus": 210000,      # MPa
      "poisson_ratio": 0.30,
      "yield_strength": 250,         # MPa  (YieldStrength)
      "ultimate_strength": 400,      # MPa  (UltimateTensileStrength)
      "thermal_conductivity": 50,    # W/(m·K)
      "specific_heat": 500,          # J/(kg·K)
      "thermal_expansion": 1.2e-5,   # 1/K (CTE)
      "color": "#808080",            # hex from FreeCAD AppearanceColor/KdColor
      "freecad_ref": { ... },
      "warnings": [...]
    }

Properties not present in the FreeCAD card are omitted (not emitted as
null) so the output stays minimal.

FreeCAD material card key names used (from their material-card .FCMat
files, also reflected in the XML property map):

    - ``Density``                   → ``density``
    - ``YoungsModulus``             → ``youngs_modulus``
    - ``PoissonRatio``              → ``poisson_ratio``
    - ``YieldStrength``             → ``yield_strength``
    - ``UltimateTensileStrength``   → ``ultimate_strength``
    - ``ThermalConductivity``       → ``thermal_conductivity``
    - ``SpecificHeat``              → ``specific_heat``
    - ``ThermalExpansionCoefficient`` → ``thermal_expansion``
    - ``KdColor``  / ``AppearanceColor`` → ``color``

Dropped (not in Kerf .material v1):
    - ``FatherMaterial``            (inheritance chain)
    - ``Description``               (long-form text)
    - ``ReferenceSource``           (bibliography ref)
    - Fluid properties (``Viscosity``, ``KinematicViscosity``, etc.)
    - Electrical properties (``ElectricConductivity``, etc.)
    - Optical properties except color

Unit handling:

FreeCAD material cards store numeric values as strings with embedded unit
suffixes (e.g. ``"7.90 g/cm^3"``, ``"210 GPa"``).  We parse these and
convert to the canonical SI units above.
"""
from __future__ import annotations

import re
from typing import Any

from .types import FCStdObject


# ---------------------------------------------------------------------------
# Mapped FreeCAD property keys → Kerf field names
# ---------------------------------------------------------------------------

_FIELD_MAP: dict[str, str] = {
    "Density":                      "density",
    "YoungsModulus":                "youngs_modulus",
    "PoissonRatio":                 "poisson_ratio",
    "YieldStrength":                "yield_strength",
    "UltimateTensileStrength":      "ultimate_strength",
    "ThermalConductivity":          "thermal_conductivity",
    "SpecificHeat":                 "specific_heat",
    "ThermalExpansionCoefficient":  "thermal_expansion",
}

_COLOR_KEYS = ("KdColor", "AppearanceColor", "DiffuseColor")


# ---------------------------------------------------------------------------
# Unit conversion table
# ---------------------------------------------------------------------------

_DENSITY_CONVERSIONS: list[tuple[re.Pattern, float]] = [
    (re.compile(r"g/cm\^?3", re.I),     1000.0),
    (re.compile(r"kg/m\^?3", re.I),     1.0),
    (re.compile(r"kg/dm\^?3", re.I),    1000.0),
    (re.compile(r"t/m\^?3", re.I),      1000.0),
]

_STRESS_CONVERSIONS: list[tuple[re.Pattern, float]] = [
    (re.compile(r"GPa", re.I),  1000.0),
    (re.compile(r"MPa", re.I),  1.0),
    (re.compile(r"kPa", re.I),  0.001),
    (re.compile(r"Pa",  re.I),  1e-6),
    (re.compile(r"N/mm\^?2", re.I), 1.0),
    (re.compile(r"kN/mm\^?2", re.I), 1000.0),
]

_CONDUCTIVITY_CONVERSIONS: list[tuple[re.Pattern, float]] = [
    (re.compile(r"W/m/K", re.I),   1.0),
    (re.compile(r"W/\(m.K\)", re.I), 1.0),
    (re.compile(r"W/mK", re.I),    1.0),
]

_SPECIFIC_HEAT_CONVERSIONS: list[tuple[re.Pattern, float]] = [
    (re.compile(r"J/kg/K", re.I),   1.0),
    (re.compile(r"J/\(kg.K\)", re.I), 1.0),
    (re.compile(r"kJ/kg/K", re.I),  1000.0),
]

_CTE_CONVERSIONS: list[tuple[re.Pattern, float]] = [
    (re.compile(r"1/K", re.I),  1.0),
    (re.compile(r"um/m/K", re.I), 1e-6),
    (re.compile(r"1e-6/K", re.I), 1e-6),
    (re.compile(r"ppm/K", re.I), 1e-6),
]

_FIELD_CONVERSIONS: dict[str, list[tuple[re.Pattern, float]]] = {
    "density":              _DENSITY_CONVERSIONS,
    "youngs_modulus":       _STRESS_CONVERSIONS,
    "yield_strength":       _STRESS_CONVERSIONS,
    "ultimate_strength":    _STRESS_CONVERSIONS,
    "thermal_conductivity": _CONDUCTIVITY_CONVERSIONS,
    "specific_heat":        _SPECIFIC_HEAT_CONVERSIONS,
    "thermal_expansion":    _CTE_CONVERSIONS,
    "poisson_ratio":        [],
}


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def translate_material(obj: FCStdObject) -> dict[str, Any]:
    """
    Translate an ``App::MaterialObject`` FCStdObject into a Kerf ``.material``
    JSON dict.

    Parameters
    ----------
    obj :
        An :class:`~kerf_imports.freecad.types.FCStdObject` with
        ``type == "App::MaterialObject"``.

    Returns
    -------
    dict
        Kerf ``.material`` payload.
    """
    warnings: list[str] = []

    mat_map = obj.properties.get("Material")
    if not isinstance(mat_map, dict):
        mat_map = {}
        warnings.append(
            f"material '{obj.label}': 'Material' property not found or not a dict — "
            "no mechanical properties extracted."
        )

    name = (
        mat_map.get("Name")
        or mat_map.get("CardName")
        or obj.label
        or obj.name
    )

    result: dict[str, Any] = {
        "version": 1,
        "name": name,
    }

    for fc_key, kerf_key in _FIELD_MAP.items():
        raw = mat_map.get(fc_key)
        if raw is None:
            continue
        val, unit, warn = _parse_quantity_str(str(raw), kerf_key)
        if warn:
            warnings.append(f"material '{name}' field '{fc_key}': {warn}")
        if val is not None:
            result[kerf_key] = val

    color_str = _extract_color(mat_map, warnings, name)
    if color_str is not None:
        result["color"] = color_str

    result["freecad_ref"] = {
        "name": obj.name,
        "label": obj.label,
        "type": obj.type,
    }
    result["warnings"] = warnings

    return result


# ---------------------------------------------------------------------------
# Quantity string parser
# ---------------------------------------------------------------------------

def _parse_quantity_str(
    raw: str,
    field: str,
) -> tuple[float | None, str, str]:
    """
    Parse a FreeCAD material property value string like ``"7.90 g/cm^3"``
    and return ``(converted_float, unit_str, warning_str)``.

    Returns ``(None, "", warning)`` if parsing fails.
    """
    raw = raw.strip()
    if not raw:
        return None, "", ""

    m = re.match(r"^([+-]?\d+(?:[.,]\d+)?(?:[eE][+-]?\d+)?)(.*)$", raw)
    if not m:
        return None, "", f"could not parse value string {raw!r} — skipped."

    num_str = m.group(1).replace(",", ".")
    unit_part = m.group(2).strip()

    try:
        num = float(num_str)
    except ValueError:
        return None, "", f"non-numeric value {raw!r} — skipped."

    converters = _FIELD_CONVERSIONS.get(field, [])
    if not converters:
        return num, unit_part, ""

    for pattern, multiplier in converters:
        if unit_part and pattern.search(unit_part):
            return num * multiplier, unit_part, ""

    if unit_part:
        return num, unit_part, (
            f"unrecognised unit {unit_part!r} for field {field!r} — "
            "value stored as-is without conversion."
        )
    return num, "", ""


# ---------------------------------------------------------------------------
# Color extraction
# ---------------------------------------------------------------------------

def _extract_color(
    mat_map: dict[str, str],
    warnings: list[str],
    mat_name: str,
) -> str | None:
    """Extract and normalise a color from the material map to hex string."""
    for key in _COLOR_KEYS:
        raw = mat_map.get(key)
        if not raw:
            continue
        parsed = _parse_color(raw)
        if parsed:
            return parsed
        warnings.append(
            f"material '{mat_name}' color key '{key}': could not parse "
            f"color value {raw!r} — skipped."
        )
    return None


def _parse_color(raw: str) -> str | None:
    """
    Parse FreeCAD color representations to hex string.

    FreeCAD uses several formats::

        "(0.50, 0.50, 0.50)"   → "#808080"   (float RGB, 0-1)
        "(128, 128, 128)"      → "#808080"   (int RGB, 0-255)
        "#808080"              → "#808080"   (already hex)
    """
    raw = raw.strip()
    if not raw:
        return None

    if re.match(r"^#[0-9a-fA-F]{6}$", raw):
        return raw.lower()

    inner = raw.strip("()")
    parts = [p.strip() for p in inner.split(",")]
    if len(parts) >= 3:
        try:
            r_raw, g_raw, b_raw = parts[0], parts[1], parts[2]
            r = float(r_raw)
            g = float(g_raw)
            b = float(b_raw)
        except ValueError:
            return None

        if r <= 1.0 and g <= 1.0 and b <= 1.0 and "." in (r_raw + g_raw + b_raw):
            ri, gi, bi = int(r * 255), int(g * 255), int(b * 255)
        else:
            ri, gi, bi = int(r), int(g), int(b)

        return f"#{ri:02x}{gi:02x}{bi:02x}"

    return None
