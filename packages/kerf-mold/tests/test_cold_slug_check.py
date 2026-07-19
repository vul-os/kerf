"""
Tests for kerf_mold.cold_slug_check
=====================================
Covers compliant, too-small, too-large, mixed multi-junction, edge cases,
LLM tool dispatch, plugin registration, and __init__ re-exports.

Beaumont 2007 §6.7 rules:
  slug well diameter = 1.5 × runner diameter  (±20 % → 1.2×–1.8×)
  slug well depth    = 2.0 × runner diameter  (±20 % → 1.6×–2.4×)

References:
  Beaumont J.P. Runner and Gating Design Handbook, 2nd ed., Hanser 2007, §6.7.
  Menges G., Michaeli W., Mohren P. How to Make Injection Molds, 3rd ed.,
    Hanser 2001, §6.5.
"""

from __future__ import annotations

import asyncio
import json

import pytest

from kerf_mold.cold_slug_check import (
    ColdSlugReport,
    RunnerJunctionSpec,
    check_cold_slug_design,
    DIAMETER_RATIO,
    DEPTH_RATIO,
    TOLERANCE,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run(coro):
    return asyncio.run(coro)


class _Ctx:
    pass


CTX = _Ctx()


# ---------------------------------------------------------------------------
# 1. 6 mm runner, 9 mm dia, 12 mm deep → compliant (exact 1.5× and 2×)
# ---------------------------------------------------------------------------

def test_6mm_runner_9mm_dia_12mm_depth_compliant():
    """Runner 6 mm, slug well 9 mm dia, 12 mm deep → exactly 1.5× and 2× → compliant."""
    spec = RunnerJunctionSpec(
        junction_id="J1",
        runner_diameter_mm=6.0,
        slug_well_diameter_mm=9.0,   # 1.5 × 6 = 9
        slug_well_depth_mm=12.0,     # 2.0 × 6 = 12
        polymer_grade="ABS",
    )
    report = check_cold_slug_design([spec])
    result = report.junction_results[0]
    assert result["slug_well_compliant"] is True
    assert result["diameter_compliant"] is True
    assert result["depth_compliant"] is True
    assert result["recommended_diameter_mm"] == pytest.approx(9.0)
    assert result["recommended_depth_mm"] == pytest.approx(12.0)


# ---------------------------------------------------------------------------
# 2. Slug well diameter = runner diameter (too small)
# ---------------------------------------------------------------------------

def test_slug_well_diameter_equals_runner_too_small():
    """Slug well diameter 6 mm = runner 6 mm → below 1.2× minimum → not compliant."""
    spec = RunnerJunctionSpec(
        junction_id="J2",
        runner_diameter_mm=6.0,
        slug_well_diameter_mm=6.0,   # only 1.0× — too small
        slug_well_depth_mm=12.0,     # 2.0× OK
        polymer_grade="PP",
    )
    report = check_cold_slug_design([spec])
    result = report.junction_results[0]
    assert result["slug_well_compliant"] is False
    assert result["diameter_compliant"] is False
    assert result["depth_compliant"] is True


# ---------------------------------------------------------------------------
# 3. Slug well diameter 20 mm (runner 6 mm) → too large
# ---------------------------------------------------------------------------

def test_slug_well_diameter_too_large():
    """Slug well diameter 20 mm on 6 mm runner → 3.33× >> 1.8× max → not compliant."""
    spec = RunnerJunctionSpec(
        junction_id="J3",
        runner_diameter_mm=6.0,
        slug_well_diameter_mm=20.0,
        slug_well_depth_mm=12.0,
        polymer_grade="PC",
    )
    report = check_cold_slug_design([spec])
    result = report.junction_results[0]
    assert result["slug_well_compliant"] is False
    assert result["diameter_compliant"] is False
    # 12 mm depth is still correct (2.0×)
    assert result["depth_compliant"] is True


# ---------------------------------------------------------------------------
# 4. Multi-junction mixed compliance
# ---------------------------------------------------------------------------

def test_multi_junction_mixed_compliance():
    """Four junctions: 2 compliant, 2 not — report reflects accurate counts."""
    junctions = [
        RunnerJunctionSpec("J1", 6.0, 9.0, 12.0, "ABS"),    # compliant
        RunnerJunctionSpec("J2", 6.0, 6.0, 12.0, "PP"),     # diam too small
        RunnerJunctionSpec("J3", 8.0, 12.0, 16.0, "PA66"),  # compliant (1.5×, 2×)
        RunnerJunctionSpec("J4", 8.0, 12.0, 5.0, "POM"),    # depth too shallow
    ]
    report = check_cold_slug_design(junctions)
    assert report.total_junctions == 4
    assert report.compliant_count == 2

    ids = {r["junction_id"]: r for r in report.junction_results}
    assert ids["J1"]["slug_well_compliant"] is True
    assert ids["J2"]["slug_well_compliant"] is False
    assert ids["J3"]["slug_well_compliant"] is True
    assert ids["J4"]["slug_well_compliant"] is False


# ---------------------------------------------------------------------------
# 5. Zero runner diameter → ValueError
# ---------------------------------------------------------------------------

def test_zero_runner_diameter_raises():
    """RunnerJunctionSpec with runner_diameter_mm=0 → ValueError."""
    with pytest.raises(ValueError, match="runner_diameter_mm must be > 0"):
        RunnerJunctionSpec(
            junction_id="J0",
            runner_diameter_mm=0.0,
            slug_well_diameter_mm=9.0,
            slug_well_depth_mm=12.0,
            polymer_grade="ABS",
        )


# ---------------------------------------------------------------------------
# 6. Negative runner diameter → ValueError
# ---------------------------------------------------------------------------

def test_negative_runner_diameter_raises():
    """RunnerJunctionSpec with runner_diameter_mm=-1 → ValueError."""
    with pytest.raises(ValueError, match="runner_diameter_mm must be > 0"):
        RunnerJunctionSpec(
            junction_id="J-neg",
            runner_diameter_mm=-1.0,
            slug_well_diameter_mm=9.0,
            slug_well_depth_mm=12.0,
            polymer_grade="ABS",
        )


# ---------------------------------------------------------------------------
# 7. Slug well exactly at lower diameter bound (1.2×) → compliant
# ---------------------------------------------------------------------------

def test_diameter_at_lower_tolerance_bound_compliant():
    """Slug well diameter = 1.2 × runner → lower tolerance boundary → compliant."""
    d_runner = 8.0
    diam_min = DIAMETER_RATIO * d_runner * (1.0 - TOLERANCE)  # 1.5*8*0.8 = 9.6
    depth_ok = DEPTH_RATIO * d_runner  # 16.0

    spec = RunnerJunctionSpec("J-lower", d_runner, diam_min, depth_ok, "ABS")
    report = check_cold_slug_design([spec])
    result = report.junction_results[0]
    assert result["diameter_compliant"] is True
    assert result["slug_well_compliant"] is True


# ---------------------------------------------------------------------------
# 8. Slug well exactly at upper diameter bound (1.8×) → compliant
# ---------------------------------------------------------------------------

def test_diameter_at_upper_tolerance_bound_compliant():
    """Slug well diameter = 1.8 × runner → upper tolerance boundary → compliant."""
    d_runner = 8.0
    diam_max = DIAMETER_RATIO * d_runner * (1.0 + TOLERANCE)  # 1.5*8*1.2 = 14.4
    depth_ok = DEPTH_RATIO * d_runner  # 16.0

    spec = RunnerJunctionSpec("J-upper", d_runner, diam_max, depth_ok, "ABS")
    report = check_cold_slug_design([spec])
    result = report.junction_results[0]
    assert result["diameter_compliant"] is True
    assert result["slug_well_compliant"] is True


# ---------------------------------------------------------------------------
# 9. Depth at lower bound (1.6×) → compliant
# ---------------------------------------------------------------------------

def test_depth_at_lower_tolerance_bound_compliant():
    """Slug well depth = 1.6 × runner → lower tolerance boundary → compliant."""
    d_runner = 10.0
    diam_ok = DIAMETER_RATIO * d_runner   # 15.0
    depth_min = DEPTH_RATIO * d_runner * (1.0 - TOLERANCE)  # 2.0*10*0.8 = 16.0

    spec = RunnerJunctionSpec("J-depth-lower", d_runner, diam_ok, depth_min, "PP")
    report = check_cold_slug_design([spec])
    assert report.junction_results[0]["depth_compliant"] is True
    assert report.junction_results[0]["slug_well_compliant"] is True


# ---------------------------------------------------------------------------
# 10. Depth just below lower bound → not compliant
# ---------------------------------------------------------------------------

def test_depth_just_below_lower_bound_not_compliant():
    """Depth just below 1.6 × runner → too shallow → not compliant."""
    d_runner = 10.0
    diam_ok = DIAMETER_RATIO * d_runner   # 15.0
    too_shallow = DEPTH_RATIO * d_runner * (1.0 - TOLERANCE) - 0.01  # 15.99

    spec = RunnerJunctionSpec("J-depth-fail", d_runner, diam_ok, too_shallow, "PP")
    report = check_cold_slug_design([spec])
    result = report.junction_results[0]
    assert result["depth_compliant"] is False
    assert result["slug_well_compliant"] is False
    assert "too shallow" in result["reason"]


# ---------------------------------------------------------------------------
# 11. Depth too deep (> 2.4×) → not compliant
# ---------------------------------------------------------------------------

def test_depth_too_deep_not_compliant():
    """Slug well depth = 3.0 × runner → exceeds 2.4× upper bound → not compliant."""
    d_runner = 6.0
    diam_ok = DIAMETER_RATIO * d_runner   # 9.0
    too_deep = DEPTH_RATIO * d_runner * (1.0 + TOLERANCE) + 1.0  # > 14.4

    spec = RunnerJunctionSpec("J-deep", d_runner, diam_ok, too_deep, "ABS")
    report = check_cold_slug_design([spec])
    result = report.junction_results[0]
    assert result["depth_compliant"] is False
    assert "too deep" in result["reason"]


# ---------------------------------------------------------------------------
# 12. Recommended values computed correctly
# ---------------------------------------------------------------------------

def test_recommended_values_computed():
    """Recommended diameter = 1.5× and depth = 2.0× runner diameter."""
    spec = RunnerJunctionSpec("J-rec", 10.0, 15.0, 20.0, "ABS")
    report = check_cold_slug_design([spec])
    result = report.junction_results[0]
    assert result["recommended_diameter_mm"] == pytest.approx(15.0)
    assert result["recommended_depth_mm"] == pytest.approx(20.0)
    assert result["diameter_min_mm"] == pytest.approx(12.0)
    assert result["diameter_max_mm"] == pytest.approx(18.0)
    assert result["depth_min_mm"] == pytest.approx(16.0)
    assert result["depth_max_mm"] == pytest.approx(24.0)


# ---------------------------------------------------------------------------
# 13. Empty junctions list → ValueError
# ---------------------------------------------------------------------------

def test_empty_junctions_raises():
    with pytest.raises(ValueError, match="at least one"):
        check_cold_slug_design([])


# ---------------------------------------------------------------------------
# 14. Honest caveat mentions key references
# ---------------------------------------------------------------------------

def test_honest_caveat_references():
    """Honest caveat must cite Beaumont, Menges, and mold trial."""
    spec = RunnerJunctionSpec("J1", 6.0, 9.0, 12.0, "ABS")
    report = check_cold_slug_design([spec])
    assert "Beaumont" in report.honest_caveat
    assert "Menges" in report.honest_caveat
    assert "mold trial" in report.honest_caveat.lower()


# ---------------------------------------------------------------------------
# 15. Both non-compliant dimensions described in reason
# ---------------------------------------------------------------------------

def test_both_noncompliant_reason_mentions_both():
    """When both diameter and depth fail, reason string mentions both issues."""
    spec = RunnerJunctionSpec("J-both", 6.0, 5.0, 5.0, "PP")  # too small on both
    report = check_cold_slug_design([spec])
    result = report.junction_results[0]
    assert result["slug_well_compliant"] is False
    assert result["diameter_compliant"] is False
    assert result["depth_compliant"] is False
    # Reason should mention both diameter and depth issues
    reason = result["reason"].lower()
    assert "diameter" in reason
    assert "depth" in reason


# ---------------------------------------------------------------------------
# 16. Zero slug_well_diameter_mm → ValueError
# ---------------------------------------------------------------------------

def test_zero_slug_well_diameter_raises():
    with pytest.raises(ValueError, match="slug_well_diameter_mm must be > 0"):
        RunnerJunctionSpec("J-zero-d", 6.0, 0.0, 12.0, "ABS")


# ---------------------------------------------------------------------------
# 17. Zero slug_well_depth_mm → ValueError
# ---------------------------------------------------------------------------

def test_zero_slug_well_depth_raises():
    with pytest.raises(ValueError, match="slug_well_depth_mm must be > 0"):
        RunnerJunctionSpec("J-zero-depth", 6.0, 9.0, 0.0, "ABS")


# ---------------------------------------------------------------------------
# 18. Single compliant junction report shape
# ---------------------------------------------------------------------------

def test_single_junction_report_shape():
    """ColdSlugReport from a single junction has correct shape and fields."""
    spec = RunnerJunctionSpec("J1", 6.0, 9.0, 12.0, "PP")
    report = check_cold_slug_design([spec])
    assert isinstance(report, ColdSlugReport)
    assert report.total_junctions == 1
    assert report.compliant_count == 1
    assert len(report.junction_results) == 1
    result = report.junction_results[0]
    assert "junction_id" in result
    assert "slug_well_compliant" in result
    assert "recommended_diameter_mm" in result
    assert "recommended_depth_mm" in result
    assert "reason" in result


# ---------------------------------------------------------------------------
# 19. LLM tool dispatch — basic compliant case
# ---------------------------------------------------------------------------

def test_tool_dispatch_compliant():
    from kerf_mold.cold_slug_check_tool import run_mold_check_cold_slug_design
    result = json.loads(_run(run_mold_check_cold_slug_design({
        "junctions": [
            {
                "junction_id": "J1",
                "runner_diameter_mm": 6.0,
                "slug_well_diameter_mm": 9.0,
                "slug_well_depth_mm": 12.0,
                "polymer_grade": "ABS",
            }
        ]
    }, CTX)))
    assert result.get("ok") is True
    assert result["total_junctions"] == 1
    assert result["compliant_count"] == 1
    assert result["all_compliant"] is True
    jr = result["junction_results"][0]
    assert jr["slug_well_compliant"] is True


# ---------------------------------------------------------------------------
# 20. LLM tool dispatch — diameter too small
# ---------------------------------------------------------------------------

def test_tool_dispatch_diameter_too_small():
    from kerf_mold.cold_slug_check_tool import run_mold_check_cold_slug_design
    result = json.loads(_run(run_mold_check_cold_slug_design({
        "junctions": [
            {
                "junction_id": "J1",
                "runner_diameter_mm": 6.0,
                "slug_well_diameter_mm": 6.0,  # = runner, too small
                "slug_well_depth_mm": 12.0,
                "polymer_grade": "PP",
            }
        ]
    }, CTX)))
    assert result.get("ok") is True
    jr = result["junction_results"][0]
    assert jr["slug_well_compliant"] is False
    assert jr["diameter_compliant"] is False


# ---------------------------------------------------------------------------
# 21. LLM tool dispatch — missing junctions → BAD_ARGS
# ---------------------------------------------------------------------------

def test_tool_dispatch_missing_junctions():
    from kerf_mold.cold_slug_check_tool import run_mold_check_cold_slug_design
    result = json.loads(_run(run_mold_check_cold_slug_design({}, CTX)))
    assert "error" in result
    assert result.get("code") == "BAD_ARGS"


# ---------------------------------------------------------------------------
# 22. LLM tool dispatch — empty junctions list → BAD_ARGS
# ---------------------------------------------------------------------------

def test_tool_dispatch_empty_junctions():
    from kerf_mold.cold_slug_check_tool import run_mold_check_cold_slug_design
    result = json.loads(_run(run_mold_check_cold_slug_design(
        {"junctions": []}, CTX
    )))
    assert "error" in result
    assert result.get("code") == "BAD_ARGS"


# ---------------------------------------------------------------------------
# 23. LLM tool dispatch — non-numeric runner_diameter_mm → BAD_ARGS
# ---------------------------------------------------------------------------

def test_tool_dispatch_non_numeric_runner_diameter():
    from kerf_mold.cold_slug_check_tool import run_mold_check_cold_slug_design
    result = json.loads(_run(run_mold_check_cold_slug_design({
        "junctions": [
            {
                "junction_id": "J1",
                "runner_diameter_mm": "six",
                "slug_well_diameter_mm": 9.0,
                "slug_well_depth_mm": 12.0,
                "polymer_grade": "ABS",
            }
        ]
    }, CTX)))
    assert "error" in result
    assert result.get("code") == "BAD_ARGS"


# ---------------------------------------------------------------------------
# 24. LLM tool dispatch — zero runner_diameter_mm → BAD_ARGS
# ---------------------------------------------------------------------------

def test_tool_dispatch_zero_runner_diameter():
    from kerf_mold.cold_slug_check_tool import run_mold_check_cold_slug_design
    result = json.loads(_run(run_mold_check_cold_slug_design({
        "junctions": [
            {
                "junction_id": "J1",
                "runner_diameter_mm": 0.0,
                "slug_well_diameter_mm": 9.0,
                "slug_well_depth_mm": 12.0,
                "polymer_grade": "ABS",
            }
        ]
    }, CTX)))
    assert "error" in result
    assert result.get("code") == "BAD_ARGS"


# ---------------------------------------------------------------------------
# 25. Tool spec name and required fields
# ---------------------------------------------------------------------------

def test_tool_spec_name():
    from kerf_mold.cold_slug_check_tool import mold_check_cold_slug_design_spec
    assert mold_check_cold_slug_design_spec.name == "mold_check_cold_slug_design"


def test_tool_spec_required_fields():
    from kerf_mold.cold_slug_check_tool import mold_check_cold_slug_design_spec
    required = mold_check_cold_slug_design_spec.input_schema.get("required", [])
    assert "junctions" in required


# ---------------------------------------------------------------------------
# 26. Plugin registers mold_check_cold_slug_design
# ---------------------------------------------------------------------------

def test_plugin_registers_cold_slug_tool():
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
    assert "mold_check_cold_slug_design" in ctx.tools.registered, (
        "mold_check_cold_slug_design should be registered in the plugin"
    )


# ---------------------------------------------------------------------------
# 27. Re-export from kerf_mold.__init__
# ---------------------------------------------------------------------------

def test_init_exports():
    from kerf_mold import (
        RunnerJunctionSpec,
        ColdSlugReport,
        check_cold_slug_design,
    )
    assert RunnerJunctionSpec is not None
    assert ColdSlugReport is not None
    assert callable(check_cold_slug_design)


# ---------------------------------------------------------------------------
# 28. Multi-junction all compliant
# ---------------------------------------------------------------------------

def test_multi_junction_all_compliant():
    """All junctions compliant → compliant_count == total_junctions."""
    junctions = [
        RunnerJunctionSpec("J1", 6.0, 9.0, 12.0, "ABS"),
        RunnerJunctionSpec("J2", 8.0, 12.0, 16.0, "PP"),
        RunnerJunctionSpec("J3", 10.0, 15.0, 20.0, "PC"),
    ]
    report = check_cold_slug_design(junctions)
    assert report.total_junctions == 3
    assert report.compliant_count == 3
    for r in report.junction_results:
        assert r["slug_well_compliant"] is True


# ---------------------------------------------------------------------------
# 29. Multi-junction all non-compliant
# ---------------------------------------------------------------------------

def test_multi_junction_all_noncompliant():
    """All junctions non-compliant → compliant_count == 0."""
    junctions = [
        RunnerJunctionSpec("J1", 6.0, 4.0, 6.0, "ABS"),   # both too small
        RunnerJunctionSpec("J2", 6.0, 25.0, 30.0, "PP"),  # both too large
    ]
    report = check_cold_slug_design(junctions)
    assert report.compliant_count == 0


# ---------------------------------------------------------------------------
# 30. Diameter non-compliant reason includes "too small" or "too large"
# ---------------------------------------------------------------------------

def test_diameter_too_small_reason():
    """Reason must contain 'too small' when diameter < 1.2× runner."""
    spec = RunnerJunctionSpec("J1", 6.0, 4.0, 12.0, "ABS")
    report = check_cold_slug_design([spec])
    result = report.junction_results[0]
    assert "too small" in result["reason"]


def test_diameter_too_large_reason():
    """Reason must contain 'too large' when diameter > 1.8× runner."""
    spec = RunnerJunctionSpec("J1", 6.0, 25.0, 12.0, "ABS")
    report = check_cold_slug_design([spec])
    result = report.junction_results[0]
    assert "too large" in result["reason"]
