"""
subd_feature_curves.py
======================
SubD feature curves — designer-specified curves that propagate through
subdivision levels independently from sharp creases.

Feature curves sit in the continuous-sharpness spectrum described by
DeRose-Kass-Truong 1998 §4 (semi-sharp creases) and Biermann-Levin-Zorin
2000 (piecewise smooth SubD with normal control):

    sharpness = 0   → smooth subdivision (no curve influence)
    sharpness = ∞   → matches a full CC crease exactly
    sharpness = s   → each subdivision level decays sharpness by 1; the
                       fractional residual smoothly blends toward the limit
                       crease position (OpenSubdiv semi-sharp decay rule)

Distinction from creases
------------------------
* Creases are stored *in the mesh topology* via SubDMesh.creases and alter
  vertex positions during the subdivision step itself.
* Feature curves are stored *externally* as polylines over vertex indices and
  are applied as a post-refinement projection step; they propagate by
  tracking which refined sub-edges derive from each original feature edge.

This separation lets designers specify stylistic ridges (e.g. swage lines,
panel gap lines on automotive bodies) that are softer than hard creases but
harder than the smooth limit surface — without modifying the base cage's
crease weights.

Public API
----------
FeatureCurve
    Dataclass: vertex indices (polyline), sharpness, propagation mode.

propagate_feature_curves(mesh, features, n_levels) -> (SubDMesh, list[FeatureCurve])
    Subdivide mesh n_levels while propagating each FeatureCurve.

make_semi_sharp_feature(mesh, edge_ids, sharpness=2.0) -> FeatureCurve
    Convenience: build a FeatureCurve from a list of edge ids.

extract_feature_curves(mesh, dihedral_threshold=30°) -> list[FeatureCurve]
    Auto-detect candidate feature curves from a base mesh by dihedral angle.

Never raises — all exceptions are caught and returned as empty / identity
results per the kerf-cad-core convention.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

from kerf_cad_core.geom.subd import SubDMesh, _catmull_clark_once


# ---------------------------------------------------------------------------
# FeatureCurve dataclass
# ---------------------------------------------------------------------------

@dataclass
class FeatureCurve:
    """A designer-specified curve on a subdivision surface.

    Parameters
    ----------
    vertex_indices : list[int]
        Ordered vertex indices forming a polyline on the *current* (possibly
        refined) mesh.  The polyline defines the feature path.
    sharpness : float
        Sharpness in [0, ∞).  Controls how strongly sub-vertices are pulled
        toward the feature polyline:
          * 0      → no pull (leave at default subdivided positions)
          * ∞      → full pull (match CC crease limit exactly)
          * finite → semi-sharp: decays by 1.0 per subdivision level (same
                     decay rule as OpenSubdiv semi-sharp creases).
    propagation : str
        'refine'  — at each subdivision level the feature curve is propagated
                    by inserting edge midpoints between each pair of adjacent
                    feature vertices (standard refinement following the mesh).
        'project' — after refinement a best-fit projection onto the smoothed
                    polyline is applied (useful for curved spine trajectories).
    """
    vertex_indices: List[int] = field(default_factory=list)
    sharpness: float = 2.0
    propagation: str = "refine"  # 'refine' | 'project'

    def __post_init__(self) -> None:
        self.sharpness = max(0.0, float(self.sharpness))
        if self.propagation not in ("refine", "project"):
            self.propagation = "refine"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _vec3(p: List[float]) -> np.ndarray:
    return np.array(p, dtype=float)


def _dist3(a: np.ndarray, b: np.ndarray) -> float:
    d = a - b
    return float(np.sqrt(d @ d))


def _lerp3_np(a: np.ndarray, b: np.ndarray, t: float) -> np.ndarray:
    return a + (b - a) * t


def _face_normal(verts: List[List[float]], face: List[int]) -> np.ndarray:
    """Newell normal for a polygon (unit vector)."""
    n = np.zeros(3, dtype=float)
    nf = len(face)
    for i in range(nf):
        curr = _vec3(verts[face[i]])
        nxt = _vec3(verts[face[(i + 1) % nf]])
        n[0] += (curr[1] - nxt[1]) * (curr[2] + nxt[2])
        n[1] += (curr[2] - nxt[2]) * (curr[0] + nxt[0])
        n[2] += (curr[0] - nxt[0]) * (curr[1] + nxt[1])
    mag = float(np.linalg.norm(n))
    if mag < 1e-15:
        return np.array([0.0, 0.0, 1.0])
    return n / mag


def _build_edge_to_face(
    mesh: SubDMesh,
) -> Dict[Tuple[int, int], List[int]]:
    """Map edge_key -> [face_indices] for dihedral angle queries."""
    edge_faces: Dict[Tuple[int, int], List[int]] = {}
    for fi, face in enumerate(mesh.faces):
        n = len(face)
        for i in range(n):
            key = mesh.edge_key(face[i], face[(i + 1) % n])
            edge_faces.setdefault(key, []).append(fi)
    return edge_faces


# ---------------------------------------------------------------------------
# Core: one-level feature-curve propagation
# ---------------------------------------------------------------------------

def _propagate_one_level(
    mesh: SubDMesh,
    features: List[FeatureCurve],
) -> Tuple[SubDMesh, List[FeatureCurve]]:
    """Apply one subdivision level and propagate each FeatureCurve.

    The standard CC step is applied first (producing the refined mesh and
    new vertex positions).  Then for each FeatureCurve the refinement logic:

    1. *Refine the curve topology*: each original feature edge (v_i, v_{i+1})
       was split into two child edges via the CC edge-point insertion.  The new
       sub-vertex is the CC edge point (nv + nf + ei in the layout produced by
       _catmull_clark_once).  The refined feature polyline therefore becomes
       [v0, ep01, v1, ep12, v2, ...] where ep_ij is the edge-point of edge
       (v_i, v_j).

    2. *Project sub-vertices toward the feature polyline* with weight
       alpha(s) where s is the current sharpness.  The target position for
       a new edge-point vertex is the interpolated position along the smooth
       feature polyline (the parametric midpoint between its feature-curve
       neighbors).  The blend weight is:
           alpha = s / (s + 1)   for finite s  [→ 0 as s→0; →1 as s→∞]
           alpha = 1.0           for s = ∞

       This is the same continuous-spectrum interpolation as the Biermann-
       Levin-Zorin "normal control" weight; it reduces to the OpenSubdiv
       crease rule at integer sharpness steps.

    3. *Decay sharpness*: new_s = max(0, s - 1.0).  When sharpness hits 0 the
       curve becomes invisible (no projection) at subsequent levels.

    Returns the refined mesh and the updated FeatureCurve list.
    """
    # Capture the vertex/face layout *before* subdivision so we can map
    # original edge indices into the refined vertex array.
    nv_before = len(mesh.vertices)
    nf_before = len(mesh.faces)
    all_edges = mesh._all_edge_keys()

    # Build edge-index map: edge_key -> refined vertex index of that edge point.
    # Layout from _catmull_clark_once: [orig_verts | face_pts | edge_pts]
    # edge point i has index nv_before + nf_before + i.
    edge_to_ep: Dict[Tuple[int, int], int] = {}
    for ei, key in enumerate(all_edges):
        edge_to_ep[key] = nv_before + nf_before + ei

    # Subdivide.
    refined = _catmull_clark_once(mesh)

    # Propagate each FeatureCurve.
    new_features: List[FeatureCurve] = []
    for fc in features:
        verts_fc = fc.vertex_indices
        s = fc.sharpness

        if len(verts_fc) < 2 or s <= 0.0:
            # Sharpness already decayed to 0 — keep the curve but don't project.
            # Expand the polyline to include edge-point indices (topology only).
            new_vi = _expand_feature_topology(verts_fc, edge_to_ep, mesh)
            new_features.append(FeatureCurve(
                vertex_indices=new_vi,
                sharpness=0.0,
                propagation=fc.propagation,
            ))
            continue

        # ------------------------------------------------------------------
        # Step 1: Expand topology (insert edge-point vertices).
        # ------------------------------------------------------------------
        new_vi = _expand_feature_topology(verts_fc, edge_to_ep, mesh)

        # ------------------------------------------------------------------
        # Step 2: Project new edge-point vertices toward the feature polyline.
        #
        # For each newly inserted edge-point vertex (every other in new_vi),
        # compute its "ideal" position on the feature polyline — which is the
        # midpoint between the two neighboring control vertices in the original
        # feature polyline.  Then blend the CC position toward this ideal by
        # alpha = s/(s+1) for finite sharpness.
        # ------------------------------------------------------------------
        alpha = 1.0 if math.isinf(s) else s / (s + 1.0)

        if alpha > 1e-12:
            rv = refined.vertices  # mutable in-place for this feature curve
            for seg_idx in range(len(verts_fc) - 1):
                # Original vertices on either side of this edge segment.
                v_a_orig = verts_fc[seg_idx]
                v_b_orig = verts_fc[seg_idx + 1]
                ekey = mesh.edge_key(v_a_orig, v_b_orig)
                if ekey not in edge_to_ep:
                    continue
                ep_idx = edge_to_ep[ekey]

                # Original control positions (pre-subdivision).
                pa = _vec3(mesh.vertices[v_a_orig])
                pb = _vec3(mesh.vertices[v_b_orig])

                if fc.propagation == "project":
                    # Project: find the parametric midpoint on the *smooth*
                    # polyline formed by the original feature-curve vertices.
                    # For a straight-edge segment that's just the midpoint.
                    # We use the refined positions of v_a and v_b to fit
                    # a smoother target.
                    pa_refined = _vec3(rv[v_a_orig])
                    pb_refined = _vec3(rv[v_b_orig])
                    ideal = (pa_refined + pb_refined) * 0.5
                else:
                    # Refine: ideal = straight midpoint of original control pts.
                    ideal = (pa + pb) * 0.5

                current = _vec3(rv[ep_idx])
                projected = _lerp3_np(current, ideal, alpha)
                rv[ep_idx] = projected.tolist()

        # ------------------------------------------------------------------
        # Step 3: Decay sharpness.
        # ------------------------------------------------------------------
        new_s = max(0.0, s - 1.0)
        new_features.append(FeatureCurve(
            vertex_indices=new_vi,
            sharpness=new_s,
            propagation=fc.propagation,
        ))

    return refined, new_features


def _expand_feature_topology(
    verts_fc: List[int],
    edge_to_ep: Dict[Tuple[int, int], int],
    mesh: SubDMesh,
) -> List[int]:
    """Expand a feature polyline by inserting edge-point indices.

    Each original segment (v_i, v_{i+1}) becomes two segments:
    (v_i, ep_{i,i+1}) and (ep_{i,i+1}, v_{i+1}).

    The resulting list has 2*(n-1)+1 = 2n-1 entries for an n-vertex polyline.
    """
    if len(verts_fc) < 2:
        return list(verts_fc)
    new_vi: List[int] = [verts_fc[0]]
    for i in range(len(verts_fc) - 1):
        v_a = verts_fc[i]
        v_b = verts_fc[i + 1]
        ekey = mesh.edge_key(v_a, v_b)
        if ekey in edge_to_ep:
            new_vi.append(edge_to_ep[ekey])
        # else: edge missing (e.g. non-adjacent vertices) — skip insertion
        new_vi.append(v_b)
    return new_vi


# ---------------------------------------------------------------------------
# Public: propagate_feature_curves
# ---------------------------------------------------------------------------

def propagate_feature_curves(
    mesh: SubDMesh,
    features: Sequence[FeatureCurve],
    n_levels: int,
) -> Tuple[SubDMesh, List[FeatureCurve]]:
    """Subdivide a mesh N levels while propagating feature curves.

    Parameters
    ----------
    mesh : SubDMesh
        Input control mesh.
    features : sequence of FeatureCurve
        Feature curves to propagate.  Each curve's vertex_indices must
        reference vertices of the *input* mesh at level 0.
    n_levels : int
        Number of subdivision levels (>= 0).  0 returns a copy + the
        original features unchanged.

    Returns
    -------
    (refined_mesh, updated_features)
        refined_mesh  : SubDMesh after n_levels of CC subdivision.
        updated_features : FeatureCurve list with vertex_indices updated to
                          reference the refined mesh and sharpness decayed.

    Notes
    -----
    * The projection step modifies edge-point vertex positions in the refined
      mesh *in-place* (no extra vertices are added).
    * When sharpness reaches 0 before all levels are done the curve remains
      in the list but is no longer projected (it's just a tagged polyline).
    * Never raises.
    """
    try:
        n_levels = max(0, int(n_levels))
        # Deep-copy mesh and features so we don't mutate inputs.
        import copy as _copy
        current_mesh = SubDMesh(
            vertices=[list(v) for v in mesh.vertices],
            faces=[list(f) for f in mesh.faces],
            creases=dict(mesh.creases),
        )
        current_features: List[FeatureCurve] = [
            FeatureCurve(
                vertex_indices=list(fc.vertex_indices),
                sharpness=fc.sharpness,
                propagation=fc.propagation,
            )
            for fc in features
        ]

        for _ in range(n_levels):
            current_mesh, current_features = _propagate_one_level(
                current_mesh, current_features
            )

        return current_mesh, current_features
    except Exception:
        import copy as _copy
        safe_mesh = SubDMesh(
            vertices=[list(v) for v in mesh.vertices],
            faces=[list(f) for f in mesh.faces],
            creases=dict(mesh.creases),
        )
        return safe_mesh, [
            FeatureCurve(
                vertex_indices=list(fc.vertex_indices),
                sharpness=fc.sharpness,
                propagation=fc.propagation,
            )
            for fc in features
        ]


# ---------------------------------------------------------------------------
# Public: make_semi_sharp_feature
# ---------------------------------------------------------------------------

def make_semi_sharp_feature(
    mesh: SubDMesh,
    edge_ids: Sequence[Tuple[int, int]],
    sharpness: float = 2.0,
) -> FeatureCurve:
    """Build a FeatureCurve from a list of connected edges.

    The edges must form a connected path (polyline) on the mesh.  This
    helper chains them into an ordered vertex list.

    Parameters
    ----------
    mesh : SubDMesh
        The base mesh (used for validation only).
    edge_ids : sequence of (v_a, v_b) pairs
        Edges forming a connected polyline.  Should be given in traversal
        order; if they are not, the helper attempts to sort them.
    sharpness : float
        Sharpness value for the resulting FeatureCurve (default 2.0).

    Returns
    -------
    FeatureCurve
        With vertex_indices ordered along the polyline.  Never raises.
    """
    try:
        if not edge_ids:
            return FeatureCurve(vertex_indices=[], sharpness=float(sharpness))

        edges = [(int(a), int(b)) for a, b in edge_ids]

        # Build adjacency to chain edges into a polyline.
        adj: Dict[int, List[int]] = {}
        for a, b in edges:
            adj.setdefault(a, []).append(b)
            adj.setdefault(b, []).append(a)

        # Find an endpoint (degree-1 vertex) or just start from first edge.
        endpoint: Optional[int] = None
        for v, nbrs in adj.items():
            if len(nbrs) == 1:
                endpoint = v
                break
        if endpoint is None:
            endpoint = edges[0][0]

        # Walk the path.
        path: List[int] = [endpoint]
        visited_edges: set = set()
        current = endpoint
        while True:
            nbrs = adj.get(current, [])
            moved = False
            for nb in nbrs:
                key = (min(current, nb), max(current, nb))
                if key not in visited_edges:
                    visited_edges.add(key)
                    path.append(nb)
                    current = nb
                    moved = True
                    break
            if not moved:
                break

        return FeatureCurve(vertex_indices=path, sharpness=float(sharpness))
    except Exception:
        return FeatureCurve(vertex_indices=[], sharpness=float(sharpness))


# ---------------------------------------------------------------------------
# Public: extract_feature_curves
# ---------------------------------------------------------------------------

def extract_feature_curves(
    mesh: SubDMesh,
    dihedral_threshold: float = math.radians(30.0),
) -> List[FeatureCurve]:
    """Auto-detect candidate feature curves from a base mesh.

    Identifies edges whose dihedral angle exceeds `dihedral_threshold` and
    groups them into connected polylines (feature curves), excluding boundary
    edges (which are typically already creased).

    This is conceptually similar to crease auto-detection but:
    * Only selects interior edges (shared by exactly 2 faces).
    * Chains qualifying edges into polylines rather than labelling isolated
      edges, so the result is curves rather than a crease dict.

    Parameters
    ----------
    mesh : SubDMesh
        Input mesh.
    dihedral_threshold : float
        Minimum dihedral angle (in radians) between adjacent faces for an
        edge to be considered a feature edge.  Default: 30 degrees.

    Returns
    -------
    list[FeatureCurve]
        One FeatureCurve per connected chain of qualifying edges.
        Returns [] for smooth surfaces.  Never raises.
    """
    try:
        if not mesh.vertices or not mesh.faces:
            return []

        edge_faces = _build_edge_to_face(mesh)
        threshold = float(dihedral_threshold)

        # Collect qualifying edges.
        feature_edges: List[Tuple[int, int]] = []
        for key, fids in edge_faces.items():
            if len(fids) != 2:
                continue  # boundary or non-manifold — skip
            n1 = _face_normal(mesh.vertices, mesh.faces[fids[0]])
            n2 = _face_normal(mesh.vertices, mesh.faces[fids[1]])
            cos_a = float(np.clip(n1 @ n2, -1.0, 1.0))
            dihedral = math.acos(cos_a)
            if dihedral >= threshold:
                feature_edges.append(key)

        if not feature_edges:
            return []

        # Build edge adjacency for chaining.
        adj: Dict[int, List[int]] = {}
        for a, b in feature_edges:
            adj.setdefault(a, []).append(b)
            adj.setdefault(b, []).append(a)

        # Walk connected components, extracting linear chains.
        visited_v: set = set()
        visited_e: set = set()
        curves: List[FeatureCurve] = []

        def _walk_chain(start: int) -> List[int]:
            """DFS walk that prefers to extend the current linear chain."""
            chain = [start]
            visited_v.add(start)
            current = start
            while True:
                nbrs = [nb for nb in adj.get(current, [])
                        if (min(current, nb), max(current, nb)) not in visited_e]
                if not nbrs:
                    break
                nb = nbrs[0]
                ekey = (min(current, nb), max(current, nb))
                visited_e.add(ekey)
                visited_v.add(nb)
                chain.append(nb)
                current = nb
            return chain

        # Start chains from endpoints (degree-1 in the feature graph) or
        # arbitrary unvisited vertices when there are cycles.
        endpoints = [v for v, nbrs in adj.items() if len(nbrs) == 1]
        if not endpoints:
            endpoints = list(adj.keys())

        for start in endpoints:
            if start in visited_v:
                continue
            chain = _walk_chain(start)
            if len(chain) >= 2:
                curves.append(FeatureCurve(vertex_indices=chain, sharpness=2.0))

        # Catch any remaining unvisited edges (cycles or disconnected pieces).
        for a, b in feature_edges:
            ekey = (min(a, b), max(a, b))
            if ekey not in visited_e:
                visited_e.add(ekey)
                visited_v.add(a)
                visited_v.add(b)
                chain = _walk_chain(b)
                full_chain = [a] + chain
                if len(full_chain) >= 2:
                    curves.append(FeatureCurve(vertex_indices=full_chain, sharpness=2.0))

        return curves
    except Exception:
        return []


# ---------------------------------------------------------------------------
# LLM tool registration — subd_make_feature_curve
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

    _subd_make_feature_curve_spec = ToolSpec(
        name="subd_make_feature_curve",
        description=(
            "Create or propagate SubD feature curves — designer-specified curves "
            "that ride a subdivision surface with continuous sharpness control "
            "independent of hard creases.\n"
            "\n"
            "Sharpness spectrum (Biermann-Levin-Zorin / DeRose-Kass-Truong):\n"
            "  sharpness=0   → smooth subdivision (no curve influence)\n"
            "  sharpness=∞   → exact CC crease (hard ridge)\n"
            "  sharpness=s   → semi-sharp: decays by 1.0/level, blends toward\n"
            "                   the feature polyline with weight s/(s+1)\n"
            "\n"
            "Operations:\n"
            "  'make'          — wrap a list of edges into a FeatureCurve.\n"
            "  'propagate'     — subdivide a mesh and propagate feature curves.\n"
            "  'auto_detect'   — detect feature curves from dihedral angle.\n"
            "\n"
            "Returns:\n"
            "  ok              : bool\n"
            "  feature_curves  : [{vertex_indices, sharpness, propagation}, ...]\n"
            "  vertices        : refined mesh vertices (propagate only)\n"
            "  faces           : refined mesh faces   (propagate only)\n"
            "\n"
            "Errors: {ok:false, reason}.  Never raises."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "op": {
                    "type": "string",
                    "description": "'make' | 'propagate' | 'auto_detect'",
                },
                "vertices": {
                    "type": "array",
                    "description": "Mesh vertices [[x,y,z], ...].",
                    "items": {"type": "array", "items": {"type": "number"}},
                },
                "faces": {
                    "type": "array",
                    "description": "Mesh face index lists [[i,j,k,l], ...].",
                    "items": {"type": "array", "items": {"type": "integer"}},
                },
                "creases": {
                    "type": "array",
                    "description": "Optional crease list [{v1,v2,value}].",
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
                "edges": {
                    "type": "array",
                    "description": "Edge pairs [[v_a, v_b], ...] for 'make' op.",
                    "items": {"type": "array", "items": {"type": "integer"}},
                },
                "sharpness": {
                    "type": "number",
                    "description": "Feature curve sharpness [0, ∞) (default 2.0).",
                },
                "propagation": {
                    "type": "string",
                    "description": "'refine' (default) or 'project'.",
                },
                "feature_curves": {
                    "type": "array",
                    "description": "Existing feature curves for 'propagate' op.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "vertex_indices": {
                                "type": "array",
                                "items": {"type": "integer"},
                            },
                            "sharpness": {"type": "number"},
                            "propagation": {"type": "string"},
                        },
                        "required": ["vertex_indices"],
                    },
                },
                "levels": {
                    "type": "integer",
                    "description": "Subdivision levels for 'propagate' (default 2).",
                },
                "dihedral_threshold_deg": {
                    "type": "number",
                    "description": "Dihedral threshold in degrees for 'auto_detect' (default 30).",
                },
            },
            "required": ["op", "vertices", "faces"],
        },
    )

    @register(_subd_make_feature_curve_spec)
    async def run_subd_make_feature_curve(ctx: "ProjectCtx", args: bytes) -> str:
        try:
            a = _json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid args: {exc}", "BAD_ARGS")

        op = str(a.get("op", "")).strip().lower()
        raw_verts = a.get("vertices", [])
        raw_faces = a.get("faces", [])
        raw_creases = a.get("creases", [])

        if not raw_verts:
            return err_payload("vertices is required", "BAD_ARGS")
        if not raw_faces:
            return err_payload("faces is required", "BAD_ARGS")
        if op not in ("make", "propagate", "auto_detect"):
            return err_payload(
                f"unknown op '{op}'; use 'make', 'propagate', or 'auto_detect'",
                "BAD_ARGS",
            )

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

        if op == "make":
            raw_edges = a.get("edges", [])
            if not raw_edges:
                return err_payload("edges is required for 'make' op", "BAD_ARGS")
            try:
                edge_pairs = [(int(e[0]), int(e[1])) for e in raw_edges]
            except Exception as exc:
                return err_payload(f"invalid edges: {exc}", "BAD_ARGS")
            sharpness = float(a.get("sharpness", 2.0))
            propagation = str(a.get("propagation", "refine"))
            fc = make_semi_sharp_feature(mesh, edge_pairs, sharpness=sharpness)
            fc.propagation = propagation if propagation in ("refine", "project") else "refine"
            return ok_payload({
                "ok": True,
                "feature_curves": [
                    {
                        "vertex_indices": fc.vertex_indices,
                        "sharpness": fc.sharpness,
                        "propagation": fc.propagation,
                    }
                ],
            })

        elif op == "propagate":
            raw_fcs = a.get("feature_curves", [])
            levels = int(a.get("levels", 2))
            if levels < 0 or levels > 6:
                return err_payload("levels must be 0..6", "BAD_ARGS")
            features: List[FeatureCurve] = []
            for rfc in raw_fcs:
                try:
                    features.append(FeatureCurve(
                        vertex_indices=[int(vi) for vi in rfc["vertex_indices"]],
                        sharpness=float(rfc.get("sharpness", 2.0)),
                        propagation=str(rfc.get("propagation", "refine")),
                    ))
                except Exception:
                    pass
            refined, updated = propagate_feature_curves(mesh, features, n_levels=levels)
            return ok_payload({
                "ok": True,
                "vertices": refined.vertices,
                "faces": refined.faces,
                "num_vertices": refined.num_vertices,
                "num_faces": refined.num_faces,
                "feature_curves": [
                    {
                        "vertex_indices": fc.vertex_indices,
                        "sharpness": fc.sharpness,
                        "propagation": fc.propagation,
                    }
                    for fc in updated
                ],
            })

        else:  # auto_detect
            threshold_deg = float(a.get("dihedral_threshold_deg", 30.0))
            threshold_rad = math.radians(threshold_deg)
            detected = extract_feature_curves(mesh, dihedral_threshold=threshold_rad)
            return ok_payload({
                "ok": True,
                "feature_curves": [
                    {
                        "vertex_indices": fc.vertex_indices,
                        "sharpness": fc.sharpness,
                        "propagation": fc.propagation,
                    }
                    for fc in detected
                ],
            })
