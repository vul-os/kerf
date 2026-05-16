"""
kerf_cad_core.struct.framing — columns, beams, and steel section catalog.

SECTION CATALOG
---------------
Nominal published dimensions for common structural steel sections.
Values are well-known engineering constants taken from publicly available
nominal dimension tables (Euronorm / AISC).  These are factual nominal
values, NOT copied from any proprietary software database or licensed table.
All values are rounded to standard published nominal figures.

Units in this catalog:
  A      — cross-sectional area (mm²)
  Ix     — second moment of area about strong axis (mm⁴)
  Iy     — second moment of area about weak axis (mm⁴)
  mass   — nominal mass per unit length (kg/m)

Sections included (~12 representative profiles):
  IPE  — European I-beams (EN 10034)
  HEA  — European wide-flange (light series, EN 53-62)
  UB   — British universal beams (BS 4-1)
  W    — AISC wide-flange (US customary, metric equivalents)

FRAMING MEMBERS
---------------
Column — vertical member spanning base_level → top_level at a grid point.
Beam   — horizontal member spanning two grid points at a given level.

Both Column and Beam carry a section name resolved from SECTION_CATALOG.
Length is derived from level elevations (Column) or grid-point coordinates
(Beam).

Mass = length (m) × section.mass (kg/m)

Validation: never raises; returns (ok, errors) tuples on bad input.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional

from kerf_cad_core.struct.grid import GridPoint, Level


# ---------------------------------------------------------------------------
# Section catalog
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SteelSection:
    """
    Nominal cross-section properties for a structural steel section.

    All values are published nominal figures; no proprietary database.
    Source: Euronorm EN 10034 (IPE/HEA), BS 4-1 (UB), AISC Steel Construction
    Manual (W-sections).  The values below are the standard nominal/tabulated
    values widely reproduced in engineering references.

    Attributes
    ----------
    name    : section designation, e.g. "IPE200"
    family  : one of "IPE", "HEA", "UB", "W"
    A_mm2   : cross-sectional area (mm²)
    Ix_mm4  : second moment of area, strong axis (mm⁴)
    Iy_mm4  : second moment of area, weak axis (mm⁴)
    mass_kg_m : nominal mass per metre (kg/m)
    """
    name: str
    family: str
    A_mm2: float
    Ix_mm4: float
    Iy_mm4: float
    mass_kg_m: float

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "family": self.family,
            "A_mm2": self.A_mm2,
            "Ix_mm4": self.Ix_mm4,
            "Iy_mm4": self.Iy_mm4,
            "mass_kg_m": self.mass_kg_m,
        }


# ---------------------------------------------------------------------------
# Catalog — nominal published values
#
# IPE sections: EN 10034 nominal dimensions (Euronorm)
#   IPE 160: A=2009 mm², Ix=8.69e6 mm⁴, Iy=0.683e6 mm⁴, 12.7 kg/m
#   IPE 200: A=2848 mm², Ix=19.43e6 mm⁴, Iy=1.424e6 mm⁴, 22.4 kg/m
#   IPE 270: A=4594 mm², Ix=57.9e6 mm⁴, Iy=4.20e6 mm⁴, 36.1 kg/m
#   IPE 360: A=7273 mm², Ix=162.7e6 mm⁴, Iy=10.43e6 mm⁴, 57.1 kg/m
#
# HEA sections: EN 53-62 nominal (European wide-flange, light series)
#   HEA 200: A=5383 mm², Ix=36.92e6 mm⁴, Iy=13.36e6 mm⁴, 42.3 kg/m
#   HEA 300: A=11250 mm², Ix=182.6e6 mm⁴, Iy=63.1e6 mm⁴, 88.3 kg/m
#   HEA 400: A=15900 mm², Ix=450.1e6 mm⁴, Iy=155.8e6 mm⁴, 124.8 kg/m
#
# UB sections: BS 4-1 nominal
#   UB 203x133x25: A=3230 mm², Ix=28.5e6 mm⁴, Iy=3.56e6 mm⁴, 25.1 kg/m
#   UB 356x171x51: A=6490 mm², Ix=141.1e6 mm⁴, Iy=12.06e6 mm⁴, 51.0 kg/m
#
# W sections: AISC Steel Construction Manual, 15th ed., Table 1-1 (W-shapes),
# converted to SI (1 in⁴ = 25.4⁴ mm⁴ = 416231.426 mm⁴; 1 in² = 645.16 mm²;
# 1 lb/ft = 1.4881639 kg/m):
#   W8x31:  A=9.13 in²,  Ix=110 in⁴, Iy=37.1 in⁴ → A=5890, Ix=45.79e6, Iy=15.44e6, 46.1 kg/m
#   W12x50: A=14.6 in²,  Ix=391 in⁴, Iy=56.3 in⁴ → A=9419, Ix=162.7e6, Iy=23.43e6, 74.4 kg/m
#   W14x68: A=20.0 in²,  Ix=722 in⁴, Iy=121 in⁴  → A=12903, Ix=300.5e6, Iy=50.36e6, 101.2 kg/m
# ---------------------------------------------------------------------------

SECTION_CATALOG: dict[str, SteelSection] = {s.name: s for s in [
    # ── IPE (Euronorm EN 10034) ──────────────────────────────────────────────
    SteelSection("IPE160",  "IPE",  2009.0,   8.69e6,  0.683e6,  12.7),
    SteelSection("IPE200",  "IPE",  2848.0,  19.43e6,  1.424e6,  22.4),
    SteelSection("IPE270",  "IPE",  4594.0,  57.9e6,   4.20e6,   36.1),
    SteelSection("IPE360",  "IPE",  7273.0, 162.7e6,  10.43e6,   57.1),
    # ── HEA (EN 53-62, light wide-flange) ────────────────────────────────────
    SteelSection("HEA200",  "HEA",  5383.0,  36.92e6,  13.36e6,  42.3),
    SteelSection("HEA300",  "HEA", 11250.0, 182.6e6,   63.1e6,   88.3),
    SteelSection("HEA400",  "HEA", 15900.0, 450.1e6,  155.8e6,  124.8),
    # ── UB (BS 4-1) ──────────────────────────────────────────────────────────
    SteelSection("UB203x133x25", "UB",  3230.0,  28.5e6,   3.56e6,  25.1),
    SteelSection("UB356x171x51", "UB",  6490.0, 141.1e6,  12.06e6,  51.0),
    # ── W (AISC, metric equivalents) ─────────────────────────────────────────
    SteelSection("W8x31",   "W",   5890.0,  45.79e6,  15.44e6,  46.1),
    SteelSection("W12x50",  "W",   9419.0, 162.7e6,   23.43e6,  74.4),
    SteelSection("W14x68",  "W",  12903.0, 300.5e6,   50.36e6, 101.2),
]}


def get_section(name: str) -> Optional[SteelSection]:
    """Return a SteelSection by name (case-insensitive) or None."""
    return SECTION_CATALOG.get(name) or SECTION_CATALOG.get(name.upper())


# ---------------------------------------------------------------------------
# Column
# ---------------------------------------------------------------------------

@dataclass
class Column:
    """
    Vertical structural column spanning base_level → top_level at grid_point.

    Attributes
    ----------
    id          : unique member identifier (user-supplied or auto-generated)
    grid_label  : grid intersection, e.g. "B/3"
    grid_point  : resolved GridPoint (coordinates in mm)
    section     : SteelSection from catalog
    base_level  : Level at the column base
    top_level   : Level at the column top
    """
    id: str
    grid_label: str
    grid_point: GridPoint
    section: SteelSection
    base_level: Level
    top_level: Level

    @property
    def length_mm(self) -> float:
        """Column length = top elevation - base elevation (mm)."""
        return abs(self.top_level.elevation_mm - self.base_level.elevation_mm)

    @property
    def mass_kg(self) -> float:
        """Steel mass = length (m) × section mass (kg/m)."""
        return (self.length_mm / 1000.0) * self.section.mass_kg_m

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "type": "column",
            "grid_label": self.grid_label,
            "x_mm": self.grid_point.x_mm,
            "y_mm": self.grid_point.y_mm,
            "section": self.section.name,
            "base_level": self.base_level.name,
            "top_level": self.top_level.name,
            "base_elevation_mm": self.base_level.elevation_mm,
            "top_elevation_mm": self.top_level.elevation_mm,
            "length_mm": round(self.length_mm, 3),
            "mass_kg": round(self.mass_kg, 4),
        }


# ---------------------------------------------------------------------------
# Beam
# ---------------------------------------------------------------------------

@dataclass
class Beam:
    """
    Horizontal structural beam spanning from start_grid_point to end_grid_point
    at a given level.

    Attributes
    ----------
    id              : unique member identifier
    start_label     : grid label of start point, e.g. "A/2"
    end_label       : grid label of end point, e.g. "C/2"
    start_point     : resolved GridPoint
    end_point       : resolved GridPoint
    section         : SteelSection from catalog
    level           : Level at which the beam sits
    """
    id: str
    start_label: str
    end_label: str
    start_point: GridPoint
    end_point: GridPoint
    section: SteelSection
    level: Level

    @property
    def length_mm(self) -> float:
        """Beam length = Euclidean distance between start and end in the XY plane (mm)."""
        dx = self.end_point.x_mm - self.start_point.x_mm
        dy = self.end_point.y_mm - self.start_point.y_mm
        return math.sqrt(dx * dx + dy * dy)

    @property
    def mass_kg(self) -> float:
        """Steel mass = length (m) × section mass (kg/m)."""
        return (self.length_mm / 1000.0) * self.section.mass_kg_m

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "type": "beam",
            "start_label": self.start_label,
            "end_label": self.end_label,
            "start_x_mm": self.start_point.x_mm,
            "start_y_mm": self.start_point.y_mm,
            "end_x_mm": self.end_point.x_mm,
            "end_y_mm": self.end_point.y_mm,
            "section": self.section.name,
            "level": self.level.name,
            "elevation_mm": self.level.elevation_mm,
            "length_mm": round(self.length_mm, 3),
            "mass_kg": round(self.mass_kg, 4),
        }
