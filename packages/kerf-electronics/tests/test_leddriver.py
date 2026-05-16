"""
Hermetic tests for kerf_electronics LED driver design module.

Covers (≥30 tests across all public functions):

  led_string_layout
    - Single string: n_series correct from supply/Vf arithmetic
    - Multiple parallel strings: n_parallel ceiling arithmetic
    - n_total == n_series × n_parallel
    - v_string_v == n_series × led_vf
    - total_lumens_achievable >= target_lumens
    - efficiency_lm_per_w == total_lumens / input_power
    - Zero headroom → ok=False
    - Non-positive supply → ok=False
    - Binning headroom >= 1.0 → ok=False
    - Warning when efficiency V_string/supply < 60 %
    - Warning when n_parallel > max_parallel_strings

  series_resistor
    - R = (V_supply - n × Vf) / If  hand-calc
    - P_R = R × If²  hand-calc
    - efficiency = V_string / V_supply
    - p_led_w = V_string × If
    - V_supply <= V_string → ok=False
    - n_series=0 → ok=False
    - Low efficiency warning issued

  driver_topology_choice
    - V_string < V_supply, high eff → topology == 'linear'
    - V_string < V_supply, low eff → topology == 'buck'
    - V_string > V_supply → topology == 'boost'
    - recommend_switching == False for linear
    - recommend_switching == True for buck/boost
    - p_linear_dissipation_w = V_drop × I_led
    - Invalid efficiency_threshold → ok=False

  buck_cc_design
    - D = V_string / (V_in × η)  hand-calc
    - L = V_in × D × (1-D) / (ΔI × fsw)  hand-calc
    - C = ΔI / (8 × fsw × ΔV)  hand-calc
    - i_l_peak = I_led + ΔI/2
    - i_l_valley = I_led - ΔI/2
    - v_sw_max == v_in
    - V_string >= V_in → ok=False
    - High duty cycle warning (D > 0.95)

  boost_cc_design
    - D = 1 - V_in × η / V_string  hand-calc
    - L = V_in × D / (ΔI × fsw)  hand-calc
    - v_sw_max == v_string
    - V_string <= V_in → ok=False
    - High duty cycle warning (D > 0.90)
    - i_in_a == I_led × V_string / (V_in × η)

  thermal_derating
    - T_j = T_amb + P × (Rth_jc + Rth_cs)  hand-calc
    - lm_derated = lm_rated × (1 - α × ΔT)
    - vf_derated = vf_rated × (1 - β × ΔT)
    - over_temp=True when T_j > tj_max_c
    - over_temp=False at low ambient
    - ΔT=0 at T_amb=25°C, no dissipation → no derating
    - Derating clamps at 0 (never negative lm/Vf)
    - Non-positive Rth → ok=False

  pwm_dimming
    - i_avg = duty_cycle × i_peak  hand-calc
    - brightness_ratio == duty_cycle
    - percent_flicker == 100.0
    - pwm_period_s == 1 / pwm_freq_hz
    - visible_flicker_risk True when freq < 1 kHz
    - visible_flicker_risk False when freq >= 1 kHz
    - duty_cycle=0 → ok=False (must be in (0,1])
    - Non-positive freq → ok=False

  LLM tool handlers
    - led_string_layout_tool happy path via tool stub
    - led_series_resistor_tool happy path
    - led_driver_topology_tool happy path
    - led_buck_cc_design_tool happy path
    - led_boost_cc_design_tool happy path
    - led_thermal_derating_tool happy path
    - led_pwm_dimming_tool happy path
    - Tools return ok=False JSON for bad args, never raise

Author: imranparuk
"""
from __future__ import annotations

import importlib.util
import json
import math
import os
import sys
import types

# ── Prefer real kerf_chat if installed; stub otherwise ───────────────────────
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

# ── Ensure src/ on path ───────────────────────────────────────────────────────
_HERE = os.path.dirname(os.path.abspath(__file__))
_SRC = os.path.join(os.path.dirname(_HERE), "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

import pytest

from kerf_electronics.leddriver.driver import (
    buck_cc_design,
    boost_cc_design,
    driver_topology_choice,
    led_string_layout,
    pwm_dimming,
    series_resistor,
    thermal_derating,
)

# ── Load tool module via importlib so the stub is active ─────────────────────
_tool_spec = importlib.util.spec_from_file_location(
    "kerf_electronics.leddriver.tools",
    os.path.join(_SRC, "kerf_electronics", "leddriver", "tools.py"),
)
_tool_mod = importlib.util.module_from_spec(_tool_spec)
_tool_spec.loader.exec_module(_tool_mod)

led_string_layout_tool = _tool_mod.led_string_layout_tool
led_series_resistor_tool = _tool_mod.led_series_resistor_tool
led_driver_topology_tool = _tool_mod.led_driver_topology_tool
led_buck_cc_design_tool = _tool_mod.led_buck_cc_design_tool
led_boost_cc_design_tool = _tool_mod.led_boost_cc_design_tool
led_thermal_derating_tool = _tool_mod.led_thermal_derating_tool
led_pwm_dimming_tool = _tool_mod.led_pwm_dimming_tool


# ── Async call helper ─────────────────────────────────────────────────────────

async def call(fn, **kwargs):
    result = await fn(None, json.dumps(kwargs).encode())
    return json.loads(result)


# ═══════════════════════════════════════════════════════════════════════════════
# 1. led_string_layout
# ═══════════════════════════════════════════════════════════════════════════════

class TestLedStringLayout:
    def test_single_string_n_series(self):
        """12V supply, 3V Vf, 1.5V headroom → floor((12-1.5)/3) = 3 series."""
        r = led_string_layout(12.0, 100.0, 3.0, 0.35, 50.0, vf_headroom_v=1.5)
        assert r["ok"] is True
        assert r["n_series"] == 3

    def test_v_string_equals_n_series_times_vf(self):
        r = led_string_layout(12.0, 100.0, 3.0, 0.35, 50.0, vf_headroom_v=1.5)
        assert r["ok"] is True
        assert abs(r["v_string_v"] - r["n_series"] * 3.0) < 1e-9

    def test_n_parallel_ceiling_arithmetic(self):
        """Need 200 lm, get 3 × 50 × 0.95 = 142.5 lm/string → ceil(200/142.5) = 2."""
        r = led_string_layout(12.0, 200.0, 3.0, 0.35, 50.0, vf_headroom_v=1.5, binning_headroom_frac=0.05)
        assert r["ok"] is True
        assert r["n_parallel"] == 2

    def test_n_total_equals_n_series_times_n_parallel(self):
        r = led_string_layout(24.0, 500.0, 3.2, 0.35, 80.0)
        assert r["ok"] is True
        assert r["n_total"] == r["n_series"] * r["n_parallel"]

    def test_total_lumens_achievable_gte_target(self):
        r = led_string_layout(24.0, 1000.0, 3.2, 0.35, 80.0, binning_headroom_frac=0.05)
        assert r["ok"] is True
        assert r["total_lumens_achievable"] >= 1000.0

    def test_efficiency_lm_per_w_formula(self):
        r = led_string_layout(12.0, 100.0, 3.0, 0.35, 50.0, vf_headroom_v=1.5)
        assert r["ok"] is True
        expected = r["total_lumens_achievable"] / r["input_power_w"]
        assert abs(r["efficiency_lm_per_w"] - expected) < 1e-3

    def test_input_power_w_formula(self):
        r = led_string_layout(12.0, 100.0, 3.0, 0.35, 50.0, vf_headroom_v=1.5)
        assert r["ok"] is True
        assert abs(r["input_power_w"] - 12.0 * r["i_total_a"]) < 1e-9

    def test_zero_headroom_returns_error(self):
        """vf_headroom_v == supply_v → no room."""
        r = led_string_layout(3.0, 100.0, 3.0, 0.35, 50.0, vf_headroom_v=3.0)
        assert r["ok"] is False

    def test_nonpositive_supply_returns_error(self):
        r = led_string_layout(0.0, 100.0, 3.0, 0.35, 50.0)
        assert r["ok"] is False

    def test_binning_headroom_gte_1_returns_error(self):
        r = led_string_layout(12.0, 100.0, 3.0, 0.35, 50.0, binning_headroom_frac=1.0)
        assert r["ok"] is False

    def test_warning_low_efficiency(self):
        """12V supply, 1V Vf, 1.5V headroom → available=10.5V → n_series=10 → v_string=10V
           efficiency = 10/12 = 83 % > 60 % — no warning.
           Use a scenario where V_string is forced small:
           5V supply, 1V Vf, 4V headroom → available=1V → n_series=1 → v_string=1V
           efficiency = 1/5 = 20 % < 60 % → warning."""
        import warnings as _w
        with _w.catch_warnings(record=True) as caught:
            _w.simplefilter("always")
            r = led_string_layout(5.0, 10.0, 1.0, 0.35, 50.0, vf_headroom_v=4.0)
        assert r["ok"] is True
        # efficiency = 1/5 = 20% → low warning
        assert any("efficiency_low" in str(w.message) for w in caught)

    def test_warning_exceeds_max_parallel(self):
        import warnings as _w
        with _w.catch_warnings(record=True) as caught:
            _w.simplefilter("always")
            # Force many parallel: tiny lm per LED, huge target
            r = led_string_layout(12.0, 10000.0, 3.0, 0.35, 1.0,
                                  vf_headroom_v=1.5, max_parallel_strings=3)
        assert r["ok"] is True
        assert r["n_parallel"] > 3
        assert any("exceeds_max_parallel" in str(w.message) for w in caught)


# ═══════════════════════════════════════════════════════════════════════════════
# 2. series_resistor
# ═══════════════════════════════════════════════════════════════════════════════

class TestSeriesResistor:
    def test_r_hand_calc(self):
        """12V supply, 3.2V Vf, 0.35A → R = (12-3.2)/0.35 = 25.143 Ω."""
        r = series_resistor(12.0, 3.2, 0.35, n_series=1)
        assert r["ok"] is True
        expected_r = (12.0 - 3.2) / 0.35
        assert abs(r["r_series_ohm"] - expected_r) < 1e-6

    def test_p_resistor_hand_calc(self):
        r = series_resistor(12.0, 3.2, 0.35, n_series=1)
        expected_r = (12.0 - 3.2) / 0.35
        expected_p = expected_r * 0.35 ** 2
        assert abs(r["p_resistor_w"] - expected_p) < 1e-6

    def test_efficiency_formula(self):
        """efficiency = V_string / V_supply = 3.2 / 12."""
        r = series_resistor(12.0, 3.2, 0.35, n_series=1)
        assert abs(r["efficiency"] - 3.2 / 12.0) < 1e-6

    def test_p_led_formula(self):
        """p_led = V_string × If = 3.2 × 0.35."""
        r = series_resistor(12.0, 3.2, 0.35, n_series=1)
        assert abs(r["p_led_w"] - 3.2 * 0.35) < 1e-9

    def test_v_string_v_formula(self):
        """n_series=3: v_string = 3 × 3.2 = 9.6 V."""
        r = series_resistor(24.0, 3.2, 0.35, n_series=3)
        assert r["ok"] is True
        assert abs(r["v_string_v"] - 3 * 3.2) < 1e-9

    def test_supply_lte_string_returns_error(self):
        """5V supply, 3 LEDs × 2V = 6V → supply < string."""
        r = series_resistor(5.0, 2.0, 0.35, n_series=3)
        assert r["ok"] is False

    def test_n_series_zero_returns_error(self):
        r = series_resistor(12.0, 3.2, 0.35, n_series=0)
        assert r["ok"] is False

    def test_low_efficiency_warning(self):
        """3V supply, 1.5V Vf → 50% efficiency → warning."""
        import warnings as _w
        with _w.catch_warnings(record=True) as caught:
            _w.simplefilter("always")
            r = series_resistor(3.0, 1.5, 0.1, n_series=1)
        assert r["ok"] is True
        assert any("efficiency_low" in str(w.message) for w in caught)

    def test_n_series_multi(self):
        """3 series LEDs: R = (24 - 3×3.2) / 0.35 = (24-9.6)/0.35."""
        r = series_resistor(24.0, 3.2, 0.35, n_series=3)
        assert r["ok"] is True
        expected_r = (24.0 - 9.6) / 0.35
        assert abs(r["r_series_ohm"] - expected_r) < 1e-6


# ═══════════════════════════════════════════════════════════════════════════════
# 3. driver_topology_choice
# ═══════════════════════════════════════════════════════════════════════════════

class TestDriverTopologyChoice:
    def test_linear_topology_high_efficiency(self):
        """12V supply, 10V string → 83% ≥ 80% → linear."""
        r = driver_topology_choice(12.0, 10.0, 0.35, efficiency_threshold=0.80)
        assert r["ok"] is True
        assert r["topology"] == "linear"
        assert r["recommend_switching"] is False

    def test_buck_topology_low_efficiency(self):
        """12V supply, 3V string → 25% < 80% → buck."""
        r = driver_topology_choice(12.0, 3.0, 0.35, efficiency_threshold=0.80)
        assert r["ok"] is True
        assert r["topology"] == "buck"
        assert r["recommend_switching"] is True

    def test_boost_topology_when_string_exceeds_supply(self):
        """5V supply, 12V string → boost."""
        r = driver_topology_choice(5.0, 12.0, 0.35)
        assert r["ok"] is True
        assert r["topology"] == "boost"
        assert r["recommend_switching"] is True

    def test_p_linear_dissipation_formula(self):
        """P_linear = (V_supply - V_string) × I = (12-10) × 0.35 = 0.7 W."""
        r = driver_topology_choice(12.0, 10.0, 0.35)
        assert r["ok"] is True
        assert abs(r["p_linear_dissipation_w"] - 2.0 * 0.35) < 1e-9

    def test_linear_efficiency_formula(self):
        r = driver_topology_choice(12.0, 10.0, 0.35)
        assert abs(r["linear_efficiency"] - 10.0 / 12.0) < 1e-5

    def test_invalid_efficiency_threshold_returns_error(self):
        r = driver_topology_choice(12.0, 10.0, 0.35, efficiency_threshold=1.5)
        assert r["ok"] is False

    def test_v_drop_formula(self):
        r = driver_topology_choice(12.0, 8.0, 0.5)
        assert abs(r["v_drop_v"] - 4.0) < 1e-9


# ═══════════════════════════════════════════════════════════════════════════════
# 4. buck_cc_design
# ═══════════════════════════════════════════════════════════════════════════════

class TestBuckCcDesign:
    def _base(self):
        return buck_cc_design(
            v_in=24.0, v_string=12.0, i_led=0.35,
            fsw_hz=200e3, inductor_ripple_frac=0.20,
            cap_ripple_v=0.05, eta=0.90,
        )

    def test_duty_cycle_hand_calc(self):
        """D = 12 / (24 × 0.90) = 0.5556."""
        r = self._base()
        assert r["ok"] is True
        expected_d = 12.0 / (24.0 * 0.90)
        assert abs(r["duty_cycle"] - expected_d) < 1e-5

    def test_inductor_hand_calc(self):
        """L = V_in × D × (1-D) / (ΔI × fsw)."""
        r = self._base()
        D = 12.0 / (24.0 * 0.90)
        delta_il = 0.20 * 0.35
        expected_l = 24.0 * D * (1 - D) / (delta_il * 200e3)
        assert abs(r["l_inductor_h"] - expected_l) < 1e-9

    def test_cap_hand_calc(self):
        """C = ΔI / (8 × fsw × ΔV)."""
        r = self._base()
        delta_il = 0.20 * 0.35
        expected_c = delta_il / (8 * 200e3 * 0.05)
        assert abs(r["c_out_f"] - expected_c) < 1e-11

    def test_i_l_peak_formula(self):
        r = self._base()
        assert abs(r["i_l_peak_a"] - (0.35 + r["delta_il_a"] / 2)) < 1e-9

    def test_i_l_valley_formula(self):
        r = self._base()
        assert abs(r["i_l_valley_a"] - (0.35 - r["delta_il_a"] / 2)) < 1e-9

    def test_v_sw_max_equals_v_in(self):
        r = self._base()
        assert abs(r["v_sw_max_v"] - 24.0) < 1e-9

    def test_v_string_gte_v_in_returns_error(self):
        r = buck_cc_design(v_in=12.0, v_string=24.0, i_led=0.35, fsw_hz=200e3)
        assert r["ok"] is False

    def test_high_duty_cycle_warning(self):
        """V_string = 22V, V_in = 24V, η=0.95 → D = 22/(24×0.95) ≈ 0.965 > 0.95."""
        import warnings as _w
        with _w.catch_warnings(record=True) as caught:
            _w.simplefilter("always")
            r = buck_cc_design(v_in=24.0, v_string=22.0, i_led=0.35,
                               fsw_hz=200e3, eta=0.95)
        assert r["ok"] is True
        assert any("duty_cycle_high" in str(w.message) for w in caught)


# ═══════════════════════════════════════════════════════════════════════════════
# 5. boost_cc_design
# ═══════════════════════════════════════════════════════════════════════════════

class TestBoostCcDesign:
    def _base(self):
        return boost_cc_design(
            v_in=5.0, v_string=12.0, i_led=0.35,
            fsw_hz=200e3, inductor_ripple_frac=0.20,
            cap_ripple_v=0.10, eta=0.88,
        )

    def test_duty_cycle_hand_calc(self):
        """D = 1 − 5 × 0.88 / 12 = 1 − 0.3667 = 0.6333."""
        r = self._base()
        assert r["ok"] is True
        expected_d = 1.0 - 5.0 * 0.88 / 12.0
        assert abs(r["duty_cycle"] - expected_d) < 1e-5

    def test_i_in_hand_calc(self):
        """I_in = I_led × V_string / (V_in × η) = 0.35 × 12 / (5 × 0.88)."""
        r = self._base()
        expected_iin = 0.35 * 12.0 / (5.0 * 0.88)
        assert abs(r["i_in_a"] - expected_iin) < 1e-6

    def test_inductor_hand_calc(self):
        """L = V_in × D / (ΔI × fsw)."""
        r = self._base()
        D = 1.0 - 5.0 * 0.88 / 12.0
        i_in = 0.35 * 12.0 / (5.0 * 0.88)
        delta_il = 0.20 * i_in
        expected_l = 5.0 * D / (delta_il * 200e3)
        assert abs(r["l_inductor_h"] - expected_l) < 1e-9

    def test_cap_hand_calc(self):
        """C = I_led × D / (fsw × ΔV)."""
        r = self._base()
        D = 1.0 - 5.0 * 0.88 / 12.0
        expected_c = 0.35 * D / (200e3 * 0.10)
        assert abs(r["c_out_f"] - expected_c) < 1e-11

    def test_v_sw_max_equals_v_string(self):
        r = self._base()
        assert abs(r["v_sw_max_v"] - 12.0) < 1e-9

    def test_v_string_lte_v_in_returns_error(self):
        r = boost_cc_design(v_in=24.0, v_string=12.0, i_led=0.35, fsw_hz=200e3)
        assert r["ok"] is False

    def test_high_duty_cycle_warning(self):
        """V_in=3V, V_string=30V, η=0.88 → D = 1 - 3×0.88/30 = 0.912 > 0.90."""
        import warnings as _w
        with _w.catch_warnings(record=True) as caught:
            _w.simplefilter("always")
            r = boost_cc_design(v_in=3.0, v_string=30.0, i_led=0.35, fsw_hz=200e3, eta=0.88)
        assert r["ok"] is True
        assert any("duty_cycle_high" in str(w.message) for w in caught)


# ═══════════════════════════════════════════════════════════════════════════════
# 6. thermal_derating
# ═══════════════════════════════════════════════════════════════════════════════

class TestThermalDerating:
    def test_junction_temp_hand_calc(self):
        """T_j = 25 + 1.0 × (5 + 3) = 33 °C."""
        r = thermal_derating(1.0, 5.0, 3.0, 25.0, 100.0, 3.2)
        assert r["ok"] is True
        assert abs(r["t_junction_c"] - 33.0) < 1e-6

    def test_delta_t_formula(self):
        r = thermal_derating(1.0, 5.0, 3.0, 25.0, 100.0, 3.2)
        assert abs(r["delta_t_k"] - (r["t_junction_c"] - 25.0)) < 1e-9

    def test_lm_derated_formula(self):
        """T_j=33°C, ΔT=8K, derating=0.5%/K → lm_derated = 100 × (1 - 0.005×8) = 96."""
        r = thermal_derating(1.0, 5.0, 3.0, 25.0, 100.0, 3.2,
                             lm_derating_per_k=0.005, vf_derating_per_k=0.002)
        expected_lm = 100.0 * (1.0 - 0.005 * 8.0)
        assert abs(r["lm_derated"] - expected_lm) < 1e-6

    def test_vf_derated_formula(self):
        """vf_derated = 3.2 × (1 - 0.002×8) = 3.2 × 0.984."""
        r = thermal_derating(1.0, 5.0, 3.0, 25.0, 100.0, 3.2,
                             lm_derating_per_k=0.005, vf_derating_per_k=0.002)
        expected_vf = 3.2 * (1.0 - 0.002 * 8.0)
        assert abs(r["vf_derated_v"] - expected_vf) < 1e-6

    def test_over_temp_true(self):
        """1W into 200 °C/W total: T_j = 25 + 200 = 225 °C > 125 °C."""
        r = thermal_derating(1.0, 150.0, 50.0, 25.0, 100.0, 3.2, tj_max_c=125.0)
        assert r["ok"] is True
        assert r["over_temp"] is True

    def test_over_temp_false_cold(self):
        """Very low power, cold ambient."""
        r = thermal_derating(0.01, 5.0, 2.0, 20.0, 100.0, 3.2, tj_max_c=125.0)
        assert r["ok"] is True
        assert r["over_temp"] is False

    def test_no_derating_at_25c_ambient_zero_power(self):
        """P=0 not allowed (must be positive). Use tiny P."""
        r = thermal_derating(1e-9, 5.0, 3.0, 25.0, 100.0, 3.2)
        assert r["ok"] is True
        # ΔT ≈ 0 → derating ≈ 0
        assert r["lm_derating_frac"] < 1e-6

    def test_over_temp_warning_issued(self):
        import warnings as _w
        with _w.catch_warnings(record=True) as caught:
            _w.simplefilter("always")
            thermal_derating(5.0, 20.0, 10.0, 25.0, 100.0, 3.2, tj_max_c=100.0)
        assert any("over_temp" in str(w.message) for w in caught)

    def test_nonpositive_rth_returns_error(self):
        r = thermal_derating(1.0, 0.0, 3.0, 25.0, 100.0, 3.2)
        assert r["ok"] is False

    def test_lm_clamped_to_zero_not_negative(self):
        """Extreme derating: very high ΔT should clamp to 0, not go negative."""
        r = thermal_derating(10.0, 50.0, 50.0, 25.0, 100.0, 3.2,
                             lm_derating_per_k=0.02)  # 2%/K
        assert r["ok"] is True
        assert r["lm_derated"] >= 0.0


# ═══════════════════════════════════════════════════════════════════════════════
# 7. pwm_dimming
# ═══════════════════════════════════════════════════════════════════════════════

class TestPwmDimming:
    def test_i_avg_formula(self):
        """I_avg = 0.5 × 0.35 = 0.175 A."""
        r = pwm_dimming(1000.0, 0.5, 0.35)
        assert r["ok"] is True
        assert abs(r["i_avg_a"] - 0.5 * 0.35) < 1e-9

    def test_brightness_ratio_equals_duty_cycle(self):
        r = pwm_dimming(1000.0, 0.25, 0.35)
        assert abs(r["brightness_ratio"] - 0.25) < 1e-9

    def test_percent_flicker_is_100(self):
        """Ideal PWM: on=I_peak, off=0 → percent_flicker = 100."""
        r = pwm_dimming(1000.0, 0.5, 0.35)
        assert r["percent_flicker"] == 100.0

    def test_pwm_period_formula(self):
        """Period = 1 / 500 Hz = 2 ms."""
        r = pwm_dimming(500.0, 0.5, 0.35)
        assert abs(r["pwm_period_s"] - 1.0 / 500.0) < 1e-12

    def test_visible_flicker_risk_true_below_1khz(self):
        """100 Hz PWM → visible_flicker_risk = True."""
        r = pwm_dimming(100.0, 0.5, 0.35)
        assert r["ok"] is True
        assert r["visible_flicker_risk"] is True

    def test_visible_flicker_risk_false_at_1khz(self):
        """1000 Hz (exactly at threshold) → NOT below threshold."""
        r = pwm_dimming(1000.0, 0.5, 0.35)
        assert r["ok"] is True
        assert r["visible_flicker_risk"] is False

    def test_visible_flicker_risk_false_above_1khz(self):
        r = pwm_dimming(10000.0, 0.1, 0.35)
        assert r["visible_flicker_risk"] is False

    def test_duty_cycle_zero_returns_error(self):
        r = pwm_dimming(1000.0, 0.0, 0.35)
        assert r["ok"] is False

    def test_nonpositive_freq_returns_error(self):
        r = pwm_dimming(0.0, 0.5, 0.35)
        assert r["ok"] is False

    def test_i_avg_scales_with_duty_cycle(self):
        """Double duty cycle → double I_avg."""
        r1 = pwm_dimming(1000.0, 0.25, 0.35)
        r2 = pwm_dimming(1000.0, 0.50, 0.35)
        assert abs(r2["i_avg_a"] / r1["i_avg_a"] - 2.0) < 1e-6


# ═══════════════════════════════════════════════════════════════════════════════
# 8. LLM tool handlers
# ═══════════════════════════════════════════════════════════════════════════════

class TestToolHandlers:
    @pytest.mark.asyncio
    async def test_string_layout_tool_happy(self):
        r = await call(led_string_layout_tool,
                       supply_v=12.0, target_lumens=200.0,
                       led_vf=3.0, led_if_a=0.35, led_lumens=50.0)
        assert r["ok"] is True
        assert "n_series" in r

    @pytest.mark.asyncio
    async def test_series_resistor_tool_happy(self):
        r = await call(led_series_resistor_tool, supply_v=12.0, led_vf=3.2, led_if_a=0.35)
        assert r["ok"] is True
        assert "r_series_ohm" in r

    @pytest.mark.asyncio
    async def test_driver_topology_tool_happy(self):
        r = await call(led_driver_topology_tool,
                       supply_v=12.0, v_string_v=10.0, led_if_a=0.35)
        assert r["ok"] is True
        assert r["topology"] == "linear"

    @pytest.mark.asyncio
    async def test_buck_cc_tool_happy(self):
        r = await call(led_buck_cc_design_tool,
                       v_in=24.0, v_string=12.0, i_led=0.35, fsw_hz=200000.0)
        assert r["ok"] is True
        assert "duty_cycle" in r

    @pytest.mark.asyncio
    async def test_boost_cc_tool_happy(self):
        r = await call(led_boost_cc_design_tool,
                       v_in=5.0, v_string=12.0, i_led=0.35, fsw_hz=200000.0)
        assert r["ok"] is True
        assert "duty_cycle" in r

    @pytest.mark.asyncio
    async def test_thermal_tool_happy(self):
        r = await call(led_thermal_derating_tool,
                       p_dissipated_w=1.0, rth_jc=5.0, rth_cs=3.0,
                       t_ambient_c=25.0, lm_rated=100.0, vf_rated_v=3.2)
        assert r["ok"] is True
        assert "t_junction_c" in r

    @pytest.mark.asyncio
    async def test_pwm_dimming_tool_happy(self):
        r = await call(led_pwm_dimming_tool,
                       pwm_freq_hz=1000.0, duty_cycle=0.5, i_peak_a=0.35)
        assert r["ok"] is True
        assert abs(r["i_avg_a"] - 0.175) < 1e-6

    @pytest.mark.asyncio
    async def test_bad_args_return_ok_false_not_raise(self):
        r = await call(led_series_resistor_tool, supply_v=-1.0, led_vf=3.2, led_if_a=0.35)
        # Real registry err_payload has no "ok" key; stub includes it
        assert r.get("ok") is False or "error" in r

    @pytest.mark.asyncio
    async def test_buck_bad_args_not_raise(self):
        r = await call(led_buck_cc_design_tool,
                       v_in=5.0, v_string=24.0, i_led=0.35, fsw_hz=200000.0)
        # Real registry err_payload has no "ok" key; stub includes it
        assert r.get("ok") is False or "error" in r
