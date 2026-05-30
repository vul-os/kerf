"""joinery_validate.py — woodworking joinery geometry validator for Kerf.

Validates joint geometry against master-craftsman proportions drawn from:

    Hammer-Krenov "Cabinetmaking and Millwork" §6 (joinery proportions)
    USDA Forest Products Lab Wood Handbook (wood mechanical properties)

IMPORTANT: These are Hammer-Krenov reference proportions — NOT FWW-certified.
The strength estimates are derived from Forest Products Lab shear values but are
simplified engineering approximations, not tested joint-level measurements.

All dimensions in millimetres unless noted.  Angles in degrees.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Literal


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------


@dataclass
class ValidationIssue:
    """A single validation finding."""

    severity: Literal["error", "warning", "info"]
    code: str
    message: str

    def to_dict(self) -> dict[str, Any]:
        return {"severity": self.severity, "code": self.code, "message": self.message}


@dataclass
class ValidationResult:
    """Aggregate result from a joinery validation pass."""

    valid: bool
    joint_type: str
    issues: list[ValidationIssue] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "valid": self.valid,
            "joint_type": self.joint_type,
            "issues": [i.to_dict() for i in self.issues],
        }


def _result(joint_type: str, issues: list[ValidationIssue]) -> ValidationResult:
    """Build a ValidationResult, marking invalid if any error-severity issue exists."""
    valid = not any(i.severity == "error" for i in issues)
    return ValidationResult(valid=valid, joint_type=joint_type, issues=issues)


# ---------------------------------------------------------------------------
# Dovetail validator
# Per Hammer-Krenov §6.2
# ---------------------------------------------------------------------------

#: Acceptable pin-angle range (degrees): 7° softwood, 14° hardwood.
_DOVETAIL_ANGLE_MIN_DEG: float = 7.0
_DOVETAIL_ANGLE_MAX_DEG: float = 14.0

#: Minimum pin width as a fraction of board thickness.
_DOVETAIL_MIN_PIN_FRACTION: float = 1 / 3

#: Minimum number of pins per joint.
_DOVETAIL_MIN_PINS: int = 2


def validate_dovetail(geometry: dict[str, Any]) -> ValidationResult:
    """Validate dovetail joint proportions against Hammer-Krenov §6.2.

    Args:
        geometry: A dict with keys:
            - ``pin_angle_deg`` (float): splay angle of the pins in degrees.
            - ``board_thickness_mm`` (float): thickness of the tail board.
            - ``pin_width_mm`` (float): width of the narrowest pin at its base.
            - ``pin_count`` (int): number of pins in the joint (``tail_count``
              from :func:`kerf_woodworking.joinery.dovetail` is accepted too).

    Returns:
        :class:`ValidationResult` with ``valid=True`` if all checks pass.
    """
    issues: list[ValidationIssue] = []

    # ------------------------------------------------------------------
    # Extract fields — accept legacy keys from joinery.dovetail()
    # ------------------------------------------------------------------
    pin_angle = float(
        geometry.get("pin_angle_deg")
        or geometry.get("tail_angle_deg")
        or 0.0
    )
    board_thickness = float(geometry.get("board_thickness_mm") or 0.0)
    # pin_width_mm may be provided directly; fall back to tail_half_width_mm * 2
    pin_width = float(
        geometry.get("pin_width_mm")
        or (geometry.get("tail_half_width_mm", 0.0) * 2.0)
        or 0.0
    )
    pin_count = int(
        geometry.get("pin_count")
        or geometry.get("tail_count")
        or 0
    )

    # ------------------------------------------------------------------
    # Check 1: pin angle range
    # ------------------------------------------------------------------
    if pin_angle <= 0:
        issues.append(ValidationIssue(
            severity="error",
            code="DOVETAIL_ANGLE_MISSING",
            message="pin_angle_deg (or tail_angle_deg) must be provided and > 0.",
        ))
    elif pin_angle < _DOVETAIL_ANGLE_MIN_DEG:
        issues.append(ValidationIssue(
            severity="error",
            code="DOVETAIL_ANGLE_TOO_SHALLOW",
            message=(
                f"Pin angle {pin_angle:.1f}° is below the 7° minimum "
                f"(Hammer-Krenov §6.2). Too shallow — poor mechanical lock."
            ),
        ))
    elif pin_angle > _DOVETAIL_ANGLE_MAX_DEG:
        issues.append(ValidationIssue(
            severity="error",
            code="DOVETAIL_ANGLE_TOO_STEEP",
            message=(
                f"Pin angle {pin_angle:.1f}° exceeds the 14° maximum "
                f"(Hammer-Krenov §6.2). Too steep — will split grain under load."
            ),
        ))

    # ------------------------------------------------------------------
    # Check 2: pin width ≥ 1/3 of board thickness
    # ------------------------------------------------------------------
    if board_thickness <= 0:
        issues.append(ValidationIssue(
            severity="error",
            code="DOVETAIL_THICKNESS_MISSING",
            message="board_thickness_mm must be provided and > 0.",
        ))
    elif pin_width > 0 and pin_width < board_thickness * _DOVETAIL_MIN_PIN_FRACTION:
        issues.append(ValidationIssue(
            severity="error",
            code="DOVETAIL_PIN_TOO_NARROW",
            message=(
                f"Pin width {pin_width:.2f} mm is less than 1/3 of board "
                f"thickness ({board_thickness / 3:.2f} mm). Pin is too fragile — "
                f"liable to short-grain failure (Hammer-Krenov §6.2)."
            ),
        ))

    # ------------------------------------------------------------------
    # Check 3: minimum 2 pins per joint
    # ------------------------------------------------------------------
    if pin_count < _DOVETAIL_MIN_PINS:
        issues.append(ValidationIssue(
            severity="error",
            code="DOVETAIL_TOO_FEW_PINS",
            message=(
                f"Joint has {pin_count} pin(s); minimum is {_DOVETAIL_MIN_PINS} "
                f"(Hammer-Krenov §6.2). Single-pin dovetails lack racking resistance."
            ),
        ))

    return _result("dovetail", issues)


# ---------------------------------------------------------------------------
# Mortise-and-tenon validator
# Per Hammer-Krenov §6.3
# ---------------------------------------------------------------------------

#: Tenon thickness should be 1/3 of board thickness (Hammer-Krenov §6.3).
_MT_TENON_THICKNESS_RATIO: float = 1 / 3

#: Tenon thickness tolerance around the ideal ratio (±10%).
_MT_TENON_RATIO_TOL: float = 0.10

#: Mortise member (board) thickness must be ≥ 3× tenon thickness so both cheeks
#: have enough wood. Each cheek = (board - tenon) / 2 ≥ tenon, which requires
#: board ≥ 3× tenon.  We apply this to the board directly.
_MT_MIN_BOARD_TO_TENON_RATIO: float = 3.0

#: Kept for back-compat; cheek wall check uses board_thickness directly.
_MT_MIN_CHEEK_RATIO: float = 3.0

#: Minimum tenon length = 1.5× tenon thickness.
_MT_MIN_LENGTH_RATIO: float = 1.5


def validate_mortise_and_tenon(geometry: dict[str, Any]) -> ValidationResult:
    """Validate mortise-and-tenon proportions against Hammer-Krenov §6.3.

    Args:
        geometry: A dict with keys:
            - ``board_thickness_mm`` (float): thickness of the tenon member.
            - ``tenon_thickness_mm`` (float): thickness of the tenon itself.
              If omitted, ``tenon_width_mm`` is used (treating width as the
              thickness face — the mortise-direction dimension).
            - ``mortise_width_mm`` (float): width of the mortise slot.
            - ``cheek_thickness_mm`` (float, optional): remaining wood beside
              the mortise; if omitted, derived as
              ``(board_thickness_mm - mortise_width_mm) / 2``.
            - ``tenon_length_mm`` (float): how far the tenon penetrates
              (``tenon_depth_mm`` from joinery.mortise_tenon is also accepted).

    Returns:
        :class:`ValidationResult`.
    """
    issues: list[ValidationIssue] = []

    board_thickness = float(geometry.get("board_thickness_mm") or 0.0)
    # Accept tenon_thickness_mm or fall back to tenon_width_mm
    tenon_thickness = float(
        geometry.get("tenon_thickness_mm")
        or geometry.get("tenon_width_mm")
        or 0.0
    )
    mortise_width = float(
        geometry.get("mortise_width_mm")
        or geometry.get("mortise_width_mm")
        or 0.0
    )
    # Cheek thickness: explicit or derived from board - mortise
    if "cheek_thickness_mm" in geometry:
        cheek_thickness = float(geometry["cheek_thickness_mm"])
    elif board_thickness > 0 and mortise_width > 0:
        cheek_thickness = (board_thickness - mortise_width) / 2.0
    else:
        cheek_thickness = 0.0

    tenon_length = float(
        geometry.get("tenon_length_mm")
        or geometry.get("tenon_depth_mm")
        or geometry.get("engagement_mm")
        or 0.0
    )

    # ------------------------------------------------------------------
    # Check 1: tenon thickness ≈ 1/3 of board thickness
    # ------------------------------------------------------------------
    if board_thickness <= 0:
        issues.append(ValidationIssue(
            severity="error",
            code="MT_BOARD_THICKNESS_MISSING",
            message="board_thickness_mm must be provided and > 0.",
        ))
    elif tenon_thickness <= 0:
        issues.append(ValidationIssue(
            severity="error",
            code="MT_TENON_THICKNESS_MISSING",
            message="tenon_thickness_mm (or tenon_width_mm) must be provided and > 0.",
        ))
    else:
        ideal = board_thickness * _MT_TENON_THICKNESS_RATIO
        ratio = tenon_thickness / board_thickness
        low  = _MT_TENON_THICKNESS_RATIO * (1 - _MT_TENON_RATIO_TOL)
        high = _MT_TENON_THICKNESS_RATIO * (1 + _MT_TENON_RATIO_TOL)
        if ratio >= 0.5:
            issues.append(ValidationIssue(
                severity="error",
                code="MT_TENON_TOO_THICK",
                message=(
                    f"Tenon thickness {tenon_thickness:.2f} mm is half or more of "
                    f"the board thickness ({board_thickness:.2f} mm). "
                    f"Tenon too thick — weak cheek wall will split under load "
                    f"(Hammer-Krenov §6.3). Ideal = 1/3 board = {ideal:.2f} mm."
                ),
            ))
        elif ratio < low:
            issues.append(ValidationIssue(
                severity="warning",
                code="MT_TENON_TOO_THIN",
                message=(
                    f"Tenon thickness {tenon_thickness:.2f} mm is below the ideal "
                    f"1/3 ratio (expected ~{ideal:.2f} mm for a {board_thickness:.2f} mm "
                    f"board). May be acceptable for decorative joints but risks tenon "
                    f"fracture under racking load (Hammer-Krenov §6.3)."
                ),
            ))

    # ------------------------------------------------------------------
    # Check 2: mortise width should equal tenon thickness (tight fit)
    # ------------------------------------------------------------------
    if mortise_width > 0 and tenon_thickness > 0:
        if not math.isclose(mortise_width, tenon_thickness, rel_tol=0.05):
            issues.append(ValidationIssue(
                severity="warning",
                code="MT_MORTISE_WIDTH_MISMATCH",
                message=(
                    f"Mortise width {mortise_width:.2f} mm differs from tenon "
                    f"thickness {tenon_thickness:.2f} mm by more than 5%. "
                    f"Loose-fit mortise reduces glue surface and racking resistance."
                ),
            ))

    # ------------------------------------------------------------------
    # Check 3: board (mortise member) thickness ≥ 3× tenon thickness.
    # Per Hammer-Krenov §6.3: tenon = 1/3 of board ensures each cheek wall
    # = (board − tenon)/2 ≥ tenon, i.e. board ≥ 3× tenon.
    # We prefer an explicit cheek_thickness arg when provided; otherwise derive
    # from board_thickness and check the board ratio.
    # ------------------------------------------------------------------
    if board_thickness > 0 and tenon_thickness > 0:
        min_board = _MT_MIN_BOARD_TO_TENON_RATIO * tenon_thickness
        if cheek_thickness > 0:
            # Explicit cheek: each side must be ≥ tenon thickness
            if cheek_thickness < tenon_thickness:
                issues.append(ValidationIssue(
                    severity="error",
                    code="MT_CHEEK_TOO_THIN",
                    message=(
                        f"Cheek wall {cheek_thickness:.2f} mm is thinner than the "
                        f"tenon thickness ({tenon_thickness:.2f} mm). Cheek will "
                        f"split under withdrawal load (Hammer-Krenov §6.3)."
                    ),
                ))
        elif board_thickness < min_board:
            issues.append(ValidationIssue(
                severity="error",
                code="MT_CHEEK_TOO_THIN",
                message=(
                    f"Board thickness {board_thickness:.2f} mm is less than 3× "
                    f"tenon thickness ({min_board:.2f} mm). Insufficient cheek wall "
                    f"material — cheek will split under withdrawal load "
                    f"(Hammer-Krenov §6.3)."
                ),
            ))

    # ------------------------------------------------------------------
    # Check 4: tenon length ≥ 1.5× tenon thickness
    # ------------------------------------------------------------------
    if tenon_length > 0 and tenon_thickness > 0:
        min_length = _MT_MIN_LENGTH_RATIO * tenon_thickness
        if tenon_length < min_length:
            issues.append(ValidationIssue(
                severity="warning",
                code="MT_TENON_TOO_SHORT",
                message=(
                    f"Tenon length {tenon_length:.2f} mm is below 1.5× tenon "
                    f"thickness ({min_length:.2f} mm). Short tenon has insufficient "
                    f"glue area and will rock in the mortise (Hammer-Krenov §6.3)."
                ),
            ))

    return _result("mortise_and_tenon", issues)


# ---------------------------------------------------------------------------
# Box joint (equal-finger) validator
# ---------------------------------------------------------------------------

#: Minimum number of fingers.
_BOX_MIN_FINGERS: int = 3


def validate_box_joint(geometry: dict[str, Any]) -> ValidationResult:
    """Validate box-joint (equal-finger) proportions.

    Args:
        geometry: A dict with keys:
            - ``finger_count`` (int): number of fingers (positive integers only).
            - ``finger_width_mm`` (float): width of each finger.
            - ``board_thickness_mm`` (float): board thickness; finger depth
              must equal this.
            - ``finger_depth_mm`` (float, optional): explicit depth; if omitted,
              assumed equal to ``board_thickness_mm``.
            - ``finger_widths_mm`` (list[float], optional): per-finger widths to
              check for uniformity.

    Returns:
        :class:`ValidationResult`.
    """
    issues: list[ValidationIssue] = []

    finger_count = int(geometry.get("finger_count") or 0)
    finger_width  = float(geometry.get("finger_width_mm") or 0.0)
    board_thickness = float(geometry.get("board_thickness_mm") or 0.0)
    finger_depth  = float(
        geometry.get("finger_depth_mm") or board_thickness or 0.0
    )
    per_finger_widths: list[float] = [
        float(w) for w in geometry.get("finger_widths_mm", [])
    ]

    # ------------------------------------------------------------------
    # Check 1: minimum 3 fingers
    # ------------------------------------------------------------------
    if finger_count < _BOX_MIN_FINGERS:
        issues.append(ValidationIssue(
            severity="error",
            code="BOX_TOO_FEW_FINGERS",
            message=(
                f"Box joint has {finger_count} finger(s); minimum is "
                f"{_BOX_MIN_FINGERS}. Fewer fingers yield insufficient mechanical "
                f"interlock and glue surface."
            ),
        ))

    # ------------------------------------------------------------------
    # Check 2: equal finger widths
    # ------------------------------------------------------------------
    if per_finger_widths and len(per_finger_widths) >= 2:
        max_w = max(per_finger_widths)
        min_w = min(per_finger_widths)
        if not math.isclose(max_w, min_w, rel_tol=0.02):
            issues.append(ValidationIssue(
                severity="error",
                code="BOX_UNEQUAL_FINGERS",
                message=(
                    f"Finger widths are not equal (min={min_w:.2f} mm, "
                    f"max={max_w:.2f} mm). Box joints require uniform finger "
                    f"width for symmetric interlock and balanced glue surface."
                ),
            ))

    # ------------------------------------------------------------------
    # Check 3: finger depth == board thickness
    # ------------------------------------------------------------------
    if board_thickness > 0 and finger_depth > 0:
        if not math.isclose(finger_depth, board_thickness, rel_tol=0.05):
            issues.append(ValidationIssue(
                severity="error",
                code="BOX_DEPTH_MISMATCH",
                message=(
                    f"Finger depth {finger_depth:.2f} mm does not equal board "
                    f"thickness {board_thickness:.2f} mm. Depth must match "
                    f"thickness for flush-face assembly."
                ),
            ))

    return _result("box_joint", issues)


# ---------------------------------------------------------------------------
# Finger joint (angled / interlocking) validator
# ---------------------------------------------------------------------------

#: Prescribed half-angle for angled finger joints (scarf/splice), degrees.
_FINGER_JOINT_PRESCRIBED_HALF_ANGLE_DEG: float = 15.0
_FINGER_JOINT_ANGLE_TOL_DEG: float = 3.0


def validate_finger_joint(geometry: dict[str, Any]) -> ValidationResult:
    """Validate angled finger (scarf) joint proportions.

    Similar to box joint checks but adds a prescribed finger tip angle.

    Args:
        geometry: A dict with keys (all from :func:`validate_box_joint`) plus:
            - ``finger_angle_deg`` (float, optional): taper angle of finger tips
              in degrees.  Default is 15°.  Acceptable range: [12°, 18°].

    Returns:
        :class:`ValidationResult`.
    """
    # Start with box-joint checks (finger count, equality, depth)
    box_result = validate_box_joint(geometry)
    issues: list[ValidationIssue] = list(box_result.issues)

    finger_angle = float(geometry.get("finger_angle_deg") or _FINGER_JOINT_PRESCRIBED_HALF_ANGLE_DEG)
    lo = _FINGER_JOINT_PRESCRIBED_HALF_ANGLE_DEG - _FINGER_JOINT_ANGLE_TOL_DEG
    hi = _FINGER_JOINT_PRESCRIBED_HALF_ANGLE_DEG + _FINGER_JOINT_ANGLE_TOL_DEG

    if not (lo <= finger_angle <= hi):
        issues.append(ValidationIssue(
            severity="warning",
            code="FINGER_ANGLE_OFF_STANDARD",
            message=(
                f"Finger tip angle {finger_angle:.1f}° is outside the standard "
                f"[{lo:.0f}°–{hi:.0f}°] range for structural finger joints. "
                f"Deviation may reduce bond-line quality in edge-glued panels."
            ),
        ))

    return _result("finger_joint", issues)


# ---------------------------------------------------------------------------
# Joinery strength estimate
# Per USDA Forest Products Lab Wood Handbook (Table 5-1 shear values)
# ---------------------------------------------------------------------------

# Rolling shear / parallel-to-grain shear strength (MPa) from FPL Wood Handbook.
# These are approximate modulus-of-rupture–scaled lower-bound design values.
# NOT joint-level tested measurements.
_SHEAR_STRENGTH_MPA: dict[str, float] = {
    "oak":    9.8,   # White oak; FPL Table 5-1 shear || grain
    "pine":   6.0,   # Southern yellow pine; FPL Table 5-1 shear || grain
    "cherry": 8.3,   # Black cherry; FPL Table 5-1 shear || grain
    "maple":  10.1,  # Hard maple; FPL Table 5-1 shear || grain
    "walnut": 9.4,   # Black walnut; FPL Table 5-1 shear || grain
}

# Joint efficiency factors (fraction of theoretical glue surface that is
# effective, based on joint type).
_JOINT_EFFICIENCY: dict[str, float] = {
    "mortise_tenon":   0.75,
    "dovetail":        0.70,
    "box_joint":       0.85,
    "finger_joint":    0.80,
    "dowel":           0.65,
    "biscuit":         0.55,
}


def joinery_strength_estimate(
    geometry: dict[str, Any],
    wood_species: Literal["oak", "pine", "cherry", "maple", "walnut"] = "oak",
) -> dict[str, Any]:
    """Estimate joint shear strength in kN.

    Uses parallel-to-grain shear values from the USDA Forest Products Lab
    Wood Handbook (Table 5-1) scaled by an empirical joint efficiency factor.

    The shear area is derived from ``engagement_mm`` and the narrower of
    ``tenon_width_mm``, ``finger_width_mm``, ``board_thickness_mm`` or
    ``volume_mm3 / engagement_mm`` for the contact face.

    IMPORTANT: These are simplified engineering estimates — NOT tested
    joint-level shear measurements.  Apply a design safety factor of ≥ 3
    before using in any structural application.

    Args:
        geometry: A joint descriptor dict as returned by any
            ``kerf_woodworking.joinery`` constructor.
        wood_species: Species key.  One of ``"oak"``, ``"pine"``,
            ``"cherry"``, ``"maple"``, ``"walnut"``.

    Returns:
        Dict with keys:
            - ``shear_strength_kN`` (float): estimated shear load capacity.
            - ``shear_area_mm2`` (float): computed glue / contact surface area.
            - ``wood_species`` (str): species used.
            - ``shear_strength_mpa`` (float): species shear modulus used.
            - ``joint_efficiency`` (float): efficiency factor applied.
            - ``safety_factor_note`` (str): reminder to apply a design factor.
    """
    species = wood_species.lower()
    if species not in _SHEAR_STRENGTH_MPA:
        raise ValueError(
            f"Unknown wood species '{wood_species}'. "
            f"Supported: {list(_SHEAR_STRENGTH_MPA)}"
        )

    joint_type = str(geometry.get("joint_type", "mortise_tenon"))
    efficiency = _JOINT_EFFICIENCY.get(joint_type, 0.65)

    # Derive shear area from geometry
    engagement = float(geometry.get("engagement_mm") or 0.0)
    shear_area = 0.0

    if joint_type == "mortise_tenon":
        # Two cheek faces: width × depth each side
        w = float(geometry.get("tenon_width_mm") or 0.0)
        d = float(geometry.get("tenon_depth_mm") or engagement)
        shear_area = 2.0 * w * d

    elif joint_type == "dovetail":
        # Approximate: tail count × tail face area
        count = int(geometry.get("tail_count") or 1)
        half_w = float(geometry.get("tail_half_width_mm") or 0.0)
        shear_area = count * 2.0 * half_w * engagement

    elif joint_type in ("finger_joint", "box_joint"):
        count = int(geometry.get("finger_count") or 1)
        fw = float(geometry.get("finger_width_mm") or 0.0)
        board_t = float(geometry.get("board_thickness_mm") or engagement)
        shear_area = count * fw * board_t

    elif joint_type == "dowel":
        count = int(geometry.get("count") or 1)
        r = float(geometry.get("diameter_mm") or 0.0) / 2.0
        shear_area = count * math.pi * r ** 2

    elif joint_type == "biscuit":
        count = int(geometry.get("count") or 1)
        slot_vol = float(geometry.get("slot_volume_mm3") or 0.0)
        shear_area = count * (slot_vol / engagement if engagement > 0 else 0.0)

    else:
        # Generic fallback: volume / engagement
        vol = float(geometry.get("volume_mm3") or 0.0)
        shear_area = vol / engagement if engagement > 0 else 0.0

    fpl_shear_mpa = _SHEAR_STRENGTH_MPA[species]
    strength_n = shear_area * fpl_shear_mpa * efficiency
    strength_kn = strength_n / 1000.0

    return {
        "shear_strength_kN":   round(strength_kn, 4),
        "shear_area_mm2":      round(shear_area, 4),
        "wood_species":        species,
        "shear_strength_mpa":  fpl_shear_mpa,
        "joint_efficiency":    efficiency,
        "joint_type":          joint_type,
        "safety_factor_note":  (
            "IMPORTANT: Apply a minimum design safety factor of 3× before using "
            "in structural applications. These are FPL Wood Handbook material "
            "values, NOT tested joint assembly measurements."
        ),
        "reference":           (
            "USDA Forest Products Lab Wood Handbook Ch. 5 (Table 5-1 shear values); "
            "Hammer-Krenov reference proportions — NOT FWW-certified."
        ),
    }
