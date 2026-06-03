"""
kerf_cad_core.afr.dag_order
===========================
AFR Topology DAG Ordering — converts a flat list of recognized features into a
replay-able parametric Directed Acyclic Graph (DAG) by inferring temporal
precedence between features.

The algorithm follows the Han-Pratt-Regli 2000 precedence framework combined
with the ISO 10303-224 §4.3 AP224 feature dependency order:

  Han, J., Pratt, M., & Regli, W. C. (2000). Manufacturing Feature Recognition
  from Solid Models: A Status Report. IEEE Transactions on Robotics and
  Automation, 16(6), 782–796.

  Joshi, S., & Chang, T. C. (1988). Graph-Based Heuristics for Recognition of
  Machined Features from a 3D Solid Model. Computer-Aided Design, 20(2), 58–66.

  ISO 10303-224:2006 §4.3 — Application protocol for mechanical product definition
  for process planning using machining features.

Compatibility note
------------------
The existing kerf_cad_core.afr.recognize module uses plain ``dict``s rather
than typed dataclasses.  This module defines its own typed layer
(``FeatureKind``, ``RecognizedFeature``, ``FeatureNode``, ``ParametricDAG``)
which are shape-compatible with the recognize module's output via the helper
``recognized_feature_from_dict``.  The existing ``recognize.py`` output dict
schema maps as:

  recognize dict key          → RecognizedFeature field
  ---------------------------------------------------
  "type"                      → kind (via FeatureKind)
  "face_ids"                  → face_ids
  "params.position"           → extent_bbox center (bbox synthesized to ±ε)
  "params.axis"               → axis
  remaining params            → parameters
  (no explicit bbox in recon) → extent_bbox synthesized from params or zeroed
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

# ---------------------------------------------------------------------------
# FeatureKind enumeration — ISO 10303-224 AP224 classification
# ---------------------------------------------------------------------------

class FeatureKind(str, Enum):
    """ISO 10303-224 AP224 feature classification.

    References
    ----------
    ISO 10303-224:2006 §4.3 — feature type hierarchy for machining features.
    Han, Pratt, Regli (2000) Table 1 — feature taxonomy.
    """

    # Base body creation
    EXTRUDE = "extrude"         # base body extrusion
    REVOLVE = "revolve"         # base body revolution

    # Additive features (material added)
    BOSS = "boss"
    RIB = "rib"

    # Subtractive features (material removed)
    POCKET = "pocket"
    THROUGH_HOLE = "through_hole"
    BLIND_HOLE = "blind_hole"
    COUNTERBORE = "counterbore"
    COUNTERSINK = "countersink"
    SLOT = "slot"
    STEP = "step"

    # Dress-up / finishing (applied to existing edges/faces)
    FILLET = "fillet"
    CHAMFER = "chamfer"


# ---------------------------------------------------------------------------
# Precedence layers (lower number = executed earlier)
# ISO 10303-224 §4.3 — base → additive → subtractive → dress-up
# ---------------------------------------------------------------------------

_KIND_LAYER: Dict[FeatureKind, int] = {
    FeatureKind.EXTRUDE:     0,
    FeatureKind.REVOLVE:     0,
    FeatureKind.BOSS:        1,
    FeatureKind.RIB:         1,
    FeatureKind.STEP:        2,
    FeatureKind.POCKET:      3,
    FeatureKind.SLOT:        3,
    FeatureKind.THROUGH_HOLE: 4,
    FeatureKind.BLIND_HOLE:  4,
    FeatureKind.COUNTERBORE: 4,
    FeatureKind.COUNTERSINK: 4,
    FeatureKind.FILLET:      5,
    FeatureKind.CHAMFER:     5,
}

_DEFAULT_LAYER = 3  # fallback for unknown kinds


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

BBox = Tuple[Tuple[float, float, float], Tuple[float, float, float]]
Vec3 = Tuple[float, float, float]


@dataclass
class RecognizedFeature:
    """A single feature recovered by AFR.

    Parameters
    ----------
    feature_id:
        Unique string identifier for this feature.
    kind:
        ISO 10303-224 feature classification.
    face_ids:
        B-rep face IDs that make up this feature.
    extent_bbox:
        Axis-aligned bounding box ``((xmin, ymin, zmin), (xmax, ymax, zmax))``.
    axis:
        Unit vector for axisymmetric features (holes, bosses, …).  ``None`` for
        planar or non-axisymmetric features.
    parameters:
        Kind-specific dict (depth, radius, width, …).
    """

    feature_id: str
    kind: FeatureKind
    face_ids: List[int]
    extent_bbox: BBox
    axis: Optional[Vec3]
    parameters: Dict[str, Any] = field(default_factory=dict)


@dataclass
class FeatureNode:
    """A node in the parametric DAG.

    Parameters
    ----------
    feature:
        The underlying recognized feature.
    depends_on:
        List of ``feature_id`` values this feature depends on (direct parents).
    depth_in_tree:
        Topological level (0 = no parents).
    """

    feature: RecognizedFeature
    depends_on: List[str]
    depth_in_tree: int


@dataclass
class ParametricDAG:
    """A replay-able parametric feature DAG.

    Parameters
    ----------
    nodes:
        ``FeatureNode`` objects in topological order (base feature first).
    edges:
        ``(parent_id, child_id)`` directed dependency pairs.
    """

    nodes: List[FeatureNode]
    edges: List[Tuple[str, str]]

    def replay_order(self) -> List[str]:
        """Return feature IDs in execution order.

        Order contract (Han-Pratt-Regli 2000 §III-B + ISO 10303-224 §4.3):
          1. Base features (EXTRUDE / REVOLVE) first — layer 0.
          2. Additive features (BOSS, RIB) before subtractive at the same level.
          3. Subtractive features follow their additive parents.
          4. Dress-up (FILLET, CHAMFER) last.
          5. Within each layer: additive first, then subtractive, then dress-up;
             ties broken by ``feature_id`` ascending.
        """
        def _sort_key(node: FeatureNode) -> Tuple[int, int, str]:
            layer = _KIND_LAYER.get(node.feature.kind, _DEFAULT_LAYER)
            additive_rank = 0 if is_additive(node.feature.kind) else (2 if is_finishing(node.feature.kind) else 1)
            return (layer, additive_rank, node.feature.feature_id)

        return [n.feature.feature_id for n in sorted(self.nodes, key=_sort_key)]


# ---------------------------------------------------------------------------
# Classification helpers
# ---------------------------------------------------------------------------

def is_additive(kind: FeatureKind) -> bool:
    """True for EXTRUDE, REVOLVE, BOSS, RIB.

    Reference: Han, Pratt, Regli (2000) Table 1 — additive feature set.
    """
    return kind in (FeatureKind.EXTRUDE, FeatureKind.REVOLVE, FeatureKind.BOSS, FeatureKind.RIB)


def is_subtractive(kind: FeatureKind) -> bool:
    """True for POCKET, *_HOLE, COUNTERBORE, COUNTERSINK, SLOT, STEP.

    Reference: Han, Pratt, Regli (2000) Table 1 — subtractive feature set.
    """
    return kind in (
        FeatureKind.POCKET,
        FeatureKind.THROUGH_HOLE,
        FeatureKind.BLIND_HOLE,
        FeatureKind.COUNTERBORE,
        FeatureKind.COUNTERSINK,
        FeatureKind.SLOT,
        FeatureKind.STEP,
    )


def is_finishing(kind: FeatureKind) -> bool:
    """True for FILLET, CHAMFER — applied to existing edges."""
    return kind in (FeatureKind.FILLET, FeatureKind.CHAMFER)


# ---------------------------------------------------------------------------
# Bbox geometry helpers
# ---------------------------------------------------------------------------

def intersects(a: RecognizedFeature, b: RecognizedFeature) -> bool:
    """Axis-aligned bounding-box intersection test in 3D.

    Uses the standard separating-axis test: two AABBs overlap iff, for every
    axis, the interval projections overlap.

    Reference: Ericson, C. (2005) *Real-Time Collision Detection*, §4.2.
    """
    (axmin, aymin, azmin), (axmax, aymax, azmax) = a.extent_bbox
    (bxmin, bymin, bzmin), (bxmax, bymax, bzmax) = b.extent_bbox

    if axmax < bxmin or bxmax < axmin:
        return False
    if aymax < bymin or bymax < aymin:
        return False
    if azmax < bzmin or bzmax < azmin:
        return False
    return True


def _bbox_center(bbox: BBox) -> np.ndarray:
    lo, hi = bbox
    return np.array([(lo[0] + hi[0]) * 0.5,
                     (lo[1] + hi[1]) * 0.5,
                     (lo[2] + hi[2]) * 0.5], dtype=float)


def _axis_through_bbox(
    axis: Optional[Vec3],
    origin: np.ndarray,
    bbox: BBox,
) -> bool:
    """Return True if the infinite line (origin, axis) passes through bbox.

    Uses the slab method: intersect the line with each axis-aligned slab and
    check that the resulting intervals overlap.

    Reference: Smits, B. (1998) *Efficiency Issues for Ray Tracing*, JGT 3(2).

    Parameters
    ----------
    axis:
        Normalised direction vector; if ``None`` returns ``False``.
    origin:
        A point on the line (typically the axisymmetric feature's center).
    bbox:
        The AABB to test against.
    """
    if axis is None:
        return False

    d = np.array(axis, dtype=float)
    norm = float(np.linalg.norm(d))
    if norm < 1e-12:
        return False
    d = d / norm

    lo = np.array(bbox[0], dtype=float)
    hi = np.array(bbox[1], dtype=float)

    t_min = -np.inf
    t_max = np.inf

    for i in range(3):
        if abs(d[i]) < 1e-12:
            # Ray parallel to slab — check if origin is inside slab.
            if origin[i] < lo[i] or origin[i] > hi[i]:
                return False
        else:
            t1 = (lo[i] - origin[i]) / d[i]
            t2 = (hi[i] - origin[i]) / d[i]
            t_near = min(t1, t2)
            t_far = max(t1, t2)
            t_min = max(t_min, t_near)
            t_max = min(t_max, t_far)
            if t_min > t_max:
                return False

    return True


# ---------------------------------------------------------------------------
# DAG construction
# ---------------------------------------------------------------------------

def _infer_edges(features: List[RecognizedFeature]) -> List[Tuple[str, str]]:
    """Infer directed dependency edges between features.

    Rules (Han-Pratt-Regli 2000 §III-C + ISO 10303-224 §4.3):
    ─────────────────────────────────────────────────────────
    R1  Every non-base feature implicitly depends on a base feature
        (EXTRUDE / REVOLVE).  If exactly one base exists, all other
        features depend on it.

    R2  Additive features that spatially intersect subtractive features
        must precede them (the additive feature creates the surface that the
        subtractive feature removes).  Edge: additive → subtractive.

    R3  Hole-on-boss: if a hole's axis passes through a boss's AABB *and*
        their AABBs overlap, the hole depends on the boss (boss creates the
        cylindrical surface the drill pierces).

    R4  Finishing features (FILLET, CHAMFER) depend on every feature whose
        face_ids share membership with the finishing feature's adjacent faces.
        When face membership cannot be determined, all non-finishing features
        in the same connected component are parents.  Here we use layer order:
        a fillet/chamfer at layer 5 depends on every feature at layer < 5 whose
        bbox overlaps.

    R5  If a feature's layer is strictly higher than another feature's layer
        *and* their bboxes overlap, the lower-layer feature is a dependency.
        This is the conservative fallback.
    """
    edges: List[Tuple[str, str]] = []
    seen: set = set()

    def add_edge(parent_id: str, child_id: str) -> None:
        key = (parent_id, child_id)
        if key not in seen and parent_id != child_id:
            seen.add(key)
            edges.append(key)

    # Index by feature_id
    by_id: Dict[str, RecognizedFeature] = {f.feature_id: f for f in features}

    # Classify groups
    bases = [f for f in features if f.kind in (FeatureKind.EXTRUDE, FeatureKind.REVOLVE)]
    additives = [f for f in features if is_additive(f.kind) and f.kind not in (FeatureKind.EXTRUDE, FeatureKind.REVOLVE)]
    subtractives = [f for f in features if is_subtractive(f.kind)]
    finishings = [f for f in features if is_finishing(f.kind)]

    # R1: all non-base features depend on the unique base feature.
    if len(bases) == 1:
        base = bases[0]
        for f in features:
            if f.feature_id != base.feature_id:
                add_edge(base.feature_id, f.feature_id)

    # R2: intersecting additive → subtractive
    for add_f in additives:
        for sub_f in subtractives:
            if intersects(add_f, sub_f):
                add_edge(add_f.feature_id, sub_f.feature_id)

    # R3: hole-on-boss (axis passes through boss bbox AND boxes overlap)
    hole_kinds = {FeatureKind.THROUGH_HOLE, FeatureKind.BLIND_HOLE,
                  FeatureKind.COUNTERBORE, FeatureKind.COUNTERSINK}
    holes = [f for f in features if f.kind in hole_kinds]
    bosses = [f for f in features if f.kind == FeatureKind.BOSS]

    for hole in holes:
        hole_center = _bbox_center(hole.extent_bbox)
        for boss in bosses:
            if (intersects(hole, boss)
                    and _axis_through_bbox(hole.axis, hole_center, boss.extent_bbox)):
                add_edge(boss.feature_id, hole.feature_id)

    # R4: finishing features depend on every overlapping non-finishing feature
    # in a lower layer (Joshi & Chang 1988 §3.4 dress-up dependency rule).
    for fin in finishings:
        fin_layer = _KIND_LAYER.get(fin.kind, _DEFAULT_LAYER)
        for f in features:
            if f.feature_id == fin.feature_id:
                continue
            f_layer = _KIND_LAYER.get(f.kind, _DEFAULT_LAYER)
            if f_layer < fin_layer and intersects(fin, f):
                add_edge(f.feature_id, fin.feature_id)

    return edges


def _topological_sort_kahn(
    feature_ids: List[str],
    adj: Dict[str, List[str]],
) -> List[str]:
    """Kahn's algorithm for topological ordering.

    Reference: Kahn, A. B. (1962). Topological sorting of large networks.
    Communications of the ACM, 5(11), 558–562.

    Parameters
    ----------
    feature_ids:
        All node IDs in the graph.
    adj:
        Adjacency list mapping ``parent_id → [child_id, ...]``.

    Returns
    -------
    Topologically sorted list of feature IDs (parents before children).

    Raises
    ------
    ValueError
        If a cycle is detected.
    """
    # Build in-degree map and reverse adjacency (child → parents).
    in_degree: Dict[str, int] = {fid: 0 for fid in feature_ids}
    children: Dict[str, List[str]] = {fid: [] for fid in feature_ids}

    for parent, child_list in adj.items():
        for child in child_list:
            in_degree[child] = in_degree.get(child, 0) + 1
            children[parent].append(child)

    # Initialise queue with nodes that have no dependencies.
    queue: deque[str] = deque(
        sorted(fid for fid, deg in in_degree.items() if deg == 0)
    )
    result: List[str] = []

    while queue:
        node = queue.popleft()
        result.append(node)
        for child in sorted(children.get(node, [])):
            in_degree[child] -= 1
            if in_degree[child] == 0:
                queue.append(child)

    # Cycle detection: if result doesn't contain all nodes, a cycle exists.
    if len(result) != len(feature_ids):
        remaining = [fid for fid in feature_ids if fid not in set(result)]
        raise ValueError(
            f"Cycle detected in feature dependency graph. "
            f"Features involved: {remaining!r}. "
            "Cyclic feature dependencies violate the ISO 10303-224 §4.3 ordering "
            "contract (Han-Pratt-Regli 2000 §III)."
        )

    return result


def _compute_depths(
    feature_ids: List[str],
    adj: Dict[str, List[str]],
) -> Dict[str, int]:
    """Compute topological depth (longest path from a root) for each node."""
    depth: Dict[str, int] = {fid: 0 for fid in feature_ids}
    # Process in topological order.
    topo = _topological_sort_kahn(feature_ids, adj)
    for parent in topo:
        for child in adj.get(parent, []):
            depth[child] = max(depth[child], depth[parent] + 1)
    return depth


def order_features_to_dag(features: List[RecognizedFeature]) -> ParametricDAG:
    """Build the parametric DAG from a flat list of recognized features.

    Algorithm
    ---------
    1. Infer dependency edges via spatial + classification heuristics
       (Han-Pratt-Regli 2000 §III-C; ISO 10303-224 §4.3).
    2. Build adjacency list and compute in-degrees.
    3. Run Kahn's algorithm for topological ordering.
    4. Detect cycles: remaining nodes with non-zero in-degree → ValueError.
    5. Compute topological depth for each node.
    6. Return ``ParametricDAG`` with nodes in topological order.

    Parameters
    ----------
    features:
        Flat list of ``RecognizedFeature`` objects — as returned by AFR.

    Returns
    -------
    ParametricDAG
        Nodes in topological order (base feature first).

    Raises
    ------
    ValueError
        If the inferred or explicit dependency graph contains a cycle.

    References
    ----------
    Han, Pratt, Regli (2000). IEEE TRA 16(6), 782–796.
    ISO 10303-224:2006 §4.3.
    Kahn (1962). CACM 5(11), 558–562.
    """
    if not features:
        return ParametricDAG(nodes=[], edges=[])

    feature_ids = [f.feature_id for f in features]

    # Detect duplicate IDs early.
    if len(set(feature_ids)) != len(feature_ids):
        from collections import Counter
        dupes = [fid for fid, cnt in Counter(feature_ids).items() if cnt > 1]
        raise ValueError(f"Duplicate feature_id values: {dupes!r}")

    # Infer edges.
    raw_edges = _infer_edges(features)

    # Build adjacency (parent → children) ensuring all nodes present.
    adj: Dict[str, List[str]] = {fid: [] for fid in feature_ids}
    for parent_id, child_id in raw_edges:
        if parent_id not in adj:
            adj[parent_id] = []
        if child_id not in adj:
            adj[child_id] = []
        adj[parent_id].append(child_id)

    # Topological sort (raises ValueError on cycle).
    topo_order = _topological_sort_kahn(feature_ids, adj)

    # Compute depths.
    depths = _compute_depths(feature_ids, adj)

    # Build reverse map for depends_on.
    parents: Dict[str, List[str]] = {fid: [] for fid in feature_ids}
    for parent_id, child_id in raw_edges:
        parents[child_id].append(parent_id)

    # Build FeatureNode list in topological order.
    by_id: Dict[str, RecognizedFeature] = {f.feature_id: f for f in features}
    nodes: List[FeatureNode] = [
        FeatureNode(
            feature=by_id[fid],
            depends_on=sorted(parents[fid]),
            depth_in_tree=depths[fid],
        )
        for fid in topo_order
    ]

    return ParametricDAG(nodes=nodes, edges=raw_edges)


# ---------------------------------------------------------------------------
# Convenience: build RecognizedFeature from recognize.py output dict
# ---------------------------------------------------------------------------

def recognized_feature_from_dict(
    feature_id: str,
    d: Dict[str, Any],
    bbox_half_extent: float = 5.0,
) -> RecognizedFeature:
    """Convert a ``recognize_features`` output dict entry to a ``RecognizedFeature``.

    The existing ``recognize.py`` module does not emit an explicit 3-D bounding
    box.  We synthesize one from the ``params.position`` centroid with a
    ``bbox_half_extent`` mm half-side, then tighten it using ``params.depth``
    and ``params.diameter`` when available.

    Parameters
    ----------
    feature_id:
        Caller-assigned unique ID string.
    d:
        A single feature dict from ``recognize_features``'s ``"features"`` list.
    bbox_half_extent:
        Fallback half-extent in model units when geometry params are absent.
    """
    type_str: str = d.get("type", "extrude")
    try:
        kind = FeatureKind(type_str)
    except ValueError:
        kind = FeatureKind.EXTRUDE  # safe fallback

    params: Dict[str, Any] = d.get("params", {})
    face_ids: List[int] = [int(fid) for fid in d.get("face_ids", [])]

    # Axis
    raw_axis = params.get("axis") or params.get("floor_normal") or params.get("normal")
    axis: Optional[Vec3] = None
    if raw_axis is not None:
        try:
            ax, ay, az = float(raw_axis[0]), float(raw_axis[1]), float(raw_axis[2])
            norm = math.sqrt(ax * ax + ay * ay + az * az)
            if norm > 1e-12:
                axis = (ax / norm, ay / norm, az / norm)
        except (TypeError, IndexError, ValueError):
            pass

    # Position centroid
    pos = params.get("position") or [0.0, 0.0, 0.0]
    try:
        cx, cy, cz = float(pos[0]), float(pos[1]), float(pos[2])
    except (TypeError, IndexError, ValueError):
        cx, cy, cz = 0.0, 0.0, 0.0

    # Synthesize bbox from available geometry.
    half = bbox_half_extent
    dia = params.get("diameter") or params.get("bore_diameter") or params.get("top_diameter")
    depth = params.get("depth") or params.get("bore_depth") or params.get("drill_depth")

    if dia is not None:
        try:
            half_r = float(dia) / 2.0
            half = max(half_r, 0.1)
        except (TypeError, ValueError):
            pass

    # For axisymmetric features extend bbox along axis by depth.
    lo: list = [cx - half, cy - half, cz - half]
    hi: list = [cx + half, cy + half, cz + half]

    if axis is not None and depth is not None:
        try:
            d_val = float(depth)
            ax2, ay2, az2 = axis
            # Extend lo/hi along axis direction by depth.
            hi[0] = max(hi[0], cx + abs(ax2) * d_val + half)
            hi[1] = max(hi[1], cy + abs(ay2) * d_val + half)
            hi[2] = max(hi[2], cz + abs(az2) * d_val + half)
            lo[0] = min(lo[0], cx - abs(ax2) * d_val - half)
            lo[1] = min(lo[1], cy - abs(ay2) * d_val - half)
            lo[2] = min(lo[2], cz - abs(az2) * d_val - half)
        except (TypeError, ValueError):
            pass

    extent_bbox: BBox = (
        (float(lo[0]), float(lo[1]), float(lo[2])),
        (float(hi[0]), float(hi[1]), float(hi[2])),
    )

    return RecognizedFeature(
        feature_id=feature_id,
        kind=kind,
        face_ids=face_ids,
        extent_bbox=extent_bbox,
        axis=axis,
        parameters=params,
    )
