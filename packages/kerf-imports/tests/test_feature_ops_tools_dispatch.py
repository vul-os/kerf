"""
test_feature_ops_tools_dispatch.py — dispatch tests for the feature_draft and
feature_mirror LLM tools.

Verifies that both tools expose a TOOLS list (name, spec, handler) and that the
async handlers return structured error payloads on invalid args rather than
raising exceptions.

No DB / real file I/O — ctx is a minimal stub.
"""
from __future__ import annotations

import asyncio
import json
import types
import uuid

import pytest


def run(coro):
    return asyncio.run(coro)


def _make_ctx():
    ctx = types.SimpleNamespace()
    ctx.project_id = uuid.uuid4()
    ctx.pool = None
    ctx.storage = None
    return ctx


# ---------------------------------------------------------------------------
# feature_draft tool
# ---------------------------------------------------------------------------

class TestFeatureDraftToolDispatch:
    def _get(self):
        try:
            from kerf_imports.tools.feature_draft import feature_draft_spec, run_feature_draft
            return feature_draft_spec, run_feature_draft
        except ImportError:
            pytest.skip("kerf_chat unavailable")

    def test_tools_list_present(self):
        try:
            from kerf_imports.tools.feature_draft import TOOLS
        except ImportError:
            pytest.skip("kerf_chat unavailable")
        assert isinstance(TOOLS, list) and len(TOOLS) >= 1

    def test_tools_list_entry_shape(self):
        try:
            from kerf_imports.tools.feature_draft import TOOLS
        except ImportError:
            pytest.skip("kerf_chat unavailable")
        for name, spec, handler in TOOLS:
            assert isinstance(name, str) and name
            assert hasattr(spec, "name") and spec.name == name
            assert callable(handler)

    def test_spec_name(self):
        spec, _ = self._get()
        assert spec.name == "feature_draft"

    def test_missing_file_id_returns_error(self):
        spec, handler = self._get()
        ctx = _make_ctx()
        result = run(handler(ctx, b"{}"))
        data = json.loads(result)
        assert data.get("ok") is not True

    def test_missing_face_ids_returns_error(self):
        spec, handler = self._get()
        ctx = _make_ctx()
        payload = json.dumps({
            "file_id": str(uuid.uuid4()),
            "neutral_plane_face_id": 0,
            "angle_deg": 5.0,
        }).encode()
        result = run(handler(ctx, payload))
        data = json.loads(result)
        assert data.get("ok") is not True
        assert data.get("code") == "BAD_ARGS"

    def test_angle_out_of_range_returns_error(self):
        spec, handler = self._get()
        ctx = _make_ctx()
        payload = json.dumps({
            "file_id": str(uuid.uuid4()),
            "face_ids": [1, 2],
            "neutral_plane_face_id": 0,
            "angle_deg": 90.0,  # outside [-30, 30]
        }).encode()
        result = run(handler(ctx, payload))
        data = json.loads(result)
        assert data.get("ok") is not True
        assert data.get("code") == "BAD_ARGS"


# ---------------------------------------------------------------------------
# feature_mirror tool
# ---------------------------------------------------------------------------

class TestFeatureMirrorToolDispatch:
    def _get(self):
        try:
            from kerf_imports.tools.feature_mirror import feature_mirror_spec, run_feature_mirror
            return feature_mirror_spec, run_feature_mirror
        except ImportError:
            pytest.skip("kerf_chat unavailable")

    def test_tools_list_present(self):
        try:
            from kerf_imports.tools.feature_mirror import TOOLS
        except ImportError:
            pytest.skip("kerf_chat unavailable")
        assert isinstance(TOOLS, list) and len(TOOLS) >= 1

    def test_tools_list_entry_shape(self):
        try:
            from kerf_imports.tools.feature_mirror import TOOLS
        except ImportError:
            pytest.skip("kerf_chat unavailable")
        for name, spec, handler in TOOLS:
            assert isinstance(name, str) and name
            assert hasattr(spec, "name") and spec.name == name
            assert callable(handler)

    def test_spec_name(self):
        spec, _ = self._get()
        assert spec.name == "feature_mirror"

    def test_missing_file_id_returns_error(self):
        spec, handler = self._get()
        ctx = _make_ctx()
        result = run(handler(ctx, b"{}"))
        data = json.loads(result)
        assert data.get("ok") is not True
        assert data.get("code") == "BAD_ARGS"

    def test_no_source_returns_error(self):
        """Neither source_feature_id nor source_body_id → BAD_ARGS."""
        spec, handler = self._get()
        ctx = _make_ctx()
        payload = json.dumps({
            "file_id": str(uuid.uuid4()),
            "mirror_plane": "XZ",
        }).encode()
        result = run(handler(ctx, payload))
        data = json.loads(result)
        assert data.get("ok") is not True
        assert data.get("code") == "BAD_ARGS"

    def test_both_sources_returns_error(self):
        """Providing both source_feature_id and source_body_id → BAD_ARGS."""
        spec, handler = self._get()
        ctx = _make_ctx()
        payload = json.dumps({
            "file_id": str(uuid.uuid4()),
            "source_feature_id": "pad-1",
            "source_body_id": "body-1",
            "mirror_plane": "XY",
        }).encode()
        result = run(handler(ctx, payload))
        data = json.loads(result)
        assert data.get("ok") is not True
        assert data.get("code") == "BAD_ARGS"
