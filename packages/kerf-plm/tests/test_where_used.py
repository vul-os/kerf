"""
tests/test_where_used.py
========================

Validation tests for kerf_plm.where_used.

Per PROSTEP-iViP SIG §5.2 "Where-Used Analysis" methodology.

Test matrix
-----------
WU-01  Part in exactly one assembly → 1 entry, depth=1.
WU-02  Part in three assemblies (one twice, two once) → 3 entries,
       total_occurrences == 4.
WU-03  Multiplicity: bolt used 4× in a single assembly → occurrence_count==4.
WU-04  Nested: sub-assembly A contains part P; master M contains A.
       where_used(P) → [{A, depth=1}, {M, depth=2}].
WU-05  Part not used anywhere → empty entries, no cycle.
WU-06  Cycle detection: A→B→A forms a cycle; traversal stops, cycle_detected=True.
WU-07  where_used report helpers: total_occurrences() and at_depth().
WU-08  build_where_used_graph + _traverse used separately (integration path).
"""

from __future__ import annotations

import pytest

from kerf_plm.where_used import (
    WhereUsedEntry,
    WhereUsedReport,
    build_where_used_graph,
    where_used,
)


# ---------------------------------------------------------------------------
# WU-01 — Part in exactly one assembly
# ---------------------------------------------------------------------------

def test_part_in_single_assembly():
    """Part P-001 used once in assembly A-001 → 1 entry at depth=1."""
    plm = {
        "parts": [{"id": "P-001", "label": "Shaft"}],
        "assemblies": [
            {"id": "A-001", "label": "Shaft Housing", "children": ["P-001"]},
        ],
    }
    report = where_used("P-001", plm)
    assert not report.cycle_detected
    assert len(report.entries) == 1
    entry = report.entries[0]
    assert entry.assembly_id == "A-001"
    assert entry.label == "Shaft Housing"
    assert entry.occurrence_count == 1
    assert entry.depth == 1


# ---------------------------------------------------------------------------
# WU-02 — Part in multiple assemblies with varying occurrences
# ---------------------------------------------------------------------------

def test_part_in_multiple_assemblies():
    """
    P-BOLT used in 3 assemblies:
      A-FRAME: twice
      A-COVER: once
      A-BASE:  once
    → 3 entries, total_occurrences == 4.
    """
    plm = {
        "parts": [{"id": "P-BOLT", "label": "Hex Bolt M8"}],
        "assemblies": [
            {"id": "A-FRAME", "label": "Frame Assembly",
             "children": ["P-BOLT", "P-BOLT"]},  # 2× occurrences
            {"id": "A-COVER", "label": "Cover Assembly",
             "children": ["P-BOLT"]},
            {"id": "A-BASE",  "label": "Base Assembly",
             "children": ["P-BOLT"]},
        ],
    }
    report = where_used("P-BOLT", plm)
    assert not report.cycle_detected
    assert len(report.entries) == 3

    by_id = {e.assembly_id: e for e in report.entries}
    assert by_id["A-FRAME"].occurrence_count == 2
    assert by_id["A-COVER"].occurrence_count == 1
    assert by_id["A-BASE"].occurrence_count == 1
    assert report.total_occurrences() == 4


# ---------------------------------------------------------------------------
# WU-03 — Multiplicity: 4 bolts in one assembly
# ---------------------------------------------------------------------------

def test_multiplicity_four_bolts():
    """Bolt used 4× in a single assembly → occurrence_count == 4."""
    plm = {
        "parts": [{"id": "P-BOLT"}],
        "assemblies": [
            {
                "id": "A-BRACKET",
                "label": "Bracket",
                "children": ["P-BOLT", "P-BOLT", "P-BOLT", "P-BOLT"],
            }
        ],
    }
    report = where_used("P-BOLT", plm)
    assert len(report.entries) == 1
    assert report.entries[0].occurrence_count == 4
    assert report.total_occurrences() == 4


# ---------------------------------------------------------------------------
# WU-04 — Nested assemblies (depth > 1)
# ---------------------------------------------------------------------------

def test_nested_assemblies_depth():
    """
    Hierarchy:
      M-001 (master) → A-SUB (sub-assembly) → P-001 (target part)

    where_used(P-001) should return:
      {A-SUB, depth=1, occurrence_count=1}
      {M-001, depth=2, occurrence_count=1}
    """
    plm = {
        "parts": [{"id": "P-001", "label": "Bearing"}],
        "assemblies": [
            {"id": "A-SUB",  "label": "Bearing Housing Sub-Assy",
             "children": ["P-001"]},
            {"id": "M-001",  "label": "Main Assembly",
             "children": ["A-SUB"]},
        ],
    }
    report = where_used("P-001", plm)
    assert not report.cycle_detected
    assert len(report.entries) == 2

    by_id = {e.assembly_id: e for e in report.entries}
    assert by_id["A-SUB"].depth == 1
    assert by_id["A-SUB"].occurrence_count == 1
    assert by_id["M-001"].depth == 2
    assert by_id["M-001"].occurrence_count == 1

    # Also verify sort order: shallower first
    assert report.entries[0].depth <= report.entries[1].depth


# ---------------------------------------------------------------------------
# WU-05 — Part not used anywhere
# ---------------------------------------------------------------------------

def test_part_not_used():
    """Part that appears in no assemblies → empty report."""
    plm = {
        "parts": [
            {"id": "P-ORPHAN", "label": "Unused Bracket"},
            {"id": "P-USED"},
        ],
        "assemblies": [
            {"id": "A-001", "children": ["P-USED"]},
        ],
    }
    report = where_used("P-ORPHAN", plm)
    assert not report.cycle_detected
    assert len(report.entries) == 0
    assert report.total_occurrences() == 0


# ---------------------------------------------------------------------------
# WU-06 — Cycle detection
# ---------------------------------------------------------------------------

def test_cycle_detection():
    """
    Construct a cyclic assembly structure (defensive test — should not
    occur in valid PLM data, but must be handled gracefully).

    A → B → A  (A contains B, B contains A).

    where_used(P-ROOT) should still return A and B but flag cycle_detected=True.
    """
    plm = {
        "parts": [{"id": "P-ROOT"}],
        "assemblies": [
            {"id": "A-001", "children": ["P-ROOT", "A-002"]},
            {"id": "A-002", "children": ["A-001"]},  # cycle: A-002 → A-001 → A-002
        ],
    }
    report = where_used("P-ROOT", plm)
    assert report.cycle_detected, "Cycle should be flagged"
    # Both direct assemblies should still appear
    ids = {e.assembly_id for e in report.entries}
    assert "A-001" in ids


# ---------------------------------------------------------------------------
# WU-07 — Report helper methods
# ---------------------------------------------------------------------------

def test_report_helpers():
    """total_occurrences() and at_depth() return correct values."""
    plm = {
        "parts": [{"id": "P-X"}],
        "assemblies": [
            {"id": "A-TOP",    "children": ["A-MID"]},
            {"id": "A-MID",    "children": ["P-X", "P-X"]},  # 2 occurrences
        ],
    }
    report = where_used("P-X", plm)
    # A-MID at depth=1 (2 occ), A-TOP at depth=2 (1 occ)
    assert len(report.at_depth(1)) == 1
    assert report.at_depth(1)[0].assembly_id == "A-MID"
    assert report.at_depth(1)[0].occurrence_count == 2

    assert len(report.at_depth(2)) == 1
    assert report.at_depth(2)[0].assembly_id == "A-TOP"

    assert report.total_occurrences() == 3  # 2 + 1


# ---------------------------------------------------------------------------
# WU-08 — build_where_used_graph + direct traversal integration
# ---------------------------------------------------------------------------

def test_build_graph_and_traverse_separately():
    """build_where_used_graph can be reused across multiple queries."""
    plm = {
        "parts": [
            {"id": "P-A", "label": "Part A"},
            {"id": "P-B", "label": "Part B"},
        ],
        "assemblies": [
            {"id": "ASM-1", "label": "Assembly 1", "children": ["P-A", "P-B"]},
            {"id": "ASM-2", "label": "Assembly 2", "children": ["P-A"]},
        ],
    }
    graph = build_where_used_graph(plm)

    # P-A is used in 2 assemblies
    from kerf_plm.where_used import _traverse
    r_a = _traverse("P-A", graph)
    assert len(r_a.entries) == 2

    # P-B is used in 1 assembly
    r_b = _traverse("P-B", graph)
    assert len(r_b.entries) == 1
    assert r_b.entries[0].assembly_id == "ASM-1"
