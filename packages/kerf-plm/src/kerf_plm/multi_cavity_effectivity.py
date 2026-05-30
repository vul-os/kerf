"""
PLM Multi-Cavity Tool Effectivity — PROSTEP-iViP SIG §6 "Multi-cavity tool effectivity".

For a multi-cavity injection mold (or similar tooling family) each cavity slot
can hold a different insert revision with its own date-effectivity window and
compatibility set.  This module resolves, for a given tool and query date, which
revision each cavity is producing.

References
----------
* PROSTEP-iViP SIG, "Multi-cavity tool effectivity" §6 — effectivity records
  for per-cavity insert configurations (DataM Tooling, ToolMonitor schema).
* ISO 10303-44:2000 §5.3 — effectivity model (date bounds, open/closed).

Data model
----------
A ``ToolCavity`` represents one slot in a multi-cavity tool:

  cavity_id          integer 1-N, unique within the tool.
  inserts            ordered list of ``CavityInsert`` records; the most
                     recently effective one wins for any given query date.

A ``CavityInsert`` represents one insert revision history record:

  revision           string label, e.g. "R5", "R6".
  effective_from     earliest date this insert is active (inclusive; None = open).
  effective_to       latest date this insert is active (inclusive; None = open).
  compatible_revisions
                     set of part-revision labels that this insert supports.
                     Empty set means "unrestricted" (supports all revisions).

The ``MultiCavityTool`` bundles tool metadata + its cavity list.

Algorithm (PROSTEP-iViP SIG §6.2 "per-cavity effectivity resolution")
-----------------------------------------------------------------------
For each cavity slot, iterate its insert records in declaration order and
select every insert whose [effective_from, effective_to] window contains the
query date.  If multiple inserts are active on that date (overlapping windows),
the LAST one in declaration order wins (latest-specification-wins semantics,
matching mold-tool DB convention).

If ``options`` supplies a ``require_revision`` key, only cavities whose active
insert revision is in the specified set are counted in effective_count.

Honest caveats (v1)
--------------------
1. Insert *wear* and *change-out queuing*: this module does not model physical
   wear curves, planned insert swap orders, or maintenance schedules.
   It only evaluates the declared effectivity windows as-is.
2. Overlapping-window resolution uses declaration-order last-wins; production
   systems (DataM, ToolMonitor) may use a "change-record timestamp" instead.
3. ``compatible_revisions`` is an exact-match set; partial revision compatibility
   (e.g. R5 ≥ R4) is not evaluated.
"""

from __future__ import annotations

HONEST_FLAG = (
    "PLM-MULTI-CAVITY-EFFECTIVITY v1: Does NOT model insert wear, change-out "
    "queuing, or maintenance schedules. Overlapping effectivity windows resolved "
    "by last-declaration-wins. compatible_revisions is an exact-match set; no "
    "partial revision ordering."
)

from dataclasses import dataclass, field
from datetime import date
from typing import Any


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class CavityInsert:
    """One insert revision record for a cavity slot.

    Parameters
    ----------
    revision:
        Revision label, e.g. "R5", "R6".
    effective_from:
        Earliest date this insert is active (inclusive).  None = no lower bound.
    effective_to:
        Latest date this insert is active (inclusive).  None = no upper bound.
    compatible_revisions:
        Set of part-revision labels this insert can produce.  Empty set means
        no restriction — all revisions are compatible.
    """

    revision: str
    effective_from: date | None = None
    effective_to: date | None = None
    compatible_revisions: set[str] = field(default_factory=set)


@dataclass
class ToolCavity:
    """One cavity slot in a multi-cavity tool.

    Parameters
    ----------
    cavity_id:
        Integer identifier, unique within the tool (1-based by convention).
    inserts:
        Ordered list of ``CavityInsert`` records covering the insert history
        for this slot.  Declaration order matters for overlap resolution.
    """

    cavity_id: int
    inserts: list[CavityInsert] = field(default_factory=list)


@dataclass
class MultiCavityTool:
    """A multi-cavity injection mold or similar tooling family.

    Parameters
    ----------
    tool_id:
        Unique identifier for the tool, e.g. "MOLD-001".
    cavities:
        Ordered list of ``ToolCavity`` objects.
    """

    tool_id: str
    cavities: list[ToolCavity] = field(default_factory=list)


@dataclass
class CavityResolution:
    """The resolved state of a single cavity at a query date.

    Attributes
    ----------
    cavity_id:
        Cavity slot identifier.
    revision:
        Resolved insert revision for the query date, or None if no insert is
        effective on that date.
    compatible_revisions:
        The compatible_revisions set from the winning insert (empty = unrestricted).
    effective:
        True iff the cavity has an active insert on the query date.
    """

    cavity_id: int
    revision: str | None
    compatible_revisions: set[str]
    effective: bool


@dataclass
class MultiCavityResult:
    """Result of a multi-cavity effectivity query.

    Attributes
    ----------
    tool_id:
        The queried tool identifier.
    query_date:
        The date used for the query.
    per_cavity_revisions:
        List of ``CavityResolution`` — one entry per cavity, in cavity_id order.
    effective_count:
        Number of cavities that have an active insert on the query date.
        If ``require_revision`` was supplied in options, only cavities whose
        active revision is in that set are counted.
    honest_flag:
        Module-level caveat string.
    """

    tool_id: str
    query_date: date
    per_cavity_revisions: list[CavityResolution]
    effective_count: int
    honest_flag: str = HONEST_FLAG

    def as_tuples(self) -> list[tuple[int, str | None]]:
        """Return [(cavity_id, revision), ...] for all cavities."""
        return [(r.cavity_id, r.revision) for r in self.per_cavity_revisions]


# ---------------------------------------------------------------------------
# Effectivity resolution helpers
# ---------------------------------------------------------------------------

def _insert_is_effective(insert: CavityInsert, query_date: date) -> bool:
    """Return True iff *insert* is effective on *query_date*.

    Implements ISO 10303-44 §5.3 date-effectivity: open bounds (None) match
    any date on that side.
    """
    if insert.effective_from is not None and query_date < insert.effective_from:
        return False
    if insert.effective_to is not None and query_date > insert.effective_to:
        return False
    return True


def _resolve_cavity(cavity: ToolCavity, query_date: date) -> CavityResolution:
    """Resolve a single cavity to its active insert revision on *query_date*.

    Iterates insert records in declaration order; the LAST effective record wins
    (PROSTEP-iViP SIG §6.2 latest-specification-wins semantics).
    """
    winning: CavityInsert | None = None
    for insert in cavity.inserts:
        if _insert_is_effective(insert, query_date):
            winning = insert

    if winning is None:
        return CavityResolution(
            cavity_id=cavity.cavity_id,
            revision=None,
            compatible_revisions=set(),
            effective=False,
        )
    return CavityResolution(
        cavity_id=cavity.cavity_id,
        revision=winning.revision,
        compatible_revisions=set(winning.compatible_revisions),
        effective=True,
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def query_multi_cavity_effectivity(
    tool: MultiCavityTool,
    query_date: date,
    options: dict[str, Any] | None = None,
) -> MultiCavityResult:
    """Return the per-cavity revision state for *tool* on *query_date*.

    Implements PROSTEP-iViP SIG §6 "Multi-cavity tool effectivity" per-cavity
    resolution algorithm.

    Parameters
    ----------
    tool:
        The ``MultiCavityTool`` to query.
    query_date:
        The calendar date for which to resolve cavity states.
    options:
        Optional filtering dict.  Recognised keys:

          ``require_revision`` (list[str] or str):
              When provided, only cavities whose resolved revision is in this
              set are counted in ``effective_count``.  Other cavities are still
              included in ``per_cavity_revisions`` for full visibility.

    Returns
    -------
    MultiCavityResult
        Per-cavity revisions and effective cavity count.

    Examples
    --------
    Depth-bar example — 4-cavity tool all at R5::

        from datetime import date
        tool = MultiCavityTool(
            tool_id="MOLD-001",
            cavities=[
                ToolCavity(i, [CavityInsert("R5")]) for i in range(1, 5)
            ],
        )
        result = query_multi_cavity_effectivity(tool, date(2026, 1, 1))
        assert result.as_tuples() == [(1,"R5"),(2,"R5"),(3,"R5"),(4,"R5")]

    Cavity 3 swapped to R6 from 2026-04-01::

        tool.cavities[2].inserts.append(
            CavityInsert("R6", effective_from=date(2026, 4, 1))
        )
        # query 2026-05-01 → cavity 3 now R6
        r = query_multi_cavity_effectivity(tool, date(2026, 5, 1))
        assert r.as_tuples() == [(1,"R5"),(2,"R5"),(3,"R6"),(4,"R5")]

        # query 2026-03-15 → all still R5
        r = query_multi_cavity_effectivity(tool, date(2026, 3, 15))
        assert r.as_tuples() == [(1,"R5"),(2,"R5"),(3,"R5"),(4,"R5")]
    """
    if options is None:
        options = {}

    # Resolve each cavity
    per_cavity: list[CavityResolution] = []
    for cavity in sorted(tool.cavities, key=lambda c: c.cavity_id):
        per_cavity.append(_resolve_cavity(cavity, query_date))

    # Compute effective_count, optionally filtered by require_revision
    require_rev = options.get("require_revision")
    if require_rev is not None:
        if isinstance(require_rev, str):
            require_rev = [require_rev]
        require_set = set(require_rev)
        effective_count = sum(
            1 for r in per_cavity
            if r.effective and r.revision is not None and r.revision in require_set
        )
    else:
        effective_count = sum(1 for r in per_cavity if r.effective)

    return MultiCavityResult(
        tool_id=tool.tool_id,
        query_date=query_date,
        per_cavity_revisions=per_cavity,
        effective_count=effective_count,
    )
