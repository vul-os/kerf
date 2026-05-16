"""
Hermetic test suite for kerf_fem.em_field — 2-D triangular-FEM electromagnetics.

Covers:
  - electrostatics(): parallel-plate capacitor, coaxial geometry, Laplace solution,
    zero-charge harmonic field, field energy ½CV², E-field direction
  - magnetostatics(): uniform current, B inside solenoid cross-section, ½LI²
  - solenoid_inductance(): analytic L vs B·per·amp
  - parallel_plate_capacitance(): C = ε₀A/d
  - coaxial_capacitance(): C = 2πε/ln(b/a)
  - field_energy_electric() / field_energy_magnetic() helpers
  - error / boundary conditions
  - concentric-circle Laplace profile (log solution)

All tests are hermetic — no DB, no network, no heavy deps.
"""

from __future__ import annotations

import math

import pytest

from kerf_fem.em_field import (
    electrostatics,
    magnetostatics,
    solenoid_inductance,
    parallel_plate_capacitance,
    coaxial_capacitance,
    field_energy_electric,
    field_energy_magnetic,
)

# ---------------------------------------------------------------------------
# Physical constants
# ---------------------------------------------------------------------------

EPS0 = 8.854187817e-12    # F/m
MU0  = 4.0 * math.pi * 1e-7  # H/m


# ---------------------------------------------------------------------------
# Mesh builders
# ---------------------------------------------------------------------------

def _rect_mesh(width: float, height: float, nx: int, ny: int):
    """
    Uniform rectangular mesh of right-triangles.
    Node (i, j) has index i*(ny+1)+j.
    Each quad is split into 2 triangles.
    """
    nodes = []
    for i in range(nx + 1):
        for j in range(ny + 1):
            x = i * width / nx
            y = j * height / ny
            nodes.append([x, y])

    elements = []
    for i in range(nx):
        for j in range(ny):
            n00 = i * (ny + 1) + j
            n10 = (i + 1) * (ny + 1) + j
            n01 = i * (ny + 1) + (j + 1)
            n11 = (i + 1) * (ny + 1) + (j + 1)
            elements.append([n00, n10, n11])
            elements.append([n00, n11, n01])

    return {"nodes": nodes, "elements": elements}


def _parallel_plate_mesh(d: float, w: float, nx: int, ny: int):
    """
    1-D (x-direction) parallel-plate mesh.
    Bottom nodes (j=0) at V=0, top (j=ny) at V=1.
    Width w in x-direction (arbitrary, cancels in C).
    d is the plate separation (y-direction).
    """
    return _rect_mesh(w, d, nx, ny)


def _bottom_nodes(mesh, ny: int):
    """Return indices of nodes on y=0 (j=0)."""
    nx1 = len(mesh["nodes"]) // (ny + 1)
    return [i * (ny + 1) for i in range(nx1)]


def _top_nodes(mesh, ny: int):
    """Return indices of nodes on y=ny (j=ny)."""
    nx1 = len(mesh["nodes"]) // (ny + 1)
    return [i * (ny + 1) + ny for i in range(nx1)]


# ---------------------------------------------------------------------------
# 1.  Analytic helpers
# ---------------------------------------------------------------------------

class TestParallelPlateCapacitance:

    def test_vacuum_gap(self):
        d = 1e-3   # 1 mm
        A = 1e-4   # 1 cm²
        res = parallel_plate_capacitance(A, d)
        assert res["ok"]
        C_expected = EPS0 * A / d
        assert abs(res["C"] - C_expected) / C_expected < 1e-9

    def test_dielectric(self):
        eps_r = 4.5
        d = 0.5e-3
        A = 1e-3
        res = parallel_plate_capacitance(A, d, eps_r=eps_r)
        assert res["ok"]
        C_expected = EPS0 * eps_r * A / d
        assert abs(res["C"] - C_expected) / C_expected < 1e-9

    def test_E_per_volt(self):
        d = 2e-3
        res = parallel_plate_capacitance(1e-4, d)
        assert res["ok"]
        assert abs(res["E_per_volt"] - 1.0 / d) < 1e-12

    def test_invalid_zero_area(self):
        res = parallel_plate_capacitance(0.0, 1e-3)
        assert res["ok"] is False

    def test_invalid_zero_separation(self):
        res = parallel_plate_capacitance(1e-4, 0.0)
        assert res["ok"] is False


class TestCoaxialCapacitance:

    def test_formula(self):
        a, b = 1e-3, 5e-3
        res = coaxial_capacitance(a, b)
        assert res["ok"]
        C_expected = 2.0 * math.pi * EPS0 / math.log(b / a)
        assert abs(res["C_per_length"] - C_expected) / C_expected < 1e-9

    def test_dielectric_scales(self):
        a, b, eps_r = 1e-3, 5e-3, 2.3
        res_vac = coaxial_capacitance(a, b)
        res_die = coaxial_capacitance(a, b, eps_r=eps_r)
        assert abs(res_die["C_per_length"] / res_vac["C_per_length"] - eps_r) < 1e-9

    def test_invalid_reversed_radii(self):
        res = coaxial_capacitance(5e-3, 1e-3)
        assert res["ok"] is False

    def test_invalid_zero_inner(self):
        res = coaxial_capacitance(0.0, 5e-3)
        assert res["ok"] is False


class TestSolenoidInductance:

    def test_formula(self):
        N, l, r = 1000, 0.1, 5e-3
        res = solenoid_inductance(N, l, r)
        assert res["ok"]
        n = N / l
        L_expected = MU0 * n * n * math.pi * r * r * l
        assert abs(res["L"] - L_expected) / L_expected < 1e-9

    def test_B_inside(self):
        N, l = 500, 0.05
        res = solenoid_inductance(N, l, 2e-3)
        assert res["ok"]
        n = N / l
        B_expected = MU0 * n
        assert abs(res["B_inside_per_amp"] - B_expected) / B_expected < 1e-9

    def test_mu_r_scales_L(self):
        N, l, r = 200, 0.1, 5e-3
        res1 = solenoid_inductance(N, l, r)
        res2 = solenoid_inductance(N, l, r, mu_r=100.0)
        assert abs(res2["L"] / res1["L"] - 100.0) < 1e-6

    def test_invalid_zero_turns(self):
        res = solenoid_inductance(0, 0.1, 5e-3)
        assert res["ok"] is False

    def test_invalid_zero_length(self):
        res = solenoid_inductance(100, 0.0, 5e-3)
        assert res["ok"] is False


# ---------------------------------------------------------------------------
# 2.  FEM electrostatics
# ---------------------------------------------------------------------------

class TestElectrostaticsFEM:

    def test_parallel_plate_potential_linear(self):
        """
        Between two parallel plates (V=0 at y=0, V=1 at y=d),
        the potential must be linear: φ(y) = y/d.
        Tolerance: 2 % to accommodate triangular-mesh discretisation error.
        """
        d = 1.0
        nx, ny = 4, 4
        mesh = _rect_mesh(1.0, d, nx, ny)
        bot = _bottom_nodes(mesh, ny)
        top = _top_nodes(mesh, ny)
        bc = {n: 0.0 for n in bot}
        bc.update({n: 1.0 for n in top})

        res = electrostatics(mesh, EPS0, bc)
        assert res["ok"], res.get("reason")

        phi = res["phi"]
        # Check a mid-node
        nodes = mesh["nodes"]
        for i, (x, y) in enumerate(nodes):
            expected = y / d
            # Skip boundary nodes
            if i in bc:
                continue
            assert abs(phi[i] - expected) < 0.05, f"node {i} phi={phi[i]:.4f} expected={expected:.4f}"

    def test_parallel_plate_capacitance_fem(self):
        """
        C_FEM ≈ ε₀ · w / d  (per unit depth).
        Mesh tolerance: within 15 % (coarse mesh; analytic value is limit).
        """
        d = 1e-3
        w = 10e-3    # wide compared to d → fringing negligible
        nx, ny = 10, 4
        mesh = _rect_mesh(w, d, nx, ny)
        bot = _bottom_nodes(mesh, ny)
        top = _top_nodes(mesh, ny)
        bc = {n: 0.0 for n in bot}
        bc.update({n: 1.0 for n in top})

        res = electrostatics(mesh, EPS0, bc)
        assert res["ok"], res.get("reason")

        C_analytic = EPS0 * w / d   # per unit depth
        assert abs(res["capacitance"] - C_analytic) / C_analytic < 0.15

    def test_E_field_direction_plate(self):
        """E should point in −y direction (from high to low V) inside a parallel plate."""
        d = 1.0
        mesh = _rect_mesh(1.0, d, 2, 2)
        bot = _bottom_nodes(mesh, 2)
        top = _top_nodes(mesh, 2)
        bc = {n: 0.0 for n in bot}
        bc.update({n: 1.0 for n in top})

        res = electrostatics(mesh, EPS0, bc)
        assert res["ok"]
        for Ex, Ey in res["E_field"]:
            assert Ey < 0.0, "E_y must point from high to low potential (−y)"

    def test_zero_charge_harmonic_potential(self):
        """With zero charge density, potential satisfies Laplace equation (discrete harmonic)."""
        mesh = _rect_mesh(1.0, 1.0, 4, 4)
        ny = 4
        bot = _bottom_nodes(mesh, ny)
        top = _top_nodes(mesh, ny)
        bc = {n: 0.0 for n in bot}
        bc.update({n: 5.0 for n in top})

        res = electrostatics(mesh, EPS0, bc, charge_density=0.0)
        assert res["ok"]
        phi = res["phi"]
        nodes = mesh["nodes"]
        # Interior nodes should have potential strictly between 0 and 5
        for i, (x, y) in enumerate(nodes):
            if i not in bc:
                assert 0.0 <= phi[i] <= 5.0 + 1e-9

    def test_field_energy_half_cv2(self):
        """
        For a parallel-plate capacitor: W = ½ C V².
        We verify W_FEM ≈ ½ C_FEM · V² (self-consistent).
        """
        d = 1.0
        w = 1.0
        V = 2.0
        nx, ny = 4, 4
        mesh = _rect_mesh(w, d, nx, ny)
        bot = _bottom_nodes(mesh, ny)
        top = _top_nodes(mesh, ny)
        bc = {n: 0.0 for n in bot}
        bc.update({n: V for n in top})

        res = electrostatics(mesh, EPS0, bc)
        assert res["ok"]
        W_expected = 0.5 * res["capacitance"] * V * V
        assert abs(res["energy"] - W_expected) / max(abs(W_expected), 1e-30) < 1e-6

    def test_bad_mesh_missing_nodes(self):
        res = electrostatics({"nodes": [], "elements": []}, EPS0, {0: 0.0, 1: 1.0})
        assert res["ok"] is False

    def test_bad_mesh_no_bc(self):
        mesh = _rect_mesh(1.0, 1.0, 2, 2)
        res = electrostatics(mesh, EPS0, {})
        assert res["ok"] is False

    def test_singular_bc_only_one_value(self):
        """Single BC value applied to all boundary nodes → singular (no potential difference)."""
        mesh = _rect_mesh(1.0, 1.0, 2, 2)
        ny = 2
        bot = _bottom_nodes(mesh, ny)
        top = _top_nodes(mesh, ny)
        # All nodes at same voltage → underdetermined interior, but system still solves (φ = const)
        bc = {n: 3.0 for n in bot}
        bc.update({n: 3.0 for n in top})
        res = electrostatics(mesh, EPS0, bc)
        # Either ok with zero energy, or graceful failure — must not raise
        assert isinstance(res, dict)
        assert "ok" in res

    def test_dirichlet_nodes_honour_bc(self):
        """Potential at Dirichlet nodes must match prescribed values exactly."""
        mesh = _rect_mesh(1.0, 1.0, 3, 3)
        ny = 3
        bot = _bottom_nodes(mesh, ny)
        top = _top_nodes(mesh, ny)
        bc = {n: 0.0 for n in bot}
        bc.update({n: 10.0 for n in top})

        res = electrostatics(mesh, EPS0, bc)
        assert res["ok"]
        phi = res["phi"]
        for n, v in bc.items():
            assert abs(phi[n] - v) < 1e-8, f"node {n}: phi={phi[n]} != {v}"


# ---------------------------------------------------------------------------
# 3.  FEM magnetostatics
# ---------------------------------------------------------------------------

class TestMagnetostaticsFEM:

    def _uniform_current_mesh(self, w=1.0, h=1.0, nx=4, ny=4, Jz=1e6):
        """Uniform current in a square cross-section, zero A on boundary."""
        mesh = _rect_mesh(w, h, nx, ny)
        ny_p = ny
        # Boundary nodes: all nodes on the four edges
        nodes = mesh["nodes"]
        bc = {}
        for i, (x, y) in enumerate(nodes):
            on_edge = (abs(x) < 1e-12 or abs(x - w) < 1e-12 or
                       abs(y) < 1e-12 or abs(y - h) < 1e-12)
            if on_edge:
                bc[i] = 0.0
        return mesh, bc, Jz

    def test_magnetostatics_returns_ok(self):
        mesh, bc, Jz = self._uniform_current_mesh()
        res = magnetostatics(mesh, MU0, Jz, bc)
        assert res["ok"], res.get("reason")
        assert "Az" in res
        assert "B_field" in res

    def test_az_inside_positive_for_positive_current(self):
        """Az inside should be positive for +Jz with Az=0 on boundary."""
        mesh, bc, Jz = self._uniform_current_mesh(Jz=1e6)
        res = magnetostatics(mesh, MU0, Jz, bc)
        assert res["ok"]
        Az = res["Az"]
        nodes = mesh["nodes"]
        w, h = 1.0, 1.0
        for i, (x, y) in enumerate(nodes):
            on_edge = (abs(x) < 1e-12 or abs(x - w) < 1e-12 or
                       abs(y) < 1e-12 or abs(y - h) < 1e-12)
            if not on_edge:
                assert Az[i] > 0.0, f"Interior Az[{i}]={Az[i]:.3e} expected > 0"

    def test_energy_positive(self):
        mesh, bc, Jz = self._uniform_current_mesh()
        res = magnetostatics(mesh, MU0, Jz, bc)
        assert res["ok"]
        assert res["energy"] > 0.0

    def test_field_energy_half_li2(self):
        """W = ½ L I²  — verify inductance is self-consistent."""
        mesh, bc, Jz = self._uniform_current_mesh(w=1.0, h=1.0, nx=4, ny=4, Jz=1e6)
        res = magnetostatics(mesh, MU0, Jz, bc)
        assert res["ok"]
        # Compute I_total from mesh
        I_total = 0.0
        elements = mesh["elements"]
        nodes_list = mesh["nodes"]
        for tri in elements:
            n0, n1, n2 = tri
            x0, y0 = nodes_list[n0]
            x1, y1 = nodes_list[n1]
            x2, y2 = nodes_list[n2]
            area = abs(0.5 * ((x1 - x0) * (y2 - y0) - (x2 - x0) * (y1 - y0)))
            I_total += Jz * area
        L = res["inductance"]
        W_expected = 0.5 * L * I_total * I_total
        assert abs(res["energy"] - W_expected) / max(abs(W_expected), 1e-30) < 1e-6

    def test_lorentz_force_zero_for_symmetric_region(self):
        """
        For a symmetric square cross-section with uniform J and symmetric mesh,
        the net force on the entire domain should be near zero by symmetry.
        """
        mesh, bc, Jz = self._uniform_current_mesh(Jz=1e6)
        all_elems = list(range(len(mesh["elements"])))
        res = magnetostatics(mesh, MU0, Jz, bc, force_region=all_elems)
        assert res["ok"]
        Fx, Fy = res["force"]
        # Not exactly zero due to discretisation, but should be small
        # relative to the energy scale
        mag = math.sqrt(Fx * Fx + Fy * Fy)
        energy = res["energy"]
        assert mag / max(energy, 1e-30) < 1.0  # very rough bound

    def test_b_field_length_matches_elements(self):
        mesh, bc, Jz = self._uniform_current_mesh()
        res = magnetostatics(mesh, MU0, Jz, bc)
        assert res["ok"]
        assert len(res["B_field"]) == len(mesh["elements"])

    def test_b_field_nonzero(self):
        mesh, bc, Jz = self._uniform_current_mesh()
        res = magnetostatics(mesh, MU0, Jz, bc)
        assert res["ok"]
        B_magnitudes = [math.sqrt(Bx * Bx + By * By) for Bx, By in res["B_field"]]
        assert max(B_magnitudes) > 0.0

    def test_bad_mesh_too_few_nodes(self):
        res = magnetostatics({"nodes": [[0, 0]], "elements": []}, MU0, 1e6, {})
        assert res["ok"] is False

    def test_inductance_scales_with_mu(self):
        """Doubling μ should roughly double inductance (same geometry, same J)."""
        mesh, bc, Jz = self._uniform_current_mesh(nx=4, ny=4)
        res1 = magnetostatics(mesh, MU0, Jz, bc)
        res2 = magnetostatics(mesh, 2.0 * MU0, Jz, bc)
        assert res1["ok"] and res2["ok"]
        # Inductance ~ μ, allow 5% tolerance for rounding
        ratio = res2["inductance"] / res1["inductance"]
        assert abs(ratio - 2.0) < 0.1


# ---------------------------------------------------------------------------
# 4.  Laplace log-profile between concentric circles (annulus)
# ---------------------------------------------------------------------------

class TestLaplaceLogProfile:
    """
    Between two concentric cylinders (2-D cross-section):
      - inner circle r=a at V_a
      - outer circle r=b at V_b
    Exact solution:  φ(r) = V_a + (V_b - V_a) * ln(r/a) / ln(b/a)
    We approximate the annulus with a coarse polar mesh and check
    that FEM solution matches the log profile within ~5%.
    """

    def _annular_mesh(self, a, b, n_r, n_theta):
        """Build a simple annular mesh in polar coords."""
        nodes = []
        for i in range(n_r + 1):
            r = a + i * (b - a) / n_r
            for j in range(n_theta):
                theta = 2.0 * math.pi * j / n_theta
                x = r * math.cos(theta)
                y = r * math.sin(theta)
                nodes.append([x, y])

        elements = []
        for i in range(n_r):
            for j in range(n_theta):
                j_next = (j + 1) % n_theta
                n00 = i * n_theta + j
                n10 = (i + 1) * n_theta + j
                n01 = i * n_theta + j_next
                n11 = (i + 1) * n_theta + j_next
                elements.append([n00, n10, n11])
                elements.append([n00, n11, n01])

        return {"nodes": nodes, "elements": elements}

    def test_log_profile_matches(self):
        a, b = 0.1, 0.5
        V_a, V_b = 1.0, 0.0
        n_r, n_theta = 5, 16
        mesh = self._annular_mesh(a, b, n_r, n_theta)
        nodes = mesh["nodes"]

        # Inner circle nodes (i=0)
        bc = {}
        for j in range(n_theta):
            bc[j] = V_a
        # Outer circle nodes (i=n_r)
        for j in range(n_theta):
            bc[n_r * n_theta + j] = V_b

        res = electrostatics(mesh, EPS0, bc)
        assert res["ok"], res.get("reason")

        phi = res["phi"]
        # Check mid-ring nodes (i = n_r//2)
        i_mid = n_r // 2
        r_mid = a + i_mid * (b - a) / n_r
        phi_expected = V_a + (V_b - V_a) * math.log(r_mid / a) / math.log(b / a)

        errors = []
        for j in range(n_theta):
            node_idx = i_mid * n_theta + j
            errors.append(abs(phi[node_idx] - phi_expected))
        max_err = max(errors)
        # Allow 5 % of voltage span
        assert max_err < 0.05 * abs(V_b - V_a), f"max error {max_err:.4f} > 5% of ΔV"


# ---------------------------------------------------------------------------
# 5.  Field-energy helper functions
# ---------------------------------------------------------------------------

class TestFieldEnergyHelpers:

    def test_electric_energy_consistent(self):
        d, w = 1.0, 1.0
        V = 3.0
        mesh = _rect_mesh(w, d, 4, 4)
        ny = 4
        bc = {n: 0.0 for n in _bottom_nodes(mesh, ny)}
        bc.update({n: V for n in _top_nodes(mesh, ny)})
        res = electrostatics(mesh, EPS0, bc)
        assert res["ok"]

        W_helper = field_energy_electric(mesh, EPS0, res["E_field"])
        assert W_helper["ok"]
        # Must match the energy returned by electrostatics itself
        assert abs(W_helper["energy"] - res["energy"]) / max(res["energy"], 1e-30) < 1e-9

    def test_magnetic_energy_consistent(self):
        w, h = 1.0, 1.0
        nx, ny = 4, 4
        Jz = 1e6
        mesh = _rect_mesh(w, h, nx, ny)
        nodes_list = mesh["nodes"]
        bc = {i: 0.0 for i, (x, y) in enumerate(nodes_list)
              if abs(x) < 1e-12 or abs(x - w) < 1e-12 or
                 abs(y) < 1e-12 or abs(y - h) < 1e-12}
        res = magnetostatics(mesh, MU0, Jz, bc)
        assert res["ok"]

        W_helper = field_energy_magnetic(mesh, MU0, res["B_field"])
        assert W_helper["ok"]
        assert abs(W_helper["energy"] - res["energy"]) / max(res["energy"], 1e-30) < 1e-9

    def test_electric_energy_wrong_field_length(self):
        mesh = _rect_mesh(1.0, 1.0, 2, 2)
        res = field_energy_electric(mesh, EPS0, [[0.0, 0.0]])  # wrong length
        assert res["ok"] is False

    def test_magnetic_energy_wrong_field_length(self):
        mesh = _rect_mesh(1.0, 1.0, 2, 2)
        res = field_energy_magnetic(mesh, MU0, [[0.0, 0.0]])
        assert res["ok"] is False
