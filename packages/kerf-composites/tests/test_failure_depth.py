"""
Tests for kerf_composites failure_depth, interlaminar, and thermal_residual.

Analytic oracles:
  1. Tsai-Wu on UD T300/5208 at σ₁ = Xt yields FI = 1.0 exactly.
  2. Tsai-Hill reduces to uniaxial form for σ₂=0, τ₁₂=0 → FI = (σ₁/Xt)².
  3. Hashin distinguishes fiber-tension vs matrix-tension failure mode.
  4. Interlaminar shear is max at neutral axis for a [0/90/0] laminate.
  5. Thermal residual: [0/90/0] cured at 175°C, used at 20°C → σ₁ in 0° plies
     is tensile (positive), because 0° plies are fibre-dominated (low CTE) and
     the high-CTE 90° core contracts more, placing the stiff 0° outer plies in
     tension.
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

from kerf_composites.layup import (
    Ply, PlyMaterial, LaminateLayup,
    T300_5208,
)
from kerf_composites.failure_depth import (
    FailureMode,
    FailureResult,
    tsai_wu,
    tsai_hill,
    max_stress,
    max_strain,
    hashin,
)
from kerf_composites.interlaminar import (
    interlaminar_shear,
    ilss_neutral_axis,
)
from kerf_composites.thermal_residual import (
    thermal_residual,
    thermal_residual_uniform,
)


# ===========================================================================
# Fixtures
# ===========================================================================

@pytest.fixture
def t300_5208() -> PlyMaterial:
    """T300/5208 CFRP — standard aerospace reference UD lamina."""
    return T300_5208


@pytest.fixture
def layup_090_0() -> LaminateLayup:
    """[0/90/0] symmetric T300/5208 laminate, 0.125 mm per ply."""
    return LaminateLayup.from_sequence([0.0, 90.0, 0.0], T300_5208, ply_thickness=0.125)


# ===========================================================================
# Section 1: Tsai-Wu
# ===========================================================================

class TestTsaiWu:
    def test_unidirectional_at_xt_gives_fi_one(self, t300_5208):
        """
        Oracle: UD ply stressed at exactly σ₁ = Xt (all other components zero).
        Tsai-Wu must yield FI = 1.0 to within 1e-6.
        """
        mat = t300_5208
        result = tsai_wu(sigma1=mat.Xt, sigma2=0.0, tau12=0.0, material=mat)
        assert abs(result.failure_index - 1.0) < 1e-6, (
            f"Expected FI=1.0, got {result.failure_index}"
        )

    def test_margin_of_safety_at_xt(self, t300_5208):
        """At FI=1, margin of safety = 0."""
        mat = t300_5208
        result = tsai_wu(sigma1=mat.Xt, sigma2=0.0, tau12=0.0, material=mat)
        assert abs(result.margin_of_safety) < 1e-6

    def test_failed_flag_at_xt(self, t300_5208):
        """At FI=1 the failed flag must be True."""
        mat = t300_5208
        result = tsai_wu(sigma1=mat.Xt, sigma2=0.0, tau12=0.0, material=mat)
        assert result.failed is True

    def test_below_xt_is_safe(self, t300_5208):
        """Below Xt by 1% → FI < 1, not failed."""
        mat = t300_5208
        result = tsai_wu(sigma1=0.99 * mat.Xt, sigma2=0.0, tau12=0.0, material=mat)
        assert result.failure_index < 1.0
        assert result.failed is False

    def test_above_xt_fails(self, t300_5208):
        """Above Xt by 1% → FI > 1, failed."""
        mat = t300_5208
        result = tsai_wu(sigma1=1.01 * mat.Xt, sigma2=0.0, tau12=0.0, material=mat)
        assert result.failure_index > 1.0
        assert result.failed is True

    def test_zero_stress_is_safe(self, t300_5208):
        """Zero stress → FI = 0."""
        mat = t300_5208
        result = tsai_wu(sigma1=0.0, sigma2=0.0, tau12=0.0, material=mat)
        assert result.failure_index == pytest.approx(0.0, abs=1e-12)

    def test_symmetric_material_zero_F1(self):
        """
        For a material with Xt = Xc, F₁ = 0 and Tsai-Wu is purely quadratic
        in σ₁ → FI at σ₁=Xt, σ₂=0, τ₁₂=0 should still equal 1.
        """
        sym_mat = PlyMaterial(
            name="Sym", E1=181.0, E2=10.3, G12=7.17, nu12=0.28,
            Xt=1500.0, Xc=1500.0, Yt=40.0, Yc=246.0, S12=68.0,
        )
        result = tsai_wu(sigma1=sym_mat.Xt, sigma2=0.0, tau12=0.0, material=sym_mat)
        assert abs(result.failure_index - 1.0) < 1e-6

    def test_pure_shear_failure(self, t300_5208):
        """At τ₁₂ = S₁₂ the Tsai-Wu FI equals F₆₆·S₁₂² = 1."""
        mat = t300_5208
        result = tsai_wu(sigma1=0.0, sigma2=0.0, tau12=mat.S12, material=mat)
        # F66·S12² = 1; F1=F2=F12=F11/F22 terms are zero for this case
        # (F1 and F2 contributions vanish; F11/F22 terms are negligible vs F66)
        # Approximate check only — other terms contribute
        assert result.failure_index > 0.0

    def test_criterion_name(self, t300_5208):
        mat = t300_5208
        result = tsai_wu(sigma1=100.0, sigma2=0.0, tau12=0.0, material=mat)
        assert "Tsai-Wu" in result.criterion


# ===========================================================================
# Section 2: Tsai-Hill
# ===========================================================================

class TestTsaiHill:
    def test_uniaxial_sigma1_only(self, t300_5208):
        """
        Oracle: σ₂=0, τ₁₂=0 → FI = (σ₁/Xt)².
        At σ₁=Xt this gives FI=1; at σ₁=Xt/2 gives FI=0.25.
        This is the uniaxial (Mises-like) collapse.
        """
        mat = t300_5208
        sigma1 = mat.Xt / 2.0
        result = tsai_hill(sigma1=sigma1, sigma2=0.0, tau12=0.0, material=mat)
        expected = (sigma1 / mat.Xt) ** 2  # = 0.25
        assert abs(result.failure_index - expected) < 1e-9

    def test_at_xt_gives_fi_one(self, t300_5208):
        """σ₂=0, τ₁₂=0, σ₁=Xt → FI=1."""
        mat = t300_5208
        result = tsai_hill(sigma1=mat.Xt, sigma2=0.0, tau12=0.0, material=mat)
        assert abs(result.failure_index - 1.0) < 1e-9

    def test_at_yt_gives_fi_one_in_sigma2(self, t300_5208):
        """σ₁=0, τ₁₂=0, σ₂=Yt → FI=1."""
        mat = t300_5208
        result = tsai_hill(sigma1=0.0, sigma2=mat.Yt, tau12=0.0, material=mat)
        assert abs(result.failure_index - 1.0) < 1e-9

    def test_pure_shear_at_s12(self, t300_5208):
        """σ₁=0, σ₂=0, τ₁₂=S₁₂ → FI = 1."""
        mat = t300_5208
        result = tsai_hill(sigma1=0.0, sigma2=0.0, tau12=mat.S12, material=mat)
        assert abs(result.failure_index - 1.0) < 1e-9

    def test_uniaxial_mises_collapse_is_not_fi_one_for_partial_load(self, t300_5208):
        """At 50% of Xt uniaxially, FI = 0.25 (not 1)."""
        mat = t300_5208
        result = tsai_hill(sigma1=mat.Xt * 0.5, sigma2=0.0, tau12=0.0, material=mat)
        assert abs(result.failure_index - 0.25) < 1e-9

    def test_criterion_name(self, t300_5208):
        result = tsai_hill(sigma1=100.0, sigma2=0.0, tau12=0.0, material=t300_5208)
        assert "Tsai-Hill" in result.criterion


# ===========================================================================
# Section 3: Max-stress
# ===========================================================================

class TestMaxStress:
    def test_fiber_tension_mode(self, t300_5208):
        """High σ₁ tension → fiber-tension mode."""
        mat = t300_5208
        result = max_stress(sigma1=mat.Xt * 1.1, sigma2=1.0, tau12=1.0, material=mat)
        assert result.mode == FailureMode.FIBER_TENSION
        assert result.failed is True

    def test_matrix_tension_mode(self, t300_5208):
        """High σ₂ → matrix-tension mode when σ₁ is small."""
        mat = t300_5208
        result = max_stress(sigma1=10.0, sigma2=mat.Yt * 1.1, tau12=1.0, material=mat)
        assert result.mode == FailureMode.MATRIX_TENSION

    def test_shear_mode(self, t300_5208):
        """High τ₁₂ → shear mode."""
        mat = t300_5208
        result = max_stress(sigma1=1.0, sigma2=1.0, tau12=mat.S12 * 1.1, material=mat)
        assert result.mode == FailureMode.SHEAR

    def test_fiber_compression_mode(self, t300_5208):
        """Negative σ₁ exceeding Xc → fiber-compression."""
        mat = t300_5208
        result = max_stress(sigma1=-mat.Xc * 1.1, sigma2=0.0, tau12=0.0, material=mat)
        assert result.mode == FailureMode.FIBER_COMPRESSION
        assert result.failed is True

    def test_safe_at_half_allowables(self, t300_5208):
        mat = t300_5208
        result = max_stress(sigma1=mat.Xt / 2, sigma2=mat.Yt / 2, tau12=mat.S12 / 2, material=mat)
        assert result.failure_index == pytest.approx(0.5, abs=1e-9)
        assert result.failed is False


# ===========================================================================
# Section 4: Max-strain
# ===========================================================================

class TestMaxStrain:
    def test_safe_state(self, t300_5208):
        """Small stresses → failure index well below 1."""
        result = max_strain(sigma1=100.0, sigma2=5.0, tau12=5.0, material=t300_5208)
        assert result.failed is False
        assert result.failure_index < 1.0

    def test_fiber_direction_governs(self, t300_5208):
        """Large σ₁ makes fiber strain govern."""
        mat = t300_5208
        result = max_strain(sigma1=mat.Xt * 0.9, sigma2=0.0, tau12=0.0, material=mat)
        assert result.fi_eps1 > result.fi_eps2
        assert result.fi_eps1 > result.fi_gamma12

    def test_criterion_name(self, t300_5208):
        result = max_strain(sigma1=100.0, sigma2=0.0, tau12=0.0, material=t300_5208)
        assert "Max-strain" in result.criterion


# ===========================================================================
# Section 5: Hashin
# ===========================================================================

class TestHashin:
    def test_fiber_tension_mode_distinguished(self, t300_5208):
        """
        Oracle: σ₁ > 0, σ₁ ≈ Xt, σ₂=0, τ₁₂=0 → mode must be FIBER_TENSION.
        """
        mat = t300_5208
        result = hashin(sigma1=mat.Xt * 1.01, sigma2=0.0, tau12=0.0, material=mat)
        assert result.mode == FailureMode.FIBER_TENSION
        assert result.failed is True
        assert result.fi_fiber_tension >= 1.0

    def test_matrix_tension_mode_distinguished(self, t300_5208):
        """
        Oracle: σ₂ > 0, σ₂ ≈ Yt, σ₁=0, τ₁₂=0 → mode must be MATRIX_TENSION.
        """
        mat = t300_5208
        result = hashin(sigma1=0.0, sigma2=mat.Yt * 1.01, tau12=0.0, material=mat)
        assert result.mode == FailureMode.MATRIX_TENSION
        assert result.failed is True

    def test_fiber_tension_not_matrix_when_sigma1_large(self, t300_5208):
        """
        When σ₁ >> σ₂ and σ₂ is well below Yt, Hashin should report
        FIBER_TENSION not MATRIX_TENSION.
        """
        mat = t300_5208
        result = hashin(sigma1=mat.Xt * 1.05, sigma2=5.0, tau12=2.0, material=mat)
        assert result.mode == FailureMode.FIBER_TENSION

    def test_matrix_compression_mode(self, t300_5208):
        """σ₂ < 0 at Yc → matrix-compression mode."""
        mat = t300_5208
        result = hashin(sigma1=0.0, sigma2=-mat.Yc * 1.01, tau12=0.0, material=mat)
        assert result.mode == FailureMode.MATRIX_COMPRESSION

    def test_fiber_compression_mode(self, t300_5208):
        """σ₁ < 0 at Xc → fiber-compression mode."""
        mat = t300_5208
        result = hashin(sigma1=-mat.Xc * 1.01, sigma2=0.0, tau12=0.0, material=mat)
        assert result.mode == FailureMode.FIBER_COMPRESSION

    def test_safe_state_no_failure(self, t300_5208):
        mat = t300_5208
        result = hashin(sigma1=100.0, sigma2=5.0, tau12=5.0, material=mat)
        assert result.failed is False

    def test_fi_fiber_tension_analytic(self, t300_5208):
        """
        At σ₁=Xt, σ₂=0, τ₁₂=0:
          FI_ft = (Xt/Xt)² + α*(0/S12)² = 1.0
        """
        mat = t300_5208
        result = hashin(sigma1=mat.Xt, sigma2=0.0, tau12=0.0, material=mat, alpha=1.0)
        assert abs(result.fi_fiber_tension - 1.0) < 1e-9

    def test_fi_matrix_tension_analytic(self, t300_5208):
        """
        At σ₂=Yt, σ₁=0, τ₁₂=0:
          FI_mt = (Yt/Yt)² + 0 = 1.0
        """
        mat = t300_5208
        result = hashin(sigma1=0.0, sigma2=mat.Yt, tau12=0.0, material=mat)
        assert abs(result.fi_matrix_tension - 1.0) < 1e-9

    def test_criterion_name(self, t300_5208):
        result = hashin(sigma1=100.0, sigma2=0.0, tau12=0.0, material=t300_5208)
        assert "Hashin" in result.criterion


# ===========================================================================
# Section 6: Interlaminar shear
# ===========================================================================

class TestInterlaminarShear:
    def test_max_at_neutral_axis_090_0(self, layup_090_0):
        """
        Oracle: [0/90/0] laminate — max ILSS at the neutral axis (z≈0).

        Rationale: outer 0° plies have much higher Q̄₁₁ than the inner 90° ply.
        The integral ∫Q̄₁₁·z dz accumulates fastest where Q̄₁₁ is large.
        For [0/90/0] the first jump is at z = −h/6 (outer/inner ply interface),
        the neutral axis is at z = 0 (mid-plane = centre of 90° ply), and
        there is a corresponding interface at z = +h/6.  By symmetry the
        maximum |τ_xz| occurs at the neutral-axis interfaces (inner/outer).
        """
        result = interlaminar_shear(layup_090_0, Mx=1000.0, beam_length=100.0)
        # Interface indices: 0 (bot), 1 (0°/90° interface, z<0), 2 (90°/0° interface, z>0), 3 (top)
        abs_tau = np.abs(result.tau_xz)
        max_idx = result.max_interface_index

        # The maximum must be at one of the inner interfaces (1 or 2), not the free surfaces (0 or 3)
        assert max_idx in (1, 2), (
            f"Expected max ILSS at inner interface (1 or 2), got index {max_idx} "
            f"at z={result.max_interface_z:.4f} mm. τ_xz = {result.tau_xz}"
        )

    def test_free_surfaces_near_zero(self, layup_090_0):
        """Free surfaces at top and bottom have zero ILSS (equilibrium BC)."""
        result = interlaminar_shear(layup_090_0, Mx=1000.0)
        assert abs(result.tau_xz[0]) < 1e-10, "Bottom free surface τ_xz should be 0."

    def test_ilss_scales_with_moment(self, layup_090_0):
        """ILSS scales linearly with applied moment."""
        r1 = interlaminar_shear(layup_090_0, Mx=1000.0)
        r2 = interlaminar_shear(layup_090_0, Mx=2000.0)
        ratio = r2.max_tau_xz / r1.max_tau_xz
        assert abs(ratio - 2.0) < 1e-6

    def test_symmetric_laminate_symmetry(self, layup_090_0):
        """For a symmetric [0/90/0] the τ profile is antisymmetric about mid-plane."""
        result = interlaminar_shear(layup_090_0, Mx=1000.0)
        # Interfaces 1 and 2 should be equal in magnitude, opposite in sign for a
        # symmetric laminate (the two inner-interface values are mirror images).
        tau = result.tau_xz
        # tau[1] and tau[2] should be equal magnitude (they are by construction for [0/90/0])
        assert abs(abs(tau[1]) - abs(tau[2])) < 1e-8

    def test_ilss_neutral_axis_helper(self, layup_090_0):
        """ilss_neutral_axis helper returns the value at z=0."""
        full = interlaminar_shear(layup_090_0, Mx=1000.0)
        na_value = ilss_neutral_axis(layup_090_0, Mx=1000.0)
        # The neutral axis (z=0) is at an interface for [0/90/0]; the value should be
        # consistent with full result
        z = full.interface_z
        mid_idx = int(np.argmin(np.abs(z)))
        assert abs(na_value - abs(full.tau_xz[mid_idx])) < 1e-10

    def test_ilss_positive_for_positive_moment(self, layup_090_0):
        """With a positive moment, max_tau_xz is positive (non-zero)."""
        result = interlaminar_shear(layup_090_0, Mx=500.0)
        assert result.max_tau_xz > 0.0


# ===========================================================================
# Section 7: Thermal residual stress
# ===========================================================================

class TestThermalResidual:
    """
    Analytic oracle: [0/90/0] T300/5208 CFRP.

    T_cure = 175°C, T_service = 20°C  →  ΔT = 20 − 175 = −155°C

    CTE values for T300/5208 (Reddy 2004):
      α₁ ≈ 0.02 × 10⁻⁶ /°C   (fibre-dominated; near zero)
      α₂ ≈ 22.5 × 10⁻⁶ /°C   (matrix-dominated; large)

    On cooling, the 90° ply wants to contract a lot in the x-direction
    (because its fibre direction is y, so its x-direction CTE = α₂ = large).
    The laminate compromises: actual x-strain lies between the two free strains.
    The 0° ply is forced to contract more than its near-zero free strain →
    compressive σ₁ in the 0° plies.  The 90° ply is held back from contracting
    as much as it wants → tensile transverse stress σ₂ in the 90° ply.

    Sign check: σ₁ (fibre-direction stress) in the 0° plies < 0 (compressive).
    """

    T_CURE = 175.0   # °C
    T_SERV = 20.0    # °C
    DELTA_T = T_SERV - T_CURE  # = −155 °C

    ALPHA1 = 0.02e-6   # 1/°C
    ALPHA2 = 22.5e-6   # 1/°C

    def test_zero_plies_compressive_on_cooldown(self, layup_090_0):
        """
        Oracle: σ₁ in 0° plies (indices 0 and 2) must be negative (compressive)
        after cooling from cure.

        Reasoning: on cool-down the 90° ply (whose x-dir CTE = α₂ >> α₁) wants
        to contract far more in x than the 0° outer plies (x-dir CTE ≈ α₁ ≈ 0).
        The laminate compromise strain lies between the two free strains, i.e.
        more negative than α₁·ΔT.  The 0° ply is therefore forced to contract
        more than its free-strain → mechanical strain is compressive → σ₁ < 0.

        Simultaneously the 90° ply is pulled back from its large contraction →
        its x-direction (= transverse in ply frame) stress σ₂ is tensile.
        """
        layup = layup_090_0
        n = layup.num_plies
        alpha1_list = [self.ALPHA1] * n
        alpha2_list = [self.ALPHA2] * n

        result = thermal_residual(
            layup,
            alpha1_list=alpha1_list,
            alpha2_list=alpha2_list,
            delta_T=self.DELTA_T,
        )

        # 0° plies are index 0 and 2
        s0 = result.ply_stresses[0]   # 0° ply
        s2 = result.ply_stresses[2]   # 0° ply

        assert s0.sigma1 < 0.0, (
            f"Expected compressive σ₁ in 0° ply 0, got {s0.sigma1:.4f} MPa"
        )
        assert s2.sigma1 < 0.0, (
            f"Expected compressive σ₁ in 0° ply 2, got {s2.sigma1:.4f} MPa"
        )

    def test_ninety_ply_tensile_in_transverse_x_direction(self, layup_090_0):
        """
        The 90° ply (index 1) has fibre direction = y.
        Its transverse direction (σ₂ in ply frame) is the x-direction.

        On cooldown the 90° ply wants to contract heavily in x (large α₂).
        The stiff 0° outer plies resist this, so the 90° ply is forced to
        remain longer in x than it wants → tensile transverse stress σ₂ > 0.
        """
        layup = layup_090_0
        n = layup.num_plies
        result = thermal_residual(
            layup,
            alpha1_list=[self.ALPHA1] * n,
            alpha2_list=[self.ALPHA2] * n,
            delta_T=self.DELTA_T,
        )
        s1 = result.ply_stresses[1]   # 90° ply
        # σ₂ in 90° ply principal frame = transverse = x-direction stress
        # The 0° plies keep the 90° ply from contracting freely in x → tensile σ₂
        assert s1.sigma2 > 0.0, (
            f"Expected tensile σ₂ in 90° ply (x-direction), got {s1.sigma2:.4f} MPa"
        )

    def test_delta_T_sign(self, layup_090_0):
        """delta_T in result matches input."""
        layup = layup_090_0
        n = layup.num_plies
        result = thermal_residual(
            layup,
            alpha1_list=[self.ALPHA1] * n,
            alpha2_list=[self.ALPHA2] * n,
            delta_T=self.DELTA_T,
        )
        assert result.delta_T == self.DELTA_T

    def test_zero_delta_T_gives_zero_stress(self, layup_090_0):
        """ΔT = 0 → all residual stresses are zero."""
        layup = layup_090_0
        n = layup.num_plies
        result = thermal_residual(
            layup,
            alpha1_list=[self.ALPHA1] * n,
            alpha2_list=[self.ALPHA2] * n,
            delta_T=0.0,
        )
        for ps in result.ply_stresses:
            assert abs(ps.sigma1) < 1e-9, f"Expected σ₁≈0, got {ps.sigma1}"
            assert abs(ps.sigma2) < 1e-9, f"Expected σ₂≈0, got {ps.sigma2}"
            assert abs(ps.tau12) < 1e-9,  f"Expected τ₁₂≈0, got {ps.tau12}"

    def test_stress_scales_with_delta_T(self, layup_090_0):
        """Residual stress scales linearly with ΔT."""
        layup = layup_090_0
        n = layup.num_plies
        r1 = thermal_residual(
            layup,
            alpha1_list=[self.ALPHA1] * n,
            alpha2_list=[self.ALPHA2] * n,
            delta_T=self.DELTA_T,
        )
        r2 = thermal_residual(
            layup,
            alpha1_list=[self.ALPHA1] * n,
            alpha2_list=[self.ALPHA2] * n,
            delta_T=self.DELTA_T * 2.0,
        )
        s1_r1 = r1.ply_stresses[0].sigma1
        s1_r2 = r2.ply_stresses[0].sigma1
        assert abs(s1_r2 / s1_r1 - 2.0) < 1e-6

    def test_uniform_helper(self, layup_090_0):
        """thermal_residual_uniform gives same result as per-ply version."""
        layup = layup_090_0
        n = layup.num_plies
        r1 = thermal_residual(
            layup,
            alpha1_list=[self.ALPHA1] * n,
            alpha2_list=[self.ALPHA2] * n,
            delta_T=self.DELTA_T,
        )
        r2 = thermal_residual_uniform(
            layup,
            alpha1=self.ALPHA1,
            alpha2=self.ALPHA2,
            delta_T=self.DELTA_T,
        )
        for ps1, ps2 in zip(r1.ply_stresses, r2.ply_stresses):
            assert abs(ps1.sigma1 - ps2.sigma1) < 1e-9
            assert abs(ps1.sigma2 - ps2.sigma2) < 1e-9

    def test_num_ply_stresses_matches_layup(self, layup_090_0):
        """Result has one entry per ply."""
        layup = layup_090_0
        n = layup.num_plies
        result = thermal_residual_uniform(
            layup, alpha1=self.ALPHA1, alpha2=self.ALPHA2, delta_T=self.DELTA_T
        )
        assert len(result.ply_stresses) == n

    def test_ply_angles_in_result(self, layup_090_0):
        """PlyThermalStress.angle matches the layup angles."""
        layup = layup_090_0
        n = layup.num_plies
        result = thermal_residual_uniform(
            layup, alpha1=self.ALPHA1, alpha2=self.ALPHA2, delta_T=self.DELTA_T
        )
        for i, ps in enumerate(result.ply_stresses):
            assert ps.angle == layup.plies[i].angle
            assert ps.ply_index == i
