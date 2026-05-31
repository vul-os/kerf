"""
kerf_mold.cooling_turbulent_re_check
======================================
Reynolds-number turbulence check for injection-mold cooling channels.

Theory
------
Effective heat transfer in mold cooling channels requires turbulent flow so
that the thin thermal boundary layer is continuously disrupted, maximising the
convective heat-transfer coefficient h.  The Dittus-Boelter correlation
(Incropera & DeWitt "Fundamentals of Heat and Mass Transfer", Eq. 8.60):

    Nu = 0.023 · Re^0.8 · Pr^n       (n=0.4 heating coolant, n=0.3 cooling)

is ONLY valid for fully turbulent, hydrodynamically and thermally developed
pipe flow with Re ≥ 10 000.  At lower Reynolds numbers the Nusselt number
(and therefore h) drops significantly; at Re < 2 300 (laminar) the flow is
thermally stratified and Dittus-Boelter must NOT be used.

Reynolds number definition (White "Fluid Mechanics" §8.1, eq. 8.1):

    Re = ρ · v · D / μ

where:
  ρ  = coolant density [kg/m³]
  v  = mean flow velocity in the channel [m/s]
  D  = hydraulic diameter of the channel [m]
  μ  = dynamic viscosity [Pa·s]

Mean velocity from volumetric flow rate Q [m³/s] and cross-sectional area A:

    A = π · (D/2)²   [m²]
    v = Q / A         [m/s]

Flow-regime thresholds (White §8.1; Beaumont 2007 §11 cooling-circuit design):
  Re < 2 300       → laminar     (avoid; Dittus-Boelter does not apply)
  2 300 ≤ Re < 4 000 → transitional (unpredictable heat transfer; avoid)
  4 000 ≤ Re < 10 000 → turbulent (Dittus-Boelter is valid but h is lower;
                         some practical guides consider this acceptable for
                         light-duty applications)
  Re ≥ 10 000     → fully_turbulent (Dittus-Boelter applicable; target for
                         effective mold cooling per Beaumont 2007 §11)

Recommended minimum flow rate calculation:
  Rearranging Re ≥ Re_target=10 000 for the minimum Q:
    Q_min = (Re_target · μ · A) / (ρ · D)
  converted to L/min: Q_min_L_per_min = Q_min_m3_s × 60 000

Unit conversions:
  diameter:  mm → m  (× 1e-3)
  flow rate: L/min → m³/s  (÷ 60 000)
  viscosity: cP → Pa·s  (× 1e-3)

Honest caveats
--------------
This module:
  • Computes Re and flow regime ONLY — it does NOT compute the Nusselt
    number, convective HTC, or heat flux from the coolant to the mold steel.
  • Does NOT model the polymer-side (part-side) boundary layer, the contact
    resistance between the molded part and the mold surface, or the thermal
    resistance of the mold steel wall — all of which dominate the actual
    cycle-time and part-temperature distribution.
  • Assumes a smooth circular channel cross-section (hydraulic diameter = D).
    Conformal, keyhole, or slotted channels have different D_h; user must
    supply the equivalent hydraulic diameter.
  • Assumes isothermal, incompressible, Newtonian single-phase flow — valid
    for water and dilute water-glycol at typical mold coolant temperatures
    (10–40 °C); does NOT model supercritical CO₂ or two-phase cooling.
  • Viscosity is entered as a single value (spatially uniform) — in practice,
    coolant viscosity varies along the channel as it picks up heat; for ΔT
    > 10 °C, re-run with exit-temperature viscosity.

References
----------
Beaumont J.P. "Runner and Gating Design Handbook", 2nd ed., Hanser 2007,
  §11 (Cooling system design); §11.1 (Reynolds number and turbulent flow
  requirement for mold cooling).
White F.M. "Fluid Mechanics", 8th ed., McGraw-Hill 2016, §8.1 (Internal
  pipe flow; Re definition; laminar/turbulent thresholds), §8.3 (Turbulent
  pipe flow; Blasius, Moody chart).
Incropera F.P., DeWitt D.P. "Fundamentals of Heat and Mass Transfer",
  7th ed., Wiley 2011, §8.5 (Dittus-Boelter correlation; Re ≥ 10 000
  validity criterion; eq. 8.60).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field


# ---------------------------------------------------------------------------
# Flow-regime thresholds (White §8.1; Beaumont 2007 §11)
# ---------------------------------------------------------------------------

#: Upper boundary of laminar regime
_RE_LAMINAR_MAX: float = 2300.0

#: Lower boundary of turbulent regime (below this = transitional)
_RE_TURBULENT_MIN: float = 4000.0

#: Minimum Re for Dittus-Boelter applicability (Beaumont 2007 §11; Incropera eq. 8.60)
_RE_FULLY_TURBULENT: float = 10_000.0


# ---------------------------------------------------------------------------
# Input dataclass
# ---------------------------------------------------------------------------

@dataclass
class CoolingFlowSpec:
    """Specification for a single cooling-channel flow condition.

    Parameters
    ----------
    channel_diameter_mm : float
        Internal (hydraulic) diameter of the circular cooling channel [mm].
        Must be > 0.  For non-circular channels supply the hydraulic diameter
        D_h = 4·A/P (4 × cross-section area / wetted perimeter).
    flow_rate_L_per_min : float
        Volumetric coolant flow rate [L/min].  Must be > 0.
    coolant_density_kg_m3 : float
        Coolant density [kg/m³].  Default 1000.0 (water at ~20 °C).
        For 30 % ethylene-glycol/water use ~1040 kg/m³.
    coolant_viscosity_cP : float
        Dynamic viscosity [centipoise].  Default 1.0 cP (water at ~20 °C).
        1 cP = 1e-3 Pa·s.  For 30 % EG/water at 20 °C use ~2.0 cP.
    """

    channel_diameter_mm: float
    flow_rate_L_per_min: float
    coolant_density_kg_m3: float = 1000.0
    coolant_viscosity_cP: float = 1.0

    def __post_init__(self) -> None:
        if self.channel_diameter_mm <= 0.0:
            raise ValueError(
                f"CoolingFlowSpec.channel_diameter_mm must be > 0, "
                f"got {self.channel_diameter_mm}"
            )
        if self.flow_rate_L_per_min <= 0.0:
            raise ValueError(
                f"CoolingFlowSpec.flow_rate_L_per_min must be > 0, "
                f"got {self.flow_rate_L_per_min}"
            )
        if self.coolant_density_kg_m3 <= 0.0:
            raise ValueError(
                f"CoolingFlowSpec.coolant_density_kg_m3 must be > 0, "
                f"got {self.coolant_density_kg_m3}"
            )
        if self.coolant_viscosity_cP <= 0.0:
            raise ValueError(
                f"CoolingFlowSpec.coolant_viscosity_cP must be > 0, "
                f"got {self.coolant_viscosity_cP}"
            )


# ---------------------------------------------------------------------------
# Output dataclass
# ---------------------------------------------------------------------------

_HONEST_CAVEAT = (
    "Re check per White 'Fluid Mechanics' §8.1 + Beaumont 2007 §11. "
    "SCOPE LIMITS: (1) Re classification ONLY — does NOT compute Nusselt "
    "number, convective HTC (h), or coolant-to-steel heat flux; Dittus-"
    "Boelter (Incropera eq. 8.60) gives Nu = 0.023·Re^0.8·Pr^n but "
    "requires Pr (Prandtl number) and is outside this module's scope. "
    "(2) Polymer-side boundary layer, mold-steel wall thermal resistance, "
    "and part-steel contact resistance are NOT modelled — these dominate "
    "the actual cycle time. (3) Circular cross-section assumed — for "
    "conformal/keyhole channels supply hydraulic diameter D_h = 4A/P. "
    "(4) Single-phase, isothermal, incompressible, Newtonian fluid — does "
    "NOT model two-phase / supercritical CO₂ cooling. (5) Viscosity "
    "spatially uniform — for ΔT > 10 °C re-run with exit viscosity."
)


@dataclass
class TurbulentReCheckReport:
    """Result of a cooling-channel Reynolds-number turbulence check.

    Attributes
    ----------
    reynolds_number : float
        Computed Re = ρ·v·D/μ (dimensionless).
    flow_regime : str
        One of: ``"laminar"`` (Re < 2 300), ``"transitional"``
        (2 300 ≤ Re < 4 000), ``"turbulent"`` (4 000 ≤ Re < 10 000),
        ``"fully_turbulent"`` (Re ≥ 10 000).
    velocity_m_per_s : float
        Mean flow velocity in the channel [m/s].
    recommended_min_flow_rate_L_per_min : float
        Minimum flow rate [L/min] required to reach Re = 10 000 (fully
        turbulent) with the given channel diameter and coolant properties.
    dittus_boelter_applicable : bool
        ``True`` iff Re ≥ 10 000 (Incropera eq. 8.60 validity criterion).
    honest_caveat : str
        Plain-language statement of model scope and limitations.
    """

    reynolds_number: float
    flow_regime: str
    velocity_m_per_s: float
    recommended_min_flow_rate_L_per_min: float
    dittus_boelter_applicable: bool
    honest_caveat: str = field(default=_HONEST_CAVEAT)


# ---------------------------------------------------------------------------
# Core computation
# ---------------------------------------------------------------------------

def check_turbulent_re(spec: CoolingFlowSpec) -> TurbulentReCheckReport:
    """Compute Reynolds number and classify the flow regime for a cooling channel.

    Parameters
    ----------
    spec : CoolingFlowSpec
        Channel geometry and coolant flow conditions.

    Returns
    -------
    TurbulentReCheckReport
        Reynolds number, flow regime, velocity, minimum recommended flow
        rate, Dittus-Boelter applicability flag, and honest caveat.

    Raises
    ------
    ValueError
        If any field in *spec* is invalid (delegated to ``__post_init__``).

    Notes
    -----
    Computation path:

    1. Convert units::

         D [m]      = channel_diameter_mm × 1e-3
         Q [m³/s]   = flow_rate_L_per_min / 60 000
         μ [Pa·s]   = coolant_viscosity_cP × 1e-3

    2. Cross-section area and mean velocity::

         A = π · (D/2)²
         v = Q / A

    3. Reynolds number::

         Re = ρ · v · D / μ

    4. Flow-regime classification (White §8.1)::

         Re < 2 300              → "laminar"
         2 300 ≤ Re < 4 000      → "transitional"
         4 000 ≤ Re < 10 000     → "turbulent"
         Re ≥ 10 000             → "fully_turbulent"

    5. Minimum recommended flow rate for Re = 10 000::

         Q_min = Re_target · μ · A / (ρ · D)
         Q_min_L_per_min = Q_min × 60 000

    """
    # --- Unit conversions ---
    D: float = spec.channel_diameter_mm * 1e-3          # m
    Q: float = spec.flow_rate_L_per_min / 60_000.0      # m³/s
    rho: float = spec.coolant_density_kg_m3              # kg/m³
    mu: float = spec.coolant_viscosity_cP * 1e-3         # Pa·s

    # --- Cross-section and velocity ---
    A: float = math.pi * (D / 2.0) ** 2                 # m²
    v: float = Q / A                                     # m/s

    # --- Reynolds number ---
    re: float = rho * v * D / mu                         # dimensionless

    # --- Flow-regime classification ---
    if re < _RE_LAMINAR_MAX:
        regime = "laminar"
    elif re < _RE_TURBULENT_MIN:
        regime = "transitional"
    elif re < _RE_FULLY_TURBULENT:
        regime = "turbulent"
    else:
        regime = "fully_turbulent"

    # --- Dittus-Boelter applicability ---
    db_applicable: bool = re >= _RE_FULLY_TURBULENT

    # --- Minimum flow rate for Re = 10 000 ---
    # Re_target = ρ · v_min · D / μ  →  v_min = Re_target · μ / (ρ · D)
    # Q_min = v_min · A = Re_target · μ · A / (ρ · D)
    Q_min_m3_s: float = _RE_FULLY_TURBULENT * mu * A / (rho * D)
    Q_min_L_per_min: float = Q_min_m3_s * 60_000.0      # L/min

    return TurbulentReCheckReport(
        reynolds_number=round(re, 4),
        flow_regime=regime,
        velocity_m_per_s=round(v, 6),
        recommended_min_flow_rate_L_per_min=round(Q_min_L_per_min, 6),
        dittus_boelter_applicable=db_applicable,
    )
