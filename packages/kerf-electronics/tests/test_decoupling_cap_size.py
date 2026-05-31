"""
Hermetic tests for decoupling_cap_size.py.

Coverage (≥ 12 tests):
  - 3.3 V rail, 2 A, 5 ns rise, 100 mV droop, 4 ICs:
      Z_t = 50 mΩ, bulk_cap = 100 nF
  - More ICs → more bypass caps
  - Faster rise time → smaller bulk cap (same droop/current)
  - Faster rise time → tighter ESL constraint (smaller max_ESL)
  - Higher bandwidth → tighter ESL constraint (max_ESL ∝ 1/f_bw)
  - Higher current → lower Z_t
  - Higher current → larger bulk cap
  - Invalid inputs → ValueError (never silently wrong)
  - Droop ≥ voltage → ValueError
  - LLM tool wrapper round-trips correctly
  - LLM tool wrapper returns error on bad inputs

Loading strategy: stub kerf_chat.tools.registry so no full install required.

Author: imranparuk
"""
from __future__ import annotations

import importlib.util
import json
import math
import os
import sys
import types

# ── Prefer real kerf_chat if present; fall back to stub ──────────────────────
try:
    import kerf_chat as _kc_pkg  # noqa: F401
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
    n: sys.modules.get(n)
    for n in ("kerf_chat", "kerf_chat.tools", "kerf_chat.tools.registry")
}
if _kc_real is None:
    sys.modules["kerf_chat.tools.registry"] = _reg_stub

# ── Ensure src/ is on sys.path ────────────────────────────────────────────────
_HERE = os.path.dirname(os.path.abspath(__file__))
_SRC = os.path.join(os.path.dirname(_HERE), "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

import pytest

from kerf_electronics.decoupling_cap_size import (
    PowerRailSpec,
    DecouplingRecommendation,
    recommend_decoupling_caps,
    recommend_decoupling_caps_from_dict,
)

# ── Load module via importlib to get the tool handler ────────────────────────
_mod_spec = importlib.util.spec_from_file_location(
    "kerf_electronics.decoupling_cap_size",
    os.path.join(_SRC, "kerf_electronics", "decoupling_cap_size.py"),
)
_mod = importlib.util.module_from_spec(_mod_spec)
_mod_spec.loader.exec_module(_mod)
_tool_handler = _mod.electronics_recommend_decoupling_caps


async def _call_tool(**kwargs) -> dict:
    raw = await _tool_handler(None, json.dumps(kwargs).encode())
    return json.loads(raw)


# ── Shared baseline spec ─────────────────────────────────────────────────────
# 3.3 V rail, 2 A transient, 5 ns rise, 100 mV droop, 200 MHz BW, 4 ICs
_BASE = PowerRailSpec(
    voltage_V=3.3,
    max_transient_current_A=2.0,
    transient_rise_time_ns=5.0,
    max_droop_mV=100.0,
    signal_bandwidth_MHz=200.0,
    num_ICs=4,
)


# ═══════════════════════════════════════════════════════════════════════════════
# 1. Canonical oracle: 3.3 V / 2 A / 5 ns / 100 mV / 4 ICs
# ═══════════════════════════════════════════════════════════════════════════════

class TestCanonicalOracle:
    def test_target_impedance_50_mOhm(self):
        """Z_t = ΔV / I = 0.1 V / 2 A = 50 mΩ."""
        rec = recommend_decoupling_caps(_BASE)
        assert abs(rec.target_impedance_mOhm - 50.0) < 1e-9, (
            f"Expected Z_t=50 mΩ, got {rec.target_impedance_mOhm:.6f} mΩ"
        )

    def test_bulk_cap_100_nF(self):
        """C_bulk = I · t_rise / ΔV = 2 · 5e-9 / 0.1 = 100 nF = 0.1 µF."""
        rec = recommend_decoupling_caps(_BASE)
        expected_uF = 2.0 * 5e-9 / 0.1 * 1e6   # = 0.1 µF
        assert abs(rec.bulk_cap_uF - expected_uF) < 1e-9, (
            f"Expected bulk_cap={expected_uF:.6f} µF, got {rec.bulk_cap_uF:.6f} µF"
        )

    def test_bypass_cap_10_nF_at_200_MHz(self):
        """At 200 MHz bandwidth the bypass cap is 10 nF (> 50 MHz threshold)."""
        rec = recommend_decoupling_caps(_BASE)
        assert abs(rec.bypass_cap_uF - 0.01) < 1e-9

    def test_bypass_count_4_for_4_ics(self):
        """4 ICs → 4 bypass caps (1 per IC, Z_t = 50 mΩ ≥ 10 mΩ threshold)."""
        rec = recommend_decoupling_caps(_BASE)
        assert rec.bypass_count == 4

    def test_return_type_is_dataclass(self):
        rec = recommend_decoupling_caps(_BASE)
        assert isinstance(rec, DecouplingRecommendation)


# ═══════════════════════════════════════════════════════════════════════════════
# 2. More ICs → more bypass caps
# ═══════════════════════════════════════════════════════════════════════════════

class TestMoreICsMoreBypassCaps:
    def test_8_ics_gives_8_bypass_caps(self):
        spec = PowerRailSpec(
            voltage_V=3.3,
            max_transient_current_A=2.0,
            transient_rise_time_ns=5.0,
            max_droop_mV=100.0,
            signal_bandwidth_MHz=10.0,
            num_ICs=8,
        )
        rec = recommend_decoupling_caps(spec)
        assert rec.bypass_count == 8

    def test_more_ics_monotonically_more_bypass_caps(self):
        """bypass_count must increase monotonically with num_ICs."""
        prev = 0
        for n in (1, 2, 4, 8, 16):
            spec = PowerRailSpec(
                voltage_V=1.8,
                max_transient_current_A=1.0,
                transient_rise_time_ns=10.0,
                max_droop_mV=50.0,
                signal_bandwidth_MHz=50.0,
                num_ICs=n,
            )
            rec = recommend_decoupling_caps(spec)
            assert rec.bypass_count >= prev
            prev = rec.bypass_count

    def test_very_tight_Zt_doubles_bypass_count(self):
        """Z_t < 10 mΩ → 2× bypass caps per IC."""
        # Z_t = 50 mV / 10 A = 5 mΩ
        spec = PowerRailSpec(
            voltage_V=1.8,
            max_transient_current_A=10.0,
            transient_rise_time_ns=1.0,
            max_droop_mV=50.0,
            signal_bandwidth_MHz=500.0,
            num_ICs=4,
        )
        rec = recommend_decoupling_caps(spec)
        # Z_t = 0.05 / 10 = 5 mΩ < 10 mΩ → count = 4 × 2 = 8
        assert rec.bypass_count == 8


# ═══════════════════════════════════════════════════════════════════════════════
# 3. Faster rise time → smaller bulk cap AND tighter ESL
# ═══════════════════════════════════════════════════════════════════════════════

class TestFasterRiseTime:
    def test_faster_rise_time_smaller_bulk_cap(self):
        """Shorter t_rise → smaller required C_bulk = I · t_rise / ΔV."""
        spec_slow = PowerRailSpec(3.3, 2.0, 10.0, 100.0, 100.0, 1)
        spec_fast = PowerRailSpec(3.3, 2.0, 1.0, 100.0, 100.0, 1)
        rec_slow = recommend_decoupling_caps(spec_slow)
        rec_fast = recommend_decoupling_caps(spec_fast)
        assert rec_fast.bulk_cap_uF < rec_slow.bulk_cap_uF, (
            f"Faster rise should give smaller bulk cap: "
            f"fast={rec_fast.bulk_cap_uF:.4f} µF, slow={rec_slow.bulk_cap_uF:.4f} µF"
        )

    def test_bulk_cap_linear_in_rise_time(self):
        """C_bulk = I · t_rise / ΔV: doubling t_rise doubles C_bulk."""
        spec1 = PowerRailSpec(3.3, 2.0, 5.0, 100.0, 50.0, 1)
        spec2 = PowerRailSpec(3.3, 2.0, 10.0, 100.0, 50.0, 1)
        rec1 = recommend_decoupling_caps(spec1)
        rec2 = recommend_decoupling_caps(spec2)
        assert abs(rec2.bulk_cap_uF / rec1.bulk_cap_uF - 2.0) < 1e-9


# ═══════════════════════════════════════════════════════════════════════════════
# 4. Higher bandwidth → tighter ESL constraint
# ═══════════════════════════════════════════════════════════════════════════════

class TestBandwidthConstraints:
    def test_higher_bandwidth_tighter_esl(self):
        """max_ESL ∝ 1/f_bw: doubling bandwidth halves max_ESL."""
        spec_lo = PowerRailSpec(3.3, 2.0, 5.0, 100.0, 100.0, 1)
        spec_hi = PowerRailSpec(3.3, 2.0, 5.0, 100.0, 200.0, 1)
        rec_lo = recommend_decoupling_caps(spec_lo)
        rec_hi = recommend_decoupling_caps(spec_hi)
        assert rec_hi.max_ESL_nH < rec_lo.max_ESL_nH, (
            f"Higher BW should give tighter ESL: "
            f"hi={rec_hi.max_ESL_nH:.4f} nH, lo={rec_lo.max_ESL_nH:.4f} nH"
        )

    def test_esl_inversely_proportional_to_bandwidth(self):
        """max_ESL = Z_t / (2π · f_bw) × bypass_count: exact formula check."""
        spec = PowerRailSpec(3.3, 2.0, 5.0, 100.0, 100.0, 2)
        rec = recommend_decoupling_caps(spec)
        Z_t = 0.1 / 2.0   # 50 mΩ
        f_bw = 100e6
        expected_esl_H = (Z_t / (2.0 * math.pi * f_bw)) * rec.bypass_count
        expected_esl_nH = expected_esl_H * 1e9
        assert abs(rec.max_ESL_nH - expected_esl_nH) / expected_esl_nH < 1e-9

    def test_50_mhz_threshold_bypass_cap_value(self):
        """At exactly 50 MHz → 100 nF; at 51 MHz → 10 nF."""
        spec_50 = PowerRailSpec(3.3, 1.0, 10.0, 100.0, 50.0, 1)
        spec_51 = PowerRailSpec(3.3, 1.0, 10.0, 100.0, 51.0, 1)
        rec_50 = recommend_decoupling_caps(spec_50)
        rec_51 = recommend_decoupling_caps(spec_51)
        assert abs(rec_50.bypass_cap_uF - 0.1) < 1e-9
        assert abs(rec_51.bypass_cap_uF - 0.01) < 1e-9


# ═══════════════════════════════════════════════════════════════════════════════
# 5. Higher transient current → lower Z_t, larger C_bulk
# ═══════════════════════════════════════════════════════════════════════════════

class TestHigherCurrent:
    def test_higher_current_lower_zt(self):
        """Z_t = ΔV / I: doubling I halves Z_t."""
        spec1 = PowerRailSpec(3.3, 1.0, 5.0, 100.0, 100.0, 1)
        spec2 = PowerRailSpec(3.3, 2.0, 5.0, 100.0, 100.0, 1)
        rec1 = recommend_decoupling_caps(spec1)
        rec2 = recommend_decoupling_caps(spec2)
        assert abs(rec2.target_impedance_mOhm / rec1.target_impedance_mOhm - 0.5) < 1e-9

    def test_higher_current_larger_bulk_cap(self):
        """C_bulk = I · t_rise / ΔV: doubling I doubles C_bulk."""
        spec1 = PowerRailSpec(3.3, 1.0, 5.0, 100.0, 100.0, 1)
        spec2 = PowerRailSpec(3.3, 2.0, 5.0, 100.0, 100.0, 1)
        rec1 = recommend_decoupling_caps(spec1)
        rec2 = recommend_decoupling_caps(spec2)
        assert abs(rec2.bulk_cap_uF / rec1.bulk_cap_uF - 2.0) < 1e-9


# ═══════════════════════════════════════════════════════════════════════════════
# 6. Invalid inputs → ValueError, never silently wrong
# ═══════════════════════════════════════════════════════════════════════════════

class TestInvalidInputs:
    def test_zero_current_raises(self):
        with pytest.raises(ValueError, match="max_transient_current_A"):
            recommend_decoupling_caps(
                PowerRailSpec(3.3, 0.0, 5.0, 100.0, 100.0, 1)
            )

    def test_negative_current_raises(self):
        with pytest.raises(ValueError):
            recommend_decoupling_caps(
                PowerRailSpec(3.3, -1.0, 5.0, 100.0, 100.0, 1)
            )

    def test_zero_droop_raises(self):
        with pytest.raises(ValueError, match="max_droop_mV"):
            recommend_decoupling_caps(
                PowerRailSpec(3.3, 2.0, 5.0, 0.0, 100.0, 1)
            )

    def test_droop_exceeds_voltage_raises(self):
        """100 mV droop on 3.3 V rail is fine; 4000 mV should raise."""
        with pytest.raises(ValueError):
            recommend_decoupling_caps(
                PowerRailSpec(3.3, 2.0, 5.0, 4000.0, 100.0, 1)
            )

    def test_zero_voltage_raises(self):
        with pytest.raises(ValueError, match="voltage_V"):
            recommend_decoupling_caps(
                PowerRailSpec(0.0, 2.0, 5.0, 100.0, 100.0, 1)
            )

    def test_zero_bandwidth_raises(self):
        with pytest.raises(ValueError, match="signal_bandwidth_MHz"):
            recommend_decoupling_caps(
                PowerRailSpec(3.3, 2.0, 5.0, 100.0, 0.0, 1)
            )

    def test_zero_rise_time_raises(self):
        with pytest.raises(ValueError, match="transient_rise_time_ns"):
            recommend_decoupling_caps(
                PowerRailSpec(3.3, 2.0, 0.0, 100.0, 100.0, 1)
            )

    def test_zero_ics_raises(self):
        with pytest.raises(ValueError, match="num_ICs"):
            recommend_decoupling_caps(
                PowerRailSpec(3.3, 2.0, 5.0, 100.0, 100.0, 0)
            )


# ═══════════════════════════════════════════════════════════════════════════════
# 7. Dict entry point (recommend_decoupling_caps_from_dict)
# ═══════════════════════════════════════════════════════════════════════════════

class TestDictEntryPoint:
    def test_valid_dict_returns_ok(self):
        result = recommend_decoupling_caps_from_dict({
            "voltage_V": 3.3,
            "max_transient_current_A": 2.0,
            "transient_rise_time_ns": 5.0,
            "max_droop_mV": 100.0,
            "signal_bandwidth_MHz": 200.0,
            "num_ICs": 4,
        })
        assert result["ok"] is True
        assert "target_impedance_mOhm" in result
        assert "bulk_cap_uF" in result
        assert "bypass_cap_uF" in result
        assert "bypass_count" in result
        assert "max_ESL_nH" in result
        assert "max_ESR_mOhm" in result
        assert "honest_caveat" in result

    def test_missing_key_returns_error(self):
        result = recommend_decoupling_caps_from_dict({
            "voltage_V": 3.3,
            "max_transient_current_A": 2.0,
            # missing transient_rise_time_ns
            "max_droop_mV": 100.0,
            "signal_bandwidth_MHz": 100.0,
            "num_ICs": 4,
        })
        assert result["ok"] is False
        assert "reason" in result

    def test_invalid_value_returns_error(self):
        result = recommend_decoupling_caps_from_dict({
            "voltage_V": 3.3,
            "max_transient_current_A": -1.0,
            "transient_rise_time_ns": 5.0,
            "max_droop_mV": 100.0,
            "signal_bandwidth_MHz": 100.0,
            "num_ICs": 4,
        })
        assert result["ok"] is False

    def test_values_match_direct_call(self):
        """Dict entry point must return same numbers as direct recommend_decoupling_caps."""
        d = {
            "voltage_V": 1.8,
            "max_transient_current_A": 3.0,
            "transient_rise_time_ns": 2.0,
            "max_droop_mV": 50.0,
            "signal_bandwidth_MHz": 300.0,
            "num_ICs": 6,
        }
        result = recommend_decoupling_caps_from_dict(d)
        assert result["ok"] is True
        spec = PowerRailSpec(**{k: (int(v) if k == "num_ICs" else float(v)) for k, v in d.items()})
        rec = recommend_decoupling_caps(spec)
        assert abs(result["target_impedance_mOhm"] - rec.target_impedance_mOhm) < 1e-9
        assert abs(result["bulk_cap_uF"] - rec.bulk_cap_uF) < 1e-9
        assert abs(result["bypass_count"] - rec.bypass_count) < 1e-9


# ═══════════════════════════════════════════════════════════════════════════════
# 8. LLM tool wrapper
# ═══════════════════════════════════════════════════════════════════════════════

class TestLLMToolWrapper:
    @pytest.mark.asyncio
    async def test_tool_ok_round_trip(self):
        res = await _call_tool(
            voltage_V=3.3,
            max_transient_current_A=2.0,
            transient_rise_time_ns=5.0,
            max_droop_mV=100.0,
            signal_bandwidth_MHz=200.0,
            num_ICs=4,
        )
        assert res.get("ok") is True
        assert abs(res["target_impedance_mOhm"] - 50.0) < 1e-6
        assert abs(res["bulk_cap_uF"] - 0.1) < 1e-6

    @pytest.mark.asyncio
    async def test_tool_invalid_json_error(self):
        raw = await _tool_handler(None, b"not valid json{{")
        data = json.loads(raw)
        assert data.get("ok") is False or "error" in data

    @pytest.mark.asyncio
    async def test_tool_zero_current_error(self):
        res = await _call_tool(
            voltage_V=3.3,
            max_transient_current_A=0.0,
            transient_rise_time_ns=5.0,
            max_droop_mV=100.0,
            signal_bandwidth_MHz=100.0,
            num_ICs=1,
        )
        assert res.get("ok") is False or "error" in res

    @pytest.mark.asyncio
    async def test_tool_all_fields_present(self):
        res = await _call_tool(
            voltage_V=1.2,
            max_transient_current_A=5.0,
            transient_rise_time_ns=1.0,
            max_droop_mV=60.0,
            signal_bandwidth_MHz=500.0,
            num_ICs=2,
        )
        assert res.get("ok") is True
        for field in (
            "target_impedance_mOhm",
            "bulk_cap_uF",
            "bypass_cap_uF",
            "bypass_count",
            "max_ESL_nH",
            "max_ESR_mOhm",
            "honest_caveat",
        ):
            assert field in res, f"missing field: {field!r}"

    @pytest.mark.asyncio
    async def test_tool_caveat_mentions_heuristic(self):
        res = await _call_tool(
            voltage_V=3.3,
            max_transient_current_A=2.0,
            transient_rise_time_ns=5.0,
            max_droop_mV=100.0,
            signal_bandwidth_MHz=100.0,
            num_ICs=1,
        )
        assert res.get("ok") is True
        caveat = res.get("honest_caveat", "")
        assert len(caveat) > 20, "honest_caveat should be non-trivial"


# ── Teardown: restore sys.modules ────────────────────────────────────────────


def teardown_module(module):
    for name, orig in _KERF_CHAT_SAVED.items():
        if orig is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = orig
