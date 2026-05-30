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

Honest limitations
------------------
* **Jerk not modelled.** Industrial CNC uses S-curve (constant-jerk / quintic)
  velocity profiles to limit snap and reduce machine vibration.  This module
  models only constant-acceleration (trapezoidal) transitions.  The resulting
  feedrates are conservative (never violate a_max) but will slightly
  over-estimate achievable throughput and produce residual vibration at corners
  on real hardware.  For jerk-limited scheduling see Erkorkmaz-Altintas 2001
  Part I §3 (quintic spline) or NURBS interpolation (Altintas 2012 §5.8).
* **2D blending arc.** The V_corner formula assumes a constant-radius arc
  tangent to both incoming and outgoing directions in the local plane.  For
  full 5-axis paths the normal acceleration model becomes more complex (axis
  inertia coupling); this implementation treats the path as a scalar
  arc-length problem.
* **Degenerate segments** (zero-length) are skipped: the feedrate at one
  endpoint is inherited from the previous constraint.

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
# Public API
# ---------------------------------------------------------------------------

def optimize_feedrate(
    waypoints: Sequence[Waypoint],
    max_feedrate: float,
    max_accel: float,
    blending_radius: float = 0.1,
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
    """
    if max_feedrate <= 0.0:
        raise ValueError(f"max_feedrate must be positive; got {max_feedrate}")
    if max_accel <= 0.0:
        raise ValueError(f"max_accel must be positive; got {max_accel}")
    if blending_radius <= 0.0:
        raise ValueError(f"blending_radius must be positive; got {blending_radius}")

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
    # Step 5 — Cycle time  (trapezoidal 1/V integration along segments)
    # ------------------------------------------------------------------
    cycle_time = 0.0
    for i in range(1, n):
        ds = seg_len[i]
        if ds < 1e-14:
            continue
        v0, v1 = v[i - 1], v[i]
        if v0 < 1e-12 and v1 < 1e-12:
            # Both endpoints at rest with non-zero length: infinite time
            # (degenerate path; happens only if max_feedrate → 0 somehow)
            cycle_time = math.inf
            break
        if v0 < 1e-12 or v1 < 1e-12:
            # One endpoint at rest: approximate with a_max ramp
            # time = 2 * ds / (v0 + v1 + eps) or use kinematic formula
            v_sum = v0 + v1
            if v_sum < 1e-12:
                cycle_time = math.inf
                break
            # For a simple linear ramp dt = 2*ds/(v0+v1)
            cycle_time += 2.0 * ds / v_sum
        else:
            # Harmonic mean: dt ≈ ds / ((v0+v1)/2) = 2*ds/(v0+v1)
            cycle_time += 2.0 * ds / (v0 + v1)

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
            "Honest limitation: only tangential acceleration is modelled (trapezoidal velocity "
            "profile). Jerk / S-curve scheduling is not implemented; production CNC controllers "
            "apply jerk limits on top of this schedule.\n\n"
            "Inputs:\n"
            "  waypoints        — list of {x, y, z} positions (mm)\n"
            "  max_feedrate     — maximum feedrate (mm/s)\n"
            "  max_accel        — maximum tangential acceleration (mm/s²)\n"
            "  blending_radius  — corner blending arc radius in mm (default 0.1)\n"
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
        except (KeyError, TypeError, ValueError) as exc:
            return err_payload(f"bad parameter: {exc}", "BAD_ARGS")

        try:
            profile = optimize_feedrate(
                waypoints,
                max_feedrate=max_feedrate,
                max_accel=max_accel,
                blending_radius=blending_radius,
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
            "caveat": (
                "Trapezoidal velocity profile only — jerk not modelled. "
                "Production CNC applies S-curve jerk limiting on top of this schedule."
            ),
        })

except ImportError:
    pass  # kerf_chat not available — tool not registered; module still importable
