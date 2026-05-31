"""
Hermetic tests for kerf_electronics.crystal_load_cap.

Pierce oscillator external load capacitor calculator.

Formula:  CL = (C1·C2)/(C1+C2) + C_stray     (NXP AN-2867 §3)
Symmetric: C1 = C2 = 2·(CL − C_stray)

Hand-calc reference
-------------------

C_stray defaults: pcb_stray=2.0 pF + mcu_pad=1.0 pF = 3.0 pF total

T01 — 16 MHz crystal, CL=20 pF, custom stray=2 pF (pcb=1+mcu=1):
    C_stray = 1 + 1 = 2 pF
    C1 = C2 = 2·(20 − 2) = 36 pF
    CL_eff  = (36·36)/(36+36) + 2 = 18 + 2 = 20 pF ✓

T02 — CL=8 pF, stray=2 pF (pcb=1+mcu=1):
    C1 = C2 = 2·(8 − 2) = 12 pF
    CL_eff = (12·12)/(12+12) + 2 = 6 + 2 = 8 pF ✓

T03 — CL=12 pF, stray=3 pF (default: pcb=2+mcu=1):
    C1 = C2 = 2·(12 − 3) = 18 pF
    CL_eff = (18·18)/(18+18) + 3 = 9 + 3 = 12 pF ✓

T04 — CL=20 pF, stray=3 pF (default):
    C1 = C2 = 2·(20 − 3) = 34 pF

T05 — Different CL (18 pF vs 12 pF) → different recommendation

T06 — Asymmetric override: verify effective CL

T07 — LLM tool handler happy path: 16 MHz, CL=20 pF, stray=2 pF → C1=C2=36 pF

T08 — LLM tool handler: CL=8 pF, stray=2 pF → C1=C2=12 pF

T09 — LLM tool handler bad args (missing load_capacitance_CL_pF)

T10 — LLM tool handler malformed JSON

T11 — CL ≤ C_stray raises ValueError

T12 — Negative frequency raises ValueError

T13 — Dict wrapper returns ok=False for invalid input

T14 — Report dataclass fields are all present and correctly typed

T15 — effective_load_cap matches formula exactly for symmetric case

T16 — Asymmetric C1 < C2 override: CL_eff computed correctly

T17 — High-frequency crystal (>20 MHz) note appears in caveat

T18 — Zero stray allowed (corner case — very clean board)

T19 — CL=6 pF (small, common for 32.768 kHz XTAL or low-cap MCUs)

T20 — Gain margin check present and non-empty

T21 — Dict wrapper round-trip matches direct call

T22 — Zero mcu_pad_capacitance_pF allowed (MCU with negligible pad cap)

Covers ≥ 12 tests required.
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

from kerf_electronics.crystal_load_cap import (
    CrystalSpec,
    PCBLayoutSpec,
    CrystalLoadCapReport,
    compute_crystal_load_caps,
    compute_crystal_load_caps_from_dict,
    electronics_compute_crystal_load_caps,
)


# ── Helpers ──────────────────────────────────────────────────────────────────

def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


class _FakeCtx:
    pass


def _make_crystal(
    freq_MHz: float = 16.0,
    CL_pF: float = 20.0,
    esr_ohms: float = 100.0,
    drive_uW: float = 50.0,
) -> CrystalSpec:
    return CrystalSpec(
        frequency_MHz=freq_MHz,
        load_capacitance_CL_pF=CL_pF,
        esr_max_ohms=esr_ohms,
        drive_level_uW=drive_uW,
    )


def _make_pcb(stray_pF: float = 1.0, pad_pF: float = 1.0) -> PCBLayoutSpec:
    """Default: stray=1 + pad=1 = 2 pF total."""
    return PCBLayoutSpec(pcb_stray_capacitance_pF=stray_pF, mcu_pad_capacitance_pF=pad_pF)


# ── T01 — 16 MHz, CL=20 pF, stray=2 pF: C1=C2=36 pF ────────────────────────

def test_t01_16mhz_cl20_stray2():
    crystal = _make_crystal(freq_MHz=16.0, CL_pF=20.0)
    pcb = _make_pcb(stray_pF=1.0, pad_pF=1.0)  # total stray = 2 pF
    report = compute_crystal_load_caps(crystal, pcb)

    # C1 = C2 = 2*(20-2) = 36 pF
    assert math.isclose(report.C1_pF, 36.0, rel_tol=1e-9)
    assert math.isclose(report.C2_pF, 36.0, rel_tol=1e-9)
    assert report.c1_c2_symmetric is True
    # effective CL = 36*36/(36+36) + 2 = 18 + 2 = 20 pF
    assert math.isclose(report.effective_load_cap_pF, 20.0, rel_tol=1e-9)


# ── T02 — CL=8 pF, stray=2 pF: C1=C2=12 pF ─────────────────────────────────

def test_t02_cl8_stray2():
    crystal = _make_crystal(freq_MHz=8.0, CL_pF=8.0)
    pcb = _make_pcb(stray_pF=1.0, pad_pF=1.0)  # total = 2 pF
    report = compute_crystal_load_caps(crystal, pcb)

    # C1 = C2 = 2*(8-2) = 12 pF
    assert math.isclose(report.C1_pF, 12.0, rel_tol=1e-9)
    assert math.isclose(report.C2_pF, 12.0, rel_tol=1e-9)
    assert report.c1_c2_symmetric is True
    # effective CL = 12*12/(12+12) + 2 = 6 + 2 = 8 pF
    assert math.isclose(report.effective_load_cap_pF, 8.0, rel_tol=1e-9)


# ── T03 — CL=12 pF, default stray=3 pF → C1=C2=18 pF ───────────────────────

def test_t03_cl12_default_stray():
    crystal = _make_crystal(freq_MHz=16.0, CL_pF=12.0)
    # Default PCBLayoutSpec: pcb=2.0 + mcu=1.0 = 3.0 pF
    report = compute_crystal_load_caps(crystal)

    # C1 = C2 = 2*(12-3) = 18 pF
    assert math.isclose(report.C1_pF, 18.0, rel_tol=1e-9)
    assert math.isclose(report.C2_pF, 18.0, rel_tol=1e-9)
    assert report.c1_c2_symmetric is True
    assert math.isclose(report.effective_load_cap_pF, 12.0, rel_tol=1e-9)


# ── T04 — CL=20 pF, default stray=3 pF → C1=C2=34 pF ───────────────────────

def test_t04_cl20_default_stray():
    crystal = _make_crystal(freq_MHz=16.0, CL_pF=20.0)
    report = compute_crystal_load_caps(crystal)

    # C1 = C2 = 2*(20-3) = 34 pF
    assert math.isclose(report.C1_pF, 34.0, rel_tol=1e-9)
    assert math.isclose(report.C2_pF, 34.0, rel_tol=1e-9)
    assert math.isclose(report.effective_load_cap_pF, 20.0, rel_tol=1e-9)


# ── T05 — Different CL (18 pF vs 12 pF) produces different recommendations ──

def test_t05_different_cl_different_recommendation():
    pcb = _make_pcb(stray_pF=1.0, pad_pF=1.0)  # 2 pF total
    report_12 = compute_crystal_load_caps(_make_crystal(CL_pF=12.0), pcb)
    report_18 = compute_crystal_load_caps(_make_crystal(CL_pF=18.0), pcb)

    # CL=12 → C1 = 2*(12-2) = 20 pF
    assert math.isclose(report_12.C1_pF, 20.0, rel_tol=1e-9)
    # CL=18 → C1 = 2*(18-2) = 32 pF
    assert math.isclose(report_18.C1_pF, 32.0, rel_tol=1e-9)
    # They must be different
    assert not math.isclose(report_12.C1_pF, report_18.C1_pF)


# ── T06 — Asymmetric override: effective CL back-computed correctly ──────────

def test_t06_asymmetric_override():
    crystal = _make_crystal(freq_MHz=16.0, CL_pF=12.0)
    pcb = _make_pcb(stray_pF=1.0, pad_pF=1.0)  # 2 pF stray

    # Use C1=15 pF, C2=27 pF (asymmetric)
    # Series: 15*27/(15+27) = 405/42 = 9.6428... pF
    # CL_eff = 9.6428... + 2 = 11.6428... pF
    report = compute_crystal_load_caps(crystal, pcb, c1_override_pF=15.0, c2_override_pF=27.0)

    c_series = (15.0 * 27.0) / (15.0 + 27.0)
    expected_cl = c_series + 2.0
    # effective_load_cap_pF is rounded to 6 decimal places in the report
    assert math.isclose(report.effective_load_cap_pF, expected_cl, rel_tol=1e-5)
    assert report.c1_c2_symmetric is False
    assert math.isclose(report.C1_pF, 15.0, rel_tol=1e-9)
    assert math.isclose(report.C2_pF, 27.0, rel_tol=1e-9)


# ── T07 — LLM tool handler: 16 MHz, CL=20 pF, stray=2 pF → C1=C2=36 pF ─────

def test_t07_llm_tool_16mhz_cl20_stray2():
    args = json.dumps({
        "frequency_MHz": 16.0,
        "load_capacitance_CL_pF": 20.0,
        "esr_max_ohms": 100.0,
        "drive_level_uW": 50.0,
        "pcb": {
            "pcb_stray_capacitance_pF": 1.0,
            "mcu_pad_capacitance_pF": 1.0,
        },
    }).encode()
    result = json.loads(_run(electronics_compute_crystal_load_caps(_FakeCtx(), args)))
    assert result.get("ok") is True
    assert math.isclose(result["C1_pF"], 36.0, rel_tol=1e-9)
    assert math.isclose(result["C2_pF"], 36.0, rel_tol=1e-9)
    assert result["c1_c2_symmetric"] is True
    assert math.isclose(result["effective_load_cap_pF"], 20.0, rel_tol=1e-9)


# ── T08 — LLM tool handler: CL=8 pF, stray=2 pF → C1=C2=12 pF ──────────────

def test_t08_llm_tool_cl8_stray2():
    args = json.dumps({
        "frequency_MHz": 8.0,
        "load_capacitance_CL_pF": 8.0,
        "esr_max_ohms": 150.0,
        "drive_level_uW": 100.0,
        "pcb": {
            "pcb_stray_capacitance_pF": 1.0,
            "mcu_pad_capacitance_pF": 1.0,
        },
    }).encode()
    result = json.loads(_run(electronics_compute_crystal_load_caps(_FakeCtx(), args)))
    assert result.get("ok") is True
    assert math.isclose(result["C1_pF"], 12.0, rel_tol=1e-9)
    assert math.isclose(result["C2_pF"], 12.0, rel_tol=1e-9)
    assert math.isclose(result["effective_load_cap_pF"], 8.0, rel_tol=1e-9)


# ── T09 — LLM tool handler bad args: missing load_capacitance_CL_pF ─────────

def test_t09_llm_tool_missing_cl():
    args = json.dumps({
        "frequency_MHz": 16.0,
        # load_capacitance_CL_pF deliberately omitted
        "esr_max_ohms": 100.0,
        "drive_level_uW": 50.0,
    }).encode()
    result = json.loads(_run(electronics_compute_crystal_load_caps(_FakeCtx(), args)))
    assert result.get("ok") is not True
    assert "error" in result or "reason" in result


# ── T10 — LLM tool handler malformed JSON ────────────────────────────────────

def test_t10_llm_tool_malformed_json():
    args = b"not valid json {"
    result = json.loads(_run(electronics_compute_crystal_load_caps(_FakeCtx(), args)))
    assert result.get("ok") is not True


# ── T11 — CL ≤ C_stray raises ValueError ─────────────────────────────────────

def test_t11_cl_less_than_stray_raises():
    crystal = _make_crystal(CL_pF=3.0)
    # Default stray = 2 + 1 = 3 pF → CL == C_stray → should raise
    with pytest.raises(ValueError, match="stray"):
        compute_crystal_load_caps(crystal)


def test_t11b_cl_strictly_less_than_stray_raises():
    crystal = _make_crystal(CL_pF=2.0)
    pcb = PCBLayoutSpec(pcb_stray_capacitance_pF=2.0, mcu_pad_capacitance_pF=1.5)
    # Total stray = 3.5 pF > CL = 2.0 pF → must raise
    with pytest.raises(ValueError):
        compute_crystal_load_caps(crystal, pcb)


# ── T12 — Negative frequency raises ValueError ────────────────────────────────

def test_t12_negative_frequency_raises():
    crystal = CrystalSpec(
        frequency_MHz=-16.0,
        load_capacitance_CL_pF=20.0,
        esr_max_ohms=100.0,
        drive_level_uW=50.0,
    )
    with pytest.raises(ValueError, match="frequency_MHz"):
        compute_crystal_load_caps(crystal)


# ── T13 — Dict wrapper returns ok=False for invalid input ────────────────────

def test_t13_dict_wrapper_invalid():
    result = compute_crystal_load_caps_from_dict({
        "frequency_MHz": 16.0,
        # load_capacitance_CL_pF missing
        "esr_max_ohms": 100.0,
        "drive_level_uW": 50.0,
    })
    assert result["ok"] is False
    assert "reason" in result


# ── T14 — Report dataclass fields present and typed correctly ─────────────────

def test_t14_report_fields_typed():
    crystal = _make_crystal()
    pcb = _make_pcb()
    report = compute_crystal_load_caps(crystal, pcb)

    assert isinstance(report, CrystalLoadCapReport)
    assert isinstance(report.C1_pF, float)
    assert isinstance(report.C2_pF, float)
    assert isinstance(report.effective_load_cap_pF, float)
    assert isinstance(report.c1_c2_symmetric, bool)
    assert isinstance(report.gain_margin_check, str)
    assert len(report.gain_margin_check) > 10
    assert isinstance(report.honest_caveat, str)
    assert len(report.honest_caveat) > 30


# ── T15 — effective_load_cap exactly matches formula for symmetric case ───────

def test_t15_effective_cl_formula_symmetric():
    """For any valid (CL, C_stray), the round-trip CL_eff == CL_target."""
    for CL_pF, stray_pF in [(6.0, 1.0), (8.0, 2.0), (10.0, 2.0), (12.0, 3.0),
                             (18.0, 3.0), (20.0, 3.0), (20.0, 2.0)]:
        crystal = _make_crystal(CL_pF=CL_pF)
        pcb_total_stray = stray_pF
        pcb = PCBLayoutSpec(pcb_stray_capacitance_pF=stray_pF, mcu_pad_capacitance_pF=0.0)
        report = compute_crystal_load_caps(crystal, pcb)
        assert math.isclose(report.effective_load_cap_pF, CL_pF, rel_tol=1e-9), (
            f"CL={CL_pF} stray={stray_pF}: got {report.effective_load_cap_pF}"
        )


# ── T16 — Asymmetric C1 < C2: CL_eff computed correctly ─────────────────────

def test_t16_asymmetric_c1_less_c2():
    crystal = _make_crystal(freq_MHz=10.0, CL_pF=15.0)
    pcb = _make_pcb(stray_pF=2.0, pad_pF=0.5)  # 2.5 pF stray

    # Provide arbitrary asymmetric C1=20 pF, C2=30 pF
    report = compute_crystal_load_caps(crystal, pcb, c1_override_pF=20.0, c2_override_pF=30.0)

    c_series = (20.0 * 30.0) / (20.0 + 30.0)  # 12.0 pF
    expected_cl = c_series + 2.5               # 14.5 pF
    assert math.isclose(report.effective_load_cap_pF, expected_cl, rel_tol=1e-9)
    assert report.c1_c2_symmetric is False


# ── T17 — High-frequency crystal (>20 MHz) note in caveat/gain_margin ────────

def test_t17_high_frequency_caveat():
    crystal = _make_crystal(freq_MHz=25.0, CL_pF=18.0)
    report = compute_crystal_load_caps(crystal)

    # Should flag high-frequency in caveat
    assert "20 MHz" in report.honest_caveat or "PI-network" in report.honest_caveat


# ── T18 — Zero mcu_pad results in correct stray calculation ──────────────────

def test_t18_zero_mcu_pad_capacitance():
    crystal = _make_crystal(CL_pF=12.0)
    pcb = PCBLayoutSpec(pcb_stray_capacitance_pF=2.0, mcu_pad_capacitance_pF=0.0)
    report = compute_crystal_load_caps(crystal, pcb)

    # C_stray = 2.0, C1 = C2 = 2*(12-2) = 20 pF
    assert math.isclose(report.C1_pF, 20.0, rel_tol=1e-9)
    assert math.isclose(report.effective_load_cap_pF, 12.0, rel_tol=1e-9)


# ── T19 — CL=6 pF (small, common for 32.768 kHz XTAL or low-cap MCUs) ───────

def test_t19_small_cl_6pf():
    crystal = _make_crystal(freq_MHz=0.032768, CL_pF=6.0, esr_ohms=35000.0, drive_uW=1.0)
    pcb = PCBLayoutSpec(pcb_stray_capacitance_pF=1.0, mcu_pad_capacitance_pF=1.0)
    report = compute_crystal_load_caps(crystal, pcb)

    # C1 = C2 = 2*(6-2) = 8 pF
    assert math.isclose(report.C1_pF, 8.0, rel_tol=1e-9)
    assert math.isclose(report.effective_load_cap_pF, 6.0, rel_tol=1e-9)


# ── T20 — Gain margin check present and non-empty ────────────────────────────

def test_t20_gain_margin_check_present():
    crystal = _make_crystal()
    report = compute_crystal_load_caps(crystal)
    assert report.gain_margin_check
    # Should mention either ESR or margin
    assert "ESR" in report.gain_margin_check or "margin" in report.gain_margin_check.lower()


# ── T21 — Dict wrapper round-trip matches direct call ────────────────────────

def test_t21_dict_wrapper_round_trip():
    direct = compute_crystal_load_caps(
        CrystalSpec(
            frequency_MHz=12.0,
            load_capacitance_CL_pF=16.0,
            esr_max_ohms=80.0,
            drive_level_uW=25.0,
        ),
        PCBLayoutSpec(pcb_stray_capacitance_pF=1.5, mcu_pad_capacitance_pF=0.5),
    )
    via_dict = compute_crystal_load_caps_from_dict({
        "frequency_MHz": 12.0,
        "load_capacitance_CL_pF": 16.0,
        "esr_max_ohms": 80.0,
        "drive_level_uW": 25.0,
        "pcb": {
            "pcb_stray_capacitance_pF": 1.5,
            "mcu_pad_capacitance_pF": 0.5,
        },
    })
    assert via_dict["ok"] is True
    assert math.isclose(via_dict["C1_pF"], direct.C1_pF, rel_tol=1e-9)
    assert math.isclose(via_dict["C2_pF"], direct.C2_pF, rel_tol=1e-9)
    assert math.isclose(via_dict["effective_load_cap_pF"], direct.effective_load_cap_pF, rel_tol=1e-9)
    assert via_dict["c1_c2_symmetric"] == direct.c1_c2_symmetric


# ── T22 — Zero stray capacitance (corner case — very clean board) ─────────────

def test_t22_zero_stray_capacitance():
    crystal = _make_crystal(CL_pF=10.0)
    pcb = PCBLayoutSpec(pcb_stray_capacitance_pF=0.0, mcu_pad_capacitance_pF=0.0)
    report = compute_crystal_load_caps(crystal, pcb)

    # C1 = C2 = 2*(10-0) = 20 pF
    assert math.isclose(report.C1_pF, 20.0, rel_tol=1e-9)
    assert math.isclose(report.effective_load_cap_pF, 10.0, rel_tol=1e-9)


# ── T23 — esr_max_ohms validation ────────────────────────────────────────────

def test_t23_zero_esr_raises():
    crystal = CrystalSpec(
        frequency_MHz=16.0,
        load_capacitance_CL_pF=20.0,
        esr_max_ohms=0.0,
        drive_level_uW=50.0,
    )
    with pytest.raises(ValueError, match="esr_max_ohms"):
        compute_crystal_load_caps(crystal)


# ── T24 — Negative stray capacitance raises ValueError ───────────────────────

def test_t24_negative_stray_raises():
    crystal = _make_crystal()
    pcb = PCBLayoutSpec(pcb_stray_capacitance_pF=-1.0, mcu_pad_capacitance_pF=1.0)
    with pytest.raises(ValueError, match="pcb_stray"):
        compute_crystal_load_caps(crystal, pcb)
