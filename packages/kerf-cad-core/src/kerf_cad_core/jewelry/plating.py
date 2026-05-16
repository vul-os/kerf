"""
kerf_cad_core.jewelry.plating
==============================

Multi-layer metal / plating specification for layered jewelry (e.g. 18k-over-silver,
vermeil, rhodium-over-white-gold, gold-fill).

All functions are pure-Python, hermetic, never raise (errors returned in-band as
``{"error": ..., "warnings": [...]}`` dicts).

## Concepts

Plating layers are deposited on the *surface* of a base metal piece.  Each layer
has:

  - ``alloy``        — one of the METAL_DENSITY_G_CM3 keys (reused from metal_cost)
  - ``thickness_um`` — thickness in microns (µm); 1 µm = 0.001 mm
  - ``coverage_mm2`` — surface area covered by this layer (mm²); often the full
                       outer surface area of the piece

Layer volume = coverage_mm2 × thickness_um × 1e-3  (mm³, converting µm → mm)
Layer mass   = layer_volume_mm3 × density_g_cm3 / 1000  (grams, mm³→cm³)

## Hallmark / legal marking

Jurisdiction rules:

  US (FTC):
    - "vermeil" requires ≥ 2.5 µm of 10k+ gold over sterling silver (925)
    - "gold-filled" or "rolled gold plate" ≥ 1/20 by weight (not handled here;
       use for electroplate only)
    - Plated items must be marked "gold plated" or "GP"; base hallmark applies
    - Rhodium plating does not affect the gold hallmark of the base

  UK / EU (Hallmarking Act + CIBJO):
    - Plated items cannot carry an independent precious-metal hallmark for the
      plating layer
    - The base metal hallmark (e.g. 925 for sterling) remains; must also state
      "plated" or equivalent
    - "vermeil" term used loosely; no statutory minimum in EU (use FTC 2.5 µm rule)

  International / general:
    - "rhodium plated" or "Rh" suffix allowed alongside base hallmark
    - Plated != alloyed; fineness stamp reflects base only

## Wear class

  "light"   — occasional wear (decorative, pendants, earrings rarely touched)
  "medium"  — daily wear but protected (most rings, bracelets)
  "heavy"   — high-friction daily wear (ring shanks, clasps, watch bezels)
  "extreme" — industrial or working jeweler's tools, tool-grade surfaces

## Incompatibility flags

Certain base/plate combinations are technically problematic:

  - Silver base + very thin gold plate (< 0.5 µm): silver tarnish diffuses
    through pinholes in thin gold, causing discolouration ("tarnish bleed-through")
  - Copper-rich base (brass, bronze) + thin gold: copper migration ("pink bleed")
    unless a nickel barrier layer is used
  - Titanium: poor adhesion for standard electroplating without PVD pre-treatment
  - Palladium plate over palladium base: functionally redundant (noted as warning)
"""

from __future__ import annotations

from typing import Optional

from kerf_cad_core.jewelry.metal_cost import (
    METAL_DENSITY_G_CM3,
    METAL_HALLMARK,
    METAL_LABELS,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Microns → mm conversion factor (1 µm = 1e-3 mm)
UM_TO_MM: float = 1e-3

# Volume conversion: 1 cm³ = 1000 mm³  (same as metal_cost.MM3_PER_CM3)
MM3_PER_CM3: float = 1000.0

# ---------------------------------------------------------------------------
# Minimum recommended plating thicknesses (µm) by wear class
# These are jewellery-industry midpoints:
#   Source: ASTM B488 (gold electrodeposit classifications), World Gold Council
#   technical guide "Gold in Electroplating" (2018), Enthone / Atotech application
#   data sheets.  Values are conservative minimums; reputable platers often specify
#   higher minimums for durability.
# ---------------------------------------------------------------------------

# Structure: {plate_alloy_family: {wear_class: min_thickness_um}}
# Alloy families keyed by prefix (checked via startswith).

_MIN_THICKNESS_TABLE: dict[str, dict[str, float]] = {
    # Gold alloys (all karats) — ASTM B488 Type I (soft) / Type III (hard)
    "gold": {
        "light":   0.5,    # decorative; minimum for colour effect
        "medium":  1.25,   # e.g. pendant bail; some daily contact
        "heavy":   2.5,    # FTC vermeil threshold; ring shank level
        "extreme": 5.0,    # e.g. watchcase; hard gold (ASTM B488 Type III)
    },
    # Rhodium — dense, very hard (Mohs 6), thin layers are highly effective
    # Ref: Precious Metal Plating for the Jewellery Industry, Johnson Matthey (2020)
    "rhodium": {
        "light":   0.1,
        "medium":  0.5,
        "heavy":   1.0,
        "extreme": 2.0,
    },
    # Silver — rarely used as a top-coat; sometimes used as a base layer
    "silver": {
        "light":   1.0,
        "medium":  3.0,
        "heavy":   5.0,
        "extreme": 10.0,
    },
    # Platinum — rare in electroplating; PVD more common
    "platinum": {
        "light":   0.25,
        "medium":  0.5,
        "heavy":   1.0,
        "extreme": 2.0,
    },
    # Palladium — used as diffusion barrier or decorative finish
    "palladium": {
        "light":   0.25,
        "medium":  0.5,
        "heavy":   1.0,
        "extreme": 2.0,
    },
    # Generic fallback for other metals (brass, bronze, titanium used as flash)
    "_default": {
        "light":   1.0,
        "medium":  2.0,
        "heavy":   5.0,
        "extreme": 10.0,
    },
}

_WEAR_CLASSES = ("light", "medium", "heavy", "extreme")

# ---------------------------------------------------------------------------
# Hallmark jurisdiction definitions
# ---------------------------------------------------------------------------

# Jurisdiction keys and their descriptions
JURISDICTIONS: dict[str, str] = {
    "us":  "United States (FTC 16 CFR Part 23)",
    "uk":  "United Kingdom (Hallmarking Act 1973 / Assay Office)",
    "eu":  "European Union (CIBJO / national hallmarking)",
    "int": "International / general (most permissive common rules)",
}

# Gold-alloy key families for hallmark logic
_GOLD_KEYS: frozenset[str] = frozenset(
    k for k in METAL_DENSITY_G_CM3 if "k_" in k or k == "24k_yellow"
)
_SILVER_BASE_KEYS: frozenset[str] = frozenset(
    ["sterling_925", "fine_silver", "argentium_935"]
)
_PLATINUM_KEYS: frozenset[str] = frozenset(
    k for k in METAL_DENSITY_G_CM3 if k.startswith("platinum")
)


def _is_gold(alloy_key: str) -> bool:
    return alloy_key in _GOLD_KEYS


def _is_silver(alloy_key: str) -> bool:
    return alloy_key in _SILVER_BASE_KEYS


def _is_platinum(alloy_key: str) -> bool:
    return alloy_key in _PLATINUM_KEYS


def _is_rhodium(alloy_key: str) -> bool:
    # Rhodium is not in METAL_DENSITY_G_CM3 as a standalone key.
    # We accept "rhodium" as a special plate alloy.
    return alloy_key == "rhodium"


def _gold_karat(alloy_key: str) -> Optional[int]:
    """Return gold karat from alloy key (e.g. '18k_yellow' → 18), or None."""
    parts = alloy_key.split("_")
    if parts and parts[0].endswith("k"):
        try:
            return int(parts[0][:-1])
        except ValueError:
            return None
    return None


# ---------------------------------------------------------------------------
# Rhodium density (for mass calculations)
# Rhodium: 12.41 g/cm³ (NIST pure element)
# ---------------------------------------------------------------------------
_RHODIUM_DENSITY_G_CM3: float = 12.41


def _resolve_density(alloy_key: str) -> Optional[float]:
    """Return density in g/cm³ for the given alloy key, or None if unknown."""
    if alloy_key in METAL_DENSITY_G_CM3:
        return METAL_DENSITY_G_CM3[alloy_key]
    if _is_rhodium(alloy_key):
        return _RHODIUM_DENSITY_G_CM3
    return None


# ---------------------------------------------------------------------------
# Public data model helpers
# ---------------------------------------------------------------------------

def plating_spec(
    base_alloy: str,
    plate_layers: list[dict],
) -> dict:
    """
    Build a validated plating specification.

    Parameters
    ----------
    base_alloy : str
        Alloy key for the base metal (from METAL_DENSITY_G_CM3, e.g. "sterling_925").
    plate_layers : list[dict]
        Ordered list of plating layers (outermost last).  Each layer dict:
            alloy        : str    — alloy key or "rhodium"
            thickness_um : float  — thickness in microns (µm)
            coverage_mm2 : float  — surface area covered (mm²)

    Returns
    -------
    dict:
        ok            — bool; False if validation failed
        error         — str description of first error (only if ok=False)
        warnings      — list of warning strings (may be non-empty even if ok=True)
        base_alloy    — normalised base alloy key
        plate_layers  — list of validated + normalised layer dicts:
                        {alloy, thickness_um, coverage_mm2, density_g_cm3}
    """
    warnings: list[str] = []

    # -- validate base alloy --------------------------------------------------
    base_key = str(base_alloy).strip().lower()
    if base_key not in METAL_DENSITY_G_CM3:
        return {
            "ok": False,
            "error": f"Unknown base_alloy '{base_alloy}'. Valid keys: {sorted(METAL_DENSITY_G_CM3)}",
            "warnings": [],
            "base_alloy": base_key,
            "plate_layers": [],
        }

    # -- validate layers -------------------------------------------------------
    if not isinstance(plate_layers, list):
        return {
            "ok": False,
            "error": "plate_layers must be a list",
            "warnings": [],
            "base_alloy": base_key,
            "plate_layers": [],
        }

    validated_layers: list[dict] = []
    for i, layer in enumerate(plate_layers):
        if not isinstance(layer, dict):
            return {
                "ok": False,
                "error": f"plate_layers[{i}] must be a dict",
                "warnings": warnings,
                "base_alloy": base_key,
                "plate_layers": [],
            }

        alloy_raw = layer.get("alloy")
        if alloy_raw is None:
            return {
                "ok": False,
                "error": f"plate_layers[{i}] missing required field 'alloy'",
                "warnings": warnings,
                "base_alloy": base_key,
                "plate_layers": [],
            }
        alloy_key = str(alloy_raw).strip().lower()
        density = _resolve_density(alloy_key)
        if density is None:
            return {
                "ok": False,
                "error": (
                    f"plate_layers[{i}] unknown alloy '{alloy_raw}'. "
                    f"Valid: {sorted(METAL_DENSITY_G_CM3)} + 'rhodium'"
                ),
                "warnings": warnings,
                "base_alloy": base_key,
                "plate_layers": [],
            }

        thickness_raw = layer.get("thickness_um")
        if thickness_raw is None:
            return {
                "ok": False,
                "error": f"plate_layers[{i}] missing required field 'thickness_um'",
                "warnings": warnings,
                "base_alloy": base_key,
                "plate_layers": [],
            }
        try:
            thickness_um = float(thickness_raw)
        except (TypeError, ValueError):
            return {
                "ok": False,
                "error": f"plate_layers[{i}].thickness_um must be a number",
                "warnings": warnings,
                "base_alloy": base_key,
                "plate_layers": [],
            }
        if thickness_um <= 0:
            return {
                "ok": False,
                "error": f"plate_layers[{i}].thickness_um must be positive, got {thickness_um}",
                "warnings": warnings,
                "base_alloy": base_key,
                "plate_layers": [],
            }

        coverage_raw = layer.get("coverage_mm2")
        if coverage_raw is None:
            return {
                "ok": False,
                "error": f"plate_layers[{i}] missing required field 'coverage_mm2'",
                "warnings": warnings,
                "base_alloy": base_key,
                "plate_layers": [],
            }
        try:
            coverage_mm2 = float(coverage_raw)
        except (TypeError, ValueError):
            return {
                "ok": False,
                "error": f"plate_layers[{i}].coverage_mm2 must be a number",
                "warnings": warnings,
                "base_alloy": base_key,
                "plate_layers": [],
            }
        if coverage_mm2 <= 0:
            return {
                "ok": False,
                "error": f"plate_layers[{i}].coverage_mm2 must be positive, got {coverage_mm2}",
                "warnings": warnings,
                "base_alloy": base_key,
                "plate_layers": [],
            }

        validated_layers.append({
            "alloy": alloy_key,
            "thickness_um": thickness_um,
            "coverage_mm2": coverage_mm2,
            "density_g_cm3": density,
        })

    # -- incompatibility warnings (non-fatal) ---------------------------------
    incompat = _incompatibility_warnings(base_key, validated_layers)
    warnings.extend(incompat)

    return {
        "ok": True,
        "error": None,
        "warnings": warnings,
        "base_alloy": base_key,
        "plate_layers": validated_layers,
    }


# ---------------------------------------------------------------------------
# Layer volume / mass
# ---------------------------------------------------------------------------

def layer_volume_mass(
    layer: dict,
    piece_surface_area_mm2: Optional[float] = None,
) -> dict:
    """
    Compute volume and mass for a single plating layer.

    Parameters
    ----------
    layer : dict
        A validated layer dict (from plating_spec) with keys:
        alloy, thickness_um, coverage_mm2, density_g_cm3.
        If coverage_mm2 is absent, ``piece_surface_area_mm2`` is used.
    piece_surface_area_mm2 : float, optional
        Fallback surface area (mm²) when layer does not carry its own
        ``coverage_mm2``.  Required if layer lacks coverage_mm2.

    Returns
    -------
    dict:
        alloy           — alloy key
        thickness_um    — thickness in µm
        coverage_mm2    — surface area used (mm²)
        density_g_cm3   — density used
        volume_mm3      — coverage_mm2 × thickness_um × UM_TO_MM
        mass_g          — volume_mm3 × density_g_cm3 / MM3_PER_CM3
    """
    alloy = layer.get("alloy", "unknown")
    thickness_um = float(layer.get("thickness_um", 0.0))
    coverage_mm2 = layer.get("coverage_mm2")
    if coverage_mm2 is None:
        coverage_mm2 = piece_surface_area_mm2
    if coverage_mm2 is None:
        return {
            "ok": False,
            "error": "coverage_mm2 not in layer and piece_surface_area_mm2 not provided",
            "alloy": alloy,
            "thickness_um": thickness_um,
            "coverage_mm2": None,
            "density_g_cm3": layer.get("density_g_cm3"),
            "volume_mm3": 0.0,
            "mass_g": 0.0,
        }
    coverage_mm2 = float(coverage_mm2)
    density = float(layer.get("density_g_cm3", 0.0))

    # Volume: area (mm²) × thickness (mm, converting from µm)
    thickness_mm = thickness_um * UM_TO_MM
    volume_mm3 = coverage_mm2 * thickness_mm
    # Mass: volume (cm³) × density (g/cm³)
    mass_g = (volume_mm3 / MM3_PER_CM3) * density

    return {
        "alloy": alloy,
        "thickness_um": thickness_um,
        "coverage_mm2": coverage_mm2,
        "density_g_cm3": density,
        "volume_mm3": volume_mm3,
        "mass_g": mass_g,
    }


# ---------------------------------------------------------------------------
# Layered weight
# ---------------------------------------------------------------------------

def layered_weight(
    piece_solid_volume_mm3: float,
    plating: dict,
) -> dict:
    """
    Compute total weight of a plated piece.

    total_mass_g = base_mass_g + Σ layer_mass_g

    Parameters
    ----------
    piece_solid_volume_mm3 : float
        Volume of the solid base-metal body in mm³ (from CAD volume query).
    plating : dict
        A validated plating spec dict (from plating_spec).

    Returns
    -------
    dict:
        ok              — bool
        error           — error string if ok=False
        base_alloy      — base metal key
        base_mass_g     — mass of base metal body in grams
        layers          — list of per-layer volume/mass dicts
        total_layer_mass_g — sum of all layer masses
        total_mass_g    — base_mass_g + total_layer_mass_g
        warnings        — list of warning strings
    """
    if not plating.get("ok", False):
        return {
            "ok": False,
            "error": f"Invalid plating spec: {plating.get('error', 'unknown')}",
            "base_alloy": plating.get("base_alloy"),
            "base_mass_g": 0.0,
            "layers": [],
            "total_layer_mass_g": 0.0,
            "total_mass_g": 0.0,
            "warnings": plating.get("warnings", []),
        }

    if piece_solid_volume_mm3 <= 0:
        return {
            "ok": False,
            "error": f"piece_solid_volume_mm3 must be positive, got {piece_solid_volume_mm3}",
            "base_alloy": plating.get("base_alloy"),
            "base_mass_g": 0.0,
            "layers": [],
            "total_layer_mass_g": 0.0,
            "total_mass_g": 0.0,
            "warnings": plating.get("warnings", []),
        }

    base_key = plating["base_alloy"]
    base_density = METAL_DENSITY_G_CM3[base_key]
    base_mass_g = (piece_solid_volume_mm3 / MM3_PER_CM3) * base_density

    layer_results = []
    total_layer_mass_g = 0.0
    for layer in plating.get("plate_layers", []):
        lvm = layer_volume_mass(layer)
        layer_results.append(lvm)
        total_layer_mass_g += lvm["mass_g"]

    total_mass_g = base_mass_g + total_layer_mass_g

    return {
        "ok": True,
        "error": None,
        "base_alloy": base_key,
        "base_mass_g": base_mass_g,
        "layers": layer_results,
        "total_layer_mass_g": total_layer_mass_g,
        "total_mass_g": total_mass_g,
        "warnings": plating.get("warnings", []),
    }


# ---------------------------------------------------------------------------
# Layered cost
# ---------------------------------------------------------------------------

def layered_cost(
    weights: dict,
    alloy_prices: dict[str, float],
) -> dict:
    """
    Compute per-layer and total cost for a plated piece.

    Parameters
    ----------
    weights : dict
        Output of layered_weight().
    alloy_prices : dict
        Map of alloy key → price per gram in your currency.
        Alloys absent from the map use price 0.0 (weight-only rows).
        Special key "rhodium" accepted.

    Returns
    -------
    dict:
        ok              — bool
        error           — error string if ok=False
        base_alloy      — base metal key
        base_mass_g     — base metal mass
        base_price_g    — price per gram for base
        base_cost       — base_mass_g × base_price_g
        layer_costs     — list of per-layer cost dicts:
                          {alloy, mass_g, price_g, cost}
        total_layer_cost — sum of all layer costs
        total_cost       — base_cost + total_layer_cost
        warnings        — forwarded from weights
    """
    if not weights.get("ok", False):
        return {
            "ok": False,
            "error": f"Invalid weights: {weights.get('error', 'unknown')}",
            "base_alloy": weights.get("base_alloy"),
            "base_mass_g": 0.0,
            "base_price_g": 0.0,
            "base_cost": 0.0,
            "layer_costs": [],
            "total_layer_cost": 0.0,
            "total_cost": 0.0,
            "warnings": weights.get("warnings", []),
        }

    base_key = weights["base_alloy"]
    base_mass_g = weights["base_mass_g"]
    base_price_g = float(alloy_prices.get(base_key, 0.0))
    base_cost = base_mass_g * base_price_g

    layer_costs = []
    total_layer_cost = 0.0
    for layer in weights.get("layers", []):
        alloy = layer["alloy"]
        mass_g = layer["mass_g"]
        price_g = float(alloy_prices.get(alloy, 0.0))
        cost = mass_g * price_g
        layer_costs.append({
            "alloy": alloy,
            "mass_g": mass_g,
            "price_g": price_g,
            "cost": cost,
        })
        total_layer_cost += cost

    total_cost = base_cost + total_layer_cost

    return {
        "ok": True,
        "error": None,
        "base_alloy": base_key,
        "base_mass_g": base_mass_g,
        "base_price_g": base_price_g,
        "base_cost": base_cost,
        "layer_costs": layer_costs,
        "total_layer_cost": total_layer_cost,
        "total_cost": total_cost,
        "warnings": weights.get("warnings", []),
    }


# ---------------------------------------------------------------------------
# Hallmark interaction
# ---------------------------------------------------------------------------

def hallmark_interaction(
    base: str,
    plate_layers: list[dict],
    jurisdiction: str = "us",
) -> dict:
    """
    Determine legal fineness stamps and required marketing terms for a plated piece.

    Parameters
    ----------
    base : str
        Base alloy key (e.g. "sterling_925").
    plate_layers : list[dict]
        Ordered validated plating layers (from plating_spec output).
        Each dict must have: alloy, thickness_um.
    jurisdiction : str
        One of: "us", "uk", "eu", "int".  Default "us".

    Returns
    -------
    dict:
        ok                  — bool
        error               — error string if ok=False
        base_alloy          — normalised base key
        base_hallmark       — integer fineness or None
        base_hallmark_label — string (e.g. "925") or "—"
        jurisdiction        — jurisdiction used
        required_terms      — list of required marking strings
        optional_terms      — list of permitted optional terms
        vermeil             — bool: True if piece qualifies as "vermeil"
        vermeil_notes       — explanation
        warnings            — list of warning strings
    """
    warnings: list[str] = []

    base_key = str(base).strip().lower()
    if base_key not in METAL_DENSITY_G_CM3:
        return {
            "ok": False,
            "error": f"Unknown base alloy '{base}'",
            "base_alloy": base_key,
            "base_hallmark": None,
            "base_hallmark_label": "—",
            "jurisdiction": jurisdiction,
            "required_terms": [],
            "optional_terms": [],
            "vermeil": False,
            "vermeil_notes": "",
            "warnings": [],
        }

    jur = str(jurisdiction).strip().lower()
    if jur not in JURISDICTIONS:
        warnings.append(
            f"Unknown jurisdiction '{jurisdiction}'; falling back to 'int'. "
            f"Valid: {sorted(JURISDICTIONS)}"
        )
        jur = "int"

    base_hallmark = METAL_HALLMARK.get(base_key)
    base_hallmark_label = str(base_hallmark) if base_hallmark is not None else "—"

    required_terms: list[str] = []
    optional_terms: list[str] = []

    # -- Determine outermost precious layer ------------------------------------
    outer_layer = None
    for layer in reversed(plate_layers):
        alloy = layer.get("alloy", "")
        if _is_gold(alloy) or _is_rhodium(alloy) or _is_platinum(alloy):
            outer_layer = layer
            break

    any_gold_layer = any(_is_gold(l.get("alloy", "")) for l in plate_layers)
    any_rhodium_layer = any(_is_rhodium(l.get("alloy", "")) for l in plate_layers)

    # Base hallmark always applies
    if base_hallmark is not None:
        required_terms.append(f"{base_hallmark_label} (base metal fineness)")

    # -- Plating terms ---------------------------------------------------------
    if plate_layers:
        if any_rhodium_layer:
            required_terms.append("Rhodium Plated" if jur in ("us", "int") else "Rh Plated")

        if any_gold_layer:
            # Check outermost gold layer thickness for marketing terms
            top_gold_layer = None
            for layer in reversed(plate_layers):
                if _is_gold(layer.get("alloy", "")):
                    top_gold_layer = layer
                    break

            if top_gold_layer is not None:
                thick = float(top_gold_layer.get("thickness_um", 0.0))
                gold_karat = _gold_karat(top_gold_layer["alloy"])
                karat_str = f"{gold_karat}k" if gold_karat else "gold"

                required_terms.append(f"{karat_str} Gold Plated")

                if jur in ("us", "int") and thick >= 0.175:
                    # FTC: ≥ 0.175 µm = "Gold Electroplate"
                    optional_terms.append("Gold Electroplate (≥0.175 µm)")
                if jur in ("us", "int") and thick >= 2.5:
                    # FTC: ≥ 2.5 µm = "Heavy Gold Electroplate"
                    optional_terms.append("Heavy Gold Electroplate (≥2.5 µm)")
            else:
                required_terms.append("Gold Plated")

        elif plate_layers:
            # Non-gold, non-rhodium plate
            outer_alloy = plate_layers[-1].get("alloy", "unknown")
            outer_label = METAL_LABELS.get(outer_alloy, outer_alloy)
            required_terms.append(f"{outer_label} Plated")

    # -- Vermeil determination -------------------------------------------------
    vermeil = False
    vermeil_notes = ""

    # Vermeil (US FTC 16 CFR §23.7):
    #   - Base must be sterling silver (925) or finer
    #   - Plating must be at least 10k gold
    #   - Plating thickness ≥ 2.5 µm
    # EU/UK: no statutory definition; FTC rule used as best practice

    if _is_silver(base_key):
        top_gold = None
        for layer in reversed(plate_layers):
            if _is_gold(layer.get("alloy", "")):
                top_gold = layer
                break

        if top_gold is not None:
            karat = _gold_karat(top_gold["alloy"])
            thick = float(top_gold.get("thickness_um", 0.0))

            if karat is not None and karat >= 10 and thick >= 2.5:
                vermeil = True
                vermeil_notes = (
                    f"Qualifies as 'vermeil' (US FTC): {karat}k gold, "
                    f"{thick:.2f} µm over {base_hallmark_label} silver. "
                    f"May use 'vermeil' or 'gold vermeil' in marketing."
                )
                required_terms.append("Vermeil (qualifies)")
            else:
                notes_parts = []
                if karat is not None and karat < 10:
                    notes_parts.append(f"gold karat {karat} < 10k minimum")
                if thick < 2.5:
                    notes_parts.append(f"thickness {thick:.2f} µm < 2.5 µm minimum")
                if notes_parts:
                    vermeil_notes = (
                        f"Does NOT qualify as 'vermeil': {'; '.join(notes_parts)}. "
                        f"Must be marketed as '{karat}k Gold Plated' only."
                    )
                    warnings.append(vermeil_notes)
    elif any_gold_layer:
        vermeil_notes = (
            "Base is not silver — 'vermeil' term does not apply. "
            "Must be marketed as 'Gold Plated' only."
        )

    return {
        "ok": True,
        "error": None,
        "base_alloy": base_key,
        "base_hallmark": base_hallmark,
        "base_hallmark_label": base_hallmark_label,
        "jurisdiction": jur,
        "required_terms": required_terms,
        "optional_terms": optional_terms,
        "vermeil": vermeil,
        "vermeil_notes": vermeil_notes,
        "warnings": warnings,
    }


# ---------------------------------------------------------------------------
# Recommended minimum thickness
# ---------------------------------------------------------------------------

def recommended_min_thickness(
    base_alloy: str,
    plate_alloy: str,
    wear_class: str = "medium",
) -> dict:
    """
    Return the recommended minimum plating thickness for the combination.

    Parameters
    ----------
    base_alloy : str
        Base metal alloy key.
    plate_alloy : str
        Plating metal alloy key (or "rhodium").
    wear_class : str
        One of: "light", "medium", "heavy", "extreme".  Default "medium".

    Returns
    -------
    dict:
        ok                  — bool
        error               — error string if ok=False
        base_alloy          — normalised base key
        plate_alloy         — normalised plate key
        wear_class          — wear class used
        min_thickness_um    — recommended minimum thickness in µm
        notes               — explanation / source
        warnings            — list of warning strings
    """
    warnings: list[str] = []

    base_key = str(base_alloy).strip().lower()
    plate_key = str(plate_alloy).strip().lower()
    wc = str(wear_class).strip().lower()

    if base_key not in METAL_DENSITY_G_CM3:
        return {
            "ok": False,
            "error": f"Unknown base_alloy '{base_alloy}'",
            "base_alloy": base_key,
            "plate_alloy": plate_key,
            "wear_class": wc,
            "min_thickness_um": 0.0,
            "notes": "",
            "warnings": [],
        }

    density = _resolve_density(plate_key)
    if density is None:
        return {
            "ok": False,
            "error": f"Unknown plate_alloy '{plate_alloy}'. Valid: {sorted(METAL_DENSITY_G_CM3)} + 'rhodium'",
            "base_alloy": base_key,
            "plate_alloy": plate_key,
            "wear_class": wc,
            "min_thickness_um": 0.0,
            "notes": "",
            "warnings": [],
        }

    if wc not in _WEAR_CLASSES:
        warnings.append(
            f"Unknown wear_class '{wear_class}'; defaulting to 'medium'. "
            f"Valid: {_WEAR_CLASSES}"
        )
        wc = "medium"

    # Determine which family table to use
    min_thick: float
    if _is_gold(plate_key):
        table = _MIN_THICKNESS_TABLE["gold"]
        source = "ASTM B488 / World Gold Council electroplating guide"
    elif _is_rhodium(plate_key):
        table = _MIN_THICKNESS_TABLE["rhodium"]
        source = "Johnson Matthey Precious Metal Plating for Jewellery (2020)"
    elif _is_silver(plate_key):
        table = _MIN_THICKNESS_TABLE["silver"]
        source = "Industry convention (silver as decorative top coat is uncommon)"
    elif _is_platinum(plate_key):
        table = _MIN_THICKNESS_TABLE["platinum"]
        source = "Platinum Guild International technical notes"
    elif plate_key.startswith("palladium"):
        table = _MIN_THICKNESS_TABLE["palladium"]
        source = "Platinum Guild International / Enthone application data"
    else:
        table = _MIN_THICKNESS_TABLE["_default"]
        source = "Generic jewellery industry convention"

    min_thick = table[wc]

    # Base-specific adjustments
    extra_notes: list[str] = []
    if base_key in ("brass", "bronze") and _is_gold(plate_key):
        copper_min = max(min_thick, 2.5)
        if copper_min > min_thick:
            min_thick = copper_min
            extra_notes.append(
                "Copper-base alloy: minimum raised to 2.5 µm to reduce copper migration "
                "(consider nickel barrier layer)"
            )

    if base_key == "titanium":
        extra_notes.append(
            "Titanium requires PVD pre-treatment or adhesion flash for reliable plating"
        )

    notes = f"Source: {source}"
    if extra_notes:
        notes += ". " + ". ".join(extra_notes)

    # Incompatibility check
    incompat = _incompatibility_warnings(base_key, [{"alloy": plate_key, "thickness_um": min_thick}])
    warnings.extend(incompat)

    return {
        "ok": True,
        "error": None,
        "base_alloy": base_key,
        "plate_alloy": plate_key,
        "wear_class": wc,
        "min_thickness_um": min_thick,
        "notes": notes,
        "warnings": warnings,
    }


# ---------------------------------------------------------------------------
# Incompatibility warnings
# ---------------------------------------------------------------------------

def _incompatibility_warnings(base_key: str, layers: list[dict]) -> list[str]:
    """
    Return a list of compatibility warning strings for the base+layers combination.

    These are non-fatal — the user can proceed but should be aware of the issues.
    """
    warnings: list[str] = []

    for i, layer in enumerate(layers):
        alloy = layer.get("alloy", "")
        thickness_um = float(layer.get("thickness_um", 0.0))

        # Tarnish bleed-through: silver base + thin gold plate
        if _is_silver(base_key) and _is_gold(alloy) and 0 < thickness_um < 0.5:
            warnings.append(
                f"Layer {i} ({alloy}, {thickness_um} µm): silver base + gold < 0.5 µm — "
                f"risk of silver tarnish diffusing through pinholes in thin gold "
                f"('tarnish bleed-through'). Recommend ≥ 0.5 µm gold or add rhodium undercoat."
            )

        # Copper migration: copper-rich base (brass/bronze) + thin gold
        if base_key in ("brass", "bronze") and _is_gold(alloy) and 0 < thickness_um < 2.5:
            warnings.append(
                f"Layer {i} ({alloy}, {thickness_um} µm): copper-base alloy + gold < 2.5 µm — "
                f"risk of copper migration ('pink bleed-through'). "
                f"Recommend a nickel barrier layer before gold plating."
            )

        # Titanium adhesion
        if base_key == "titanium" and thickness_um > 0:
            warnings.append(
                f"Layer {i} ({alloy}): titanium base requires PVD/ion-beam pre-treatment "
                f"for adequate adhesion; standard electroplating adhesion is poor."
            )

        # Redundant palladium-over-palladium
        if base_key.startswith("palladium") and alloy.startswith("palladium"):
            warnings.append(
                f"Layer {i} ({alloy}): palladium plating over palladium base is "
                f"functionally redundant — consider omitting or using rhodium for colour contrast."
            )

    return warnings


# ---------------------------------------------------------------------------
# LLM tool registration
# ---------------------------------------------------------------------------

try:
    import json as _json
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register
    from kerf_core.utils.context import ProjectCtx  # noqa: F401

    _plating_spec_tool = ToolSpec(
        name="jewelry_plating",
        description=(
            "Multi-layer metal plating specification for jewelry — 18k-over-silver, vermeil,\n"
            "rhodium, gold-fill, and similar layered constructions.\n"
            "\n"
            "Given a base metal and an ordered list of plating layers (alloy + thickness in\n"
            "microns + surface area in mm²), returns:\n"
            "  - per-layer volume and mass (V = area × thickness, mass = V × ρ)\n"
            "  - total piece weight (base + all layers)\n"
            "  - per-layer and total material cost\n"
            "  - legal hallmark / fineness stamp requirements per jurisdiction\n"
            "  - vermeil qualification (US FTC: ≥ 2.5 µm 10k+ gold over sterling)\n"
            "  - recommended minimum plating thickness by wear class\n"
            "  - incompatibility warnings (tarnish bleed-through, copper migration, etc.)\n"
            "\n"
            "Base alloy keys (same as jewelry_metal_cost):\n"
            "  sterling_925, fine_silver, argentium_935\n"
            "  10k_yellow/white/rose, 14k_yellow/white/rose, 18k_yellow/white/rose, etc.\n"
            "  platinum_950, platinum_900, palladium_950, brass, bronze, titanium\n"
            "\n"
            "Plate layer alloy keys: same as above + 'rhodium'\n"
            "\n"
            "Wear classes: light, medium, heavy, extreme\n"
            "Jurisdictions: us, uk, eu, int"
        ),
        input_schema={
            "type": "object",
            "properties": {
                "base_alloy": {
                    "type": "string",
                    "description": "Base metal alloy key (e.g. 'sterling_925', '18k_yellow').",
                },
                "plate_layers": {
                    "type": "array",
                    "description": (
                        "Ordered list of plating layers (innermost first, outermost last). "
                        "Each: {alloy, thickness_um, coverage_mm2}."
                    ),
                    "items": {
                        "type": "object",
                        "properties": {
                            "alloy":        {"type": "string"},
                            "thickness_um": {"type": "number"},
                            "coverage_mm2": {"type": "number"},
                        },
                        "required": ["alloy", "thickness_um", "coverage_mm2"],
                    },
                },
                "piece_solid_volume_mm3": {
                    "type": "number",
                    "description": (
                        "Volume of the solid base metal body in mm³ (from CAD volume query). "
                        "Required for weight and cost calculation."
                    ),
                },
                "alloy_prices": {
                    "type": "object",
                    "description": (
                        "Map of alloy key → price per gram in your currency. "
                        "Include base alloy and any plate alloys for cost output. "
                        "Missing keys default to 0 (weight-only rows)."
                    ),
                    "additionalProperties": {"type": "number"},
                },
                "jurisdiction": {
                    "type": "string",
                    "description": "Hallmark jurisdiction: us, uk, eu, int. Default 'us'.",
                },
                "wear_class": {
                    "type": "string",
                    "description": (
                        "Wear class for minimum thickness recommendation: "
                        "light, medium, heavy, extreme. Default 'medium'."
                    ),
                },
            },
            "required": ["base_alloy", "plate_layers"],
        },
    )

    @register(_plating_spec_tool, write=False)
    async def run_jewelry_plating(ctx: "ProjectCtx", args: bytes) -> str:
        """LLM tool: jewelry_plating."""
        try:
            a = _json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

        base_alloy = a.get("base_alloy")
        if base_alloy is None:
            return err_payload("base_alloy is required", "BAD_ARGS")

        plate_layers_raw = a.get("plate_layers")
        if plate_layers_raw is None:
            return err_payload("plate_layers is required", "BAD_ARGS")
        if not isinstance(plate_layers_raw, list):
            return err_payload("plate_layers must be an array", "BAD_ARGS")

        spec = plating_spec(str(base_alloy), plate_layers_raw)
        if not spec["ok"]:
            return err_payload(spec["error"], "BAD_ARGS")

        result: dict = {
            "spec": spec,
        }

        # -- weight -----------------------------------------------------------
        volume_mm3 = a.get("piece_solid_volume_mm3")
        if volume_mm3 is not None:
            try:
                volume_mm3 = float(volume_mm3)
            except (TypeError, ValueError):
                return err_payload("piece_solid_volume_mm3 must be a number", "BAD_ARGS")
            if volume_mm3 <= 0:
                return err_payload(
                    f"piece_solid_volume_mm3 must be positive, got {volume_mm3}", "BAD_ARGS"
                )
            weights = layered_weight(volume_mm3, spec)
            result["weight"] = weights

            # -- cost ---------------------------------------------------------
            alloy_prices = a.get("alloy_prices") or {}
            if not isinstance(alloy_prices, dict):
                return err_payload("alloy_prices must be an object", "BAD_ARGS")
            costs = layered_cost(weights, alloy_prices)
            result["cost"] = costs

        # -- hallmark interaction ---------------------------------------------
        jurisdiction = str(a.get("jurisdiction", "us")).strip().lower()
        hallmark = hallmark_interaction(
            base=spec["base_alloy"],
            plate_layers=spec["plate_layers"],
            jurisdiction=jurisdiction,
        )
        result["hallmark"] = hallmark

        # -- recommended thickness for each layer by wear class ---------------
        wear_class = str(a.get("wear_class", "medium")).strip().lower()
        thickness_recs = []
        for layer in spec["plate_layers"]:
            rec = recommended_min_thickness(
                base_alloy=spec["base_alloy"],
                plate_alloy=layer["alloy"],
                wear_class=wear_class,
            )
            thickness_recs.append(rec)
        result["thickness_recommendations"] = thickness_recs

        return ok_payload(result)

    _TOOL_REGISTERED = True

except ImportError:
    _TOOL_REGISTERED = False
