"""
Tests for kerf_cad_core.gdt.composite_tolerance_check.

Validates ASME Y14.5-2018 composite (stacked) feature control frames:
  PLTZF (Pattern-Locating Tolerance Zone Framework)  — segment[0]
  FRTZF (Feature-Relating Tolerance Zone Framework)  — segment[1+]

Rules tested:
  R1 — all segments must share the same geometric symbol (§10.5.2(a))
  R2 — lower segment tol ≤ upper segment tol (§10.5.1 Note 2)
  R3 — lower segment datum_refs ⊆ upper segment datum_refs (§10.5.1(b))

Pure-Python, hermetic — no OCC, no DB, no network.
"""
from __future__ import annotations

import pytest

from kerf_cad_core.gdt.composite_tolerance_check import (
    CompositeTolSegment,
    CompositeFrameSpec,
    CompositeFrameValidationReport,
    validate_composite_frame,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _seg(symbol="position", tol=0.5, datums=None, mc="RFS"):
    return CompositeTolSegment(
        symbol=symbol,
        tol_value_mm=tol,
        datum_refs=datums if datums is not None else [],
        material_condition=mc,
    )


def _spec(feature_id="test-feature", *segments):
    return CompositeFrameSpec(feature_id=feature_id, segments=list(segments))


# ---------------------------------------------------------------------------
# 1. CompositeTolSegment dataclass
# ---------------------------------------------------------------------------

class TestCompositeTolSegment:
    def test_valid_position_segment(self):
        s = _seg("position", 0.5, ["A", "B", "C"])
        assert s.symbol == "position"
        assert s.tol_value_mm == 0.5
        assert s.datum_refs == ["A", "B", "C"]
        assert s.material_condition == "RFS"

    def test_valid_profile_surface_segment(self):
        s = _seg("profile_surface", 1.0, ["A"])
        assert s.symbol == "profile_surface"

    def test_valid_profile_line_segment(self):
        s = _seg("profile_line", 0.2, [])
        assert s.symbol == "profile_line"

    def test_invalid_symbol_raises(self):
        with pytest.raises(ValueError, match="symbol"):
            _seg("flatness", 0.1)

    def test_zero_tol_raises(self):
        with pytest.raises(ValueError, match="tol_value_mm"):
            _seg("position", 0.0)

    def test_negative_tol_raises(self):
        with pytest.raises(ValueError, match="tol_value_mm"):
            _seg("position", -0.1)

    def test_invalid_material_condition_raises(self):
        with pytest.raises(ValueError, match="material_condition"):
            _seg("position", 0.5, ["A"], mc="BOTH")

    def test_mmc_material_condition(self):
        s = _seg("position", 0.5, ["A"], mc="MMC")
        assert s.material_condition == "MMC"

    def test_lmc_material_condition(self):
        s = _seg("position", 0.5, ["A"], mc="LMC")
        assert s.material_condition == "LMC"

    def test_datum_refs_normalised_upper(self):
        s = _seg("position", 0.5, ["a", "b"])
        assert s.datum_refs == ["A", "B"]

    def test_datum_refs_whitespace_stripped(self):
        s = _seg("position", 0.5, ["  A  ", " B"])
        assert s.datum_refs == ["A", "B"]

    def test_to_dict_round_trip(self):
        s = _seg("position", 0.3, ["A", "B"], mc="MMC")
        s2 = CompositeTolSegment.from_dict(s.to_dict())
        assert s2.symbol == "position"
        assert s2.tol_value_mm == 0.3
        assert s2.datum_refs == ["A", "B"]
        assert s2.material_condition == "MMC"


# ---------------------------------------------------------------------------
# 2. CompositeFrameSpec dataclass
# ---------------------------------------------------------------------------

class TestCompositeFrameSpec:
    def test_basic_construction(self):
        spec = _spec("hole-1", _seg("position", 0.5, ["A", "B", "C"]), _seg("position", 0.1, ["A"]))
        assert spec.feature_id == "hole-1"
        assert len(spec.segments) == 2

    def test_empty_feature_id_raises(self):
        with pytest.raises(ValueError, match="feature_id"):
            CompositeFrameSpec(feature_id="", segments=[])

    def test_whitespace_feature_id_raises(self):
        with pytest.raises(ValueError, match="feature_id"):
            CompositeFrameSpec(feature_id="   ", segments=[])

    def test_to_dict_round_trip(self):
        spec = _spec(
            "pattern-B",
            _seg("profile_surface", 0.8, ["A", "B"]),
            _seg("profile_surface", 0.2, ["A"]),
        )
        d = spec.to_dict()
        spec2 = CompositeFrameSpec.from_dict(d)
        assert spec2.feature_id == "pattern-B"
        assert len(spec2.segments) == 2
        assert spec2.segments[0].symbol == "profile_surface"
        assert spec2.segments[1].tol_value_mm == 0.2


# ---------------------------------------------------------------------------
# 3. CompositeFrameValidationReport dataclass
# ---------------------------------------------------------------------------

class TestCompositeFrameValidationReport:
    def test_valid_report(self):
        r = CompositeFrameValidationReport(valid=True)
        assert r.violations == []
        assert "§10.5" in r.standard_section
        assert r.honest_caveat

    def test_invalid_report_has_violations(self):
        r = CompositeFrameValidationReport(valid=False, violations=["R1: something"])
        assert not r.valid
        assert len(r.violations) == 1

    def test_to_dict(self):
        r = CompositeFrameValidationReport(valid=True)
        d = r.to_dict()
        assert d["valid"] is True
        assert isinstance(d["violations"], list)
        assert "standard_section" in d
        assert "honest_caveat" in d


# ---------------------------------------------------------------------------
# 4. validate_composite_frame — valid cases
# ---------------------------------------------------------------------------

class TestValidCases:
    def test_valid_composite_position_two_segment(self):
        """
        Classic §10.5.2 example:
          |⌖|0.5|A|B|C|   ← PLTZF: locates and orients the pattern
          |⌖|0.1|A|B|     ← FRTZF: refines orientation (A+B only, subset)
        """
        spec = _spec(
            "bore-pattern",
            _seg("position", 0.5, ["A", "B", "C"]),
            _seg("position", 0.1, ["A", "B"]),
        )
        report = validate_composite_frame(spec)
        assert report.valid is True
        assert report.violations == []

    def test_valid_composite_profile_surface(self):
        """
        §11.6 composite profile example:
          |⌓|1.0|A|B|C|   ← PLTZF
          |⌓|0.3|A|      ← FRTZF refines to single orientation datum
        """
        spec = _spec(
            "contoured-surface",
            _seg("profile_surface", 1.0, ["A", "B", "C"]),
            _seg("profile_surface", 0.3, ["A"]),
        )
        report = validate_composite_frame(spec)
        assert report.valid is True

    def test_valid_frtzf_no_datums(self):
        """
        FRTZF with empty datum refs = freely-relating (§10.5.2 Note 1).
        This is valid — no subset violation since empty ⊆ anything.
        """
        spec = _spec(
            "pattern-free",
            _seg("position", 0.5, ["A", "B", "C"]),
            _seg("position", 0.1, []),
        )
        report = validate_composite_frame(spec)
        assert report.valid is True

    def test_valid_three_tier_composite(self):
        """
        Multi-tier: three segments with shrinking tolerances and subsets.
        """
        spec = _spec(
            "three-tier",
            _seg("position", 1.0, ["A", "B", "C"]),
            _seg("position", 0.5, ["A", "B"]),
            _seg("position", 0.2, ["A"]),
        )
        report = validate_composite_frame(spec)
        assert report.valid is True

    def test_valid_equal_tol_segments(self):
        """
        Equal tolerance values should pass (≤ not <).
        """
        spec = _spec(
            "equal-tol",
            _seg("position", 0.5, ["A", "B", "C"]),
            _seg("position", 0.5, ["A"]),
        )
        report = validate_composite_frame(spec)
        assert report.valid is True

    def test_valid_profile_line_composite(self):
        spec = _spec(
            "line-profile",
            _seg("profile_line", 0.4, ["A", "B"]),
            _seg("profile_line", 0.1, ["A"]),
        )
        report = validate_composite_frame(spec)
        assert report.valid is True


# ---------------------------------------------------------------------------
# 5. validate_composite_frame — R1 violations (symbol mismatch)
# ---------------------------------------------------------------------------

class TestR1SymbolMismatch:
    def test_position_and_profile_surface(self):
        spec = _spec(
            "bad-symbols",
            _seg("position", 0.5, ["A", "B"]),
            _seg("profile_surface", 0.1, ["A"]),
        )
        report = validate_composite_frame(spec)
        assert report.valid is False
        assert any("R1" in v for v in report.violations)
        assert any("symbol" in v.lower() for v in report.violations)

    def test_profile_surface_and_profile_line(self):
        spec = _spec(
            "bad-mixed",
            _seg("profile_surface", 0.5, ["A"]),
            _seg("profile_line", 0.1, ["A"]),
        )
        report = validate_composite_frame(spec)
        assert report.valid is False
        assert any("R1" in v for v in report.violations)

    def test_position_and_profile_line(self):
        spec = _spec(
            "pos-line-mix",
            _seg("position", 0.6, ["A", "B"]),
            _seg("profile_line", 0.2, ["A"]),
        )
        report = validate_composite_frame(spec)
        assert report.valid is False
        assert any("R1" in v for v in report.violations)


# ---------------------------------------------------------------------------
# 6. validate_composite_frame — R2 violations (tolerance not shrinking)
# ---------------------------------------------------------------------------

class TestR2ToleranceNotShrinking:
    def test_frtzf_larger_than_pltzf(self):
        """
        |⌖|0.5|A|B|C| PLTZF
        |⌖|0.7|A|B|   FRTZF — 0.7 > 0.5, invalid
        """
        spec = _spec(
            "bad-tol",
            _seg("position", 0.5, ["A", "B", "C"]),
            _seg("position", 0.7, ["A", "B"]),
        )
        report = validate_composite_frame(spec)
        assert report.valid is False
        assert any("R2" in v for v in report.violations)
        assert any("0.7" in v for v in report.violations)

    def test_middle_segment_too_large(self):
        """Three-tier: middle segment is fine but third is too large."""
        spec = _spec(
            "three-tier-bad",
            _seg("position", 1.0, ["A", "B", "C"]),
            _seg("position", 0.5, ["A", "B"]),
            _seg("position", 0.8, ["A"]),   # 0.8 > 0.5 — invalid
        )
        report = validate_composite_frame(spec)
        assert report.valid is False
        assert any("R2" in v for v in report.violations)

    def test_frtzf_exactly_equal_to_pltzf_is_valid(self):
        spec = _spec(
            "equal-ok",
            _seg("position", 0.3, ["A", "B"]),
            _seg("position", 0.3, ["A"]),
        )
        report = validate_composite_frame(spec)
        assert report.valid is True


# ---------------------------------------------------------------------------
# 7. validate_composite_frame — R3 violations (datum not a subset)
# ---------------------------------------------------------------------------

class TestR3DatumNotSubset:
    def test_frtzf_introduces_new_datum(self):
        """
        PLTZF has A|B|C, FRTZF has A|D|E — D and E are new, not allowed.
        """
        spec = _spec(
            "bad-datums",
            _seg("position", 0.5, ["A", "B", "C"]),
            _seg("position", 0.1, ["A", "D", "E"]),
        )
        report = validate_composite_frame(spec)
        assert report.valid is False
        assert any("R3" in v for v in report.violations)
        # The violation message should mention the new datums D or E
        combined = " ".join(report.violations)
        assert "D" in combined or "E" in combined

    def test_frtzf_introduces_single_new_datum(self):
        spec = _spec(
            "one-new-datum",
            _seg("position", 0.5, ["A", "B"]),
            _seg("position", 0.1, ["A", "B", "C"]),  # C is new
        )
        report = validate_composite_frame(spec)
        assert report.valid is False
        assert any("R3" in v for v in report.violations)

    def test_frtzf_subset_is_valid(self):
        """A|B is a proper subset of A|B|C — valid."""
        spec = _spec(
            "good-subset",
            _seg("position", 0.5, ["A", "B", "C"]),
            _seg("position", 0.1, ["A", "B"]),
        )
        report = validate_composite_frame(spec)
        assert report.valid is True

    def test_frtzf_single_datum_from_pltzf_valid(self):
        spec = _spec(
            "single-datum",
            _seg("position", 0.5, ["A", "B", "C"]),
            _seg("position", 0.1, ["A"]),
        )
        report = validate_composite_frame(spec)
        assert report.valid is True

    def test_multi_tier_third_segment_adds_datum(self):
        """
        Three-tier where the third segment introduces a datum not in second.
        Second is a valid subset of first (A|B ⊆ A|B|C).
        Third (A|B|D) — D not in second (A|B) — violation on segment[2].
        """
        spec = _spec(
            "three-bad",
            _seg("position", 1.0, ["A", "B", "C"]),
            _seg("position", 0.5, ["A", "B"]),
            _seg("position", 0.2, ["A", "B", "D"]),   # D not in A|B
        )
        report = validate_composite_frame(spec)
        assert report.valid is False
        assert any("R3" in v for v in report.violations)


# ---------------------------------------------------------------------------
# 8. validate_composite_frame — multiple violations at once
# ---------------------------------------------------------------------------

class TestMultipleViolations:
    def test_symbol_and_tol_both_wrong(self):
        spec = _spec(
            "double-error",
            _seg("position", 0.5, ["A", "B"]),
            _seg("profile_surface", 0.9, ["A"]),  # R1 + R2
        )
        report = validate_composite_frame(spec)
        assert report.valid is False
        assert len(report.violations) >= 2

    def test_all_three_rules_violated(self):
        spec = _spec(
            "triple-error",
            _seg("position", 0.5, ["A", "B"]),
            _seg("profile_surface", 0.9, ["A", "C"]),  # R1 (symbol) + R2 (0.9>0.5) + R3 (C new)
        )
        report = validate_composite_frame(spec)
        assert report.valid is False
        assert len(report.violations) >= 3


# ---------------------------------------------------------------------------
# 9. validate_composite_frame — structural / edge cases
# ---------------------------------------------------------------------------

class TestStructuralEdgeCases:
    def test_only_one_segment_invalid(self):
        spec = CompositeFrameSpec(
            feature_id="one-seg",
            segments=[_seg("position", 0.5, ["A"])],
        )
        report = validate_composite_frame(spec)
        assert report.valid is False
        assert any("2" in v for v in report.violations)   # requires 2 segments

    def test_empty_segments_invalid(self):
        spec = CompositeFrameSpec(feature_id="no-segs", segments=[])
        report = validate_composite_frame(spec)
        assert report.valid is False

    def test_report_standard_section_references_asme(self):
        spec = _spec(
            "ref-check",
            _seg("position", 0.5, ["A"]),
            _seg("position", 0.1, ["A"]),
        )
        report = validate_composite_frame(spec)
        assert "ASME" in report.standard_section
        assert "10.5" in report.standard_section

    def test_honest_caveat_present(self):
        spec = _spec(
            "caveat-check",
            _seg("position", 0.5, ["A"]),
            _seg("position", 0.1, ["A"]),
        )
        report = validate_composite_frame(spec)
        assert len(report.honest_caveat) > 20  # not empty

    def test_from_dict_round_trip_then_validate(self):
        """Serialise to dict, deserialise, then validate."""
        spec = _spec(
            "rt-validate",
            _seg("position", 0.5, ["A", "B", "C"]),
            _seg("position", 0.1, ["A", "B"]),
        )
        spec2 = CompositeFrameSpec.from_dict(spec.to_dict())
        report = validate_composite_frame(spec2)
        assert report.valid is True

    def test_re_export_from_gdt_init(self):
        """Ensure symbols are re-exported through gdt/__init__.py."""
        from kerf_cad_core.gdt import (
            CompositeTolSegment as CTS,
            CompositeFrameSpec as CFS,
            CompositeFrameValidationReport as CFVR,
            validate_composite_frame as vcf,
        )
        s = CTS(symbol="position", tol_value_mm=0.5, datum_refs=["A"])
        spec = CFS(feature_id="init-test", segments=[s, CTS(symbol="position", tol_value_mm=0.2)])
        r = vcf(spec)
        assert r.valid is True
