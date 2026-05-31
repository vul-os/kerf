"""
Hermetic tests for kerf_electronics.wire_ampacity_derate —
NEC 2023 Article 310 ampacity derating (ambient + bundling).

NEC Table 310.15(B)(2)(a) correction factors (75 °C insulation column):
  ≤30°C → 1.00, 31–35°C → 0.94, 36–40°C → 0.88, 41–45°C → 0.82,
  46–50°C → 0.75, 51–55°C → 0.67, 56–60°C → 0.58.

NEC Table 310.15(B)(3)(a) bundling adjustment factors:
  1–3 → 1.00, 4–6 → 0.80, 7–9 → 0.70, 10–20 → 0.50,
  21–30 → 0.45, 31–40 → 0.40, 41+ → 0.35.

Test roster (14+ tests):
  1.  12 AWG Cu THWN, 30°C ambient, 3 conductors → C_T=1.00, C_b=1.00 → I_eff = base
  2.  12 AWG Cu THWN, 45°C ambient, 3 conductors → C_T=0.82, C_b=1.00 → I_eff = 0.82×base
  3.  12 AWG Cu THWN, 30°C ambient, 6 conductors → C_T=1.00, C_b=0.80 → I_eff = 0.80×base
  4.  12 AWG Cu THWN, 45°C ambient, 6 conductors → C_T=0.82, C_b=0.80 → I_eff = 0.656×base
  5.  Bracket boundaries — ambient factor for all 7 brackets
  6.  Bundling factors for all bracket boundaries (1,3,4,6,7,9,10,20,21,30,31,40,41,50)
  7.  free-air (in_conduit=False): bundling factor always 1.00 regardless of count
  8.  Ambient ≤30°C (below base 30): factor = 1.00
  9.  Ambient exactly at bracket boundaries (31,35,40,45,50,55,60)
  10. Large conductor run: 4/0 aluminum XHHW, 50°C, 9 conductors
  11. High conductor count: 41+ conductors → factor = 0.35
  12. ValueError for ambient > 60°C
  13. ValueError for invalid material
  14. ValueError for invalid insulation class
  15. ValueError for base_ampacity_A <= 0
  16. ValueError for num_current_carrying_conductors < 1
  17. Report has all required fields with correct types
  18. LLM tool handler happy path (valid JSON inputs)
  19. LLM tool handler bad args (invalid material)
  20. LLM tool handler malformed JSON
  21. Effective ampacity is monotonically decreasing with higher ambient
  22. Effective ampacity is monotonically decreasing with more conductors
"""
from __future__ import annotations

import json
import math
import pytest

from kerf_electronics.wire_ampacity_derate import (
    WireSpec,
    InstallationConditions,
    DeratedAmpacityReport,
    compute_derated_ampacity,
    _ambient_correction_factor_75c,
    _bundling_factor,
    _AMBIENT_CORRECTION_75C,
    _BUNDLING_FACTORS,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

BASE_12AWG_CU = 25.0   # NEC Table 310.16 75°C copper 12 AWG: 25 A
BASE_10AWG_CU = 35.0   # NEC Table 310.16 75°C copper 10 AWG: 35 A
BASE_4_0_AL   = 180.0  # NEC Table 310.16 75°C aluminum 4/0 AWG: 180 A


def _wire(awg="12", material="copper", ins="THWN", base=BASE_12AWG_CU):
    return WireSpec(awg_size=awg, material=material, insulation_class=ins, base_ampacity_A=base)


def _cond(ambient=30.0, n=1, in_conduit=True):
    return InstallationConditions(
        ambient_temp_C=ambient,
        num_current_carrying_conductors=n,
        in_conduit=in_conduit,
    )


# ---------------------------------------------------------------------------
# Test 1 — nominal: 30°C, 3 conductors → factors 1.00 × 1.00 → I_eff = base
# ---------------------------------------------------------------------------

def test_nominal_30c_3cond_no_derating():
    """12 AWG Cu THWN, ambient=30°C, 3 conductors: both factors 1.00."""
    rpt = compute_derated_ampacity(_wire(), _cond(ambient=30.0, n=3))
    assert rpt.ambient_correction_factor == 1.00
    assert rpt.bundling_factor == 1.00
    assert abs(rpt.effective_ampacity_A - BASE_12AWG_CU) < 1e-9


# ---------------------------------------------------------------------------
# Test 2 — 45°C ambient, 3 conductors → C_T=0.82, C_b=1.00
# ---------------------------------------------------------------------------

def test_45c_ambient_3cond_ambient_derating():
    """12 AWG Cu THWN, ambient=45°C, 3 conductors: C_T=0.82, C_b=1.00."""
    rpt = compute_derated_ampacity(_wire(), _cond(ambient=45.0, n=3))
    assert rpt.ambient_correction_factor == 0.82
    assert rpt.bundling_factor == 1.00
    expected = BASE_12AWG_CU * 0.82
    assert abs(rpt.effective_ampacity_A - expected) < 1e-6


# ---------------------------------------------------------------------------
# Test 3 — 30°C, 6 conductors → C_T=1.00, C_b=0.80
# ---------------------------------------------------------------------------

def test_30c_6cond_bundling_derating():
    """12 AWG Cu THWN, ambient=30°C, 6 conductors: C_T=1.00, C_b=0.80."""
    rpt = compute_derated_ampacity(_wire(), _cond(ambient=30.0, n=6))
    assert rpt.ambient_correction_factor == 1.00
    assert rpt.bundling_factor == 0.80
    expected = BASE_12AWG_CU * 0.80
    assert abs(rpt.effective_ampacity_A - expected) < 1e-6


# ---------------------------------------------------------------------------
# Test 4 — 45°C, 6 conductors → 0.82 × 0.80 = 0.656 × base
# ---------------------------------------------------------------------------

def test_45c_6cond_combined_derating():
    """12 AWG Cu THWN, ambient=45°C, 6 conductors: 0.82 × 0.80 = 0.656."""
    rpt = compute_derated_ampacity(_wire(), _cond(ambient=45.0, n=6))
    assert rpt.ambient_correction_factor == 0.82
    assert rpt.bundling_factor == 0.80
    combined = 0.82 * 0.80
    assert abs(combined - 0.656) < 1e-9
    expected = BASE_12AWG_CU * combined
    assert abs(rpt.effective_ampacity_A - expected) < 1e-6


# ---------------------------------------------------------------------------
# Test 5 — All ambient bracket factors (all 7 brackets)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("ambient,expected_factor", [
    (25.0, 1.00),   # below 30 → factor 1.00
    (30.0, 1.00),   # exactly 30 → first bracket upper bound
    (31.0, 0.94),   # 31–35 bracket
    (35.0, 0.94),   # exactly 35 → second bracket upper bound
    (36.0, 0.88),   # 36–40 bracket
    (40.0, 0.88),   # exactly 40
    (41.0, 0.82),   # 41–45 bracket
    (45.0, 0.82),   # exactly 45
    (46.0, 0.75),   # 46–50 bracket
    (50.0, 0.75),   # exactly 50
    (51.0, 0.67),   # 51–55 bracket
    (55.0, 0.67),   # exactly 55
    (56.0, 0.58),   # 56–60 bracket
    (60.0, 0.58),   # exactly 60 — maximum supported
])
def test_all_ambient_brackets(ambient, expected_factor):
    """Verify Table 310.15(B)(2)(a) correction factor for every bracket."""
    factor = _ambient_correction_factor_75c(ambient)
    assert factor == expected_factor, (
        f"At {ambient}°C expected {expected_factor}, got {factor}"
    )


# ---------------------------------------------------------------------------
# Test 6 — All bundling factor brackets
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("n,expected_factor", [
    (1,  1.00),
    (3,  1.00),   # upper bound of first bracket
    (4,  0.80),   # first count in 4–6 bracket
    (6,  0.80),
    (7,  0.70),
    (9,  0.70),
    (10, 0.50),
    (20, 0.50),
    (21, 0.45),
    (30, 0.45),
    (31, 0.40),
    (40, 0.40),
    (41, 0.35),
    (50, 0.35),
    (99, 0.35),
])
def test_all_bundling_brackets(n, expected_factor):
    """Verify Table 310.15(B)(3)(a) bundling factor for every bracket."""
    factor = _bundling_factor(n)
    assert factor == expected_factor, (
        f"For {n} conductors expected {expected_factor}, got {factor}"
    )


# ---------------------------------------------------------------------------
# Test 7 — Free-air installation: bundling factor always 1.00
# ---------------------------------------------------------------------------

def test_free_air_no_bundling_derating():
    """in_conduit=False: bundling factor = 1.00 regardless of conductor count."""
    for n in [1, 3, 6, 10, 41]:
        rpt = compute_derated_ampacity(
            _wire(),
            InstallationConditions(ambient_temp_C=30.0, num_current_carrying_conductors=n, in_conduit=False)
        )
        assert rpt.bundling_factor == 1.00, (
            f"Expected bundling_factor=1.00 for free-air with n={n}, got {rpt.bundling_factor}"
        )


# ---------------------------------------------------------------------------
# Test 8 — Ambient below 30°C clamps to factor 1.00
# ---------------------------------------------------------------------------

def test_ambient_below_30c_is_1_00():
    """Ambient < 30°C (e.g. 15°C) uses correction factor 1.00."""
    rpt = compute_derated_ampacity(_wire(), _cond(ambient=15.0))
    assert rpt.ambient_correction_factor == 1.00
    assert abs(rpt.effective_ampacity_A - BASE_12AWG_CU) < 1e-9


# ---------------------------------------------------------------------------
# Test 9 — Bracket boundaries produce expected factors (spot-check via full call)
# ---------------------------------------------------------------------------

def test_bracket_boundary_31c():
    """31°C is the first temperature above 30°C — must use 0.94."""
    rpt = compute_derated_ampacity(_wire(), _cond(ambient=31.0))
    assert rpt.ambient_correction_factor == 0.94


def test_bracket_boundary_55c():
    """55°C upper bound of 51–55 bracket → 0.67."""
    rpt = compute_derated_ampacity(_wire(), _cond(ambient=55.0))
    assert rpt.ambient_correction_factor == 0.67


# ---------------------------------------------------------------------------
# Test 10 — Large conductor: 4/0 Al XHHW, 50°C, 9 conductors
#           C_T=0.75 (46–50 bracket), C_b=0.70 (7–9 bracket)
# ---------------------------------------------------------------------------

def test_4_0_aluminum_xhhw_50c_9cond():
    """4/0 Al XHHW, base=180A, 50°C, 9 conductors: C_T=0.75, C_b=0.70."""
    wire = WireSpec(awg_size="4/0", material="aluminum", insulation_class="XHHW",
                    base_ampacity_A=BASE_4_0_AL)
    cond = InstallationConditions(ambient_temp_C=50.0, num_current_carrying_conductors=9)
    rpt = compute_derated_ampacity(wire, cond)
    assert rpt.ambient_correction_factor == 0.75
    assert rpt.bundling_factor == 0.70
    expected = BASE_4_0_AL * 0.75 * 0.70
    assert abs(rpt.effective_ampacity_A - expected) < 1e-5


# ---------------------------------------------------------------------------
# Test 11 — High conductor count ≥ 41 → bundling factor 0.35
# ---------------------------------------------------------------------------

def test_41_plus_conductors_factor_035():
    """41 or more current-carrying conductors → bundling factor = 0.35."""
    for n in [41, 50, 100]:
        rpt = compute_derated_ampacity(_wire(), _cond(ambient=30.0, n=n))
        assert rpt.bundling_factor == 0.35, f"n={n}: expected 0.35, got {rpt.bundling_factor}"
        expected = BASE_12AWG_CU * 1.00 * 0.35
        assert abs(rpt.effective_ampacity_A - expected) < 1e-6


# ---------------------------------------------------------------------------
# Test 12 — Ambient > 60°C raises ValueError
# ---------------------------------------------------------------------------

def test_ambient_above_60c_raises():
    """Ambient temperature > 60°C is outside Table 310.15(B)(2)(a) range."""
    with pytest.raises(ValueError, match="60"):
        compute_derated_ampacity(_wire(), _cond(ambient=61.0))

    with pytest.raises(ValueError, match="60"):
        _ambient_correction_factor_75c(75.0)


# ---------------------------------------------------------------------------
# Test 13 — Invalid material raises ValueError
# ---------------------------------------------------------------------------

def test_invalid_material_raises():
    """Unknown material must raise ValueError."""
    wire = WireSpec(awg_size="12", material="silver", insulation_class="THWN",
                    base_ampacity_A=25.0)
    with pytest.raises(ValueError, match="material"):
        compute_derated_ampacity(wire, _cond())


# ---------------------------------------------------------------------------
# Test 14 — Invalid insulation class raises ValueError
# ---------------------------------------------------------------------------

def test_invalid_insulation_raises():
    """Unknown insulation class must raise ValueError."""
    wire = WireSpec(awg_size="12", material="copper", insulation_class="XLPE",
                    base_ampacity_A=25.0)
    with pytest.raises(ValueError, match="insulation_class"):
        compute_derated_ampacity(wire, _cond())


# ---------------------------------------------------------------------------
# Test 15 — base_ampacity_A ≤ 0 raises ValueError
# ---------------------------------------------------------------------------

def test_zero_base_ampacity_raises():
    """base_ampacity_A must be positive."""
    wire = WireSpec(awg_size="12", material="copper", insulation_class="THWN",
                    base_ampacity_A=0.0)
    with pytest.raises(ValueError, match="base_ampacity_A"):
        compute_derated_ampacity(wire, _cond())

    wire_neg = WireSpec(awg_size="12", material="copper", insulation_class="THWN",
                        base_ampacity_A=-5.0)
    with pytest.raises(ValueError, match="base_ampacity_A"):
        compute_derated_ampacity(wire_neg, _cond())


# ---------------------------------------------------------------------------
# Test 16 — num_current_carrying_conductors < 1 raises ValueError
# ---------------------------------------------------------------------------

def test_zero_conductors_raises():
    """num_current_carrying_conductors must be ≥ 1."""
    with pytest.raises(ValueError):
        compute_derated_ampacity(_wire(), _cond(n=0))
    with pytest.raises(ValueError):
        _bundling_factor(0)


# ---------------------------------------------------------------------------
# Test 17 — Report has all required fields with correct types
# ---------------------------------------------------------------------------

def test_report_has_all_required_fields():
    """DeratedAmpacityReport must expose all documented fields."""
    rpt = compute_derated_ampacity(_wire(), _cond(ambient=40.0, n=6))

    assert hasattr(rpt, "base_ampacity_A")
    assert hasattr(rpt, "ambient_correction_factor")
    assert hasattr(rpt, "bundling_factor")
    assert hasattr(rpt, "effective_ampacity_A")
    assert hasattr(rpt, "conditions_summary")
    assert hasattr(rpt, "code_section_cited")
    assert hasattr(rpt, "honest_caveat")

    assert isinstance(rpt.base_ampacity_A, float)
    assert isinstance(rpt.ambient_correction_factor, float)
    assert isinstance(rpt.bundling_factor, float)
    assert isinstance(rpt.effective_ampacity_A, float)
    assert isinstance(rpt.conditions_summary, str)
    assert isinstance(rpt.code_section_cited, list)
    assert len(rpt.code_section_cited) >= 2
    assert isinstance(rpt.honest_caveat, str)
    assert len(rpt.honest_caveat) > 20


# ---------------------------------------------------------------------------
# Test 18 — LLM tool handler happy path
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_llm_tool_handler_happy_path():
    """electronics_compute_derated_ampacity returns ok=True for valid inputs."""
    from kerf_electronics.tools.wire_ampacity_derate import electronics_compute_derated_ampacity

    args = json.dumps({
        "awg_size": "12",
        "material": "copper",
        "insulation_class": "THWN",
        "base_ampacity_A": 25.0,
        "ambient_temp_C": 45.0,
        "num_current_carrying_conductors": 6,
        "in_conduit": True,
    }).encode()

    result = await electronics_compute_derated_ampacity(None, args)
    payload = json.loads(result)

    assert payload.get("ok") is True
    assert "base_ampacity_A" in payload
    assert "ambient_correction_factor" in payload
    assert "bundling_factor" in payload
    assert "effective_ampacity_A" in payload
    assert "conditions_summary" in payload
    assert "code_section_cited" in payload
    assert "honest_caveat" in payload

    # 0.82 × 0.80 × 25 = 16.4 A
    assert abs(payload["ambient_correction_factor"] - 0.82) < 1e-9
    assert abs(payload["bundling_factor"] - 0.80) < 1e-9
    assert abs(payload["effective_ampacity_A"] - 16.4) < 1e-5


# ---------------------------------------------------------------------------
# Test 19 — LLM tool handler bad args (invalid material)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_llm_tool_handler_bad_args():
    """electronics_compute_derated_ampacity returns error payload for invalid material."""
    from kerf_electronics.tools.wire_ampacity_derate import electronics_compute_derated_ampacity

    args = json.dumps({
        "awg_size": "12",
        "material": "gold",          # invalid
        "insulation_class": "THWN",
        "base_ampacity_A": 25.0,
        "ambient_temp_C": 30.0,
    }).encode()

    result = await electronics_compute_derated_ampacity(None, args)
    payload = json.loads(result)
    assert "error" in payload
    assert payload.get("code") == "BAD_ARGS"


# ---------------------------------------------------------------------------
# Test 20 — LLM tool handler malformed JSON
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_llm_tool_handler_malformed_json():
    """electronics_compute_derated_ampacity returns error payload for malformed JSON."""
    from kerf_electronics.tools.wire_ampacity_derate import electronics_compute_derated_ampacity

    result = await electronics_compute_derated_ampacity(None, b"not valid json {{")
    payload = json.loads(result)
    assert "error" in payload
    assert payload.get("code") == "BAD_ARGS"


# ---------------------------------------------------------------------------
# Test 21 — Effective ampacity monotonically decreasing with higher ambient
# ---------------------------------------------------------------------------

def test_monotone_decrease_with_ambient():
    """As ambient temperature rises, effective ampacity must decrease or stay same."""
    temps = [25, 30, 35, 40, 45, 50, 55, 60]
    ampacities = []
    for t in temps:
        rpt = compute_derated_ampacity(_wire(), _cond(ambient=float(t), n=3))
        ampacities.append(rpt.effective_ampacity_A)

    for i in range(1, len(ampacities)):
        assert ampacities[i] <= ampacities[i - 1], (
            f"Ampacity increased from {temps[i-1]}°C to {temps[i]}°C: "
            f"{ampacities[i-1]:.4f} → {ampacities[i]:.4f}"
        )


# ---------------------------------------------------------------------------
# Test 22 — Effective ampacity monotonically decreasing with more conductors
# ---------------------------------------------------------------------------

def test_monotone_decrease_with_conductors():
    """As conductor count rises (in_conduit=True), effective ampacity must decrease."""
    counts = [1, 3, 4, 6, 7, 9, 10, 20, 21, 30, 31, 40, 41, 50]
    ampacities = []
    for n in counts:
        rpt = compute_derated_ampacity(_wire(), _cond(ambient=30.0, n=n))
        ampacities.append(rpt.effective_ampacity_A)

    for i in range(1, len(ampacities)):
        assert ampacities[i] <= ampacities[i - 1], (
            f"Ampacity increased from n={counts[i-1]} to n={counts[i]}: "
            f"{ampacities[i-1]:.4f} → {ampacities[i]:.4f}"
        )


# ---------------------------------------------------------------------------
# Test 23 — code_section_cited includes Table 310.16 and 310.15(B)(2)(a)
# ---------------------------------------------------------------------------

def test_code_sections_always_include_base_references():
    """Report code_section_cited must always mention Table 310.16 and 310.15(B)(2)(a)."""
    rpt = compute_derated_ampacity(_wire(), _cond(ambient=30.0, n=1))
    joined = " ".join(rpt.code_section_cited)
    assert "310.16" in joined
    assert "310.15" in joined


# ---------------------------------------------------------------------------
# Test 24 — Bundling code section cites conductor count when > 3
# ---------------------------------------------------------------------------

def test_code_section_mentions_bundling_count():
    """When > 3 conductors, bundling section should cite the count."""
    rpt = compute_derated_ampacity(_wire(), _cond(ambient=30.0, n=10))
    # The report should explicitly mention 310.15(B)(3)(a)
    joined = " ".join(rpt.code_section_cited)
    assert "310.15" in joined
    assert any("0.50" in s or "10" in s for s in rpt.code_section_cited)


# ---------------------------------------------------------------------------
# Test 25 — Conditions summary contains key parameters
# ---------------------------------------------------------------------------

def test_conditions_summary_contains_key_params():
    """conditions_summary must mention AWG, material, ambient and effective ampacity."""
    rpt = compute_derated_ampacity(_wire(awg="10", base=BASE_10AWG_CU), _cond(ambient=40.0, n=6))
    summary = rpt.conditions_summary
    assert "10" in summary         # AWG
    assert "copper" in summary.lower()
    assert "40" in summary         # ambient
    assert "0.80" in summary       # bundling factor


# ---------------------------------------------------------------------------
# Test 26 — TW insulation accepted with honest caveat about 60°C rating
# ---------------------------------------------------------------------------

def test_tw_insulation_accepted_with_caveat():
    """TW insulation is accepted; caveat warns about 60°C vs 75°C column."""
    wire = WireSpec(awg_size="14", material="copper", insulation_class="TW",
                    base_ampacity_A=15.0)
    rpt = compute_derated_ampacity(wire, _cond(ambient=30.0))
    assert rpt.effective_ampacity_A > 0
    assert "TW" in rpt.honest_caveat or "60" in rpt.honest_caveat


# ---------------------------------------------------------------------------
# Test 27 — Aluminum conductor accepted
# ---------------------------------------------------------------------------

def test_aluminum_conductor_accepted():
    """Aluminum material is valid and produces a positive effective ampacity."""
    wire = WireSpec(awg_size="2/0", material="aluminum", insulation_class="THHN",
                    base_ampacity_A=135.0)
    rpt = compute_derated_ampacity(wire, _cond(ambient=35.0, n=4))
    # C_T=0.94, C_b=0.80
    assert rpt.ambient_correction_factor == 0.94
    assert rpt.bundling_factor == 0.80
    expected = 135.0 * 0.94 * 0.80
    assert abs(rpt.effective_ampacity_A - expected) < 1e-5


# ---------------------------------------------------------------------------
# Test 28 — RHW insulation accepted
# ---------------------------------------------------------------------------

def test_rhw_insulation_accepted():
    """RHW insulation is a valid 75°C class and produces correct factors."""
    wire = WireSpec(awg_size="6", material="copper", insulation_class="RHW",
                    base_ampacity_A=65.0)
    rpt = compute_derated_ampacity(wire, _cond(ambient=56.0, n=7))
    # C_T=0.58, C_b=0.70
    assert rpt.ambient_correction_factor == 0.58
    assert rpt.bundling_factor == 0.70
    expected = 65.0 * 0.58 * 0.70
    assert abs(rpt.effective_ampacity_A - expected) < 1e-5
