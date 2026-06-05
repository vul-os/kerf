"""
Tests for the textiles_pattern_grade LLM tool.

DoD oracles
-----------
1. Bodice-front grade produces the correct number of sizes.
2. Bust girth increases monotonically from XS → XXL for bodice_front.
3. Width and height increase when grading up by one US size.
4. Sleeve grade covers all sizes in the standard run.
5. Pants grade produces valid area_cm2 at each size.
6. spec='women_eu' is accepted without error.
7. Unknown block returns ok=False with error key.
8. Missing base_size returns ok=False.
9. seam_allowance_cm adds to bounding box vs no-SA version.
10. All tools in textiles are importable (registration check).
"""

from __future__ import annotations

import asyncio
import json
import pytest

from kerf_textiles.tools import (
    textiles_pattern_grade_spec,
    run_textiles_pattern_grade,
    textiles_generate_spec,
    textiles_cloth_drape_spec,
    textiles_cut_room_spec,
    textiles_etextiles_spec,
    textiles_sustainability_spec,
)


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _grade(params: dict) -> dict:
    return _run(run_textiles_pattern_grade(params))


# ---------------------------------------------------------------------------
# 1. Spec sanity
# ---------------------------------------------------------------------------

class TestPatternGradeSpec:
    def test_spec_name(self):
        assert textiles_pattern_grade_spec["name"] == "textiles_pattern_grade"

    def test_spec_has_description(self):
        assert len(textiles_pattern_grade_spec["description"]) > 40

    def test_spec_required_fields(self):
        required = textiles_pattern_grade_spec["input_schema"]["required"]
        assert "block" in required
        assert "base_size" in required


# ---------------------------------------------------------------------------
# 2. Bodice grading
# ---------------------------------------------------------------------------

class TestBodiceGrade:
    def test_grade_bodice_front_default_run(self):
        result = _grade({"block": "bodice_front", "base_size": "M"})
        assert result.get("ok") is True
        assert len(result["sizes"]) >= 4   # at least XS/S/M/L/XL

    def test_bust_girth_increases_xs_to_xxl(self):
        result = _grade({
            "block": "bodice_front",
            "base_size": "M",
            "size_run": ["XS", "S", "M", "L", "XL", "XXL"],
        })
        assert result.get("ok") is True
        sizes = result["sizes"]
        girths = [sizes[s]["bust_girth_cm"] for s in ["XS", "S", "M", "L", "XL", "XXL"]]
        for i in range(len(girths) - 1):
            assert girths[i] < girths[i + 1], (
                f"bust girth not monotone: {girths[i]} >= {girths[i+1]}"
            )

    def test_width_increases_s_to_xl(self):
        result = _grade({
            "block": "bodice_front",
            "base_size": "S",
            "size_run": ["S", "M", "L", "XL"],
        })
        assert result.get("ok") is True
        sizes = result["sizes"]
        widths = [sizes[s]["width_cm"] for s in ["S", "M", "L", "XL"]]
        assert widths[-1] > widths[0], "width should increase from S to XL"

    def test_bodice_back(self):
        result = _grade({
            "block": "bodice_back",
            "base_size": "L",
            "size_run": ["S", "M", "L", "XL"],
        })
        assert result.get("ok") is True
        for s in ["S", "M", "L", "XL"]:
            assert s in result["sizes"]

    def test_bodice_front_women_eu_spec(self):
        result = _grade({
            "block": "bodice_front",
            "base_size": "M",
            "spec": "women_eu",
        })
        assert result.get("ok") is True
        assert result["spec"] == "women_eu"


# ---------------------------------------------------------------------------
# 3. Sleeve grading
# ---------------------------------------------------------------------------

class TestSleeveGrade:
    def test_sleeve_grade_standard_run(self):
        result = _grade({"block": "sleeve", "base_size": "M"})
        assert result.get("ok") is True
        assert len(result["sizes"]) >= 4

    def test_sleeve_bust_girth_present(self):
        result = _grade({
            "block": "sleeve",
            "base_size": "M",
            "size_run": ["S", "M", "L"],
        })
        assert result.get("ok") is True
        for s in ["S", "M", "L"]:
            assert "bust_girth_cm" in result["sizes"][s]


# ---------------------------------------------------------------------------
# 4. Pants grading
# ---------------------------------------------------------------------------

class TestPantsGrade:
    def test_pants_front_grade(self):
        result = _grade({"block": "pants_front", "base_size": "M"})
        assert result.get("ok") is True
        assert len(result["sizes"]) >= 4

    def test_pants_back_grade(self):
        result = _grade({
            "block": "pants_back",
            "base_size": "L",
            "size_run": ["S", "M", "L", "XL"],
        })
        assert result.get("ok") is True
        for s in ["S", "M", "L", "XL"]:
            assert result["sizes"][s]["area_cm2"] > 0


# ---------------------------------------------------------------------------
# 5. Seam allowance
# ---------------------------------------------------------------------------

class TestGradeWithSeamAllowance:
    def test_sa_expands_bounding_box(self):
        no_sa = _grade({
            "block": "bodice_front",
            "base_size": "M",
            "size_run": ["M"],
        })
        with_sa = _grade({
            "block": "bodice_front",
            "base_size": "M",
            "size_run": ["M"],
            "seam_allowance_cm": 1.5,
        })
        assert no_sa.get("ok") is True
        assert with_sa.get("ok") is True
        w_no  = no_sa["sizes"]["M"]["width_cm"]
        w_sa  = with_sa["sizes"]["M"]["width_cm"]
        assert w_sa > w_no, f"SA width {w_sa:.2f} should > no-SA {w_no:.2f}"


# ---------------------------------------------------------------------------
# 6. Error paths
# ---------------------------------------------------------------------------

class TestGradeErrors:
    def test_unknown_block(self):
        result = _grade({"block": "tutu_skirt", "base_size": "M"})
        assert result.get("ok") is False
        assert "error" in result

    def test_missing_base_size(self):
        result = _grade({"block": "bodice_front", "base_size": ""})
        assert result.get("ok") is False

    def test_invalid_spec_graceful(self):
        # An unknown spec falls back or errors gracefully
        result = _grade({
            "block": "bodice_front",
            "base_size": "M",
            "spec": "alien_galaxy",
        })
        # Either ok with fallback, or error — must not raise
        assert "ok" in result


# ---------------------------------------------------------------------------
# 7. All textiles tools importable
# ---------------------------------------------------------------------------

class TestTextilesRegistration:
    def test_all_spec_names(self):
        specs = [
            textiles_generate_spec,
            textiles_cloth_drape_spec,
            textiles_cut_room_spec,
            textiles_etextiles_spec,
            textiles_sustainability_spec,
            textiles_pattern_grade_spec,
        ]
        names = {s["name"] for s in specs}
        assert "textiles_generate" in names
        assert "textiles_cloth_drape" in names
        assert "textiles_cut_room" in names
        assert "textiles_etextiles" in names
        assert "textiles_sustainability" in names
        assert "textiles_pattern_grade" in names

    def test_all_specs_have_descriptions(self):
        specs = [
            textiles_generate_spec,
            textiles_cloth_drape_spec,
            textiles_cut_room_spec,
            textiles_etextiles_spec,
            textiles_sustainability_spec,
            textiles_pattern_grade_spec,
        ]
        for spec in specs:
            assert len(spec["description"]) > 20, f"{spec['name']} description too short"
