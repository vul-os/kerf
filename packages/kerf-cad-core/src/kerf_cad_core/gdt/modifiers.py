"""
kerf_cad_core.gdt.modifiers — Standard Y14.5 tolerance modifiers.

Modifiers appear inside or adjacent to the tolerance compartment of a feature
control frame and qualify how the tolerance zone is applied.

ASME Y14.5-2018 §2 / §6 / §7:
  MMC  — Maximum Material Condition (largest shaft / smallest hole)
  LMC  — Least Material Condition   (smallest shaft / largest hole)
  RFS  — Regardless of Feature Size  (default when no modifier stated)
  PROJECTED — Projected Tolerance Zone (height appended after tolerance value)
  TANGENT   — Tangent Plane modifier   (for orientation callouts on flat faces)
  FREE_STATE — Free State (for non-rigid parts)
  STATISTICAL — Statistical Tolerance
  CONTINUOUS_FEATURE — CF modifier (treats interrupted surface as one feature)
  INDEPENDENCY — Independent of size (ISO 8015 circle-I)
  UNEQUAL_BILATERAL — Unequal bilateral profile zone (UZ)
"""
from __future__ import annotations

from enum import Enum


class ToleranceModifier(str, Enum):
    """Standard ASME Y14.5 / ISO 1101 tolerance modifier symbols."""

    # Material condition modifiers (applicable to features of size only)
    MMC = "MMC"            # Maximum Material Condition  ⓜ
    LMC = "LMC"            # Least Material Condition    ⓛ
    RFS = "RFS"            # Regardless of Feature Size  ⓢ  (default, rarely shown)

    # Zone modifiers
    PROJECTED = "PROJECTED"    # Projected tolerance zone    ⓟ
    TANGENT = "TANGENT"        # Tangent plane modifier      ⓣ
    FREE_STATE = "FREE_STATE"  # Free state                  ⓕ

    # Statistical / administration
    STATISTICAL = "STATISTICAL"        # Statistical tolerance  ＜ST＞
    CONTINUOUS_FEATURE = "CONTINUOUS_FEATURE"  # CF
    INDEPENDENCY = "INDEPENDENCY"      # Circle-I (ISO 8015)
    UNEQUAL_BILATERAL = "UNEQUAL_BILATERAL"    # UZ


# Modifiers that are only meaningful for features of size (have actual size).
_FEATURE_OF_SIZE_MODIFIERS: frozenset[ToleranceModifier] = frozenset({
    ToleranceModifier.MMC,
    ToleranceModifier.LMC,
    ToleranceModifier.RFS,
})


def requires_feature_of_size(modifier: ToleranceModifier) -> bool:
    """Return True if this modifier is only valid for features of size."""
    return modifier in _FEATURE_OF_SIZE_MODIFIERS
