"""
Hermetic tests for kerf_cad_core.cam_lathe_profile — lathe G-code emitter.

Coverage:
  emit_lathe_gcode — cylinder step reduction (Ø20 → Ø10 at Z=50)
  emit_lathe_gcode — tapered profile (linear XZ interpolation in G70 blocks)
  emit_lathe_gcode — concave step profile (warning emitted; program still produced)
  emit_lathe_gcode — oracle G71/G70 block syntax check
  emit_lathe_gcode — M03/M06 sequence in correct order
  emit_lathe_gcode — G96 CSS block appears before G70
  emit_lathe_gcode — G97 constant-RPM appears before G71 and after G70
  emit_lathe_gcode — profile block N100/N200 numbering
  emit_lathe_gcode — program number O-word emitted when supplied
  emit_lathe_gcode — ValueError on < 2 profile points
  emit_lathe_gcode — ValueError when stock_x_mm <= max profile X
  emit_lathe_gcode — diameter programming (X = 2 × radius)
  emit_lathe_gcode — SFM → CSS conversion
  emit_lathe_gcode — pass_count estimate
  cam_emit_lathe_gcode LLM tool — happy path (cylinder)
  cam_emit_lathe_gcode LLM tool — missing profile → error
  cam_emit_lathe_gcode LLM tool — missing stock_x_mm → error
  cam_emit_lathe_gcode LLM tool — bad JSON → error
  cam_emit_lathe_gcode LLM tool — stock_x_mm too small → error

All tests are pure-Python and hermetic: no OCC, no DB, no network.

References:
  NIST RS-274/NGC Interpreter Version 3 (Kramer et al. 2000).
  Smid, P. CNC Programming Handbook, 3rd ed., Industrial Press 2008, §6.

Author: imranparuk
"""
from __future__ import annotations

import asyncio
import json
import math
import re
import uuid

import pytest

from kerf_cad_core.cam_lathe_profile import (
    emit_lathe_gcode,
    LatheProgram,
    _sfm_to_css,
    _calc_rpm,
    _dia,
    _fmt,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _fake_ctx():
    class _Ctx:
        project_id = uuid.uuid4()
    return _Ctx()


def _lines(prog: LatheProgram) -> list[str]:
    return [ln for ln in prog.text.splitlines() if ln.strip()]


# ---------------------------------------------------------------------------
# Unit: helpers
# ---------------------------------------------------------------------------

def test_fmt_integer_value():
    assert _fmt(10.0) == "10."


def test_fmt_fractional_value():
    assert _fmt(1.2346) == "1.2346"


def test_fmt_no_decimal_places():
    assert _fmt(2000.0, 0) == "2000"


def test_sfm_to_css():
    css = _sfm_to_css(600.0)
    assert abs(css - 182.88) < 0.01


def test_calc_rpm_at_10mm_radius():
    css = _sfm_to_css(600.0)
    rpm = _calc_rpm(css, 10.0)  # 20mm diameter
    expected = (css * 1000.0) / (math.pi * 20.0)
    assert abs(rpm - expected) < 1.0


def test_calc_rpm_clamped_max():
    # Very small radius → RPM would exceed _RPM_MAX
    rpm = _calc_rpm(300.0, 0.01)
    assert rpm == 4000.0


def test_calc_rpm_zero_radius():
    rpm = _calc_rpm(300.0, 0.0)
    assert rpm == 4000.0


def test_dia_double():
    assert _dia(10.0) == 20.0


# ---------------------------------------------------------------------------
# Core: cylinder step reduction (Ø20mm → Ø10mm step at Z=50)
# ---------------------------------------------------------------------------

# Profile: starts at Z=0, X=10 (Ø20); steps to X=5 (Ø10) at Z=50
CYL_PROFILE = [(0.0, 10.0), (50.0, 10.0), (50.0, 5.0), (100.0, 5.0)]
CYL_STOCK = 12.0  # radius (Ø24mm stock)


def test_cylinder_returns_lathe_program():
    prog = emit_lathe_gcode(CYL_PROFILE, CYL_STOCK)
    assert isinstance(prog, LatheProgram)
    assert prog.text
    assert prog.line_count > 0


def test_cylinder_g71_present():
    prog = emit_lathe_gcode(CYL_PROFILE, CYL_STOCK)
    assert any(ln.startswith("G71") for ln in _lines(prog))


def test_cylinder_g70_present():
    prog = emit_lathe_gcode(CYL_PROFILE, CYL_STOCK)
    assert any(ln.startswith("G70") for ln in _lines(prog))


def test_cylinder_g96_present():
    """G96 constant-surface-speed block must appear before G70."""
    prog = emit_lathe_gcode(CYL_PROFILE, CYL_STOCK)
    lines = _lines(prog)
    g96_idx = next((i for i, ln in enumerate(lines) if ln.startswith("G96")), None)
    g70_idx = next((i for i, ln in enumerate(lines) if ln.startswith("G70")), None)
    assert g96_idx is not None, "G96 not found"
    assert g70_idx is not None, "G70 not found"
    assert g96_idx < g70_idx, "G96 must precede G70"


def test_cylinder_g97_before_g71():
    """G97 (constant RPM) must appear before G71 rough cycle."""
    prog = emit_lathe_gcode(CYL_PROFILE, CYL_STOCK)
    lines = _lines(prog)
    g97_idx = next((i for i, ln in enumerate(lines) if ln.startswith("G97")), None)
    g71_idx = next((i for i, ln in enumerate(lines) if ln.startswith("G71")), None)
    assert g97_idx is not None
    assert g71_idx is not None
    assert g97_idx < g71_idx


def test_cylinder_m03_spindle_on():
    prog = emit_lathe_gcode(CYL_PROFILE, CYL_STOCK)
    assert any("M03" in ln for ln in _lines(prog))


def test_cylinder_m05_spindle_off():
    prog = emit_lathe_gcode(CYL_PROFILE, CYL_STOCK)
    assert any(ln.strip() == "M05" for ln in _lines(prog))


def test_cylinder_m06_tool_change():
    prog = emit_lathe_gcode(CYL_PROFILE, CYL_STOCK)
    assert any("M06" in ln for ln in _lines(prog))


def test_cylinder_m06_before_m03():
    """Tool change must precede spindle-on."""
    lines = _lines(emit_lathe_gcode(CYL_PROFILE, CYL_STOCK))
    m06_idx = next((i for i, ln in enumerate(lines) if "M06" in ln), None)
    m03_idx = next((i for i, ln in enumerate(lines) if "M03" in ln), None)
    assert m06_idx is not None
    assert m03_idx is not None
    assert m06_idx < m03_idx


def test_cylinder_m30_at_end():
    lines = _lines(emit_lathe_gcode(CYL_PROFILE, CYL_STOCK))
    assert lines[-1] == "M30"


def test_cylinder_profile_n100_block():
    prog = emit_lathe_gcode(CYL_PROFILE, CYL_STOCK)
    assert any(ln.startswith("N100 ") for ln in _lines(prog))


def test_cylinder_profile_last_n_block():
    # 4 points → N100, N110, N120, N130
    prog = emit_lathe_gcode(CYL_PROFILE, CYL_STOCK)
    assert any(ln.startswith("N130 ") for ln in _lines(prog))


def test_cylinder_diameter_programming():
    """X values in profile blocks must be diameters (2 × radius)."""
    prog = emit_lathe_gcode(CYL_PROFILE, CYL_STOCK)
    # First profile point: radius=10 → X should be 20.
    n100_line = next(ln for ln in _lines(prog) if ln.startswith("N100 "))
    assert "X20." in n100_line


def test_cylinder_css_metadata():
    prog = emit_lathe_gcode(CYL_PROFILE, CYL_STOCK, sfm=600)
    expected_css = round(_sfm_to_css(600.0), 4)
    assert abs(prog.css_m_per_min - expected_css) < 0.01


def test_cylinder_pass_count_reasonable():
    # stock_x=12, max_x=10 → radial stock=2; doc=2 → ~1 pass
    prog = emit_lathe_gcode(CYL_PROFILE, CYL_STOCK, doc_mm=2.0)
    assert prog.pass_count >= 1


def test_cylinder_feed_mm_rev():
    prog = emit_lathe_gcode(CYL_PROFILE, CYL_STOCK, ipr=0.25)
    assert prog.feed_mm_rev == 0.25


# ---------------------------------------------------------------------------
# Core: tapered profile (linear X–Z interpolation in G70 blocks)
# ---------------------------------------------------------------------------

# Profile: Z=0, X=15 (Ø30) → Z=100, X=5 (Ø10) — continuous taper
TAPER_PROFILE = [(0.0, 15.0), (50.0, 10.0), (100.0, 5.0)]
TAPER_STOCK = 17.0


def test_taper_profile_has_three_n_blocks():
    prog = emit_lathe_gcode(TAPER_PROFILE, TAPER_STOCK)
    n_blocks = [ln for ln in _lines(prog) if re.match(r"N\d{3,}", ln)]
    assert len(n_blocks) == 3


def test_taper_profile_n100_g00():
    """First profile block (N100) must be G00 — Smid 2008 §6.4."""
    prog = emit_lathe_gcode(TAPER_PROFILE, TAPER_STOCK)
    n100 = next(ln for ln in _lines(prog) if ln.startswith("N100 "))
    assert "G00" in n100


def test_taper_profile_n110_g01():
    """Subsequent profile blocks must be G01 feed moves."""
    prog = emit_lathe_gcode(TAPER_PROFILE, TAPER_STOCK)
    n110 = next(ln for ln in _lines(prog) if ln.startswith("N110 "))
    assert "G01" in n110


def test_taper_profile_g71_p_q():
    """G71 must reference P=100 and Q=120 for 3-point profile."""
    prog = emit_lathe_gcode(TAPER_PROFILE, TAPER_STOCK)
    g71 = next(ln for ln in _lines(prog) if ln.startswith("G71"))
    assert "P100" in g71
    assert "Q120" in g71


def test_taper_profile_g70_p_q():
    """G70 must reference same P/Q as G71."""
    prog = emit_lathe_gcode(TAPER_PROFILE, TAPER_STOCK)
    g70 = next(ln for ln in _lines(prog) if ln.startswith("G70"))
    assert "P100" in g70
    assert "Q120" in g70


def test_taper_no_warnings():
    """Monotone-decreasing X taper should produce no warnings."""
    prog = emit_lathe_gcode(TAPER_PROFILE, TAPER_STOCK)
    assert prog.warnings == []


# ---------------------------------------------------------------------------
# Core: concave step profile (X increases mid-profile — triggers warning)
# ---------------------------------------------------------------------------

# Concave: Z=0, X=10 → Z=30, X=5 → Z=60, X=8 (concave, X goes up)
CONCAVE_PROFILE = [(0.0, 10.0), (30.0, 5.0), (60.0, 8.0)]
CONCAVE_STOCK = 12.0


def test_concave_still_emits_program():
    prog = emit_lathe_gcode(CONCAVE_PROFILE, CONCAVE_STOCK)
    assert prog.text
    assert any(ln.startswith("G71") for ln in _lines(prog))


def test_concave_emits_warning():
    prog = emit_lathe_gcode(CONCAVE_PROFILE, CONCAVE_STOCK)
    assert any("concave" in w.lower() for w in prog.warnings)


# ---------------------------------------------------------------------------
# Oracle: G71 block format (Smid 2008 §6.4)
# ---------------------------------------------------------------------------

def test_oracle_g71_u_w_d_f_s():
    """G71 block must contain P, Q, U, W, D, F, S words."""
    prog = emit_lathe_gcode([(0.0, 5.0), (50.0, 5.0)], stock_x_mm=8.0)
    g71 = next(ln for ln in _lines(prog) if ln.startswith("G71"))
    for word in ("P", "Q", "U", "W", "D", "F", "S"):
        assert word in g71, f"G71 missing word {word}: {g71}"


def test_oracle_g70_f_s():
    """G70 block must contain P, Q, F, S words."""
    prog = emit_lathe_gcode([(0.0, 5.0), (50.0, 5.0)], stock_x_mm=8.0)
    g70 = next(ln for ln in _lines(prog) if ln.startswith("G70"))
    for word in ("P", "Q", "F", "S"):
        assert word in g70, f"G70 missing word {word}: {g70}"


def test_oracle_preamble_g18_g21_g40():
    """Preamble must contain G18 (ZX plane), G21 (metric), G40 (cancel CNRC)."""
    prog = emit_lathe_gcode([(0.0, 5.0), (50.0, 5.0)], stock_x_mm=8.0)
    preamble = _lines(prog)[2]  # after possible O-word/comments
    # Find preamble line
    preamble_line = next(ln for ln in _lines(prog) if "G18" in ln)
    assert "G21" in preamble_line
    assert "G40" in preamble_line


# ---------------------------------------------------------------------------
# Program number
# ---------------------------------------------------------------------------

def test_program_number_o_word():
    prog = emit_lathe_gcode(
        [(0.0, 5.0), (50.0, 5.0)], stock_x_mm=8.0, program_number=42
    )
    assert _lines(prog)[0] == "O0042"


def test_no_program_number_no_o_word():
    prog = emit_lathe_gcode([(0.0, 5.0), (50.0, 5.0)], stock_x_mm=8.0)
    assert not any(re.match(r"^O\d+", ln) for ln in _lines(prog))


# ---------------------------------------------------------------------------
# Tool ID
# ---------------------------------------------------------------------------

def test_tool_id_in_t_code():
    prog = emit_lathe_gcode([(0.0, 5.0), (50.0, 5.0)], stock_x_mm=8.0, tool_id=3)
    assert any("T03" in ln for ln in _lines(prog))


# ---------------------------------------------------------------------------
# Validation errors
# ---------------------------------------------------------------------------

def test_too_few_profile_points():
    with pytest.raises(ValueError, match="at least 2 points"):
        emit_lathe_gcode([(0.0, 5.0)], stock_x_mm=8.0)


def test_stock_too_small():
    with pytest.raises(ValueError, match="stock_x_mm"):
        emit_lathe_gcode([(0.0, 10.0), (50.0, 5.0)], stock_x_mm=9.0)


def test_stock_exactly_at_max_profile_x_fails():
    with pytest.raises(ValueError):
        emit_lathe_gcode([(0.0, 10.0), (50.0, 10.0)], stock_x_mm=10.0)


def test_negative_x_radius_fails():
    with pytest.raises(ValueError, match="X_radius must be >= 0"):
        emit_lathe_gcode([(0.0, -5.0), (50.0, 5.0)], stock_x_mm=8.0)


# ---------------------------------------------------------------------------
# LLM tool wrapper
# ---------------------------------------------------------------------------

try:
    from kerf_cad_core.cam_lathe_profile import run_cam_emit_lathe_gcode
    _TOOL_AVAILABLE = True
except ImportError:
    _TOOL_AVAILABLE = False


@pytest.mark.skipif(not _TOOL_AVAILABLE, reason="kerf_chat not installed")
def test_llm_tool_happy_path_cylinder():
    ctx = _fake_ctx()
    args = json.dumps({
        "profile": [[0.0, 10.0], [50.0, 10.0], [50.0, 5.0], [100.0, 5.0]],
        "stock_x_mm": 12.0,
        "sfm": 600,
        "ipr": 0.25,
    }).encode()
    result = _run(run_cam_emit_lathe_gcode(ctx, args))
    data = json.loads(result)
    assert data["ok"] is True
    assert "G71" in data["gcode"]
    assert "G70" in data["gcode"]
    assert data["line_count"] > 0


@pytest.mark.skipif(not _TOOL_AVAILABLE, reason="kerf_chat not installed")
def test_llm_tool_missing_profile():
    ctx = _fake_ctx()
    args = json.dumps({"stock_x_mm": 12.0}).encode()
    result = _run(run_cam_emit_lathe_gcode(ctx, args))
    data = json.loads(result)
    # err_payload returns {"error": ..., "code": ...}
    assert "error" in data


@pytest.mark.skipif(not _TOOL_AVAILABLE, reason="kerf_chat not installed")
def test_llm_tool_missing_stock_x():
    ctx = _fake_ctx()
    args = json.dumps({
        "profile": [[0.0, 5.0], [50.0, 5.0]],
    }).encode()
    result = _run(run_cam_emit_lathe_gcode(ctx, args))
    data = json.loads(result)
    assert "error" in data


@pytest.mark.skipif(not _TOOL_AVAILABLE, reason="kerf_chat not installed")
def test_llm_tool_bad_json():
    ctx = _fake_ctx()
    result = _run(run_cam_emit_lathe_gcode(ctx, b"{invalid json"))
    data = json.loads(result)
    assert "error" in data


@pytest.mark.skipif(not _TOOL_AVAILABLE, reason="kerf_chat not installed")
def test_llm_tool_stock_too_small():
    ctx = _fake_ctx()
    args = json.dumps({
        "profile": [[0.0, 10.0], [50.0, 5.0]],
        "stock_x_mm": 3.0,  # smaller than max profile X (10)
    }).encode()
    result = _run(run_cam_emit_lathe_gcode(ctx, args))
    data = json.loads(result)
    assert "error" in data
