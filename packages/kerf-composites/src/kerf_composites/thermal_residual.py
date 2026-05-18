"""
kerf_composites.thermal_residual — Thermal residual stress via CLT.

When a laminate cures at elevated temperature and cools to service temperature,
each ply has different coefficients of thermal expansion (CTE) in its principal
axes.  The laminate constrains free thermal contraction → residual stresses.

Method: Classical Laminate Theory (CLT) with hygrothermal loads.

    Thermal free strain in ply k principal axes:
        εᵀ₁ = α₁ · ΔT,   εᵀ₂ = α₂ · ΔT,   γᵀ₁₂ = 0

    Transformed to laminate axes:
        {εᵀ}ˡᵃᵐ = T_strain⁻¹ · {εᵀ}ᵖˡʸ

    CLT thermal force/moment resultants:
        {Nᵀ} = Σ Q̄ₖ · {εᵀ}ₖ · tₖ
        {Mᵀ} = Σ Q̄ₖ · {εᵀ}ₖ · z_mid,k · tₖ

    Laminate mid-plane strains and curvatures from ABD inverse:
        {ε⁰, κ} = [ABD]⁻¹ · {Nᵀ, Mᵀ}

    Residual ply stress (principal axes) in ply k:
        {σ}ₖ = Q̄ₖ · ({ε⁰} + z_mid,k · {κ} − {εᵀ}ₖ)

Units
-----
CTE in 1/°C (or 1/K — same magnitude).
Moduli in GPa, thickness in mm.
ΔT in °C.
Resulting stresses in MPa.

References
----------
Jones, R. M. (1975). Mechanics of Composite Materials. Scripta.
Tsai, S. W. & Hahn, H. T. (1980). Introduction to Composite Materials.
    Technomic.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Sequence

import numpy as np

from kerf_composites.layup import Ply, PlyMaterial, LaminateLayup
from kerf_composites.clt import abd_matrices, ply_Qbar_matrix, ply_Q_matrix


# ---------------------------------------------------------------------------
# Extended ply material with CTE
# ---------------------------------------------------------------------------

@dataclass
class ThermalPlyMaterial:
    """
    PlyMaterial extended with coefficients of thermal expansion.

    Wraps an existing PlyMaterial and adds alpha1 / alpha2.

    Parameters
    ----------
    base : PlyMaterial
        Mechanical properties.
    alpha1 : float
        Longitudinal (fibre-direction) CTE [1/°C].  Typically ≈ 0–1 × 10⁻⁶.
    alpha2 : float
        Transverse CTE [1/°C].  Typically ≈ 25–30 × 10⁻⁶ for CFRP.
    """
    base: PlyMaterial
    alpha1: float  # 1/°C
    alpha2: float  # 1/°C

    # Delegate attribute access to base for mechanical properties
    def __getattr__(self, name: str):
        return getattr(self.base, name)


# T300/5208 CTE values (Reddy 2004; typical published values)
# α₁ ≈ 0.02 × 10⁻⁶ /°C (near-zero, fibre-dominated)
# α₂ ≈ 22.5 × 10⁻⁶ /°C (matrix-dominated)
T300_5208_CTE = ThermalPlyMaterial(
    base=None,  # Will be set after import; see module bottom
    alpha1=0.02e-6,  # 1/°C
    alpha2=22.5e-6,  # 1/°C
)


# ---------------------------------------------------------------------------
# Result dataclasses
# ---------------------------------------------------------------------------

@dataclass
class PlyThermalStress:
    """Thermal residual stress state in one ply's principal axes [MPa]."""
    ply_index: int
    angle: float
    sigma1: float  # MPa — fibre direction
    sigma2: float  # MPa — transverse
    tau12: float   # MPa — in-plane shear


@dataclass
class ThermalResidualResult:
    """
    Full thermal residual stress analysis result.

    Attributes
    ----------
    ply_stresses : list[PlyThermalStress]
        Per-ply residual stresses in principal axes [MPa].
    delta_T : float
        Temperature change applied [°C].  Negative for cool-down.
    mid_plane_strains : np.ndarray, shape (3,)
        Laminate mid-plane thermal strains [ε⁰_xx, ε⁰_yy, γ⁰_xy].
    curvatures : np.ndarray, shape (3,)
        Laminate thermal curvatures [κ_xx, κ_yy, κ_xy] [1/mm].
    """
    ply_stresses: list[PlyThermalStress]
    delta_T: float
    mid_plane_strains: np.ndarray
    curvatures: np.ndarray


# ---------------------------------------------------------------------------
# Strain transformation helpers
# ---------------------------------------------------------------------------

def _T_strain(theta_deg: float) -> np.ndarray:
    """
    Strain transformation matrix for angle θ (degrees).

    Transforms from ply principal axes to laminate axes:
        {ε}ˡᵃᵐ = T_strain · {ε}ᵖˡʸ

    Using Voigt notation (ε₁₁, ε₂₂, γ₁₂) with engineering shear strain.
    """
    t = math.radians(theta_deg)
    c = math.cos(t)
    s = math.sin(t)
    c2, s2, cs = c * c, s * s, c * s
    return np.array([
        [ c2,  s2,  cs],
        [ s2,  c2, -cs],
        [-2*cs, 2*cs, c2 - s2],
    ], dtype=float)


def _thermal_strain_lam(ply: Ply, alpha1: float, alpha2: float, dT: float) -> np.ndarray:
    """
    Thermal free-strain in laminate axes for a ply with given CTEs and ΔT.

    Returns shape (3,): [εᵀ_xx, εᵀ_yy, γᵀ_xy].
    """
    eps_ply = np.array([alpha1 * dT, alpha2 * dT, 0.0])
    T = _T_strain(ply.angle)
    return T @ eps_ply


# ---------------------------------------------------------------------------
# Main function
# ---------------------------------------------------------------------------

def thermal_residual(
    layup: LaminateLayup,
    alpha1_list: Sequence[float],
    alpha2_list: Sequence[float],
    delta_T: float,
) -> ThermalResidualResult:
    """
    Compute thermal residual stresses in a laminate due to a temperature change.

    Parameters
    ----------
    layup : LaminateLayup
        Laminate definition.
    alpha1_list : sequence of float
        Per-ply longitudinal CTE [1/°C].  Length must equal layup.num_plies.
    alpha2_list : sequence of float
        Per-ply transverse CTE [1/°C].
    delta_T : float
        Temperature change [°C].  Negative for cure cool-down
        (ΔT = T_service − T_cure).

    Returns
    -------
    ThermalResidualResult
    """
    n = layup.num_plies
    if len(alpha1_list) != n or len(alpha2_list) != n:
        raise ValueError("alpha1_list and alpha2_list must each have length equal to num_plies.")

    A, B, D = abd_matrices(layup)  # N/mm, N, N·mm

    # Build 6×6 ABD matrix for combined in-plane + bending
    ABD = np.zeros((6, 6), dtype=float)
    ABD[:3, :3] = A
    ABD[:3, 3:] = B
    ABD[3:, :3] = B
    ABD[3:, 3:] = D

    z = layup.z_coords  # length n+1

    # Thermal resultants
    NT = np.zeros(3)  # [N/mm] thermal force resultant
    MT = np.zeros(3)  # [N] thermal moment resultant

    for k, ply in enumerate(layup.plies):
        a1 = alpha1_list[k]
        a2 = alpha2_list[k]

        eps_T_lam = _thermal_strain_lam(ply, a1, a2, delta_T)  # free strain in lam axes

        Qbar = ply_Qbar_matrix(ply)  # GPa
        Qbar_mpa = Qbar * 1.0e3      # N/mm²

        t_k = ply.thickness
        z_mid = 0.5 * (z[k] + z[k + 1])

        NT += Qbar_mpa @ eps_T_lam * t_k        # N/mm
        MT += Qbar_mpa @ eps_T_lam * z_mid * t_k  # N

    # Solve for mid-plane strains and curvatures
    # [NT, MT] = [A B; B D] · [ε⁰, κ]
    rhs = np.concatenate([NT, MT])
    try:
        sol = np.linalg.solve(ABD, rhs)
    except np.linalg.LinAlgError:
        sol = np.linalg.lstsq(ABD, rhs, rcond=None)[0]

    eps0 = sol[:3]   # mid-plane strains
    kappa = sol[3:]  # curvatures [1/mm]

    # Per-ply residual stresses in principal axes
    ply_stresses = []
    for k, ply in enumerate(layup.plies):
        a1 = alpha1_list[k]
        a2 = alpha2_list[k]

        z_mid = 0.5 * (z[k] + z[k + 1])
        eps_lam = eps0 + z_mid * kappa  # laminate-axis strain at ply mid-plane
        eps_T_lam = _thermal_strain_lam(ply, a1, a2, delta_T)

        eps_mech_lam = eps_lam - eps_T_lam  # mechanical strain in lam axes

        Qbar = ply_Qbar_matrix(ply)
        Qbar_mpa = Qbar * 1.0e3  # N/mm² = MPa

        sigma_lam = Qbar_mpa @ eps_mech_lam  # [MPa] in laminate axes

        # Rotate back to principal (ply) axes: {σ}ᵖˡʸ = T_stress · {σ}ˡᵃᵐ
        # T_stress for stress uses (c², s², 2cs) / (s², c², -2cs) / (-cs, cs, c²-s²)
        t = math.radians(ply.angle)
        c, s = math.cos(t), math.sin(t)
        c2, s2, cs = c * c, s * s, c * s
        T_stress = np.array([
            [ c2,  s2,  2*cs],
            [ s2,  c2, -2*cs],
            [-cs,  cs,  c2 - s2],
        ], dtype=float)
        sigma_ply = T_stress @ sigma_lam  # [MPa] in principal axes

        ply_stresses.append(PlyThermalStress(
            ply_index=k,
            angle=ply.angle,
            sigma1=float(sigma_ply[0]),
            sigma2=float(sigma_ply[1]),
            tau12=float(sigma_ply[2]),
        ))

    return ThermalResidualResult(
        ply_stresses=ply_stresses,
        delta_T=delta_T,
        mid_plane_strains=eps0,
        curvatures=kappa,
    )


# ---------------------------------------------------------------------------
# Convenience wrapper for uniform-CTE laminates
# ---------------------------------------------------------------------------

def thermal_residual_uniform(
    layup: LaminateLayup,
    alpha1: float,
    alpha2: float,
    delta_T: float,
) -> ThermalResidualResult:
    """
    Thermal residual analysis with the same CTE for all plies.

    Parameters
    ----------
    layup : LaminateLayup
    alpha1 : float  [1/°C]  longitudinal CTE for all plies
    alpha2 : float  [1/°C]  transverse CTE for all plies
    delta_T : float  [°C]

    Returns
    -------
    ThermalResidualResult
    """
    n = layup.num_plies
    return thermal_residual(
        layup,
        alpha1_list=[alpha1] * n,
        alpha2_list=[alpha2] * n,
        delta_T=delta_T,
    )


# ---------------------------------------------------------------------------
# Patch T300_5208_CTE base after import
# ---------------------------------------------------------------------------

from kerf_composites.layup import T300_5208  # noqa: E402
T300_5208_CTE.base = T300_5208
