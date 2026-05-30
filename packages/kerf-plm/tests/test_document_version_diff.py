"""
tests/test_document_version_diff.py
=====================================

Validation tests for kerf_plm.document_version_diff.

ISO 10303-44 §5.2 document version control + Borst-Lahti §6.3 change record.

Test index
----------
T01  Depth-bar: 5-item BOM rev A→B: 1 added, 1 removed, 1 modified, 2 unchanged
     → report: 1 added, 1 removed, 1 modified, unchanged count=2, 0 renamed.
T02  All unchanged — no entries emitted, unchanged=N.
T03  All added (empty A).
T04  All removed (empty B).
T05  Modified qty → criticality ENGINEERING.
T06  Modified description only → criticality ADMINISTRATIVE.
T07  Nested dict field change detected (field-level).
T08  Renamed item detected by high field-value similarity (>=80%).
T09  No rename when similarity below threshold (two unrelated items).
T10  Multiple renames resolved greedily (best similarity first; no double-match).
T11  Empty A and B → empty report.
T12  HONEST_FLAG present on DocumentDiffReport.
T13  Bad args to tool layer → BAD_ARGS code.
T14  Tool layer: valid round-trip JSON for depth-bar BOM.
T15  100-item BOM diff completes in < 1 second.
T16  Removal criticality is always ENGINEERING.
T17  Addition criticality is always ENGINEERING.
T18  Mixed field changes (admin + engineering) → overall criticality ENGINEERING.
T19  rename_threshold below match threshold disables rename detection.
T20  key_field override (use 'pn' instead of 'id').
"""

from __future__ import annotations

import asyncio
import json
import time

import pytest

from kerf_plm.document_version_diff import (
    ChangeKind,
    Criticality,
    DiffEntry,
    DocumentDiffReport,
    HONEST_FLAG,
    diff_documents,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _ctx():
    try:
        from kerf_plm._compat import ProjectCtx
        return ProjectCtx()
    except ImportError:
        return None


# ---------------------------------------------------------------------------
# T01 — Depth-bar: 5-item BOM rev A→B
# ---------------------------------------------------------------------------

def test_depth_bar_5_item_bom():
    """
    Depth-bar per spec: 5-item BOM A→B.
    Item P-001: unchanged (qty=1 in both)
    Item P-002: unchanged (qty=2 in both)
    Item P-003: modified (qty 3→5)
    Item P-004: removed (present in A, absent in B)
    Item P-005: added (absent in A, present in B)
    Expected: added=1, removed=1, modified=1, unchanged=2, renamed=0.
    """
    doc_a = [
        {"id": "P-001", "description": "Bolt", "qty": 1},
        {"id": "P-002", "description": "Nut", "qty": 2},
        {"id": "P-003", "description": "Bracket", "qty": 3},
        {"id": "P-004", "description": "Washer", "qty": 4},
    ]
    doc_b = [
        {"id": "P-001", "description": "Bolt", "qty": 1},
        {"id": "P-002", "description": "Nut", "qty": 2},
        {"id": "P-003", "description": "Bracket", "qty": 5},  # modified
        {"id": "P-005", "description": "Pin", "qty": 1},      # added
    ]
    report = diff_documents(doc_a, doc_b)

    assert report.added == 1
    assert report.removed == 1
    assert report.modified == 1
    assert report.unchanged == 2
    assert report.renamed == 0

    # UNCHANGED items are NOT in entries
    entry_keys = {e.key for e in report.entries}
    assert "P-001" not in entry_keys
    assert "P-002" not in entry_keys

    kinds = {e.key: e.kind for e in report.entries}
    assert kinds["P-003"] == ChangeKind.MODIFIED
    assert kinds["P-004"] == ChangeKind.REMOVED
    assert kinds["P-005"] == ChangeKind.ADDED


# ---------------------------------------------------------------------------
# T02 — All unchanged
# ---------------------------------------------------------------------------

def test_all_unchanged():
    doc = [{"id": f"P-{i:03d}", "qty": i} for i in range(1, 11)]
    report = diff_documents(doc, doc)
    assert report.added == 0
    assert report.removed == 0
    assert report.modified == 0
    assert report.unchanged == 10
    assert report.entries == []


# ---------------------------------------------------------------------------
# T03 — All added (empty A)
# ---------------------------------------------------------------------------

def test_all_added():
    doc_b = [{"id": "P-001", "qty": 1}, {"id": "P-002", "qty": 2}]
    report = diff_documents([], doc_b)
    assert report.added == 2
    assert report.removed == 0
    assert report.modified == 0
    assert report.unchanged == 0


# ---------------------------------------------------------------------------
# T04 — All removed (empty B)
# ---------------------------------------------------------------------------

def test_all_removed():
    doc_a = [{"id": "P-001", "qty": 1}, {"id": "P-002", "qty": 2}]
    report = diff_documents(doc_a, [])
    assert report.removed == 2
    assert report.added == 0
    assert report.modified == 0


# ---------------------------------------------------------------------------
# T05 — Modified qty → criticality ENGINEERING
# ---------------------------------------------------------------------------

def test_modified_qty_is_engineering():
    doc_a = [{"id": "P-001", "qty": 1}]
    doc_b = [{"id": "P-001", "qty": 3}]
    report = diff_documents(doc_a, doc_b)
    assert report.modified == 1
    entry = report.entries[0]
    assert entry.kind == ChangeKind.MODIFIED
    assert entry.criticality == Criticality.ENGINEERING
    assert len(entry.field_changes) == 1
    fc = entry.field_changes[0]
    assert fc.field == "qty"
    assert fc.old_value == 1
    assert fc.new_value == 3
    assert fc.criticality == Criticality.ENGINEERING


# ---------------------------------------------------------------------------
# T06 — Modified description only → criticality ADMINISTRATIVE
# ---------------------------------------------------------------------------

def test_modified_description_is_administrative():
    doc_a = [{"id": "P-001", "description": "Old Bolt", "qty": 1}]
    doc_b = [{"id": "P-001", "description": "New Bolt M5", "qty": 1}]
    report = diff_documents(doc_a, doc_b)
    assert report.modified == 1
    entry = report.entries[0]
    assert entry.criticality == Criticality.ADMINISTRATIVE
    assert len(entry.field_changes) == 1
    assert entry.field_changes[0].criticality == Criticality.ADMINISTRATIVE


# ---------------------------------------------------------------------------
# T07 — Nested document diff (nested dict values compared as equal/not-equal)
# ---------------------------------------------------------------------------

def test_nested_document_diff():
    """Nested dicts are compared by equality; a nested change registers as modified."""
    doc_a = [{"id": "D-001", "spec": {"tensile": 400, "yield": 250}}]
    doc_b = [{"id": "D-001", "spec": {"tensile": 450, "yield": 250}}]
    report = diff_documents(doc_a, doc_b)
    assert report.modified == 1
    entry = report.entries[0]
    assert entry.kind == ChangeKind.MODIFIED
    assert any(fc.field == "spec" for fc in entry.field_changes)


# ---------------------------------------------------------------------------
# T08 — Renamed item detected (high similarity)
# ---------------------------------------------------------------------------

def test_renamed_item_detected():
    """
    P-001 in A with same description/material/qty but different id matches P-099 in B.
    Similarity should be >=0.80 → detected as RENAMED.
    """
    doc_a = [{"id": "P-001", "description": "Hex Bolt M6", "material": "Steel", "qty": 4}]
    doc_b = [{"id": "P-099", "description": "Hex Bolt M6", "material": "Steel", "qty": 4}]
    report = diff_documents(doc_a, doc_b)
    assert report.renamed == 1
    assert report.added == 0
    assert report.removed == 0
    entry = report.entries[0]
    assert entry.kind == ChangeKind.RENAMED
    assert entry.renamed_from == "P-001"
    assert entry.key == "P-099"


# ---------------------------------------------------------------------------
# T09 — No rename when dissimilar (two unrelated items)
# ---------------------------------------------------------------------------

def test_no_rename_when_dissimilar():
    """
    Bolt removed and completely different Pin added → no rename.
    Jaccard similarity ~0.0 (disjoint field values).
    """
    doc_a = [{"id": "P-001", "description": "Hex Bolt M6", "material": "Steel", "qty": 4}]
    doc_b = [{"id": "P-002", "description": "Spring Pin 3mm", "material": "Brass", "qty": 1}]
    report = diff_documents(doc_a, doc_b)
    assert report.renamed == 0
    assert report.removed == 1
    assert report.added == 1


# ---------------------------------------------------------------------------
# T10 — Multiple renames: greedy best-first, no double-match
# ---------------------------------------------------------------------------

def test_multiple_renames_greedy():
    """
    Two pairs: (P-001, P-100) and (P-002, P-200) are high-similarity renames.
    """
    doc_a = [
        {"id": "P-001", "description": "Bolt M6", "material": "Steel", "qty": 4},
        {"id": "P-002", "description": "Nut M6", "material": "Zinc", "qty": 4},
    ]
    doc_b = [
        {"id": "P-100", "description": "Bolt M6", "material": "Steel", "qty": 4},
        {"id": "P-200", "description": "Nut M6", "material": "Zinc", "qty": 4},
    ]
    report = diff_documents(doc_a, doc_b)
    assert report.renamed == 2
    assert report.added == 0
    assert report.removed == 0


# ---------------------------------------------------------------------------
# T11 — Empty A and B
# ---------------------------------------------------------------------------

def test_empty_documents():
    report = diff_documents([], [])
    assert report.added == 0
    assert report.removed == 0
    assert report.modified == 0
    assert report.unchanged == 0
    assert report.entries == []


# ---------------------------------------------------------------------------
# T12 — HONEST_FLAG present
# ---------------------------------------------------------------------------

def test_honest_flag_present():
    report = diff_documents([], [])
    assert report.honest_flag == HONEST_FLAG
    assert "rename" in report.honest_flag.lower()
    assert "heuristic" in report.honest_flag.lower()


# ---------------------------------------------------------------------------
# T13 — Tool layer BAD_ARGS
# ---------------------------------------------------------------------------

def test_tool_bad_args_doc_a_not_list():
    from kerf_plm._tools_module import run_plm_document_version_diff
    result_json = run(run_plm_document_version_diff(_ctx(), json.dumps(
        {"doc_a": "not_a_list", "doc_b": []}
    ).encode()))
    result = json.loads(result_json)
    assert result.get("code") == "BAD_ARGS"


def test_tool_bad_args_missing_doc_b():
    from kerf_plm._tools_module import run_plm_document_version_diff
    result_json = run(run_plm_document_version_diff(_ctx(), json.dumps(
        {"doc_a": []}
    ).encode()))
    result = json.loads(result_json)
    # doc_b defaults to None → BAD_ARGS
    assert result.get("code") == "BAD_ARGS"


# ---------------------------------------------------------------------------
# T14 — Tool layer: valid JSON round-trip for depth-bar BOM
# ---------------------------------------------------------------------------

def test_tool_roundtrip_depth_bar():
    from kerf_plm._tools_module import run_plm_document_version_diff

    doc_a = [
        {"id": "P-001", "qty": 1},
        {"id": "P-002", "qty": 2},
        {"id": "P-003", "qty": 3},
        {"id": "P-004", "qty": 4},
    ]
    doc_b = [
        {"id": "P-001", "qty": 1},
        {"id": "P-002", "qty": 2},
        {"id": "P-003", "qty": 5},
        {"id": "P-005", "qty": 1},
    ]
    args = json.dumps({"doc_a": doc_a, "doc_b": doc_b}).encode()
    result_json = run(run_plm_document_version_diff(_ctx(), args))
    result = json.loads(result_json)
    assert "added" in result
    assert result["added"] == 1
    assert result["removed"] == 1
    assert result["modified"] == 1
    assert result["unchanged"] == 2
    assert "honest_flag" in result


# ---------------------------------------------------------------------------
# T15 — 100-item BOM diff completes in < 1 second
# ---------------------------------------------------------------------------

def test_performance_100_items():
    doc_a = [
        {"id": f"P-{i:04d}", "qty": i, "material": "Steel", "description": f"Part {i}"}
        for i in range(100)
    ]
    doc_b = [dict(item) for item in doc_a]
    doc_b.pop(50)  # remove P-0050
    doc_b.append({"id": "P-9999", "qty": 1, "material": "Brass", "description": "New Part"})
    for item in doc_b:
        if item["id"] in {f"P-{i:04d}" for i in range(0, 10)}:
            item["qty"] = item["qty"] + 100  # modify qty

    t0 = time.perf_counter()
    report = diff_documents(doc_a, doc_b)
    elapsed = time.perf_counter() - t0

    assert elapsed < 1.0, f"100-item diff took {elapsed:.3f}s, expected < 1s"
    assert report.removed == 1
    assert report.added == 1
    assert report.modified == 10


# ---------------------------------------------------------------------------
# T16 — Removal criticality is always ENGINEERING
# ---------------------------------------------------------------------------

def test_removal_is_engineering():
    doc_a = [{"id": "P-001", "description": "Administrative part", "notes": "can remove"}]
    report = diff_documents(doc_a, [])
    assert report.removed == 1
    assert report.entries[0].criticality == Criticality.ENGINEERING


# ---------------------------------------------------------------------------
# T17 — Addition criticality is always ENGINEERING
# ---------------------------------------------------------------------------

def test_addition_is_engineering():
    doc_b = [{"id": "P-001", "description": "New part", "notes": "just metadata"}]
    report = diff_documents([], doc_b)
    assert report.added == 1
    assert report.entries[0].criticality == Criticality.ENGINEERING


# ---------------------------------------------------------------------------
# T18 — Mixed field changes → overall criticality ENGINEERING
# ---------------------------------------------------------------------------

def test_mixed_fields_overall_engineering():
    doc_a = [{"id": "P-001", "description": "Old desc", "qty": 1}]
    doc_b = [{"id": "P-001", "description": "New desc", "qty": 5}]
    report = diff_documents(doc_a, doc_b)
    entry = report.entries[0]
    assert entry.criticality == Criticality.ENGINEERING
    field_crits = {fc.field: fc.criticality for fc in entry.field_changes}
    assert field_crits["description"] == Criticality.ADMINISTRATIVE
    assert field_crits["qty"] == Criticality.ENGINEERING


# ---------------------------------------------------------------------------
# T19 — Low rename_threshold: pair below threshold → pure add+remove
# ---------------------------------------------------------------------------

def test_rename_threshold_below_match():
    """
    Items have ~60% field similarity (3 of 5 non-key field-value pairs match).
    Default threshold 0.80 → no rename. Explicit 0.80 → same result.
    """
    # 4 non-key fields; 3 shared → Jaccard = 3/5 = 0.60 < 0.80
    doc_a = [{"id": "P-001", "description": "Bolt M6", "material": "Steel", "qty": 4, "grade": "8.8"}]
    doc_b = [{"id": "P-099", "description": "Bolt M6", "material": "Brass", "qty": 4, "grade": "8.8"}]

    report_default = diff_documents(doc_a, doc_b)
    assert report_default.renamed == 0
    assert report_default.removed == 1
    assert report_default.added == 1

    report_explicit = diff_documents(doc_a, doc_b, rename_threshold=0.80)
    assert report_explicit.renamed == 0


# ---------------------------------------------------------------------------
# T20 — key_field override ('pn')
# ---------------------------------------------------------------------------

def test_key_field_override():
    doc_a = [{"pn": "BLT-001", "qty": 2, "description": "Bolt"}]
    doc_b = [
        {"pn": "BLT-001", "qty": 3, "description": "Bolt"},
        {"pn": "NUT-001", "qty": 1, "description": "Nut"},
    ]
    report = diff_documents(doc_a, doc_b, key_field="pn")
    assert report.modified == 1
    assert report.added == 1
    assert report.removed == 0
    modified = next(e for e in report.entries if e.kind == ChangeKind.MODIFIED)
    assert modified.key == "BLT-001"
