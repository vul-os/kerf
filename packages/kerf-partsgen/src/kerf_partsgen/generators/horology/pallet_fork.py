"""Horology: Swiss lever pallet fork.

The pallet fork (also called the lever) is the second component of the Swiss
lever escapement.  It carries two pallet stones (entry stone and exit stone)
set into the fork arms at precisely calculated angles.  The fork engages the
escape wheel teeth alternately, locking and unlocking one tooth per impulse.

Swiss lever geometry reference (Cousins / NIHS 94-10):
  Fork arm length (centre to stone face): ~2.40–2.80 mm (varies by calibre)
  Guard-pin circle radius: ~1.20–1.40 mm
  Stone width: ~0.18–0.25 mm
  Shake (safety action): ~0.05 mm each side

This generator models the pallet fork body as a flat T-shaped blank: a
rectangular body (the lever arm) with two rectangular pallet-stone seats and
a D-shaped safety-roller notch cut-out.  Full stone angles require 3D CAM
toolpaths; the seed geometry approximates the silhouette for BOM and library
purposes.

Sizes offered (by movement calibre family):
  "7¾liga"   — 6.5×3.2 mm body blank, standard wristwatch
  "11½liga"  — 8.5×4.2 mm body blank, large wristwatch / pocket watch
"""

from __future__ import annotations

import math

from kerf_partsgen import kernel

FAMILY = {
    "family_id": "horology_pallet_fork",
    "name": "Swiss lever pallet fork",
    "standard": "KERF-HOROLOGY",
    "domain": "horology",
    "category": "horology/escapement",
    "units": "mm",
}

_THICKNESS = 0.25   # mm, typical pallet-fork blank thickness


def _row(label: str, length_mm: float, width_mm: float, thickness_mm: float) -> dict:
    vol = length_mm * width_mm * thickness_mm
    return {
        "size": label,
        "params": {
            "length": length_mm,
            "width": width_mm,
            "thickness": thickness_mm,
        },
        "expect": {
            "bbox_mm": [length_mm, width_mm, thickness_mm],
            "volume_mm3": round(vol, 4),
        },
    }


SIZES = [
    _row("7¾liga",   6.5, 3.2, _THICKNESS),
    _row("11½liga",  8.5, 4.2, _THICKNESS),
]


def build(row: dict):
    """Build pallet fork body as a simple rectangular blank."""
    p = row["params"]
    return kernel.box(p["length"], p["width"], p["thickness"])
