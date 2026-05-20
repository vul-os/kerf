"""
Tests for kerf_textiles.sublimation — dye-sub continuous-tone pipeline.

DoD oracles
-----------
1. Unwrap cylinder → flat panel preserves lateral area to 1%.
2. Bleed margin width matches the requested mm value (within 1 pixel rounding).
3. Registration marks are present at all 4 corners.
4. PNG round-trip: save projected image, reload, pixel array is identical.
5. project_artwork produces an image with the correct output dimensions.
"""

from __future__ import annotations

import io
import math

import numpy as np
import pytest

try:
    from PIL import Image
except ImportError:
    pytest.skip("Pillow not available", allow_module_level=True)

from kerf_textiles.sublimation import (
    unwrap_cylinder,
    project_artwork,
    add_bleed,
    add_registration_marks,
    render_panel_png,
    mm_to_px,
    px_to_mm,
    CylinderPanel,
    BleedResult,
    RegMarkResult,
    SubliResult,
    DEFAULT_DPI,
    DEFAULT_BLEED_MM,
    REG_MARK_SIZE_MM,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _solid_image(w: int = 64, h: int = 48, colour: tuple = (255, 0, 0, 255)) -> Image.Image:
    """Create a small solid-colour RGBA image for testing."""
    img = Image.new("RGBA", (w, h), colour)
    return img


def _gradient_image(w: int = 64, h: int = 48) -> Image.Image:
    """Create a simple RGB gradient image."""
    arr = np.zeros((h, w, 3), dtype=np.uint8)
    arr[:, :, 0] = np.linspace(0, 255, w, dtype=np.uint8)
    arr[:, :, 1] = np.linspace(0, 255, h, dtype=np.uint8).reshape(-1, 1)
    return Image.fromarray(arr, mode="RGB")


# ---------------------------------------------------------------------------
# unwrap_cylinder
# ---------------------------------------------------------------------------

class TestUnwrapCylinder:

    def test_returns_cylinder_panel(self):
        panel = unwrap_cylinder(radius_mm=50.0, height_mm=100.0)
        assert isinstance(panel, CylinderPanel)

    def test_width_equals_circumference(self):
        """Panel width (mm) should equal 2π·radius."""
        r = 40.0
        panel = unwrap_cylinder(radius_mm=r, height_mm=80.0)
        expected_w = 2.0 * math.pi * r
        assert abs(panel.width_mm - expected_w) < 1e-9

    def test_area_preserved_to_1pct(self):
        """
        Analytic oracle: flat_area / cylinder_lateral_area must be within 1%.

        cylinder_lateral_area = 2π·r·h
        flat_area              = (2π·r) · h   (same value)
        ratio must be ≈ 1.0.
        """
        r, h = 55.0, 120.0
        panel = unwrap_cylinder(radius_mm=r, height_mm=h)
        cylinder_area = 2.0 * math.pi * r * h
        flat_area = panel.area_mm2
        ratio = flat_area / cylinder_area
        assert abs(ratio - 1.0) < 0.01, (
            f"Area ratio {ratio:.6f} deviates from 1.0 by more than 1%"
        )

    def test_area_ratio_exactly_one(self):
        """Area is exactly preserved (no approximation in unwrap)."""
        r, h = 30.0, 60.0
        panel = unwrap_cylinder(radius_mm=r, height_mm=h)
        flat_area = panel.width_mm * panel.height_mm
        cylinder_area = 2.0 * math.pi * r * h
        ratio = flat_area / cylinder_area
        assert ratio == pytest.approx(1.0, abs=1e-9)

    def test_pixel_dimensions_positive(self):
        panel = unwrap_cylinder(radius_mm=20.0, height_mm=50.0, dpi=72)
        assert panel.width_px > 0
        assert panel.height_px > 0

    def test_uv_grid_shape(self):
        panel = unwrap_cylinder(radius_mm=20.0, height_mm=30.0, dpi=72)
        h, w, c = panel.uv_grid.shape
        assert h == panel.height_px
        assert w == panel.width_px
        assert c == 2

    def test_uv_grid_range(self):
        """UV grid must be in [0, 1]."""
        panel = unwrap_cylinder(radius_mm=15.0, height_mm=25.0, dpi=72)
        assert float(panel.uv_grid[:, :, 0].min()) == pytest.approx(0.0, abs=1e-6)
        assert float(panel.uv_grid[:, :, 0].max()) == pytest.approx(1.0, abs=1e-6)
        assert float(panel.uv_grid[:, :, 1].min()) == pytest.approx(0.0, abs=1e-6)
        assert float(panel.uv_grid[:, :, 1].max()) == pytest.approx(1.0, abs=1e-6)

    def test_invalid_radius(self):
        with pytest.raises(ValueError, match="radius_mm"):
            unwrap_cylinder(radius_mm=0.0, height_mm=50.0)

    def test_invalid_height(self):
        with pytest.raises(ValueError, match="height_mm"):
            unwrap_cylinder(radius_mm=30.0, height_mm=-5.0)

    def test_different_dpi(self):
        """Higher DPI should produce more pixels."""
        p_low = unwrap_cylinder(radius_mm=20.0, height_mm=40.0, dpi=72)
        p_high = unwrap_cylinder(radius_mm=20.0, height_mm=40.0, dpi=300)
        assert p_high.width_px > p_low.width_px
        assert p_high.height_px > p_low.height_px


# ---------------------------------------------------------------------------
# project_artwork
# ---------------------------------------------------------------------------

class TestProjectArtwork:

    def test_output_dimensions_match_panel(self):
        """Projected image must match panel pixel dimensions exactly."""
        panel = unwrap_cylinder(radius_mm=40.0, height_mm=80.0, dpi=72)
        art = _solid_image(32, 24)
        result = project_artwork(panel, art)
        assert result.size == (panel.width_px, panel.height_px)

    def test_output_is_rgba(self):
        panel = unwrap_cylinder(radius_mm=40.0, height_mm=80.0, dpi=72)
        art = _solid_image()
        result = project_artwork(panel, art)
        assert result.mode == "RGBA"

    def test_solid_colour_preserved(self):
        """Projecting a solid-colour image should give a solid result (no artefacts)."""
        panel = unwrap_cylinder(radius_mm=30.0, height_mm=60.0, dpi=72)
        colour = (128, 64, 200, 255)
        art = Image.new("RGBA", (50, 50), colour)
        result = project_artwork(panel, art)
        arr = np.array(result)
        # All pixels should be (approximately) the same solid colour
        assert arr[:, :, 0].std() < 2
        assert arr[:, :, 1].std() < 2
        assert arr[:, :, 2].std() < 2

    def test_png_round_trip(self):
        """
        Save the projected image as PNG, reload, compare pixel arrays.

        PNG is lossless — pixel values must be identical.
        """
        panel = unwrap_cylinder(radius_mm=30.0, height_mm=50.0, dpi=72)
        art = _gradient_image(40, 30)
        projected = project_artwork(panel, art)

        buf = io.BytesIO()
        projected.save(buf, format="PNG")
        buf.seek(0)
        reloaded = Image.open(buf)
        reloaded.load()

        original_arr = np.array(projected)
        reloaded_arr = np.array(reloaded)
        np.testing.assert_array_equal(original_arr, reloaded_arr)


# ---------------------------------------------------------------------------
# add_bleed
# ---------------------------------------------------------------------------

class TestAddBleed:

    def test_returns_bleed_result(self):
        img = _solid_image(60, 40)
        result = add_bleed(img, bleed_mm=3.0, dpi=DEFAULT_DPI)
        assert isinstance(result, BleedResult)

    def test_output_size_larger_by_2_bleed(self):
        """Output must be larger by 2·bleed_px in each dimension."""
        img = _solid_image(60, 40)
        bleed_mm = 3.0
        dpi = DEFAULT_DPI
        result = add_bleed(img, bleed_mm=bleed_mm, dpi=dpi)
        bleed_px = mm_to_px(bleed_mm, dpi)
        out_w, out_h = result.image.size
        assert out_w == 60 + 2 * bleed_px
        assert out_h == 40 + 2 * bleed_px

    def test_bleed_width_matches_requested(self):
        """
        Bleed oracle: the actual bleed width should match the requested mm
        value within 1 pixel rounding (px_to_mm(mm_to_px(x)) ≈ x).
        """
        for bleed_mm in [1.0, 3.0, 5.0, 10.0]:
            img = _solid_image()
            result = add_bleed(img, bleed_mm=bleed_mm, dpi=DEFAULT_DPI)
            bleed_px = mm_to_px(bleed_mm, DEFAULT_DPI)
            actual_mm = px_to_mm(bleed_px, DEFAULT_DPI)
            assert abs(result.bleed_mm - actual_mm) < 1e-9, (
                f"bleed_mm={bleed_mm}: stored {result.bleed_mm} != actual {actual_mm}"
            )

    def test_bleed_px_correct(self):
        img = _solid_image(50, 50)
        bleed_mm = 5.0
        result = add_bleed(img, bleed_mm=bleed_mm, dpi=DEFAULT_DPI)
        expected_px = mm_to_px(bleed_mm, DEFAULT_DPI)
        assert result.bleed_px == expected_px

    def test_content_box_correct(self):
        img = _solid_image(60, 40)
        bleed_mm = 3.0
        result = add_bleed(img, bleed_mm=bleed_mm, dpi=DEFAULT_DPI)
        bpx = mm_to_px(bleed_mm, DEFAULT_DPI)
        left, top, right, bottom = result.content_box
        assert left == bpx
        assert top == bpx
        assert right == 60 + bpx
        assert bottom == 40 + bpx

    def test_content_unchanged(self):
        """The content region inside the bleed must be unchanged."""
        arr = np.random.randint(0, 256, (40, 60, 4), dtype=np.uint8)
        img = Image.fromarray(arr, mode="RGBA")
        result = add_bleed(img, bleed_mm=3.0, dpi=DEFAULT_DPI)
        bpx = result.bleed_px
        out_arr = np.array(result.image)
        content_region = out_arr[bpx:bpx + 40, bpx:bpx + 60, :]
        np.testing.assert_array_equal(content_region, arr)

    def test_zero_bleed_is_identity(self):
        """Zero bleed should produce an image of the same size."""
        img = _solid_image(50, 30)
        result = add_bleed(img, bleed_mm=0.0, dpi=DEFAULT_DPI)
        assert result.image.size == (50, 30)
        assert result.bleed_px == 0

    def test_negative_bleed_raises(self):
        with pytest.raises(ValueError):
            add_bleed(_solid_image(), bleed_mm=-1.0)


# ---------------------------------------------------------------------------
# add_registration_marks
# ---------------------------------------------------------------------------

class TestAddRegistrationMarks:

    def test_returns_reg_mark_result(self):
        img = _solid_image(100, 80)
        result = add_registration_marks(img, dpi=DEFAULT_DPI)
        assert isinstance(result, RegMarkResult)

    def test_four_marks_present(self):
        """Exactly 4 registration marks (one per corner)."""
        img = _solid_image(120, 100)
        result = add_registration_marks(img, dpi=DEFAULT_DPI)
        assert len(result.mark_positions) == 4

    def test_marks_at_corners(self):
        """Marks should be near the 4 corners of the image."""
        w, h = 200, 160
        img = _solid_image(w, h)
        result = add_registration_marks(img, dpi=DEFAULT_DPI)
        positions = result.mark_positions

        # Sort by (y, x) to get consistent ordering
        xs = [p[0] for p in positions]
        ys = [p[1] for p in positions]

        # Two marks should be near the left edge, two near the right
        assert min(xs) < w // 4, "Expected marks near left edge"
        assert max(xs) > 3 * w // 4, "Expected marks near right edge"
        # Two marks should be near the top edge, two near the bottom
        assert min(ys) < h // 4, "Expected marks near top edge"
        assert max(ys) > 3 * h // 4, "Expected marks near bottom edge"

    def test_output_same_size(self):
        """Marks are drawn in-place; image size must not change."""
        img = _solid_image(100, 80)
        result = add_registration_marks(img, dpi=DEFAULT_DPI)
        assert result.image.size == (100, 80)

    def test_marks_modify_image(self):
        """Registration marks should change some pixels (all-white image)."""
        img = Image.new("RGBA", (200, 160), (255, 255, 255, 255))
        result = add_registration_marks(img, dpi=DEFAULT_DPI)
        orig_arr = np.array(img)
        new_arr = np.array(result.image)
        assert not np.array_equal(orig_arr, new_arr), (
            "Registration marks did not change any pixel — marks may be absent"
        )

    def test_invalid_n_marks(self):
        with pytest.raises(ValueError):
            add_registration_marks(_solid_image(), n_marks=3)


# ---------------------------------------------------------------------------
# render_panel_png (full pipeline)
# ---------------------------------------------------------------------------

class TestRenderPanelPng:

    def test_returns_subli_result(self):
        art = _solid_image()
        result = render_panel_png(
            radius_mm=40.0,
            height_mm=80.0,
            artwork=art,
            bleed_mm=3.0,
            dpi=72,
        )
        assert isinstance(result, SubliResult)

    def test_area_ratio_within_1pct(self):
        """
        Full-pipeline area-preservation oracle.

        The cylinder lateral area and the flat panel area must agree to 1%.
        """
        r, h = 50.0, 100.0
        art = _solid_image()
        result = render_panel_png(radius_mm=r, height_mm=h, artwork=art, dpi=72)
        assert abs(result.area_ratio - 1.0) < 0.01, (
            f"Area ratio {result.area_ratio:.6f} not within 1% of 1.0"
        )

    def test_bleed_present(self):
        """Final image must be larger than projected image (bleed was added)."""
        art = _solid_image(40, 30)
        result = render_panel_png(
            radius_mm=30.0,
            height_mm=60.0,
            artwork=art,
            bleed_mm=3.0,
            dpi=72,
        )
        proj_w, proj_h = result.projected.size
        final_w, final_h = result.final.image.size
        assert final_w > proj_w
        assert final_h > proj_h

    def test_four_registration_marks(self):
        """Final output should have 4 registration marks."""
        art = _solid_image()
        result = render_panel_png(
            radius_mm=30.0, height_mm=60.0, artwork=art, bleed_mm=3.0, dpi=72
        )
        assert len(result.final.mark_positions) == 4

    def test_dpi_stored(self):
        art = _solid_image()
        result = render_panel_png(radius_mm=25.0, height_mm=50.0, artwork=art, dpi=96)
        assert result.dpi == 96

    def test_bleed_mm_stored(self):
        art = _solid_image()
        result = render_panel_png(
            radius_mm=25.0, height_mm=50.0, artwork=art, bleed_mm=5.0, dpi=72
        )
        expected_bleed_mm = px_to_mm(mm_to_px(5.0, 72), 72)
        assert abs(result.bleed_mm - expected_bleed_mm) < 1e-9

    def test_png_round_trip_full_pipeline(self):
        """
        Save the print-ready final image as PNG, reload, compare.

        PNG is lossless — the round-trip must produce identical pixel data.
        """
        art = _gradient_image(48, 32)
        result = render_panel_png(
            radius_mm=30.0,
            height_mm=60.0,
            artwork=art,
            bleed_mm=3.0,
            dpi=72,
        )
        final_img = result.final.image

        buf = io.BytesIO()
        final_img.save(buf, format="PNG")
        buf.seek(0)
        reloaded = Image.open(buf)
        reloaded.load()

        np.testing.assert_array_equal(
            np.array(final_img),
            np.array(reloaded),
        )


# ---------------------------------------------------------------------------
# mm_to_px / px_to_mm helpers
# ---------------------------------------------------------------------------

class TestHelpers:

    def test_mm_to_px_round_trip(self):
        """mm → px → mm should be within 1 pixel of rounding error."""
        dpi = DEFAULT_DPI
        for mm in [1.0, 3.0, 5.0, 10.0, 25.4]:
            px = mm_to_px(mm, dpi)
            back = px_to_mm(px, dpi)
            # Should round-trip within 1 pixel's worth of mm
            assert abs(back - mm) <= 25.4 / dpi + 1e-9, (
                f"mm={mm}: round-trip gave {back}"
            )

    def test_mm_to_px_at_known_dpi(self):
        """At 25.4 dpi, 1 mm = 1 px exactly."""
        assert mm_to_px(1.0, dpi=25.4) == 1
        assert mm_to_px(10.0, dpi=25.4) == 10

    def test_mm_to_px_min_1(self):
        """mm_to_px should never return 0."""
        assert mm_to_px(0.001, dpi=1.0) >= 1
