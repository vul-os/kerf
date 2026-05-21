"""
kerf_cad_core.geom.mold — Mould / injection-moulding geometry utilities.

GK-118: Parting-line generation
--------------------------------
The parting line is the silhouette curve of a body w.r.t. a pull direction:
the locus of points on the surface where the face normal is exactly
perpendicular to the pull direction (draft angle ≈ 0°).

In practice the body is discretised by sampling each face over a UV grid;
for each pair of adjacent UV samples whose dot-product sign with the pull
direction changes, the zero-crossing point is interpolated and collected.
The result is a list of 3-D points that approximate the parting-line
silhouette.

Only pure-Python / NumPy — no OCC runtime required (hermetic).
"""

from __future__ import annotations

import math
from typing import List, Sequence, Union

import numpy as np

# ---------------------------------------------------------------------------
# Public type alias (mirrors convention in bridge_loops / section_contour)
# ---------------------------------------------------------------------------

Point3 = List[float]

# ---------------------------------------------------------------------------
# Internal helpers (reuse draft_analysis UV-sampling machinery)
# ---------------------------------------------------------------------------

_FD_H: float = 1e-7
_GRID: int = 16   # UV sample count per axis per face (finer than GK-92's 5)


def _face_surface_domain(face: object):
    """Return (u_lo, u_hi, v_lo, v_hi) for the parametric domain of *face*."""
    srf = face.surface  # type: ignore[attr-defined]
    try:
        from kerf_cad_core.geom.brep import Plane, CylinderSurface, SphereSurface
        if isinstance(srf, Plane):
            return 0.0, 1.0, 0.0, 1.0
        elif isinstance(srf, CylinderSurface):
            return 0.0, 2.0 * math.pi, 0.0, 1.0
        elif isinstance(srf, SphereSurface):
            return 0.0, 2.0 * math.pi, -math.pi / 2.0, math.pi / 2.0
        else:
            raise TypeError
    except (TypeError, ImportError):
        return 0.0, 1.0, 0.0, 1.0


def _eval_point(srf: object, u: float, v: float) -> np.ndarray:
    """Evaluate *srf* at (u, v) and return a 3-vector."""
    return np.asarray(srf.evaluate(u, v), dtype=float)[:3]


def _outward_normal(face: object, srf: object, u: float, v: float) -> np.ndarray:
    """Return the outward unit normal of *face* at (u, v)."""
    p = _eval_point(srf, u, v)
    if hasattr(srf, "normal"):
        raw = np.asarray(srf.normal(u, v), dtype=float)[:3]
    else:
        pu = _eval_point(srf, u + _FD_H, v)
        pv = _eval_point(srf, u, v + _FD_H)
        raw = np.cross(pu - p, pv - p)

    nrm = float(np.linalg.norm(raw))
    unit_n = raw / nrm if nrm > 1e-15 else raw

    orient = getattr(face, "orientation", True)
    if not orient:
        unit_n = -unit_n
    return unit_n


def _dot_pull(face: object, srf: object, u: float, v: float,
              pull_hat: np.ndarray) -> float:
    """Signed dot-product n(u,v) · pull_hat (positive = faces pull direction)."""
    n = _outward_normal(face, srf, u, v)
    return float(np.dot(n, pull_hat))


def _lerp_pt(srf: object, u0: float, v0: float, u1: float, v1: float,
             d0: float, d1: float) -> Point3:
    """Linear interpolation along the UV edge where the sign of *d* changes."""
    if abs(d0 - d1) < 1e-30:
        t = 0.5
    else:
        t = d0 / (d0 - d1)
    t = max(0.0, min(1.0, t))
    u = u0 + t * (u1 - u0)
    v = v0 + t * (v1 - v0)
    p = _eval_point(srf, u, v)
    return [float(p[0]), float(p[1]), float(p[2])]


# ---------------------------------------------------------------------------
# GK-118: parting_line
# ---------------------------------------------------------------------------

def parting_line(
    body: object,
    pull_direction: Union[Sequence[float], np.ndarray],
    *,
    n_samples: int = _GRID,
) -> List[Point3]:
    """Parting-line generation for injection-moulding / die-casting.

    GK-118
    ------
    The parting line is the silhouette of *body* w.r.t. the demould
    *pull_direction*: the set of surface points where the outward face
    normal is perpendicular to the pull axis (draft angle ≈ 0).

    The algorithm samples each face on an ``n_samples × n_samples`` UV
    grid and, for every UV quad, finds the four edges where the sign of
    ``n · pull_hat`` changes.  Zero-crossings are linearly interpolated
    to obtain 3-D parting points.

    Parameters
    ----------
    body:
        Any ``kerf_cad_core.geom.brep.Body`` (or duck-typed object with
        ``all_faces()`` returning ``Face``-like objects that have a
        ``.surface`` attribute supporting ``.evaluate(u, v)``).
    pull_direction:
        3-vector giving the mould pull direction (need not be unit length).
    n_samples:
        UV grid resolution per axis per face.  Default 16 (higher → more
        parting points, finer silhouette approximation).

    Returns
    -------
    list[Point3]
        Unsorted list of 3-D points lying on the parting line/curve.
        For a closed convex body (sphere, cylinder …) the points will
        approximate the closed equatorial silhouette.

    Raises
    ------
    ValueError
        If *pull_direction* is a zero vector.

    Notes
    -----
    * Pure-Python / NumPy only — no OCC runtime required.
    * Reuses the per-face UV sampling and outward-normal convention from
      ``draft_analysis`` (GK-92).
    """
    pull = np.asarray(pull_direction, dtype=float).ravel()[:3]
    pull_nrm = float(np.linalg.norm(pull))
    if pull_nrm < 1e-15:
        raise ValueError("pull_direction must be a non-zero vector")
    pull_hat = pull / pull_nrm

    n = int(n_samples)
    if n < 2:
        n = 2

    parting_pts: List[Point3] = []

    for face in body.all_faces():  # type: ignore[attr-defined]
        srf = face.surface  # type: ignore[attr-defined]
        u_lo, u_hi, v_lo, v_hi = _face_surface_domain(face)

        us = np.linspace(u_lo, u_hi, n)
        vs = np.linspace(v_lo, v_hi, n)

        # Build (n x n) grid of dot-products
        dots = np.empty((n, n), dtype=float)
        for i, u in enumerate(us):
            for j, v in enumerate(vs):
                dots[i, j] = _dot_pull(face, srf, float(u), float(v), pull_hat)

        # Scan horizontal edges (fixed i, varying j)
        for i in range(n):
            for j in range(n - 1):
                d0, d1 = dots[i, j], dots[i, j + 1]
                if d0 * d1 <= 0.0 and not (d0 == 0.0 and d1 == 0.0):
                    pt = _lerp_pt(srf,
                                  float(us[i]), float(vs[j]),
                                  float(us[i]), float(vs[j + 1]),
                                  d0, d1)
                    parting_pts.append(pt)

        # Scan vertical edges (fixed j, varying i)
        for j in range(n):
            for i in range(n - 1):
                d0, d1 = dots[i, j], dots[i + 1, j]
                if d0 * d1 <= 0.0 and not (d0 == 0.0 and d1 == 0.0):
                    pt = _lerp_pt(srf,
                                  float(us[i]),     float(vs[j]),
                                  float(us[i + 1]), float(vs[j]),
                                  d0, d1)
                    parting_pts.append(pt)

    return parting_pts
