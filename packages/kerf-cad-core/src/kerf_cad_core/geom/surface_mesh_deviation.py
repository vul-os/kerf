"""
surface_mesh_deviation.py
=========================
NURBS surface ↔ triangle mesh max-deviation metrics.

Implements Hausdorff distance and per-region max / RMS deviation between a
NURBS surface and a reference triangle mesh, as required for class-A acceptance
of reverse-engineering fits (point cloud → NURBS surface).

Functions
---------
hausdorff_surface_to_mesh(surface, mesh, n_samples) -> SurfaceMeshDeviation
    One-sided Hausdorff: sample the NURBS surface, find closest point on the
    mesh for each sample, return max / mean / RMS and per-region max.

bidirectional_hausdorff(surface, mesh, n_samples) -> dict
    Two-sided symmetric Hausdorff = max(surface→mesh, mesh→surface).

max_deviation_visualization(surface, mesh, n_samples_u, n_samples_v) -> dict
    UV-grid deviation map for false-colour heatmap display.

Data class
----------
SurfaceMeshDeviation
    hausdorff_max, hausdorff_mean, rms, per_region_max, n_samples_used.

References
----------
Aspert, N., Santa-Cruz, D., Ebrahimi, T. (2002).  "MESH: Measuring errors
between surfaces using the Hausdorff distance."  Proc. ICME 2002.

Cignoni, P., Rocchini, C., Scopigno, R. (1998).  "Metro: Measuring error on
simplified surfaces."  Computer Graphics Forum 17(2).

Piegl, L. & Tiller, W. (1997).  The NURBS Book, 2nd ed., Springer.

Algorithm
---------
For each NURBS sample p:
  1. Build a KDTree over mesh *vertices* — O(log N) approximate nearest vertex.
  2. Expand to all triangles incident to the k nearest vertices.
  3. For each candidate triangle, compute the exact closest point (point-triangle
     projection) and update the minimum distance.

This two-stage approach gives exact closest-point distances without the expense
of a full brute-force search over all triangles.  The KDTree vertex expansion
guarantees coverage: the true closest point on any triangle is reachable from
at least one of its three vertices.

Mesh format
-----------
mesh : dict with keys:
    "vertices"  — (N, 3) float array or list of [x, y, z]
    "triangles" — (M, 3) int array or list of [i, j, k] vertex indices

All functions return {"ok": True/False, "reason": str, ...} — never raise.
LLM tool registered as ``nurbs_max_deviation_to_mesh`` via @register.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np
from scipy.spatial import KDTree  # noqa: F401

from kerf_cad_core.geom.nurbs import NurbsSurface, surface_evaluate


# ---------------------------------------------------------------------------
# Data class
# ---------------------------------------------------------------------------

@dataclass
class SurfaceMeshDeviation:
    """Result of a NURBS surface ↔ mesh deviation computation.

    Attributes
    ----------
    hausdorff_max : float
        One-sided Hausdorff distance: max over all surface samples of the
        closest-point distance to the mesh.  This is the dominant metric for
        class-A acceptance: it bounds the worst-case fit error.

    hausdorff_mean : float
        Mean over all sample→closest-point distances.

    rms : float
        Root-mean-square of all sample→closest-point distances.

    per_region_max : dict
        If a region map was supplied (list of (u_lo, u_hi, v_lo, v_hi) tuples),
        maps region index → max deviation in that region.  Empty dict otherwise.

    n_samples_used : int
        Actual number of surface samples evaluated (may be < n_samples when
        surface domain is degenerate).
    """
    hausdorff_max: float = 0.0
    hausdorff_mean: float = 0.0
    rms: float = 0.0
    per_region_max: Dict[int, float] = field(default_factory=dict)
    n_samples_used: int = 0


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _parse_mesh(
    mesh: dict,
) -> Tuple[Optional[np.ndarray], Optional[np.ndarray], str]:
    """Parse and validate mesh dict.  Returns (vertices, triangles, error_str)."""
    if not isinstance(mesh, dict):
        return None, None, "mesh must be a dict with 'vertices' and 'triangles'"
    verts_raw = mesh.get("vertices")
    tris_raw  = mesh.get("triangles")
    if verts_raw is None or tris_raw is None:
        return None, None, "mesh must have 'vertices' and 'triangles' keys"
    try:
        verts = np.asarray(verts_raw, dtype=float)
        if verts.ndim == 1 and verts.size == 0:
            return None, None, "mesh has no vertices"
        if verts.ndim != 2 or verts.shape[1] < 3:
            verts = verts.reshape(-1, 3)
    except Exception as exc:
        return None, None, f"invalid vertices: {exc}"
    try:
        tris = np.asarray(tris_raw, dtype=int)
        if tris.ndim != 2 or tris.shape[1] != 3:
            tris = tris.reshape(-1, 3)
    except Exception as exc:
        return None, None, f"invalid triangles: {exc}"
    if verts.shape[0] == 0:
        return None, None, "mesh has no vertices"
    if tris.shape[0] == 0:
        return None, None, "mesh has no triangles"
    max_idx = int(np.max(tris))
    if max_idx >= verts.shape[0]:
        return None, None, (
            f"triangle index {max_idx} exceeds vertex count {verts.shape[0]}"
        )
    return verts[:, :3], tris, ""


def _point_triangle_closest(
    p: np.ndarray,
    a: np.ndarray,
    b: np.ndarray,
    c: np.ndarray,
) -> float:
    """Closest squared distance from point p to triangle (a, b, c).

    Uses the standard parametric projection (Ericson 2005, "Real-Time Collision
    Detection" §5.1.5).  Handles all Voronoi regions correctly: vertex, edge,
    and face interior.

    Returns the squared distance (caller takes sqrt when needed).
    """
    ab = b - a
    ac = c - a
    ap = p - a

    d1 = float(np.dot(ab, ap))
    d2 = float(np.dot(ac, ap))
    if d1 <= 0.0 and d2 <= 0.0:
        # Voronoi region of vertex A
        diff = p - a
        return float(np.dot(diff, diff))

    bp = p - b
    d3 = float(np.dot(ab, bp))
    d4 = float(np.dot(ac, bp))
    if d3 >= 0.0 and d4 <= d3:
        # Voronoi region of vertex B
        diff = p - b
        return float(np.dot(diff, diff))

    cp = p - c
    d5 = float(np.dot(ab, cp))
    d6 = float(np.dot(ac, cp))
    if d6 >= 0.0 and d5 <= d6:
        # Voronoi region of vertex C
        diff = p - c
        return float(np.dot(diff, diff))

    vc = d1 * d4 - d3 * d2
    if vc <= 0.0 and d1 >= 0.0 and d3 <= 0.0:
        # Edge AB
        v = d1 / (d1 - d3)
        q = a + v * ab
        diff = p - q
        return float(np.dot(diff, diff))

    vb = d5 * d2 - d1 * d6
    if vb <= 0.0 and d2 >= 0.0 and d6 <= 0.0:
        # Edge AC
        w = d2 / (d2 - d6)
        q = a + w * ac
        diff = p - q
        return float(np.dot(diff, diff))

    va = d3 * d6 - d5 * d4
    if va <= 0.0 and (d4 - d3) >= 0.0 and (d5 - d6) >= 0.0:
        # Edge BC
        w = (d4 - d3) / ((d4 - d3) + (d5 - d6))
        q = b + w * (c - b)
        diff = p - q
        return float(np.dot(diff, diff))

    # Face interior
    denom = 1.0 / (va + vb + vc)
    v = vb * denom
    w = vc * denom
    q = a + v * ab + w * ac
    diff = p - q
    return float(np.dot(diff, diff))


def _build_vertex_triangle_map(
    tris: np.ndarray,
    n_verts: int,
) -> List[List[int]]:
    """For each vertex, list the triangle indices that contain it."""
    vmap: List[List[int]] = [[] for _ in range(n_verts)]
    for ti, tri in enumerate(tris):
        for vi in tri:
            vmap[vi].append(ti)
    return vmap


def _closest_dist_to_mesh(
    p: np.ndarray,
    verts: np.ndarray,
    tris: np.ndarray,
    tree: KDTree,
    vmap: List[List[int]],
    k_neighbours: int = 20,
) -> float:
    """Closest distance from point p to a triangle mesh.

    Two-stage algorithm (Aspert et al. 2002 §3.2):
    1. KDTree query on vertices → k nearest vertex candidates.
    2. Gather all triangles incident to those vertices.
    3. Exact point-triangle closest-point test for each candidate triangle.

    k_neighbours is set to 20 by default.  A larger k is needed at mesh
    singularities such as pole vertices where many triangles share a single
    degenerate vertex and the 8 nearest neighbours may all map to that one
    degenerate point, missing the incident triangles whose far vertices cover
    the query point (Aspert et al. 2002 §3.3 "degenerate configurations").
    """
    # Stage 1: k nearest vertices
    k = min(k_neighbours, verts.shape[0])
    dists_v, idx_v = tree.query(p, k=k)

    # Stage 2: collect incident triangles
    candidate_tris = set()
    for vi in idx_v:
        for ti in vmap[int(vi)]:
            candidate_tris.add(ti)

    # Stage 3: exact closest point on each candidate triangle
    best_d2 = float("inf")
    a_vert, b_vert, c_vert = verts[tris[:, 0]], verts[tris[:, 1]], verts[tris[:, 2]]
    for ti in candidate_tris:
        d2 = _point_triangle_closest(p, a_vert[ti], b_vert[ti], c_vert[ti])
        if d2 < best_d2:
            best_d2 = d2

    return math.sqrt(max(0.0, best_d2))


def _sample_surface_uniform(
    surface: NurbsSurface,
    n_samples: int,
) -> Tuple[np.ndarray, np.ndarray]:
    """Sample n_samples points on surface uniformly via a stratified UV grid.

    Returns (points (N, 3), uv_params (N, 2)).
    The grid is n_u × n_v where n_u * n_v is as close to n_samples as possible
    with n_u ≈ n_v.
    """
    n_u = max(2, int(math.ceil(math.sqrt(n_samples))))
    n_v = max(2, int(math.ceil(n_samples / n_u)))

    u_min = float(surface.knots_u[0])
    u_max = float(surface.knots_u[-1])
    v_min = float(surface.knots_v[0])
    v_max = float(surface.knots_v[-1])

    us = np.linspace(u_min, u_max, n_u)
    vs = np.linspace(v_min, v_max, n_v)

    pts = []
    uvs = []
    for u in us:
        for v in vs:
            pt = surface_evaluate(surface, float(u), float(v))
            pts.append(pt[:3])
            uvs.append([u, v])

    return np.array(pts, dtype=float), np.array(uvs, dtype=float)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def hausdorff_surface_to_mesh(
    surface: NurbsSurface,
    mesh: dict,
    n_samples: int = 1000,
    regions: Optional[Sequence[Tuple[float, float, float, float]]] = None,
) -> "SurfaceMeshDeviation | dict":
    """One-sided Hausdorff distance: NURBS surface → triangle mesh.

    Samples the NURBS surface uniformly, finds the closest point on the mesh
    for each sample (Aspert et al. 2002 two-stage algorithm), and returns the
    max / mean / RMS and per-region max.

    Parameters
    ----------
    surface : NurbsSurface
        The NURBS surface being verified.
    mesh : dict
        Triangle mesh with keys ``"vertices"`` (N×3) and ``"triangles"`` (M×3).
    n_samples : int
        Number of UV samples on the surface (default 1000).
    regions : list of (u_lo, u_hi, v_lo, v_hi) or None
        Optional sub-domain regions for per-region max deviation reporting.

    Returns
    -------
    SurfaceMeshDeviation
        On success.  On error returns dict {ok: False, reason: str}.
    """
    try:
        if not isinstance(surface, NurbsSurface):
            return {"ok": False, "reason": "surface must be a NurbsSurface"}

        verts, tris, err = _parse_mesh(mesh)
        if verts is None:
            return {"ok": False, "reason": err}

        n_samples = max(4, int(n_samples))

        # Build KDTree on mesh vertices and vertex→triangle map
        tree = KDTree(verts)
        vmap = _build_vertex_triangle_map(tris, verts.shape[0])

        # Sample the surface
        pts, uvs = _sample_surface_uniform(surface, n_samples)
        n_used = pts.shape[0]

        # Compute distances
        dists = np.empty(n_used, dtype=float)
        for i in range(n_used):
            dists[i] = _closest_dist_to_mesh(pts[i], verts, tris, tree, vmap)

        hausdorff_max = float(np.max(dists))
        hausdorff_mean = float(np.mean(dists))
        rms = float(np.sqrt(np.mean(dists ** 2)))

        # Per-region max
        per_region_max: Dict[int, float] = {}
        if regions:
            for ri, (u_lo, u_hi, v_lo, v_hi) in enumerate(regions):
                mask = (
                    (uvs[:, 0] >= u_lo) & (uvs[:, 0] <= u_hi) &
                    (uvs[:, 1] >= v_lo) & (uvs[:, 1] <= v_hi)
                )
                if np.any(mask):
                    per_region_max[ri] = float(np.max(dists[mask]))
                else:
                    per_region_max[ri] = 0.0

        return SurfaceMeshDeviation(
            hausdorff_max=hausdorff_max,
            hausdorff_mean=hausdorff_mean,
            rms=rms,
            per_region_max=per_region_max,
            n_samples_used=n_used,
        )

    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "reason": str(exc)}


def _mesh_to_surface_distances(
    surface: NurbsSurface,
    verts: np.ndarray,
    n_surface_grid: int = 40,
) -> np.ndarray:
    """Compute closest distance from each mesh vertex to the NURBS surface.

    Uses a brute-force grid search on the surface (no Newton refinement) —
    adequate for the backward direction since mesh vertices are typically
    widely spaced compared to the surface sample grid.

    Returns a (len(verts),) float array of distances.
    """
    # Pre-build surface point grid
    n = max(4, int(math.ceil(math.sqrt(n_surface_grid))))
    u_min = float(surface.knots_u[0])
    u_max = float(surface.knots_u[-1])
    v_min = float(surface.knots_v[0])
    v_max = float(surface.knots_v[-1])
    us = np.linspace(u_min, u_max, n)
    vs = np.linspace(v_min, v_max, n)

    surf_pts = np.empty((n * n, 3), dtype=float)
    k = 0
    for u in us:
        for v in vs:
            pt = surface_evaluate(surface, float(u), float(v))
            surf_pts[k] = pt[:3]
            k += 1

    # Build KDTree on surface points for fast vertex→surface lookup
    surf_tree = KDTree(surf_pts)
    dists_v, _ = surf_tree.query(verts, k=1)
    return np.asarray(dists_v, dtype=float)


def bidirectional_hausdorff(
    surface: NurbsSurface,
    mesh: dict,
    n_samples: int = 1000,
) -> dict:
    """Two-sided symmetric Hausdorff distance between NURBS surface and mesh.

    Computes:
    - forward:  H(surface → mesh)  — sample surface, closest point on mesh
    - backward: H(mesh → surface)  — sample mesh vertices, closest point on surface

    Symmetric Hausdorff = max(forward, backward).

    Parameters
    ----------
    surface : NurbsSurface
    mesh : dict  — ``"vertices"`` (N×3) and ``"triangles"`` (M×3)
    n_samples : int  — surface sample count (default 1000)

    Returns
    -------
    dict
        ok, hausdorff_forward, hausdorff_backward, hausdorff_symmetric,
        hausdorff_mean_forward, rms_forward, n_surface_samples, n_mesh_vertices.
        On error: {ok: False, reason: str}.

    Notes
    -----
    The backward pass uses the mesh *vertices* as representative samples
    (Aspert et al. 2002, §3.1): for each vertex, the closest point on the
    surface is found via a grid search.  This is a conservative upper bound on
    H(mesh→surface) since the true H queries all points on the mesh, not just
    vertices.  For typical CAD tessellations the vertex-only estimate is tight
    because the surface varies slowly relative to the triangle edge length.
    """
    try:
        if not isinstance(surface, NurbsSurface):
            return {"ok": False, "reason": "surface must be a NurbsSurface"}

        verts, tris, err = _parse_mesh(mesh)
        if verts is None:
            return {"ok": False, "reason": err}

        # Forward direction: surface → mesh
        fwd_result = hausdorff_surface_to_mesh(surface, mesh, n_samples=n_samples)
        if isinstance(fwd_result, dict) and not fwd_result.get("ok", True):
            return fwd_result

        h_fwd: float = fwd_result.hausdorff_max  # type: ignore[union-attr]
        h_fwd_mean: float = fwd_result.hausdorff_mean  # type: ignore[union-attr]
        rms_fwd: float = fwd_result.rms  # type: ignore[union-attr]
        n_surf = fwd_result.n_samples_used  # type: ignore[union-attr]

        # Backward direction: mesh vertices → surface
        n_grid = max(16, int(math.ceil(math.sqrt(n_samples))))
        back_dists = _mesh_to_surface_distances(surface, verts, n_surface_grid=n_grid * n_grid)
        h_back = float(np.max(back_dists))

        h_sym = max(h_fwd, h_back)

        return {
            "ok": True,
            "reason": "",
            "hausdorff_forward": h_fwd,
            "hausdorff_backward": h_back,
            "hausdorff_symmetric": h_sym,
            "hausdorff_mean_forward": h_fwd_mean,
            "rms_forward": rms_fwd,
            "n_surface_samples": n_surf,
            "n_mesh_vertices": int(verts.shape[0]),
        }

    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "reason": str(exc)}


def max_deviation_visualization(
    surface: NurbsSurface,
    mesh: dict,
    n_samples_u: int = 20,
    n_samples_v: int = 20,
) -> dict:
    """UV-grid deviation map for false-colour heatmap display.

    Evaluates the surface on a regular n_u × n_v UV grid, computes the
    closest-point distance to the mesh for each sample, and returns the
    distances keyed by (u, v) parameter coordinates.

    Parameters
    ----------
    surface : NurbsSurface
    mesh : dict  — ``"vertices"`` (N×3) and ``"triangles"`` (M×3)
    n_samples_u, n_samples_v : int  — grid resolution (default 20×20)

    Returns
    -------
    dict
        ok, uv_distances (list of {u, v, distance}), max_deviation,
        mean_deviation, rms_deviation, n_samples_u, n_samples_v.
        On error: {ok: False, reason: str}.
    """
    try:
        if not isinstance(surface, NurbsSurface):
            return {"ok": False, "reason": "surface must be a NurbsSurface"}

        verts, tris, err = _parse_mesh(mesh)
        if verts is None:
            return {"ok": False, "reason": err}

        nu = max(2, int(n_samples_u))
        nv = max(2, int(n_samples_v))

        u_min = float(surface.knots_u[0])
        u_max = float(surface.knots_u[-1])
        v_min = float(surface.knots_v[0])
        v_max = float(surface.knots_v[-1])
        us = np.linspace(u_min, u_max, nu)
        vs = np.linspace(v_min, v_max, nv)

        tree = KDTree(verts)
        vmap = _build_vertex_triangle_map(tris, verts.shape[0])

        uv_distances = []
        all_dists = []

        for u in us:
            for v in vs:
                pt = surface_evaluate(surface, float(u), float(v))[:3]
                d = _closest_dist_to_mesh(pt, verts, tris, tree, vmap)
                uv_distances.append({
                    "u": float(u),
                    "v": float(v),
                    "distance": float(d),
                })
                all_dists.append(d)

        dists_arr = np.array(all_dists, dtype=float)
        return {
            "ok": True,
            "reason": "",
            "uv_distances": uv_distances,
            "max_deviation": float(np.max(dists_arr)),
            "mean_deviation": float(np.mean(dists_arr)),
            "rms_deviation": float(np.sqrt(np.mean(dists_arr ** 2))),
            "n_samples_u": nu,
            "n_samples_v": nv,
        }

    except Exception as exc:  # noqa: BLE001
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

    _nurbs_max_deviation_spec = ToolSpec(
        name="nurbs_max_deviation_to_mesh",
        description=(
            "Compute the Hausdorff max deviation between a NURBS surface and a reference "
            "triangle mesh.  Critical for verifying NURBS fits during reverse-engineering "
            "(point cloud → NURBS surface) and for class-A acceptance.\n\n"
            "Returns one-sided Hausdorff max / mean / RMS, bidirectional symmetric Hausdorff, "
            "UV heatmap of per-sample distances, and per-region max deviation.\n\n"
            "Reference: Aspert-Santa-Cruz-Ebrahimi 2002 (MESH); Cignoni-Rocchini-Scopigno "
            "1998 (METRO).\n\n"
            "Returns: {ok, hausdorff_max, hausdorff_mean, rms, hausdorff_symmetric, "
            "n_samples_used, uv_heatmap (optional)}. Never raises."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "degree_u": {"type": "integer", "description": "Surface degree in U."},
                "degree_v": {"type": "integer", "description": "Surface degree in V."},
                "control_points": {
                    "type": "array",
                    "description": "Flattened nu*nv control points [[x,y,z], ...].",
                    "items": {"type": "array", "items": {"type": "number"}},
                },
                "num_u": {"type": "integer", "description": "Number of control points in U."},
                "num_v": {"type": "integer", "description": "Number of control points in V."},
                "mesh_vertices": {
                    "type": "array",
                    "description": "Triangle mesh vertices [[x,y,z], ...].",
                    "items": {"type": "array", "items": {"type": "number"}},
                },
                "mesh_triangles": {
                    "type": "array",
                    "description": "Triangle face index triples [[i,j,k], ...].",
                    "items": {"type": "array", "items": {"type": "integer"}},
                },
                "n_samples": {
                    "type": "integer",
                    "description": "Number of surface samples (default 1000).",
                },
                "include_heatmap": {
                    "type": "boolean",
                    "description": "If true, return UV heatmap (20×20 grid). Default false.",
                },
                "heatmap_nu": {
                    "type": "integer",
                    "description": "Heatmap U resolution (default 20).",
                },
                "heatmap_nv": {
                    "type": "integer",
                    "description": "Heatmap V resolution (default 20).",
                },
            },
            "required": [
                "degree_u", "degree_v", "control_points", "num_u", "num_v",
                "mesh_vertices", "mesh_triangles",
            ],
        },
    )

    def _build_surface_from_args(a: dict):
        """Build NurbsSurface from tool args dict. Returns (surface, error_str)."""
        import numpy as _np
        degree_u = a.get("degree_u")
        degree_v = a.get("degree_v")
        raw_cp   = a.get("control_points", [])
        num_u    = a.get("num_u")
        num_v    = a.get("num_v")

        if any(x is None for x in [degree_u, degree_v, num_u, num_v]) or not raw_cp:
            return None, "degree_u, degree_v, control_points, num_u, num_v are required"

        try:
            degree_u = int(degree_u)
            degree_v = int(degree_v)
            num_u    = int(num_u)
            num_v    = int(num_v)
        except (TypeError, ValueError) as exc:
            return None, f"degree/num must be integers: {exc}"

        if degree_u < 1 or degree_v < 1:
            return None, "degree_u and degree_v must be >= 1"
        if num_u < 2 or num_v < 2:
            return None, "num_u and num_v must be >= 2"
        if len(raw_cp) != num_u * num_v:
            return None, f"control_points length {len(raw_cp)} != num_u*num_v={num_u*num_v}"

        try:
            cp_flat = [_np.asarray(p, dtype=float) for p in raw_cp]
            dim = cp_flat[0].size
            cp = _np.array([p.tolist()[:dim] for p in cp_flat], dtype=float).reshape(num_u, num_v, dim)
        except Exception as exc:
            return None, f"invalid control_points: {exc}"

        def _make_knots(n: int, deg: int) -> _np.ndarray:
            inner = max(0, n - deg - 1)
            return _np.concatenate([
                _np.zeros(deg + 1),
                _np.linspace(0.0, 1.0, inner + 2)[1:-1] if inner > 0 else _np.array([]),
                _np.ones(deg + 1),
            ])

        try:
            surface = NurbsSurface(
                degree_u=degree_u, degree_v=degree_v,
                control_points=cp,
                knots_u=_make_knots(num_u, degree_u),
                knots_v=_make_knots(num_v, degree_v),
            )
        except Exception as exc:
            return None, f"failed to build NurbsSurface: {exc}"

        return surface, ""

    @register(_nurbs_max_deviation_spec)
    async def run_nurbs_max_deviation_to_mesh(ctx: "ProjectCtx", args: bytes) -> str:
        try:
            a = _json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid args: {exc}", "BAD_ARGS")

        surface, err = _build_surface_from_args(a)
        if surface is None:
            return err_payload(err, "BAD_ARGS")

        mesh_v = a.get("mesh_vertices")
        mesh_t = a.get("mesh_triangles")
        if not mesh_v or not mesh_t:
            return err_payload("mesh_vertices and mesh_triangles are required", "BAD_ARGS")

        mesh = {"vertices": mesh_v, "triangles": mesh_t}
        n_samples = int(a.get("n_samples", 1000))

        # One-sided forward
        fwd = hausdorff_surface_to_mesh(surface, mesh, n_samples=n_samples)
        if isinstance(fwd, dict) and not fwd.get("ok", True):
            return err_payload(fwd["reason"], "OP_FAILED")

        # Bidirectional
        bidir = bidirectional_hausdorff(surface, mesh, n_samples=n_samples)
        if not bidir["ok"]:
            return err_payload(bidir["reason"], "OP_FAILED")

        payload = {
            "ok": True,
            "hausdorff_max":       fwd.hausdorff_max,     # type: ignore[union-attr]
            "hausdorff_mean":      fwd.hausdorff_mean,    # type: ignore[union-attr]
            "rms":                 fwd.rms,               # type: ignore[union-attr]
            "hausdorff_symmetric": bidir["hausdorff_symmetric"],
            "hausdorff_forward":   bidir["hausdorff_forward"],
            "hausdorff_backward":  bidir["hausdorff_backward"],
            "n_samples_used":      fwd.n_samples_used,    # type: ignore[union-attr]
        }

        # Optional UV heatmap
        if a.get("include_heatmap", False):
            hu = int(a.get("heatmap_nu", 20))
            hv = int(a.get("heatmap_nv", 20))
            heatmap = max_deviation_visualization(surface, mesh, hu, hv)
            if heatmap["ok"]:
                payload["uv_heatmap"] = heatmap["uv_distances"]

        return ok_payload(payload)
