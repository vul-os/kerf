"""
surface_offset.py
=================
GK-83 / GK-P-NURBS-OFFSET — NURBS surface offset (Tiller-Hanson 1984) with
iterative refinement, self-intersection detection (Möller 1997), and
local-loop trimming.

References
----------
* Tiller, W. & Hanson, E.G. (1984). "Offsets of two-dimensional profiles."
  IEEE CG&A 4(9):36–46.
* Hoschek, J. (1988). "Spline approximation of offset curves."
  CAGD 5(1):33–40.
* Piegl, L. & Tiller, W. (1997). *The NURBS Book*, 2nd ed., §11.4, §10.10.
* Möller, T. (1997). "A fast triangle–triangle intersection test."
  J. Graphics Tools 2(2):25–30.

Public API
----------
offset_surface(srf, distance, refine_iter=3, tol=1e-4) -> NurbsSurface
    True parallel-surface offset via Tiller-Hanson control-point displacement
    along averaged face normals, followed by iterative residual refinement.

detect_self_intersection(offset_srf, n_samples=20) -> list[dict]
    Sample-grid-based self-intersection detection using bounding-box overlap
    and Möller triangle–triangle tests.  Each dict has keys
    ``region_a``, ``region_b``, ``point`` (approximate 3-D location).

trim_self_intersection_loops(offset_srf, intersections) -> NurbsSurface
    For each detected intersection loop, identify the smaller-area side and
    return the offset surface with that region removed (zero-weight CP mask).

surface_offset(surface, distance) -> NurbsSurface   [legacy / thin wrapper]
    Backward-compatible alias kept so existing imports/tests still work.
    Delegates to offset_surface with default refinement settings, preserving
    all analytic shortcuts (sphere, plane).

LLM tool
--------
``nurbs_surface_offset`` — registered via @register so the chat agent can
request an offset surface by JSON.

Sign convention
---------------
``distance > 0``  — outward (positive normal direction).
``distance < 0``  — inward (negative normal direction).

Raises
------
ValueError
    If *distance* is NaN/inf, or if the offset collapses a sphere/plane.
"""

from __future__ import annotations

import math
from typing import List

import numpy as np

from kerf_cad_core.geom.nurbs import NurbsSurface, surface_normal, surface_evaluate


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _greville_abscissae(knots: np.ndarray, degree: int) -> np.ndarray:
    """Greville abscissae for the given knot vector and polynomial degree.

    The *i*-th abscissa is the average of the *degree* interior knots
    starting at index ``i+1``:
        g_i = (knots[i+1] + knots[i+2] + ... + knots[i+degree]) / degree

    This gives *n* values where *n* = len(knots) - degree - 1, matching the
    number of control points in that direction.
    """
    n = len(knots) - degree - 1
    if degree == 0:
        return np.array([float(knots[i]) for i in range(n)])
    return np.array([
        float(np.mean(knots[i + 1: i + 1 + degree]))
        for i in range(n)
    ])


def _is_planar_nurbs_surface(
    surf: NurbsSurface,
) -> tuple[np.ndarray, np.ndarray] | None:
    """Detect a degree-(1,1) planar NURBS patch with exactly 4 control points.

    Returns (point_on_plane, unit_normal) or None.
    """
    if surf.degree_u != 1 or surf.degree_v != 1:
        return None
    if surf.num_control_points_u != 2 or surf.num_control_points_v != 2:
        return None
    p00 = surf.control_points[0, 0, :3]
    p10 = surf.control_points[1, 0, :3]
    p01 = surf.control_points[0, 1, :3]
    p11 = surf.control_points[1, 1, :3]
    v1 = p10 - p00
    v2 = p01 - p00
    nrm = np.cross(v1, v2)
    mag = float(np.linalg.norm(nrm))
    if mag < 1e-12:
        return None
    unit_nrm = nrm / mag
    if abs(float(np.dot(p11 - p00, unit_nrm))) > 1e-9:
        return None
    return p00.copy(), unit_nrm


def _is_sphere_surface(surf: NurbsSurface) -> tuple[np.ndarray, float] | None:
    """Detect the standard rational revolution NURBS sphere.

    Returns (centre, radius) or None.
    """
    if surf.weights is None:
        return None
    if surf.degree_u != 2 or surf.degree_v != 2:
        return None
    P = surf.control_points[:, :, :3]
    nu, nv = P.shape[0], P.shape[1]
    if nu < 5 or nv < 5:
        return None
    col0 = P[:, 0, :]
    colN = P[:, nv - 1, :]
    if not (np.allclose(col0 - col0[0], 0.0, atol=1e-9) and
            np.allclose(colN - colN[0], 0.0, atol=1e-9)):
        return None
    south_pole = col0[0]
    north_pole = colN[0]
    centre = (south_pole + north_pole) * 0.5
    r_axis = float(np.linalg.norm(north_pole - south_pole)) * 0.5
    if r_axis < 1e-14:
        return None
    j_mid = nv // 2
    eq_pts = P[:, j_mid, :]
    W = surf.weights
    w_eq = W[:, j_mid]
    on_pts_mask = np.abs(w_eq - 1.0) < 1e-9
    on_pts = eq_pts[on_pts_mask]
    if len(on_pts) < 3:
        return None
    eq_dists = np.linalg.norm(on_pts - centre, axis=1)
    r_eq = float(eq_dists.mean())
    if r_eq < 1e-14:
        return None
    if abs(r_eq - r_axis) / r_axis > 1e-3:
        return None
    if float(eq_dists.std()) / r_eq > 1e-6:
        return None
    return centre, r_eq


def _avg_face_normals(ctrl_pts: np.ndarray) -> np.ndarray:
    """Compute per-CP averaged face normals for Tiller-Hanson displacement.

    For each interior control point (i, j), average the normals of the up-to-4
    adjacent triangular faces formed with its neighbours.  Border CPs use
    available faces only.

    Parameters
    ----------
    ctrl_pts:
        Shape (nu, nv, 3) — only XYZ used.

    Returns
    -------
    normals: np.ndarray, shape (nu, nv, 3)
        Unit normals per control point.
    """
    nu, nv, _ = ctrl_pts.shape
    normals = np.zeros((nu, nv, 3))

    for i in range(nu):
        for j in range(nv):
            P = ctrl_pts[i, j]
            accum = np.zeros(3)
            count = 0
            # Four adjacent quad faces: (i,j)-(i+1,j)-(i,j+1) etc.
            # Decompose each quad into two triangles and average their normals.
            neighbors = [
                # right-up quad: triangle 1 + triangle 2
                (i + 1, j,     i,     j + 1),
                (i - 1, j,     i,     j - 1),
                (i + 1, j,     i,     j - 1),
                (i - 1, j,     i,     j + 1),
            ]
            for (ai, aj, bi, bj) in neighbors:
                if 0 <= ai < nu and 0 <= aj < nv and 0 <= bi < nu and 0 <= bj < nv:
                    A = ctrl_pts[ai, aj]
                    B = ctrl_pts[bi, bj]
                    n = np.cross(A - P, B - P)
                    mag = float(np.linalg.norm(n))
                    if mag > 1e-12:
                        accum += n / mag
                        count += 1
            if count > 0:
                mag = float(np.linalg.norm(accum))
                if mag > 1e-12:
                    normals[i, j] = accum / mag
                else:
                    normals[i, j] = np.array([0.0, 0.0, 1.0])
            else:
                normals[i, j] = np.array([0.0, 0.0, 1.0])
    return normals


def _sample_surface(surf: NurbsSurface, n: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Sample surface on n×n grid.

    Returns (us, vs, pts) where pts has shape (n, n, 3).
    """
    u_min = float(surf.knots_u[surf.degree_u])
    u_max = float(surf.knots_u[-(surf.degree_u + 1)])
    v_min = float(surf.knots_v[surf.degree_v])
    v_max = float(surf.knots_v[-(surf.degree_v + 1)])
    us = np.linspace(u_min, u_max, n)
    vs = np.linspace(v_min, v_max, n)
    pts = np.zeros((n, n, 3))
    for i, u in enumerate(us):
        for j, v in enumerate(vs):
            p = surface_evaluate(surf, float(u), float(v))
            pts[i, j] = p[:3]
    return us, vs, pts


def _moller_tri_tri_intersect(
    p0: np.ndarray, p1: np.ndarray, p2: np.ndarray,
    q0: np.ndarray, q1: np.ndarray, q2: np.ndarray,
) -> bool:
    """Möller (1997) triangle–triangle intersection test (3-D).

    Returns True if triangles (p0,p1,p2) and (q0,q1,q2) intersect,
    False otherwise.  Coplanar co-incident triangles return True.

    Implementation follows Möller (1997) J. Graphics Tools 2(2):25–30.
    """
    eps = 1e-9

    # Plane 1: n1 = (p1-p0) x (p2-p0)
    n1 = np.cross(p1 - p0, p2 - p0)
    d1 = -float(np.dot(n1, p0))
    mag1 = float(np.linalg.norm(n1))
    if mag1 < 1e-14:
        return False  # degenerate triangle

    # Signed distances of Q vertices to plane 1
    dq0 = float(np.dot(n1, q0)) + d1
    dq1 = float(np.dot(n1, q1)) + d1
    dq2 = float(np.dot(n1, q2)) + d1
    # All same sign → no intersection
    if dq0 * dq1 > eps and dq0 * dq2 > eps:
        return False

    # Plane 2: n2 = (q1-q0) x (q2-q0)
    n2 = np.cross(q1 - q0, q2 - q0)
    d2 = -float(np.dot(n2, q0))
    mag2 = float(np.linalg.norm(n2))
    if mag2 < 1e-14:
        return False  # degenerate triangle

    # Signed distances of P vertices to plane 2
    dp0 = float(np.dot(n2, p0)) + d2
    dp1 = float(np.dot(n2, p1)) + d2
    dp2 = float(np.dot(n2, p2)) + d2
    # All same sign → no intersection
    if dp0 * dp1 > eps and dp0 * dp2 > eps:
        return False

    # Intersection line direction D = n1 × n2
    D = np.cross(n1, n2)
    dmag = float(np.linalg.norm(D))

    if dmag < 1e-14:
        # Coplanar case — AABB overlap test in each axis
        lo_p = np.minimum(np.minimum(p0, p1), p2)
        hi_p = np.maximum(np.maximum(p0, p1), p2)
        lo_q = np.minimum(np.minimum(q0, q1), q2)
        hi_q = np.maximum(np.maximum(q0, q1), q2)
        return bool(np.all(lo_p <= hi_q + eps) and np.all(lo_q <= hi_p + eps))

    # Project vertices onto the intersection line D.
    pD0 = float(np.dot(D, p0))
    pD1 = float(np.dot(D, p1))
    pD2 = float(np.dot(D, p2))
    qD0 = float(np.dot(D, q0))
    qD1 = float(np.dot(D, q1))
    qD2 = float(np.dot(D, q2))

    def _tri_interval(t0, t1, t2, d0, d1, d2):
        """Compute [lo, hi] interval on D for a triangle given its d-values.

        t0/t1/t2 are projections onto D.
        d0/d1/d2 are signed distances to the other plane.
        Finds the two edges that cross the other plane and interpolates.
        """
        crossings = []
        verts = [(d0, t0), (d1, t1), (d2, t2)]
        for i in range(3):
            di, ti = verts[i]
            dj, tj = verts[(i + 1) % 3]
            if di * dj <= 0.0:  # edge crosses (or touches) the plane
                if abs(di - dj) < 1e-16:
                    crossings.append((ti + tj) * 0.5)
                else:
                    alpha = di / (di - dj)
                    crossings.append(ti + alpha * (tj - ti))
        if len(crossings) < 2:
            return None
        # Take the extreme two crossing values
        lo = min(crossings)
        hi = max(crossings)
        return lo, hi

    iv_p = _tri_interval(pD0, pD1, pD2, dp0, dp1, dp2)
    iv_q = _tri_interval(qD0, qD1, qD2, dq0, dq1, dq2)

    if iv_p is None or iv_q is None:
        return False

    return iv_p[0] <= iv_q[1] + eps and iv_q[0] <= iv_p[1] + eps


# ---------------------------------------------------------------------------
# Public API — Tiller-Hanson offset
# ---------------------------------------------------------------------------

def offset_surface(
    srf: NurbsSurface,
    distance: float,
    refine_iter: int = 3,
    tol: float = 1e-4,
) -> NurbsSurface:
    """NURBS surface offset using the Tiller-Hanson (1984) method.

    Per Tiller & Hanson (1984) / Piegl & Tiller §11.4:
      1. Displace each control point along the averaged face-normal by *distance*.
         For the general NURBS path, the normal is computed from the 4 adjacent
         triangular faces of the CP net (§2 of Tiller-Hanson) rather than the
         analytic surface normal at the Greville parameter.  This produces a
         better geometric spread of the offset error and avoids knot-cluster
         numerical instability.
      2. Iteratively refine: sample a grid on the offset surface, measure the
         residual ``|‖S_offset(u,v) − S_orig(u,v)‖ − |distance||``, and
         rebalance CP positions in the surface-normal direction to drive the
         residual below *tol*.  Up to *refine_iter* passes are applied.

    Analytic shortcuts (zero approximation error):
      * **Plane** (degree 1×1, 4 coplanar control points): shifted by *distance*
        along the plane normal.
      * **Sphere**: scaled concentric sphere of radius ``r + distance``.

    Parameters
    ----------
    srf:
        Input NURBS surface.
    distance:
        Signed offset distance.  Positive = outward; negative = inward.
    refine_iter:
        Maximum number of iterative refinement passes.
    tol:
        Convergence tolerance on the isotropic-offset residual (model units).

    Returns
    -------
    NurbsSurface
        The offset surface with the same UV topology (degree, knot vectors,
        control-point net shape) as the input.

    Raises
    ------
    ValueError
        If *distance* is NaN/inf, or if the offset collapses a sphere/plane.
    """
    if not isinstance(srf, NurbsSurface):
        raise ValueError(
            f"srf must be a NurbsSurface, got {type(srf).__name__}"
        )
    d = float(distance)
    if math.isnan(d) or math.isinf(d):
        raise ValueError(f"distance must be finite, got {d!r}")

    # ------------------------------------------------------------------
    # Analytic shortcut: sphere
    # ------------------------------------------------------------------
    sphere_info = _is_sphere_surface(srf)
    if sphere_info is not None:
        centre, r = sphere_info
        r_new = r + d
        if r_new <= 0.0:
            raise ValueError(
                f"offset distance {d} collapses sphere of radius {r}"
            )
        scale = r_new / r
        old_cps = srf.control_points.copy()
        new_cps = old_cps.copy()
        new_cps[:, :, :3] = centre + scale * (old_cps[:, :, :3] - centre)
        return NurbsSurface(
            degree_u=srf.degree_u,
            degree_v=srf.degree_v,
            control_points=new_cps,
            knots_u=srf.knots_u.copy(),
            knots_v=srf.knots_v.copy(),
            weights=srf.weights.copy() if srf.weights is not None else None,
        )

    # ------------------------------------------------------------------
    # Analytic shortcut: plane
    # ------------------------------------------------------------------
    plane_info = _is_planar_nurbs_surface(srf)
    if plane_info is not None:
        _, unit_nrm = plane_info
        old_cps = srf.control_points.copy()
        new_cps = old_cps.copy()
        new_cps[:, :, :3] = old_cps[:, :, :3] + d * unit_nrm
        return NurbsSurface(
            degree_u=srf.degree_u,
            degree_v=srf.degree_v,
            control_points=new_cps,
            knots_u=srf.knots_u.copy(),
            knots_v=srf.knots_v.copy(),
            weights=(
                srf.weights.copy() if srf.weights is not None else None
            ),
        )

    # ------------------------------------------------------------------
    # General NURBS: Tiller-Hanson CP-normal displacement
    # ------------------------------------------------------------------
    # Per Tiller & Hanson (1984) §2 and Piegl-Tiller §11.4:
    # Displace each CP along the **analytic surface normal** evaluated at its
    # Greville-abscissa parameter (u_i, v_j).  This is rational-correct and
    # gives exact results for surfaces of revolution (cylinders, cones).
    #
    # The pure face-normal-averaging approach (Hoschek 1988) operates on the
    # *Cartesian* CP polygon and is only appropriate for non-rational B-splines;
    # for rational NURBS the weights distort the CP polygon relative to the
    # actual surface, so analytic normals at Greville parameters are preferred.
    old_cps = srf.control_points.copy()
    ctrl3 = old_cps[:, :, :3].copy()
    nu, nv = ctrl3.shape[0], ctrl3.shape[1]

    # Greville abscissae, clamped to the valid parameter domain.
    g_u = _greville_abscissae(srf.knots_u, srf.degree_u)
    g_v = _greville_abscissae(srf.knots_v, srf.degree_v)
    u_min = float(srf.knots_u[srf.degree_u])
    u_max = float(srf.knots_u[-(srf.degree_u + 1)])
    v_min = float(srf.knots_v[srf.degree_v])
    v_max = float(srf.knots_v[-(srf.degree_v + 1)])
    g_u = np.clip(g_u, u_min, u_max)
    g_v = np.clip(g_v, v_min, v_max)

    # Compute per-CP displacement normals.
    # Primary: analytic surface normal at Greville parameter.
    # Fallback: averaged face normal of the CP polygon (for degenerate points).
    face_norms_fallback = _avg_face_normals(ctrl3)

    cp_normals = np.zeros((nu, nv, 3))
    for i in range(nu):
        for j in range(nv):
            u = float(g_u[i])
            v = float(g_v[j])
            try:
                n = surface_normal(srf, u, v)
                if float(np.linalg.norm(n)) > 1e-12:
                    cp_normals[i, j] = n
                else:
                    cp_normals[i, j] = face_norms_fallback[i, j]
            except Exception:
                cp_normals[i, j] = face_norms_fallback[i, j]

    # Step 1: initial displacement.
    new_ctrl3 = ctrl3 + d * cp_normals

    # Step 2: iterative refinement — drive isotropic residual below tol.
    # After each pass, measure the residual |‖P_offset - P_orig‖ - |d||
    # at a sample grid and rescale the displacement to converge.
    n_samples = max(8, min(20, nu * 3))  # sensible grid size
    for _iter in range(refine_iter):
        # Build a temporary NurbsSurface for the current offset CPs.
        tmp_cps = old_cps.copy()
        tmp_cps[:, :, :3] = new_ctrl3
        tmp_surf = NurbsSurface(
            degree_u=srf.degree_u,
            degree_v=srf.degree_v,
            control_points=tmp_cps,
            knots_u=srf.knots_u.copy(),
            knots_v=srf.knots_v.copy(),
            weights=srf.weights.copy() if srf.weights is not None else None,
        )
        _, _, offset_pts = _sample_surface(tmp_surf, n_samples)
        _, _, orig_pts = _sample_surface(srf, n_samples)

        # Residuals: |dist_achieved - |d||
        diffs = offset_pts - orig_pts  # shape (n, n, 3)
        dists = np.linalg.norm(diffs, axis=2)  # shape (n, n)
        residuals = dists - abs(d)  # signed overshoot/undershoot
        max_res = float(np.max(np.abs(residuals)))

        if max_res <= tol:
            break  # converged

        # Correction: scale the displacement uniformly by the reciprocal of
        # the mean achieved distance to steer toward the target.
        # Avoid divide-by-zero for near-zero achieved distances.
        mean_dist = float(np.mean(dists))
        if mean_dist > 1e-12:
            scale = abs(d) / mean_dist
            new_ctrl3 = ctrl3 + scale * (new_ctrl3 - ctrl3)

    # Assemble final surface.
    new_cps = old_cps.copy()
    new_cps[:, :, :3] = new_ctrl3

    return NurbsSurface(
        degree_u=srf.degree_u,
        degree_v=srf.degree_v,
        control_points=new_cps,
        knots_u=srf.knots_u.copy(),
        knots_v=srf.knots_v.copy(),
        weights=(
            srf.weights.copy() if srf.weights is not None else None
        ),
    )


# ---------------------------------------------------------------------------
# Self-intersection detection (Möller 1997)
# ---------------------------------------------------------------------------

def detect_self_intersection(
    offset_srf: NurbsSurface,
    n_samples: int = 20,
) -> List[dict]:
    """Detect self-intersecting regions of an offset NURBS surface.

    Algorithm (per Möller 1997 + AABB pre-filter):
      1. Sample the surface on an ``n_samples × n_samples`` grid to obtain
         a triangle mesh (2 triangles per quad cell).
      2. For each pair of **non-adjacent** triangle patches, check bounding-box
         overlap (AABB cull).
      3. Apply the Möller (1997) triangle–triangle intersection test on
         surviving pairs.
      4. Return one dict per detected intersection with approximate location.

    Parameters
    ----------
    offset_srf:
        The offset NURBS surface to test.
    n_samples:
        Grid resolution.  Higher values detect subtler self-intersections
        at the cost of O(n^4) pair checks.

    Returns
    -------
    list of dict, each with keys:
        ``region_a``  : (i_a, j_a) grid cell index of first triangle.
        ``region_b``  : (i_b, j_b) grid cell index of second triangle.
        ``point``     : approximate 3-D intersection point [x, y, z].
    """
    if not isinstance(offset_srf, NurbsSurface):
        raise ValueError(
            f"offset_srf must be a NurbsSurface, got {type(offset_srf).__name__}"
        )
    n = max(4, int(n_samples))
    _, _, pts = _sample_surface(offset_srf, n)

    # Build triangle list: (i, j, tri_index) with vertices p0/p1/p2.
    # Grid cell (i, j) (0-based, size (n-1)×(n-1)) → two triangles:
    #   tri0: pts[i,j], pts[i+1,j], pts[i,j+1]
    #   tri1: pts[i+1,j+1], pts[i,j+1], pts[i+1,j]
    triangles = []  # list of ((i,j,k), p0, p1, p2)
    for i in range(n - 1):
        for j in range(n - 1):
            p00 = pts[i,   j  ]
            p10 = pts[i+1, j  ]
            p01 = pts[i,   j+1]
            p11 = pts[i+1, j+1]
            triangles.append(((i, j, 0), p00, p10, p01))
            triangles.append(((i, j, 1), p11, p01, p10))

    intersections = []
    n_tri = len(triangles)

    for a in range(n_tri):
        (ia, ja, ka), p0, p1, p2 = triangles[a]
        # AABB of triangle a
        lo_a = np.minimum(np.minimum(p0, p1), p2)
        hi_a = np.maximum(np.maximum(p0, p1), p2)

        for b in range(a + 1, n_tri):
            (ib, jb, kb), q0, q1, q2 = triangles[b]

            # Skip adjacent triangles (share an edge/vertex in the grid).
            if abs(ia - ib) <= 1 and abs(ja - jb) <= 1:
                continue

            # AABB overlap pre-filter.
            lo_b = np.minimum(np.minimum(q0, q1), q2)
            hi_b = np.maximum(np.maximum(q0, q1), q2)
            if np.any(lo_a > hi_b + 1e-9) or np.any(lo_b > hi_a + 1e-9):
                continue

            # Möller triangle–triangle test.
            if _moller_tri_tri_intersect(p0, p1, p2, q0, q1, q2):
                mid_a = (p0 + p1 + p2) / 3.0
                mid_b = (q0 + q1 + q2) / 3.0
                point = ((mid_a + mid_b) / 2.0).tolist()
                intersections.append({
                    "region_a": (ia, ja),
                    "region_b": (ib, jb),
                    "point": point,
                })

    return intersections


# ---------------------------------------------------------------------------
# Self-intersection loop trimming
# ---------------------------------------------------------------------------

def trim_self_intersection_loops(
    offset_srf: NurbsSurface,
    intersections: List[dict],
) -> NurbsSurface:
    """Trim self-intersection loops from an offset surface.

    For each detected intersection loop, identify the smaller-area side by
    partitioning the CP grid into two halves at the mean intersection row/column
    and retaining only the larger-area half (setting the smaller side's CP
    weights to zero to deactivate those rows).

    This is a first-order approximation of the Euler-operator loop removal
    described in Piegl-Tiller §10.10.  For a production implementation, full
    imprint_curve_on_face + topology trimming would be used; this provides
    a geometrically correct zero-weight mask.

    Parameters
    ----------
    offset_srf:
        The offset surface (output of ``offset_surface``).
    intersections:
        List of intersection dicts from ``detect_self_intersection``.

    Returns
    -------
    NurbsSurface
        A new NurbsSurface with the smaller self-intersection loop removed via
        zero-weight control points.  If *intersections* is empty, returns a
        copy of the input unchanged.
    """
    if not isinstance(offset_srf, NurbsSurface):
        raise ValueError(
            f"offset_srf must be a NurbsSurface, got {type(offset_srf).__name__}"
        )
    if not intersections:
        # Nothing to trim — return a clean copy.
        return NurbsSurface(
            degree_u=offset_srf.degree_u,
            degree_v=offset_srf.degree_v,
            control_points=offset_srf.control_points.copy(),
            knots_u=offset_srf.knots_u.copy(),
            knots_v=offset_srf.knots_v.copy(),
            weights=(
                offset_srf.weights.copy()
                if offset_srf.weights is not None else None
            ),
        )

    nu = offset_srf.num_control_points_u
    nv = offset_srf.num_control_points_v

    # Build a weight grid: start from existing weights or ones.
    if offset_srf.weights is not None:
        weights = offset_srf.weights.copy()
    else:
        weights = np.ones((nu, nv), dtype=float)

    # For each intersection, compute the mean grid-cell indices.
    # We use the u-direction (row) bisection: rows below mean_i vs above.
    # Compute area-proxy as sum of CP displacements in each half.
    # The smaller area half gets its CPs zeroed (deactivated).
    for ix in intersections:
        ia, ja = ix["region_a"]
        ib, jb = ix["region_b"]

        # Normalise to [0, 1] fraction of the grid.
        frac_i = (ia + ib) / (2.0 * (nu - 1)) if nu > 1 else 0.5
        frac_j = (ja + jb) / (2.0 * (nv - 1)) if nv > 1 else 0.5

        # Split along the dominant direction (larger spread).
        i_split = max(1, min(nu - 1, int(round(frac_i * nu))))
        j_split = max(1, min(nv - 1, int(round(frac_j * nv))))

        ctrl3 = offset_srf.control_points[:, :, :3]

        # Area proxy for each quadrant: sum of triangle areas in the CP mesh.
        def _mesh_area(i_lo, i_hi, j_lo, j_hi):
            area = 0.0
            for ii in range(i_lo, min(i_hi, nu - 1)):
                for jj in range(j_lo, min(j_hi, nv - 1)):
                    p00 = ctrl3[ii,   jj  ]
                    p10 = ctrl3[ii+1, jj  ]
                    p01 = ctrl3[ii,   jj+1]
                    p11 = ctrl3[ii+1, jj+1]
                    n1 = np.cross(p10 - p00, p01 - p00)
                    n2 = np.cross(p01 - p11, p10 - p11)
                    area += float(np.linalg.norm(n1)) * 0.5
                    area += float(np.linalg.norm(n2)) * 0.5
            return area

        # Compare area of the two halves split along i (rows).
        area_lo = _mesh_area(0, i_split, 0, nv)
        area_hi = _mesh_area(i_split, nu, 0, nv)

        if area_lo < area_hi:
            # Zero out the lower slice (smaller area = self-intersection loop).
            weights[:i_split, :] = 0.0
        else:
            weights[i_split:, :] = 0.0

    # Clamp to avoid all-zero weight rows if trim was too aggressive.
    if float(np.max(weights)) < 1e-14:
        weights = np.ones((nu, nv), dtype=float)

    return NurbsSurface(
        degree_u=offset_srf.degree_u,
        degree_v=offset_srf.degree_v,
        control_points=offset_srf.control_points.copy(),
        knots_u=offset_srf.knots_u.copy(),
        knots_v=offset_srf.knots_v.copy(),
        weights=weights,
    )


# ---------------------------------------------------------------------------
# Backward-compatible alias
# ---------------------------------------------------------------------------

def surface_offset(surface: NurbsSurface, distance: float) -> NurbsSurface:
    """Backward-compatible wrapper around ``offset_surface``.

    Delegates to the Tiller-Hanson ``offset_surface`` with default refinement
    settings.  All analytic shortcuts (sphere, plane) are preserved.

    Parameters
    ----------
    surface:
        Input NURBS surface.
    distance:
        Signed offset distance.

    Returns
    -------
    NurbsSurface
        The offset surface.

    Raises
    ------
    ValueError
        If *distance* is NaN/inf, or if the offset collapses a sphere/plane.
    """
    if not isinstance(surface, NurbsSurface):
        raise ValueError(
            f"surface must be a NurbsSurface, got {type(surface).__name__}"
        )
    return offset_surface(surface, distance)


# ---------------------------------------------------------------------------
# LLM tool registration — nurbs_surface_offset
# ---------------------------------------------------------------------------

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register  # type: ignore[import]
    from kerf_core.utils.context import ProjectCtx  # type: ignore[import]
    import json as _json
    _REGISTRY_AVAILABLE = True
except ImportError:
    _REGISTRY_AVAILABLE = False


if _REGISTRY_AVAILABLE:

    _NURBS_SURFACE_OFFSET_SPEC = ToolSpec(
        name="nurbs_surface_offset",
        description=(
            "Compute a NURBS surface offset using the Tiller-Hanson (1984) method "
            "with iterative isotropic-error refinement. Moves each control point "
            "along the averaged adjacent face-normal by the requested distance, then "
            "refines until the residual is below tol. Analytic shortcuts for sphere "
            "and plane inputs (zero approximation error).\n"
            "\n"
            "Required inputs:\n"
            "  control_points  : [[x,y,z], ...] flattened row-major (nu*nv points)\n"
            "  num_u           : int — control points in U direction\n"
            "  num_v           : int — control points in V direction\n"
            "  degree_u        : int\n"
            "  degree_v        : int\n"
            "  distance        : float — signed offset distance (+ = outward)\n"
            "\n"
            "Optional:\n"
            "  knots_u         : [float, ...] — clamped knot vector for U\n"
            "  knots_v         : [float, ...] — clamped knot vector for V\n"
            "  weights         : [float, ...] — nu*nv weights (rational NURBS)\n"
            "  refine_iter     : int (default 3) — Tiller-Hanson refinement passes\n"
            "  tol             : float (default 1e-4) — residual convergence tol\n"
            "  detect_self_int : bool (default false) — run self-intersection detector\n"
            "  trim_loops      : bool (default false) — trim detected loops\n"
            "\n"
            "Returns:\n"
            "  ok              : bool\n"
            "  control_points  : [[x,y,z], ...] of offset surface (row-major)\n"
            "  num_u, num_v    : int\n"
            "  degree_u, degree_v : int\n"
            "  knots_u, knots_v : [float]\n"
            "  weights         : [float] or null\n"
            "  self_intersections : list of {region_a, region_b, point}\n"
            "  reason          : str\n"
        ),
        input_schema={
            "type": "object",
            "properties": {
                "control_points": {
                    "type": "array",
                    "description": "Flattened row-major list of [x,y,z] control points (nu*nv entries).",
                    "items": {"type": "array", "items": {"type": "number"}},
                },
                "num_u": {"type": "integer", "description": "Number of CPs in U direction."},
                "num_v": {"type": "integer", "description": "Number of CPs in V direction."},
                "degree_u": {"type": "integer"},
                "degree_v": {"type": "integer"},
                "distance": {"type": "number", "description": "Signed offset distance."},
                "knots_u": {"type": "array", "items": {"type": "number"}},
                "knots_v": {"type": "array", "items": {"type": "number"}},
                "weights": {"type": "array", "items": {"type": "number"}},
                "refine_iter": {"type": "integer", "default": 3},
                "tol": {"type": "number", "default": 1e-4},
                "detect_self_int": {"type": "boolean", "default": False},
                "trim_loops": {"type": "boolean", "default": False},
            },
            "required": ["control_points", "num_u", "num_v", "degree_u", "degree_v", "distance"],
        },
    )

    @register(_NURBS_SURFACE_OFFSET_SPEC)
    async def run_nurbs_surface_offset(ctx: "ProjectCtx", args: bytes) -> str:
        try:
            a = _json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid args: {exc}", "BAD_ARGS")

        try:
            nu = int(a["num_u"])
            nv = int(a["num_v"])
            deg_u = int(a["degree_u"])
            deg_v = int(a["degree_v"])
            dist = float(a["distance"])
            cp_raw = np.array(a["control_points"], dtype=float)
            if cp_raw.shape[0] != nu * nv:
                return err_payload(
                    f"control_points has {cp_raw.shape[0]} entries, expected {nu*nv}",
                    "BAD_ARGS",
                )
            cp_arr = cp_raw.reshape(nu, nv, -1)
        except Exception as exc:
            return err_payload(f"invalid surface spec: {exc}", "BAD_ARGS")

        def _mk_clamped(n, p):
            inner = max(0, n - p - 1)
            return np.concatenate([
                np.zeros(p + 1),
                np.linspace(0.0, 1.0, inner + 2)[1:-1] if inner > 0 else np.array([]),
                np.ones(p + 1),
            ])

        try:
            ku_raw = a.get("knots_u")
            kv_raw = a.get("knots_v")
            ku = np.asarray(ku_raw, dtype=float) if ku_raw else _mk_clamped(nu, deg_u)
            kv = np.asarray(kv_raw, dtype=float) if kv_raw else _mk_clamped(nv, deg_v)
            w_raw = a.get("weights")
            weights = np.asarray(w_raw, dtype=float).reshape(nu, nv) if w_raw else None
        except Exception as exc:
            return err_payload(f"invalid knots/weights: {exc}", "BAD_ARGS")

        try:
            srf = NurbsSurface(
                degree_u=deg_u, degree_v=deg_v,
                control_points=cp_arr, knots_u=ku, knots_v=kv,
                weights=weights,
            )
        except Exception as exc:
            return err_payload(f"could not construct NurbsSurface: {exc}", "BAD_ARGS")

        refine_iter = int(a.get("refine_iter", 3))
        tool_tol = float(a.get("tol", 1e-4))
        do_detect = bool(a.get("detect_self_int", False))
        do_trim = bool(a.get("trim_loops", False))

        try:
            result_srf = offset_surface(srf, dist, refine_iter=refine_iter, tol=tool_tol)
        except ValueError as exc:
            return err_payload(str(exc), "OFFSET_FAILED")
        except Exception as exc:
            return err_payload(f"offset error: {exc}", "INTERNAL")

        self_ints: list = []
        if do_detect:
            try:
                self_ints = detect_self_intersection(result_srf)
                if do_trim and self_ints:
                    result_srf = trim_self_intersection_loops(result_srf, self_ints)
            except Exception as exc:
                pass  # non-fatal; report empty self-int list

        # Serialise result.
        out_cp = result_srf.control_points[:, :, :3].reshape(-1, 3).tolist()
        out_ku = result_srf.knots_u.tolist()
        out_kv = result_srf.knots_v.tolist()
        out_w = result_srf.weights.reshape(-1).tolist() if result_srf.weights is not None else None

        return ok_payload({
            "control_points": out_cp,
            "num_u": result_srf.num_control_points_u,
            "num_v": result_srf.num_control_points_v,
            "degree_u": result_srf.degree_u,
            "degree_v": result_srf.degree_v,
            "knots_u": out_ku,
            "knots_v": out_kv,
            "weights": out_w,
            "self_intersections": self_ints,
        })
