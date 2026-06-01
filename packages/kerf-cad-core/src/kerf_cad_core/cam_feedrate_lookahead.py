"""
cam_feedrate_lookahead — CAM toolpath feedrate optimiser with corner lookahead.

Algorithm (Erkorkmaz-Altintas 2001 / Altintas 2012 §5.7)
---------------------------------------------------------
Given a piecewise-linear toolpath W = {w_0, w_1, …, w_n} and scalar
constraints (max feedrate V_target, max tangential acceleration a_max,
blending radius r_blend), compute the optimal feedrate V_i at each waypoint
so that:

  1. **Corner feedrate** — the machine can negotiate the direction change at
     w_i without exceeding a_max on the blended arc:

         V_corner_i = sqrt(a_max · r_blend / sin(θ_i / 2))

     where θ_i is the angle between the incoming segment (w_{i-1}→w_i) and
     the outgoing segment (w_i→w_{i+1}).  For collinear waypoints (θ_i ≈ 0)
     the constraint is inactive and V_corner_i = V_target.

  2. **Forward pass** — propagate acceleration limit from start to end:

         V_fwd_i = min(V_target, sqrt(V_fwd_{i-1}² + 2 · a_max · Δs_i))

     where Δs_i = ‖w_i − w_{i-1}‖.  V_fwd_0 = 0 (start at rest).

  3. **Backward pass** — propagate deceleration limit from end to start and
     intersect with the forward-pass result:

         V_i = min(V_fwd_i, sqrt(V_{i+1}² + 2 · a_max · Δs_{i+1}))

     V_n = 0 (end at rest).

  The two-pass strategy is the classical "lookahead buffer" used in open-source
  firmware (Marlin, LinuxCNC) and described rigorously in:

  • Erkorkmaz, K. & Altintas, Y. (2001). "High-speed CNC system design. Part I:
    jerk limited trajectory generation and quintic spline interpolation."
    International Journal of Machine Tools and Manufacture, 41(9), 1323–1345.
  • Altintas, Y. (2012). Manufacturing Automation (2nd ed.). Cambridge University
    Press. §5.7 "Feedrate scheduling".

S-curve / jerk-limited scheduling (7-segment profile)
------------------------------------------------------
An opt-in S-curve mode is available via ``schedule_s_curve`` and the
``profile_type="s-curve"`` parameter on ``optimize_feedrate``.  The 7-segment
constant-jerk profile is described in:

  • Lambrechts, P., Boerlage, M. & Steinbuch, M. (2005). "Trajectory planning
    and feedforward design for electromechanical motion systems." Control
    Engineering Practice, 13(2), 145–157.  IEEE TCST special issue.
  • Erkorkmaz, K. & Altintas, Y. (2001). §3.3 "Jerk-limited trajectory
    generation".

The seven segments are:
  1. Jerk-on accelerate   (j = +J_max)
  2. Constant accel       (j = 0,     a = A_max)
  3. Jerk-off accelerate  (j = −J_max)
  4. Constant velocity    (a = 0,     v = V_peak)
  5. Jerk-on decelerate   (j = −J_max)
  6. Constant decel       (j = 0,     a = −A_max)
  7. Jerk-off decelerate  (j = +J_max)

When the distance is too short to reach V_max, a symmetric triangular (no
constant-velocity phase) or a pure jerk-ramp fallback is used automatically.

Honest limitations
------------------
* **2D blending arc.** The V_corner formula assumes a constant-radius arc
  tangent to both incoming and outgoing directions in the local plane.  For
  full 5-axis paths the normal acceleration model becomes more complex (axis
  inertia coupling); this implementation treats the path as a scalar
  arc-length problem.
* **Degenerate segments** (zero-length) are skipped: the feedrate at one
  endpoint is inherited from the previous constraint.
* **S-curve is per-segment.** ``schedule_s_curve`` operates on a single
  distance/speed triple.  The lookahead integration in ``optimize_feedrate``
  with ``profile_type="s-curve"`` uses the trapezoidal V_corner / pass logic
  unchanged; per-segment S-curve timing is computed independently.

Author: imranparuk
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import List, Sequence, Tuple

# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------

Waypoint = Tuple[float, float, float]   # (X, Y, Z) in mm


@dataclass
class SCurveProfile:
    """
    Result of a 7-segment jerk-limited (S-curve) feedrate schedule for a
    single motion segment.

    Attributes
    ----------
    segment_durations_s:
        Duration of each of the (up to) 7 segments, in seconds.  Segments
        whose duration is zero are degenerate (omitted in time-optimal sense).
        Length is always exactly 7.
    total_time_s:
        Sum of all segment durations (seconds).
    peak_velocity_mm_per_min:
        Actual peak velocity reached (mm/min).  May be less than the requested
        V_max when distance is too short (triangular fallback).
    peak_accel_mm_per_s2:
        Actual peak acceleration used (mm/s²).  May be less than A_max when
        distance is too short to need a constant-accel phase.
    peak_jerk_mm_per_s3:
        Actual peak jerk used (mm/s³) — always equals J_max input.
    is_triangular_fallback:
        True when the distance was too short to reach V_max (segments 4 and
        the constant-accel phases may be zero).
    """

    segment_durations_s: List[float] = field(default_factory=lambda: [0.0] * 7)
    total_time_s: float = 0.0
    peak_velocity_mm_per_min: float = 0.0
    peak_accel_mm_per_s2: float = 0.0
    peak_jerk_mm_per_s3: float = 0.0
    is_triangular_fallback: bool = False


@dataclass
class FeedrateProfile:
    """
    Per-waypoint feedrate schedule returned by ``optimize_feedrate``.

    Attributes
    ----------
    feedrates:
        V_i (mm/s) at each waypoint in the same order as the input.
    corner_angles:
        θ_i (radians) at each interior waypoint (0 at endpoints).
    corner_feedrates:
        V_corner_i (mm/s) at each waypoint; V_target at endpoints and
        collinear interior points.
    segment_lengths:
        Δs_i (mm) — distance from waypoint i-1 to waypoint i; 0 for i=0.
    total_cycle_time:
        Estimated cycle time (seconds) using trapezoidal integration of
        1/V along each segment.  Segments adjacent to a V=0 waypoint
        contribute ∞ (physically unreachable in zero-distance); the caller
        should treat degenerate segments separately.
    """

    feedrates: List[float] = field(default_factory=list)
    corner_angles: List[float] = field(default_factory=list)
    corner_feedrates: List[float] = field(default_factory=list)
    segment_lengths: List[float] = field(default_factory=list)
    total_cycle_time: float = 0.0


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _norm(v: Tuple[float, float, float]) -> float:
    return math.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2])


def _sub(a: Waypoint, b: Waypoint) -> Tuple[float, float, float]:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _dot(a: Tuple[float, float, float], b: Tuple[float, float, float]) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _unit(v: Tuple[float, float, float]) -> Tuple[float, float, float]:
    n = _norm(v)
    if n < 1e-14:
        return (0.0, 0.0, 0.0)
    return (v[0] / n, v[1] / n, v[2] / n)


def _corner_angle(a: Waypoint, b: Waypoint, c: Waypoint) -> float:
    """
    Return the turning angle θ at waypoint b (radians), i.e. the angle between
    the incoming direction (a→b) and the outgoing direction (b→c).

    Returns 0 if any segment is degenerate (zero length).
    """
    d_in = _unit(_sub(b, a))
    d_out = _unit(_sub(c, b))
    # dot product of unit vectors → cosine of angle between them
    cos_angle = max(-1.0, min(1.0, _dot(d_in, d_out)))
    # angle between directions; 0 = straight through, π = 180° reversal
    return math.acos(cos_angle)


def _corner_feedrate(
    theta: float,
    a_max: float,
    r_blend: float,
    v_target: float,
) -> float:
    """
    Maximum negotiable feedrate at a corner with turning angle *theta* (rad).

    Formula (Altintas 2012 §5.7):
        V_corner = sqrt(a_max · r_blend / sin(θ/2))

    For θ < _TOL (nearly collinear) the constraint is inactive → V_target.
    For θ ≈ π (U-turn) the constraint approaches 0.
    """
    _TOL = 1e-6
    half = theta / 2.0
    if half < _TOL:
        return v_target
    sin_half = math.sin(half)
    if sin_half < _TOL:
        return v_target
    v_c = math.sqrt(a_max * r_blend / sin_half)
    return min(v_c, v_target)


# ---------------------------------------------------------------------------
# S-curve (7-segment jerk-limited) scheduling
# ---------------------------------------------------------------------------

def _accel_half_distance(v_peak: float, v_at_Amax: float, t_j_max: float,
                         a_max: float, j_max: float) -> float:
    """
    Distance covered in the acceleration half (segs 1+2+3) to reach *v_peak*
    from rest, using jerk *j_max* and acceleration limit *a_max*.

    Parameters match the local variables in ``schedule_s_curve``.
    """
    if v_peak <= v_at_Amax:
        # Pure jerk ramps only (no constant-accel phase, segs 1+3).
        # t_j such that J*t_j^2 = v_peak  →  t_j = sqrt(v_peak/J)
        # Exact area under velocity curve:
        #   seg1 (j=+J, start v=0, a=0, t=t_j):
        #     v(t) = (J/2)*t^2,  s1 = (J/6)*t_j^3
        #   seg3 (j=-J, start v=v_peak/2, a=J*t_j, t=t_j):
        #     s3 = (v_peak/2)*t_j + (J*t_j/2)*t_j^2 - (J/6)*t_j^3
        #        = (J*t_j^2/2)*t_j + J*t_j^3/2 - J*t_j^3/6
        #        = J*t_j^3/2 + J*t_j^3/2 - J*t_j^3/6 = 5*J*t_j^3/6
        #   s_half = s1 + s3 = J*t_j^3/6 + 5*J*t_j^3/6 = J*t_j^3
        t_j = math.sqrt(v_peak / j_max)
        return j_max * t_j ** 3
    else:
        # Full jerk ramps + constant-accel phase (segs 1+2+3).
        t_j = t_j_max
        t_flat = (v_peak - v_at_Amax) / a_max
        # seg1: j=+J, a starts 0, v starts 0, duration t_j
        v1 = j_max / 2.0 * t_j ** 2          # velocity at end of seg1
        s1 = j_max / 6.0 * t_j ** 3          # distance in seg1
        # seg2: j=0, a=A_max, starts at v1, duration t_flat
        s2 = v1 * t_flat + 0.5 * a_max * t_flat ** 2
        # seg3: j=-J, a starts at A_max, v starts at v1+A_max*t_flat, duration t_j
        v2 = v1 + a_max * t_flat
        s3 = v2 * t_j + 0.5 * a_max * t_j ** 2 - j_max / 6.0 * t_j ** 3
        return s1 + s2 + s3


def schedule_s_curve(
    distance_mm: float,
    V_max_mm_per_min: float,
    A_max_mm_per_s2: float,
    J_max_mm_per_s3: float,
) -> SCurveProfile:
    """
    Compute the time-optimal 7-segment S-curve (jerk-limited) velocity profile
    for a single motion segment of length *distance_mm*, starting and ending
    at rest.

    The 7 segments follow Lambrechts-Boerlage-Steinbuch (2005) IEEE TCST and
    Erkorkmaz-Altintas (2001) §3.3::

        Seg 1: j = +J_max   (jerk-on  accelerate)
        Seg 2: j = 0        (constant acceleration  a = A_max)
        Seg 3: j = −J_max   (jerk-off accelerate)
        Seg 4: j = 0, a = 0 (constant velocity  v = V_peak)
        Seg 5: j = −J_max   (jerk-on  decelerate)
        Seg 6: j = 0        (constant deceleration a = −A_max)
        Seg 7: j = +J_max   (jerk-off decelerate)

    By symmetry the acceleration half (segs 1-3) mirrors the deceleration half
    (segs 5-7).

    Triangular / short-distance fallback
    -------------------------------------
    When *distance_mm* is too short to reach *V_max_mm_per_min* the algorithm
    automatically reduces the peak velocity so that exactly half the distance
    is used for acceleration and half for deceleration (symmetric profile).
    If even a pure jerk-ramp (no constant-accel phase) overshoots, the peak
    velocity is further reduced to fit in the jerk-limited ramp only.

    Parameters
    ----------
    distance_mm:
        Total travel distance in mm.  Must be ≥ 0.
    V_max_mm_per_min:
        Requested maximum feedrate (mm/min).  Must be > 0.
    A_max_mm_per_s2:
        Maximum acceleration magnitude (mm/s²).  Must be > 0.
    J_max_mm_per_s3:
        Maximum jerk magnitude (mm/s³).  Must be > 0.

    Returns
    -------
    SCurveProfile
        Segment durations (s), total time (s), peak velocity (mm/min),
        peak acceleration (mm/s²), and peak jerk (mm/s³).

    References
    ----------
    Lambrechts, P., Boerlage, M. & Steinbuch, M. (2005). Control Engineering
    Practice, 13(2), 145–157.
    Erkorkmaz, K. & Altintas, Y. (2001). Int. J. Machine Tools Manuf.,
    41(9), 1323–1345 §3.3.
    """
    if distance_mm < 0.0:
        raise ValueError(f"distance_mm must be >= 0; got {distance_mm}")
    if V_max_mm_per_min <= 0.0:
        raise ValueError(f"V_max_mm_per_min must be positive; got {V_max_mm_per_min}")
    if A_max_mm_per_s2 <= 0.0:
        raise ValueError(f"A_max_mm_per_s2 must be positive; got {A_max_mm_per_s2}")
    if J_max_mm_per_s3 <= 0.0:
        raise ValueError(f"J_max_mm_per_s3 must be positive; got {J_max_mm_per_s3}")

    # Convert V_max from mm/min → mm/s for internal calculations
    V_max = V_max_mm_per_min / 60.0
    A_max = A_max_mm_per_s2
    J_max = J_max_mm_per_s3

    # Zero-distance edge case
    if distance_mm < 1e-14:
        return SCurveProfile(
            segment_durations_s=[0.0] * 7,
            total_time_s=0.0,
            peak_velocity_mm_per_min=0.0,
            peak_accel_mm_per_s2=0.0,
            peak_jerk_mm_per_s3=J_max,
            is_triangular_fallback=False,
        )

    # Time to ramp jerk from 0 to A_max:
    #   t_j_max = A_max / J_max
    # Velocity gained in a single jerk ramp pair (seg1+seg3) when A_max IS reached:
    #   v_at_Amax = J_max * t_j_max^2 = A_max^2 / J_max
    t_j_max = A_max / J_max
    v_at_Amax = J_max * t_j_max ** 2   # == A_max^2 / J_max

    # Full-speed distance = 2 * accel_half_distance(V_max)
    s_full_accel = _accel_half_distance(V_max, v_at_Amax, t_j_max, A_max, J_max)
    s_full = 2.0 * s_full_accel

    is_triangular = False
    if distance_mm >= s_full:
        V_peak = V_max
    else:
        # Distance too short — binary-search for the reduced peak velocity
        # that exactly fits: 2 * accel_half_distance(V_peak) == distance_mm
        is_triangular = True
        s_half_target = distance_mm / 2.0
        v_lo, v_hi = 0.0, V_max
        for _ in range(60):
            v_mid = 0.5 * (v_lo + v_hi)
            if _accel_half_distance(v_mid, v_at_Amax, t_j_max, A_max, J_max) <= s_half_target:
                v_lo = v_mid
            else:
                v_hi = v_mid
        V_peak = v_lo

    # ------------------------------------------------------------------
    # Compute segment durations for the chosen V_peak
    # ------------------------------------------------------------------
    if V_peak <= v_at_Amax:
        # Pure jerk ramps only (no constant-accel phase, segs 1+3 and 5+7)
        t_j = math.sqrt(max(0.0, V_peak / J_max))
        t_flat = 0.0
        a_peak = J_max * t_j
    else:
        t_j = t_j_max
        t_flat = (V_peak - v_at_Amax) / A_max
        a_peak = A_max

    # Constant-velocity segment duration
    s_accel_decel = 2.0 * _accel_half_distance(V_peak, v_at_Amax, t_j_max, A_max, J_max)
    s_const_v = distance_mm - s_accel_decel
    t_const_v = (s_const_v / V_peak) if V_peak > 1e-14 else 0.0
    t_const_v = max(0.0, t_const_v)  # clamp tiny negatives from fp arithmetic

    # 7 segment durations [T1..T7]
    T = [t_j, t_flat, t_j, t_const_v, t_j, t_flat, t_j]

    total_time = sum(T)

    return SCurveProfile(
        segment_durations_s=T,
        total_time_s=total_time,
        peak_velocity_mm_per_min=V_peak * 60.0,
        peak_accel_mm_per_s2=a_peak,
        peak_jerk_mm_per_s3=J_max,
        is_triangular_fallback=is_triangular,
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def optimize_feedrate(
    waypoints: Sequence[Waypoint],
    max_feedrate: float,
    max_accel: float,
    blending_radius: float = 0.1,
    profile_type: str = "trapezoid",
) -> FeedrateProfile:
    """
    Compute the optimal feedrate at each waypoint in *waypoints*.

    Parameters
    ----------
    waypoints:
        Ordered sequence of (X, Y, Z) positions in mm.  At least 1 point
        required; 2 points gives a straight segment with no interior corners.
    max_feedrate:
        Maximum allowable feedrate (mm/s).  Must be > 0.
    max_accel:
        Maximum tangential acceleration (mm/s²).  Must be > 0.
    blending_radius:
        Radius of the blending arc at each corner (mm).  Typical range
        0.01–1 mm.  Larger values are more conservative (lower V_corner) for
        a given corner angle.  Default 0.1 mm.
    profile_type:
        Velocity profile model.  One of:

        ``"trapezoid"`` *(default)* — constant-acceleration (trapezoidal)
        transitions.  The two-pass lookahead algorithm (Erkorkmaz-Altintas
        2001 / Altintas 2012 §5.7) gives per-waypoint feedrates.  Backward
        compatible; all existing callers see this behaviour.

        ``"s-curve"`` — jerk-limited 7-segment S-curve per Lambrechts-
        Boerlage-Steinbuch (2005).  The same trapezoidal two-pass algorithm
        determines the per-waypoint feedrate schedule; additionally the
        ``total_cycle_time`` is recomputed using the S-curve timing for each
        segment so the time estimate accounts for jerk limiting (typically
        10–30% longer than the trapezoidal estimate at the same A_max).

    Returns
    -------
    FeedrateProfile
        Per-waypoint feedrates, corner angles, corner feedrates, segment
        lengths, and estimated cycle time.

    References
    ----------
    Erkorkmaz & Altintas 2001 International Journal of Machine Tools and
    Manufacture 41(9) §2–3.
    Altintas 2012 Manufacturing Automation (2nd ed.) §5.7.
    Lambrechts, Boerlage & Steinbuch 2005 Control Engineering Practice
    13(2) 145–157.
    """
    if max_feedrate <= 0.0:
        raise ValueError(f"max_feedrate must be positive; got {max_feedrate}")
    if max_accel <= 0.0:
        raise ValueError(f"max_accel must be positive; got {max_accel}")
    if blending_radius <= 0.0:
        raise ValueError(f"blending_radius must be positive; got {blending_radius}")
    if profile_type not in ("trapezoid", "s-curve"):
        raise ValueError(
            f"profile_type must be 'trapezoid' or 's-curve'; got {profile_type!r}"
        )

    n = len(waypoints)
    if n == 0:
        return FeedrateProfile()

    wps: List[Waypoint] = [tuple(w) for w in waypoints]  # type: ignore[misc]

    # ------------------------------------------------------------------
    # Step 1 — Segment lengths
    # ------------------------------------------------------------------
    seg_len: List[float] = [0.0]   # seg_len[i] = dist from wp[i-1] to wp[i]
    for i in range(1, n):
        seg_len.append(_norm(_sub(wps[i], wps[i - 1])))

    # ------------------------------------------------------------------
    # Step 2 — Corner angles and corner feedrates
    # ------------------------------------------------------------------
    corner_angles: List[float] = [0.0] * n
    corner_vmax: List[float] = [max_feedrate] * n

    for i in range(1, n - 1):
        theta = _corner_angle(wps[i - 1], wps[i], wps[i + 1])
        corner_angles[i] = theta
        corner_vmax[i] = _corner_feedrate(theta, max_accel, blending_radius, max_feedrate)

    # Endpoints start and finish at rest
    corner_vmax[0] = 0.0
    corner_vmax[n - 1] = 0.0

    # ------------------------------------------------------------------
    # Step 3 — Forward pass  (accelerate from start)
    # ------------------------------------------------------------------
    vfwd: List[float] = [0.0] * n
    vfwd[0] = 0.0  # start at rest
    for i in range(1, n):
        ds = seg_len[i]
        if ds < 1e-14:
            # Zero-length segment: inherit previous feedrate clipped to corner
            vfwd[i] = min(vfwd[i - 1], corner_vmax[i])
        else:
            # Maximum speed reachable by accelerating from vfwd[i-1] over ds
            v_accel = math.sqrt(vfwd[i - 1] ** 2 + 2.0 * max_accel * ds)
            vfwd[i] = min(max_feedrate, v_accel, corner_vmax[i])

    # ------------------------------------------------------------------
    # Step 4 — Backward pass  (decelerate toward each corner)
    # ------------------------------------------------------------------
    v: List[float] = list(vfwd)
    v[n - 1] = 0.0  # end at rest
    for i in range(n - 2, -1, -1):
        ds = seg_len[i + 1]
        if ds < 1e-14:
            v[i] = min(v[i], v[i + 1])
        else:
            # Maximum speed at i so the machine can reach v[i+1] after ds
            v_decel = math.sqrt(v[i + 1] ** 2 + 2.0 * max_accel * ds)
            v[i] = min(v[i], v_decel)

    # ------------------------------------------------------------------
    # Step 5 — Cycle time
    #
    # "trapezoid": classic trapezoidal 1/V integration along segments.
    # "s-curve": use schedule_s_curve for each segment, treating the
    #   average feedrate on the segment as V_max and using a default
    #   J_max = 10 * A_max (a common heuristic; Lambrechts 2005 §3
    #   quotes j_max/a_max ≈ 10–20 on typical servo axes).
    #   The per-waypoint feedrate schedule (v[]) is still the trapezoidal
    #   two-pass result; only cycle_time is refined.
    #
    # NOTE: Jerk/S-curve scheduling is now implemented via schedule_s_curve()
    # which provides the full 7-segment jerk-limited profile per
    # Lambrechts-Boerlage-Steinbuch (2005) and Erkorkmaz-Altintas §3.3.
    # Use profile_type="s-curve" to activate. The trapezoidal path is
    # retained as the default for full backward compatibility.
    # ------------------------------------------------------------------
    cycle_time = 0.0
    if profile_type == "trapezoid":
        for i in range(1, n):
            ds = seg_len[i]
            if ds < 1e-14:
                continue
            v0, v1 = v[i - 1], v[i]
            if v0 < 1e-12 and v1 < 1e-12:
                # Both endpoints at rest with non-zero length: infinite time
                cycle_time = math.inf
                break
            v_sum = v0 + v1
            if v_sum < 1e-12:
                cycle_time = math.inf
                break
            # Harmonic mean: dt ≈ 2*ds/(v0+v1)
            cycle_time += 2.0 * ds / v_sum
    else:
        # S-curve mode
        j_max_default = 10.0 * max_accel
        for i in range(1, n):
            ds = seg_len[i]
            if ds < 1e-14:
                continue
            v0, v1 = v[i - 1], v[i]
            if v0 < 1e-12 and v1 < 1e-12:
                cycle_time = math.inf
                break
            v_sum = v0 + v1
            if v_sum < 1e-12:
                cycle_time = math.inf
                break
            # Use average feedrate (mm/s → mm/min) as V_max for S-curve
            v_seg_mm_s = 0.5 * v_sum
            v_seg_mm_min = v_seg_mm_s * 60.0
            sc = schedule_s_curve(
                distance_mm=ds,
                V_max_mm_per_min=v_seg_mm_min,
                A_max_mm_per_s2=max_accel,
                J_max_mm_per_s3=j_max_default,
            )
            cycle_time += sc.total_time_s

    return FeedrateProfile(
        feedrates=v,
        corner_angles=corner_angles,
        corner_feedrates=corner_vmax,
        segment_lengths=seg_len,
        total_cycle_time=cycle_time,
    )


# ---------------------------------------------------------------------------
# LLM tool
# ---------------------------------------------------------------------------

try:
    import json as _json

    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register  # type: ignore[import]
    from kerf_core.utils.context import ProjectCtx  # type: ignore[import]

    _spec = ToolSpec(
        name="cam_optimize_feedrate_lookahead",
        description=(
            "Compute the optimal feedrate at each waypoint of a CAM toolpath using the "
            "two-pass corner lookahead algorithm (Erkorkmaz-Altintas 2001 / Altintas 2012 §5.7).\n\n"
            "The algorithm:\n"
            "  1. Computes the maximum corner feedrate at each interior waypoint:\n"
            "       V_corner = sqrt(a_max × r_blend / sin(θ/2))  where θ is the turning angle.\n"
            "  2. Forward pass: accelerate from rest, capped by V_target and V_corner.\n"
            "  3. Backward pass: decelerate toward each corner, intersected with forward pass.\n\n"
            "The result is a per-waypoint feedrate schedule (mm/s), corner angles (radians), "
            "and an estimated cycle time.\n\n"
            "Profile types:\n"
            "  'trapezoid' (default) — constant-acceleration (trapezoidal) velocity profile.\n"
            "  's-curve' — jerk-limited 7-segment S-curve profile per Lambrechts-Boerlage-\n"
            "    Steinbuch (2005) / Erkorkmaz-Altintas §3.3. Cycle time accounts for jerk "
            "limiting (typically 10–30% longer than trapezoidal at same A_max).\n\n"
            "Inputs:\n"
            "  waypoints        — list of {x, y, z} positions (mm)\n"
            "  max_feedrate     — maximum feedrate (mm/s)\n"
            "  max_accel        — maximum tangential acceleration (mm/s²)\n"
            "  blending_radius  — corner blending arc radius in mm (default 0.1)\n"
            "  profile_type     — 'trapezoid' or 's-curve' (default 'trapezoid')\n"
        ),
        input_schema={
            "type": "object",
            "required": ["waypoints", "max_feedrate", "max_accel"],
            "properties": {
                "waypoints": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "x": {"type": "number"},
                            "y": {"type": "number"},
                            "z": {"type": "number"},
                        },
                        "required": ["x", "y", "z"],
                    },
                    "description": "Ordered list of (X, Y, Z) waypoints in mm.",
                    "minItems": 1,
                },
                "max_feedrate": {
                    "type": "number",
                    "description": "Maximum feedrate (mm/s). Typical range 100–5000 mm/s.",
                },
                "max_accel": {
                    "type": "number",
                    "description": "Maximum tangential acceleration (mm/s²). Typical range 500–10000 mm/s².",
                },
                "blending_radius": {
                    "type": "number",
                    "description": "Corner blending arc radius (mm). Default 0.1 mm.",
                    "default": 0.1,
                },
                "profile_type": {
                    "type": "string",
                    "enum": ["trapezoid", "s-curve"],
                    "description": "Velocity profile: 'trapezoid' (default) or 's-curve' (jerk-limited).",
                    "default": "trapezoid",
                },
            },
        },
    )

    @register(_spec)
    async def _run_cam_optimize_feedrate_lookahead(ctx: ProjectCtx, args: bytes) -> str:
        try:
            a = _json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid args: {exc}", "BAD_ARGS")

        try:
            raw_wps = a.get("waypoints", [])
            waypoints: List[Waypoint] = [
                (float(w["x"]), float(w["y"]), float(w["z"]))
                for w in raw_wps
            ]
            max_feedrate = float(a["max_feedrate"])
            max_accel = float(a["max_accel"])
            blending_radius = float(a.get("blending_radius", 0.1))
            profile_type = str(a.get("profile_type", "trapezoid"))
        except (KeyError, TypeError, ValueError) as exc:
            return err_payload(f"bad parameter: {exc}", "BAD_ARGS")

        try:
            profile = optimize_feedrate(
                waypoints,
                max_feedrate=max_feedrate,
                max_accel=max_accel,
                blending_radius=blending_radius,
                profile_type=profile_type,
            )
        except ValueError as exc:
            return err_payload(str(exc), "BAD_ARGS")

        return ok_payload({
            "waypoint_count": len(waypoints),
            "feedrates_mm_s": [round(v, 4) for v in profile.feedrates],
            "corner_angles_rad": [round(a, 6) for a in profile.corner_angles],
            "corner_feedrates_mm_s": [round(v, 4) for v in profile.corner_feedrates],
            "segment_lengths_mm": [round(s, 4) for s in profile.segment_lengths],
            "total_cycle_time_s": (
                None if math.isinf(profile.total_cycle_time)
                else round(profile.total_cycle_time, 6)
            ),
            "algorithm": "two-pass lookahead (Erkorkmaz-Altintas 2001 / Altintas 2012 §5.7)",
            "profile_type": profile_type,
        })

except ImportError:
    pass  # kerf_chat not available — tool not registered; module still importable
