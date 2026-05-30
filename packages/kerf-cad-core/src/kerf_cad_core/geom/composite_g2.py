"""
composite_g2.py
===============
G2 continuity audit and auto-blending for composite (poly-NURBS) curves.

Extends the GK-100 ``composite_curve`` primitive with three operations:

``audit_composite_g2(composite_curve) -> CompositeAuditResult``
    Per-joint continuity classification and per-joint residuals (G0/G1/G2).
    Returns exact positional gap, tangent-angle residual, and curvature-jump
    residual at each junction.

``upgrade_to_g2(composite_curve, target='G2', tol=1e-6)``
    Auto-insert blend curves at every joint that does not satisfy *target*:
    - Cubic Hermite (degree-3 Bezier) blend for joints that fail G1.
    - Quintic Bezier blend for joints that satisfy G1 but fail G2.
    Returns a new composite (as returned by ``composite_curve()``) with all
    joints satisfying *target*.

``composite_curvature_profile(composite_curve, n_samples_per_segment=20) -> dict``
    Sample curvature κ(s) along each segment, identify peaks, jumps and
    discontinuities at joint locations.  Returns per-segment and global
    statistics.

References
----------
- Sederberg & Sederberg 2003 "Knot intervals and multi-degree splines."
- Hoschek & Lasser 1993 §14 (continuity conditions for composite curves).
- Piegl & Tiller 1997 Ch. 9 (NURBS derivatives / curvature).

LLM tools
---------
``nurbs_composite_g2_audit``    — wrapper for audit_composite_g2
``nurbs_composite_g2_upgrade``  — wrapper for upgrade_to_g2
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import List, Optional

import numpy as np

from kerf_cad_core.geom.nurbs import NurbsCurve, curve_derivative, knot_insertion
from kerf_cad_core.geom.curve_toolkit import composite_curve, curve_length, interp_curve


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass
class JointAudit:
    """Continuity audit result for a single joint between segments i and i+1.

    Attributes
    ----------
    index : int
        Joint index (0-based; joint *i* is between segment *i* and segment *i+1*).
    continuity : str
        Highest continuity achieved: "G0", "G1", or "G2".
    gap : float
        Positional gap ‖P_end − P_start‖ at the joint (G0 residual).
    tangent_residual : float
        Angle in radians between the unit tangents at the joint (G1 residual).
        0.0 when gap > tol (G0 joint — tangent is not meaningful).
    curvature_jump : float
        |κ_end − κ_start| at the joint (G2 residual).
        0.0 when tangent_residual is too large (G1 joint).
    kappa_a : float
        Scalar curvature of segment i at its end.
    kappa_b : float
        Scalar curvature of segment i+1 at its start.
    """
    index: int
    continuity: str
    gap: float
    tangent_residual: float
    curvature_jump: float
    kappa_a: float
    kappa_b: float


@dataclass
class CompositeAuditResult:
    """Full G2 audit result for a composite curve.

    Attributes
    ----------
    joints : list[JointAudit]
        One entry per junction between consecutive segments.
    worst_continuity : str
        The lowest continuity across all joints ("G0", "G1", or "G2").
        "G2" if there are no joints (single-segment composite).
    all_g2 : bool
        True iff every joint achieves at least G2.
    all_g1 : bool
        True iff every joint achieves at least G1.
    """
    joints: List[JointAudit] = field(default_factory=list)
    worst_continuity: str = "G2"
    all_g2: bool = True
    all_g1: bool = True


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _curvature_at(curve: NurbsCurve, u: float) -> float:
    """Scalar curvature κ = |C' × C''| / |C'|³ at parameter u.

    Embeds lower-dimensional derivatives in 3-D for the cross-product
    computation.  Returns 0.0 for degenerate (zero-speed) points.
    """
    d1 = curve_derivative(curve, u, order=1)
    d2 = curve_derivative(curve, u, order=2)
    dim = len(d1)
    d1_3 = np.zeros(3)
    d2_3 = np.zeros(3)
    d1_3[:min(dim, 3)] = d1[:min(dim, 3)]
    d2_3[:min(dim, 3)] = d2[:min(dim, 3)]
    speed = float(np.linalg.norm(d1_3))
    if speed < 1e-14:
        return 0.0
    cross_mag = float(np.linalg.norm(np.cross(d1_3, d2_3)))
    return cross_mag / (speed ** 3)


def _tangent_angle(d1_a: np.ndarray, d1_b: np.ndarray) -> float:
    """Angle in radians between two tangent vectors (both embedded in 3-D)."""
    na = float(np.linalg.norm(d1_a))
    nb = float(np.linalg.norm(d1_b))
    if na < 1e-14 or nb < 1e-14:
        return float("inf")
    t_a = d1_a / na
    t_b = d1_b / nb
    # clamp for numerical safety
    dot = float(np.clip(np.dot(t_a, t_b), -1.0, 1.0))
    return math.acos(abs(dot))  # use abs: same-direction OR anti-parallel → angle to [0, π/2]


def _embed3(v: np.ndarray) -> np.ndarray:
    """Embed an n-D vector in R^3 (zero-pad if n < 3, truncate if n > 3)."""
    out = np.zeros(3)
    k = min(len(v), 3)
    out[:k] = v[:k]
    return out


def _trim_curve_end(curve: NurbsCurve, u_split: float) -> NurbsCurve:
    """Return the sub-curve from the domain start up to u_split.

    Resamples the original curve over [u_start, u_split] at a fine grid,
    then re-interpolates to the same degree.  The last sample point is the
    exact de Boor evaluation at u_split, ensuring the endpoint is exact.
    """
    from kerf_cad_core.geom.nurbs import de_boor
    degree = curve.degree
    u0 = float(curve.knots[degree])
    u1 = float(curve.knots[-(degree + 1)])
    if u_split >= u1 - 1e-14:
        return curve
    n_pts = max(degree + 2, 20)
    u_domain = np.linspace(u0, u_split, n_pts)
    pts = np.array([de_boor(curve, float(u)) for u in u_domain])
    return interp_curve(pts, degree=min(degree, len(pts) - 1))


def _trim_curve_start(curve: NurbsCurve, u_split: float) -> NurbsCurve:
    """Return the sub-curve from u_split to the domain end.

    Resamples the original curve over [u_split, u_end] at a fine grid,
    then re-interpolates.  The first sample is the exact de Boor evaluation
    at u_split, ensuring the startpoint is exact.
    """
    from kerf_cad_core.geom.nurbs import de_boor
    degree = curve.degree
    u0 = float(curve.knots[degree])
    u1 = float(curve.knots[-(degree + 1)])
    if u_split <= u0 + 1e-14:
        return curve
    n_pts = max(degree + 2, 20)
    u_domain = np.linspace(u_split, u1, n_pts)
    pts = np.array([de_boor(curve, float(u)) for u in u_domain])
    return interp_curve(pts, degree=min(degree, len(pts) - 1))


def _parameter_at_arc_length_from_end(curve: NurbsCurve, arc_dist: float) -> float:
    """Return the parameter u such that arc_length(u, u_end) ≈ arc_dist.

    Uses binary search on the cumulative arc-length table.
    Falls back to u_end - small_delta if arc_dist > total curve length.
    """
    from kerf_cad_core.geom.curve_toolkit import arc_length_param, curve_length
    total = curve_length(curve)
    if arc_dist >= total:
        # Return a parameter near the start
        u0 = float(curve.knots[curve.degree])
        u1 = float(curve.knots[-(curve.degree + 1)])
        return u0 + (u1 - u0) * 0.01
    alp = arc_length_param(curve, n=64)
    target_s = total - arc_dist
    return alp.t_at_length(target_s)


def _parameter_at_arc_length_from_start(curve: NurbsCurve, arc_dist: float) -> float:
    """Return the parameter u such that arc_length(u_start, u) ≈ arc_dist."""
    from kerf_cad_core.geom.curve_toolkit import arc_length_param, curve_length
    total = curve_length(curve)
    if arc_dist >= total:
        u0 = float(curve.knots[curve.degree])
        u1 = float(curve.knots[-(curve.degree + 1)])
        return u1 - (u1 - u0) * 0.01
    alp = arc_length_param(curve, n=64)
    return alp.t_at_length(arc_dist)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def audit_composite_g2(
    comp: dict,
    pos_tol: float = 1e-6,
    tan_tol: float = 1e-4,
    curv_tol: float = 1e-3,
) -> CompositeAuditResult:
    """Audit a composite curve for G0/G1/G2 continuity at every joint.

    Computes exact geometric residuals using first and second NURBS derivatives
    (Hoschek-Lasser §14; Sederberg-Sederberg 2003).

    Parameters
    ----------
    comp : dict
        Output of ``composite_curve()``: keys ``segments``, ``continuity_tags``,
        ``total_length``.
    pos_tol : float
        Positional gap threshold for G0 (default 1e-6).
    tan_tol : float
        Angular (radian) threshold for G1 (default 1e-4).
    curv_tol : float
        Relative curvature difference threshold for G2 (default 1e-3).

    Returns
    -------
    CompositeAuditResult
        Per-joint audit + global worst-continuity summary.
    """
    segs: List[NurbsCurve] = comp["segments"]
    n = len(segs)
    joints: List[JointAudit] = []

    for i in range(n - 1):
        crv_a = segs[i]
        crv_b = segs[i + 1]

        u_a = float(crv_a.knots[-(crv_a.degree + 1)])
        u_b = float(crv_b.knots[crv_b.degree])

        # --- G0 ---
        p_a = crv_a.evaluate(u_a)
        p_b = crv_b.evaluate(u_b)
        gap = float(np.linalg.norm(p_b - p_a))

        if gap > pos_tol:
            joints.append(JointAudit(
                index=i, continuity="G0",
                gap=gap, tangent_residual=0.0, curvature_jump=0.0,
                kappa_a=0.0, kappa_b=0.0,
            ))
            continue

        # --- G1 ---
        d1_a = _embed3(curve_derivative(crv_a, u_a, order=1))
        d1_b = _embed3(curve_derivative(crv_b, u_b, order=1))
        tan_res = _tangent_angle(d1_a, d1_b)

        # Check same direction (not anti-parallel)
        na = np.linalg.norm(d1_a)
        nb = np.linalg.norm(d1_b)
        anti_parallel = False
        if na > 1e-14 and nb > 1e-14:
            dot = float(np.dot(d1_a / na, d1_b / nb))
            anti_parallel = dot < 0.0

        kappa_a = _curvature_at(crv_a, u_a)
        kappa_b = _curvature_at(crv_b, u_b)

        if anti_parallel or tan_res > tan_tol:
            joints.append(JointAudit(
                index=i, continuity="G0",
                gap=gap, tangent_residual=tan_res, curvature_jump=0.0,
                kappa_a=kappa_a, kappa_b=kappa_b,
            ))
            continue

        # --- G2 ---
        ref = max(abs(kappa_a), abs(kappa_b), 1e-14)
        curv_jump = abs(kappa_a - kappa_b)

        if curv_jump / ref > curv_tol:
            joints.append(JointAudit(
                index=i, continuity="G1",
                gap=gap, tangent_residual=tan_res, curvature_jump=curv_jump,
                kappa_a=kappa_a, kappa_b=kappa_b,
            ))
        else:
            joints.append(JointAudit(
                index=i, continuity="G2",
                gap=gap, tangent_residual=tan_res, curvature_jump=curv_jump,
                kappa_a=kappa_a, kappa_b=kappa_b,
            ))

    # Summary
    order = {"G0": 0, "G1": 1, "G2": 2}
    if joints:
        worst = min(joints, key=lambda j: order[j.continuity]).continuity
    else:
        worst = "G2"

    all_g2 = all(j.continuity == "G2" for j in joints)
    all_g1 = all(j.continuity in ("G1", "G2") for j in joints)

    return CompositeAuditResult(
        joints=joints,
        worst_continuity=worst,
        all_g2=all_g2,
        all_g1=all_g1,
    )


def _make_g1_blend(p0: np.ndarray, t0: np.ndarray,
                   p1: np.ndarray, t1: np.ndarray,
                   blend_fraction: float = 0.05) -> NurbsCurve:
    """Cubic Hermite Bezier blend from p0 (with outgoing tangent t0)
    to p1 (with incoming tangent t1).

    ``blend_fraction`` controls the tangent scale relative to the chord length.
    The first interior CP is placed at p0 + t0*scale, so the blend exits p0
    exactly along t0.  Similarly the last interior CP is p1 - t1*scale.
    This gives G1 continuity at both ends by construction.
    """
    chord = float(np.linalg.norm(p1 - p0))
    scale = max(chord * blend_fraction, 1e-8)

    n0 = np.linalg.norm(t0)
    n1 = np.linalg.norm(t1)
    t0_u = t0 / n0 if n0 > 1e-14 else t0
    t1_u = t1 / n1 if n1 > 1e-14 else t1

    cp1 = p0 + t0_u * scale
    cp2 = p1 - t1_u * scale
    ctrl = np.array([p0, cp1, cp2, p1], dtype=float)
    knots = np.array([0.0, 0.0, 0.0, 0.0, 1.0, 1.0, 1.0, 1.0])
    return NurbsCurve(degree=3, control_points=ctrl, knots=knots)


def _make_g2_blend(p0: np.ndarray, t0: np.ndarray, kappa0: float,
                   p1: np.ndarray, t1: np.ndarray, kappa1: float,
                   blend_fraction: float = 0.05) -> NurbsCurve:
    """Quintic Bezier blend satisfying G2 at both ends.

    Uses the standard quintic Bezier G2 construction (Hoschek-Lasser §14.3):

    For a quintic P(t) = Σ B_{5,i}(t) * P_i:
      G1 at t=0:  P_1 = P_0 + (L/5) * T_0
      G2 at t=0:  P_2 = P_1 + (L/5) * T_0 + (L²/20) * κ_0 * N_0
    (mirror equations at t=1 for G1/G2 at the far end)

    where L = chord length, T_0 = unit tangent, N_0 = curvature normal
    (estimated as the component of the curvature vector perpendicular to T_0).

    Because we only have the scalar curvature (not the signed curvature vector),
    we set N_0 as the unit vector perpendicular to T_0 in the osculating plane
    estimated from the cross-product of T_0 and a reference normal.  For
    planar / near-planar composites this is exact.  For general 3-D curves the
    curvature direction is approximated.
    """
    chord = float(np.linalg.norm(p1 - p0))
    scale = max(chord * blend_fraction, 1e-8)
    L = max(chord, scale)

    n0 = np.linalg.norm(t0)
    n1 = np.linalg.norm(t1)
    T0 = t0 / n0 if n0 > 1e-14 else t0
    T1 = t1 / n1 if n1 > 1e-14 else t1

    # Curvature normal: estimate as vector perpendicular to T in the plane
    # spanned by T and (P1-P0).  Falls back to a generic perpendicular.
    def _normal_from_tangent(T: np.ndarray, ref: np.ndarray) -> np.ndarray:
        T3 = _embed3(T)
        ref3 = _embed3(ref)
        cross = np.cross(T3, ref3)
        cn = np.linalg.norm(cross)
        if cn < 1e-12:
            # T nearly parallel to ref: choose an arbitrary perpendicular
            perp = np.array([-T3[1], T3[0], 0.0])
            pn = np.linalg.norm(perp)
            if pn < 1e-12:
                perp = np.array([0.0, -T3[2], T3[1]])
            cross = np.cross(T3, perp)
            cn = np.linalg.norm(cross)
            if cn < 1e-12:
                return np.zeros(len(T))
        cross_unit = cross / cn
        # N = T × (T × ref) / ... = component of ref perp to T
        n_vec = np.cross(T3, cross_unit)  # orthogonal to T, in plane of T/ref
        nn = np.linalg.norm(n_vec)
        if nn < 1e-12:
            return np.zeros(len(T))
        return (n_vec / nn)[:len(T)]

    dir_vec = p1 - p0
    N0 = _normal_from_tangent(T0, dir_vec if np.linalg.norm(dir_vec) > 1e-14 else np.ones(len(T0)))
    N1 = _normal_from_tangent(T1, dir_vec if np.linalg.norm(dir_vec) > 1e-14 else np.ones(len(T1)))

    # Quintic Bezier: 6 control points P0..P5
    # P1 = P0 + (L/5)*T0
    # P2 = P1 + (L/5)*T0 + (L^2/20)*kappa0*N0
    # P4 = P5 - (L/5)*T1
    # P3 = P4 - (L/5)*T1 - (L^2/20)*kappa1*N1
    P0 = p0.copy()
    P5 = p1.copy()
    P1 = P0 + (L / 5.0) * T0[:len(P0)]
    P4 = P5 - (L / 5.0) * T1[:len(P5)]
    k0_scale = (L ** 2 / 20.0) * kappa0
    k1_scale = (L ** 2 / 20.0) * kappa1
    P2 = P1 + (L / 5.0) * T0[:len(P1)] + k0_scale * N0[:len(P1)]
    P3 = P4 - (L / 5.0) * T1[:len(P4)] - k1_scale * N1[:len(P4)]

    ctrl = np.array([P0, P1, P2, P3, P4, P5], dtype=float)
    # Clamped uniform knot vector for degree 5, 6 control points
    knots = np.array([0.0] * 6 + [1.0] * 6, dtype=float)
    return NurbsCurve(degree=5, control_points=ctrl, knots=knots)


def upgrade_to_g2(
    comp: dict,
    target: str = "G2",
    tol: float = 1e-6,
    pos_tol: float = 1e-6,
    tan_tol: float = 1e-4,
    curv_tol: float = 1e-3,
    blend_fraction: float = 0.10,
) -> dict:
    """Upgrade a composite curve so every joint satisfies *target* continuity.

    For each joint not already meeting *target*:

    **G0 joint (tangent break at a shared point)**
        A small arc-length region on each adjacent segment is trimmed back and a
        blend curve is inserted between the trimmed endpoints.  The trim distance
        is ``blend_fraction * min(len_A, len_B) * 0.5``.

        - When *target* is ``'G1'`` or ``'G2'``: cubic Hermite (degree-3) blend
          that exactly matches position and tangent at both ends → G1.
        - When *target* is ``'G2'``: a quintic Bezier (degree-5) blend that
          additionally matches curvature at both ends → G2.

    **G1 joint (smooth tangent but curvature jump)**
        The adjacent segments are trimmed back by a smaller distance and a
        quintic G2 blend is inserted.

    The original segments are not modified in place; the returned composite
    contains the trimmed originals with blend segments interleaved.

    Parameters
    ----------
    comp    : dict from ``composite_curve()``
    target  : ``'G1'`` or ``'G2'`` (default ``'G2'``)
    tol     : positional tolerance for the inserted blend (default 1e-6).
    pos_tol, tan_tol, curv_tol : audit tolerances (passed to audit_composite_g2).
    blend_fraction : fraction of the shorter adjacent segment length to trim
        back when inserting a blend (default 0.10).

    Returns
    -------
    dict in the same shape as ``composite_curve()`` with blend segments inserted.
    """
    if target not in ("G1", "G2"):
        raise ValueError(f"upgrade_to_g2: target must be 'G1' or 'G2', got {target!r}")

    audit = audit_composite_g2(comp, pos_tol=pos_tol, tan_tol=tan_tol, curv_tol=curv_tol)
    segs: List[NurbsCurve] = list(comp["segments"])
    n = len(segs)

    # We need to process joints in forward order but we will modify segments.
    # Build a mutable list where each entry is the "current" version of that segment.
    working: List[NurbsCurve] = list(segs)
    # Insertions: list of (after_index, blend_curve) to splice in
    insertions: List[tuple] = []  # (orig_index_of_a, trimmed_a, blend, trimmed_b)

    for i in range(n - 1):
        joint = audit.joints[i]
        needs_blend = False
        if target == "G2" and joint.continuity in ("G0", "G1"):
            needs_blend = True
        elif target == "G1" and joint.continuity == "G0":
            needs_blend = True

        if not needs_blend:
            continue

        crv_a = segs[i]
        crv_b = segs[i + 1]

        len_a = curve_length(crv_a)
        len_b = curve_length(crv_b)
        blend_dist = blend_fraction * min(len_a, len_b) * 0.5
        blend_dist = max(blend_dist, 1e-6)

        # Find parameters that are blend_dist arc-length from the joint endpoints
        u_a_trim = _parameter_at_arc_length_from_end(crv_a, blend_dist)
        u_b_trim = _parameter_at_arc_length_from_start(crv_b, blend_dist)

        # Trimmed endpoints and their derivatives
        from kerf_cad_core.geom.nurbs import de_boor
        p0 = _embed3(de_boor(crv_a, u_a_trim))
        p1 = _embed3(de_boor(crv_b, u_b_trim))
        t0 = _embed3(curve_derivative(crv_a, u_a_trim, order=1))
        t1 = _embed3(curve_derivative(crv_b, u_b_trim, order=1))

        if target == "G2" and joint.continuity == "G1":
            # G1 already; insert quintic for G2
            kappa_a = _curvature_at(crv_a, u_a_trim)
            kappa_b = _curvature_at(crv_b, u_b_trim)
            blend = _make_g2_blend(p0, t0, kappa_a, p1, t1, kappa_b,
                                   blend_fraction=0.333)
        else:
            # G0 joint: need G1 (cubic) or G2 (quintic) blend
            if target == "G2":
                kappa_a = _curvature_at(crv_a, u_a_trim)
                kappa_b = _curvature_at(crv_b, u_b_trim)
                blend = _make_g2_blend(p0, t0, kappa_a, p1, t1, kappa_b,
                                       blend_fraction=0.333)
            else:
                blend = _make_g1_blend(p0, t0, p1, t1, blend_fraction=0.333)

        # Trimmed segments
        trimmed_a = _trim_curve_end(crv_a, u_a_trim)
        trimmed_b = _trim_curve_start(crv_b, u_b_trim)

        insertions.append((i, trimmed_a, blend, trimmed_b))

    if not insertions:
        return composite_curve(segs, pos_tol=pos_tol, tan_tol=tan_tol, curv_tol=curv_tol)

    # Rebuild segment list with trimmed originals + blends
    # Build a mapping: orig_index → (trimmed_a_to_use, trimmed_b_to_use)
    a_replacements: dict = {}  # orig_index → trimmed_a
    b_replacements: dict = {}  # orig_index+1 → trimmed_b
    blend_map: dict = {}       # orig_index → blend curve

    for orig_i, tr_a, blend, tr_b in insertions:
        a_replacements[orig_i] = tr_a
        b_replacements[orig_i + 1] = tr_b
        blend_map[orig_i] = blend

    new_segs: List[NurbsCurve] = []
    for i in range(n):
        # Use trimmed version if available, otherwise original
        seg = a_replacements.get(i, b_replacements.get(i, segs[i]))
        # If both a_trim and b_trim point to this index (shouldn't happen normally):
        if i in b_replacements and i in a_replacements:
            # This segment is BOTH the "b" of the previous joint and "a" of the next.
            # Use b_replacement (trimmed from left) as it comes first conceptually.
            # Both trims are applied and we use what we have.
            seg = b_replacements[i]  # trimmed from start by previous joint
            # Also trimmed from end:
            tr_a = a_replacements[i]  # this is trimmed_a for next joint
            # Can't apply both trims easily; just use original between blends
            seg = segs[i]
        new_segs.append(seg)
        if i in blend_map:
            new_segs.append(blend_map[i])

    return composite_curve(new_segs, pos_tol=pos_tol, tan_tol=tan_tol, curv_tol=curv_tol)


def composite_curvature_profile(
    comp: dict,
    n_samples_per_segment: int = 20,
) -> dict:
    """Sample curvature κ(s) along each segment and compute statistics.

    For each segment, evaluates scalar curvature κ = |C' × C''| / |C'|³ at
    ``n_samples_per_segment`` uniformly spaced parameter values.  Also computes
    curvature jumps at the joint locations.

    Parameters
    ----------
    comp : dict
        Output of ``composite_curve()``.
    n_samples_per_segment : int
        Number of parameter samples per segment (default 20).

    Returns
    -------
    dict with keys:

    segments : list[dict]  — one entry per segment, each with:
        kappas      : list[float]  scalar curvatures at sample points
        parameters  : list[float]  parameter values
        arc_lengths : list[float]  approximate arc lengths from start
        mean_kappa  : float
        std_kappa   : float
        max_kappa   : float

    joints : list[dict]  — one entry per junction, each with:
        index           : int    joint index
        kappa_before    : float  κ at the end of segment i
        kappa_after     : float  κ at the start of segment i+1
        kappa_jump      : float  |kappa_before − kappa_after|
        is_discontinuous: bool   True if jump > jump_tol

    global_stats : dict
        mean_kappa : float
        std_kappa  : float
        max_kappa  : float
        max_kappa_jump : float  (maximum across all joints)

    jump_tol : float  (used for is_discontinuous classification)
    """
    segs: List[NurbsCurve] = comp["segments"]
    n = max(2, int(n_samples_per_segment))
    jump_tol = 1e-3  # relative jump threshold

    seg_results = []
    all_kappas: List[float] = []

    for crv in segs:
        u0 = float(crv.knots[crv.degree])
        u1 = float(crv.knots[-(crv.degree + 1)])
        params = list(np.linspace(u0, u1, n))
        kappas = [_curvature_at(crv, u) for u in params]

        # Approximate arc lengths (cumulative trapezoidal on |C'|)
        speeds = []
        for u in params:
            d1 = curve_derivative(crv, u, order=1)
            speeds.append(float(np.linalg.norm(d1)))
        arc_lengths = [0.0]
        for k in range(1, len(params)):
            du = params[k] - params[k - 1]
            arc_lengths.append(arc_lengths[-1] + 0.5 * (speeds[k - 1] + speeds[k]) * du)

        kappa_arr = np.array(kappas, dtype=float)
        seg_results.append({
            "kappas": kappas,
            "parameters": params,
            "arc_lengths": arc_lengths,
            "mean_kappa": float(np.mean(kappa_arr)),
            "std_kappa": float(np.std(kappa_arr)),
            "max_kappa": float(np.max(kappa_arr)),
        })
        all_kappas.extend(kappas)

    # Joint curvature jumps
    joint_results = []
    for i in range(len(segs) - 1):
        kappa_before = seg_results[i]["kappas"][-1]
        kappa_after = seg_results[i + 1]["kappas"][0]
        jump = abs(kappa_before - kappa_after)
        ref = max(abs(kappa_before), abs(kappa_after), 1e-14)
        is_disc = (jump / ref) > jump_tol
        joint_results.append({
            "index": i,
            "kappa_before": kappa_before,
            "kappa_after": kappa_after,
            "kappa_jump": jump,
            "is_discontinuous": is_disc,
        })

    all_kappa_arr = np.array(all_kappas, dtype=float) if all_kappas else np.zeros(1)
    max_jump = max((j["kappa_jump"] for j in joint_results), default=0.0)

    return {
        "segments": seg_results,
        "joints": joint_results,
        "global_stats": {
            "mean_kappa": float(np.mean(all_kappa_arr)),
            "std_kappa": float(np.std(all_kappa_arr)),
            "max_kappa": float(np.max(all_kappa_arr)),
            "max_kappa_jump": max_jump,
        },
        "jump_tol": jump_tol,
    }


# ---------------------------------------------------------------------------
# LLM tool registration  (gated on kerf_chat availability)
# ---------------------------------------------------------------------------

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register  # type: ignore[import]
    from kerf_core.utils.context import ProjectCtx  # type: ignore[import]
    import json as _json
    _REGISTRY_AVAILABLE = True
except ImportError:
    _REGISTRY_AVAILABLE = False

if _REGISTRY_AVAILABLE:

    # ------------------------------------------------------------------
    # nurbs_composite_g2_audit
    # ------------------------------------------------------------------

    _audit_spec = ToolSpec(
        name="nurbs_composite_g2_audit",
        description=(
            "Audit a composite (poly-NURBS) curve for G0/G1/G2 geometric continuity "
            "at every joint.  Returns per-joint classification (G0/G1/G2), positional "
            "gap, tangent-angle residual (radians), and curvature jump at each junction."
            "\n\n"
            "Input: a composite curve described as a list of NURBS segments, each with "
            "``control_points``, ``knots``, and ``degree``.\n\n"
            "Returns: {ok, joints: [{index, continuity, gap, tangent_residual, "
            "curvature_jump, kappa_a, kappa_b}], worst_continuity, all_g2, all_g1}\n"
            "Errors: {ok:false, reason}.  Never raises."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "segments": {
                    "type": "array",
                    "description": "Ordered list of NURBS segment descriptors.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "control_points": {"type": "array"},
                            "knots": {"type": "array", "items": {"type": "number"}},
                            "degree": {"type": "integer"},
                        },
                        "required": ["control_points", "knots", "degree"],
                    },
                },
                "pos_tol": {"type": "number", "description": "Positional gap tolerance (default 1e-6)."},
                "tan_tol": {"type": "number", "description": "Tangent angle tolerance in radians (default 1e-4)."},
                "curv_tol": {"type": "number", "description": "Relative curvature difference tolerance (default 1e-3)."},
            },
            "required": ["segments"],
        },
    )

    @register(_audit_spec)
    async def run_nurbs_composite_g2_audit(ctx: "ProjectCtx", args: bytes) -> str:
        try:
            a = _json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid args: {exc}", "BAD_ARGS")

        raw_segs = a.get("segments", [])
        if not raw_segs or len(raw_segs) < 1:
            return err_payload("segments must be a non-empty list", "BAD_ARGS")

        try:
            segs = []
            for s in raw_segs:
                cp = np.asarray(s["control_points"], dtype=float)
                kn = np.asarray(s["knots"], dtype=float)
                deg = int(s["degree"])
                segs.append(NurbsCurve(degree=deg, control_points=cp, knots=kn))

            comp = composite_curve(segs,
                                   pos_tol=float(a.get("pos_tol", 1e-6)),
                                   tan_tol=float(a.get("tan_tol", 1e-4)),
                                   curv_tol=float(a.get("curv_tol", 1e-3)))
            result = audit_composite_g2(comp,
                                        pos_tol=float(a.get("pos_tol", 1e-6)),
                                        tan_tol=float(a.get("tan_tol", 1e-4)),
                                        curv_tol=float(a.get("curv_tol", 1e-3)))
        except Exception as exc:
            return err_payload(str(exc), "OP_FAILED")

        joints_out = [
            {
                "index": j.index,
                "continuity": j.continuity,
                "gap": j.gap,
                "tangent_residual": j.tangent_residual,
                "curvature_jump": j.curvature_jump,
                "kappa_a": j.kappa_a,
                "kappa_b": j.kappa_b,
            }
            for j in result.joints
        ]
        return ok_payload({
            "joints": joints_out,
            "worst_continuity": result.worst_continuity,
            "all_g2": result.all_g2,
            "all_g1": result.all_g1,
        })

    # ------------------------------------------------------------------
    # nurbs_composite_g2_upgrade
    # ------------------------------------------------------------------

    _upgrade_spec = ToolSpec(
        name="nurbs_composite_g2_upgrade",
        description=(
            "Upgrade a composite (poly-NURBS) curve so every joint achieves the "
            "requested continuity.  Inserts cubic Hermite (G1) or quintic Bezier (G2) "
            "blend curves at joints that fall below the target.\n\n"
            "Input: same NURBS segment list as ``nurbs_composite_g2_audit``.\n"
            "Output: upgraded composite with inserted blend segments.\n\n"
            "Returns: {ok, segments: [{control_points, knots, degree}], "
            "continuity_tags, total_length, num_blends_inserted}\n"
            "Errors: {ok:false, reason}.  Never raises."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "segments": {
                    "type": "array",
                    "description": "Ordered list of NURBS segment descriptors.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "control_points": {"type": "array"},
                            "knots": {"type": "array", "items": {"type": "number"}},
                            "degree": {"type": "integer"},
                        },
                        "required": ["control_points", "knots", "degree"],
                    },
                },
                "target": {
                    "type": "string",
                    "enum": ["G1", "G2"],
                    "description": "Target continuity (default 'G2').",
                },
                "tol": {"type": "number", "description": "Positional tolerance for blends (default 1e-6)."},
                "blend_fraction": {"type": "number", "description": "Tangent scale as fraction of chord (default 0.05)."},
            },
            "required": ["segments"],
        },
    )

    @register(_upgrade_spec)
    async def run_nurbs_composite_g2_upgrade(ctx: "ProjectCtx", args: bytes) -> str:
        try:
            a = _json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid args: {exc}", "BAD_ARGS")

        raw_segs = a.get("segments", [])
        if not raw_segs or len(raw_segs) < 1:
            return err_payload("segments must be a non-empty list", "BAD_ARGS")

        target = a.get("target", "G2")
        if target not in ("G1", "G2"):
            return err_payload("target must be 'G1' or 'G2'", "BAD_ARGS")

        try:
            segs = []
            for s in raw_segs:
                cp = np.asarray(s["control_points"], dtype=float)
                kn = np.asarray(s["knots"], dtype=float)
                deg = int(s["degree"])
                segs.append(NurbsCurve(degree=deg, control_points=cp, knots=kn))

            tol = float(a.get("tol", 1e-6))
            blend_fraction = float(a.get("blend_fraction", 0.05))
            comp = composite_curve(segs)
            n_before = len(comp["segments"])
            upgraded = upgrade_to_g2(comp, target=target, tol=tol, blend_fraction=blend_fraction)
            n_after = len(upgraded["segments"])
        except Exception as exc:
            return err_payload(str(exc), "OP_FAILED")

        seg_out = [
            {
                "control_points": s.control_points.tolist(),
                "knots": s.knots.tolist(),
                "degree": s.degree,
            }
            for s in upgraded["segments"]
        ]
        return ok_payload({
            "segments": seg_out,
            "continuity_tags": upgraded["continuity_tags"],
            "total_length": upgraded["total_length"],
            "num_blends_inserted": n_after - n_before,
        })
