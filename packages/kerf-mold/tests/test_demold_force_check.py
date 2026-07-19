"""
Tests for kerf_mold.demold_force_check
=======================================
Covers demolding force estimation, ejector pin count, input validation,
edge cases, and LLM tool dispatch.

Formula under test (Beaumont 2007 §9.3 cavity-ejection, Menges 2001 §7.4):
  F = μ · σ_h · A_contact · cosα / (cosα + μ · sinα)

References:
  Beaumont J.P. Runner and Gating Design Handbook, 2nd ed., Hanser 2007, §9.3.
  Menges G., Michaeli W., Mohren P. How to Make Injection Molds, 3rd ed.,
    Hanser 2001, §7.4 + Table 7.6.
"""

import asyncio
import json
import math

import pytest

from kerf_mold.demold_force_check import (
    FRICTION_COEFF,
    SHRINKAGE_STRESS_MPA,
    DemoldForceReport,
    MoldedPartSpec,
    compute_demold_force,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _expected_force(mu: float, sigma_h: float, area_cm2: float, alpha_deg: float) -> float:
    """Reference implementation of the cavity-ejection formula."""
    A_mm2 = area_cm2 * 100.0  # cm² → mm²
    a = math.radians(alpha_deg)
    c, s = math.cos(a), math.sin(a)
    return mu * sigma_h * A_mm2 * c / (c + mu * s)


# ---------------------------------------------------------------------------
# 1. ABS, 100 cm², 1°, SPI_B1 — baseline case (Beaumont §9.3 reference)
# ---------------------------------------------------------------------------

def test_abs_100cm2_1deg_spi_b1_force():
    spec = MoldedPartSpec(
        polymer_grade="ABS",
        contact_area_cm2=100.0,
        draft_angle_deg=1.0,
        mold_steel_finish_class="SPI_B1",
    )
    report = compute_demold_force(spec)
    expected = _expected_force(0.25, 4.0, 100.0, 1.0)
    assert report.demold_force_N == pytest.approx(expected, rel=1e-4)
    assert report.demold_force_N == pytest.approx(9956.55, abs=1.0)


def test_abs_100cm2_1deg_spi_b1_pin_count():
    spec = MoldedPartSpec(
        polymer_grade="ABS",
        contact_area_cm2=100.0,
        draft_angle_deg=1.0,
        mold_steel_finish_class="SPI_B1",
    )
    report = compute_demold_force(spec, single_pin_capacity_N=2500.0)
    # F ≈ 9956.6 N → ceil(9956.6 / 2500) = 4
    assert report.ejector_pin_count_required == 4


# ---------------------------------------------------------------------------
# 2. Increased draft angle → lower force
# ---------------------------------------------------------------------------

def test_increased_draft_angle_lowers_force():
    """Larger draft (relief) angle reduces ejection force."""
    def _f(alpha):
        spec = MoldedPartSpec("ABS", 100.0, alpha, "SPI_B1")
        return compute_demold_force(spec).demold_force_N

    f1 = _f(1.0)
    f3 = _f(3.0)
    f5 = _f(5.0)
    f10 = _f(10.0)

    assert f1 > f3, "Force should decrease as draft angle increases 1→3°"
    assert f3 > f5, "Force should decrease as draft angle increases 3→5°"
    assert f5 > f10, "Force should decrease as draft angle increases 5→10°"


# ---------------------------------------------------------------------------
# 3. Polished finish (SPI_A1) → lower force than textured (SPI_D1)
# ---------------------------------------------------------------------------

def test_polished_finish_lower_force_than_textured():
    """SPI_A1 (μ=0.15) gives lower ejection force than SPI_D1 (μ=0.40)."""
    spec_a1 = MoldedPartSpec("ABS", 100.0, 1.0, "SPI_A1")
    spec_d1 = MoldedPartSpec("ABS", 100.0, 1.0, "SPI_D1")

    f_a1 = compute_demold_force(spec_a1).demold_force_N
    f_d1 = compute_demold_force(spec_d1).demold_force_N

    assert f_a1 < f_d1, (
        f"SPI_A1 force {f_a1:.1f} N should be less than SPI_D1 force {f_d1:.1f} N"
    )


# ---------------------------------------------------------------------------
# 4. Finish class ordering: A1 < A2 < B1 < C1 < D1
# ---------------------------------------------------------------------------

def test_friction_coeff_ordering_by_finish():
    """Friction and force increase monotonically from polished to textured."""
    classes = ["SPI_A1", "SPI_A2", "SPI_B1", "SPI_C1", "SPI_D1"]
    forces = []
    for cls in classes:
        spec = MoldedPartSpec("PP", 50.0, 2.0, cls)
        forces.append(compute_demold_force(spec).demold_force_N)

    for i in range(len(forces) - 1):
        assert forces[i] < forces[i + 1], (
            f"Force for {classes[i]} ({forces[i]:.1f} N) should be < "
            f"{classes[i+1]} ({forces[i+1]:.1f} N)"
        )


# ---------------------------------------------------------------------------
# 5. Edge: draft angle = 0° → maximum force, warning in caveat
# ---------------------------------------------------------------------------

def test_zero_draft_angle_gives_maximum_force_and_warning():
    """At α=0°, force = μ·σ_h·A (no taper relief); caveat flags it."""
    spec_zero = MoldedPartSpec("ABS", 100.0, 0.0, "SPI_B1")
    spec_small = MoldedPartSpec("ABS", 100.0, 0.5, "SPI_B1")

    r_zero = compute_demold_force(spec_zero)
    r_small = compute_demold_force(spec_small)

    # Zero draft gives maximum force
    assert r_zero.demold_force_N > r_small.demold_force_N

    # At alpha=0: F = mu * sigma * A exactly
    expected_zero = 0.25 * 4.0 * 100.0 * 100.0  # 10000 N
    assert r_zero.demold_force_N == pytest.approx(expected_zero, rel=1e-6)

    # Caveat should mention zero draft warning
    assert "0°" in r_zero.honest_caveat or "zero" in r_zero.honest_caveat.lower() or \
           "Draft angle = 0" in r_zero.honest_caveat


# ---------------------------------------------------------------------------
# 6. Shrinkage stress ordering: POM > PP > ABS > PA66 > PC
# ---------------------------------------------------------------------------

def test_higher_shrinkage_stress_higher_force():
    """Force scales with polymer shrinkage stress (Menges 2001 Table 7.6)."""
    # Stresses: POM=4.5, PP=5.0, ABS=4.0, PA66=3.5, PC=3.0
    polymers_by_stress = [
        ("PC",   3.0),
        ("PA66", 3.5),
        ("ABS",  4.0),
        ("POM",  4.5),
        ("PP",   5.0),
    ]
    forces = []
    for grade, _ in polymers_by_stress:
        spec = MoldedPartSpec(grade, 50.0, 1.0, "SPI_B1")
        forces.append(compute_demold_force(spec).demold_force_N)

    for i in range(len(forces) - 1):
        assert forces[i] < forces[i + 1], (
            f"Force for {polymers_by_stress[i][0]} should be < "
            f"{polymers_by_stress[i+1][0]}"
        )


# ---------------------------------------------------------------------------
# 7. Force scales linearly with contact area
# ---------------------------------------------------------------------------

def test_force_linear_in_contact_area():
    """Doubling the contact area doubles the ejection force."""
    spec1 = MoldedPartSpec("ABS", 50.0, 1.0, "SPI_B1")
    spec2 = MoldedPartSpec("ABS", 100.0, 1.0, "SPI_B1")
    f1 = compute_demold_force(spec1).demold_force_N
    f2 = compute_demold_force(spec2).demold_force_N
    assert f2 == pytest.approx(2.0 * f1, rel=1e-6)


# ---------------------------------------------------------------------------
# 8. DemoldForceReport fields are correctly populated
# ---------------------------------------------------------------------------

def test_report_fields_populated():
    """All DemoldForceReport fields are populated with correct values."""
    spec = MoldedPartSpec("PC", 80.0, 2.0, "SPI_A2")
    report = compute_demold_force(spec, single_pin_capacity_N=3000.0)

    assert report.friction_coeff_used == pytest.approx(0.18)
    assert report.polymer_shrinkage_stress_MPa == pytest.approx(3.0)
    assert report.contact_pressure_MPa == pytest.approx(3.0)
    assert report.demold_force_N > 0.0
    assert report.ejector_pin_count_required >= 1
    assert len(report.honest_caveat) > 20


# ---------------------------------------------------------------------------
# 9. Ejector pin count rounds up correctly
# ---------------------------------------------------------------------------

def test_ejector_pin_count_ceiling():
    """Pin count is always ceil(F / capacity)."""
    # Use PP, SPI_D1, large area to get a known large force
    spec = MoldedPartSpec("PP", 200.0, 1.0, "SPI_D1")
    report = compute_demold_force(spec, single_pin_capacity_N=2500.0)
    expected_count = math.ceil(report.demold_force_N / 2500.0)
    assert report.ejector_pin_count_required == expected_count


def test_single_pin_when_force_small():
    """Minimum pin count is 1 even if force is tiny."""
    spec = MoldedPartSpec("PC", 1.0, 10.0, "SPI_A1")
    report = compute_demold_force(spec, single_pin_capacity_N=100000.0)
    assert report.ejector_pin_count_required >= 1


# ---------------------------------------------------------------------------
# 10. Invalid polymer grade raises ValueError
# ---------------------------------------------------------------------------

def test_invalid_polymer_grade_raises():
    with pytest.raises(ValueError, match="Unknown polymer_grade"):
        MoldedPartSpec(
            polymer_grade="HDPE",
            contact_area_cm2=100.0,
            draft_angle_deg=1.0,
            mold_steel_finish_class="SPI_B1",
        )


# ---------------------------------------------------------------------------
# 11. Invalid finish class raises ValueError
# ---------------------------------------------------------------------------

def test_invalid_finish_class_raises():
    with pytest.raises(ValueError, match="Unknown mold_steel_finish_class"):
        MoldedPartSpec(
            polymer_grade="ABS",
            contact_area_cm2=100.0,
            draft_angle_deg=1.0,
            mold_steel_finish_class="SPI_E1",
        )


# ---------------------------------------------------------------------------
# 12. Non-positive contact area raises ValueError
# ---------------------------------------------------------------------------

def test_zero_contact_area_raises():
    with pytest.raises(ValueError, match="contact_area_cm2 must be > 0"):
        MoldedPartSpec(
            polymer_grade="ABS",
            contact_area_cm2=0.0,
            draft_angle_deg=1.0,
            mold_steel_finish_class="SPI_B1",
        )


def test_negative_contact_area_raises():
    with pytest.raises(ValueError, match="contact_area_cm2 must be > 0"):
        MoldedPartSpec(
            polymer_grade="ABS",
            contact_area_cm2=-10.0,
            draft_angle_deg=1.0,
            mold_steel_finish_class="SPI_B1",
        )


# ---------------------------------------------------------------------------
# 13. Negative draft angle raises ValueError
# ---------------------------------------------------------------------------

def test_negative_draft_angle_raises():
    with pytest.raises(ValueError, match="draft_angle_deg must be >= 0"):
        MoldedPartSpec(
            polymer_grade="ABS",
            contact_area_cm2=100.0,
            draft_angle_deg=-1.0,
            mold_steel_finish_class="SPI_B1",
        )


# ---------------------------------------------------------------------------
# 14. Honest caveat mentions key references and polymer
# ---------------------------------------------------------------------------

def test_honest_caveat_content():
    spec = MoldedPartSpec("PA66", 60.0, 1.0, "SPI_C1")
    report = compute_demold_force(spec)
    assert "Beaumont" in report.honest_caveat
    assert "Menges" in report.honest_caveat
    assert "PA66" in report.honest_caveat
    assert "chemical adhesion" in report.honest_caveat.lower() or \
           "Chemical adhesion" in report.honest_caveat


# ---------------------------------------------------------------------------
# 15. Shrinkage stress DB matches Menges 2001 Table 7.6 values
# ---------------------------------------------------------------------------

def test_shrinkage_stress_db_values():
    assert SHRINKAGE_STRESS_MPA["ABS"] == pytest.approx(4.0)
    assert SHRINKAGE_STRESS_MPA["PC"] == pytest.approx(3.0)
    assert SHRINKAGE_STRESS_MPA["PP"] == pytest.approx(5.0)
    assert SHRINKAGE_STRESS_MPA["PA66"] == pytest.approx(3.5)
    assert SHRINKAGE_STRESS_MPA["POM"] == pytest.approx(4.5)


# ---------------------------------------------------------------------------
# 16. Friction coefficient DB matches expected values
# ---------------------------------------------------------------------------

def test_friction_coeff_db_values():
    assert FRICTION_COEFF["SPI_A1"] == pytest.approx(0.15)
    assert FRICTION_COEFF["SPI_A2"] == pytest.approx(0.18)
    assert FRICTION_COEFF["SPI_B1"] == pytest.approx(0.25)
    assert FRICTION_COEFF["SPI_C1"] == pytest.approx(0.30)
    assert FRICTION_COEFF["SPI_D1"] == pytest.approx(0.40)


# ---------------------------------------------------------------------------
# 17. LLM tool dispatch (mold_compute_demold_force)
# ---------------------------------------------------------------------------

class _Ctx:
    pass


CTX = _Ctx()


def _run(coro):
    return asyncio.run(coro)


def test_tool_dispatch_basic():
    from kerf_mold.demold_force_check_tool import run_mold_compute_demold_force
    result = json.loads(_run(run_mold_compute_demold_force({
        "polymer_grade": "ABS",
        "contact_area_cm2": 100.0,
        "draft_angle_deg": 1.0,
        "mold_steel_finish_class": "SPI_B1",
    }, CTX)))
    assert result.get("ok") is True
    assert "demold_force_N" in result
    assert result["demold_force_N"] == pytest.approx(9956.55, abs=1.0)
    assert result["friction_coeff_used"] == pytest.approx(0.25)
    assert result["ejector_pin_count_required"] == 4


def test_tool_dispatch_missing_polymer_grade():
    from kerf_mold.demold_force_check_tool import run_mold_compute_demold_force
    result = json.loads(_run(run_mold_compute_demold_force({
        "contact_area_cm2": 100.0,
        "draft_angle_deg": 1.0,
        "mold_steel_finish_class": "SPI_B1",
    }, CTX)))
    assert "error" in result
    assert result.get("code") == "BAD_ARGS"


def test_tool_dispatch_invalid_finish_class():
    from kerf_mold.demold_force_check_tool import run_mold_compute_demold_force
    result = json.loads(_run(run_mold_compute_demold_force({
        "polymer_grade": "ABS",
        "contact_area_cm2": 100.0,
        "draft_angle_deg": 1.0,
        "mold_steel_finish_class": "SPI_X9",
    }, CTX)))
    assert "error" in result
    assert result.get("code") == "BAD_ARGS"


# ---------------------------------------------------------------------------
# 18. Tool spec name and fields
# ---------------------------------------------------------------------------

def test_tool_spec_name():
    from kerf_mold.demold_force_check_tool import mold_compute_demold_force_spec
    assert mold_compute_demold_force_spec.name == "mold_compute_demold_force"


def test_tool_spec_has_required_fields():
    from kerf_mold.demold_force_check_tool import mold_compute_demold_force_spec
    required = mold_compute_demold_force_spec.input_schema.get("required", [])
    assert "polymer_grade" in required
    assert "contact_area_cm2" in required
    assert "draft_angle_deg" in required
    assert "mold_steel_finish_class" in required


# ---------------------------------------------------------------------------
# 19. Plugin registers mold_compute_demold_force
# ---------------------------------------------------------------------------

def test_plugin_registers_demold_force_tool():
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
    assert "mold_compute_demold_force" in ctx.tools.registered, (
        "mold_compute_demold_force should be registered in the plugin"
    )


# ---------------------------------------------------------------------------
# 20. Re-export from kerf_mold.__init__
# ---------------------------------------------------------------------------

def test_init_exports():
    from kerf_mold import (
        MoldedPartSpec,
        DemoldForceReport,
        SHRINKAGE_STRESS_MPA,
        FRICTION_COEFF,
        compute_demold_force,
    )
    assert MoldedPartSpec is not None
    assert DemoldForceReport is not None
    assert "ABS" in SHRINKAGE_STRESS_MPA
    assert "SPI_B1" in FRICTION_COEFF
    assert callable(compute_demold_force)


# ---------------------------------------------------------------------------
# 21. Custom pin capacity changes pin count
# ---------------------------------------------------------------------------

def test_custom_pin_capacity_changes_count():
    spec = MoldedPartSpec("ABS", 100.0, 1.0, "SPI_B1")
    r_small = compute_demold_force(spec, single_pin_capacity_N=1000.0)
    r_large = compute_demold_force(spec, single_pin_capacity_N=5000.0)
    assert r_small.ejector_pin_count_required > r_large.ejector_pin_count_required


# ---------------------------------------------------------------------------
# 22. POM has higher force than PC (sigma_h: 4.5 vs 3.0) at same conditions
# ---------------------------------------------------------------------------

def test_pom_higher_force_than_pc():
    spec_pom = MoldedPartSpec("POM", 100.0, 1.0, "SPI_B1")
    spec_pc = MoldedPartSpec("PC", 100.0, 1.0, "SPI_B1")
    f_pom = compute_demold_force(spec_pom).demold_force_N
    f_pc = compute_demold_force(spec_pc).demold_force_N
    assert f_pom > f_pc, f"POM force {f_pom:.1f} should exceed PC force {f_pc:.1f}"
