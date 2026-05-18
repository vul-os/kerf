"""Jewelry: plain round bangle (annular band).

Original MIT generator (human-written).  A bangle is a rigid closed hoop
worn on the wrist; this family covers the plain / unadorned band variant
used as a sizing and weight reference in jewelry CAD.

Sizes are the four industry-standard wrist sizes S/M/L/XL sourced from
the Pandora / Rio Grande bracelet-sizing guides (inner circumference
midpoints) and a nominal band width + wall thickness consistent with a
solid 3 mm round-wire section.  Dimensions are uncopyrightable facts.

Geometry
--------
A bangle band is modelled as an annular disc: an outer cylinder with the
bore cut out, built entirely from the Kerf OCCT kernel facade
(cylinder + boolean cut).

    outer_diameter = inner_diameter + 2 * wall_thickness
    height         = band_width  (axial dimension = ring height)

    disc  = cylinder(outer_diameter / 2, height)
    bore  = cylinder(inner_diameter / 2, height)   # slightly oversized
    solid = cut(disc, bore)

This is the same formulation as ISO 7089 flat washer (proven reference
generator) applied to jewelry-domain parameters.

Volume (annular cylinder, exact):
    V = π * ((outer_r)² − (inner_r)²) * height
"""

from __future__ import annotations

import math

from kerf_partsgen import kernel

FAMILY = {
    "family_id": "jewelry_plain_bangle",
    "name": "Jewelry plain round bangle",
    "standard": "KERF-JEWELRY",
    "domain": "jewelry",
    "category": "jewelry/bracelets",
    "units": "mm",
}

# ---------------------------------------------------------------------------
# Dimension table — uncopyrightable industry midpoints
# ---------------------------------------------------------------------------
# Size label, inner_circumference_mm, band_width_mm, wall_thickness_mm.
# inner_diameter = inner_circumference / π.
# outer_diameter = inner_diameter + 2 * wall_thickness.
# Wrist size circumferences: S 155 mm, M 165 mm, L 175 mm, XL 185 mm
# (Pandora / Rio Grande bracelet sizing guide midpoints).
# Band width 6 mm, wall 3 mm — typical round-wire bangle proportions.


def _row(label: str, inner_circ_mm: float, band_width_mm: float, wall_mm: float) -> dict:
    inner_d = inner_circ_mm / math.pi
    outer_d = inner_d + 2.0 * wall_mm
    inner_r = inner_d / 2.0
    outer_r = outer_d / 2.0
    vol = math.pi * (outer_r ** 2 - inner_r ** 2) * band_width_mm
    return {
        "size": label,
        "params": {
            "inner_diameter": round(inner_d, 3),
            "outer_diameter": round(outer_d, 3),
            "band_width": band_width_mm,
            "wall_thickness": wall_mm,
            "inner_circumference": inner_circ_mm,
        },
        "expect": {
            "bbox_mm": [round(outer_d, 3), round(outer_d, 3), band_width_mm],
            "volume_mm3": round(vol, 2),
        },
    }


SIZES = [
    _row("S",  155.0, 6.0, 3.0),
    _row("M",  165.0, 6.0, 3.0),
    _row("L",  175.0, 6.0, 3.0),
    _row("XL", 185.0, 6.0, 3.0),
]


def build(row: dict):
    """Build the annular bangle solid by boolean-cutting the bore from the disc."""
    p = row["params"]
    outer_r = p["outer_diameter"] / 2.0
    inner_r = p["inner_diameter"] / 2.0
    height = p["band_width"]

    disc = kernel.cylinder(radius=outer_r, height=height)
    bore = kernel.cylinder(radius=inner_r, height=height * 2.0)
    return kernel.cut(disc, bore)
