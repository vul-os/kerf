"""
kerf_plm.part_obsolescence_check
=================================

BOM component obsolescence risk assessment per IEC 62402:2019
(Obsolescence management — Application guide) and the US DoD DMSMS
(Diminishing Manufacturing Sources and Material Shortages) handbook.

Given a list of ``PartLifecycleEntry`` records — one per unique part
number — and an optional flat BOM relationship map, the function
``check_part_obsolescence`` produces an ``ObsolescenceReport`` that
quantifies the proportion of at-risk and obsolete components and
identifies which parent assemblies are exposed.

Lifecycle status vocabulary (IEC 62402 §4 + JEDEC JEP106 / PSST table)
-----------------------------------------------------------------------
active      Part is in full production; no supply-chain constraint.
preferred   Manufacturer's preferred alternative; typically a newer
            footprint-compatible revision.  Slightly preferred over
            *active* for new designs.
NRND        Not Recommended for New Designs — the part will not be
            proactively discontinued but no new design starts should
            use it.  Risk weight: 1.
LTB         Last-Time Buy — manufacturer has published a final order
            window.  Designers must qualify an alternative immediately.
            Risk weight: 3.
EOL         End-of-Life — production has stopped; stock-on-hand only.
            Risk weight: 5.
obsolete    No manufacturer stock; may require aftermarket or re-design.
            Risk weight: 10.

Risk score formula (kerf heuristic, IEC 62402 §5.3 risk-based approach)
------------------------------------------------------------------------
    risk_score = (NRND*1 + LTB*3 + EOL*5 + obsolete*10) / total_parts * 10

Score range: 0 (all active/preferred) → 100 (all obsolete, normalised).
A single obsolete part in a 10-part BOM scores 10.0.

Honest caveats
--------------
- Lifecycle data is **caller-supplied**; no live IHS Markit / Octopart /
  Silicon Expert API integration is included.  Callers must refresh
  lifecycle entries from their preferred data source (distributor feeds,
  ERP lifecycle fields, quarterly DMSMS scans).
- The risk-weight ladder (1 / 3 / 5 / 10) is a kerf heuristic that
  approximates IEC 62402 §5.3 risk prioritisation; real programmes should
  calibrate weights to their supply-chain lead time, sole-source exposure,
  and strategic-stock policy per the DMSMS handbook §2.3.
- ``affected_assemblies`` is derived from the flat BOM relationships only;
  multi-level (depth > 1) propagation is not performed in this module.
- ``last_buy_date`` parsing is informational only; no calendar-awareness
  (no "X days until LTB window closes") is computed here.
- Alternative part suggestions are pass-through from the caller-supplied
  ``alternative_pn`` field; no cross-reference search is performed.

References
----------
- IEC 62402:2019 — Obsolescence management — Application guide.
- US DoD DMSMS Handbook (2018 revision), §2.3 (Risk prioritisation) and
  §4.1 (BOM-level exposure analysis).
- JEDEC JEP106 — Standard for Manufacturer and Supplier Identification
  (lifecycle status codes used by electronics distributors).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

__all__ = [
    "PartLifecycleStatus",
    "PartLifecycleEntry",
    "ObsolescenceReport",
    "check_part_obsolescence",
    "HONEST_CAVEAT",
]

# ---------------------------------------------------------------------------
# Lifecycle status constants
# ---------------------------------------------------------------------------

class PartLifecycleStatus:
    """String constants for IEC 62402 part lifecycle status values.

    Using a plain class of string constants rather than an ``Enum`` keeps
    the values serialisable to JSON without a custom encoder and avoids
    friction when values arrive as raw strings from external feeds.
    """

    ACTIVE = "active"
    PREFERRED = "preferred"
    NRND = "NRND"          # Not Recommended for New Designs
    LTB = "LTB"            # Last-Time Buy
    EOL = "EOL"            # End-of-Life
    OBSOLETE = "obsolete"

    _ALL = {"active", "preferred", "NRND", "LTB", "EOL", "obsolete"}

    @classmethod
    def is_valid(cls, status: str) -> bool:
        """Return True if *status* is a recognised lifecycle value."""
        return status in cls._ALL


# Risk weights per IEC 62402 §5.3 risk-based approach (kerf heuristic).
_RISK_WEIGHTS: dict[str, int] = {
    "active": 0,
    "preferred": 0,
    "NRND": 1,
    "LTB": 3,
    "EOL": 5,
    "obsolete": 10,
}

HONEST_CAVEAT = (
    "Lifecycle data is caller-supplied; no live IHS Markit / Octopart / "
    "Silicon Expert API integration is included. "
    "Callers must refresh lifecycle entries from their preferred data source "
    "(distributor feeds, ERP lifecycle fields, quarterly DMSMS scans). "
    "Risk weights (NRND×1, LTB×3, EOL×5, obsolete×10) are kerf heuristics "
    "approximating IEC 62402 §5.3 risk prioritisation; calibrate to your "
    "supply-chain lead time and strategic-stock policy per the DMSMS handbook §2.3. "
    "Affected assemblies are derived from flat BOM relationships only; "
    "multi-level propagation beyond depth 1 is not performed."
)


# ---------------------------------------------------------------------------
# Public dataclasses
# ---------------------------------------------------------------------------

@dataclass
class PartLifecycleEntry:
    """Lifecycle record for a single component.

    Parameters
    ----------
    part_number:    Manufacturer part number (MPN) or internal PN.
    manufacturer:   Manufacturer name (e.g. 'Texas Instruments').
    status:         One of the ``PartLifecycleStatus`` string constants.
    last_buy_date:  Optional ISO 8601 date string for the LTB window close
                    date (e.g. '2025-12-31').  ``None`` if not applicable.
    alternative_pn: Optional recommended replacement MPN.  ``None`` if no
                    alternative has been identified.
    """

    part_number: str
    manufacturer: str
    status: str
    last_buy_date: Optional[str]
    alternative_pn: Optional[str]

    def __post_init__(self) -> None:
        if not self.part_number or not self.part_number.strip():
            raise ValueError("part_number must be a non-empty string")
        if not self.manufacturer or not self.manufacturer.strip():
            raise ValueError("manufacturer must be a non-empty string")
        if not PartLifecycleStatus.is_valid(self.status):
            raise ValueError(
                f"status '{self.status}' is not valid; "
                f"must be one of {sorted(PartLifecycleStatus._ALL)}"
            )


@dataclass
class ObsolescenceReport:
    """Result of a BOM-level part-obsolescence assessment.

    Attributes
    ----------
    total_parts:          Total number of distinct parts assessed.
    num_active:           Count of parts with status *active* or *preferred*.
    num_at_risk:          Count of parts with status NRND, LTB, or EOL
                          (at-risk but not yet fully obsolete).
    num_obsolete:         Count of parts with status *obsolete*.
    risk_score:           Normalised risk score 0–100 per the formula:
                          ``(NRND×1 + LTB×3 + EOL×5 + obsolete×10) /
                          total_parts × 10``
                          A score of 0 means all parts are active/preferred.
    critical_part_alerts: List of dicts, one per EOL or obsolete part,
                          each containing:
                          ``{part_number, manufacturer, status,
                             last_buy_date, alternative_pn}``.
    affected_assemblies:  List of parent assembly part numbers (from
                          *bom_relationships*) that use at least one
                          at-risk or obsolete part.
    honest_caveat:        Scope-limitation statement (module-level
                          ``HONEST_CAVEAT``).
    """

    total_parts: int
    num_active: int
    num_at_risk: int        # NRND + LTB + EOL
    num_obsolete: int
    risk_score: float       # 0–100
    critical_part_alerts: list[dict]
    affected_assemblies: list[str]
    honest_caveat: str


# ---------------------------------------------------------------------------
# Core check function
# ---------------------------------------------------------------------------

def check_part_obsolescence(
    parts: list[PartLifecycleEntry],
    bom_relationships: Optional[list[dict]] = None,
) -> ObsolescenceReport:
    """Assess BOM-level part obsolescence risk.

    For each ``PartLifecycleEntry`` in *parts*, the function:

    1. Classifies the part into *active*, *at-risk*, or *obsolete*.
    2. Accumulates the risk score using the weighted formula from IEC 62402.
    3. Builds ``critical_part_alerts`` for every EOL or obsolete part.
    4. Uses *bom_relationships* to identify parent assemblies that contain
       at least one at-risk or obsolete component.

    Parameters
    ----------
    parts:
        List of ``PartLifecycleEntry`` records for the parts in scope.
        Duplicate ``part_number`` values are allowed; each occurrence is
        counted as a separate BOM line entry.
    bom_relationships:
        Optional flat list of BOM relationship dicts.  Each dict must
        have ``"parent_pn"`` (str) and ``"child_pn"`` (str) keys.
        Additional keys (e.g. ``"qty"``) are ignored.  When ``None`` or
        empty, ``affected_assemblies`` will be an empty list.

    Returns
    -------
    ObsolescenceReport

    Raises
    ------
    TypeError
        If *parts* is not a list or *bom_relationships* is not a list /
        None.
    ValueError
        Propagated from ``PartLifecycleEntry.__post_init__`` for invalid
        lifecycle status values.
    """
    if not isinstance(parts, list):
        raise TypeError(f"parts must be a list, got {type(parts).__name__}")
    if bom_relationships is not None and not isinstance(bom_relationships, list):
        raise TypeError(
            f"bom_relationships must be a list or None, "
            f"got {type(bom_relationships).__name__}"
        )

    total = len(parts)

    # Empty BOM — return a zero-risk report immediately.
    if total == 0:
        return ObsolescenceReport(
            total_parts=0,
            num_active=0,
            num_at_risk=0,
            num_obsolete=0,
            risk_score=0.0,
            critical_part_alerts=[],
            affected_assemblies=[],
            honest_caveat=HONEST_CAVEAT,
        )

    # --- Count by bucket ---
    num_active = 0
    num_at_risk = 0
    num_obsolete = 0
    weighted_sum = 0

    # Set of at-risk or obsolete part_numbers for assembly-impact lookup.
    at_risk_or_obsolete_pns: set[str] = set()

    critical_part_alerts: list[dict] = []

    for entry in parts:
        s = entry.status
        w = _RISK_WEIGHTS.get(s, 0)
        weighted_sum += w

        if s in ("active", "preferred"):
            num_active += 1
        elif s == "obsolete":
            num_obsolete += 1
            at_risk_or_obsolete_pns.add(entry.part_number)
            critical_part_alerts.append({
                "part_number": entry.part_number,
                "manufacturer": entry.manufacturer,
                "status": entry.status,
                "last_buy_date": entry.last_buy_date,
                "alternative_pn": entry.alternative_pn,
            })
        else:
            # NRND, LTB, EOL
            num_at_risk += 1
            at_risk_or_obsolete_pns.add(entry.part_number)
            if s == "EOL":
                critical_part_alerts.append({
                    "part_number": entry.part_number,
                    "manufacturer": entry.manufacturer,
                    "status": entry.status,
                    "last_buy_date": entry.last_buy_date,
                    "alternative_pn": entry.alternative_pn,
                })

    # risk_score = weighted_sum / total * 10  (0–100 when max weight=10)
    risk_score = round(weighted_sum / total * 10, 4)

    # --- Affected assemblies ---
    affected_assemblies: list[str] = []
    if bom_relationships and at_risk_or_obsolete_pns:
        seen_parents: set[str] = set()
        for rel in bom_relationships:
            if not isinstance(rel, dict):
                continue
            child_pn = rel.get("child_pn")
            parent_pn = rel.get("parent_pn")
            if (
                child_pn in at_risk_or_obsolete_pns
                and parent_pn
                and parent_pn not in seen_parents
            ):
                seen_parents.add(parent_pn)
                affected_assemblies.append(parent_pn)

    return ObsolescenceReport(
        total_parts=total,
        num_active=num_active,
        num_at_risk=num_at_risk,
        num_obsolete=num_obsolete,
        risk_score=risk_score,
        critical_part_alerts=critical_part_alerts,
        affected_assemblies=affected_assemblies,
        honest_caveat=HONEST_CAVEAT,
    )
