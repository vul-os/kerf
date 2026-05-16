"""
Hermetic tests for kerf_cad_core.seismic — ASCE 7 ELF seismic analysis.

Coverage:
  elf.site_coefficients               — Fa/Fv table lookup, SMS/SM1/SDS/SD1
  elf.design_spectrum                 — Sa(T) four regions, T0/Ts/TL
  elf.approximate_period              — Ta = Ct·hn^x, all structure types
  elf.seismic_response_coefficient    — Cs basic/cap/floor, governing cases
  elf.base_shear                      — V = Cs·W
  elf.vertical_distribution           — Fx/Cvx with k exponent
  elf.story_shear_and_overturning     — Vx, Mx at each level
  elf.drift_and_stability             — Δx, drift ratio, θ, flags
  elf.sdof_spectral_displacement      — Sd = Sa·g·T²/(4π²)
  tools.*                             — LLM tool wrappers (happy + error paths)

All tests are pure-Python and hermetic: no OCC, no DB, no network.
Formulas verified algebraically against ASCE 7 hand-calculations.

References
----------
ASCE/SEI 7-22, Chapters 11–12.

Author: imranparuk
"""
from __future__ import annotations

import asyncio
import json
import math
import uuid

import pytest

from kerf_cad_core.seismic.elf import (
    site_coefficients,
    design_spectrum,
    approximate_period,
    seismic_response_coefficient,
    base_shear,
    vertical_distribution,
    story_shear_and_overturning,
    drift_and_stability,
    sdof_spectral_displacement,
)
from kerf_cad_core.seismic.tools import (
    run_site_coefficients,
    run_design_spectrum,
    run_approximate_period,
    run_response_coefficient,
    run_base_shear,
    run_vertical_distribution,
    run_story_shear_overturning,
    run_drift_stability,
    run_sdof_displacement,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _ctx():
    try:
        from kerf_core.utils.context import ProjectCtx  # type: ignore[import]
        return ProjectCtx(
            pool=None, storage=None,
            project_id=uuid.uuid4(), user_id=uuid.uuid4(),
            role="owner", http_client=None,
        )
    except Exception:
        return None


def _args(**kwargs) -> bytes:
    return json.dumps(kwargs).encode()


def _ok_tool(raw: str) -> dict:
    d = json.loads(raw)
    assert d.get("ok") is True, f"Expected ok=True, got: {d}"
    return d


def _err_tool(raw: str) -> dict:
    d = json.loads(raw)
    is_ok_false = d.get("ok") is False
    is_err_payload = "error" in d and "code" in d
    assert is_ok_false or is_err_payload, f"Expected error response, got: {d}"
    return d


REL = 1e-5


# ===========================================================================
# 1. site_coefficients — ASCE 7 Tables 11.4-1 / 11.4-2
# ===========================================================================

class TestSiteCoefficients:

    def test_site_class_D_typical(self):
        """Site class D, Ss=1.0, S1=0.4 → known table values."""
        res = site_coefficients(1.0, 0.4, "D")
        assert res["ok"] is True
        # From ASCE 7 Table 11.4-1, Ss=1.0, D → Fa=1.1
        assert abs(res["Fa"] - 1.1) < 0.01
        # From ASCE 7 Table 11.4-2, S1=0.4, D → Fv=1.9
        assert abs(res["Fv"] - 1.9) < 0.01
        assert abs(res["SMS"] - res["Fa"] * 1.0) < 1e-4
        assert abs(res["SM1"] - res["Fv"] * 0.4) < 1e-4
        # SDS and SD1 use the rounded SMS/SM1 values
        assert abs(res["SDS"] - (2.0 / 3.0) * res["SMS"]) < 5e-4
        assert abs(res["SD1"] - (2.0 / 3.0) * res["SM1"]) < 5e-4

    def test_site_class_A_all_periods(self):
        """Site class A → Fa=0.8, Fv=0.8 always."""
        res = site_coefficients(0.5, 0.2, "A")
        assert res["ok"] is True
        assert abs(res["Fa"] - 0.8) < 1e-6
        assert abs(res["Fv"] - 0.8) < 1e-6

    def test_site_class_B(self):
        """Site class B → Fa=0.9, Fv=0.8 always."""
        res = site_coefficients(1.0, 0.5, "B")
        assert res["ok"] is True
        assert abs(res["Fa"] - 0.9) < 1e-6
        assert abs(res["Fv"] - 0.8) < 1e-6

    def test_site_class_C_interpolation(self):
        """Site class C, Ss=0.375 → Fa interpolated between 1.3 and 1.2."""
        res = site_coefficients(0.375, 0.1, "C")
        assert res["ok"] is True
        # At Ss=0.25: 1.3; at Ss=0.50: 1.3 → stays 1.3 in this range
        # (both endpoints are 1.3 so no change)
        assert abs(res["Fa"] - 1.3) < 1e-6

    def test_site_class_C_high_ss(self):
        """Site class C, Ss=1.5 → Fa=1.2."""
        res = site_coefficients(1.5, 0.6, "C")
        assert res["ok"] is True
        assert abs(res["Fa"] - 1.2) < 1e-4

    def test_site_class_E_low_values(self):
        """Site class E, Ss=0.25 → Fa=2.4 (table entry)."""
        res = site_coefficients(0.25, 0.1, "E")
        assert res["ok"] is True
        assert abs(res["Fa"] - 2.4) < 1e-6

    def test_site_class_E_requires_site_specific(self):
        """Site class E, Ss=1.0 → site-specific required, should error."""
        res = site_coefficients(1.0, 0.3, "E")
        assert res["ok"] is False
        assert "site-specific" in res["reason"].lower() or "not tabulated" in res["reason"].lower()

    def test_sds_sd1_formula(self):
        """SDS = 2/3 · SMS and SD1 = 2/3 · SM1 (within rounding)."""
        res = site_coefficients(0.6, 0.2, "D")
        assert res["ok"] is True
        # SDS and SD1 are rounded to 4 decimal places from rounded SMS/SM1
        assert abs(res["SDS"] - (2.0 / 3.0) * res["SMS"]) < 5e-4
        assert abs(res["SD1"] - (2.0 / 3.0) * res["SM1"]) < 5e-4

    def test_invalid_site_class(self):
        res = site_coefficients(1.0, 0.4, "F")
        assert res["ok"] is False

    def test_negative_Ss(self):
        res = site_coefficients(-0.1, 0.2, "D")
        assert res["ok"] is False

    def test_lowercase_site_class(self):
        """site_class should be case-insensitive."""
        res = site_coefficients(0.5, 0.2, "d")
        assert res["ok"] is True


# ===========================================================================
# 2. design_spectrum — ASCE 7 §11.4.5
# ===========================================================================

class TestDesignSpectrum:

    def test_constant_acceleration_region(self):
        """T in [T0, Ts] → Sa = SDS."""
        SDS, SD1 = 1.2, 0.6
        T0 = 0.2 * SD1 / SDS   # 0.10 s
        Ts = SD1 / SDS           # 0.50 s
        T = 0.3  # inside [T0, Ts]
        res = design_spectrum(T, SDS, SD1)
        assert res["ok"] is True
        assert res["region"] == "constant_acceleration"
        assert abs(res["Sa_g"] - SDS) < 1e-9

    def test_constant_velocity_region(self):
        """T in (Ts, TL] → Sa = SD1/T."""
        SDS, SD1 = 1.2, 0.6
        Ts = SD1 / SDS  # 0.50 s
        T = 1.0
        assert T > Ts
        res = design_spectrum(T, SDS, SD1)
        assert res["ok"] is True
        assert res["region"] == "constant_velocity"
        assert abs(res["Sa_g"] - SD1 / T) < 1e-9

    def test_rising_region(self):
        """T < T0 → Sa = SDS·(0.4 + 0.6·T/T0)."""
        SDS, SD1 = 1.0, 0.5
        T0 = 0.2 * SD1 / SDS
        T = T0 / 2.0
        res = design_spectrum(T, SDS, SD1)
        assert res["ok"] is True
        assert res["region"] == "rising"
        expected = SDS * (0.4 + 0.6 * T / T0)
        assert abs(res["Sa_g"] - expected) < 1e-9

    def test_long_period_region(self):
        """T > TL → Sa = SD1·TL/T²."""
        SDS, SD1, TL = 1.0, 0.5, 6.0
        T = 8.0
        res = design_spectrum(T, SDS, SD1, TL=TL)
        assert res["ok"] is True
        assert res["region"] == "long_period"
        expected = SD1 * TL / (T ** 2)
        assert abs(res["Sa_g"] - expected) < 1e-9

    def test_T0_and_Ts_computed(self):
        """T0 and Ts returned correctly."""
        SDS, SD1 = 0.8, 0.4
        res = design_spectrum(0.5, SDS, SD1)
        assert res["ok"] is True
        assert abs(res["T0"] - 0.2 * SD1 / SDS) < 1e-9
        assert abs(res["Ts"] - SD1 / SDS) < 1e-9

    def test_invalid_T_negative(self):
        res = design_spectrum(-0.1, 1.0, 0.5)
        assert res["ok"] is False

    def test_invalid_SDS_zero(self):
        res = design_spectrum(0.5, 0.0, 0.4)
        assert res["ok"] is False


# ===========================================================================
# 3. approximate_period — ASCE 7 Table 12.8-2
# ===========================================================================

class TestApproximatePeriod:

    def test_steel_moment_frame(self):
        """Steel moment: Ta = 0.0724 · hn^0.80."""
        hn = 20.0
        res = approximate_period(hn, "steel_moment")
        assert res["ok"] is True
        expected = 0.0724 * (hn ** 0.80)
        # Ta_s is rounded to 4 decimal places
        assert abs(res["Ta_s"] - expected) < 1e-4

    def test_concrete_moment_frame(self):
        """Concrete moment: Ta = 0.0466 · hn^0.90."""
        hn = 15.0
        res = approximate_period(hn, "concrete_moment")
        assert res["ok"] is True
        expected = 0.0466 * (hn ** 0.90)
        assert abs(res["Ta_s"] - expected) < 1e-4

    def test_eccentrically_braced(self):
        """EBF: Ta = 0.0731 · hn^0.75."""
        hn = 30.0
        res = approximate_period(hn, "eccentrically_braced")
        assert res["ok"] is True
        expected = 0.0731 * (hn ** 0.75)
        assert abs(res["Ta_s"] - expected) < 1e-4

    def test_other_structure(self):
        """Other: Ta = 0.0488 · hn^0.75."""
        hn = 10.0
        res = approximate_period(hn, "other")
        assert res["ok"] is True
        expected = 0.0488 * (hn ** 0.75)
        assert abs(res["Ta_s"] - expected) < 1e-4

    def test_default_type_is_other(self):
        """Default structure_type='other' matches explicit 'other'."""
        hn = 12.0
        r1 = approximate_period(hn)
        r2 = approximate_period(hn, "other")
        assert r1["ok"] and r2["ok"]
        assert abs(r1["Ta_s"] - r2["Ta_s"]) < 1e-12

    def test_invalid_hn_zero(self):
        res = approximate_period(0.0)
        assert res["ok"] is False

    def test_invalid_structure_type(self):
        res = approximate_period(10.0, "unknown_type")
        assert res["ok"] is False


# ===========================================================================
# 4. seismic_response_coefficient — ASCE 7 §12.8.1.1
# ===========================================================================

class TestSeismicResponseCoefficient:

    def test_basic_formula(self):
        """Cs_basic = SDS / (R/Ie)."""
        SDS, SD1, T, R, Ie = 1.0, 0.5, 0.3, 8.0, 1.0
        res = seismic_response_coefficient(SDS, SD1, T, R, Ie)
        assert res["ok"] is True
        assert abs(res["Cs_basic"] - SDS / (R / Ie)) < 1e-9

    def test_cap_governs_short_period(self):
        """Cap governs when SD1/(T·R/Ie) < SDS/(R/Ie) — long T or high R."""
        SDS, SD1, T, R, Ie = 1.0, 0.4, 2.0, 6.0, 1.0
        res = seismic_response_coefficient(SDS, SD1, T, R, Ie)
        assert res["ok"] is True
        assert res["cap_governs"] is True
        # Cs = max(min(basic, cap), floor); cap governs over basic
        # (final Cs may be raised by floor, but cap_governs flag is still set)
        assert res["Cs"] >= res["Cs_cap"] - 1e-9

    def test_floor_governs(self):
        """Floor governs when 0.044·SDS·Ie > cap — extreme long T."""
        # Make SDS large and T very long so cap is tiny
        SDS, SD1, T, R, Ie = 2.0, 0.1, 50.0, 8.0, 1.0
        res = seismic_response_coefficient(SDS, SD1, T, R, Ie)
        assert res["ok"] is True
        assert res["floor_governs"] is True

    def test_floor_minimum_001(self):
        """Floor: Cs_floor >= 0.01 always."""
        SDS, SD1, T, R, Ie = 0.1, 0.05, 10.0, 8.0, 1.0
        res = seismic_response_coefficient(SDS, SD1, T, R, Ie)
        assert res["ok"] is True
        assert res["Cs_floor"] >= 0.01 - 1e-9

    def test_s1_floor_when_high_s1(self):
        """When S1 >= 0.6g, floor includes 0.5·S1/(R/Ie)."""
        SDS, SD1, T, R, Ie, S1 = 1.5, 0.7, 0.5, 3.0, 1.0, 0.65
        res = seismic_response_coefficient(SDS, SD1, T, R, Ie, S1=S1)
        assert res["ok"] is True
        floor_s1 = 0.5 * S1 / (R / Ie)
        # Cs_floor is rounded to 6 decimal places
        assert res["Cs_floor"] >= floor_s1 - 1e-5

    def test_long_period_cap(self):
        """T > TL: cap = SD1·TL/T²·(R/Ie)."""
        SDS, SD1, T, R, Ie, TL = 1.0, 0.5, 8.0, 6.0, 1.0, 6.0
        res = seismic_response_coefficient(SDS, SD1, T, R, Ie, TL=TL)
        assert res["ok"] is True
        expected_cap = SD1 * TL / (T ** 2 * (R / Ie))
        # Cs_cap is rounded to 6 decimal places
        assert abs(res["Cs_cap"] - expected_cap) < 1e-5

    def test_invalid_negative_R(self):
        res = seismic_response_coefficient(1.0, 0.5, 0.5, -1.0, 1.0)
        assert res["ok"] is False


# ===========================================================================
# 5. base_shear — V = Cs · W
# ===========================================================================

class TestBaseShear:

    def test_simple_calculation(self):
        """V = Cs · W algebraically."""
        Cs, W = 0.1667, 5000.0
        res = base_shear(Cs, W)
        assert res["ok"] is True
        assert abs(res["V_kN"] - Cs * W) < 0.01

    def test_high_seismic_region(self):
        """Large Cs still computes without error."""
        res = base_shear(0.30, 3000.0)
        assert res["ok"] is True
        assert abs(res["V_kN"] - 900.0) < 0.01

    def test_invalid_zero_W(self):
        res = base_shear(0.1, 0.0)
        assert res["ok"] is False

    def test_invalid_negative_Cs(self):
        res = base_shear(-0.05, 5000.0)
        assert res["ok"] is False


# ===========================================================================
# 6. vertical_distribution — Fx and Cvx
# ===========================================================================

class TestVerticalDistribution:

    def test_linear_distribution_T_small(self):
        """T <= 0.5s: k=1, triangular distribution."""
        V = 1000.0
        W = [500.0, 500.0, 500.0]
        h = [3.0, 6.0, 9.0]
        res = vertical_distribution(V, W, h, T=0.3)
        assert res["ok"] is True
        assert abs(res["k"] - 1.0) < 1e-9
        # Cvx ∝ wi·hi → proportional to [3, 6, 9] → fractions [1/6, 2/6, 3/6]
        total_wh = sum(W[i] * h[i] for i in range(3))
        expected_Cvx = [(W[i] * h[i]) / total_wh for i in range(3)]
        for i, ecvx in enumerate(expected_Cvx):
            assert abs(res["Cvx"][i] - ecvx) < REL

    def test_parabolic_distribution_T_large(self):
        """T >= 2.5s: k=2.0."""
        V = 2000.0
        W = [1000.0, 1000.0]
        h = [5.0, 10.0]
        res = vertical_distribution(V, W, h, T=3.0)
        assert res["ok"] is True
        assert abs(res["k"] - 2.0) < 1e-9

    def test_k_interpolation(self):
        """T=1.5s: k = 1.0 + (1.5-0.5)/2.0 = 1.5."""
        V = 500.0
        W = [200.0, 200.0]
        h = [4.0, 8.0]
        res = vertical_distribution(V, W, h, T=1.5)
        assert res["ok"] is True
        assert abs(res["k"] - 1.5) < 1e-9

    def test_fx_sums_to_V(self):
        """Sum of Fx must equal V."""
        V = 1500.0
        W = [400.0, 400.0, 400.0, 400.0]
        h = [3.5, 7.0, 10.5, 14.0]
        res = vertical_distribution(V, W, h, T=0.8)
        assert res["ok"] is True
        assert abs(sum(res["Fx_kN"]) - V) < 0.01

    def test_cvx_sums_to_one(self):
        """Sum of Cvx must equal 1.0."""
        V = 800.0
        W = [300.0, 500.0, 200.0]
        h = [4.0, 8.0, 12.0]
        res = vertical_distribution(V, W, h, T=0.4)
        assert res["ok"] is True
        assert abs(sum(res["Cvx"]) - 1.0) < 1e-9

    def test_invalid_mismatched_lengths(self):
        res = vertical_distribution(1000.0, [500.0, 500.0], [3.0], T=0.5)
        assert res["ok"] is False

    def test_invalid_non_increasing_heights(self):
        res = vertical_distribution(1000.0, [500.0, 500.0], [6.0, 3.0], T=0.5)
        assert res["ok"] is False


# ===========================================================================
# 7. story_shear_and_overturning
# ===========================================================================

class TestStoryShearAndOverturning:

    def test_two_storey_simple(self):
        """Two-storey: Vx[0]=F1+F2, Vx[1]=F2; Mx[0]=F1·0+F2·(h2-h1)."""
        Fx = [300.0, 200.0]
        h = [3.5, 7.0]
        res = story_shear_and_overturning(Fx, h)
        assert res["ok"] is True
        assert abs(res["Vx_kN"][0] - 500.0) < 0.001
        assert abs(res["Vx_kN"][1] - 200.0) < 0.001
        # Mx[0] = F[0]·(3.5-3.5) + F[1]·(7.0-3.5) = 200*3.5 = 700
        assert abs(res["Mx_kNm"][0] - 700.0) < 0.001
        # Mx[1] = F[1]·(7.0-7.0) = 0
        assert abs(res["Mx_kNm"][1] - 0.0) < 0.001

    def test_three_storey_base_shear(self):
        """Vx at base = sum of all Fx."""
        Fx = [100.0, 200.0, 300.0]
        h = [3.0, 6.0, 9.0]
        res = story_shear_and_overturning(Fx, h)
        assert res["ok"] is True
        assert abs(res["Vx_kN"][0] - 600.0) < 0.001

    def test_overturning_at_top_is_zero(self):
        """Top storey overturning moment is always 0."""
        Fx = [50.0, 80.0, 120.0]
        h = [4.0, 8.0, 12.0]
        res = story_shear_and_overturning(Fx, h)
        assert res["ok"] is True
        assert abs(res["Mx_kNm"][-1]) < 1e-9

    def test_invalid_mismatched_lengths(self):
        res = story_shear_and_overturning([100.0, 200.0], [3.0])
        assert res["ok"] is False


# ===========================================================================
# 8. drift_and_stability
# ===========================================================================

class TestDriftAndStability:

    def test_inelastic_drift_formula(self):
        """Δx = Cd · δxe / Ie."""
        delta_xe = [0.005, 0.012]
        Cd, Ie = 5.0, 1.0
        Px = [2000.0, 1000.0]
        Vx = [500.0, 300.0]
        hsx = [3.5, 3.5]
        res = drift_and_stability(delta_xe, Cd, Ie, Px, Vx, hsx)
        assert res["ok"] is True
        for i, dxe in enumerate(delta_xe):
            expected = Cd * dxe / Ie
            assert abs(res["Delta_x_m"][i] - expected) < 1e-9

    def test_drift_ratio_within_limit(self):
        """Small drifts → all drift_ok=True."""
        delta_xe = [0.001, 0.002]
        Cd, Ie = 4.0, 1.0
        hsx = [3.5, 3.5]
        Vx = [400.0, 200.0]
        Px = [1500.0, 800.0]
        res = drift_and_stability(delta_xe, Cd, Ie, Px, Vx, hsx)
        assert res["ok"] is True
        assert all(res["drift_ok"])

    def test_drift_exceedance_flagged(self):
        """Large drifts trigger drift exceedance warning."""
        delta_xe = [0.05]  # Δx = 5*0.05/1 = 0.25 m; ratio = 0.25/3.5 > 0.02
        Cd, Ie = 5.0, 1.0
        hsx = [3.5]
        Vx = [500.0]
        Px = [2000.0]
        res = drift_and_stability(delta_xe, Cd, Ie, Px, Vx, hsx)
        assert res["ok"] is True
        assert not res["drift_ok"][0]
        assert any("drift exceedance" in w.lower() for w in res["warnings"])

    def test_theta_formula(self):
        """θ = Px·Δx/(Vx·hsx·Cd) algebraically verified."""
        delta_xe = [0.002]
        Cd, Ie = 5.0, 1.0
        Px = [3000.0]
        Vx = [600.0]
        hsx = [3.5]
        res = drift_and_stability(delta_xe, Cd, Ie, Px, Vx, hsx)
        assert res["ok"] is True
        Delta_x = Cd * delta_xe[0] / Ie
        expected_theta = Px[0] * Delta_x / (Vx[0] * hsx[0] * Cd)
        # theta is rounded to 6 decimal places
        assert abs(res["theta"][0] - expected_theta) < 1e-5

    def test_theta_high_warns(self):
        """θ > 0.10 → P-delta warning."""
        # Need large Px·Δx relative to Vx·hsx·Cd
        delta_xe = [0.10]  # Δx = 5*0.10/1 = 0.5 m
        Cd, Ie = 5.0, 1.0
        Px = [10000.0]
        Vx = [100.0]
        hsx = [3.5]
        res = drift_and_stability(delta_xe, Cd, Ie, Px, Vx, hsx)
        assert res["ok"] is True
        assert not res["theta_ok"][0]
        assert any("p-delta" in w.lower() for w in res["warnings"])

    def test_custom_drift_limit(self):
        """Custom drift_limit_ratio=0.015 applied correctly."""
        delta_xe = [0.004]  # Δx = 4*0.004 = 0.016; ratio = 0.016/3.5 ≈ 0.00457 < 0.015
        Cd, Ie = 4.0, 1.0
        hsx = [3.5]
        Vx = [400.0]
        Px = [1000.0]
        res = drift_and_stability(
            delta_xe, Cd, Ie, Px, Vx, hsx, drift_limit_ratio=0.015
        )
        assert res["ok"] is True
        assert res["drift_ok"][0]

    def test_invalid_zero_Vx(self):
        res = drift_and_stability([0.002], 5.0, 1.0, [2000.0], [0.0], [3.5])
        assert res["ok"] is False


# ===========================================================================
# 9. sdof_spectral_displacement
# ===========================================================================

class TestSdofSpectralDisplacement:

    def test_algebraic(self):
        """Sd = Sa·g·T²/(4π²)."""
        Sa_g = 0.5
        T = 1.0
        g = 9.80665
        expected = Sa_g * g * T ** 2 / (4.0 * math.pi ** 2)
        res = sdof_spectral_displacement(Sa_g, T)
        assert res["ok"] is True
        # Sd_m is rounded to 6 decimal places
        assert abs(res["Sd_m"] - expected) < 1e-5

    def test_mm_conversion(self):
        """Sd_mm = Sd_m × 1000."""
        res = sdof_spectral_displacement(0.3, 0.5)
        assert res["ok"] is True
        assert abs(res["Sd_mm"] - res["Sd_m"] * 1000.0) < 1e-6

    def test_zero_sa(self):
        """Sa=0 → Sd=0."""
        res = sdof_spectral_displacement(0.0, 1.0)
        assert res["ok"] is True
        assert abs(res["Sd_m"]) < 1e-12

    def test_invalid_negative_T(self):
        res = sdof_spectral_displacement(0.5, 0.0)
        assert res["ok"] is False

    def test_invalid_negative_Sa(self):
        res = sdof_spectral_displacement(-0.1, 1.0)
        assert res["ok"] is False


# ===========================================================================
# 10. LLM Tool wrapper tests
# ===========================================================================

class TestToolWrappers:

    def test_run_site_coefficients_happy(self):
        ctx = _ctx()
        raw = _run(run_site_coefficients(ctx, _args(Ss=1.0, S1=0.4, site_class="D")))
        d = _ok_tool(raw)
        assert d["SDS"] > 0
        assert d["SD1"] > 0

    def test_run_site_coefficients_missing_field(self):
        ctx = _ctx()
        raw = _run(run_site_coefficients(ctx, _args(Ss=1.0, S1=0.4)))  # missing site_class
        _err_tool(raw)

    def test_run_site_coefficients_bad_json(self):
        ctx = _ctx()
        raw = _run(run_site_coefficients(ctx, b"not-json"))
        _err_tool(raw)

    def test_run_design_spectrum_happy(self):
        ctx = _ctx()
        raw = _run(run_design_spectrum(ctx, _args(T=0.5, SDS=1.2, SD1=0.6)))
        d = _ok_tool(raw)
        assert d["Sa_g"] > 0
        assert "region" in d

    def test_run_design_spectrum_missing_SDS(self):
        ctx = _ctx()
        raw = _run(run_design_spectrum(ctx, _args(T=0.5, SD1=0.6)))
        _err_tool(raw)

    def test_run_approximate_period_happy(self):
        ctx = _ctx()
        raw = _run(run_approximate_period(ctx, _args(hn=20.0, structure_type="steel_moment")))
        d = _ok_tool(raw)
        assert d["Ta_s"] > 0

    def test_run_approximate_period_missing_hn(self):
        ctx = _ctx()
        raw = _run(run_approximate_period(ctx, _args(structure_type="other")))
        _err_tool(raw)

    def test_run_response_coefficient_happy(self):
        ctx = _ctx()
        raw = _run(run_response_coefficient(ctx, _args(
            SDS=1.0, SD1=0.5, T=0.5, R=8.0, Ie=1.0
        )))
        d = _ok_tool(raw)
        assert d["Cs"] > 0
        assert "cap_governs" in d

    def test_run_response_coefficient_missing_R(self):
        ctx = _ctx()
        raw = _run(run_response_coefficient(ctx, _args(
            SDS=1.0, SD1=0.5, T=0.5, Ie=1.0
        )))
        _err_tool(raw)

    def test_run_base_shear_happy(self):
        ctx = _ctx()
        raw = _run(run_base_shear(ctx, _args(Cs=0.1, W=5000.0)))
        d = _ok_tool(raw)
        assert abs(d["V_kN"] - 500.0) < 0.01

    def test_run_base_shear_bad_json(self):
        ctx = _ctx()
        raw = _run(run_base_shear(ctx, b"{{bad"))
        _err_tool(raw)

    def test_run_vertical_distribution_happy(self):
        ctx = _ctx()
        raw = _run(run_vertical_distribution(ctx, _args(
            V=1000.0,
            W_stories=[500.0, 500.0, 500.0],
            h_stories=[3.0, 6.0, 9.0],
            T=0.5,
        )))
        d = _ok_tool(raw)
        assert len(d["Fx_kN"]) == 3
        assert abs(sum(d["Fx_kN"]) - 1000.0) < 0.01

    def test_run_vertical_distribution_missing_field(self):
        ctx = _ctx()
        raw = _run(run_vertical_distribution(ctx, _args(
            V=1000.0, W_stories=[500.0], T=0.5  # missing h_stories
        )))
        _err_tool(raw)

    def test_run_story_shear_overturning_happy(self):
        ctx = _ctx()
        raw = _run(run_story_shear_overturning(ctx, _args(
            Fx=[200.0, 300.0, 500.0],
            h_stories=[3.5, 7.0, 10.5],
        )))
        d = _ok_tool(raw)
        assert abs(d["Vx_kN"][0] - 1000.0) < 0.01
        assert abs(d["Mx_kNm"][-1]) < 1e-9

    def test_run_story_shear_overturning_bad_json(self):
        ctx = _ctx()
        raw = _run(run_story_shear_overturning(ctx, b"}bad"))
        _err_tool(raw)

    def test_run_drift_stability_happy(self):
        ctx = _ctx()
        raw = _run(run_drift_stability(ctx, _args(
            delta_xe=[0.002, 0.004],
            Cd=5.0, Ie=1.0,
            Px=[2000.0, 1000.0],
            Vx=[600.0, 350.0],
            hsx=[3.5, 3.5],
        )))
        d = _ok_tool(raw)
        assert len(d["Delta_x_m"]) == 2
        assert len(d["theta"]) == 2

    def test_run_drift_stability_missing_Cd(self):
        ctx = _ctx()
        raw = _run(run_drift_stability(ctx, _args(
            delta_xe=[0.002], Ie=1.0,
            Px=[2000.0], Vx=[600.0], hsx=[3.5],
        )))
        _err_tool(raw)

    def test_run_sdof_displacement_happy(self):
        ctx = _ctx()
        raw = _run(run_sdof_displacement(ctx, _args(Sa_g=0.5, T=1.0)))
        d = _ok_tool(raw)
        assert d["Sd_m"] > 0
        assert d["Sd_mm"] > 0

    def test_run_sdof_displacement_bad_json(self):
        ctx = _ctx()
        raw = _run(run_sdof_displacement(ctx, b"not-valid"))
        _err_tool(raw)
