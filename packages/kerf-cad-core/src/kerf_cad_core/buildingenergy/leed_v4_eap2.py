"""
kerf_cad_core.buildingenergy.leed_v4_eap2 — LEED v4.1 EAp2 + EAc1 (Optimize Energy Performance).

Evaluates the LEED v4.1 BD+C Energy & Atmosphere Prerequisite 2 (Minimum Energy
Performance) and Credit 1 (Optimize Energy Performance) against ASHRAE 90.1-2016
Appendix G as the LEED reference baseline.

HONEST FLAG: This is a design-exploration tool.  It does NOT constitute a
GBCI-certified LEED submission.  Full LEED certification requires a LEED-AP
Energy & Atmosphere qualified professional, a USGBC-approved energy modelling
methodology, and GBCI project review.

Dataclasses
-----------
LeedEAp2Spec     — project inputs: type, EUI values, rating system version
LeedEAp2Report   — prerequisite + credit result: savings %, points, caveat

Functions
---------
evaluate_leed_v4_eap2(spec) -> LeedEAp2Report

Method
------
Per USGBC LEED v4.1 BD+C Reference Guide — Energy & Atmosphere section:
  1. EAp2 (Prerequisite): proposed EUI must be ≥5% better than ASHRAE 90.1-2016
     Appendix G baseline.
  2. EAc1 (Credit): additional points (1–18) awarded per the LEED v4.1 savings
     tier table (Table EAc1-1).  New Construction baseline table is used; the
     same table applies to Major Renovation.  Core & Shell uses a 2% lower threshold.

LEED v4.1 vs v4.0 differences:
  - v4.1 uses ASHRAE 90.1-2019 as the reference standard (updated from 2016).
    This module supports both versions via spec.rating_system.
  - Point thresholds in v4.1 are identical to v4.0 up to 50% savings.

References
----------
USGBC — LEED v4 BD+C Reference Guide, Energy & Atmosphere (EA)
USGBC — LEED v4.1 Operations and Maintenance Reference Guide, EA section
ASHRAE 90.1-2016 + 90.1-2019 — Energy Standard; Appendix G baseline modelling
GBCI — LEED v4.1 Credit Library: EA Prerequisite 2 + EA Credit 1
ASHRAE 90.1-2022 Appendix G — Performance Rating Method

Author: imranparuk
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional


# ---------------------------------------------------------------------------
# LEED v4.1 EAc1 Optimize Energy Performance point table
# (Table EAc1-1, LEED v4.1 BD+C, New Construction & Major Renovation)
# Source: USGBC LEED v4.1 Credit Library, EA Credit 1
#
# Energy cost savings (% better than ASHRAE 90.1 Appendix G baseline) → points
# ---------------------------------------------------------------------------

# (minimum_savings_pct, points_earned)
_LEED_V41_POINTS_TABLE: List[tuple] = [
    (6,  1), (8,  2), (10,  3), (12,  4), (14,  5),
    (16, 6), (18, 7), (20,  8), (22,  9), (24, 10),
    (26, 11), (28, 12), (30, 13), (34, 14), (38, 15),
    (42, 16), (46, 17), (50, 18),
]

# Maximum points available for EAc1
_LEED_EAC1_MAX_POINTS = 18

# EAp2 minimum threshold per rating system / project type
# All EAp2 minimums per USGBC LEED v4.1 Reference Guide Table EAp2-1
_EAP2_MIN_PCT: Dict[str, float] = {
    "new_construction": 5.0,
    "major_renovation": 5.0,
    "core_and_shell": 3.0,   # reduced threshold for shell-only buildings
    "schools": 5.0,
    "retail": 5.0,
    "data_centers": 5.0,
    "warehouses": 5.0,
    "hospitality": 5.0,
    "healthcare": 5.0,
}

# Bonus: Core & Shell gets a -2% savings threshold reduction for EAc1 points
_CORE_SHELL_SAVINGS_BONUS = 2.0


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class LeedEAp2Spec:
    """Input specification for LEED v4 EAp2 + EAc1 evaluation.

    Attributes
    ----------
    project_type : str
        LEED project type:
        'new_construction' | 'major_renovation' | 'core_and_shell' |
        'schools' | 'retail' | 'data_centers' | 'warehouses' |
        'hospitality' | 'healthcare'.
    rating_system : str
        LEED rating system version. Default 'BD+C v4.1'.
        Accepted: 'BD+C v4.1', 'BD+C v4.0', 'ID+C v4.1', 'O+M v4.1'.
    proposed_annual_eui : float
        Proposed building annual site EUI (kWh/(m²·yr)).
    baseline_annual_eui : float
        ASHRAE 90.1-2016 (or 90.1-2019 for v4.1) Appendix G Reference Building
        annual site EUI (kWh/(m²·yr)). Use compute_compliance_report() to obtain
        the Kerf ASHRAE 90.1 baseline EUI, or supply from a full energy model.
    renewables_offset_kwh_m2 : float
        On-site renewable energy generation (kWh/(m²·yr)) that can be applied
        to reduce proposed EUI for LEED calculations. Default 0.0.
        Per LEED v4.1 EAp2 § — on-site renewables may be included in
        the proposed energy cost calculation.
    """
    project_type: str
    proposed_annual_eui: float
    baseline_annual_eui: float
    rating_system: str = "BD+C v4.1"
    renewables_offset_kwh_m2: float = 0.0


@dataclass
class LeedEAp2Report:
    """LEED v4 EAp2 + EAc1 evaluation result.

    Attributes
    ----------
    energy_savings_pct : float
        (baseline_eui - proposed_eui) / baseline_eui × 100.
        Positive = better than baseline.
    minimum_threshold_pct : float
        EAp2 minimum energy savings required (% above baseline) for this project type.
        LEED v4.1 default: 5.0% for New Construction.
    prerequisite_met : bool
        True if energy_savings_pct >= minimum_threshold_pct.
    optional_eac1_points : int
        EAc1 Optimize Energy Performance points (0–18) based on savings tier.
    net_proposed_eui : float
        Proposed EUI after subtracting renewable offset (kWh/(m²·yr)).
    honest_caveat : str
        Methodology and certification caveat.
    point_detail : list[str]
        Narrative list explaining the point award.
    """
    energy_savings_pct: float
    minimum_threshold_pct: float
    prerequisite_met: bool
    optional_eac1_points: int
    net_proposed_eui: float = 0.0
    honest_caveat: str = ""
    point_detail: List[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Point lookup
# ---------------------------------------------------------------------------

def _leed_eac1_points(savings_pct: float, project_type: str) -> int:
    """Look up EAc1 points from savings percentage.

    Core & Shell buildings receive a 2% bonus (savings threshold reduced by 2pp)
    per USGBC LEED v4.1 Core & Shell exception.
    """
    effective_pct = savings_pct
    if project_type.lower() == "core_and_shell":
        effective_pct += _CORE_SHELL_SAVINGS_BONUS

    points = 0
    for min_pct, pts in _LEED_V41_POINTS_TABLE:
        if effective_pct >= min_pct:
            points = pts
    return min(points, _LEED_EAC1_MAX_POINTS)


# ---------------------------------------------------------------------------
# Core evaluation
# ---------------------------------------------------------------------------

def evaluate_leed_v4_eap2(spec: LeedEAp2Spec) -> LeedEAp2Report:
    """Evaluate LEED v4.1 EAp2 (prerequisite) and EAc1 (credit) performance.

    Algorithm
    ---------
    1. Subtract renewable energy offset from proposed EUI.
    2. Calculate energy savings % vs. ASHRAE 90.1 Appendix G baseline.
    3. Check EAp2 prerequisite (≥5% savings for NC).
    4. Look up EAc1 point tier from savings table.

    Parameters
    ----------
    spec : LeedEAp2Spec

    Returns
    -------
    LeedEAp2Report

    Raises
    ------
    ValueError : if proposed_annual_eui or baseline_annual_eui ≤ 0.

    References
    ----------
    USGBC — LEED v4.1 BD+C Reference Guide, EA Prerequisite 2 and EA Credit 1
    ASHRAE 90.1-2016 Appendix G — Performance Rating Method (LEED v4 baseline)
    ASHRAE 90.1-2019 Appendix G — Performance Rating Method (LEED v4.1 baseline)
    """
    if spec.proposed_annual_eui <= 0:
        raise ValueError("proposed_annual_eui must be > 0")
    if spec.baseline_annual_eui <= 0:
        raise ValueError("baseline_annual_eui must be > 0")

    ptype_key = spec.project_type.lower().replace("-", "_").replace(" ", "_")
    min_threshold = _EAP2_MIN_PCT.get(ptype_key, 5.0)  # default 5% if type unknown

    # Renewable offset reduces proposed EUI
    net_proposed = max(0.0, spec.proposed_annual_eui - max(0.0, spec.renewables_offset_kwh_m2))

    # Savings calculation per LEED v4.1 EAp2/EAc1
    savings_pct = (spec.baseline_annual_eui - net_proposed) / spec.baseline_annual_eui * 100.0

    prereq_met = savings_pct >= min_threshold
    eac1_points = _leed_eac1_points(savings_pct, ptype_key) if prereq_met else 0

    # --- point detail narrative ---
    detail: List[str] = []
    if prereq_met:
        detail.append(
            f"EAp2 Prerequisite MET: {savings_pct:.1f}% energy savings ≥ "
            f"{min_threshold:.1f}% minimum for {spec.project_type}."
        )
    else:
        detail.append(
            f"EAp2 Prerequisite NOT MET: {savings_pct:.1f}% energy savings < "
            f"{min_threshold:.1f}% minimum. Building CANNOT pursue LEED certification "
            f"until this prerequisite is satisfied."
        )

    if prereq_met and eac1_points > 0:
        # Find the tier boundaries
        prev_min = 0.0
        next_min: Optional[float] = None
        for min_pct, pts in _LEED_V41_POINTS_TABLE:
            if pts == eac1_points:
                prev_min = float(min_pct)
            if pts == eac1_points + 1:
                next_min = float(min_pct)
                break
        detail.append(
            f"EAc1 Optimize Energy Performance: {eac1_points} point(s) "
            f"(savings tier ≥{prev_min:.0f}%)."
        )
        if next_min and savings_pct < next_min:
            gap = next_min - savings_pct
            detail.append(
                f"To earn {eac1_points + 1} EAc1 points, improve energy savings by "
                f"{gap:.1f}% more (target ≥{next_min:.0f}%)."
            )
        elif savings_pct >= _LEED_V41_POINTS_TABLE[-1][0]:
            detail.append("Maximum EAc1 points (18) achieved at ≥50% savings tier.")
    elif prereq_met:
        # Prerequisite met but below first point threshold (5–6%)
        detail.append(
            f"EAc1 requires ≥6% savings for 1 point. Current savings: {savings_pct:.1f}%. "
            "No optional EAc1 credit awarded, but EAp2 prerequisite is satisfied."
        )

    if spec.renewables_offset_kwh_m2 > 0:
        detail.append(
            f"Renewable energy offset applied: {spec.renewables_offset_kwh_m2:.1f} kWh/(m²·yr). "
            f"Net proposed EUI: {net_proposed:.1f} kWh/(m²·yr) "
            f"(from gross {spec.proposed_annual_eui:.1f} kWh/(m²·yr))."
        )

    caveat = (
        "This is a simplified LEED v4.1 EAp2 + EAc1 screening tool for design exploration. "
        "It does NOT constitute a GBCI-certified LEED submission. "
        "Full LEED certification requires a LEED-AP qualified professional, a USGBC-approved "
        "energy modelling methodology (whole building energy simulation per ASHRAE 90.1-2016 "
        "or 90.1-2019 Appendix G), and GBCI project review. "
        "EUI-based savings are indicative; energy cost savings (used in formal submissions) "
        "may differ from EUI savings by ±5–15% depending on fuel mix and utility rates. "
        "Refer to USGBC LEED v4.1 BD+C Reference Guide, EA section."
    )

    return LeedEAp2Report(
        energy_savings_pct=round(savings_pct, 2),
        minimum_threshold_pct=min_threshold,
        prerequisite_met=prereq_met,
        optional_eac1_points=eac1_points,
        net_proposed_eui=round(net_proposed, 2),
        honest_caveat=caveat,
        point_detail=detail,
    )
