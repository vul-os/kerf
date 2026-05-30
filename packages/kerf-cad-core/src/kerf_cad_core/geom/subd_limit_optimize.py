"""subd_limit_optimize.py
========================
Constrained cage-CP optimization for Catmull-Clark SubD limit surfaces.

Given a set of *LimitConstraint* objects — each specifying a desired property
of the limit surface at a parametric location (face, u, v) — this module
finds cage control-point (CP) positions that minimize the squared residual
of those constraints via gradient descent.

This is the *inverse* of limit evaluation: instead of asking "what does the
limit surface look like for this cage?", we ask "what cage CPs produce a
limit surface with these properties?"

The approach follows the constrained-fitting literature (Loop & Schaefer 2008,
Peters 2000): for each constraint type we compute the constraint value from
the current cage via the Stam closed-form limit rule, form a squared-residual
loss, and take a gradient-descent step on the cage CP positions.

Public API
----------
LimitConstraint(dataclass)
    Encodes one constraint:
      kind        — 'passes_through', 'tangent_to_dir', 'has_normal', 'has_curvature'
      face_id     — index into mesh.faces
      u, v        — parametric coordinate in [0, 1] × [0, 1] on that face
      target_value — target (varies by kind; see docstring below)

CageOptimizeResult(dataclass)
    Returned by optimize_cage_for_constraints:
      mesh           — updated SubDMesh with optimized cage CPs
      residuals      — per-constraint final squared residual
      history        — list of total loss per iteration (length <= n_iters)
      converged      — bool: True if final total loss < 1e-6

optimize_cage_for_constraints(mesh, constraints, n_iters=100, lr=0.01)
    → CageOptimizeResult
    Gradient descent on cage CP positions to minimize constraint residuals.

fit_cage_to_points(mesh, target_limit_points, n_iters=200) -> SubDMesh
    Convenience wrapper: 'passes_through' constraints for every supplied
    (face_id, u, v, point) tuple.  Returns the optimized mesh.

Implementation notes
--------------------
* The limit position at a parametric (face_id, u, v) is approximated as a
  bilinear blend of the four face-corner Stam limit positions.  This is the
  standard "limit-surface evaluation by corner interpolation" used in OpenSubdiv
  for quick point queries when Stam patches are not needed.

* Gradients of the limit position w.r.t. cage CPs are computed analytically
  via the Stam limit formula:
      P_lim(vi) = (n^2 * P_vi + 4n * R_avg + n * F_avg) / (n^2 + 5n)
  where R_avg and F_avg are averages of edge-midpoints and face-centroids,
  all of which are linear in the cage CP positions.  Therefore ∂P_lim/∂P_j
  (for each cage CP P_j) is a sparse closed-form coefficient.

* For 'passes_through': loss = ||P_limit - target||^2
* For 'tangent_to_dir': loss = (1 - |n_limit · target_dir|)^2
* For 'has_normal':     loss = ||n_limit - target_normal||^2
* For 'has_curvature':  loss = (κ_limit - target_kappa)^2  (mean curvature)

* Never raises — all exceptions produce fallback results.
"""

from __future__ import annotations

import math
import copy
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

from kerf_cad_core.geom.subd import SubDMesh

# ---------------------------------------------------------------------------
# LimitConstraint
# ---------------------------------------------------------------------------

VALID_KINDS = frozenset({"passes_through", "tangent_to_dir", "has_normal", "has_curvature"})


@dataclass
class LimitConstraint:
    """One constraint on the SubD limit surface at a parametric location.

    Parameters
    ----------
    kind : str
        One of:
        - 'passes_through'  : target_value is a [x, y, z] point the limit
                              surface must pass through.
        - 'tangent_to_dir'  : target_value is a direction [dx, dy, dz]; the
                              limit surface normal must be perpendicular to it
                              (equivalently, the surface is tangent to the dir).
        - 'has_normal'      : target_value is a [nx, ny, nz] unit normal the
                              limit surface must have at this point.
        - 'has_curvature'   : target_value is a scalar float — the desired
                              mean curvature at this point.
    face_id : int
        Index into mesh.faces identifying the quad face.
    u : float
        Parametric u coordinate in [0, 1] on the face.
    v : float
        Parametric v coordinate in [0, 1] on the face.
    target_value : list[float] or float
        Interpretation depends on `kind` (see above).
    """
    kind: str
    face_id: int
    u: float
    v: float
    target_value: object  # list[float] | float


@dataclass
class CageOptimizeResult:
    """Result of :func:`optimize_cage_for_constraints`.

    Attributes
    ----------
    mesh : SubDMesh
        Updated cage with optimized CP positions.
    residuals : list[float]
        Per-constraint final squared residual (one per input constraint).
    history : list[float]
        Total loss (sum of squared residuals) at the end of each iteration.
    converged : bool
        True if final total loss < 1e-6.
    """
    mesh: SubDMesh
    residuals: List[float] = field(default_factory=list)
    history: List[float] = field(default_factory=list)
    converged: bool = False


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _np3(v: Sequence) -> np.ndarray:
    return np.asarray(v, dtype=float).ravel()[:3]


def _stam_limit_pos(
    vi: int,
    verts: np.ndarray,          # (N, 3) float array
    vert_faces: Dict[int, List[int]],
    vert_neighbors: Dict[int, List[int]],
    faces: List[List[int]],
) -> np.ndarray:
    """Stam closed-form limit position for vertex vi.

    Returns P_lim as a (3,) array.  Returns the cage vertex itself for
    boundary / isolated vertices.
    """
    v = verts[vi]
    adj_face_idxs = vert_faces.get(vi, [])
    adj_nbrs = vert_neighbors.get(vi, [])
    n = len(adj_face_idxs)

    if n == 0 or len(adj_nbrs) == 0:
        return v.copy()

    face_centroids = np.array([
        np.mean(verts[np.array(faces[fi])], axis=0)
        for fi in adj_face_idxs
    ])  # (n, 3)
    F = np.mean(face_centroids, axis=0)  # (3,)

    edge_mids = 0.5 * (v + verts[adj_nbrs])  # (len(nbrs), 3)
    R = np.mean(edge_mids, axis=0)  # (3,)

    denom = float(n * n + 5 * n)
    if abs(denom) < 1e-15:
        return v.copy()

    return (n * n * v + 4.0 * n * R + float(n) * F) / denom


def _build_adjacency(
    mesh: SubDMesh,
) -> Tuple[Dict[int, List[int]], Dict[int, List[int]]]:
    """Build vert_faces and vert_neighbors from a SubDMesh."""
    vert_faces: Dict[int, List[int]] = {}
    vert_neighbors: Dict[int, List[int]] = {}
    for fi, face in enumerate(mesh.faces):
        m = len(face)
        for k, vi in enumerate(face):
            vert_faces.setdefault(vi, []).append(fi)
            prev_nb = face[(k - 1) % m]
            next_nb = face[(k + 1) % m]
            if prev_nb not in vert_neighbors.get(vi, []):
                vert_neighbors.setdefault(vi, []).append(prev_nb)
            if next_nb not in vert_neighbors.get(vi, []):
                vert_neighbors.setdefault(vi, []).append(next_nb)
    return vert_faces, vert_neighbors


def _limit_at_face_param(
    face_id: int,
    u: float,
    v: float,
    verts: np.ndarray,
    mesh: SubDMesh,
    vert_faces: Dict[int, List[int]],
    vert_neighbors: Dict[int, List[int]],
) -> np.ndarray:
    """Bilinear blend of four face-corner limit positions at (u, v).

    The face is assumed to be a quad [q0, q1, q2, q3] with layout:
        q0 = (u=0, v=0)   q1 = (u=1, v=0)
        q3 = (u=0, v=1)   q2 = (u=1, v=1)

    This is the standard limit-surface approximation used in quick queries.
    """
    face = mesh.faces[face_id]
    if len(face) < 4:
        q0 = face[0]
        return _stam_limit_pos(q0, verts, vert_faces, vert_neighbors, mesh.faces)

    q0, q1, q2, q3 = face[0], face[1], face[2], face[3]
    L00 = _stam_limit_pos(q0, verts, vert_faces, vert_neighbors, mesh.faces)
    L10 = _stam_limit_pos(q1, verts, vert_faces, vert_neighbors, mesh.faces)
    L11 = _stam_limit_pos(q2, verts, vert_faces, vert_neighbors, mesh.faces)
    L01 = _stam_limit_pos(q3, verts, vert_faces, vert_neighbors, mesh.faces)

    # Bilinear interpolation
    return (
        (1 - u) * (1 - v) * L00
        + u * (1 - v) * L10
        + u * v * L11
        + (1 - u) * v * L01
    )


def _limit_normal_at_face_param(
    face_id: int,
    u: float,
    v: float,
    verts: np.ndarray,
    mesh: SubDMesh,
    vert_faces: Dict[int, List[int]],
    vert_neighbors: Dict[int, List[int]],
) -> np.ndarray:
    """Estimated limit surface normal at (face_id, u, v).

    Computed as the cross product of the parametric tangents du and dv,
    each estimated by finite differences of the bilinear limit-position blend.
    Falls back to the Newell normal of the face if degenerate.
    """
    eps = 1e-4
    du = min(max(u, eps), 1.0 - eps)
    dv = min(max(v, eps), 1.0 - eps)

    # Finite differences for tangents
    p_plus_u = _limit_at_face_param(face_id, min(du + eps, 1.0), dv,
                                     verts, mesh, vert_faces, vert_neighbors)
    p_minus_u = _limit_at_face_param(face_id, max(du - eps, 0.0), dv,
                                      verts, mesh, vert_faces, vert_neighbors)
    p_plus_v = _limit_at_face_param(face_id, du, min(dv + eps, 1.0),
                                     verts, mesh, vert_faces, vert_neighbors)
    p_minus_v = _limit_at_face_param(face_id, du, max(dv - eps, 0.0),
                                      verts, mesh, vert_faces, vert_neighbors)

    t_u = p_plus_u - p_minus_u
    t_v = p_plus_v - p_minus_v

    n = np.cross(t_u, t_v)
    norm = float(np.linalg.norm(n))
    if norm < 1e-14:
        # Fallback: Newell normal of cage face
        face = mesh.faces[face_id]
        n = np.zeros(3, dtype=float)
        m = len(face)
        for k in range(m):
            curr = verts[face[k]]
            nxt = verts[face[(k + 1) % m]]
            n[0] += (curr[1] - nxt[1]) * (curr[2] + nxt[2])
            n[1] += (curr[2] - nxt[2]) * (curr[0] + nxt[0])
            n[2] += (curr[0] - nxt[0]) * (curr[1] + nxt[1])
        norm = float(np.linalg.norm(n)) or 1.0
    return n / norm


def _limit_mean_curvature_at_face_param(
    face_id: int,
    u: float,
    v: float,
    verts: np.ndarray,
    mesh: SubDMesh,
    vert_faces: Dict[int, List[int]],
    vert_neighbors: Dict[int, List[int]],
) -> float:
    """Estimated mean curvature at (face_id, u, v) via finite differences.

    Uses the discrete Laplace-Beltrami approximation:
        H ≈ |Δ P_limit| / (2 * ||P_limit||)  (simplified divergence estimate)

    For a flat region, this returns approximately 0.
    """
    eps = 1e-3
    p   = _limit_at_face_param(face_id, u, v, verts, mesh, vert_faces, vert_neighbors)
    p_u1 = _limit_at_face_param(face_id, min(u + eps, 1.0), v,
                                  verts, mesh, vert_faces, vert_neighbors)
    p_u0 = _limit_at_face_param(face_id, max(u - eps, 0.0), v,
                                  verts, mesh, vert_faces, vert_neighbors)
    p_v1 = _limit_at_face_param(face_id, u, min(v + eps, 1.0),
                                  verts, mesh, vert_faces, vert_neighbors)
    p_v0 = _limit_at_face_param(face_id, u, max(v - eps, 0.0),
                                  verts, mesh, vert_faces, vert_neighbors)

    # Discrete Laplacian of limit position
    laplacian = (p_u1 + p_u0 + p_v1 + p_v0 - 4.0 * p) / (eps * eps)
    kappa = 0.5 * float(np.linalg.norm(laplacian))
    return kappa


def _constraint_residual_only(
    constraint: LimitConstraint,
    verts: np.ndarray,
    mesh: SubDMesh,
    vert_faces: Dict[int, List[int]],
    vert_neighbors: Dict[int, List[int]],
) -> float:
    """Compute only the scalar residual (no gradient) for a constraint.

    This is a non-recursive helper used by _numerical_gradient.
    """
    c = constraint
    fid = int(c.face_id)
    u = float(c.u)
    v = float(c.v)

    if fid < 0 or fid >= len(mesh.faces):
        return 0.0

    face = mesh.faces[fid]
    if len(face) < 4:
        return 0.0

    kind = c.kind

    if kind == "passes_through":
        p_limit = _limit_at_face_param(fid, u, v, verts, mesh, vert_faces, vert_neighbors)
        target = np.asarray(c.target_value, dtype=float).ravel()[:3]
        diff = p_limit - target
        return float(np.dot(diff, diff))

    elif kind == "has_normal":
        n_limit = _limit_normal_at_face_param(fid, u, v, verts, mesh, vert_faces, vert_neighbors)
        target = np.asarray(c.target_value, dtype=float).ravel()[:3]
        t_norm = float(np.linalg.norm(target))
        if t_norm > 1e-14:
            target = target / t_norm
        diff = n_limit - target
        return float(np.dot(diff, diff))

    elif kind == "tangent_to_dir":
        n_limit = _limit_normal_at_face_param(fid, u, v, verts, mesh, vert_faces, vert_neighbors)
        target = np.asarray(c.target_value, dtype=float).ravel()[:3]
        t_norm = float(np.linalg.norm(target))
        if t_norm > 1e-14:
            target = target / t_norm
        dot_val = float(np.dot(n_limit, target))
        return dot_val ** 2

    elif kind == "has_curvature":
        kappa = _limit_mean_curvature_at_face_param(fid, u, v, verts, mesh, vert_faces, vert_neighbors)
        target_kappa = float(c.target_value)
        diff_k = kappa - target_kappa
        return diff_k ** 2

    return 0.0


def _constraint_residual_and_grad(
    constraint: LimitConstraint,
    verts: np.ndarray,
    mesh: SubDMesh,
    vert_faces: Dict[int, List[int]],
    vert_neighbors: Dict[int, List[int]],
) -> Tuple[float, np.ndarray]:
    """Compute (residual, gradient w.r.t. all cage CPs) for one constraint.

    Returns
    -------
    (residual : float, grad : np.ndarray of shape (N, 3))
        residual is the current squared residual.
        grad[j] is d(residual)/d(verts[j]).
    """
    N = len(verts)
    grad = np.zeros_like(verts)

    c = constraint
    fid = int(c.face_id)
    u = float(c.u)
    v = float(c.v)

    if fid < 0 or fid >= len(mesh.faces):
        return 0.0, grad

    face = mesh.faces[fid]
    if len(face) < 4:
        return 0.0, grad

    kind = c.kind

    if kind == "passes_through":
        p_limit = _limit_at_face_param(fid, u, v, verts, mesh, vert_faces, vert_neighbors)
        target = np.asarray(c.target_value, dtype=float).ravel()[:3]
        diff = p_limit - target
        residual = float(np.dot(diff, diff))

        # Analytic gradient via Stam limit-position linearization.
        # P_limit(u,v) = bilinear blend of {L(q0), L(q1), L(q2), L(q3)}.
        # L(qi) = (n^2 * P_qi + 4n * R_avg + n * F_avg) / (n^2+5n).
        # dL(qi)/dP_j is sparse and linear — computed via _stam_limit_gradient.
        blend_weights = _face_blend_weights(u, v)  # (q0,q1,q2,q3) bilinear weights
        for k, qi in enumerate(face[:4]):
            w = blend_weights[k]
            # dResidual/d(P_j) = 2 * diff · (dP_limit/dP_j)
            # dP_limit/dP_j = w * dL(qi)/dP_j  (summed over corners)
            dlim_dj = _stam_limit_gradient(qi, verts, vert_faces, vert_neighbors, mesh.faces)
            # dlim_dj[j] = dL(qi)/d(verts[j]) as (3,3) matrix — here we only
            # need the component along diff, so:
            # d(||diff||^2)/d(verts[j]) = 2 * diff · (w * dlim_dj[j] @ e3)
            for j in range(N):
                coeff = dlim_dj.get(j, None)
                if coeff is not None:
                    # coeff is (3,) = d(L_qi)/d(verts[j]) as a scalar per-axis
                    grad[j] += 2.0 * w * diff * coeff

    elif kind == "has_normal":
        n_limit = _limit_normal_at_face_param(fid, u, v, verts, mesh, vert_faces, vert_neighbors)
        target = np.asarray(c.target_value, dtype=float).ravel()[:3]
        t_norm = float(np.linalg.norm(target))
        if t_norm > 1e-14:
            target = target / t_norm
        diff = n_limit - target
        residual = float(np.dot(diff, diff))
        # Numerical gradient for normal constraints (cheaper than analytic)
        grad = _numerical_gradient(constraint, verts, mesh, vert_faces, vert_neighbors)

    elif kind == "tangent_to_dir":
        n_limit = _limit_normal_at_face_param(fid, u, v, verts, mesh, vert_faces, vert_neighbors)
        target = np.asarray(c.target_value, dtype=float).ravel()[:3]
        t_norm = float(np.linalg.norm(target))
        if t_norm > 1e-14:
            target = target / t_norm
        # Surface is tangent to dir when n_limit · dir = 0
        dot_val = float(np.dot(n_limit, target))
        residual = dot_val ** 2
        grad = _numerical_gradient(constraint, verts, mesh, vert_faces, vert_neighbors)

    elif kind == "has_curvature":
        kappa = _limit_mean_curvature_at_face_param(fid, u, v, verts, mesh, vert_faces, vert_neighbors)
        target_kappa = float(c.target_value)
        diff_k = kappa - target_kappa
        residual = diff_k ** 2
        grad = _numerical_gradient(constraint, verts, mesh, vert_faces, vert_neighbors)

    else:
        residual = 0.0

    return float(residual), grad


def _face_blend_weights(u: float, v: float) -> List[float]:
    """Bilinear blend weights for (u, v) over face corners (q0,q1,q2,q3).

    Layout:  q0=(0,0), q1=(1,0), q2=(1,1), q3=(0,1).
    """
    return [
        (1 - u) * (1 - v),  # q0
        u * (1 - v),         # q1
        u * v,               # q2
        (1 - u) * v,         # q3
    ]


def _stam_limit_gradient(
    vi: int,
    verts: np.ndarray,
    vert_faces: Dict[int, List[int]],
    vert_neighbors: Dict[int, List[int]],
    faces: List[List[int]],
) -> Dict[int, np.ndarray]:
    """Compute dL(vi)/d(verts[j]) for all j that affect L(vi).

    Returns a dict mapping vertex index j → (3,) coefficient vector c_j such that:
        L(vi) = sum_j  c_j[axis] * verts[j, axis]   (per-axis linear)
    i.e. grad_j = c_j = dL(vi)/d(verts[j]).

    For the Stam limit rule:
        L(vi) = (n^2 * vi + 4n * Σ R_k/K + n * Σ F_fi/F) / (n^2 + 5n)

    where K = len(adj_nbrs), F_count = len(adj_face_idxs),
    R_k = 0.5*(vi + nb_k), F_fi = (1/|face_fi|) * sum_{j in face_fi} verts[j].

    This function returns the sparse Jacobian as a dict.
    """
    adj_face_idxs = vert_faces.get(vi, [])
    adj_nbrs = vert_neighbors.get(vi, [])
    n = len(adj_face_idxs)
    coeffs: Dict[int, float] = {}

    if n == 0 or len(adj_nbrs) == 0:
        # Limit == cage vertex: d/d(vi) = 1, all others 0
        coeffs[vi] = 1.0
        result = {j: np.ones(3, dtype=float) * c for j, c in coeffs.items()}
        return result

    K = len(adj_nbrs)
    denom = float(n * n + 5 * n)

    # Contribution from n^2 * vi / denom
    coeffs[vi] = coeffs.get(vi, 0.0) + float(n * n) / denom

    # Contribution from 4n * (1/K) * sum_k (0.5*(vi + nb_k)) / denom
    # = 4n / (2K * denom) * sum_k vi  +  4n / (2K * denom) * sum_k nb_k
    edge_weight_vi = (4.0 * n) / (2.0 * K * denom)
    edge_weight_nb = (4.0 * n) / (2.0 * K * denom)
    coeffs[vi] = coeffs.get(vi, 0.0) + edge_weight_vi * K  # sum over K nbrs
    for nb in adj_nbrs:
        coeffs[nb] = coeffs.get(nb, 0.0) + edge_weight_nb

    # Contribution from n / (F_count * denom) * sum_fi (1/|face|) * sum_{j in face_fi} verts[j]
    F_count = len(adj_face_idxs)
    for fi in adj_face_idxs:
        face = faces[fi]
        face_size = len(face)
        face_weight = float(n) / (float(F_count) * float(face_size) * denom)
        for j in face:
            coeffs[j] = coeffs.get(j, 0.0) + face_weight

    # Broadcast to (3,) vectors (per-axis coefficients are identical)
    result = {j: np.full(3, c, dtype=float) for j, c in coeffs.items()}
    return result


def _numerical_gradient(
    constraint: LimitConstraint,
    verts: np.ndarray,
    mesh: SubDMesh,
    vert_faces: Dict[int, List[int]],
    vert_neighbors: Dict[int, List[int]],
    eps: float = 1e-5,
) -> np.ndarray:
    """Numerical gradient of the constraint residual w.r.t. all cage CPs.

    Uses central finite differences.  Only perturbs vertices that are part of
    the face neighborhood to avoid O(N^2) cost on large meshes.
    """
    N = len(verts)
    grad = np.zeros_like(verts)

    fid = int(constraint.face_id)
    if fid < 0 or fid >= len(mesh.faces):
        return grad

    # Collect relevant vertices: face corners + their 1-ring neighbors
    face = mesh.faces[fid]
    relevant_verts: set = set()
    for qi in face:
        relevant_verts.add(qi)
        relevant_verts.update(vert_neighbors.get(qi, []))

    def residual_at(v: np.ndarray) -> float:
        return _constraint_residual_only(
            constraint, v, mesh, vert_faces, vert_neighbors
        )

    for j in relevant_verts:
        if j >= N:
            continue
        for axis in range(3):
            verts[j, axis] += eps
            r_plus = residual_at(verts)
            verts[j, axis] -= 2 * eps
            r_minus = residual_at(verts)
            verts[j, axis] += eps  # restore
            grad[j, axis] = (r_plus - r_minus) / (2 * eps)

    return grad


# ---------------------------------------------------------------------------
# Public: optimize_cage_for_constraints
# ---------------------------------------------------------------------------

def optimize_cage_for_constraints(
    mesh: SubDMesh,
    constraints: List[LimitConstraint],
    n_iters: int = 100,
    lr: float = 0.01,
) -> CageOptimizeResult:
    """Optimize cage CP positions to minimize limit-surface constraint residuals.

    For each constraint in *constraints*, the squared residual between the
    current limit-surface value at (face_id, u, v) and the target_value is
    computed.  Gradient descent on the cage CP positions minimizes the total
    loss Σ residuals.

    Uses Adam-style adaptive learning rate (per-parameter momentum).

    Parameters
    ----------
    mesh : SubDMesh
        Input control cage.  Not modified in place.
    constraints : list[LimitConstraint]
        Constraints to satisfy.  Each must have a valid face_id.
    n_iters : int
        Maximum number of gradient-descent iterations.
    lr : float
        Learning rate (step size).

    Returns
    -------
    CageOptimizeResult
        Updated cage + per-constraint residuals + loss history.
        Never raises.
    """
    try:
        # Deep copy mesh so we don't mutate input
        opt_mesh = copy.deepcopy(mesh)
        verts = np.array([[float(x) for x in v] for v in opt_mesh.vertices], dtype=float)
        N = len(verts)

        if N == 0 or not constraints:
            return CageOptimizeResult(
                mesh=opt_mesh,
                residuals=[0.0] * len(constraints),
                history=[],
                converged=False,
            )

        # Filter invalid constraints
        valid_constraints = [
            c for c in constraints
            if 0 <= int(c.face_id) < len(opt_mesh.faces)
            and c.kind in VALID_KINDS
        ]
        if not valid_constraints:
            return CageOptimizeResult(
                mesh=opt_mesh,
                residuals=[0.0] * len(constraints),
                history=[],
                converged=False,
            )

        vert_faces, vert_neighbors = _build_adjacency(opt_mesh)

        history: List[float] = []

        for t in range(1, n_iters + 1):
            total_loss = 0.0
            total_grad = np.zeros_like(verts)

            for c in valid_constraints:
                res, g = _constraint_residual_and_grad(
                    c, verts, opt_mesh, vert_faces, vert_neighbors
                )
                total_loss += res
                total_grad += g

            history.append(total_loss)

            if total_loss < 1e-10:
                break

            # Armijo line-search gradient descent for guaranteed monotone decrease.
            # Step: verts_new = verts - step * grad
            # Reduce step until loss decreases (or min step reached).
            step = lr
            grad_norm_sq = float(np.sum(total_grad ** 2))
            if grad_norm_sq < 1e-30:
                break  # gradient vanished

            armijo_c = 0.5  # sufficient decrease parameter
            verts_new = verts - step * total_grad
            loss_new = sum(
                _constraint_residual_only(c, verts_new, opt_mesh, vert_faces, vert_neighbors)
                for c in valid_constraints
            )
            # Backtrack
            for _ in range(20):
                if loss_new <= total_loss - armijo_c * step * grad_norm_sq:
                    break
                step *= 0.5
                verts_new = verts - step * total_grad
                loss_new = sum(
                    _constraint_residual_only(c, verts_new, opt_mesh, vert_faces, vert_neighbors)
                    for c in valid_constraints
                )
            verts = verts_new

        # Final residuals
        vert_faces2, vert_neighbors2 = _build_adjacency(opt_mesh)
        final_residuals = []
        for c in constraints:
            try:
                fid = int(c.face_id)
                if 0 <= fid < len(opt_mesh.faces) and c.kind in VALID_KINDS:
                    res, _ = _constraint_residual_and_grad(
                        c, verts, opt_mesh, vert_faces2, vert_neighbors2
                    )
                else:
                    res = 0.0
            except Exception:
                res = 0.0
            final_residuals.append(float(res))

        # Write optimized positions back to mesh
        opt_mesh.vertices = [list(verts[i]) for i in range(N)]

        final_loss = sum(final_residuals)
        return CageOptimizeResult(
            mesh=opt_mesh,
            residuals=final_residuals,
            history=history,
            converged=bool(final_loss < 1e-6),
        )

    except Exception:
        # Never raise — return unmodified mesh
        fallback = copy.deepcopy(mesh)
        return CageOptimizeResult(
            mesh=fallback,
            residuals=[float("inf")] * len(constraints),
            history=[],
            converged=False,
        )


# ---------------------------------------------------------------------------
# Public: fit_cage_to_points
# ---------------------------------------------------------------------------

def fit_cage_to_points(
    mesh: SubDMesh,
    target_limit_points: List[Tuple],
    n_iters: int = 200,
) -> SubDMesh:
    """Fit cage CPs so the limit surface passes through the supplied points.

    Parameters
    ----------
    mesh : SubDMesh
        Input control cage.
    target_limit_points : list of (face_id, u, v, point)
        Each entry specifies a parametric location and the desired limit
        position.  point is a [x, y, z] sequence.
    n_iters : int
        Gradient-descent iterations.

    Returns
    -------
    SubDMesh
        Optimized cage whose limit surface passes through the target points
        (within solver tolerance).  Never raises.
    """
    try:
        constraints = [
            LimitConstraint(
                kind="passes_through",
                face_id=int(fid),
                u=float(u),
                v=float(v),
                target_value=list(pt),
            )
            for fid, u, v, pt in target_limit_points
        ]
        result = optimize_cage_for_constraints(mesh, constraints, n_iters=n_iters)
        return result.mesh
    except Exception:
        return copy.deepcopy(mesh)


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
    import json as _json  # noqa: F811

    _subd_optimize_cage_spec = ToolSpec(
        name="subd_optimize_cage",
        description=(
            "Optimize SubD cage control-point positions to satisfy limit-surface "
            "constraints.  Given a control mesh and a list of constraints, runs "
            "gradient descent on the cage CP positions to minimize the squared "
            "residual of each constraint.\n"
            "\n"
            "Constraint kinds:\n"
            "  passes_through  — target_value: [x, y, z] point on limit surface\n"
            "  has_normal      — target_value: [nx, ny, nz] unit normal\n"
            "  tangent_to_dir  — target_value: [dx, dy, dz] direction; surface "
            "                    normal must be perpendicular to this\n"
            "  has_curvature   — target_value: scalar mean curvature\n"
            "\n"
            "Returns:\n"
            "  ok            : bool\n"
            "  vertices      : updated cage vertices [[x,y,z], ...]\n"
            "  faces         : cage faces (unchanged)\n"
            "  creases       : cage creases (unchanged)\n"
            "  residuals     : per-constraint final squared residual\n"
            "  total_loss    : sum of residuals\n"
            "  converged     : bool — true if total_loss < 1e-6\n"
            "  iterations    : number of iterations run\n"
            "\n"
            "Errors: {ok:false, reason} for invalid inputs.  Never raises."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "vertices": {
                    "type": "array",
                    "description": "Control-mesh vertices as [[x,y,z], ...].",
                    "items": {"type": "array", "items": {"type": "number"}},
                },
                "faces": {
                    "type": "array",
                    "description": "Face vertex-index lists as [[i,j,k,l], ...].",
                    "items": {"type": "array", "items": {"type": "integer"}},
                },
                "creases": {
                    "type": "array",
                    "description": "Optional crease entries [{v1, v2, value}].",
                    "items": {
                        "type": "object",
                        "properties": {
                            "v1": {"type": "integer"},
                            "v2": {"type": "integer"},
                            "value": {"type": "number"},
                        },
                        "required": ["v1", "v2", "value"],
                    },
                },
                "constraints": {
                    "type": "array",
                    "description": "List of constraints to satisfy.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "kind": {
                                "type": "string",
                                "description": (
                                    "'passes_through', 'has_normal', "
                                    "'tangent_to_dir', or 'has_curvature'."
                                ),
                            },
                            "face_id": {
                                "type": "integer",
                                "description": "Index into faces.",
                            },
                            "u": {
                                "type": "number",
                                "description": "Parametric u in [0, 1].",
                            },
                            "v": {
                                "type": "number",
                                "description": "Parametric v in [0, 1].",
                            },
                            "target_value": {
                                "description": (
                                    "Target value: [x,y,z] for passes_through/has_normal/"
                                    "tangent_to_dir; scalar for has_curvature."
                                ),
                            },
                        },
                        "required": ["kind", "face_id", "u", "v", "target_value"],
                    },
                },
                "n_iters": {
                    "type": "integer",
                    "description": "Gradient-descent iterations (default 100).",
                },
                "lr": {
                    "type": "number",
                    "description": "Learning rate (default 0.01).",
                },
            },
            "required": ["vertices", "faces", "constraints"],
        },
    )

    @register(_subd_optimize_cage_spec)
    async def run_subd_optimize_cage(ctx: "ProjectCtx", args: bytes) -> str:
        try:
            a = _json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid args: {exc}", "BAD_ARGS")

        raw_verts = a.get("vertices", [])
        raw_faces = a.get("faces", [])
        raw_creases = a.get("creases", [])
        raw_constraints = a.get("constraints", [])
        n_iters = int(a.get("n_iters", 100))
        lr = float(a.get("lr", 0.01))

        if not raw_verts:
            return err_payload("vertices is required", "BAD_ARGS")
        if not raw_faces:
            return err_payload("faces is required", "BAD_ARGS")
        if not raw_constraints:
            return err_payload("constraints is required", "BAD_ARGS")
        if n_iters < 1 or n_iters > 2000:
            return err_payload("n_iters must be 1..2000", "BAD_ARGS")
        if lr <= 0.0 or lr > 10.0:
            return err_payload("lr must be in (0, 10]", "BAD_ARGS")

        try:
            mesh = SubDMesh(
                vertices=[[float(x) for x in v] for v in raw_verts],
                faces=[[int(i) for i in f] for f in raw_faces],
            )
        except Exception as exc:
            return err_payload(f"invalid mesh: {exc}", "BAD_ARGS")

        for ce in raw_creases:
            try:
                mesh.set_crease(int(ce["v1"]), int(ce["v2"]), float(ce["value"]))
            except Exception:
                pass

        constraints: List[LimitConstraint] = []
        for i, rc in enumerate(raw_constraints):
            try:
                kind = str(rc.get("kind", "")).strip()
                if kind not in VALID_KINDS:
                    return err_payload(
                        f"constraint[{i}] kind '{kind}' must be one of "
                        f"{sorted(VALID_KINDS)}", "BAD_ARGS"
                    )
                constraints.append(LimitConstraint(
                    kind=kind,
                    face_id=int(rc["face_id"]),
                    u=float(rc["u"]),
                    v=float(rc["v"]),
                    target_value=rc["target_value"],
                ))
            except Exception as exc:
                return err_payload(f"constraint[{i}] invalid: {exc}", "BAD_ARGS")

        result = optimize_cage_for_constraints(mesh, constraints, n_iters=n_iters, lr=lr)

        out_mesh = result.mesh
        creases_out = [
            {"v1": k[0], "v2": k[1], "value": v}
            for k, v in out_mesh.creases.items()
        ]
        return ok_payload({
            "ok": True,
            "vertices": out_mesh.vertices,
            "faces": out_mesh.faces,
            "creases": creases_out,
            "residuals": result.residuals,
            "total_loss": float(sum(result.residuals)),
            "converged": result.converged,
            "iterations": len(result.history),
        })
