"""Horology: gear-train wheel and pinion.

A mechanical watch gear train steps down from the mainspring barrel (slow,
high-torque) to the escapement (fast, low-torque) through 3–5 wheel-pinion
pairs.  Each pair consists of a large wheel (many teeth) driving a small
pinion (few leaves / teeth).

Standard Swiss three-train nomenclature:
  Third wheel (3rd):  drives from the centre wheel
  Fourth wheel (4th): drives from the third wheel, carries seconds hand
  Escape pinion:      driven by the fourth wheel, meshes with escape wheel

This generator produces a solid disc + hub representing a single gear-train
wheel blank.  Tooth form is not cut (same rationale as escape_wheel —
requires CNC/EDM); the blank captures pitch diameter, thickness, and hub
bore for BOM / library purposes.

Gear-train wheel parameters follow DIN 58400 (fine-mechanics module series):
  Module m ∈ {0.06, 0.08, 0.10, 0.12, 0.15, 0.20, 0.25} mm

Sizes offered (representative wristwatch + pocket watch wheels):
  "m0.10z72"  — m=0.10, z=72 (third wheel, wristwatch)
  "m0.10z64"  — m=0.10, z=64 (fourth wheel, wristwatch)
  "m0.15z90"  — m=0.15, z=90 (third wheel, pocket watch)
  "m0.20z80"  — m=0.20, z=80 (barrel wheel, pocket watch)
"""

from __future__ import annotations

import math

from kerf_partsgen import kernel

FAMILY = {
    "family_id": "horology_gear_train_wheel",
    "name": "Horology gear-train wheel",
    "standard": "KERF-HOROLOGY / DIN 58400",
    "domain": "horology",
    "category": "horology/gear_train",
    "units": "mm",
}

_THICKNESS = 0.20   # mm, typical gear blank thickness (wristwatch)
_POCKET_THICKNESS = 0.40   # mm, pocket watch


def _row(label: str, module: float, num_teeth: int, thickness_mm: float) -> dict:
    pitch_d = module * num_teeth
    tip_d = pitch_d + 2.0 * module     # addendum = 1 module
    bore_d = pitch_d * 0.25            # collet/bore ~ 25% of pitch diameter
    outer_r = tip_d / 2.0
    bore_r = bore_d / 2.0
    vol = math.pi * (outer_r ** 2 - bore_r ** 2) * thickness_mm
    return {
        "size": label,
        "params": {
            "module": module,
            "num_teeth": num_teeth,
            "pitch_diameter": round(pitch_d, 4),
            "tip_diameter": round(tip_d, 4),
            "bore_diameter": round(bore_d, 4),
            "thickness": thickness_mm,
        },
        "expect": {
            "bbox_mm": [round(tip_d, 4), round(tip_d, 4), thickness_mm],
            "volume_mm3": round(vol, 4),
        },
    }


SIZES = [
    _row("m0.10z72", 0.10, 72, _THICKNESS),
    _row("m0.10z64", 0.10, 64, _THICKNESS),
    _row("m0.15z90", 0.15, 90, _POCKET_THICKNESS),
    _row("m0.20z80", 0.20, 80, _POCKET_THICKNESS),
]


def build(row: dict):
    """Build gear wheel blank: annular disc (tip-circle minus bore)."""
    p = row["params"]
    outer_r = p["tip_diameter"] / 2.0
    bore_r = p["bore_diameter"] / 2.0
    t = p["thickness"]

    disc = kernel.cylinder(radius=outer_r, height=t)
    bore = kernel.cylinder(radius=bore_r, height=t * 2.0)
    return kernel.cut(disc, bore)
