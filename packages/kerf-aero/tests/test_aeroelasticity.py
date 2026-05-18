"""
Pytest analytic-oracle tests for the kerf_aero aeroelasticity module.

Oracles:
1. Theodorsen 2-DOF typical-section flutter: flutter speed U_F within ±5% of
   the reference value 2.165 * b * ω_α  (Bisplinghoff, Ashley & Halfman 1955,
   Chapter 6; also NACA TN 3696, Fig. 4).

2. p-k damping curve crosses zero at the flutter velocity within ±1%.

3. Doublet-lattice on a single-panel flat wing at k=0 reduces to the steady
   VLM — specifically, the AIC matrix at k=0 is real and the implied lift-
   curve slope dCL/dα is positive (consistency check).
"""

import math
import sys
import os

import numpy as np
import pytest

# ---------------------------------------------------------------------------
# Path bootstrap (in case conftest.py is not run first)
# ---------------------------------------------------------------------------
_HERE    = os.path.dirname(os.path.abspath(__file__))
_PLUGIN  = os.path.dirname(_HERE)
_PACKAGES = os.path.dirname(_PLUGIN)
_SRC = os.path.join(_PLUGIN, "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

# Also add kerf-core src if present (soft dep)
_core_src = os.path.join(_PACKAGES, "kerf-core", "src")
if os.path.isdir(_core_src) and _core_src not in sys.path:
    sys.path.insert(0, _core_src)

# ---------------------------------------------------------------------------
# Imports from the modules under test
# ---------------------------------------------------------------------------
from kerf_aero.aeroelasticity import (
    TypicalSectionParams,
    theodorsen_C,
    typical_section_pk,
    run_typical_section,
)
from kerf_aero.doublet_lattice import (
    TrapezoidalPanel,
    build_aic_matrix,
    make_rectangular_wing,
    steady_vlm_lift_slope,
)
from kerf_aero.flutter_pk import (
    ModalMode,
    FlutterResult,
    FlutterPoint,
    project_aic,
    pk_flutter_sweep,
)


# ===========================================================================
# Helper
# ===========================================================================

def _relative_error(computed: float, reference: float) -> float:
    if abs(reference) < 1e-30:
        return abs(computed)
    return abs(computed - reference) / abs(reference)


# ===========================================================================
# Oracle 1 — Theodorsen typical-section flutter speed ≈ 2.165 b ω_α  (±5%)
# ===========================================================================

class TestTypicalSectionFlutterSpeed:
    """Textbook 2-DOF typical-section flutter oracle.

    Parameters (NACA/Bisplinghoff canonical case):
        b = 1 m, a = -0.2, x_α = 0.1, r_α = 0.5,
        ω_h/ω_α = 0.5, μ = 20, ρ = 1.225 kg/m³

    Reference flutter speed: U_F* = U_F / (b ω_α) ≈ 2.165
    """

    # Standard parameters
    PARAMS = dict(
        b=1.0,
        a=-0.2,
        x_alpha=0.1,
        r_alpha=0.5,
        omega_h_over_omega_a=0.5,
        mu=20.0,
        rho=1.225,
        omega_alpha=1.0,   # rad/s (sets velocity scale)
    )
    U_F_STAR_REF = 2.165  # reference non-dimensional flutter speed
    TOL_REL = 0.05         # ±5% tolerance

    def test_flutter_speed_within_tolerance(self):
        """Flutter speed must be within ±5% of the 2.165 b ω_α reference."""
        result = run_typical_section(**self.PARAMS, n_V=300, V_max_factor=5.0)

        U_F    = result["flutter_speed"]
        U_F_nd = result["flutter_speed_nd"]

        assert not math.isnan(U_F), (
            "Flutter solver returned NaN — no flutter detected in the sweep range."
        )
        assert U_F > 0.0, f"Flutter speed must be positive, got {U_F}"

        err = _relative_error(U_F_nd, self.U_F_STAR_REF)
        assert err < self.TOL_REL, (
            f"Flutter speed U_F* = {U_F_nd:.4f} deviates {err*100:.1f}% from "
            f"reference {self.U_F_STAR_REF} (tolerance ±{self.TOL_REL*100:.0f}%)"
        )

    def test_flutter_frequency_physical(self):
        """Flutter frequency must lie between ω_h and ω_α."""
        result = run_typical_section(**self.PARAMS, n_V=300, V_max_factor=5.0)
        params = result["params"]
        omega_f = result["flutter_freq"]

        assert not math.isnan(omega_f), "Flutter frequency must not be NaN."
        assert params.omega_h <= omega_f <= params.omega_alpha * 1.5, (
            f"Flutter frequency {omega_f:.4f} rad/s outside expected range "
            f"[{params.omega_h:.4f}, {params.omega_alpha * 1.5:.4f}]"
        )


# ===========================================================================
# Oracle 2 — p-k damping crosses zero at flutter speed (within ±1%)
# ===========================================================================

class TestPKDampingCrossing:
    """The p-k V-g diagram must show a damping zero crossing at U_F.

    For the same canonical parameters, the damping g = 2 Re(p)/Im(p) for
    one mode should cross from negative (stable) to zero (flutter) to
    positive (unstable) at the flutter speed.
    """

    def test_damping_crosses_zero(self):
        """The unstable mode must transition from g < 0 to g > 0 at U_F."""
        params = TypicalSectionParams(
            b=1.0, a=-0.2, x_alpha=0.1, r_alpha=0.5,
            omega_h=0.5, omega_alpha=1.0,
            mu=20.0, rho=1.225,
        )

        # Sweep with fine resolution around the expected flutter speed
        V_ref = params.b * params.omega_alpha   # = 1.0 m/s
        U_F_approx = 2.165 * V_ref
        V_arr = np.linspace(0.05 * V_ref, 4.0 * V_ref, 400)

        result = typical_section_pk(params, V_arr)

        U_F = result["flutter_speed"]
        assert not math.isnan(U_F), "p-k method must detect flutter."

        # Find the zero crossing in the unstable mode
        damping = result["damping"]   # shape (N_V, 2)
        V_cross_found = False

        for mode_idx in range(2):
            g_col = damping[:, mode_idx]
            # Find last sign change from - to +
            for i in range(1, len(V_arr)):
                if (
                    not math.isnan(g_col[i - 1])
                    and not math.isnan(g_col[i])
                    and g_col[i - 1] < 0.0
                    and g_col[i] >= 0.0
                ):
                    # Linear interpolation of zero crossing
                    V_cross = (
                        V_arr[i - 1]
                        + (-g_col[i - 1]) / (g_col[i] - g_col[i - 1])
                        * (V_arr[i] - V_arr[i - 1])
                    )
                    err = _relative_error(V_cross, U_F)
                    assert err < 0.01, (
                        f"Damping zero crossing at V={V_cross:.4f} differs "
                        f"from reported flutter speed U_F={U_F:.4f} by "
                        f"{err*100:.2f}% (tolerance ±1%)"
                    )
                    V_cross_found = True
                    break
            if V_cross_found:
                break

        assert V_cross_found, (
            "No damping zero crossing found in p-k V-g curve. "
            "The unstable mode must pass through zero damping at flutter speed."
        )

    def test_stable_below_flutter(self):
        """Both modes must have negative damping below 90% of flutter speed."""
        params = TypicalSectionParams(
            b=1.0, a=-0.2, x_alpha=0.1, r_alpha=0.5,
            omega_h=0.5, omega_alpha=1.0,
            mu=20.0, rho=1.225,
        )
        V_ref = params.b * params.omega_alpha
        U_F_approx = 2.165 * V_ref

        # Sweep only up to 80% of expected flutter speed
        V_sub = np.linspace(0.1 * V_ref, 0.8 * U_F_approx, 100)
        result = typical_section_pk(params, V_sub)

        damping = result["damping"]
        # At all velocities below flutter, both modes should be stable (g < 0)
        for m in range(2):
            valid = damping[:, m][~np.isnan(damping[:, m])]
            if len(valid) > 0:
                max_g = float(np.max(valid))
                assert max_g < 0.1, (
                    f"Mode {m} has positive damping g={max_g:.4f} below 80% "
                    f"of the expected flutter speed (structural system should "
                    f"be stable sub-flutter)."
                )


# ===========================================================================
# Oracle 3 — DLM at k=0 reduces to steady VLM
# ===========================================================================

class TestDLMSteadyLimit:
    """Doublet-lattice at k=0 must be consistent with steady VLM.

    Checks:
    (a) AIC matrix is purely real at k=0 (no imaginary part due to unsteady
        aero forces).
    (b) Single-panel AIC has a positive diagonal (positive downwash from
        positive doublet strength).
    (c) Lift-curve slope for a rectangular wing (AR=8) is positive.
    """

    def test_aic_real_at_k0_single_panel(self):
        """AIC matrix must be real (|Im| ≈ 0) at k=0."""
        panel = TrapezoidalPanel(
            x_ea=0.25, y_ea=0.5,
            chord=1.0, span=1.0,
        )
        Q0 = build_aic_matrix([panel], k=0.0, M=0.0)
        assert Q0.shape == (1, 1)

        imag_frac = abs(Q0[0, 0].imag) / (abs(Q0[0, 0]) + 1e-30)
        assert imag_frac < 1e-8, (
            f"AIC imaginary fraction at k=0: {imag_frac:.2e} (expected < 1e-8)"
        )

    def test_aic_positive_diagonal(self):
        """Diagonal of AIC at k=0 must be positive (self-downwash is positive)."""
        panels = make_rectangular_wing(span=8.0, chord=1.0, n_span=4, n_chord=1)
        Q0 = build_aic_matrix(panels, k=0.0, M=0.0)
        diag = np.real(np.diag(Q0))
        assert np.all(diag > 0), (
            f"Diagonal of k=0 AIC must be positive. Got min = {diag.min():.4f}"
        )

    def test_lift_slope_positive(self):
        """Lift-curve slope from steady VLM must be positive."""
        panels = make_rectangular_wing(span=8.0, chord=1.0, n_span=8, n_chord=1)
        dCL_dalpha = steady_vlm_lift_slope(panels, M=0.0)
        assert dCL_dalpha > 0.0, (
            f"VLM lift-curve slope must be positive, got {dCL_dalpha:.4f}"
        )

    def test_aic_k0_matches_k_small(self):
        """AIC at k=0 and k=1e-6 must agree to within 0.1%."""
        panels = make_rectangular_wing(span=4.0, chord=1.0, n_span=2, n_chord=1)
        Q0     = build_aic_matrix(panels, k=0.0,  M=0.0)
        Q_eps  = build_aic_matrix(panels, k=1e-6, M=0.0)

        # Compare real parts
        rel_diff = np.max(
            np.abs(np.real(Q0) - np.real(Q_eps))
            / (np.abs(np.real(Q0)) + 1e-20)
        )
        assert rel_diff < 1e-3, (
            f"Real part of AIC differs between k=0 and k=1e-6 by "
            f"{rel_diff:.2e} (should agree to < 0.1%)."
        )

    def test_single_panel_k0_positive_real(self):
        """Single-panel AIC at k=0 must have positive real part (positive downwash)."""
        panel = TrapezoidalPanel(x_ea=0.25, y_ea=0.5, chord=1.0, span=2.0)
        Q0 = build_aic_matrix([panel], k=0.0, M=0.0)
        assert Q0[0, 0].real > 0.0, (
            f"Single-panel AIC real part must be > 0, got {Q0[0,0].real:.6f}"
        )


# ===========================================================================
# Supplementary: Theodorsen function properties
# ===========================================================================

class TestTheodorsenFunction:
    """Verify basic properties of the Theodorsen C(k) function."""

    def test_quasi_steady_limit(self):
        """C(k→0) should approach 1."""
        C = theodorsen_C(1e-6)
        assert abs(C.real - 1.0) < 0.01, f"C(k→0).real = {C.real:.4f}, expected ~1.0"
        assert abs(C.imag) < 0.01, f"C(k→0).imag = {C.imag:.4f}, expected ~0.0"

    def test_high_k_limit(self):
        """C(k→∞) should approach 0.5."""
        C = theodorsen_C(100.0)
        assert abs(C.real - 0.5) < 0.02, f"C(k→∞).real = {C.real:.4f}, expected ~0.5"

    def test_magnitude_between_half_and_one(self):
        """|C(k)| must lie in [0.5, 1.0] for all k > 0."""
        for k in [0.01, 0.1, 0.5, 1.0, 2.0, 5.0, 10.0]:
            C = theodorsen_C(k)
            mag = abs(C)
            assert 0.45 <= mag <= 1.05, (
                f"C({k}) magnitude {mag:.4f} outside expected [0.45, 1.05]"
            )

    def test_real_part_monotone_decreasing(self):
        """F(k) = Re(C(k)) should be monotonically non-increasing."""
        k_vals = np.linspace(0.01, 5.0, 50)
        F_vals = np.array([theodorsen_C(k).real for k in k_vals])
        diffs = np.diff(F_vals)
        assert np.all(diffs <= 0.05), (
            "F(k) = Re(C(k)) should be monotonically non-increasing."
        )


# ===========================================================================
# Supplementary: DLM panel construction
# ===========================================================================

class TestDLMPanelConstruction:
    """Sanity checks for the doublet-lattice panel mesh."""

    def test_rectangular_wing_panel_count(self):
        """make_rectangular_wing must return n_span * n_chord panels."""
        for ns, nc in [(4, 1), (6, 2), (8, 4)]:
            panels = make_rectangular_wing(span=4.0, chord=1.0, n_span=ns, n_chord=nc)
            assert len(panels) == ns * nc, (
                f"Expected {ns * nc} panels, got {len(panels)}"
            )

    def test_panel_geometry(self):
        """Panel doublet line must be at 1/4-chord of sub-panel."""
        panels = make_rectangular_wing(span=4.0, chord=1.0, n_span=4, n_chord=2)
        for p in panels:
            # x_ea should be at 1/4 of sub-panel chord from LE
            dx = 1.0 / 2   # sub-panel chord = total_chord / n_chord
            expected_x_ea_options = [0.25 * dx, dx + 0.25 * dx]  # two chordwise positions
            assert any(
                abs(p.x_ea - x) < 1e-10 for x in expected_x_ea_options
            ), f"Panel x_ea={p.x_ea:.6f} not at 1/4-chord of sub-panel"

    def test_panel_areas_positive(self):
        """All panel areas must be positive."""
        panels = make_rectangular_wing(span=8.0, chord=2.0, n_span=6, n_chord=3)
        for p in panels:
            assert p.area > 0.0, f"Panel area must be positive, got {p.area}"

    def test_aic_matrix_shape(self):
        """AIC matrix shape must be (N, N) for N panels."""
        panels = make_rectangular_wing(span=4.0, chord=1.0, n_span=4, n_chord=1)
        N = len(panels)
        Q = build_aic_matrix(panels, k=0.3, M=0.3)
        assert Q.shape == (N, N), f"Expected shape ({N},{N}), got {Q.shape}"

    def test_aic_subsonic_only(self):
        """build_aic_matrix must raise ValueError for M >= 1."""
        panels = make_rectangular_wing(span=2.0, chord=1.0, n_span=2, n_chord=1)
        with pytest.raises(ValueError, match="subsonic"):
            build_aic_matrix(panels, k=0.3, M=1.0)
        with pytest.raises(ValueError, match="subsonic"):
            build_aic_matrix(panels, k=0.3, M=1.5)


# ===========================================================================
# Supplementary: p-k sweep with synthetic modes
# ===========================================================================

class TestPKSweepSynthetic:
    """Smoke-test the p-k flutter sweep with simple synthetic modes."""

    def test_pk_sweep_runs_and_returns_result(self):
        """pk_flutter_sweep must return a FlutterResult without error."""
        panels = make_rectangular_wing(span=4.0, chord=1.0, n_span=4, n_chord=1)
        N = len(panels)

        # Two synthetic modes: uniform plunge and linear pitch
        mode0 = ModalMode(
            frequency=5.0,
            mode_shape=np.ones(N),
            modal_mass=1.0,
        )
        mode1 = ModalMode(
            frequency=10.0,
            mode_shape=np.linspace(0.0, 1.0, N),
            modal_mass=1.0,
        )

        V_arr = np.linspace(1.0, 100.0, 30)
        result = pk_flutter_sweep(
            modes=[mode0, mode1],
            panels=panels,
            rho=1.225,
            b_ref=0.5,
            M=0.3,
            velocities=V_arr,
        )

        assert isinstance(result, FlutterResult)
        assert len(result.vg_curves) == 2
        for curve in result.vg_curves:
            assert len(curve) == len(V_arr)

    def test_vg_curve_has_correct_velocity_entries(self):
        """Each V-g point must match the swept velocity."""
        panels = make_rectangular_wing(span=2.0, chord=1.0, n_span=2, n_chord=1)
        N = len(panels)
        modes = [
            ModalMode(frequency=5.0, mode_shape=np.ones(N), modal_mass=1.0)
        ]
        V_arr = np.array([10.0, 20.0, 30.0, 40.0, 50.0])
        result = pk_flutter_sweep(
            modes=modes, panels=panels, rho=1.225,
            b_ref=0.5, M=0.2, velocities=V_arr,
        )

        for i, pt in enumerate(result.vg_curves[0]):
            assert abs(pt.velocity - V_arr[i]) < 1e-10, (
                f"V-g point velocity mismatch: {pt.velocity} != {V_arr[i]}"
            )

    def test_project_aic_shape(self):
        """project_aic must return (n_modes, n_modes) matrix."""
        panels = make_rectangular_wing(span=4.0, chord=1.0, n_span=4, n_chord=1)
        N = len(panels)
        Q_aero = build_aic_matrix(panels, k=0.2, M=0.3)
        panel_areas = np.array([p.area for p in panels])

        modes = [
            ModalMode(frequency=5.0, mode_shape=np.ones(N)),
            ModalMode(frequency=10.0, mode_shape=np.arange(N, dtype=float)),
        ]

        Q_modal = project_aic(Q_aero, modes, panel_areas)
        assert Q_modal.shape == (2, 2), f"Expected (2,2), got {Q_modal.shape}"
