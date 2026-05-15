"""
Steady-state junction-temperature estimator for PCB components.

Thermal resistance network model
---------------------------------
Standard three-element junction-to-ambient thermal resistance chain
(see e.g. Texas Instruments Application Report SLVA462B, "Thermal Design by
Insight, Not Hindsight"):

    Tj = Ta + P * Rtotal

  • With heatsink:
        Rtotal = θjc + θcs + θsa
      where:
        θjc  = junction-to-case (package datasheet, °C/W)
        θcs  = case-to-heatsink (interface material, °C/W)
        θsa  = heatsink-to-ambient (heatsink datasheet, °C/W)

  • Without heatsink (die to ambient through package + board spreading):
        Rtotal = θja   (effective junction-to-ambient, °C/W)

Board copper spreading (first-order)
--------------------------------------
A copper pour under a component acts as a heat-spreading plane.  The
first-order spreading resistance of a copper area A (mm²) with weight w (oz):

    Rspread [°C/W] = 1 / (k_copper * t * sqrt(π * A))

where:
    k_copper ≈ 390 W/(m·°C)  [bulk copper at 25 °C]
    t        = copper thickness (m), from standard oz-to-mm table
    A        = copper area (m²)

This is a conservative estimate; actual spreading benefits from multiple
layers and board material conduction.  Derived from the circular spreading
resistance approximation in Delphi Thermal Desktop documentation and
commonly cited in IPC-2152 board thermal design guidelines.

All functions follow the kerf never-raise contract: validation errors are
returned as dicts with {ok: False, reason: str}.

Author: imranparuk
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import List, Optional

# ── Physical constants ────────────────────────────────────────────────────────

# Copper thermal conductivity at 25 °C (W/(m·°C))
_K_COPPER = 390.0

# Standard copper weight → thickness (m)
_OZ_TO_M: dict[float, float] = {
    0.5: 17.5e-6,
    1.0: 35.0e-6,
    2.0: 70.0e-6,
    3.0: 105.0e-6,
    4.0: 140.0e-6,
}


# ── Public data classes ───────────────────────────────────────────────────────

@dataclass
class ThermalComponent:
    """Input description of a single PCB component for thermal analysis."""
    ref: str                          # e.g. "U1", "Q3"
    power_w: float                    # dissipated power (W)
    theta_ja: Optional[float] = None  # junction-to-ambient (°C/W), used when no heatsink
    theta_jc: Optional[float] = None  # junction-to-case (°C/W)
    theta_cs: float = 0.0            # case-to-heatsink interface (°C/W)
    theta_sa: Optional[float] = None  # heatsink-to-ambient (°C/W); None = no heatsink
    tj_max_c: Optional[float] = None  # max junction temp from datasheet (°C)


@dataclass
class ThermalResult:
    """Result for a single component junction-temperature calculation."""
    ref: str
    power_w: float
    ambient_c: float
    tj_c: float                        # computed junction temperature (°C)
    r_total_c_per_w: float            # effective thermal resistance used
    has_heatsink: bool
    tj_max_c: Optional[float]
    over_limit: bool                   # True when tj_c > tj_max_c (and tj_max_c given)
    margin_c: Optional[float]         # tj_max_c - tj_c; None when tj_max_c not given


@dataclass
class ComponentBoardResult:
    """Per-component result within a board thermal report."""
    ref: str
    power_w: float
    tj_c: float
    r_total_c_per_w: float
    over_limit: bool
    tj_max_c: Optional[float]
    margin_c: Optional[float]


@dataclass
class BoardThermalResult:
    """Board-level thermal rollup result."""
    ambient_c: float
    total_power_w: float
    components: List[ComponentBoardResult] = field(default_factory=list)
    worst_ref: str = ""
    worst_tj_c: float = 0.0
    any_over_limit: bool = False


# ── Core calculation: copper spreading resistance ─────────────────────────────

def copper_spreading_resistance(
    copper_area_mm2: float,
    copper_weight_oz: float = 1.0,
) -> float:
    """
    First-order copper-spreading thermal resistance (°C/W).

    Uses the circular spreading approximation:
        Rspread = 1 / (k_copper * t * sqrt(π * A))

    where A is in m², t is the copper thickness in m.

    Parameters
    ----------
    copper_area_mm2:
        Copper pour area under / around the component (mm²).
    copper_weight_oz:
        Copper foil weight (oz/ft²). Common values: 0.5, 1, 2.

    Returns
    -------
    Spreading resistance in °C/W.

    Raises
    ------
    ValueError for invalid inputs.
    """
    if copper_area_mm2 <= 0:
        raise ValueError("copper_area_mm2 must be positive")
    if copper_weight_oz <= 0:
        raise ValueError("copper_weight_oz must be positive")

    # Thickness in metres
    t_m = _OZ_TO_M.get(copper_weight_oz)
    if t_m is None:
        # Linear interpolation from 1 oz basis
        t_m = copper_weight_oz * _OZ_TO_M[1.0]

    # Area in m²
    area_m2 = copper_area_mm2 * 1e-6  # mm² → m²

    r_spread = 1.0 / (_K_COPPER * t_m * math.sqrt(math.pi * area_m2))
    return r_spread


# ── Core calculation: junction temperature ───────────────────────────────────

def thermal_junction(
    power_w: float,
    ambient_c: float,
    theta_ja: Optional[float] = None,
    theta_jc: Optional[float] = None,
    theta_cs: float = 0.0,
    theta_sa: Optional[float] = None,
    tj_max_c: Optional[float] = None,
) -> dict:
    """
    Compute steady-state junction temperature.

    Use the three-element chain when heatsink data is available:
        Tj = Ta + P * (θjc + θcs + θsa)

    Fall back to the single-parameter model when no heatsink:
        Tj = Ta + P * θja

    Parameters
    ----------
    power_w:
        Component power dissipation (W).  Zero is valid (Tj = Ta).
    ambient_c:
        Board ambient temperature (°C).
    theta_ja:
        Effective junction-to-ambient thermal resistance (°C/W).
        Required when theta_jc/theta_sa are not supplied.
    theta_jc:
        Junction-to-case thermal resistance (°C/W).  Required for the
        heatsink model.
    theta_cs:
        Case-to-heatsink interface resistance (°C/W).  Defaults to 0.0
        (direct contact / thermal pad only).
    theta_sa:
        Heatsink-to-ambient resistance (°C/W).  When supplied (not None),
        the three-element chain is used; otherwise theta_ja is used.
    tj_max_c:
        Maximum rated junction temperature from component datasheet (°C).
        When supplied, over-limit check is performed.

    Returns
    -------
    dict with keys:
        ok           : bool
        tj_c         : float — computed junction temperature
        r_total      : float — effective thermal resistance (°C/W)
        has_heatsink : bool
        over_limit   : bool  — True when tj_c > tj_max_c
        margin_c     : float | None — tj_max_c − tj_c
        reason       : str  — present only on error (ok=False)
    """
    # ── Validate ──────────────────────────────────────────────────────────
    if power_w < 0:
        return {"ok": False, "reason": "power_w must be >= 0"}
    if theta_ja is not None and theta_ja < 0:
        return {"ok": False, "reason": "theta_ja must be >= 0"}
    if theta_jc is not None and theta_jc < 0:
        return {"ok": False, "reason": "theta_jc must be >= 0"}
    if theta_cs < 0:
        return {"ok": False, "reason": "theta_cs must be >= 0"}
    if theta_sa is not None and theta_sa < 0:
        return {"ok": False, "reason": "theta_sa must be >= 0"}

    # ── Choose model ──────────────────────────────────────────────────────
    has_heatsink = theta_sa is not None and theta_jc is not None
    if has_heatsink:
        r_total = float(theta_jc) + float(theta_cs) + float(theta_sa)
    elif theta_ja is not None:
        r_total = float(theta_ja)
    else:
        return {
            "ok": False,
            "reason": (
                "Provide either theta_ja (no heatsink) or "
                "theta_jc + theta_sa (heatsink model)"
            ),
        }

    tj = ambient_c + power_w * r_total

    # ── Derating check ────────────────────────────────────────────────────
    over_limit = False
    margin: Optional[float] = None
    if tj_max_c is not None:
        margin = round(tj_max_c - tj, 6)
        over_limit = tj > tj_max_c

    return {
        "ok": True,
        "tj_c": round(tj, 6),
        "r_total": round(r_total, 6),
        "has_heatsink": has_heatsink,
        "over_limit": over_limit,
        "margin_c": margin,
    }


# ── Heatsink sizing ───────────────────────────────────────────────────────────

def thermal_heatsink_required(
    power_w: float,
    ambient_c: float,
    theta_jc: float,
    tj_max_c: float,
    theta_cs: float = 0.0,
    safety_margin_c: float = 0.0,
) -> dict:
    """
    Calculate the maximum allowable heatsink-to-ambient resistance θsa to
    keep junction temperature at or below Tj_max (with optional safety margin).

    Derivation from Tj = Ta + P * (θjc + θcs + θsa):
        θsa_max = (Tj_target − Ta) / P − θjc − θcs
    where Tj_target = Tj_max − safety_margin_c.

    Parameters
    ----------
    power_w:
        Component power dissipation (W).
    ambient_c:
        Ambient temperature (°C).
    theta_jc:
        Junction-to-case thermal resistance (°C/W).
    tj_max_c:
        Maximum rated junction temperature (°C).
    theta_cs:
        Case-to-heatsink interface resistance (°C/W).
    safety_margin_c:
        Safety margin subtracted from tj_max_c (°C). Default 0.

    Returns
    -------
    dict with keys:
        ok               : bool
        theta_sa_max_c_w : float — maximum allowable θsa (°C/W)
        tj_target_c      : float — Tj_max − safety_margin_c
        feasible         : bool  — False when P=0 (no heatsink needed) or θsa_max < 0
        reason           : str   — present only on error (ok=False)
    """
    if power_w < 0:
        return {"ok": False, "reason": "power_w must be >= 0"}
    if theta_jc < 0:
        return {"ok": False, "reason": "theta_jc must be >= 0"}
    if theta_cs < 0:
        return {"ok": False, "reason": "theta_cs must be >= 0"}
    if safety_margin_c < 0:
        return {"ok": False, "reason": "safety_margin_c must be >= 0"}

    tj_target = tj_max_c - safety_margin_c

    if power_w == 0:
        # No dissipation → no heatsink required
        return {
            "ok": True,
            "theta_sa_max_c_w": None,
            "tj_target_c": round(tj_target, 6),
            "feasible": True,
            "note": "power_w is zero — no heatsink required",
        }

    theta_sa_max = (tj_target - ambient_c) / power_w - theta_jc - theta_cs

    return {
        "ok": True,
        "theta_sa_max_c_w": round(theta_sa_max, 6),
        "tj_target_c": round(tj_target, 6),
        "feasible": theta_sa_max >= 0,
    }


# ── Board rollup ──────────────────────────────────────────────────────────────

def thermal_board_report(
    components: List[ThermalComponent],
    ambient_c: float,
) -> dict:
    """
    Board-level thermal rollup: compute Tj for every component, sum
    dissipations, and flag components over their Tj_max limit.

    Parameters
    ----------
    components:
        List of ThermalComponent descriptors.
    ambient_c:
        Board ambient temperature (°C).

    Returns
    -------
    dict with keys:
        ok             : bool
        ambient_c      : float
        total_power_w  : float
        components     : list of per-component result dicts
        worst_ref      : str  — ref of component with highest Tj
        worst_tj_c     : float
        any_over_limit : bool
        reason         : str  — present only on error (ok=False)
    """
    if not components:
        return {"ok": False, "reason": "components list is empty"}

    total_power = 0.0
    results = []
    worst_tj = -1e30
    worst_ref = ""
    any_over = False

    for comp in components:
        res = thermal_junction(
            power_w=comp.power_w,
            ambient_c=ambient_c,
            theta_ja=comp.theta_ja,
            theta_jc=comp.theta_jc,
            theta_cs=comp.theta_cs,
            theta_sa=comp.theta_sa,
            tj_max_c=comp.tj_max_c,
        )
        if not res["ok"]:
            return {
                "ok": False,
                "reason": f"component {comp.ref!r}: {res['reason']}",
            }

        total_power += comp.power_w

        entry = {
            "ref": comp.ref,
            "power_w": comp.power_w,
            "tj_c": res["tj_c"],
            "r_total_c_per_w": res["r_total"],
            "over_limit": res["over_limit"],
            "tj_max_c": comp.tj_max_c,
            "margin_c": res["margin_c"],
        }
        results.append(entry)

        if res["over_limit"]:
            any_over = True

        if res["tj_c"] > worst_tj:
            worst_tj = res["tj_c"]
            worst_ref = comp.ref

    return {
        "ok": True,
        "ambient_c": ambient_c,
        "total_power_w": round(total_power, 6),
        "components": results,
        "worst_ref": worst_ref,
        "worst_tj_c": round(worst_tj, 6),
        "any_over_limit": any_over,
    }
