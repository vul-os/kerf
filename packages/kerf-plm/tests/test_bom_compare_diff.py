"""
tests/test_bom_compare_diff.py
================================

Validation tests for kerf_plm.bom_compare_diff.

Per ISO 10303-44:2021 §6 (product structure change documentation) and the PLM
dictionary "BOM rev compare" definition.

Test matrix
-----------
BD-01  Identical BOMs: num_added=0, num_removed=0, num_qty_changed=0, num_unchanged=N.
BD-02  Completely empty BOMs: all counts zero, empty diff_entries.
BD-03  Added single part: num_added=1, correct qty_delta.
BD-04  Added multiple parts: num_added=N, all classified correctly.
BD-05  Removed single part: num_removed=1, qty_delta negative.
BD-06  Removed multiple parts: num_removed=N.
BD-07  Quantity increase: num_qty_changed=1, change_type='qty_increased', delta correct.
BD-08  Quantity decrease: num_qty_changed=1, change_type='qty_decreased', delta negative.
BD-09  Mixed diff: add + remove + qty_increased + qty_decreased + unchanged.
BD-10  Duplicate part_numbers in old_bom: last-write-wins.
BD-11  Duplicate part_numbers in new_bom: last-write-wins.
BD-12  total_parts_old / total_parts_new counts reflect deduped maps.
BD-13  diff_entries are sorted by part_number (deterministic order).
BD-14  old_qty/new_qty fields: added has old_qty=None; removed has new_qty=None.
BD-15  honest_caveat is a non-empty string.
BD-16  Re-export: BomLineItem, BomDiffEntry, BomDiffReport, compare_boms from kerf_plm.
BD-17  Fractional quantities: 2.5 items, delta = 0.5.
BD-18  Zero qty allowed in BomLineItem (qty >= 0 contract).
"""

from __future__ import annotations

import pytest

from kerf_plm.bom_compare_diff import (
    BomDiffEntry,
    BomDiffReport,
    BomLineItem,
    compare_boms,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def item(pn: str, qty: float, description: str | None = None) -> BomLineItem:
    """Convenience constructor for BomLineItem."""
    return BomLineItem(part_number=pn, qty=qty, description=description)


def by_pn(entries: list[BomDiffEntry]) -> dict[str, BomDiffEntry]:
    """Index BomDiffEntry list by part_number for easy lookup."""
    return {e.part_number: e for e in entries}


# ---------------------------------------------------------------------------
# BD-01  Identical BOMs
# ---------------------------------------------------------------------------


def test_bd01_identical_boms_no_changes():
    bom = [item("PN-A", 2.0), item("PN-B", 5.0), item("PN-C", 1.0)]
    report = compare_boms(bom, bom)

    assert report.num_added == 0
    assert report.num_removed == 0
    assert report.num_qty_changed == 0
    assert report.num_unchanged == 3
    assert report.total_parts_old == 3
    assert report.total_parts_new == 3
    assert len(report.diff_entries) == 3
    for e in report.diff_entries:
        assert e.change_type == "unchanged"
        assert e.qty_delta == 0.0


# ---------------------------------------------------------------------------
# BD-02  Empty BOMs
# ---------------------------------------------------------------------------


def test_bd02_both_empty_boms():
    report = compare_boms([], [])

    assert report.num_added == 0
    assert report.num_removed == 0
    assert report.num_qty_changed == 0
    assert report.num_unchanged == 0
    assert report.total_parts_old == 0
    assert report.total_parts_new == 0
    assert report.diff_entries == []


# ---------------------------------------------------------------------------
# BD-03  Added single part
# ---------------------------------------------------------------------------


def test_bd03_added_single_part():
    old = [item("PN-A", 2.0)]
    new = [item("PN-A", 2.0), item("PN-NEW", 4.0)]

    report = compare_boms(old, new)

    assert report.num_added == 1
    assert report.num_removed == 0
    assert report.num_qty_changed == 0
    assert report.num_unchanged == 1

    idx = by_pn(report.diff_entries)
    added = idx["PN-NEW"]
    assert added.change_type == "added"
    assert added.old_qty is None
    assert added.new_qty == 4.0
    assert added.qty_delta == 4.0


# ---------------------------------------------------------------------------
# BD-04  Added multiple parts
# ---------------------------------------------------------------------------


def test_bd04_added_multiple_parts():
    old = [item("PN-A", 1.0)]
    new = [item("PN-A", 1.0), item("PN-B", 3.0), item("PN-C", 7.0)]

    report = compare_boms(old, new)

    assert report.num_added == 2
    idx = by_pn(report.diff_entries)
    assert idx["PN-B"].change_type == "added"
    assert idx["PN-C"].change_type == "added"
    assert idx["PN-B"].qty_delta == 3.0
    assert idx["PN-C"].qty_delta == 7.0


# ---------------------------------------------------------------------------
# BD-05  Removed single part
# ---------------------------------------------------------------------------


def test_bd05_removed_single_part():
    old = [item("PN-A", 2.0), item("PN-REM", 3.0)]
    new = [item("PN-A", 2.0)]

    report = compare_boms(old, new)

    assert report.num_removed == 1
    assert report.num_added == 0

    idx = by_pn(report.diff_entries)
    removed = idx["PN-REM"]
    assert removed.change_type == "removed"
    assert removed.old_qty == 3.0
    assert removed.new_qty is None
    assert removed.qty_delta == -3.0


# ---------------------------------------------------------------------------
# BD-06  Removed multiple parts
# ---------------------------------------------------------------------------


def test_bd06_removed_multiple_parts():
    old = [item("PN-A", 1.0), item("PN-B", 2.0), item("PN-C", 3.0)]
    new = [item("PN-A", 1.0)]

    report = compare_boms(old, new)

    assert report.num_removed == 2
    idx = by_pn(report.diff_entries)
    assert idx["PN-B"].change_type == "removed"
    assert idx["PN-C"].change_type == "removed"
    assert idx["PN-B"].qty_delta == -2.0
    assert idx["PN-C"].qty_delta == -3.0


# ---------------------------------------------------------------------------
# BD-07  Quantity increase
# ---------------------------------------------------------------------------


def test_bd07_qty_increased():
    old = [item("PN-X", 2.0)]
    new = [item("PN-X", 5.0)]

    report = compare_boms(old, new)

    assert report.num_qty_changed == 1
    assert report.num_added == 0
    assert report.num_removed == 0

    e = report.diff_entries[0]
    assert e.change_type == "qty_increased"
    assert e.old_qty == 2.0
    assert e.new_qty == 5.0
    assert e.qty_delta == 3.0


# ---------------------------------------------------------------------------
# BD-08  Quantity decrease
# ---------------------------------------------------------------------------


def test_bd08_qty_decreased():
    old = [item("PN-X", 8.0)]
    new = [item("PN-X", 3.0)]

    report = compare_boms(old, new)

    assert report.num_qty_changed == 1
    e = report.diff_entries[0]
    assert e.change_type == "qty_decreased"
    assert e.old_qty == 8.0
    assert e.new_qty == 3.0
    assert e.qty_delta == -5.0


# ---------------------------------------------------------------------------
# BD-09  Mixed diff
# ---------------------------------------------------------------------------


def test_bd09_mixed_diff():
    old = [
        item("PN-UNCHANGED", 4.0),
        item("PN-INC", 2.0),
        item("PN-DEC", 10.0),
        item("PN-REMOVED", 1.0),
    ]
    new = [
        item("PN-UNCHANGED", 4.0),
        item("PN-INC", 6.0),
        item("PN-DEC", 3.0),
        item("PN-ADDED", 5.0),
    ]

    report = compare_boms(old, new)

    assert report.num_added == 1
    assert report.num_removed == 1
    assert report.num_qty_changed == 2
    assert report.num_unchanged == 1

    idx = by_pn(report.diff_entries)
    assert idx["PN-ADDED"].change_type == "added"
    assert idx["PN-REMOVED"].change_type == "removed"
    assert idx["PN-INC"].change_type == "qty_increased"
    assert idx["PN-DEC"].change_type == "qty_decreased"
    assert idx["PN-UNCHANGED"].change_type == "unchanged"


# ---------------------------------------------------------------------------
# BD-10  Duplicate part_numbers in old_bom (last-write-wins)
# ---------------------------------------------------------------------------


def test_bd10_duplicate_in_old_bom_last_write_wins():
    old = [item("PN-A", 1.0), item("PN-A", 9.0)]  # second wins → qty=9
    new = [item("PN-A", 9.0)]

    report = compare_boms(old, new)

    # After dedup, old has 1 unique part with qty=9; same as new → unchanged
    assert report.total_parts_old == 1
    assert report.num_unchanged == 1
    assert report.num_qty_changed == 0


# ---------------------------------------------------------------------------
# BD-11  Duplicate part_numbers in new_bom (last-write-wins)
# ---------------------------------------------------------------------------


def test_bd11_duplicate_in_new_bom_last_write_wins():
    old = [item("PN-B", 3.0)]
    new = [item("PN-B", 3.0), item("PN-B", 7.0)]  # second wins → qty=7

    report = compare_boms(old, new)

    assert report.total_parts_new == 1
    # old=3, new=7 → qty_increased
    e = report.diff_entries[0]
    assert e.change_type == "qty_increased"
    assert e.new_qty == 7.0
    assert e.qty_delta == 4.0


# ---------------------------------------------------------------------------
# BD-12  total_parts counts reflect deduped maps
# ---------------------------------------------------------------------------


def test_bd12_total_counts_after_dedup():
    old = [item("X", 1.0), item("X", 2.0), item("Y", 3.0)]  # dedup → 2
    new = [item("A", 5.0), item("B", 6.0), item("B", 7.0)]  # dedup → 2

    report = compare_boms(old, new)

    assert report.total_parts_old == 2
    assert report.total_parts_new == 2


# ---------------------------------------------------------------------------
# BD-13  diff_entries sorted by part_number
# ---------------------------------------------------------------------------


def test_bd13_diff_entries_sorted_by_part_number():
    old = [item("ZZZ", 1.0), item("AAA", 2.0), item("MMM", 3.0)]
    new = [item("ZZZ", 1.0), item("AAA", 2.0), item("MMM", 3.0)]

    report = compare_boms(old, new)

    part_numbers = [e.part_number for e in report.diff_entries]
    assert part_numbers == sorted(part_numbers)


# ---------------------------------------------------------------------------
# BD-14  old_qty / new_qty fields for added and removed entries
# ---------------------------------------------------------------------------


def test_bd14_old_qty_new_qty_none_fields():
    old = [item("PN-KEEP", 1.0), item("PN-GONE", 2.0)]
    new = [item("PN-KEEP", 1.0), item("PN-FRESH", 3.0)]

    report = compare_boms(old, new)
    idx = by_pn(report.diff_entries)

    # Removed: new_qty must be None
    assert idx["PN-GONE"].new_qty is None
    assert idx["PN-GONE"].old_qty == 2.0

    # Added: old_qty must be None
    assert idx["PN-FRESH"].old_qty is None
    assert idx["PN-FRESH"].new_qty == 3.0

    # Unchanged: both non-None
    assert idx["PN-KEEP"].old_qty == 1.0
    assert idx["PN-KEEP"].new_qty == 1.0


# ---------------------------------------------------------------------------
# BD-15  honest_caveat is a non-empty string
# ---------------------------------------------------------------------------


def test_bd15_honest_caveat_present():
    report = compare_boms([], [])
    assert isinstance(report.honest_caveat, str)
    assert len(report.honest_caveat) > 0


# ---------------------------------------------------------------------------
# BD-16  Re-export from kerf_plm package
# ---------------------------------------------------------------------------


def test_bd16_reexport_from_kerf_plm():
    from kerf_plm import BomDiffEntry as BDE
    from kerf_plm import BomDiffReport as BDR
    from kerf_plm import BomLineItem as BLI
    from kerf_plm import compare_boms as cb

    bom = [BLI(part_number="PN-1", qty=1.0)]
    r = cb(bom, bom)
    assert isinstance(r, BDR)
    assert r.num_unchanged == 1


# ---------------------------------------------------------------------------
# BD-17  Fractional quantities
# ---------------------------------------------------------------------------


def test_bd17_fractional_quantities():
    old = [item("PN-F", 2.0)]
    new = [item("PN-F", 2.5)]

    report = compare_boms(old, new)

    assert report.num_qty_changed == 1
    e = report.diff_entries[0]
    assert e.change_type == "qty_increased"
    assert abs(e.qty_delta - 0.5) < 1e-9


# ---------------------------------------------------------------------------
# BD-18  Zero qty allowed in BomLineItem
# ---------------------------------------------------------------------------


def test_bd18_zero_qty_allowed():
    # qty=0 is a valid zero-quantity BOM line (e.g. reference parts)
    old_item = BomLineItem(part_number="PN-Z", qty=0.0)
    new_item = BomLineItem(part_number="PN-Z", qty=2.0)

    report = compare_boms([old_item], [new_item])

    assert report.num_qty_changed == 1
    e = report.diff_entries[0]
    assert e.change_type == "qty_increased"
    assert e.qty_delta == 2.0
