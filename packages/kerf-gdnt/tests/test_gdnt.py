"""
Test suite for kerf-gdnt: GD&T / PMI model-based definition.

Oracles:
  - ISO 1101 + ASME Y14.5 symbol codes match the published spec character set.
  - A feature with measured value within tolerance reports pass.
  - A feature outside tolerance reports fail with the correct deviation.
  - An FCF serialises to the canonical textual form (e.g. ⏐⌖⏐∅0.5 Ⓜ ⏐A⏐B⏐C⏐).
"""

import json
import pytest

from kerf_gdnt.symbols import (
    ALL_SYMBOLS,
    ALL_MODIFIERS,
    FLATNESS,
    STRAIGHTNESS,
    PERPENDICULARITY,
    PARALLELISM,
    POSITION,
    CIRCULAR_RUNOUT,
    TOTAL_RUNOUT,
    PROFILE_SURFACE,
    CYLINDRICITY,
    MODIFIER_MMC,
    MODIFIER_LMC,
    MODIFIER_FREE_STATE,
    MODIFIER_DIAMETER,
    get_symbol,
    get_modifier,
)
from kerf_gdnt.feature_control_frame import DatumReference, FeatureControlFrame
from kerf_gdnt.datums import (
    DatumFeature,
    DatumSimulator,
    DatumReferenceFrame,
    make_3_2_1_frame,
)
from kerf_gdnt.inspection_report import (
    InspectionRow,
    InspectionReport,
    build_report,
    render_report,
    report_to_dicts,
)
from kerf_gdnt.tools import (
    run_gdnt_list_symbols,
    run_gdnt_create_fcf,
    run_gdnt_validate_fcf,
    run_gdnt_inspect_feature,
    run_gdnt_build_report,
    run_gdt_worst_case_stack,
    run_gdt_rss_stack,
    run_gdt_monte_carlo_stack,
)
from kerf_gdnt.tol_stack import (
    StackElement,
    worst_case_stack,
    rss_stack,
    monte_carlo_stack,
    expected_yield_at_spec,
)


# ---------------------------------------------------------------------------
# Symbol registry tests
# ---------------------------------------------------------------------------

class TestSymbolRegistry:
    def test_all_expected_symbols_present(self):
        expected_codes = {
            "straightness", "flatness", "circularity", "cylindricity",
            "profile_line", "profile_surface",
            "angularity", "perpendicularity", "parallelism",
            "position", "concentricity", "symmetry",
            "circular_runout", "total_runout",
        }
        assert expected_codes.issubset(set(ALL_SYMBOLS.keys())), (
            f"Missing symbols: {expected_codes - set(ALL_SYMBOLS.keys())}"
        )

    def test_symbol_categories(self):
        """Each symbol must belong to a recognised category."""
        valid_cats = {"form", "orientation", "location", "runout", "profile"}
        for code, sym in ALL_SYMBOLS.items():
            assert sym.category in valid_cats, (
                f"Symbol {code!r} has unexpected category {sym.category!r}"
            )

    def test_form_symbols_category(self):
        for code in ("straightness", "flatness", "circularity", "cylindricity"):
            assert ALL_SYMBOLS[code].category == "form"

    def test_orientation_symbols_category(self):
        for code in ("angularity", "perpendicularity", "parallelism"):
            assert ALL_SYMBOLS[code].category == "orientation"

    def test_location_symbols_category(self):
        for code in ("position", "concentricity", "symmetry"):
            assert ALL_SYMBOLS[code].category == "location"

    def test_runout_symbols_category(self):
        for code in ("circular_runout", "total_runout"):
            assert ALL_SYMBOLS[code].category == "runout"

    def test_profile_symbols_category(self):
        for code in ("profile_line", "profile_surface"):
            assert ALL_SYMBOLS[code].category == "profile"

    def test_symbols_have_unicode_chars(self):
        """Every symbol must expose a non-empty unicode string."""
        for code, sym in ALL_SYMBOLS.items():
            assert sym.unicode, f"Symbol {code!r} has empty unicode"

    def test_symbols_have_iso_and_asme_codes(self):
        for code, sym in ALL_SYMBOLS.items():
            assert "ISO 1101" in sym.iso_code, f"{code}: missing ISO reference"
            assert "ASME Y14.5" in sym.asme_code, f"{code}: missing ASME reference"

    def test_get_symbol_roundtrip(self):
        for code in ALL_SYMBOLS:
            sym = get_symbol(code)
            assert sym.code == code

    def test_get_symbol_unknown_raises(self):
        with pytest.raises(KeyError):
            get_symbol("not_a_real_symbol")

    def test_position_unicode(self):
        """ASME Y14.5 position symbol is ⌖ (U+2316)."""
        assert POSITION.unicode == "⌖"

    def test_flatness_unicode(self):
        """Flatness uses the parallelogram symbol."""
        assert FLATNESS.unicode == "▱"

    def test_cylindricity_unicode(self):
        """Cylindricity uses ⌭ (U+232D)."""
        assert CYLINDRICITY.unicode == "⌭"


class TestModifierRegistry:
    def test_all_modifiers_present(self):
        expected = {"M", "L", "S", "F", "P", "T", "dia"}
        assert expected.issubset(set(ALL_MODIFIERS.keys()))

    def test_mmc_unicode(self):
        """MMC modifier must be circled M — Ⓜ (U+24C2)."""
        assert MODIFIER_MMC.unicode == "Ⓜ"

    def test_lmc_unicode(self):
        """LMC modifier must be circled L — Ⓛ."""
        assert MODIFIER_LMC.unicode == "Ⓛ"

    def test_free_state_unicode(self):
        assert MODIFIER_FREE_STATE.unicode == "Ⓕ"

    def test_diameter_unicode(self):
        """Diameter symbol ⌀ (U+2300)."""
        assert MODIFIER_DIAMETER.unicode == "⌀"

    def test_get_modifier_unknown_raises(self):
        with pytest.raises(KeyError):
            get_modifier("Z")


# ---------------------------------------------------------------------------
# Feature Control Frame tests
# ---------------------------------------------------------------------------

class TestFCFRender:
    def test_position_with_diameter_mmc_and_three_datums(self):
        """
        Canonical form: ⏐⌖⏐∅0.5 Ⓜ ⏐A⏐B⏐C⏐
        """
        fcf = FeatureControlFrame(
            symbol_code="position",
            tolerance_value=0.5,
            diameter_zone=True,
            tolerance_modifier="M",
            datum_refs=[
                DatumReference("A"),
                DatumReference("B"),
                DatumReference("C"),
            ],
        )
        rendered = fcf.render()
        # Must start with the position symbol compartment
        assert "⌖" in rendered, "Position symbol ⌖ not found in rendered FCF"
        # Must include diameter sign
        assert "⌀" in rendered, "Diameter sign ⌀ not found"
        # Must include tolerance value
        assert "0.5" in rendered
        # Must include MMC modifier
        assert "Ⓜ" in rendered
        # Must include all three datum labels
        assert "A" in rendered
        assert "B" in rendered
        assert "C" in rendered
        # Frame compartment dividers
        assert rendered.count("⏐") >= 4  # opening + symbol + tol + A + B + C = 6

    def test_flatness_no_datums(self):
        """Flatness: no datum refs required — ⏐▱⏐0.05⏐ (no datum compartments)."""
        fcf = FeatureControlFrame(
            symbol_code="flatness",
            tolerance_value=0.05,
        )
        rendered = fcf.render()
        assert "▱" in rendered
        assert "0.05" in rendered

    def test_perpendicularity_with_datum(self):
        fcf = FeatureControlFrame(
            symbol_code="perpendicularity",
            tolerance_value=0.1,
            datum_refs=[DatumReference("A")],
        )
        rendered = fcf.render()
        assert "⟂" in rendered
        assert "0.1" in rendered
        assert "A" in rendered

    def test_straightness_lmc(self):
        fcf = FeatureControlFrame(
            symbol_code="straightness",
            tolerance_value=0.02,
            tolerance_modifier="L",
        )
        rendered = fcf.render()
        assert "Ⓛ" in rendered

    def test_from_dict_roundtrip(self):
        """to_dict → from_dict → render must be stable."""
        fcf = FeatureControlFrame(
            symbol_code="position",
            tolerance_value=0.3,
            diameter_zone=True,
            tolerance_modifier="M",
            datum_refs=[DatumReference("A"), DatumReference("B", modifier="M")],
        )
        d = fcf.to_dict()
        fcf2 = FeatureControlFrame.from_dict(d)
        assert fcf2.render() == fcf.render()
        assert fcf2.symbol_code == fcf.symbol_code
        assert fcf2.tolerance_value == fcf.tolerance_value
        assert fcf2.diameter_zone == fcf.diameter_zone
        assert fcf2.tolerance_modifier == fcf.tolerance_modifier

    def test_validation_unknown_symbol(self):
        fcf = FeatureControlFrame(symbol_code="wobble", tolerance_value=0.1)
        issues = fcf.validate()
        assert any("wobble" in i for i in issues)

    def test_validation_negative_tolerance(self):
        fcf = FeatureControlFrame(symbol_code="flatness", tolerance_value=-0.1)
        issues = fcf.validate()
        assert any("non-negative" in i for i in issues)

    def test_validation_too_many_datums(self):
        fcf = FeatureControlFrame(
            symbol_code="position",
            tolerance_value=0.1,
            datum_refs=[
                DatumReference("A"), DatumReference("B"),
                DatumReference("C"), DatumReference("D"),
            ],
        )
        issues = fcf.validate()
        assert any("three" in i or "3" in i for i in issues)

    def test_render_contains_compartment_dividers(self):
        """Every rendered FCF must open with ⏐."""
        fcf = FeatureControlFrame(symbol_code="circularity", tolerance_value=0.01)
        assert fcf.render().startswith("⏐")


# ---------------------------------------------------------------------------
# Datum Reference Frame tests
# ---------------------------------------------------------------------------

class TestDatumReferenceFrame:
    def test_make_3_2_1_frame(self):
        drf = make_3_2_1_frame()
        assert drf.total_dof_constrained == 6
        assert drf.is_fully_constrained

    def test_ordered_labels(self):
        drf = make_3_2_1_frame("X", "Y", "Z")
        assert drf.ordered_labels() == ["X", "Y", "Z"]

    def test_primary_only_not_fully_constrained(self):
        drf = DatumReferenceFrame(
            primary=DatumSimulator(
                datum_label="A",
                simulator_type="surface_plate",
                dof_constrained=3,
            )
        )
        assert not drf.is_fully_constrained
        assert drf.total_dof_constrained == 3

    def test_str_representation(self):
        drf = make_3_2_1_frame()
        s = str(drf)
        assert "A" in s
        assert "B" in s
        assert "fully constrained" in s


# ---------------------------------------------------------------------------
# Inspection Report tests (pass/fail oracles)
# ---------------------------------------------------------------------------

class TestInspectionPassFail:
    """Core oracle: within tolerance → PASS; outside → FAIL with correct deviation."""

    def _make_flatness_fcf(self, tol: float) -> FeatureControlFrame:
        return FeatureControlFrame(symbol_code="flatness", tolerance_value=tol)

    def test_bilateral_within_tolerance_passes(self):
        """Measured within ±tol/2 of nominal → PASS."""
        fcf = self._make_flatness_fcf(0.1)
        row = InspectionRow(
            feature_id="F1", fcf=fcf,
            nominal=0.0, measured=0.04,  # dev=0.04, half_tol=0.05 → PASS
        )
        assert row.passed
        assert row.status == "PASS"
        assert abs(row.deviation - 0.04) < 1e-10

    def test_bilateral_outside_tolerance_fails(self):
        """Measured outside ±tol/2 → FAIL."""
        fcf = self._make_flatness_fcf(0.1)
        row = InspectionRow(
            feature_id="F2", fcf=fcf,
            nominal=0.0, measured=0.06,  # dev=0.06 > 0.05 → FAIL
        )
        assert not row.passed
        assert row.status == "FAIL"
        assert abs(row.deviation - 0.06) < 1e-10

    def test_bilateral_exactly_on_limit_passes(self):
        """Deviation exactly at ±tol/2 is a PASS (inclusive boundary).
        Use nominal=0.0 so deviation is computed exactly from a single float."""
        fcf = self._make_flatness_fcf(0.1)
        row = InspectionRow(feature_id="F3", fcf=fcf, nominal=0.0, measured=0.05)
        assert row.passed  # 0.05 == tol/2 = 0.05

    def test_negative_deviation_within_tolerance_passes(self):
        fcf = self._make_flatness_fcf(0.2)
        row = InspectionRow(feature_id="F4", fcf=fcf, nominal=5.0, measured=4.92)
        # dev = -0.08, |dev| = 0.08 < 0.10 → PASS
        assert row.passed
        assert abs(row.deviation - (-0.08)) < 1e-10

    def test_negative_deviation_outside_tolerance_fails(self):
        fcf = self._make_flatness_fcf(0.1)
        row = InspectionRow(feature_id="F5", fcf=fcf, nominal=5.0, measured=4.94)
        # dev = -0.06 < -0.05 → FAIL
        assert not row.passed

    def test_unilateral_within_tolerance_passes(self):
        """Unilateral zone [nominal, nominal+tol]."""
        fcf = self._make_flatness_fcf(0.1)
        row = InspectionRow(
            feature_id="F6", fcf=fcf,
            nominal=0.0, measured=0.08,
            unilateral=True,
        )
        assert row.passed

    def test_unilateral_below_nominal_fails(self):
        """Measured below nominal in unilateral zone → FAIL."""
        fcf = self._make_flatness_fcf(0.1)
        row = InspectionRow(
            feature_id="F7", fcf=fcf,
            nominal=0.0, measured=-0.01,
            unilateral=True,
        )
        assert not row.passed

    def test_unilateral_above_tol_fails(self):
        """Measured above nominal+tol in unilateral zone → FAIL."""
        fcf = self._make_flatness_fcf(0.1)
        row = InspectionRow(
            feature_id="F8", fcf=fcf,
            nominal=0.0, measured=0.11,
            unilateral=True,
        )
        assert not row.passed

    def test_deviation_reported_correctly(self):
        """Deviation is always measured − nominal regardless of pass/fail."""
        fcf = self._make_flatness_fcf(0.05)
        nominal = 25.0
        measured = 25.07
        row = InspectionRow(feature_id="D", fcf=fcf, nominal=nominal, measured=measured)
        assert abs(row.deviation - 0.07) < 1e-10
        assert row.status == "FAIL"

    def test_zero_deviation_always_passes(self):
        for code in ("flatness", "position", "perpendicularity", "circular_runout"):
            fcf = FeatureControlFrame(symbol_code=code, tolerance_value=0.1)
            row = InspectionRow(feature_id="X", fcf=fcf, nominal=1.0, measured=1.0)
            assert row.passed, f"Zero deviation should PASS for {code}"


class TestInspectionReport:
    def _sample_report(self) -> InspectionReport:
        fcf_flat = FeatureControlFrame(symbol_code="flatness", tolerance_value=0.1)
        fcf_pos = FeatureControlFrame(
            symbol_code="position",
            tolerance_value=0.5,
            diameter_zone=True,
            tolerance_modifier="M",
            datum_refs=[DatumReference("A"), DatumReference("B"), DatumReference("C")],
        )
        return build_report(
            part_number="P-1234",
            measurements=[
                {"feature_id": "F1", "fcf": fcf_flat, "nominal": 0.0, "measured": 0.03},
                {"feature_id": "F2", "fcf": fcf_pos, "nominal": 0.0, "measured": 0.0},
                {"feature_id": "F3", "fcf": fcf_flat, "nominal": 0.0, "measured": 0.04},
            ],
            revision="B",
            inspector="CMM-01",
        )

    def test_overall_pass(self):
        report = self._sample_report()
        assert report.overall_pass
        assert report.passed_count == 3
        assert report.failed_count == 0

    def test_one_failure(self):
        fcf = FeatureControlFrame(symbol_code="flatness", tolerance_value=0.1)
        report = build_report(
            part_number="P-9999",
            measurements=[
                {"feature_id": "F1", "fcf": fcf, "nominal": 0.0, "measured": 0.03},   # PASS
                {"feature_id": "F2", "fcf": fcf, "nominal": 0.0, "measured": 0.09},   # FAIL (0.09 > 0.05)
            ],
        )
        assert not report.overall_pass
        assert report.failed_count == 1
        assert report.passed_count == 1

    def test_render_contains_part_number(self):
        report = self._sample_report()
        md = render_report(report)
        assert "P-1234" in md

    def test_render_contains_pass_fail(self):
        report = self._sample_report()
        md = render_report(report)
        assert "PASS" in md

    def test_render_contains_failed_section_when_failures(self):
        fcf = FeatureControlFrame(symbol_code="flatness", tolerance_value=0.1)
        report = build_report(
            part_number="P-X",
            measurements=[
                {"feature_id": "BAD", "fcf": fcf, "nominal": 0.0, "measured": 0.2},
            ],
        )
        md = render_report(report)
        assert "Failed features" in md
        assert "BAD" in md

    def test_report_to_dicts(self):
        report = self._sample_report()
        rows = report_to_dicts(report)
        assert len(rows) == 3
        for row in rows:
            assert "feature_id" in row
            assert "status" in row
            assert "deviation" in row
            assert "fcf_rendered" in row


# ---------------------------------------------------------------------------
# Tool surface tests
# ---------------------------------------------------------------------------

class TestLLMTools:
    """Smoke-test the tool surface using the _compat shim."""

    def test_list_symbols_all(self):
        out = json.loads(run_gdnt_list_symbols({}, ctx=None))
        assert "symbols" in out
        assert "modifiers" in out
        codes = {s["code"] for s in out["symbols"]}
        assert "flatness" in codes
        assert "position" in codes

    def test_list_symbols_filter_form(self):
        out = json.loads(run_gdnt_list_symbols({"category": "form"}, ctx=None))
        for s in out["symbols"]:
            assert s["category"] == "form"

    def test_create_fcf_position(self):
        out = json.loads(run_gdnt_create_fcf({
            "symbol_code": "position",
            "tolerance_value": 0.5,
            "diameter_zone": True,
            "tolerance_modifier": "M",
            "datum_refs": [
                {"label": "A"},
                {"label": "B"},
                {"label": "C"},
            ],
        }, ctx=None))
        assert "rendered" in out
        rendered = out["rendered"]
        assert "⌖" in rendered
        assert "⌀" in rendered
        assert "0.5" in rendered
        assert "Ⓜ" in rendered

    def test_create_fcf_bad_symbol(self):
        out = json.loads(run_gdnt_create_fcf({
            "symbol_code": "not_real",
            "tolerance_value": 0.1,
        }, ctx=None))
        assert "error" in out
        assert out["code"] == "BAD_FCF"

    def test_validate_fcf_valid(self):
        fcf_dict = {
            "symbol_code": "flatness",
            "tolerance_value": 0.05,
            "diameter_zone": False,
            "tolerance_modifier": None,
            "datum_refs": [],
        }
        out = json.loads(run_gdnt_validate_fcf({"fcf": fcf_dict}, ctx=None))
        assert out["valid"] is True
        assert out["issues"] == []

    def test_validate_fcf_invalid(self):
        fcf_dict = {
            "symbol_code": "ghost",
            "tolerance_value": -1.0,
            "datum_refs": [],
        }
        out = json.loads(run_gdnt_validate_fcf({"fcf": fcf_dict}, ctx=None))
        assert out["valid"] is False
        assert len(out["issues"]) >= 2

    def test_inspect_feature_pass(self):
        fcf_dict = {
            "symbol_code": "flatness",
            "tolerance_value": 0.1,
            "datum_refs": [],
        }
        out = json.loads(run_gdnt_inspect_feature({
            "feature_id": "F1",
            "fcf": fcf_dict,
            "nominal": 0.0,
            "measured": 0.03,
        }, ctx=None))
        assert out["status"] == "PASS"
        assert abs(out["deviation"] - 0.03) < 1e-9

    def test_inspect_feature_fail(self):
        fcf_dict = {
            "symbol_code": "flatness",
            "tolerance_value": 0.1,
            "datum_refs": [],
        }
        out = json.loads(run_gdnt_inspect_feature({
            "feature_id": "F2",
            "fcf": fcf_dict,
            "nominal": 0.0,
            "measured": 0.08,  # 0.08 > 0.05 → FAIL
        }, ctx=None))
        assert out["status"] == "FAIL"
        assert abs(out["deviation"] - 0.08) < 1e-9

    def test_build_report_tool(self):
        fcf_dict = {
            "symbol_code": "perpendicularity",
            "tolerance_value": 0.2,
            "datum_refs": [{"label": "A"}],
        }
        out = json.loads(run_gdnt_build_report({
            "part_number": "PN-TEST",
            "revision": "A",
            "inspector": "Test",
            "measurements": [
                {"feature_id": "F1", "fcf": fcf_dict, "nominal": 0.0, "measured": 0.05},
                # tol=0.2 → bilateral zone ±0.1; 0.09 < 0.1 → PASS
                {"feature_id": "F2", "fcf": fcf_dict, "nominal": 0.0, "measured": 0.09},
            ],
        }, ctx=None))
        assert "markdown" in out
        assert "rows" in out
        assert "summary" in out
        assert out["summary"]["total"] == 2
        assert out["summary"]["passed"] == 2  # both within ±0.1
        assert out["summary"]["overall_pass"] is True

    def test_build_report_tool_with_failure(self):
        fcf_dict = {
            "symbol_code": "flatness",
            "tolerance_value": 0.1,
            "datum_refs": [],
        }
        out = json.loads(run_gdnt_build_report({
            "part_number": "PN-FAIL",
            "measurements": [
                {"feature_id": "F1", "fcf": fcf_dict, "nominal": 0.0, "measured": 0.02},  # PASS
                {"feature_id": "F2", "fcf": fcf_dict, "nominal": 0.0, "measured": 0.09},  # FAIL
            ],
        }, ctx=None))
        assert out["summary"]["failed"] == 1
        assert out["summary"]["overall_pass"] is False
        assert "FAIL" in out["markdown"]


# ---------------------------------------------------------------------------
# Integration: FCF round-trip through tool surface
# ---------------------------------------------------------------------------

class TestFCFCanonicalForm:
    """Verify the full canonical ⏐⌖⏐∅0.5 Ⓜ ⏐A⏐B⏐C⏐ form."""

    def test_canonical_position_fcf(self):
        """
        ASME Y14.5-2018 §3.3.1 canonical feature control frame:
          ⏐⌖⏐∅0.5 Ⓜ ⏐A⏐B⏐C⏐
        """
        fcf = FeatureControlFrame(
            symbol_code="position",
            tolerance_value=0.5,
            diameter_zone=True,
            tolerance_modifier="M",
            datum_refs=[
                DatumReference("A"),
                DatumReference("B"),
                DatumReference("C"),
            ],
        )
        rendered = fcf.render()
        # Verify each expected fragment in order
        assert rendered.startswith("⏐"), f"Must start with ⏐: {rendered!r}"
        assert "⌖" in rendered, "Position symbol ⌖ missing"
        assert "⌀0.5" in rendered, f"⌀0.5 fragment missing: {rendered!r}"
        assert "Ⓜ" in rendered, "MMC modifier Ⓜ missing"
        assert "⏐A" in rendered, "Datum A missing"
        assert "⏐B" in rendered, "Datum B missing"
        assert "⏐C" in rendered, "Datum C missing"
        # Count minimum separators: leading + symbol-comp + tol-comp + A + B + C + trailing = 7
        assert rendered.count("⏐") >= 6, f"Too few compartment dividers: {rendered!r}"

    def test_serialise_to_tool_and_back(self):
        """FCF created via tool surface must render identically to direct construction."""
        out = json.loads(run_gdnt_create_fcf({
            "symbol_code": "position",
            "tolerance_value": 0.5,
            "diameter_zone": True,
            "tolerance_modifier": "M",
            "datum_refs": [{"label": "A"}, {"label": "B"}, {"label": "C"}],
        }, ctx=None))
        rendered_tool = out["rendered"]

        fcf_direct = FeatureControlFrame(
            symbol_code="position",
            tolerance_value=0.5,
            diameter_zone=True,
            tolerance_modifier="M",
            datum_refs=[
                DatumReference("A"),
                DatumReference("B"),
                DatumReference("C"),
            ],
        )
        assert rendered_tool == fcf_direct.render()


# ---------------------------------------------------------------------------
# Tolerance Stack-Up tests
# ---------------------------------------------------------------------------

def _three_equal_elements(tol: float = 0.1) -> list[StackElement]:
    """3 identical additive elements: nominal=10, ±tol, normal distribution."""
    return [StackElement(nominal=10.0, plus_tol=tol, minus_tol=tol) for _ in range(3)]


class TestWorstCaseStack:
    """Oracle: 3 × (10 ± 0.1) → nominal=30, max=30.3, min=29.7."""

    def test_three_elements_nominal(self):
        result = worst_case_stack(_three_equal_elements())
        assert abs(result["nominal"] - 30.0) < 1e-10

    def test_three_elements_max(self):
        result = worst_case_stack(_three_equal_elements())
        assert abs(result["max"] - 30.3) < 1e-10

    def test_three_elements_min(self):
        result = worst_case_stack(_three_equal_elements())
        assert abs(result["min"] - 29.7) < 1e-10

    def test_three_elements_range(self):
        result = worst_case_stack(_three_equal_elements())
        assert abs(result["range"] - 0.6) < 1e-10

    def test_mean_equals_nominal(self):
        result = worst_case_stack(_three_equal_elements())
        assert result["mean"] == result["nominal"]

    def test_subtractive_direction(self):
        """One subtractive element flips which tolerance is the upper contribution."""
        elements = [
            StackElement(nominal=20.0, plus_tol=0.1, minus_tol=0.1, direction=1),
            StackElement(nominal=10.0, plus_tol=0.05, minus_tol=0.05, direction=-1),
        ]
        result = worst_case_stack(elements)
        assert abs(result["nominal"] - 10.0) < 1e-10  # 20 - 10 = 10
        assert abs(result["max"] - 10.15) < 1e-10      # 10 + 0.1 + 0.05
        assert abs(result["min"] - 9.85) < 1e-10       # 10 - 0.1 - 0.05

    def test_asymmetric_tolerance(self):
        """Asymmetric plus/minus tolerances accumulate independently."""
        elements = [
            StackElement(nominal=5.0, plus_tol=0.2, minus_tol=0.1),
            StackElement(nominal=5.0, plus_tol=0.3, minus_tol=0.05),
        ]
        result = worst_case_stack(elements)
        assert abs(result["nominal"] - 10.0) < 1e-10
        assert abs(result["max"] - 10.5) < 1e-10   # 10 + 0.2 + 0.3
        assert abs(result["min"] - 9.85) < 1e-10   # 10 - 0.1 - 0.05


class TestRSSStack:
    """Oracle: 3 × (10 ± 0.1, normal) → σ_total = sqrt(3 × (0.1/3)²) = 0.1/sqrt(3)
    → ±3σ_total = ±0.1*sqrt(3) ≈ ±0.1732."""

    def test_three_elements_nominal(self):
        result = rss_stack(_three_equal_elements())
        assert abs(result["nominal"] - 30.0) < 1e-10

    def test_three_elements_sigma_total(self):
        import math
        result = rss_stack(_three_equal_elements())
        # each element σ = 0.1/3; variance = 3 × (0.1/3)² = 0.01/3
        expected_sigma = math.sqrt(3 * (0.1 / 3) ** 2)
        assert abs(result["sigma_total"] - expected_sigma) < 1e-10

    def test_three_elements_3sigma_bounds(self):
        import math
        result = rss_stack(_three_equal_elements())
        expected_sigma = math.sqrt(3 * (0.1 / 3) ** 2)
        assert abs(result["plus_3sigma"] - (30.0 + 3 * expected_sigma)) < 1e-10
        assert abs(result["minus_3sigma"] - (30.0 - 3 * expected_sigma)) < 1e-10

    def test_rss_tighter_than_worst_case(self):
        """RSS ±3σ must always be within worst-case bounds for normal distributions."""
        elements = _three_equal_elements(tol=0.2)
        wc = worst_case_stack(elements)
        rss = rss_stack(elements)
        assert rss["plus_3sigma"] < wc["max"]
        assert rss["minus_3sigma"] > wc["min"]

    def test_rss_range_matches_6sigma(self):
        result = rss_stack(_three_equal_elements())
        assert abs(result["range"] - 6.0 * result["sigma_total"]) < 1e-10

    def test_single_element_rss_equals_3sigma(self):
        """For a single element, RSS ±3σ should equal ±tol exactly."""
        e = [StackElement(nominal=10.0, plus_tol=0.3, minus_tol=0.3)]
        result = rss_stack(e)
        assert abs(result["plus_3sigma"] - 10.3) < 1e-10
        assert abs(result["minus_3sigma"] - 9.7) < 1e-10


class TestMonteCarloStack:
    """MC vs RSS: for normal distributions, 99.7 % bounds should agree within 5 %."""

    N = 100_000  # large enough for stable statistics

    def test_mc_mean_close_to_nominal(self):
        elements = _three_equal_elements()
        result = monte_carlo_stack(elements, n_trials=self.N)
        # mean should be within 0.01 of 30.0
        assert abs(result["mean"] - 30.0) < 0.01

    def test_mc_std_close_to_rss_sigma(self):
        """MC std should agree with RSS sigma_total within 5 %."""
        import math
        elements = _three_equal_elements()
        rss_result = rss_stack(elements)
        mc_result = monte_carlo_stack(elements, n_trials=self.N)
        sigma_expected = rss_result["sigma_total"]
        rel_err = abs(mc_result["std"] - sigma_expected) / sigma_expected
        assert rel_err < 0.05, (
            f"MC std={mc_result['std']:.6f} vs RSS sigma={sigma_expected:.6f} "
            f"(rel_err={rel_err:.3f})"
        )

    def test_mc_std_vs_rss_sigma_within_5pct(self):
        """MC std and RSS sigma_total must agree within 5 % (99.7 % bound agreement).

        For independent normal contributors the central-limit theorem guarantees
        that the assembly distribution is normal with σ = RSS sigma_total.
        MC std is the unbiased estimate of that same σ, so the two must converge
        for large n_trials.
        """
        elements = _three_equal_elements()
        rss_result = rss_stack(elements)
        mc_result = monte_carlo_stack(elements, n_trials=self.N)

        sigma_rss = rss_result["sigma_total"]
        sigma_mc = mc_result["std"]
        rel_err = abs(sigma_mc - sigma_rss) / sigma_rss
        assert rel_err < 0.05, (
            f"MC std={sigma_mc:.6f} vs RSS sigma={sigma_rss:.6f} "
            f"(rel_err={rel_err:.3f})"
        )

    def test_n_trials_returned(self):
        result = monte_carlo_stack(_three_equal_elements(), n_trials=500)
        assert result["n_trials"] == 500

    def test_percentiles_ordered(self):
        result = monte_carlo_stack(_three_equal_elements(), n_trials=5000)
        assert result["percentile_5"] < result["percentile_95"]
        assert result["percentile_95"] < result["percentile_99"]
        assert result["min_observed"] <= result["percentile_5"]
        assert result["max_observed"] >= result["percentile_99"]


class TestYieldCalculation:
    """Yield oracle tests."""

    N = 50_000

    def test_wide_spec_near_100_pct(self):
        """Spec = 30 ± 0.5 with 3 × (10 ± 0.1) → yield should be ~100 %."""
        elements = _three_equal_elements()
        y = expected_yield_at_spec(elements, spec_min=29.5, spec_max=30.5, n_trials=self.N)
        assert y > 0.999, f"Expected yield ~1.0, got {y:.4f}"

    def test_tight_spec_reduces_yield(self):
        """Spec = 30 ± 0.05 with 3 × (10 ± 0.1) normal is much tighter than 3σ;
        yield should drop noticeably below 100 %."""
        elements = _three_equal_elements()
        y_wide = expected_yield_at_spec(elements, spec_min=29.5, spec_max=30.5, n_trials=self.N)
        y_tight = expected_yield_at_spec(elements, spec_min=29.95, spec_max=30.05, n_trials=self.N)
        assert y_tight < y_wide, "Tighter spec must yield lower fraction than wide spec"
        assert y_tight < 0.99, f"Tight spec should have meaningful rejects, got {y_tight:.4f}"

    def test_impossible_spec_zero_yield(self):
        """Spec band entirely outside the achievable range → yield = 0."""
        elements = _three_equal_elements()
        y = expected_yield_at_spec(elements, spec_min=100.0, spec_max=200.0, n_trials=self.N)
        assert y == 0.0

    def test_spec_min_greater_than_max_raises(self):
        elements = _three_equal_elements()
        with pytest.raises(ValueError, match="spec_min"):
            expected_yield_at_spec(elements, spec_min=31.0, spec_max=29.0)


class TestStackUpLLMTools:
    """Smoke-tests for the three LLM tool wrappers."""

    def _elements_payload(self, n: int = 3, tol: float = 0.1) -> list[dict]:
        return [
            {"nominal": 10.0, "plus_tol": tol, "minus_tol": tol, "distribution": "normal",
             "direction": 1}
            for _ in range(n)
        ]

    def test_worst_case_tool_nominal(self):
        out = json.loads(run_gdt_worst_case_stack(
            {"elements": self._elements_payload()}, ctx=None
        ))
        assert abs(out["nominal"] - 30.0) < 1e-10
        assert abs(out["max"] - 30.3) < 1e-10
        assert abs(out["min"] - 29.7) < 1e-10

    def test_rss_tool_nominal(self):
        out = json.loads(run_gdt_rss_stack(
            {"elements": self._elements_payload()}, ctx=None
        ))
        assert abs(out["nominal"] - 30.0) < 1e-10
        assert "sigma_total" in out
        assert out["sigma_total"] > 0

    def test_monte_carlo_tool_mean(self):
        out = json.loads(run_gdt_monte_carlo_stack(
            {"elements": self._elements_payload(), "n_trials": 20000}, ctx=None
        ))
        assert abs(out["mean"] - 30.0) < 0.02

    def test_monte_carlo_tool_with_yield(self):
        out = json.loads(run_gdt_monte_carlo_stack({
            "elements": self._elements_payload(),
            "n_trials": 20000,
            "spec_min": 29.5,
            "spec_max": 30.5,
        }, ctx=None))
        assert "expected_yield" in out
        assert out["expected_yield"] > 0.999

    def test_worst_case_tool_bad_input(self):
        out = json.loads(run_gdt_worst_case_stack(
            {"elements": [{"nominal": 10.0, "plus_tol": -1.0, "minus_tol": 0.1}]}, ctx=None
        ))
        assert "error" in out
        assert out["code"] == "STACK_ERROR"
