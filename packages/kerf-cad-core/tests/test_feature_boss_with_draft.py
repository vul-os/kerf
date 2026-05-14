"""
Tests for feature_boss_with_draft tool and helpers.

Pure-Python: no database, no ProjectCtx needed for the validation tests.
The tool-registration tests use a lightweight fake pool/ctx.
"""

from __future__ import annotations

import asyncio
import json
import uuid

import pytest

from kerf_cad_core.feature_boss_with_draft import (
    DRAFT_ANGLE_MAX,
    DRAFT_ANGLE_MIN,
    VALID_DIRECTIONS,
    VALID_DRAFT_DIRECTIONS,
    build_boss_with_draft_node,
    validate_boss_with_draft_args,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_ctx(initial_content: str = ""):
    """Return (ctx, store, file_id) with an in-memory fake pool."""
    store = {
        "content": initial_content or json.dumps({"version": 1, "features": []}),
        "kind": "feature",
    }
    project_id = uuid.uuid4()
    file_id = uuid.uuid4()

    class FakePool:
        def fetchone(self, query, *args):
            return (store["content"], store["kind"])

        def execute(self, query, *args):
            store["content"] = args[0]

    # Lazy import so the test file can be collected even if ProjectCtx
    # lives in a slightly different path on the CI machine.
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


def run_tool(ctx, file_id, **kwargs):
    from kerf_cad_core.feature_boss_with_draft import run_feature_boss_with_draft

    args = {"file_id": str(file_id), **kwargs}
    raw = asyncio.new_event_loop().run_until_complete(
        run_feature_boss_with_draft(ctx, json.dumps(args).encode())
    )
    return json.loads(raw)


# ---------------------------------------------------------------------------
# validate_boss_with_draft_args
# ---------------------------------------------------------------------------

class TestValidateBossWithDraftArgs:
    def test_valid_minimal(self):
        err, code = validate_boss_with_draft_args("/p.sketch", 10.0, "up", 3.0, "outward")
        assert err is None and code is None

    def test_valid_all_directions(self):
        for d in VALID_DIRECTIONS:
            err, code = validate_boss_with_draft_args("/p.sketch", 5.0, d, 2.0, "outward")
            assert err is None, f"direction '{d}' should be valid"

    def test_valid_all_draft_directions(self):
        for dd in VALID_DRAFT_DIRECTIONS:
            err, code = validate_boss_with_draft_args("/p.sketch", 5.0, "up", 2.0, dd)
            assert err is None, f"draft_direction '{dd}' should be valid"

    # sketch_path
    def test_missing_sketch_path(self):
        err, code = validate_boss_with_draft_args("", 10.0, "up", 3.0, "outward")
        assert code == "BAD_ARGS"
        assert "sketch_path" in err

    def test_sketch_path_wrong_extension(self):
        err, code = validate_boss_with_draft_args("/profile.json", 10.0, "up", 3.0, "outward")
        assert code == "BAD_ARGS"
        assert ".sketch" in err

    def test_sketch_path_none(self):
        err, code = validate_boss_with_draft_args(None, 10.0, "up", 3.0, "outward")
        assert code == "BAD_ARGS"

    # height
    def test_height_zero_rejected(self):
        err, code = validate_boss_with_draft_args("/p.sketch", 0, "up", 3.0, "outward")
        assert code == "BAD_ARGS"
        assert "height" in err

    def test_height_negative_rejected(self):
        err, code = validate_boss_with_draft_args("/p.sketch", -5, "up", 3.0, "outward")
        assert code == "BAD_ARGS"

    def test_height_not_number_rejected(self):
        err, code = validate_boss_with_draft_args("/p.sketch", "tall", "up", 3.0, "outward")
        assert code == "BAD_ARGS"

    # direction
    def test_invalid_direction_rejected(self):
        err, code = validate_boss_with_draft_args("/p.sketch", 10.0, "sideways", 3.0, "outward")
        assert code == "BAD_ARGS"
        assert "sideways" in err

    # draft_angle_deg
    def test_angle_at_min_boundary_ok(self):
        err, code = validate_boss_with_draft_args("/p.sketch", 10.0, "up", DRAFT_ANGLE_MIN, "outward")
        assert err is None

    def test_angle_at_max_boundary_ok(self):
        err, code = validate_boss_with_draft_args("/p.sketch", 10.0, "up", DRAFT_ANGLE_MAX, "outward")
        assert err is None

    def test_angle_zero_ok(self):
        # Zero is valid (degenerates to plain pad but not an error)
        err, code = validate_boss_with_draft_args("/p.sketch", 10.0, "up", 0.0, "outward")
        assert err is None

    def test_angle_exceeds_max_rejected(self):
        err, code = validate_boss_with_draft_args("/p.sketch", 10.0, "up", 30.1, "outward")
        assert code == "BAD_ARGS"
        assert "30.1" in err

    def test_angle_below_min_rejected(self):
        err, code = validate_boss_with_draft_args("/p.sketch", 10.0, "up", -35.0, "outward")
        assert code == "BAD_ARGS"
        assert "-35" in err

    def test_angle_not_number_rejected(self):
        err, code = validate_boss_with_draft_args("/p.sketch", 10.0, "up", "steep", "outward")
        assert code == "BAD_ARGS"

    # draft_direction
    def test_invalid_draft_direction_rejected(self):
        err, code = validate_boss_with_draft_args("/p.sketch", 10.0, "up", 3.0, "sideways")
        assert code == "BAD_ARGS"
        assert "sideways" in err


# ---------------------------------------------------------------------------
# build_boss_with_draft_node
# ---------------------------------------------------------------------------

class TestBuildBossWithDraftNode:
    def test_required_fields_present(self):
        node = build_boss_with_draft_node(
            "boss_with_draft-1", "/p.sketch", 20.0, "up", 5.0, "outward"
        )
        assert node["id"] == "boss_with_draft-1"
        assert node["op"] == "boss_with_draft"
        assert node["sketch_path"] == "/p.sketch"
        assert node["height"] == 20.0
        assert node["direction"] == "up"
        assert node["draft_angle_deg"] == 5.0
        assert node["draft_direction"] == "outward"
        assert "name" not in node

    def test_name_included_when_provided(self):
        node = build_boss_with_draft_node(
            "boss_with_draft-1", "/p.sketch", 10.0, "up", 3.0, "outward", name="my_boss"
        )
        assert node["name"] == "my_boss"

    def test_height_coerced_to_float(self):
        node = build_boss_with_draft_node("n", "/p.sketch", 5, "up", 2, "inward")
        assert isinstance(node["height"], float)
        assert isinstance(node["draft_angle_deg"], float)

    def test_schema_round_trip(self):
        node = build_boss_with_draft_node(
            "boss_with_draft-7", "/parts/lid.sketch", 15.0, "symmetric", -2.5, "inward"
        )
        serialised = json.dumps(node)
        restored = json.loads(serialised)
        assert restored == node


# ---------------------------------------------------------------------------
# Tool handler (fake DB)
# ---------------------------------------------------------------------------

class TestRunFeatureBossWithDraft:
    # These tests require kerf_core to be importable; they are skipped if it
    # is not installed (mirrors the pattern used in test_feature_helix.py).

    @pytest.fixture(autouse=True)
    def _skip_if_no_kerf_core(self):
        try:
            from kerf_core.utils.context import ProjectCtx  # noqa: F401
        except ImportError:
            pytest.skip("kerf_core not installed")

    def test_missing_file_id(self):
        ctx, store, fid = make_ctx()
        from kerf_cad_core.feature_boss_with_draft import run_feature_boss_with_draft

        raw = asyncio.new_event_loop().run_until_complete(
            run_feature_boss_with_draft(
                ctx,
                json.dumps({
                    "sketch_path": "/p.sketch",
                    "height": 10,
                    "draft_angle_deg": 3,
                }).encode(),
            )
        )
        result = json.loads(raw)
        assert "error" in result

    def test_missing_sketch_path(self):
        ctx, store, fid = make_ctx()
        result = run_tool(ctx, fid, height=10, draft_angle_deg=3)
        assert "error" in result

    def test_missing_height(self):
        ctx, store, fid = make_ctx()
        result = run_tool(ctx, fid, sketch_path="/p.sketch", draft_angle_deg=3)
        assert "error" in result

    def test_missing_draft_angle(self):
        ctx, store, fid = make_ctx()
        result = run_tool(ctx, fid, sketch_path="/p.sketch", height=10)
        assert "error" in result

    def test_draft_angle_out_of_range_35(self):
        ctx, store, fid = make_ctx()
        result = run_tool(ctx, fid, sketch_path="/p.sketch", height=10, draft_angle_deg=35)
        assert "error" in result
        assert result.get("code") == "BAD_ARGS"

    def test_draft_angle_out_of_range_minus_31(self):
        ctx, store, fid = make_ctx()
        result = run_tool(ctx, fid, sketch_path="/p.sketch", height=10, draft_angle_deg=-31)
        assert "error" in result
        assert result.get("code") == "BAD_ARGS"

    def test_invalid_uuid(self):
        from kerf_cad_core.feature_boss_with_draft import run_feature_boss_with_draft

        ctx, store, fid = make_ctx()
        raw = asyncio.new_event_loop().run_until_complete(
            run_feature_boss_with_draft(
                ctx,
                json.dumps({
                    "file_id": "not-a-uuid",
                    "sketch_path": "/p.sketch",
                    "height": 10,
                    "draft_angle_deg": 3,
                }).encode(),
            )
        )
        result = json.loads(raw)
        assert "error" in result

    def test_appends_node(self):
        ctx, store, fid = make_ctx()
        result = run_tool(ctx, fid, sketch_path="/p.sketch", height=20.0, draft_angle_deg=3.0)
        assert "error" not in result
        assert result["op"] == "boss_with_draft"
        doc = json.loads(store["content"])
        assert len(doc["features"]) == 1
        node = doc["features"][0]
        assert node["op"] == "boss_with_draft"
        assert node["sketch_path"] == "/p.sketch"
        assert node["height"] == 20.0
        assert node["draft_angle_deg"] == 3.0
        assert node["direction"] == "up"
        assert node["draft_direction"] == "outward"

    def test_node_id_auto_increments(self):
        ctx, store, fid = make_ctx()
        run_tool(ctx, fid, sketch_path="/p.sketch", height=10, draft_angle_deg=2)
        run_tool(ctx, fid, sketch_path="/p.sketch", height=10, draft_angle_deg=2)
        doc = json.loads(store["content"])
        assert doc["features"][0]["id"] == "boss_with_draft-1"
        assert doc["features"][1]["id"] == "boss_with_draft-2"

    def test_explicit_node_id(self):
        ctx, store, fid = make_ctx()
        result = run_tool(
            ctx, fid, sketch_path="/p.sketch", height=10, draft_angle_deg=2, id="custom-boss"
        )
        assert result["id"] == "custom-boss"
        doc = json.loads(store["content"])
        assert doc["features"][0]["id"] == "custom-boss"

    def test_angle_zero_emits_hint(self):
        ctx, store, fid = make_ctx()
        result = run_tool(ctx, fid, sketch_path="/p.sketch", height=10, draft_angle_deg=0)
        assert "error" not in result
        assert "hint" in result

    def test_direction_down_stored(self):
        ctx, store, fid = make_ctx()
        run_tool(ctx, fid, sketch_path="/p.sketch", height=15, draft_angle_deg=1, direction="down")
        doc = json.loads(store["content"])
        assert doc["features"][0]["direction"] == "down"

    def test_direction_symmetric_stored(self):
        ctx, store, fid = make_ctx()
        run_tool(
            ctx, fid, sketch_path="/p.sketch", height=15, draft_angle_deg=1,
            direction="symmetric"
        )
        doc = json.loads(store["content"])
        assert doc["features"][0]["direction"] == "symmetric"

    def test_draft_direction_inward_stored(self):
        ctx, store, fid = make_ctx()
        run_tool(
            ctx, fid, sketch_path="/p.sketch", height=10, draft_angle_deg=5,
            draft_direction="inward"
        )
        doc = json.loads(store["content"])
        assert doc["features"][0]["draft_direction"] == "inward"

    def test_name_stored(self):
        ctx, store, fid = make_ctx()
        run_tool(
            ctx, fid, sketch_path="/p.sketch", height=10, draft_angle_deg=3, name="housing_boss"
        )
        doc = json.loads(store["content"])
        assert doc["features"][0]["name"] == "housing_boss"

    def test_boundary_angle_plus_30(self):
        ctx, store, fid = make_ctx()
        result = run_tool(ctx, fid, sketch_path="/p.sketch", height=10, draft_angle_deg=30)
        assert "error" not in result

    def test_boundary_angle_minus_30(self):
        ctx, store, fid = make_ctx()
        result = run_tool(ctx, fid, sketch_path="/p.sketch", height=10, draft_angle_deg=-30)
        assert "error" not in result

    def test_op_field_in_payload(self):
        ctx, store, fid = make_ctx()
        result = run_tool(ctx, fid, sketch_path="/p.sketch", height=10, draft_angle_deg=3)
        assert result.get("op") == "boss_with_draft"

    def test_file_id_in_payload(self):
        ctx, store, fid = make_ctx()
        result = run_tool(ctx, fid, sketch_path="/p.sketch", height=10, draft_angle_deg=3)
        assert result.get("file_id") == str(fid)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
