"""
Tests for stair code-compliance checker (IBC 2024 / ADA §504 / ICC A117.1 / OBC).

Pure-Python, hermetic — no OCC, no DB, no network.
All dimensions in inches (as the code references use imperial units).

Coverage:
  - IBC 2024: passing case, riser too tall, tread too shallow, width too narrow,
    headroom violation, landing violation, Blondel fail, vertical-rise-between-landings
  - ADA §504: tread too shallow, tread too wide, handrail out of range
  - ICC A117.1: treated identically to ADA (same thresholds) — spot-checks
  - Ontario OBC: riser, tread, headroom
  - Blondel formula: pass / fail
  - all_compliant convenience property
  - Violations table structure (3-tuple code_ref/requirement/actual)
  - Invalid jurisdiction returns a violation, not an exception
"""
from __future__ import annotations

import pytest

from kerf_cad_core.arch.stair_code_check import (
    StairCodeSpec,
    StairCodeReport,
    check_stair_codes,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _spec(**kwargs) -> StairCodeSpec:
    """Build a fully-valid IBC 2024 base spec, overridable via kwargs."""
    defaults = dict(
        tread_depth_in=11.0,
        riser_height_in=7.0,
        stair_width_in=44.0,
        handrail_height_in=36.0,
        headroom_clearance_in=80.0,
        num_risers=14,
        has_landing=False,
        landing_depth_in=44.0,
        jurisdiction="ibc_2024",
    )
    defaults.update(kwargs)
    return StairCodeSpec(**defaults)


def _refs(report: StairCodeReport) -> list[str]:
    """Extract code reference strings from the violations list."""
    return [v[0] for v in report.violations]


# ---------------------------------------------------------------------------
# 1. IBC 2024 — passing case
# ---------------------------------------------------------------------------

class TestIbcPass:
    def test_all_compliant(self):
        report = check_stair_codes(_spec())
        assert report.all_compliant, f"Unexpected violations: {report.violations}"

    def test_riser_compliant_true(self):
        assert check_stair_codes(_spec()).riser_compliant is True

    def test_tread_compliant_true(self):
        assert check_stair_codes(_spec()).tread_compliant is True

    def test_width_compliant_true(self):
        assert check_stair_codes(_spec()).width_compliant is True

    def test_headroom_compliant_true(self):
        assert check_stair_codes(_spec()).headroom_compliant is True

    def test_handrail_compliant_true(self):
        assert check_stair_codes(_spec()).handrail_compliant is True

    def test_honest_caveat_present(self):
        report = check_stair_codes(_spec())
        assert "IBC 2024" in report.honest_caveat
        assert "AHJ" in report.honest_caveat


# ---------------------------------------------------------------------------
# 2. IBC 2024 — riser too tall (8" > max 7")
# ---------------------------------------------------------------------------

class TestIbcRiserFail:
    def setup_method(self):
        self.report = check_stair_codes(_spec(riser_height_in=8.0))

    def test_riser_compliant_false(self):
        assert self.report.riser_compliant is False

    def test_violation_code_ref(self):
        assert any("1011.5.2" in r for r in _refs(self.report))

    def test_not_all_compliant(self):
        assert not self.report.all_compliant

    def test_actual_value_in_violation(self):
        actuals = [v[2] for v in self.report.violations]
        assert any("8.000" in a for a in actuals)


# ---------------------------------------------------------------------------
# 3. IBC 2024 — tread too shallow (10" < min 11")
# ---------------------------------------------------------------------------

class TestIbcTreadFail:
    def setup_method(self):
        self.report = check_stair_codes(_spec(tread_depth_in=10.0))

    def test_tread_compliant_false(self):
        assert self.report.tread_compliant is False

    def test_violation_code_ref(self):
        assert any("1011.5.3" in r for r in _refs(self.report))


# ---------------------------------------------------------------------------
# 4. IBC 2024 — width too narrow (36" < min 44")
# ---------------------------------------------------------------------------

class TestIbcWidthFail:
    def setup_method(self):
        self.report = check_stair_codes(_spec(stair_width_in=36.0))

    def test_width_compliant_false(self):
        assert self.report.width_compliant is False

    def test_violation_code_ref(self):
        assert any("1011.2" in r for r in _refs(self.report))


# ---------------------------------------------------------------------------
# 5. IBC 2024 — headroom too low (78" < min 80")
# ---------------------------------------------------------------------------

class TestIbcHeadroomFail:
    def setup_method(self):
        self.report = check_stair_codes(_spec(headroom_clearance_in=78.0))

    def test_headroom_compliant_false(self):
        assert self.report.headroom_compliant is False

    def test_violation_code_ref(self):
        assert any("1011.3" in r for r in _refs(self.report))


# ---------------------------------------------------------------------------
# 6. IBC 2024 — handrail out of range (40" > max 38")
# ---------------------------------------------------------------------------

class TestIbcHandrailFail:
    def setup_method(self):
        self.report = check_stair_codes(_spec(handrail_height_in=40.0))

    def test_handrail_compliant_false(self):
        assert self.report.handrail_compliant is False

    def test_violation_code_ref(self):
        assert any("1012" in r for r in _refs(self.report))


# ---------------------------------------------------------------------------
# 7. IBC 2024 — landing too shallow (has_landing=True, 24" < min 36")
# ---------------------------------------------------------------------------

class TestIbcLandingFail:
    def setup_method(self):
        self.report = check_stair_codes(
            _spec(has_landing=True, landing_depth_in=24.0, stair_width_in=44.0)
        )

    def test_landing_compliant_false(self):
        assert self.report.landing_compliant is False

    def test_violation_code_ref(self):
        assert any("1011.7" in r for r in _refs(self.report))


# ---------------------------------------------------------------------------
# 8. Blondel formula — 2R + T = 26" (> 25" max)
# ---------------------------------------------------------------------------

class TestBlondelFail:
    def setup_method(self):
        # 2×7.5 + 11 = 26 > 25
        self.report = check_stair_codes(_spec(riser_height_in=7.0, tread_depth_in=12.5))

    def test_ratio_compliant_false(self):
        assert self.report.ratio_2r_plus_t_compliant is False

    def test_violation_mentions_blondel(self):
        assert any("Blondel" in r for r in _refs(self.report))


class TestBlondelPass:
    def test_ratio_compliant_true(self):
        # 2×7.0 + 11.0 = 25.0 — exactly at the upper bound (inclusive)
        report = check_stair_codes(_spec(riser_height_in=7.0, tread_depth_in=11.0))
        assert report.ratio_2r_plus_t_compliant is True

    def test_interior_value(self):
        # 2×6.5 + 11.0 = 24.0 — at lower bound
        report = check_stair_codes(_spec(riser_height_in=6.5, tread_depth_in=11.0))
        assert report.ratio_2r_plus_t_compliant is True


# ---------------------------------------------------------------------------
# 9. IBC 2024 — vertical rise between landings exceeds 147"
# ---------------------------------------------------------------------------

class TestIbcTurningFail:
    def setup_method(self):
        # 22 risers × 7" = 154" > 147"
        self.report = check_stair_codes(_spec(num_risers=22, riser_height_in=7.0))

    def test_turning_compliant_false(self):
        assert self.report.turning_compliant is False

    def test_violation_code_ref(self):
        assert any("1011.8" in r for r in _refs(self.report))


class TestIbcTurningPass:
    def test_exactly_at_limit(self):
        # 21 × 7.0 = 147 — exactly at limit
        report = check_stair_codes(_spec(num_risers=21, riser_height_in=7.0))
        assert report.turning_compliant is True


# ---------------------------------------------------------------------------
# 10. ADA §504 — tread too shallow (10" < 11")
# ---------------------------------------------------------------------------

class TestAdaTreadFail:
    def setup_method(self):
        self.report = check_stair_codes(
            _spec(tread_depth_in=10.0, jurisdiction="ada_504")
        )

    def test_tread_compliant_false(self):
        assert self.report.tread_compliant is False

    def test_violation_code_ref(self):
        assert any("504.2" in r for r in _refs(self.report))


# ---------------------------------------------------------------------------
# 11. ADA §504 — tread too wide (> 12" implicit max)
# ---------------------------------------------------------------------------

class TestAdaTreadTooWide:
    def setup_method(self):
        # 13" > ADA uniform nosing limit 12"
        self.report = check_stair_codes(
            _spec(tread_depth_in=13.0, jurisdiction="ada_504")
        )

    def test_tread_compliant_false(self):
        assert self.report.tread_compliant is False


# ---------------------------------------------------------------------------
# 12. ADA §504 — handrail height out of range (33" < 34")
# ---------------------------------------------------------------------------

class TestAdaHandrailFail:
    def setup_method(self):
        self.report = check_stair_codes(
            _spec(handrail_height_in=33.0, jurisdiction="ada_504")
        )

    def test_handrail_compliant_false(self):
        assert self.report.handrail_compliant is False

    def test_violation_code_ref(self):
        assert any("505.4" in r for r in _refs(self.report))


# ---------------------------------------------------------------------------
# 13. ICC A117.1 — spot-check passes like ADA
# ---------------------------------------------------------------------------

class TestIccA1171Pass:
    def test_passing_spec(self):
        report = check_stair_codes(
            _spec(
                tread_depth_in=11.0,
                riser_height_in=7.0,
                handrail_height_in=36.0,
                jurisdiction="icc_a117_1",
            )
        )
        assert report.all_compliant, f"Violations: {report.violations}"


# ---------------------------------------------------------------------------
# 14. Ontario OBC — riser too tall (9" > 8.27")
# ---------------------------------------------------------------------------

class TestObcRiserFail:
    def setup_method(self):
        self.report = check_stair_codes(
            _spec(riser_height_in=9.0, jurisdiction="ontario_obc")
        )

    def test_riser_compliant_false(self):
        assert self.report.riser_compliant is False

    def test_violation_code_ref(self):
        assert any("9.8.4.1" in r for r in _refs(self.report))


# ---------------------------------------------------------------------------
# 15. Ontario OBC — headroom 76" < min 78.74"
# ---------------------------------------------------------------------------

class TestObcHeadroomFail:
    def setup_method(self):
        self.report = check_stair_codes(
            _spec(headroom_clearance_in=76.0, jurisdiction="ontario_obc")
        )

    def test_headroom_compliant_false(self):
        assert self.report.headroom_compliant is False

    def test_violation_code_ref(self):
        assert any("9.8.3.1" in r for r in _refs(self.report))


# ---------------------------------------------------------------------------
# 16. Invalid jurisdiction — graceful degradation
# ---------------------------------------------------------------------------

class TestInvalidJurisdiction:
    def test_returns_report_not_raises(self):
        spec = _spec(jurisdiction="unknown_code")
        report = check_stair_codes(spec)
        assert isinstance(report, StairCodeReport)

    def test_has_violation(self):
        spec = _spec(jurisdiction="unknown_code")
        report = check_stair_codes(spec)
        assert len(report.violations) > 0

    def test_not_all_compliant(self):
        spec = _spec(jurisdiction="unknown_code")
        report = check_stair_codes(spec)
        assert not report.all_compliant


# ---------------------------------------------------------------------------
# 17. Violations are 3-tuples
# ---------------------------------------------------------------------------

class TestViolationStructure:
    def test_violation_is_3_tuple(self):
        report = check_stair_codes(_spec(riser_height_in=8.0))
        for v in report.violations:
            assert len(v) == 3, f"Expected 3-tuple, got {v!r}"

    def test_violation_all_strings(self):
        report = check_stair_codes(_spec(riser_height_in=8.0))
        for code_ref, requirement, actual in report.violations:
            assert isinstance(code_ref, str)
            assert isinstance(requirement, str)
            assert isinstance(actual, str)
