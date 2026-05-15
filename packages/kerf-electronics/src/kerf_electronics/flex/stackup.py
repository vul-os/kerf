# Author: imranparuk
"""
Flex and rigid-flex stackup data models.

Terminology
-----------
Layer       — a single material stratum with a type, thickness, and optional
              dielectric constant.
Stackup     — an ordered list of Layer objects representing a board cross-section,
              with helpers to identify rigid / flex zones and copper layers.
BendRegion  — a subset of a stackup that will be mechanically bent; carries the
              bend angle, inner radius, and flex type (single-sided / double-sided /
              dynamic).

All thickness values are in mm.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional


# ── Enumerations ──────────────────────────────────────────────────────────────

class LayerType(str, Enum):
    COPPER = "copper"
    PI = "PI"               # polyimide film (Kapton-class)
    ADHESIVE = "adhesive"   # acrylic or epoxy adhesive film
    COVERLAY = "coverlay"   # polyimide + adhesive protective film
    STIFFENER = "stiffener" # FR4 or steel stiffener (rigid zone only)


class ZoneType(str, Enum):
    RIGID = "rigid"
    FLEX = "flex"


class FlexType(str, Enum):
    SINGLE_SIDED = "single_sided"  # copper on one face only
    DOUBLE_SIDED = "double_sided"  # copper on both faces
    DYNAMIC = "dynamic"            # repeated flexing in use (e.g. flex cable)


# ── Layer ─────────────────────────────────────────────────────────────────────

@dataclass
class Layer:
    """A single material stratum in a PCB stackup.

    Attributes
    ----------
    layer_type : LayerType
        Material classification.
    thickness_mm : float
        Stratum thickness in mm.  Must be > 0.
    name : str
        Human-readable label (e.g. ``"top_cu"``, ``"core_PI"``).
    er : float | None
        Relative permittivity (εr) — meaningful for dielectric layers;
        ``None`` for copper / stiffener.
    zone : ZoneType
        Whether this layer belongs to a rigid or flex zone of the board.
    """

    layer_type: LayerType
    thickness_mm: float
    name: str = ""
    er: Optional[float] = None
    zone: ZoneType = ZoneType.FLEX

    def is_copper(self) -> bool:
        return self.layer_type == LayerType.COPPER

    def is_dielectric(self) -> bool:
        return self.layer_type in (LayerType.PI, LayerType.ADHESIVE, LayerType.COVERLAY)

    def is_stiffener(self) -> bool:
        return self.layer_type == LayerType.STIFFENER


# ── Stackup ───────────────────────────────────────────────────────────────────

@dataclass
class Stackup:
    """Ordered list of layers representing a board cross-section (top → bottom).

    Parameters
    ----------
    layers : list[Layer]
        Ordered stack from top surface to bottom surface.
    name : str
        Optional descriptive name for the stackup.
    """

    layers: List[Layer] = field(default_factory=list)
    name: str = ""

    # ── Derived properties ─────────────────────────────────────────────────

    def total_thickness_mm(self) -> float:
        """Sum of all layer thicknesses (mm)."""
        return sum(la.thickness_mm for la in self.layers)

    def flex_thickness_mm(self) -> float:
        """Sum of flex-zone layer thicknesses (mm)."""
        return sum(la.thickness_mm for la in self.layers if la.zone == ZoneType.FLEX)

    def rigid_thickness_mm(self) -> float:
        """Sum of rigid-zone layer thicknesses (mm)."""
        return sum(la.thickness_mm for la in self.layers if la.zone == ZoneType.RIGID)

    def copper_layers(self) -> List[Layer]:
        """Return all copper layers."""
        return [la for la in self.layers if la.is_copper()]

    def copper_count(self) -> int:
        """Total copper layer count."""
        return len(self.copper_layers())

    def flex_copper_layers(self) -> List[Layer]:
        """Copper layers in the flex zone."""
        return [la for la in self.layers if la.is_copper() and la.zone == ZoneType.FLEX]

    def flex_copper_count(self) -> int:
        """Copper layer count in the flex zone."""
        return len(self.flex_copper_layers())

    def has_copper(self) -> bool:
        return self.copper_count() > 0

    def is_valid(self) -> tuple[bool, str]:
        """Basic sanity check.  Returns ``(True, "")`` or ``(False, reason)``."""
        if not self.layers:
            return False, "stackup has no layers"
        if not self.has_copper():
            return False, "stackup has no copper layers"
        for i, la in enumerate(self.layers):
            if la.thickness_mm <= 0:
                return False, f"layer[{i}] '{la.name}' has non-positive thickness"
        return True, ""

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "layers": [
                {
                    "name": la.name,
                    "type": la.layer_type.value,
                    "thickness_mm": la.thickness_mm,
                    "er": la.er,
                    "zone": la.zone.value,
                }
                for la in self.layers
            ],
            "total_thickness_mm": self.total_thickness_mm(),
            "flex_thickness_mm": self.flex_thickness_mm(),
            "copper_count": self.copper_count(),
            "flex_copper_count": self.flex_copper_count(),
        }


# ── BendRegion ────────────────────────────────────────────────────────────────

@dataclass
class BendRegion:
    """A region of the flex circuit that will be bent.

    Parameters
    ----------
    name : str
        Descriptive identifier (e.g. ``"fold_A"``).
    inner_radius_mm : float
        Bend inner radius r in mm (measured to the inner surface of the bend).
        Must be > 0.
    bend_angle_deg : float
        Subtended bend angle in degrees (0–360).  Informational; used for
        arc-length estimate but not for IPC-2223 pass/fail.
    flex_thickness_mm : float | None
        Effective flex-zone thickness t in mm.  If ``None``, derived from the
        associated ``Stackup``.
    flex_type : FlexType
        Flex type that governs the minimum bend radius rule.
    location_mm : float | None
        Distance along the board from a reference edge to the centre of the
        bend region (optional, informational).
    stackup : Stackup | None
        Reference to the parent stackup.  Used when ``flex_thickness_mm``
        is ``None``.
    """

    name: str = ""
    inner_radius_mm: float = 0.0
    bend_angle_deg: float = 90.0
    flex_thickness_mm: Optional[float] = None
    flex_type: FlexType = FlexType.SINGLE_SIDED
    location_mm: Optional[float] = None
    stackup: Optional[Stackup] = None

    def effective_flex_thickness(self) -> float:
        """Return the effective flex thickness for bend calculations (mm)."""
        if self.flex_thickness_mm is not None and self.flex_thickness_mm > 0:
            return self.flex_thickness_mm
        if self.stackup is not None:
            t = self.stackup.flex_thickness_mm()
            if t > 0:
                return t
        return 0.0

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "inner_radius_mm": self.inner_radius_mm,
            "bend_angle_deg": self.bend_angle_deg,
            "flex_type": self.flex_type.value,
            "location_mm": self.location_mm,
            "effective_flex_thickness_mm": self.effective_flex_thickness(),
        }
