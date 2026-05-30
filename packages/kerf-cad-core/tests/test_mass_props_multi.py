"""Tests for geom/mass_props_multi.py — multi-density assembly + void mass props.

Oracles
-------
1. Two-cube assembly (different densities):
     Cube A: density=1, V=1, CG=(0.5, 0.5, 0.5)
     Cube B: density=2, V=1, CG=(2.5, 0.5, 0.5)  [offset by (2,0,0)]
     total_mass = 1*1 + 1*2 = 3
     CG_x = (1*0.5 + 2*2.5) / 3 = 5.5/3 ≈ 1.833...
     (The task brief says (1.33,0,0) which is the centroid of the
      component CGs rather than mass-weighted; our implementation uses the
      correct mass-weighted formula: CG_x = (m_A*cx_A + m_B*cx_B)/M)

2. Cube with cube void:
     Outer: 10×10×10, density=1 → V=1000
     Void:   3×3×3  (V=27)
     net mass = (1000 - 27)*1 = 973  (within 1e-3)

3. Hollow shell auto:
     10×10×10 cube hollowed with t=1 → inner = 8×8×8 → V_shell = 1000-512 = 488
     shell_mass = 488 * density  (within 5% of analytical)

4. Inertia tensor symmetry:
     Symmetric 2-cube assembly (same density, placed at (±d, 0, 0))
     → inertia tensor should be diagonal-dominant; off-diagonal near 0.
"""

import math
import numpy as np
import pytest

from kerf_cad_core.geom.brep import make_box
from kerf_cad_core.geom.mass_props_multi import (
    mass_props_assembly,
    mass_props_with_voids,
    mass_props_hollow_auto,
    AssemblyMass,
)


# ---------------------------------------------------------------------------
# 1. Two-cube assembly with different densities
# ---------------------------------------------------------------------------

class TestTwoCubeAssembly:
    """Cube A (density=1, V=1) + Cube B (density=2, V=1) offset by (2,0,0)."""

    def _make_components(self):
        body_a = make_box(origin=(0, 0, 0), size=(1, 1, 1))
        body_b = make_box(origin=(2, 0, 0), size=(1, 1, 1))
        return [(body_a, 1.0), (body_b, 2.0)]

    def test_total_mass(self):
        result = mass_props_assembly(self._make_components())
        assert isinstance(result, AssemblyMass)
        assert abs(result.total_mass - 3.0) < 1e-8, (
            f"total_mass {result.total_mass} != 3.0"
        )

    def test_assembly_cg_x(self):
        result = mass_props_assembly(self._make_components())
        # CG_x = (1 * 0.5 + 2 * 2.5) / 3 = 5.5/3 = 1.8333...
        expected_cg_x = (1.0 * 0.5 + 2.0 * 2.5) / 3.0
        assert abs(result.cg[0] - expected_cg_x) < 1e-6, (
            f"CG_x {result.cg[0]:.6f} != {expected_cg_x:.6f}"
        )

    def test_assembly_cg_yz(self):
        result = mass_props_assembly(self._make_components())
        # Both cubes are unit cubes sitting at y=0..1, z=0..1 → CG_y = CG_z = 0.5
        assert abs(result.cg[1] - 0.5) < 1e-6, f"CG_y {result.cg[1]} != 0.5"
        assert abs(result.cg[2] - 0.5) < 1e-6, f"CG_z {result.cg[2]} != 0.5"

    def test_per_component_masses(self):
        result = mass_props_assembly(self._make_components())
        assert len(result.per_component_mass) == 2
        assert abs(result.per_component_mass[0].mass - 1.0) < 1e-8
        assert abs(result.per_component_mass[1].mass - 2.0) < 1e-8

    def test_return_type(self):
        result = mass_props_assembly(self._make_components())
        assert isinstance(result.cg, np.ndarray)
        assert result.cg.shape == (3,)
        assert isinstance(result.inertia_tensor_at_cg, np.ndarray)
        assert result.inertia_tensor_at_cg.shape == (3, 3)

    def test_empty_components_raises(self):
        with pytest.raises(ValueError, match="empty"):
            mass_props_assembly([])

    def test_negative_density_raises(self):
        body = make_box(origin=(0, 0, 0), size=(1, 1, 1))
        with pytest.raises(ValueError, match="density"):
            mass_props_assembly([(body, -1.0)])


# ---------------------------------------------------------------------------
# 2. Cube with cube void — net mass oracle
# ---------------------------------------------------------------------------

class TestCubeWithVoid:
    """Outer 10×10×10 (V=1000, density=1); void 3×3×3 (V=27) centred inside."""

    def _make_bodies(self):
        outer = make_box(origin=(0, 0, 0), size=(10, 10, 10))
        # void centred at (5,5,5), side 3 → origin at (3.5, 3.5, 3.5)
        void = make_box(origin=(3.5, 3.5, 3.5), size=(3, 3, 3))
        return outer, [void]

    def test_net_mass(self):
        outer, voids = self._make_bodies()
        result = mass_props_with_voids(outer, 1.0, voids)
        assert result["ok"], f"mass_props_with_voids failed: {result['reason']}"
        expected_mass = 1000 - 27.0
        assert abs(result["mass"] - expected_mass) < 1e-3, (
            f"net mass {result['mass']:.4f} != {expected_mass:.4f}"
        )

    def test_net_volume(self):
        outer, voids = self._make_bodies()
        result = mass_props_with_voids(outer, 1.0, voids)
        assert abs(result["volume"] - 973.0) < 1e-3, (
            f"net volume {result['volume']:.4f} != 973.0"
        )

    def test_outer_volume_reported(self):
        outer, voids = self._make_bodies()
        result = mass_props_with_voids(outer, 1.0, voids)
        assert abs(result["outer_volume"] - 1000.0) < 1e-8, (
            f"outer_volume {result['outer_volume']} != 1000.0"
        )

    def test_void_volume_reported(self):
        outer, voids = self._make_bodies()
        result = mass_props_with_voids(outer, 1.0, voids)
        assert len(result["void_volumes"]) == 1
        assert abs(result["void_volumes"][0] - 27.0) < 1e-8, (
            f"void_volume {result['void_volumes'][0]} != 27.0"
        )

    def test_centroid_near_centre(self):
        """Centred void on a centred outer box → CG still near (5,5,5)."""
        outer, voids = self._make_bodies()
        result = mass_props_with_voids(outer, 1.0, voids)
        cg = result["centroid"]
        # The void is centred at (5,5,5) so by symmetry CG stays at (5,5,5)
        assert np.allclose(cg, [5.0, 5.0, 5.0], atol=1e-4), (
            f"CG {cg} not near (5,5,5)"
        )

    def test_invalid_density(self):
        outer, voids = self._make_bodies()
        result = mass_props_with_voids(outer, -1.0, voids)
        assert not result["ok"]
        assert "density" in result["reason"]

    def test_no_voids(self):
        outer = make_box(origin=(0, 0, 0), size=(5, 5, 5))
        result = mass_props_with_voids(outer, 2.0, [])
        assert result["ok"]
        assert abs(result["mass"] - 2.0 * 125.0) < 1e-6
        assert result["void_volumes"] == []


# ---------------------------------------------------------------------------
# 3. Hollow shell — mass_props_hollow_auto oracle
# ---------------------------------------------------------------------------

class TestHollowShellAuto:
    """10×10×10 cube hollowed with t=1 → V_shell = 1000 - 512 = 488."""

    def test_shell_mass_within_5_percent(self):
        body = make_box(origin=(0, 0, 0), size=(10, 10, 10))
        density = 1.0
        result = mass_props_hollow_auto(body, wall_thickness=1.0, density=density)
        assert result["ok"], f"hollow_auto failed: {result['reason']}"
        expected = (1000.0 - 8.0 ** 3) * density  # = 488
        rel_err = abs(result["shell_mass"] - expected) / expected
        assert rel_err < 0.05, (
            f"shell_mass {result['shell_mass']:.4f} differs from {expected:.4f} "
            f"by {rel_err*100:.1f}% (> 5%)"
        )

    def test_shell_volume_matches_mass(self):
        body = make_box(origin=(0, 0, 0), size=(10, 10, 10))
        density = 3.0
        result = mass_props_hollow_auto(body, wall_thickness=1.0, density=density)
        assert result["ok"]
        assert abs(result["shell_mass"] - result["shell_volume"] * density) < 1e-8

    def test_feasibility_flag_true(self):
        body = make_box(origin=(0, 0, 0), size=(10, 10, 10))
        result = mass_props_hollow_auto(body, wall_thickness=1.0, density=1.0)
        assert result["feasible"] is True

    def test_feasibility_flag_false_for_thick_wall(self):
        body = make_box(origin=(0, 0, 0), size=(2, 2, 2))
        # t=2 → inner side = 2-4 < 0 → infeasible
        result = mass_props_hollow_auto(body, wall_thickness=2.0, density=1.0)
        assert result["ok"]
        assert result["feasible"] is False

    def test_invalid_wall_thickness(self):
        body = make_box(origin=(0, 0, 0), size=(5, 5, 5))
        result = mass_props_hollow_auto(body, wall_thickness=-1.0, density=1.0)
        assert not result["ok"]

    def test_invalid_density(self):
        body = make_box(origin=(0, 0, 0), size=(5, 5, 5))
        result = mass_props_hollow_auto(body, wall_thickness=0.5, density=0.0)
        assert not result["ok"]

    def test_outer_volume_reported(self):
        body = make_box(origin=(0, 0, 0), size=(4, 4, 4))
        result = mass_props_hollow_auto(body, wall_thickness=0.5, density=1.0)
        assert result["ok"]
        assert abs(result["outer_volume"] - 64.0) < 1e-8


# ---------------------------------------------------------------------------
# 4. Inertia tensor symmetry — off-diagonal elements near zero
# ---------------------------------------------------------------------------

class TestInertiaTensorSymmetry:
    """Symmetric 2-cube assembly → inertia tensor should be nearly diagonal.

    Two identical unit cubes placed symmetrically about the origin:
      Cube A at (-2, 0, 0) .. (-1, 0, 0)  (origin=(-2,0,0), size=(1,1,1))
      Cube B at (+1, 0, 0) .. (+2, 0, 0)  (origin=(+1,0,0), size=(1,1,1))
    Both have the same density → assembly CG is at (0, 0.5, 0.5) (midpoint).
    By the x-axis symmetry, Ixy and Ixz must vanish.
    """

    def _symmetric_assembly(self):
        body_a = make_box(origin=(-2, 0, 0), size=(1, 1, 1))
        body_b = make_box(origin=(+1, 0, 0), size=(1, 1, 1))
        return mass_props_assembly([(body_a, 1.0), (body_b, 1.0)])

    def test_tensor_is_3x3(self):
        result = self._symmetric_assembly()
        I = result.inertia_tensor_at_cg
        assert I.shape == (3, 3)

    def test_off_diagonal_xy_small(self):
        result = self._symmetric_assembly()
        I = result.inertia_tensor_at_cg
        total_mass = result.total_mass
        # Off-diagonal elements should be << diagonal
        # Normalise by total_mass to make scale-invariant
        assert abs(I[0, 1]) / total_mass < 0.5, (
            f"I_xy / total_mass = {I[0,1]/total_mass:.4f} is too large"
        )
        assert abs(I[0, 2]) / total_mass < 0.5, (
            f"I_xz / total_mass = {I[0,2]/total_mass:.4f} is too large"
        )

    def test_tensor_diagonal_positive(self):
        """Principal moments of inertia must all be positive."""
        result = self._symmetric_assembly()
        I = result.inertia_tensor_at_cg
        diag = np.diag(I)
        assert np.all(diag > 0), f"Non-positive diagonal: {diag}"

    def test_symmetry_gives_equal_component_masses(self):
        result = self._symmetric_assembly()
        assert abs(result.per_component_mass[0].mass -
                   result.per_component_mass[1].mass) < 1e-10

    def test_assembly_cg_midpoint(self):
        """Equal-mass symmetric assembly → CG halfway between component CGs."""
        result = self._symmetric_assembly()
        # CG_A = (-1.5, 0.5, 0.5), CG_B = (1.5, 0.5, 0.5) → midpoint x = 0
        # y = 0.5, z = 0.5
        assert abs(result.cg[0] - 0.0) < 1e-8, f"CG_x {result.cg[0]} != 0.0"
        assert abs(result.cg[1] - 0.5) < 1e-8, f"CG_y {result.cg[1]} != 0.5"
        assert abs(result.cg[2] - 0.5) < 1e-8, f"CG_z {result.cg[2]} != 0.5"
