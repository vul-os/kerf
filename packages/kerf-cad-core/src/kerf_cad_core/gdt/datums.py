"""
kerf_cad_core.gdt.datums — Datum and DatumReferenceFrame dataclasses.

A Datum identifies a theoretically exact geometric reference (plane, axis, or
centre-plane) derived from a real feature on the part.  A DatumReferenceFrame
(DRF) orders up to three datum labels as primary / secondary / tertiary
references, establishing the mutually perpendicular datum planes required to
fully constrain position and orientation.

ASME Y14.5 §4 / ISO 5459 nomenclature is followed.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class DatumType(str, Enum):
    """Geometric nature of the datum derived feature."""
    PLANE = "PLANE"          # flat surface  → datum plane
    AXIS = "AXIS"            # cylinder/cone → datum axis
    CENTRE_PLANE = "CENTRE_PLANE"  # slot/tab → centre plane
    POINT = "POINT"          # sphere centre → datum point
    LINE = "LINE"            # edge / line element → datum line


@dataclass
class Datum:
    """
    A single lettered datum (e.g. 'A', 'B', 'C').

    Attributes
    ----------
    label:
        The datum letter(s) used on the drawing callout, e.g. 'A', 'B', 'AB'.
    datum_type:
        Geometric nature of the datum feature.
    feature_ref:
        Optional reference to the feature this datum is derived from (e.g.
        face name, surface id, or a feature-tree node id).
    description:
        Human-readable note.
    is_compound:
        True when the datum is a compound datum (e.g. 'A-B' co-datums in
        ASME Y14.5-2018 §7.5).
    """
    label: str
    datum_type: DatumType = DatumType.PLANE
    feature_ref: Optional[str] = None
    description: Optional[str] = None
    is_compound: bool = False

    def __post_init__(self) -> None:
        label = self.label.strip()
        if not label:
            raise ValueError("Datum label must not be empty")
        self.label = label
        if isinstance(self.datum_type, str):
            self.datum_type = DatumType(self.datum_type.upper())

    def to_dict(self) -> dict:
        return {
            "label": self.label,
            "datum_type": self.datum_type.value,
            "feature_ref": self.feature_ref,
            "description": self.description,
            "is_compound": self.is_compound,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Datum":
        return cls(
            label=d["label"],
            datum_type=DatumType(d.get("datum_type", "PLANE")),
            feature_ref=d.get("feature_ref"),
            description=d.get("description"),
            is_compound=bool(d.get("is_compound", False)),
        )


@dataclass
class DatumReferenceFrame:
    """
    Ordered datum reference frame (up to three datums: primary / secondary /
    tertiary) per ASME Y14.5 §4.4.

    Precedence
    ----------
    Primary datum provides the greatest number of degrees-of-freedom
    constraint.  Secondary and tertiary refine the remaining DOF.  The
    ordering is significant for position, orientation, and runout callouts.

    Attributes
    ----------
    primary:
        The highest-precedence datum label (required when any datum is given).
    secondary:
        Second-precedence datum label (optional).
    tertiary:
        Third-precedence datum label (optional).  Only valid when secondary
        is also provided.
    """
    primary: Optional[str] = None
    secondary: Optional[str] = None
    tertiary: Optional[str] = None

    def __post_init__(self) -> None:
        # Strip whitespace
        self.primary = self.primary.strip() if self.primary else None
        self.secondary = self.secondary.strip() if self.secondary else None
        self.tertiary = self.tertiary.strip() if self.tertiary else None
        # Structural rule: tertiary without secondary is invalid
        if self.tertiary and not self.secondary:
            raise ValueError(
                "DatumReferenceFrame: tertiary datum requires a secondary datum"
            )

    @property
    def labels(self) -> list[str]:
        """Return non-None datum labels in precedence order."""
        out: list[str] = []
        if self.primary:
            out.append(self.primary)
        if self.secondary:
            out.append(self.secondary)
        if self.tertiary:
            out.append(self.tertiary)
        return out

    @property
    def is_empty(self) -> bool:
        return self.primary is None

    def to_dict(self) -> dict:
        return {
            "primary": self.primary,
            "secondary": self.secondary,
            "tertiary": self.tertiary,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "DatumReferenceFrame":
        return cls(
            primary=d.get("primary"),
            secondary=d.get("secondary"),
            tertiary=d.get("tertiary"),
        )

    def __str__(self) -> str:
        parts = [p for p in [self.primary, self.secondary, self.tertiary] if p]
        return "|".join(parts) if parts else "(none)"
