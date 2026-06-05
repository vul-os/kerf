"""
Tests for 3D rebar placement, BS 8666 bend shapes, bending schedule,
and shop drawing generation.

Oracle values
-------------
Stirrup spacing:
  Beam 5000mm long, cover=25mm, spacing=200mm:
  usable = 5000 - 2×25 = 4950mm
  n_stirrups = int(4950/200) + 1 = 24 + 1 = 25

Bar offset from face:
  Longitudinal bar centroid from bottom face:
  cover + stirrup_d + bar_d/2 = 25 + 10 + 8 = 43 mm  (16mm bar, 10mm stirrup)

BS 8666 Shape 00 cut length:
  Straight bar, A = 5000 mm → cut = 5000 mm

BS 8666 Shape 25 cut length (closed rectangular stirrup):
  d = 10 mm, r = 2×10 = 20 mm (d ≤ 16 mm)
  A = inner_width, B = inner_height
  beam 300×600, cover=25, stirrup d=10:
    inner_w = 300 - 2×25 - 10 = 240 mm
    inner_h = 600 - 2×25 - 10 = 540 mm
  perimeter = 2×(240 + 540) = 1560 mm
  4 bend allowance = 4 × (π/2) × (20 + 5) = 4 × 1.5708 × 25 = 157.08 mm
  hook = (3π/8)(25) + max(10×10, 75) = 29.45 + 100 = 129.45 mm
  cut = 1560 + 157.08 + 129.45 ≈ 1846.5 mm

Bending schedule mass:
  16mm bar: 1.579 kg/m, cut = 5000mm, count = 3
  total mass = 1.579 × 5.0 × 3 = 23.685 kg
"""

from __future__ import annotations

import math
import pytest

from kerf_structural.rebar_3d import (
    bs_bar_properties,
    bar_cut_length,
    shape_code_description,
    place_longitudinal_bars,
    place_stirrups,
    detail_member,
    generate_bending_schedule,
    ConcreteSection,
    _min_bend_radius,
)
from kerf_structural.shop_drawing import (
    generate_shop_drawing,
    generate_ga_drawing,
    TitleBlock,
)


# ---------------------------------------------------------------------------
# Bar properties
# ---------------------------------------------------------------------------

class TestBarProperties:
    def test_known_diameters(self):
        for d in [6, 8, 10, 12, 16, 20, 25, 32]:
            props = bs_bar_properties(d)
            assert props.diameter_mm == d
            assert props.area_mm2 > 0
            assert props.mass_kg_per_m > 0

    def test_area_scales_with_diameter(self):
        p12 = bs_bar_properties(12)
        p16 = bs_bar_properties(16)
        assert p16.area_mm2 > p12.area_mm2

    def test_invalid_diameter_raises(self):
        with pytest.raises(ValueError, match="not in BS table"):
            bs_bar_properties(15)  # not a standard size

    def test_16mm_mass_known(self):
        p = bs_bar_properties(16)
        # BS table: T16 = 1.579 kg/m
        assert p.mass_kg_per_m == pytest.approx(1.579, rel=1e-3)


# ---------------------------------------------------------------------------
# BS 8666 bend radii
# ---------------------------------------------------------------------------

class TestBendRadius:
    def test_small_bar_radius_is_2d(self):
        # d <= 16 mm → r = 2d
        assert _min_bend_radius(10.0) == pytest.approx(20.0)
        assert _min_bend_radius(16.0) == pytest.approx(32.0)

    def test_medium_bar_radius_is_3pt5d(self):
        # 20 and 25 mm → r = 3.5d
        assert _min_bend_radius(20.0) == pytest.approx(70.0)
        assert _min_bend_radius(25.0) == pytest.approx(87.5)

    def test_large_bar_radius_is_4d(self):
        # d >= 32 mm → r = 4d
        assert _min_bend_radius(32.0) == pytest.approx(128.0)


# ---------------------------------------------------------------------------
# BS 8666 shape code cut lengths
# ---------------------------------------------------------------------------

class TestBarCutLength:
    def test_shape_00_straight(self):
        # Straight bar: cut = A
        length = bar_cut_length("00", {"A": 5000.0}, 16)
        assert length == pytest.approx(5000.0, rel=1e-3)

    def test_shape_00_various_lengths(self):
        for A in [1000, 2500, 6000]:
            assert bar_cut_length("00", {"A": float(A)}, 12) == pytest.approx(A, rel=1e-3)

    def test_shape_25_closed_stirrup_T10(self):
        """
        BS 8666 shape 25 — closed rectangular stirrup, T10.
        d=10, r=20, A=240, B=540 (as computed from beam oracle).
        Expected ≈ 1846.5 mm (see module docstring oracle).
        """
        cut = bar_cut_length("25", {"A": 240.0, "B": 540.0}, 10)
        # Compute expected analytically
        d = 10.0
        r = _min_bend_radius(d)  # 20
        bend_allow = 4 * (math.pi / 2.0) * (r + d / 2.0)
        hook = (3.0 * math.pi / 8.0) * (r + d / 2.0) + max(10 * d, 75.0)
        expected = 2.0 * (240 + 540) + bend_allow + hook
        assert abs(cut - expected) < 2.0  # within 2 mm (rounding)

    def test_shape_13_L_bend(self):
        """Shape 13: L-shape. L = A + B - 0.5r - d."""
        d = 16
        A, B = 1000.0, 300.0
        cut = bar_cut_length("13", {"A": A, "B": B}, d)
        r = _min_bend_radius(float(d))
        expected = A + B - 0.5 * r - d
        assert abs(cut - expected) < 1.0

    def test_shape_22_Z_bar(self):
        """Shape 22: Z-bar. L = A + B + C - r - 2d."""
        d = 12
        A, B, C = 500.0, 200.0, 500.0
        cut = bar_cut_length("22", {"A": A, "B": B, "C": C}, d)
        r = _min_bend_radius(float(d))
        expected = A + B + C - r - 2.0 * d
        assert abs(cut - expected) < 1.0

    def test_shape_51_circular_link(self):
        """Shape 51: circular link. L = π(A - d) + tail."""
        d = 10
        A = 300.0  # mean diameter
        cut = bar_cut_length("51", {"A": A}, d)
        tail = max(12.0 * d, 75.0)
        expected = math.pi * (A - d) + tail
        assert abs(cut - expected) < 1.0

    def test_unknown_shape_raises(self):
        with pytest.raises(ValueError, match="Unknown shape code"):
            bar_cut_length("99", {"A": 1000}, 16)

    def test_shape_code_description(self):
        desc = shape_code_description("25")
        assert "stirrup" in desc.lower() or "rectangular" in desc.lower()


# ---------------------------------------------------------------------------
# 3D bar placement — longitudinal bars
# ---------------------------------------------------------------------------

class TestLongitudinalPlacement:
    @pytest.fixture
    def section(self):
        return ConcreteSection(width_mm=300, depth_mm=600, length_mm=5000, cover_mm=25)

    def test_bottom_bars_y_offset(self, section):
        """Bottom bar centroid = cover + stirrup_d + bar_d/2 from bottom face."""
        bars = place_longitudinal_bars(
            section, bar_diameter_mm=16, n_bars_bottom=3, n_bars_top=2,
            stirrup_diameter_mm=10
        )
        bottom = next(b for b in bars if b.role == "longitudinal" and "1" in b.mark)
        # centreline stores Point3 objects; access .y
        cl_y = bottom.centreline[0].y
        expected_y = 25 + 10 + 16 / 2.0  # cover + stirrup + half bar = 43 mm
        assert abs(cl_y - expected_y) < 0.5

    def test_top_bars_y_offset(self, section):
        """Top bar centroid = depth - (cover + stirrup_d + bar_d/2) from bottom."""
        bars = place_longitudinal_bars(
            section, bar_diameter_mm=16, n_bars_bottom=3, n_bars_top=2,
            stirrup_diameter_mm=10
        )
        top = next(b for b in bars if b.role == "longitudinal" and "2" in b.mark)
        cl_y = top.centreline[0].y
        expected_y = 600 - (25 + 10 + 16 / 2.0)  # 543 mm
        assert abs(cl_y - expected_y) < 0.5

    def test_correct_bar_count(self, section):
        bars = place_longitudinal_bars(
            section, bar_diameter_mm=16, n_bars_bottom=3, n_bars_top=2,
            stirrup_diameter_mm=10
        )
        bot = next(b for b in bars if "1" in b.mark)
        top = next(b for b in bars if "2" in b.mark)
        assert bot.count == 3
        assert top.count == 2

    def test_cut_length_equals_member_length(self, section):
        """Straight longitudinal bars: cut length = member length."""
        bars = place_longitudinal_bars(
            section, bar_diameter_mm=16, n_bars_bottom=3, n_bars_top=2,
            stirrup_diameter_mm=10
        )
        for b in bars:
            assert b.cut_length_mm == pytest.approx(5000.0, rel=1e-3)

    def test_mass_computed_correctly(self, section):
        """T16 bar, 5000 mm, 3 bars: 1.579 kg/m × 5 m × 3 = 23.685 kg."""
        bars = place_longitudinal_bars(
            section, bar_diameter_mm=16, n_bars_bottom=3, n_bars_top=2,
            stirrup_diameter_mm=10
        )
        bot = next(b for b in bars if "1" in b.mark)
        expected = 1.579 * (5000.0 / 1000.0) * 3
        assert abs(bot.mass_kg - expected) < 0.01


# ---------------------------------------------------------------------------
# Stirrup placement
# ---------------------------------------------------------------------------

class TestStirrupPlacement:
    @pytest.fixture
    def section(self):
        return ConcreteSection(width_mm=300, depth_mm=600, length_mm=5000, cover_mm=25)

    def test_stirrup_count_oracle(self, section):
        """
        Oracle: usable = 5000 - 2×25 = 4950mm, spacing=200mm → 25 stirrups.
        """
        stirrups = place_stirrups(section, stirrup_diameter_mm=10, spacing_mm=200)
        assert len(stirrups) == 1
        assert stirrups[0].count == 25

    def test_stirrup_count_various_spacings(self, section):
        """Fewer stirrups with larger spacing."""
        s200 = place_stirrups(section, stirrup_diameter_mm=10, spacing_mm=200)
        s300 = place_stirrups(section, stirrup_diameter_mm=10, spacing_mm=300)
        assert s200[0].count > s300[0].count

    def test_stirrup_inner_dims(self, section):
        """
        Stirrup A = width - 2×cover - stirrup_d = 300 - 50 - 10 = 240 mm.
        Stirrup B = depth - 2×cover - stirrup_d = 600 - 50 - 10 = 540 mm.
        """
        stirrups = place_stirrups(section, stirrup_diameter_mm=10, spacing_mm=200)
        dims = stirrups[0].dims
        assert dims["A"] == pytest.approx(240.0, rel=1e-3)
        assert dims["B"] == pytest.approx(540.0, rel=1e-3)

    def test_stirrup_shape_code_25(self, section):
        stirrups = place_stirrups(section, stirrup_diameter_mm=10, spacing_mm=200)
        assert stirrups[0].shape_code == "25"

    def test_stirrup_role(self, section):
        stirrups = place_stirrups(section, stirrup_diameter_mm=10, spacing_mm=200)
        assert stirrups[0].role == "stirrup"


# ---------------------------------------------------------------------------
# detail_member integration
# ---------------------------------------------------------------------------

class TestDetailMember:
    def test_beam_returns_ok(self):
        result = detail_member(
            member_type="beam",
            length_mm=6000, width_mm=300, depth_mm=600, cover_mm=25,
            long_bar_diameter_mm=16, n_bars_bottom=3, n_bars_top=2,
            stirrup_diameter_mm=10, stirrup_spacing_mm=200,
        )
        assert result["ok"] is True

    def test_beam_has_longitudinal_and_stirrups(self):
        result = detail_member(
            member_type="beam",
            length_mm=6000, width_mm=300, depth_mm=600, cover_mm=25,
            long_bar_diameter_mm=16, n_bars_bottom=3, n_bars_top=2,
            stirrup_diameter_mm=10, stirrup_spacing_mm=200,
        )
        assert len(result["longitudinal_bars"]) == 2  # bottom + top
        assert len(result["stirrups"]) == 1

    def test_slab_has_no_stirrups(self):
        result = detail_member(
            member_type="slab",
            length_mm=5000, width_mm=1000, depth_mm=200, cover_mm=20,
            long_bar_diameter_mm=12, n_bars_bottom=5, n_bars_top=0,
            stirrup_diameter_mm=10, stirrup_spacing_mm=150,
        )
        assert result["stirrups"] == []

    def test_column_has_ties(self):
        result = detail_member(
            member_type="column",
            length_mm=3000, width_mm=400, depth_mm=400, cover_mm=30,
            long_bar_diameter_mm=20, n_bars_bottom=4, n_bars_top=4,
            stirrup_diameter_mm=10, stirrup_spacing_mm=200,
        )
        assert len(result["stirrups"]) == 1
        assert result["stirrups"][0]["role"] == "stirrup"

    def test_summary_total_count(self):
        result = detail_member(
            member_type="beam",
            length_mm=5000, width_mm=300, depth_mm=600, cover_mm=25,
            long_bar_diameter_mm=16, n_bars_bottom=3, n_bars_top=2,
            stirrup_diameter_mm=10, stirrup_spacing_mm=200,
        )
        manual_count = sum(b["count"] for b in result["all_bars"])
        assert result["summary"]["total_bar_count"] == manual_count

    def test_summary_mass_positive(self):
        result = detail_member(
            member_type="beam",
            length_mm=5000, width_mm=300, depth_mm=600, cover_mm=25,
            long_bar_diameter_mm=16, n_bars_bottom=3, n_bars_top=2,
            stirrup_diameter_mm=10, stirrup_spacing_mm=200,
        )
        assert result["summary"]["total_mass_kg"] > 0

    def test_section_geometry_in_result(self):
        result = detail_member(
            member_type="beam",
            length_mm=5000, width_mm=300, depth_mm=600, cover_mm=25,
            long_bar_diameter_mm=16, n_bars_bottom=3, n_bars_top=2,
            stirrup_diameter_mm=10, stirrup_spacing_mm=200,
        )
        sec = result["section"]
        assert sec["width_mm"] == 300
        assert sec["depth_mm"] == 600
        assert sec["cover_mm"] == 25

    def test_bar_centreline_present(self):
        result = detail_member(
            member_type="beam",
            length_mm=5000, width_mm=300, depth_mm=600, cover_mm=25,
            long_bar_diameter_mm=16, n_bars_bottom=3, n_bars_top=2,
            stirrup_diameter_mm=10, stirrup_spacing_mm=200,
        )
        for bar in result["all_bars"]:
            assert "centreline" in bar
            assert len(bar["centreline"]) >= 2
            assert len(bar["centreline"][0]) == 3  # [x, y, z]


# ---------------------------------------------------------------------------
# Bending schedule
# ---------------------------------------------------------------------------

class TestBendingSchedule:
    @pytest.fixture
    def two_beam_members(self):
        """Two beams: B1 and B2, each with 3×T16 bottom + 2×T16 top + 25×T10 stirrups."""
        def _detail(ref):
            d = detail_member(
                member_type="beam",
                length_mm=5000, width_mm=300, depth_mm=600, cover_mm=25,
                long_bar_diameter_mm=16, n_bars_bottom=3, n_bars_top=2,
                stirrup_diameter_mm=10, stirrup_spacing_mm=200,
            )
            return {"member_ref": ref, "all_bars": d["all_bars"]}
        return [_detail("B1"), _detail("B2")]

    def test_schedule_has_rows(self, two_beam_members):
        sched = generate_bending_schedule(two_beam_members)
        assert sched["ok"] is True
        assert len(sched["rows"]) > 0

    def test_schedule_row_count_matches(self, two_beam_members):
        """2 members × 3 bar types (bot, top, stir) = 6 rows."""
        sched = generate_bending_schedule(two_beam_members)
        assert sched["summary"]["row_count"] == 6

    def test_mass_is_sum_of_rows(self, two_beam_members):
        sched = generate_bending_schedule(two_beam_members)
        manual_mass = sum(r["mass_kg"] for r in sched["rows"])
        assert abs(sched["summary"]["total_mass_kg"] - manual_mass) < 0.01

    def test_total_mass_positive(self, two_beam_members):
        sched = generate_bending_schedule(two_beam_members)
        assert sched["summary"]["total_mass_kg"] > 0

    def test_member_refs_present(self, two_beam_members):
        sched = generate_bending_schedule(two_beam_members)
        refs = {r["member_ref"] for r in sched["rows"]}
        assert "B1" in refs and "B2" in refs

    def test_known_mass_oracle(self):
        """
        B1: 3×T16@5000 bottom.
        Mass = 1.579 kg/m × 5.0m × 3 = 23.685 kg
        """
        d = detail_member(
            member_type="beam",
            length_mm=5000, width_mm=300, depth_mm=600, cover_mm=25,
            long_bar_diameter_mm=16, n_bars_bottom=3, n_bars_top=0,
            stirrup_diameter_mm=10, stirrup_spacing_mm=9999,  # minimal stirrups
        )
        sched = generate_bending_schedule([{"member_ref": "B1", "all_bars": d["all_bars"]}])
        # Find the longitudinal (T16) row
        long_rows = [r for r in sched["rows"] if r["diameter_mm"] == 16 and r["number_of_bars"] == 3]
        assert len(long_rows) == 1
        expected_mass = 1.579 * (5000.0 / 1000.0) * 3
        assert abs(long_rows[0]["mass_kg"] - expected_mass) < 0.05

    def test_all_bars_have_shape_codes(self, two_beam_members):
        sched = generate_bending_schedule(two_beam_members)
        for row in sched["rows"]:
            assert row["shape_code"] in ("00", "25", "26", "13", "21", "22", "31", "38", "41", "51", "11", "12")


# ---------------------------------------------------------------------------
# Shop drawing
# ---------------------------------------------------------------------------

class TestShopDrawing:
    @pytest.fixture
    def beam_detail(self):
        return detail_member(
            member_type="beam",
            length_mm=6000, width_mm=300, depth_mm=600, cover_mm=25,
            long_bar_diameter_mm=16, n_bars_bottom=3, n_bars_top=2,
            stirrup_diameter_mm=10, stirrup_spacing_mm=200,
        )

    @pytest.fixture
    def schedule_rows(self, beam_detail):
        sched = generate_bending_schedule([{"member_ref": "B1", "all_bars": beam_detail["all_bars"]}])
        return sched["rows"]

    def test_shop_drawing_ok(self, beam_detail, schedule_rows):
        drawing = generate_shop_drawing(
            member_ref="B1",
            member_type="beam",
            length_mm=6000, width_mm=300, depth_mm=600, cover_mm=25,
            long_bar_diameter_mm=16, n_bars_bottom=3, n_bars_top=2,
            stirrup_diameter_mm=10, stirrup_spacing_mm=200,
            bending_schedule_rows=schedule_rows,
        )
        assert drawing["ok"] is True

    def test_shop_drawing_two_sheets(self, beam_detail, schedule_rows):
        drawing = generate_shop_drawing(
            member_ref="B1", member_type="beam",
            length_mm=6000, width_mm=300, depth_mm=600, cover_mm=25,
            long_bar_diameter_mm=16, n_bars_bottom=3, n_bars_top=2,
            stirrup_diameter_mm=10, stirrup_spacing_mm=200,
            bending_schedule_rows=schedule_rows,
        )
        assert len(drawing["sheets"]) == 2

    def test_sheet_1_has_entities(self, beam_detail, schedule_rows):
        drawing = generate_shop_drawing(
            member_ref="B1", member_type="beam",
            length_mm=6000, width_mm=300, depth_mm=600, cover_mm=25,
            long_bar_diameter_mm=16, n_bars_bottom=3, n_bars_top=2,
            stirrup_diameter_mm=10, stirrup_spacing_mm=200,
            bending_schedule_rows=schedule_rows,
        )
        assert drawing["sheets"][0]["entity_count"] > 10

    def test_sheet_2_has_schedule_rows(self, beam_detail, schedule_rows):
        """Sheet 2 is the bending schedule — check it has table entities."""
        drawing = generate_shop_drawing(
            member_ref="B1", member_type="beam",
            length_mm=6000, width_mm=300, depth_mm=600, cover_mm=25,
            long_bar_diameter_mm=16, n_bars_bottom=3, n_bars_top=2,
            stirrup_diameter_mm=10, stirrup_spacing_mm=200,
            bending_schedule_rows=schedule_rows,
        )
        sheet2 = drawing["sheets"][1]
        assert sheet2["entity_count"] > 0
        # There should be text entities containing bar marks
        texts = [e for e in sheet2["entities"] if e["type"] == "text"]
        assert len(texts) > 0

    def test_member_ref_in_drawing(self, beam_detail, schedule_rows):
        drawing = generate_shop_drawing(
            member_ref="B1", member_type="beam",
            length_mm=6000, width_mm=300, depth_mm=600, cover_mm=25,
            long_bar_diameter_mm=16, n_bars_bottom=3, n_bars_top=2,
            stirrup_diameter_mm=10, stirrup_spacing_mm=200,
            bending_schedule_rows=schedule_rows,
        )
        assert drawing["member_ref"] == "B1"

    def test_title_block_present(self, beam_detail, schedule_rows):
        drawing = generate_shop_drawing(
            member_ref="B1", member_type="beam",
            length_mm=6000, width_mm=300, depth_mm=600, cover_mm=25,
            long_bar_diameter_mm=16, n_bars_bottom=3, n_bars_top=2,
            stirrup_diameter_mm=10, stirrup_spacing_mm=200,
            bending_schedule_rows=schedule_rows,
            title_block={"project_name": "TestProject", "drawn_by": "KerfBot"},
        )
        tb = drawing["title_block"]
        assert tb["project_name"] == "TestProject"
        assert tb["drawn_by"] == "KerfBot"

    def test_summary_mass_matches_schedule(self, beam_detail, schedule_rows):
        drawing = generate_shop_drawing(
            member_ref="B1", member_type="beam",
            length_mm=6000, width_mm=300, depth_mm=600, cover_mm=25,
            long_bar_diameter_mm=16, n_bars_bottom=3, n_bars_top=2,
            stirrup_diameter_mm=10, stirrup_spacing_mm=200,
            bending_schedule_rows=schedule_rows,
        )
        expected_mass = round(sum(r["mass_kg"] for r in schedule_rows), 3)
        assert abs(drawing["summary"]["total_mass_kg"] - expected_mass) < 0.01

    def test_section_entities_include_rects_and_circles(self, beam_detail, schedule_rows):
        """Section view should contain outline rect + stirrup rect + bar circles."""
        drawing = generate_shop_drawing(
            member_ref="B1", member_type="beam",
            length_mm=6000, width_mm=300, depth_mm=600, cover_mm=25,
            long_bar_diameter_mm=16, n_bars_bottom=3, n_bars_top=2,
            stirrup_diameter_mm=10, stirrup_spacing_mm=200,
            bending_schedule_rows=schedule_rows,
        )
        sheet1_entities = drawing["sheets"][0]["entities"]
        rects = [e for e in sheet1_entities if e["type"] == "rect"]
        circles = [e for e in sheet1_entities if e["type"] == "circle"]
        assert len(rects) >= 2   # at least outer + stirrup
        assert len(circles) >= 5  # 3 bottom + 2 top bars

    def test_assembly_marks_in_sheet1(self, beam_detail, schedule_rows):
        """Sheet 1 should have text with member mark 'B1'."""
        drawing = generate_shop_drawing(
            member_ref="B1", member_type="beam",
            length_mm=6000, width_mm=300, depth_mm=600, cover_mm=25,
            long_bar_diameter_mm=16, n_bars_bottom=3, n_bars_top=2,
            stirrup_diameter_mm=10, stirrup_spacing_mm=200,
            bending_schedule_rows=schedule_rows,
        )
        texts = [e["text"] for e in drawing["sheets"][0]["entities"] if e["type"] == "text"]
        assert any("B1" in t for t in texts)


# ---------------------------------------------------------------------------
# GA drawing
# ---------------------------------------------------------------------------

class TestGADrawing:
    @pytest.fixture
    def members(self):
        members = []
        for i, (ref, x, y) in enumerate([("B1", 0, 0), ("B2", 6000, 0), ("C1", 3000, 3000)]):
            d = detail_member(
                member_type="beam" if ref.startswith("B") else "column",
                length_mm=6000 if ref.startswith("B") else 3000,
                width_mm=300, depth_mm=600 if ref.startswith("B") else 400,
                cover_mm=25,
                long_bar_diameter_mm=16, n_bars_bottom=3, n_bars_top=2,
                stirrup_diameter_mm=10, stirrup_spacing_mm=200,
            )
            members.append({
                "member_ref": ref,
                "member_type": d["member_type"],
                "x_mm": float(x),
                "y_mm": float(y),
                "width_mm": 300,
                "depth_mm": d["section"]["depth_mm"],
                "length_mm": d["section"]["length_mm"],
                "all_bars": d["all_bars"],
            })
        return members

    def test_ga_drawing_ok(self, members):
        ga = generate_ga_drawing(members)
        assert ga["ok"] is True

    def test_ga_has_three_sheets(self, members):
        ga = generate_ga_drawing(members)
        assert len(ga["sheets"]) == 3

    def test_ga_sheet1_is_plan(self, members):
        ga = generate_ga_drawing(members)
        assert "Plan" in ga["sheets"][0]["title"] or "GA" in ga["sheets"][0]["title"]

    def test_ga_sheet3_is_schedule(self, members):
        ga = generate_ga_drawing(members)
        assert "Schedule" in ga["sheets"][2]["title"] or "BBS" in ga["sheets"][2]["title"]

    def test_ga_summary_member_count(self, members):
        ga = generate_ga_drawing(members)
        assert ga["summary"]["member_count"] == 3

    def test_ga_total_mass_positive(self, members):
        ga = generate_ga_drawing(members)
        assert ga["summary"]["total_mass_kg"] > 0
