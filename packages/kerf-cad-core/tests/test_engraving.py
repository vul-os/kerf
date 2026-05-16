"""
Tests for kerf_cad_core.jewelry.engraving

Pure-Python hermetic tests (no DB, no OCC, no network):
  - Stroke font: glyph advance widths, text_width_em, kerning contribution
  - render_text_outlines: returns polylines, correct total width, min_stroke_width
  - total_stroke_length: segment accumulation
  - compute_text_on_curve: valid spec, validation errors, diagnostics
  - compute_text_on_band_inner: width/circumference maths, space warning
  - compute_signet_seal: spec shape, border volume, mode choices, bad inputs
  - compute_monogram_compose: 2-initial / 3-initial bounding boxes, styles
  - LLM tool specs: names and required fields
  - LLM tool runners: success paths, missing required fields, bad file_id,
    validation errors
  - Diagnostics: tool_warning fires below threshold, silent above threshold
  - Node op/feature keys in returned spec dicts
"""

from __future__ import annotations

import asyncio
import json
import math
import uuid

import pytest

from kerf_cad_core.jewelry.engraving import (
    # constants
    _OP,
    _DEFAULT_MIN_TOOL_DIAMETER_MM,
    _DEFAULT_STROKE_WIDTH_FRAC,
    _VALID_MONOGRAM_STYLES,
    _VALID_ENGRAVING_MODES,
    _VALID_BORDER_SHAPES,
    _VALID_TEXT_ALIGNMENTS,
    # font helpers
    get_glyph,
    glyph_advance,
    text_width_em,
    render_text_outlines,
    total_stroke_length,
    _monogram_bounding_box,
    # compute functions
    compute_text_on_curve,
    compute_text_on_band_inner,
    compute_signet_seal,
    compute_monogram_compose,
    # tool specs
    jewelry_text_on_curve_spec,
    jewelry_text_on_band_inner_spec,
    jewelry_signet_seal_spec,
    jewelry_monogram_compose_spec,
    # runners
    run_jewelry_text_on_curve,
    run_jewelry_text_on_band_inner,
    run_jewelry_signet_seal,
    run_jewelry_monogram_compose,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_TOLERANCE = 1e-6


def make_ctx(initial_content: str = "", kind: str = "feature"):
    store = {
        "content": initial_content or json.dumps({"version": 1, "features": []}),
        "kind": kind,
    }
    project_id = uuid.uuid4()
    file_id = uuid.uuid4()

    class FakePool:
        def fetchone(self, query, *args):
            if store["kind"] == "NOT_FOUND":
                return None
            return (store["content"], store["kind"])

        def execute(self, query, *args):
            if args:
                store["content"] = args[0]

    try:
        from kerf_core.utils.context import ProjectCtx  # type: ignore[import]
    except ImportError:
        class ProjectCtx:  # type: ignore[no-redef]
            def __init__(self, **kwargs):
                for k, v in kwargs.items():
                    setattr(self, k, v)

    ctx = ProjectCtx(
        pool=FakePool(),
        storage=None,
        project_id=project_id,
        user_id=uuid.uuid4(),
        role="owner",
        http_client=None,
    )
    return ctx, store, file_id


def run_sync(coro):
    loop = asyncio.new_event_loop()
    try:
        return json.loads(loop.run_until_complete(coro))
    finally:
        loop.close()


def call_tool(runner, ctx, file_id_or_none, **kwargs):
    a = {}
    if file_id_or_none is not None:
        a["file_id"] = str(file_id_or_none)
    a.update(kwargs)
    return run_sync(runner(ctx, json.dumps(a).encode()))


# ---------------------------------------------------------------------------
# 1. Stroke font / glyph data
# ---------------------------------------------------------------------------

class TestGlyphFont:
    def test_all_uppercase_letters_present(self):
        import string
        for ch in string.ascii_uppercase:
            g = get_glyph(ch)
            assert "strokes" in g
            assert "advance" in g
            assert g["advance"] > 0, f"glyph {ch!r} has zero advance"

    def test_all_digits_present(self):
        for d in "0123456789":
            g = get_glyph(d)
            assert g["advance"] > 0, f"digit {d!r} has zero advance"

    def test_space_glyph_has_no_strokes(self):
        g = get_glyph(" ")
        assert g["strokes"] == []
        assert g["advance"] > 0

    def test_fallback_for_unknown_char(self):
        g = get_glyph("\x01")
        assert "strokes" in g
        assert g["advance"] > 0

    def test_lowercase_maps_to_uppercase(self):
        for ch in "abcxyz":
            g = get_glyph(ch)
            g_upper = get_glyph(ch.upper())
            assert g == g_upper

    def test_glyph_advance_positive(self):
        for ch in "HELLO WORLD 123":
            assert glyph_advance(ch) > 0, f"zero advance for {ch!r}"

    def test_text_width_em_empty(self):
        assert text_width_em("") == pytest.approx(0.0)

    def test_text_width_em_single_char(self):
        assert text_width_em("A") == pytest.approx(glyph_advance("A"))

    def test_text_width_em_multi_char_no_kerning(self):
        txt = "ABC"
        expected = sum(glyph_advance(c) for c in txt)
        assert text_width_em(txt) == pytest.approx(expected)

    def test_text_width_em_with_kerning(self):
        txt = "AB"
        k = 0.1
        # 2 chars → 1 kerning gap
        expected = glyph_advance("A") + glyph_advance("B") + k
        assert text_width_em(txt, kerning_em=k) == pytest.approx(expected)

    def test_kerning_adds_n_minus_1_gaps(self):
        txt = "ABCDE"
        k = 0.05
        base = sum(glyph_advance(c) for c in txt)
        expected = base + k * (len(txt) - 1)
        assert text_width_em(txt, kerning_em=k) == pytest.approx(expected)


# ---------------------------------------------------------------------------
# 2. render_text_outlines
# ---------------------------------------------------------------------------

class TestRenderTextOutlines:
    def test_returns_three_tuple(self):
        pls, w, sw = render_text_outlines("A", 4.0)
        assert isinstance(pls, list)
        assert isinstance(w, float)
        assert isinstance(sw, float)

    def test_empty_string_returns_zero_width(self):
        _, w, _ = render_text_outlines("", 3.0)
        assert w == pytest.approx(0.0)

    def test_width_scales_with_cap_height(self):
        _, w1, _ = render_text_outlines("AB", 2.0)
        _, w2, _ = render_text_outlines("AB", 4.0)
        assert w2 == pytest.approx(w1 * 2.0, rel=1e-4)

    def test_min_stroke_width_proportional_to_cap_height(self):
        cap = 3.0
        _, _, sw = render_text_outlines("A", cap)
        assert sw == pytest.approx(_DEFAULT_STROKE_WIDTH_FRAC * cap, rel=1e-6)

    def test_width_matches_text_width_em_times_scale(self):
        txt = "HELLO"
        cap = 5.0
        expected_em = text_width_em(txt, kerning_em=0.0)
        expected_mm = expected_em * cap
        _, w, _ = render_text_outlines(txt, cap, kerning_mm=0.0)
        assert w == pytest.approx(expected_mm, rel=1e-4)

    def test_kerning_mm_adds_correct_gap(self):
        cap = 4.0
        k = 0.5
        txt = "AB"
        _, w_no_k, _ = render_text_outlines(txt, cap, kerning_mm=0.0)
        _, w_k, _ = render_text_outlines(txt, cap, kerning_mm=k)
        # 2 chars → 1 gap of k mm
        assert w_k == pytest.approx(w_no_k + k, rel=1e-4)

    def test_all_polylines_have_at_least_2_points(self):
        pls, _, _ = render_text_outlines("ABCDEFGHIJKLMNOPQRSTUVWXYZ", 4.0)
        for pl in pls:
            assert len(pl) >= 2, "polyline with fewer than 2 points"

    def test_polyline_coords_are_floats(self):
        pls, _, _ = render_text_outlines("AB", 3.0)
        for pl in pls:
            for x, y in pl:
                assert isinstance(x, float)
                assert isinstance(y, float)


# ---------------------------------------------------------------------------
# 3. total_stroke_length
# ---------------------------------------------------------------------------

class TestTotalStrokeLength:
    def test_single_segment(self):
        pls = [[(0.0, 0.0), (3.0, 4.0)]]
        assert total_stroke_length(pls) == pytest.approx(5.0)

    def test_two_polylines(self):
        pls = [[(0.0, 0.0), (1.0, 0.0)], [(0.0, 0.0), (0.0, 2.0)]]
        assert total_stroke_length(pls) == pytest.approx(3.0)

    def test_empty(self):
        assert total_stroke_length([]) == pytest.approx(0.0)

    def test_arc_length_on_circle_within_epsilon(self):
        """Rendered circle arc-length should be close to 2πr for a fine polygon."""
        r = 1.0
        from kerf_cad_core.jewelry.engraving import _circle_pts
        pts = _circle_pts(0.0, 0.0, r, 64)
        length = total_stroke_length([pts])
        expected = 2 * math.pi * r
        # 64-segment polygon: error < 0.1%
        assert abs(length - expected) / expected < 0.001


# ---------------------------------------------------------------------------
# 4. compute_text_on_curve
# ---------------------------------------------------------------------------

class TestTextOnCurve:
    _REF = "curve-001"

    def test_basic_spec_shape(self):
        s = compute_text_on_curve(self._REF, "HELLO", cap_height_mm=3.0)
        assert s["op"] == _OP
        assert s["feature"] == "text_on_curve"
        assert s["target_ref"] == self._REF
        assert "engraving_hints" in s
        assert "outline_paths" in s
        assert "diagnostics" in s

    def test_total_text_width_matches_render(self):
        cap = 4.0
        txt = "ABC"
        s = compute_text_on_curve(self._REF, txt, cap_height_mm=cap)
        _, expected_w, _ = render_text_outlines(txt, cap, 0.0)
        assert s["engraving_hints"]["total_text_width_mm"] == pytest.approx(expected_w, rel=1e-4)

    def test_kerning_reflected_in_width(self):
        cap = 3.0
        k = 0.2
        txt = "AB"
        s_no_k = compute_text_on_curve(self._REF, txt, cap_height_mm=cap, kerning_mm=0.0)
        s_k = compute_text_on_curve(self._REF, txt, cap_height_mm=cap, kerning_mm=k)
        assert s_k["engraving_hints"]["total_text_width_mm"] > s_no_k["engraving_hints"]["total_text_width_mm"]

    def test_missing_target_ref_raises(self):
        with pytest.raises(ValueError, match="target_ref is required"):
            compute_text_on_curve("", "HELLO", cap_height_mm=3.0)

    def test_empty_text_raises(self):
        with pytest.raises(ValueError, match="text is required"):
            compute_text_on_curve(self._REF, "  ", cap_height_mm=3.0)

    def test_negative_cap_height_raises(self):
        with pytest.raises(ValueError, match="cap_height_mm must be > 0"):
            compute_text_on_curve(self._REF, "A", cap_height_mm=-1.0)

    def test_zero_cap_height_raises(self):
        with pytest.raises(ValueError, match="cap_height_mm must be > 0"):
            compute_text_on_curve(self._REF, "A", cap_height_mm=0.0)

    def test_invalid_start_t_raises(self):
        with pytest.raises(ValueError, match="start_t must be in"):
            compute_text_on_curve(self._REF, "A", cap_height_mm=3.0, start_t=1.5)

    def test_invalid_alignment_raises(self):
        with pytest.raises(ValueError, match="alignment"):
            compute_text_on_curve(self._REF, "A", cap_height_mm=3.0, alignment="justified")

    def test_invalid_mode_raises(self):
        with pytest.raises(ValueError, match="mode"):
            compute_text_on_curve(self._REF, "A", cap_height_mm=3.0, mode="hollow")

    def test_diagnostics_tool_warning_fires_below_threshold(self):
        # Very small cap_height → stroke smaller than default threshold
        s = compute_text_on_curve(self._REF, "A", cap_height_mm=0.5,
                                  min_tool_diameter_mm=0.3)
        assert s["diagnostics"]["tool_warning"] != ""

    def test_diagnostics_tool_warning_silent_above_threshold(self):
        # Large cap_height → stroke well above default threshold
        s = compute_text_on_curve(self._REF, "A", cap_height_mm=10.0,
                                  min_tool_diameter_mm=0.3)
        assert s["diagnostics"]["tool_warning"] == ""

    def test_recessed_volume_positive(self):
        s = compute_text_on_curve(self._REF, "ABC", cap_height_mm=4.0, depth_mm=0.3)
        assert s["diagnostics"]["recessed_volume_mm3"] > 0

    def test_mode_stored_in_hints(self):
        s = compute_text_on_curve(self._REF, "A", cap_height_mm=3.0, mode="raised")
        assert s["engraving_hints"]["mode"] == "raised"

    @pytest.mark.parametrize("alignment", sorted(_VALID_TEXT_ALIGNMENTS))
    def test_all_alignments_accepted(self, alignment):
        s = compute_text_on_curve(self._REF, "A", cap_height_mm=3.0, alignment=alignment)
        assert s["engraving_hints"]["alignment"] == alignment


# ---------------------------------------------------------------------------
# 5. compute_text_on_band_inner
# ---------------------------------------------------------------------------

class TestTextOnBandInner:
    _REF = "band-001"

    def test_basic_spec_shape(self):
        s = compute_text_on_band_inner(self._REF, "JAN 1985", band_inner_diameter_mm=17.0,
                                       cap_height_mm=2.0)
        assert s["op"] == _OP
        assert s["feature"] == "text_on_band_inner"
        assert "engraving_hints" in s
        hints = s["engraving_hints"]
        assert "inner_circumference_mm" in hints
        assert "text_arc_deg" in hints

    def test_inner_circumference_formula(self):
        d = 18.0
        s = compute_text_on_band_inner(self._REF, "TEST", band_inner_diameter_mm=d,
                                       cap_height_mm=2.0)
        expected = math.pi * d
        assert s["engraving_hints"]["inner_circumference_mm"] == pytest.approx(expected, rel=1e-5)

    def test_text_arc_deg_proportional_to_text_width(self):
        d = 18.0
        circ = math.pi * d
        cap = 2.0
        txt = "AB"
        s = compute_text_on_band_inner(self._REF, txt, band_inner_diameter_mm=d,
                                       cap_height_mm=cap)
        w = s["engraving_hints"]["total_text_width_mm"]
        expected_arc = (w / circ) * 360.0
        assert s["engraving_hints"]["text_arc_deg"] == pytest.approx(expected_arc, rel=1e-4)

    def test_space_warning_fires_when_text_too_wide(self):
        # Force text wider than 95% of circumference by using a very large cap_height
        s = compute_text_on_band_inner(self._REF, "ABCDEFGHIJKLM",
                                       band_inner_diameter_mm=10.0, cap_height_mm=8.0)
        assert s["diagnostics"]["tool_warning"] != ""

    def test_angular_offset_stored(self):
        s = compute_text_on_band_inner(self._REF, "AB", band_inner_diameter_mm=17.0,
                                       cap_height_mm=2.0, angular_offset_deg=45.0)
        assert s["engraving_hints"]["angular_offset_deg"] == pytest.approx(45.0)

    def test_angular_offset_normalised(self):
        s = compute_text_on_band_inner(self._REF, "A", band_inner_diameter_mm=17.0,
                                       cap_height_mm=2.0, angular_offset_deg=370.0)
        assert 0.0 <= s["engraving_hints"]["angular_offset_deg"] < 360.0

    def test_missing_target_ref_raises(self):
        with pytest.raises(ValueError, match="target_ref is required"):
            compute_text_on_band_inner("", "TEXT", band_inner_diameter_mm=17.0,
                                       cap_height_mm=2.0)

    def test_empty_text_raises(self):
        with pytest.raises(ValueError, match="text is required"):
            compute_text_on_band_inner(self._REF, "", band_inner_diameter_mm=17.0,
                                       cap_height_mm=2.0)

    def test_zero_diameter_raises(self):
        with pytest.raises(ValueError, match="band_inner_diameter_mm must be > 0"):
            compute_text_on_band_inner(self._REF, "A", band_inner_diameter_mm=0.0,
                                       cap_height_mm=2.0)

    def test_negative_depth_raises(self):
        with pytest.raises(ValueError, match="depth_mm must be > 0"):
            compute_text_on_band_inner(self._REF, "A", band_inner_diameter_mm=17.0,
                                       cap_height_mm=2.0, depth_mm=-0.1)

    def test_recessed_volume_positive(self):
        s = compute_text_on_band_inner(self._REF, "JOHN", band_inner_diameter_mm=17.0,
                                       cap_height_mm=2.0, depth_mm=0.15)
        assert s["diagnostics"]["recessed_volume_mm3"] > 0

    def test_mode_always_recessed(self):
        s = compute_text_on_band_inner(self._REF, "A", band_inner_diameter_mm=17.0,
                                       cap_height_mm=2.0)
        assert s["engraving_hints"]["mode"] == "recessed"


# ---------------------------------------------------------------------------
# 6. compute_signet_seal
# ---------------------------------------------------------------------------

class TestSignetSeal:
    _REF = "face-001"

    def test_basic_spec_shape(self):
        s = compute_signet_seal(self._REF, "JRS", cap_height_mm=6.0)
        assert s["op"] == _OP
        assert s["feature"] == "signet_seal"
        assert "engraving_hints" in s
        assert "outline_paths" in s
        assert "diagnostics" in s

    def test_mode_recessed_default(self):
        s = compute_signet_seal(self._REF, "A", cap_height_mm=5.0)
        assert s["engraving_hints"]["mode"] == "recessed"

    def test_mode_raised_stored(self):
        s = compute_signet_seal(self._REF, "A", cap_height_mm=5.0, mode="raised")
        assert s["engraving_hints"]["mode"] == "raised"

    def test_border_shape_stored(self):
        s = compute_signet_seal(self._REF, "A", cap_height_mm=5.0, border_shape="oval")
        assert s["engraving_hints"]["border_shape"] == "oval"

    def test_border_none_by_default(self):
        s = compute_signet_seal(self._REF, "A", cap_height_mm=5.0)
        assert s["engraving_hints"]["border_shape"] == "none"

    @pytest.mark.parametrize("shape", sorted(_VALID_BORDER_SHAPES))
    def test_all_border_shapes_accepted(self, shape):
        s = compute_signet_seal(self._REF, "A", cap_height_mm=5.0, border_shape=shape)
        assert s["engraving_hints"]["border_shape"] == shape

    def test_volume_higher_with_border(self):
        s_no = compute_signet_seal(self._REF, "A", cap_height_mm=5.0, border_shape="none")
        s_yes = compute_signet_seal(self._REF, "A", cap_height_mm=5.0,
                                     border_shape="rectangle", border_width_mm=0.5)
        assert s_yes["diagnostics"]["recessed_volume_mm3"] > s_no["diagnostics"]["recessed_volume_mm3"]

    def test_missing_target_ref_raises(self):
        with pytest.raises(ValueError, match="target_ref is required"):
            compute_signet_seal("", "A", cap_height_mm=5.0)

    def test_empty_text_raises(self):
        with pytest.raises(ValueError, match="text is required"):
            compute_signet_seal(self._REF, "", cap_height_mm=5.0)

    def test_invalid_mode_raises(self):
        with pytest.raises(ValueError, match="mode"):
            compute_signet_seal(self._REF, "A", cap_height_mm=5.0, mode="hollow")

    def test_invalid_border_shape_raises(self):
        with pytest.raises(ValueError, match="border_shape"):
            compute_signet_seal(self._REF, "A", cap_height_mm=5.0, border_shape="triangle")

    def test_negative_border_width_raises(self):
        with pytest.raises(ValueError, match="border_width_mm"):
            compute_signet_seal(self._REF, "A", cap_height_mm=5.0, border_width_mm=-1.0)

    def test_diagnostics_tool_warning_fires(self):
        s = compute_signet_seal(self._REF, "A", cap_height_mm=0.5, min_tool_diameter_mm=0.3)
        assert s["diagnostics"]["tool_warning"] != ""

    def test_total_text_width_positive(self):
        s = compute_signet_seal(self._REF, "SMITH", cap_height_mm=5.0)
        assert s["engraving_hints"]["total_text_width_mm"] > 0

    def test_depth_stored(self):
        s = compute_signet_seal(self._REF, "A", cap_height_mm=5.0, depth_mm=0.5)
        assert s["engraving_hints"]["depth_mm"] == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# 7. compute_monogram_compose
# ---------------------------------------------------------------------------

class TestMonogramCompose:
    def test_two_initial_spec_shape(self):
        s = compute_monogram_compose("AB", cap_height_mm=6.0)
        assert s["op"] == _OP
        assert s["feature"] == "monogram_compose"
        assert "monogram_hints" in s
        assert "bounding_box" in s
        assert "outline_paths" in s
        assert "diagnostics" in s

    def test_three_initial_spec_shape(self):
        s = compute_monogram_compose("JRS", cap_height_mm=8.0)
        assert s["monogram_hints"]["letter_count"] == 3

    def test_two_initial_letter_count(self):
        s = compute_monogram_compose("AB", cap_height_mm=6.0)
        assert s["monogram_hints"]["letter_count"] == 2

    def test_initials_stored_uppercase(self):
        s = compute_monogram_compose("ab", cap_height_mm=6.0)
        assert s["monogram_hints"]["initials"] == "AB"

    def test_bounding_box_keys_present(self):
        s = compute_monogram_compose("JRS", cap_height_mm=6.0)
        bb = s["bounding_box"]
        for key in ("xmin_mm", "ymin_mm", "xmax_mm", "ymax_mm", "width_mm", "height_mm"):
            assert key in bb, f"missing key {key!r} in bounding_box"

    def test_bounding_box_width_positive(self):
        s = compute_monogram_compose("JRS", cap_height_mm=6.0)
        assert s["bounding_box"]["width_mm"] > 0

    def test_bounding_box_height_positive(self):
        s = compute_monogram_compose("AB", cap_height_mm=6.0)
        assert s["bounding_box"]["height_mm"] > 0

    def test_stacked_height_greater_than_width_for_tall_narrow_letters(self):
        # I is narrow; stacked III should be taller than wide
        s = compute_monogram_compose("III", style="stacked", cap_height_mm=9.0)
        bb = s["bounding_box"]
        assert bb["height_mm"] > bb["width_mm"]

    @pytest.mark.parametrize("style", sorted(_VALID_MONOGRAM_STYLES))
    def test_all_styles_accepted(self, style):
        s = compute_monogram_compose("AB", style=style, cap_height_mm=6.0)
        assert s["monogram_hints"]["style"] == style

    def test_encircled_has_more_paths_than_interlocked(self):
        s_int = compute_monogram_compose("AB", style="interlocked", cap_height_mm=6.0)
        s_enc = compute_monogram_compose("AB", style="encircled", cap_height_mm=6.0)
        # encircled adds a circle → more polylines
        assert len(s_enc["outline_paths"]) > len(s_int["outline_paths"])

    def test_single_initial_raises(self):
        with pytest.raises(ValueError, match="2 or 3"):
            compute_monogram_compose("A", cap_height_mm=6.0)

    def test_four_initials_raises(self):
        with pytest.raises(ValueError, match="2 or 3"):
            compute_monogram_compose("ABCD", cap_height_mm=6.0)

    def test_invalid_style_raises(self):
        with pytest.raises(ValueError, match="style"):
            compute_monogram_compose("AB", style="diagonal", cap_height_mm=6.0)

    def test_zero_cap_height_raises(self):
        with pytest.raises(ValueError, match="cap_height_mm"):
            compute_monogram_compose("AB", cap_height_mm=0.0)

    def test_invalid_side_scale_raises(self):
        with pytest.raises(ValueError, match="side_scale"):
            compute_monogram_compose("ABC", side_scale=0.0, cap_height_mm=6.0)

    def test_diagnostics_total_stroke_length_positive(self):
        s = compute_monogram_compose("JRS", cap_height_mm=8.0)
        assert s["diagnostics"]["total_stroke_length_mm"] > 0

    def test_tool_warning_fires_below_threshold(self):
        s = compute_monogram_compose("AB", cap_height_mm=0.5, min_tool_diameter_mm=0.3)
        assert s["diagnostics"]["tool_warning"] != ""


# ---------------------------------------------------------------------------
# 8. _monogram_bounding_box helper
# ---------------------------------------------------------------------------

class TestBoundingBox:
    def test_empty_returns_zeros(self):
        bb = _monogram_bounding_box([])
        assert bb == (0.0, 0.0, 0.0, 0.0)

    def test_known_points(self):
        pls = [[(1.0, 2.0), (5.0, 3.0)], [(-1.0, 0.0), (3.0, 7.0)]]
        xmin, ymin, xmax, ymax = _monogram_bounding_box(pls)
        assert xmin == pytest.approx(-1.0)
        assert ymin == pytest.approx(0.0)
        assert xmax == pytest.approx(5.0)
        assert ymax == pytest.approx(7.0)


# ---------------------------------------------------------------------------
# 9. Tool spec names and required fields
# ---------------------------------------------------------------------------

class TestToolSpecs:
    def test_text_on_curve_name(self):
        assert jewelry_text_on_curve_spec.name == "jewelry_text_on_curve"

    def test_text_on_band_inner_name(self):
        assert jewelry_text_on_band_inner_spec.name == "jewelry_text_on_band_inner"

    def test_signet_seal_name(self):
        assert jewelry_signet_seal_spec.name == "jewelry_signet_seal"

    def test_monogram_compose_name(self):
        assert jewelry_monogram_compose_spec.name == "jewelry_monogram_compose"

    def test_text_on_curve_required_fields(self):
        req = jewelry_text_on_curve_spec.input_schema["required"]
        for f in ("file_id", "target_ref", "text", "cap_height_mm"):
            assert f in req

    def test_text_on_band_inner_required_fields(self):
        req = jewelry_text_on_band_inner_spec.input_schema["required"]
        for f in ("file_id", "target_ref", "text", "band_inner_diameter_mm", "cap_height_mm"):
            assert f in req

    def test_signet_seal_required_fields(self):
        req = jewelry_signet_seal_spec.input_schema["required"]
        for f in ("file_id", "target_ref", "text", "cap_height_mm"):
            assert f in req

    def test_monogram_compose_required_fields(self):
        req = jewelry_monogram_compose_spec.input_schema["required"]
        for f in ("initials", "cap_height_mm"):
            assert f in req

    def test_mode_enum_covers_valid_modes(self):
        props = jewelry_text_on_curve_spec.input_schema["properties"]
        assert set(props["mode"]["enum"]) == _VALID_ENGRAVING_MODES

    def test_border_shape_enum_covers_valid_shapes(self):
        props = jewelry_signet_seal_spec.input_schema["properties"]
        assert set(props["border_shape"]["enum"]) == _VALID_BORDER_SHAPES

    def test_monogram_style_enum_covers_valid_styles(self):
        props = jewelry_monogram_compose_spec.input_schema["properties"]
        assert set(props["style"]["enum"]) == _VALID_MONOGRAM_STYLES


# ---------------------------------------------------------------------------
# 10. LLM tool runners
# ---------------------------------------------------------------------------

class TestRunTextOnCurve:
    def test_success_returns_ok(self):
        ctx, _, fid = make_ctx()
        r = call_tool(run_jewelry_text_on_curve, ctx, fid,
                      target_ref="c-1", text="HELLO", cap_height_mm=3.0)
        assert "error" not in r, r
        assert r["op"] == _OP
        assert r["feature"] == "text_on_curve"

    def test_missing_file_id_returns_error(self):
        ctx, _, _ = make_ctx()
        r = call_tool(run_jewelry_text_on_curve, ctx, None,
                      target_ref="c-1", text="A", cap_height_mm=3.0)
        assert "error" in r

    def test_bad_file_id_returns_error(self):
        ctx, _, _ = make_ctx()
        r = call_tool(run_jewelry_text_on_curve, ctx, "not-a-uuid",
                      target_ref="c-1", text="A", cap_height_mm=3.0)
        assert "error" in r

    def test_missing_cap_height_returns_error(self):
        ctx, _, fid = make_ctx()
        r = call_tool(run_jewelry_text_on_curve, ctx, fid,
                      target_ref="c-1", text="A")
        assert "error" in r

    def test_validation_error_returns_bad_args(self):
        ctx, _, fid = make_ctx()
        r = call_tool(run_jewelry_text_on_curve, ctx, fid,
                      target_ref="c-1", text="A", cap_height_mm=0.0)
        assert r.get("code") == "BAD_ARGS"

    def test_file_not_found_returns_not_found(self):
        ctx, store, fid = make_ctx()
        store["kind"] = "NOT_FOUND"
        r = call_tool(run_jewelry_text_on_curve, ctx, fid,
                      target_ref="c-1", text="A", cap_height_mm=3.0)
        assert r.get("code") == "NOT_FOUND"

    def test_node_persisted_in_store(self):
        ctx, store, fid = make_ctx()
        call_tool(run_jewelry_text_on_curve, ctx, fid,
                  target_ref="c-1", text="AB", cap_height_mm=3.0)
        doc = json.loads(store["content"])
        feats = doc["features"]
        assert len(feats) == 1
        assert feats[0]["feature"] == "text_on_curve"

    def test_diagnostics_in_response(self):
        ctx, _, fid = make_ctx()
        r = call_tool(run_jewelry_text_on_curve, ctx, fid,
                      target_ref="c-1", text="X", cap_height_mm=5.0)
        assert "diagnostics" in r


class TestRunTextOnBandInner:
    def test_success_returns_ok(self):
        ctx, _, fid = make_ctx()
        r = call_tool(run_jewelry_text_on_band_inner, ctx, fid,
                      target_ref="b-1", text="LOVE",
                      band_inner_diameter_mm=17.0, cap_height_mm=2.0)
        assert "error" not in r, r
        assert r["feature"] == "text_on_band_inner"

    def test_missing_diameter_returns_error(self):
        ctx, _, fid = make_ctx()
        r = call_tool(run_jewelry_text_on_band_inner, ctx, fid,
                      target_ref="b-1", text="A", cap_height_mm=2.0)
        assert "error" in r

    def test_inner_circumference_in_response(self):
        ctx, _, fid = make_ctx()
        r = call_tool(run_jewelry_text_on_band_inner, ctx, fid,
                      target_ref="b-1", text="HI",
                      band_inner_diameter_mm=18.0, cap_height_mm=2.0)
        assert "inner_circumference_mm" in r
        assert r["inner_circumference_mm"] == pytest.approx(math.pi * 18.0, rel=1e-4)


class TestRunSignetSeal:
    def test_success_returns_ok(self):
        ctx, _, fid = make_ctx()
        r = call_tool(run_jewelry_signet_seal, ctx, fid,
                      target_ref="face-1", text="JRS", cap_height_mm=6.0)
        assert "error" not in r, r
        assert r["feature"] == "signet_seal"

    def test_mode_in_response(self):
        ctx, _, fid = make_ctx()
        r = call_tool(run_jewelry_signet_seal, ctx, fid,
                      target_ref="face-1", text="A", cap_height_mm=5.0, mode="raised")
        assert r["mode"] == "raised"

    def test_missing_text_returns_error(self):
        ctx, _, fid = make_ctx()
        r = call_tool(run_jewelry_signet_seal, ctx, fid,
                      target_ref="face-1", cap_height_mm=5.0)
        assert "error" in r

    def test_bad_border_returns_bad_args(self):
        ctx, _, fid = make_ctx()
        r = call_tool(run_jewelry_signet_seal, ctx, fid,
                      target_ref="face-1", text="A", cap_height_mm=5.0,
                      border_shape="diamond")
        assert r.get("code") == "BAD_ARGS"


class TestRunMonogramCompose:
    def test_success_returns_ok(self):
        ctx, _, _ = make_ctx()
        r = call_tool(run_jewelry_monogram_compose, ctx, None,
                      initials="JRS", cap_height_mm=8.0)
        assert "error" not in r, r
        assert r["feature"] == "monogram_compose"

    def test_bounding_box_in_response(self):
        ctx, _, _ = make_ctx()
        r = call_tool(run_jewelry_monogram_compose, ctx, None,
                      initials="AB", cap_height_mm=6.0)
        assert "bounding_box" in r

    def test_missing_initials_returns_error(self):
        ctx, _, _ = make_ctx()
        r = call_tool(run_jewelry_monogram_compose, ctx, None, cap_height_mm=6.0)
        assert "error" in r

    def test_missing_cap_height_returns_error(self):
        ctx, _, _ = make_ctx()
        r = call_tool(run_jewelry_monogram_compose, ctx, None, initials="AB")
        assert "error" in r

    def test_invalid_initials_length_returns_error(self):
        ctx, _, _ = make_ctx()
        r = call_tool(run_jewelry_monogram_compose, ctx, None,
                      initials="ABCD", cap_height_mm=6.0)
        assert "error" in r

    def test_invalid_style_returns_bad_args(self):
        ctx, _, _ = make_ctx()
        r = call_tool(run_jewelry_monogram_compose, ctx, None,
                      initials="AB", cap_height_mm=6.0, style="spiral")
        assert r.get("code") == "BAD_ARGS"

    def test_stacked_style_returns_ok(self):
        ctx, _, _ = make_ctx()
        r = call_tool(run_jewelry_monogram_compose, ctx, None,
                      initials="MR", style="stacked", cap_height_mm=8.0)
        assert r["style"] == "stacked"

    def test_encircled_style_returns_ok(self):
        ctx, _, _ = make_ctx()
        r = call_tool(run_jewelry_monogram_compose, ctx, None,
                      initials="JS", style="encircled", cap_height_mm=7.0)
        assert r["style"] == "encircled"
