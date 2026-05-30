"""nurbs_param_optimal.py — GK-P50: Optimal NURBS surface reparametrization.

Re-parametrize a NURBS surface to minimise distortion using:

* **LSCM** (Least-Squares Conformal Map, Lévy et al. 2002): minimises angle
  distortion by enforcing the Cauchy-Riemann equations in a least-squares
  sense over a triangulation of the surface.  Ideal for FEA meshing and
  texture streaming where angle fidelity matters.

* **ARAP** (As-Rigid-As-Possible, Liu-Zhou-Pommer 2008 / Sheffer-Praun-Rose
  2006 §5): iterative local-global scheme that minimises per-triangle
  similarity distortion (sum of squared deviations from nearest rotation).
  Balances angle and area distortion; preferred for mechanical surfaces.

* **Uniform**: trivial uniform sampling as a distortion baseline.

Public API
----------
reparametrize_lscm(surface, n_samples_u, n_samples_v) -> NurbsSurface
reparametrize_arap(surface, n_samples_u, n_samples_v, n_iters) -> NurbsSurface
distortion_metric(original, reparametrized, n_samples) -> dict
reparam_compare(surface, methods) -> dict

Algorithm detail
----------------
1.  *Sample* the input surface on an (n_u × n_v) grid of (u, v) parameters
    and evaluate 3-D positions.  Triangulate the grid with two triangles per
    quad cell.

2a. *LSCM*: apply the existing ``uv_unwrap.lscm_unwrap`` solver (reused from
    Wave 4BB) to the 3-D triangulation.  This returns optimal (s, t) ∈ ℝ² for
    each sampled vertex by solving the Cauchy-Riemann least-squares system.

2b. *ARAP*: initialise with LSCM, then alternate:
    - Local step: for each triangle find the nearest rotation R_t (SVD of the
      Jacobian of the current map).
    - Global step: solve a sparse linear system to minimise ∑_t ||J_t - R_t||²_F
      subject to pinned boundary vertices.
    Iterated for ``n_iters`` rounds.

3.  *Re-fit*: the (s, t) UV coordinates become the new parameter grid.
    A bicubic (degree-3) NURBS surface is re-fitted through the original 3-D
    point grid using global tensor-product least-squares fitting
    (Piegl & Tiller §9.4).

4.  *Distortion metrics*: angle distortion is the mean angular change per
    triangle; area distortion is the mean ratio of UV-triangle area to 3-D
    surface-element area.

References
----------
* Lévy, B., Petitjean, S., Ray, N., Maillot, J., 2002.  "Least Squares
  Conformal Maps for Automatic Texture Atlas Generation."  SIGGRAPH 2002.
* Liu, L., Zhang, L., Xu, Y., Gotsman, C., Gortler, S.J., 2008.  "A Local/
  Global Approach to Mesh Parameterisation."  SGP 2008.
* Sheffer, A., Praun, E., Rose, K., 2006.  "Mesh Parameterisation Methods and
  their Applications."  Foundations and Trends in CG&V, §5.
"""
from __future__ import annotations

import math
from typing import Dict, List, Optional, Tuple

import numpy as np

from kerf_cad_core.geom.nurbs import NurbsSurface, surface_evaluate, find_span, _basis_funcs
from kerf_cad_core.geom.uv_unwrap import lscm_unwrap

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _sample_surface(
    surface: NurbsSurface,
    n_u: int,
    n_v: int,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Sample surface on an n_u × n_v grid.

    Returns
    -------
    pts   : (n_u*n_v, 3) array of 3-D positions
    u_vals: (n_u,) parameter values in u
    v_vals: (n_v,) parameter values in v
    """
    p = surface.degree_u
    q = surface.degree_v
    u0 = float(surface.knots_u[p])
    u1 = float(surface.knots_u[-(p + 1)])
    v0 = float(surface.knots_v[q])
    v1 = float(surface.knots_v[-(q + 1)])

    u_vals = np.linspace(u0, u1, n_u)
    v_vals = np.linspace(v0, v1, n_v)

    pts = np.zeros((n_u * n_v, 3))
    for i, u in enumerate(u_vals):
        for j, v in enumerate(v_vals):
            pts[i * n_v + j] = surface_evaluate(surface, float(u), float(v))

    return pts, u_vals, v_vals


def _grid_triangulation(n_u: int, n_v: int) -> List[List[int]]:
    """Build triangles for an n_u × n_v vertex grid."""
    faces: List[List[int]] = []
    for i in range(n_u - 1):
        for j in range(n_v - 1):
            a = i * n_v + j
            b = a + 1
            c = (i + 1) * n_v + j + 1
            d = (i + 1) * n_v + j
            faces.append([a, b, c])
            faces.append([a, c, d])
    return faces


def _normalize_uv(uv: np.ndarray) -> np.ndarray:
    """Normalise UV coordinates to [0, 1] × [0, 1]."""
    uv = uv.copy()
    u_min, v_min = uv[:, 0].min(), uv[:, 1].min()
    u_max, v_max = uv[:, 0].max(), uv[:, 1].max()
    u_range = u_max - u_min if u_max - u_min > 1e-12 else 1.0
    v_range = v_max - v_min if v_max - v_min > 1e-12 else 1.0
    uv[:, 0] = (uv[:, 0] - u_min) / u_range
    uv[:, 1] = (uv[:, 1] - v_min) / v_range
    return uv


# ---------------------------------------------------------------------------
# NURBS surface re-fitting from scattered (s,t) → 3D data
# ---------------------------------------------------------------------------


def _fit_nurbs_surface(
    st_coords: np.ndarray,   # (N, 2) — re-mapped parameter coords in [0,1]^2
    xyz_pts: np.ndarray,     # (N, 3) — corresponding 3-D positions
    n_u: int,
    n_v: int,
    degree: int = 3,
) -> NurbsSurface:
    """Fit a tensor-product NURBS surface through a scattered (s,t)→3D dataset.

    Performs global tensor-product least-squares fitting: builds a basis matrix
    B where B[k, i*n_cp_v + j] = N_i(s_k) * N_j(t_k), then solves
    B @ ctrl.reshape(-1, 3) ≈ xyz_pts in the least-squares sense.

    Parameters
    ----------
    st_coords : (N, 2) ndarray
        Parameter coordinates for each point; expected in [0, 1]^2.
    xyz_pts : (N, 3) ndarray
        3-D positions.
    n_u, n_v : int
        Grid dimensions (used only for control-point count heuristic).
    degree : int
        NURBS degree (default 3).

    Returns
    -------
    NurbsSurface with ``degree_u == degree_v == degree``.
    """
    N = len(st_coords)

    # Keep control-point count conservative so the basis matrix stays full-rank.
    # LSCM UV grids are typically 45°-rotated, covering only ~50% of the parameter
    # square, so we limit n_cp to avoid underdetermined basis rows.
    n_cp_u = max(min(n_u // 3, degree + 2), degree + 1)
    n_cp_v = max(min(n_v // 3, degree + 2), degree + 1)

    def _uniform_knots(n_ctrl: int, deg: int) -> np.ndarray:
        n_int = n_ctrl - deg - 1
        internal = np.linspace(0.0, 1.0, n_int + 2)[1:-1] if n_int > 0 else np.array([])
        return np.concatenate([np.zeros(deg + 1), internal, np.ones(deg + 1)])

    knots_u = _uniform_knots(n_cp_u, degree)
    knots_v = _uniform_knots(n_cp_v, degree)
    n_ctrl_total = n_cp_u * n_cp_v

    def _basis_val(u_val: float, knots: np.ndarray, n_ctrl: int, deg: int) -> np.ndarray:
        """Evaluate all basis functions at u_val; returns (n_ctrl,) array."""
        N_arr = np.zeros(n_ctrl)
        u_clip = float(np.clip(u_val, knots[deg], knots[-(deg + 1)]))
        span = find_span(n_ctrl - 1, deg, u_clip, knots)
        N_loc = _basis_funcs(span, u_clip, deg, knots)
        for r in range(deg + 1):
            N_arr[span - deg + r] = N_loc[r]
        return N_arr

    # Build tensor-product basis matrix B: shape (N, n_cp_u * n_cp_v)
    B = np.zeros((N, n_ctrl_total))
    for k in range(N):
        s_k = float(st_coords[k, 0])
        t_k = float(st_coords[k, 1])
        Nu = _basis_val(s_k, knots_u, n_cp_u, degree)   # (n_cp_u,)
        Nv = _basis_val(t_k, knots_v, n_cp_v, degree)   # (n_cp_v,)
        # Tensor product: B[k, i*n_cp_v + j] = Nu[i] * Nv[j]
        B[k] = np.outer(Nu, Nv).ravel()

    # Solve B @ ctrl_flat ≈ xyz_pts  (least squares, 3 RHS)
    ctrl_flat, _, _, _ = np.linalg.lstsq(B, xyz_pts, rcond=None)  # (n_ctrl_total, 3)
    ctrl_pts = ctrl_flat.reshape(n_cp_u, n_cp_v, 3)

    return NurbsSurface(
        degree_u=degree,
        degree_v=degree,
        control_points=ctrl_pts,
        knots_u=knots_u,
        knots_v=knots_v,
        weights=None,
    )


# ---------------------------------------------------------------------------
# LSCM reparametrization
# ---------------------------------------------------------------------------


def reparametrize_lscm(
    surface: NurbsSurface,
    n_samples_u: int = 20,
    n_samples_v: int = 20,
) -> NurbsSurface:
    """Reparametrize a NURBS surface using LSCM (Lévy 2002).

    Samples the surface densely, builds a triangulation, applies LSCM to find
    optimal (s, t) UV coordinates that minimise angle distortion, then re-fits
    a bicubic NURBS surface through the 3-D point grid using the new parameters.

    Parameters
    ----------
    surface : NurbsSurface
        Input NURBS surface to reparametrize.
    n_samples_u : int
        Number of sample points in the u direction (default 20).
    n_samples_v : int
        Number of sample points in the v direction (default 20).

    Returns
    -------
    NurbsSurface
        Re-fitted bicubic NURBS surface with LSCM-optimal parameterisation.

    References
    ----------
    Lévy, B. et al. (2002). "Least Squares Conformal Maps for Automatic
    Texture Atlas Generation." SIGGRAPH 2002.
    """
    n_u = max(n_samples_u, 4)
    n_v = max(n_samples_v, 4)

    pts, _, _ = _sample_surface(surface, n_u, n_v)
    faces = _grid_triangulation(n_u, n_v)

    mesh = {
        "vertices": pts.tolist(),
        "faces": faces,
    }

    result = lscm_unwrap(mesh)
    uv_list = result["uv"]

    # Convert to array and normalise to [0, 1]^2
    uv = np.array(uv_list, dtype=float)  # (n_u*n_v, 2)
    uv = _normalize_uv(uv)

    # Re-fit NURBS surface using optimal UV as parameter values
    return _fit_nurbs_surface(uv, pts, n_u, n_v, degree=3)


# ---------------------------------------------------------------------------
# ARAP reparametrization
# ---------------------------------------------------------------------------


def _arap_local_step(
    uv: np.ndarray,          # (N, 2) current UV
    pts_3d: np.ndarray,      # (N, 3) 3-D positions
    faces: List[List[int]],  # triangles
) -> np.ndarray:
    """Local step: compute per-triangle best-fit rotation.

    For each triangle, compute J_t (the Jacobian from UV to 3-D projected
    local frame), then extract the nearest rotation via SVD.

    Returns
    -------
    rotations : list of (2, 2) rotation matrices, one per triangle.
    """
    rotations = []
    for f in faces:
        i0, i1, i2 = f

        # UV edge vectors
        uv0, uv1, uv2 = uv[i0], uv[i1], uv[i2]
        du1 = uv1 - uv0
        du2 = uv2 - uv0

        # 3D edge vectors projected to 2D using local triangle frame
        p0, p1, p2 = pts_3d[i0], pts_3d[i1], pts_3d[i2]
        e1 = p1 - p0
        e2 = p2 - p0
        len_e1 = np.linalg.norm(e1)
        if len_e1 < 1e-12:
            rotations.append(np.eye(2))
            continue
        x_ax = e1 / len_e1
        n_ax = np.cross(e1, e2)
        n_norm = np.linalg.norm(n_ax)
        if n_norm < 1e-12:
            rotations.append(np.eye(2))
            continue
        n_ax /= n_norm
        y_ax = np.cross(n_ax, x_ax)
        # 2D local coordinates of e1 and e2
        q1 = np.array([np.dot(e1, x_ax), np.dot(e1, y_ax)])
        q2 = np.array([np.dot(e2, x_ax), np.dot(e2, y_ax)])

        # Build the Jacobian J such that J @ du = dq
        # [q1 | q2] = J @ [du1 | du2]  ->  J = [q1|q2] @ inv([du1|du2])
        D_uv = np.column_stack([du1, du2])   # (2, 2)
        D_q = np.column_stack([q1, q2])      # (2, 2)

        det = D_uv[0, 0] * D_uv[1, 1] - D_uv[0, 1] * D_uv[1, 0]
        if abs(det) < 1e-12:
            rotations.append(np.eye(2))
            continue

        J = D_q @ np.linalg.inv(D_uv)

        # Nearest rotation via SVD
        U, _s, Vt = np.linalg.svd(J)
        R = U @ Vt
        if np.linalg.det(R) < 0:
            U[:, -1] *= -1
            R = U @ Vt
        rotations.append(R)

    return rotations


def _arap_global_step(
    uv: np.ndarray,          # (N, 2) current UV
    pts_3d: np.ndarray,      # (N, 3) 3-D positions
    faces: List[List[int]],  # triangles
    rotations: list,         # per-triangle best-fit 2×2 rotation matrices
    pin_dict: Dict[int, Tuple[float, float]],
) -> np.ndarray:
    """Global step: solve sparse linear system for ARAP.

    Minimise  ∑_t w_t ∑_{e ∈ t} ||Δuv_e - R_t Δq_e||²_F

    where Δuv_e is the UV edge vector, Δq_e is the corresponding projected
    3-D edge vector in the local frame, and R_t is the per-triangle rotation
    from the local step.

    The system is assembled per edge as:
        for each (va, vb) edge with target rhs = R_t @ q_edge:
            w * (uv[va] - uv[vb])^2 → diagonal & off-diagonal terms
            RHS: w * rhs

    Solved independently for U and V coordinates.
    """
    n_verts = len(uv)
    free_verts = [i for i in range(n_verts) if i not in pin_dict]
    n_free = len(free_verts)
    if n_free == 0:
        return uv.copy()
    free_idx = {vi: k for k, vi in enumerate(free_verts)}

    try:
        from scipy.sparse import lil_matrix
        from scipy.sparse.linalg import spsolve
        use_sparse = True
    except ImportError:
        use_sparse = False

    # Separate systems for U and V (each n_free × n_free)
    if use_sparse:
        Au = lil_matrix((n_free, n_free))
        Av = lil_matrix((n_free, n_free))
    else:
        Au = np.zeros((n_free, n_free))
        Av = np.zeros((n_free, n_free))

    bu = np.zeros(n_free)
    bv = np.zeros(n_free)

    for f_idx, f in enumerate(faces):
        i0, i1, i2 = f
        R = rotations[f_idx]  # (2, 2)

        # 3D edge vectors projected to local 2D triangle frame
        p0, p1, p2 = pts_3d[i0], pts_3d[i1], pts_3d[i2]
        e1 = p1 - p0
        e2 = p2 - p0
        len_e1 = np.linalg.norm(e1)
        if len_e1 < 1e-12:
            continue
        x_ax = e1 / len_e1
        n_ax = np.cross(e1, e2)
        n_norm = np.linalg.norm(n_ax)
        if n_norm < 1e-12:
            continue
        n_ax /= n_norm
        y_ax = np.cross(n_ax, x_ax)

        q1 = np.array([np.dot(e1, x_ax), np.dot(e1, y_ax)])
        q2 = np.array([np.dot(e2, x_ax), np.dot(e2, y_ax)])

        area3d = abs(q1[0] * q2[1] - q2[0] * q1[1]) * 0.5
        w = max(area3d, 1e-12)

        # Per-edge: target = R @ q_edge, constraint: uv[vb] - uv[va] = target
        edges = [
            (i0, i1, R @ q1),
            (i0, i2, R @ q2),
            (i1, i2, R @ (q2 - q1)),
        ]

        for va, vb, target_uv in edges:
            # Minimise w * ||uv[vb] - uv[va] - target||^2
            # Expands to: for U:  w*(ub - ua)^2 - 2*w*(ub-ua)*tu
            # Gradient w.r.t. ua (if free): 2w*(ua - ub) + 2w*tu → Au[a,a]+=w, Au[a,b]-=w, bu[a]-=w*tu
            # Gradient w.r.t. ub (if free): 2w*(ub - ua) - 2w*tu → Au[b,b]+=w, Au[b,a]-=w, bu[b]+=w*tu

            # ∂E/∂u_va = -2w*(u_vb - u_va - tu)  → A[ra,ra]+=w; A[ra,rb]-=w; b[ra]+=w*(-tu)
            # ∂E/∂u_vb = +2w*(u_vb - u_va - tu)  → A[rb,rb]+=w; A[rb,ra]-=w; b[rb]+=w*tu
            for (row_vi, rhs_sign) in [(va, -1.0), (vb, +1.0)]:
                if row_vi not in free_idx:
                    continue
                ri = free_idx[row_vi]

                # Diagonal
                Au[ri, ri] += w
                Av[ri, ri] += w

                # Off-diagonal / RHS for the other endpoint
                other_vi = vb if row_vi == va else va
                if other_vi in free_idx:
                    ci = free_idx[other_vi]
                    Au[ri, ci] -= w
                    Av[ri, ci] -= w
                else:
                    # Pinned: known value goes to RHS
                    pin_u, pin_v = pin_dict[other_vi]
                    # The term -w * u_other goes to RHS as +w * pin_val
                    bu[ri] += w * float(pin_u)
                    bv[ri] += w * float(pin_v)

                # Target RHS: derivative of -2w*target*(u_vb-u_va) w.r.t. u_row_vi
                # = -2w*target*rhs_sign  → normal equations: b[ri] += w*rhs_sign*target
                bu[ri] += w * rhs_sign * float(target_uv[0])
                bv[ri] += w * rhs_sign * float(target_uv[1])

    # Tikhonov regularisation for stability
    lam = 1e-8

    if use_sparse:
        from scipy.sparse import eye as sp_eye
        Au_csr = Au.tocsr() + lam * sp_eye(n_free, format='csr')
        Av_csr = Av.tocsr() + lam * sp_eye(n_free, format='csr')
        try:
            sol_u = spsolve(Au_csr, bu)
            sol_v = spsolve(Av_csr, bv)
        except Exception:
            sol_u = np.linalg.lstsq(Au_csr.toarray(), bu, rcond=None)[0]
            sol_v = np.linalg.lstsq(Av_csr.toarray(), bv, rcond=None)[0]
    else:
        Au += lam * np.eye(n_free)
        Av += lam * np.eye(n_free)
        sol_u, _, _, _ = np.linalg.lstsq(Au, bu, rcond=None)
        sol_v, _, _, _ = np.linalg.lstsq(Av, bv, rcond=None)

    new_uv = uv.copy()
    for k, vi in enumerate(free_verts):
        new_uv[vi, 0] = float(sol_u[k])
        new_uv[vi, 1] = float(sol_v[k])
    for vi, (pu, pv) in pin_dict.items():
        new_uv[vi] = [float(pu), float(pv)]

    return new_uv


def reparametrize_arap(
    surface: NurbsSurface,
    n_samples_u: int = 20,
    n_samples_v: int = 20,
    n_iters: int = 20,
) -> NurbsSurface:
    """Reparametrize a NURBS surface using ARAP (Liu et al. 2008).

    Applies the As-Rigid-As-Possible iterative local-global scheme to find
    a UV parametrization that minimises per-triangle shape distortion (a mix
    of angle and area).  Initialised from LSCM for fast convergence.

    Parameters
    ----------
    surface : NurbsSurface
        Input NURBS surface.
    n_samples_u : int
        Number of sample points in u (default 20).
    n_samples_v : int
        Number of sample points in v (default 20).
    n_iters : int
        Number of ARAP local-global iterations (default 20).

    Returns
    -------
    NurbsSurface
        Re-fitted bicubic NURBS surface with ARAP-optimal parameterisation.

    References
    ----------
    Liu, L., Zhang, L., Xu, Y., Gotsman, C., Gortler, S.J. (2008).
    "A Local/Global Approach to Mesh Parameterisation." SGP 2008.
    """
    n_u = max(n_samples_u, 4)
    n_v = max(n_samples_v, 4)

    pts, _, _ = _sample_surface(surface, n_u, n_v)
    faces = _grid_triangulation(n_u, n_v)

    # Initialise with LSCM
    mesh = {"vertices": pts.tolist(), "faces": faces}
    lscm_result = lscm_unwrap(mesh)
    uv = np.array(lscm_result["uv"], dtype=float)
    uv = _normalize_uv(uv)

    # Pin two corner vertices to fix translation+rotation degrees of freedom
    n_verts = n_u * n_v
    # Use top-left corner (index 0) and bottom-right corner (index n_verts-1)
    pin_dict: Dict[int, Tuple[float, float]] = {
        0: (float(uv[0, 0]), float(uv[0, 1])),
        n_verts - 1: (float(uv[n_verts - 1, 0]), float(uv[n_verts - 1, 1])),
    }

    for _ in range(n_iters):
        rots = _arap_local_step(uv, pts, faces)
        new_uv = _arap_global_step(uv, pts, faces, rots, pin_dict)
        new_uv = _normalize_uv(new_uv)
        # Re-pin
        for vi, (pu, pv) in pin_dict.items():
            new_uv[vi] = [pu, pv]
        if np.linalg.norm(new_uv - uv) < 1e-8:
            break
        uv = new_uv

    return _fit_nurbs_surface(uv, pts, n_u, n_v, degree=3)


# ---------------------------------------------------------------------------
# Distortion metrics
# ---------------------------------------------------------------------------


def _parametric_distortion(surface: NurbsSurface, n: int) -> Tuple[List[float], List[float]]:
    """Measure UV-to-3D stretch distortion for a surface.

    Builds a uniform UV triangulation and for each 3D triangle computes:
    - Angle distortion: |angle in UV space - angle in 3D triangle| (radians)
    - Area distortion: |UV_area / 3D_area - 1|

    The UV and 3D triangles are compared via their angles and area ratios.
    For a perfect conformal parametrization, angle_distortion → 0 for all tri.
    For a perfect equi-areal parametrization, area_distortion → 0.
    """
    pts_3d, _, _ = _sample_surface(surface, n, n)
    faces = _grid_triangulation(n, n)

    # UV coordinates: normalised uniform grid
    uv = np.zeros((n * n, 2))
    for i in range(n):
        for j in range(n):
            uv[i * n + j] = [i / (n - 1) if n > 1 else 0.0,
                              j / (n - 1) if n > 1 else 0.0]

    angle_errs: List[float] = []
    area_ratios: List[float] = []

    for f in faces:
        i0, i1, i2 = f

        # 3D triangle
        a3, b3, c3 = pts_3d[i0], pts_3d[i1], pts_3d[i2]
        e1_3d = b3 - a3
        e2_3d = c3 - a3
        area_3d = 0.5 * np.linalg.norm(np.cross(e1_3d, e2_3d))
        if area_3d < 1e-14:
            continue

        # UV triangle
        a_uv, b_uv, c_uv = uv[i0], uv[i1], uv[i2]
        e1_uv = b_uv - a_uv
        e2_uv = c_uv - a_uv
        area_uv = abs(e1_uv[0] * e2_uv[1] - e1_uv[1] * e2_uv[0]) * 0.5
        if area_uv < 1e-14:
            continue

        # Area ratio: want UV area proportional to 3D area
        # Distortion = deviation from a perfectly uniform mapping
        # (sum UV areas = sum 3D areas after normalization)
        area_ratios.append(area_uv / area_3d)

        # Angle at vertex 0 in both domains
        def _angle(e1: np.ndarray, e2: np.ndarray) -> float:
            n1 = np.linalg.norm(e1)
            n2 = np.linalg.norm(e2)
            if n1 < 1e-14 or n2 < 1e-14:
                return 0.0
            cos_a = float(np.dot(e1, e2)) / (n1 * n2)
            cos_a = max(-1.0, min(1.0, cos_a))
            return math.acos(cos_a)

        ang_uv = _angle(e1_uv, e2_uv)
        ang_3d = _angle(e1_3d, e2_3d)
        angle_errs.append(abs(ang_uv - ang_3d))

    return angle_errs, area_ratios


def distortion_metric(
    original: NurbsSurface,
    reparametrized: NurbsSurface,
    n_samples: int = 100,
) -> dict:
    """Compute angle and area distortion of a reparametrized NURBS surface.

    Measures the distortion introduced by the parametrization itself: for each
    surface, compares the shape of UV parameter triangles to the corresponding
    3D surface triangles.  A conformal map minimises angle distortion; an
    equi-areal map minimises area distortion.

    The comparison between ``original`` and ``reparametrized`` reports the
    *improvement* in distortion (negative = reparametrized is better).

    Parameters
    ----------
    original : NurbsSurface
        The original surface.
    reparametrized : NurbsSurface
        The reparametrized surface.
    n_samples : int
        Grid resolution for triangulation per direction (sqrt of total).

    Returns
    -------
    dict with keys:
        ``angle_distortion``       : mean angle distortion (reparametrized)
        ``area_distortion``        : mean area-ratio CV (reparametrized)
        ``max_angle_distortion``   : max angle distortion (reparametrized)
        ``max_area_distortion``    : max area-ratio deviation (reparametrized)
        ``orig_angle_distortion``  : mean angle distortion (original)
        ``orig_area_distortion``   : mean area-ratio CV (original)
        ``angle_improvement``      : original - reparametrized angle distortion
        ``area_improvement``       : original - reparametrized area distortion
        ``n_triangles``            : number of triangles evaluated
    """
    n = max(int(math.sqrt(n_samples)), 4)

    orig_ang, orig_area = _parametric_distortion(original, n)
    new_ang, new_area = _parametric_distortion(reparametrized, n)

    if not orig_ang or not new_ang:
        return {
            "angle_distortion": 0.0,
            "area_distortion": 0.0,
            "max_angle_distortion": 0.0,
            "max_area_distortion": 0.0,
            "orig_angle_distortion": 0.0,
            "orig_area_distortion": 0.0,
            "angle_improvement": 0.0,
            "area_improvement": 0.0,
            "n_triangles": 0,
        }

    # Area distortion as coefficient of variation of area ratios (lower = more uniform)
    def _cv(vals: List[float]) -> float:
        arr = np.array(vals)
        mean = float(arr.mean())
        return float(arr.std() / mean) if mean > 1e-14 else 0.0

    orig_angle = float(np.mean(orig_ang))
    orig_area_cv = _cv(orig_area)
    new_angle = float(np.mean(new_ang))
    new_area_cv = _cv(new_area)

    return {
        "angle_distortion": new_angle,
        "area_distortion": new_area_cv,
        "max_angle_distortion": float(np.max(new_ang)),
        "max_area_distortion": float(np.max(np.abs(np.array(new_area) - np.mean(new_area)))),
        "orig_angle_distortion": orig_angle,
        "orig_area_distortion": orig_area_cv,
        "angle_improvement": orig_angle - new_angle,
        "area_improvement": orig_area_cv - new_area_cv,
        "n_triangles": min(len(orig_ang), len(new_ang)),
    }


# ---------------------------------------------------------------------------
# Comparison helper
# ---------------------------------------------------------------------------


def _reparametrize_uniform(
    surface: NurbsSurface,
    n_samples_u: int = 20,
    n_samples_v: int = 20,
) -> NurbsSurface:
    """Re-fit surface with uniform (identity) parametrization as baseline."""
    n_u = max(n_samples_u, 4)
    n_v = max(n_samples_v, 4)
    pts, _, _ = _sample_surface(surface, n_u, n_v)

    # Uniform UV grid
    us = np.linspace(0.0, 1.0, n_u)
    vs = np.linspace(0.0, 1.0, n_v)
    uv = np.zeros((n_u * n_v, 2))
    for i in range(n_u):
        for j in range(n_v):
            uv[i * n_v + j] = [us[i], vs[j]]

    return _fit_nurbs_surface(uv, pts, n_u, n_v, degree=3)


def reparam_compare(
    surface: NurbsSurface,
    methods: Optional[List[str]] = None,
    n_samples_u: int = 20,
    n_samples_v: int = 20,
    n_iters: int = 20,
) -> dict:
    """Compare distortion metrics across reparametrization methods.

    Parameters
    ----------
    surface : NurbsSurface
        The surface to analyse.
    methods : list of str, optional
        Subset of ``['lscm', 'arap', 'uniform']`` (default: all three).
    n_samples_u : int
        Grid resolution in u.
    n_samples_v : int
        Grid resolution in v.
    n_iters : int
        ARAP iteration count.

    Returns
    -------
    dict
        Maps each method name to its :func:`distortion_metric` result, plus a
        ``"best_angle"`` key naming the method with lowest angle distortion and
        a ``"best_area"`` key naming the method with lowest area distortion.
    """
    if methods is None:
        methods = ["lscm", "arap", "uniform"]

    results: dict = {}
    reparam_funcs = {
        "lscm": lambda s: reparametrize_lscm(s, n_samples_u, n_samples_v),
        "arap": lambda s: reparametrize_arap(s, n_samples_u, n_samples_v, n_iters),
        "uniform": lambda s: _reparametrize_uniform(s, n_samples_u, n_samples_v),
    }

    for method in methods:
        if method not in reparam_funcs:
            results[method] = {"error": f"Unknown method '{method}'"}
            continue
        try:
            reparam_surf = reparam_funcs[method](surface)
            metrics = distortion_metric(surface, reparam_surf, n_samples=n_samples_u * n_samples_v)
            results[method] = metrics
        except Exception as exc:
            results[method] = {"error": str(exc)}

    # Determine best method per metric
    valid = {m: v for m, v in results.items() if "error" not in v}
    if valid:
        best_angle = min(valid, key=lambda m: valid[m]["angle_distortion"])
        best_area = min(valid, key=lambda m: valid[m]["area_distortion"])
    else:
        best_angle = best_area = "none"

    results["best_angle"] = best_angle
    results["best_area"] = best_area
    return results


# ---------------------------------------------------------------------------
# LLM tool registration (gated — graceful no-op when registry absent)
# ---------------------------------------------------------------------------

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register  # type: ignore[import]
    from kerf_core.utils.context import ProjectCtx  # type: ignore[import]
    import json as _json
    _REGISTRY_AVAILABLE = True
except ImportError:
    _REGISTRY_AVAILABLE = False


if _REGISTRY_AVAILABLE:

    _reparam_spec = ToolSpec(
        name="nurbs_reparametrize_optimal",
        description=(
            "Reparametrize a NURBS surface to minimise distortion using LSCM (angle-preserving) "
            "or ARAP (shape-preserving) methods, then report distortion metrics.\n"
            "\n"
            "LSCM (Lévy 2002): minimises angle distortion — best for texture mapping and FEA "
            "meshing where conformal (angle-preserving) parameters matter.\n"
            "ARAP (Liu et al. 2008): balances angle and area distortion — better for mechanical "
            "surfaces and mesh generation.\n"
            "\n"
            "Returns:\n"
            "  ok                  : bool\n"
            "  method              : str ('lscm' | 'arap')\n"
            "  surface             : {control_points, knots_u, knots_v, degree_u, degree_v}\n"
            "  distortion          : {angle_distortion, area_distortion, ...}\n"
            "  comparison          : per-method distortion if compare=true\n"
            "\n"
            "Errors: {ok:false, reason}.  Never raises."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "control_points": {
                    "type": "array",
                    "description": "NURBS control point grid [[[x,y,z], ...], ...] (nu x nv x 3).",
                },
                "knots_u": {
                    "type": "array",
                    "description": "Knot vector in u direction.",
                    "items": {"type": "number"},
                },
                "knots_v": {
                    "type": "array",
                    "description": "Knot vector in v direction.",
                    "items": {"type": "number"},
                },
                "degree_u": {
                    "type": "integer",
                    "description": "NURBS degree in u (default 3).",
                },
                "degree_v": {
                    "type": "integer",
                    "description": "NURBS degree in v (default 3).",
                },
                "method": {
                    "type": "string",
                    "description": "Reparametrization method: 'lscm' (default) or 'arap'.",
                    "enum": ["lscm", "arap"],
                },
                "n_samples_u": {
                    "type": "integer",
                    "description": "Sample grid resolution in u (default 20).",
                },
                "n_samples_v": {
                    "type": "integer",
                    "description": "Sample grid resolution in v (default 20).",
                },
                "n_iters": {
                    "type": "integer",
                    "description": "ARAP iteration count (default 20, ignored for LSCM).",
                },
                "compare": {
                    "type": "boolean",
                    "description": "If true, also compute distortion for all 3 methods (default false).",
                },
            },
            "required": ["control_points", "knots_u", "knots_v"],
        },
    )

    @register(_reparam_spec)
    async def run_nurbs_reparametrize_optimal(ctx: "ProjectCtx", args: bytes) -> str:
        try:
            a = _json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid args: {exc}", "BAD_ARGS")

        cp_raw = a.get("control_points")
        ku_raw = a.get("knots_u")
        kv_raw = a.get("knots_v")

        if cp_raw is None or ku_raw is None or kv_raw is None:
            return err_payload(
                "control_points, knots_u, and knots_v are required", "BAD_ARGS"
            )

        try:
            cp = np.array(cp_raw, dtype=float)
            if cp.ndim != 3 or cp.shape[2] != 3:
                return err_payload(
                    "control_points must be (nu, nv, 3)", "BAD_ARGS"
                )
            ku = np.array(ku_raw, dtype=float)
            kv = np.array(kv_raw, dtype=float)
            deg_u = int(a.get("degree_u", 3))
            deg_v = int(a.get("degree_v", 3))
        except Exception as exc:
            return err_payload(f"invalid surface data: {exc}", "BAD_ARGS")

        method = a.get("method", "lscm")
        if method not in ("lscm", "arap"):
            return err_payload("method must be 'lscm' or 'arap'", "BAD_ARGS")

        n_su = int(a.get("n_samples_u", 20))
        n_sv = int(a.get("n_samples_v", 20))
        n_iters = int(a.get("n_iters", 20))
        do_compare = bool(a.get("compare", False))

        try:
            surface = NurbsSurface(
                degree_u=deg_u,
                degree_v=deg_v,
                control_points=cp,
                knots_u=ku,
                knots_v=kv,
            )
        except Exception as exc:
            return err_payload(f"could not construct NurbsSurface: {exc}", "BAD_ARGS")

        try:
            if method == "lscm":
                reparam = reparametrize_lscm(surface, n_su, n_sv)
            else:
                reparam = reparametrize_arap(surface, n_su, n_sv, n_iters)
        except Exception as exc:
            return err_payload(f"reparametrization failed: {exc}", "OP_FAILED")

        try:
            metrics = distortion_metric(surface, reparam, n_samples=n_su * n_sv)
        except Exception as exc:
            metrics = {"error": str(exc)}

        payload: dict = {
            "method": method,
            "surface": {
                "control_points": reparam.control_points.tolist(),
                "knots_u": reparam.knots_u.tolist(),
                "knots_v": reparam.knots_v.tolist(),
                "degree_u": reparam.degree_u,
                "degree_v": reparam.degree_v,
            },
            "distortion": metrics,
        }

        if do_compare:
            try:
                comparison = reparam_compare(surface, methods=["lscm", "arap", "uniform"],
                                             n_samples_u=n_su, n_samples_v=n_sv,
                                             n_iters=n_iters)
                payload["comparison"] = comparison
            except Exception as exc:
                payload["comparison"] = {"error": str(exc)}

        return ok_payload(payload)
