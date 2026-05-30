"""duct_sizing_optimizer.py — ASHRAE §35 equal-friction duct sizing optimizer.

Implements the *equal-friction method* (ASHRAE Handbook of Fundamentals 2021,
Chapter 35 — Duct Design) for low-pressure HVAC supply and return systems.
Also provides stubs for the static-regain and T-method signatures.

DISCLAIMER: These are implementations of ASHRAE *methods* — NOT ASHRAE certified
designs. Always verify against local codes and a qualified MEP engineer.

Methods implemented
-------------------
equal_friction
    Each duct segment is sized so that the friction loss per unit length
    (in w.c. per 100 ft, or Pa/m) is constant throughout the system.
    Balances noise and material cost; default for low-pressure (<2 in w.c.
    total system) HVAC.

static_regain (stub)
    Each segment downstream of a branch is sized so that the static
    pressure regained equals the friction loss in the next segment.
    Better for long runs with many branches.

T-method (stub)
    Linear-programming optimisation over the full tree; minimises total
    cost subject to a pressure-drop budget.

All quantities
--------------
Imperial (CFM / in w.c.) at the public API; SI internally.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Literal

from kerf_hvac.pressure import friction_factor, AIR_DENSITY_KG_M3, AIR_DYNAMIC_VISCOSITY_PA_S


# ---------------------------------------------------------------------------
# Unit conversions
# ---------------------------------------------------------------------------

_CFM_TO_M3S = 4.719474432e-4       # 1 CFM = x m³/s
_FPM_TO_MS = 5.08e-3                # 1 FPM = x m/s
_IWC100_TO_PA_PER_M = 249.089 / (100.0 * 0.3048)  # 1 in w.c./100 ft → Pa/m
_M_TO_IN = 1.0 / 0.0254            # 1 m = x inches
_FT_TO_M = 0.3048


def _cfm(m3s: float) -> float:
    return m3s / _CFM_TO_M3S


def _fpm(ms: float) -> float:
    return ms / _FPM_TO_MS


# ---------------------------------------------------------------------------
# Standard HVAC round duct diameters (inches, per SMACNA/ASHRAE practice)
# ---------------------------------------------------------------------------

# Low end: 1-inch steps below 10 in; 2-inch steps 10–20 in;
# then 22, 24, 26, 28, 30, 32, 36, 42, 48, 54, 60.
_STD_DIAMETERS_IN = [
    4, 5, 6, 7, 8, 9, 10,
    12, 14, 16, 18, 20, 22, 24, 26, 28, 30, 32, 36, 42, 48, 54, 60,
]


# ---------------------------------------------------------------------------
# Data class: result for one segment
# ---------------------------------------------------------------------------

@dataclass
class SizedSegment:
    """Result for a single duct segment after sizing.

    All imperial-facing attributes use in / CFM / FPM / in-w.c.
    Internal SI values are also stored for downstream calculation.

    Attributes:
        label: Optional segment identifier (e.g. 'Trunk-1', 'Branch-A').
        flow_cfm: Design airflow through this segment (CFM).
        length_ft: Segment length (ft). -1.0 if not provided.
        method: Sizing method used.
        diameter_in: Recommended round duct diameter, inches.
            Rounded *up* to the nearest SMACNA standard size.
        diameter_exact_in: Exact (non-rounded) equivalent round diameter, in.
        velocity_fpm: Mean air velocity at the standard size (FPM).
        friction_loss_in_wc_per_100ft: Actual friction loss rate at the
            standard diameter (in w.c. / 100 ft).
        total_friction_loss_in_wc: Friction loss over the full segment length.
            0.0 if length_ft <= 0.
        equivalent_round_dia_in: Alias for diameter_in (for API symmetry).
        diameter_mm: Standard diameter in mm.
    """

    label: str = ""
    flow_cfm: float = 0.0
    length_ft: float = -1.0
    method: str = "equal_friction"

    diameter_in: float = 0.0
    diameter_exact_in: float = 0.0
    velocity_fpm: float = 0.0
    friction_loss_in_wc_per_100ft: float = 0.0
    total_friction_loss_in_wc: float = 0.0
    equivalent_round_dia_in: float = 0.0

    @property
    def diameter_mm(self) -> float:
        """Standard diameter in millimetres."""
        return self.diameter_in * 25.4


# ---------------------------------------------------------------------------
# Core equal-friction solver
# ---------------------------------------------------------------------------

def _friction_rate_pa_per_m(
    D_m: float,
    Q_m3s: float,
    rho: float = AIR_DENSITY_KG_M3,
    mu: float = AIR_DYNAMIC_VISCOSITY_PA_S,
    eps_m: float = 0.09e-3,
) -> float:
    """Compute friction loss per unit length (Pa/m) for a round duct.

    Args:
        D_m: Duct inside diameter (m).
        Q_m3s: Volumetric flow rate (m³/s).
        rho: Air density (kg/m³).
        mu: Dynamic viscosity (Pa·s).
        eps_m: Absolute roughness (m).

    Returns:
        Friction rate in Pa/m.
    """
    A = math.pi * D_m ** 2 / 4.0
    v = Q_m3s / A
    Re = rho * v * D_m / mu
    eps_D = eps_m / D_m
    f = friction_factor(Re, eps_D)
    return f * (1.0 / D_m) * 0.5 * rho * v ** 2


def _solve_diameter_for_friction_rate(
    Q_m3s: float,
    target_pa_per_m: float,
    rho: float = AIR_DENSITY_KG_M3,
    mu: float = AIR_DYNAMIC_VISCOSITY_PA_S,
    eps_m: float = 0.09e-3,
    tol_m: float = 1e-7,
) -> float:
    """Iterative bisection: find D (m) such that friction rate = target_pa_per_m.

    Uses Colebrook-White friction factor via :func:`kerf_hvac.pressure.friction_factor`.
    Convergence guaranteed by the monotonicity of friction rate with diameter at
    fixed flow and friction rate (higher D → lower friction rate).

    Args:
        Q_m3s: Volumetric flow rate (m³/s).
        target_pa_per_m: Target friction loss per unit length (Pa/m).
        rho: Air density (kg/m³).
        mu: Dynamic viscosity (Pa·s).
        eps_m: Absolute roughness (m).
        tol_m: Diameter tolerance (m). Default 1e-7 m = 0.1 µm.

    Returns:
        Exact diameter (m) satisfying the friction rate.

    Raises:
        ValueError: If no diameter in [0.02, 5.0] m satisfies the target.
    """
    if Q_m3s <= 0:
        raise ValueError("Q_m3s must be positive")
    if target_pa_per_m <= 0:
        raise ValueError("target_pa_per_m must be positive")

    D_lo, D_hi = 0.02, 5.0  # 20 mm to 5 m search range

    fr_lo = _friction_rate_pa_per_m(D_lo, Q_m3s, rho, mu, eps_m)
    fr_hi = _friction_rate_pa_per_m(D_hi, Q_m3s, rho, mu, eps_m)

    if fr_lo < target_pa_per_m:
        # Even the smallest duct has a lower friction rate — very high velocity, tiny duct
        # This happens for very small flows. Return the minimum sensible duct.
        return D_lo
    if fr_hi > target_pa_per_m:
        raise ValueError(
            f"Cannot achieve friction rate {target_pa_per_m:.4f} Pa/m for flow "
            f"{_cfm(Q_m3s):.1f} CFM within D ≤ 5 m."
        )

    # Bisection (monotonic: larger D → lower friction rate)
    for _ in range(80):
        D_mid = 0.5 * (D_lo + D_hi)
        fr_mid = _friction_rate_pa_per_m(D_mid, Q_m3s, rho, mu, eps_m)
        if fr_mid > target_pa_per_m:
            D_lo = D_mid
        else:
            D_hi = D_mid
        if (D_hi - D_lo) < tol_m:
            break

    return 0.5 * (D_lo + D_hi)


def _std_size_up(D_exact_in: float) -> float:
    """Round exact diameter up to the nearest SMACNA standard size (inches)."""
    for s in _STD_DIAMETERS_IN:
        if s >= D_exact_in - 1e-9:
            return float(s)
    return float(_STD_DIAMETERS_IN[-1])  # cap at largest standard size


def _pa_per_m_to_in_wc_per_100ft(pa_per_m: float) -> float:
    """Convert Pa/m to in w.c. per 100 ft."""
    return pa_per_m / _IWC100_TO_PA_PER_M


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def equal_friction_size(
    flow_cfm: float,
    friction_rate_in_wc_per_100ft: float = 0.08,
    roughness_mm: float = 0.09,
    max_velocity_fpm: float | None = None,
    air_density_kg_m3: float = AIR_DENSITY_KG_M3,
    air_viscosity_pa_s: float = AIR_DYNAMIC_VISCOSITY_PA_S,
) -> dict:
    """Size a round duct by the ASHRAE equal-friction method.

    Given a design airflow and a target friction rate (in w.c. / 100 ft),
    returns the exact and standard-size diameters, duct velocity, and
    friction loss rate.

    The exact diameter is solved iteratively using the Colebrook-White
    equation (ASHRAE Handbook 2021, §35). The standard diameter is the
    next SMACNA standard size at or above the exact diameter.

    If *max_velocity_fpm* is supplied, the standard diameter is also
    checked against the velocity limit and sized up if needed (relevant
    for residential / low-noise applications).

    Args:
        flow_cfm: Design airflow (CFM).
        friction_rate_in_wc_per_100ft: Target friction loss rate
            (in w.c. / 100 ft). Default 0.08 — ASHRAE default for
            low-pressure supply systems.
        roughness_mm: Duct roughness (mm). Default 0.09 mm (galvanised
            steel per ASHRAE HOF Table 1).
        max_velocity_fpm: Optional velocity ceiling (FPM). When set and
            the equal-friction diameter would exceed this velocity, the
            function sizes up to the next standard duct that satisfies
            the limit. Typical residential limit: 700 FPM.
        air_density_kg_m3: Air density (kg/m³). Default standard.
        air_viscosity_pa_s: Dynamic viscosity (Pa·s). Default standard.

    Returns:
        Dict with keys::

            diameter_in          float   Standard round duct diameter (in)
            diameter_exact_in    float   Exact (non-rounded) diameter (in)
            velocity_fpm         float   Mean velocity at standard size (FPM)
            friction_loss_in_wc_per_100ft  float  Actual friction rate at std size
            equivalent_round_dia float   Same as diameter_in (ASHRAE terminology)
            diameter_mm          float   Standard diameter in mm
            warning              str     Present when velocity limit applied

    Raises:
        ValueError: If inputs are out of range or no solution is found.

    Note:
        ASHRAE methods — NOT ASHRAE certified. Verify with a licensed MEP engineer.
    """
    if flow_cfm <= 0:
        raise ValueError("flow_cfm must be positive")
    if friction_rate_in_wc_per_100ft <= 0:
        raise ValueError("friction_rate_in_wc_per_100ft must be positive")

    Q_m3s = flow_cfm * _CFM_TO_M3S
    target_pa_per_m = friction_rate_in_wc_per_100ft * _IWC100_TO_PA_PER_M
    eps_m = roughness_mm * 1e-3

    D_exact_m = _solve_diameter_for_friction_rate(
        Q_m3s, target_pa_per_m, air_density_kg_m3, air_viscosity_pa_s, eps_m
    )
    D_exact_in = D_exact_m * _M_TO_IN

    # Round up to standard size
    D_std_in = _std_size_up(D_exact_in)
    warning: str | None = None

    # Velocity check: size up if needed
    if max_velocity_fpm is not None:
        v_max_ms = max_velocity_fpm * _FPM_TO_MS
        for s_in in _STD_DIAMETERS_IN:
            if s_in < D_std_in - 1e-9:
                continue
            D_trial_m = s_in * 0.0254
            A_trial = math.pi * D_trial_m ** 2 / 4.0
            v_trial = Q_m3s / A_trial
            if v_trial <= v_max_ms + 1e-9:
                if s_in != D_std_in:
                    warning = (
                        f"Sized up from {D_std_in}\" to {s_in}\" to satisfy "
                        f"max velocity {max_velocity_fpm:.0f} FPM"
                    )
                    D_std_in = s_in
                break

    D_std_m = D_std_in * 0.0254
    A_std = math.pi * D_std_m ** 2 / 4.0
    v_std_ms = Q_m3s / A_std
    fr_std = _friction_rate_pa_per_m(D_std_m, Q_m3s, air_density_kg_m3, air_viscosity_pa_s, eps_m)

    result: dict = {
        "diameter_in": D_std_in,
        "diameter_exact_in": round(D_exact_in, 4),
        "velocity_fpm": round(_fpm(v_std_ms), 1),
        "friction_loss_in_wc_per_100ft": round(_pa_per_m_to_in_wc_per_100ft(fr_std), 5),
        "equivalent_round_dia": D_std_in,
        "diameter_mm": round(D_std_in * 25.4, 1),
    }
    if warning:
        result["warning"] = warning
    return result


def size_duct_run(
    segments: list[dict],
    total_flow_cfm: float,
    method: Literal["equal_friction", "static_regain", "T_method"] = "equal_friction",
    friction_rate_in_wc_per_100ft: float = 0.08,
    roughness_mm: float = 0.09,
    max_velocity_fpm: float | None = None,
) -> list[SizedSegment]:
    """Size all segments in a duct run.

    For a series/branching duct run, each segment carries a fraction of
    the total design flow (upstream segments carry the cumulative downstream
    demand). This function:

    1. Distributes flow through the run (downstream demand model).
    2. Sizes each segment by the chosen method.
    3. Returns :class:`SizedSegment` objects in the same order as input.

    Segment dict schema::

        {
            "label":      str   (optional)  — identifier
            "flow_cfm":   float (optional)  — explicit flow override; if absent
                                              the segment is sized to carry the
                                              *cumulative downstream demand*
            "length_ft":  float (optional)  — segment length for total loss
            "downstream_cfm": float (optional) — flow delivered to downstream
                                              branch from this node; used to
                                              compute remaining trunk flow
        }

    Flow distribution rule (no explicit ``flow_cfm``):
        - Segment 0 (trunk entry) carries ``total_flow_cfm``.
        - Each subsequent segment carries the previous segment's flow
          minus ``downstream_cfm`` (if given) or ``total_flow_cfm / n_segments``
          if no branch splits are specified.

    Args:
        segments: Ordered list of segment dicts (trunk → terminals).
        total_flow_cfm: Total system airflow entering the first segment (CFM).
        method: Sizing method — ``'equal_friction'`` (default),
            ``'static_regain'`` (stub, falls back to equal_friction),
            or ``'T_method'`` (stub, falls back to equal_friction).
        friction_rate_in_wc_per_100ft: Target friction rate for equal-friction
            and static-regain methods.
        roughness_mm: Duct roughness (mm).
        max_velocity_fpm: Optional velocity ceiling (FPM).

    Returns:
        List of :class:`SizedSegment` in input order.

    Raises:
        ValueError: If inputs are invalid or flow distribution is inconsistent.

    Note:
        ASHRAE methods — NOT ASHRAE certified.
    """
    if not segments:
        raise ValueError("segments must be a non-empty list")
    if total_flow_cfm <= 0:
        raise ValueError("total_flow_cfm must be positive")

    if method not in ("equal_friction", "static_regain", "T_method"):
        raise ValueError(f"Unknown method: {method!r}. Choose 'equal_friction', 'static_regain', or 'T_method'.")

    # static_regain and T_method stubs fall back to equal_friction
    if method in ("static_regain", "T_method"):
        _fallback_note = (
            f"'{method}' is not yet fully implemented; "
            "falling back to equal_friction."
        )
    else:
        _fallback_note = None

    n = len(segments)
    results: list[SizedSegment] = []

    # Assign flows
    trunk_flow = total_flow_cfm
    for i, seg in enumerate(segments):
        # Explicit flow override
        if "flow_cfm" in seg and seg["flow_cfm"] is not None:
            flow_cfm = float(seg["flow_cfm"])
        else:
            flow_cfm = trunk_flow

        label = str(seg.get("label", f"seg-{i}"))
        length_ft = float(seg.get("length_ft", -1.0))

        # Size this segment
        sizing = equal_friction_size(
            flow_cfm=flow_cfm,
            friction_rate_in_wc_per_100ft=friction_rate_in_wc_per_100ft,
            roughness_mm=roughness_mm,
            max_velocity_fpm=max_velocity_fpm,
        )

        # Compute total segment friction loss if length is known
        total_fl = 0.0
        if length_ft > 0:
            total_fl = sizing["friction_loss_in_wc_per_100ft"] * length_ft / 100.0

        seg_result = SizedSegment(
            label=label,
            flow_cfm=flow_cfm,
            length_ft=length_ft,
            method=method if _fallback_note is None else "equal_friction",
            diameter_in=sizing["diameter_in"],
            diameter_exact_in=sizing["diameter_exact_in"],
            velocity_fpm=sizing["velocity_fpm"],
            friction_loss_in_wc_per_100ft=sizing["friction_loss_in_wc_per_100ft"],
            total_friction_loss_in_wc=round(total_fl, 6),
            equivalent_round_dia_in=sizing["equivalent_round_dia"],
        )
        results.append(seg_result)

        # Update trunk flow: subtract branch takeoff
        downstream_cfm = seg.get("downstream_cfm")
        if downstream_cfm is not None:
            trunk_flow = flow_cfm - float(downstream_cfm)
        else:
            # Uniform distribution: each segment delivers 1/n of total
            trunk_flow = flow_cfm - (total_flow_cfm / n)
            trunk_flow = max(trunk_flow, 0.0)

    return results


def compute_duct_cost(
    sized_segments: list[SizedSegment],
    cost_per_sq_ft: float = 5.0,
) -> float:
    """Estimate the total duct fabrication cost from sized segments.

    Uses lateral surface area of round duct:

        surface_area (sq in) = π · D_in · L_in
        cost = Σ (π · D_in · L_in · cost_per_sq_ft / 144)

    where 144 converts square inches to square feet.

    Only segments with ``length_ft > 0`` contribute to cost.

    Args:
        sized_segments: Output from :func:`size_duct_run` or a list of
            :class:`SizedSegment` objects with ``diameter_in`` and
            ``length_ft`` populated.
        cost_per_sq_ft: Duct sheet-metal / fabric cost (USD/sq ft).
            Default $5.00/sq ft (light-gauge galvanised steel + labour).

    Returns:
        Total estimated duct cost (USD).

    Note:
        ASHRAE methods — NOT ASHRAE certified.
    """
    if cost_per_sq_ft < 0:
        raise ValueError("cost_per_sq_ft must be non-negative")

    total_cost = 0.0
    for seg in sized_segments:
        if seg.length_ft > 0 and seg.diameter_in > 0:
            L_in = seg.length_ft * 12.0  # feet → inches
            # Surface area in sq_in = π × D_in × L_in
            # ÷ 144 → sq_ft; × cost_per_sq_ft → USD
            total_cost += math.pi * seg.diameter_in * L_in * cost_per_sq_ft / 144.0

    return total_cost
