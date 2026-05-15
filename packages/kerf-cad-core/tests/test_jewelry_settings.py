"""
Tests for kerf_cad_core.jewelry.settings — prong head, bezel, channel, pavé,
tension, flush, halo, three-stone, cluster.

Structure
---------
Pure-Python tests (always run):
  - ToolSpec schema assertions (names, required fields, enum values).
  - Input validation: bad values rejected with code='BAD_ARGS'.
  - Node shape: node dicts stored in the feature JSON match the spec.
  - Geometry math: _compute_pave_grid, derived hints, seat positions,
    cluster positions, three-stone offsets, halo radius, tension band spread,
    flush opening diameter.

OCC-gated tests:
  Skipped when pythonocc / OCC imports are not available — follows the same
  skip pattern used in test_cad_core.py and test_quad_remesh.py.
"""

from __future__ import annotations

import asyncio
import json
import math
import uuid

import pytest

# ---------------------------------------------------------------------------
# OCC skip guard (matches the pattern in test_cad_core.py)
# ---------------------------------------------------------------------------

try:
    from OCC.Core.BRepPrimAPI import BRepPrimAPI_MakeCylinder  # type: ignore
    _OCC_AVAILABLE = True
except ImportError:
    _OCC_AVAILABLE = False

skip_no_occ = pytest.mark.skipif(
    not _OCC_AVAILABLE,
    reason="pythonocc not installed — OCC-dependent tests skipped",
)

# ---------------------------------------------------------------------------
# Imports under test
# ---------------------------------------------------------------------------

from kerf_cad_core.jewelry.settings import (
    # ToolSpec objects
    jewelry_prong_head_spec,
    jewelry_bezel_spec,
    jewelry_channel_spec,
    jewelry_pave_spec,
    jewelry_tension_spec,
    jewelry_flush_spec,
    # Runners
    run_jewelry_create_prong_head,
    run_jewelry_create_bezel,
    run_jewelry_create_channel,
    run_jewelry_pave_array,
    run_jewelry_create_tension,
    run_jewelry_create_flush,
    # Pure-Python helpers
    build_prong_head_node,
    build_bezel_node,
    build_channel_node,
    build_pave_array_node,
    build_tension_node,
    build_flush_node,
    _compute_pave_grid,
)

# ---------------------------------------------------------------------------
# Helpers — in-memory fake context (same as test_feature_boolean.py pattern)
# ---------------------------------------------------------------------------

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
            store["content"] = args[0]

    from kerf_core.utils.context import ProjectCtx  # type: ignore[import]

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
    return asyncio.new_event_loop().run_until_complete(coro)


def call_tool(runner, ctx, file_id, **kwargs):
    args = {"file_id": str(file_id), **kwargs}
    raw = run_sync(runner(ctx, json.dumps(args).encode()))
    return json.loads(raw)


def get_last_node(store):
    doc = json.loads(store["content"])
    return doc["features"][-1]


# ============================================================================
# ToolSpec schema tests
# ============================================================================

class TestProngHeadSpec:
    def test_name(self):
        assert jewelry_prong_head_spec.name == "jewelry_create_prong_head"

    def test_required_fields(self):
        req = jewelry_prong_head_spec.input_schema["required"]
        assert "file_id" in req
        assert "stone_diameter" in req
        assert "prong_count" in req
        assert "prong_wire_diameter" in req
        assert "prong_height" in req

    def test_prong_count_enum(self):
        props = jewelry_prong_head_spec.input_schema["properties"]
        enum = props["prong_count"].get("enum", [])
        assert set(enum) == {4, 6}

    def test_head_style_enum(self):
        props = jewelry_prong_head_spec.input_schema["properties"]
        enum = props["head_style"].get("enum", [])
        assert set(enum) == {"standard", "basket", "trellis", "cathedral"}

    def test_optional_fields_not_required(self):
        req = jewelry_prong_head_spec.input_schema["required"]
        assert "head_style" not in req
        assert "basket_rail_count" not in req
        assert "seat_angle_deg" not in req
        assert "id" not in req


class TestBezzelSpec:
    def test_name(self):
        assert jewelry_bezel_spec.name == "jewelry_create_bezel"

    def test_required_fields(self):
        req = jewelry_bezel_spec.input_schema["required"]
        for f in ["file_id", "stone_diameter", "wall_thickness", "bezel_height", "bearing_ledge_height"]:
            assert f in req

    def test_bezel_style_enum(self):
        props = jewelry_bezel_spec.input_schema["properties"]
        enum = props["bezel_style"].get("enum", [])
        assert set(enum) == {"full", "partial", "collet", "tapered"}


class TestChannelSpec:
    def test_name(self):
        assert jewelry_channel_spec.name == "jewelry_create_channel"

    def test_required_fields(self):
        req = jewelry_channel_spec.input_schema["required"]
        for f in ["file_id", "stone_diameter", "stone_count", "stone_spacing", "rail_height", "rail_thickness", "floor_thickness"]:
            assert f in req


class TestPaveSpec:
    def test_name(self):
        assert jewelry_pave_spec.name == "jewelry_pave_array"

    def test_required_fields(self):
        req = jewelry_pave_spec.input_schema["required"]
        for f in ["file_id", "region_width", "region_height", "stone_diameter", "stone_spacing", "edge_margin"]:
            assert f in req

    def test_optional_fields_not_required(self):
        req = jewelry_pave_spec.input_schema["required"]
        assert "surface_normal" not in req
        assert "surface_origin" not in req
        assert "id" not in req


# ============================================================================
# Prong head — node shape + geometry math
# ============================================================================

class TestProngHeadGeometry:
    def test_head_outer_diameter(self):
        node = build_prong_head_node(
            node_id="test-1",
            stone_diameter=6.5,
            prong_count=6,
            prong_wire_diameter=1.0,
            prong_height=2.0,
            head_style="standard",
            basket_rail_count=0,
            seat_angle_deg=15.0,
        )
        expected_outer = 6.5 + 2 * 1.0
        assert math.isclose(node["_head_outer_diameter"], expected_outer, rel_tol=1e-5)

    def test_seat_depth_positive(self):
        node = build_prong_head_node(
            node_id="test-1",
            stone_diameter=5.0,
            prong_count=4,
            prong_wire_diameter=0.9,
            prong_height=1.5,
            head_style="basket",
            basket_rail_count=1,
            seat_angle_deg=20.0,
        )
        assert node["_seat_depth"] > 0

    def test_node_op(self):
        node = build_prong_head_node(
            node_id="prong-1",
            stone_diameter=4.0,
            prong_count=4,
            prong_wire_diameter=0.8,
            prong_height=1.2,
            head_style="trellis",
            basket_rail_count=2,
            seat_angle_deg=15.0,
        )
        assert node["op"] == "jewelry_prong_head"
        assert node["id"] == "prong-1"
        assert node["prong_count"] == 4
        assert node["head_style"] == "trellis"

    def test_cathedral_style_stored(self):
        node = build_prong_head_node(
            node_id="prong-2",
            stone_diameter=7.0,
            prong_count=6,
            prong_wire_diameter=1.2,
            prong_height=2.5,
            head_style="cathedral",
            basket_rail_count=0,
            seat_angle_deg=12.0,
        )
        assert node["head_style"] == "cathedral"


# ============================================================================
# Prong head — LLM tool runner
# ============================================================================

class TestProngHeadRunner:
    def test_success_4_prong(self):
        ctx, store, fid = make_ctx()
        result = call_tool(
            run_jewelry_create_prong_head, ctx, fid,
            stone_diameter=6.5,
            prong_count=4,
            prong_wire_diameter=1.0,
            prong_height=2.0,
        )
        assert result.get("error") is None, result
        assert result["op"] == "jewelry_prong_head"
        assert result["prong_count"] == 4

    def test_success_6_prong_basket(self):
        ctx, store, fid = make_ctx()
        result = call_tool(
            run_jewelry_create_prong_head, ctx, fid,
            stone_diameter=6.5,
            prong_count=6,
            prong_wire_diameter=1.0,
            prong_height=2.0,
            head_style="basket",
            basket_rail_count=2,
        )
        assert result.get("error") is None
        node = get_last_node(store)
        assert node["head_style"] == "basket"
        assert node["basket_rail_count"] == 2

    def test_node_id_auto_generated(self):
        ctx, store, fid = make_ctx()
        call_tool(
            run_jewelry_create_prong_head, ctx, fid,
            stone_diameter=5.0, prong_count=4,
            prong_wire_diameter=0.9, prong_height=1.5,
        )
        node = get_last_node(store)
        assert node["id"].startswith("jewelry_prong_head-")

    def test_explicit_node_id(self):
        ctx, store, fid = make_ctx()
        call_tool(
            run_jewelry_create_prong_head, ctx, fid,
            stone_diameter=5.0, prong_count=4,
            prong_wire_diameter=0.9, prong_height=1.5,
            id="my-prong-head",
        )
        node = get_last_node(store)
        assert node["id"] == "my-prong-head"

    def test_invalid_prong_count_rejected(self):
        ctx, _, fid = make_ctx()
        result = call_tool(
            run_jewelry_create_prong_head, ctx, fid,
            stone_diameter=6.5,
            prong_count=3,
            prong_wire_diameter=1.0,
            prong_height=2.0,
        )
        assert result.get("code") == "BAD_ARGS"
        assert "prong_count" in result.get("error", "")

    def test_zero_stone_diameter_rejected(self):
        ctx, _, fid = make_ctx()
        result = call_tool(
            run_jewelry_create_prong_head, ctx, fid,
            stone_diameter=0,
            prong_count=6,
            prong_wire_diameter=1.0,
            prong_height=2.0,
        )
        assert result.get("code") == "BAD_ARGS"

    def test_negative_prong_height_rejected(self):
        ctx, _, fid = make_ctx()
        result = call_tool(
            run_jewelry_create_prong_head, ctx, fid,
            stone_diameter=6.5,
            prong_count=4,
            prong_wire_diameter=1.0,
            prong_height=-1.0,
        )
        assert result.get("code") == "BAD_ARGS"

    def test_invalid_head_style_rejected(self):
        ctx, _, fid = make_ctx()
        result = call_tool(
            run_jewelry_create_prong_head, ctx, fid,
            stone_diameter=6.5, prong_count=4,
            prong_wire_diameter=1.0, prong_height=2.0,
            head_style="claw",
        )
        assert result.get("code") == "BAD_ARGS"

    def test_non_uuid_file_id_rejected(self):
        ctx, _, _ = make_ctx()
        result = call_tool(
            run_jewelry_create_prong_head, ctx, "not-a-uuid",
            stone_diameter=6.5, prong_count=4,
            prong_wire_diameter=1.0, prong_height=2.0,
        )
        assert result.get("code") == "BAD_ARGS"

    def test_missing_file_not_found(self):
        ctx, _, fid = make_ctx(kind="NOT_FOUND")
        result = call_tool(
            run_jewelry_create_prong_head, ctx, fid,
            stone_diameter=6.5, prong_count=4,
            prong_wire_diameter=1.0, prong_height=2.0,
        )
        assert result.get("code") == "NOT_FOUND"

    def test_invalid_json_args(self):
        ctx, _, _ = make_ctx()
        raw = run_sync(run_jewelry_create_prong_head(ctx, b"not json"))
        result = json.loads(raw)
        assert result.get("code") == "BAD_ARGS"

    @pytest.mark.parametrize("style", ["standard", "basket", "trellis", "cathedral"])
    def test_all_head_styles_accepted(self, style):
        ctx, store, fid = make_ctx()
        result = call_tool(
            run_jewelry_create_prong_head, ctx, fid,
            stone_diameter=6.0, prong_count=6,
            prong_wire_diameter=1.0, prong_height=2.0,
            head_style=style,
        )
        assert result.get("error") is None, f"style={style}: {result}"


# ============================================================================
# Bezel — node shape + geometry math
# ============================================================================

class TestBezzelGeometry:
    def test_outer_diameter(self):
        node = build_bezel_node(
            node_id="bezel-1",
            stone_diameter=8.0,
            wall_thickness=0.5,
            bezel_height=3.0,
            bearing_ledge_height=1.5,
            bezel_style="full",
            partial_opening_deg=0.0,
            taper_angle_deg=0.0,
        )
        assert math.isclose(node["_outer_diameter"], 8.0 + 2 * 0.5, rel_tol=1e-5)

    def test_inner_diameter_equals_stone(self):
        node = build_bezel_node(
            node_id="bezel-2",
            stone_diameter=5.0,
            wall_thickness=0.4,
            bezel_height=2.0,
            bearing_ledge_height=0.8,
            bezel_style="collet",
            partial_opening_deg=0.0,
            taper_angle_deg=5.0,
        )
        assert math.isclose(node["_inner_diameter"], 5.0, rel_tol=1e-9)

    def test_op_field(self):
        node = build_bezel_node(
            node_id="b-1", stone_diameter=6.0, wall_thickness=0.5,
            bezel_height=2.5, bearing_ledge_height=1.0,
            bezel_style="tapered", partial_opening_deg=0.0, taper_angle_deg=3.0,
        )
        assert node["op"] == "jewelry_bezel"


# ============================================================================
# Bezel — LLM tool runner
# ============================================================================

class TestBezzelRunner:
    def test_success_full_bezel(self):
        ctx, store, fid = make_ctx()
        result = call_tool(
            run_jewelry_create_bezel, ctx, fid,
            stone_diameter=8.0,
            wall_thickness=0.5,
            bezel_height=3.0,
            bearing_ledge_height=1.5,
        )
        assert result.get("error") is None, result
        assert result["op"] == "jewelry_bezel"

    def test_success_partial_bezel(self):
        ctx, store, fid = make_ctx()
        result = call_tool(
            run_jewelry_create_bezel, ctx, fid,
            stone_diameter=7.0,
            wall_thickness=0.6,
            bezel_height=2.8,
            bearing_ledge_height=1.2,
            bezel_style="partial",
            partial_opening_deg=90.0,
        )
        assert result.get("error") is None
        node = get_last_node(store)
        assert node["bezel_style"] == "partial"
        assert node["partial_opening_deg"] == 90.0

    def test_bearing_ledge_must_be_less_than_height(self):
        ctx, _, fid = make_ctx()
        result = call_tool(
            run_jewelry_create_bezel, ctx, fid,
            stone_diameter=6.0,
            wall_thickness=0.5,
            bezel_height=2.0,
            bearing_ledge_height=2.0,  # equal, not less — invalid
        )
        assert result.get("code") == "BAD_ARGS"
        assert "bearing_ledge_height" in result.get("error", "")

    def test_partial_opening_out_of_range_rejected(self):
        ctx, _, fid = make_ctx()
        result = call_tool(
            run_jewelry_create_bezel, ctx, fid,
            stone_diameter=6.0,
            wall_thickness=0.5,
            bezel_height=2.5,
            bearing_ledge_height=1.0,
            bezel_style="partial",
            partial_opening_deg=0.0,  # 0 is invalid (must be >= 1)
        )
        assert result.get("code") == "BAD_ARGS"

    def test_negative_taper_rejected(self):
        ctx, _, fid = make_ctx()
        result = call_tool(
            run_jewelry_create_bezel, ctx, fid,
            stone_diameter=6.0,
            wall_thickness=0.5,
            bezel_height=2.5,
            bearing_ledge_height=1.0,
            taper_angle_deg=-5.0,
        )
        assert result.get("code") == "BAD_ARGS"

    def test_invalid_style_rejected(self):
        ctx, _, fid = make_ctx()
        result = call_tool(
            run_jewelry_create_bezel, ctx, fid,
            stone_diameter=6.0,
            wall_thickness=0.5,
            bezel_height=2.5,
            bearing_ledge_height=1.0,
            bezel_style="rub-over",  # not in enum
        )
        assert result.get("code") == "BAD_ARGS"

    def test_zero_wall_thickness_rejected(self):
        ctx, _, fid = make_ctx()
        result = call_tool(
            run_jewelry_create_bezel, ctx, fid,
            stone_diameter=6.0,
            wall_thickness=0.0,
            bezel_height=2.5,
            bearing_ledge_height=1.0,
        )
        assert result.get("code") == "BAD_ARGS"

    @pytest.mark.parametrize("style", ["full", "partial", "collet", "tapered"])
    def test_all_bezel_styles_accepted(self, style):
        ctx, store, fid = make_ctx()
        extra = {}
        if style == "partial":
            extra["partial_opening_deg"] = 120.0
        if style in ("tapered", "collet"):
            extra["taper_angle_deg"] = 5.0
        result = call_tool(
            run_jewelry_create_bezel, ctx, fid,
            stone_diameter=7.0,
            wall_thickness=0.5,
            bezel_height=3.0,
            bearing_ledge_height=1.2,
            bezel_style=style,
            **extra,
        )
        assert result.get("error") is None, f"style={style}: {result}"


# ============================================================================
# Channel — node shape + geometry math
# ============================================================================

class TestChannelGeometry:
    def test_channel_length(self):
        node = build_channel_node(
            node_id="ch-1",
            stone_diameter=3.0,
            stone_count=5,
            stone_spacing=3.5,
            rail_height=1.5,
            rail_thickness=0.5,
            floor_thickness=0.4,
        )
        expected_length = 5 * 3.5
        assert math.isclose(node["_channel_length"], expected_length, rel_tol=1e-5)

    def test_rail_separation(self):
        node = build_channel_node(
            node_id="ch-2",
            stone_diameter=4.0,
            stone_count=3,
            stone_spacing=4.5,
            rail_height=2.0,
            rail_thickness=0.6,
            floor_thickness=0.5,
        )
        assert math.isclose(node["_rail_separation"], 4.0, rel_tol=1e-9)

    def test_op_field(self):
        node = build_channel_node(
            node_id="ch-1", stone_diameter=3.0, stone_count=4,
            stone_spacing=3.5, rail_height=1.5,
            rail_thickness=0.5, floor_thickness=0.4,
        )
        assert node["op"] == "jewelry_channel"


# ============================================================================
# Channel — LLM tool runner
# ============================================================================

class TestChannelRunner:
    def test_success(self):
        ctx, store, fid = make_ctx()
        result = call_tool(
            run_jewelry_create_channel, ctx, fid,
            stone_diameter=3.0,
            stone_count=5,
            stone_spacing=3.5,
            rail_height=1.5,
            rail_thickness=0.5,
            floor_thickness=0.4,
        )
        assert result.get("error") is None, result
        assert result["op"] == "jewelry_channel"
        assert result["stone_count"] == 5
        assert math.isclose(result["channel_length"], 5 * 3.5, rel_tol=1e-5)

    def test_node_stored(self):
        ctx, store, fid = make_ctx()
        call_tool(
            run_jewelry_create_channel, ctx, fid,
            stone_diameter=3.0, stone_count=5, stone_spacing=3.5,
            rail_height=1.5, rail_thickness=0.5, floor_thickness=0.4,
        )
        node = get_last_node(store)
        assert node["op"] == "jewelry_channel"
        assert node["stone_count"] == 5
        assert node["stone_diameter"] == 3.0

    def test_node_id_auto(self):
        ctx, store, fid = make_ctx()
        call_tool(
            run_jewelry_create_channel, ctx, fid,
            stone_diameter=3.0, stone_count=5, stone_spacing=3.5,
            rail_height=1.5, rail_thickness=0.5, floor_thickness=0.4,
        )
        node = get_last_node(store)
        assert node["id"].startswith("jewelry_channel-")

    def test_stone_count_zero_rejected(self):
        ctx, _, fid = make_ctx()
        result = call_tool(
            run_jewelry_create_channel, ctx, fid,
            stone_diameter=3.0, stone_count=0, stone_spacing=3.5,
            rail_height=1.5, rail_thickness=0.5, floor_thickness=0.4,
        )
        assert result.get("code") == "BAD_ARGS"

    def test_spacing_le_diameter_rejected(self):
        ctx, _, fid = make_ctx()
        result = call_tool(
            run_jewelry_create_channel, ctx, fid,
            stone_diameter=3.0,
            stone_count=5,
            stone_spacing=2.5,  # less than stone_diameter — overlap
            rail_height=1.5,
            rail_thickness=0.5,
            floor_thickness=0.4,
        )
        assert result.get("code") == "BAD_ARGS"
        assert "stone_spacing" in result.get("error", "")

    def test_spacing_equal_to_diameter_rejected(self):
        ctx, _, fid = make_ctx()
        result = call_tool(
            run_jewelry_create_channel, ctx, fid,
            stone_diameter=3.0,
            stone_count=5,
            stone_spacing=3.0,  # equal — no gap, invalid
            rail_height=1.5,
            rail_thickness=0.5,
            floor_thickness=0.4,
        )
        assert result.get("code") == "BAD_ARGS"

    def test_negative_rail_height_rejected(self):
        ctx, _, fid = make_ctx()
        result = call_tool(
            run_jewelry_create_channel, ctx, fid,
            stone_diameter=3.0, stone_count=3, stone_spacing=3.5,
            rail_height=-1.0, rail_thickness=0.5, floor_thickness=0.4,
        )
        assert result.get("code") == "BAD_ARGS"

    def test_non_integer_stone_count_rejected(self):
        ctx, _, fid = make_ctx()
        result = call_tool(
            run_jewelry_create_channel, ctx, fid,
            stone_diameter=3.0, stone_count="five", stone_spacing=3.5,
            rail_height=1.5, rail_thickness=0.5, floor_thickness=0.4,
        )
        assert result.get("code") == "BAD_ARGS"


# ============================================================================
# Pavé — grid math
# ============================================================================

class TestPaveGrid:
    def test_basic_grid_produces_placements(self):
        placements = _compute_pave_grid(
            region_width=10.0,
            region_height=10.0,
            stone_diameter=1.5,
            stone_spacing=0.2,
            edge_margin=0.5,
        )
        assert len(placements) > 0

    def test_grid_u_v_in_range(self):
        placements = _compute_pave_grid(
            region_width=10.0,
            region_height=10.0,
            stone_diameter=1.5,
            stone_spacing=0.2,
            edge_margin=0.5,
        )
        for p in placements:
            assert 0.0 <= p["u"] <= 1.0, f"u out of range: {p['u']}"
            assert 0.0 <= p["v"] <= 1.0, f"v out of range: {p['v']}"

    def test_grid_has_row_col_fields(self):
        placements = _compute_pave_grid(
            region_width=8.0, region_height=6.0,
            stone_diameter=1.0, stone_spacing=0.3, edge_margin=0.5,
        )
        for p in placements:
            assert "row" in p
            assert "col" in p

    def test_tiny_region_returns_empty(self):
        placements = _compute_pave_grid(
            region_width=1.0, region_height=1.0,
            stone_diameter=2.0,
            stone_spacing=0.2,
            edge_margin=0.5,
        )
        assert placements == []

    def test_edge_margin_larger_than_region_returns_empty(self):
        placements = _compute_pave_grid(
            region_width=3.0, region_height=3.0,
            stone_diameter=1.0, stone_spacing=0.2,
            edge_margin=2.0,  # 2 * edge_margin > region_width
        )
        assert placements == []

    def test_larger_region_more_placements(self):
        small = _compute_pave_grid(
            region_width=5.0, region_height=5.0,
            stone_diameter=1.0, stone_spacing=0.2, edge_margin=0.3,
        )
        large = _compute_pave_grid(
            region_width=10.0, region_height=10.0,
            stone_diameter=1.0, stone_spacing=0.2, edge_margin=0.3,
        )
        assert len(large) > len(small)

    def test_odd_rows_hex_offset(self):
        """Odd rows should have a different col distribution than even rows."""
        placements = _compute_pave_grid(
            region_width=15.0, region_height=10.0,
            stone_diameter=1.5, stone_spacing=0.2, edge_margin=0.5,
        )
        # Gather row 0 vs row 1 u-values.
        row0_u = [p["u"] for p in placements if p["row"] == 0]
        row1_u = [p["u"] for p in placements if p["row"] == 1]
        # If both rows have at least one placement, row 1 should start at a
        # different u from row 0 (the hex half-pitch offset).
        if row0_u and row1_u:
            assert not math.isclose(
                min(row0_u), min(row1_u), abs_tol=1e-4
            ), "Odd-row hex offset not applied"

    def test_pitch_governs_count(self):
        """More spacing → fewer placements."""
        fewer = _compute_pave_grid(
            region_width=10.0, region_height=10.0,
            stone_diameter=1.5, stone_spacing=1.0, edge_margin=0.5,
        )
        more = _compute_pave_grid(
            region_width=10.0, region_height=10.0,
            stone_diameter=1.5, stone_spacing=0.2, edge_margin=0.5,
        )
        assert len(more) >= len(fewer)


# ============================================================================
# Pavé — node builder
# ============================================================================

class TestPaveNodeBuilder:
    def test_placement_count_matches_grid(self):
        node = build_pave_array_node(
            node_id="pave-1",
            region_width=10.0,
            region_height=10.0,
            stone_diameter=1.5,
            stone_spacing=0.2,
            edge_margin=0.5,
            surface_normal=[0, 0, 1],
            surface_origin=[0, 0, 0],
        )
        assert node["_placement_count"] == len(node["placements"])

    def test_op_field(self):
        node = build_pave_array_node(
            node_id="pave-2",
            region_width=8.0, region_height=6.0,
            stone_diameter=1.0, stone_spacing=0.3, edge_margin=0.5,
            surface_normal=[0, 0, 1], surface_origin=[0, 0, 0],
        )
        assert node["op"] == "jewelry_pave"

    def test_surface_normal_stored(self):
        sn = [0.0, 1.0, 0.0]
        node = build_pave_array_node(
            node_id="pave-3",
            region_width=8.0, region_height=6.0,
            stone_diameter=1.0, stone_spacing=0.3, edge_margin=0.5,
            surface_normal=sn, surface_origin=[1.0, 2.0, 3.0],
        )
        assert node["surface_normal"] == sn


# ============================================================================
# Pavé — LLM tool runner
# ============================================================================

class TestPaveRunner:
    def test_success(self):
        ctx, store, fid = make_ctx()
        result = call_tool(
            run_jewelry_pave_array, ctx, fid,
            region_width=10.0,
            region_height=10.0,
            stone_diameter=1.5,
            stone_spacing=0.2,
            edge_margin=0.5,
        )
        assert result.get("error") is None, result
        assert result["op"] == "jewelry_pave"
        assert result["placement_count"] > 0

    def test_node_stored_with_placements(self):
        ctx, store, fid = make_ctx()
        call_tool(
            run_jewelry_pave_array, ctx, fid,
            region_width=10.0, region_height=10.0,
            stone_diameter=1.5, stone_spacing=0.2, edge_margin=0.5,
        )
        node = get_last_node(store)
        assert node["op"] == "jewelry_pave"
        assert isinstance(node["placements"], list)
        assert node["_placement_count"] == len(node["placements"])

    def test_node_id_auto(self):
        ctx, store, fid = make_ctx()
        call_tool(
            run_jewelry_pave_array, ctx, fid,
            region_width=8.0, region_height=8.0,
            stone_diameter=1.0, stone_spacing=0.3, edge_margin=0.4,
        )
        node = get_last_node(store)
        assert node["id"].startswith("jewelry_pave-")

    def test_custom_surface_normal_stored(self):
        ctx, store, fid = make_ctx()
        call_tool(
            run_jewelry_pave_array, ctx, fid,
            region_width=8.0, region_height=8.0,
            stone_diameter=1.0, stone_spacing=0.3, edge_margin=0.4,
            surface_normal=[0.0, 1.0, 0.0],
            surface_origin=[5.0, 0.0, 2.5],
        )
        node = get_last_node(store)
        assert node["surface_normal"] == [0.0, 1.0, 0.0]
        assert node["surface_origin"] == [5.0, 0.0, 2.5]

    def test_zero_region_width_rejected(self):
        ctx, _, fid = make_ctx()
        result = call_tool(
            run_jewelry_pave_array, ctx, fid,
            region_width=0.0, region_height=10.0,
            stone_diameter=1.5, stone_spacing=0.2, edge_margin=0.5,
        )
        assert result.get("code") == "BAD_ARGS"

    def test_negative_stone_spacing_rejected(self):
        ctx, _, fid = make_ctx()
        result = call_tool(
            run_jewelry_pave_array, ctx, fid,
            region_width=10.0, region_height=10.0,
            stone_diameter=1.5, stone_spacing=-0.2, edge_margin=0.5,
        )
        assert result.get("code") == "BAD_ARGS"

    def test_negative_edge_margin_rejected(self):
        ctx, _, fid = make_ctx()
        result = call_tool(
            run_jewelry_pave_array, ctx, fid,
            region_width=10.0, region_height=10.0,
            stone_diameter=1.5, stone_spacing=0.2, edge_margin=-0.5,
        )
        assert result.get("code") == "BAD_ARGS"

    def test_invalid_surface_normal_length_rejected(self):
        ctx, _, fid = make_ctx()
        result = call_tool(
            run_jewelry_pave_array, ctx, fid,
            region_width=10.0, region_height=10.0,
            stone_diameter=1.5, stone_spacing=0.2, edge_margin=0.5,
            surface_normal=[0, 1],  # 2-element, should be 3
        )
        assert result.get("code") == "BAD_ARGS"

    def test_non_uuid_file_id_rejected(self):
        ctx, _, _ = make_ctx()
        result = call_tool(
            run_jewelry_pave_array, ctx, "not-a-uuid",
            region_width=10.0, region_height=10.0,
            stone_diameter=1.5, stone_spacing=0.2, edge_margin=0.5,
        )
        assert result.get("code") == "BAD_ARGS"

    def test_missing_file_not_found(self):
        ctx, _, fid = make_ctx(kind="NOT_FOUND")
        result = call_tool(
            run_jewelry_pave_array, ctx, fid,
            region_width=10.0, region_height=10.0,
            stone_diameter=1.5, stone_spacing=0.2, edge_margin=0.5,
        )
        assert result.get("code") == "NOT_FOUND"

    def test_invalid_json_args(self):
        ctx, _, _ = make_ctx()
        raw = run_sync(run_jewelry_pave_array(ctx, b"{invalid json"))
        result = json.loads(raw)
        assert result.get("code") == "BAD_ARGS"


# ============================================================================
# Multiple nodes in same file — ID auto-increments
# ============================================================================

class TestMultipleNodes:
    def test_prong_head_ids_increment(self):
        ctx, store, fid = make_ctx()
        for _ in range(3):
            call_tool(
                run_jewelry_create_prong_head, ctx, fid,
                stone_diameter=6.0, prong_count=4,
                prong_wire_diameter=1.0, prong_height=2.0,
            )
        doc = json.loads(store["content"])
        ids = [n["id"] for n in doc["features"]]
        assert ids == [
            "jewelry_prong_head-1",
            "jewelry_prong_head-2",
            "jewelry_prong_head-3",
        ]

    def test_different_setting_types_coexist(self):
        ctx, store, fid = make_ctx()
        call_tool(
            run_jewelry_create_prong_head, ctx, fid,
            stone_diameter=6.5, prong_count=6,
            prong_wire_diameter=1.0, prong_height=2.0,
        )
        call_tool(
            run_jewelry_create_bezel, ctx, fid,
            stone_diameter=6.5, wall_thickness=0.5,
            bezel_height=3.0, bearing_ledge_height=1.5,
        )
        call_tool(
            run_jewelry_create_channel, ctx, fid,
            stone_diameter=2.5, stone_count=7, stone_spacing=3.0,
            rail_height=1.5, rail_thickness=0.5, floor_thickness=0.4,
        )
        doc = json.loads(store["content"])
        ops = [n["op"] for n in doc["features"]]
        assert "jewelry_prong_head" in ops
        assert "jewelry_bezel" in ops
        assert "jewelry_channel" in ops


# ============================================================================
# OCC-gated placeholder (extends to real solid tests once OCC is present)
# ============================================================================

@skip_no_occ
class TestOccProngHead:
    """OCC-gated: verify the node spec round-trips through BRepPrimAPI cylinder."""

    def test_occ_cylinder_from_prong_head_spec(self):
        """Smoke test: build a cylinder with the head outer diameter."""
        from OCC.Core.BRepPrimAPI import BRepPrimAPI_MakeCylinder  # type: ignore
        from OCC.Core.gp import gp_Pnt, gp_Ax2, gp_Dir  # type: ignore

        node = build_prong_head_node(
            node_id="occ-test-1",
            stone_diameter=6.5,
            prong_count=4,
            prong_wire_diameter=1.0,
            prong_height=2.0,
            head_style="standard",
            basket_rail_count=0,
            seat_angle_deg=15.0,
        )
        radius = node["_head_outer_diameter"] / 2.0
        height = node["prong_height"]

        ax = gp_Ax2(gp_Pnt(0, 0, 0), gp_Dir(0, 0, 1))
        cyl = BRepPrimAPI_MakeCylinder(ax, radius, height)
        shape = cyl.Shape()
        assert not shape.IsNull()


# ============================================================================
# Tension setting — ToolSpec schema
# ============================================================================

class TestTensionSpec:
    def test_name(self):
        assert jewelry_tension_spec.name == "jewelry_create_tension"

    def test_required_fields(self):
        req = jewelry_tension_spec.input_schema["required"]
        for f in ["file_id", "stone_diameter", "band_thickness", "gap", "rail_width", "rail_depth"]:
            assert f in req

    def test_id_not_required(self):
        assert "id" not in jewelry_tension_spec.input_schema["required"]


# ============================================================================
# Tension setting — geometry math
# ============================================================================

class TestTensionGeometry:
    def test_seat_radius(self):
        node = build_tension_node(
            node_id="t-1",
            stone_diameter=6.0,
            band_thickness=3.0,
            gap=5.0,
            rail_width=0.5,
            rail_depth=0.3,
        )
        assert math.isclose(node["_seat_radius"], 3.0, rel_tol=1e-9)

    def test_band_spread(self):
        node = build_tension_node(
            node_id="t-2",
            stone_diameter=6.0,
            band_thickness=3.0,
            gap=5.0,
            rail_width=0.5,
            rail_depth=0.3,
        )
        assert math.isclose(node["_band_spread"], 6.0 + 5.0, rel_tol=1e-9)

    def test_op_field(self):
        node = build_tension_node(
            node_id="t-3",
            stone_diameter=5.0,
            band_thickness=2.5,
            gap=4.5,
            rail_width=0.4,
            rail_depth=0.25,
        )
        assert node["op"] == "jewelry_tension"

    def test_all_params_stored(self):
        node = build_tension_node(
            node_id="t-4",
            stone_diameter=7.0,
            band_thickness=3.5,
            gap=6.0,
            rail_width=0.6,
            rail_depth=0.35,
        )
        assert node["stone_diameter"] == 7.0
        assert node["band_thickness"] == 3.5
        assert node["gap"] == 6.0
        assert node["rail_width"] == 0.6
        assert node["rail_depth"] == 0.35


# ============================================================================
# Tension setting — LLM tool runner
# ============================================================================

class TestTensionRunner:
    def test_success(self):
        ctx, store, fid = make_ctx()
        result = call_tool(
            run_jewelry_create_tension, ctx, fid,
            stone_diameter=6.5,
            band_thickness=3.2,
            gap=5.8,
            rail_width=0.5,
            rail_depth=0.3,
        )
        assert result.get("error") is None, result
        assert result["op"] == "jewelry_tension"
        assert result["stone_diameter"] == 6.5

    def test_node_stored(self):
        ctx, store, fid = make_ctx()
        call_tool(
            run_jewelry_create_tension, ctx, fid,
            stone_diameter=6.5, band_thickness=3.2, gap=5.8,
            rail_width=0.5, rail_depth=0.3,
        )
        node = get_last_node(store)
        assert node["op"] == "jewelry_tension"
        assert node["stone_diameter"] == 6.5

    def test_node_id_auto(self):
        ctx, store, fid = make_ctx()
        call_tool(
            run_jewelry_create_tension, ctx, fid,
            stone_diameter=6.5, band_thickness=3.2, gap=5.8,
            rail_width=0.5, rail_depth=0.3,
        )
        node = get_last_node(store)
        assert node["id"].startswith("jewelry_tension-")

    def test_explicit_node_id(self):
        ctx, store, fid = make_ctx()
        call_tool(
            run_jewelry_create_tension, ctx, fid,
            stone_diameter=6.5, band_thickness=3.2, gap=5.8,
            rail_width=0.5, rail_depth=0.3,
            id="my-tension",
        )
        node = get_last_node(store)
        assert node["id"] == "my-tension"

    def test_gap_ge_stone_diameter_rejected(self):
        ctx, _, fid = make_ctx()
        # gap == stone_diameter means stone would fall out
        result = call_tool(
            run_jewelry_create_tension, ctx, fid,
            stone_diameter=6.5, band_thickness=3.2, gap=6.5,
            rail_width=0.5, rail_depth=0.3,
        )
        assert result.get("code") == "BAD_ARGS"
        assert "gap" in result.get("error", "")

    def test_gap_greater_than_diameter_rejected(self):
        ctx, _, fid = make_ctx()
        result = call_tool(
            run_jewelry_create_tension, ctx, fid,
            stone_diameter=6.5, band_thickness=3.2, gap=7.0,
            rail_width=0.5, rail_depth=0.3,
        )
        assert result.get("code") == "BAD_ARGS"

    def test_zero_stone_diameter_rejected(self):
        ctx, _, fid = make_ctx()
        result = call_tool(
            run_jewelry_create_tension, ctx, fid,
            stone_diameter=0, band_thickness=3.2, gap=5.0,
            rail_width=0.5, rail_depth=0.3,
        )
        assert result.get("code") == "BAD_ARGS"

    def test_negative_rail_depth_rejected(self):
        ctx, _, fid = make_ctx()
        result = call_tool(
            run_jewelry_create_tension, ctx, fid,
            stone_diameter=6.5, band_thickness=3.2, gap=5.8,
            rail_width=0.5, rail_depth=-0.1,
        )
        assert result.get("code") == "BAD_ARGS"

    def test_missing_file_not_found(self):
        ctx, _, fid = make_ctx(kind="NOT_FOUND")
        result = call_tool(
            run_jewelry_create_tension, ctx, fid,
            stone_diameter=6.5, band_thickness=3.2, gap=5.8,
            rail_width=0.5, rail_depth=0.3,
        )
        assert result.get("code") == "NOT_FOUND"

    def test_invalid_json_rejected(self):
        ctx, _, _ = make_ctx()
        raw = run_sync(run_jewelry_create_tension(ctx, b"not json"))
        result = json.loads(raw)
        assert result.get("code") == "BAD_ARGS"

    def test_band_spread_in_result(self):
        ctx, store, fid = make_ctx()
        result = call_tool(
            run_jewelry_create_tension, ctx, fid,
            stone_diameter=6.0, band_thickness=3.0, gap=5.0,
            rail_width=0.5, rail_depth=0.3,
        )
        assert math.isclose(result["_band_spread"], 6.0 + 5.0, rel_tol=1e-9)


# ============================================================================
# Flush / gypsy setting — ToolSpec schema
# ============================================================================

class TestFlushSpec:
    def test_name(self):
        assert jewelry_flush_spec.name == "jewelry_create_flush"

    def test_required_fields(self):
        req = jewelry_flush_spec.input_schema["required"]
        for f in ["file_id", "stone_diameter", "seat_depth", "bevel_width", "bevel_angle_deg"]:
            assert f in req

    def test_id_not_required(self):
        assert "id" not in jewelry_flush_spec.input_schema["required"]


# ============================================================================
# Flush / gypsy setting — geometry math
# ============================================================================

class TestFlushGeometry:
    def test_seat_volume_positive(self):
        node = build_flush_node(
            node_id="f-1",
            stone_diameter=3.0,
            seat_depth=1.5,
            bevel_width=0.2,
            bevel_angle_deg=45.0,
        )
        assert node["_seat_volume_approx"] > 0

    def test_seat_volume_formula(self):
        sd = 4.0
        depth = 2.0
        node = build_flush_node(
            node_id="f-2",
            stone_diameter=sd,
            seat_depth=depth,
            bevel_width=0.1,
            bevel_angle_deg=30.0,
        )
        expected = math.pi * (sd / 2) ** 2 * depth
        assert math.isclose(node["_seat_volume_approx"], expected, rel_tol=1e-4)

    def test_opening_diameter_larger_than_stone(self):
        node = build_flush_node(
            node_id="f-3",
            stone_diameter=5.0,
            seat_depth=2.0,
            bevel_width=0.3,
            bevel_angle_deg=45.0,
        )
        assert node["_opening_diameter"] > node["stone_diameter"]

    def test_zero_bevel_opening_equals_stone(self):
        node = build_flush_node(
            node_id="f-4",
            stone_diameter=4.0,
            seat_depth=1.5,
            bevel_width=0.0,
            bevel_angle_deg=45.0,
        )
        assert math.isclose(node["_opening_diameter"], 4.0, rel_tol=1e-9)

    def test_op_field(self):
        node = build_flush_node(
            node_id="f-5",
            stone_diameter=3.0, seat_depth=1.2,
            bevel_width=0.2, bevel_angle_deg=45.0,
        )
        assert node["op"] == "jewelry_flush"


# ============================================================================
# Flush / gypsy setting — LLM tool runner
# ============================================================================

class TestFlushRunner:
    def test_success(self):
        ctx, store, fid = make_ctx()
        result = call_tool(
            run_jewelry_create_flush, ctx, fid,
            stone_diameter=3.5,
            seat_depth=1.8,
            bevel_width=0.2,
            bevel_angle_deg=45.0,
        )
        assert result.get("error") is None, result
        assert result["op"] == "jewelry_flush"

    def test_node_stored(self):
        ctx, store, fid = make_ctx()
        call_tool(
            run_jewelry_create_flush, ctx, fid,
            stone_diameter=3.5, seat_depth=1.8, bevel_width=0.2, bevel_angle_deg=45.0,
        )
        node = get_last_node(store)
        assert node["op"] == "jewelry_flush"
        assert node["stone_diameter"] == 3.5

    def test_node_id_auto(self):
        ctx, store, fid = make_ctx()
        call_tool(
            run_jewelry_create_flush, ctx, fid,
            stone_diameter=3.5, seat_depth=1.8, bevel_width=0.2, bevel_angle_deg=45.0,
        )
        node = get_last_node(store)
        assert node["id"].startswith("jewelry_flush-")

    def test_bevel_angle_90_rejected(self):
        ctx, _, fid = make_ctx()
        result = call_tool(
            run_jewelry_create_flush, ctx, fid,
            stone_diameter=3.5, seat_depth=1.8, bevel_width=0.2, bevel_angle_deg=90.0,
        )
        assert result.get("code") == "BAD_ARGS"
        assert "bevel_angle_deg" in result.get("error", "")

    def test_bevel_angle_over_90_rejected(self):
        ctx, _, fid = make_ctx()
        result = call_tool(
            run_jewelry_create_flush, ctx, fid,
            stone_diameter=3.5, seat_depth=1.8, bevel_width=0.2, bevel_angle_deg=120.0,
        )
        assert result.get("code") == "BAD_ARGS"

    def test_zero_stone_diameter_rejected(self):
        ctx, _, fid = make_ctx()
        result = call_tool(
            run_jewelry_create_flush, ctx, fid,
            stone_diameter=0, seat_depth=1.8, bevel_width=0.2, bevel_angle_deg=45.0,
        )
        assert result.get("code") == "BAD_ARGS"

    def test_negative_seat_depth_rejected(self):
        ctx, _, fid = make_ctx()
        result = call_tool(
            run_jewelry_create_flush, ctx, fid,
            stone_diameter=3.5, seat_depth=-0.5, bevel_width=0.2, bevel_angle_deg=45.0,
        )
        assert result.get("code") == "BAD_ARGS"

    def test_opening_diameter_in_result(self):
        ctx, store, fid = make_ctx()
        result = call_tool(
            run_jewelry_create_flush, ctx, fid,
            stone_diameter=4.0, seat_depth=2.0, bevel_width=0.3, bevel_angle_deg=45.0,
        )
        assert "_opening_diameter" in result
        assert result["_opening_diameter"] > result["stone_diameter"]

    def test_missing_file_not_found(self):
        ctx, _, fid = make_ctx(kind="NOT_FOUND")
        result = call_tool(
            run_jewelry_create_flush, ctx, fid,
            stone_diameter=3.5, seat_depth=1.8, bevel_width=0.2, bevel_angle_deg=45.0,
        )
        assert result.get("code") == "NOT_FOUND"

    def test_invalid_json_rejected(self):
        ctx, _, _ = make_ctx()
        raw = run_sync(run_jewelry_create_flush(ctx, b"bad"))
        result = json.loads(raw)
        assert result.get("code") == "BAD_ARGS"


# ============================================================================
# Halo setting — ToolSpec schema
# ============================================================================

