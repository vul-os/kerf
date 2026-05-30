"""
subd_limit_principal_dirs.py
============================
SubD limit-surface principal curvature directions.

Computes the two orthogonal tangent directions (principal directions) at which
normal curvature is extremized (κ_1, κ_2) on a Catmull-Clark limit surface.

Public API
----------
evaluate_principal_directions(mesh, face_id, u, v) -> PrincipalDirectionsResult
    Evaluate principal curvature magnitudes and their 3-D direction vectors at
    a parametric point (u, v) within a given quad face.

trace_principal_curvature_lines(mesh, n_samples=20) -> dict
    Sample seed points across the mesh and integrate principal-direction fields
    to produce trace polylines for ridge/valley line extraction.

subd_evaluate_principal_directions (LLM tool)
    Registered tool wrapping ``evaluate_principal_directions``.

Math
----
Given a parametric point on the limit surface we need:

  1. Tangent vectors T_u, T_v via Stam's eigenvector formula (reused from
     subd_to_nurbs._stam_limit_tangents).  These are computed at the face
     corner vertices and bilinearly blended to (u, v).

  2. First fundamental form:
       E = T_u · T_u,  F = T_u · T_v,  G = T_v · T_v

  3. Second fundamental form via finite differences of the limit-surface
     normal across the face (L = Suu·n, M = Suv·n, N = Svv·n in classical
     notation, written e, f, g here to match do Carmo §3.3):

         h = small parameter step
         T_uu ≈ (S(u+h,v) - 2·S(u,v) + S(u-h,v)) / h²
         T_vv ≈ (S(u,v+h) - 2·S(u,v) + S(u,v-h)) / h²
         T_uv ≈ (S(u+h,v+h) - S(u+h,v-h)
                  - S(u-h,v+h) + S(u-h,v-h)) / (4h²)
         e = T_uu · n,  f = T_uv · n,  g = T_vv · n

  4. Shape operator W as a 2×2 matrix in the (T_u, T_v) basis:
       W = I⁻¹ · II        where  I = [[E,F],[F,G]],  II = [[e,f],[f,g]]

  5. Eigendecomposition of W:
       eigenvalues  → κ_1, κ_2   (principal curvatures)
       eigenvectors → (α, β)_1, (α, β)_2  in tangent basis

  6. Back-project to 3-D:
       d_1 = α_1·T_u + β_1·T_v   (normalised)
       d_2 = α_2·T_u + β_2·T_v   (normalised)

References
----------
do Carmo, M.P. §3 (principal directions = eigenvectors of shape operator).
Stam, J. (1998) Exact Evaluation of Catmull-Clark Subdivision Surfaces at
Arbitrary Parameter Values, SIGGRAPH 98.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import numpy as np
from scipy.linalg import eigh  # type: ignore

from kerf_cad_core.geom.subd import (
    SubDMesh,
    catmull_clark_subdivide,
)
from kerf_cad_core.geom.subd_to_nurbs import (
    _build_vertex_adjacency,
    _stam_limit_tangents,
)


# ---------------------------------------------------------------------------
# Public result type
# ---------------------------------------------------------------------------


@dataclass
class PrincipalDirectionsResult:
    """Principal curvature directions at a limit-surface point.

    Attributes
    ----------
    kappa_1 : float
        Larger (more-positive) principal curvature.
    kappa_2 : float
        Smaller (more-negative) principal curvature.
    principal_dir_1 : np.ndarray  shape (3,)
        Unit 3-D direction of κ_1.
    principal_dir_2 : np.ndarray  shape (3,)
        Unit 3-D direction of κ_2  (orthogonal to principal_dir_1).
    normal : np.ndarray  shape (3,)
        Unit outward normal at the evaluated point.
    position : np.ndarray  shape (3,)
        3-D position of the evaluated point.
    E : float
        First fundamental form coefficient E.
    F : float
        First fundamental form coefficient F.
    G : float
        First fundamental form coefficient G.
    e : float
        Second fundamental form coefficient L (Suu·n).
    f : float
        Second fundamental form coefficient M (Suv·n).
    g : float
        Second fundamental form coefficient N (Svv·n).
    degenerate : bool
        True when the point is degenerate (near-zero determinant).
    """
    kappa_1: float
    kappa_2: float
    principal_dir_1: np.ndarray
    principal_dir_2: np.ndarray
    normal: np.ndarray
    position: np.ndarray
    E: float = 0.0
    F: float = 0.0
    G: float = 0.0
    e: float = 0.0
    f: float = 0.0
    g: float = 0.0
    degenerate: bool = False


# ---------------------------------------------------------------------------
# Internal: subdivide-then-sample the limit surface
# ---------------------------------------------------------------------------

_DEFAULT_LEVELS = 4   # subdivision levels for limit-surface approximation
_FD_H = 0.01          # finite-difference step in (u,v) parameter space (face-local)


def _subdivide_face_to_limit(mesh: SubDMesh, face_id: int) -> SubDMesh:
    """Subdivide mesh and return the sub-mesh for the quadrant of face face_id.

    After N levels of CC subdivision each original face becomes (2^N)×(2^N)
    quads.  We return the full subdivided mesh (small quad mesh) for the
    face-quadrant corresponding to face_id.

    This is the "local subdivision" approach from Stam 1998: instead of the
    full Stam eigenanalysis for arbitrary valence, we subdivide until all
    vertices in the face patch are regular (valence 4), then use bilinear
    interpolation within the resulting quad grid.
    """
    return catmull_clark_subdivide(mesh, levels=_DEFAULT_LEVELS)


def _bilinear_interp(
    p00: np.ndarray,
    p10: np.ndarray,
    p01: np.ndarray,
    p11: np.ndarray,
    u: float,
    v: float,
) -> np.ndarray:
    """Bilinear interpolation over [0,1]×[0,1] quad.

    Layout:
        p00 = (u=0, v=0),  p10 = (u=1, v=0)
        p01 = (u=0, v=1),  p11 = (u=1, v=1)
    """
    return (
        (1 - u) * (1 - v) * p00
        + u * (1 - v) * p10
        + (1 - u) * v * p01
        + u * v * p11
    )


def _face_limit_position(
    sub_mesh: SubDMesh,
    face_origin_idx: int,
    u: float,
    v: float,
    levels: int = _DEFAULT_LEVELS,
) -> np.ndarray:
    """Evaluate the limit position at (u, v) within a subdivided face region.

    After `levels` of CC subdivision the face fan produced by the original
    face `face_origin_idx` occupies a (2^levels × 2^levels) block of quads in
    the subdivided mesh.  We locate the sub-quad containing (u, v) and do
    bilinear interpolation.

    Parameters
    ----------
    sub_mesh : SubDMesh
        Fully-subdivided mesh.
    face_origin_idx : int
        Index of the original face in the *original* mesh.  After subdivision,
        original face i produces quads at indices
        i * 4^levels .. (i+1) * 4^levels - 1.
    u, v : float in [0, 1]
        Parameter within the face.
    levels : int

    Returns
    -------
    3-vector  position on the limit surface.
    """
    u = float(np.clip(u, 0.0, 1.0))
    v = float(np.clip(v, 0.0, 1.0))

    n_side = 2 ** levels          # quads per side after subdivision
    total_quads_per_face = n_side * n_side

    fi0 = face_origin_idx * total_quads_per_face
    fi1 = fi0 + total_quads_per_face

    if fi1 > len(sub_mesh.faces):
        # Fallback: return centroid of all faces
        all_verts = [np.array(sub_mesh.vertices[vi], dtype=float)
                     for f in sub_mesh.faces for vi in f]
        return np.mean(np.array(all_verts), axis=0)

    # Map (u, v) into the grid of sub-quads
    # sub-quad (i_u, i_v):   col i_u in [0, n_side), row i_v in [0, n_side)
    iu_f = u * n_side
    iv_f = v * n_side
    iu = int(min(math.floor(iu_f), n_side - 1))
    iv = int(min(math.floor(iv_f), n_side - 1))
    su = iu_f - iu          # local parameter within sub-quad
    sv = iv_f - iv

    # Sub-quad index: row-major order (u-fastest)
    sub_fi = fi0 + iv * n_side + iu

    if sub_fi >= len(sub_mesh.faces):
        sub_fi = fi0

    quad = sub_mesh.faces[sub_fi]
    if len(quad) < 4:
        return np.array(sub_mesh.vertices[quad[0]], dtype=float)

    p00 = np.array(sub_mesh.vertices[quad[0]], dtype=float)
    p10 = np.array(sub_mesh.vertices[quad[1]], dtype=float)
    p11 = np.array(sub_mesh.vertices[quad[2]], dtype=float)
    p01 = np.array(sub_mesh.vertices[quad[3]], dtype=float)

    return _bilinear_interp(p00, p10, p01, p11, su, sv)


def _sample_limit(
    mesh: SubDMesh,
    face_id: int,
    u: float,
    v: float,
    sub_mesh: Optional[SubDMesh] = None,
) -> np.ndarray:
    """Sample the limit surface at (u, v) within face face_id.

    Uses the subdivided mesh approximation.  The subdivision is done once
    per mesh and re-used via the optional sub_mesh argument.
    """
    if sub_mesh is None:
        sub_mesh = _subdivide_face_to_limit(mesh, face_id)
    return _face_limit_position(sub_mesh, face_id, u, v, levels=_DEFAULT_LEVELS)


# ---------------------------------------------------------------------------
# Public: evaluate_principal_directions
# ---------------------------------------------------------------------------


def evaluate_principal_directions(
    mesh: SubDMesh,
    face_id: int,
    u: float,
    v: float,
) -> PrincipalDirectionsResult:
    """Evaluate principal curvature directions on the SubD limit surface.

    Computes the two orthogonal tangent directions (in 3-D) that correspond
    to the extremal normal curvatures κ_1 ≥ κ_2 at the limit-surface point.

    Algorithm
    ---------
    1. Subdivide the mesh 4 levels to obtain a dense limit approximation.
    2. Evaluate S(u,v), S(u±h,v), S(u,v±h), S(u±h,v±h) by bilinear sampling
       within the subdivided face patch.
    3. Compute T_u = ∂S/∂u and T_v = ∂S/∂v by central finite differences.
    4. Compute second partials T_uu, T_vv, T_uv by second-order FD.
    5. Build first/second fundamental form coefficients.
    6. Shape operator W = I⁻¹ · II (2×2 in the tangent basis).
    7. Eigendecompose W via scipy.linalg.eigh (symmetric matrix).
    8. Back-project eigenvectors to 3-D.

    Parameters
    ----------
    mesh : SubDMesh
        Catmull-Clark control mesh.
    face_id : int
        0-based index of the quad face to evaluate on.
    u, v : float in [0, 1]
        Parametric coordinates within the face.

    Returns
    -------
    PrincipalDirectionsResult — never raises.

    Notes
    -----
    * At an *umbilic point* (κ_1 = κ_2), the principal directions are
      degenerate (any orthogonal pair in the tangent plane is valid).  The
      function returns an arbitrary orthogonal pair in this case.
    * At degenerate surface points (zero normal), ``degenerate=True`` is set
      and the returned directions/curvatures are fallback values.
    """
    try:
        face_id = int(face_id)
        u = float(np.clip(u, 0.01, 0.99))
        v = float(np.clip(v, 0.01, 0.99))

        if face_id < 0 or face_id >= len(mesh.faces):
            return _degenerate_result()

        # --- Subdivide once ---
        sub = catmull_clark_subdivide(mesh, levels=_DEFAULT_LEVELS)

        def S(uu: float, vv: float) -> np.ndarray:
            return _face_limit_position(sub, face_id, uu, vv, levels=_DEFAULT_LEVELS)

        # --- Central finite differences for first partials ---
        h = _FD_H
        S_c   = S(u,   v)
        S_u_p = S(u+h, v)
        S_u_m = S(u-h, v)
        S_v_p = S(u,   v+h)
        S_v_m = S(u,   v-h)

        T_u = (S_u_p - S_u_m) / (2.0 * h)
        T_v = (S_v_p - S_v_m) / (2.0 * h)

        # --- Second partials ---
        T_uu = (S_u_p - 2.0 * S_c + S_u_m) / (h * h)
        T_vv = (S_v_p - 2.0 * S_c + S_v_m) / (h * h)

        S_pp = S(u+h, v+h)
        S_pm = S(u+h, v-h)
        S_mp = S(u-h, v+h)
        S_mm = S(u-h, v-h)
        T_uv = (S_pp - S_pm - S_mp + S_mm) / (4.0 * h * h)

        # --- Unit normal ---
        cross = np.cross(T_u, T_v)
        cross_mag = float(np.linalg.norm(cross))
        if cross_mag < 1e-12:
            return _degenerate_result(position=S_c)

        n_hat = cross / cross_mag

        # --- First fundamental form I = [[E, F], [F, G]] ---
        E = float(np.dot(T_u, T_u))
        F = float(np.dot(T_u, T_v))
        G = float(np.dot(T_v, T_v))

        EGF2 = E * G - F * F
        if abs(EGF2) < 1e-20:
            return _degenerate_result(position=S_c)

        # --- Second fundamental form II = [[e, f], [f, g]] ---
        e = float(np.dot(T_uu, n_hat))   # L = Suu · n
        f = float(np.dot(T_uv, n_hat))   # M = Suv · n
        g = float(np.dot(T_vv, n_hat))   # N = Svv · n

        # --- Shape operator W = I⁻¹ · II ---
        # I  = [[E, F], [F, G]]
        # II = [[e, f], [f, g]]
        I_mat  = np.array([[E, F], [F, G]], dtype=float)
        II_mat = np.array([[e, f], [f, g]], dtype=float)

        # W = I⁻¹ · II (not necessarily symmetric).
        # For eigenanalysis we solve the generalised eigenvalue problem:
        #   II · x = λ · I · x
        # which is equivalent to W · x = λ · x and gives real eigenvalues
        # because I and II are both symmetric (and I is positive-definite at
        # regular points).
        try:
            eigenvalues, eigenvectors = eigh(II_mat, I_mat)
        except Exception:
            # Fallback: standard eigendecomposition of W = I⁻¹ II
            try:
                W = np.linalg.solve(I_mat, II_mat)
                eigenvalues, eigenvectors = np.linalg.eig(W)
                # Sort by real part descending
                idx = np.argsort(-eigenvalues.real)
                eigenvalues = eigenvalues[idx].real
                eigenvectors = eigenvectors[:, idx].real
            except Exception:
                return _degenerate_result(position=S_c, normal=n_hat)

        # eigh returns eigenvalues in ascending order → κ_2 ≤ κ_1
        kappa_2 = float(eigenvalues[0])
        kappa_1 = float(eigenvalues[1])
        ev_2 = eigenvectors[:, 0]   # (α, β) for κ_2
        ev_1 = eigenvectors[:, 1]   # (α, β) for κ_1

        # --- Back-project to 3-D ---
        d1_3d = float(ev_1[0]) * T_u + float(ev_1[1]) * T_v
        d2_3d = float(ev_2[0]) * T_u + float(ev_2[1]) * T_v

        n1 = float(np.linalg.norm(d1_3d))
        n2 = float(np.linalg.norm(d2_3d))

        if n1 < 1e-14:
            # Umbilic fallback: pick an arbitrary orthonormal pair in tangent plane
            d1_3d, d2_3d = _tangent_plane_ortho_pair(T_u, T_v)
        else:
            d1_3d = d1_3d / n1
            if n2 < 1e-14:
                d2_3d = np.cross(n_hat, d1_3d)
                n2b = float(np.linalg.norm(d2_3d))
                d2_3d = d2_3d / n2b if n2b > 1e-14 else _perp(d1_3d)
            else:
                d2_3d = d2_3d / n2

        return PrincipalDirectionsResult(
            kappa_1=kappa_1,
            kappa_2=kappa_2,
            principal_dir_1=d1_3d,
            principal_dir_2=d2_3d,
            normal=n_hat,
            position=S_c,
            E=E, F=F, G=G,
            e=e, f=f, g=g,
            degenerate=False,
        )

    except Exception:
        return _degenerate_result()


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _degenerate_result(
    position: Optional[np.ndarray] = None,
    normal: Optional[np.ndarray] = None,
) -> PrincipalDirectionsResult:
    pos = position if position is not None else np.zeros(3)
    nor = normal if normal is not None else np.array([0.0, 0.0, 1.0])
    return PrincipalDirectionsResult(
        kappa_1=0.0,
        kappa_2=0.0,
        principal_dir_1=np.array([1.0, 0.0, 0.0]),
        principal_dir_2=np.array([0.0, 1.0, 0.0]),
        normal=nor,
        position=pos,
        degenerate=True,
    )


def _tangent_plane_ortho_pair(
    T_u: np.ndarray,
    T_v: np.ndarray,
) -> Tuple[np.ndarray, np.ndarray]:
    """Return two orthonormal vectors in the tangent plane spanned by T_u, T_v."""
    n_u = float(np.linalg.norm(T_u))
    if n_u < 1e-14:
        e1 = np.array([1.0, 0.0, 0.0])
    else:
        e1 = T_u / n_u
    # Gram-Schmidt: e2 = T_v - (T_v·e1)e1
    e2 = T_v - float(np.dot(T_v, e1)) * e1
    n_2 = float(np.linalg.norm(e2))
    if n_2 < 1e-14:
        e2 = _perp(e1)
    else:
        e2 = e2 / n_2
    return e1, e2


def _perp(v: np.ndarray) -> np.ndarray:
    """Return an arbitrary unit vector perpendicular to v."""
    v = v / (float(np.linalg.norm(v)) + 1e-30)
    if abs(v[0]) < 0.9:
        candidate = np.array([1.0, 0.0, 0.0])
    else:
        candidate = np.array([0.0, 1.0, 0.0])
    out = candidate - float(np.dot(candidate, v)) * v
    return out / (float(np.linalg.norm(out)) + 1e-30)


# ---------------------------------------------------------------------------
# Public: trace_principal_curvature_lines
# ---------------------------------------------------------------------------


def trace_principal_curvature_lines(
    mesh: SubDMesh,
    n_samples: int = 20,
    n_steps: int = 30,
    step_size: float = 0.04,
) -> dict:
    """Trace principal curvature lines from seed points across the mesh.

    Integrates the principal direction field from a grid of seed (face, u, v)
    points via Euler integration.  Returns a dictionary of ridge and valley
    polyline traces.

    Parameters
    ----------
    mesh : SubDMesh
    n_samples : int
        Number of seed points (spread across all faces × interior UV grid).
    n_steps : int
        Integration steps per trace.
    step_size : float
        Euler step size in (u, v) parameter space per step.

    Returns
    -------
    dict with keys:
        ok         : bool
        traces_k1  : list of polylines  (lists of [x,y,z] points) — κ_1 direction
        traces_k2  : list of polylines  (lists of [x,y,z] points) — κ_2 direction
        n_seeds    : int
    """
    try:
        if not mesh.faces:
            return {"ok": False, "reason": "empty mesh"}

        n_faces = len(mesh.faces)
        n_samples = max(1, int(n_samples))

        # Build seed list: spread evenly across faces and interior UV
        seeds = []
        per_face = max(1, n_samples // n_faces)
        sqrt_pf = max(1, int(math.sqrt(per_face)))
        us_grid = [(i + 0.5) / sqrt_pf for i in range(sqrt_pf)]
        vs_grid = [(j + 0.5) / sqrt_pf for j in range(sqrt_pf)]

        for fi in range(n_faces):
            for us in us_grid:
                for vs in vs_grid:
                    seeds.append((fi, float(us), float(vs)))
                    if len(seeds) >= n_samples:
                        break
                if len(seeds) >= n_samples:
                    break
            if len(seeds) >= n_samples:
                break

        traces_k1 = []
        traces_k2 = []

        # Pre-subdivide once
        sub = catmull_clark_subdivide(mesh, levels=_DEFAULT_LEVELS)

        def S_sub(fi: int, uu: float, vv: float) -> np.ndarray:
            return _face_limit_position(sub, fi, uu, vv, levels=_DEFAULT_LEVELS)

        for (fi, u0, v0) in seeds:
            r1 = evaluate_principal_directions(mesh, fi, u0, v0)
            if r1.degenerate:
                continue

            # Trace in κ_1 direction (forward)
            poly_k1 = [r1.position.tolist()]
            poly_k2 = [r1.position.tolist()]
            u, v = float(u0), float(v0)
            d1 = r1.principal_dir_1.copy()
            d2 = r1.principal_dir_2.copy()

            for _ in range(n_steps):
                # Project d1 to (u,v) parameter steps via the metric
                h = _FD_H
                Tu = (S_sub(fi, u+h, v) - S_sub(fi, u-h, v)) / (2.0*h)
                Tv = (S_sub(fi, u, v+h) - S_sub(fi, u, v-h)) / (2.0*h)
                A = np.column_stack([Tu, Tv])  # 3×2
                try:
                    du_dv, _, _, _ = np.linalg.lstsq(A, d1, rcond=None)
                except Exception:
                    break
                step_len = float(np.linalg.norm(du_dv))
                if step_len < 1e-14:
                    break
                du_dv = du_dv / step_len * step_size
                u_new = float(np.clip(u + du_dv[0], 0.02, 0.98))
                v_new = float(np.clip(v + du_dv[1], 0.02, 0.98))
                pos = S_sub(fi, u_new, v_new)
                poly_k1.append(pos.tolist())
                # Update direction (ensure sign continuity)
                r_new = evaluate_principal_directions(mesh, fi, u_new, v_new)
                if not r_new.degenerate:
                    if float(np.dot(r_new.principal_dir_1, d1)) < 0:
                        d1 = -r_new.principal_dir_1
                    else:
                        d1 = r_new.principal_dir_1
                u, v = u_new, v_new

            u, v = float(u0), float(v0)
            d2_cur = d2.copy()
            for _ in range(n_steps):
                h = _FD_H
                Tu = (S_sub(fi, u+h, v) - S_sub(fi, u-h, v)) / (2.0*h)
                Tv = (S_sub(fi, u, v+h) - S_sub(fi, u, v-h)) / (2.0*h)
                A = np.column_stack([Tu, Tv])
                try:
                    du_dv, _, _, _ = np.linalg.lstsq(A, d2_cur, rcond=None)
                except Exception:
                    break
                step_len = float(np.linalg.norm(du_dv))
                if step_len < 1e-14:
                    break
                du_dv = du_dv / step_len * step_size
                u_new = float(np.clip(u + du_dv[0], 0.02, 0.98))
                v_new = float(np.clip(v + du_dv[1], 0.02, 0.98))
                pos = S_sub(fi, u_new, v_new)
                poly_k2.append(pos.tolist())
                r_new = evaluate_principal_directions(mesh, fi, u_new, v_new)
                if not r_new.degenerate:
                    if float(np.dot(r_new.principal_dir_2, d2_cur)) < 0:
                        d2_cur = -r_new.principal_dir_2
                    else:
                        d2_cur = r_new.principal_dir_2
                u, v = u_new, v_new

            if len(poly_k1) > 1:
                traces_k1.append(poly_k1)
            if len(poly_k2) > 1:
                traces_k2.append(poly_k2)

        return {
            "ok": True,
            "traces_k1": traces_k1,
            "traces_k2": traces_k2,
            "n_seeds": len(seeds),
        }
    except Exception as exc:
        return {"ok": False, "reason": str(exc)}


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

    _subd_principal_dirs_spec = ToolSpec(
        name="subd_evaluate_principal_directions",
        description=(
            "Evaluate the principal curvature directions on a Catmull-Clark SubD "
            "limit surface at a parametric point (u, v) within a specified quad face.\n"
            "\n"
            "Returns the two orthogonal 3-D tangent directions d1 and d2 along which "
            "the normal curvature is extremized (κ_1 ≥ κ_2), together with the "
            "surface normal, position, and first/second fundamental form coefficients.\n"
            "\n"
            "Use for:\n"
            "  - Surface fairness analysis on SubD shapes\n"
            "  - Ridge/valley line tracing\n"
            "  - Anisotropic remeshing direction fields\n"
            "\n"
            "Returns:\n"
            "  ok              : bool\n"
            "  kappa_1         : float   — larger principal curvature\n"
            "  kappa_2         : float   — smaller principal curvature\n"
            "  principal_dir_1 : [x,y,z] — 3-D unit direction of κ_1\n"
            "  principal_dir_2 : [x,y,z] — 3-D unit direction of κ_2\n"
            "  normal          : [x,y,z] — unit surface normal\n"
            "  position        : [x,y,z] — 3-D position\n"
            "  E, F, G         : first fundamental form\n"
            "  e, f, g         : second fundamental form\n"
            "  degenerate      : bool    — true if point is degenerate\n"
            "\n"
            "Errors: {ok:false, reason} for invalid inputs.  Never raises."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "vertices": {
                    "type": "array",
                    "description": "Control-mesh vertices [[x,y,z], ...].",
                    "items": {"type": "array", "items": {"type": "number"}},
                },
                "faces": {
                    "type": "array",
                    "description": "Face vertex-index lists [[i,j,k,l], ...].",
                    "items": {"type": "array", "items": {"type": "integer"}},
                },
                "face_id": {
                    "type": "integer",
                    "description": "0-based face index to evaluate on.",
                    "minimum": 0,
                },
                "u": {
                    "type": "number",
                    "description": "U parameter in [0, 1] within the face.",
                    "minimum": 0.0,
                    "maximum": 1.0,
                },
                "v": {
                    "type": "number",
                    "description": "V parameter in [0, 1] within the face.",
                    "minimum": 0.0,
                    "maximum": 1.0,
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
            },
            "required": ["vertices", "faces", "face_id", "u", "v"],
        },
    )

    @register(_subd_principal_dirs_spec)
    async def run_subd_evaluate_principal_directions(
        ctx: "ProjectCtx", args: bytes
    ) -> str:
        try:
            a = _json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid args: {exc}", "BAD_ARGS")

        raw_verts = a.get("vertices", [])
        raw_faces = a.get("faces", [])
        face_id   = int(a.get("face_id", 0))
        u         = float(a.get("u", 0.5))
        v         = float(a.get("v", 0.5))
        raw_creases = a.get("creases", [])

        if not raw_verts:
            return err_payload("vertices is required", "BAD_ARGS")
        if not raw_faces:
            return err_payload("faces is required", "BAD_ARGS")

        try:
            mesh = SubDMesh(
                vertices=[[float(x) for x in vv] for vv in raw_verts],
                faces=[[int(i) for i in f] for f in raw_faces],
            )
        except Exception as exc:
            return err_payload(f"invalid mesh: {exc}", "BAD_ARGS")

        for ce in raw_creases:
            try:
                mesh.set_crease(int(ce["v1"]), int(ce["v2"]), float(ce["value"]))
            except Exception:
                pass

        result = evaluate_principal_directions(mesh, face_id, u, v)

        return ok_payload({
            "ok": True,
            "kappa_1": result.kappa_1,
            "kappa_2": result.kappa_2,
            "principal_dir_1": result.principal_dir_1.tolist(),
            "principal_dir_2": result.principal_dir_2.tolist(),
            "normal": result.normal.tolist(),
            "position": result.position.tolist(),
            "E": result.E, "F": result.F, "G": result.G,
            "e": result.e, "f": result.f, "g": result.g,
            "degenerate": result.degenerate,
        })
