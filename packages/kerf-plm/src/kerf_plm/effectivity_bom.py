"""
PLM effectivity BOM expansion -- ISO 10303-44 + Borst-Lahti ss7.4.

Implements the 150% -> 100% BOM reduction algorithm.

A *150% BOM* (max-effectivity structure) contains every *possible* line item
across all variants and time periods.  An *EffectivitySelector* represents the
concrete context (date, serial number range, configuration options) for a
specific build.  Expanding the 150% BOM against that selector produces the
*100% BOM* -- the exact set of parts and quantities valid for that build.

References
----------
* ISO 10303-44:2000 -- Industrial automation systems and integration -- Product
  data representation and exchange -- Part 44: Integrated generic resource:
  Product structure configuration (ss5.3 Effectivity model, ss6.4 BOM rollup).
* Borst, W.N. & Lahti, H., PLM Handbook (2nd ed., 2022) ss7.4 "BOM rollup
  and effectivity management".

Honest caveats (v1)
--------------------
* Option-requirement resolution is exact-match key=value only.  Complex
  AND/OR/NOT compound expressions (e.g. engine=v6 OR engine=v8 together,
  NOT trim=base) are NOT evaluated.  A line with option_requirements
  containing n entries is included only when all n entries match the
  supplied options dict (implicit AND).  Flag HONEST_FLAG documents this.
* Serial-number ranges are compared as integers when both ends and the selector
  are integer-parseable; otherwise a lexicographic compare is used.
"""

from __future__ import annotations

HONEST_FLAG = (
    "PLM-EFFECTIVITY-BOM v1: option_requirements uses implicit AND + exact "
    "key=value match only.  Complex AND/OR/NOT compound expressions are NOT "
    "supported.  Date bounds are ISO-8601 (YYYY-MM-DD).  Serial-range compare "
    "is integer-first, lexicographic fallback."
)

from dataclasses import dataclass, field
from datetime import date
from typing import Any


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class BomLine:
    """One line item in a 150% BOM structure.

    Parameters
    ----------
    part_id:
        Unique identifier for this part or sub-assembly.
    description:
        Human-readable label.
    qty:
        Base quantity per occurrence in the parent assembly.  Must be > 0.
    effective_from:
        The earliest *calendar date* on which this line is valid (inclusive).
        None means "no lower bound".
    effective_to:
        The latest *calendar date* on which this line is valid (inclusive).
        None means "no upper bound".
    serial_from:
        Earliest serial number (inclusive) at which this line is effective.
        None means "no lower bound".
    serial_to:
        Latest serial number (inclusive) at which this line is effective.
        None means "no upper bound".
    option_requirements:
        Dict of {option_key: required_value} pairs.  ALL pairs must match
        the selector's options dict for this line to be included (implicit
        AND, exact-match only -- see HONEST_FLAG).
    attributes:
        Arbitrary metadata passed through unchanged to the output.
    """

    part_id: str
    description: str = ""
    qty: float = 1.0
    effective_from: date | None = None
    effective_to: date | None = None
    serial_from: str | None = None
    serial_to: str | None = None
    option_requirements: dict[str, str] = field(default_factory=dict)
    attributes: dict[str, Any] = field(default_factory=dict)


@dataclass
class EffectivityFilter:
    """The concrete build context used to resolve a 150% BOM.

    Parameters
    ----------
    effective_date:
        Calendar date for date-effectivity filtering.  None skips date
        filtering entirely (date bounds are ignored, not treated as failures).
    serial_number:
        Serial number of the specific unit being built.  None skips serial
        filtering.
    options:
        Configuration option selections, e.g. {"engine": "v6", "trim": "sport"}.
        Lines whose option_requirements are not fully satisfied are excluded.
        An empty dict means *no options selected*; any line that requires a
        specific option value will be excluded unless its requirement is met.
    """

    effective_date: date | None = None
    serial_number: str | None = None
    options: dict[str, str] = field(default_factory=dict)


@dataclass
class ExpandedBomEntry:
    """One resolved line in the 100% BOM result."""

    part_id: str
    description: str
    qty: float
    attributes: dict[str, Any]


@dataclass
class ExpandedBom:
    """Result of a 150% -> 100% BOM expansion.

    Attributes
    ----------
    entries:
        Resolved line items in input order.
    total_qty:
        Sum of qty across all entries.
    selector:
        The EffectivityFilter that was applied.
    honest_flag:
        Human-readable caveat string (see module-level HONEST_FLAG).
    """

    entries: list[ExpandedBomEntry]
    total_qty: float
    selector: EffectivityFilter
    honest_flag: str = HONEST_FLAG

    def part_ids(self) -> list[str]:
        """Return ordered list of part IDs in the expanded BOM."""
        return [e.part_id for e in self.entries]


# ---------------------------------------------------------------------------
# Core filtering logic
# ---------------------------------------------------------------------------

def _cmp_serial(a: str, b: str) -> int:
    """Compare two serial number strings.

    Returns negative / zero / positive (like C strcmp).
    Tries integer comparison first; falls back to lexicographic.
    """
    try:
        ia, ib = int(a), int(b)
        return (ia > ib) - (ia < ib)
    except ValueError:
        return (a > b) - (a < b)


def _line_is_effective(line: BomLine, selector: EffectivityFilter) -> bool:
    """Return True iff line satisfies every active criterion in selector.

    Date filtering (ISO 10303-44 ss5.3 date-effectivity):
      A line is date-effective if effective_from <= effective_date <= effective_to,
      where missing bounds are treated as open (no constraint on that end).

    Serial-number filtering (ISO 10303-44 ss5.3 serial-effectivity):
      Analogous to date, using serial_from/serial_to as inclusive bounds.

    Option filtering (Borst-Lahti ss7.4 variant effectivity):
      Each {key: value} pair in line.option_requirements must have a
      matching entry in selector.options.  Implicit AND; exact-match only
      (see HONEST_FLAG).
    """
    # --- Date effectivity ---
    if selector.effective_date is not None:
        d = selector.effective_date
        if line.effective_from is not None and d < line.effective_from:
            return False
        if line.effective_to is not None and d > line.effective_to:
            return False

    # --- Serial-number effectivity ---
    if selector.serial_number is not None:
        sn = selector.serial_number
        if line.serial_from is not None and _cmp_serial(sn, line.serial_from) < 0:
            return False
        if line.serial_to is not None and _cmp_serial(sn, line.serial_to) > 0:
            return False

    # --- Option-requirement effectivity (implicit AND, exact-match) ---
    for opt_key, req_val in line.option_requirements.items():
        if selector.options.get(opt_key) != req_val:
            return False

    return True


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def expand_effectivity_bom(
    bom_150: list[BomLine],
    effective_date: date | None = None,
    options: dict[str, str] | None = None,
    serial_number: str | None = None,
) -> ExpandedBom:
    """Expand a 150% BOM to a 100% BOM for the given effectivity context.

    Implements ISO 10303-44 ss5.3 effectivity model + Borst-Lahti ss7.4 BOM
    rollup.  Each BomLine in bom_150 is tested against the compound
    selector; lines that pass all active criteria are included in the result.

    Parameters
    ----------
    bom_150:
        The 150% (max-effectivity) BOM -- the universal superset of all line
        items.
    effective_date:
        Calendar date for date-effectivity evaluation (ISO-8601).  None
        disables date filtering.
    options:
        Configuration option selections (e.g. {"engine": "v6"}).  None
        is treated as an empty dict.  Lines with un-met option requirements
        are excluded.
    serial_number:
        Unit serial number for serial-effectivity filtering.  None disables
        serial filtering.

    Returns
    -------
    ExpandedBom
        The 100% BOM with resolved line items and total quantity.

    Examples
    --------
    Depth-bar example from the task specification::

        lines = [
            BomLine("A", qty=2,
                    effective_from=date(2025,1,1), effective_to=date(2026,12,31)),
            BomLine("B", qty=1, option_requirements={"engine": "v6"}),
            BomLine("C", qty=4),
        ]
        # date=2026-03-15, engine=v8 -> A + C = qty 6
        r = expand_effectivity_bom(lines, date(2026,3,15), {"engine": "v8"})
        assert r.total_qty == 6

        # date=2026-03-15, engine=v6 -> A + B + C = qty 7
        r = expand_effectivity_bom(lines, date(2026,3,15), {"engine": "v6"})
        assert r.total_qty == 7
    """
    if options is None:
        options = {}

    selector = EffectivityFilter(
        effective_date=effective_date,
        serial_number=serial_number,
        options=options,
    )

    entries: list[ExpandedBomEntry] = []
    for line in bom_150:
        if _line_is_effective(line, selector):
            entries.append(ExpandedBomEntry(
                part_id=line.part_id,
                description=line.description,
                qty=line.qty,
                attributes=dict(line.attributes),
            ))

    total_qty = sum(e.qty for e in entries)
    return ExpandedBom(entries=entries, total_qty=total_qty, selector=selector)
