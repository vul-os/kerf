"""
Tests for the `mode` field on the `feature_sweep1` backend tool.

Pure-Python: no database required. All tests use a lightweight fake pool/ctx
that stores content in-memory, matching the pattern in test_feature_boss_with_draft.py.

Covers:
  - Schema: mode accepted with all 3 valid values, rejects invalid strings,
    defaults to "auto" when omitted.
  - Node shape: mode field is stored in the JSON node written to the feature file.
  - Input schema: the ToolSpec declares the enum constraint.
"""

from __future__ import annotations

import asyncio
import json
import uuid

import pytest

from kerf_cad_core.surfacing import (
    feature_sweep1_spec,
    run_feature_sweep1,
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
    args = {"file_id": str(file_id), **kwargs}
    raw = asyncio.new_event_loop().run_until_complete(
        run_feature_sweep1(ctx, json.dumps(args).encode())
    )
    return json.loads(raw)


# ---------------------------------------------------------------------------
# ToolSpec schema
# ---------------------------------------------------------------------------

class TestFeatureSweep1Spec:
    def test_spec_name(self):
        assert feature_sweep1_spec.name == "feature_sweep1"

    def test_spec_has_mode_field(self):
        props = feature_sweep1_spec.input_schema["properties"]
        assert "mode" in props, "mode field missing from feature_sweep1 input schema"

    def test_mode_enum_values(self):
        props = feature_sweep1_spec.input_schema["properties"]
        enum = props["mode"].get("enum", [])
        assert set(enum) == {"auto", "frenet", "corrected_frenet"}, (
            f"Unexpected enum values: {enum}"
        )

    def test_mode_not_required(self):
        required = feature_sweep1_spec.input_schema.get("required", [])
        assert "mode" not in required, "mode should be optional, not required"

    def test_required_fields_unchanged(self):
        required = feature_sweep1_spec.input_schema.get("required", [])
        assert "file_id" in required
        assert "profile_sketch_path" in required
        assert "path_sketch_path" in required


# ---------------------------------------------------------------------------
# mode defaults to "auto"
# ---------------------------------------------------------------------------

class TestModeDefault:
    def test_mode_auto_when_omitted(self):
        ctx, store, fid = make_ctx()
        result = run_tool(
            ctx, fid,
            profile_sketch_path="/profile.sketch",
            path_sketch_path="/path.sketch",
        )
        assert result.get("error") is None
        doc = json.loads(store["content"])
        node = doc["features"][0]
        assert node["mode"] == "auto"

    def test_mode_auto_explicit(self):
        ctx, store, fid = make_ctx()
        result = run_tool(
            ctx, fid,
            profile_sketch_path="/profile.sketch",
            path_sketch_path="/path.sketch",
            mode="auto",
        )
        assert result.get("error") is None
        doc = json.loads(store["content"])
        node = doc["features"][0]
        assert node["mode"] == "auto"


# ---------------------------------------------------------------------------
# mode: all 3 valid values accepted
# ---------------------------------------------------------------------------

class TestModeValidValues:
    @pytest.mark.parametrize("mode", ["auto", "frenet", "corrected_frenet"])
    def test_valid_mode_accepted(self, mode):
        ctx, store, fid = make_ctx()
        result = run_tool(
            ctx, fid,
            profile_sketch_path="/p.sketch",
            path_sketch_path="/path.sketch",
            mode=mode,
        )
        assert result.get("error") is None, (
            f"Expected success for mode='{mode}', got error: {result.get('error')}"
        )
        doc = json.loads(store["content"])
        node = doc["features"][0]
        assert node["mode"] == mode

    def test_corrected_frenet_stored_in_node(self):
        ctx, store, fid = make_ctx()
        result = run_tool(
            ctx, fid,
            profile_sketch_path="/ring.sketch",
            path_sketch_path="/helix.sketch",
            mode="corrected_frenet",
        )
        assert result.get("error") is None
        doc = json.loads(store["content"])
        node = doc["features"][0]
        assert node["op"] == "sweep1"
        assert node["mode"] == "corrected_frenet"


# ---------------------------------------------------------------------------
# mode: invalid values rejected
# ---------------------------------------------------------------------------

class TestModeInvalidValues:
    @pytest.mark.parametrize("bad_mode", [
        "Frenet",
        "FRENET",
        "corrected-frenet",
        "corrected frenet",
        "parallel_transport",
        "  ",
        "none",
        "null",
    ])
    def test_invalid_mode_rejected(self, bad_mode):
        ctx, store, fid = make_ctx()
        result = run_tool(
            ctx, fid,
            profile_sketch_path="/p.sketch",
            path_sketch_path="/path.sketch",
            mode=bad_mode,
        )
        assert result.get("error") is not None, (
            f"Expected error for mode='{bad_mode}' but got success"
        )
        assert result.get("code") == "BAD_ARGS"

    def test_invalid_mode_does_not_modify_file(self):
        ctx, store, fid = make_ctx()
        initial = store["content"]
        run_tool(
            ctx, fid,
            profile_sketch_path="/p.sketch",
            path_sketch_path="/path.sketch",
            mode="bad_mode",
        )
        # File must not have been mutated
        assert store["content"] == initial


# ---------------------------------------------------------------------------
# Node shape
# ---------------------------------------------------------------------------

class TestNodeShape:
    def test_node_contains_expected_fields(self):
        ctx, store, fid = make_ctx()
        run_tool(
            ctx, fid,
            profile_sketch_path="/circle.sketch",
            path_sketch_path="/spine.sketch",
            scale=1.5,
            twist_deg=45.0,
            mode="frenet",
        )
        doc = json.loads(store["content"])
        node = doc["features"][0]
        assert node["op"] == "sweep1"
        assert node["profile_sketch_path"] == "/circle.sketch"
        assert node["path_sketch_path"] == "/spine.sketch"
        assert node["scale"] == 1.5
        assert node["twist_deg"] == 45.0
        assert node["mode"] == "frenet"
        assert node["id"].startswith("sweep1-")

    def test_mode_whitespace_is_stripped(self):
        ctx, store, fid = make_ctx()
        result = run_tool(
            ctx, fid,
            profile_sketch_path="/p.sketch",
            path_sketch_path="/path.sketch",
            mode="  auto  ",
        )
        # "  auto  " strips to "auto" which is valid
        assert result.get("error") is None
        doc = json.loads(store["content"])
        assert doc["features"][0]["mode"] == "auto"
