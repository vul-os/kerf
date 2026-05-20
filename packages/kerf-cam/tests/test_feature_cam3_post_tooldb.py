"""
T-36  CAM 3-axis: post + tool DB integration.

Scope : kerf-cam/posts/ + tool_db.py chained with cam_jobs.
Target: 25 toolpaths; valid G-code for fanuc/mach3/grbl/linuxcnc;
        tool-change blocks; feed/speed from DB.

All tests are pure-Python — no DB, no opencamlib, no pythonOCC.
"""

from __future__ import annotations

import re
import sys
import os

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), "src"))

import pytest

from kerf_cam.tool_db import parse_tool, Tool
from kerf_cam.posts_common import PostOpts3
from kerf_cam.posts.linuxcnc_3x import emit as lnx_emit
from kerf_cam.posts.grbl_3x import emit as grbl_emit
from kerf_cam.posts.mach3_3x import emit as mach3_emit
from kerf_cam.posts.fanuc_3x import emit as fanuc_emit

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

ALL_EMITTERS = [
    ("fanuc",    fanuc_emit),
    ("mach3",    mach3_emit),
    ("grbl",     grbl_emit),
    ("linuxcnc", lnx_emit),
]

EMITTER_IDS = [name for name, _ in ALL_EMITTERS]
EMITTER_FNS = [fn for _, fn in ALL_EMITTERS]


def _pts(n: int = 5, *, z: float = -2.0) -> list[dict]:
    """n evenly spaced CL points along X at fixed Y/Z."""
    return [{"x": float(i) * 10.0, "y": float(i) * 2.0, "z": z} for i in range(n)]


def _flat_end(overrides: dict | None = None) -> dict:
    d = {
        "id": "T1",
        "name": "6mm carbide flat-end",
        "type": "flat_end",
        "diameter_mm": 6.0,
        "flute_count": 2,
        "material": "carbide",
        "spindle_rpm_min": 8000,
        "feed_rate_mm_min": 750.0,
        "plunge_rate_mm_min": 200.0,
    }
    if overrides:
        d.update(overrides)
    return d


def _ball_end(overrides: dict | None = None) -> dict:
    d = {
        "id": "T2",
        "name": "4mm ball-end HSS",
        "type": "ball_end",
        "diameter_mm": 4.0,
        "ball_radius_mm": 2.0,
        "flute_count": 2,
        "material": "hss",
        "spindle_rpm_min": 12000,
        "feed_rate_mm_min": 600.0,
        "plunge_rate_mm_min": 150.0,
    }
    if overrides:
        d.update(overrides)
    return d


def _bull_end(overrides: dict | None = None) -> dict:
    d = {
        "id": "T3",
        "name": "10mm bull-end",
        "type": "bull_end",
        "diameter_mm": 10.0,
        "corner_radius_mm": 1.0,
        "spindle_rpm_min": 6000,
        "feed_rate_mm_min": 900.0,
        "plunge_rate_mm_min": 250.0,
    }
    if overrides:
        d.update(overrides)
    return d


def _drill(overrides: dict | None = None) -> dict:
    d = {
        "id": "T4",
        "name": "5mm HSS drill",
        "type": "drill",
        "diameter_mm": 5.0,
        "tip_angle_deg": 118.0,
        "spindle_rpm_min": 3000,
        "feed_rate_mm_min": 120.0,
        "plunge_rate_mm_min": 80.0,
    }
    if overrides:
        d.update(overrides)
    return d


def _face_mill(overrides: dict | None = None) -> dict:
    d = {
        "id": "T5",
        "name": "50mm face mill",
        "type": "face_mill",
        "diameter_mm": 50.0,
        "spindle_rpm_min": 2500,
        "feed_rate_mm_min": 1200.0,
        "plunge_rate_mm_min": 400.0,
    }
    if overrides:
        d.update(overrides)
    return d


def _chamfer(overrides: dict | None = None) -> dict:
    d = {
        "id": "T6",
        "name": "90deg chamfer",
        "type": "chamfer",
        "diameter_mm": 8.0,
        "included_angle_deg": 90.0,
        "spindle_rpm_min": 5000,
        "feed_rate_mm_min": 300.0,
        "plunge_rate_mm_min": 100.0,
    }
    if overrides:
        d.update(overrides)
    return d


# ---------------------------------------------------------------------------
# Toolpath fixtures: 25 distinct (tool, pts, opts) combinations
# ---------------------------------------------------------------------------

def _toolpath_cases():
    """Yield (case_id, tool_dict, cl_points, extra_opts) for 25 toolpaths."""
    # 1-5: flat-end tool, varying path lengths
    for n, pts_count in enumerate([1, 3, 5, 10, 20], start=1):
        yield (
            f"flat_end_n{pts_count}",
            _flat_end(),
            _pts(pts_count),
            {},
        )

    # 6-10: ball-end at various Z depths
    for n, z in enumerate([-0.5, -1.0, -2.5, -5.0, -10.0], start=6):
        yield (
            f"ball_end_z{abs(z):.1f}",
            _ball_end(),
            _pts(4, z=z),
            {},
        )

    # 11-12: bull-end and drill
    yield ("bull_end_basic",  _bull_end(), _pts(5), {})
    yield ("drill_basic",     _drill(),    _pts(3), {})

    # 13: face mill — wide flat pass
    yield ("face_mill_basic", _face_mill(), _pts(6), {})

    # 14: chamfer pass
    yield ("chamfer_basic", _chamfer(), _pts(4), {})

    # 15: flat-end, flood coolant off
    yield (
        "flat_end_coolant_off",
        _flat_end(),
        _pts(4),
        {"coolant": "off"},
    )

    # 16: flat-end, mist coolant
    yield (
        "flat_end_coolant_mist",
        _flat_end(),
        _pts(4),
        {"coolant": "mist"},
    )

    # 17: ball-end, explicit override feed beats tool feed
    yield (
        "ball_end_feed_override",
        _ball_end(),
        _pts(4),
        {"feed_cut_mm_min": 999.0},
    )

    # 18: flat-end, explicit spindle override
    yield (
        "flat_end_spindle_override",
        _flat_end(),
        _pts(4),
        {"spindle_rpm": 15000},
    )

    # 19: per-point feed override embedded in CL points
    pts_pp = [
        {"x": 0.0, "y": 0.0, "z": -1.0, "feed": 333.0},
        {"x": 10.0, "y": 0.0, "z": -1.0},
        {"x": 20.0, "y": 0.0, "z": -1.0},
    ]
    yield ("per_point_feed", _flat_end(), pts_pp, {})

    # 20: tool with full geometry (shank, flute_length, overall_length)
    yield (
        "flat_end_full_geometry",
        _flat_end({
            "shank_diameter_mm": 6.0,
            "flute_length_mm": 20.0,
            "overall_length_mm": 60.0,
        }),
        _pts(5),
        {},
    )

    # 21-22: two tools in sequence (same opts object is separate per call)
    yield ("t2_then_t1_flat", _flat_end({"id": "T7"}), _pts(3), {"tool_number": 7})
    yield ("t2_then_t1_ball", _ball_end({"id": "T8"}), _pts(3), {"tool_number": 8})

    # 23: flat-end, single-point (boundary: only one CL point)
    yield ("flat_end_single_point", _flat_end(), _pts(1), {})

    # 24: drill with no feeds — rely fully on sentinel defaults
    yield (
        "drill_no_feeds",
        {"id": "T9", "name": "3mm drill", "type": "drill", "diameter_mm": 3.0},
        _pts(2),
        {},
    )

    # 25: flat-end, no_n_numbers=True (Fanuc variant; others unaffected)
    yield (
        "flat_end_no_n_numbers",
        _flat_end(),
        _pts(5),
        {"no_n_numbers": True},
    )


TOOLPATHS = list(_toolpath_cases())
TOOLPATH_IDS = [tp[0] for tp in TOOLPATHS]


def _make_opts(tool: Tool, extra: dict) -> PostOpts3:
    kwargs = {"tool": tool}
    kwargs.update(extra)
    return PostOpts3(**kwargs)


# ===========================================================================
# Section 1: All 25 toolpaths produce non-empty G-code for all 4 posts
#            (parametrized: 25 toolpaths × 4 posts = 100 sub-cases)
# ===========================================================================

@pytest.mark.parametrize("case_id,tool_dict,cl_pts,extra_opts", TOOLPATHS, ids=TOOLPATH_IDS)
@pytest.mark.parametrize("post_name,emit_fn", ALL_EMITTERS, ids=EMITTER_IDS)
def test_gcode_nonempty(post_name, emit_fn, case_id, tool_dict, cl_pts, extra_opts):
    """Every (post, toolpath) combination produces a non-empty string."""
    tool = parse_tool(tool_dict)
    opts = _make_opts(tool, extra_opts)
    gcode = emit_fn(cl_pts, opts)
    assert isinstance(gcode, str) and len(gcode) > 0, (
        f"{post_name}/{case_id}: got empty output"
    )


# ===========================================================================
# Section 2: G-code structure — program end marker present
# ===========================================================================

@pytest.mark.parametrize("case_id,tool_dict,cl_pts,extra_opts", TOOLPATHS, ids=TOOLPATH_IDS)
@pytest.mark.parametrize("post_name,emit_fn", ALL_EMITTERS, ids=EMITTER_IDS)
def test_gcode_has_m30(post_name, emit_fn, case_id, tool_dict, cl_pts, extra_opts):
    """Every post must end with M30 (program end + rewind)."""
    tool = parse_tool(tool_dict)
    opts = _make_opts(tool, extra_opts)
    gcode = emit_fn(cl_pts, opts)
    assert "M30" in gcode, f"{post_name}/{case_id}: M30 missing"


# ===========================================================================
# Section 3: Tool-change blocks — tool-change present in output
# ===========================================================================

@pytest.mark.parametrize("case_id,tool_dict,cl_pts,extra_opts", TOOLPATHS, ids=TOOLPATH_IDS)
def test_linuxcnc_tool_change_present(case_id, tool_dict, cl_pts, extra_opts):
    """LinuxCNC must have M6 T<n> in output for every toolpath."""
    tool = parse_tool(tool_dict)
    opts = _make_opts(tool, extra_opts)
    gcode = lnx_emit(cl_pts, opts)
    assert re.search(r"M6 T\d+", gcode), (
        f"linuxcnc/{case_id}: no M6 T<n> tool-change found"
    )


@pytest.mark.parametrize("case_id,tool_dict,cl_pts,extra_opts", TOOLPATHS, ids=TOOLPATH_IDS)
def test_mach3_tool_change_present(case_id, tool_dict, cl_pts, extra_opts):
    """Mach3 must have T<n> M6 tool-change block for every toolpath."""
    tool = parse_tool(tool_dict)
    opts = _make_opts(tool, extra_opts)
    gcode = mach3_emit(cl_pts, opts)
    assert re.search(r"T\d+ M6", gcode), (
        f"mach3/{case_id}: no T<n> M6 tool-change found"
    )


@pytest.mark.parametrize("case_id,tool_dict,cl_pts,extra_opts", TOOLPATHS, ids=TOOLPATH_IDS)
def test_grbl_tool_change_comment_present(case_id, tool_dict, cl_pts, extra_opts):
    """GRBL must have (M6 T<n>) comment — never a bare M6."""
    tool = parse_tool(tool_dict)
    opts = _make_opts(tool, extra_opts)
    gcode = grbl_emit(cl_pts, opts)
    assert re.search(r"\(M6 T\d+\)", gcode), (
        f"grbl/{case_id}: no (M6 T<n>) comment found"
    )
    # Verify no bare M6 on any non-comment line
    for line in gcode.splitlines():
        stripped = line.strip()
        if stripped.startswith("(") or stripped.startswith(";"):
            continue
        assert not re.match(r"M6(\s|$)", stripped), (
            f"grbl/{case_id}: bare M6 found on non-comment line: {line!r}"
        )


@pytest.mark.parametrize("case_id,tool_dict,cl_pts,extra_opts", TOOLPATHS, ids=TOOLPATH_IDS)
def test_fanuc_tool_change_present(case_id, tool_dict, cl_pts, extra_opts):
    """Fanuc must have M6 T<n> for every toolpath."""
    tool = parse_tool(tool_dict)
    opts = _make_opts(tool, extra_opts)
    gcode = fanuc_emit(cl_pts, opts)
    assert re.search(r"M6 T\d+", gcode), (
        f"fanuc/{case_id}: no M6 T<n> tool-change found"
    )


# ===========================================================================
# Section 4: Feed/speed come from tool DB — not sentinel defaults
# ===========================================================================

@pytest.mark.parametrize("post_name,emit_fn", ALL_EMITTERS, ids=EMITTER_IDS)
def test_feed_from_tool_db_flat_end(post_name, emit_fn):
    """Cut feed of 750 mm/min from tool DB must appear in output."""
    tool = parse_tool(_flat_end())  # feed_rate_mm_min = 750
    opts = _make_opts(tool, {})
    gcode = emit_fn(_pts(5), opts)
    assert "F750" in gcode, (
        f"{post_name}: expected F750 (tool DB feed) not found"
    )


@pytest.mark.parametrize("post_name,emit_fn", ALL_EMITTERS, ids=EMITTER_IDS)
def test_plunge_feed_from_tool_db(post_name, emit_fn):
    """Plunge feed 200 mm/min from tool DB must appear in output."""
    tool = parse_tool(_flat_end())  # plunge_rate_mm_min = 200
    opts = _make_opts(tool, {})
    gcode = emit_fn(_pts(3), opts)
    assert "F200" in gcode, (
        f"{post_name}: expected F200 (tool DB plunge) not found"
    )


@pytest.mark.parametrize("post_name,emit_fn", ALL_EMITTERS, ids=EMITTER_IDS)
def test_spindle_from_tool_db(post_name, emit_fn):
    """Spindle RPM 8000 from tool DB must appear in output."""
    tool = parse_tool(_flat_end())  # spindle_rpm_min = 8000
    opts = _make_opts(tool, {})
    gcode = emit_fn(_pts(3), opts)
    assert "S8000" in gcode, (
        f"{post_name}: expected S8000 from tool DB not found"
    )


@pytest.mark.parametrize("post_name,emit_fn", ALL_EMITTERS, ids=EMITTER_IDS)
def test_caller_override_beats_tool_db_feed(post_name, emit_fn):
    """Explicit PostOpts3.feed_cut_mm_min must override tool DB value."""
    tool = parse_tool(_flat_end())  # tool feed = 750
    opts = _make_opts(tool, {"feed_cut_mm_min": 1111.0})
    gcode = emit_fn(_pts(4), opts)
    assert "F1111" in gcode, (
        f"{post_name}: expected F1111 (caller override) not found"
    )
    assert "F750" not in gcode, (
        f"{post_name}: tool DB feed F750 should be suppressed by caller override"
    )


@pytest.mark.parametrize("post_name,emit_fn", ALL_EMITTERS, ids=EMITTER_IDS)
def test_ball_end_feed_from_tool_db(post_name, emit_fn):
    """Ball-end tool: feed 600 and plunge 150 from tool DB."""
    tool = parse_tool(_ball_end())
    opts = _make_opts(tool, {})
    gcode = emit_fn(_pts(4), opts)
    assert "F600" in gcode, f"{post_name}: F600 (ball-end cut feed) not found"
    assert "F150" in gcode, f"{post_name}: F150 (ball-end plunge feed) not found"


@pytest.mark.parametrize("post_name,emit_fn", ALL_EMITTERS, ids=EMITTER_IDS)
def test_bull_end_feed_from_tool_db(post_name, emit_fn):
    """Bull-end tool: feed 900 and plunge 250 from tool DB."""
    tool = parse_tool(_bull_end())
    opts = _make_opts(tool, {})
    gcode = emit_fn(_pts(3), opts)
    assert "F900" in gcode, f"{post_name}: F900 (bull-end cut feed) not found"
    assert "F250" in gcode, f"{post_name}: F250 (bull-end plunge feed) not found"


# ===========================================================================
# Section 5: G-code coordinate output — X/Y/Z moves present
# ===========================================================================

@pytest.mark.parametrize("post_name,emit_fn", ALL_EMITTERS, ids=EMITTER_IDS)
def test_xyz_moves_present(post_name, emit_fn):
    """G1 moves must contain X/Y/Z coordinates for non-empty toolpaths."""
    tool = parse_tool(_flat_end())
    opts = _make_opts(tool, {})
    gcode = emit_fn(_pts(5), opts)
    g1_lines = [l for l in gcode.splitlines() if "G1 X" in l or "G1 Z" in l]
    assert len(g1_lines) >= 1, f"{post_name}: no G1 moves found"
    # At least one G1 should have all three coordinates
    xyz_lines = [l for l in g1_lines if "X" in l and "Y" in l and "Z" in l]
    assert len(xyz_lines) >= 1, f"{post_name}: no G1 with X,Y,Z found"


@pytest.mark.parametrize("post_name,emit_fn", ALL_EMITTERS, ids=EMITTER_IDS)
def test_coordinate_format(post_name, emit_fn):
    """Coordinates must be formatted as decimal numbers (3 d.p.)."""
    tool = parse_tool(_flat_end())
    opts = _make_opts(tool, {})
    gcode = emit_fn(_pts(3), opts)
    # Match e.g. X10.000 or X-3.500
    assert re.search(r"[XYZ]-?\d+\.\d{3}", gcode), (
        f"{post_name}: no 3-decimal coordinate found"
    )


# ===========================================================================
# Section 6: Absolute positioning and unit mode headers
# ===========================================================================

@pytest.mark.parametrize("post_name,emit_fn", ALL_EMITTERS, ids=EMITTER_IDS)
def test_absolute_mode(post_name, emit_fn):
    """All posts must use G90 absolute positioning."""
    tool = parse_tool(_flat_end())
    opts = _make_opts(tool, {})
    gcode = emit_fn(_pts(3), opts)
    assert "G90" in gcode, f"{post_name}: G90 (absolute) missing"


@pytest.mark.parametrize("post_name,emit_fn", ALL_EMITTERS, ids=EMITTER_IDS)
def test_metric_mode(post_name, emit_fn):
    """All posts must declare G21 metric units."""
    tool = parse_tool(_flat_end())
    opts = _make_opts(tool, {})
    gcode = emit_fn(_pts(3), opts)
    assert "G21" in gcode, f"{post_name}: G21 (metric) missing"


# ===========================================================================
# Section 7: Dialect-specific structural rules
# ===========================================================================

def test_linuxcnc_tape_markers():
    """LinuxCNC output must be wrapped with % tape markers."""
    gcode = lnx_emit(_pts(3), PostOpts3())
    assert gcode.startswith("%"), "LinuxCNC: should start with %"
    assert gcode.endswith("%"), "LinuxCNC: should end with %"


def test_mach3_no_tape_markers():
    """Mach3 does not need % tape markers."""
    gcode = mach3_emit(_pts(3), PostOpts3())
    assert "%" not in gcode, "Mach3: should not contain % tape markers"


def test_grbl_tape_markers():
    """GRBL output is wrapped with % tape markers."""
    gcode = grbl_emit(_pts(3), PostOpts3())
    assert gcode.startswith("%"), "GRBL: should start with %"
    assert gcode.endswith("%"), "GRBL: should end with %"


def test_fanuc_n_numbers_present():
    """Fanuc defaults to N-number line sequencing."""
    gcode = fanuc_emit(_pts(3), PostOpts3())
    assert re.search(r"N\d+\s", gcode), "Fanuc: N-number lines missing"


def test_fanuc_no_n_numbers_mode():
    """Fanuc: no_n_numbers=True suppresses N-numbers but keeps G-code body."""
    opts = PostOpts3(no_n_numbers=True)
    gcode = fanuc_emit(_pts(3), opts)
    assert not re.search(r"\bN\d+\s", gcode), "Fanuc: N-numbers present when suppressed"
    assert "G90" in gcode, "Fanuc: G90 missing when no_n_numbers=True"


def test_mach3_paren_tool_comment():
    """Mach3 uses parenthetical (upper-case) comments for tool info."""
    tool = parse_tool(_flat_end())
    opts = PostOpts3(tool=tool)
    gcode = mach3_emit(_pts(3), opts)
    assert re.search(r"\(TOOL:", gcode), "Mach3: no (TOOL:...) comment found"


def test_fanuc_paren_tool_comment():
    """Fanuc uses parenthetical (upper-case) comments for tool info."""
    tool = parse_tool(_flat_end())
    opts = PostOpts3(tool=tool)
    gcode = fanuc_emit(_pts(3), opts)
    assert re.search(r"\(TOOL:", gcode), "Fanuc: no (TOOL:...) comment found"


def test_linuxcnc_semicolon_tool_comment():
    """LinuxCNC uses ; prefix for tool comment."""
    tool = parse_tool(_flat_end())
    opts = PostOpts3(tool=tool)
    gcode = lnx_emit(_pts(3), opts)
    assert "; tool: T1" in gcode, "LinuxCNC: no '; tool: T1' comment found"


def test_grbl_semicolon_tool_comment():
    """GRBL uses ; prefix for tool comment."""
    tool = parse_tool(_flat_end())
    opts = PostOpts3(tool=tool)
    gcode = grbl_emit(_pts(3), opts)
    assert "; tool: T1" in gcode, "GRBL: no '; tool: T1' comment found"


# ===========================================================================
# Section 8: Boundary / malformed inputs
# ===========================================================================

@pytest.mark.parametrize("post_name,emit_fn", ALL_EMITTERS, ids=EMITTER_IDS)
def test_empty_toolpath_handled_gracefully(post_name, emit_fn):
    """Empty CL point list must not crash — must still produce M30."""
    opts = PostOpts3()
    gcode = emit_fn([], opts)
    assert "M30" in gcode, f"{post_name}: M30 missing for empty toolpath"
    # No G1 X moves should be emitted
    assert not any("G1 X" in line for line in gcode.splitlines()), (
        f"{post_name}: unexpected G1 X on empty toolpath"
    )


@pytest.mark.parametrize("post_name,emit_fn", ALL_EMITTERS, ids=EMITTER_IDS)
def test_single_point_toolpath(post_name, emit_fn):
    """Single CL point: rapid + plunge + end — no cutting G1 X move needed."""
    tool = parse_tool(_flat_end())
    opts = _make_opts(tool, {})
    gcode = emit_fn([{"x": 0.0, "y": 0.0, "z": -1.0}], opts)
    assert "M30" in gcode, f"{post_name}: M30 missing for single-point toolpath"


@pytest.mark.parametrize("post_name,emit_fn", ALL_EMITTERS, ids=EMITTER_IDS)
def test_negative_coordinates(post_name, emit_fn):
    """Negative X/Y/Z coordinates must be emitted correctly."""
    pts = [{"x": -10.0, "y": -5.0, "z": -3.0}, {"x": -5.0, "y": -2.5, "z": -3.0}]
    tool = parse_tool(_flat_end())
    opts = _make_opts(tool, {})
    gcode = emit_fn(pts, opts)
    assert "X-10.000" in gcode or "X-10." in gcode, (
        f"{post_name}: negative X coordinate not found"
    )


@pytest.mark.parametrize("post_name,emit_fn", ALL_EMITTERS, ids=EMITTER_IDS)
def test_large_toolpath_100_points(post_name, emit_fn):
    """100 CL points must complete without error and produce at least 100 G1 lines."""
    pts = [{"x": float(i), "y": 0.0, "z": -1.0} for i in range(100)]
    tool = parse_tool(_flat_end())
    opts = _make_opts(tool, {})
    gcode = emit_fn(pts, opts)
    g1_count = sum(1 for line in gcode.splitlines() if line.strip().startswith("G1") or
                   # Fanuc prefixes N<n> before G1
                   re.match(r"N\d+ G1", line))
    assert g1_count >= 100, (
        f"{post_name}: expected >= 100 G1 lines for 100-point path, got {g1_count}"
    )


# ===========================================================================
# Section 9: Idempotency — calling emit() twice gives identical output
# ===========================================================================

@pytest.mark.parametrize("post_name,emit_fn", ALL_EMITTERS, ids=EMITTER_IDS)
def test_emit_idempotent(post_name, emit_fn):
    """Two calls with the same opts produce identical G-code."""
    tool = parse_tool(_flat_end())
    pts = _pts(5)
    # Use separate opts objects (apply_tool_defaults is called in-place)
    gcode1 = emit_fn(pts, _make_opts(tool, {}))
    gcode2 = emit_fn(pts, _make_opts(tool, {}))
    assert gcode1 == gcode2, f"{post_name}: emit is not idempotent"


# ===========================================================================
# Section 10: Tool DB round-trip sanity
# ===========================================================================

@pytest.mark.parametrize("tool_dict", [
    _flat_end(), _ball_end(), _bull_end(), _drill(), _face_mill(), _chamfer(),
], ids=["flat_end", "ball_end", "bull_end", "drill", "face_mill", "chamfer"])
def test_tool_db_roundtrip_feeds_preserved(tool_dict):
    """parse_tool -> to_dict must preserve feed_rate_mm_min and plunge_rate_mm_min."""
    tool = parse_tool(tool_dict)
    out = tool.to_dict()
    if tool_dict.get("feed_rate_mm_min") is not None:
        assert out["feed_rate_mm_min"] == pytest.approx(tool_dict["feed_rate_mm_min"])
    if tool_dict.get("plunge_rate_mm_min") is not None:
        assert out["plunge_rate_mm_min"] == pytest.approx(tool_dict["plunge_rate_mm_min"])
    if tool_dict.get("spindle_rpm_min") is not None:
        assert out["spindle_rpm_min"] == pytest.approx(tool_dict["spindle_rpm_min"])
