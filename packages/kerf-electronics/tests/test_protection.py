"""
Hermetic tests for the circuit-protection design module.

Covers ≥30 tests:

  fuse_select
    - Returns ok=True with required keys
    - Correctly passes a well-sized fuse
    - UNDERSIZED flag when load > derated rating
    - Derated current decreases at elevated temperature
    - VOLTAGE_RATING_LOW flag when fuse voltage < supply
    - I2T_EXCEEDED flag when fuse I²t > downstream withstand
    - Bad arguments return ok=False

  inrush_ntc_size
    - Inrush peak = V / R_cold
    - Energy = 0.5 × C × V²
    - NTC_OVERLOADED when P_ss > rated power
    - EXCESSIVE_DROP when V_ntc > 5% of supply
    - Zero capacitance → ok=False

  tvs_mov_clamp
    - All-ok for a well-chosen TVS
    - STANDOFF_TOO_LOW when standoff < working voltage
    - CLAMP_TOO_HIGH when clamp > 1.5× standoff
    - POWER_EXCEEDED when pulse power > rated
    - IPP_UNDERSIZED when TVS I_pp < surge current
    - IEC level compliance pass/fail
    - Negative working voltage → ok=False

  reverse_polarity
    - P-FET preferred when RDS(on) loss < diode drop loss
    - Diode preferred when diode loss < FET loss
    - DIODE_VF_EXCEEDS_SUPPLY warning
    - Exact numeric check for diode power loss

  efuse_trip
    - Normal operation: conduction_ok=True, soa_ok=True
    - WILL_TRIP when load ≥ trip threshold
    - CONDUCTION_OVERLOAD when P_cond > max power
    - Fault energy increases with trip delay

  ptc_resettable
    - load_within_hold=True for safe current
    - PTC_WILL_TRIP for load >= derated trip
    - PTC_MARGINAL for load between hold and trip
    - trip_current ≤ hold_current → ok=False
    - Derating at elevated temperature reduces hold current

  breaker_coordination
    - Fully coordinated case returns coordinated=True
    - UNCOORDINATED when ratio < minimum
    - Exact selectivity ratio computed
    - Time-ok=False when downstream is slower

  onderdonk_trace_fuse
    - Wider trace → higher fusing current
    - Thicker copper → higher fusing current
    - Longer fusing time → lower fusing current
    - Exact numerical value for 1 oz / 1 mm / 1 s
    - Zero width → ok=False
    - ambient_temp ≥ melting_temp → ok=False

  wire_ampacity
    - AWG 14 @ 30°C: base ampacity = 15 A
    - load ≤ derated ampacity → ampacity_ok=True
    - WIRE_UNDERSIZED when load > derated
    - FUSE_OVERSIZED_FOR_WIRE when fuse > derated ampacity
    - Voltage drop scales linearly with wire length
    - Temperature correction factor < 1 above 30°C
    - Unknown AWG → ok=False

  LLM tool handlers
    - protection_fuse_select tool returns ok=True
    - protection_inrush_ntc_size tool returns ok=True
    - protection_tvs_mov_clamp tool returns ok=True
    - protection_reverse_polarity tool returns ok=True
    - protection_efuse_trip tool returns ok=True
    - protection_ptc_resettable tool returns ok=True
    - protection_breaker_coordination tool returns ok=True
    - protection_onderdonk_trace_fuse tool returns ok=True
    - protection_wire_ampacity tool returns ok=True
    - Tool with invalid JSON → returns error payload

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

# ── Stub kerf_chat if not installed ──────────────────────────────────────────
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

from kerf_electronics.protection.protect import (
    breaker_coordination,
    efuse_trip,
    fuse_select,
    inrush_ntc_size,
    onderdonk_trace_fuse,
    ptc_resettable,
    reverse_polarity,
    tvs_mov_clamp,
    wire_ampacity,
)

# ── Load tool module via importlib so stub is active ─────────────────────────
_tool_spec = importlib.util.spec_from_file_location(
    "kerf_electronics.protection.tools",
    os.path.join(_SRC, "kerf_electronics", "protection", "tools.py"),
)
_tool_mod = importlib.util.module_from_spec(_tool_spec)
_tool_spec.loader.exec_module(_tool_mod)

_fuse_tool = _tool_mod.protection_fuse_select
_inrush_tool = _tool_mod.protection_inrush_ntc_size
_tvs_tool = _tool_mod.protection_tvs_mov_clamp
_revpol_tool = _tool_mod.protection_reverse_polarity
_efuse_tool = _tool_mod.protection_efuse_trip
_ptc_tool = _tool_mod.protection_ptc_resettable
_coord_tool = _tool_mod.protection_breaker_coordination
_onderdonk_tool = _tool_mod.protection_onderdonk_trace_fuse
_wire_tool = _tool_mod.protection_wire_ampacity


async def call(fn, **kwargs):
    result = await fn(None, json.dumps(kwargs).encode())
    return json.loads(result)


# ═══════════════════════════════════════════════════════════════════════════════
# 1. fuse_select
# ═══════════════════════════════════════════════════════════════════════════════

class TestFuseSelect:
    def _defaults(self, **overrides):
        base = dict(
            load_current_a=1.0,
            supply_voltage_v=12.0,
            ambient_temp_c=25.0,
            fuse_rating_a=2.0,
            fuse_voltage_v=32.0,
            fuse_interrupt_a=2000.0,  # > 12/0.01=1200 A conservative estimate
            fuse_i2t_as2=1.0,
            downstream_i2t_withstand_as2=10.0,
        )
        base.update(overrides)
        return base

    def test_ok_returns_required_keys(self):
        res = fuse_select(**self._defaults())
        assert res["ok"] is True
        for k in ("derated_current_a", "current_ok", "voltage_ok",
                  "interrupt_ok", "i2t_ok", "all_ok", "warnings"):
            assert k in res, f"missing key {k!r}"

    def test_well_sized_fuse_all_ok(self):
        res = fuse_select(**self._defaults())
        assert res["all_ok"] is True
        assert res["warnings"] == []

    def test_undersized_flag(self):
        """Load current > derated rating → UNDERSIZED warning."""
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            res = fuse_select(**self._defaults(load_current_a=1.9, fuse_rating_a=2.0))
            # derated at 25°C, 0.75 factor → derated = 1.5 A; load 1.9 > 1.5
            assert res["current_ok"] is False
            assert "UNDERSIZED" in res["warnings"]
            assert any("undersized" in str(x.message).lower() for x in w)

    def test_derated_current_lower_at_high_temp(self):
        res_25 = fuse_select(**self._defaults())
        res_70 = fuse_select(**self._defaults(ambient_temp_c=70.0))
        assert res_70["derated_current_a"] < res_25["derated_current_a"]

    def test_voltage_rating_low_flag(self):
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            res = fuse_select(**self._defaults(fuse_voltage_v=5.0, supply_voltage_v=12.0))
            assert res["voltage_ok"] is False
            assert "VOLTAGE_RATING_LOW" in res["warnings"]

    def test_i2t_exceeded_flag(self):
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            res = fuse_select(**self._defaults(
                fuse_i2t_as2=100.0, downstream_i2t_withstand_as2=50.0
            ))
            assert res["i2t_ok"] is False
            assert "I2T_EXCEEDED" in res["warnings"]

    def test_bad_args_return_error(self):
        res = fuse_select(
            load_current_a=-1.0, supply_voltage_v=12.0, ambient_temp_c=25.0,
            fuse_rating_a=2.0, fuse_voltage_v=32.0, fuse_interrupt_a=100.0,
            fuse_i2t_as2=1.0, downstream_i2t_withstand_as2=10.0,
        )
        assert res["ok"] is False
        assert "load_current_a" in res["reason"]


# ═══════════════════════════════════════════════════════════════════════════════
# 2. inrush_ntc_size
# ═══════════════════════════════════════════════════════════════════════════════

class TestInrushNtcSize:
    def test_inrush_peak_formula(self):
        """I_peak = V / R_cold."""
        V, R_cold = 12.0, 4.0
        res = inrush_ntc_size(
            supply_voltage_v=V, bulk_capacitance_uf=1000.0,
            ntc_resistance_cold_ohm=R_cold, ntc_resistance_hot_ohm=0.1,
            ntc_max_power_w=1.0, steady_state_current_a=0.5,
        )
        assert res["ok"] is True
        assert abs(res["inrush_peak_a"] - V / R_cold) < 1e-6

    def test_inrush_energy_formula(self):
        """E = 0.5 × C × V²."""
        V = 12.0
        C_uf = 1000.0
        C = C_uf * 1e-6
        expected = 0.5 * C * V ** 2
        res = inrush_ntc_size(
            supply_voltage_v=V, bulk_capacitance_uf=C_uf,
            ntc_resistance_cold_ohm=5.0, ntc_resistance_hot_ohm=0.1,
            ntc_max_power_w=1.0, steady_state_current_a=0.5,
        )
        assert abs(res["inrush_energy_j"] - expected) < 1e-9

    def test_ntc_overloaded_warning(self):
        """P_ss > ntc_max_power → NTC_OVERLOADED."""
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            res = inrush_ntc_size(
                supply_voltage_v=12.0, bulk_capacitance_uf=470.0,
                ntc_resistance_cold_ohm=5.0, ntc_resistance_hot_ohm=2.0,
                ntc_max_power_w=0.1, steady_state_current_a=1.0,  # P_ss=2W > 0.1W
            )
            assert "NTC_OVERLOADED" in res["warnings"]

    def test_excessive_drop_warning(self):
        """V_ntc > 5% of supply → EXCESSIVE_DROP."""
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            res = inrush_ntc_size(
                supply_voltage_v=5.0, bulk_capacitance_uf=100.0,
                ntc_resistance_cold_ohm=1.0, ntc_resistance_hot_ohm=1.0,
                ntc_max_power_w=10.0, steady_state_current_a=1.0,  # V_drop=1V > 5%*5V
            )
            assert "EXCESSIVE_DROP" in res["warnings"]

    def test_zero_capacitance_returns_error(self):
        res = inrush_ntc_size(
            supply_voltage_v=12.0, bulk_capacitance_uf=0.0,
            ntc_resistance_cold_ohm=5.0, ntc_resistance_hot_ohm=0.1,
            ntc_max_power_w=1.0, steady_state_current_a=0.5,
        )
        assert res["ok"] is False


# ═══════════════════════════════════════════════════════════════════════════════
# 3. tvs_mov_clamp
# ═══════════════════════════════════════════════════════════════════════════════

class TestTvsMoveClamp:
    def _good(self, **overrides):
        base = dict(
            working_voltage_v=12.0,
            tvs_standoff_v=15.0,
            tvs_clamping_v_at_ipp=22.0,   # ≤ 1.5×15=22.5 V — within clamping threshold
            tvs_ipp_a=20.0,
            tvs_peak_power_w=600.0,
            surge_current_a=10.0,
            surge_energy_j=1e-4,
        )
        base.update(overrides)
        return base

    def test_all_ok_for_good_tvs(self):
        res = tvs_mov_clamp(**self._good())
        assert res["ok"] is True
        assert res["all_ok"] is True

    def test_standoff_too_low_flag(self):
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            res = tvs_mov_clamp(**self._good(tvs_standoff_v=10.0, working_voltage_v=12.0))
            assert res["standoff_ok"] is False
            assert "STANDOFF_TOO_LOW" in res["warnings"]

    def test_clamp_too_high_flag(self):
        # clamp > 1.5 × standoff: 30 V > 1.5×15 = 22.5 V
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            res = tvs_mov_clamp(**self._good(tvs_clamping_v_at_ipp=30.0))
            assert res["clamping_v_ok"] is False
            assert "CLAMP_TOO_HIGH" in res["warnings"]

    def test_power_exceeded_flag(self):
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            res = tvs_mov_clamp(**self._good(tvs_peak_power_w=10.0))
            # pulse_power = 24 * 10 = 240 W > 10 W
            assert res["power_ok"] is False
            assert "POWER_EXCEEDED" in res["warnings"]

    def test_ipp_undersized_flag(self):
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            res = tvs_mov_clamp(**self._good(tvs_ipp_a=5.0, surge_current_a=10.0))
            assert res["ipp_ok"] is False
            assert "IPP_UNDERSIZED" in res["warnings"]

    def test_iec_level_compliance_pass(self):
        # IEC Level 1 = 500 A; TVS rated 600 A; use a low surge_current to keep power ok
        res = tvs_mov_clamp(**self._good(
            tvs_ipp_a=600.0,
            tvs_peak_power_w=20000.0,  # large enough to absorb 600 A × 22 V
            surge_current_a=10.0,
            iec_level="1",
        ))
        assert res["iec_compliance"] is True

    def test_iec_level_compliance_fail(self):
        # IEC Level 4 = 4000 A; TVS rated 500 A
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            res = tvs_mov_clamp(**self._good(tvs_ipp_a=500.0, surge_current_a=100.0, iec_level="4"))
            assert res["iec_compliance"] is False
            assert "IEC_LEVEL_NOT_MET" in res["warnings"]

    def test_negative_working_voltage_returns_error(self):
        res = tvs_mov_clamp(**self._good(working_voltage_v=-1.0))
        assert res["ok"] is False


# ═══════════════════════════════════════════════════════════════════════════════
# 4. reverse_polarity
# ═══════════════════════════════════════════════════════════════════════════════

class TestReversePolarity:
    def test_pfet_preferred_low_rds(self):
        """At low RDS(on), P-FET loss < diode loss → preferred = 'pfet'."""
        res = reverse_polarity(
            supply_voltage_v=12.0,
            load_current_a=2.0,
            diode_vf_v=0.7,
            pfet_rds_on_ohm=0.01,  # loss = 4 * 0.01 = 0.04 W vs diode 1.4 W
        )
        assert res["ok"] is True
        assert res["preferred"] == "pfet"

    def test_diode_preferred_high_rds(self):
        """At high RDS(on), diode preferred."""
        res = reverse_polarity(
            supply_voltage_v=12.0,
            load_current_a=2.0,
            diode_vf_v=0.3,          # diode loss = 0.6 W
            pfet_rds_on_ohm=1.0,     # P-FET loss = 4 W
        )
        assert res["preferred"] == "diode"

    def test_diode_power_exact(self):
        """P_diode = V_f × I_load exactly."""
        res = reverse_polarity(
            supply_voltage_v=12.0,
            load_current_a=3.0,
            diode_vf_v=0.6,
            pfet_rds_on_ohm=0.05,
        )
        assert abs(res["diode_power_w"] - 0.6 * 3.0) < 1e-9

    def test_diode_vf_exceeds_supply_warning(self):
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            res = reverse_polarity(
                supply_voltage_v=1.0,
                load_current_a=0.1,
                diode_vf_v=1.5,
                pfet_rds_on_ohm=0.1,
            )
            assert "DIODE_VF_EXCEEDS_SUPPLY" in res["warnings"]


# ═══════════════════════════════════════════════════════════════════════════════
# 5. efuse_trip
# ═══════════════════════════════════════════════════════════════════════════════

class TestEfuseTrip:
    def test_normal_operation_ok(self):
        res = efuse_trip(
            current_limit_a=5.0,
            load_current_a=2.0,
            supply_voltage_v=12.0,
            efuse_rds_on_ohm=0.05,
            efuse_max_power_w=1.0,
        )
        assert res["ok"] is True
        assert res["conduction_ok"] is True
        assert res["soa_ok"] is True
        assert "WILL_TRIP" not in res["warnings"]

    def test_will_trip_warning(self):
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            res = efuse_trip(
                current_limit_a=2.0,
                load_current_a=2.5,  # load > limit
                supply_voltage_v=5.0,
                efuse_rds_on_ohm=0.01,
                efuse_max_power_w=1.0,
            )
            assert "WILL_TRIP" in res["warnings"]

    def test_conduction_overload_warning(self):
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            res = efuse_trip(
                current_limit_a=5.0,
                load_current_a=3.0,
                supply_voltage_v=12.0,
                efuse_rds_on_ohm=1.0,  # P_cond = 9 W
                efuse_max_power_w=0.5,
            )
            assert "CONDUCTION_OVERLOAD" in res["warnings"]

    def test_fault_energy_increases_with_trip_delay(self):
        r1 = efuse_trip(
            current_limit_a=3.0, load_current_a=1.0, supply_voltage_v=5.0,
            efuse_rds_on_ohm=0.01, efuse_max_power_w=1.0, trip_delay_us=1.0,
        )
        r10 = efuse_trip(
            current_limit_a=3.0, load_current_a=1.0, supply_voltage_v=5.0,
            efuse_rds_on_ohm=0.01, efuse_max_power_w=1.0, trip_delay_us=10.0,
        )
        assert r10["fault_energy_j"] > r1["fault_energy_j"]


# ═══════════════════════════════════════════════════════════════════════════════
# 6. ptc_resettable
# ═══════════════════════════════════════════════════════════════════════════════

class TestPtcResettable:
    def test_load_within_hold(self):
        res = ptc_resettable(
            ptc_hold_current_a=1.0,
            ptc_trip_current_a=2.0,
            load_current_a=0.5,
            ptc_resistance_ohm=0.5,
            supply_voltage_v=5.0,
        )
        assert res["ok"] is True
        assert res["load_within_hold"] is True
        assert res["will_trip"] is False

    def test_ptc_will_trip(self):
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            res = ptc_resettable(
                ptc_hold_current_a=1.0,
                ptc_trip_current_a=2.0,
                load_current_a=2.5,  # > trip
                ptc_resistance_ohm=0.5,
                supply_voltage_v=5.0,
            )
            assert res["will_trip"] is True
            assert "PTC_WILL_TRIP" in res["warnings"]

    def test_ptc_marginal(self):
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            res = ptc_resettable(
                ptc_hold_current_a=1.0,
                ptc_trip_current_a=2.0,
                load_current_a=1.5,  # between hold and trip
                ptc_resistance_ohm=0.5,
                supply_voltage_v=5.0,
            )
            assert "PTC_MARGINAL" in res["warnings"]

    def test_trip_leq_hold_returns_error(self):
        res = ptc_resettable(
            ptc_hold_current_a=2.0,
            ptc_trip_current_a=1.0,  # trip < hold — invalid
            load_current_a=0.5,
            ptc_resistance_ohm=0.5,
            supply_voltage_v=5.0,
        )
        assert res["ok"] is False

    def test_derating_at_elevated_temp(self):
        """Hold current at 75°C should be lower than at 25°C."""
        res_25 = ptc_resettable(
            ptc_hold_current_a=1.0, ptc_trip_current_a=2.0, load_current_a=0.5,
            ptc_resistance_ohm=0.5, supply_voltage_v=5.0, ambient_temp_c=25.0,
        )
        res_75 = ptc_resettable(
            ptc_hold_current_a=1.0, ptc_trip_current_a=2.0, load_current_a=0.5,
            ptc_resistance_ohm=0.5, supply_voltage_v=5.0, ambient_temp_c=75.0,
        )
        assert res_75["hold_current_derated_a"] < res_25["hold_current_derated_a"]


# ═══════════════════════════════════════════════════════════════════════════════
# 7. breaker_coordination
# ═══════════════════════════════════════════════════════════════════════════════

class TestBreakerCoordination:
    def test_coordinated_case(self):
        res = breaker_coordination(
            upstream_trip_current_a=32.0,
            downstream_trip_current_a=16.0,    # ratio=2.0 ≥ 1.6
            upstream_trip_time_s=0.5,
            downstream_trip_time_s=0.1,         # downstream clears first
        )
        assert res["ok"] is True
        assert res["coordinated"] is True
        assert res["ratio_ok"] is True
        assert res["time_ok"] is True

    def test_uncoordinated_low_ratio(self):
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            res = breaker_coordination(
                upstream_trip_current_a=20.0,
                downstream_trip_current_a=16.0,  # ratio=1.25 < 1.6
                upstream_trip_time_s=0.5,
                downstream_trip_time_s=0.1,
            )
            assert res["coordinated"] is False
            assert "UNCOORDINATED" in res["warnings"]

    def test_selectivity_ratio_exact(self):
        res = breaker_coordination(
            upstream_trip_current_a=32.0,
            downstream_trip_current_a=20.0,
            upstream_trip_time_s=1.0,
            downstream_trip_time_s=0.1,
        )
        assert abs(res["selectivity_ratio"] - 32.0 / 20.0) < 1e-4

    def test_time_ok_false_when_upstream_faster(self):
        # ratio ok but upstream clears before downstream
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            res = breaker_coordination(
                upstream_trip_current_a=32.0,
                downstream_trip_current_a=16.0,  # ratio=2.0 ok
                upstream_trip_time_s=0.05,        # upstream faster!
                downstream_trip_time_s=0.5,
            )
            assert res["time_ok"] is False


# ═══════════════════════════════════════════════════════════════════════════════
# 8. onderdonk_trace_fuse
# ═══════════════════════════════════════════════════════════════════════════════

class TestOnderdonkTraceFuse:
    def test_wider_trace_higher_fusing_current(self):
        r1 = onderdonk_trace_fuse(trace_width_mm=0.5, trace_thickness_um=35.0, fusing_time_s=1.0)
        r2 = onderdonk_trace_fuse(trace_width_mm=1.0, trace_thickness_um=35.0, fusing_time_s=1.0)
        assert r2["fusing_current_a"] > r1["fusing_current_a"]

    def test_thicker_copper_higher_fusing_current(self):
        r1 = onderdonk_trace_fuse(trace_width_mm=1.0, trace_thickness_um=35.0, fusing_time_s=1.0)
        r2 = onderdonk_trace_fuse(trace_width_mm=1.0, trace_thickness_um=70.0, fusing_time_s=1.0)
        assert r2["fusing_current_a"] > r1["fusing_current_a"]

    def test_longer_fusing_time_lower_current(self):
        """Longer time → lower fusing current (1/sqrt(t) dependence)."""
        r1 = onderdonk_trace_fuse(trace_width_mm=1.0, trace_thickness_um=35.0, fusing_time_s=0.1)
        r2 = onderdonk_trace_fuse(trace_width_mm=1.0, trace_thickness_um=35.0, fusing_time_s=1.0)
        assert r2["fusing_current_a"] < r1["fusing_current_a"]

    def test_fusing_time_sqrt_relationship(self):
        """Fusing current ∝ 1/sqrt(t) — 10× longer → 1/sqrt(10) lower."""
        r1 = onderdonk_trace_fuse(trace_width_mm=1.0, trace_thickness_um=35.0, fusing_time_s=1.0)
        r10 = onderdonk_trace_fuse(trace_width_mm=1.0, trace_thickness_um=35.0, fusing_time_s=10.0)
        ratio = r1["fusing_current_a"] / r10["fusing_current_a"]
        assert abs(ratio - math.sqrt(10.0)) < 1e-4

    def test_exact_numerical_value(self):
        """
        1 mm trace, 35 μm copper (1 oz), 1 s, 25°C ambient.
        A [cm²] = 1 mm × 35e-3 mm × 1e-2 = 35e-5 cm² = 3.5e-4 cm²
        A [cmil] = 3.5e-4 / 5.0671e-6 ≈ 69.08 cmil
        ΔT = 1085 − 25 = 1060 °C
        I = 69.08 × sqrt(1060 / (33 × 1)) ≈ 69.08 × 5.667 ≈ 391.4 A
        """
        w_mm, t_um, t_s = 1.0, 35.0, 1.0
        area_mm2 = w_mm * (t_um * 1e-3)
        area_cm2 = area_mm2 * 1e-2
        area_cmil = area_cm2 / 5.0671e-6
        delta_T = 1085.0 - 25.0
        expected = area_cmil * math.sqrt(delta_T / (33.0 * t_s))
        res = onderdonk_trace_fuse(
            trace_width_mm=w_mm, trace_thickness_um=t_um, fusing_time_s=t_s
        )
        assert abs(res["fusing_current_a"] - expected) / expected < 1e-4

    def test_zero_width_returns_error(self):
        res = onderdonk_trace_fuse(trace_width_mm=0.0, trace_thickness_um=35.0, fusing_time_s=1.0)
        assert res["ok"] is False

    def test_ambient_geq_melting_returns_error(self):
        res = onderdonk_trace_fuse(
            trace_width_mm=1.0, trace_thickness_um=35.0, fusing_time_s=1.0,
            ambient_temp_c=1100.0, melting_temp_c=1085.0,
        )
        assert res["ok"] is False


# ═══════════════════════════════════════════════════════════════════════════════
# 9. wire_ampacity
# ═══════════════════════════════════════════════════════════════════════════════

class TestWireAmpacity:
    def test_awg14_base_ampacity(self):
        """AWG 14 base ampacity = 15 A per NEC 310.16."""
        res = wire_ampacity(awg=14, load_current_a=10.0, wire_length_m=1.0)
        assert res["ok"] is True
        assert res["base_ampacity_a"] == 15.0

    def test_load_within_ampacity_ok(self):
        res = wire_ampacity(awg=12, load_current_a=15.0, wire_length_m=2.0)
        assert res["ampacity_ok"] is True
        assert "WIRE_UNDERSIZED" not in res["warnings"]

    def test_wire_undersized_warning(self):
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            res = wire_ampacity(awg=22, load_current_a=10.0, wire_length_m=1.0)
            # AWG 22 base = 5 A; at 30°C CF=1; derated=5 A; 10 A > 5 A
            assert res["ampacity_ok"] is False
            assert "WIRE_UNDERSIZED" in res["warnings"]

    def test_fuse_oversized_for_wire(self):
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            res = wire_ampacity(awg=22, load_current_a=1.0, wire_length_m=1.0, fuse_rating_a=20.0)
            # AWG 22 derated ≈ 5 A; fuse 20 A > 5 A
            assert res["fuse_ok"] is False
            assert "FUSE_OVERSIZED_FOR_WIRE" in res["warnings"]

    def test_voltage_drop_scales_with_length(self):
        r1 = wire_ampacity(awg=14, load_current_a=10.0, wire_length_m=1.0)
        r5 = wire_ampacity(awg=14, load_current_a=10.0, wire_length_m=5.0)
        # V_drop ∝ length
        ratio = r5["voltage_drop_v"] / r1["voltage_drop_v"]
        assert abs(ratio - 5.0) < 1e-3

    def test_derated_ampacity_lower_at_high_temp(self):
        """Derated ampacity at 50°C ambient is lower than at 30°C (base)."""
        r_30 = wire_ampacity(awg=14, load_current_a=5.0, wire_length_m=1.0,
                             ambient_temp_c=30.0, insulation_temp_c=90.0)
        r_50 = wire_ampacity(awg=14, load_current_a=5.0, wire_length_m=1.0,
                             ambient_temp_c=50.0, insulation_temp_c=90.0)
        assert r_50["ok"] is True
        assert r_50["derated_ampacity_a"] < r_30["derated_ampacity_a"]

    def test_unknown_awg_returns_error(self):
        res = wire_ampacity(awg=99, load_current_a=1.0, wire_length_m=1.0)
        assert res["ok"] is False
        assert "AWG" in res["reason"] or "awg" in res["reason"].lower()


# ═══════════════════════════════════════════════════════════════════════════════
# 10. LLM tool handlers
# ═══════════════════════════════════════════════════════════════════════════════

class TestToolHandlers:
    @pytest.mark.asyncio
    async def test_fuse_select_tool_ok(self):
        res = await call(
            _fuse_tool,
            load_current_a=1.0, supply_voltage_v=12.0, ambient_temp_c=25.0,
            fuse_rating_a=2.0, fuse_voltage_v=32.0, fuse_interrupt_a=2000.0,
            fuse_i2t_as2=1.0, downstream_i2t_withstand_as2=10.0,
        )
        assert res["ok"] is True
        assert "derated_current_a" in res

    @pytest.mark.asyncio
    async def test_inrush_ntc_tool_ok(self):
        res = await call(
            _inrush_tool,
            supply_voltage_v=12.0, bulk_capacitance_uf=1000.0,
            ntc_resistance_cold_ohm=5.0, ntc_resistance_hot_ohm=0.1,
            ntc_max_power_w=1.0, steady_state_current_a=0.5,
        )
        assert res["ok"] is True
        assert "inrush_peak_a" in res

    @pytest.mark.asyncio
    async def test_tvs_mov_clamp_tool_ok(self):
        res = await call(
            _tvs_tool,
            working_voltage_v=12.0, tvs_standoff_v=15.0,
            tvs_clamping_v_at_ipp=22.0, tvs_ipp_a=20.0,
            tvs_peak_power_w=600.0, surge_current_a=10.0, surge_energy_j=1e-4,
        )
        assert res["ok"] is True
        assert "all_ok" in res

    @pytest.mark.asyncio
    async def test_reverse_polarity_tool_ok(self):
        res = await call(
            _revpol_tool,
            supply_voltage_v=12.0, load_current_a=2.0,
            diode_vf_v=0.7, pfet_rds_on_ohm=0.01,
        )
        assert res["ok"] is True
        assert "preferred" in res

    @pytest.mark.asyncio
    async def test_efuse_trip_tool_ok(self):
        res = await call(
            _efuse_tool,
            current_limit_a=5.0, load_current_a=2.0, supply_voltage_v=12.0,
            efuse_rds_on_ohm=0.05, efuse_max_power_w=1.0,
        )
        assert res["ok"] is True
        assert "soa_ok" in res

    @pytest.mark.asyncio
    async def test_ptc_resettable_tool_ok(self):
        res = await call(
            _ptc_tool,
            ptc_hold_current_a=1.0, ptc_trip_current_a=2.0,
            load_current_a=0.5, ptc_resistance_ohm=0.5, supply_voltage_v=5.0,
        )
        assert res["ok"] is True
        assert "load_within_hold" in res

    @pytest.mark.asyncio
    async def test_breaker_coordination_tool_ok(self):
        res = await call(
            _coord_tool,
            upstream_trip_current_a=32.0, downstream_trip_current_a=16.0,
            upstream_trip_time_s=0.5, downstream_trip_time_s=0.1,
        )
        assert res["ok"] is True
        assert "coordinated" in res

    @pytest.mark.asyncio
    async def test_onderdonk_tool_ok(self):
        res = await call(
            _onderdonk_tool,
            trace_width_mm=1.0, trace_thickness_um=35.0, fusing_time_s=1.0,
        )
        assert res["ok"] is True
        assert "fusing_current_a" in res

    @pytest.mark.asyncio
    async def test_wire_ampacity_tool_ok(self):
        res = await call(
            _wire_tool,
            awg=14, load_current_a=10.0, wire_length_m=2.0,
        )
        assert res["ok"] is True
        assert "derated_ampacity_a" in res

    @pytest.mark.asyncio
    async def test_tool_invalid_json_returns_error(self):
        result = await _fuse_tool(None, b"not valid json{{")
        data = json.loads(result)
        assert data.get("ok") is False or "error" in data
