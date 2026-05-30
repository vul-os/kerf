"""DIN/ISO metric fastener catalog — pure-Python, no external DB.

Standard dimensions are sourced from publicly available DIN/ISO tables:
  DIN 931  — Hexagon bolt, partial thread (coarse pitch)
  DIN 933  — Hexagon bolt, full thread (coarse pitch)
  DIN 912  — Hexagon socket head cap screw (ISO 4762)
  DIN 7991 — Hexagon socket countersunk head cap screw (ISO 10642)
  DIN 125  — Plain washer, form A
  DIN 934  — Hexagon nut, style 1 (ISO 4032)
  ISO 7380 — Hexagon socket button head cap screw

DISCLAIMER: Standard dimensions from public DIN tables — NOT DIN-certified.
These values are for reference and preliminary engineering calculations only.
For precision-critical or safety-critical applications always verify against the
current published standard.

Torque calculations use VDI 2230 simplified method (K-factor approach):
  T = K · F_M · d
where F_M is the assembly preload (80 % of yield for grade 8.8 / A2-70 by
default) and K is the tightening-torque coefficient (default 0.14 for slightly
oiled threads).

References
----------
DIN 931:2012, DIN 933:2012, DIN 912:2012, DIN 7991:2012, DIN 125:2011,
DIN 934:2012, ISO 7380:2011.
VDI 2230 Part 1 (2015): Systematic calculation of highly stressed bolted joints.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional

# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class FastenerSpec:
    """Immutable descriptor for one concrete fastener size/material combination.

    ``dimensions`` carries the head geometry from the relevant DIN/ISO table.
    Typical keys per standard:

    DIN 931/933/912  : head_diameter_max, head_height_max, wrench_size,
                       thread_pitch_coarse, thread_pitch_fine (where applicable)
    DIN 7991         : head_diameter_max, head_height_max, wrench_size,
                       thread_pitch_coarse
    DIN 125          : inner_diameter, outer_diameter, thickness
    DIN 934          : width_across_flats, nut_height, thread_pitch_coarse
    ISO 7380         : head_diameter_max, head_height_max, wrench_size,
                       thread_pitch_coarse
    """
    standard: str
    """e.g. 'DIN 931', 'DIN 912', 'ISO 7380'"""
    kind: str
    """One of: hex_bolt / cap_screw / countersunk_cap_screw / flat_washer / hex_nut / button_head_cap_screw"""
    size: str
    """Metric thread designation, e.g. 'M3', 'M10', 'M20'"""
    length_mm: Optional[float]
    """Nominal bolt/screw length in mm; None for nuts and washers."""
    thread_pitch: float
    """Coarse-pitch value in mm per DIN 13-1 (the default series for most applications)."""
    material: str
    """e.g. 'steel_grade_8.8', 'stainless_a2-70', 'stainless_a4-80'"""
    dimensions: dict
    """Standard geometry values (all floats, in mm or degrees) keyed per standard."""

    # Nominal thread diameter in mm (derived from size string)
    diameter_mm: float = field(init=False)

    def __post_init__(self) -> None:
        # Parse diameter from 'M10' -> 10.0
        try:
            self.diameter_mm = float(self.size.lstrip("Mm"))
        except ValueError:
            self.diameter_mm = 0.0

    def nominal_stress_area(self) -> float:
        """Tensile stress area A_s (mm²) per ISO 898-1 / DIN 13 formula.

        A_s = π/4 · ((d2 + d3) / 2)²
        where d2 = pitch diameter, d3 = minor diameter.
        For the coarse thread: d2 = d - 0.6495·p, d3 = d - 1.2269·p.
        Simplified single-formula equivalent: A_s ≈ π/4·(d - 0.9382·p)².
        """
        d = self.diameter_mm
        p = self.thread_pitch
        ds = d - 0.9382 * p
        return math.pi / 4 * ds ** 2


# ---------------------------------------------------------------------------
# Coarse thread pitches per DIN 13-1 (metric preferred series)
# ---------------------------------------------------------------------------

# {size: coarse_pitch_mm}
_COARSE_PITCH: dict[str, float] = {
    "M1":   0.25,
    "M1.2": 0.25,
    "M1.6": 0.35,
    "M2":   0.40,
    "M2.5": 0.45,
    "M3":   0.50,
    "M3.5": 0.60,
    "M4":   0.70,
    "M5":   0.80,
    "M6":   1.00,
    "M7":   1.00,
    "M8":   1.25,
    "M10":  1.50,
    "M12":  1.75,
    "M14":  2.00,
    "M16":  2.00,
    "M18":  2.50,
    "M20":  2.50,
    "M22":  2.50,
    "M24":  3.00,
    "M27":  3.00,
    "M30":  3.50,
    "M36":  4.00,
    "M42":  4.50,
    "M48":  5.00,
}

# ---------------------------------------------------------------------------
# Per-standard dimensional tables
# All values taken from public DIN/ISO dimensional standards (max dimensions).
# ---------------------------------------------------------------------------

# DIN 931 / DIN 933 Hex bolt (partial / full thread)
# Columns: head_diameter_max (e/s circumscribed circle), wrench_size (s, mm),
#          head_height_max (k, mm)
_DIN_931_DIMS: dict[str, dict] = {
    "M3":  {"head_diameter_max": 6.35,  "wrench_size": 5.5,  "head_height_max": 2.00,
            "thread_pitch_coarse": 0.50},
    "M4":  {"head_diameter_max": 7.66,  "wrench_size": 7.0,  "head_height_max": 2.80,
            "thread_pitch_coarse": 0.70},
    "M5":  {"head_diameter_max": 8.79,  "wrench_size": 8.0,  "head_height_max": 3.50,
            "thread_pitch_coarse": 0.80},
    "M6":  {"head_diameter_max": 11.05, "wrench_size": 10.0, "head_height_max": 4.00,
            "thread_pitch_coarse": 1.00},
    "M8":  {"head_diameter_max": 14.38, "wrench_size": 13.0, "head_height_max": 5.30,
            "thread_pitch_coarse": 1.25},
    "M10": {"head_diameter_max": 17.77, "wrench_size": 17.0, "head_height_max": 6.40,
            "thread_pitch_coarse": 1.50},
    "M12": {"head_diameter_max": 20.03, "wrench_size": 19.0, "head_height_max": 7.50,
            "thread_pitch_coarse": 1.75},
    "M14": {"head_diameter_max": 23.36, "wrench_size": 22.0, "head_height_max": 8.80,
            "thread_pitch_coarse": 2.00},
    "M16": {"head_diameter_max": 26.75, "wrench_size": 24.0, "head_height_max": 10.00,
            "thread_pitch_coarse": 2.00},
    "M18": {"head_diameter_max": 30.14, "wrench_size": 27.0, "head_height_max": 11.50,
            "thread_pitch_coarse": 2.50},
    "M20": {"head_diameter_max": 33.53, "wrench_size": 30.0, "head_height_max": 12.50,
            "thread_pitch_coarse": 2.50},
    "M22": {"head_diameter_max": 35.72, "wrench_size": 32.0, "head_height_max": 14.00,
            "thread_pitch_coarse": 2.50},
    "M24": {"head_diameter_max": 39.98, "wrench_size": 36.0, "head_height_max": 15.00,
            "thread_pitch_coarse": 3.00},
    "M27": {"head_diameter_max": 45.20, "wrench_size": 41.0, "head_height_max": 17.00,
            "thread_pitch_coarse": 3.00},
    "M30": {"head_diameter_max": 50.85, "wrench_size": 46.0, "head_height_max": 18.70,
            "thread_pitch_coarse": 3.50},
    "M36": {"head_diameter_max": 60.79, "wrench_size": 55.0, "head_height_max": 22.50,
            "thread_pitch_coarse": 4.00},
}

# Fine-pitch (ISO 261 preferred), per size where commonly specified
_DIN_931_FINE: dict[str, float] = {
    "M8":  1.00,
    "M10": 1.25,
    "M12": 1.25,
    "M14": 1.50,
    "M16": 1.50,
    "M18": 1.50,
    "M20": 1.50,
    "M22": 1.50,
    "M24": 2.00,
    "M27": 2.00,
    "M30": 2.00,
    "M36": 3.00,
}

# DIN 912 / ISO 4762 — Hexagon socket head cap screw
# head_diameter (dk), head_height (k), wrench_size (s)
_DIN_912_DIMS: dict[str, dict] = {
    "M3":  {"head_diameter_max": 5.5,  "head_height_max": 3.0,  "wrench_size": 2.5,
            "thread_pitch_coarse": 0.50},
    "M4":  {"head_diameter_max": 7.0,  "head_height_max": 4.0,  "wrench_size": 3.0,
            "thread_pitch_coarse": 0.70},
    "M5":  {"head_diameter_max": 8.5,  "head_height_max": 5.0,  "wrench_size": 4.0,
            "thread_pitch_coarse": 0.80},
    "M6":  {"head_diameter_max": 10.0, "head_height_max": 6.0,  "wrench_size": 5.0,
            "thread_pitch_coarse": 1.00},
    "M8":  {"head_diameter_max": 13.0, "head_height_max": 8.0,  "wrench_size": 6.0,
            "thread_pitch_coarse": 1.25},
    "M10": {"head_diameter_max": 16.0, "head_height_max": 10.0, "wrench_size": 8.0,
            "thread_pitch_coarse": 1.50},
    "M12": {"head_diameter_max": 18.0, "head_height_max": 12.0, "wrench_size": 10.0,
            "thread_pitch_coarse": 1.75},
    "M14": {"head_diameter_max": 21.0, "head_height_max": 14.0, "wrench_size": 12.0,
            "thread_pitch_coarse": 2.00},
    "M16": {"head_diameter_max": 24.0, "head_height_max": 16.0, "wrench_size": 14.0,
            "thread_pitch_coarse": 2.00},
    "M20": {"head_diameter_max": 30.0, "head_height_max": 20.0, "wrench_size": 17.0,
            "thread_pitch_coarse": 2.50},
    "M24": {"head_diameter_max": 36.0, "head_height_max": 24.0, "wrench_size": 19.0,
            "thread_pitch_coarse": 3.00},
    "M30": {"head_diameter_max": 45.0, "head_height_max": 30.0, "wrench_size": 22.0,
            "thread_pitch_coarse": 3.50},
    "M36": {"head_diameter_max": 54.0, "head_height_max": 36.0, "wrench_size": 27.0,
            "thread_pitch_coarse": 4.00},
}

# DIN 7991 / ISO 10642 — Hexagon socket countersunk head cap screw
# head_diameter (dk, 90° countersink), head_height (k, approx flush depth), wrench_size (s)
_DIN_7991_DIMS: dict[str, dict] = {
    "M3":  {"head_diameter_max": 6.72,  "head_height_max": 1.86, "wrench_size": 2.0,
            "countersink_angle_deg": 90, "thread_pitch_coarse": 0.50},
    "M4":  {"head_diameter_max": 8.96,  "head_height_max": 2.48, "wrench_size": 2.5,
            "countersink_angle_deg": 90, "thread_pitch_coarse": 0.70},
    "M5":  {"head_diameter_max": 11.20, "head_height_max": 3.10, "wrench_size": 3.0,
            "countersink_angle_deg": 90, "thread_pitch_coarse": 0.80},
    "M6":  {"head_diameter_max": 13.44, "head_height_max": 3.72, "wrench_size": 4.0,
            "countersink_angle_deg": 90, "thread_pitch_coarse": 1.00},
    "M8":  {"head_diameter_max": 17.92, "head_height_max": 4.96, "wrench_size": 5.0,
            "countersink_angle_deg": 90, "thread_pitch_coarse": 1.25},
    "M10": {"head_diameter_max": 22.40, "head_height_max": 6.20, "wrench_size": 6.0,
            "countersink_angle_deg": 90, "thread_pitch_coarse": 1.50},
    "M12": {"head_diameter_max": 26.88, "head_height_max": 7.44, "wrench_size": 8.0,
            "countersink_angle_deg": 90, "thread_pitch_coarse": 1.75},
    "M16": {"head_diameter_max": 33.60, "head_height_max": 8.80, "wrench_size": 10.0,
            "countersink_angle_deg": 90, "thread_pitch_coarse": 2.00},
    "M20": {"head_diameter_max": 40.32, "head_height_max": 10.16, "wrench_size": 12.0,
            "countersink_angle_deg": 90, "thread_pitch_coarse": 2.50},
}

# DIN 125 (form A) — Plain washers
# inner_diameter (d1), outer_diameter (d2), thickness (h)
_DIN_125_DIMS: dict[str, dict] = {
    "M3":  {"inner_diameter": 3.2,  "outer_diameter": 7.0,  "thickness": 0.5},
    "M4":  {"inner_diameter": 4.3,  "outer_diameter": 9.0,  "thickness": 0.8},
    "M5":  {"inner_diameter": 5.3,  "outer_diameter": 10.0, "thickness": 1.0},
    "M6":  {"inner_diameter": 6.4,  "outer_diameter": 12.0, "thickness": 1.6},
    "M8":  {"inner_diameter": 8.4,  "outer_diameter": 16.0, "thickness": 1.6},
    "M10": {"inner_diameter": 10.5, "outer_diameter": 20.0, "thickness": 2.0},
    "M12": {"inner_diameter": 13.0, "outer_diameter": 24.0, "thickness": 2.5},
    "M14": {"inner_diameter": 15.0, "outer_diameter": 28.0, "thickness": 2.5},
    "M16": {"inner_diameter": 17.0, "outer_diameter": 30.0, "thickness": 3.0},
    "M18": {"inner_diameter": 19.0, "outer_diameter": 34.0, "thickness": 3.0},
    "M20": {"inner_diameter": 21.0, "outer_diameter": 37.0, "thickness": 3.0},
    "M22": {"inner_diameter": 23.0, "outer_diameter": 39.0, "thickness": 3.0},
    "M24": {"inner_diameter": 25.0, "outer_diameter": 44.0, "thickness": 4.0},
    "M27": {"inner_diameter": 28.0, "outer_diameter": 50.0, "thickness": 4.0},
    "M30": {"inner_diameter": 31.0, "outer_diameter": 56.0, "thickness": 4.0},
    "M36": {"inner_diameter": 37.0, "outer_diameter": 66.0, "thickness": 5.0},
}

# DIN 934 / ISO 4032 — Hexagon nut, style 1
# width_across_flats (s, mm), nut_height (m, mm)
_DIN_934_DIMS: dict[str, dict] = {
    "M3":  {"width_across_flats": 5.5,  "nut_height": 2.4,  "thread_pitch_coarse": 0.50},
    "M4":  {"width_across_flats": 7.0,  "nut_height": 3.2,  "thread_pitch_coarse": 0.70},
    "M5":  {"width_across_flats": 8.0,  "nut_height": 4.0,  "thread_pitch_coarse": 0.80},
    "M6":  {"width_across_flats": 10.0, "nut_height": 5.0,  "thread_pitch_coarse": 1.00},
    "M8":  {"width_across_flats": 13.0, "nut_height": 6.5,  "thread_pitch_coarse": 1.25},
    "M10": {"width_across_flats": 17.0, "nut_height": 8.0,  "thread_pitch_coarse": 1.50},
    "M12": {"width_across_flats": 19.0, "nut_height": 10.0, "thread_pitch_coarse": 1.75},
    "M14": {"width_across_flats": 22.0, "nut_height": 11.0, "thread_pitch_coarse": 2.00},
    "M16": {"width_across_flats": 24.0, "nut_height": 13.0, "thread_pitch_coarse": 2.00},
    "M18": {"width_across_flats": 27.0, "nut_height": 15.0, "thread_pitch_coarse": 2.50},
    "M20": {"width_across_flats": 30.0, "nut_height": 16.0, "thread_pitch_coarse": 2.50},
    "M22": {"width_across_flats": 32.0, "nut_height": 18.0, "thread_pitch_coarse": 2.50},
    "M24": {"width_across_flats": 36.0, "nut_height": 19.0, "thread_pitch_coarse": 3.00},
    "M27": {"width_across_flats": 41.0, "nut_height": 22.0, "thread_pitch_coarse": 3.00},
    "M30": {"width_across_flats": 46.0, "nut_height": 24.0, "thread_pitch_coarse": 3.50},
    "M36": {"width_across_flats": 55.0, "nut_height": 29.0, "thread_pitch_coarse": 4.00},
}

# ISO 7380 — Button head cap screw
# head_diameter (dk), head_height (k), wrench_size (s)
_ISO_7380_DIMS: dict[str, dict] = {
    "M3":  {"head_diameter_max": 5.7,  "head_height_max": 1.65, "wrench_size": 2.0,
            "thread_pitch_coarse": 0.50},
    "M4":  {"head_diameter_max": 7.6,  "head_height_max": 2.20, "wrench_size": 2.5,
            "thread_pitch_coarse": 0.70},
    "M5":  {"head_diameter_max": 9.5,  "head_height_max": 2.75, "wrench_size": 3.0,
            "thread_pitch_coarse": 0.80},
    "M6":  {"head_diameter_max": 10.5, "head_height_max": 3.30, "wrench_size": 4.0,
            "thread_pitch_coarse": 1.00},
    "M8":  {"head_diameter_max": 14.0, "head_height_max": 4.40, "wrench_size": 5.0,
            "thread_pitch_coarse": 1.25},
    "M10": {"head_diameter_max": 17.5, "head_height_max": 5.50, "wrench_size": 6.0,
            "thread_pitch_coarse": 1.50},
    "M12": {"head_diameter_max": 21.0, "head_height_max": 6.60, "wrench_size": 8.0,
            "thread_pitch_coarse": 1.75},
    "M16": {"head_diameter_max": 28.0, "head_height_max": 8.80, "wrench_size": 10.0,
            "thread_pitch_coarse": 2.00},
    "M20": {"head_diameter_max": 35.0, "head_height_max": 11.0, "wrench_size": 12.0,
            "thread_pitch_coarse": 2.50},
}

# ---------------------------------------------------------------------------
# Material yield strengths (proof load stress, σ_p, MPa) per ISO 898-1 / ISO 3506
# Used for VDI 2230 preload calculation.
# ---------------------------------------------------------------------------

# {material_key: (ultimate_tensile_strength_MPa, yield_strength_MPa)}
_MATERIAL_STRENGTH: dict[str, tuple[float, float]] = {
    "steel_grade_4.6":    (400.0, 240.0),
    "steel_grade_4.8":    (420.0, 336.0),
    "steel_grade_5.6":    (500.0, 300.0),
    "steel_grade_5.8":    (520.0, 416.0),
    "steel_grade_6.8":    (600.0, 480.0),
    "steel_grade_8.8":    (800.0, 640.0),
    "steel_grade_10.9":   (1000.0, 900.0),
    "steel_grade_12.9":   (1200.0, 1080.0),
    "stainless_a2-70":    (700.0, 450.0),
    "stainless_a2-80":    (800.0, 600.0),
    "stainless_a4-70":    (700.0, 450.0),
    "stainless_a4-80":    (800.0, 600.0),
    "stainless_a2-50":    (500.0, 210.0),
    "brass":              (350.0, 200.0),
    "titanium_grade_5":   (950.0, 880.0),
}

# ---------------------------------------------------------------------------
# Standard bolt lengths (mm) — nominal values from DIN/ISO preferred series
# ---------------------------------------------------------------------------
_STANDARD_LENGTHS_MM = [
    5, 6, 8, 10, 12, 14, 16, 18, 20, 22, 25, 28, 30, 35, 40, 45, 50,
    55, 60, 65, 70, 80, 90, 100, 110, 120, 130, 140, 150, 160, 180, 200,
]

# ---------------------------------------------------------------------------
# Catalog builder helpers
# ---------------------------------------------------------------------------

def _make_bolt_spec(
    standard: str,
    kind: str,
    size: str,
    length_mm: Optional[float],
    dims: dict,
    material: str,
) -> FastenerSpec:
    pitch = dims.get("thread_pitch_coarse", _COARSE_PITCH.get(size, 0.0))
    return FastenerSpec(
        standard=standard,
        kind=kind,
        size=size,
        length_mm=length_mm,
        thread_pitch=pitch,
        material=material,
        dimensions=dict(dims),
    )


def _make_washer_spec(size: str, dims: dict, material: str) -> FastenerSpec:
    return FastenerSpec(
        standard="DIN 125",
        kind="flat_washer",
        size=size,
        length_mm=None,
        thread_pitch=_COARSE_PITCH.get(size, 0.0),
        material=material,
        dimensions=dict(dims),
    )


def _make_nut_spec(size: str, dims: dict, material: str) -> FastenerSpec:
    pitch = dims.get("thread_pitch_coarse", _COARSE_PITCH.get(size, 0.0))
    return FastenerSpec(
        standard="DIN 934",
        kind="hex_nut",
        size=size,
        length_mm=None,
        thread_pitch=pitch,
        material=material,
        dimensions=dict(dims),
    )


# ---------------------------------------------------------------------------
# Build the comprehensive catalog
# ---------------------------------------------------------------------------

def _build_catalog() -> dict[str, dict[str, list[FastenerSpec]]]:
    """Build the full catalog: {standard: {size: [FastenerSpec, ...]}}

    For length-carrying standards (bolts/screws) we expand every size over
    the standard length series (where that length is geometrically sensible).
    Nuts and washers are stored without length (None).

    Returns
    -------
    dict
        Outer key = normalised standard string (e.g. "DIN 931").
        Inner key = size string (e.g. "M10").
        Value = list of FastenerSpec (one per length for bolts; single item for
        nuts/washers, at the default material 'steel_grade_8.8').
    """
    catalog: dict[str, dict[str, list[FastenerSpec]]] = {}

    def _add(std: str, size: str, spec: FastenerSpec) -> None:
        catalog.setdefault(std, {}).setdefault(size, []).append(spec)

    default_bolt_material = "steel_grade_8.8"
    default_stainless = "stainless_a2-70"
    washer_material = "steel_grade_8.8"

    for std, kind, dims_table in [
        ("DIN 931", "hex_bolt",             _DIN_931_DIMS),
        ("DIN 933", "hex_bolt",             _DIN_931_DIMS),   # same dims, full thread
        ("DIN 912", "cap_screw",            _DIN_912_DIMS),
        ("DIN 7991", "countersunk_cap_screw", _DIN_7991_DIMS),
        ("ISO 7380", "button_head_cap_screw", _ISO_7380_DIMS),
        ("ISO 4762", "cap_screw",            _DIN_912_DIMS),   # ISO number for DIN 912
    ]:
        for size, dims in dims_table.items():
            d = float(size.lstrip("Mm"))
            for length in _STANDARD_LENGTHS_MM:
                # Only emit sensible lengths (length >= 2×diameter for bolts)
                if length < max(d * 1.5, 5.0):
                    continue
                spec = _make_bolt_spec(std, kind, size, float(length), dims,
                                       default_bolt_material)
                _add(std, size, spec)
            # Also add a stainless variant at the most common length
            common_len = max(d * 3, 10.0)
            # Round to nearest standard length
            common_len = min(_STANDARD_LENGTHS_MM,
                             key=lambda l: abs(l - common_len))
            spec_ss = _make_bolt_spec(std, kind, size, float(common_len), dims,
                                       default_stainless)
            _add(std, size, spec_ss)

    # DIN 125 — washers
    for size, dims in _DIN_125_DIMS.items():
        spec = _make_washer_spec(size, dims, washer_material)
        _add("DIN 125", size, spec)

    # DIN 934 — hex nuts
    for size, dims in _DIN_934_DIMS.items():
        spec = _make_nut_spec(size, dims, default_bolt_material)
        _add("DIN 934", size, spec)

    return catalog


# Module-level catalog — built once at import.
DIN_FASTENERS_CATALOG: dict[str, dict[str, list[FastenerSpec]]] = _build_catalog()

# ---------------------------------------------------------------------------
# Lookup
# ---------------------------------------------------------------------------

def lookup_fastener(
    standard: str,
    size: str,
    length_mm: Optional[float] = None,
    material: Optional[str] = None,
) -> FastenerSpec:
    """Return a FastenerSpec from the catalog.

    Parameters
    ----------
    standard : str
        Standard identifier, case-insensitive, e.g. ``'din 931'`` or ``'DIN 931'``.
    size : str
        Metric size, case-insensitive, e.g. ``'m10'`` or ``'M10'``.
    length_mm : float, optional
        Nominal length in mm. When None, returns the first entry for the
        size (useful for nuts/washers where length is not applicable).
    material : str, optional
        Filter by material key (case-insensitive). When None any material
        matches (first match returned).

    Returns
    -------
    FastenerSpec

    Raises
    ------
    KeyError
        If the standard or size is not in the catalog.
    ValueError
        If no entry matches the requested length/material.
    """
    std_key = standard.strip().upper()
    # Normalise: 'DIN931' -> 'DIN 931', 'ISO4762' -> 'ISO 4762'
    import re as _re
    std_key_spaced = _re.sub(r'([A-Z]+)(\d)', r'\1 \2', std_key)

    # Try with space first, then without
    found_std: Optional[dict] = None
    for candidate in [std_key_spaced, std_key]:
        # Case-insensitive search over catalog keys
        for cat_key in DIN_FASTENERS_CATALOG:
            if cat_key.upper() == candidate:
                found_std = DIN_FASTENERS_CATALOG[cat_key]
                break
        if found_std is not None:
            break

    if found_std is None:
        available = list(DIN_FASTENERS_CATALOG.keys())
        raise KeyError(
            f"Standard {standard!r} not found. "
            f"Available: {available}"
        )

    size_key = size.strip().upper()
    # Normalise 'm10' -> 'M10'
    if size_key.startswith("M"):
        pass
    else:
        size_key = "M" + size_key.lstrip("M")

    found_size: Optional[list[FastenerSpec]] = None
    for cat_size in found_std:
        if cat_size.upper() == size_key:
            found_size = found_std[cat_size]
            break

    if found_size is None:
        raise KeyError(
            f"Size {size!r} not found in standard {standard!r}. "
            f"Available: {list(found_std.keys())}"
        )

    candidates = found_size
    if material is not None:
        mat_lower = material.lower()
        candidates = [s for s in candidates if s.material.lower() == mat_lower]
        if not candidates:
            raise ValueError(
                f"No {standard} {size} entry found with material {material!r}"
            )

    if length_mm is not None:
        lmatch = [s for s in candidates if s.length_mm == length_mm]
        if not lmatch:
            # Try nearest
            with_len = [s for s in candidates if s.length_mm is not None]
            if with_len:
                nearest = min(with_len, key=lambda s: abs((s.length_mm or 0) - length_mm))
                raise ValueError(
                    f"No {standard} {size} at exactly {length_mm}mm. "
                    f"Nearest available: {nearest.length_mm}mm. "
                    f"Use length_mm=None to get the first entry."
                )
            raise ValueError(
                f"No {standard} {size} entries with a length dimension."
            )
        return lmatch[0]

    return candidates[0]


# ---------------------------------------------------------------------------
# Torque recommendation — VDI 2230 simplified K-factor method
# ---------------------------------------------------------------------------

def recommend_torque(
    spec: FastenerSpec,
    friction_coefficient: float = 0.14,
    preload_ratio: float = 0.80,
) -> float:
    """Recommended assembly torque in N·m (VDI 2230 simplified K-factor method).

    T_A = K · F_M · d

    where:
      d     = nominal bolt diameter [m]
      F_M   = assembly preload = preload_ratio × R_p0.2 × A_s  [N]
      K     = tightening-torque coefficient (function of friction):
              K ≈ 0.5·(μ·(d2/d)·(1/cos(α/2) + d_w/(2·d)·μ))
              For metric ISO thread with 60° flank and μ = μ_total the VDI
              2230 simplified form gives K ≈ 0.16 + 0.58·μ + 0.5·μ·(d_w/d)
              where d_w/d ≈ 1.5 for hex heads.
              Practical approximation used here: K = 0.16 + 1.45·μ.
              At μ = 0.12:  K ≈ 0.334 → T ≈ 0.334·F_M·d (matches tables).
              At μ = 0.14 (default): K ≈ 0.363.
              Reference: VDI 2230 Part 1 (2015) Table A3 notes.

    Parameters
    ----------
    spec : FastenerSpec
        The fastener to size.
    friction_coefficient : float
        Overall friction coefficient μ (head face + thread).
        Common values: 0.10 (oiled), 0.12 (lightly oiled), 0.14 (slightly
        oiled/black oxide), 0.20 (dry/zinc-plated), 0.25 (hot-dip galvanised).
    preload_ratio : float
        Fraction of yield strength mobilised as assembly preload.
        VDI 2230 recommends 0.80 for well-controlled torque wrenches.

    Returns
    -------
    float
        Assembly torque T_A in N·m.

    Raises
    ------
    ValueError
        If the material is not in the known strength database.
    KeyError
        (propagated) if spec has no diameter.
    """
    if spec.diameter_mm <= 0:
        raise ValueError(f"Cannot compute torque — invalid diameter: {spec.diameter_mm}")

    if spec.material not in _MATERIAL_STRENGTH:
        raise ValueError(
            f"Material {spec.material!r} not in strength database. "
            f"Known: {list(_MATERIAL_STRENGTH.keys())}"
        )

    _, R_p02 = _MATERIAL_STRENGTH[spec.material]   # yield / 0.2% proof stress (MPa)
    A_s = spec.nominal_stress_area()                # mm²
    F_M = preload_ratio * R_p02 * A_s              # N  (MPa·mm² = N)

    # VDI 2230 Pt1 (2015) K-factor using Shigley thread+collar decomposition.
    #
    # T = T_thread + T_collar  (both in N·mm)
    #
    # T_thread = F_M · (d2/2) · (l + π·μ·d2/cos(α)) / (π·d2/cos(α) − μ·l)
    #   d2 = pitch diameter = d − 0.6495·p
    #   l  = lead = p (single-start)
    #   α  = 30° (half-angle of 60° ISO metric thread flank)
    #
    # T_collar = F_M · μ · d_w / 2
    #   d_w = effective bearing diameter of head/nut contact face:
    #         d_w ≈ (0.9·s + d_h) / 2  where s = wrench_size, d_h = d + 0.5 mm clearance
    #
    # K = T_total / (F_M · d)  [dimensionless, with consistent length units]
    #
    # This yields K ≈ 0.17–0.19 for μ = 0.14, consistent with
    # Shigley Table 8-15, VDI 2230 Table A6, Bickford 4th ed.
    # Reference M10 8.8 μ=0.14: T ≈ 49–53 N·m.

    mu = friction_coefficient
    d = spec.diameter_mm          # mm
    p = spec.thread_pitch         # mm
    alpha_half = math.radians(30)  # 60° thread half-angle
    d2 = d - 0.6495 * p           # pitch diameter, mm
    l = p                          # lead (single-start), mm

    # Thread component (N·mm)
    denom = math.pi * d2 / math.cos(alpha_half) - mu * l
    if denom <= 0:
        # Numerically degenerate (should not happen for standard threads)
        denom = 1e-9
    T_thread = F_M * (d2 / 2) * (l + math.pi * mu * d2 / math.cos(alpha_half)) / denom

    # Collar/bearing component (N·mm): use wrench_size from dimensions if available,
    # otherwise fall back to 1.5·d as a reasonable approximation
    s = spec.dimensions.get(
        "wrench_size",
        spec.dimensions.get("width_across_flats", 1.5 * d)
    )
    d_hole = d + 0.5  # nominal clearance-hole diameter
    d_w = (0.9 * s + d_hole) / 2   # effective bearing diameter
    T_collar = F_M * mu * d_w / 2

    T_total_Nmm = T_thread + T_collar
    T_A = T_total_Nmm / 1000.0   # N·m
    return round(T_A, 3)


# ---------------------------------------------------------------------------
# 3D model stub — lazy generator
# ---------------------------------------------------------------------------

def generate_3d_model(spec: FastenerSpec):
    """Lazy 3D geometry generator for a fastener spec.

    Returns a Body-like object when the OCCT worker is available; raises
    ImportError with a clear message otherwise.  This keeps kerf-parts a
    pure-Python package with no hard dependency on the OCCT geometry kernel.

    The actual parametric geometry uses:
      - Hexagonal prism for the head (DIN 931/933/934)
      - Cylindrical cap for DIN 912/ISO 7380/ISO 4762
      - ISO metric thread profile extruded along the shank
      - Countersink cone for DIN 7991

    Parameters
    ----------
    spec : FastenerSpec

    Returns
    -------
    Body  (kerf_cad_core.body.Body)
        A solid OCCT Body that can be inserted into assemblies or exported to STEP.

    Raises
    ------
    ImportError
        If the OCCT geometry kernel (kerf-cad-core) is not installed.
    NotImplementedError
        For standards or kinds not yet modelled.
    """
    try:
        from kerf_cad_core.fasteners import build_fastener_body  # type: ignore[import]
        return build_fastener_body(spec)
    except ImportError as exc:
        raise ImportError(
            "3D geometry generation requires kerf-cad-core. "
            "Install with: pip install kerf-cad-core\n"
            f"Original error: {exc}"
        ) from exc


# ---------------------------------------------------------------------------
# LLM tool implementations
# ---------------------------------------------------------------------------

def _parts_lookup_fastener(
    standard: str,
    size: str,
    length_mm: Optional[float] = None,
    material: Optional[str] = None,
) -> dict:
    """LLM-callable: look up a DIN/ISO metric fastener and return its dimensions.

    Parameters
    ----------
    standard : str
        Standard identifier (case-insensitive).
        Supported: 'DIN 931', 'DIN 933', 'DIN 912', 'DIN 7991', 'DIN 125',
        'DIN 934', 'ISO 7380', 'ISO 4762'.
    size : str
        Metric size string (case-insensitive), e.g. 'M10', 'm6', 'M20'.
    length_mm : float | None
        Nominal length in mm; None for nuts/washers.
    material : str | None
        Material filter, e.g. 'steel_grade_8.8', 'stainless_a2-70'.

    Returns
    -------
    dict
        Structured result with ``standard``, ``kind``, ``size``, ``length_mm``,
        ``thread_pitch``, ``material``, ``diameter_mm``,
        ``stress_area_mm2``, ``dimensions``, ``disclaimer``.
    """
    try:
        spec = lookup_fastener(standard, size, length_mm=length_mm, material=material)
    except (KeyError, ValueError) as exc:
        return {"ok": False, "error": str(exc)}

    return {
        "ok": True,
        "standard": spec.standard,
        "kind": spec.kind,
        "size": spec.size,
        "length_mm": spec.length_mm,
        "thread_pitch": spec.thread_pitch,
        "material": spec.material,
        "diameter_mm": spec.diameter_mm,
        "stress_area_mm2": round(spec.nominal_stress_area(), 3),
        "dimensions": spec.dimensions,
        "disclaimer": (
            "Standard dimensions from public DIN tables — NOT DIN-certified. "
            "Verify against current published standard for precision/safety-critical use."
        ),
    }


def _parts_torque_recommendation(
    standard: str,
    size: str,
    material: str = "steel_grade_8.8",
    friction_coefficient: float = 0.14,
    preload_ratio: float = 0.80,
) -> dict:
    """LLM-callable: compute VDI 2230 assembly torque for a metric fastener.

    Parameters
    ----------
    standard : str
        Fastener standard, e.g. 'DIN 931', 'DIN 912'.
    size : str
        Metric size, e.g. 'M10'.
    material : str
        Material property key; default 'steel_grade_8.8'.
    friction_coefficient : float
        Total friction coefficient μ (thread + bearing face). Default 0.14
        (slightly oiled). Common: 0.10 (oil), 0.14 (slight oil), 0.20 (dry).
    preload_ratio : float
        Fraction of yield strength used as assembly preload. Default 0.80
        (recommended by VDI 2230 for controlled torque).

    Returns
    -------
    dict
        ``torque_Nm``, ``preload_N``, ``friction_coefficient``,
        ``material``, ``stress_area_mm2``, ``method``, ``disclaimer``.
    """
    try:
        spec = lookup_fastener(standard, size, material=material)
    except (KeyError, ValueError) as exc:
        return {"ok": False, "error": str(exc)}

    try:
        torque = recommend_torque(spec, friction_coefficient, preload_ratio)
    except (ValueError, KeyError) as exc:
        return {"ok": False, "error": str(exc)}

    _, R_p02 = _MATERIAL_STRENGTH[spec.material]
    A_s = spec.nominal_stress_area()
    F_M = preload_ratio * R_p02 * A_s

    return {
        "ok": True,
        "standard": spec.standard,
        "size": spec.size,
        "material": spec.material,
        "torque_Nm": torque,
        "preload_N": round(F_M, 1),
        "friction_coefficient": friction_coefficient,
        "preload_ratio": preload_ratio,
        "stress_area_mm2": round(A_s, 3),
        "method": "VDI 2230 Part 1 (2015) simplified K-factor: T = K·F_M·d",
        "disclaimer": (
            "For reference calculations only — NOT DIN-certified. "
            "Verify against VDI 2230 Part 1 (2015) for safety-critical joints."
        ),
    }


# ---------------------------------------------------------------------------
# LLM tool registry — same shape as kerf-aero AEROSPACE_TOOLS
# ---------------------------------------------------------------------------

PARTS_FASTENER_TOOLS: list[dict] = [
    {
        "name": "parts_lookup_fastener",
        "fn": _parts_lookup_fastener,
        "description": (
            "Look up dimensions for a DIN/ISO metric fastener (hex bolts, cap screws, "
            "washers, nuts). Returns head geometry, thread pitch, and material from "
            "the built-in DIN 931/933/912/7991/125/934 and ISO 7380/4762 catalog. "
            "Standard dimensions from public DIN tables — NOT DIN-certified."
        ),
    },
    {
        "name": "parts_torque_recommendation",
        "fn": _parts_torque_recommendation,
        "description": (
            "Compute VDI 2230 assembly torque for a metric fastener. "
            "Returns recommended tightening torque (N·m), preload force (N), "
            "and stress area based on material yield strength and thread geometry. "
            "Method: T = K·F_M·d per VDI 2230 Part 1 (2015)."
        ),
    },
]

__all__ = [
    "FastenerSpec",
    "DIN_FASTENERS_CATALOG",
    "lookup_fastener",
    "recommend_torque",
    "generate_3d_model",
    "PARTS_FASTENER_TOOLS",
]
