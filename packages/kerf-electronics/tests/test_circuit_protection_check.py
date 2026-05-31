"""
Hermetic tests for kerf_electronics.circuit_protection_check.

NEC 2023 Article 240.4 + Table 310.16 + Article 215 compliance.

Hand-calc reference:
  NEC 215.3 / 210.20(A): required_ocpd_min = 1.25 × I_continuous + I_non_continuous
  NEC 240.4(B): OCPD rating ≤ conductor ampacity (75°C column)
  NEC 240.4(D): 14 AWG Cu → max 15 A; 12 AWG Cu → max 20 A; 10 AWG Cu → max 30 A
  NEC Table 310.16 75°C copper: 14=20A, 12=25A, 10=35A, 8=50A, 6=65A, 4=85A, ...
  Aluminum ≈ 78% of copper (exact values from NEC Table 310.16 Al column).

Covers ≥ 14 tests:
  T01  12 AWG Cu THWN, 16A continuous, 0A non-cont, 20A breaker → required=20A; PASS
  T02  12 AWG Cu, 20A continuous, 0A non-cont, 20A breaker → required=25A; FAIL (too small)
  T03  6 AWG Cu, 60A continuous (pure), 70A breaker → ampacity=65A; breaker>ampacity; FAIL
  T04  Al 4 AWG, 60A continuous, 75A breaker → ampacity=65A (Al); OCPD>ampacity; FAIL
  T05  14 AWG Cu, 15A breaker (240.4(D) small-conductor rule) → PASS
  T06  14 AWG Cu, 20A breaker → exceeds 240.4(D) cap of 15A → FAIL
  T07  12 AWG Cu, 20A breaker exactly at 240.4(D) cap → PASS
  T08  10 AWG Cu, 30A breaker exactly at 240.4(D) cap → PASS
  T09  10 AWG Cu, 35A breaker → exceeds 240.4(D) cap of 30A → FAIL
  T10  8 AWG Cu, 40A continuous, 50A breaker → required=50A; breaker=ampacity=50A; PASS
  T11  1/0 AWG Cu, 100A continuous, 150A breaker → required=125A; breaker=ampacity=150A; PASS
  T12  4/0 AWG Cu, 200A continuous, 230A breaker → required=250A > ampacity=230A; conductor_adequate=False
  T13  Report fields all present and typed correctly
  T14  Invalid AWG raises ValueError
  T15  Invalid material raises ValueError
  T16  Negative continuous current raises ValueError
  T17  Invalid insulation raises ValueError
  T18  LLM tool handler happy path
  T19  LLM tool handler bad args (invalid AWG)
  T20  LLM tool handler malformed JSON
  T21  Aluminum 12 AWG, 15A continuous, 20A breaker → Al ampacity=20A; required=18.75A; PASS
  T22  Non-continuous-only load (0 continuous) — required = 1.25×0 + non_cont
  T23  Mixed continuous + non-continuous → required = 1.25*cont + non_cont
  T24  code_section_cited includes 240.4(D) for small conductors, not for large
  T25  honest_caveat always mentions derating
"""
from __future__ import annotations

import json
import math
import pytest

from kerf_electronics.circuit_protection_check import (
    ConductorSpec,
    LoadSpec,
    OcpdSpec,
    CircuitProtectionReport,
    check_circuit_protection,
    _TABLE_310_16_75C,
    _SMALL_CONDUCTOR_MAX_OCPD_CU,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _conductor(awg: str, material: str = "copper", insulation: str = "THWN") -> ConductorSpec:
    return ConductorSpec(awg_size=awg, material=material, insulation_class=insulation)


def _load(cont: float, non_cont: float = 0.0, v: float = 120.0) -> LoadSpec:
    return LoadSpec(
        continuous_current_A=cont,
        non_continuous_current_A=non_cont,
        voltage_V=v,
        phase="single_phase",
    )


def _ocpd(rating: float, btype: str = "standard") -> OcpdSpec:
    return OcpdSpec(breaker_rating_A=rating, breaker_type=btype)


# ---------------------------------------------------------------------------
# T01 — 12 AWG Cu THWN, 16A continuous, 0 non-cont, 20A breaker → PASS
# ---------------------------------------------------------------------------

def test_t01_12awg_16a_cont_20a_breaker_pass():
    """12 AWG Cu: required_ocpd = 1.25×16 = 20A; breaker=20A; ampacity=25A (but 240.4(D) cap=20A).
    20A breaker == 240.4(D) cap → ocpd_compliant=True; conductor_adequate=True.
    """
    rpt = check_circuit_protection(_conductor("12"), _load(16.0), _ocpd(20.0))
    assert rpt.ampacity_A == 25.0
    assert rpt.derated_ampacity_A == 20.0   # 240.4(D) cap
    assert abs(rpt.required_ocpd_min_A - 20.0) < 1e-6
    assert rpt.ocpd_compliant is True
    assert rpt.conductor_adequate is True


# ---------------------------------------------------------------------------
# T02 — 12 AWG Cu, 20A continuous, 0 non-cont, 20A breaker → FAIL (too small)
# ---------------------------------------------------------------------------

def test_t02_12awg_20a_cont_20a_breaker_fail():
    """12 AWG Cu: required_ocpd = 1.25×20 = 25A; breaker=20A < 25A → fail."""
    rpt = check_circuit_protection(_conductor("12"), _load(20.0), _ocpd(20.0))
    assert abs(rpt.required_ocpd_min_A - 25.0) < 1e-6
    # 20A breaker < 25A required → not load-compliant
    assert rpt.ocpd_compliant is False


# ---------------------------------------------------------------------------
# T03 — 6 AWG Cu, 60A continuous (pure), 70A breaker → ampacity=65A; FAIL
# ---------------------------------------------------------------------------

def test_t03_6awg_60a_cont_70a_breaker_fail():
    """6 AWG Cu: ampacity=65A; breaker=70A > ampacity → 240.4(B) fail."""
    rpt = check_circuit_protection(_conductor("6"), _load(60.0), _ocpd(70.0))
    assert rpt.ampacity_A == 65.0
    assert rpt.derated_ampacity_A == 65.0  # no 240.4(D) cap for 6 AWG
    # required = 1.25×60 = 75A; breaker=70A < 75A → load sizing fails too
    # Also breaker=70A > ampacity=65A → 240.4(B) fails
    assert rpt.ocpd_compliant is False


# ---------------------------------------------------------------------------
# T04 — Aluminum 4 AWG, 60A continuous, 75A breaker
#        ampacity (NEC Table 310.16 Al) = 65A; OCPD > ampacity → FAIL
# ---------------------------------------------------------------------------

def test_t04_al_4awg_60a_cont_75a_breaker_fail():
    """Al 4 AWG: Table 310.16 Al ampacity=65A; 75A breaker > 65A → 240.4(B) fail."""
    rpt = check_circuit_protection(_conductor("4", "aluminum"), _load(60.0), _ocpd(75.0))
    assert rpt.ampacity_A == 65.0
    # required = 1.25×60 = 75A; breaker=75A == required → load sizing pass
    # but 75A > ampacity=65A → 240.4(B) fail → ocpd_compliant=False
    assert rpt.ocpd_compliant is False


# ---------------------------------------------------------------------------
# T05 — 14 AWG Cu, 10A continuous, 15A breaker — 240.4(D) exactly at limit → PASS
# ---------------------------------------------------------------------------

def test_t05_14awg_15a_breaker_pass():
    """14 AWG Cu: 240.4(D) cap=15A; 15A breaker == cap → PASS."""
    rpt = check_circuit_protection(_conductor("14"), _load(10.0), _ocpd(15.0))
    assert rpt.derated_ampacity_A == 15.0
    assert rpt.ocpd_compliant is True
    assert rpt.conductor_adequate is True


# ---------------------------------------------------------------------------
# T06 — 14 AWG Cu, 20A breaker — exceeds 240.4(D) cap of 15A → FAIL
# ---------------------------------------------------------------------------

def test_t06_14awg_20a_breaker_fail():
    """14 AWG Cu: 240.4(D) cap=15A; 20A breaker > cap → FAIL."""
    rpt = check_circuit_protection(_conductor("14"), _load(10.0), _ocpd(20.0))
    assert rpt.derated_ampacity_A == 15.0
    # 20A > 15A derated → not compliant
    assert rpt.ocpd_compliant is False


# ---------------------------------------------------------------------------
# T07 — 12 AWG Cu, 20A breaker exactly at 240.4(D) cap → PASS
# ---------------------------------------------------------------------------

def test_t07_12awg_20a_breaker_at_cap_pass():
    """12 AWG Cu: 240.4(D) cap=20A; 20A breaker == cap; 12A continuous → required=15A → PASS."""
    rpt = check_circuit_protection(_conductor("12"), _load(12.0), _ocpd(20.0))
    assert rpt.derated_ampacity_A == 20.0
    assert abs(rpt.required_ocpd_min_A - 15.0) < 1e-6
    assert rpt.ocpd_compliant is True


# ---------------------------------------------------------------------------
# T08 — 10 AWG Cu, 30A breaker exactly at 240.4(D) cap → PASS
# ---------------------------------------------------------------------------

def test_t08_10awg_30a_breaker_at_cap_pass():
    """10 AWG Cu: 240.4(D) cap=30A; 30A breaker == cap; 20A continuous → required=25A → PASS."""
    rpt = check_circuit_protection(_conductor("10"), _load(20.0), _ocpd(30.0))
    assert rpt.derated_ampacity_A == 30.0
    assert abs(rpt.required_ocpd_min_A - 25.0) < 1e-6
    assert rpt.ocpd_compliant is True


# ---------------------------------------------------------------------------
# T09 — 10 AWG Cu, 35A breaker exceeds 240.4(D) cap of 30A → FAIL
# ---------------------------------------------------------------------------

def test_t09_10awg_35a_breaker_fail():
    """10 AWG Cu: 240.4(D) cap=30A; 35A breaker > cap → FAIL."""
    rpt = check_circuit_protection(_conductor("10"), _load(20.0), _ocpd(35.0))
    assert rpt.derated_ampacity_A == 30.0
    assert rpt.ocpd_compliant is False


# ---------------------------------------------------------------------------
# T10 — 8 AWG Cu, 40A continuous, 50A breaker → required=50A; breaker=ampacity=50A → PASS
# ---------------------------------------------------------------------------

def test_t10_8awg_40a_cont_50a_breaker_pass():
    """8 AWG Cu: ampacity=50A; required=1.25×40=50A; 50A breaker == required == ampacity → PASS."""
    rpt = check_circuit_protection(_conductor("8"), _load(40.0), _ocpd(50.0))
    assert rpt.ampacity_A == 50.0
    assert abs(rpt.required_ocpd_min_A - 50.0) < 1e-6
    assert rpt.ocpd_compliant is True
    assert rpt.conductor_adequate is True


# ---------------------------------------------------------------------------
# T11 — 1/0 AWG Cu, 100A continuous, 150A breaker → required=125A; PASS
# ---------------------------------------------------------------------------

def test_t11_1_0awg_100a_cont_150a_breaker_pass():
    """1/0 AWG Cu: ampacity=150A; required=125A; 150A breaker ≥ 125A and ≤ 150A → PASS."""
    rpt = check_circuit_protection(_conductor("1/0"), _load(100.0), _ocpd(150.0))
    assert rpt.ampacity_A == 150.0
    assert abs(rpt.required_ocpd_min_A - 125.0) < 1e-6
    assert rpt.ocpd_compliant is True
    assert rpt.conductor_adequate is True


# ---------------------------------------------------------------------------
# T12 — 4/0 AWG Cu, 200A continuous, 230A breaker → required=250A > ampacity=230A
# ---------------------------------------------------------------------------

def test_t12_4_0awg_200a_cont_230a_breaker_conductor_inadequate():
    """4/0 AWG Cu: ampacity=230A; required=1.25×200=250A > 230A → conductor_adequate=False.
    Also 230A breaker < required 250A → ocpd_compliant=False.
    """
    rpt = check_circuit_protection(_conductor("4/0"), _load(200.0), _ocpd(230.0))
    assert rpt.ampacity_A == 230.0
    assert abs(rpt.required_ocpd_min_A - 250.0) < 1e-6
    assert rpt.conductor_adequate is False
    assert rpt.ocpd_compliant is False


# ---------------------------------------------------------------------------
# T13 — Report fields all present and typed correctly
# ---------------------------------------------------------------------------

def test_t13_report_all_fields_typed():
    """CircuitProtectionReport must expose all documented fields with correct types."""
    rpt = check_circuit_protection(_conductor("6"), _load(30.0, 5.0), _ocpd(50.0))
    assert isinstance(rpt.ampacity_A, float)
    assert isinstance(rpt.required_ocpd_min_A, float)
    assert isinstance(rpt.derated_ampacity_A, float)
    assert isinstance(rpt.ocpd_compliant, bool)
    assert isinstance(rpt.conductor_adequate, bool)
    assert isinstance(rpt.code_section_cited, list)
    assert len(rpt.code_section_cited) >= 3
    assert isinstance(rpt.honest_caveat, str)
    assert len(rpt.honest_caveat) > 0


# ---------------------------------------------------------------------------
# T14 — Invalid AWG raises ValueError
# ---------------------------------------------------------------------------

def test_t14_invalid_awg_raises():
    """Unsupported AWG size must raise ValueError."""
    with pytest.raises(ValueError, match="Unsupported AWG"):
        check_circuit_protection(_conductor("7"), _load(10.0), _ocpd(20.0))


# ---------------------------------------------------------------------------
# T15 — Invalid material raises ValueError
# ---------------------------------------------------------------------------

def test_t15_invalid_material_raises():
    """Unknown conductor material must raise ValueError."""
    with pytest.raises(ValueError, match="material"):
        check_circuit_protection(_conductor("12", "gold"), _load(10.0), _ocpd(20.0))


# ---------------------------------------------------------------------------
# T16 — Negative continuous current raises ValueError
# ---------------------------------------------------------------------------

def test_t16_negative_current_raises():
    """Negative continuous current must raise ValueError."""
    with pytest.raises(ValueError, match="continuous_current_A"):
        check_circuit_protection(
            _conductor("12"),
            LoadSpec(-5.0, 0.0, 120.0, "single_phase"),
            _ocpd(20.0),
        )


# ---------------------------------------------------------------------------
# T17 — Invalid insulation raises ValueError
# ---------------------------------------------------------------------------

def test_t17_invalid_insulation_raises():
    """Unsupported insulation class must raise ValueError."""
    with pytest.raises(ValueError, match="insulation_class"):
        check_circuit_protection(
            ConductorSpec("12", "copper", "XLPE"),
            _load(10.0),
            _ocpd(20.0),
        )


# ---------------------------------------------------------------------------
# T18 — LLM tool handler happy path
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_t18_llm_tool_happy_path():
    """electronics_check_circuit_protection LLM tool returns ok=True for valid input."""
    from kerf_electronics.tools.circuit_protection import electronics_check_circuit_protection

    args = json.dumps({
        "awg_size": "12",
        "material": "copper",
        "insulation_class": "THWN",
        "continuous_current_A": 16.0,
        "non_continuous_current_A": 0.0,
        "voltage_V": 120.0,
        "phase": "single_phase",
        "breaker_rating_A": 20.0,
        "breaker_type": "standard",
    }).encode()

    result = await electronics_check_circuit_protection(None, args)
    payload = json.loads(result)
    assert payload.get("ok") is True
    assert "ampacity_A" in payload
    assert "required_ocpd_min_A" in payload
    assert "ocpd_compliant" in payload
    assert "conductor_adequate" in payload
    assert "code_section_cited" in payload
    assert "honest_caveat" in payload


# ---------------------------------------------------------------------------
# T19 — LLM tool handler bad args (invalid AWG)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_t19_llm_tool_bad_awg():
    """electronics_check_circuit_protection returns error payload for unsupported AWG."""
    from kerf_electronics.tools.circuit_protection import electronics_check_circuit_protection

    args = json.dumps({
        "awg_size": "7",   # not in table
        "material": "copper",
        "insulation_class": "THWN",
        "continuous_current_A": 10.0,
        "non_continuous_current_A": 0.0,
        "voltage_V": 120.0,
        "phase": "single_phase",
        "breaker_rating_A": 20.0,
    }).encode()

    result = await electronics_check_circuit_protection(None, args)
    payload = json.loads(result)
    assert "error" in payload or payload.get("ok") is False or "code" in payload


# ---------------------------------------------------------------------------
# T20 — LLM tool handler malformed JSON
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_t20_llm_tool_malformed_json():
    """electronics_check_circuit_protection returns error for malformed JSON."""
    from kerf_electronics.tools.circuit_protection import electronics_check_circuit_protection

    result = await electronics_check_circuit_protection(None, b"{not valid json{{")
    payload = json.loads(result)
    assert "error" in payload
    assert payload.get("code") == "BAD_ARGS"


# ---------------------------------------------------------------------------
# T21 — Aluminum 12 AWG, 15A continuous, 20A breaker → Al ampacity=20A; PASS
# ---------------------------------------------------------------------------

def test_t21_al_12awg_15a_cont_20a_breaker_pass():
    """12 AWG Al: Table 310.16 Al ampacity=20A; required=1.25×15=18.75A; 20A breaker → PASS."""
    rpt = check_circuit_protection(_conductor("12", "aluminum"), _load(15.0), _ocpd(20.0))
    assert rpt.ampacity_A == 20.0
    assert abs(rpt.required_ocpd_min_A - 18.75) < 1e-4
    assert rpt.ocpd_compliant is True
    assert rpt.conductor_adequate is True


# ---------------------------------------------------------------------------
# T22 — Non-continuous-only load: required = 1.25×0 + non_cont = non_cont
# ---------------------------------------------------------------------------

def test_t22_non_continuous_only_load():
    """With zero continuous load, required_ocpd = non_continuous_current_A exactly."""
    rpt = check_circuit_protection(
        _conductor("10"),
        LoadSpec(0.0, 28.0, 240.0, "single_phase"),
        _ocpd(30.0),
    )
    assert abs(rpt.required_ocpd_min_A - 28.0) < 1e-6
    # 30A breaker ≥ 28A and ≤ 30A (240.4(D) cap for 10 AWG) → PASS
    assert rpt.ocpd_compliant is True


# ---------------------------------------------------------------------------
# T23 — Mixed continuous + non-continuous: required = 1.25*cont + non_cont
# ---------------------------------------------------------------------------

def test_t23_mixed_continuous_non_continuous():
    """Required OCPD = 1.25×I_cont + I_non_cont (NEC 215.3)."""
    cont = 20.0
    non_cont = 10.0
    expected_required = 1.25 * cont + non_cont  # = 35.0 A
    rpt = check_circuit_protection(
        _conductor("8"),
        LoadSpec(cont, non_cont, 240.0, "single_phase"),
        _ocpd(40.0),
    )
    assert abs(rpt.required_ocpd_min_A - expected_required) < 1e-6
    # ampacity=50A; required=35A; breaker=40A ≥ 35A and ≤ 50A → PASS
    assert rpt.ocpd_compliant is True


# ---------------------------------------------------------------------------
# T24 — code_section_cited includes 240.4(D) for small conductors, not for large
# ---------------------------------------------------------------------------

def test_t24_small_conductor_section_cited():
    """240.4(D) section must appear in code_section_cited for ≤10 AWG, not for larger."""
    rpt_small = check_circuit_protection(_conductor("14"), _load(10.0), _ocpd(15.0))
    rpt_large = check_circuit_protection(_conductor("6"), _load(30.0), _ocpd(50.0))

    small_sections = " ".join(rpt_small.code_section_cited)
    large_sections = " ".join(rpt_large.code_section_cited)

    assert "240.4(D)" in small_sections
    assert "240.4(D)" not in large_sections


# ---------------------------------------------------------------------------
# T25 — honest_caveat always mentions derating caveats
# ---------------------------------------------------------------------------

def test_t25_honest_caveat_mentions_derating():
    """honest_caveat must warn about missing derating (temperature and bundling)."""
    rpt = check_circuit_protection(_conductor("8", "aluminum"), _load(35.0), _ocpd(40.0))
    caveat_lower = rpt.honest_caveat.lower()
    assert "derat" in caveat_lower or "310.15" in rpt.honest_caveat
    # Aluminum caveat
    assert "aluminum" in caveat_lower or "al" in caveat_lower


# ---------------------------------------------------------------------------
# T26 — Parametric: all AWG sizes produce positive ampacity
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("awg", [
    "14", "12", "10", "8", "6", "4", "3", "2", "1",
    "1/0", "2/0", "3/0", "4/0", "250kcmil", "300kcmil", "500kcmil",
])
def test_t26_all_awg_copper_ampacity_positive(awg):
    """Every supported copper AWG/kcmil size must yield ampacity_A > 0."""
    rpt = check_circuit_protection(
        _conductor(awg),
        _load(5.0),
        _ocpd(15.0),
    )
    assert rpt.ampacity_A > 0.0


# ---------------------------------------------------------------------------
# T27 — 3 AWG Cu, 80A continuous, 100A breaker → required=100A; ampacity=100A; PASS
# ---------------------------------------------------------------------------

def test_t27_3awg_80a_cont_100a_breaker_pass():
    """3 AWG Cu: ampacity=100A; required=1.25×80=100A; 100A breaker == required == ampacity → PASS."""
    rpt = check_circuit_protection(_conductor("3"), _load(80.0), _ocpd(100.0))
    assert rpt.ampacity_A == 100.0
    assert abs(rpt.required_ocpd_min_A - 100.0) < 1e-6
    assert rpt.ocpd_compliant is True


# ---------------------------------------------------------------------------
# T28 — 500 kcmil Cu, 300A continuous, 380A breaker → required=375A; breaker > required; PASS
# ---------------------------------------------------------------------------

def test_t28_500kcmil_300a_cont_380a_breaker_pass():
    """500 kcmil Cu: ampacity=380A; required=1.25×300=375A; 380A breaker ≥ 375A and ≤ 380A → PASS."""
    rpt = check_circuit_protection(_conductor("500kcmil"), _load(300.0), _ocpd(380.0))
    assert rpt.ampacity_A == 380.0
    assert abs(rpt.required_ocpd_min_A - 375.0) < 1e-6
    assert rpt.ocpd_compliant is True
    assert rpt.conductor_adequate is True
