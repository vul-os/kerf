"""
kerf_mold.core_pin_cooling
===========================
Baffle / bubbler cooling design for tall injection-mold core pins (slender
interior-rib cooling).

Theory
------
Slender core pins (diameter < 20 mm, height > 50 mm) cannot be cooled by
conventional straight drilled channels because the pin itself is too narrow to
fit a channel of adequate diameter.  Two internal cooling architectures are
used in practice (Menges 2001 §7.5; Beaumont 2007 §11.4):

  Baffle cooling
  ~~~~~~~~~~~~~~
  A longitudinal dividing plate (baffle) is inserted into a single central
  bore, creating two half-annular flow passages — coolant flows down one side
  and returns up the other.  The hydraulic diameter of each half-annular
  passage is approximated as the tube ID (i.e. the full bore diameter),
  because the baffle is thin relative to the bore.  Effective in cores with
  bore-ID ≥ 4 mm.

  Bubbler / fountain cooling
  ~~~~~~~~~~~~~~~~~~~~~~~~~~
  A small-diameter inner tube (the "bubbler tube") is inserted coaxially
  inside the bore.  Coolant is pumped down through the inner tube and returns
  up the annular gap between the tube OD and the bore ID.  The hydraulic
  diameter of the return annulus is D_h = D_bore − D_tube.  Beaumont 2007
  §11.4 and Menges 2001 §7.5 report that the fountain effect at the tip and
  the better contact between the coolant and the pin tip approximately double
  the effective convective HTC compared with a baffle of the same bore
  diameter and flow rate.

Reynolds number — volumetric form (avoids area computation ambiguity)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
For full circular pipe flow:

    Re = 4·Q·ρ / (π·D·μ)

  where Q [m³/s], ρ [kg/m³], D [m], μ [Pa·s].

This is algebraically identical to ρ·v·D/μ with v = 4Q/(π·D²).  The same
formula is applied to both baffle and bubbler channels using the HYDRAULIC
DIAMETER of the relevant passage:

  Baffle  : D_h = cooling_type_id_mm × 1e-3  (full bore)
  Bubbler : D_h = cooling_type_id_mm × 1e-3  (outer bore; inner tube OD is
                  not separately modelled — conservative: hydraulic diameter
                  slightly overestimated, Re slightly understated)

Dittus-Boelter Nusselt number (Incropera & DeWitt 7th ed., eq. 8.60)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Valid for Re ≥ 10 000, 0.6 ≤ Pr ≤ 160, L/D ≥ 10 (thermally developed,
turbulent):

    Nu = 0.023 · Re^0.8 · Pr^0.4   (Pr^0.4 → coolant being heated)

Convective heat-transfer coefficient (HTC):

    h = Nu · k_f / D_h

  where k_f = thermal conductivity of coolant [W/m·K].

Bubbler HTC multiplier (Menges 2001 §7.5; Beaumont 2007 §11.4)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Bubbler/fountain cooling is reported to approximately double the HTC relative
to an equivalent baffle because:

  (a) the impinging jet at the pin tip breaks the thermal boundary layer;
  (b) the annular return flow is slightly more turbulent near the tip.

Applied as: h_bubbler ≈ 2 × h_baffle.

Core-tip temperature — lumped capacitance approximation
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
The steel core pin is modelled as a lumped (spatially uniform temperature)
thermal resistance body in steady state.  The lumped fin analogy gives:

    T_tip_estimate = T_melt − (T_melt − T_coolant) · (h·A_pin) / (h·A_pin + k_steel·A_cross/L_half)

For practical estimation we use a simplified steady-state 1-D balance over a
half-height slab of steel:

    Q_heat = (T_melt − T_tip) / R_total

    R_total = R_conv_polymer + R_cond_steel + R_conv_coolant

    R_conv_polymer = 1 / (h_p · A_pin_surface)   [K/W]
      h_p = 2 000 W/m²K (polymer contact HTC — Menges 2001 §7.1 typical
            range 1 000–4 000 W/m²K; 2 000 W/m²K is a conservative mid-
            point for crystalline / amorphous resins)
    R_cond_steel   = L_half / (k_steel · A_cross)  [K/W]
      k_steel = 15 W/m·K (typical mold steel — P20/H13; Menges 2001 §7.1)
      L_half  = core_height_mm / 2 (heat path from mid-height to coolant)
      A_cross = π · (core_diameter_mm/2)² (cross-sectional area for axial
                conduction through the pin body)
    R_conv_coolant = 1 / (h_cool · A_cool)  [K/W]
      h_cool  = HTC from Dittus-Boelter above
      A_cool  = π · D_h · core_height_mm   (cooled internal bore area)

    T_tip = T_coolant + Q_heat · (R_cond_steel + R_conv_coolant)

Because R_conv_polymer is usually the controlling resistance for a
well-designed cooling channel, T_tip converges toward T_coolant + a small
offset when h_cool >> h_p.

Cycle-time estimate
~~~~~~~~~~~~~~~~~~~
A simplified 1-D Fourier single-term cooling-time approximation (Menges 2001
§7.3.3; identical to Chen-Chiang 1985):

    t_c = (h_wall² / (π² · α)) · ln[(8/π²) · (T_melt − T_coolant) / (T_eject − T_coolant)]

  where:
    h_wall  = half the core wall thickness = core_diameter_mm / 2 [m]
    α       = thermal diffusivity of the polymer [m²/s]
    T_eject = target_core_temp_C (used as part ejection temperature)

  Default polymer diffusivity: 1.0e-7 m²/s (ABS baseline; Menges 2001 Table 7.3).

Honest caveats
--------------
  (1) Lumped-capacitance steady-state only — NO transient FEA.  Transient
      temperature cycling (important for thin cores < 5 mm) is NOT modelled.
  (2) Uniform melt temperature assumed — no gate-to-far-end gradient.
  (3) Bubbler HTC multiplier is an empirical factor (Menges 2001 §7.5) —
      actual improvement depends on tube OD/bore ID ratio, flow split, tip
      clearance, and entry turbulence.
  (4) Polymer-side HTC (h_p = 2000 W/m²K) is a handbook midpoint; actual
      values range 1 000–4 000 W/m²K depending on polymer viscosity, melt
      pressure, and surface roughness.
  (5) Dittus-Boelter requires Re ≥ 10 000 and L/D ≥ 10 for fully-developed
      turbulent flow; below Re 10 000 the Nu formula over-predicts HTC — the
      report flags this.
  (6) No cooling-channel thermal resistance along the mold steel surrounding
      the core bore is included — assumes the bore is machined directly in
      the pin body.
  (7) Cycle-time estimate is for the core-pin wall thickness only (1-D
      Fourier); actual mold cycle depends on the thickest wall section and
      both core/cavity cooling simultaneously.

References
----------
Menges G., Michaeli W., Mohren P. "How to Make Injection Molds", 3rd ed.,
  Hanser 2001, §7.5 (Core pin cooling — baffle and bubbler designs; HTC
  comparison), §7.1 (Polymer-side heat-transfer coefficient), §7.3.3
  (Cooling-time formula).

Beaumont J.P. "Runner and Gating Design Handbook", 2nd ed., Hanser 2007,
  §11.4 (Slender-core cooling — baffle vs. bubbler; fountain-effect doubling
  of HTC).

Incropera F.P., DeWitt D.P. "Fundamentals of Heat and Mass Transfer",
  7th ed., Wiley 2011, §8.5 (Dittus-Boelter correlation; eq. 8.60).

White F.M. "Fluid Mechanics", 8th ed., McGraw-Hill 2016, §8.1 (Reynolds
  number definition; laminar/turbulent thresholds).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field


# ---------------------------------------------------------------------------
# Physical constants / defaults
# ---------------------------------------------------------------------------

#: Water at ~20 °C density [kg/m³]
_WATER_DENSITY_KG_M3: float = 1000.0

#: Water at ~20 °C dynamic viscosity [Pa·s]
_WATER_MU_PA_S: float = 1.0e-3

#: Water at ~20 °C Prandtl number (dimensionless)
_WATER_PR: float = 7.0

#: Water at ~20 °C thermal conductivity [W/m·K]
_WATER_K_W_M_K: float = 0.598

#: Mold steel (P20 / H13) thermal conductivity [W/m·K] (Menges 2001 §7.1)
_STEEL_K_W_M_K: float = 15.0

#: Polymer-side convective HTC [W/m²K] (Menges 2001 §7.1, midpoint)
_H_POLYMER_W_M2_K: float = 2000.0

#: Default polymer thermal diffusivity [m²/s] (ABS; Menges 2001 Table 7.3)
_POLYMER_ALPHA_M2_S: float = 1.0e-7

#: Minimum Re for Dittus-Boelter applicability (Incropera eq. 8.60)
_RE_MIN_DITTUS_BOELTER: float = 10_000.0

#: Bubbler HTC multiplier relative to baffle (Menges 2001 §7.5; Beaumont 2007 §11.4)
_BUBBLER_HTC_MULTIPLIER: float = 2.0

#: Nominal coolant temperature [°C] (chiller setpoint; typical mold cooling)
_DEFAULT_COOLANT_TEMP_C: float = 20.0


# ---------------------------------------------------------------------------
# Honest caveat text
# ---------------------------------------------------------------------------

_HONEST_CAVEAT = (
    "Lumped-capacitance steady-state model: Menges 2001 §7.5 + Beaumont 2007 "
    "§11.4. SCOPE LIMITS: (1) No transient FEA — lumped capacitance "
    "steady-state only; transient thermal cycling of thin cores (< 5 mm) NOT "
    "captured. (2) Uniform melt temperature assumed — no gate-to-far-end "
    "gradient. (3) Bubbler HTC = 2× baffle is an empirical factor from "
    "Menges §7.5; actual factor depends on tube OD/bore ID ratio, tip "
    "clearance, and entry turbulence. (4) Polymer-side HTC = 2000 W/m²K is "
    "a handbook midpoint (range 1 000–4 000 W/m²K). (5) Dittus-Boelter "
    "(Incropera eq. 8.60) requires Re ≥ 10 000 and L/D ≥ 10 — low-Re "
    "results over-estimate HTC. (6) Cycle-time estimate is 1-D Fourier "
    "first-term for pin wall-half-thickness only — NOT full mold cycle. "
    "(7) Confirm with transient injection-mold FEA (Moldflow Insight, "
    "Moldex3D, SigmaSoft) for production tooling."
)


# ---------------------------------------------------------------------------
# Input dataclass
# ---------------------------------------------------------------------------

@dataclass
class CorePinSpec:
    """Geometry and operating conditions for a core-pin interior cooling circuit.

    Parameters
    ----------
    core_diameter_mm : float
        Outer diameter of the core pin [mm].  Must be > 0.
    core_height_mm : float
        Height (length) of the core pin above the parting line [mm].  Must
        be > 0.
    baffle_or_bubbler : str
        Internal cooling type: ``"baffle"`` (longitudinal dividing plate) or
        ``"bubbler"`` (inner fountain tube).  Case-insensitive.
    cooling_type_id_mm : float
        Internal bore diameter of the cooling passage [mm].  For baffle: the
        full bore ID.  For bubbler: the outer bore ID (inner tube OD is not
        separately modelled).  Must be > 0 and < core_diameter_mm.
    coolant_flow_L_per_min : float
        Volumetric coolant flow rate through the core pin cooling circuit
        [L/min].  Must be > 0.
    melt_temp_C : float
        Polymer melt temperature at the gate [°C].  Must be > 0.
    target_core_temp_C : float
        Target core pin temperature (= ejection temperature for the pin
        cavity surface) [°C].  Must be > 0 and < melt_temp_C.
    polymer_grade : str
        Informal polymer identification (used only for display / caveat
        purposes — e.g. ``"ABS"``, ``"PP"``, ``"PA66"``).  No look-up table
        is applied; thermal diffusivity is fixed at the ABS default.
    coolant_temp_C : float, optional
        Coolant supply temperature [°C].  Default 20.0.
    coolant_density_kg_m3 : float, optional
        Coolant density [kg/m³].  Default 1000.0 (water at ~20 °C).
    coolant_viscosity_Pa_s : float, optional
        Coolant dynamic viscosity [Pa·s].  Default 1.0e-3 (water at ~20 °C).
    coolant_Pr : float, optional
        Coolant Prandtl number.  Default 7.0 (water at ~20 °C).
    coolant_k_W_m_K : float, optional
        Coolant thermal conductivity [W/m·K].  Default 0.598 (water at
        ~20 °C).
    """

    core_diameter_mm: float
    core_height_mm: float
    baffle_or_bubbler: str
    cooling_type_id_mm: float
    coolant_flow_L_per_min: float
    melt_temp_C: float
    target_core_temp_C: float
    polymer_grade: str
    coolant_temp_C: float = _DEFAULT_COOLANT_TEMP_C
    coolant_density_kg_m3: float = _WATER_DENSITY_KG_M3
    coolant_viscosity_Pa_s: float = _WATER_MU_PA_S
    coolant_Pr: float = _WATER_PR
    coolant_k_W_m_K: float = _WATER_K_W_M_K

    def __post_init__(self) -> None:  # noqa: C901
        if self.core_diameter_mm <= 0.0:
            raise ValueError(
                f"CorePinSpec.core_diameter_mm must be > 0, "
                f"got {self.core_diameter_mm}"
            )
        if self.core_height_mm <= 0.0:
            raise ValueError(
                f"CorePinSpec.core_height_mm must be > 0, "
                f"got {self.core_height_mm}"
            )
        _type = self.baffle_or_bubbler.lower().strip()
        if _type not in ("baffle", "bubbler"):
            raise ValueError(
                f"CorePinSpec.baffle_or_bubbler must be 'baffle' or 'bubbler', "
                f"got {self.baffle_or_bubbler!r}"
            )
        # Store normalised value
        self.baffle_or_bubbler = _type
        if self.cooling_type_id_mm <= 0.0:
            raise ValueError(
                f"CorePinSpec.cooling_type_id_mm must be > 0, "
                f"got {self.cooling_type_id_mm}"
            )
        if self.cooling_type_id_mm >= self.core_diameter_mm:
            raise ValueError(
                f"CorePinSpec.cooling_type_id_mm ({self.cooling_type_id_mm}) "
                f"must be < core_diameter_mm ({self.core_diameter_mm})"
            )
        if self.coolant_flow_L_per_min <= 0.0:
            raise ValueError(
                f"CorePinSpec.coolant_flow_L_per_min must be > 0, "
                f"got {self.coolant_flow_L_per_min}"
            )
        if self.melt_temp_C <= 0.0:
            raise ValueError(
                f"CorePinSpec.melt_temp_C must be > 0, "
                f"got {self.melt_temp_C}"
            )
        if self.target_core_temp_C <= 0.0:
            raise ValueError(
                f"CorePinSpec.target_core_temp_C must be > 0, "
                f"got {self.target_core_temp_C}"
            )
        if self.target_core_temp_C >= self.melt_temp_C:
            raise ValueError(
                f"CorePinSpec.target_core_temp_C ({self.target_core_temp_C}) "
                f"must be < melt_temp_C ({self.melt_temp_C})"
            )
        if self.coolant_density_kg_m3 <= 0.0:
            raise ValueError(
                f"CorePinSpec.coolant_density_kg_m3 must be > 0, "
                f"got {self.coolant_density_kg_m3}"
            )
        if self.coolant_viscosity_Pa_s <= 0.0:
            raise ValueError(
                f"CorePinSpec.coolant_viscosity_Pa_s must be > 0, "
                f"got {self.coolant_viscosity_Pa_s}"
            )
        if self.coolant_Pr <= 0.0:
            raise ValueError(
                f"CorePinSpec.coolant_Pr must be > 0, "
                f"got {self.coolant_Pr}"
            )
        if self.coolant_k_W_m_K <= 0.0:
            raise ValueError(
                f"CorePinSpec.coolant_k_W_m_K must be > 0, "
                f"got {self.coolant_k_W_m_K}"
            )


# ---------------------------------------------------------------------------
# Output dataclass
# ---------------------------------------------------------------------------

@dataclass
class CorePinCoolingReport:
    """Result of a baffle / bubbler core-pin cooling design analysis.

    Attributes
    ----------
    reynolds_number : float
        Re = 4·Q·ρ/(π·D_h·μ) in the cooling bore (dimensionless).
    htc_W_per_m2K : float
        Convective heat-transfer coefficient at the bore wall [W/m²K].
        Computed via Dittus-Boelter (Incropera eq. 8.60):
        Nu = 0.023·Re^0.8·Pr^0.4; h = Nu·k_f/D_h.
        Bubbler applies a 2× multiplier per Menges 2001 §7.5.
    estimated_core_tip_temp_C : float
        Estimated steady-state core-pin tip temperature [°C] from a 1-D
        lumped resistance model (R_polymer + R_steel + R_coolant).
    cooling_adequate : bool
        True iff estimated_core_tip_temp_C ≤ target_core_temp_C and
        Re ≥ 10 000 (fully turbulent).
    cycle_time_estimate_s : float
        1-D Fourier first-term cooling-time estimate [s] using pin
        half-diameter as h_wall and the ABS baseline diffusivity.
        Uses Chen-Chiang / Menges 2001 §7.3.3 formula.
    honest_caveat : str
        Plain-language statement of model scope and limitations.
    """

    reynolds_number: float
    htc_W_per_m2K: float
    estimated_core_tip_temp_C: float
    cooling_adequate: bool
    cycle_time_estimate_s: float
    honest_caveat: str = field(default=_HONEST_CAVEAT)


# ---------------------------------------------------------------------------
# Core computation
# ---------------------------------------------------------------------------

def design_core_pin_cooling(spec: CorePinSpec) -> CorePinCoolingReport:
    """Design and verify a baffle or bubbler cooling circuit for a core pin.

    Parameters
    ----------
    spec : CorePinSpec
        Core geometry, cooling configuration, and operating conditions.

    Returns
    -------
    CorePinCoolingReport
        Reynolds number, Dittus-Boelter HTC, estimated core-tip temperature,
        adequacy flag, cycle-time estimate, and honest caveat.

    Raises
    ------
    ValueError
        If any field in *spec* is invalid (delegated to ``__post_init__``).

    Notes
    -----
    Computation path:

    1. Unit conversions::

         D_h [m]  = cooling_type_id_mm × 1e-3
         Q   [m³/s] = coolant_flow_L_per_min / 60 000
         L_pin [m]  = core_height_mm × 1e-3
         D_pin [m]  = core_diameter_mm × 1e-3

    2. Reynolds number (volumetric form)::

         Re = 4 · Q · ρ / (π · D_h · μ)

    3. Nusselt number (Dittus-Boelter, Incropera eq. 8.60)::

         Nu = 0.023 · Re^0.8 · Pr^0.4

       Applied even below Re=10 000 but flagged as unreliable.

    4. Convective HTC::

         h_base = Nu · k_f / D_h   [W/m²K]

       Bubbler: h = 2 · h_base; Baffle: h = h_base.

    5. Thermal resistances (1-D steady-state)::

         A_pin_surface = π · D_pin · L_pin          [m²]  (lateral)
         A_cross       = π · (D_pin/2)²             [m²]  (axial cross-section)
         L_half        = L_pin / 2                  [m]   (half height)
         A_cool        = π · D_h · L_pin            [m²]  (bore inner area)

         R_poly  = 1 / (h_p · A_pin_surface)        [K/W]
         R_steel = L_half / (k_steel · A_cross)     [K/W]
         R_cool  = 1 / (h · A_cool)                 [K/W]
         R_total = R_poly + R_steel + R_cool

    6. Heat flux and tip temperature::

         Q_heat  = (T_melt − T_coolant) / R_total   [W]
         T_tip   = T_coolant + Q_heat · (R_steel + R_cool)  [°C]

    7. Cooling-time estimate (Menges 2001 §7.3.3 / Chen-Chiang 1985)::

         h_wall = D_pin / 2                         [m] (half wall thickness)
         T_e    = target_core_temp_C                [°C]

         t_c = (h_wall² / (π² · α)) · ln[(8/π²) · (T_melt − T_coolant)
                                                   / (T_e   − T_coolant)]

       Returns 0.0 if the log argument ≤ 0 (i.e. T_e ≤ T_coolant).

    """
    # --- Unit conversions ---
    D_h: float = spec.cooling_type_id_mm * 1e-3          # m — hydraulic diameter
    Q: float   = spec.coolant_flow_L_per_min / 60_000.0  # m³/s
    rho: float = spec.coolant_density_kg_m3               # kg/m³
    mu: float  = spec.coolant_viscosity_Pa_s              # Pa·s
    Pr: float  = spec.coolant_Pr                          # dimensionless
    k_f: float = spec.coolant_k_W_m_K                    # W/m·K

    L_pin: float = spec.core_height_mm * 1e-3             # m
    D_pin: float = spec.core_diameter_mm * 1e-3           # m

    T_melt: float   = spec.melt_temp_C                   # °C
    T_cool: float   = spec.coolant_temp_C                 # °C
    T_target: float = spec.target_core_temp_C             # °C

    # --- Reynolds number (volumetric form) ---
    re: float = 4.0 * Q * rho / (math.pi * D_h * mu)

    # --- Nusselt number (Dittus-Boelter Incropera eq. 8.60) ---
    # Applied regardless of Re; low-Re caveat is in honest_caveat.
    nu: float = 0.023 * (re ** 0.8) * (Pr ** 0.4)

    # --- Convective HTC at the bore wall ---
    h_base: float = nu * k_f / D_h   # W/m²K

    # Bubbler doubles the HTC (Menges 2001 §7.5; Beaumont 2007 §11.4)
    if spec.baffle_or_bubbler == "bubbler":
        h_cool: float = _BUBBLER_HTC_MULTIPLIER * h_base
    else:
        h_cool = h_base

    # --- Geometric areas ---
    A_pin_surface: float = math.pi * D_pin * L_pin        # m² lateral surface
    A_cross: float       = math.pi * (D_pin / 2.0) ** 2  # m² axial section
    A_cool: float        = math.pi * D_h * L_pin          # m² bore inner area
    L_half: float        = L_pin / 2.0                    # m

    # --- Thermal resistances (1-D steady-state lumped model) ---
    R_poly: float  = 1.0 / (_H_POLYMER_W_M2_K * A_pin_surface)   # K/W
    R_steel: float = L_half / (_STEEL_K_W_M_K * A_cross)         # K/W
    R_cool: float  = 1.0 / (h_cool * A_cool)                     # K/W
    R_total: float = R_poly + R_steel + R_cool                    # K/W

    # --- Steady-state heat flux and tip temperature ---
    Q_heat: float  = (T_melt - T_cool) / R_total         # W
    T_tip: float   = T_cool + Q_heat * (R_steel + R_cool) # °C

    # --- Cooling adequacy ---
    cooling_adequate: bool = (T_tip <= T_target) and (re >= _RE_MIN_DITTUS_BOELTER)

    # --- Cycle-time estimate (Menges 2001 §7.3.3 / Chen-Chiang 1985) ---
    h_wall: float = D_pin / 2.0   # half wall thickness [m]
    cycle_time_s: float = 0.0
    _log_arg = (8.0 / (math.pi ** 2)) * (T_melt - T_cool) / max(T_target - T_cool, 1e-6)
    if _log_arg > 0.0:
        cycle_time_s = (h_wall ** 2 / (math.pi ** 2 * _POLYMER_ALPHA_M2_S)) * math.log(_log_arg)
        if cycle_time_s < 0.0:
            cycle_time_s = 0.0

    return CorePinCoolingReport(
        reynolds_number=round(re, 2),
        htc_W_per_m2K=round(h_cool, 2),
        estimated_core_tip_temp_C=round(T_tip, 2),
        cooling_adequate=cooling_adequate,
        cycle_time_estimate_s=round(cycle_time_s, 4),
    )
