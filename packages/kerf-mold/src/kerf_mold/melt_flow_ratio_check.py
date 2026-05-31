"""
kerf_mold.melt_flow_ratio_check
================================
Injection-speed envelope from MFR/MVR, wall thickness, and gate type.

Theory — Beaumont 2007 §4 + Menges 2001 §6.2 + ASTM D1238
-----------------------------------------------------------
The Melt Flow Rate (MFR, g/10 min) or Melt Volume Rate (MVR, cm³/10 min) is
the standardised measure of a polymer's flow under a controlled load and
temperature (ASTM D1238 / ISO 1133).  It is inversely proportional to melt
viscosity: a low MFR indicates a high-viscosity, sluggish melt; a high MFR
indicates a low-viscosity, free-flowing melt.

Injection speed selection (Menges 2001 §6.2; Beaumont 2007 §4.3):
----------------------------------------------------------------------
  1. Jetting (Menges 2001 §6.2.3, Beaumont 2007 §4.4):
     Jetting occurs when the melt enters the cavity as a free jet rather than
     spreading as a fountain flow.  It is driven by excess injection speed
     relative to the gate cross-section.  High-MFR materials (low viscosity)
     are more susceptible to jetting at very high speeds because the reduced
     wall friction allows the jet to persist.  For edge and pin gates (small
     cross-section), a lower minimum speed is used to establish fountain flow
     before the melt reaches the far wall.  Fan and film gates spread the flow
     and greatly reduce jetting risk.

  2. Sink marks (Beaumont 2007 §4.6; Menges 2001 §6.2.5):
     Sink marks arise from insufficient packing of thick sections during
     solidification.  They are primarily a function of wall thickness (> 4 mm
     nominated by Beaumont 2007 §4.6 Table 4.5 as elevated risk) and of
     insufficient hold pressure/time.  Injection speed itself has a secondary
     effect: too slow a fill speed allows premature gate freeze-off before
     packing is complete, exacerbating sinks.

  3. Gate freeze-off (Menges 2001 §6.2.4; Beaumont 2007 §4.5):
     Gate freeze-off terminates packing prematurely.  It is inversely related
     to MFR: viscous low-MFR melts require higher injection pressure and
     therefore leave more residual stress at the gate; the gate freeze window
     is shorter because heat transfer is slower at high viscosity.  High-MFR
     materials freeze more slowly in relative terms and allow a wider packing
     window — gate-freeze risk is therefore lower for high-MFR polymers.

Speed envelope heuristic (Beaumont 2007 §4.3 guidance; Menges 2001 §6.2):
---------------------------------------------------------------------------
  MFR classification and baseline speed window:
    low_MFR_<5         :  5 –  25 mm/s  (viscous, thick-wall tendency)
    medium_MFR_5-25    : 25 –  75 mm/s  (standard engineering grades)
    high_MFR_25-100    : 50 – 150 mm/s  (thin-wall, free-flow grades)
    super_high_MFR_>100: 80 – 200 mm/s  (ultra-thin wall, LCP/PP grades)

  Wall thickness adjustment (Beaumont 2007 §4.3 Table 4.1):
    Wall < 1.5 mm → scale upper bound up by 30 % (faster fill needed to
      avoid premature freeze-off and short-shots)
    Wall 1.5–3 mm → baseline envelope (no adjustment)
    Wall 3–4 mm   → scale lower bound down by 20 % (can fill more slowly)
    Wall > 4 mm   → scale both bounds down by 25 % (thick walls; slow fill
      to avoid jetting and excessive shear heating)

  Gate type adjustment (Beaumont 2007 §7; Menges 2001 §6.6):
    pin_gate / edge_gate   → tight tolerance; baseline; jetting risk applies
    fan_gate / film_gate   → wide land distributes flow; upper bound +20 %
    hot_tip / hot_runner   → direct injection into cavity; wider speed window
    submarine_gate         → shear-sensitive; lower bound +10 %
    sprue_gate             → large cross-section; lower jetting risk; baseline

Risk assessment:
  - gate_freeze_risk: inversely with MFR (low_MFR → high; high_MFR → low)
  - jetting_risk: high for pin/edge gates at high speed + high MFR;
    mitigated by fan/film gates and appropriate slower minimum speed
  - sink_mark_risk: high for wall > 4 mm (Beaumont 2007 §4.6 Table 4.5);
    medium for 2.5–4 mm; low for < 2.5 mm

Honest caveats
--------------
These speed windows are FIRST-APPROXIMATION heuristics calibrated against
Beaumont 2007 §4 and Menges 2001 §6.2 typical-process tables.  Real injection
speed is determined by:
  • Actual melt viscosity curve (shear-rate-dependent) — not just MFR
  • Part geometry: projected area, flow length, number of gates
  • Tool steel / gate land geometry and surface finish
  • Melt and mold temperature interaction
  • Machine hydraulic response and screw check-ring closing characteristics
  • Actual gate size (land length × width or diameter)
Validate the recommended window on-tool via a DOE (Design of Experiments)
short-shot series and cavity-pressure measurement.  MFR is a single-point
viscosity surrogate (ASTM D1238 / ISO 1133 at one shear rate); it does not
capture the full shear-thinning curve required for precise simulation.

References
----------
Beaumont J.P. "Runner and Gating Design Handbook", 2nd ed., Hanser 2007,
  §4 — Melt flow and injection speed; §7 — Gate design.
Menges G., Michaeli W., Mohren P. "How to Make Injection Molds", 3rd ed.,
  Hanser 2001, §6.2 — Injection conditions.
ASTM International. ASTM D1238-23 "Standard Test Method for Melt Flow Rates
  of Thermoplastics by Extrusion Plastometer." West Conshohocken, PA, 2023.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple

# ---------------------------------------------------------------------------
# MFR classification boundaries (ASTM D1238 test conditions vary; these are
# MFR in g/10 min at standard condition for the polymer grade as reported
# on the data sheet — Beaumont 2007 §4 Table 4.3)
# ---------------------------------------------------------------------------

_MFR_LOW_MAX: float = 5.0        # < 5 g/10 min → low MFR
_MFR_MEDIUM_MAX: float = 25.0    # 5–25 g/10 min → medium MFR
_MFR_HIGH_MAX: float = 100.0     # 25–100 g/10 min → high MFR
                                  # > 100 g/10 min → super high MFR

# ---------------------------------------------------------------------------
# Baseline speed windows [mm/s] per MFR classification
# (Beaumont 2007 §4.3; Menges 2001 §6.2 — representative rule)
# ---------------------------------------------------------------------------

_BASELINE_SPEEDS: dict[str, Tuple[float, float]] = {
    "low_MFR_<5":          (5.0,   25.0),
    "medium_MFR_5-25":     (25.0,  75.0),
    "high_MFR_25-100":     (50.0, 150.0),
    "super_high_MFR_>100": (80.0, 200.0),
}

# ---------------------------------------------------------------------------
# Gate types — grouped by flow behaviour
# (Beaumont 2007 §7; Menges 2001 §6.6)
# ---------------------------------------------------------------------------

# Supported gate_type strings (case-insensitive, stripped)
_GATE_SPEED_SCALE: dict[str, Tuple[float, float]] = {
    # (lower_bound_factor, upper_bound_factor)
    "pin_gate":       (1.0, 1.0),
    "edge_gate":      (1.0, 1.0),
    "fan_gate":       (1.0, 1.2),   # wide land distributes flow, upper +20 %
    "film_gate":      (1.0, 1.2),
    "hot_tip":        (0.9, 1.1),   # hot runner; slightly wider window
    "hot_runner":     (0.9, 1.1),
    "submarine_gate": (1.1, 1.0),   # shear-sensitive; lower bound +10 %
    "sprue_gate":     (1.0, 1.0),
    "tab_gate":       (1.0, 1.05),
    "diaphragm_gate": (0.9, 1.0),
}

_GATE_FALLBACK_SCALE: Tuple[float, float] = (1.0, 1.0)

# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class MeltFlowSpec:
    """Input specification for the melt-flow-ratio injection-speed check.

    Attributes
    ----------
    polymer_grade : str
        Polymer commercial grade name (e.g., 'PC', 'PP-H', 'ABS').
        Used for reporting only; MFR is provided separately via ASTM D1238.
    mfr_g_per_10min : float
        Melt Flow Rate measured per ASTM D1238 (or ISO 1133) at the standard
        test condition for the polymer, in g/10 min.  Must be > 0.
        Typical ranges: HDPE pipe 0.3, ABS 10-30, PP injection 12-40,
        PC 4-22, nylon PA66 13-60, TPE 1-60.
    wall_thickness_mm : float
        Nominal wall thickness of the part [mm].  Must be > 0.
        Drives the wall-thickness adjustment and sink-mark risk.
    gate_type : str
        Gate geometry/type.  Supported values (case-insensitive):
        'pin_gate', 'edge_gate', 'fan_gate', 'film_gate',
        'hot_tip', 'hot_runner', 'submarine_gate', 'sprue_gate',
        'tab_gate', 'diaphragm_gate'.
        Unknown types use baseline scale factors (no adjustment, with caveat).
    melt_temp_C : float
        Melt temperature at the nozzle [deg C].  Must be > 0.
        Used for reporting and honest caveat context; not in the speed
        envelope calculation (temperature interacts with MFR non-linearly
        and requires the full viscosity curve).
    mold_temp_C : float
        Mold (coolant-side) temperature [deg C].  Must be >= 0.
        Used for reporting context; affects actual freeze-off timing
        but is folded into the qualitative risk only.
    """

    polymer_grade: str
    mfr_g_per_10min: float         # ASTM D1238; g/10 min; > 0
    wall_thickness_mm: float       # mm; > 0
    gate_type: str
    melt_temp_C: float             # deg C; > 0
    mold_temp_C: float             # deg C; >= 0

    def __post_init__(self) -> None:
        if self.mfr_g_per_10min <= 0.0:
            raise ValueError(
                f"mfr_g_per_10min must be > 0, got {self.mfr_g_per_10min}"
            )
        if self.wall_thickness_mm <= 0.0:
            raise ValueError(
                f"wall_thickness_mm must be > 0, got {self.wall_thickness_mm}"
            )
        if self.melt_temp_C <= 0.0:
            raise ValueError(
                f"melt_temp_C must be > 0, got {self.melt_temp_C}"
            )
        if self.mold_temp_C < 0.0:
            raise ValueError(
                f"mold_temp_C must be >= 0, got {self.mold_temp_C}"
            )


@dataclass
class MeltFlowRatioReport:
    """Output of check_melt_flow_ratio.

    Attributes
    ----------
    mfr_classification : str
        One of: 'low_MFR_<5' | 'medium_MFR_5-25' | 'high_MFR_25-100' |
        'super_high_MFR_>100'.
    recommended_injection_speed_mm_per_s : tuple[float, float]
        Recommended injection speed window (min, max) in mm/s.
        Based on MFR classification, wall thickness, and gate type.
        (Beaumont 2007 §4.3; Menges 2001 §6.2)
    gate_freeze_risk : str
        'low' | 'medium' | 'high'
        Inversely related to MFR: low-MFR viscous melts have higher gate-
        freeze risk under normal packing conditions.
    jetting_risk : str
        'low' | 'medium' | 'high'
        Risk of the melt entering the cavity as a free jet rather than
        fountain flow.  High for pin/edge gates with high-MFR materials
        at high injection speed.
    sink_mark_risk : str
        'low' | 'medium' | 'high'
        Primarily driven by wall thickness (Beaumont 2007 §4.6 Table 4.5):
        high for wall > 4 mm, medium for 2.5-4 mm, low for < 2.5 mm.
    honest_caveat : str
        Plain-language description of model limitations and what validation
        is required before production.
    """

    mfr_classification: str
    recommended_injection_speed_mm_per_s: Tuple[float, float]
    gate_freeze_risk: str
    jetting_risk: str
    sink_mark_risk: str
    honest_caveat: str


# ---------------------------------------------------------------------------
# Caveat template
# ---------------------------------------------------------------------------

_HONEST_CAVEAT = (
    "Heuristic injection-speed envelope derived from Beaumont 2007 §4.3 "
    "(Runner and Gating Design Handbook) and Menges 2001 §6.2 "
    "(How to Make Injection Molds). "
    "MFR (ASTM D1238) is a single-point viscosity surrogate at one shear rate "
    "and temperature; it does not capture the full shear-thinning curve required "
    "for precise process optimisation. "
    "Actual optimum injection speed depends on: real melt viscosity curve, "
    "projected cavity area, flow length, number of gates, gate geometry, "
    "mold steel surface finish, machine hydraulic response, and screw/check-ring "
    "characteristics. "
    "Validate these speed limits on-tool via a short-shot DOE series with cavity "
    "pressure measurement before locking process parameters. "
    "Speed window uncertainty is typically +-20 % of the stated envelope."
)


# ---------------------------------------------------------------------------
# Classification helpers
# ---------------------------------------------------------------------------

def _classify_mfr(mfr: float) -> str:
    """Classify MFR into four bands.

    Based on Beaumont 2007 §4 Table 4.3 and Menges 2001 §6.2.

    Parameters
    ----------
    mfr : float
        Melt Flow Rate in g/10 min (ASTM D1238).

    Returns
    -------
    str
        One of the four MFR classification strings.
    """
    if mfr < _MFR_LOW_MAX:
        return "low_MFR_<5"
    elif mfr < _MFR_MEDIUM_MAX:
        return "medium_MFR_5-25"
    elif mfr < _MFR_HIGH_MAX:
        return "high_MFR_25-100"
    else:
        return "super_high_MFR_>100"


def _wall_speed_adjustment(wall_mm: float) -> Tuple[float, float]:
    """Return (lower_factor, upper_factor) for wall thickness.

    Based on Beaumont 2007 §4.3 Table 4.1.

    Parameters
    ----------
    wall_mm : float
        Wall thickness in mm.

    Returns
    -------
    tuple[float, float]
        (lower_bound_scale, upper_bound_scale)
    """
    if wall_mm < 1.5:
        # Very thin wall: need faster fill to avoid premature freeze-off
        # Beaumont 2007 §4.3: upper bound +30 %; lower bound unchanged
        return (1.0, 1.3)
    elif wall_mm <= 3.0:
        # Standard range: no adjustment
        return (1.0, 1.0)
    elif wall_mm <= 4.0:
        # Moderately thick: can fill more slowly; lower bound -20 %
        return (0.8, 1.0)
    else:
        # Thick section (> 4 mm): slow fill to avoid jetting and shear heat
        # Beaumont 2007 §4.6: both bounds -25 %
        return (0.75, 0.75)


def _gate_freeze_risk(mfr_class: str) -> str:
    """Gate-freeze risk is inversely related to MFR.

    Low MFR → high-viscosity melt → limited packing window → higher gate-
    freeze risk.  High MFR → lower viscosity → wider packing window.

    Menges 2001 §6.2.4; Beaumont 2007 §4.5.

    Parameters
    ----------
    mfr_class : str
        MFR classification string.

    Returns
    -------
    str
        'low' | 'medium' | 'high'
    """
    return {
        "low_MFR_<5":          "high",
        "medium_MFR_5-25":     "medium",
        "high_MFR_25-100":     "low",
        "super_high_MFR_>100": "low",
    }[mfr_class]


def _jetting_risk(mfr_class: str, gate_type_key: str, wall_mm: float) -> str:
    """Assess jetting risk.

    Jetting is promoted by:
    - High MFR (low viscosity): free jet persists without wall friction arrest
    - Small gate cross-section (pin/edge gate): thin jet stream
    - Thin walls + high speed: wall friction is insufficient to deflect jet

    Beaumont 2007 §4.4; Menges 2001 §6.2.3.

    Parameters
    ----------
    mfr_class : str
        MFR classification string.
    gate_type_key : str
        Normalised gate type key.
    wall_mm : float
        Wall thickness in mm.

    Returns
    -------
    str
        'low' | 'medium' | 'high'
    """
    # Gate types that spread flow and resist jetting
    low_jet_gates = {"fan_gate", "film_gate", "diaphragm_gate"}
    # Gate types with small cross-section and high jetting susceptibility
    high_jet_gates = {"pin_gate", "edge_gate", "submarine_gate"}

    if gate_type_key in low_jet_gates:
        return "low"

    high_mfr = mfr_class in ("high_MFR_25-100", "super_high_MFR_>100")
    thin_wall = wall_mm < 2.0

    if gate_type_key in high_jet_gates and high_mfr:
        return "high" if thin_wall else "medium"
    elif gate_type_key in high_jet_gates and not high_mfr:
        return "medium"
    else:
        # hot_tip, hot_runner, sprue_gate, tab_gate, unknown
        return "low" if not high_mfr else "medium"


def _sink_mark_risk(wall_mm: float) -> str:
    """Sink-mark risk driven primarily by wall thickness.

    Beaumont 2007 §4.6 Table 4.5; Menges 2001 §6.2.5:
    - Wall > 4 mm → high sink risk (insufficient packing, extended shrinkage)
    - Wall 2.5-4 mm → medium sink risk
    - Wall < 2.5 mm → low sink risk

    Parameters
    ----------
    wall_mm : float
        Wall thickness in mm.

    Returns
    -------
    str
        'low' | 'medium' | 'high'
    """
    if wall_mm > 4.0:
        return "high"
    elif wall_mm >= 2.5:
        return "medium"
    else:
        return "low"


# ---------------------------------------------------------------------------
# Main computation
# ---------------------------------------------------------------------------

def check_melt_flow_ratio(spec: MeltFlowSpec) -> MeltFlowRatioReport:
    """Determine the recommended injection-speed envelope from MFR and process parameters.

    Implements the empirical speed-window selection method from:
      Beaumont 2007 §4 (melt flow and injection speed guidelines)
      Menges 2001 §6.2 (injection conditions for polymer processing)

    Parameters
    ----------
    spec : MeltFlowSpec
        Polymer and process specification.

    Returns
    -------
    MeltFlowRatioReport
        Speed envelope, risk classifications, and honest caveat.

    Raises
    ------
    ValueError
        If spec contains out-of-range values (validated in MeltFlowSpec.__post_init__).

    Notes
    -----
    Speed envelope calculation:

    1.  Classify MFR → baseline (v_min, v_max) from _BASELINE_SPEEDS table.
    2.  Apply wall-thickness correction factors (f_lower, f_upper)
        from _wall_speed_adjustment.
    3.  Apply gate-type correction factors (g_lower, g_upper)
        from _GATE_SPEED_SCALE.
    4.  Final speed = (v_min * f_lower * g_lower, v_max * f_upper * g_upper),
        rounded to 1 decimal place; minimum 1.0 mm/s.
    """
    mfr_class = _classify_mfr(spec.mfr_g_per_10min)

    # Baseline speed window
    v_min_base, v_max_base = _BASELINE_SPEEDS[mfr_class]

    # Wall thickness adjustment
    f_lower, f_upper = _wall_speed_adjustment(spec.wall_thickness_mm)

    # Gate type adjustment
    gate_key = spec.gate_type.strip().lower().replace(" ", "_").replace("-", "_")
    g_lower, g_upper = _GATE_SPEED_SCALE.get(gate_key, _GATE_FALLBACK_SCALE)

    # Apply adjustments
    v_min = max(1.0, round(v_min_base * f_lower * g_lower, 1))
    v_max = max(v_min + 1.0, round(v_max_base * f_upper * g_upper, 1))

    # Risk assessments
    freeze_risk = _gate_freeze_risk(mfr_class)
    jet_risk = _jetting_risk(mfr_class, gate_key, spec.wall_thickness_mm)
    sink_risk = _sink_mark_risk(spec.wall_thickness_mm)

    return MeltFlowRatioReport(
        mfr_classification=mfr_class,
        recommended_injection_speed_mm_per_s=(v_min, v_max),
        gate_freeze_risk=freeze_risk,
        jetting_risk=jet_risk,
        sink_mark_risk=sink_risk,
        honest_caveat=_HONEST_CAVEAT,
    )
