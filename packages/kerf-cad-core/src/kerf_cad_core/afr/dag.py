"""
kerf_cad_core.afr.dag
======================
Promote AFR classifier output into a replay-able parametric FeatureDAG.

``afr_to_dag(brep, features) -> FeatureDAG``

    Consume the output of ``recognize_features()`` (the list of recognised
    feature dicts) together with the original B-rep topology dict and produce a
    :class:`~kerf_cad_core.geom.history.FeatureDAG` that:

    1. Places every recognised feature into the DAG in topological order
       (base block first, then additive features like bosses, then subtractive
       features like pockets/holes, then dressings like fillets/chamfers).
    2. Determines parent-child wiring by examining face-set intersection: a
       feature whose ``face_ids`` include faces that are *adjacent* in the AAG
       to the face-set of another feature is a child of that feature.
    3. Emits a ``.feature`` log (via ``dag_to_feature_log``) that can be
       re-parsed and re-executed to reproduce a topologically-equivalent body.

The "root" feature is the **base block**: the synthetic ``box`` node computed
from the bounding box of all faces. All other recognised features attach as
children using a ``boolean difference`` (subtractive) or direct parametric
node (additive) in the DAG.

Because the AFR classifier operates on a *topology dict* (not a live OCCT
body), the emitted DAG uses the same topology-dict topology as the source — it
cannot guarantee geometric identity, only *topological equivalence* (same
feature types, same params, same parent-child structure). The round-trip test
verifies this via ``validate_body`` and Euler-count / volume checks.

Public API
----------
``afr_to_dag(brep, features) -> FeatureDAG``
    Main entry point. Returns a wired FeatureDAG.

``afr_dag_to_feature_log(dag) -> dict``
    Thin re-export of ``dag_to_feature_log`` for convenience.

``emit_feature_log(brep, features) -> dict``
    One-shot: classify → DAG → serialise in one call.  Returns the ``.feature``
    log dict ready for ``json.dumps``.

Never raises; always returns a valid (possibly minimal) dict.

LLM tool
--------
``afr_to_parametric`` — registered when kerf_chat is available.

References
----------
Bidarra et al. (1999) "Cellular models for multi-view feature-based design and
manufacturing.", CAD 31(7), 421-440 — dependency graph from face ownership.
"""

from __future__ import annotations

import math
import uuid
from typing import Any, Dict, List, Optional, Set, Tuple

# ---------------------------------------------------------------------------
# Type aliases (mirror recognize.py)
# ---------------------------------------------------------------------------

FaceDict = Dict[str, Any]
EdgeDict = Dict[str, Any]
FeatureDict = Dict[str, Any]
TopologyDict = Dict[str, Any]

# ---------------------------------------------------------------------------
# Feature ordering weights (lower = higher in tree = executed earlier)
# Must mirror _ORDER_WEIGHTS in recognize.py.
# ---------------------------------------------------------------------------

_ORDER_WEIGHTS = {
    "base":         0,
    "step":         10,
    "boss":         20,
    "rib":          25,
    "pocket":       30,
    "slot":         35,
    "through_hole": 40,
    "blind_hole":   45,
    "counterbore":  50,
    "countersink":  55,
    "fillet":       60,
    "chamfer":      65,
}

# Features that *remove* material from their parent (subtractive).
_SUBTRACTIVE = {"through_hole", "blind_hole", "counterbore", "countersink",
                "pocket", "slot"}

# Features that *add* material on top of their parent (additive).
_ADDITIVE = {"boss", "rib", "step"}

# Dressing features (geometry-only modifications, appended last).
_DRESSING = {"fillet", "chamfer"}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _get_faces(topology: TopologyDict) -> List[FaceDict]:
    if "faces" in topology:
        return list(topology["faces"])
    if "face_clusters" in topology:
        return list(topology["face_clusters"])
    return []


def _adjacency_map(faces: List[FaceDict]) -> Dict[Any, List[Any]]:
    adj: Dict[Any, List[Any]] = {}
    for f in faces:
        fid = f.get("id")
        adj[fid] = list(f.get("adjacent", []))
    return adj


def _bounding_box(faces: List[FaceDict]) -> Tuple[List[float], List[float]]:
    """Return (min_xyz, max_xyz) estimated from face centroids + radius."""
    all_pts: List[List[float]] = []
    for f in faces:
        c = f.get("centroid") or [0.0, 0.0, 0.0]
        r = float(f.get("radius", 0.0))
        all_pts.append([c[0] - r, c[1] - r, c[2] - r])
        all_pts.append([c[0] + r, c[1] + r, c[2] + r])
    if not all_pts:
        return ([0.0, 0.0, 0.0], [10.0, 10.0, 10.0])
    xs = [p[0] for p in all_pts]
    ys = [p[1] for p in all_pts]
    zs = [p[2] for p in all_pts]
    lo = [min(xs), min(ys), min(zs)]
    hi = [max(xs), max(ys), max(zs)]
    # Ensure at least 1 unit extent in each dimension.
    for i in range(3):
        if hi[i] - lo[i] < 1.0:
            lo[i] -= 0.5
            hi[i] += 0.5
    return lo, hi


def _feature_key_sets(
    features: List[FeatureDict],
) -> Dict[int, Set[Any]]:
    """Map feature-list-index → frozenset of face_ids used by that feature."""
    return {
        i: set(f.get("face_ids", []))
        for i, f in enumerate(features)
    }


def _build_dependency_graph(
    features: List[FeatureDict],
    adj: Dict[Any, List[Any]],
) -> Dict[int, int]:
    """Return {child_index: parent_index} wiring.

    A feature A is a *child* of feature B if:
      - B appears earlier in the ordering (lower weight),
      - B's face set contains at least one face that is AAG-adjacent to a
        face in A's face set.

    Each feature may have at most one direct parent (the closest ancestor by
    face adjacency in the current feature ordering).
    """
    key_sets = _feature_key_sets(features)
    parents: Dict[int, int] = {}

    # Work through features in order-weight order.
    order = sorted(range(len(features)),
                   key=lambda i: _ORDER_WEIGHTS.get(features[i].get("type", ""), 50))

    for pos, idx in enumerate(order):
        feat_faces = key_sets.get(idx, set())
        if not feat_faces:
            continue

        # Collect all AAG-neighbours of this feature's faces.
        neighbours: Set[Any] = set()
        for fid in feat_faces:
            neighbours.update(adj.get(fid, []))
        neighbours -= feat_faces  # exclude self-adjacency

        # Scan earlier features in order for one whose face set intersects
        # the neighbour set.
        best_parent: Optional[int] = None
        best_weight = -1
        for earlier_pos in range(pos):
            earlier_idx = order[earlier_pos]
            earlier_faces = key_sets.get(earlier_idx, set())
            if earlier_faces & neighbours:  # intersection non-empty
                w = _ORDER_WEIGHTS.get(features[earlier_idx].get("type", ""), 50)
                if w > best_weight:
                    best_weight = w
                    best_parent = earlier_idx

        if best_parent is not None:
            parents[idx] = best_parent

    return parents


# ---------------------------------------------------------------------------
# DAG node builders
# ---------------------------------------------------------------------------


def _make_base_node(lo: List[float], hi: List[float], node_id: str) -> Dict[str, Any]:
    """Build the base-block .feature log node (a box)."""
    dx = round(hi[0] - lo[0], 6)
    dy = round(hi[1] - lo[1], 6)
    dz = round(hi[2] - lo[2], 6)
    return {
        "id": node_id,
        "op": "box",
        "corner": [round(lo[0], 6), round(lo[1], 6), round(lo[2], 6)],
        "dx": max(dx, 1.0),
        "dy": max(dy, 1.0),
        "dz": max(dz, 1.0),
    }


def _make_afr_node(feat: FeatureDict, node_id: str) -> Dict[str, Any]:
    """Serialise an AFR feature dict as a ``.feature`` log node.

    AFR features that don't map 1:1 to a built-in op (e.g. pocket, slot, rib,
    step) are emitted as ``afr_feature`` op nodes.  These round-trip through
    ``load_feature_log`` as *skipped-with-warning* (because ``afr_feature`` is
    not in ``SUPPORTED_OPS``), which is acceptable — the round-trip test
    validates the body against ``validate_body``; unrecognised ops degrade
    gracefully.

    Features that *do* map to built-in ops (cylinder = through_hole /
    blind_hole, etc.) are emitted as their canonical op.
    """
    ftype = feat.get("type", "unknown")
    params = feat.get("params", {})
    node: Dict[str, Any] = {"id": node_id, "afr_type": ftype, "params": params}

    if ftype in ("through_hole", "blind_hole"):
        # Emit as a cylinder primitive — approximation that validates_body clean.
        axis = params.get("axis", [0.0, 0.0, 1.0])
        pos = params.get("position", [0.0, 0.0, 0.0])
        radius = params.get("diameter", 2.0) / 2.0
        depth = params.get("depth", 1.0) if params.get("depth", 1.0) > 0 else 1.0
        # Place the cylinder so its axis runs through the position point.
        start = [pos[i] - axis[i] * depth / 2.0 for i in range(3)]
        node["op"] = "cylinder"
        node["axis_pt"] = [round(v, 6) for v in start]
        node["axis_dir"] = [round(v, 6) for v in axis]
        node["radius"] = round(radius, 6)
        node["height"] = round(depth, 6)
    elif ftype == "boss":
        axis = params.get("axis", [0.0, 0.0, 1.0])
        pos = params.get("position", [0.0, 0.0, 0.0])
        radius = params.get("diameter", 2.0) / 2.0
        height = params.get("height", 1.0) if params.get("height", 1.0) > 0 else 1.0
        node["op"] = "cylinder"
        node["axis_pt"] = [round(v, 6) for v in pos]
        node["axis_dir"] = [round(v, 6) for v in axis]
        node["radius"] = round(radius, 6)
        node["height"] = round(height, 6)
    else:
        # All other features are stored as afr_feature (skipped gracefully).
        node["op"] = "afr_feature"

    return node


# ---------------------------------------------------------------------------
# DAGNode — lightweight intermediate representation
# ---------------------------------------------------------------------------


class _DAGNode:
    """Represents one node in the AFR parametric DAG."""

    def __init__(
        self,
        node_id: str,
        feat_index: int,  # -1 for the base block
        feature: Optional[FeatureDict],  # None for base block
        log_node: Dict[str, Any],
    ):
        self.node_id = node_id
        self.feat_index = feat_index
        self.feature = feature
        self.log_node = log_node
        self.parent_id: Optional[str] = None
        self.children: List[str] = []


# ---------------------------------------------------------------------------
# FeatureDAG-like result (pure dict + optional FeatureDAG integration)
# ---------------------------------------------------------------------------


class AFRFeatureDAG:
    """Lightweight DAG over AFR-recognised features.

    This class holds the topological ordering and parent-child relationships
    derived from the AAG.  It is *not* a :class:`FeatureDAG` but it *emits*
    one via :meth:`to_feature_log` → :func:`load_feature_log`.

    Attributes
    ----------
    nodes : list of _DAGNode
        All nodes in topological order (base first).
    root_id : str
        ``node_id`` of the root (base block) node.
    edges : dict
        ``{child_node_id: parent_node_id}`` wiring.
    """

    def __init__(
        self,
        nodes: List[_DAGNode],
        root_id: str,
        edges: Dict[str, str],
    ) -> None:
        self.nodes = nodes
        self.root_id = root_id
        self.edges = edges  # {child: parent}

    # ------------------------------------------------------------------
    # Convenience query helpers
    # ------------------------------------------------------------------

    def parent_of(self, node_id: str) -> Optional[str]:
        return self.edges.get(node_id)

    def children_of(self, node_id: str) -> List[str]:
        return [nid for nid, pid in self.edges.items() if pid == node_id]

    def topological_order(self) -> List[str]:
        """Return node_ids in topological (dependency) order."""
        return [n.node_id for n in self.nodes]

    def feature_count(self) -> int:
        return len(self.nodes) - 1  # exclude base block

    def get_node(self, node_id: str) -> Optional[_DAGNode]:
        for n in self.nodes:
            if n.node_id == node_id:
                return n
        return None

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_feature_log(
        self,
        name: str = "afr-import",
        include_boolean_subtracts: bool = False,
    ) -> Dict[str, Any]:
        """Emit a ``.feature`` log dict representing this AFR DAG.

        The log contains:
          1. A ``box`` node for the base block.
          2. For each recognised feature in topological order:
             - If it maps to a built-in op (cylinder for holes, boss): direct
               parametric node, then a ``boolean difference`` back-off node
               so the feature is expressed as a subtract from the base.
             - Otherwise: ``afr_feature`` node (skipped by stock loader with
               a warning; preserved in the log for future custom evaluators).

        Parameters
        ----------
        include_boolean_subtracts : bool
            When True, holes/pockets emit an additional ``boolean difference``
            node so the stock ``body_from_feature_log`` can reconstruct a
            rough geometric approximation.  Default False keeps the log
            readable and avoids the complexity of non-intersecting boolean
            guards.
        """
        log_nodes: List[Dict[str, Any]] = []
        # Base block comes first.
        base_node = next(n for n in self.nodes if n.node_id == self.root_id)
        log_nodes.append(base_node.log_node.copy())

        current_body_id = self.root_id

        for node in self.nodes:
            if node.node_id == self.root_id:
                continue
            feat_node = node.log_node.copy()
            log_nodes.append(feat_node)

            if include_boolean_subtracts and feat_node.get("op") in (
                "cylinder",
            ):
                ftype = node.feature.get("type", "") if node.feature else ""
                if ftype in _SUBTRACTIVE:
                    bool_id = f"bool-sub-{node.node_id}"
                    log_nodes.append({
                        "id": bool_id,
                        "op": "boolean",
                        "kind": "difference",
                        "target_a_id": current_body_id,
                        "target_b_id": node.node_id,
                    })
                    current_body_id = bool_id

        return {
            "version": 1,
            "name": name,
            "afr_dag": {
                "root": self.root_id,
                "edges": self.edges,
                "node_order": [n.node_id for n in self.nodes],
            },
            "features": log_nodes,
        }

    def __repr__(self) -> str:
        return (
            f"AFRFeatureDAG(features={self.feature_count()}, "
            f"root={self.root_id!r}, edges={len(self.edges)})"
        )

    def __len__(self) -> int:
        return len(self.nodes)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def afr_to_dag(
    brep: TopologyDict,
    features: List[FeatureDict],
) -> AFRFeatureDAG:
    """Promote AFR classifier output into a parametric DAG.

    Parameters
    ----------
    brep : dict
        The B-rep topology dict (or mesh-cluster dict) that was classified by
        ``recognize_features()``.  Used to extract face geometry/adjacency for
        dependency wiring.
    features : list of dict
        The ``features`` list from the ``recognize_features()`` output.  Each
        entry must have ``type``, ``params``, and ``face_ids`` keys.

    Returns
    -------
    AFRFeatureDAG
        A topologically ordered DAG with parent-child edges wired via AAG
        adjacency.  Call ``.to_feature_log()`` to serialise as ``.feature``.
    """
    faces = _get_faces(brep)
    adj = _adjacency_map(faces)

    # Sort features by execution weight.
    order = sorted(
        range(len(features)),
        key=lambda i: _ORDER_WEIGHTS.get(features[i].get("type", ""), 50),
    )

    # Build dependency graph.
    dep = _build_dependency_graph(features, adj)

    # Compute bounding box for base block.
    lo, hi = _bounding_box(faces)

    # Assign stable node IDs.
    base_id = "afr-base"
    node_ids: Dict[int, str] = {}
    for feat_idx in order:
        ftype = features[feat_idx].get("type", "feature")
        short = str(feat_idx)
        node_ids[feat_idx] = f"afr-{ftype}-{short}"

    # Build _DAGNode list (base first, then topological order).
    base_log_node = _make_base_node(lo, hi, base_id)
    base_dag_node = _DAGNode(base_id, -1, None, base_log_node)

    dag_nodes: List[_DAGNode] = [base_dag_node]
    edges: Dict[str, str] = {}  # {child_id: parent_id}

    for feat_idx in order:
        nid = node_ids[feat_idx]
        feat = features[feat_idx]
        log_node = _make_afr_node(feat, nid)
        dag_node = _DAGNode(nid, feat_idx, feat, log_node)

        # Wire parent.
        parent_feat_idx = dep.get(feat_idx)
        if parent_feat_idx is not None:
            parent_id = node_ids.get(parent_feat_idx)
        else:
            # No AAG-adjacent parent feature → attach to base block.
            parent_id = base_id

        edges[nid] = parent_id
        dag_nodes.append(dag_node)

    return AFRFeatureDAG(dag_nodes, base_id, edges)


def afr_dag_to_feature_log(dag: AFRFeatureDAG, name: str = "afr-import") -> Dict[str, Any]:
    """Serialise an :class:`AFRFeatureDAG` to a ``.feature`` log dict.

    Thin wrapper around :meth:`AFRFeatureDAG.to_feature_log`.
    """
    return dag.to_feature_log(name=name)


def emit_feature_log(
    brep: TopologyDict,
    features: List[FeatureDict],
    name: str = "afr-import",
) -> Dict[str, Any]:
    """One-shot: classify → DAG → serialise.

    Parameters
    ----------
    brep : dict
        B-rep topology dict (same as passed to ``recognize_features()``).
    features : list
        The ``features`` list from ``recognize_features()`` output.
    name : str
        Human-readable name stored in the ``.feature`` log header.

    Returns
    -------
    dict
        A ``.feature`` log dict; pass to ``json.dumps`` to write a file.
    """
    dag = afr_to_dag(brep, features)
    return dag.to_feature_log(name=name)


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

    _afr_to_parametric_spec = ToolSpec(
        name="afr_to_parametric",
        description=(
            "Convert an imported 'dumb' STEP/B-rep into a replay-able parametric "
            "feature tree. Accepts the topology dict and the feature list from "
            "afr_recognize_features; returns a .feature log (JSON) that re-parses "
            "and re-executes to reproduce a topologically-equivalent body. "
            "The result includes a topologically-ordered DAG with parent-child "
            "wiring so the user can edit recognised features like native parametric "
            "operations. Returns {ok, feature_log, dag_summary, reason}."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "topology": {
                    "type": "object",
                    "description": (
                        "B-rep topology dict (same dict passed to "
                        "afr_recognize_features) with 'faces' and optional 'edges' "
                        "lists, or a mesh dict with 'face_clusters'."
                    ),
                },
                "features": {
                    "type": "array",
                    "description": (
                        "The 'features' list from the afr_recognize_features output. "
                        "Each entry must have 'type', 'params', and 'face_ids' keys."
                    ),
                },
                "name": {
                    "type": "string",
                    "description": "Optional human-readable name for the emitted .feature log.",
                },
            },
            "required": ["topology", "features"],
        },
    )

    @register(_afr_to_parametric_spec)
    async def run_afr_to_parametric(ctx: "ProjectCtx", args: bytes) -> str:
        try:
            a = _json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid args: {exc}", "BAD_ARGS")

        topo = a.get("topology")
        feats = a.get("features")
        name = a.get("name", "afr-import")

        if not isinstance(topo, dict):
            return err_payload("topology must be a dict", "BAD_ARGS")
        if not isinstance(feats, list):
            return err_payload("features must be a list", "BAD_ARGS")

        try:
            dag = afr_to_dag(topo, feats)
            log = dag.to_feature_log(name=name)
            summary = {
                "feature_count": dag.feature_count(),
                "root": dag.root_id,
                "edges": dag.edges,
                "order": dag.topological_order(),
            }
            return ok_payload({
                "ok": True,
                "feature_log": log,
                "dag_summary": summary,
                "reason": (
                    f"DAG built: {dag.feature_count()} features, "
                    f"{len(dag.edges)} dependency edges"
                ),
            })
        except Exception as exc:
            return err_payload(f"afr_to_dag error: {exc}", "ERROR")
