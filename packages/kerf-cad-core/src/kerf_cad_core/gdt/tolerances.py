"""
kerf_cad_core.gdt.tolerances — GeometricTolerance and ToleranceSymbol.

Each GeometricTolerance instance represents one feature control frame:
    [ symbol | tolerance_value | modifier | datum_ref_frame ]

ASME Y14.5-2018 characteristic symbols are grouped into the standard five
categories:  Form, Profile, Orientation, Location, Runout.

ISO 1101 equivalents are parenthesised in comments where they differ.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from kerf_cad_core.gdt.datums import DatumReferenceFrame
from kerf_cad_core.gdt.modifiers import ToleranceModifier


class ToleranceSymbol(str, Enum):
    """GD&T characteristic symbols per ASME Y14.5-2018 / ISO 1101."""

    # ── Form (no datum reference) ──────────────────────────────────────────
    FLATNESS = "FLATNESS"              # ⏥
    STRAIGHTNESS = "STRAIGHTNESS"      # ⏤
    CIRCULARITY = "CIRCULARITY"        # ○  (roundness)
    CYLINDRICITY = "CYLINDRICITY"      # ⌭

    # ── Profile ────────────────────────────────────────────────────────────
    PROFILE_LINE = "PROFILE_LINE"      # ⌒  (profile of a line)
    PROFILE_SURFACE = "PROFILE_SURFACE"  # ⌓  (profile of a surface)

    # ── Orientation ────────────────────────────────────────────────────────
    PARALLELISM = "PARALLELISM"        # ∥
    PERPENDICULARITY = "PERPENDICULARITY"  # ⊥
    ANGULARITY = "ANGULARITY"          # ∠

    # ── Location ───────────────────────────────────────────────────────────
    POSITION = "POSITION"              # ⊕
    CONCENTRICITY = "CONCENTRICITY"    # ◎  (ASME) / coaxiality (ISO)
    SYMMETRY = "SYMMETRY"              # ≡

    # ── Runout ─────────────────────────────────────────────────────────────
    RUNOUT = "RUNOUT"                  # ↗  (circular runout)
    TOTAL_RUNOUT = "TOTAL_RUNOUT"      # ⟿  (total runout)


# ── Category helpers ──────────────────────────────────────────────────────────

_FORM_SYMBOLS: frozenset[ToleranceSymbol] = frozenset({
    ToleranceSymbol.FLATNESS,
    ToleranceSymbol.STRAIGHTNESS,
    ToleranceSymbol.CIRCULARITY,
    ToleranceSymbol.CYLINDRICITY,
})

_PROFILE_SYMBOLS: frozenset[ToleranceSymbol] = frozenset({
    ToleranceSymbol.PROFILE_LINE,
    ToleranceSymbol.PROFILE_SURFACE,
})

_ORIENTATION_SYMBOLS: frozenset[ToleranceSymbol] = frozenset({
    ToleranceSymbol.PARALLELISM,
    ToleranceSymbol.PERPENDICULARITY,
    ToleranceSymbol.ANGULARITY,
})

_LOCATION_SYMBOLS: frozenset[ToleranceSymbol] = frozenset({
    ToleranceSymbol.POSITION,
    ToleranceSymbol.CONCENTRICITY,
    ToleranceSymbol.SYMMETRY,
})

_RUNOUT_SYMBOLS: frozenset[ToleranceSymbol] = frozenset({
    ToleranceSymbol.RUNOUT,
    ToleranceSymbol.TOTAL_RUNOUT,
})


def tolerance_category(sym: ToleranceSymbol) -> str:
    """Return the GD&T category name for a symbol."""
    if sym in _FORM_SYMBOLS:
        return "form"
    if sym in _PROFILE_SYMBOLS:
        return "profile"
    if sym in _ORIENTATION_SYMBOLS:
        return "orientation"
    if sym in _LOCATION_SYMBOLS:
        return "location"
    if sym in _RUNOUT_SYMBOLS:
        return "runout"
    return "unknown"


@dataclass
class GeometricTolerance:
    """
    A single feature control frame entry.

    Attributes
    ----------
    feature_name:
        Identifier of the feature being toleranced (e.g. 'bore-top',
        'face-A', or a feature-tree node id).
    symbol:
        GD&T characteristic symbol.
    tolerance_value:
        Tolerance zone width/diameter in millimetres (> 0).
    diameter_zone:
        When True the tolerance zone is cylindrical (⌀ prefix on drawing).
    datum_ref:
        Ordered datum reference frame.  May be empty for form tolerances.
    modifiers:
        List of applicable Y14.5 modifiers (MMC, LMC, RFS, PROJECTED, …).
    is_feature_of_size:
        True when the feature being toleranced has an actual size (shaft,
        hole, slot, etc.).  Required for MMC/LMC modifier validation.
    projected_zone_height:
        When the PROJECTED modifier is active, the minimum projected zone
        height in mm (required).
    note:
        Optional human-readable annotation.
    """
    feature_name: str
    symbol: ToleranceSymbol
    tolerance_value: float
    diameter_zone: bool = False
    datum_ref: DatumReferenceFrame = field(default_factory=DatumReferenceFrame)
    modifiers: list[ToleranceModifier] = field(default_factory=list)
    is_feature_of_size: bool = False
    projected_zone_height: Optional[float] = None
    note: Optional[str] = None

    def __post_init__(self) -> None:
        if not self.feature_name or not self.feature_name.strip():
            raise ValueError("GeometricTolerance: feature_name must not be empty")
        self.feature_name = self.feature_name.strip()
        if isinstance(self.symbol, str):
            self.symbol = ToleranceSymbol(self.symbol.upper())
        try:
            self.tolerance_value = float(self.tolerance_value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"GeometricTolerance: tolerance_value must be numeric: {exc}") from exc
        if self.tolerance_value <= 0:
            raise ValueError(
                f"GeometricTolerance: tolerance_value must be > 0, got {self.tolerance_value}"
            )
        if not isinstance(self.datum_ref, DatumReferenceFrame):
            if isinstance(self.datum_ref, dict):
                self.datum_ref = DatumReferenceFrame.from_dict(self.datum_ref)
            else:
                self.datum_ref = DatumReferenceFrame()
        # Normalise modifiers
        normalised: list[ToleranceModifier] = []
        for m in self.modifiers:
            if isinstance(m, str):
                normalised.append(ToleranceModifier(m.upper()))
            else:
                normalised.append(m)
        self.modifiers = normalised

    @property
    def category(self) -> str:
        return tolerance_category(self.symbol)

    def to_dict(self) -> dict:
        return {
            "feature_name": self.feature_name,
            "symbol": self.symbol.value,
            "tolerance_value": self.tolerance_value,
            "diameter_zone": self.diameter_zone,
            "datum_ref": self.datum_ref.to_dict(),
            "modifiers": [m.value for m in self.modifiers],
            "is_feature_of_size": self.is_feature_of_size,
            "projected_zone_height": self.projected_zone_height,
            "note": self.note,
            "category": self.category,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "GeometricTolerance":
        return cls(
            feature_name=d["feature_name"],
            symbol=ToleranceSymbol(d["symbol"].upper()),
            tolerance_value=float(d["tolerance_value"]),
            diameter_zone=bool(d.get("diameter_zone", False)),
            datum_ref=DatumReferenceFrame.from_dict(d.get("datum_ref") or {}),
            modifiers=[ToleranceModifier(m.upper()) for m in (d.get("modifiers") or [])],
            is_feature_of_size=bool(d.get("is_feature_of_size", False)),
            projected_zone_height=d.get("projected_zone_height"),
            note=d.get("note"),
        )
