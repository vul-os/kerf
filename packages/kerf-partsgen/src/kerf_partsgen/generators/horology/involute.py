"""Involute tooth-profile geometry.

The involute of a circle is the curve traced by a point on a taut string
unwound from a cylinder (the base circle of radius ``r_b``).

Parametric form (pressure angle ``phi`` used as the rolling parameter ``t``):

    x(t) = r_b * (cos t  +  t * sin t)
    y(t) = r_b * (sin t  -  t * cos t)

Reference: Shigley's Mechanical Engineering Design §13-5; AGMA 908-B89.

For horology / fine-pitch gears the module ``m`` (mm/tooth), number of teeth
``z``, and pressure angle ``alpha`` (typically 14.5° or 20° for clocks,
20° for modern Swiss watches) fully define the tooth geometry:

    pitch_diameter  d   = m * z
    base-circle     r_b = (d/2) * cos(alpha)
    addendum        a   = m          (standard full-depth)
    dedendum        b   = 1.25 * m  (standard full-depth)
    tip radius      r_a = d/2 + a
    root radius     r_f = d/2 - b

Involute profile validity criteria (this module's ``check_involute_profile``):

  1. Base-circle radius is positive and strictly less than the pitch radius.
  2. The involute starts at or below the base circle (t_start ≥ 0).
  3. The involute spans at least the full addendum height (points extend to
     r ≥ r_a − tolerance, where r = ||(x, y)||).
  4. Profile points are monotonically increasing in radius along the flank
     (the tooth does not fold back on itself).
  5. Adjacent profile points satisfy the smoothness criterion (chord length
     < 2× average spacing — no discontinuities).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import NamedTuple


# ---------------------------------------------------------------------------
# Core involute parametric curve
# ---------------------------------------------------------------------------


class ProfilePoint(NamedTuple):
    x: float
    y: float
    t: float   # involute parameter (rolling angle, radians)
    r: float   # polar radius = sqrt(x²+y²)


def involute_profile(
    module: float,
    num_teeth: int,
    pressure_angle_deg: float = 20.0,
    n_points: int = 40,
) -> list[ProfilePoint]:
    """Generate one flank of an involute tooth profile (right-hand side).

    Parameters
    ----------
    module:
        Tooth module in mm (pitch_diameter / num_teeth).
    num_teeth:
        Number of teeth on the gear.
    pressure_angle_deg:
        Standard pressure angle in degrees (20° for modern Swiss watches).
    n_points:
        Number of profile sample points from base-circle to tip.

    Returns
    -------
    List of ``ProfilePoint`` sampled from the base-circle intersection to
    the tip-circle, ordered from root to tip (increasing radius).
    """
    if module <= 0:
        raise ValueError(f"module must be positive, got {module}")
    if num_teeth < 6:
        raise ValueError(f"num_teeth must be >= 6, got {num_teeth}")
    if not (0 < pressure_angle_deg < 90):
        raise ValueError(f"pressure_angle_deg must be in (0, 90), got {pressure_angle_deg}")

    alpha = math.radians(pressure_angle_deg)
    d = module * num_teeth           # pitch diameter
    r_p = d / 2.0                   # pitch radius
    r_b = r_p * math.cos(alpha)     # base-circle radius
    r_a = r_p + module              # tip-circle radius (addendum = module)

    # t at which the involute reaches the pitch circle: inv(alpha) = tan(alpha) - alpha
    t_pitch = math.tan(alpha)

    # t at which the involute reaches the tip circle:
    # r(t) = r_b * sqrt(1 + t^2)  → t_tip = sqrt((r_a/r_b)^2 - 1)
    t_tip = math.sqrt(max((r_a / r_b) ** 2 - 1.0, 0.0))

    # Profile spans t in [0, t_tip] (t=0 is at the base circle)
    points: list[ProfilePoint] = []
    for i in range(n_points):
        t = t_tip * i / (n_points - 1)
        x = r_b * (math.cos(t) + t * math.sin(t))
        y = r_b * (math.sin(t) - t * math.cos(t))
        r = math.hypot(x, y)
        points.append(ProfilePoint(x=x, y=y, t=t, r=r))

    return points


# ---------------------------------------------------------------------------
# Validity checker
# ---------------------------------------------------------------------------


@dataclass
class InvoluteCheckResult:
    passed: bool
    reasons: list[str] = field(default_factory=list)
    r_base: float = 0.0
    r_pitch: float = 0.0
    r_tip: float = 0.0
    n_points: int = 0


def check_involute_profile(
    module: float,
    num_teeth: int,
    pressure_angle_deg: float = 20.0,
    n_points: int = 40,
    tip_tol_mm: float = 1e-6,
) -> InvoluteCheckResult:
    """Validate that an involute tooth profile satisfies all geometry criteria.

    Returns an ``InvoluteCheckResult`` with ``passed=True`` when all five
    criteria from the module docstring are satisfied.

    Parameters
    ----------
    module, num_teeth, pressure_angle_deg:
        Same as :func:`involute_profile`.
    tip_tol_mm:
        Tolerance for criterion 3 (profile must reach within ``tip_tol_mm``
        of the theoretical tip circle).
    """
    reasons: list[str] = []

    try:
        profile = involute_profile(module, num_teeth, pressure_angle_deg, n_points)
    except ValueError as exc:
        return InvoluteCheckResult(passed=False, reasons=[str(exc)])

    alpha = math.radians(pressure_angle_deg)
    d = module * num_teeth
    r_p = d / 2.0
    r_b = r_p * math.cos(alpha)
    r_a = r_p + module

    result = InvoluteCheckResult(
        passed=False,
        r_base=r_b,
        r_pitch=r_p,
        r_tip=r_a,
        n_points=len(profile),
    )

    # Criterion 1: base-circle radius positive and < pitch radius
    if r_b <= 0:
        reasons.append(f"base-circle radius {r_b:.6f} <= 0")
    if r_b >= r_p:
        reasons.append(
            f"base-circle radius {r_b:.6f} >= pitch radius {r_p:.6f}"
        )

    if not profile:
        reasons.append("profile is empty")
        result.reasons = reasons
        return result

    # Criterion 2: first point starts at or below base circle
    t0 = profile[0].t
    if t0 < 0:
        reasons.append(f"first profile parameter t={t0:.6f} < 0")

    # Criterion 3: profile reaches the tip circle
    max_r = max(pt.r for pt in profile)
    if max_r < r_a - tip_tol_mm:
        reasons.append(
            f"profile max radius {max_r:.6f} does not reach tip circle "
            f"{r_a:.6f} (short by {r_a - max_r:.6f} mm)"
        )

    # Criterion 4: radii monotonically non-decreasing
    for i in range(1, len(profile)):
        if profile[i].r < profile[i - 1].r - 1e-10:
            reasons.append(
                f"profile not monotone at index {i}: "
                f"r[{i}]={profile[i].r:.6f} < r[{i-1}]={profile[i-1].r:.6f}"
            )
            break  # report first violation only

    # Criterion 5: smoothness (no discontinuities — chord < 2x mean spacing)
    chords = [
        math.hypot(profile[i].x - profile[i - 1].x,
                   profile[i].y - profile[i - 1].y)
        for i in range(1, len(profile))
    ]
    if chords:
        mean_chord = sum(chords) / len(chords)
        for i, c in enumerate(chords):
            if c > 2.0 * mean_chord + 1e-10:
                reasons.append(
                    f"discontinuity at index {i+1}: chord {c:.6f} > "
                    f"2x mean {mean_chord:.6f}"
                )
                break

    result.passed = not reasons
    result.reasons = reasons
    return result
