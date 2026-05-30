"""
seam_control.py
===============
NURBS seam-line control for closed (periodic) surfaces.

For a cylinder, sphere, or torus the periodic parameter direction has an
*arbitrary* seam — the iso-parameter line where u=0 and u=1 coincide.
Default placement (e.g. u=0 = the +x meridian) often clashes with feature
edges, texture boundaries, or mating surfaces.  This module lets the caller
slide the seam to any desired parameter position.

Theory — Piegl & Tiller §5.2 (knot-vector reparametrisation for periodic
surfaces).  For a *clamped-periodic* NURBS with knot multiplicity ``p+1`` at
the ends and simple (multiplicity 1) interior knots, the seam sits at
parameter 0 (= 1 after wrapping).  Shifting the seam by Δ is equivalent to
a cyclic rotation of the control net by the number of control points
corresponding to Δ.

For a fully periodic direction the parameterisation is uniform:
    Δ_integer = round(new_seam_parameter * n_cp)   (number of CP rows to roll)

After rolling the control-point (and weight) rows the knot vector is
regenerated as a uniform open-ended knot vector on [0, 1] that represents
the same underlying curve.

Public API
----------
detect_seam(surface) -> SeamInfo
    Identify which parameter direction is periodic and where the seam is.

shift_seam(surface, new_seam_parameter) -> NurbsSurface
    Move the seam to the given parameter position (in [0, 1]).

align_seam_to_curve(surface, curve_on_surface) -> NurbsSurface
    Project a curve onto the periodic parameter direction and pick its median
    parameter as the new seam position.

SeamInfo
    Dataclass returned by detect_seam.

Constraints
-----------
- Only works for surfaces that are *fully* periodic in one parameter
  direction (closed surfaces).
- The surface must use a uniform knot vector in the periodic direction.
- Only numpy; no OCCT dependency.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional, Sequence

import numpy as np

from kerf_cad_core.geom.nurbs import (
    NurbsCurve,
    NurbsSurface,
    surface_evaluate,
)

__all__ = [
    "SeamInfo",
    "detect_seam",
    "shift_seam",
    "align_seam_to_curve",
]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_TOL_CLOSED = 1e-8   # max distance for first/last CP to be considered coincident


def _uniform_open_knots(n: int, degree: int) -> np.ndarray:
    """Clamped uniform knot vector for n control points at the given degree.

    The knot vector is [0…0, t_1, …, t_{n-degree-1}, 1…1] with (degree+1)
    clamped knots at each end.  The (n - degree - 1) interior knots are evenly
    spaced.  This is the standard clamped B-spline knot vector.
    """
    m = n + degree + 1
    k = np.zeros(m)
    # Interior knots
    n_interior = n - degree - 1
    for i in range(n_interior):
        k[degree + 1 + i] = (i + 1) / (n_interior + 1)
    k[-(degree + 1):] = 1.0
    return k


def _is_direction_periodic(cp_slice: np.ndarray, tol: float = _TOL_CLOSED) -> bool:
    """Return True when the first and last rows in cp_slice are close enough
    to be considered a closed (periodic) seam.

    cp_slice has shape (n, ...) — rows are the control-point rows in the
    candidate periodic direction.
    """
    first = cp_slice[0].ravel()
    last  = cp_slice[-1].ravel()
    return bool(np.linalg.norm(first - last) < tol * max(1.0, np.linalg.norm(first)))


def _seam_curve_3d(surf: NurbsSurface, direction: str, seam_param: float,
                   n_samples: int = 32) -> np.ndarray:
    """Sample the seam iso-curve and return (n_samples, 3) 3-D points."""
    pts = []
    u_min = float(surf.knots_u[surf.degree_u])
    u_max = float(surf.knots_u[surf.num_control_points_u])
    v_min = float(surf.knots_v[surf.degree_v])
    v_max = float(surf.knots_v[surf.num_control_points_v])

    for i in range(n_samples):
        t = i / (n_samples - 1)
        if direction == "u":
            u = seam_param
            v = v_min + t * (v_max - v_min)
        else:
            u = u_min + t * (u_max - u_min)
            v = seam_param
        pts.append(surface_evaluate(surf, u, v))
    return np.array(pts)


# ---------------------------------------------------------------------------
# SeamInfo
# ---------------------------------------------------------------------------

@dataclass
class SeamInfo:
    """Result of ``detect_seam``.

    Attributes
    ----------
    periodic_direction : str or None
        ``'u'``, ``'v'``, or ``None`` (open surface).
    seam_parameter : float or None
        Parameter value of the seam in the periodic direction (domain [0, 1]).
        ``None`` when the surface is not periodic.
    seam_curve_3d : np.ndarray or None
        (32, 3) array of 3-D points sampled along the seam iso-curve.
        ``None`` when the surface is not periodic.
    """
    periodic_direction: Optional[str]
    seam_parameter: Optional[float]
    seam_curve_3d: Optional[np.ndarray]


# ---------------------------------------------------------------------------
# detect_seam
# ---------------------------------------------------------------------------

def detect_seam(surface: NurbsSurface) -> SeamInfo:
    """Identify which parameter direction of *surface* is periodic.

    A surface is considered periodic in a direction when its first and last
    control-point rows in that direction are coincident (within ``_TOL_CLOSED``).
    The seam of a freshly-constructed surface is always at parameter 0 (= 1
    after identification).

    For an open surface (no periodic direction) returns
    ``SeamInfo(periodic_direction=None, seam_parameter=None, seam_curve_3d=None)``.
    """
    cp = surface.control_points  # (nu, nv, 3)

    # Check u direction: close iff cp[0, :] ≈ cp[-1, :]
    # Use Frobenius norm across all v columns.
    u_span_start = float(surface.knots_u[surface.degree_u])
    u_span_end   = float(surface.knots_u[surface.num_control_points_u])
    v_span_start = float(surface.knots_v[surface.degree_v])
    v_span_end   = float(surface.knots_v[surface.num_control_points_v])

    u_closed = _is_direction_periodic(cp)          # first/last u-row close
    v_closed = _is_direction_periodic(cp.transpose(1, 0, 2))  # first/last v-row close

    if u_closed and not v_closed:
        seam_p = u_span_start
        crv = _seam_curve_3d(surface, "u", seam_p)
        return SeamInfo("u", seam_p, crv)

    if v_closed and not u_closed:
        seam_p = v_span_start
        crv = _seam_curve_3d(surface, "v", seam_p)
        return SeamInfo("v", seam_p, crv)

    if u_closed and v_closed:
        # Both directions closed (e.g. torus); report u as primary.
        seam_p = u_span_start
        crv = _seam_curve_3d(surface, "u", seam_p)
        return SeamInfo("u", seam_p, crv)

    return SeamInfo(None, None, None)


# ---------------------------------------------------------------------------
# shift_seam
# ---------------------------------------------------------------------------

def shift_seam(surface: NurbsSurface, new_seam_parameter: float) -> NurbsSurface:
    """Shift the periodic-direction seam to *new_seam_parameter*.

    Parameters
    ----------
    surface : NurbsSurface
        A NURBS surface that is periodic (closed) in its u or v direction.
        Open surfaces raise ``ValueError``.
    new_seam_parameter : float
        Desired seam parameter in [0, 1) (the normalised domain of the
        periodic direction).

    Returns
    -------
    NurbsSurface
        New surface with the same geometry but the seam at the requested
        parameter.  The non-periodic direction is unchanged.

    Raises
    ------
    ValueError
        If the surface is not periodic in any direction.
    """
    info = detect_seam(surface)
    if info.periodic_direction is None:
        raise ValueError(
            "shift_seam: surface is not closed/periodic in any direction. "
            "detect_seam returned periodic_direction=None."
        )

    t = float(new_seam_parameter) % 1.0   # wrap into [0, 1)
    direction = info.periodic_direction

    cp  = surface.control_points.copy()  # (nu, nv, dim)
    W   = surface.weights.copy() if surface.weights is not None else None
    nu, nv = cp.shape[:2]

    if direction == "u":
        # Number of unique periodic CPs in u: last row is a copy of first,
        # so there are (nu - 1) independent rows.
        n_unique = nu - 1
        # Compute shift index: how many rows to roll
        shift = int(round(t * n_unique)) % n_unique

        if shift == 0:
            # No change; return a copy.
            return NurbsSurface(
                degree_u=surface.degree_u,
                degree_v=surface.degree_v,
                control_points=cp,
                knots_u=surface.knots_u.copy(),
                knots_v=surface.knots_v.copy(),
                weights=W,
            )

        # Roll the first n_unique rows, then re-append the wrapped first row.
        cp_unique = cp[:n_unique]               # (n_unique, nv, dim)
        cp_rolled = np.roll(cp_unique, -shift, axis=0)
        # Re-close: last row = first rolled row
        cp_new = np.concatenate([cp_rolled, cp_rolled[:1]], axis=0)

        if W is not None:
            W_unique = W[:n_unique]
            W_rolled = np.roll(W_unique, -shift, axis=0)
            W_new = np.concatenate([W_rolled, W_rolled[:1]], axis=0)
        else:
            W_new = None

        # Rebuild uniform open knot vector for u direction (nu control points)
        knots_u_new = _uniform_open_knots(nu, surface.degree_u)
        return NurbsSurface(
            degree_u=surface.degree_u,
            degree_v=surface.degree_v,
            control_points=cp_new,
            knots_u=knots_u_new,
            knots_v=surface.knots_v.copy(),
            weights=W_new,
        )

    else:  # direction == "v"
        n_unique = nv - 1
        shift = int(round(t * n_unique)) % n_unique

        if shift == 0:
            return NurbsSurface(
                degree_u=surface.degree_u,
                degree_v=surface.degree_v,
                control_points=cp,
                knots_u=surface.knots_u.copy(),
                knots_v=surface.knots_v.copy(),
                weights=W,
            )

        cp_unique = cp[:, :n_unique]            # (nu, n_unique, dim)
        cp_rolled = np.roll(cp_unique, -shift, axis=1)
        cp_new = np.concatenate([cp_rolled, cp_rolled[:, :1]], axis=1)

        if W is not None:
            W_unique = W[:, :n_unique]
            W_rolled = np.roll(W_unique, -shift, axis=1)
            W_new = np.concatenate([W_rolled, W_rolled[:, :1]], axis=1)
        else:
            W_new = None

        knots_v_new = _uniform_open_knots(nv, surface.degree_v)
        return NurbsSurface(
            degree_u=surface.degree_u,
            degree_v=surface.degree_v,
            control_points=cp_new,
            knots_u=surface.knots_u.copy(),
            knots_v=knots_v_new,
            weights=W_new,
        )


# ---------------------------------------------------------------------------
# align_seam_to_curve
# ---------------------------------------------------------------------------

def align_seam_to_curve(
    surface: NurbsSurface,
    curve_on_surface: NurbsCurve,
    n_samples: int = 64,
) -> NurbsSurface:
    """Align the seam of *surface* to lie along *curve_on_surface*.

    The function projects the 3-D curve onto the periodic parameter direction
    by finding the closest surface parameter for each sampled curve point, then
    picks the **median** of those parameters as the new seam position.

    Parameters
    ----------
    surface : NurbsSurface
        A closed (periodic) NURBS surface.
    curve_on_surface : NurbsCurve
        A curve whose 3-D points lie (approximately) on *surface*.  The
        function uses point-inversion via ``closest_point_surface`` to find
        the corresponding (u, v) parameters and reads off the periodic-
        direction component.
    n_samples : int
        Number of points to sample along the curve for the median estimate.

    Returns
    -------
    NurbsSurface
        New surface with the seam aligned to the curve's parameter.

    Raises
    ------
    ValueError
        If the surface is not periodic in any direction.
    """
    from kerf_cad_core.geom.inversion import closest_point_surface

    info = detect_seam(surface)
    if info.periodic_direction is None:
        raise ValueError(
            "align_seam_to_curve: surface is not closed/periodic in any direction."
        )

    # Sample curve
    t_vals = np.linspace(0.0, 1.0, n_samples)
    params = []
    for t in t_vals:
        pt3d = curve_on_surface.evaluate(float(t))
        u_cp, v_cp, _pt, _dist = closest_point_surface(surface, pt3d)
        if info.periodic_direction == "u":
            params.append(float(u_cp))
        else:
            params.append(float(v_cp))

    # Median parameter in the periodic direction
    median_param = float(np.median(params))

    # Normalise to [0, 1]
    if info.periodic_direction == "u":
        lo = float(surface.knots_u[surface.degree_u])
        hi = float(surface.knots_u[surface.num_control_points_u])
    else:
        lo = float(surface.knots_v[surface.degree_v])
        hi = float(surface.knots_v[surface.num_control_points_v])

    span = hi - lo
    if span < 1e-15:
        raise ValueError("align_seam_to_curve: degenerate knot span in periodic direction.")
    new_seam = (median_param - lo) / span

    return shift_seam(surface, new_seam)


# ---------------------------------------------------------------------------
# LLM tool: nurbs_shift_seam
# ---------------------------------------------------------------------------

def _register_llm_tool() -> None:
    """Register the ``nurbs_shift_seam`` LLM tool if the registry is available."""
    try:
        from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register
    except ImportError:
        return

    import json

    _spec = ToolSpec(
        name="nurbs_shift_seam",
        description=(
            "Shift the periodic seam line of a closed NURBS surface to a new "
            "parameter position.  Useful for cylinders, spheres, and tori where "
            "the default u=0 seam clashes with feature edges, texture boundaries, "
            "or mating surfaces.  Returns the modified surface as serialised "
            "control-point / knot data."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "surface": {
                    "type": "object",
                    "description": (
                        "Serialised NurbsSurface: "
                        "{degree_u, degree_v, control_points (nu×nv×3), "
                        "knots_u, knots_v, weights (nu×nv, optional)}."
                    ),
                },
                "new_seam_parameter": {
                    "type": "number",
                    "description": (
                        "Target seam position in the normalised periodic "
                        "parameter domain [0, 1).  0.5 moves the seam halfway "
                        "around the closed direction."
                    ),
                },
                "detect_only": {
                    "type": "boolean",
                    "description": (
                        "If true, return SeamInfo without shifting (useful to "
                        "query which direction is periodic and where the current "
                        "seam is)."
                    ),
                },
            },
            "required": ["surface"],
        },
    )

    @register(_spec, write=False)
    async def _run_nurbs_shift_seam(ctx, args: bytes) -> str:  # noqa: F811
        try:
            a = json.loads(args)
        except Exception as e:
            return err_payload(f"invalid args JSON: {e}", "BAD_ARGS")

        sdata = a.get("surface")
        if not sdata:
            return err_payload("'surface' is required", "BAD_ARGS")

        try:
            cp = np.array(sdata["control_points"], dtype=float)
            ku = np.array(sdata["knots_u"], dtype=float)
            kv = np.array(sdata["knots_v"], dtype=float)
            du = int(sdata["degree_u"])
            dv = int(sdata["degree_v"])
            W_raw = sdata.get("weights")
            W = np.array(W_raw, dtype=float) if W_raw is not None else None
            surf = NurbsSurface(
                degree_u=du, degree_v=dv,
                control_points=cp, knots_u=ku, knots_v=kv,
                weights=W,
            )
        except Exception as e:
            return err_payload(f"cannot deserialise surface: {e}", "BAD_ARGS")

        detect_only = bool(a.get("detect_only", False))
        info = detect_seam(surf)

        if detect_only:
            return ok_payload({
                "periodic_direction": info.periodic_direction,
                "seam_parameter": info.seam_parameter,
                "seam_curve_3d": (
                    info.seam_curve_3d.tolist()
                    if info.seam_curve_3d is not None else None
                ),
            })

        t = float(a.get("new_seam_parameter", 0.0))
        try:
            new_surf = shift_seam(surf, t)
        except ValueError as e:
            return err_payload(str(e), "NOT_PERIODIC")

        return ok_payload({
            "degree_u": new_surf.degree_u,
            "degree_v": new_surf.degree_v,
            "control_points": new_surf.control_points.tolist(),
            "knots_u": new_surf.knots_u.tolist(),
            "knots_v": new_surf.knots_v.tolist(),
            "weights": (
                new_surf.weights.tolist()
                if new_surf.weights is not None else None
            ),
            "seam_info": {
                "periodic_direction": info.periodic_direction,
                "seam_parameter": info.seam_parameter,
            },
        })


_register_llm_tool()
