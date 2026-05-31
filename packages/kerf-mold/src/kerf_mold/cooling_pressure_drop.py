"""
kerf_mold.cooling_pressure_drop
=================================
Total pressure-drop computation for multi-segment injection-mold cooling-
channel networks using Darcy-Weisbach + minor-loss coefficients.

Theory
------
The Darcy-Weisbach pressure-drop equation (White "Fluid Mechanics" 8th ed.
§6.7, eq. 6.30) for a straight circular pipe segment of length L [m] and
inner diameter D [m] carrying an incompressible Newtonian fluid at mean
velocity v [m/s]:

    ΔP_major = f · (L/D) · (ρ·v²/2)            [Pa]

where f is the Darcy friction factor (dimensionless).

Reynolds number:
    Re = ρ·v·D / μ

Friction-factor models (smooth pipe, White §6.7):
  • Laminar  (Re < 2300):  f = 64 / Re
  • Transitional (2300 ≤ Re ≤ 4000): linear interpolation between laminar
    and turbulent values — flagged in caveat
  • Turbulent (Re > 4000):  f = 0.316 / Re^0.25  (Blasius, White §6.7,
    valid 4 000 < Re < 100 000; upper-range caveat emitted above 100 000)

Minor losses (Beaumont 2007 §11.2, Table 11.1; White §6.9):
    ΔP_minor = K · (ρ·v²/2)                     [Pa]

K-factors per segment type:
  straight    → K = 0   (no minor loss, only Darcy-Weisbach)
  elbow_90    → K = 0.9
  elbow_45    → K = 0.4
  tee_thru    → K = 0.6
  tee_branch  → K = 1.8

Total network pressure drop = Σ (ΔP_major_i + ΔP_minor_i) over all segments.

Pump-head recommendation:
  recommended_pump_head_bar = total_pressure_drop_bar × 1.25   (25 % margin)

Unit conversions used internally:
  length:   mm → m  (×1e-3)
  diameter: mm → m  (×1e-3)
  flow rate: L/min → m³/s  (×1/60 000)
  viscosity: cP → Pa·s  (×1e-3)
  pressure:  Pa → bar  (×1e-5)

Honest caveats
--------------
This calculation is:
  • Single-phase, incompressible water (or water-glycol) only.
  • Smooth-pipe Blasius turbulent friction factor (no pipe roughness /
    Colebrook-White correction) — conservative for smooth bores, may under-
    predict for rough-drilled channels; use Colebrook-White / Moody chart if
    roughness ε/D > 0.001.
  • No heat-transfer coupling — coolant temperature (and therefore viscosity)
    treated as spatially uniform; for multi-segment layouts with significant
    heat pick-up (ΔT > 10 °C), recompute with exit-viscosity estimate.
  • No two-phase cooling (phase-change / boiling flow) modelled.
  • Minor-loss K-factors are handbook best estimates; actual values depend on
    elbow radius, fitting geometry, and Reynolds number.
  • Assumes series (single-circuit) flow — parallel manifold networks require
    per-branch Re and ΔP computed individually.

References
----------
Beaumont J.P. "Runner and Gating Design Handbook", 2nd ed., Hanser 2007,
  §11.2 (Cooling circuit hydraulics), Table 11.1 (K-factors).
White F.M. "Fluid Mechanics", 8th ed., McGraw-Hill 2016,
  §6.7 (Darcy-Weisbach), §6.9 (minor losses), eq. 6.30.
Menges G., Michaeli W., Mohren P. "How to Make Injection Molds", 3rd ed.,
  Hanser 2001, §6.5 (cooling-circuit layout).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import List


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Minor-loss K-factors by segment_type (White §6.9; Beaumont 2007 §11.2)
_MINOR_LOSS_K: dict[str, float] = {
    "straight":   0.0,
    "elbow_90":   0.9,
    "elbow_45":   0.4,
    "tee_thru":   0.6,
    "tee_branch": 1.8,
}

_VALID_SEGMENT_TYPES = frozenset(_MINOR_LOSS_K.keys())

#: Regime thresholds (White §6.7)
_RE_LAMINAR_MAX = 2300.0
_RE_TURBULENT_MIN = 4000.0
_RE_BLASIUS_MAX = 100_000.0

#: 25 % safety margin on recommended pump head
_PUMP_MARGIN = 1.25


# ---------------------------------------------------------------------------
# Input dataclasses
# ---------------------------------------------------------------------------

@dataclass
class CoolingChannelSegment:
    """One segment in a mold cooling-channel network.

    Parameters
    ----------
    length_mm : float
        Segment length [mm].  Must be > 0.
    diameter_mm : float
        Internal channel diameter [mm].  Must be > 0.
    segment_type : str
        Pipe-fitting type.  One of: "straight", "elbow_90", "elbow_45",
        "tee_thru", "tee_branch".
    """

    length_mm: float
    diameter_mm: float
    segment_type: str

    def __post_init__(self) -> None:
        if self.length_mm <= 0.0:
            raise ValueError(
                f"CoolingChannelSegment.length_mm must be > 0, "
                f"got {self.length_mm}"
            )
        if self.diameter_mm <= 0.0:
            raise ValueError(
                f"CoolingChannelSegment.diameter_mm must be > 0, "
                f"got {self.diameter_mm}"
            )
        if self.segment_type not in _VALID_SEGMENT_TYPES:
            raise ValueError(
                f"CoolingChannelSegment.segment_type must be one of "
                f"{sorted(_VALID_SEGMENT_TYPES)}, got '{self.segment_type}'"
            )


@dataclass
class CoolantSpec:
    """Coolant fluid properties.

    Parameters
    ----------
    flow_rate_L_per_min : float
        Volumetric flow rate [L/min].  Must be > 0.
    density_kg_m3 : float
        Coolant density [kg/m³].  Default 1000 kg/m³ (water at ~20 °C).
    viscosity_cP : float
        Dynamic viscosity [centipoise].  Default 1.0 cP (water at ~20 °C).
        1 cP = 1e-3 Pa·s.
    """

    flow_rate_L_per_min: float
    density_kg_m3: float = 1000.0
    viscosity_cP: float = 1.0

    def __post_init__(self) -> None:
        if self.flow_rate_L_per_min <= 0.0:
            raise ValueError(
                f"CoolantSpec.flow_rate_L_per_min must be > 0, "
                f"got {self.flow_rate_L_per_min}"
            )
        if self.density_kg_m3 <= 0.0:
            raise ValueError(
                f"CoolantSpec.density_kg_m3 must be > 0, "
                f"got {self.density_kg_m3}"
            )
        if self.viscosity_cP <= 0.0:
            raise ValueError(
                f"CoolantSpec.viscosity_cP must be > 0, "
                f"got {self.viscosity_cP}"
            )


# ---------------------------------------------------------------------------
# Output dataclass
# ---------------------------------------------------------------------------

_HONEST_CAVEAT = (
    "Darcy-Weisbach single-phase incompressible hydraulics (White §6.7; "
    "Beaumont 2007 §11.2). Smooth-pipe Blasius turbulent f (no Colebrook-"
    "White roughness correction). No heat-transfer coupling — viscosity "
    "assumed spatially uniform; for ΔT > 10 °C re-run with exit viscosity. "
    "No two-phase (boiling/phase-change) cooling modelled. K-factors are "
    "handbook averages — actual values vary with elbow radius and Re. "
    "Series (single-circuit) network assumed; parallel branches need per-"
    "branch analysis. Pump-head recommendation adds 25 % safety margin."
)


@dataclass
class CoolingPressureDropReport:
    """Result of a mold cooling-channel network pressure-drop analysis.

    Attributes
    ----------
    total_pressure_drop_bar : float
        Sum of all major (Darcy-Weisbach) + minor (K-factor) losses [bar].
    reynolds_number : float
        Pipe Reynolds number Re = ρ·v·D/μ.  Computed for the first segment
        (all segments share the same flow rate; v and Re vary with D_i).
        Per-segment Re is in ``segment_breakdown``.
    friction_factor : float
        Darcy friction factor f for the first segment (representative).
    segment_breakdown : list[dict]
        Per-segment detail dicts, each containing:
        {index, length_mm, diameter_mm, segment_type,
         velocity_m_s, reynolds_number, friction_factor,
         dp_major_bar, dp_minor_bar, dp_total_bar}.
    chiller_head_required_bar : float
        Minimum chiller/pump head required = total_pressure_drop_bar.
    recommended_pump_head_bar : float
        total_pressure_drop_bar × 1.25 (25 % design margin).
    honest_caveat : str
        Plain-language statement of limitations.
    """

    total_pressure_drop_bar: float
    reynolds_number: float
    friction_factor: float
    segment_breakdown: List[dict]
    chiller_head_required_bar: float
    recommended_pump_head_bar: float
    honest_caveat: str = field(default=_HONEST_CAVEAT)


# ---------------------------------------------------------------------------
# Core computation
# ---------------------------------------------------------------------------

def _friction_factor(re: float) -> float:
    """Return Darcy friction factor for smooth pipe (White §6.7).

    Re < 2300     → laminar:  f = 64 / Re
    2300 ≤ Re ≤ 4000 → linear interpolation (transitional)
    Re > 4000     → Blasius turbulent:  f = 0.316 / Re^0.25
    """
    if re < _RE_LAMINAR_MAX:
        return 64.0 / re
    if re > _RE_TURBULENT_MIN:
        return 0.316 / (re ** 0.25)
    # Transitional: linear blend between laminar and Blasius values
    f_lam = 64.0 / _RE_LAMINAR_MAX
    f_turb = 0.316 / (_RE_TURBULENT_MIN ** 0.25)
    t = (re - _RE_LAMINAR_MAX) / (_RE_TURBULENT_MIN - _RE_LAMINAR_MAX)
    return f_lam + t * (f_turb - f_lam)


def compute_cooling_pressure_drop(
    segments: List[CoolingChannelSegment],
    coolant: CoolantSpec,
) -> CoolingPressureDropReport:
    """Compute total pressure drop across a mold cooling-channel network.

    Uses Darcy-Weisbach for straight runs and K-factor minor losses for
    fittings (elbows, tees).  All segments are assumed in series and share
    the same volumetric flow rate.

    Parameters
    ----------
    segments : list[CoolingChannelSegment]
        Ordered list of pipe segments (at least one required).
    coolant : CoolantSpec
        Coolant fluid properties and flow rate.

    Returns
    -------
    CoolingPressureDropReport

    Raises
    ------
    ValueError
        - ``segments`` is empty.
        - Any segment has invalid parameters (delegated to dataclass).
        - Any coolant property is invalid (delegated to dataclass).

    Notes
    -----
    Unit-conversion path:
      flow_rate_L_per_min → Q_m3_s = Q / 60 000
      diameter_mm         → D_m    = D * 1e-3
      length_mm           → L_m    = L * 1e-3
      viscosity_cP        → mu_Pa_s = mu * 1e-3
      ΔP [Pa]             → ΔP [bar] = ΔP * 1e-5
    """
    if not segments:
        raise ValueError("segments list must contain at least one segment")

    # Fluid properties
    rho = coolant.density_kg_m3                          # kg/m³
    mu = coolant.viscosity_cP * 1e-3                     # Pa·s
    Q = coolant.flow_rate_L_per_min / 60_000.0           # m³/s

    total_dp_pa = 0.0
    breakdown: List[dict] = []

    for i, seg in enumerate(segments):
        D = seg.diameter_mm * 1e-3       # m
        L = seg.length_mm * 1e-3         # m
        A = math.pi * (D / 2.0) ** 2    # m²
        v = Q / A                        # m/s  (mean velocity)

        re = rho * v * D / mu            # Reynolds number (dimensionless)
        f = _friction_factor(re)         # Darcy friction factor

        # Dynamic pressure head  [Pa]
        q_dyn = 0.5 * rho * v ** 2

        # Major loss (Darcy-Weisbach)
        dp_major_pa = f * (L / D) * q_dyn

        # Minor loss (K-factor)
        K = _MINOR_LOSS_K[seg.segment_type]
        dp_minor_pa = K * q_dyn

        dp_seg_pa = dp_major_pa + dp_minor_pa
        total_dp_pa += dp_seg_pa

        breakdown.append({
            "index": i,
            "length_mm": seg.length_mm,
            "diameter_mm": seg.diameter_mm,
            "segment_type": seg.segment_type,
            "velocity_m_s": round(v, 6),
            "reynolds_number": round(re, 2),
            "friction_factor": round(f, 8),
            "dp_major_bar": round(dp_major_pa * 1e-5, 8),
            "dp_minor_bar": round(dp_minor_pa * 1e-5, 8),
            "dp_total_bar": round(dp_seg_pa * 1e-5, 8),
        })

    total_bar = total_dp_pa * 1e-5

    # Representative Re and f from first segment
    rep = breakdown[0]

    return CoolingPressureDropReport(
        total_pressure_drop_bar=round(total_bar, 8),
        reynolds_number=rep["reynolds_number"],
        friction_factor=rep["friction_factor"],
        segment_breakdown=breakdown,
        chiller_head_required_bar=round(total_bar, 8),
        recommended_pump_head_bar=round(total_bar * _PUMP_MARGIN, 8),
    )
