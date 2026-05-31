"""
kerf_cad_core.arch.punching_shear — ACI 318-19 §22.6 two-way (punching) shear.

Checks punching shear capacity of a flat concrete slab around a column per
ACI 318-19 §22.6 (Two-way shear strength) with no shear reinforcement (Vs = 0).

Critical section perimeter b_0 is located at d/2 from the column face
(ACI 318-19 §22.6.4.1).

Governing concrete shear stress vc is the minimum of three ACI equations
(ACI 318-19 §22.6.5.2):
  (a)  vc = 0.33 · λ · √f'c
  (b)  vc = 0.17 · (1 + 2/β_c) · λ · √f'c   (aspect-ratio check)
  (c)  vc = 0.083 · (α_s · d/b_0 + 2) · λ · √f'c  (perimeter check)

where:
  β_c   = ratio of long-to-short column dimension (≥ 1)
  α_s   = 40 (interior), 30 (edge), 20 (corner)
  λ     = lightweight-concrete modification factor (default 1.0 normalweight)

Design strength:  φ·Vn = φ · vc · b_0 · d   (φ = 0.75 for shear per Table 21.2.1)

All units mm and MPa unless otherwise noted.  Output forces in kN.

References:
  ACI 318-19 §22.6.4 (critical section), §22.6.5 (vc equations), §22.6.3 (b_0)
  Wight J.K. (2019) *Reinforced Concrete: Mechanics and Design* 8e §13.10.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

__all__ = [
    "ColumnSlabSpec",
    "PunchingShearReport",
    "check_punching_shear",
]

# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class ColumnSlabSpec:
    """
    Column and slab geometry for ACI 318-19 §22.6 punching shear check.

    Parameters
    ----------
    column_size_mm : float
        Side dimension of square column (mm), or diameter of circular column,
        or short side of rectangular column.  Must be > 0.
    slab_thickness_mm : float
        Overall slab thickness h (mm).  Must be > 0.
    fc_MPa : float
        Specified compressive strength of concrete f'c (MPa).  Must be > 0.
        ACI 318-19 §22.6.5.1 caps √f'c at √69 MPa (≈8.31 MPa) for normal-
        weight concrete; this limit is NOT enforced here — flag in caveat.
    effective_depth_d_mm : float
        Effective depth d to the tension reinforcement (mm).  Must be > 0 and
        < slab_thickness_mm.
    column_shape : str
        One of ``"square"``, ``"rectangular"``, ``"circular"``.
    column_width_b_mm : float | None
        Long-side dimension of a rectangular column (mm).  Required when
        column_shape == "rectangular".  Must be ≥ column_size_mm.
    alpha_s : int
        ACI α_s factor: 40 = interior column, 30 = edge column, 20 = corner
        column (ACI 318-19 §22.6.5.2c).  Default 40 (interior).
    lambda_factor : float
        Lightweight-concrete modification factor λ per ACI 318-19 §19.2.4.
        Default 1.0 (normalweight concrete).
    """
    column_size_mm: float
    slab_thickness_mm: float
    fc_MPa: float
    effective_depth_d_mm: float
    column_shape: str
    column_width_b_mm: float | None = None
    alpha_s: int = 40
    lambda_factor: float = 1.0


@dataclass
class PunchingShearReport:
    """
    Output of ACI 318-19 §22.6 punching shear check.

    Parameters
    ----------
    b_0_mm : float
        Critical-section perimeter b_0 at d/2 from column face (mm).
    vc_basic_MPa : float
        vc from the basic equation (a): 0.33·λ·√f'c (MPa).
    vc_aspect_MPa : float
        vc from the aspect-ratio equation (b): 0.17·(1+2/β_c)·λ·√f'c (MPa).
    vc_perimeter_MPa : float
        vc from the perimeter equation (c): 0.083·(α_s·d/b_0+2)·λ·√f'c (MPa).
    vc_governing_MPa : float
        Minimum of (a), (b), (c) — governs the design (MPa).
    phi_vc_kN : float
        LRFD design punching shear strength φ·vc·b_0·d in kN.
    demand_capacity_ratio : float
        V_applied / φ·Vn.  ≤ 1.0 = adequate.
    adequate : bool
        True when demand_capacity_ratio ≤ 1.0.
    governing_eqn : str
        Label of the ACI equation that governs:
        "basic", "aspect-ratio", or "perimeter".
    honest_caveat : str
        Scope caveats and limitations.
    """
    b_0_mm: float
    vc_basic_MPa: float
    vc_aspect_MPa: float
    vc_perimeter_MPa: float
    vc_governing_MPa: float
    phi_vc_kN: float
    demand_capacity_ratio: float
    adequate: bool
    governing_eqn: str
    honest_caveat: str


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------

_VALID_SHAPES = frozenset({"square", "rectangular", "circular"})


def _validate_spec(spec: ColumnSlabSpec) -> None:
    """Raise ValueError on invalid inputs."""
    if spec.column_shape not in _VALID_SHAPES:
        raise ValueError(
            f"column_shape must be one of {sorted(_VALID_SHAPES)}, "
            f"got '{spec.column_shape}'"
        )
    if spec.column_size_mm <= 0:
        raise ValueError(
            f"column_size_mm must be > 0, got {spec.column_size_mm}"
        )
    if spec.slab_thickness_mm <= 0:
        raise ValueError(
            f"slab_thickness_mm must be > 0, got {spec.slab_thickness_mm}"
        )
    if spec.fc_MPa <= 0:
        raise ValueError(f"fc_MPa must be > 0, got {spec.fc_MPa}")
    if spec.effective_depth_d_mm <= 0:
        raise ValueError(
            f"effective_depth_d_mm must be > 0, got {spec.effective_depth_d_mm}"
        )
    if spec.effective_depth_d_mm >= spec.slab_thickness_mm:
        raise ValueError(
            f"effective_depth_d_mm ({spec.effective_depth_d_mm}) must be "
            f"< slab_thickness_mm ({spec.slab_thickness_mm})"
        )
    if spec.column_shape == "rectangular":
        if spec.column_width_b_mm is None:
            raise ValueError(
                "column_width_b_mm is required for rectangular columns"
            )
        if spec.column_width_b_mm < spec.column_size_mm:
            raise ValueError(
                f"column_width_b_mm ({spec.column_width_b_mm}) must be "
                f">= column_size_mm ({spec.column_size_mm}) — "
                "column_size_mm is the short side, column_width_b_mm is the long side"
            )
    if spec.alpha_s not in (40, 30, 20):
        raise ValueError(
            f"alpha_s must be 40 (interior), 30 (edge), or 20 (corner), "
            f"got {spec.alpha_s}"
        )
    if spec.lambda_factor <= 0:
        raise ValueError(
            f"lambda_factor must be > 0, got {spec.lambda_factor}"
        )


# ---------------------------------------------------------------------------
# Critical-section perimeter b_0
# ---------------------------------------------------------------------------

def _compute_b0(spec: ColumnSlabSpec) -> tuple[float, float]:
    """
    Return (b_0_mm, beta_c) where b_0 is the ACI 318-19 §22.6.4.1
    critical-section perimeter at d/2 from the column face.

    For square:       b_0 = 4 · (c + d)
    For rectangular:  b_0 = 2 · (c1 + d) + 2 · (c2 + d)
                           = 2 · (c1 + c2 + 2·d)
                      β_c = c2 / c1  (long/short ≥ 1)
    For circular:     equiv. square side c_sq = diameter;
                      b_0 = π · (c + d)  per Wight §13.10 (circular perimeter)
    """
    c = spec.column_size_mm
    d = spec.effective_depth_d_mm

    if spec.column_shape == "square":
        b_0 = 4.0 * (c + d)
        beta_c = 1.0

    elif spec.column_shape == "rectangular":
        c2 = spec.column_width_b_mm  # long side (c2 >= c1)
        c1 = c                       # short side
        b_0 = 2.0 * (c1 + d) + 2.0 * (c2 + d)
        beta_c = c2 / c1  # ≥ 1

    else:  # circular
        # ACI 318-19 §22.6.4.2: for circular columns the critical section
        # perimeter is taken as a circle at d/2 from the column face.
        # b_0 = π · (diameter + d)
        b_0 = math.pi * (c + d)
        beta_c = 1.0

    return b_0, beta_c


# ---------------------------------------------------------------------------
# Core calculation
# ---------------------------------------------------------------------------

def check_punching_shear(
    spec: ColumnSlabSpec,
    V_applied_kN: float,
    phi: float = 0.75,
) -> PunchingShearReport:
    """
    Check two-way (punching) shear capacity per ACI 318-19 §22.6.

    The governing concrete shear stress vc is the **minimum** of
    ACI 318-19 §22.6.5.2 equations (a), (b), (c):

      (a)  vc = 0.33 · λ · √f'c                              [basic]
      (b)  vc = 0.17 · (1 + 2/β_c) · λ · √f'c               [aspect-ratio]
      (c)  vc = 0.083 · (α_s · d/b_0 + 2) · λ · √f'c        [perimeter]

    Design strength: φ·Vn = φ · vc · b_0 · d   (N → converted to kN)

    Parameters
    ----------
    spec : ColumnSlabSpec
        Column, slab, and material geometry.
    V_applied_kN : float
        Applied punching shear force V_u (kN).  Must be ≥ 0.
    phi : float
        ACI strength-reduction factor for shear.
        Default 0.75 per ACI 318-19 Table 21.2.1.

    Returns
    -------
    PunchingShearReport

    Raises
    ------
    ValueError
        On invalid geometry, material, or load parameters.
    """
    _validate_spec(spec)

    if V_applied_kN < 0:
        raise ValueError(
            f"V_applied_kN must be >= 0, got {V_applied_kN}"
        )
    if phi <= 0 or phi > 1.0:
        raise ValueError(f"phi must be in (0, 1], got {phi}")

    d = spec.effective_depth_d_mm
    fc = spec.fc_MPa
    lam = spec.lambda_factor
    alpha_s = spec.alpha_s

    sqrt_fc = math.sqrt(fc)

    b_0, beta_c = _compute_b0(spec)

    # -------------------------------------------------------------------------
    # ACI 318-19 §22.6.5.2 — three equations, all in MPa
    # -------------------------------------------------------------------------

    # (a) Basic equation
    vc_a = 0.33 * lam * sqrt_fc

    # (b) Aspect-ratio equation (β_c = long/short column side)
    # Note: for square/circular β_c = 1.0, so 1 + 2/β_c = 3.0 and
    # vc_b = 0.17·3·λ·√f'c = 0.51·λ·√f'c > vc_a → never governs for β_c≤2.
    vc_b = 0.17 * (1.0 + 2.0 / beta_c) * lam * sqrt_fc

    # (c) Perimeter/column-location equation
    vc_c = 0.083 * (alpha_s * d / b_0 + 2.0) * lam * sqrt_fc

    # Governing vc = min of (a), (b), (c)
    vc_values = {
        "basic": vc_a,
        "aspect-ratio": vc_b,
        "perimeter": vc_c,
    }
    governing_eqn = min(vc_values, key=lambda k: vc_values[k])
    vc_gov = vc_values[governing_eqn]

    # -------------------------------------------------------------------------
    # Design strength φ·Vn (kN)
    # -------------------------------------------------------------------------
    # Vn = vc · b_0 · d  [N]  (Vc only, no shear reinforcement)
    Vn_N = vc_gov * b_0 * d
    phi_Vn_kN = phi * Vn_N / 1_000.0  # N → kN

    # -------------------------------------------------------------------------
    # Demand/capacity ratio
    # -------------------------------------------------------------------------
    dcr = V_applied_kN / phi_Vn_kN if phi_Vn_kN > 0.0 else float("inf")
    adequate = dcr <= 1.0

    # -------------------------------------------------------------------------
    # Honest caveat
    # -------------------------------------------------------------------------
    caveat = (
        "ACI 318-19 §22.6 Two-way (punching) shear — "
        "Wight 'Reinforced Concrete: Mechanics and Design' 8e §13.10. "
        f"b_0 = {b_0:.1f} mm (critical perimeter at d/2 from column face); "
        f"d = {d:.1f} mm; f'c = {fc:.1f} MPa; β_c = {beta_c:.3f}; "
        f"α_s = {alpha_s}; λ = {lam}. "
        f"vc(a)={vc_a:.4f} MPa (basic), "
        f"vc(b)={vc_b:.4f} MPa (aspect-ratio), "
        f"vc(c)={vc_c:.4f} MPa (perimeter). "
        f"Governing vc = {vc_gov:.4f} MPa [{governing_eqn}]. "
        f"φ·Vn = {phi_Vn_kN:.2f} kN (φ={phi}). "
        f"V_applied = {V_applied_kN:.2f} kN → DCR = {dcr:.4f} "
        f"({'ADEQUATE' if adequate else 'INADEQUATE'}). "
        "SCOPE LIMITATIONS: "
        "(1) No shear reinforcement (Vs = 0); headed studs or stirrups not modelled — "
        "use ACI 318-19 §22.6.6 for shear-reinforced slabs. "
        "(2) Uniform perimeter assumed; slab openings, re-entrant corners, and "
        "column caps / drop panels not modelled (ACI §22.6.4.3). "
        "(3) Unbalanced moment transfer (moment-shear interaction γ_v effect, "
        "ACI §R8.4.4.2) not included — use ACI §8.4.4 with c_AB fractions. "
        "(4) No axial compression or tension effect on vc (ACI §22.6.5.5 / Table 22.6.5.3). "
        "(5) √f'c cap at √69 MPa (≈8.31 MPa) per ACI §22.6.5.1 is NOT "
        "automatically enforced — user must ensure f'c ≤ 69 MPa for code compliance. "
        "(6) Slab edge/corner geometry (reduced perimeter) not handled automatically "
        "— set α_s=30 (edge) or α_s=20 (corner) and reduce b_0 manually if needed. "
        "Always verify with licensed structural engineer."
    )

    return PunchingShearReport(
        b_0_mm=b_0,
        vc_basic_MPa=vc_a,
        vc_aspect_MPa=vc_b,
        vc_perimeter_MPa=vc_c,
        vc_governing_MPa=vc_gov,
        phi_vc_kN=phi_Vn_kN,
        demand_capacity_ratio=dcr,
        adequate=adequate,
        governing_eqn=governing_eqn,
        honest_caveat=caveat,
    )
