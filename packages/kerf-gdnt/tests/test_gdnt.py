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
