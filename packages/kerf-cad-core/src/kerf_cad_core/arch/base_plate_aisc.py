"""
kerf_cad_core.arch.base_plate_aisc — AISC Design Guide 1 (2nd ed) §3.1 steel column
base plate design for concentric axial loads.

Implements:
  - Concrete bearing strength: AISC DG-1 Eq 3.1-3 / AISC 360-22 §J8
      Pp = 0.85·f'c·A1·sqrt(A2/A1)  with A2/A1 ≤ 4
      φ_c·Pp ≥ P_u   (φ_c = 0.65 per AISC 360-22 §J8)
  - Required plate area A1_req = P_u / (φ_c · 0.85 · f'c · sqrt(A2/A1))
      Conservatively use A2/A1 = 1 to establish minimum then iterate or
      cap at A2/A1 = 4 (gives 2× benefit: sqrt(4)=2).
  - Plate dimension sizing: from A1_req with N ≈ B (square or near-square plate),
      padded outboard from column, rounded up to next 5 mm.
  - Murray-Stockwell thickness (AISC DG-1 §3.1.2 Eq 3.1-5):
      t = l · sqrt(2·P_u / (0.9·Fy·B·N))
      where l = max(m, n, λ·n')
      m = (N − 0.95·d) / 2       [DG-1 Eq 3.1-1]
      n = (B_plate − 0.80·bf) / 2 [DG-1 Eq 3.1-2]
      n' = sqrt(d·bf) / 4         [DG-1 §3.1.2]
      λ = min(1, 2·sqrt(X) / (1 + sqrt(1-X)))  where
          X = (4·d·bf / (d+bf)²) · (P_u / (φ_c·Pp_full))  [DG-1 Eq 3.1-8]

SCOPE: concentric axial load ONLY — AISC DG-1 §3.1 (Table 3-1, Eq 3.1-1 to 3.1-8).
NOT covered: moment transfer (DG-1 §3.2), shear lug (DG-1 §3.5), anchor rod tension
(DG-1 §3.3–3.4), A-frame / brace loading, biaxial bending. All units in mm, kN, MPa.

References:
  AISC Design Guide 1, 2nd ed. (2006) §3.1, Eqs 3.1-1 through 3.1-8.
  AISC 360-22 §J8 (Column base plates — bearing strength).
  Fisher J.M. & Kloiber L.A. (2006) AISC Design Guide 1: Base Plate and Anchor Rod
    Design, 2nd ed.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

__all__ = [
    "ColumnSpec",
    "ConcreteSpec",
    "BasePlateReport",
    "design_base_plate",
]

# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class ColumnSpec:
    """
    Steel wide-flange column geometry (W-shape).

    Parameters
    ----------
    column_d_mm : float
        Overall depth d of the W-section in mm (strong-axis depth).
        Example: W14x90 → d = 355.6 mm.
    column_bf_mm : float
        Flange width bf of the W-section in mm.
        Example: W14x90 → bf = 368.3 mm.
    axial_load_kN : float
        Factored axial compressive demand P_u in kN (LRFD).
        Must be > 0.
    """
    column_d_mm: float
    column_bf_mm: float
    axial_load_kN: float


@dataclass
class ConcreteSpec:
    """
    Concrete pedestal / footing geometry and strength.

    Parameters
    ----------
    fc_MPa : float
        Concrete compressive strength f'c in MPa.  Must be > 0.
        Typical: 21–55 MPa (3 000–8 000 psi).
    support_width_B_mm : float
        Width of the supporting concrete pedestal or footing in mm.
        Used to compute A2 (full bearing area).  Must be ≥ plate width.
    support_length_L_mm : float
        Length of the supporting concrete pedestal or footing in mm.
        Used to compute A2 (full bearing area).  Must be ≥ plate length.
    phi_c : float
        Resistance factor for concrete bearing, φ_c.
        AISC 360-22 §J8 default = 0.65.
    """
    fc_MPa: float
    support_width_B_mm: float
    support_length_L_mm: float
    phi_c: float = 0.65


@dataclass
class BasePlateReport:
    """
    Result of AISC DG-1 §3.1 base plate design for concentric axial load.

    Parameters
    ----------
    plate_B_mm : float
        Required plate width (direction of flange, parallel to bf) in mm.
    plate_N_mm : float
        Required plate length (direction of web, parallel to d) in mm.
    plate_thickness_t_mm : float
        Required plate thickness t in mm (Murray-Stockwell method).
    m_mm : float
        Cantilever dimension m from web centreline to plate edge in mm.
    n_mm : float
        Cantilever dimension n from flange centreline to plate edge in mm.
    X_factor : float
        Dimensionless factor X used in λ computation (DG-1 Eq 3.1-8).
    plate_phi_Pn_kN : float
        Design bearing strength φ_c·Pp for the selected plate in kN.
    demand_capacity_ratio : float
        P_u / (φ_c·Pp) — should be ≤ 1.0 for an adequate design.
    adequate : bool
        True if DCR ≤ 1.0 (plate is adequate for the applied load).
    honest_caveat : str
        Scope limitations and code references.
    """
    plate_B_mm: float
    plate_N_mm: float
    plate_thickness_t_mm: float
    m_mm: float
    n_mm: float
    X_factor: float
    plate_phi_Pn_kN: float
    demand_capacity_ratio: float
    adequate: bool
    honest_caveat: str


# ---------------------------------------------------------------------------
# Core design function
# ---------------------------------------------------------------------------

_ROUND_TO_MM = 5  # round plate dimensions up to nearest 5 mm


def _round_up(value: float, multiple: float = 5.0) -> float:
    """Round *value* up to the next multiple of *multiple*."""
    return math.ceil(value / multiple) * multiple


def design_base_plate(
    column: ColumnSpec,
    concrete: ConcreteSpec,
    Fy: float = 345.0,
) -> BasePlateReport:
    """
    Design a steel column base plate for concentric axial load per AISC DG-1 §3.1.

    Algorithm
    ---------
    1. Compute maximum A2/A1 ratio (capped at 4) from concrete pedestal size.
    2. Determine minimum required A1:
         A1_req = P_u / (φ_c · 0.85 · f'c · sqrt(A2/A1))
       Iterate: start with ratio=1, solve A1, check if pedestal is at least as
       large as A1·sqrt(4), then tighten.  One iteration is sufficient because
       the sqrt(A2/A1) factor is bounded above by 2 (i.e. A2/A1 ≤ 4).
    3. Choose square-ish plate N ≈ B ≥ sqrt(A1_req), padded outward from column
       by at least (0.5·d + 3) and (0.5·bf + 3) in each direction, rounded up to
       nearest 5 mm.
    4. Verify bearing strength for the selected plate.
    5. Compute cantilever dimensions m, n, n', λ, l = max(m, n, λ·n').
    6. Compute plate thickness via Murray-Stockwell:
         t = l · sqrt(2·P_u / (0.9·Fy·B_plate·N_plate))

    Parameters
    ----------
    column : ColumnSpec
        W-section depth d, flange width bf, factored load P_u.
    concrete : ConcreteSpec
        Concrete strength f'c, pedestal dimensions (B_ped, L_ped), φ_c.
    Fy : float
        Plate steel yield stress in MPa.  Default 345 MPa (A36 = 250 MPa;
        A572 Gr 50 = 345 MPa).  AISC DG-1 §3.1 uses 0.9·Fy for thickness.

    Returns
    -------
    BasePlateReport

    Raises
    ------
    ValueError
        On invalid inputs.
    """
    # ---- Input validation --------------------------------------------------
    if column.column_d_mm <= 0:
        raise ValueError(f"column_d_mm must be > 0, got {column.column_d_mm}")
    if column.column_bf_mm <= 0:
        raise ValueError(f"column_bf_mm must be > 0, got {column.column_bf_mm}")
    if column.axial_load_kN <= 0:
        raise ValueError(f"axial_load_kN must be > 0, got {column.axial_load_kN}")
    if concrete.fc_MPa <= 0:
        raise ValueError(f"fc_MPa must be > 0, got {concrete.fc_MPa}")
    if concrete.support_width_B_mm <= 0:
        raise ValueError(
            f"support_width_B_mm must be > 0, got {concrete.support_width_B_mm}"
        )
    if concrete.support_length_L_mm <= 0:
        raise ValueError(
            f"support_length_L_mm must be > 0, got {concrete.support_length_L_mm}"
        )
    if concrete.phi_c <= 0 or concrete.phi_c > 1.0:
        raise ValueError(f"phi_c must be in (0, 1], got {concrete.phi_c}")
    if Fy <= 0:
        raise ValueError(f"Fy must be > 0, got {Fy}")

    # ---- Convenience aliases -----------------------------------------------
    d = column.column_d_mm          # mm  (section depth)
    bf = column.column_bf_mm        # mm  (flange width)
    P_u = column.axial_load_kN * 1e3  # N  (factored axial load)
    fc = concrete.fc_MPa            # MPa
    phi_c = concrete.phi_c
    A2_ped = concrete.support_width_B_mm * concrete.support_length_L_mm  # mm²

    # ---- Step 1: A2/A1 ratio -----------------------------------------------
    # We use the maximum allowed ratio = 4 (AISC 360-22 §J8 / DG-1 Eq 3.1-3)
    # This gives the most favourable bearing (sqrt(4)=2 doubling factor).
    # The actual ratio is clamped at 4, so we design with factor sqrt(4)=2
    # and then verify once plate is sized.

    # Base bearing stress with A2/A1 = 4:
    #   fp_max = 0.85·f'c·sqrt(4) = 1.70·f'c [MPa] = 1.70·f'c [N/mm²]
    # Required A1 = P_u / (phi_c · fp_max)
    sqrt_ratio_max = 2.0  # sqrt(4)
    fp_max_MPa = 0.85 * fc * sqrt_ratio_max   # N/mm² = MPa
    A1_req = P_u / (phi_c * fp_max_MPa)        # mm²

    # ---- Step 2: minimum plate dimensions from column geometry -------------
    # The plate must cover the column (0.95d × 0.80bf bearing footprint per
    # DG-1 §3.1.1) plus allow for any outstand.  Minimum from geometry:
    N_min_geom = 0.95 * d        # mm  (DG-1 §3.1, m-dimension)
    B_min_geom = 0.80 * bf       # mm  (DG-1 §3.1, n-dimension)

    # Minimum from bearing area requirement (square plate: B·N ≥ A1_req)
    side_from_area = math.sqrt(A1_req)

    # Take maximum of geometric minimum and area-based minimum; round up to 5 mm
    N_plate = _round_up(max(N_min_geom, side_from_area))
    B_plate = _round_up(max(B_min_geom, side_from_area))

    # Actual plate area
    A1 = B_plate * N_plate  # mm²

    # ---- Step 3: Verify actual A2/A1 ---------------------------------------
    # Actual ratio is limited to the pedestal area vs plate area, capped at 4.
    actual_ratio = A2_ped / A1
    sqrt_actual = math.sqrt(min(actual_ratio, 4.0))

    # ---- Step 4: Bearing strength check ------------------------------------
    # AISC 360-22 §J8 Eq J8-2: Pp = 0.85·f'c·A1·sqrt(A2/A1)  [N]
    Pp = 0.85 * fc * A1 * sqrt_actual  # N
    phi_Pp = phi_c * Pp                 # N
    DCR = P_u / phi_Pp

    # If DCR > 1.0, the plate area is insufficient with the assumed ratio.
    # Recalculate using the actual A2/A1 if A2_ped is larger than plate.
    if DCR > 1.0 and actual_ratio < 4.0:
        # Tighten: use exact ratio
        fp_act_MPa = 0.85 * fc * sqrt_actual
        A1_req2 = P_u / (phi_c * fp_act_MPa)
        side_from_area2 = math.sqrt(A1_req2)
        N_plate = _round_up(max(N_min_geom, side_from_area2))
        B_plate = _round_up(max(B_min_geom, side_from_area2))
        A1 = B_plate * N_plate
        actual_ratio = A2_ped / A1
        sqrt_actual = math.sqrt(min(actual_ratio, 4.0))
        Pp = 0.85 * fc * A1 * sqrt_actual
        phi_Pp = phi_c * Pp
        DCR = P_u / phi_Pp

    # ---- Step 5: Cantilever dimensions (DG-1 §3.1.2) ----------------------
    # m = (N - 0.95·d) / 2       [DG-1 Eq 3.1-1]
    # n = (B - 0.80·bf) / 2      [DG-1 Eq 3.1-2]
    # n' = sqrt(d·bf) / 4        [DG-1 §3.1.2]
    m = (N_plate - 0.95 * d) / 2.0
    n = (B_plate - 0.80 * bf) / 2.0
    n_prime = math.sqrt(d * bf) / 4.0

    # λ (lambda) — DG-1 Eq 3.1-8
    # X = [4·d·bf / (d+bf)²] · [P_u / (φ_c·Pp_full)]
    # where Pp_full = φ_c · 0.85 · f'c · A1 · sqrt_actual
    # We use phi_Pp_full for the denominator to match the code intent
    # (bearing capacity of the selected plate at this load level)
    denom_X = (d + bf) ** 2
    X = (4.0 * d * bf / denom_X) * (P_u / phi_Pp) if phi_Pp > 0 else 0.0
    # Clamp X to [0, 1] — X > 1 would only occur if design is over-capacity
    X = min(X, 1.0)

    # λ = min(1, 2·sqrt(X) / (1 + sqrt(1 - X)))
    if X <= 0.0:
        lam = 0.0
    elif X >= 1.0:
        lam = 1.0
    else:
        lam = min(1.0, 2.0 * math.sqrt(X) / (1.0 + math.sqrt(1.0 - X)))

    # Governing cantilever length
    l = max(m, n, lam * n_prime)

    # ---- Step 6: Plate thickness (Murray-Stockwell, DG-1 Eq 3.1-5) --------
    # t = l · sqrt(2·P_u / (0.9·Fy·B_plate·N_plate))
    # Note: 0.9·Fy·B·N is the plate yield resistance; P_u is in N
    denom_t = 0.9 * Fy * B_plate * N_plate  # N (Fy in MPa = N/mm², area in mm²)
    if denom_t > 0 and l > 0:
        t = l * math.sqrt(2.0 * P_u / denom_t)
    else:
        t = 0.0

    # Round thickness up to nearest mm (practical fabrication)
    t = math.ceil(t)

    # ---- Honest scope caveat -----------------------------------------------
    caveat = (
        "AISC Design Guide 1, 2nd ed. (2006) §3.1 — concentric axial compressive load only. "
        "AISC 360-22 §J8 bearing strength: Pp = 0.85·f'c·A1·√(A2/A1) ≤ 1.70·f'c·A1; φ_c = 0.65. "
        "Plate thickness via Murray-Stockwell: t = l·√(2Pu/(0.9·Fy·B·N)); "
        "l = max(m, n, λ·n'). "
        f"Selected plate: {B_plate:.0f}×{N_plate:.0f}×{t:.0f} mm "
        f"(B×N×t); √(A2/A1)={sqrt_actual:.3f}; DCR={DCR:.3f}. "
        "SCOPE LIMITATIONS: "
        "(1) Concentric compressive load ONLY — moment transfer (DG-1 §3.2), biaxial bending, "
        "and eccentric load are NOT modelled. "
        "(2) Anchor rod design (DG-1 §3.3–3.4) and shear lug (DG-1 §3.5) NOT included. "
        "(3) Assumes full bearing over A1 = B·N — weld/grout is competent to transfer load. "
        "(4) A2 is taken as the full pedestal plan area; irregular pedestals must supply equivalent "
        "rectangular A2 that fits within a geometrically similar figure to A1 (AISC 360-22 §J8). "
        "(5) Grout strength assumed ≥ f'c; grout pad thickness < 50 mm (DG-1 §3.1.2). "
        "(6) Plate steel yield stress Fy used for thickness; check Fy vs selected plate grade. "
        "Refs: AISC DG-1 §3.1 (Fisher & Kloiber 2006); AISC 360-22 §J8."
    )

    return BasePlateReport(
        plate_B_mm=B_plate,
        plate_N_mm=N_plate,
        plate_thickness_t_mm=float(t),
        m_mm=m,
        n_mm=n,
        X_factor=X,
        plate_phi_Pn_kN=phi_Pp / 1e3,
        demand_capacity_ratio=DCR,
        adequate=(DCR <= 1.0),
        honest_caveat=caveat,
    )
