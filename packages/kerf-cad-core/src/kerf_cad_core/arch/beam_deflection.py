"""
kerf_cad_core.arch.beam_deflection — Architectural beam deflection and moment check.

Implements closed-form Euler-Bernoulli beam deflection formulas for six
common structural load cases, referenced against:
  Roark's Formulas for Stress and Strain, 9th edition, §8 (Young, Budynas, Sadegh 2020)
  AISC Steel Construction Manual, 15th ed., Table 3-23

Supported cases:

  simply_supported + point_center:
      δ_max = P·L³ / (48·E·I)          at mid-span     [Roark Table 8.1, case 7]
      M_max = P·L / 4                    at mid-span

  simply_supported + udl (uniform distributed load):
      δ_max = 5·w·L⁴ / (384·E·I)       at mid-span     [Roark Table 8.1, case 2]
      M_max = w·L² / 8                   at mid-span

  cantilever + point_center (= point load at free tip):
      δ_max = P·L³ / (3·E·I)            at free tip     [Roark Table 8.1, case 1]
      M_max = P·L                         at fixed support

  cantilever + udl:
      δ_max = w·L⁴ / (8·E·I)            at free tip     [Roark Table 8.1, case 3]
      M_max = w·L² / 2                    at fixed support

  fixed_fixed + udl:
      δ_max = w·L⁴ / (384·E·I)          at mid-span     [Roark Table 8.1, case 15]
      M_max = w·L² / 12                   at supports (hogging)

  fixed_fixed + point_center:
      δ_max = P·L³ / (192·E·I)          at mid-span     [Roark Table 8.1, case 8]
      M_support = -P·L / 8               at each fixed support (hogging, governing)
      M_center  =  P·L / 8               at load point (sagging)
      δ(x) = P·x²·(3L−4x) / (48·E·I)   for 0 ≤ x ≤ L/2; symmetric about mid-span

All dimensions in **millimetres**, forces in **Newtons**, stresses in **MPa**.

Scope and caveats
-----------------
  • Linear-elastic, small-deflection, Euler-Bernoulli (no shear deformation).
  • No material non-linearity; no yield check; no lateral-torsional buckling.
  • Shear deformation (Timoshenko correction) omitted.
  • Only the five classic closed-form cases above — partial-span loads, patches,
    multiple loads, prestress, and temperature require a different solver.
  • V_max reported from simple statics (P/2 or w·L/2 for SS; P or w·L for cantilever).

References
----------
  Roark, R.J., Budynas, R.G., Sadegh, A.M. (2020). Roark's Formulas for Stress
    and Strain, 9th ed. McGraw-Hill. Chapter 8 "Beams; Flexure of Straight Bars".
  AISC (2017). Steel Construction Manual, 15th ed. Table 3-23 "Shears, Moments,
    and Deflections".
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

__all__ = [
    "BeamSpec",
    "BeamDeflectionReport",
    "compute_beam_deflection",
]

# ---------------------------------------------------------------------------
# Supported enumerations
# ---------------------------------------------------------------------------

_VALID_SUPPORT_TYPES = frozenset({"simply_supported", "cantilever", "fixed_fixed"})
_VALID_LOAD_TYPES = frozenset({"point_center", "udl"})


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class BeamSpec:
    """
    Geometry, material, and loading for a single-span beam.

    Parameters
    ----------
    length_mm : float
        Clear span length in mm. Must be > 0.
    E_MPa : float
        Elastic (Young's) modulus in MPa. Typical: 200 000 MPa (steel),
        70 000 MPa (aluminium), 12 000–16 000 MPa (structural timber LVL).
    I_mm4 : float
        Second moment of area (moment of inertia) about the bending axis in mm⁴.
        Must be > 0.
    support_type : str
        Boundary conditions:
          "simply_supported" — pin at each end (rotation free, no moment).
          "cantilever"       — fully fixed at one end, free at the other.
          "fixed_fixed"      — fully fixed at both ends (propped/encastré).
    load_type : str
        Loading pattern:
          "point_center" — single point load P (N) applied at mid-span (SS / fixed-fixed)
                           or at the free tip (cantilever).
          "udl"          — uniform distributed load w (N/mm) over full span.
    load_value : float
        Magnitude of the applied load.
          • "point_center": total point load P in Newtons (N). Must be ≥ 0.
          • "udl": uniform load intensity w in N/mm. Must be ≥ 0.
    """
    length_mm: float
    E_MPa: float
    I_mm4: float
    support_type: str
    load_type: str
    load_value: float


@dataclass
class BeamDeflectionReport:
    """
    Output of a beam deflection calculation.

    Parameters
    ----------
    delta_max_mm : float
        Maximum mid-span (or tip, for cantilever) deflection in mm.
        Positive = downward.
    M_max_Nmm : float
        Maximum bending moment in N·mm.
        For simply-supported spans: hogging (span centre or quarter-point).
        For cantilever: at the fixed support (hogging).
        For fixed-fixed UDL: at the supports (hogging); mid-span sagging
        moment = w·L²/24 (not reported here — use honest_caveat).
    V_max_N : float
        Maximum shear force in N (absolute value). For symmetric cases = reaction.
    deflection_location_mm : float
        Distance from the left support (or fixed end for cantilever) at which
        δ_max occurs, in mm.
    honest_caveat : str
        Plain-language scope statement: references, assumptions, what is
        NOT checked.
    """
    delta_max_mm: float
    M_max_Nmm: float
    V_max_N: float
    deflection_location_mm: float
    honest_caveat: str


# ---------------------------------------------------------------------------
# Core computation
# ---------------------------------------------------------------------------

def compute_beam_deflection(spec: BeamSpec) -> BeamDeflectionReport:
    """
    Compute mid-span deflection, maximum moment, and shear for a single-span beam.

    Parameters
    ----------
    spec : BeamSpec
        Beam geometry, material, support, and load specification.

    Returns
    -------
    BeamDeflectionReport

    Raises
    ------
    ValueError
        If any required parameter is invalid (non-positive L / E / I,
        negative load, or unrecognised support/load type).

    Notes
    -----
    Euler-Bernoulli linear-elastic closed-form only. No shear deformation,
    no buckling, no yield, no partial-span loads.
    """
    # --- Input validation ------------------------------------------------
    if spec.length_mm <= 0.0:
        raise ValueError(f"length_mm must be > 0, got {spec.length_mm}")
    if spec.E_MPa <= 0.0:
        raise ValueError(f"E_MPa must be > 0, got {spec.E_MPa}")
    if spec.I_mm4 <= 0.0:
        raise ValueError(f"I_mm4 must be > 0, got {spec.I_mm4}")
    if spec.load_value < 0.0:
        raise ValueError(f"load_value must be ≥ 0, got {spec.load_value}")
    if spec.support_type not in _VALID_SUPPORT_TYPES:
        raise ValueError(
            f"support_type must be one of {sorted(_VALID_SUPPORT_TYPES)}, "
            f"got {spec.support_type!r}"
        )
    if spec.load_type not in _VALID_LOAD_TYPES:
        raise ValueError(
            f"load_type must be one of {sorted(_VALID_LOAD_TYPES)}, "
            f"got {spec.load_type!r}"
        )

    L = spec.length_mm
    E = spec.E_MPa
    I = spec.I_mm4
    EI = E * I

    # ---- Case dispatch --------------------------------------------------

    support = spec.support_type
    load = spec.load_type
    val = spec.load_value  # P [N] or w [N/mm]

    if support == "simply_supported" and load == "point_center":
        # Roark 9e Table 8.1 case 7 (centre point load, SS beam)
        # AISC Table 3-23 diagram 1
        P = val
        delta_max = (P * L ** 3) / (48.0 * EI)   # mm
        M_max = (P * L) / 4.0                      # N·mm
        V_max = P / 2.0                             # N
        x_delta = L / 2.0
        case_desc = "simply-supported + centre point load P"
        refs = "Roark 9e §8 Table 8.1 case 7; AISC Manual Table 3-23 diagram 1"
        caveats = (
            "δ=PL³/(48EI), M=PL/4. "
            "Linear-elastic Euler-Bernoulli; no shear deformation (Timoshenko), "
            "no lateral-torsional buckling, no yield check."
        )

    elif support == "simply_supported" and load == "udl":
        # Roark 9e Table 8.1 case 2 (UDL, SS beam)
        # AISC Table 3-23 diagram 2
        w = val
        delta_max = (5.0 * w * L ** 4) / (384.0 * EI)   # mm
        M_max = (w * L ** 2) / 8.0                         # N·mm
        V_max = w * L / 2.0                                 # N
        x_delta = L / 2.0
        case_desc = "simply-supported + UDL w"
        refs = "Roark 9e §8 Table 8.1 case 2; AISC Manual Table 3-23 diagram 2"
        caveats = (
            "δ=5wL⁴/(384EI), M=wL²/8. "
            "Linear-elastic Euler-Bernoulli; no shear deformation, "
            "no buckling, no yield check."
        )

    elif support == "cantilever" and load == "point_center":
        # 'point_center' for cantilever means point load at the free tip.
        # Roark 9e Table 8.1 case 1 (cantilever + tip point load)
        P = val
        delta_max = (P * L ** 3) / (3.0 * EI)   # mm at free tip
        M_max = P * L                              # N·mm at fixed support
        V_max = P                                  # N at fixed support
        x_delta = L   # deflection at free tip (distance from fixed end)
        case_desc = "cantilever + tip point load P"
        refs = "Roark 9e §8 Table 8.1 case 1; AISC Manual Table 3-23 diagram 6"
        caveats = (
            "δ=PL³/(3EI) at free tip, M=PL at fixed support. "
            "'point_center' maps to tip load for cantilever spans. "
            "Linear-elastic Euler-Bernoulli; no shear deformation, "
            "no buckling, no yield check."
        )

    elif support == "cantilever" and load == "udl":
        # Roark 9e Table 8.1 case 3 (cantilever + UDL)
        w = val
        delta_max = (w * L ** 4) / (8.0 * EI)   # mm at free tip
        M_max = (w * L ** 2) / 2.0               # N·mm at fixed support
        V_max = w * L                              # N
        x_delta = L
        case_desc = "cantilever + UDL w"
        refs = "Roark 9e §8 Table 8.1 case 3; AISC Manual Table 3-23 diagram 7"
        caveats = (
            "δ=wL⁴/(8EI) at free tip, M=wL²/2 at fixed support. "
            "Linear-elastic Euler-Bernoulli; no shear deformation, "
            "no buckling, no yield check."
        )

    elif support == "fixed_fixed" and load == "udl":
        # Roark 9e Table 8.1 case 15 (fixed-fixed + UDL)
        # AISC Manual Table 3-23 diagram 9
        w = val
        delta_max = (w * L ** 4) / (384.0 * EI)   # mm at mid-span
        # M_max at supports (hogging) = wL²/12; mid-span sagging = wL²/24
        M_max = (w * L ** 2) / 12.0               # N·mm (at supports, governing)
        V_max = w * L / 2.0                         # N
        x_delta = L / 2.0
        case_desc = "fixed-fixed + UDL w"
        refs = "Roark 9e §8 Table 8.1 case 15; AISC Manual Table 3-23 diagram 9"
        caveats = (
            "δ=wL⁴/(384EI) at mid-span, M_support=wL²/12 (hogging, governs), "
            "M_midspan=wL²/24 (sagging, not reported). "
            "Linear-elastic Euler-Bernoulli; no shear deformation, "
            "no buckling, no yield check."
        )

    elif support == "fixed_fixed" and load == "point_center":
        # Roark 9e Table 8.1 case 8 (fixed-fixed beam, centre point load P)
        # AISC Manual Table 3-23 diagram 8
        # Reactions: R = P/2 at each support.
        # Max deflection at centre: δ_max = P·L³ / (192·E·I)
        # Fixed-end moment (hogging, governing): M_support = -P·L / 8
        # Mid-span sagging moment:               M_center  =  P·L / 8
        # Max shear: V_max = P/2
        # Deflection profile (0 ≤ x ≤ L/2):
        #   δ(x) = P·x²·(3L − 4x) / (48·E·I)
        # (symmetric: δ(L−x) = δ(x))
        P = val
        delta_max = (P * L ** 3) / (192.0 * EI)   # mm at mid-span
        # M_max_Nmm is reported as absolute value of governing moment (support hogging)
        M_max = (P * L) / 8.0                      # N·mm (magnitude; hogging at supports)
        V_max = P / 2.0                             # N
        x_delta = L / 2.0
        case_desc = "fixed-fixed + centre point load P"
        refs = "Roark 9e §8 Table 8.1 case 8; AISC Manual Table 3-23 diagram 8"
        caveats = (
            "δ_max=PL³/(192EI) at mid-span, M_support=−PL/8 (hogging, governs), "
            "M_center=PL/8 (sagging, not reported separately). "
            "Deflection profile: δ(x)=Px²(3L−4x)/(48EI) for 0≤x≤L/2, symmetric. "
            "R=P/2 at each support. "
            "Linear-elastic Euler-Bernoulli; no shear deformation, "
            "no buckling, no yield check."
        )

    else:
        # Should not reach here given prior validation, but be explicit.
        raise ValueError(
            f"Unhandled case: support_type={spec.support_type!r}, "
            f"load_type={spec.load_type!r}."
        )

    # ---- Build caveat ---------------------------------------------------
    honest_caveat = (
        f"ARCH-BEAM-DEFLECTION: {case_desc}. "
        f"Ref: {refs}. "
        f"{caveats} "
        f"L={L:.1f} mm, E={E:.0f} MPa, I={I:.4g} mm⁴, "
        f"load={'P='+str(val)+' N' if load=='point_center' else 'w='+str(val)+' N/mm'}. "
        f"Results: δ_max={delta_max:.4g} mm, M_max={M_max:.4g} N·mm, V_max={V_max:.4g} N. "
        f"SCOPE: linear-elastic only. No yield/buckling/shear-deformation/partial-span-loads."
    )

    return BeamDeflectionReport(
        delta_max_mm=delta_max,
        M_max_Nmm=M_max,
        V_max_N=V_max,
        deflection_location_mm=x_delta,
        honest_caveat=honest_caveat,
    )
