"""
Tests for kerf_textiles.screen_print — spot-colour separation pipeline.

DoD oracles
-----------
1. separate_spot_colours extracts the correct number of distinct colours.
2. Each separation mask covers exactly the pixels of that colour.
3. add_bleed (imported from sublimation) works on separation masks.
4. Registration marks appear in each layer.
5. render_separations_pdf produces valid PDF bytes (starts with %PDF).
6. render_separations produces one output per input colour.
"""

from __future__ import annotations

import io

import numpy as np
import pytest

try:
    from PIL import Image
except ImportError:
    pytest.skip("Pillow not available", allow_module_level=True)

from kerf_textiles.screen_print import (
    separate_spot_colours,
    render_separations,
    render_separations_pdf,
    SpotColour,
    SeparationResult,
    PrintReadySeparation,
    ScreenPrintResult,
)
from kerf_textiles.sublimation import mm_to_px, DEFAULT_DPI


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _two_colour_image(w: int = 60, h: int = 40) -> Image.Image:
    """
    RGBA image with exactly 2 spot colours:
    - Left half: red   (255, 0, 0, 255)
    - Right half: blue (0, 0, 255, 255)
    """
    arr = np.zeros((h, w, 4), dtype=np.uint8)
    arr[:, :w // 2] = [255, 0, 0, 255]
    arr[:, w // 2:] = [0, 0, 255, 255]
    return Image.fromarray(arr, mode="RGBA")


def _three_colour_image() -> Image.Image:
    """RGBA image with 3 spot colours: red / green / blue bands."""
    w, h = 60, 60
    arr = np.zeros((h, w, 4), dtype=np.uint8)
    arr[:20, :] = [255, 0, 0, 255]    # red band
    arr[20:40, :] = [0, 255, 0, 255]  # green band
    arr[40:, :] = [0, 0, 255, 255]    # blue band
    return Image.fromarray(arr, mode="RGBA")


def _single_colour_image() -> Image.Image:
    return Image.new("RGBA", (40, 30), (0, 128, 255, 255))


def _transparent_image() -> Image.Image:
    """All-transparent image → 0 spot colours."""
    return Image.new("RGBA", (40, 30), (0, 0, 0, 0))


# ---------------------------------------------------------------------------
# separate_spot_colours
# ---------------------------------------------------------------------------

class TestSeparateSpotColours:

    def test_two_colours_detected(self):
        img = _two_colour_image()
        result = separate_spot_colours(img)
        assert result.n_colours == 2

    def test_three_colours_detected(self):
        result = separate_spot_colours(_three_colour_image())
        assert result.n_colours == 3

    def test_single_colour(self):
        result = separate_spot_colours(_single_colour_image())
        assert result.n_colours == 1

    def test_transparent_image(self):
        result = separate_spot_colours(_transparent_image())
        assert result.n_colours == 0

    def test_returns_separation_result(self):
        result = separate_spot_colours(_two_colour_image())
        assert isinstance(result, SeparationResult)

    def test_mask_pixel_counts(self):
        """
        Pixel count for each colour should match the actual pixel count
        in the source image.
        """
        w, h = 60, 40
        img = _two_colour_image(w=w, h=h)
        result = separate_spot_colours(img)

        # Each half has w//2 * h pixels
        expected = (w // 2) * h
        for spot in result.colours:
            assert spot.pixel_count == expected, (
                f"Colour {spot.colour_rgba}: expected {expected} pixels, got {spot.pixel_count}"
            )

    def test_masks_are_correct_size(self):
        img = _two_colour_image(w=60, h=40)
        result = separate_spot_colours(img)
        for spot in result.colours:
            assert spot.mask.size == (60, 40)

    def test_masks_are_mode_L(self):
        """Masks should be 8-bit greyscale (L mode)."""
        result = separate_spot_colours(_two_colour_image())
        for spot in result.colours:
            assert spot.mask.mode == "L"

    def test_masks_are_binary(self):
        """Mask values should be only 0 or 255."""
        result = separate_spot_colours(_two_colour_image())
        for spot in result.colours:
            arr = np.array(spot.mask)
            unique_vals = np.unique(arr)
            assert set(unique_vals.tolist()).issubset({0, 255}), (
                f"Mask for {spot.colour_rgba} has non-binary values: {unique_vals}"
            )

    def test_mask_covers_correct_pixels(self):
        """
        For a 2-colour image, the red mask should be True on the left half
        and False on the right half.
        """
        w, h = 60, 40
        img = _two_colour_image(w=w, h=h)
        result = separate_spot_colours(img)

        # Find red spot
        red_spot = next(
            s for s in result.colours if s.colour_rgba[0] == 255 and s.colour_rgba[2] == 0
        )
        arr = np.array(red_spot.mask)

        # Left half: all 255
        assert np.all(arr[:, : w // 2] == 255), "Red mask should be 255 on left half"
        # Right half: all 0
        assert np.all(arr[:, w // 2 :] == 0), "Red mask should be 0 on right half"

    def test_masks_are_disjoint(self):
        """
        Masks from different colours must not overlap (each pixel belongs to
        at most one colour).
        """
        result = separate_spot_colours(_two_colour_image())
        masks = [np.array(s.mask) for s in result.colours]
        combined = np.zeros_like(masks[0], dtype=np.int32)
        for m in masks:
            combined += (m == 255).astype(np.int32)
        # Every non-zero pixel should appear in exactly one mask
        assert np.all(combined <= 1), "Masks overlap — pixels belong to multiple colours"

    def test_masks_cover_all_opaque_pixels(self):
        """
        Union of all masks should cover all opaque (alpha >= 128) pixels.
        """
        img = _two_colour_image()
        arr = np.array(img.convert("RGBA"))
        opaque = arr[:, :, 3] >= 128

        result = separate_spot_colours(img)
        union = np.zeros(opaque.shape, dtype=bool)
        for s in result.colours:
            union |= (np.array(s.mask) == 255)

        np.testing.assert_array_equal(union, opaque)

    def test_name_format(self):
        result = separate_spot_colours(_single_colour_image())
        assert len(result.colours) == 1
        name = result.colours[0].name
        assert name.startswith("spot_")

    def test_max_colours_exceeded(self):
        """Should raise ValueError if the palette is too large."""
        # Build an image with many colours (gradient)
        arr = np.arange(256 * 4, dtype=np.uint8).reshape(4, 64, 4)
        arr[:, :, 3] = 255
        img = Image.fromarray(arr[:1, :, :], mode="RGBA")  # 1 row, 64 unique colours
        with pytest.raises(ValueError, match="max_colours"):
            separate_spot_colours(img, max_colours=4)

    def test_total_pixels(self):
        w, h = 60, 40
        result = separate_spot_colours(_two_colour_image(w=w, h=h))
        assert result.total_pixels == w * h
        assert result.width_px == w
        assert result.height_px == h


# ---------------------------------------------------------------------------
# render_separations
# ---------------------------------------------------------------------------

class TestRenderSeparations:

    def test_returns_screen_print_result(self):
        result = render_separations(_two_colour_image(), dpi=72)
        assert isinstance(result, ScreenPrintResult)

    def test_n_separations_matches_colours(self):
        result = render_separations(_two_colour_image(), dpi=72)
        assert result.n_colours == 2
        assert len(result.separations) == 2

    def test_three_colour_separations(self):
        result = render_separations(_three_colour_image(), dpi=72)
        assert result.n_colours == 3

    def test_each_separation_has_registration_marks(self):
        result = render_separations(_two_colour_image(), dpi=72)
        for sep in result.separations:
            assert isinstance(sep, PrintReadySeparation)
            assert len(sep.final.mark_positions) == 4

    def test_bleed_applied(self):
        """Final image should be larger than the source (bleed was added)."""
        img = _two_colour_image(w=60, h=40)
        result = render_separations(img, bleed_mm=3.0, dpi=DEFAULT_DPI)
        bleed_px = mm_to_px(3.0, DEFAULT_DPI)
        for sep in result.separations:
            fin_w, fin_h = sep.final.image.size
            # Final image = content + 2*bleed in each dimension
            assert fin_w == 60 + 2 * bleed_px, (
                f"Expected width {60 + 2 * bleed_px}, got {fin_w}"
            )
            assert fin_h == 40 + 2 * bleed_px, (
                f"Expected height {40 + 2 * bleed_px}, got {fin_h}"
            )

    def test_bleed_mm_stored(self):
        result = render_separations(_two_colour_image(), bleed_mm=5.0, dpi=72)
        # bleed_mm stored should be consistent with the requested value
        for sep in result.separations:
            assert sep.bleed_mm > 0.0

    def test_separation_images_are_rgba(self):
        result = render_separations(_two_colour_image(), dpi=72)
        for sep in result.separations:
            assert sep.final.image.mode == "RGBA"

    def test_single_colour_pipeline(self):
        result = render_separations(_single_colour_image(), dpi=72)
        assert result.n_colours == 1
        assert len(result.separations) == 1
        assert len(result.separations[0].final.mark_positions) == 4


# ---------------------------------------------------------------------------
# render_separations_pdf
# ---------------------------------------------------------------------------

class TestRenderSeparationsPdf:

    def test_returns_bytes(self):
        screen_result = render_separations(_two_colour_image(), dpi=72)
        pdf_bytes = render_separations_pdf(screen_result)
        assert isinstance(pdf_bytes, bytes)

    def test_starts_with_pdf_header(self):
        screen_result = render_separations(_two_colour_image(), dpi=72)
        pdf_bytes = render_separations_pdf(screen_result)
        assert pdf_bytes.startswith(b"%PDF-"), (
            f"PDF must start with %PDF-, got: {pdf_bytes[:8]!r}"
        )

    def test_ends_with_eof(self):
        screen_result = render_separations(_two_colour_image(), dpi=72)
        pdf_bytes = render_separations_pdf(screen_result)
        assert b"%%EOF" in pdf_bytes

    def test_three_colour_pdf(self):
        """PDF should be produced for a 3-colour artwork."""
        screen_result = render_separations(_three_colour_image(), dpi=72)
        pdf_bytes = render_separations_pdf(screen_result)
        assert len(pdf_bytes) > 100
        assert pdf_bytes.startswith(b"%PDF-")

    def test_pdf_contains_xref(self):
        screen_result = render_separations(_two_colour_image(), dpi=72)
        pdf_bytes = render_separations_pdf(screen_result)
        assert b"xref" in pdf_bytes

    def test_empty_separations_raises(self):
        # Build a ScreenPrintResult with no separations
        empty = ScreenPrintResult(
            separations=[], n_colours=0, dpi=72, bleed_mm=0.0
        )
        with pytest.raises(ValueError):
            render_separations_pdf(empty)

    def test_pdf_non_empty(self):
        screen_result = render_separations(_single_colour_image(), dpi=72)
        pdf_bytes = render_separations_pdf(screen_result)
        assert len(pdf_bytes) > 200, "PDF seems too small to contain image data"

    def test_pdf_custom_page_size(self):
        """Should accept explicit page dimensions."""
        screen_result = render_separations(_two_colour_image(), dpi=72)
        pdf_bytes = render_separations_pdf(
            screen_result,
            page_width_mm=210.0,
            page_height_mm=297.0,
        )
        assert pdf_bytes.startswith(b"%PDF-")
        # A4 dimensions in points appear in the PDF
        assert b"595" in pdf_bytes or b"210" in pdf_bytes or b"841" in pdf_bytes
