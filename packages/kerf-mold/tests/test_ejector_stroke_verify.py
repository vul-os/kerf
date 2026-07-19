"""
Tests for kerf_mold.ejector_stroke_verify — ejector stroke sufficiency.

Oracle coverage (Beaumont 2007 §9 + Menges 2001 §7.4):

  1.  Adequate stroke: depth=100mm + margin=5mm = 105mm ≤ machine=150mm → PASS
       clearance = 45mm.
  2.  Insufficient stroke: depth=100mm + margin=5mm = 105mm > machine=100mm → FAIL.
  3.  Exact boundary: depth=95mm + margin=5mm = 100mm == machine=100mm → PASS,
       clearance=0.
  4.  Force adequate: 10 pins × 500N/pin = 5000N ≥ required 2000N → PASS.
  5.  Force inadequate: 2 pins × 500N/pin = 1000N < required 2000N → FAIL.
  6.  Deflection oracle: Ø5mm pin L=200mm steel E=200000N/mm², I=π·5⁴/64.
       F = 2000/10 = 200N (10 pins).
       δ = 200·200³/(3·200000·I) — compute and assert against formula.
  7.  Deflection PASS: Ø5mm L=50mm — very stiff → δ << 0.05mm.
  8.  Deflection FAIL: Ø3.18mm L=300mm under 50N → δ > 0.05mm.
  9.  Knockout bar PASS: plate=20mm ≥ bar=15mm.
  10. Knockout bar FAIL: plate=10mm < bar=15mm → violation.
  11. Knockout bar skipped when only diameter is given (no plate thickness).
  12. ok=True only when ALL four checks pass.
  13. Marginal stroke warning: clearance < 10mm but ≥ 0.
  14. Multiple pin groups: mixed diameters, counts; sum checked correctly.
  15. EjectorPinSpec validation: negative diameter raises ValueError.
  16. EjectorPinSpec validation: zero count raises ValueError.
  17. verify_ejector_stroke raises on empty pin list.
  18. verify_ejector_stroke raises on non-positive part_depth_mm.
  19. LLM tool: flat-plate adequate scenario → ok=True.
  20. LLM tool: bad args (missing pins) → ok=False / error key.
"""

from __future__ import annotations

import json
import math
import os
import sys

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
_SRC = os.path.join(os.path.dirname(_HERE), "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from kerf_mold.ejector_stroke_verify import (
    DEFAULT_ALLOWABLE_DEFLECTION_MM,
    STEEL_E_N_MM2,
    EjectorPinSpec,
    EjectorStrokeReport,
    PinDeflectionResult,
    verify_ejector_stroke,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _pin(d: float, L: float, n: int = 1) -> EjectorPinSpec:
    return EjectorPinSpec(diameter_mm=d, free_length_mm=L, count=n)


def _I(d: float) -> float:
    """Solid-circle second moment of area I = π·d⁴/64."""
    return math.pi * d ** 4 / 64.0


def _delta(F: float, L: float, d: float, E: float = STEEL_E_N_MM2) -> float:
    """Euler-Bernoulli cantilever tip deflection δ = F·L³/(3·E·I)."""
    return F * L ** 3 / (3.0 * E * _I(d))


# ---------------------------------------------------------------------------
# EjectorPinSpec dataclass validation
# ---------------------------------------------------------------------------

class TestEjectorPinSpec:
    def test_valid_spec(self):
        p = _pin(5.0, 200.0, 10)
        assert p.diameter_mm == 5.0
        assert p.free_length_mm == 200.0
        assert p.count == 10

    def test_second_moment_of_area_oracle(self):
        """I = π·5⁴/64 for Ø5mm pin. Oracle: π·625/64 ≈ 30.679 mm⁴."""
        p = _pin(5.0, 200.0)
        expected = math.pi * 5.0 ** 4 / 64.0
        assert p.second_moment_of_area_mm4 == pytest.approx(expected, rel=1e-9)

    def test_negative_diameter_raises(self):
        with pytest.raises(ValueError, match="diameter_mm"):
            _pin(-1.0, 100.0)

    def test_zero_length_raises(self):
        with pytest.raises(ValueError, match="free_length_mm"):
            _pin(5.0, 0.0)

    def test_zero_count_raises(self):
        with pytest.raises(ValueError, match="count"):
            EjectorPinSpec(diameter_mm=5.0, free_length_mm=100.0, count=0)


# ---------------------------------------------------------------------------
# Stroke adequacy (Check 1) — Beaumont §9.1
# ---------------------------------------------------------------------------

class TestStrokeCheck:
    def test_adequate_stroke_beaumont_example(self):
        """Oracle: depth=100 + margin=5 = 105 ≤ machine=150 → PASS, clearance=45."""
        r = verify_ejector_stroke(
            part_depth_mm=100.0,
            machine_stroke_mm=150.0,
            pins=[_pin(5.0, 100.0, 10)],
            ejection_force_N=500.0,
        )
        assert r.stroke_adequate is True
        assert r.required_stroke_mm == pytest.approx(105.0)
        assert r.stroke_clearance_mm == pytest.approx(45.0)
        assert not any("STROKE" in v for v in r.violations)

    def test_insufficient_stroke(self):
        """Oracle: depth=100 + margin=5 = 105 > machine=100 → FAIL."""
        r = verify_ejector_stroke(
            part_depth_mm=100.0,
            machine_stroke_mm=100.0,
            pins=[_pin(5.0, 100.0, 10)],
            ejection_force_N=500.0,
        )
        assert r.stroke_adequate is False
        assert r.stroke_clearance_mm == pytest.approx(-5.0)
        assert any("STROKE INSUFFICIENT" in v for v in r.violations)

    def test_exact_boundary_passes(self):
        """depth=95 + margin=5 = 100 == machine=100 → PASS, clearance=0."""
        r = verify_ejector_stroke(
            part_depth_mm=95.0,
            machine_stroke_mm=100.0,
            pins=[_pin(5.0, 80.0, 10)],
            ejection_force_N=200.0,
        )
        assert r.stroke_adequate is True
        assert r.stroke_clearance_mm == pytest.approx(0.0, abs=1e-9)

    def test_marginal_stroke_warning(self):
        """Clearance < 10mm but ≥ 0 → warning issued, still PASS."""
        r = verify_ejector_stroke(
            part_depth_mm=98.0,
            machine_stroke_mm=105.0,   # clearance = 105 - (98+5) = 2 mm
            pins=[_pin(5.0, 80.0, 5)],
            ejection_force_N=100.0,
        )
        assert r.stroke_adequate is True
        assert r.stroke_clearance_mm == pytest.approx(2.0)
        assert any("marginal" in w.lower() for w in r.warnings)

    def test_custom_safety_margin(self):
        r = verify_ejector_stroke(
            part_depth_mm=50.0,
            machine_stroke_mm=60.0,
            pins=[_pin(5.0, 50.0, 4)],
            ejection_force_N=100.0,
            safety_margin_mm=8.0,
        )
        assert r.required_stroke_mm == pytest.approx(58.0)
        assert r.stroke_adequate is True


# ---------------------------------------------------------------------------
# Force adequacy (Check 2) — Menges §7.4
# ---------------------------------------------------------------------------

class TestForceCheck:
    def test_force_adequate(self):
        """10 pins × 500N/pin = 5000N ≥ required 2000N → PASS."""
        r = verify_ejector_stroke(
            part_depth_mm=50.0,
            machine_stroke_mm=100.0,
            pins=[_pin(5.0, 100.0, 10)],
            ejection_force_N=2000.0,
            force_per_pin_max_N=500.0,
        )
        assert r.force_adequate is True
        assert r.total_pin_count == 10
        assert r.force_capacity_N == pytest.approx(5000.0)

    def test_force_inadequate(self):
        """2 pins × 500N/pin = 1000N < required 2000N → FAIL."""
        r = verify_ejector_stroke(
            part_depth_mm=50.0,
            machine_stroke_mm=100.0,
            pins=[_pin(5.0, 100.0, 2)],
            ejection_force_N=2000.0,
            force_per_pin_max_N=500.0,
        )
        assert r.force_adequate is False
        assert any("FORCE INSUFFICIENT" in v for v in r.violations)

    def test_multiple_pin_groups_count_sum(self):
        """Two groups: 4 × Ø5mm + 6 × Ø3.18mm = 10 total."""
        r = verify_ejector_stroke(
            part_depth_mm=40.0,
            machine_stroke_mm=100.0,
            pins=[_pin(5.0, 80.0, 4), _pin(3.18, 60.0, 6)],
            ejection_force_N=500.0,
            force_per_pin_max_N=500.0,
        )
        assert r.total_pin_count == 10
        assert r.force_per_pin_N == pytest.approx(50.0)


# ---------------------------------------------------------------------------
# Pin deflection (Check 3) — Beaumont §9.3 cantilever formula
# ---------------------------------------------------------------------------

class TestDeflectionCheck:
    def test_deflection_oracle_formula(self):
        """Ø5mm pin, L=200mm, 10 pins, F_total=2000N → F/pin=200N.
        Oracle δ = 200·200³/(3·200000·I) where I=π·5⁴/64.
        """
        d = 5.0
        L = 200.0
        F_total = 2000.0
        n = 10
        F_pin = F_total / n  # 200 N
        expected_delta = _delta(F_pin, L, d)

        r = verify_ejector_stroke(
            part_depth_mm=60.0,
            machine_stroke_mm=200.0,
            pins=[_pin(d, L, n)],
            ejection_force_N=F_total,
        )
        pd = r.pin_deflections[0]
        assert pd.deflection_mm == pytest.approx(expected_delta, rel=1e-6)
        assert pd.force_per_pin_N == pytest.approx(F_pin, rel=1e-6)

    def test_deflection_stiff_pin_passes(self):
        """Ø12.7mm L=50mm, small force → δ << 0.05mm → PASS.

        Oracle: Ø12.7mm → I=π·12.7⁴/64 ≈ 1278 mm⁴.
        F_pin = 100/8 = 12.5N, δ = 12.5·50³/(3·200000·1278) ≈ 8.1e-5 mm << 0.05mm.
        """
        r = verify_ejector_stroke(
            part_depth_mm=30.0,
            machine_stroke_mm=80.0,
            pins=[_pin(12.7, 50.0, 8)],
            ejection_force_N=100.0,
        )
        assert r.deflection_ok is True
        assert r.max_deflection_mm < DEFAULT_ALLOWABLE_DEFLECTION_MM

    def test_deflection_slender_pin_fails(self):
        """Ø3.18mm L=300mm under high load → δ > 0.05mm → FAIL.
        Oracle: use 1 pin group with count=1, force=F_total so F_pin=F_total.
        Pick F such that δ > 0.05mm.
        I = π·3.18⁴/64 ≈ 7.98 mm⁴
        Need F > 0.05·3·200000·I/300³ = 0.05·3·200000·7.98/27000000
              = 0.05·4788000/27000000 ≈ 0.00886 N — trivially exceeded.
        """
        d = 3.18
        L = 300.0
        I_pin = _I(d)
        # Choose F so δ is definitely > allowable
        F_needed_for_allowable = DEFAULT_ALLOWABLE_DEFLECTION_MM * 3.0 * STEEL_E_N_MM2 * I_pin / L ** 3
        F_use = F_needed_for_allowable * 5  # 5× the threshold
        r = verify_ejector_stroke(
            part_depth_mm=30.0,
            machine_stroke_mm=500.0,
            pins=[_pin(d, L, 1)],
            ejection_force_N=F_use,
            force_per_pin_max_N=10_000.0,
        )
        assert r.deflection_ok is False
        assert any("PIN DEFLECTION EXCEEDED" in v for v in r.violations)
        assert r.max_deflection_mm > DEFAULT_ALLOWABLE_DEFLECTION_MM

    def test_deflection_allowable_boundary_pass(self):
        """Force chosen so δ is 99% of allowable → PASS.

        Using 99% avoids floating-point == boundary issues; clearly below limit.
        """
        d = 5.0
        L = 100.0
        allow = DEFAULT_ALLOWABLE_DEFLECTION_MM
        F_at_limit = allow * 3.0 * STEEL_E_N_MM2 * _I(d) / L ** 3
        F_use = F_at_limit * 0.99  # 99% of threshold → definitely PASS
        r = verify_ejector_stroke(
            part_depth_mm=30.0,
            machine_stroke_mm=200.0,
            pins=[_pin(d, L, 1)],
            ejection_force_N=F_use,
            allowable_deflection_mm=allow,
            force_per_pin_max_N=10_000.0,
        )
        assert r.pin_deflections[0].passes is True
        assert r.pin_deflections[0].deflection_mm < allow


# ---------------------------------------------------------------------------
# Knockout bar (Check 4) — Beaumont §9.5
# ---------------------------------------------------------------------------

class TestKnockoutBarCheck:
    def test_knockout_bar_pass(self):
        """Plate 20mm ≥ bar 15mm → PASS."""
        r = verify_ejector_stroke(
            part_depth_mm=50.0,
            machine_stroke_mm=100.0,
            pins=[_pin(5.0, 80.0, 8)],
            ejection_force_N=200.0,
            ejector_plate_thickness_mm=20.0,
            knockout_bar_diameter_mm=15.0,
        )
        assert r.knockout_bar_ok is True
        assert r.knockout_bar_checked is True

    def test_knockout_bar_fail(self):
        """Plate 10mm < bar 15mm → FAIL + violation."""
        r = verify_ejector_stroke(
            part_depth_mm=50.0,
            machine_stroke_mm=100.0,
            pins=[_pin(5.0, 80.0, 8)],
            ejection_force_N=200.0,
            ejector_plate_thickness_mm=10.0,
            knockout_bar_diameter_mm=15.0,
        )
        assert r.knockout_bar_ok is False
        assert r.knockout_bar_checked is True
        assert any("KNOCKOUT BAR" in v for v in r.violations)

    def test_knockout_bar_skipped_when_no_inputs(self):
        """No plate/bar provided → check skipped, ok not affected by it."""
        r = verify_ejector_stroke(
            part_depth_mm=50.0,
            machine_stroke_mm=100.0,
            pins=[_pin(5.0, 80.0, 8)],
            ejection_force_N=200.0,
        )
        assert r.knockout_bar_checked is False
        assert r.knockout_bar_ok is True  # default True when not checked

    def test_knockout_bar_skipped_missing_plate_thickness_warns(self):
        """Bar diameter given but no plate thickness → warning issued."""
        r = verify_ejector_stroke(
            part_depth_mm=50.0,
            machine_stroke_mm=100.0,
            pins=[_pin(5.0, 80.0, 8)],
            ejection_force_N=200.0,
            knockout_bar_diameter_mm=15.0,
        )
        assert r.knockout_bar_checked is False
        assert any("knockout" in w.lower() for w in r.warnings)


# ---------------------------------------------------------------------------
# ok = ALL four checks pass
# ---------------------------------------------------------------------------

class TestOkFlag:
    def test_all_pass_ok_true(self):
        """Baseline adequate scenario → ok=True.

        Use large-diameter short pins so deflection passes.
        Ø12.7mm L=50mm, 10 pins, F=500N → F_pin=50N.
        δ = 50·50³/(3·200000·I_12.7) where I≈1278mm⁴ → δ≈8.1e-4 mm << 0.05mm.
        """
        r = verify_ejector_stroke(
            part_depth_mm=100.0,
            machine_stroke_mm=150.0,
            pins=[_pin(12.7, 50.0, 10)],
            ejection_force_N=500.0,
        )
        assert r.ok is True, f"Expected ok=True; violations={r.violations}"
        assert r.violations == []

    def test_stroke_fail_ok_false(self):
        r = verify_ejector_stroke(
            part_depth_mm=100.0,
            machine_stroke_mm=80.0,  # too short
            pins=[_pin(5.0, 80.0, 10)],
            ejection_force_N=500.0,
        )
        assert r.ok is False

    def test_force_fail_ok_false(self):
        r = verify_ejector_stroke(
            part_depth_mm=50.0,
            machine_stroke_mm=200.0,
            pins=[_pin(5.0, 80.0, 1)],
            ejection_force_N=100_000.0,  # impossible with 1 pin
            force_per_pin_max_N=500.0,
        )
        assert r.ok is False


# ---------------------------------------------------------------------------
# Input validation guards
# ---------------------------------------------------------------------------

class TestInputValidation:
    def test_empty_pins_raises(self):
        with pytest.raises(ValueError, match="pins must be a non-empty list"):
            verify_ejector_stroke(
                part_depth_mm=50.0,
                machine_stroke_mm=100.0,
                pins=[],
                ejection_force_N=100.0,
            )

    def test_negative_part_depth_raises(self):
        with pytest.raises(ValueError, match="part_depth_mm"):
            verify_ejector_stroke(
                part_depth_mm=-10.0,
                machine_stroke_mm=100.0,
                pins=[_pin(5.0, 80.0)],
                ejection_force_N=100.0,
            )

    def test_zero_machine_stroke_raises(self):
        with pytest.raises(ValueError, match="machine_stroke_mm"):
            verify_ejector_stroke(
                part_depth_mm=50.0,
                machine_stroke_mm=0.0,
                pins=[_pin(5.0, 80.0)],
                ejection_force_N=100.0,
            )


# ---------------------------------------------------------------------------
# LLM tool integration
# ---------------------------------------------------------------------------

class TestEjectorStrokeVerifyTool:
    def setup_method(self):
        import asyncio
        self._loop = asyncio.new_event_loop()

    def teardown_method(self):
        self._loop.close()

    def _run(self, coro):
        return self._loop.run_until_complete(coro)

    def _ctx(self):
        class _Ctx:
            pass
        return _Ctx()

    def test_tool_adequate_scenario(self):
        """depth=100mm, machine=150mm, 10×Ø12.7mm L=50mm, F=500N → ok=True.

        Large-diameter short pins keep deflection well below 0.05mm limit.
        """
        from kerf_mold.ejector_stroke_verify_tool import (
            run_mold_verify_ejector_stroke,
            mold_verify_ejector_stroke_spec,
        )
        assert mold_verify_ejector_stroke_spec.name == "mold_verify_ejector_stroke"

        args = json.dumps({
            "part_depth_mm": 100.0,
            "machine_stroke_mm": 150.0,
            "ejection_force_N": 500.0,
            "pins": [{"diameter_mm": 12.7, "free_length_mm": 50.0, "count": 10}],
        }).encode()
        result = json.loads(self._run(
            run_mold_verify_ejector_stroke(self._ctx(), args)
        ))
        assert result.get("ok") is True
        assert result["stroke_adequate"] is True
        assert result["stroke_clearance_mm"] == pytest.approx(45.0)
        assert "honest_flag" in result

    def test_tool_insufficient_stroke(self):
        """machine_stroke too short → ok=False, stroke_adequate=False."""
        from kerf_mold.ejector_stroke_verify_tool import run_mold_verify_ejector_stroke
        args = json.dumps({
            "part_depth_mm": 100.0,
            "machine_stroke_mm": 100.0,
            "ejection_force_N": 500.0,
            "pins": [{"diameter_mm": 5.0, "free_length_mm": 80.0, "count": 10}],
        }).encode()
        result = json.loads(self._run(
            run_mold_verify_ejector_stroke(self._ctx(), args)
        ))
        assert result.get("ok") is False
        assert result["stroke_adequate"] is False
        assert len(result["violations"]) >= 1

    def test_tool_missing_required_field(self):
        """Omit 'pins' → error response."""
        from kerf_mold.ejector_stroke_verify_tool import run_mold_verify_ejector_stroke
        args = json.dumps({
            "part_depth_mm": 100.0,
            "machine_stroke_mm": 150.0,
            "ejection_force_N": 500.0,
            # pins omitted
        }).encode()
        result = json.loads(self._run(
            run_mold_verify_ejector_stroke(self._ctx(), args)
        ))
        assert result.get("ok") is False or "error" in result

    def test_tool_bad_json(self):
        """Malformed JSON → error response."""
        from kerf_mold.ejector_stroke_verify_tool import run_mold_verify_ejector_stroke
        result = json.loads(self._run(
            run_mold_verify_ejector_stroke(self._ctx(), b"not-json")
        ))
        assert "error" in result

    def test_tool_spec_required_fields(self):
        from kerf_mold.ejector_stroke_verify_tool import mold_verify_ejector_stroke_spec
        required = mold_verify_ejector_stroke_spec.input_schema.get("required", [])
        assert "part_depth_mm" in required
        assert "machine_stroke_mm" in required
        assert "ejection_force_N" in required
        assert "pins" in required

    def test_tool_knockout_bar_check(self):
        """Plate < bar → ok=False, knockout_bar_ok=False."""
        from kerf_mold.ejector_stroke_verify_tool import run_mold_verify_ejector_stroke
        args = json.dumps({
            "part_depth_mm": 50.0,
            "machine_stroke_mm": 120.0,
            "ejection_force_N": 200.0,
            "pins": [{"diameter_mm": 5.0, "free_length_mm": 60.0, "count": 8}],
            "ejector_plate_thickness_mm": 10.0,
            "knockout_bar_diameter_mm": 20.0,
        }).encode()
        result = json.loads(self._run(
            run_mold_verify_ejector_stroke(self._ctx(), args)
        ))
        assert result["knockout_bar_ok"] is False
        assert result["knockout_bar_checked"] is True
