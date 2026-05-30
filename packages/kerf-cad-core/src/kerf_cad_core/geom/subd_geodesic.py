"""
subd_geodesic.py
================
Geodesic distance on triangle/quad meshes via the **heat method**
(Crane, Weischedel & Wardetzky 2013, "Geodesics in Heat: A New Approach to
Computing Distance Based on Heat Flow", ACM TOG 32(5)).

The algorithm runs entirely in Python with numpy + scipy.sparse.  No OCCT
or external binary dependency.

Algorithm summary
-----------------
Given a triangulated (or auto-triangulated quad) mesh and a set of source
vertices:

1. Build the cotangent Laplacian **L** (intrinsic geometry) and the lumped
   diagonal mass matrix **M** (vertex areas).
2. Solve the heat equation ``(M − t·L) u = δ``  where ``δ_i = 1`` for
   sources and 0 elsewhere, and ``t = h²·c`` with ``h`` = mean edge length
   and ``c = 5`` (default multiplier).
3. For each triangle face, approximate the gradient ``∇u`` from the per-vertex
   ``u`` values, normalise to unit length: ``X = −∇u / ‖∇u‖``.
4. Compute the divergence ``∇·X`` per vertex.
5. Solve the Poisson equation ``L φ = ∇·X`` for ``φ``.
6. Shift ``φ`` so the minimum is zero (sources should be at distance 0).

Public API
----------
compute_geodesic_heat_method(mesh, source_indices, time_step=None) → ndarray
    Per-vertex geodesic distances from the given source set.

compute_geodesic_to_point(mesh, source_point) → ndarray
    Find the nearest vertex to *source_point* and call
    ``compute_geodesic_heat_method``.

compute_geodesic_path(mesh, source_idx, target_idx) → list[list[float]]
    Trace the geodesic path from *source_idx* back to *target_idx* by
    steepest-descent on the distance field.  Returns an ordered list of
    ``[x, y, z]`` waypoints (vertex positions).

All functions accept ``SubDMesh`` instances (from ``subd.py``) or plain
dict-style meshes ``{"vertices": [[x,y,z],...], "faces": [[i,j,k/l],...]}``
and never raise — errors are returned as zero-filled arrays or empty lists.

References
----------
* Crane K., Weischedel C., Wardetzky M. (2013). "Geodesics in Heat: A New
  Approach to Computing Distance Based on Heat Flow." ACM Transactions on
  Graphics, 32(5), Article 152.  DOI: 10.1145/2516971.2516977
"""

from __future__ import annotations

import math
from typing import Any, List, Optional, Sequence, Union

import numpy as np
import scipy.sparse as sp
import scipy.sparse.linalg as spla


# ---------------------------------------------------------------------------
# Type helpers
# ---------------------------------------------------------------------------

# Accept SubDMesh instances OR plain dicts with 'vertices'/'faces'
MeshLike = Any


def _to_arrays(mesh: MeshLike):
    """Return (V, F_tri) numpy arrays from SubDMesh or dict.

    Quads are split into two triangles:  [a,b,c,d] → [a,b,c], [a,c,d].
    F_tri has shape (T, 3), dtype int64.
    """
    if hasattr(mesh, "vertices"):
        verts = mesh.vertices
        faces = mesh.faces
    else:
        verts = mesh["vertices"]
        faces = mesh["faces"]

    V = np.array(verts, dtype=np.float64)   # (n_verts, 3)

    tri_list: List[List[int]] = []
    for face in faces:
        f = list(face)
        n = len(f)
        if n < 3:
            continue
        if n == 3:
            tri_list.append(f)
        else:
            # Fan triangulation from first vertex
            for k in range(1, n - 1):
                tri_list.append([f[0], f[k], f[k + 1]])

    F = np.array(tri_list, dtype=np.int64)   # (T, 3)
    return V, F


# ---------------------------------------------------------------------------
# Cotangent Laplacian + mass matrix
# ---------------------------------------------------------------------------

def _build_laplacian_and_mass(V: np.ndarray, F: np.ndarray):
    """Construct the cotangent Laplacian and the lumped mass matrix.

    Returns
    -------
    L : scipy.sparse CSC matrix (n, n)
        Cotangent Laplacian, positive semi-definite (−∑ cot weights).
        Convention: L[i,i] = ∑_j w_ij; L[i,j] = −w_ij.
    M : scipy.sparse CSC diagonal matrix (n, n)
        Lumped (Voronoi area) mass matrix.
    """
    n = V.shape[0]
    T = F.shape[0]

    rows, cols, vals = [], [], []
    areas = np.zeros(n)

    for t in range(T):
        i0, i1, i2 = F[t]
        p0, p1, p2 = V[i0], V[i1], V[i2]

        # Edge vectors
        e0 = p2 - p1   # opposite vertex i0
        e1 = p0 - p2   # opposite vertex i1
        e2 = p1 - p0   # opposite vertex i2

        # Triangle area (half cross product magnitude)
        cross = np.cross(e2, -e1)  # = np.cross(p1-p0, p2-p0)
        area = 0.5 * np.linalg.norm(cross)
        if area < 1e-15:
            continue

        # Cotangent weights: cot(angle at vertex i) = (e_a · e_b) / (2 * area)
        # where e_a, e_b are the two edge vectors emanating from i.
        # For vertex i0: edges are (p1-p0) and (p2-p0) → e2 and -e1
        # For vertex i1: edges are (p0-p1) and (p2-p1) → -e2 and e0
        # For vertex i2: edges are (p0-p2) and (p1-p2) → e1 and -e0
        cot0 = np.dot(-e2,  e1) / (2.0 * area)   # cot at i0
        cot1 = np.dot(-e0,  e2) / (2.0 * area)   # cot at i1
        cot2 = np.dot(-e1,  e0) / (2.0 * area)   # cot at i2

        # Clamp to avoid numerical blow-up near degenerate angles
        cot0 = max(-10.0, min(10.0, cot0))
        cot1 = max(-10.0, min(10.0, cot1))
        cot2 = max(-10.0, min(10.0, cot2))

        # L[i0, i1] += -0.5*(cot2) (shared by the two faces adjacent to edge i0-i1)
        # Contribution from this triangle to edge (i0, i1): cot at i2 / 2
        # Similarly for (i1, i2): cot at i0 / 2, and (i0, i2): cot at i1 / 2
        for ia, ib, wt in [(i0, i1, cot2), (i1, i2, cot0), (i0, i2, cot1)]:
            w = 0.5 * wt
            # Off-diagonal entries
            rows += [ia, ib]
            cols += [ib, ia]
            vals += [-w, -w]
            # Diagonal entries
            rows += [ia, ib]
            cols += [ia, ib]
            vals += [w, w]

        # Lumped mass: each vertex gets 1/3 of the triangle area
        areas[i0] += area / 3.0
        areas[i1] += area / 3.0
        areas[i2] += area / 3.0

    L = sp.csc_matrix((vals, (rows, cols)), shape=(n, n))
    M = sp.diags(areas, format="csc")
    return L, M


# ---------------------------------------------------------------------------
# Face gradient
# ---------------------------------------------------------------------------

def _face_gradient(V: np.ndarray, F: np.ndarray, u: np.ndarray) -> np.ndarray:
    """Compute per-face gradient of scalar field *u*.

    Returns
    -------
    grad : ndarray, shape (T, 3)
        Gradient vector in 3-D for each triangle face.
    """
    T = F.shape[0]
    grad = np.zeros((T, 3))

    for t in range(T):
        i0, i1, i2 = F[t]
        p0, p1, p2 = V[i0], V[i1], V[i2]

        e1 = p1 - p0   # edge p0→p1
        e2 = p2 - p0   # edge p0→p2

        normal = np.cross(e1, e2)
        area2 = np.linalg.norm(normal)
        if area2 < 1e-15:
            continue
        n_hat = normal / area2   # unit normal
        area = 0.5 * area2

        # Gradient formula: ∇u = 1/(2A) * sum_i u_i * (n × e_i_opp)
        # where e_i_opp is the edge opposite to vertex i.
        # Opposite edges (wound CCW from inside the face):
        #   vertex i0 → opposite edge: p2 - p1 = e2 - e1
        #   vertex i1 → opposite edge: p0 - p2 = -e2
        #   vertex i2 → opposite edge: p1 - p0 = e1 but negated sign correction
        # Standard formula: ∇u = (1/2A) * (u0*(n×(p2-p1)) + u1*(n×(p0-p2)) + u2*(n×(p1-p0)))
        e_opp0 = p2 - p1   # opposite edge for vertex i0
        e_opp1 = p0 - p2   # opposite edge for vertex i1
        e_opp2 = p1 - p0   # opposite edge for vertex i2

        gu = (u[i0] * np.cross(n_hat, e_opp0) +
              u[i1] * np.cross(n_hat, e_opp1) +
              u[i2] * np.cross(n_hat, e_opp2)) / (2.0 * area)
        grad[t] = gu

    return grad


# ---------------------------------------------------------------------------
# Divergence of face vector field → per vertex
# ---------------------------------------------------------------------------

def _divergence(V: np.ndarray, F: np.ndarray, X: np.ndarray) -> np.ndarray:
    """Compute per-vertex divergence of per-face vector field *X*.

    Implements: div_i = (1/2) ∑_{t ∈ N(i)} (cot(α_j) * X_t·e_ij + cot(α_k) * X_t·e_ik)
    where j, k are the other two vertices of triangle t opposite vertex i,
    and α_j, α_k are the angles at j and k.

    Parameters
    ----------
    V : (n, 3) vertex positions
    F : (T, 3) face indices
    X : (T, 3) per-face unit-gradient vectors

    Returns
    -------
    div : (n,) divergence per vertex
    """
    n = V.shape[0]
    div = np.zeros(n)

    for t in range(F.shape[0]):
        i0, i1, i2 = F[t]
        p0, p1, p2 = V[i0], V[i1], V[i2]

        e0 = p2 - p1
        e1 = p0 - p2
        e2 = p1 - p0

        cross = np.cross(e2, -e1)
        area = 0.5 * np.linalg.norm(cross)
        if area < 1e-15:
            continue

        cot0 = np.dot(-e2,  e1) / (2.0 * area)
        cot1 = np.dot(-e0,  e2) / (2.0 * area)
        cot2 = np.dot(-e1,  e0) / (2.0 * area)

        cot0 = max(-10.0, min(10.0, cot0))
        cot1 = max(-10.0, min(10.0, cot1))
        cot2 = max(-10.0, min(10.0, cot2))

        Xt = X[t]

        # Vertex i0 uses angles at i1 (cot1) and i2 (cot2)
        div[i0] += 0.5 * (cot2 * np.dot(Xt, p1 - p0) + cot1 * np.dot(Xt, p2 - p0))
        # Vertex i1 uses angles at i0 (cot0) and i2 (cot2)
        div[i1] += 0.5 * (cot0 * np.dot(Xt, p2 - p1) + cot2 * np.dot(Xt, p0 - p1))
        # Vertex i2 uses angles at i0 (cot0) and i1 (cot1)
        div[i2] += 0.5 * (cot1 * np.dot(Xt, p0 - p2) + cot0 * np.dot(Xt, p1 - p2))

    return div


# ---------------------------------------------------------------------------
# Mean edge length
# ---------------------------------------------------------------------------

def _mean_edge_length(V: np.ndarray, F: np.ndarray) -> float:
    edges = set()
    for face in F:
        for k in range(3):
            a, b = int(face[k]), int(face[(k + 1) % 3])
            edges.add((min(a, b), max(a, b)))
    if not edges:
        return 1.0
    lengths = [np.linalg.norm(V[a] - V[b]) for a, b in edges]
    return float(np.mean(lengths))


# ---------------------------------------------------------------------------
# Core heat-method solver
# ---------------------------------------------------------------------------

def compute_geodesic_heat_method(
    mesh: MeshLike,
    source_indices: Sequence[int],
    time_step: Optional[float] = None,
) -> np.ndarray:
    """Compute per-vertex geodesic distances from *source_indices* on *mesh*.

    Implements the heat method of Crane, Weischedel & Wardetzky (2013).

    Parameters
    ----------
    mesh : SubDMesh or dict with ``vertices`` / ``faces``
        The input mesh.  Quad faces are automatically split into triangles.
    source_indices : sequence of int
        Vertex indices of the heat sources (δ-function sources).  The returned
        distance is the minimum geodesic distance to *any* of these sources.
    time_step : float, optional
        Heat diffusion time.  Defaults to ``h² × 5`` where ``h`` is the mean
        edge length — the recommended heuristic from the paper.

    Returns
    -------
    distances : ndarray, shape (n_verts,)
        Per-vertex geodesic distances (float64, ≥ 0).
        Returns a zero-filled array on error.
    """
    try:
        V, F = _to_arrays(mesh)
        n = V.shape[0]

        if n == 0 or F.shape[0] == 0:
            return np.zeros(n)

        sources = list(source_indices)
        if not sources:
            return np.zeros(n)

        # Clamp source indices
        sources = [int(s) for s in sources if 0 <= int(s) < n]
        if not sources:
            return np.zeros(n)

        # --- Step 0: build matrices ---
        L, M = _build_laplacian_and_mass(V, F)

        # --- Step 1: heat diffusion time ---
        h = _mean_edge_length(V, F)
        if time_step is None or time_step <= 0.0:
            t = h * h * 5.0
        else:
            t = float(time_step)

        # --- Step 2: solve (M + t·L) u = delta ---
        # Sign convention: L is the **positive** cotangent Laplacian,
        # i.e. L[i,i] = Σ_j w_ij > 0 and L[i,j] = −w_ij ≤ 0.
        # The heat equation ∂u/∂t = Δu discretises as
        #     (M + t·L) u_t = M·u_0
        # where the delta source is M·δ ≈ δ (lumped mass absorbed into RHS).
        # This produces u that is maximum at the source and decays outward.
        delta = np.zeros(n)
        for s in sources:
            delta[s] = 1.0

        A = (M + t * L).tocsc()
        # Use spsolve (direct factorisation via SuperLU / CHOLMOD)
        try:
            u = spla.spsolve(A, delta)
        except Exception:
            # Fallback: LSQR
            result = spla.lsqr(A, delta)
            u = result[0]

        # --- Step 3: normalise gradient X = −∇u / |∇u| ---
        # u is a heat kernel (max at source, decaying outward), so ∇u points
        # *toward* the source.  X = −∇u / |∇u| points *away* from the source.
        grad_u = _face_gradient(V, F, u)
        grad_norms = np.linalg.norm(grad_u, axis=1, keepdims=True)
        # Avoid division by zero on degenerate faces
        safe_norms = np.where(grad_norms < 1e-15, 1.0, grad_norms)
        X = -grad_u / safe_norms   # (T, 3) unit vectors pointing away from source

        # --- Step 4: divergence ∇·X ---
        rhs = _divergence(V, F, X)

        # --- Step 5: solve L φ = ∇·X ---
        # Add a small diagonal regulariser to make L non-singular on open meshes
        eps = 1e-8
        L_reg = (L + eps * sp.eye(n, format="csc")).tocsc()
        try:
            phi = spla.spsolve(L_reg, rhs)
        except Exception:
            result = spla.lsqr(L_reg, rhs)
            phi = result[0]

        # --- Step 6: correct orientation and shift so sources are at 0 ---
        # The Poisson solve yields φ that is *maximum* at the source because
        # ∇·X is a source term at the origin.  Negate to get a distance-like
        # field that is minimum (zero) at the source and grows outward.
        phi = -phi
        phi -= np.min(phi[sources])   # align minimum source to 0

        # Clip negatives from numerical noise
        phi = np.maximum(phi, 0.0)
        return phi.astype(np.float64)

    except Exception:
        # Never raise — return zeros
        try:
            V, _ = _to_arrays(mesh)
            return np.zeros(V.shape[0])
        except Exception:
            return np.zeros(0)


# ---------------------------------------------------------------------------
# Nearest-vertex convenience wrapper
# ---------------------------------------------------------------------------

def compute_geodesic_to_point(
    mesh: MeshLike,
    source_point: Sequence[float],
) -> np.ndarray:
    """Compute per-vertex geodesic distances from the mesh vertex nearest to
    *source_point*.

    Parameters
    ----------
    mesh : SubDMesh or dict
        The input mesh.
    source_point : sequence of 3 floats
        3-D query point.  The closest mesh vertex is used as the heat source.

    Returns
    -------
    distances : ndarray, shape (n_verts,)
    """
    try:
        V, _ = _to_arrays(mesh)
        if V.shape[0] == 0:
            return np.zeros(0)
        sp_pt = np.array(source_point, dtype=np.float64)
        dists = np.linalg.norm(V - sp_pt[None, :], axis=1)
        nearest = int(np.argmin(dists))
        return compute_geodesic_heat_method(mesh, [nearest])
    except Exception:
        try:
            V, _ = _to_arrays(mesh)
            return np.zeros(V.shape[0])
        except Exception:
            return np.zeros(0)


# ---------------------------------------------------------------------------
# Geodesic path tracing
# ---------------------------------------------------------------------------

def compute_geodesic_path(
    mesh: MeshLike,
    source_idx: int,
    target_idx: int,
) -> List[List[float]]:
    """Trace the geodesic path from *source_idx* to *target_idx*.

    Algorithm: compute the distance field from *source_idx*, then follow the
    steepest-descent direction (negative gradient of φ) vertex-by-vertex from
    *target_idx* back to the source.

    Parameters
    ----------
    mesh : SubDMesh or dict
    source_idx : int
        Starting vertex index.
    target_idx : int
        Ending vertex index.

    Returns
    -------
    path : list of [x, y, z]
        Ordered waypoints from *source_idx* to *target_idx*.
        Returns an empty list on error.
    """
    try:
        V, F = _to_arrays(mesh)
        n = V.shape[0]
        if n == 0 or not (0 <= source_idx < n) or not (0 <= target_idx < n):
            return []

        # Build vertex-level adjacency once
        adj: List[List[int]] = [[] for _ in range(n)]
        for face in F:
            for k in range(3):
                a, b = int(face[k]), int(face[(k + 1) % 3])
                if b not in adj[a]:
                    adj[a].append(b)
                if a not in adj[b]:
                    adj[b].append(a)

        phi = compute_geodesic_heat_method(mesh, [source_idx])

        # Walk from target back to source following minimum-phi neighbours
        path_indices = [target_idx]
        visited = {target_idx}
        current = target_idx
        max_steps = n  # guard against infinite loops

        for _ in range(max_steps):
            if current == source_idx:
                break
            neighbours = adj[current]
            if not neighbours:
                break
            # Pick neighbour with smallest φ
            best = min(neighbours, key=lambda v: phi[v])
            if phi[best] >= phi[current]:
                # Stuck at a local minimum — break (shouldn't happen on smooth meshes)
                break
            if best in visited:
                break
            path_indices.append(best)
            visited.add(best)
            current = best

        # Reverse so it goes source → target
        path_indices.reverse()

        return [list(V[i]) for i in path_indices]

    except Exception:
        return []


# ---------------------------------------------------------------------------
# LLM tool registration (optional — kerf_chat not always installed)
# ---------------------------------------------------------------------------

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register  # type: ignore[import]
    from kerf_core.utils.context import ProjectCtx  # type: ignore[import]
    import json as _json
    _REGISTRY_AVAILABLE = True
except ImportError:
    _REGISTRY_AVAILABLE = False


if _REGISTRY_AVAILABLE:

    # -----------------------------------------------------------------------
    # subd_geodesic_distance
    # -----------------------------------------------------------------------

    _subd_geodesic_spec = ToolSpec(
        name="subd_geodesic_distance",
        description=(
            "Compute per-vertex geodesic distances on a triangle or quad mesh "
            "using the heat method (Crane, Weischedel & Wardetzky 2013, ACM TOG "
            "32:5). Suitable for SubD limit surfaces, scan meshes, and arbitrary "
            "triangulated geometry.\n\n"
            "The heat method is O(n) after a one-time Cholesky factorisation and "
            "produces smooth, accurate geodesic distances even on coarse meshes.\n\n"
            "**Mode 1 — by vertex index** (``source_indices``): supply a list of "
            "vertex indices; the result is the min-distance to any of those sources.\n\n"
            "**Mode 2 — by 3-D point** (``source_point``): supply a [x,y,z] point; "
            "the nearest mesh vertex is found and used as the source.\n\n"
            "**Path tracing** (``trace_path=true``): additionally returns a "
            "``path`` list of [x,y,z] waypoints along the geodesic from the "
            "first source vertex to ``target_index``.\n\n"
            "Returns: {ok, distances:[float,...], "
            "source_vertices:[int,...], "
            "vertex_count:int, "
            "time_step:float, "
            "path?:[[x,y,z],...]}\n\n"
            "Errors: {ok:false, reason}.  Never raises."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "verts": {
                    "type": "array",
                    "description": "Vertex list [[x,y,z], ...]",
                    "items": {"type": "array", "items": {"type": "number"}},
                },
                "faces": {
                    "type": "array",
                    "description": (
                        "Face list — triangles [[i,j,k],...] or quads [[i,j,k,l],...] "
                        "(0-based indices).  Quads are automatically triangulated."
                    ),
                    "items": {"type": "array", "items": {"type": "integer"}},
                },
                "source_indices": {
                    "type": "array",
                    "description": (
                        "Vertex indices of heat sources.  Geodesic distance is the "
                        "minimum distance to any source.  Mutually exclusive with "
                        "``source_point``."
                    ),
                    "items": {"type": "integer"},
                },
                "source_point": {
                    "type": "array",
                    "description": (
                        "[x, y, z] 3-D point.  The nearest vertex is used as the "
                        "source.  Mutually exclusive with ``source_indices``."
                    ),
                    "items": {"type": "number"},
                },
                "time_step": {
                    "type": "number",
                    "description": (
                        "Heat diffusion time t.  Defaults to h²×5 where h is the "
                        "mean edge length — the recommended heuristic.  Larger values "
                        "give smoother but less accurate distances."
                    ),
                },
                "trace_path": {
                    "type": "boolean",
                    "description": (
                        "If true, also trace the geodesic path from the first source "
                        "vertex to ``target_index``."
                    ),
                },
                "target_index": {
                    "type": "integer",
                    "description": "Target vertex for path tracing (requires trace_path=true).",
                },
            },
            "required": ["verts", "faces"],
        },
    )

    @register(_subd_geodesic_spec)
    async def run_subd_geodesic_distance(ctx: "ProjectCtx", args: bytes) -> str:
        try:
            a = _json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid args: {exc}", "BAD_ARGS")

        verts = a.get("verts")
        faces = a.get("faces")
        if not verts or not faces:
            return err_payload("verts and faces are required", "BAD_ARGS")

        mesh = {"vertices": verts, "faces": faces}
        time_step = a.get("time_step")
        source_indices = a.get("source_indices")
        source_point = a.get("source_point")

        if source_indices is not None:
            phi = compute_geodesic_heat_method(mesh, source_indices, time_step=time_step)
            src_verts = source_indices
        elif source_point is not None:
            phi = compute_geodesic_to_point(mesh, source_point)
            # Find which vertex was selected
            try:
                V = np.array(verts, dtype=np.float64)
                sp_pt = np.array(source_point, dtype=np.float64)
                dists = np.linalg.norm(V - sp_pt[None, :], axis=1)
                src_verts = [int(np.argmin(dists))]
            except Exception:
                src_verts = []
        else:
            return err_payload("one of source_indices or source_point is required", "BAD_ARGS")

        # Compute actual time step used
        try:
            V_arr, F_arr = _to_arrays(mesh)
            h = _mean_edge_length(V_arr, F_arr)
            used_t = float(time_step) if (time_step and time_step > 0) else h * h * 5.0
        except Exception:
            used_t = -1.0

        payload: dict = {
            "distances": phi.tolist(),
            "source_vertices": src_verts,
            "vertex_count": len(phi),
            "time_step": used_t,
        }

        # Optional path tracing
        if a.get("trace_path") and a.get("target_index") is not None and src_verts:
            path = compute_geodesic_path(mesh, src_verts[0], int(a["target_index"]))
            payload["path"] = path

        return ok_payload(payload)
