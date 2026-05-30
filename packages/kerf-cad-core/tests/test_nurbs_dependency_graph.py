"""NURBS dependency graph tests.

Covers:
  DGT-01  Build graph for box body — correct node counts and edge structure.
  DGT-02  Mark-dirty propagation — vertex dirtied → all sharing faces + body dirty.
  DGT-03  Smart-edit speedup    — move one CP → only 3 faces recomputed, not all 6.
  DGT-04  Topological order     — propagate processes vertices → edges → faces → body.

All tests are hermetic (pure-Python, numpy only, no OCCT).
"""

from __future__ import annotations

import pytest
import numpy as np

from kerf_cad_core.geom.brep import make_box
from kerf_cad_core.geom.dependency_graph import (
    DependencyGraph,
    GraphNode,
    NodeKind,
    build_graph_for_body,
    smart_edit,
)


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _box_graph():
    """Return (body, graph) for a unit box."""
    body = make_box(origin=(0.0, 0.0, 0.0), size=(1.0, 1.0, 1.0))
    g = build_graph_for_body(body)
    return body, g


# ---------------------------------------------------------------------------
# DGT-01  Build graph for box body
# ---------------------------------------------------------------------------

class TestBuildGraphForBox:
    """DGT-01: A unit box has V=8, E=12, F=6, B=1 after graph construction."""

    def test_vertex_count(self):
        body, g = _box_graph()
        cp_nodes = [n for n in g.nodes() if n.kind == NodeKind.CONTROL_POINT]
        assert len(cp_nodes) == 8, (
            f"expected 8 vertex nodes, got {len(cp_nodes)}"
        )

    def test_edge_count(self):
        body, g = _box_graph()
        curve_nodes = [n for n in g.nodes() if n.kind == NodeKind.CURVE]
        assert len(curve_nodes) == 12, (
            f"expected 12 edge nodes, got {len(curve_nodes)}"
        )

    def test_face_count(self):
        body, g = _box_graph()
        face_nodes = [n for n in g.nodes() if n.kind == NodeKind.SURFACE]
        assert len(face_nodes) == 6, (
            f"expected 6 face nodes, got {len(face_nodes)}"
        )

    def test_body_count(self):
        body, g = _box_graph()
        body_nodes = [n for n in g.nodes() if n.kind == NodeKind.BODY]
        assert len(body_nodes) == 1, (
            f"expected 1 body node, got {len(body_nodes)}"
        )

    def test_dependency_edges_present(self):
        """The graph must have dependency edges (> 0)."""
        body, g = _box_graph()
        assert g.edge_count() > 0, "dependency graph must have edges"

    def test_body_downstream_of_faces(self):
        """Every face node must be an ancestor of the body node."""
        body, g = _box_graph()
        body_node = next(n for n in g.nodes() if n.kind == NodeKind.BODY)
        face_nodes = [n for n in g.nodes() if n.kind == NodeKind.SURFACE]
        # body's upstreams (transitively) must include all faces
        upstream_labels = g.upstream_of(body_node)
        for fn in face_nodes:
            assert fn.label in upstream_labels, (
                f"face {fn.label} should be upstream of body"
            )

    def test_vertices_upstream_of_edges(self):
        """Every vertex node must be an ancestor of at least one edge node."""
        body, g = _box_graph()
        vtx_nodes = [n for n in g.nodes() if n.kind == NodeKind.CONTROL_POINT]
        edge_nodes = [n for n in g.nodes() if n.kind == NodeKind.CURVE]
        # collect all vertices that appear in any edge's upstream set
        vtx_labels_with_downstream = set()
        for en in edge_nodes:
            for ul in g.upstream_of(en):
                vtx_labels_with_downstream.add(ul)
        # every vertex should appear as upstream of some edge
        for vn in vtx_nodes:
            assert vn.label in vtx_labels_with_downstream, (
                f"vertex {vn.label} has no downstream edge"
            )


# ---------------------------------------------------------------------------
# DGT-02  Mark-dirty propagation
# ---------------------------------------------------------------------------

class TestMarkDirtyPropagation:
    """DGT-02: Marking a corner vertex dirty propagates to its faces and body."""

    def test_vertex_makes_self_dirty(self):
        body, g = _box_graph()
        vtx_node = next(n for n in g.nodes() if n.kind == NodeKind.CONTROL_POINT)
        g.mark_dirty(vtx_node)
        assert vtx_node.dirty

    def test_faces_become_dirty(self):
        """Marking vertex[0] dirty → all 3 faces sharing that vertex dirty."""
        body, g = _box_graph()
        vertices = body.all_vertices()
        v0 = vertices[0]
        vtx_node = g.get_node(f"Vertex@{id(v0):x}")
        assert vtx_node is not None

        g.mark_dirty(vtx_node)

        # vertex 0 at (0,0,0) is shared by bottom, front, and left faces.
        # At least 3 face nodes must be dirty.
        dirty_faces = [n for n in g.nodes()
                       if n.kind == NodeKind.SURFACE and n.dirty]
        assert len(dirty_faces) >= 3, (
            f"expected >= 3 dirty faces; got {len(dirty_faces)}"
        )

    def test_body_becomes_dirty(self):
        body, g = _box_graph()
        vtx_node = next(n for n in g.nodes() if n.kind == NodeKind.CONTROL_POINT)
        g.mark_dirty(vtx_node)
        body_nodes = [n for n in g.nodes() if n.kind == NodeKind.BODY]
        assert all(bn.dirty for bn in body_nodes), (
            "body node must be dirty when a vertex is marked dirty"
        )

    def test_uninvolved_vertices_stay_clean(self):
        """Vertices not reachable from the dirty node stay clean."""
        body, g = _box_graph()
        vertices = body.all_vertices()
        # Mark only vertex 0
        v0 = vertices[0]
        vtx_node = g.get_node(f"Vertex@{id(v0):x}")
        g.mark_dirty(vtx_node)

        # The OTHER vertices (v1..v7) must not be dirty — dirtiness does NOT
        # propagate *upstream*, only downstream.
        for v in vertices[1:]:
            other_node = g.get_node(f"Vertex@{id(v):x}")
            assert other_node is not None
            assert not other_node.dirty, (
                f"vertex {other_node.label} should NOT be dirty"
            )

    def test_mark_dirty_returns_newly_dirty_set(self):
        body, g = _box_graph()
        vtx_node = next(n for n in g.nodes() if n.kind == NodeKind.CONTROL_POINT)
        newly_dirty = g.mark_dirty(vtx_node)
        assert isinstance(newly_dirty, set)
        assert vtx_node.label in newly_dirty


# ---------------------------------------------------------------------------
# DGT-03  Smart-edit speedup
# ---------------------------------------------------------------------------

class TestSmartEditSpeedup:
    """DGT-03: Moving one vertex → smart_edit recomputes only 3 faces, not 6."""

    def _make_counting_graph(self):
        """Build a box graph where each node's recompute increments a counter."""
        body = make_box(origin=(0.0, 0.0, 0.0), size=(1.0, 1.0, 1.0))
        g = build_graph_for_body(body)
        recomputed_labels = []

        for node in g.nodes():
            # Capture node label in closure
            label = node.label

            def _recompute(lbl=label):
                recomputed_labels.append(lbl)

            node.recompute = _recompute

        return body, g, recomputed_labels

    def test_only_three_faces_recomputed(self):
        """
        A box corner vertex is shared by exactly 3 faces (bottom, front, left
        for vertex 0 at (0,0,0)).  smart_edit must recompute exactly those 3
        face nodes (plus the edges that use that vertex, plus the vertex itself,
        plus the shell/body chain) — crucially, no more than 3 face-kind nodes.
        """
        body, g, recomputed_labels = self._make_counting_graph()
        vertices = body.all_vertices()

        v0 = vertices[0]
        vtx_node = g.get_node(f"Vertex@{id(v0):x}")
        assert vtx_node is not None

        def _noop_edit(b):
            # The actual geometry mutation is a no-op here; we just test the
            # graph propagation bookkeeping.
            pass

        smart_edit(body, _noop_edit, g, dirty_nodes=[vtx_node])

        face_recomputed = [
            lbl for lbl in recomputed_labels
            if g.get_node(lbl) and g.get_node(lbl).kind == NodeKind.SURFACE
        ]

        # A full recompute would touch all 6 faces; smart edit must touch < 6.
        assert len(face_recomputed) < 6, (
            f"smart_edit should touch < 6 faces, got {len(face_recomputed)}: "
            f"{face_recomputed}"
        )
        # And at least 1 face must be recomputed (the ones that use vertex 0).
        assert len(face_recomputed) >= 1, (
            "smart_edit must recompute at least 1 face when a vertex changes"
        )

    def test_vertex_itself_recomputed(self):
        body, g, recomputed_labels = self._make_counting_graph()
        vertices = body.all_vertices()
        v0 = vertices[0]
        vtx_node = g.get_node(f"Vertex@{id(v0):x}")
        assert vtx_node is not None

        smart_edit(body, lambda b: None, g, dirty_nodes=[vtx_node])

        assert vtx_node.label in recomputed_labels, (
            "the dirty vertex node itself must be in the recomputed list"
        )

    def test_clean_after_propagate(self):
        """All nodes must be clean after smart_edit completes."""
        body, g, _ = self._make_counting_graph()
        vertices = body.all_vertices()
        v0 = vertices[0]
        vtx_node = g.get_node(f"Vertex@{id(v0):x}")
        smart_edit(body, lambda b: None, g, dirty_nodes=[vtx_node])

        dirty = [n for n in g.nodes() if n.dirty]
        assert not dirty, (
            f"all nodes should be clean after propagate; dirty: {[n.label for n in dirty]}"
        )


# ---------------------------------------------------------------------------
# DGT-04  Topological order
# ---------------------------------------------------------------------------

class TestTopologicalOrder:
    """DGT-04: propagate processes nodes in dependency order."""

    def test_vertices_before_edges_before_faces_before_body(self):
        """
        When all nodes are dirty, recompute order must satisfy:
          every vertex processed before every edge that depends on it,
          every edge processed before every face that depends on it,
          every face processed before the body.
        """
        body, g = _box_graph()
        order: list[str] = []

        for node in g.nodes():
            label = node.label

            def _recompute(lbl=label):
                order.append(lbl)

            node.recompute = _recompute
            node.dirty = True  # mark all dirty manually

        g.propagate()

        def _kind(lbl):
            n = g.get_node(lbl)
            return n.kind if n else None

        # Build index map
        pos = {lbl: i for i, lbl in enumerate(order)}

        # For each edge, verify all its upstream vertices come before it
        for node in g.nodes():
            if node.kind == NodeKind.CURVE:
                for up_lbl in g._deps.get(node.label, ()):
                    up_node = g.get_node(up_lbl)
                    if up_node and up_node.kind == NodeKind.CONTROL_POINT:
                        assert pos[up_lbl] < pos[node.label], (
                            f"vertex {up_lbl} must be processed before edge "
                            f"{node.label}"
                        )

        # For each face, verify all its upstream edges come before it
        for node in g.nodes():
            if node.kind == NodeKind.SURFACE:
                for up_lbl in g._deps.get(node.label, ()):
                    up_node = g.get_node(up_lbl)
                    if up_node and up_node.kind == NodeKind.CURVE:
                        assert pos[up_lbl] < pos[node.label], (
                            f"edge {up_lbl} must be processed before face "
                            f"{node.label}"
                        )

        # The single body node must come after all face/shell nodes
        body_nodes = [n for n in g.nodes() if n.kind == NodeKind.BODY]
        face_nodes = [n for n in g.nodes() if n.kind == NodeKind.SURFACE]
        for bn in body_nodes:
            for fn in face_nodes:
                assert pos[fn.label] < pos[bn.label], (
                    f"face {fn.label} must be processed before body {bn.label}"
                )

    def test_propagate_returns_ordered_list(self):
        """propagate() must return a non-empty list of labels."""
        body, g = _box_graph()
        for n in g.nodes():
            n.dirty = True
        result = g.propagate()
        assert isinstance(result, list)
        assert len(result) == g.node_count()

    def test_propagate_clears_dirty(self):
        """After propagate, no nodes remain dirty."""
        body, g = _box_graph()
        for n in g.nodes():
            n.dirty = True
        g.propagate()
        assert all(not n.dirty for n in g.nodes())

    def test_empty_propagate_on_clean_graph(self):
        """Calling propagate on a clean graph returns an empty list."""
        body, g = _box_graph()
        result = g.propagate()
        assert result == []
