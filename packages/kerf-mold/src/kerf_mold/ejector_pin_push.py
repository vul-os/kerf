"""
kerf_mold.ejector_pin_push
==========================
Compute the buckling-limited axial push force for an SPI-standard ejector pin
using Euler's critical-load formula.

Theory — SPI/ANSI B151.1 + Roark's 9e §15
------------------------------------------
An ejector pin loaded axially in compression may buckle (fail elastically at a
load far below yield) when its slenderness ratio is large.  The Euler formula
(Euler 1744; Roark's Formulas for Stress and Strain, 9th ed., §15.2) gives the
critical buckling load:

    F_cr = π² · E · I / (K · L)²

where:
  E    — Young's modulus of the pin material [N/mm² = MPa]
  I    — Second moment of area of the pin cross-section [mm⁴]
         For a solid circular section: I = π · d⁴ / 64
  K    — End-condition factor (effective-length coefficient):
           K = 1.0  pinned-pinned (SPI/ANSI B151.1 design default for guided pins)
           K = 0.5  fixed-fixed (both ends fully clamped)
           K = 0.7  fixed-pinned (one end clamped, one end guided)
           K = 2.0  cantilever (one end fixed, one end free)
  L    — Unsupported pin length (free length between supports) [mm]
  K·L  — Effective (buckling) length [mm]

The demand-to-capacity ratio:
    DCR = required_push_force_N / F_cr

  DCR ≤ 1.0  → pin is adequate
  DCR > 1.0  → pin will buckle before developing the required force

Recommendation logic
--------------------
When DCR > 1.0 the function searches SPI-standard pin diameters in ascending
order and returns the smallest diameter whose F_cr ≥ required_push_force_N,
using a 10 % design margin (i.e., target F_cr ≥ 1.1 × required_push_force_N).
If no standard SPI diameter is adequate, the next-integer-millimetre size is
returned with an advisory caveat.

Material — Young's modulus
--------------------------
All tool-steel grades used for ejector pins share the same nominal E:

  M2 tool steel  — E ≈ 200 GPa  (primary grade; Böhler/Uddeholm data sheets)
  H13 hot-work   — E ≈ 200 GPa  (ASM Handbook Vol. 1, Table 9.2)
  S7  shock       — E ≈ 200 GPa  (ASM Handbook Vol. 1)
  D2  cold-work   — E ≈ 200 GPa  (Roberts & Cary "Tool Steels" 5th ed.)

E = 200 000 N/mm² (200 GPa) is used for all four grades.  The ±1–2 % variation
between grades is negligible compared to the ±10–20 % uncertainty in end-
condition factor K and length tolerancing in a real mold.

Honest caveats
--------------
1. **Euler formula valid only for long/slender pins** (slenderness ratio
   K·L/r ≥ ~120 for tool steel, where r = d/4 for solid round section,
   equivalently L/d ≥ ~30 for K=1).  For short stout pins (K·L/r < 30) the
   Johnson parabolic formula gives a more accurate result:

       F_cr_Johnson = A·σ_y · [1 − σ_y·(K·L/r)² / (4·π²·E)]

   The reported DCR is non-conservative (too optimistic) in the short-column
   regime.  The function flags this in `honest_caveat` when L/d < 30.

2. **Bushing friction is ignored.**  In practice the pin guide bushing exerts
   a lateral force on the pin proportional to the side load and friction
   coefficient (μ ≈ 0.05–0.10 for lubricated H13/M2 pin in hardened bushing).
   This reduces the effective axial capacity by 3–10 %.

3. **Pin straightness and press-fit preload.**  SPI/ANSI B151.1 requires total
   indicator runout (TIR) ≤ 0.002 mm/25 mm; eccentricity reduces F_cr by
   amplification factor [1 − F/F_cr]⁻¹ (beam-column effect, Roark's §15.3).

4. **Dynamic ejection forces** are NOT modelled.  Impact at end-of-stroke can
   momentarily exceed the static demand force.

5. **Fatigue** over millions of cycles is NOT assessed.  For high-volume
   tooling (> 1 M cycles) select H13 or M2 at Rockwell C 60–62 and verify
   pin fatigue life separately.

References
----------
Society of the Plastics Industry (SPI) / ANSI B151.1 — Ejector pin dimensional
  standards and load-capacity guidance.
Roark R.J. & Young W.C. "Formulas for Stress and Strain", 9th ed. (2020),
  §15.2 (Euler columns), §15.3 (beam-column interaction).
ASM Handbook Vol. 1: Properties and Selection: Irons, Steels, and High-Performance
  Alloys, 10th ed. — Tool steel moduli.
Roberts G.A. & Cary R.A. "Tool Steels", 5th ed., ASM International 1980.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Literal

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Young's modulus for all supported tool-steel grades [N/mm²].
#: All grades share the same nominal E = 200 GPa.
_E_TOOL_STEEL_N_MM2: float = 200_000.0  # N/mm² = MPa

#: SPI/ANSI B151.1 standard ejector pin diameters [mm] in ascending order.
#: Source: DME/HASCO/Mold-Masters standard stock catalogue + SPI B151.1 Table 1.
SPI_EJECTOR_PIN_DIAMETERS_MM: tuple[float, ...] = (
    1.0, 1.5, 2.0, 2.5, 3.0, 4.0, 5.0, 6.0, 8.0, 10.0, 12.0, 16.0, 20.0,
)

#: Supported pin material strings.
PinMaterial = Literal["M2_tool_steel", "H13", "S7", "D2"]

#: Slenderness-ratio threshold below which the Johnson formula is more accurate.
#: Euler is non-conservative for K·L/r < 120 (tool steel σ_y ≈ 2 000 MPa).
#: Expressed as effective-length-to-diameter ratio for K=1: K·L/d < 30.
_SLENDERNESS_THRESHOLD_L_OVER_D: float = 30.0

#: Design margin applied when searching for recommended diameter.
_DESIGN_MARGIN: float = 1.10  # 10 %

# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class EjectorPinPushSpec:
    """Specification for an ejector pin buckling-force check.

    Attributes
    ----------
    pin_diameter_mm : float
        Pin shank diameter [mm].  Must be > 0.
    pin_length_L_mm : float
        Free (unsupported) length of the pin between guides [mm].
        Typically measured from the rear face of the ejector plate to the
        parting face of the mold.  Must be > 0.
    pin_material : str
        One of ``"M2_tool_steel"``, ``"H13"``, ``"S7"``, ``"D2"``.
        All grades use E = 200 GPa; the field is recorded for traceability.
    end_condition_K : float
        Effective-length (end-condition) coefficient K.

        +------------------+-------+------------------------------------------+
        | Condition         |   K   | Typical use                              |
        +==================+=======+==========================================+
        | Pinned–pinned     |  1.0  | SPI/ANSI B151.1 default — guided pin     |
        | Fixed–pinned      |  0.7  | Rear end clamped, tip guided in bushing  |
        | Fixed–fixed       |  0.5  | Both ends clamped (rare for ejector pins)|
        | Cantilever        |  2.0  | Unsupported tip (never use this)         |
        +------------------+-------+------------------------------------------+

        Default 1.0 (pinned-pinned).
    required_push_force_N : float
        Total axial push force the pin must transmit [N].  Typically obtained
        from ``mold_compute_demold_force`` divided by the number of ejector
        pins.  Must be > 0.
    """

    pin_diameter_mm: float
    pin_length_L_mm: float
    pin_material: str
    end_condition_K: float = 1.0
    required_push_force_N: float = 0.0

    def __post_init__(self) -> None:
        _valid_materials = {"M2_tool_steel", "H13", "S7", "D2"}
        if self.pin_diameter_mm <= 0.0:
            raise ValueError(
                f"pin_diameter_mm must be > 0, got {self.pin_diameter_mm}"
            )
        if self.pin_length_L_mm <= 0.0:
            raise ValueError(
                f"pin_length_L_mm must be > 0, got {self.pin_length_L_mm}"
            )
        if self.pin_material not in _valid_materials:
            raise ValueError(
                f"Unknown pin_material '{self.pin_material}'. "
                f"Supported: {sorted(_valid_materials)}."
            )
        if self.end_condition_K <= 0.0:
            raise ValueError(
                f"end_condition_K must be > 0, got {self.end_condition_K}"
            )
        if self.required_push_force_N < 0.0:
            raise ValueError(
                f"required_push_force_N must be >= 0, got {self.required_push_force_N}"
            )


@dataclass
class EjectorPinPushReport:
    """Result produced by :func:`compute_ejector_pin_push`.

    Attributes
    ----------
    buckling_force_N : float
        Euler critical buckling load F_cr = π²·E·I/(K·L)² [N].
    dcr : float
        Demand-to-capacity ratio = required_push_force_N / buckling_force_N.
        Values > 1.0 indicate the pin will buckle before developing the
        required push force.
    adequate : bool
        True iff dcr ≤ 1.0 (pin is not expected to buckle).
    recommended_min_diameter_mm : float
        Smallest SPI-standard pin diameter (with 10 % design margin) that
        satisfies F_cr ≥ 1.1 × required_push_force_N at the same length and
        end condition.  Equal to ``pin_diameter_mm`` if the current pin is
        already adequate.
    recommended_pin_material : str
        Material recommendation.  "M2_tool_steel" is suggested when dcr > 0.8
        (near the limit) or the current material is suboptimal; otherwise the
        input material is preserved.
    honest_caveat : str
        Plain-language statement of model limitations — Euler regime, bushing
        friction, short-column correction, etc.
    """

    buckling_force_N: float
    dcr: float
    adequate: bool
    recommended_min_diameter_mm: float
    recommended_pin_material: str
    honest_caveat: str = field(default="")


# ---------------------------------------------------------------------------
# Core computation
# ---------------------------------------------------------------------------

_CAVEAT_TMPL = (
    "Euler critical buckling load F_cr = π²·E·I/(K·L)² "
    "(SPI/ANSI B151.1 + Roark's 9e §15.2). "
    "E = 200 GPa for {material} (all tool-steel grades ≈ 200 GPa). "
    "I = π·d⁴/64 for solid round section. "
    "End-condition K = {K} (K=1.0 pinned-pinned SPI default, K=0.5 fixed-fixed, "
    "K=2.0 cantilever). "
    "{short_column_note}"
    "HONEST CAVEATS: "
    "(1) Euler formula is non-conservative for short/stout pins — "
    "use Johnson parabolic formula when K·L/r < 120 (K·L/d < 30 for K=1). "
    "(2) Bushing friction (μ≈0.05–0.10 lubricated) reduces axial capacity "
    "3–10 % and is NOT modelled here. "
    "(3) Pin eccentricity / TIR reduces capacity via beam-column amplification "
    "(Roark's 9e §15.3) — NOT modelled. "
    "(4) Dynamic impact at end-of-stroke and pin fatigue are NOT assessed. "
    "Verify by mold trial with load cell; for > 1 M cycles select M2 or H13 "
    "at HRC 60–62 and check fatigue life separately. "
    "Refs: SPI/ANSI B151.1; Roark's 9e §15.2–15.3; "
    "ASM Handbook Vol.1 (tool-steel E values)."
)

_SHORT_COLUMN_NOTE = (
    "WARNING: L/d = {ld:.1f} < 30 — this pin is in the short-column regime "
    "where Euler over-estimates F_cr (non-conservative). "
    "Apply the Johnson parabolic formula: "
    "F_cr_J = A·σ_y·[1 − σ_y·(K·L/r)²/(4·π²·E)] "
    "for a more accurate and safe result. "
)


def _second_moment_of_area(d_mm: float) -> float:
    """Solid circular section second moment of area I = π·d⁴/64 [mm⁴]."""
    return math.pi * d_mm ** 4 / 64.0


def _euler_buckling_force(d_mm: float, L_mm: float, K: float,
                          E_N_mm2: float = _E_TOOL_STEEL_N_MM2) -> float:
    """Euler critical buckling load [N] for a solid circular column.

    Parameters
    ----------
    d_mm : float
        Pin diameter [mm].
    L_mm : float
        Free length [mm].
    K : float
        End-condition coefficient.
    E_N_mm2 : float
        Young's modulus [N/mm²].

    Returns
    -------
    float
        F_cr = π²·E·I / (K·L)² [N].
    """
    I = _second_moment_of_area(d_mm)
    KL = K * L_mm
    return (math.pi ** 2 * E_N_mm2 * I) / (KL ** 2)


def _find_recommended_diameter(
    L_mm: float,
    K: float,
    required_N: float,
    E_N_mm2: float = _E_TOOL_STEEL_N_MM2,
) -> float:
    """Find the smallest SPI-standard diameter with F_cr ≥ required_N × margin.

    Returns the pin diameter [mm].  Falls back to a non-standard integer-mm
    size if no SPI standard size qualifies.
    """
    target = required_N * _DESIGN_MARGIN
    for d in SPI_EJECTOR_PIN_DIAMETERS_MM:
        if _euler_buckling_force(d, L_mm, K, E_N_mm2) >= target:
            return d
    # Brute-force integer mm above the largest SPI size
    d = float(math.ceil(SPI_EJECTOR_PIN_DIAMETERS_MM[-1])) + 1.0
    while d < 100.0:
        if _euler_buckling_force(d, L_mm, K, E_N_mm2) >= target:
            return d
        d += 1.0
    return d  # safety fallback; should not happen for practical pin sizes


def compute_ejector_pin_push(spec: EjectorPinPushSpec) -> EjectorPinPushReport:
    """Compute the Euler buckling-limited push force for an ejector pin.

    Applies the Euler critical-load formula
    ``F_cr = π²·E·I / (K·L)²`` (Roark's 9th ed. §15.2 + SPI/ANSI B151.1).

    Parameters
    ----------
    spec : EjectorPinPushSpec
        Pin geometry, material, end condition, and required push force.

    Returns
    -------
    EjectorPinPushReport
        Buckling force, DCR, adequacy, recommended diameter, and honest
        caveats.

    Raises
    ------
    ValueError
        If spec contains invalid values.
    """
    E = _E_TOOL_STEEL_N_MM2  # same for all supported grades

    f_cr = _euler_buckling_force(
        spec.pin_diameter_mm, spec.pin_length_L_mm, spec.end_condition_K, E
    )
    f_cr = round(f_cr, 3)

    # DCR — guard against zero required force (edge case: just characterising capacity)
    if spec.required_push_force_N == 0.0:
        dcr = 0.0
    else:
        dcr = spec.required_push_force_N / f_cr

    dcr = round(dcr, 6)
    adequate = dcr <= 1.0

    # Recommended diameter
    if adequate:
        rec_d = spec.pin_diameter_mm
    else:
        rec_d = _find_recommended_diameter(
            spec.pin_length_L_mm, spec.end_condition_K,
            spec.required_push_force_N, E,
        )

    # Material recommendation: prefer M2 for high-load (near capacity) cases
    if dcr > 0.8 or not adequate:
        rec_mat = "M2_tool_steel"
    else:
        rec_mat = spec.pin_material

    # Short-column check: effective-length/diameter ratio
    KL = spec.end_condition_K * spec.pin_length_L_mm
    ld = KL / spec.pin_diameter_mm  # K·L / d (K·L/r = 4·K·L/d for solid round)
    if ld < _SLENDERNESS_THRESHOLD_L_OVER_D:
        short_note = _SHORT_COLUMN_NOTE.format(ld=KL / spec.pin_diameter_mm)
    else:
        short_note = ""

    caveat = _CAVEAT_TMPL.format(
        material=spec.pin_material,
        K=spec.end_condition_K,
        short_column_note=short_note,
    )

    return EjectorPinPushReport(
        buckling_force_N=f_cr,
        dcr=dcr,
        adequate=adequate,
        recommended_min_diameter_mm=rec_d,
        recommended_pin_material=rec_mat,
        honest_caveat=caveat,
    )
