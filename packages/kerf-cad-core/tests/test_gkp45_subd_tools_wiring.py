"""GK-P45 wiring test: ToolSpec dispatch + FeatureView entry check.

Verifies that subd_tools.py registers its ToolSpecs correctly and that
the expected ops appear in the FeatureView.jsx FEATURE_KINDS list.
"""
from __future__ import annotations

import importlib
import json
import pathlib
import re
import uuid

import pytest


# ---------------------------------------------------------------------------
# Import guard: if kerf_chat is not installed, skip gracefully.
# ---------------------------------------------------------------------------

try:
    from kerf_chat.tools.registry import Registry  # type: ignore
    _HAS_REGISTRY = True
except ImportError:
    _HAS_REGISTRY = False

try:
    import kerf_cad_core.subd_tools  # noqa: F401 — side-effect import to register
    _HAS_SUBD_TOOLS = True
except ImportError:
    _HAS_SUBD_TOOLS = False


def _registered(name: str) -> bool:
    from kerf_chat.tools.registry import Registry  # type: ignore
    return any(t.spec.name == name for t in Registry)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_WORKTREE = pathlib.Path(__file__).parents[3]
_FEATURE_VIEW = _WORKTREE / "src" / "components" / "FeatureView.jsx"


def _feature_view_text() -> str:
    return _FEATURE_VIEW.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# ToolSpec registration
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not _HAS_SUBD_TOOLS, reason="kerf_chat/subd_tools not importable")
def test_subd_poke_toolspec_registered():
    """feature_subd_poke ToolSpec must be registered in the global registry."""
    import kerf_cad_core.subd_tools  # ensure registered
    assert _registered("feature_subd_poke"), "feature_subd_poke not in tool registry"


@pytest.mark.skipif(not _HAS_SUBD_TOOLS, reason="kerf_chat/subd_tools not importable")
def test_subd_extrude_along_toolspec_registered():
    import kerf_cad_core.subd_tools
    assert _registered("feature_subd_extrude_along")


@pytest.mark.skipif(not _HAS_SUBD_TOOLS, reason="kerf_chat/subd_tools not importable")
def test_sculpt_brush_toolspec_registered():
    import kerf_cad_core.subd_tools
    assert _registered("feature_sculpt_brush")


@pytest.mark.skipif(not _HAS_SUBD_TOOLS, reason="kerf_chat/subd_tools not importable")
def test_multires_evaluate_toolspec_registered():
    import kerf_cad_core.subd_tools
    assert _registered("feature_multires_evaluate")


# ---------------------------------------------------------------------------
# FeatureView.jsx FEATURE_KINDS entries
# ---------------------------------------------------------------------------

def test_subd_poke_in_feature_view():
    text = _feature_view_text()
    assert "subd_poke" in text, "subd_poke missing from FeatureView.jsx FEATURE_KINDS"


def test_subd_extrude_along_in_feature_view():
    text = _feature_view_text()
    assert "subd_extrude_along" in text


def test_sculpt_brush_in_feature_view():
    text = _feature_view_text()
    assert "sculpt_brush" in text


def test_multires_evaluate_in_feature_view():
    text = _feature_view_text()
    assert "multires_evaluate" in text


# ---------------------------------------------------------------------------
# ToolSpec schema sanity
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not _HAS_SUBD_TOOLS, reason="kerf_chat/subd_tools not importable")
def test_subd_poke_schema_has_required_fields():
    import kerf_cad_core.subd_tools as m
    schema = m.feature_subd_poke_spec.input_schema
    required = schema.get("required", [])
    assert "file_id" in required
    assert "target_id" in required
    assert "face_id" in required


@pytest.mark.skipif(not _HAS_SUBD_TOOLS, reason="kerf_chat/subd_tools not importable")
def test_sculpt_brush_schema_mode_enum():
    import kerf_cad_core.subd_tools as m
    schema = m.feature_sculpt_brush_spec.input_schema
    mode_enum = schema["properties"]["mode"]["enum"]
    assert set(mode_enum) == {"grab", "smooth", "inflate"}


@pytest.mark.skipif(not _HAS_SUBD_TOOLS, reason="kerf_chat/subd_tools not importable")
def test_dispatch_rejects_missing_file_id():
    """run_feature_subd_poke must return BAD_ARGS when file_id is missing."""
    import asyncio
    import kerf_cad_core.subd_tools as m

    class _FakePool:
        def fetchone(self, *a, **kw):
            return None

    class _FakeCtx:
        pool = _FakePool()
        project_id = uuid.uuid4()

    result = asyncio.get_event_loop().run_until_complete(
        m.run_feature_subd_poke(
            _FakeCtx(),
            json.dumps({"target_id": "cage-1", "face_id": 0}).encode(),
        )
    )
    payload = json.loads(result)
    assert payload.get("code") == "BAD_ARGS"


@pytest.mark.skipif(not _HAS_SUBD_TOOLS, reason="kerf_chat/subd_tools not importable")
def test_dispatch_rejects_invalid_uuid():
    import asyncio
    import kerf_cad_core.subd_tools as m

    class _FakePool:
        def fetchone(self, *a, **kw):
            return None

    class _FakeCtx:
        pool = _FakePool()
        project_id = uuid.uuid4()

    result = asyncio.get_event_loop().run_until_complete(
        m.run_feature_subd_poke(
            _FakeCtx(),
            json.dumps({"file_id": "not-a-uuid", "target_id": "x", "face_id": 0}).encode(),
        )
    )
    payload = json.loads(result)
    assert payload.get("code") == "BAD_ARGS"
