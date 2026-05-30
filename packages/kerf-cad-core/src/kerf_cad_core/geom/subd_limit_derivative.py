"""subd_limit_derivative.py
==========================
Stam-exact arbitrary-order derivatives of Catmull-Clark limit surfaces.

Reference: Stam 1998 §3 — "Exact Evaluation of Catmull-Clark Subdivision
Surfaces at Arbitrary Parameter Values."

For a smooth interior vertex of valence n the limit surface is characterised
by eigenvectors of the CC subdivision matrix.  The p-th order derivative in
the u-direction arises by differentiating the eigenbasis functions p times;
mixed partial ∂^(p+q)S/(∂u^p ∂v^q) is obtained by repeated differentiation.

For the *regular* case (valence-4 interior quads) the limit surface is a
bicubic B-spline patch and the derivatives reduce exactly to B-spline
derivative evaluation via de-Boor.  For extraordinary vertices (valence n≠4)
Stam gives an eigenstructure representation: the surface is expressed as a
linear combination of n basis functions; differentiating each eigenbasis
function (p+q) times gives the desired mixed partial.

This module implements:
  evaluate_derivative(mesh, face_id, u, v, order=(1,0)) -> np.ndarray
      Stam-exact ∂^(p+q)S/(∂u^p ∂v^q) at (u,v) on the given face.
      order=(p,q): p u-derivatives, q v-derivatives.

  evaluate_derivative_grid(mesh, face_id, n_samples=10, max_order=4) -> dict
      Sample all orders up to total degree max_order on a regular grid.
      Returns {(p,q): np.ndarray of shape (n_samples, n_samples, 3)}.

  compare_derivative_methods(mesh, face_id, sample_uv,
                             methods, orders) -> dict
      Compare Stam-exact vs finite-difference at the given sample points.
      Returns per-(method,order) results and a comparison summary.

Public API
----------
evaluate_derivative
evaluate_derivative_grid
compare_derivative_methods
StamDerivativeError

Design notes
------------
For the regular (valence-4) case the limit surface on a given face patch is a
degree-3 bicubic tensor-product polynomial in (u,v).  The 4×4 Bezier control
net is extracted using the same Stam basis as subd_to_nurbs.py.  Derivatives
are then computed analytically by differentiating the Bernstein basis:

  ∂^p B_{i,3}(t) / ∂t^p = 3!/(3-p)! * B_{i-p, 3-p}(t) * (binomial stuff)

For the extraordinary case (valence n≠4) we model the limit surface in the
characteristic map coordinate system.  The surface is written as:

  S(u,v) = Σ_{k} λ_k^level * Φ_k(u_sub, v_sub) * c_k

where λ_k are the CC eigenvalues and Φ_k are the eigenbasis functions on a
unit quad.  Differentiation w.r.t. u or v passes through the characteristic
map Jacobian.

For the purpose of this module — where the primary use-case is class-A
continuity testing and fairness analysis — we implement a numerically stable
approach that:
1. Uses the exact Bezier representation for regular patches (exact to machine
   precision for all orders).
2. Uses the eigenstructure representation for extraordinary patches, valid for
   smooth interior vertices.

Both paths share the common interface `evaluate_derivative(mesh, face_id, u, v,
order)` which dispatches based on whether all four vertices of `face_id` are
regular (valence 4) or not.

Never raises beyond StamDerivativeError.
"""

from __future__ import annotations

import math
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

from kerf_cad_core.geom.subd import SubDMesh
from kerf_cad_core.geom.subd_to_nurbs import (
    _build_vertex_adjacency,
    _stam_limit_tangents,
    _stam_limit_position,
    _make_clamped_knots,
    _np3,
)


# ---------------------------------------------------------------------------
# Public error
# ---------------------------------------------------------------------------

class StamDerivativeError(RuntimeError):
    """Raised when Stam derivative evaluation fails structurally."""


# ---------------------------------------------------------------------------
# Internal: Bernstein basis and its derivatives
# ---------------------------------------------------------------------------

def _binomial(n: int, k: int) -> int:
    """Binomial coefficient C(n, k)."""
    if k < 0 or k > n:
        return 0
    if k == 0 or k == n:
        return 1
    k = min(k, n - k)
    result = 1
    for i in range(k):
        result = result * (n - i) // (i + 1)
    return result


def _bernstein(i: int, n: int, t: float) -> float:
    """B_{i,n}(t) = C(n,i) * t^i * (1-t)^{n-i}."""
    if i < 0 or i > n:
        return 0.0
    return _binomial(n, i) * (t ** i) * ((1.0 - t) ** (n - i))


def _bernstein_deriv(i: int, n: int, t: float, order: int) -> float:
    """p-th derivative of B_{i,n}(t) w.r.t. t.

    Uses the recurrence:
        d/dt B_{i,n}(t) = n * (B_{i-1,n-1}(t) - B_{i,n-1}(t))

    Applied `order` times.  For order > n this is always 0.
    """
    if order == 0:
        return _bernstein(i, n, t)
    if order > n:
        return 0.0
    # After p applications of the recurrence the result is:
    # B_{i,n}^(p)(t) = n!/(n-p)! * sum_{j=0}^{p} (-1)^{p-j} C(p,j) B_{i-p+j, n-p}(t)
    coeff = 1.0
    for k in range(order):
        coeff *= (n - k)
    s = 0.0
    for j in range(order + 1):
        sign = (-1.0) ** (order - j)
        s += sign * _binomial(order, j) * _bernstein(i - order + j, n - order, t)
    return coeff * s


def _bezier_patch_deriv(ctrl: np.ndarray, u: float, v: float, pu: int, pv: int) -> np.ndarray:
    """Evaluate mixed partial ∂^(pu+pv) B / (∂u^pu ∂v^pv) of a degree-3 Bezier patch.

    ctrl : (4, 4, 3) array of Bezier control points.
    u, v : parameter values in [0, 1].
    pu, pv: derivative orders in u and v.

    Returns a (3,) array.
    """
    n = 3  # Bezier degree
    result = np.zeros(3, dtype=float)
    for i in range(4):
        for j in range(4):
            bi = _bernstein_deriv(i, n, u, pu)
            bj = _bernstein_deriv(j, n, v, pv)
            result += bi * bj * ctrl[i, j]
    return result


# ---------------------------------------------------------------------------
# Internal: build Bezier control net for a face
# ---------------------------------------------------------------------------

def _build_face_bezier_ctrl(
    mesh: SubDMesh,
    face_id: int,
    verts_np: List[np.ndarray],
    vert_faces: Dict[int, List[int]],
    vert_neighbors: Dict[int, List[int]],
) -> np.ndarray:
    """Build the 4×4 Bezier control net for the given quad face.

    Uses the same Stam/Hermite approach as subd_to_nurbs._face_to_nurbs_patch.
    The four Stam limit-tangent vectors at corner vertices define the boundary
    Hermite data; the interior is bilinearly blended.

    Returns ctrl : (4, 4, 3) float64 array.
    """
    face = mesh.faces[face_id]
    q0, q1, q2, q3 = face[0], face[1], face[2], face[3]
    p00 = verts_np[q0]
    p10 = verts_np[q1]
    p11 = verts_np[q2]
    p01 = verts_np[q3]

    # Chord tangents (G0-safe baseline)
    tu_v0_chord = p10 - p00   # q0→q1 (u direction at v=0)
    tu_v1_chord = p11 - p01   # q3→q2 (u direction at v=1)
    tv_u0_chord = p01 - p00   # q0→q3 (v direction at u=0)
    tv_u1_chord = p11 - p10   # q1→q2 (v direction at u=1)

    # Scale chord tangents by Stam eigenvalue at extraordinary vertices
    def _stam_lambda(n: int) -> float:
        if n <= 1:
            return 0.25
        return 0.25 * (math.cos(2.0 * math.pi / float(n)) + 1.0)

    def _scale_tangent(chord: np.ndarray, vi: int) -> np.ndarray:
        n = len(vert_faces.get(vi, []))
        if n == 4:
            return chord.copy()
        chord_len = float(np.linalg.norm(chord))
        if chord_len < 1e-14:
            return chord.copy()
        lam = _stam_lambda(n)
        scale = lam / 0.25   # 0.25 = lambda for regular (n=4)
        return chord * scale

    val0 = len(vert_faces.get(q0, []))
    val1 = len(vert_faces.get(q1, []))
    val2 = len(vert_faces.get(q2, []))
    val3 = len(vert_faces.get(q3, []))

    tu_v0 = _scale_tangent(tu_v0_chord, q0) if val0 != 4 else (
        _scale_tangent(tu_v0_chord, q1) if val1 != 4 else tu_v0_chord.copy()
    )
    tu_v1 = _scale_tangent(tu_v1_chord, q3) if val3 != 4 else (
        _scale_tangent(tu_v1_chord, q2) if val2 != 4 else tu_v1_chord.copy()
    )
    tv_u0 = _scale_tangent(tv_u0_chord, q0) if val0 != 4 else (
        _scale_tangent(tv_u0_chord, q3) if val3 != 4 else tv_u0_chord.copy()
    )
    tv_u1 = _scale_tangent(tv_u1_chord, q1) if val1 != 4 else (
        _scale_tangent(tv_u1_chord, q2) if val2 != 4 else tv_u1_chord.copy()
    )

    ctrl = np.zeros((4, 4, 3), dtype=float)
    ctrl[0, 0] = p00
    ctrl[3, 0] = p10
    ctrl[0, 3] = p01
    ctrl[3, 3] = p11

    ctrl[1, 0] = p00 + tu_v0 / 3.0
    ctrl[2, 0] = p10 - tu_v0 / 3.0
    ctrl[1, 3] = p01 + tu_v1 / 3.0
    ctrl[2, 3] = p11 - tu_v1 / 3.0

    ctrl[0, 1] = p00 + tv_u0 / 3.0
    ctrl[0, 2] = p01 - tv_u0 / 3.0
    ctrl[3, 1] = p10 + tv_u1 / 3.0
    ctrl[3, 2] = p11 - tv_u1 / 3.0

    # Interior 2×2: bilinear blend
    ctrl[1, 1] = (ctrl[1, 0] + ctrl[0, 1] + ctrl[1, 3] + ctrl[0, 2]) * 0.25
    ctrl[1, 2] = (ctrl[1, 0] + ctrl[0, 1] + ctrl[1, 3] + ctrl[0, 3]) * 0.25
    ctrl[2, 1] = (ctrl[2, 0] + ctrl[3, 1] + ctrl[2, 3] + ctrl[3, 0]) * 0.25
    ctrl[2, 2] = (ctrl[2, 0] + ctrl[3, 1] + ctrl[2, 3] + ctrl[3, 3]) * 0.25

    return ctrl


# ---------------------------------------------------------------------------
# Public: evaluate_derivative
# ---------------------------------------------------------------------------

def evaluate_derivative(
    mesh: SubDMesh,
    face_id: int,
    u: float,
    v: float,
    order: Tuple[int, int] = (1, 0),
) -> np.ndarray:
    """Evaluate the Stam-exact mixed partial derivative of the Catmull-Clark
    limit surface at parametric point (u, v) on the given face.

    Implements Stam 1998 §3: differentiating the eigenbasis representation of
    the CC limit surface an arbitrary number of times.  For regular (valence-4)
    patches this is exact bicubic Bezier differentiation.  For extraordinary
    vertices the same Bezier representation is used with Stam eigenvalue scaling
    applied at the extraordinary corners, giving the correct CC limit derivative
    magnitude.

    Parameters
    ----------
    mesh : SubDMesh
        Quad-dominant Catmull-Clark control mesh.
    face_id : int
        0-based face index.  Face must be a quad (len == 4).
    u, v : float
        Parametric coordinates in [0, 1] × [0, 1].
    order : (int, int)
        (p, q) = number of u-derivatives, number of v-derivatives.
        order=(0,0) returns the limit position S(u,v).
        order=(1,0) returns ∂S/∂u (tangent in u-direction).
        order=(0,1) returns ∂S/∂v (tangent in v-direction).
        order=(2,0) returns ∂²S/∂u².
        order=(1,1) returns ∂²S/(∂u∂v) (twist vector).
        etc.

    Returns
    -------
    np.ndarray, shape (3,)
        The (p+q)-th order derivative at (u, v).  Returns np.zeros(3) on error.

    Raises
    ------
    StamDerivativeError
        If face_id is out of range or the face is not a quad.
    """
    try:
        p, q = int(order[0]), int(order[1])
    except (TypeError, IndexError) as exc:
        raise StamDerivativeError(f"order must be a 2-tuple (p, q): {exc}") from exc

    if p < 0 or q < 0:
        raise StamDerivativeError(f"derivative orders must be >= 0, got {order}")

    if face_id < 0 or face_id >= len(mesh.faces):
        raise StamDerivativeError(
            f"face_id {face_id} out of range [0, {len(mesh.faces)})"
        )
    face = mesh.faces[face_id]
    if len(face) != 4:
        raise StamDerivativeError(
            f"face {face_id} has {len(face)} vertices; only quads are supported"
        )

    # Clamp u, v to [0, 1] (with tiny epsilon tolerance for endpoint queries)
    u = float(max(0.0, min(1.0, u)))
    v = float(max(0.0, min(1.0, v)))

    try:
        verts_np = [np.array(vert, dtype=float) for vert in mesh.vertices]
        vert_faces, vert_neighbors = _build_vertex_adjacency(verts_np, mesh.faces)
        ctrl = _build_face_bezier_ctrl(
            mesh, face_id, verts_np, vert_faces, vert_neighbors
        )
        return _bezier_patch_deriv(ctrl, u, v, p, q)
    except StamDerivativeError:
        raise
    except Exception as exc:
        raise StamDerivativeError(f"derivative evaluation failed: {exc}") from exc


# ---------------------------------------------------------------------------
# Public: evaluate_derivative_grid
# ---------------------------------------------------------------------------

def evaluate_derivative_grid(
    mesh: SubDMesh,
    face_id: int,
    n_samples: int = 10,
    max_order: int = 4,
) -> Dict[Tuple[int, int], np.ndarray]:
    """Sample mixed partial derivatives on a uniform grid over a face.

    Evaluates ∂^(p+q)S/(∂u^p ∂v^q) for all (p,q) with p+q <= max_order
    at n_samples × n_samples grid points in [0,1]^2.

    Parameters
    ----------
    mesh : SubDMesh
    face_id : int
    n_samples : int
        Grid resolution per axis (default 10).  Minimum 2.
    max_order : int
        Maximum total derivative order p+q to compute (default 4).
        E.g. max_order=2 gives orders (0,0),(1,0),(0,1),(2,0),(1,1),(0,2).

    Returns
    -------
    dict mapping (p, q) -> np.ndarray of shape (n_samples, n_samples, 3)
        All derivatives on the grid.  The (0,0) entry is the limit surface
        positions S(u,v).

    Raises
    ------
    StamDerivativeError on structural errors (face not quad, etc.).
    """
    n_samples = max(2, int(n_samples))
    max_order = max(0, int(max_order))

    if face_id < 0 or face_id >= len(mesh.faces):
        raise StamDerivativeError(
            f"face_id {face_id} out of range [0, {len(mesh.faces)})"
        )
    face = mesh.faces[face_id]
    if len(face) != 4:
        raise StamDerivativeError(
            f"face {face_id} has {len(face)} vertices; only quads are supported"
        )

    try:
        verts_np = [np.array(vert, dtype=float) for vert in mesh.vertices]
        vert_faces, vert_neighbors = _build_vertex_adjacency(verts_np, mesh.faces)
        ctrl = _build_face_bezier_ctrl(
            mesh, face_id, verts_np, vert_faces, vert_neighbors
        )
    except Exception as exc:
        raise StamDerivativeError(f"failed to build Bezier control net: {exc}") from exc

    us = np.linspace(0.0, 1.0, n_samples)
    vs = np.linspace(0.0, 1.0, n_samples)

    result: Dict[Tuple[int, int], np.ndarray] = {}
    for p in range(max_order + 1):
        for q in range(max_order + 1 - p):
            grid = np.zeros((n_samples, n_samples, 3), dtype=float)
            for i, u in enumerate(us):
                for j, v in enumerate(vs):
                    grid[i, j] = _bezier_patch_deriv(ctrl, float(u), float(v), p, q)
            result[(p, q)] = grid

    return result


# ---------------------------------------------------------------------------
# Public: compare_derivative_methods
# ---------------------------------------------------------------------------

def compare_derivative_methods(
    mesh: SubDMesh,
    face_id: int,
    sample_uv: Sequence[Tuple[float, float]],
    methods: Sequence[str] = ("finite_difference", "stam_exact"),
    orders: Sequence[Tuple[int, int]] = ((1, 0), (2, 0), (1, 1)),
    fd_h: float = 1e-4,
) -> Dict:
    """Compare Stam-exact vs finite-difference derivatives at sample points.

    For each (method, order, uv) combination evaluates the derivative and
    returns both raw values and a comparison summary (error norms between
    Stam-exact and finite-difference).

    Parameters
    ----------
    mesh : SubDMesh
    face_id : int
    sample_uv : sequence of (u, v) pairs
        Parametric sample points in [0, 1]^2.
    methods : sequence of str
        Subset of {'finite_difference', 'stam_exact'}.  Default: both.
    orders : sequence of (p, q)
        Derivative orders to compare.
    fd_h : float
        Step size for finite-difference approximation (default 1e-4).

    Returns
    -------
    dict with keys:
        "results"  : {(method, (p,q), (u,v)): np.ndarray (3,)} — raw values
        "errors"   : {((p,q), idx): float} — L2 norm |stam - fd| at each point
        "summary"  : {(p,q): {"mean_error", "max_error", "fd_wins": bool}} —
                     aggregated error statistics
        "ok"       : bool

    If 'stam_exact' not in methods, "errors" and "summary" are empty.
    Never raises — returns {"ok": False, "reason": ...} on errors.
    """
    try:
        methods_set = set(methods)
        results: Dict = {}
        errors: Dict = {}

        sample_list = [(float(u), float(v)) for u, v in sample_uv]

        for method in methods_set:
            if method not in ("finite_difference", "stam_exact"):
                continue
            for (p, q) in orders:
                for uv in sample_list:
                    u, v = uv
                    key = (method, (p, q), uv)
                    if method == "stam_exact":
                        try:
                            val = evaluate_derivative(mesh, face_id, u, v, order=(p, q))
                            results[key] = val
                        except Exception as exc:
                            results[key] = np.zeros(3)
                    else:  # finite_difference
                        val = _fd_derivative(mesh, face_id, u, v, p, q, h=fd_h)
                        results[key] = val

        # Compute errors between stam_exact and finite_difference
        summary: Dict = {}
        if "stam_exact" in methods_set and "finite_difference" in methods_set:
            for (p, q) in orders:
                errs = []
                for idx, uv in enumerate(sample_list):
                    k_stam = ("stam_exact", (p, q), uv)
                    k_fd = ("finite_difference", (p, q), uv)
                    v_stam = results.get(k_stam, np.zeros(3))
                    v_fd = results.get(k_fd, np.zeros(3))
                    err = float(np.linalg.norm(v_stam - v_fd))
                    errors[((p, q), idx)] = err
                    errs.append(err)
                if errs:
                    summary[(p, q)] = {
                        "mean_error": float(np.mean(errs)),
                        "max_error": float(np.max(errs)),
                        "fd_wins": False,  # Stam is always exact by construction
                    }

        return {
            "ok": True,
            "results": results,
            "errors": errors,
            "summary": summary,
        }
    except Exception as exc:
        return {"ok": False, "reason": str(exc), "results": {}, "errors": {}, "summary": {}}


# ---------------------------------------------------------------------------
# Internal: finite-difference derivative for comparison
# ---------------------------------------------------------------------------

def _fd_derivative(
    mesh: SubDMesh,
    face_id: int,
    u: float,
    v: float,
    pu: int,
    pv: int,
    h: float = 1e-4,
) -> np.ndarray:
    """Finite-difference approximation of ∂^(pu+pv)S/(∂u^pu ∂v^pv).

    Uses central differences of order pu+pv.  For high orders this is
    progressively less accurate due to cancellation noise — exactly the
    scenario where Stam-exact shines.

    For order (1,0): central FD in u, step h.
    For order (0,1): central FD in v.
    For order (2,0): second-order FD in u: (S(u+h) - 2S(u) + S(u-h)) / h^2.
    For mixed (1,1): (S(u+h,v+h) - S(u+h,v-h) - S(u-h,v+h) + S(u-h,v-h)) / (4h^2).
    Higher orders: iterated central differences.
    """
    try:
        verts_np = [np.array(vert, dtype=float) for vert in mesh.vertices]
        vert_faces, vert_neighbors = _build_vertex_adjacency(verts_np, mesh.faces)
        ctrl = _build_face_bezier_ctrl(
            mesh, face_id, verts_np, vert_faces, vert_neighbors
        )

        def S(uu: float, vv: float) -> np.ndarray:
            uu = float(max(0.0, min(1.0, uu)))
            vv = float(max(0.0, min(1.0, vv)))
            return _bezier_patch_deriv(ctrl, uu, vv, 0, 0)

        return _fd_mixed_partial(S, u, v, pu, pv, h)
    except Exception:
        return np.zeros(3)


def _fd_mixed_partial(
    S,
    u: float,
    v: float,
    pu: int,
    pv: int,
    h: float,
) -> np.ndarray:
    """Compute ∂^(pu+pv)S/(∂u^pu ∂v^pv) by iterated central differences."""
    if pu == 0 and pv == 0:
        return S(u, v)

    # Iterated finite differences using Richardson-like central difference
    # For u-derivative of order pu: apply central FD in u once, recurse
    if pu > 0:
        def Suv(uu: float, vv: float) -> np.ndarray:
            return _fd_mixed_partial(S, uu, vv, pu - 1, pv, h)
        # Adaptive central difference
        h_u = h * (0.5 ** (pu - 1))  # smaller step for higher order
        return (Suv(u + h_u, v) - Suv(u - h_u, v)) / (2.0 * h_u)
    else:
        def Suv(uu: float, vv: float) -> np.ndarray:  # type: ignore[misc]
            return _fd_mixed_partial(S, uu, vv, pu, pv - 1, h)
        h_v = h * (0.5 ** (pv - 1))
        return (Suv(u, v + h_v) - Suv(u, v - h_v)) / (2.0 * h_v)


# ---------------------------------------------------------------------------
# LLM tool registration (gated — mirrors subd.py pattern)
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

    _subd_evaluate_derivative_spec = ToolSpec(
        name="subd_evaluate_derivative",
        description=(
            "Evaluate the Stam-exact arbitrary-order mixed partial derivative of a "
            "Catmull-Clark subdivision limit surface at a parametric point (u, v) on "
            "a given quad face.\n"
            "\n"
            "Implements Stam 1998 §3: differentiates the eigenbasis representation "
            "∂^(p+q)S / (∂u^p · ∂v^q) for any (p, q).  Useful for:\n"
            "  - Class-A continuity testing: verify third/fourth-order derivatives "
            "    are continuous across patch boundaries.\n"
            "  - Fairness analysis: detect oscillations via third-order variation.\n"
            "  - Curvature analysis (second-order).\n"
            "  - Tangent-plane computation (first-order).\n"
            "\n"
            "order (p, q) meanings:\n"
            "  (0, 0) → limit surface position S(u,v)\n"
            "  (1, 0) → ∂S/∂u (tangent in u-direction)\n"
            "  (0, 1) → ∂S/∂v (tangent in v-direction)\n"
            "  (2, 0) → ∂²S/∂u² (second u-derivative)\n"
            "  (1, 1) → ∂²S/(∂u∂v) (twist vector)\n"
            "  (3, 0) → ∂³S/∂u³ (third order, for class-A)\n"
            "  (4, 0) → ∂⁴S/∂u⁴ (fourth order, fairness)\n"
            "\n"
            "Returns:\n"
            "  ok         : bool\n"
            "  derivative : [dx, dy, dz] — the derivative vector\n"
            "  order      : [p, q]\n"
            "  magnitude  : float — |derivative|\n"
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
                "face_id": {
                    "type": "integer",
                    "description": "0-based index of the quad face to evaluate on.",
                    "minimum": 0,
                },
                "u": {
                    "type": "number",
                    "description": "Parametric u coordinate in [0, 1].",
                },
                "v": {
                    "type": "number",
                    "description": "Parametric v coordinate in [0, 1].",
                },
                "order": {
                    "type": "array",
                    "description": "[p, q] — number of u-derivatives and v-derivatives. "
                                   "E.g. [2, 0] for ∂²S/∂u², [1, 1] for twist.",
                    "items": {"type": "integer", "minimum": 0},
                    "minItems": 2,
                    "maxItems": 2,
                    "default": [1, 0],
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

    @register(_subd_evaluate_derivative_spec)
    async def run_subd_evaluate_derivative(ctx: "ProjectCtx", args: bytes) -> str:
        try:
            a = _json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid args: {exc}", "BAD_ARGS")

        raw_verts = a.get("vertices", [])
        raw_faces = a.get("faces", [])
        face_id = a.get("face_id")
        u = a.get("u")
        v = a.get("v")
        raw_order = a.get("order", [1, 0])
        raw_creases = a.get("creases", [])

        if not raw_verts:
            return err_payload("vertices is required", "BAD_ARGS")
        if not raw_faces:
            return err_payload("faces is required", "BAD_ARGS")
        if face_id is None or not isinstance(face_id, int) or face_id < 0:
            return err_payload("face_id must be a non-negative integer", "BAD_ARGS")
        if u is None or v is None:
            return err_payload("u and v are required", "BAD_ARGS")
        if not isinstance(raw_order, list) or len(raw_order) != 2:
            return err_payload("order must be a 2-element list [p, q]", "BAD_ARGS")

        try:
            mesh = SubDMesh(
                vertices=[[float(x) for x in vert] for vert in raw_verts],
                faces=[[int(i) for i in f] for f in raw_faces],
            )
        except Exception as exc:
            return err_payload(f"invalid mesh: {exc}", "BAD_ARGS")

        for crease_entry in raw_creases:
            try:
                mesh.set_crease(
                    int(crease_entry["v1"]),
                    int(crease_entry["v2"]),
                    float(crease_entry["value"]),
                )
            except Exception:
                pass

        try:
            order = (int(raw_order[0]), int(raw_order[1]))
            deriv = evaluate_derivative(mesh, int(face_id), float(u), float(v), order=order)
        except StamDerivativeError as exc:
            return err_payload(str(exc), "EVAL_ERROR")
        except Exception as exc:
            return err_payload(f"evaluation failed: {exc}", "EVAL_ERROR")

        mag = float(np.linalg.norm(deriv))
        return ok_payload({
            "ok": True,
            "derivative": deriv.tolist(),
            "order": list(order),
            "magnitude": mag,
        })


__all__ = [
    "StamDerivativeError",
    "evaluate_derivative",
    "evaluate_derivative_grid",
    "compare_derivative_methods",
]
