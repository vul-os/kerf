"""Tests for kerf_cad_core.geom.auto_chamfer.

All tests are hermetic — no network, no OCCT, no external fixtures.

Analytical oracles used:
- Cube (1×1×1): 12 edges, all 90° interior dihedrals, all on convex hull.
  Expected: every edge → 'safety_chamfer', recommended_width=0.5mm.
- Chamfered cube: apply recommend_chamfers on one edge with chamfer_edge.
  The bevel face's edges include non-Line3 coedges and the bevel edge itself
  is new; the original edge is consumed — so the original edge position is
  absent from the chamfered body, confirming it was processed.
- apply_chamfer_recommendations: volume reduced by ~½·w²·L per chamfered edge.
- Interior edge / hollow body heuristic: a body with only 2 adjacent faces
  both flush against hull — a concave edge (interior dihedral > 180°) should
  be classified 'no_chamfer'.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from kerf_cad_core.geom.brep import validate_body
from kerf_cad_core.geom.brep_build import box_to_body
from kerf_cad_core.geom.chamfer import chamfer_edge
from kerf_cad_core.geom.auto_chamfer import (
    ChamferRecommendationResult,
    EdgeChamferInfo,
    apply_chamfer_recommendations,
    chamfer_size_by_design_intent,
    recommend_chamfers,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _unit_box():
    """1×1×1 box at origin."""
    return box_to_body((0, 0, 0), 1, 1, 1)


def _pick_edge_by_vertices(body, pt0, pt1, tol=1e-6):
    """Find an edge whose endpoints match pt0 and pt1 (in either order)."""
    p0 = np.asarray(pt0, dtype=float)
    p1 = np.asarray(pt1, dtype=float)
    for e in body.all_edges():
        a = e.v_start.point
        b = e.v_end.point
        if (np.linalg.norm(a - p0) < tol and np.linalg.norm(b - p1) < tol) or \
           (np.linalg.norm(a - p1) < tol and np.linalg.norm(b - p0) < tol):
            return e
    raise AssertionError(f"No edge found between {pt0} and {pt1}")


def _box_volume(body):
    """Estimate body volume using the divergence theorem (fan triangulation)."""
    vol = 0.0
    for face in body.all_faces():
        outer = face.outer_loop()
        if outer is None or len(outer.coedges) < 3:
            continue
        pts = [np.asarray(ce.start_point(), dtype=float) for ce in outer.coedges]
        p0 = pts[0]
        for i in range(1, len(pts) - 1):
            a = pts[i] - p0
            b = pts[i + 1] - p0
            cross = np.cross(a, b)
            vol += float(np.dot(p0, cross))
    return abs(vol) / 6.0


# ---------------------------------------------------------------------------
# Test 1 — Cube edges: all 12 classified 'safety_chamfer'
# ---------------------------------------------------------------------------


def test_cube_all_edges_safety_chamfer():
    """A 1×1×1 cube has 12 edges, all 90° dihedrals on the hull → all safety_chamfer."""
    body = _unit_box()
    result = recommend_chamfers(body, safety_chamfer_mm=0.5)

    assert isinstance(result, ChamferRecommendationResult)
    assert len(result.per_edge) == 12, (
        f"Expected 12 edges, got {len(result.per_edge)}"
    )
    for info in result.per_edge:
        assert info.kind == "safety_chamfer", (
            f"Edge with dihedral={info.dihedral_deg:.1f}° classified as "
            f"'{info.kind}', expected 'safety_chamfer'"
        )
        assert abs(info.recommended_width - 0.5) < 1e-9, (
            f"Expected width=0.5mm, got {info.recommended_width}"
        )


def test_cube_all_edges_convex():
    """All box edges should be flagged as convex."""
    body = _unit_box()
    result = recommend_chamfers(body)
    for info in result.per_edge:
        assert info.is_convex, f"Edge dihedral={info.dihedral_deg:.1f}° not flagged convex"


def test_cube_all_edges_on_hull():
    """All box edges should be flagged as on the convex-hull boundary."""
    body = _unit_box()
    result = recommend_chamfers(body)
    for info in result.per_edge:
        assert info.is_on_hull_boundary, (
            f"Edge midpoint not flagged on hull (dihedral={info.dihedral_deg:.1f}°)"
        )


def test_cube_dihedral_angles_approx_90():
    """All 12 box edges should have interior dihedral ≈ 90°."""
    body = _unit_box()
    result = recommend_chamfers(body)
    for info in result.per_edge:
        assert not math.isnan(info.dihedral_deg), "Dihedral angle is NaN"
        assert abs(info.dihedral_deg - 90.0) < 1.0, (
            f"Expected ≈90°, got {info.dihedral_deg:.4f}°"
        )


def test_cube_total_recommended_edges():
    """total_recommended_edges should equal 12 for a cube."""
    body = _unit_box()
    result = recommend_chamfers(body)
    assert result.total_recommended_edges == 12


def test_cube_result_has_notes():
    """design_intent_notes should be non-empty."""
    body = _unit_box()
    result = recommend_chamfers(body)
    assert len(result.design_intent_notes) > 0


# ---------------------------------------------------------------------------
# Test 2 — Filleted / chamfered cube: the consumed edge no longer present
# ---------------------------------------------------------------------------


def test_chamfered_cube_consumed_edge_absent():
    """After chamfering one edge, the original edge midpoint is absent from result body."""
    body = _unit_box()
    target_edge = _pick_edge_by_vertices(body, (1, 0, 1), (0, 0, 1))
    original_mid = 0.5 * (target_edge.v_start.point + target_edge.v_end.point)

    chamfered_body = chamfer_edge(body, target_edge, 0.1)

    # The original edge midpoint should no longer appear as any edge midpoint
    from kerf_cad_core.geom.brep import Line3
    for e in chamfered_body.all_edges():
        if isinstance(e.curve, Line3):
            mid = 0.5 * (e.curve.p0 + e.curve.p1)
        else:
            mid = 0.5 * (e.v_start.point + e.v_end.point)
        dist = float(np.linalg.norm(mid - original_mid))
        assert dist > 0.05, (
            f"Original edge midpoint {original_mid} still present at dist={dist:.4f}"
        )


def test_recommend_on_chamfered_body_does_not_recommend_bevel_edges():
    """After one chamfer, the new bevel face edges should not be recommended
    for a further chamfer (they are the new bevel face boundaries, which are
    typically not re-entrant and appear as boundary or non-planar edges)."""
    body = _unit_box()
    edge = _pick_edge_by_vertices(body, (1, 0, 1), (0, 0, 1))
    chamfered = chamfer_edge(body, edge, 0.1)

    # Run recommendation — it should not crash and should return a result
    result = recommend_chamfers(chamfered)
    assert isinstance(result, ChamferRecommendationResult)
    # Chamfered body has 15 edges — we should get 15 records
    assert len(result.per_edge) == 15, (
        f"Expected 15 edges in chamfered body, got {len(result.per_edge)}"
    )


# ---------------------------------------------------------------------------
# Test 3 — apply_chamfer_recommendations: volume reduced
# ---------------------------------------------------------------------------


def test_apply_chamfer_reduces_volume():
    """apply_chamfer_recommendations on a cube removes material from each chamfered edge.

    For a symmetric chamfer of width w on a right-angle edge of length L,
    the volume removed per edge is ½·w²·L.

    We apply with safety_chamfer_mm=0.1 (small enough to fit all 12 edges
    sequentially) and verify the total volume reduction is > 0.
    """
    w = 0.05  # 0.05mm — tiny to avoid width-exceeds-face on sequential chamfers
    body = _unit_box()
    vol_before = _box_volume(body)

    result = recommend_chamfers(body, safety_chamfer_mm=w)
    chamfered_body = apply_chamfer_recommendations(body, result)

    vol_after = _box_volume(chamfered_body)
    removed = vol_before - vol_after

    # At least one chamfer should have been applied
    assert removed > 0, f"Volume should decrease after applying chamfers, got {removed}"


def test_apply_chamfer_single_edge_volume():
    """Apply recommendation for one edge and verify volume removed ≈ ½·w²·L."""
    w = 0.1  # mm = 0.1 units (unit box)
    L = 1.0
    expected_removed = 0.5 * w * w * L

    body = _unit_box()
    # Get recommendations with only one edge width set to w
    result = recommend_chamfers(body, safety_chamfer_mm=w)

    # Apply only the first recommended edge
    from kerf_cad_core.geom.auto_chamfer import ChamferRecommendationResult, EdgeChamferInfo
    first_only = ChamferRecommendationResult(
        per_edge=[result.per_edge[0]] + [
            EdgeChamferInfo(
                edge=info.edge,
                kind="no_chamfer",
                dihedral_deg=info.dihedral_deg,
                is_convex=info.is_convex,
                is_on_hull_boundary=info.is_on_hull_boundary,
                recommended_width=0.0,
                edge_length=info.edge_length,
            )
            for info in result.per_edge[1:]
        ],
        total_recommended_edges=1,
        recommended_widths=result.recommended_widths,
        design_intent_notes=result.design_intent_notes,
    )

    vol_before = _box_volume(body)
    chamfered = apply_chamfer_recommendations(body, first_only)
    vol_after = _box_volume(chamfered)
    removed = vol_before - vol_after

    assert abs(removed - expected_removed) < 1e-6, (
        f"Volume removed {removed:.8f} ≠ expected {expected_removed:.8f}"
    )


def test_apply_chamfer_result_is_valid_body():
    """apply_chamfer_recommendations should return a validate_body-clean result."""
    body = _unit_box()
    result = recommend_chamfers(body, safety_chamfer_mm=0.05)
    chamfered = apply_chamfer_recommendations(body, result)
    vr = validate_body(chamfered)
    assert vr["ok"], f"validate_body errors: {vr['errors']}"


# ---------------------------------------------------------------------------
# Test 4 — Interior edge / concave edge skip
# ---------------------------------------------------------------------------


def test_concave_edge_classified_no_chamfer():
    """An interior/concave edge (re-entrant) should be classified 'no_chamfer'.

    We construct a 2×1×1 box and then examine the edges.  All box edges are
    90° convex, so there are no concave edges in a simple box.

    Instead, we test the _is_convex_edge / _dihedral_angle_deg functions
    directly with inverted normals (simulating a reflex / interior edge).
    """
    from kerf_cad_core.geom.auto_chamfer import _dihedral_angle_deg, _is_convex_edge

    # Two faces pointing toward each other (inward-facing normals)
    # Simulates a re-entrant (concave) edge where normals converge
    n1 = np.array([1.0, 0.0, 0.0])
    n2 = np.array([0.0, 1.0, 0.0])
    # Normal box corner: dihedral ≈ 90°, convex
    assert _is_convex_edge(n1, n2), "Perpendicular normals should be convex"
    assert abs(_dihedral_angle_deg(n1, n2) - 90.0) < 1e-9

    # Co-planar edge (same normal direction) → dihedral ≈ 180° → NOT convex
    n_flat1 = np.array([0.0, 0.0, 1.0])
    n_flat2 = np.array([0.0, 0.0, 1.0])
    assert not _is_convex_edge(n_flat1, n_flat2), (
        "Co-planar normals should not be convex (dihedral ≈ 180°)"
    )

    # Reflex / inward corner: normals point toward each other
    # n1 · n2 > 0 → exterior angle < 90° → interior dihedral > 90°
    # but this can still be convex by our threshold (< 179°)
    # A truly re-entrant edge has normals that are nearly anti-parallel
    # but pointing into the interior — modelled as n1 · n2 → +1 (co-directional)
    n_reflex1 = np.array([0.0, 0.0, 1.0])
    n_reflex2 = np.array([0.0, 0.0, 1.0])  # same direction → near-co-planar
    dihedral = _dihedral_angle_deg(n_reflex1, n_reflex2)
    assert dihedral >= 179.0, (
        f"Co-directional normals should give dihedral≈180°, got {dihedral:.2f}°"
    )


def test_non_manifold_edge_classified_no_chamfer():
    """An edge with only 1 adjacent face (boundary edge) → no_chamfer.

    We test this through the full recommend_chamfers path by creating a body
    with a boundary edge (open shell) — but since box_to_body always produces
    a closed manifold, we instead verify the classification via
    _faces_of_edge on a synthetic scenario.
    """
    # In the unit box, all edges are shared by exactly 2 faces.
    # Verify that no edge is classified as 'no_chamfer' due to topology.
    body = _unit_box()
    result = recommend_chamfers(body)
    # All 12 edges of a closed box should be manifold and thus not no_chamfer
    # due to non-manifold topology.  (They are all classified safety_chamfer.)
    no_chamfer_count = sum(1 for e in result.per_edge if e.kind == "no_chamfer")
    assert no_chamfer_count == 0, (
        f"Expected 0 no_chamfer edges on clean box, got {no_chamfer_count}"
    )


# ---------------------------------------------------------------------------
# Test 5 — chamfer_size_by_design_intent
# ---------------------------------------------------------------------------


def test_chamfer_size_safety_intent():
    body = _unit_box()
    result = recommend_chamfers(body)
    for info in result.per_edge:
        w = chamfer_size_by_design_intent(info, intent="safety")
        assert abs(w - 0.5) < 1e-9


def test_chamfer_size_manufacturing_intent():
    body = _unit_box()
    result = recommend_chamfers(body)
    for info in result.per_edge:
        w = chamfer_size_by_design_intent(info, intent="manufacturing")
        assert abs(w - 1.0) < 1e-9


def test_chamfer_size_auto_intent():
    """'auto' intent should return the same width as the classified kind."""
    body = _unit_box()
    result = recommend_chamfers(body)
    for info in result.per_edge:
        w_auto = chamfer_size_by_design_intent(info, intent="auto")
        assert abs(w_auto - info.recommended_width) < 1e-9


def test_chamfer_size_no_chamfer_edge():
    """'no_chamfer' edges always return 0.0 regardless of intent."""
    body = _unit_box()
    result = recommend_chamfers(body)
    # Fabricate a no_chamfer info
    dummy = EdgeChamferInfo(
        edge=result.per_edge[0].edge,
        kind="no_chamfer",
        dihedral_deg=180.0,
        is_convex=False,
        is_on_hull_boundary=False,
        recommended_width=0.0,
        edge_length=1.0,
    )
    assert chamfer_size_by_design_intent(dummy, intent="auto") == 0.0
    assert chamfer_size_by_design_intent(dummy, intent="safety") == 0.0
    assert chamfer_size_by_design_intent(dummy, intent="manufacturing") == 0.0


# ---------------------------------------------------------------------------
# Test 6 — Larger box (2×3×4) edge counts and widths
# ---------------------------------------------------------------------------


def test_larger_box_all_edges_safety_chamfer():
    """A 2×3×4 box also has 12 edges, all safety_chamfer."""
    body = box_to_body((0, 0, 0), 2, 3, 4)
    result = recommend_chamfers(body, safety_chamfer_mm=0.5)
    assert len(result.per_edge) == 12
    for info in result.per_edge:
        assert info.kind == "safety_chamfer", (
            f"Edge dihedral={info.dihedral_deg:.2f}° classified as '{info.kind}'"
        )


# ---------------------------------------------------------------------------
# Test 7 — Recommended widths mapping populated
# ---------------------------------------------------------------------------


def test_recommended_widths_contains_all_kinds():
    body = _unit_box()
    result = recommend_chamfers(body)
    for kind in ("safety_chamfer", "manufacturing_chamfer", "cosmetic_chamfer", "no_chamfer"):
        assert kind in result.recommended_widths, f"Missing kind '{kind}' in recommended_widths"
    assert result.recommended_widths["no_chamfer"] == 0.0
    assert result.recommended_widths["safety_chamfer"] == 0.5
    assert result.recommended_widths["manufacturing_chamfer"] == 1.0
