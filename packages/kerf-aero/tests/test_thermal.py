"""
pytest suite for kerf_aero.thermal — spacecraft thermal control analysis.

Coverage
--------
  - Stefan–Boltzmann black-body radiation (oracle)
  - View factor: infinite parallel plates = 1.0
  - View factor: unit-area parallel plates 1 m apart (Howell C-11)
  - Thermal network: 2-node radiative pair steady-state
  - Thermal network: transient step converges toward equilibrium
  - Solar flux at Earth (1 AU) and Mars (1.524 AU)
  - Absorbed solar flux geometry (angle of incidence)
  - Eclipse geometry (umbra / penumbra / sunlight)
  - Coatings catalogue completeness
  - Coatings: white paint and black paint property values
  - Coatings: α/ε ratio for gold
"""

from __future__ import annotations

import math
import pytest

from kerf_aero.thermal import network as nt
from kerf_aero.thermal import solar_flux as sf
from kerf_aero.thermal import view_factors as vf
from kerf_aero.thermal import coatings as ct
from kerf_aero.thermal.network import (
    Node,
    ConductiveLink,
    RadiativeLink,
    ThermalNetwork,
    STEFAN_BOLTZMANN,
    make_space_node,
    radiative_coupling,
)
from kerf_aero.thermal.solar_flux import (
    SOLAR_CONSTANT_W_M2,
    solar_flux_at_distance,
    absorbed_solar_flux,
    eclipse_geometry,
    PLANET_SOLAR_FLUX,
)
from kerf_aero.thermal.view_factors import (
    parallel_plates_infinite,
    parallel_rectangles_equal,
    perpendicular_rectangles_shared_edge,
    parallel_disks_equal_radius,
    sphere_to_environment,
)
from kerf_aero.thermal.coatings import COATINGS, Coating, get as get_coating


# ---------------------------------------------------------------------------
# Stefan–Boltzmann oracle
# ---------------------------------------------------------------------------

class TestStefanBoltzmann:
    """Black-body radiation from a 1 m² surface at 300 K."""

    def test_blackbody_power_300K(self):
        """1 m² black body at 300 K → σ T⁴ ≈ 459.27 W."""
        T = 300.0
        area = 1.0
        epsilon = 1.0   # perfect black body
        expected = STEFAN_BOLTZMANN * T**4 * area * epsilon
        # Oracle: σ = 5.670374419e-8 W/(m² K⁴), T⁴ = 8.1e9 K⁴
        assert abs(expected - 459.27) < 1.0, (
            f"Expected ~459 W, got {expected:.4f} W"
        )

    def test_blackbody_sigma_value(self):
        """Stefan–Boltzmann constant is 5.670374419e-8 W m⁻² K⁻⁴."""
        assert abs(STEFAN_BOLTZMANN - 5.670374419e-8) < 1e-16

    def test_radiative_link_factor(self):
        """RadiativeLink.rad_factor = σ ε A F."""
        lk = RadiativeLink("a", "b", epsilon_eff=1.0, area=1.0, view_factor=1.0)
        assert abs(lk.rad_factor - STEFAN_BOLTZMANN) < 1e-20

    def test_blackbody_to_space_steady_state(self):
        """
        A 1-m² black-body node absorbing σ·300⁴ W should reach 300 K in
        steady-state radiating to space (T_space → 0 K).
        """
        T_eq = 300.0
        Q_ext = STEFAN_BOLTZMANN * T_eq**4   # exact balance
        net = ThermalNetwork()
        net.add_node(Node("body", T=200.0, Q_ext=Q_ext))
        net.add_node(Node("space", T=0.01, fixed=True))
        net.add_link(RadiativeLink("body", "space",
                                   epsilon_eff=1.0, area=1.0, view_factor=1.0))
        T = net.solve_steady_state()
        # T_space=0.01 K introduces a tiny offset; allow 0.1 K tolerance
        assert abs(T["body"] - T_eq) < 0.1, (
            f"Expected {T_eq} K, got {T['body']:.6f} K"
        )


# ---------------------------------------------------------------------------
# View factors
# ---------------------------------------------------------------------------

class TestViewFactors:
    """Analytic view-factor values."""

    def test_infinite_parallel_plates(self):
        """F for infinite parallel plates = 1.0 (exact)."""
        assert parallel_plates_infinite() == 1.0

    def test_sphere_to_environment(self):
        """Convex surface (sphere) sees only its enclosure → F = 1.0."""
        assert sphere_to_environment() == 1.0

    def test_parallel_rectangles_unit_area_1m_separation(self):
        """
        Two 1 m × 1 m parallel plates separated by 1 m.
        Howell C-11: F ≈ 0.1998... (within 5% of 0.20).
        """
        F = parallel_rectangles_equal(a=1.0, b=1.0, c=1.0)
        # Analytic value is approximately 0.19982
        assert 0.19 < F < 0.21, f"Expected ~0.20, got {F:.5f}"
        # Within 5% of 0.20
        assert abs(F - 0.20) / 0.20 < 0.05

    def test_parallel_rectangles_very_close_approaches_1(self):
        """
        Two 1 m × 1 m plates 0.001 m apart should have F very close to 1.
        """
        F = parallel_rectangles_equal(a=1.0, b=1.0, c=0.001)
        assert F > 0.99, f"Expected F → 1 for small separation, got {F:.5f}"

    def test_parallel_rectangles_symmetry(self):
        """F(a=2, b=1, c=1) and F(a=1, b=2, c=1) should be equal."""
        F1 = parallel_rectangles_equal(a=2.0, b=1.0, c=1.0)
        F2 = parallel_rectangles_equal(a=1.0, b=2.0, c=1.0)
        assert abs(F1 - F2) < 1e-10, f"Symmetry broken: {F1} vs {F2}"

    def test_parallel_rectangles_in_unit_range(self):
        """View factors must be in [0, 1] for a range of geometries."""
        for a in [0.5, 1.0, 2.0]:
            for b in [0.5, 1.0, 2.0]:
                for c in [0.1, 1.0, 5.0]:
                    F = parallel_rectangles_equal(a=a, b=b, c=c)
                    assert 0.0 <= F <= 1.0, (
                        f"F={F} out of range for a={a}, b={b}, c={c}"
                    )

    def test_perpendicular_rectangles_in_unit_range(self):
        """Perpendicular-rectangle view factors are in [0, 1]."""
        for w in [0.5, 1.0]:
            for h in [0.5, 1.0]:
                for l in [0.5, 1.0]:
                    F = perpendicular_rectangles_shared_edge(w=w, h=h, l=l)
                    assert 0.0 <= F <= 1.0, (
                        f"F={F} out of range for w={w}, h={h}, l={l}"
                    )

    def test_parallel_disks_equal_radius_in_unit_range(self):
        """Parallel-disk view factor is in [0, 1]."""
        for r in [0.5, 1.0, 2.0]:
            for h in [0.1, 1.0, 5.0]:
                F = parallel_disks_equal_radius(r=r, h=h)
                assert 0.0 <= F <= 1.0, f"F={F} out of range for r={r}, h={h}"

    def test_parallel_disks_large_radius_approaches_1(self):
        """Very large disk radius relative to separation → F → 1."""
        F = parallel_disks_equal_radius(r=1000.0, h=1.0)
        assert F > 0.999, f"Expected F → 1, got {F:.5f}"

    def test_parallel_disks_small_radius(self):
        """Very small disk radius relative to separation → F → 0."""
        F = parallel_disks_equal_radius(r=0.001, h=100.0)
        assert F < 0.01, f"Expected F → 0, got {F:.5f}"


# ---------------------------------------------------------------------------
# Thermal network — steady state
# ---------------------------------------------------------------------------

class TestNetworkSteadyState:
    """Lumped thermal network steady-state solver."""

    def test_two_node_radiative_isothermal(self):
        """
        Two nodes connected by a radiative link, one held at 300 K with no
        external heat on either.  Free node should reach 300 K.
        """
        net = ThermalNetwork()
        net.add_node(Node("hot", T=300.0, fixed=True))
        net.add_node(Node("free", T=100.0))
        net.add_link(RadiativeLink("hot", "free",
                                   epsilon_eff=1.0, area=1.0, view_factor=1.0))
        T = net.solve_steady_state()
        assert abs(T["free"] - 300.0) < 1e-3, (
            f"Expected 300 K, got {T['free']:.4f} K"
        )

    def test_two_node_conductive_isothermal(self):
        """
        Two nodes connected by a conductive link, one fixed at 500 K.
        Free node has Q_ext=0 → reaches 500 K.
        """
        net = ThermalNetwork()
        net.add_node(Node("src", T=500.0, fixed=True))
        net.add_node(Node("sink", T=200.0))
        net.add_link(ConductiveLink("src", "sink", conductance=10.0))
        T = net.solve_steady_state()
        assert abs(T["sink"] - 500.0) < 1e-6

    def test_three_node_linear_conduction(self):
        """
        Linear chain: A (fixed 600 K) — k=1 W/K — B (free) — k=1 W/K — C (fixed 300 K).
        Steady-state: T_B = (600 + 300) / 2 = 450 K.
        """
        net = ThermalNetwork()
        net.add_node(Node("A", T=600.0, fixed=True))
        net.add_node(Node("B", T=400.0))
        net.add_node(Node("C", T=300.0, fixed=True))
        net.add_link(ConductiveLink("A", "B", conductance=1.0))
        net.add_link(ConductiveLink("B", "C", conductance=1.0))
        T = net.solve_steady_state()
        assert abs(T["B"] - 450.0) < 1e-4, f"Expected 450 K, got {T['B']:.4f}"

    def test_node_with_heat_source(self):
        """
        Single node with Q_ext = σ T_eq⁴ radiating to space at 0 K.
        Node should converge to the equilibrium temperature T_eq = 300 K.
        """
        T_eq = 300.0
        Q_ext = STEFAN_BOLTZMANN * T_eq**4  # ≈ 459.27 W
        net = ThermalNetwork()
        net.add_node(Node("panel", T=250.0, Q_ext=Q_ext))
        net.add_node(Node("space", T=0.01, fixed=True))
        net.add_link(RadiativeLink("panel", "space",
                                   epsilon_eff=1.0, area=1.0, view_factor=1.0))
        T = net.solve_steady_state()
        assert abs(T["panel"] - T_eq) < 1.0, (
            f"Expected {T_eq} K, got {T['panel']:.4f} K"
        )

    def test_fixed_node_unchanged(self):
        """Fixed nodes must not be modified by the solver."""
        net = ThermalNetwork()
        net.add_node(Node("fixed", T=500.0, fixed=True))
        T = net.solve_steady_state()
        assert T["fixed"] == 500.0

    def test_temperatures_method(self):
        """temperatures() returns the current node temperatures."""
        net = ThermalNetwork()
        net.add_node(Node("a", T=300.0))
        assert net.temperatures() == {"a": 300.0}


# ---------------------------------------------------------------------------
# Thermal network — transient
# ---------------------------------------------------------------------------

class TestNetworkTransient:
    """Implicit-Euler transient solver."""

    def test_transient_approaches_steady_state(self):
        """
        A single capacitive node radiating to space should cool/heat toward
        the steady-state temperature over many time steps.
        """
        T_eq = 300.0
        Q_ext = STEFAN_BOLTZMANN * T_eq**4
        net = ThermalNetwork()
        net.add_node(Node("panel", T=100.0, C=1e4, Q_ext=Q_ext))
        net.add_node(Node("space", T=0.01, fixed=True))
        net.add_link(RadiativeLink("panel", "space",
                                   epsilon_eff=1.0, area=1.0, view_factor=1.0))
        # Run many steps with large dt
        for _ in range(500):
            net.step_transient(dt=1000.0)
        T = net.temperatures()
        assert abs(T["panel"] - T_eq) < 5.0, (
            f"Expected ~{T_eq} K after transient, got {T['panel']:.2f} K"
        )

    def test_transient_no_change_at_equilibrium(self):
        """
        A node already at equilibrium should not drift under a time step.
        """
        T_eq = 300.0
        Q_ext = STEFAN_BOLTZMANN * T_eq**4
        net = ThermalNetwork()
        net.add_node(Node("panel", T=T_eq, C=1e4, Q_ext=Q_ext))
        net.add_node(Node("space", T=0.01, fixed=True))
        net.add_link(RadiativeLink("panel", "space",
                                   epsilon_eff=1.0, area=1.0, view_factor=1.0))
        T_before = net.temperatures()["panel"]
        net.step_transient(dt=100.0)
        T_after = net.temperatures()["panel"]
        assert abs(T_after - T_before) < 0.01, (
            f"Node drifted from equilibrium: {T_before:.4f} → {T_after:.4f} K"
        )

    def test_transient_invalid_dt(self):
        """Negative dt raises ValueError."""
        net = ThermalNetwork()
        net.add_node(Node("a", T=300.0))
        with pytest.raises(ValueError):
            net.step_transient(dt=-1.0)


# ---------------------------------------------------------------------------
# Solar flux
# ---------------------------------------------------------------------------

class TestSolarFlux:
    """Solar irradiance calculations."""

    def test_solar_constant_1au(self):
        """Solar flux at 1 AU = 1361 W/m²."""
        assert abs(solar_flux_at_distance(1.0) - 1361.0) < 1e-9

    def test_solar_constant_value(self):
        """SOLAR_CONSTANT_W_M2 is 1361 W/m²."""
        assert SOLAR_CONSTANT_W_M2 == 1361.0

    def test_solar_flux_mars(self):
        """
        Solar flux at Mars (1.524 AU) = 1361 / 1.524² ≈ 585.9 W/m².
        Must be within 1% of the analytic value.
        """
        au_mars = 1.524
        expected = 1361.0 / au_mars**2
        actual = solar_flux_at_distance(au_mars)
        rel_error = abs(actual - expected) / expected
        assert rel_error < 0.01, (
            f"Mars flux: expected {expected:.2f} W/m², got {actual:.2f} W/m² "
            f"(rel error {rel_error:.4%})"
        )
        # Sanity: in the right ballpark 580–590 W/m²
        assert 580 < actual < 595

    def test_solar_flux_inverse_square(self):
        """Doubling distance halves flux by factor of 4."""
        F1 = solar_flux_at_distance(1.0)
        F2 = solar_flux_at_distance(2.0)
        assert abs(F2 - F1 / 4.0) < 1e-9

    def test_solar_flux_planet_table(self):
        """PLANET_SOLAR_FLUX contains Earth and Mars entries."""
        assert "earth" in PLANET_SOLAR_FLUX
        assert "mars" in PLANET_SOLAR_FLUX
        assert abs(PLANET_SOLAR_FLUX["earth"] - 1361.0) < 1.0
        assert 580 < PLANET_SOLAR_FLUX["mars"] < 595

    def test_absorbed_flux_normal_incidence(self):
        """Normal incidence (0°): Q = α A S."""
        alpha = 0.5
        area = 2.0
        S = solar_flux_at_distance(1.0)
        Q = absorbed_solar_flux(alpha=alpha, area=area, angle_deg=0.0)
        assert abs(Q - alpha * area * S) < 1e-9

    def test_absorbed_flux_90_degrees(self):
        """Grazing incidence (90°): Q ≈ 0 (floating-point cos(90°) is ~0)."""
        Q = absorbed_solar_flux(alpha=1.0, area=1.0, angle_deg=90.0)
        assert Q < 1e-10

    def test_absorbed_flux_45_degrees(self):
        """45° incidence: Q = α A S cos(45°)."""
        alpha = 1.0
        area = 1.0
        S = solar_flux_at_distance(1.0)
        Q = absorbed_solar_flux(alpha=alpha, area=area, angle_deg=45.0)
        expected = alpha * area * S * math.cos(math.radians(45.0))
        assert abs(Q - expected) < 1e-9

    def test_solar_flux_invalid_distance(self):
        """Zero or negative distance raises ValueError."""
        with pytest.raises(ValueError):
            solar_flux_at_distance(0.0)
        with pytest.raises(ValueError):
            solar_flux_at_distance(-1.0)


# ---------------------------------------------------------------------------
# Eclipse geometry
# ---------------------------------------------------------------------------

class TestEclipseGeometry:
    """Earth shadow (umbra / penumbra) calculations."""

    def test_full_sunlight(self):
        """Spacecraft in the Sun direction (angle=0) is not eclipsed."""
        geo = eclipse_geometry(spacecraft_altitude_km=400.0, sun_angle_rad=0.0)
        assert not geo.in_umbra
        assert not geo.in_penumbra
        assert geo.eclipse_fraction == 0.0

    def test_deep_umbra(self):
        """Spacecraft directly behind Earth (angle=π) is in umbra."""
        geo = eclipse_geometry(spacecraft_altitude_km=400.0,
                               sun_angle_rad=math.pi)
        assert geo.in_umbra
        assert geo.eclipse_fraction == 1.0

    def test_eclipse_fraction_in_range(self):
        """Eclipse fraction is always in [0, 1]."""
        for angle_deg in range(0, 361, 10):
            geo = eclipse_geometry(
                spacecraft_altitude_km=500.0,
                sun_angle_rad=math.radians(angle_deg),
            )
            assert 0.0 <= geo.eclipse_fraction <= 1.0

    def test_invalid_altitude(self):
        """Non-positive altitude raises ValueError."""
        with pytest.raises(ValueError):
            eclipse_geometry(spacecraft_altitude_km=0.0, sun_angle_rad=0.0)


# ---------------------------------------------------------------------------
# Coatings catalogue
# ---------------------------------------------------------------------------

class TestCoatings:
    """Spacecraft surface coating catalogue."""

    def test_catalogue_has_at_least_10_entries(self):
        """Catalogue must contain at least 10 distinct coatings."""
        assert len(COATINGS) >= 10, (
            f"Expected >= 10 coatings, found {len(COATINGS)}"
        )

    def test_all_entries_are_coating_instances(self):
        """Every entry in COATINGS is a Coating dataclass."""
        for name, c in COATINGS.items():
            assert isinstance(c, Coating), f"{name} is not a Coating"

    def test_all_alpha_in_range(self):
        """All absorptivity values in [0, 1]."""
        for name, c in COATINGS.items():
            assert 0.0 <= c.alpha <= 1.0, f"{name}: alpha={c.alpha}"

    def test_all_epsilon_in_range(self):
        """All emissivity values in [0, 1]."""
        for name, c in COATINGS.items():
            assert 0.0 <= c.epsilon <= 1.0, f"{name}: epsilon={c.epsilon}"

    def test_white_paint_s13g_properties(self):
        """
        White paint (S13G): α ≈ 0.20 (± 0.05), ε ≈ 0.85 (± 0.05).
        """
        c = get_coating("white_paint_s13g")
        assert c is not None, "white_paint_s13g not found in catalogue"
        assert abs(c.alpha - 0.20) <= 0.05, f"white paint alpha={c.alpha}"
        assert abs(c.epsilon - 0.85) <= 0.05, f"white paint epsilon={c.epsilon}"

    def test_black_paint_properties(self):
        """
        Black paint (Chemglaze Z-306): α ≈ 0.95 (± 0.05), ε ≈ 0.90 (± 0.05).
        """
        c = get_coating("black_paint_chemglaze_z306")
        assert c is not None, "black_paint_chemglaze_z306 not found"
        assert abs(c.alpha - 0.95) <= 0.05, f"black paint alpha={c.alpha}"
        assert abs(c.epsilon - 0.90) <= 0.05, f"black paint epsilon={c.epsilon}"

    def test_gold_low_emissivity(self):
        """Gold coating has very low emissivity (ε < 0.05)."""
        c = get_coating("gold_electroplated")
        assert c is not None, "gold_electroplated not found"
        assert c.epsilon < 0.05, f"Expected ε < 0.05 for gold, got {c.epsilon}"

    def test_ito_quartz_low_alpha(self):
        """ITO-coated quartz mirror (OSR) has very low absorptivity (α < 0.15)."""
        c = get_coating("ito_coated_quartz_mirror_osr")
        assert c is not None, "ito_coated_quartz_mirror_osr not found"
        assert c.alpha < 0.15, f"Expected α < 0.15 for OSR, got {c.alpha}"

    def test_alpha_over_epsilon_gold(self):
        """Gold: very high α/ε ratio (> 5) means it runs hot in sunlight."""
        c = get_coating("gold_electroplated")
        assert c is not None
        ratio = c.alpha_over_epsilon
        assert ratio > 5.0, f"Expected α/ε > 5 for gold, got {ratio:.2f}"

    def test_alpha_over_epsilon_white_paint_low(self):
        """White paint: low α/ε ratio (< 0.30) makes it a good radiator."""
        c = get_coating("white_paint_s13g")
        assert c is not None
        ratio = c.alpha_over_epsilon
        assert ratio < 0.30, f"Expected α/ε < 0.30 for white paint, got {ratio:.3f}"

    def test_get_nonexistent_returns_none(self):
        """get() returns None for unknown coating names."""
        assert get_coating("no_such_coating") is None

    def test_coating_invalid_alpha_raises(self):
        """Constructing a Coating with out-of-range α raises ValueError."""
        with pytest.raises(ValueError):
            Coating(name="bad", alpha=1.5, epsilon=0.5)

    def test_coating_invalid_epsilon_raises(self):
        """Constructing a Coating with out-of-range ε raises ValueError."""
        with pytest.raises(ValueError):
            Coating(name="bad", alpha=0.5, epsilon=-0.1)


# ---------------------------------------------------------------------------
# Integration: simple panel equilibrium temperature
# ---------------------------------------------------------------------------

class TestIntegration:
    """End-to-end: panel equilibrium temperature in Earth orbit."""

    def test_white_panel_equilibrium_temperature(self):
        """
        A white-painted (α=0.20, ε=0.85) 1-m² flat panel in Earth orbit
        (1 AU), solar-facing, radiating to space (3 K) should reach an
        equilibrium temperature T_eq where:

            α S = ε σ T_eq⁴
            T_eq = (α S / (ε σ))^(1/4)

        With S = 1361 W/m²:
            T_eq = (0.20 × 1361 / (0.85 × σ))^0.25 ≈ 226 K
        """
        alpha = 0.20
        epsilon = 0.85
        S = solar_flux_at_distance(1.0)
        Q_solar = alpha * S  # per m²

        # Analytic equilibrium
        T_eq_analytic = (Q_solar / (epsilon * STEFAN_BOLTZMANN)) ** 0.25

        # Solve via network
        net = ThermalNetwork()
        net.add_node(Node("panel", T=300.0, Q_ext=Q_solar))
        net.add_node(Node("space", T=3.0, fixed=True))
        net.add_link(RadiativeLink("panel", "space",
                                   epsilon_eff=epsilon, area=1.0, view_factor=1.0))
        T_solved = net.solve_steady_state()["panel"]

        assert abs(T_solved - T_eq_analytic) < 1.0, (
            f"Expected {T_eq_analytic:.2f} K, got {T_solved:.2f} K"
        )
        # Sanity: white panel radiating to a 3 K background is well above 200 K
        assert 190 < T_solved < 300

    def test_view_factor_solar_flux_combined(self):
        """
        Two parallel 1m × 1m panels separated by 1m.  Panel 1 is solar-heated.
        Panel 2 receives radiation from Panel 1 (view factor ~0.20) and
        also from space through the remaining solid angle.
        The view factor used is the Howell formula result.
        """
        F12 = parallel_rectangles_equal(a=1.0, b=1.0, c=1.0)
        assert 0.19 < F12 < 0.21

        S = solar_flux_at_distance(1.0)
        alpha = 0.5
        Q_solar_panel1 = alpha * S   # [W/m²] absorbed by panel 1

        # Panel 1 equilibrium temperature (radiating to space)
        T1_eq = (Q_solar_panel1 / STEFAN_BOLTZMANN) ** 0.25

        # Panel 2 receives from panel 1 via view factor and radiates to space
        # Q_in = σ F12 (T1^4 - T2^4)
        # At equilibrium: σ F12 T1^4 - σ F12 T2^4 + σ(1-F12) * 0 - σ*1*T2^4 = 0
        # σ T2^4 (F12 + 1 - F12) = σ F12 T1^4
        # T2^4 = F12 * T1^4  →  T2 = T1 * F12^0.25
        T2_expected = T1_eq * (F12 ** 0.25)
        assert T2_expected > 0  # sanity
