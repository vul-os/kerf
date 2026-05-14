"""
Tests for the feature_loft tool and helpers.

Pure-Python: no database, no ProjectCtx needed for the validation tests.
The tool-registration tests use a lightweight fake pool/ctx.
"""

from __future__ import annotations

import asyncio
import json
import uuid

import pytest

from kerf_cad_core.feature_loft import (
    VALID_CONTINUITY,
    build_loft_node,
    validate_loft_args,
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
    from kerf_cad_core.feature_loft import run_feature_loft

    args = {"file_id": str(file_id), **kwargs}
    raw = asyncio.new_event_loop().run_until_complete(
        run_feature_loft(ctx, json.dumps(args).encode())
    )
    return json.loads(raw)


# ---------------------------------------------------------------------------
# validate_loft_args
# ---------------------------------------------------------------------------

class TestValidateLoftArgs:
    TWO_PATHS = ["/p1.sketch", "/p2.sketch"]
    THREE_PATHS = ["/p1.sketch", "/p2.sketch", "/p3.sketch"]

    def test_valid_minimal(self):
        err, code = validate_loft_args(self.TWO_PATHS, False, False, False, "C0")
        assert err is None and code is None

    def test_valid_symmetric_two_profiles(self):
        err, code = validate_loft_args(self.TWO_PATHS, False, False, True, "C0")
        assert err is None and code is None

    def test_valid_closed_three_profiles(self):
        err, code = validate_loft_args(self.THREE_PATHS, False, True, False, "C0")
        assert err is None and code is None

    def test_valid_all_continuity(self):
        for cont in VALID_CONTINUITY:
            err, code = validate_loft_args(self.TWO_PATHS, False, False, False, cont)
            assert err is None, f"continuity '{cont}' should be valid"

    # -- profile_sketch_paths ------------------------------------------------

    def test_not_a_list(self):
        err, code = validate_loft_args("/p1.sketch", False, False, False, "C0")
        assert code == "BAD_ARGS"
        assert "list" in err

    def test_too_few_paths(self):
        err, code = validate_loft_args(["/p1.sketch"], False, False, False, "C0")
        assert code == "BAD_ARGS"
        assert "2" in err

    def test_empty_list(self):
        err, code = validate_loft_args([], False, False, False, "C0")
        assert code == "BAD_ARGS"

    def test_non_string_path(self):
        err, code = validate_loft_args(["/p1.sketch", 42], False, False, False, "C0")
        assert code == "BAD_ARGS"

    def test_wrong_extension(self):
        err, code = validate_loft_args(["/p1.sketch", "/p2.json"], False, False, False, "C0")
        assert code == "BAD_ARGS"
        assert ".sketch" in err

    # -- symmetric constraints -----------------------------------------------

    def test_symmetric_requires_exactly_2_profiles(self):
        err, code = validate_loft_args(self.THREE_PATHS, False, False, True, "C0")
        assert code == "BAD_ARGS"
        assert "2" in err

    def test_symmetric_one_profile_rejected(self):
        # 1 profile normally errors for count < 2, but let's be explicit
        err, code = validate_loft_args(["/p1.sketch"], False, False, True, "C0")
        assert code == "BAD_ARGS"

    def test_symmetric_and_closed_rejected(self):
        err, code = validate_loft_args(self.TWO_PATHS, False, True, True, "C0")
        assert code == "BAD_ARGS"
        assert "symmetric" in err.lower() or "closed" in err.lower()

    # -- closed constraints --------------------------------------------------

    def test_closed_with_two_profiles_rejected(self):
        err, code = validate_loft_args(self.TWO_PATHS, False, True, False, "C0")
        assert code == "BAD_ARGS"
        assert "3" in err

    # -- continuity ----------------------------------------------------------

    def test_invalid_continuity(self):
        err, code = validate_loft_args(self.TWO_PATHS, False, False, False, "G1")
        assert code == "BAD_ARGS"
        assert "G1" in err

    def test_continuity_case_insensitive(self):
        # validate_loft_args uppercases internally
        err, code = validate_loft_args(self.TWO_PATHS, False, False, False, "c1")
        assert err is None

    # -- type errors on bool fields ------------------------------------------

    def test_ruled_not_bool(self):
        err, code = validate_loft_args(self.TWO_PATHS, "yes", False, False, "C0")
        assert code == "BAD_ARGS"
        assert "ruled" in err

    def test_closed_not_bool(self):
        err, code = validate_loft_args(self.TWO_PATHS, False, "yes", False, "C0")
        assert code == "BAD_ARGS"
        assert "closed" in err

    def test_symmetric_not_bool(self):
        err, code = validate_loft_args(self.TWO_PATHS, False, False, "yes", "C0")
        assert code == "BAD_ARGS"
        assert "symmetric" in err


# ---------------------------------------------------------------------------
# build_loft_node
# ---------------------------------------------------------------------------

class TestBuildLoftNode:
    def test_required_fields_present(self):
        node = build_loft_node("loft-1", ["/p1.sketch", "/p2.sketch"], False, False, False, "C0")
        assert node["id"] == "loft-1"
        assert node["op"] == "loft"
        assert node["profile_sketch_paths"] == ["/p1.sketch", "/p2.sketch"]
        assert node["ruled"] is False
        assert node["closed"] is False
        assert node["symmetric"] is False
        assert node["continuity"] == "C0"

    def test_symmetric_flag_stored(self):
        node = build_loft_node("loft-1", ["/p1.sketch", "/p2.sketch"], False, False, True, "C1")
        assert node["symmetric"] is True
        assert node["continuity"] == "C1"

    def test_name_included_when_provided(self):
        node = build_loft_node("loft-1", ["/p1.sketch", "/p2.sketch"], False, False, False, "C0", name="handle")
        assert node["name"] == "handle"

    def test_name_excluded_when_empty(self):
        node = build_loft_node("loft-1", ["/p1.sketch", "/p2.sketch"], False, False, False, "C0")
        assert "name" not in node

    def test_continuity_uppercased(self):
        node = build_loft_node("loft-1", ["/p1.sketch", "/p2.sketch"], False, False, False, "c2")
        assert node["continuity"] == "C2"

    def test_schema_round_trip(self):
        node = build_loft_node(
            "loft-7", ["/parts/p1.sketch", "/parts/p2.sketch"], True, False, True, "C1"
        )
        serialised = json.dumps(node)
        restored = json.loads(serialised)
        assert restored == node


# ---------------------------------------------------------------------------
# Tool handler (fake DB)
# ---------------------------------------------------------------------------

class TestRunFeatureLoft:
    @pytest.fixture(autouse=True)
    def _skip_if_no_kerf_core(self):
        try:
            from kerf_core.utils.context import ProjectCtx  # noqa: F401
        except ImportError:
            pytest.skip("kerf_core not installed")

    def test_missing_file_id(self):
        ctx, store, fid = make_ctx()
        from kerf_cad_core.feature_loft import run_feature_loft

        raw = asyncio.new_event_loop().run_until_complete(
            run_feature_loft(
                ctx,
                json.dumps({"profile_sketch_paths": ["/p1.sketch", "/p2.sketch"]}).encode(),
            )
        )
        result = json.loads(raw)
        assert "error" in result

    def test_missing_profiles(self):
        ctx, store, fid = make_ctx()
        result = run_tool(ctx, fid)
        assert "error" in result

    def test_too_few_profiles(self):
        ctx, store, fid = make_ctx()
        result = run_tool(ctx, fid, profile_sketch_paths=["/p1.sketch"])
        assert "error" in result
        assert result.get("code") == "BAD_ARGS"

    def test_symmetric_with_three_profiles_rejected(self):
        ctx, store, fid = make_ctx()
        result = run_tool(
            ctx, fid,
            profile_sketch_paths=["/p1.sketch", "/p2.sketch", "/p3.sketch"],
            symmetric=True,
        )
        assert "error" in result
        assert result.get("code") == "BAD_ARGS"

    def test_symmetric_and_closed_rejected(self):
        ctx, store, fid = make_ctx()
        result = run_tool(
            ctx, fid,
            profile_sketch_paths=["/p1.sketch", "/p2.sketch"],
            symmetric=True,
            closed=True,
        )
        assert "error" in result
        assert result.get("code") == "BAD_ARGS"

    def test_closed_with_two_profiles_rejected(self):
        ctx, store, fid = make_ctx()
        result = run_tool(
            ctx, fid,
            profile_sketch_paths=["/p1.sketch", "/p2.sketch"],
            closed=True,
        )
        assert "error" in result
        assert result.get("code") == "BAD_ARGS"

    def test_invalid_uuid(self):
        from kerf_cad_core.feature_loft import run_feature_loft

        ctx, store, fid = make_ctx()
        raw = asyncio.new_event_loop().run_until_complete(
            run_feature_loft(
                ctx,
                json.dumps({
                    "file_id": "not-a-uuid",
                    "profile_sketch_paths": ["/p1.sketch", "/p2.sketch"],
                }).encode(),
            )
        )
        result = json.loads(raw)
        assert "error" in result

    def test_appends_node_default(self):
        ctx, store, fid = make_ctx()
        result = run_tool(ctx, fid, profile_sketch_paths=["/p1.sketch", "/p2.sketch"])
        assert "error" not in result
        assert result["op"] == "loft"
        doc = json.loads(store["content"])
        assert len(doc["features"]) == 1
        node = doc["features"][0]
        assert node["op"] == "loft"
        assert node["symmetric"] is False
        assert node["closed"] is False
        assert node["ruled"] is False
        assert node["continuity"] == "C0"

    def test_appends_symmetric_node(self):
        ctx, store, fid = make_ctx()
        result = run_tool(
            ctx, fid,
            profile_sketch_paths=["/p1.sketch", "/p2.sketch"],
            symmetric=True,
        )
        assert "error" not in result
        assert result.get("symmetric") is True
        doc = json.loads(store["content"])
        node = doc["features"][0]
        assert node["symmetric"] is True
        assert node["op"] == "loft"

    def test_default_symmetric_is_false(self):
        """Omitting symmetric must default to False — preserves existing behaviour."""
        ctx, store, fid = make_ctx()
        result = run_tool(ctx, fid, profile_sketch_paths=["/p1.sketch", "/p2.sketch"])
        assert "error" not in result
        doc = json.loads(store["content"])
        assert doc["features"][0]["symmetric"] is False

    def test_node_id_auto_increments(self):
        ctx, store, fid = make_ctx()
        run_tool(ctx, fid, profile_sketch_paths=["/p1.sketch", "/p2.sketch"])
        run_tool(ctx, fid, profile_sketch_paths=["/p1.sketch", "/p2.sketch"])
        doc = json.loads(store["content"])
        assert doc["features"][0]["id"] == "loft-1"
        assert doc["features"][1]["id"] == "loft-2"

    def test_explicit_node_id(self):
        ctx, store, fid = make_ctx()
        result = run_tool(
            ctx, fid, profile_sketch_paths=["/p1.sketch", "/p2.sketch"], id="sym-loft"
        )
        assert result["id"] == "sym-loft"
        doc = json.loads(store["content"])
        assert doc["features"][0]["id"] == "sym-loft"

    def test_continuity_c1_stored(self):
        ctx, store, fid = make_ctx()
        run_tool(ctx, fid, profile_sketch_paths=["/p1.sketch", "/p2.sketch"], continuity="C1")
        doc = json.loads(store["content"])
        assert doc["features"][0]["continuity"] == "C1"

    def test_invalid_continuity_rejected(self):
        ctx, store, fid = make_ctx()
        result = run_tool(
            ctx, fid,
            profile_sketch_paths=["/p1.sketch", "/p2.sketch"],
            continuity="G1",
        )
        assert "error" in result
        assert result.get("code") == "BAD_ARGS"

    def test_name_stored(self):
        ctx, store, fid = make_ctx()
        run_tool(
            ctx, fid,
            profile_sketch_paths=["/p1.sketch", "/p2.sketch"],
            name="handle_loft",
        )
        doc = json.loads(store["content"])
        assert doc["features"][0]["name"] == "handle_loft"

    def test_op_field_in_payload(self):
        ctx, store, fid = make_ctx()
        result = run_tool(ctx, fid, profile_sketch_paths=["/p1.sketch", "/p2.sketch"])
        assert result.get("op") == "loft"

    def test_file_id_in_payload(self):
        ctx, store, fid = make_ctx()
        result = run_tool(ctx, fid, profile_sketch_paths=["/p1.sketch", "/p2.sketch"])
        assert result.get("file_id") == str(fid)

    def test_profile_paths_stored_as_list(self):
        ctx, store, fid = make_ctx()
        paths = ["/p1.sketch", "/p2.sketch", "/p3.sketch"]
        run_tool(ctx, fid, profile_sketch_paths=paths)
        doc = json.loads(store["content"])
        assert doc["features"][0]["profile_sketch_paths"] == paths

    def test_symmetric_false_preserves_existing_behaviour(self):
        """symmetric=False with 3 profiles must NOT error (original loft behaviour)."""
        ctx, store, fid = make_ctx()
        result = run_tool(
            ctx, fid,
            profile_sketch_paths=["/p1.sketch", "/p2.sketch", "/p3.sketch"],
            symmetric=False,
        )
        assert "error" not in result


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
