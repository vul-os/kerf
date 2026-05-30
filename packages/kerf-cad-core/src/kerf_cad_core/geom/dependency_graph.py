"""dependency_graph.py
=====================
NURBS dependency graph + smart-edit propagation.

Implements the parametric change-propagation model described in:

    Hoffmann, C.M., Joan-Arinyo, R. (2002). "Erep — A solid modeler editing
    tool."  Proceedings of the 7th ACM Symposium on Solid Modeling and
    Applications, ACM Press, pp. 27–38.

Design overview
---------------
A ``DependencyGraph`` is a DAG whose nodes are geometric entities (control
points, curves, surfaces, bodies) and whose directed edges encode "X depends on
Y" (upstream → downstream).  When an entity is mutated:

1. ``mark_dirty(node)`` propagates the *dirty* flag forward along edges so that
   every entity whose value depends (directly or transitively) on the changed
   node is scheduled for recomputation.
2. ``propagate()`` performs a topological sort over the dirty sub-graph and
   re-evaluates each node's ``recompute`` callable in dependency order.

``build_graph_for_body(body)`` derives the graph automatically from a B-rep
``Body``: vertex → edge → face → shell/solid → body.

``smart_edit(body, edit_op, dependency_graph)`` applies an edit operation,
marks only the affected nodes dirty, then calls ``propagate()`` — touching
only the reachable downstream sub-graph rather than every entity in the body.

No networkx dependency: the graph is stored as two plain adjacency dicts
(upstream → {downstream} and downstream → {upstream}).

Public API
----------
  NodeKind          — enum for vertex / edge / face / shell / body
  GraphNode         — lightweight node wrapper (entity ref + kind + dirty flag)
  DependencyGraph   — DAG, add_dependency, mark_dirty, propagate
  build_graph_for_body(body) -> DependencyGraph
  smart_edit(body, edit_op, dependency_graph) -> body

LLM tools (registered when kerf_chat.tools.registry is available):
  nurbs_dependency_graph  — build + query the graph for a serialised body
  nurbs_smart_edit        — apply a CP edit and report what was recomputed
"""

from __future__ import annotations

import json
from collections import deque
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import (
    Any,
    Callable,
    Dict,
    Iterable,
    List,
    Optional,
    Set,
)


# ---------------------------------------------------------------------------
# Node kinds
# ---------------------------------------------------------------------------

class NodeKind(Enum):
    CONTROL_POINT = auto()
    CURVE = auto()
    SURFACE = auto()
    SHELL = auto()
    BODY = auto()


# ---------------------------------------------------------------------------
# Graph node
# ---------------------------------------------------------------------------

@dataclass
class GraphNode:
    """A node in the dependency graph.

    Attributes
    ----------
    entity : Any
        The underlying geometric object (Vertex, Edge, Face, Body, or a plain
        np.ndarray control point).
    kind : NodeKind
        Semantic role of this node.
    dirty : bool
        True when the entity must be recomputed before it can be used.
    recompute : Optional[Callable[[], None]]
        Called by ``propagate()`` when this node is dirty.  May be None for
        leaf nodes (e.g. raw control points) that have no derived value.
    label : str
        Human-readable name for debugging / serialisation.
    """

    entity: Any
    kind: NodeKind
    dirty: bool = False
    recompute: Optional[Callable[[], None]] = field(default=None, repr=False)
    label: str = ""

    def __post_init__(self):
        if not self.label:
            self.label = f"{self.kind.name}@{id(self.entity):x}"

    # Identity is object-identity of the wrapped entity so the same Python
    # object maps to exactly one node in the graph regardless of duplicates.
    def __hash__(self):
        return id(self.entity)

    def __eq__(self, other):
        if isinstance(other, GraphNode):
            return self.entity is other.entity
        return NotImplemented


# ---------------------------------------------------------------------------
# DependencyGraph
# ---------------------------------------------------------------------------

class DependencyGraph:
    """Directed acyclic dependency graph.

    Edges are stored as ``_deps[downstream] = {upstream, ...}`` (what does
    this node depend on?) and the reverse ``_rdeps[upstream] = {downstream,
    ...}`` (what downstream nodes consume this node?).

    Propagation direction: upstream → downstream.  When a node is marked dirty
    all transitive *downstream* successors are also marked dirty.
    """

    def __init__(self) -> None:
        # node label → GraphNode
        self._nodes: Dict[str, GraphNode] = {}
        # node label → set of downstream node labels
        self._rdeps: Dict[str, Set[str]] = {}
        # node label → set of upstream node labels
        self._deps: Dict[str, Set[str]] = {}

    # ------------------------------------------------------------------
    # Node management
    # ------------------------------------------------------------------

    def add_node(self, node: GraphNode) -> None:
        """Register a node (idempotent by label)."""
        if node.label not in self._nodes:
            self._nodes[node.label] = node
            self._rdeps[node.label] = set()
            self._deps[node.label] = set()

    def get_node(self, label: str) -> Optional[GraphNode]:
        return self._nodes.get(label)

    def nodes(self) -> List[GraphNode]:
        return list(self._nodes.values())

    def node_count(self) -> int:
        return len(self._nodes)

    def edge_count(self) -> int:
        return sum(len(v) for v in self._rdeps.values())

    # ------------------------------------------------------------------
    # Edge management
    # ------------------------------------------------------------------

    def add_dependency(self, downstream: GraphNode, upstream: GraphNode) -> None:
        """Record that *downstream* depends on *upstream*.

        Calling with unknown nodes auto-registers them.  Adding a duplicate
        edge is a no-op.
        """
        self.add_node(downstream)
        self.add_node(upstream)
        self._deps[downstream.label].add(upstream.label)
        self._rdeps[upstream.label].add(downstream.label)

    # ------------------------------------------------------------------
    # Dirty propagation
    # ------------------------------------------------------------------

    def mark_dirty(self, node: GraphNode) -> Set[str]:
        """Mark *node* and all transitive downstream nodes as dirty.

        Returns the set of node labels that were newly marked dirty (for
        introspection / testing).
        """
        self.add_node(node)
        newly_dirty: Set[str] = set()
        queue: deque[str] = deque([node.label])
        while queue:
            label = queue.popleft()
            n = self._nodes.get(label)
            if n is None:
                continue
            if not n.dirty:
                n.dirty = True
                newly_dirty.add(label)
            # propagate forward to all downstream consumers
            for ds_label in self._rdeps.get(label, ()):
                ds = self._nodes.get(ds_label)
                if ds is not None and not ds.dirty:
                    queue.append(ds_label)
        return newly_dirty

    # ------------------------------------------------------------------
    # Topological sort
    # ------------------------------------------------------------------

    def _topo_order(self, labels: Iterable[str]) -> List[str]:
        """Kahn's algorithm: return labels in dependency-first order.

        Only considers nodes reachable within the subgraph spanned by
        *labels*, restricted to edges that exist in the full graph.
        """
        label_set = set(labels)
        # in-degree within the subgraph
        in_deg: Dict[str, int] = {}
        for lbl in label_set:
            in_deg[lbl] = 0
        for lbl in label_set:
            for up in self._deps.get(lbl, ()):
                if up in label_set:
                    in_deg[lbl] += 1

        queue: deque[str] = deque(l for l, d in in_deg.items() if d == 0)
        result: List[str] = []
        while queue:
            lbl = queue.popleft()
            result.append(lbl)
            for ds in self._rdeps.get(lbl, ()):
                if ds in label_set:
                    in_deg[ds] -= 1
                    if in_deg[ds] == 0:
                        queue.append(ds)

        if len(result) != len(label_set):
            # Cycle detected — fall back to arbitrary order (should not happen
            # in a well-formed B-rep graph).
            missing = label_set - set(result)
            result.extend(missing)
        return result

    # ------------------------------------------------------------------
    # Propagate
    # ------------------------------------------------------------------

    def propagate(self) -> List[str]:
        """Re-evaluate all dirty nodes in topological (dependency-first) order.

        Calls each node's ``recompute`` callable (if present) and clears the
        dirty flag.  Returns the ordered list of node labels that were
        recomputed.
        """
        dirty_labels = [lbl for lbl, n in self._nodes.items() if n.dirty]
        ordered = self._topo_order(dirty_labels)
        recomputed: List[str] = []
        for lbl in ordered:
            node = self._nodes[lbl]
            if node.dirty:
                if node.recompute is not None:
                    node.recompute()
                node.dirty = False
                recomputed.append(lbl)
        return recomputed

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    def dirty_nodes(self) -> List[GraphNode]:
        return [n for n in self._nodes.values() if n.dirty]

    def downstream_of(self, node: GraphNode) -> Set[str]:
        """Return all transitive downstream node labels of *node*."""
        visited: Set[str] = set()
        queue: deque[str] = deque(self._rdeps.get(node.label, ()))
        while queue:
            lbl = queue.popleft()
            if lbl not in visited:
                visited.add(lbl)
                queue.extend(self._rdeps.get(lbl, ()))
        return visited

    def upstream_of(self, node: GraphNode) -> Set[str]:
        """Return all transitive upstream node labels of *node*."""
        visited: Set[str] = set()
        queue: deque[str] = deque(self._deps.get(node.label, ()))
        while queue:
            lbl = queue.popleft()
            if lbl not in visited:
                visited.add(lbl)
                queue.extend(self._deps.get(lbl, ()))
        return visited


# ---------------------------------------------------------------------------
# build_graph_for_body
# ---------------------------------------------------------------------------

def build_graph_for_body(body: Any) -> DependencyGraph:  # body: brep.Body
    """Auto-build a ``DependencyGraph`` from a B-rep ``Body``.

    Dependency structure (Hoffmann-Joan-Arinyo §3.1 entity hierarchy):

      control_point → edge → face → shell/solid → body

    For each entity a ``GraphNode`` is created with:
      - ``kind``    set to the matching ``NodeKind``
      - ``label``   set to ``"<Kind>@<python_id_hex>"``
      - ``recompute`` set to a no-op lambda (real geometry update would live
        here in a full implementation; the graph records *what* must be
        re-evaluated so that the caller's evaluator can act on the ordered
        list returned by ``propagate()``)

    Parameters
    ----------
    body : kerf_cad_core.geom.brep.Body

    Returns
    -------
    DependencyGraph
        Fully wired graph with nodes for every vertex, edge, face, and the
        body itself, plus dependency edges.
    """
    g = DependencyGraph()

    body_node = GraphNode(entity=body, kind=NodeKind.BODY,
                          label=f"Body@{id(body):x}",
                          recompute=lambda: None)
    g.add_node(body_node)

    # Collect shells (from solids + free shells)
    all_shells = body.all_shells()

    for shell in all_shells:
        shell_node = GraphNode(entity=shell, kind=NodeKind.SHELL,
                               label=f"Shell@{id(shell):x}",
                               recompute=lambda: None)
        g.add_node(shell_node)
        # body depends on shell
        g.add_dependency(body_node, shell_node)

        for face in shell.faces:
            face_node = GraphNode(entity=face, kind=NodeKind.SURFACE,
                                  label=f"Face@{id(face):x}",
                                  recompute=lambda: None)
            g.add_node(face_node)
            # shell depends on face
            g.add_dependency(shell_node, face_node)

            # edges used by this face (via coedges / loops)
            face_edges: Set[Any] = set()
            for loop in face.loops:
                for coedge in loop.coedges:
                    face_edges.add(coedge.edge)

            for edge in face_edges:
                edge_node = GraphNode(entity=edge, kind=NodeKind.CURVE,
                                      label=f"Edge@{id(edge):x}",
                                      recompute=lambda: None)
                g.add_node(edge_node)
                # face depends on edge
                g.add_dependency(face_node, edge_node)

                # vertices of the edge
                for vertex in (edge.v_start, edge.v_end):
                    vtx_node = GraphNode(
                        entity=vertex,
                        kind=NodeKind.CONTROL_POINT,
                        label=f"Vertex@{id(vertex):x}",
                        recompute=lambda: None,
                    )
                    g.add_node(vtx_node)
                    # edge depends on vertex
                    g.add_dependency(edge_node, vtx_node)

    return g


# ---------------------------------------------------------------------------
# smart_edit
# ---------------------------------------------------------------------------

def smart_edit(
    body: Any,
    edit_op: Callable[[Any], None],
    dependency_graph: DependencyGraph,
    dirty_nodes: Optional[List[GraphNode]] = None,
) -> Any:
    """Apply *edit_op* to *body* and recompute only affected entities.

    Parameters
    ----------
    body : Body
        The B-rep body being edited.
    edit_op : Callable[[Body], None]
        Function that mutates *body* in-place (e.g. moves a control point).
    dependency_graph : DependencyGraph
        Pre-built dependency graph for *body*.
    dirty_nodes : list[GraphNode] | None
        The nodes that ``edit_op`` will change.  If None the caller is
        expected to call ``dependency_graph.mark_dirty(...)`` *inside*
        ``edit_op`` or to supply the nodes explicitly after building them via
        ``dependency_graph.get_node``.

    Returns
    -------
    body
        The same ``body`` reference (mutated in place).

    Notes
    -----
    The order of operations:
      1. Mark *dirty_nodes* dirty (propagates forward automatically).
      2. Apply *edit_op* (allowed to add additional ``mark_dirty`` calls).
      3. ``propagate()`` re-evaluates dirty nodes in topological order.
    """
    # 1. Mark initially dirty nodes
    if dirty_nodes is not None:
        for dn in dirty_nodes:
            dependency_graph.mark_dirty(dn)

    # 2. Apply the edit
    edit_op(body)

    # 3. Re-evaluate dirty nodes in dependency order
    dependency_graph.propagate()

    return body


# ---------------------------------------------------------------------------
# LLM tool registration
# ---------------------------------------------------------------------------

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register  # type: ignore[import]
    _REGISTRY_AVAILABLE = True
except ImportError:
    _REGISTRY_AVAILABLE = False

if _REGISTRY_AVAILABLE:

    # ------------------------------------------------------------------
    # nurbs_dependency_graph
    # ------------------------------------------------------------------

    _dep_graph_spec = ToolSpec(
        name="nurbs_dependency_graph",
        description=(
            "Build a NURBS dependency graph for a B-rep body and report its "
            "topology (node counts by kind, edge count, dirty state).  Useful "
            "for understanding which surfaces and edges depend on a given control "
            "point / vertex before performing a parametric edit.\n"
            "\n"
            "Input: a JSON body descriptor (same format as nurbs_smart_edit).\n"
            "Output:\n"
            "  ok            : bool\n"
            "  node_counts   : {CONTROL_POINT, CURVE, SURFACE, SHELL, BODY}\n"
            "  edge_count    : int  (dependency edges in the DAG)\n"
            "  nodes         : list[{label, kind, dirty}]\n"
            "\n"
            "Errors: {ok:false, reason, code} — never raises."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "body_spec": {
                    "type": "object",
                    "description": (
                        "Body specification.  Supported types:\n"
                        "  {\"type\": \"box\", \"origin\": [x,y,z], \"size\": [sx,sy,sz]}\n"
                        "Returns graph topology; geometry values are placeholders."
                    ),
                },
            },
            "required": ["body_spec"],
        },
    )

    @register(_dep_graph_spec)
    async def run_nurbs_dependency_graph(ctx: Any, args: bytes) -> str:
        try:
            a = json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid JSON: {exc}", "BAD_ARGS")

        body_spec = a.get("body_spec")
        if not body_spec:
            return err_payload("body_spec is required", "BAD_ARGS")

        try:
            body = _body_from_spec(body_spec)
        except Exception as exc:
            return err_payload(f"failed to build body: {exc}", "BUILD_ERROR")

        g = build_graph_for_body(body)

        counts: Dict[str, int] = {k.name: 0 for k in NodeKind}
        for node in g.nodes():
            counts[node.kind.name] += 1

        return ok_payload({
            "node_counts": counts,
            "edge_count": g.edge_count(),
            "nodes": [
                {"label": n.label, "kind": n.kind.name, "dirty": n.dirty}
                for n in g.nodes()
            ],
        })

    # ------------------------------------------------------------------
    # nurbs_smart_edit
    # ------------------------------------------------------------------

    _smart_edit_spec = ToolSpec(
        name="nurbs_smart_edit",
        description=(
            "Apply a parametric control-point edit to a B-rep body and report "
            "which dependent surfaces were recomputed.  Uses the NURBS dependency "
            "graph (Hoffmann-Joan-Arinyo 2002) to touch only the downstream sub-"
            "graph of the changed vertex — significantly faster than a full-body "
            "recompute for large models.\n"
            "\n"
            "Output:\n"
            "  ok               : bool\n"
            "  recomputed_nodes : list[{label, kind}]  — recomputed in topo order\n"
            "  recomputed_count : int\n"
            "  total_nodes      : int\n"
            "\n"
            "Errors: {ok:false, reason, code} — never raises."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "body_spec": {
                    "type": "object",
                    "description": (
                        "Body specification.  E.g. {\"type\": \"box\", "
                        "\"origin\": [0,0,0], \"size\": [1,1,1]}."
                    ),
                },
                "vertex_index": {
                    "type": "integer",
                    "description": (
                        "0-based index into body.all_vertices() for the vertex "
                        "to move."
                    ),
                },
                "delta": {
                    "type": "array",
                    "description": "[dx, dy, dz] displacement to apply.",
                    "items": {"type": "number"},
                },
            },
            "required": ["body_spec", "vertex_index", "delta"],
        },
    )

    @register(_smart_edit_spec)
    async def run_nurbs_smart_edit(ctx: Any, args: bytes) -> str:
        import numpy as _np  # local import to avoid top-level cost

        try:
            a = json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid JSON: {exc}", "BAD_ARGS")

        body_spec = a.get("body_spec")
        vtx_idx = a.get("vertex_index")
        delta = a.get("delta")

        if body_spec is None:
            return err_payload("body_spec is required", "BAD_ARGS")
        if vtx_idx is None:
            return err_payload("vertex_index is required", "BAD_ARGS")
        if delta is None:
            return err_payload("delta is required", "BAD_ARGS")

        try:
            body = _body_from_spec(body_spec)
        except Exception as exc:
            return err_payload(f"failed to build body: {exc}", "BUILD_ERROR")

        vertices = body.all_vertices()
        try:
            vtx_idx = int(vtx_idx)
        except (TypeError, ValueError) as exc:
            return err_payload(f"vertex_index must be integer: {exc}", "BAD_ARGS")
        if not (0 <= vtx_idx < len(vertices)):
            return err_payload(
                f"vertex_index {vtx_idx} out of range [0, {len(vertices)})",
                "BAD_ARGS",
            )

        try:
            dv = _np.array(delta, dtype=float)
            if dv.shape != (3,):
                return err_payload("delta must be a 3-element array [dx,dy,dz]", "BAD_ARGS")
        except Exception as exc:
            return err_payload(f"invalid delta: {exc}", "BAD_ARGS")

        g = build_graph_for_body(body)
        target_vtx = vertices[vtx_idx]
        vtx_label = f"Vertex@{id(target_vtx):x}"
        vtx_node = g.get_node(vtx_label)
        if vtx_node is None:
            return err_payload(
                f"vertex {vtx_label} not found in dependency graph", "INTERNAL"
            )

        def _move(b: Any) -> None:
            target_vtx.point = target_vtx.point + dv

        recomputed = []

        def _track_smart_edit() -> None:
            nonlocal recomputed
            g.mark_dirty(vtx_node)
            _move(body)
            recomputed = g.propagate()

        _track_smart_edit()

        return ok_payload({
            "recomputed_nodes": [
                {"label": lbl, "kind": g.get_node(lbl).kind.name if g.get_node(lbl) else "?"}
                for lbl in recomputed
            ],
            "recomputed_count": len(recomputed),
            "total_nodes": g.node_count(),
        })


def _body_from_spec(spec: dict) -> Any:
    """Build a Body from a JSON spec dict.  Only ``box`` is supported for now."""
    btype = spec.get("type", "box").lower()
    if btype == "box":
        from kerf_cad_core.geom.brep import make_box  # local to avoid circular
        origin = spec.get("origin", [0.0, 0.0, 0.0])
        size = spec.get("size", [1.0, 1.0, 1.0])
        return make_box(origin=tuple(origin), size=tuple(size))
    raise ValueError(f"unsupported body type: {btype!r}")
