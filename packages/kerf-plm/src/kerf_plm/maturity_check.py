"""
kerf_plm.maturity_check
=======================

BOM completeness maturity assessment using a NASA TRL-style (Technology
Readiness Level) scoring model, rolled up to a parent assembly score.

References
----------
- NASA SP-2016-6105 Rev 2 (NASA Systems Engineering Handbook) — TRL 1–9 scale.
- ISO/IEC 15288:2023 §6.3 — System maturity criteria across the lifecycle.
- INCOSE SE Handbook v4 §4.1 — maturity gate definitions.

Honest caveats
--------------
- TRL is a qualitative scale; mapping a single integer per component is an
  oversimplification. Real maturity assessments also include test heritage
  traceability, supplier capability maturity (AS9100 / CMMI), and
  demonstrated reliability in the intended operational environment.
- Weighted average by quantity is a convenience heuristic. A single
  TRL-1 component at qty=1 can ground a thousand-part assembly regardless
  of the average.  Use ``blocker_count`` (TRL < 5) alongside
  ``weighted_avg_trl`` for actionable prioritisation.
- Manufacturer qualification, drawing completeness, supplier identity, and
  test data are boolean proxies for a much richer readiness evidence package
  (e.g. DV/PV reports, FMEA, PPAP).
- Risk bands (low / medium / high / critical) are kerf heuristics; they do
  not replace a formal Systems Engineering Review Board assessment.
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = [
    "ComponentMaturity",
    "MaturityReport",
    "assess_bom_maturity",
    "HONEST_CAVEAT",
]

HONEST_CAVEAT = (
    "TRL weighted-average is a simplified proxy. "
    "Real maturity assessments include test heritage, supplier capability "
    "(AS9100 / CMMI level), demonstrated performance in operational "
    "environment, FMEA closure, and PPAP evidence packages. "
    "A single low-TRL component can block an assembly regardless of the "
    "mean score — always inspect blocker_count in addition to weighted_avg_trl. "
    "Risk bands are kerf heuristics; they do not replace a formal SRR/PDR/CDR "
    "gate review per ISO/IEC 15288:2023 §6.3."
)

# ---------------------------------------------------------------------------
# TRL validation
# ---------------------------------------------------------------------------

_TRL_MIN = 1
_TRL_MAX = 9
_TRL_BLOCKER_THRESHOLD = 5   # TRL < 5 → blocker
_TRL_LOW = 7                 # TRL >= 7 → low risk


def _validate_trl(trl: int, part_number: str) -> None:
    if not isinstance(trl, int):
        raise TypeError(
            f"trl_level must be an int for part '{part_number}', "
            f"got {type(trl).__name__}"
        )
    if not (_TRL_MIN <= trl <= _TRL_MAX):
        raise ValueError(
            f"trl_level must be in 1–9 for part '{part_number}', got {trl}"
        )


# ---------------------------------------------------------------------------
# Public dataclasses
# ---------------------------------------------------------------------------

@dataclass
class ComponentMaturity:
    """Maturity profile for a single BOM component.

    Parameters
    ----------
    part_number:           Unique part identifier (e.g. 'PN-001').
    trl_level:             NASA TRL score 1–9 (1 = basic principles observed;
                           9 = actual system proven in operational environment).
    manufacturer_qualified: True if the manufacturer holds a relevant
                            qualification (e.g. AS9100D cert, QPL listing).
    has_drawings:          True if released engineering drawings exist for
                           the part (minimum: detail drawing at revision A or
                           higher).
    has_supplier:          True if a confirmed supplier (with valid DUNS / ERP
                           supplier record) exists for the part.
    has_test_data:         True if DV or PV test reports (or equivalent
                           acceptance test data) exist for the part.
    """

    part_number: str
    trl_level: int  # 1–9
    manufacturer_qualified: bool
    has_drawings: bool
    has_supplier: bool
    has_test_data: bool

    def __post_init__(self) -> None:
        if not self.part_number or not self.part_number.strip():
            raise ValueError("part_number must be a non-empty string")
        _validate_trl(self.trl_level, self.part_number)


@dataclass
class MaturityReport:
    """Result of a BOM-level maturity assessment.

    Attributes
    ----------
    parent_pn:        Part number of the parent assembly being assessed.
    weighted_avg_trl: Quantity-weighted average TRL across all child components.
                      0.0 for an assembly with no children.
    blocker_count:    Number of child components with TRL < 5 (programme blockers
                      per ISO/IEC 15288 §6.3 gate criteria).
    risk_level:       Heuristic risk band — "low" (avg TRL ≥ 7), "medium" (5–6),
                      "high" (3–4), or "critical" (< 3 or any TRL ≤ 2).
    recommendation:   Plain-English next-step guidance.
    honest_caveat:    Scope limitation statement (see module-level HONEST_CAVEAT).
    """

    parent_pn: str
    weighted_avg_trl: float
    blocker_count: int
    risk_level: str       # "low" | "medium" | "high" | "critical"
    recommendation: str
    honest_caveat: str


# ---------------------------------------------------------------------------
# Risk classification
# ---------------------------------------------------------------------------

def _classify_risk(
    weighted_avg: float,
    children: list[ComponentMaturity],
) -> tuple[str, str]:
    """Return (risk_level, recommendation) given the weighted average TRL
    and the full child list.

    Risk bands (kerf heuristic):
      critical : any component TRL ≤ 2  OR  weighted_avg < 3
      high     : weighted_avg in [3, 5)
      medium   : weighted_avg in [5, 7)
      low      : weighted_avg >= 7

    Critical takes precedence over the average band if any single component
    is at TRL 1 or 2 — a single unproven component can ground a programme.
    """
    has_critical_component = any(c.trl_level <= 2 for c in children)

    if has_critical_component or weighted_avg < 3:
        risk = "critical"
        rec = (
            "IMMEDIATE ACTION REQUIRED: one or more components are at TRL 1–2 "
            "(basic principles only; no proof-of-concept demonstration). "
            "Escalate to programme office; consider design alternatives or "
            "technology development sprints before next programme gate."
        )
    elif weighted_avg < 5:
        risk = "high"
        rec = (
            "HIGH RISK: weighted average TRL is below 5. "
            "Components have not yet completed technology validation in relevant "
            "environment (TRL 5). Prioritise prototype testing and supplier "
            "qualification. Do not proceed to CDR without closing blocker_count "
            "components to TRL ≥ 5."
        )
    elif weighted_avg < 7:
        risk = "medium"
        rec = (
            "MEDIUM RISK: weighted average TRL is 5–6. "
            "Components have laboratory or relevant-environment validation but "
            "lack demonstration in operational environment (TRL 7). "
            "Resolve remaining blocker items and complete qualification testing "
            "before production release."
        )
    else:
        risk = "low"
        rec = (
            "LOW RISK: weighted average TRL ≥ 7. "
            "Components are demonstrated in or above operational environment. "
            "Proceed with standard design reviews; monitor any remaining "
            "items without manufacturer qualification, drawings, or test data."
        )

    return risk, rec


# ---------------------------------------------------------------------------
# Core assessment function
# ---------------------------------------------------------------------------

def assess_bom_maturity(
    parent_pn: str,
    children: list[ComponentMaturity],
    qty_per_child: dict[str, float],
) -> MaturityReport:
    """Compute a TRL-based maturity roll-up for a parent assembly.

    The weighted average TRL is:

        weighted_avg_trl = sum(trl_i × qty_i) / sum(qty_i)

    where qty_i is taken from *qty_per_child* for each child's part_number.
    Missing entries in *qty_per_child* default to 1.0.

    Parameters
    ----------
    parent_pn:     Part number of the parent assembly.
    children:      List of ComponentMaturity records for each child.
    qty_per_child: Mapping of child part_number → quantity in the assembly.
                   Quantities must be > 0.

    Returns
    -------
    MaturityReport with weighted_avg_trl, blocker_count, risk_level,
    recommendation, and honest_caveat.

    Raises
    ------
    ValueError
        If parent_pn is empty.
    ValueError
        If any qty value is ≤ 0.
    TypeError / ValueError
        Propagated from ComponentMaturity.__post_init__ for invalid TRL values.
    """
    if not parent_pn or not parent_pn.strip():
        raise ValueError("parent_pn must be a non-empty string")

    # Validate all quantities
    for pn, qty in qty_per_child.items():
        if qty <= 0:
            raise ValueError(
                f"qty for part '{pn}' must be > 0, got {qty}"
            )

    # --- Empty BOM: return a safe low-risk default ---
    if not children:
        return MaturityReport(
            parent_pn=parent_pn,
            weighted_avg_trl=0.0,
            blocker_count=0,
            risk_level="low",
            recommendation=(
                "No child components supplied. "
                "Re-run once the BOM is populated."
            ),
            honest_caveat=HONEST_CAVEAT,
        )

    # --- Weighted average ---
    total_weight = 0.0
    weighted_trl_sum = 0.0
    for comp in children:
        qty = qty_per_child.get(comp.part_number, 1.0)
        if qty <= 0:
            raise ValueError(
                f"qty for part '{comp.part_number}' must be > 0, got {qty}"
            )
        weighted_trl_sum += comp.trl_level * qty
        total_weight += qty

    weighted_avg = weighted_trl_sum / total_weight

    # --- Blocker count: TRL < 5 ---
    blocker_count = sum(1 for c in children if c.trl_level < _TRL_BLOCKER_THRESHOLD)

    # --- Risk classification ---
    risk_level, recommendation = _classify_risk(weighted_avg, children)

    return MaturityReport(
        parent_pn=parent_pn,
        weighted_avg_trl=round(weighted_avg, 4),
        blocker_count=blocker_count,
        risk_level=risk_level,
        recommendation=recommendation,
        honest_caveat=HONEST_CAVEAT,
    )
