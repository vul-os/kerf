"""
Tests for PCB via current-carrying capacity — IPC-2152 §6.3 + IPC-2221A §6.

Test inventory (≥ 12 tests as required):

  Physics / formula correctness
    1.  cross_section_area — 0.3 mm drill, 25 µm: A = π·300·25 ≈ 23562 µm²
    2.  cross_section_area_0p5mm — 0.5 mm drill, 25 µm: A = π·500·25 ≈ 39270 µm²
    3.  larger_drill_more_current — 0.5 mm vs 0.3 mm same plating/dT
    4.  thicker_plating_more_current — 35 µm vs 25 µm same drill/dT
    5.  higher_dT_more_current — 20 °C vs 10 °C same geometry
    6.  current_range_0p3mm — absolute range check: 1–2 A for 0.3 mm/25 µm/10 °C
    7.  current_range_0p5mm — absolute range check: 2–4 A for 0.5 mm/25 µm/10 °C
    8.  equiv_trace_width_positive — reported equivalent trace width > 0 and < 5 mm
    9.  equiv_trace_width_scales_with_drill — larger drill → wider equiv trace
   10.  recommended_vias_no_target — no target current → n_vias = 1
   11.  recommended_vias_target_5A — 5 A target with ~1.8 A/via → 3 vias
   12.  recommended_vias_target_1A — 1 A target with ~1.8 A/via → 1 via (already sufficient)
   13.  recommended_vias_target_10A — 10 A target with ~1.8 A/via → 6 vias
   14.  recommended_vias_ceiling — n × per_via ≥ target_current always

  Validation / edge cases
   15.  zero_drill_raises — drill = 0 → ValueError
   16.  negative_plating_raises — plating = -1 → ValueError
   17.  zero_temp_rise_raises — dT = 0 → ValueError
   18.  zero_via_length_raises — via_length = 0 → ValueError
   19.  zero_pad_raises — copper_pad_size = 0 → ValueError

  Dataclass fields
   20.  report_fields_present — report has all required attributes
   21.  honest_caveat_nonempty — caveat string is nonempty
   22.  cross_section_reported_correctly — report.via_cross_section_um2 ≈ π·D·t

  LLM tool handler
   23.  tool_ok_basic — valid JSON args returns ok=True payload
   24.  tool_ok_with_target — tool with target_current_A returns n_vias ≥ 1
   25.  tool_bad_args_missing_required — missing drill_diameter_mm → error payload
   26.  tool_invalid_json — non-JSON bytes → error payload

Author: imranparuk
"""
from __future__ import annotations

import asyncio
import json
import math
import os
import sys
import types

# ── Ensure src/ is on path ────────────────────────────────────────────────────
_HERE = os.path.dirname(os.path.abspath(__file__))
_SRC = os.path.join(os.path.dirname(_HERE), "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

# ── Stub kerf_chat so _compat.py register() mirror-path doesn't explode ──────
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
sys.modules.setdefault("kerf_chat.tools.registry", _reg_stub)

import pytest

from kerf_electronics.pcb_via_current import (
    PcbViaSpec,
    PcbViaCurrentReport,
    compute_pcb_via_max_current,
    _barrel_cross_section_um2,
    _via_capacity_amps,
    _equiv_trace_width_mm,
)
from kerf_electronics.tools.pcb_via_current import (
    electronics_compute_pcb_via_current,
    TOOLS,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _spec(D=0.3, t=25.0, L=1.6, dT=10.0, pad=1.0):
    return PcbViaSpec(
        drill_diameter_mm=D,
        plating_thickness_um=t,
        via_length_mm=L,
        temp_rise_C=dT,
        copper_pad_size_mm=pad,
    )


def run_async(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


async def call_tool(**kwargs):
    result = await electronics_compute_pcb_via_current(None, json.dumps(kwargs).encode())
    return json.loads(result)


# ═══════════════════════════════════════════════════════════════════════════════
# 1. Physics / formula correctness
# ═══════════════════════════════════════════════════════════════════════════════

def test_cross_section_area_0p3mm():
    """A = π · 300 µm · 25 µm ≈ 23562 µm²."""
    A = _barrel_cross_section_um2(0.3, 25.0)
    expected = math.pi * 300.0 * 25.0
    assert abs(A - expected) < 0.01, f"Expected ≈{expected:.2f}, got {A:.2f}"
    # Range check: within 0.1% of analytic
    assert 23500 < A < 23600


def test_cross_section_area_0p5mm():
    """A = π · 500 µm · 25 µm ≈ 39270 µm²."""
    A = _barrel_cross_section_um2(0.5, 25.0)
    expected = math.pi * 500.0 * 25.0
    assert abs(A - expected) < 0.01
    assert 39200 < A < 39350


def test_larger_drill_more_current():
    """0.5 mm drill carries more current than 0.3 mm at same plating and ΔT."""
    r_small = compute_pcb_via_max_current(_spec(D=0.3))
    r_large = compute_pcb_via_max_current(_spec(D=0.5))
    assert r_large.max_current_A > r_small.max_current_A


def test_thicker_plating_more_current():
    """35 µm plating carries more current than 25 µm at same drill and ΔT."""
    r_thin = compute_pcb_via_max_current(_spec(t=25.0))
    r_thick = compute_pcb_via_max_current(_spec(t=35.0))
    assert r_thick.max_current_A > r_thin.max_current_A


def test_higher_dT_more_current():
    """ΔT = 20 °C allows more current than ΔT = 10 °C."""
    r_10 = compute_pcb_via_max_current(_spec(dT=10.0))
    r_20 = compute_pcb_via_max_current(_spec(dT=20.0))
    assert r_20.max_current_A > r_10.max_current_A


def test_current_range_0p3mm():
    """0.3 mm drill, 25 µm plating, 10 °C: expect 1–3 A."""
    r = compute_pcb_via_max_current(_spec(D=0.3, t=25.0, dT=10.0))
    assert 1.0 <= r.max_current_A <= 3.0, (
        f"Expected 1–3 A, got {r.max_current_A:.4f} A"
    )


def test_current_range_0p5mm():
    """0.5 mm drill, 25 µm plating, 10 °C: expect 2–4 A."""
    r = compute_pcb_via_max_current(_spec(D=0.5, t=25.0, dT=10.0))
    assert 2.0 <= r.max_current_A <= 4.0, (
        f"Expected 2–4 A, got {r.max_current_A:.4f} A"
    )


def test_equiv_trace_width_positive():
    """Equivalent trace width is positive and physically reasonable (< 5 mm)."""
    r = compute_pcb_via_max_current(_spec())
    assert r.equivalent_trace_width_mm > 0
    assert r.equivalent_trace_width_mm < 5.0


def test_equiv_trace_width_scales_with_drill():
    """Larger drill → wider equivalent 1 oz trace width."""
    r_small = compute_pcb_via_max_current(_spec(D=0.3))
    r_large = compute_pcb_via_max_current(_spec(D=0.5))
    assert r_large.equivalent_trace_width_mm > r_small.equivalent_trace_width_mm


def test_recommended_vias_no_target():
    """No target current → n_vias = 1."""
    r = compute_pcb_via_max_current(_spec(), target_current_A=None)
    assert r.recommended_via_count_for_target_current == 1


def test_recommended_vias_target_5A():
    """5 A target with ~1.8 A per 0.3mm/25µm/10°C via → ceil(5/1.8) = 3 vias."""
    r = compute_pcb_via_max_current(_spec(D=0.3, t=25.0, dT=10.0), target_current_A=5.0)
    # I_per_via ≈ 1.795 → ceil(5/1.795) = 3
    assert r.recommended_via_count_for_target_current == 3


def test_recommended_vias_target_1A():
    """1 A target, ~1.8 A capacity → 1 via sufficient."""
    r = compute_pcb_via_max_current(_spec(D=0.3, t=25.0, dT=10.0), target_current_A=1.0)
    assert r.recommended_via_count_for_target_current == 1


def test_recommended_vias_target_10A():
    """10 A target with ~1.8 A/via → ceil(10/1.795) = 6 vias."""
    r = compute_pcb_via_max_current(_spec(D=0.3, t=25.0, dT=10.0), target_current_A=10.0)
    # ceil(10 / 1.795) = ceil(5.57) = 6
    assert r.recommended_via_count_for_target_current == 6


def test_recommended_vias_ceiling():
    """n_vias × I_per_via ≥ target_current always."""
    for target in [0.5, 1.0, 2.0, 3.7, 5.0, 7.5, 12.0]:
        r = compute_pcb_via_max_current(_spec(), target_current_A=target)
        n = r.recommended_via_count_for_target_current
        assert n * r.max_current_A >= target, (
            f"target={target}, n={n}, per_via={r.max_current_A:.4f}: "
            f"n×I = {n*r.max_current_A:.4f} < target"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# 2. Validation / edge cases
# ═══════════════════════════════════════════════════════════════════════════════

def test_zero_drill_raises():
    with pytest.raises(ValueError, match="drill_diameter_mm"):
        compute_pcb_via_max_current(_spec(D=0.0))


def test_negative_plating_raises():
    with pytest.raises(ValueError, match="plating_thickness_um"):
        compute_pcb_via_max_current(_spec(t=-1.0))


def test_zero_temp_rise_raises():
    with pytest.raises(ValueError, match="temp_rise_C"):
        compute_pcb_via_max_current(_spec(dT=0.0))


def test_zero_via_length_raises():
    with pytest.raises(ValueError, match="via_length_mm"):
        compute_pcb_via_max_current(_spec(L=0.0))


def test_zero_pad_raises():
    with pytest.raises(ValueError, match="copper_pad_size_mm"):
        compute_pcb_via_max_current(_spec(pad=0.0))


# ═══════════════════════════════════════════════════════════════════════════════
# 3. Dataclass fields
# ═══════════════════════════════════════════════════════════════════════════════

def test_report_fields_present():
    """PcbViaCurrentReport has all required attributes with correct types."""
    r = compute_pcb_via_max_current(_spec())
    assert isinstance(r, PcbViaCurrentReport)
    assert isinstance(r.max_current_A, float)
    assert isinstance(r.via_cross_section_um2, float)
    assert isinstance(r.equivalent_trace_width_mm, float)
    assert isinstance(r.recommended_via_count_for_target_current, int)
    assert isinstance(r.honest_caveat, str)


def test_honest_caveat_nonempty():
    r = compute_pcb_via_max_current(_spec())
    assert len(r.honest_caveat) > 50


def test_cross_section_reported_correctly():
    """Report.via_cross_section_um2 matches analytic π·D·t."""
    r = compute_pcb_via_max_current(_spec(D=0.3, t=25.0))
    expected = math.pi * 300.0 * 25.0
    assert abs(r.via_cross_section_um2 - expected) < 0.1, (
        f"Expected {expected:.2f}, reported {r.via_cross_section_um2}"
    )


# ═══════════════════════════════════════════════════════════════════════════════
# 4. LLM tool handler
# ═══════════════════════════════════════════════════════════════════════════════

def test_tool_ok_basic():
    """Valid args → ok=True with required keys."""
    result = run_async(call_tool(
        drill_diameter_mm=0.3,
        plating_thickness_um=25.0,
        via_length_mm=1.6,
        temp_rise_C=10.0,
    ))
    assert result.get("ok") is True
    assert "max_current_A" in result
    assert "via_cross_section_um2" in result
    assert "equivalent_trace_width_mm" in result
    assert "recommended_via_count_for_target_current" in result
    assert "honest_caveat" in result
    assert result["max_current_A"] > 0


def test_tool_ok_with_target():
    """Tool with target_current_A returns recommended_via_count ≥ 1."""
    result = run_async(call_tool(
        drill_diameter_mm=0.5,
        plating_thickness_um=25.0,
        via_length_mm=1.6,
        temp_rise_C=10.0,
        target_current_A=5.0,
    ))
    assert result.get("ok") is True
    n = result["recommended_via_count_for_target_current"]
    assert n >= 1
    assert n * result["max_current_A"] >= 5.0


def test_tool_bad_args_missing_required():
    """Missing drill_diameter_mm → error payload (ok absent or code BAD_ARGS)."""
    result = run_async(call_tool(
        plating_thickness_um=25.0,
        via_length_mm=1.6,
    ))
    assert result.get("ok") is not True
    assert "error" in result or result.get("code") == "BAD_ARGS"


def test_tool_invalid_json():
    """Non-JSON bytes → error payload."""
    async def _call():
        raw = await electronics_compute_pcb_via_current(None, b"not-json{{{")
        return json.loads(raw)
    result = run_async(_call())
    assert result.get("ok") is not True
    assert "error" in result


def test_tools_list_exports_one_entry():
    """TOOLS list must export exactly 1 entry for this module."""
    assert len(TOOLS) == 1
    name, spec, handler = TOOLS[0]
    assert name == "electronics_compute_pcb_via_current"
    assert callable(handler)
