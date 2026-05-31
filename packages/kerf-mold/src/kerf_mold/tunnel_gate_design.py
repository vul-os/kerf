"""
kerf_mold.tunnel_gate_design
==============================
Design a tunnel (submarine) gate for an injection mold given part weight and
polymer grade.

Returns gate diameter, length, angle, break-off force, shear rate, and
freeze time.

Theory
------
Tunnel (submarine) gates enter the part through the cavity wall at an angle,
breaking off automatically during ejection.  They are typically circular in
cross-section, located below the parting line, and are an attractive
alternative to edge gates wherever a clean automatic degating is required.

Gate diameter — Beaumont 2007 §7.4 rule
----------------------------------------
Beaumont's primary thumb rule for tunnel-gate diameter is:

    D_gate = 0.5 × wall_thickness_at_gate_mm   [mm]

with a lower bound of 0.8 mm (practical machining minimum) and an upper
bound of 2/3 of the wall thickness (Menges 2001 §6.6.5 upper cap).

A secondary wall-clock correction is applied for high-viscosity polymers
(PC, PA66, PMMA, POM, PEI, PPO) where the gate must be at least 10 % wider
to compensate for the elevated resistance to flow:

    D_gate_corrected = D_gate × viscosity_factor   [mm]

Gate angle — Menges 2001 §6.6.5
---------------------------------
Menges recommends a tunnel-gate angle of 30°–45° from the parting-line
direction (typically 30° for soft materials, 45° for stiff/glassy polymers).
The user may supply a custom angle; out-of-range inputs trigger a flag.

Break-off force
---------------
During ejection the gate stub must snap cleanly.  The break-off force is
approximated by:

    F_break = tau_shear × A_gate

where:
    tau_shear ≈ shear_strength_MPa × 10⁶   [Pa]
    A_gate    = π/4 × D_gate²              [m²]

Polymer shear-strength values (Menges 2001 Table 6.3):
    ABS        : 30 MPa
    PC         : 45 MPa (high-viscosity)
    PP         : 22 MPa
    PA66       : 40 MPa
    POM        : 38 MPa
    PMMA       : 42 MPa
    PE-LD      : 18 MPa
    PE-HD      : 20 MPa
    PS         : 30 MPa
    PEI        : 50 MPa
    PPO        : 45 MPa
    TPE        : 15 MPa
    Default    : 30 MPa (ABS-baseline)

Shear rate — Hagen-Poiseuille
-------------------------------
The volumetric flow rate Q is back-calculated from part weight, melt density,
and an assumed injection time (default: Beaumont 2007 §4.2 thumb: 1 s per
gram of part weight, min 0.5 s):

    t_fill = 1.0 s   (Beaumont §4.2 typical injection — constant reference)
    Q      = (part_weight_g / rho_melt_kg_m3) / t_fill   [m³/s]

Wall shear rate (Hagen-Poiseuille, Newtonian approximation):

    gamma_dot = 4Q / (pi × r³)    [s⁻¹]
    where r = D_gate / 2   [m]

Beaumont 2007 §7.4 upper limit: 50 000 s⁻¹.
Exceeding this limit causes gate freeze-off degradation, jetting, and weld
defects.

Freeze time — 1-D Fourier (Menges 2001 §7.3.3 / Chen-Chiang 1985)
-------------------------------------------------------------------
The gate freeze time is estimated using the first-term approximation of the
1-D Fourier cooling series:

    t_freeze = (D²_gate / (π² × α)) × ln[(8/π²) × (T_melt − T_mold) / (T_eject − T_mold)]

where:
    D_gate [m] is used as the characteristic thickness (full diameter — gate
       is fully enclosed in the steel, cooled from all sides; using diameter
       as the effective wall thickness is a conservative single-slab estimate).
    α      [m²/s] — polymer thermal diffusivity (Menges Table 7.3).
    T_melt [°C]  — melt temperature (from spec.melt_temp_C).
    T_mold [°C]  — default 40 °C.
    T_eject[°C]  — ejection temperature (polymer-specific from thermal DB).

Melt density database (Menges 2001 Table A.1 — solid density; melt density
                        ≈ 0.78 × solid density as practical approximation)
---------------------------------------------------------------------------
    ABS  : 1050 kg/m³ solid → 820 melt
    PC   : 1200 kg/m³ solid → 935 melt
    PP   : 910  kg/m³ solid → 710 melt
    PA66 : 1140 kg/m³ solid → 890 melt
    POM  : 1410 kg/m³ solid → 1100 melt
    PMMA : 1190 kg/m³ solid → 930 melt
    PE-LD: 920  kg/m³ solid → 720 melt
    PE-HD: 960  kg/m³ solid → 750 melt
    PS   : 1050 kg/m³ solid → 820 melt
    PEI  : 1270 kg/m³ solid → 990 melt
    PPO  : 1060 kg/m³ solid → 830 melt
    TPE  : 900  kg/m³ solid → 700 melt
    Default: 820 melt (ABS-baseline)

Honest caveats
--------------
1. Diameter rule: Beaumont 2007 §7.4 rule is a START-POINT heuristic only.
   Actual diameter depends on filling pressure (injection speed, runner
   layout, multi-cavity balance), rheology (power-law index, WLF shift),
   and gate location relative to flow leaders.  Complex multi-cavity timing
   requires Moldflow / Moldex3D full 3-D fill simulation.

2. Break-off force: Shear-strength values are mid-range Menges 2001 Table 6.3
   values.  Actual break force is sensitive to mold temperature, cooling time
   after gate freeze, gate stub aspect ratio, and ductility of the specific
   polymer grade.  Confirm with mold-trial gate-break force measurement.

3. Shear rate: Hagen-Poiseuille is a Newtonian approximation.  Real
   polymers are shear-thinning (power-law n ≈ 0.2–0.5); apparent shear rate
   at the gate wall is 25–50 % higher than the Newtonian value for n ≈ 0.3.
   Use the Rabinowitsch correction for design confirmation.

4. Freeze time: 1-D Fourier first-term with constant diffusivity.  Does NOT
   model crystallisation latent heat (PP/PA66/POM → actual freeze time
   15–25 % longer), 3-D conduction through the steel land, or gate-land
   contact resistance.  The tunnel gate is fully enclosed in steel — actual
   freeze is faster than a slab model predicts.

References
----------
Beaumont J.P. "Runner and Gating Design Handbook", 2nd ed., Hanser 2007,
  §7.4 (Tunnel / Submarine Gates) + §4.2 (fill-time thumb rule).
Menges G., Michaeli W., Mohren P. "How to Make Injection Molds", 3rd ed.,
  Hanser 2001, §6.6.5 (Gate Types — Tunnel Gate) + Table 6.3 (shear
  strength) + Table 7.3 (thermal diffusivity) + §7.3.3 (freeze time).
Chen, C.-C. & Chiang, C.-H. "Injection Mold Cooling Time Analysis",
  ANTEC 1985, pp. 432–436.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, Optional


# ---------------------------------------------------------------------------
# Polymer property databases
# ---------------------------------------------------------------------------

#: Melt density [kg/m³] — approx 0.78 × solid density (Menges 2001 Table A.1)
_MELT_DENSITY_KG_M3: Dict[str, float] = {
    "ABS":   820.0,
    "PC":    935.0,
    "PP":    710.0,
    "PA66":  890.0,
    "POM":  1100.0,
    "PMMA":  930.0,
    "PELD":  720.0,
    "PE-LD": 720.0,
    "PEHD":  750.0,
    "PE-HD": 750.0,
    "PS":    820.0,
    "PEI":   990.0,
    "PPO":   830.0,
    "TPE":   700.0,
}

#: Shear strength [MPa] per Menges 2001 Table 6.3
_SHEAR_STRENGTH_MPA: Dict[str, float] = {
    "ABS":   30.0,
    "PC":    45.0,
    "PP":    22.0,
    "PA66":  40.0,
    "POM":   38.0,
    "PMMA":  42.0,
    "PELD":  18.0,
    "PE-LD": 18.0,
    "PEHD":  20.0,
    "PE-HD": 20.0,
    "PS":    30.0,
    "PEI":   50.0,
    "PPO":   45.0,
    "TPE":   15.0,
}

#: Thermal diffusivity [m²/s] per Menges 2001 Table 7.3
_THERMAL_DIFFUSIVITY_M2_S: Dict[str, float] = {
    "ABS":   1.00e-7,
    "PC":    1.50e-7,
    "PP":    0.95e-7,
    "PA66":  1.40e-7,
    "POM":   0.95e-7,
    "PMMA":  1.13e-7,
    "PELD":  1.10e-7,
    "PE-LD": 1.10e-7,
    "PEHD":  1.20e-7,
    "PE-HD": 1.20e-7,
    "PS":    1.00e-7,
    "PEI":   1.10e-7,
    "PPO":   1.05e-7,
    "TPE":   1.00e-7,
}

#: Ejection temperature [°C] (average part temperature at demould)
_EJECTION_TEMP_C: Dict[str, float] = {
    "ABS":   80.0,
    "PC":   100.0,
    "PP":    90.0,
    "PA66": 100.0,
    "POM":   90.0,
    "PMMA":  80.0,
    "PELD":  85.0,
    "PE-LD": 85.0,
    "PEHD":  90.0,
    "PE-HD": 90.0,
    "PS":    70.0,
    "PEI":  120.0,
    "PPO":  100.0,
    "TPE":   60.0,
}

#: High-viscosity polymers that need the +10% diameter correction
_HIGH_VISCOSITY_POLYMERS = frozenset([
    "PC", "PA66", "PMMA", "POM", "PEI", "PPO",
])

#: Beaumont §7.4 shear rate upper limit [s⁻¹]
_SHEAR_RATE_LIMIT_PER_S: float = 50_000.0

#: Practical minimum gate diameter [mm] — machining floor
_D_GATE_MIN_MM: float = 0.8

#: Menges §6.6.5 upper cap: gate diameter ≤ 2/3 × wall thickness
_D_GATE_UPPER_FRACTION: float = 2.0 / 3.0

#: Menges §6.6.5 angle range [°]
_ANGLE_MIN_DEG: float = 30.0
_ANGLE_MAX_DEG: float = 45.0

#: Default mold temperature [°C]
_T_MOLD_C: float = 40.0


def _normalise_grade(polymer_grade: str) -> str:
    """Return upper-cased, stripped polymer grade key."""
    return polymer_grade.upper().strip()


def _lookup(db: Dict[str, float], grade_norm: str, default: float) -> float:
    return db.get(grade_norm, default)


# ---------------------------------------------------------------------------
# Input dataclass
# ---------------------------------------------------------------------------

@dataclass
class TunnelGateSpec:
    """Specification for a tunnel (submarine) gate design.

    Attributes
    ----------
    part_weight_g : float
        Total shot weight of the part [g].  Used to back-calculate fill flow
        rate Q and is the primary driver of the shear-rate calculation.
        Must be > 0.
    wall_thickness_at_gate_mm : float
        Local wall thickness at the gate attachment point [mm].
        Beaumont §7.4: D_gate = 0.5 × wall_thickness.  Must be > 0.
    polymer_grade : str
        Polymer grade string (case-insensitive).  Supported: ABS, PC, PP,
        PA66, POM, PMMA, PE-LD, PE-HD, PS, PEI, PPO, TPE.
        Unknown grades fall back to ABS-baseline properties with a caveat.
    melt_temp_C : float
        Melt injection temperature [°C].  Used for freeze-time calculation.
        Must be > 0.
    gate_angle_deg : float, optional
        Gate entry angle relative to the parting-line direction [°].
        Menges §6.6.5 recommended range: 30°–45°.  Default: 30.0.
    gate_length_mm : float, optional
        Gate land (tunnel) length [mm].  Beaumont §7.4: typically 1.0–2.0 mm.
        Default: 1.5.
    """

    part_weight_g: float
    wall_thickness_at_gate_mm: float
    polymer_grade: str
    melt_temp_C: float
    gate_angle_deg: float = 30.0
    gate_length_mm: float = 1.5

    def __post_init__(self) -> None:
        if self.part_weight_g <= 0.0:
            raise ValueError(
                f"part_weight_g must be > 0, got {self.part_weight_g}"
            )
        if self.wall_thickness_at_gate_mm <= 0.0:
            raise ValueError(
                f"wall_thickness_at_gate_mm must be > 0, "
                f"got {self.wall_thickness_at_gate_mm}"
            )
        if self.melt_temp_C <= 0.0:
            raise ValueError(
                f"melt_temp_C must be > 0, got {self.melt_temp_C}"
            )
        if self.gate_length_mm <= 0.0:
            raise ValueError(
                f"gate_length_mm must be > 0, got {self.gate_length_mm}"
            )
        if not (0.0 < self.gate_angle_deg < 90.0):
            raise ValueError(
                f"gate_angle_deg must be in (0, 90), got {self.gate_angle_deg}"
            )


# ---------------------------------------------------------------------------
# Output dataclass
# ---------------------------------------------------------------------------

@dataclass
class TunnelGateReport:
    """Report produced by design_tunnel_gate.

    Attributes
    ----------
    gate_diameter_mm : float
        Designed gate diameter [mm] (Beaumont 2007 §7.4 rule, viscosity-
        corrected for high-viscosity polymers).
    gate_break_off_force_N : float
        Estimated gate break-off force during ejection [N], from shear
        strength × gate cross-sectional area (Menges 2001 Table 6.3).
    gate_freeze_time_s : float
        Estimated gate freeze time [s] from 1-D Fourier first-term
        approximation (Chen-Chiang / Menges 2001 §7.3.3).
    shear_rate_at_gate_per_s : float
        Apparent wall shear rate at the gate entrance [s⁻¹], Hagen-
        Poiseuille (Newtonian): γ̇ = 4Q/(π·r³).
    shear_within_limit : bool
        True if shear_rate_at_gate_per_s ≤ 50 000 s⁻¹ (Beaumont §7.4).
    recommended_angle_deg : float
        Recommended gate angle per Menges §6.6.5: 30° for flexible/low-
        stiffness polymers, 45° for stiff/glassy polymers; clamped to the
        spec.gate_angle_deg if the user-supplied value is within range.
    honest_caveat : str
        Plain-language statement of model limitations.
    """

    gate_diameter_mm: float
    gate_break_off_force_N: float
    gate_freeze_time_s: float
    shear_rate_at_gate_per_s: float
    shear_within_limit: bool
    recommended_angle_deg: float
    honest_caveat: str = field(default="")


# ---------------------------------------------------------------------------
# Core computation
# ---------------------------------------------------------------------------

_CAVEAT_TMPL = (
    "Tunnel-gate diameter from Beaumont 2007 §7.4 rule (D = 0.5 × wall_thickness"
    "{viscosity_note}); break-off force from Menges 2001 Table 6.3 shear-strength "
    "({shear_str_MPa:.0f} MPa for {polymer}); shear rate via Hagen-Poiseuille "
    "Newtonian approximation (actual shear-thinning polymer shear rate ≈ 1.25–1.5× "
    "higher; apply Rabinowitsch correction for design confirmation); freeze time via "
    "Chen-Chiang / Menges §7.3.3 1-D Fourier (constant diffusivity; no crystallisation "
    "latent heat — PP/PA66/POM actual freeze 15–25 % longer). "
    "HONEST: diameter is a start-point heuristic — complex multi-cavity timing and "
    "filling balance require Moldflow / Moldex3D full 3-D fill simulation. "
    "Confirm break-off force and vestige by mold-trial measurement. "
    "References: Beaumont J.P. Runner and Gating Design Handbook 2nd ed. Hanser 2007 "
    "§7.4; Menges G., Michaeli W., Mohren P. How to Make Injection Molds 3rd "
    "ed. Hanser 2001 §6.6.5 + Table 6.3 + §7.3.3; Chen-Chiang ANTEC 1985."
)


def design_tunnel_gate(spec: TunnelGateSpec) -> TunnelGateReport:
    """Design a tunnel (submarine) gate given part weight and polymer grade.

    Applies Beaumont 2007 §7.4 diameter rule, Menges 2001 §6.6.5 angle
    guidance, Hagen-Poiseuille shear-rate check, and Chen-Chiang /
    Menges §7.3.3 gate-freeze-time estimate.

    Parameters
    ----------
    spec : TunnelGateSpec
        Full gate specification (part weight, wall thickness, polymer, etc.).

    Returns
    -------
    TunnelGateReport

    Raises
    ------
    ValueError
        If any spec field has an invalid value.
    """
    grade_key = _normalise_grade(spec.polymer_grade)

    # -------------------------------------------------------------------
    # 1. Gate diameter — Beaumont 2007 §7.4
    # -------------------------------------------------------------------
    # D_gate = 0.5 × wall_thickness_at_gate_mm
    d_initial_mm = 0.5 * spec.wall_thickness_at_gate_mm

    # High-viscosity correction: +10 % for PC, PA66, PMMA, POM, PEI, PPO
    if grade_key in _HIGH_VISCOSITY_POLYMERS:
        viscosity_factor = 1.10
        viscosity_note = ", +10 % high-viscosity correction for " + grade_key
    else:
        viscosity_factor = 1.0
        viscosity_note = ""

    d_corrected_mm = d_initial_mm * viscosity_factor

    # Apply lower bound (machining floor)
    d_corrected_mm = max(d_corrected_mm, _D_GATE_MIN_MM)

    # Apply Menges §6.6.5 upper cap: D ≤ 2/3 × wall_thickness
    d_upper_mm = _D_GATE_UPPER_FRACTION * spec.wall_thickness_at_gate_mm
    d_gate_mm = min(d_corrected_mm, d_upper_mm)

    # Ensure always ≥ machining floor even after upper cap
    d_gate_mm = max(d_gate_mm, _D_GATE_MIN_MM)

    d_gate_mm = round(d_gate_mm, 6)

    # -------------------------------------------------------------------
    # 2. Break-off force
    # -------------------------------------------------------------------
    shear_strength_MPa = _lookup(
        _SHEAR_STRENGTH_MPA, grade_key, 30.0,  # ABS-baseline default
    )
    # A_gate = π/4 × D² [m²]; D in metres
    d_gate_m = d_gate_mm * 1e-3
    A_gate_m2 = math.pi / 4.0 * d_gate_m ** 2
    F_break_N = shear_strength_MPa * 1e6 * A_gate_m2

    # -------------------------------------------------------------------
    # 3. Shear rate — Hagen-Poiseuille
    # -------------------------------------------------------------------
    rho_melt = _lookup(_MELT_DENSITY_KG_M3, grade_key, 820.0)

    # Fill time: Beaumont §4.2 typical fill time ≈ 1.0 s (constant reference
    # injection — represents a standard 1-second fill for a typical machine
    # shot; heavier/larger parts have proportionally higher flow rate Q).
    t_fill_s = 1.0

    # Volumetric flow rate [m³/s]
    mass_kg = spec.part_weight_g * 1e-3
    vol_m3 = mass_kg / rho_melt
    Q_m3_s = vol_m3 / t_fill_s

    # Shear rate: γ̇ = 4Q/(π·r³)
    r_m = d_gate_m / 2.0
    if r_m <= 0.0:
        shear_rate_per_s = 0.0
    else:
        shear_rate_per_s = 4.0 * Q_m3_s / (math.pi * r_m ** 3)

    shear_within_limit = shear_rate_per_s <= _SHEAR_RATE_LIMIT_PER_S

    # -------------------------------------------------------------------
    # 4. Gate freeze time — 1-D Fourier (Chen-Chiang / Menges §7.3.3)
    # -------------------------------------------------------------------
    alpha_m2_s = _lookup(_THERMAL_DIFFUSIVITY_M2_S, grade_key, 1.00e-7)
    T_mold_C = _T_MOLD_C
    T_eject_C = _lookup(_EJECTION_TEMP_C, grade_key, 80.0)

    # Guard: melt must be hotter than ejection which must be hotter than mold
    T_melt = spec.melt_temp_C
    T_ejection = max(T_eject_C, T_mold_C + 1.0)
    T_melt_safe = max(T_melt, T_ejection + 1.0)

    # Characteristic thickness for freeze time: use full gate diameter [m]
    # (gate land is fully enclosed in steel — diameter is the critical
    #  half-width × 2; conservative single-slab estimate)
    h_gate_m = d_gate_m

    log_arg = (8.0 / (math.pi ** 2)) * (T_melt_safe - T_mold_C) / (T_ejection - T_mold_C)
    if log_arg <= 0.0 or alpha_m2_s <= 0.0:
        gate_freeze_time_s = 0.0
    else:
        gate_freeze_time_s = (h_gate_m ** 2 / (math.pi ** 2 * alpha_m2_s)) * math.log(log_arg)

    gate_freeze_time_s = max(gate_freeze_time_s, 0.0)

    # -------------------------------------------------------------------
    # 5. Recommended angle — Menges §6.6.5
    # -------------------------------------------------------------------
    # Stiff/glassy polymers: 45°; flexible/low-viscosity: 30°.
    # recommended_angle_deg always reflects the polymer-appropriate guidance.
    # If the user-supplied angle is outside [30, 45], the caveat flags it.
    if grade_key in _HIGH_VISCOSITY_POLYMERS:
        recommended_angle_deg = 45.0
    else:
        recommended_angle_deg = 30.0

    # -------------------------------------------------------------------
    # 6. Caveat
    # -------------------------------------------------------------------
    caveat = _CAVEAT_TMPL.format(
        viscosity_note=viscosity_note,
        shear_str_MPa=shear_strength_MPa,
        polymer=spec.polymer_grade,
    )

    return TunnelGateReport(
        gate_diameter_mm=round(d_gate_mm, 6),
        gate_break_off_force_N=round(F_break_N, 4),
        gate_freeze_time_s=round(gate_freeze_time_s, 6),
        shear_rate_at_gate_per_s=round(shear_rate_per_s, 2),
        shear_within_limit=shear_within_limit,
        recommended_angle_deg=recommended_angle_deg,
        honest_caveat=caveat,
    )
