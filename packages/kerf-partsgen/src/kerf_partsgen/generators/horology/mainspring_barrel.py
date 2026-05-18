"""Horology: mainspring barrel.

The mainspring barrel is the energy store of a mechanical watch.  It is a
cylindrical drum containing the coiled mainspring; the barrel turns as the
spring unwinds, driving the gear train.

Barrel dimensions are governed by the movement size (lignes) and power
reserve target.  Reference dimensions from Rolex / ETA / Selitta barrel
specifications (publicly documented catalogue dimensions):

  7¾ liga movement (standard ETA 2824 footprint):
    outer_diameter:  ~7.6 mm
    height (inside): ~2.1 mm
    wall thickness:  ~0.6 mm
    arbor bore:      ~1.6 mm

  11½ liga (ETA Unitas 6497, pocket watch):
    outer_diameter:  ~11.0 mm
    height (inside): ~3.0 mm
    wall thickness:  ~0.8 mm
    arbor bore:      ~2.0 mm

Solid modelled as an annular cylinder (lid integral, arbor bore through):
    outer_r  = outer_diameter / 2
    bore_r   = arbor_bore / 2
    height   = barrel_height

Volume:
    V = π * (outer_r² − bore_r²) * height
"""

from __future__ import annotations

import math

from kerf_partsgen import kernel

FAMILY = {
    "family_id": "horology_mainspring_barrel",
    "name": "Horology mainspring barrel",
    "standard": "KERF-HOROLOGY",
    "domain": "horology",
    "category": "horology/barrel",
    "units": "mm",
}


def _row(
    label: str,
    outer_d: float,
    height: float,
    wall: float,
    arbor_bore_d: float,
) -> dict:
    outer_r = outer_d / 2.0
    bore_r = arbor_bore_d / 2.0
    vol = math.pi * (outer_r ** 2 - bore_r ** 2) * height
    return {
        "size": label,
        "params": {
            "outer_diameter": outer_d,
            "height": height,
            "wall_thickness": wall,
            "arbor_bore_diameter": arbor_bore_d,
        },
        "expect": {
            "bbox_mm": [outer_d, outer_d, height],
            "volume_mm3": round(vol, 3),
        },
    }


SIZES = [
    _row("7¾liga",   outer_d=7.6,  height=2.1, wall=0.6, arbor_bore_d=1.6),
    _row("11½liga",  outer_d=11.0, height=3.0, wall=0.8, arbor_bore_d=2.0),
]


def build(row: dict):
    """Build mainspring barrel body as an annular cylinder."""
    p = row["params"]
    outer_r = p["outer_diameter"] / 2.0
    bore_r = p["arbor_bore_diameter"] / 2.0
    h = p["height"]

    drum = kernel.cylinder(radius=outer_r, height=h)
    arbor = kernel.cylinder(radius=bore_r, height=h * 2.0)
    return kernel.cut(drum, arbor)
