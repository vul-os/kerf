"""
Tests for kerf_cfd.combustion.reacting_flow (Magnussen EBU).

References:
  Magnussen, B.F., Hjertager, B.H. (1976). 16th Symposium on Combustion,
  pp. 719–729.
"""

from __future__ import annotations

import numpy as np
import pytest

from kerf_cfd.combustion.reacting_flow import (
    CombustionMixture,
    FuelSpecies,
    magnussen_ebu_reaction_rate,
    step_combustion,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def ch4():
    return FuelSpecies(
        name="CH4",
        molar_mass_kg_per_mol=0.01604,
        LHV_J_per_kg=50_050_000.0,
        stoichiometric_AFR=17.2,
    )


@pytest.fixture
def base_mix(ch4):
    n = 5
    return CombustionMixture(
        fuel=ch4,
        Y_fuel=np.full(n, 0.1),
        Y_oxidizer=np.full(n, 0.2),
        Y_products=np.full(n, 0.1),
        temperature=np.full(n, 800.0),
        density=np.full(n, 1.1),
    )


# ---------------------------------------------------------------------------
# EBU reaction rate tests
# ---------------------------------------------------------------------------

class TestMagnussenEBU:

    def test_zero_fuel_gives_zero_rate(self, ch4):
        """EBU rate must be 0 when Y_fuel = 0 (no fuel to burn)."""
        n = 4
        mix = CombustionMixture(
            fuel=ch4,
            Y_fuel=np.zeros(n),
            Y_oxidizer=np.full(n, 0.23),
            Y_products=np.full(n, 0.0),
            temperature=np.full(n, 1000.0),
        )
        eps_k = np.full(n, 100.0)
        omega = magnussen_ebu_reaction_rate(mix, eps_k)
        assert np.all(omega == 0.0), "Rate should be zero with no fuel"

    def test_zero_oxidizer_gives_zero_rate(self, ch4):
        """EBU rate must be 0 when Y_oxidizer = 0 (no oxygen)."""
        n = 4
        mix = CombustionMixture(
            fuel=ch4,
            Y_fuel=np.full(n, 0.1),
            Y_oxidizer=np.zeros(n),
            Y_products=np.full(n, 0.2),
            temperature=np.full(n, 1000.0),
        )
        eps_k = np.full(n, 100.0)
        omega = magnussen_ebu_reaction_rate(mix, eps_k)
        assert np.all(omega == 0.0), "Rate should be zero with no oxidizer"

    def test_zero_products_gives_zero_rate(self, ch4):
        """EBU min-3 term is B*Y_pr/(1+s); zero products → zero rate."""
        n = 3
        mix = CombustionMixture(
            fuel=ch4,
            Y_fuel=np.full(n, 0.2),
            Y_oxidizer=np.full(n, 0.5),
            Y_products=np.zeros(n),
            temperature=np.full(n, 1500.0),
        )
        eps_k = np.full(n, 50.0)
        omega = magnussen_ebu_reaction_rate(mix, eps_k)
        assert np.all(omega == 0.0), "Rate should be zero with no products (B*Y_pr=0)"

    def test_rate_nonnegative(self, base_mix):
        """EBU reaction rate must always be >= 0."""
        eps_k = np.array([10.0, 50.0, 0.0, 100.0, 200.0])
        omega = magnussen_ebu_reaction_rate(base_mix, eps_k)
        assert np.all(omega >= 0.0)

    def test_rate_proportional_to_eps_k(self, ch4):
        """EBU rate should double when ε/k doubles (linear in turbulent time-scale)."""
        n = 3
        mix = CombustionMixture(
            fuel=ch4,
            Y_fuel=np.full(n, 0.1),
            Y_oxidizer=np.full(n, 0.3),
            Y_products=np.full(n, 0.2),
            temperature=np.full(n, 900.0),
        )
        eps_k1 = np.full(n, 50.0)
        eps_k2 = np.full(n, 100.0)
        omega1 = magnussen_ebu_reaction_rate(mix, eps_k1)
        omega2 = magnussen_ebu_reaction_rate(mix, eps_k2)
        np.testing.assert_allclose(omega2, 2.0 * omega1, rtol=1e-10)

    def test_rate_shape(self, base_mix):
        """Output shape must match number of cells."""
        eps_k = np.ones(5) * 20.0
        omega = magnussen_ebu_reaction_rate(base_mix, eps_k)
        assert omega.shape == (5,)

    def test_constant_A_ebu_scales_rate(self, ch4):
        """Doubling A_ebu doubles the rate."""
        n = 2
        mix = CombustionMixture(
            fuel=ch4,
            Y_fuel=np.full(n, 0.1),
            Y_oxidizer=np.full(n, 0.3),
            Y_products=np.full(n, 0.2),
            temperature=np.full(n, 1000.0),
        )
        eps_k = np.full(n, 30.0)
        r1 = magnussen_ebu_reaction_rate(mix, eps_k, A_ebu=4.0)
        r2 = magnussen_ebu_reaction_rate(mix, eps_k, A_ebu=8.0)
        np.testing.assert_allclose(r2, 2.0 * r1, rtol=1e-10)


# ---------------------------------------------------------------------------
# step_combustion tests
# ---------------------------------------------------------------------------

class TestStepCombustion:

    def test_heat_release_raises_temperature(self, ch4, base_mix):
        """Temperature must increase when combustion proceeds."""
        eps_k = np.full(5, 100.0)
        mix_new = step_combustion(base_mix, ch4, eps_k, dt=1e-4)
        assert np.all(mix_new.temperature >= base_mix.temperature), (
            "Temperature should not decrease during combustion"
        )

    def test_heat_release_nonzero_when_reacting(self, ch4, base_mix):
        """When there is fuel + oxidizer + products, temperature must rise."""
        eps_k = np.full(5, 200.0)
        mix_new = step_combustion(base_mix, ch4, eps_k, dt=1e-3)
        delta_T = mix_new.temperature - base_mix.temperature
        assert np.any(delta_T > 0.0), "Heat release should raise temperature"

    def test_fuel_decreases(self, ch4, base_mix):
        """Fuel mass fraction must decrease or stay constant after reaction."""
        eps_k = np.full(5, 100.0)
        mix_new = step_combustion(base_mix, ch4, eps_k, dt=1e-4)
        assert np.all(mix_new.Y_fuel <= base_mix.Y_fuel + 1e-12)

    def test_products_increase(self, ch4, base_mix):
        """Product mass fraction must increase or stay constant."""
        eps_k = np.full(5, 100.0)
        mix_new = step_combustion(base_mix, ch4, eps_k, dt=1e-4)
        assert np.all(mix_new.Y_products >= base_mix.Y_products - 1e-12)

    def test_no_reaction_no_temperature_change(self, ch4):
        """With Y_fuel=0 there should be no temperature change."""
        n = 3
        mix = CombustionMixture(
            fuel=ch4,
            Y_fuel=np.zeros(n),
            Y_oxidizer=np.full(n, 0.23),
            Y_products=np.zeros(n),
            temperature=np.full(n, 500.0),
        )
        eps_k = np.full(n, 1000.0)
        mix_new = step_combustion(mix, ch4, eps_k, dt=0.01)
        np.testing.assert_allclose(mix_new.temperature, mix.temperature, rtol=1e-12)

    def test_mass_fractions_bounded(self, ch4, base_mix):
        """All mass fractions must remain in [0, 1] after large dt."""
        eps_k = np.full(5, 1000.0)
        mix_new = step_combustion(base_mix, ch4, eps_k, dt=1.0)
        assert np.all(mix_new.Y_fuel >= -1e-12)
        assert np.all(mix_new.Y_oxidizer >= -1e-12)
        assert np.all(mix_new.Y_products >= -1e-12)
        assert np.all(mix_new.Y_fuel <= 1.0 + 1e-12)

    def test_output_is_new_object(self, ch4, base_mix):
        """step_combustion must not mutate the input mixture."""
        Y_fuel_before = base_mix.Y_fuel.copy()
        T_before = base_mix.temperature.copy()
        eps_k = np.full(5, 100.0)
        _ = step_combustion(base_mix, ch4, eps_k, dt=1e-3)
        np.testing.assert_array_equal(base_mix.Y_fuel, Y_fuel_before)
        np.testing.assert_array_equal(base_mix.temperature, T_before)
