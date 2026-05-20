"""
network_srf.py
==============
Network surface construction: skinning, approximate network surface, and the
true Gordon / Coons-Gordon surface.

The Gordon surface (William J. Gordon, 1969) interpolates **both** families of
input curves exactly:

    G(u,v) = Σ_i L_i(v) · c_i(u)          (loft through u-family in v)
           + Σ_j M_j(u) · d_j(v)          (loft through v-family in u)
           - Σ_i Σ_j L_i(v) · M_j(u) · P_ij   (tensor-product correction)

where
    c_i   = u-direction curves at v-parameters v̄_i
    d_j   = v-direction curves at u-parameters ū_j
    L_i   = Lagrange basis polynomials for the v̄ parameter sequence
    M_j   = Lagrange basis polynomials for the ū parameter sequence
    P_ij  = c_i(ū_j) = d_j(v̄_i)  (intersection points, must agree within tol)

Public API additions (GK-42)
-----------------------------
gordon_network_srf(u_curves, v_curves, *, u_params, v_params, tol, grid_n)
    -> NurbsSurface
"""

import numpy as np
from kerf_cad_core.geom.nurbs import NurbsCurve, NurbsSurface


def network_srf(curves: list[NurbsCurve], degree_u: int = 3) -> NurbsSurface:
    if len(curves) < 2:
        raise ValueError("At least 2 curves are required for skinning")

    for i, curve in enumerate(curves):
        if curve.control_points.shape[1] != curves[0].control_points.shape[1]:
            raise ValueError(f"Curve {i} has incompatible dimension")

    num_curves = len(curves)
    num_profile_pts = curves[0].num_control_points
    dim = curves[0].control_points.shape[1]

    aligned_curves = align_knot_vectors(curves)

    degree_v = max(c.degree for c in aligned_curves)

    common_knots_v = aligned_curves[0].knots.copy()

    control_points = np.zeros((num_curves, num_profile_pts, dim))

    for i, curve in enumerate(aligned_curves):
        control_points[i, :, :] = curve.control_points

    knots_u = compute_interpolation_knots(num_curves, degree_u)
    knots_u = ensure_valid_knot_vector(knots_u, degree_u, num_curves)

    final_surface = NurbsSurface(
        degree_u=degree_u,
        degree_v=degree_v,
        control_points=control_points,
        knots_u=knots_u,
        knots_v=common_knots_v
    )

    return final_surface


def align_knot_vectors(curves: list[NurbsCurve]) -> list[NurbsCurve]:
    from kerf_cad_core.geom.nurbs import knot_insertion

    max_num_knots = max(len(c.knots) for c in curves)
    target_knots = np.linspace(0, 1, max_num_knots)

    aligned = []
    for curve in curves:
        if len(curve.knots) < max_num_knots - 1:
            num_insertions = max_num_knots - len(curve.knots)
            u_values = np.linspace(curve.knots[curve.degree],
                                    curve.knots[-curve.degree - 1],
                                    num_insertions + 2)[1:-1]
            aligned_curve = curve
            for u in u_values:
                aligned_curve = knot_insertion(aligned_curve, u)
            aligned.append(aligned_curve)
        else:
            aligned.append(curve)

    return aligned


def compute_interpolation_knots(num_points: int, degree: int) -> np.ndarray:
    num_knots = num_points + degree + 1

    if num_points <= degree:
        knots = np.zeros(num_knots)
        knots[:degree + 1] = 0.0
        knots[-degree - 1:] = 1.0
        return knots

    knots = np.zeros(num_knots)

    knots[:degree + 1] = 0.0
    knots[-degree - 1:] = 1.0

    internal_count = num_knots - 2 * (degree + 1)
    if internal_count > 0:
        internal_knots = np.linspace(0, 1, internal_count + 2)[1:-1]
        knots[degree + 1:-degree - 1] = internal_knots

    return knots


def ensure_valid_knot_vector(knots: np.ndarray, degree: int, num_control_points: int) -> np.ndarray:
    expected_length = num_control_points + degree + 1

    if len(knots) < expected_length:
        additional = np.linspace(knots[-1], 1.0, expected_length - len(knots) + 1)[1:]
        knots = np.concatenate([knots, additional])

    return knots


def network_srf_with_compatibility(curves: list[NurbsCurve],
                                    degree_u: int = 3,
                                    continuity: str = "C1") -> NurbsSurface:
    if len(curves) < 2:
        raise ValueError("At least 2 curves are required")

    if continuity == "C0":
        return network_srf(curves, degree_u)

    aligned_curves = align_knot_vectors(curves)

    if continuity == "C1":
        aligned_curves = compute_tangent_constraints(aligned_curves)

    return network_srf(aligned_curves, degree_u)


def compute_tangent_constraints(curves: list[NurbsCurve]) -> list[NurbsCurve]:
    if len(curves) < 2:
        return curves

    constrained = [curves[0]]

    for i in range(1, len(curves)):
        curve = curves[i]
        prev_curve = curves[i - 1]

        t = i / (len(curves) - 1)

        constrained.append(curve)

    return constrained


def network_srf_global(curves: list[NurbsCurve],
                       degree_u: int = 3,
                       degree_v: int = 3) -> NurbsSurface:
    if len(curves) < 2:
        raise ValueError("At least 2 curves are required")

    num_curves = len(curves)
    num_profile_pts = curves[0].num_control_points
    dim = curves[0].control_points.shape[1]

    for curve in curves:
        if curve.num_control_points != num_profile_pts:
            raise ValueError("All curves must have the same number of control points")

    aligned_curves = align_knot_vectors(curves)

    common_knots_v = aligned_curves[0].knots.copy()

    control_points = np.zeros((num_curves, num_profile_pts, dim))
    for i, curve in enumerate(aligned_curves):
        control_points[i, :, :] = curve.control_points

    if degree_u > degree_v:
        for i in range(num_curves):
            for j in range(num_profile_pts):
                for k in range(dim):
                    control_points[i, j, k] = interpolate_along_v(
                        [curves[m].control_points[j, k] for m in range(num_curves)],
                        i / (num_curves - 1) if num_curves > 1 else 0.5,
                        degree_v
                    )

    knots_u = compute_interpolation_knots(num_curves, degree_u)
    knots_u = ensure_valid_knot_vector(knots_u, degree_u, num_curves)

    return NurbsSurface(
        degree_u=degree_u,
        degree_v=degree_v,
        control_points=control_points,
        knots_u=knots_u,
        knots_v=common_knots_v
    )


def interpolate_along_v(values: list, t: float, degree: int) -> float:
    n = len(values) - 1
    if n == 0:
        return values[0]

    for k in range(1, n + 1):
        for i in range(n, k - 1, -1):
            alpha = t if i < n else 1.0
            values[i] = alpha * values[i] + (1 - alpha) * values[i - 1]

    return values[n]


def network_srf_from_cross_sections(u_curves: list[NurbsCurve],
                                    v_curves: list[NurbsCurve],
                                    degree_u: int = 3,
                                    degree_v: int = 3) -> NurbsSurface:
    if len(u_curves) < 2 or len(v_curves) < 2:
        raise ValueError("At least 2 curves in each direction required")

    u_surface = network_srf(u_curves, degree_v)
    v_surface = network_srf(v_curves, degree_u)

    num_u = u_surface.num_control_points_u
    num_v = u_surface.num_control_points_v
    dim = u_surface.control_points.shape[2]

    control_points = np.zeros((num_u, num_v, dim))

    for i in range(num_u):
        for j in range(num_v):
            control_points[i, j] = (u_surface.control_points[i, j] +
                                     v_surface.control_points[i, j]) / 2

    merged_knots_u = merge_knot_vectors([u_surface.knots_u, v_surface.knots_u])
    merged_knots_v = merge_knot_vectors([u_surface.knots_v, v_surface.knots_v])

    return NurbsSurface(
        degree_u=degree_u,
        degree_v=degree_v,
        control_points=control_points,
        knots_u=merged_knots_u,
        knots_v=merged_knots_v
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


def validate_curves_for_skinning(curves: list[NurbsCurve]) -> tuple:
    if len(curves) < 2:
        return False, "Need at least 2 curves"

    num_pts = curves[0].num_control_points
    dim = curves[0].control_points.shape[1]

    for i, curve in enumerate(curves):
        if curve.num_control_points != num_pts:
            return False, f"Curve {i} has {curve.num_control_points} control points, expected {num_pts}"
        if curve.control_points.shape[1] != dim:
            return False, f"Curve {i} has dimension {curve.control_points.shape[1]}, expected {dim}"

    return True, "Valid"


def approximate_network_srf(u_curves: list[NurbsCurve],
                           v_curves: list[NurbsCurve],
                           degree_u: int = 3,
                           degree_v: int = 3) -> NurbsSurface:
    if not u_curves or not v_curves:
        raise ValueError("Both u_curves and v_curves must be non-empty")

    num_u = len(u_curves)
    num_v = len(v_curves)

    u_aligned = align_knot_vectors(u_curves)
    v_aligned = align_knot_vectors(v_curves)

    dim = u_aligned[0].control_points.shape[1]

    num_cp_u = num_u
    num_cp_v = u_aligned[0].num_control_points

    control_points = np.zeros((num_cp_u, num_cp_v, dim))

    for i in range(num_cp_u):
        control_points[i, :, :] = u_aligned[i].control_points

    knots_u = compute_interpolation_knots(num_cp_u, degree_u)
    knots_u = ensure_valid_knot_vector(knots_u, degree_u, num_cp_u)

    knots_v = v_aligned[0].knots.copy()

    return NurbsSurface(
        degree_u=degree_u,
        degree_v=degree_v,
        control_points=control_points,
        knots_u=knots_u,
        knots_v=knots_v
    )


# ---------------------------------------------------------------------------
# GK-42  True Gordon / Coons-Gordon network surface
# ---------------------------------------------------------------------------

def _lagrange_basis(params: np.ndarray, k: int, t: float) -> float:
    """Evaluate the k-th Lagrange basis polynomial at *t* for the given
    node sequence *params*.

    L_k(t) = prod_{j != k} (t - params[j]) / (params[k] - params[j])
    """
    n = len(params)
    num = 1.0
    den = 1.0
    pk = float(params[k])
    for j in range(n):
        if j == k:
            continue
        pj = float(params[j])
        num *= (t - pj)
        den *= (pk - pj)
    if abs(den) < 1e-300:
        # Degenerate (all params equal): treat as Kronecker delta.
        return 1.0 if abs(t - pk) < 1e-12 else 0.0
    return num / den


def _eval_curve_at(curve: NurbsCurve, t: float) -> np.ndarray:
    """Evaluate *curve* at normalised parameter *t* in [0, 1], clamped."""
    u0 = float(curve.knots[curve.degree])
    u1 = float(curve.knots[-curve.degree - 1])
    u = max(u0, min(u1, u0 + t * (u1 - u0)))
    pt = curve.evaluate(u)
    p = np.asarray(pt, dtype=float).ravel()
    if p.shape[0] < 3:
        p = np.concatenate([p, np.zeros(3 - p.shape[0])])
    return p[:3]


def _make_clamped_knots_g(n: int, degree: int) -> np.ndarray:
    """Clamped uniform knot vector for *n* control points of given *degree*."""
    m = n + degree + 1
    knots = np.zeros(m)
    knots[:degree + 1] = 0.0
    knots[-(degree + 1):] = 1.0
    n_inner = m - 2 * (degree + 1)
    if n_inner > 0:
        inner = np.linspace(0.0, 1.0, n_inner + 2)[1:-1]
        knots[degree + 1:degree + 1 + n_inner] = inner
    return knots


def _grid_interpolating_surface(pts: np.ndarray) -> NurbsSurface:
    """Build a NurbsSurface interpolating an (nu x nv x 3) point grid.

    Uses degree-1 in both directions (bilinear) for 2×2 grids (exact), or
    degree-3 (cubic) for larger grids using the B-spline global interpolation
    from the Coons module.
    """
    from kerf_cad_core.geom.coons import _interpolating_surface
    nu, nv, _ = pts.shape
    deg = min(3, min(nu, nv) - 1)
    if deg < 1:
        deg = 1
    return _interpolating_surface(pts, deg, deg)


def gordon_network_srf(
    u_curves: list,
    v_curves: list,
    *,
    u_params: list = None,
    v_params: list = None,
    tol: float = 1e-6,
    grid_n: int = 20,
) -> NurbsSurface:
    """True Gordon / Coons-Gordon surface interpolating **both** curve families.

    The Gordon surface is defined as:

        G(u,v) = Σ_i L_i(v) · c_i(u)            [u-family loft]
               + Σ_j M_j(u) · d_j(v)            [v-family loft]
               - Σ_i Σ_j L_i(v) · M_j(u) · P_ij [tensor correction]

    Both families of curves are interpolated *exactly* (within *tol* of the
    grid sampling precision).

    Parameters
    ----------
    u_curves : list[NurbsCurve]
        m ≥ 1 curves running in the u-direction.  Each curve is placed at a
        specific v-parameter ``v_params[i]``.
    v_curves : list[NurbsCurve]
        n ≥ 1 curves running in the v-direction.  Each curve is placed at a
        specific u-parameter ``u_params[j]``.
    u_params : list[float] or None
        u-parameter values where each v-curve lives (length == len(v_curves)).
        If None, evenly spaced in [0, 1].
    v_params : list[float] or None
        v-parameter values where each u-curve lives (length == len(u_curves)).
        If None, evenly spaced in [0, 1].
    tol : float
        Tolerance for intersection-point agreement check (default 1e-6).
    grid_n : int
        Number of sample points per direction for the evaluation grid.
        Minimum is max(2, m, n).

    Returns
    -------
    NurbsSurface — interpolates all u_curves and all v_curves within
    the grid-sampling precision (≤ 1e-9 for straight-line inputs).

    Raises
    ------
    ValueError
        If the intersection points c_i(ū_j) and d_j(v̄_i) disagree by > tol.
    """
    m = len(u_curves)
    n = len(v_curves)
    if m < 1:
        raise ValueError("gordon_network_srf: need at least 1 u-curve")
    if n < 1:
        raise ValueError("gordon_network_srf: need at least 1 v-curve")

    # Default placement parameters: evenly spaced in [0, 1].
    if v_params is None:
        v_params = list(np.linspace(0.0, 1.0, m)) if m > 1 else [0.0]
    if u_params is None:
        u_params = list(np.linspace(0.0, 1.0, n)) if n > 1 else [0.0]

    v_params = np.asarray(v_params, dtype=float)
    u_params = np.asarray(u_params, dtype=float)

    if len(v_params) != m:
        raise ValueError(
            f"gordon_network_srf: v_params length {len(v_params)} != "
            f"len(u_curves) {m}"
        )
    if len(u_params) != n:
        raise ValueError(
            f"gordon_network_srf: u_params length {len(u_params)} != "
            f"len(v_curves) {n}"
        )

    # Compute intersection points P[i,j] = c_i(u_params[j]) = d_j(v_params[i])
    # and verify agreement within tol.
    P = np.zeros((m, n, 3))
    for i in range(m):
        for j in range(n):
            from_u = _eval_curve_at(u_curves[i], float(u_params[j]))
            from_v = _eval_curve_at(v_curves[j], float(v_params[i]))
            dist = float(np.linalg.norm(from_u - from_v))
            if dist > tol:
                raise ValueError(
                    f"gordon_network_srf: intersection mismatch at "
                    f"(i={i}, j={j}): c_i(u_params[j])={from_u} vs "
                    f"d_j(v_params[i])={from_v}, distance={dist:.6g} > "
                    f"tol={tol:.6g}"
                )
            # Average the two estimates.
            P[i, j] = 0.5 * (from_u + from_v)

    # Build the Gordon formula on a grid_n x grid_n parameter grid.
    grid_n = max(grid_n, max(m, n) + 1, 2)
    us = np.linspace(0.0, 1.0, grid_n)
    vs = np.linspace(0.0, 1.0, grid_n)

    grid = np.zeros((grid_n, grid_n, 3))
    for gi, u in enumerate(us):
        for gj, v in enumerate(vs):
            # Term 1: Σ_i L_i(v) · c_i(u)
            t1 = np.zeros(3)
            for i in range(m):
                li = _lagrange_basis(v_params, i, v)
                t1 += li * _eval_curve_at(u_curves[i], u)

            # Term 2: Σ_j M_j(u) · d_j(v)
            t2 = np.zeros(3)
            for j in range(n):
                mj = _lagrange_basis(u_params, j, u)
                t2 += mj * _eval_curve_at(v_curves[j], v)

            # Term 3: Σ_i Σ_j L_i(v) · M_j(u) · P_ij
            t3 = np.zeros(3)
            for i in range(m):
                li = _lagrange_basis(v_params, i, v)
                for j in range(n):
                    mj = _lagrange_basis(u_params, j, u)
                    t3 += li * mj * P[i, j]

            grid[gi, gj] = t1 + t2 - t3

    return _grid_interpolating_surface(grid)