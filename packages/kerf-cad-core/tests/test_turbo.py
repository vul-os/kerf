"""
Hermetic tests for kerf_cad_core.turbo — turbomachinery blade/stage design.

Coverage:
  stage.euler_work                    — Euler equation W = U·ΔCθ
  stage.velocity_triangles_axial      — axial stage velocity triangles
  stage.velocity_triangles_centrifugal — centrifugal impeller exit triangles
  stage.dimensionless_groups          — φ, ψ, power coefficient, Mach
  stage.specific_speed_diameter       — Ω_s, Δ_s, machine type
  stage.cordier_optimum               — Cordier-line Δ_s_opt
  stage.degree_of_reaction            — R = 1 − (Cθ1+Cθ2)/(2U)
  stage.axial_stage                   — full axial stage analysis
  stage.centrifugal_impeller          — impeller head, slip, NPSH
  stage.fan_affinity                  — affinity laws (speed + trim)
  stage.stage_efficiency              — η_is, η_p, reheat factor
  stage.surge_choke_margin            — SM, CM, surge/choke risk
  tools.*                             — LLM tool wrappers (happy + error paths)

All tests are pure-Python and hermetic: no OCC, no DB, no network.
Formulas verified against Dixon/Saravanamuttoo hand-calcs.

References
----------
Dixon, S.L. & Hall, C.A. "Fluid Mechanics and Thermodynamics of
  Turbomachinery", 7th ed., Butterworth-Heinemann (2014).
Saravanamuttoo, H.I.H. et al. "Gas Turbine Theory", 7th ed., Pearson (2017).

Author: imranparuk
"""
from __future__ import annotations

import asyncio
import json
import math
import uuid

import pytest

from kerf_cad_core.turbo.stage import (
    euler_work,
    velocity_triangles_axial,
    velocity_triangles_centrifugal,
    dimensionless_groups,
    specific_speed_diameter,
    cordier_optimum,
    degree_of_reaction,
    axial_stage,
    centrifugal_impeller,
    fan_affinity,
    stage_efficiency,
    surge_choke_margin,
)
from kerf_cad_core.turbo.tools import (
    run_turbo_euler_work,
    run_turbo_velocity_triangles_axial,
    run_turbo_velocity_triangles_centrifugal,
    run_turbo_dimensionless_groups,
    run_turbo_specific_speed_diameter,
    run_turbo_cordier_optimum,
    run_turbo_degree_of_reaction,
    run_turbo_axial_stage,
    run_turbo_centrifugal_impeller,
    run_turbo_fan_affinity,
    run_turbo_stage_efficiency,
    run_turbo_surge_choke_margin,
)

REL = 1e-6


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


def _ok(raw: str) -> dict:
    d = json.loads(raw)
    assert d.get("ok") is True, f"Expected ok=True, got: {d}"
    return d


def _err(raw: str) -> dict:
    d = json.loads(raw)
    is_ok_false = d.get("ok") is False
    is_err_payload = "error" in d and "code" in d
    assert is_ok_false or is_err_payload, f"Expected error response, got: {d}"
    return d


# ===========================================================================
# 1. euler_work
# ===========================================================================

class TestEulerWork:

    def test_basic_compressor(self):
        """W = U · ΔCθ — basic identity check."""
        U, dCt = 200.0, 80.0
        res = euler_work(U, dCt)
        assert res["ok"] is True
        assert abs(res["W_specific"] - U * dCt) < REL

    def test_turbine_negative_dCtheta(self):
        """Turbine convention: ΔCθ < 0 → W < 0."""
        res = euler_work(250.0, -100.0)
        assert res["ok"] is True
        assert res["W_specific"] == pytest.approx(-25000.0)

    def test_zero_dCtheta_gives_warning(self):
        """ΔCθ = 0 → W = 0, warning about zero energy transfer."""
        res = euler_work(200.0, 0.0)
        assert res["ok"] is True
        assert res["W_specific"] == 0.0
        assert len(res["warnings"]) > 0

    def test_negative_U_returns_error(self):
        res = euler_work(-100.0, 50.0)
        assert res["ok"] is False

    def test_zero_U_returns_error(self):
        res = euler_work(0.0, 50.0)
        assert res["ok"] is False

    def test_fields_present(self):
        res = euler_work(180.0, 60.0)
        assert "U_m_s" in res
        assert "dCtheta_m_s" in res
        assert abs(res["U_m_s"] - 180.0) < REL


# ===========================================================================
# 2. velocity_triangles_axial
# ===========================================================================

class TestVelocityTrianglesAxial:

    def test_axial_entry_alpha1_zero(self):
        """
        Axial entry (α1=0): Cθ1=0, W1 = √(U² + Ca²), β1 = atan(−U/Ca).
        Dixon §3.2 worked example template.
        """
        U, Ca = 200.0, 150.0
        res = velocity_triangles_axial(U, Ca, 0.0, 20.0)
        assert res["ok"] is True
        assert abs(res["Ctheta1_m_s"]) < REL
        assert abs(res["C1_m_s"] - Ca) < 1e-9  # C1 = Ca when α1=0
        # W1 = sqrt(U² + Ca²)
        W1_expected = math.sqrt(U**2 + Ca**2)
        assert abs(res["W1_m_s"] - W1_expected) / W1_expected < REL

    def test_velocity_triangle_closure(self):
        """
        Vector closure: C = W + U (in the tangential direction).
        Cθ = Wθ + U.
        """
        U, Ca = 250.0, 180.0
        res = velocity_triangles_axial(U, Ca, 0.0, 30.0)
        assert res["ok"] is True
        b2 = math.radians(res["beta2_deg"])
        Wt2 = Ca * math.tan(b2)
        Ct2 = Wt2 + U
        assert abs(Ct2 - res["Ctheta2_m_s"]) < 1e-8

    def test_euler_work_consistent(self):
        """W_specific = U · dCtheta, consistent with euler_work()."""
        U, Ca = 200.0, 150.0
        res = velocity_triangles_axial(U, Ca, 0.0, 25.0)
        assert res["ok"] is True
        W_euler = euler_work(U, res["dCtheta_m_s"])
        assert abs(res["W_specific"] - W_euler["W_specific"]) < 1e-8

    def test_symmetric_50pct_reaction(self):
        """
        For 50% reaction stage: α1 = β2, α2 = β1 (symmetric triangles).
        Dixon §3.5.
        """
        # 50% reaction: Cθ1 + Cθ2 = U
        # Choose Ca=150, U=200, set α1 such that Cθ1 = 25 (and Cθ2 = 175)
        # R = 1 - (Cθ1+Cθ2)/(2U) = 1 - 200/400 = 0.5
        U, Ca = 200.0, 150.0
        # Cθ1 = 25, α1 = atan(25/150)
        # Cθ2 = 175, α2 = atan(175/150)
        alpha1 = math.degrees(math.atan(25.0 / 150.0))
        alpha2 = math.degrees(math.atan(175.0 / 150.0))
        res = velocity_triangles_axial(U, Ca, alpha1, alpha2)
        assert res["ok"] is True
        R = 1.0 - (res["Ctheta1_m_s"] + res["Ctheta2_m_s"]) / (2.0 * U)
        assert abs(R - 0.5) < 1e-6

    def test_angle_out_of_range_returns_error(self):
        res = velocity_triangles_axial(200.0, 150.0, 89.5, 20.0)
        assert res["ok"] is False

    def test_negative_Ca_returns_error(self):
        res = velocity_triangles_axial(200.0, -10.0, 0.0, 20.0)
        assert res["ok"] is False

    def test_absolute_velocity_magnitude(self):
        """C2 = sqrt(Ca² + Cθ2²)."""
        U, Ca = 220.0, 160.0
        res = velocity_triangles_axial(U, Ca, 0.0, 28.0)
        assert res["ok"] is True
        C2_expected = math.sqrt(Ca**2 + res["Ctheta2_m_s"]**2)
        assert abs(res["C2_m_s"] - C2_expected) < 1e-9


# ===========================================================================
# 3. velocity_triangles_centrifugal
# ===========================================================================

class TestVelocityTrianglesCentrifugal:

    def test_ideal_whirl_formula(self):
        """
        Cθ2_ideal = U2 + Cr2 · tan(β2_rad).
        For β2 = −30°: tan(−30°) = −1/√3 ≈ −0.5774.
        Dixon §7.2.
        """
        U2, Cr2, beta2 = 300.0, 50.0, -30.0
        res = velocity_triangles_centrifugal(U2, Cr2, beta2_deg=beta2, slip_factor=1.0)
        assert res["ok"] is True
        Ct2_ideal_expected = U2 + Cr2 * math.tan(math.radians(beta2))
        assert abs(res["Ctheta2_ideal_m_s"] - Ct2_ideal_expected) / abs(Ct2_ideal_expected) < REL

    def test_slip_factor_reduces_whirl(self):
        """Actual whirl = σ · ideal whirl."""
        U2, Cr2, beta2, sigma = 300.0, 50.0, -30.0, 0.85
        res = velocity_triangles_centrifugal(U2, Cr2, beta2_deg=beta2, slip_factor=sigma)
        assert res["ok"] is True
        assert abs(res["Ctheta2_actual_m_s"] - sigma * res["Ctheta2_ideal_m_s"]) < 1e-9

    def test_euler_work_with_slip(self):
        """W_actual = U2 · Cθ2_actual."""
        U2, Cr2, beta2, sigma = 300.0, 50.0, -30.0, 0.88
        res = velocity_triangles_centrifugal(U2, Cr2, beta2_deg=beta2, slip_factor=sigma)
        assert res["ok"] is True
        W_expected = U2 * res["Ctheta2_actual_m_s"]
        assert abs(res["W_specific_actual"] - W_expected) < 1e-6

    def test_default_slip_factor_is_0p9(self):
        """Default slip factor σ = 0.9."""
        res = velocity_triangles_centrifugal(300.0, 50.0, beta2_deg=-30.0)
        assert res["ok"] is True
        assert res["slip_factor"] == pytest.approx(0.9)

    def test_slip_factor_gt_1_returns_error(self):
        res = velocity_triangles_centrifugal(300.0, 50.0, slip_factor=1.1)
        assert res["ok"] is False

    def test_negative_U2_returns_error(self):
        res = velocity_triangles_centrifugal(-100.0, 50.0)
        assert res["ok"] is False

    def test_absolute_exit_velocity(self):
        """C2 = sqrt(Cr2² + Cθ2_actual²)."""
        U2, Cr2 = 300.0, 60.0
        res = velocity_triangles_centrifugal(U2, Cr2, beta2_deg=-25.0, slip_factor=0.9)
        assert res["ok"] is True
        C2_expected = math.sqrt(Cr2**2 + res["Ctheta2_actual_m_s"]**2)
        assert abs(res["C2_m_s"] - C2_expected) < 1e-9


# ===========================================================================
# 4. dimensionless_groups
# ===========================================================================

class TestDimensionlessGroups:

    def test_flow_coefficient_formula(self):
        """φ = Ca / U."""
        U, Ca = 200.0, 150.0
        res = dimensionless_groups(U, Ca, 80.0)
        assert res["ok"] is True
        assert abs(res["phi"] - Ca / U) < REL

    def test_loading_coefficient_formula(self):
        """ψ = ΔCθ / U."""
        U, Ca, dCt = 200.0, 150.0, 60.0
        res = dimensionless_groups(U, Ca, dCt)
        assert res["ok"] is True
        assert abs(res["psi"] - dCt / U) < REL

    def test_power_coefficient_formula(self):
        """C_P = φ · ψ."""
        U, Ca, dCt = 200.0, 150.0, 60.0
        res = dimensionless_groups(U, Ca, dCt)
        assert res["ok"] is True
        phi = Ca / U
        psi = dCt / U
        assert abs(res["power_coeff"] - phi * psi) < REL

    def test_blade_mach_number(self):
        """M_U = U / a."""
        U, Ca, dCt, a = 200.0, 150.0, 60.0, 340.0
        res = dimensionless_groups(U, Ca, dCt, blade_speed_sound=a)
        assert res["ok"] is True
        assert abs(res["blade_mach"] - U / a) < REL

    def test_high_phi_triggers_warning(self):
        """φ > 0.8 → warning."""
        res = dimensionless_groups(100.0, 90.0, 30.0)
        assert res["ok"] is True
        assert any("flow" in w.lower() or "phi" in w.lower() for w in res["warnings"])

    def test_high_psi_triggers_warning(self):
        """|ψ| > 0.5 → warning."""
        res = dimensionless_groups(100.0, 30.0, 60.0)
        assert res["ok"] is True
        assert any("loading" in w.lower() or "psi" in w.lower() for w in res["warnings"])

    def test_no_blade_mach_without_speed_of_sound(self):
        """blade_mach is None when blade_speed_sound is not provided."""
        res = dimensionless_groups(200.0, 150.0, 60.0)
        assert res["ok"] is True
        assert res["blade_mach"] is None


# ===========================================================================
# 5. specific_speed_diameter
# ===========================================================================

class TestSpecificSpeedDiameter:

    def test_omega_s_formula(self):
        """Ω_s = ω·√Q / (gH)^(3/4). Dixon §1.5."""
        Q, gH, omega = 0.05, 200.0, 150.0
        res = specific_speed_diameter(Q, gH, omega)
        assert res["ok"] is True
        Os_expected = omega * math.sqrt(Q) / gH**0.75
        assert abs(res["Omega_s"] - Os_expected) / Os_expected < REL

    def test_delta_s_formula(self):
        """Δ_s = D·(gH)^(1/4) / √Q."""
        Q, gH, omega, D = 0.05, 200.0, 150.0, 0.3
        res = specific_speed_diameter(Q, gH, omega, D=D)
        assert res["ok"] is True
        Ds_expected = D * gH**0.25 / math.sqrt(Q)
        assert abs(res["Delta_s"] - Ds_expected) / Ds_expected < REL

    def test_low_omega_s_is_radial(self):
        """Low Ω_s (low Q, high gH) → radial machine."""
        # Ω_s small: small Q, large gH
        res = specific_speed_diameter(Q=1e-4, gH=1000.0, omega=50.0)
        assert res["ok"] is True
        assert "radial" in res["machine_type"].lower()

    def test_high_omega_s_is_axial(self):
        """High Ω_s (high Q, low gH) → axial machine."""
        res = specific_speed_diameter(Q=2.0, gH=50.0, omega=100.0)
        assert res["ok"] is True
        assert "axial" in res["machine_type"].lower()

    def test_no_diameter_gives_none_delta_s(self):
        """Δ_s is None when D is not provided."""
        res = specific_speed_diameter(Q=0.05, gH=200.0, omega=150.0)
        assert res["ok"] is True
        assert res["Delta_s"] is None

    def test_zero_Q_returns_error(self):
        res = specific_speed_diameter(Q=0.0, gH=200.0, omega=150.0)
        assert res["ok"] is False


# ===========================================================================
# 6. cordier_optimum
# ===========================================================================

class TestCordierOptimum:

    def test_returns_positive_delta_s(self):
        """Δ_s_opt must be positive for any valid Ω_s."""
        for Os in (0.3, 1.0, 2.5, 5.0, 8.0):
            res = cordier_optimum(Os)
            assert res["ok"] is True
            assert res["Delta_s_opt"] > 0

    def test_decreasing_trend(self):
        """Δ_s_opt decreases as Ω_s increases (Cordier trend)."""
        res_low = cordier_optimum(0.5)
        res_high = cordier_optimum(5.0)
        assert res_low["Delta_s_opt"] > res_high["Delta_s_opt"]

    def test_extrapolation_warning(self):
        """Ω_s outside [0.2, 10.0] → extrapolation warning."""
        res = cordier_optimum(0.1)
        assert res["ok"] is True
        assert any("extrap" in w.lower() or "outside" in w.lower() for w in res["warnings"])

    def test_machine_type_axial_for_high_omega_s(self):
        res = cordier_optimum(5.0)
        assert res["ok"] is True
        assert "axial" in res["machine_type"].lower()

    def test_machine_type_radial_for_low_omega_s(self):
        res = cordier_optimum(0.5)
        assert res["ok"] is True
        assert "radial" in res["machine_type"].lower()

    def test_zero_omega_s_returns_error(self):
        res = cordier_optimum(0.0)
        assert res["ok"] is False


# ===========================================================================
# 7. degree_of_reaction
# ===========================================================================

class TestDegreeOfReaction:

    def test_50pct_reaction(self):
        """R = 0.5 for Cθ1 + Cθ2 = U. Dixon §3.5."""
        U = 200.0
        Ct1, Ct2 = 50.0, 150.0  # sum = 200 = U
        res = degree_of_reaction(Ct1, Ct2, U)
        assert res["ok"] is True
        assert abs(res["R"] - 0.5) < REL

    def test_impulse_stage_zero_reaction(self):
        """Impulse stage: Cθ1 + Cθ2 = 2U → R = 0."""
        U = 200.0
        res = degree_of_reaction(U, U, U)
        assert res["ok"] is True
        assert abs(res["R"]) < REL

    def test_negative_reaction_warning(self):
        """R < 0 → warning issued."""
        res = degree_of_reaction(300.0, 300.0, 200.0)
        assert res["ok"] is True
        assert res["R"] < 0
        assert len(res["warnings"]) > 0

    def test_formula_general(self):
        """R = 1 − (Ct1 + Ct2) / (2·U)."""
        Ct1, Ct2, U = 20.0, 80.0, 150.0
        expected = 1.0 - (Ct1 + Ct2) / (2.0 * U)
        res = degree_of_reaction(Ct1, Ct2, U)
        assert res["ok"] is True
        assert abs(res["R"] - expected) < REL

    def test_zero_U_returns_error(self):
        res = degree_of_reaction(50.0, 100.0, 0.0)
        assert res["ok"] is False


# ===========================================================================
# 8. axial_stage
# ===========================================================================

class TestAxialStage:

    def test_basic_compressor_stage(self):
        """Compressor stage returns diffusion factor and de Haller."""
        res = axial_stage(U=200.0, Ca=150.0, alpha1_deg=0.0, alpha2_deg=25.0)
        assert res["ok"] is True
        assert res["diffusion_factor"] is not None
        assert res["de_haller"] is not None
        assert res["W_specific"] > 0  # compressor adds work

    def test_de_haller_gt_0p72_no_stall_warning(self):
        """de Haller ratio > 0.72 → no stall warning expected."""
        # Use modest loading to keep W2/W1 well above 0.72
        res = axial_stage(U=200.0, Ca=150.0, alpha1_deg=0.0, alpha2_deg=15.0)
        assert res["ok"] is True
        assert res["de_haller"] > 0.72
        stall_warnings = [w for w in res["warnings"] if "stall" in w.lower() or "0.72" in w]
        assert len(stall_warnings) == 0

    def test_stall_warning_triggered(self):
        """High loading → de Haller < 0.72 → stall warning."""
        # Very high exit angle to force large diffusion
        res = axial_stage(U=200.0, Ca=150.0, alpha1_deg=0.0, alpha2_deg=50.0)
        assert res["ok"] is True
        # Check whether stall risk is flagged (either via de Haller or DF)
        all_warn = " ".join(res["warnings"])
        assert "0.72" in all_warn or "stall" in all_warn.lower() or "DF" in all_warn or "diffusion" in all_warn.lower()

    def test_turbine_no_diffusion_factor(self):
        """Turbine mode: diffusion_factor and de_haller should be None."""
        res = axial_stage(
            U=300.0, Ca=180.0, alpha1_deg=40.0, alpha2_deg=-10.0,
            is_compressor=False
        )
        assert res["ok"] is True
        assert res["diffusion_factor"] is None
        assert res["de_haller"] is None

    def test_degree_of_reaction_embedded(self):
        """axial_stage R must match standalone degree_of_reaction."""
        U, Ca, a1, a2 = 220.0, 160.0, 0.0, 22.0
        res_stage = axial_stage(U, Ca, a1, a2)
        vt = res_stage["velocity_triangles"]
        res_R = degree_of_reaction(vt["Ctheta1_m_s"], vt["Ctheta2_m_s"], U)
        assert abs(res_stage["R"] - res_R["R"]) < 1e-9

    def test_aspect_ratio_computed(self):
        """aspect_ratio = span/chord when both provided."""
        res = axial_stage(
            U=200.0, Ca=150.0, alpha1_deg=0.0, alpha2_deg=20.0,
            chord=0.08, span=0.40
        )
        assert res["ok"] is True
        assert abs(res["aspect_ratio"] - 0.40 / 0.08) < REL

    def test_reynolds_computed(self):
        """Re_blade > 0 when chord, span, nu provided."""
        res = axial_stage(
            U=200.0, Ca=150.0, alpha1_deg=0.0, alpha2_deg=20.0,
            chord=0.08, span=0.40, nu=1.46e-5
        )
        assert res["ok"] is True
        assert res["Re_blade"] is not None
        assert res["Re_blade"] > 0


# ===========================================================================
# 9. centrifugal_impeller
# ===========================================================================

class TestCentrifugalImpeller:

    def test_basic_water_pump(self):
        """Basic water pump: positive Euler head returned."""
        res = centrifugal_impeller(
            n_rpm=1450.0, D2_m=0.30, b2_m=0.025,
            D1_tip_m=0.15, D1_hub_m=0.06,
        )
        assert res["ok"] is True
        assert res["H_euler_m"] > 0

    def test_tip_speed_formula(self):
        """U2 = ω · D2/2 = n_rpm · π/30 · D2/2."""
        n, D2 = 1450.0, 0.30
        omega = n * 2.0 * math.pi / 60.0
        U2_expected = omega * D2 / 2.0
        res = centrifugal_impeller(
            n_rpm=n, D2_m=D2, b2_m=0.025,
            D1_tip_m=0.15, D1_hub_m=0.06,
        )
        assert res["ok"] is True
        assert abs(res["U2_m_s"] - U2_expected) < 1e-9

    def test_stanitz_slip_factor(self):
        """Stanitz slip: σ = 1 − (π·sin|β2|) / Z."""
        beta2, Z = -30.0, 8
        b2_rad = abs(math.radians(beta2))
        sigma_expected = 1.0 - (math.pi * math.sin(b2_rad)) / Z
        sigma_expected = max(0.0, min(sigma_expected, 1.0))
        res = centrifugal_impeller(
            n_rpm=1450.0, D2_m=0.30, b2_m=0.025,
            D1_tip_m=0.15, D1_hub_m=0.06,
            beta2_deg=beta2, Z=Z, slip_model="stanitz",
        )
        assert res["ok"] is True
        assert abs(res["slip_factor"] - sigma_expected) < 1e-9

    def test_wiesner_slip_factor(self):
        """Wiesner slip: σ = 1 − √(sin|β2|) / Z^0.7."""
        beta2, Z = -30.0, 8
        b2_rad = abs(math.radians(beta2))
        sigma_expected = 1.0 - math.sqrt(math.sin(b2_rad)) / Z**0.7
        sigma_expected = max(0.0, min(sigma_expected, 1.0))
        res = centrifugal_impeller(
            n_rpm=1450.0, D2_m=0.30, b2_m=0.025,
            D1_tip_m=0.15, D1_hub_m=0.06,
            beta2_deg=beta2, Z=Z, slip_model="wiesner",
        )
        assert res["ok"] is True
        assert abs(res["slip_factor"] - sigma_expected) < 1e-9

    def test_npsh_inception_positive(self):
        """NPSH inception estimate must be > 0."""
        res = centrifugal_impeller(
            n_rpm=2900.0, D2_m=0.20, b2_m=0.015,
            D1_tip_m=0.10, D1_hub_m=0.04,
        )
        assert res["ok"] is True
        assert res["NPSH_inception_m"] > 0

    def test_D1_hub_ge_D1_tip_returns_error(self):
        res = centrifugal_impeller(
            n_rpm=1450.0, D2_m=0.30, b2_m=0.025,
            D1_tip_m=0.10, D1_hub_m=0.12,
        )
        assert res["ok"] is False

    def test_D1_tip_gt_D2_returns_error(self):
        res = centrifugal_impeller(
            n_rpm=1450.0, D2_m=0.20, b2_m=0.025,
            D1_tip_m=0.25, D1_hub_m=0.05,
        )
        assert res["ok"] is False

    def test_blade_count_lt_2_returns_error(self):
        res = centrifugal_impeller(
            n_rpm=1450.0, D2_m=0.30, b2_m=0.025,
            D1_tip_m=0.15, D1_hub_m=0.06, Z=1,
        )
        assert res["ok"] is False


# ===========================================================================
# 10. fan_affinity
# ===========================================================================

class TestFanAffinity:

    def test_speed_increase_scales_flow(self):
        """Q2 = Q1 · (n2/n1)."""
        Q1, n1, n2 = 2.0, 1450.0, 1750.0
        res = fan_affinity(Q1, 50.0, 5000.0, n1, n2)
        assert res["ok"] is True
        assert abs(res["Q2"] - Q1 * n2 / n1) / (Q1 * n2 / n1) < REL

    def test_speed_increase_scales_head_squared(self):
        """H2 = H1 · (n2/n1)²."""
        H1, n1, n2 = 50.0, 1450.0, 1750.0
        res = fan_affinity(2.0, H1, 5000.0, n1, n2)
        assert res["ok"] is True
        assert abs(res["H2"] - H1 * (n2 / n1)**2) / (H1 * (n2 / n1)**2) < REL

    def test_speed_increase_scales_power_cubed(self):
        """P2 = P1 · (n2/n1)³."""
        P1, n1, n2 = 5000.0, 1450.0, 1750.0
        res = fan_affinity(2.0, 50.0, P1, n1, n2)
        assert res["ok"] is True
        assert abs(res["P2"] - P1 * (n2 / n1)**3) / (P1 * (n2 / n1)**3) < REL

    def test_trim_reduces_flow_linearly(self):
        """Q2 = Q1 · (D2/D1) at constant speed."""
        Q1, D1, D2 = 2.0, 0.30, 0.27
        res = fan_affinity(Q1, 50.0, 5000.0, 1450.0, 1450.0, D1=D1, D2=D2)
        assert res["ok"] is True
        assert abs(res["Q2"] - Q1 * D2 / D1) / (Q1 * D2 / D1) < REL

    def test_same_speed_no_change(self):
        """n1 = n2, D1 = D2 → no change."""
        Q1, H1, P1, n = 2.0, 50.0, 5000.0, 1450.0
        res = fan_affinity(Q1, H1, P1, n, n, D1=0.3, D2=0.3)
        assert res["ok"] is True
        assert abs(res["Q2"] - Q1) < REL
        assert abs(res["H2"] - H1) < REL
        assert abs(res["P2"] - P1) < REL

    def test_excessive_trim_warning(self):
        """Trim ratio < 0.70 → warning."""
        res = fan_affinity(2.0, 50.0, 5000.0, 1450.0, 1450.0, D1=0.30, D2=0.20)
        assert res["ok"] is True
        assert any("trim" in w.lower() or "0.70" in w for w in res["warnings"])

    def test_D2_without_D1_returns_error(self):
        """Providing D2 without D1 is invalid."""
        res = fan_affinity(2.0, 50.0, 5000.0, 1450.0, 1750.0, D2=0.27)
        assert res["ok"] is False


# ===========================================================================
# 11. stage_efficiency
# ===========================================================================

class TestStageEfficiency:

    def test_isentropic_efficiency_compressor(self):
        """η_is = W_is / W_actual for compressor."""
        W_a, W_is = 120000.0, 100000.0
        res = stage_efficiency(W_a, W_is, stage_type="compressor")
        assert res["ok"] is True
        assert abs(res["eta_isentropic"] - W_is / W_a) < REL

    def test_isentropic_efficiency_turbine(self):
        """η_is = W_actual / W_is for turbine."""
        W_a, W_is = 90000.0, 100000.0
        res = stage_efficiency(W_a, W_is, stage_type="turbine")
        assert res["ok"] is True
        assert abs(res["eta_isentropic"] - W_a / W_is) < REL

    def test_polytropic_efficiency_compressor(self):
        """η_p = [(γ−1)/γ] / [(n−1)/n] for compressor."""
        gamma, n = 1.4, 1.6
        ratio_n = (n - 1.0) / n
        ratio_g = (gamma - 1.0) / gamma
        eta_p_expected = ratio_g / ratio_n
        res = stage_efficiency(
            W_actual=120000.0, W_isentropic=100000.0,
            polytropic_n=n, gamma=gamma, stage_type="compressor"
        )
        assert res["ok"] is True
        assert abs(res["eta_polytropic"] - eta_p_expected) < REL

    def test_polytropic_efficiency_turbine(self):
        """η_p = [(n−1)/n] / [(γ−1)/γ] for turbine."""
        gamma, n = 1.4, 1.3
        ratio_n = (n - 1.0) / n
        ratio_g = (gamma - 1.0) / gamma
        eta_p_expected = ratio_n / ratio_g
        res = stage_efficiency(
            W_actual=90000.0, W_isentropic=100000.0,
            polytropic_n=n, gamma=gamma, stage_type="turbine"
        )
        assert res["ok"] is True
        assert abs(res["eta_polytropic"] - eta_p_expected) < REL

    def test_small_stage_factor_greater_than_1(self):
        """Reheat/preheat factor f_r > 1 for non-ideal stage."""
        res = stage_efficiency(120000.0, 100000.0, stage_type="compressor")
        assert res["ok"] is True
        assert res["small_stage_factor"] > 1.0

    def test_perfect_isentropic_gives_fr_1(self):
        """η_is = 1.0 → f_r = 1.0."""
        res = stage_efficiency(100000.0, 100000.0, stage_type="compressor")
        assert res["ok"] is True
        assert abs(res["eta_isentropic"] - 1.0) < REL
        assert abs(res["small_stage_factor"] - 1.0) < REL

    def test_isothermal_polytropic_n_returns_error(self):
        """polytropic_n = 1.0 is invalid."""
        res = stage_efficiency(120000.0, 100000.0, polytropic_n=1.0)
        assert res["ok"] is False

    def test_negative_W_actual_returns_error(self):
        res = stage_efficiency(-100.0, 100000.0)
        assert res["ok"] is False

    def test_invalid_stage_type_returns_error(self):
        res = stage_efficiency(100000.0, 90000.0, stage_type="fan")
        assert res["ok"] is False


# ===========================================================================
# 12. surge_choke_margin
# ===========================================================================

class TestSurgeChokeMargin:

    def test_healthy_margins(self):
        """Operating well away from surge and choke → no risk flags."""
        res = surge_choke_margin(phi_op=0.5, phi_surge=0.3, phi_choke=0.9)
        assert res["ok"] is True
        assert res["surge_risk"] is False
        assert res["choke_risk"] is False

    def test_surge_margin_formula(self):
        """SM = (φ_op − φ_surge) / φ_op."""
        phi_op, phi_surge, phi_choke = 0.5, 0.3, 0.9
        SM_expected = (phi_op - phi_surge) / phi_op
        res = surge_choke_margin(phi_op=phi_op, phi_surge=phi_surge, phi_choke=phi_choke)
        assert res["ok"] is True
        assert abs(res["surge_margin"] - SM_expected) < REL

    def test_choke_margin_formula(self):
        """CM = (φ_choke − φ_op) / φ_op."""
        phi_op, phi_surge, phi_choke = 0.5, 0.3, 0.9
        CM_expected = (phi_choke - phi_op) / phi_op
        res = surge_choke_margin(phi_op=phi_op, phi_surge=phi_surge, phi_choke=phi_choke)
        assert res["ok"] is True
        assert abs(res["choke_margin"] - CM_expected) < REL

    def test_surge_condition_flagged(self):
        """SM < 0 → operating in surge → SURGE warning."""
        res = surge_choke_margin(phi_op=0.2, phi_surge=0.3, phi_choke=0.8)
        assert res["ok"] is True
        assert res["surge_risk"] is True
        assert any("surge" in w.lower() for w in res["warnings"])

    def test_low_surge_margin_warning(self):
        """SM < min_surge_margin (0.15) → warning."""
        # SM = (0.5 - 0.45) / 0.5 = 0.10 < 0.15
        res = surge_choke_margin(phi_op=0.5, phi_surge=0.45, phi_choke=0.9)
        assert res["ok"] is True
        assert res["surge_risk"] is True
        assert len(res["warnings"]) > 0

    def test_phi_choke_le_phi_op_returns_error(self):
        res = surge_choke_margin(phi_op=0.5, phi_surge=0.2, phi_choke=0.4)
        assert res["ok"] is False

    def test_zero_phi_op_returns_error(self):
        res = surge_choke_margin(phi_op=0.0, phi_surge=0.2, phi_choke=0.8)
        assert res["ok"] is False


# ===========================================================================
# 13. LLM tool wrappers
# ===========================================================================

class TestToolWrappers:

    def test_euler_work_happy_path(self):
        ctx = _ctx()
        raw = _run(run_turbo_euler_work(ctx, _args(U=200.0, dCtheta=80.0)))
        d = _ok(raw)
        assert abs(d["W_specific"] - 200.0 * 80.0) < REL

    def test_euler_work_missing_field(self):
        ctx = _ctx()
        raw = _run(run_turbo_euler_work(ctx, _args(U=200.0)))
        _err(raw)

    def test_euler_work_bad_json(self):
        ctx = _ctx()
        raw = _run(run_turbo_euler_work(ctx, b"not json"))
        _err(raw)

    def test_velocity_triangles_axial_happy_path(self):
        ctx = _ctx()
        raw = _run(run_turbo_velocity_triangles_axial(
            ctx, _args(U=200.0, Ca=150.0, alpha1_deg=0.0, alpha2_deg=25.0)
        ))
        d = _ok(raw)
        assert d["W_specific"] > 0
        assert "beta1_deg" in d

    def test_velocity_triangles_axial_missing_Ca(self):
        ctx = _ctx()
        raw = _run(run_turbo_velocity_triangles_axial(
            ctx, _args(U=200.0, alpha1_deg=0.0, alpha2_deg=25.0)
        ))
        _err(raw)

    def test_velocity_triangles_centrifugal_happy_path(self):
        ctx = _ctx()
        raw = _run(run_turbo_velocity_triangles_centrifugal(
            ctx, _args(U2=300.0, Cr2=50.0, beta2_deg=-30.0, slip_factor=0.88)
        ))
        d = _ok(raw)
        assert d["Ctheta2_actual_m_s"] > 0
        assert d["W_specific_actual"] > 0

    def test_velocity_triangles_centrifugal_default_slip(self):
        ctx = _ctx()
        raw = _run(run_turbo_velocity_triangles_centrifugal(
            ctx, _args(U2=300.0, Cr2=50.0)
        ))
        d = _ok(raw)
        assert d["slip_factor"] == pytest.approx(0.9)

    def test_dimensionless_groups_happy_path(self):
        ctx = _ctx()
        raw = _run(run_turbo_dimensionless_groups(
            ctx, _args(U=200.0, Ca=150.0, dCtheta=60.0)
        ))
        d = _ok(raw)
        assert abs(d["phi"] - 150.0 / 200.0) < REL
        assert abs(d["psi"] - 60.0 / 200.0) < REL

    def test_specific_speed_diameter_happy_path(self):
        ctx = _ctx()
        raw = _run(run_turbo_specific_speed_diameter(
            ctx, _args(Q=0.05, gH=200.0, omega=150.0, D=0.3)
        ))
        d = _ok(raw)
        assert d["Omega_s"] > 0
        assert d["Delta_s"] is not None

    def test_cordier_optimum_happy_path(self):
        ctx = _ctx()
        raw = _run(run_turbo_cordier_optimum(ctx, _args(Omega_s=1.5)))
        d = _ok(raw)
        assert d["Delta_s_opt"] > 0

    def test_cordier_optimum_missing_Omega_s(self):
        ctx = _ctx()
        raw = _run(run_turbo_cordier_optimum(ctx, _args()))
        _err(raw)

    def test_degree_of_reaction_happy_path(self):
        ctx = _ctx()
        raw = _run(run_turbo_degree_of_reaction(
            ctx, _args(Ctheta1=50.0, Ctheta2=150.0, U=200.0)
        ))
        d = _ok(raw)
        assert abs(d["R"] - 0.5) < REL

    def test_axial_stage_happy_path(self):
        ctx = _ctx()
        raw = _run(run_turbo_axial_stage(
            ctx, _args(U=200.0, Ca=150.0, alpha1_deg=0.0, alpha2_deg=20.0)
        ))
        d = _ok(raw)
        assert d["W_specific"] > 0
        assert "R" in d

    def test_centrifugal_impeller_happy_path(self):
        ctx = _ctx()
        raw = _run(run_turbo_centrifugal_impeller(ctx, _args(
            n_rpm=1450.0, D2_m=0.30, b2_m=0.025,
            D1_tip_m=0.15, D1_hub_m=0.06,
        )))
        d = _ok(raw)
        assert d["H_euler_m"] > 0
        assert d["NPSH_inception_m"] > 0

    def test_centrifugal_impeller_missing_D1_hub(self):
        ctx = _ctx()
        raw = _run(run_turbo_centrifugal_impeller(ctx, _args(
            n_rpm=1450.0, D2_m=0.30, b2_m=0.025, D1_tip_m=0.15,
        )))
        _err(raw)

    def test_fan_affinity_happy_path(self):
        ctx = _ctx()
        raw = _run(run_turbo_fan_affinity(ctx, _args(
            Q1=2.0, H1=50.0, P1=5000.0, n1=1450.0, n2=1750.0
        )))
        d = _ok(raw)
        expected_Q2 = 2.0 * 1750.0 / 1450.0
        assert abs(d["Q2"] - expected_Q2) / expected_Q2 < REL

    def test_fan_affinity_missing_n2(self):
        ctx = _ctx()
        raw = _run(run_turbo_fan_affinity(ctx, _args(
            Q1=2.0, H1=50.0, P1=5000.0, n1=1450.0
        )))
        _err(raw)

    def test_stage_efficiency_happy_path(self):
        ctx = _ctx()
        raw = _run(run_turbo_stage_efficiency(ctx, _args(
            W_actual=120000.0, W_isentropic=100000.0
        )))
        d = _ok(raw)
        assert abs(d["eta_isentropic"] - 100000.0 / 120000.0) < REL

    def test_stage_efficiency_turbine_mode(self):
        ctx = _ctx()
        raw = _run(run_turbo_stage_efficiency(ctx, _args(
            W_actual=90000.0, W_isentropic=100000.0, stage_type="turbine"
        )))
        d = _ok(raw)
        assert abs(d["eta_isentropic"] - 0.9) < REL

    def test_surge_choke_margin_happy_path(self):
        ctx = _ctx()
        raw = _run(run_turbo_surge_choke_margin(ctx, _args(
            phi_op=0.5, phi_surge=0.3, phi_choke=0.9
        )))
        d = _ok(raw)
        assert d["surge_risk"] is False
        assert d["choke_risk"] is False

    def test_surge_choke_margin_surge_detected(self):
        ctx = _ctx()
        raw = _run(run_turbo_surge_choke_margin(ctx, _args(
            phi_op=0.2, phi_surge=0.3, phi_choke=0.8
        )))
        d = _ok(raw)
        assert d["surge_risk"] is True

    def test_surge_choke_margin_invalid_phi_choke(self):
        ctx = _ctx()
        raw = _run(run_turbo_surge_choke_margin(ctx, _args(
            phi_op=0.5, phi_surge=0.3, phi_choke=0.4
        )))
        _err(raw)
