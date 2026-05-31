"""
tests/test_ecn_impact_analysis.py
===================================

Validation tests for kerf_plm.ecn_impact_analysis.

References
----------
- ISO 10007:2003 §6 — Change control
- APICS Dictionary 16th ed. — "engineering change notice (ECN)"
- SAE AS9100D §8.1.3 — Configuration management

Test matrix
-----------
ECN-01  Single-component ECN with 3 direct parents → total_affected_parents=3.
ECN-02  Empty BOM (no relationships) → total_affected_parents=0.
ECN-03  Emergency urgency → Class_I_immediate regardless of parent count.
ECN-04  Cost calculation matches formula: parents×50 + drawings×150 + WOs×200.
ECN-05  Multiple components: parents deduped (shared parent counted once).
ECN-06  Deferred urgency, zero parents → Class_III_drawing_only.
ECN-07  Deferred urgency, nonzero parents → Class_II_rev.
ECN-08  Normal urgency, >= 20 parents → Class_I_immediate.
ECN-09  Normal urgency, 1 parent → Class_II_rev.
ECN-10  Normal urgency, zero parents → Class_III_drawing_only.
ECN-11  Drawings count: distinct drawing IDs across affected parents.
ECN-12  Work orders count: distinct WO IDs across affected parents.
ECN-13  affected_parent_tree is sorted list of unique parent PNs.
ECN-14  honest_caveat field is present and non-empty.
ECN-15  Invalid urgency raises ValueError.
ECN-16  Transitive BFS: component → sub-assembly → top-level assembly.
ECN-17  Custom cost_per_drawing_revision parameter is used in cost formula.
ECN-18  Re-export: EcnInput, EcnImpactReport, analyze_ecn_impact importable
        from kerf_plm top-level __init__.
ECN-19  Multiple ECN components, drawings linked to different parents: deduped.
ECN-20  Zero-cost ECN (no parents, drawings, or WOs): estimated_cost_usd=0.0.
"""

from __future__ import annotations

import pytest

from kerf_plm.component_whereused import BomRelationship
from kerf_plm.ecn_impact_analysis import (
    EcnInput,
    EcnImpactReport,
    analyze_ecn_impact,
    HONEST_CAVEAT,
    PARENT_REVISION_COST_USD,
    WORK_ORDER_REROUTE_COST_USD,
    CLASS_I_PARENT_THRESHOLD,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def rel(parent: str, child: str, qty: float = 1.0) -> BomRelationship:
    return BomRelationship(parent_pn=parent, child_pn=child, qty=qty)


def ecn(
    ecn_id: str = "ECN-001",
    affected: list[str] | None = None,
    description: str = "Test change",
    urgency: str = "normal",
) -> EcnInput:
    return EcnInput(
        ecn_id=ecn_id,
        affected_components=affected or [],
        change_description=description,
        urgency=urgency,
    )


# ===========================================================================
# ECN-01  Single-component ECN with 3 direct parents
# ===========================================================================

def test_ecn01_single_component_three_parents():
    """BFS upward from P-001 finds 3 direct parent assemblies."""
    rels = [
        rel("A-001", "P-001"),
        rel("A-002", "P-001"),
        rel("A-003", "P-001"),
    ]
    report = analyze_ecn_impact(
        ecn_input=ecn(affected=["P-001"]),
        bom_relationships=rels,
    )
    assert report.total_affected_parents == 3
    assert set(report.affected_parent_tree) == {"A-001", "A-002", "A-003"}


# ===========================================================================
# ECN-02  Empty BOM
# ===========================================================================

def test_ecn02_empty_bom():
    """No relationships → no parents, zero cost."""
    report = analyze_ecn_impact(
        ecn_input=ecn(affected=["P-001"]),
        bom_relationships=[],
    )
    assert report.total_affected_parents == 0
    assert report.affected_parent_tree == []
    assert report.estimated_cost_usd == 0.0


# ===========================================================================
# ECN-03  Emergency urgency → Class_I_immediate
# ===========================================================================

def test_ecn03_emergency_urgency_class_i():
    """Emergency urgency → Class_I_immediate regardless of parent count."""
    # Even with just 1 parent (below the 20-threshold), emergency → Class I.
    rels = [rel("A-001", "P-001")]
    report = analyze_ecn_impact(
        ecn_input=ecn(affected=["P-001"], urgency="emergency"),
        bom_relationships=rels,
    )
    assert report.implementation_class == "Class_I_immediate"


def test_ecn03b_emergency_zero_parents_still_class_i():
    """Emergency urgency + zero parents still → Class_I_immediate."""
    report = analyze_ecn_impact(
        ecn_input=ecn(affected=["P-999"], urgency="emergency"),
        bom_relationships=[],
    )
    assert report.implementation_class == "Class_I_immediate"


# ===========================================================================
# ECN-04  Cost calculation matches formula
# ===========================================================================

def test_ecn04_cost_formula():
    """estimated_cost_usd = parents×50 + drawings×150 + work_orders×200."""
    rels = [
        rel("A-001", "P-001"),
        rel("A-002", "P-001"),
    ]
    drawings_db = {
        "A-001": ["DWG-100", "DWG-101"],
        "A-002": ["DWG-200"],
    }
    work_orders_db = {
        "A-001": ["WO-10"],
        "A-002": ["WO-20", "WO-30"],
    }
    report = analyze_ecn_impact(
        ecn_input=ecn(affected=["P-001"]),
        bom_relationships=rels,
        drawings_db=drawings_db,
        work_orders_db=work_orders_db,
        cost_per_drawing_revision=150.0,
    )
    expected = 2 * 50.0 + 3 * 150.0 + 3 * 200.0
    assert report.estimated_cost_usd == pytest.approx(expected)


# ===========================================================================
# ECN-05  Multiple components: parents deduped
# ===========================================================================

def test_ecn05_multiple_components_parents_deduped():
    """Two ECN components sharing a common parent: parent counted once."""
    rels = [
        rel("TOP-001", "P-001"),
        rel("TOP-001", "P-002"),
        rel("TOP-002", "P-002"),
    ]
    report = analyze_ecn_impact(
        ecn_input=ecn(affected=["P-001", "P-002"]),
        bom_relationships=rels,
    )
    # TOP-001 appears in both traversals but should be counted once.
    assert report.total_affected_parents == 2
    assert set(report.affected_parent_tree) == {"TOP-001", "TOP-002"}


# ===========================================================================
# ECN-06  Deferred urgency, zero parents → Class_III
# ===========================================================================

def test_ecn06_deferred_zero_parents_class_iii():
    """Deferred urgency + zero parents → Class_III_drawing_only."""
    report = analyze_ecn_impact(
        ecn_input=ecn(affected=["P-999"], urgency="deferred"),
        bom_relationships=[],
    )
    assert report.implementation_class == "Class_III_drawing_only"


# ===========================================================================
# ECN-07  Deferred urgency, nonzero parents → Class_II_rev
# ===========================================================================

def test_ecn07_deferred_nonzero_parents_class_ii():
    """Deferred urgency + at least one parent → Class_II_rev."""
    rels = [rel("A-001", "P-001")]
    report = analyze_ecn_impact(
        ecn_input=ecn(affected=["P-001"], urgency="deferred"),
        bom_relationships=rels,
    )
    assert report.implementation_class == "Class_II_rev"


# ===========================================================================
# ECN-08  Normal urgency, >= 20 parents → Class_I_immediate
# ===========================================================================

def test_ecn08_normal_urgency_large_impact_class_i():
    """Normal urgency + >= 20 parents → Class_I_immediate."""
    rels = [rel(f"A-{i:03d}", "P-001") for i in range(CLASS_I_PARENT_THRESHOLD)]
    report = analyze_ecn_impact(
        ecn_input=ecn(affected=["P-001"], urgency="normal"),
        bom_relationships=rels,
    )
    assert report.total_affected_parents == CLASS_I_PARENT_THRESHOLD
    assert report.implementation_class == "Class_I_immediate"


# ===========================================================================
# ECN-09  Normal urgency, 1 parent → Class_II_rev
# ===========================================================================

def test_ecn09_normal_urgency_one_parent_class_ii():
    """Normal urgency + 1 parent → Class_II_rev."""
    rels = [rel("A-001", "P-001")]
    report = analyze_ecn_impact(
        ecn_input=ecn(affected=["P-001"], urgency="normal"),
        bom_relationships=rels,
    )
    assert report.implementation_class == "Class_II_rev"


# ===========================================================================
# ECN-10  Normal urgency, zero parents → Class_III
# ===========================================================================

def test_ecn10_normal_urgency_zero_parents_class_iii():
    """Normal urgency + zero parents → Class_III_drawing_only."""
    report = analyze_ecn_impact(
        ecn_input=ecn(affected=["P-999"], urgency="normal"),
        bom_relationships=[],
    )
    assert report.implementation_class == "Class_III_drawing_only"


# ===========================================================================
# ECN-11  Drawings count: distinct IDs across affected parents
# ===========================================================================

def test_ecn11_drawings_deduped():
    """Drawings shared by multiple parents are counted once."""
    rels = [
        rel("A-001", "P-001"),
        rel("A-002", "P-001"),
    ]
    # DWG-SHARED appears in both parents' drawing lists.
    drawings_db = {
        "A-001": ["DWG-SHARED", "DWG-100"],
        "A-002": ["DWG-SHARED", "DWG-200"],
    }
    report = analyze_ecn_impact(
        ecn_input=ecn(affected=["P-001"]),
        bom_relationships=rels,
        drawings_db=drawings_db,
    )
    assert report.total_affected_drawings == 3  # DWG-SHARED, DWG-100, DWG-200


# ===========================================================================
# ECN-12  Work orders count: distinct WO IDs across affected parents
# ===========================================================================

def test_ecn12_work_orders_deduped():
    """Work orders shared by multiple parents are counted once."""
    rels = [
        rel("A-001", "P-001"),
        rel("A-002", "P-001"),
    ]
    work_orders_db = {
        "A-001": ["WO-SHARED", "WO-100"],
        "A-002": ["WO-SHARED"],
    }
    report = analyze_ecn_impact(
        ecn_input=ecn(affected=["P-001"]),
        bom_relationships=rels,
        work_orders_db=work_orders_db,
    )
    assert report.total_open_work_orders == 2  # WO-SHARED, WO-100


# ===========================================================================
# ECN-13  affected_parent_tree is sorted
# ===========================================================================

def test_ecn13_affected_parent_tree_sorted():
    """affected_parent_tree is a sorted list of unique parent PNs."""
    rels = [
        rel("C-001", "P-001"),
        rel("A-001", "P-001"),
        rel("B-001", "P-001"),
    ]
    report = analyze_ecn_impact(
        ecn_input=ecn(affected=["P-001"]),
        bom_relationships=rels,
    )
    assert report.affected_parent_tree == ["A-001", "B-001", "C-001"]


# ===========================================================================
# ECN-14  honest_caveat present and non-empty
# ===========================================================================

def test_ecn14_honest_caveat_present():
    """EcnImpactReport.honest_caveat is a non-empty string."""
    report = analyze_ecn_impact(
        ecn_input=ecn(affected=["P-001"]),
        bom_relationships=[],
    )
    assert isinstance(report.honest_caveat, str)
    assert len(report.honest_caveat) > 20
    # Must mention ISO 10007 or heuristic to anchor the methodology.
    assert "ISO 10007" in report.honest_caveat or "heuristic" in report.honest_caveat.lower()


# ===========================================================================
# ECN-15  Invalid urgency raises ValueError
# ===========================================================================

def test_ecn15_invalid_urgency_raises():
    """Invalid urgency value raises ValueError."""
    with pytest.raises(ValueError, match="urgency"):
        analyze_ecn_impact(
            ecn_input=ecn(affected=["P-001"], urgency="urgent"),
            bom_relationships=[],
        )


# ===========================================================================
# ECN-16  Transitive BFS traversal
# ===========================================================================

def test_ecn16_transitive_bfs():
    """Component → sub-assembly → top-level: both sub-assembly and top found."""
    #  P-001 → SUB-001 → TOP-001 (3-level chain)
    rels = [
        rel("SUB-001", "P-001"),
        rel("TOP-001", "SUB-001"),
    ]
    report = analyze_ecn_impact(
        ecn_input=ecn(affected=["P-001"]),
        bom_relationships=rels,
    )
    assert report.total_affected_parents == 2
    assert "SUB-001" in report.affected_parent_tree
    assert "TOP-001" in report.affected_parent_tree


# ===========================================================================
# ECN-17  Custom cost_per_drawing_revision
# ===========================================================================

def test_ecn17_custom_cost_per_drawing_revision():
    """Non-default cost_per_drawing_revision is applied in cost formula."""
    rels = [rel("A-001", "P-001")]
    drawings_db = {"A-001": ["DWG-100"]}
    cost_per_rev = 500.0
    report = analyze_ecn_impact(
        ecn_input=ecn(affected=["P-001"]),
        bom_relationships=rels,
        drawings_db=drawings_db,
        cost_per_drawing_revision=cost_per_rev,
    )
    # 1 parent × $50 + 1 drawing × $500 + 0 WOs = $550
    assert report.estimated_cost_usd == pytest.approx(1 * 50.0 + 1 * 500.0)


# ===========================================================================
# ECN-18  Re-export from kerf_plm top-level
# ===========================================================================

def test_ecn18_top_level_re_export():
    """EcnInput, EcnImpactReport, analyze_ecn_impact importable from kerf_plm."""
    from kerf_plm import EcnInput as _EI, EcnImpactReport as _EIR, analyze_ecn_impact as _fn
    assert _EI is EcnInput
    assert _EIR is EcnImpactReport
    assert _fn is analyze_ecn_impact


# ===========================================================================
# ECN-19  Multiple ECN components + drawings deduped across traversals
# ===========================================================================

def test_ecn19_multiple_components_drawings_deduped():
    """Two ECN components each reaching different parents; drawings deduped."""
    rels = [
        rel("A-001", "P-001"),
        rel("A-002", "P-002"),
        rel("A-001", "P-002"),  # A-001 also used by P-002
    ]
    drawings_db = {
        "A-001": ["DWG-X"],
        "A-002": ["DWG-Y"],
    }
    report = analyze_ecn_impact(
        ecn_input=ecn(affected=["P-001", "P-002"]),
        bom_relationships=rels,
        drawings_db=drawings_db,
    )
    # Both A-001 and A-002 are affected (A-001 deduplicated).
    assert report.total_affected_parents == 2
    assert report.total_affected_drawings == 2  # DWG-X, DWG-Y


# ===========================================================================
# ECN-20  Zero-cost ECN (no parents, drawings, or WOs)
# ===========================================================================

def test_ecn20_zero_cost_no_impact():
    """ECN affecting a part with no parents, no drawings, no WOs → cost=0.0."""
    report = analyze_ecn_impact(
        ecn_input=ecn(affected=["ORPHAN-001"]),
        bom_relationships=[],
        drawings_db={"ORPHAN-001": []},
        work_orders_db={"ORPHAN-001": []},
    )
    assert report.total_affected_parents == 0
    assert report.total_affected_drawings == 0
    assert report.total_open_work_orders == 0
    assert report.estimated_cost_usd == 0.0


# ===========================================================================
# ECN-21  ecn_id is preserved in report
# ===========================================================================

def test_ecn21_ecn_id_preserved():
    """ecn_id from EcnInput is faithfully copied to EcnImpactReport."""
    report = analyze_ecn_impact(
        ecn_input=ecn(ecn_id="ECN-2026-ALPHA-42", affected=["P-001"]),
        bom_relationships=[],
    )
    assert report.ecn_id == "ECN-2026-ALPHA-42"


# ===========================================================================
# ECN-22  Empty affected_components list → zero parents, Class_III
# ===========================================================================

def test_ecn22_empty_affected_components():
    """Empty affected_components → no traversal; total_affected_parents=0."""
    rels = [rel("A-001", "P-001")]
    report = analyze_ecn_impact(
        ecn_input=ecn(affected=[], urgency="normal"),
        bom_relationships=rels,
    )
    assert report.total_affected_parents == 0
    assert report.implementation_class == "Class_III_drawing_only"
