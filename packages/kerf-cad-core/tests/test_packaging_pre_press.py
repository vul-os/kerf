"""
Tests for kerf_cad_core.packaging.pre_press

Covers:
  - BleedTrimSpec geometry (bleed_box, safety_box)
  - RegistrationMark validation
  - SpotColorLayer validation
  - check_pre_press — bleed ok / bleed too small / safety zone breach / marks insufficient
  - generate_registration_marks — 4 corners, correct positions
  - export_pdf_x_1a — returns bytes, has PDF header, has PDF/X-1a XMP marker
  - pre_press_tools wrappers — check, gen_marks, add_spot_color, bleed_box, plate_count, export

References: ISO 15930-1:2001, ISO 12647-2:2013, GRACoL 2013.
"""

import math
import pytest

from kerf_cad_core.packaging.pre_press import (
    BleedTrimSpec,
    PrePressJob,
    PrePressReport,
    RegistrationMark,
    SpotColorLayer,
    check_pre_press,
    export_pdf_x_1a,
    generate_registration_marks,
)
from kerf_cad_core.packaging.pre_press_tools import (
    _tool_prepress_add_spot_color,
    _tool_prepress_bleed_box,
    _tool_prepress_check,
    _tool_prepress_export_pdf_x1a,
    _tool_prepress_gen_marks,
    _tool_prepress_plate_count,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

TRIM_BOX = (10.0, 10.0, 210.0, 297.0)  # A4 trim area placed at offset (10,10)
ARTWORK_BBOX_SAFE = (20.0, 20.0, 200.0, 287.0)  # inside safety zone
ARTWORK_BBOX_BREACH = (12.0, 12.0, 208.0, 295.0)  # outside safety zone


def _default_bt(bleed: float = 3.0, safety: float = 4.0) -> BleedTrimSpec:
    return BleedTrimSpec(trim_box=TRIM_BOX, bleed_mm=bleed, safety_zone_mm=safety)


def _make_marks(bt: BleedTrimSpec) -> list[RegistrationMark]:
    return generate_registration_marks(bt)


def _default_job(bleed: float = 3.0) -> PrePressJob:
    bt = _default_bt(bleed=bleed)
    marks = _make_marks(bt)
    spots = [
        SpotColorLayer("pantone_485", "PANTONE 485 C", 40.0),
        SpotColorLayer("spot_uv", "Spot UV varnish", 100.0, overprint=True),
    ]
    return PrePressJob(
        bleed_trim=bt,
        registration_marks=marks,
        spot_colors=spots,
        finishing=["varnish_gloss", "foil_stamp"],
    )


# ---------------------------------------------------------------------------
# 1. BleedTrimSpec geometry
# ---------------------------------------------------------------------------

class TestBleedTrimSpec:
    def test_bleed_box(self):
        bt = _default_bt(bleed=3.0)
        bb = bt.bleed_box
        assert bb[0] == pytest.approx(TRIM_BOX[0] - 3.0)
        assert bb[1] == pytest.approx(TRIM_BOX[1] - 3.0)
        assert bb[2] == pytest.approx(TRIM_BOX[2] + 3.0)
        assert bb[3] == pytest.approx(TRIM_BOX[3] + 3.0)

    def test_safety_box(self):
        bt = _default_bt(safety=4.0)
        sb = bt.safety_box
        assert sb[0] == pytest.approx(TRIM_BOX[0] + 4.0)
        assert sb[1] == pytest.approx(TRIM_BOX[1] + 4.0)
        assert sb[2] == pytest.approx(TRIM_BOX[2] - 4.0)
        assert sb[3] == pytest.approx(TRIM_BOX[3] - 4.0)

    def test_trim_dimensions(self):
        bt = _default_bt()
        assert bt.trim_width_mm == pytest.approx(200.0)
        assert bt.trim_height_mm == pytest.approx(287.0)

    def test_bleed_5mm(self):
        bt = BleedTrimSpec(trim_box=(0.0, 0.0, 100.0, 200.0), bleed_mm=5.0)
        bb = bt.bleed_box
        assert bb == pytest.approx((-5.0, -5.0, 105.0, 205.0))


# ---------------------------------------------------------------------------
# 2. RegistrationMark validation
# ---------------------------------------------------------------------------

class TestRegistrationMark:
    def test_valid_cross(self):
        m = RegistrationMark(position=(5.0, 5.0), kind="cross", color_layers=["cyan"])
        assert m.kind == "cross"

    def test_valid_circle(self):
        m = RegistrationMark(position=(0.0, 0.0), kind="circle", color_layers=["black"])
        assert m.kind == "circle"

    def test_valid_corner_bracket(self):
        m = RegistrationMark(position=(3.0, 3.0), kind="corner_bracket", color_layers=["cyan", "black"])
        assert m.kind == "corner_bracket"

    def test_invalid_kind(self):
        with pytest.raises(ValueError, match="kind"):
            RegistrationMark(position=(0.0, 0.0), kind="star", color_layers=["cyan"])

    def test_empty_color_layers(self):
        with pytest.raises(ValueError, match="color_layers"):
            RegistrationMark(position=(0.0, 0.0), kind="cross", color_layers=[])


# ---------------------------------------------------------------------------
# 3. SpotColorLayer validation
# ---------------------------------------------------------------------------

class TestSpotColorLayer:
    def test_valid(self):
        sc = SpotColorLayer("p485", "PANTONE 485 C", 45.0)
        assert sc.coverage_pct == 45.0
        assert sc.overprint is False

    def test_overprint_true(self):
        sc = SpotColorLayer("uv", "Spot UV", 100.0, overprint=True)
        assert sc.overprint is True

    def test_coverage_out_of_range_negative(self):
        with pytest.raises(ValueError, match="coverage_pct"):
            SpotColorLayer("x", "y", -1.0)

    def test_coverage_out_of_range_over_100(self):
        with pytest.raises(ValueError, match="coverage_pct"):
            SpotColorLayer("x", "y", 101.0)


# ---------------------------------------------------------------------------
# 4. generate_registration_marks
# ---------------------------------------------------------------------------

class TestGenerateRegistrationMarks:
    def test_returns_4_marks(self):
        bt = _default_bt()
        marks = generate_registration_marks(bt)
        assert len(marks) == 4

    def test_all_corner_bracket_by_default(self):
        bt = _default_bt()
        marks = generate_registration_marks(bt)
        assert all(m.kind == "corner_bracket" for m in marks)

    def test_cross_kind(self):
        bt = _default_bt()
        marks = generate_registration_marks(bt, kind="cross")
        assert all(m.kind == "cross" for m in marks)

    def test_marks_outside_trim_box(self):
        """All marks must be outside the trim box (in the slug area)."""
        bt = _default_bt(bleed=3.0)
        marks = generate_registration_marks(bt)
        x0, y0, x1, y1 = TRIM_BOX
        for m in marks:
            px, py = m.position
            # At least one coordinate should be outside trim
            assert px < x0 or px > x1 or py < y0 or py > y1, (
                f"Mark at {m.position} appears to be inside trim box"
            )

    def test_cmyk_default_layers(self):
        bt = _default_bt()
        marks = generate_registration_marks(bt)
        for m in marks:
            assert set(m.color_layers) == {"cyan", "magenta", "yellow", "black"}

    def test_custom_layers(self):
        bt = _default_bt()
        marks = generate_registration_marks(bt, color_layers=["cyan", "black", "pantone_485"])
        for m in marks:
            assert "pantone_485" in m.color_layers

    def test_invalid_kind_raises(self):
        bt = _default_bt()
        with pytest.raises(ValueError):
            generate_registration_marks(bt, kind="star")

    def test_mark_positions_cover_all_corners(self):
        """Marks should be at 4 distinct quadrant positions."""
        bt = BleedTrimSpec(trim_box=(0.0, 0.0, 100.0, 100.0), bleed_mm=3.0)
        marks = generate_registration_marks(bt)
        xs = {m.position[0] for m in marks}
        ys = {m.position[1] for m in marks}
        # Should have exactly 2 x values (left / right) and 2 y values (bottom / top)
        assert len(xs) == 2
        assert len(ys) == 2


# ---------------------------------------------------------------------------
# 5. check_pre_press
# ---------------------------------------------------------------------------

class TestCheckPrePress:
    def test_all_ok(self):
        job = _default_job(bleed=3.0)
        report = check_pre_press(job, ARTWORK_BBOX_SAFE)
        assert report.bleed_mm_correct is True
        assert report.safety_zone_clear is True
        assert report.registration_mark_count == 4
        assert report.n_spot_colors == 2
        assert report.pdf_x_1a_compliant is True
        assert report.estimated_plate_count == 6  # 4 CMYK + 2 spot

    def test_bleed_too_small(self):
        job = _default_job(bleed=2.0)
        report = check_pre_press(job, ARTWORK_BBOX_SAFE)
        assert report.bleed_mm_correct is False
        assert any("BLEED-INSUFFICIENT" in w for w in report.warnings)

    def test_safety_zone_breach(self):
        job = _default_job(bleed=3.0)
        report = check_pre_press(job, ARTWORK_BBOX_BREACH)
        assert report.safety_zone_clear is False
        assert any("SAFETY-ZONE" in w for w in report.warnings)

    def test_no_registration_marks(self):
        bt = _default_bt()
        job = PrePressJob(
            bleed_trim=bt,
            registration_marks=[],
            spot_colors=[],
            finishing=[],
        )
        report = check_pre_press(job, ARTWORK_BBOX_SAFE)
        assert report.registration_mark_count == 0
        assert report.pdf_x_1a_compliant is False
        assert any("REGISTRATION" in w for w in report.warnings)

    def test_plate_count_no_spots(self):
        bt = _default_bt()
        marks = _make_marks(bt)
        job = PrePressJob(bleed_trim=bt, registration_marks=marks, spot_colors=[], finishing=[])
        report = check_pre_press(job, ARTWORK_BBOX_SAFE)
        assert report.estimated_plate_count == 4  # CMYK only

    def test_plate_count_three_spots(self):
        bt = _default_bt()
        marks = _make_marks(bt)
        spots = [
            SpotColorLayer("p485", "PANTONE 485 C", 30.0),
            SpotColorLayer("uv", "Spot UV varnish", 100.0, overprint=True),
            SpotColorLayer("foil", "foil_gold", 20.0, overprint=True),
        ]
        job = PrePressJob(bleed_trim=bt, registration_marks=marks, spot_colors=spots, finishing=[])
        report = check_pre_press(job, ARTWORK_BBOX_SAFE)
        assert report.estimated_plate_count == 7  # 4 + 3

    def test_unknown_finishing_warns(self):
        job = _default_job()
        job.finishing = ["magic_glitter"]
        report = check_pre_press(job, ARTWORK_BBOX_SAFE)
        assert any("FINISHING-UNKNOWN" in w for w in report.warnings)

    def test_honest_caveat_always_present(self):
        job = _default_job()
        report = check_pre_press(job, ARTWORK_BBOX_SAFE)
        assert any("HONEST-CAVEAT" in w for w in report.warnings)


# ---------------------------------------------------------------------------
# 6. export_pdf_x_1a
# ---------------------------------------------------------------------------

class TestExportPdfX1a:
    def test_returns_bytes(self):
        job = _default_job()
        pdf = export_pdf_x_1a(job, "<svg/>")
        assert isinstance(pdf, bytes)
        assert len(pdf) > 100

    def test_pdf_header(self):
        job = _default_job()
        pdf = export_pdf_x_1a(job, "")
        assert pdf.startswith(b"%PDF-1.3")

    def test_pdf_x_1a_marker_in_xmp(self):
        job = _default_job()
        pdf = export_pdf_x_1a(job, "")
        assert b"PDF/X-1a:2001" in pdf

    def test_trim_box_present(self):
        job = _default_job()
        pdf = export_pdf_x_1a(job, "")
        assert b"/TrimBox" in pdf

    def test_bleed_box_present(self):
        job = _default_job()
        pdf = export_pdf_x_1a(job, "")
        assert b"/BleedBox" in pdf

    def test_output_intents_cmyk(self):
        job = _default_job()
        pdf = export_pdf_x_1a(job, "")
        assert b"GTS_PDFX" in pdf or b"OutputIntents" in pdf

    def test_eof_marker(self):
        job = _default_job()
        pdf = export_pdf_x_1a(job, "")
        assert b"%%EOF" in pdf

    def test_empty_artwork_svg(self):
        """Should succeed with empty SVG."""
        job = _default_job()
        pdf = export_pdf_x_1a(job, "")
        assert pdf.startswith(b"%PDF")

    def test_large_trim_box(self):
        """A0 poster trim box."""
        bt = BleedTrimSpec(trim_box=(0.0, 0.0, 841.0, 1189.0), bleed_mm=5.0)
        marks = generate_registration_marks(bt)
        job = PrePressJob(bleed_trim=bt, registration_marks=marks, spot_colors=[], finishing=[])
        pdf = export_pdf_x_1a(job, "")
        assert b"/TrimBox" in pdf


# ---------------------------------------------------------------------------
# 7. Tool wrappers
# ---------------------------------------------------------------------------

class TestToolPrePressCheck:
    def test_valid(self):
        result = _tool_prepress_check(
            trim_box=[10.0, 10.0, 210.0, 297.0],
            bleed_mm=3.0,
            safety_zone_mm=4.0,
            registration_marks=[
                {"position": [3.0, 3.0], "kind": "corner_bracket", "color_layers": ["cyan", "black"]},
                {"position": [217.0, 3.0], "kind": "corner_bracket", "color_layers": ["cyan", "black"]},
                {"position": [217.0, 304.0], "kind": "corner_bracket", "color_layers": ["cyan", "black"]},
                {"position": [3.0, 304.0], "kind": "corner_bracket", "color_layers": ["cyan", "black"]},
            ],
            artwork_bbox=[20.0, 20.0, 200.0, 287.0],
        )
        assert result["ok"] is True
        assert result["bleed_mm_correct"] is True
        assert result["safety_zone_clear"] is True
        assert result["estimated_plate_count"] == 4

    def test_bad_trim_box(self):
        result = _tool_prepress_check(trim_box=[10.0, 10.0])
        assert result["ok"] is False
        assert "trim_box" in result["reason"]


class TestToolGenMarks:
    def test_returns_4_marks(self):
        result = _tool_prepress_gen_marks(trim_box=[0.0, 0.0, 100.0, 200.0])
        assert result["ok"] is True
        assert len(result["marks"]) == 4

    def test_mark_positions_are_lists(self):
        result = _tool_prepress_gen_marks(trim_box=[0.0, 0.0, 100.0, 200.0])
        for m in result["marks"]:
            assert isinstance(m["position"], list)
            assert len(m["position"]) == 2

    def test_bad_trim_box(self):
        result = _tool_prepress_gen_marks(trim_box=[1.0])
        assert result["ok"] is False


class TestToolAddSpotColor:
    def test_valid_pantone(self):
        result = _tool_prepress_add_spot_color("p485", "PANTONE 485 C", 40.0)
        assert result["ok"] is True
        assert result["plate_adds"] == 1

    def test_foil_overprint_warning(self):
        result = _tool_prepress_add_spot_color("foil", "foil_gold", 20.0, overprint=False)
        assert result["ok"] is True
        assert any("foil" in w.lower() for w in result["warnings"])

    def test_varnish_overprint_warning(self):
        result = _tool_prepress_add_spot_color("uv", "Spot UV varnish", 100.0, overprint=False)
        assert result["ok"] is True
        assert any("varnish" in w.lower() for w in result["warnings"])

    def test_coverage_out_of_range(self):
        result = _tool_prepress_add_spot_color("x", "y", 150.0)
        assert result["ok"] is False


class TestToolBleedBox:
    def test_basic(self):
        result = _tool_prepress_bleed_box(trim_box=[0.0, 0.0, 100.0, 200.0], bleed_mm=3.0)
        assert result["ok"] is True
        assert result["bleed_box"] == pytest.approx([-3.0, -3.0, 103.0, 203.0])
        assert result["safety_box"] == pytest.approx([4.0, 4.0, 96.0, 196.0])

    def test_dimensions(self):
        result = _tool_prepress_bleed_box(trim_box=[10.0, 10.0, 110.0, 210.0])
        assert result["trim_width_mm"] == pytest.approx(100.0)
        assert result["trim_height_mm"] == pytest.approx(200.0)


class TestToolPlateCount:
    def test_cmyk_only(self):
        result = _tool_prepress_plate_count()
        assert result["ok"] is True
        assert result["total_plates"] == 4

    def test_with_spots(self):
        result = _tool_prepress_plate_count(spot_colors=["PANTONE 485 C", "foil_gold"])
        assert result["total_plates"] == 6  # 4 + 2

    def test_with_varnish_finishing(self):
        result = _tool_prepress_plate_count(
            spot_colors=["PANTONE 485 C"],
            finishing=["varnish_gloss", "foil_stamp"],
        )
        assert result["total_plates"] == 7  # 4 + 1 spot + 2 finishing

    def test_die_cut_no_plate(self):
        """Die cutting does not add a printing plate."""
        result = _tool_prepress_plate_count(finishing=["die_cut"])
        assert result["total_plates"] == 4


class TestToolExportPdfX1a:
    def test_valid(self):
        result = _tool_prepress_export_pdf_x1a(trim_box=[0.0, 0.0, 100.0, 200.0])
        assert result["ok"] is True
        assert result["pdf_size_bytes"] > 100
        assert "honest_caveat" in result

    def test_with_spot_colors(self):
        result = _tool_prepress_export_pdf_x1a(
            trim_box=[0.0, 0.0, 100.0, 200.0],
            spot_colors=[{"layer_id": "p485", "color_name": "PANTONE 485 C", "coverage_pct": 40.0}],
        )
        assert result["ok"] is True
        assert "PANTONE 485 C" in result["spot_colors"]

    def test_bad_trim_box(self):
        result = _tool_prepress_export_pdf_x1a(trim_box="bad")
        assert result["ok"] is False
