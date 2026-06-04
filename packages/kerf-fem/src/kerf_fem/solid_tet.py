"""
kerf_fem.solid_tet — 4-node and 10-node tetrahedral solid finite elements.

Implements:
  * Tet4  — 4-node linear tetrahedron (constant strain, single Gauss point)
  * Tet10 — 10-node quadratic tetrahedron (4-point Gauss quadrature)

DOF convention: 3 translational DOFs per node (u, v, w) in global X, Y, Z.
Tet4:  12×12 stiffness and mass matrices.
Tet10: 30×30 stiffness and mass matrices.

References
----------
* Cook, Malkus, Plesha & Witt, "Concepts and Applications of Finite Element
  Analysis", 4th ed. (2001), §6.2–§6.4 (constant-strain tet), §6.6 (higher-order).
* Bathe, "Finite Element Procedures", (1996), §5.3.1 (isoparametric solids).
* Hughes, "The Finite Element Method" (1987), §3.1–§3.3.

All routines use pure numpy (no external FEM libraries).
HONEST: Tet10 uses a standard 4-point Gauss rule for the reference tetrahedron
(Zienkiewicz & Taylor Table B.4); production codes typically use 5- or 11-point
rules for higher accuracy.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np


# ---------------------------------------------------------------------------
# Data class
# ---------------------------------------------------------------------------

@dataclass
class SolidElement:
    """Solid 3-D finite element descriptor.

    HONEST: This is a lightweight descriptor; assembly into a global stiffness
    matrix requires external glue code (see solid_tools.py).
    """
    kind: str                           # 'tet4' | 'tet10' | 'hex8' | 'hex20'
    node_indices: list[int]             # 4/10/8/20 global node indices
    material: object                    # object with attributes E, nu, density


# ---------------------------------------------------------------------------
# Tet4 — linear constant-strain tetrahedron
# ---------------------------------------------------------------------------

def _tet4_volume_and_B(nodes_xyz: np.ndarray) -> tuple[float, np.ndarray]:
    """Compute volume and constant strain-displacement matrix B for Tet4.

    Parameters
    ----------
    nodes_xyz : (4, 3) float array
        Rows are node coordinates [x, y, z].

    Returns
    -------
    vol : float
        Element volume (must be > 0 for positive orientation).
    B : (6, 12) float array
        Constant strain-displacement matrix.

    Reference: Cook et al. (2001) eq. 6.2-6 — B is constant for Tet4 (CST in 3-D).
    """
    nodes_xyz = np.asarray(nodes_xyz, dtype=float)
    if nodes_xyz.shape != (4, 3):
        raise ValueError("nodes_xyz must be (4, 3)")

    x1, y1, z1 = nodes_xyz[0]
    x2, y2, z2 = nodes_xyz[1]
    x3, y3, z3 = nodes_xyz[2]
    x4, y4, z4 = nodes_xyz[3]

    # Volume = (1/6) |det J| where J is the Jacobian of the mapping
    # For a tet: 6V = det([[x2-x1, x3-x1, x4-x1],
    #                       [y2-y1, y3-y1, y4-y1],
    #                       [z2-z1, z3-z1, z4-z1]])
    J = np.array([
        [x2 - x1, x3 - x1, x4 - x1],
        [y2 - y1, y3 - y1, y4 - y1],
        [z2 - z1, z3 - z1, z4 - z1],
    ])
    det_J = np.linalg.det(J)
    vol = det_J / 6.0
    if vol <= 0.0:
        raise ValueError(
            f"Tet4 has non-positive volume {vol:.6e}. "
            "Check node ordering (should follow right-hand rule)."
        )

    # Cofactors for the natural→physical mapping (Cook eq. 6.2-3)
    # a_i = det of sub-matrix when row i and col 1 are removed, etc.
    # Closed-form B from Cook (2001) §6.2, eq. 6.2-6
    a1 = (  (y3 - y4) * (z2 - z4) - (y2 - y4) * (z3 - z4) )  # ∂N1/∂y · ... from cofactors
    a2 = -(  (y3 - y4) * (z1 - z4) - (y1 - y4) * (z3 - z4) )
    a3 = (  (y2 - y4) * (z1 - z4) - (y1 - y4) * (z2 - z4) )
    a4 = -(a1 + a2 + a3)

    b1 = -(  (x3 - x4) * (z2 - z4) - (x2 - x4) * (z3 - z4) )
    b2 = (  (x3 - x4) * (z1 - z4) - (x1 - x4) * (z3 - z4) )
    b3 = -(  (x2 - x4) * (z1 - z4) - (x1 - x4) * (z2 - z4) )
    b4 = -(b1 + b2 + b3)

    c1 = (  (x3 - x4) * (y2 - y4) - (x2 - x4) * (y3 - y4) )
    c2 = -(  (x3 - x4) * (y1 - y4) - (x1 - x4) * (y3 - y4) )
    c3 = (  (x2 - x4) * (y1 - y4) - (x1 - x4) * (y2 - y4) )
    c4 = -(c1 + c2 + c3)

    inv6V = 1.0 / (6.0 * vol)

    # B matrix (6 × 12) — strain ordering: [ε_xx, ε_yy, ε_zz, γ_xy, γ_yz, γ_xz]
    B = np.zeros((6, 12))
    for i, (ai, bi, ci) in enumerate([(a1, b1, c1), (a2, b2, c2),
                                       (a3, b3, c3), (a4, b4, c4)]):
        col = i * 3
        B[0, col + 0] = ai * inv6V      # ∂N/∂x * u
        B[1, col + 1] = bi * inv6V      # ∂N/∂y * v   (note: sign convention)
        B[2, col + 2] = ci * inv6V      # ∂N/∂z * w
        B[3, col + 0] = bi * inv6V      # γ_xy = ∂u/∂y + ∂v/∂x
        B[3, col + 1] = ai * inv6V
        B[4, col + 1] = ci * inv6V      # γ_yz = ∂v/∂z + ∂w/∂y
        B[4, col + 2] = bi * inv6V
        B[5, col + 0] = ci * inv6V      # γ_xz = ∂u/∂z + ∂w/∂x
        B[5, col + 2] = ai * inv6V

    return vol, B


def _elasticity_matrix(E: float, nu: float) -> np.ndarray:
    """3-D isotropic linear elasticity matrix C (6×6).

    Reference: Cook et al. (2001) eq. 5.1-3.
    """
    lam = E * nu / ((1.0 + nu) * (1.0 - 2.0 * nu))
    mu = E / (2.0 * (1.0 + nu))
    C = np.array([
        [lam + 2*mu, lam,        lam,        0,    0,    0   ],
        [lam,        lam + 2*mu, lam,        0,    0,    0   ],
        [lam,        lam,        lam + 2*mu, 0,    0,    0   ],
        [0,          0,          0,          mu,   0,    0   ],
        [0,          0,          0,          0,    mu,   0   ],
        [0,          0,          0,          0,    0,    mu  ],
    ])
    return C


def stiffness_matrix_tet4(nodes_xyz: np.ndarray, E: float, nu: float) -> np.ndarray:
    """Compute the 12×12 element stiffness matrix for a Tet4 element.

    Parameters
    ----------
    nodes_xyz : (4, 3) float array
        Node coordinates.
    E : float
        Young's modulus [Pa].
    nu : float
        Poisson's ratio (must satisfy 0 < nu < 0.5).

    Returns
    -------
    K : (12, 12) float array
        Element stiffness matrix. Symmetric, positive semi-definite (6 rigid-body
        modes corresponding to zero eigenvalues).

    HONEST: Tet4 is a constant-strain element; it is notoriously stiff in bending.
    For accurate bending results use Tet10 or Hex8.

    Reference: Cook et al. (2001) eq. 6.2-8  K = V · Bᵀ C B
    """
    vol, B = _tet4_volume_and_B(nodes_xyz)
    C = _elasticity_matrix(E, nu)
    K = vol * (B.T @ C @ B)
    return K


def mass_matrix_consistent_tet4(nodes_xyz: np.ndarray, density: float) -> np.ndarray:
    """Compute the 12×12 consistent mass matrix for a Tet4 element.

    Uses the closed-form result for a linear tetrahedron:
        M = (ρ V / 20) * [(2 I4⊗I3) + (ones_4x4 ⊗ I3)]
    which gives 2 on same-node same-DOF, 1 on same-node cross-DOF partner,
    and 1 on different-node same-DOF. See Cook et al. (2001) eq. 11.2-4.

    HONEST: Lumped mass matrix (row-sum) is often preferred for dynamics; this
    is the consistent form.

    Reference: Cook et al. (2001) §11.2.
    """
    nodes_xyz = np.asarray(nodes_xyz, dtype=float)
    vol, _ = _tet4_volume_and_B(nodes_xyz)
    # Consistent mass for linear tet: M_ij = ρV * (1+δ_ij) / 20 per DOF pair
    # Full 12×12: assemble as block structure
    M = np.zeros((12, 12))
    factor = density * vol / 20.0
    for i in range(4):
        for j in range(4):
            val = factor * (2.0 if i == j else 1.0)
            for dof in range(3):
                M[3 * i + dof, 3 * j + dof] = val
    return M


# ---------------------------------------------------------------------------
# Tet10 — quadratic serendipity tetrahedron
# ---------------------------------------------------------------------------

# Natural coordinates for 4 Gauss points of the Tet (Zienkiewicz & Taylor, Vol.1 Table B.4)
# Exact for degree-2 polynomials; adequate for Tet10 (quadratic) elements.
_TET10_GP_A = 0.1381966011250105
_TET10_GP_B = 0.5854101966249685
_TET10_GAUSS_PTS = [
    (_TET10_GP_A, _TET10_GP_A, _TET10_GP_A),
    (_TET10_GP_B, _TET10_GP_A, _TET10_GP_A),
    (_TET10_GP_A, _TET10_GP_B, _TET10_GP_A),
    (_TET10_GP_A, _TET10_GP_A, _TET10_GP_B),
]
_TET10_GAUSS_WGTS = [0.25, 0.25, 0.25, 0.25]  # weights sum to 1 (volume of ref tet = 1/6, factored separately)


def _tet10_shape_and_grad(L1: float, L2: float, L3: float) -> tuple[np.ndarray, np.ndarray]:
    """Shape functions and their natural-coordinate gradients for Tet10.

    Node ordering follows Cook et al. (2001) §6.6:
      Corner nodes: 1(L1=1), 2(L2=1), 3(L3=1), 4(L4=1)
      Midside nodes: 5(L1-L2 edge), 6(L2-L3 edge), 7(L1-L3 edge),
                     8(L1-L4 edge), 9(L2-L4 edge), 10(L3-L4 edge)
    where L4 = 1 - L1 - L2 - L3.

    Returns
    -------
    N  : (10,) shape function values
    dN : (3, 10) ∂N/∂L1, ∂N/∂L2, ∂N/∂L3 — Jacobian columns still needed
    """
    L4 = 1.0 - L1 - L2 - L3

    N = np.array([
        L1 * (2.0 * L1 - 1.0),         # N1
        L2 * (2.0 * L2 - 1.0),         # N2
        L3 * (2.0 * L3 - 1.0),         # N3
        L4 * (2.0 * L4 - 1.0),         # N4
        4.0 * L1 * L2,                 # N5
        4.0 * L2 * L3,                 # N6
        4.0 * L1 * L3,                 # N7
        4.0 * L1 * L4,                 # N8
        4.0 * L2 * L4,                 # N9
        4.0 * L3 * L4,                 # N10
    ])

    # ∂N/∂Li (shape 3×10: rows=L1,L2,L3; cols=nodes)
    dNdL = np.zeros((3, 10))

    # ∂N/∂L1
    dNdL[0, 0] = 4.0 * L1 - 1.0
    dNdL[0, 1] = 0.0
    dNdL[0, 2] = 0.0
    dNdL[0, 3] = -(4.0 * L4 - 1.0)    # ∂(L4(2L4-1))/∂L1 = -(4L4-1)
    dNdL[0, 4] = 4.0 * L2
    dNdL[0, 5] = 0.0
    dNdL[0, 6] = 4.0 * L3
    dNdL[0, 7] = 4.0 * (L4 - L1)
    dNdL[0, 8] = -4.0 * L2
    dNdL[0, 9] = -4.0 * L3

    # ∂N/∂L2
    dNdL[1, 0] = 0.0
    dNdL[1, 1] = 4.0 * L2 - 1.0
    dNdL[1, 2] = 0.0
    dNdL[1, 3] = -(4.0 * L4 - 1.0)
    dNdL[1, 4] = 4.0 * L1
    dNdL[1, 5] = 4.0 * L3
    dNdL[1, 6] = 0.0
    dNdL[1, 7] = -4.0 * L1
    dNdL[1, 8] = 4.0 * (L4 - L2)
    dNdL[1, 9] = -4.0 * L3

    # ∂N/∂L3
    dNdL[2, 0] = 0.0
    dNdL[2, 1] = 0.0
    dNdL[2, 2] = 4.0 * L3 - 1.0
    dNdL[2, 3] = -(4.0 * L4 - 1.0)
    dNdL[2, 4] = 0.0
    dNdL[2, 5] = 4.0 * L2
    dNdL[2, 6] = 4.0 * L1
    dNdL[2, 7] = -4.0 * L1
    dNdL[2, 8] = -4.0 * L2
    dNdL[2, 9] = 4.0 * (L4 - L3)

    return N, dNdL


def stiffness_matrix_tet10(nodes_xyz: np.ndarray, E: float, nu: float) -> np.ndarray:
    """Compute the 30×30 element stiffness matrix for a Tet10 element.

    Uses a 4-point Gauss rule on the reference tetrahedron.

    Parameters
    ----------
    nodes_xyz : (10, 3) float array
        Node coordinates in Cook et al. node ordering (corners first, then midside).
    E, nu : float
        Isotropic material parameters.

    Returns
    -------
    K : (30, 30) symmetric positive semi-definite stiffness matrix.

    HONEST: 4-point Gauss rule is exact for degree-2 integrands; the integrand
    here is degree 4 (Bᵀ C B with quadratic shape functions → quartic in general).
    A 5-point or higher rule gives slightly more accurate results.

    Reference: Cook et al. (2001) §6.6; Zienkiewicz & Taylor (2000) Table B.4.
    """
    nodes_xyz = np.asarray(nodes_xyz, dtype=float)
    if nodes_xyz.shape != (10, 3):
        raise ValueError("nodes_xyz must be (10, 3)")

    C = _elasticity_matrix(E, nu)
    K = np.zeros((30, 30))

    for (L1, L2, L3), w in zip(_TET10_GAUSS_PTS, _TET10_GAUSS_WGTS):
        N, dNdL = _tet10_shape_and_grad(L1, L2, L3)

        # Jacobian J (3×3): J_ij = sum_k dNdL[i,k] * xyz[k,j]
        J = dNdL @ nodes_xyz   # (3, 3)
        det_J = np.linalg.det(J)
        # NOTE: The barycentric (L1,L2,L3) natural coordinate Jacobian can be negative
        # for a positively-oriented physical element because the mapping convention
        # is J[row_xyz, col_L] = d(xyz[row])/d(L[col]), which gives det(J)=-1 for
        # the standard unit tet. Use abs(det_J) for integration (Cook §6.6 eq.6.6-2).
        abs_det_J = abs(det_J)
        if abs_det_J < 1e-20:
            raise ValueError(f"Degenerate Jacobian det≈0 at Gauss point; check node ordering")
        inv_J = np.linalg.inv(J)

        # ∂N/∂xyz = inv_J @ dNdL  (3×10)
        dNdxyz = inv_J @ dNdL

        # Build B matrix (6×30)
        B = np.zeros((6, 30))
        for a in range(10):
            col = 3 * a
            B[0, col + 0] = dNdxyz[0, a]
            B[1, col + 1] = dNdxyz[1, a]
            B[2, col + 2] = dNdxyz[2, a]
            B[3, col + 0] = dNdxyz[1, a]
            B[3, col + 1] = dNdxyz[0, a]
            B[4, col + 1] = dNdxyz[2, a]
            B[4, col + 2] = dNdxyz[1, a]
            B[5, col + 0] = dNdxyz[2, a]
            B[5, col + 2] = dNdxyz[0, a]

        # Integration weight for reference tet volume (1/6)
        K += w * abs_det_J / 6.0 * (B.T @ C @ B)

    return K


def mass_matrix_consistent_tet10(nodes_xyz: np.ndarray, density: float) -> np.ndarray:
    """Compute the 30×30 consistent mass matrix for a Tet10 element via Gauss quadrature.

    HONEST: Uses the same 4-point Gauss rule as stiffness; a higher-order rule
    would be needed for machine-precision mass integration.

    Reference: Cook et al. (2001) §11.2.
    """
    nodes_xyz = np.asarray(nodes_xyz, dtype=float)
    if nodes_xyz.shape != (10, 3):
        raise ValueError("nodes_xyz must be (10, 3)")

    M = np.zeros((30, 30))
    for (L1, L2, L3), w in zip(_TET10_GAUSS_PTS, _TET10_GAUSS_WGTS):
        N, dNdL = _tet10_shape_and_grad(L1, L2, L3)
        J = dNdL @ nodes_xyz
        abs_det_J = abs(np.linalg.det(J))

        # Build N_mat (3×30): block-diag of shape functions for u,v,w DOFs
        N_mat = np.zeros((3, 30))
        for a in range(10):
            N_mat[0, 3 * a + 0] = N[a]
            N_mat[1, 3 * a + 1] = N[a]
            N_mat[2, 3 * a + 2] = N[a]

        M += density * w * abs_det_J / 6.0 * (N_mat.T @ N_mat)
    return M


# ---------------------------------------------------------------------------
# Von Mises stress helper (works for both Tet4 and Tet10)
# ---------------------------------------------------------------------------

def von_mises_stress_tet4(
    nodes_xyz: np.ndarray,
    displacements: np.ndarray,
    E: float,
    nu: float,
) -> float:
    """Von Mises stress at the centroid of a Tet4 element.

    Parameters
    ----------
    nodes_xyz : (4, 3)
    displacements : (4, 3) or (12,) nodal displacements
    E, nu : float

    Returns
    -------
    float  Von Mises stress [Pa].

    HONEST: Constant-strain tet has the same stress everywhere; no extrapolation
    or smoothing is performed.

    Reference: Cook et al. (2001) §6.3.
    """
    nodes_xyz = np.asarray(nodes_xyz, dtype=float)
    d = np.asarray(displacements, dtype=float).ravel()
    if d.shape != (12,):
        raise ValueError("displacements must have 12 components (4 nodes × 3 DOFs)")

    _, B = _tet4_volume_and_B(nodes_xyz)
    C = _elasticity_matrix(E, nu)
    sigma = C @ (B @ d)   # 6-vector [σ_xx, σ_yy, σ_zz, τ_xy, τ_yz, τ_xz]

    sxx, syy, szz, txy, tyz, txz = sigma
    vm = np.sqrt(
        0.5 * ((sxx - syy)**2 + (syy - szz)**2 + (szz - sxx)**2 + 6.0 * (txy**2 + tyz**2 + txz**2))
    )
    return float(vm)
