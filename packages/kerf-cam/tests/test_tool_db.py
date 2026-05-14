"""
T7 tests: tool DB schema validation + geometry sanity + round-trip.

All tests are pure-Python (no DB required).
"""

from __future__ import annotations

import sys
import os

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), "src"))

import pytest
from kerf_cam.tool_db import parse_tool, validate_tool, TOOL_TYPES, Tool


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _base(overrides=None) -> dict:
    """Return a minimal valid ball_end tool dict."""
    d = {
        "id": "T1",
        "name": "Test Ball-end",
        "type": "ball_end",
        "diameter_mm": 6.35,
        "ball_radius_mm": 3.175,
    }
    if overrides:
        d.update(overrides)
    return d


# ===========================================================================
# Section 1: Universal required field validation
# ===========================================================================

def test_missing_id():
    d = _base()
    del d["id"]
    errs = validate_tool(d)
    assert any("id" in e for e in errs), errs


def test_missing_name():
    d = _base()
    del d["name"]
    errs = validate_tool(d)
    assert any("name" in e for e in errs), errs


def test_missing_type():
    d = _base()
    del d["type"]
    errs = validate_tool(d)
    assert any("type" in e for e in errs), errs


def test_missing_diameter():
    d = _base()
    del d["diameter_mm"]
    errs = validate_tool(d)
    assert any("diameter_mm" in e for e in errs), errs


def test_unknown_type():
    d = _base({"type": "unicorn_cutter"})
    errs = validate_tool(d)
    assert any("unknown tool type" in e for e in errs), errs


# ===========================================================================
# Section 2: Type-specific required fields
# ===========================================================================

def test_ball_end_requires_ball_radius():
    d = _base()
    del d["ball_radius_mm"]
    errs = validate_tool(d)
    assert any("ball_radius_mm" in e for e in errs), errs


def test_bull_end_requires_corner_radius():
    d = {
        "id": "T2", "name": "Bull", "type": "bull_end",
        "diameter_mm": 10.0,
    }
    errs = validate_tool(d)
    assert any("corner_radius_mm" in e for e in errs), errs


def test_chamfer_requires_included_angle():
    d = {
        "id": "T3", "name": "Chamfer", "type": "chamfer",
        "diameter_mm": 8.0,
    }
    errs = validate_tool(d)
    assert any("included_angle_deg" in e for e in errs), errs


def test_engraver_requires_included_angle():
    d = {
        "id": "T4", "name": "Engrave", "type": "engraver",
        "diameter_mm": 3.0,
    }
    errs = validate_tool(d)
    assert any("included_angle_deg" in e for e in errs), errs


def test_flat_end_no_extra_required():
    d = {
        "id": "T5", "name": "Flat", "type": "flat_end",
        "diameter_mm": 6.0,
    }
    errs = validate_tool(d)
    assert errs == [], errs


def test_drill_no_extra_required():
    d = {
        "id": "T6", "name": "Drill", "type": "drill",
        "diameter_mm": 3.0,
    }
    errs = validate_tool(d)
    assert errs == [], errs


def test_face_mill_no_extra_required():
    d = {
        "id": "T7", "name": "Face Mill", "type": "face_mill",
        "diameter_mm": 50.0,
    }
    errs = validate_tool(d)
    assert errs == [], errs


# ===========================================================================
# Section 3: Geometry sanity
# ===========================================================================

def test_ball_radius_exceeds_diameter_half():
    d = _base({"ball_radius_mm": 4.0, "diameter_mm": 6.0})  # 4 > 3
    errs = validate_tool(d)
    assert any("ball_radius_mm" in e and "≤" in e for e in errs), errs


def test_ball_radius_equals_diameter_half_ok():
    d = _base({"ball_radius_mm": 3.0, "diameter_mm": 6.0})  # exact equality
    errs = validate_tool(d)
    assert errs == [], errs


def test_corner_radius_exceeds_diameter_half():
    d = {
        "id": "T8", "name": "Bull", "type": "bull_end",
        "diameter_mm": 10.0, "corner_radius_mm": 6.0,
    }
    errs = validate_tool(d)
    assert any("corner_radius_mm" in e and "≤" in e for e in errs), errs


def test_included_angle_out_of_range_zero():
    d = {
        "id": "T9", "name": "Chamfer", "type": "chamfer",
        "diameter_mm": 8.0, "included_angle_deg": 0.0,
    }
    errs = validate_tool(d)
    assert any("included_angle_deg" in e for e in errs), errs


def test_included_angle_out_of_range_180():
    d = {
        "id": "T10", "name": "Chamfer", "type": "chamfer",
        "diameter_mm": 8.0, "included_angle_deg": 180.0,
    }
    errs = validate_tool(d)
    assert any("included_angle_deg" in e for e in errs), errs


def test_included_angle_valid_90():
    d = {
        "id": "T11", "name": "Chamfer", "type": "chamfer",
        "diameter_mm": 8.0, "included_angle_deg": 90.0,
    }
    errs = validate_tool(d)
    assert errs == [], errs


def test_flute_length_exceeds_overall_length():
    d = _base({
        "flute_length_mm": 40.0,
        "overall_length_mm": 30.0,
    })
    errs = validate_tool(d)
    assert any("flute_length_mm" in e and "overall_length_mm" in e for e in errs), errs


def test_spindle_rpm_min_gt_max():
    d = _base({
        "spindle_rpm_min": 20000,
        "spindle_rpm_max": 10000,
    })
    errs = validate_tool(d)
    assert any("spindle_rpm_min" in e for e in errs), errs


def test_negative_feed_rate():
    d = _base({"feed_rate_mm_min": -100})
    errs = validate_tool(d)
    assert any("feed_rate_mm_min" in e for e in errs), errs


def test_negative_diameter():
    d = _base({"diameter_mm": -1.0})
    errs = validate_tool(d)
    assert any("diameter_mm" in e for e in errs), errs


# ===========================================================================
# Section 4: parse_tool + to_dict round-trip
# ===========================================================================

def test_round_trip_ball_end():
    d = {
        "id": "T1",
        "name": "1/4\" carbide ball-end",
        "type": "ball_end",
        "diameter_mm": 6.35,
        "ball_radius_mm": 3.175,
        "flute_length_mm": 25.0,
        "shank_diameter_mm": 6.35,
        "overall_length_mm": 65.0,
        "flute_count": 2,
        "material": "carbide",
        "spindle_rpm_min": 8000,
        "spindle_rpm_max": 24000,
        "feed_rate_mm_min": 800.0,
        "plunge_rate_mm_min": 200.0,
        "notes": "test tool",
    }
    tool = parse_tool(d)
    out = tool.to_dict()

    assert out["id"] == "T1"
    assert out["name"] == d["name"]
    assert out["type"] == "ball_end"
    assert out["diameter_mm"] == pytest.approx(6.35)
    assert out["ball_radius_mm"] == pytest.approx(3.175)
    assert out["flute_count"] == 2
    assert out["material"] == "carbide"
    assert out["spindle_rpm_min"] == pytest.approx(8000)
    assert out["feed_rate_mm_min"] == pytest.approx(800.0)


def test_round_trip_drill():
    d = {
        "id": "D1",
        "name": "3mm HSS drill",
        "type": "drill",
        "diameter_mm": 3.0,
        "tip_angle_deg": 118.0,
    }
    tool = parse_tool(d)
    out = tool.to_dict()
    assert out["type"] == "drill"
    assert out["tip_angle_deg"] == pytest.approx(118.0)


def test_parse_raises_on_invalid():
    d = _base({"ball_radius_mm": 10.0, "diameter_mm": 6.0})  # ball_r > diam/2
    with pytest.raises(ValueError, match="ball_radius_mm"):
        parse_tool(d)


# ===========================================================================
# Section 5: Tool.to_comment()
# ===========================================================================

def test_to_comment_ball_end():
    d = _base({"flute_count": 2, "material": "carbide"})
    tool = parse_tool(d)
    comment = tool.to_comment()
    assert "T1" in comment
    assert "ball r=" in comment
    assert "carbide" in comment


def test_to_comment_chamfer():
    d = {
        "id": "T12",
        "name": "90° chamfer",
        "type": "chamfer",
        "diameter_mm": 8.0,
        "included_angle_deg": 90.0,
    }
    tool = parse_tool(d)
    comment = tool.to_comment()
    assert "incl angle 90°" in comment


# ===========================================================================
# Section 6: effective_ball_radius
# ===========================================================================

def test_effective_ball_radius_ball_end():
    tool = parse_tool(_base())
    assert tool.effective_ball_radius == pytest.approx(3.175)


def test_effective_ball_radius_wrong_type():
    d = {
        "id": "T13",
        "name": "Flat",
        "type": "flat_end",
        "diameter_mm": 6.0,
    }
    tool = parse_tool(d)
    with pytest.raises(ValueError, match="ball_end"):
        _ = tool.effective_ball_radius


# ===========================================================================
# Section 7: All tool types parse without error
# ===========================================================================

@pytest.mark.parametrize("tool_type,extra", [
    ("ball_end",  {"ball_radius_mm": 3.0}),
    ("flat_end",  {}),
    ("bull_end",  {"corner_radius_mm": 1.0}),
    ("chamfer",   {"included_angle_deg": 90.0}),
    ("drill",     {}),
    ("face_mill", {}),
    ("engraver",  {"included_angle_deg": 60.0}),
])
def test_all_types_valid(tool_type, extra):
    d = {"id": "TX", "name": f"{tool_type} tool", "type": tool_type, "diameter_mm": 6.0}
    d.update(extra)
    tool = parse_tool(d)
    assert tool.type == tool_type
