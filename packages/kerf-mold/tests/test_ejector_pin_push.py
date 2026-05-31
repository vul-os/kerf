"""
Tests for kerf_mold.ejector_pin_push
=====================================
Covers Euler buckling-force computation, demand-to-capacity ratio, diameter
recommendation, input validation, edge cases, and LLM tool dispatch.

Formula under test (SPI/ANSI B151.1 + Roark's 9e §15.2):
  F_cr = π² · E · I / (K · L)²
  I    = π · d⁴ / 64  (solid circular cross-section)
  E    = 200 000 N/mm²  (all tool-steel grades)

Reference hand calculations:
  8 mm pin, L=100 mm, K=1 (pinned-pinned):
    I    = π·8⁴/64 = π·4096/64 = 201.062 mm⁴
    F_cr = π²·200000·201.062/(1·100)² = 1 973 920 / 10 000 = 197 392 / ...
    Wait, let's be precise:
    I    = π·4096/64 = 64π = 201.0619... mm⁴
    F_cr = π²·200000·201.0619 / (100)²
         = 9.8696·200000·201.0619 / 10000
         = 9.8696·40212.38 / 10000 (missing factor)
    Actually step-by-step:
    F_cr = (π² × 200000 × 201.0619) / (1.0 × 100)²
         = (9.86960 × 200000 × 201.0619) / 10000
         = (9.86960 × 40 212 380) / 10000    ... no, 200000 × 201.0619 = 40 212 380
    Wait: 200000 × 201.0619 = 40 212 380 N·mm² ... that seems large.
    Let us be careful with units:
       F_cr [N] = π² · E[N/mm²] · I[mm⁴] / (K·L[mm])²
       F_cr = π² · 200000 · 201.062 / (1·100)²
            = 9.8696 · 200000 · 201.062 / 10000
            = 9.8696 · 4 021 240 / 10000
            Wait: 200000 × 201.062 = 40 212 400 N·mm²
            π² × 40 212 400 = 9.8696 × 40 212 400 = 396 891 000 N·mm²
            / (100)² = 396 891 000 / 10 000 = 39 689 N  ≈ 39 689 N
    Hmm, that is ~39 700 N, not 3970 N.
    Let me re-check the task spec:
      "I = π·8⁴/64 = 201 mm⁴; F_cr = π²·200000·201/(1·100)² = 3970 N"
    π²·200000·201 / 10000 = 9.8696 × 200000 × 201 / 10000
    = 9.8696 × 40 200 000 / 10000
    = 396 556 320 / 10000
    = 39 655 N, not 3970 N.
    The task spec appears to have a typo — the correct answer is ≈ 39 670 N.
    The "3970 N" figure is off by 10× (maybe they dropped a factor of 10
    somewhere). Our tests verify the correct formula.

    Independent check:
      d=8 mm, L=100 mm, K=1, E=200 GPa:
      r = d/4 = 2 mm  (radius of gyration for solid circle)
      KL/r = 100/2 = 50  → slender enough for Euler
      F_cr = π²·200000·(π·8⁴/64)/(100)²
      = π²·200000·64π / 10000
      = π³·200000·64/10000
      = 31.006·200000·64/10000
      = 31.006 × 1 280 000 / 10000
      = 39 687 808 / 10000
      = 39 688 N  ✓  (approximately 39 670–39 700 N)

References:
  SPI/ANSI B151.1; Roark's 9e §15.2.
"""

import asyncio
import json
import math

import pytest

from kerf_mold.ejector_pin_push import (
    EjectorPinPushReport,
    EjectorPinPushSpec,
    SPI_EJECTOR_PIN_DIAMETERS_MM,
    _E_TOOL_STEEL_N_MM2,
    _euler_buckling_force,
    _second_moment_of_area,
    compute_ejector_pin_push,
)


# ---------------------------------------------------------------------------
# Reference implementation
# ---------------------------------------------------------------------------

def _ref_I(d_mm: float) -> float:
    """I = π·d⁴/64 [mm⁴]."""
    return math.pi * d_mm ** 4 / 64.0


def _ref_Fcr(d_mm: float, L_mm: float, K: float,
              E: float = _E_TOOL_STEEL_N_MM2) -> float:
    """F_cr = π²·E·I/(K·L)² [N]."""
    I = _ref_I(d_mm)
    return (math.pi ** 2 * E * I) / (K * L_mm) ** 2


# ---------------------------------------------------------------------------
# 1. Second moment of area — formula I = π·d⁴/64
# ---------------------------------------------------------------------------

def test_second_moment_of_area_8mm():
    """I = π·8⁴/64 = π·4096/64 = 64π ≈ 201.062 mm⁴."""
    I = _second_moment_of_area(8.0)
    expected = math.pi * 8 ** 4 / 64
    assert I == pytest.approx(expected, rel=1e-9)
    assert I == pytest.approx(201.062, abs=0.01)


def test_second_moment_of_area_4mm():
    """I(4mm) = π·256/64 = 4π ≈ 12.566 mm⁴ — exactly 1/16 of I(8mm)."""
    I_8 = _second_moment_of_area(8.0)
    I_4 = _second_moment_of_area(4.0)
    assert I_4 == pytest.approx(I_8 / 16.0, rel=1e-9)


def test_second_moment_of_area_scales_with_d4():
    """I scales as d⁴: doubling d → 16× increase."""
    assert _second_moment_of_area(10.0) == pytest.approx(
        _second_moment_of_area(5.0) * 16.0, rel=1e-9
    )


# ---------------------------------------------------------------------------
# 2. Euler buckling force — 8 mm pin, L=100 mm, K=1 (pinned-pinned)
#    Reference: F_cr = π²·200000·(64π)/(100)² ≈ 39 688 N
# ---------------------------------------------------------------------------

def test_euler_8mm_100mm_pinned_pinned():
    """8 mm, L=100, K=1: F_cr ≈ 39 688 N (Roark's 9e §15.2 verification)."""
    F = _euler_buckling_force(8.0, 100.0, 1.0)
    expected = _ref_Fcr(8.0, 100.0, 1.0)
    assert F == pytest.approx(expected, rel=1e-9)
    # Numerical check: F_cr = π³ × 200000 × 64 / 10000
    F_approx = math.pi ** 3 * 200_000 * 64 / 10_000
    assert F == pytest.approx(F_approx, rel=1e-6)
    # Must be in the range ~39 600–39 800 N
    assert 39_600 < F < 39_800


def test_euler_8mm_100mm_compute_report():
    """compute_ejector_pin_push returns correct buckling_force_N for 8mm/100mm."""
    spec = EjectorPinPushSpec(
        pin_diameter_mm=8.0,
        pin_length_L_mm=100.0,
        pin_material="H13",
        end_condition_K=1.0,
        required_push_force_N=2000.0,
    )
    report = compute_ejector_pin_push(spec)
    assert report.buckling_force_N == pytest.approx(_ref_Fcr(8.0, 100.0, 1.0), rel=1e-5)
    assert report.adequate is True
    assert report.dcr < 1.0


# ---------------------------------------------------------------------------
# 3. Smaller diameter (4 mm) reduces F_cr by exactly 16×
# ---------------------------------------------------------------------------

def test_4mm_sixteen_times_weaker_than_8mm():
    """F_cr(4mm) = F_cr(8mm) / 16 at same L and K (I scales as d⁴)."""
    F_8 = _euler_buckling_force(8.0, 100.0, 1.0)
    F_4 = _euler_buckling_force(4.0, 100.0, 1.0)
    assert F_8 / F_4 == pytest.approx(16.0, rel=1e-9)


def test_smaller_diameter_lower_Fcr():
    """F_cr decreases monotonically as diameter decreases."""
    diameters = [10.0, 8.0, 6.0, 5.0, 4.0, 3.0, 2.0]
    forces = [_euler_buckling_force(d, 150.0, 1.0) for d in diameters]
    for i in range(len(forces) - 1):
        assert forces[i] > forces[i + 1], (
            f"F_cr should decrease with diameter: {diameters[i]} mm → "
            f"{diameters[i+1]} mm gave {forces[i]:.1f} → {forces[i+1]:.1f} N"
        )


# ---------------------------------------------------------------------------
# 4. Longer L reduces F_cr quadratically (F_cr ∝ 1/L²)
# ---------------------------------------------------------------------------

def test_longer_L_reduces_Fcr_quadratically():
    """Doubling L reduces F_cr by 4× (inverse-square law)."""
    F_100 = _euler_buckling_force(8.0, 100.0, 1.0)
    F_200 = _euler_buckling_force(8.0, 200.0, 1.0)
    assert F_100 / F_200 == pytest.approx(4.0, rel=1e-9)


def test_quadratic_L_scaling_three_lengths():
    """F_cr(100) / F_cr(300) = 9 (3²)."""
    F_100 = _euler_buckling_force(6.0, 100.0, 1.0)
    F_300 = _euler_buckling_force(6.0, 300.0, 1.0)
    assert F_100 / F_300 == pytest.approx(9.0, rel=1e-9)


def test_force_decreases_with_L():
    """F_cr decreases monotonically as L increases."""
    lengths = [50.0, 100.0, 150.0, 200.0, 300.0]
    forces = [_euler_buckling_force(6.0, L, 1.0) for L in lengths]
    for i in range(len(forces) - 1):
        assert forces[i] > forces[i + 1]


# ---------------------------------------------------------------------------
# 5. End-condition factor K — fixed-fixed gives 4× higher F_cr than pinned-pinned
# ---------------------------------------------------------------------------

def test_fixed_fixed_four_times_pinned_pinned():
    """K=0.5 (fixed-fixed) gives F_cr = 4× K=1.0 (pinned-pinned)."""
    F_pp = _euler_buckling_force(8.0, 100.0, K=1.0)
    F_ff = _euler_buckling_force(8.0, 100.0, K=0.5)
    assert F_ff / F_pp == pytest.approx(4.0, rel=1e-9)


def test_cantilever_one_quarter_of_pinned_pinned():
    """K=2.0 (cantilever) gives F_cr = 1/4 of K=1.0 (pinned-pinned)."""
    F_pp = _euler_buckling_force(8.0, 100.0, K=1.0)
    F_cant = _euler_buckling_force(8.0, 100.0, K=2.0)
    assert F_pp / F_cant == pytest.approx(4.0, rel=1e-9)


# ---------------------------------------------------------------------------
# 6. DCR calculation and adequate flag
# ---------------------------------------------------------------------------

def test_dcr_adequate_when_force_below_Fcr():
    """DCR < 1 when required force is below F_cr → adequate=True."""
    spec = EjectorPinPushSpec(
        pin_diameter_mm=8.0,
        pin_length_L_mm=100.0,
        pin_material="M2_tool_steel",
        end_condition_K=1.0,
        required_push_force_N=5000.0,  # well below ~39 688 N
    )
    report = compute_ejector_pin_push(spec)
    assert report.adequate is True
    assert report.dcr < 1.0
    assert report.dcr == pytest.approx(5000.0 / report.buckling_force_N, rel=1e-4)


def test_dcr_inadequate_when_force_exceeds_Fcr():
    """DCR > 1 when required force exceeds F_cr → adequate=False."""
    # 2 mm pin, L=200 mm — very weak
    spec = EjectorPinPushSpec(
        pin_diameter_mm=2.0,
        pin_length_L_mm=200.0,
        pin_material="H13",
        end_condition_K=1.0,
        required_push_force_N=5000.0,
    )
    report = compute_ejector_pin_push(spec)
    assert report.adequate is False
    assert report.dcr > 1.0


def test_dcr_zero_when_required_force_zero():
    """DCR = 0 when required_push_force_N = 0 (capacity characterisation only)."""
    spec = EjectorPinPushSpec(
        pin_diameter_mm=6.0,
        pin_length_L_mm=100.0,
        pin_material="S7",
        end_condition_K=1.0,
        required_push_force_N=0.0,
    )
    report = compute_ejector_pin_push(spec)
    assert report.dcr == pytest.approx(0.0, abs=1e-9)
    assert report.adequate is True


# ---------------------------------------------------------------------------
# 7. Recommended diameter — larger diameter when force exceeded
# ---------------------------------------------------------------------------

def test_recommend_larger_diameter_when_inadequate():
    """When current pin buckles, recommended_min_diameter_mm > pin_diameter_mm."""
    spec = EjectorPinPushSpec(
        pin_diameter_mm=2.0,
        pin_length_L_mm=150.0,
        pin_material="H13",
        end_condition_K=1.0,
        required_push_force_N=3000.0,
    )
    report = compute_ejector_pin_push(spec)
    assert not report.adequate
    assert report.recommended_min_diameter_mm > spec.pin_diameter_mm


def test_recommend_adequate_diameter_capacity():
    """Recommended diameter gives F_cr ≥ 1.1 × required_push_force_N."""
    required = 3000.0
    spec = EjectorPinPushSpec(
        pin_diameter_mm=2.0,
        pin_length_L_mm=150.0,
        pin_material="H13",
        end_condition_K=1.0,
        required_push_force_N=required,
    )
    report = compute_ejector_pin_push(spec)
    rec_d = report.recommended_min_diameter_mm
    F_rec = _ref_Fcr(rec_d, spec.pin_length_L_mm, spec.end_condition_K)
    assert F_rec >= required * 1.10 - 1.0  # small numerical tolerance


def test_recommend_current_diameter_when_adequate():
    """When pin is adequate, recommended_min_diameter_mm == pin_diameter_mm."""
    spec = EjectorPinPushSpec(
        pin_diameter_mm=8.0,
        pin_length_L_mm=100.0,
        pin_material="M2_tool_steel",
        end_condition_K=1.0,
        required_push_force_N=1000.0,
    )
    report = compute_ejector_pin_push(spec)
    assert report.adequate is True
    assert report.recommended_min_diameter_mm == pytest.approx(spec.pin_diameter_mm)


def test_recommend_spi_standard_diameter():
    """Recommended diameter is always in the SPI standard list (or above)."""
    spec = EjectorPinPushSpec(
        pin_diameter_mm=3.0,
        pin_length_L_mm=200.0,
        pin_material="D2",
        end_condition_K=1.0,
        required_push_force_N=8000.0,
    )
    report = compute_ejector_pin_push(spec)
    rec_d = report.recommended_min_diameter_mm
    # Must be in SPI list or an integer mm fallback above the largest SPI size
    in_spi = rec_d in SPI_EJECTOR_PIN_DIAMETERS_MM
    above_max = rec_d > max(SPI_EJECTOR_PIN_DIAMETERS_MM)
    assert in_spi or above_max, (
        f"Recommended diameter {rec_d} mm is not a SPI standard size or above max"
    )


# ---------------------------------------------------------------------------
# 8. Report field population
# ---------------------------------------------------------------------------

def test_report_fields_populated():
    """All EjectorPinPushReport fields are populated correctly."""
    spec = EjectorPinPushSpec(
        pin_diameter_mm=5.0,
        pin_length_L_mm=120.0,
        pin_material="M2_tool_steel",
        end_condition_K=1.0,
        required_push_force_N=1500.0,
    )
    report = compute_ejector_pin_push(spec)
    assert report.buckling_force_N > 0.0
    assert 0.0 <= report.dcr <= 10.0
    assert isinstance(report.adequate, bool)
    assert report.recommended_min_diameter_mm > 0.0
    assert report.recommended_pin_material in {"M2_tool_steel", "H13", "S7", "D2"}
    assert len(report.honest_caveat) > 50


def test_honest_caveat_mentions_euler():
    """Honest caveat references Euler formula and key caveats."""
    spec = EjectorPinPushSpec(
        pin_diameter_mm=8.0,
        pin_length_L_mm=100.0,
        pin_material="H13",
        end_condition_K=1.0,
        required_push_force_N=2000.0,
    )
    report = compute_ejector_pin_push(spec)
    assert "Euler" in report.honest_caveat
    assert "Roark" in report.honest_caveat
    assert "Johnson" in report.honest_caveat


# ---------------------------------------------------------------------------
# 9. Short-column warning when K·L/d < 30
# ---------------------------------------------------------------------------

def test_short_column_warning_in_caveat():
    """Short stout pin (L/d < 30) triggers short-column warning in caveat."""
    # L/d = 20/8 = 2.5 → very short column
    spec = EjectorPinPushSpec(
        pin_diameter_mm=8.0,
        pin_length_L_mm=20.0,
        pin_material="M2_tool_steel",
        end_condition_K=1.0,
        required_push_force_N=1000.0,
    )
    report = compute_ejector_pin_push(spec)
    assert "short-column" in report.honest_caveat.lower() or \
           "Johnson" in report.honest_caveat or \
           "WARNING" in report.honest_caveat


def test_no_short_column_warning_for_slender_pin():
    """Slender pin (L/d ≥ 30) does not trigger the short-column warning."""
    # L/d = 300/8 = 37.5 → slender
    spec = EjectorPinPushSpec(
        pin_diameter_mm=8.0,
        pin_length_L_mm=300.0,
        pin_material="H13",
        end_condition_K=1.0,
        required_push_force_N=1000.0,
    )
    report = compute_ejector_pin_push(spec)
    assert "WARNING" not in report.honest_caveat


# ---------------------------------------------------------------------------
# 10. Input validation — ValueError on bad inputs
# ---------------------------------------------------------------------------

def test_invalid_material_raises():
    with pytest.raises(ValueError, match="Unknown pin_material"):
        EjectorPinPushSpec(
            pin_diameter_mm=5.0,
            pin_length_L_mm=100.0,
            pin_material="P20",
            end_condition_K=1.0,
            required_push_force_N=1000.0,
        )


def test_zero_diameter_raises():
    with pytest.raises(ValueError, match="pin_diameter_mm must be > 0"):
        EjectorPinPushSpec(
            pin_diameter_mm=0.0,
            pin_length_L_mm=100.0,
            pin_material="H13",
            end_condition_K=1.0,
            required_push_force_N=1000.0,
        )


def test_negative_length_raises():
    with pytest.raises(ValueError, match="pin_length_L_mm must be > 0"):
        EjectorPinPushSpec(
            pin_diameter_mm=5.0,
            pin_length_L_mm=-50.0,
            pin_material="D2",
            end_condition_K=1.0,
            required_push_force_N=1000.0,
        )


def test_zero_K_raises():
    with pytest.raises(ValueError, match="end_condition_K must be > 0"):
        EjectorPinPushSpec(
            pin_diameter_mm=5.0,
            pin_length_L_mm=100.0,
            pin_material="M2_tool_steel",
            end_condition_K=0.0,
            required_push_force_N=1000.0,
        )


def test_negative_required_force_raises():
    with pytest.raises(ValueError, match="required_push_force_N must be >= 0"):
        EjectorPinPushSpec(
            pin_diameter_mm=5.0,
            pin_length_L_mm=100.0,
            pin_material="S7",
            end_condition_K=1.0,
            required_push_force_N=-100.0,
        )


# ---------------------------------------------------------------------------
# 11. LLM tool dispatch
# ---------------------------------------------------------------------------

class _Ctx:
    pass


CTX = _Ctx()


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def test_tool_dispatch_basic():
    from kerf_mold.ejector_pin_push_tool import run_mold_compute_ejector_pin_push
    result = json.loads(_run(run_mold_compute_ejector_pin_push({
        "pin_diameter_mm": 8.0,
        "pin_length_L_mm": 100.0,
        "pin_material": "H13",
        "end_condition_K": 1.0,
        "required_push_force_N": 2000.0,
    }, CTX)))
    assert result.get("ok") is True
    assert "buckling_force_N" in result
    # F_cr should be approximately 39 688 N
    assert result["buckling_force_N"] == pytest.approx(_ref_Fcr(8.0, 100.0, 1.0), rel=1e-4)
    assert result["adequate"] is True
    assert result["dcr"] < 1.0


def test_tool_dispatch_missing_diameter():
    from kerf_mold.ejector_pin_push_tool import run_mold_compute_ejector_pin_push
    result = json.loads(_run(run_mold_compute_ejector_pin_push({
        "pin_length_L_mm": 100.0,
        "pin_material": "H13",
        "required_push_force_N": 2000.0,
    }, CTX)))
    assert "error" in result
    assert result.get("code") == "BAD_ARGS"


def test_tool_dispatch_invalid_material():
    from kerf_mold.ejector_pin_push_tool import run_mold_compute_ejector_pin_push
    result = json.loads(_run(run_mold_compute_ejector_pin_push({
        "pin_diameter_mm": 5.0,
        "pin_length_L_mm": 100.0,
        "pin_material": "P20",
        "required_push_force_N": 1000.0,
    }, CTX)))
    assert "error" in result
    assert result.get("code") == "BAD_ARGS"


def test_tool_dispatch_uses_default_K():
    """Tool uses K=1.0 when end_condition_K is not supplied."""
    from kerf_mold.ejector_pin_push_tool import run_mold_compute_ejector_pin_push
    result = json.loads(_run(run_mold_compute_ejector_pin_push({
        "pin_diameter_mm": 6.0,
        "pin_length_L_mm": 120.0,
        "pin_material": "M2_tool_steel",
        "required_push_force_N": 500.0,
    }, CTX)))
    assert result.get("ok") is True
    expected = _ref_Fcr(6.0, 120.0, 1.0)
    assert result["buckling_force_N"] == pytest.approx(expected, rel=1e-4)


# ---------------------------------------------------------------------------
# 12. Tool spec name and schema
# ---------------------------------------------------------------------------

def test_tool_spec_name():
    from kerf_mold.ejector_pin_push_tool import mold_compute_ejector_pin_push_spec
    assert mold_compute_ejector_pin_push_spec.name == "mold_compute_ejector_pin_push"


def test_tool_spec_required_fields():
    from kerf_mold.ejector_pin_push_tool import mold_compute_ejector_pin_push_spec
    required = mold_compute_ejector_pin_push_spec.input_schema.get("required", [])
    assert "pin_diameter_mm" in required
    assert "pin_length_L_mm" in required
    assert "pin_material" in required
    assert "required_push_force_N" in required


# ---------------------------------------------------------------------------
# 13. Plugin registers mold_compute_ejector_pin_push
# ---------------------------------------------------------------------------

def test_plugin_registers_ejector_pin_push_tool():
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
    assert "mold_compute_ejector_pin_push" in ctx.tools.registered, (
        "mold_compute_ejector_pin_push should be registered in the plugin"
    )


# ---------------------------------------------------------------------------
# 14. Re-export from kerf_mold.__init__
# ---------------------------------------------------------------------------

def test_init_exports():
    from kerf_mold import (
        EjectorPinPushSpec,
        EjectorPinPushReport,
        SPI_EJECTOR_PIN_DIAMETERS_MM_PUSH,
        compute_ejector_pin_push,
    )
    assert EjectorPinPushSpec is not None
    assert EjectorPinPushReport is not None
    assert 8.0 in SPI_EJECTOR_PIN_DIAMETERS_MM_PUSH
    assert callable(compute_ejector_pin_push)


# ---------------------------------------------------------------------------
# 15. All four materials accepted; all return same E (200 GPa)
# ---------------------------------------------------------------------------

def test_all_materials_accepted():
    """All four material grades should be accepted and return identical F_cr
    (same E = 200 GPa)."""
    materials = ["M2_tool_steel", "H13", "S7", "D2"]
    forces = []
    for mat in materials:
        spec = EjectorPinPushSpec(
            pin_diameter_mm=5.0,
            pin_length_L_mm=100.0,
            pin_material=mat,
            end_condition_K=1.0,
            required_push_force_N=1000.0,
        )
        report = compute_ejector_pin_push(spec)
        forces.append(report.buckling_force_N)

    # All four grades share E = 200 GPa; F_cr must be identical
    for i in range(1, len(forces)):
        assert forces[i] == pytest.approx(forces[0], rel=1e-9), (
            f"F_cr for {materials[i]} differs from M2 — E should be 200 GPa for all grades"
        )


# ---------------------------------------------------------------------------
# 16. SPI standard diameters list — basic sanity checks
# ---------------------------------------------------------------------------

def test_spi_diameters_sorted_ascending():
    assert list(SPI_EJECTOR_PIN_DIAMETERS_MM) == sorted(SPI_EJECTOR_PIN_DIAMETERS_MM)


def test_spi_diameters_includes_common_sizes():
    assert 3.0 in SPI_EJECTOR_PIN_DIAMETERS_MM
    assert 5.0 in SPI_EJECTOR_PIN_DIAMETERS_MM
    assert 8.0 in SPI_EJECTOR_PIN_DIAMETERS_MM


def test_spi_diameters_positive():
    assert all(d > 0 for d in SPI_EJECTOR_PIN_DIAMETERS_MM)


# ---------------------------------------------------------------------------
# 17. Material recommendation — M2 preferred near capacity
# ---------------------------------------------------------------------------

def test_material_recommendation_m2_when_near_limit():
    """When DCR > 0.8 (close to buckling), M2 is recommended."""
    F_cr = _ref_Fcr(5.0, 150.0, 1.0)
    required = F_cr * 0.85  # DCR = 0.85 > 0.8
    spec = EjectorPinPushSpec(
        pin_diameter_mm=5.0,
        pin_length_L_mm=150.0,
        pin_material="S7",
        end_condition_K=1.0,
        required_push_force_N=required,
    )
    report = compute_ejector_pin_push(spec)
    assert report.recommended_pin_material == "M2_tool_steel"


def test_material_recommendation_preserves_grade_when_comfortable():
    """When DCR is well below 0.8, the input material is preserved."""
    F_cr = _ref_Fcr(8.0, 100.0, 1.0)
    required = F_cr * 0.3  # DCR = 0.3, well below 0.8
    spec = EjectorPinPushSpec(
        pin_diameter_mm=8.0,
        pin_length_L_mm=100.0,
        pin_material="D2",
        end_condition_K=1.0,
        required_push_force_N=required,
    )
    report = compute_ejector_pin_push(spec)
    assert report.recommended_pin_material == "D2"


# ---------------------------------------------------------------------------
# 18. DCR precision — exact formula verification
# ---------------------------------------------------------------------------

def test_dcr_exact_formula():
    """DCR = required_force / F_cr exactly."""
    d, L, K, req = 6.0, 120.0, 1.0, 4000.0
    spec = EjectorPinPushSpec(
        pin_diameter_mm=d,
        pin_length_L_mm=L,
        pin_material="M2_tool_steel",
        end_condition_K=K,
        required_push_force_N=req,
    )
    report = compute_ejector_pin_push(spec)
    expected_dcr = req / _ref_Fcr(d, L, K)
    assert report.dcr == pytest.approx(expected_dcr, rel=1e-5)


# ---------------------------------------------------------------------------
# 19. Fixed-fixed end condition — verify adequate for borderline pinned case
# ---------------------------------------------------------------------------

def test_fixed_fixed_makes_borderline_pin_adequate():
    """A pin that buckles under pinned-pinned is adequate under fixed-fixed."""
    # Choose a case where the pin barely fails under K=1
    d, L = 4.0, 200.0
    F_pp = _ref_Fcr(d, L, K=1.0)
    required = F_pp * 1.5  # 50 % over pinned-pinned capacity

    spec_pp = EjectorPinPushSpec(
        pin_diameter_mm=d, pin_length_L_mm=L,
        pin_material="H13", end_condition_K=1.0,
        required_push_force_N=required,
    )
    spec_ff = EjectorPinPushSpec(
        pin_diameter_mm=d, pin_length_L_mm=L,
        pin_material="H13", end_condition_K=0.5,
        required_push_force_N=required,
    )

    rep_pp = compute_ejector_pin_push(spec_pp)
    rep_ff = compute_ejector_pin_push(spec_ff)

    assert not rep_pp.adequate, "Pinned-pinned pin should fail at 1.5× F_cr"
    assert rep_ff.adequate, "Fixed-fixed pin should be adequate (4× stronger)"


# ---------------------------------------------------------------------------
# 20. Response spi_standard_diameters_mm key present in tool output
# ---------------------------------------------------------------------------

def test_tool_response_includes_spi_diameters():
    from kerf_mold.ejector_pin_push_tool import run_mold_compute_ejector_pin_push
    result = json.loads(_run(run_mold_compute_ejector_pin_push({
        "pin_diameter_mm": 5.0,
        "pin_length_L_mm": 100.0,
        "pin_material": "H13",
        "required_push_force_N": 1000.0,
    }, CTX)))
    assert result.get("ok") is True
    assert "spi_standard_diameters_mm" in result
    assert 5.0 in result["spi_standard_diameters_mm"]
