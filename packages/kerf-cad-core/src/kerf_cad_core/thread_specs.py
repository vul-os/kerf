"""
thread_specs — ISO metric and Unified (UTS) thread specification catalog.

Thread dimensions are factual standard nominal constants derived from:
  - ISO 261:2013  (metric thread series selection)
  - ISO 965-1:1998 (metric thread tolerances, 6H/6g reference)
  - ASME B1.1-2003 (Unified Inch Screw Threads — UNC/UNF)

All values are **original computed/derived nominal dimensions**, not a
redistribution of any proprietary database.  Formulas used:

  Metric (ISO):
    pitch P given in catalog
    minor_dia  = major_dia - 1.226869 * P    (ISO 68-1 formula for 60° thread)
    tap_drill  = major_dia - P               (common workshop approximation for
                                              ~75% thread engagement, ISO 228)

  UTS (ASME B1.1):
    TPI given in catalog
    P_in       = 1 / TPI  (inches)
    minor_dia  = major_dia_in - 1.299038 * P_in   (60° thread, same formula)
    tap_drill  = major_dia_in - P_in              (same ~75% approximation)
    All inch values also stored in mm (×25.4).

Author: imranparuk
"""

from __future__ import annotations

from typing import TypedDict

# ---------------------------------------------------------------------------
# Typed record for a single thread spec entry
# ---------------------------------------------------------------------------

class ThreadSpec(TypedDict, total=False):
    designation: str        # canonical short form, e.g. "M6", "1/4-20 UNC"
    standard: str           # "ISO metric" | "UTS UNC" | "UTS UNF"
    system: str             # "metric" | "inch"
    major_dia_mm: float     # nominal major diameter, mm
    pitch_mm: float         # thread pitch, mm
    minor_dia_mm: float     # minor (root) diameter, mm
    tap_drill_mm: float     # tap-drill diameter, mm (75% engagement approx)
    major_dia_in: float     # nominal major diameter, inches (UTS only)
    pitch_in: float         # thread pitch, inches (UTS only)
    minor_dia_in: float     # minor diameter, inches (UTS only)
    tap_drill_in: float     # tap-drill diameter, inches (UTS only)
    thread_class: str       # default tolerance class: "6H/6g" (metric) / "2B/2A" (UTS)
    series: str             # "coarse" | "fine"


# ---------------------------------------------------------------------------
# ISO Metric coarse thread data — ISO 261 / ISO 965-1
# major_dia_mm, pitch_mm — exact standard nominal values
# minor_dia and tap_drill computed from ISO 68-1 formula
# ---------------------------------------------------------------------------

def _metric_spec(
    desig: str,
    major_mm: float,
    pitch_mm: float,
    series: str = "coarse",
) -> ThreadSpec:
    minor = round(major_mm - 1.226869 * pitch_mm, 4)
    tap   = round(major_mm - pitch_mm, 4)
    return ThreadSpec(
        designation=desig,
        standard="ISO metric",
        system="metric",
        major_dia_mm=major_mm,
        pitch_mm=pitch_mm,
        minor_dia_mm=minor,
        tap_drill_mm=tap,
        thread_class="6H/6g",
        series=series,
    )


# ISO 261 — coarse pitch series (M1.6 through M64)
# Data: (designation, major_dia_mm, pitch_mm)
_METRIC_COARSE_RAW: list[tuple[str, float, float]] = [
    ("M1.6",  1.6,   0.35),
    ("M2",    2.0,   0.40),
    ("M2.5",  2.5,   0.45),
    ("M3",    3.0,   0.50),
    ("M3.5",  3.5,   0.60),
    ("M4",    4.0,   0.70),
    ("M5",    5.0,   0.80),
    ("M6",    6.0,   1.00),
    ("M7",    7.0,   1.00),
    ("M8",    8.0,   1.25),
    ("M10",  10.0,   1.50),
    ("M12",  12.0,   1.75),
    ("M14",  14.0,   2.00),
    ("M16",  16.0,   2.00),
    ("M18",  18.0,   2.50),
    ("M20",  20.0,   2.50),
    ("M22",  22.0,   2.50),
    ("M24",  24.0,   3.00),
    ("M27",  27.0,   3.00),
    ("M30",  30.0,   3.50),
    ("M33",  33.0,   3.50),
    ("M36",  36.0,   4.00),
    ("M39",  39.0,   4.00),
    ("M42",  42.0,   4.50),
    ("M45",  45.0,   4.50),
    ("M48",  48.0,   5.00),
    ("M52",  52.0,   5.00),
    ("M56",  56.0,   5.50),
    ("M60",  60.0,   5.50),
    ("M64",  64.0,   6.00),
]

# ISO 261 — selected fine pitch series
# Each tuple: (base_designation, pitch_designation, major_dia_mm, pitch_mm)
_METRIC_FINE_RAW: list[tuple[str, float, float]] = [
    ("M8x1",    8.0,  1.00),
    ("M10x1",  10.0,  1.00),
    ("M10x1.25",10.0, 1.25),
    ("M12x1.25",12.0, 1.25),
    ("M12x1.5", 12.0, 1.50),
    ("M14x1.5", 14.0, 1.50),
    ("M16x1.5", 16.0, 1.50),
    ("M18x1.5", 18.0, 1.50),
    ("M20x1.5", 20.0, 1.50),
    ("M20x2",   20.0, 2.00),
    ("M24x1.5", 24.0, 1.50),
    ("M24x2",   24.0, 2.00),
    ("M30x1.5", 30.0, 1.50),
    ("M30x2",   30.0, 2.00),
    ("M36x1.5", 36.0, 1.50),
    ("M36x3",   36.0, 3.00),
    ("M42x2",   42.0, 2.00),
    ("M48x2",   48.0, 2.00),
    ("M6x0.75",  6.0, 0.75),
]

# Build lookup: designation → ThreadSpec
METRIC_COARSE: dict[str, ThreadSpec] = {
    d: _metric_spec(d, maj, p, "coarse")
    for d, maj, p in _METRIC_COARSE_RAW
}

METRIC_FINE: dict[str, ThreadSpec] = {
    d: _metric_spec(d, maj, p, "fine")
    for d, maj, p in _METRIC_FINE_RAW
}

METRIC_ALL: dict[str, ThreadSpec] = {**METRIC_COARSE, **METRIC_FINE}


# ---------------------------------------------------------------------------
# UTS (Unified National) thread data — ASME B1.1-2003
# Numbered sizes and fractional sizes, UNC and UNF series.
# Data: (designation, major_dia_in, tpi, series_label)
# ---------------------------------------------------------------------------

def _uts_spec(
    desig: str,
    major_in: float,
    tpi: float,
    standard: str,
    series: str,
) -> ThreadSpec:
    p_in   = 1.0 / tpi
    minor  = major_in - 1.299038 * p_in
    tap    = major_in - p_in
    mm     = 25.4
    return ThreadSpec(
        designation=desig,
        standard=standard,
        system="inch",
        major_dia_mm=round(major_in * mm, 4),
        pitch_mm=round(p_in * mm, 4),
        minor_dia_mm=round(minor * mm, 4),
        tap_drill_mm=round(tap * mm, 4),
        major_dia_in=round(major_in, 6),
        pitch_in=round(p_in, 6),
        minor_dia_in=round(minor, 6),
        tap_drill_in=round(tap, 6),
        thread_class="2B/2A",
        series=series,
    )


# ASME B1.1 — numbered machine screw sizes (UNC and UNF)
# major diameter for numbered sizes: d = 0.060 + 0.013 × N  (ASME B1.1 formula)
# Values listed below match ASME B1.1 Table 2 nominal major diameters.

_UTS_NUMBERED_RAW: list[tuple[str, float, float, str]] = [
    # designation, major_dia_in, tpi, standard
    # UNC
    ("#0-80 UNF",   0.0600, 80,  "UTS UNF"),   # #0 is fine only
    ("#1-64 UNC",   0.0730, 64,  "UTS UNC"),
    ("#1-72 UNF",   0.0730, 72,  "UTS UNF"),
    ("#2-56 UNC",   0.0860, 56,  "UTS UNC"),
    ("#2-64 UNF",   0.0860, 64,  "UTS UNF"),
    ("#3-48 UNC",   0.0990, 48,  "UTS UNC"),
    ("#3-56 UNF",   0.0990, 56,  "UTS UNF"),
    ("#4-40 UNC",   0.1120, 40,  "UTS UNC"),
    ("#4-48 UNF",   0.1120, 48,  "UTS UNF"),
    ("#5-40 UNC",   0.1250, 40,  "UTS UNC"),
    ("#5-44 UNF",   0.1250, 44,  "UTS UNF"),
    ("#6-32 UNC",   0.1380, 32,  "UTS UNC"),
    ("#6-40 UNF",   0.1380, 40,  "UTS UNF"),
    ("#8-32 UNC",   0.1640, 32,  "UTS UNC"),
    ("#8-36 UNF",   0.1640, 36,  "UTS UNF"),
    ("#10-24 UNC",  0.1900, 24,  "UTS UNC"),
    ("#10-32 UNF",  0.1900, 32,  "UTS UNF"),
    ("#12-24 UNC",  0.2160, 24,  "UTS UNC"),
    ("#12-28 UNF",  0.2160, 28,  "UTS UNF"),
]

_UTS_FRACTIONAL_RAW: list[tuple[str, float, float, str]] = [
    # UNC fractional
    ("1/4-20 UNC",   0.2500, 20,  "UTS UNC"),
    ("1/4-28 UNF",   0.2500, 28,  "UTS UNF"),
    ("5/16-18 UNC",  0.3125, 18,  "UTS UNC"),
    ("5/16-24 UNF",  0.3125, 24,  "UTS UNF"),
    ("3/8-16 UNC",   0.3750, 16,  "UTS UNC"),
    ("3/8-24 UNF",   0.3750, 24,  "UTS UNF"),
    ("7/16-14 UNC",  0.4375, 14,  "UTS UNC"),
    ("7/16-20 UNF",  0.4375, 20,  "UTS UNF"),
    ("1/2-13 UNC",   0.5000, 13,  "UTS UNC"),
    ("1/2-20 UNF",   0.5000, 20,  "UTS UNF"),
    ("9/16-12 UNC",  0.5625, 12,  "UTS UNC"),
    ("9/16-18 UNF",  0.5625, 18,  "UTS UNF"),
    ("5/8-11 UNC",   0.6250, 11,  "UTS UNC"),
    ("5/8-18 UNF",   0.6250, 18,  "UTS UNF"),
    ("3/4-10 UNC",   0.7500, 10,  "UTS UNC"),
    ("3/4-16 UNF",   0.7500, 16,  "UTS UNF"),
    ("7/8-9 UNC",    0.8750,  9,  "UTS UNC"),
    ("7/8-14 UNF",   0.8750, 14,  "UTS UNF"),
    ("1-8 UNC",      1.0000,  8,  "UTS UNC"),
    ("1-14 UNF",     1.0000, 14,  "UTS UNF"),
    ("1 1/4-7 UNC",  1.2500,  7,  "UTS UNC"),
    ("1 1/4-12 UNF", 1.2500, 12,  "UTS UNF"),
    ("1 1/2-6 UNC",  1.5000,  6,  "UTS UNC"),
    ("1 1/2-12 UNF", 1.5000, 12,  "UTS UNF"),
]


def _build_uts(raw: list[tuple[str, float, float, str]]) -> dict[str, ThreadSpec]:
    out: dict[str, ThreadSpec] = {}
    for desig, major_in, tpi, std in raw:
        series = "coarse" if "UNC" in std else "fine"
        out[desig] = _uts_spec(desig, major_in, tpi, std, series)
    return out


UTS_ALL: dict[str, ThreadSpec] = {
    **_build_uts(_UTS_NUMBERED_RAW),
    **_build_uts(_UTS_FRACTIONAL_RAW),
}

# ---------------------------------------------------------------------------
# Combined master catalog
# ---------------------------------------------------------------------------

ALL_THREADS: dict[str, ThreadSpec] = {**METRIC_ALL, **UTS_ALL}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def lookup(designation: str) -> ThreadSpec | None:
    """Return spec for *designation* or None if not found (case-sensitive)."""
    return ALL_THREADS.get(designation)


def metric_coarse_designations() -> list[str]:
    """Return all ISO metric coarse designations in ascending size order."""
    return [d for d, _, _ in _METRIC_COARSE_RAW]


def uts_unc_designations() -> list[str]:
    """Return all UNC designations."""
    return [d for d, _, _, s in _UTS_NUMBERED_RAW + _UTS_FRACTIONAL_RAW if "UNC" in s]


def uts_unf_designations() -> list[str]:
    """Return all UNF designations."""
    return [d for d, _, _, s in _UTS_NUMBERED_RAW + _UTS_FRACTIONAL_RAW if "UNF" in s]
