"""
Classical Laminate Theory (CLT / CLPT) for composite laminates.

Implements the standard CLT formulation to compute the [A B D] stiffness
matrix of a general layered composite laminate and the ply-level stresses
from applied in-plane loads and bending moments.

Physical model
--------------
The laminate mid-plane is the reference surface.  Under CLT assumptions
(Kirchhoff-Love):
  - Straight lines normal to the mid-surface remain straight and normal
    (no transverse shear strains).
  - Plate thickness does not change.

The ABD constitutive relation:
    { N }   [ A  B ] { ε⁰ }
    { M } = [ B  D ] { κ  }

where:
    N  = in-plane stress resultants [N/m]:    N_x, N_y, N_xy
    M  = bending moment resultants [N·m/m]:  M_x, M_y, M_xy
    ε⁰ = mid-plane strains [-]:              ε_x, ε_y, γ_xy
    κ  = curvatures [1/m]:                   κ_x, κ_y, κ_xy

    A_ij = Σ_k Q̄_ij^k (z_k - z_{k-1})
    B_ij = (1/2) Σ_k Q̄_ij^k (z_k² - z_{k-1}²)
    D_ij = (1/3) Σ_k Q̄_ij^k (z_k³ - z_{k-1}³)

    Q̄_ij^k is the transformed reduced stiffness matrix for ply k at
    orientation θ_k.

Ply stress recovery
-------------------
At depth z within ply k:
    ε(z) = ε⁰ + z·κ           (global frame)
    σ_global = Q̄_k · ε(z)
    σ_material = T_k · σ_global   (rotate to fibre frame)

The midplane strains and curvatures are found by solving:
    [A B] { ε⁰ }   { N }
    [B D] { κ  } = { M }

via the (6×6) ABD inverse (compliance matrix).

Honest limitations
------------------
- CLT only — no through-thickness shear (FSDT/HSDT needed for thick plates).
- Hygrothermal terms are set to zero (v1); temperature/moisture swelling not
  included.
- Assumes linear elastic ply behaviour (no progressive damage).
- No delamination modelling.

References
----------
Jones R.M. (1999). "Mechanics of Composite Materials." 2nd ed. Taylor & Francis.
  Chapter 4 — Classical Lamination Theory.
Reddy J.N. (2003). "Mechanics of Laminated Composite Plates and Shells."
  2nd ed. CRC Press. Chapter 3.
Daniel I.M., Ishai O. (2006). "Engineering Mechanics of Composite Materials."
  2nd ed. Oxford University Press.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import List

import numpy as np


# ---------------------------------------------------------------------------
# Ply and Laminate dataclasses
# ---------------------------------------------------------------------------

@dataclass
class LaminaPly:
    """
    A single unidirectional composite ply within a laminate stack.

    Fibre direction is along the local 1-axis.
    Transverse direction is along the local 2-axis.
    The ply is in a state of plane stress (σ_3 = τ_13 = τ_23 = 0 assumed by CLT).

    Parameters
    ----------
    material_name : str
        Descriptive name (e.g. 'T300/5208 carbon-epoxy').
    E1_pa : float
        Young's modulus along the fibre direction [Pa].
    E2_pa : float
        Young's modulus transverse to fibres [Pa].
    G12_pa : float
        In-plane shear modulus [Pa].
    nu12 : float
        Major Poisson ratio (ε_2 / -ε_1 under σ_1 loading).
    thickness_mm : float
        Ply thickness [mm].
    orientation_deg : float
        Ply fibre orientation angle θ measured from the laminate x-axis [°].
    sigma_1_T_pa : float
        Tensile strength along fibre direction (X_T) [Pa].
    sigma_1_C_pa : float
        Compressive strength along fibre direction (X_C) [Pa]. Positive value.
    sigma_2_T_pa : float
        Transverse tensile strength (Y_T) [Pa].
    sigma_2_C_pa : float
        Transverse compressive strength (Y_C) [Pa]. Positive value.
    tau_12_pa : float
        In-plane shear strength (S) [Pa].
    """
    material_name: str
    E1_pa: float
    E2_pa: float
    G12_pa: float
    nu12: float
    thickness_mm: float
    orientation_deg: float
    sigma_1_T_pa: float
    sigma_1_C_pa: float
    sigma_2_T_pa: float
    sigma_2_C_pa: float
    tau_12_pa: float

    @property
    def nu21(self) -> float:
        """Minor Poisson ratio from reciprocal relation: ν₂₁ = ν₁₂ · E₂ / E₁."""
        return self.nu12 * self.E2_pa / self.E1_pa

    @property
    def thickness_m(self) -> float:
        """Thickness in metres."""
        return self.thickness_mm * 1e-3

    def Q_matrix(self) -> np.ndarray:
        """
        Reduced stiffness matrix Q in the material (1-2) frame.

        Under plane-stress assumption:
            Q_11 = E1 / (1 - ν12·ν21)
            Q_22 = E2 / (1 - ν12·ν21)
            Q_12 = ν12·E2 / (1 - ν12·ν21)
            Q_66 = G12

        Returns (3,3) array [[Q11, Q12, 0], [Q12, Q22, 0], [0, 0, Q66]].

        Reference: Jones (1999) eq. (2.68).
        """
        nu21 = self.nu21
        denom = 1.0 - self.nu12 * nu21
        Q11 = self.E1_pa / denom
        Q22 = self.E2_pa / denom
        Q12 = self.nu12 * self.E2_pa / denom
        Q66 = self.G12_pa
        return np.array([
            [Q11, Q12,  0.0],
            [Q12, Q22,  0.0],
            [0.0, 0.0,  Q66],
        ])

    def Qbar_matrix(self) -> np.ndarray:
        """
        Transformed reduced stiffness matrix Q̄ in the laminate (x-y) frame.

        Applies the bond transformation at angle θ:
            Q̄ = T⁻¹ Q T⁻ᵀ

        where T is the stress transformation matrix.

        Reference: Jones (1999) eq. (2.84).

        Returns (3,3) array in [σ_x, σ_y, τ_xy] ordering.
        """
        theta = math.radians(self.orientation_deg)
        c = math.cos(theta)
        s = math.sin(theta)
        c2 = c * c
        s2 = s * s
        cs = c * s

        Q = self.Q_matrix()
        Q11, Q12, Q22, Q66 = Q[0, 0], Q[0, 1], Q[1, 1], Q[2, 2]

        # Jones (1999) eqs. (2.79)-(2.84)
        Qb11 = Q11*c2*c2 + 2.0*(Q12 + 2.0*Q66)*s2*c2 + Q22*s2*s2
        Qb12 = (Q11 + Q22 - 4.0*Q66)*s2*c2 + Q12*(s2*s2 + c2*c2)
        Qb22 = Q11*s2*s2 + 2.0*(Q12 + 2.0*Q66)*s2*c2 + Q22*c2*c2
        Qb16 = (Q11 - Q12 - 2.0*Q66)*c2*cs - (Q22 - Q12 - 2.0*Q66)*s2*cs
        Qb26 = (Q11 - Q12 - 2.0*Q66)*s2*cs - (Q22 - Q12 - 2.0*Q66)*c2*cs
        Qb66 = (Q11 + Q22 - 2.0*Q12 - 2.0*Q66)*s2*c2 + Q66*(s2*s2 + c2*c2)

        return np.array([
            [Qb11, Qb12, Qb16],
            [Qb12, Qb22, Qb26],
            [Qb16, Qb26, Qb66],
        ])

    def T_stress(self) -> np.ndarray:
        """
        Stress transformation matrix T for rotation by θ.

        Transforms stress from laminate (x-y) frame to material (1-2) frame:
            {σ_1, σ_2, τ_12} = T · {σ_x, σ_y, τ_xy}

        Reference: Jones (1999) eq. (2.30).
        Note: uses the Reuter matrix convention for shear (factor of 2).
        """
        theta = math.radians(self.orientation_deg)
        c = math.cos(theta)
        s = math.sin(theta)
        c2, s2, cs = c*c, s*s, c*s
        return np.array([
            [ c2,  s2,  2.0*cs],
            [ s2,  c2, -2.0*cs],
            [-cs,  cs,  c2 - s2],
        ])


@dataclass
class Laminate:
    """
    A stacked sequence of unidirectional plies forming a composite laminate.

    Plies are listed from bottom (−h/2) to top (+h/2).
    The mid-plane z = 0 is the reference surface for CLT.

    Parameters
    ----------
    plies : list[LaminaPly]
        Ordered list of plies, bottom to top.
    """
    plies: List[LaminaPly]

    @property
    def total_thickness_mm(self) -> float:
        """Total laminate thickness [mm]."""
        return sum(p.thickness_mm for p in self.plies)

    @property
    def total_thickness_m(self) -> float:
        """Total laminate thickness [m]."""
        return self.total_thickness_mm * 1e-3

    def _ply_z_bounds(self) -> list[tuple[float, float]]:
        """
        Compute (z_bottom, z_top) for each ply in metres.

        The mid-plane is at z=0; z increases upward.
        Returns list of (z_{k-1}, z_k) pairs for each ply k.
        """
        h_total = self.total_thickness_m
        z0 = -h_total / 2.0
        bounds = []
        z = z0
        for ply in self.plies:
            z_bot = z
            z_top = z + ply.thickness_m
            bounds.append((z_bot, z_top))
            z = z_top
        return bounds

    def compute_ABD_matrix(self) -> np.ndarray:
        """
        Compute the (6×6) ABD stiffness matrix of the laminate.

        Layout:
            [ A  B ]   (3×3 blocks)
            [ B  D ]

        where:
            A_ij = Σ_k Q̄_ij^k · (z_k − z_{k-1})
            B_ij = ½ Σ_k Q̄_ij^k · (z_k² − z_{k-1}²)
            D_ij = ⅓ Σ_k Q̄_ij^k · (z_k³ − z_{k-1}³)

        A [N/m]   : extensional stiffness
        B [N]     : bending-extension coupling
        D [N·m]   : bending stiffness

        Returns (6,6) numpy array.

        Reference: Jones (1999) Ch. 4, eqs. (4.4)-(4.6).
        """
        A = np.zeros((3, 3))
        B = np.zeros((3, 3))
        D = np.zeros((3, 3))
        bounds = self._ply_z_bounds()

        for ply, (z_bot, z_top) in zip(self.plies, bounds):
            Qb = ply.Qbar_matrix()
            dz  = z_top - z_bot
            dz2 = z_top**2 - z_bot**2
            dz3 = z_top**3 - z_bot**3
            A += Qb * dz
            B += Qb * (0.5 * dz2)
            D += Qb * (dz3 / 3.0)

        ABD = np.zeros((6, 6))
        ABD[:3, :3] = A
        ABD[:3, 3:] = B
        ABD[3:, :3] = B
        ABD[3:, 3:] = D
        return ABD


# ---------------------------------------------------------------------------
# Response dataclass
# ---------------------------------------------------------------------------

@dataclass
class LaminateResponse:
    """
    CLT solution: mid-plane strains, curvatures, and ply-level stresses.

    Attributes
    ----------
    midplane_strain : np.ndarray (3,)
        Mid-plane strains [ε_x, ε_y, γ_xy] [-].
    curvature : np.ndarray (3,)
        Curvatures [κ_x, κ_y, κ_xy] [1/m].
    ply_stresses : list[np.ndarray]
        Per-ply stress in the material frame [σ_1, σ_2, τ_12] [Pa].
        Each element is (3,). Uses mid-ply z for recovery (conservative).
    ply_strains_global : list[np.ndarray]
        Per-ply strain in the global frame [ε_x, ε_y, γ_xy] at mid-ply z.
    """
    midplane_strain: np.ndarray
    curvature: np.ndarray
    ply_stresses: List[np.ndarray]
    ply_strains_global: List[np.ndarray]


# ---------------------------------------------------------------------------
# Analysis function
# ---------------------------------------------------------------------------

def analyze_laminate(
    laminate: Laminate,
    in_plane_loads: np.ndarray,
    bending_moments: np.ndarray,
) -> LaminateResponse:
    """
    Classical Laminate Theory analysis.

    Computes mid-plane strains, curvatures, and ply-level stresses in the
    material (fibre) frame for each ply under the applied loads.

    Parameters
    ----------
    laminate : Laminate
        The composite laminate.
    in_plane_loads : np.ndarray (3,)
        In-plane stress resultants [N_x, N_y, N_xy] [N/m].
    bending_moments : np.ndarray (3,)
        Bending/twisting moment resultants [M_x, M_y, M_xy] [N·m/m].

    Returns
    -------
    LaminateResponse

    Algorithm
    ---------
    1. Compute ABD matrix.
    2. Form the combined load vector {N, M} (6,).
    3. Solve [A B; B D] · {ε⁰, κ} = {N, M} for mid-plane strains and
       curvatures.
    4. For each ply k at mid-ply depth z_mid = (z_bot + z_top) / 2:
         ε(z_mid) = ε⁰ + z_mid · κ          (global frame)
         σ_global  = Q̄_k · ε(z_mid)
         σ_mat     = T_k · σ_global           (material frame)

    Notes
    -----
    Hygrothermal terms are set to zero in this version (v1).
    CLT is valid for thin laminates (h/a < ~0.05).  For thick
    laminates, use FSDT or HSDT.

    References
    ----------
    Jones (1999) Ch. 4.  Reddy (2003) §3.3.
    """
    in_plane_loads = np.asarray(in_plane_loads, dtype=float)
    bending_moments = np.asarray(bending_moments, dtype=float)

    if in_plane_loads.shape != (3,):
        raise ValueError("in_plane_loads must be shape (3,)")
    if bending_moments.shape != (3,):
        raise ValueError("bending_moments must be shape (3,)")

    ABD = laminate.compute_ABD_matrix()
    load_vec = np.concatenate([in_plane_loads, bending_moments])

    # Solve for mid-plane strains and curvatures
    try:
        deformation = np.linalg.solve(ABD, load_vec)
    except np.linalg.LinAlgError as e:
        raise ValueError(f"ABD matrix is singular — check laminate definition: {e}")

    eps0 = deformation[:3]
    kappa = deformation[3:]

    # Ply-level stress recovery
    bounds = laminate._ply_z_bounds()
    ply_stresses = []
    ply_strains_global = []

    for ply, (z_bot, z_top) in zip(laminate.plies, bounds):
        z_mid = 0.5 * (z_bot + z_top)
        # Global strain at mid-ply depth
        eps_global = eps0 + z_mid * kappa
        # Global stress
        # sigma_global = Qbar · eps_global
        # (for consistency, stress in material frame via transformation)
        # Material frame stress: σ_mat = T · Qbar · eps_global
        # Or equivalently: σ_mat = Q · T_eps · eps_global
        # Use: σ_global = Qbar · eps_global, then T · σ_global
        sigma_global = ply.Qbar_matrix() @ eps_global
        T = ply.T_stress()
        sigma_mat = T @ sigma_global
        ply_stresses.append(sigma_mat)
        ply_strains_global.append(eps_global.copy())

    return LaminateResponse(
        midplane_strain=eps0,
        curvature=kappa,
        ply_stresses=ply_stresses,
        ply_strains_global=ply_strains_global,
    )
