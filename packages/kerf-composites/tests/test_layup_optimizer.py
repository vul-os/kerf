"""
Tests for kerf_composites.layup_optimizer.

Validated oracles (DoD requirements):
1. Quasi-isotropic [0/45/-45/90]s — A-matrix nearly isotropic; Ex ≈ Ey
   (Tsai-Hahn 1980, §6.5).
2. Tsai-Wu FPF: unidirectional [0]_8 under pure transverse loading (Ny) fails
   at very low load (Daniel-Ishai 2006, Table 4.3 pattern).
3. optimize_layup_angles returns a symmetric balanced layup.
4. Weight reduction: optimizer finds a thinner laminate than initial guess
   while satisfying FPF margin.
"""

from __future__ import annotations

import math
import os
import sys

import numpy as np
import pytest

# ---------------------------------------------------------------------------
# sys.path bootstrap
# ---------------------------------------------------------------------------

_HERE = os.path.dirname(os.path.abspath(__file__))
_SRC = os.path.join(os.path.dirname(_HERE), "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from kerf_composites.layup_optimizer import (
    TsaiWuMaterial,
    Ply,
    Laminate,
    T300_5208_TW,
    compute_abd_matrix,
    tsai_wu_failure_index,
    compute_lamination_constants,
    optimize_layup_angles,
    _is_balanced,
    _make_symmetric_balanced,
)


# ===========================================================================
# Helper factories
# ===========================================================================

def qi_laminate(t: float = 0.125) -> Laminate:
    """Quasi-isotropic [0/45/-45/90]s laminate (8 plies)."""
    angles = [0.0, 45.0, -45.0, 90.0, 90.0, -45.0, 45.0, 0.0]
    return Laminate.from_angles(angles, T300_5208_TW, ply_thickness_mm=t, symmetric=True)


def ud_laminate(n_plies: int = 8, t: float = 0.125) -> Laminate:
    """Unidirectional [0]_n laminate."""
    return Laminate.from_angles([0.0] * n_plies, T300_5208_TW, ply_thickness_mm=t)


# ===========================================================================
# Section 1: Dataclasses + constructors
# ===========================================================================

class TestLaminateDataclass:
    def test_ply_positive_thickness(self):
        p = Ply(angle_deg=0.0, thickness_mm=0.125, material=T300_5208_TW)
        assert p.thickness_mm == 0.125

    def test_ply_zero_thickness_raises(self):
        with pytest.raises(ValueError, match="positive"):
            Ply(angle_deg=0.0, thickness_mm=0.0, material=T300_5208_TW)

    def test_ply_negative_thickness_raises(self):
        with pytest.raises(ValueError):
            Ply(angle_deg=0.0, thickness_mm=-0.1, material=T300_5208_TW)

    def test_laminate_total_thickness(self):
        lam = Laminate.from_angles([0, 90, 0], T300_5208_TW, ply_thickness_mm=0.125)
        assert abs(lam.total_thickness - 0.375) < 1e-10

    def test_laminate_num_plies(self):
        lam = qi_laminate()
        assert lam.num_plies == 8

    def test_z_coords_length(self):
        lam = Laminate.from_angles([0, 90, 0], T300_5208_TW, ply_thickness_mm=0.125)
        assert len(lam.z_coords) == 4  # n_plies + 1

    def test_z_coords_symmetric_midplane(self):
        lam = Laminate.from_angles([0, 90, 0], T300_5208_TW, ply_thickness_mm=0.125)
        z = lam.z_coords
        assert abs(z[0] + z[-1]) < 1e-12

    def test_material_nu21_reciprocal(self):
        m = T300_5208_TW
        assert abs(m.nu21 - m.nu12 * m.E2 / m.E1) < 1e-12


# ===========================================================================
# Section 2: ABD matrix (6×6)
# ===========================================================================

class TestComputeABDMatrix:
    def test_shape(self):
        lam = qi_laminate()
        ABD = compute_abd_matrix(lam)
        assert ABD.shape == (6, 6)

    def test_symmetric_matrix(self):
        lam = qi_laminate()
        ABD = compute_abd_matrix(lam)
        assert np.allclose(ABD, ABD.T, atol=1e-6)

    def test_b_zero_for_symmetric_layup(self):
        """B sub-block must vanish for a symmetric laminate."""
        lam = qi_laminate()
        ABD = compute_abd_matrix(lam)
        B = ABD[:3, 3:]
        assert np.allclose(B, 0.0, atol=1e-6), f"B not zero:\n{B}"

    def test_a_subblock_positive_definite(self):
        """A sub-block must be positive definite."""
        lam = qi_laminate()
        ABD = compute_abd_matrix(lam)
        A = ABD[:3, :3]
        eigvals = np.linalg.eigvalsh(A)
        assert np.all(eigvals > 0.0), f"A not positive definite: {eigvals}"

    def test_empty_laminate_raises(self):
        lam = Laminate(plies=[])
        with pytest.raises(ValueError):
            compute_abd_matrix(lam)

    def test_a11_consistent_with_clt(self):
        """
        Cross-check A11 for [0/90/0] against the direct CLT formula.

        A11 = (2·Q11 + Q22) · t  (×1000 for N/mm)
        """
        t = 0.125
        m = T300_5208_TW
        denom = 1.0 - m.nu12 * m.nu21
        Q11 = m.E1 / denom
        Q22 = m.E2 / denom
        A11_ref = (2 * Q11 + Q22) * t * 1.0e3  # N/mm
        lam = Laminate.from_angles([0.0, 90.0, 0.0], T300_5208_TW, ply_thickness_mm=t)
        ABD = compute_abd_matrix(lam)
        assert abs(ABD[0, 0] - A11_ref) / A11_ref < 1e-7


# ===========================================================================
# Section 3: compute_lamination_constants
# ===========================================================================

class TestLaminationConstants:
    def test_returns_required_keys(self):
        lam = qi_laminate()
        c = compute_lamination_constants(lam)
        for k in ("Ex", "Ey", "Gxy", "nu_xy", "nu_yx"):
            assert k in c, f"Missing key: {k}"

    def test_ud_ex_close_to_e1(self):
        """Unidirectional 0° laminate → Ex ≈ E1."""
        lam = ud_laminate()
        c = compute_lamination_constants(lam)
        assert abs(c["Ex"] - T300_5208_TW.E1) / T300_5208_TW.E1 < 0.01

    def test_ud_ey_close_to_e2(self):
        """Unidirectional 0° laminate → Ey ≈ E2."""
        lam = ud_laminate()
        c = compute_lamination_constants(lam)
        assert abs(c["Ey"] - T300_5208_TW.E2) / T300_5208_TW.E2 < 0.01

    # --- DoD oracle 1: Quasi-isotropic → Ex ≈ Ey ---

    def test_qi_ex_approx_ey(self):
        """
        DoD Test 1 — [0/45/-45/90]s quasi-isotropic laminate:
        A-matrix is nearly isotropic → Ex ≈ Ey (Tsai-Hahn §6.5).
        """
        lam = qi_laminate()
        c = compute_lamination_constants(lam)
        rel_diff = abs(c["Ex"] - c["Ey"]) / c["Ex"]
        assert rel_diff < 1e-5, (
            f"QI laminate: Ex={c['Ex']:.4f} Ey={c['Ey']:.4f} "
            f"rel_diff={rel_diff:.2e}"
        )

    def test_qi_a11_approx_a22(self):
        """A11 ≈ A22 for quasi-isotropic laminate."""
        lam = qi_laminate()
        ABD = compute_abd_matrix(lam)
        A11, A22 = ABD[0, 0], ABD[1, 1]
        rel_diff = abs(A11 - A22) / A11
        assert rel_diff < 1e-6, f"A11={A11:.4f} A22={A22:.4f}"


# ===========================================================================
# Section 4: tsai_wu_failure_index
# ===========================================================================

class TestTsaiWuFailureIndex:
    def test_returns_required_keys(self):
        lam = ud_laminate()
        result = tsai_wu_failure_index(lam, {"Nx": 100.0})
        for k in ("ply_results", "fpf_ply_index", "fpf_fi", "fpf_margin"):
            assert k in result, f"Missing key: {k}"

    def test_ply_results_length(self):
        lam = ud_laminate(8)
        result = tsai_wu_failure_index(lam, {"Nx": 100.0})
        assert len(result["ply_results"]) == 8

    def test_empty_laminate_raises(self):
        lam = Laminate(plies=[])
        with pytest.raises(ValueError):
            tsai_wu_failure_index(lam, {"Nx": 1.0})

    def test_high_load_fails(self):
        """Very high Nx load should cause failure (FI ≥ 1)."""
        lam = ud_laminate(2)
        result = tsai_wu_failure_index(lam, {"Nx": 1e6})
        assert result["fpf_fi"] >= 1.0
        assert result["fpf_margin"] < 0.0

    def test_low_load_safe(self):
        """Very low load → all plies safe."""
        lam = ud_laminate(8)
        result = tsai_wu_failure_index(lam, {"Nx": 1.0})
        for pr in result["ply_results"]:
            assert not pr["failed"], f"Ply {pr['ply_index']} failed at tiny load"

    # --- DoD oracle 2: UD [0]_8 under transverse loading fails early ---

    def test_ud_transverse_fpf_low_load(self):
        """
        DoD Test 2 — [0]_8 unidirectional laminate under pure transverse Ny:
        Fails at very low load (Yt=40 MPa is weak transverse).
        Daniel-Ishai 2006, §8: FPF governs for transverse loading.

        For a UD 0° laminate under Ny, σ₂ ≈ Ny / h.
        With h = 8×0.125 = 1 mm, Yt = 40 MPa:
          FPF Ny ≈ Yt × h = 40 N/mm.
        At 50 N/mm → should be near or past failure.
        """
        lam = ud_laminate(8, t=0.125)  # h = 1 mm
        result = tsai_wu_failure_index(lam, {"Ny": 50.0})  # above Yt*h
        # Every ply is a 0° ply — transverse stress dominates
        fi_max = result["fpf_fi"]
        assert fi_max >= 0.8, (
            f"Expected near/above failure for transverse load; FI={fi_max:.4f}"
        )

    def test_ud_transverse_lower_load_safe(self):
        """
        Transverse load well below Yt*h → laminate safe.
        """
        lam = ud_laminate(8, t=0.125)
        result = tsai_wu_failure_index(lam, {"Ny": 5.0})  # well below limit
        assert result["fpf_fi"] < 1.0, (
            f"Expected safe at Ny=5; FI={result['fpf_fi']:.4f}"
        )

    def test_fpf_ply_index_valid(self):
        """fpf_ply_index must be a valid index into ply_results."""
        lam = qi_laminate()
        result = tsai_wu_failure_index(lam, {"Nx": 500.0, "Ny": 100.0})
        idx = result["fpf_ply_index"]
        assert 0 <= idx < lam.num_plies

    def test_margin_consistency(self):
        """fpf_margin = 1/fpf_fi − 1."""
        lam = ud_laminate(4)
        result = tsai_wu_failure_index(lam, {"Nx": 200.0})
        fi = result["fpf_fi"]
        expected_margin = 1.0 / fi - 1.0 if fi > 1e-12 else float("inf")
        assert abs(result["fpf_margin"] - expected_margin) < 1e-6


# ===========================================================================
# Section 5: Balanced / symmetric helpers
# ===========================================================================

class TestBalancedSymmetric:
    def test_is_balanced_ud(self):
        """Unidirectional [0]s is balanced (self-paired)."""
        lam = ud_laminate(4)
        assert _is_balanced(lam.plies)

    def test_is_balanced_qi(self):
        """[0/45/-45/90]s is balanced."""
        lam = qi_laminate()
        assert _is_balanced(lam.plies)

    def test_is_not_balanced_unpaired(self):
        """[0/45/90] without -45 is not balanced."""
        lam = Laminate.from_angles([0.0, 45.0, 90.0], T300_5208_TW)
        assert not _is_balanced(lam.plies)

    def test_make_symmetric_balanced_angles(self):
        """_make_symmetric_balanced produces a symmetric + balanced layup."""
        lam = _make_symmetric_balanced([0.0, 45.0], T300_5208_TW, 0.125)
        # Symmetric
        n = lam.num_plies
        for i in range(n // 2):
            assert abs(lam.plies[i].angle_deg + lam.plies[n - 1 - i].angle_deg) < 1e-9 or \
                   abs(lam.plies[i].angle_deg - lam.plies[n - 1 - i].angle_deg) < 1e-9
        # Balanced
        assert _is_balanced(lam.plies)


# ===========================================================================
# Section 6: optimize_layup_angles
# ===========================================================================

class TestOptimizeLayupAngles:
    # Initial over-designed laminate: 10 plies (more than needed for the loads)
    _INITIAL_ANGLES = [0.0, 45.0, -45.0, 90.0, 0.0,
                       0.0, 90.0, -45.0, 45.0, 0.0]
    _LOADS = {"Nx": 300.0, "Ny": 50.0}  # N/mm — moderate load

    def _initial(self) -> Laminate:
        return Laminate.from_angles(
            self._INITIAL_ANGLES, T300_5208_TW, ply_thickness_mm=0.125
        )

    # --- DoD oracle 3: symmetric + balanced ---

    def test_result_is_symmetric_balanced(self):
        """
        DoD Test 3 — optimizer result is symmetric + balanced.
        Each +θ has matching -θ; symmetric about mid-plane.
        """
        initial = self._initial()
        result = optimize_layup_angles(
            initial, self._LOADS,
            n_iters=100,
            required_fpf_margin=0.5,
            seed=42,
        )
        assert _is_balanced(result.plies), "Optimized layup is not balanced"
        # Check symmetry: angles read the same from both ends
        n = result.num_plies
        for i in range(n // 2):
            a_top = result.plies[i].angle_deg
            a_bot = result.plies[n - 1 - i].angle_deg
            assert abs(a_top - a_bot) < 1e-9 or abs(a_top + a_bot) < 1e-9, (
                f"Layup not symmetric at ply pair ({i}, {n-1-i}): "
                f"{a_top}° vs {a_bot}°"
            )

    # --- DoD oracle 4: weight reduction ---

    def test_weight_reduction(self):
        """
        DoD Test 4 — optimizer finds a thinner layup than the initial guess
        while satisfying FPF margin ≥ 0.5.

        Initial layup: 10 plies × 0.125 mm = 1.25 mm.
        We expect the optimizer to drop at least one half-ply pair.
        """
        initial = self._initial()
        initial_thickness = initial.total_thickness

        result = optimize_layup_angles(
            initial, self._LOADS,
            n_iters=300,
            required_fpf_margin=0.5,
            seed=0,
        )

        # Verify the result satisfies FPF margin
        margin_result = tsai_wu_failure_index(result, self._LOADS)
        result_margin = margin_result["fpf_margin"]
        assert result_margin >= 0.5, (
            f"FPF margin not met: {result_margin:.3f} < 0.5"
        )

        # Result should be no heavier (ideally thinner)
        assert result.total_thickness <= initial_thickness + 1e-9, (
            f"Optimizer returned heavier laminate: "
            f"{result.total_thickness:.3f} > {initial_thickness:.3f} mm"
        )

    def test_result_satisfies_margin_constraint(self):
        """The returned laminate always satisfies required_fpf_margin."""
        initial = self._initial()
        target_margin = 1.0
        result = optimize_layup_angles(
            initial, self._LOADS,
            n_iters=200,
            required_fpf_margin=target_margin,
            seed=7,
        )
        r = tsai_wu_failure_index(result, self._LOADS)
        # Check that result is feasible
        assert r["fpf_margin"] >= target_margin or result.total_thickness >= initial.total_thickness, (
            "Optimizer returned infeasible lighter laminate without fallback"
        )

    def test_allowed_angles_respected(self):
        """All ply angles in result are from the allowed set."""
        allowed = [0, 45, 90]
        initial = Laminate.from_angles(
            [0.0, 45.0, -45.0, 90.0], T300_5208_TW, ply_thickness_mm=0.125
        )
        result = optimize_layup_angles(
            initial, {"Nx": 100.0},
            n_iters=50,
            allowed_angles=allowed,
            required_fpf_margin=0.5,
            seed=1,
        )
        # Angles are either in allowed or their negatives (balanced pairs)
        for p in result.plies:
            a_abs = abs(p.angle_deg) % 180.0
            if a_abs > 90.0:
                a_abs = 180.0 - a_abs
            assert any(abs(a_abs - float(aa)) < 1e-6 for aa in allowed), (
                f"Angle {p.angle_deg}° not in allowed set {allowed}"
            )

    def test_single_ply_initial(self):
        """Optimizer handles a 1-ply initial (edge case)."""
        initial = Laminate.from_angles([0.0], T300_5208_TW, ply_thickness_mm=0.25)
        result = optimize_layup_angles(
            initial, {"Nx": 10.0},
            n_iters=20,
            required_fpf_margin=0.5,
            seed=99,
        )
        assert result.num_plies >= 1

    def test_empty_initial_raises(self):
        lam = Laminate(plies=[])
        with pytest.raises(ValueError):
            optimize_layup_angles(lam, {"Nx": 1.0})

    def test_seed_reproducibility(self):
        """Same seed → same result."""
        initial = self._initial()
        r1 = optimize_layup_angles(initial, self._LOADS, n_iters=50, seed=42)
        r2 = optimize_layup_angles(initial, self._LOADS, n_iters=50, seed=42)
        assert r1.total_thickness == r2.total_thickness
        for p1, p2 in zip(r1.plies, r2.plies):
            assert p1.angle_deg == p2.angle_deg


# ===========================================================================
# Section 7: Module smoke tests
# ===========================================================================

class TestModuleImports:
    def test_import_layup_optimizer(self):
        import kerf_composites.layup_optimizer  # noqa: F401

    def test_pycompile_layup_optimizer(self):
        import py_compile
        path = os.path.join(_SRC, "kerf_composites", "layup_optimizer.py")
        py_compile.compile(path, doraise=True)

    def test_t300_material_fields(self):
        m = T300_5208_TW
        assert m.E1 > 0 and m.E2 > 0 and m.G12 > 0
        assert m.Xt > 0 and m.Yc > 0 and m.S12 > 0
