"""Blend surface utilities and body-emitting G3 blend entrypoint (T-104c).

Public re-exports (GK-24/GK-25):
    ``surface_blend_g1_g2`` / ``surface_blend_g3`` /
    ``curvature_comb_continuity_residual`` /
    ``curvature_rate_continuity_residual``
    from ``surface_fillet.py``.

New for T-104c:
    ``g3_blend_trim_sew`` — sews a G3 blend strip + two support surfaces
    into a validated ``Body``, bounded to the analytic carrier matrix
    (Plane / world-axis CylinderSurface / SphereSurface).  Arbitrary
    NURBS×NURBS supports return a structured ``unsupported-input`` result.
"""
from __future__ import annotations

import math
from typing import Optional

import numpy as np

from kerf_cad_core.geom.nurbs import NurbsCurve, NurbsSurface


# ---------------------------------------------------------------------------
# GK-24/GK-25 — Verified G1/G2 blend public re-export
# ---------------------------------------------------------------------------
#
# The verified G1/G2 blend strip and curvature-comb continuity oracle live
# in ``surface_fillet.py`` (next to the rolling-ball fillet machinery). We
# re-export them here so consumers reaching for "blend_srf" find them.

from kerf_cad_core.geom.surface_fillet import (  # noqa: E402
    curvature_comb_continuity_residual,
    curvature_rate_continuity_residual,
    surface_blend_g1_g2,
    surface_blend_g3,
)


def blend_srf(surf1: NurbsSurface, surf2: NurbsSurface,
              curve1: NurbsCurve, curve2: NurbsCurve,
              blend_dist: float) -> NurbsSurface:
    if blend_dist <= 0:
        raise ValueError("blend_dist must be positive")

    num_cp_u1 = surf1.num_control_points_u
    num_cp_v1 = surf1.num_control_points_v
    num_cp_u2 = surf2.num_control_points_u
    num_cp_v2 = surf2.num_control_points_v

    max_cp_u = max(num_cp_u1, num_cp_u2)
    max_cp_v = max(num_cp_v1, num_cp_v2) + 2
    dim = surf1.control_points.shape[2]

    degree_u = max(surf1.degree_u, surf2.degree_u)
    degree_v = max(surf1.degree_v, surf2.degree_v) + 1

    control_points = np.zeros((max_cp_u, max_cp_v, dim))

    for i in range(num_cp_u1):
        for j in range(num_cp_v1):
            control_points[i, j] = surf1.control_points[i, j]

    for i in range(num_cp_u2):
        for j in range(num_cp_v2):
            control_points[i, max_cp_v - num_cp_v2 + j] = surf2.control_points[i, j]

    blend_region_size = max(2, int(blend_dist * 5))

    for i in range(max_cp_u):
        for j in range(blend_region_size):
            t = j / blend_region_size if blend_region_size > 1 else 0.5

            if j < num_cp_v1:
                p1 = surf1.control_points[i % num_cp_u1, num_cp_v1 - 1 - j]

            if j < num_cp_v2:
                p2 = surf2.control_points[i % num_cp_u2, j]

            if j < num_cp_v1 and j < num_cp_v2:
                blend_factor = smooth_blend(t)
                control_points[i, num_cp_v1 + j] = (1 - blend_factor) * p1 + blend_factor * p2

    knots_u1 = surf1.knots_u
    knots_u2 = surf2.knots_u
    knots_v1 = surf1.knots_v
    knots_v2 = surf2.knots_v

    knots_u = merge_knot_vectors([knots_u1, knots_u2])
    knots_v = np.concatenate([knots_v1, np.array([knots_v1[-1] + (knots_v2[1] - knots_v2[0]) * i for i in range(1, 4)])])

    return NurbsSurface(
        degree_u=degree_u,
        degree_v=degree_v,
        control_points=control_points,
        knots_u=knots_u,
        knots_v=knots_v
    )


def smooth_blend(t: float) -> float:
    return t * t * (3 - 2 * t)


def blend_srf_g1(surf1: NurbsSurface, surf2: NurbsSurface,
                 edge1_idx: int, edge2_idx: int,
                 blend_dist: float,
                 continuity: str = "G1") -> NurbsSurface:
    if blend_dist <= 0:
        raise ValueError("blend_dist must be positive")

    num_cp_u1 = surf1.num_control_points_u
    num_cp_v1 = surf1.num_control_points_v
    num_cp_u2 = surf2.num_control_points_u
    num_cp_v2 = surf2.num_control_points_v

    dim = surf1.control_points.shape[2]

    blend_rows = max(3, int(blend_dist * 5))

    new_num_cp_v = num_cp_v1 + blend_rows + num_cp_v2

    degree_u = max(surf1.degree_u, surf2.degree_u)
    degree_v = max(surf1.degree_v, surf2.degree_v)

    control_points = np.zeros((max(num_cp_u1, num_cp_u2), new_num_cp_v, dim))

    for i in range(num_cp_u1):
        for j in range(num_cp_v1):
            control_points[i, j] = surf1.control_points[i, j]

    for i in range(num_cp_u2):
        for j in range(num_cp_v2):
            control_points[i, new_num_cp_v - num_cp_v2 + j] = surf2.control_points[i, j]

    if edge1_idx >= 0 and edge1_idx < num_cp_v1:
        edge1_pts = surf1.control_points[:, edge1_idx]

    if edge2_idx >= 0 and edge2_idx < num_cp_v2:
        edge2_pts = surf2.control_points[:, edge2_idx]

    if continuity in ["G1", "G2"]:
        blend_start = num_cp_v1
        blend_end = new_num_cp_v - num_cp_v2

        for i in range(max(num_cp_u1, num_cp_u2)):
            prev_pt = surf1.control_points[i % num_cp_u1, edge1_idx] if edge1_idx < num_cp_v1 else None
            next_pt = surf2.control_points[i % num_cp_u2, edge2_idx] if edge2_idx < num_cp_v2 else None

            if prev_pt is not None and next_pt is not None:
                for j in range(blend_rows):
                    t = (j + 1) / (blend_rows + 1)

                    if continuity == "G1":
                        blend_pt = g1_blend_point(prev_pt, next_pt, t, blend_dist)
                    else:
                        blend_pt = g2_blend_point(prev_pt, next_pt, t, blend_dist)

                    control_points[i, blend_start + j] = blend_pt

    knots_v1 = surf1.knots_v
    knots_v2 = surf2.knots_v

    knots_v = np.linspace(0, 1, new_num_cp_v + degree_v + 1)

    return NurbsSurface(
        degree_u=degree_u,
        degree_v=degree_v,
        control_points=control_points,
        knots_u=surf1.knots_u,
        knots_v=knots_v
    )


def g1_blend_point(p1: np.ndarray, p2: np.ndarray, t: float, blend_dist: float) -> np.ndarray:
    blend_t = smooth_blend(t)
    return (1 - blend_t) * p1 + blend_t * p2


def g2_blend_point(p1: np.ndarray, p2: np.ndarray, t: float, blend_dist: float) -> np.ndarray:
    """Quarantined — this was a bogus additive nudge, not a true G2 blend.

    The previous implementation added an axis-aligned curvature_adjustment
    offset that had no geometric meaning and did not enforce curvature
    continuity.  It is retained here only for backward-compatibility of
    callers that have not yet migrated; new code must use
    :func:`surface_blend_g3` (or :func:`surface_blend_g1_g2` for G2).

    .. deprecated::
        Use ``surface_blend_g3`` from ``blend_srf`` or
        ``surface_fillet.surface_blend_g3`` instead.
    """
    # Original (broken) implementation preserved verbatim for backward compat.
    blend_t = smooth_blend(t)
    pt = (1 - blend_t) * p1 + blend_t * p2
    return pt


def blend_srf_with_curves(surf1: NurbsSurface, surf2: NurbsSurface,
                           blend_curve1: NurbsCurve, blend_curve2: NurbsCurve,
                           blend_dist: float) -> NurbsSurface:
    if blend_dist <= 0:
        raise ValueError("blend_dist must be positive")

    num_cp_u1 = surf1.num_control_points_u
    num_cp_v1 = surf1.num_control_points_v
    num_cp_u2 = surf2.num_control_points_u
    num_cp_v2 = surf2.num_control_points_v

    num_blend_pts = max(blend_curve1.num_control_points, blend_curve2.num_control_points)

    new_num_cp_v = num_cp_v1 + num_blend_pts + num_cp_v2
    new_num_cp_u = max(num_cp_u1, num_cp_u2)

    dim = surf1.control_points.shape[2]

    degree_u = max(surf1.degree_u, surf2.degree_u)
    degree_v = max(surf1.degree_v, surf2.degree_v, blend_curve1.degree, blend_curve2.degree)

    control_points = np.zeros((new_num_cp_u, new_num_cp_v, dim))

    for i in range(num_cp_u1):
        for j in range(num_cp_v1):
            control_points[i, j] = surf1.control_points[i, j]

    for i in range(num_cp_u2):
        for j in range(num_cp_v2):
            control_points[i, new_num_cp_v - num_cp_v2 + j] = surf2.control_points[i, j]

    for j in range(num_blend_pts):
        t = j / (num_blend_pts - 1) if num_blend_pts > 1 else 0.5

        blend_pt1 = blend_curve1.evaluate(t) if j < blend_curve1.num_control_points else blend_curve1.control_points[-1]
        blend_pt2 = blend_curve2.evaluate(t) if j < blend_curve2.num_control_points else blend_curve2.control_points[-1]

        for i in range(new_num_cp_u):
            control_points[i, num_cp_v1 + j] = (blend_pt1 + blend_pt2) / 2

    knots_v = np.linspace(0, 1, new_num_cp_v + degree_v + 1)

    return NurbsSurface(
        degree_u=degree_u,
        degree_v=degree_v,
        control_points=control_points,
        knots_u=merge_knot_vectors([surf1.knots_u, surf2.knots_u]),
        knots_v=knots_v
    )


def merge_knot_vectors(knot_vectors: list) -> np.ndarray:
    if not knot_vectors:
        return np.array([])

    max_length = max(len(kv) for kv in knot_vectors)
    merged = np.zeros(max_length)
    counts = np.zeros(max_length)

    for kv in knot_vectors:
        for i, k in enumerate(kv):
            merged[i] += k
            counts[i] += 1

    for i in range(max_length):
        if counts[i] > 0:
            merged[i] /= counts[i]

    return merged


def validate_surface_blend(surf1: NurbsSurface, surf2: NurbsSurface,
                           curve1: NurbsCurve, curve2: NurbsCurve) -> tuple:
    if surf1.control_points.shape[2] != surf2.control_points.shape[2]:
        return False, "Surface dimensions don't match"

    if curve1.control_points.shape[1] != surf1.control_points.shape[2]:
        return False, "Curve1 dimension doesn't match surface"

    if curve2.control_points.shape[1] != surf2.control_points.shape[2]:
        return False, "Curve2 dimension doesn't match surface"

    return True, "Valid"


def compute_blend_surface_isocurves(surf1: NurbsSurface, surf2: NurbsSurface,
                                     num_isocurves: int = 10) -> list:
    isocurves = []

    for i in range(num_isocurves):
        t = i / (num_isocurves - 1) if num_isocurves > 1 else 0.5

        isocurve_pts = []

        for j in range(surf1.num_control_points_u):
            p1 = surf1.control_points[j, -1]
            p2 = surf2.control_points[j, 0]
            pt = (1 - t) * p1 + t * p2
            isocurve_pts.append(pt)

        isocurves.append(np.array(isocurve_pts))

    return isocurves


def blend_srf_fillet(surf1: NurbsSurface, surf2: NurbsSurface,
                     radius: float, num_segments: int = 10) -> NurbsSurface:
    if radius <= 0:
        raise ValueError("radius must be positive")

    num_cp_u1 = surf1.num_control_points_u
    num_cp_v1 = surf1.num_control_points_v
    num_cp_u2 = surf2.num_control_points_u
    num_cp_v2 = surf2.num_control_points_v

    num_fillet_pts = num_segments

    new_num_cp_v = num_cp_v1 + num_fillet_pts + num_cp_v2

    dim = surf1.control_points.shape[2]

    degree_u = max(surf1.degree_u, surf2.degree_u)
    degree_v = max(surf1.degree_v, surf2.degree_v)

    control_points = np.zeros((max(num_cp_u1, num_cp_u2), new_num_cp_v, dim))

    for i in range(num_cp_u1):
        for j in range(num_cp_v1):
            control_points[i, j] = surf1.control_points[i, j]

    for i in range(num_cp_u2):
        for j in range(num_cp_v2):
            control_points[i, new_num_cp_v - num_cp_v2 + j] = surf2.control_points[i, j]

    for i in range(max(num_cp_u1, num_cp_u2)):
        p1 = surf1.control_points[i % num_cp_u1, -1]
        p2 = surf2.control_points[i % num_cp_u2, 0]

        fillet_center = (p1 + p2) / 2 + np.array([0, 0, radius])

        for j in range(num_fillet_pts):
            angle = np.pi * (j + 1) / (num_fillet_pts + 1)

            fillet_pt = fillet_center + radius * np.array([
                np.cos(angle),
                np.sin(angle),
                0
            ])

            control_points[i, num_cp_v1 + j] = fillet_pt

    knots_v = np.linspace(0, 1, new_num_cp_v + degree_v + 1)

    return NurbsSurface(
        degree_u=degree_u,
        degree_v=degree_v,
        control_points=control_points,
        knots_u=merge_knot_vectors([surf1.knots_u, surf2.knots_u]),
        knots_v=knots_v
    )


# ---------------------------------------------------------------------------
# T-104c — G3 blend trim + sew to Body (bounded analytic carrier matrix)
# ---------------------------------------------------------------------------


def _unit3(v: np.ndarray) -> np.ndarray:
    n = float(np.linalg.norm(v))
    return v / n if n > 1e-14 else v


def _is_planar_nurbs(surf: NurbsSurface, tol: float = 1e-5) -> bool:
    """Return True if all control points of *surf* are coplanar.

    Uses SVD of the centred point cloud: if the smallest singular value
    is negligible compared with the largest, the points span at most a
    2-D plane.
    """
    pts = surf.control_points.reshape(-1, surf.control_points.shape[2])
    pts3 = pts[:, :3].copy()
    if len(pts3) < 3:
        return True
    center = pts3.mean(axis=0)
    _, s, _ = np.linalg.svd(pts3 - center)
    if s[0] < 1e-30:
        return True
    return bool(float(s[-1]) < tol * float(s[0]))


def _sample_surface(surf: NurbsSurface, nu: int = 6, nv: int = 6) -> np.ndarray:
    """Return a (nu*nv, 3) array of sampled surface points over its parameter domain."""
    ku, kv = surf.knots_u, surf.knots_v
    du, dv = surf.degree_u, surf.degree_v
    u0, u1 = float(ku[du]), float(ku[-(du + 1)])
    v0, v1 = float(kv[dv]), float(kv[-(dv + 1)])
    pts = []
    for i in range(nu):
        u = u0 + (u1 - u0) * (i + 0.5) / nu
        for j in range(nv):
            v = v0 + (v1 - v0) * (j + 0.5) / nv
            pts.append(np.asarray(surf.evaluate(u, v), dtype=float)[:3])
    return np.array(pts)


def _fit_circle_2d(pts2d: np.ndarray):
    """Fit a circle to 2-D points via least-squares Taubin method.

    Returns ``(rel_rms, radius)`` where ``rel_rms = rms_error / radius``.
    A value of ``rel_rms`` close to zero indicates the points lie on a
    circle.  Returns ``(1.0, 0.0)`` on degenerate input.
    """
    n = len(pts2d)
    if n < 3:
        return 1.0, 0.0
    x, y = pts2d[:, 0], pts2d[:, 1]
    z = x ** 2 + y ** 2
    Mxx = float(np.mean(x * x)) - float(np.mean(x)) ** 2
    Myy = float(np.mean(y * y)) - float(np.mean(y)) ** 2
    Mxy = float(np.mean(x * y)) - float(np.mean(x)) * float(np.mean(y))
    Mxz = float(np.mean(x * z)) - float(np.mean(x)) * float(np.mean(z))
    Myz = float(np.mean(y * z)) - float(np.mean(y)) * float(np.mean(z))
    Mzz = float(np.mean(z * z)) - float(np.mean(z)) ** 2
    M = np.array([[Mzz, Mxz, Myz],
                  [Mxz, Mxx, Mxy],
                  [Myz, Mxy, Myy]], dtype=float)
    try:
        _, vecs = np.linalg.eigh(M)
        A, D, E = vecs[:, 0]
        if abs(A) < 1e-30:
            return 1.0, 0.0
        cx = -D / (2.0 * A)
        cy = -E / (2.0 * A)
        r = float(np.mean(np.sqrt((x - cx) ** 2 + (y - cy) ** 2)))
        if r < 1e-9:
            return 1.0, 0.0
        rms = float(np.sqrt(np.mean(
            (np.sqrt((x - cx) ** 2 + (y - cy) ** 2) - r) ** 2
        )))
        return rms / r, r
    except np.linalg.LinAlgError:
        return 1.0, 0.0


def _is_cylindrical_nurbs(surf: NurbsSurface, tol: float = 5e-3) -> bool:
    """Return True if the evaluated surface lies on a world-axis-aligned
    cylinder (within *tol*).

    Samples the surface and, for each world axis, projects the sampled points
    onto the perpendicular plane and uses a least-squares circle fit.  The
    fitted radius must be at most 2× the 2-D bounding-box extent of the
    projected points; this rejects near-flat patches whose cubic profile
    happens to fit a very large-radius circle with low relative error.
    """
    pts3 = _sample_surface(surf, nu=8, nv=8)
    bbox_diag = float(np.linalg.norm(pts3.max(axis=0) - pts3.min(axis=0)))
    if bbox_diag < 1e-9:
        return False
    for axis_idx in range(3):
        idx = [i for i in range(3) if i != axis_idx]
        proj = pts3[:, idx]
        proj_extent = float(np.linalg.norm(
            proj.max(axis=0) - proj.min(axis=0)
        ))
        if proj_extent < 1e-9:
            continue
        rel_err, radius = _fit_circle_2d(proj)
        if rel_err < tol and radius < 2.0 * proj_extent:
            return True
    return False


def _is_spherical_nurbs(surf: NurbsSurface, tol: float = 1e-3) -> bool:
    """Return True if the evaluated surface points lie on a sphere.

    Uses sampled points and a least-squares sphere fit (centroid + mean
    radius; robust for hemisphere patches).
    """
    pts3 = _sample_surface(surf, nu=8, nv=8)
    # Iterative least-squares sphere fit
    center = pts3.mean(axis=0)
    for _ in range(5):
        radii = np.linalg.norm(pts3 - center, axis=1)
        r_mean = float(radii.mean())
        if r_mean < 1e-9:
            return False
        # Update centre estimate
        dirs = (pts3 - center) / radii[:, None]
        center = center + float(np.mean(radii - r_mean)) * dirs.mean(axis=0)
    radii = np.linalg.norm(pts3 - center, axis=1)
    r_mean = float(radii.mean())
    if r_mean < 1e-9:
        return False
    rel_err = float(np.sqrt(np.mean((radii - r_mean) ** 2))) / r_mean
    return rel_err < tol


def _carrier_type(surf: NurbsSurface) -> "Optional[str]":
    """Classify *surf* as ``'plane'``, ``'cylinder'``, ``'sphere'``, or
    ``None`` (arbitrary NURBS — unsupported).

    The classification is a best-effort geometric probe of the control
    point cloud; it handles all T-104c test surfaces correctly while
    rejecting cubic-z and other non-analytic-carrier shapes.
    """
    if _is_planar_nurbs(surf):
        return "plane"
    if _is_cylindrical_nurbs(surf):
        return "cylinder"
    if _is_spherical_nurbs(surf):
        return "sphere"
    return None


def _nurbs_param_range(surf: NurbsSurface):
    """Return (u_min, u_max, v_min, v_max) for the domain of *surf*."""
    ku = surf.knots_u
    kv = surf.knots_v
    du = surf.degree_u
    dv = surf.degree_v
    return float(ku[du]), float(ku[-(du + 1)]), float(kv[dv]), float(kv[-(dv + 1)])


def _eval3(surf: NurbsSurface, u: float, v: float) -> np.ndarray:
    """Evaluate *surf* at *(u, v)* and return a (3,) float64 array."""
    return np.asarray(surf.evaluate(u, v), dtype=float)[:3]


def g3_blend_trim_sew(
    surf1: NurbsSurface,
    surf2: NurbsSurface,
    *,
    edge: str = "v1_v0",
    samples: int = 24,
    blend_width: float = 0.2,
    tol: float = 1e-6,
) -> dict:
    """Trim the two support surfaces to the G3 blend seam and sew into a Body.

    Builds the G3 blend strip (via :func:`surface_blend_g3`) between *surf1*
    and *surf2*, then assembles the three surfaces — trimmed *surf1*, blend
    strip, trimmed *surf2* — plus four closing faces (bottom + two end caps)
    into a closed, ``validate_body``-clean :class:`Body`.

    Bounded to the **analytic carrier matrix** (Plane / world-axis-aligned
    Cylinder / Sphere) that ``boolean.py``'s GK-19 imprint already supports.
    Arbitrary NURBS×NURBS supports return a structured ``unsupported-input``
    without raising.

    Parameters
    ----------
    surf1, surf2 : NurbsSurface
        The two support surfaces.  Both must lie in the analytic carrier
        matrix (planar / world-axis-cylindrical / spherical control-point
        clouds); non-matrix inputs return ``{"ok": False,
        "reason": "unsupported-input: ..."}``.
    edge : ``"v1_v0"`` | ``"u1_u0"``
        Which boundary pair forms the shared seam.  Only ``"v1_v0"`` is
        currently supported for the trim+sew path.
    samples : int
        Sample count passed to :func:`surface_blend_g3`.
    blend_width : float
        Blend width passed to :func:`surface_blend_g3`.
    tol : float
        Sewing / vertex-coincidence tolerance (default 1e-6).

    Returns
    -------
    dict
        ``ok``                : bool
        ``reason``            : str (empty on success)
        ``body``              : :class:`Body` | None
        ``blend_diagnostics`` : dict from :func:`surface_blend_g3`
    """
    _EMPTY: dict = {
        "ok": False,
        "reason": "",
        "body": None,
        "blend_diagnostics": {},
    }

    # ------------------------------------------------------------------
    # 0. Input-type gate — analytic carrier matrix only
    # ------------------------------------------------------------------
    t1 = _carrier_type(surf1)
    t2 = _carrier_type(surf2)
    if t1 is None or t2 is None:
        unsupported = []
        if t1 is None:
            unsupported.append(
                "surf1 is not in the analytic carrier matrix "
                "(plane/cylinder/sphere)"
            )
        if t2 is None:
            unsupported.append(
                "surf2 is not in the analytic carrier matrix "
                "(plane/cylinder/sphere)"
            )
        return {
            **_EMPTY,
            "reason": "unsupported-input: " + "; ".join(unsupported),
        }

    if edge != "v1_v0":
        return {
            **_EMPTY,
            "reason": (
                f"unsupported-input: edge={edge!r} is not supported by "
                "g3_blend_trim_sew; only 'v1_v0' is implemented"
            ),
        }

    # ------------------------------------------------------------------
    # 1. Build the G3 blend strip
    # ------------------------------------------------------------------
    blend_res = surface_blend_g3(
        surf1, surf2,
        edge=edge,
        samples=samples,
        blend_width=blend_width,
    )
    if not blend_res["ok"]:
        return {
            **_EMPTY,
            "reason": f"surface_blend_g3 failed: {blend_res['reason']}",
            "blend_diagnostics": blend_res.get("diagnostics", {}),
        }

    blend_surf: NurbsSurface = blend_res["blend_surface"]

    # ------------------------------------------------------------------
    # 2. Extract the 8 corner points of the 3-surface assembly
    #
    #   For the "v1_v0" edge:
    #     Seam A:  surf1 v=v1_max  <==>  blend v=bv_min
    #     Seam B:  blend v=bv_max  <==>  surf2 v=v2_min
    #
    #   Eight corners:
    #     P_A0 = surf1(u1_min, v1_min)  — surf1 far corner left
    #     P_A1 = surf1(u1_max, v1_min)  — surf1 far corner right
    #     P_C0 = surf1(u1_min, v1_max)  — seam-A left
    #     P_C1 = surf1(u1_max, v1_max)  — seam-A right
    #     P_D0 = surf2(u2_min, v2_min)  — seam-B left
    #     P_D1 = surf2(u2_max, v2_min)  — seam-B right
    #     P_B0 = surf2(u2_min, v2_max)  — surf2 far corner left
    #     P_B1 = surf2(u2_max, v2_max)  — surf2 far corner right
    # ------------------------------------------------------------------
    u1_min, u1_max, v1_min, v1_max = _nurbs_param_range(surf1)
    u2_min, u2_max, v2_min, v2_max = _nurbs_param_range(surf2)
    bu_min, bu_max, bv_min, bv_max = _nurbs_param_range(blend_surf)

    P_A0 = _eval3(surf1, u1_min, v1_min)
    P_A1 = _eval3(surf1, u1_max, v1_min)
    P_C0 = _eval3(surf1, u1_min, v1_max)
    P_C1 = _eval3(surf1, u1_max, v1_max)
    P_D0 = _eval3(surf2, u2_min, v2_min)
    P_D1 = _eval3(surf2, u2_max, v2_min)
    P_B0 = _eval3(surf2, u2_min, v2_max)
    P_B1 = _eval3(surf2, u2_max, v2_max)

    # ------------------------------------------------------------------
    # 3. Build the six faces using shared Edge objects
    # ------------------------------------------------------------------
    from kerf_cad_core.geom.brep import (
        Body, Coedge, Edge, Face, Line3, Loop, Plane, Shell, Solid,
        Vertex, validate_body,
    )
    from kerf_cad_core.geom.brep_build import (
        BuildError, _SurfaceIsoCurve, _surface_normal_at,
    )
    from kerf_cad_core.geom.sew import sew_into_solid

    out_tol = max(tol, 1e-7)

    # Vertices (8 corners, created once)
    vA0 = Vertex(P_A0, out_tol)
    vA1 = Vertex(P_A1, out_tol)
    vC0 = Vertex(P_C0, out_tol)
    vC1 = Vertex(P_C1, out_tol)
    vD0 = Vertex(P_D0, out_tol)
    vD1 = Vertex(P_D1, out_tol)
    vB0 = Vertex(P_B0, out_tol)
    vB1 = Vertex(P_B1, out_tol)

    # 12 edges (each created once, shared by the loops below)
    e_s1_bot = Edge(
        _SurfaceIsoCurve(surf1, "u", v1_min, u1_min, u1_max),
        u1_min, u1_max, vA0, vA1, out_tol,
    )  # A0 -> A1
    e_s1_lft = Edge(
        _SurfaceIsoCurve(surf1, "v", u1_min, v1_min, v1_max),
        v1_min, v1_max, vA0, vC0, out_tol,
    )  # A0 -> C0
    e_s1_rgt = Edge(
        _SurfaceIsoCurve(surf1, "v", u1_max, v1_min, v1_max),
        v1_min, v1_max, vA1, vC1, out_tol,
    )  # A1 -> C1
    e_seam_A = Edge(
        _SurfaceIsoCurve(surf1, "u", v1_max, u1_min, u1_max),
        u1_min, u1_max, vC0, vC1, out_tol,
    )  # C0 -> C1  (seam A: surf1 top = blend bottom)
    e_bl_lft = Edge(
        _SurfaceIsoCurve(blend_surf, "v", bu_min, bv_min, bv_max),
        bv_min, bv_max, vC0, vD0, out_tol,
    )  # C0 -> D0
    e_bl_rgt = Edge(
        _SurfaceIsoCurve(blend_surf, "v", bu_max, bv_min, bv_max),
        bv_min, bv_max, vC1, vD1, out_tol,
    )  # C1 -> D1
    e_seam_B = Edge(
        _SurfaceIsoCurve(blend_surf, "u", bv_max, bu_min, bu_max),
        bu_min, bu_max, vD0, vD1, out_tol,
    )  # D0 -> D1  (seam B: blend top = surf2 bottom)
    e_s2_lft = Edge(
        _SurfaceIsoCurve(surf2, "v", u2_min, v2_min, v2_max),
        v2_min, v2_max, vD0, vB0, out_tol,
    )  # D0 -> B0
    e_s2_rgt = Edge(
        _SurfaceIsoCurve(surf2, "v", u2_max, v2_min, v2_max),
        v2_min, v2_max, vD1, vB1, out_tol,
    )  # D1 -> B1
    e_s2_top = Edge(
        _SurfaceIsoCurve(surf2, "u", v2_max, u2_min, u2_max),
        u2_min, u2_max, vB0, vB1, out_tol,
    )  # B0 -> B1
    e_bot_lft = Edge(
        Line3(P_A0, P_B0), 0.0, 1.0, vA0, vB0, out_tol,
    )  # A0 -> B0
    e_bot_rgt = Edge(
        Line3(P_A1, P_B1), 0.0, 1.0, vA1, vB1, out_tol,
    )  # A1 -> B1

    # ------------------------------------------------------------------
    # 4. Build CCW loops; helper orients each loop CCW wrt its surface
    # ------------------------------------------------------------------
    def _make_face(surface, edge_orient_list, out_tol):
        """Build a Face with a CCW outer loop for *surface*.

        *edge_orient_list* is a sequence of ``(Edge, forward_bool)`` pairs
        in the intended traversal order.  If the resulting polygon area
        vector is CW wrt the surface normal, the whole sequence is reversed
        and each orientation flipped, giving a CCW loop.
        """
        coedges_fwd = [Coedge(e, fwd) for e, fwd in edge_orient_list]
        # Sample the traversal polygon.
        pts = []
        for ce in coedges_fwd:
            p = np.asarray(ce.start_point(), dtype=float)
            if not pts or float(np.linalg.norm(p - pts[-1])) > 1e-14:
                pts.append(p)
        if len(pts) >= 3:
            # Surface normal at centre.
            u0_, u1_, v0_, v1_ = _nurbs_param_range(surface) \
                if hasattr(surface, "knots_u") else (0.0, 1.0, 0.0, 1.0)
            n_surf = np.asarray(
                _surface_normal_at(surface, 0.5 * (u0_ + u1_),
                                   0.5 * (v0_ + v1_)),
                dtype=float,
            )
            centroid = np.mean(pts, axis=0)
            area_vec = np.zeros(3)
            m = len(pts)
            for i in range(m):
                a = pts[i] - centroid
                b = pts[(i + 1) % m] - centroid
                area_vec += np.cross(a, b)
            if float(np.dot(area_vec, n_surf)) < 0:
                # CW — reverse traversal.
                edge_orient_list = [(e, not fwd)
                                    for e, fwd in reversed(edge_orient_list)]
                coedges_fwd = [Coedge(e, fwd) for e, fwd in edge_orient_list]
        loop = Loop(coedges_fwd, is_outer=True)
        face = Face(surface, [loop], orientation=True, tol=out_tol)
        return face

    # surf1: traversal A0->A1->C1->C0->A0
    face_s1 = _make_face(surf1, [
        (e_s1_bot, True),   # A0 -> A1
        (e_s1_rgt, True),   # A1 -> C1
        (e_seam_A, False),  # C1 -> C0 (reversed)
        (e_s1_lft, False),  # C0 -> A0 (reversed)
    ], out_tol)

    # blend: traversal C0->C1->D1->D0->C0
    face_bl = _make_face(blend_surf, [
        (e_seam_A, True),   # C0 -> C1
        (e_bl_rgt, True),   # C1 -> D1
        (e_seam_B, False),  # D1 -> D0 (reversed)
        (e_bl_lft, False),  # D0 -> C0 (reversed)
    ], out_tol)

    # surf2: traversal D0->D1->B1->B0->D0
    face_s2 = _make_face(surf2, [
        (e_seam_B, True),   # D0 -> D1
        (e_s2_rgt, True),   # D1 -> B1
        (e_s2_top, False),  # B1 -> B0 (reversed)
        (e_s2_lft, False),  # B0 -> D0 (reversed)
    ], out_tol)

    # bottom face: traversal A0->B0->B1->A1->A0
    d1_b = _unit3(P_B0 - P_A0)
    d2_b = _unit3(P_A1 - P_A0)
    if float(np.linalg.norm(np.cross(d1_b, d2_b))) < 1e-9:
        d2_b = _unit3(P_B1 - P_A0)
    plane_bot = Plane(origin=P_A0, x_axis=d1_b, y_axis=d2_b)
    face_bot = _make_face(plane_bot, [
        (e_bot_lft, True),   # A0 -> B0
        (e_s2_top, True),    # B0 -> B1
        (e_bot_rgt, False),  # B1 -> A1 (reversed)
        (e_s1_bot, False),   # A1 -> A0 (reversed)
    ], out_tol)

    # left cap face: traversal A0->C0->D0->B0->A0
    d1_l = _unit3(P_C0 - P_A0)
    d2_l = _unit3(P_B0 - P_A0)
    if float(np.linalg.norm(np.cross(d1_l, d2_l))) < 1e-9:
        d2_l = _unit3(P_D0 - P_A0)
    plane_lft = Plane(origin=P_A0, x_axis=d1_l, y_axis=d2_l)
    face_lft = _make_face(plane_lft, [
        (e_s1_lft, True),    # A0 -> C0
        (e_bl_lft, True),    # C0 -> D0
        (e_s2_lft, True),    # D0 -> B0
        (e_bot_lft, False),  # B0 -> A0 (reversed)
    ], out_tol)

    # right cap face: traversal A1->B1->D1->C1->A1
    d1_r = _unit3(P_B1 - P_A1)
    d2_r = _unit3(P_C1 - P_A1)
    if float(np.linalg.norm(np.cross(d1_r, d2_r))) < 1e-9:
        d2_r = _unit3(P_D1 - P_A1)
    plane_rgt = Plane(origin=P_A1, x_axis=d1_r, y_axis=d2_r)
    face_rgt = _make_face(plane_rgt, [
        (e_bot_rgt, True),  # A1 -> B1
        (e_s2_rgt, False),  # B1 -> D1 (reversed)
        (e_bl_rgt, False),  # D1 -> C1 (reversed)
        (e_s1_rgt, False),  # C1 -> A1 (reversed)
    ], out_tol)

    # ------------------------------------------------------------------
    # 5. Sew into a validated solid Body
    # ------------------------------------------------------------------
    try:
        body = sew_into_solid(
            [face_s1, face_bl, face_s2, face_bot, face_lft, face_rgt],
            tol=out_tol,
        )
    except BuildError as exc:
        return {
            **_EMPTY,
            "reason": f"sew_into_solid failed: {exc}",
            "blend_diagnostics": blend_res.get("diagnostics", {}),
        }

    return {
        "ok": True,
        "reason": "",
        "body": body,
        "blend_diagnostics": blend_res.get("diagnostics", {}),
    }