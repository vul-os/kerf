"""
Parametric gemstone solid generator.

Supported cuts
--------------
round_brilliant  57/58 facets — the GIA standard.
princess         Square modified brilliant (4-fold symmetry).
oval             Elliptical modified brilliant.
emerald          Rectangular step cut.
marquise         Boat-shaped modified brilliant.
pear             Teardrop modified brilliant.
cushion          Square/rectangular cushion modified brilliant.
radiant          Cropped-corner rectangular modified brilliant.
asscher          Square step cut with cropped corners (high crown).
trillion         Triangular modified brilliant (Trillion™ / triangular brilliant).
heart            Heart-shaped modified brilliant.
baguette         Rectangular step cut (long narrow bar).
briolette        Elongated teardrop with all-facet surface; no table.

Each cut is described by a *proportions dict* whose keys follow GIA/AGS
conventions (all linear dimensions as mm, angles in degrees).

Carat ↔ mm formulae
--------------------
These are empirical weight approximations used industry-wide.

Round brilliant (1 ct ≈ 6.5 mm diameter, diamond density 3.51 g/cm³):
    carat = (diameter_mm / 6.5) ** 3

    Derivation: density of diamond ≈ 3.51 g/cm³; a brilliant approximates a
    flattened cylinder.  The cube exponent captures the volume scaling.
    Inversion: diameter_mm = 6.5 * carat**(1/3)

Other cuts use an equivalent-diameter conversion via their aspect ratio
relative to round brilliant.  E.g. a 1 ct princess ≈ 5.5 mm side length.

Coloured-stone density correction
----------------------------------
The ref_mm constants above are calibrated for diamond (3.51 g/cm³).  For a
different material, the reference dimension scales as:

    ref_mm_material = ref_mm_diamond * (rho_diamond / rho_material) ** (1/3)

so that volume × density = the same 0.2 g per carat.

Pass `density_g_cm3` (or `material`) to carat_from_mm / mm_from_carat to get
accurate carat weights for coloured stones.  Default material is "diamond" for
full backward compatibility.

Density sources: GIA Gemology Reference (https://www.gia.edu/gems-gemology),
Richard T. Liddicoat Jr., "GIA Gem Reference Guide" (GIA 1995), and
*Gemological Institute of America Gem Encyclopedia* (2014 ed.).

Industry reference proportions
-------------------------------
Round brilliant (ideal / "Tolkowsky"):
    table_pct        : 53–58 %   (table width / girdle diameter)
    crown_angle_deg  : 34.5°
    pavilion_angle_deg: 40.75°
    girdle_pct       : 2.5 % (thin-medium girdle thickness / diameter)
    total_depth_pct  : 61–62 %

Princess:
    table_pct: 75 %, crown_angle_deg: 30°, pavilion_angle_deg: 42°,
    pavilion_depth_pct: 43 %, total_depth_pct: 68 %

Emerald:
    table_pct: 60 %, crown_angle_deg: 15°, step_rows: 3,
    total_depth_pct: 60 %, corner_cut_ratio: 0.15

Radiant:
    table_pct: 62 %, crown_angle_deg: 32°, pavilion_angle_deg: 41°,
    aspect_ratio: 0.75, corner_cut_ratio: 0.10

Asscher:
    table_pct: 60 %, crown_angle_deg: 25°, step_rows: 3,
    aspect_ratio: 1.0, corner_cut_ratio: 0.20 (deeper corner cuts than emerald)

Trillion:
    table_pct: 55 %, crown_angle_deg: 34°, pavilion_angle_deg: 41°,
    sides: 3, aspect_ratio: 1.0 (equilateral)

Heart:
    table_pct: 56 %, crown_angle_deg: 34.5°, pavilion_angle_deg: 40.75°,
    aspect_ratio: 0.98 (length ≈ width), cleft_depth_pct: 10

Baguette:
    table_pct: 70 %, crown_angle_deg: 8°, step_rows: 2,
    aspect_ratio: 0.40 (3:1 to 4:1 L:W typical)

Briolette:
    No table; full-facet elongated teardrop; crown_angle_deg = 30° (upper facets),
    pavilion_angle_deg = 45° (lower point), aspect_ratio: 0.50 (height ≈ 2× width)

LLM-facing tools
----------------
  jewelry_create_gemstone  — appends a gemstone node to a .feature file
"""

from __future__ import annotations

import json
import uuid
from typing import Optional, NamedTuple

from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register
from kerf_core.utils.context import ProjectCtx
from kerf_cad_core.surfacing import (
    read_feature_content,
    append_feature_node,
    next_node_id,
)


# ---------------------------------------------------------------------------
# Cut registry
# ---------------------------------------------------------------------------

GEMSTONE_CUTS = {
    "round_brilliant",
    "princess",
    "oval",
    "emerald",
    "marquise",
    "pear",
    "cushion",
    # Fancy cuts added in second slice:
    "radiant",
    "asscher",
    "trillion",
    "heart",
    "baguette",
    "briolette",
}


# ---------------------------------------------------------------------------
# Gemstone material density table
# ---------------------------------------------------------------------------

# Specific gravity (g/cm³) for common gem materials.
#
# Sources:
#   GIA Gem Reference Guide (Liddicoat, GIA 1995) — primary authority for SG
#   GIA Gemology Reference: https://www.gia.edu/gems-gemology
#   Gemological Institute of America Gem Encyclopedia, 2014 ed.
#   International Gem Society (IGS) gem property tables
#   Values are midpoint of published range where a range is given.
#
# One carat = 0.2 g exactly.  The carat-from-mm formula assumes a specific
# volume for a given cut shape.  For a material with density ρ (g/cm³) vs.
# diamond (3.51 g/cm³), the reference dimension at 1 ct scales as:
#
#     ref_mm_material = ref_mm_diamond × (3.51 / ρ) ^ (1/3)
#
# This keeps the volume × ρ = 0.2 g relationship intact.
GEMSTONE_DENSITIES: dict[str, float] = {
    # Natural stones
    "diamond":      3.51,  # GIA; range 3.50–3.53
    "ruby":         3.99,  # GIA; corundum range 3.97–4.05, midpoint ~4.00
    "sapphire":     4.00,  # GIA; corundum (same mineral as ruby)
    "emerald":      2.72,  # GIA; beryl range 2.67–2.78, typical 2.72
    "amethyst":     2.65,  # GIA; quartz
    "citrine":      2.65,  # GIA; quartz
    "aquamarine":   2.72,  # GIA; beryl
    "morganite":    2.71,  # GIA; beryl
    "topaz":        3.53,  # GIA; range 3.49–3.57
    "garnet":       3.78,  # GIA; pyrope–almandine midpoint (~3.6–4.0)
    "spinel":       3.60,  # GIA; range 3.54–3.63
    "tanzanite":    3.35,  # GIA; zoisite
    "peridot":      3.32,  # GIA; range 3.27–3.37
    "tourmaline":   3.10,  # GIA; range 2.82–3.32, typical ~3.10
    "opal":         2.08,  # GIA; range 1.98–2.20
    "moonstone":    2.56,  # GIA; orthoclase feldspar
    "alexandrite":  3.73,  # GIA; chrysoberyl
    "chrysoberyl":  3.73,  # GIA
    "zircon":       4.67,  # GIA; range 3.93–4.73 (high type ~4.67)
    "pearl":        2.71,  # GIA; nacre range 2.60–2.85
    "coral":        2.65,  # GIA; organic
    "amber":        1.08,  # GIA; organic
    "lapis_lazuli": 2.80,  # GIA; range 2.50–3.00, typical 2.80
    "turquoise":    2.75,  # GIA; range 2.60–2.90
    "jade_jadeite": 3.33,  # GIA; jadeite
    "jade_nephrite":2.95,  # GIA; nephrite
}

# Diamond SG used as the calibration baseline for ref_mm constants
_DIAMOND_DENSITY: float = GEMSTONE_DENSITIES["diamond"]


# ---------------------------------------------------------------------------
# Carat ↔ mm sizing
# ---------------------------------------------------------------------------

# Exponent k for: carat = (dim_mm / ref_mm) ** k
# ref_mm = diameter at 1 carat for DIAMOND; k = 3 for a cubic scaling approx.

_CARAT_REF: dict[str, tuple[float, float]] = {
    # (ref_diameter_mm_for_diamond, exponent)
    "round_brilliant": (6.5, 3.0),
    "princess":        (5.5, 3.0),   # side length
    "oval":            (7.7, 3.0),   # long axis
    "emerald":         (7.0, 3.0),   # long axis
    "marquise":        (10.0, 3.0),  # long axis
    "pear":            (8.0, 3.0),   # long axis
    "cushion":         (5.5, 3.0),   # side length
    # Fancy cuts (ref_mm derived from equivalent-volume comparison to round brilliant):
    "radiant":         (6.0, 3.0),   # similar footprint to princess; ~10% larger
    "asscher":         (5.5, 3.0),   # square step; similar depth to emerald
    "trillion":        (7.0, 3.0),   # equilateral triangle; large face, shallow
    "heart":           (6.5, 3.0),   # same ref as round brilliant (≈same volume)
    "baguette":        (5.0, 3.0),   # 3:1 narrow bar; shallow step cut
    "briolette":       (5.5, 3.0),   # elongated teardrop; half-round cross-section
}


def _effective_ref_mm(cut: str, density_g_cm3: float) -> float:
    """Return ref_mm adjusted for material density.

    The published ref_mm values assume diamond density (3.51 g/cm³).
    For a different material:
        ref_mm_material = ref_mm_diamond × (rho_diamond / rho_material) ^ (1/3)

    This ensures that ref_mm_material × density = 0.2 g (1 carat) for the
    same cut geometry.
    """
    ref_mm, _exp = _CARAT_REF[cut]
    if density_g_cm3 == _DIAMOND_DENSITY:
        return ref_mm
    return ref_mm * (_DIAMOND_DENSITY / density_g_cm3) ** (1.0 / 3.0)


def _resolve_density(material: Optional[str], density_g_cm3: Optional[float]) -> float:
    """Return density in g/cm³ from material name or explicit override.

    Precedence: explicit density_g_cm3 > GEMSTONE_DENSITIES lookup > diamond default.
    """
    if density_g_cm3 is not None:
        if density_g_cm3 <= 0:
            raise ValueError("density_g_cm3 must be positive")
        return density_g_cm3
    if material is not None:
        key = material.lower().replace(" ", "_")
        if key in GEMSTONE_DENSITIES:
            return GEMSTONE_DENSITIES[key]
        # Unknown material: fall back to diamond with no error (backward-compat)
    return _DIAMOND_DENSITY


def carat_from_mm(
    cut: str,
    dim_mm: float,
    *,
    material: Optional[str] = None,
    density_g_cm3: Optional[float] = None,
) -> float:
    """Return estimated carat weight from the primary dimension in mm.

    For round_brilliant, dim_mm is the girdle diameter.
    For all other cuts, dim_mm is the long-axis length.

    Formula: carat = (dim_mm / ref_mm_material) ** exponent
    where ref_mm_material is the ~1-carat dimension for that cut at the
    given material density (default: diamond, 3.51 g/cm³).

    Parameters
    ----------
    cut : str
        One of the GEMSTONE_CUTS keys.
    dim_mm : float
        Primary dimension in mm (>0).
    material : str, optional
        Material name (e.g. ``"ruby"``).  Looked up in GEMSTONE_DENSITIES.
        Ignored if ``density_g_cm3`` is also supplied.
    density_g_cm3 : float, optional
        Explicit material density in g/cm³.  Overrides ``material``.
    """
    if cut not in _CARAT_REF:
        raise ValueError(f"Unknown cut: {cut!r}")
    if dim_mm <= 0:
        raise ValueError("dim_mm must be positive")
    rho = _resolve_density(material, density_g_cm3)
    _ref_mm, exp = _CARAT_REF[cut]
    ref_mm = _effective_ref_mm(cut, rho)
    return (dim_mm / ref_mm) ** exp


def mm_from_carat(
    cut: str,
    carat: float,
    *,
    material: Optional[str] = None,
    density_g_cm3: Optional[float] = None,
) -> float:
    """Return the primary dimension in mm for a given carat weight.

    Inverse of carat_from_mm:
        dim_mm = ref_mm_material * carat ** (1 / exponent)

    Parameters
    ----------
    cut : str
        One of the GEMSTONE_CUTS keys.
    carat : float
        Stone weight in carats (>0).
    material : str, optional
        Material name (e.g. ``"ruby"``).  Looked up in GEMSTONE_DENSITIES.
    density_g_cm3 : float, optional
        Explicit density in g/cm³.  Overrides ``material``.
    """
    if cut not in _CARAT_REF:
        raise ValueError(f"Unknown cut: {cut!r}")
    if carat <= 0:
        raise ValueError("carat must be positive")
    rho = _resolve_density(material, density_g_cm3)
    _ref_mm, exp = _CARAT_REF[cut]
    ref_mm = _effective_ref_mm(cut, rho)
    return ref_mm * (carat ** (1.0 / exp))


# ---------------------------------------------------------------------------
# Industry-standard default proportions per cut
# ---------------------------------------------------------------------------

class GemProportions(NamedTuple):
    """All dimensions in mm (relative to the girdle diameter = 1 when normalised).
    Angles in degrees.
    """
    cut: str
    # Primary sizing
    diameter_mm: float          # girdle diameter (round) or long-axis (others)
    aspect_ratio: float         # width / long-axis  (1.0 for round/square)
    # Crown
    table_pct: float            # table width / girdle diameter, percent
    crown_angle_deg: float
    crown_height_pct: float     # crown height / diameter, percent
    # Pavilion
    pavilion_angle_deg: float
    pavilion_depth_pct: float   # pavilion depth / diameter, percent
    # Girdle
    girdle_pct: float           # girdle thickness / diameter, percent
    # Derived
    total_depth_pct: float      # crown + girdle + pavilion
    # Cut-specific extras
    extras: dict


def gemstone_proportions(
    cut: str,
    diameter_mm: Optional[float] = None,
    carat: Optional[float] = None,
    *,
    # Optional overrides (None = use industry default)
    table_pct: Optional[float] = None,
    crown_angle_deg: Optional[float] = None,
    pavilion_angle_deg: Optional[float] = None,
    girdle_pct: Optional[float] = None,
    aspect_ratio: Optional[float] = None,
    # Material density for correct carat↔mm conversion
    material: Optional[str] = None,
    density_g_cm3: Optional[float] = None,
) -> GemProportions:
    """Return a GemProportions for the given cut + sizing.

    Exactly one of diameter_mm or carat must be provided.

    Parameters
    ----------
    cut : str
        One of the GEMSTONE_CUTS keys.
    diameter_mm : float, optional
        Primary dimension in mm.  Exclusive with ``carat``.
    carat : float, optional
        Stone weight in carats.  Converted to mm via carat formula.
    material : str, optional
        Material name for density lookup (e.g. ``"ruby"``).  Used only when
        ``carat`` is given.  Ignored if ``density_g_cm3`` is also supplied.
    density_g_cm3 : float, optional
        Explicit material density in g/cm³.  Overrides ``material``.
    """
    if cut not in GEMSTONE_CUTS:
        raise ValueError(f"Unknown cut {cut!r}. Valid: {sorted(GEMSTONE_CUTS)}")

    # Resolve sizing
    if diameter_mm is not None and carat is not None:
        raise ValueError("Provide diameter_mm OR carat, not both")
    if diameter_mm is None and carat is None:
        raise ValueError("One of diameter_mm or carat is required")
    if carat is not None:
        if carat <= 0:
            raise ValueError("carat must be positive")
        diameter_mm = mm_from_carat(cut, carat, material=material, density_g_cm3=density_g_cm3)
    if diameter_mm <= 0:
        raise ValueError("diameter_mm must be positive")

    # Industry defaults per cut
    _defaults = _CUT_DEFAULTS[cut]

    ta_pct    = table_pct         if table_pct         is not None else _defaults["table_pct"]
    ca_deg    = crown_angle_deg   if crown_angle_deg    is not None else _defaults["crown_angle_deg"]
    pa_deg    = pavilion_angle_deg if pavilion_angle_deg is not None else _defaults["pavilion_angle_deg"]
    gi_pct    = girdle_pct        if girdle_pct         is not None else _defaults["girdle_pct"]
    ar        = aspect_ratio      if aspect_ratio        is not None else _defaults.get("aspect_ratio", 1.0)

    # Compute derived heights (fraction of diameter).
    # When a cut has explicit crown_height_pct / pavilion_depth_pct in its
    # defaults those values take precedence; otherwise derive from angles.
    # Note: briolette has table_pct=0 (no table) — handled naturally.
    import math
    stored_ch = _defaults.get("crown_height_pct")
    crown_h_pct = (
        stored_ch if stored_ch is not None and stored_ch != 0
        else (1 - ta_pct / 100.0) / 2 * math.tan(math.radians(ca_deg)) * 100
    )
    stored_pd = _defaults.get("pavilion_depth_pct")
    pav_d_pct = (
        stored_pd if stored_pd is not None and stored_pd != 0
        else 0.5 * math.tan(math.radians(pa_deg)) * 100
    )
    gi_mm_pct = gi_pct
    total = crown_h_pct + gi_mm_pct + pav_d_pct

    return GemProportions(
        cut=cut,
        diameter_mm=diameter_mm,
        aspect_ratio=ar,
        table_pct=ta_pct,
        crown_angle_deg=ca_deg,
        crown_height_pct=crown_h_pct,
        pavilion_angle_deg=pa_deg,
        pavilion_depth_pct=pav_d_pct,
        girdle_pct=gi_mm_pct,
        total_depth_pct=total,
        extras=dict(_defaults.get("extras", {})),
    )


# Industry-standard defaults
_CUT_DEFAULTS: dict[str, dict] = {
    "round_brilliant": {
        "table_pct": 57.0,
        "crown_angle_deg": 34.5,
        "crown_height_pct": 16.2,
        "pavilion_angle_deg": 40.75,
        "pavilion_depth_pct": 43.1,
        "girdle_pct": 2.5,
        "aspect_ratio": 1.0,
        "extras": {"facet_count": 57, "culet": "none"},
    },
    "princess": {
        "table_pct": 75.0,
        "crown_angle_deg": 30.0,
        "crown_height_pct": 10.5,
        "pavilion_angle_deg": 42.0,
        "pavilion_depth_pct": 43.0,
        "girdle_pct": 2.0,
        "aspect_ratio": 1.0,
        "extras": {"facet_count": 57},
    },
    "oval": {
        "table_pct": 56.0,
        "crown_angle_deg": 34.5,
        "crown_height_pct": 15.0,
        "pavilion_angle_deg": 40.75,
        "pavilion_depth_pct": 43.0,
        "girdle_pct": 2.5,
        "aspect_ratio": 0.66,       # width = 0.66 × length (typical 1.35:1 L:W)
        "extras": {"facet_count": 57},
    },
    "emerald": {
        "table_pct": 60.0,
        "crown_angle_deg": 15.0,
        "crown_height_pct": 8.0,
        "pavilion_angle_deg": 45.0,
        "pavilion_depth_pct": 43.0,
        "girdle_pct": 2.0,
        "aspect_ratio": 0.71,       # width = 0.71 × length (standard ~1.4:1)
        "extras": {"step_rows": 3, "corner_cut_ratio": 0.15},
    },
    "marquise": {
        "table_pct": 56.0,
        "crown_angle_deg": 33.5,
        "crown_height_pct": 14.0,
        "pavilion_angle_deg": 41.0,
        "pavilion_depth_pct": 43.0,
        "girdle_pct": 2.5,
        "aspect_ratio": 0.50,       # width = 0.50 × length (~2:1 L:W)
        "extras": {"facet_count": 57},
    },
    "pear": {
        "table_pct": 55.0,
        "crown_angle_deg": 35.0,
        "crown_height_pct": 15.0,
        "pavilion_angle_deg": 41.0,
        "pavilion_depth_pct": 43.5,
        "girdle_pct": 2.5,
        "aspect_ratio": 0.62,       # width = 0.62 × length
        "extras": {"facet_count": 57},
    },
    "cushion": {
        "table_pct": 60.0,
        "crown_angle_deg": 35.0,
        "crown_height_pct": 14.0,
        "pavilion_angle_deg": 41.0,
        "pavilion_depth_pct": 43.5,
        "girdle_pct": 2.0,
        "aspect_ratio": 1.0,
        "extras": {"corner_radius_pct": 15},  # corner radius as % of side
    },
    # -----------------------------------------------------------------------
    # Fancy cuts (GIA/AGS industry standards; see module docstring for refs)
    # -----------------------------------------------------------------------
    "radiant": {
        # Cropped-corner rectangular modified brilliant.
        # GIA reference: table 62–70%, depth 61–67%, typical 1.0–1.5 L:W.
        "table_pct": 62.0,
        "crown_angle_deg": 32.0,
        "crown_height_pct": 13.0,
        "pavilion_angle_deg": 41.0,
        "pavilion_depth_pct": 43.0,
        "girdle_pct": 2.5,
        "aspect_ratio": 0.75,       # width = 0.75 × length (~1.33:1 L:W)
        "extras": {
            "corner_cut_ratio": 0.10,  # fraction of corner removed
            "facet_count": 70,         # typical radiant facet count
        },
    },
    "asscher": {
        # Square step cut with heavily cropped corners (deep high crown).
        # GIA reference: table 60–68%, depth 60–66%, 1:1 L:W.
        "table_pct": 60.0,
        "crown_angle_deg": 25.0,
        "crown_height_pct": 15.0,
        "pavilion_angle_deg": 43.0,
        "pavilion_depth_pct": 43.0,
        "girdle_pct": 2.0,
        "aspect_ratio": 1.0,
        "extras": {
            "step_rows": 3,
            "corner_cut_ratio": 0.20,   # deeper corner cuts than emerald
        },
    },
    "trillion": {
        # Equilateral triangular modified brilliant (also called triangular brilliant).
        # GIA reference: table 50–60%, depth 32–48%, equilateral (L:W ≈ 1:1).
        "table_pct": 55.0,
        "crown_angle_deg": 34.0,
        "crown_height_pct": 11.0,
        "pavilion_angle_deg": 41.0,
        "pavilion_depth_pct": 37.0,
        "girdle_pct": 2.5,
        "aspect_ratio": 1.0,    # equilateral triangle; "width" = same as "length"
        "extras": {
            "sides": 3,
            "facet_count": 43,  # standard trillion facet count
        },
    },
    "heart": {
        # Heart-shaped modified brilliant.
        # GIA reference: table 53–63%, depth 58–62%, L:W ratio 0.90–1.10.
        "table_pct": 56.0,
        "crown_angle_deg": 34.5,
        "crown_height_pct": 15.0,
        "pavilion_angle_deg": 40.75,
        "pavilion_depth_pct": 43.0,
        "girdle_pct": 2.5,
        "aspect_ratio": 0.98,   # slight width/length imbalance typical for heart
        "extras": {
            "cleft_depth_pct": 10,  # depth of the V-cleft as % of width
            "facet_count": 59,
        },
    },
    "baguette": {
        # Rectangular step cut (narrow bar); common in channel-set side stones.
        # GIA reference: table 60–75%, depth 42–50%, L:W typically 2.5:1 to 4:1.
        "table_pct": 70.0,
        "crown_angle_deg": 8.0,
        "crown_height_pct": 4.0,
        "pavilion_angle_deg": 43.0,
        "pavilion_depth_pct": 40.0,
        "girdle_pct": 1.5,
        "aspect_ratio": 0.33,   # width = 0.33 × length (3:1 L:W)
        "extras": {
            "step_rows": 2,
            "corner_cut_ratio": 0.0,    # straight (no corner cut); tapered baguette has corners cut
        },
    },
    "briolette": {
        # Elongated double-cone (teardrop) with all-facet surface; no table or girdle.
        # Dimensions: height (long axis) × width; typical aspect ~0.50 (2:1 H:W).
        # "crown" facets are the upper hemisphere; "pavilion" the lower point.
        "table_pct": 0.0,           # no table on a briolette
        "crown_angle_deg": 30.0,
        "crown_height_pct": 50.0,   # upper half
        "pavilion_angle_deg": 45.0,
        "pavilion_depth_pct": 50.0, # lower half / pointed end
        "girdle_pct": 2.0,          # thin equatorial band
        "aspect_ratio": 0.50,       # width = 0.50 × height (~2:1 H:W)
        "extras": {
            "facet_rows": 8,    # horizontal rows of triangular facets
        },
    },
}


# ---------------------------------------------------------------------------
# Feature node helpers
# ---------------------------------------------------------------------------

def _gemstone_node(
    node_id: str,
    cut: str,
    diameter_mm: float,
    props: GemProportions,
    position: Optional[list] = None,
    orientation_deg: Optional[list] = None,
    material: str = "diamond",
) -> dict:
    """Build the JSON feature node for a gemstone."""
    node: dict = {
        "id": node_id,
        "op": "gemstone",
        "cut": cut,
        "diameter_mm": diameter_mm,
        "aspect_ratio": props.aspect_ratio,
        "table_pct": props.table_pct,
        "crown_angle_deg": props.crown_angle_deg,
        "crown_height_pct": props.crown_height_pct,
        "pavilion_angle_deg": props.pavilion_angle_deg,
        "pavilion_depth_pct": props.pavilion_depth_pct,
        "girdle_pct": props.girdle_pct,
        "total_depth_pct": props.total_depth_pct,
        "material": material,
    }
    if props.extras:
        node["extras"] = props.extras
    if position is not None:
        node["position"] = position
    if orientation_deg is not None:
        node["orientation_deg"] = orientation_deg
    return node


# ---------------------------------------------------------------------------
# LLM tool: jewelry_create_gemstone
# ---------------------------------------------------------------------------

jewelry_create_gemstone_spec = ToolSpec(
    name="jewelry_create_gemstone",
    description=(
        "Append a `gemstone` node to a `.feature` file. "
        "Generates a parametric gemstone solid with industry-standard proportions. "
        "Supported cuts: round_brilliant, princess, oval, emerald, marquise, pear, cushion, "
        "radiant, asscher, trillion, heart, baguette, briolette. "
        "Size the stone by carat OR by diameter_mm (long axis for non-round cuts). "
        "Carat formula: carat = (diameter_mm / ref_mm)^3 where ref_mm is calibrated per cut "
        "and material density (default: diamond, 3.51 g/cm³). "
        "Pass material='ruby' (or density_g_cm3=4.00) for accurate coloured-stone carat weights. "
        "The gemstone node stores proportions used by the OCCT "
        "worker to build a closed solid (pavilion cone + girdle cylinder + crown prism). "
        "Use jewelry_cut_gem_seat to cut the matching seat from a ring shank or bezel."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "file_id": {
                "type": "string",
                "description": "Target .feature file id (uuid).",
            },
            "cut": {
                "type": "string",
                "enum": sorted(GEMSTONE_CUTS),
                "description": (
                    "Gemstone cut style. "
                    "round_brilliant=57 facets, princess=square brilliant, oval=elliptical brilliant, "
                    "emerald=rectangular step cut, marquise=boat, pear=teardrop, cushion=soft square, "
                    "radiant=cropped-corner rectangular brilliant, asscher=square step cut, "
                    "trillion=triangular brilliant, heart=heart-shaped brilliant, "
                    "baguette=narrow rectangular step cut, briolette=all-facet elongated teardrop."
                ),
            },
            "carat": {
                "type": "number",
                "description": (
                    "Stone weight in carats. Converted to mm via the carat formula. "
                    "Provide carat OR diameter_mm, not both. "
                    "For coloured stones supply material or density_g_cm3 for accuracy."
                ),
            },
            "diameter_mm": {
                "type": "number",
                "description": (
                    "Primary dimension in mm: girdle diameter (round brilliant) or "
                    "long axis (all other cuts). Provide diameter_mm OR carat, not both."
                ),
            },
            "material": {
                "type": "string",
                "description": (
                    "Stone material name, e.g. 'diamond', 'ruby', 'sapphire', 'emerald', "
                    "'amethyst', 'topaz', 'garnet', 'aquamarine', 'citrine', 'peridot', "
                    "'tanzanite', 'opal'. Used for density lookup (carat↔mm). Default: 'diamond'."
                ),
            },
            "density_g_cm3": {
                "type": "number",
                "description": (
                    "Explicit material density in g/cm³. Overrides material lookup. "
                    "Use this for unusual stones not in the built-in density table."
                ),
            },
            "position": {
                "type": "array",
                "items": {"type": "number"},
                "description": "[x, y, z] placement in model space (mm). Default: [0, 0, 0].",
            },
            "orientation_deg": {
                "type": "array",
                "items": {"type": "number"},
                "description": "[rx, ry, rz] Euler angles in degrees. Default: [0, 0, 0].",
            },
            "table_pct": {"type": "number", "description": "Table width override (% of diameter). Optional."},
            "crown_angle_deg": {"type": "number", "description": "Crown angle override (degrees). Optional."},
            "pavilion_angle_deg": {"type": "number", "description": "Pavilion angle override (degrees). Optional."},
            "girdle_pct": {"type": "number", "description": "Girdle thickness override (% of diameter). Optional."},
            "aspect_ratio": {
                "type": "number",
                "description": "Width/length ratio override. 1.0=square/round. Default per cut.",
            },
            "id": {"type": "string", "description": "Optional explicit node id."},
        },
        "required": ["file_id", "cut"],
    },
)


@register(jewelry_create_gemstone_spec, write=True)
async def run_jewelry_create_gemstone(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as e:
        return err_payload(f"invalid args: {e}", "BAD_ARGS")

    file_id_str     = a.get("file_id", "").strip()
    cut             = a.get("cut", "").strip()
    carat           = a.get("carat", None)
    diameter_mm     = a.get("diameter_mm", None)
    material        = a.get("material", "diamond")
    density_g_cm3   = a.get("density_g_cm3", None)
    position        = a.get("position", None)
    orientation_deg = a.get("orientation_deg", None)
    node_id         = a.get("id", "").strip()

    prop_overrides = {
        k: a.get(k)
        for k in ("table_pct", "crown_angle_deg", "pavilion_angle_deg", "girdle_pct", "aspect_ratio")
        if a.get(k) is not None
    }

    # Validate required fields
    if not file_id_str:
        return err_payload("file_id is required", "BAD_ARGS")
    if not cut:
        return err_payload("cut is required", "BAD_ARGS")
    if cut not in GEMSTONE_CUTS:
        return err_payload(
            f"Unknown cut {cut!r}. Valid cuts: {sorted(GEMSTONE_CUTS)}", "BAD_ARGS"
        )

    if carat is not None and diameter_mm is not None:
        return err_payload("Provide carat OR diameter_mm, not both", "BAD_ARGS")
    if carat is None and diameter_mm is None:
        return err_payload("One of carat or diameter_mm is required", "BAD_ARGS")

    if carat is not None:
        try:
            carat = float(carat)
        except Exception:
            return err_payload("carat must be a number", "BAD_ARGS")
        if carat <= 0:
            return err_payload("carat must be positive", "BAD_ARGS")

    if diameter_mm is not None:
        try:
            diameter_mm = float(diameter_mm)
        except Exception:
            return err_payload("diameter_mm must be a number", "BAD_ARGS")
        if diameter_mm <= 0:
            return err_payload("diameter_mm must be positive", "BAD_ARGS")

    # Validate numeric overrides
    for key in ("table_pct", "crown_angle_deg", "pavilion_angle_deg", "girdle_pct"):
        val = prop_overrides.get(key)
        if val is not None:
            try:
                prop_overrides[key] = float(val)
            except Exception:
                return err_payload(f"{key} must be a number", "BAD_ARGS")
            if prop_overrides[key] <= 0:
                return err_payload(f"{key} must be positive", "BAD_ARGS")

    ar = prop_overrides.get("aspect_ratio")
    if ar is not None:
        try:
            prop_overrides["aspect_ratio"] = float(ar)
        except Exception:
            return err_payload("aspect_ratio must be a number", "BAD_ARGS")
        if prop_overrides["aspect_ratio"] <= 0:
            return err_payload("aspect_ratio must be positive", "BAD_ARGS")

    if density_g_cm3 is not None:
        try:
            density_g_cm3 = float(density_g_cm3)
        except Exception:
            return err_payload("density_g_cm3 must be a number", "BAD_ARGS")
        if density_g_cm3 <= 0:
            return err_payload("density_g_cm3 must be positive", "BAD_ARGS")

    try:
        fid = uuid.UUID(file_id_str)
    except Exception:
        return err_payload("file_id must be a uuid", "BAD_ARGS")

    content, err = read_feature_content(ctx, fid)
    if err:
        return err_payload(f"file not found: {err}", "NOT_FOUND")

    # Resolve proportions (pass material + density for correct carat→mm sizing)
    try:
        props = gemstone_proportions(
            cut,
            diameter_mm=diameter_mm,
            carat=carat,
            material=str(material) if material else None,
            density_g_cm3=density_g_cm3,
            **prop_overrides,
        )
    except ValueError as e:
        return err_payload(str(e), "BAD_ARGS")

    if not node_id:
        node_id = next_node_id(content, "gemstone")

    node = _gemstone_node(
        node_id,
        cut,
        props.diameter_mm,
        props,
        position=position,
        orientation_deg=orientation_deg,
        material=str(material) if material else "diamond",
    )

    _name, nid, err2 = append_feature_node(ctx, fid, node)
    if err2:
        return err_payload(err2, "ERROR")

    # carat_approx uses the same material density so the value is accurate
    mat_label = str(material) if material else None
    return ok_payload({
        "file_id": file_id_str,
        "id": nid,
        "op": "gemstone",
        "cut": cut,
        "diameter_mm": props.diameter_mm,
        "carat_approx": round(
            carat_from_mm(cut, props.diameter_mm, material=mat_label, density_g_cm3=density_g_cm3),
            3,
        ),
        "total_depth_mm": round(props.total_depth_pct / 100 * props.diameter_mm, 3),
    })
