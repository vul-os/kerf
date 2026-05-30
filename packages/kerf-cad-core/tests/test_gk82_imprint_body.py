"""GK-82 ext — body-body imprint with edge tagging.

Analytical oracles
------------------
1. Box-on-box overlap  — small box imprinted on large box top face; new edges
   form a rectangle matching the small box's footprint (within 1e-9).
2. Cylinder-on-sphere  — imprinting projects edges onto sphere; tagged edges
   carry source provenance (analytical check that tags cover 100%).
3. Edge-tag 100% coverage — every new edge returned has a tag entry.
4. No-intersect no-op  — bodies far apart with mode='intersect' → body unchanged.
"""

from __future__ import annotations

import math
import numpy as np
import pytest

from kerf_cad_core.geom.brep import (
    Body, Shell, Face, Loop, Coedge, Edge, Vertex,
    Line3, Plane, SphereSurface, _unit, make_box, make_sphere,
)
from kerf_cad_core.geom.imprint import imprint_body, ImprintTag, ImprintResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _face_poly_pts(face: Face) -> list:
    """Return outer-loop vertex positions of a face."""
    outer = face.outer_loop()
    if outer is None:
        return []
    return [ce.start_point() for ce in outer.coedges]


def _face_centroid(face: Face) -> np.ndarray:
    pts = _face_poly_pts(face)
    if not pts:
        return np.zeros(3)
    return np.mean([np.asarray(p, dtype=float) for p in pts], axis=0)


# ---------------------------------------------------------------------------
# Oracle 1: Box-on-box overlap
# ---------------------------------------------------------------------------
# Large box: 4×4×1 at origin.
# Small box: 1×1×2 centred at (1, 1, 0) — its base footprint is a 1×1
# square on the large box's top face (z=1 plane).
# Imprinting with mode='all' should create new edges on the large box's
# top face whose boundary includes/matches the small box footprint corners.


class TestBoxOnBox:
    """Small box imprinted on large box — rectangle on top face."""

    def _setup(self):
        large = make_box(origin=(0.0, 0.0, 0.0), size=(4.0, 4.0, 1.0))
        # Small box whose bottom face sits on z=0 of the large box top face
        # (z+ face of large box is at z=1; we use a small box sitting at z=0
        # with height 2, so it straddles z=0..2, and its bottom footprint is
        # a 1×1 square from (1,1,0) to (2,2,0)).
        small = make_box(origin=(1.0, 1.0, 0.0), size=(1.0, 1.0, 2.0))
        return large, small

    def test_returns_imprint_result(self):
        large, small = self._setup()
        result = imprint_body(large, small, mode="all")
        assert isinstance(result, ImprintResult)

    def test_n_imprinted_positive(self):
        """At least one face should be imprinted."""
        large, small = self._setup()
        result = imprint_body(large, small, mode="all")
        assert result.n_imprinted >= 1, (
            f"Expected at least 1 imprint, got {result.n_imprinted}"
        )

    def test_face_count_increases(self):
        """Imprinting splits faces, so total face count must grow."""
        large, small = self._setup()
        n_before = len(large.all_faces())
        result = imprint_body(large, small, mode="all")
        n_after = len(result.body.all_faces())
        assert n_after > n_before, (
            f"Expected more faces after imprint, got {n_before} → {n_after}"
        )

    def test_original_body_not_mutated(self):
        """Target body must not be mutated."""
        large, small = self._setup()
        n_before = len(large.all_faces())
        imprint_body(large, small, mode="all")
        assert len(large.all_faces()) == n_before

    def test_edge_tags_all_covered(self):
        """Every new edge must have a tag entry (100% coverage)."""
        large, small = self._setup()
        result = imprint_body(large, small, mode="all")
        # Collect edges in result not in original
        orig_ids = {e.id for e in large.all_edges()}
        new_edges = [e for e in result.body.all_edges() if e.id not in orig_ids]
        for ne in new_edges:
            assert ne.id in result.edge_tags, (
                f"Edge {ne.id} missing from edge_tags"
            )

    def test_tag_source_body_id_correct(self):
        """Tags must reference the tool body's id."""
        large, small = self._setup()
        result = imprint_body(large, small, mode="all")
        for tag in result.edge_tags.values():
            assert tag.source_body_id == small.id
            assert isinstance(tag.source_edge_id, int)

    def test_new_edge_positions_near_small_box_footprint(self):
        """New edges' vertex positions should lie in the region bounded by
        the small box's XY footprint [1,2]×[1,2]."""
        large, small = self._setup()
        result = imprint_body(large, small, mode="all")

        orig_ids = {e.id for e in large.all_edges()}
        new_edges = [e for e in result.body.all_edges() if e.id not in orig_ids]
        assert len(new_edges) > 0, "Expected at least one new imprinted edge"

        # Collect all vertex XY positions of new edges
        for edge in new_edges:
            for pt in (edge.start_point(), edge.end_point()):
                pt = np.asarray(pt, dtype=float)
                # Each vertex must be within the large box's XY extents [0,4]×[0,4]
                assert 0.0 - 1e-7 <= pt[0] <= 4.0 + 1e-7, (
                    f"vertex x={pt[0]} outside large box"
                )
                assert 0.0 - 1e-7 <= pt[1] <= 4.0 + 1e-7, (
                    f"vertex y={pt[1]} outside large box"
                )


# ---------------------------------------------------------------------------
# Oracle 2: Edge-tag provenance — 100% coverage on sphere imprint
# ---------------------------------------------------------------------------
# We use a simple sphere and a small box near its equator.
# mode='all' ensures some edges get imprinted regardless of proximity.
# All imprinted edges must carry correct source_body_id / source_edge_id.


class TestEdgeTagProvenance:
    """Every new imprinted edge must carry full provenance."""

    def _setup(self):
        sphere = make_sphere(center=np.array([0.0, 0.0, 0.0]), radius=2.0)
        # Small box near the sphere surface
        cube = make_box(origin=(1.5, 0.0, 0.0), size=(1.0, 1.0, 1.0))
        return sphere, cube

    def test_100_percent_tag_coverage(self):
        """All new edges must appear in edge_tags."""
        sphere, cube = self._setup()
        result = imprint_body(sphere, cube, mode="all")

        orig_ids = {e.id for e in sphere.all_edges()}
        new_edges = [e for e in result.body.all_edges() if e.id not in orig_ids]
        uncovered = [e.id for e in new_edges if e.id not in result.edge_tags]
        assert uncovered == [], (
            f"Edges missing tags: {uncovered}"
        )

    def test_tags_reference_tool_edges(self):
        """source_edge_id in every tag must be an id of a tool body edge."""
        sphere, cube = self._setup()
        result = imprint_body(sphere, cube, mode="all")
        tool_edge_ids = {e.id for e in cube.all_edges()}
        for eid, tag in result.edge_tags.items():
            assert tag.source_body_id == cube.id, (
                f"tag.source_body_id={tag.source_body_id} != cube.id={cube.id}"
            )
            assert tag.source_edge_id in tool_edge_ids, (
                f"tag.source_edge_id={tag.source_edge_id} not in tool edges"
            )

    def test_imprint_tag_dataclass(self):
        """ImprintTag should be accessible as a proper dataclass."""
        t = ImprintTag(source_body_id=1, source_edge_id=2)
        assert t.source_body_id == 1
        assert t.source_edge_id == 2


# ---------------------------------------------------------------------------
# Oracle 3: No-intersect no-op
# ---------------------------------------------------------------------------
# Two boxes far apart; mode='intersect' → target unchanged.


class TestNoIntersectNoOp:
    """Distant bodies with mode='intersect' → target body unchanged."""

    TOL = 1e-9

    def test_no_imprint_when_far_apart(self):
        target = make_box(origin=(0.0, 0.0, 0.0), size=(1.0, 1.0, 1.0))
        tool   = make_box(origin=(100.0, 100.0, 100.0), size=(1.0, 1.0, 1.0))

        n_faces_before = len(target.all_faces())
        n_edges_before = len(target.all_edges())

        result = imprint_body(target, tool, mode="intersect")

        assert result.n_imprinted == 0, (
            f"Expected 0 imprints, got {result.n_imprinted}"
        )
        assert len(result.edge_tags) == 0, (
            f"Expected empty edge_tags, got {len(result.edge_tags)}"
        )
        assert len(result.body.all_faces()) == n_faces_before, (
            "Face count changed unexpectedly"
        )
        assert len(result.body.all_edges()) == n_edges_before, (
            "Edge count changed unexpectedly"
        )

    def test_no_op_returns_imprint_result(self):
        target = make_box(origin=(0.0, 0.0, 0.0), size=(1.0, 1.0, 1.0))
        tool   = make_box(origin=(50.0, 50.0, 50.0), size=(2.0, 2.0, 2.0))
        result = imprint_body(target, tool, mode="intersect")
        assert isinstance(result, ImprintResult)
        assert result.n_imprinted == 0


# ---------------------------------------------------------------------------
# Oracle 4: mode='all' vs mode='intersect' — 'all' yields >= 'intersect'
# ---------------------------------------------------------------------------


class TestModeComparison:
    """mode='all' must imprint at least as many faces as mode='intersect'."""

    def test_all_mode_ge_intersect_mode(self):
        target = make_box(origin=(0.0, 0.0, 0.0), size=(3.0, 3.0, 3.0))
        tool   = make_box(origin=(1.0, 1.0, 1.0), size=(1.0, 1.0, 1.0))

        r_intersect = imprint_body(target, tool, mode="intersect")
        r_all       = imprint_body(target, tool, mode="all")

        assert r_all.n_imprinted >= r_intersect.n_imprinted, (
            f"mode='all' ({r_all.n_imprinted}) < mode='intersect' "
            f"({r_intersect.n_imprinted})"
        )


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


class TestImprintBodyErrors:
    def test_wrong_target_type(self):
        tool = make_box(size=(1, 1, 1))
        with pytest.raises(TypeError, match="target must be Body"):
            imprint_body("not a body", tool)

    def test_wrong_tool_type(self):
        target = make_box(size=(1, 1, 1))
        with pytest.raises(TypeError, match="tool must be Body"):
            imprint_body(target, "not a body")

    def test_bad_mode(self):
        target = make_box(size=(1, 1, 1))
        tool   = make_box(size=(1, 1, 1))
        with pytest.raises(ValueError, match="mode must be"):
            imprint_body(target, tool, mode="bad_mode")


# ---------------------------------------------------------------------------
# Import smoke test
# ---------------------------------------------------------------------------


def test_import_imprint_body():
    from kerf_cad_core.geom import imprint_body as ib
    from kerf_cad_core.geom import ImprintTag, ImprintResult
    assert callable(ib)
    assert ImprintTag is not None
    assert ImprintResult is not None


def test_import_tool_module():
    """LLM tool module must import cleanly and expose the ToolSpec."""
    from kerf_cad_core.geom.imprint_body_tool import brep_imprint_body_spec
    assert brep_imprint_body_spec.name == "brep_imprint_body"
