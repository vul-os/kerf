"""
intersection_degen.py
=====================
Degenerate elliptic surface-surface intersection (SSI) — coplanar quadric
intersections, tangent contacts, coaxial cylinders.

Reference: Patrikalakis & Maekawa §5.4 — degenerate intersection types via
Legendre / Weierstrass canonical forms.

Public API
----------
detect_degenerate_ssi(srf_a, srf_b, tol=1e-6) -> DegenerateSSIType
    Classify the surface pair before marching.  Returns one of:
        'coaxial_cylinders'    — same or different radii, shared axis
        'coplanar_planes'      — both surfaces are coincident planes
        'sphere_tangent_plane' — sphere just touches a plane
        'cone_apex_match'      — two cones sharing the apex (structural flag)
        'tangent_quadric_pair' — two quadrics tangent along a conic
        'generic'              — no degenerate configuration detected

compute_degenerate_ssi_curve(srf_a, srf_b, kind) -> list[dict]
    Compute the intersection analytically for a classified degenerate pair.
    Returns branch dicts compatible with surface_surface_intersect output.

ssi_extended(srf_a, srf_b, *, tol, **kw) -> dict
    Drop-in replacement for surface_surface_intersect.  Detects degenerate
    cases first; falls back to the hardened marching SSI for 'generic'.

All functions are pure-Python + NumPy.  Never raises.
"""

from __future__ import annotations

import math
from typing import List, Optional, Tuple

import numpy as np

# ---------------------------------------------------------------------------
# Type alias
# ---------------------------------------------------------------------------

DegenerateSSIType = str  # one of the string literals above

_DEGEN_KINDS = frozenset({
    "coaxial_cylinders",
    "coplanar_planes",
    "sphere_tangent_plane",
    "cone_apex_match",
    "tangent_quadric_pair",
    "generic",
})

# ---------------------------------------------------------------------------
# Reuse primitive recognition from intersection.py
# ---------------------------------------------------------------------------

from kerf_cad_core.geom.intersection import (  # noqa: E402
    _classify_primitive,
    _sample_surface_grid,
    _fit_plane,
    _fit_sphere,
    _fit_cylinder,
    _PRIM_FIT_TOL,
    _circle_polyline,
    _surface_param_range,
    surface_surface_intersect as _generic_ssi,
)
from kerf_cad_core.geom.nurbs import NurbsSurface  # noqa: E402


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _unit(v: np.ndarray) -> np.ndarray:
    n = np.linalg.norm(v)
    return v / n if n > 1e-300 else v


def _fit_cylinder_robust(
    pts: np.ndarray,
) -> Optional[Tuple[np.ndarray, np.ndarray, float, float]]:
    """Robust cylinder fit: tries all three SVD directions as axis candidates.

    The standard _fit_cylinder from intersection.py uses vh[0] (largest
    singular vector) as the axis candidate.  This works when the cylinder is
    elongated (half_len >> radius), but fails when the cylinder is compact
    (half_len ~ radius) because the maximum-variance direction becomes radial.

    This function tries all three SVD right-singular vectors and returns the
    fit with the smallest residual.

    Returns (axis_point, unit_axis_dir, radius, max_abs_residual) or None.
    """
    if pts.shape[0] < 6:
        return None
    c = pts.mean(axis=0)
    q = pts - c
    try:
        _, sv, vh = np.linalg.svd(q, full_matrices=False)
    except np.linalg.LinAlgError:
        return None

    best: Optional[Tuple[np.ndarray, np.ndarray, float, float]] = None

    for i in range(3):
        axis = vh[i]
        axis = axis / (np.linalg.norm(axis) + 1e-300)
        # Project points onto the plane perpendicular to the candidate axis.
        proj = q - np.outer(q @ axis, axis)
        # Build an orthonormal 2-D basis in that plane.
        e1 = vh[(i + 1) % 3] - (vh[(i + 1) % 3] @ axis) * axis
        nrm_e1 = np.linalg.norm(e1)
        if nrm_e1 < 1e-14:
            continue
        e1 = e1 / nrm_e1
        e2 = np.cross(axis, e1)
        x = proj @ e1
        y = proj @ e2
        M = np.column_stack([2.0 * x, 2.0 * y, np.ones_like(x)])
        rhs = x * x + y * y
        try:
            sol, *_ = np.linalg.lstsq(M, rhs, rcond=None)
        except np.linalg.LinAlgError:
            continue
        cx2, cy2 = sol[0], sol[1]
        r2 = sol[2] + cx2 * cx2 + cy2 * cy2
        if r2 <= 1e-18:
            continue
        radius = math.sqrt(r2)
        axis_pt = c + cx2 * e1 + cy2 * e2
        d = pts - axis_pt
        perp = d - np.outer(d @ axis, axis)
        resid = float(np.max(np.abs(np.linalg.norm(perp, axis=1) - radius)))
        if best is None or resid < best[3]:
            best = (axis_pt, axis, radius, resid)

    return best


def _classify_primitive_robust(s: NurbsSurface, tol: float) -> Optional[dict]:
    """Like _classify_primitive but with the robust multi-axis cylinder fit.

    Used in coaxial-cylinder detection to handle compact (half_len ~ radius)
    cylinders where the standard SVD-based axis-from-largest-variance fails.
    """
    pts = _sample_surface_grid(s)
    if pts.shape[0] < 6:
        return None
    span = float(np.max(np.linalg.norm(pts - pts.mean(axis=0), axis=1))) + 1.0
    abs_tol = max(tol, _PRIM_FIT_TOL) * span

    # Plane first (quick out for flat surfaces).
    pl = _fit_plane(pts)
    if pl is not None and pl[2] <= abs_tol:
        return {"kind": "plane", "point": pl[0], "normal": pl[1]}

    # Sphere vs robust cylinder — pick tighter fit.
    sp = _fit_sphere(pts)
    cy = _fit_cylinder_robust(pts)
    sp_ok = sp is not None and sp[2] <= abs_tol
    cy_ok = cy is not None and cy[3] <= abs_tol

    if sp_ok and cy_ok:
        if sp[2] <= cy[3]:
            return {"kind": "sphere", "center": sp[0], "radius": sp[1]}
        return {"kind": "cylinder", "axis_point": cy[0],
                "axis_dir": cy[1], "radius": cy[2]}
    if sp_ok:
        return {"kind": "sphere", "center": sp[0], "radius": sp[1]}
    if cy_ok:
        return {"kind": "cylinder", "axis_point": cy[0],
                "axis_dir": cy[1], "radius": cy[2]}
    return None


def _axes_parallel(a: np.ndarray, b: np.ndarray, tol: float = 1e-6) -> bool:
    """Return True when unit vectors a and b are (anti-)parallel."""
    cross = np.cross(_unit(a), _unit(b))
    return float(np.linalg.norm(cross)) < tol


def _point_on_axis(pt: np.ndarray,
                   axis_pt: np.ndarray,
                   axis_dir: np.ndarray,
                   tol: float) -> bool:
    """Return True when *pt* is within *tol* of the infinite line."""
    d = pt - axis_pt
    d_ax = float(d @ _unit(axis_dir))
    perp = d - d_ax * _unit(axis_dir)
    return float(np.linalg.norm(perp)) < tol


def _axes_coincident(ax_pt_a: np.ndarray, ax_dir_a: np.ndarray,
                     ax_pt_b: np.ndarray, ax_dir_b: np.ndarray,
                     tol: float = 1e-6) -> bool:
    """Return True when two infinite lines are the same (within tol)."""
    if not _axes_parallel(ax_dir_a, ax_dir_b, tol):
        return False
    return _point_on_axis(ax_pt_b, ax_pt_a, ax_dir_a, tol)


def _empty_params(n: int) -> List[List[float]]:
    return [[0.0, 0.0]] * n


# ---------------------------------------------------------------------------
# detect_degenerate_ssi
# ---------------------------------------------------------------------------

def detect_degenerate_ssi(
    srf_a: NurbsSurface,
    srf_b: NurbsSurface,
    tol: float = 1e-6,
) -> DegenerateSSIType:
    """Classify the surface pair for degenerate SSI handling.

    Uses sampled primitive fitting (plane / sphere / cylinder) to recognise
    the surface types, then checks geometric relationships.

    Parameters
    ----------
    srf_a, srf_b : NurbsSurface
    tol : float
        Spatial tolerance for geometric tests.

    Returns
    -------
    DegenerateSSIType string:
        'coaxial_cylinders', 'coplanar_planes', 'sphere_tangent_plane',
        'cone_apex_match', 'tangent_quadric_pair', or 'generic'.
    """
    try:
        return _detect_degenerate_ssi_impl(srf_a, srf_b, tol)
    except Exception:
        return "generic"


def _detect_degenerate_ssi_impl(
    srf_a: NurbsSurface,
    srf_b: NurbsSurface,
    tol: float,
) -> DegenerateSSIType:
    if not isinstance(srf_a, NurbsSurface) or not isinstance(srf_b, NurbsSurface):
        return "generic"

    # Use the robust classifier (tries all 3 SVD directions for cylinders)
    # so compact cylinders (half_len ~ radius) are correctly recognised.
    pa = _classify_primitive_robust(srf_a, tol)
    pb = _classify_primitive_robust(srf_b, tol)
    if pa is None or pb is None:
        # At least one surface is freeform — check for tangent quadric pair
        # via the Legendre/Weierstrass test: sample both surfaces densely and
        # measure the minimum distance between them + check if normals match.
        return _check_tangent_freeform(srf_a, srf_b, tol)

    ka, kb = pa["kind"], pb["kind"]

    # ---- coplanar planes ----
    if ka == "plane" and kb == "plane":
        na = _unit(pa["normal"])
        nb = _unit(pb["normal"])
        if not _axes_parallel(na, nb, tol * 100):
            return "generic"  # intersecting planes → generic
        # Parallel; check if they are the *same* plane (point of b on plane a).
        d = float((pb["point"] - pa["point"]) @ na)
        pts_b = _sample_surface_grid(srf_b, 5)
        max_d = float(np.max(np.abs((pts_b - pa["point"]) @ na)))
        if max_d < max(tol, _PRIM_FIT_TOL) * 10:
            return "coplanar_planes"
        return "generic"  # offset parallel planes — no intersection

    # ---- sphere tangent to plane ----
    if {ka, kb} == {"plane", "sphere"}:
        pl = pa if ka == "plane" else pb
        sp = pa if ka == "sphere" else pb
        n = _unit(pl["normal"])
        d = abs(float((sp["center"] - pl["point"]) @ n))
        r = sp["radius"]
        gap = abs(d - r)
        if gap < max(tol, 1e-9) * max(1.0, r):
            return "sphere_tangent_plane"
        return "generic"

    # ---- coaxial cylinders ----
    if ka == "cylinder" and kb == "cylinder":
        ax_a = _unit(pa["axis_dir"])
        ax_b = _unit(pb["axis_dir"])
        if not _axes_parallel(ax_a, ax_b, tol * 10):
            return "generic"
        if not _axes_coincident(pa["axis_point"], ax_a,
                                pb["axis_point"], ax_b,
                                tol=max(tol, _PRIM_FIT_TOL) * 50):
            return "generic"
        return "coaxial_cylinders"

    # ---- tangent quadric pair via Legendre canonical form ----
    # Two quadrics (cylinder/sphere or sphere/sphere or cylinder/sphere not
    # already handled above) that are tangent along a conic.  Detect by
    # measuring the minimum distance between sampled point sets and checking
    # that it is below tol while normals at the closest pair are anti-parallel.
    return _check_tangent_freeform(srf_a, srf_b, tol)


def _check_tangent_freeform(
    srf_a: NurbsSurface,
    srf_b: NurbsSurface,
    tol: float,
) -> DegenerateSSIType:
    """Legendre-form tangent contact detection for general NURBS pairs.

    §5.4 (Patrikalakis-Maekawa): two surfaces are tangent along a conic when
    their pencil matrix (the difference of the quadric matrices in Legendre
    canonical form) is rank-deficient.  For the sampled-grid approximation we
    use: find the pair of sample points with minimum 3-D distance; if that
    distance is below tol AND the surface normals at those points are
    anti-parallel to within tol_angle, report 'tangent_quadric_pair'.
    """
    try:
        from kerf_cad_core.geom.intersection import _surf_eval, _surf_normal  # noqa: F401
        n = 13
        u0a, u1a, v0a, v1a = _surface_param_range(srf_a)
        u0b, u1b, v0b, v1b = _surface_param_range(srf_b)
        us_a = np.linspace(u0a, u1a, n)
        vs_a = np.linspace(v0a, v1a, n)
        us_b = np.linspace(u0b, u1b, n)
        vs_b = np.linspace(v0b, v1b, n)
        pts_a = np.array([[_surf_eval(srf_a, float(u), float(v))
                           for v in vs_a] for u in us_a]).reshape(-1, 3)
        pts_b = np.array([[_surf_eval(srf_b, float(u), float(v))
                           for v in vs_b] for u in us_b]).reshape(-1, 3)

        # Find closest pair.
        dists = np.linalg.norm(pts_a[:, None, :] - pts_b[None, :, :], axis=2)
        idx = np.unravel_index(np.argmin(dists), dists.shape)
        min_d = float(dists[idx])

        if min_d > max(tol, _PRIM_FIT_TOL) * 200:
            return "generic"

        # Check anti-parallel normals at the closest pair.
        ia, ib = idx
        i_a, j_a = divmod(int(ia), n)
        i_b, j_b = divmod(int(ib), n)
        ua = float(us_a[i_a]); va = float(vs_a[j_a])
        ub = float(us_b[i_b]); vb = float(vs_b[j_b])
        na_vec = _surf_normal(srf_a, ua, va)
        nb_vec = _surf_normal(srf_b, ub, vb)
        # Tangent contact: normals anti-parallel (dot close to ±1).
        dot = abs(float(na_vec @ nb_vec))
        if dot > 1.0 - tol * 1000:
            return "tangent_quadric_pair"
    except Exception:
        pass
    return "generic"


# ---------------------------------------------------------------------------
# compute_degenerate_ssi_curve
# ---------------------------------------------------------------------------

def compute_degenerate_ssi_curve(
    srf_a: NurbsSurface,
    srf_b: NurbsSurface,
    kind: DegenerateSSIType,
    tol: float = 1e-6,
) -> List[dict]:
    """Compute analytical intersection curve(s) for a degenerate SSI pair.

    Parameters
    ----------
    srf_a, srf_b : NurbsSurface
    kind : DegenerateSSIType
        As returned by detect_degenerate_ssi.
    tol : float

    Returns
    -------
    List of branch dicts (points / params_a / params_b / closed), the same
    schema as surface_surface_intersect branches.  Empty list ⇒ no real
    intersection.
    """
    try:
        return _compute_degenerate_ssi_curve_impl(srf_a, srf_b, kind, tol)
    except Exception:
        return []


def _compute_degenerate_ssi_curve_impl(
    srf_a: NurbsSurface,
    srf_b: NurbsSurface,
    kind: DegenerateSSIType,
    tol: float,
) -> List[dict]:

    pa = _classify_primitive_robust(srf_a, tol)
    pb = _classify_primitive_robust(srf_b, tol)

    # ---- coplanar planes ----
    if kind == "coplanar_planes":
        # The entire surface is the "intersection" — return the bounding
        # polyline of surface A as a degenerate branch.
        pts = _sample_surface_grid(srf_a, 7).tolist()
        return [{
            "points": pts,
            "params_a": _empty_params(len(pts)),
            "params_b": _empty_params(len(pts)),
            "closed": False,
            "degenerate": "coplanar",
        }]

    # ---- sphere tangent to plane ----
    if kind == "sphere_tangent_plane":
        if pa is None or pb is None:
            return []
        pl = pa if pa["kind"] == "plane" else pb
        sp = pa if pa["kind"] == "sphere" else pb
        n = _unit(pl["normal"])
        # Signed distance from sphere centre to plane.
        d = float((sp["center"] - pl["point"]) @ n)
        # Tangent point: foot of the perpendicular from the centre to the plane.
        tangent_pt = (sp["center"] - d * n).tolist()
        return [{
            "points": [tangent_pt],
            "params_a": _empty_params(1),
            "params_b": _empty_params(1),
            "closed": False,
            "degenerate": "tangent_point",
        }]

    # ---- coaxial cylinders ----
    if kind == "coaxial_cylinders":
        if pa is None or pb is None:
            return []
        rA = pa["radius"] if pa["kind"] == "cylinder" else pb["radius"]
        rB = pb["radius"] if pb["kind"] == "cylinder" else pa["radius"]

        # Different radii → no intersection.
        if abs(rA - rB) > max(tol, 1e-9) * max(1.0, abs(rA + rB)):
            return []

        # Same radius → the entire cylinder surface is the intersection.
        # Return a dense circle at the mid-height of surface A as a proxy.
        cy = pa if pa["kind"] == "cylinder" else pb
        ax_pt = np.asarray(cy["axis_point"], dtype=float)
        ax_dir = _unit(np.asarray(cy["axis_dir"], dtype=float))
        r = cy["radius"]
        # Build an orthonormal frame perpendicular to the axis.
        ref = (np.array([1.0, 0.0, 0.0]) if abs(ax_dir[0]) < 0.9
               else np.array([0.0, 1.0, 0.0]))
        e1 = ref - (ref @ ax_dir) * ax_dir
        e1 = e1 / (np.linalg.norm(e1) + 1e-300)
        e2 = np.cross(ax_dir, e1)
        poly = _circle_polyline(ax_pt, r, e1, e2, n=121)
        return [{
            "points": poly,
            "params_a": _empty_params(len(poly)),
            "params_b": _empty_params(len(poly)),
            "closed": True,
            "degenerate": "coaxial_same_radius",
        }]

    # ---- tangent quadric pair — Legendre canonical form ----
    if kind == "tangent_quadric_pair":
        return _legendre_tangent_conic(srf_a, srf_b, pa, pb, tol)

    # ---- cone apex match ----
    if kind == "cone_apex_match":
        # Structural flag only; no analytic curve implemented.
        return []

    # generic — no degenerate handling
    return []


def _legendre_tangent_conic(
    srf_a: NurbsSurface,
    srf_b: NurbsSurface,
    pa: Optional[dict],
    pb: Optional[dict],
    tol: float,
) -> List[dict]:
    """Patrikalakis-Maekawa §5.4: Legendre canonical-form tangent intersection.

    For two quadric surfaces that are tangent along a conic, the intersection
    locus is a planar conic section.  We find the tangent plane (the common
    tangent at the tangent point) and intersect both surfaces with it.

    Algorithm:
    1. Sample both surfaces to find the point of closest approach (the tangent
       contact point).
    2. Compute the common tangent plane there (average of the two normals, both
       should be anti-parallel).
    3. Fit a conic to the set of intersection-candidate points of surface A
       with this tangent plane via a dense scan.

    For two recognised quadrics (sphere/cylinder) we can also use the exact
    formula for the intersection of two quadric surfaces via their canonical
    matrix pencil (Weierstrass form):  F(x) = x^T A x + ... , G(x) = x^T B x + ...
    The pencil A + λB has a zero determinant for the tangent case; the conic is
    the intersection with the common tangent plane.
    """
    try:
        from kerf_cad_core.geom.intersection import _surf_eval, _surf_normal  # noqa: F401
    except ImportError:
        return []

    # Find tangent contact point by dense sampling.
    n = 17
    u0a, u1a, v0a, v1a = _surface_param_range(srf_a)
    u0b, u1b, v0b, v1b = _surface_param_range(srf_b)
    us_a = np.linspace(u0a, u1a, n)
    vs_a = np.linspace(v0a, v1a, n)
    us_b = np.linspace(u0b, u1b, n)
    vs_b = np.linspace(v0b, v1b, n)

    pts_a = np.array([[_surf_eval(srf_a, float(u), float(v))
                       for v in vs_a] for u in us_a]).reshape(-1, 3)
    pts_b = np.array([[_surf_eval(srf_b, float(u), float(v))
                       for v in vs_b] for u in us_b]).reshape(-1, 3)

    dists = np.linalg.norm(pts_a[:, None, :] - pts_b[None, :, :], axis=2)
    idx = np.unravel_index(np.argmin(dists), dists.shape)
    ia, ib = idx
    i_a, j_a = divmod(int(ia), n)
    i_b, j_b = divmod(int(ib), n)

    ua = float(us_a[i_a]); va = float(vs_a[j_a])
    ub = float(us_b[i_b]); vb = float(vs_b[j_b])
    contact_a = _surf_eval(srf_a, ua, va)
    contact_b = _surf_eval(srf_b, ub, vb)
    contact_pt = (contact_a + contact_b) * 0.5
    na_vec = _surf_normal(srf_a, ua, va)
    # Common tangent plane normal: average the two (anti-parallel) normals.
    nb_vec = _surf_normal(srf_b, ub, vb)
    # Make them point the same way for averaging.
    if float(na_vec @ nb_vec) < 0.0:
        nb_vec = -nb_vec
    tangent_normal = _unit(na_vec + nb_vec)

    # Legendre/Weierstrass: for quadric pencil λA + B, when det=0 (tangent
    # case), the intersection is entirely contained in the pencil plane.
    # We approximate the conic by scanning a dense grid of points on surface A
    # that are within tol of the tangent plane.
    plane_d = float(contact_pt @ tangent_normal)
    scale = float(np.max(np.linalg.norm(pts_a - pts_a.mean(axis=0), axis=1))) + 1.0
    scan_tol = max(tol, _PRIM_FIT_TOL) * scale * 5

    on_plane_a = pts_a[np.abs(pts_a @ tangent_normal - plane_d) < scan_tol]

    if len(on_plane_a) < 2:
        # Fallback: return the single tangent point.
        return [{
            "points": [contact_pt.tolist()],
            "params_a": _empty_params(1),
            "params_b": _empty_params(1),
            "closed": False,
            "degenerate": "tangent_conic",
        }]

    # Sort the on-plane points by angle around the contact point to form a conic
    # polyline.  Project onto the tangent plane's 2-D frame.
    ref = np.array([1.0, 0.0, 0.0])
    if abs(float(tangent_normal @ ref)) > 0.9:
        ref = np.array([0.0, 1.0, 0.0])
    ex = ref - (ref @ tangent_normal) * tangent_normal
    ex = _unit(ex)
    ey = np.cross(tangent_normal, ex)

    rel = on_plane_a - contact_pt
    angles = np.arctan2(rel @ ey, rel @ ex)
    order = np.argsort(angles)
    ordered = on_plane_a[order].tolist()

    # Close the polyline if the endpoints are close.
    closed = (len(ordered) >= 4 and
              float(np.linalg.norm(
                  np.array(ordered[0]) - np.array(ordered[-1])
              )) < scale * 0.5)

    return [{
        "points": ordered,
        "params_a": _empty_params(len(ordered)),
        "params_b": _empty_params(len(ordered)),
        "closed": closed,
        "degenerate": "tangent_conic",
    }]


# ---------------------------------------------------------------------------
# ssi_extended — the public entry point
# ---------------------------------------------------------------------------

def ssi_extended(
    srf_a: NurbsSurface,
    srf_b: NurbsSurface,
    *,
    tol: float = 1e-6,
    samples_u: int = 24,
    samples_v: int = 24,
    step: float = 0.02,
    max_steps: int = 2000,
) -> dict:
    """Extended surface-surface intersect with degenerate case detection.

    Checks detect_degenerate_ssi first.  Only falls back to the generic
    hardened marching SSI when the pair is classified as 'generic'.

    Returns the same dict schema as surface_surface_intersect:
        ok, reason, branches, branch_count, degenerate_kind.
    """
    try:
        return _ssi_extended_impl(
            srf_a, srf_b,
            tol=tol, samples_u=samples_u, samples_v=samples_v,
            step=step, max_steps=max_steps,
        )
    except Exception as exc:
        return {
            "ok": False,
            "reason": f"ssi_extended internal error: {exc}",
            "branches": [],
            "branch_count": 0,
            "degenerate_kind": "generic",
        }


def _ssi_extended_impl(
    srf_a: NurbsSurface,
    srf_b: NurbsSurface,
    *,
    tol: float,
    samples_u: int,
    samples_v: int,
    step: float,
    max_steps: int,
) -> dict:
    kind = detect_degenerate_ssi(srf_a, srf_b, tol=tol)

    if kind != "generic":
        branches = compute_degenerate_ssi_curve(srf_a, srf_b, kind, tol=tol)
        return {
            "ok": True,
            "reason": "",
            "branches": branches,
            "branch_count": len(branches),
            "degenerate_kind": kind,
        }

    # Fall back to the hardened generic marching SSI.
    result = _generic_ssi(
        srf_a, srf_b,
        tol=tol, samples_u=samples_u, samples_v=samples_v,
        step=step, max_steps=max_steps,
    )
    result["degenerate_kind"] = "generic"
    return result


# ---------------------------------------------------------------------------
# LLM tool registration
# ---------------------------------------------------------------------------

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register  # type: ignore[import]
    from kerf_core.utils.context import ProjectCtx  # type: ignore[import]
    import json as _json
    _REGISTRY_AVAILABLE = True
except ImportError:
    _REGISTRY_AVAILABLE = False


if _REGISTRY_AVAILABLE:
    import numpy as _np_tool
    from kerf_cad_core.geom.nurbs import NurbsSurface as _NS

    _NURBS_SSI_DEGEN_SPEC = ToolSpec(
        name="nurbs_ssi_with_degenerate_check",
        description=(
            "Compute surface-surface intersection (SSI) with automatic degenerate-case "
            "detection and Legendre canonical-form analytical curves.\n"
            "\n"
            "Detects and resolves:\n"
            "  - coaxial_cylinders : same radius → entire cylinder; different → empty.\n"
            "  - coplanar_planes   : returns shared surface boundary.\n"
            "  - sphere_tangent_plane : single point at tangent contact.\n"
            "  - tangent_quadric_pair : Legendre/Weierstrass conic section.\n"
            "  - generic           : falls back to hardened marching SSI.\n"
            "\n"
            "Returns:\n"
            "  ok             : bool\n"
            "  branch_count   : int\n"
            "  branches       : list of {points, params_a, params_b, closed, degenerate?}\n"
            "  degenerate_kind: str — the detected degenerate type\n"
            "\n"
            "Errors: {ok:false, reason}.  Never raises."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "surf_a_control_points": {
                    "type": "array",
                    "description": "Flat list of [x,y,z] control points, row-major (num_u * num_v).",
                    "items": {"type": "array", "items": {"type": "number"}},
                },
                "surf_a_degree_u": {"type": "integer"},
                "surf_a_degree_v": {"type": "integer"},
                "surf_a_num_u": {"type": "integer"},
                "surf_a_num_v": {"type": "integer"},
                "surf_b_control_points": {
                    "type": "array",
                    "items": {"type": "array", "items": {"type": "number"}},
                },
                "surf_b_degree_u": {"type": "integer"},
                "surf_b_degree_v": {"type": "integer"},
                "surf_b_num_u": {"type": "integer"},
                "surf_b_num_v": {"type": "integer"},
                "tolerance": {"type": "number", "description": "Spatial tolerance (default 1e-6)."},
            },
            "required": [
                "surf_a_control_points", "surf_a_degree_u", "surf_a_degree_v",
                "surf_a_num_u", "surf_a_num_v",
                "surf_b_control_points", "surf_b_degree_u", "surf_b_degree_v",
                "surf_b_num_u", "surf_b_num_v",
            ],
        },
    )

    def _build_surface(a: dict, prefix: str) -> "_NS":
        nu = int(a[f"{prefix}num_u"])
        nv = int(a[f"{prefix}num_v"])
        cp = _np_tool.array(
            a.get(f"{prefix}control_points", []), dtype=float
        ).reshape(nu, nv, -1)
        du = int(a[f"{prefix}degree_u"])
        dv = int(a[f"{prefix}degree_v"])

        def _mk(n: int, d: int) -> _np_tool.ndarray:
            inner = max(0, n - d - 1)
            return _np_tool.concatenate([
                _np_tool.zeros(d + 1),
                (_np_tool.linspace(0.0, 1.0, inner + 2)[1:-1]
                 if inner > 0 else _np_tool.array([])),
                _np_tool.ones(d + 1),
            ])

        return _NS(
            degree_u=du, degree_v=dv, control_points=cp,
            knots_u=_mk(nu, du), knots_v=_mk(nv, dv),
        )

    @register(_NURBS_SSI_DEGEN_SPEC)
    async def run_nurbs_ssi_with_degenerate_check(
        ctx: "ProjectCtx", args: bytes
    ) -> str:
        try:
            a = _json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid args: {exc}", "BAD_ARGS")
        try:
            sA = _build_surface(a, "surf_a_")
            sB = _build_surface(a, "surf_b_")
        except Exception as exc:
            return err_payload(f"invalid surface: {exc}", "BAD_ARGS")
        tol = float(a.get("tolerance", 1e-6))
        result = ssi_extended(sA, sB, tol=tol)
        if not result["ok"]:
            return err_payload(result["reason"], "OP_FAILED")
        return ok_payload(result)
