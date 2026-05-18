"""
Tests for kerf_aero.llm_tools — 12 aerospace LLM tools.

Verifies:
  - Each tool returns a non-error dict on valid sample inputs
  - Invalid inputs raise structured ValueError with a message
"""

from __future__ import annotations

import math
import pytest

from kerf_aero.llm_tools.aerospace_tools import (
    aero_airfoil_coords,
    aero_airfoil_polar,
    aero_vlm_wing,
    aero_orbital_elements_to_state,
    aero_hohmann_transfer,
    aero_lambert_solve,
    aero_rocket_dv,
    aero_cea_lite,
    aero_atmosphere,
    aero_attitude_propagate,
    aero_thermal_steady_state,
    aero_material_lookup,
)


# ---------------------------------------------------------------------------
# Tool 1: aero_airfoil_coords
# ---------------------------------------------------------------------------

class TestAeroAirfoilCoords:

    def test_naca4_basic(self):
        result = aero_airfoil_coords("naca0012")
        assert isinstance(result, dict)
        assert result["name"] == "naca0012"
        assert result["n_points"] > 0
        assert len(result["coords"]) == result["n_points"]
        assert all(len(pt) == 2 for pt in result["coords"])
        assert "NACA" in result["source"]

    def test_naca4_no_prefix(self):
        result = aero_airfoil_coords("2412")
        assert "naca2412" in result["name"]

    def test_naca5(self):
        result = aero_airfoil_coords("naca23012")
        assert "23012" in result["name"]
        assert result["n_points"] > 0

    def test_selig_slug(self):
        result = aero_airfoil_coords("e387")
        assert result["n_points"] > 0
        assert "Selig" in result["source"]

    def test_invalid_name_raises_valueerror(self):
        with pytest.raises(ValueError, match="not recognised"):
            aero_airfoil_coords("notanairfoil_xyz_abc")

    def test_coords_x_range(self):
        result = aero_airfoil_coords("naca0012")
        xs = [pt[0] for pt in result["coords"]]
        assert min(xs) >= -0.01
        assert max(xs) <= 1.01


# ---------------------------------------------------------------------------
# Tool 2: aero_airfoil_polar
# ---------------------------------------------------------------------------

class TestAeroAirfoilPolar:

    def test_symmetric_airfoil_zero_lift_at_zero_alpha(self):
        result = aero_airfoil_polar("naca0012", -4.0, 8.0, 2.0)
        assert "alpha" in result
        assert "CL" in result
        assert len(result["alpha"]) == len(result["CL"])
        # Symmetric airfoil should have CL_alpha > 0
        assert result["CL_alpha"] > 0

    def test_returns_expected_keys(self):
        result = aero_airfoil_polar("naca2412", 0.0, 6.0, 2.0)
        for key in ("name", "alpha", "CL", "CD_wave", "alpha_L0", "CL_alpha"):
            assert key in result

    def test_step_too_small_raises(self):
        with pytest.raises(ValueError, match="step must be"):
            aero_airfoil_polar("naca0012", 0, 5, 0.05)

    def test_invalid_range_raises(self):
        with pytest.raises(ValueError, match="alpha_min"):
            aero_airfoil_polar("naca0012", 10.0, 5.0, 1.0)

    def test_invalid_airfoil_raises(self):
        with pytest.raises(ValueError):
            aero_airfoil_polar("notexistent_xyz", 0, 5, 1.0)

    def test_cl_increases_with_alpha(self):
        result = aero_airfoil_polar("naca0012", 0.0, 10.0, 2.0)
        cls = result["CL"]
        # Should be monotonically increasing for attached flow range
        for i in range(1, len(cls)):
            assert cls[i] > cls[i - 1] - 0.05  # allow tiny tolerance


# ---------------------------------------------------------------------------
# Tool 3: aero_vlm_wing
# ---------------------------------------------------------------------------

class TestAeroVlmWing:

    def test_rectangular_wing(self):
        result = aero_vlm_wing(span=10.0, root_chord=1.0, alpha_deg=5.0)
        assert result.get("ok", True)
        assert "CL" in result
        assert result["CL"] > 0
        assert result["CDi"] >= 0
        assert result["AR"] > 0

    def test_tapered_swept_wing(self):
        result = aero_vlm_wing(span=12.0, root_chord=2.0, tip_chord=1.0,
                               sweep_deg=25.0, alpha_deg=4.0)
        assert result["CL"] > 0

    def test_span_efficiency_physical_range(self):
        result = aero_vlm_wing(span=8.0, root_chord=1.2, alpha_deg=5.0)
        assert 0.0 < result["span_efficiency"] <= 1.2  # Oswald < 1 for realistic wings

    def test_zero_alpha_gives_small_cl(self):
        result = aero_vlm_wing(span=10.0, root_chord=1.0, alpha_deg=0.0)
        assert abs(result["CL"]) < 0.05  # symmetric, unswept → near zero

    def test_invalid_span_raises(self):
        with pytest.raises(ValueError, match="span"):
            aero_vlm_wing(span=-1.0, root_chord=1.0)

    def test_invalid_root_chord_raises(self):
        with pytest.raises(ValueError, match="root_chord"):
            aero_vlm_wing(span=10.0, root_chord=0.0)

    def test_invalid_tip_chord_raises(self):
        with pytest.raises(ValueError, match="tip_chord"):
            aero_vlm_wing(span=10.0, root_chord=1.0, tip_chord=-1.0)


# ---------------------------------------------------------------------------
# Tool 4: aero_orbital_elements_to_state
# ---------------------------------------------------------------------------

class TestAeroOrbitalElementsToState:

    def test_circular_leo(self):
        # ISS-like orbit: a=6778 km, e=0, i=51.6
        result = aero_orbital_elements_to_state(
            a=6778.0, e=0.001, i=51.6, raan=0.0, argp=0.0, true_anomaly=0.0
        )
        assert result.get("ok", True)
        assert "position_km" in result
        assert len(result["position_km"]) == 3
        assert len(result["velocity_km_s"]) == 3
        # Speed should be close to circular velocity ~7.67 km/s for 6778 km
        assert 7.0 < result["speed_km_s"] < 8.5
        # Altitude should be ~400 km
        assert 350 < result["altitude_km"] < 500

    def test_gto_orbit(self):
        result = aero_orbital_elements_to_state(
            a=24400.0, e=0.73, i=5.0, raan=178.0, argp=178.0, true_anomaly=0.0
        )
        assert result["ok"]
        assert result["orbital_period_s"] > 0

    def test_invalid_a_raises(self):
        with pytest.raises(ValueError, match="Semi-major axis"):
            aero_orbital_elements_to_state(-100, 0.0, 0, 0, 0, 0)

    def test_invalid_eccentricity_raises(self):
        with pytest.raises(ValueError, match="[Ee]ccentricity"):
            aero_orbital_elements_to_state(7000, 1.5, 0, 0, 0, 0)

    def test_state_vector_has_expected_magnitude(self):
        result = aero_orbital_elements_to_state(
            a=7000.0, e=0.0, i=0.0, raan=0.0, argp=0.0, true_anomaly=90.0
        )
        # Radius should equal a for circular orbit
        assert abs(result["radius_km"] - 7000.0) < 10.0


# ---------------------------------------------------------------------------
# Tool 5: aero_hohmann_transfer
# ---------------------------------------------------------------------------

class TestAeroHohmannTransfer:

    def test_leo_to_geo(self):
        # LEO 400 km → GEO 35786 km above Earth = r=6778 → r=42164 km
        result = aero_hohmann_transfer(r1=6778.0, r2=42164.0)
        assert result.get("ok", True)
        # Total ΔV for LEO→GEO should be ~3.9 km/s
        assert 3.5 < result["dv_total_km_s"] < 4.5
        assert result["dv1_km_s"] > 0
        assert result["dv2_km_s"] > 0
        assert result["tof_s"] > 0
        assert result["tof_min"] > 0

    def test_same_orbit_gives_zero_dv(self):
        result = aero_hohmann_transfer(r1=7000.0, r2=7000.0)
        assert result["dv_total_km_s"] == 0.0

    def test_descending_transfer(self):
        result = aero_hohmann_transfer(r1=42164.0, r2=6778.0)
        assert result["dv_total_km_s"] > 0
        assert result["r_ratio"] < 1.0

    def test_invalid_r1_raises(self):
        with pytest.raises(ValueError, match="r1"):
            aero_hohmann_transfer(r1=-100.0, r2=7000.0)

    def test_invalid_r2_raises(self):
        with pytest.raises(ValueError, match="r2"):
            aero_hohmann_transfer(r1=7000.0, r2=0.0)


# ---------------------------------------------------------------------------
# Tool 6: aero_lambert_solve
# ---------------------------------------------------------------------------

class TestAeroLambertSolve:

    def test_simple_transfer(self):
        r1 = [7000.0, 0.0, 0.0]
        r2 = [0.0, 7000.0, 0.0]
        result = aero_lambert_solve(r1, r2, tof=3600.0)
        assert result.get("ok", True)
        assert "v1_km_s" in result
        assert "v2_km_s" in result
        assert len(result["v1_km_s"]) == 3
        assert len(result["v2_km_s"]) == 3
        assert result["dv1_km_s"] > 0
        assert result["dv2_km_s"] > 0

    def test_inclined_transfer(self):
        r1 = [6800.0, 0.0, 0.0]
        r2 = [0.0, 0.0, 7200.0]
        result = aero_lambert_solve(r1, r2, tof=7200.0)
        assert result["ok"]

    def test_invalid_r1_length_raises(self):
        with pytest.raises(ValueError, match="r1"):
            aero_lambert_solve([7000.0, 0.0], [0.0, 7000.0, 0.0], tof=3600.0)

    def test_invalid_r2_length_raises(self):
        with pytest.raises(ValueError, match="r2"):
            aero_lambert_solve([7000.0, 0.0, 0.0], [0.0, 7000.0], tof=3600.0)

    def test_zero_tof_raises(self):
        with pytest.raises(ValueError, match="tof"):
            aero_lambert_solve([7000, 0, 0], [0, 7000, 0], tof=0.0)

    def test_negative_tof_raises(self):
        with pytest.raises(ValueError, match="tof"):
            aero_lambert_solve([7000, 0, 0], [0, 7000, 0], tof=-100.0)


# ---------------------------------------------------------------------------
# Tool 7: aero_rocket_dv
# ---------------------------------------------------------------------------

class TestAeroRocketDv:

    def test_standard_case(self):
        result = aero_rocket_dv(mass_ratio=4.0, isp=350.0)
        assert result.get("ok", True)
        # ΔV = 350 * 9.80665 * ln(4) ≈ 4764 m/s
        assert abs(result["delta_v_m_s"] - 4764.0) < 20.0
        assert result["propellant_fraction"] > 0
        assert result["propellant_fraction"] < 1.0

    def test_mass_ratio_one_gives_zero_dv(self):
        result = aero_rocket_dv(mass_ratio=1.0, isp=300.0)
        assert abs(result["delta_v_m_s"]) < 0.01

    def test_high_isp(self):
        result = aero_rocket_dv(mass_ratio=2.0, isp=450.0)
        # ΔV = 450 * 9.80665 * ln(2) ≈ 3055 m/s
        assert abs(result["delta_v_m_s"] - 3055.0) < 20.0

    def test_km_s_consistent_with_m_s(self):
        result = aero_rocket_dv(mass_ratio=3.0, isp=400.0)
        assert abs(result["delta_v_km_s"] * 1000.0 - result["delta_v_m_s"]) < 0.01

    def test_invalid_mass_ratio_raises(self):
        with pytest.raises(ValueError, match="mass_ratio"):
            aero_rocket_dv(mass_ratio=0.0, isp=300.0)

    def test_mass_ratio_below_one_raises(self):
        with pytest.raises(ValueError, match="mass_ratio"):
            aero_rocket_dv(mass_ratio=0.5, isp=300.0)

    def test_invalid_isp_raises(self):
        with pytest.raises(ValueError, match="isp"):
            aero_rocket_dv(mass_ratio=2.0, isp=-10.0)


# ---------------------------------------------------------------------------
# Tool 8: aero_cea_lite
# ---------------------------------------------------------------------------

class TestAeroCeaLite:

    def test_lox_rp1(self):
        result = aero_cea_lite("LOX/RP-1", of_ratio=2.3, chamber_pressure=70.0)
        assert result.get("ok", True)
        # Reference: Tc ~ 3500-3700 K at OF=2.3, Pc=70 bar
        assert 2500 < result["tc_k"] < 4500
        assert result["isp_vac_s"] > 200
        assert result["c_star_m_s"] > 1000
        assert 1.0 < result["gamma"] < 1.8

    def test_lox_lh2(self):
        result = aero_cea_lite("LOX/LH2", of_ratio=6.0, chamber_pressure=100.0)
        assert result["ok"]
        # LH2 has higher Isp
        assert result["isp_vac_s"] > 350

    def test_n2o4_mmh(self):
        result = aero_cea_lite("N2O4/MMH", of_ratio=1.73, chamber_pressure=30.0)
        assert result["ok"]
        assert result["tc_k"] > 2000

    def test_lox_ch4(self):
        result = aero_cea_lite("LOX/CH4", of_ratio=3.4, chamber_pressure=60.0)
        assert result["ok"]

    def test_with_oxidizer_kwarg(self):
        result = aero_cea_lite("RP-1", oxidizer="LOX", of_ratio=2.5)
        assert result["ok"]

    def test_unknown_propellant_raises(self):
        with pytest.raises(ValueError, match="CEA-lite failed|unknown"):
            aero_cea_lite("UNICORN/FUEL", of_ratio=2.0)

    def test_invalid_of_ratio_raises(self):
        with pytest.raises(ValueError, match="of_ratio"):
            aero_cea_lite("LOX/RP-1", of_ratio=0.0)

    def test_invalid_chamber_pressure_raises(self):
        with pytest.raises(ValueError, match="chamber_pressure"):
            aero_cea_lite("LOX/RP-1", of_ratio=2.3, chamber_pressure=-5.0)


# ---------------------------------------------------------------------------
# Tool 9: aero_atmosphere
# ---------------------------------------------------------------------------

class TestAeroAtmosphere:

    def test_sea_level(self):
        result = aero_atmosphere(0.0)
        assert result.get("ok", True)
        # ISA sea level: T=288.15 K, P=101325 Pa
        assert abs(result["temperature_k"] - 288.15) < 0.5
        assert abs(result["pressure_pa"] - 101325.0) < 100.0
        assert result["density_kg_m3"] > 1.0
        assert result["layer"] == "Troposphere"

    def test_tropopause(self):
        result = aero_atmosphere(11.0)
        # ISA tropopause: T=216.65 K
        assert abs(result["temperature_k"] - 216.65) < 1.0
        assert result["layer"] == "Tropopause"

    def test_stratosphere(self):
        result = aero_atmosphere(25.0)
        assert result["ok"]
        assert "Stratosphere" in result["layer"]

    def test_mesosphere(self):
        result = aero_atmosphere(70.0)
        assert result["ok"]
        assert "Meso" in result["layer"]

    def test_density_decreases_with_altitude(self):
        r0 = aero_atmosphere(0.0)
        r10 = aero_atmosphere(10.0)
        r30 = aero_atmosphere(30.0)
        assert r0["density_kg_m3"] > r10["density_kg_m3"] > r30["density_kg_m3"]

    def test_speed_of_sound_positive(self):
        result = aero_atmosphere(5.0)
        assert result["speed_of_sound_m_s"] > 200.0

    def test_negative_altitude_raises(self):
        with pytest.raises(ValueError, match="altitude_km"):
            aero_atmosphere(-1.0)

    def test_above_model_limit_raises(self):
        with pytest.raises(ValueError, match="86"):
            aero_atmosphere(90.0)

    def test_pressure_hpa_consistent(self):
        result = aero_atmosphere(0.0)
        assert abs(result["pressure_hpa"] - result["pressure_pa"] / 100.0) < 0.01


# ---------------------------------------------------------------------------
# Tool 10: aero_attitude_propagate
# ---------------------------------------------------------------------------

class TestAeroAttitudePropagate:

    def test_identity_no_rotation_stays_still(self):
        result = aero_attitude_propagate(
            quaternion=[1.0, 0.0, 0.0, 0.0],
            omega_body=[0.0, 0.0, 0.0],
            duration=5.0,
            dt=0.1,
        )
        assert result.get("ok", True)
        # No angular velocity → quaternion unchanged
        q = result["q_final"]
        assert abs(q[0] - 1.0) < 1e-6
        assert abs(q[1]) < 1e-6

    def test_spin_about_z_axis(self):
        result = aero_attitude_propagate(
            quaternion=[1.0, 0.0, 0.0, 0.0],
            omega_body=[0.0, 0.0, 0.1],
            duration=5.0,
            dt=0.05,
        )
        assert result["ok"]
        q = result["q_final"]
        # Quaternion should remain normalised
        norm = sum(x ** 2 for x in q) ** 0.5
        assert abs(norm - 1.0) < 1e-5

    def test_returns_euler_angles(self):
        result = aero_attitude_propagate(
            quaternion=[1.0, 0.0, 0.0, 0.0],
            omega_body=[0.1, 0.05, 0.02],
            duration=2.0,
            dt=0.1,
        )
        assert "euler_final_deg" in result
        assert len(result["euler_final_deg"]) == 3

    def test_invalid_quaternion_length_raises(self):
        with pytest.raises(ValueError, match="quaternion"):
            aero_attitude_propagate([1, 0, 0], [0, 0, 0], 1.0)

    def test_invalid_omega_length_raises(self):
        with pytest.raises(ValueError, match="omega_body"):
            aero_attitude_propagate([1, 0, 0, 0], [0, 0], 1.0)

    def test_zero_duration_raises(self):
        with pytest.raises(ValueError, match="duration"):
            aero_attitude_propagate([1, 0, 0, 0], [0, 0, 0], 0.0)

    def test_dt_too_small_raises(self):
        with pytest.raises(ValueError, match="dt"):
            aero_attitude_propagate([1, 0, 0, 0], [0, 0, 0], 1.0, dt=0.00001)

    def test_too_many_steps_raises(self):
        with pytest.raises(ValueError, match="Too many steps"):
            aero_attitude_propagate([1, 0, 0, 0], [0, 0, 0], 1000.0, dt=0.001)


# ---------------------------------------------------------------------------
# Tool 11: aero_thermal_steady_state
# ---------------------------------------------------------------------------

class TestAeroThermalSteadyState:

    def _simple_network(self):
        """Single panel radiating to space — steady-state has analytic solution."""
        nodes = [
            {"node_id": "panel", "T": 300.0, "Q_ext": 100.0},
            {"node_id": "space", "T": 3.0, "fixed": True},
        ]
        links = [
            {
                "type": "radiative",
                "node_a": "panel",
                "node_b": "space",
                "epsilon_eff": 0.85,
                "area": 1.0,
                "view_factor": 1.0,
            }
        ]
        return nodes, links

    def test_simple_radiative_network(self):
        nodes, links = self._simple_network()
        result = aero_thermal_steady_state(nodes, links)
        assert result.get("ok", True)
        assert result["converged"]
        assert "panel" in result["temperatures"]
        # Panel should settle above 3K (space) and have some finite temperature
        T_panel = result["temperatures"]["panel"]
        assert T_panel > 50.0  # above space temp
        assert T_panel < 1000.0

    def test_space_node_stays_fixed(self):
        nodes, links = self._simple_network()
        result = aero_thermal_steady_state(nodes, links)
        assert abs(result["temperatures"]["space"] - 3.0) < 0.01

    def test_conductive_link(self):
        nodes = [
            {"node_id": "hot", "T": 500.0, "fixed": True},
            {"node_id": "cold", "T": 100.0},
        ]
        links = [
            {
                "type": "conductive",
                "node_a": "hot",
                "node_b": "cold",
                "conductance": 10.0,
            }
        ]
        result = aero_thermal_steady_state(nodes, links)
        assert result["converged"]
        # Cold node with no external heat and only conductive link to fixed hot
        # will reach hot temperature
        T_cold = result["temperatures"]["cold"]
        assert abs(T_cold - 500.0) < 10.0  # should converge to hot-side T

    def test_missing_node_id_raises(self):
        with pytest.raises(ValueError, match="node_id"):
            aero_thermal_steady_state(
                [{"T": 300.0}],
                []
            )

    def test_missing_T_raises(self):
        with pytest.raises(ValueError, match="'T'"):
            aero_thermal_steady_state(
                [{"node_id": "x"}],
                []
            )

    def test_unknown_link_node_raises(self):
        nodes = [{"node_id": "a", "T": 300.0}]
        links = [
            {"type": "conductive", "node_a": "a", "node_b": "unknown", "conductance": 1.0}
        ]
        with pytest.raises(ValueError, match="node_b"):
            aero_thermal_steady_state(nodes, links)

    def test_unknown_link_type_raises(self):
        nodes = [
            {"node_id": "a", "T": 300.0},
            {"node_id": "b", "T": 200.0},
        ]
        links = [
            {"type": "quantum_entanglement", "node_a": "a", "node_b": "b"}
        ]
        with pytest.raises(ValueError, match="link type"):
            aero_thermal_steady_state(nodes, links)

    def test_missing_conductance_raises(self):
        nodes = [
            {"node_id": "a", "T": 300.0},
            {"node_id": "b", "T": 200.0},
        ]
        links = [{"type": "conductive", "node_a": "a", "node_b": "b"}]
        with pytest.raises(ValueError, match="conductance"):
            aero_thermal_steady_state(nodes, links)

    def test_missing_radiative_fields_raises(self):
        nodes = [
            {"node_id": "a", "T": 300.0},
            {"node_id": "b", "T": 200.0},
        ]
        links = [{"type": "radiative", "node_a": "a", "node_b": "b"}]
        with pytest.raises(ValueError, match="epsilon_eff|area|view_factor"):
            aero_thermal_steady_state(nodes, links)


# ---------------------------------------------------------------------------
# Tool 12: aero_material_lookup
# ---------------------------------------------------------------------------

class TestAeroMaterialLookup:

    def test_al2024_by_slug(self):
        result = aero_material_lookup("al2024-t3")
        assert result.get("ok", True)
        assert result["name"] == "Aluminium 2024-T3"
        assert result["density_kg_m3"] > 0
        assert result["youngs_modulus_gpa"] > 0

    def test_al7075_by_alias(self):
        result = aero_material_lookup("al7075")
        assert "7075" in result["name"]

    def test_titanium_alias(self):
        result = aero_material_lookup("titanium")
        assert "Ti" in result["name"] or "titanium" in result["name"].lower()

    def test_cfrp_alias(self):
        result = aero_material_lookup("cfrp")
        assert result["category"] == "composite"

    def test_inconel_alias(self):
        result = aero_material_lookup("inconel")
        assert "Inconel" in result["name"]
        assert result["max_service_temp_c"] > 500

    def test_pica_ablator(self):
        result = aero_material_lookup("pica")
        assert result["category"] == "tps"
        assert result["density_kg_m3"] < 500  # very low density

    def test_kapton(self):
        result = aero_material_lookup("kapton")
        assert result["category"] == "polymer"

    def test_unknown_material_raises(self):
        with pytest.raises(ValueError, match="not found"):
            aero_material_lookup("unobtanium_xyzzyx_99")

    def test_all_materials_have_required_fields(self):
        slugs = ["al2024-t3", "al6061-t6", "al7075-t6", "ti-6al-4v",
                 "4340-steel", "cfrp-ud-t300", "inconel-718", "kapton-h"]
        for slug in slugs:
            result = aero_material_lookup(slug)
            assert result["ok"]
            assert "density_kg_m3" in result
            assert "category" in result
            assert "uses" in result

    def test_sic_cmc(self):
        result = aero_material_lookup("sic")
        assert result["category"] == "cmc"
        assert result["max_service_temp_c"] > 1000
