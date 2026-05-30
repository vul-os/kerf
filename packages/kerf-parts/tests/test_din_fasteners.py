"""Tests for the DIN/ISO metric fastener catalog (kerf_parts.din_fasteners).

Oracle values come from publicly available DIN tables (see module docstring).

DISCLAIMER: Standard dimensions from public DIN tables — NOT DIN-certified.

Coverage
--------
  DIN 931 M10 head_diameter = 17 mm oracle (wrench_size = 17 mm per DIN table)
  DIN 912 M5  head_diameter = 8.5 mm, head_height = 5.0 mm
  Torque for M10 8.8 ≈ 50 N·m (within 10 % of VDI 2230 reference)
  Case-insensitive lookup: 'din 931'/'m10' == 'DIN 931'/'M10'
  Catalog completeness (M3-M20 in each standard)
  FastenerSpec.nominal_stress_area() sanity
  Washer has no length_mm
  Hex nut has no length_mm
  LLM tool registry has 2 entries with correct names
  LLM tools return ok=True on valid input
  LLM tools return ok=False on bad input
  lookup_fastener raises KeyError for unknown standard
  lookup_fastener raises KeyError for unknown size
"""
from __future__ import annotations

import math
import pytest

from kerf_parts.din_fasteners import (
    DIN_FASTENERS_CATALOG,
    FastenerSpec,
    PARTS_FASTENER_TOOLS,
    lookup_fastener,
    recommend_torque,
    _parts_lookup_fastener,
    _parts_torque_recommendation,
)


# ---------------------------------------------------------------------------
# Oracle tests — verified against published DIN tables
# ---------------------------------------------------------------------------

class TestDIN931Oracle:
    """DIN 931 hex bolt dimensional oracles."""

    def test_m10_wrench_size(self):
        """DIN 931 M10: wrench_size = 17 mm (width across flats 's')."""
        spec = lookup_fastener("DIN 931", "M10")
        assert spec.dimensions["wrench_size"] == 17.0, (
            f"Expected 17.0, got {spec.dimensions['wrench_size']}"
        )

    def test_m10_head_diameter_max(self):
        """DIN 931 M10: head_diameter_max ~17.77 mm (circumscribed circle 'e')."""
        spec = lookup_fastener("DIN 931", "M10")
        hd = spec.dimensions["head_diameter_max"]
        # Published DIN 931: e ≈ 17.77 mm for M10
        assert abs(hd - 17.77) < 0.05, f"head_diameter_max {hd} not close to 17.77"

    def test_m10_thread_pitch_coarse(self):
        """DIN 931 M10: thread_pitch_coarse = 1.5 mm (DIN 13-1 coarse series)."""
        spec = lookup_fastener("DIN 931", "M10")
        assert spec.dimensions["thread_pitch_coarse"] == 1.5, (
            f"Expected 1.5, got {spec.dimensions['thread_pitch_coarse']}"
        )

    def test_m10_kind(self):
        spec = lookup_fastener("DIN 931", "M10")
        assert spec.kind == "hex_bolt"

    def test_m10_standard_label(self):
        spec = lookup_fastener("DIN 931", "M10")
        assert spec.standard == "DIN 931"


class TestDIN912Oracle:
    """DIN 912 / ISO 4762 hexagon socket head cap screw dimensional oracles."""

    def test_m5_head_diameter(self):
        """DIN 912 M5: head_diameter_max = 8.5 mm (dk in DIN 912 table)."""
        spec = lookup_fastener("DIN 912", "M5")
        hd = spec.dimensions["head_diameter_max"]
        assert hd == 8.5, f"Expected 8.5, got {hd}"

    def test_m5_head_height(self):
        """DIN 912 M5: head_height_max = 5.0 mm (k in DIN 912 table)."""
        spec = lookup_fastener("DIN 912", "M5")
        hh = spec.dimensions["head_height_max"]
        assert hh == 5.0, f"Expected 5.0, got {hh}"

    def test_m5_kind(self):
        spec = lookup_fastener("DIN 912", "M5")
        assert spec.kind == "cap_screw"

    def test_m6_head_diameter(self):
        """DIN 912 M6: head_diameter_max = 10.0 mm."""
        spec = lookup_fastener("DIN 912", "M6")
        assert spec.dimensions["head_diameter_max"] == 10.0

    def test_m10_wrench_size(self):
        """DIN 912 M10: wrench_size = 8.0 mm (Allen key)."""
        spec = lookup_fastener("DIN 912", "M10")
        assert spec.dimensions["wrench_size"] == 8.0


# ---------------------------------------------------------------------------
# Torque oracle — VDI 2230 reference value for M10 8.8
# ---------------------------------------------------------------------------

class TestVDI2230TorqueOracle:
    """Assembly torque validation against published VDI 2230 reference tables."""

    def test_m10_grade88_torque_within_10pct(self):
        """M10 grade 8.8 torque should be ≈50 N·m (VDI 2230 reference: ~47-52 N·m)."""
        spec = lookup_fastener("DIN 931", "M10", material="steel_grade_8.8")
        torque = recommend_torque(spec, friction_coefficient=0.14)
        # Published VDI 2230 Part 1 (2015) Table A4 reference: ~49-51 N·m for M10 8.8
        # Accept ±10% of 50 N·m reference
        reference = 50.0
        tolerance = 0.10
        assert abs(torque - reference) / reference <= tolerance, (
            f"M10 8.8 torque {torque:.2f} N·m is >10% from {reference} N·m reference"
        )

    def test_m6_grade88_torque_positive(self):
        spec = lookup_fastener("DIN 931", "M6", material="steel_grade_8.8")
        torque = recommend_torque(spec, friction_coefficient=0.14)
        assert torque > 0

    def test_m12_grade88_torque_greater_than_m10(self):
        spec_m10 = lookup_fastener("DIN 931", "M10", material="steel_grade_8.8")
        spec_m12 = lookup_fastener("DIN 931", "M12", material="steel_grade_8.8")
        t10 = recommend_torque(spec_m10)
        t12 = recommend_torque(spec_m12)
        assert t12 > t10, f"M12 torque ({t12}) should exceed M10 ({t10})"

    def test_higher_friction_gives_higher_torque(self):
        spec = lookup_fastener("DIN 931", "M10", material="steel_grade_8.8")
        t_oiled = recommend_torque(spec, friction_coefficient=0.10)
        t_dry   = recommend_torque(spec, friction_coefficient=0.20)
        assert t_dry > t_oiled

    def test_stainless_a2_70_torque(self):
        """Stainless A2-70 M10 torque should be smaller than 8.8 (lower yield)."""
        spec_ss = lookup_fastener("DIN 931", "M10", material="stainless_a2-70")
        spec_88 = lookup_fastener("DIN 931", "M10", material="steel_grade_8.8")
        t_ss = recommend_torque(spec_ss)
        t_88 = recommend_torque(spec_88)
        # A2-70 proof ~450 MPa vs 8.8 proof ~640 MPa → lower torque expected
        assert t_ss < t_88, f"A2-70 torque {t_ss:.2f} should be < 8.8 torque {t_88:.2f}"


# ---------------------------------------------------------------------------
# Case-insensitive lookup oracle
# ---------------------------------------------------------------------------

class TestCaseInsensitiveLookup:
    """lookup_fastener must be case-insensitive for both standard and size."""

    def test_lowercase_standard_and_size(self):
        spec_lower = lookup_fastener("din 931", "m10")
        spec_upper = lookup_fastener("DIN 931", "M10")
        assert spec_lower.standard == spec_upper.standard
        assert spec_lower.size == spec_upper.size
        assert spec_lower.thread_pitch == spec_upper.thread_pitch

    def test_mixed_case_standard(self):
        spec = lookup_fastener("Din 912", "M5")
        assert spec.dimensions["head_diameter_max"] == 8.5

    def test_lowercase_size_only(self):
        spec = lookup_fastener("DIN 931", "m10")
        assert spec.size == "M10"

    def test_din912_iso4762_same_dims(self):
        """DIN 912 and ISO 4762 share identical geometry (ISO 4762 = DIN 912)."""
        spec_din = lookup_fastener("DIN 912", "M6")
        spec_iso = lookup_fastener("ISO 4762", "M6")
        assert spec_din.dimensions["head_diameter_max"] == spec_iso.dimensions["head_diameter_max"]
        assert spec_din.dimensions["head_height_max"] == spec_iso.dimensions["head_height_max"]


# ---------------------------------------------------------------------------
# Catalog completeness
# ---------------------------------------------------------------------------

class TestCatalogCompleteness:
    """The catalog covers the mandatory sizes M3-M20 per the task spec."""

    REQUIRED_SIZES = ["M3", "M4", "M5", "M6", "M8", "M10", "M12", "M16", "M20"]
    REQUIRED_STANDARDS = ["DIN 931", "DIN 912", "DIN 7991", "DIN 125", "DIN 934", "ISO 7380"]

    @pytest.mark.parametrize("std", REQUIRED_STANDARDS)
    def test_standard_in_catalog(self, std):
        assert std in DIN_FASTENERS_CATALOG, f"Standard {std} missing from catalog"

    @pytest.mark.parametrize("std", ["DIN 931", "DIN 912", "DIN 934"])
    @pytest.mark.parametrize("size", REQUIRED_SIZES)
    def test_size_covered(self, std, size):
        catalog_std = DIN_FASTENERS_CATALOG.get(std, {})
        assert size in catalog_std, f"{std} {size} not in catalog"

    def test_din931_m10_length_variants(self):
        """DIN 931 M10 should have entries for multiple standard lengths."""
        specs = DIN_FASTENERS_CATALOG["DIN 931"]["M10"]
        lengths = [s.length_mm for s in specs if s.length_mm is not None]
        assert len(lengths) >= 5, f"Expected >=5 length variants, got {len(lengths)}: {lengths}"

    def test_din125_washers_no_length(self):
        """Washers should have length_mm = None."""
        spec = lookup_fastener("DIN 125", "M10")
        assert spec.length_mm is None

    def test_din934_nut_no_length(self):
        """Hex nuts should have length_mm = None."""
        spec = lookup_fastener("DIN 934", "M10")
        assert spec.length_mm is None

    def test_din934_nut_kind(self):
        spec = lookup_fastener("DIN 934", "M10")
        assert spec.kind == "hex_nut"

    def test_din125_washer_kind(self):
        spec = lookup_fastener("DIN 125", "M10")
        assert spec.kind == "flat_washer"


# ---------------------------------------------------------------------------
# FastenerSpec mechanics
# ---------------------------------------------------------------------------

class TestFastenerSpec:
    def test_diameter_mm_parsed(self):
        spec = lookup_fastener("DIN 931", "M10")
        assert spec.diameter_mm == 10.0

    def test_nominal_stress_area_m10(self):
        """M10 coarse: stress area should be ≈58 mm² per ISO 898-1."""
        spec = lookup_fastener("DIN 931", "M10", material="steel_grade_8.8")
        A_s = spec.nominal_stress_area()
        # Published ISO 898-1 A_s(M10 p1.5) = 58.0 mm²
        assert abs(A_s - 58.0) < 2.0, f"A_s = {A_s:.2f}, expected ≈58 mm²"

    def test_nominal_stress_area_m6(self):
        """M6 coarse: A_s ≈ 20.1 mm²."""
        spec = lookup_fastener("DIN 931", "M6")
        A_s = spec.nominal_stress_area()
        assert abs(A_s - 20.1) < 1.5, f"A_s(M6) = {A_s:.2f}"

    def test_stress_area_increases_with_diameter(self):
        spec_m6 = lookup_fastener("DIN 931", "M6")
        spec_m10 = lookup_fastener("DIN 931", "M10")
        spec_m16 = lookup_fastener("DIN 931", "M16")
        assert spec_m6.nominal_stress_area() < spec_m10.nominal_stress_area()
        assert spec_m10.nominal_stress_area() < spec_m16.nominal_stress_area()


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------

class TestLookupErrors:
    def test_unknown_standard_raises_key_error(self):
        with pytest.raises(KeyError, match="DIN 999"):
            lookup_fastener("DIN 999", "M10")

    def test_unknown_size_raises_key_error(self):
        with pytest.raises(KeyError, match="M99"):
            lookup_fastener("DIN 931", "M99")

    def test_exact_length_not_found_raises_value_error(self):
        with pytest.raises(ValueError, match="7.777"):
            lookup_fastener("DIN 931", "M10", length_mm=7.777)

    def test_unknown_material_in_torque_raises(self):
        spec = lookup_fastener("DIN 931", "M10")
        spec_bad_mat = FastenerSpec(
            standard="DIN 931", kind="hex_bolt", size="M10",
            length_mm=30.0, thread_pitch=1.5, material="unobtanium",
            dimensions={"head_diameter_max": 17.77, "wrench_size": 17.0, "head_height_max": 6.4},
        )
        with pytest.raises(ValueError, match="unobtanium"):
            recommend_torque(spec_bad_mat)


# ---------------------------------------------------------------------------
# LLM tool registry
# ---------------------------------------------------------------------------

class TestLLMToolRegistry:
    def test_registry_has_exactly_two_tools(self):
        assert len(PARTS_FASTENER_TOOLS) == 2

    def test_registry_tool_names(self):
        names = {t["name"] for t in PARTS_FASTENER_TOOLS}
        assert "parts_lookup_fastener" in names
        assert "parts_torque_recommendation" in names

    def test_registry_entries_have_fn_and_description(self):
        for tool in PARTS_FASTENER_TOOLS:
            assert callable(tool["fn"]), f"{tool['name']} fn not callable"
            assert isinstance(tool["description"], str) and tool["description"], \
                f"{tool['name']} has empty description"

    def test_parts_lookup_fastener_ok(self):
        result = _parts_lookup_fastener("DIN 931", "M10")
        assert result["ok"] is True
        assert result["standard"] == "DIN 931"
        assert result["size"] == "M10"
        assert "dimensions" in result
        assert "disclaimer" in result
        assert "NOT DIN-certified" in result["disclaimer"]

    def test_parts_lookup_fastener_bad_standard(self):
        result = _parts_lookup_fastener("DIN 999", "M10")
        assert result["ok"] is False
        assert "error" in result

    def test_parts_lookup_fastener_bad_size(self):
        result = _parts_lookup_fastener("DIN 931", "M99")
        assert result["ok"] is False

    def test_parts_torque_recommendation_ok(self):
        result = _parts_torque_recommendation("DIN 931", "M10",
                                               material="steel_grade_8.8")
        assert result["ok"] is True
        assert "torque_Nm" in result
        assert "preload_N" in result
        assert result["torque_Nm"] > 0
        assert "VDI 2230" in result["method"]

    def test_parts_torque_recommendation_bad_standard(self):
        result = _parts_torque_recommendation("DIN 999", "M10")
        assert result["ok"] is False

    def test_parts_torque_recommendation_includes_disclaimer(self):
        result = _parts_torque_recommendation("DIN 912", "M6")
        assert result["ok"] is True
        assert "NOT DIN-certified" in result["disclaimer"]

    def test_lookup_tool_stress_area_present(self):
        result = _parts_lookup_fastener("DIN 912", "M5")
        assert result["ok"] is True
        assert result["stress_area_mm2"] > 0


# ---------------------------------------------------------------------------
# DIN 7991 countersunk cap screw
# ---------------------------------------------------------------------------

class TestDIN7991:
    def test_m6_countersink_angle(self):
        spec = lookup_fastener("DIN 7991", "M6")
        assert spec.dimensions.get("countersink_angle_deg") == 90

    def test_m6_kind(self):
        spec = lookup_fastener("DIN 7991", "M6")
        assert spec.kind == "countersunk_cap_screw"

    def test_m5_head_diameter(self):
        spec = lookup_fastener("DIN 7991", "M5")
        hd = spec.dimensions["head_diameter_max"]
        # DIN 7991 M5: dk ≈ 11.20 mm
        assert abs(hd - 11.20) < 0.1, f"Expected ≈11.20, got {hd}"


# ---------------------------------------------------------------------------
# ISO 7380 button head
# ---------------------------------------------------------------------------

class TestISO7380:
    def test_m6_kind(self):
        spec = lookup_fastener("ISO 7380", "M6")
        assert spec.kind == "button_head_cap_screw"

    def test_m8_head_diameter(self):
        spec = lookup_fastener("ISO 7380", "M8")
        hd = spec.dimensions["head_diameter_max"]
        assert abs(hd - 14.0) < 0.5, f"Expected ≈14.0, got {hd}"


# ---------------------------------------------------------------------------
# DIN 934 hex nut dimensional oracle
# ---------------------------------------------------------------------------

class TestDIN934Oracle:
    def test_m10_width_across_flats(self):
        """DIN 934 M10: s = 17 mm (width across flats)."""
        spec = lookup_fastener("DIN 934", "M10")
        assert spec.dimensions["width_across_flats"] == 17.0

    def test_m10_nut_height(self):
        """DIN 934 M10: m = 8.0 mm (nut height)."""
        spec = lookup_fastener("DIN 934", "M10")
        assert spec.dimensions["nut_height"] == 8.0
