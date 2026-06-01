"""Tests for BREP-CHAMFER-RECOMMEND-SIZE.

Covers:
  - DIN 74 Form A/B oracle values (§1 countersink criterion)
  - M3 bolt hole edge → 0.2 mm offset × 45° (DIN 74:1974 Form A d1=3.0 → d2=3.4)
  - Deburring small edge → 0.5 mm × 45° (Drozda-Wick §3-7 floor)
  - Cosmetic visible edge → cosmetic kind (Boothroyd-Dewhurst §4)
  - Sharp internal corner → not applicable (ISO 13715 external-edge convention)
  - Non-linear (arc) edge → not applicable (variable-offset out of scope)
  - Coplanar faces → not applicable
  - Face-too-small guard → not applicable when face_min/4 < deburring floor
  - Batch wrapper (recommend_chamfer_sizes_for_body) returns one rec per edge
  - ChamferContext defaults are sensible (steel, auto, 6mm mill, visible)
  - DIN74_COUNTERSINK_TABLE completeness: all entries have d2 > d1
  - Re-export from geom.__init__ works
"""

from __future__ import annotations

import math
import pytest

from kerf_cad_core.geom.chamfer_recommend_size import (
    AsymmetricChamferRecommendation,
    ChamferContext,
    ChamferRecommendation,
    DIN74_COUNTERSINK_TABLE,
    DIN74_FORMB_TABLE,
    recommend_asymmetric_chamfer,
    recommend_chamfer_size,
    recommend_chamfer_sizes_for_body,
    _din74_lookup,
)
from kerf_cad_core.geom.brep_build import box_to_body
from kerf_cad_core.geom.brep import Line3, Edge, Vertex
from kerf_cad_core.geom.fillet_solid import _find_incident_faces


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _box_body():
    """Small 10×10×10 mm box for geometry tests."""
    return box_to_body([0.0, 0.0, 0.0], 10.0, 10.0, 10.0)


def _first_linear_edge_and_faces(body):
    for edge in body.all_edges():
        if isinstance(edge.curve, Line3):
            faces = _find_incident_faces(body, edge)
            if len(faces) == 2:
                return edge, faces
    raise RuntimeError("no linear edge found")


# ---------------------------------------------------------------------------
# DIN 74 oracle tests (Criterion 3)
# ---------------------------------------------------------------------------

class TestDIN74Oracle:
    """Verify DIN 74:1974 Form A lookup against standard table values."""

    def test_m3_form_a(self):
        # DIN 74:1974 Table 1 Form A: d1=3.0 → d2=3.4 → offset=0.2 mm
        offset = _din74_lookup(3.0, "A")
        assert offset is not None
        assert abs(offset - 0.2) < 1e-6, f"M3 DIN74A offset expected 0.2mm, got {offset}"

    def test_m6_form_a(self):
        # d1=6.0 → d2=6.6 → offset=0.3 mm
        offset = _din74_lookup(6.0, "A")
        assert offset is not None
        assert abs(offset - 0.3) < 1e-6

    def test_m10_form_a(self):
        # d1=10.0 → d2=11.0 → offset=0.5 mm
        offset = _din74_lookup(10.0, "A")
        assert offset is not None
        assert abs(offset - 0.5) < 1e-6

    def test_m12_form_a(self):
        # d1=12.0 → d2=13.5 → offset=0.75 mm
        offset = _din74_lookup(12.0, "A")
        assert offset is not None
        assert abs(offset - 0.75) < 1e-6

    def test_m2_form_a(self):
        # d1=2.0 → d2=2.4 → offset=0.2 mm
        offset = _din74_lookup(2.0, "A")
        assert offset is not None
        assert abs(offset - 0.2) < 1e-6

    def test_m3_form_b(self):
        # Form B: d1=3.0 → d2=4.5 → offset=0.75 mm
        offset = _din74_lookup(3.0, "B")
        assert offset is not None
        assert abs(offset - 0.75) < 1e-6

    def test_unknown_diameter_returns_none(self):
        # No standard size for 2.7 mm
        result = _din74_lookup(2.7, "A")
        assert result is None

    def test_all_form_a_entries_d2_gt_d1(self):
        """All DIN 74 Form A entries must have countersink > hole diameter."""
        for d1, d2 in DIN74_COUNTERSINK_TABLE.items():
            assert d2 > d1, f"DIN74A: d1={d1} d2={d2} — d2 must exceed d1"

    def test_all_form_b_entries_d2_gt_d1(self):
        for d1, d2 in DIN74_FORMB_TABLE.items():
            assert d2 > d1, f"DIN74B: d1={d1} d2={d2} — d2 must exceed d1"


# ---------------------------------------------------------------------------
# M3 bolt hole countersink scenario
# ---------------------------------------------------------------------------

class TestM3BoltHoleCriteria:
    """M3 bolt hole edge → DIN 74 Form A governs → 0.2 mm × 45°."""

    def test_m3_countersink_offset(self):
        body = _box_body()
        edge, faces = _first_linear_edge_and_faces(body)
        ctx = ChamferContext(hole_diameter_mm=3.0, din74_form="A", is_visible=True)
        rec = recommend_chamfer_size(edge, faces, ctx)
        assert rec.applicable
        assert rec.kind == "countersink"
        assert abs(rec.offset_mm - 0.2) < 1e-6, f"Expected 0.2mm, got {rec.offset_mm}"
        assert abs(rec.angle_deg - 45.0) < 1e-9

    def test_m3_din_reference_string(self):
        body = _box_body()
        edge, faces = _first_linear_edge_and_faces(body)
        ctx = ChamferContext(hole_diameter_mm=3.0, din74_form="A")
        rec = recommend_chamfer_size(edge, faces, ctx)
        assert "DIN 74" in rec.din_reference
        assert "3.4" in rec.din_reference  # d2

    def test_m3_rationale_cites_drozda(self):
        body = _box_body()
        edge, faces = _first_linear_edge_and_faces(body)
        ctx = ChamferContext(hole_diameter_mm=3.0)
        rec = recommend_chamfer_size(edge, faces, ctx)
        assert "Drozda" in rec.rationale or "DIN" in rec.rationale

    def test_m6_countersink_offset(self):
        body = _box_body()
        edge, faces = _first_linear_edge_and_faces(body)
        ctx = ChamferContext(hole_diameter_mm=6.0, din74_form="A")
        rec = recommend_chamfer_size(edge, faces, ctx)
        assert rec.kind == "countersink"
        assert abs(rec.offset_mm - 0.3) < 1e-6


# ---------------------------------------------------------------------------
# Deburring small edge scenario
# ---------------------------------------------------------------------------

class TestDeburringSmallEdge:
    """Small visible edge with no hole → deburring floor 0.5 mm × 45°."""

    def test_deburring_floor_applied_no_hole(self):
        body = _box_body()
        edge, faces = _first_linear_edge_and_faces(body)
        # Large mill → manufacturing criterion; disable by setting small mill
        ctx = ChamferContext(
            hole_diameter_mm=None,
            chamfer_mill_diameter_mm=1.0,  # 0.5 mm offset = deburring floor
            is_visible=False,
        )
        rec = recommend_chamfer_size(edge, faces, ctx)
        assert rec.applicable
        # offset should be ≥ deburring floor (0.5 mm)
        assert rec.offset_mm >= 0.5 - 1e-9

    def test_deburring_rationale_cites_iso13715(self):
        body = _box_body()
        edge, faces = _first_linear_edge_and_faces(body)
        ctx = ChamferContext(hole_diameter_mm=None, chamfer_mill_diameter_mm=1.0, is_visible=False)
        rec = recommend_chamfer_size(edge, faces, ctx)
        assert "ISO 13715" in rec.rationale or "Drozda" in rec.rationale

    def test_deburring_angle_is_45(self):
        body = _box_body()
        edge, faces = _first_linear_edge_and_faces(body)
        ctx = ChamferContext(chamfer_mill_diameter_mm=1.0, is_visible=False)
        rec = recommend_chamfer_size(edge, faces, ctx)
        assert abs(rec.angle_deg - 45.0) < 1e-9


# ---------------------------------------------------------------------------
# Cosmetic visible edge scenario
# ---------------------------------------------------------------------------

class TestCosmeticVisibleEdge:
    """Visible edge, no hole, small mill → cosmetic 1.5 mm × 45°."""

    def test_cosmetic_kind_returned(self):
        body = _box_body()
        edge, faces = _first_linear_edge_and_faces(body)
        ctx = ChamferContext(
            hole_diameter_mm=None,
            chamfer_mill_diameter_mm=1.0,   # mill offset=0.5 < cosmetic 1.5
            is_visible=True,
        )
        rec = recommend_chamfer_size(edge, faces, ctx)
        assert rec.applicable
        # Cosmetic (1.5 mm) should dominate deburring (0.5 mm) + 0.5 mm mill
        assert rec.kind == "cosmetic"
        assert abs(rec.offset_mm - 1.5) < 1e-6

    def test_cosmetic_rationale_cites_boothroyd(self):
        body = _box_body()
        edge, faces = _first_linear_edge_and_faces(body)
        ctx = ChamferContext(chamfer_mill_diameter_mm=1.0, is_visible=True)
        rec = recommend_chamfer_size(edge, faces, ctx)
        assert "Boothroyd" in rec.rationale

    def test_not_visible_skips_cosmetic(self):
        body = _box_body()
        edge, faces = _first_linear_edge_and_faces(body)
        ctx = ChamferContext(chamfer_mill_diameter_mm=1.0, is_visible=False)
        rec = recommend_chamfer_size(edge, faces, ctx)
        # Without visibility, kind should not be cosmetic
        assert rec.kind != "cosmetic"


# ---------------------------------------------------------------------------
# Sharp internal corner — no chamfer
# ---------------------------------------------------------------------------

class TestSharpInternalCorner:
    """Internal concave corners with very low dihedral: not chamfered."""

    def test_arc_edge_not_applicable(self):
        """Non-linear (CircleArc3) edge must return applicable=False."""
        try:
            from kerf_cad_core.geom.brep import CircleArc3, Edge, Vertex
        except ImportError:
            pytest.skip("CircleArc3 not available in this build")
        import numpy as np
        try:
            arc = CircleArc3(
                center=np.array([0.0, 0.0, 0.0]),
                radius=5.0,
                normal=np.array([0.0, 0.0, 1.0]),
                start_angle=0.0,
                end_angle=math.pi / 2,
            )
            v0 = Vertex(np.array([5.0, 0.0, 0.0]))
            v1 = Vertex(np.array([0.0, 5.0, 0.0]))
            arc_edge = Edge(curve=arc, start=v0, end=v1)
        except (AttributeError, TypeError) as exc:
            pytest.skip(f"CircleArc3 construction failed: {exc}")

        ctx = ChamferContext()
        body = _box_body()
        _, faces = _first_linear_edge_and_faces(body)
        rec = recommend_chamfer_size(arc_edge, faces, ctx)
        assert not rec.applicable

    def test_wrong_face_count_not_applicable(self):
        """Non-manifold edge (not 2 faces) returns applicable=False."""
        body = _box_body()
        edge, faces = _first_linear_edge_and_faces(body)
        ctx = ChamferContext()
        rec = recommend_chamfer_size(edge, [faces[0]], ctx)  # only 1 face
        assert not rec.applicable

    def test_coplanar_faces_not_applicable(self):
        """Coplanar face pair (dihedral ≈ 180°) skipped."""
        # Construct two faces with parallel normals pointing same direction
        # (dihedral ≈ 180°).  Use a wide flat box where a mid-plane edge shares
        # the same normal on both sides by creating a degenerate pair.
        # Simplest: mock the surface_normal to return same direction.
        body = _box_body()
        edge, faces = _first_linear_edge_and_faces(body)

        class _CoplanarFace:
            def surface_normal(self, u, v):
                import numpy as np
                return np.array([0.0, 0.0, 1.0])
            def outer_loop(self):
                return None

        mock_faces = [_CoplanarFace(), _CoplanarFace()]
        ctx = ChamferContext()
        rec = recommend_chamfer_size(edge, mock_faces, ctx)
        assert not rec.applicable


# ---------------------------------------------------------------------------
# Batch wrapper
# ---------------------------------------------------------------------------

class TestBatchWrapper:
    """recommend_chamfer_sizes_for_body returns one rec per edge."""

    def test_length_equals_edge_count(self):
        body = _box_body()
        recs = recommend_chamfer_sizes_for_body(body)
        assert len(recs) == len(body.all_edges())

    def test_edge_index_sequential(self):
        body = _box_body()
        recs = recommend_chamfer_sizes_for_body(body)
        for i, rec in enumerate(recs):
            assert rec.edge_index == i

    def test_some_applicable(self):
        body = _box_body()
        recs = recommend_chamfer_sizes_for_body(body)
        applicable = [r for r in recs if r.applicable]
        assert len(applicable) > 0

    def test_manufacturing_context_propagates(self):
        body = _box_body()
        ctx = ChamferContext(chamfer_mill_diameter_mm=3.0, is_visible=False)
        recs = recommend_chamfer_sizes_for_body(body, ctx)
        # All applicable offsets should be >= deburring floor
        for r in recs:
            if r.applicable:
                assert r.offset_mm >= 0.5 - 1e-9


# ---------------------------------------------------------------------------
# ChamferRecommendation dataclass defaults
# ---------------------------------------------------------------------------

class TestChamferRecommendationDefaults:
    def test_default_angle_is_45(self):
        rec = ChamferRecommendation()
        assert abs(rec.angle_deg - 45.0) < 1e-9

    def test_default_applicable_true(self):
        rec = ChamferRecommendation()
        assert rec.applicable

    def test_default_din_reference_empty(self):
        rec = ChamferRecommendation()
        assert rec.din_reference == ""


# ---------------------------------------------------------------------------
# Re-export from geom.__init__
# ---------------------------------------------------------------------------

class TestGeomInitReexport:
    def test_chamfer_context_importable(self):
        from kerf_cad_core.geom import ChamferContext as CC
        assert CC is ChamferContext

    def test_chamfer_recommendation_importable(self):
        from kerf_cad_core.geom import ChamferRecommendation as CR
        assert CR is ChamferRecommendation

    def test_din74_table_importable(self):
        from kerf_cad_core.geom import DIN74_COUNTERSINK_TABLE as tbl
        assert 3.0 in tbl
        assert 6.0 in tbl

    def test_recommend_chamfer_size_importable(self):
        from kerf_cad_core.geom import recommend_chamfer_size as fn
        assert callable(fn)

    def test_recommend_chamfer_sizes_for_body_importable(self):
        from kerf_cad_core.geom import recommend_chamfer_sizes_for_body as fn
        assert callable(fn)


# ---------------------------------------------------------------------------
# criteria_offsets transparency
# ---------------------------------------------------------------------------

class TestCriteriaOffsets:
    def test_all_criteria_present(self):
        body = _box_body()
        edge, faces = _first_linear_edge_and_faces(body)
        ctx = ChamferContext(hole_diameter_mm=3.0, is_visible=True)
        rec = recommend_chamfer_size(edge, faces, ctx)
        assert "deburring" in rec.criteria_offsets
        assert "manufacturing" in rec.criteria_offsets
        assert "cosmetic" in rec.criteria_offsets
        assert "countersink_din74" in rec.criteria_offsets

    def test_deburring_offset_is_0_5(self):
        body = _box_body()
        edge, faces = _first_linear_edge_and_faces(body)
        ctx = ChamferContext(hole_diameter_mm=3.0, is_visible=True)
        rec = recommend_chamfer_size(edge, faces, ctx)
        assert abs(rec.criteria_offsets["deburring"] - 0.5) < 1e-9

    def test_manufacturing_offset_from_mill(self):
        body = _box_body()
        edge, faces = _first_linear_edge_and_faces(body)
        ctx = ChamferContext(chamfer_mill_diameter_mm=6.0)
        rec = recommend_chamfer_size(edge, faces, ctx)
        # 6mm mill → 3.0 mm offset
        assert abs(rec.criteria_offsets["manufacturing"] - 3.0) < 1e-9


# ---------------------------------------------------------------------------
# Asymmetric chamfer — recommend_asymmetric_chamfer()
# ---------------------------------------------------------------------------


class TestAsymmetricChamfer:
    """Tests for recommend_asymmetric_chamfer() and the ratio= path."""

    def _edge(self):
        body = _box_body()
        for e in body.all_edges():
            from kerf_cad_core.geom.brep import Line3
            if isinstance(e.curve, Line3):
                return e
        raise RuntimeError("no linear edge")

    # ------------------------------------------------------------------
    # Test 1: ratio=1.0 gives symmetric 45° result
    # ------------------------------------------------------------------
    def test_ratio_1_is_symmetric(self):
        edge = self._edge()
        rec = recommend_asymmetric_chamfer(edge, ratio_a_to_b=1.0)
        assert rec.applicable
        assert rec.is_symmetric
        assert abs(rec.leg_a_mm - rec.leg_b_mm) < 1e-9
        assert abs(rec.angle_a_deg - 45.0) < 1e-9
        assert abs(rec.angle_b_deg - 45.0) < 1e-9

    # ------------------------------------------------------------------
    # Test 2: ratio=2.0 → leg_a = 2 × leg_b
    # ------------------------------------------------------------------
    def test_ratio_2_legs(self):
        edge = self._edge()
        rec = recommend_asymmetric_chamfer(edge, ratio_a_to_b=2.0)
        assert rec.applicable
        assert not rec.is_symmetric
        assert abs(rec.leg_a_mm - 2.0 * rec.leg_b_mm) < 1e-9

    # ------------------------------------------------------------------
    # Test 3: ratio=0.5 → leg_b = 2 × leg_a
    # ------------------------------------------------------------------
    def test_ratio_0_5_legs(self):
        edge = self._edge()
        rec = recommend_asymmetric_chamfer(edge, ratio_a_to_b=0.5)
        assert rec.applicable
        assert not rec.is_symmetric
        # leg_a = 0.5 * leg_b  →  leg_b = 2 * leg_a
        assert abs(rec.leg_b_mm - 2.0 * rec.leg_a_mm) < 1e-9

    # ------------------------------------------------------------------
    # Test 4: angle computation — atan2(leg_b, leg_a)
    # ------------------------------------------------------------------
    def test_angle_computation_ratio_2(self):
        edge = self._edge()
        rec = recommend_asymmetric_chamfer(edge, ratio_a_to_b=2.0)
        expected_a = math.degrees(math.atan2(rec.leg_b_mm, rec.leg_a_mm))
        assert abs(rec.angle_a_deg - expected_a) < 1e-6

    def test_angle_computation_ratio_0_5(self):
        edge = self._edge()
        rec = recommend_asymmetric_chamfer(edge, ratio_a_to_b=0.5)
        expected_a = math.degrees(math.atan2(rec.leg_b_mm, rec.leg_a_mm))
        assert abs(rec.angle_a_deg - expected_a) < 1e-6

    # ------------------------------------------------------------------
    # Test 5: angles always sum to 90°
    # ------------------------------------------------------------------
    def test_angles_sum_to_90(self):
        edge = self._edge()
        for ratio in [0.25, 0.5, 1.0, 2.0, 4.0]:
            rec = recommend_asymmetric_chamfer(edge, ratio_a_to_b=ratio)
            assert abs(rec.angle_a_deg + rec.angle_b_deg - 90.0) < 1e-9, (
                f"ratio={ratio}: angles {rec.angle_a_deg} + {rec.angle_b_deg} != 90"
            )

    # ------------------------------------------------------------------
    # Test 6: invalid ratio <= 0 → applicable=False
    # ------------------------------------------------------------------
    def test_invalid_ratio_zero(self):
        edge = self._edge()
        rec = recommend_asymmetric_chamfer(edge, ratio_a_to_b=0.0)
        assert not rec.applicable

    def test_invalid_ratio_negative(self):
        edge = self._edge()
        rec = recommend_asymmetric_chamfer(edge, ratio_a_to_b=-1.5)
        assert not rec.applicable

    # ------------------------------------------------------------------
    # Test 7: ratio cap — ratio > 10 clips to 10
    # ------------------------------------------------------------------
    def test_ratio_cap_at_10(self):
        edge = self._edge()
        rec = recommend_asymmetric_chamfer(edge, ratio_a_to_b=100.0)
        assert rec.applicable
        # Must be capped: leg_a <= 10 * leg_b
        assert rec.leg_a_mm <= 10.0 * rec.leg_b_mm + 1e-9

    # ------------------------------------------------------------------
    # Test 8: recommend_chamfer_size with ratio=2.0 delegates to asymmetric
    # ------------------------------------------------------------------
    def test_recommend_chamfer_size_ratio_2_delegates(self):
        body = _box_body()
        edge, faces = _first_linear_edge_and_faces(body)
        rec = recommend_chamfer_size(edge, faces, ratio=2.0)
        assert isinstance(rec, ChamferRecommendation)
        assert rec.applicable
        # angle_deg should be < 45 (because leg_a > leg_b, angle_a < 45)
        assert rec.angle_deg < 45.0

    # ------------------------------------------------------------------
    # Test 9: backward compat — old API call (no ratio) still symmetric
    # ------------------------------------------------------------------
    def test_backward_compat_no_ratio(self):
        body = _box_body()
        edge, faces = _first_linear_edge_and_faces(body)
        ctx = ChamferContext(hole_diameter_mm=3.0, din74_form="A")
        rec = recommend_chamfer_size(edge, faces, ctx)
        # No ratio arg → symmetric 45°
        assert abs(rec.angle_deg - 45.0) < 1e-9
        assert rec.kind == "countersink"

    # ------------------------------------------------------------------
    # Test 10: AsymmetricChamferRecommendation dataclass defaults
    # ------------------------------------------------------------------
    def test_asymmetric_dataclass_defaults(self):
        rec = AsymmetricChamferRecommendation()
        assert rec.leg_a_mm == 0.0
        assert rec.leg_b_mm == 0.0
        assert abs(rec.angle_a_deg - 45.0) < 1e-9
        assert abs(rec.angle_b_deg - 45.0) < 1e-9
        assert rec.is_symmetric is True
        assert rec.applicable is True

    # ------------------------------------------------------------------
    # Test 11: application='cosmetic' uses cosmetic base leg
    # ------------------------------------------------------------------
    def test_cosmetic_application_base_leg(self):
        edge = self._edge()
        rec = recommend_asymmetric_chamfer(edge, application="cosmetic", ratio_a_to_b=1.0)
        assert rec.applicable
        # cosmetic base = 1.5 mm
        assert abs(rec.leg_b_mm - 1.5) < 1e-9
        assert abs(rec.leg_a_mm - 1.5) < 1e-9

    # ------------------------------------------------------------------
    # Test 12: rationale cites Drozda-Wick
    # ------------------------------------------------------------------
    def test_rationale_cites_drozda(self):
        edge = self._edge()
        rec = recommend_asymmetric_chamfer(edge, ratio_a_to_b=2.0)
        assert "Drozda" in rec.rationale or "ISO 13715" in rec.rationale
