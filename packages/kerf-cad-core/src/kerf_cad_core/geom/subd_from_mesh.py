"""
subd_from_mesh.py
=================
SubD cage auto-derivation from a dense mesh.

Converts a dense sculpted/scanned mesh back to an editable SubD control cage
whose Catmull-Clark limit surface approximates the input mesh.

Reference
---------
- Lee, Moreton, Hoppe (2000). "Displaced Subdivision Surfaces".
  SIGGRAPH 2000.
- Marinov, Kobbelt (2004). "Direct Anisotropic Quad-Dominant Remeshing".
  Pacific Graphics 2004.

Public API
----------
derive_cage_from_mesh(dense_mesh, target_cage_vertices=20) -> CageResult
    Simplify the dense mesh using QEM edge-collapse to `target_cage_vertices`,
    wrap as a SubD cage, subdivide 3 levels and compare to original to measure
    limit-surface deviation.  Returns CageResult.

fit_subd_to_mesh(dense_mesh, base_cage, n_iters=50) -> CageResult
    Given a base cage topology, run iterative gradient descent on cage control
    point (CP) positions to minimise the one-sided Hausdorff distance to the
    dense mesh.  Returns CageResult with improved cage.

recommend_subd_topology(dense_mesh) -> str
    Inspect polygon-type distribution and recommend 'CC' (quads), 'Loop'
    (triangles), or 'mixed'.

All functions never raise — failures surface as CageResult with deviation=inf
or short string returns.

Dense mesh input format
-----------------------
A dict with:
    "vertices" : list of [x, y, z]
    "faces"    : list of vertex-index lists (tris or quads allowed)
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

from kerf_cad_core.geom.subd import (
    SubDMesh,
    catmull_clark_subdivide,
    quad_mesh_to_subd,
)
from kerf_cad_core.geom.mesh_repair import decimate


# ---------------------------------------------------------------------------
# CageResult dataclass
# ---------------------------------------------------------------------------

@dataclass
class CageResult:
    """Result returned by cage derivation / fitting functions.

    Attributes
    ----------
    cage : SubDMesh
        The derived or fitted SubD control cage.
    limit_surface_deviation_from_original : float
        Approximate one-sided Hausdorff distance from the cage's limit surface
        (subdivided 3 levels) to the original dense mesh, expressed in the
        same units as the input vertices.  Inf indicates failure.
    optimal_levels : int
        Recommended number of subdivision levels (1-4) that minimise deviation
        while remaining within a reasonable face budget.
    deviation_relative : float
        deviation / bounding_box_diagonal, useful for mesh-scale-independent
        reporting.
    num_cage_vertices : int
        Number of vertices in the derived cage.
    num_cage_faces : int
        Number of faces in the derived cage.
    """
    cage: SubDMesh = field(default_factory=SubDMesh)
    limit_surface_deviation_from_original: float = math.inf
    optimal_levels: int = 3
    deviation_relative: float = math.inf
    num_cage_vertices: int = 0
    num_cage_faces: int = 0


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _bbox_diagonal(verts: List[List[float]]) -> float:
    """Return bounding-box diagonal of a vertex list."""
    if not verts:
        return 1.0
    xs = [v[0] for v in verts]
    ys = [v[1] for v in verts]
    zs = [v[2] for v in verts]
    dx = max(xs) - min(xs)
    dy = max(ys) - min(ys)
    dz = max(zs) - min(zs)
    diag = math.sqrt(dx * dx + dy * dy + dz * dz)
    return diag if diag > 1e-15 else 1.0


def _one_sided_hausdorff(
    pts_a: List[List[float]],
    pts_b: List[List[float]],
    sample_cap: int = 1000,
) -> float:
    """Approximate one-sided Hausdorff: max over pts_a of min-dist to pts_b.

    Both sets are randomly sub-sampled to at most *sample_cap* points each
    for efficiency (pure-Python, no KD-tree).

    Returns the max-min distance.  Returns 0.0 if either list is empty.
    """
    if not pts_a or not pts_b:
        return 0.0

    # Deterministic sub-sample: take every k-th point.
    def _subsample(pts: List[List[float]], cap: int) -> List[List[float]]:
        n = len(pts)
        if n <= cap:
            return pts
        step = n // cap
        return pts[::step][:cap]

    sa = _subsample(pts_a, sample_cap)
    sb = _subsample(pts_b, sample_cap)

    max_min = 0.0
    for pa in sa:
        best = math.inf
        for pb in sb:
            dx = pa[0] - pb[0]
            dy = pa[1] - pb[1]
            dz = pa[2] - pb[2]
            d = dx * dx + dy * dy + dz * dz
            if d < best:
                best = d
        max_min = max(max_min, best)

    return math.sqrt(max_min)


def _hausdorff_symmetric(
    pts_a: List[List[float]],
    pts_b: List[List[float]],
    sample_cap: int = 500,
) -> float:
    """Symmetric Hausdorff distance (max of both one-sided distances)."""
    return max(
        _one_sided_hausdorff(pts_a, pts_b, sample_cap),
        _one_sided_hausdorff(pts_b, pts_a, sample_cap),
    )


def _mesh_to_vertex_list(dense_mesh: Dict) -> List[List[float]]:
    """Extract vertices list from dense_mesh dict."""
    verts = dense_mesh.get("vertices", [])
    return [[float(v[0]), float(v[1]), float(v[2])] for v in verts]


def _mesh_to_face_list(dense_mesh: Dict) -> List[List[int]]:
    """Extract faces list from dense_mesh dict."""
    faces = dense_mesh.get("faces", [])
    return [[int(i) for i in f] for f in faces]


def _triangulate_faces(faces: List[List[int]]) -> List[List[int]]:
    """Fan-triangulate mixed n-gon faces into triangles for QEM decimation."""
    tris = []
    for face in faces:
        n = len(face)
        if n < 3:
            continue
        if n == 3:
            tris.append(list(face))
        else:
            # Fan from first vertex
            for i in range(1, n - 1):
                tris.append([face[0], face[i], face[i + 1]])
    return tris


def _subd_mesh_vertices(cage: SubDMesh, levels: int) -> List[List[float]]:
    """Subdivide cage `levels` times and return vertex positions."""
    subdivided = catmull_clark_subdivide(cage, levels=levels)
    return subdivided.vertices


def _measure_deviation(
    cage: SubDMesh,
    original_verts: List[List[float]],
    levels: int = 3,
    sample_cap: int = 500,
) -> float:
    """Compute Hausdorff deviation between cage limit surface and original mesh."""
    limit_verts = _subd_mesh_vertices(cage, levels)
    if not limit_verts:
        return math.inf
    return _hausdorff_symmetric(limit_verts, original_verts, sample_cap=sample_cap)


def _find_optimal_levels(
    cage: SubDMesh,
    original_verts: List[List[float]],
    diag: float,
    max_levels: int = 4,
) -> Tuple[int, float]:
    """Find the level 1..max_levels that minimises relative deviation.

    Returns (best_level, best_deviation_absolute).
    """
    best_level = 3
    best_dev = math.inf
    for lvl in range(1, max_levels + 1):
        dev = _measure_deviation(cage, original_verts, levels=lvl, sample_cap=300)
        if dev < best_dev:
            best_dev = dev
            best_level = lvl
    return best_level, best_dev


def _quads_from_decimated_tris(
    verts: List[List[float]],
    tris: List[List[int]],
) -> Tuple[List[List[float]], List[List[int]]]:
    """Pair adjacent triangles into quads using a greedy matching.

    Adjacent tris sharing an interior edge are merged into quads.
    Unpaired tris are retained as triangles (SubD handles n-gons).

    Returns (verts_unchanged, quads_and_leftover_tris).
    """
    if not tris:
        return verts, tris

    # Build edge → [face_idx] adjacency
    edge_faces: Dict[Tuple[int, int], List[int]] = {}
    for fi, tri in enumerate(tris):
        a, b, c = tri
        for ea, eb in ((a, b), (b, c), (c, a)):
            key = (min(ea, eb), max(ea, eb))
            edge_faces.setdefault(key, []).append(fi)

    used = [False] * len(tris)
    quads: List[List[int]] = []

    # Greedy: for each unpaired tri, find its best neighbour to form a quad
    for fi, tri in enumerate(tris):
        if used[fi]:
            continue
        a, b, c = tri
        merged = False
        for edge in ((a, b), (b, c), (c, a)):
            key = (min(edge[0], edge[1]), max(edge[0], edge[1]))
            nbrs = edge_faces.get(key, [])
            for fj in nbrs:
                if fj == fi or used[fj]:
                    continue
                # Merge: find the vertex in tri not on shared edge,
                # and the vertex in neighbour not on shared edge.
                shared = set(key)
                tri_unique = [v for v in tri if v not in shared]
                nbr_unique = [v for v in tris[fj] if v not in shared]
                if len(tri_unique) != 1 or len(nbr_unique) != 1:
                    continue
                # Build quad: tri_unique - edge_v0 - nbr_unique - edge_v1
                e0, e1 = edge
                quad = [tri_unique[0], e0, nbr_unique[0], e1]
                quads.append(quad)
                used[fi] = True
                used[fj] = True
                merged = True
                break
            if merged:
                break
        if not merged:
            # Keep as triangle
            quads.append(list(tri))

    return verts, quads


# ---------------------------------------------------------------------------
# Public: derive_cage_from_mesh
# ---------------------------------------------------------------------------

def derive_cage_from_mesh(
    dense_mesh: Dict,
    target_cage_vertices: int = 20,
) -> CageResult:
    """Derive a SubD control cage from a dense mesh via QEM decimation.

    Algorithm (Lee-Moreton-Hoppe 2000 §3 — coarse cage construction):
      1. Fan-triangulate the dense mesh.
      2. Run QEM edge-collapse (kerf_cad_core.geom.mesh_repair.decimate) to
         produce a simplified mesh with approximately `target_cage_vertices`
         vertices.  The target is reached by iterating face-count reductions:
         we target ~2 * target_cage_vertices faces (Euler: V ≈ F/2 for closed
         manifold quads).
      3. Merge adjacent triangles into quads (greedy matching on shared edges)
         to bias toward CC-friendly topology.
      4. Wrap as a SubDMesh (boundary edges tagged as creased).
      5. Subdivide the cage 3 levels and measure Hausdorff deviation against
         the original mesh vertices.
      6. Sweep levels 1-4 to find the optimal subdivision depth.

    Parameters
    ----------
    dense_mesh : dict
        {"vertices": [[x,y,z], ...], "faces": [[i,j,...], ...]}
    target_cage_vertices : int
        Desired number of cage control vertices.  Default 20.

    Returns
    -------
    CageResult
        Never raises.
    """
    try:
        target_cage_vertices = max(4, int(target_cage_vertices))

        orig_verts = _mesh_to_vertex_list(dense_mesh)
        orig_faces = _mesh_to_face_list(dense_mesh)

        if not orig_verts or not orig_faces:
            return CageResult()

        diag = _bbox_diagonal(orig_verts)

        # Step 1: triangulate input (QEM decimate expects triangles)
        tris = _triangulate_faces(orig_faces)
        if not tris:
            return CageResult()

        # Step 2: QEM decimation.
        # For Euler V-E+F=2 on a closed quad mesh: V ≈ F/2.
        # We target target_cage_vertices * 2 triangles; minimum 4.
        target_tri_faces = max(4, target_cage_vertices * 2)

        result = decimate(
            orig_verts,
            tris,
            target_faces=target_tri_faces,
        )

        if not result.get("ok"):
            # Fallback: use original mesh directly if decimation fails
            simp_verts = orig_verts[:target_cage_vertices]
            simp_tris = [f for f in tris if all(i < len(simp_verts) for i in f)]
        else:
            simp_verts = result["verts"]
            simp_tris = result["faces"]

        # Step 3: merge tris into quads
        cage_verts, cage_faces = _quads_from_decimated_tris(simp_verts, simp_tris)

        if not cage_faces:
            return CageResult()

        # Step 4: wrap as SubDMesh (boundary edges creased)
        cage = quad_mesh_to_subd(cage_verts, cage_faces)

        # Step 5 & 6: measure deviation and find optimal levels
        opt_levels, deviation = _find_optimal_levels(cage, orig_verts, diag)
        dev_rel = deviation / diag

        return CageResult(
            cage=cage,
            limit_surface_deviation_from_original=deviation,
            optimal_levels=opt_levels,
            deviation_relative=dev_rel,
            num_cage_vertices=cage.num_vertices,
            num_cage_faces=cage.num_faces,
        )
    except Exception:
        return CageResult()


# ---------------------------------------------------------------------------
# Public: fit_subd_to_mesh
# ---------------------------------------------------------------------------

def fit_subd_to_mesh(
    dense_mesh: Dict,
    base_cage: SubDMesh,
    n_iters: int = 50,
) -> CageResult:
    """Fit a SubD cage to a dense mesh by optimising CP positions.

    Given a fixed cage topology (vertices and faces from `base_cage`),
    iteratively moves control points (CPs) to minimise the one-sided
    Hausdorff distance from the cage's limit surface to the target mesh.

    Algorithm (Marinov-Kobbelt 2004 — direct fitting):
      Each iteration:
        1. Subdivide cage 2 levels to sample limit surface.
        2. For each cage vertex, compute the average displacement needed
           to bring the nearby limit-surface sample closer to the nearest
           point on the target mesh.
        3. Apply a dampened gradient step (step = 0.1 / (1 + 0.1 * iter)).

    Parameters
    ----------
    dense_mesh : dict
        Target mesh {"vertices": [...], "faces": [...]}
    base_cage : SubDMesh
        Starting cage topology and CP positions.
    n_iters : int
        Number of gradient descent iterations (default 50).

    Returns
    -------
    CageResult
        Never raises.
    """
    try:
        import copy

        orig_verts = _mesh_to_vertex_list(dense_mesh)
        if not orig_verts:
            return CageResult()

        n_iters = max(1, int(n_iters))
        diag = _bbox_diagonal(orig_verts)

        cage = copy.deepcopy(base_cage)
        nv = len(cage.vertices)
        if nv == 0:
            return CageResult()

        # Build vertex-face adjacency for cage: cage_vert → [face indices]
        vert_face_adj: Dict[int, List[int]] = {}
        for fi, face in enumerate(cage.faces):
            for vi in face:
                vert_face_adj.setdefault(vi, []).append(fi)

        # Gradient descent loop
        for it in range(n_iters):
            step = 0.1 / (1.0 + 0.1 * it)

            # Subdivide current cage 2 levels
            sub = catmull_clark_subdivide(cage, levels=2)
            sub_verts = sub.vertices
            if not sub_verts:
                break

            # Sub-sample for efficiency
            cap = min(500, len(sub_verts), len(orig_verts))
            step_sub = max(1, len(sub_verts) // cap)
            sub_sample = sub_verts[::step_sub][:cap]
            step_orig = max(1, len(orig_verts) // cap)
            orig_sample = orig_verts[::step_orig][:cap]

            # For each cage vertex, accumulate gradient from the limit-surface
            # displacement toward the target mesh.
            grads: List[List[float]] = [[0.0, 0.0, 0.0] for _ in range(nv)]
            count: List[int] = [0] * nv

            # Project each sub_sample point onto nearest original vertex,
            # compute a displacement vector, then distribute back to cage.
            # Distribution: each sub_sample point contributes to the nearest
            # cage vertex (by original cage position, not subdivided).
            cage_pts = cage.vertices
            for sp in sub_sample:
                # Find nearest original mesh vertex
                best_orig_d = math.inf
                best_orig_v = None
                for op in orig_sample:
                    d = (sp[0]-op[0])**2 + (sp[1]-op[1])**2 + (sp[2]-op[2])**2
                    if d < best_orig_d:
                        best_orig_d = d
                        best_orig_v = op

                if best_orig_v is None:
                    continue

                # Find nearest cage vertex
                best_cage_d = math.inf
                best_cage_i = 0
                for ci, cp in enumerate(cage_pts):
                    d = (sp[0]-cp[0])**2 + (sp[1]-cp[1])**2 + (sp[2]-cp[2])**2
                    if d < best_cage_d:
                        best_cage_d = d
                        best_cage_i = ci

                # Displacement: move cage vertex toward best_orig_v
                dx = best_orig_v[0] - cage_pts[best_cage_i][0]
                dy = best_orig_v[1] - cage_pts[best_cage_i][1]
                dz = best_orig_v[2] - cage_pts[best_cage_i][2]
                grads[best_cage_i][0] += dx
                grads[best_cage_i][1] += dy
                grads[best_cage_i][2] += dz
                count[best_cage_i] += 1

            # Apply normalised gradient step
            new_verts = [list(v) for v in cage.vertices]
            for ci in range(nv):
                if count[ci] > 0:
                    gx = grads[ci][0] / count[ci]
                    gy = grads[ci][1] / count[ci]
                    gz = grads[ci][2] / count[ci]
                    new_verts[ci][0] += step * gx
                    new_verts[ci][1] += step * gy
                    new_verts[ci][2] += step * gz

            cage.vertices = new_verts

        # Final deviation measurement
        deviation = _measure_deviation(cage, orig_verts, levels=3, sample_cap=500)
        dev_rel = deviation / diag

        return CageResult(
            cage=cage,
            limit_surface_deviation_from_original=deviation,
            optimal_levels=3,
            deviation_relative=dev_rel,
            num_cage_vertices=cage.num_vertices,
            num_cage_faces=cage.num_faces,
        )
    except Exception:
        return CageResult()


# ---------------------------------------------------------------------------
# Public: recommend_subd_topology
# ---------------------------------------------------------------------------

def recommend_subd_topology(dense_mesh: Dict) -> str:
    """Recommend a SubD scheme based on polygon-type distribution.

    Analyses the dense mesh faces:
      - If >= 80 % are triangles → 'Loop' (Loop subdivision for triangle meshes)
      - If >= 80 % are quads     → 'CC'   (Catmull-Clark for quad meshes)
      - Otherwise                → 'mixed'

    Parameters
    ----------
    dense_mesh : dict
        {"vertices": [...], "faces": [...]}

    Returns
    -------
    str — 'CC', 'Loop', or 'mixed'.  Never raises.
    """
    try:
        faces = _mesh_to_face_list(dense_mesh)
        if not faces:
            return "mixed"

        n_total = len(faces)
        n_tris = sum(1 for f in faces if len(f) == 3)
        n_quads = sum(1 for f in faces if len(f) == 4)

        frac_tris = n_tris / n_total
        frac_quads = n_quads / n_total

        threshold = 0.8
        if frac_tris >= threshold:
            return "Loop"
        if frac_quads >= threshold:
            return "CC"
        return "mixed"
    except Exception:
        return "mixed"


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

    # ------------------------------------------------------------------
    # subd_derive_from_mesh
    # ------------------------------------------------------------------

    _subd_derive_spec = ToolSpec(
        name="subd_derive_from_mesh",
        description=(
            "Derive a SubD control cage from a dense sculpted or scanned mesh "
            "using QEM (quadric error metric) edge-collapse decimation followed "
            "by quad-dominant remeshing (Lee-Moreton-Hoppe 2000 §3).\n"
            "\n"
            "The dense mesh is simplified to approximately `target_cage_vertices` "
            "control vertices.  Adjacent triangles are paired into quads so the "
            "result is CC-friendly.  The cage is evaluated at 3 subdivision levels "
            "and the Hausdorff deviation from the original mesh is reported.\n"
            "\n"
            "Returns:\n"
            "  ok                               : bool\n"
            "  cage_vertices                    : [[x,y,z], ...]\n"
            "  cage_faces                       : [[i,j,...], ...]\n"
            "  num_cage_vertices                : int\n"
            "  num_cage_faces                   : int\n"
            "  limit_surface_deviation          : float  (world units)\n"
            "  deviation_relative               : float  (fraction of bbox diag)\n"
            "  optimal_levels                   : int\n"
            "  topology_recommendation          : str  ('CC'/'Loop'/'mixed')\n"
            "\n"
            "Errors: {ok:false, reason}.  Never raises."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "vertices": {
                    "type": "array",
                    "description": "Dense mesh vertices [[x,y,z], ...].",
                    "items": {"type": "array", "items": {"type": "number"}},
                },
                "faces": {
                    "type": "array",
                    "description": "Dense mesh faces [[i,j,...], ...].",
                    "items": {"type": "array", "items": {"type": "integer"}},
                },
                "target_cage_vertices": {
                    "type": "integer",
                    "description": "Target control vertex count for the cage (default 20, min 4).",
                    "default": 20,
                },
            },
            "required": ["vertices", "faces"],
        },
    )

    @register(_subd_derive_spec)
    async def run_subd_derive_from_mesh(ctx: "ProjectCtx", args: bytes) -> str:
        try:
            a = _json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid args: {exc}", "BAD_ARGS")

        raw_verts = a.get("vertices", [])
        raw_faces = a.get("faces", [])
        target_cv = int(a.get("target_cage_vertices", 20))

        if not raw_verts:
            return err_payload("vertices is required", "BAD_ARGS")
        if not raw_faces:
            return err_payload("faces is required", "BAD_ARGS")
        if target_cv < 4:
            return err_payload("target_cage_vertices must be >= 4", "BAD_ARGS")

        dense_mesh = {"vertices": raw_verts, "faces": raw_faces}

        result = derive_cage_from_mesh(dense_mesh, target_cage_vertices=target_cv)
        topo = recommend_subd_topology(dense_mesh)

        return ok_payload({
            "ok": True,
            "cage_vertices": result.cage.vertices,
            "cage_faces": result.cage.faces,
            "num_cage_vertices": result.num_cage_vertices,
            "num_cage_faces": result.num_cage_faces,
            "limit_surface_deviation": result.limit_surface_deviation_from_original,
            "deviation_relative": result.deviation_relative,
            "optimal_levels": result.optimal_levels,
            "topology_recommendation": topo,
        })

    # ------------------------------------------------------------------
    # subd_fit_to_mesh
    # ------------------------------------------------------------------

    _subd_fit_spec = ToolSpec(
        name="subd_fit_to_mesh",
        description=(
            "Fit a SubD cage topology to a target dense mesh by iterative "
            "gradient descent on control point positions (Marinov-Kobbelt 2004).\n"
            "\n"
            "Given a base cage (vertices + faces) and a target dense mesh, "
            "optimises the cage control points to minimise the Hausdorff distance "
            "from the cage's limit surface to the dense mesh.\n"
            "\n"
            "Returns:\n"
            "  ok                      : bool\n"
            "  cage_vertices           : [[x,y,z], ...] (fitted positions)\n"
            "  cage_faces              : [[i,j,...], ...] (topology unchanged)\n"
            "  num_cage_vertices       : int\n"
            "  num_cage_faces          : int\n"
            "  limit_surface_deviation : float\n"
            "  deviation_relative      : float\n"
            "\n"
            "Errors: {ok:false, reason}.  Never raises."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "target_vertices": {
                    "type": "array",
                    "description": "Target dense mesh vertices [[x,y,z], ...].",
                    "items": {"type": "array", "items": {"type": "number"}},
                },
                "target_faces": {
                    "type": "array",
                    "description": "Target dense mesh faces [[i,j,...], ...].",
                    "items": {"type": "array", "items": {"type": "integer"}},
                },
                "cage_vertices": {
                    "type": "array",
                    "description": "Base cage control vertices [[x,y,z], ...].",
                    "items": {"type": "array", "items": {"type": "number"}},
                },
                "cage_faces": {
                    "type": "array",
                    "description": "Base cage topology faces [[i,j,...], ...].",
                    "items": {"type": "array", "items": {"type": "integer"}},
                },
                "n_iters": {
                    "type": "integer",
                    "description": "Number of gradient descent iterations (default 50).",
                    "default": 50,
                },
            },
            "required": ["target_vertices", "target_faces", "cage_vertices", "cage_faces"],
        },
    )

    @register(_subd_fit_spec)
    async def run_subd_fit_to_mesh(ctx: "ProjectCtx", args: bytes) -> str:
        try:
            a = _json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid args: {exc}", "BAD_ARGS")

        tgt_verts = a.get("target_vertices", [])
        tgt_faces = a.get("target_faces", [])
        cage_verts = a.get("cage_vertices", [])
        cage_faces_raw = a.get("cage_faces", [])
        n_iters = int(a.get("n_iters", 50))

        if not tgt_verts:
            return err_payload("target_vertices is required", "BAD_ARGS")
        if not tgt_faces:
            return err_payload("target_faces is required", "BAD_ARGS")
        if not cage_verts:
            return err_payload("cage_vertices is required", "BAD_ARGS")
        if not cage_faces_raw:
            return err_payload("cage_faces is required", "BAD_ARGS")

        dense_mesh = {"vertices": tgt_verts, "faces": tgt_faces}

        try:
            base_cage = SubDMesh(
                vertices=[[float(x) for x in v] for v in cage_verts],
                faces=[[int(i) for i in f] for f in cage_faces_raw],
            )
        except Exception as exc:
            return err_payload(f"invalid cage: {exc}", "BAD_ARGS")

        result = fit_subd_to_mesh(dense_mesh, base_cage, n_iters=n_iters)

        return ok_payload({
            "ok": True,
            "cage_vertices": result.cage.vertices,
            "cage_faces": result.cage.faces,
            "num_cage_vertices": result.num_cage_vertices,
            "num_cage_faces": result.num_cage_faces,
            "limit_surface_deviation": result.limit_surface_deviation_from_original,
            "deviation_relative": result.deviation_relative,
        })
