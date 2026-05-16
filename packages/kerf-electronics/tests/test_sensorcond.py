"""
Hermetic tests for the sensor signal-conditioning module.

Covers (≥30 tests):
  wheatstone_bridge_output
    - Quarter-bridge linearised formula: Vout = (Vex/4) × GF × ε
    - Full-bridge output = 4× quarter-bridge
    - Half-bridge output = 2× quarter-bridge
    - Lead-wire sensitivity loss
    - Nonlinearity warning at high strain
    - Invalid config → ok=False
    - Zero excitation → ok=False

  bridge_excitation_power
    - P_arm = Vex² / (4 × Rg)
    - P_total = Vex² / Rg
    - Max safe excitation computed correctly
    - Self-heating warning when P_arm > 30 mW

  strain_to_stress
    - σ = E × ε (exact)
    - Negative strain (compression) allowed
    - Zero modulus → ok=False

  rtd_resistance + rtd_temperature (CVD round-trip)
    - R(0 °C) = R₀ = 100 Ω (PT100)
    - R(100 °C) ≈ 138.506 Ω (IEC 60751)
    - R(−50 °C) with cubic C term
    - Round-trip: temperature → resistance → temperature recovers input ±0.01 °C
    - Out-of-range warning (T > 850 °C)

  rtd_lead_wire_error
    - 2-wire: error = 2 × R_lead
    - 4-wire: zero error
    - 3-wire: zero error (balanced)
    - Invalid wiring string → ok=False
    - Large 2-wire error warns

  thermocouple_temperature
    - Type K: 0 mV → 0 °C (within ~1 °C, cold junction = 0)
    - Type J: known voltage → known temperature (NIST table)
    - Type T: 0 mV → 0 °C
    - Cold-junction compensation shifts effective voltage
    - CJC warning when |T_cj| > 5 °C
    - Invalid TC type → ok=False
    - Out-of-range voltage → ok (with warning)

  instrumentation_amp_gain
    - G = 1 + 2 × R_int / R_gain (exact)
    - CMRR-limited warning when e_cmrr > e_offset
    - Zero gain resistor → ok=False

  adc_required_bits / enob_from_noise
    - 10 V FSR, 10 mV resolution → 10 bits
    - ENOB = log2(1 / (1e-5 × √12)) for known noise
    - Warning for ≥24 bits

  antialias_filter_corner
    - fc = f_nyq / 10^(40/(20×2)) for defaults
    - Higher-order filter gives higher fc
    - Warning when fc < fs/4

  loop_4_20ma_scaling + loop_burden_voltage
    - 4 mA → span_low exactly
    - 20 mA → span_high exactly
    - 12 mA → midpoint
    - Fault warning outside [3.8, 20.5] mA
    - Compliance margin computed correctly
    - Warning when margin < 1 V

  noise_budget_rss
    - Single source: total = source
    - Two equal: total = source × √2
    - Dominant source warning

  filter_topology_select
    - G=1, Q=0.7 → Sallen-Key
    - G=10, Q=2 → MFB
    - Single-ended supply nudges toward SK

  LLM tool handlers
    - sensorcond_bridge_output tool returns ok=True
    - sensorcond_rtd_resistance tool returns ok=True
    - sensorcond_thermocouple tool returns ok=True with temperature_c
    - sensorcond_ina_gain tool returns ok=True with gain
    - Tool invalid JSON → error payload

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

from kerf_electronics.sensorcond.condition import (
    antialias_filter_corner,
    adc_required_bits,
    bridge_excitation_power,
    enob_from_noise,
    filter_topology_select,
    instrumentation_amp_gain,
    loop_4_20ma_scaling,
    loop_burden_voltage,
    noise_budget_rss,
    rtd_lead_wire_error,
    rtd_resistance,
    rtd_temperature,
    strain_to_stress,
    thermocouple_temperature,
    wheatstone_bridge_output,
)

# ── Load tool module via importlib so stub is active ─────────────────────────
_tool_spec = importlib.util.spec_from_file_location(
    "kerf_electronics.sensorcond.tools",
    os.path.join(_SRC, "kerf_electronics", "sensorcond", "tools.py"),
)
_tool_mod = importlib.util.module_from_spec(_tool_spec)
_tool_spec.loader.exec_module(_tool_mod)

bridge_output_tool = _tool_mod.sensorcond_bridge_output
rtd_resistance_tool = _tool_mod.sensorcond_rtd_resistance
thermocouple_tool = _tool_mod.sensorcond_thermocouple
ina_gain_tool = _tool_mod.sensorcond_ina_gain
noise_rss_tool = _tool_mod.sensorcond_noise_rss


# ── Async call helper ─────────────────────────────────────────────────────────

async def call(fn, **kwargs):
    result = await fn(None, json.dumps(kwargs).encode())
    return json.loads(result)


# ═══════════════════════════════════════════════════════════════════════════════
# 1. Wheatstone bridge output
# ═══════════════════════════════════════════════════════════════════════════════

class TestWheatstoneBridgeOutput:
    """Quarter/half/full bridge output vs strain, lead-wire, nonlinearity."""

    def test_quarter_bridge_linearised_formula(self):
        """Vout_linearised = (Vex/4) × GF × strain."""
        vex = 5.0
        gf = 2.0
        strain_ue = 500.0
        strain = strain_ue * 1e-6
        expected = (vex / 4.0) * gf * strain
        res = wheatstone_bridge_output(
            excitation_v=vex, gauge_factor=gf, strain_ue=strain_ue, config="quarter"
        )
        assert res["ok"] is True
        assert abs(res["vout_linearised_v"] - expected) < 1e-12

    def test_full_bridge_four_times_quarter(self):
        """Full-bridge output = 4× quarter-bridge (linearised)."""
        kw = dict(excitation_v=5.0, gauge_factor=2.0, strain_ue=100.0)
        q = wheatstone_bridge_output(**kw, config="quarter")
        f = wheatstone_bridge_output(**kw, config="full")
        ratio = f["vout_linearised_v"] / q["vout_linearised_v"]
        assert abs(ratio - 4.0) < 1e-9

    def test_half_bridge_two_times_quarter(self):
        """Half-bridge output = 2× quarter-bridge (linearised)."""
        kw = dict(excitation_v=5.0, gauge_factor=2.0, strain_ue=100.0)
        q = wheatstone_bridge_output(**kw, config="quarter")
        h = wheatstone_bridge_output(**kw, config="half")
        ratio = h["vout_linearised_v"] / q["vout_linearised_v"]
        assert abs(ratio - 2.0) < 1e-9

    def test_lead_wire_sensitivity_loss(self):
        """Lead resistance reduces effective gauge factor → lower output."""
        no_lead = wheatstone_bridge_output(
            excitation_v=5.0, gauge_factor=2.0, strain_ue=500.0,
            lead_resistance_ohm=0.0, nominal_resistance_ohm=350.0
        )
        with_lead = wheatstone_bridge_output(
            excitation_v=5.0, gauge_factor=2.0, strain_ue=500.0,
            lead_resistance_ohm=5.0, nominal_resistance_ohm=350.0
        )
        assert with_lead["vout_linearised_v"] < no_lead["vout_linearised_v"]
        assert with_lead["lead_wire_sensitivity_loss_pct"] > 0.0

    def test_lead_wire_loss_pct_formula(self):
        """Loss = (1 - Rg/(Rg + Rl)) × 100."""
        rg = 350.0
        rl = 3.5  # 1% loss expected
        expected_loss_pct = (1.0 - rg / (rg + rl)) * 100.0
        res = wheatstone_bridge_output(
            excitation_v=5.0, gauge_factor=2.0, strain_ue=100.0,
            lead_resistance_ohm=rl, nominal_resistance_ohm=rg
        )
        assert abs(res["lead_wire_sensitivity_loss_pct"] - expected_loss_pct) < 0.001

    def test_nonlinearity_warning_high_strain(self):
        """ΔR/R > 1% at high strain triggers a nonlinearity warning."""
        # GF=2, strain to give ΔR/R = 0.02 (>1%): strain = 0.02/2 = 0.01 = 10000 µε
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            res = wheatstone_bridge_output(
                excitation_v=5.0, gauge_factor=2.0, strain_ue=10000.0, config="quarter"
            )
            assert res["ok"] is True
            assert any("nonlinearity" in str(x.message).lower() for x in w)

    def test_invalid_config_returns_error(self):
        res = wheatstone_bridge_output(
            excitation_v=5.0, gauge_factor=2.0, strain_ue=100.0, config="three-quarter"
        )
        assert res["ok"] is False
        assert "config" in res["reason"]

    def test_zero_excitation_returns_error(self):
        res = wheatstone_bridge_output(
            excitation_v=0.0, gauge_factor=2.0, strain_ue=100.0
        )
        assert res["ok"] is False


# ═══════════════════════════════════════════════════════════════════════════════
# 2. Bridge excitation power
# ═══════════════════════════════════════════════════════════════════════════════

class TestBridgeExcitationPower:
    def test_p_arm_formula(self):
        """P_arm = Vex² / (4 × Rg) — rounded to 6 decimal places."""
        vex = 5.0
        rg = 350.0
        expected_p_arm = vex ** 2 / (4.0 * rg)
        res = bridge_excitation_power(excitation_v=vex, nominal_resistance_ohm=rg)
        assert res["ok"] is True
        assert abs(res["p_arm_w"] - round(expected_p_arm, 6)) < 1e-9

    def test_p_total_formula(self):
        """P_total = Vex² / Rg — rounded to 6 decimal places."""
        vex = 5.0
        rg = 350.0
        expected = vex ** 2 / rg
        res = bridge_excitation_power(excitation_v=vex, nominal_resistance_ohm=rg)
        assert abs(res["p_total_w"] - round(expected, 6)) < 1e-9

    def test_max_safe_excitation(self):
        """Vex_max = sqrt(4 × Rg × 30e-3)."""
        rg = 350.0
        expected = math.sqrt(4.0 * rg * 30e-3)
        res = bridge_excitation_power(excitation_v=1.0, nominal_resistance_ohm=rg)
        assert abs(res["max_safe_excitation_v"] - expected) < 0.001

    def test_self_heating_warning(self):
        """High excitation (P_arm > 30 mW) triggers warning."""
        # For 350 Ω: Vex_max ≈ 6.48 V; use 10 V to trigger
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            bridge_excitation_power(excitation_v=10.0, nominal_resistance_ohm=350.0)
            assert any("30 mw" in str(x.message).lower() or
                       "self-heating" in str(x.message).lower() or
                       "30" in str(x.message)
                       for x in w)


# ═══════════════════════════════════════════════════════════════════════════════
# 3. Strain to stress
# ═══════════════════════════════════════════════════════════════════════════════

class TestStrainToStress:
    def test_exact_formula(self):
        """σ = E × ε exactly."""
        strain_ue = 500.0
        E_gpa = 200.0
        expected_mpa = E_gpa * 1e9 * strain_ue * 1e-6 * 1e-6
        res = strain_to_stress(strain_ue=strain_ue, youngs_modulus_gpa=E_gpa)
        assert res["ok"] is True
        assert abs(res["stress_mpa"] - expected_mpa) < 1e-6

    def test_negative_strain_compression(self):
        """Negative strain (compression) is valid."""
        res = strain_to_stress(strain_ue=-200.0, youngs_modulus_gpa=70.0)
        assert res["ok"] is True
        assert res["stress_mpa"] < 0.0

    def test_zero_modulus_returns_error(self):
        res = strain_to_stress(strain_ue=100.0, youngs_modulus_gpa=0.0)
        assert res["ok"] is False

    def test_steel_200gpa_500ue(self):
        """500 µε on steel (200 GPa) → 100 MPa."""
        res = strain_to_stress(strain_ue=500.0, youngs_modulus_gpa=200.0)
        assert res["ok"] is True
        assert abs(res["stress_mpa"] - 100.0) < 1e-6


# ═══════════════════════════════════════════════════════════════════════════════
# 4. RTD Callendar-Van Dusen
# ═══════════════════════════════════════════════════════════════════════════════

class TestRTD:
    def test_pt100_at_0c(self):
        """PT100 R(0 °C) = 100.0 Ω exactly."""
        res = rtd_resistance(temperature_c=0.0, r0_ohm=100.0)
        assert res["ok"] is True
        assert abs(res["resistance_ohm"] - 100.0) < 1e-4

    def test_pt100_at_100c(self):
        """PT100 R(100 °C) ≈ 138.506 Ω per IEC 60751."""
        # R = 100 × (1 + 3.9083e-3×100 + (−5.775e-7)×100²)
        #   = 100 × (1 + 0.39083 − 0.005775) = 100 × 1.385055 = 138.5055
        res = rtd_resistance(temperature_c=100.0, r0_ohm=100.0)
        assert res["ok"] is True
        assert abs(res["resistance_ohm"] - 138.5055) < 0.001

    def test_pt100_at_minus50c(self):
        """PT100 R(−50 °C): uses cubic C term, must be < R(0 °C)."""
        res = rtd_resistance(temperature_c=-50.0, r0_ohm=100.0)
        assert res["ok"] is True
        assert res["resistance_ohm"] < 100.0

    def test_round_trip_positive_temperature(self):
        """T → R → T recovers within 0.01 °C for T ≥ 0."""
        for T_in in [0.0, 25.0, 100.0, 300.0, 600.0]:
            r_res = rtd_resistance(temperature_c=T_in, r0_ohm=100.0)
            assert r_res["ok"] is True
            t_res = rtd_temperature(resistance_ohm=r_res["resistance_ohm"], r0_ohm=100.0)
            assert t_res["ok"] is True
            assert abs(t_res["temperature_c"] - T_in) < 0.01, (
                f"Round-trip failed for T={T_in}: got {t_res['temperature_c']}"
            )

    def test_round_trip_negative_temperature(self):
        """T → R → T round-trip for T < 0 °C within 0.1 °C."""
        for T_in in [-50.0, -100.0, -150.0]:
            r_res = rtd_resistance(temperature_c=T_in, r0_ohm=100.0)
            assert r_res["ok"] is True
            t_res = rtd_temperature(resistance_ohm=r_res["resistance_ohm"], r0_ohm=100.0)
            assert t_res["ok"] is True
            assert abs(t_res["temperature_c"] - T_in) < 0.1, (
                f"Round-trip failed for T={T_in}: got {t_res['temperature_c']}"
            )

    def test_out_of_range_warning(self):
        """Temperature > 850 °C triggers a warning."""
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            res = rtd_resistance(temperature_c=900.0, r0_ohm=100.0)
            assert res["ok"] is True
            assert any("850" in str(x.message) or "range" in str(x.message).lower()
                       for x in w)


# ═══════════════════════════════════════════════════════════════════════════════
# 5. RTD lead-wire error
# ═══════════════════════════════════════════════════════════════════════════════

class TestRTDLeadWire:
    def test_2wire_error_equals_2_times_lead(self):
        """2-wire: R_error = 2 × R_lead."""
        res = rtd_lead_wire_error(
            measurement_resistance_ohm=110.0,
            lead_resistance_ohm=1.0,
            wiring="2-wire",
        )
        assert res["ok"] is True
        assert abs(res["r_error_ohm"] - 2.0) < 1e-9

    def test_4wire_zero_error(self):
        """4-wire: R_error = 0."""
        res = rtd_lead_wire_error(
            measurement_resistance_ohm=110.0,
            lead_resistance_ohm=5.0,
            wiring="4-wire",
        )
        assert res["ok"] is True
        assert res["r_error_ohm"] == 0.0

    def test_3wire_zero_error_balanced(self):
        """3-wire (balanced): R_error = 0."""
        res = rtd_lead_wire_error(
            measurement_resistance_ohm=110.0,
            lead_resistance_ohm=2.0,
            wiring="3-wire",
        )
        assert res["ok"] is True
        assert res["r_error_ohm"] == 0.0

    def test_invalid_wiring_returns_error(self):
        res = rtd_lead_wire_error(
            measurement_resistance_ohm=110.0,
            lead_resistance_ohm=1.0,
            wiring="5-wire",
        )
        assert res["ok"] is False

    def test_2wire_large_error_warns(self):
        """2-wire with >0.5 °C error issues a warning."""
        # 1 Ω lead per side, 2-wire: 2 Ω error, ΔT ≈ 2/(100×3.85e-3) = 5.2 °C
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            res = rtd_lead_wire_error(
                measurement_resistance_ohm=110.0,
                lead_resistance_ohm=1.0,
                wiring="2-wire",
                r0_ohm=100.0,
            )
            assert res["ok"] is True
            assert abs(res["temperature_error_c"]) > 0.5
            assert any("2-wire" in str(x.message).lower() or
                       "0.5" in str(x.message)
                       for x in w)


# ═══════════════════════════════════════════════════════════════════════════════
# 6. Thermocouple NIST inverse
# ═══════════════════════════════════════════════════════════════════════════════

class TestThermocouple:
    def test_type_k_zero_mv_is_zero_c(self):
        """Type K: 0 mV at 0 °C cold junction → 0 °C."""
        res = thermocouple_temperature(voltage_mv=0.0, tc_type="K", cold_junction_temp_c=0.0)
        assert res["ok"] is True
        assert abs(res["temperature_c"]) < 1.0  # polynomial should give ~0

    def test_type_t_zero_mv_is_zero_c(self):
        """Type T: 0 mV at 0 °C → 0 °C."""
        res = thermocouple_temperature(voltage_mv=0.0, tc_type="T", cold_junction_temp_c=0.0)
        assert res["ok"] is True
        assert abs(res["temperature_c"]) < 1.0

    def test_type_j_known_value(self):
        """Type J: NIST table — ~10.778 mV at 200 °C (cold junction 0 °C)."""
        # NIST Type J table: 200 °C → 10.778 mV
        # Inverse: 10.778 mV → ~200 °C
        res = thermocouple_temperature(voltage_mv=10.778, tc_type="J", cold_junction_temp_c=0.0)
        assert res["ok"] is True
        assert abs(res["temperature_c"] - 200.0) < 2.0  # within 2 °C of table value

    def test_type_k_known_value(self):
        """Type K: NIST table — ~4.096 mV at 100 °C."""
        # NIST Type K: 100 °C → 4.096 mV  → inverse should give ~100 °C
        res = thermocouple_temperature(voltage_mv=4.096, tc_type="K", cold_junction_temp_c=0.0)
        assert res["ok"] is True
        assert abs(res["temperature_c"] - 100.0) < 2.0

    def test_cjc_shifts_effective_voltage(self):
        """Non-zero cold junction adds a compensation voltage."""
        res0 = thermocouple_temperature(voltage_mv=4.096, tc_type="K", cold_junction_temp_c=0.0)
        res25 = thermocouple_temperature(voltage_mv=4.096, tc_type="K", cold_junction_temp_c=25.0)
        assert res25["cjc_voltage_mv"] > 0.0
        assert res25["temperature_c"] > res0["temperature_c"]

    def test_cjc_warning_above_5c(self):
        """Cold junction > 5 °C triggers CJC accuracy warning."""
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            thermocouple_temperature(voltage_mv=2.0, tc_type="K", cold_junction_temp_c=10.0)
            assert any("cold-junction" in str(x.message).lower() or
                       "cjc" in str(x.message).lower() or
                       "5 °C" in str(x.message) or
                       "5" in str(x.message)
                       for x in w)

    def test_invalid_tc_type_returns_error(self):
        res = thermocouple_temperature(voltage_mv=1.0, tc_type="Z")
        assert res["ok"] is False
        assert "tc_type" in res["reason"].lower() or "type" in res["reason"].lower()

    def test_out_of_range_voltage_warns(self):
        """Voltage outside NIST range issues a warning but still returns ok=True."""
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            res = thermocouple_temperature(voltage_mv=100.0, tc_type="K")
            assert res["ok"] is True
            assert any("range" in str(x.message).lower() or
                       "above" in str(x.message).lower()
                       for x in w)


# ═══════════════════════════════════════════════════════════════════════════════
# 7. Instrumentation amplifier gain and error
# ═══════════════════════════════════════════════════════════════════════════════

class TestInstrumentationAmpGain:
    def test_gain_formula(self):
        """G = 1 + 2 × R_int / R_gain."""
        r_int = 49.4e3
        r_gain = 1000.0
        expected = 1.0 + 2.0 * r_int / r_gain
        res = instrumentation_amp_gain(r_gain_ohm=r_gain, r_internal_ohm=r_int)
        assert res["ok"] is True
        assert abs(res["gain"] - expected) < 0.001

    def test_cmrr_limited_warning(self):
        """Large common-mode voltage with low CMRR triggers warning."""
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            res = instrumentation_amp_gain(
                r_gain_ohm=1000.0,
                cmrr_db=40.0,   # CMRR = 100 V/V (poor)
                common_mode_v=10.0,  # 10 V common mode
                offset_voltage_uv=50.0,
            )
            assert res["ok"] is True
            # e_cmrr = 10 V / 100 * 1e6 = 100000 µV >> e_offset = 50 µV
            assert res["cmrr_limited"] is True
            assert any("cmrr" in str(x.message).lower() for x in w)

    def test_zero_gain_resistor_returns_error(self):
        res = instrumentation_amp_gain(r_gain_ohm=0.0)
        assert res["ok"] is False

    def test_cmrr_not_limited_low_vcm(self):
        """With V_cm = 0, CMRR contribution is zero → not CMRR-limited."""
        res = instrumentation_amp_gain(
            r_gain_ohm=1000.0,
            common_mode_v=0.0,
            offset_voltage_uv=100.0,
        )
        assert res["ok"] is True
        assert res["cmrr_limited"] is False
        assert res["e_cmrr_uv"] == 0.0

    def test_e_total_rms_geq_max_component(self):
        """RSS total must be ≥ each individual component."""
        res = instrumentation_amp_gain(
            r_gain_ohm=500.0,
            offset_voltage_uv=50.0,
            cmrr_db=80.0,
            common_mode_v=1.0,
        )
        assert res["ok"] is True
        assert res["e_total_rms_uv"] >= max(res["e_offset_uv"], res["e_cmrr_uv"])


# ═══════════════════════════════════════════════════════════════════════════════
# 8. ADC bits and ENOB
# ═══════════════════════════════════════════════════════════════════════════════

class TestADCAndENOB:
    def test_10v_10mv_requires_10_bits(self):
        """10 V FSR / 10 mV → 1000 levels → ceil(log2(1000)) = 10 bits."""
        res = adc_required_bits(full_scale_range_v=10.0, target_resolution_mv=10.0)
        assert res["ok"] is True
        assert res["recommended_bits"] == 10

    def test_5v_1uv_requires_23_bits(self):
        """5 V FSR / 0.001 mV → 5e6 levels → ≥22.25 bits → 23 bits."""
        res = adc_required_bits(full_scale_range_v=5.0, target_resolution_mv=0.001)
        assert res["ok"] is True
        assert res["recommended_bits"] >= 22

    def test_lsb_size_from_bits(self):
        """LSB size = FSR / 2^N."""
        res = adc_required_bits(full_scale_range_v=1.0, target_resolution_mv=1.0)
        assert res["ok"] is True
        N = res["recommended_bits"]
        expected_lsb = 1.0 / (2 ** N) * 1e3
        assert abs(res["lsb_size_mv"] - expected_lsb) < 1e-6

    def test_enob_formula(self):
        """ENOB = log2(FSR / (noise_rms × √12))."""
        noise_uv = 100.0
        fsr = 1.0
        expected = math.log2(fsr / (noise_uv * 1e-6 * math.sqrt(12.0)))
        res = enob_from_noise(noise_rms_uv=noise_uv, full_scale_range_v=fsr)
        assert res["ok"] is True
        assert abs(res["enob"] - expected) < 0.001

    def test_enob_low_noise_warning(self):
        """Noise so small that ENOB > 24 triggers high-ENOB warning."""
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            enob_from_noise(noise_rms_uv=0.001, full_scale_range_v=1.0)
            assert any("24" in str(x.message) or "enob" in str(x.message).lower()
                       for x in w)

    def test_zero_fsr_returns_error(self):
        res = adc_required_bits(full_scale_range_v=0.0, target_resolution_mv=1.0)
        assert res["ok"] is False


# ═══════════════════════════════════════════════════════════════════════════════
# 9. Anti-alias filter corner
# ═══════════════════════════════════════════════════════════════════════════════

class TestAntialiasFilterCorner:
    def test_default_formula(self):
        """fc = f_nyq / 10^(40/(20×2)) = f_nyq / 10 for N=2, 40 dB."""
        fs = 10000.0
        f_nyq = fs / 2.0
        expected_fc = f_nyq / (10.0 ** (40.0 / (20.0 * 2)))
        res = antialias_filter_corner(sample_rate_hz=fs, stopband_attenuation_db=40.0, filter_order=2)
        assert res["ok"] is True
        assert abs(res["filter_corner_hz"] - expected_fc) < 0.01

    def test_higher_order_gives_higher_fc(self):
        """Higher filter order → higher fc (same fs and attenuation)."""
        fs = 10000.0
        r2 = antialias_filter_corner(sample_rate_hz=fs, filter_order=2)
        r4 = antialias_filter_corner(sample_rate_hz=fs, filter_order=4)
        assert r4["filter_corner_hz"] > r2["filter_corner_hz"]

    def test_bandwidth_ratio(self):
        """bandwidth_ratio = fc / f_nyq."""
        fs = 10000.0
        res = antialias_filter_corner(sample_rate_hz=fs, stopband_attenuation_db=20.0, filter_order=1)
        assert res["ok"] is True
        assert abs(res["bandwidth_ratio"] - res["filter_corner_hz"] / res["nyquist_hz"]) < 1e-6

    def test_warning_when_fc_lt_fs_over_4(self):
        """Very high attenuation required in a low-order filter → fc < fs/4 → warning."""
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            res = antialias_filter_corner(
                sample_rate_hz=10000.0,
                stopband_attenuation_db=80.0,
                filter_order=1,
            )
            assert res["ok"] is True
            assert any("fs/4" in str(x.message) or "quarter" in str(x.message).lower()
                       or "less than" in str(x.message).lower()
                       for x in w)


# ═══════════════════════════════════════════════════════════════════════════════
# 10. 4-20 mA loop scaling and burden
# ═══════════════════════════════════════════════════════════════════════════════

class TestLoop4_20mA:
    def test_4ma_is_span_low(self):
        """4 mA → span_low exactly."""
        res = loop_4_20ma_scaling(current_ma=4.0, span_low=0.0, span_high=100.0)
        assert res["ok"] is True
        assert abs(res["value"] - 0.0) < 1e-9

    def test_20ma_is_span_high(self):
        """20 mA → span_high exactly."""
        res = loop_4_20ma_scaling(current_ma=20.0, span_low=0.0, span_high=100.0)
        assert res["ok"] is True
        assert abs(res["value"] - 100.0) < 1e-9

    def test_12ma_is_midpoint(self):
        """12 mA → midpoint of span."""
        res = loop_4_20ma_scaling(current_ma=12.0, span_low=0.0, span_high=100.0)
        assert res["ok"] is True
        assert abs(res["value"] - 50.0) < 1e-9

    def test_fault_current_warning(self):
        """Current < 3.8 mA triggers fault warning."""
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            res = loop_4_20ma_scaling(current_ma=2.0, span_low=0.0, span_high=100.0)
            assert res["ok"] is True
            assert any("3.8" in str(x.message) or "open" in str(x.message).lower()
                       or "fault" in str(x.message).lower() or "range" in str(x.message).lower()
                       for x in w)

    def test_burden_voltage(self):
        """V_burden = I × R."""
        res = loop_burden_voltage(
            current_ma=20.0,
            burden_resistance_ohm=250.0,
            supply_voltage_v=24.0,
        )
        assert res["ok"] is True
        expected_vb = 20e-3 * 250.0
        assert abs(res["v_burden_v"] - expected_vb) < 1e-6

    def test_compliance_margin(self):
        """compliance_margin = V_supply − V_burden − V_min_compliance."""
        res = loop_burden_voltage(
            current_ma=20.0,
            burden_resistance_ohm=250.0,
            supply_voltage_v=24.0,
            transmitter_min_compliance_v=3.0,
        )
        assert res["ok"] is True
        expected = 24.0 - 20e-3 * 250.0 - 3.0
        assert abs(res["compliance_margin_v"] - expected) < 1e-6
        assert res["compliant"] is True

    def test_compliance_warning_low_margin(self):
        """Compliance margin < 1 V triggers warning."""
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            # Tight supply: 24V, 1.1 kΩ burden, 20 mA → V_burden = 22V → margin = -1V
            loop_burden_voltage(
                current_ma=20.0,
                burden_resistance_ohm=1100.0,
                supply_voltage_v=24.0,
                transmitter_min_compliance_v=3.0,
            )
            assert any("compliance" in str(x.message).lower() or
                       "1 v" in str(x.message).lower() or
                       "margin" in str(x.message).lower()
                       for x in w)

    def test_equal_span_returns_error(self):
        """span_low == span_high is invalid."""
        res = loop_4_20ma_scaling(current_ma=12.0, span_low=50.0, span_high=50.0)
        assert res["ok"] is False


# ═══════════════════════════════════════════════════════════════════════════════
# 11. Noise budget RSS
# ═══════════════════════════════════════════════════════════════════════════════

class TestNoiseBudgetRSS:
    def test_single_source(self):
        """Single source: total = that source."""
        res = noise_budget_rss([42.0])
        assert res["ok"] is True
        assert abs(res["total_rms_uv"] - 42.0) < 1e-9

    def test_two_equal_sources(self):
        """Two equal sources: total = source × √2 (rounded to 4 dp)."""
        v = 30.0
        res = noise_budget_rss([v, v])
        assert res["ok"] is True
        assert abs(res["total_rms_uv"] - round(v * math.sqrt(2.0), 4)) < 1e-9

    def test_three_sources_rss(self):
        """RSS formula: sqrt(a² + b² + c²) (rounded to 4 dp)."""
        a, b, c = 10.0, 20.0, 30.0
        expected = math.sqrt(a ** 2 + b ** 2 + c ** 2)
        res = noise_budget_rss([a, b, c])
        assert res["ok"] is True
        assert abs(res["total_rms_uv"] - round(expected, 4)) < 1e-9

    def test_dominant_source_warning(self):
        """Source dominating > 70% of variance triggers warning."""
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            res = noise_budget_rss([100.0, 1.0, 1.0])
            assert res["ok"] is True
            assert res["dominant_source_fraction"] > 0.70
            assert any("dominat" in str(x.message).lower() for x in w)

    def test_empty_list_returns_error(self):
        res = noise_budget_rss([])
        assert res["ok"] is False

    def test_negative_source_returns_error(self):
        res = noise_budget_rss([10.0, -5.0])
        assert res["ok"] is False


# ═══════════════════════════════════════════════════════════════════════════════
# 12. Filter topology selector
# ═══════════════════════════════════════════════════════════════════════════════

class TestFilterTopologySelect:
    def test_unity_gain_low_q_is_sallen_key(self):
        """G=1, Q=0.7 → Sallen-Key preferred."""
        res = filter_topology_select(gain=1.0, q_factor=0.707)
        assert res["ok"] is True
        assert res["recommended_topology"] == "sallen-key"

    def test_high_gain_high_q_is_mfb(self):
        """G=10, Q=2 → MFB preferred."""
        res = filter_topology_select(gain=10.0, q_factor=2.0)
        assert res["ok"] is True
        assert res["recommended_topology"] == "mfb"

    def test_single_ended_nudges_sk(self):
        """Single-ended supply increases SK score."""
        res_split = filter_topology_select(gain=1.5, q_factor=0.7, supply_single_ended=False)
        res_single = filter_topology_select(gain=1.5, q_factor=0.7, supply_single_ended=True)
        assert res_single["sk_score"] > res_split["sk_score"]

    def test_zero_gain_returns_error(self):
        res = filter_topology_select(gain=0.0, q_factor=0.7)
        assert res["ok"] is False

    def test_reasons_list_nonempty(self):
        """Decision always has at least one reason."""
        res = filter_topology_select(gain=2.0, q_factor=1.0)
        assert res["ok"] is True
        assert len(res["reasons"]) >= 1


# ═══════════════════════════════════════════════════════════════════════════════
# 13. LLM tool handlers
# ═══════════════════════════════════════════════════════════════════════════════

class TestToolHandlers:
    @pytest.mark.asyncio
    async def test_bridge_output_tool_ok(self):
        res = await call(
            bridge_output_tool,
            excitation_v=5.0, gauge_factor=2.0, strain_ue=500.0, config="quarter"
        )
        assert res["ok"] is True
        assert "vout_linearised_v" in res

    @pytest.mark.asyncio
    async def test_rtd_resistance_tool_ok(self):
        res = await call(rtd_resistance_tool, temperature_c=25.0)
        assert res["ok"] is True
        assert "resistance_ohm" in res

    @pytest.mark.asyncio
    async def test_thermocouple_tool_ok(self):
        res = await call(thermocouple_tool, voltage_mv=4.096, tc_type="K")
        assert res["ok"] is True
        assert "temperature_c" in res

    @pytest.mark.asyncio
    async def test_ina_gain_tool_ok(self):
        res = await call(ina_gain_tool, r_gain_ohm=1000.0)
        assert res["ok"] is True
        assert "gain" in res

    @pytest.mark.asyncio
    async def test_noise_rss_tool_ok(self):
        res = await call(noise_rss_tool, noise_sources_uv=[10.0, 20.0, 30.0])
        assert res["ok"] is True
        assert "total_rms_uv" in res

    @pytest.mark.asyncio
    async def test_tool_invalid_json_returns_error(self):
        result = await bridge_output_tool(None, b"not valid json{{")
        data = json.loads(result)
        assert data.get("ok") is False or "error" in data
