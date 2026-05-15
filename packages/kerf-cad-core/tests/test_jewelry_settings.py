"""
Tests for kerf_cad_core.jewelry.settings — prong head, bezel, channel, pavé,
tension, flush, halo, three-stone, cluster, bar, bead/grain, gypsy-pavé,
illusion, invisible, plus v4 settings: suspension_mount, vtip_protector,
bombe_cluster, patterned_bezel, trellis_prong, bar_channel_graduated.

Structure
---------
Pure-Python tests (always run):
  - ToolSpec schema assertions (names, required fields, enum values).
  - Input validation: bad values rejected with code='BAD_ARGS'.
  - Node shape: node dicts stored in the feature JSON match the spec.
  - Geometry math: _compute_pave_grid, derived hints, seat positions,
    cluster positions, three-stone offsets, halo radius, tension band spread,
    flush opening diameter, bombe positions, graduated row positions.

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
    jewelry_halo_spec,
    jewelry_three_stone_spec,
    jewelry_cluster_spec,
    jewelry_bar_spec,
    jewelry_bead_grain_spec,
    jewelry_gypsy_pave_spec,
    jewelry_illusion_spec,
    jewelry_invisible_spec,
    # v3 ToolSpec objects
    jewelry_prong_variant_spec,
    jewelry_head_gallery_spec,
    jewelry_under_bezel_spec,
    jewelry_peg_setting_spec,
    jewelry_coronet_spec,
    # v4 ToolSpec objects
    jewelry_suspension_mount_spec,
    jewelry_vtip_protector_spec,
    jewelry_bombe_cluster_spec,
    jewelry_patterned_bezel_spec,
    jewelry_trellis_prong_spec,
    jewelry_bar_channel_graduated_spec,
    # Runners
    run_jewelry_create_prong_head,
    run_jewelry_create_bezel,
    run_jewelry_create_channel,
    run_jewelry_pave_array,
    run_jewelry_create_tension,
    run_jewelry_create_flush,
    run_jewelry_create_halo,
    run_jewelry_create_three_stone,
    run_jewelry_create_cluster,
    run_jewelry_create_bar,
    run_jewelry_create_bead_grain,
    run_jewelry_create_gypsy_pave,
    run_jewelry_create_illusion,
    run_jewelry_create_invisible,
    # v3 runners
    run_jewelry_create_prong_variant,
    run_jewelry_create_head_gallery,
    run_jewelry_create_under_bezel,
    run_jewelry_create_peg_setting,
    run_jewelry_create_coronet,
    # v4 runners
    run_jewelry_create_suspension_mount,
    run_jewelry_create_vtip_protector,
    run_jewelry_create_bombe_cluster,
    run_jewelry_create_patterned_bezel,
    run_jewelry_create_trellis_prong,
    run_jewelry_create_bar_channel_graduated,
    # Pure-Python helpers
    build_prong_head_node,
    build_bezel_node,
    build_channel_node,
    build_pave_array_node,
    build_tension_node,
    build_flush_node,
    build_halo_node,
    build_three_stone_node,
    build_cluster_node,
    build_bar_node,
    build_bead_grain_node,
    build_gypsy_pave_node,
    build_illusion_node,
    build_invisible_node,
    # v3 helpers
    build_prong_variant_node,
    build_head_gallery_node,
    build_under_bezel_node,
    build_peg_setting_node,
    build_coronet_node,
    # v4 helpers
    build_suspension_mount_node,
    build_vtip_protector_node,
    build_bombe_cluster_node,
    build_patterned_bezel_node,
    build_trellis_prong_node,
    build_bar_channel_graduated_node,
    _compute_pave_grid,
    _compute_cluster_positions,
    _compute_bombe_positions,
    _compute_graduated_row,
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

class TestHaloSpec:
    def test_name(self):
        assert jewelry_halo_spec.name == "jewelry_create_halo"

    def test_required_fields(self):
        req = jewelry_halo_spec.input_schema["required"]
        for f in ["file_id", "center_diameter", "halo_stone_size", "halo_stone_count", "halo_gap", "halo_metal_width"]:
            assert f in req

    def test_id_not_required(self):
        assert "id" not in jewelry_halo_spec.input_schema["required"]


# ============================================================================
# Halo setting — geometry math
# ============================================================================

class TestHaloGeometry:
    def test_halo_radius_formula(self):
        center_d = 6.5
        stone_size = 1.2
        gap = 0.15
        node = build_halo_node(
            node_id="h-1",
            center_diameter=center_d,
            halo_stone_size=stone_size,
            halo_stone_count=18,
            halo_gap=gap,
            halo_metal_width=0.4,
        )
        expected_radius = center_d / 2.0 + gap + stone_size / 2.0
        assert math.isclose(node["_halo_radius"], expected_radius, rel_tol=1e-5)

    def test_halo_outer_diameter_larger_than_center(self):
        node = build_halo_node(
            node_id="h-2",
            center_diameter=6.5,
            halo_stone_size=1.2,
            halo_stone_count=18,
            halo_gap=0.15,
            halo_metal_width=0.4,
        )
        assert node["_halo_outer_diameter"] > node["center_diameter"]

    def test_accent_pitch_deg(self):
        node = build_halo_node(
            node_id="h-3",
            center_diameter=6.0,
            halo_stone_size=1.0,
            halo_stone_count=18,
            halo_gap=0.2,
            halo_metal_width=0.3,
        )
        assert math.isclose(node["_accent_pitch_deg"], 360.0 / 18, rel_tol=1e-5)

    def test_op_field(self):
        node = build_halo_node(
            node_id="h-4",
            center_diameter=5.0, halo_stone_size=1.0,
            halo_stone_count=16, halo_gap=0.15, halo_metal_width=0.35,
        )
        assert node["op"] == "jewelry_halo"

    def test_all_params_stored(self):
        node = build_halo_node(
            node_id="h-5",
            center_diameter=7.0,
            halo_stone_size=1.3,
            halo_stone_count=22,
            halo_gap=0.2,
            halo_metal_width=0.45,
        )
        assert node["center_diameter"] == 7.0
        assert node["halo_stone_size"] == 1.3
        assert node["halo_stone_count"] == 22
        assert node["halo_gap"] == 0.2
        assert node["halo_metal_width"] == 0.45


# ============================================================================
# Halo setting — LLM tool runner
# ============================================================================

class TestHaloRunner:
    def test_success(self):
        ctx, store, fid = make_ctx()
        result = call_tool(
            run_jewelry_create_halo, ctx, fid,
            center_diameter=6.5,
            halo_stone_size=1.2,
            halo_stone_count=18,
            halo_gap=0.15,
            halo_metal_width=0.4,
        )
        assert result.get("error") is None, result
        assert result["op"] == "jewelry_halo"
        assert result["halo_stone_count"] == 18

    def test_node_stored(self):
        ctx, store, fid = make_ctx()
        call_tool(
            run_jewelry_create_halo, ctx, fid,
            center_diameter=6.5, halo_stone_size=1.2, halo_stone_count=18,
            halo_gap=0.15, halo_metal_width=0.4,
        )
        node = get_last_node(store)
        assert node["op"] == "jewelry_halo"
        assert node["center_diameter"] == 6.5

    def test_node_id_auto(self):
        ctx, store, fid = make_ctx()
        call_tool(
            run_jewelry_create_halo, ctx, fid,
            center_diameter=6.5, halo_stone_size=1.2, halo_stone_count=18,
            halo_gap=0.15, halo_metal_width=0.4,
        )
        node = get_last_node(store)
        assert node["id"].startswith("jewelry_halo-")

    def test_halo_stone_count_lt_3_rejected(self):
        ctx, _, fid = make_ctx()
        result = call_tool(
            run_jewelry_create_halo, ctx, fid,
            center_diameter=6.5, halo_stone_size=1.2, halo_stone_count=2,
            halo_gap=0.15, halo_metal_width=0.4,
        )
        assert result.get("code") == "BAD_ARGS"
        assert "halo_stone_count" in result.get("error", "")

    def test_zero_center_diameter_rejected(self):
        ctx, _, fid = make_ctx()
        result = call_tool(
            run_jewelry_create_halo, ctx, fid,
            center_diameter=0, halo_stone_size=1.2, halo_stone_count=18,
            halo_gap=0.15, halo_metal_width=0.4,
        )
        assert result.get("code") == "BAD_ARGS"

    def test_negative_halo_gap_rejected(self):
        ctx, _, fid = make_ctx()
        result = call_tool(
            run_jewelry_create_halo, ctx, fid,
            center_diameter=6.5, halo_stone_size=1.2, halo_stone_count=18,
            halo_gap=-0.1, halo_metal_width=0.4,
        )
        assert result.get("code") == "BAD_ARGS"

    def test_non_integer_count_rejected(self):
        ctx, _, fid = make_ctx()
        result = call_tool(
            run_jewelry_create_halo, ctx, fid,
            center_diameter=6.5, halo_stone_size=1.2, halo_stone_count="eighteen",
            halo_gap=0.15, halo_metal_width=0.4,
        )
        assert result.get("code") == "BAD_ARGS"

    def test_halo_outer_diameter_in_result(self):
        ctx, store, fid = make_ctx()
        result = call_tool(
            run_jewelry_create_halo, ctx, fid,
            center_diameter=6.5, halo_stone_size=1.2, halo_stone_count=18,
            halo_gap=0.15, halo_metal_width=0.4,
        )
        assert "_halo_outer_diameter" in result
        assert result["_halo_outer_diameter"] > result["center_diameter"]

    def test_missing_file_not_found(self):
        ctx, _, fid = make_ctx(kind="NOT_FOUND")
        result = call_tool(
            run_jewelry_create_halo, ctx, fid,
            center_diameter=6.5, halo_stone_size=1.2, halo_stone_count=18,
            halo_gap=0.15, halo_metal_width=0.4,
        )
        assert result.get("code") == "NOT_FOUND"

    def test_invalid_json_rejected(self):
        ctx, _, _ = make_ctx()
        raw = run_sync(run_jewelry_create_halo(ctx, b"not json"))
        result = json.loads(raw)
        assert result.get("code") == "BAD_ARGS"

    @pytest.mark.parametrize("count", [3, 10, 18, 24, 32])
    def test_various_stone_counts_accepted(self, count):
        ctx, store, fid = make_ctx()
        result = call_tool(
            run_jewelry_create_halo, ctx, fid,
            center_diameter=6.0, halo_stone_size=1.0, halo_stone_count=count,
            halo_gap=0.2, halo_metal_width=0.35,
        )
        assert result.get("error") is None, f"count={count}: {result}"


# ============================================================================
# Three-stone setting — ToolSpec schema
# ============================================================================

class TestThreeStoneSpec:
    def test_name(self):
        assert jewelry_three_stone_spec.name == "jewelry_create_three_stone"

    def test_required_fields(self):
        req = jewelry_three_stone_spec.input_schema["required"]
        for f in ["file_id", "center_diameter", "side_diameter", "stone_spacing", "base_height"]:
            assert f in req

    def test_id_not_required(self):
        assert "id" not in jewelry_three_stone_spec.input_schema["required"]


# ============================================================================
# Three-stone setting — geometry math
# ============================================================================

class TestThreeStoneGeometry:
    def test_side_offset_x_formula(self):
        cd = 6.5
        sd = 4.0
        sp = 0.2
        node = build_three_stone_node(
            node_id="ts-1",
            center_diameter=cd,
            side_diameter=sd,
            stone_spacing=sp,
            base_height=1.5,
        )
        expected_offset = cd / 2.0 + sp + sd / 2.0
        assert math.isclose(node["_side_offset_x"], expected_offset, rel_tol=1e-5)

    def test_total_width_formula(self):
        cd = 6.5
        sd = 4.0
        sp = 0.2
        node = build_three_stone_node(
            node_id="ts-2",
            center_diameter=cd,
            side_diameter=sd,
            stone_spacing=sp,
            base_height=1.5,
        )
        expected_offset = cd / 2.0 + sp + sd / 2.0
        expected_width = 2.0 * expected_offset + sd
        assert math.isclose(node["_total_width"], expected_width, rel_tol=1e-5)

    def test_total_width_greater_than_center(self):
        node = build_three_stone_node(
            node_id="ts-3",
            center_diameter=7.0,
            side_diameter=4.5,
            stone_spacing=0.25,
            base_height=2.0,
        )
        assert node["_total_width"] > node["center_diameter"]

    def test_op_field(self):
        node = build_three_stone_node(
            node_id="ts-4",
            center_diameter=6.0, side_diameter=4.0,
            stone_spacing=0.2, base_height=1.5,
        )
        assert node["op"] == "jewelry_three_stone"

    def test_all_params_stored(self):
        node = build_three_stone_node(
            node_id="ts-5",
            center_diameter=6.5,
            side_diameter=4.2,
            stone_spacing=0.18,
            base_height=1.8,
        )
        assert node["center_diameter"] == 6.5
        assert node["side_diameter"] == 4.2
        assert node["stone_spacing"] == 0.18
        assert node["base_height"] == 1.8


# ============================================================================
# Three-stone setting — LLM tool runner
# ============================================================================

class TestThreeStoneRunner:
    def test_success(self):
        ctx, store, fid = make_ctx()
        result = call_tool(
            run_jewelry_create_three_stone, ctx, fid,
            center_diameter=6.5,
            side_diameter=4.0,
            stone_spacing=0.2,
            base_height=1.5,
        )
        assert result.get("error") is None, result
        assert result["op"] == "jewelry_three_stone"
        assert result["center_diameter"] == 6.5
        assert result["side_diameter"] == 4.0

    def test_node_stored(self):
        ctx, store, fid = make_ctx()
        call_tool(
            run_jewelry_create_three_stone, ctx, fid,
            center_diameter=6.5, side_diameter=4.0, stone_spacing=0.2, base_height=1.5,
        )
        node = get_last_node(store)
        assert node["op"] == "jewelry_three_stone"
        assert node["center_diameter"] == 6.5

    def test_node_id_auto(self):
        ctx, store, fid = make_ctx()
        call_tool(
            run_jewelry_create_three_stone, ctx, fid,
            center_diameter=6.5, side_diameter=4.0, stone_spacing=0.2, base_height=1.5,
        )
        node = get_last_node(store)
        assert node["id"].startswith("jewelry_three_stone-")

    def test_zero_center_diameter_rejected(self):
        ctx, _, fid = make_ctx()
        result = call_tool(
            run_jewelry_create_three_stone, ctx, fid,
            center_diameter=0, side_diameter=4.0, stone_spacing=0.2, base_height=1.5,
        )
        assert result.get("code") == "BAD_ARGS"

    def test_negative_side_diameter_rejected(self):
        ctx, _, fid = make_ctx()
        result = call_tool(
            run_jewelry_create_three_stone, ctx, fid,
            center_diameter=6.5, side_diameter=-1.0, stone_spacing=0.2, base_height=1.5,
        )
        assert result.get("code") == "BAD_ARGS"

    def test_zero_spacing_rejected(self):
        ctx, _, fid = make_ctx()
        result = call_tool(
            run_jewelry_create_three_stone, ctx, fid,
            center_diameter=6.5, side_diameter=4.0, stone_spacing=0.0, base_height=1.5,
        )
        assert result.get("code") == "BAD_ARGS"

    def test_zero_base_height_rejected(self):
        ctx, _, fid = make_ctx()
        result = call_tool(
            run_jewelry_create_three_stone, ctx, fid,
            center_diameter=6.5, side_diameter=4.0, stone_spacing=0.2, base_height=0.0,
        )
        assert result.get("code") == "BAD_ARGS"

    def test_total_width_in_result(self):
        ctx, store, fid = make_ctx()
        result = call_tool(
            run_jewelry_create_three_stone, ctx, fid,
            center_diameter=6.5, side_diameter=4.0, stone_spacing=0.2, base_height=1.5,
        )
        assert "_total_width" in result
        assert result["_total_width"] > result["center_diameter"]

    def test_missing_file_not_found(self):
        ctx, _, fid = make_ctx(kind="NOT_FOUND")
        result = call_tool(
            run_jewelry_create_three_stone, ctx, fid,
            center_diameter=6.5, side_diameter=4.0, stone_spacing=0.2, base_height=1.5,
        )
        assert result.get("code") == "NOT_FOUND"

    def test_invalid_json_rejected(self):
        ctx, _, _ = make_ctx()
        raw = run_sync(run_jewelry_create_three_stone(ctx, b"not json"))
        result = json.loads(raw)
        assert result.get("code") == "BAD_ARGS"


# ============================================================================
# Cluster setting — ToolSpec schema
# ============================================================================

class TestClusterSpec:
    def test_name(self):
        assert jewelry_cluster_spec.name == "jewelry_create_cluster"

    def test_required_fields(self):
        req = jewelry_cluster_spec.input_schema["required"]
        for f in ["file_id", "cluster_diameter", "stone_size", "stone_count", "dome_height"]:
            assert f in req

    def test_id_not_required(self):
        assert "id" not in jewelry_cluster_spec.input_schema["required"]


# ============================================================================
# Cluster setting — geometry math (_compute_cluster_positions)
# ============================================================================

class TestClusterPositions:
    def test_single_stone_at_origin(self):
        positions = _compute_cluster_positions(
            cluster_diameter=8.0, stone_size=2.0, stone_count=1,
        )
        assert len(positions) == 1
        assert math.isclose(positions[0]["x"], 0.0, abs_tol=1e-9)
        assert math.isclose(positions[0]["y"], 0.0, abs_tol=1e-9)

    def test_count_matches_requested(self):
        for n in [3, 5, 7, 9, 12]:
            positions = _compute_cluster_positions(
                cluster_diameter=10.0, stone_size=1.5, stone_count=n,
            )
            assert len(positions) == n, f"n={n}"

    def test_angle_spacing_uniform(self):
        n = 6
        positions = _compute_cluster_positions(
            cluster_diameter=10.0, stone_size=1.5, stone_count=n,
        )
        angles = [p["angle_deg"] for p in positions]
        for i in range(n):
            assert math.isclose(angles[i], i * 360.0 / n, rel_tol=1e-5)

    def test_all_on_same_radius(self):
        n = 8
        positions = _compute_cluster_positions(
            cluster_diameter=12.0, stone_size=1.8, stone_count=n,
        )
        radii = [math.hypot(p["x"], p["y"]) for p in positions]
        expected_r = 12.0 / 2.0 - 1.8 / 2.0
        for r in radii:
            assert math.isclose(r, expected_r, rel_tol=1e-4), f"radius={r}, expected={expected_r}"

    def test_positions_have_required_keys(self):
        positions = _compute_cluster_positions(
            cluster_diameter=10.0, stone_size=1.5, stone_count=5,
        )
        for p in positions:
            assert "x" in p and "y" in p and "angle_deg" in p


# ============================================================================
# Cluster setting — node builder
# ============================================================================

class TestClusterNodeBuilder:
    def test_op_field(self):
        node = build_cluster_node(
            node_id="cl-1",
            cluster_diameter=10.0, stone_size=1.5, stone_count=7, dome_height=1.2,
        )
        assert node["op"] == "jewelry_cluster"

    def test_positions_count_matches(self):
        node = build_cluster_node(
            node_id="cl-2",
            cluster_diameter=10.0, stone_size=1.5, stone_count=7, dome_height=1.2,
        )
        assert node["_actual_count"] == len(node["positions"]) == 7

    def test_placement_radius_hint(self):
        cd = 10.0
        ss = 1.5
        node = build_cluster_node(
            node_id="cl-3",
            cluster_diameter=cd, stone_size=ss, stone_count=7, dome_height=1.2,
        )
        expected = cd / 2.0 - ss / 2.0
        assert math.isclose(node["_placement_radius"], expected, rel_tol=1e-5)

    def test_flat_dome_zero_height(self):
        node = build_cluster_node(
            node_id="cl-4",
            cluster_diameter=8.0, stone_size=1.2, stone_count=5, dome_height=0.0,
        )
        assert node["dome_height"] == 0.0

    def test_all_params_stored(self):
        node = build_cluster_node(
            node_id="cl-5",
            cluster_diameter=12.0,
            stone_size=2.0,
            stone_count=9,
            dome_height=1.5,
        )
        assert node["cluster_diameter"] == 12.0
        assert node["stone_size"] == 2.0
        assert node["stone_count"] == 9
        assert node["dome_height"] == 1.5


# ============================================================================
# Cluster setting — LLM tool runner
# ============================================================================

class TestClusterRunner:
    def test_success(self):
        ctx, store, fid = make_ctx()
        result = call_tool(
            run_jewelry_create_cluster, ctx, fid,
            cluster_diameter=10.0,
            stone_size=1.5,
            stone_count=7,
            dome_height=1.0,
        )
        assert result.get("error") is None, result
        assert result["op"] == "jewelry_cluster"
        assert result["stone_count"] == 7

    def test_node_stored(self):
        ctx, store, fid = make_ctx()
        call_tool(
            run_jewelry_create_cluster, ctx, fid,
            cluster_diameter=10.0, stone_size=1.5, stone_count=7, dome_height=1.0,
        )
        node = get_last_node(store)
        assert node["op"] == "jewelry_cluster"
        assert node["stone_count"] == 7
        assert isinstance(node["positions"], list)

    def test_node_id_auto(self):
        ctx, store, fid = make_ctx()
        call_tool(
            run_jewelry_create_cluster, ctx, fid,
            cluster_diameter=10.0, stone_size=1.5, stone_count=7, dome_height=1.0,
        )
        node = get_last_node(store)
        assert node["id"].startswith("jewelry_cluster-")

    def test_flat_dome_accepted(self):
        ctx, store, fid = make_ctx()
        result = call_tool(
            run_jewelry_create_cluster, ctx, fid,
            cluster_diameter=8.0, stone_size=1.2, stone_count=5, dome_height=0.0,
        )
        assert result.get("error") is None, result

    def test_zero_cluster_diameter_rejected(self):
        ctx, _, fid = make_ctx()
        result = call_tool(
            run_jewelry_create_cluster, ctx, fid,
            cluster_diameter=0, stone_size=1.5, stone_count=7, dome_height=1.0,
        )
        assert result.get("code") == "BAD_ARGS"

    def test_negative_stone_size_rejected(self):
        ctx, _, fid = make_ctx()
        result = call_tool(
            run_jewelry_create_cluster, ctx, fid,
            cluster_diameter=10.0, stone_size=-0.5, stone_count=7, dome_height=1.0,
        )
        assert result.get("code") == "BAD_ARGS"

    def test_zero_stone_count_rejected(self):
        ctx, _, fid = make_ctx()
        result = call_tool(
            run_jewelry_create_cluster, ctx, fid,
            cluster_diameter=10.0, stone_size=1.5, stone_count=0, dome_height=1.0,
        )
        assert result.get("code") == "BAD_ARGS"

    def test_negative_stone_count_rejected(self):
        ctx, _, fid = make_ctx()
        result = call_tool(
            run_jewelry_create_cluster, ctx, fid,
            cluster_diameter=10.0, stone_size=1.5, stone_count=-2, dome_height=1.0,
        )
        assert result.get("code") == "BAD_ARGS"

    def test_negative_dome_height_rejected(self):
        ctx, _, fid = make_ctx()
        result = call_tool(
            run_jewelry_create_cluster, ctx, fid,
            cluster_diameter=10.0, stone_size=1.5, stone_count=7, dome_height=-0.5,
        )
        assert result.get("code") == "BAD_ARGS"

    def test_non_integer_stone_count_rejected(self):
        ctx, _, fid = make_ctx()
        result = call_tool(
            run_jewelry_create_cluster, ctx, fid,
            cluster_diameter=10.0, stone_size=1.5, stone_count="seven", dome_height=1.0,
        )
        assert result.get("code") == "BAD_ARGS"

    def test_placement_radius_in_result(self):
        ctx, store, fid = make_ctx()
        result = call_tool(
            run_jewelry_create_cluster, ctx, fid,
            cluster_diameter=10.0, stone_size=1.5, stone_count=7, dome_height=1.0,
        )
        assert "_placement_radius" in result
        assert result["_placement_radius"] >= 0

    def test_missing_file_not_found(self):
        ctx, _, fid = make_ctx(kind="NOT_FOUND")
        result = call_tool(
            run_jewelry_create_cluster, ctx, fid,
            cluster_diameter=10.0, stone_size=1.5, stone_count=7, dome_height=1.0,
        )
        assert result.get("code") == "NOT_FOUND"

    def test_invalid_json_rejected(self):
        ctx, _, _ = make_ctx()
        raw = run_sync(run_jewelry_create_cluster(ctx, b"bad json"))
        result = json.loads(raw)
        assert result.get("code") == "BAD_ARGS"


# ============================================================================
# Bar setting — ToolSpec schema
# ============================================================================

class TestBarSpec:
    def test_name(self):
        assert jewelry_bar_spec.name == "jewelry_create_bar"

    def test_required_fields(self):
        req = jewelry_bar_spec.input_schema["required"]
        for f in ["file_id", "stone_diameter", "bar_width", "bar_height", "stone_count", "pitch"]:
            assert f in req

    def test_id_not_required(self):
        assert "id" not in jewelry_bar_spec.input_schema["required"]


# ============================================================================
# Bar setting — geometry math
# ============================================================================

class TestBarGeometry:
    def test_bar_length_formula(self):
        node = build_bar_node(
            node_id="bar-1",
            stone_diameter=2.5,
            bar_width=0.6,
            bar_height=0.8,
            stone_count=7,
            pitch=2.8,
        )
        assert math.isclose(node["_bar_length"], 7 * 2.8, rel_tol=1e-5)

    def test_bar_separation_equals_stone_diameter(self):
        node = build_bar_node(
            node_id="bar-2",
            stone_diameter=3.0,
            bar_width=0.7,
            bar_height=1.0,
            stone_count=5,
            pitch=3.5,
        )
        assert math.isclose(node["_bar_separation"], 3.0, rel_tol=1e-9)

    def test_op_field(self):
        node = build_bar_node(
            node_id="bar-3",
            stone_diameter=2.0, bar_width=0.5, bar_height=0.7,
            stone_count=3, pitch=2.5,
        )
        assert node["op"] == "jewelry_bar"

    def test_all_params_stored(self):
        node = build_bar_node(
            node_id="bar-4",
            stone_diameter=2.5,
            bar_width=0.6,
            bar_height=0.9,
            stone_count=6,
            pitch=3.0,
        )
        assert node["stone_diameter"] == 2.5
        assert node["bar_width"] == 0.6
        assert node["bar_height"] == 0.9
        assert node["stone_count"] == 6
        assert node["pitch"] == 3.0


# ============================================================================
# Bar setting — LLM tool runner
# ============================================================================

class TestBarRunner:
    def test_success(self):
        ctx, store, fid = make_ctx()
        result = call_tool(
            run_jewelry_create_bar, ctx, fid,
            stone_diameter=2.5,
            bar_width=0.6,
            bar_height=0.8,
            stone_count=7,
            pitch=2.9,
        )
        assert result.get("error") is None, result
        assert result["op"] == "jewelry_bar"
        assert result["stone_count"] == 7

    def test_node_stored(self):
        ctx, store, fid = make_ctx()
        call_tool(
            run_jewelry_create_bar, ctx, fid,
            stone_diameter=2.5, bar_width=0.6, bar_height=0.8,
            stone_count=5, pitch=2.9,
        )
        node = get_last_node(store)
        assert node["op"] == "jewelry_bar"
        assert node["stone_diameter"] == 2.5

    def test_node_id_auto(self):
        ctx, store, fid = make_ctx()
        call_tool(
            run_jewelry_create_bar, ctx, fid,
            stone_diameter=2.5, bar_width=0.6, bar_height=0.8,
            stone_count=5, pitch=2.9,
        )
        node = get_last_node(store)
        assert node["id"].startswith("jewelry_bar-")

    def test_explicit_node_id(self):
        ctx, store, fid = make_ctx()
        call_tool(
            run_jewelry_create_bar, ctx, fid,
            stone_diameter=2.5, bar_width=0.6, bar_height=0.8,
            stone_count=5, pitch=2.9,
            id="my-bar",
        )
        node = get_last_node(store)
        assert node["id"] == "my-bar"

    def test_pitch_le_stone_diameter_rejected(self):
        ctx, _, fid = make_ctx()
        result = call_tool(
            run_jewelry_create_bar, ctx, fid,
            stone_diameter=3.0, bar_width=0.6, bar_height=0.8,
            stone_count=5, pitch=2.5,  # less than stone_diameter
        )
        assert result.get("code") == "BAD_ARGS"
        assert "pitch" in result.get("error", "")

    def test_pitch_equal_to_diameter_rejected(self):
        ctx, _, fid = make_ctx()
        result = call_tool(
            run_jewelry_create_bar, ctx, fid,
            stone_diameter=3.0, bar_width=0.6, bar_height=0.8,
            stone_count=5, pitch=3.0,  # equal, not greater
        )
        assert result.get("code") == "BAD_ARGS"

    def test_zero_stone_diameter_rejected(self):
        ctx, _, fid = make_ctx()
        result = call_tool(
            run_jewelry_create_bar, ctx, fid,
            stone_diameter=0, bar_width=0.6, bar_height=0.8,
            stone_count=5, pitch=2.9,
        )
        assert result.get("code") == "BAD_ARGS"

    def test_zero_stone_count_rejected(self):
        ctx, _, fid = make_ctx()
        result = call_tool(
            run_jewelry_create_bar, ctx, fid,
            stone_diameter=2.5, bar_width=0.6, bar_height=0.8,
            stone_count=0, pitch=2.9,
        )
        assert result.get("code") == "BAD_ARGS"

    def test_negative_bar_height_rejected(self):
        ctx, _, fid = make_ctx()
        result = call_tool(
            run_jewelry_create_bar, ctx, fid,
            stone_diameter=2.5, bar_width=0.6, bar_height=-0.5,
            stone_count=5, pitch=2.9,
        )
        assert result.get("code") == "BAD_ARGS"

    def test_bar_length_in_result(self):
        ctx, store, fid = make_ctx()
        result = call_tool(
            run_jewelry_create_bar, ctx, fid,
            stone_diameter=2.5, bar_width=0.6, bar_height=0.8,
            stone_count=5, pitch=3.0,
        )
        assert "_bar_length" in result
        assert math.isclose(result["_bar_length"], 5 * 3.0, rel_tol=1e-5)

    def test_missing_file_not_found(self):
        ctx, _, fid = make_ctx(kind="NOT_FOUND")
        result = call_tool(
            run_jewelry_create_bar, ctx, fid,
            stone_diameter=2.5, bar_width=0.6, bar_height=0.8,
            stone_count=5, pitch=2.9,
        )
        assert result.get("code") == "NOT_FOUND"

    def test_invalid_json_rejected(self):
        ctx, _, _ = make_ctx()
        raw = run_sync(run_jewelry_create_bar(ctx, b"not json"))
        result = json.loads(raw)
        assert result.get("code") == "BAD_ARGS"


# ============================================================================
# Bead / grain setting — ToolSpec schema
# ============================================================================

class TestBeadGrainSpec:
    def test_name(self):
        assert jewelry_bead_grain_spec.name == "jewelry_create_bead_grain"

    def test_required_fields(self):
        req = jewelry_bead_grain_spec.input_schema["required"]
        for f in ["file_id", "stone_diameter", "bead_count_per_stone", "bead_diameter", "field_layout"]:
            assert f in req

    def test_field_layout_enum(self):
        props = jewelry_bead_grain_spec.input_schema["properties"]
        enum = props["field_layout"].get("enum", [])
        assert set(enum) == {"line", "grid"}

    def test_id_not_required(self):
        assert "id" not in jewelry_bead_grain_spec.input_schema["required"]


# ============================================================================
# Bead / grain setting — geometry math
# ============================================================================

class TestBeadGrainGeometry:
    def test_bead_pitch_deg_formula(self):
        node = build_bead_grain_node(
            node_id="bg-1",
            stone_diameter=2.0,
            bead_count_per_stone=4,
            bead_diameter=0.5,
            field_layout="line",
        )
        assert math.isclose(node["_bead_pitch_deg"], 360.0 / 4, rel_tol=1e-5)

    def test_bead_ring_radius_formula(self):
        node = build_bead_grain_node(
            node_id="bg-2",
            stone_diameter=3.0,
            bead_count_per_stone=3,
            bead_diameter=0.6,
            field_layout="grid",
        )
        assert math.isclose(node["_bead_ring_radius"], 1.5, rel_tol=1e-9)

    def test_op_field(self):
        node = build_bead_grain_node(
            node_id="bg-3",
            stone_diameter=2.0, bead_count_per_stone=2,
            bead_diameter=0.4, field_layout="line",
        )
        assert node["op"] == "jewelry_bead_grain"

    def test_all_params_stored(self):
        node = build_bead_grain_node(
            node_id="bg-4",
            stone_diameter=2.5,
            bead_count_per_stone=4,
            bead_diameter=0.55,
            field_layout="grid",
        )
        assert node["stone_diameter"] == 2.5
        assert node["bead_count_per_stone"] == 4
        assert node["bead_diameter"] == 0.55
        assert node["field_layout"] == "grid"


# ============================================================================
# Bead / grain setting — LLM tool runner
# ============================================================================

class TestBeadGrainRunner:
    def test_success_line(self):
        ctx, store, fid = make_ctx()
        result = call_tool(
            run_jewelry_create_bead_grain, ctx, fid,
            stone_diameter=2.0,
            bead_count_per_stone=3,
            bead_diameter=0.5,
            field_layout="line",
        )
        assert result.get("error") is None, result
        assert result["op"] == "jewelry_bead_grain"
        assert result["field_layout"] == "line"

    def test_success_grid(self):
        ctx, store, fid = make_ctx()
        result = call_tool(
            run_jewelry_create_bead_grain, ctx, fid,
            stone_diameter=2.0,
            bead_count_per_stone=4,
            bead_diameter=0.5,
            field_layout="grid",
        )
        assert result.get("error") is None, result
        node = get_last_node(store)
        assert node["field_layout"] == "grid"

    def test_node_id_auto(self):
        ctx, store, fid = make_ctx()
        call_tool(
            run_jewelry_create_bead_grain, ctx, fid,
            stone_diameter=2.0, bead_count_per_stone=3,
            bead_diameter=0.5, field_layout="line",
        )
        node = get_last_node(store)
        assert node["id"].startswith("jewelry_bead_grain-")

    def test_bead_count_lt_2_rejected(self):
        ctx, _, fid = make_ctx()
        result = call_tool(
            run_jewelry_create_bead_grain, ctx, fid,
            stone_diameter=2.0, bead_count_per_stone=1,
            bead_diameter=0.5, field_layout="line",
        )
        assert result.get("code") == "BAD_ARGS"
        assert "bead_count_per_stone" in result.get("error", "")

    def test_zero_bead_count_rejected(self):
        ctx, _, fid = make_ctx()
        result = call_tool(
            run_jewelry_create_bead_grain, ctx, fid,
            stone_diameter=2.0, bead_count_per_stone=0,
            bead_diameter=0.5, field_layout="line",
        )
        assert result.get("code") == "BAD_ARGS"

    def test_invalid_field_layout_rejected(self):
        ctx, _, fid = make_ctx()
        result = call_tool(
            run_jewelry_create_bead_grain, ctx, fid,
            stone_diameter=2.0, bead_count_per_stone=3,
            bead_diameter=0.5, field_layout="scatter",
        )
        assert result.get("code") == "BAD_ARGS"
        assert "field_layout" in result.get("error", "")

    def test_zero_stone_diameter_rejected(self):
        ctx, _, fid = make_ctx()
        result = call_tool(
            run_jewelry_create_bead_grain, ctx, fid,
            stone_diameter=0, bead_count_per_stone=3,
            bead_diameter=0.5, field_layout="line",
        )
        assert result.get("code") == "BAD_ARGS"

    def test_negative_bead_diameter_rejected(self):
        ctx, _, fid = make_ctx()
        result = call_tool(
            run_jewelry_create_bead_grain, ctx, fid,
            stone_diameter=2.0, bead_count_per_stone=3,
            bead_diameter=-0.1, field_layout="line",
        )
        assert result.get("code") == "BAD_ARGS"

    def test_bead_pitch_in_result(self):
        ctx, store, fid = make_ctx()
        result = call_tool(
            run_jewelry_create_bead_grain, ctx, fid,
            stone_diameter=2.0, bead_count_per_stone=4,
            bead_diameter=0.5, field_layout="line",
        )
        assert "_bead_pitch_deg" in result
        assert math.isclose(result["_bead_pitch_deg"], 90.0, rel_tol=1e-5)

    def test_missing_file_not_found(self):
        ctx, _, fid = make_ctx(kind="NOT_FOUND")
        result = call_tool(
            run_jewelry_create_bead_grain, ctx, fid,
            stone_diameter=2.0, bead_count_per_stone=3,
            bead_diameter=0.5, field_layout="line",
        )
        assert result.get("code") == "NOT_FOUND"

    def test_invalid_json_rejected(self):
        ctx, _, _ = make_ctx()
        raw = run_sync(run_jewelry_create_bead_grain(ctx, b"bad"))
        result = json.loads(raw)
        assert result.get("code") == "BAD_ARGS"

    @pytest.mark.parametrize("layout", ["line", "grid"])
    def test_all_layouts_accepted(self, layout):
        ctx, store, fid = make_ctx()
        result = call_tool(
            run_jewelry_create_bead_grain, ctx, fid,
            stone_diameter=2.0, bead_count_per_stone=3,
            bead_diameter=0.5, field_layout=layout,
        )
        assert result.get("error") is None, f"layout={layout}: {result}"


# ============================================================================
# Gypsy-pavé (star setting) — ToolSpec schema
# ============================================================================

class TestGypsyPaveSpec:
    def test_name(self):
        assert jewelry_gypsy_pave_spec.name == "jewelry_create_gypsy_pave"

    def test_required_fields(self):
        req = jewelry_gypsy_pave_spec.input_schema["required"]
        for f in ["file_id", "stone_diameter", "seat_depth", "star_ray_count"]:
            assert f in req

    def test_id_not_required(self):
        assert "id" not in jewelry_gypsy_pave_spec.input_schema["required"]


# ============================================================================
# Gypsy-pavé (star setting) — geometry math
# ============================================================================

class TestGypsyPaveGeometry:
    def test_ray_pitch_deg_formula(self):
        node = build_gypsy_pave_node(
            node_id="gp-1",
            stone_diameter=2.0,
            seat_depth=1.2,
            star_ray_count=8,
        )
        assert math.isclose(node["_ray_pitch_deg"], 360.0 / 8, rel_tol=1e-5)

    def test_seat_radius_formula(self):
        node = build_gypsy_pave_node(
            node_id="gp-2",
            stone_diameter=4.0,
            seat_depth=1.8,
            star_ray_count=6,
        )
        assert math.isclose(node["_seat_radius"], 2.0, rel_tol=1e-9)

    def test_op_field(self):
        node = build_gypsy_pave_node(
            node_id="gp-3",
            stone_diameter=3.0, seat_depth=1.5, star_ray_count=12,
        )
        assert node["op"] == "jewelry_gypsy_pave"

    def test_all_params_stored(self):
        node = build_gypsy_pave_node(
            node_id="gp-4",
            stone_diameter=2.5,
            seat_depth=1.3,
            star_ray_count=6,
        )
        assert node["stone_diameter"] == 2.5
        assert node["seat_depth"] == 1.3
        assert node["star_ray_count"] == 6


# ============================================================================
# Gypsy-pavé (star setting) — LLM tool runner
# ============================================================================

class TestGypsyPaveRunner:
    def test_success(self):
        ctx, store, fid = make_ctx()
        result = call_tool(
            run_jewelry_create_gypsy_pave, ctx, fid,
            stone_diameter=2.5,
            seat_depth=1.4,
            star_ray_count=8,
        )
        assert result.get("error") is None, result
        assert result["op"] == "jewelry_gypsy_pave"
        assert result["star_ray_count"] == 8

    def test_node_stored(self):
        ctx, store, fid = make_ctx()
        call_tool(
            run_jewelry_create_gypsy_pave, ctx, fid,
            stone_diameter=2.5, seat_depth=1.4, star_ray_count=6,
        )
        node = get_last_node(store)
        assert node["op"] == "jewelry_gypsy_pave"
        assert node["stone_diameter"] == 2.5

    def test_node_id_auto(self):
        ctx, store, fid = make_ctx()
        call_tool(
            run_jewelry_create_gypsy_pave, ctx, fid,
            stone_diameter=2.5, seat_depth=1.4, star_ray_count=6,
        )
        node = get_last_node(store)
        assert node["id"].startswith("jewelry_gypsy_pave-")

    def test_explicit_node_id(self):
        ctx, store, fid = make_ctx()
        call_tool(
            run_jewelry_create_gypsy_pave, ctx, fid,
            stone_diameter=2.5, seat_depth=1.4, star_ray_count=6,
            id="my-star",
        )
        node = get_last_node(store)
        assert node["id"] == "my-star"

    def test_ray_count_lt_4_rejected(self):
        ctx, _, fid = make_ctx()
        result = call_tool(
            run_jewelry_create_gypsy_pave, ctx, fid,
            stone_diameter=2.5, seat_depth=1.4, star_ray_count=3,
        )
        assert result.get("code") == "BAD_ARGS"
        assert "star_ray_count" in result.get("error", "")

    def test_ray_count_zero_rejected(self):
        ctx, _, fid = make_ctx()
        result = call_tool(
            run_jewelry_create_gypsy_pave, ctx, fid,
            stone_diameter=2.5, seat_depth=1.4, star_ray_count=0,
        )
        assert result.get("code") == "BAD_ARGS"

    def test_zero_stone_diameter_rejected(self):
        ctx, _, fid = make_ctx()
        result = call_tool(
            run_jewelry_create_gypsy_pave, ctx, fid,
            stone_diameter=0, seat_depth=1.4, star_ray_count=6,
        )
        assert result.get("code") == "BAD_ARGS"

    def test_negative_seat_depth_rejected(self):
        ctx, _, fid = make_ctx()
        result = call_tool(
            run_jewelry_create_gypsy_pave, ctx, fid,
            stone_diameter=2.5, seat_depth=-0.5, star_ray_count=6,
        )
        assert result.get("code") == "BAD_ARGS"

    def test_ray_pitch_in_result(self):
        ctx, store, fid = make_ctx()
        result = call_tool(
            run_jewelry_create_gypsy_pave, ctx, fid,
            stone_diameter=2.5, seat_depth=1.4, star_ray_count=6,
        )
        assert "_ray_pitch_deg" in result
        assert math.isclose(result["_ray_pitch_deg"], 60.0, rel_tol=1e-5)

    def test_missing_file_not_found(self):
        ctx, _, fid = make_ctx(kind="NOT_FOUND")
        result = call_tool(
            run_jewelry_create_gypsy_pave, ctx, fid,
            stone_diameter=2.5, seat_depth=1.4, star_ray_count=6,
        )
        assert result.get("code") == "NOT_FOUND"

    def test_invalid_json_rejected(self):
        ctx, _, _ = make_ctx()
        raw = run_sync(run_jewelry_create_gypsy_pave(ctx, b"bad"))
        result = json.loads(raw)
        assert result.get("code") == "BAD_ARGS"

    @pytest.mark.parametrize("rays", [4, 6, 8, 12, 16])
    def test_various_ray_counts_accepted(self, rays):
        ctx, store, fid = make_ctx()
        result = call_tool(
            run_jewelry_create_gypsy_pave, ctx, fid,
            stone_diameter=2.5, seat_depth=1.4, star_ray_count=rays,
        )
        assert result.get("error") is None, f"rays={rays}: {result}"


# ============================================================================
# Illusion / miracle-plate setting — ToolSpec schema
# ============================================================================

class TestIllusionSpec:
    def test_name(self):
        assert jewelry_illusion_spec.name == "jewelry_create_illusion"

    def test_required_fields(self):
        req = jewelry_illusion_spec.input_schema["required"]
        for f in ["file_id", "stone_diameter", "plate_diameter", "facet_count"]:
            assert f in req

    def test_id_not_required(self):
        assert "id" not in jewelry_illusion_spec.input_schema["required"]


# ============================================================================
# Illusion / miracle-plate setting — geometry math
# ============================================================================

class TestIllusionGeometry:
    def test_plate_wall_width_formula(self):
        node = build_illusion_node(
            node_id="il-1",
            stone_diameter=3.0,
            plate_diameter=6.0,
            facet_count=8,
        )
        expected = (6.0 - 3.0) / 2.0
        assert math.isclose(node["_plate_wall_width"], expected, rel_tol=1e-9)

    def test_facet_pitch_deg_formula(self):
        node = build_illusion_node(
            node_id="il-2",
            stone_diameter=2.0,
            plate_diameter=5.0,
            facet_count=12,
        )
        assert math.isclose(node["_facet_pitch_deg"], 360.0 / 12, rel_tol=1e-5)

    def test_op_field(self):
        node = build_illusion_node(
            node_id="il-3",
            stone_diameter=2.0, plate_diameter=4.5, facet_count=8,
        )
        assert node["op"] == "jewelry_illusion"

    def test_all_params_stored(self):
        node = build_illusion_node(
            node_id="il-4",
            stone_diameter=2.5,
            plate_diameter=5.5,
            facet_count=10,
        )
        assert node["stone_diameter"] == 2.5
        assert node["plate_diameter"] == 5.5
        assert node["facet_count"] == 10

    def test_plate_wall_width_positive(self):
        node = build_illusion_node(
            node_id="il-5",
            stone_diameter=1.5, plate_diameter=4.0, facet_count=6,
        )
        assert node["_plate_wall_width"] > 0


# ============================================================================
# Illusion / miracle-plate setting — LLM tool runner
# ============================================================================

class TestIllusionRunner:
    def test_success(self):
        ctx, store, fid = make_ctx()
        result = call_tool(
            run_jewelry_create_illusion, ctx, fid,
            stone_diameter=2.5,
            plate_diameter=5.0,
            facet_count=8,
        )
        assert result.get("error") is None, result
        assert result["op"] == "jewelry_illusion"
        assert result["facet_count"] == 8

    def test_node_stored(self):
        ctx, store, fid = make_ctx()
        call_tool(
            run_jewelry_create_illusion, ctx, fid,
            stone_diameter=2.5, plate_diameter=5.0, facet_count=8,
        )
        node = get_last_node(store)
        assert node["op"] == "jewelry_illusion"
        assert node["stone_diameter"] == 2.5
        assert node["plate_diameter"] == 5.0

    def test_node_id_auto(self):
        ctx, store, fid = make_ctx()
        call_tool(
            run_jewelry_create_illusion, ctx, fid,
            stone_diameter=2.5, plate_diameter=5.0, facet_count=8,
        )
        node = get_last_node(store)
        assert node["id"].startswith("jewelry_illusion-")

    def test_plate_not_larger_than_stone_rejected(self):
        ctx, _, fid = make_ctx()
        result = call_tool(
            run_jewelry_create_illusion, ctx, fid,
            stone_diameter=5.0, plate_diameter=4.0,  # plate < stone
            facet_count=8,
        )
        assert result.get("code") == "BAD_ARGS"
        assert "plate_diameter" in result.get("error", "")

    def test_plate_equal_to_stone_rejected(self):
        ctx, _, fid = make_ctx()
        result = call_tool(
            run_jewelry_create_illusion, ctx, fid,
            stone_diameter=4.0, plate_diameter=4.0,  # equal, not larger
            facet_count=8,
        )
        assert result.get("code") == "BAD_ARGS"

    def test_facet_count_lt_4_rejected(self):
        ctx, _, fid = make_ctx()
        result = call_tool(
            run_jewelry_create_illusion, ctx, fid,
            stone_diameter=2.5, plate_diameter=5.0, facet_count=3,
        )
        assert result.get("code") == "BAD_ARGS"
        assert "facet_count" in result.get("error", "")

    def test_zero_stone_diameter_rejected(self):
        ctx, _, fid = make_ctx()
        result = call_tool(
            run_jewelry_create_illusion, ctx, fid,
            stone_diameter=0, plate_diameter=5.0, facet_count=8,
        )
        assert result.get("code") == "BAD_ARGS"

    def test_plate_wall_width_in_result(self):
        ctx, store, fid = make_ctx()
        result = call_tool(
            run_jewelry_create_illusion, ctx, fid,
            stone_diameter=2.0, plate_diameter=6.0, facet_count=8,
        )
        assert "_plate_wall_width" in result
        assert math.isclose(result["_plate_wall_width"], (6.0 - 2.0) / 2.0, rel_tol=1e-5)

    def test_missing_file_not_found(self):
        ctx, _, fid = make_ctx(kind="NOT_FOUND")
        result = call_tool(
            run_jewelry_create_illusion, ctx, fid,
            stone_diameter=2.5, plate_diameter=5.0, facet_count=8,
        )
        assert result.get("code") == "NOT_FOUND"

    def test_invalid_json_rejected(self):
        ctx, _, _ = make_ctx()
        raw = run_sync(run_jewelry_create_illusion(ctx, b"not json"))
        result = json.loads(raw)
        assert result.get("code") == "BAD_ARGS"

    @pytest.mark.parametrize("facets", [4, 8, 12, 16])
    def test_various_facet_counts_accepted(self, facets):
        ctx, store, fid = make_ctx()
        result = call_tool(
            run_jewelry_create_illusion, ctx, fid,
            stone_diameter=2.0, plate_diameter=5.0, facet_count=facets,
        )
        assert result.get("error") is None, f"facets={facets}: {result}"


# ============================================================================
# Invisible setting — ToolSpec schema
# ============================================================================

class TestInvisibleSpec:
    def test_name(self):
        assert jewelry_invisible_spec.name == "jewelry_create_invisible"

    def test_required_fields(self):
        req = jewelry_invisible_spec.input_schema["required"]
        for f in ["file_id", "stone_size", "rail_width", "rail_height", "grid_rows", "grid_cols"]:
            assert f in req

    def test_id_not_required(self):
        assert "id" not in jewelry_invisible_spec.input_schema["required"]


# ============================================================================
# Invisible setting — geometry math
# ============================================================================

class TestInvisibleGeometry:
    def test_total_width_formula(self):
        node = build_invisible_node(
            node_id="inv-1",
            stone_size=3.0,
            rail_width=0.3,
            rail_height=0.8,
            grid_rows=2,
            grid_cols=4,
        )
        assert math.isclose(node["_total_width"], 4 * 3.0, rel_tol=1e-9)

    def test_total_height_formula(self):
        node = build_invisible_node(
            node_id="inv-2",
            stone_size=3.0,
            rail_width=0.3,
            rail_height=0.8,
            grid_rows=2,
            grid_cols=4,
        )
        assert math.isclose(node["_total_height"], 2 * 3.0, rel_tol=1e-9)

    def test_stone_count_formula(self):
        node = build_invisible_node(
            node_id="inv-3",
            stone_size=2.5,
            rail_width=0.25,
            rail_height=0.7,
            grid_rows=3,
            grid_cols=3,
        )
        assert node["_stone_count"] == 9

    def test_seat_positions_count(self):
        rows, cols = 2, 3
        node = build_invisible_node(
            node_id="inv-4",
            stone_size=2.5,
            rail_width=0.25,
            rail_height=0.7,
            grid_rows=rows,
            grid_cols=cols,
        )
        assert len(node["seat_positions"]) == rows * cols

    def test_seat_positions_row_col_fields(self):
        node = build_invisible_node(
            node_id="inv-5",
            stone_size=3.0,
            rail_width=0.3,
            rail_height=0.8,
            grid_rows=2,
            grid_cols=2,
        )
        for seat in node["seat_positions"]:
            assert "row" in seat
            assert "col" in seat
            assert "x" in seat
            assert "y" in seat

    def test_seat_x_y_centred_in_cell(self):
        ss = 4.0
        node = build_invisible_node(
            node_id="inv-6",
            stone_size=ss,
            rail_width=0.3,
            rail_height=0.8,
            grid_rows=1,
            grid_cols=2,
        )
        seats = {(s["row"], s["col"]): s for s in node["seat_positions"]}
        # First stone: col=0 → x = 0 * ss + ss/2 = 2.0
        assert math.isclose(seats[(0, 0)]["x"], ss / 2.0, rel_tol=1e-9)
        # Second stone: col=1 → x = 1 * ss + ss/2 = 6.0
        assert math.isclose(seats[(0, 1)]["x"], ss + ss / 2.0, rel_tol=1e-9)

    def test_op_field(self):
        node = build_invisible_node(
            node_id="inv-7",
            stone_size=3.0, rail_width=0.3, rail_height=0.8,
            grid_rows=2, grid_cols=2,
        )
        assert node["op"] == "jewelry_invisible"

    def test_all_params_stored(self):
        node = build_invisible_node(
            node_id="inv-8",
            stone_size=3.0,
            rail_width=0.35,
            rail_height=0.9,
            grid_rows=3,
            grid_cols=4,
        )
        assert node["stone_size"] == 3.0
        assert node["rail_width"] == 0.35
        assert node["rail_height"] == 0.9
        assert node["grid_rows"] == 3
        assert node["grid_cols"] == 4


# ============================================================================
# Invisible setting — LLM tool runner
# ============================================================================

class TestInvisibleRunner:
    def test_success(self):
        ctx, store, fid = make_ctx()
        result = call_tool(
            run_jewelry_create_invisible, ctx, fid,
            stone_size=3.0,
            rail_width=0.3,
            rail_height=0.8,
            grid_rows=2,
            grid_cols=3,
        )
        assert result.get("error") is None, result
        assert result["op"] == "jewelry_invisible"
        assert result["grid_rows"] == 2
        assert result["grid_cols"] == 3
        assert result["_stone_count"] == 6

    def test_node_stored(self):
        ctx, store, fid = make_ctx()
        call_tool(
            run_jewelry_create_invisible, ctx, fid,
            stone_size=3.0, rail_width=0.3, rail_height=0.8,
            grid_rows=2, grid_cols=3,
        )
        node = get_last_node(store)
        assert node["op"] == "jewelry_invisible"
        assert node["stone_size"] == 3.0
        assert isinstance(node["seat_positions"], list)
        assert len(node["seat_positions"]) == 6

    def test_node_id_auto(self):
        ctx, store, fid = make_ctx()
        call_tool(
            run_jewelry_create_invisible, ctx, fid,
            stone_size=3.0, rail_width=0.3, rail_height=0.8,
            grid_rows=2, grid_cols=2,
        )
        node = get_last_node(store)
        assert node["id"].startswith("jewelry_invisible-")

    def test_explicit_node_id(self):
        ctx, store, fid = make_ctx()
        call_tool(
            run_jewelry_create_invisible, ctx, fid,
            stone_size=3.0, rail_width=0.3, rail_height=0.8,
            grid_rows=2, grid_cols=2,
            id="my-invisible",
        )
        node = get_last_node(store)
        assert node["id"] == "my-invisible"

    def test_zero_stone_size_rejected(self):
        ctx, _, fid = make_ctx()
        result = call_tool(
            run_jewelry_create_invisible, ctx, fid,
            stone_size=0, rail_width=0.3, rail_height=0.8,
            grid_rows=2, grid_cols=2,
        )
        assert result.get("code") == "BAD_ARGS"

    def test_zero_grid_rows_rejected(self):
        ctx, _, fid = make_ctx()
        result = call_tool(
            run_jewelry_create_invisible, ctx, fid,
            stone_size=3.0, rail_width=0.3, rail_height=0.8,
            grid_rows=0, grid_cols=2,
        )
        assert result.get("code") == "BAD_ARGS"
        assert "grid_rows" in result.get("error", "")

    def test_zero_grid_cols_rejected(self):
        ctx, _, fid = make_ctx()
        result = call_tool(
            run_jewelry_create_invisible, ctx, fid,
            stone_size=3.0, rail_width=0.3, rail_height=0.8,
            grid_rows=2, grid_cols=0,
        )
        assert result.get("code") == "BAD_ARGS"
        assert "grid_cols" in result.get("error", "")

    def test_negative_rail_width_rejected(self):
        ctx, _, fid = make_ctx()
        result = call_tool(
            run_jewelry_create_invisible, ctx, fid,
            stone_size=3.0, rail_width=-0.1, rail_height=0.8,
            grid_rows=2, grid_cols=2,
        )
        assert result.get("code") == "BAD_ARGS"

    def test_non_integer_grid_rows_rejected(self):
        ctx, _, fid = make_ctx()
        result = call_tool(
            run_jewelry_create_invisible, ctx, fid,
            stone_size=3.0, rail_width=0.3, rail_height=0.8,
            grid_rows="two", grid_cols=2,
        )
        assert result.get("code") == "BAD_ARGS"

    def test_non_integer_grid_cols_rejected(self):
        ctx, _, fid = make_ctx()
        result = call_tool(
            run_jewelry_create_invisible, ctx, fid,
            stone_size=3.0, rail_width=0.3, rail_height=0.8,
            grid_rows=2, grid_cols="three",
        )
        assert result.get("code") == "BAD_ARGS"

    def test_total_dimensions_in_result(self):
        ctx, store, fid = make_ctx()
        result = call_tool(
            run_jewelry_create_invisible, ctx, fid,
            stone_size=3.0, rail_width=0.3, rail_height=0.8,
            grid_rows=2, grid_cols=4,
        )
        assert "_total_width" in result
        assert "_total_height" in result
        assert math.isclose(result["_total_width"], 4 * 3.0, rel_tol=1e-5)
        assert math.isclose(result["_total_height"], 2 * 3.0, rel_tol=1e-5)

    def test_1x1_grid_accepted(self):
        ctx, store, fid = make_ctx()
        result = call_tool(
            run_jewelry_create_invisible, ctx, fid,
            stone_size=3.0, rail_width=0.3, rail_height=0.8,
            grid_rows=1, grid_cols=1,
        )
        assert result.get("error") is None, result
        assert result["_stone_count"] == 1

    def test_missing_file_not_found(self):
        ctx, _, fid = make_ctx(kind="NOT_FOUND")
        result = call_tool(
            run_jewelry_create_invisible, ctx, fid,
            stone_size=3.0, rail_width=0.3, rail_height=0.8,
            grid_rows=2, grid_cols=2,
        )
        assert result.get("code") == "NOT_FOUND"

    def test_invalid_json_rejected(self):
        ctx, _, _ = make_ctx()
        raw = run_sync(run_jewelry_create_invisible(ctx, b"not json"))
        result = json.loads(raw)
        assert result.get("code") == "BAD_ARGS"

    @pytest.mark.parametrize("rows,cols", [(1, 1), (1, 4), (2, 2), (3, 3), (4, 5)])
    def test_various_grid_sizes_accepted(self, rows, cols):
        ctx, store, fid = make_ctx()
        result = call_tool(
            run_jewelry_create_invisible, ctx, fid,
            stone_size=3.0, rail_width=0.3, rail_height=0.8,
            grid_rows=rows, grid_cols=cols,
        )
        assert result.get("error") is None, f"rows={rows}, cols={cols}: {result}"
        assert result["_stone_count"] == rows * cols


# ============================================================================
# All new settings coexist in the same feature file
# ============================================================================

class TestNewSettingsCoexist:
    def test_all_five_new_settings_in_one_file(self):
        ctx, store, fid = make_ctx()
        call_tool(
            run_jewelry_create_bar, ctx, fid,
            stone_diameter=2.5, bar_width=0.6, bar_height=0.8,
            stone_count=5, pitch=2.9,
        )
        call_tool(
            run_jewelry_create_bead_grain, ctx, fid,
            stone_diameter=2.0, bead_count_per_stone=3,
            bead_diameter=0.5, field_layout="line",
        )
        call_tool(
            run_jewelry_create_gypsy_pave, ctx, fid,
            stone_diameter=2.5, seat_depth=1.4, star_ray_count=6,
        )
        call_tool(
            run_jewelry_create_illusion, ctx, fid,
            stone_diameter=2.5, plate_diameter=5.0, facet_count=8,
        )
        call_tool(
            run_jewelry_create_invisible, ctx, fid,
            stone_size=3.0, rail_width=0.3, rail_height=0.8,
            grid_rows=2, grid_cols=3,
        )
        doc = json.loads(store["content"])
        ops = [n["op"] for n in doc["features"]]
        assert "jewelry_bar" in ops
        assert "jewelry_bead_grain" in ops
        assert "jewelry_gypsy_pave" in ops
        assert "jewelry_illusion" in ops
        assert "jewelry_invisible" in ops

    @pytest.mark.parametrize("count", [1, 3, 7, 12, 19])
    def test_various_stone_counts_accepted(self, count):
        ctx, store, fid = make_ctx()
        result = call_tool(
            run_jewelry_create_cluster, ctx, fid,
            cluster_diameter=10.0, stone_size=1.5, stone_count=count, dome_height=1.0,
        )
        assert result.get("error") is None, f"count={count}: {result}"


# ============================================================================
# Cross-style node coexistence — new styles integrate with existing
# ============================================================================

class TestAllStylesCoexist:
    def test_all_nine_styles_in_same_file(self):
        ctx, store, fid = make_ctx()
        call_tool(run_jewelry_create_prong_head, ctx, fid,
                  stone_diameter=6.5, prong_count=6, prong_wire_diameter=1.0, prong_height=2.0)
        call_tool(run_jewelry_create_bezel, ctx, fid,
                  stone_diameter=6.5, wall_thickness=0.5, bezel_height=3.0, bearing_ledge_height=1.5)
        call_tool(run_jewelry_create_channel, ctx, fid,
                  stone_diameter=2.5, stone_count=5, stone_spacing=3.0,
                  rail_height=1.5, rail_thickness=0.5, floor_thickness=0.4)
        call_tool(run_jewelry_pave_array, ctx, fid,
                  region_width=10.0, region_height=10.0,
                  stone_diameter=1.5, stone_spacing=0.2, edge_margin=0.5)
        call_tool(run_jewelry_create_tension, ctx, fid,
                  stone_diameter=6.5, band_thickness=3.0, gap=5.8,
                  rail_width=0.5, rail_depth=0.3)
        call_tool(run_jewelry_create_flush, ctx, fid,
                  stone_diameter=3.5, seat_depth=1.8, bevel_width=0.2, bevel_angle_deg=45.0)
        call_tool(run_jewelry_create_halo, ctx, fid,
                  center_diameter=6.5, halo_stone_size=1.2, halo_stone_count=18,
                  halo_gap=0.15, halo_metal_width=0.4)
        call_tool(run_jewelry_create_three_stone, ctx, fid,
                  center_diameter=6.5, side_diameter=4.0, stone_spacing=0.2, base_height=1.5)
        call_tool(run_jewelry_create_cluster, ctx, fid,
                  cluster_diameter=10.0, stone_size=1.5, stone_count=7, dome_height=1.0)

        doc = json.loads(store["content"])
        ops = [n["op"] for n in doc["features"]]
        expected_ops = [
            "jewelry_prong_head",
            "jewelry_bezel",
            "jewelry_channel",
            "jewelry_pave",
            "jewelry_tension",
            "jewelry_flush",
            "jewelry_halo",
            "jewelry_three_stone",
            "jewelry_cluster",
        ]
        assert ops == expected_ops, f"ops mismatch: {ops}"


# ============================================================================
# OCC-gated: new styles
# ============================================================================

@skip_no_occ
class TestOccNewStyles:
    """OCC-gated: smoke-test node specs for new setting types via BRepPrimAPI."""

    def test_occ_tension_band_cylinder(self):
        from OCC.Core.BRepPrimAPI import BRepPrimAPI_MakeCylinder  # type: ignore
        from OCC.Core.gp import gp_Pnt, gp_Ax2, gp_Dir  # type: ignore

        node = build_tension_node(
            node_id="occ-t-1",
            stone_diameter=6.5, band_thickness=3.0, gap=5.5,
            rail_width=0.5, rail_depth=0.3,
        )
        # Build a cylinder representing the band cross-section.
        ax = gp_Ax2(gp_Pnt(0, 0, 0), gp_Dir(0, 0, 1))
        cyl = BRepPrimAPI_MakeCylinder(ax, node["_seat_radius"], node["band_thickness"])
        assert not cyl.Shape().IsNull()

    def test_occ_flush_seat_cylinder(self):
        from OCC.Core.BRepPrimAPI import BRepPrimAPI_MakeCylinder  # type: ignore
        from OCC.Core.gp import gp_Pnt, gp_Ax2, gp_Dir  # type: ignore

        node = build_flush_node(
            node_id="occ-f-1",
            stone_diameter=3.5, seat_depth=1.8, bevel_width=0.2, bevel_angle_deg=45.0,
        )
        ax = gp_Ax2(gp_Pnt(0, 0, 0), gp_Dir(0, 0, 1))
        cyl = BRepPrimAPI_MakeCylinder(ax, node["stone_diameter"] / 2.0, node["seat_depth"])
        assert not cyl.Shape().IsNull()

    def test_occ_halo_outer_cylinder(self):
        from OCC.Core.BRepPrimAPI import BRepPrimAPI_MakeCylinder  # type: ignore
        from OCC.Core.gp import gp_Pnt, gp_Ax2, gp_Dir  # type: ignore

        node = build_halo_node(
            node_id="occ-h-1",
            center_diameter=6.5, halo_stone_size=1.2, halo_stone_count=18,
            halo_gap=0.15, halo_metal_width=0.4,
        )
        ax = gp_Ax2(gp_Pnt(0, 0, 0), gp_Dir(0, 0, 1))
        cyl = BRepPrimAPI_MakeCylinder(ax, node["_halo_outer_diameter"] / 2.0, 2.0)
        assert not cyl.Shape().IsNull()

    def test_occ_cluster_dome_cylinder(self):
        from OCC.Core.BRepPrimAPI import BRepPrimAPI_MakeCylinder  # type: ignore
        from OCC.Core.gp import gp_Pnt, gp_Ax2, gp_Dir  # type: ignore

        node = build_cluster_node(
            node_id="occ-cl-1",
            cluster_diameter=10.0, stone_size=1.5, stone_count=7, dome_height=1.2,
        )
        ax = gp_Ax2(gp_Pnt(0, 0, 0), gp_Dir(0, 0, 1))
        cyl = BRepPrimAPI_MakeCylinder(ax, node["cluster_diameter"] / 2.0, node["dome_height"])
        assert not cyl.Shape().IsNull()


# ============================================================================
# v3 — Prong variant library (ToolSpec + geometry + runner)
# ============================================================================

class TestProngVariantSpec:
    def test_name(self):
        assert jewelry_prong_variant_spec.name == "jewelry_create_prong_variant"

    def test_required_fields(self):
        req = jewelry_prong_variant_spec.input_schema["required"]
        for f in ["file_id", "variant", "stone_diameter", "prong_count", "wire_gauge", "prong_height"]:
            assert f in req

    def test_variant_enum_contains_all_six(self):
        props = jewelry_prong_variant_spec.input_schema["properties"]
        enum = set(props["variant"].get("enum", []))
        expected = {"double_prong", "claw_prong", "v_prong", "fishtail_prong", "split_prong", "decorative_prong"}
        assert expected == enum

    def test_variant_profile_enum(self):
        props = jewelry_prong_variant_spec.input_schema["properties"]
        enum = set(props["variant_profile"].get("enum", []))
        assert {"round", "tapered", "filigree", "star", "leaf"} == enum

    def test_optional_fields_not_required(self):
        req = jewelry_prong_variant_spec.input_schema["required"]
        assert "variant_param" not in req
        assert "variant_profile" not in req
        assert "id" not in req


class TestProngVariantGeometry:
    def _make_node(self, variant="double_prong", **kw):
        defaults = dict(
            node_id="pv-1",
            variant=variant,
            stone_diameter=6.5,
            prong_count=4,
            wire_gauge=1.0,
            prong_height=2.0,
        )
        defaults.update(kw)
        return build_prong_variant_node(**defaults)

    def test_head_outer_diameter(self):
        node = self._make_node()
        assert math.isclose(node["_head_outer_diameter"], 6.5 + 2 * 1.0, rel_tol=1e-5)

    def test_prong_pitch_deg_4_prong(self):
        node = self._make_node(prong_count=4)
        assert math.isclose(node["_prong_pitch_deg"], 90.0, rel_tol=1e-5)

    def test_prong_pitch_deg_6_prong(self):
        node = self._make_node(prong_count=6)
        assert math.isclose(node["_prong_pitch_deg"], 60.0, rel_tol=1e-5)

    def test_op_field(self):
        node = self._make_node()
        assert node["op"] == "jewelry_prong_variant"

    def test_variant_stored(self):
        for v in ["double_prong", "claw_prong", "v_prong", "fishtail_prong", "split_prong", "decorative_prong"]:
            node = self._make_node(variant=v)
            assert node["variant"] == v

    def test_variant_param_stored(self):
        node = self._make_node(variant_param=0.6)
        assert math.isclose(node["variant_param"], 0.6, rel_tol=1e-5)

    def test_variant_profile_stored(self):
        node = self._make_node(variant="decorative_prong", variant_profile="star")
        assert node["variant_profile"] == "star"


class TestProngVariantRunner:
    @pytest.mark.parametrize("variant", [
        "double_prong", "claw_prong", "v_prong",
        "fishtail_prong", "split_prong", "decorative_prong",
    ])
    def test_all_variants_accepted(self, variant):
        ctx, store, fid = make_ctx()
        result = call_tool(
            run_jewelry_create_prong_variant, ctx, fid,
            variant=variant,
            stone_diameter=6.5,
            prong_count=4,
            wire_gauge=1.0,
            prong_height=2.0,
        )
        assert result.get("error") is None, f"variant={variant}: {result}"
        assert result["op"] == "jewelry_prong_variant"
        assert result["variant"] == variant

    def test_node_appended(self):
        ctx, store, fid = make_ctx()
        call_tool(
            run_jewelry_create_prong_variant, ctx, fid,
            variant="claw_prong",
            stone_diameter=5.0,
            prong_count=6,
            wire_gauge=0.9,
            prong_height=1.8,
        )
        node = get_last_node(store)
        assert node["op"] == "jewelry_prong_variant"
        assert node["variant"] == "claw_prong"

    def test_node_id_auto_generated(self):
        ctx, store, fid = make_ctx()
        call_tool(
            run_jewelry_create_prong_variant, ctx, fid,
            variant="split_prong",
            stone_diameter=5.0, prong_count=4,
            wire_gauge=1.0, prong_height=2.0,
        )
        node = get_last_node(store)
        assert node["id"].startswith("jewelry_prong_variant-")

    def test_explicit_id(self):
        ctx, store, fid = make_ctx()
        call_tool(
            run_jewelry_create_prong_variant, ctx, fid,
            variant="v_prong",
            stone_diameter=5.0, prong_count=4,
            wire_gauge=1.0, prong_height=2.0,
            id="my-v-prong",
        )
        node = get_last_node(store)
        assert node["id"] == "my-v-prong"

    def test_invalid_variant_rejected(self):
        ctx, _, fid = make_ctx()
        result = call_tool(
            run_jewelry_create_prong_variant, ctx, fid,
            variant="magic_prong",
            stone_diameter=6.5, prong_count=4,
            wire_gauge=1.0, prong_height=2.0,
        )
        assert result.get("code") == "BAD_ARGS"

    def test_prong_count_below_2_rejected(self):
        ctx, _, fid = make_ctx()
        result = call_tool(
            run_jewelry_create_prong_variant, ctx, fid,
            variant="double_prong",
            stone_diameter=6.5, prong_count=1,
            wire_gauge=1.0, prong_height=2.0,
        )
        assert result.get("code") == "BAD_ARGS"

    def test_negative_wire_gauge_rejected(self):
        ctx, _, fid = make_ctx()
        result = call_tool(
            run_jewelry_create_prong_variant, ctx, fid,
            variant="claw_prong",
            stone_diameter=6.5, prong_count=4,
            wire_gauge=-1.0, prong_height=2.0,
        )
        assert result.get("code") == "BAD_ARGS"

    def test_negative_variant_param_rejected(self):
        ctx, _, fid = make_ctx()
        result = call_tool(
            run_jewelry_create_prong_variant, ctx, fid,
            variant="claw_prong",
            stone_diameter=6.5, prong_count=4,
            wire_gauge=1.0, prong_height=2.0,
            variant_param=-0.5,
        )
        assert result.get("code") == "BAD_ARGS"

    def test_v_prong_angle_ge_90_rejected(self):
        ctx, _, fid = make_ctx()
        result = call_tool(
            run_jewelry_create_prong_variant, ctx, fid,
            variant="v_prong",
            stone_diameter=6.5, prong_count=4,
            wire_gauge=1.0, prong_height=2.0,
            variant_param=90.0,
        )
        assert result.get("code") == "BAD_ARGS"

    def test_split_prong_fraction_above_1_rejected(self):
        ctx, _, fid = make_ctx()
        result = call_tool(
            run_jewelry_create_prong_variant, ctx, fid,
            variant="split_prong",
            stone_diameter=6.5, prong_count=4,
            wire_gauge=1.0, prong_height=2.0,
            variant_param=1.5,
        )
        assert result.get("code") == "BAD_ARGS"

    def test_invalid_variant_profile_rejected(self):
        ctx, _, fid = make_ctx()
        result = call_tool(
            run_jewelry_create_prong_variant, ctx, fid,
            variant="decorative_prong",
            stone_diameter=6.5, prong_count=4,
            wire_gauge=1.0, prong_height=2.0,
            variant_profile="diamond_cut",
        )
        assert result.get("code") == "BAD_ARGS"

    def test_zero_stone_diameter_rejected(self):
        ctx, _, fid = make_ctx()
        result = call_tool(
            run_jewelry_create_prong_variant, ctx, fid,
            variant="double_prong",
            stone_diameter=0, prong_count=4,
            wire_gauge=1.0, prong_height=2.0,
        )
        assert result.get("code") == "BAD_ARGS"

    def test_non_uuid_file_id_rejected(self):
        ctx, _, _ = make_ctx()
        result = call_tool(
            run_jewelry_create_prong_variant, ctx, "bad-id",
            variant="double_prong",
            stone_diameter=6.5, prong_count=4,
            wire_gauge=1.0, prong_height=2.0,
        )
        assert result.get("code") == "BAD_ARGS"

    def test_missing_file_not_found(self):
        ctx, _, fid = make_ctx(kind="NOT_FOUND")
        result = call_tool(
            run_jewelry_create_prong_variant, ctx, fid,
            variant="double_prong",
            stone_diameter=6.5, prong_count=4,
            wire_gauge=1.0, prong_height=2.0,
        )
        assert result.get("code") == "NOT_FOUND"

    def test_decorative_prong_all_profiles_accepted(self):
        for profile in ["round", "tapered", "filigree", "star", "leaf"]:
            ctx, store, fid = make_ctx()
            result = call_tool(
                run_jewelry_create_prong_variant, ctx, fid,
                variant="decorative_prong",
                stone_diameter=6.5, prong_count=4,
                wire_gauge=1.0, prong_height=2.0,
                variant_profile=profile,
            )
            assert result.get("error") is None, f"profile={profile}: {result}"

    def test_v_prong_valid_angle(self):
        ctx, store, fid = make_ctx()
        result = call_tool(
            run_jewelry_create_prong_variant, ctx, fid,
            variant="v_prong",
            stone_diameter=7.0, prong_count=4,
            wire_gauge=1.1, prong_height=2.5,
            variant_param=45.0,
        )
        assert result.get("error") is None
        node = get_last_node(store)
        assert math.isclose(node["variant_param"], 45.0)


# ============================================================================
# v3 — Head + gallery builder (ToolSpec + geometry + runner)
# ============================================================================

class TestHeadGallerySpec:
    def test_name(self):
        assert jewelry_head_gallery_spec.name == "jewelry_create_head_gallery"

    def test_required_fields(self):
        req = jewelry_head_gallery_spec.input_schema["required"]
        for f in ["file_id", "head_diameter", "head_height", "gallery_height", "gallery_style", "motif_pitch"]:
            assert f in req

    def test_gallery_style_enum(self):
        props = jewelry_head_gallery_spec.input_schema["properties"]
        enum = set(props["gallery_style"].get("enum", []))
        assert {"plain", "scalloped", "milgrain_edge", "pierced", "filigree"} == enum

    def test_optional_fields_not_required(self):
        req = jewelry_head_gallery_spec.input_schema["required"]
        assert "id" not in req


class TestHeadGalleryGeometry:
    def _make_node(self, **kw):
        defaults = dict(
            node_id="hg-1",
            head_diameter=9.0,
            head_height=3.0,
            gallery_height=1.5,
            gallery_style="scalloped",
            motif_pitch=1.2,
        )
        defaults.update(kw)
        return build_head_gallery_node(**defaults)

    def test_op_field(self):
        node = self._make_node()
        assert node["op"] == "jewelry_head_gallery"

    def test_gallery_outer_diameter_equals_head(self):
        node = self._make_node(head_diameter=10.0)
        assert math.isclose(node["_gallery_outer_diameter"], 10.0, rel_tol=1e-5)

    def test_gallery_circumference(self):
        node = self._make_node(head_diameter=8.0)
        assert math.isclose(node["_gallery_circumference"], math.pi * 8.0, rel_tol=1e-5)

    def test_motif_count_plain(self):
        node = self._make_node(gallery_style="plain", motif_pitch=0.0)
        assert node["_motif_count"] == 0

    def test_motif_count_scalloped(self):
        # circumference = π * 9 ≈ 28.27; pitch = 1.2 → floor(28.27/1.2) = 23
        node = self._make_node(gallery_style="scalloped", motif_pitch=1.2, head_diameter=9.0)
        expected = max(1, int(math.floor(math.pi * 9.0 / 1.2)))
        assert node["_motif_count"] == expected

    def test_motif_pitch_stored(self):
        node = self._make_node(motif_pitch=2.0)
        assert math.isclose(node["motif_pitch"], 2.0, rel_tol=1e-5)

    def test_gallery_style_stored(self):
        for style in ["plain", "scalloped", "milgrain_edge", "pierced", "filigree"]:
            pitch = 0.0 if style == "plain" else 1.0
            node = self._make_node(gallery_style=style, motif_pitch=pitch)
            assert node["gallery_style"] == style


class TestHeadGalleryRunner:
    @pytest.mark.parametrize("style,pitch", [
        ("plain", 0.0),
        ("scalloped", 1.2),
        ("milgrain_edge", 0.5),
        ("pierced", 1.5),
        ("filigree", 2.0),
    ])
    def test_all_styles_accepted(self, style, pitch):
        ctx, store, fid = make_ctx()
        result = call_tool(
            run_jewelry_create_head_gallery, ctx, fid,
            head_diameter=9.0,
            head_height=3.0,
            gallery_height=1.5,
            gallery_style=style,
            motif_pitch=pitch,
        )
        assert result.get("error") is None, f"style={style}: {result}"
        assert result["op"] == "jewelry_head_gallery"

    def test_node_appended(self):
        ctx, store, fid = make_ctx()
        call_tool(
            run_jewelry_create_head_gallery, ctx, fid,
            head_diameter=9.0,
            head_height=3.0,
            gallery_height=1.5,
            gallery_style="filigree",
            motif_pitch=2.0,
        )
        node = get_last_node(store)
        assert node["op"] == "jewelry_head_gallery"
        assert node["gallery_style"] == "filigree"

    def test_node_id_auto_generated(self):
        ctx, store, fid = make_ctx()
        call_tool(
            run_jewelry_create_head_gallery, ctx, fid,
            head_diameter=8.0, head_height=2.5,
            gallery_height=1.0, gallery_style="plain", motif_pitch=0.0,
        )
        node = get_last_node(store)
        assert node["id"].startswith("jewelry_head_gallery-")

    def test_invalid_style_rejected(self):
        ctx, _, fid = make_ctx()
        result = call_tool(
            run_jewelry_create_head_gallery, ctx, fid,
            head_diameter=9.0, head_height=3.0,
            gallery_height=1.5, gallery_style="rope", motif_pitch=1.0,
        )
        assert result.get("code") == "BAD_ARGS"

    def test_nonplain_zero_motif_pitch_rejected(self):
        ctx, _, fid = make_ctx()
        result = call_tool(
            run_jewelry_create_head_gallery, ctx, fid,
            head_diameter=9.0, head_height=3.0,
            gallery_height=1.5, gallery_style="scalloped", motif_pitch=0.0,
        )
        assert result.get("code") == "BAD_ARGS"

    def test_negative_motif_pitch_rejected(self):
        ctx, _, fid = make_ctx()
        result = call_tool(
            run_jewelry_create_head_gallery, ctx, fid,
            head_diameter=9.0, head_height=3.0,
            gallery_height=1.5, gallery_style="plain", motif_pitch=-1.0,
        )
        assert result.get("code") == "BAD_ARGS"

    def test_zero_head_diameter_rejected(self):
        ctx, _, fid = make_ctx()
        result = call_tool(
            run_jewelry_create_head_gallery, ctx, fid,
            head_diameter=0, head_height=3.0,
            gallery_height=1.5, gallery_style="plain", motif_pitch=0.0,
        )
        assert result.get("code") == "BAD_ARGS"

    def test_non_uuid_file_id_rejected(self):
        ctx, _, _ = make_ctx()
        result = call_tool(
            run_jewelry_create_head_gallery, ctx, "bad-id",
            head_diameter=9.0, head_height=3.0,
            gallery_height=1.5, gallery_style="plain", motif_pitch=0.0,
        )
        assert result.get("code") == "BAD_ARGS"

    def test_missing_file_not_found(self):
        ctx, _, fid = make_ctx(kind="NOT_FOUND")
        result = call_tool(
            run_jewelry_create_head_gallery, ctx, fid,
            head_diameter=9.0, head_height=3.0,
            gallery_height=1.5, gallery_style="plain", motif_pitch=0.0,
        )
        assert result.get("code") == "NOT_FOUND"


# ============================================================================
# v3 — Under-bezel (ToolSpec + geometry + runner)
# ============================================================================

class TestUnderBezelSpec:
    def test_name(self):
        assert jewelry_under_bezel_spec.name == "jewelry_create_under_bezel"

    def test_required_fields(self):
        req = jewelry_under_bezel_spec.input_schema["required"]
        for f in ["file_id", "stone_diameter", "wall_thickness", "collet_height", "base_diameter", "base_thickness"]:
            assert f in req

    def test_optional_id_not_required(self):
        req = jewelry_under_bezel_spec.input_schema["required"]
        assert "id" not in req


class TestUnderBezelGeometry:
    def _make_node(self, **kw):
        defaults = dict(
            node_id="ub-1",
            stone_diameter=6.5,
            wall_thickness=0.5,
            collet_height=2.0,
            base_diameter=8.0,
            base_thickness=0.4,
        )
        defaults.update(kw)
        return build_under_bezel_node(**defaults)

    def test_op_field(self):
        node = self._make_node()
        assert node["op"] == "jewelry_under_bezel"

    def test_outer_diameter(self):
        node = self._make_node(stone_diameter=6.5, wall_thickness=0.5)
        assert math.isclose(node["_outer_diameter"], 6.5 + 2 * 0.5, rel_tol=1e-5)

    def test_collet_volume_positive(self):
        node = self._make_node()
        assert node["_collet_volume_approx"] > 0

    def test_collet_volume_math(self):
        node = self._make_node(stone_diameter=6.0, wall_thickness=0.4, collet_height=1.5)
        r_outer = (6.0 + 2 * 0.4) / 2.0
        r_inner = 6.0 / 2.0
        expected = math.pi * (r_outer ** 2 - r_inner ** 2) * 1.5
        assert math.isclose(node["_collet_volume_approx"], round(expected, 4), rel_tol=1e-4)


class TestUnderBezelRunner:
    def test_success(self):
        ctx, store, fid = make_ctx()
        result = call_tool(
            run_jewelry_create_under_bezel, ctx, fid,
            stone_diameter=6.5,
            wall_thickness=0.5,
            collet_height=2.0,
            base_diameter=8.0,
            base_thickness=0.4,
        )
        assert result.get("error") is None
        assert result["op"] == "jewelry_under_bezel"

    def test_node_appended(self):
        ctx, store, fid = make_ctx()
        call_tool(
            run_jewelry_create_under_bezel, ctx, fid,
            stone_diameter=5.0, wall_thickness=0.4,
            collet_height=1.8, base_diameter=6.5, base_thickness=0.3,
        )
        node = get_last_node(store)
        assert node["op"] == "jewelry_under_bezel"

    def test_node_id_auto_generated(self):
        ctx, store, fid = make_ctx()
        call_tool(
            run_jewelry_create_under_bezel, ctx, fid,
            stone_diameter=5.0, wall_thickness=0.4,
            collet_height=1.8, base_diameter=6.5, base_thickness=0.3,
        )
        node = get_last_node(store)
        assert node["id"].startswith("jewelry_under_bezel-")

    def test_base_diameter_too_small_rejected(self):
        ctx, _, fid = make_ctx()
        # base_diameter must be >= stone_diameter + 2*wall_thickness = 6.5 + 1.0 = 7.5
        result = call_tool(
            run_jewelry_create_under_bezel, ctx, fid,
            stone_diameter=6.5, wall_thickness=0.5,
            collet_height=2.0, base_diameter=7.0, base_thickness=0.4,
        )
        assert result.get("code") == "BAD_ARGS"

    def test_zero_collet_height_rejected(self):
        ctx, _, fid = make_ctx()
        result = call_tool(
            run_jewelry_create_under_bezel, ctx, fid,
            stone_diameter=6.5, wall_thickness=0.5,
            collet_height=0, base_diameter=8.0, base_thickness=0.4,
        )
        assert result.get("code") == "BAD_ARGS"

    def test_negative_stone_diameter_rejected(self):
        ctx, _, fid = make_ctx()
        result = call_tool(
            run_jewelry_create_under_bezel, ctx, fid,
            stone_diameter=-1.0, wall_thickness=0.5,
            collet_height=2.0, base_diameter=8.0, base_thickness=0.4,
        )
        assert result.get("code") == "BAD_ARGS"

    def test_non_uuid_file_id_rejected(self):
        ctx, _, _ = make_ctx()
        result = call_tool(
            run_jewelry_create_under_bezel, ctx, "bad",
            stone_diameter=6.5, wall_thickness=0.5,
            collet_height=2.0, base_diameter=8.0, base_thickness=0.4,
        )
        assert result.get("code") == "BAD_ARGS"

    def test_missing_file_not_found(self):
        ctx, _, fid = make_ctx(kind="NOT_FOUND")
        result = call_tool(
            run_jewelry_create_under_bezel, ctx, fid,
            stone_diameter=6.5, wall_thickness=0.5,
            collet_height=2.0, base_diameter=8.0, base_thickness=0.4,
        )
        assert result.get("code") == "NOT_FOUND"


# ============================================================================
# v3 — Peg setting (ToolSpec + geometry + runner)
# ============================================================================

class TestPegSettingSpec:
    def test_name(self):
        assert jewelry_peg_setting_spec.name == "jewelry_create_peg_setting"

    def test_required_fields(self):
        req = jewelry_peg_setting_spec.input_schema["required"]
        for f in ["file_id", "stone_diameter", "peg_diameter", "peg_length", "base_diameter", "base_thickness"]:
            assert f in req

    def test_optional_id_not_required(self):
        req = jewelry_peg_setting_spec.input_schema["required"]
        assert "id" not in req


class TestPegSettingGeometry:
    def _make_node(self, **kw):
        defaults = dict(
            node_id="ps-1",
            stone_diameter=4.0,
            peg_diameter=1.5,
            peg_length=6.0,
            base_diameter=3.0,
            base_thickness=0.5,
        )
        defaults.update(kw)
        return build_peg_setting_node(**defaults)

    def test_op_field(self):
        node = self._make_node()
        assert node["op"] == "jewelry_peg_setting"

    def test_cup_depth(self):
        node = self._make_node(stone_diameter=5.0)
        assert math.isclose(node["_cup_depth"], 5.0 * 0.2, rel_tol=1e-5)

    def test_peg_aspect_ratio(self):
        node = self._make_node(peg_diameter=1.5, peg_length=6.0)
        assert math.isclose(node["_peg_aspect_ratio"], 6.0 / 1.5, rel_tol=1e-5)

    def test_all_params_stored(self):
        node = self._make_node()
        assert node["stone_diameter"] == 4.0
        assert node["peg_diameter"] == 1.5
        assert node["peg_length"] == 6.0
        assert node["base_diameter"] == 3.0
        assert node["base_thickness"] == 0.5


class TestPegSettingRunner:
    def test_success(self):
        ctx, store, fid = make_ctx()
        result = call_tool(
            run_jewelry_create_peg_setting, ctx, fid,
            stone_diameter=4.0,
            peg_diameter=1.5,
            peg_length=6.0,
            base_diameter=3.0,
            base_thickness=0.5,
        )
        assert result.get("error") is None
        assert result["op"] == "jewelry_peg_setting"

    def test_node_appended(self):
        ctx, store, fid = make_ctx()
        call_tool(
            run_jewelry_create_peg_setting, ctx, fid,
            stone_diameter=3.5, peg_diameter=1.2,
            peg_length=5.0, base_diameter=2.5, base_thickness=0.4,
        )
        node = get_last_node(store)
        assert node["op"] == "jewelry_peg_setting"

    def test_node_id_auto_generated(self):
        ctx, store, fid = make_ctx()
        call_tool(
            run_jewelry_create_peg_setting, ctx, fid,
            stone_diameter=4.0, peg_diameter=1.5,
            peg_length=6.0, base_diameter=3.0, base_thickness=0.5,
        )
        node = get_last_node(store)
        assert node["id"].startswith("jewelry_peg_setting-")

    def test_explicit_id(self):
        ctx, store, fid = make_ctx()
        call_tool(
            run_jewelry_create_peg_setting, ctx, fid,
            stone_diameter=4.0, peg_diameter=1.5,
            peg_length=6.0, base_diameter=3.0, base_thickness=0.5,
            id="stud-peg-1",
        )
        node = get_last_node(store)
        assert node["id"] == "stud-peg-1"

    def test_base_smaller_than_peg_rejected(self):
        ctx, _, fid = make_ctx()
        result = call_tool(
            run_jewelry_create_peg_setting, ctx, fid,
            stone_diameter=4.0, peg_diameter=2.5,
            peg_length=6.0, base_diameter=1.5, base_thickness=0.5,
        )
        assert result.get("code") == "BAD_ARGS"

    def test_zero_peg_length_rejected(self):
        ctx, _, fid = make_ctx()
        result = call_tool(
            run_jewelry_create_peg_setting, ctx, fid,
            stone_diameter=4.0, peg_diameter=1.5,
            peg_length=0, base_diameter=3.0, base_thickness=0.5,
        )
        assert result.get("code") == "BAD_ARGS"

    def test_zero_stone_diameter_rejected(self):
        ctx, _, fid = make_ctx()
        result = call_tool(
            run_jewelry_create_peg_setting, ctx, fid,
            stone_diameter=0, peg_diameter=1.5,
            peg_length=6.0, base_diameter=3.0, base_thickness=0.5,
        )
        assert result.get("code") == "BAD_ARGS"

    def test_non_uuid_file_id_rejected(self):
        ctx, _, _ = make_ctx()
        result = call_tool(
            run_jewelry_create_peg_setting, ctx, "not-a-uuid",
            stone_diameter=4.0, peg_diameter=1.5,
            peg_length=6.0, base_diameter=3.0, base_thickness=0.5,
        )
        assert result.get("code") == "BAD_ARGS"

    def test_missing_file_not_found(self):
        ctx, _, fid = make_ctx(kind="NOT_FOUND")
        result = call_tool(
            run_jewelry_create_peg_setting, ctx, fid,
            stone_diameter=4.0, peg_diameter=1.5,
            peg_length=6.0, base_diameter=3.0, base_thickness=0.5,
        )
        assert result.get("code") == "NOT_FOUND"


# ============================================================================
# v3 — Crown / coronet setting (ToolSpec + geometry + runner)
# ============================================================================

class TestCoronetSpec:
    def test_name(self):
        assert jewelry_coronet_spec.name == "jewelry_create_coronet"

    def test_required_fields(self):
        req = jewelry_coronet_spec.input_schema["required"]
        for f in ["file_id", "stone_diameter", "prong_count", "crown_height", "taper", "wire_gauge"]:
            assert f in req

    def test_optional_id_not_required(self):
        req = jewelry_coronet_spec.input_schema["required"]
        assert "id" not in req


class TestCoronetGeometry:
    def _make_node(self, **kw):
        defaults = dict(
            node_id="cor-1",
            stone_diameter=7.0,
            prong_count=6,
            crown_height=3.5,
            taper=0.3,
            wire_gauge=1.1,
        )
        defaults.update(kw)
        return build_coronet_node(**defaults)

    def test_op_field(self):
        node = self._make_node()
        assert node["op"] == "jewelry_coronet"

    def test_base_diameter(self):
        node = self._make_node(stone_diameter=7.0, wire_gauge=1.1)
        assert math.isclose(node["_base_diameter"], 7.0 + 2 * 1.1, rel_tol=1e-5)

    def test_tip_diameter_less_than_base(self):
        node = self._make_node(taper=0.3)
        assert node["_tip_diameter"] < node["_base_diameter"]

    def test_tip_diameter_not_below_stone(self):
        # Taper is clamped so tip can't shrink below stone_diameter.
        node = self._make_node(stone_diameter=7.0, wire_gauge=0.5, taper=0.4)
        assert node["_tip_diameter"] >= node["stone_diameter"]

    def test_prong_pitch_6_prong(self):
        node = self._make_node(prong_count=6)
        assert math.isclose(node["_prong_pitch_deg"], 60.0, rel_tol=1e-5)

    def test_prong_pitch_8_prong(self):
        node = self._make_node(prong_count=8)
        assert math.isclose(node["_prong_pitch_deg"], 45.0, rel_tol=1e-5)

    def test_zero_taper_allowed(self):
        node = self._make_node(taper=0.0)
        # base == tip when taper=0 (clamped at stone_diameter)
        assert math.isclose(node["_base_diameter"], node["_tip_diameter"], rel_tol=1e-5)

    def test_all_params_stored(self):
        node = self._make_node()
        assert node["prong_count"] == 6
        assert node["taper"] == 0.3
        assert node["wire_gauge"] == 1.1


class TestCoronetRunner:
    def test_success(self):
        ctx, store, fid = make_ctx()
        result = call_tool(
            run_jewelry_create_coronet, ctx, fid,
            stone_diameter=7.0,
            prong_count=6,
            crown_height=3.5,
            taper=0.3,
            wire_gauge=1.1,
        )
        assert result.get("error") is None
        assert result["op"] == "jewelry_coronet"
        assert result["prong_count"] == 6

    def test_node_appended(self):
        ctx, store, fid = make_ctx()
        call_tool(
            run_jewelry_create_coronet, ctx, fid,
            stone_diameter=6.0, prong_count=8,
            crown_height=3.0, taper=0.2, wire_gauge=1.0,
        )
        node = get_last_node(store)
        assert node["op"] == "jewelry_coronet"
        assert node["prong_count"] == 8

    def test_node_id_auto_generated(self):
        ctx, store, fid = make_ctx()
        call_tool(
            run_jewelry_create_coronet, ctx, fid,
            stone_diameter=7.0, prong_count=6,
            crown_height=3.5, taper=0.3, wire_gauge=1.1,
        )
        node = get_last_node(store)
        assert node["id"].startswith("jewelry_coronet-")

    def test_explicit_id(self):
        ctx, store, fid = make_ctx()
        call_tool(
            run_jewelry_create_coronet, ctx, fid,
            stone_diameter=7.0, prong_count=6,
            crown_height=3.5, taper=0.3, wire_gauge=1.1,
            id="coronet-vintage-1",
        )
        node = get_last_node(store)
        assert node["id"] == "coronet-vintage-1"

    def test_prong_count_below_3_rejected(self):
        ctx, _, fid = make_ctx()
        result = call_tool(
            run_jewelry_create_coronet, ctx, fid,
            stone_diameter=7.0, prong_count=2,
            crown_height=3.5, taper=0.3, wire_gauge=1.1,
        )
        assert result.get("code") == "BAD_ARGS"

    def test_negative_taper_rejected(self):
        ctx, _, fid = make_ctx()
        result = call_tool(
            run_jewelry_create_coronet, ctx, fid,
            stone_diameter=7.0, prong_count=6,
            crown_height=3.5, taper=-0.5, wire_gauge=1.1,
        )
        assert result.get("code") == "BAD_ARGS"

    def test_taper_ge_wire_gauge_rejected(self):
        ctx, _, fid = make_ctx()
        result = call_tool(
            run_jewelry_create_coronet, ctx, fid,
            stone_diameter=7.0, prong_count=6,
            crown_height=3.5, taper=1.1, wire_gauge=1.1,
        )
        assert result.get("code") == "BAD_ARGS"

    def test_zero_crown_height_rejected(self):
        ctx, _, fid = make_ctx()
        result = call_tool(
            run_jewelry_create_coronet, ctx, fid,
            stone_diameter=7.0, prong_count=6,
            crown_height=0, taper=0.3, wire_gauge=1.1,
        )
        assert result.get("code") == "BAD_ARGS"

    def test_zero_stone_diameter_rejected(self):
        ctx, _, fid = make_ctx()
        result = call_tool(
            run_jewelry_create_coronet, ctx, fid,
            stone_diameter=0, prong_count=6,
            crown_height=3.5, taper=0.3, wire_gauge=1.1,
        )
        assert result.get("code") == "BAD_ARGS"

    def test_non_uuid_file_id_rejected(self):
        ctx, _, _ = make_ctx()
        result = call_tool(
            run_jewelry_create_coronet, ctx, "nope",
            stone_diameter=7.0, prong_count=6,
            crown_height=3.5, taper=0.3, wire_gauge=1.1,
        )
        assert result.get("code") == "BAD_ARGS"

    def test_missing_file_not_found(self):
        ctx, _, fid = make_ctx(kind="NOT_FOUND")
        result = call_tool(
            run_jewelry_create_coronet, ctx, fid,
            stone_diameter=7.0, prong_count=6,
            crown_height=3.5, taper=0.3, wire_gauge=1.1,
        )
        assert result.get("code") == "NOT_FOUND"

    def test_zero_taper_accepted(self):
        ctx, store, fid = make_ctx()
        result = call_tool(
            run_jewelry_create_coronet, ctx, fid,
            stone_diameter=7.0, prong_count=10,
            crown_height=4.0, taper=0.0, wire_gauge=1.2,
        )
        assert result.get("error") is None
        node = get_last_node(store)
        assert node["taper"] == 0.0

    def test_base_and_tip_diameters_in_result(self):
        ctx, store, fid = make_ctx()
        result = call_tool(
            run_jewelry_create_coronet, ctx, fid,
            stone_diameter=7.0, prong_count=6,
            crown_height=3.5, taper=0.3, wire_gauge=1.1,
        )
        assert "_base_diameter" in result
        assert "_tip_diameter" in result


# ============================================================================
# OCC-gated tests — v3 settings
# ============================================================================

@skip_no_occ
class TestV3OCC:
    """Smoke tests: use node-spec derived dimensions to build trivial OCCT
    cylinders, verifying that node geometry hints are numerically reasonable
    so the worker's primitive ops will succeed."""

    def test_occ_prong_variant_outer_cylinder(self):
        from OCC.Core.BRepPrimAPI import BRepPrimAPI_MakeCylinder  # type: ignore
        from OCC.Core.gp import gp_Pnt, gp_Ax2, gp_Dir  # type: ignore

        node = build_prong_variant_node(
            node_id="occ-pv-1",
            variant="claw_prong",
            stone_diameter=6.5,
            prong_count=6,
            wire_gauge=1.0,
            prong_height=2.5,
        )
        ax = gp_Ax2(gp_Pnt(0, 0, 0), gp_Dir(0, 0, 1))
        cyl = BRepPrimAPI_MakeCylinder(ax, node["_head_outer_diameter"] / 2.0, node["prong_height"])
        assert not cyl.Shape().IsNull()

    def test_occ_head_gallery_cylinder(self):
        from OCC.Core.BRepPrimAPI import BRepPrimAPI_MakeCylinder  # type: ignore
        from OCC.Core.gp import gp_Pnt, gp_Ax2, gp_Dir  # type: ignore

        node = build_head_gallery_node(
            node_id="occ-hg-1",
            head_diameter=9.0,
            head_height=3.0,
            gallery_height=1.5,
            gallery_style="scalloped",
            motif_pitch=1.2,
        )
        ax = gp_Ax2(gp_Pnt(0, 0, 0), gp_Dir(0, 0, 1))
        cyl = BRepPrimAPI_MakeCylinder(ax, node["_gallery_outer_diameter"] / 2.0, node["head_height"])
        assert not cyl.Shape().IsNull()

    def test_occ_under_bezel_annular_cylinder(self):
        from OCC.Core.BRepPrimAPI import BRepPrimAPI_MakeCylinder  # type: ignore
        from OCC.Core.gp import gp_Pnt, gp_Ax2, gp_Dir  # type: ignore

        node = build_under_bezel_node(
            node_id="occ-ub-1",
            stone_diameter=6.5,
            wall_thickness=0.5,
            collet_height=2.0,
            base_diameter=8.0,
            base_thickness=0.4,
        )
        ax = gp_Ax2(gp_Pnt(0, 0, 0), gp_Dir(0, 0, 1))
        cyl = BRepPrimAPI_MakeCylinder(ax, node["_outer_diameter"] / 2.0, node["collet_height"])
        assert not cyl.Shape().IsNull()

    def test_occ_peg_setting_cylinder(self):
        from OCC.Core.BRepPrimAPI import BRepPrimAPI_MakeCylinder  # type: ignore
        from OCC.Core.gp import gp_Pnt, gp_Ax2, gp_Dir  # type: ignore

        node = build_peg_setting_node(
            node_id="occ-ps-1",
            stone_diameter=4.0,
            peg_diameter=1.5,
            peg_length=6.0,
            base_diameter=3.0,
            base_thickness=0.5,
        )
        ax = gp_Ax2(gp_Pnt(0, 0, 0), gp_Dir(0, 0, 1))
        cyl = BRepPrimAPI_MakeCylinder(ax, node["peg_diameter"] / 2.0, node["peg_length"])
        assert not cyl.Shape().IsNull()

    def test_occ_coronet_cylinder(self):
        from OCC.Core.BRepPrimAPI import BRepPrimAPI_MakeCylinder  # type: ignore
        from OCC.Core.gp import gp_Pnt, gp_Ax2, gp_Dir  # type: ignore

        node = build_coronet_node(
            node_id="occ-cor-1",
            stone_diameter=7.0,
            prong_count=6,
            crown_height=3.5,
            taper=0.3,
            wire_gauge=1.1,
        )
        ax = gp_Ax2(gp_Pnt(0, 0, 0), gp_Dir(0, 0, 1))
        cyl = BRepPrimAPI_MakeCylinder(ax, node["_base_diameter"] / 2.0, node["crown_height"])
        assert not cyl.Shape().IsNull()


# ============================================================================
# V4: Suspension / dangle mount — ToolSpec schema
# ============================================================================

class TestSuspensionMountSpec:
    def test_name(self):
        assert jewelry_suspension_mount_spec.name == "jewelry_create_suspension_mount"

    def test_required_fields(self):
        req = jewelry_suspension_mount_spec.input_schema["required"]
        for f in ["file_id", "stone_diameter", "seat_style", "seat_depth",
                  "ring_wire_diameter", "ring_inner_diameter", "bail_height"]:
            assert f in req

    def test_seat_style_enum(self):
        props = jewelry_suspension_mount_spec.input_schema["properties"]
        enum = props["seat_style"].get("enum", [])
        assert set(enum) == {"bezel_cup", "prong_cup", "claw_cup"}

    def test_optional_id_not_required(self):
        req = jewelry_suspension_mount_spec.input_schema["required"]
        assert "id" not in req


# ============================================================================
# V4: Suspension mount — geometry math
# ============================================================================

class TestSuspensionMountGeometry:
    def test_ring_outer_diameter(self):
        node = build_suspension_mount_node(
            node_id="sm-1",
            stone_diameter=5.0,
            seat_style="bezel_cup",
            seat_depth=1.5,
            ring_wire_diameter=0.8,
            ring_inner_diameter=2.0,
            bail_height=1.5,
        )
        expected = 2.0 + 2 * 0.8
        assert math.isclose(node["_ring_outer_diameter"], expected, rel_tol=1e-5)

    def test_total_height(self):
        node = build_suspension_mount_node(
            node_id="sm-2",
            stone_diameter=4.0,
            seat_style="prong_cup",
            seat_depth=1.2,
            ring_wire_diameter=0.9,
            ring_inner_diameter=2.5,
            bail_height=2.0,
        )
        expected = 1.2 + 2.0 + 0.9
        assert math.isclose(node["_total_height"], expected, rel_tol=1e-5)

    def test_seat_radius(self):
        node = build_suspension_mount_node(
            node_id="sm-3",
            stone_diameter=6.0,
            seat_style="claw_cup",
            seat_depth=1.8,
            ring_wire_diameter=1.0,
            ring_inner_diameter=3.0,
            bail_height=1.5,
        )
        assert math.isclose(node["_seat_radius"], 3.0, rel_tol=1e-9)

    def test_op_field(self):
        node = build_suspension_mount_node(
            node_id="sm-4",
            stone_diameter=5.0,
            seat_style="bezel_cup",
            seat_depth=1.5,
            ring_wire_diameter=0.8,
            ring_inner_diameter=2.0,
            bail_height=1.5,
        )
        assert node["op"] == "jewelry_suspension_mount"


# ============================================================================
# V4: Suspension mount — LLM tool runner
# ============================================================================

class TestSuspensionMountRunner:
    def test_success_bezel_cup(self):
        ctx, store, fid = make_ctx()
        result = call_tool(
            run_jewelry_create_suspension_mount, ctx, fid,
            stone_diameter=5.0,
            seat_style="bezel_cup",
            seat_depth=1.5,
            ring_wire_diameter=0.8,
            ring_inner_diameter=2.5,
            bail_height=1.5,
        )
        assert result.get("error") is None, result
        assert result["op"] == "jewelry_suspension_mount"
        assert result["seat_style"] == "bezel_cup"

    def test_success_prong_cup(self):
        ctx, store, fid = make_ctx()
        result = call_tool(
            run_jewelry_create_suspension_mount, ctx, fid,
            stone_diameter=4.0,
            seat_style="prong_cup",
            seat_depth=1.0,
            ring_wire_diameter=0.9,
            ring_inner_diameter=2.0,
            bail_height=2.0,
        )
        assert result.get("error") is None
        node = get_last_node(store)
        assert node["seat_style"] == "prong_cup"

    def test_node_id_auto_generated(self):
        ctx, store, fid = make_ctx()
        call_tool(
            run_jewelry_create_suspension_mount, ctx, fid,
            stone_diameter=5.0, seat_style="bezel_cup",
            seat_depth=1.5, ring_wire_diameter=0.8,
            ring_inner_diameter=2.0, bail_height=1.5,
        )
        node = get_last_node(store)
        assert node["id"].startswith("jewelry_suspension_mount-")

    def test_ring_inner_must_exceed_wire_diameter(self):
        ctx, _, fid = make_ctx()
        result = call_tool(
            run_jewelry_create_suspension_mount, ctx, fid,
            stone_diameter=5.0, seat_style="bezel_cup",
            seat_depth=1.5, ring_wire_diameter=1.5,
            ring_inner_diameter=1.0,  # less than wire_diameter — invalid
            bail_height=1.5,
        )
        assert result.get("code") == "BAD_ARGS"
        assert "ring_inner_diameter" in result.get("error", "")

    def test_invalid_seat_style_rejected(self):
        ctx, _, fid = make_ctx()
        result = call_tool(
            run_jewelry_create_suspension_mount, ctx, fid,
            stone_diameter=5.0, seat_style="tube_cup",
            seat_depth=1.5, ring_wire_diameter=0.8,
            ring_inner_diameter=2.0, bail_height=1.5,
        )
        assert result.get("code") == "BAD_ARGS"

    def test_zero_stone_diameter_rejected(self):
        ctx, _, fid = make_ctx()
        result = call_tool(
            run_jewelry_create_suspension_mount, ctx, fid,
            stone_diameter=0, seat_style="bezel_cup",
            seat_depth=1.5, ring_wire_diameter=0.8,
            ring_inner_diameter=2.0, bail_height=1.5,
        )
        assert result.get("code") == "BAD_ARGS"

    @pytest.mark.parametrize("style", ["bezel_cup", "prong_cup", "claw_cup"])
    def test_all_seat_styles_accepted(self, style):
        ctx, store, fid = make_ctx()
        result = call_tool(
            run_jewelry_create_suspension_mount, ctx, fid,
            stone_diameter=5.0, seat_style=style,
            seat_depth=1.5, ring_wire_diameter=0.8,
            ring_inner_diameter=2.0, bail_height=1.5,
        )
        assert result.get("error") is None, f"style={style}: {result}"


# ============================================================================
# V4: V-tip protector — ToolSpec schema
# ============================================================================

class TestVtipProtectorSpec:
    def test_name(self):
        assert jewelry_vtip_protector_spec.name == "jewelry_create_vtip_protector"

    def test_required_fields(self):
        req = jewelry_vtip_protector_spec.input_schema["required"]
        for f in ["file_id", "stone_shape", "tip_count", "tip_width",
                  "tip_length", "wall_thickness", "seat_angle_deg"]:
            assert f in req

    def test_stone_shape_enum(self):
        props = jewelry_vtip_protector_spec.input_schema["properties"]
        enum = props["stone_shape"].get("enum", [])
        assert set(enum) == {"pear", "marquise", "heart", "trillion"}


# ============================================================================
# V4: V-tip protector — geometry math
# ============================================================================

class TestVtipProtectorGeometry:
    def test_tip_opening_width(self):
        node = build_vtip_protector_node(
            node_id="vt-1",
            stone_shape="marquise",
            tip_count=2,
            tip_width=0.6,
            tip_length=1.0,
            wall_thickness=0.3,
            seat_angle_deg=60.0,
        )
        half_rad = math.radians(30.0)
        expected = 2.0 * 1.0 * math.tan(half_rad)
        assert math.isclose(node["_tip_opening_width"], expected, rel_tol=1e-4)

    def test_cap_area_approx(self):
        node = build_vtip_protector_node(
            node_id="vt-2",
            stone_shape="trillion",
            tip_count=3,
            tip_width=0.8,
            tip_length=1.2,
            wall_thickness=0.25,
            seat_angle_deg=60.0,
        )
        expected = 0.5 * 0.8 * 1.2
        assert math.isclose(node["_cap_area_approx"], expected, rel_tol=1e-5)

    def test_op_field(self):
        node = build_vtip_protector_node(
            node_id="vt-3",
            stone_shape="pear",
            tip_count=1,
            tip_width=0.5,
            tip_length=0.8,
            wall_thickness=0.2,
            seat_angle_deg=45.0,
        )
        assert node["op"] == "jewelry_vtip_protector"
        assert node["stone_shape"] == "pear"
        assert node["tip_count"] == 1


# ============================================================================
# V4: V-tip protector — LLM tool runner
# ============================================================================

class TestVtipProtectorRunner:
    def test_success_pear(self):
        ctx, store, fid = make_ctx()
        result = call_tool(
            run_jewelry_create_vtip_protector, ctx, fid,
            stone_shape="pear",
            tip_count=1,
            tip_width=0.6,
            tip_length=1.0,
            wall_thickness=0.3,
            seat_angle_deg=50.0,
        )
        assert result.get("error") is None, result
        assert result["op"] == "jewelry_vtip_protector"

    def test_success_trillion(self):
        ctx, store, fid = make_ctx()
        result = call_tool(
            run_jewelry_create_vtip_protector, ctx, fid,
            stone_shape="trillion",
            tip_count=3,
            tip_width=0.7,
            tip_length=1.2,
            wall_thickness=0.3,
            seat_angle_deg=60.0,
        )
        assert result.get("error") is None
        node = get_last_node(store)
        assert node["stone_shape"] == "trillion"
        assert node["tip_count"] == 3

    def test_node_id_auto_generated(self):
        ctx, store, fid = make_ctx()
        call_tool(
            run_jewelry_create_vtip_protector, ctx, fid,
            stone_shape="marquise", tip_count=2,
            tip_width=0.5, tip_length=1.0,
            wall_thickness=0.25, seat_angle_deg=55.0,
        )
        node = get_last_node(store)
        assert node["id"].startswith("jewelry_vtip_protector-")

    def test_seat_angle_180_rejected(self):
        ctx, _, fid = make_ctx()
        result = call_tool(
            run_jewelry_create_vtip_protector, ctx, fid,
            stone_shape="pear", tip_count=1,
            tip_width=0.5, tip_length=1.0,
            wall_thickness=0.25, seat_angle_deg=180.0,
        )
        assert result.get("code") == "BAD_ARGS"

    def test_zero_tip_count_rejected(self):
        ctx, _, fid = make_ctx()
        result = call_tool(
            run_jewelry_create_vtip_protector, ctx, fid,
            stone_shape="pear", tip_count=0,
            tip_width=0.5, tip_length=1.0,
            wall_thickness=0.25, seat_angle_deg=50.0,
        )
        assert result.get("code") == "BAD_ARGS"

    def test_invalid_stone_shape_rejected(self):
        ctx, _, fid = make_ctx()
        result = call_tool(
            run_jewelry_create_vtip_protector, ctx, fid,
            stone_shape="oval",  # not in valid set
            tip_count=2, tip_width=0.5, tip_length=1.0,
            wall_thickness=0.25, seat_angle_deg=55.0,
        )
        assert result.get("code") == "BAD_ARGS"

    @pytest.mark.parametrize("shape", ["pear", "marquise", "heart", "trillion"])
    def test_all_stone_shapes_accepted(self, shape):
        ctx, store, fid = make_ctx()
        result = call_tool(
            run_jewelry_create_vtip_protector, ctx, fid,
            stone_shape=shape, tip_count=2,
            tip_width=0.6, tip_length=1.0,
            wall_thickness=0.3, seat_angle_deg=60.0,
        )
        assert result.get("error") is None, f"shape={shape}: {result}"


# ============================================================================
# V4: Bombé cluster — ToolSpec schema
# ============================================================================

class TestBombeClusterSpec:
    def test_name(self):
        assert jewelry_bombe_cluster_spec.name == "jewelry_create_bombe_cluster"

    def test_required_fields(self):
        req = jewelry_bombe_cluster_spec.input_schema["required"]
        for f in ["file_id", "dome_radius", "stone_size", "stone_count",
                  "cap_half_angle_deg", "base_height"]:
            assert f in req


# ============================================================================
# V4: Bombé cluster — geometry math
# ============================================================================

class TestBombeClusterGeometry:
    def test_base_diameter(self):
        node = build_bombe_cluster_node(
            node_id="bc-1",
            dome_radius=8.0,
            stone_size=1.2,
            stone_count=7,
            cap_half_angle_deg=60.0,
            base_height=1.5,
        )
        expected = 2.0 * 8.0 * math.sin(math.radians(60.0))
        assert math.isclose(node["_base_diameter"], expected, rel_tol=1e-4)

    def test_cap_arc_length(self):
        node = build_bombe_cluster_node(
            node_id="bc-2",
            dome_radius=10.0,
            stone_size=1.0,
            stone_count=5,
            cap_half_angle_deg=45.0,
            base_height=1.0,
        )
        expected = 10.0 * math.radians(45.0)
        assert math.isclose(node["_cap_arc_length"], expected, rel_tol=1e-4)

    def test_actual_count_matches_stone_count(self):
        node = build_bombe_cluster_node(
            node_id="bc-3",
            dome_radius=7.0,
            stone_size=1.0,
            stone_count=9,
            cap_half_angle_deg=70.0,
            base_height=1.2,
        )
        assert node["_actual_count"] == 9
        assert len(node["positions"]) == 9

    def test_single_stone_at_pole(self):
        positions = _compute_bombe_positions(dome_radius=8.0, stone_size=1.0, stone_count=1)
        assert len(positions) == 1
        assert math.isclose(positions[0]["polar_deg"], 0.0, abs_tol=1e-9)

    def test_positions_have_required_keys(self):
        positions = _compute_bombe_positions(dome_radius=8.0, stone_size=1.0, stone_count=5)
        for p in positions:
            assert "x" in p and "y" in p and "z" in p
            assert "polar_deg" in p and "azimuth_deg" in p

    def test_op_field(self):
        node = build_bombe_cluster_node(
            node_id="bc-4",
            dome_radius=8.0, stone_size=1.0,
            stone_count=5, cap_half_angle_deg=60.0, base_height=1.0,
        )
        assert node["op"] == "jewelry_bombe_cluster"


# ============================================================================
# V4: Bombé cluster — LLM tool runner
# ============================================================================

class TestBombeClusterRunner:
    def test_success(self):
        ctx, store, fid = make_ctx()
        result = call_tool(
            run_jewelry_create_bombe_cluster, ctx, fid,
            dome_radius=8.0,
            stone_size=1.2,
            stone_count=7,
            cap_half_angle_deg=60.0,
            base_height=1.5,
        )
        assert result.get("error") is None, result
        assert result["op"] == "jewelry_bombe_cluster"
        assert result["stone_count"] == 7

    def test_node_id_auto_generated(self):
        ctx, store, fid = make_ctx()
        call_tool(
            run_jewelry_create_bombe_cluster, ctx, fid,
            dome_radius=8.0, stone_size=1.0,
            stone_count=5, cap_half_angle_deg=60.0, base_height=1.0,
        )
        node = get_last_node(store)
        assert node["id"].startswith("jewelry_bombe_cluster-")

    def test_cap_angle_90_rejected(self):
        ctx, _, fid = make_ctx()
        result = call_tool(
            run_jewelry_create_bombe_cluster, ctx, fid,
            dome_radius=8.0, stone_size=1.0,
            stone_count=5, cap_half_angle_deg=90.0,  # >= 90 — invalid
            base_height=1.0,
        )
        assert result.get("code") == "BAD_ARGS"

    def test_zero_stone_count_rejected(self):
        ctx, _, fid = make_ctx()
        result = call_tool(
            run_jewelry_create_bombe_cluster, ctx, fid,
            dome_radius=8.0, stone_size=1.0,
            stone_count=0, cap_half_angle_deg=60.0, base_height=1.0,
        )
        assert result.get("code") == "BAD_ARGS"

    def test_result_contains_base_diameter(self):
        ctx, store, fid = make_ctx()
        result = call_tool(
            run_jewelry_create_bombe_cluster, ctx, fid,
            dome_radius=8.0, stone_size=1.0,
            stone_count=3, cap_half_angle_deg=60.0, base_height=1.0,
        )
        assert "_base_diameter" in result


# ============================================================================
# V4: Patterned bezel — ToolSpec schema
# ============================================================================

class TestPatternedBezelSpec:
    def test_name(self):
        assert jewelry_patterned_bezel_spec.name == "jewelry_create_patterned_bezel"

    def test_required_fields(self):
        req = jewelry_patterned_bezel_spec.input_schema["required"]
        for f in ["file_id", "stone_diameter", "wall_thickness", "bezel_height",
                  "bearing_ledge_height", "pattern", "petal_count"]:
            assert f in req

    def test_pattern_enum(self):
        props = jewelry_patterned_bezel_spec.input_schema["properties"]
        enum = props["pattern"].get("enum", [])
        assert set(enum) == {"lotus", "compass", "star", "plain"}


# ============================================================================
# V4: Patterned bezel — geometry math
# ============================================================================

class TestPatternedBezelGeometry:
    def test_outer_diameter(self):
        node = build_patterned_bezel_node(
            node_id="pb-1",
            stone_diameter=7.0,
            wall_thickness=0.5,
            bezel_height=3.0,
            bearing_ledge_height=1.2,
            pattern="lotus",
            petal_count=8,
        )
        assert math.isclose(node["_outer_diameter"], 7.0 + 2 * 0.5, rel_tol=1e-9)

    def test_petal_pitch_deg(self):
        node = build_patterned_bezel_node(
            node_id="pb-2",
            stone_diameter=6.0,
            wall_thickness=0.4,
            bezel_height=2.5,
            bearing_ledge_height=1.0,
            pattern="star",
            petal_count=12,
        )
        assert math.isclose(node["_petal_pitch_deg"], 360.0 / 12, rel_tol=1e-5)

    def test_op_field(self):
        node = build_patterned_bezel_node(
            node_id="pb-3",
            stone_diameter=5.0, wall_thickness=0.4,
            bezel_height=2.0, bearing_ledge_height=0.8,
            pattern="compass", petal_count=8,
        )
        assert node["op"] == "jewelry_patterned_bezel"
        assert node["pattern"] == "compass"


# ============================================================================
# V4: Patterned bezel — LLM tool runner
# ============================================================================

class TestPatternedBezelRunner:
    def test_success_lotus(self):
        ctx, store, fid = make_ctx()
        result = call_tool(
            run_jewelry_create_patterned_bezel, ctx, fid,
            stone_diameter=7.0,
            wall_thickness=0.5,
            bezel_height=3.0,
            bearing_ledge_height=1.2,
            pattern="lotus",
            petal_count=8,
        )
        assert result.get("error") is None, result
        assert result["op"] == "jewelry_patterned_bezel"
        assert result["pattern"] == "lotus"

    def test_success_compass(self):
        ctx, store, fid = make_ctx()
        result = call_tool(
            run_jewelry_create_patterned_bezel, ctx, fid,
            stone_diameter=6.0,
            wall_thickness=0.5,
            bezel_height=2.8,
            bearing_ledge_height=1.1,
            pattern="compass",
            petal_count=8,
        )
        assert result.get("error") is None
        node = get_last_node(store)
        assert node["pattern"] == "compass"
        assert node["petal_count"] == 8

    def test_node_id_auto_generated(self):
        ctx, store, fid = make_ctx()
        call_tool(
            run_jewelry_create_patterned_bezel, ctx, fid,
            stone_diameter=6.0, wall_thickness=0.5,
            bezel_height=2.5, bearing_ledge_height=1.0,
            pattern="star", petal_count=6,
        )
        node = get_last_node(store)
        assert node["id"].startswith("jewelry_patterned_bezel-")

    def test_bearing_ledge_must_be_less_than_height(self):
        ctx, _, fid = make_ctx()
        result = call_tool(
            run_jewelry_create_patterned_bezel, ctx, fid,
            stone_diameter=6.0, wall_thickness=0.5,
            bezel_height=2.0, bearing_ledge_height=2.0,  # equal — invalid
            pattern="lotus", petal_count=8,
        )
        assert result.get("code") == "BAD_ARGS"
        assert "bearing_ledge_height" in result.get("error", "")

    def test_petal_count_too_low_rejected(self):
        ctx, _, fid = make_ctx()
        result = call_tool(
            run_jewelry_create_patterned_bezel, ctx, fid,
            stone_diameter=6.0, wall_thickness=0.5,
            bezel_height=2.5, bearing_ledge_height=1.0,
            pattern="lotus", petal_count=2,
        )
        assert result.get("code") == "BAD_ARGS"

    def test_invalid_pattern_rejected(self):
        ctx, _, fid = make_ctx()
        result = call_tool(
            run_jewelry_create_patterned_bezel, ctx, fid,
            stone_diameter=6.0, wall_thickness=0.5,
            bezel_height=2.5, bearing_ledge_height=1.0,
            pattern="snowflake", petal_count=8,
        )
        assert result.get("code") == "BAD_ARGS"

    @pytest.mark.parametrize("pattern", ["lotus", "compass", "star", "plain"])
    def test_all_patterns_accepted(self, pattern):
        ctx, store, fid = make_ctx()
        result = call_tool(
            run_jewelry_create_patterned_bezel, ctx, fid,
            stone_diameter=6.0, wall_thickness=0.5,
            bezel_height=2.5, bearing_ledge_height=1.0,
            pattern=pattern, petal_count=8,
        )
        assert result.get("error") is None, f"pattern={pattern}: {result}"


# ============================================================================
# V4: Trellis prong — ToolSpec schema
# ============================================================================

class TestTrellisProngSpec:
    def test_name(self):
        assert jewelry_trellis_prong_spec.name == "jewelry_create_trellis_prong"

    def test_required_fields(self):
        req = jewelry_trellis_prong_spec.input_schema["required"]
        for f in ["file_id", "stone_diameter", "prong_count", "wire_gauge",
                  "prong_height", "weave_style", "cross_height"]:
            assert f in req

    def test_weave_style_enum(self):
        props = jewelry_trellis_prong_spec.input_schema["properties"]
        enum = props["weave_style"].get("enum", [])
        assert set(enum) == {"x_cross", "diagonal", "square"}


# ============================================================================
# V4: Trellis prong — geometry math
# ============================================================================

class TestTrellisProngGeometry:
    def test_outer_diameter(self):
        node = build_trellis_prong_node(
            node_id="tp-1",
            stone_diameter=6.5,
            prong_count=6,
            wire_gauge=1.0,
            prong_height=2.5,
            weave_style="x_cross",
            cross_height=1.0,
        )
        assert math.isclose(node["_outer_diameter"], 6.5 + 2 * 1.0, rel_tol=1e-9)

    def test_cross_clearance(self):
        node = build_trellis_prong_node(
            node_id="tp-2",
            stone_diameter=5.0,
            prong_count=4,
            wire_gauge=0.9,
            prong_height=2.0,
            weave_style="diagonal",
            cross_height=0.8,
        )
        assert math.isclose(node["_cross_clearance"], 0.9 * 2.0, rel_tol=1e-9)

    def test_prong_pitch_deg(self):
        node = build_trellis_prong_node(
            node_id="tp-3",
            stone_diameter=6.0,
            prong_count=8,
            wire_gauge=1.0,
            prong_height=2.5,
            weave_style="square",
            cross_height=1.0,
        )
        assert math.isclose(node["_prong_pitch_deg"], 360.0 / 8, rel_tol=1e-5)

    def test_op_field(self):
        node = build_trellis_prong_node(
            node_id="tp-4",
            stone_diameter=5.0, prong_count=4, wire_gauge=0.9,
            prong_height=2.0, weave_style="x_cross", cross_height=0.8,
        )
        assert node["op"] == "jewelry_trellis_prong"
        assert node["weave_style"] == "x_cross"


# ============================================================================
# V4: Trellis prong — LLM tool runner
# ============================================================================

class TestTrellisProngRunner:
    def test_success_x_cross(self):
        ctx, store, fid = make_ctx()
        result = call_tool(
            run_jewelry_create_trellis_prong, ctx, fid,
            stone_diameter=6.5,
            prong_count=6,
            wire_gauge=1.0,
            prong_height=2.5,
            weave_style="x_cross",
            cross_height=1.0,
        )
        assert result.get("error") is None, result
        assert result["op"] == "jewelry_trellis_prong"
        assert result["weave_style"] == "x_cross"

    def test_success_diagonal(self):
        ctx, store, fid = make_ctx()
        result = call_tool(
            run_jewelry_create_trellis_prong, ctx, fid,
            stone_diameter=5.0,
            prong_count=4,
            wire_gauge=0.9,
            prong_height=2.0,
            weave_style="diagonal",
            cross_height=0.8,
        )
        assert result.get("error") is None
        node = get_last_node(store)
        assert node["weave_style"] == "diagonal"

    def test_node_id_auto_generated(self):
        ctx, store, fid = make_ctx()
        call_tool(
            run_jewelry_create_trellis_prong, ctx, fid,
            stone_diameter=5.0, prong_count=4, wire_gauge=0.9,
            prong_height=2.0, weave_style="x_cross", cross_height=0.8,
        )
        node = get_last_node(store)
        assert node["id"].startswith("jewelry_trellis_prong-")

    def test_odd_prong_count_rejected(self):
        ctx, _, fid = make_ctx()
        result = call_tool(
            run_jewelry_create_trellis_prong, ctx, fid,
            stone_diameter=6.0, prong_count=5,  # odd — invalid
            wire_gauge=1.0, prong_height=2.5,
            weave_style="x_cross", cross_height=1.0,
        )
        assert result.get("code") == "BAD_ARGS"
        assert "even" in result.get("error", "").lower()

    def test_prong_count_too_low_rejected(self):
        ctx, _, fid = make_ctx()
        result = call_tool(
            run_jewelry_create_trellis_prong, ctx, fid,
            stone_diameter=6.0, prong_count=2,  # < 4 — invalid
            wire_gauge=1.0, prong_height=2.5,
            weave_style="x_cross", cross_height=1.0,
        )
        assert result.get("code") == "BAD_ARGS"

    def test_cross_height_must_be_less_than_prong_height(self):
        ctx, _, fid = make_ctx()
        result = call_tool(
            run_jewelry_create_trellis_prong, ctx, fid,
            stone_diameter=6.0, prong_count=4,
            wire_gauge=1.0, prong_height=2.0,
            weave_style="x_cross", cross_height=2.5,  # > prong_height — invalid
        )
        assert result.get("code") == "BAD_ARGS"
        assert "cross_height" in result.get("error", "")

    def test_invalid_weave_style_rejected(self):
        ctx, _, fid = make_ctx()
        result = call_tool(
            run_jewelry_create_trellis_prong, ctx, fid,
            stone_diameter=5.0, prong_count=4,
            wire_gauge=1.0, prong_height=2.0,
            weave_style="hexagonal", cross_height=0.8,
        )
        assert result.get("code") == "BAD_ARGS"

    @pytest.mark.parametrize("style", ["x_cross", "diagonal", "square"])
    def test_all_weave_styles_accepted(self, style):
        ctx, store, fid = make_ctx()
        result = call_tool(
            run_jewelry_create_trellis_prong, ctx, fid,
            stone_diameter=6.0, prong_count=4,
            wire_gauge=1.0, prong_height=2.5,
            weave_style=style, cross_height=1.0,
        )
        assert result.get("error") is None, f"style={style}: {result}"


# ============================================================================
# V4: Bar-channel graduated row — ToolSpec schema
# ============================================================================

class TestBarChannelGraduatedSpec:
    def test_name(self):
        assert jewelry_bar_channel_graduated_spec.name == "jewelry_create_bar_channel_graduated"

    def test_required_fields(self):
        req = jewelry_bar_channel_graduated_spec.input_schema["required"]
        for f in ["file_id", "stone_count", "largest_diameter", "smallest_diameter",
                  "stone_spacing", "bar_width", "bar_height", "floor_thickness"]:
            assert f in req


# ============================================================================
# V4: Bar-channel graduated row — geometry math
# ============================================================================

class TestBarChannelGraduatedGeometry:
    def test_single_stone(self):
        stones = _compute_graduated_row(
            stone_count=1,
            largest_diameter=3.0,
            smallest_diameter=3.0,
            stone_spacing=0.2,
        )
        assert len(stones) == 1
        assert math.isclose(stones[0]["diameter"], 3.0, rel_tol=1e-9)
        assert math.isclose(stones[0]["x_center"], 1.5, rel_tol=1e-9)

    def test_uniform_row(self):
        stones = _compute_graduated_row(
            stone_count=3,
            largest_diameter=2.0,
            smallest_diameter=2.0,
            stone_spacing=0.1,
        )
        assert len(stones) == 3
        # All diameters equal when largest == smallest
        for s in stones:
            assert math.isclose(s["diameter"], 2.0, rel_tol=1e-9)
        # Positions should be strictly increasing
        x_positions = [s["x_center"] for s in stones]
        assert x_positions == sorted(x_positions)

    def test_graduated_diameters_decreasing(self):
        stones = _compute_graduated_row(
            stone_count=5,
            largest_diameter=4.0,
            smallest_diameter=2.0,
            stone_spacing=0.1,
        )
        diameters = [s["diameter"] for s in stones]
        for i in range(len(diameters) - 1):
            assert diameters[i] >= diameters[i + 1]

    def test_total_row_length_positive(self):
        node = build_bar_channel_graduated_node(
            node_id="bcg-1",
            stone_count=5,
            largest_diameter=3.5,
            smallest_diameter=2.0,
            stone_spacing=0.15,
            bar_width=0.6,
            bar_height=1.0,
            floor_thickness=0.4,
        )
        assert node["_total_row_length"] > 0

    def test_bar_count_equals_stone_count_minus_one(self):
        node = build_bar_channel_graduated_node(
            node_id="bcg-2",
            stone_count=7,
            largest_diameter=3.0,
            smallest_diameter=1.5,
            stone_spacing=0.1,
            bar_width=0.5,
            bar_height=0.9,
            floor_thickness=0.35,
        )
        assert node["_bar_count"] == 6  # 7 stones -> 6 bars

    def test_op_field(self):
        node = build_bar_channel_graduated_node(
            node_id="bcg-3",
            stone_count=3,
            largest_diameter=3.0, smallest_diameter=2.0,
            stone_spacing=0.1, bar_width=0.5,
            bar_height=0.9, floor_thickness=0.3,
        )
        assert node["op"] == "jewelry_bar_channel_graduated"

    def test_stones_list_in_node(self):
        node = build_bar_channel_graduated_node(
            node_id="bcg-4",
            stone_count=4,
            largest_diameter=3.0, smallest_diameter=2.0,
            stone_spacing=0.1, bar_width=0.5,
            bar_height=0.9, floor_thickness=0.3,
        )
        assert len(node["stones"]) == 4
        for s in node["stones"]:
            assert "index" in s and "diameter" in s and "x_center" in s


# ============================================================================
# V4: Bar-channel graduated row — LLM tool runner
# ============================================================================

class TestBarChannelGraduatedRunner:
    def test_success(self):
        ctx, store, fid = make_ctx()
        result = call_tool(
            run_jewelry_create_bar_channel_graduated, ctx, fid,
            stone_count=5,
            largest_diameter=3.5,
            smallest_diameter=2.0,
            stone_spacing=0.15,
            bar_width=0.6,
            bar_height=1.0,
            floor_thickness=0.4,
        )
        assert result.get("error") is None, result
        assert result["op"] == "jewelry_bar_channel_graduated"
        assert result["stone_count"] == 5

    def test_success_uniform_row(self):
        ctx, store, fid = make_ctx()
        result = call_tool(
            run_jewelry_create_bar_channel_graduated, ctx, fid,
            stone_count=3,
            largest_diameter=2.5,
            smallest_diameter=2.5,  # same — uniform
            stone_spacing=0.1,
            bar_width=0.5,
            bar_height=0.8,
            floor_thickness=0.3,
        )
        assert result.get("error") is None

    def test_node_id_auto_generated(self):
        ctx, store, fid = make_ctx()
        call_tool(
            run_jewelry_create_bar_channel_graduated, ctx, fid,
            stone_count=3, largest_diameter=3.0, smallest_diameter=2.0,
            stone_spacing=0.1, bar_width=0.5, bar_height=0.9, floor_thickness=0.3,
        )
        node = get_last_node(store)
        assert node["id"].startswith("jewelry_bar_channel_graduated-")

    def test_smallest_greater_than_largest_rejected(self):
        ctx, _, fid = make_ctx()
        result = call_tool(
            run_jewelry_create_bar_channel_graduated, ctx, fid,
            stone_count=3,
            largest_diameter=2.0,
            smallest_diameter=3.0,  # larger — invalid
            stone_spacing=0.1,
            bar_width=0.5, bar_height=0.9, floor_thickness=0.3,
        )
        assert result.get("code") == "BAD_ARGS"
        assert "smallest_diameter" in result.get("error", "")

    def test_zero_stone_count_rejected(self):
        ctx, _, fid = make_ctx()
        result = call_tool(
            run_jewelry_create_bar_channel_graduated, ctx, fid,
            stone_count=0,
            largest_diameter=3.0, smallest_diameter=2.0,
            stone_spacing=0.1, bar_width=0.5, bar_height=0.9, floor_thickness=0.3,
        )
        assert result.get("code") == "BAD_ARGS"

    def test_negative_stone_spacing_rejected(self):
        ctx, _, fid = make_ctx()
        result = call_tool(
            run_jewelry_create_bar_channel_graduated, ctx, fid,
            stone_count=3,
            largest_diameter=3.0, smallest_diameter=2.0,
            stone_spacing=-0.1,  # negative — invalid
            bar_width=0.5, bar_height=0.9, floor_thickness=0.3,
        )
        assert result.get("code") == "BAD_ARGS"

    def test_result_contains_row_length_and_bar_count(self):
        ctx, store, fid = make_ctx()
        result = call_tool(
            run_jewelry_create_bar_channel_graduated, ctx, fid,
            stone_count=4, largest_diameter=3.0, smallest_diameter=1.8,
            stone_spacing=0.12, bar_width=0.5, bar_height=1.0, floor_thickness=0.35,
        )
        assert "_total_row_length" in result
        assert "_bar_count" in result
        assert result["_bar_count"] == 3  # 4 stones -> 3 bars


# ============================================================================
# OCC-gated tests — v4 settings
# ============================================================================

@skip_no_occ
class TestV4OCC:
    """Smoke tests for v4 settings: use node-spec derived dimensions to build
    trivial OCCT cylinders, verifying geometry hints are numerically reasonable."""

    def test_occ_suspension_mount_ring(self):
        from OCC.Core.BRepPrimAPI import BRepPrimAPI_MakeTorus  # type: ignore
        from OCC.Core.gp import gp_Pnt, gp_Ax2, gp_Dir  # type: ignore

        node = build_suspension_mount_node(
            node_id="occ-sm-1",
            stone_diameter=5.0,
            seat_style="bezel_cup",
            seat_depth=1.5,
            ring_wire_diameter=0.8,
            ring_inner_diameter=2.5,
            bail_height=1.5,
        )
        # Torus with major radius = (ring_inner + ring_outer) / 4, minor = ring_wire/2
        major_r = (node["ring_inner_diameter"] + node["_ring_outer_diameter"]) / 4.0
        minor_r = node["ring_wire_diameter"] / 2.0
        ax = gp_Ax2(gp_Pnt(0, 0, 0), gp_Dir(0, 0, 1))
        torus = BRepPrimAPI_MakeTorus(ax, major_r, minor_r)
        assert not torus.Shape().IsNull()

    def test_occ_vtip_protector_box(self):
        from OCC.Core.BRepPrimAPI import BRepPrimAPI_MakeBox  # type: ignore

        node = build_vtip_protector_node(
            node_id="occ-vt-1",
            stone_shape="marquise",
            tip_count=2,
            tip_width=0.6,
            tip_length=1.0,
            wall_thickness=0.3,
            seat_angle_deg=60.0,
        )
        # Box of tip_width x tip_length x wall_thickness per cap
        box = BRepPrimAPI_MakeBox(node["tip_width"], node["tip_length"], node["wall_thickness"])
        assert not box.Shape().IsNull()

    def test_occ_bombe_cluster_cylinder(self):
        from OCC.Core.BRepPrimAPI import BRepPrimAPI_MakeCylinder  # type: ignore
        from OCC.Core.gp import gp_Pnt, gp_Ax2, gp_Dir  # type: ignore

        node = build_bombe_cluster_node(
            node_id="occ-bc-1",
            dome_radius=8.0,
            stone_size=1.2,
            stone_count=7,
            cap_half_angle_deg=60.0,
            base_height=1.5,
        )
        ax = gp_Ax2(gp_Pnt(0, 0, 0), gp_Dir(0, 0, 1))
        cyl = BRepPrimAPI_MakeCylinder(ax, node["_base_diameter"] / 2.0, node["base_height"])
        assert not cyl.Shape().IsNull()

    def test_occ_patterned_bezel_cylinder(self):
        from OCC.Core.BRepPrimAPI import BRepPrimAPI_MakeCylinder  # type: ignore
        from OCC.Core.gp import gp_Pnt, gp_Ax2, gp_Dir  # type: ignore

        node = build_patterned_bezel_node(
            node_id="occ-pb-1",
            stone_diameter=7.0,
            wall_thickness=0.5,
            bezel_height=3.0,
            bearing_ledge_height=1.2,
            pattern="lotus",
            petal_count=8,
        )
        ax = gp_Ax2(gp_Pnt(0, 0, 0), gp_Dir(0, 0, 1))
        cyl = BRepPrimAPI_MakeCylinder(ax, node["_outer_diameter"] / 2.0, node["bezel_height"])
        assert not cyl.Shape().IsNull()

    def test_occ_trellis_prong_cylinder(self):
        from OCC.Core.BRepPrimAPI import BRepPrimAPI_MakeCylinder  # type: ignore
        from OCC.Core.gp import gp_Pnt, gp_Ax2, gp_Dir  # type: ignore

        node = build_trellis_prong_node(
            node_id="occ-tp-1",
            stone_diameter=6.5,
            prong_count=6,
            wire_gauge=1.0,
            prong_height=2.5,
            weave_style="x_cross",
            cross_height=1.0,
        )
        ax = gp_Ax2(gp_Pnt(0, 0, 0), gp_Dir(0, 0, 1))
        cyl = BRepPrimAPI_MakeCylinder(ax, node["_outer_diameter"] / 2.0, node["prong_height"])
        assert not cyl.Shape().IsNull()

    def test_occ_bar_channel_graduated_box(self):
        from OCC.Core.BRepPrimAPI import BRepPrimAPI_MakeBox  # type: ignore

        node = build_bar_channel_graduated_node(
            node_id="occ-bcg-1",
            stone_count=5,
            largest_diameter=3.5,
            smallest_diameter=2.0,
            stone_spacing=0.15,
            bar_width=0.6,
            bar_height=1.0,
            floor_thickness=0.4,
        )
        # Build a box of total row length × bar_height × floor_thickness
        box = BRepPrimAPI_MakeBox(
            node["_total_row_length"],
            node["bar_height"],
            node["floor_thickness"],
        )
        assert not box.Shape().IsNull()
