"""
Tests for kerf_mold.sprue_bushing_match
=========================================
Covers compliant cases, non-compliant radius (tight / loose), non-compliant
orifice, taper out-of-range, edge cases, LLM tool dispatch, plugin registration,
and __init__ re-exports.

Beaumont 2007 §6.4 rules:
  sprue_R = nozzle_r + 0.5–1.0 mm  (seat radius excess)
  sprue_O = nozzle_O + 0.5–1.0 mm  (orifice diameter excess)
  taper   = 1.5°/side – 3.0°/side  (DME standard §3.2)

References:
  Beaumont J.P. Runner and Gating Design Handbook, 2nd ed., Hanser 2007, §6.4.
  DME Company LLC Mold Components Catalogue 2023, §3.2.
"""

from __future__ import annotations

import asyncio
import json

import pytest

from kerf_mold.sprue_bushing_match import (
    SprueBushingSpec,
    MachineNozzleSpec,
    SprueMatchReport,
    check_sprue_bushing_match,
    R_EXCESS_MIN_MM,
    R_EXCESS_MAX_MM,
    O_EXCESS_MIN_MM,
    O_EXCESS_MAX_MM,
    TAPER_MIN_DEG,
    TAPER_MAX_DEG,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


class _Ctx:
    pass


CTX = _Ctx()


def _standard_sprue(
    R_mm: float = 12.7,
    O_mm: float = 4.5,
    length_mm: float = 70.0,
    taper_deg: float = 2.0,
) -> SprueBushingSpec:
    return SprueBushingSpec(
        nozzle_radius_R_mm=R_mm,
        sprue_orifice_diameter_O_mm=O_mm,
        total_length_mm=length_mm,
        taper_per_side_deg=taper_deg,
    )


def _standard_nozzle(
    r_mm: float = 12.0,
    O_mm: float = 4.0,
) -> MachineNozzleSpec:
    return MachineNozzleSpec(
        nozzle_tip_radius_mm=r_mm,
        nozzle_tip_orifice_diameter_mm=O_mm,
    )


# ---------------------------------------------------------------------------
# 1. Standard compliant case: nozzle r=12, sprue R=12.7, nozzle O=4, sprue O=4.5
# ---------------------------------------------------------------------------

def test_standard_compliant_case():
    """nozzle r=12 mm, sprue R=12.7 mm (+0.7 mm); nozzle O=4, sprue O=4.5 (+0.5): compliant."""
    sprue = _standard_sprue(R_mm=12.7, O_mm=4.5, taper_deg=2.0)
    nozzle = _standard_nozzle(r_mm=12.0, O_mm=4.0)
    report = check_sprue_bushing_match(sprue, nozzle)
    assert report.R_compliant is True
    assert report.O_compliant is True
    assert report.taper_compliant is True
    assert report.R_mismatch_mm == pytest.approx(0.7)
    assert report.O_mismatch_mm == pytest.approx(0.5)
    assert "COMPLIANT" in report.recommendation


# ---------------------------------------------------------------------------
# 2. Sprue R equals nozzle R (R_mismatch=0): not compliant
# ---------------------------------------------------------------------------

def test_sprue_R_equal_to_nozzle_R_not_compliant():
    """Sprue R = nozzle R (0 mm excess) → interference risk → R_compliant=False."""
    sprue = _standard_sprue(R_mm=12.0, O_mm=4.5, taper_deg=2.0)
    nozzle = _standard_nozzle(r_mm=12.0, O_mm=4.0)
    report = check_sprue_bushing_match(sprue, nozzle)
    assert report.R_compliant is False
    assert report.R_mismatch_mm == pytest.approx(0.0)
    assert "NON-COMPLIANT" in report.recommendation


# ---------------------------------------------------------------------------
# 3. Sprue R 2 mm larger than nozzle R (too loose): not compliant
# ---------------------------------------------------------------------------

def test_sprue_R_2mm_larger_not_compliant():
    """Sprue R = nozzle R + 2.0 mm (exceeds +1.0 mm max) → R_compliant=False."""
    sprue = _standard_sprue(R_mm=14.0, O_mm=4.5, taper_deg=2.0)
    nozzle = _standard_nozzle(r_mm=12.0, O_mm=4.0)
    report = check_sprue_bushing_match(sprue, nozzle)
    assert report.R_compliant is False
    assert report.R_mismatch_mm == pytest.approx(2.0)
    assert "NON-COMPLIANT" in report.recommendation


# ---------------------------------------------------------------------------
# 4. Sprue R at minimum bound (+0.5 mm): compliant
# ---------------------------------------------------------------------------

def test_sprue_R_at_minimum_bound_compliant():
    """Sprue R = nozzle R + 0.5 mm (lower bound) → R_compliant=True."""
    sprue = _standard_sprue(R_mm=12.5, O_mm=4.5, taper_deg=2.0)
    nozzle = _standard_nozzle(r_mm=12.0, O_mm=4.0)
    report = check_sprue_bushing_match(sprue, nozzle)
    assert report.R_compliant is True
    assert report.R_mismatch_mm == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# 5. Sprue R at maximum bound (+1.0 mm): compliant
# ---------------------------------------------------------------------------

def test_sprue_R_at_maximum_bound_compliant():
    """Sprue R = nozzle R + 1.0 mm (upper bound) → R_compliant=True."""
    sprue = _standard_sprue(R_mm=13.0, O_mm=4.5, taper_deg=2.0)
    nozzle = _standard_nozzle(r_mm=12.0, O_mm=4.0)
    report = check_sprue_bushing_match(sprue, nozzle)
    assert report.R_compliant is True
    assert report.R_mismatch_mm == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# 6. Orifice undersized (sprue O = nozzle O): not compliant
# ---------------------------------------------------------------------------

def test_sprue_O_equal_to_nozzle_O_not_compliant():
    """Sprue O = nozzle O (0 mm excess) → back-pressure risk → O_compliant=False."""
    sprue = _standard_sprue(R_mm=12.7, O_mm=4.0, taper_deg=2.0)
    nozzle = _standard_nozzle(r_mm=12.0, O_mm=4.0)
    report = check_sprue_bushing_match(sprue, nozzle)
    assert report.O_compliant is False
    assert report.O_mismatch_mm == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# 7. Orifice oversized by 2 mm: not compliant
# ---------------------------------------------------------------------------

def test_sprue_O_2mm_too_large_not_compliant():
    """Sprue O = nozzle O + 2.0 mm (exceeds +1.0 mm max) → O_compliant=False."""
    sprue = _standard_sprue(R_mm=12.7, O_mm=6.0, taper_deg=2.0)
    nozzle = _standard_nozzle(r_mm=12.0, O_mm=4.0)
    report = check_sprue_bushing_match(sprue, nozzle)
    assert report.O_compliant is False
    assert report.O_mismatch_mm == pytest.approx(2.0)


# ---------------------------------------------------------------------------
# 8. Taper below 1.5°/side: not compliant
# ---------------------------------------------------------------------------

def test_taper_below_minimum_not_compliant():
    """Taper = 1.0°/side < 1.5° minimum → taper_compliant=False."""
    sprue = _standard_sprue(R_mm=12.7, O_mm=4.5, taper_deg=1.0)
    nozzle = _standard_nozzle(r_mm=12.0, O_mm=4.0)
    report = check_sprue_bushing_match(sprue, nozzle)
    assert report.taper_compliant is False
    assert "NON-COMPLIANT" in report.recommendation


# ---------------------------------------------------------------------------
# 9. Taper above 3.0°/side: not compliant
# ---------------------------------------------------------------------------

def test_taper_above_maximum_not_compliant():
    """Taper = 4.0°/side > 3.0° maximum → taper_compliant=False."""
    sprue = _standard_sprue(R_mm=12.7, O_mm=4.5, taper_deg=4.0)
    nozzle = _standard_nozzle(r_mm=12.0, O_mm=4.0)
    report = check_sprue_bushing_match(sprue, nozzle)
    assert report.taper_compliant is False


# ---------------------------------------------------------------------------
# 10. Taper at minimum boundary (1.5°): compliant
# ---------------------------------------------------------------------------

def test_taper_at_minimum_boundary_compliant():
    """Taper = 1.5°/side (lower bound) → taper_compliant=True."""
    sprue = _standard_sprue(R_mm=12.7, O_mm=4.5, taper_deg=TAPER_MIN_DEG)
    nozzle = _standard_nozzle(r_mm=12.0, O_mm=4.0)
    report = check_sprue_bushing_match(sprue, nozzle)
    assert report.taper_compliant is True


# ---------------------------------------------------------------------------
# 11. Taper at maximum boundary (3.0°): compliant
# ---------------------------------------------------------------------------

def test_taper_at_maximum_boundary_compliant():
    """Taper = 3.0°/side (upper bound) → taper_compliant=True."""
    sprue = _standard_sprue(R_mm=12.7, O_mm=4.5, taper_deg=TAPER_MAX_DEG)
    nozzle = _standard_nozzle(r_mm=12.0, O_mm=4.0)
    report = check_sprue_bushing_match(sprue, nozzle)
    assert report.taper_compliant is True


# ---------------------------------------------------------------------------
# 12. All three checks fail simultaneously
# ---------------------------------------------------------------------------

def test_all_three_checks_fail():
    """R too large, O too large, taper too low → all three non-compliant."""
    sprue = _standard_sprue(R_mm=15.0, O_mm=9.0, taper_deg=0.5)
    nozzle = _standard_nozzle(r_mm=12.0, O_mm=4.0)
    report = check_sprue_bushing_match(sprue, nozzle)
    assert report.R_compliant is False
    assert report.O_compliant is False
    assert report.taper_compliant is False
    assert "NON-COMPLIANT" in report.recommendation


# ---------------------------------------------------------------------------
# 13. Sprue R slightly below lower bound (0.49 mm excess): not compliant
# ---------------------------------------------------------------------------

def test_sprue_R_just_below_lower_bound_not_compliant():
    """Sprue R excess 0.49 mm < 0.5 mm minimum → R_compliant=False."""
    sprue = _standard_sprue(R_mm=12.49, O_mm=4.5, taper_deg=2.0)
    nozzle = _standard_nozzle(r_mm=12.0, O_mm=4.0)
    report = check_sprue_bushing_match(sprue, nozzle)
    assert report.R_compliant is False
    assert report.R_mismatch_mm == pytest.approx(0.49)


# ---------------------------------------------------------------------------
# 14. Sprue R slightly above upper bound (1.01 mm excess): not compliant
# ---------------------------------------------------------------------------

def test_sprue_R_just_above_upper_bound_not_compliant():
    """Sprue R excess 1.01 mm > 1.0 mm maximum → R_compliant=False."""
    sprue = _standard_sprue(R_mm=13.01, O_mm=4.5, taper_deg=2.0)
    nozzle = _standard_nozzle(r_mm=12.0, O_mm=4.0)
    report = check_sprue_bushing_match(sprue, nozzle)
    assert report.R_compliant is False
    assert report.R_mismatch_mm == pytest.approx(1.01)


# ---------------------------------------------------------------------------
# 15. Sprue R smaller than nozzle R (negative mismatch): not compliant
# ---------------------------------------------------------------------------

def test_sprue_R_smaller_than_nozzle_R_not_compliant():
    """Sprue R < nozzle R → R_mismatch < 0 → R_compliant=False."""
    sprue = _standard_sprue(R_mm=11.0, O_mm=4.5, taper_deg=2.0)
    nozzle = _standard_nozzle(r_mm=12.0, O_mm=4.0)
    report = check_sprue_bushing_match(sprue, nozzle)
    assert report.R_compliant is False
    assert report.R_mismatch_mm < 0.0


# ---------------------------------------------------------------------------
# 16. Zero nozzle radius → ValueError
# ---------------------------------------------------------------------------

def test_zero_nozzle_radius_raises():
    with pytest.raises(ValueError, match="nozzle_tip_radius_mm must be > 0"):
        MachineNozzleSpec(nozzle_tip_radius_mm=0.0, nozzle_tip_orifice_diameter_mm=4.0)


# ---------------------------------------------------------------------------
# 17. Zero sprue R → ValueError
# ---------------------------------------------------------------------------

def test_zero_sprue_R_raises():
    with pytest.raises(ValueError, match="nozzle_radius_R_mm must be > 0"):
        SprueBushingSpec(
            nozzle_radius_R_mm=0.0,
            sprue_orifice_diameter_O_mm=4.5,
            total_length_mm=70.0,
            taper_per_side_deg=2.0,
        )


# ---------------------------------------------------------------------------
# 18. Zero taper → ValueError
# ---------------------------------------------------------------------------

def test_zero_taper_raises():
    with pytest.raises(ValueError, match="taper_per_side_deg must be > 0"):
        SprueBushingSpec(
            nozzle_radius_R_mm=12.7,
            sprue_orifice_diameter_O_mm=4.5,
            total_length_mm=70.0,
            taper_per_side_deg=0.0,
        )


# ---------------------------------------------------------------------------
# 19. Zero sprue orifice → ValueError
# ---------------------------------------------------------------------------

def test_zero_sprue_orifice_raises():
    with pytest.raises(ValueError, match="sprue_orifice_diameter_O_mm must be > 0"):
        SprueBushingSpec(
            nozzle_radius_R_mm=12.7,
            sprue_orifice_diameter_O_mm=0.0,
            total_length_mm=70.0,
            taper_per_side_deg=2.0,
        )


# ---------------------------------------------------------------------------
# 20. Honest caveat mentions cold-runner and hot-runner scope
# ---------------------------------------------------------------------------

def test_honest_caveat_scope():
    """Honest caveat must mention cold-runner scope and hot-runner exclusion."""
    sprue = _standard_sprue()
    nozzle = _standard_nozzle()
    report = check_sprue_bushing_match(sprue, nozzle)
    caveat = report.honest_caveat.lower()
    assert "cold-runner" in caveat
    assert "hot-runner" in caveat
    assert "beaumont" in caveat


# ---------------------------------------------------------------------------
# 21. Report dataclass is SprueMatchReport with correct fields
# ---------------------------------------------------------------------------

def test_report_fields_present():
    """SprueMatchReport has the expected field names."""
    sprue = _standard_sprue()
    nozzle = _standard_nozzle()
    report = check_sprue_bushing_match(sprue, nozzle)
    assert isinstance(report, SprueMatchReport)
    assert hasattr(report, "R_mismatch_mm")
    assert hasattr(report, "R_compliant")
    assert hasattr(report, "O_mismatch_mm")
    assert hasattr(report, "O_compliant")
    assert hasattr(report, "taper_compliant")
    assert hasattr(report, "recommendation")
    assert hasattr(report, "honest_caveat")


# ---------------------------------------------------------------------------
# 22. O mismatch at lower bound (+0.5 mm): compliant
# ---------------------------------------------------------------------------

def test_O_mismatch_at_lower_bound_compliant():
    """Sprue O = nozzle O + 0.5 mm (lower bound) → O_compliant=True."""
    sprue = _standard_sprue(R_mm=12.7, O_mm=4.5, taper_deg=2.0)
    nozzle = _standard_nozzle(r_mm=12.0, O_mm=4.0)
    report = check_sprue_bushing_match(sprue, nozzle)
    assert report.O_compliant is True
    assert report.O_mismatch_mm == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# 23. O mismatch at upper bound (+1.0 mm): compliant
# ---------------------------------------------------------------------------

def test_O_mismatch_at_upper_bound_compliant():
    """Sprue O = nozzle O + 1.0 mm (upper bound) → O_compliant=True."""
    sprue = _standard_sprue(R_mm=12.7, O_mm=5.0, taper_deg=2.0)
    nozzle = _standard_nozzle(r_mm=12.0, O_mm=4.0)
    report = check_sprue_bushing_match(sprue, nozzle)
    assert report.O_compliant is True
    assert report.O_mismatch_mm == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# 24. LLM tool dispatch — standard compliant case
# ---------------------------------------------------------------------------

def test_tool_dispatch_compliant():
    from kerf_mold.sprue_bushing_match_tool import run_mold_check_sprue_bushing_match
    result = json.loads(_run(run_mold_check_sprue_bushing_match({
        "sprue_bushing": {
            "nozzle_radius_R_mm": 12.7,
            "sprue_orifice_diameter_O_mm": 4.5,
            "total_length_mm": 70.0,
            "taper_per_side_deg": 2.0,
        },
        "machine_nozzle": {
            "nozzle_tip_radius_mm": 12.0,
            "nozzle_tip_orifice_diameter_mm": 4.0,
        },
    }, CTX)))
    assert result.get("ok") is True
    assert result["R_compliant"] is True
    assert result["O_compliant"] is True
    assert result["taper_compliant"] is True
    assert result["fully_compliant"] is True


# ---------------------------------------------------------------------------
# 25. LLM tool dispatch — sprue R equals nozzle R → non-compliant
# ---------------------------------------------------------------------------

def test_tool_dispatch_R_equal_not_compliant():
    from kerf_mold.sprue_bushing_match_tool import run_mold_check_sprue_bushing_match
    result = json.loads(_run(run_mold_check_sprue_bushing_match({
        "sprue_bushing": {
            "nozzle_radius_R_mm": 12.0,
            "sprue_orifice_diameter_O_mm": 4.5,
            "total_length_mm": 70.0,
            "taper_per_side_deg": 2.0,
        },
        "machine_nozzle": {
            "nozzle_tip_radius_mm": 12.0,
            "nozzle_tip_orifice_diameter_mm": 4.0,
        },
    }, CTX)))
    assert result.get("ok") is True
    assert result["R_compliant"] is False
    assert result["fully_compliant"] is False


# ---------------------------------------------------------------------------
# 26. LLM tool dispatch — missing sprue_bushing → BAD_ARGS
# ---------------------------------------------------------------------------

def test_tool_dispatch_missing_sprue_bushing():
    from kerf_mold.sprue_bushing_match_tool import run_mold_check_sprue_bushing_match
    result = json.loads(_run(run_mold_check_sprue_bushing_match({
        "machine_nozzle": {
            "nozzle_tip_radius_mm": 12.0,
            "nozzle_tip_orifice_diameter_mm": 4.0,
        }
    }, CTX)))
    assert "error" in result
    assert result.get("code") == "BAD_ARGS"


# ---------------------------------------------------------------------------
# 27. LLM tool dispatch — missing machine_nozzle → BAD_ARGS
# ---------------------------------------------------------------------------

def test_tool_dispatch_missing_machine_nozzle():
    from kerf_mold.sprue_bushing_match_tool import run_mold_check_sprue_bushing_match
    result = json.loads(_run(run_mold_check_sprue_bushing_match({
        "sprue_bushing": {
            "nozzle_radius_R_mm": 12.7,
            "sprue_orifice_diameter_O_mm": 4.5,
            "total_length_mm": 70.0,
            "taper_per_side_deg": 2.0,
        }
    }, CTX)))
    assert "error" in result
    assert result.get("code") == "BAD_ARGS"


# ---------------------------------------------------------------------------
# 28. LLM tool dispatch — non-numeric nozzle radius → BAD_ARGS
# ---------------------------------------------------------------------------

def test_tool_dispatch_non_numeric_nozzle_radius():
    from kerf_mold.sprue_bushing_match_tool import run_mold_check_sprue_bushing_match
    result = json.loads(_run(run_mold_check_sprue_bushing_match({
        "sprue_bushing": {
            "nozzle_radius_R_mm": 12.7,
            "sprue_orifice_diameter_O_mm": 4.5,
            "total_length_mm": 70.0,
            "taper_per_side_deg": 2.0,
        },
        "machine_nozzle": {
            "nozzle_tip_radius_mm": "twelve",
            "nozzle_tip_orifice_diameter_mm": 4.0,
        },
    }, CTX)))
    assert "error" in result
    assert result.get("code") == "BAD_ARGS"


# ---------------------------------------------------------------------------
# 29. LLM tool dispatch — zero sprue R → BAD_ARGS
# ---------------------------------------------------------------------------

def test_tool_dispatch_zero_sprue_R():
    from kerf_mold.sprue_bushing_match_tool import run_mold_check_sprue_bushing_match
    result = json.loads(_run(run_mold_check_sprue_bushing_match({
        "sprue_bushing": {
            "nozzle_radius_R_mm": 0.0,
            "sprue_orifice_diameter_O_mm": 4.5,
            "total_length_mm": 70.0,
            "taper_per_side_deg": 2.0,
        },
        "machine_nozzle": {
            "nozzle_tip_radius_mm": 12.0,
            "nozzle_tip_orifice_diameter_mm": 4.0,
        },
    }, CTX)))
    assert "error" in result
    assert result.get("code") == "BAD_ARGS"


# ---------------------------------------------------------------------------
# 30. Tool spec name and required fields
# ---------------------------------------------------------------------------

def test_tool_spec_name():
    from kerf_mold.sprue_bushing_match_tool import mold_check_sprue_bushing_match_spec
    assert mold_check_sprue_bushing_match_spec.name == "mold_check_sprue_bushing_match"


def test_tool_spec_required_fields():
    from kerf_mold.sprue_bushing_match_tool import mold_check_sprue_bushing_match_spec
    required = mold_check_sprue_bushing_match_spec.input_schema.get("required", [])
    assert "sprue_bushing" in required
    assert "machine_nozzle" in required


# ---------------------------------------------------------------------------
# 31. Plugin registers mold_check_sprue_bushing_match
# ---------------------------------------------------------------------------

def test_plugin_registers_sprue_bushing_tool():
    from kerf_mold.plugin import register
    from fastapi import FastAPI

    class _MockReg:
        def __init__(self):
            self.registered = {}

        def register(self, name, spec, handler):
            self.registered[name] = (spec, handler)

    class _MockCtx:
        def __init__(self):
            self.tools = _MockReg()

    app = FastAPI()
    ctx = _MockCtx()

    async def _go():
        return await register(app, ctx)

    _run(_go())
    assert "mold_check_sprue_bushing_match" in ctx.tools.registered, (
        "mold_check_sprue_bushing_match should be registered in the plugin"
    )


# ---------------------------------------------------------------------------
# 32. Re-export from kerf_mold.__init__
# ---------------------------------------------------------------------------

def test_init_exports():
    from kerf_mold import (
        SprueBushingSpec,
        MachineNozzleSpec,
        SprueMatchReport,
        check_sprue_bushing_match,
        R_EXCESS_MIN_MM,
        R_EXCESS_MAX_MM,
        O_EXCESS_MIN_MM,
        O_EXCESS_MAX_MM,
        TAPER_MIN_DEG,
        TAPER_MAX_DEG,
    )
    assert callable(check_sprue_bushing_match)
    assert R_EXCESS_MIN_MM == pytest.approx(0.5)
    assert R_EXCESS_MAX_MM == pytest.approx(1.0)
    assert TAPER_MIN_DEG == pytest.approx(1.5)
    assert TAPER_MAX_DEG == pytest.approx(3.0)


# ---------------------------------------------------------------------------
# 33. Small-nozzle case: nozzle r=8.5, sprue R=9.3 (+0.8 mm): compliant
# ---------------------------------------------------------------------------

def test_small_nozzle_compliant():
    """Small nozzle r=8.5 mm, sprue R=9.3 mm (+0.8 mm within [+0.5,+1.0]): compliant."""
    sprue = SprueBushingSpec(
        nozzle_radius_R_mm=9.3,
        sprue_orifice_diameter_O_mm=3.5,
        total_length_mm=50.0,
        taper_per_side_deg=2.0,
    )
    nozzle = MachineNozzleSpec(
        nozzle_tip_radius_mm=8.5,
        nozzle_tip_orifice_diameter_mm=3.0,
    )
    report = check_sprue_bushing_match(sprue, nozzle)
    assert report.R_compliant is True
    assert report.O_compliant is True
    assert report.taper_compliant is True


# ---------------------------------------------------------------------------
# 34. Orifice just below lower bound (0.49 mm excess): not compliant
# ---------------------------------------------------------------------------

def test_O_just_below_lower_bound_not_compliant():
    """Sprue O = nozzle O + 0.49 mm < 0.5 mm minimum → O_compliant=False."""
    sprue = _standard_sprue(R_mm=12.7, O_mm=4.49, taper_deg=2.0)
    nozzle = _standard_nozzle(r_mm=12.0, O_mm=4.0)
    report = check_sprue_bushing_match(sprue, nozzle)
    assert report.O_compliant is False
    assert report.O_mismatch_mm == pytest.approx(0.49)
