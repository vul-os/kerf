"""
kerf_cad_core.arch.slab_deflection — Two-way rectangular concrete slab deflection.

Implements closed-form center-point deflection for two-way rectangular slabs under
uniform load with all-edges-simply-supported (AESS) and all-edges-fixed (AEFC)
boundary conditions, using Kirchhoff thin-plate theory.

References
----------
  Timoshenko, S.P. & Woinowsky-Krieger, S. (1959).
    Theory of Plates and Shells, 2nd ed. McGraw-Hill.
    §44 (Table 41 — SS coefficients; Table 42 — fixed-edge coefficients).

  Roark, R.J., Budynas, R.G., Sadegh, A.M. (2020).
    Roark's Formulas for Stress and Strain, 9th ed. McGraw-Hill.
    Table 11.4 — rectangular plates, uniform load.

Formula
-------
  δ_max = α · q · a⁴ / D

  where:
    q   = uniform load intensity  [N/mm²] = [MPa]
    a   = shorter span             [mm]
    D   = E·h³ / (12·(1−ν²))     — plate flexural stiffness  [N·mm]
    α   = non-dimensional coefficient from Timoshenko Tables 41 / 42

Timoshenko Table 41 — simply-supported (AESS) α values, interpolated at ratio a/b:
  a/b = 1.0  → α = 0.00406
  a/b = 1.2  → α = 0.00564   (interpolated reference)
  a/b = 1.4  → α = 0.00668   (interpolated reference)
  a/b = 1.5  → α = 0.00772
  a/b = 1.6  → α = 0.00830   (interpolated reference)
  a/b = 2.0  → α = 0.01013
  a/b ≥ 3.0  → α = 0.01302   (one-way strip limit: 5/(384) × 1 = 0.013021)

Timoshenko Table 42 — fixed-fixed (AEFC) α values, ν = 0.3 tabulation:
  a/b = 1.0  → α = 0.00126

Moment coefficients (simply-supported, ν = 0.2, Timoshenko Table 41):
  β_x (M_x, along a-direction) at a/b = 1.0: 0.0479
  β_y (M_y, along b-direction) at a/b = 1.0: 0.0479
  M = β · q · a²  [N·mm/mm]

Scope and caveats
-----------------
  • Linear-elastic Kirchhoff thin-plate (small deflection, no shear deformation).
  • No shear deformation — Mindlin plate correction omitted (significant for h/a > ~0.1).
  • No plastic hinge redistribution; no cracking; no concrete creep / shrinkage.
  • Isotropic plate only; no orthotropic / ribbed slab equivalent stiffness.
  • Interpolation between tabulated a/b ratios uses linear interpolation on α.
  • a is defined as the shorter span; b is the longer span (a ≤ b always enforced).
  • Fixed-fixed case (AEFC): only a/b = 1.0 coefficient is tabulated here; for other
    ratios an approximate Kirchhoff series solution is used (Timoshenko §44 Table 42
    does not give a compact closed-form for the general case — the α_ff formula below
    is a monotone approximation anchored at a/b=1.0 with the correct one-way limit).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

__all__ = [
    "SlabSpec",
    "LoadSpec",
    "SlabDeflectionReport",
    "compute_slab_deflection",
]

# ---------------------------------------------------------------------------
# Timoshenko Table 41 — simply-supported (AESS) α, β_x, β_y
# Tabulated at discrete a/b ratios (a = shorter span, b = longer span)
# Reference: Timoshenko & Woinowsky-Krieger 2e Table 41 (ν = 0.2)
# ---------------------------------------------------------------------------

_SS_TABLE: list[tuple[float, float, float, float]] = [
    # (a/b,   alpha,    beta_x,  beta_y)
    (1.0,  0.00406,  0.0479,  0.0479),
    (1.1,  0.00485,  0.0554,  0.0493),
    (1.2,  0.00564,  0.0627,  0.0501),
    (1.3,  0.00638,  0.0694,  0.0503),
    (1.4,  0.00712,  0.0755,  0.0502),
    (1.5,  0.00772,  0.0812,  0.0498),
    (1.6,  0.00830,  0.0862,  0.0491),
    (1.7,  0.00883,  0.0908,  0.0484),
    (1.8,  0.00931,  0.0948,  0.0475),
    (1.9,  0.00974,  0.0985,  0.0466),
    (2.0,  0.01013,  0.1017,  0.0456),
    (3.0,  0.01223,  0.1189,  0.0384),
    (4.0,  0.01282,  0.1235,  0.0355),
    (5.0,  0.01297,  0.1246,  0.0348),
    (1e9,  0.01302,  0.1250,  0.0000),  # one-way strip limit
]

# Fixed-fixed (AEFC) tabulation — Timoshenko Table 42 (ν ≈ 0.3)
# Only a/b = 1.0 coefficient is precisely tabulated; the progression to
# the one-way fixed-fixed limit (α_ff_1way = 1/(384) = 0.002604) is
# approximated with the same shape as the SS curve, scaled by the ratio
# α_ff(1.0) / α_ss(1.0) at each tabulated SS point.
_FF_ALPHA_1 = 0.00126  # Timoshenko Table 42, a/b = 1.0, ν = 0.3
_SS_ALPHA_1 = 0.00406  # SS Table 41, a/b = 1.0
_FF_1WAY    = 1.0 / 384.0  # fixed-fixed one-way limit (w·L⁴/(384·EI) → α = 1/384)


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class SlabSpec:
    """
    Geometry and material specification for a two-way rectangular concrete slab.

    Parameters
    ----------
    length_a_mm : float
        Length of one side of the slab in mm. Together with width_b_mm, the
        shorter dimension is taken as span a (Timoshenko convention). Must be > 0.
    width_b_mm : float
        Length of the other side of the slab in mm. Must be > 0.
    thickness_h_mm : float
        Slab thickness h in mm. Must be > 0.
    E_MPa : float
        Elastic (Young's) modulus in MPa. Typical concrete: 25 000–35 000 MPa.
        Default 30 000 MPa (C25/30 Eurocode 2 E_cm ≈ 31 000 MPa).
    poisson : float
        Poisson's ratio ν. Typical concrete: 0.2 (Eurocode 2 §3.1.3; ACI 318-19).
        Default 0.2.
    """
    length_a_mm: float
    width_b_mm: float
    thickness_h_mm: float
    E_MPa: float
    poisson: float = 0.2


@dataclass
class LoadSpec:
    """
    Loading and boundary condition specification for a two-way slab.

    Parameters
    ----------
    udl_kPa : float
        Uniform distributed load in kPa (kN/m²). Must be ≥ 0.
    edge_condition : str
        Boundary condition for all four edges:
          "simply_supported" — all edges simply supported (AESS).
          "fixed_fixed"      — all edges fully fixed (AEFC).
    """
    udl_kPa: float
    edge_condition: str


@dataclass
class SlabDeflectionReport:
    """
    Output of a two-way slab deflection calculation.

    Parameters
    ----------
    delta_max_mm : float
        Maximum center-point deflection in mm. Positive = downward.
    location : str
        Description of where δ_max occurs (always center for rectangular slabs).
    M_max_xx_Nmm_per_mm : float
        Maximum bending moment per unit width in the x-direction (along span a)
        in N·mm/mm. For simply-supported slabs: Timoshenko Table 41 β_x · q · a².
        For fixed-fixed slabs: approximate center moment (not at support).
    M_max_yy_Nmm_per_mm : float
        Maximum bending moment per unit width in the y-direction (along span b)
        in N·mm/mm.
    plate_stiffness_D : float
        Plate flexural stiffness D = E·h³ / (12·(1−ν²)) in N·mm.
    honest_caveat : str
        Plain-language scope statement: references, assumptions, what is NOT checked.
    """
    delta_max_mm: float
    location: str
    M_max_xx_Nmm_per_mm: float
    M_max_yy_Nmm_per_mm: float
    plate_stiffness_D: float
    honest_caveat: str


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _interp_ss(ratio: float) -> tuple[float, float, float]:
    """
    Linearly interpolate Timoshenko Table 41 coefficients (α, β_x, β_y) at
    the given a/b ratio.  Clamps at ratio >= table maximum.

    Parameters
    ----------
    ratio : float
        a/b where a ≤ b (so ratio ≤ 1.0 ... wait, a is shorter span).

    Notes
    -----
    In Timoshenko's convention, a is the shorter span, so a/b ≤ 1. But Table 41
    actually tabulates the *inverse* ratio a_short / a_long which I call r = a/b ≤ 1.
    However, many sources (and Roark Table 11.4) list the ratio as a/b where a is the
    shorter dimension, giving r from 1.0 upward ... the table here is keyed by the
    ratio of SHORT to LONG span, meaning entries go from 1.0 (square) to ∞ (one-way).
    """
    table = _SS_TABLE
    if ratio <= table[0][0]:
        return table[0][1], table[0][2], table[0][3]
    if ratio >= table[-1][0]:
        return table[-1][1], table[-1][2], table[-1][3]
    # Linear interpolation
    for i in range(len(table) - 1):
        r0, a0, bx0, by0 = table[i]
        r1, a1, bx1, by1 = table[i + 1]
        if r0 <= ratio <= r1:
            t = (ratio - r0) / (r1 - r0)
            return (
                a0 + t * (a1 - a0),
                bx0 + t * (bx1 - bx0),
                by0 + t * (by1 - by0),
            )
    # Should not reach here
    return table[-1][1], table[-1][2], table[-1][3]  # pragma: no cover


def _alpha_ff(ratio: float) -> float:
    """
    Approximate fixed-fixed (AEFC) deflection coefficient α_ff at the given
    a/b ratio.

    Approach:
      • Anchored at a/b = 1.0: α_ff = 0.00126 (Timoshenko Table 42).
      • Anchored at a/b → ∞: α_ff → 1/384 ≈ 0.002604 (one-way fixed limit).
      • Intermediate values scaled from the SS curve:
          α_ff(r) = α_ss(r) × (α_ff(1.0) / α_ss(1.0))
        capped at the one-way fixed limit (α_ff never exceeds 1/384).
    This is a monotone approximation; exact values for intermediate ratios
    require the Timoshenko double-series solution (§44).
    """
    alpha_ss, _, _ = _interp_ss(ratio)
    # Scale SS coefficient by the FF/SS ratio at unit aspect ratio
    scale = _FF_ALPHA_1 / _SS_ALPHA_1
    alpha = alpha_ss * scale
    # Cap at one-way fixed-fixed limit
    return min(alpha, _FF_1WAY)


# ---------------------------------------------------------------------------
# Core computation
# ---------------------------------------------------------------------------

def compute_slab_deflection(slab: SlabSpec, load: LoadSpec) -> SlabDeflectionReport:
    """
    Compute center-point deflection and maximum moments for a two-way rectangular
    slab under uniform load using Kirchhoff thin-plate theory.

    Parameters
    ----------
    slab : SlabSpec
        Slab geometry and material specification.
    load : LoadSpec
        Load and boundary condition specification.

    Returns
    -------
    SlabDeflectionReport

    Raises
    ------
    ValueError
        If any required parameter is invalid (non-positive dimensions, negative
        load, or unrecognised edge_condition).

    Notes
    -----
    Formula: δ_max = α · q · a⁴ / D
    where a is the shorter plan dimension, D = E·h³/(12·(1−ν²)),
    q is the uniform load in N/mm², and α is the dimensionless Timoshenko
    coefficient for the given boundary condition and aspect ratio a/b.

    References: Timoshenko & Woinowsky-Krieger 2e §44 Tables 41–42;
                Roark 9e Table 11.4.
    """
    # ── Input validation ───────────────────────────────────────────────────
    if slab.length_a_mm <= 0.0:
        raise ValueError(f"length_a_mm must be > 0, got {slab.length_a_mm}")
    if slab.width_b_mm <= 0.0:
        raise ValueError(f"width_b_mm must be > 0, got {slab.width_b_mm}")
    if slab.thickness_h_mm <= 0.0:
        raise ValueError(f"thickness_h_mm must be > 0, got {slab.thickness_h_mm}")
    if slab.E_MPa <= 0.0:
        raise ValueError(f"E_MPa must be > 0, got {slab.E_MPa}")
    if not (0.0 < slab.poisson < 0.5):
        raise ValueError(f"poisson must be in (0, 0.5), got {slab.poisson}")
    if load.udl_kPa < 0.0:
        raise ValueError(f"udl_kPa must be ≥ 0, got {load.udl_kPa}")
    _VALID_EDGE = frozenset({"simply_supported", "fixed_fixed"})
    if load.edge_condition not in _VALID_EDGE:
        raise ValueError(
            f"edge_condition must be one of {sorted(_VALID_EDGE)}, "
            f"got {load.edge_condition!r}"
        )

    # ── Geometry setup ─────────────────────────────────────────────────────
    # Timoshenko: a = shorter span, b = longer span (a ≤ b)
    a_mm = min(slab.length_a_mm, slab.width_b_mm)
    b_mm = max(slab.length_a_mm, slab.width_b_mm)
    h    = slab.thickness_h_mm
    E    = slab.E_MPa
    nu   = slab.poisson

    # ── Plate flexural stiffness D = E·h³ / (12·(1−ν²)) [N·mm] ──────────
    D = (E * h ** 3) / (12.0 * (1.0 - nu ** 2))

    # ── Unit load conversion: q_kPa → q [N/mm²] ──────────────────────────
    # 1 kPa = 1 kN/m² = 0.001 N/mm²
    q_N_per_mm2 = load.udl_kPa * 1.0e-3  # [N/mm²]

    # Zero load → zero deflection
    if load.udl_kPa == 0.0:
        return SlabDeflectionReport(
            delta_max_mm=0.0,
            location="slab center",
            M_max_xx_Nmm_per_mm=0.0,
            M_max_yy_Nmm_per_mm=0.0,
            plate_stiffness_D=D,
            honest_caveat=_build_caveat(
                slab, load, a_mm, b_mm, D, 0.0, 0.0, 0.0, 0.0
            ),
        )

    # ── Aspect ratio r = a/b (≤ 1.0 when a is the shorter span) ──────────
    # Timoshenko Table 41 is indexed by the ratio SHORT/LONG = a/b ≤ 1.
    # When a = b (square), r = 1.0 exactly.
    r = a_mm / b_mm  # 0 < r ≤ 1.0

    # However, the table starts at r=1 and goes to ∞ (one-way strip).
    # Timoshenko's own table is indexed by b/a (≥1) in some editions and
    # a/b (≤1) in others. The α values above are keyed to b/a ≥ 1.
    # Let's use ratio = b/a = 1/r to look up the table (table runs from 1.0 upward).
    ratio = b_mm / a_mm  # ≥ 1.0

    # ── Deflection coefficient α ──────────────────────────────────────────
    if load.edge_condition == "simply_supported":
        alpha, beta_x, beta_y = _interp_ss(ratio)
        condition_desc = "all-edges-simply-supported (AESS)"
        ref_table = "Timoshenko Table 41"
    else:  # fixed_fixed
        alpha = _alpha_ff(ratio)
        # For fixed-fixed, the center moment is smaller than SS by similar ratio
        # Use same SS β scaled down, with honest caveat that these are approximate.
        _, beta_x_ss, beta_y_ss = _interp_ss(ratio)
        scale_m = _FF_ALPHA_1 / _SS_ALPHA_1
        beta_x = beta_x_ss * scale_m
        beta_y = beta_y_ss * scale_m
        condition_desc = "all-edges-fixed (AEFC)"
        ref_table = "Timoshenko Table 42 (a/b=1 exact; other ratios approx.)"

    # ── Center-point deflection: δ = α · q · a⁴ / D ──────────────────────
    delta_max_mm = alpha * q_N_per_mm2 * (a_mm ** 4) / D

    # ── Maximum moments per unit width: M = β · q · a² [N·mm/mm] ─────────
    M_xx = beta_x * q_N_per_mm2 * (a_mm ** 2)
    M_yy = beta_y * q_N_per_mm2 * (a_mm ** 2)

    # ── Build report ───────────────────────────────────────────────────────
    caveat = _build_caveat(slab, load, a_mm, b_mm, D, alpha, delta_max_mm, M_xx, M_yy)

    return SlabDeflectionReport(
        delta_max_mm=delta_max_mm,
        location="slab center (x=a/2, y=b/2)",
        M_max_xx_Nmm_per_mm=M_xx,
        M_max_yy_Nmm_per_mm=M_yy,
        plate_stiffness_D=D,
        honest_caveat=caveat,
    )


def _build_caveat(
    slab: SlabSpec,
    load: LoadSpec,
    a_mm: float,
    b_mm: float,
    D: float,
    alpha: float,
    delta: float,
    M_xx: float,
    M_yy: float,
) -> str:
    return (
        f"ARCH-SLAB-DEFLECTION: two-way rectangular slab, {load.edge_condition}. "
        f"Ref: Timoshenko & Woinowsky-Krieger 2e §44 Tables 41–42; Roark 9e Table 11.4. "
        f"Formula: delta=alpha*q*a^4/D; D=E*h^3/(12*(1-nu^2)). "
        f"a={a_mm:.1f} mm (shorter span), b={b_mm:.1f} mm, h={slab.thickness_h_mm:.1f} mm, "
        f"E={slab.E_MPa:.0f} MPa, nu={slab.poisson}. "
        f"q={load.udl_kPa:.3f} kPa={load.udl_kPa*1e-3:.6f} N/mm^2. "
        f"alpha={alpha:.6g}, D={D:.4g} N·mm. "
        f"Results: delta_max={delta:.4g} mm, M_xx={M_xx:.4g} N·mm/mm, M_yy={M_yy:.4g} N·mm/mm. "
        f"SCOPE: linear-elastic Kirchhoff thin-plate only. "
        f"NOT included: shear deformation (Mindlin) — important for h/a>~0.1; "
        f"plastic hinge redistribution; concrete cracking / tension stiffening; "
        f"creep / shrinkage; orthotropic / ribbed slabs; punching shear; "
        f"intermediate fixed-fixed ratios use an approximate scaled interpolation, "
        f"not Timoshenko's double-series solution."
    )
