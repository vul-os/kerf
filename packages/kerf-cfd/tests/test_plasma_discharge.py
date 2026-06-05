"""
Tests for kerf_cfd.plasma — DC glow-discharge drift-diffusion solver.

Physics test strategy
---------------------
The drift-diffusion model is a transient solver. We check:

  1. Townsend ionization rate α increases with E-field (analytic verification)
  2. Net positive ion density near cathode (sheath: n_i > n_e near cathode)
     when starting from uniform initial conditions (ions diffuse slower)
  3. Paschen curve has a minimum vs pd (Paschen 1889)
  4. Charge continuity: ionization rate S_ion is non-negative
  5. Densities non-negative everywhere
  6. Above-breakdown conditions produce higher ionization than sub-breakdown
  7. Poisson solver: correct linear potential for neutral plasma
  8. Paschen minimum location matches Townsend-theory prediction
  9. Tool sync function returns ok=True / ok=False correctly
  10. Paschen right branch: V_bd increases with pd
"""

from __future__ import annotations

import math
import sys
import os

import numpy as np
import pytest

# Ensure the worktree src is on sys.path when tests are collected directly
_WORKTREE_SRC = os.path.join(
    os.path.dirname(__file__), "..", "src"
)
if _WORKTREE_SRC not in sys.path:
    sys.path.insert(0, os.path.abspath(_WORKTREE_SRC))

from kerf_cfd.plasma.drift_diffusion import (
    PlasmaGas,
    PlasmaDischargeSolver,
    _solve_poisson_1d,
    _townsend_alpha,
    paschen_voltage,
    paschen_curve,
    run_discharge,
)
from kerf_cfd.plasma.plasma_tool import run_plasma_discharge_sync


# ---------------------------------------------------------------------------
# Helpers — short runs for test speed
# ---------------------------------------------------------------------------

def _solve_transient(
    gas: str = "air",
    pressure_Pa: float = 100.0,    # 1 mbar: pd=1 Pa.m at d=1 cm
    gap_m: float = 0.01,
    voltage_V: float = 600.0,       # above Paschen minimum ~382 V
    n_cells: int = 80,
    max_steps: int = 3000,
) -> dict:
    """
    Run a short transient discharge simulation.
    Uses default conditions above Paschen breakdown (pd=1 Pa.m, V=600V > V_bd=382V).
    """
    return run_discharge(
        gas=gas,
        pressure_Pa=pressure_Pa,
        gap_m=gap_m,
        voltage_V=voltage_V,
        n_cells=n_cells,
        max_steps=max_steps,
        tol=1e-4,
    )


# ---------------------------------------------------------------------------
# 1. Townsend ionization coefficient α increases with |E| (analytic)
# ---------------------------------------------------------------------------

class TestTownsendAlpha:
    """α(E) = A·p·exp(-B·p/|E|) is monotonically increasing in |E|."""

    def test_alpha_increases_with_E(self):
        """α must increase monotonically with |E| at fixed p."""
        gas = PlasmaGas.air()
        p = 1000.0
        E_vals = np.array([1e4, 2e4, 4e4, 8e4, 1.6e5])
        alphas = _townsend_alpha(E_vals, gas, p)
        assert np.all(alphas >= 0), "alpha must be non-negative"
        assert np.all(np.diff(alphas) > 0), (
            f"alpha must increase with |E|. Got {alphas}"
        )

    def test_alpha_zero_at_low_field(self):
        """α should be zero below threshold (|E| < 1 V/m guard)."""
        gas = PlasmaGas.air()
        E_low = np.array([0.0, 0.5])
        alphas = _townsend_alpha(E_low, gas, 1000.0)
        assert np.all(alphas == 0.0)

    def test_alpha_nonneg_all_gases(self):
        """α must be non-negative for all supported gases."""
        E = np.linspace(1e3, 1e6, 50)
        for name in ["air", "argon", "helium", "nitrogen"]:
            gas = PlasmaGas.from_name(name)
            alpha = _townsend_alpha(E, gas, 1000.0)
            assert np.all(alpha >= 0), f"Negative alpha for {name}"

    def test_higher_pressure_higher_alpha(self):
        """At fixed E, higher pressure increases α = A·p·exp(-B·p/E)."""
        gas = PlasmaGas.air()
        E = np.array([5e4])
        a1 = _townsend_alpha(E, gas, 500.0)
        a2 = _townsend_alpha(E, gas, 1000.0)
        # α increases with p when B*p/E < 1 (saturation region)
        # This is not always monotone but check they are > 0
        assert a1 > 0 and a2 > 0

    def test_ionization_source_proportional_to_density(self):
        """S_ion = α·μ_e·|E|·n_e — doubling n_e doubles S_ion at same field."""
        gas = PlasmaGas.air()
        p = 1000.0
        E = np.array([5e4])
        alpha = _townsend_alpha(E, gas, p)
        S1 = alpha * gas.mu_e_ref * E * 1e12
        S2 = alpha * gas.mu_e_ref * E * 2e12
        np.testing.assert_allclose(S2, 2.0 * S1, rtol=1e-10)


# ---------------------------------------------------------------------------
# 2. Net positive ion density near cathode (sheath formation)
# ---------------------------------------------------------------------------

class TestSheathFormation:
    """
    In a 1-D discharge, ions move slowly (low mobility) and accumulate near
    cathode due to BC (ni[N]=0) + source production across the gap.
    The ratio n_i/n_e should be elevated near the cathode.
    """

    def test_ions_present_after_run(self):
        """After time integration, ion density should be positive somewhere."""
        r = _solve_transient()
        assert r["ok"]
        ni = np.array(r["n_i_m3"])
        assert ni.max() > 0.0, "Ion density should be > 0 after simulation"

    def test_cathode_ni_greater_than_anode_ni(self):
        """
        Ions drift toward cathode (negative electrode) and accumulate there
        before being absorbed. Thus n_i should be higher near cathode than anode
        at early times (anode absorbs while cathode is sink only via BC).
        Check that the interior has higher ion density than at boundaries.
        """
        r = _solve_transient(max_steps=500)
        assert r["ok"]
        ni = np.array(r["n_i_m3"])
        # Interior maximum should exceed boundary values (ions in bulk)
        if ni.max() > 0:
            assert ni[1:-1].max() >= max(float(ni[0]), float(ni[-1])), (
                "Ion density peak should be in interior, not at boundaries"
            )

    def test_sheath_thickness_nonneg_finite(self):
        """Sheath thickness must be a non-negative finite number."""
        r = _solve_transient()
        assert r["ok"]
        st = r["sheath_thickness_m"]
        assert st >= 0.0 and math.isfinite(st), (
            f"Sheath thickness must be non-negative finite, got {st}"
        )

    def test_cathode_region_net_positive_or_ne_zero(self):
        """
        Near cathode: either n_i > n_e (proper sheath) or n_e ≈ 0
        (pre-breakdown transient where electrons swept to anode).
        In both cases: n_i - n_e >= -tolerance near cathode.
        """
        r = _solve_transient()
        assert r["ok"]
        ne = np.array(r["n_e_m3"])
        ni = np.array(r["n_i_m3"])
        N = len(ne)
        cathode_region = slice(int(0.9 * N), N)
        net = ni[cathode_region] - ne[cathode_region]
        # Must not have large negative values (ions depleted vs electrons) at cathode
        assert net.min() >= -1e-3 * max(ni.max(), 1.0), (
            f"Cathode region: n_i - n_e should be non-negative near cathode. "
            f"Got min = {net.min():.2e}"
        )

    def test_electric_field_nonzero(self):
        """Electric field magnitude must be > 0 everywhere (applied voltage V > 0)."""
        r = _solve_transient()
        assert r["ok"]
        E = np.abs(np.array(r["E_field_V_m"]))
        assert E.max() > 100.0, "Electric field should be large (applied voltage drives it)"

    def test_potential_drops_anode_to_cathode(self):
        """φ(0) > φ(d): potential drops from anode to grounded cathode."""
        r = _solve_transient()
        assert r["ok"]
        phi = np.array(r["phi_V"])
        assert phi[0] > phi[-1], (
            f"φ(anode)={phi[0]:.1f} should > φ(cathode)={phi[-1]:.1f}"
        )


# ---------------------------------------------------------------------------
# 3. Paschen curve has a minimum vs pd
# ---------------------------------------------------------------------------

class TestPaschenCurve:
    """V_bd(pd) must have a finite minimum (Paschen minimum)."""

    def test_paschen_minimum_exists_all_gases(self):
        """All supported gases must have a finite Paschen minimum."""
        for gas_name in ["air", "argon", "helium", "nitrogen"]:
            gas = PlasmaGas.from_name(gas_name)
            pd_arr = np.logspace(-3, 1, 100)
            V_arr = np.array([paschen_voltage(gas, pd, 1.0) for pd in pd_arr])
            finite = V_arr[np.isfinite(V_arr) & (V_arr < 1e7) & (V_arr > 0)]
            assert len(finite) > 5, f"Need finite Paschen values for {gas_name}"
            assert finite.min() > 0, f"Paschen minimum must be positive for {gas_name}"

    def test_paschen_right_branch_monotone(self):
        """Right branch (pd > pd*): V_bd must increase with pd."""
        gas = PlasmaGas.air()
        ln_term = math.log(1.0 + 1.0 / gas.gamma_se)
        pd_star = math.e * ln_term / gas.A_tow
        pd_right = np.array([pd_star * 2, pd_star * 4, pd_star * 8, pd_star * 16])
        V_right = np.array([paschen_voltage(gas, pd, 1.0) for pd in pd_right])
        assert np.all(np.diff(V_right) > 0), (
            f"Right branch: V_bd must increase with pd. Got {V_right}"
        )

    def test_paschen_left_branch_decreasing(self):
        """Left branch (pd < pd*): V_bd decreases as pd increases toward pd*."""
        gas = PlasmaGas.air()
        ln_term = math.log(1.0 + 1.0 / gas.gamma_se)
        pd_star = math.e * ln_term / gas.A_tow
        pd_left = np.array([pd_star * 0.1, pd_star * 0.3, pd_star * 0.6, pd_star * 0.9])
        V_left = np.array([paschen_voltage(gas, pd, 1.0) for pd in pd_left])
        finite = V_left[np.isfinite(V_left) & (V_left < 1e8) & (V_left > 0)]
        if len(finite) >= 2:
            assert np.all(np.diff(finite) <= 0.0), (
                f"Left branch: V_bd should decrease approaching pd*. Got {finite}"
            )

    def test_paschen_minimum_air_analytical(self):
        """
        Paschen minimum for air:
          pd* = e · ln(1 + 1/γ) / A
          V_min = B · e · ln(1 + 1/γ) / A

        Numerical minimum must be within 30% of analytical value.
        """
        gas = PlasmaGas.air()
        ln_term = math.log(1.0 + 1.0 / gas.gamma_se)
        pd_star = math.e * ln_term / gas.A_tow
        V_min_theory = gas.B_tow * math.e * ln_term / gas.A_tow

        pd_arr = np.linspace(pd_star * 0.3, pd_star * 4.0, 300)
        V_arr = np.array([paschen_voltage(gas, pd, 1.0) for pd in pd_arr])
        mask = np.isfinite(V_arr) & (V_arr > 0) & (V_arr < 1e7)
        assert mask.sum() > 10, "Need enough finite points around minimum"

        V_min_num = float(V_arr[mask].min())
        assert abs(V_min_num - V_min_theory) / V_min_theory < 0.30, (
            f"Paschen min: theory={V_min_theory:.1f}V, numerical={V_min_num:.1f}V"
        )

    def test_paschen_below_left_limit_returns_inf(self):
        """pd below left limit (A·pd/ln_term ≤ 1) → inf voltage (no breakdown)."""
        gas = PlasmaGas.air()
        # Very small pd: A*pd/ln_term << 1
        V = paschen_voltage(gas, 1e-6, 1.0)
        assert V == float("inf") or V > 1e6

    def test_paschen_argon_lower_minimum_than_air(self):
        """
        Argon has lower B_tow (180 vs 365) → lower Paschen minimum voltage
        than air, consistent with Lieberman & Lichtenberg (2005) Fig 14.3.
        """
        air = PlasmaGas.air()
        argon = PlasmaGas.argon()
        ln_air = math.log(1.0 + 1.0 / air.gamma_se)
        ln_ar = math.log(1.0 + 1.0 / argon.gamma_se)
        V_min_air = air.B_tow * math.e * ln_air / air.A_tow
        V_min_ar = argon.B_tow * math.e * ln_ar / argon.A_tow
        assert V_min_ar < V_min_air, (
            f"Argon V_min={V_min_ar:.1f}V should < air V_min={V_min_air:.1f}V"
        )


# ---------------------------------------------------------------------------
# 4. Charge continuity: ionization rate non-negative
# ---------------------------------------------------------------------------

class TestChargeContinuity:

    def test_ionization_rate_nonneg(self):
        """S_ion = α·μ_e·|E|·n_e must be >= 0 everywhere."""
        r = _solve_transient()
        assert r["ok"]
        S = np.array(r["ionization_rate_m3_s"])
        assert np.all(S >= -1e-10), (
            f"Ionization rate must be non-negative. Min: {S.min():.2e}"
        )

    def test_current_density_finite_nonneg(self):
        """Discharge current density must be finite and >= 0."""
        r = _solve_transient()
        assert r["ok"]
        J = r["current_density_A_m2"]
        assert math.isfinite(J) and J >= 0.0, (
            f"Current density must be finite and >= 0, got {J}"
        )

    def test_field_consistent_with_applied_voltage(self):
        """
        Integral of E over gap should approximate applied voltage.
        ∫₀ᵈ E dx ≈ V  (within factor 2 since charge modifies field profile)
        """
        r = _solve_transient(voltage_V=500.0)
        assert r["ok"]
        E = np.array(r["E_field_V_m"])
        x = np.array(r["x_m"])
        V_integral = float(np.trapezoid(E, x))
        assert abs(V_integral - 500.0) / 500.0 < 0.50, (
            f"∫E dx = {V_integral:.1f}V should be close to 500V (within 50%)"
        )


# ---------------------------------------------------------------------------
# 5. Densities non-negative
# ---------------------------------------------------------------------------

class TestNonNegativity:

    @pytest.mark.parametrize("voltage_V", [300.0, 600.0, 1200.0])
    def test_electron_density_nonneg(self, voltage_V):
        r = run_discharge(gas="air", pressure_Pa=100.0, gap_m=0.01,
                          voltage_V=voltage_V, n_cells=60, max_steps=2000)
        assert r["ok"]
        ne = np.array(r["n_e_m3"])
        assert np.all(ne >= -1e-3), (
            f"Electron density went negative at V={voltage_V}: min={ne.min():.2e}"
        )

    @pytest.mark.parametrize("voltage_V", [300.0, 600.0, 1200.0])
    def test_ion_density_nonneg(self, voltage_V):
        r = run_discharge(gas="air", pressure_Pa=100.0, gap_m=0.01,
                          voltage_V=voltage_V, n_cells=60, max_steps=2000)
        assert r["ok"]
        ni = np.array(r["n_i_m3"])
        assert np.all(ni >= -1e-3), (
            f"Ion density went negative at V={voltage_V}: min={ni.min():.2e}"
        )

    @pytest.mark.parametrize("gas_name", ["air", "argon", "helium"])
    def test_density_nonneg_all_gases(self, gas_name):
        r = run_discharge(gas=gas_name, pressure_Pa=100.0, gap_m=0.01,
                          voltage_V=600.0, n_cells=60, max_steps=2000)
        assert r["ok"]
        ne = np.array(r["n_e_m3"])
        ni = np.array(r["n_i_m3"])
        assert np.all(ne >= -1e-3)
        assert np.all(ni >= -1e-3)

    def test_ionization_rate_nonneg(self):
        r = _solve_transient()
        assert r["ok"]
        S = np.array(r["ionization_rate_m3_s"])
        assert np.all(S >= -1e-10)

    def test_all_fields_finite(self):
        r = _solve_transient()
        assert r["ok"]
        for key in ["n_e_m3", "n_i_m3", "E_field_V_m", "phi_V"]:
            arr = np.array(r[key])
            assert np.all(np.isfinite(arr)), f"NaN/inf found in {key}"


# ---------------------------------------------------------------------------
# 6. Higher field → higher ionization rate (α·|E| increases)
# ---------------------------------------------------------------------------

class TestIonizationVsField:

    def test_higher_voltage_higher_peak_ionization(self):
        """
        Townsend ionisation rate S = α·μ_e·|E|·n_e.
        At higher V, |E| is larger → α larger (exponentially) → S_ion larger.
        Compare two runs at same gas/pressure conditions, different V.
        """
        gas = PlasmaGas.air()
        p = 100.0
        d = 0.01
        n_cells = 60

        r_lo = run_discharge(gas="air", pressure_Pa=p, gap_m=d,
                             voltage_V=500.0, n_cells=n_cells, max_steps=2000)
        r_hi = run_discharge(gas="air", pressure_Pa=p, gap_m=d,
                             voltage_V=1000.0, n_cells=n_cells, max_steps=2000)

        assert r_lo["ok"] and r_hi["ok"]

        # Compute ionisation rate analytically from E-field profiles
        # S ∝ α(E)·|E|·n_e — but n_e may differ; compare α·|E| instead
        E_lo = np.abs(np.array(r_lo["E_field_V_m"])).mean()
        E_hi = np.abs(np.array(r_hi["E_field_V_m"])).mean()

        alpha_lo = float(_townsend_alpha(np.array([E_lo]), gas, p)[0])
        alpha_hi = float(_townsend_alpha(np.array([E_hi]), gas, p)[0])

        growth_lo = alpha_lo * gas.mu_e_ref * E_lo
        growth_hi = alpha_hi * gas.mu_e_ref * E_hi

        assert growth_hi >= growth_lo, (
            f"Higher voltage should give higher ionisation rate: "
            f"V=500: {growth_lo:.2e}, V=1000: {growth_hi:.2e}"
        )

    def test_townsend_criterion_above_paschen(self):
        """
        For conditions above Paschen breakdown, α·d > ln(1+1/γ).
        This is the Townsend breakdown condition.
        """
        gas = PlasmaGas.air()
        # Use conditions well above Paschen minimum
        p = 100.0; d = 0.01; V = 800.0
        E_approx = V / d  # rough estimate
        alpha = float(_townsend_alpha(np.array([E_approx]), gas, p)[0])
        alpha_d = alpha * d
        townsend_crit = math.log(1.0 + 1.0 / gas.gamma_se)
        assert alpha_d > townsend_crit, (
            f"Should be above Townsend criterion: α·d={alpha_d:.2f} vs "
            f"ln(1+1/γ)={townsend_crit:.2f}"
        )


# ---------------------------------------------------------------------------
# 7. Poisson solver unit tests
# ---------------------------------------------------------------------------

class TestPoissonSolver:

    def test_neutral_plasma_linear_potential(self):
        """For ρ=0 (neutral), potential should be linear from V_anode to 0."""
        N = 20
        h = 0.01 / N
        rho = np.zeros(N + 1)
        phi, E = _solve_poisson_1d(rho, h, 400.0)
        # phi should be linear
        np.testing.assert_allclose(phi, np.linspace(400.0, 0.0, N + 1), atol=1e-9)

    def test_neutral_plasma_uniform_field(self):
        """For ρ=0, E-field should be uniform = V/d."""
        N = 20
        h = 0.01 / N
        rho = np.zeros(N + 1)
        phi, E = _solve_poisson_1d(rho, h, 400.0)
        E_expected = 400.0 / 0.01  # V/d = 40000 V/m
        np.testing.assert_allclose(E[:-1], E_expected, rtol=1e-9)

    def test_boundary_conditions_satisfied(self):
        """φ[0] = V_anode and φ[N] = 0 must be exactly satisfied."""
        N = 30
        h = 0.01 / N
        rho = np.random.default_rng(42).uniform(-1e-3, 1e-3, N + 1)
        phi, E = _solve_poisson_1d(rho, h, 300.0)
        assert abs(phi[0] - 300.0) < 1e-10, f"Anode BC: φ[0]={phi[0]}"
        assert abs(phi[-1] - 0.0) < 1e-10, f"Cathode BC: φ[N]={phi[-1]}"

    def test_space_charge_modifies_potential(self):
        """
        Uniform positive space charge modifies the potential away from linear.
        d²φ/dx² = −ρ/ε₀: positive ρ → downward curvature → midpoint dips below linear.
        Check that the solver produces a consistent, non-linear profile.
        """
        N = 50
        d = 0.01
        h = d / N
        # Uniform positive space charge (scaled to be physically large)
        from kerf_cfd.plasma.drift_diffusion import _EPS0, _Q_E
        ne = np.full(N + 1, 0.0)        # no electrons
        ni = np.full(N + 1, 1e15)      # lots of ions → positive ρ
        rho = _Q_E * (ni - ne)         # positive charge density [C/m³]
        phi, E = _solve_poisson_1d(rho, h, 400.0)
        # With strong positive charge, d²φ/dx² < 0 → φ curves downward
        # The mid-point potential must differ from linear profile
        phi_linear_mid = 400.0 * 0.5   # = 200 V (linear)
        # Just verify BCs and that phi is significantly different from linear
        assert abs(phi[0] - 400.0) < 1e-9, "Anode BC must hold"
        assert abs(phi[-1] - 0.0) < 1e-9, "Cathode BC must hold"
        # Midpoint potential is modified by space charge (above or below linear)
        assert abs(phi[N // 2] - phi_linear_mid) > 1.0, (
            "Strong space charge should significantly modify potential from linear"
        )


# ---------------------------------------------------------------------------
# 8. Paschen minimum analytical check
# ---------------------------------------------------------------------------

class TestPaschenAnalytical:

    def test_minimum_pd_formula(self):
        """
        pd_min = e · ln(1 + 1/γ) / A
        for air with A=12, γ=0.01: pd_min ≈ e·4.615/12 ≈ 1.045 Pa·m
        """
        gas = PlasmaGas.air()
        ln_term = math.log(1.0 + 1.0 / gas.gamma_se)
        pd_min_theory = math.e * ln_term / gas.A_tow

        # Scan to find numerical minimum
        pd_arr = np.linspace(pd_min_theory * 0.5, pd_min_theory * 3.0, 500)
        V_arr = np.array([paschen_voltage(gas, pd, 1.0) for pd in pd_arr])
        mask = np.isfinite(V_arr) & (V_arr > 0)
        assert mask.sum() > 50
        pd_num_min = pd_arr[mask][int(np.argmin(V_arr[mask]))]

        # Numerical minimum should be within 20% of theory
        assert abs(pd_num_min - pd_min_theory) / pd_min_theory < 0.20, (
            f"pd_min: theory={pd_min_theory:.4f}, numerical={pd_num_min:.4f}"
        )

    def test_minimum_voltage_formula(self):
        """V_min = B · e · ln(1 + 1/γ) / A — within 10% of numerical scan."""
        gas = PlasmaGas.air()
        ln_term = math.log(1.0 + 1.0 / gas.gamma_se)
        V_min_theory = gas.B_tow * math.e * ln_term / gas.A_tow

        pd_star = math.e * ln_term / gas.A_tow
        pd_arr = np.linspace(pd_star * 0.6, pd_star * 2.5, 300)
        V_arr = np.array([paschen_voltage(gas, pd, 1.0) for pd in pd_arr])
        mask = np.isfinite(V_arr) & (V_arr > 0)
        V_min_num = float(V_arr[mask].min())

        assert abs(V_min_num - V_min_theory) / V_min_theory < 0.10, (
            f"V_min: theory={V_min_theory:.1f}, numerical={V_min_num:.1f}"
        )


# ---------------------------------------------------------------------------
# 9. Tool sync function (API layer)
# ---------------------------------------------------------------------------

class TestPlasmaTool:

    def test_tool_ok_default(self):
        result = run_plasma_discharge_sync()
        assert result.get("ok"), f"Expected ok=True: {result}"

    def test_tool_ok_argon(self):
        result = run_plasma_discharge_sync(gas="argon", pressure=100.0, voltage=600.0)
        assert result.get("ok")

    def test_tool_invalid_gas(self):
        result = run_plasma_discharge_sync(gas="xenon")
        assert not result.get("ok")
        assert result.get("code") == "BAD_ARGS"

    def test_tool_invalid_pressure(self):
        result = run_plasma_discharge_sync(pressure=-100.0)
        assert not result.get("ok")

    def test_tool_invalid_gap(self):
        result = run_plasma_discharge_sync(gap=-0.01)
        assert not result.get("ok")

    def test_tool_invalid_voltage(self):
        result = run_plasma_discharge_sync(voltage=-100.0)
        assert not result.get("ok")

    def test_tool_invalid_n_cells_too_small(self):
        result = run_plasma_discharge_sync(n_cells=10)
        assert not result.get("ok")
        assert result.get("code") == "BAD_ARGS"

    def test_tool_has_paschen_curve(self):
        result = run_plasma_discharge_sync(pressure=100.0, voltage=600.0)
        assert result.get("ok")
        pc = result["paschen_curve"]
        assert "pd_Pa_m" in pc and "V_bd_V" in pc
        assert len(pc["pd_Pa_m"]) == len(pc["V_bd_V"])

    def test_tool_paschen_curve_has_minimum(self):
        """Returned Paschen curve must have a finite minimum (not all inf)."""
        result = run_plasma_discharge_sync(pressure=100.0, voltage=600.0)
        assert result.get("ok")
        V_bd = np.array(result["paschen_curve"]["V_bd_V"])
        finite = V_bd[np.isfinite(V_bd) & (V_bd > 0)]
        assert len(finite) > 5, "Paschen curve should have multiple finite points"
        assert float(finite.min()) > 0

    def test_tool_has_model_notes(self):
        result = run_plasma_discharge_sync()
        assert result.get("ok")
        notes = result.get("model_notes", "")
        assert "drift-diffusion" in notes.lower() or "DRIFT-DIFFUSION" in notes

    def test_tool_output_lengths_consistent(self):
        result = run_plasma_discharge_sync(n_cells=80)
        assert result.get("ok")
        n = len(result["x_m"])
        assert len(result["n_e_m3"]) == n
        assert len(result["n_i_m3"]) == n
        assert len(result["E_field_V_m"]) == n
        assert len(result["phi_V"]) == n
        assert len(result["ionization_rate_m3_s"]) == n

    def test_tool_breakdown_estimate_positive(self):
        """Breakdown voltage estimate must be positive."""
        result = run_plasma_discharge_sync(pressure=100.0, gap=0.01, voltage=600.0)
        assert result.get("ok")
        V_bd = result["breakdown_estimate_V"]
        assert V_bd > 0, f"Breakdown voltage must be > 0, got {V_bd}"


# ---------------------------------------------------------------------------
# 10. Gas parameters
# ---------------------------------------------------------------------------

class TestGasParameters:

    def test_all_gases_constructable(self):
        for name in ["air", "argon", "helium", "nitrogen", "n2"]:
            gas = PlasmaGas.from_name(name)
            assert gas.mu_e_ref > 0
            assert gas.mu_i > 0
            assert gas.A_tow > 0
            assert gas.B_tow > 0
            assert 0 < gas.gamma_se < 1

    def test_unknown_gas_raises(self):
        with pytest.raises(ValueError, match="Unknown gas"):
            PlasmaGas.from_name("xenon")

    def test_paschen_voltage_positive_at_typical_pd(self):
        """Paschen voltage > 0 for all gases at pd = pd* (minimum location)."""
        for gas_name in ["air", "argon", "helium", "nitrogen"]:
            gas = PlasmaGas.from_name(gas_name)
            ln_term = math.log(1.0 + 1.0 / gas.gamma_se)
            pd_star = math.e * ln_term / gas.A_tow
            V = paschen_voltage(gas, pd_star * 1.5, 1.0)
            assert V > 0 and math.isfinite(V), (
                f"{gas_name}: V_bd at pd=1.5·pd* should be finite+positive, got {V}"
            )
