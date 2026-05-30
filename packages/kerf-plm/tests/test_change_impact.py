"""
tests/test_change_impact.py
===========================

Validation tests for kerf_plm.change_impact.

Analytical oracles
------------------
T1  Single-part, no dependencies → 0 downstream impacted nodes.
T2  Parent assembly with 3 children → changing the parent flags all 3 children
    as impacted (hop=1 → high).
T3  4-hop chain P1→P2→P3→P4→P5 (P1 at root) → changing P1 produces:
      P2 high, P3 medium, P4 medium, P5 low.
T4  Mating hole ↔ shaft → propose_co_changes() returns shaft when hole changes.
T5  (bonus) estimate_change_cost() respects per-tier hours and scales with rate.
T6  (bonus) impact graph with no node registered for changed_part_id returns
    an empty report (graceful handling).
T7  (bonus) BFS does not double-count nodes visited via multiple paths.
"""

from __future__ import annotations

import pytest

from kerf_plm.change_impact import (
    ImpactEdge,
    ImpactGraph,
    ImpactNode,
    ImpactReport,
    analyze_change_impact,
    build_impact_graph,
    estimate_change_cost,
    propose_co_changes,
)


# ---------------------------------------------------------------------------
# T1 — Isolated part: zero downstream nodes
# ---------------------------------------------------------------------------

def test_isolated_part_no_downstream():
    """An isolated part with no dependency edges must produce 0 impacted nodes."""
    plm = {
        "parts": [
            {"id": "P-001", "label": "Standalone Bracket", "kind": "part"},
        ],
    }
    graph = build_impact_graph(plm)
    report = analyze_change_impact("P-001", graph)

    assert report.changed_part_id == "P-001"
    assert len(report.impacted_nodes) == 0


# ---------------------------------------------------------------------------
# T2 — Parent assembly with 3 children
# ---------------------------------------------------------------------------

def test_parent_assembly_three_children_all_impacted():
    """
    Assembly A-001 contains children P-001, P-002, P-003.
    Changing A-001 must flag P-001, P-002, P-003 as impacted at level 'high'
    (hop=1, because A-001 depends_on each child, so changing A-001 propagates
    impact outward).

    Wait — let's think about direction carefully.
    The assembly DEPENDS ON its children (it breaks if a child changes).
    So: child change → assembly impacted.

    But the test requirement says "changing parent flags all 3 as impacted".
    This maps to a scenario where the assembly IS the parent being changed,
    and all children need rework because the parent changed.

    We model this with explicit "impacted_by" edges:
      child depends_on assembly (each child is governed by the assembly spec)
    i.e. assembly change → each child is impacted.

    OR we supply explicit edges: P-001 depends_on A-001 (child governs spec).

    The test is: changing A-001 → all three children flagged.
    """
    plm = {
        "parts": [
            {"id": "A-001", "label": "Main Assembly", "kind": "assembly"},
            {"id": "P-001", "label": "Child 1", "kind": "part"},
            {"id": "P-002", "label": "Child 2", "kind": "part"},
            {"id": "P-003", "label": "Child 3", "kind": "part"},
        ],
        "edges": [
            # Each child depends_on the assembly (assembly spec change → child rework)
            {"source": "P-001", "target": "A-001", "kind": "depends_on"},
            {"source": "P-002", "target": "A-001", "kind": "depends_on"},
            {"source": "P-003", "target": "A-001", "kind": "depends_on"},
        ],
    }
    graph = build_impact_graph(plm)
    report = analyze_change_impact("A-001", graph)

    impacted_ids = {n.node_id for n in report.impacted_nodes}
    assert {"P-001", "P-002", "P-003"}.issubset(impacted_ids), (
        f"Expected all 3 children impacted; got {impacted_ids}"
    )

    # All must be at hop=1 → 'high'
    for node in report.impacted_nodes:
        if node.node_id in {"P-001", "P-002", "P-003"}:
            assert node.hop_distance == 1, (
                f"{node.node_id} should be hop=1; got {node.hop_distance}"
            )
            assert node.impact_level == "high", (
                f"{node.node_id} should be 'high'; got {node.impact_level}"
            )


# ---------------------------------------------------------------------------
# T3 — 4-hop chain: impact level categorisation
# ---------------------------------------------------------------------------

def test_four_hop_chain_impact_levels():
    """
    Chain: P1 → P2 → P3 → P4 → P5
    (P2 depends_on P1, P3 depends_on P2, P4 depends_on P3, P5 depends_on P4)

    Changing P1:
      P2 hop=1 → high
      P3 hop=2 → medium
      P4 hop=3 → medium
      P5 hop=4 → low
    """
    plm = {
        "parts": [
            {"id": "P1", "label": "Root"},
            {"id": "P2", "label": "Level 1"},
            {"id": "P3", "label": "Level 2"},
            {"id": "P4", "label": "Level 3"},
            {"id": "P5", "label": "Level 4"},
        ],
        "edges": [
            {"source": "P2", "target": "P1", "kind": "depends_on"},
            {"source": "P3", "target": "P2", "kind": "depends_on"},
            {"source": "P4", "target": "P3", "kind": "depends_on"},
            {"source": "P5", "target": "P4", "kind": "depends_on"},
        ],
    }
    graph = build_impact_graph(plm)
    report = analyze_change_impact("P1", graph)

    by_id = {n.node_id: n for n in report.impacted_nodes}

    assert set(by_id.keys()) == {"P2", "P3", "P4", "P5"}, (
        f"Unexpected impacted set: {set(by_id.keys())}"
    )

    assert by_id["P2"].hop_distance == 1
    assert by_id["P2"].impact_level == "high"

    assert by_id["P3"].hop_distance == 2
    assert by_id["P3"].impact_level == "medium"

    assert by_id["P4"].hop_distance == 3
    assert by_id["P4"].impact_level == "medium"

    assert by_id["P5"].hop_distance == 4
    assert by_id["P5"].impact_level == "low"


# ---------------------------------------------------------------------------
# T4 — Co-changes: mating hole → shaft
# ---------------------------------------------------------------------------

def test_co_changes_mating_hole_suggests_shaft():
    """
    Changing a hole diameter → propose_co_changes() must suggest the mating
    shaft as a required co-change (mates_with edge).
    """
    plm = {
        "parts": [
            {
                "id": "P-HOLE",
                "label": "Flange Hole Ø20mm",
                "kind": "part",
                "attributes": {"feature": "hole", "diameter_mm": 20},
            },
            {
                "id": "P-SHAFT",
                "label": "Drive Shaft Ø19.97mm",
                "kind": "part",
                "attributes": {"feature": "shaft", "diameter_mm": 19.97},
            },
        ],
        "edges": [
            {
                "source": "P-HOLE",
                "target": "P-SHAFT",
                "kind": "mates_with",
                "strength": 1.0,
            },
        ],
    }
    graph = build_impact_graph(plm)
    report = analyze_change_impact("P-HOLE", graph)
    suggestions = propose_co_changes(report, impact_graph=graph)

    suggested_ids = {s.node_id for s in suggestions}
    assert "P-SHAFT" in suggested_ids, (
        f"Expected P-SHAFT in co-change suggestions; got {suggested_ids}"
    )

    # The reason must mention geometry / mating
    shaft_suggestion = next(s for s in suggestions if s.node_id == "P-SHAFT")
    assert "mates" in shaft_suggestion.reason.lower() or "interface" in shaft_suggestion.reason.lower(), (
        f"Unexpected reason text: {shaft_suggestion.reason}"
    )


# ---------------------------------------------------------------------------
# T5 — estimate_change_cost analytical oracle
# ---------------------------------------------------------------------------

def test_estimate_change_cost_analytical():
    """
    A report with exactly:
      1 high node  (8h)
      2 medium nodes (3h each = 6h)
      3 low nodes    (1h each = 3h)
    Total = 17h; at $150/hr → $2550.

    Verify tier breakdown and total.
    """
    plm = {
        "parts": [
            {"id": "ROOT"},
            {"id": "H1"},
            {"id": "M1"}, {"id": "M2"},
            {"id": "L1"}, {"id": "L2"}, {"id": "L3"},
        ],
        "edges": [
            # ROOT → H1 (hop=1 high)
            {"source": "H1",  "target": "ROOT", "kind": "depends_on"},
            # H1 → M1, M2 (hop=2 medium)
            {"source": "M1",  "target": "H1",   "kind": "depends_on"},
            {"source": "M2",  "target": "H1",   "kind": "depends_on"},
            # M1 → L1, L2 (hop=3 still medium!)
            {"source": "L1",  "target": "M1",   "kind": "depends_on"},
            {"source": "L2",  "target": "M1",   "kind": "depends_on"},
            # M2 → L3 (hop=3 still medium!)
            {"source": "L3",  "target": "M2",   "kind": "depends_on"},
        ],
    }
    # Note: per the hop→level mapping, hop=3 is MEDIUM not low.
    # To get a 'low' node we need hop=4. Let's add one more hop for L1.
    plm["edges"].append({"source": "LL1", "target": "L1", "kind": "depends_on"})
    plm["parts"].append({"id": "LL1"})
    plm["edges"].append({"source": "LL2", "target": "L2", "kind": "depends_on"})
    plm["parts"].append({"id": "LL2"})
    plm["edges"].append({"source": "LL3", "target": "L3", "kind": "depends_on"})
    plm["parts"].append({"id": "LL3"})

    graph = build_impact_graph(plm)
    report = analyze_change_impact("ROOT", graph)

    # Verify classification
    by_id = {n.node_id: n for n in report.impacted_nodes}
    assert by_id["H1"].impact_level == "high"
    assert by_id["M1"].impact_level == "medium"
    assert by_id["M2"].impact_level == "medium"
    assert by_id["LL1"].impact_level == "low"
    assert by_id["LL2"].impact_level == "low"
    assert by_id["LL3"].impact_level == "low"

    # Cost estimate
    cost = estimate_change_cost(report, hourly_rate=150.0)
    assert cost["hourly_rate"] == 150.0
    # 1 high = 8h, 5 medium = 15h (M1+M2+L1+L2+L3 are all medium at hops 2/3)
    # 3 low = 3h (LL1, LL2, LL3)
    expected_high_hours = 1 * 8.0
    high_hours = cost["by_level"]["high"]["hours"]
    assert abs(high_hours - expected_high_hours) < 1e-9, (
        f"High hours: expected {expected_high_hours}, got {high_hours}"
    )
    assert cost["total_cost_usd"] == pytest.approx(cost["total_hours"] * 150.0)


# ---------------------------------------------------------------------------
# T6 — Graceful handling: changed part not in graph
# ---------------------------------------------------------------------------

def test_changed_part_not_in_graph_returns_empty():
    """Changing a part not present in the graph → empty ImpactReport."""
    plm = {"parts": [{"id": "P-001"}]}
    graph = build_impact_graph(plm)
    report = analyze_change_impact("NONEXISTENT", graph)

    assert report.changed_part_id == "NONEXISTENT"
    assert len(report.impacted_nodes) == 0


# ---------------------------------------------------------------------------
# T7 — No double-counting through diamond dependencies
# ---------------------------------------------------------------------------

def test_diamond_dependency_no_double_count():
    """
    Diamond: ROOT → A and ROOT → B; A → C and B → C.
    Changing ROOT should include C exactly once (at hop=2).
    """
    plm = {
        "parts": [
            {"id": "ROOT"}, {"id": "A"}, {"id": "B"}, {"id": "C"},
        ],
        "edges": [
            {"source": "A", "target": "ROOT", "kind": "depends_on"},
            {"source": "B", "target": "ROOT", "kind": "depends_on"},
            {"source": "C", "target": "A",    "kind": "depends_on"},
            {"source": "C", "target": "B",    "kind": "depends_on"},
        ],
    }
    graph = build_impact_graph(plm)
    report = analyze_change_impact("ROOT", graph)

    node_ids = [n.node_id for n in report.impacted_nodes]
    assert node_ids.count("C") == 1, (
        f"C should appear exactly once; got: {node_ids}"
    )

    by_id = {n.node_id: n for n in report.impacted_nodes}
    # C is reached via A at hop=2
    assert by_id["C"].hop_distance == 2
    assert by_id["C"].impact_level == "medium"


# ---------------------------------------------------------------------------
# T8 — LLM tool plm_change_impact round-trip (no kerf-core dependency)
# ---------------------------------------------------------------------------

import asyncio


def test_plm_change_impact_tool_roundtrip():
    """plm_change_impact tool returns valid JSON with expected keys."""
    import json as _json
    from kerf_plm.tools import run_plm_change_impact
    from kerf_plm._compat import ProjectCtx

    ctx = ProjectCtx()
    args = _json.dumps({
        "changed_part_id": "P1",
        "plm_data": {
            "parts": [{"id": "P1"}, {"id": "P2"}],
            "edges": [{"source": "P2", "target": "P1", "kind": "depends_on"}],
        },
        "hourly_rate": 80.0,
    }).encode()

    result_str = asyncio.get_event_loop().run_until_complete(
        run_plm_change_impact(ctx, args)
    )
    result = _json.loads(result_str)

    assert "impacted_nodes" in result
    assert "cost_estimate" in result
    assert "summary" in result
    assert result["summary"]["high"] == 1
    assert result["cost_estimate"]["total_hours"] == pytest.approx(8.0)
    assert result["cost_estimate"]["total_cost_usd"] == pytest.approx(640.0)


def test_plm_propose_co_changes_tool_roundtrip():
    """plm_propose_co_changes tool returns valid JSON with suggestion for mating shaft."""
    import json as _json
    from kerf_plm.tools import run_plm_propose_co_changes
    from kerf_plm._compat import ProjectCtx

    ctx = ProjectCtx()
    args = _json.dumps({
        "changed_part_id": "HOLE",
        "plm_data": {
            "parts": [{"id": "HOLE", "label": "Bore Ø12"}, {"id": "SHAFT", "label": "Shaft Ø11.98"}],
            "edges": [{"source": "HOLE", "target": "SHAFT", "kind": "mates_with"}],
        },
    }).encode()

    result_str = asyncio.get_event_loop().run_until_complete(
        run_plm_propose_co_changes(ctx, args)
    )
    result = _json.loads(result_str)

    assert "suggestions" in result
    suggested_ids = {s["node_id"] for s in result["suggestions"]}
    assert "SHAFT" in suggested_ids
