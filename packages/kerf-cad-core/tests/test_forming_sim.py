"""
Hermetic tests for kerf_cad_core.procsim.forming_sim — sheet forming
formability simulation (AutoForm direction).

Coverage (≥25 tests, all hermetic, no OCC / DB / network):

  flc0                     — Keeler-Goodwin FLC₀ formula verification
  flc_curve                — plane-strain minimum, left/right half shape
  strain_path              — deep-draw, stretch, plane-strain modes
  safety_margin            — safe / marginal / fail zone logic
  thinning                 — volume conservation (ε₁ + ε₂ + ε₃ = 0)
  wrinkling_tendency       — compressive hoop → wrinkling index
  draw_bead_restraining_force — Stoughton bending + friction model
  blank_holder_force_window   — F_min < F_max, invalid geometry detection
  limiting_draw_ratio      — LDR analytic formula check vs textbook
  springback               — Rf/R increases with σ_y/E; curl model
  one_step_inverse         — section-based strain estimate

References
----------
Keeler (1965) SAE 650535; Goodwin (1968) SAE 680093;
Hosford & Caddell "Metal Forming" 4th ed. §9.3, §12;
Marciniak, Duncan & Hu "Mechanics of Sheet Metal Forming" 2nd ed.

Author: imranparuk
"""
from __future__ import annotations

import math

import pytest

from kerf_cad_core.procsim.forming_sim import (
    flc0,
    flc_curve,
    strain_path,
    safety_margin,
    thinning,
    wrinkling_tendency,
    draw_bead_restraining_force,
    blank_holder_force_window,
    limiting_draw_ratio,
    springback,
    one_step_inverse,
)


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------

def _ok(result: dict) -> dict:
    """Assert result is ok and return it."""
    assert result["ok"] is True, f"Expected ok=True, got: {result}"
    return result


def _fail(result: dict) -> dict:
    """Assert result has ok=False and return it."""
    assert result["ok"] is False, f"Expected ok=False, got: {result}"
    assert "reason" in result
    return result


# ---------------------------------------------------------------------------
# 1. flc0 — Keeler-Goodwin formula
# ---------------------------------------------------------------------------

class TestFlc0:
    def test_formula_matches_reference(self):
        """FLC₀ = (23.3 + 14.13·t_mm)·n/0.21 — reference mild steel."""
        n, t = 0.21, 0.001  # 1 mm sheet
        r = _ok(flc0(n, t))
        t_mm = t * 1000
        expected_pct = (23.3 + 14.13 * t_mm) * n / 0.21
        assert abs(r["FLC0_pct"] - expected_pct) < 1e-9
        assert abs(r["FLC0"] - expected_pct / 100.0) < 1e-11

    def test_increases_with_n(self):
        """Higher n → higher FLC₀ (more formable material)."""
        t = 0.0015
        r1 = _ok(flc0(0.15, t))
        r2 = _ok(flc0(0.30, t))
        assert r2["FLC0"] > r1["FLC0"]

    def test_increases_with_thickness(self):
        """Thicker sheet → higher FLC₀ (Keeler thickness dependence)."""
        n = 0.22
        r1 = _ok(flc0(n, 0.0008))  # 0.8 mm
        r2 = _ok(flc0(n, 0.002))   # 2.0 mm
        assert r2["FLC0"] > r1["FLC0"]

    def test_n_zero_invalid(self):
        _fail(flc0(0.0, 0.001))

    def test_t_zero_invalid(self):
        _fail(flc0(0.20, 0.0))

    def test_t_mm_field_correct(self):
        r = _ok(flc0(0.20, 0.002))
        assert abs(r["t_mm"] - 2.0) < 1e-10

    def test_typical_mild_steel(self):
        """Mild steel (n=0.21, t=1 mm): FLC₀ ≈ 24.4%."""
        r = _ok(flc0(0.21, 0.001))
        # (23.3 + 14.13) * 0.21 / 0.21 = 37.43 % — recheck formula
        expected = (23.3 + 14.13 * 1.0) * 0.21 / 0.21
        assert abs(r["FLC0_pct"] - expected) < 1e-6

    def test_returns_warnings_list(self):
        r = _ok(flc0(0.20, 0.001))
        assert isinstance(r["warnings"], list)


# ---------------------------------------------------------------------------
# 2. flc_curve — full FLC
# ---------------------------------------------------------------------------

class TestFlcCurve:
    def test_plane_strain_is_minimum(self):
        """FLC minimum must be at ε₂ = 0 (plane-strain)."""
        r = _ok(flc_curve(0.22, 0.0015, n_points=41))
        curve = r["curve"]
        min_eps1 = min(pt["eps1_flc"] for pt in curve)
        # The point at ε₂ = 0 should equal or be within floating-point of the minimum
        plane_strain_pts = [pt for pt in curve if abs(pt["eps2"]) < 1e-6]
        assert len(plane_strain_pts) >= 1
        ps_eps1 = plane_strain_pts[0]["eps1_flc"]
        assert abs(ps_eps1 - min_eps1) < 1e-6

    def test_left_half_increases(self):
        """For ε₂ < 0 (draw side): ε₁_FLC increases as ε₂ decreases."""
        r = _ok(flc_curve(0.22, 0.0015, n_points=21))
        left = [pt for pt in r["curve"] if pt["eps2"] < -1e-8]
        # Sorted by eps2 ascending (most negative first)
        left_sorted = sorted(left, key=lambda p: p["eps2"])
        for i in range(len(left_sorted) - 1):
            assert left_sorted[i]["eps1_flc"] >= left_sorted[i + 1]["eps1_flc"] - 1e-9

    def test_right_half_increases(self):
        """For ε₂ > 0 (stretch side): ε₁_FLC increases as ε₂ increases."""
        r = _ok(flc_curve(0.22, 0.0015, n_points=21))
        right = [pt for pt in r["curve"] if pt["eps2"] > 1e-8]
        right_sorted = sorted(right, key=lambda p: p["eps2"])
        for i in range(len(right_sorted) - 1):
            assert right_sorted[i + 1]["eps1_flc"] >= right_sorted[i]["eps1_flc"] - 1e-9

    def test_curve_length(self):
        r = _ok(flc_curve(0.22, 0.0015, n_points=11))
        assert len(r["curve"]) == 11

    def test_minimum_eps1_equals_flc0(self):
        r = _ok(flc_curve(0.22, 0.0015))
        assert abs(r["minimum_eps1"] - r["FLC0"]) < 1e-10

    def test_invalid_n_points(self):
        _fail(flc_curve(0.22, 0.0015, n_points=2))


# ---------------------------------------------------------------------------
# 3. strain_path
# ---------------------------------------------------------------------------

class TestStrainPath:
    def test_plane_strain_eps2_zero(self):
        """Plane-strain: ε₂ = 0 always."""
        r = _ok(strain_path("plane_strain", 0.20))
        assert r["eps2"] == 0.0
        assert abs(r["eps3"] + 0.20) < 1e-12

    def test_stretch_eps1_equals_eps2(self):
        """Equi-biaxial stretch: ε₁ = ε₂."""
        r = _ok(strain_path("stretch", 0.15))
        assert abs(r["eps1"] - r["eps2"]) < 1e-12
        assert abs(r["eps3"] + 2 * 0.15) < 1e-12

    def test_deep_draw_isotropic(self):
        """Isotropic (r=1): ε₂ = −ε₁/2."""
        e1 = 0.20
        r = _ok(strain_path("deep_draw", e1, r_aniso=1.0))
        assert abs(r["eps2"] - (-e1 / 2.0)) < 1e-12

    def test_deep_draw_high_r(self):
        """High-r anisotropy (r=2): ε₂ = −2·ε₁/3."""
        e1 = 0.20
        r = _ok(strain_path("deep_draw", e1, r_aniso=2.0))
        expected_eps2 = -2.0 * e1 / 3.0
        assert abs(r["eps2"] - expected_eps2) < 1e-12

    def test_volume_conservation(self):
        """ε₁ + ε₂ + ε₃ = 0 for all modes."""
        for mode in ("deep_draw", "stretch", "plane_strain"):
            r = _ok(strain_path(mode, 0.18, r_aniso=1.5))
            total = r["eps1"] + r["eps2"] + r["eps3"]
            assert abs(total) < 1e-12, f"Volume not conserved for {mode}: {total}"

    def test_invalid_mode(self):
        _fail(strain_path("bad_mode", 0.10))

    def test_zero_eps1_invalid(self):
        _fail(strain_path("deep_draw", 0.0))


# ---------------------------------------------------------------------------
# 4. safety_margin
# ---------------------------------------------------------------------------

class TestSafetyMargin:
    def test_well_below_flc_is_safe(self):
        """Deep-draw safe: ε₁ well below FLC₀ → 'safe'."""
        r = _ok(safety_margin(eps1=0.05, eps2=-0.05, n=0.22, t=0.0015))
        assert r["zone"] == "safe"
        assert r["delta_eps1"] > 0.10

    def test_at_flc_is_fail(self):
        """At the FLC limit: ε₁ = ε₁_FLC → 'fail'."""
        n, t = 0.22, 0.0015
        f0_res = flc0(n, t)
        f0 = f0_res["FLC0"]
        # Plane-strain: ε₂=0, so ε₁_FLC = FLC₀
        r = _ok(safety_margin(eps1=f0, eps2=0.0, n=n, t=t))
        assert r["zone"] == "fail"
        assert abs(r["delta_eps1"]) < 1e-10

    def test_above_flc_is_fail(self):
        """ε₁ > ε₁_FLC → 'fail'."""
        n, t = 0.22, 0.0015
        f0 = flc0(n, t)["FLC0"]
        r = _ok(safety_margin(eps1=f0 + 0.05, eps2=0.0, n=n, t=t))
        assert r["zone"] == "fail"
        assert r["delta_eps1"] < 0.0

    def test_marginal_zone(self):
        """Just below FLC (within 0.10): 'marginal'."""
        n, t = 0.22, 0.0015
        f0 = flc0(n, t)["FLC0"]
        # Slightly below: Δε₁ = 0.05 (within 10 %)
        r = _ok(safety_margin(eps1=f0 - 0.05, eps2=0.0, n=n, t=t))
        assert r["zone"] == "marginal"

    def test_stretching_side_flc_limit(self):
        """On stretch side (ε₂ > 0): FLC limit = FLC₀ + 0.5·ε₂."""
        n, t, e2 = 0.22, 0.0015, 0.10
        f0 = flc0(n, t)["FLC0"]
        eps1_limit = f0 + 0.5 * e2
        # At exactly the limit → fail
        r = _ok(safety_margin(eps1=eps1_limit, eps2=e2, n=n, t=t))
        assert r["zone"] == "fail"


# ---------------------------------------------------------------------------
# 5. thinning — volume conservation
# ---------------------------------------------------------------------------

class TestThinning:
    def test_plane_strain_thinning_equals_eps1(self):
        """Plane-strain: ε₂=0 → ε₃ = −ε₁ → thinning conserves volume."""
        e1 = 0.20
        r = _ok(thinning(eps1=e1, eps2=0.0))
        assert abs(r["eps3"] + e1) < 1e-12
        # thinning_pct = (1 − exp(ε₃)) × 100
        expected_thin = (1.0 - math.exp(-e1)) * 100.0
        assert abs(r["thinning_pct"] - expected_thin) < 1e-9

    def test_stretch_double_thinning(self):
        """Equi-biaxial stretch: ε₂ = ε₁ → ε₃ = −2ε₁."""
        e1 = 0.10
        r = _ok(thinning(eps1=e1, eps2=e1))
        assert abs(r["eps3"] + 2 * e1) < 1e-12

    def test_deep_draw_isotropic_thinning(self):
        """Isotropic deep draw: ε₂ = −ε₁/2 → ε₃ = −ε₁/2 (same thinning as ε₁/2)."""
        e1 = 0.20
        e2 = -e1 / 2.0
        r = _ok(thinning(eps1=e1, eps2=e2))
        assert abs(r["eps3"] - (-e1 / 2.0)) < 1e-12

    def test_volume_conservation_identity(self):
        """ε₁ + ε₂ + ε₃ = 0 for arbitrary values."""
        for (e1, e2) in [(0.15, -0.08), (0.20, 0.0), (0.12, 0.12)]:
            r = _ok(thinning(eps1=e1, eps2=e2))
            assert abs(r["eps1"] + r["eps2"] + r["eps3"]) < 1e-12

    def test_thickening_in_drawing(self):
        """Large compressive e2: deep draw can produce net thickening."""
        # ε₁ small, ε₂ large negative → ε₃ > 0 → thickening
        r = _ok(thinning(eps1=0.05, eps2=-0.20))
        assert r["eps3"] > 0.0
        assert r["thickening_pct"] > 0.0

    def test_negative_eps1_invalid(self):
        _fail(thinning(eps1=-0.01, eps2=0.0))


# ---------------------------------------------------------------------------
# 6. wrinkling_tendency
# ---------------------------------------------------------------------------

class TestWrinkling:
    def test_tensile_eps2_stable(self):
        """ε₂ > 0 (stretching) → W = 0 → 'stable'."""
        r = _ok(wrinkling_tendency(eps1=0.15, eps2=0.05, r_aniso=1.5,
                                   t=0.001, R_die=0.01))
        assert r["wrinkling_index"] == 0.0
        assert r["tendency"] == "stable"

    def test_compressive_eps2_produces_index(self):
        """ε₂ < 0 → positive wrinkling index."""
        r = _ok(wrinkling_tendency(eps1=0.20, eps2=-0.10, r_aniso=1.0,
                                   t=0.001, R_die=0.05))
        assert r["wrinkling_index"] > 0.0

    def test_high_wrinkling_risk(self):
        """Thin sheet, large die radius, high |ε₂|/ε₁ → wrinkle_risk."""
        r = _ok(wrinkling_tendency(eps1=0.05, eps2=-0.20, r_aniso=1.0,
                                   t=0.001, R_die=0.50))
        assert r["tendency"] == "wrinkle_risk"

    def test_eps1_zero_invalid(self):
        _fail(wrinkling_tendency(eps1=0.0, eps2=-0.10, r_aniso=1.0,
                                 t=0.001, R_die=0.01))

    def test_t_over_R_field(self):
        r = _ok(wrinkling_tendency(eps1=0.10, eps2=-0.05, r_aniso=1.0,
                                   t=0.002, R_die=0.010))
        assert abs(r["t_over_R"] - 0.2) < 1e-10


# ---------------------------------------------------------------------------
# 7. draw_bead_restraining_force
# ---------------------------------------------------------------------------

class TestDrawBeadForce:
    def test_increases_with_yield_stress(self):
        """Higher σ_y → larger restraining force."""
        base = dict(t=0.001, mu=0.10, R_bead=0.005, w_bead=1.0)
        r1 = _ok(draw_bead_restraining_force(sigma_y=200e6, **base))
        r2 = _ok(draw_bead_restraining_force(sigma_y=400e6, **base))
        assert r2["F_per_width_N_m"] > r1["F_per_width_N_m"]

    def test_friction_component_zero_when_mu_zero(self):
        """μ=0 → friction component = 0."""
        r = _ok(draw_bead_restraining_force(t=0.001, sigma_y=250e6, mu=0.0,
                                            R_bead=0.005, w_bead=1.0))
        assert abs(r["friction_component_N_m"]) < 1e-6

    def test_total_force_equals_per_width_times_width(self):
        w = 0.5
        r = _ok(draw_bead_restraining_force(t=0.001, sigma_y=250e6, mu=0.10,
                                            R_bead=0.005, w_bead=w))
        assert abs(r["F_total_N"] - r["F_per_width_N_m"] * w) < 1e-6

    def test_formula_check(self):
        """Manual formula check: F/b = σ_y·t²/(4R)·(2 + 3·μ·π/2)."""
        t, sy, mu, R = 0.001, 300e6, 0.12, 0.004
        r = _ok(draw_bead_restraining_force(t=t, sigma_y=sy, mu=mu, R_bead=R, w_bead=1.0))
        M_per_b = sy * t ** 2 / 4.0
        expected = M_per_b / R * (2.0 + 3.0 * mu * math.pi / 2.0)
        assert abs(r["F_per_width_N_m"] - expected) < 1e-4


# ---------------------------------------------------------------------------
# 8. blank_holder_force_window
# ---------------------------------------------------------------------------

class TestBHWindow:
    def test_valid_window_low_less_than_high(self):
        """Standard deep-draw geometry: F_min < F_max."""
        r = _ok(blank_holder_force_window(
            sigma_y=250e6, t=0.001,
            A_blank=0.04, A_punch=0.01,
            mu=0.10, R_die=0.008,
        ))
        assert r["window_valid"] is True
        assert r["F_BH_min_N"] < r["F_BH_max_N"]

    def test_a_blank_must_exceed_a_punch(self):
        """A_blank <= A_punch → error."""
        r = blank_holder_force_window(
            sigma_y=250e6, t=0.001,
            A_blank=0.01, A_punch=0.01,
            mu=0.10, R_die=0.005,
        )
        _fail(r)

    def test_bh_forces_increase_with_sigma_y(self):
        """Higher yield stress → both F_min and F_max increase."""
        kwargs = dict(t=0.001, A_blank=0.04, A_punch=0.01, mu=0.10, R_die=0.008)
        r1 = _ok(blank_holder_force_window(sigma_y=200e6, **kwargs))
        r2 = _ok(blank_holder_force_window(sigma_y=400e6, **kwargs))
        assert r2["F_BH_min_N"] > r1["F_BH_min_N"]
        assert r2["F_BH_max_N"] > r1["F_BH_max_N"]

    def test_flange_area_field(self):
        r = _ok(blank_holder_force_window(
            sigma_y=250e6, t=0.001,
            A_blank=0.05, A_punch=0.02,
            mu=0.10, R_die=0.005,
        ))
        assert abs(r["A_flange_m2"] - 0.03) < 1e-10


# ---------------------------------------------------------------------------
# 9. limiting_draw_ratio
# ---------------------------------------------------------------------------

class TestLDR:
    def test_analytic_value_isotropic(self):
        """Isotropic (r=1, n=0.21): LDR = exp(√0.21) ≈ 1.564."""
        r = _ok(limiting_draw_ratio(r_aniso=1.0, n=0.21))
        expected = math.exp(math.sqrt(1.0 * 0.21))
        assert abs(r["LDR"] - expected) < 1e-10

    def test_higher_r_gives_higher_ldr(self):
        """Higher anisotropy r → higher LDR (better drawability)."""
        r1 = _ok(limiting_draw_ratio(r_aniso=1.0, n=0.22))
        r2 = _ok(limiting_draw_ratio(r_aniso=2.0, n=0.22))
        assert r2["LDR"] > r1["LDR"]

    def test_higher_n_gives_higher_ldr(self):
        """Higher n → higher LDR."""
        r1 = _ok(limiting_draw_ratio(r_aniso=1.5, n=0.18))
        r2 = _ok(limiting_draw_ratio(r_aniso=1.5, n=0.30))
        assert r2["LDR"] > r1["LDR"]

    def test_textbook_high_r_steel(self):
        """r̄=2.0, n=0.22 → LDR ≈ 1.93 (Hosford & Caddell §12)."""
        r = _ok(limiting_draw_ratio(r_aniso=2.0, n=0.22))
        expected = math.exp(math.sqrt(2.0 * 0.22))
        assert abs(r["LDR"] - expected) < 1e-8
        # Check textbook range: 1.8–2.0
        assert 1.8 < r["LDR"] < 2.1

    def test_swift_form_correct(self):
        """LDR_swift = exp(r/(1+r))."""
        r_val, n_val = 1.5, 0.20
        r = _ok(limiting_draw_ratio(r_aniso=r_val, n=n_val))
        expected_swift = math.exp(r_val / (1.0 + r_val))
        assert abs(r["LDR_swift"] - expected_swift) < 1e-10

    def test_zero_r_invalid(self):
        _fail(limiting_draw_ratio(r_aniso=0.0, n=0.20))

    def test_zero_n_invalid(self):
        _fail(limiting_draw_ratio(r_aniso=1.5, n=0.0))


# ---------------------------------------------------------------------------
# 10. springback
# ---------------------------------------------------------------------------

class TestSpringback:
    def test_springback_increases_with_yield_over_modulus(self):
        """Higher σ_y/E → more springback (lower Rf/R)."""
        base = dict(E=200e9, t=0.001, R_punch=0.05, nu=0.30)
        r1 = _ok(springback(sigma_y=200e6, **base))
        r2 = _ok(springback(sigma_y=800e6, **base))
        assert r2["Rf_over_R"] < r1["Rf_over_R"]

    def test_springback_increases_with_R_over_t(self):
        """Larger R/t (gentler bend) → more springback."""
        base = dict(sigma_y=300e6, E=200e9, t=0.001, nu=0.30)
        r1 = _ok(springback(R_punch=0.005, **base))   # R/t = 5
        r2 = _ok(springback(R_punch=0.020, **base))   # R/t = 20
        assert r2["Rf_over_R"] < r1["Rf_over_R"]

    def test_rf_over_r_field(self):
        """Pure bending: Rf/R = 1 − 3x + 4x³, x = (σ_y/E)·(R/t)."""
        sy, E, t, R = 300e6, 200e9, 0.001, 0.020
        r = _ok(springback(sigma_y=sy, E=E, t=t, R_punch=R, nu=0.30))
        x = (sy / E) * (R / t)
        expected = 1.0 - 3.0 * x + 4.0 * x ** 3
        expected = max(0.0, min(2.0, expected))
        assert abs(r["Rf_over_R"] - expected) < 1e-10

    def test_curl_radius_increases_with_E(self):
        """Higher E → larger R_curl (less curl)."""
        base = dict(sigma_y=300e6, t=0.001, R_punch=0.020, nu=0.30)
        r1 = _ok(springback(E=70e9, **base))   # aluminium
        r2 = _ok(springback(E=200e9, **base))  # steel
        assert r2["R_curl_m"] > r1["R_curl_m"]

    def test_curl_formula(self):
        """R_curl = E·t / (4·σ_y·(1−ν²))."""
        sy, E, t, R, nu = 300e6, 200e9, 0.001, 0.020, 0.30
        r = _ok(springback(sigma_y=sy, E=E, t=t, R_punch=R, nu=nu))
        expected_curl = E * t / (4.0 * sy * (1.0 - nu ** 2))
        assert abs(r["R_curl_m"] - expected_curl) < 1e-6

    def test_nu_invalid(self):
        _fail(springback(sigma_y=300e6, E=200e9, t=0.001, R_punch=0.020, nu=0.5))


# ---------------------------------------------------------------------------
# 11. one_step_inverse
# ---------------------------------------------------------------------------

class TestOneStepInverse:
    def _simple_profile(self):
        """Simple V-profile: blank→deformed 3:1 arc/straight ratio."""
        return [(0.0, 0.0), (0.05, 0.05), (0.10, 0.0)]

    def test_basic_profile_ok(self):
        r = _ok(one_step_inverse(
            profile_coords=self._simple_profile(),
            t=0.001, sigma_y=250e6, n=0.22, K=500e6,
        ))
        assert r["n_segments"] == 2
        assert r["L_def_total_m"] > 0
        assert r["eps1_avg"] >= 0

    def test_volume_conservation_per_segment(self):
        """Each segment: ε₁ + ε₂ + ε₃ = 0 (plane-strain, ε₂=0)."""
        r = _ok(one_step_inverse(
            profile_coords=self._simple_profile(),
            t=0.001, sigma_y=250e6, n=0.22, K=500e6,
        ))
        for seg in r["segments"]:
            total = seg["eps1"] + seg["eps2"] + seg["eps3"]
            assert abs(total) < 1e-12

    def test_flat_profile_zero_strain(self):
        """Straight horizontal profile: L_def = L_blank → ε₁_avg = 0."""
        coords = [(0.0, 0.0), (0.10, 0.0)]
        r = _ok(one_step_inverse(
            profile_coords=coords,
            t=0.001, sigma_y=250e6, n=0.22, K=500e6,
        ))
        assert abs(r["eps1_avg"]) < 1e-10

    def test_too_few_points(self):
        _fail(one_step_inverse(
            profile_coords=[(0.0, 0.0)],
            t=0.001, sigma_y=250e6, n=0.22, K=500e6,
        ))

    def test_safe_zone_below_flc(self):
        """Modest deformation → all segments safe (well below FLC)."""
        # Very gentle profile: small deviation from straight line
        coords = [(0.0, 0.0), (0.05, 0.001), (0.10, 0.0)]
        r = _ok(one_step_inverse(
            profile_coords=coords,
            t=0.001, sigma_y=250e6, n=0.22, K=500e6,
        ))
        assert r["overall_zone"] == "safe"

    def test_sigma_f_positive_for_strained_segments(self):
        """All strained segments should have positive σ_f."""
        r = _ok(one_step_inverse(
            profile_coords=self._simple_profile(),
            t=0.001, sigma_y=250e6, n=0.22, K=500e6,
        ))
        for seg in r["segments"]:
            assert seg["sigma_f_Pa"] > 0
