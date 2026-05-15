"""
Hermetic tests for kerf_electronics thermal junction-temperature estimator.

Covers:
  - Tj = Ta + P * Rθ exact (θja, θjc+θcs+θsa chain)
  - Zero power → Tj = Ta
  - Adding a heatsink lowers Tj
  - Heavier copper → lower spreading resistance
  - copper_spreading_resistance decreasing with area
  - Derating: over_limit flag set when Tj > Tj_max
  - Derating: over_limit clear when Tj ≤ Tj_max
  - margin_c = tj_max_c − tj_c (exact)
  - θja model vs θjc+θcs+θsa model give same Tj when resistances equal
  - thermal_heatsink_required exact back-calculation
  - thermal_heatsink_required: adding heatsink lowers Tj (forward verify)
  - thermal_heatsink_required: infeasible when Tj_max < Ta + P*θjc
  - thermal_heatsink_required: zero power → no heatsink needed
  - thermal_heatsink_required: safety margin reduces θsa_max
  - Board rollup sums total_power_w exactly
  - Board rollup flags worst_ref correctly (highest Tj)
  - Board rollup: any_over_limit True when one component over limit
  - Board rollup: any_over_limit False when none over limit
  - Board rollup: empty components → ok=False
  - Negative theta_ja → friendly error, ok=False
  - Negative theta_jc → friendly error, ok=False
  - Negative theta_cs → friendly error, ok=False
  - Negative theta_sa → friendly error, ok=False
  - Negative power → friendly error, ok=False
  - Missing thermal resistance → friendly error, ok=False
  - LLM tool handlers via registry stub (thermal_junction_tool,
    thermal_board_report_tool, thermal_heatsink_required_tool)

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

from kerf_electronics.thermal.model import (
    ThermalComponent,
    copper_spreading_resistance,
    thermal_board_report,
    thermal_heatsink_required,
    thermal_junction,
)

# ── Load tool module via importlib so the stub is active ─────────────────────
_tool_spec = importlib.util.spec_from_file_location(
    "kerf_electronics.tools.thermal",
    os.path.join(_SRC, "kerf_electronics", "tools", "thermal.py"),
)
_tool_mod = importlib.util.module_from_spec(_tool_spec)
_tool_spec.loader.exec_module(_tool_mod)

thermal_junction_tool = _tool_mod.thermal_junction_tool
thermal_board_report_tool = _tool_mod.thermal_board_report_tool
thermal_heatsink_required_tool = _tool_mod.thermal_heatsink_required_tool


# ── Async helper ──────────────────────────────────────────────────────────────

async def call(fn, **kwargs):
    result = await fn(None, json.dumps(kwargs).encode())
    return json.loads(result)


# ═══════════════════════════════════════════════════════════════════════════════
# 1. thermal_junction — pure model
# ═══════════════════════════════════════════════════════════════════════════════

class TestThermalJunctionModel:
    def test_theta_ja_exact(self):
        """Tj = Ta + P * θja."""
        res = thermal_junction(power_w=5.0, ambient_c=25.0, theta_ja=20.0)
        assert res["ok"] is True
        assert abs(res["tj_c"] - (25.0 + 5.0 * 20.0)) < 1e-9

    def test_three_element_chain_exact(self):
        """Tj = Ta + P * (θjc + θcs + θsa)."""
        res = thermal_junction(
            power_w=2.0,
            ambient_c=30.0,
            theta_jc=5.0,
            theta_cs=1.0,
            theta_sa=4.0,
        )
        assert res["ok"] is True
        expected = 30.0 + 2.0 * (5.0 + 1.0 + 4.0)
        assert abs(res["tj_c"] - expected) < 1e-9

    def test_zero_power_tj_equals_ta(self):
        """P=0 → Tj = Ta exactly."""
        res = thermal_junction(power_w=0.0, ambient_c=40.0, theta_ja=50.0)
        assert res["ok"] is True
        assert abs(res["tj_c"] - 40.0) < 1e-9

    def test_heatsink_lowers_tj_compared_to_no_heatsink(self):
        """Adding a heatsink (lower effective R) gives lower Tj."""
        # No heatsink: θja = 60 °C/W
        no_hs = thermal_junction(power_w=3.0, ambient_c=25.0, theta_ja=60.0)
        # Heatsink: θjc=5, θcs=1, θsa=10 → total 16 °C/W < 60 °C/W
        with_hs = thermal_junction(
            power_w=3.0,
            ambient_c=25.0,
            theta_jc=5.0,
            theta_cs=1.0,
            theta_sa=10.0,
        )
        assert no_hs["ok"] and with_hs["ok"]
        assert with_hs["tj_c"] < no_hs["tj_c"]

    def test_over_limit_flagged_when_tj_exceeds_tj_max(self):
        """over_limit = True when Tj > Tj_max."""
        res = thermal_junction(
            power_w=10.0, ambient_c=25.0, theta_ja=15.0, tj_max_c=100.0
        )
        # Tj = 25 + 10*15 = 175 > 100
        assert res["ok"] is True
        assert res["over_limit"] is True
        assert res["margin_c"] < 0

    def test_over_limit_clear_when_tj_within_tj_max(self):
        """over_limit = False when Tj ≤ Tj_max."""
        res = thermal_junction(
            power_w=2.0, ambient_c=25.0, theta_ja=10.0, tj_max_c=150.0
        )
        # Tj = 25 + 20 = 45 < 150
        assert res["ok"] is True
        assert res["over_limit"] is False
        assert res["margin_c"] > 0

    def test_margin_c_exact(self):
        """margin_c = tj_max_c − tj_c exactly."""
        tj_max = 125.0
        res = thermal_junction(
            power_w=4.0, ambient_c=25.0, theta_ja=10.0, tj_max_c=tj_max
        )
        expected_tj = 25.0 + 4.0 * 10.0
        assert abs(res["margin_c"] - (tj_max - expected_tj)) < 1e-9

    def test_negative_power_friendly_error(self):
        """Negative power → ok=False, not raise."""
        res = thermal_junction(power_w=-1.0, ambient_c=25.0, theta_ja=20.0)
        assert res["ok"] is False
        assert "power_w" in res["reason"]

    def test_negative_theta_ja_friendly_error(self):
        """Negative θja → ok=False."""
        res = thermal_junction(power_w=1.0, ambient_c=25.0, theta_ja=-5.0)
        assert res["ok"] is False
        assert "theta_ja" in res["reason"]

    def test_negative_theta_jc_friendly_error(self):
        """Negative θjc → ok=False."""
        res = thermal_junction(
            power_w=1.0, ambient_c=25.0, theta_jc=-5.0, theta_sa=10.0
        )
        assert res["ok"] is False
        assert "theta_jc" in res["reason"]

    def test_negative_theta_cs_friendly_error(self):
        """Negative θcs → ok=False."""
        res = thermal_junction(
            power_w=1.0, ambient_c=25.0, theta_jc=5.0, theta_cs=-1.0, theta_sa=10.0
        )
        assert res["ok"] is False
        assert "theta_cs" in res["reason"]

    def test_negative_theta_sa_friendly_error(self):
        """Negative θsa → ok=False."""
        res = thermal_junction(
            power_w=1.0, ambient_c=25.0, theta_jc=5.0, theta_sa=-3.0
        )
        assert res["ok"] is False
        assert "theta_sa" in res["reason"]

    def test_missing_thermal_resistance_friendly_error(self):
        """No θja and no θjc/θsa → ok=False."""
        res = thermal_junction(power_w=2.0, ambient_c=25.0)
        assert res["ok"] is False
        assert "theta_ja" in res["reason"] or "theta_jc" in res["reason"]

    def test_theta_ja_equals_chain_when_equal(self):
        """θja model ≡ chain model when θjc+θcs+θsa == θja."""
        theta = 30.0
        res_ja = thermal_junction(power_w=3.0, ambient_c=25.0, theta_ja=theta)
        res_chain = thermal_junction(
            power_w=3.0,
            ambient_c=25.0,
            theta_jc=20.0,
            theta_cs=5.0,
            theta_sa=5.0,
        )
        assert abs(res_ja["tj_c"] - res_chain["tj_c"]) < 1e-9

    def test_has_heatsink_flag_set_correctly(self):
        """has_heatsink True iff theta_jc and theta_sa both supplied."""
        res_no = thermal_junction(power_w=1.0, ambient_c=25.0, theta_ja=30.0)
        res_hs = thermal_junction(
            power_w=1.0, ambient_c=25.0, theta_jc=5.0, theta_sa=10.0
        )
        assert res_no["has_heatsink"] is False
        assert res_hs["has_heatsink"] is True


# ═══════════════════════════════════════════════════════════════════════════════
# 2. copper_spreading_resistance
# ═══════════════════════════════════════════════════════════════════════════════

class TestCopperSpreadingResistance:
    def test_larger_area_lower_resistance(self):
        """More copper area → lower spreading resistance."""
        r_small = copper_spreading_resistance(100.0, 1.0)
        r_large = copper_spreading_resistance(1000.0, 1.0)
        assert r_small > r_large

    def test_heavier_copper_lower_resistance(self):
        """Thicker copper → lower spreading resistance."""
        r_1oz = copper_spreading_resistance(500.0, 1.0)
        r_2oz = copper_spreading_resistance(500.0, 2.0)
        assert r_2oz < r_1oz

    def test_resistance_positive(self):
        """Spreading resistance is always positive."""
        r = copper_spreading_resistance(200.0, 1.0)
        assert r > 0

    def test_invalid_area_raises(self):
        """Zero or negative area raises ValueError."""
        with pytest.raises(ValueError):
            copper_spreading_resistance(0.0, 1.0)
        with pytest.raises(ValueError):
            copper_spreading_resistance(-100.0, 1.0)

    def test_formula_sanity(self):
        """Spot-check: 500 mm² of 1 oz copper gives a finite, positive °C/W."""
        r = copper_spreading_resistance(500.0, 1.0)
        # Just verify it is a finite positive number (formula is a first-order
        # circular spreading approximation; units are consistent)
        assert math.isfinite(r)
        assert r > 0


# ═══════════════════════════════════════════════════════════════════════════════
# 3. thermal_heatsink_required
# ═══════════════════════════════════════════════════════════════════════════════

class TestThermalHeatsinkRequired:
    def test_exact_back_calculation(self):
        """θsa_max back-calculates so Tj = Tj_max exactly."""
        power_w = 5.0
        ambient_c = 25.0
        theta_jc = 8.0
        theta_cs = 1.0
        tj_max = 125.0

        res = thermal_heatsink_required(
            power_w=power_w,
            ambient_c=ambient_c,
            theta_jc=theta_jc,
            tj_max_c=tj_max,
            theta_cs=theta_cs,
        )
        assert res["ok"] is True
        theta_sa_max = res["theta_sa_max_c_w"]
        # Forward verify
        tj_verify = ambient_c + power_w * (theta_jc + theta_cs + theta_sa_max)
        assert abs(tj_verify - tj_max) < 1e-6

    def test_heatsink_at_theta_sa_max_gives_tj_at_limit(self):
        """Heatsink with θsa = θsa_max → Tj ≤ Tj_max (no margin)."""
        res = thermal_heatsink_required(
            power_w=3.0,
            ambient_c=30.0,
            theta_jc=6.0,
            tj_max_c=100.0,
        )
        assert res["feasible"] is True
        theta_sa = res["theta_sa_max_c_w"]
        tj = 30.0 + 3.0 * (6.0 + 0.0 + theta_sa)
        assert abs(tj - 100.0) < 1e-6

    def test_infeasible_when_no_heatsink_can_help(self):
        """If Ta + P*θjc > Tj_max, no heatsink can help → feasible=False."""
        # P=100W, θjc=5 °C/W, Ta=25 → base temp = 525 °C > any Tj_max
        res = thermal_heatsink_required(
            power_w=100.0,
            ambient_c=25.0,
            theta_jc=5.0,
            tj_max_c=150.0,
        )
        assert res["ok"] is True
        assert res["feasible"] is False

    def test_zero_power_no_heatsink_needed(self):
        """P=0 → no heatsink required, note field present."""
        res = thermal_heatsink_required(
            power_w=0.0,
            ambient_c=25.0,
            theta_jc=8.0,
            tj_max_c=125.0,
        )
        assert res["ok"] is True
        assert res["feasible"] is True
        assert "note" in res

    def test_safety_margin_reduces_theta_sa_max(self):
        """With safety margin, allowed θsa_max is smaller."""
        res_no_margin = thermal_heatsink_required(
            power_w=5.0, ambient_c=25.0, theta_jc=5.0, tj_max_c=125.0,
            safety_margin_c=0.0,
        )
        res_margin = thermal_heatsink_required(
            power_w=5.0, ambient_c=25.0, theta_jc=5.0, tj_max_c=125.0,
            safety_margin_c=10.0,
        )
        assert res_no_margin["ok"] and res_margin["ok"]
        assert res_margin["theta_sa_max_c_w"] < res_no_margin["theta_sa_max_c_w"]

    def test_negative_power_friendly_error(self):
        """Negative power → ok=False."""
        res = thermal_heatsink_required(
            power_w=-2.0, ambient_c=25.0, theta_jc=5.0, tj_max_c=125.0
        )
        assert res["ok"] is False


# ═══════════════════════════════════════════════════════════════════════════════
# 4. thermal_board_report
# ═══════════════════════════════════════════════════════════════════════════════

class TestThermalBoardReport:
    def _make_components(self):
        return [
            ThermalComponent(ref="U1", power_w=2.0, theta_ja=20.0, tj_max_c=125.0),
            ThermalComponent(ref="U2", power_w=5.0, theta_ja=15.0, tj_max_c=150.0),
            ThermalComponent(ref="Q1", power_w=1.0, theta_ja=30.0),
        ]

    def test_total_power_sum_exact(self):
        """total_power_w = sum of all component powers."""
        comps = self._make_components()
        res = thermal_board_report(comps, ambient_c=25.0)
        assert res["ok"] is True
        assert abs(res["total_power_w"] - 8.0) < 1e-9

    def test_worst_ref_is_highest_tj(self):
        """worst_ref points to component with highest Tj."""
        # U2: Tj = 25 + 5*15 = 100, U1: 25+2*20=65, Q1: 25+1*30=55
        comps = self._make_components()
        res = thermal_board_report(comps, ambient_c=25.0)
        assert res["worst_ref"] == "U2"
        assert abs(res["worst_tj_c"] - (25.0 + 5.0 * 15.0)) < 1e-9

    def test_any_over_limit_true_when_one_exceeds(self):
        """any_over_limit True when at least one component over Tj_max."""
        comps = [
            ThermalComponent(ref="U1", power_w=10.0, theta_ja=20.0, tj_max_c=50.0),  # Tj=225>50
            ThermalComponent(ref="U2", power_w=1.0, theta_ja=10.0, tj_max_c=200.0),  # Tj=35<200
        ]
        res = thermal_board_report(comps, ambient_c=25.0)
        assert res["ok"] is True
        assert res["any_over_limit"] is True

    def test_any_over_limit_false_when_all_safe(self):
        """any_over_limit False when all components within Tj_max."""
        comps = [
            ThermalComponent(ref="U1", power_w=1.0, theta_ja=10.0, tj_max_c=200.0),
            ThermalComponent(ref="U2", power_w=0.5, theta_ja=5.0, tj_max_c=150.0),
        ]
        res = thermal_board_report(comps, ambient_c=25.0)
        assert res["ok"] is True
        assert res["any_over_limit"] is False

    def test_empty_components_friendly_error(self):
        """Empty components list → ok=False."""
        res = thermal_board_report([], ambient_c=25.0)
        assert res["ok"] is False

    def test_component_count_matches(self):
        """Result has same number of component entries as input."""
        comps = self._make_components()
        res = thermal_board_report(comps, ambient_c=25.0)
        assert len(res["components"]) == len(comps)

    def test_per_component_tj_exact(self):
        """Each component's tj_c = Ta + P * θja."""
        comps = [
            ThermalComponent(ref="R1", power_w=3.0, theta_ja=10.0),
        ]
        res = thermal_board_report(comps, ambient_c=20.0)
        assert res["ok"] is True
        assert abs(res["components"][0]["tj_c"] - (20.0 + 3.0 * 10.0)) < 1e-9


# ═══════════════════════════════════════════════════════════════════════════════
# 5. LLM tool handlers
# ═══════════════════════════════════════════════════════════════════════════════

class TestThermalJunctionTool:
    @pytest.mark.asyncio
    async def test_basic_theta_ja(self):
        """Tool returns ok=True and correct tj_c via θja model."""
        res = await call(thermal_junction_tool, power_w=5.0, ambient_c=25.0, theta_ja=10.0)
        assert res["ok"] is True
        assert abs(res["tj_c"] - 75.0) < 1e-6

    @pytest.mark.asyncio
    async def test_basic_chain(self):
        """Tool returns ok=True via three-element chain."""
        res = await call(
            thermal_junction_tool,
            power_w=2.0, ambient_c=30.0,
            theta_jc=5.0, theta_cs=1.0, theta_sa=4.0,
        )
        assert res["ok"] is True
        expected = 30.0 + 2.0 * 10.0
        assert abs(res["tj_c"] - expected) < 1e-6

    @pytest.mark.asyncio
    async def test_over_limit_flag_via_tool(self):
        """Tool correctly reports over_limit when Tj > Tj_max."""
        res = await call(
            thermal_junction_tool,
            power_w=10.0, ambient_c=25.0, theta_ja=15.0, tj_max_c=100.0,
        )
        assert res["ok"] is True
        assert res["over_limit"] is True

    @pytest.mark.asyncio
    async def test_missing_resistance_returns_error(self):
        """Tool returns error (not exception) when no resistance supplied."""
        res = await call(thermal_junction_tool, power_w=2.0, ambient_c=25.0)
        assert res.get("ok") is not True
        assert "error" in res or res.get("ok") is False

    @pytest.mark.asyncio
    async def test_invalid_args_json_type_error(self):
        """Non-numeric power_w → error response."""
        res = await call(thermal_junction_tool, power_w="hot", ambient_c=25.0, theta_ja=10.0)
        assert res.get("ok") is not True
        assert "error" in res or res.get("ok") is False


class TestThermalBoardReportTool:
    @pytest.mark.asyncio
    async def test_board_report_basic(self):
        """Tool returns ok=True with correct total power."""
        res = await call(
            thermal_board_report_tool,
            ambient_c=25.0,
            components=[
                {"ref": "U1", "power_w": 3.0, "theta_ja": 20.0},
                {"ref": "U2", "power_w": 2.0, "theta_ja": 15.0},
            ],
        )
        assert res["ok"] is True
        assert abs(res["total_power_w"] - 5.0) < 1e-6

    @pytest.mark.asyncio
    async def test_board_report_worst_ref(self):
        """Tool identifies worst_ref correctly."""
        # U1: 25+3*20=85, U2: 25+2*15=55
        res = await call(
            thermal_board_report_tool,
            ambient_c=25.0,
            components=[
                {"ref": "U1", "power_w": 3.0, "theta_ja": 20.0},
                {"ref": "U2", "power_w": 2.0, "theta_ja": 15.0},
            ],
        )
        assert res["worst_ref"] == "U1"

    @pytest.mark.asyncio
    async def test_board_report_empty_components(self):
        """Tool returns error response for empty components."""
        res = await call(thermal_board_report_tool, ambient_c=25.0, components=[])
        assert res.get("ok") is not True
        assert "error" in res or res.get("ok") is False

    @pytest.mark.asyncio
    async def test_board_report_over_limit_flagged(self):
        """Tool sets any_over_limit when component exceeds Tj_max."""
        res = await call(
            thermal_board_report_tool,
            ambient_c=25.0,
            components=[
                {"ref": "U1", "power_w": 20.0, "theta_ja": 10.0, "tj_max_c": 50.0},
            ],
        )
        assert res["ok"] is True
        assert res["any_over_limit"] is True


class TestThermalHeatsinkRequiredTool:
    @pytest.mark.asyncio
    async def test_heatsink_required_basic(self):
        """Tool returns ok=True and feasible θsa_max."""
        res = await call(
            thermal_heatsink_required_tool,
            power_w=5.0, ambient_c=25.0, theta_jc=8.0, tj_max_c=125.0,
        )
        assert res["ok"] is True
        assert res["feasible"] is True
        assert res["theta_sa_max_c_w"] > 0

    @pytest.mark.asyncio
    async def test_heatsink_required_infeasible(self):
        """Tool marks feasible=False when impossible."""
        res = await call(
            thermal_heatsink_required_tool,
            power_w=100.0, ambient_c=25.0, theta_jc=5.0, tj_max_c=150.0,
        )
        assert res["ok"] is True
        assert res["feasible"] is False

    @pytest.mark.asyncio
    async def test_heatsink_required_zero_power(self):
        """Tool handles zero power gracefully."""
        res = await call(
            thermal_heatsink_required_tool,
            power_w=0.0, ambient_c=25.0, theta_jc=8.0, tj_max_c=125.0,
        )
        assert res["ok"] is True
        assert res["feasible"] is True

    @pytest.mark.asyncio
    async def test_missing_required_arg(self):
        """Tool returns error response when required arg missing."""
        # theta_jc missing
        result = await thermal_heatsink_required_tool(
            None, json.dumps({"power_w": 5.0, "ambient_c": 25.0, "tj_max_c": 125.0}).encode()
        )
        res = json.loads(result)
        assert res.get("ok") is not True
        assert "error" in res or res.get("ok") is False
