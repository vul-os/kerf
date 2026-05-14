"""
Tests for the feature_section tool and helpers.

Pure-Python: no database, no ProjectCtx needed for the validation tests.
The tool-registration tests use a lightweight fake pool/ctx.
"""

from __future__ import annotations

import asyncio
import json
import uuid

import pytest

from kerf_cad_core.feature_section import (
    build_section_node,
    validate_section_args,
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
    from kerf_cad_core.feature_section import run_feature_section

    args = {"file_id": str(file_id), **kwargs}
    raw = asyncio.new_event_loop().run_until_complete(
        run_feature_section(ctx, json.dumps(args).encode())
    )
    return json.loads(raw)


# ---------------------------------------------------------------------------
# validate_section_args — success paths
# ---------------------------------------------------------------------------

class TestValidateSectionArgsSuccess:
    def test_valid_xy_plane(self):
        err, code = validate_section_args(
            "pad-1",
            {"point": [0.0, 0.0, 10.0], "normal": [0.0, 0.0, 1.0]},
        )
        assert err is None
        assert code is None

    def test_valid_xz_plane(self):
        err, code = validate_section_args(
            "revolve-1",
            {"point": [0, 0, 0], "normal": [0, 1, 0]},
        )
        assert err is None
        assert code is None

    def test_valid_oblique_normal(self):
        err, code = validate_section_args(
            "loft-1",
            {"point": [5, 5, 5], "normal": [1, 1, 0]},
        )
        assert err is None
        assert code is None

    def test_normal_need_not_be_unit_length(self):
        # Worker normalises — validation only checks it is non-zero.
        err, code = validate_section_args(
            "pad-1",
            {"point": [0, 0, 0], "normal": [3, 0, 0]},
        )
        assert err is None

    def test_integer_coords_accepted(self):
        err, code = validate_section_args(
            "pad-1",
            {"point": [0, 0, 0], "normal": [0, 0, 1]},
        )
        assert err is None


# ---------------------------------------------------------------------------
# validate_section_args — error paths
# ---------------------------------------------------------------------------

class TestValidateSectionArgsErrors:
    def test_empty_target_solid_ref(self):
        err, code = validate_section_args(
            "",
            {"point": [0, 0, 0], "normal": [0, 0, 1]},
        )
        assert err is not None
        assert code == "BAD_ARGS"
        assert "target_solid_ref" in err

    def test_non_string_target_solid_ref(self):
        err, code = validate_section_args(
            123,
            {"point": [0, 0, 0], "normal": [0, 0, 1]},
        )
        assert code == "BAD_ARGS"

    def test_plane_not_dict(self):
        err, code = validate_section_args("pad-1", [0, 0, 1])
        assert code == "BAD_ARGS"
        assert "plane" in err

    def test_missing_point(self):
        err, code = validate_section_args("pad-1", {"normal": [0, 0, 1]})
        assert code == "BAD_ARGS"
        assert "point" in err

    def test_missing_normal(self):
        err, code = validate_section_args("pad-1", {"point": [0, 0, 0]})
        assert code == "BAD_ARGS"
        assert "normal" in err

    def test_point_wrong_length(self):
        err, code = validate_section_args(
            "pad-1",
            {"point": [0, 0], "normal": [0, 0, 1]},
        )
        assert code == "BAD_ARGS"
        assert "point" in err

    def test_normal_wrong_length(self):
        err, code = validate_section_args(
            "pad-1",
            {"point": [0, 0, 0], "normal": [0, 1]},
        )
        assert code == "BAD_ARGS"
        assert "normal" in err

    def test_zero_normal(self):
        err, code = validate_section_args(
            "pad-1",
            {"point": [0, 0, 0], "normal": [0, 0, 0]},
        )
        assert code == "BAD_ARGS"
        assert "zero" in err.lower() or "magnitude" in err.lower()

    def test_non_numeric_point(self):
        err, code = validate_section_args(
            "pad-1",
            {"point": ["a", 0, 0], "normal": [0, 0, 1]},
        )
        assert code == "BAD_ARGS"


# ---------------------------------------------------------------------------
# build_section_node
# ---------------------------------------------------------------------------

class TestBuildSectionNode:
    def test_basic_structure(self):
        node = build_section_node("section-1", "pad-1", [0, 0, 10], [0, 0, 1])
        assert node["id"] == "section-1"
        assert node["op"] == "section"
        assert node["target_solid_ref"] == "pad-1"
        assert node["plane"]["point"] == [0, 0, 10]
        assert node["plane"]["normal"] == [0, 0, 1]

    def test_optional_name(self):
        node = build_section_node("s-1", "pad-1", [0, 0, 0], [0, 0, 1], name="mid cut")
        assert node["name"] == "mid cut"

    def test_no_name_omitted(self):
        node = build_section_node("s-1", "pad-1", [0, 0, 0], [0, 0, 1])
        assert "name" not in node

    def test_lists_are_copies(self):
        pt = [1.0, 2.0, 3.0]
        nrm = [0.0, 0.0, 1.0]
        node = build_section_node("s-1", "pad-1", pt, nrm)
        pt[0] = 99
        assert node["plane"]["point"][0] == 1.0  # copy, not reference


# ---------------------------------------------------------------------------
# run_feature_section (integration with fake pool)
# ---------------------------------------------------------------------------

class TestRunFeatureSection:
    def test_appends_node(self):
        ctx, store, fid = make_ctx()
        result = run_tool(ctx, fid,
                          target_solid_ref="pad-1",
                          plane={"point": [0, 0, 5], "normal": [0, 0, 1]})
        # ok_payload returns the dict directly (no 'ok' key); error is signalled
        # by an 'error' key.  A successful result has 'op' == 'section'.
        assert "error" not in result
        assert result["op"] == "section"
        doc = json.loads(store["content"])
        assert len(doc["features"]) == 1
        node = doc["features"][0]
        assert node["op"] == "section"
        assert node["target_solid_ref"] == "pad-1"

    def test_auto_id_generation(self):
        ctx, store, fid = make_ctx()
        result = run_tool(ctx, fid,
                          target_solid_ref="pad-1",
                          plane={"point": [0, 0, 0], "normal": [0, 0, 1]})
        assert "error" not in result
        assert result["id"].startswith("section-")

    def test_explicit_id_honoured(self):
        ctx, store, fid = make_ctx()
        result = run_tool(ctx, fid,
                          target_solid_ref="pad-1",
                          plane={"point": [0, 0, 0], "normal": [0, 0, 1]},
                          id="my-section")
        assert result["id"] == "my-section"

    def test_bad_file_id(self):
        # A real invalid UUID is rejected early with BAD_ARGS.
        ctx, store, fid = make_ctx()
        from kerf_cad_core.feature_section import run_feature_section
        import asyncio
        raw = asyncio.new_event_loop().run_until_complete(
            run_feature_section(ctx, json.dumps({"file_id": "not-a-uuid",
                                                  "target_solid_ref": "pad-1",
                                                  "plane": {"point": [0,0,0], "normal": [0,0,1]}}).encode())
        )
        r = json.loads(raw)
        assert "error" in r
        assert r.get("code") == "BAD_ARGS"

    def test_missing_plane_returns_bad_args(self):
        ctx, store, fid = make_ctx()
        from kerf_cad_core.feature_section import run_feature_section
        import asyncio
        raw = asyncio.new_event_loop().run_until_complete(
            run_feature_section(ctx, json.dumps({"file_id": str(fid),
                                                  "target_solid_ref": "pad-1"}).encode())
        )
        r = json.loads(raw)
        assert "error" in r
        assert r.get("code") == "BAD_ARGS"
