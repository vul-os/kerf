"""
trim_validation.py
==================
Side-selection heuristic and validation contract for trim-by-curve
geometry (NURBS Phase 4 Capability 2e).

This module provides:

  1. ``select_side`` — deterministic side-selection given
     (face, trim_loop, target_point). Returns::

       {
           "side": "inside" | "outside",
           "validated": True,
           "residual": float,
       }

     where ``residual`` is the 3-D foot-point distance from the target
     to its nearest UV projection on the surface (a proxy for how
     confidently the point was placed).  Raises :class:`AmbiguousPoint`
     when the target falls on the trim loop within ``tol``.

  2. ``validate_body_post_trim`` — run :func:`brep.validate_body` on a
     :class:`Body` that has just been trimmed and return a structured
     report.  Checks:

       * ``validate_body`` passes (Euler-Poincare + loop closure + ...),
       * no dangling edges (edges with fewer than 2 coedges in a closed
         shell),
       * residual (max vertex-position deviation from expected) ≤ tol.

  Pure-Python; no OCCT, no JS, no database.

Side-selection algorithm
------------------------
Given a surface ``S``, a UV-space trim loop ``L`` (a :class:`TrimCurve`
or a list of UV samples), and a target 3-D point ``P``:

  1. Project ``P`` onto ``S`` via the same Newton / inversion path as
     :mod:`trim_curve` → get ``(u_p, v_p)`` and the foot-point
     distance ``residual``.
  2. If ``residual`` is within the UV-loop's boundary tolerance the
     point is *on* the loop → raise :class:`AmbiguousPoint`.
  3. Classify ``(u_p, v_p)`` against the UV loop polygon with
     :func:`trim_curve.split_face_uv` (even-odd ray test).  The
     ray test returns ``'positive'`` (winding count is odd → point is
     inside the enclosed region) or ``'negative'`` (outside).
  4. Map ``positive`` → ``"inside"``, ``negative`` → ``"outside"``.

The mapping is intentionally consistent with the ``keep_side`` contract
in :func:`trim_curve.trim_face` so that a caller who receives
``side='inside'`` can directly pass ``keep_side='positive'`` to
:func:`trim_curve.trim_face`.

Public API
----------
select_side(face_or_surface, trim_loop, target_point, *, tol=1e-6,
            loop_is_closed=True) -> dict
    Classify which side of the trim loop a 3-D target point falls on.

validate_body_post_trim(body, *, tol=1e-6) -> dict
    Post-trim body validation returning
    ``{"ok": bool, "errors": [...], "residual": float}``.

AmbiguousPoint(ValueError)
    Raised when ``target_point`` is within ``tol`` of the trim loop.
"""

from __future__ import annotations

import math
from typing import List, Optional, Sequence, Tuple, Union

import numpy as np

from kerf_cad_core.geom.nurbs import NurbsSurface
from kerf_cad_core.geom.trim_curve import (
    TrimCurve,
    _project_point_to_uv,
    _uv_domain,
    project_curve_to_uv,
    split_face_uv,
)

# Import brep pieces lazily to avoid circular import at module level.
# ``_brep_validate`` is set once on first use.
_brep_validate = None


def _get_validate_body():
    global _brep_validate
    if _brep_validate is None:
        from kerf_cad_core.geom.brep import validate_body  # type: ignore[import]
        _brep_validate = validate_body
    return _brep_validate


__all__ = [
    "AmbiguousPoint",
    "select_side",
    "validate_body_post_trim",
]


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class AmbiguousPoint(ValueError):
    """Raised when a target point lies on (within tol of) the trim loop.

    Attributes
    ----------
    residual : float
        The 3-D foot-point distance from the target to its nearest
        projection on the surface.
    uv : tuple[float, float] | None
        The UV parameter of the closest foot point, if available.
    """

    def __init__(
        self,
        message: str,
        residual: float = 0.0,
        uv: Optional[Tuple[float, float]] = None,
    ) -> None:
        super().__init__(message)
        self.residual = residual
        self.uv = uv


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _surface_from_face_or_surface(face_or_surface) -> object:
    """Extract the underlying surface from a Face or return it directly."""
    # Accept a brep.Face or a NurbsSurface / analytic surface
    if hasattr(face_or_surface, "surface"):
        return face_or_surface.surface
    return face_or_surface


def _uv_samples_from_trim_loop(
    trim_loop: Union[TrimCurve, List[Tuple[float, float]]],
) -> List[Tuple[float, float]]:
    """Return a plain list of (u, v) pairs from a TrimCurve or UV list."""
    if isinstance(trim_loop, TrimCurve):
        return list(trim_loop.uv_samples)
    return list(trim_loop)


def _loop_boundary_tol(
    uv_samples: List[Tuple[float, float]],
    tol: float,
) -> float:
    """Return the UV-space tolerance to use for on-loop proximity.

    We use the larger of ``tol`` and 5% of the mean segment length so
    that a small closed loop does not have an unrealistically tight
    on-loop band.
    """
    if len(uv_samples) < 2:
        return tol
    segs = [
        math.hypot(uv_samples[i + 1][0] - uv_samples[i][0],
                   uv_samples[i + 1][1] - uv_samples[i][1])
        for i in range(len(uv_samples) - 1)
    ]
    mean_seg = sum(segs) / len(segs)
    return max(tol, 0.05 * mean_seg)


def _min_uv_dist_to_loop(
    uv: Tuple[float, float],
    uv_samples: List[Tuple[float, float]],
    *,
    closed: bool = True,
) -> float:
    """Minimum UV-space distance from ``uv`` to the trim loop polyline."""
    if not uv_samples:
        return float("inf")
    qu, qv = uv
    min_dist = float("inf")
    n = len(uv_samples)
    segments = list(range(n - 1))
    if closed and n >= 2:
        segments = list(range(n))  # include wrap-around segment

    for i in segments:
        u0, v0 = uv_samples[i % n]
        u1, v1 = uv_samples[(i + 1) % n]
        du, dv = u1 - u0, v1 - v0
        seg_len_sq = du * du + dv * dv
        if seg_len_sq < 1e-30:
            d = math.hypot(qu - u0, qv - v0)
        else:
            t = ((qu - u0) * du + (qv - v0) * dv) / seg_len_sq
            t = max(0.0, min(1.0, t))
            d = math.hypot(qu - (u0 + t * du), qv - (v0 + t * dv))
        if d < min_dist:
            min_dist = d
    return min_dist


def _project_to_nurbs_uv(
    surface: NurbsSurface,
    point_3d: np.ndarray,
    *,
    tol: float = 1e-6,
) -> Tuple[Tuple[float, float], float]:
    """Project a 3-D point onto a NurbsSurface; return ``((u, v), residual)``.

    ``residual`` is the 3-D Euclidean distance from ``point_3d`` to the
    foot point on the surface.  Returns ``(None, inf)`` when the projection
    fails.
    """
    u_min, u_max, v_min, v_max = _uv_domain(surface)
    u_init = (u_min + u_max) * 0.5
    v_init = (v_min + v_max) * 0.5
    uv = _project_point_to_uv(surface, point_3d, u_init, v_init, tol=tol)
    if uv is None:
        return None, float("inf")
    from kerf_cad_core.geom.nurbs import surface_evaluate  # type: ignore[import]
    foot = surface_evaluate(surface, uv[0], uv[1])[:3]
    residual = float(np.linalg.norm(np.asarray(point_3d, dtype=float)[:3] - foot))
    return uv, residual


def _project_to_analytic_uv(
    surface,
    point_3d: np.ndarray,
    *,
    tol: float = 1e-6,
) -> Tuple[Optional[Tuple[float, float]], float]:
    """Project ``point_3d`` onto an analytic surface (Plane, CylinderSurface, etc.)
    by sampling the surface as a light NurbsSurface approximation.

    Falls back to a simple point-in-plane projection for Plane surfaces,
    and to angle+height inversion for CylinderSurface.  Any other surface
    type that exposes ``evaluate(u, v)`` is handled via brute-force grid
    search.
    """
    p = np.asarray(point_3d, dtype=float)

    # --- Plane ---
    try:
        from kerf_cad_core.geom.brep import Plane  # type: ignore[import]
        if isinstance(surface, Plane):
            # u = (p - origin) . x_axis,  v = (p - origin) . y_axis
            d = p - surface.origin
            u = float(np.dot(d, surface.x_axis))
            v = float(np.dot(d, surface.y_axis))
            foot = surface.evaluate(u, v)[:3]
            residual = float(np.linalg.norm(p - foot))
            return (u, v), residual
    except ImportError:
        pass

    # --- CylinderSurface ---
    try:
        from kerf_cad_core.geom.brep import CylinderSurface  # type: ignore[import]
        if isinstance(surface, CylinderSurface):
            c = surface.center
            ax = surface.axis
            xref = surface.x_ref
            yref = surface._y
            # v = height along axis
            d = p - c
            v = float(np.dot(d, ax))
            # radial component
            radial = d - v * ax
            # angle u: project radial onto (xref, yref)
            rx = float(np.dot(radial, xref))
            ry = float(np.dot(radial, yref))
            u = math.atan2(ry, rx)  # in [-pi, pi]
            foot = surface.evaluate(u, v)
            residual = float(np.linalg.norm(p - foot[:3]))
            return (u, v), residual
    except ImportError:
        pass

    # --- Generic: brute-force grid (N×N) ---
    N = 32
    us = np.linspace(0.0, 1.0, N)
    vs = np.linspace(0.0, 1.0, N)
    best_uv = (0.5, 0.5)
    best_dist = float("inf")
    for ui in us:
        for vi in vs:
            try:
                q = np.asarray(surface.evaluate(float(ui), float(vi)), dtype=float)[:3]
                d = float(np.linalg.norm(p - q))
                if d < best_dist:
                    best_dist = d
                    best_uv = (float(ui), float(vi))
            except Exception:
                continue
    return best_uv, best_dist


# ---------------------------------------------------------------------------
# Public: select_side
# ---------------------------------------------------------------------------


def select_side(
    face_or_surface,
    trim_loop: Union[TrimCurve, List[Tuple[float, float]]],
    target_point,
    *,
    tol: float = 1e-6,
    loop_is_closed: bool = True,
) -> dict:
    """Classify which side of the trim loop a 3-D point falls on.

    Parameters
    ----------
    face_or_surface : Face | NurbsSurface | analytic surface
        The face (or bare surface) whose UV domain is used for
        classification.  When a :class:`brep.Face` is supplied its
        ``.surface`` attribute is used.
    trim_loop : TrimCurve | list of (u, v)
        The UV-space trim loop.  A :class:`TrimCurve` from
        :mod:`trim_curve` or a plain list of ``(u, v)`` pairs.
    target_point : array-like, shape (3,)
        The 3-D world-space point to classify.
    tol : float
        Projection convergence tolerance.  Also used as the on-loop
        proximity threshold (scaled by loop mean segment length — see
        :func:`_loop_boundary_tol`).
    loop_is_closed : bool
        Whether to treat the trim loop as a closed polygon when running
        the even-odd test (default ``True``).

    Returns
    -------
    dict with keys:
        side      : "inside" | "outside"
        validated : True
        residual  : float  — 3-D foot-point distance (quality indicator)

    Raises
    ------
    AmbiguousPoint
        When ``target_point`` projects to a UV point that is within the
        on-loop tolerance of the trim loop boundary.
    TypeError
        When ``face_or_surface`` is not a recognised surface type.
    ValueError
        When ``trim_loop`` contains fewer than 2 UV samples, or
        ``target_point`` cannot be projected onto the surface.
    """
    surface = _surface_from_face_or_surface(face_or_surface)
    uv_samples = _uv_samples_from_trim_loop(trim_loop)
    pt = np.asarray(target_point, dtype=float)
    if pt.ndim == 0 or pt.size < 3:
        raise ValueError(
            f"target_point must be a 3-D array-like; got shape {pt.shape}"
        )
    pt = pt[:3]

    if len(uv_samples) < 2:
        raise ValueError(
            "trim_loop must contain at least 2 UV samples for side classification"
        )

    # --- Project target_point onto the surface ---
    if isinstance(surface, NurbsSurface):
        uv_result, residual = _project_to_nurbs_uv(surface, pt, tol=tol)
    else:
        uv_result, residual = _project_to_analytic_uv(surface, pt, tol=tol)

    if uv_result is None:
        raise ValueError(
            f"target_point {pt.tolist()} could not be projected onto the surface "
            f"(residual=inf).  The point may lie entirely off the surface."
        )

    u_p, v_p = uv_result

    # --- On-loop proximity check ---
    loop_tol = _loop_boundary_tol(uv_samples, tol)
    uv_dist = _min_uv_dist_to_loop((u_p, v_p), uv_samples, closed=loop_is_closed)
    if uv_dist <= loop_tol:
        raise AmbiguousPoint(
            f"target_point {pt.tolist()} projects to UV ({u_p:.6g}, {v_p:.6g}) "
            f"which is within the trim loop boundary tolerance "
            f"(uv_dist={uv_dist:.3e} <= loop_tol={loop_tol:.3e})",
            residual=residual,
            uv=(u_p, v_p),
        )

    # --- Even-odd ray-casting test ---
    raw_side = split_face_uv(uv_samples, (u_p, v_p), closed_loop=loop_is_closed)
    # "positive" (odd crossings) = inside the enclosed region
    # "negative" (even crossings) = outside
    side = "inside" if raw_side == "positive" else "outside"

    return {
        "side": side,
        "validated": True,
        "residual": residual,
    }


# ---------------------------------------------------------------------------
# Public: validate_body_post_trim
# ---------------------------------------------------------------------------


def validate_body_post_trim(body, *, tol: float = 1e-6) -> dict:
    """Run structural validation on a post-trim :class:`Body`.

    This wraps :func:`brep.validate_body` and adds two extra checks:

    1. **No orphan edges** — in every closed shell every edge must be
       used by exactly 2 coedges of opposite orientation.  (This is
       already in ``validate_body``'s 2-manifold check; we re-surface it
       as a named check so callers can distinguish the failure cause.)

    2. **Residual ≤ tol** — the maximum vertex-position deviation
       computed as the max gap across all loop-closure coedge pairs.
       This mirrors the ``validate_body`` loop-closure check but surfaces
       the numeric residual.

    Parameters
    ----------
    body : Body
        The trimmed body to validate.
    tol : float
        Tolerance for the residual check (default 1e-6).

    Returns
    -------
    dict with keys:
        ok       : bool
        errors   : list[str]
        residual : float  — max coedge-gap across all loops
    """
    validate_body_fn = _get_validate_body()

    errors: List[str] = []
    residual: float = 0.0

    # --- Primary validate_body ---
    primary = validate_body_fn(body)
    if not primary["ok"]:
        errors.extend(primary.get("errors", []))

    # --- Residual: max coedge gap across all loops ---
    try:
        for lp in body.all_loops():
            n = len(lp.coedges)
            if n == 0:
                continue
            for i, ce in enumerate(lp.coedges):
                nxt = lp.coedges[(i + 1) % n]
                try:
                    gap = float(
                        np.linalg.norm(ce.end_point() - nxt.start_point())
                    )
                    if gap > residual:
                        residual = gap
                except Exception:
                    continue
    except Exception as exc:
        errors.append(f"residual computation failed: {exc}")

    # --- Residual threshold check ---
    if residual > tol:
        errors.append(
            f"post-trim residual {residual:.3e} exceeds tolerance {tol:.3e}"
        )

    # --- Orphan edge check (re-surfaced for clarity) ---
    try:
        for sh in body.all_shells():
            if not sh.is_closed:
                continue
            for edge in sh.edges():
                n_coedges = len(edge.coedges)
                if n_coedges == 0:
                    errors.append(
                        f"orphan edge Edge#{edge.id}: no coedges in closed shell"
                    )
                elif n_coedges == 1:
                    errors.append(
                        f"orphan edge Edge#{edge.id}: only 1 coedge in closed shell "
                        f"(expected 2)"
                    )
    except Exception as exc:
        errors.append(f"orphan-edge check failed: {exc}")

    ok = len(errors) == 0
    return {"ok": ok, "errors": errors, "residual": residual}
