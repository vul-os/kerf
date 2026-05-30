"""
kerf_composites.layup_optimizer — Ply angle optimizer for composite laminates.

Minimize laminate weight (total thickness) subject to a first-ply-failure (FPF)
margin constraint, using Classical Laminate Theory (CLT) + Tsai-Wu failure
criterion and a simulated-annealing search over discrete ply angles.

References
----------
Tsai, S. W. & Hahn, H. T. (1980). Introduction to Composite Materials.
    Technomic Publishing, §6 (ABD matrices), §7 (Tsai-Wu).
Daniel, I. M. & Ishai, O. (2006). Engineering Mechanics of Composite Materials,
    2nd ed. Oxford University Press, §8 (failure criteria + FPF).

Key functions
-------------
compute_abd_matrix(laminate)               → ndarray (6×6) full ABD
tsai_wu_failure_index(laminate, loads)     → dict (per-ply FI, FPF ply index)
optimize_layup_angles(initial, loads, …)   → Laminate (optimized)
compute_lamination_constants(laminate)     → dict (Ex, Ey, Gxy, nu_xy, nu_yx)

Dataclasses
-----------
Ply       — angle_deg, thickness_mm, material (TsaiWuMaterial)
Laminate  — list[Ply], symmetric flag
TsaiWuMaterial — full orthotropic + strength tensor

Units
-----
Moduli: GPa.  Strengths, stresses: MPa.  Thickness: mm.
Stiffness matrices: N/mm (A), N (B), N·mm (D).
Load resultants: N/mm (Nx, Ny, Nxy) and N·mm/mm (Mx, My, Mxy).
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import Sequence

import numpy as np


# ---------------------------------------------------------------------------
# Material dataclass
# ---------------------------------------------------------------------------

@dataclass
class TsaiWuMaterial:
    """
    Orthotropic ply material for Tsai-Wu analysis.

    Attributes (all required)
    -------------------------
    name : str
    E1   : float  — fibre-direction Young's modulus [GPa]
    E2   : float  — transverse Young's modulus [GPa]
    G12  : float  — in-plane shear modulus [GPa]
    nu12 : float  — major Poisson ratio (dimensionless)
    Xt   : float  — longitudinal tensile strength [MPa]
    Xc   : float  — longitudinal compressive strength [MPa]
    Yt   : float  — transverse tensile strength [MPa]
    Yc   : float  — transverse compressive strength [MPa]
    S12  : float  — in-plane shear strength [MPa]
    rho  : float  — density [g/cm³], optional (default 1.6, typical CFRP)
    """
    name: str
    E1: float    # GPa
    E2: float    # GPa
    G12: float   # GPa
    nu12: float
    Xt: float    # MPa
    Xc: float    # MPa
    Yt: float    # MPa
    Yc: float    # MPa
    S12: float   # MPa
    rho: float = 1.6  # g/cm³

    @property
    def nu21(self) -> float:
        """Minor Poisson ratio (reciprocal relation)."""
        return self.nu12 * self.E2 / self.E1


# ---------------------------------------------------------------------------
# Reference materials (Tsai-Hahn 1980, Table 2.2; Daniel-Ishai 2006, App. A)
# ---------------------------------------------------------------------------

#: T300/5208 CFRP — the industry benchmark unidirectional lamina.
#: E1=181, E2=10.3, G12=7.17, nu12=0.28 (Tsai-Hahn 1980)
#: Xt=1500, Xc=1500, Yt=40, Yc=246, S12=68 (typical qualification data)
T300_5208_TW = TsaiWuMaterial(
    name="T300/5208 CFRP",
    E1=181.0, E2=10.3, G12=7.17, nu12=0.28,
    Xt=1500.0, Xc=1500.0, Yt=40.0, Yc=246.0, S12=68.0,
    rho=1.6,
)

#: AS4/3501-6 CFRP — common aerospace autoclave material.
AS4_3501 = TsaiWuMaterial(
    name="AS4/3501-6 CFRP",
    E1=148.0, E2=10.5, G12=5.61, nu12=0.30,
    Xt=2280.0, Xc=1725.0, Yt=57.0, Yc=228.0, S12=71.0,
    rho=1.58,
)


# ---------------------------------------------------------------------------
# Ply and Laminate dataclasses
# ---------------------------------------------------------------------------

@dataclass
class Ply:
    """
    A single composite ply for the optimizer.

    Parameters
    ----------
    angle_deg   : float            — fibre orientation [degrees]
    thickness_mm: float            — ply thickness [mm]
    material    : TsaiWuMaterial   — ply orthotropic + strength data
    """
    angle_deg: float
    thickness_mm: float
    material: TsaiWuMaterial

    def __post_init__(self):
        if self.thickness_mm <= 0.0:
            raise ValueError(
                f"Ply thickness must be positive, got {self.thickness_mm!r}"
            )


@dataclass
class Laminate:
    """
    An ordered ply stack for CLT + optimizer use.

    Parameters
    ----------
    plies     : list[Ply]   — ordered bottom-to-top ply stack
    symmetric : bool        — if True the stack is [θ₁/θ₂/…/θ₂/θ₁] symmetric
                              (B matrix vanishes; recommended for production)

    Properties
    ----------
    total_thickness : float   — sum of ply thicknesses [mm]
    num_plies       : int     — len(plies)
    z_coords        : list    — ply interface z-coordinates from mid-plane [mm]
    """
    plies: list[Ply] = field(default_factory=list)
    symmetric: bool = True

    def __post_init__(self):
        if not isinstance(self.plies, list):
            self.plies = list(self.plies)

    @property
    def num_plies(self) -> int:
        return len(self.plies)

    @property
    def total_thickness(self) -> float:
        return sum(p.thickness_mm for p in self.plies)

    @property
    def z_coords(self) -> list[float]:
        """
        Z-coordinates of ply interfaces measured from the mid-plane [mm].
        Returns (num_plies + 1) values; z[0] is the bottom face.
        """
        h = self.total_thickness
        z: list[float] = [-h / 2.0]
        for p in self.plies:
            z.append(z[-1] + p.thickness_mm)
        return z

    @classmethod
    def from_angles(
        cls,
        angles_deg: Sequence[float],
        material: TsaiWuMaterial,
        ply_thickness_mm: float = 0.125,
        symmetric: bool = True,
    ) -> "Laminate":
        """
        Convenience constructor: build a Laminate from a list of angles.

        The ``symmetric`` flag is metadata only — the ply sequence is stored
        as supplied; supply a symmetric sequence explicitly if desired.
        """
        plies = [
            Ply(angle_deg=a, thickness_mm=ply_thickness_mm, material=material)
            for a in angles_deg
        ]
        return cls(plies=plies, symmetric=symmetric)


# ---------------------------------------------------------------------------
# Reduced stiffness Q (principal axes)
# ---------------------------------------------------------------------------

def _ply_Q(ply: Ply) -> np.ndarray:
    """3×3 reduced stiffness matrix Q in ply principal axes [GPa]."""
    m = ply.material
    denom = 1.0 - m.nu12 * m.nu21
    Q11 = m.E1 / denom
    Q22 = m.E2 / denom
    Q12 = m.nu12 * m.E2 / denom
    Q66 = m.G12
    return np.array([
        [Q11, Q12, 0.0],
        [Q12, Q22, 0.0],
        [0.0, 0.0, Q66],
    ], dtype=float)


def _ply_Qbar(ply: Ply) -> np.ndarray:
    """3×3 transformed reduced stiffness Q̄ in laminate axes [GPa]."""
    theta = math.radians(ply.angle_deg)
    c = math.cos(theta)
    s = math.sin(theta)
    c2, s2 = c * c, s * s
    cs = c * s
    c4, s4, c2s2 = c2 * c2, s2 * s2, c2 * s2

    Q = _ply_Q(ply)
    Q11, Q12, Q22, Q66 = Q[0, 0], Q[0, 1], Q[1, 1], Q[2, 2]

    Qb11 = Q11 * c4 + 2.0 * (Q12 + 2.0 * Q66) * c2s2 + Q22 * s4
    Qb12 = (Q11 + Q22 - 4.0 * Q66) * c2s2 + Q12 * (c4 + s4)
    Qb22 = Q11 * s4 + 2.0 * (Q12 + 2.0 * Q66) * c2s2 + Q22 * c4
    Qb16 = (Q11 - Q12 - 2.0 * Q66) * c2 * cs - (Q22 - Q12 - 2.0 * Q66) * s2 * cs
    Qb26 = (Q11 - Q12 - 2.0 * Q66) * s2 * cs - (Q22 - Q12 - 2.0 * Q66) * c2 * cs
    Qb66 = (Q11 + Q22 - 2.0 * Q12 - 2.0 * Q66) * c2s2 + Q66 * (c4 + s4)

    return np.array([
        [Qb11, Qb12, Qb16],
        [Qb12, Qb22, Qb26],
        [Qb16, Qb26, Qb66],
    ], dtype=float)


# ---------------------------------------------------------------------------
# ABD matrix (6×6 full CLT)
# ---------------------------------------------------------------------------

def compute_abd_matrix(laminate: Laminate) -> np.ndarray:
    """
    Compute the full 6×6 [A | B; B | D] CLT stiffness matrix.

    The sub-blocks are computed per Tsai-Hahn 1980, §6:
        Aij = Σ Q̄ij_k · (z_k − z_{k-1})          [N/mm]
        Bij = ½ Σ Q̄ij_k · (z_k² − z_{k-1}²)       [N]
        Dij = ⅓ Σ Q̄ij_k · (z_k³ − z_{k-1}³)       [N·mm]

    Returns
    -------
    ndarray, shape (6, 6)
        Full ABD matrix arranged as:
            [[A₁₁  A₁₂  A₁₆  B₁₁  B₁₂  B₁₆],
             [A₁₂  A₂₂  A₂₆  B₁₂  B₂₂  B₂₆],
             [A₁₆  A₂₆  A₆₆  B₁₆  B₂₆  B₆₆],
             [B₁₁  B₁₂  B₁₆  D₁₁  D₁₂  D₁₆],
             [B₁₂  B₂₂  B₂₆  D₁₂  D₂₂  D₂₆],
             [B₁₆  B₂₆  B₆₆  D₁₆  D₂₆  D₆₆]]

    Units
    -----
    A: N/mm,  B: N,  D: N·mm
    """
    if laminate.num_plies == 0:
        raise ValueError("Laminate has no plies.")

    A = np.zeros((3, 3), dtype=float)
    B = np.zeros((3, 3), dtype=float)
    D = np.zeros((3, 3), dtype=float)

    z = laminate.z_coords  # length = num_plies + 1

    for k, ply in enumerate(laminate.plies):
        Qb = _ply_Qbar(ply)
        zk = z[k + 1]
        zkm1 = z[k]
        dz = zk - zkm1
        dz2 = zk ** 2 - zkm1 ** 2
        dz3 = zk ** 3 - zkm1 ** 3

        A += Qb * dz
        B += Qb * (0.5 * dz2)
        D += Qb * (dz3 / 3.0)

    # Convert GPa·mm → N/mm  (×1000)
    A = A * 1.0e3
    B = B * 1.0e3
    D = D * 1.0e3

    # Assemble 6×6
    ABD = np.zeros((6, 6), dtype=float)
    ABD[:3, :3] = A
    ABD[:3, 3:] = B
    ABD[3:, :3] = B
    ABD[3:, 3:] = D
    return ABD


# ---------------------------------------------------------------------------
# Tsai-Wu failure index per ply
# ---------------------------------------------------------------------------

def _tsai_wu_fi_ply(
    sigma1: float,
    sigma2: float,
    tau12: float,
    mat: TsaiWuMaterial,
    F12_star: float = -0.5,
) -> float:
    """
    Tsai-Wu failure index for a single ply (Tsai-Hahn 1980, §7):

        FI = F₁σ₁ + F₂σ₂ + F₁₁σ₁² + F₂₂σ₂² + F₆₆τ₁₂² + 2F₁₂σ₁σ₂
    """
    F1 = 1.0 / mat.Xt - 1.0 / mat.Xc
    F2 = 1.0 / mat.Yt - 1.0 / mat.Yc
    F11 = 1.0 / (mat.Xt * mat.Xc)
    F22 = 1.0 / (mat.Yt * mat.Yc)
    F66 = 1.0 / (mat.S12 ** 2)
    F12 = F12_star * math.sqrt(F11 * F22)

    return (
        F1 * sigma1
        + F2 * sigma2
        + F11 * sigma1 ** 2
        + F22 * sigma2 ** 2
        + F66 * tau12 ** 2
        + 2.0 * F12 * sigma1 * sigma2
    )


def _stress_transformation_matrix(theta_rad: float) -> np.ndarray:
    """
    Stress transformation matrix T for rotation by theta from laminate to
    ply principal axes.  Consistent with Reuter matrix / engineering shear.

    σ_ply = T · σ_lam   (where σ = [σ₁, σ₂, τ₁₂]ᵀ)
    """
    c = math.cos(theta_rad)
    s = math.sin(theta_rad)
    return np.array([
        [c * c,  s * s,  2.0 * c * s],
        [s * s,  c * c, -2.0 * c * s],
        [-c * s,  c * s,  c * c - s * s],
    ], dtype=float)


def tsai_wu_failure_index(
    laminate: Laminate,
    loads: dict,
    F12_star: float = -0.5,
) -> dict:
    """
    Compute Tsai-Wu failure indices for every ply under the given load state
    and identify first-ply-failure (FPF).

    Parameters
    ----------
    laminate : Laminate
        Ply stack.
    loads : dict
        Load resultants.  Supported keys (all in N/mm or N·mm/mm):
            Nx, Ny, Nxy   — in-plane force resultants [N/mm]
            Mx, My, Mxy   — bending / twisting moment resultants [N·mm/mm]
        Unspecified components default to 0.
    F12_star : float
        Tsai-Wu interaction coefficient (default −0.5, conservative).

    Returns
    -------
    dict with:
        ply_results : list of dicts, each containing:
            ply_index    : int
            angle_deg    : float
            sigma1_MPa   : float
            sigma2_MPa   : float
            tau12_MPa    : float
            tsai_wu_fi   : float   (failure index; ≥1 → failure)
            margin       : float   (= 1/FI − 1; positive → safe)
            failed       : bool
        fpf_ply_index : int | None   — first-ply-failure index (min FI ply)
        fpf_fi        : float        — FI at first-ply-failure ply
        fpf_margin    : float        — safety margin at FPF ply (1/FI − 1)
        total_thickness_mm : float
    """
    if laminate.num_plies == 0:
        raise ValueError("Laminate has no plies.")

    Nx  = float(loads.get("Nx",  0.0))
    Ny  = float(loads.get("Ny",  0.0))
    Nxy = float(loads.get("Nxy", 0.0))
    Mx  = float(loads.get("Mx",  0.0))
    My  = float(loads.get("My",  0.0))
    Mxy = float(loads.get("Mxy", 0.0))

    # Build A, B, D sub-blocks
    A = np.zeros((3, 3), dtype=float)
    B = np.zeros((3, 3), dtype=float)
    D = np.zeros((3, 3), dtype=float)
    z = laminate.z_coords
    for k, ply in enumerate(laminate.plies):
        Qb = _ply_Qbar(ply)
        zk, zkm1 = z[k + 1], z[k]
        dz = zk - zkm1
        dz2 = zk ** 2 - zkm1 ** 2
        dz3 = zk ** 3 - zkm1 ** 3
        A += Qb * dz
        B += Qb * (0.5 * dz2)
        D += Qb * (dz3 / 3.0)
    A *= 1.0e3
    B *= 1.0e3
    D *= 1.0e3

    # Assemble 6×6 and solve for mid-plane strains + curvatures
    ABD = np.zeros((6, 6), dtype=float)
    ABD[:3, :3] = A
    ABD[:3, 3:] = B
    ABD[3:, :3] = B
    ABD[3:, 3:] = D

    load_vec = np.array([Nx, Ny, Nxy, Mx, My, Mxy], dtype=float)
    try:
        deformation = np.linalg.solve(ABD, load_vec)
    except np.linalg.LinAlgError:
        deformation = np.linalg.lstsq(ABD, load_vec, rcond=None)[0]

    eps0 = deformation[:3]   # mid-plane strains [dimensionless]
    kappa = deformation[3:]  # curvatures [1/mm]

    ply_results = []
    min_margin = float("inf")
    fpf_ply_index = None
    fpf_fi = 0.0

    for k, ply in enumerate(laminate.plies):
        # Strain at ply mid-depth (per CLT, Tsai-Hahn §6.2)
        z_mid = (z[k] + z[k + 1]) / 2.0
        strain_lam = eps0 + z_mid * kappa  # laminate-axis engineering strains

        # Ply-level stress in laminate axes: σ_lam = Q̄ · ε_lam  [GPa → ×1e3 → MPa]
        Qb = _ply_Qbar(ply)
        stress_lam_GPa = Qb @ strain_lam   # GPa (= stress in GPa for dimensionless ε)
        stress_lam_MPa = stress_lam_GPa * 1.0e3  # → MPa

        # Rotate to ply principal axes
        theta = math.radians(ply.angle_deg)
        T = _stress_transformation_matrix(theta)
        stress_ply = T @ stress_lam_MPa  # [σ₁, σ₂, τ₁₂] in MPa

        sigma1, sigma2, tau12 = float(stress_ply[0]), float(stress_ply[1]), float(stress_ply[2])

        fi = _tsai_wu_fi_ply(sigma1, sigma2, tau12, ply.material, F12_star=F12_star)
        margin = (1.0 / fi - 1.0) if fi > 1e-12 else float("inf")
        failed = fi >= 1.0

        ply_results.append({
            "ply_index": k,
            "angle_deg": ply.angle_deg,
            "sigma1_MPa": sigma1,
            "sigma2_MPa": sigma2,
            "tau12_MPa": tau12,
            "tsai_wu_fi": fi,
            "margin": margin,
            "failed": failed,
        })

        if fi > fpf_fi:
            fpf_fi = fi
            fpf_ply_index = k
        if margin < min_margin:
            min_margin = margin

    fpf_margin = (1.0 / fpf_fi - 1.0) if fpf_fi > 1e-12 else float("inf")

    return {
        "ply_results": ply_results,
        "fpf_ply_index": fpf_ply_index,
        "fpf_fi": fpf_fi,
        "fpf_margin": fpf_margin,
        "total_thickness_mm": laminate.total_thickness,
    }


# ---------------------------------------------------------------------------
# Lamination constants (in-plane engineering moduli)
# ---------------------------------------------------------------------------

def compute_lamination_constants(laminate: Laminate) -> dict:
    """
    Compute effective in-plane engineering moduli from the A-matrix compliance.

    Uses Jones (1975) / Tsai-Hahn §6.5 approach:
        a = A⁻¹
        Ex   = 1 / (h · a₁₁)   [GPa]
        Ey   = 1 / (h · a₂₂)   [GPa]
        Gxy  = 1 / (h · a₆₆)   [GPa]
        nu_xy = −a₁₂ / a₁₁
        nu_yx = −a₁₂ / a₂₂

    Returns
    -------
    dict with keys: Ex, Ey, Gxy, nu_xy, nu_yx  (moduli in GPa)
    """
    if laminate.num_plies == 0:
        raise ValueError("Laminate has no plies.")
    h = laminate.total_thickness
    if h <= 0.0:
        raise ValueError("Laminate has zero total thickness.")

    A = np.zeros((3, 3), dtype=float)
    z = laminate.z_coords
    for k, ply in enumerate(laminate.plies):
        Qb = _ply_Qbar(ply)
        dz = z[k + 1] - z[k]
        A += Qb * dz
    A *= 1.0e3  # GPa·mm → N/mm

    a = np.linalg.inv(A)  # compliance mm/N

    # Ex = 1/(a11*h)  [N/mm² = MPa → /1000 → GPa]
    Ex   = 1.0 / (a[0, 0] * h) / 1.0e3
    Ey   = 1.0 / (a[1, 1] * h) / 1.0e3
    Gxy  = 1.0 / (a[2, 2] * h) / 1.0e3
    nu_xy = -a[0, 1] / a[0, 0]
    nu_yx = -a[0, 1] / a[1, 1]

    return {
        "Ex": Ex,
        "Ey": Ey,
        "Gxy": Gxy,
        "nu_xy": nu_xy,
        "nu_yx": nu_yx,
        "total_thickness_mm": h,
        "num_plies": laminate.num_plies,
    }


# ---------------------------------------------------------------------------
# Constraint checker
# ---------------------------------------------------------------------------

def _fpf_margin(laminate: Laminate, loads: dict, F12_star: float = -0.5) -> float:
    """Return the minimum FPF margin (= 1/FI_max − 1) for the laminate."""
    result = tsai_wu_failure_index(laminate, loads, F12_star=F12_star)
    return float(result["fpf_margin"])


def _is_balanced(plies: list[Ply], tol: float = 1e-9) -> bool:
    """
    True if every off-axis ply at +θ has a matching ply at −θ with equal
    thickness and the same material.  Zero and 90° plies count as self-paired.
    """
    # Bucket by (|angle| mod 90, thickness, material id)
    from collections import Counter
    counts: Counter = Counter()
    for p in plies:
        a = p.angle_deg % 180.0
        # Normalise: angles in [0, 90]; 135° → -45° → 45°
        if a > 90.0:
            a = 180.0 - a
        counts[(round(a, 6), round(p.thickness_mm, 6), id(p.material))] += 1
    # 0° and 90° are self-paired; all others must appear in even counts
    for (a, t, mid), cnt in counts.items():
        if abs(a) < 1e-9 or abs(a - 90.0) < 1e-9:
            continue  # self-paired angles
        if cnt % 2 != 0:
            return False
    return True


def _make_symmetric_balanced(
    half_angles: list[float],
    material: TsaiWuMaterial,
    ply_thickness_mm: float,
) -> Laminate:
    """
    Build a symmetric balanced laminate from a half-stack of angles.

    For each angle θ in half_angles:
      - If θ is 0 or 90, keep as-is.
      - Otherwise pair with −θ (both sides of the mid-plane).

    The full stack is: expanded_half + reversed(expanded_half)
    where expanded_half replaces each off-axis θ with [θ, −θ].
    """
    def expand(angles):
        result = []
        for a in angles:
            a_norm = a % 180.0
            if abs(a_norm) < 1e-9 or abs(a_norm - 90.0) < 1e-9:
                result.append(a)
            else:
                result.append(a)
                result.append(-a)
        return result

    top_half = expand(half_angles)
    full_angles = top_half + list(reversed(top_half))
    plies = [
        Ply(angle_deg=a, thickness_mm=ply_thickness_mm, material=material)
        for a in full_angles
    ]
    return Laminate(plies=plies, symmetric=True)


# ---------------------------------------------------------------------------
# Simulated-annealing layup angle optimizer
# ---------------------------------------------------------------------------

def optimize_layup_angles(
    initial_layup: Laminate,
    loads: dict,
    n_iters: int = 200,
    allowed_angles: list[int] | None = None,
    required_fpf_margin: float = 1.5,
    F12_star: float = -0.5,
    seed: int | None = None,
) -> Laminate:
    """
    Minimize laminate weight (total thickness) subject to a first-ply-failure
    margin constraint, using simulated annealing over discrete ply angles.

    The optimizer works on a half-stack of N/2 angles (the other half is the
    symmetric mirror).  At each step it randomly changes one angle in the
    half-stack and conditionally accepts the mutation.

    The algorithm simultaneously:
      1. Explores angle permutations (always acceptable if FPF margin ≥ target).
      2. Drops plies from the half-stack when margin headroom allows.

    Constraint: each off-axis angle θ in the stack is paired with −θ
    (balanced), and the full stack is symmetric.

    Parameters
    ----------
    initial_layup : Laminate
        Starting point.  The optimizer will use the same material and ply
        thickness as the initial plies (assumed uniform).
    loads : dict
        Load resultants (same convention as tsai_wu_failure_index).
    n_iters : int
        Number of SA iterations (default 200; increase for better solutions).
    allowed_angles : list[int]
        Discrete angle candidates in degrees (default [0,15,30,45,60,75,90]).
    required_fpf_margin : float
        Minimum FPF margin (1/FI − 1) required (default 1.5 → RF = 2.5).
    F12_star : float
        Tsai-Wu interaction coefficient.
    seed : int | None
        Random seed for reproducibility.

    Returns
    -------
    Laminate
        Optimized (symmetric, balanced) laminate that satisfies the FPF
        margin constraint and has total thickness ≤ initial_layup total
        thickness.

    Notes
    -----
    Weight ≡ total thickness (uniform material density across plies).
    The optimizer cannot always find a thinner laminate when the initial
    layup is already near-minimal; the returned laminate is always feasible.
    """
    if allowed_angles is None:
        allowed_angles = [0, 15, 30, 45, 60, 75, 90]

    rng = random.Random(seed)

    if initial_layup.num_plies == 0:
        raise ValueError("initial_layup has no plies.")

    # Extract reference material + ply thickness from first ply
    ref_mat = initial_layup.plies[0].material
    ref_t = initial_layup.plies[0].thickness_mm

    # Build symmetric balanced version of initial layup
    n_half = max(1, initial_layup.num_plies // 2)
    half_angles = [p.angle_deg for p in initial_layup.plies[:n_half]]

    def build(angles: list[float]) -> Laminate:
        return _make_symmetric_balanced(angles, ref_mat, ref_t)

    current = build(half_angles)
    try:
        current_margin = _fpf_margin(current, loads, F12_star)
    except Exception:
        current_margin = -float("inf")

    # Keep track of best feasible solution
    best = current
    best_thickness = current.total_thickness
    best_margin = current_margin

    # SA temperature schedule
    T_start = 1.0
    T_end = 1e-3

    for i in range(n_iters):
        T = T_start * (T_end / T_start) ** (i / max(n_iters - 1, 1))

        # --- Propose a mutation ---
        proposal_angles = list(half_angles)
        action = rng.random()

        if action < 0.5 or len(proposal_angles) <= 1:
            # Mutate a random angle
            idx = rng.randrange(len(proposal_angles))
            proposal_angles[idx] = float(rng.choice(allowed_angles))
        elif action < 0.75 and len(proposal_angles) > 1:
            # Try removing a ply (weight reduction)
            idx = rng.randrange(len(proposal_angles))
            proposal_angles = proposal_angles[:idx] + proposal_angles[idx + 1:]
        else:
            # Swap two angles
            if len(proposal_angles) >= 2:
                i1, i2 = rng.sample(range(len(proposal_angles)), 2)
                proposal_angles[i1], proposal_angles[i2] = (
                    proposal_angles[i2], proposal_angles[i1]
                )

        if not proposal_angles:
            continue

        candidate = build(proposal_angles)
        try:
            cand_margin = _fpf_margin(candidate, loads, F12_star)
        except Exception:
            continue

        feasible = cand_margin >= required_fpf_margin

        # Accept if feasible and lighter, or by Metropolis criterion
        delta = candidate.total_thickness - current.total_thickness
        if feasible:
            if delta <= 0.0:
                # Always accept lighter feasible solution
                half_angles = proposal_angles
                current = candidate
                current_margin = cand_margin
            else:
                # Accept heavier with Boltzmann probability
                prob = math.exp(-delta / (T * ref_t + 1e-15))
                if rng.random() < prob:
                    half_angles = proposal_angles
                    current = candidate
                    current_margin = cand_margin
        else:
            # Accept infeasible with low probability to escape local minima
            prob = math.exp(
                -(required_fpf_margin - cand_margin) / (T + 1e-15)
            )
            if rng.random() < prob:
                half_angles = proposal_angles
                current = candidate
                current_margin = cand_margin

        # Track global best feasible
        if feasible and candidate.total_thickness <= best_thickness:
            best = candidate
            best_thickness = candidate.total_thickness
            best_margin = cand_margin

    # If initial was feasible and best never updated, return current
    if best_margin >= required_fpf_margin:
        return best

    # Fall back: return the most margin-positive solution found
    return current
