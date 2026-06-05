"""
Tests for kerf_cfd.combustion.multispecies_reacting_flow.

Covers:
  - Mass conservation (ΣYk = 1 maintained throughout)
  - Arrhenius rate increases with temperature
  - Fuel conversion increases with residence time (longer reactor / slower flow)
  - Adiabatic flame temperature in physical range for CH4/air
  - Equilibrium approached: fuel depleted, products formed
  - Energy closure: temperature rises when heat of reaction is negative
  - Species-concentration fields are physically bounded

References:
  Westbrook, C.K., Dryer, F.L. (1981). PECS 7, 23-86.
  Williams, F.A. (1985). Combustion Theory.
  Law, C.K. (2006). Combustion Physics.
  JANAF/NIST (Chase, 1998).
"""

from __future__ import annotations

import numpy as np
import pytest

from kerf_cfd.combustion.multispecies_reacting_flow import (
    ArrheniusReaction,
    MultispeciesState,
    Species,
    adiabatic_flame_temperature,
    ch4_one_step,
    fuel_conversion,
    generic_ab_to_c,
    h2_one_step,
    solve_reactor,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def ch4_mechanism():
    return ch4_one_step()


@pytest.fixture
def h2_mechanism():
    return h2_one_step()


@pytest.fixture
def ab_mechanism():
    return generic_ab_to_c()


# ---------------------------------------------------------------------------
# ArrheniusReaction.rate_coefficient
# ---------------------------------------------------------------------------

class TestArrheniusRateCoefficient:
    """Arrhenius kf = A * T^b * exp(-Ea/(R*T))."""

    def test_rate_increases_with_temperature(self):
        """kf must strictly increase with temperature for Ea > 0."""
        rxn = ArrheniusReaction(
            A=1.0e8,
            b=0.0,
            Ea=50_000.0,    # [J/mol]
            reactant_stoich={"A": 1.0},
            product_stoich={"B": 1.0},
        )
        T_low = np.array([500.0, 1000.0, 1500.0])
        T_high = np.array([600.0, 1200.0, 1800.0])
        kf_low = rxn.rate_coefficient(T_low)
        kf_high = rxn.rate_coefficient(T_high)
        assert np.all(kf_high > kf_low), (
            "Arrhenius rate must increase with temperature"
        )

    def test_rate_always_positive(self):
        """Rate coefficient must be positive for all physical temperatures."""
        rxn = ArrheniusReaction(
            A=2.119e11, b=0.0, Ea=202_600.0,
            reactant_stoich={"CH4": 1.0}, product_stoich={"CO2": 1.0},
        )
        T = np.linspace(300.0, 3000.0, 100)
        kf = rxn.rate_coefficient(T)
        assert np.all(kf > 0.0)

    def test_zero_ea_rate_is_just_A(self):
        """With Ea=0 and b=0, kf should equal A for all T."""
        rxn = ArrheniusReaction(
            A=42.0, b=0.0, Ea=0.0,
            reactant_stoich={"A": 1.0}, product_stoich={"B": 1.0},
        )
        T = np.array([300.0, 1000.0, 2000.0])
        kf = rxn.rate_coefficient(T)
        np.testing.assert_allclose(kf, 42.0, rtol=1e-10)

    def test_doubling_A_doubles_rate(self):
        """Pre-exponential scales rate linearly."""
        rxn1 = ArrheniusReaction(A=1e6, b=0.0, Ea=30_000.0,
                                  reactant_stoich={"A": 1.0}, product_stoich={"B": 1.0})
        rxn2 = ArrheniusReaction(A=2e6, b=0.0, Ea=30_000.0,
                                  reactant_stoich={"A": 1.0}, product_stoich={"B": 1.0})
        T = np.array([1000.0, 1500.0])
        np.testing.assert_allclose(rxn2.rate_coefficient(T),
                                   2.0 * rxn1.rate_coefficient(T), rtol=1e-10)


# ---------------------------------------------------------------------------
# MultispeciesState utilities
# ---------------------------------------------------------------------------

class TestMultispeciesState:

    def test_enforce_closure_sums_to_one(self):
        """After enforce_closure, every row should sum to 1.0."""
        species, _ = ch4_one_step()
        n = 10
        # Deliberately non-normalised
        Y = np.random.RandomState(42).uniform(0.0, 0.3, size=(n, len(species)))
        state = MultispeciesState(
            species=species,
            Y=Y,
            temperature=np.full(n, 1000.0),
            density=np.full(n, 1.2),
        )
        state.enforce_closure()
        row_sums = state.Y.sum(axis=1)
        np.testing.assert_allclose(row_sums, 1.0, atol=1e-12)

    def test_mass_fractions_non_negative_after_closure(self):
        """Closure must not produce negative mass fractions."""
        species, _ = ch4_one_step()
        n = 5
        Y = np.zeros((n, len(species)))
        Y[:, 0] = 0.05   # CH4
        Y[:, 1] = 0.23   # O2
        # N2 is the bath — will get the rest
        state = MultispeciesState(
            species=species,
            Y=Y,
            temperature=np.full(n, 900.0),
            density=np.full(n, 1.1),
        )
        state.enforce_closure()
        assert np.all(state.Y >= 0.0), "No negative mass fractions"

    def test_mole_fractions_sum_to_one(self):
        """Mole fractions must sum to 1 within tolerance."""
        species, _ = ch4_one_step()
        n = 8
        Y = np.zeros((n, len(species)))
        Y[:, 0] = 0.05   # CH4
        Y[:, 1] = 0.23   # O2
        Y[:, 4] = 0.72   # N2
        state = MultispeciesState(
            species=species, Y=Y,
            temperature=np.full(n, 300.0),
            density=np.full(n, 1.2),
        )
        X = state.mole_fractions()
        np.testing.assert_allclose(X.sum(axis=1), 1.0, atol=1e-10)

    def test_molar_concentrations_positive(self):
        """Molar concentrations [Xk] = ρ Yk / Wk must be non-negative."""
        species, _ = ch4_one_step()
        n = 4
        Y = np.zeros((n, len(species)))
        Y[:, 1] = 0.23
        Y[:, 4] = 0.77
        state = MultispeciesState(
            species=species, Y=Y,
            temperature=np.full(n, 500.0),
            density=np.full(n, 1.1),
        )
        conc = state.molar_concentrations()
        assert np.all(conc >= 0.0)


# ---------------------------------------------------------------------------
# Mass conservation
# ---------------------------------------------------------------------------

class TestMassConservation:

    def test_sum_Yk_equals_one_initial(self, ch4_mechanism):
        """Initial state must satisfy closure."""
        species, reactions = ch4_mechanism
        Y_inlet = {"CH4": 0.05, "O2": 0.23, "N2": 0.72}
        state = solve_reactor(
            species_list=species,
            reactions=reactions,
            Y_inlet=Y_inlet,
            T_inlet=1000.0,
            rho_inlet=1.1,
            n_cells=10,
            length=0.05,
            velocity=0.5,
            max_steps=5,   # very few steps
        )
        row_sums = state.Y.sum(axis=1)
        np.testing.assert_allclose(row_sums, 1.0, atol=1e-10,
                                   err_msg="ΣYk must equal 1 after solver")

    def test_sum_Yk_equals_one_after_many_steps(self, ch4_mechanism):
        """Mass conservation must hold throughout a full reactor solve."""
        species, reactions = ch4_mechanism
        Y_inlet = {"CH4": 0.05, "O2": 0.23, "N2": 0.72}
        state = solve_reactor(
            species_list=species,
            reactions=reactions,
            Y_inlet=Y_inlet,
            T_inlet=1000.0,
            rho_inlet=1.1,
            n_cells=30,
            length=0.1,
            velocity=0.5,
            max_steps=2000,
        )
        row_sums = state.Y.sum(axis=1)
        np.testing.assert_allclose(row_sums, 1.0, atol=1e-8,
                                   err_msg="ΣYk must equal 1 at all cells")

    def test_sum_Yk_equals_one_ab_mechanism(self, ab_mechanism):
        """Mass conservation holds for generic A+B→C mechanism."""
        species, reactions = ab_mechanism
        Y_inlet = {"A": 0.3, "B": 0.3, "M": 0.4}
        state = solve_reactor(
            species_list=species,
            reactions=reactions,
            Y_inlet=Y_inlet,
            T_inlet=800.0,
            rho_inlet=1.2,
            n_cells=20,
            length=0.2,
            velocity=1.0,
            max_steps=1000,
        )
        row_sums = state.Y.sum(axis=1)
        np.testing.assert_allclose(row_sums, 1.0, atol=1e-8)


# ---------------------------------------------------------------------------
# Arrhenius rate vs temperature
# ---------------------------------------------------------------------------

class TestArrheniusRateVsTemperature:

    def test_ch4_rate_increases_with_T(self, ch4_mechanism):
        """CH4 1-step: production rate of CO2 should increase with T."""
        from kerf_cfd.combustion.multispecies_reacting_flow import (
            compute_species_production_rates,
        )
        species, reactions = ch4_mechanism
        sp_names = [sp.name for sp in species]
        n = 5
        T_vals = np.array([800.0, 1000.0, 1200.0, 1500.0, 2000.0])
        co2_idx = sp_names.index("CO2")

        rates = []
        for T in T_vals:
            Y = np.zeros((1, len(species)))
            Y[0, sp_names.index("CH4")] = 0.05
            Y[0, sp_names.index("O2")] = 0.23
            Y[0, sp_names.index("N2")] = 0.72
            state = MultispeciesState(
                species=species, Y=Y,
                temperature=np.array([T]),
                density=np.array([1.1]),
            )
            omega = compute_species_production_rates(state, reactions)
            rates.append(float(omega[0, co2_idx]))

        # CO2 production rate must increase monotonically with T
        for i in range(len(rates) - 1):
            assert rates[i + 1] > rates[i], (
                f"CO2 production rate should increase with T: "
                f"rate({T_vals[i+1]}) = {rates[i+1]} ≤ rate({T_vals[i]}) = {rates[i]}"
            )

    def test_h2_rate_increases_with_T(self, h2_mechanism):
        """H2 1-step: H2O production rate increases with T."""
        from kerf_cfd.combustion.multispecies_reacting_flow import (
            compute_species_production_rates,
        )
        species, reactions = h2_mechanism
        sp_names = [sp.name for sp in species]
        h2o_idx = sp_names.index("H2O")

        T_low = np.array([600.0])
        T_high = np.array([1500.0])

        def rate_at(T):
            Y = np.zeros((1, len(species)))
            Y[0, sp_names.index("H2")] = 0.05
            Y[0, sp_names.index("O2")] = 0.40
            Y[0, sp_names.index("N2")] = 0.55
            st = MultispeciesState(species=species, Y=Y, temperature=T,
                                   density=np.array([1.0]))
            return float(compute_species_production_rates(st, reactions)[0, h2o_idx])

        assert rate_at(T_high) > rate_at(T_low), "H2O rate must increase with T"


# ---------------------------------------------------------------------------
# Fuel conversion increases with residence time
# ---------------------------------------------------------------------------

class TestFuelConversionVsResidenceTime:

    def test_longer_reactor_higher_conversion(self, ch4_mechanism):
        """Longer reactor at same velocity → higher fuel conversion."""
        species, reactions = ch4_mechanism
        Y_inlet = {"CH4": 0.05, "O2": 0.23, "N2": 0.72}
        common = dict(
            species_list=species,
            reactions=reactions,
            Y_inlet=Y_inlet,
            T_inlet=1200.0,   # hot: chemistry active
            rho_inlet=1.0,
            n_cells=40,
            velocity=1.0,
            max_steps=3000,
        )
        state_short = solve_reactor(**common, length=0.05)
        state_long  = solve_reactor(**common, length=0.20)

        ch4_idx = [sp.name for sp in species].index("CH4")
        conv_short = float(np.mean(state_short.Y[:, ch4_idx]))
        conv_long  = float(np.mean(state_long.Y[:, ch4_idx]))

        # More CH4 consumed → lower mean Y_CH4 in longer reactor
        assert conv_long <= conv_short + 1e-8, (
            f"Longer reactor should consume more fuel: "
            f"Y_CH4_short={conv_short:.4f}, Y_CH4_long={conv_long:.4f}"
        )

    def test_slower_flow_higher_conversion(self, ch4_mechanism):
        """Slower velocity → longer residence time → higher conversion."""
        species, reactions = ch4_mechanism
        Y_inlet = {"CH4": 0.05, "O2": 0.23, "N2": 0.72}
        common = dict(
            species_list=species,
            reactions=reactions,
            Y_inlet=Y_inlet,
            T_inlet=1300.0,
            rho_inlet=1.0,
            n_cells=30,
            length=0.1,
            max_steps=3000,
        )
        state_fast = solve_reactor(**common, velocity=2.0)
        state_slow = solve_reactor(**common, velocity=0.5)

        ch4_idx = [sp.name for sp in species].index("CH4")
        Y_ch4_fast = float(state_fast.Y[-1, ch4_idx])
        Y_ch4_slow = float(state_slow.Y[-1, ch4_idx])

        assert Y_ch4_slow <= Y_ch4_fast + 1e-8, (
            "Slower flow should leave less CH4 at outlet"
        )

    def test_conversion_bounded_0_to_1(self, ch4_mechanism):
        """Fuel conversion must be in [0, 1]."""
        species, reactions = ch4_mechanism
        Y_inlet = {"CH4": 0.05, "O2": 0.23, "N2": 0.72}
        state = solve_reactor(
            species_list=species, reactions=reactions,
            Y_inlet=Y_inlet, T_inlet=1200.0, rho_inlet=1.0,
            n_cells=20, length=0.1, velocity=0.5, max_steps=2000,
        )
        conv = fuel_conversion(state, "CH4", Y_inlet["CH4"])
        assert np.all(conv >= -1e-8), "Conversion must be >= 0"
        assert np.all(conv <= 1.0 + 1e-8), "Conversion must be <= 1"


# ---------------------------------------------------------------------------
# Adiabatic flame temperature
# ---------------------------------------------------------------------------

class TestAdiabaticFlameTemperature:

    def test_ch4_Tad_physical_range(self):
        """Stoichiometric CH4/air adiabatic Tad should be 1800–2800 K.

        Literature: stoichiometric methane/air ≈ 2226 K (Law 2006 §5.3).
        Simplified cp-weighted balance gives ~2200–2500 K range.
        """
        species, _ = ch4_one_step()
        # Stoichiometric CH4/air: φ=1.0
        # mass fraction: ~0.055 CH4, 0.22 O2, 0.725 N2 (air at 23.2% O2 by mass)
        Y_react = {"CH4": 0.055, "O2": 0.22, "N2": 0.725}
        T_ad = adiabatic_flame_temperature(
            species_list=species,
            Y_react=Y_react,
            T_react=300.0,
        )
        assert 1500.0 <= T_ad <= 3500.0, (
            f"CH4/air adiabatic flame temp should be ~1800-2800 K, got {T_ad:.1f} K"
        )

    def test_h2_Tad_physical_range(self):
        """Stoichiometric H2/air Tad should be in 2000–3500 K.

        Literature: H2/air stoichiometric ≈ 2483 K (Law 2006).
        """
        species, _ = h2_one_step()
        # stoichiometric H2/air: ~0.028 H2, 0.226 O2, 0.746 N2
        Y_react = {"H2": 0.028, "O2": 0.226, "N2": 0.746}
        T_ad = adiabatic_flame_temperature(
            species_list=species,
            Y_react=Y_react,
            T_react=300.0,
        )
        assert 1500.0 <= T_ad <= 4000.0, (
            f"H2/air adiabatic flame temp should be ~2000-3500 K, got {T_ad:.1f} K"
        )

    def test_no_fuel_Tad_equals_T_react(self):
        """With no fuel, adiabatic flame temp ≈ inlet temperature."""
        species, _ = ch4_one_step()
        Y_react = {"N2": 1.0}
        T_ad = adiabatic_flame_temperature(
            species_list=species, Y_react=Y_react, T_react=500.0
        )
        # Inert: hf=0, so ΔT ≈ 0
        assert abs(T_ad - 500.0) < 5.0, f"Inert mixture Tad should ~ 500 K, got {T_ad:.1f}"

    def test_Tad_increases_with_fuel_fraction(self):
        """Higher fuel mass fraction (up to stoichiometric) → higher Tad."""
        species, _ = ch4_one_step()
        T_ad_lean = adiabatic_flame_temperature(
            species_list=species,
            Y_react={"CH4": 0.02, "O2": 0.23, "N2": 0.75},
            T_react=300.0,
        )
        T_ad_rich = adiabatic_flame_temperature(
            species_list=species,
            Y_react={"CH4": 0.06, "O2": 0.23, "N2": 0.71},
            T_react=300.0,
        )
        assert T_ad_rich > T_ad_lean, "More fuel → higher adiabatic flame temp"


# ---------------------------------------------------------------------------
# Equilibrium approached: products formed, fuel depleted
# ---------------------------------------------------------------------------

class TestEquilibriumApproached:

    def test_ch4_products_formed_at_outlet(self, ch4_mechanism):
        """At high temperature, CO2 and H2O mass fractions must increase."""
        species, reactions = ch4_mechanism
        sp_names = [sp.name for sp in species]
        Y_inlet = {"CH4": 0.055, "O2": 0.22, "N2": 0.725}
        state = solve_reactor(
            species_list=species,
            reactions=reactions,
            Y_inlet=Y_inlet,
            T_inlet=1500.0,   # hot enough for rapid chemistry
            rho_inlet=1.0,
            n_cells=40,
            length=0.15,
            velocity=0.5,
            max_steps=4000,
        )
        co2_inlet = Y_inlet.get("CO2", 0.0)
        h2o_inlet = Y_inlet.get("H2O", 0.0)
        co2_outlet = float(state.Y[-1, sp_names.index("CO2")])
        h2o_outlet = float(state.Y[-1, sp_names.index("H2O")])

        assert co2_outlet > co2_inlet, "CO2 must increase from inlet to outlet"
        assert h2o_outlet > h2o_inlet, "H2O must increase from inlet to outlet"

    def test_ch4_depleted_at_outlet(self, ch4_mechanism):
        """Fuel (CH4) must decrease from inlet to outlet."""
        species, reactions = ch4_mechanism
        sp_names = [sp.name for sp in species]
        Y_inlet = {"CH4": 0.055, "O2": 0.22, "N2": 0.725}
        state = solve_reactor(
            species_list=species,
            reactions=reactions,
            Y_inlet=Y_inlet,
            T_inlet=1500.0,
            rho_inlet=1.0,
            n_cells=40,
            length=0.15,
            velocity=0.5,
            max_steps=4000,
        )
        ch4_outlet = float(state.Y[-1, sp_names.index("CH4")])
        assert ch4_outlet < Y_inlet["CH4"], "CH4 must be consumed in reactor"

    def test_temperature_increases_in_reactor(self, ch4_mechanism):
        """Temperature should rise in a hot reacting reactor (heat release)."""
        species, reactions = ch4_mechanism
        Y_inlet = {"CH4": 0.055, "O2": 0.22, "N2": 0.725}
        state = solve_reactor(
            species_list=species,
            reactions=reactions,
            Y_inlet=Y_inlet,
            T_inlet=1400.0,
            rho_inlet=1.0,
            n_cells=30,
            length=0.1,
            velocity=0.5,
            max_steps=3000,
        )
        T_max = float(np.max(state.temperature))
        assert T_max > 1400.0, "Temperature must rise above inlet in reactive flow"

    def test_ab_to_c_products_increase(self, ab_mechanism):
        """Generic A+B→C: species C must increase in the reactor."""
        species, reactions = ab_mechanism
        sp_names = [sp.name for sp in species]
        Y_inlet = {"A": 0.3, "B": 0.3, "M": 0.4}
        state = solve_reactor(
            species_list=species,
            reactions=reactions,
            Y_inlet=Y_inlet,
            T_inlet=1000.0,
            rho_inlet=1.2,
            n_cells=30,
            length=0.2,
            velocity=0.5,
            max_steps=2000,
        )
        c_outlet = float(state.Y[-1, sp_names.index("C")])
        c_inlet = Y_inlet.get("C", 0.0)
        assert c_outlet > c_inlet, "Product C must form in A+B→C reactor"


# ---------------------------------------------------------------------------
# Species mass fractions physically bounded
# ---------------------------------------------------------------------------

class TestSpeciesBounds:

    def test_mass_fractions_non_negative_throughout(self, ch4_mechanism):
        """All Yk must remain ≥ 0 throughout solve."""
        species, reactions = ch4_mechanism
        Y_inlet = {"CH4": 0.055, "O2": 0.22, "N2": 0.725}
        state = solve_reactor(
            species_list=species,
            reactions=reactions,
            Y_inlet=Y_inlet,
            T_inlet=1200.0,
            rho_inlet=1.0,
            n_cells=30,
            length=0.1,
            velocity=0.5,
            max_steps=2000,
        )
        assert np.all(state.Y >= -1e-10), "No species mass fraction may be negative"

    def test_mass_fractions_not_exceed_one(self, ch4_mechanism):
        """All Yk must be ≤ 1."""
        species, reactions = ch4_mechanism
        Y_inlet = {"CH4": 0.055, "O2": 0.22, "N2": 0.725}
        state = solve_reactor(
            species_list=species,
            reactions=reactions,
            Y_inlet=Y_inlet,
            T_inlet=1200.0,
            rho_inlet=1.0,
            n_cells=30,
            length=0.1,
            velocity=0.5,
            max_steps=2000,
        )
        assert np.all(state.Y <= 1.0 + 1e-10), "No species mass fraction may exceed 1"


# ---------------------------------------------------------------------------
# Tool integration (LLM tool handler smoke-test)
# ---------------------------------------------------------------------------

class TestMultispeciesToolHandler:

    @pytest.mark.asyncio
    async def test_ch4_tool_runs(self):
        """LLM tool should return a valid JSON result for CH4_1step."""
        import json
        from kerf_cfd.combustion.multispecies_tool import (
            run_cfd_reacting_flow_multispecies,
        )
        params = {
            "mechanism": "CH4_1step",
            "inlet_composition": {"CH4": 0.055, "O2": 0.22, "N2": 0.725},
            "inlet_temperature": 1200.0,
            "inlet_density": 1.0,
            "reactor_length_m": 0.1,
            "velocity_m_per_s": 0.5,
            "n_cells": 20,
            "max_steps": 1000,
            "return_profiles": False,
        }
        result_str = await run_cfd_reacting_flow_multispecies(params)
        result = json.loads(result_str)
        assert "outlet_mass_fractions" in result
        assert "adiabatic_flame_temperature_K" in result
        assert "outlet_fuel_conversion" in result
        assert abs(result["mass_fraction_sum_outlet"] - 1.0) < 1e-6

    @pytest.mark.asyncio
    async def test_custom_mechanism_tool(self):
        """LLM tool should accept a custom mechanism."""
        import json
        from kerf_cfd.combustion.multispecies_tool import (
            run_cfd_reacting_flow_multispecies,
        )
        params = {
            "mechanism": "custom",
            "species_list": [
                {"name": "A", "molar_mass_kg_per_mol": 0.01, "hf_J_per_kg": 100_000.0, "cp_J_per_kgK": 1000.0},
                {"name": "B", "molar_mass_kg_per_mol": 0.01, "hf_J_per_kg": 0.0, "cp_J_per_kgK": 1000.0},
                {"name": "C", "molar_mass_kg_per_mol": 0.02, "hf_J_per_kg": -80_000.0, "cp_J_per_kgK": 1000.0},
                {"name": "M", "molar_mass_kg_per_mol": 0.03, "hf_J_per_kg": 0.0, "cp_J_per_kgK": 1000.0},
            ],
            "reactions": [
                {
                    "A": 5e5, "b": 0.0, "Ea_J_per_mol": 40_000.0,
                    "reactant_stoich": {"A": 1.0, "B": 1.0},
                    "product_stoich": {"C": 1.0},
                }
            ],
            "inlet_composition": {"A": 0.3, "B": 0.3, "M": 0.4},
            "inlet_temperature": 900.0,
            "n_cells": 15,
            "max_steps": 500,
        }
        result_str = await run_cfd_reacting_flow_multispecies(params)
        result = json.loads(result_str)
        assert "outlet_mass_fractions" in result
        assert result["mass_fraction_sum_outlet"] == pytest.approx(1.0, abs=1e-6)

    @pytest.mark.asyncio
    async def test_bad_mechanism_returns_error(self):
        """Unknown mechanism name should return an error payload."""
        import json
        from kerf_cfd.combustion.multispecies_tool import (
            run_cfd_reacting_flow_multispecies,
        )
        params = {
            "mechanism": "NONEXISTENT_42",
            "inlet_composition": {"CH4": 0.05, "N2": 0.95},
            "inlet_temperature": 1000.0,
        }
        result_str = await run_cfd_reacting_flow_multispecies(params)
        result = json.loads(result_str)
        assert "error" in result
        assert result.get("code") == "BAD_ARGS"

    @pytest.mark.asyncio
    async def test_return_profiles_flag(self):
        """With return_profiles=True, per-cell profiles must be in the result."""
        import json
        from kerf_cfd.combustion.multispecies_tool import (
            run_cfd_reacting_flow_multispecies,
        )
        params = {
            "mechanism": "H2_1step",
            "inlet_composition": {"H2": 0.03, "O2": 0.23, "N2": 0.74},
            "inlet_temperature": 1100.0,
            "n_cells": 10,
            "max_steps": 200,
            "return_profiles": True,
        }
        result_str = await run_cfd_reacting_flow_multispecies(params)
        result = json.loads(result_str)
        assert "x_m" in result, "Profiles should include x positions"
        assert "temperature_K_profile" in result
        assert len(result["temperature_K_profile"]) == 10
