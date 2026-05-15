"""
Hermetic tests for kerf_electronics battery pack sizing & runtime estimator.

Covers:
  - size_pack: basic series/parallel config math
  - size_pack: exact n_s / n_p ceiling arithmetic
  - size_pack: pack_energy_wh = pack_voltage_v * pack_capacity_ah
  - size_pack: pack_mass and volume scale linearly with cell count
  - size_pack: pack_r_int_ohm = n_s * R_cell / n_p
  - size_pack: missing required arg returns ok=False
  - size_pack: non-positive inputs return ok=False
  - estimate_runtime: single-step zero-load returns full duration
  - estimate_runtime: simple constant load depletes pack at expected time
  - estimate_runtime: Peukert effect — higher k yields shorter runtime
  - estimate_runtime: DoD limit reduces usable capacity proportionally
  - estimate_runtime: larger DoD → longer runtime (monotonicity)
  - estimate_runtime: higher power → shorter runtime (monotonicity)
  - estimate_runtime: exhausted flag set when pack depletes mid-profile
  - estimate_runtime: exhausted flag clear when profile fits in capacity
  - estimate_runtime: C-rate warning added when current exceeds limit
  - estimate_runtime: no C-rate warning when current within limit
  - estimate_runtime: multi-step profile energy sums correctly
  - estimate_runtime: invalid load_profile element returns ok=False
  - estimate_charge_time: total_time_h = cc_time + cv_tail exactly
  - estimate_charge_time: faster charge rate reduces CC time
  - estimate_charge_time: higher dod_at_start increases charge time
  - estimate_charge_time: cv_tail == 0.2 * cc_time exactly
  - estimate_charge_time: invalid args return ok=False
  - estimate_thermal_rise: formula Q = I^2 * R * t
  - estimate_thermal_rise: heavier pack → lower temperature rise
  - estimate_thermal_rise: zero current → zero heat
  - estimate_thermal_rise: warning added when delta_T > 20 C
  - estimate_thermal_rise: invalid arg returns ok=False
  - pack_report: combined output contains pack/runtime/charge keys
  - pack_report: warnings list is present
  - pack_report: invalid cell spec propagates error
  - LLM tool handlers via registry stub (battery_size_pack, battery_runtime,
    battery_charge_time, battery_report)

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
_KERF_CHAT_SAVED = {
    _n: sys.modules.get(_n)
    for _n in ("kerf_chat", "kerf_chat.tools", "kerf_chat.tools.registry")
}
if _kc_real is None:
    sys.modules["kerf_chat.tools.registry"] = _reg_stub

# ── Ensure src/ on path ───────────────────────────────────────────────────────
_HERE = os.path.dirname(os.path.abspath(__file__))
_SRC = os.path.join(os.path.dirname(_HERE), "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

import pytest

from kerf_electronics.battery.pack import (
    estimate_charge_time,
    estimate_runtime,
    estimate_thermal_rise,
    pack_report,
    size_pack,
)

# ── Load tool module via importlib so the stub is active ─────────────────────
_tool_spec = importlib.util.spec_from_file_location(
    "kerf_electronics.battery.tools",
    os.path.join(_SRC, "kerf_electronics", "battery", "tools.py"),
)
_tool_mod = importlib.util.module_from_spec(_tool_spec)
_tool_spec.loader.exec_module(_tool_mod)

battery_size_pack_tool = _tool_mod.battery_size_pack
battery_runtime_tool = _tool_mod.battery_runtime
battery_charge_time_tool = _tool_mod.battery_charge_time
battery_report_tool = _tool_mod.battery_report


# ── Async call helper ─────────────────────────────────────────────────────────

async def call(fn, **kwargs):
    result = await fn(None, json.dumps(kwargs).encode())
    return json.loads(result)


# ═══════════════════════════════════════════════════════════════════════════════
# 1. size_pack — configuration math
# ═══════════════════════════════════════════════════════════════════════════════

class TestSizePack:
    def test_single_cell_pack(self):
        """1S1P: target <= cell ratings → 1 series, 1 parallel."""
        r = size_pack(3.6, 2.0, 3.6, 3.0)
        assert r["ok"] is True
        assert r["n_series"] == 1
        assert r["n_parallel"] == 1

    def test_series_ceil_arithmetic(self):
        """4S: 14.4 V target / 3.6 V cell = 4 exactly."""
        r = size_pack(14.4, 2.0, 3.6, 3.0)
        assert r["ok"] is True
        assert r["n_series"] == 4

    def test_series_ceil_rounds_up(self):
        """Target = 10 V, cell = 3.6 V → ceil(10/3.6) = 3."""
        r = size_pack(10.0, 2.0, 3.6, 3.0)
        assert r["ok"] is True
        assert r["n_series"] == 3

    def test_parallel_ceil_rounds_up(self):
        """Target = 5 Ah, cell = 3.0 Ah → ceil(5/3) = 2 parallel."""
        r = size_pack(3.6, 5.0, 3.6, 3.0)
        assert r["ok"] is True
        assert r["n_parallel"] == 2

    def test_n_total_equals_ns_times_np(self):
        r = size_pack(14.4, 9.0, 3.6, 3.0)
        assert r["ok"] is True
        assert r["n_total"] == r["n_series"] * r["n_parallel"]

    def test_pack_voltage_equals_ns_times_vcell(self):
        r = size_pack(14.4, 3.0, 3.6, 3.0)
        assert r["ok"] is True
        expected_v = r["n_series"] * 3.6
        assert abs(r["pack_voltage_v"] - expected_v) < 1e-9

    def test_pack_capacity_equals_np_times_qcell(self):
        r = size_pack(14.4, 9.0, 3.6, 3.0)
        assert r["ok"] is True
        expected_q = r["n_parallel"] * 3.0
        assert abs(r["pack_capacity_ah"] - expected_q) < 1e-9

    def test_pack_energy_equals_v_times_ah(self):
        r = size_pack(14.4, 9.0, 3.6, 3.0)
        assert r["ok"] is True
        expected = r["pack_voltage_v"] * r["pack_capacity_ah"]
        assert abs(r["pack_energy_wh"] - expected) < 1e-6

    def test_pack_mass_scales_with_cell_count(self):
        r = size_pack(14.4, 9.0, 3.6, 3.0, cell_mass_g=46.0)
        assert r["ok"] is True
        expected_mass = r["n_total"] * 46.0
        assert abs(r["pack_mass_g"] - expected_mass) < 1e-6

    def test_pack_volume_scales_with_cell_count(self):
        r = size_pack(14.4, 9.0, 3.6, 3.0, cell_volume_cm3=16.5)
        assert r["ok"] is True
        expected_vol = r["n_total"] * 16.5
        assert abs(r["pack_volume_cm3"] - expected_vol) < 1e-6

    def test_pack_r_int_series_parallel(self):
        """R_pack = n_s * R_cell / n_p."""
        r = size_pack(14.4, 6.0, 3.6, 3.0, cell_r_int_ohm=0.05)
        assert r["ok"] is True
        expected_r = r["n_series"] * 0.05 / r["n_parallel"]
        assert abs(r["pack_r_int_ohm"] - expected_r) < 1e-9

    def test_missing_target_voltage_error(self):
        r = size_pack(None, 3.0, 3.6, 3.0)
        assert r["ok"] is False

    def test_zero_cell_voltage_error(self):
        r = size_pack(14.4, 3.0, 0.0, 3.0)
        assert r["ok"] is False

    def test_negative_capacity_error(self):
        r = size_pack(14.4, -1.0, 3.6, 3.0)
        assert r["ok"] is False

    def test_no_mass_given_returns_none(self):
        r = size_pack(3.6, 3.0, 3.6, 3.0)
        assert r["ok"] is True
        assert r["pack_mass_g"] is None

    def test_warnings_list_present(self):
        r = size_pack(3.6, 3.0, 3.6, 3.0)
        assert r["ok"] is True
        assert isinstance(r["warnings"], list)


# ═══════════════════════════════════════════════════════════════════════════════
# 2. estimate_runtime — physics & monotonicity
# ═══════════════════════════════════════════════════════════════════════════════

class TestEstimateRuntime:
    def _simple_profile(self, power_w: float, duration_s: float) -> list[dict]:
        return [{"power_W": power_w, "duration_s": duration_s}]

    def test_zero_load_returns_full_duration(self):
        """Zero-power step: no charge consumed, full duration returned."""
        r = estimate_runtime(
            pack_capacity_ah=10.0,
            pack_voltage_v=12.0,
            load_profile=[{"power_W": 0.0, "duration_s": 3600.0}],
            peukert_k=1.0,
            dod_limit=1.0,
        )
        assert r["ok"] is True
        assert abs(r["runtime_s"] - 3600.0) < 1e-6
        assert r["exhausted"] is False

    def test_constant_load_depletes_at_expected_time(self):
        """10 Ah at 12 V = 120 Wh; 60 W load → 2 h = 7200 s."""
        r = estimate_runtime(
            pack_capacity_ah=10.0,
            pack_voltage_v=12.0,
            load_profile=[{"power_W": 60.0, "duration_s": 7200.0}],
            peukert_k=1.0,
            dod_limit=1.0,
        )
        assert r["ok"] is True
        # With k=1.0 and dod=1.0, all 10 Ah is usable; 60W/12V = 5A; t = 10/5 h = 2 h
        assert abs(r["runtime_s"] - 7200.0) < 1.0
        assert r["exhausted"] is False

    def test_peukert_higher_k_shorter_runtime(self):
        """Higher Peukert exponent → shorter effective capacity at same current."""
        base = estimate_runtime(
            pack_capacity_ah=5.0, pack_voltage_v=12.0,
            load_profile=[{"power_W": 30.0, "duration_s": 7200.0}],
            peukert_k=1.0, dod_limit=1.0,
        )
        penalized = estimate_runtime(
            pack_capacity_ah=5.0, pack_voltage_v=12.0,
            load_profile=[{"power_W": 30.0, "duration_s": 7200.0}],
            peukert_k=1.3, dod_limit=1.0,
        )
        assert base["ok"] and penalized["ok"]
        assert penalized["runtime_s"] <= base["runtime_s"]

    def test_dod_limit_reduces_usable_capacity(self):
        """50% DoD should give half the runtime of 100% DoD at same load."""
        full = estimate_runtime(
            pack_capacity_ah=10.0, pack_voltage_v=12.0,
            load_profile=[{"power_W": 60.0, "duration_s": 7200.0}],
            peukert_k=1.0, dod_limit=1.0,
        )
        half = estimate_runtime(
            pack_capacity_ah=10.0, pack_voltage_v=12.0,
            load_profile=[{"power_W": 60.0, "duration_s": 7200.0}],
            peukert_k=1.0, dod_limit=0.5,
        )
        assert full["ok"] and half["ok"]
        assert abs(half["runtime_s"] - full["runtime_s"] * 0.5) < 1.0

    def test_larger_dod_longer_runtime(self):
        """Monotonicity: higher DoD → longer available runtime."""
        r1 = estimate_runtime(
            pack_capacity_ah=10.0, pack_voltage_v=12.0,
            load_profile=[{"power_W": 30.0, "duration_s": 14400.0}],
            peukert_k=1.0, dod_limit=0.7,
        )
        r2 = estimate_runtime(
            pack_capacity_ah=10.0, pack_voltage_v=12.0,
            load_profile=[{"power_W": 30.0, "duration_s": 14400.0}],
            peukert_k=1.0, dod_limit=0.9,
        )
        assert r1["ok"] and r2["ok"]
        assert r2["runtime_s"] >= r1["runtime_s"]

    def test_higher_power_shorter_runtime(self):
        """Monotonicity: higher power draw → shorter runtime."""
        low = estimate_runtime(
            pack_capacity_ah=10.0, pack_voltage_v=12.0,
            load_profile=[{"power_W": 12.0, "duration_s": 36000.0}],
            peukert_k=1.0, dod_limit=1.0,
        )
        high = estimate_runtime(
            pack_capacity_ah=10.0, pack_voltage_v=12.0,
            load_profile=[{"power_W": 120.0, "duration_s": 36000.0}],
            peukert_k=1.0, dod_limit=1.0,
        )
        assert low["ok"] and high["ok"]
        assert high["runtime_s"] < low["runtime_s"]

    def test_exhausted_flag_when_pack_depletes(self):
        """Requesting more runtime than available → exhausted=True."""
        r = estimate_runtime(
            pack_capacity_ah=1.0, pack_voltage_v=12.0,
            load_profile=[{"power_W": 120.0, "duration_s": 7200.0}],
            peukert_k=1.0, dod_limit=1.0,
        )
        assert r["ok"] is True
        assert r["exhausted"] is True

    def test_exhausted_false_when_fits(self):
        """Profile fits entirely within capacity → exhausted=False."""
        r = estimate_runtime(
            pack_capacity_ah=100.0, pack_voltage_v=12.0,
            load_profile=[{"power_W": 12.0, "duration_s": 60.0}],
            peukert_k=1.0, dod_limit=1.0,
        )
        assert r["ok"] is True
        assert r["exhausted"] is False

    def test_c_rate_warning_when_exceeded(self):
        """Warning added when step current > max C-rate."""
        # 120W / 12V = 10A on a 1 Ah pack = 10C; max is 5C
        r = estimate_runtime(
            pack_capacity_ah=1.0, pack_voltage_v=12.0,
            load_profile=[{"power_W": 120.0, "duration_s": 60.0}],
            peukert_k=1.0, dod_limit=1.0,
            cell_max_discharge_c=5.0,
        )
        assert r["ok"] is True
        assert len(r["warnings"]) > 0

    def test_no_c_rate_warning_when_within_limit(self):
        """No warning when current is below max C-rate."""
        # 12W / 12V = 1A on a 10 Ah pack = 0.1C; max is 2C
        r = estimate_runtime(
            pack_capacity_ah=10.0, pack_voltage_v=12.0,
            load_profile=[{"power_W": 12.0, "duration_s": 600.0}],
            peukert_k=1.0, dod_limit=1.0,
            cell_max_discharge_c=2.0,
        )
        assert r["ok"] is True
        assert all("C-rate" not in w for w in r["warnings"])

    def test_multi_step_energy_sums_correctly(self):
        """Total energy = sum of per-step energies."""
        profile = [
            {"power_W": 10.0, "duration_s": 600.0},
            {"power_W": 20.0, "duration_s": 300.0},
            {"power_W": 5.0,  "duration_s": 1200.0},
        ]
        r = estimate_runtime(
            pack_capacity_ah=100.0, pack_voltage_v=12.0,
            load_profile=profile, peukert_k=1.0, dod_limit=1.0,
        )
        assert r["ok"] is True
        step_energy_sum = sum(s["energy_wh"] for s in r["steps"])
        assert abs(step_energy_sum - r["energy_delivered_wh"]) < 1e-6

    def test_invalid_load_profile_entry_returns_error(self):
        r = estimate_runtime(
            pack_capacity_ah=10.0, pack_voltage_v=12.0,
            load_profile=["not a dict"],
            peukert_k=1.0, dod_limit=1.0,
        )
        assert r["ok"] is False

    def test_empty_load_profile_returns_error(self):
        r = estimate_runtime(
            pack_capacity_ah=10.0, pack_voltage_v=12.0,
            load_profile=[], peukert_k=1.0, dod_limit=1.0,
        )
        assert r["ok"] is False


# ═══════════════════════════════════════════════════════════════════════════════
# 3. estimate_charge_time — CC-CV model
# ═══════════════════════════════════════════════════════════════════════════════

class TestEstimateChargeTime:
    def test_total_time_equals_cc_plus_cv(self):
        r = estimate_charge_time(10.0, charge_c_rate=0.5, dod_at_start=0.8)
        assert r["ok"] is True
        assert abs(r["total_time_h"] - (r["cc_time_h"] + r["cv_tail_h"])) < 1e-9

    def test_cv_tail_is_20pct_of_cc(self):
        r = estimate_charge_time(10.0, charge_c_rate=0.5, dod_at_start=0.8)
        assert r["ok"] is True
        assert abs(r["cv_tail_h"] - 0.2 * r["cc_time_h"]) < 1e-9

    def test_faster_rate_reduces_cc_time(self):
        r1 = estimate_charge_time(10.0, charge_c_rate=0.5, dod_at_start=0.8)
        r2 = estimate_charge_time(10.0, charge_c_rate=1.0, dod_at_start=0.8)
        assert r1["ok"] and r2["ok"]
        assert r2["cc_time_h"] < r1["cc_time_h"]

    def test_higher_dod_increases_charge_time(self):
        r1 = estimate_charge_time(10.0, charge_c_rate=0.5, dod_at_start=0.5)
        r2 = estimate_charge_time(10.0, charge_c_rate=0.5, dod_at_start=0.9)
        assert r1["ok"] and r2["ok"]
        assert r2["total_time_h"] > r1["total_time_h"]

    def test_total_time_min_consistent(self):
        r = estimate_charge_time(10.0, charge_c_rate=1.0, dod_at_start=1.0)
        assert r["ok"] is True
        assert abs(r["total_time_min"] - r["total_time_h"] * 60.0) < 1e-6

    def test_zero_capacity_returns_error(self):
        r = estimate_charge_time(0.0)
        assert r["ok"] is False

    def test_negative_c_rate_returns_error(self):
        r = estimate_charge_time(10.0, charge_c_rate=-0.5)
        assert r["ok"] is False

    def test_dod_over_one_returns_error(self):
        r = estimate_charge_time(10.0, dod_at_start=1.5)
        assert r["ok"] is False


# ═══════════════════════════════════════════════════════════════════════════════
# 4. estimate_thermal_rise — Joule heating
# ═══════════════════════════════════════════════════════════════════════════════

class TestEstimateThermalRise:
    def test_formula_exact(self):
        """ΔT = I² * R * t / (m * c)."""
        r = estimate_thermal_rise(
            pack_r_int_ohm=0.1,
            discharge_current_a=10.0,
            discharge_time_s=3600.0,
            pack_mass_g=500.0,
            specific_heat_j_kg_c=900.0,
        )
        assert r["ok"] is True
        heat = 10.0 ** 2 * 0.1 * 3600.0
        delta_t = heat / (0.5 * 900.0)
        assert abs(r["heat_generated_j"] - heat) < 1e-6
        assert abs(r["delta_T_c"] - delta_t) < 1e-6

    def test_heavier_pack_lower_delta_t(self):
        """Larger mass → lower temperature rise."""
        r1 = estimate_thermal_rise(0.1, 5.0, 3600.0, 200.0)
        r2 = estimate_thermal_rise(0.1, 5.0, 3600.0, 2000.0)
        assert r1["ok"] and r2["ok"]
        assert r2["delta_T_c"] < r1["delta_T_c"]

    def test_zero_current_zero_heat(self):
        r = estimate_thermal_rise(0.1, 0.0, 3600.0, 500.0)
        assert r["ok"] is True
        assert r["heat_generated_j"] == 0.0
        assert r["delta_T_c"] == 0.0

    def test_warning_when_delta_t_over_20(self):
        """Very high current + low mass → ΔT > 20 °C → warning."""
        r = estimate_thermal_rise(
            pack_r_int_ohm=1.0,
            discharge_current_a=100.0,
            discharge_time_s=3600.0,
            pack_mass_g=100.0,
            specific_heat_j_kg_c=900.0,
        )
        assert r["ok"] is True
        assert len(r["warnings"]) > 0

    def test_invalid_r_int_returns_error(self):
        r = estimate_thermal_rise(0.0, 10.0, 3600.0, 500.0)
        assert r["ok"] is False

    def test_invalid_mass_returns_error(self):
        r = estimate_thermal_rise(0.1, 10.0, 3600.0, -100.0)
        assert r["ok"] is False


# ═══════════════════════════════════════════════════════════════════════════════
# 5. pack_report — combined report
# ═══════════════════════════════════════════════════════════════════════════════

class TestPackReport:
    def _profile(self):
        return [{"power_W": 10.0, "duration_s": 3600.0}]

    def test_combined_keys_present(self):
        r = pack_report(14.4, 3.0, 3.6, 3.0, self._profile())
        assert r["ok"] is True
        assert "pack" in r
        assert "runtime" in r
        assert "charge" in r
        assert "warnings" in r

    def test_thermal_present_when_r_and_mass_given(self):
        r = pack_report(14.4, 3.0, 3.6, 3.0, self._profile(),
                        cell_r_int_ohm=0.05, cell_mass_g=46.0)
        assert r["ok"] is True
        assert r["thermal"] is not None
        assert r["thermal"]["ok"] is True

    def test_thermal_none_when_no_r_int(self):
        r = pack_report(14.4, 3.0, 3.6, 3.0, self._profile())
        assert r["ok"] is True
        assert r["thermal"] is None

    def test_invalid_cell_spec_propagates_error(self):
        r = pack_report(14.4, 3.0, 0.0, 3.0, self._profile())
        assert r["ok"] is False

    def test_warnings_is_list(self):
        r = pack_report(14.4, 3.0, 3.6, 3.0, self._profile())
        assert r["ok"] is True
        assert isinstance(r["warnings"], list)


# ═══════════════════════════════════════════════════════════════════════════════
# 6. LLM tool handlers
# ═══════════════════════════════════════════════════════════════════════════════

class TestToolBatterySizePack:
    @pytest.mark.asyncio
    async def test_basic_4s2p(self):
        result = await call(
            battery_size_pack_tool,
            target_voltage_v=14.4,
            target_capacity_ah=6.0,
            cell_voltage_v=3.6,
            cell_capacity_ah=3.0,
        )
        assert result["ok"] is True
        assert result["n_series"] == 4
        assert result["n_parallel"] == 2

    @pytest.mark.asyncio
    async def test_missing_required_returns_error(self):
        result = await call(
            battery_size_pack_tool,
            target_voltage_v=14.4,
            # missing cell_voltage_v
            target_capacity_ah=6.0,
            cell_capacity_ah=3.0,
        )
        assert "error" in result

    @pytest.mark.asyncio
    async def test_invalid_json_returns_error(self):
        res = json.loads(await battery_size_pack_tool(None, b"not json"))
        assert "error" in res


class TestToolBatteryRuntime:
    @pytest.mark.asyncio
    async def test_basic_runtime_call(self):
        result = await call(
            battery_runtime_tool,
            pack_capacity_ah=10.0,
            pack_voltage_v=12.0,
            load_profile=[{"power_W": 60.0, "duration_s": 7200.0}],
            peukert_k=1.0,
            dod_limit=1.0,
        )
        assert result["ok"] is True
        assert result["runtime_s"] > 0

    @pytest.mark.asyncio
    async def test_exhausted_flag_via_tool(self):
        result = await call(
            battery_runtime_tool,
            pack_capacity_ah=0.1,
            pack_voltage_v=12.0,
            load_profile=[{"power_W": 120.0, "duration_s": 7200.0}],
        )
        assert result["ok"] is True
        assert result["exhausted"] is True

    @pytest.mark.asyncio
    async def test_invalid_json_returns_error(self):
        res = json.loads(await battery_runtime_tool(None, b"{bad json"))
        assert "error" in res


class TestToolBatteryChargeTime:
    @pytest.mark.asyncio
    async def test_basic_charge_time(self):
        result = await call(
            battery_charge_time_tool,
            pack_capacity_ah=10.0,
            charge_c_rate=0.5,
            dod_at_start=0.8,
        )
        assert result["ok"] is True
        assert result["total_time_h"] > 0

    @pytest.mark.asyncio
    async def test_missing_capacity_returns_error(self):
        result = await call(battery_charge_time_tool, charge_c_rate=0.5)
        assert "error" in result

    @pytest.mark.asyncio
    async def test_defaults_applied(self):
        """Calling with only pack_capacity_ah should use default c_rate and dod."""
        result = await call(battery_charge_time_tool, pack_capacity_ah=5.0)
        assert result["ok"] is True


class TestToolBatteryReport:
    @pytest.mark.asyncio
    async def test_full_report(self):
        result = await call(
            battery_report_tool,
            target_voltage_v=14.4,
            target_capacity_ah=3.0,
            cell_voltage_v=3.6,
            cell_capacity_ah=3.0,
            load_profile=[{"power_W": 20.0, "duration_s": 3600.0}],
            cell_mass_g=46.0,
            cell_r_int_ohm=0.05,
        )
        assert result["ok"] is True
        assert "pack" in result
        assert "runtime" in result
        assert "charge" in result

    @pytest.mark.asyncio
    async def test_invalid_pack_spec_returns_error(self):
        result = await call(
            battery_report_tool,
            target_voltage_v=0.0,
            target_capacity_ah=3.0,
            cell_voltage_v=3.6,
            cell_capacity_ah=3.0,
            load_profile=[{"power_W": 10.0, "duration_s": 600.0}],
        )
        assert "error" in result


# ── Restore sys.modules so the kerf_chat stub does not leak ──────────────────
def teardown_module(module):  # noqa: D401
    import sys as _sys
    for _name, _orig in _KERF_CHAT_SAVED.items():
        if _orig is None:
            _sys.modules.pop(_name, None)
        else:
            _sys.modules[_name] = _orig
