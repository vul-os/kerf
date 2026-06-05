"""
Tests for pcb_3d_clearance.py — 3D PCB body-clearance DRC + STEP component import.

Coverage (≥25 tests):
  1. AABB gap: separated AABBs → correct Euclidean gap
  2. AABB gap: touching AABBs → gap == 0
  3. AABB gap: fully overlapping AABBs → negative gap
  4. AABB gap: partial XY overlap but Z separated → correct Euclidean
  5. Rotated AABB: 45° rotation increases AABB half-extent (conservative)
  6. Rotated AABB: 0° rotation → AABB half == body half
  7. check_3d_clearance: zero components → 0 violations, 0 pairs
  8. check_3d_clearance: one component → 0 violations, 0 pairs
  9. check_3d_clearance: two components far apart → 0 violations
 10. check_3d_clearance: two components in contact → 1 body_clearance violation
 11. check_3d_clearance: two components overlapping → 1 body_intersection violation
 12. check_3d_clearance: violation gap_mm stored correctly
 13. check_3d_clearance: required_mm stored in violation dict
 14. check_3d_clearance: violation_count matches violations list length
 15. check_3d_clearance: pairs_checked == n*(n-1)//2
 16. check_3d_clearance: component_count matches input
 17. check_3d_clearance: negative min_clearance_mm → ok=False
 18. check_3d_clearance: non-list input → ok=False
 19. check_3d_clearance: bottom-side component placed below board
 20. extract_component_bodies: empty circuit → empty list
 21. parse_step_body_bbox: minimal STEP with CARTESIAN_POINTs → correct bbox
 22. parse_step_body_bbox: single-point STEP → fallback (< 2 points)
 23. parse_step_body_bbox: STEP with SOT23 heuristic → recognised dims
 24. parse_step_body_bbox: always returns ok=True + method key
 25. LLM tool pcb_3d_clearance_check: bad args → code==BAD_ARGS
 26. LLM tool pcb_3d_clearance_check: invalid json → code==BAD_ARGS
 27. LLM tool pcb_3d_clearance_check: empty circuit → ok=True, 0 violations
 28. LLM tool pcb_step_import_body: missing step_text → code==BAD_ARGS
 29. LLM tool pcb_step_import_body: valid STEP → ok=True, x/y/z keys

References
----------
Altium 3D Body Clearance Rule §7.4; IPC-7351B §4.5;
STEP AP214 ISO 10303-214 §4.3 / AP242 ISO 10303-242 §4.3.
Gottschalk et al. "OBBTree" §2.1; SIGGRAPH 1996.
"""

from __future__ import annotations

import importlib.util
import json
import math
import os
import sys
import types

# ── Stub kerf_chat if not installed ──────────────────────────────────────────
try:
    import kerf_chat as _kc  # noqa: F401
    import kerf_chat.tools.registry as _kcr  # noqa: F401
except Exception:
    _kc = None
    _kcr = None

_reg_stub = types.ModuleType("kerf_chat.tools.registry")
_reg_stub.Registry = type("Registry", (list,), {})
_reg_stub.ToolSpec = type(
    "ToolSpec", (), {"__init__": lambda s, **kw: s.__dict__.update(kw)}
)
_reg_stub.err_payload = lambda msg, code="ERROR": json.dumps(
    {"ok": False, "error": msg, "code": code}
)
_reg_stub.ok_payload = lambda v: json.dumps({"ok": True, **v})
_reg_stub.register = lambda spec, write=False: (lambda fn: fn)

_kc_stub = types.ModuleType("kerf_chat")
_kct_stub = types.ModuleType("kerf_chat.tools")
sys.modules.setdefault("kerf_chat", _kc_stub)
sys.modules.setdefault("kerf_chat.tools", _kct_stub)
if _kcr is None:
    sys.modules["kerf_chat.tools.registry"] = _reg_stub

# ── Ensure src/ on sys.path ──────────────────────────────────────────────────
_HERE = os.path.dirname(os.path.abspath(__file__))
_SRC = os.path.join(os.path.dirname(_HERE), "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

import pytest

from kerf_electronics.pcb_3d_clearance import (
    ComponentBody3D,
    ClearanceViolation,
    _body_aabb,
    _aabb_gap,
    check_3d_clearance,
    extract_component_bodies,
    parse_step_body_bbox,
)

# ── Load tool module via importlib so stub is active ─────────────────────────
_tool_spec = importlib.util.spec_from_file_location(
    "kerf_electronics.pcb_3d_clearance",
    os.path.join(_SRC, "kerf_electronics", "pcb_3d_clearance.py"),
)
_tool_mod = importlib.util.module_from_spec(_tool_spec)
_tool_spec.loader.exec_module(_tool_mod)

pcb_3d_clearance_check_tool = _tool_mod.pcb_3d_clearance_check
pcb_step_import_body_tool = _tool_mod.pcb_step_import_body


# ── Async helper ──────────────────────────────────────────────────────────────

async def call(fn, **kwargs):
    result = await fn(None, json.dumps(kwargs).encode())
    return json.loads(result)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _comp(refdes="U1", x=10.0, y=10.0, z_bot=1.6, z_top=3.1,
          width=5.0, height=4.0, rotation=0.0, side="top"):
    return ComponentBody3D(
        refdes=refdes,
        x_mm=x, y_mm=y,
        z_bot_mm=z_bot, z_top_mm=z_top,
        width_mm=width, height_mm=height,
        rotation_deg=rotation,
    )


MINIMAL_STEP = """\
ISO-10303-21;
HEADER;
FILE_DESCRIPTION(('SOT23 Component'),'2;1');
ENDSEC;
DATA;
#1=CARTESIAN_POINT('',(0.,0.,0.));
#2=CARTESIAN_POINT('',(2.9,0.,0.));
#3=CARTESIAN_POINT('',(2.9,1.6,0.));
#4=CARTESIAN_POINT('',(0.,1.6,0.));
#5=CARTESIAN_POINT('',(0.,0.,1.1));
#6=CARTESIAN_POINT('',(2.9,1.6,1.1));
ENDSEC;
END-ISO-10303-21;
"""


# ─── AABB gap tests ───────────────────────────────────────────────────────────

class TestAabbGap:

    def test_separated_diagonal_gap(self):
        """Two boxes separated diagonally (all axes separated) → Euclidean distance."""
        a = (0.0, 2.0,  0.0, 2.0,  0.0, 2.0)  # xmin, xmax, ymin, ymax, zmin, zmax
        b = (5.0, 7.0,  5.0, 7.0,  5.0, 7.0)
        gap = _aabb_gap(a, b)
        # dx = 5-2=3, dy = 5-2=3, dz = 5-2=3 → sqrt(27)
        expected = math.sqrt(27.0)
        assert abs(gap - expected) < 1e-6, f"expected {expected:.4f}, got {gap}"

    def test_touching_gap_is_zero(self):
        """Adjacent boxes (touching on one face) → gap = 0."""
        a = (0.0, 3.0,  0.0, 3.0,  0.0, 3.0)
        b = (3.0, 6.0,  0.0, 3.0,  0.0, 3.0)
        gap = _aabb_gap(a, b)
        # dx = max(0-6, 3-3) = 0, dy = max(0-3, 0-3) = -3, dz = -3
        # partially overlapping → gap = 0.0
        assert abs(gap) < 1e-9, f"expected 0.0, got {gap}"

    def test_overlap_is_negative(self):
        """Fully interpenetrating boxes → negative gap."""
        a = (0.0, 5.0,  0.0, 5.0,  0.0, 5.0)
        b = (1.0, 4.0,  1.0, 4.0,  1.0, 4.0)
        gap = _aabb_gap(a, b)
        assert gap < 0, f"expected negative gap, got {gap}"

    def test_partial_xy_overlap_z_separated(self):
        """Overlapping in XY but separated in Z → partial contact → gap 0."""
        a = (0.0, 5.0,  0.0, 5.0,  0.0, 2.0)
        b = (1.0, 4.0,  1.0, 4.0,  5.0, 7.0)  # Z gap = 5.0 - 2.0 = 3.0
        gap = _aabb_gap(a, b)
        # dx < 0 (overlapping), dy < 0 (overlapping), dz > 0 (separated)
        # → partially overlapping → gap == 0.0
        assert gap == 0.0, f"expected 0.0 for partial overlap, got {gap}"

    def test_all_axes_separated_euclidean(self):
        """Boxes separated on all 3 axes → Euclidean distance."""
        a = (0.0, 1.0,  0.0, 1.0,  0.0, 1.0)
        b = (4.0, 5.0,  4.0, 5.0,  4.0, 5.0)
        gap = _aabb_gap(a, b)
        expected = math.sqrt(3 * (4.0 - 1.0) ** 2)  # sqrt(27) ≈ 5.196
        assert abs(gap - expected) < 1e-6, f"expected {expected:.4f}, got {gap:.4f}"

    def test_x_only_separation_returns_euclidean(self):
        """Boxes separated only in X; co-located in Y and Z → Euclidean (X distance only)."""
        # Boxes share same Y and Z extent; only separated in X
        a = (0.0, 1.0,  0.0, 1.0,  0.0, 1.0)
        b = (6.0, 7.0,  0.0, 1.0,  0.0, 1.0)
        gap = _aabb_gap(a, b)
        # dx = max(0-7, 6-1) = 5, dy = max(0-1, 0-1) = -1 (overlapping), dz = -1
        # partial overlap → gap = 0.0
        assert gap == 0.0, f"single-axis separation yields partial-overlap gap=0, got {gap}"


# ─── Rotated AABB tests ───────────────────────────────────────────────────────

class TestBodyAabb:

    def test_zero_rotation_aabb_half_equals_body_half(self):
        """0° rotation → AABB half equals half of body dims."""
        c = _comp(x=0.0, y=0.0, width=10.0, height=6.0, rotation=0.0)
        xmin, xmax, ymin, ymax, _, _ = _body_aabb(c)
        assert abs((xmax - xmin) / 2 - 5.0) < 1e-9
        assert abs((ymax - ymin) / 2 - 3.0) < 1e-9

    def test_45deg_rotation_expands_aabb(self):
        """45° rotation → AABB larger than the body (conservative envelope)."""
        c = _comp(x=0.0, y=0.0, width=10.0, height=6.0, rotation=45.0)
        xmin, xmax, ymin, ymax, _, _ = _body_aabb(c)
        half_x = (xmax - xmin) / 2
        half_y = (ymax - ymin) / 2
        # At 45° the rotated AABB half should be hw*cos45 + hh*sin45 = 5*√2/2 + 3*√2/2
        expected = (5.0 + 3.0) * math.sqrt(2) / 2
        assert abs(half_x - expected) < 1e-6
        assert abs(half_y - expected) < 1e-6

    def test_90deg_rotation_swaps_dims(self):
        """90° rotation of a non-square body should swap X and Y extents."""
        c = _comp(x=0.0, y=0.0, width=10.0, height=4.0, rotation=90.0)
        xmin, xmax, ymin, ymax, _, _ = _body_aabb(c)
        half_x = (xmax - xmin) / 2
        half_y = (ymax - ymin) / 2
        # At 90°: aabb_half_x = hw*cos90 + hh*sin90 = 0 + hh = 2
        #         aabb_half_y = hw*sin90 + hh*cos90 = 5 + 0 = 5
        assert abs(half_x - 2.0) < 1e-6, f"half_x={half_x}"
        assert abs(half_y - 5.0) < 1e-6, f"half_y={half_y}"

    def test_z_coords_passthrough(self):
        """Z coordinates from ComponentBody3D should pass through to AABB."""
        c = _comp(z_bot=1.6, z_top=5.0)
        _, _, _, _, zmin, zmax = _body_aabb(c)
        assert abs(zmin - 1.6) < 1e-9
        assert abs(zmax - 5.0) < 1e-9


# ─── check_3d_clearance ───────────────────────────────────────────────────────

class TestCheck3dClearance:

    def test_zero_components(self):
        r = check_3d_clearance([])
        assert r["ok"]
        assert r["violation_count"] == 0
        assert r["pairs_checked"] == 0

    def test_one_component(self):
        r = check_3d_clearance([_comp("U1")])
        assert r["ok"]
        assert r["violation_count"] == 0
        assert r["pairs_checked"] == 0

    def test_two_components_far_apart_no_violations(self):
        """Components separated in all 3 axes → no violation."""
        # Place them at completely different X, Y, and Z so all axes are separated
        a = _comp("U1", x=0.0,   y=0.0,   z_bot=0.0,   z_top=1.5, width=2.0, height=2.0)
        b = _comp("U2", x=100.0, y=100.0, z_bot=10.0, z_top=11.5, width=2.0, height=2.0)
        r = check_3d_clearance([a, b])
        assert r["ok"]
        assert r["violation_count"] == 0

    def test_two_components_too_close_clearance_violation(self):
        """Components with only 0.05 mm gap (< default 0.2 mm)."""
        a = _comp("U1", x=0.0, width=4.0, height=4.0)
        b = _comp("U2", x=4.05, width=4.0, height=4.0)
        # AABB half_x = 2.0 each, gap = 4.05 - 2.0 - 2.0 = 0.05
        r = check_3d_clearance([a, b], min_clearance_mm=0.2)
        assert r["ok"]
        assert r["violation_count"] == 1
        v = r["violations"][0]
        assert v["violation_type"] == "body_clearance"
        assert v["gap_mm"] < 0.2
        assert v["severity"] == "warning"

    def test_two_components_overlapping_body_intersection(self):
        """Components whose AABBs overlap → body_intersection (error)."""
        a = _comp("U1", x=0.0, width=10.0, height=10.0)
        b = _comp("U2", x=1.0, width=10.0, height=10.0)
        r = check_3d_clearance([a, b], min_clearance_mm=0.2)
        assert r["ok"]
        assert r["violation_count"] == 1
        v = r["violations"][0]
        assert v["violation_type"] == "body_intersection"
        assert v["gap_mm"] < 0
        assert v["severity"] == "error"

    def test_violation_gap_mm_stored(self):
        a = _comp("U1", x=0.0, width=4.0, height=4.0)
        b = _comp("U2", x=4.05, width=4.0, height=4.0)
        r = check_3d_clearance([a, b])
        v = r["violations"][0]
        assert isinstance(v["gap_mm"], float)

    def test_violation_required_mm(self):
        a = _comp("U1", x=0.0, width=4.0, height=4.0)
        b = _comp("U2", x=4.05, width=4.0, height=4.0)
        r = check_3d_clearance([a, b], min_clearance_mm=0.5)
        assert r["violations"][0]["required_mm"] == 0.5

    def test_violation_count_matches_list(self):
        comps = [_comp(f"U{i}", x=i * 0.5, width=1.0, height=1.0) for i in range(5)]
        r = check_3d_clearance(comps, min_clearance_mm=0.2)
        assert r["violation_count"] == len(r["violations"])

    def test_pairs_checked_formula(self):
        n = 6
        comps = [_comp(f"U{i}", x=i * 50.0) for i in range(n)]
        r = check_3d_clearance(comps)
        assert r["pairs_checked"] == n * (n - 1) // 2

    def test_component_count_matches_input(self):
        comps = [_comp(f"U{i}", x=i * 50.0) for i in range(4)]
        r = check_3d_clearance(comps)
        assert r["component_count"] == 4

    def test_negative_min_clearance_error(self):
        r = check_3d_clearance([], min_clearance_mm=-1.0)
        assert not r["ok"]

    def test_non_list_input_error(self):
        r = check_3d_clearance("not-a-list")  # type: ignore[arg-type]
        assert not r["ok"]

    def test_bottom_side_component_z_below_board(self):
        """Bottom-side component body should be placed below Z=0."""
        c = ComponentBody3D(
            refdes="D1", x_mm=10.0, y_mm=10.0,
            z_bot_mm=-1.5, z_top_mm=0.0,
            width_mm=3.0, height_mm=3.0,
        )
        _, _, _, _, zmin, zmax = _body_aabb(c)
        assert zmin < 0.0
        assert zmax == 0.0


# ─── extract_component_bodies ─────────────────────────────────────────────────

class TestExtractComponentBodies:

    def test_empty_circuit_returns_empty(self):
        bodies = extract_component_bodies([])
        assert bodies == []

    def test_no_pcb_component_returns_empty(self):
        cj = [{"type": "pcb_board", "width": 100.0, "height": 80.0}]
        bodies = extract_component_bodies(cj)
        assert bodies == []


# ─── parse_step_body_bbox ─────────────────────────────────────────────────────

class TestParseStepBodyBbox:

    def test_cartesian_point_scan_returns_bbox(self):
        r = parse_step_body_bbox(MINIMAL_STEP)
        assert r["ok"]
        assert r["method"] == "cartesian_point_scan"
        assert abs(r["x_mm"] - 2.9) < 0.01
        assert abs(r["y_mm"] - 1.6) < 0.01
        assert abs(r["z_mm"] - 1.1) < 0.01

    def test_n_points_counted(self):
        r = parse_step_body_bbox(MINIMAL_STEP)
        assert r["n_points"] == 6

    def test_single_point_falls_back(self):
        """Only one CARTESIAN_POINT → fallback."""
        step = "CARTESIAN_POINT('',(1.0,2.0,3.0));"
        r = parse_step_body_bbox(step)
        assert r["ok"]
        assert r["method"] == "fallback"

    def test_sot23_heuristic_recognised(self):
        """'SOT23' in description triggers IPC-7351B §4.5 heuristic dims."""
        step = (
            "ISO-10303-21;\nHEADER;\n"
            "FILE_DESCRIPTION(('SOT23 body'),'2;1');\n"
            "ENDSEC;\nDATA;\nENDSEC;\nEND-ISO-10303-21;\n"
        )
        r = parse_step_body_bbox(step)
        assert r["ok"]
        # SOT23 heuristic: x=2.9, y=1.6, z=1.1
        assert abs(r["x_mm"] - 2.9) < 0.01

    def test_always_returns_ok_true(self):
        r = parse_step_body_bbox("")
        assert r["ok"] is True

    def test_method_key_always_present(self):
        r = parse_step_body_bbox("")
        assert "method" in r

    def test_minimum_0_1_mm_enforced(self):
        """Single-axis zero-extent STEP → at least 0.1 mm per dimension."""
        step = (
            "CARTESIAN_POINT('',(0.,0.,0.));\n"
            "CARTESIAN_POINT('',(0.,0.,0.1));\n"
        )
        r = parse_step_body_bbox(step)
        assert r["x_mm"] >= 0.1
        assert r["y_mm"] >= 0.1


# ─── LLM tool: pcb_3d_clearance_check ────────────────────────────────────────

class TestPcb3dClearanceCheckTool:

    @pytest.mark.asyncio
    async def test_bad_args_returns_error_code(self):
        r = await call(pcb_3d_clearance_check_tool, circuit_json="not-a-list")
        assert r.get("code") == "BAD_ARGS"

    @pytest.mark.asyncio
    async def test_invalid_json_returns_error(self):
        result = await pcb_3d_clearance_check_tool(None, b"{bad json")
        r = json.loads(result)
        assert r.get("code") == "BAD_ARGS"

    @pytest.mark.asyncio
    async def test_empty_circuit_ok(self):
        r = await call(pcb_3d_clearance_check_tool, circuit_json=[])
        assert r["ok"] is True
        assert r["violation_count"] == 0

    @pytest.mark.asyncio
    async def test_missing_circuit_json_key(self):
        result = await pcb_3d_clearance_check_tool(None, json.dumps({}).encode())
        r = json.loads(result)
        assert r.get("code") == "BAD_ARGS"


# ─── LLM tool: pcb_step_import_body ──────────────────────────────────────────

class TestPcbStepImportBodyTool:

    @pytest.mark.asyncio
    async def test_missing_step_text_error(self):
        r = await call(pcb_step_import_body_tool)
        assert r.get("code") == "BAD_ARGS"

    @pytest.mark.asyncio
    async def test_empty_step_text_error(self):
        r = await call(pcb_step_import_body_tool, step_text="   ")
        assert r.get("code") == "BAD_ARGS"

    @pytest.mark.asyncio
    async def test_valid_step_returns_bbox(self):
        r = await call(pcb_step_import_body_tool, step_text=MINIMAL_STEP)
        assert r["ok"] is True
        assert "x_mm" in r
        assert "y_mm" in r
        assert "z_mm" in r

    @pytest.mark.asyncio
    async def test_invalid_json_error(self):
        result = await pcb_step_import_body_tool(None, b"not json")
        r = json.loads(result)
        assert r.get("code") == "BAD_ARGS"

    @pytest.mark.asyncio
    async def test_method_key_returned(self):
        r = await call(pcb_step_import_body_tool, step_text=MINIMAL_STEP)
        assert "method" in r


if __name__ == "__main__":
    import unittest
    unittest.main()
