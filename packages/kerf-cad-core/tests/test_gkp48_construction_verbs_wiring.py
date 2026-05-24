"""GK-P48 wiring test: construction verbs ToolSpec dispatch + FeatureView entries."""
from __future__ import annotations

import json
import pathlib
import uuid

import pytest

try:
    import kerf_cad_core.construction_verbs_tools  # noqa: F401
    _HAS_TOOLS = True
except ImportError:
    _HAS_TOOLS = False

_WORKTREE = pathlib.Path(__file__).parents[3]
_FEATURE_VIEW = _WORKTREE / "src" / "components" / "FeatureView.jsx"


def _fv() -> str:
    return _FEATURE_VIEW.read_text(encoding="utf-8")


def _registered(name: str) -> bool:
    from kerf_chat.tools.registry import Registry  # type: ignore
    return any(t.spec.name == name for t in Registry)


# FeatureView presence
def test_hem_sheet_in_feature_view():
    assert "hem_sheet" in _fv()

def test_jog_sheet_in_feature_view():
    assert "jog_sheet" in _fv()

def test_multi_flange_in_feature_view():
    assert "multi_flange" in _fv()

def test_delete_face_in_feature_view():
    assert "delete_face" in _fv()

def test_push_pull_in_feature_view():
    # push_pull was already in modify category; we added it as a first-class node too
    assert "push_pull" in _fv()

def test_gusset_plate_in_feature_view():
    assert "gusset_plate" in _fv()

def test_cope_notch_in_feature_view():
    assert "cope_notch" in _fv()


# ToolSpec registration
@pytest.mark.skipif(not _HAS_TOOLS, reason="construction_verbs_tools not importable")
def test_hem_sheet_registered():
    import kerf_cad_core.construction_verbs_tools
    assert _registered("feature_hem_sheet")

@pytest.mark.skipif(not _HAS_TOOLS, reason="construction_verbs_tools not importable")
def test_jog_sheet_registered():
    import kerf_cad_core.construction_verbs_tools
    assert _registered("feature_jog_sheet")

@pytest.mark.skipif(not _HAS_TOOLS, reason="construction_verbs_tools not importable")
def test_multi_flange_registered():
    import kerf_cad_core.construction_verbs_tools
    assert _registered("feature_multi_flange")

@pytest.mark.skipif(not _HAS_TOOLS, reason="construction_verbs_tools not importable")
def test_delete_face_registered():
    import kerf_cad_core.construction_verbs_tools
    assert _registered("feature_delete_face")

@pytest.mark.skipif(not _HAS_TOOLS, reason="construction_verbs_tools not importable")
def test_push_pull_registered():
    import kerf_cad_core.construction_verbs_tools
    assert _registered("feature_push_pull")

@pytest.mark.skipif(not _HAS_TOOLS, reason="construction_verbs_tools not importable")
def test_gusset_plate_registered():
    import kerf_cad_core.construction_verbs_tools
    assert _registered("feature_gusset_plate")

@pytest.mark.skipif(not _HAS_TOOLS, reason="construction_verbs_tools not importable")
def test_cope_notch_registered():
    import kerf_cad_core.construction_verbs_tools
    assert _registered("feature_cope_notch")


# Dispatch error cases
@pytest.mark.skipif(not _HAS_TOOLS, reason="construction_verbs_tools not importable")
def test_hem_sheet_bad_style():
    import asyncio
    import kerf_cad_core.construction_verbs_tools as m

    class _FakeCtx:
        class pool:
            @staticmethod
            def fetchone(*a, **kw): return None
        project_id = uuid.uuid4()

    result = asyncio.get_event_loop().run_until_complete(
        m.run_feature_hem_sheet(
            _FakeCtx(),
            json.dumps({
                "file_id": str(uuid.uuid4()),
                "target_id": "bend-1",
                "style": "invalid_style",
            }).encode(),
        )
    )
    assert json.loads(result)["code"] == "BAD_ARGS"


@pytest.mark.skipif(not _HAS_TOOLS, reason="construction_verbs_tools not importable")
def test_jog_sheet_zero_offset():
    import asyncio
    import kerf_cad_core.construction_verbs_tools as m

    class _FakeCtx:
        class pool:
            @staticmethod
            def fetchone(*a, **kw): return None
        project_id = uuid.uuid4()

    result = asyncio.get_event_loop().run_until_complete(
        m.run_feature_jog_sheet(
            _FakeCtx(),
            json.dumps({
                "file_id": str(uuid.uuid4()),
                "target_id": "sheet-1",
                "offset": 0.0,  # invalid: must be non-zero
            }).encode(),
        )
    )
    assert json.loads(result)["code"] == "BAD_ARGS"


@pytest.mark.skipif(not _HAS_TOOLS, reason="construction_verbs_tools not importable")
def test_delete_face_negative_face_id():
    import asyncio
    import kerf_cad_core.construction_verbs_tools as m

    class _FakeCtx:
        class pool:
            @staticmethod
            def fetchone(*a, **kw): return None
        project_id = uuid.uuid4()

    result = asyncio.get_event_loop().run_until_complete(
        m.run_feature_delete_face(
            _FakeCtx(),
            json.dumps({
                "file_id": str(uuid.uuid4()),
                "target_id": "body-1",
                "face_id": -1,  # invalid
            }).encode(),
        )
    )
    assert json.loads(result)["code"] == "BAD_ARGS"


@pytest.mark.skipif(not _HAS_TOOLS, reason="construction_verbs_tools not importable")
def test_gusset_plate_zero_thickness():
    import asyncio
    import kerf_cad_core.construction_verbs_tools as m

    class _FakeCtx:
        class pool:
            @staticmethod
            def fetchone(*a, **kw): return None
        project_id = uuid.uuid4()

    result = asyncio.get_event_loop().run_until_complete(
        m.run_feature_gusset_plate(
            _FakeCtx(),
            json.dumps({
                "file_id": str(uuid.uuid4()),
                "target_id": "frame-1",
                "vertex_pos": [0, 0, 0],
                "thickness_mm": 0,  # invalid: must be > 0
            }).encode(),
        )
    )
    assert json.loads(result)["code"] == "BAD_ARGS"


@pytest.mark.skipif(not _HAS_TOOLS, reason="construction_verbs_tools not importable")
def test_cope_notch_bad_end():
    import asyncio
    import kerf_cad_core.construction_verbs_tools as m

    class _FakeCtx:
        class pool:
            @staticmethod
            def fetchone(*a, **kw): return None
        project_id = uuid.uuid4()

    result = asyncio.get_event_loop().run_until_complete(
        m.run_feature_cope_notch(
            _FakeCtx(),
            json.dumps({
                "file_id": str(uuid.uuid4()),
                "target_id": "frame-1",
                "member_index": 0,
                "end": "middle",  # invalid: must be 'start' or 'end'
            }).encode(),
        )
    )
    assert json.loads(result)["code"] == "BAD_ARGS"
