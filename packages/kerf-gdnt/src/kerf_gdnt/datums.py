"""
Datum reference frame, datum features, and datum simulators.

Terminology follows ISO 5459:2011 and ASME Y14.5-2018 §4.

A :class:`DatumFeature` is a physical feature on a part nominated to
establish a datum (e.g. a flat face, a cylindrical bore, a cone).

A :class:`DatumSimulator` is the ideal geometry (typically a physical
gauge surface) used to simulate the datum during inspection.

A :class:`DatumReferenceFrame` aggregates the primary, secondary, and
tertiary datum simulators to fully constrain the 6 degrees of freedom of
the part's coordinate system.

Degrees of freedom constrained (ISO 5459:2011 Table 1):
  - Flat primary face:   3 DOF (1 translation, 2 rotations)
  - Cylindrical hole:    4 DOF (2 translations, 2 rotations — or 2 + 2 depending on length)
  - Flat secondary:      2 DOF (1 translation, 1 rotation)
  - Point:               1 DOF (1 translation)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Optional


FeatureType = Literal[
    "flat_face",
    "cylinder",
    "cone",
    "sphere",
    "line",
    "point",
    "slot",
]

SimulatorType = Literal[
    "surface_plate",
    "mandrel",
    "collet",
    "vee_block",
    "point_contact",
    "slot_gauge",
    "unknown",
]


@dataclass
class DatumFeature:
    """
    A nominated datum feature on a part.

    Parameters
    ----------
    label:
        Single letter (or letter+digit) identifier, e.g. ``"A"``, ``"B1"``.
    feature_type:
        Geometric type of the feature.
    description:
        Optional free-text description (e.g. "bottom face", "Ø20 bore").
    """
    label: str
    feature_type: FeatureType
    description: Optional[str] = None

    def __str__(self) -> str:
        return f"Datum {self.label} ({self.feature_type})"


@dataclass
class DatumSimulator:
    """
    The idealised simulator used during inspection to establish the datum.

    Parameters
    ----------
    datum_label:
        Matches the label of the :class:`DatumFeature` it simulates.
    simulator_type:
        Type of physical simulator.
    dof_constrained:
        Number of degrees of freedom this simulator removes from the part.
    """
    datum_label: str
    simulator_type: SimulatorType
    dof_constrained: int

    def __str__(self) -> str:
        return (
            f"Simulator for datum {self.datum_label}: "
            f"{self.simulator_type} ({self.dof_constrained} DOF)"
        )


@dataclass
class DatumReferenceFrame:
    """
    A complete datum reference frame (DRF) — up to three ordered datums.

    Per ASME Y14.5-2018 §4.1 the ordered sequence is:
      primary → secondary → tertiary

    Parameters
    ----------
    primary:
        Primary datum (constrains most DOF — typically a flat face = 3 DOF).
    secondary:
        Secondary datum (constrains next most DOF).
    tertiary:
        Tertiary datum (constrains remaining DOF to fully lock the part).
    """
    primary: DatumSimulator
    secondary: Optional[DatumSimulator] = None
    tertiary: Optional[DatumSimulator] = None

    @property
    def total_dof_constrained(self) -> int:
        total = self.primary.dof_constrained
        if self.secondary:
            total += self.secondary.dof_constrained
        if self.tertiary:
            total += self.tertiary.dof_constrained
        return total

    @property
    def is_fully_constrained(self) -> bool:
        """True when the DRF removes all 6 translational + rotational DOF."""
        return self.total_dof_constrained >= 6

    def ordered_labels(self) -> list[str]:
        """Return datum labels in [primary, secondary?, tertiary?] order."""
        labels = [self.primary.datum_label]
        if self.secondary:
            labels.append(self.secondary.datum_label)
        if self.tertiary:
            labels.append(self.tertiary.datum_label)
        return labels

    def __str__(self) -> str:
        labels = self.ordered_labels()
        dof = self.total_dof_constrained
        status = "fully constrained" if self.is_fully_constrained else f"{dof}/6 DOF constrained"
        return f"DRF [{' | '.join(labels)}] — {status}"


# ---------------------------------------------------------------------------
# Convenience constructors
# ---------------------------------------------------------------------------

def make_3_2_1_frame(
    primary_label: str = "A",
    secondary_label: str = "B",
    tertiary_label: str = "C",
) -> DatumReferenceFrame:
    """
    Build a classic 3-2-1 flat-face datum reference frame.

    Primary face (surface plate)   → 3 DOF (tz, rx, ry)
    Secondary face (parallel stop) → 2 DOF (ty, rz)
    Tertiary face (side stop)       → 1 DOF (tx)
    """
    return DatumReferenceFrame(
        primary=DatumSimulator(
            datum_label=primary_label,
            simulator_type="surface_plate",
            dof_constrained=3,
        ),
        secondary=DatumSimulator(
            datum_label=secondary_label,
            simulator_type="surface_plate",
            dof_constrained=2,
        ),
        tertiary=DatumSimulator(
            datum_label=tertiary_label,
            simulator_type="point_contact",
            dof_constrained=1,
        ),
    )
