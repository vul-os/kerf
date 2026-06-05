"""
Tests for kerf_gdnt.tools — gdt_validate_frame and gdt_parse_frame tools.

Coverage
--------
gdt_validate_frame:
  - happy path: valid position frame → valid=True, violations=[]
  - parse error: bad string → valid=False, violations non-empty
  - orientation without datum → violation
  - form tolerance with datum → violation
  - MMC on form tolerance → violation
  - projected zone on non-position → violation
  - canonical_string round-trips correctly

gdt_parse_frame:
  - valid position frame → correct fields
  - diameter zone parsed
  - tolerance modifier parsed
  - datum refs parsed with modifier
  - multiple datums
  - parse error → err_payload BAD_ARGS/PARSE_ERROR
  - missing fcf_string → err_payload BAD_ARGS

plugin:
  - gdt_validate_frame_spec and gdt_parse_frame_spec importable from tools
  - plugin.py imports both without error
"""
from __future__ import annotations

import json
import pytest

from kerf_gdnt.tools import (
    gdt_validate_frame_spec,
    run_gdt_validate_frame,
    gdt_parse_frame_spec,
    run_gdt_parse_frame,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _validate(fcf_string: str) -> dict:
    return json.loads(run_gdt_validate_frame({"fcf_string": fcf_string}, None))


def _parse(fcf_string: str) -> dict:
    return json.loads(run_gdt_parse_frame({"fcf_string": fcf_string}, None))


# ---------------------------------------------------------------------------
# gdt_validate_frame — spec structure
# ---------------------------------------------------------------------------

class TestGdtValidateFrameSpec:
    def test_spec_name(self):
        assert gdt_validate_frame_spec.name == "gdt_validate_frame"

    def test_spec_has_fcf_string_property(self):
        props = gdt_validate_frame_spec.input_schema.get("properties", {})
        assert "fcf_string" in props

    def test_spec_required_includes_fcf_string(self):
        required = gdt_validate_frame_spec.input_schema.get("required", [])
        assert "fcf_string" in required


# ---------------------------------------------------------------------------
# gdt_validate_frame — valid frames
# ---------------------------------------------------------------------------

class TestGdtValidateFrameValid:
    def test_position_frame_valid(self):
        r = _validate("[position][dia:0.05][M][A][B][C]")
        assert r["valid"] is True
        assert r["violations"] == []

    def test_flatness_no_datums_valid(self):
        r = _validate("[flatness][0.05]")
        assert r["valid"] is True

    def test_perpendicularity_with_datum_valid(self):
        r = _validate("[perpendicularity][0.1][A]")
        assert r["valid"] is True

    def test_circularity_valid(self):
        r = _validate("[circularity][0.01]")
        assert r["valid"] is True

    def test_canonical_string_round_trips(self):
        r = _validate("[position][dia:0.05][M][A][B][C]")
        assert r["canonical_string"] == "[position][dia:0.05][M][A][B][C]"

    def test_perpendicularity_canonical_string(self):
        r = _validate("[perpendicularity][0.1][A]")
        assert r["canonical_string"] == "[perpendicularity][0.1][A]"

    def test_warnings_field_present(self):
        r = _validate("[flatness][0.05]")
        assert "warnings" in r


# ---------------------------------------------------------------------------
# gdt_validate_frame — invalid frames
# ---------------------------------------------------------------------------

class TestGdtValidateFrameInvalid:
    def test_bad_string_parse_error_returns_invalid(self):
        r = _validate("not_a_canonical_frame")
        assert r["valid"] is False
        assert len(r["violations"]) > 0

    def test_orientation_without_datum_is_violation(self):
        # perpendicularity requires at least 1 datum
        r = _validate("[perpendicularity][0.1]")
        assert r["valid"] is False
        assert any("datum" in v.lower() or "ORIENTATION" in v for v in r["violations"])

    def test_form_tolerance_with_datum_is_violation(self):
        # flatness must NOT reference datums
        r = _validate("[flatness][0.05][A]")
        assert r["valid"] is False
        assert any("datum" in v.lower() or "FORM" in v for v in r["violations"])

    def test_mmc_on_flatness_is_violation(self):
        # M modifier not applicable to form tolerances
        r = _validate("[flatness][0.05][M]")
        assert r["valid"] is False
        assert any("modifier" in v.lower() or "MODIFIER" in v for v in r["violations"])

    def test_projected_zone_on_non_position_is_violation(self):
        r = _validate("[flatness][0.05][P]")
        assert r["valid"] is False
        assert any("position" in v.lower() or "PROJECTED" in v for v in r["violations"])

    def test_missing_fcf_string_returns_error(self):
        r = json.loads(run_gdt_validate_frame({}, None))
        assert r.get("code") == "BAD_ARGS"

    def test_empty_fcf_string_returns_error(self):
        r = json.loads(run_gdt_validate_frame({"fcf_string": ""}, None))
        assert r.get("code") == "BAD_ARGS"

    def test_unknown_symbol_is_violation(self):
        r = _validate("[foobar][0.05]")
        assert r["valid"] is False

    def test_non_positive_tolerance_is_violation(self):
        r = _validate("[flatness][-0.01]")
        assert r["valid"] is False


# ---------------------------------------------------------------------------
# gdt_parse_frame — spec structure
# ---------------------------------------------------------------------------

class TestGdtParseFrameSpec:
    def test_spec_name(self):
        assert gdt_parse_frame_spec.name == "gdt_parse_frame"

    def test_spec_has_fcf_string_property(self):
        props = gdt_parse_frame_spec.input_schema.get("properties", {})
        assert "fcf_string" in props

    def test_spec_required_includes_fcf_string(self):
        required = gdt_parse_frame_spec.input_schema.get("required", [])
        assert "fcf_string" in required


# ---------------------------------------------------------------------------
# gdt_parse_frame — valid frames
# ---------------------------------------------------------------------------

class TestGdtParseFrameValid:
    def test_symbol_code_correct(self):
        r = _parse("[position][dia:0.05][M][A][B][C]")
        assert r["symbol_code"] == "position"

    def test_tolerance_value_correct(self):
        r = _parse("[position][dia:0.05][M][A][B][C]")
        assert r["tolerance_value"] == pytest.approx(0.05)

    def test_diameter_zone_true(self):
        r = _parse("[position][dia:0.05][M][A][B][C]")
        assert r["diameter_zone"] is True

    def test_diameter_zone_false_when_absent(self):
        r = _parse("[flatness][0.05]")
        assert r["diameter_zone"] is False

    def test_modifier_parsed(self):
        r = _parse("[position][dia:0.05][M][A]")
        assert r["tolerance_modifier"] == "M"

    def test_modifier_null_when_absent(self):
        r = _parse("[flatness][0.05]")
        assert r["tolerance_modifier"] is None

    def test_datum_refs_count(self):
        r = _parse("[position][dia:0.05][M][A][B][C]")
        assert len(r["datum_refs"]) == 3

    def test_datum_refs_labels(self):
        r = _parse("[position][dia:0.05][M][A][B][C]")
        labels = [dr["label"] for dr in r["datum_refs"]]
        assert labels == ["A", "B", "C"]

    def test_datum_modifier_parsed(self):
        r = _parse("[position][dia:0.05][M][A/M][B]")
        assert r["datum_refs"][0]["modifier"] == "M"
        assert r["datum_refs"][1]["modifier"] is None

    def test_canonical_string_in_result(self):
        r = _parse("[perpendicularity][0.1][A]")
        assert r["canonical_string"] == "[perpendicularity][0.1][A]"

    def test_flatness_no_datums(self):
        r = _parse("[flatness][0.05]")
        assert r["datum_refs"] == []

    def test_circularity_zero_datums(self):
        r = _parse("[circularity][0.02]")
        assert len(r["datum_refs"]) == 0

    def test_tolerance_value_integer(self):
        r = _parse("[flatness][1]")
        assert r["tolerance_value"] == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# gdt_parse_frame — error cases
# ---------------------------------------------------------------------------

class TestGdtParseFrameErrors:
    def test_missing_fcf_string_returns_error(self):
        r = json.loads(run_gdt_parse_frame({}, None))
        assert r.get("code") == "BAD_ARGS"

    def test_empty_fcf_string_returns_error(self):
        r = json.loads(run_gdt_parse_frame({"fcf_string": ""}, None))
        assert r.get("code") == "BAD_ARGS"

    def test_malformed_string_returns_parse_error(self):
        r = json.loads(run_gdt_parse_frame({"fcf_string": "not_canonical"}, None))
        assert r.get("code") == "PARSE_ERROR"

    def test_unknown_symbol_returns_parse_error(self):
        r = json.loads(run_gdt_parse_frame({"fcf_string": "[unknown_sym][0.05]"}, None))
        assert r.get("code") == "PARSE_ERROR"


# ---------------------------------------------------------------------------
# Plugin import sanity
# ---------------------------------------------------------------------------

class TestPluginImport:
    def test_plugin_imports_both_tools(self):
        # Verify the import that plugin.py relies on works
        from kerf_gdnt.tools import (
            gdt_validate_frame_spec, run_gdt_validate_frame,
            gdt_parse_frame_spec, run_gdt_parse_frame,
        )
        assert gdt_validate_frame_spec is not None
        assert run_gdt_validate_frame is not None
        assert gdt_parse_frame_spec is not None
        assert run_gdt_parse_frame is not None
