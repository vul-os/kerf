"""
Hermetic tests for kerf_electronics.diffpair_skew_check.

Intra-pair length-matching skew (mm and ps) for PCB differential pairs.

Hand-calc reference
-------------------
c = 0.3 mm/ps  (speed of light in free space)
v = c / √εr

FR4 (εr = 4.5):   v = 0.3 / √4.5 = 0.3 / 2.12132 ≈ 0.14142 mm/ps
Air (εr = 1.0):   v = 0.3 / √1.0 = 0.3 mm/ps

50 mm / 52 mm, FR4:
  Δl = 2 mm
  Δt = 2 / 0.14142 ≈ 14.142 ps
  → USB 3.0 (20 ps): 14.14 ps < 20 ps  → COMPLIANT
  → PCIe 4.0 (2 ps): 14.14 ps > 2 ps   → NOT COMPLIANT
  → HDMI 2.1 (15 ps): 14.14 ps < 15 ps → COMPLIANT
  → DDR5 (5 ps): 14.14 ps > 5 ps       → NOT COMPLIANT
  → SATA III (15 ps): 14.14 ps < 15 ps → COMPLIANT

Recommended ΔL_max for USB 3.0 / FR4:
  ΔL_max = 20 ps × 0.14142 mm/ps = 2.8284 mm

Equal lengths:
  Δl = 0 → Δt = 0 ps → always compliant for any protocol

Custom 10 ps budget, FR4, Δl=1 mm:
  Δt = 1 / 0.14142 ≈ 7.071 ps < 10 ps → COMPLIANT

Custom 5 ps budget, FR4, Δl=1 mm:
  Δt ≈ 7.071 ps > 5 ps → NOT COMPLIANT

Covers ≥ 12 tests:
  T01  50/52 mm FR4 USB 3.0  → Δ=2 mm → ~14.1 ps < 20 ps  → PASS
  T02  50/52 mm FR4 PCIe 4.0 → ~14.1 ps > 2 ps             → FAIL
  T03  Equal lengths, any protocol                           → Δt=0, PASS
  T04  Air (εr=1) propagates faster than FR4                → v_air > v_FR4
  T05  Custom protocol with budget > skew                    → PASS
  T06  Custom protocol with budget < skew                    → FAIL
  T07  50/52 mm FR4 HDMI 2.1 → ~14.1 ps < 15 ps            → PASS
  T08  50/52 mm FR4 DDR5     → ~14.1 ps > 5 ps             → FAIL
  T09  50/52 mm FR4 SATA III → ~14.1 ps < 15 ps            → PASS
  T10  recommended_max_length_mismatch_mm is budget_ps × v
  T11  propagation_velocity correctly computed for Rogers-like εr
  T12  LLM tool handler happy path (USB 3.0, FR4, PASS)
  T13  LLM tool handler happy path (PCIe 4.0, FR4, FAIL)
  T14  LLM tool handler bad args (missing pos_length_mm)
  T15  LLM tool handler malformed JSON
  T16  Invalid protocol raises ValueError
  T17  Negative length raises ValueError
  T18  Zero εr raises ValueError
  T19  custom protocol without budget raises ValueError
  T20  Dict wrapper returns ok=False on invalid input
  T21  report fields all present and typed correctly
  T22  time_skew_ps round-trip via dict wrapper matches direct call
"""
from __future__ import annotations

import asyncio
import json
import math
import os
import sys
import types

# ── Stub kerf_chat if not installed ─────────────────────────────────────────
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
if _kc_real is None:
    sys.modules["kerf_chat.tools.registry"] = _reg_stub

# ── Ensure src/ is on sys.path ───────────────────────────────────────────────
_HERE = os.path.dirname(os.path.abspath(__file__))
_SRC = os.path.join(os.path.dirname(_HERE), "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

import pytest

from kerf_electronics.diffpair_skew_check import (
    DiffPairSpec,
    DiffPairSkewReport,
    check_diffpair_skew,
    check_diffpair_skew_from_dict,
    _C_MM_PER_PS,
    _PROTOCOL_BUDGETS_PS,
    electronics_check_diffpair_skew,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _v_fr4() -> float:
    """Propagation velocity in FR4 (εr=4.5) in mm/ps."""
    return _C_MM_PER_PS / math.sqrt(4.5)


def _v(er: float) -> float:
    return _C_MM_PER_PS / math.sqrt(er)


def _run(coro):
    return asyncio.run(coro)


class _FakeCtx:
    pass


# ---------------------------------------------------------------------------
# T01 — 50/52 mm FR4, USB 3.0: ~14.1 ps < 20 ps → COMPLIANT
# ---------------------------------------------------------------------------

def test_t01_usb30_fr4_2mm_compliant():
    spec = DiffPairSpec(
        signal_name="USB_DP",
        pos_length_mm=50.0,
        neg_length_mm=52.0,
        dielectric_constant_er=4.5,
        protocol="usb_30",
    )
    report = check_diffpair_skew(spec)
    v = _v_fr4()
    expected_skew_ps = 2.0 / v
    assert math.isclose(report.length_skew_mm, 2.0, rel_tol=1e-6)
    assert math.isclose(report.time_skew_ps, expected_skew_ps, rel_tol=1e-4)
    assert report.skew_budget_ps == 20.0
    assert report.compliant is True


# ---------------------------------------------------------------------------
# T02 — same 50/52 mm FR4, PCIe 4.0: ~14.1 ps > 2 ps → NOT COMPLIANT
# ---------------------------------------------------------------------------

def test_t02_pcie40_fr4_2mm_noncompliant():
    spec = DiffPairSpec(
        signal_name="PCIE_TXP",
        pos_length_mm=50.0,
        neg_length_mm=52.0,
        dielectric_constant_er=4.5,
        protocol="pcie_40",
    )
    report = check_diffpair_skew(spec)
    assert report.skew_budget_ps == 2.0
    assert report.compliant is False
    # ~14.14 ps >> 2 ps
    assert report.time_skew_ps > 10.0


# ---------------------------------------------------------------------------
# T03 — Equal lengths: always compliant, Δt = 0
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("protocol", list(_PROTOCOL_BUDGETS_PS.keys()))
def test_t03_equal_lengths_always_compliant(protocol: str):
    spec = DiffPairSpec(
        signal_name="EQ_PAIR",
        pos_length_mm=75.0,
        neg_length_mm=75.0,
        dielectric_constant_er=4.5,
        protocol=protocol,
    )
    report = check_diffpair_skew(spec)
    assert report.length_skew_mm == 0.0
    assert report.time_skew_ps == 0.0
    assert report.compliant is True


# ---------------------------------------------------------------------------
# T04 — Air (εr=1) propagates faster than FR4 (εr=4.5)
# ---------------------------------------------------------------------------

def test_t04_air_faster_than_fr4():
    # Both with 2 mm mismatch — air substrate should have lower time skew
    spec_air = DiffPairSpec(
        signal_name="AIR_PAIR",
        pos_length_mm=50.0,
        neg_length_mm=52.0,
        dielectric_constant_er=1.0,
        protocol="usb_30",
    )
    spec_fr4 = DiffPairSpec(
        signal_name="FR4_PAIR",
        pos_length_mm=50.0,
        neg_length_mm=52.0,
        dielectric_constant_er=4.5,
        protocol="usb_30",
    )
    report_air = check_diffpair_skew(spec_air)
    report_fr4 = check_diffpair_skew(spec_fr4)

    # Air velocity = c = 0.3 mm/ps; FR4 velocity ≈ 0.1414 mm/ps
    assert report_air.propagation_velocity_mm_per_ps > report_fr4.propagation_velocity_mm_per_ps
    # Faster velocity → shorter time for same physical delta
    assert report_air.time_skew_ps < report_fr4.time_skew_ps
    # Air velocity should be exactly c = 0.3 mm/ps
    assert math.isclose(report_air.propagation_velocity_mm_per_ps, 0.3, rel_tol=1e-6)


# ---------------------------------------------------------------------------
# T05 — Custom protocol with generous budget: COMPLIANT
# ---------------------------------------------------------------------------

def test_t05_custom_protocol_pass():
    spec = DiffPairSpec(
        signal_name="CUSTOM_PAIR",
        pos_length_mm=50.0,
        neg_length_mm=51.0,
        dielectric_constant_er=4.5,
        protocol="custom",
        custom_skew_budget_ps=20.0,
    )
    report = check_diffpair_skew(spec)
    # Δl=1mm, Δt ≈ 7.07 ps < 20 ps
    assert report.skew_budget_ps == 20.0
    assert report.compliant is True
    assert math.isclose(report.time_skew_ps, 1.0 / _v_fr4(), rel_tol=1e-4)


# ---------------------------------------------------------------------------
# T06 — Custom protocol with tight budget: NOT COMPLIANT
# ---------------------------------------------------------------------------

def test_t06_custom_protocol_fail():
    spec = DiffPairSpec(
        signal_name="CUSTOM_TIGHT",
        pos_length_mm=50.0,
        neg_length_mm=51.0,
        dielectric_constant_er=4.5,
        protocol="custom",
        custom_skew_budget_ps=5.0,
    )
    report = check_diffpair_skew(spec)
    # Δl=1mm, Δt ≈ 7.07 ps > 5 ps
    assert report.skew_budget_ps == 5.0
    assert report.compliant is False


# ---------------------------------------------------------------------------
# T07 — 50/52 mm FR4 HDMI 2.1: ~14.14 ps < 15 ps → COMPLIANT
# ---------------------------------------------------------------------------

def test_t07_hdmi21_fr4_2mm_compliant():
    spec = DiffPairSpec(
        signal_name="HDMI_D0P",
        pos_length_mm=50.0,
        neg_length_mm=52.0,
        dielectric_constant_er=4.5,
        protocol="hdmi_21",
    )
    report = check_diffpair_skew(spec)
    assert report.skew_budget_ps == 15.0
    # Δt ≈ 14.14 ps < 15 ps
    assert report.time_skew_ps < 15.0
    assert report.compliant is True


# ---------------------------------------------------------------------------
# T08 — 50/52 mm FR4 DDR5: ~14.14 ps > 5 ps → NOT COMPLIANT
# ---------------------------------------------------------------------------

def test_t08_ddr5_fr4_2mm_noncompliant():
    spec = DiffPairSpec(
        signal_name="DDR5_DQS_P",
        pos_length_mm=50.0,
        neg_length_mm=52.0,
        dielectric_constant_er=4.5,
        protocol="ddr5",
    )
    report = check_diffpair_skew(spec)
    assert report.skew_budget_ps == 5.0
    assert report.compliant is False


# ---------------------------------------------------------------------------
# T09 — 50/52 mm FR4 SATA III: ~14.14 ps < 15 ps → COMPLIANT
# ---------------------------------------------------------------------------

def test_t09_sata3_fr4_2mm_compliant():
    spec = DiffPairSpec(
        signal_name="SATA_TXP",
        pos_length_mm=50.0,
        neg_length_mm=52.0,
        dielectric_constant_er=4.5,
        protocol="sata_iii",
    )
    report = check_diffpair_skew(spec)
    assert report.skew_budget_ps == 15.0
    assert report.compliant is True
    # Δt should be just below budget
    assert 13.0 < report.time_skew_ps < 15.0


# ---------------------------------------------------------------------------
# T10 — recommended_max_length_mismatch_mm = budget_ps × v
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("protocol,budget_ps", list(_PROTOCOL_BUDGETS_PS.items()))
def test_t10_recommended_max_mismatch_formula(protocol: str, budget_ps: float):
    spec = DiffPairSpec(
        signal_name="CHECK_PAIR",
        pos_length_mm=100.0,
        neg_length_mm=100.0,
        dielectric_constant_er=4.5,
        protocol=protocol,
    )
    report = check_diffpair_skew(spec)
    v = _v_fr4()
    expected = budget_ps * v
    assert math.isclose(
        report.recommended_max_length_mismatch_mm, expected, rel_tol=1e-5
    ), (
        f"{protocol}: expected {expected:.4f} mm, got "
        f"{report.recommended_max_length_mismatch_mm:.4f} mm"
    )


# ---------------------------------------------------------------------------
# T11 — Propagation velocity correct for Rogers-like εr=3.66
# ---------------------------------------------------------------------------

def test_t11_velocity_rogers_4350b():
    er = 3.66  # Rogers 4350B nominal
    spec = DiffPairSpec(
        signal_name="RF_PAIR",
        pos_length_mm=30.0,
        neg_length_mm=30.0,
        dielectric_constant_er=er,
        protocol="hdmi_21",
    )
    report = check_diffpair_skew(spec)
    expected_v = 0.3 / math.sqrt(er)
    assert math.isclose(report.propagation_velocity_mm_per_ps, expected_v, rel_tol=1e-5)


# ---------------------------------------------------------------------------
# T12 — LLM tool handler happy path, USB 3.0, FR4, PASS
# ---------------------------------------------------------------------------

def test_t12_llm_tool_usb30_fr4_pass():
    args = json.dumps({
        "signal_name": "USB_DP",
        "pos_length_mm": 50.0,
        "neg_length_mm": 52.0,
        "dielectric_constant_er": 4.5,
        "protocol": "usb_30",
    }).encode()
    result = json.loads(_run(electronics_check_diffpair_skew(_FakeCtx(), args)))
    assert result.get("ok") is True
    assert result["compliant"] is True
    assert result["skew_budget_ps"] == 20.0
    assert math.isclose(result["time_skew_ps"], 2.0 / _v_fr4(), rel_tol=1e-4)


# ---------------------------------------------------------------------------
# T13 — LLM tool handler happy path, PCIe 4.0, FR4, FAIL
# ---------------------------------------------------------------------------

def test_t13_llm_tool_pcie40_fr4_fail():
    args = json.dumps({
        "signal_name": "PCIE_TXP",
        "pos_length_mm": 50.0,
        "neg_length_mm": 52.0,
        "dielectric_constant_er": 4.5,
        "protocol": "pcie_40",
    }).encode()
    result = json.loads(_run(electronics_check_diffpair_skew(_FakeCtx(), args)))
    assert result.get("ok") is True
    assert result["compliant"] is False
    assert result["skew_budget_ps"] == 2.0


# ---------------------------------------------------------------------------
# T14 — LLM tool handler bad args (missing pos_length_mm)
# ---------------------------------------------------------------------------

def test_t14_llm_tool_missing_required_field():
    args = json.dumps({
        "signal_name": "BAD_PAIR",
        "neg_length_mm": 52.0,
    }).encode()
    result = json.loads(_run(electronics_check_diffpair_skew(_FakeCtx(), args)))
    # Should return an error payload
    assert result.get("ok") is not True
    assert "error" in result or "reason" in result


# ---------------------------------------------------------------------------
# T15 — LLM tool handler malformed JSON
# ---------------------------------------------------------------------------

def test_t15_llm_tool_malformed_json():
    args = b"not valid json {"
    result = json.loads(_run(electronics_check_diffpair_skew(_FakeCtx(), args)))
    assert result.get("ok") is not True


# ---------------------------------------------------------------------------
# T16 — Invalid protocol raises ValueError
# ---------------------------------------------------------------------------

def test_t16_invalid_protocol_raises():
    spec = DiffPairSpec(
        signal_name="BAD",
        pos_length_mm=50.0,
        neg_length_mm=52.0,
        protocol="ethernet_10g",  # not a valid protocol
    )
    with pytest.raises(ValueError, match="protocol"):
        check_diffpair_skew(spec)


# ---------------------------------------------------------------------------
# T17 — Negative trace length raises ValueError
# ---------------------------------------------------------------------------

def test_t17_negative_length_raises():
    spec = DiffPairSpec(
        signal_name="NEG",
        pos_length_mm=-1.0,
        neg_length_mm=50.0,
        protocol="usb_30",
    )
    with pytest.raises(ValueError, match="pos_length_mm"):
        check_diffpair_skew(spec)


# ---------------------------------------------------------------------------
# T18 — Zero dielectric constant raises ValueError
# ---------------------------------------------------------------------------

def test_t18_zero_er_raises():
    spec = DiffPairSpec(
        signal_name="ZERR",
        pos_length_mm=50.0,
        neg_length_mm=52.0,
        dielectric_constant_er=0.0,
        protocol="usb_30",
    )
    with pytest.raises(ValueError, match="dielectric_constant_er"):
        check_diffpair_skew(spec)


# ---------------------------------------------------------------------------
# T19 — custom protocol without budget raises ValueError
# ---------------------------------------------------------------------------

def test_t19_custom_without_budget_raises():
    spec = DiffPairSpec(
        signal_name="CUS",
        pos_length_mm=50.0,
        neg_length_mm=52.0,
        protocol="custom",
        custom_skew_budget_ps=None,
    )
    with pytest.raises(ValueError, match="custom_skew_budget_ps"):
        check_diffpair_skew(spec)


# ---------------------------------------------------------------------------
# T20 — dict wrapper returns ok=False on invalid input (missing key)
# ---------------------------------------------------------------------------

def test_t20_dict_wrapper_missing_key():
    result = check_diffpair_skew_from_dict({
        "signal_name": "MISSING",
        # pos_length_mm deliberately omitted
        "neg_length_mm": 52.0,
    })
    assert result["ok"] is False
    assert "reason" in result


# ---------------------------------------------------------------------------
# T21 — Report dataclass fields are all present and typed correctly
# ---------------------------------------------------------------------------

def test_t21_report_fields_typed():
    spec = DiffPairSpec(
        signal_name="FIELD_CHECK",
        pos_length_mm=60.0,
        neg_length_mm=61.5,
        dielectric_constant_er=4.5,
        protocol="usb_30",
    )
    report = check_diffpair_skew(spec)
    assert isinstance(report, DiffPairSkewReport)
    assert isinstance(report.length_skew_mm, float)
    assert isinstance(report.time_skew_ps, float)
    assert isinstance(report.skew_budget_ps, float)
    assert isinstance(report.compliant, bool)
    assert isinstance(report.recommended_max_length_mismatch_mm, float)
    assert isinstance(report.propagation_velocity_mm_per_ps, float)
    assert isinstance(report.honest_caveat, str)
    assert len(report.honest_caveat) > 20


# ---------------------------------------------------------------------------
# T22 — time_skew_ps round-trip: dict wrapper matches direct call
# ---------------------------------------------------------------------------

def test_t22_dict_wrapper_matches_direct():
    direct = check_diffpair_skew(
        DiffPairSpec(
            signal_name="ROUND_TRIP",
            pos_length_mm=55.0,
            neg_length_mm=57.3,
            dielectric_constant_er=4.2,
            protocol="hdmi_21",
        )
    )
    via_dict = check_diffpair_skew_from_dict({
        "signal_name": "ROUND_TRIP",
        "pos_length_mm": 55.0,
        "neg_length_mm": 57.3,
        "dielectric_constant_er": 4.2,
        "protocol": "hdmi_21",
    })
    assert via_dict["ok"] is True
    assert math.isclose(via_dict["time_skew_ps"], direct.time_skew_ps, rel_tol=1e-9)
    assert math.isclose(
        via_dict["recommended_max_length_mismatch_mm"],
        direct.recommended_max_length_mismatch_mm,
        rel_tol=1e-9,
    )
    assert via_dict["compliant"] == direct.compliant
