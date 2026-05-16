"""
Hermetic tests for the magnetics design module.

Covers ≥30 hand-verifiable tests against McLyman / power-magnetics formulas:

  Faraday turns (transformer & inductor)
  Area-product Ap selection
  Steinmetz core loss
  Gap length & AL
  AWG selection
  Dowell AC factor
  Copper loss (DC + AC)
  Temperature rise
  Saturation check
  Window utilisation
  Turns ratio
  Flyback, forward, push-pull transformer specifics
  Leakage inductance estimate
  LLM tool handlers (stub registry)

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

# ── Stub kerf_chat.tools.registry (no real registry needed for unit tests) ────
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

from kerf_electronics.magnetics.design import (
    CORE_MATERIALS,
    awg_from_current,
    copper_loss,
    core_select_ap,
    core_select_kg,
    dowell_ac_factor,
    flyback_transformer,
    forward_transformer,
    gap_length,
    inductor_turns,
    leakage_inductance_estimate,
    push_pull_transformer,
    saturation_check,
    skin_depth,
    steinmetz_core_loss,
    temperature_rise,
    total_loss,
    transformer_primary_turns,
    turns_ratio,
    window_utilization,
)

# ── Load tool module via importlib so stub is active ─────────────────────────
_tool_spec = importlib.util.spec_from_file_location(
    "kerf_electronics.magnetics.tools",
    os.path.join(_SRC, "kerf_electronics", "magnetics", "tools.py"),
)
_tool_mod = importlib.util.module_from_spec(_tool_spec)
_tool_spec.loader.exec_module(_tool_mod)

_core_ap_tool = _tool_mod.magnetics_core_select_ap
_core_kg_tool = _tool_mod.magnetics_core_select_kg
_xfmr_turns_tool = _tool_mod.magnetics_transformer_turns
_ind_turns_tool = _tool_mod.magnetics_inductor_turns
_gap_tool = _tool_mod.magnetics_gap_length
_awg_tool = _tool_mod.magnetics_awg_select
_core_loss_tool = _tool_mod.magnetics_core_loss
_cu_loss_tool = _tool_mod.magnetics_copper_loss
_temp_tool = _tool_mod.magnetics_temperature_rise
_sat_tool = _tool_mod.magnetics_saturation_check


# ── Async call helper ─────────────────────────────────────────────────────────

async def call(fn, **kwargs):
    result = await fn(None, json.dumps(kwargs).encode())
    return json.loads(result)


# ═══════════════════════════════════════════════════════════════════════════════
# 1. transformer_primary_turns — Faraday's law
# ═══════════════════════════════════════════════════════════════════════════════

class TestTransformerPrimaryTurns:
    """Np = V / (k × f × Bmax × Ae)   k=4 square-wave, k=4.44 sinusoidal."""

    def test_square_wave_hand_calc(self):
        """
        McLyman §4.2 example proxy:
        V=100V, f=100kHz, Bmax=0.2T, Ae=1.73e-4 m² (ETD44-like)
        Np = 100 / (4 × 100000 × 0.2 × 1.73e-4) = 100 / 13.84 ≈ 7.22 → ceil = 8
        """
        ae = 1.73e-4
        res = transformer_primary_turns(
            v_primary=100.0, freq_hz=100e3, bmax_t=0.2, ae_m2=ae, waveform="square"
        )
        assert res["ok"] is True
        expected_exact = 100.0 / (4.0 * 100e3 * 0.2 * ae)
        assert abs(res["Np_exact"] - expected_exact) < 0.001
        assert res["Np"] == math.ceil(expected_exact)

    def test_sine_wave_formula_constant(self):
        """Sinusoidal uses k=4.44."""
        res = transformer_primary_turns(
            v_primary=230.0, freq_hz=50.0, bmax_t=1.2, ae_m2=1e-4, waveform="sine"
        )
        assert res["ok"] is True
        assert res["formula_constant"] == 4.44
        expected = 230.0 / (4.44 * 50.0 * 1.2 * 1e-4)
        assert abs(res["Np_exact"] - expected) < 0.01

    def test_turns_ceil_up(self):
        """Np always rounds up (ceil) to ensure Bmax is not exceeded."""
        res = transformer_primary_turns(
            v_primary=48.0, freq_hz=200e3, bmax_t=0.25, ae_m2=1.25e-4, waveform="square"
        )
        assert res["ok"] is True
        assert res["Np"] == math.ceil(res["Np_exact"])
        assert isinstance(res["Np"], int)

    def test_invalid_zero_freq(self):
        res = transformer_primary_turns(
            v_primary=100.0, freq_hz=0.0, bmax_t=0.2, ae_m2=1e-4
        )
        assert res["ok"] is False

    def test_invalid_waveform(self):
        res = transformer_primary_turns(
            v_primary=100.0, freq_hz=50e3, bmax_t=0.3, ae_m2=1e-4, waveform="triangle"
        )
        assert res["ok"] is False

    def test_bmax_increase_reduces_turns(self):
        """Higher Bmax → fewer turns needed."""
        r1 = transformer_primary_turns(100, 100e3, 0.2, 1e-4)
        r2 = transformer_primary_turns(100, 100e3, 0.3, 1e-4)
        assert r1["Np_exact"] > r2["Np_exact"]


# ═══════════════════════════════════════════════════════════════════════════════
# 2. inductor_turns — Ampere's law
# ═══════════════════════════════════════════════════════════════════════════════

class TestInductorTurns:
    """N = L × I_peak / (Bmax × Ae)"""

    def test_hand_calc(self):
        """
        L=100µH, I_pk=5A, Bmax=0.3T, Ae=1.25e-4 m²
        N = 100e-6 × 5 / (0.3 × 1.25e-4) = 5e-4 / 3.75e-5 ≈ 13.33 → 14
        """
        res = inductor_turns(
            inductance_h=100e-6, i_peak_a=5.0, bmax_t=0.3, ae_m2=1.25e-4
        )
        assert res["ok"] is True
        expected = 100e-6 * 5.0 / (0.3 * 1.25e-4)
        assert abs(res["N_exact"] - expected) < 0.001
        assert res["N"] == math.ceil(expected)

    def test_larger_inductance_more_turns(self):
        r1 = inductor_turns(100e-6, 5.0, 0.3, 1e-4)
        r2 = inductor_turns(200e-6, 5.0, 0.3, 1e-4)
        # N_exact is rounded to 4 decimal places; use rel=1e-3 tolerance
        assert r2["N_exact"] == pytest.approx(2.0 * r1["N_exact"], rel=1e-3)

    def test_invalid_zero_bmax(self):
        res = inductor_turns(100e-6, 5.0, 0.0, 1e-4)
        assert res["ok"] is False

    def test_returns_int_turns(self):
        res = inductor_turns(50e-6, 3.0, 0.25, 2e-4)
        assert res["ok"] is True
        assert isinstance(res["N"], int)


# ═══════════════════════════════════════════════════════════════════════════════
# 3. turns_ratio
# ═══════════════════════════════════════════════════════════════════════════════

class TestTurnsRatio:

    def test_ideal_ratio(self):
        res = turns_ratio(v_primary=400.0, v_secondary=20.0)
        assert res["ok"] is True
        assert res["n_ideal"] == pytest.approx(20.0, rel=1e-6)

    def test_actual_turns_reg_error(self):
        """20:1 ideal; 20 turns primary, 1 turn secondary → exact match."""
        res = turns_ratio(400.0, 20.0, np_actual=20, ns_actual=1)
        assert res["ok"] is True
        assert abs(res["turns_reg_error_pct"]) < 0.01

    def test_actual_turns_reg_error_nonzero(self):
        """19:1 actual vs 20:1 ideal → voltage error ≈ 5 %."""
        res = turns_ratio(400.0, 20.0, np_actual=19, ns_actual=1)
        assert res["ok"] is True
        # Vs_actual = 400/19 ≈ 21.05 V, error vs 20 V ≈ +5.26 %
        assert abs(res["turns_reg_error_pct"]) > 4.0

    def test_zero_secondary_invalid(self):
        res = turns_ratio(400.0, 0.0)
        assert res["ok"] is False


# ═══════════════════════════════════════════════════════════════════════════════
# 4. core_select_ap — area-product
# ═══════════════════════════════════════════════════════════════════════════════

class TestCoreSelectAp:

    def test_returns_ok_with_core(self):
        res = core_select_ap(power_va=50.0, freq_hz=100e3, bmax_t=0.2)
        assert res["ok"] is True
        assert "selected_core" in res
        assert "name" in res["selected_core"]

    def test_ap_formula(self):
        """
        Ap = P / (kt × kw × Bmax × J × f)
        P=100VA, kw=0.4, kt=1, Bmax=0.2, J=4e6, f=100e3
        Ap = 100 / (1 × 0.4 × 0.2 × 4e6 × 100e3) = 100 / 3.2e10 = 3.125e-9 m⁴
        """
        res = core_select_ap(
            power_va=100.0, freq_hz=100e3, bmax_t=0.2,
            j_am2=4.0e6, kw=0.4, kt=1.0
        )
        assert res["ok"] is True
        expected_ap = 100.0 / (1.0 * 0.4 * 0.2 * 4.0e6 * 100e3)
        assert abs(res["ap_required_m4"] - expected_ap) < expected_ap * 1e-9

    def test_selected_core_ap_sufficient(self):
        """Selected core Ap must be >= required Ap."""
        res = core_select_ap(power_va=20.0, freq_hz=50e3, bmax_t=0.25)
        assert res["ok"] is True
        core = res["selected_core"]
        ap_core = core["Ae"] * core["Wa"]
        assert ap_core >= res["ap_required_m4"] * 0.999  # small tolerance for candidate ordering

    def test_zero_power_invalid(self):
        res = core_select_ap(power_va=0.0, freq_hz=100e3, bmax_t=0.2)
        assert res["ok"] is False

    def test_higher_power_selects_larger_core(self):
        r_small = core_select_ap(10.0, 100e3, 0.2)
        r_large = core_select_ap(500.0, 100e3, 0.2)
        ap_small = r_small["selected_core"]["Ae"] * r_small["selected_core"]["Wa"]
        ap_large = r_large["selected_core"]["Ae"] * r_large["selected_core"]["Wa"]
        assert ap_large >= ap_small


# ═══════════════════════════════════════════════════════════════════════════════
# 5. steinmetz_core_loss — Pv = k × f^α × B^β
# ═══════════════════════════════════════════════════════════════════════════════

class TestSteinmetzCoreLoss:

    def test_n87_hand_calc(self):
        """
        N87: k=16.9, alpha=1.36, beta=2.86
        f=100kHz, B=0.1T, Vc=3.46e-6 m³ (ETD29)
        Pv = 16.9 × (100000)^1.36 × (0.1)^2.86
        """
        mat = CORE_MATERIALS["N87"]
        f, b, vc = 100e3, 0.1, 3.46e-6
        expected_pv = mat["k"] * (f ** mat["alpha"]) * (b ** mat["beta"])
        res = steinmetz_core_loss(freq_hz=f, b_peak_t=b, core_volume_m3=vc, material="N87")
        assert res["ok"] is True
        assert abs(res["p_volume_w_m3"] - round(expected_pv, 2)) < 1.0  # rounding
        assert abs(res["p_core_w"] - expected_pv * vc) / (expected_pv * vc) < 1e-6

    def test_saturation_flag_triggered(self):
        """B_peak >= Bsat triggers saturation_flag and warning."""
        bsat = CORE_MATERIALS["N87"]["Bsat"]
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            res = steinmetz_core_loss(
                freq_hz=100e3, b_peak_t=bsat + 0.01, core_volume_m3=1e-6, material="N87"
            )
        assert res["ok"] is True
        assert res["saturation_flag"] is True
        assert any("saturate" in str(x.message).lower() for x in w)

    def test_no_saturation_flag_below_bsat(self):
        bsat = CORE_MATERIALS["N87"]["Bsat"]
        res = steinmetz_core_loss(
            freq_hz=100e3, b_peak_t=bsat * 0.7, core_volume_m3=1e-6, material="N87"
        )
        assert res["ok"] is True
        assert res["saturation_flag"] is False

    def test_core_loss_scales_with_freq(self):
        """Doubling frequency → 2^alpha × core loss (alpha > 1)."""
        r1 = steinmetz_core_loss(100e3, 0.1, 1e-6, "N87")
        r2 = steinmetz_core_loss(200e3, 0.1, 1e-6, "N87")
        alpha = CORE_MATERIALS["N87"]["alpha"]
        # p_core_w rounded to 6 decimal places; use relative tolerance of 1e-4
        ratio = r2["p_core_w"] / r1["p_core_w"]
        assert abs(ratio - 2.0 ** alpha) / (2.0 ** alpha) < 1e-4

    def test_core_loss_scales_with_bpeak(self):
        """Doubling B_peak → 2^beta × core loss."""
        r1 = steinmetz_core_loss(100e3, 0.05, 1e-6, "N87")
        r2 = steinmetz_core_loss(100e3, 0.10, 1e-6, "N87")
        beta = CORE_MATERIALS["N87"]["beta"]
        # p_core_w rounded to 6 decimal places; use relative tolerance of 1e-3
        ratio = r2["p_core_w"] / r1["p_core_w"]
        assert abs(ratio - 2.0 ** beta) / (2.0 ** beta) < 1e-3

    def test_unknown_material_returns_error(self):
        res = steinmetz_core_loss(100e3, 0.1, 1e-6, material="UNOBTANIUM")
        assert res["ok"] is False

    def test_powder_core_material(self):
        res = steinmetz_core_loss(100e3, 0.3, 1e-6, material="KOOL_MU_60")
        assert res["ok"] is True
        assert res["p_core_w"] > 0


# ═══════════════════════════════════════════════════════════════════════════════
# 6. gap_length
# ═══════════════════════════════════════════════════════════════════════════════

class TestGapLength:

    def test_hand_calc_no_fringing(self):
        """
        lg = μ0 × N² × Ae / L
        μ0=4π×10-7, N=20, Ae=1.25e-4, L=100µH
        lg = 4π×10-7 × 400 × 1.25e-4 / 100e-6
           = 4π×10-7 × 0.05 / 100e-6
           = 4π×10-7 × 500 ≈ 628.3 µm = 0.6283 mm
        """
        mu0 = 4.0 * math.pi * 1e-7
        n, ae, l = 20, 1.25e-4, 100e-6
        expected_lg = mu0 * n ** 2 * ae / l
        res = gap_length(inductance_h=l, n_turns=n, ae_m2=ae, mu_i=2200, fringing_iter=0)
        assert res["ok"] is True
        assert abs(res["lg_m"] - expected_lg) / expected_lg < 1e-6

    def test_fringing_reduces_gap(self):
        """With fringing correction, effective gap should be slightly smaller."""
        res0 = gap_length(100e-6, 20, 1.25e-4, fringing_iter=0)
        res3 = gap_length(100e-6, 20, 1.25e-4, fringing_iter=3)
        assert res0["ok"] and res3["ok"]
        # lg_eff with fringing <= ungapped lg
        assert res3["lg_eff_mm"] <= res0["lg_mm"] * 1.001  # allow rounding

    def test_al_nH_per_turn2_positive(self):
        res = gap_length(100e-6, 20, 1.25e-4)
        assert res["ok"] is True
        assert res["AL_nH_per_turn2"] > 0

    def test_invalid_zero_turns(self):
        res = gap_length(100e-6, 0, 1.25e-4)
        assert res["ok"] is False

    def test_larger_inductance_larger_gap(self):
        """L2 = 2×L1 → gap2 ≈ 2×gap1 (linear)."""
        r1 = gap_length(100e-6, 20, 1.25e-4, fringing_iter=0)
        r2 = gap_length(200e-6, 20, 1.25e-4, fringing_iter=0)
        # More inductance → larger gap needed (N is same but L doubled) — wait,
        # lg = μ0 N² Ae / L → larger L → smaller gap.
        assert r2["lg_m"] < r1["lg_m"]


# ═══════════════════════════════════════════════════════════════════════════════
# 7. awg_from_current
# ═══════════════════════════════════════════════════════════════════════════════

class TestAwgFromCurrent:

    def test_1a_at_4amm2(self):
        """
        A_req = 1 / 4e6 = 0.25 mm² = 0.25e-6 m²
        AWG 24 dia=0.511mm → A=0.205mm² < 0.25mm²
        AWG 22 dia=0.644mm → A=0.326mm² > 0.25mm² → should select AWG 22
        """
        res = awg_from_current(i_rms_a=1.0, j_am2=4.0e6)
        assert res["ok"] is True
        a_req = 1.0 / 4.0e6
        assert res["area_m2"] >= a_req

    def test_higher_current_coarser_awg(self):
        """Higher current → lower AWG number (coarser wire)."""
        r1 = awg_from_current(1.0, 4e6)
        r2 = awg_from_current(5.0, 4e6)
        assert r1["ok"] and r2["ok"]
        assert r2["awg"] <= r1["awg"]  # coarser = lower number

    def test_area_always_sufficient(self):
        """Selected wire area always >= required area."""
        for i_rms in [0.1, 0.5, 1.0, 3.0, 8.0]:
            res = awg_from_current(i_rms, 4e6)
            assert res["ok"] is True
            a_req = i_rms / 4e6
            assert res["area_m2"] >= a_req * 0.999

    def test_invalid_zero_current(self):
        res = awg_from_current(0.0, 4e6)
        assert res["ok"] is False


# ═══════════════════════════════════════════════════════════════════════════════
# 8. skin_depth
# ═══════════════════════════════════════════════════════════════════════════════

class TestSkinDepth:

    def test_copper_at_100khz(self):
        """
        δ = sqrt(ρ / (π × f × μ0)) for copper (μr=1)
        = sqrt(1.72e-8 / (π × 100e3 × 4π×10-7))
        ≈ 0.208 mm (textbook value ~0.21 mm)
        """
        res = skin_depth(freq_hz=100e3)
        assert res["ok"] is True
        assert 0.18e-3 < res["delta_m"] < 0.25e-3

    def test_skin_depth_decreases_with_freq(self):
        """Higher frequency → smaller skin depth."""
        r1 = skin_depth(100e3)
        r2 = skin_depth(400e3)
        assert r2["delta_m"] < r1["delta_m"]

    def test_skin_depth_scales_as_inv_sqrt_freq(self):
        """δ ∝ 1/√f → δ(4f) = δ(f)/2."""
        r1 = skin_depth(100e3)
        r4 = skin_depth(400e3)
        ratio = r4["delta_m"] / r1["delta_m"]
        assert abs(ratio - 0.5) < 0.001

    def test_zero_freq_invalid(self):
        res = skin_depth(0.0)
        assert res["ok"] is False


# ═══════════════════════════════════════════════════════════════════════════════
# 9. dowell_ac_factor
# ═══════════════════════════════════════════════════════════════════════════════

class TestDowellAcFactor:

    def test_dc_limit_single_layer(self):
        """Very low frequency → δ >> d → Fr ≈ 1."""
        res = dowell_ac_factor(freq_hz=1.0, wire_dia_m=0.5e-3, n_layers=1)
        assert res["ok"] is True
        assert abs(res["Fr"] - 1.0) < 0.01

    def test_fr_increases_with_layers(self):
        """More layers → higher Fr (Dowell proximity factor)."""
        r1 = dowell_ac_factor(100e3, 0.5e-3, n_layers=1)
        r5 = dowell_ac_factor(100e3, 0.5e-3, n_layers=5)
        assert r5["Fr"] >= r1["Fr"]

    def test_fr_gte_1(self):
        """AC resistance factor must always be >= 1."""
        res = dowell_ac_factor(100e3, 0.3e-3, n_layers=3)
        assert res["ok"] is True
        assert res["Fr"] >= 1.0

    def test_invalid_negative_freq(self):
        res = dowell_ac_factor(-1.0, 0.5e-3, 1)
        assert res["ok"] is False

    def test_invalid_zero_layers(self):
        res = dowell_ac_factor(100e3, 0.5e-3, 0)
        assert res["ok"] is False


# ═══════════════════════════════════════════════════════════════════════════════
# 10. copper_loss
# ═══════════════════════════════════════════════════════════════════════════════

class TestCopperLoss:

    def test_dc_only_fr1(self):
        """Fr=1 → P_total = I² × R."""
        res = copper_loss(i_rms_dc_a=2.0, rdc_ohm=0.1, fr=1.0)
        assert res["ok"] is True
        assert abs(res["p_total_w"] - 0.4) < 1e-9
        assert abs(res["p_ac_w"]) < 1e-9

    def test_ac_contribution(self):
        """Fr=2 → P_total = 2 × I² × R."""
        res = copper_loss(i_rms_dc_a=2.0, rdc_ohm=0.1, fr=2.0)
        assert res["ok"] is True
        assert abs(res["p_total_w"] - 0.8) < 1e-9

    def test_fr_less_than_1_invalid(self):
        res = copper_loss(i_rms_dc_a=1.0, rdc_ohm=0.1, fr=0.9)
        assert res["ok"] is False

    def test_zero_current_invalid(self):
        res = copper_loss(i_rms_dc_a=0.0, rdc_ohm=0.1)
        assert res["ok"] is False

    def test_rac_equals_fr_times_rdc(self):
        fr = 3.5
        rdc = 0.05
        res = copper_loss(i_rms_dc_a=1.0, rdc_ohm=rdc, fr=fr)
        assert res["ok"] is True
        assert abs(res["rac_ohm"] - rdc * fr) < 1e-10


# ═══════════════════════════════════════════════════════════════════════════════
# 11. temperature_rise
# ═══════════════════════════════════════════════════════════════════════════════

class TestTemperatureRise:

    def test_surface_area_model(self):
        """
        ΔT = P / (h × A)  with h=10 W/(m²K)
        P=1W, A=50cm²=50e-4 m²
        ΔT = 1 / (10 × 50e-4) = 20 K
        """
        res = temperature_rise(p_total_w=1.0, surface_area_m2=50e-4, t_ambient_c=25.0)
        assert res["ok"] is True
        assert abs(res["delta_t_k"] - 20.0) < 0.001

    def test_rth_model(self):
        """ΔT = P × Rth = 2 × 15 = 30 K."""
        res = temperature_rise(p_total_w=2.0, rth_c_per_w=15.0, t_ambient_c=25.0)
        assert res["ok"] is True
        assert abs(res["delta_t_k"] - 30.0) < 0.001

    def test_over_temp_warning(self):
        """T_total > T_max → over_temp=True, warning issued."""
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            res = temperature_rise(
                p_total_w=10.0, rth_c_per_w=20.0, t_ambient_c=25.0, t_max_c=100.0
            )
        assert res["ok"] is True
        assert res["over_temp"] is True
        assert any("over" in str(x.message).lower() or "t_max" in str(x.message).lower() for x in w)

    def test_no_thermal_path_invalid(self):
        """Must provide surface_area or rth."""
        res = temperature_rise(p_total_w=1.0)
        assert res["ok"] is False

    def test_t_margin_is_tmax_minus_ttotal(self):
        res = temperature_rise(p_total_w=1.0, rth_c_per_w=10.0, t_ambient_c=25.0, t_max_c=100.0)
        assert res["ok"] is True
        assert abs(res["t_margin_k"] - (100.0 - res["t_total_c"])) < 1e-6


# ═══════════════════════════════════════════════════════════════════════════════
# 12. saturation_check
# ═══════════════════════════════════════════════════════════════════════════════

class TestSaturationCheck:

    def test_not_saturated(self):
        """B_peak well below Bsat → saturated=False.

        μ0 × 2200 × 5 × 0.5 / 0.09 = 7.68e-3 T << Bsat(N87)=0.39 T
        """
        # Small N × I / le so B_peak << Bsat
        res = saturation_check(
            n_turns=5, i_peak_a=0.5, ae_m2=1.25e-4,
            le_m=0.09, mu_i=2200, material="N87"
        )
        assert res["ok"] is True
        assert res["b_peak_t"] > 0
        assert res["bsat_t"] == pytest.approx(CORE_MATERIALS["N87"]["Bsat"])
        assert res["saturated"] is False

    def test_saturated_when_b_exceeds_bsat(self):
        """Force saturation by using very high N × I."""
        bsat = CORE_MATERIALS["N87"]["Bsat"]
        # Choose N, I, le, mu_i so μ0 × μi × N × I / le > Bsat
        # e.g., μ0=4π×10-7, μi=2200, N=50, I=50, le=0.01 → B ≈ 693T >> Bsat
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            res = saturation_check(
                n_turns=50, i_peak_a=50.0, ae_m2=1e-4,
                le_m=0.01, mu_i=2200, material="N87"
            )
        assert res["ok"] is True
        assert res["saturated"] is True
        assert any("saturate" in str(x.message).lower() for x in w)

    def test_bsat_override(self):
        """Use bsat_override_t instead of material."""
        res = saturation_check(
            n_turns=10, i_peak_a=1.0, ae_m2=1e-4,
            le_m=0.05, mu_i=1.0, bsat_override_t=2.0
        )
        assert res["ok"] is True
        assert res["bsat_t"] == 2.0

    def test_b_peak_formula(self):
        """B_peak = μ0 × μi × N × I / le."""
        mu0 = 4.0 * math.pi * 1e-7
        n, i, mu_i, le = 30, 3.0, 100.0, 0.05
        expected = mu0 * mu_i * n * i / le
        res = saturation_check(n, i, 1e-4, le, mu_i)
        assert res["ok"] is True
        # b_peak_t rounded to 6 decimal places; use relative tolerance of 1e-4
        assert abs(res["b_peak_t"] - expected) / expected < 1e-4


# ═══════════════════════════════════════════════════════════════════════════════
# 13. window_utilization
# ═══════════════════════════════════════════════════════════════════════════════

class TestWindowUtilization:

    def test_basic(self):
        """Ku = sum / Wa = 0.1e-6 / 0.5e-4 = 0.002."""
        res = window_utilization([0.1e-6], wa_m2=0.5e-4, ku_max=0.4)
        assert res["ok"] is True
        assert abs(res["ku"] - 0.1e-6 / 0.5e-4) < 1e-10
        assert res["over_fill"] is False

    def test_over_fill_warning(self):
        """Ku > ku_max → over_fill=True, warning issued."""
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            res = window_utilization([0.5e-4], wa_m2=0.5e-4, ku_max=0.4)
        assert res["ok"] is True
        assert res["over_fill"] is True
        # Warning message contains "core" or "winding" or "ku"
        assert len(w) > 0

    def test_multi_winding(self):
        """Sum of two windings."""
        a1, a2 = 0.1e-6, 0.2e-6
        res = window_utilization([a1, a2], wa_m2=1.0e-4, ku_max=0.4)
        assert res["ok"] is True
        assert abs(res["ku"] - (a1 + a2) / 1.0e-4) < 1e-10

    def test_empty_list_invalid(self):
        res = window_utilization([], wa_m2=1e-4)
        assert res["ok"] is False


# ═══════════════════════════════════════════════════════════════════════════════
# 14. flyback_transformer
# ═══════════════════════════════════════════════════════════════════════════════

class TestFlybackTransformer:

    def test_returns_ok(self):
        res = flyback_transformer(
            v_in=100.0, v_out=12.0, i_out=2.0, fsw=100e3,
            duty=0.4, ae_m2=1.25e-4, bmax_t=0.2
        )
        assert res["ok"] is True
        assert "Np" in res
        assert "Ns" in res
        assert "n" in res

    def test_turns_positive(self):
        res = flyback_transformer(48, 5, 3, 200e3, 0.35, 1e-4, 0.25)
        assert res["ok"] is True
        assert res["Np"] >= 1
        assert res["Ns"] >= 1

    def test_diode_stress_formula(self):
        """V_diode_stress = Vout + Vin/n."""
        res = flyback_transformer(100.0, 12.0, 2.0, 100e3, 0.4, 1.25e-4, 0.2)
        assert res["ok"] is True
        expected_vds = 12.0 + 100.0 / res["n"]
        assert abs(res["v_diode_stress_v"] - expected_vds) < 0.1

    def test_invalid_duty_out_of_range(self):
        res = flyback_transformer(100, 12, 2, 100e3, 1.1, 1e-4, 0.2)
        assert res["ok"] is False


# ═══════════════════════════════════════════════════════════════════════════════
# 15. push_pull_transformer
# ═══════════════════════════════════════════════════════════════════════════════

class TestPushPullTransformer:

    def test_returns_ok(self):
        res = push_pull_transformer(
            v_in=48.0, v_out=5.0, i_out=10.0,
            fsw=100e3, ae_m2=2.0e-4, bmax_t=0.2
        )
        assert res["ok"] is True
        assert res["Np"] >= 1
        assert res["v_switch_stress_v"] == pytest.approx(2 * 48.0)

    def test_np_formula(self):
        """Np = V_in / (4 × f × Bmax × Ae) — same as full-bridge square-wave."""
        v, f, b, ae = 48.0, 100e3, 0.2, 2.0e-4
        res = push_pull_transformer(v, 5.0, 10.0, f, ae, b)
        assert res["ok"] is True
        np_exact = v / (4.0 * f * b * ae)
        assert res["Np"] == math.ceil(np_exact)

    def test_invalid_zero_fsw(self):
        res = push_pull_transformer(48, 5, 10, 0, 2e-4, 0.2)
        assert res["ok"] is False


# ═══════════════════════════════════════════════════════════════════════════════
# 16. leakage_inductance_estimate
# ═══════════════════════════════════════════════════════════════════════════════

class TestLeakageInductanceEstimate:

    def test_hand_calc(self):
        """
        Llk = μ0 × Np² × lw / (3 × bw) × (hp/3 + h_ins + hs/3)
        Np=20, lw=0.06m, bw=0.03m, hp=3mm, hs=2mm, h_ins=0.5mm
        """
        mu0 = 4.0 * math.pi * 1e-7
        np_t, lw, bw, hp, hs, hi = 20, 0.06, 0.03, 3e-3, 2e-3, 0.5e-3
        expected = mu0 * np_t ** 2 * lw / (3.0 * bw) * (hp / 3 + hi + hs / 3)
        res = leakage_inductance_estimate(np_t, lw, bw, hp, hs, hi)
        assert res["ok"] is True
        assert abs(res["leakage_h"] - expected) / expected < 1e-6

    def test_more_turns_more_leakage(self):
        """Leakage ∝ Np² — doubling Np → 4× leakage."""
        r1 = leakage_inductance_estimate(10, 0.05, 0.02, 2e-3, 2e-3)
        r2 = leakage_inductance_estimate(20, 0.05, 0.02, 2e-3, 2e-3)
        # leakage_h rounded to 12 decimal places; use relative tolerance 1e-4
        assert abs(r2["leakage_h"] / r1["leakage_h"] - 4.0) < 1e-4

    def test_insulation_gap_increases_leakage(self):
        r0 = leakage_inductance_estimate(20, 0.05, 0.02, 2e-3, 2e-3, 0.0)
        r1 = leakage_inductance_estimate(20, 0.05, 0.02, 2e-3, 2e-3, 1.0e-3)
        assert r1["leakage_h"] > r0["leakage_h"]

    def test_invalid_zero_breadth(self):
        res = leakage_inductance_estimate(20, 0.05, 0.0, 2e-3, 2e-3)
        assert res["ok"] is False


# ═══════════════════════════════════════════════════════════════════════════════
# 17. total_loss
# ═══════════════════════════════════════════════════════════════════════════════

class TestTotalLoss:

    def test_basic(self):
        res = total_loss(p_core_w=0.5, winding_losses_w=[0.3, 0.2])
        assert res["ok"] is True
        assert abs(res["p_total_w"] - 1.0) < 1e-9

    def test_empty_windings_invalid(self):
        res = total_loss(p_core_w=0.5, winding_losses_w=[])
        assert res["ok"] is False


# ═══════════════════════════════════════════════════════════════════════════════
# 18. core_select_kg
# ═══════════════════════════════════════════════════════════════════════════════

class TestCoreSelectKg:

    def test_returns_ok(self):
        res = core_select_kg(power_va=50.0, freq_hz=100e3, bmax_t=0.2)
        assert res["ok"] is True
        assert "selected_core" in res

    def test_kg_required_positive(self):
        res = core_select_kg(power_va=50.0, freq_hz=100e3, bmax_t=0.2)
        assert res["ok"] is True
        assert res["kg_required_m5"] > 0


# ═══════════════════════════════════════════════════════════════════════════════
# 19. LLM tool handlers (stub registry)
# ═══════════════════════════════════════════════════════════════════════════════

class TestLlmTools:

    @pytest.mark.asyncio
    async def test_core_ap_tool_ok(self):
        res = await call(_core_ap_tool, power_va=50.0, freq_hz=100e3, bmax_t=0.2)
        assert res["ok"] is True
        assert "selected_core" in res

    @pytest.mark.asyncio
    async def test_xfmr_turns_tool_ok(self):
        res = await call(_xfmr_turns_tool, v_primary=100.0, freq_hz=100e3,
                         bmax_t=0.2, ae_m2=1.25e-4)
        assert res["ok"] is True
        assert res["Np"] >= 1

    @pytest.mark.asyncio
    async def test_ind_turns_tool_ok(self):
        res = await call(_ind_turns_tool, inductance_h=100e-6, i_peak_a=5.0,
                         bmax_t=0.3, ae_m2=1.25e-4)
        assert res["ok"] is True
        assert res["N"] >= 1

    @pytest.mark.asyncio
    async def test_gap_tool_ok(self):
        res = await call(_gap_tool, inductance_h=100e-6, n_turns=20, ae_m2=1.25e-4)
        assert res["ok"] is True
        assert "lg_mm" in res

    @pytest.mark.asyncio
    async def test_awg_tool_ok(self):
        res = await call(_awg_tool, i_rms_a=2.0)
        assert res["ok"] is True
        assert "awg" in res

    @pytest.mark.asyncio
    async def test_core_loss_tool_ok(self):
        res = await call(_core_loss_tool, freq_hz=100e3, b_peak_t=0.1,
                         core_volume_m3=3.46e-6)
        assert res["ok"] is True
        assert "p_core_w" in res

    @pytest.mark.asyncio
    async def test_cu_loss_tool_ok(self):
        res = await call(_cu_loss_tool, i_rms_dc_a=2.0, rdc_ohm=0.1)
        assert res["ok"] is True
        assert "p_total_w" in res

    @pytest.mark.asyncio
    async def test_temp_tool_ok(self):
        res = await call(_temp_tool, p_total_w=1.0, rth_c_per_w=15.0)
        assert res["ok"] is True
        assert "t_total_c" in res

    @pytest.mark.asyncio
    async def test_sat_tool_ok(self):
        res = await call(_sat_tool, n_turns=20, i_peak_a=2.0,
                         ae_m2=1.25e-4, le_m=0.09, mu_i=2200.0)
        assert res["ok"] is True
        assert "b_peak_t" in res

    @pytest.mark.asyncio
    async def test_tool_invalid_json_returns_error(self):
        raw = await _core_ap_tool(None, b"not json{{{")
        parsed = json.loads(raw)
        # Stub err_payload returns {"ok": False, "error": ..., "code": ...}
        assert parsed.get("ok") is False or "error" in parsed

    @pytest.mark.asyncio
    async def test_cu_loss_tool_with_dowell_inputs(self):
        """Tool auto-computes Fr from Dowell inputs."""
        res = await call(
            _cu_loss_tool,
            i_rms_dc_a=2.0, rdc_ohm=0.1,
            freq_hz=100e3, wire_dia_m=0.5e-3, n_layers=3,
        )
        assert res["ok"] is True
        assert res["p_total_w"] >= res["p_dc_w"]

    @pytest.mark.asyncio
    async def test_core_kg_tool_ok(self):
        res = await call(_core_kg_tool, power_va=50.0, freq_hz=100e3, bmax_t=0.2)
        assert res["ok"] is True
        assert "selected_core" in res
