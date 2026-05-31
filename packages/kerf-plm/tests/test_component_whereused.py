"""
tests/test_component_whereused.py
==================================

Validation tests for kerf_plm.component_whereused.

References
----------
- ISO 10303-44:2021 (STEP AP44 product structure)
- APICS Dictionary 16th ed. — "where-used"
- PROSTEP-iViP Smart Systems Engineering SIG §5.2

Test matrix
-----------
WU-01  Single direct parent, qty=2 → one entry, level=1, qty=2.
WU-02  Three-level chain: P0 → A1 → A2 → A3 → query P0 yields levels 1, 2, 3.
WU-03  Multiple direct parents: P0 in both A1 and B1 → 2 entries, both level=1.
WU-04  Cycle detection: A→B, B→A raises ValueError.
WU-05  Empty: component has no parents → num_unique_parents=0, entries=[].
WU-06  Component not in any relationship → num_unique_parents=0.
WU-07  qty aggregation: two rows same (parent, child) → summed qty.
WU-08  Diamond BOM: P0 → A1, P0 → A2, A1 → A3, A2 → A3 → A3 at level=2,
       found via BFS shallowest path first.
WU-09  names dict populates parent_name on entries.
WU-10  names=None → parent_name is None on all entries.
WU-11  num_total_usages = sum of all entry qty values.
WU-12  max_depth is correct on a 4-level hierarchy.
WU-13  Entries are sorted by (level, parent_pn).
WU-14  Re-export: BomRelationship, WhereUsedEntry, WhereUsedReport,
       find_component_whereused importable from kerf_plm top-level.
WU-15  Self-referential cycle (A uses A) raises ValueError.
WU-16  Large flat BOM: 50 separate assemblies each using the same bolt.
WU-17  honest_caveat field is present and non-empty.
"""

from __future__ import annotations

import pytest

from kerf_plm.component_whereused import (
    BomRelationship,
    WhereUsedEntry,
    WhereUsedReport,
    find_component_whereused,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def rel(parent: str, child: str, qty: float = 1.0) -> BomRelationship:
    return BomRelationship(parent_pn=parent, child_pn=child, qty=qty)


# ===========================================================================
# WU-01  Single direct parent, qty=2
# ===========================================================================

def test_wu01_single_direct_parent():
    """Single direct parent with qty=2 → one entry at level=1."""
    rels = [rel("ASSY-001", "BOLT-M8", qty=2.0)]
    report = find_component_whereused("BOLT-M8", rels)

    assert report.component_pn == "BOLT-M8"
    assert report.num_unique_parents == 1
    assert report.max_depth == 1
    assert len(report.entries) == 1

    entry = report.entries[0]
    assert entry.parent_pn == "ASSY-001"
    assert entry.qty == 2.0
    assert entry.level == 1


# ===========================================================================
# WU-02  Three-level chain
# ===========================================================================

def test_wu02_three_level_chain():
    """P0 → A1 → A2 → A3: query P0 yields A1 (level=1), A2 (level=2), A3 (level=3)."""
    rels = [
        rel("A1", "P0"),
        rel("A2", "A1"),
        rel("A3", "A2"),
    ]
    report = find_component_whereused("P0", rels)

    assert report.num_unique_parents == 3
    assert report.max_depth == 3

    by_pn = {e.parent_pn: e for e in report.entries}
    assert by_pn["A1"].level == 1
    assert by_pn["A2"].level == 2
    assert by_pn["A3"].level == 3


# ===========================================================================
# WU-03  Multiple direct parents
# ===========================================================================

def test_wu03_multiple_direct_parents():
    """P0 used in both A1 and B1 → 2 entries, both level=1."""
    rels = [
        rel("A1", "P0", qty=4.0),
        rel("B1", "P0", qty=1.0),
    ]
    report = find_component_whereused("P0", rels)

    assert report.num_unique_parents == 2
    assert report.max_depth == 1

    pns = {e.parent_pn for e in report.entries}
    assert pns == {"A1", "B1"}

    for entry in report.entries:
        assert entry.level == 1


# ===========================================================================
# WU-04  Cycle detection
# ===========================================================================

def test_wu04_cycle_detection():
    """A→B, B→A raises ValueError with cycle information."""
    rels = [
        rel("A", "B"),
        rel("B", "A"),
    ]
    with pytest.raises(ValueError, match="Cycle"):
        find_component_whereused("A", rels)


# ===========================================================================
# WU-05  Empty: no parents
# ===========================================================================

def test_wu05_empty_no_parents():
    """Component with no relationships → empty report."""
    rels = [rel("ASSY-X", "OTHER-PART")]
    report = find_component_whereused("BOLT-M8", rels)

    assert report.num_unique_parents == 0
    assert report.num_total_usages == 0
    assert report.max_depth == 0
    assert report.entries == []


# ===========================================================================
# WU-06  Component not referenced at all
# ===========================================================================

def test_wu06_component_not_referenced():
    """Component absent from all relationships → empty report."""
    rels = [rel("ASSY-1", "PART-X")]
    report = find_component_whereused("UNKNOWN-PN", rels)

    assert report.num_unique_parents == 0
    assert report.entries == []


# ===========================================================================
# WU-07  qty aggregation: duplicate rows summed
# ===========================================================================

def test_wu07_qty_aggregation():
    """Two rows with same (parent, child) → qty summed into single entry."""
    rels = [
        rel("ASSY-001", "BOLT-M8", qty=2.0),
        rel("ASSY-001", "BOLT-M8", qty=3.0),  # second row for the same pair
    ]
    report = find_component_whereused("BOLT-M8", rels)

    assert report.num_unique_parents == 1
    entry = report.entries[0]
    assert entry.qty == 5.0  # 2 + 3


# ===========================================================================
# WU-08  Diamond BOM — BFS shallowest level wins
# ===========================================================================

def test_wu08_diamond_bom():
    """Diamond: P0 → A1, P0 → A2, A1 → ROOT, A2 → ROOT.
    ROOT reachable from P0 at level=2 via two paths; BFS records level=2 once."""
    rels = [
        rel("A1", "P0"),
        rel("A2", "P0"),
        rel("ROOT", "A1"),
        rel("ROOT", "A2"),
    ]
    report = find_component_whereused("P0", rels)

    by_pn = {e.parent_pn: e for e in report.entries}
    assert "A1" in by_pn
    assert "A2" in by_pn
    assert "ROOT" in by_pn
    # ROOT is at level=2 via both A1 and A2; BFS sees it once at level=2
    assert by_pn["ROOT"].level == 2
    # Total unique parents: A1, A2, ROOT
    assert report.num_unique_parents == 3


# ===========================================================================
# WU-09  names dict populates parent_name
# ===========================================================================

def test_wu09_names_dict():
    """names dict maps parent_pn → human-readable name."""
    rels = [rel("ASSY-001", "BOLT-M8", qty=4.0)]
    names = {"ASSY-001": "Main Bracket Assembly"}
    report = find_component_whereused("BOLT-M8", rels, names=names)

    assert report.entries[0].parent_name == "Main Bracket Assembly"


# ===========================================================================
# WU-10  names=None → parent_name is None
# ===========================================================================

def test_wu10_names_none():
    """When names is None, parent_name is None on all entries."""
    rels = [rel("ASSY-001", "BOLT-M8")]
    report = find_component_whereused("BOLT-M8", rels, names=None)

    assert report.entries[0].parent_name is None


# ===========================================================================
# WU-11  num_total_usages
# ===========================================================================

def test_wu11_num_total_usages():
    """num_total_usages = sum of all entry qty values across all levels."""
    rels = [
        rel("A1", "P0", qty=3.0),
        rel("A2", "P0", qty=2.0),
        rel("A3", "A1", qty=5.0),
    ]
    report = find_component_whereused("P0", rels)

    # Entries: A1 (qty=3), A2 (qty=2), A3 (qty=5) → sum=10
    total = sum(e.qty for e in report.entries)
    assert report.num_total_usages == int(total)
    assert report.num_total_usages == 10


# ===========================================================================
# WU-12  max_depth on a 4-level hierarchy
# ===========================================================================

def test_wu12_max_depth_four_levels():
    """4-level chain: P0 → L1 → L2 → L3 → L4 → max_depth == 4."""
    rels = [
        rel("L1", "P0"),
        rel("L2", "L1"),
        rel("L3", "L2"),
        rel("L4", "L3"),
    ]
    report = find_component_whereused("P0", rels)
    assert report.max_depth == 4


# ===========================================================================
# WU-13  Entries sorted by (level, parent_pn)
# ===========================================================================

def test_wu13_entries_sorted():
    """Entries are sorted by level ascending then parent_pn lexicographically."""
    rels = [
        rel("Z-ASSY", "PART"),
        rel("A-ASSY", "PART"),
        rel("M-ASSY", "PART"),
    ]
    report = find_component_whereused("PART", rels)

    pns = [e.parent_pn for e in report.entries]
    assert pns == sorted(pns), f"Expected sorted by pn: {pns}"

    levels = [e.level for e in report.entries]
    assert levels == sorted(levels), f"Expected sorted by level: {levels}"


# ===========================================================================
# WU-14  Re-export from kerf_plm top-level
# ===========================================================================

def test_wu14_reexport_from_kerf_plm():
    """BomRelationship, WhereUsedEntry, WhereUsedReport, find_component_whereused
    are importable from the kerf_plm top-level package."""
    from kerf_plm import (
        BomRelationship as BR,
        WhereUsedEntry as WUE,
        WhereUsedReport as WUR,
        find_component_whereused as fwu,
    )
    assert BR is BomRelationship
    assert WUE is WhereUsedEntry
    assert WUR is WhereUsedReport
    assert fwu is find_component_whereused


# ===========================================================================
# WU-15  Self-referential cycle
# ===========================================================================

def test_wu15_self_referential_cycle():
    """An assembly that uses itself raises ValueError (BOM invariant violation)."""
    rels = [rel("ASSY-X", "ASSY-X")]
    with pytest.raises(ValueError, match="Cycle"):
        find_component_whereused("ASSY-X", rels)


# ===========================================================================
# WU-16  Large flat BOM: 50 assemblies all using the same bolt
# ===========================================================================

def test_wu16_large_flat_bom():
    """50 separate assemblies each using BOLT-M6 → 50 entries, all level=1."""
    bolt = "BOLT-M6"
    rels = [rel(f"ASSY-{i:03d}", bolt, qty=float(i + 1)) for i in range(50)]
    report = find_component_whereused(bolt, rels)

    assert report.num_unique_parents == 50
    assert report.max_depth == 1
    for entry in report.entries:
        assert entry.level == 1


# ===========================================================================
# WU-17  honest_caveat is present and non-empty
# ===========================================================================

def test_wu17_honest_caveat_present():
    """WhereUsedReport always carries a non-empty honest_caveat string."""
    rels = [rel("ASSY-001", "PART-X")]
    report = find_component_whereused("PART-X", rels)

    assert isinstance(report.honest_caveat, str)
    assert len(report.honest_caveat) > 10
    # Caveat should mention in-memory or ISO 10303-44
    assert "in-memory" in report.honest_caveat.lower() or "ISO 10303" in report.honest_caveat
