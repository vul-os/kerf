"""
kerf_plm.component_whereused
============================

Component Where-Used report: given a flat list of BOM relationships, produce
every parent assembly that (directly or transitively) references a target
component, with aggregated quantity and BFS level.

Methodology
-----------
ISO 10303-44 (STEP AP44 product structure) and APICS dictionary
"where-used" definition.

  "Where-used analysis: determination of every higher-level item that
  incorporates a given component in its bill of material."
  — APICS Dictionary, 16th ed.

The BOM is modelled as a directed acyclic graph (DAG) where each
BomRelationship represents an edge child→parent (i.e. "parent_pn *contains*
child_pn at qty").  Where-Used performs a BFS upward from the target
component to root assemblies.

Level semantics
^^^^^^^^^^^^^^^
``level == 1``  → the assembly is a direct parent of the target component.
``level == 2``  → the assembly is a grandparent (parent of a parent), etc.

Quantity aggregation
^^^^^^^^^^^^^^^^^^^^
``qty`` in each WhereUsedEntry is the *direct* quantity consumed at that
parent level (not path-multiplied).  For multi-level totals the caller
should multiply down the hierarchy.

Cycle detection
^^^^^^^^^^^^^^^
Assumes an acyclic BOM DAG.  If a cycle is detected (a candidate parent is
already on the active BFS path) a ``ValueError`` is raised immediately,
identifying the offending cycle path.

Honest caveats
--------------
- In-memory traversal only: no DB pagination, no live PDM feed.
- qty per entry is the direct quantity at that single parent level; it does
  NOT represent path-multiplied extended quantities.
- Assumes an acyclic BOM (ISO 10303-44 invariant); cycles raise ValueError.
- No effectivity, variant, or revision filtering.
- No multi-unit-of-measure conversion.

References
----------
- ISO 10303-44:2021 (STEP Application Protocol 44 — product structure)
- APICS Dictionary, 16th ed.: "where-used"
- PROSTEP-iViP Smart Systems Engineering SIG §5.2

Public API
----------
  find_component_whereused(component_pn, relationships, names) -> WhereUsedReport
"""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Optional


# ---------------------------------------------------------------------------
# Honest caveat string (used in WhereUsedReport and LLM tool output)
# ---------------------------------------------------------------------------

HONEST_CAVEAT = (
    "In-memory BOM traversal only. "
    "qty per entry is the direct quantity at that level (not path-multiplied). "
    "No DB pagination, live PDM sync, effectivity filtering, or MoU conversion. "
    "Cycles raise ValueError. "
    "ISO 10303-44 product structure; APICS 'where-used' definition."
)


# ---------------------------------------------------------------------------
# Domain dataclasses
# ---------------------------------------------------------------------------

@dataclass
class BomRelationship:
    """A single parent→child relationship in a flat BOM.

    Represents the ISO 10303-44 ``next_assembly_usage_occurrence`` concept:
    assembly ``parent_pn`` directly uses ``child_pn`` with a given ``qty``.

    Attributes
    ----------
    parent_pn:
        Part number of the parent assembly.
    child_pn:
        Part number of the child component.
    qty:
        Quantity of ``child_pn`` used in one unit of ``parent_pn``.
        Must be positive.
    """
    parent_pn: str
    child_pn: str
    qty: float


@dataclass
class WhereUsedEntry:
    """A single parent assembly that consumes the queried component.

    Attributes
    ----------
    parent_pn:
        Part number of the parent assembly.
    parent_name:
        Optional human-readable name of the parent (from *names* dict).
    qty:
        Direct quantity consumed: sum of all BomRelationship.qty values
        where parent_pn == this assembly and child_pn == the queried
        component (or an intermediate sub-assembly at this BFS hop).
    level:
        BFS depth from the queried component.
        1 = direct parent, 2 = grandparent, …
    """
    parent_pn: str
    parent_name: Optional[str]
    qty: float
    level: int


@dataclass
class WhereUsedReport:
    """Result of ``find_component_whereused()``.

    Attributes
    ----------
    component_pn:
        The queried component part number.
    num_unique_parents:
        Count of distinct parent assemblies across all levels.
    num_total_usages:
        Sum of all entry qty values (all levels combined).
    max_depth:
        Maximum BFS level reached (0 if no parents found).
    entries:
        List of WhereUsedEntry, sorted by level ascending then parent_pn.
    honest_caveat:
        Methodology and limitation note per ISO 10303-44 / APICS.
    """
    component_pn: str
    num_unique_parents: int
    num_total_usages: int
    max_depth: int
    entries: list[WhereUsedEntry] = field(default_factory=list)
    honest_caveat: str = HONEST_CAVEAT


# ---------------------------------------------------------------------------
# Core function
# ---------------------------------------------------------------------------

def find_component_whereused(
    component_pn: str,
    relationships: list[BomRelationship],
    names: Optional[dict[str, str]] = None,
) -> WhereUsedReport:
    """Find every parent assembly that uses *component_pn*, with qty and level.

    Performs a BFS upward from *component_pn* through the assembly hierarchy
    derived from *relationships*.  Each unique parent assembly is recorded
    once (at its first-visited, shallowest BFS level).

    Parameters
    ----------
    component_pn:
        The component (leaf or sub-assembly) to query.
    relationships:
        Flat list of BomRelationship objects describing the entire BOM.
        May contain relationships unrelated to *component_pn*.
    names:
        Optional mapping from part number → human-readable name.
        Used to populate ``WhereUsedEntry.parent_name``.

    Returns
    -------
    WhereUsedReport

    Raises
    ------
    ValueError
        If a cycle is detected in the BOM graph.  The error message
        includes the full cycle path.
    """
    if names is None:
        names = {}

    # Build an inverted map: child_pn → [(parent_pn, qty), ...]
    # Multiple rows with the same (parent, child) are summed.
    child_to_parents: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for rel in relationships:
        child_to_parents[rel.child_pn][rel.parent_pn] += rel.qty

    # BFS upward from component_pn.
    # Queue entries: (current_pn, level, path_set_so_far)
    # We use path as a frozenset for O(1) cycle check, plus a tuple for error msg.
    queue: deque[tuple[str, int, tuple[str, ...]]] = deque()
    queue.append((component_pn, 0, (component_pn,)))

    # seen: parent_pn → WhereUsedEntry (first-visit wins for level)
    seen: dict[str, WhereUsedEntry] = {}

    while queue:
        current_pn, level, path = queue.popleft()

        parent_map = child_to_parents.get(current_pn, {})
        for parent_pn, qty in parent_map.items():
            new_level = level + 1

            # Cycle check: parent already on the active path
            if parent_pn in path:
                cycle_display = " → ".join(path) + " → " + parent_pn
                raise ValueError(
                    f"Cycle detected in BOM graph: {cycle_display}"
                )

            if parent_pn not in seen:
                entry = WhereUsedEntry(
                    parent_pn=parent_pn,
                    parent_name=names.get(parent_pn),
                    qty=qty,
                    level=new_level,
                )
                seen[parent_pn] = entry
                queue.append((parent_pn, new_level, path + (parent_pn,)))
            # First-visit BFS invariant: shallower level always wins.
            # Do not re-queue nodes already seen at a shallower level.

    entries = sorted(seen.values(), key=lambda e: (e.level, e.parent_pn))

    num_unique = len(entries)
    num_total = int(sum(e.qty for e in entries))
    max_depth = max((e.level for e in entries), default=0)

    return WhereUsedReport(
        component_pn=component_pn,
        num_unique_parents=num_unique,
        num_total_usages=num_total,
        max_depth=max_depth,
        entries=entries,
        honest_caveat=HONEST_CAVEAT,
    )
