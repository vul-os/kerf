"""
kerf_plm.where_used
===================

Where-Used Analysis — inverse of BOM expansion.

For a given target part, traverses the assembly hierarchy in reverse to list
every assembly (and sub-assembly) that consumes it, with multiplicity and
depth.

Methodology
-----------
Implements PROSTEP-iViP SIG §5.2 "Where-Used Analysis" (Product Structure
Management module, Smart Systems Engineering).  The BOM is modelled as a
directed acyclic graph (DAG) where an edge A→B means "assembly A *contains*
child B".  Where-Used is the reverse BFS/DFS from the target part upward
through parent assemblies.

Multiplicity
^^^^^^^^^^^^
``occurrence_count`` is the number of times the target part (or a
sub-assembly containing it) appears as a *direct* child reference in the
given assembly.  This corresponds to PROSTEP position multiplicity: if a
bolt appears twice in an assembly, ``occurrence_count`` == 2.

Depth
^^^^^
``depth`` == 1  → the assembly is an *immediate* parent of the target part.
``depth`` == 2  → the assembly is a grandparent (parent-of-parent), etc.

Cycle detection
^^^^^^^^^^^^^^^
Assumes an acyclic assembly DAG (the invariant required by PROSTEP §5.2).
If a cycle is detected the traversal stops at that branch and the result
includes a ``cycle_detected`` flag.  Recursion is capped at depth 20 as a
defensive measure.

Public API
----------
  where_used(target_part_id, plm_data)   -> WhereUsedReport
  build_where_used_graph(plm_data)       -> WhereUsedGraph
"""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, field

MAX_DEPTH: int = 20  # PROSTEP-iViP §5.2: cap traversal to prevent cycle runaway


# ---------------------------------------------------------------------------
# Domain types
# ---------------------------------------------------------------------------

@dataclass
class WhereUsedEntry:
    """A single assembly that consumes (directly or transitively) the target part."""
    assembly_id: str
    label: str
    occurrence_count: int  # how many times target (or a parent of it) appears in this asm
    depth: int             # 1 = immediate parent, 2 = grandparent, …


@dataclass
class WhereUsedReport:
    """Result of where_used()."""
    target_part_id: str
    entries: list[WhereUsedEntry] = field(default_factory=list)
    cycle_detected: bool = False
    cycle_path: list[str] = field(default_factory=list)

    def total_occurrences(self) -> int:
        """Sum of all occurrence_count across all entries."""
        return sum(e.occurrence_count for e in self.entries)

    def at_depth(self, depth: int) -> list[WhereUsedEntry]:
        return [e for e in self.entries if e.depth == depth]


# ---------------------------------------------------------------------------
# Graph
# ---------------------------------------------------------------------------

class WhereUsedGraph:
    """
    Inverted BOM graph for where-used traversal.

    For each child part/assembly, stores the set of parent assemblies that
    directly reference it, along with the occurrence count (multiplicity) of
    that reference.
    """

    def __init__(self) -> None:
        # child_id -> list of (parent_id, occurrence_count)
        self._parents: dict[str, list[tuple[str, int]]] = defaultdict(list)
        # assembly id -> label
        self._labels: dict[str, str] = {}
        # all known node ids (parts + assemblies)
        self._nodes: set[str] = set()

    def add_assembly(self, assembly_id: str, children: list[str], label: str = "") -> None:
        """Register an assembly with its children list.

        Multiple occurrences of the same child_id in *children* are counted.
        """
        self._nodes.add(assembly_id)
        self._labels[assembly_id] = label or assembly_id

        # Count occurrences per child
        counts: dict[str, int] = defaultdict(int)
        for child_id in children:
            counts[child_id] += 1
            self._nodes.add(child_id)

        for child_id, count in counts.items():
            self._parents[child_id].append((assembly_id, count))

    def set_label(self, node_id: str, label: str) -> None:
        self._labels[node_id] = label

    def parents_of(self, node_id: str) -> list[tuple[str, int]]:
        """Return [(parent_id, occurrence_count), ...] for direct parents."""
        return list(self._parents.get(node_id, []))

    def label(self, node_id: str) -> str:
        return self._labels.get(node_id, node_id)

    def has_node(self, node_id: str) -> bool:
        return node_id in self._nodes


# ---------------------------------------------------------------------------
# Build graph from PLM data dict
# ---------------------------------------------------------------------------

def build_where_used_graph(plm_data: dict) -> WhereUsedGraph:
    """
    Build a WhereUsedGraph from a PLM data dictionary.

    The schema is identical to the one consumed by ``build_impact_graph``
    (kerf_plm.change_impact).  Only the ``parts`` and ``assemblies`` sections
    are used for where-used traversal.

    Example input::

        {
          "parts": [
            {"id": "P-001", "label": "Hex Bolt M8"},
            ...
          ],
          "assemblies": [
            {
              "id": "A-001",
              "label": "Bracket Sub-Assembly",
              "children": ["P-001", "P-001", "P-002"]  # P-001 appears twice → count=2
            },
            ...
          ],
          ...
        }
    """
    g = WhereUsedGraph()

    # Register part labels
    for part in plm_data.get("parts", []):
        g._nodes.add(part["id"])
        g._labels[part["id"]] = part.get("label", part["id"])

    # Register assemblies (also used as nodes / potential children)
    for asm in plm_data.get("assemblies", []):
        asm_id = asm["id"]
        label = asm.get("label", asm_id)
        children = asm.get("children", [])
        g.add_assembly(asm_id, children, label=label)

    return g


# ---------------------------------------------------------------------------
# Core traversal
# ---------------------------------------------------------------------------

def where_used(
    target_part_id: str,
    plm_data: dict,
) -> WhereUsedReport:
    """
    List all assemblies / sub-assemblies that consume *target_part_id*,
    with multiplicity and depth.

    Implements PROSTEP-iViP SIG §5.2 "Where-Used Analysis".

    Assumes an acyclic assembly DAG.  If a cycle is detected the traversal
    is cut at that branch and ``WhereUsedReport.cycle_detected`` is set True.
    Traversal depth is capped at ``MAX_DEPTH`` (==20) as a defensive measure.

    Parameters
    ----------
    target_part_id:
        The part or sub-assembly to query.
    plm_data:
        PLM product-structure dict (same schema as ``plm_change_impact``).

    Returns
    -------
    WhereUsedReport
        ``entries`` is sorted by depth ascending, then assembly_id.
        ``cycle_detected`` is True if a cycle was found.
    """
    graph = build_where_used_graph(plm_data)
    return _traverse(target_part_id, graph)


def _traverse(target_part_id: str, graph: WhereUsedGraph) -> WhereUsedReport:
    """BFS up the assembly hierarchy from *target_part_id*."""
    if not graph.has_node(target_part_id):
        return WhereUsedReport(target_part_id=target_part_id)

    report = WhereUsedReport(target_part_id=target_part_id)
    # seen maps assembly_id -> WhereUsedEntry (first-visit depth wins)
    seen: dict[str, WhereUsedEntry] = {}
    cycle_detected = False
    cycle_path: list[str] = []

    # BFS queue: (node_id, depth, path_from_root_to_here)
    queue: deque[tuple[str, int, list[str]]] = deque()
    queue.append((target_part_id, 0, [target_part_id]))

    while queue:
        current_id, depth, path = queue.popleft()

        if depth >= MAX_DEPTH:
            # Cap traversal — do not recurse further
            continue

        for parent_id, occ_count in graph.parents_of(current_id):
            new_depth = depth + 1

            # Cycle check: parent already on the active path
            if parent_id in path:
                cycle_detected = True
                cycle_path = path + [parent_id]
                continue  # Cut this branch

            if parent_id not in seen:
                entry = WhereUsedEntry(
                    assembly_id=parent_id,
                    label=graph.label(parent_id),
                    occurrence_count=occ_count,
                    depth=new_depth,
                )
                seen[parent_id] = entry
                queue.append((parent_id, new_depth, path + [parent_id]))
            # NOTE: if parent_id already seen at shallower depth we keep the
            # shallower depth (first-visit BFS invariant) but do NOT re-queue.

    report.entries = sorted(seen.values(), key=lambda e: (e.depth, e.assembly_id))
    report.cycle_detected = cycle_detected
    report.cycle_path = cycle_path
    return report
