"""
Verify that all kerf-apparel LLM tools are importable and have correct specs.

Response format (compat layer)
-------------------------------
ok_payload(v) -> json.dumps(v)         # no 'ok' key; success = no 'error' key
err_payload(msg, code) -> json.dumps({"error": msg, "code": code})

Registered tools checked
------------------------
apparel_grade_bodice    apparel_add_seam       apparel_make_marker
apparel_generate_block  apparel_flatten_pattern
apparel_apply_grading   apparel_grade_check
garment_avatar_body_form
"""

from __future__ import annotations

import json
import asyncio
import pytest

from kerf_apparel.tools import (
    grade_bodice_spec, run_grade_bodice,
    add_seam_spec, run_add_seam,
    make_marker_spec, run_make_marker,
    generate_block_spec, run_generate_block,
    flatten_pattern_spec, run_flatten_pattern,
    apply_grading_spec, run_apply_grading,
    grade_check_spec, run_grade_check,
    avatar_body_form_spec, run_avatar_body_form,
)


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _is_success(d: dict) -> bool:
    """ok_payload — success = no 'error' key."""
    return "error" not in d


def _is_error(d: dict) -> bool:
    return "error" in d


SPECS = [
    grade_bodice_spec,
    add_seam_spec,
    make_marker_spec,
    generate_block_spec,
    flatten_pattern_spec,
    apply_grading_spec,
    grade_check_spec,
    avatar_body_form_spec,
]

EXPECTED_NAMES = {
    "apparel_grade_bodice",
    "apparel_add_seam",
    "apparel_make_marker",
    "apparel_generate_block",
    "apparel_flatten_pattern",
    "apparel_apply_grading",
    "apparel_grade_check",
    "garment_avatar_body_form",
}


class TestSpecStructure:
    def test_all_specs_have_names(self):
        names = {s.name for s in SPECS}
        assert names == EXPECTED_NAMES

    def test_all_specs_have_descriptions(self):
        for s in SPECS:
            assert len(s.description) > 20, f"{s.name} description too short"

    def test_all_specs_have_input_schemas(self):
        for s in SPECS:
            assert s.input_schema is not None
            assert "type" in s.input_schema

    def test_no_duplicate_names(self):
        names = [s.name for s in SPECS]
        assert len(names) == len(set(names))


class TestApplyGradingSpec:
    def test_spec_name(self):
        assert apply_grading_spec.name == "apparel_apply_grading"

    def test_spec_enumerates_specs(self):
        props = apply_grading_spec.input_schema["properties"]
        assert "spec" in props
        enum_vals = props["spec"]["enum"]
        assert "women_us" in enum_vals
        assert "men_us" in enum_vals
        assert "women_eu" in enum_vals
        assert "men_eu" in enum_vals


class TestGradeCheckSpec:
    def test_spec_name(self):
        assert grade_check_spec.name == "apparel_grade_check"

    def test_measurements_required(self):
        assert "measurements" in grade_check_spec.input_schema["required"]


class TestAvatarBodyFormSpec:
    def test_spec_name(self):
        assert avatar_body_form_spec.name == "garment_avatar_body_form"

    def test_spec_describes_caesar(self):
        assert "CAESAR" in avatar_body_form_spec.description

    def test_sex_enum(self):
        props = avatar_body_form_spec.input_schema["properties"]
        assert "sex" in props
        enum_vals = props["sex"]["enum"]
        assert "female" in enum_vals
        assert "male" in enum_vals
        assert "unisex" in enum_vals


class TestApplyGradingDispatch:
    def setup_method(self):
        from kerf_apparel._compat import ProjectCtx
        self._ctx = ProjectCtx()

    def _dispatch(self, params: dict) -> dict:
        raw = _run(run_apply_grading(self._ctx, json.dumps(params).encode()))
        return json.loads(raw)

    def test_grade_up_one_size(self):
        result = self._dispatch({
            "block": "bodice_front",
            "from_size": "M",
            "to_size": "L",
            "spec": "women_us",
        })
        assert _is_success(result), f"unexpected error: {result}"
        assert "to_bbox_cm" in result
        # Grading up should generally increase width
        from_w = result["from_bbox_cm"]["width"]
        to_w   = result["to_bbox_cm"]["width"]
        assert to_w >= from_w

    def test_grade_down_one_size(self):
        result = self._dispatch({
            "block": "bodice_front",
            "from_size": "L",
            "to_size": "M",
        })
        assert _is_success(result), f"unexpected error: {result}"
        assert "from_bbox_cm" in result
        assert "to_bbox_cm" in result

    def test_missing_block_returns_error(self):
        result = self._dispatch({"from_size": "M", "to_size": "L"})
        assert _is_error(result)

    def test_missing_from_size_returns_error(self):
        result = self._dispatch({"block": "bodice_front", "to_size": "L"})
        assert _is_error(result)

    def test_unknown_spec_returns_error(self):
        result = self._dispatch({
            "block": "bodice_front",
            "from_size": "M",
            "to_size": "L",
            "spec": "martian_xl",
        })
        assert _is_error(result)

    def test_returns_grade_deltas(self):
        result = self._dispatch({
            "block": "bodice_front",
            "from_size": "S",
            "to_size": "L",
        })
        assert _is_success(result)
        assert "grade_dx_mm" in result
        assert "grade_dy_mm" in result

    def test_returns_area_values(self):
        """apply_grading returns bounding box/area; areas may differ or not depending on grade method."""
        result = self._dispatch({
            "block": "bodice_front",
            "from_size": "S",
            "to_size": "L",
        })
        assert _is_success(result)
        assert result["from_area_cm2"] > 0
        assert result["to_area_cm2"] > 0


class TestGradeCheckDispatch:
    def setup_method(self):
        from kerf_apparel._compat import ProjectCtx
        self._ctx = ProjectCtx()

    def _dispatch(self, params: dict) -> dict:
        raw = _run(run_grade_check(self._ctx, json.dumps(params).encode()))
        return json.loads(raw)

    def test_iso_codes_compliant(self):
        """Known ISO 8559-2 codes should produce zero warnings."""
        result = self._dispatch({
            "measurements": {
                "chest_girth": 92,
                "waist_girth": 74,
                "hip_girth": 96,
            }
        })
        assert _is_success(result), f"unexpected error: {result}"
        assert isinstance(result["warnings"], list)
        assert result["iso_compliant"] is True

    def test_non_standard_code_produces_warning(self):
        result = self._dispatch({
            "measurements": {
                "unobtainium_circumference": 42,
            }
        })
        assert _is_success(result), f"unexpected error: {result}"
        assert result["non_standard_count"] >= 1
        assert len(result["warnings"]) >= 1

    def test_empty_measurements_ok(self):
        result = self._dispatch({"measurements": {}})
        assert _is_success(result), f"unexpected error: {result}"
        assert result["total_codes"] == 0

    def test_missing_measurements_field(self):
        result = self._dispatch({})
        assert _is_error(result)

    def test_iso_compliant_flag_false_for_non_standard(self):
        result = self._dispatch({
            "measurements": {"unknown_code_xyz": 50}
        })
        assert _is_success(result)
        assert result["iso_compliant"] is False
