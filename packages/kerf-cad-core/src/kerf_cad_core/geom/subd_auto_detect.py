"""
subd_auto_detect.py
===================
Automatic detection and classification of sharp edges and feature curves from
an input mesh for SubD modelling.

Background
----------
When importing a mesh for SubD editing, creases and feature curves must be
tagged so the subdivision evaluator can reproduce the intended sharpness.
This module implements the Hubeli-Gross (2000) / Botsch-Kobbelt (2003)
dihedral-angle classification strategy:

  * **hard_crease** (∞ sharpness) — dihedral angle > ``hard_threshold_deg``
    (default 80°).  These become hard cage creases with sharpness = math.inf.
  * **feature_curve** (moderate crease) — dihedral angle between
    ``feature_threshold_deg`` (default 30°) and ``hard_threshold_deg``.
    These are grouped into polyline chains for smooth-but-visible ridge lines.
  * **smooth** — dihedral angle < ``feature_threshold_deg``.  No special tag.

The dihedral angle is the *supplement* of the angle between outward face
normals: 0° means the faces are coplanar (smooth), 90° is a right-angle
corner, 180° is a fold-back.  Formally::

    dihedral_deg = acos(clamp(dot(n0, n1), -1, 1)) * (180 / π)

This convention matches Rhino / Blender auto-smooth behaviour.

Public API
----------
EdgeClassification
    dataclass — classified edge lists + per-edge dihedral stats.

FeatureCurve
    dataclass — a connected polyline chain of feature / hard edges.

SubDPreprocessResult
    dataclass — classified edges + chained curves + a crease-tagged SubDMesh
    ready for the Catmull-Clark evaluator.

auto_classify_edges(mesh, hard_threshold_deg, feature_threshold_deg)
    Classify all interior edges by dihedral angle.

chain_feature_curves(mesh, feature_edges)
    Group feature edges into connected polyline chains.

auto_subd_preprocess(mesh, hard_threshold, feature_threshold)
    End-to-end pipeline: classify → chain → tag cage creases.

recommend_thresholds(mesh)
    Analyse dihedral histogram; suggest hard/feature thresholds via
    Otsu's method on the angle distribution.

Never raises — all exceptions are caught and returned as empty / identity
results.
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

from kerf_cad_core.geom.subd import SubDMesh


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class EdgeClassification:
    """Result of :func:`auto_classify_edges`.

    Attributes
    ----------
    hard_edges : list of (int, int)
        Edge vertex-index pairs whose dihedral angle > hard_threshold_deg.
        These should be tagged with sharpness=math.inf in the SubD cage.
    feature_edges : list of (int, int)
        Edge pairs in the feature-curve band (moderate sharpness).
    smooth_edges : list of (int, int)
        Remaining edges — no special tagging required.
    dihedral_angles : dict mapping (int, int) -> float
        Dihedral angle in degrees for every interior (two-face) edge.
        Boundary edges (one adjacent face) are omitted.
    boundary_edges : list of (int, int)
        Edges with exactly one adjacent face (mesh boundary).
    """
    hard_edges: List[Tuple[int, int]] = field(default_factory=list)
    feature_edges: List[Tuple[int, int]] = field(default_factory=list)
    smooth_edges: List[Tuple[int, int]] = field(default_factory=list)
    dihedral_angles: Dict[Tuple[int, int], float] = field(default_factory=dict)
    boundary_edges: List[Tuple[int, int]] = field(default_factory=list)

    # Convenience stats --------------------------------------------------------
    @property
    def dihedral_stats(self) -> Dict[str, float]:
        """Return min/max/mean/std of dihedral angles for interior edges."""
        angles = list(self.dihedral_angles.values())
        if not angles:
            return {"min": 0.0, "max": 0.0, "mean": 0.0, "std": 0.0, "count": 0}
        n = len(angles)
        mn = min(angles)
        mx = max(angles)
        mean = sum(angles) / n
        variance = sum((a - mean) ** 2 for a in angles) / n
        return {
            "min": mn,
            "max": mx,
            "mean": mean,
            "std": math.sqrt(variance),
            "count": float(n),
        }


@dataclass
class FeatureCurve:
    """A connected polyline chain of feature or hard edges.

    Attributes
    ----------
    vertex_chain : list[int]
        Ordered vertex indices forming the polyline.  Length >= 2.
    edge_pairs : list of (int, int)
        The (a, b) edge pairs in chain order.
    kind : str
        'hard_crease' or 'feature_curve'.
    is_closed : bool
        True if the chain forms a closed loop.
    """
    vertex_chain: List[int] = field(default_factory=list)
    edge_pairs: List[Tuple[int, int]] = field(default_factory=list)
    kind: str = "feature_curve"
    is_closed: bool = False

    @property
    def length(self) -> int:
        """Number of edges in the chain."""
        return len(self.edge_pairs)


@dataclass
class SubDPreprocessResult:
    """Result of :func:`auto_subd_preprocess`.

    Attributes
    ----------
    mesh : SubDMesh
        The input mesh with crease weights assigned:
          - hard edges → crease = math.inf (clamped to 1.0 by SubDMesh)
          - feature edges → crease = 0.5 (fractional, Botsch-Kobbelt §3.2)
    classification : EdgeClassification
        The edge classification produced during preprocessing.
    hard_curves : list[FeatureCurve]
        Hard-crease chains (sharpness=inf).
    feature_curves : list[FeatureCurve]
        Feature-curve chains (moderate sharpness).
    """
    mesh: SubDMesh = field(default_factory=SubDMesh)
    classification: EdgeClassification = field(default_factory=EdgeClassification)
    hard_curves: List[FeatureCurve] = field(default_factory=list)
    feature_curves: List[FeatureCurve] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Internal geometry helpers
# ---------------------------------------------------------------------------

def _face_normal(verts: List[List[float]], face: List[int]) -> Tuple[float, float, float]:
    """Return the outward face normal (not normalised for degenerate faces).

    Uses Newell's method to handle non-planar n-gons robustly.
    """
    nx = ny = nz = 0.0
    n = len(face)
    for i in range(n):
        a = verts[face[i]]
        b = verts[face[(i + 1) % n]]
        nx += (a[1] - b[1]) * (a[2] + b[2])
        ny += (a[2] - b[2]) * (a[0] + b[0])
        nz += (a[0] - b[0]) * (a[1] + b[1])
    mag = math.sqrt(nx * nx + ny * ny + nz * nz)
    if mag < 1e-15:
        return (0.0, 0.0, 0.0)
    return (nx / mag, ny / mag, nz / mag)


def _dot3(a: Tuple[float, float, float], b: Tuple[float, float, float]) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _dihedral_angle_deg(
    verts: List[List[float]],
    faces: List[List[int]],
    f0: int,
    f1: int,
) -> float:
    """Dihedral angle in degrees between two adjacent faces (0 = coplanar)."""
    n0 = _face_normal(verts, faces[f0])
    n1 = _face_normal(verts, faces[f1])
    # Guard degenerate normals
    if n0 == (0.0, 0.0, 0.0) or n1 == (0.0, 0.0, 0.0):
        return 0.0
    cos_a = max(-1.0, min(1.0, _dot3(n0, n1)))
    # acos gives angle between normals; 0 = coplanar, 180 = folded back
    return math.degrees(math.acos(cos_a))


def _build_edge_face_map(
    faces: List[List[int]],
) -> Dict[Tuple[int, int], List[int]]:
    """Map each (min,max) edge key → list of adjacent face indices."""
    ef: Dict[Tuple[int, int], List[int]] = defaultdict(list)
    for fi, face in enumerate(faces):
        n = len(face)
        for i in range(n):
            a, b = face[i], face[(i + 1) % n]
            key = (min(a, b), max(a, b))
            ef[key].append(fi)
    return dict(ef)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def auto_classify_edges(
    mesh: SubDMesh,
    hard_threshold_deg: float = 80.0,
    feature_threshold_deg: float = 30.0,
) -> EdgeClassification:
    """Classify every mesh edge by dihedral angle.

    Parameters
    ----------
    mesh : SubDMesh
        Input mesh.  Only triangle and quad faces are needed; n-gons work too.
    hard_threshold_deg : float
        Dihedral angle above which an edge is classified as 'hard_crease'.
        Default 80°, matching a right-angle crease (90°) with a small margin.
    feature_threshold_deg : float
        Dihedral angle above which an edge enters the 'feature_curve' band
        (below ``hard_threshold_deg``).  Default 30°.

    Returns
    -------
    EdgeClassification
        Hard, feature, and smooth edge lists plus per-edge dihedral angles.
    """
    try:
        result = EdgeClassification()
        if not mesh.faces or not mesh.vertices:
            return result

        ef_map = _build_edge_face_map(mesh.faces)
        verts = mesh.vertices
        faces = mesh.faces

        for key, adj_faces in ef_map.items():
            if len(adj_faces) == 1:
                result.boundary_edges.append(key)
            elif len(adj_faces) >= 2:
                angle = _dihedral_angle_deg(verts, faces, adj_faces[0], adj_faces[1])
                result.dihedral_angles[key] = angle

                if angle > hard_threshold_deg:
                    result.hard_edges.append(key)
                elif angle > feature_threshold_deg:
                    result.feature_edges.append(key)
                else:
                    result.smooth_edges.append(key)
            # Edges with 3+ faces (non-manifold) are silently skipped

        return result
    except Exception:
        return EdgeClassification()


def chain_feature_curves(
    mesh: SubDMesh,
    feature_edges: List[Tuple[int, int]],
    kind: str = "feature_curve",
) -> List[FeatureCurve]:
    """Group a set of edges into connected polyline chains.

    Uses a simple graph-walk: build adjacency from the edge set, then trace
    chains starting from degree-1 endpoints (open chains) or any unvisited
    vertex (for closed loops).

    Parameters
    ----------
    mesh : SubDMesh
        The mesh (used only for vertex count validation).
    feature_edges : list of (int, int)
        Edges to chain.  Usually ``EdgeClassification.feature_edges`` or
        ``EdgeClassification.hard_edges``.
    kind : str
        Tag stored on every returned :class:`FeatureCurve`.

    Returns
    -------
    list[FeatureCurve]
        Each element is one connected polyline chain.
    """
    try:
        if not feature_edges:
            return []

        # Build vertex → adjacent vertices map restricted to feature_edges
        adj: Dict[int, List[int]] = defaultdict(list)
        edge_set: Set[Tuple[int, int]] = set()
        for a, b in feature_edges:
            key = (min(a, b), max(a, b))
            edge_set.add(key)
            adj[a].append(b)
            adj[b].append(a)

        visited_edges: Set[Tuple[int, int]] = set()
        visited_verts: Set[int] = set()
        chains: List[FeatureCurve] = []

        def _edge_key(u: int, v: int) -> Tuple[int, int]:
            return (min(u, v), max(u, v))

        def _trace(start: int, prev: Optional[int]) -> FeatureCurve:
            """Walk the chain from start vertex."""
            chain_verts = [start]
            chain_edges: List[Tuple[int, int]] = []
            visited_verts.add(start)
            current = start
            came_from = prev

            while True:
                # Neighbours not yet visited via an unvisited edge
                nbrs = [
                    v for v in adj[current]
                    if _edge_key(current, v) not in visited_edges
                ]
                if not nbrs:
                    break
                # Prefer the neighbour we didn't come from (continue chain)
                nxt = None
                for v in nbrs:
                    if v != came_from:
                        nxt = v
                        break
                if nxt is None:
                    nxt = nbrs[0]

                ek = _edge_key(current, nxt)
                if ek in visited_edges:
                    break
                visited_edges.add(ek)

                # Closed loop detection
                if nxt == start:
                    chain_edges.append(ek)
                    return FeatureCurve(
                        vertex_chain=chain_verts,
                        edge_pairs=chain_edges,
                        kind=kind,
                        is_closed=True,
                    )

                visited_verts.add(nxt)
                chain_verts.append(nxt)
                chain_edges.append(ek)
                came_from = current
                current = nxt

            return FeatureCurve(
                vertex_chain=chain_verts,
                edge_pairs=chain_edges,
                kind=kind,
                is_closed=False,
            )

        # Find degree-1 vertices (chain endpoints) first for clean ordering
        degree_one = [v for v, nbrs in adj.items() if len(nbrs) == 1]

        # Start from endpoints so open chains are traced from end to end
        for start_v in degree_one:
            if start_v in visited_verts:
                continue
            c = _trace(start_v, None)
            if c.edge_pairs:
                chains.append(c)

        # Remaining unvisited vertices belong to closed loops
        for start_v in list(adj.keys()):
            if start_v in visited_verts:
                continue
            c = _trace(start_v, None)
            if c.edge_pairs:
                chains.append(c)

        return chains
    except Exception:
        return []


def auto_subd_preprocess(
    mesh: SubDMesh,
    hard_threshold: float = 80.0,
    feature_threshold: float = 30.0,
) -> SubDPreprocessResult:
    """End-to-end SubD preprocessing pipeline.

    Steps
    -----
    1. Classify all edges via :func:`auto_classify_edges`.
    2. Chain hard edges into :class:`FeatureCurve` objects.
    3. Chain feature edges into :class:`FeatureCurve` objects.
    4. Copy the input mesh and assign crease weights:
       - hard edges → crease = math.inf (→ hard crease in Catmull-Clark)
       - feature edges → crease = 0.5 (fractional, Botsch-Kobbelt §3.2)

    Parameters
    ----------
    mesh : SubDMesh
        Raw input mesh (e.g., imported from STL/OBJ).
    hard_threshold : float
        Dihedral angle (degrees) above which edges are hard creases.
    feature_threshold : float
        Dihedral angle (degrees) above which edges enter the feature band.

    Returns
    -------
    SubDPreprocessResult
        Tagged SubDMesh ready for Catmull-Clark subdivision.
    """
    try:
        classification = auto_classify_edges(mesh, hard_threshold, feature_threshold)

        hard_curves = chain_feature_curves(mesh, classification.hard_edges, kind="hard_crease")
        feat_curves = chain_feature_curves(mesh, classification.feature_edges, kind="feature_curve")

        # Copy the mesh so the original is not mutated
        import copy
        tagged_mesh = SubDMesh(
            vertices=[list(v) for v in mesh.vertices],
            faces=[list(f) for f in mesh.faces],
            creases=dict(mesh.creases),
        )

        # Hard edges → infinite sharpness (SubDMesh clamps to 1.0 internally,
        # but math.inf is the conventional flag for the cage authoring layer)
        for edge in classification.hard_edges:
            tagged_mesh.set_crease(edge[0], edge[1], math.inf)

        # Feature edges → fractional sharpness 0.5 (Botsch-Kobbelt §3.2)
        for edge in classification.feature_edges:
            # Don't overwrite a hard crease
            existing = tagged_mesh.get_crease(edge[0], edge[1])
            if existing < 0.5:
                tagged_mesh.set_crease(edge[0], edge[1], 0.5)

        return SubDPreprocessResult(
            mesh=tagged_mesh,
            classification=classification,
            hard_curves=hard_curves,
            feature_curves=feat_curves,
        )
    except Exception:
        return SubDPreprocessResult(mesh=mesh)


def recommend_thresholds(mesh: SubDMesh) -> Dict[str, float]:
    """Suggest optimal hard/feature dihedral thresholds for a mesh.

    Uses Otsu's method on the histogram of interior dihedral angles to find
    the threshold that maximises inter-class variance.  Applied twice:
    once on the full distribution to locate the hard/feature boundary, and
    once on the sub-distribution below that to locate the feature/smooth
    boundary.

    Parameters
    ----------
    mesh : SubDMesh
        Input mesh.

    Returns
    -------
    dict with keys
        * ``hard_threshold``    — recommended hard-crease threshold (degrees)
        * ``feature_threshold`` — recommended feature-curve threshold (degrees)
        * ``angle_count``       — number of interior dihedral angles measured
        * ``angle_mean``        — mean dihedral angle
        * ``angle_max``         — maximum dihedral angle observed
    """
    try:
        # Collect all interior dihedral angles
        ef_map = _build_edge_face_map(mesh.faces)
        angles: List[float] = []
        for key, adj_faces in ef_map.items():
            if len(adj_faces) == 2:
                a = _dihedral_angle_deg(mesh.vertices, mesh.faces,
                                        adj_faces[0], adj_faces[1])
                angles.append(a)

        if not angles:
            return {
                "hard_threshold": 80.0,
                "feature_threshold": 30.0,
                "angle_count": 0,
                "angle_mean": 0.0,
                "angle_max": 0.0,
            }

        n = len(angles)
        mean_a = sum(angles) / n
        max_a = max(angles)

        # Otsu's method on a 180-bin histogram (1° per bin)
        def _otsu_threshold(values: List[float], bins: int = 180) -> float:
            """Return Otsu threshold in degrees for a list of angles."""
            if not values:
                return 45.0
            hist = [0] * bins
            for v in values:
                idx = min(int(v), bins - 1)
                hist[idx] += 1

            total = len(values)
            best_thresh = 0.0
            best_var = -1.0

            w0 = 0
            sum0 = 0.0
            total_sum = sum(i * hist[i] for i in range(bins))

            for t in range(1, bins):
                w0 += hist[t - 1]
                if w0 == 0:
                    continue
                w1 = total - w0
                if w1 == 0:
                    break
                sum0 += (t - 1) * hist[t - 1]
                mu0 = sum0 / w0
                mu1 = (total_sum - sum0) / w1
                var = (w0 / total) * (w1 / total) * (mu0 - mu1) ** 2
                if var > best_var:
                    best_var = var
                    best_thresh = float(t)

            return best_thresh

        hard_t = _otsu_threshold(angles)
        # Apply Otsu again on angles below the hard threshold to find the
        # feature/smooth boundary
        sub_angles = [a for a in angles if a < hard_t]
        feature_t = _otsu_threshold(sub_angles) if len(sub_angles) > 1 else hard_t * 0.3

        # Clamp to sane defaults if the distribution is degenerate
        hard_t = max(10.0, min(170.0, hard_t))
        feature_t = max(5.0, min(hard_t - 5.0, feature_t))

        return {
            "hard_threshold": round(hard_t, 1),
            "feature_threshold": round(feature_t, 1),
            "angle_count": float(n),
            "angle_mean": round(mean_a, 2),
            "angle_max": round(max_a, 2),
        }
    except Exception:
        return {
            "hard_threshold": 80.0,
            "feature_threshold": 30.0,
            "angle_count": 0,
            "angle_mean": 0.0,
            "angle_max": 0.0,
        }
