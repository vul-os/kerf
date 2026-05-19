"""Aerospace fasteners catalogue.

Each entry is a dict with keys:
    spec          : str  — part-number / spec (e.g. "HL18PB-6-8")
    mfr           : str  — manufacturer / standard body
    diameter_in   : float — nominal shank diameter, inches
    length_in     : float — nominal length (grip + protrusion), inches
    head_style    : str  — e.g. "protruding", "countersunk", "flat", "pan"
    material      : str  — e.g. "titanium", "alloy-steel", "a286", "aluminum"
    grip_range    : tuple[float,float] — (min_grip_in, max_grip_in)
    shear_kip     : float — ultimate shear allowable, kip
    tension_kip   : float — ultimate tension allowable, kip
    finish        : str  — surface treatment

Sources / references
--------------------
Hi-Lok data: IFI / Hi-Shear Corp dimensional tables (HL10, HL11, HL18, HL19).
NAS6203..NAS6210: NAS (National Aerospace Standard) tables, Grade 160.
MS27039, MS9395, MS21250: MS (Military Standard) fastener tables.
AS3219..AS3243: AS (Aerospace Standard, SAE) rivet/fastener tables.
Cherry / CherryMAX: Cherry Aerospace product data sheets.
Huck-Lok / Huck BOM: Huck International / Arconic Fastening product data.
Tinnerman: Tinnerman Palnut fastening systems catalogue.

All allowables are published or conservatively interpolated design values.
Shear based on double-shear / 2 unless noted; divide by 2 for single-shear.
1 kip = 1000 lbf.
"""

from __future__ import annotations

from typing import Any

# ---------------------------------------------------------------------------
# Required field names — used by validators
# ---------------------------------------------------------------------------
REQUIRED_FIELDS: tuple[str, ...] = (
    "spec",
    "mfr",
    "diameter_in",
    "length_in",
    "head_style",
    "material",
    "grip_range",
    "shear_kip",
    "tension_kip",
    "finish",
)

# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _f(
    spec: str,
    mfr: str,
    dia: float,
    length: float,
    head: str,
    mat: str,
    grip_min: float,
    grip_max: float,
    shear: float,
    tension: float,
    finish: str,
) -> dict[str, Any]:
    return {
        "spec": spec,
        "mfr": mfr,
        "diameter_in": dia,
        "length_in": length,
        "head_style": head,
        "material": mat,
        "grip_range": (grip_min, grip_max),
        "shear_kip": shear,
        "tension_kip": tension,
        "finish": finish,
    }


# ---------------------------------------------------------------------------
# Hi-Lok HL18 — titanium protruding-head pin + collar, 100-ksi shear
# Diameter code: 4=1/4", 5=5/16", 6=3/8"  (also -3=3/16", -5=5/16", etc.)
# Grip code: 1/16" increments
# Diameters covered: 1/8"(2), 3/16"(3), 1/4"(4), 5/16"(5), 3/8"(6)
# ---------------------------------------------------------------------------
_HL18 = [
    # 1/8" (code -2)
    _f("HL18PB-2-2", "Hi-Shear", 0.125, 0.375, "protruding", "titanium", 0.063, 0.125, 1.23, 1.35, "none"),
    _f("HL18PB-2-4", "Hi-Shear", 0.125, 0.500, "protruding", "titanium", 0.188, 0.250, 1.23, 1.35, "none"),
    _f("HL18PB-2-6", "Hi-Shear", 0.125, 0.625, "protruding", "titanium", 0.313, 0.375, 1.23, 1.35, "none"),
    _f("HL18PB-2-8", "Hi-Shear", 0.125, 0.750, "protruding", "titanium", 0.438, 0.500, 1.23, 1.35, "none"),
    # 3/16" (code -3)
    _f("HL18PB-3-4", "Hi-Shear", 0.1875, 0.500, "protruding", "titanium", 0.188, 0.250, 2.52, 2.86, "none"),
    _f("HL18PB-3-6", "Hi-Shear", 0.1875, 0.625, "protruding", "titanium", 0.313, 0.375, 2.52, 2.86, "none"),
    _f("HL18PB-3-8", "Hi-Shear", 0.1875, 0.750, "protruding", "titanium", 0.438, 0.500, 2.52, 2.86, "none"),
    _f("HL18PB-3-10", "Hi-Shear", 0.1875, 0.875, "protruding", "titanium", 0.563, 0.625, 2.52, 2.86, "none"),
    # 1/4" (code -4)
    _f("HL18PB-4-4", "Hi-Shear", 0.250, 0.500, "protruding", "titanium", 0.188, 0.250, 4.42, 5.10, "none"),
    _f("HL18PB-4-6", "Hi-Shear", 0.250, 0.625, "protruding", "titanium", 0.313, 0.375, 4.42, 5.10, "none"),
    _f("HL18PB-4-8", "Hi-Shear", 0.250, 0.750, "protruding", "titanium", 0.438, 0.500, 4.42, 5.10, "none"),
    _f("HL18PB-4-10", "Hi-Shear", 0.250, 0.875, "protruding", "titanium", 0.563, 0.625, 4.42, 5.10, "none"),
    _f("HL18PB-4-12", "Hi-Shear", 0.250, 1.000, "protruding", "titanium", 0.688, 0.750, 4.42, 5.10, "none"),
    # 5/16" (code -5)
    _f("HL18PB-5-6", "Hi-Shear", 0.3125, 0.625, "protruding", "titanium", 0.313, 0.375, 6.80, 7.90, "none"),
    _f("HL18PB-5-8", "Hi-Shear", 0.3125, 0.750, "protruding", "titanium", 0.438, 0.500, 6.80, 7.90, "none"),
    _f("HL18PB-5-10", "Hi-Shear", 0.3125, 0.875, "protruding", "titanium", 0.563, 0.625, 6.80, 7.90, "none"),
    _f("HL18PB-5-12", "Hi-Shear", 0.3125, 1.000, "protruding", "titanium", 0.688, 0.750, 6.80, 7.90, "none"),
    _f("HL18PB-5-16", "Hi-Shear", 0.3125, 1.250, "protruding", "titanium", 0.938, 1.000, 6.80, 7.90, "none"),
    # 3/8" (code -6)
    _f("HL18PB-6-8", "Hi-Shear", 0.375, 0.750, "protruding", "titanium", 0.438, 0.500, 9.70, 11.40, "none"),
    _f("HL18PB-6-10", "Hi-Shear", 0.375, 0.875, "protruding", "titanium", 0.563, 0.625, 9.70, 11.40, "none"),
    _f("HL18PB-6-12", "Hi-Shear", 0.375, 1.000, "protruding", "titanium", 0.688, 0.750, 9.70, 11.40, "none"),
    _f("HL18PB-6-16", "Hi-Shear", 0.375, 1.250, "protruding", "titanium", 0.938, 1.000, 9.70, 11.40, "none"),
    _f("HL18PB-6-20", "Hi-Shear", 0.375, 1.500, "protruding", "titanium", 1.188, 1.250, 9.70, 11.40, "none"),
]

# ---------------------------------------------------------------------------
# Hi-Lok HL19 — titanium 100° countersunk-head pin + collar
# ---------------------------------------------------------------------------
_HL19 = [
    # 1/8" (code -2)
    _f("HL19PB-2-4", "Hi-Shear", 0.125, 0.500, "countersunk", "titanium", 0.188, 0.250, 1.23, 1.08, "none"),
    _f("HL19PB-2-6", "Hi-Shear", 0.125, 0.625, "countersunk", "titanium", 0.313, 0.375, 1.23, 1.08, "none"),
    _f("HL19PB-2-8", "Hi-Shear", 0.125, 0.750, "countersunk", "titanium", 0.438, 0.500, 1.23, 1.08, "none"),
    # 3/16" (code -3)
    _f("HL19PB-3-4", "Hi-Shear", 0.1875, 0.500, "countersunk", "titanium", 0.188, 0.250, 2.52, 2.30, "none"),
    _f("HL19PB-3-6", "Hi-Shear", 0.1875, 0.625, "countersunk", "titanium", 0.313, 0.375, 2.52, 2.30, "none"),
    _f("HL19PB-3-8", "Hi-Shear", 0.1875, 0.750, "countersunk", "titanium", 0.438, 0.500, 2.52, 2.30, "none"),
    # 1/4" (code -4)
    _f("HL19PB-4-4", "Hi-Shear", 0.250, 0.500, "countersunk", "titanium", 0.188, 0.250, 4.42, 4.10, "none"),
    _f("HL19PB-4-6", "Hi-Shear", 0.250, 0.625, "countersunk", "titanium", 0.313, 0.375, 4.42, 4.10, "none"),
    _f("HL19PB-4-8", "Hi-Shear", 0.250, 0.750, "countersunk", "titanium", 0.438, 0.500, 4.42, 4.10, "none"),
    _f("HL19PB-4-12", "Hi-Shear", 0.250, 1.000, "countersunk", "titanium", 0.688, 0.750, 4.42, 4.10, "none"),
    # 5/16" (code -5)
    _f("HL19PB-5-6", "Hi-Shear", 0.3125, 0.625, "countersunk", "titanium", 0.313, 0.375, 6.80, 6.40, "none"),
    _f("HL19PB-5-8", "Hi-Shear", 0.3125, 0.750, "countersunk", "titanium", 0.438, 0.500, 6.80, 6.40, "none"),
    _f("HL19PB-5-12", "Hi-Shear", 0.3125, 1.000, "countersunk", "titanium", 0.688, 0.750, 6.80, 6.40, "none"),
    # 3/8" (code -6)
    _f("HL19PB-6-8", "Hi-Shear", 0.375, 0.750, "countersunk", "titanium", 0.438, 0.500, 9.70, 9.20, "none"),
    _f("HL19PB-6-12", "Hi-Shear", 0.375, 1.000, "countersunk", "titanium", 0.688, 0.750, 9.70, 9.20, "none"),
    _f("HL19PB-6-16", "Hi-Shear", 0.375, 1.250, "countersunk", "titanium", 0.938, 1.000, 9.70, 9.20, "none"),
]

# ---------------------------------------------------------------------------
# Hi-Lok HL10 — alloy-steel protruding-head pin + collar (160-ksi)
# ---------------------------------------------------------------------------
_HL10 = [
    _f("HL10PB-3-4", "Hi-Shear", 0.1875, 0.500, "protruding", "alloy-steel", 0.188, 0.250, 3.70, 4.20, "cadmium"),
    _f("HL10PB-3-6", "Hi-Shear", 0.1875, 0.625, "protruding", "alloy-steel", 0.313, 0.375, 3.70, 4.20, "cadmium"),
    _f("HL10PB-3-8", "Hi-Shear", 0.1875, 0.750, "protruding", "alloy-steel", 0.438, 0.500, 3.70, 4.20, "cadmium"),
    _f("HL10PB-4-4", "Hi-Shear", 0.250, 0.500, "protruding", "alloy-steel", 0.188, 0.250, 6.50, 7.50, "cadmium"),
    _f("HL10PB-4-6", "Hi-Shear", 0.250, 0.625, "protruding", "alloy-steel", 0.313, 0.375, 6.50, 7.50, "cadmium"),
    _f("HL10PB-4-8", "Hi-Shear", 0.250, 0.750, "protruding", "alloy-steel", 0.438, 0.500, 6.50, 7.50, "cadmium"),
    _f("HL10PB-4-12", "Hi-Shear", 0.250, 1.000, "protruding", "alloy-steel", 0.688, 0.750, 6.50, 7.50, "cadmium"),
    _f("HL10PB-5-6", "Hi-Shear", 0.3125, 0.625, "protruding", "alloy-steel", 0.313, 0.375, 10.10, 11.70, "cadmium"),
    _f("HL10PB-5-8", "Hi-Shear", 0.3125, 0.750, "protruding", "alloy-steel", 0.438, 0.500, 10.10, 11.70, "cadmium"),
    _f("HL10PB-5-12", "Hi-Shear", 0.3125, 1.000, "protruding", "alloy-steel", 0.688, 0.750, 10.10, 11.70, "cadmium"),
    _f("HL10PB-6-8", "Hi-Shear", 0.375, 0.750, "protruding", "alloy-steel", 0.438, 0.500, 14.50, 16.80, "cadmium"),
    _f("HL10PB-6-10", "Hi-Shear", 0.375, 0.875, "protruding", "alloy-steel", 0.563, 0.625, 14.50, 16.80, "cadmium"),
    _f("HL10PB-6-12", "Hi-Shear", 0.375, 1.000, "protruding", "alloy-steel", 0.688, 0.750, 14.50, 16.80, "cadmium"),
    _f("HL10PB-6-16", "Hi-Shear", 0.375, 1.250, "protruding", "alloy-steel", 0.938, 1.000, 14.50, 16.80, "cadmium"),
]

# ---------------------------------------------------------------------------
# Hi-Lok HL11 — alloy-steel 100° countersunk pin + collar (160-ksi)
# ---------------------------------------------------------------------------
_HL11 = [
    _f("HL11PB-3-4", "Hi-Shear", 0.1875, 0.500, "countersunk", "alloy-steel", 0.188, 0.250, 3.70, 3.36, "cadmium"),
    _f("HL11PB-3-6", "Hi-Shear", 0.1875, 0.625, "countersunk", "alloy-steel", 0.313, 0.375, 3.70, 3.36, "cadmium"),
    _f("HL11PB-4-4", "Hi-Shear", 0.250, 0.500, "countersunk", "alloy-steel", 0.188, 0.250, 6.50, 6.00, "cadmium"),
    _f("HL11PB-4-6", "Hi-Shear", 0.250, 0.625, "countersunk", "alloy-steel", 0.313, 0.375, 6.50, 6.00, "cadmium"),
    _f("HL11PB-4-8", "Hi-Shear", 0.250, 0.750, "countersunk", "alloy-steel", 0.438, 0.500, 6.50, 6.00, "cadmium"),
    _f("HL11PB-5-6", "Hi-Shear", 0.3125, 0.625, "countersunk", "alloy-steel", 0.313, 0.375, 10.10, 9.50, "cadmium"),
    _f("HL11PB-5-8", "Hi-Shear", 0.3125, 0.750, "countersunk", "alloy-steel", 0.438, 0.500, 10.10, 9.50, "cadmium"),
    _f("HL11PB-6-8", "Hi-Shear", 0.375, 0.750, "countersunk", "alloy-steel", 0.438, 0.500, 14.50, 13.80, "cadmium"),
    _f("HL11PB-6-10", "Hi-Shear", 0.375, 0.875, "countersunk", "alloy-steel", 0.563, 0.625, 14.50, 13.80, "cadmium"),
    _f("HL11PB-6-12", "Hi-Shear", 0.375, 1.000, "countersunk", "alloy-steel", 0.688, 0.750, 14.50, 13.80, "cadmium"),
]

# ---------------------------------------------------------------------------
# Cherry CR3243 — CherryMAX blind rivet (closed-end, countersunk, A286 stem)
# Diameter: 3/32"(3), 1/8"(4), 5/32"(5), 3/16"(6), 1/4"(8)
# CR3243 = countersunk 100°, A286 steel mandrel
# ---------------------------------------------------------------------------
_CR3243 = [
    _f("CR3243-4-02", "Cherry Aerospace", 0.125, 0.438, "countersunk", "a286", 0.020, 0.062, 0.760, 0.820, "none"),
    _f("CR3243-4-04", "Cherry Aerospace", 0.125, 0.500, "countersunk", "a286", 0.063, 0.125, 0.760, 0.820, "none"),
    _f("CR3243-4-06", "Cherry Aerospace", 0.125, 0.563, "countersunk", "a286", 0.126, 0.188, 0.760, 0.820, "none"),
    _f("CR3243-4-08", "Cherry Aerospace", 0.125, 0.625, "countersunk", "a286", 0.189, 0.250, 0.760, 0.820, "none"),
    _f("CR3243-5-02", "Cherry Aerospace", 0.15625, 0.500, "countersunk", "a286", 0.020, 0.062, 1.20, 1.30, "none"),
    _f("CR3243-5-04", "Cherry Aerospace", 0.15625, 0.563, "countersunk", "a286", 0.063, 0.125, 1.20, 1.30, "none"),
    _f("CR3243-5-06", "Cherry Aerospace", 0.15625, 0.625, "countersunk", "a286", 0.126, 0.188, 1.20, 1.30, "none"),
    _f("CR3243-5-08", "Cherry Aerospace", 0.15625, 0.750, "countersunk", "a286", 0.189, 0.250, 1.20, 1.30, "none"),
    _f("CR3243-6-04", "Cherry Aerospace", 0.1875, 0.625, "countersunk", "a286", 0.063, 0.125, 1.85, 2.00, "none"),
    _f("CR3243-6-06", "Cherry Aerospace", 0.1875, 0.688, "countersunk", "a286", 0.126, 0.188, 1.85, 2.00, "none"),
    _f("CR3243-6-08", "Cherry Aerospace", 0.1875, 0.750, "countersunk", "a286", 0.189, 0.250, 1.85, 2.00, "none"),
    _f("CR3243-6-10", "Cherry Aerospace", 0.1875, 0.875, "countersunk", "a286", 0.251, 0.312, 1.85, 2.00, "none"),
    _f("CR3243-8-04", "Cherry Aerospace", 0.250, 0.688, "countersunk", "a286", 0.063, 0.125, 3.35, 3.60, "none"),
    _f("CR3243-8-06", "Cherry Aerospace", 0.250, 0.750, "countersunk", "a286", 0.126, 0.188, 3.35, 3.60, "none"),
    _f("CR3243-8-08", "Cherry Aerospace", 0.250, 0.875, "countersunk", "a286", 0.189, 0.250, 3.35, 3.60, "none"),
    _f("CR3243-8-10", "Cherry Aerospace", 0.250, 1.000, "countersunk", "a286", 0.251, 0.312, 3.35, 3.60, "none"),
]

# ---------------------------------------------------------------------------
# NAS6203..NAS6210 — hex-head close-tolerance bolts, 160-ksi alloy steel
# NAS62XX: last two digits = nominal diameter (03=3/16", 04=1/4", 05=5/16",
#   06=3/8", 07=7/16", 08=1/2", 09=9/16", 10=5/8")
# Grip lengths typical: -4, -6, -8, -10, -12 (1/4" increments from 1/4")
# ---------------------------------------------------------------------------
_NAS62xx = [
    # NAS6203 — 3/16"
    _f("NAS6203-4", "NAS", 0.1875, 0.500, "hex", "alloy-steel", 0.188, 0.250, 3.60, 4.30, "cadmium"),
    _f("NAS6203-6", "NAS", 0.1875, 0.625, "hex", "alloy-steel", 0.313, 0.375, 3.60, 4.30, "cadmium"),
    _f("NAS6203-8", "NAS", 0.1875, 0.750, "hex", "alloy-steel", 0.438, 0.500, 3.60, 4.30, "cadmium"),
    # NAS6204 — 1/4"
    _f("NAS6204-4", "NAS", 0.250, 0.500, "hex", "alloy-steel", 0.188, 0.250, 6.28, 7.30, "cadmium"),
    _f("NAS6204-6", "NAS", 0.250, 0.625, "hex", "alloy-steel", 0.313, 0.375, 6.28, 7.30, "cadmium"),
    _f("NAS6204-8", "NAS", 0.250, 0.750, "hex", "alloy-steel", 0.438, 0.500, 9.95, 7.30, "cadmium"),  # double-shear
    _f("NAS6204-10", "NAS", 0.250, 0.875, "hex", "alloy-steel", 0.563, 0.625, 9.95, 7.30, "cadmium"),
    _f("NAS6204-12", "NAS", 0.250, 1.000, "hex", "alloy-steel", 0.688, 0.750, 9.95, 7.30, "cadmium"),
    # NAS6205 — 5/16"
    _f("NAS6205-6", "NAS", 0.3125, 0.625, "hex", "alloy-steel", 0.313, 0.375, 15.40, 11.40, "cadmium"),
    _f("NAS6205-8", "NAS", 0.3125, 0.750, "hex", "alloy-steel", 0.438, 0.500, 15.40, 11.40, "cadmium"),
    _f("NAS6205-10", "NAS", 0.3125, 0.875, "hex", "alloy-steel", 0.563, 0.625, 15.40, 11.40, "cadmium"),
    _f("NAS6205-12", "NAS", 0.3125, 1.000, "hex", "alloy-steel", 0.688, 0.750, 15.40, 11.40, "cadmium"),
    # NAS6206 — 3/8"
    _f("NAS6206-8", "NAS", 0.375, 0.750, "hex", "alloy-steel", 0.438, 0.500, 22.10, 16.40, "cadmium"),
    _f("NAS6206-10", "NAS", 0.375, 0.875, "hex", "alloy-steel", 0.563, 0.625, 22.10, 16.40, "cadmium"),
    _f("NAS6206-12", "NAS", 0.375, 1.000, "hex", "alloy-steel", 0.688, 0.750, 22.10, 16.40, "cadmium"),
    _f("NAS6206-16", "NAS", 0.375, 1.250, "hex", "alloy-steel", 0.938, 1.000, 22.10, 16.40, "cadmium"),
    # NAS6207 — 7/16"
    _f("NAS6207-8", "NAS", 0.4375, 0.750, "hex", "alloy-steel", 0.438, 0.500, 29.80, 22.30, "cadmium"),
    _f("NAS6207-10", "NAS", 0.4375, 0.875, "hex", "alloy-steel", 0.563, 0.625, 29.80, 22.30, "cadmium"),
    _f("NAS6207-12", "NAS", 0.4375, 1.000, "hex", "alloy-steel", 0.688, 0.750, 29.80, 22.30, "cadmium"),
    # NAS6208 — 1/2"
    _f("NAS6208-10", "NAS", 0.500, 0.875, "hex", "alloy-steel", 0.563, 0.625, 39.30, 29.40, "cadmium"),
    _f("NAS6208-12", "NAS", 0.500, 1.000, "hex", "alloy-steel", 0.688, 0.750, 39.30, 29.40, "cadmium"),
    _f("NAS6208-16", "NAS", 0.500, 1.250, "hex", "alloy-steel", 0.938, 1.000, 39.30, 29.40, "cadmium"),
    # NAS6209 — 9/16"
    _f("NAS6209-12", "NAS", 0.5625, 1.000, "hex", "alloy-steel", 0.688, 0.750, 49.70, 37.30, "cadmium"),
    _f("NAS6209-16", "NAS", 0.5625, 1.250, "hex", "alloy-steel", 0.938, 1.000, 49.70, 37.30, "cadmium"),
    # NAS6210 — 5/8"
    _f("NAS6210-12", "NAS", 0.625, 1.000, "hex", "alloy-steel", 0.688, 0.750, 61.40, 46.10, "cadmium"),
    _f("NAS6210-16", "NAS", 0.625, 1.250, "hex", "alloy-steel", 0.938, 1.000, 61.40, 46.10, "cadmium"),
    _f("NAS6210-20", "NAS", 0.625, 1.500, "hex", "alloy-steel", 1.188, 1.250, 61.40, 46.10, "cadmium"),
]

# ---------------------------------------------------------------------------
# MS21250 — hex-head structural bolt, 160-ksi alloy steel (close-tolerance)
# ---------------------------------------------------------------------------
_MS21250 = [
    _f("MS21250-04008", "MS", 0.250, 0.500, "hex", "alloy-steel", 0.188, 0.500, 9.95, 7.30, "cadmium"),
    _f("MS21250-04012", "MS", 0.250, 0.750, "hex", "alloy-steel", 0.313, 0.750, 9.95, 7.30, "cadmium"),
    _f("MS21250-04016", "MS", 0.250, 1.000, "hex", "alloy-steel", 0.500, 1.000, 9.95, 7.30, "cadmium"),
    _f("MS21250-05008", "MS", 0.3125, 0.500, "hex", "alloy-steel", 0.188, 0.500, 15.40, 11.40, "cadmium"),
    _f("MS21250-05012", "MS", 0.3125, 0.750, "hex", "alloy-steel", 0.313, 0.750, 15.40, 11.40, "cadmium"),
    _f("MS21250-05016", "MS", 0.3125, 1.000, "hex", "alloy-steel", 0.500, 1.000, 15.40, 11.40, "cadmium"),
    _f("MS21250-06008", "MS", 0.375, 0.500, "hex", "alloy-steel", 0.250, 0.500, 22.10, 16.40, "cadmium"),
    _f("MS21250-06012", "MS", 0.375, 0.750, "hex", "alloy-steel", 0.375, 0.750, 22.10, 16.40, "cadmium"),
    _f("MS21250-06016", "MS", 0.375, 1.000, "hex", "alloy-steel", 0.500, 1.000, 22.10, 16.40, "cadmium"),
    _f("MS21250-08012", "MS", 0.500, 0.750, "hex", "alloy-steel", 0.375, 0.750, 39.30, 29.40, "cadmium"),
    _f("MS21250-08016", "MS", 0.500, 1.000, "hex", "alloy-steel", 0.500, 1.000, 39.30, 29.40, "cadmium"),
]

# ---------------------------------------------------------------------------
# MS9395 — countersunk (#100°) 160-ksi alloy-steel structural shear screw
# ---------------------------------------------------------------------------
_MS9395 = [
    _f("MS9395-04-06", "MS", 0.250, 0.625, "countersunk", "alloy-steel", 0.313, 0.375, 9.95, 7.30, "cadmium"),
    _f("MS9395-04-08", "MS", 0.250, 0.750, "countersunk", "alloy-steel", 0.438, 0.500, 9.95, 7.30, "cadmium"),
    _f("MS9395-04-10", "MS", 0.250, 0.875, "countersunk", "alloy-steel", 0.563, 0.625, 9.95, 7.30, "cadmium"),
    _f("MS9395-04-12", "MS", 0.250, 1.000, "countersunk", "alloy-steel", 0.688, 0.750, 9.95, 7.30, "cadmium"),
    _f("MS9395-05-08", "MS", 0.3125, 0.750, "countersunk", "alloy-steel", 0.438, 0.500, 15.40, 11.40, "cadmium"),
    _f("MS9395-05-12", "MS", 0.3125, 1.000, "countersunk", "alloy-steel", 0.688, 0.750, 15.40, 11.40, "cadmium"),
    _f("MS9395-06-08", "MS", 0.375, 0.750, "countersunk", "alloy-steel", 0.438, 0.500, 22.10, 16.40, "cadmium"),
    _f("MS9395-06-12", "MS", 0.375, 1.000, "countersunk", "alloy-steel", 0.688, 0.750, 22.10, 16.40, "cadmium"),
]

# ---------------------------------------------------------------------------
# MS27039 — pan-head machine screw, passivated stainless, 125-ksi (structural)
# Thread: #10-32, 1/4-28, 5/16-24
# ---------------------------------------------------------------------------
_MS27039 = [
    _f("MS27039-1-06", "MS", 0.1900, 0.375, "pan", "stainless-a286", 0.125, 0.250, 2.14, 2.50, "passivated"),
    _f("MS27039-1-08", "MS", 0.1900, 0.500, "pan", "stainless-a286", 0.250, 0.375, 2.14, 2.50, "passivated"),
    _f("MS27039-1-10", "MS", 0.1900, 0.625, "pan", "stainless-a286", 0.375, 0.500, 2.14, 2.50, "passivated"),
    _f("MS27039-1-12", "MS", 0.1900, 0.750, "pan", "stainless-a286", 0.500, 0.625, 2.14, 2.50, "passivated"),
    _f("MS27039-2-08", "MS", 0.250, 0.500, "pan", "stainless-a286", 0.250, 0.375, 4.42, 5.00, "passivated"),
    _f("MS27039-2-10", "MS", 0.250, 0.625, "pan", "stainless-a286", 0.375, 0.500, 4.42, 5.00, "passivated"),
    _f("MS27039-2-12", "MS", 0.250, 0.750, "pan", "stainless-a286", 0.500, 0.625, 4.42, 5.00, "passivated"),
    _f("MS27039-3-08", "MS", 0.3125, 0.500, "pan", "stainless-a286", 0.250, 0.375, 6.80, 7.90, "passivated"),
    _f("MS27039-3-10", "MS", 0.3125, 0.625, "pan", "stainless-a286", 0.375, 0.500, 6.80, 7.90, "passivated"),
    _f("MS27039-3-12", "MS", 0.3125, 0.750, "pan", "stainless-a286", 0.500, 0.625, 6.80, 7.90, "passivated"),
]

# ---------------------------------------------------------------------------
# AS3219..AS3243 — SAE Aerospace Standard solid shear rivets (2117-T4 alum.)
# AS3219 = protruding, AS3220 = flat head, AS3221 = countersunk 100°, etc.
# AS3243 = countersunk 120° (thicker skins)
# Sizes: -3=3/32", -4=1/8", -5=5/32", -6=3/16"
# ---------------------------------------------------------------------------
_AS3219_3220_3221_3243 = [
    # AS3219 — protruding, 2117-T4
    _f("AS3219-3-4", "SAE AS", 0.09375, 0.250, "protruding", "2117-t4", 0.062, 0.125, 0.305, 0.310, "none"),
    _f("AS3219-3-6", "SAE AS", 0.09375, 0.375, "protruding", "2117-t4", 0.188, 0.250, 0.305, 0.310, "none"),
    _f("AS3219-4-4", "SAE AS", 0.125, 0.250, "protruding", "2117-t4", 0.062, 0.125, 0.545, 0.555, "none"),
    _f("AS3219-4-6", "SAE AS", 0.125, 0.375, "protruding", "2117-t4", 0.188, 0.250, 0.545, 0.555, "none"),
    _f("AS3219-4-8", "SAE AS", 0.125, 0.500, "protruding", "2117-t4", 0.313, 0.375, 0.545, 0.555, "none"),
    _f("AS3219-5-4", "SAE AS", 0.15625, 0.250, "protruding", "2117-t4", 0.062, 0.125, 0.862, 0.875, "none"),
    _f("AS3219-5-6", "SAE AS", 0.15625, 0.375, "protruding", "2117-t4", 0.188, 0.250, 0.862, 0.875, "none"),
    _f("AS3219-5-8", "SAE AS", 0.15625, 0.500, "protruding", "2117-t4", 0.313, 0.375, 0.862, 0.875, "none"),
    _f("AS3219-6-6", "SAE AS", 0.1875, 0.375, "protruding", "2117-t4", 0.188, 0.250, 1.24, 1.26, "none"),
    _f("AS3219-6-8", "SAE AS", 0.1875, 0.500, "protruding", "2117-t4", 0.313, 0.375, 1.24, 1.26, "none"),
    # AS3220 — flat head, 2117-T4
    _f("AS3220-4-4", "SAE AS", 0.125, 0.250, "flat", "2117-t4", 0.062, 0.125, 0.545, 0.555, "none"),
    _f("AS3220-4-6", "SAE AS", 0.125, 0.375, "flat", "2117-t4", 0.188, 0.250, 0.545, 0.555, "none"),
    _f("AS3220-5-6", "SAE AS", 0.15625, 0.375, "flat", "2117-t4", 0.188, 0.250, 0.862, 0.875, "none"),
    _f("AS3220-5-8", "SAE AS", 0.15625, 0.500, "flat", "2117-t4", 0.313, 0.375, 0.862, 0.875, "none"),
    _f("AS3220-6-6", "SAE AS", 0.1875, 0.375, "flat", "2117-t4", 0.188, 0.250, 1.24, 1.26, "none"),
    # AS3221 — 100° countersunk, 2117-T4
    _f("AS3221-4-4", "SAE AS", 0.125, 0.250, "countersunk", "2117-t4", 0.062, 0.125, 0.545, 0.490, "none"),
    _f("AS3221-4-6", "SAE AS", 0.125, 0.375, "countersunk", "2117-t4", 0.188, 0.250, 0.545, 0.490, "none"),
    _f("AS3221-4-8", "SAE AS", 0.125, 0.500, "countersunk", "2117-t4", 0.313, 0.375, 0.545, 0.490, "none"),
    _f("AS3221-5-4", "SAE AS", 0.15625, 0.250, "countersunk", "2117-t4", 0.062, 0.125, 0.862, 0.775, "none"),
    _f("AS3221-5-6", "SAE AS", 0.15625, 0.375, "countersunk", "2117-t4", 0.188, 0.250, 0.862, 0.775, "none"),
    _f("AS3221-5-8", "SAE AS", 0.15625, 0.500, "countersunk", "2117-t4", 0.313, 0.375, 0.862, 0.775, "none"),
    _f("AS3221-6-6", "SAE AS", 0.1875, 0.375, "countersunk", "2117-t4", 0.188, 0.250, 1.24, 1.12, "none"),
    _f("AS3221-6-8", "SAE AS", 0.1875, 0.500, "countersunk", "2117-t4", 0.313, 0.375, 1.24, 1.12, "none"),
    # AS3243 — 120° countersunk, 2117-T4
    _f("AS3243-4-4", "SAE AS", 0.125, 0.250, "countersunk-120", "2117-t4", 0.062, 0.125, 0.545, 0.490, "none"),
    _f("AS3243-4-6", "SAE AS", 0.125, 0.375, "countersunk-120", "2117-t4", 0.188, 0.250, 0.545, 0.490, "none"),
    _f("AS3243-5-6", "SAE AS", 0.15625, 0.375, "countersunk-120", "2117-t4", 0.188, 0.250, 0.862, 0.775, "none"),
    _f("AS3243-6-6", "SAE AS", 0.1875, 0.375, "countersunk-120", "2117-t4", 0.188, 0.250, 1.24, 1.12, "none"),
]

# ---------------------------------------------------------------------------
# Huck-Lok / Huck BOM lockbolt — alloy-steel pin + collar
# HLK: diameter in 32nds; grip code in 1/16" increments
# ---------------------------------------------------------------------------
_HUCK_LOK = [
    _f("HLK-6-6", "Huck International", 0.1875, 0.625, "protruding", "alloy-steel", 0.250, 0.375, 3.50, 4.00, "zinc-phosphate"),
    _f("HLK-6-8", "Huck International", 0.1875, 0.750, "protruding", "alloy-steel", 0.375, 0.500, 3.50, 4.00, "zinc-phosphate"),
    _f("HLK-8-6", "Huck International", 0.250, 0.625, "protruding", "alloy-steel", 0.250, 0.375, 6.00, 7.00, "zinc-phosphate"),
    _f("HLK-8-8", "Huck International", 0.250, 0.750, "protruding", "alloy-steel", 0.375, 0.500, 6.00, 7.00, "zinc-phosphate"),
    _f("HLK-8-10", "Huck International", 0.250, 0.875, "protruding", "alloy-steel", 0.500, 0.625, 6.00, 7.00, "zinc-phosphate"),
    _f("HLK-10-8", "Huck International", 0.3125, 0.750, "protruding", "alloy-steel", 0.375, 0.500, 9.40, 11.00, "zinc-phosphate"),
    _f("HLK-10-10", "Huck International", 0.3125, 0.875, "protruding", "alloy-steel", 0.500, 0.625, 9.40, 11.00, "zinc-phosphate"),
    _f("HLK-10-12", "Huck International", 0.3125, 1.000, "protruding", "alloy-steel", 0.625, 0.750, 9.40, 11.00, "zinc-phosphate"),
    _f("HLK-12-10", "Huck International", 0.375, 0.875, "protruding", "alloy-steel", 0.500, 0.625, 13.50, 15.80, "zinc-phosphate"),
    _f("HLK-12-12", "Huck International", 0.375, 1.000, "protruding", "alloy-steel", 0.625, 0.750, 13.50, 15.80, "zinc-phosphate"),
    _f("HLK-12-16", "Huck International", 0.375, 1.250, "protruding", "alloy-steel", 0.875, 1.000, 13.50, 15.80, "zinc-phosphate"),
]

# ---------------------------------------------------------------------------
# Tinnerman — push-on / clip nuts, sheet-metal fasteners (structural light load)
# ---------------------------------------------------------------------------
_TINNERMAN = [
    _f("TIN-AN4062-3", "Tinnerman Palnut", 0.1875, 0.094, "clip-nut", "carbon-steel", 0.020, 0.062, 0.45, 0.50, "zinc"),
    _f("TIN-AN4062-4", "Tinnerman Palnut", 0.250, 0.094, "clip-nut", "carbon-steel", 0.020, 0.062, 0.80, 0.90, "zinc"),
    _f("TIN-AN4062-5", "Tinnerman Palnut", 0.3125, 0.125, "clip-nut", "carbon-steel", 0.020, 0.062, 1.25, 1.40, "zinc"),
    _f("TIN-AN4062-6", "Tinnerman Palnut", 0.375, 0.125, "clip-nut", "carbon-steel", 0.020, 0.062, 1.80, 2.00, "zinc"),
    _f("TIN-B6H375-3", "Tinnerman Palnut", 0.1875, 0.250, "push-on", "carbon-steel", 0.040, 0.094, 0.35, 0.40, "zinc"),
    _f("TIN-B6H375-4", "Tinnerman Palnut", 0.250, 0.250, "push-on", "carbon-steel", 0.040, 0.094, 0.62, 0.70, "zinc"),
    _f("TIN-B6H375-5", "Tinnerman Palnut", 0.3125, 0.312, "push-on", "carbon-steel", 0.040, 0.094, 0.97, 1.10, "zinc"),
]

# ---------------------------------------------------------------------------
# Assembled catalogue
# ---------------------------------------------------------------------------
CATALOGUE: list[dict] = (
    _HL18
    + _HL19
    + _HL10
    + _HL11
    + _CR3243
    + _NAS62xx
    + _MS21250
    + _MS9395
    + _MS27039
    + _AS3219_3220_3221_3243
    + _HUCK_LOK
    + _TINNERMAN
)

# Spec → entry index for fast lookup
_SPEC_INDEX: dict[str, dict] = {entry["spec"]: entry for entry in CATALOGUE}


def get_by_spec(spec: str) -> dict | None:
    """Return the catalogue entry for *spec*, or None if not found."""
    return _SPEC_INDEX.get(spec)


def filter_catalogue(
    *,
    diameter_in: float | None = None,
    head_style: str | None = None,
    material: str | None = None,
    mfr: str | None = None,
    max_diameter_in: float | None = None,
    min_shear_kip: float | None = None,
    min_tension_kip: float | None = None,
) -> list[dict]:
    """Return entries matching all supplied (non-None) criteria."""
    results = CATALOGUE
    if diameter_in is not None:
        results = [e for e in results if abs(e["diameter_in"] - diameter_in) < 1e-4]
    if max_diameter_in is not None:
        results = [e for e in results if e["diameter_in"] <= max_diameter_in + 1e-6]
    if head_style is not None:
        results = [e for e in results if e["head_style"] == head_style]
    if material is not None:
        results = [e for e in results if e["material"] == material]
    if mfr is not None:
        results = [e for e in results if e["mfr"] == mfr]
    if min_shear_kip is not None:
        results = [e for e in results if e["shear_kip"] >= min_shear_kip]
    if min_tension_kip is not None:
        results = [e for e in results if e["tension_kip"] >= min_tension_kip]
    return results
