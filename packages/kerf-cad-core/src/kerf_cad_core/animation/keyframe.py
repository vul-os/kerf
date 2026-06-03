"""
kerf_cad_core.animation.keyframe — Keyframe / FCurve animation system.

Covers max3ds animation, Blender FCurve, and max3ds skeletal dynamics keyframing.

Interpolation methods
---------------------
  step    — hold previous keyframe value until next key (no interpolation)
  linear  — linear interpolation between consecutive keyframes
  bezier  — cubic Bezier interpolation using per-key tangents
              (McLaughlin 2001, "Game Programming Gems" Ch. 4.3)

Bezier evaluation
-----------------
Each Bezier segment is defined by four control points:
    P0 = (t0, v0),  P1 = (t0 + tan_out[0], v0 + tan_out[1])
    P2 = (t1 + tan_in[0],  v1 + tan_in[1]),  P3 = (t1, v1)
where tan_out / tan_in are (dx, dy) tangent offsets.
We solve for the parameter u ∈ [0,1] such that B_x(u) = t, then read B_y(u).
Newton-Raphson is used for the root-finding step (converges in ~4 iterations).

References
----------
McLaughlin, R. (2001). "Keyframe Animation" in DeLoura, M. (ed.)
    Game Programming Gems, Ch. 4.3. Charles River Media.
Blender Foundation. FCurve documentation.
    https://docs.blender.org/api/current/bpy.types.FCurve.html
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Union
import math

import numpy as np


@dataclass
class Keyframe:
    """A single keyframe sample on a function curve.

    Attributes
    ----------
    t : float
        Time in seconds.
    value : float or np.ndarray
        Scalar value or vector value (e.g. (3,) position).
    interpolation : str
        One of 'step', 'linear', 'bezier'.
    tangent_in : tuple[float, float] | None
        (dx, dy) handle offset from this key for bezier arrival. dx < 0.
    tangent_out : tuple[float, float] | None
        (dx, dy) handle offset from this key for bezier departure. dx > 0.
    """
    t: float
    value: Union[float, np.ndarray]
    interpolation: str = "bezier"
    tangent_in: "tuple[float, float] | None" = None
    tangent_out: "tuple[float, float] | None" = None


def _is_array(v) -> bool:
    return isinstance(v, np.ndarray)


def _lerp(a, b, u: float):
    """Linear interpolation between a and b at parameter u ∈ [0,1]."""
    if _is_array(a) or _is_array(b):
        a = np.asarray(a, dtype=float)
        b = np.asarray(b, dtype=float)
    return a + u * (b - a)


def _bezier_solve_t(t0: float, t1: float, t: float,
                    p1x: float, p2x: float,
                    max_iter: int = 20, tol: float = 1e-8) -> float:
    """Solve cubic Bezier B_x(u) = t for parameter u ∈ [0,1].

    Bezier x-component: B_x(u) = (1-u)^3*t0 + 3*(1-u)^2*u*p1x + 3*(1-u)*u^2*p2x + u^3*t1

    Uses Newton-Raphson.  Falls back to bisection if derivative ≈ 0.
    (McLaughlin 2001, §4.3.)
    """
    # Normalise to [0, 1] time span
    dt = t1 - t0
    if dt <= 0:
        return 0.0
    # x control points in normalised space [0,1]
    bx1 = (p1x - t0) / dt
    bx2 = (p2x - t0) / dt
    s = (t - t0) / dt   # target in normalised space

    # Clamp for safety
    s = max(0.0, min(1.0, s))

    def bx(u):
        om = 1.0 - u
        return 3.0 * om * om * u * bx1 + 3.0 * om * u * u * bx2 + u * u * u

    def dbx(u):
        om = 1.0 - u
        return (3.0 * om * (om - 2.0 * u) * bx1
                + 3.0 * u * (2.0 * om - u) * bx2
                + 3.0 * u * u)

    u = s  # initial guess
    for _ in range(max_iter):
        fx = bx(u) - s
        if abs(fx) < tol:
            break
        d = dbx(u)
        if abs(d) < 1e-12:
            # Bisection fallback
            lo, hi = 0.0, 1.0
            for __ in range(32):
                mid = 0.5 * (lo + hi)
                if bx(mid) < s:
                    lo = mid
                else:
                    hi = mid
            u = 0.5 * (lo + hi)
            break
        u = u - fx / d
        u = max(0.0, min(1.0, u))
    return u


def _eval_bezier_scalar(k0: Keyframe, k1: Keyframe, t: float) -> float:
    """Evaluate scalar bezier segment from k0 to k1 at time t.

    Control points (tangent_out of k0, tangent_in of k1):
        handle_out = (k0.t + tout[0], k0.value + tout[1])
        handle_in  = (k1.t + tin[0],  k1.value + tin[1])
    (McLaughlin 2001, §4.3.)
    """
    t0, v0 = k0.t, float(k0.value)
    t1, v1 = k1.t, float(k1.value)

    tout = k0.tangent_out if k0.tangent_out is not None else (0.0, 0.0)
    tin = k1.tangent_in if k1.tangent_in is not None else (0.0, 0.0)

    p1x = t0 + tout[0]
    p1y = v0 + tout[1]
    p2x = t1 + tin[0]
    p2y = v1 + tin[1]

    u = _bezier_solve_t(t0, t1, t, p1x, p2x)

    # Evaluate B_y(u)
    om = 1.0 - u
    by = (om ** 3 * v0
          + 3.0 * om * om * u * p1y
          + 3.0 * om * u * u * p2y
          + u ** 3 * v1)
    return by


def _eval_bezier_array(k0: Keyframe, k1: Keyframe, t: float) -> np.ndarray:
    """Evaluate per-component bezier for array-valued keyframes."""
    v0 = np.asarray(k0.value, dtype=float)
    v1 = np.asarray(k1.value, dtype=float)
    t0, t1 = k0.t, k1.t

    tout = k0.tangent_out if k0.tangent_out is not None else (0.0, 0.0)
    tin = k1.tangent_in if k1.tangent_in is not None else (0.0, 0.0)

    p1x = t0 + tout[0]
    p2x = t1 + tin[0]
    u = _bezier_solve_t(t0, t1, t, p1x, p2x)

    # Tangent y-offsets are scalar but applied uniformly across components
    p1y = v0 + tout[1]
    p2y = v1 + tin[1]

    om = 1.0 - u
    return (om ** 3 * v0
            + 3.0 * om * om * u * p1y
            + 3.0 * om * u * u * p2y
            + u ** 3 * v1)


@dataclass
class FCurve:
    """A function curve — an ordered list of keyframes evaluatable at any t.

    Attributes
    ----------
    keyframes : list[Keyframe]
        Keyframes sorted by ascending t; must have at least one entry.
    cyclic : bool
        If True, wraps t modulo the curve's [t_start, t_end] span.
        (Blender FCurve 'CYCLIC' extrapolation mode.)
    """
    keyframes: "list[Keyframe]"
    cyclic: bool = False

    def _sorted_keys(self) -> "list[Keyframe]":
        return sorted(self.keyframes, key=lambda k: k.t)

    def evaluate(self, t: float) -> "Union[float, np.ndarray]":
        """Evaluate the FCurve at time t.

        Algorithm
        ---------
        1. If cyclic, wrap t to [t_first, t_last) using modulo arithmetic.
        2. Clamp to the first/last keyframe outside the defined range.
        3. Find bracketing keyframes.
        4. Dispatch to step / linear / bezier.

        Bezier interpolation follows McLaughlin (2001) cubic Bezier solving.
        """
        keys = self._sorted_keys()
        if not keys:
            raise ValueError("FCurve has no keyframes")

        if len(keys) == 1:
            return keys[0].value

        t_start = keys[0].t
        t_end = keys[-1].t

        if self.cyclic and t_end > t_start:
            span = t_end - t_start
            t = t_start + math.fmod(t - t_start, span)
            if t < t_start:
                t += span

        # Clamp
        if t <= t_start:
            return keys[0].value
        if t >= t_end:
            return keys[-1].value

        # Binary search for bracketing pair
        lo, hi = 0, len(keys) - 1
        while hi - lo > 1:
            mid = (lo + hi) // 2
            if keys[mid].t <= t:
                lo = mid
            else:
                hi = mid

        k0, k1 = keys[lo], keys[hi]
        interp = k0.interpolation

        if interp == "step":
            return k0.value

        if interp == "linear":
            dt = k1.t - k0.t
            if dt <= 0:
                return k0.value
            u = (t - k0.t) / dt
            return _lerp(k0.value, k1.value, u)

        # bezier (default)
        if _is_array(k0.value):
            return _eval_bezier_array(k0, k1, t)
        return _eval_bezier_scalar(k0, k1, t)


@dataclass
class AnimClip:
    """An animation clip — a named collection of FCurves over a time range.

    Attributes
    ----------
    name : str
        Clip identifier (e.g. 'walk_cycle').
    duration : float
        Total duration in seconds.
    fcurves : dict[str, FCurve]
        Mapping of channel name (e.g. 'bone.head.rx') to its FCurve.
    """
    name: str
    duration: float
    fcurves: "dict[str, FCurve]"

    def evaluate(self, t: float) -> "dict[str, Union[float, np.ndarray]]":
        """Evaluate all FCurves at time t.

        Returns a dict mapping channel name → evaluated value.
        t is not clamped here; each FCurve handles clamping / wrapping.
        """
        return {ch: fc.evaluate(t) for ch, fc in self.fcurves.items()}


__all__ = [
    "Keyframe",
    "FCurve",
    "AnimClip",
]
