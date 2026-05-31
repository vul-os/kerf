"""
kerf_plm.bom_compare_diff
=========================

Flat BOM revision comparison per ISO 10303-44 §6 (product structure change
documentation) and the PLM dictionary "BOM rev compare" definition.

Given two flat BOMs (each a list of BomLineItem records keyed by part_number),
this module computes a structured diff that classifies every line as:

  added           — part appears in new_bom only
  removed         — part appears in old_bom only
  qty_increased   — part exists in both; qty_new > qty_old
  qty_decreased   — part exists in both; qty_new < qty_old
  unchanged       — part exists in both; qty_new == qty_old

Honest caveats
--------------
- Flat BOM only: this is a one-level part-number / quantity comparison.
  No multi-level hierarchy traversal, no where-used cascade, no effectivity
  or variant expansion.  If your BOM is a structured tree, flatten it first.
- Part identity is determined solely by part_number string equality
  (case-sensitive).  No semantic normalisation (PN aliases, revision codes).
- Duplicate part_number entries in either input list are collapsed via
  last-write-wins (caller must deduplicate or use explicit revision records).
- qty_delta is signed: positive for increases, negative for decreases.
  For added/removed entries, qty_delta = +new_qty / -old_qty respectively.
- No description-change detection: if only the description field changes
  the entry is classified "unchanged" (qty governs).

References
----------
- ISO 10303-44:2021 §6 — product configuration management; BOM revision
  documentation; "NEXT_ASSEMBLY_USAGE_OCCURRENCE" change records.
- PLM Dictionary (Grigoris Kalkanis, 2020) — "BOM rev compare" definition.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


# ---------------------------------------------------------------------------
# Honest caveat
# ---------------------------------------------------------------------------

HONEST_CAVEAT = (
    "Flat BOM diff only — single-level part_number/qty comparison. "
    "No hierarchy traversal, no where-used cascade, no effectivity or variant "
    "expansion. Duplicate part_number entries collapsed (last-write-wins). "
    "Part identity by case-sensitive string equality only; no PN alias or "
    "revision normalisation. Description changes are not detected. "
    "References: ISO 10303-44:2021 §6; PLM Dictionary 'BOM rev compare'."
)


# ---------------------------------------------------------------------------
# Public dataclasses
# ---------------------------------------------------------------------------


@dataclass
class BomLineItem:
    """A single line in a flat Bill of Materials.

    Parameters
    ----------
    part_number:
        Unique part identifier, e.g. 'PN-001'.  Used as the diff key.
    qty:
        Quantity of this part in the BOM (must be a positive real number).
    description:
        Optional human-readable part description.  Not used for diff keying.
    """

    part_number: str
    qty: float
    description: Optional[str] = None

    def __post_init__(self) -> None:
        if not self.part_number:
            raise ValueError("BomLineItem.part_number must not be empty.")
        if self.qty < 0:
            raise ValueError(
                f"BomLineItem.qty must be >= 0 for part '{self.part_number}', "
                f"got {self.qty}"
            )


@dataclass
class BomDiffEntry:
    """A single entry in the BOM revision diff.

    Parameters
    ----------
    part_number:
        Part identifier.
    change_type:
        One of: 'added', 'removed', 'qty_increased', 'qty_decreased',
        'unchanged'.
    old_qty:
        Quantity in the old BOM, or None if the part was absent.
    new_qty:
        Quantity in the new BOM, or None if the part was removed.
    qty_delta:
        Signed quantity change: new_qty - old_qty.
        For 'added'   entries: +new_qty (old was absent, treated as 0).
        For 'removed' entries: -old_qty (new is absent, treated as 0).
        For unchanged: 0.0.
    """

    part_number: str
    change_type: str  # "added"|"removed"|"qty_increased"|"qty_decreased"|"unchanged"
    old_qty: Optional[float]
    new_qty: Optional[float]
    qty_delta: float


@dataclass
class BomDiffReport:
    """Structured diff report for two BOM revisions.

    Parameters
    ----------
    total_parts_old:
        Distinct part count in old_bom (after dedup).
    total_parts_new:
        Distinct part count in new_bom (after dedup).
    num_added:
        Parts present in new_bom but absent in old_bom.
    num_removed:
        Parts present in old_bom but absent in new_bom.
    num_qty_changed:
        Parts present in both BOMs with a different quantity (increased or
        decreased).
    num_unchanged:
        Parts present in both BOMs with the same quantity.
    diff_entries:
        All BomDiffEntry records, sorted by part_number for determinism.
    honest_caveat:
        Plain-English scope limitation statement.
    """

    total_parts_old: int
    total_parts_new: int
    num_added: int
    num_removed: int
    num_qty_changed: int
    num_unchanged: int
    diff_entries: list[BomDiffEntry] = field(default_factory=list)
    honest_caveat: str = HONEST_CAVEAT


# ---------------------------------------------------------------------------
# Core algorithm
# ---------------------------------------------------------------------------


def compare_boms(
    old_bom: list[BomLineItem],
    new_bom: list[BomLineItem],
) -> BomDiffReport:
    """Compare two flat BOM revisions and return a structured diff report.

    The comparison is keyed on ``part_number`` (case-sensitive).  Duplicate
    part_number entries in either list are collapsed via last-write-wins
    (the last occurrence in iteration order is used).

    Classification rules
    --------------------
    - Part in new only            → 'added'        (qty_delta = +new_qty)
    - Part in old only            → 'removed'       (qty_delta = -old_qty)
    - Part in both, qty unchanged → 'unchanged'     (qty_delta = 0.0)
    - Part in both, qty_new > qty_old → 'qty_increased' (qty_delta > 0)
    - Part in both, qty_new < qty_old → 'qty_decreased' (qty_delta < 0)

    Parameters
    ----------
    old_bom:
        Flat BOM for the older revision (list of BomLineItem).
    new_bom:
        Flat BOM for the newer revision (list of BomLineItem).

    Returns
    -------
    BomDiffReport with aggregate counts and per-line diff entries, sorted by
    part_number.
    """
    # Build keyed maps (last-write-wins for duplicate part_numbers)
    old_map: dict[str, BomLineItem] = {}
    for item in old_bom:
        old_map[item.part_number] = item

    new_map: dict[str, BomLineItem] = {}
    for item in new_bom:
        new_map[item.part_number] = item

    all_part_numbers = sorted(set(old_map) | set(new_map))

    entries: list[BomDiffEntry] = []
    num_added = 0
    num_removed = 0
    num_qty_changed = 0
    num_unchanged = 0

    for pn in all_part_numbers:
        in_old = pn in old_map
        in_new = pn in new_map

        if in_new and not in_old:
            # Added
            new_qty = new_map[pn].qty
            entries.append(
                BomDiffEntry(
                    part_number=pn,
                    change_type="added",
                    old_qty=None,
                    new_qty=new_qty,
                    qty_delta=new_qty,
                )
            )
            num_added += 1

        elif in_old and not in_new:
            # Removed
            old_qty = old_map[pn].qty
            entries.append(
                BomDiffEntry(
                    part_number=pn,
                    change_type="removed",
                    old_qty=old_qty,
                    new_qty=None,
                    qty_delta=-old_qty,
                )
            )
            num_removed += 1

        else:
            # Present in both — compare quantities
            old_qty = old_map[pn].qty
            new_qty = new_map[pn].qty
            delta = new_qty - old_qty

            if delta > 0:
                change_type = "qty_increased"
                num_qty_changed += 1
            elif delta < 0:
                change_type = "qty_decreased"
                num_qty_changed += 1
            else:
                change_type = "unchanged"
                num_unchanged += 1

            entries.append(
                BomDiffEntry(
                    part_number=pn,
                    change_type=change_type,
                    old_qty=old_qty,
                    new_qty=new_qty,
                    qty_delta=delta,
                )
            )

    return BomDiffReport(
        total_parts_old=len(old_map),
        total_parts_new=len(new_map),
        num_added=num_added,
        num_removed=num_removed,
        num_qty_changed=num_qty_changed,
        num_unchanged=num_unchanged,
        diff_entries=entries,
        honest_caveat=HONEST_CAVEAT,
    )
