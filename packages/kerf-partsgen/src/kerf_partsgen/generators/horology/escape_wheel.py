"""Horology: Swiss lever escape wheel.

The Swiss lever escapement escape wheel is the heart of a mechanical watch.
It has 15 teeth (the universal Swiss standard for 3 Hz / 21 600 bph movements)
with a specific tooth form: unlike standard involute gears, the escape wheel
uses a *club-tooth* (also called *ratchet-tooth*) profile — a near-radial
locking face on the entry side and a curved impulse face on the exit side.

This generator approximates the tooth profile using the involute-based
geometry from :mod:`kerf_partsgen.generators.horology.involute` with a
small module appropriate for a wristwatch (module ≈ 0.095–0.12 mm).

Reference dimensions (Cousins / Ronda escapement data, Swiss Lever, 7¾ liga):
  teeth:          15
  diameter (OD):  ~3.85 mm  (varies by ébauche — 7¾ liga is most common)
  tooth height:   ~0.20 mm
  module:         diameter / teeth ≈ 0.095 mm (normalised to module = 0.10 mm
                  for a clean reference row)

Sizes offered:
  "5¾liga"  — small (ladies): OD 2.90 mm, 15 teeth, m = 0.0965
  "7¾liga"  — standard (men):  OD 3.85 mm, 15 teeth, m = 0.128
  "11½liga" — large (pocket):  OD 5.20 mm, 15 teeth, m = 0.173

For the partsgen pipeline the solid is modelled as a flat disc (escape wheel
blank) — the exact tooth form requires specialised OCCT toolpaths that are
out of scope for the seed geometry.  The tooth-profile validation is done
analytically in :func:`check_involute_profile` (see ``involute.py``).

Volume formula (solid disc approximation for BOM / weight estimation):
    V = π * r_tip² * thickness

Geometry (disc with central bore, built from kernel):
    outer_r  = OD / 2
    bore_r   = outer_r * 0.35   (collet seat ratio)
    thickness = 0.18 mm  (typical heat-treated steel blank)
"""

from __future__ import annotations

import math

from kerf_partsgen import kernel

FAMILY = {
    "family_id": "horology_escape_wheel",
    "name": "Swiss lever escape wheel",
    "standard": "KERF-HOROLOGY",
    "domain": "horology",
    "category": "horology/escapement",
    "units": "mm",
}

# Swiss lever escape wheel lignes → mm: 1 ligne = 2.2558 mm
_THICKNESS = 0.18   # heat-treated steel blank, mm


def _row(label: str, od_mm: float, num_teeth: int, thickness_mm: float) -> dict:
    r_tip = od_mm / 2.0
    bore_r = r_tip * 0.35
    vol = math.pi * (r_tip ** 2 - bore_r ** 2) * thickness_mm
    return {
        "size": label,
        "params": {
            "outer_diameter": round(od_mm, 3),
            "num_teeth": num_teeth,
            "thickness": thickness_mm,
            "bore_diameter": round(bore_r * 2.0, 3),
            "module": round(od_mm / num_teeth, 4),
        },
        "expect": {
            "bbox_mm": [round(od_mm, 3), round(od_mm, 3), thickness_mm],
            "volume_mm3": round(vol, 4),
        },
    }


SIZES = [
    _row("5¾liga",   2.90,  15, _THICKNESS),
    _row("7¾liga",   3.85,  15, _THICKNESS),
    _row("11½liga",  5.20,  15, _THICKNESS),
]


def build(row: dict):
    """Build escape wheel blank: annular disc (outer disc minus bore)."""
    p = row["params"]
    outer_r = p["outer_diameter"] / 2.0
    bore_r = p["bore_diameter"] / 2.0
    t = p["thickness"]

    disc = kernel.cylinder(radius=outer_r, height=t)
    bore = kernel.cylinder(radius=bore_r, height=t * 2.0)
    return kernel.cut(disc, bore)
