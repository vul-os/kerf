"""
kerf_fem.solid_tools — Global assembly and static solver for 3-D solid FEM.

Provides:
  solve_static_solid — assemble global K from SolidElement list, apply BCs, solve.
  von_mises_stress_at_centroid — dispatch to element-type-specific stress routine.

References
----------
* Cook, Malkus, Plesha & Witt, "Concepts and Applications of Finite Element
  Analysis", 4th ed. (2001), §2.4 (direct stiffness assembly), §2.5 (BCs).
* Bathe, "Finite Element Procedures" (1996), §4.2 (global assembly).

HONEST: This is a direct-stiffness assembly + dense solve (numpy.linalg.solve).
For production meshes with >10k DOFs use a sparse solver (scipy.sparse.linalg or
PETSc). The sparse pathway is not implemented here.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from kerf_fem.solid_tet import (
    SolidElement,
    stiffness_matrix_tet4,
    stiffness_matrix_tet10,
    mass_matrix_consistent_tet4,
    mass_matrix_consistent_tet10,
    von_mises_stress_tet4,
    _elasticity_matrix,
)
from kerf_fem.solid_hex import (
    stiffness_matrix_hex8,
    stiffness_matrix_hex20,
    mass_matrix_consistent_hex8,
    mass_matrix_consistent_hex20,
    von_mises_stress_hex8,
)


# ---------------------------------------------------------------------------
# Element dispatch tables
# ---------------------------------------------------------------------------

_N_NODES = {"tet4": 4, "tet10": 10, "hex8": 8, "hex20": 20}
_N_DOFS = {k: 3 * v for k, v in _N_NODES.items()}


def _element_ke(elem: SolidElement, nodes: np.ndarray) -> np.ndarray:
    """Return the element stiffness matrix for *elem*."""
    xyz = nodes[elem.node_indices]
    E = elem.material.E
    nu = elem.material.nu
    dispatch = {
        "tet4":  stiffness_matrix_tet4,
        "tet10": stiffness_matrix_tet10,
        "hex8":  stiffness_matrix_hex8,
        "hex20": stiffness_matrix_hex20,
    }
    fn = dispatch.get(elem.kind)
    if fn is None:
        raise ValueError(f"Unknown element kind '{elem.kind}'")
    return fn(xyz, E, nu)


def _element_me(elem: SolidElement, nodes: np.ndarray) -> np.ndarray:
    """Return the consistent mass matrix for *elem*."""
    xyz = nodes[elem.node_indices]
    density = elem.material.density
    dispatch = {
        "tet4":  mass_matrix_consistent_tet4,
        "tet10": mass_matrix_consistent_tet10,
        "hex8":  mass_matrix_consistent_hex8,
        "hex20": mass_matrix_consistent_hex20,
    }
    fn = dispatch.get(elem.kind)
    if fn is None:
        raise ValueError(f"Unknown element kind '{elem.kind}'")
    return fn(xyz, density)


# ---------------------------------------------------------------------------
# Global assembly
# ---------------------------------------------------------------------------

def _assemble_global_K(
    nodes: np.ndarray,
    elements: list[SolidElement],
    n_dof_total: int,
) -> np.ndarray:
    """Direct stiffness assembly of global stiffness matrix.

    Reference: Cook et al. (2001) §2.4, eq. 2.4-1.
    """
    K = np.zeros((n_dof_total, n_dof_total))
    for elem in elements:
        Ke = _element_ke(elem, nodes)
        n_nodes = _N_NODES[elem.kind]
        # Scatter Ke into K using connectivity (node indices → global DOF indices)
        dof_map = []
        for ni in elem.node_indices[:n_nodes]:
            dof_map.extend([3 * ni, 3 * ni + 1, 3 * ni + 2])
        dof_map = np.array(dof_map, dtype=int)
        np.add.at(K, np.ix_(dof_map, dof_map), Ke)
    return K


def _assemble_global_M(
    nodes: np.ndarray,
    elements: list[SolidElement],
    n_dof_total: int,
) -> np.ndarray:
    """Direct stiffness assembly of global consistent mass matrix."""
    M = np.zeros((n_dof_total, n_dof_total))
    for elem in elements:
        Me = _element_me(elem, nodes)
        n_nodes = _N_NODES[elem.kind]
        dof_map = []
        for ni in elem.node_indices[:n_nodes]:
            dof_map.extend([3 * ni, 3 * ni + 1, 3 * ni + 2])
        dof_map = np.array(dof_map, dtype=int)
        np.add.at(M, np.ix_(dof_map, dof_map), Me)
    return M


# ---------------------------------------------------------------------------
# Boundary condition application (penalty method for simplicity)
# ---------------------------------------------------------------------------

def _apply_dirichlet_penalty(
    K: np.ndarray,
    f: np.ndarray,
    constrained_dofs: list[int],
    prescribed_values: list[float],
    penalty: float | None = None,
) -> None:
    """Apply Dirichlet BCs via penalty method (in-place).

    HONEST: The penalty method avoids modifying K's sparsity pattern but can
    ill-condition the system. Production solvers use elimination or Lagrange
    multipliers. Penalty is set to 1e6 × max(diag(K)) by default.

    Reference: Cook et al. (2001) §2.5.
    """
    if penalty is None:
        diag_max = np.max(np.diag(K))
        penalty = 1e6 * diag_max if diag_max > 0 else 1e20

    for dof, val in zip(constrained_dofs, prescribed_values):
        K[dof, dof] += penalty
        f[dof] += penalty * val


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def solve_static_solid(
    nodes: np.ndarray,
    elements: list[SolidElement],
    constraints: dict[int, tuple],
    loads: dict[int, tuple],
) -> np.ndarray:
    """Assemble and solve the linear static FEM system K u = f.

    Parameters
    ----------
    nodes : (N, 3) float array
        Global nodal coordinates.
    elements : list[SolidElement]
        List of element descriptors (kind, node_indices, material).
    constraints : dict {node_id: (Dx, Dy, Dz)}
        Prescribed displacements per node. Use None to leave a DOF free.
        Example: {0: (0.0, 0.0, 0.0)} fixes node 0 in all directions.
        Example: {0: (0.0, None, 0.0)} fixes only X and Z.
    loads : dict {node_id: (Fx, Fy, Fz)}
        Nodal forces [N] per node. Unspecified nodes have zero load.

    Returns
    -------
    u : (N, 3) float array
        Nodal displacements [m].

    Raises
    ------
    ValueError
        If the system is singular (no constraints applied, or degenerate mesh).

    HONEST: Dense assembly + numpy.linalg.solve; practical only for small meshes
    (< ~500 nodes). For large meshes integrate with scipy.sparse or PETSc.

    Reference: Cook et al. (2001) §2.4–2.5.
    """
    nodes = np.asarray(nodes, dtype=float)
    n_nodes = nodes.shape[0]
    n_dof = 3 * n_nodes

    # Assemble global stiffness
    K = _assemble_global_K(nodes, elements, n_dof)

    # Build load vector
    f = np.zeros(n_dof)
    for node_id, (fx, fy, fz) in loads.items():
        f[3 * node_id + 0] += fx
        f[3 * node_id + 1] += fy
        f[3 * node_id + 2] += fz

    # Apply boundary conditions
    constrained_dofs: list[int] = []
    prescribed_values: list[float] = []
    for node_id, dof_vals in constraints.items():
        for dof_offset, val in enumerate(dof_vals):
            if val is not None:
                constrained_dofs.append(3 * node_id + dof_offset)
                prescribed_values.append(float(val))

    _apply_dirichlet_penalty(K, f, constrained_dofs, prescribed_values)

    # Solve K u = f
    try:
        u_flat = np.linalg.solve(K, f)
    except np.linalg.LinAlgError as exc:
        raise ValueError(
            "Stiffness matrix is singular. Ensure sufficient constraints are applied."
        ) from exc

    return u_flat.reshape(n_nodes, 3)


def von_mises_stress_at_centroid(
    element: SolidElement,
    nodes: np.ndarray,
    displacements: np.ndarray,
    E: float,
    nu: float,
) -> float:
    """Compute the von Mises stress at the centroid of a solid element.

    Parameters
    ----------
    element : SolidElement
    nodes : (N, 3) global nodal coordinates
    displacements : (N, 3) or (N*3,) global nodal displacement array
    E, nu : float material parameters

    Returns
    -------
    float  Von Mises stress [Pa] at element centroid.

    HONEST: For higher-order elements (Tet10, Hex20) this evaluates stress at the
    geometric centroid in natural coordinates (L1=L2=L3=L4=0.25 for tet,
    ξ=η=ζ=0 for hex). Superconvergent Barlow points give more accurate stresses
    for Hex8. For Tet4, stress is constant so the centroid is exact.

    Reference: Cook et al. (2001) §6.8, §6.3.
    """
    nodes = np.asarray(nodes, dtype=float)
    u_flat = np.asarray(displacements, dtype=float).ravel()

    n_nodes_elem = _N_NODES[element.kind]
    d_elem = np.zeros(3 * n_nodes_elem)
    for local_i, global_i in enumerate(element.node_indices[:n_nodes_elem]):
        d_elem[3 * local_i: 3 * local_i + 3] = u_flat[3 * global_i: 3 * global_i + 3]

    xyz_elem = nodes[element.node_indices[:n_nodes_elem]]

    if element.kind == "tet4":
        return von_mises_stress_tet4(xyz_elem, d_elem, E, nu)
    elif element.kind == "hex8":
        return von_mises_stress_hex8(xyz_elem, d_elem, E, nu)
    elif element.kind in ("tet10", "hex20"):
        # General centroid stress via B-matrix at centroid
        return _von_mises_at_natural_centroid(element, xyz_elem, d_elem, E, nu)
    else:
        raise ValueError(f"Unknown element kind '{element.kind}'")


def _von_mises_at_natural_centroid(
    element: SolidElement,
    xyz_elem: np.ndarray,
    d_elem: np.ndarray,
    E: float,
    nu: float,
) -> float:
    """Von Mises stress at natural coordinate centroid for higher-order elements."""
    from kerf_fem.solid_tet import _tet10_shape_and_grad
    from kerf_fem.solid_hex import _hex20_shape_and_grad

    C = _elasticity_matrix(E, nu)

    if element.kind == "tet10":
        # Centroid: L1=L2=L3=L4=0.25
        L = 0.25
        _, dNdL = _tet10_shape_and_grad(L, L, L)
        J = dNdL @ xyz_elem
        # Note: tet barycentric Jacobian can have negative det for valid elements; use inv directly
        inv_J = np.linalg.inv(J)
        dNdxyz = inv_J @ dNdL
        n = 10
    else:  # hex20
        _, dNds = _hex20_shape_and_grad(0.0, 0.0, 0.0)
        J = dNds @ xyz_elem
        inv_J = np.linalg.inv(J)
        dNdxyz = inv_J @ dNds
        n = 20

    B = np.zeros((6, 3 * n))
    for a in range(n):
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

    sigma = C @ (B @ d_elem)
    sxx, syy, szz, txy, tyz, txz = sigma
    vm = np.sqrt(
        0.5 * ((sxx - syy)**2 + (syy - szz)**2 + (szz - sxx)**2
               + 6.0 * (txy**2 + tyz**2 + txz**2))
    )
    return float(vm)
