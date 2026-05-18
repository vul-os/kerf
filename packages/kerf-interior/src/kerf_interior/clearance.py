"""
ADA (Americans with Disabilities Act) and ANSI A117.1 dimensional checks.

All public functions work in millimetres internally.  Imperial constants are
converted once at module load so there is a single source of truth.

Key references
--------------
- ADA Standards for Accessible Design, 2010 (DOJ)
- ANSI A117.1-2009: Accessible and Usable Buildings and Facilities
- ICC A117.1-2017: updated reach-range tables

Dimension summary
-----------------
Turning circle        : 60 in / 1524 mm diameter  (§304.3.1)
Corridor clear width  : 36 in /  914 mm minimum   (§403.5.1)
Knee clearance height : 27 in /  686 mm minimum   (§306.3.1)
Knee clearance depth  : 19 in /  483 mm minimum   (§306.3.3)
Reach range high      : 48 in / 1219 mm maximum   (§308.2.1 unobstructed forward)
Reach range low       : 15 in /  381 mm minimum   (§308.2.1)
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Sequence


# ---------------------------------------------------------------------------
# ADA / ANSI constants (all in mm)
# ---------------------------------------------------------------------------

#: Wheelchair turning-circle diameter per ADA §304.3.1.
TURNING_CIRCLE_DIAMETER_MM: float = 1524.0   # 60 in

#: Minimum accessible corridor / clear-floor width per ADA §403.5.1.
MIN_CORRIDOR_WIDTH_MM: float = 914.0          # 36 in

#: Minimum knee-clearance height (underside of surface) per ADA §306.3.1.
MIN_KNEE_CLEARANCE_HEIGHT_MM: float = 686.0   # 27 in

#: Minimum knee-clearance depth per ADA §306.3.3.
MIN_KNEE_CLEARANCE_DEPTH_MM: float = 483.0    # 19 in

#: Maximum forward reach (high) — unobstructed, per ADA §308.2.1.
MAX_REACH_HIGH_MM: float = 1219.0             # 48 in

#: Minimum forward reach (low) per ADA §308.2.1.
MIN_REACH_LOW_MM: float = 381.0               # 15 in


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ADAViolation:
    """A single ADA/ANSI dimensional violation."""
    rule: str
    """Short rule identifier, e.g. ``"turning_radius"``, ``"corridor_width"``."""
    actual_mm: float
    """Measured dimension in millimetres."""
    limit_mm: float
    """Required dimension in millimetres."""
    message: str
    """Human-readable description of the violation."""

    @property
    def deficit_mm(self) -> float:
        """How far the actual value falls short of (or exceeds) the limit."""
        return self.limit_mm - self.actual_mm


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------

def turning_circle_diameter_mm(radius_mm: float | None = None) -> float:
    """Return the ADA wheelchair turning-circle diameter in mm.

    Parameters
    ----------
    radius_mm:
        If given, treat this as a circular-clearance radius and return the
        corresponding diameter.  If ``None``, return the canonical ADA value
        of 1524 mm (60 in).
    """
    if radius_mm is None:
        return TURNING_CIRCLE_DIAMETER_MM
    return radius_mm * 2.0


def check_turning_radius(
    clearance_diameter_mm: float,
    *,
    tolerance_mm: float = 5.0,
) -> list[ADAViolation]:
    """Check that a circular clear-floor area meets the ADA turning-circle.

    Parameters
    ----------
    clearance_diameter_mm:
        Diameter of the available clear-floor circle in millimetres.
    tolerance_mm:
        Allowed construction tolerance (default 5 mm).  The diameter must be
        at least ``TURNING_CIRCLE_DIAMETER_MM - tolerance_mm``.

    Returns
    -------
    list[ADAViolation]
        Empty list if compliant; one ``ADAViolation`` otherwise.
    """
    required = TURNING_CIRCLE_DIAMETER_MM - tolerance_mm
    if clearance_diameter_mm < required:
        return [
            ADAViolation(
                rule="turning_radius",
                actual_mm=clearance_diameter_mm,
                limit_mm=TURNING_CIRCLE_DIAMETER_MM,
                message=(
                    f"Turning-circle diameter {clearance_diameter_mm:.1f} mm is less than "
                    f"ADA minimum {TURNING_CIRCLE_DIAMETER_MM:.0f} mm (60 in). "
                    f"Deficit: {TURNING_CIRCLE_DIAMETER_MM - clearance_diameter_mm:.1f} mm."
                ),
            )
        ]
    return []


def check_corridor_clearance(
    corridor_width_mm: float,
    *,
    tolerance_mm: float = 0.0,
) -> list[ADAViolation]:
    """Check that a corridor/passage meets the ADA minimum clear width.

    Parameters
    ----------
    corridor_width_mm:
        Clear (unobstructed) corridor width in millimetres.
    tolerance_mm:
        Allowed construction tolerance.

    Returns
    -------
    list[ADAViolation]
        Empty list if compliant; one ``ADAViolation`` otherwise.
    """
    required = MIN_CORRIDOR_WIDTH_MM - tolerance_mm
    if corridor_width_mm < required:
        return [
            ADAViolation(
                rule="corridor_width",
                actual_mm=corridor_width_mm,
                limit_mm=MIN_CORRIDOR_WIDTH_MM,
                message=(
                    f"Corridor width {corridor_width_mm:.1f} mm is less than "
                    f"ADA minimum {MIN_CORRIDOR_WIDTH_MM:.0f} mm (36 in). "
                    f"Deficit: {MIN_CORRIDOR_WIDTH_MM - corridor_width_mm:.1f} mm."
                ),
            )
        ]
    return []


def check_knee_clearance(
    height_mm: float,
    depth_mm: float,
) -> list[ADAViolation]:
    """Check that a knee-clearance recess meets ADA §306.3 requirements.

    Parameters
    ----------
    height_mm:
        Clear height from finished floor to the underside of the surface
        (desk, counter, etc.) in millimetres.
    depth_mm:
        Depth of the clear space under the surface in millimetres.

    Returns
    -------
    list[ADAViolation]
        List of violations (may be empty or contain one or two items).
    """
    violations: list[ADAViolation] = []

    if height_mm < MIN_KNEE_CLEARANCE_HEIGHT_MM:
        violations.append(
            ADAViolation(
                rule="knee_clearance_height",
                actual_mm=height_mm,
                limit_mm=MIN_KNEE_CLEARANCE_HEIGHT_MM,
                message=(
                    f"Knee-clearance height {height_mm:.1f} mm is less than "
                    f"ADA minimum {MIN_KNEE_CLEARANCE_HEIGHT_MM:.0f} mm (27 in)."
                ),
            )
        )

    if depth_mm < MIN_KNEE_CLEARANCE_DEPTH_MM:
        violations.append(
            ADAViolation(
                rule="knee_clearance_depth",
                actual_mm=depth_mm,
                limit_mm=MIN_KNEE_CLEARANCE_DEPTH_MM,
                message=(
                    f"Knee-clearance depth {depth_mm:.1f} mm is less than "
                    f"ADA minimum {MIN_KNEE_CLEARANCE_DEPTH_MM:.0f} mm (19 in)."
                ),
            )
        )

    return violations


def check_reach_range(
    reach_height_mm: float,
    *,
    check_high: bool = True,
    check_low: bool = True,
) -> list[ADAViolation]:
    """Check that a reach height falls within the ADA §308.2 forward reach range.

    Parameters
    ----------
    reach_height_mm:
        Height of the element being reached (switch, shelf, control panel, etc.)
        in millimetres above finished floor.
    check_high:
        Whether to check the high-reach limit (default True).
    check_low:
        Whether to check the low-reach limit (default True).

    Returns
    -------
    list[ADAViolation]
        Violations found (may be empty, or contain 1-2 items).
    """
    violations: list[ADAViolation] = []

    if check_high and reach_height_mm > MAX_REACH_HIGH_MM:
        violations.append(
            ADAViolation(
                rule="reach_range_high",
                actual_mm=reach_height_mm,
                limit_mm=MAX_REACH_HIGH_MM,
                message=(
                    f"Reach height {reach_height_mm:.1f} mm exceeds ADA maximum "
                    f"{MAX_REACH_HIGH_MM:.0f} mm (48 in). "
                    f"Excess: {reach_height_mm - MAX_REACH_HIGH_MM:.1f} mm."
                ),
            )
        )

    if check_low and reach_height_mm < MIN_REACH_LOW_MM:
        violations.append(
            ADAViolation(
                rule="reach_range_low",
                actual_mm=reach_height_mm,
                limit_mm=MIN_REACH_LOW_MM,
                message=(
                    f"Reach height {reach_height_mm:.1f} mm is below ADA minimum "
                    f"{MIN_REACH_LOW_MM:.0f} mm (15 in)."
                ),
            )
        )

    return violations


def audit_clearances(
    *,
    turning_diameter_mm: float | None = None,
    corridor_widths_mm: Sequence[float] = (),
    knee_clearances: Sequence[tuple[float, float]] = (),
    reach_heights_mm: Sequence[float] = (),
) -> list[ADAViolation]:
    """Run a batch ADA audit and return all violations found.

    Parameters
    ----------
    turning_diameter_mm:
        Clear-floor turning-circle diameter to check (optional).
    corridor_widths_mm:
        Sequence of corridor widths to check.
    knee_clearances:
        Sequence of ``(height_mm, depth_mm)`` pairs to check.
    reach_heights_mm:
        Sequence of reach heights to check.

    Returns
    -------
    list[ADAViolation]
        All violations found across all checks.
    """
    violations: list[ADAViolation] = []

    if turning_diameter_mm is not None:
        violations.extend(check_turning_radius(turning_diameter_mm))

    for width in corridor_widths_mm:
        violations.extend(check_corridor_clearance(width))

    for height, depth in knee_clearances:
        violations.extend(check_knee_clearance(height, depth))

    for height in reach_heights_mm:
        violations.extend(check_reach_range(height))

    return violations
