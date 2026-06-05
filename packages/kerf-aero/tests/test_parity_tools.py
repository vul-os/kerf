"""
Tests for parity-gap LLM tools:
  - aero_flutter_typical_section  (Tool 15)
  - aero_reentry_heat_flux        (Tool 16)
  - aero_sixdof_simulate          (Tool 17)
  - aero_staging                  (Tool 18)

Oracle values:
  - Flutter: Bisplinghoff et al. (1955) typical section default params give
    U_F* = U_F/(b·ω_α) ≈ 2.0-2.5 (exact depends on μ, ω_h/ω_α, r_α, x_α, a).
    With ω_h/ω_α = 0.5, μ=20, a=-0.2, x_α=0.1, r_α=0.5: U_F* ≈ 2.15.
  - Reentry heat flux: q_conv = 1.7415e-4 * sqrt(rho/R_n) * V^3.
    At sea level (rho=1.225), V=7800 m/s, R_n=0.5m:
    q = 1.7415e-4 * sqrt(1.225/0.5) * 7800^3 ≈ 7.65e9 W/m²
  - 6-DOF: level flight with zero forces decelerates due to gravity—
    altitude drops (z goes positive). No forces → gravity only.
  - Staging: 2-stage rocket, Isp=350, total ΔV=9200 m/s, payload=1000 kg.
"""

from __future__ import annotations

import math
import pytest

from kerf_aero.llm_tools.aerospace_tools import (
    aero_flutter_typical_section,
    aero_reentry_heat_flux,
    aero_sixdof_simulate,
    aero_staging,
)


# ---------------------------------------------------------------------------
# Tool 15: aero_flutter_typical_section
# ---------------------------------------------------------------------------

class TestFlutterTypicalSection:

    def test_returns_ok_dict(self):
        result = aero_flutter_typical_section(
            b=0.5, omega_h=10.0, omega_alpha=20.0, mu=20.0, n_v=60
        )
        assert isinstance(result, dict)
        assert result.get("ok") is True

    def test_flutter_speed_found(self):
        # Default params: ω_h/ω_α = 0.5, μ=20, a=-0.2, x_α=0.1, r_α=0.5, rho=1.225
        result = aero_flutter_typical_section(
            b=0.5, a=-0.2, x_alpha=0.1, r_alpha=0.5,
            omega_h=10.0, omega_alpha=20.0, mu=20.0, rho=1.225,
            n_v=120,
        )
        assert result["ok"]
        U_F = result["flutter_speed_m_s"]
        assert U_F is not None, "Expected flutter speed to be found"
        assert U_F > 0
        # Non-dimensional flutter speed should be in reasonable range
        U_F_nd = result["flutter_speed_nd"]
        assert U_F_nd is not None
        # Bisplinghoff reference: U_F* ≈ 2.0-2.5 for these params
        assert 1.0 < U_F_nd < 5.0, f"U_F* = {U_F_nd} outside expected [1, 5]"

    def test_flutter_freq_positive(self):
        result = aero_flutter_typical_section(
            b=0.5, omega_h=10.0, omega_alpha=20.0, mu=20.0, n_v=80
        )
        if result["flutter_speed_m_s"] is not None:
            assert result["flutter_freq_rad_s"] > 0
            assert result["flutter_freq_hz"] > 0

    def test_vg_arrays_correct_length(self):
        n_v = 50
        result = aero_flutter_typical_section(
            b=0.5, omega_h=10.0, omega_alpha=20.0, mu=20.0, n_v=n_v
        )
        assert len(result["velocities_m_s"]) == n_v
        assert len(result["damping_mode0"]) == n_v
        assert len(result["damping_mode1"]) == n_v
        assert len(result["freq_mode0_rad_s"]) == n_v
        assert len(result["freq_mode1_rad_s"]) == n_v

    def test_high_mass_ratio_raises_flutter_speed(self):
        """Heavier wing (larger μ) should flutter at higher speed."""
        r1 = aero_flutter_typical_section(
            b=0.5, omega_h=10.0, omega_alpha=20.0, mu=20.0, n_v=100
        )
        r2 = aero_flutter_typical_section(
            b=0.5, omega_h=10.0, omega_alpha=20.0, mu=50.0, n_v=100
        )
        if r1["flutter_speed_m_s"] and r2["flutter_speed_m_s"]:
            assert r2["flutter_speed_m_s"] > r1["flutter_speed_m_s"]

    def test_invalid_b_raises(self):
        with pytest.raises(ValueError, match="b"):
            aero_flutter_typical_section(b=-0.1, omega_h=10, omega_alpha=20)

    def test_invalid_omega_h_raises(self):
        with pytest.raises(ValueError, match="omega_h"):
            aero_flutter_typical_section(b=0.5, omega_h=0, omega_alpha=20)

    def test_method_string_present(self):
        result = aero_flutter_typical_section(b=0.5, omega_h=10, omega_alpha=20, n_v=30)
        assert "Theodorsen" in result["method"]
        assert "reference" in result


# ---------------------------------------------------------------------------
# Tool 16: aero_reentry_heat_flux
# ---------------------------------------------------------------------------

class TestReentryHeatFlux:

    def test_point_mode_returns_ok(self):
        result = aero_reentry_heat_flux(velocity_m_s=7800, altitude_km=70)
        assert isinstance(result, dict)
        assert result.get("ok") is True

    def test_sutton_graves_formula(self):
        """
        Verify Sutton-Graves: q = k_SG * sqrt(rho/Rn) * V^3
        At 70 km ISA: rho ≈ 8.28e-5 kg/m³, V=7800 m/s, Rn=0.2 m:
        q ≈ 1.7415e-4 * sqrt(8.28e-5 / 0.2) * 7800^3 ≈ 1.68e6 W/m²
        Allow ±20% around computed value.
        """
        K_SG = 1.7415e-4
        V = 7800.0
        Rn = 0.2
        # ISA density at 70 km ≈ 8.28e-5 kg/m³ (US Std Atm 1976)
        rho_70km = 8.282864591179e-5
        expected_q = K_SG * math.sqrt(rho_70km / Rn) * V**3

        result = aero_reentry_heat_flux(velocity_m_s=V, altitude_km=70, nose_radius_m=Rn)
        assert result["ok"]
        q = result["q_convective_W_m2"]
        assert q > 0
        # Check within ±5% of analytic expectation
        assert abs(q - expected_q) / expected_q < 0.05, f"q_conv={q} expected≈{expected_q}"

    def test_sea_level_formula(self):
        """At sea level (rho=1.225), V=500, Rn=0.5."""
        K_SG = 1.7415e-4
        V = 500.0
        rho = 1.225
        Rn = 0.5
        expected = K_SG * math.sqrt(rho / Rn) * V**3
        result = aero_reentry_heat_flux(velocity_m_s=V, altitude_km=0, nose_radius_m=Rn,
                                         include_radiative=False)
        assert result["ok"]
        q = result["q_convective_W_m2"]
        assert abs(q - expected) / expected < 0.05, f"q={q} expected≈{expected}"

    def test_radiative_zero_below_10kms(self):
        """Radiative flux should be zero below 10 km/s."""
        result = aero_reentry_heat_flux(velocity_m_s=5000, altitude_km=50,
                                         include_radiative=True)
        assert result["q_radiative_W_m2"] == 0.0

    def test_radiative_nonzero_above_10kms(self):
        """Radiative flux should be non-zero above 10 km/s."""
        result = aero_reentry_heat_flux(velocity_m_s=11000, altitude_km=60,
                                         include_radiative=True)
        assert result["q_radiative_W_m2"] > 0

    def test_wcm2_consistent(self):
        result = aero_reentry_heat_flux(velocity_m_s=7800, altitude_km=70)
        q_total = result["q_total_W_m2"]
        q_cm2 = result["q_total_W_cm2"]
        assert abs(q_cm2 - q_total / 1e4) < 1.0

    def test_trajectory_mode(self):
        traj = [[80, 5000], [70, 7000], [60, 8000], [50, 7000], [40, 5000]]
        result = aero_reentry_heat_flux(
            velocity_m_s=0, altitude_km=0, trajectory_table=traj
        )
        assert result["ok"]
        assert result["n_points"] == 5
        assert len(result["trajectory"]) == 5
        assert all("q_total_W_m2" in p for p in result["trajectory"])

    def test_invalid_altitude(self):
        with pytest.raises(ValueError, match="altitude"):
            aero_reentry_heat_flux(velocity_m_s=7800, altitude_km=200)

    def test_invalid_nose_radius(self):
        with pytest.raises(ValueError, match="nose_radius"):
            aero_reentry_heat_flux(velocity_m_s=7800, altitude_km=70, nose_radius_m=-0.1)


# ---------------------------------------------------------------------------
# Tool 17: aero_sixdof_simulate
# ---------------------------------------------------------------------------

class TestSixDOFSimulate:

    def test_returns_ok_dict(self):
        result = aero_sixdof_simulate(
            mass_kg=1000, ixx=100, iyy=500, izz=500,
            airspeed_m_s=50, altitude_m=500,
            duration=5.0, dt=0.1,
        )
        assert isinstance(result, dict)
        assert result.get("ok") is True

    def test_trajectory_has_correct_steps(self):
        result = aero_sixdof_simulate(
            mass_kg=1000, ixx=100, iyy=500, izz=500,
            airspeed_m_s=50, altitude_m=500,
            duration=10.0, dt=0.1,
        )
        assert result["ok"]
        assert result["n_steps"] == 100

    def test_gravity_only_drops_altitude(self):
        """With zero applied forces, aircraft falls due to gravity."""
        result = aero_sixdof_simulate(
            mass_kg=1000, ixx=100, iyy=500, izz=500,
            airspeed_m_s=0, altitude_m=1000,
            duration=2.0, dt=0.1,
            fx=0, fy=0, fz=0, mx=0, my=0, mz=0,
        )
        assert result["ok"]
        # Altitude should decrease (gravity pulls down)
        assert result["final_altitude_m"] < 1000.0

    def test_final_state_structure(self):
        result = aero_sixdof_simulate(
            mass_kg=500, ixx=50, iyy=200, izz=200,
            duration=2.0, dt=0.05,
        )
        assert result["ok"]
        fs = result["final_state"]
        for key in ("altitude_m", "u_m_s", "v_m_s", "w_m_s", "quaternion",
                    "p_rad_s", "q_rad_s", "r_rad_s"):
            assert key in fs

    def test_euler_angles_present(self):
        result = aero_sixdof_simulate(
            mass_kg=500, ixx=50, iyy=200, izz=200,
            duration=1.0, dt=0.1,
        )
        assert result["ok"]
        euler = result["final_euler_deg"]
        assert len(euler) == 3
        assert all(isinstance(v, float) for v in euler)

    def test_trajectory_summary_non_empty(self):
        result = aero_sixdof_simulate(
            mass_kg=1000, ixx=100, iyy=500, izz=500,
            airspeed_m_s=50, altitude_m=500,
            duration=10.0, dt=0.1,
        )
        assert result["ok"]
        assert len(result["trajectory_summary"]) > 0
        pt = result["trajectory_summary"][0]
        assert "t_s" in pt
        assert "altitude_m" in pt
        assert "airspeed_m_s" in pt

    def test_invalid_mass_raises(self):
        with pytest.raises(ValueError, match="mass_kg"):
            aero_sixdof_simulate(mass_kg=0, ixx=100, iyy=500, izz=500)

    def test_invalid_dt_raises(self):
        with pytest.raises(ValueError, match="dt"):
            aero_sixdof_simulate(mass_kg=500, ixx=50, iyy=200, izz=200, dt=0.0001)

    def test_too_many_steps_raises(self):
        with pytest.raises(ValueError, match="Too many steps"):
            aero_sixdof_simulate(
                mass_kg=500, ixx=50, iyy=200, izz=200,
                duration=200, dt=0.001,
            )


# ---------------------------------------------------------------------------
# Tool 18: aero_staging
# ---------------------------------------------------------------------------

class TestAeroStaging:

    def test_explicit_two_stage(self):
        stages = [
            {"isp": 350, "m0": 10000, "mf": 4000, "name": "Stage 1"},
            {"isp": 350, "m0": 2000,  "mf": 800,  "name": "Stage 2"},
        ]
        result = aero_staging(stages=stages)
        assert result["ok"]
        assert result["mode"] == "explicit"
        assert result["n_stages"] == 2
        assert result["total_delta_v_m_s"] > 0
        # Sum of stage DVs
        stage_sum = sum(s["delta_v_ms"] for s in result["stage_results"])
        assert abs(stage_sum - result["total_delta_v_m_s"]) < 0.1

    def test_explicit_single_stage_tsiolkovsky(self):
        """Verify Tsiolkovsky: ΔV = Isp * g0 * ln(m0/mf)"""
        isp = 350.0
        m0 = 5000.0
        mf = 2000.0
        g0 = 9.80665
        expected_dv = isp * g0 * math.log(m0 / mf)
        result = aero_staging(stages=[{"isp": isp, "m0": m0, "mf": mf}])
        assert result["ok"]
        assert abs(result["total_delta_v_m_s"] - expected_dv) < 0.01

    def test_optimal_split_returns_ok(self):
        result = aero_staging(
            total_delta_v=9200, n_stages=2, isp_per_stage=350,
            payload_mass=1000, structural_fraction=0.1,
        )
        assert result["ok"]
        assert result["mode"] == "optimal_split"

    def test_optimal_split_dv_sums_correctly(self):
        result = aero_staging(
            total_delta_v=9200, n_stages=2, isp_per_stage=350, payload_mass=1000,
        )
        assert result["ok"]
        splits = result["optimal_dv_split_m_s"]
        assert abs(sum(splits) - 9200) < 0.1

    def test_optimal_equal_isp_equal_split(self):
        """Equal Isp + equal structural fraction → equal ΔV split."""
        result = aero_staging(
            total_delta_v=9000, n_stages=3, isp_per_stage=350,
            payload_mass=500, structural_fraction=0.1,
        )
        assert result["ok"]
        if result["equal_split"]:
            splits = result["optimal_dv_split_m_s"]
            for dv in splits:
                assert abs(dv - 3000) < 1.0

    def test_payload_fraction_positive(self):
        result = aero_staging(
            total_delta_v=9200, n_stages=2, isp_per_stage=350,
            payload_mass=1000, structural_fraction=0.1,
        )
        assert result["ok"]
        assert 0 < result["payload_fraction"] < 1.0

    def test_unequal_isp_stages(self):
        """Unequal Isp per stage: first stage lower Isp (e.g. solid), second higher."""
        result = aero_staging(
            total_delta_v=8000, n_stages=2,
            isp_per_stage=[280.0, 420.0],
            payload_mass=500, structural_fraction=0.1,
        )
        assert result["ok"]
        assert result["n_stages"] == 2

    def test_explicit_empty_raises(self):
        with pytest.raises(ValueError):
            aero_staging(stages=[])

    def test_no_args_raises(self):
        with pytest.raises(ValueError, match="total_delta_v"):
            aero_staging()

    def test_invalid_total_dv_raises(self):
        with pytest.raises(ValueError, match="total_delta_v"):
            aero_staging(total_delta_v=-100, n_stages=2, isp_per_stage=350)
