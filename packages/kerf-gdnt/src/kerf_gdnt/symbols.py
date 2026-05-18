"""
GD&T / PMI symbols — ISO 1101:2017 + ASME Y14.5-2018.

Each symbol has:
  - ``code``      — canonical short identifier (ASCII-safe, used in APIs)
  - ``unicode``   — the Unicode character(s) from ISO/ASME character sets
  - ``name``      — human-readable English name
  - ``category``  — form / orientation / location / runout / profile
  - ``iso_code``  — ISO 1101 clause reference
  - ``asme_code`` — ASME Y14.5-2018 section reference

Modifier symbols (material condition, etc.) are defined separately in
:data:`MODIFIERS`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


Category = Literal["form", "orientation", "location", "runout", "profile"]


@dataclass(frozen=True)
class GDTSymbol:
    code: str
    unicode: str
    name: str
    category: Category
    iso_code: str       # e.g. "ISO 1101:2017 §17.1"
    asme_code: str      # e.g. "ASME Y14.5-2018 §10.1"


# ---------------------------------------------------------------------------
# Form tolerances
# ---------------------------------------------------------------------------

STRAIGHTNESS = GDTSymbol(
    code="straightness",
    unicode="⎯",       # ⏯  — ISO uses a horizontal line ─  (U+23AF)
    name="Straightness",
    category="form",
    iso_code="ISO 1101:2017 §17.2",
    asme_code="ASME Y14.5-2018 §12.4",
)

FLATNESS = GDTSymbol(
    code="flatness",
    unicode="▱",       # ▱  parallelogram (ISO 1101 / ASME symbol for flatness)
    name="Flatness",
    category="form",
    iso_code="ISO 1101:2017 §17.3",
    asme_code="ASME Y14.5-2018 §12.5",
)

CIRCULARITY = GDTSymbol(
    code="circularity",
    unicode="○",       # ○  circle
    name="Circularity (Roundness)",
    category="form",
    iso_code="ISO 1101:2017 §17.4",
    asme_code="ASME Y14.5-2018 §12.6",
)

CYLINDRICITY = GDTSymbol(
    code="cylindricity",
    unicode="⌭",       # ⌭  cylinder symbol
    name="Cylindricity",
    category="form",
    iso_code="ISO 1101:2017 §17.5",
    asme_code="ASME Y14.5-2018 §12.7",
)

# ---------------------------------------------------------------------------
# Profile tolerances
# ---------------------------------------------------------------------------

PROFILE_LINE = GDTSymbol(
    code="profile_line",
    unicode="⌒",       # ⌒  arc
    name="Profile of a Line",
    category="profile",
    iso_code="ISO 1101:2017 §17.6",
    asme_code="ASME Y14.5-2018 §11.5",
)

PROFILE_SURFACE = GDTSymbol(
    code="profile_surface",
    unicode="⌓",       # ⌓  surface profile symbol
    name="Profile of a Surface",
    category="profile",
    iso_code="ISO 1101:2017 §17.7",
    asme_code="ASME Y14.5-2018 §11.6",
)

# ---------------------------------------------------------------------------
# Orientation tolerances
# ---------------------------------------------------------------------------

ANGULARITY = GDTSymbol(
    code="angularity",
    unicode="∠",       # ∠  angle sign
    name="Angularity",
    category="orientation",
    iso_code="ISO 1101:2017 §17.8",
    asme_code="ASME Y14.5-2018 §10.4",
)

PERPENDICULARITY = GDTSymbol(
    code="perpendicularity",
    unicode="⟂",       # ⟂  perpendicular
    name="Perpendicularity",
    category="orientation",
    iso_code="ISO 1101:2017 §17.9",
    asme_code="ASME Y14.5-2018 §10.5",
)

PARALLELISM = GDTSymbol(
    code="parallelism",
    unicode="⼏",       # ⼏  — ISO uses // (two slashes); closest Unicode U+2016 ‖
    name="Parallelism",
    category="orientation",
    iso_code="ISO 1101:2017 §17.10",
    asme_code="ASME Y14.5-2018 §10.6",
)

# ---------------------------------------------------------------------------
# Location tolerances
# ---------------------------------------------------------------------------

POSITION = GDTSymbol(
    code="position",
    unicode="⌖",       # ⌖  position target symbol
    name="Position",
    category="location",
    iso_code="ISO 1101:2017 §17.11",
    asme_code="ASME Y14.5-2018 §9.4",
)

CONCENTRICITY = GDTSymbol(
    code="concentricity",
    unicode="◎",       # ◎  bullseye (coaxiality / concentricity)
    name="Concentricity / Coaxiality",
    category="location",
    iso_code="ISO 1101:2017 §17.13",
    asme_code="ASME Y14.5-2018 §9.9",
)

SYMMETRY = GDTSymbol(
    code="symmetry",
    unicode="⌯",       # ⌯  symmetry symbol
    name="Symmetry",
    category="location",
    iso_code="ISO 1101:2017 §17.14",
    asme_code="ASME Y14.5-2018 §9.10",
)

# ---------------------------------------------------------------------------
# Runout tolerances
# ---------------------------------------------------------------------------

CIRCULAR_RUNOUT = GDTSymbol(
    code="circular_runout",
    unicode="↗",       # ↗  single arrow (ASME/ISO circular runout)
    name="Circular Runout",
    category="runout",
    iso_code="ISO 1101:2017 §17.15",
    asme_code="ASME Y14.5-2018 §13.4",
)

TOTAL_RUNOUT = GDTSymbol(
    code="total_runout",
    unicode="⇈",       # ⇈  double upward arrow (total runout)
    name="Total Runout",
    category="runout",
    iso_code="ISO 1101:2017 §17.16",
    asme_code="ASME Y14.5-2018 §13.5",
)

# ---------------------------------------------------------------------------
# Master registry
# ---------------------------------------------------------------------------

ALL_SYMBOLS: dict[str, GDTSymbol] = {
    s.code: s
    for s in [
        STRAIGHTNESS, FLATNESS, CIRCULARITY, CYLINDRICITY,
        PROFILE_LINE, PROFILE_SURFACE,
        ANGULARITY, PERPENDICULARITY, PARALLELISM,
        POSITION, CONCENTRICITY, SYMMETRY,
        CIRCULAR_RUNOUT, TOTAL_RUNOUT,
    ]
}


# ---------------------------------------------------------------------------
# Modifier symbols (material condition, projection, tangent, etc.)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Modifier:
    code: str
    unicode: str
    name: str
    iso_code: str
    asme_code: str


MODIFIER_MMC = Modifier(
    code="M",
    unicode="Ⓜ",   # Ⓜ  circled M — Maximum Material Condition
    name="Maximum Material Condition (MMC)",
    iso_code="ISO 2692:2014 §3.1",
    asme_code="ASME Y14.5-2018 §2.11.4",
)

MODIFIER_LMC = Modifier(
    code="L",
    unicode="Ⓛ",   # Ⓛ  circled L — Least Material Condition
    name="Least Material Condition (LMC)",
    iso_code="ISO 2692:2014 §3.2",
    asme_code="ASME Y14.5-2018 §2.11.5",
)

MODIFIER_RFS = Modifier(
    code="S",
    unicode="Ⓢ",   # Ⓢ  circled S — Regardless of Feature Size (default)
    name="Regardless of Feature Size (RFS)",
    iso_code="ISO 1101:2017 §A.2",
    asme_code="ASME Y14.5-2018 §2.11.3",
)

MODIFIER_FREE_STATE = Modifier(
    code="F",
    unicode="Ⓕ",   # Ⓕ  circled F — Free State
    name="Free State",
    iso_code="ISO 10579:2010 §3.1",
    asme_code="ASME Y14.5-2018 §5.6",
)

MODIFIER_PROJECTED = Modifier(
    code="P",
    unicode="Ⓟ",   # Ⓟ  circled P — Projected Tolerance Zone
    name="Projected Tolerance Zone",
    iso_code="ISO 1101:2017 §A.3",
    asme_code="ASME Y14.5-2018 §9.8",
)

MODIFIER_TANGENT = Modifier(
    code="T",
    unicode="Ⓣ",   # Ⓣ  circled T — Tangent Plane
    name="Tangent Plane",
    iso_code="ISO 1101:2017 §A.4",
    asme_code="ASME Y14.5-2018 §6.6",
)

MODIFIER_DIAMETER = Modifier(
    code="dia",
    unicode="⌀",   # ⌀  diameter sign
    name="Diameter",
    iso_code="ISO 1101:2017 §A.5",
    asme_code="ASME Y14.5-2018 §3.3.17",
)

ALL_MODIFIERS: dict[str, Modifier] = {
    m.code: m
    for m in [
        MODIFIER_MMC, MODIFIER_LMC, MODIFIER_RFS,
        MODIFIER_FREE_STATE, MODIFIER_PROJECTED, MODIFIER_TANGENT,
        MODIFIER_DIAMETER,
    ]
}


def get_symbol(code: str) -> GDTSymbol:
    """Return the :class:`GDTSymbol` for *code*, raising ``KeyError`` if unknown."""
    return ALL_SYMBOLS[code]


def get_modifier(code: str) -> Modifier:
    """Return the :class:`Modifier` for *code*, raising ``KeyError`` if unknown."""
    return ALL_MODIFIERS[code]
