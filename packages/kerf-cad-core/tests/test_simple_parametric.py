"""
Tests for the education/maker on-ramp:
  simple_parametric.templates — parametric starter part templates
  simple_parametric.cut_list  — cut-list + flat-pack layout engine
  simple_parametric.tools     — LLM tool wrappers (round-trip JSON)

Coverage:
  - list_templates returns all known template keys
  - build_part returns correct panel count and dimensions for each template
  - Box panels satisfy: bottom = W×D, front/back = W×(H-T), left/right = (D-2T)×(H-T)
  - Lid_box has a lid panel equal to external W×D
  - Enclosure has 6 panels: base, lid, front, back, left, right
  - Shelf bracket has exactly 2 panels
  - t_slot_frame returns member panels (h==0) with correct lengths
  - Unknown template raises ValueError
  - Params clamped to min/max (not rejected)
  - Default params produce positive-dimension panels
  - compute_cut_list: single panel on one sheet has utilization > 0
  - compute_cut_list: panel list from box template fits on <= 2 sheets (1220×2440)
  - compute_cut_list: rolled-up pieces have correct total area
  - compute_cut_list: placements count >= total panel qty
  - compute_cut_list: panel larger than sheet produces an error entry
  - compute_cut_list: kerf/margin=0 accepted without error
  - compute_cut_list: negative kerf clamped, error note in errors list
  - cut_list_to_csv: CSV contains all panel names + summary line
  - LLM tool list_maker_templates round-trip: ok=True, templates list
  - LLM tool build_maker_part round-trip: ok=True, panels non-empty
  - LLM tool compute_maker_cut_list round-trip: ok=True, sheets_used >= 1
  - LLM tool export_cut_list_csv round-trip: ok=True, csv contains "Part name"
  - LLM tool build_maker_part: unknown template → error, not raise
  - Determinism: same inputs produce identical output

Pure-Python, hermetic — no database, no OCCT, no ProjectCtx required.

Author: imranparuk
"""

from __future__ import annotations

import asyncio
import json
import math

import pytest

from kerf_cad_core.simple_parametric.templates import (
    build_part,
    list_templates,
    TEMPLATES,
    PanelDef,
)
from kerf_cad_core.simple_parametric.cut_list import (
    compute_cut_list,
    compute_flat_pack_layout,
    cut_list_to_csv,
    CutListResult,
    CutPiece,
)
from kerf_cad_core.simple_parametric.tools import (
    run_list_maker_templates,
    run_build_maker_part,
    run_compute_maker_cut_list,
    run_export_cut_list_csv,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


class _NullCtx:
    pass


_ctx = _NullCtx()


def _ok(json_str: str) -> dict:
    d = json.loads(json_str)
    assert d.get("ok") is True, f"Expected ok payload; got: {json_str[:300]}"
    return d


def _err(json_str: str) -> dict:
    d = json.loads(json_str)
    assert "error" in d or d.get("ok") is False, f"Expected error payload; got: {json_str[:300]}"
    return d


def _args(**kwargs) -> bytes:
    return json.dumps(kwargs).encode()


# ---------------------------------------------------------------------------
# Template listing
# ---------------------------------------------------------------------------

def test_list_templates_returns_all_known():
    templates = list_templates()
    keys = {t["key"] for t in templates}
    assert "box" in keys
    assert "lid_box" in keys
    assert "enclosure" in keys
    assert "shelf_bracket" in keys
    assert "t_slot_frame" in keys
    assert len(templates) >= 5


def test_list_templates_have_required_fields():
    for tmpl in list_templates():
        assert "key" in tmpl
        assert "description" in tmpl
        assert "params" in tmpl
        for _pname, pspec in tmpl["params"].items():
            assert "default" in pspec
            assert "min" in pspec
            assert "max" in pspec


# ---------------------------------------------------------------------------
# Template: box
# ---------------------------------------------------------------------------

BOX_PARAMS = {"width": 300.0, "depth": 200.0, "height": 150.0, "thickness": 9.0}


def test_box_panel_count():
    part = build_part("box", BOX_PARAMS)
    assert len(part.panels) == 5


def test_box_bottom_dimensions():
    part = build_part("box", BOX_PARAMS)
    bottom = next(p for p in part.panels if p.name == "bottom")
    assert bottom.w == pytest.approx(300.0)
    assert bottom.h == pytest.approx(200.0)
    assert bottom.thickness == pytest.approx(9.0)
    assert bottom.qty == 1


def test_box_front_back_dimensions():
    """Front and back panels span full external width, height = (H - T)."""
    W, H, T = 300.0, 150.0, 9.0
    part = build_part("box", BOX_PARAMS)
    front = next(p for p in part.panels if p.name == "front")
    assert front.w == pytest.approx(W)
    assert front.h == pytest.approx(H - T)


def test_box_left_right_dimensions():
    """Left/right panels: width = (D - 2T), height = (H - T)."""
    D, H, T = 200.0, 150.0, 9.0
    part = build_part("box", BOX_PARAMS)
    left = next(p for p in part.panels if p.name == "left")
    assert left.w == pytest.approx(D - 2 * T)
    assert left.h == pytest.approx(H - T)


def test_box_panels_have_positive_dimensions():
    part = build_part("box")
    for p in part.panels:
        assert p.w > 0, f"{p.name} has w <= 0"
        assert p.h > 0 or p.h == 0.0, f"{p.name} has negative h"
        assert p.thickness > 0


def test_box_default_params_work():
    """build_part with no params uses template defaults."""
    part = build_part("box")
    assert len(part.panels) == 5
    assert part.params["thickness"] == pytest.approx(9.0)


def test_box_params_clamped_not_rejected():
    """Out-of-range params are clamped, not rejected."""
    part = build_part("box", {"thickness": 99999.0, "width": -5.0})
    specs = TEMPLATES["box"]["param_specs"]
    assert part.params["thickness"] == pytest.approx(specs["thickness"][2])  # max
    assert part.params["width"]     == pytest.approx(specs["width"][1])       # min


def test_box_jscad_non_empty():
    part = build_part("box", BOX_PARAMS)
    assert len(part.jscad) > 50
    assert "@jscad/modeling" in part.jscad


# ---------------------------------------------------------------------------
# Template: lid_box
# ---------------------------------------------------------------------------

def test_lid_box_has_lid_panel():
    W, D = 200.0, 150.0
    part = build_part("lid_box", {"width": W, "depth": D, "height": 100.0, "thickness": 9.0})
    lid = next(p for p in part.panels if p.name == "lid")
    assert lid.w == pytest.approx(W)
    assert lid.h == pytest.approx(D)


def test_lid_box_panel_count():
    part = build_part("lid_box")
    # base panels + lid + lip strips
    assert len(part.panels) >= 6


# ---------------------------------------------------------------------------
# Template: enclosure
# ---------------------------------------------------------------------------

def test_enclosure_has_six_main_panels():
    part = build_part("enclosure", {"width": 150.0, "depth": 100.0, "height": 60.0, "thickness": 3.0})
    names = {p.name for p in part.panels}
    assert "base"  in names
    assert "lid"   in names
    assert "front" in names
    assert "back"  in names
    assert "left"  in names
    assert "right" in names


def test_enclosure_base_lid_equal_footprint():
    W, D = 150.0, 100.0
    part = build_part("enclosure", {"width": W, "depth": D, "height": 60.0, "thickness": 3.0})
    base = next(p for p in part.panels if p.name == "base")
    lid  = next(p for p in part.panels if p.name == "lid")
    assert base.w == pytest.approx(lid.w)
    assert base.h == pytest.approx(lid.h)


# ---------------------------------------------------------------------------
# Template: shelf_bracket
# ---------------------------------------------------------------------------

def test_shelf_bracket_two_panels():
    part = build_part("shelf_bracket")
    assert len(part.panels) == 2
    names = {p.name for p in part.panels}
    assert "wall_plate" in names
    assert "shelf_plate" in names


def test_shelf_bracket_wall_plate_height():
    WH = 180.0
    part = build_part("shelf_bracket", {"wall_h": WH})
    wall = next(p for p in part.panels if p.name == "wall_plate")
    assert wall.h == pytest.approx(WH)


# ---------------------------------------------------------------------------
# Template: t_slot_frame
# ---------------------------------------------------------------------------

def test_t_slot_frame_member_lengths():
    W, H, P = 500.0, 400.0, 20.0
    part = build_part("t_slot_frame", {"width": W, "height": H, "profile_mm": P})
    hor  = next(p for p in part.panels if p.name == "horizontal_member")
    vert = next(p for p in part.panels if p.name == "vertical_member")
    assert hor.w  == pytest.approx(W)
    assert vert.w == pytest.approx(H - 2 * P)


def test_t_slot_frame_qty_frames_multiplies():
    part = build_part("t_slot_frame", {"qty_frames": 2})
    hor = next(p for p in part.panels if p.name == "horizontal_member")
    assert hor.qty == 4  # 2 per frame × 2 frames


# ---------------------------------------------------------------------------
# Unknown template
# ---------------------------------------------------------------------------

def test_unknown_template_raises():
    with pytest.raises(ValueError, match="Unknown template"):
        build_part("nonexistent_template")


# ---------------------------------------------------------------------------
# Cut list: basic correctness
# ---------------------------------------------------------------------------

def _make_panels(*specs) -> list[PanelDef]:
    """Build PanelDef list from (name, w, h, thickness, qty) tuples."""
    return [PanelDef(name=n, w=w, h=h, thickness=t, qty=q) for (n, w, h, t, q) in specs]


def test_cut_list_single_panel_one_sheet():
    panels = _make_panels(("base", 300.0, 200.0, 9.0, 1))
    result = compute_cut_list(panels, sheet_w=600.0, sheet_h=600.0, kerf=0.0, margin=0.0)
    assert result.sheets_used == 1
    assert result.utilization > 0
    assert not result.errors


def test_cut_list_area_correct():
    """Total area == sum of (w × h × qty) for all panels."""
    W1, H1, T, Q1 = 300.0, 200.0, 9.0, 1
    W2, H2,    Q2 = 150.0, 150.0,      2
    panels = _make_panels(
        ("a", W1, H1, T, Q1),
        ("b", W2, H2, T, Q2),
    )
    result = compute_cut_list(panels, sheet_w=1000.0, sheet_h=1000.0)
    expected = W1 * H1 * Q1 + W2 * H2 * Q2
    assert result.total_area_mm2 == pytest.approx(expected, rel=1e-6)


def test_cut_list_box_fits_two_sheets():
    """A standard box (300×200×150, T=9) should fit on ≤2 standard sheets."""
    part = build_part("box", BOX_PARAMS)
    result = compute_cut_list(part.panels, sheet_w=1220.0, sheet_h=2440.0)
    assert result.sheets_used <= 2
    assert not result.errors


def test_cut_list_placement_count_matches_qty():
    panels = _make_panels(
        ("a", 100.0, 80.0, 9.0, 3),
        ("b", 200.0, 50.0, 9.0, 2),
    )
    result = compute_cut_list(panels, sheet_w=1220.0, sheet_h=2440.0, kerf=5.0)
    total_placed = len(result.placements)
    total_qty = sum(p.qty for p in panels)
    # All panels should be placed (no errors expected for small panels on large sheet)
    assert not result.errors
    assert total_placed == total_qty


def test_cut_list_oversized_panel_error():
    """A panel larger than the usable sheet area produces an error, not a crash."""
    huge = _make_panels(("giant", 5000.0, 5000.0, 9.0, 1))
    result = compute_cut_list(huge, sheet_w=600.0, sheet_h=600.0)
    assert len(result.errors) >= 1
    assert "giant" in result.errors[0]


def test_cut_list_zero_kerf_margin_accepted():
    panels = _make_panels(("p", 100.0, 80.0, 9.0, 1))
    result = compute_cut_list(panels, sheet_w=500.0, sheet_h=500.0, kerf=0.0, margin=0.0)
    assert not result.errors
    assert result.sheets_used == 1


def test_cut_list_negative_kerf_clamped():
    panels = _make_panels(("p", 100.0, 80.0, 9.0, 1))
    result = compute_cut_list(panels, sheet_w=500.0, sheet_h=500.0, kerf=-5.0)
    # negative kerf triggers an error note, but still computes
    assert any("kerf" in e.lower() for e in result.errors)
    assert result.sheets_used >= 1


def test_cut_list_utilization_in_range():
    part = build_part("enclosure", {"width": 150.0, "depth": 100.0, "height": 60.0, "thickness": 3.0})
    result = compute_cut_list(part.panels, sheet_w=600.0, sheet_h=400.0)
    if result.sheets_used > 0:
        assert 0.0 < result.utilization <= 1.0


def test_cut_list_rolled_up_qty():
    """When two PanelDef have the same name+size, qty is merged."""
    panels = [
        PanelDef("side", 100.0, 80.0, 9.0, qty=1),
        PanelDef("side", 100.0, 80.0, 9.0, qty=1),
    ]
    result = compute_cut_list(panels, sheet_w=500.0, sheet_h=500.0)
    assert result.pieces[0].qty == 2


# ---------------------------------------------------------------------------
# CSV export
# ---------------------------------------------------------------------------

def test_csv_contains_header_and_panels():
    panels = _make_panels(
        ("bottom", 300.0, 200.0, 9.0, 1),
        ("side",   300.0, 141.0, 9.0, 2),
    )
    result = compute_cut_list(panels, sheet_w=1220.0, sheet_h=2440.0)
    csv = cut_list_to_csv(result)
    assert "Part name" in csv
    assert "bottom" in csv
    assert "side" in csv
    assert "TOTAL" in csv


def test_csv_summary_line_present():
    panels = _make_panels(("p", 200.0, 150.0, 9.0, 2))
    result = compute_cut_list(panels, sheet_w=1220.0, sheet_h=2440.0)
    csv = cut_list_to_csv(result)
    assert "Sheets required" in csv


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------

def test_determinism_templates():
    p1 = build_part("box", BOX_PARAMS)
    p2 = build_part("box", BOX_PARAMS)
    assert p1.to_dict() == p2.to_dict()


def test_determinism_cut_list():
    part = build_part("box", BOX_PARAMS)
    r1 = compute_cut_list(part.panels, sheet_w=1220.0, sheet_h=2440.0)
    r2 = compute_cut_list(part.panels, sheet_w=1220.0, sheet_h=2440.0)
    assert r1.to_dict() == r2.to_dict()


# ---------------------------------------------------------------------------
# LLM tool wrappers (round-trip JSON)
# ---------------------------------------------------------------------------

def test_tool_list_templates_ok():
    resp = _run(run_list_maker_templates(_ctx, b"{}"))
    d = _ok(resp)
    assert d["count"] >= 5
    assert isinstance(d["templates"], list)


def test_tool_build_part_box_ok():
    resp = _run(run_build_maker_part(
        _ctx,
        _args(template="box", params={"width": 300, "depth": 200, "height": 150, "thickness": 9}),
    ))
    d = _ok(resp)
    assert d["template"] == "box"
    assert len(d["panels"]) == 5
    assert "@jscad/modeling" in d["jscad"]


def test_tool_build_part_unknown_template():
    resp = _run(run_build_maker_part(_ctx, _args(template="does_not_exist")))
    _err(resp)


def test_tool_build_part_missing_template_arg():
    resp = _run(run_build_maker_part(_ctx, _args(params={"width": 300})))
    _err(resp)


def test_tool_compute_cut_list_box():
    # First build the part
    part = build_part("box", BOX_PARAMS)
    panels_raw = part.to_dict()["panels"]

    resp = _run(run_compute_maker_cut_list(
        _ctx,
        _args(
            panels=panels_raw,
            sheet_w=1220.0,
            sheet_h=2440.0,
            material="9mm plywood",
            kerf=3.0,
            margin=10.0,
        ),
    ))
    d = _ok(resp)
    assert d["sheets_used"] >= 1
    assert d["total_area_mm2"] > 0
    assert isinstance(d["placements"], list)
    assert len(d["placements"]) == len(panels_raw)


def test_tool_compute_cut_list_enclosure():
    part = build_part("enclosure", {"width": 150.0, "depth": 100.0, "height": 60.0, "thickness": 3.0})
    panels_raw = part.to_dict()["panels"]

    resp = _run(run_compute_maker_cut_list(
        _ctx,
        _args(panels=panels_raw, sheet_w=600.0, sheet_h=400.0, material="3mm acrylic", kerf=0.2, margin=5.0),
    ))
    d = _ok(resp)
    assert d["sheets_used"] >= 1


def test_tool_export_csv_ok():
    part = build_part("box", BOX_PARAMS)
    panels_raw = part.to_dict()["panels"]

    # Get cut list
    cl_resp = _run(run_compute_maker_cut_list(_ctx, _args(panels=panels_raw)))
    cl = _ok(cl_resp)

    # Export CSV
    csv_resp = _run(run_export_cut_list_csv(_ctx, _args(cut_list=cl)))
    d = _ok(csv_resp)
    assert "Part name" in d["csv"]
    assert "bottom" in d["csv"]
    assert d["line_count"] > 0


def test_tool_compute_cut_list_bad_panels():
    resp = _run(run_compute_maker_cut_list(_ctx, _args(panels="not_a_list")))
    _err(resp)


def test_tool_compute_cut_list_missing_panels():
    resp = _run(run_compute_maker_cut_list(_ctx, _args(sheet_w=600)))
    _err(resp)


# ---------------------------------------------------------------------------
# End-to-end: full maker flow
# ---------------------------------------------------------------------------

def test_e2e_maker_flow_box():
    """
    Full end-to-end: list templates → build box → compute cut list → export CSV.
    Verifies the DoD: maker can go from parametric prompt to a cut list.
    """
    # Step 1: discover templates
    templates = list_templates()
    assert any(t["key"] == "box" for t in templates)

    # Step 2: build part
    part = build_part("box", {"width": 300.0, "depth": 200.0, "height": 150.0, "thickness": 9.0})
    assert len(part.panels) == 5

    # Step 3: compute cut list
    result = compute_cut_list(
        part.panels,
        material="9mm plywood",
        sheet_w=1220.0,
        sheet_h=2440.0,
        kerf=3.0,
        margin=10.0,
    )
    assert result.sheets_used >= 1
    assert result.total_area_mm2 > 0
    assert len(result.placements) == 5
    assert not result.errors

    # Step 4: export CSV
    csv = cut_list_to_csv(result)
    assert "bottom" in csv
    assert "9mm plywood" in csv
    assert "TOTAL" in csv


def test_e2e_maker_flow_enclosure():
    """
    Full end-to-end for the enclosure template — the electronics persona path.
    """
    part = build_part("enclosure", {"width": 150.0, "depth": 100.0, "height": 60.0, "thickness": 3.0})

    result = compute_cut_list(
        part.panels,
        material="3mm acrylic",
        sheet_w=600.0,
        sheet_h=400.0,
        kerf=0.2,
        margin=5.0,
    )
    assert result.sheets_used >= 1
    # All 6 main panels should be placed
    assert len(result.placements) >= 6
    csv = cut_list_to_csv(result)
    assert "base" in csv
    assert "lid" in csv
