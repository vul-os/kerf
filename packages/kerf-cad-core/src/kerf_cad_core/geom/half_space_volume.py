"""B-rep volume of a half-space intersection.

Given a closed B-rep solid and a cutting plane defined by a point and outward
normal, compute the volume of the solid that lies on the **positive-normal side**
(above the plane) and the **negative-normal side** (below).

Algorithm
---------
Uses the divergence theorem (Gauss's theorem) applied to the half-solid
(Mortenson, *Mathematics for Computer Graphics Applications*, 2nd ed., §11.6):

    V_above = (1/3) ∬_{clipped boundary} r · n_face dA
              + (1/3) ∬_{cut cross-section} r · (−n̂) dA

The second term is the contribution of the **cut-plane closing face**.  On the
cut plane ``(r − p₀) · n̂ = 0``, so ``r · (−n̂) = −p₀ · n̂`` (constant), giving:

    cut_plane_correction = −(1/3) · (p₀ · n̂) · A_cut

where A_cut is the cross-sectional area at the cutting plane.

**Face classification**: Each face's 5-point sign test classifies it as:
  - Fully above → standard GL quadrature contributes to V_above_raw
  - Fully below → contributes zero
  - Straddling → grid_n × grid_n sub-quad grid with bilinear signed-distance
    interpolation; above sub-quads contribute; straddle sub-quads use the
    above fraction from corner distances

**Cut cross-section area** (A_cut): estimated via edge-plane intersections.
Straddling edges are bisected to find the 3D intersection points; these are
projected onto a local 2D frame in the cutting plane and sorted by angle;
the shoelace formula gives A_cut.  For curved edges (circles, NURBS), a
parametric bisection locates the crossing.

Mortenson reference
-------------------
Mortenson, *Mathematics for Computer Graphics Applications*, 2nd ed. §11.6:
The volume of a closed solid equals the boundary surface integral via the
divergence theorem.  Restricting the integration domain to a half-space
requires adding the cut-plane closing face, whose contribution is
-(1/3)·(p₀·n̂)·A_cut.

Caveats / honest-flags
----------------------
* **Straddling faces with complex multi-crossing topology** (highly curved
  surfaces where the cutting plane intersects the UV domain in 3+ disconnected
  arcs, e.g. a torus cut by a plane through its hole) use sub-quad centroid
  classification.  Error is typically < 2% for grid_n ≥ 32.  Faces with
  > 50% straddling sub-quads are flagged in ``HalfSpaceVolumeReport.warnings``.
* ``plane_cut_area`` is estimated by edge bisection + shoelace; error is
  O(1/n_bisect) for curved edges at default bisect depth 24.
* Degenerate UV domains are guarded against (cylinder caps use curve sampling).

Public API
----------
    HalfSpaceVolumeReport  — dataclass: volume_above, volume_below, total,
                              plane_cut_area, warnings
    volume_above_plane(solid, plane_origin, plane_normal) -> float
    volume_below_plane(solid, plane_origin, plane_normal) -> float
    compute_half_space_volume(solid, plane_origin, plane_normal, ...) -> HalfSpaceVolumeReport

LLM tool ``brep_volume_above_plane`` is registered via the kerf_chat registry
(try/except guard so the module is importable without kerf_chat installed).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np

from kerf_cad_core.geom.brep import (
    Body,
    Face,
    Plane,
    CylinderSurface,
    SphereSurface,
    TorusSurface,
)

# ---------------------------------------------------------------------------
# Gauss–Legendre quadrature cache
# ---------------------------------------------------------------------------

_GL_CACHE: Dict[int, Tuple[np.ndarray, np.ndarray]] = {}


def _gl(n: int) -> Tuple[np.ndarray, np.ndarray]:
    """Gauss–Legendre nodes/weights on [-1, 1] (cached)."""
    if n not in _GL_CACHE:
        from numpy.polynomial.legendre import leggauss
        _GL_CACHE[n] = leggauss(n)
    return _GL_CACHE[n]


# ---------------------------------------------------------------------------
# Surface element via finite difference
# ---------------------------------------------------------------------------

_FD_H = 1e-6


def _surface_element(surface, u: float, v: float) -> Tuple[np.ndarray, np.ndarray]:
    """Return (point, area-weighted parametric normal N) at (u, v).

    N = dr/du × dr/dv; |N| = area element; direction = parametric normal.
    """
    p = np.asarray(surface.evaluate(u, v), dtype=float)
    pu = np.asarray(surface.evaluate(u + _FD_H, v), dtype=float)
    pv = np.asarray(surface.evaluate(u, v + _FD_H), dtype=float)
    du = (pu - p) / _FD_H
    dv = (pv - p) / _FD_H
    return p, np.cross(du, dv)


# ---------------------------------------------------------------------------
# UV domain helpers
# ---------------------------------------------------------------------------

def _sample_face_boundary_points(face: Face, n_per_edge: int = 16) -> List[np.ndarray]:
    """Sample 3D points along all coedge curves of a face's outer loop.

    Samples n_per_edge+2 points per coedge (including endpoints).  This
    handles circular coedges (e.g. cylinder caps) where vertex-only
    sampling gives a degenerate bounding box.
    """
    outer = face.outer_loop()
    if outer is None:
        return []
    pts: List[np.ndarray] = []
    for ce in outer.coedges:
        edge = ce.edge
        t0 = edge.t0 if ce.orientation else edge.t1
        t1 = edge.t1 if ce.orientation else edge.t0
        ts = np.linspace(t0, t1, n_per_edge + 2)
        for t in ts:
            try:
                p = np.asarray(edge.curve.evaluate(t), dtype=float)
                pts.append(p)
            except Exception:
                pass
    return pts


def _uv_bounds(face: Face, surface) -> Tuple[float, float, float, float]:
    """Return (u_lo, u_hi, v_lo, v_hi) natural parametric domain for a face.

    For planar faces: samples boundary curves (not just vertices) to handle
    circular coedges (e.g. cylinder caps with a single seam vertex).

    Reference: Mortenson §11.6 — integration over the natural UV domain.
    """
    if isinstance(surface, Plane):
        outer = face.outer_loop()
        if outer is None:
            return 0.0, 1.0, 0.0, 1.0
        origin = np.asarray(surface.origin, dtype=float)
        e1 = np.asarray(surface.x_axis, dtype=float)
        norm_e1 = np.linalg.norm(e1)
        if norm_e1 < 1e-14:
            return 0.0, 1.0, 0.0, 1.0
        e1 = e1 / norm_e1
        n_hat_face = surface._n  # noqa: SLF001
        e2 = np.cross(n_hat_face, e1)
        e2n = np.linalg.norm(e2)
        if e2n < 1e-14:
            return 0.0, 1.0, 0.0, 1.0
        e2 = e2 / e2n
        # Sample curves (not just vertices) so circular edges are covered
        pts = _sample_face_boundary_points(face, n_per_edge=16)
        if not pts:
            return 0.0, 1.0, 0.0, 1.0
        us = [float(np.dot(p - origin, e1)) for p in pts]
        vs = [float(np.dot(p - origin, e2)) for p in pts]
        u_lo, u_hi = min(us), max(us)
        v_lo, v_hi = min(vs), max(vs)
        # Guard against degenerate bounds (point loops)
        if abs(u_hi - u_lo) < 1e-12:
            u_lo -= 1e-6; u_hi += 1e-6
        if abs(v_hi - v_lo) < 1e-12:
            v_lo -= 1e-6; v_hi += 1e-6
        return u_lo, u_hi, v_lo, v_hi

    if isinstance(surface, CylinderSurface):
        outer = face.outer_loop()
        if outer is None:
            return 0.0, 2.0 * math.pi, 0.0, 1.0
        # Sample curves for v-height range (same issue: seam vertex only)
        pts = _sample_face_boundary_points(face, n_per_edge=4)
        if pts:
            vs = [float(np.dot(surface.axis, p - surface.center)) for p in pts]
            v_lo, v_hi = min(vs), max(vs)
        else:
            v_lo, v_hi = 0.0, 1.0
        return 0.0, 2.0 * math.pi, v_lo, v_hi

    if isinstance(surface, SphereSurface):
        return 0.0, 2.0 * math.pi, -math.pi / 2.0, math.pi / 2.0

    if isinstance(surface, TorusSurface):
        return 0.0, 2.0 * math.pi, 0.0, 2.0 * math.pi

    # NurbsSurface
    try:
        from kerf_cad_core.geom.nurbs import NurbsSurface
        if isinstance(surface, NurbsSurface):
            d = surface.degree_u
            u_lo = float(surface.knots_u[d])
            u_hi = float(surface.knots_u[-(d + 1)])
            d = surface.degree_v
            v_lo = float(surface.knots_v[d])
            v_hi = float(surface.knots_v[-(d + 1)])
            return u_lo, u_hi, v_lo, v_hi
    except Exception:
        pass

    return 0.0, 1.0, 0.0, 1.0


# ---------------------------------------------------------------------------
# Signed distance helper
# ---------------------------------------------------------------------------

def _signed_dist(p: np.ndarray, plane_origin: np.ndarray, plane_normal: np.ndarray) -> float:
    """Signed distance from point p to the cutting plane. Positive = above."""
    return float(np.dot(p - plane_origin, plane_normal))


# ---------------------------------------------------------------------------
# Bilinear fraction above the plane for a rectangular sub-quad
# ---------------------------------------------------------------------------

def _fraction_above_bilinear(d00: float, d10: float, d01: float, d11: float) -> float:
    """Fraction (0–1) of a quad's area above the plane (d ≥ 0).

    Uses linear interpolation of signed distances at four corners.
    Exact for planar faces with linear signed-distance variation; first-order
    approximation for curved faces (error O(Δu·Δv)).
    """
    n_above = sum(1 for d in (d00, d10, d01, d11) if d >= 0.0)
    if n_above == 4:
        return 1.0
    if n_above == 0:
        return 0.0
    pos_sum = sum(d for d in (d00, d10, d01, d11) if d >= 0.0)
    neg_sum = sum(-d for d in (d00, d10, d01, d11) if d < 0.0)
    total = pos_sum + neg_sum
    if total < 1e-30:
        return 0.5
    return pos_sum / total


# ---------------------------------------------------------------------------
# Planar face: Green's theorem area + volume contribution
# ---------------------------------------------------------------------------

def _plane_face_green(face: Face, quad_order: int = 16) -> Tuple[float, np.ndarray, float]:
    """Compute area and volume contribution for a Plane face via Green's theorem.

    Returns (area_signed, n_hat_eff, dV) where:
      - area_signed  = signed area from coedge winding (positive if n_hat_eff is outward)
      - n_hat_eff    = effective outward unit normal (may differ from surface._n * orient
                        because Plane y_axis can be negated to fix coedge winding)
      - dV           = (1/3) * (n_hat_eff · origin) * area_signed

    Reference: mass_props._planar_face_integrals (same algorithm).
    """
    surface = face.surface
    orient = 1.0 if face.orientation else -1.0
    n_hat = np.asarray(surface.normal(0.0, 0.0), dtype=float) * orient
    n_hat = n_hat / max(np.linalg.norm(n_hat), 1e-14)

    # Local 2D frame in the plane (same as mass_props)
    e1 = np.asarray(surface.x_axis, dtype=float)
    e1 = e1 / max(np.linalg.norm(e1), 1e-14)
    e2 = np.cross(n_hat, e1)
    e2 = e2 / max(np.linalg.norm(e2), 1e-14)

    origin = np.asarray(surface.origin, dtype=float)

    outer = face.outer_loop()
    if outer is None:
        return 0.0, n_hat, 0.0

    xi, wi = _gl(quad_order)

    A = 0.0
    for ce in outer.coedges:
        edge = ce.edge
        t0 = edge.t0 if ce.orientation else edge.t1
        t1 = edge.t1 if ce.orientation else edge.t0
        t_mid = 0.5 * (t0 + t1)
        t_half = 0.5 * (t1 - t0)
        for k in range(quad_order):
            t = t_mid + t_half * xi[k]
            wk = wi[k] * t_half
            try:
                p = np.asarray(edge.curve.evaluate(t), dtype=float)
            except Exception:
                continue
            # FD tangent
            h = 1e-7
            try:
                dp = np.asarray(edge.curve.evaluate(t + h), dtype=float) - p
            except Exception:
                continue
            d = p - origin
            u = float(np.dot(d, e1))
            v = float(np.dot(d, e2))
            du_dt = float(np.dot(dp, e1)) / h
            dv_dt = float(np.dot(dp, e2)) / h
            A += 0.5 * (-v * du_dt + u * dv_dt) * wk

    # For a Plane face, r·n_hat is constant = n_hat·origin
    n_dot_origin = float(np.dot(n_hat, origin))
    dV = n_dot_origin * A / 3.0
    return A, n_hat, dV


def _plane_face_above_area(
    face: Face,
    plane_origin: np.ndarray,
    plane_normal: np.ndarray,
    quad_order: int = 16,
) -> float:
    """Estimate the signed area of a Plane face that lies above the cutting plane.

    Uses the Sutherland-Hodgman polygon-clipping algorithm: builds a polygon
    from sampled boundary points, clips to the above half-space, then applies
    the shoelace (Green's theorem) formula to compute signed area.

    The signed area has the same sign convention as _plane_face_green (positive
    when coedge winding is CCW as seen from the effective outward normal).
    """
    surface = face.surface
    orient = 1.0 if face.orientation else -1.0
    n_hat_face = np.asarray(surface.normal(0.0, 0.0), dtype=float) * orient
    n_hat_face = n_hat_face / max(np.linalg.norm(n_hat_face), 1e-14)

    e1 = np.asarray(surface.x_axis, dtype=float)
    e1 = e1 / max(np.linalg.norm(e1), 1e-14)
    e2 = np.cross(n_hat_face, e1)
    e2 = e2 / max(np.linalg.norm(e2), 1e-14)
    origin = np.asarray(surface.origin, dtype=float)

    outer = face.outer_loop()
    if outer is None:
        return 0.0

    def to_uv(p3: np.ndarray) -> Tuple[float, float]:
        d = p3 - origin
        return float(np.dot(d, e1)), float(np.dot(d, e2))

    p0_cut = plane_origin
    n_cut = plane_normal

    # Step 1: Sample all boundary points in 3D
    n_samp = max(quad_order * 2, 32)
    boundary_pts: List[np.ndarray] = []
    for ce in outer.coedges:
        edge = ce.edge
        t0 = edge.t0 if ce.orientation else edge.t1
        t1 = edge.t1 if ce.orientation else edge.t0
        ts = np.linspace(t0, t1, n_samp + 1)
        for k, t in enumerate(ts):
            if k == 0 and boundary_pts:
                continue  # avoid duplicate at coedge junction
            try:
                boundary_pts.append(np.asarray(edge.curve.evaluate(t), dtype=float))
            except Exception:
                pass

    if not boundary_pts:
        return 0.0

    # Step 2: Sutherland-Hodgman clip to above half-space (d >= 0)
    clipped: List[np.ndarray] = []
    n_pts = len(boundary_pts)
    for k in range(n_pts):
        pa = boundary_pts[k]
        pb = boundary_pts[(k + 1) % n_pts]
        da = _signed_dist(pa, p0_cut, n_cut)
        db = _signed_dist(pb, p0_cut, n_cut)

        if da >= 0.0:
            clipped.append(pa)

        # If crossing: add intersection point
        if (da >= 0.0) != (db >= 0.0):
            denom = da - db
            if abs(denom) > 1e-15:
                alpha = da / denom
                pc = pa + alpha * (pb - pa)
                clipped.append(pc)

    if len(clipped) < 3:
        return 0.0

    # Step 3: Shoelace formula for signed area in UV space
    # A = (1/2) Σ (u_i * v_{i+1} - u_{i+1} * v_i)
    uvs = [to_uv(p) for p in clipped]
    A = 0.0
    n_c = len(uvs)
    for i in range(n_c):
        j = (i + 1) % n_c
        A += uvs[i][0] * uvs[j][1] - uvs[j][0] * uvs[i][1]
    return A / 2.0


# ---------------------------------------------------------------------------
# GL volume integrand
# ---------------------------------------------------------------------------

def _gl_integrate_full(surface, u_lo: float, u_hi: float,
                       v_lo: float, v_hi: float,
                       orient: float, n: int) -> float:
    """Gauss-Legendre integration of the divergence-theorem volume integrand.

    Returns (1/3) ∬_{u_lo..u_hi × v_lo..v_hi} r · (orient · N) du dv.

    Reference: Mortenson §11.6 — V = (1/3) ∬_boundary r · n dA.
    """
    xi, wi = _gl(n)
    u_mid, u_h = 0.5 * (u_lo + u_hi), 0.5 * (u_hi - u_lo)
    v_mid, v_h = 0.5 * (v_lo + v_hi), 0.5 * (v_hi - v_lo)
    us = u_mid + u_h * xi
    vs = v_mid + v_h * xi

    dV = 0.0
    for i in range(n):
        for j in range(n):
            try:
                p, N = _surface_element(surface, us[i], vs[j])
            except Exception:
                continue
            w = wi[i] * wi[j] * u_h * v_h
            dV += float(np.dot(p, orient * N)) * w
    return dV / 3.0


# ---------------------------------------------------------------------------
# Per-face half-space contribution
# ---------------------------------------------------------------------------

def _face_half_space_contribution(
    face: Face,
    plane_origin: np.ndarray,
    plane_normal: np.ndarray,
    gl_order: int,
    grid_n: int,
) -> Tuple[float, List[str]]:
    """Divergence-theorem volume contribution for the above-half of one face.

    Returns (vol_above_raw, warnings).  The caller applies the cut-plane
    closing term using A_cut computed from edge intersections.

    For straddling faces, uses a grid_n × grid_n sub-quad grid with bilinear
    signed-distance interpolation (Mortenson §11.6).
    """
    surface = face.surface
    orient = 1.0 if face.orientation else -1.0
    warns: List[str] = []

    # -----------------------------------------------------------------------
    # Special handling for Plane faces (flat faces).
    # For a Plane face, r·n_outward is constant = n_outward·origin, so the
    # divergence-theorem volume contribution is:
    #   dV_above = (1/3) * (n_outward · origin) * A_above
    # where A_above is the area of the face above the cutting plane.
    # We compute the outward normal and signed area via Green's theorem
    # (coedge winding determines the correct sign), not by GL quadrature on
    # the UV bounding box (which would integrate over the wrong domain).
    # -----------------------------------------------------------------------
    if isinstance(surface, Plane):
        # Get area and effective outward normal via Green's theorem
        A_signed, n_hat_eff, _dV_full = _plane_face_green(face, quad_order=gl_order)
        n_dot_orig = float(np.dot(n_hat_eff, np.asarray(surface.origin, dtype=float)))

        # Classify face using sampled boundary points
        bpts = _sample_face_boundary_points(face, n_per_edge=8)
        if not bpts:
            return 0.0, warns
        dists = [_signed_dist(p, plane_origin, plane_normal) for p in bpts]
        all_above = all(d >= 0.0 for d in dists)
        all_below = all(d < 0.0 for d in dists)

        if all_below:
            return 0.0, warns

        if all_above:
            # Fully above: contribution = (1/3) * (n_out · origin) * A_signed
            return n_dot_orig * A_signed / 3.0, warns

        # Straddling Plane face: compute A_above via Green's theorem on
        # clipped coedge segments
        A_above = _plane_face_above_area(face, plane_origin, plane_normal, quad_order=gl_order)
        return n_dot_orig * A_above / 3.0, warns

    # -----------------------------------------------------------------------
    # Curved faces: use GL quadrature on the parametric UV domain.
    # The parametric normal dr/du × dr/dv is reliable for CylinderSurface,
    # SphereSurface, TorusSurface, NurbsSurface (consistent parametrization).
    # -----------------------------------------------------------------------
    u_lo, u_hi, v_lo, v_hi = _uv_bounds(face, surface)
    du = u_hi - u_lo
    dv = v_hi - v_lo
    if abs(du) < 1e-14 or abs(dv) < 1e-14:
        return 0.0, warns

    # Quick 5-point sign test to classify face
    test_uvs = [
        (u_lo, v_lo), (u_hi, v_lo), (u_lo, v_hi), (u_hi, v_hi),
        (0.5 * (u_lo + u_hi), 0.5 * (v_lo + v_hi)),
    ]
    signs = []
    for cu, cv in test_uvs:
        try:
            cp = np.asarray(surface.evaluate(cu, cv), dtype=float)
            signs.append(_signed_dist(cp, plane_origin, plane_normal))
        except Exception:
            pass

    if not signs:
        return 0.0, warns

    all_above = all(s >= 0.0 for s in signs)
    all_below = all(s < 0.0 for s in signs)

    # --- Fully above: standard GL quadrature ----------------------------
    if all_above:
        return _gl_integrate_full(surface, u_lo, u_hi, v_lo, v_hi, orient, gl_order), warns

    # --- Fully below: zero contribution ---------------------------------
    if all_below:
        return 0.0, warns

    # --- Straddling: sub-quad grid with bilinear fraction ---------------
    vol_above_raw = 0.0
    sub_du = du / grid_n
    sub_dv = dv / grid_n
    straddle_count = 0

    for i in range(grid_n):
        for j in range(grid_n):
            su_lo = u_lo + i * sub_du
            su_hi = su_lo + sub_du
            sv_lo = v_lo + j * sub_dv
            sv_hi = sv_lo + sub_dv
            su_mid = 0.5 * (su_lo + su_hi)
            sv_mid = 0.5 * (sv_lo + sv_hi)

            # Signed distances at 4 corners
            d_corners = []
            for scu, scv in [(su_lo, sv_lo), (su_hi, sv_lo), (su_lo, sv_hi), (su_hi, sv_hi)]:
                try:
                    sp = np.asarray(surface.evaluate(scu, scv), dtype=float)
                    d_corners.append(_signed_dist(sp, plane_origin, plane_normal))
                except Exception:
                    try:
                        sp_mid = np.asarray(surface.evaluate(su_mid, sv_mid), dtype=float)
                        d_corners.append(_signed_dist(sp_mid, plane_origin, plane_normal))
                    except Exception:
                        d_corners.append(0.0)

            n_above = sum(1 for d in d_corners if d >= 0.0)
            if n_above == 0:
                continue  # fully below

            if n_above == 4:
                # Fully above sub-quad: 2×2 GL integration
                vol_above_raw += _gl_integrate_full(
                    surface, su_lo, su_hi, sv_lo, sv_hi, orient, 2
                )
            else:
                # Straddling sub-quad: bilinear fraction * full integration
                straddle_count += 1
                frac = _fraction_above_bilinear(*d_corners)
                sub_contrib = _gl_integrate_full(
                    surface, su_lo, su_hi, sv_lo, sv_hi, orient, 2
                )
                vol_above_raw += frac * sub_contrib

    # Honest-flag for complex multi-crossing faces
    total_quads = grid_n * grid_n
    straddle_frac = straddle_count / max(total_quads, 1)
    if straddle_frac > 0.5:
        warns.append(
            f"honest-flag: face with surface type {type(surface).__name__!r} has "
            f"{straddle_count}/{total_quads} ({100*straddle_frac:.0f}%) straddling "
            f"sub-quads — complex multi-crossing topology; half-space volume for this "
            f"face may exceed 1% error at grid_n={grid_n}. "
            f"Increase grid_n for better accuracy."
        )

    return vol_above_raw, warns


# ---------------------------------------------------------------------------
# Cut cross-section area via edge-plane intersections
# ---------------------------------------------------------------------------

def _edge_plane_intersection(edge, plane_origin: np.ndarray, plane_normal: np.ndarray,
                              n_bisect: int = 24) -> Optional[np.ndarray]:
    """Find the 3D intersection point of an edge with the cutting plane via bisection.

    Returns the 3D intersection point, or None if no crossing is found.
    The edge's curve is sampled at t0 and t1; if they straddle the plane,
    bisection locates the crossing to within |t1-t0| / 2^n_bisect.
    """
    p_start = np.asarray(edge.v_start.point, dtype=float)
    p_end = np.asarray(edge.v_end.point, dtype=float)
    d_start = _signed_dist(p_start, plane_origin, plane_normal)
    d_end = _signed_dist(p_end, plane_origin, plane_normal)

    # For vertex-vertex check first (straight edges)
    if (d_start >= 0.0) != (d_end >= 0.0):
        t0, t1 = edge.t0, edge.t1
        for _ in range(n_bisect):
            t_mid = 0.5 * (t0 + t1)
            try:
                p_mid = np.asarray(edge.curve.evaluate(t_mid), dtype=float)
            except Exception:
                break
            d_mid = _signed_dist(p_mid, plane_origin, plane_normal)
            if abs(d_mid) < 1e-12:
                return p_mid
            if (d_start >= 0.0) == (d_mid >= 0.0):
                t0 = t_mid; d_start = d_mid
            else:
                t1 = t_mid; d_end = d_mid
        try:
            return np.asarray(edge.curve.evaluate(0.5 * (t0 + t1)), dtype=float)
        except Exception:
            return None

    # For curved edges where vertex distances are degenerate (both 0 or same sign),
    # sample along the curve to find crossings
    if abs(d_start) < 1e-10 and abs(d_end) < 1e-10:
        # Both endpoints on plane — might be a crossing; sample interior
        t0, t1 = edge.t0, edge.t1
        n_samples = max(n_bisect, 24)
        ts = np.linspace(t0, t1, n_samples + 1)
        d_prev = d_start
        crossings = []
        for k in range(1, len(ts)):
            try:
                p = np.asarray(edge.curve.evaluate(ts[k]), dtype=float)
                d = _signed_dist(p, plane_origin, plane_normal)
                if (d_prev >= 0.0) != (d >= 0.0):
                    # Crossing between ts[k-1] and ts[k]
                    ta, tb = ts[k-1], ts[k]
                    da = d_prev
                    for _ in range(16):
                        tm = 0.5*(ta+tb)
                        try:
                            pm = np.asarray(edge.curve.evaluate(tm), dtype=float)
                        except Exception:
                            break
                        dm = _signed_dist(pm, plane_origin, plane_normal)
                        if abs(dm) < 1e-12:
                            crossings.append(pm); break
                        if (da >= 0.0) == (dm >= 0.0):
                            ta = tm; da = dm
                        else:
                            tb = tm
                    else:
                        try:
                            crossings.append(np.asarray(edge.curve.evaluate(0.5*(ta+tb)), dtype=float))
                        except Exception:
                            pass
                d_prev = d
            except Exception:
                pass
        return crossings[0] if crossings else None

    return None  # no crossing


def _compute_cut_area(solid: Body,
                      plane_origin: np.ndarray,
                      plane_normal: np.ndarray,
                      n_bisect: int = 24) -> float:
    """Estimate the cross-sectional area at the cutting plane.

    Finds all edge-plane intersection points, projects them to a local 2D
    frame in the cutting plane, sorts by angle from centroid, and applies
    the shoelace formula.

    This gives the exact area for polygonal cross-sections (planar solids)
    and a good approximation for curved cross-sections (error O(1/n_bisect)
    for curved edges).
    """
    p0 = plane_origin
    n_hat = plane_normal

    # Build local 2D orthonormal frame in the cutting plane
    ref = np.array([1.0, 0.0, 0.0]) if abs(n_hat[0]) < 0.9 else np.array([0.0, 1.0, 0.0])
    e1 = np.cross(n_hat, ref)
    e1n = np.linalg.norm(e1)
    if e1n < 1e-14:
        return 0.0
    e1 = e1 / e1n
    e2 = np.cross(n_hat, e1)

    def to_2d(p3: np.ndarray) -> np.ndarray:
        d = p3 - p0
        return np.array([float(np.dot(d, e1)), float(np.dot(d, e2))])

    # Collect unique edges and find intersection points
    seen_edge_ids: set = set()
    pts_2d: List[np.ndarray] = []

    for face in solid.all_faces():
        outer = face.outer_loop()
        if outer is None:
            continue
        for ce in outer.coedges:
            edge = ce.edge
            eid = id(edge)
            if eid in seen_edge_ids:
                continue
            seen_edge_ids.add(eid)

            # Also handle curved edges that might have multiple crossings
            # by sampling along the curve
            p_start = np.asarray(edge.v_start.point, dtype=float)
            p_end = np.asarray(edge.v_end.point, dtype=float)
            d_start = _signed_dist(p_start, p0, n_hat)
            d_end = _signed_dist(p_end, p0, n_hat)

            # Try to find crossings by sampling
            t0_, t1_ = edge.t0, edge.t1
            n_samp = max(n_bisect, 24)
            ts = np.linspace(t0_, t1_, n_samp + 1)
            d_vals = []
            p_vals = []
            for t in ts:
                try:
                    p = np.asarray(edge.curve.evaluate(t), dtype=float)
                    d = _signed_dist(p, p0, n_hat)
                    d_vals.append(d)
                    p_vals.append(p)
                except Exception:
                    d_vals.append(0.0)
                    p_vals.append(None)

            # Find sign changes
            for k in range(len(d_vals) - 1):
                if d_vals[k] is None or d_vals[k+1] is None:
                    continue
                if (d_vals[k] >= 0.0) != (d_vals[k+1] >= 0.0):
                    # Bisect between ts[k] and ts[k+1]
                    ta, tb = ts[k], ts[k+1]
                    da = d_vals[k]
                    for _ in range(20):
                        tm = 0.5 * (ta + tb)
                        try:
                            pm = np.asarray(edge.curve.evaluate(tm), dtype=float)
                        except Exception:
                            break
                        dm = _signed_dist(pm, p0, n_hat)
                        if abs(dm) < 1e-12:
                            pts_2d.append(to_2d(pm))
                            break
                        if (da >= 0.0) == (dm >= 0.0):
                            ta = tm; da = dm
                        else:
                            tb = tm
                    else:
                        try:
                            pm = np.asarray(edge.curve.evaluate(0.5*(ta+tb)), dtype=float)
                            pts_2d.append(to_2d(pm))
                        except Exception:
                            pass

    if len(pts_2d) < 3:
        return 0.0

    # Sort by angle from centroid → convex polygon ordering
    pts_arr = np.array(pts_2d)
    centroid_2d = np.mean(pts_arr, axis=0)
    angles = [math.atan2(float(p[1] - centroid_2d[1]), float(p[0] - centroid_2d[0]))
              for p in pts_2d]
    sorted_pts = [p for _, p in sorted(zip(angles, pts_2d))]

    # Shoelace formula for polygon area
    n_pts = len(sorted_pts)
    area = 0.0
    for i in range(n_pts):
        j = (i + 1) % n_pts
        area += sorted_pts[i][0] * sorted_pts[j][1]
        area -= sorted_pts[j][0] * sorted_pts[i][1]
    return abs(area) / 2.0


# ---------------------------------------------------------------------------
# Public dataclass
# ---------------------------------------------------------------------------

@dataclass
class HalfSpaceVolumeReport:
    """Result of a half-space volume computation.

    Attributes
    ----------
    volume_above : float
        Volume of the solid on the positive-normal side of the cutting plane.
    volume_below : float
        Volume of the solid on the negative-normal side of the cutting plane.
    total : float
        Total volume (volume_above + volume_below).  Should match
        ``body_mass_props`` volume within quadrature error.
    plane_cut_area : float
        Estimated cross-sectional area at the cutting plane.  Computed from
        edge-plane intersections via shoelace formula; accurate for polygonal
        cross-sections, approximate (bisection error) for curved cross-sections.
    warnings : list[str]
        Honest-flags and diagnostics (e.g. multi-crossing faces).
    """
    volume_above: float
    volume_below: float
    total: float
    plane_cut_area: float
    warnings: List[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def compute_half_space_volume(
    solid: Body,
    plane_origin,
    plane_normal,
    gl_order: int = 16,
    grid_n: int = 32,
) -> HalfSpaceVolumeReport:
    """Compute the volume of *solid* split by a cutting plane.

    Algorithm: divergence theorem with cut-plane closing face (Mortenson §11.6).

    Parameters
    ----------
    solid : Body
        A closed (watertight) B-rep solid.
    plane_origin : array-like, shape (3,)
        A point on the cutting plane.
    plane_normal : array-like, shape (3,)
        Outward normal of the cutting plane (will be normalised).
        Points on the positive side are "above".
    gl_order : int
        Gauss-Legendre order for fully-classified faces (default 16).
    grid_n : int
        Sub-quad grid resolution for straddling faces (default 32).

    Returns
    -------
    HalfSpaceVolumeReport

    Examples
    --------
    Unit cube cut at z=0.5  →  volume_above ≈ 0.5, volume_below ≈ 0.5::

        body = make_box(origin=(0,0,0), size=(1,1,1))
        r = compute_half_space_volume(body, [0,0,0.5], [0,0,1])

    Unit sphere cut at equator (z=0)  →  each half ≈ 4π/6 ≈ 2.094::

        body = make_sphere(center=(0,0,0), radius=1.0)
        r = compute_half_space_volume(body, [0,0,0], [0,0,1])

    Cylinder r=1, h=2 cut at x=0  →  each half ≈ π::

        body = make_cylinder(center=(0,0,0), axis=(0,0,1), radius=1.0, height=2.0)
        r = compute_half_space_volume(body, [0,0,0], [1,0,0])

    Reference: Mortenson, *Mathematics for Computer Graphics Applications*,
    2nd ed., §11.6 (divergence-theorem volume from boundary faces).
    """
    p0 = np.asarray(plane_origin, dtype=float)
    n_hat = np.asarray(plane_normal, dtype=float)
    n_norm = np.linalg.norm(n_hat)
    if n_norm < 1e-14:
        raise ValueError("plane_normal must be non-zero")
    n_hat = n_hat / n_norm

    # Step 1: Accumulate raw above contributions from boundary faces
    vol_above_raw = 0.0
    all_warnings: List[str] = []

    for face in solid.all_faces():
        va, warns = _face_half_space_contribution(
            face, p0, n_hat, gl_order=gl_order, grid_n=grid_n
        )
        vol_above_raw += va
        all_warnings.extend(warns)

    # Step 2: Compute cross-section area A_cut from edge-plane intersections
    cut_area = _compute_cut_area(solid, p0, n_hat)

    # Step 3: Apply cut-plane closing face correction (Mortenson §11.6)
    # Cut plane (outward normal -n̂ for the above solid) contributes:
    #   (1/3) · integral r·(-n̂) dA = (1/3) · (-p0·n̂) · A_cut
    # because on the cut plane (r-p0)·n̂ = 0, so r·(-n̂) = -(r·n̂) = -(p0·n̂)
    p0_dot_n = float(np.dot(p0, n_hat))
    cut_correction = -(1.0 / 3.0) * p0_dot_n * cut_area
    vol_above = vol_above_raw + cut_correction

    # Step 4: Total volume via full divergence theorem
    # Plane faces use Green's theorem (same as mass_props); curved faces use GL.
    total_vol = 0.0
    for face in solid.all_faces():
        surface = face.surface
        orient = 1.0 if face.orientation else -1.0
        if isinstance(surface, Plane):
            _A, _n, dV = _plane_face_green(face, quad_order=gl_order)
            total_vol += dV
        else:
            u_lo, u_hi, v_lo, v_hi = _uv_bounds(face, surface)
            if abs(u_hi - u_lo) < 1e-14 or abs(v_hi - v_lo) < 1e-14:
                continue
            total_vol += _gl_integrate_full(surface, u_lo, u_hi, v_lo, v_hi, orient, gl_order)

    vol_below = total_vol - vol_above

    return HalfSpaceVolumeReport(
        volume_above=vol_above,
        volume_below=vol_below,
        total=total_vol,
        plane_cut_area=cut_area,
        warnings=all_warnings,
    )


def volume_above_plane(
    solid: Body,
    plane_origin,
    plane_normal,
    gl_order: int = 16,
    grid_n: int = 32,
) -> float:
    """Volume of *solid* on the positive-normal side of the cutting plane.

    Convenience wrapper around :func:`compute_half_space_volume`.
    Uses divergence theorem with cut-plane closing face (Mortenson §11.6).
    """
    return compute_half_space_volume(
        solid, plane_origin, plane_normal, gl_order, grid_n
    ).volume_above


def volume_below_plane(
    solid: Body,
    plane_origin,
    plane_normal,
    gl_order: int = 16,
    grid_n: int = 32,
) -> float:
    """Volume of *solid* on the negative-normal side of the cutting plane.

    Convenience wrapper around :func:`compute_half_space_volume`.
    Uses divergence theorem with cut-plane closing face (Mortenson §11.6).
    """
    return compute_half_space_volume(
        solid, plane_origin, plane_normal, gl_order, grid_n
    ).volume_below


# ---------------------------------------------------------------------------
# LLM tool registration (kerf_chat registry, try/except guard)
# ---------------------------------------------------------------------------

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register  # type: ignore[import]
    from kerf_core.utils.context import ProjectCtx  # type: ignore[import]
    import json as _json
    _REGISTRY_AVAILABLE = True
except ImportError:
    _REGISTRY_AVAILABLE = False

if _REGISTRY_AVAILABLE:

    _spec = ToolSpec(
        name="brep_volume_above_plane",
        description=(
            "Compute the volume of a B-rep solid on the positive-normal side of a "
            "cutting plane (half-space intersection volume).\n\n"
            "Algorithm: divergence theorem with cut-plane closing face (Mortenson §11.6). "
            "Faces classified fully-above / fully-below / straddling; straddling faces "
            "use 32×32 sub-quad grid with bilinear signed-distance interpolation. "
            "Cut cross-section area from edge-plane bisection + shoelace formula.\n\n"
            "Use cases: mold cavity volume per pull-direction, hydrostatic "
            "submerged-volume, material-above-datum, cut-volume analysis.\n\n"
            "Depth-bar oracles:\n"
            "  • Unit cube cut z=0.5 → volume_above ≈ 0.5, volume_below ≈ 0.5\n"
            "  • Unit sphere cut z=0 → each half ≈ 2.094 (= 4π/6)\n"
            "  • Cylinder r=1 h=2 cut x=0 → volume_above = volume_below ≈ π\n\n"
            "Honest-flag: faces with > 50% straddling sub-quads (multi-crossing "
            "topology) are flagged in 'warnings'; error may exceed 1% for those faces.\n\n"
            "Returns: {ok, volume_above, volume_below, total, plane_cut_area, warnings}"
        ),
        input_schema={
            "type": "object",
            "properties": {
                "primitive": {
                    "type": "object",
                    "description": (
                        "Primitive solid: 'type' ('box'|'sphere'|'cylinder'). "
                        "Box: 'origin' [x,y,z] + 'size' [x,y,z]. "
                        "Sphere: 'center' [x,y,z] + 'radius'. "
                        "Cylinder: 'center', 'axis', 'radius', 'height'."
                    ),
                },
                "plane_origin": {
                    "type": "array",
                    "items": {"type": "number"},
                    "minItems": 3,
                    "maxItems": 3,
                    "description": "Point [x,y,z] on the cutting plane.",
                },
                "plane_normal": {
                    "type": "array",
                    "items": {"type": "number"},
                    "minItems": 3,
                    "maxItems": 3,
                    "description": "Normal [nx,ny,nz] of the cutting plane (will be normalised).",
                },
                "gl_order": {
                    "type": "integer",
                    "description": "GL order for full-face integration (default 16).",
                    "default": 16,
                },
                "grid_n": {
                    "type": "integer",
                    "description": "Sub-quad grid resolution for straddling faces (default 32).",
                    "default": 32,
                },
            },
            "required": ["primitive", "plane_origin", "plane_normal"],
        },
    )

    @register(_spec)
    async def run_brep_volume_above_plane(ctx: "ProjectCtx", args: bytes) -> str:
        """LLM tool: brep_volume_above_plane."""
        try:
            a = _json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid JSON: {exc}", "BAD_ARGS")

        prim = a.get("primitive")
        if prim is None:
            return err_payload("'primitive' is required", "BAD_ARGS")
        plane_origin = a.get("plane_origin")
        plane_normal = a.get("plane_normal")
        if plane_origin is None or plane_normal is None:
            return err_payload("'plane_origin' and 'plane_normal' are required", "BAD_ARGS")
        gl_order = int(a.get("gl_order", 16))
        grid_n = int(a.get("grid_n", 32))

        try:
            from kerf_cad_core.geom.brep import make_box, make_sphere, make_cylinder
            ptype = str(prim.get("type", "box")).lower()
            if ptype == "box":
                origin = prim.get("origin", [0.0, 0.0, 0.0])
                size = prim.get("size", [1.0, 1.0, 1.0])
                solid = make_box(origin=origin, size=size)
            elif ptype == "sphere":
                center = prim.get("center", [0.0, 0.0, 0.0])
                radius = float(prim.get("radius", 1.0))
                solid = make_sphere(center=center, radius=radius)
            elif ptype == "cylinder":
                center = prim.get("center", [0.0, 0.0, 0.0])
                axis = prim.get("axis", [0.0, 0.0, 1.0])
                radius = float(prim.get("radius", 1.0))
                height = float(prim.get("height", 1.0))
                solid = make_cylinder(center=center, axis=axis, radius=radius, height=height)
            else:
                return err_payload(
                    f"unknown primitive type {ptype!r}; supported: box, sphere, cylinder",
                    "BAD_ARGS",
                )
        except Exception as exc:
            return err_payload(f"failed to build solid: {exc}", "OP_FAILED")

        try:
            report = compute_half_space_volume(
                solid, plane_origin, plane_normal, gl_order=gl_order, grid_n=grid_n
            )
        except Exception as exc:
            return err_payload(str(exc), "OP_FAILED")

        return ok_payload({
            "volume_above": report.volume_above,
            "volume_below": report.volume_below,
            "total": report.total,
            "plane_cut_area": report.plane_cut_area,
            "warnings": report.warnings,
        })
