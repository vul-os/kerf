"""
Tests for kerf_cad_core.civil.plan_profile_sheet — plan-and-profile sheet generator.

References:
  • ASCE Manual 21 §3.4 — sheet layout standards.
  • AASHTO Green Book (2018) §3 — profile view vertical exaggeration.
  • BLM Manual of Surveying Instructions §6 — stationing conventions.
"""
from __future__ import annotations

import math
import pytest

from kerf_cad_core.civil.plan_profile_sheet import (
    PlanProfileSpec,
    PlanProfileSheet,
    generate_plan_profile_sheet,
    _SHEET_SIZES,
    _PX_PER_INCH,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_alignment(
    n_stations: int = 10,
    sta_start: float = 0.0,
    sta_step: float = 50.0,
    x_step: float = 50.0,
    y_const: float = 0.0,
    elev_start: float = 100.0,
    grade: float = 0.01,
) -> list[tuple[float, float, float, float]]:
    """Generate a straight alignment with uniform grade."""
    pts = []
    for i in range(n_stations):
        sta = sta_start + i * sta_step
        x = i * x_step
        y = y_const
        elev = elev_start + i * sta_step * grade
        pts.append((sta, x, y, elev))
    return pts


def _default_spec(**kwargs) -> PlanProfileSpec:
    defaults = dict(
        alignment_id="TEST_ALIGN",
        station_start=0.0,
        station_end=450.0,
        plan_view_scale=50.0,
        profile_view_scale_h=50.0,
        profile_view_scale_v=10.0,
        sheet_size="ANSI_D",
        grid_interval_ft=50.0,
    )
    defaults.update(kwargs)
    return PlanProfileSpec(**defaults)


# ---------------------------------------------------------------------------
# Basic SVG output tests
# ---------------------------------------------------------------------------

def test_returns_plan_profile_sheet():
    """generate_plan_profile_sheet returns a PlanProfileSheet instance."""
    geom = _make_alignment(10)
    spec = _default_spec()
    result = generate_plan_profile_sheet(geom, spec)
    assert isinstance(result, PlanProfileSheet)


def test_svg_is_nonempty_string():
    geom = _make_alignment(10)
    spec = _default_spec()
    result = generate_plan_profile_sheet(geom, spec)
    assert isinstance(result.svg, str)
    assert len(result.svg) > 100


def test_svg_contains_plan_view_comment():
    """SVG must contain a plan_view section marker."""
    geom = _make_alignment(10)
    spec = _default_spec()
    result = generate_plan_profile_sheet(geom, spec)
    assert "plan_view" in result.svg


def test_svg_contains_profile_view_comment():
    """SVG must contain a profile_view section marker."""
    geom = _make_alignment(10)
    spec = _default_spec()
    result = generate_plan_profile_sheet(geom, spec)
    assert "profile_view" in result.svg


def test_svg_is_valid_xml_root():
    """SVG string must open and close with <svg> tags."""
    geom = _make_alignment(10)
    spec = _default_spec()
    result = generate_plan_profile_sheet(geom, spec)
    assert result.svg.strip().startswith("<svg")
    assert result.svg.strip().endswith("</svg>")


# ---------------------------------------------------------------------------
# Sheet size: ANSI_D → 24×36 inches (landscape)
# ---------------------------------------------------------------------------

def test_ansi_d_sheet_width():
    """ANSI_D landscape: SVG width = 36 inches × 96 px/in = 3456 px."""
    geom = _make_alignment(10)
    spec = _default_spec(sheet_size="ANSI_D")
    result = generate_plan_profile_sheet(geom, spec)
    expected_w = 36 * _PX_PER_INCH
    assert f'width="{expected_w:.0f}"' in result.svg


def test_ansi_d_sheet_height():
    """ANSI_D landscape: SVG height = 24 inches × 96 px/in = 2304 px."""
    geom = _make_alignment(10)
    spec = _default_spec(sheet_size="ANSI_D")
    result = generate_plan_profile_sheet(geom, spec)
    expected_h = 24 * _PX_PER_INCH
    assert f'height="{expected_h:.0f}"' in result.svg


def test_arch_d_same_canvas_size():
    """ARCH_D shares the same physical canvas as ANSI_D (24×36 in)."""
    geom = _make_alignment(10)
    spec_ansi = _default_spec(sheet_size="ANSI_D")
    spec_arch = _default_spec(sheet_size="ARCH_D")
    r_ansi = generate_plan_profile_sheet(geom, spec_ansi)
    r_arch = generate_plan_profile_sheet(geom, spec_arch)
    # Both should have the same width/height SVG attributes
    for attr in ["width=", "height="]:
        # Extract the value after attr
        def _extract(svg: str, a: str) -> str:
            idx = svg.find(a)
            if idx == -1:
                return ""
            s = svg[idx + len(a):]
            return s.split('"')[1] if '"' in s else s.split(" ")[0]
        assert _extract(r_ansi.svg, attr) == _extract(r_arch.svg, attr)


# ---------------------------------------------------------------------------
# Bounding boxes
# ---------------------------------------------------------------------------

def test_plan_view_bbox_tuple():
    geom = _make_alignment(10)
    spec = _default_spec()
    result = generate_plan_profile_sheet(geom, spec)
    assert len(result.plan_view_bbox) == 4
    x, y, w, h = result.plan_view_bbox
    assert w > 0 and h > 0


def test_profile_view_bbox_tuple():
    geom = _make_alignment(10)
    spec = _default_spec()
    result = generate_plan_profile_sheet(geom, spec)
    assert len(result.profile_view_bbox) == 4
    x, y, w, h = result.profile_view_bbox
    assert w > 0 and h > 0


def test_profile_below_plan():
    """Profile view y-origin must be greater than plan view y-origin (below it)."""
    geom = _make_alignment(10)
    spec = _default_spec()
    result = generate_plan_profile_sheet(geom, spec)
    plan_y = result.plan_view_bbox[1]
    prof_y = result.profile_view_bbox[1]
    assert prof_y > plan_y


# ---------------------------------------------------------------------------
# Station labels
# ---------------------------------------------------------------------------

def test_stations_labeled_nonempty():
    """stations_labeled must contain at least one station value."""
    geom = _make_alignment(10)
    spec = _default_spec()
    result = generate_plan_profile_sheet(geom, spec)
    assert len(result.stations_labeled) >= 1


def test_stations_labeled_within_range():
    """All labeled stations must fall within [station_start, station_end]."""
    geom = _make_alignment(10, sta_start=0.0, sta_step=50.0)
    spec = _default_spec(station_start=0.0, station_end=450.0)
    result = generate_plan_profile_sheet(geom, spec)
    for sta in result.stations_labeled:
        assert 0.0 <= sta <= 450.0 + 1e-6, f"Station {sta} out of range"


# ---------------------------------------------------------------------------
# Vertical exaggeration
# ---------------------------------------------------------------------------

def test_vertical_exaggeration_10x():
    """
    Profile view with 10× vertical exaggeration (AASHTO Green Book 2018 §3).
    The SVG must contain 'Vert. Exag. 10×' or similar text.
    """
    geom = _make_alignment(10)
    spec = _default_spec(profile_view_scale_v=10.0)
    result = generate_plan_profile_sheet(geom, spec)
    assert "10" in result.svg   # e.g. "Vert. Exag. 10×"


def test_different_exaggeration_reflected():
    """Changing profile_view_scale_v from 10 to 5 changes the SVG output."""
    geom = _make_alignment(10)
    spec10 = _default_spec(profile_view_scale_v=10.0)
    spec5 = _default_spec(profile_view_scale_v=5.0)
    r10 = generate_plan_profile_sheet(geom, spec10)
    r5 = generate_plan_profile_sheet(geom, spec5)
    assert r10.svg != r5.svg


# ---------------------------------------------------------------------------
# Degenerate input
# ---------------------------------------------------------------------------

def test_degenerate_single_point_no_crash():
    """Single-point alignment → returns sheet without crashing."""
    geom = [(0.0, 0.0, 0.0, 100.0)]
    spec = _default_spec(station_start=0.0, station_end=0.0)
    result = generate_plan_profile_sheet(geom, spec)
    assert isinstance(result.svg, str)
    assert len(result.svg) > 10


def test_title_block_contains_alignment_id():
    """SVG title block must contain the alignment_id string."""
    geom = _make_alignment(10)
    spec = _default_spec(alignment_id="RIVER_ROAD_STA_0_TO_500")
    result = generate_plan_profile_sheet(geom, spec)
    assert "RIVER_ROAD_STA_0_TO_500" in result.svg
