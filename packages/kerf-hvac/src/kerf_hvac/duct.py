"""duct.py — DuctSystem data model.

Supports rectangular, round, and oval ducts with the following fittings:
  elbow, reducer, tee, cap, flex

All dimensions are in millimetres (mm) unless otherwise noted.
Airflow in m³/s (SI) throughout; helper conversions for CFM are provided.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


# ---------------------------------------------------------------------------
# Unit conversion helpers
# ---------------------------------------------------------------------------

def cfm_to_m3s(cfm: float) -> float:
    """Convert CFM (cubic feet per minute) to m³/s."""
    return cfm * 4.719474432e-4


def m3s_to_cfm(m3s: float) -> float:
    """Convert m³/s to CFM."""
    return m3s / 4.719474432e-4


def fpm_to_ms(fpm: float) -> float:
    """Convert feet-per-minute to m/s."""
    return fpm * 5.08e-3


def ms_to_fpm(ms: float) -> float:
    """Convert m/s to feet-per-minute."""
    return ms / 5.08e-3


def inch_to_mm(inch: float) -> float:
    """Convert inches to mm."""
    return inch * 25.4


def mm_to_inch(mm: float) -> float:
    """Convert mm to inches."""
    return mm / 25.4


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

class DuctShape(str, Enum):
    RECTANGULAR = "rectangular"
    ROUND = "round"
    OVAL = "oval"


class FittingType(str, Enum):
    ELBOW = "elbow"
    REDUCER = "reducer"
    TEE = "tee"
    CAP = "cap"
    FLEX = "flex"


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class DuctSection:
    """A straight duct segment.

    For rectangular ducts: width_mm and height_mm must be set.
    For round ducts: diameter_mm must be set.
    For oval ducts: width_mm (major) and height_mm (minor) must be set, with
        the oval approximated as a rectangle with semicircular ends.

    Args:
        shape: Cross-section shape.
        length_mm: Length of the section in mm.
        airflow_m3s: Design airflow through this section in m³/s.
        width_mm: Width (or major axis for oval) in mm.
        height_mm: Height (or minor axis for oval) in mm.
        diameter_mm: Diameter for round ducts in mm.
        material: Duct material string, e.g. 'galvanised_steel'.
        roughness_mm: Absolute roughness of inner wall (mm). Default 0.09 mm
            (galvanised steel per ASHRAE HOF).
        insulation_thickness_mm: External insulation thickness in mm.
        label: Optional descriptive label.
    """

    shape: DuctShape
    length_mm: float
    airflow_m3s: float
    width_mm: Optional[float] = None
    height_mm: Optional[float] = None
    diameter_mm: Optional[float] = None
    material: str = "galvanised_steel"
    roughness_mm: float = 0.09
    insulation_thickness_mm: float = 25.0
    label: Optional[str] = None

    # ------------------------------------------------------------------
    # Derived geometry
    # ------------------------------------------------------------------

    def area_m2(self) -> float:
        """Cross-sectional area in m²."""
        if self.shape == DuctShape.ROUND:
            if self.diameter_mm is None:
                raise ValueError("diameter_mm required for round duct")
            r = (self.diameter_mm / 1000) / 2
            return math.pi * r * r
        elif self.shape == DuctShape.RECTANGULAR:
            if self.width_mm is None or self.height_mm is None:
                raise ValueError("width_mm and height_mm required for rectangular duct")
            return (self.width_mm / 1000) * (self.height_mm / 1000)
        elif self.shape == DuctShape.OVAL:
            if self.width_mm is None or self.height_mm is None:
                raise ValueError("width_mm and height_mm required for oval duct")
            # Oval = rectangle + two semicircles
            a = self.width_mm / 1000   # major (total width)
            b = self.height_mm / 1000  # minor (height = diameter of semicircles)
            rect_w = a - b             # width of rectangular portion
            if rect_w < 0:
                raise ValueError("oval width_mm must be >= height_mm")
            return rect_w * b + math.pi * (b / 2) ** 2
        else:
            raise ValueError(f"Unknown duct shape: {self.shape}")

    def hydraulic_diameter_m(self) -> float:
        """Hydraulic diameter D_h = 4A/P in metres."""
        if self.shape == DuctShape.ROUND:
            return self.diameter_mm / 1000
        elif self.shape == DuctShape.RECTANGULAR:
            w = self.width_mm / 1000
            h = self.height_mm / 1000
            return 4 * (w * h) / (2 * (w + h))
        elif self.shape == DuctShape.OVAL:
            a = self.width_mm / 1000
            b = self.height_mm / 1000
            rect_w = a - b
            area = rect_w * b + math.pi * (b / 2) ** 2
            perimeter = 2 * rect_w + math.pi * b
            return 4 * area / perimeter
        else:
            raise ValueError(f"Unknown duct shape: {self.shape}")

    def velocity_m_s(self) -> float:
        """Mean air velocity in m/s."""
        return self.airflow_m3s / self.area_m2()


@dataclass
class Fitting:
    """A duct fitting at a node in the system.

    Args:
        fitting_type: Type of fitting.
        angle_deg: Turn angle for elbows (degrees, default 90).
        upstream_section: Reference to the upstream DuctSection.
        downstream_section: Reference to the downstream DuctSection (for
            reducers and tees).
        branch_section: Branch leg of a tee.
        flex_length_mm: Length for flex connectors in mm.
        label: Optional label.
    """

    fitting_type: FittingType
    angle_deg: float = 90.0
    upstream_section: Optional[DuctSection] = None
    downstream_section: Optional[DuctSection] = None
    branch_section: Optional[DuctSection] = None
    flex_length_mm: Optional[float] = None
    label: Optional[str] = None


@dataclass
class DuctSystem:
    """A complete HVAC duct system: a directed graph of sections and fittings.

    Attributes:
        name: System name, e.g. 'Supply Air – Level 1'.
        sections: Ordered list of duct sections (main trunk first).
        fittings: Fittings associated with nodes between sections.
        design_airflow_m3s: Total system design airflow in m³/s.
    """

    name: str = "Unnamed Duct System"
    sections: list[DuctSection] = field(default_factory=list)
    fittings: list[Fitting] = field(default_factory=list)
    design_airflow_m3s: float = 0.0

    def add_section(self, section: DuctSection) -> None:
        """Append a duct section."""
        self.sections.append(section)

    def add_fitting(self, fitting: Fitting) -> None:
        """Append a fitting."""
        self.fittings.append(fitting)

    def total_length_mm(self) -> float:
        """Sum of all straight-run lengths."""
        return sum(s.length_mm for s in self.sections)

    def to_dict(self) -> dict:
        """Serialise to a plain dict (JSON-ready)."""
        return {
            "name": self.name,
            "design_airflow_m3s": self.design_airflow_m3s,
            "sections": [
                {
                    "shape": s.shape.value,
                    "length_mm": s.length_mm,
                    "airflow_m3s": s.airflow_m3s,
                    "width_mm": s.width_mm,
                    "height_mm": s.height_mm,
                    "diameter_mm": s.diameter_mm,
                    "material": s.material,
                    "roughness_mm": s.roughness_mm,
                    "insulation_thickness_mm": s.insulation_thickness_mm,
                    "label": s.label,
                }
                for s in self.sections
            ],
            "fittings": [
                {
                    "fitting_type": f.fitting_type.value,
                    "angle_deg": f.angle_deg,
                    "flex_length_mm": f.flex_length_mm,
                    "label": f.label,
                }
                for f in self.fittings
            ],
        }

    @classmethod
    def from_dict(cls, d: dict) -> "DuctSystem":
        """Deserialise from a plain dict."""
        sys = cls(
            name=d.get("name", "Unnamed Duct System"),
            design_airflow_m3s=d.get("design_airflow_m3s", 0.0),
        )
        for s in d.get("sections", []):
            sys.sections.append(
                DuctSection(
                    shape=DuctShape(s["shape"]),
                    length_mm=s["length_mm"],
                    airflow_m3s=s["airflow_m3s"],
                    width_mm=s.get("width_mm"),
                    height_mm=s.get("height_mm"),
                    diameter_mm=s.get("diameter_mm"),
                    material=s.get("material", "galvanised_steel"),
                    roughness_mm=s.get("roughness_mm", 0.09),
                    insulation_thickness_mm=s.get("insulation_thickness_mm", 25.0),
                    label=s.get("label"),
                )
            )
        for f in d.get("fittings", []):
            sys.fittings.append(
                Fitting(
                    fitting_type=FittingType(f["fitting_type"]),
                    angle_deg=f.get("angle_deg", 90.0),
                    flex_length_mm=f.get("flex_length_mm"),
                    label=f.get("label"),
                )
            )
        return sys
