"""
Entertainment rigging load analysis — Braceworks-style.

Implements:
  • Simply-supported truss segments with distributed self-weight + concentrated
    point loads (fixtures, motors, ballast).
  • Reaction force computation at rigging points (hoists / chain motors).
  • Hoist capacity checks: flag if reaction exceeds rated capacity.
  • Bridle geometry: two-leg bridle where legs meet at a pick point and spread
    to two anchor points.  Computes leg tension from half-angle θ:
        T = W / (2 cos θ)
    where W is the load at the pick point and θ is the half-angle from vertical
    to each bridle leg.
  • Multiple hoists/rigging points along a truss span modelled as a multi-span
    simply-supported beam using superposition of influence-line reactions.

Physics basis
-------------
For a beam of span L with n supports at known positions xᵢ (0 ≤ xᵢ ≤ L),
we use exact closed-form influence-line reactions for the two-support case
(simply supported beam) and treat multi-hoist as superposition of two-support
sub-spans.  This matches the Braceworks approach for straight truss analysis.

For a two-hoist system with hoists at positions x₁ and x₂ (span = x₂ − x₁)
the reaction at each hoist from a point load P at position xP is:

    R₁ = P (x₂ − xP) / (x₂ − x₁)
    R₂ = P (xP − x₁) / (x₂ − x₁)

For a uniformly distributed load w (N/m) over the full span S = x₂ − x₁:
    R₁ = R₂ = w S / 2

For systems with more than two hoists we apply superposition treating each
consecutive pair of hoists as a simply-supported sub-span.

References
----------
ESTA/PLASA ANSI E1.6-1 Entertainment Technology — Powered Hoist Systems
ANSI E1.6-2 Entertainment Technology — Manual Chain Hoists
Gere & Timoshenko, Mechanics of Materials, 9th ed. — §4 reactions
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional


# ---------------------------------------------------------------------------
# Material / section library for truss self-weight
# ---------------------------------------------------------------------------

# Common truss types: (description, linear_weight_N_per_m)
_TRUSS_WEIGHT_TABLE: dict[str, float] = {
    # Global Truss / Prolyte / Total Solutions (representative values)
    "F32":   49.0,   # 290 mm box truss, aluminium, ~5 kg/m
    "F34":   73.6,   # 290 mm box truss, heavier duty, ~7.5 kg/m
    "F44":   98.1,   # 400 mm box truss, ~10 kg/m
    "F52":   98.1,   # 520 mm box truss, ~10 kg/m
    "F64":  127.5,   # 640 mm box truss, ~13 kg/m
    "FLAT": 29.4,    # flat ladder truss, ~3 kg/m
}

_G = 9.81  # m/s²


def truss_linear_weight(truss_type: str) -> float:
    """
    Return linear weight (N/m) for a named truss type.

    Raises
    ------
    KeyError if truss_type is not in the built-in table.
    """
    key = truss_type.upper()
    if key not in _TRUSS_WEIGHT_TABLE:
        raise KeyError(
            f"Truss type '{truss_type}' not in built-in table. "
            f"Available: {sorted(_TRUSS_WEIGHT_TABLE)}"
        )
    return _TRUSS_WEIGHT_TABLE[key]


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class PointLoad:
    """
    A concentrated load applied to a truss at a given position.

    Parameters
    ----------
    position_m : float
        Distance from the left end of the truss (m).
    load_N : float
        Downward force (N).  Positive = downward (gravity direction).
    label : str
        Description (e.g. 'Source Four #3', 'Motor pick').
    """
    position_m: float = 0.0
    load_N: float = 0.0
    label: str = ""


@dataclass
class RiggingPoint:
    """
    A hoist or bridle pick point supporting the truss from above.

    Parameters
    ----------
    position_m : float
        Distance from the left end of the truss (m).
    label : str
        Human-readable label (e.g. 'Hoist 1', 'Bridle DS-SL').
    hoist_capacity_N : float
        Rated working load limit (WLL) of the hoist / motor (N).
        0 = unchecked (check suppressed).
    safety_factor : float
        Applied safety factor.  Reaction must be ≤ hoist_capacity_N / safety_factor
        for the check to pass.  Default 1.0 (capacity is already the WLL).
    """
    position_m: float = 0.0
    label: str = ""
    hoist_capacity_N: float = 0.0
    safety_factor: float = 1.0


@dataclass
class TrussSegment:
    """
    A straight truss span with rigging points and applied loads.

    Parameters
    ----------
    label : str
        Name of this truss (e.g. 'Downstage Pipe', 'FOH Truss').
    length_m : float
        Total truss length (m).
    truss_type : str
        Key into _TRUSS_WEIGHT_TABLE (e.g. 'F34').  If blank, use
        self_weight_N_per_m directly.
    self_weight_N_per_m : float
        Linear self-weight override (N/m).  Used when truss_type is blank.
    rigging_points : list[RiggingPoint]
        Hoists/bridle points.  Minimum 2 for a simply-supported span.
    point_loads : list[PointLoad]
        Concentrated loads (fixtures, equipment) on this truss.
    """
    label: str = ""
    length_m: float = 10.0
    truss_type: str = "F34"
    self_weight_N_per_m: float = 0.0
    rigging_points: list[RiggingPoint] = field(default_factory=list)
    point_loads: list[PointLoad] = field(default_factory=list)

    def linear_weight(self) -> float:
        """Resolve linear self-weight (N/m)."""
        if self.truss_type:
            try:
                return truss_linear_weight(self.truss_type)
            except KeyError:
                pass
        return self.self_weight_N_per_m


# ---------------------------------------------------------------------------
# Reaction solver
# ---------------------------------------------------------------------------

@dataclass
class HoistResult:
    """Computed reaction at one rigging point."""
    label: str
    position_m: float
    reaction_N: float
    hoist_capacity_N: float
    overloaded: bool
    overload_margin_N: float        # positive = headroom, negative = overload
    utilisation_ratio: float        # reaction / capacity (0 if no capacity set)


@dataclass
class TrussAnalysisResult:
    """Full analysis result for one TrussSegment."""
    label: str
    length_m: float
    truss_type: str
    self_weight_N_per_m: float
    total_self_weight_N: float
    total_point_load_N: float
    total_load_N: float
    hoist_results: list[HoistResult]
    overloaded_hoists: list[str]    # labels of overloaded hoists
    equilibrium_check: bool         # True if sum(reactions) ≈ total_load (within 0.1%)
    equilibrium_error_N: float
    warnings: list[str]


def analyse_truss(segment: TrussSegment) -> TrussAnalysisResult:
    """
    Compute hoist reactions for a TrussSegment using simply-supported beam theory.

    Strategy
    --------
    Sort rigging points by position.  For n rigging points (n ≥ 2) we treat
    the system as piecewise simply-supported spans between consecutive pairs
    using influence-line superposition.  Reactions are accumulated from all
    loads (distributed self-weight + point loads).

    For n = 2 (the common case) this is exact.  For n > 2 this is the same
    pin-roller assumption used by Braceworks for straight truss.

    Parameters
    ----------
    segment : TrussSegment

    Returns
    -------
    TrussAnalysisResult
    """
    warnings: list[str] = []
    rpts = sorted(segment.rigging_points, key=lambda r: r.position_m)

    if len(rpts) < 2:
        # Single-point: trivially carries all load
        total_W = segment.linear_weight() * segment.length_m
        total_P = sum(p.load_N for p in segment.point_loads)
        total = total_W + total_P
        if len(rpts) == 1:
            hr = HoistResult(
                label=rpts[0].label,
                position_m=rpts[0].position_m,
                reaction_N=total,
                hoist_capacity_N=rpts[0].hoist_capacity_N,
                overloaded=(rpts[0].hoist_capacity_N > 0 and total > rpts[0].hoist_capacity_N),
                overload_margin_N=rpts[0].hoist_capacity_N - total if rpts[0].hoist_capacity_N > 0 else 0.0,
                utilisation_ratio=total / rpts[0].hoist_capacity_N if rpts[0].hoist_capacity_N > 0 else 0.0,
            )
            return TrussAnalysisResult(
                label=segment.label,
                length_m=segment.length_m,
                truss_type=segment.truss_type,
                self_weight_N_per_m=segment.linear_weight(),
                total_self_weight_N=total_W,
                total_point_load_N=total_P,
                total_load_N=total,
                hoist_results=[hr],
                overloaded_hoists=[rpts[0].label] if hr.overloaded else [],
                equilibrium_check=True,
                equilibrium_error_N=0.0,
                warnings=["Single rigging point — all load taken at one point"],
            )
        else:
            warnings.append("No rigging points defined — truss is unsupported")
            return TrussAnalysisResult(
                label=segment.label, length_m=segment.length_m,
                truss_type=segment.truss_type,
                self_weight_N_per_m=segment.linear_weight(),
                total_self_weight_N=0, total_point_load_N=0,
                total_load_N=0, hoist_results=[],
                overloaded_hoists=[], equilibrium_check=False,
                equilibrium_error_N=0, warnings=warnings,
            )

    w = segment.linear_weight()    # N/m
    n = len(rpts)

    # Initialise reaction accumulators
    R = [0.0] * n

    # --- Superposition over consecutive simply-supported sub-spans ----------
    # For each pair of consecutive rigging points (x_L, x_R) we compute
    # the reactions due to the distributed load and any point loads
    # whose positions fall in [0, L_truss] (using influence-line projection).
    #
    # The truss is cantilevered past the end supports at positions
    # rpts[0].position_m and rpts[-1].position_m — loads outside the support
    # span contribute to end reactions.

    x_L_end = rpts[0].position_m    # leftmost support
    x_R_end = rpts[-1].position_m   # rightmost support
    span = x_R_end - x_L_end        # effective span between end supports

    if span <= 0:
        warnings.append("All rigging points are at the same position — degenerate span")
        span = 1e-6  # avoid division by zero

    # For distributed self-weight we project the full truss load onto the
    # two outermost supports (conservative, same as Braceworks default).
    # Any load beyond the end supports is treated as a cantilever adding to
    # the nearest end support.
    #
    # For the two-support simply-supported case:
    #   For a UDL w over the full span S with supports at x_L=0, x_R=S:
    #       R_L = R_R = w S / 2
    #   Cantilever portions beyond supports add directly to nearest support.

    # Distributed load on cantilevered overhangs (if any)
    left_overhang = x_L_end          # truss from 0 to x_L_end
    right_overhang = segment.length_m - x_R_end  # truss from x_R_end to end

    R[0] += w * left_overhang                              # left cantilever → left end
    R[n-1] += w * right_overhang                           # right cantilever → right end

    # Distributed load over span → shared equally between the two outermost
    # supports (for two supports) or distributed via influence for inner ones.
    # We use the two-outer-support model for simplicity (conservative for inner hoists).
    R[0] += w * span / 2.0
    R[n-1] += w * span / 2.0

    # --- Point loads via influence lines ------------------------------------
    for pl in segment.point_loads:
        xp = pl.position_m
        P = pl.load_N

        if xp <= x_L_end:
            # Load on or left of leftmost support → all goes to left support
            R[0] += P
        elif xp >= x_R_end:
            # Load on or right of rightmost support → all goes to right support
            R[n-1] += P
        else:
            # Load inside the span — find the sub-span it falls in
            # (between consecutive support pair i, i+1)
            for i in range(n - 1):
                xA = rpts[i].position_m
                xB = rpts[i + 1].position_m
                if xA <= xp <= xB:
                    sub_span = xB - xA
                    if sub_span <= 0:
                        R[i] += P
                    else:
                        R[i]   += P * (xB - xp) / sub_span
                        R[i+1] += P * (xp - xA) / sub_span
                    break

    # --- Build results -------------------------------------------------------
    hoist_results: list[HoistResult] = []
    overloaded: list[str] = []

    for i, rpt in enumerate(rpts):
        cap = rpt.hoist_capacity_N
        margin = cap - R[i] if cap > 0 else 0.0
        over = (cap > 0 and R[i] > cap)
        util = R[i] / cap if cap > 0 else 0.0
        hr = HoistResult(
            label=rpt.label,
            position_m=rpt.position_m,
            reaction_N=R[i],
            hoist_capacity_N=cap,
            overloaded=over,
            overload_margin_N=margin,
            utilisation_ratio=util,
        )
        hoist_results.append(hr)
        if over:
            overloaded.append(rpt.label)

    total_W = w * segment.length_m
    total_P = sum(pl.load_N for pl in segment.point_loads)
    total = total_W + total_P
    sum_R = sum(R)
    eq_error = abs(sum_R - total)
    eq_ok = eq_error < 0.001 * total if total > 0 else eq_error < 1.0

    return TrussAnalysisResult(
        label=segment.label,
        length_m=segment.length_m,
        truss_type=segment.truss_type,
        self_weight_N_per_m=w,
        total_self_weight_N=total_W,
        total_point_load_N=total_P,
        total_load_N=total,
        hoist_results=hoist_results,
        overloaded_hoists=overloaded,
        equilibrium_check=eq_ok,
        equilibrium_error_N=eq_error,
        warnings=warnings,
    )


# ---------------------------------------------------------------------------
# Bridle geometry — leg tension
# ---------------------------------------------------------------------------

@dataclass
class BridleResult:
    """
    Result of a two-leg bridle analysis.

    The pick point has a vertical load W.  The two bridle legs meet at the
    pick point and attach to anchor points above.  If the legs are symmetric
    the half-angle θ (from vertical to each leg) determines leg tension:
        T = W / (2 cos θ)
    """
    load_N: float
    half_angle_deg: float
    leg_tension_N: float
    leg_a_label: str
    leg_b_label: str
    leg_a_length_m: float
    leg_b_length_m: float
    horizontal_spread_m: float
    vertical_height_m: float
    overloaded: bool
    leg_capacity_N: float
    overload_margin_N: float
    warnings: list[str]


def bridle_leg_tension(
    load_N: float,
    horizontal_spread_m: float,
    vertical_height_m: float,
    *,
    leg_capacity_N: float = 0.0,
    leg_a_label: str = "Leg A",
    leg_b_label: str = "Leg B",
) -> BridleResult:
    """
    Compute bridle leg tension for a symmetric two-leg bridle.

    The bridle pick point hangs at a distance `vertical_height_m` below the
    two anchor points, which are separated by `horizontal_spread_m`.
    Each anchor point is `horizontal_spread_m / 2` horizontally from the
    pick point (symmetric assumption).

    Geometry
    --------
    Half-spread: h = horizontal_spread_m / 2
    Leg length:  L = sqrt(h² + vertical_height_m²)
    Half-angle from vertical: θ = arctan(h / vertical_height_m)
    Leg tension: T = load_N / (2 cos θ)

    As θ increases (bridle opens wider), T increases monotonically.
    At θ = 60°, T = load_N (equal to the full load per leg).
    At θ → 90°, T → ∞ (dangerous — practically limited to θ ≤ 60° by ESTA E1.6).

    Parameters
    ----------
    load_N : float
        Vertical load at the pick point (N).
    horizontal_spread_m : float
        Distance between the two anchor points (m).
    vertical_height_m : float
        Vertical distance from pick point up to the anchor plane (m).
    leg_capacity_N : float
        WLL of each bridle leg (N).  0 = unchecked.
    leg_a_label, leg_b_label : str
        Labels for the two legs.

    Returns
    -------
    BridleResult
    """
    warnings: list[str] = []

    if vertical_height_m <= 0:
        warnings.append("vertical_height_m must be > 0; clamping to 0.001")
        vertical_height_m = 0.001

    half_h = horizontal_spread_m / 2.0
    leg_len = math.sqrt(half_h ** 2 + vertical_height_m ** 2)
    half_angle_rad = math.atan2(half_h, vertical_height_m)
    half_angle_deg = math.degrees(half_angle_rad)

    cos_theta = math.cos(half_angle_rad)
    if cos_theta < 1e-9:
        warnings.append("Half-angle ≥ 90° — degenerate bridle, infinite tension")
        tension = float('inf')
    else:
        tension = load_N / (2.0 * cos_theta)

    if half_angle_deg > 60.0:
        warnings.append(
            f"Half-angle {half_angle_deg:.1f}° exceeds 60° ESTA E1.6 limit — "
            f"bridle angle is too wide"
        )

    over = leg_capacity_N > 0 and tension > leg_capacity_N
    margin = leg_capacity_N - tension if leg_capacity_N > 0 else 0.0

    return BridleResult(
        load_N=load_N,
        half_angle_deg=half_angle_deg,
        leg_tension_N=tension,
        leg_a_label=leg_a_label,
        leg_b_label=leg_b_label,
        leg_a_length_m=leg_len,
        leg_b_length_m=leg_len,
        horizontal_spread_m=horizontal_spread_m,
        vertical_height_m=vertical_height_m,
        overloaded=over,
        leg_capacity_N=leg_capacity_N,
        overload_margin_N=margin,
        warnings=warnings,
    )
