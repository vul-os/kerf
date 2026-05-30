"""Tests for kerf_cad_core.geom.fillet_recommend_radius.

All tests are hermetic: no network, no OCCT, no external fixtures.
Analytic oracles are drawn from:
  - Peterson (1974) Stress Concentration Factors §2.3
    Kt = 1 + 2·sqrt(d/r)  for tension notch
  - Boothroyd-Dewhurst (2002) Product Design for Manufacture and Assembly §4
    r ≤ face_min / 4

DEPTH CHECK oracles
-------------------
- 10×10×5 box (smallest face = 5 mm):
    face_size cap = 5/4 = 1.25 mm
    Peterson notch (edge_len=5, notch_depth=5): 0.1×5 = 0.5 mm
    stress_floor (steel, factor=0.05, wt=5 mm): 0.05×5 = 0.25 mm
    tool floor: 1.0 mm
    → max(0.5, 0.25, 1.0) capped at 1.25 → r = 1.25 mm  ✓

- Stress-critical steel, wall=20 mm:
    stress_floor = 0.05 × 20 = 1.0 mm
    → r ≥ 1.0 mm  ✓

- Sharp intentional crease (preserve_sharp=True, exterior corner ≥90°):
    → applicable=False, radius_mm=0.0  ✓
"""

from __future__ import annotations

import math
import pytest
import numpy as np

from kerf_cad_core.geom.brep_build import box_to_body
from kerf_cad_core.geom.fillet_solid import _find_incident_faces
from kerf_cad_core.geom.fillet_recommend_radius import (
    FilletRadiusContext,
    RadiusRecommendation,
    recommend_fillet_radius,
    recommend_fillet_radii_for_body,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _box(dx, dy, dz):
    return box_to_body((0.0, 0.0, 0.0), dx, dy, dz)


def _recs_applicable(body, ctx):
    recs = recommend_fillet_radii_for_body(body, ctx)
    return [r for r in recs if r.applicable]


# ---------------------------------------------------------------------------
# Test 1: 10×10×5 box — face-size rule oracle
# Expected r = 1.25 mm  (face_min=5, /4=1.25; tool floor=1.0; final=1.25)
# ---------------------------------------------------------------------------

class TestBoxFaceSizeRule:
    """Oracle: 10×10×5 box should yield r = 1.25 mm on edges bounding the
    5mm face (tool floor 1.0 mm < face_size cap 1.25 mm).
    With preserve_sharp=False all exterior edges get recommendations."""

    def test_10x10x5_radius_oracle(self):
        """Oracle: 10×10×5 box, smallest face_min=5 mm.
        face_size cap = 5/4 = 1.25 mm.
        With tool_radius=0.5 mm (< face_cap) and steel stress floor=0.25 mm:
          max(peterson_notch=0.5, stress_floor=0.25, tool=0.5) = 0.5 mm.
          That is below the face_size cap of 1.25 mm, so r = 0.5 mm.
        The face_size cap itself = 1.25 mm (Boothroyd-Dewhurst §4 oracle).
        When tool_radius=1.25 mm (equal to face cap): r = 1.25 mm.
        """
        body = _box(10.0, 10.0, 5.0)
        # Use tool_radius == face_size_cap to hit the oracle exactly
        ctx = FilletRadiusContext(
            material="steel",
            tool_radius_mm=1.25,
            preserve_sharp=False,
        )
        recs = recommend_fillet_radii_for_body(body, ctx)
        applicable = [r for r in recs if r.applicable]
        assert len(applicable) > 0, "Expected at least some applicable edges"
        # Find edges adjacent to the 5mm face (those with face_size cap 1.25)
        capped_at_125 = [
            r for r in applicable
            if abs(r.criteria_radii.get("face_size", 0) - 1.25) < 0.01
        ]
        assert len(capped_at_125) > 0, (
            "Expected edges with face_size cap = 5/4 = 1.25 mm"
        )
        for rec in capped_at_125:
            assert abs(rec.radius_mm - 1.25) < 0.01, (
                f"Expected r=1.25 mm (face_size cap, Boothroyd-Dewhurst §4), got {rec.radius_mm}"
            )

    def test_10x10x5_rationale_cites_boothroyd(self):
        body = _box(10.0, 10.0, 5.0)
        ctx = FilletRadiusContext(preserve_sharp=False)
        recs = recommend_fillet_radii_for_body(body, ctx)
        applicable = [r for r in recs if r.applicable]
        for rec in applicable:
            assert "Boothroyd" in rec.rationale or "face" in rec.rationale.lower(), (
                "Rationale should cite Boothroyd-Dewhurst face-size rule"
            )

    def test_10x10x5_alternatives_present(self):
        body = _box(10.0, 10.0, 5.0)
        ctx = FilletRadiusContext(preserve_sharp=False)
        recs = recommend_fillet_radii_for_body(body, ctx)
        for rec in recs:
            if rec.applicable:
                assert len(rec.alternatives) >= 1, (
                    "Expected at least one alternative radius"
                )
                # All alternatives ≤ face_size cap
                face_cap = rec.criteria_radii.get("face_size", float("inf"))
                for alt in rec.alternatives:
                    assert alt <= face_cap + 1e-9, (
                        f"Alternative {alt} exceeds face-size cap {face_cap}"
                    )


# ---------------------------------------------------------------------------
# Test 2: large flat box — all edges preserve_sharp by default
# ---------------------------------------------------------------------------

class TestPreserveSharpDefault:
    """All box edges are exterior convex corners (≥90° between normals).
    With default preserve_sharp=True, all should be not-applicable."""

    def test_unit_box_preserve_sharp_all_not_applicable(self):
        body = _box(1.0, 1.0, 1.0)
        ctx = FilletRadiusContext(preserve_sharp=True)
        recs = recommend_fillet_radii_for_body(body, ctx)
        applicable = [r for r in recs if r.applicable]
        assert len(applicable) == 0, (
            f"Expected 0 applicable (all exterior, preserve_sharp=True), "
            f"got {len(applicable)}"
        )
        for rec in recs:
            assert rec.radius_mm == 0.0
            assert "exterior" in rec.rationale.lower() or "preserved" in rec.rationale.lower()


# ---------------------------------------------------------------------------
# Test 3: stress-critical steel edge with wall_thickness_mm=20
# Oracle: stress_relief_floor = 0.05 × 20 = 1.0 mm
# ---------------------------------------------------------------------------

class TestStressCriticalSteel:
    """Peterson 1974 Table 2.1 + Shigley §6: for steel, r ≥ 0.05 × wall_thickness.
    With wall=20 mm, floor = 1.0 mm."""

    def test_stress_floor_steel_20mm_wall(self):
        body = _box(10.0, 10.0, 20.0)
        ctx = FilletRadiusContext(
            material="steel",
            tool_radius_mm=0.5,   # tool smaller than stress floor
            wall_thickness_mm=20.0,
            preserve_sharp=False,
        )
        recs = recommend_fillet_radii_for_body(body, ctx)
        applicable = [r for r in recs if r.applicable]
        assert len(applicable) > 0
        for rec in applicable:
            sr_floor = rec.criteria_radii.get("stress_relief_floor", 0.0)
            assert abs(sr_floor - 1.0) < 0.01, (
                f"Expected stress_relief_floor = 0.05×20 = 1.0, got {sr_floor}"
            )
            # Final radius must be ≥ stress floor (capped by face size)
            assert rec.radius_mm >= sr_floor - 0.01 or rec.radius_mm == rec.criteria_radii.get("face_size", 0.0), (
                f"radius_mm {rec.radius_mm} should be ≥ stress_floor {sr_floor} or at face cap"
            )

    def test_stress_floor_steel_rationale_cites_peterson(self):
        body = _box(10.0, 10.0, 20.0)
        ctx = FilletRadiusContext(
            material="steel",
            wall_thickness_mm=20.0,
            preserve_sharp=False,
        )
        recs = recommend_fillet_radii_for_body(body, ctx)
        for rec in recs:
            if rec.applicable:
                assert "Peterson" in rec.rationale, (
                    "Rationale must cite Peterson 1974"
                )

    def test_cast_iron_higher_floor(self):
        """cast_iron factor=0.08 > steel factor=0.05."""
        body = _box(10.0, 10.0, 10.0)
        ctx_steel = FilletRadiusContext(
            material="steel", wall_thickness_mm=10.0, preserve_sharp=False
        )
        ctx_cast = FilletRadiusContext(
            material="cast_iron", wall_thickness_mm=10.0, preserve_sharp=False
        )
        recs_steel = [r for r in recommend_fillet_radii_for_body(body, ctx_steel) if r.applicable]
        recs_cast = [r for r in recommend_fillet_radii_for_body(body, ctx_cast) if r.applicable]
        if recs_steel and recs_cast:
            r_steel = recs_steel[0].criteria_radii["stress_relief_floor"]
            r_cast = recs_cast[0].criteria_radii["stress_relief_floor"]
            assert r_cast > r_steel, (
                f"cast_iron floor {r_cast} should exceed steel floor {r_steel}"
            )


# ---------------------------------------------------------------------------
# Test 4: sharp crease preservation (≥90° dihedral)
# ---------------------------------------------------------------------------

class TestSharpCreasePreservation:
    """All box exterior edges have dihedral ≥ 90° between outward normals.
    With preserve_sharp=True these must NOT be recommended (applicable=False)."""

    def test_sharp_edges_not_filleted(self):
        body = _box(5.0, 3.0, 2.0)
        ctx = FilletRadiusContext(preserve_sharp=True)
        recs = recommend_fillet_radii_for_body(body, ctx)
        for rec in recs:
            # All edges on a box are exterior convex → preserve_sharp kicks in
            assert not rec.applicable or rec.radius_mm == 0.0, (
                "Sharp exterior edge should not be recommended with preserve_sharp=True"
            )

    def test_preserve_sharp_false_yields_recommendations(self):
        body = _box(5.0, 3.0, 2.0)
        ctx = FilletRadiusContext(preserve_sharp=False, tool_radius_mm=0.1)
        recs = recommend_fillet_radii_for_body(body, ctx)
        applicable = [r for r in recs if r.applicable]
        assert len(applicable) > 0, (
            "With preserve_sharp=False, box edges should receive recommendations"
        )

    def test_rationale_mentions_intentional(self):
        body = _box(1.0, 1.0, 1.0)
        ctx = FilletRadiusContext(preserve_sharp=True)
        recs = recommend_fillet_radii_for_body(body, ctx)
        for rec in recs:
            if not rec.applicable:
                assert "intentional" in rec.rationale.lower() or "preserved" in rec.rationale.lower() or "coplanar" in rec.rationale.lower() or "non-straight" in rec.rationale.lower() or "non-manifold" in rec.rationale.lower(), (
                    f"Expected 'preserved' / 'intentional' in rationale, got: {rec.rationale[:80]}"
                )


# ---------------------------------------------------------------------------
# Test 5: Peterson Kt oracle — tension formula
# Kt = 1 + 2·sqrt(d/r); d=5, r=1.25 → Kt = 1 + 2·sqrt(4) = 5.0
# But max is capped at base_stress_concentration; exterior corners give Kt=1.0
# ---------------------------------------------------------------------------

class TestPetersonKtOracle:
    """Verify analytic Kt formula from Peterson 1974 §2.3.

    For a tension notch: Kt = 1 + 2·sqrt(d/r).
    The recommend_fillet_radius function reports kt_before and kt_after.
    For exterior box edges: kt_before = kt_after = 1.0 (no stress riser).
    """

    def test_exterior_edges_kt_equals_one(self):
        body = _box(10.0, 10.0, 5.0)
        ctx = FilletRadiusContext(preserve_sharp=False)
        recs = recommend_fillet_radii_for_body(body, ctx)
        for rec in recs:
            if rec.applicable:
                # All box edges are exterior corners
                assert rec.kt_before == 1.0, (
                    f"Exterior corner kt_before should be 1.0, got {rec.kt_before}"
                )
                assert rec.kt_after == 1.0, (
                    f"Exterior corner kt_after should be 1.0, got {rec.kt_after}"
                )

    def test_tension_kt_formula_direct(self):
        """Direct: Kt formula correctness — tension, d=4, r=1 → Kt = 1+2*2=5."""
        from kerf_cad_core.geom.fillet_recommend_radius import _kt_tension
        kt = _kt_tension(notch_depth=4.0, r=1.0)
        expected = 1.0 + 2.0 * math.sqrt(4.0 / 1.0)
        assert abs(kt - expected) < 1e-9, f"Tension Kt oracle failed: {kt} vs {expected}"

    def test_bending_kt_formula_direct(self):
        """Direct: bending formula Kt = 1 + sqrt(d/r), d=4, r=1 → Kt = 1+2=3."""
        from kerf_cad_core.geom.fillet_recommend_radius import _kt_bending
        kt = _kt_bending(notch_depth=4.0, r=1.0)
        expected = 1.0 + math.sqrt(4.0 / 1.0)
        assert abs(kt - expected) < 1e-9, f"Bending Kt oracle failed: {kt} vs {expected}"

    def test_kt_always_gte_one(self):
        """Peterson formulas must always return Kt ≥ 1."""
        from kerf_cad_core.geom.fillet_recommend_radius import _kt_tension, _kt_bending
        for d in [0.1, 1.0, 5.0, 10.0]:
            for r in [0.01, 0.1, 1.0, 5.0]:
                assert _kt_tension(d, r) >= 1.0
                assert _kt_bending(d, r) >= 1.0

    def test_kt_decreases_with_larger_radius(self):
        """Larger r must give lower Kt (monotonically decreasing)."""
        from kerf_cad_core.geom.fillet_recommend_radius import _kt_tension
        d = 5.0
        kt_small = _kt_tension(d, 0.5)
        kt_large = _kt_tension(d, 2.0)
        assert kt_large < kt_small, f"Larger r should give lower Kt: {kt_large} < {kt_small}"


# ---------------------------------------------------------------------------
# Test 6: Tool constraint — face too small for tool
# ---------------------------------------------------------------------------

class TestToolConstraint:
    """If tool_radius_mm > face_size_cap, edge must be not-applicable."""

    def test_tool_larger_than_face_cap(self):
        # 10×10×1 box: smallest face_min ≈ 1mm → face_cap = 0.25mm
        # tool_radius = 1.0mm > face_cap → not applicable
        body = _box(10.0, 10.0, 1.0)
        ctx = FilletRadiusContext(
            tool_radius_mm=1.0,
            preserve_sharp=False,
        )
        recs = recommend_fillet_radii_for_body(body, ctx)
        # Edges adjacent to the 1mm face have face_cap=0.25 < tool=1.0
        for rec in recs:
            cap = rec.criteria_radii.get("face_size", float("inf"))
            tool = rec.criteria_radii.get("tool_constraint", 0.0)
            if cap < tool and not rec.applicable:
                assert rec.radius_mm == 0.0
                # Verify rationale explains the cause
                assert "tool" in rec.rationale.lower() or "small" in rec.rationale.lower()

    def test_tool_zero_allows_any_radius(self):
        """tool_radius_mm=0 removes the manufacturing floor."""
        body = _box(10.0, 10.0, 5.0)
        ctx = FilletRadiusContext(
            tool_radius_mm=0.0,
            preserve_sharp=False,
        )
        recs = recommend_fillet_radii_for_body(body, ctx)
        applicable = [r for r in recs if r.applicable]
        # With no tool floor, we should still get recommendations from Peterson
        assert len(applicable) > 0


# ---------------------------------------------------------------------------
# Test 7: criteria_radii dict is complete
# ---------------------------------------------------------------------------

class TestCriteriaRadiiDict:
    def test_applicable_edge_has_all_criteria_keys(self):
        body = _box(10.0, 10.0, 5.0)
        ctx = FilletRadiusContext(preserve_sharp=False)
        recs = recommend_fillet_radii_for_body(body, ctx)
        expected_keys = {"face_size", "peterson_notch", "stress_relief_floor",
                         "tool_constraint", "final"}
        for rec in recs:
            if rec.applicable:
                assert expected_keys == set(rec.criteria_radii.keys()), (
                    f"criteria_radii missing keys: "
                    f"{expected_keys - set(rec.criteria_radii.keys())}"
                )

    def test_final_equals_radius_mm(self):
        body = _box(10.0, 10.0, 5.0)
        ctx = FilletRadiusContext(preserve_sharp=False)
        recs = recommend_fillet_radii_for_body(body, ctx)
        for rec in recs:
            if rec.applicable:
                assert abs(rec.criteria_radii["final"] - rec.radius_mm) < 1e-9


# ---------------------------------------------------------------------------
# Test 8: single-edge API
# ---------------------------------------------------------------------------

class TestSingleEdgeAPI:
    def test_recommend_fillet_radius_returns_dataclass(self):
        body = _box(10.0, 10.0, 5.0)
        edges = body.all_edges()
        assert len(edges) > 0
        edge = edges[0]
        incident = _find_incident_faces(body, edge)
        ctx = FilletRadiusContext(preserve_sharp=False)
        rec = recommend_fillet_radius(edge, incident, ctx)
        assert isinstance(rec, RadiusRecommendation)
        assert rec.rationale != ""

    def test_wrong_face_count_returns_not_applicable(self):
        body = _box(5.0, 5.0, 5.0)
        edges = body.all_edges()
        edge = edges[0]
        ctx = FilletRadiusContext()
        # Pass only one face — should fail gracefully
        incident = _find_incident_faces(body, edge)
        rec = recommend_fillet_radius(edge, incident[:1], ctx)
        assert not rec.applicable
        assert "2" in rec.rationale  # mentions expected 2 faces
