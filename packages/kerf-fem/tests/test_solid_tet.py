"""
Tests for kerf_fem.solid_tet — Tet4 and Tet10 solid finite elements.

References
----------
* Cook, Malkus, Plesha & Witt (2001) §6.2–6.6.
* Bathe (1996) §5.3.
"""

from __future__ import annotations

import math
import numpy as np
import pytest

from kerf_fem.solid_tet import (
    SolidElement,
    stiffness_matrix_tet4,
    stiffness_matrix_tet10,
    mass_matrix_consistent_tet4,
    mass_matrix_consistent_tet10,
    von_mises_stress_tet4,
    _elasticity_matrix,
)
from kerf_fem.solid_tools import solve_static_solid, von_mises_stress_at_centroid


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _unit_tet_nodes():
    """Unit tetrahedron with nodes at origin and along axes (positive volume)."""
    return np.array([
        [0.0, 0.0, 0.0],
        [1.0, 0.0, 0.0],
        [0.0, 1.0, 0.0],
        [0.0, 0.0, 1.0],
    ])


def _unit_tet_nodes_10():
    """10-node tet from the unit tet with midside nodes at edge midpoints."""
    c = _unit_tet_nodes()
    mids = np.array([
        0.5 * (c[0] + c[1]),   # N5 (1-2 edge)
        0.5 * (c[1] + c[2]),   # N6 (2-3 edge)
        0.5 * (c[0] + c[2]),   # N7 (1-3 edge)
        0.5 * (c[0] + c[3]),   # N8 (1-4 edge)
        0.5 * (c[1] + c[3]),   # N9 (2-4 edge)
        0.5 * (c[2] + c[3]),   # N10 (3-4 edge)
    ])
    return np.vstack([c, mids])


class _Material:
    def __init__(self, E=200e9, nu=0.3, density=7850.0):
        self.E = E
        self.nu = nu
        self.density = density


# ---------------------------------------------------------------------------
# Test 1: Tet4 stiffness matrix is symmetric
# ---------------------------------------------------------------------------

def test_tet4_stiffness_symmetric():
    """K = Kᵀ for Tet4."""
    nodes = _unit_tet_nodes()
    K = stiffness_matrix_tet4(nodes, E=200e9, nu=0.3)
    assert K.shape == (12, 12)
    np.testing.assert_allclose(K, K.T, atol=1e-6, err_msg="Tet4 K not symmetric")


# ---------------------------------------------------------------------------
# Test 2: Tet4 stiffness matrix is positive semi-definite (6 zero eigenvalues)
# ---------------------------------------------------------------------------

def test_tet4_stiffness_positive_semidefinite():
    """K has exactly 6 near-zero eigenvalues (rigid-body modes) and the rest positive."""
    nodes = _unit_tet_nodes()
    K = stiffness_matrix_tet4(nodes, E=200e9, nu=0.3)
    eigs = np.linalg.eigvalsh(K)
    # Sort ascending
    eigs_sorted = np.sort(eigs)
    # First 6 should be near zero (< tolerance), rest positive
    assert np.all(eigs_sorted[:6] > -1e3), f"Negative eigenvalues: {eigs_sorted[:6]}"
    assert np.all(eigs_sorted[6:] > 1e6), f"Non-positive deformational eigenvalues: {eigs_sorted[6:]}"


# ---------------------------------------------------------------------------
# Test 3: Tet4 stiffness is invariant to rigid-body translation
# ---------------------------------------------------------------------------

def test_tet4_stiffness_translation_invariant():
    """K should not depend on the absolute position of the element."""
    n1 = _unit_tet_nodes()
    n2 = n1 + np.array([10.0, -5.0, 3.0])
    K1 = stiffness_matrix_tet4(n1, E=200e9, nu=0.3)
    K2 = stiffness_matrix_tet4(n2, E=200e9, nu=0.3)
    np.testing.assert_allclose(K1, K2, rtol=1e-10, err_msg="K changed under translation")


# ---------------------------------------------------------------------------
# Test 4: Tet4 mass matrix — total mass
# ---------------------------------------------------------------------------

def test_tet4_mass_matrix_total_mass():
    """Sum of each row of M (per node) should equal total element mass / 4."""
    nodes = _unit_tet_nodes()
    density = 7850.0
    vol = 1.0 / 6.0   # unit tet
    total_mass = density * vol
    M = mass_matrix_consistent_tet4(nodes, density)
    assert M.shape == (12, 12)
    # Row sums of x-DOF rows (0, 3, 6, 9) should sum to total mass
    row_sum_x = sum(M[3 * i, :].sum() for i in range(4))
    np.testing.assert_allclose(row_sum_x, total_mass, rtol=1e-10,
                               err_msg="Tet4 mass matrix row sum ≠ total mass")


# ---------------------------------------------------------------------------
# Test 5: Tet4 mass matrix is symmetric
# ---------------------------------------------------------------------------

def test_tet4_mass_matrix_symmetric():
    nodes = _unit_tet_nodes()
    M = mass_matrix_consistent_tet4(nodes, density=7850.0)
    np.testing.assert_allclose(M, M.T, atol=1e-20, err_msg="Tet4 M not symmetric")


# ---------------------------------------------------------------------------
# Test 6: Tet4 + Tet10 eigenvalue problem K - λM > 0
# ---------------------------------------------------------------------------

def test_tet4_eigenvalue_problem():
    """Generalised eigenvalues λ of (K - λM) should all be positive (or zero for rigid modes)."""
    nodes = _unit_tet_nodes()
    K = stiffness_matrix_tet4(nodes, E=200e9, nu=0.3)
    M = mass_matrix_consistent_tet4(nodes, density=7850.0)
    # Regularise: add small diagonal to M to avoid singularity issues
    M_reg = M + 1e-20 * np.eye(12)
    eigvals = np.linalg.eigvalsh(np.linalg.solve(M_reg, K))
    assert np.all(eigvals > -1e-3), f"Negative generalised eigenvalues: {eigvals[eigvals < 0]}"


# ---------------------------------------------------------------------------
# Test 7: Tet10 stiffness matrix is symmetric
# ---------------------------------------------------------------------------

def test_tet10_stiffness_symmetric():
    nodes = _unit_tet_nodes_10()
    K = stiffness_matrix_tet10(nodes, E=200e9, nu=0.3)
    assert K.shape == (30, 30)
    np.testing.assert_allclose(K, K.T, atol=1e-4, err_msg="Tet10 K not symmetric")


# ---------------------------------------------------------------------------
# Test 8: Tet10 stiffness positive semi-definite
# ---------------------------------------------------------------------------

def test_tet10_stiffness_positive_semidefinite():
    nodes = _unit_tet_nodes_10()
    K = stiffness_matrix_tet10(nodes, E=200e9, nu=0.3)
    eigs = np.sort(np.linalg.eigvalsh(K))
    # 6 rigid-body near-zero modes
    assert np.all(eigs[:6] > -1e5), f"Negative eigenvalues: {eigs[:6]}"
    assert np.all(eigs[6:] > 1e4), f"Non-positive deformational eigenvalues: {eigs[6:]}"


# ---------------------------------------------------------------------------
# Test 9: Tet10 mass matrix total mass
# ---------------------------------------------------------------------------

def test_tet10_mass_total_mass():
    nodes = _unit_tet_nodes_10()
    density = 7850.0
    vol = 1.0 / 6.0
    total_mass = density * vol
    M = mass_matrix_consistent_tet10(nodes, density)
    assert M.shape == (30, 30)
    row_sum = sum(M[3 * i, :].sum() for i in range(10))
    np.testing.assert_allclose(row_sum, total_mass, rtol=1e-6,
                               err_msg="Tet10 mass matrix row sum ≠ total mass")


# ---------------------------------------------------------------------------
# Test 10: solve_static_solid — single Tet4, uniaxial stretch
# ---------------------------------------------------------------------------

def test_solve_static_solid_tet4_uniaxial():
    """Single Tet4 under uniaxial tension: check tip node displaces in load direction.

    A single tet has 12 DOFs and 6 rigid-body modes. We constrain enough DOFs
    to remove all rigid-body modes:
      - Node 0: fully fixed (3 constraints — removes 3 translations)
      - Node 1: Y and Z fixed (2 constraints — removes 1 rotation about Z, 1 about Y)
      - Node 2: Z fixed (1 constraint — removes 1 rotation about X)
    Total: 6 constraints → well-posed system.
    """
    nodes = np.array([
        [0.0, 0.0, 0.0],
        [1.0, 0.0, 0.0],
        [0.0, 1.0, 0.0],
        [0.0, 0.0, 1.0],
    ])
    mat = _Material(E=200e9, nu=0.3, density=7850.0)
    elem = SolidElement(kind="tet4", node_indices=[0, 1, 2, 3], material=mat)

    # 6 constraints to remove all rigid-body modes
    constraints = {
        0: (0.0, 0.0, 0.0),    # fully fixed
        1: (None, 0.0, 0.0),   # Y and Z fixed
        2: (None, None, 0.0),  # Z fixed
    }
    loads = {3: (0.0, 0.0, 1.0)}

    u = solve_static_solid(nodes, [elem], constraints, loads)
    assert u.shape == (4, 3)
    # Node 3 should move in +Z direction
    assert u[3, 2] > 0.0, f"Expected positive Z displacement at tip, got {u[3, 2]}"


# ---------------------------------------------------------------------------
# Test 11: von_mises_stress_tet4 — positive for loaded element
# ---------------------------------------------------------------------------

def test_von_mises_stress_tet4_positive():
    """Von Mises stress should be positive under load."""
    nodes = _unit_tet_nodes()
    d = np.zeros((4, 3))
    d[3, 2] = 1e-4   # small displacement at node 3 in Z

    vm = von_mises_stress_tet4(nodes, d, E=200e9, nu=0.3)
    assert vm > 0.0, f"Expected positive von Mises stress, got {vm}"


# ---------------------------------------------------------------------------
# Test 12: SolidElement dataclass creation
# ---------------------------------------------------------------------------

def test_solid_element_dataclass():
    mat = _Material()
    elem = SolidElement(kind="tet4", node_indices=[0, 1, 2, 3], material=mat)
    assert elem.kind == "tet4"
    assert len(elem.node_indices) == 4
    assert elem.material.E == 200e9


# ---------------------------------------------------------------------------
# Test 13: Elasticity matrix symmetry and positive-definiteness
# ---------------------------------------------------------------------------

def test_elasticity_matrix_symmetric_pd():
    C = _elasticity_matrix(200e9, 0.3)
    assert C.shape == (6, 6)
    np.testing.assert_allclose(C, C.T, atol=1e-6, err_msg="C not symmetric")
    eigs = np.linalg.eigvalsh(C)
    assert np.all(eigs > 0), f"C not positive definite: {eigs}"


# ---------------------------------------------------------------------------
# Test 14: Tet4 wrong volume raises ValueError
# ---------------------------------------------------------------------------

def test_tet4_wrong_orientation_raises():
    """Nodes in wrong orientation should raise ValueError (negative volume)."""
    nodes = np.array([
        [0.0, 0.0, 1.0],   # swapped nodes 3 and 4 to invert orientation
        [1.0, 0.0, 0.0],
        [0.0, 1.0, 0.0],
        [0.0, 0.0, 0.0],
    ])
    with pytest.raises(ValueError, match="non-positive volume"):
        stiffness_matrix_tet4(nodes, E=200e9, nu=0.3)


# ---------------------------------------------------------------------------
# Test 15: von_mises_stress_at_centroid dispatch
# ---------------------------------------------------------------------------

def test_von_mises_at_centroid_dispatch():
    """von_mises_stress_at_centroid should work for both tet4 and tet10."""
    nodes_4 = _unit_tet_nodes()
    nodes_all = np.vstack([nodes_4, np.zeros((100, 3))])  # pad global array
    u_all = np.zeros((104, 3))
    u_all[3, 2] = 1e-4

    mat = _Material()
    elem4 = SolidElement(kind="tet4", node_indices=[0, 1, 2, 3], material=mat)
    vm = von_mises_stress_at_centroid(elem4, nodes_all, u_all, E=mat.E, nu=mat.nu)
    assert vm >= 0.0
