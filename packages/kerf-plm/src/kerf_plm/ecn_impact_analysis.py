"""
kerf_plm.ecn_impact_analysis
============================

ECN (Engineering Change Notice) Cascading Impact Analysis.

Methodology
-----------
ISO 10007:2003 §6 (Change control process) and APICS Dictionary 16th ed.
"engineering change notice (ECN)":

  "A document used to describe and authorize a change to a previously
  approved part, process, or product. The ECN initiates the change-control
  process defined in ISO 10007 §6."

This module computes the *cascading* impact of an ECN affecting one or more
part numbers.  Given:

  1. The ECN description (``EcnInput``)
  2. A flat list of BOM parent→child relationships (``BomRelationship`` list)
  3. Optional drawings database: {part_number: [drawing_id, ...]}
  4. Optional open work orders database: {part_number: [work_order_id, ...]}

It performs:

  1. BFS upward from every ECN-affected component through the BOM hierarchy
     to identify ALL transitively affected parent assemblies (deduped).
  2. Drawing impact: counts distinct drawing IDs linked to affected parents.
  3. Work order impact: counts open work orders linked to affected parents.
  4. Cost estimate (heuristic):
       cost = (parent_count × 50)
            + (drawing_count × cost_per_drawing_revision)
            + (work_order_count × 200)
  5. Implementation class assignment:
       Class_I_immediate   — emergency urgency OR large parent count (>= 20)
       Class_II_rev        — normal urgency with moderate impact (parents 1-19)
       Class_III_drawing_only — deferred urgency OR zero parents found

Implementation classification reference
----------------------------------------
Per ISO 10007 §6.3.2 and SAE AS9102B common practice:
  Class I (Immediate)   — safety, regulatory, or emergency changes requiring
                          mandatory retrofit or immediate production hold.
  Class II (Rev)        — planned drawing/document revision incorporated on a
                          "use existing, next production order" basis.
  Class III (Drawing Only) — administrative or deferred changes; drawing updated
                             but no active production impact.

Honest caveats
--------------
- Cost formula is a heuristic estimate.  Real-world ECN costs vary widely
  by industry, change classification, and company process maturity.
  Aerospace/defence ECNs can exceed $10 000 per drawing revision; consumer
  electronics may be < $50.  Use this estimate for initial prioritisation only.
- In-memory BOM traversal: no DB pagination, live PDM sync, effectivity
  filtering, or revision-specific routing.
- Work order and drawing lookups are exact part-number matches; no
  assembly-level aggregation unless explicitly included in the input dicts.
- Class assignment heuristics are simplified; real ECN classification
  requires engineering judgment and change-board review per ISO 10007 §6.5.

References
----------
- ISO 10007:2003 §6 — Quality management systems — Guidelines for
  configuration management — Change control
- APICS Dictionary 16th ed.: "engineering change notice (ECN)"
- SAE AS9100D §8.1.3 — Configuration management for aerospace
- SAE AS9102B — First Article Inspection
- MIL-HDBK-61B — Configuration Identification and Change Management

Public API
----------
  analyze_ecn_impact(
      ecn_input,
      bom_relationships,
      drawings_db=None,
      work_orders_db=None,
      cost_per_drawing_revision=150.0,
  ) -> EcnImpactReport
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Optional

from kerf_plm.component_whereused import BomRelationship, find_component_whereused


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Heuristic cost per parent assembly revision (USD).
PARENT_REVISION_COST_USD: float = 50.0

#: Heuristic cost per open work order re-routing (USD).
WORK_ORDER_REROUTE_COST_USD: float = 200.0

#: Threshold: >= this many affected parents → Class I immediate.
CLASS_I_PARENT_THRESHOLD: int = 20

#: Honest caveat string surfaced on every report.
HONEST_CAVEAT = (
    "ECN cost estimate is a heuristic (parents×$50 + drawings×$cost_per_rev + work_orders×$200). "
    "Real-world ECN costs vary widely by industry and change classification — "
    "aerospace/defence drawing revisions can exceed $10 000; consumer electronics may be <$50. "
    "Use for initial prioritisation only. "
    "In-memory BOM traversal: no DB pagination, live PDM sync, or effectivity filtering. "
    "Class assignment is heuristic; real ECN classification requires engineering judgment "
    "and change-board review per ISO 10007 §6.5 (APICS 'engineering change notice')."
)


# ---------------------------------------------------------------------------
# Input dataclass
# ---------------------------------------------------------------------------

@dataclass
class EcnInput:
    """Describes an Engineering Change Notice for impact analysis.

    Attributes
    ----------
    ecn_id:
        Unique ECN identifier, e.g. ``'ECN-2026-0042'``.
    affected_components:
        Part numbers directly listed on the ECN.  Each is treated as a
        starting point for the BFS upward traversal.
    change_description:
        Free-text description of the change.
    urgency:
        ``'emergency'`` | ``'normal'`` | ``'deferred'``.
        Controls implementation class assignment:
          emergency → Class_I_immediate regardless of impact size.
          deferred  → Class_III_drawing_only regardless of impact size
                      (when zero parents found; otherwise Class_II_rev).
    """
    ecn_id: str
    affected_components: list[str]
    change_description: str
    urgency: str  # "emergency" | "normal" | "deferred"


# ---------------------------------------------------------------------------
# Output dataclass
# ---------------------------------------------------------------------------

@dataclass
class EcnImpactReport:
    """Result of ``analyze_ecn_impact()``.

    Attributes
    ----------
    ecn_id:
        ECN identifier from the input.
    total_affected_parents:
        Count of distinct parent assemblies reachable from any ECN-affected
        component via BFS upward traversal.  Deduplicated across all components.
    total_affected_drawings:
        Count of distinct drawing IDs linked to any affected parent assembly
        (from *drawings_db*).  0 when *drawings_db* is not supplied.
    total_open_work_orders:
        Count of distinct open work order IDs linked to any affected parent
        (from *work_orders_db*).  0 when *work_orders_db* is not supplied.
    estimated_cost_usd:
        Heuristic cost estimate in USD:
          ``(total_affected_parents × 50)
          + (total_affected_drawings × cost_per_drawing_revision)
          + (total_open_work_orders × 200)``
    implementation_class:
        Heuristic ISO 10007 implementation class:
          ``'Class_I_immediate'``    — emergency urgency OR >= 20 parents.
          ``'Class_II_rev'``         — normal urgency, 1–19 parents.
          ``'Class_III_drawing_only'`` — deferred urgency OR zero parents.
    affected_parent_tree:
        Sorted list of all unique parent assembly part numbers discovered
        during the BFS.
    honest_caveat:
        Methodology and limitation note (ISO 10007 §6 + APICS ECN).
    """
    ecn_id: str
    total_affected_parents: int
    total_affected_drawings: int
    total_open_work_orders: int
    estimated_cost_usd: float
    implementation_class: str
    affected_parent_tree: list[str] = field(default_factory=list)
    honest_caveat: str = HONEST_CAVEAT


# ---------------------------------------------------------------------------
# Core function
# ---------------------------------------------------------------------------

def analyze_ecn_impact(
    ecn_input: EcnInput,
    bom_relationships: list[BomRelationship],
    drawings_db: Optional[dict[str, list[str]]] = None,
    work_orders_db: Optional[dict[str, list[str]]] = None,
    cost_per_drawing_revision: float = 150.0,
) -> EcnImpactReport:
    """Compute the cascading BOM impact of an Engineering Change Notice.

    For each component in ``ecn_input.affected_components``, performs a BFS
    upward traversal through the BOM defined by ``bom_relationships`` to
    find all transitively affected parent assemblies.  Results are then
    joined against *drawings_db* and *work_orders_db* to count affected
    drawings and open work orders, and a heuristic cost estimate is computed.

    Parameters
    ----------
    ecn_input:
        ``EcnInput`` describing the ECN: id, affected components, description,
        and urgency.
    bom_relationships:
        Flat list of ``BomRelationship(parent_pn, child_pn, qty)`` records
        describing the BOM structure.  May include entries unrelated to the
        ECN-affected components.
    drawings_db:
        Optional mapping from part_number → list of drawing IDs linked to
        that part.  Used to count affected drawings.  When ``None``, drawing
        count is reported as 0.
    work_orders_db:
        Optional mapping from part_number → list of open work order IDs.
        When ``None``, work order count is reported as 0.
    cost_per_drawing_revision:
        Heuristic cost (USD) to revise one drawing.  Default: ``150.0``.
        Adjust for your industry (aerospace typically higher; consumer lower).

    Returns
    -------
    EcnImpactReport

    Raises
    ------
    ValueError
        If ``ecn_input.urgency`` is not one of ``'emergency'``, ``'normal'``,
        ``'deferred'``.
        If ``bom_relationships`` contains a cycle (propagated from
        ``find_component_whereused``).
    """
    valid_urgencies = {"emergency", "normal", "deferred"}
    if ecn_input.urgency not in valid_urgencies:
        raise ValueError(
            f"ecn_input.urgency must be one of {sorted(valid_urgencies)!r}, "
            f"got {ecn_input.urgency!r}"
        )

    if drawings_db is None:
        drawings_db = {}
    if work_orders_db is None:
        work_orders_db = {}

    # BFS upward for each affected component; deduplicate across all components.
    all_affected_parents: set[str] = set()

    for component_pn in ecn_input.affected_components:
        report = find_component_whereused(
            component_pn=component_pn,
            relationships=bom_relationships,
        )
        for entry in report.entries:
            all_affected_parents.add(entry.parent_pn)

    # Count distinct drawings linked to any affected parent.
    affected_drawings: set[str] = set()
    for parent_pn in all_affected_parents:
        for drawing_id in drawings_db.get(parent_pn, []):
            affected_drawings.add(drawing_id)

    # Count distinct open work orders linked to any affected parent.
    affected_work_orders: set[str] = set()
    for parent_pn in all_affected_parents:
        for wo_id in work_orders_db.get(parent_pn, []):
            affected_work_orders.add(wo_id)

    total_parents = len(all_affected_parents)
    total_drawings = len(affected_drawings)
    total_work_orders = len(affected_work_orders)

    # Heuristic cost estimate.
    estimated_cost = (
        total_parents * PARENT_REVISION_COST_USD
        + total_drawings * cost_per_drawing_revision
        + total_work_orders * WORK_ORDER_REROUTE_COST_USD
    )

    # Implementation class assignment (ISO 10007 §6.3.2 + heuristic).
    if ecn_input.urgency == "emergency":
        impl_class = "Class_I_immediate"
    elif ecn_input.urgency == "deferred" and total_parents == 0:
        impl_class = "Class_III_drawing_only"
    elif total_parents >= CLASS_I_PARENT_THRESHOLD:
        impl_class = "Class_I_immediate"
    elif total_parents == 0:
        impl_class = "Class_III_drawing_only"
    else:
        impl_class = "Class_II_rev"

    return EcnImpactReport(
        ecn_id=ecn_input.ecn_id,
        total_affected_parents=total_parents,
        total_affected_drawings=total_drawings,
        total_open_work_orders=total_work_orders,
        estimated_cost_usd=round(estimated_cost, 2),
        implementation_class=impl_class,
        affected_parent_tree=sorted(all_affected_parents),
        honest_caveat=HONEST_CAVEAT,
    )
