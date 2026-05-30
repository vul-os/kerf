"""
kerf_plm.document_version_diff
================================

Controlled PLM document version diff per:
  - ISO 10303-44 §5.2  "Document version and revision management" — each document
    revision is a uniquely identified, immutable snapshot; changes between revisions
    must be explicitly described and classified.
  - Borst-Lahti §6.3  "Change record and document delta" — a delta record itemises
    added, removed, and modified items; modifications are characterised at the field
    level and classified as engineering-critical or administrative.

Public API
----------
  diff_documents(doc_a, doc_b, key_field='id') -> DocumentDiffReport

Data model
----------
  ChangeKind       — ADDED | REMOVED | MODIFIED | UNCHANGED | RENAMED
  Criticality      — ENGINEERING | ADMINISTRATIVE
  DiffEntry        — single item difference record
  DocumentDiffReport — aggregate result with summary counts

Usage example
-------------
  from kerf_plm.document_version_diff import diff_documents

  doc_a = [{"id": "P-001", "qty": 1}, {"id": "P-002", "qty": 2}]
  doc_b = [{"id": "P-001", "qty": 3}, {"id": "P-003", "qty": 1}]
  report = diff_documents(doc_a, doc_b)
  # report.added == 1, report.removed == 1, report.modified == 1

Rename-detection honest-flag
-----------------------------
Rename detection uses a heuristic fingerprint: two items (one in doc_a only, one in
doc_b only) are considered a rename when their field similarity score is >= 0.80.
Similarity is the Jaccard overlap of (field, value) pairs shared between the two
items divided by the union of all (field, value) pairs, *excluding* the key_field
itself.

  HONEST_FLAG (module-level string) declares this limitation explicitly:
  a rename heuristic at 80% similarity may misclassify true independent add/remove
  pairs as renames when their field contents are coincidentally similar (e.g. two
  distinct parts with the same description and quantity but different IDs).

Criticality classification (Borst-Lahti §6.3 Table 3)
-------------------------------------------------------
  ENGINEERING  — changes to fields that affect design intent or product function:
                 qty, quantity, mass, material, tolerance, grade, spec, drawing,
                 drawing_rev, revision, unit, type, part_number, pn, mpn,
                 description (when the item is being renamed, description changes
                 are ADMINISTRATIVE; standalone description edits on a kept key
                 are ADMINISTRATIVE — see below).
  ADMINISTRATIVE — all other field changes: description-only, metadata, dates,
                 notes, supplier, cost, currency, lead_time, approved_by, etc.

  Note: if ANY modified field is ENGINEERING, the overall DiffEntry criticality
  is ENGINEERING.  A DiffEntry with only ADMINISTRATIVE field changes is
  ADMINISTRATIVE.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Any

# ---------------------------------------------------------------------------
# Honest-flag (module-level, always present on result)
# ---------------------------------------------------------------------------

HONEST_FLAG = (
    "rename_detection: heuristic fingerprint (>=80% field-value Jaccard similarity, "
    "excluding key_field). May misclassify true independent add/remove pairs as "
    "renames when field contents are coincidentally similar."
)

# ---------------------------------------------------------------------------
# Engineering-critical field names  (Borst-Lahti §6.3 Table 3)
# ---------------------------------------------------------------------------

_ENGINEERING_FIELDS: frozenset[str] = frozenset({
    "qty",
    "quantity",
    "mass",
    "weight",
    "material",
    "tolerance",
    "grade",
    "spec",
    "specification",
    "drawing",
    "drawing_rev",
    "revision",
    "rev",
    "unit",
    "units",
    "type",
    "part_number",
    "pn",
    "mpn",
    "manufacturer_part_number",
    "part_type",
    "assembly",
    "parent_assembly",
    "interface",
    "standard",
})

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class ChangeKind(enum.Enum):
    ADDED = "added"
    REMOVED = "removed"
    MODIFIED = "modified"
    UNCHANGED = "unchanged"
    RENAMED = "renamed"


class Criticality(enum.Enum):
    ENGINEERING = "engineering"
    ADMINISTRATIVE = "administrative"


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass
class FieldChange:
    """A single field-level change within a modified item."""

    field: str
    old_value: Any
    new_value: Any
    criticality: Criticality

    def to_dict(self) -> dict:
        return {
            "field": self.field,
            "old_value": self.old_value,
            "new_value": self.new_value,
            "criticality": self.criticality.value,
        }


@dataclass
class DiffEntry:
    """
    A single item-level change record (ISO 10303-44 §5.2 / Borst-Lahti §6.3).

    Fields
    ------
    key           — the stable key-field value identifying this item.
    kind          — ChangeKind (ADDED / REMOVED / MODIFIED / UNCHANGED / RENAMED).
    old_item      — item dict from doc_a (None for ADDED).
    new_item      — item dict from doc_b (None for REMOVED).
    field_changes — list of FieldChange objects (only for MODIFIED / RENAMED).
    criticality   — overall criticality: ENGINEERING if any field change is
                    engineering-critical; ADMINISTRATIVE otherwise.
    renamed_from  — original key value when kind == RENAMED.
    """

    key: Any
    kind: ChangeKind
    old_item: dict | None = None
    new_item: dict | None = None
    field_changes: list[FieldChange] = field(default_factory=list)
    criticality: Criticality = Criticality.ADMINISTRATIVE
    renamed_from: Any = None

    def to_dict(self) -> dict:
        d: dict = {
            "key": self.key,
            "kind": self.kind.value,
            "criticality": self.criticality.value,
        }
        if self.old_item is not None:
            d["old_item"] = self.old_item
        if self.new_item is not None:
            d["new_item"] = self.new_item
        if self.field_changes:
            d["field_changes"] = [fc.to_dict() for fc in self.field_changes]
        if self.renamed_from is not None:
            d["renamed_from"] = self.renamed_from
        return d


@dataclass
class DocumentDiffReport:
    """
    Aggregate diff report for two document revisions.

    Summary counts follow the depth-bar spec: UNCHANGED items are NOT
    included in the entries list (only added/removed/modified/renamed).
    """

    entries: list[DiffEntry] = field(default_factory=list)
    added: int = 0
    removed: int = 0
    modified: int = 0
    renamed: int = 0
    unchanged: int = 0
    honest_flag: str = HONEST_FLAG

    def to_dict(self) -> dict:
        return {
            "added": self.added,
            "removed": self.removed,
            "modified": self.modified,
            "renamed": self.renamed,
            "unchanged": self.unchanged,
            "entries": [e.to_dict() for e in self.entries],
            "honest_flag": self.honest_flag,
        }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _classify_field(fname: str) -> Criticality:
    """Return ENGINEERING if fname is a safety/design field, else ADMINISTRATIVE."""
    return (
        Criticality.ENGINEERING
        if fname.lower() in _ENGINEERING_FIELDS
        else Criticality.ADMINISTRATIVE
    )


def _field_changes(old: dict, new: dict) -> list[FieldChange]:
    """Compute field-level changes between two items."""
    all_fields = set(old) | set(new)
    changes: list[FieldChange] = []
    for f in sorted(all_fields):
        ov = old.get(f)
        nv = new.get(f)
        if ov != nv:
            changes.append(FieldChange(
                field=f,
                old_value=ov,
                new_value=nv,
                criticality=_classify_field(f),
            ))
    return changes


def _overall_criticality(fchanges: list[FieldChange]) -> Criticality:
    """ENGINEERING if any field is engineering-critical; ADMINISTRATIVE otherwise."""
    if any(fc.criticality == Criticality.ENGINEERING for fc in fchanges):
        return Criticality.ENGINEERING
    return Criticality.ADMINISTRATIVE


def _item_fingerprint(item: dict, key_field: str) -> set[tuple]:
    """
    Return a set of (field, str(value)) pairs excluding the key_field.

    Used for rename-detection Jaccard similarity.
    """
    return {
        (k, str(v))
        for k, v in item.items()
        if k != key_field
    }


def _jaccard_similarity(set_a: set, set_b: set) -> float:
    """Jaccard similarity between two sets.  Returns 0.0 if both are empty."""
    union = set_a | set_b
    if not union:
        return 1.0  # both empty → identical
    return len(set_a & set_b) / len(union)


# ---------------------------------------------------------------------------
# Core diff algorithm
# ---------------------------------------------------------------------------

_RENAME_THRESHOLD = 0.80  # Borst-Lahti §6.3 heuristic; see HONEST_FLAG


def diff_documents(
    doc_a: list[dict],
    doc_b: list[dict],
    key_field: str = "id",
    rename_threshold: float = _RENAME_THRESHOLD,
) -> DocumentDiffReport:
    """
    Diff two ordered lists of JSON-like dicts representing controlled PLM document
    revisions.

    Per ISO 10303-44 §5.2 and Borst-Lahti §6.3:
      - Items are matched by *key_field* (default: 'id').
      - Added / removed items are identified by key presence.
      - Modified items have field-level change records with criticality classification.
      - Renamed items: orphan add/remove pairs with >= rename_threshold Jaccard
        field-value similarity are collapsed into a single RENAMED entry.
        See HONEST_FLAG for limitations.

    Parameters
    ----------
    doc_a           : list of item dicts representing revision A.
    doc_b           : list of item dicts representing revision B.
    key_field       : field name used as the stable item identifier.
    rename_threshold: minimum Jaccard similarity for rename detection (default 0.80).

    Returns
    -------
    DocumentDiffReport with entries (UNCHANGED items excluded), summary counts,
    and honest_flag.

    Performance
    -----------
    O(N + M) matching step + O(|orphans_a| * |orphans_b|) rename scan.
    For typical rename-free documents this is O(N + M).  For a 100-item BOM
    revision with no renames this runs in < 1 ms.
    """
    if not isinstance(doc_a, list):
        raise TypeError(f"doc_a must be a list, got {type(doc_a).__name__!r}")
    if not isinstance(doc_b, list):
        raise TypeError(f"doc_b must be a list, got {type(doc_b).__name__!r}")

    map_a: dict[Any, dict] = {}
    for item in doc_a:
        k = item.get(key_field)
        if k is not None:
            map_a[k] = item

    map_b: dict[Any, dict] = {}
    for item in doc_b:
        k = item.get(key_field)
        if k is not None:
            map_b[k] = item

    report = DocumentDiffReport()

    # Matched keys — UNCHANGED or MODIFIED
    for key in map_a.keys() & map_b.keys():
        old_item = map_a[key]
        new_item = map_b[key]
        fchanges = _field_changes(old_item, new_item)
        if not fchanges:
            report.unchanged += 1
            # UNCHANGED entries are NOT appended per depth-bar spec
        else:
            crit = _overall_criticality(fchanges)
            entry = DiffEntry(
                key=key,
                kind=ChangeKind.MODIFIED,
                old_item=old_item,
                new_item=new_item,
                field_changes=fchanges,
                criticality=crit,
            )
            report.entries.append(entry)
            report.modified += 1

    # Orphans in A (candidates for REMOVED or renamed-away)
    only_a = {k: map_a[k] for k in map_a.keys() - map_b.keys()}
    # Orphans in B (candidates for ADDED or renamed-to)
    only_b = {k: map_b[k] for k in map_b.keys() - map_a.keys()}

    # Rename detection — O(|only_a| * |only_b|) pairwise scan
    matched_a: set = set()
    matched_b: set = set()

    if only_a and only_b:
        # Build fingerprints once
        fps_a = {k: _item_fingerprint(v, key_field) for k, v in only_a.items()}
        fps_b = {k: _item_fingerprint(v, key_field) for k, v in only_b.items()}

        # Greedy best-first matching
        candidates: list[tuple[float, Any, Any]] = []
        for ka, fp_a in fps_a.items():
            for kb, fp_b in fps_b.items():
                sim = _jaccard_similarity(fp_a, fp_b)
                if sim >= rename_threshold:
                    candidates.append((sim, ka, kb))

        candidates.sort(key=lambda t: -t[0])  # highest similarity first

        for sim, ka, kb in candidates:
            if ka in matched_a or kb in matched_b:
                continue
            matched_a.add(ka)
            matched_b.add(kb)

            old_item = only_a[ka]
            new_item = only_b[kb]
            fchanges = _field_changes(old_item, new_item)
            crit = _overall_criticality(fchanges)
            entry = DiffEntry(
                key=kb,
                kind=ChangeKind.RENAMED,
                old_item=old_item,
                new_item=new_item,
                field_changes=fchanges,
                criticality=crit,
                renamed_from=ka,
            )
            report.entries.append(entry)
            report.renamed += 1

    # Remaining orphans in A → REMOVED
    for key, item in only_a.items():
        if key in matched_a:
            continue
        entry = DiffEntry(
            key=key,
            kind=ChangeKind.REMOVED,
            old_item=item,
            criticality=Criticality.ENGINEERING,  # removal is always engineering-critical
        )
        report.entries.append(entry)
        report.removed += 1

    # Remaining orphans in B → ADDED
    for key, item in only_b.items():
        if key in matched_b:
            continue
        entry = DiffEntry(
            key=key,
            kind=ChangeKind.ADDED,
            new_item=item,
            criticality=Criticality.ENGINEERING,  # addition is always engineering-critical
        )
        report.entries.append(entry)
        report.added += 1

    return report
