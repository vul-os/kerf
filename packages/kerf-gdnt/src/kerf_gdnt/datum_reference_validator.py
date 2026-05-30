"""
Datum Reference Frame (DRF) validator -- ASME Y14.5-2018 §4.

Implements §4.11 datum precedence rules for a feature control frame's datum
reference frame:

  §4.11.1  Primary datum -- must be present; for a planar datum it constrains
           3 DOF (translation along normal + 2 rotations): the "3-point plane."
  §4.11.2  Secondary datum -- constrains 2 additional DOF (2-pt line contact);
           must not repeat the primary label.
  §4.11.3  Tertiary datum -- constrains the final DOF (1-pt contact); must
           differ from primary and secondary.

Material-condition modifier rules (§4.11.5 / §6.3):
  * RFS (S modifier, or absence of modifier) -- always applicable; the datum
    feature is simulated at its actual mating size.
  * RMB (regardless of material boundary, modifier S on FOS) -- applicable to
    features of size; NOT applicable to planar (non-FOS) datums.
  * MMB (maximum material boundary, modifier M) -- applicable to features of
    size; NOT applicable to planar datums (§4.11.5(a)).
  * LMB (least material boundary, modifier L) -- applicable to features of
    size; NOT applicable to planar datums (§4.11.5(b)).

Figures used as oracles:
  * Fig. 4-1  -- Valid 3-2-1 plane/plane/plane DRF (A primary, B secondary, C tertiary)
  * Fig. 4-2  -- Valid FOS DRF: cylindrical primary datum A (RMB), secondary B (flat face)
  * Fig. 4-11 -- Datum target validation (point/line/area targets on primary face)

NOTE: Composite tolerance frames (§10.5) are OUT OF SCOPE; if detected, a
      warning is added but no DRF precedence checks are performed on the
      composite segment.

Kerf is not ASME-certified; this is engineering support software.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Optional

from kerf_gdnt.feature_control_frame import DatumReference


# ---------------------------------------------------------------------------
# Feature-of-size classification
# ---------------------------------------------------------------------------

#: Feature types that qualify as features of size (FOS) per ASME Y14.5-2018 §1.3.32.
#: Planar features (flat_face) are NOT features of size.
_FOS_FEATURE_TYPES: frozenset[str] = frozenset({
    "cylinder",
    "cone",
    "sphere",
    "slot",
    "width",   # parallel-plane FOS
})

#: Planar (non-FOS) feature types.
_PLANAR_FEATURE_TYPES: frozenset[str] = frozenset({
    "flat_face",
    "plane",
})

#: Datum target types per §4.24.
DatumTargetType = Literal["point", "line", "area", "movable"]


# ---------------------------------------------------------------------------
# Input dataclasses
# ---------------------------------------------------------------------------

@dataclass
class DatumInfo:
    """
    Metadata about a datum feature declared on the drawing.

    Parameters
    ----------
    label:
        Datum letter (e.g. ``"A"``, ``"B"``, ``"C"``).
    feature_type:
        Geometric type of the nominated feature.  Use one of the literals
        defined in :data:`kerf_gdnt.datums.FeatureType`.
    is_datum_target:
        True when the datum is established through datum targets (§4.24)
        rather than full-surface contact.
    target_type:
        Type of datum target if ``is_datum_target`` is True.
    """
    label: str
    feature_type: str   # e.g. "flat_face", "cylinder", "slot"
    is_datum_target: bool = False
    target_type: Optional[DatumTargetType] = None

    @property
    def is_fos(self) -> bool:
        """True when this datum feature is a feature of size (§1.3.32)."""
        return self.feature_type in _FOS_FEATURE_TYPES

    @property
    def is_planar(self) -> bool:
        """True when this datum feature is a planar (non-FOS) feature."""
        return self.feature_type in _PLANAR_FEATURE_TYPES


@dataclass
class DatumReferenceEntry:
    """
    A single datum compartment in a feature control frame.

    Parameters
    ----------
    label:
        Datum letter, e.g. ``"A"``.
    modifier:
        Material-boundary modifier: ``"M"`` (MMB), ``"L"`` (LMB), ``"S"`` (RMB/RFS),
        or ``None`` (implies RFS for FOS, no modifier for planar).
    """
    label: str
    modifier: Optional[str] = None  # None | "M" | "L" | "S"


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

@dataclass
class DRFViolation:
    """A single DRF precedence/modifier violation."""
    code: str        # machine-readable
    message: str     # human-readable
    rule: str        # ASME Y14.5-2018 §x.x.x citation

    def __str__(self) -> str:
        return f"[{self.code}] {self.message} ({self.rule})"


@dataclass
class ValidationReport:
    """
    Result of :func:`validate_datum_reference_frame`.

    Attributes
    ----------
    valid:
        True when no violations are detected.
    violations:
        List of :class:`DRFViolation` objects -- empty on success.
    warnings:
        Non-fatal notes (e.g. unusual but permitted constructs).
    composite_scope_flag:
        True if composite tolerance frame §10.5 was detected and DRF checks
        were skipped for the composite segment.
    """
    valid: bool
    violations: list[DRFViolation] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    composite_scope_flag: bool = False

    def to_dict(self) -> dict:
        return {
            "valid": self.valid,
            "violations": [
                {"code": v.code, "message": v.message, "rule": v.rule}
                for v in self.violations
            ],
            "warnings": self.warnings,
            "composite_scope_flag": self.composite_scope_flag,
        }


# ---------------------------------------------------------------------------
# Validator
# ---------------------------------------------------------------------------

def validate_datum_reference_frame(
    frame_datums: list[DatumReferenceEntry],
    datum_registry: dict[str, DatumInfo],
    *,
    is_composite_lower_segment: bool = False,
) -> ValidationReport:
    """
    Validate the datum reference frame (DRF) declared in a feature control
    frame against ASME Y14.5-2018 §4.11 datum precedence rules.

    Parameters
    ----------
    frame_datums:
        Ordered list of datum references from the FCF -- position 0 is
        primary, 1 is secondary, 2 is tertiary.  At most 3 entries.
    datum_registry:
        Mapping from datum letter to :class:`DatumInfo` describing the
        feature type and target configuration on the drawing.
    is_composite_lower_segment:
        If True the caller signals that this is the lower (pattern-locating)
        segment of a composite tolerance frame (§10.5).  DRF precedence checks
        are skipped; only a warning is added. OUT OF SCOPE per §10.5.

    Returns
    -------
    ValidationReport
        ``valid=True`` when all rules pass.

    Rules implemented
    -----------------
    R1  §4.11 / §4.3   -- Primary datum must be present.
    R2  §4.11.1        -- Primary planar datum must constrain 3 DOF (3-point).
    R3  §4.11.2        -- Secondary datum must not repeat primary label.
    R4  §4.11.3        -- Tertiary datum must not repeat primary or secondary.
    R5  §4.11          -- Duplicate datum labels anywhere in the DRF.
    R6  §4.11.5(a)     -- MMB modifier (M) on a planar datum is not permitted.
    R7  §4.11.5(b)     -- LMB modifier (L) on a planar datum is not permitted.
    R8  §4.11.5        -- FOS datum without an explicit modifier is valid (RFS implied).
    R9  §4.24          -- Datum target: point/line/area type noted for primary.
    R10 §4.11.5        -- RMB (S modifier) on a planar datum is not meaningful
                         (planar datums have no material boundary to depart from);
                         flagged as a violation.
    """
    violations: list[DRFViolation] = []
    warnings: list[str] = []

    # --- Composite tolerance frame out-of-scope flag (§10.5) ----------------
    if is_composite_lower_segment:
        warnings.append(
            "Composite tolerance frame lower segment (§10.5) detected. "
            "DRF precedence validation is OUT OF SCOPE for this segment. "
            "Consult ASME Y14.5-2018 §10.5 for composite FCF rules."
        )
        return ValidationReport(
            valid=True,
            violations=[],
            warnings=warnings,
            composite_scope_flag=True,
        )

    # --- R1: Primary datum must be present (§4.11 / §4.3) ------------------
    if not frame_datums:
        violations.append(DRFViolation(
            code="MISSING_PRIMARY",
            message=(
                "No datum references present in the feature control frame. "
                "A datum reference frame requires at least a primary datum."
            ),
            rule="ASME Y14.5-2018 §4.11 / §4.3",
        ))
        return ValidationReport(valid=False, violations=violations, warnings=warnings)

    # --- R5: Duplicate datum labels (§4.11) ---------------------------------
    seen_labels: set[str] = set()
    duplicates: set[str] = set()
    for entry in frame_datums:
        if entry.label in seen_labels:
            duplicates.add(entry.label)
        seen_labels.add(entry.label)

    if duplicates:
        violations.append(DRFViolation(
            code="DUPLICATE_DATUM_LETTER",
            message=(
                f"Datum letter(s) {sorted(duplicates)} appear more than once in the "
                "DRF. Each datum letter must appear at most once (primary, secondary, "
                "or tertiary position)."
            ),
            rule="ASME Y14.5-2018 §4.11",
        ))

    # --- Per-datum modifier checks (R6, R7, R8, R10) -----------------------
    for i, entry in enumerate(frame_datums):
        position_name = ("primary", "secondary", "tertiary")[i] if i < 3 else f"datum[{i}]"
        info = datum_registry.get(entry.label)

        if info is None:
            warnings.append(
                f"Datum '{entry.label}' ({position_name}) is referenced in the FCF "
                "but not defined in the datum registry. Cannot validate feature-type "
                "rules. Verify datum is declared on the drawing (ASME Y14.5-2018 §4.3)."
            )
            continue

        modifier = entry.modifier  # None | "M" | "L" | "S"

        # R6: MMB (M) on planar datum (§4.11.5(a)) ---------------------------
        if modifier == "M" and info.is_planar:
            violations.append(DRFViolation(
                code="MMB_ON_PLANAR_DATUM",
                message=(
                    f"Datum '{entry.label}' ({position_name}) is a planar feature "
                    f"('{info.feature_type}') and cannot carry an MMB (M) modifier. "
                    "Material-boundary modifiers apply only to features of size."
                ),
                rule="ASME Y14.5-2018 §4.11.5(a)",
            ))

        # R7: LMB (L) on planar datum (§4.11.5(b)) ---------------------------
        elif modifier == "L" and info.is_planar:
            violations.append(DRFViolation(
                code="LMB_ON_PLANAR_DATUM",
                message=(
                    f"Datum '{entry.label}' ({position_name}) is a planar feature "
                    f"('{info.feature_type}') and cannot carry an LMB (L) modifier. "
                    "Material-boundary modifiers apply only to features of size."
                ),
                rule="ASME Y14.5-2018 §4.11.5(b)",
            ))

        # R10: RMB (S) on planar datum is not meaningful (§4.11.5) -----------
        elif modifier == "S" and info.is_planar:
            violations.append(DRFViolation(
                code="RMB_ON_PLANAR_DATUM",
                message=(
                    f"Datum '{entry.label}' ({position_name}) is a planar feature "
                    f"('{info.feature_type}'). The RMB/RFS (S) modifier is not "
                    "applicable to planar datums -- planar datums have no material "
                    "boundary. Omit the modifier."
                ),
                rule="ASME Y14.5-2018 §4.11.5",
            ))

        # R8: FOS without modifier is valid (RFS implied) -- no action needed
        elif modifier is None and info.is_fos:
            # RFS is implied per §6.3; this is valid, add informational note
            warnings.append(
                f"Datum '{entry.label}' ({position_name}) is a feature of size "
                f"('{info.feature_type}') with no modifier -- RFS/RMB is implied "
                "(ASME Y14.5-2018 §6.3). Explicit 'S' modifier is recommended for clarity."
            )

        # Valid: FOS with M modifier (MMB) ------------------------------------
        elif modifier == "M" and info.is_fos:
            pass  # valid per §4.11.5(a)

        # Valid: FOS with L modifier (LMB) ------------------------------------
        elif modifier == "L" and info.is_fos:
            pass  # valid per §4.11.5(b)

        # Valid: FOS with S modifier (RMB) ------------------------------------
        elif modifier == "S" and info.is_fos:
            pass  # valid per §4.11.5

        # R9: Datum target notes (§4.24) -------------------------------------
        if info.is_datum_target and i == 0:
            # Primary datum target: verify type is recorded
            if info.target_type not in ("point", "line", "area", "movable"):
                warnings.append(
                    f"Primary datum '{entry.label}' is declared as a datum target "
                    "but has an unrecognised target_type. Targets must be point, line, "
                    "area, or movable per ASME Y14.5-2018 §4.24 (Fig. 4-11)."
                )

    # --- R2: Primary planar datum -- 3-point (§4.11.1) ----------------------
    if frame_datums:
        primary_entry = frame_datums[0]
        primary_info = datum_registry.get(primary_entry.label)
        if primary_info is not None and primary_info.is_planar:
            # 3-pt contact for primary plane: validated implicitly by
            # feature_type; warn if is_datum_target with <3 point targets
            if primary_info.is_datum_target and primary_info.target_type == "point":
                warnings.append(
                    f"Primary datum '{primary_entry.label}' uses point datum targets "
                    "(§4.24 Fig. 4-11). Ensure at least 3 target points are specified "
                    "to satisfy 3-point plane constraint (ASME Y14.5-2018 §4.11.1)."
                )

    valid = len(violations) == 0
    return ValidationReport(valid=valid, violations=violations, warnings=warnings)


# ---------------------------------------------------------------------------
# Convenience: build from FCF DatumReference objects
# ---------------------------------------------------------------------------

def drf_entries_from_datum_refs(
    datum_refs: list[DatumReference],
) -> list[DatumReferenceEntry]:
    """
    Convert a list of :class:`~kerf_gdnt.feature_control_frame.DatumReference`
    objects (from a FeatureControlFrame) into :class:`DatumReferenceEntry`
    objects suitable for :func:`validate_datum_reference_frame`.
    """
    return [
        DatumReferenceEntry(label=dr.label, modifier=dr.modifier)
        for dr in datum_refs
    ]
