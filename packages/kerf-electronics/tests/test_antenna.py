"""
Hermetic tests for the antenna element design module.

All tests are checked against hand-calculations from:
  - Balanis, C.A., "Antenna Theory", 4th ed. (Wiley, 2016)
  - Kraus, J.D. & Marhefka, R.J., "Antennas for All Applications", 3rd ed. (McGraw-Hill, 2002)
  - Pozar, D.M., "Microwave Engineering", 4th ed. (Wiley, 2012)

Author: imranparuk
"""
from __future__ import annotations

import importlib.util
import json
import math
import os
import sys
import types
import warnings

# ── Prefer the real kerf_chat if installed; stub otherwise ───────────────────
try:
    import kerf_chat as _kc_pkg  # noqa: F401
    import kerf_chat.tools as _kc_tools  # noqa: F401
    import kerf_chat.tools.registry as _kc_real  # noqa: F401
except Exception:
    _kc_real = None

_reg_stub = types.ModuleType("kerf_chat.tools.registry")
_reg_stub.Registry = type("Registry", (list,), {})
_reg_stub.ToolSpec = type(
    "ToolSpec", (), {"__init__": lambda s, **kw: s.__dict__.update(kw)}
)
_reg_stub.err_payload = lambda msg, code: json.dumps(
    {"ok": False, "error": msg, "code": code}
)
_reg_stub.ok_payload = lambda v: json.dumps({"ok": True, **v})
_reg_stub.register = lambda spec, write=False: (lambda fn: fn)

_kerf_chat_stub = types.ModuleType("kerf_chat")
_kerf_chat_tools_stub = types.ModuleType("kerf_chat.tools")
sys.modules.setdefault("kerf_chat", _kerf_chat_stub)
sys.modules.setdefault("kerf_chat.tools", _kerf_chat_tools_stub)
if _kc_real is None:
    sys.modules["kerf_chat.tools.registry"] = _reg_stub

# ── Ensure src/ is on path ────────────────────────────────────────────────────
_HERE = os.path.dirname(os.path.abspath(__file__))
_SRC = os.path.join(os.path.dirname(_HERE), "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

import pytest

from kerf_electronics.antenna.element import (
    aperture_efficiency,
    array_factor_ula,
    beamwidth_directivity,
    directivity_gain_efficiency,
    ground_plane_image,
    half_wave_dipole,
    helical_axial,
    horn_gain,
    microstrip_patch,
    monopole,
    near_far_field_boundary,
    polarization_axial_ratio,
    small_loop,
    vswr_bandwidth_from_q,
    yagi_uda,
)
import kerf_electronics.antenna.tools as _antenna_tools


# ═══════════════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════════════

_C = 2.997924580e8


def _lam(f):
    return _C / f


# ═══════════════════════════════════════════════════════════════════════════════
# 1. half_wave_dipole
# ═══════════════════════════════════════════════════════════════════════════════

def test_dipole_resonant_length_at_300mhz():
    """Resonant length at 300 MHz = 0.4786 × λ (shortening factor)."""
    result = half_wave_dipole(300e6)
    assert result["ok"]
    lam = _lam(300e6)
    # 0.4786 × λ, tolerance 1% (accounts for exact value of c used)
    expected = 0.4786 * lam
    assert abs(result["resonant_length_m"] - expected) < expected * 0.01


def test_dipole_half_wave_length_at_300mhz():
    """Half-wave length at 300 MHz = λ/2."""
    result = half_wave_dipole(300e6)
    assert result["ok"]
    lam = _lam(300e6)
    assert abs(result["half_wave_length_m"] - 0.5 * lam) < 1e-4


def test_dipole_input_resistance():
    """Thin half-wave dipole Rin ≈ 73.1 Ω (Balanis Table 4.2)."""
    result = half_wave_dipole(1e9)
    assert result["ok"]
    assert abs(result["R_in_ohm"] - 73.1) < 0.2


def test_dipole_gain_dbi():
    """Half-wave dipole gain = 2.15 dBi (η=1.0, D=1.643)."""
    result = half_wave_dipole(1e9, efficiency=1.0)
    assert result["ok"]
    assert abs(result["gain_dbi"] - 2.15) < 0.05


def test_dipole_gain_dbd():
    """Half-wave dipole gain referenced to dipole = 0 dBd."""
    result = half_wave_dipole(1e9, efficiency=1.0)
    assert result["ok"]
    assert abs(result["gain_dbd"]) < 0.1


def test_dipole_efficiency_scales_gain():
    """η=0.5 should reduce gain by 3 dB compared to η=1."""
    r1 = half_wave_dipole(1e9, efficiency=1.0)
    r2 = half_wave_dipole(1e9, efficiency=0.5)
    assert r1["ok"] and r2["ok"]
    assert abs(r1["gain_dbi"] - r2["gain_dbi"] - 3.01) < 0.1


def test_dipole_invalid_freq():
    """Zero frequency → ok=False."""
    result = half_wave_dipole(0)
    assert not result["ok"]


def test_dipole_efficiency_over_1():
    """Efficiency > 1.0 → ok=False."""
    result = half_wave_dipole(1e9, efficiency=1.1)
    assert not result["ok"]


def test_dipole_vswr_bw_positive():
    """VSWR bandwidth must be a positive Hz value."""
    result = half_wave_dipole(2.4e9)
    assert result["ok"]
    assert result["vswr_bw_hz"] > 0


# ═══════════════════════════════════════════════════════════════════════════════
# 2. monopole
# ═══════════════════════════════════════════════════════════════════════════════

def test_monopole_resonant_length_half_dipole():
    """Monopole resonant length = half of dipole resonant length."""
    d = half_wave_dipole(100e6)
    m = monopole(100e6)
    assert d["ok"] and m["ok"]
    assert abs(m["resonant_length_m"] - d["resonant_length_m"] / 2) < 1e-6


def test_monopole_rin_half_dipole():
    """Monopole Rin = 36.5 Ω (half of dipole 73.1 Ω)."""
    m = monopole(100e6)
    assert m["ok"]
    assert abs(m["R_in_ohm"] - 36.5) < 0.2


def test_monopole_gain_3db_above_dipole():
    """Monopole gain ≈ dipole gain + 3.01 dBi (image theory)."""
    d = half_wave_dipole(100e6, efficiency=1.0)
    m = monopole(100e6, efficiency=1.0)
    assert d["ok"] and m["ok"]
    assert abs(m["gain_dbi"] - (d["gain_dbi"] + 3.01)) < 0.05


def test_monopole_invalid_freq():
    """Negative frequency → ok=False."""
    result = monopole(-1e9)
    assert not result["ok"]


# ═══════════════════════════════════════════════════════════════════════════════
# 3. small_loop
# ═══════════════════════════════════════════════════════════════════════════════

def test_small_loop_radiation_resistance_scales_area_squared():
    """Radiation resistance scales as A²."""
    r1 = small_loop(100e6, loop_area_m2=1e-4)
    r2 = small_loop(100e6, loop_area_m2=2e-4)
    assert r1["ok"] and r2["ok"]
    # Rr ∝ A² → doubling A → ×4 Rr
    ratio = r2["radiation_resistance_ohm"] / r1["radiation_resistance_ohm"]
    assert abs(ratio - 4.0) < 0.05


def test_small_loop_radiation_resistance_scales_turns_squared():
    """Radiation resistance scales as N²."""
    r1 = small_loop(100e6, loop_area_m2=1e-4, n_turns=1)
    r4 = small_loop(100e6, loop_area_m2=1e-4, n_turns=4)
    assert r1["ok"] and r4["ok"]
    ratio = r4["radiation_resistance_ohm"] / r1["radiation_resistance_ohm"]
    assert abs(ratio - 16.0) < 0.5


def test_small_loop_directivity():
    """Small loop D = 1.5 (identical to short dipole)."""
    result = small_loop(100e6, loop_area_m2=1e-5)
    assert result["ok"]
    assert abs(result["directivity"] - 1.5) < 0.001


def test_small_loop_electrically_small_flag():
    """Very small area → electrically_small=True."""
    result = small_loop(100e6, loop_area_m2=1e-8)
    assert result["ok"]
    assert result["electrically_small"] is True


def test_small_loop_large_area_warning():
    """Large loop (ka ≥ 0.5) → warning issued, ok still True."""
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        result = small_loop(1e9, loop_area_m2=0.1)
    assert result["ok"]
    assert any("electrically small" in str(x.message).lower() for x in w)


def test_small_loop_invalid_turns():
    """n_turns=0 → ok=False."""
    result = small_loop(100e6, loop_area_m2=1e-4, n_turns=0)
    assert not result["ok"]


# ═══════════════════════════════════════════════════════════════════════════════
# 4. microstrip_patch
# ═══════════════════════════════════════════════════════════════════════════════

def test_patch_width_greater_than_length():
    """For typical εr, patch width W > length L (Balanis §14.2 design rule)."""
    r = microstrip_patch(2.4e9, er=4.4, h_m=1.6e-3)
    assert r["ok"]
    assert r["patch_width_m"] > r["patch_length_m"]


def test_patch_length_near_half_wave_in_substrate():
    """Patch length ≈ λ/(2 sqrt(εr_eff))."""
    freq = 2.4e9
    er = 4.4
    h = 1.6e-3
    r = microstrip_patch(freq, er=er, h_m=h)
    assert r["ok"]
    lam_eff = _C / (freq * math.sqrt(r["er_eff"]))
    expected_L = lam_eff / 2.0 - 2.0 * r["delta_L_m"]
    assert abs(r["patch_length_m"] - expected_L) < 1e-6


def test_patch_er_eff_between_1_and_er():
    """Effective permittivity 1 ≤ εr_eff ≤ εr."""
    r = microstrip_patch(5.8e9, er=10.2, h_m=0.635e-3)
    assert r["ok"]
    assert 1.0 <= r["er_eff"] <= 10.2


def test_patch_inset_feed_less_than_L():
    """Inset feed distance y₀ < patch length L."""
    r = microstrip_patch(2.4e9, er=4.4, h_m=1.6e-3)
    assert r["ok"]
    if r["inset_feed_m"] is not None:
        assert r["inset_feed_m"] < r["patch_length_m"]


def test_patch_edge_impedance_positive():
    """Edge impedance should be a positive value."""
    r = microstrip_patch(2.4e9, er=4.4, h_m=1.6e-3)
    assert r["ok"]
    assert r["edge_impedance_ohm"] > 0


def test_patch_invalid_er():
    """er = 0 → ok=False."""
    result = microstrip_patch(2.4e9, er=0, h_m=1.6e-3)
    assert not result["ok"]


def test_patch_gain_positive_dbi():
    """Patch gain should be positive dBi (directional over isotropic)."""
    r = microstrip_patch(2.4e9, er=4.4, h_m=1.6e-3)
    assert r["ok"]
    # Analytic two-slot model gives ~2-3 dBi directivity; full-wave would give ~6.6 dBi
    assert r["gain_dbi"] > 0.0


# ═══════════════════════════════════════════════════════════════════════════════
# 5. yagi_uda
# ═══════════════════════════════════════════════════════════════════════════════

def test_yagi_gain_increases_with_directors():
    """More directors → higher gain (use long-enough boom to avoid spacing compression)."""
    r1 = yagi_uda(144e6, n_directors=1, boom_wavelengths=0.6)
    r5 = yagi_uda(144e6, n_directors=5, boom_wavelengths=1.5)
    assert r1["ok"] and r5["ok"]
    assert r5["gain_dbi"] > r1["gain_dbi"]


def test_yagi_reflector_longer_than_driven():
    """Reflector length > driven element length (Balanis Table 10.6)."""
    r = yagi_uda(144e6)
    assert r["ok"]
    assert r["reflector_length_m"] > r["driven_length_m"]


def test_yagi_driven_length_near_half_wave():
    """Driven element ≈ 0.47 λ."""
    r = yagi_uda(144e6)
    assert r["ok"]
    lam = _lam(144e6)
    assert abs(r["driven_length_m"] - 0.47 * lam) < 1e-4


def test_yagi_n_elements_correct():
    """n_elements = 1 + 1 + n_directors."""
    r = yagi_uda(144e6, n_directors=4)
    assert r["ok"]
    assert r["n_elements"] == 6


def test_yagi_invalid_directors():
    """Negative n_directors → ok=False."""
    result = yagi_uda(144e6, n_directors=-1)
    assert not result["ok"]


# ═══════════════════════════════════════════════════════════════════════════════
# 6. helical_axial
# ═══════════════════════════════════════════════════════════════════════════════

def test_helical_gain_increases_with_turns():
    """More turns → higher gain."""
    r5 = helical_axial(2.4e9, n_turns=5)
    r10 = helical_axial(2.4e9, n_turns=10)
    assert r5["ok"] and r10["ok"]
    assert r10["gain_dbi"] > r5["gain_dbi"]


def test_helical_axial_ratio_approaches_1_for_many_turns():
    """Axial ratio AR = (2N+1)/(2N) → 1 as N → ∞."""
    r = helical_axial(2.4e9, n_turns=100)
    assert r["ok"]
    assert abs(r["axial_ratio"] - 1.0) < 0.02


def test_helical_in_axial_mode_range():
    """Standard design (C/λ=1, α=12.5°) → in_axial_mode_range=True."""
    r = helical_axial(2.4e9, n_turns=6, circumference_wavelengths=1.0, pitch_angle_deg=12.5)
    assert r["ok"]
    assert r["in_axial_mode_range"] is True


def test_helical_out_of_range_warning():
    """C/λ = 0.3 → out-of-range warning issued."""
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        r = helical_axial(2.4e9, n_turns=5, circumference_wavelengths=0.3)
    assert r["ok"]
    assert any("axial-mode" in str(x.message).lower() or "out of" in str(x.message).lower() for x in w)


def test_helical_impedance_scales_with_c_lam():
    """R_in ≈ 140 × C/λ → proportional to circumference wavelengths."""
    r1 = helical_axial(2.4e9, n_turns=5, circumference_wavelengths=1.0)
    r2 = helical_axial(2.4e9, n_turns=5, circumference_wavelengths=1.2)
    assert r1["ok"] and r2["ok"]
    ratio = r2["R_in_ohm"] / r1["R_in_ohm"]
    assert abs(ratio - 1.2) < 0.05


def test_helical_invalid_turns():
    """n_turns = 0 → ok=False."""
    result = helical_axial(2.4e9, n_turns=0)
    assert not result["ok"]


# ═══════════════════════════════════════════════════════════════════════════════
# 7. horn_gain
# ═══════════════════════════════════════════════════════════════════════════════

def test_horn_gain_larger_aperture():
    """Larger aperture → higher gain."""
    r1 = horn_gain(10e9, aperture_width_m=0.05, aperture_height_m=0.04)
    r2 = horn_gain(10e9, aperture_width_m=0.10, aperture_height_m=0.08)
    assert r1["ok"] and r2["ok"]
    assert r2["gain_dbi"] > r1["gain_dbi"]


def test_horn_gain_scales_with_frequency():
    """Higher frequency → larger aperture in wavelengths → higher gain."""
    r1 = horn_gain(10e9, aperture_width_m=0.05, aperture_height_m=0.04)
    r2 = horn_gain(20e9, aperture_width_m=0.05, aperture_height_m=0.04)
    assert r1["ok"] and r2["ok"]
    assert r2["gain_dbi"] > r1["gain_dbi"]


def test_horn_hpbw_e_smaller_for_larger_b():
    """Larger b (E-plane aperture) → smaller E-plane HPBW."""
    r1 = horn_gain(10e9, aperture_width_m=0.05, aperture_height_m=0.02)
    r2 = horn_gain(10e9, aperture_width_m=0.05, aperture_height_m=0.04)
    assert r1["ok"] and r2["ok"]
    assert r2["hpbw_e_plane_deg"] < r1["hpbw_e_plane_deg"]


def test_horn_effective_aperture_formula():
    """Aeff = ηap × Ap."""
    r = horn_gain(10e9, aperture_width_m=0.05, aperture_height_m=0.04,
                   aperture_efficiency=0.51)
    assert r["ok"]
    Ap = 0.05 * 0.04
    assert abs(r["effective_aperture_m2"] - 0.51 * Ap) < 1e-9


def test_horn_invalid_aperture():
    """Zero aperture width → ok=False."""
    result = horn_gain(10e9, aperture_width_m=0, aperture_height_m=0.04)
    assert not result["ok"]


# ═══════════════════════════════════════════════════════════════════════════════
# 8. directivity_gain_efficiency
# ═══════════════════════════════════════════════════════════════════════════════

def test_dge_compute_gain_from_d_and_eta():
    """G = η × D: for D=1.643, η=1.0 → G ≈ 2.15 dBi."""
    r = directivity_gain_efficiency(directivity=1.643, efficiency=1.0)
    assert r["ok"]
    assert abs(r["gain_dbi"] - 2.15) < 0.05


def test_dge_compute_efficiency():
    """η = G / D: for G=2.15 dBi, D=1.643 → η ≈ 1.0."""
    r = directivity_gain_efficiency(directivity=1.643, gain_dbi=2.15)
    assert r["ok"]
    assert abs(r["efficiency"] - 1.0) < 0.05


def test_dge_compute_directivity():
    """D = G / η: for G=2.15 dBi, η=1.0 → D ≈ 1.643."""
    r = directivity_gain_efficiency(gain_dbi=2.15, efficiency=1.0)
    assert r["ok"]
    assert abs(r["directivity"] - 1.643) < 0.05


def test_dge_three_params_error():
    """All three provided → ok=False."""
    r = directivity_gain_efficiency(directivity=1.643, gain_dbi=2.15, efficiency=1.0)
    assert not r["ok"]


def test_dge_one_param_error():
    """Only one provided → ok=False."""
    r = directivity_gain_efficiency(directivity=1.643)
    assert not r["ok"]


# ═══════════════════════════════════════════════════════════════════════════════
# 9. beamwidth_directivity (Kraus approximation)
# ═══════════════════════════════════════════════════════════════════════════════

def test_beamwidth_directivity_half_wave_dipole():
    """Half-wave dipole: θ_E=78°, θ_H=360° → D_Kraus ≈ 41253/28080 ≈ 1.47."""
    r = beamwidth_directivity(hpbw_e_deg=78.0, hpbw_h_deg=360.0)
    assert r["ok"]
    # Expected: 41253 / (78 × 360) = 41253 / 28080 ≈ 1.469
    assert abs(r["directivity_kraus"] - 1.469) < 0.02


def test_beamwidth_directivity_pencil_beam():
    """Narrow pencil beam θ_E=θ_H=10° → D_Kraus = 41253/100 = 412.5."""
    r = beamwidth_directivity(hpbw_e_deg=10.0, hpbw_h_deg=10.0)
    assert r["ok"]
    assert abs(r["directivity_kraus"] - 412.53) < 1.0


def test_beamwidth_directivity_invalid():
    """Zero beamwidth → ok=False."""
    r = beamwidth_directivity(hpbw_e_deg=0.0, hpbw_h_deg=10.0)
    assert not r["ok"]


# ═══════════════════════════════════════════════════════════════════════════════
# 10. aperture_efficiency
# ═══════════════════════════════════════════════════════════════════════════════

def test_aperture_eff_isotropic_at_1ghz():
    """Isotropic antenna (0 dBi) at 1 GHz: Aeff = λ²/(4π) = 0.3²/(4π) ≈ 7.16e-3 m²."""
    lam = _lam(1e9)
    expected_Aeff = lam**2 / (4 * math.pi)
    r = aperture_efficiency(1e9, gain_dbi=0.0)
    assert r["ok"]
    assert abs(r["effective_aperture_m2"] - expected_Aeff) < 1e-6


def test_aperture_eff_with_physical_aperture():
    """When physical aperture is provided, aperture_efficiency is computed."""
    r = aperture_efficiency(10e9, gain_dbi=20.0, physical_aperture_m2=0.01)
    assert r["ok"]
    assert "aperture_efficiency" in r
    assert 0.0 < r["aperture_efficiency"] <= 1.5  # ηap can exceed 1 for super-directive


def test_aperture_eff_invalid_freq():
    """Zero frequency → ok=False."""
    r = aperture_efficiency(0, gain_dbi=10.0)
    assert not r["ok"]


# ═══════════════════════════════════════════════════════════════════════════════
# 11. near_far_field_boundary
# ═══════════════════════════════════════════════════════════════════════════════

def test_fraunhofer_formula():
    """Fraunhofer distance = 2D²/λ."""
    freq = 10e9
    D = 0.1
    lam = _lam(freq)
    expected = 2.0 * D**2 / lam
    r = near_far_field_boundary(freq, D)
    assert r["ok"]
    assert abs(r["fraunhofer_distance_m"] - expected) < 1e-6


def test_reactive_near_field_boundary():
    """Reactive near-field boundary = 0.62 sqrt(D³/λ)."""
    freq = 1e9
    D = 0.3
    lam = _lam(freq)
    expected = 0.62 * math.sqrt(D**3 / lam)
    r = near_far_field_boundary(freq, D)
    assert r["ok"]
    assert abs(r["reactive_near_field_m"] - expected) < 1e-6


def test_fraunhofer_greater_than_reactive():
    """Fraunhofer boundary > reactive near-field boundary (for D >> λ)."""
    r = near_far_field_boundary(10e9, 0.3)
    assert r["ok"]
    assert r["fraunhofer_distance_m"] > r["reactive_near_field_m"]


# ═══════════════════════════════════════════════════════════════════════════════
# 12. polarization_axial_ratio
# ═══════════════════════════════════════════════════════════════════════════════

def test_polarization_circular_ar1():
    """AR=1 (circular) → PLF_worst = 0 (no mismatch with opposite circular)."""
    r = polarization_axial_ratio(1.0)
    assert r["ok"]
    assert abs(r["plf_worst_case"]) < 1e-9
    assert r["is_circular"] is True


def test_polarization_linear_ar_large():
    """AR=1000 (linear) → PLF_worst ≈ 1.0."""
    r = polarization_axial_ratio(1000.0)
    assert r["ok"]
    assert r["plf_worst_case"] > 0.99
    assert r["is_linear"] is True


def test_polarization_tilt_45deg():
    """Linear 45° tilt → PLF = cos²(45°) = 0.5."""
    r = polarization_axial_ratio(1000.0, tilt_angle_deg=45.0)
    assert r["ok"]
    assert abs(r["plf_linear_tilt"] - 0.5) < 1e-6


def test_polarization_invalid_ar():
    """AR < 1.0 → ok=False."""
    r = polarization_axial_ratio(0.5)
    assert not r["ok"]


# ═══════════════════════════════════════════════════════════════════════════════
# 13. ground_plane_image
# ═══════════════════════════════════════════════════════════════════════════════

def test_ground_plane_image_resistance_half():
    """Monopole Rin = Rdipole / 2."""
    r = ground_plane_image(73.1, 42.5, 2.15)
    assert r["ok"]
    assert abs(r["monopole_R_in_ohm"] - 73.1 / 2.0) < 0.01


def test_ground_plane_image_reactance_half():
    """Monopole Xin = Xdipole / 2."""
    r = ground_plane_image(73.1, 42.5, 2.15)
    assert r["ok"]
    assert abs(r["monopole_X_in_ohm"] - 42.5 / 2.0) < 0.01


def test_ground_plane_image_gain_3dbi_higher():
    """Monopole gain = dipole gain + 3.01 dBi."""
    r = ground_plane_image(73.1, 42.5, 2.15)
    assert r["ok"]
    assert abs(r["monopole_gain_dbi"] - (2.15 + 3.01)) < 0.01


# ═══════════════════════════════════════════════════════════════════════════════
# 14. array_factor_ula
# ═══════════════════════════════════════════════════════════════════════════════

def test_ula_array_gain_equals_10log10_N():
    """ULA array gain = 10 log10(N)."""
    N = 8
    r = array_factor_ula(2.4e9, N, element_spacing_m=0.0625, scan_angle_deg=90.0)
    assert r["ok"]
    expected = 10.0 * math.log10(N)
    assert abs(r["array_gain_dbi"] - expected) < 0.01


def test_ula_grating_lobe_detected_half_lam_endfire():
    """d=λ/2 at endfire (θ₀=0°) triggers grating lobe (threshold = λ/(1+1) = λ/2)."""
    lam = _lam(2.4e9)
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        r = array_factor_ula(2.4e9, 4, element_spacing_m=lam / 2.0,
                              scan_angle_deg=0.0, check_grating_lobes=True)
    assert r["ok"]
    assert r["grating_lobe_present"] is True


def test_ula_no_grating_lobe_half_lambda_broadside():
    """d=λ/2 at broadside (θ₀=90°): threshold = λ/1 → no grating lobe."""
    lam = _lam(2.4e9)
    r = array_factor_ula(2.4e9, 4, element_spacing_m=lam / 2.0,
                          scan_angle_deg=90.0, check_grating_lobes=True)
    assert r["ok"]
    assert r["grating_lobe_present"] is False


def test_ula_null_positions_present():
    """Null positions are reported for N>1."""
    r = array_factor_ula(2.4e9, 4, element_spacing_m=0.0625, scan_angle_deg=90.0)
    assert r["ok"]
    assert len(r["null_angles_deg"]) > 0


def test_ula_invalid_n_elements():
    """n_elements = 0 → ok=False."""
    r = array_factor_ula(2.4e9, 0, element_spacing_m=0.05)
    assert not r["ok"]


# ═══════════════════════════════════════════════════════════════════════════════
# 15. vswr_bandwidth_from_q
# ═══════════════════════════════════════════════════════════════════════════════

def test_vswr_bw_formula():
    """BW_fraction = (S-1)/(Q sqrt(S)) for S=2: BW = 1/(Q sqrt(2))."""
    Q = 10.0
    S = 2.0
    r = vswr_bandwidth_from_q(1e9, q_factor=Q, vswr_limit=S)
    assert r["ok"]
    expected = (S - 1.0) / (Q * math.sqrt(S))
    # Rounded to 6 decimal places in result — allow 5e-7 tolerance
    assert abs(r["bw_fraction"] - expected) < 5e-7


def test_vswr_bw_symmetric_around_centre():
    """Lower and upper band edges symmetric around centre frequency."""
    r = vswr_bandwidth_from_q(2.4e9, q_factor=15.0)
    assert r["ok"]
    centre = (r["bw_lower_hz"] + r["bw_upper_hz"]) / 2.0
    assert abs(centre - 2.4e9) < 1.0


def test_vswr_bw_return_loss_vswr2():
    """VSWR=2 → |Γ|=1/3 → RL = 20 log10(3) ≈ 9.54 dB."""
    r = vswr_bandwidth_from_q(1e9, q_factor=10.0, vswr_limit=2.0)
    assert r["ok"]
    assert abs(r["return_loss_db"] - 9.542) < 0.01


def test_vswr_bw_invalid_q():
    """Q=0 → ok=False."""
    r = vswr_bandwidth_from_q(1e9, q_factor=0)
    assert not r["ok"]


def test_vswr_bw_invalid_vswr():
    """VSWR < 1 → ok=False."""
    r = vswr_bandwidth_from_q(1e9, q_factor=10.0, vswr_limit=0.9)
    assert not r["ok"]


# ═══════════════════════════════════════════════════════════════════════════════
# 16. LLM tool handlers (stub registry)
# ═══════════════════════════════════════════════════════════════════════════════

import asyncio


def _run(coro):
    return asyncio.run(coro)


def test_tool_dipole_returns_ok():
    payload = json.dumps({"freq_hz": 300e6})
    result_str = _run(_antenna_tools.antenna_half_wave_dipole(None, payload.encode()))
    result = json.loads(result_str)
    assert result.get("ok") is True


def test_tool_monopole_returns_ok():
    payload = json.dumps({"freq_hz": 900e6})
    result_str = _run(_antenna_tools.antenna_monopole(None, payload.encode()))
    result = json.loads(result_str)
    assert result.get("ok") is True


def test_tool_small_loop_returns_ok():
    payload = json.dumps({"freq_hz": 100e6, "loop_area_m2": 1e-4})
    result_str = _run(_antenna_tools.antenna_small_loop(None, payload.encode()))
    result = json.loads(result_str)
    assert result.get("ok") is True


def test_tool_patch_returns_ok():
    payload = json.dumps({"freq_hz": 2.4e9, "er": 4.4, "h_m": 1.6e-3})
    result_str = _run(_antenna_tools.antenna_microstrip_patch(None, payload.encode()))
    result = json.loads(result_str)
    assert result.get("ok") is True


def test_tool_yagi_returns_ok():
    payload = json.dumps({"freq_hz": 144e6, "n_directors": 3})
    result_str = _run(_antenna_tools.antenna_yagi_uda(None, payload.encode()))
    result = json.loads(result_str)
    assert result.get("ok") is True


def test_tool_helical_returns_ok():
    payload = json.dumps({"freq_hz": 2.4e9, "n_turns": 5})
    result_str = _run(_antenna_tools.antenna_helical_axial(None, payload.encode()))
    result = json.loads(result_str)
    assert result.get("ok") is True


def test_tool_horn_returns_ok():
    payload = json.dumps({"freq_hz": 10e9, "aperture_width_m": 0.05, "aperture_height_m": 0.04})
    result_str = _run(_antenna_tools.antenna_horn_gain(None, payload.encode()))
    result = json.loads(result_str)
    assert result.get("ok") is True


def test_tool_array_returns_ok():
    payload = json.dumps({"freq_hz": 2.4e9, "n_elements": 4, "element_spacing_m": 0.0625})
    result_str = _run(_antenna_tools.antenna_array_factor_ula(None, payload.encode()))
    result = json.loads(result_str)
    assert result.get("ok") is True


def test_tool_vswr_bw_returns_ok():
    payload = json.dumps({"freq_hz": 1e9, "q_factor": 10.0})
    result_str = _run(_antenna_tools.antenna_vswr_bw(None, payload.encode()))
    result = json.loads(result_str)
    assert result.get("ok") is True


def test_tool_invalid_json_returns_error():
    result_str = _run(_antenna_tools.antenna_half_wave_dipole(None, b"not json"))
    result = json.loads(result_str)
    # The stub err_payload returns {"ok": False, "error": ..., "code": ...}
    # The real ok_payload returns {"ok": True, ...}
    # Either way, the result must NOT be a success
    assert result.get("ok") is not True


def test_tools_list_has_all_entries():
    """TOOLS list should contain exactly 15 entries."""
    assert len(_antenna_tools.TOOLS) == 15


def test_tools_list_names_unique():
    """All tool names in TOOLS should be unique."""
    names = [t[0] for t in _antenna_tools.TOOLS]
    assert len(names) == len(set(names))
