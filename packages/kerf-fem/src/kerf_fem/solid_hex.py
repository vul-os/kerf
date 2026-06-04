"""
kerf_fem.solid_hex — 8-node and 20-node hexahedral solid finite elements.

Implements:
  * Hex8  — 8-node trilinear isoparametric hexahedron (2×2×2 Gauss quadrature)
  * Hex20 — 20-node serendipity hexahedron (3×3×3 Gauss quadrature)

DOF convention: 3 translational DOFs per node (u, v, w) in global X, Y, Z.
Hex8:  24×24 stiffness and mass matrices.
Hex20: 60×60 stiffness and mass matrices.

References
----------
* Cook, Malkus, Plesha & Witt, "Concepts and Applications of Finite Element
  Analysis", 4th ed. (2001), §6.7–§6.9 (hexahedral elements).
* Bathe, "Finite Element Procedures" (1996), §5.3.2 (3-D isoparametric).
* Hughes, "The Finite Element Method" (1987), §3.4–§3.6.

All routines use pure numpy (no external FEM libraries).
HONEST: Hex8 with 2×2×2 integration can exhibit volumetric locking for
nearly-incompressible materials (ν → 0.5); use reduced/selective integration or
higher-order elements in that regime.
"""

from __future__ import annotations

import numpy as np

from kerf_fem.solid_tet import _elasticity_matrix, SolidElement  # re-export SolidElement


# ---------------------------------------------------------------------------
# 1-D Gauss points and weights
# ---------------------------------------------------------------------------

_GAUSS_1D_2 = np.array([-1.0 / np.sqrt(3.0), 1.0 / np.sqrt(3.0)])
_GAUSS_W_2 = np.array([1.0, 1.0])

_GAUSS_1D_3 = np.array([-np.sqrt(0.6), 0.0, np.sqrt(0.6)])
_GAUSS_W_3 = np.array([5.0 / 9.0, 8.0 / 9.0, 5.0 / 9.0])


# ---------------------------------------------------------------------------
# Hex8 shape functions and derivatives
# ---------------------------------------------------------------------------

# Node ordering for Hex8 (Cook et al. 2001, §6.7, Fig 6.7-1):
#   nodes 0-3 on ζ=-1 face (bottom), 4-7 on ζ=+1 face (top)
#   within each face: counterclockwise viewed from outside
#
# Natural coords (ξ, η, ζ) ∈ [-1,1]³
_HEX8_NODES_NATURAL = np.array([
    [-1, -1, -1],   # 0
    [ 1, -1, -1],   # 1
    [ 1,  1, -1],   # 2
    [-1,  1, -1],   # 3
    [-1, -1,  1],   # 4
    [ 1, -1,  1],   # 5
    [ 1,  1,  1],   # 6
    [-1,  1,  1],   # 7
], dtype=float)


def _hex8_shape_and_grad(xi: float, eta: float, zeta: float) -> tuple[np.ndarray, np.ndarray]:
    """Shape functions and natural-coordinate gradients for Hex8.

    Returns
    -------
    N    : (8,)   shape function values
    dNds : (3, 8) ∂N/∂ξ, ∂N/∂η, ∂N/∂ζ  (rows = ξ, η, ζ)

    Reference: Cook et al. (2001) eq. 6.7-1.
    """
    xi_i, eta_i, zeta_i = _HEX8_NODES_NATURAL.T
    N = 0.125 * (1 + xi_i * xi) * (1 + eta_i * eta) * (1 + zeta_i * zeta)

    dNds = np.zeros((3, 8))
    dNds[0] = 0.125 * xi_i * (1 + eta_i * eta) * (1 + zeta_i * zeta)
    dNds[1] = 0.125 * (1 + xi_i * xi) * eta_i * (1 + zeta_i * zeta)
    dNds[2] = 0.125 * (1 + xi_i * xi) * (1 + eta_i * eta) * zeta_i

    return N, dNds


def stiffness_matrix_hex8(nodes_xyz: np.ndarray, E: float, nu: float) -> np.ndarray:
    """Compute the 24×24 element stiffness matrix for a Hex8 element.

    Uses 2×2×2 Gauss quadrature (8 integration points), which is the standard
    full integration rule for trilinear hex elements.

    Parameters
    ----------
    nodes_xyz : (8, 3) float array
        Node coordinates in Cook et al. ordering (corners, bottom face CCW then top).
    E : float
        Young's modulus [Pa].
    nu : float
        Poisson's ratio.

    Returns
    -------
    K : (24, 24) symmetric positive semi-definite stiffness matrix.

    HONEST: Full 2×2×2 integration can produce volumetric locking for ν → 0.5.
    For nearly-incompressible materials use selective/reduced integration.

    Reference: Cook et al. (2001) §6.7–6.8, eq. 6.8-1.
    """
    nodes_xyz = np.asarray(nodes_xyz, dtype=float)
    if nodes_xyz.shape != (8, 3):
        raise ValueError("nodes_xyz must be (8, 3)")

    C = _elasticity_matrix(E, nu)
    K = np.zeros((24, 24))

    for i, xi in enumerate(_GAUSS_1D_2):
        for j, eta in enumerate(_GAUSS_1D_2):
            for k, zeta in enumerate(_GAUSS_1D_2):
                w = _GAUSS_W_2[i] * _GAUSS_W_2[j] * _GAUSS_W_2[k]
                _, dNds = _hex8_shape_and_grad(xi, eta, zeta)

                J = dNds @ nodes_xyz  # (3, 3)
                det_J = np.linalg.det(J)
                if det_J <= 0.0:
                    raise ValueError(f"Non-positive Jacobian det={det_J:.6e}")
                inv_J = np.linalg.inv(J)

                dNdxyz = inv_J @ dNds  # (3, 8)

                B = np.zeros((6, 24))
                for a in range(8):
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

                K += w * det_J * (B.T @ C @ B)

    return K


def mass_matrix_consistent_hex8(nodes_xyz: np.ndarray, density: float) -> np.ndarray:
    """Compute the 24×24 consistent mass matrix for a Hex8 element.

    Uses 2×2×2 Gauss quadrature.

    HONEST: Consistent mass matrix requires solving a linear system for implicit
    dynamics; lumped mass (row-sum or HRZ) is commonly used instead.

    Reference: Cook et al. (2001) §11.2, eq. 11.2-2.
    """
    nodes_xyz = np.asarray(nodes_xyz, dtype=float)
    if nodes_xyz.shape != (8, 3):
        raise ValueError("nodes_xyz must be (8, 3)")

    M = np.zeros((24, 24))
    for i, xi in enumerate(_GAUSS_1D_2):
        for j, eta in enumerate(_GAUSS_1D_2):
            for k, zeta in enumerate(_GAUSS_1D_2):
                w = _GAUSS_W_2[i] * _GAUSS_W_2[j] * _GAUSS_W_2[k]
                N, dNds = _hex8_shape_and_grad(xi, eta, zeta)

                J = dNds @ nodes_xyz
                det_J = np.linalg.det(J)

                N_mat = np.zeros((3, 24))
                for a in range(8):
                    N_mat[0, 3 * a + 0] = N[a]
                    N_mat[1, 3 * a + 1] = N[a]
                    N_mat[2, 3 * a + 2] = N[a]

                M += density * w * det_J * (N_mat.T @ N_mat)
    return M


# ---------------------------------------------------------------------------
# Hex20 — 20-node serendipity hexahedron
# ---------------------------------------------------------------------------

# Node numbering: 8 corners (same as Hex8) + 12 midside nodes.
# Midside nodes: 8,9,10,11 on ζ=-1 face edges; 12-15 on vertical edges;
# 16-19 on ζ=+1 face edges.
# See Cook et al. (2001) Fig 6.9-1.
_HEX20_CORNERS = np.array([
    [-1, -1, -1], [ 1, -1, -1], [ 1,  1, -1], [-1,  1, -1],  # 0-3
    [-1, -1,  1], [ 1, -1,  1], [ 1,  1,  1], [-1,  1,  1],  # 4-7
], dtype=float)

# Midside node natural coords
_HEX20_MIDS = np.array([
    [ 0, -1, -1],  # 8  (between 0 and 1)
    [ 1,  0, -1],  # 9  (between 1 and 2)
    [ 0,  1, -1],  # 10 (between 2 and 3)
    [-1,  0, -1],  # 11 (between 3 and 0)
    [-1, -1,  0],  # 12 (between 0 and 4)
    [ 1, -1,  0],  # 13 (between 1 and 5)
    [ 1,  1,  0],  # 14 (between 2 and 6)
    [-1,  1,  0],  # 15 (between 3 and 7)
    [ 0, -1,  1],  # 16 (between 4 and 5)
    [ 1,  0,  1],  # 17 (between 5 and 6)
    [ 0,  1,  1],  # 18 (between 6 and 7)
    [-1,  0,  1],  # 19 (between 7 and 4)
], dtype=float)

_HEX20_NATURAL = np.vstack([_HEX20_CORNERS, _HEX20_MIDS])


def _hex20_shape_and_grad(xi: float, eta: float, zeta: float) -> tuple[np.ndarray, np.ndarray]:
    """Shape functions and natural-coordinate gradients for Hex20.

    Reference: Cook et al. (2001) eq. 6.9-1 (serendipity hex).

    Returns N (20,) and dNds (3, 20).
    """
    N = np.zeros(20)
    dNds = np.zeros((3, 20))

    # Corner nodes (i = 0..7): N_i = (1+ξ_i ξ)(1+η_i η)(1+ζ_i ζ)(ξ_i ξ+η_i η+ζ_i ζ-2)/8
    for i in range(8):
        xi_i, eta_i, zeta_i = _HEX20_CORNERS[i]
        f_xi = 1.0 + xi_i * xi
        f_eta = 1.0 + eta_i * eta
        f_zeta = 1.0 + zeta_i * zeta
        q = xi_i * xi + eta_i * eta + zeta_i * zeta - 2.0
        N[i] = 0.125 * f_xi * f_eta * f_zeta * q

        dNds[0, i] = 0.125 * (xi_i * f_eta * f_zeta * q + f_xi * f_eta * f_zeta * xi_i)
        dNds[1, i] = 0.125 * (f_xi * eta_i * f_zeta * q + f_xi * f_eta * f_zeta * eta_i)
        dNds[2, i] = 0.125 * (f_xi * f_eta * zeta_i * q + f_xi * f_eta * f_zeta * zeta_i)

    # Midside nodes: split into three groups based on which coordinate is 0
    for i in range(12):
        idx = i + 8
        xi_m, eta_m, zeta_m = _HEX20_MIDS[i]

        if xi_m == 0.0:
            # ξ_m = 0 → N = (1-ξ²)(1+η_m η)(1+ζ_m ζ)/4
            f_eta = 1.0 + eta_m * eta
            f_zeta = 1.0 + zeta_m * zeta
            N[idx] = 0.25 * (1.0 - xi**2) * f_eta * f_zeta
            dNds[0, idx] = 0.25 * (-2.0 * xi) * f_eta * f_zeta
            dNds[1, idx] = 0.25 * (1.0 - xi**2) * eta_m * f_zeta
            dNds[2, idx] = 0.25 * (1.0 - xi**2) * f_eta * zeta_m
        elif eta_m == 0.0:
            # η_m = 0 → N = (1+ξ_m ξ)(1-η²)(1+ζ_m ζ)/4
            f_xi = 1.0 + xi_m * xi
            f_zeta = 1.0 + zeta_m * zeta
            N[idx] = 0.25 * f_xi * (1.0 - eta**2) * f_zeta
            dNds[0, idx] = 0.25 * xi_m * (1.0 - eta**2) * f_zeta
            dNds[1, idx] = 0.25 * f_xi * (-2.0 * eta) * f_zeta
            dNds[2, idx] = 0.25 * f_xi * (1.0 - eta**2) * zeta_m
        else:  # zeta_m == 0
            # ζ_m = 0 → N = (1+ξ_m ξ)(1+η_m η)(1-ζ²)/4
            f_xi = 1.0 + xi_m * xi
            f_eta = 1.0 + eta_m * eta
            N[idx] = 0.25 * f_xi * f_eta * (1.0 - zeta**2)
            dNds[0, idx] = 0.25 * xi_m * f_eta * (1.0 - zeta**2)
            dNds[1, idx] = 0.25 * f_xi * eta_m * (1.0 - zeta**2)
            dNds[2, idx] = 0.25 * f_xi * f_eta * (-2.0 * zeta)

    return N, dNds


def stiffness_matrix_hex20(nodes_xyz: np.ndarray, E: float, nu: float) -> np.ndarray:
    """Compute the 60×60 element stiffness matrix for a Hex20 element.

    Uses 3×3×3 Gauss quadrature (27 integration points), which is full integration
    for the serendipity hexahedron.

    Parameters
    ----------
    nodes_xyz : (20, 3) float array
        Node coordinates in Cook et al. Hex20 node ordering.
    E, nu : float
        Isotropic material parameters.

    Returns
    -------
    K : (60, 60) symmetric positive semi-definite stiffness matrix.

    HONEST: 3×3×3 full integration gives exact stiffness for regular hexahedra;
    distorted elements may benefit from selective reduced integration.

    Reference: Cook et al. (2001) §6.9.
    """
    nodes_xyz = np.asarray(nodes_xyz, dtype=float)
    if nodes_xyz.shape != (20, 3):
        raise ValueError("nodes_xyz must be (20, 3)")

    C = _elasticity_matrix(E, nu)
    K = np.zeros((60, 60))

    for i, xi in enumerate(_GAUSS_1D_3):
        for j, eta in enumerate(_GAUSS_1D_3):
            for k, zeta in enumerate(_GAUSS_1D_3):
                w = _GAUSS_W_3[i] * _GAUSS_W_3[j] * _GAUSS_W_3[k]
                _, dNds = _hex20_shape_and_grad(xi, eta, zeta)

                J = dNds @ nodes_xyz
                det_J = np.linalg.det(J)
                if det_J <= 0.0:
                    raise ValueError(f"Non-positive Jacobian det={det_J:.6e}")
                inv_J = np.linalg.inv(J)

                dNdxyz = inv_J @ dNds  # (3, 20)

                B = np.zeros((6, 60))
                for a in range(20):
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

                K += w * det_J * (B.T @ C @ B)

    return K


def mass_matrix_consistent_hex20(nodes_xyz: np.ndarray, density: float) -> np.ndarray:
    """Compute the 60×60 consistent mass matrix for Hex20 via 3×3×3 Gauss quadrature.

    HONEST: As with Hex8, lumped mass is often preferred in explicit dynamics.

    Reference: Cook et al. (2001) §11.2.
    """
    nodes_xyz = np.asarray(nodes_xyz, dtype=float)
    if nodes_xyz.shape != (20, 3):
        raise ValueError("nodes_xyz must be (20, 3)")

    M = np.zeros((60, 60))
    for i, xi in enumerate(_GAUSS_1D_3):
        for j, eta in enumerate(_GAUSS_1D_3):
            for k, zeta in enumerate(_GAUSS_1D_3):
                w = _GAUSS_W_3[i] * _GAUSS_W_3[j] * _GAUSS_W_3[k]
                N, dNds = _hex20_shape_and_grad(xi, eta, zeta)

                J = dNds @ nodes_xyz
                det_J = np.linalg.det(J)

                N_mat = np.zeros((3, 60))
                for a in range(20):
                    N_mat[0, 3 * a + 0] = N[a]
                    N_mat[1, 3 * a + 1] = N[a]
                    N_mat[2, 3 * a + 2] = N[a]

                M += density * w * det_J * (N_mat.T @ N_mat)
    return M


# ---------------------------------------------------------------------------
# Von Mises stress helper for Hex8 at the element centroid
# ---------------------------------------------------------------------------

def von_mises_stress_hex8(
    nodes_xyz: np.ndarray,
    displacements: np.ndarray,
    E: float,
    nu: float,
) -> float:
    """Von Mises stress at the centroid (ξ=η=ζ=0) of a Hex8 element.

    Parameters
    ----------
    nodes_xyz : (8, 3)
    displacements : (8, 3) or (24,) nodal displacements
    E, nu : float

    Returns
    -------
    float  Von Mises stress [Pa].

    HONEST: Centroidal stress from full-integration Hex8 may be less accurate
    than superconvergent Barlow points (ξ=η=ζ=±1/√3); use stress smoothing
    (e.g. SPR) for post-processing in production.

    Reference: Cook et al. (2001) §6.8.
    """
    nodes_xyz = np.asarray(nodes_xyz, dtype=float)
    d = np.asarray(displacements, dtype=float).ravel()
    if d.shape != (24,):
        raise ValueError("displacements must have 24 components (8 nodes × 3 DOFs)")

    _, dNds = _hex8_shape_and_grad(0.0, 0.0, 0.0)
    J = dNds @ nodes_xyz
    inv_J = np.linalg.inv(J)
    dNdxyz = inv_J @ dNds

    B = np.zeros((6, 24))
    for a in range(8):
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

    C = _elasticity_matrix(E, nu)
    sigma = C @ (B @ d)
    sxx, syy, szz, txy, tyz, txz = sigma
    vm = np.sqrt(
        0.5 * ((sxx - syy)**2 + (syy - szz)**2 + (szz - sxx)**2
               + 6.0 * (txy**2 + tyz**2 + txz**2))
    )
    return float(vm)
