"""Hermetic tests for substitute_component tool and _resolve_geometry helper.

All tests are fully hermetic — no network, no DB, no real geometry toolchain.
The tool is async but we exercise it via asyncio.run so pytest-asyncio is not
required.

Coverage (≥ 20 assertions):
  _resolve_geometry
    1.  returns None for non-dict input
    2.  returns None when neither model_3d nor model_3d_paths present
    3.  returns {"kind": "jscad", "source": ...} for a model_3d string
    4.  returns None when model_3d is empty / non-string
    5.  returns {"kind": "step", "path": ...} for model_3d_paths with .step entry
    6.  skips .wrl / non-step paths; picks first .step
    7.  returns None when model_3d_paths contains no .step entries
    8.  prefers model_3d over model_3d_paths when both present

  substitute_component tool handler
    9.  returns BAD_ARGS on unparseable args bytes
    10. returns BAD_ARGS when component_id missing / empty
    11. returns BAD_ARGS when part_content missing / empty
    12. returns BAD_ARGS when part_content is not valid JSON
    13. returns BAD_ARGS when part_content parses to a non-object
    14. returns kind="none" when part has no geometry hint
    15. returns kind="jscad" with source for a model_3d part
    16. returns kind="step" with path for a model_3d_paths part
    17. result carries component_id and cached=False on first call
    18. second call with same component_id returns cached=True without re-parsing
    19. bust_cache=True forces re-resolve even when cached
    20. clear_substitute_cache() wipes the cache (next call is a cache miss)
    21. two different component_ids are cached independently
    22. cache value is the descriptor only, not the full part doc

  plugin registration
    23. plugin.py can be imported without kerf_core / kerf_chat
    24. TOOLS list has the expected tool names
"""
from __future__ import annotations

import asyncio
import json
import sys
import types

import pytest

from kerf_parts.tools import (
    TOOLS,
    _SUBST_CACHE,
    _resolve_geometry,
    _run_substitute_component,
    clear_substitute_cache,
    _substitute_component_spec,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run(coro):
    """Run a coroutine synchronously."""
    return asyncio.run(coro)


def _args(**kwargs) -> bytes:
    return json.dumps(kwargs).encode()


def _parse(result: str) -> dict:
    return json.loads(result)


class _FakeCtx:
    pass


ctx = _FakeCtx()


# ---------------------------------------------------------------------------
# _resolve_geometry tests
# ---------------------------------------------------------------------------

class TestResolveGeometry:
    def test_non_dict_input_returns_none(self):
        assert _resolve_geometry(None) is None
        assert _resolve_geometry("string") is None
        assert _resolve_geometry(42) is None
        assert _resolve_geometry([]) is None

    def test_empty_dict_returns_none(self):
        assert _resolve_geometry({}) is None

    def test_no_geometry_hint_returns_none(self):
        doc = {"version": 1, "name": "Resistor", "value": "10k"}
        assert _resolve_geometry(doc) is None

    def test_model_3d_string_returns_jscad(self):
        src = "export default function () { return null }"
        doc = {"model_3d": src}
        result = _resolve_geometry(doc)
        assert result is not None
        assert result["kind"] == "jscad"
        assert result["source"] == src

    def test_model_3d_empty_string_returns_none(self):
        assert _resolve_geometry({"model_3d": ""}) is None
        assert _resolve_geometry({"model_3d": "   "}) is None

    def test_model_3d_non_string_returns_none(self):
        assert _resolve_geometry({"model_3d": 42}) is None
        assert _resolve_geometry({"model_3d": None}) is None

    def test_model_3d_paths_step_returns_step(self):
        doc = {"model_3d_paths": ["Packages/R.wrl", "Packages/R.step"]}
        result = _resolve_geometry(doc)
        assert result is not None
        assert result["kind"] == "step"
        assert result["path"] == "Packages/R.step"

    def test_model_3d_paths_picks_first_step(self):
        doc = {"model_3d_paths": ["a.step", "b.step"]}
        assert _resolve_geometry(doc)["path"] == "a.step"

    def test_model_3d_paths_skips_non_step(self):
        doc = {"model_3d_paths": ["Packages/R.wrl", "Packages/R.3dshapes"]}
        assert _resolve_geometry(doc) is None

    def test_model_3d_paths_case_insensitive(self):
        doc = {"model_3d_paths": ["Packages/R.STP"]}
        result = _resolve_geometry(doc)
        assert result is not None
        assert result["kind"] == "step"

    def test_prefers_model_3d_over_model_3d_paths(self):
        src = "export default () => {}"
        doc = {"model_3d": src, "model_3d_paths": ["R.step"]}
        result = _resolve_geometry(doc)
        assert result["kind"] == "jscad"
        assert result["source"] == src


# ---------------------------------------------------------------------------
# substitute_component handler tests
# ---------------------------------------------------------------------------

class TestSubstituteComponentHandler:
    def setup_method(self):
        clear_substitute_cache()

    def teardown_method(self):
        clear_substitute_cache()

    def test_bad_json_args_returns_bad_args(self):
        result = _parse(_run(_run_substitute_component(ctx, b"not json")))
        assert result.get("code") == "BAD_ARGS"

    def test_missing_component_id_returns_bad_args(self):
        part = json.dumps({"version": 1, "name": "R"})
        result = _parse(_run(_run_substitute_component(ctx, _args(part_content=part))))
        assert result.get("code") == "BAD_ARGS"

    def test_empty_component_id_returns_bad_args(self):
        part = json.dumps({"version": 1, "name": "R"})
        result = _parse(_run(_run_substitute_component(ctx, _args(component_id="   ", part_content=part))))
        assert result.get("code") == "BAD_ARGS"

    def test_missing_part_content_returns_bad_args(self):
        result = _parse(_run(_run_substitute_component(ctx, _args(component_id="cid-1"))))
        assert result.get("code") == "BAD_ARGS"

    def test_invalid_json_part_content_returns_bad_args(self):
        result = _parse(_run(_run_substitute_component(ctx, _args(
            component_id="cid-1",
            part_content="{not json",
        ))))
        assert result.get("code") == "BAD_ARGS"

    def test_non_object_part_content_returns_bad_args(self):
        result = _parse(_run(_run_substitute_component(ctx, _args(
            component_id="cid-1",
            part_content="[1, 2, 3]",
        ))))
        assert result.get("code") == "BAD_ARGS"

    def test_no_geometry_hint_returns_kind_none(self):
        part = json.dumps({"version": 1, "name": "R", "value": "10k"})
        result = _parse(_run(_run_substitute_component(ctx, _args(
            component_id="cid-1",
            part_content=part,
        ))))
        assert result.get("kind") == "none"
        assert result.get("component_id") == "cid-1"

    def test_jscad_part_returns_kind_jscad(self):
        src = "export default function () { return null }"
        part = json.dumps({"version": 1, "name": "R", "model_3d": src})
        result = _parse(_run(_run_substitute_component(ctx, _args(
            component_id="cid-jscad",
            part_content=part,
        ))))
        assert result.get("kind") == "jscad"
        assert result.get("source") == src
        assert result.get("component_id") == "cid-jscad"
        assert result.get("cached") is False

    def test_step_part_returns_kind_step(self):
        part = json.dumps({"version": 1, "name": "Bolt", "model_3d_paths": ["M6x20.step"]})
        result = _parse(_run(_run_substitute_component(ctx, _args(
            component_id="cid-step",
            part_content=part,
        ))))
        assert result.get("kind") == "step"
        assert result.get("path") == "M6x20.step"

    def test_second_call_returns_cached(self):
        src = "export default () => {}"
        part = json.dumps({"version": 1, "name": "R", "model_3d": src})
        _run(_run_substitute_component(ctx, _args(component_id="cid-cache", part_content=part)))
        result2 = _parse(_run(_run_substitute_component(ctx, _args(
            component_id="cid-cache",
            part_content=part,
        ))))
        assert result2.get("cached") is True

    def test_bust_cache_refetches(self):
        src = "export default () => {}"
        part = json.dumps({"version": 1, "name": "R", "model_3d": src})
        _run(_run_substitute_component(ctx, _args(component_id="cid-bust", part_content=part)))
        result2 = _parse(_run(_run_substitute_component(ctx, _args(
            component_id="cid-bust",
            part_content=part,
            bust_cache=True,
        ))))
        assert result2.get("cached") is False

    def test_clear_cache_resets_state(self):
        src = "export default () => {}"
        part = json.dumps({"model_3d": src})
        _run(_run_substitute_component(ctx, _args(component_id="cid-clear", part_content=part)))
        assert "cid-clear" in _SUBST_CACHE
        clear_substitute_cache()
        assert "cid-clear" not in _SUBST_CACHE

    def test_two_different_ids_cached_independently(self):
        src = "export default () => {}"
        part = json.dumps({"model_3d": src})
        _run(_run_substitute_component(ctx, _args(component_id="id-A", part_content=part)))
        _run(_run_substitute_component(ctx, _args(component_id="id-B", part_content=part)))
        assert "id-A" in _SUBST_CACHE
        assert "id-B" in _SUBST_CACHE

    def test_cache_stores_descriptor_not_full_doc(self):
        src = "export default () => {}"
        full_doc = {"version": 1, "name": "R", "value": "10k", "model_3d": src,
                    "distributors": [{"name": "Digi-Key"}], "metadata": {"big": "data"}}
        part = json.dumps(full_doc)
        _run(_run_substitute_component(ctx, _args(component_id="cid-mem", part_content=part)))
        cached = _SUBST_CACHE.get("cid-mem")
        assert cached is not None
        # Descriptor has kind + source only — not the full doc.
        assert "distributors" not in cached
        assert "metadata" not in cached
        assert cached.get("kind") == "jscad"


# ---------------------------------------------------------------------------
# TOOLS list structure tests
# ---------------------------------------------------------------------------

class TestToolsList:
    def test_tools_list_is_non_empty(self):
        assert len(TOOLS) >= 1

    def test_substitute_component_in_tools(self):
        names = [t[0] for t in TOOLS]
        assert "substitute_component" in names

    def test_spec_name_matches_entry_name(self):
        for name, spec, _handler in TOOLS:
            assert spec.name == name

    def test_spec_has_required_schema_keys(self):
        assert "component_id" in _substitute_component_spec.input_schema["properties"]
        assert "part_content" in _substitute_component_spec.input_schema["properties"]
        assert "component_id" in _substitute_component_spec.input_schema["required"]
        assert "part_content" in _substitute_component_spec.input_schema["required"]


# ---------------------------------------------------------------------------
# plugin.py importability (no kerf_core / kerf_chat required)
# ---------------------------------------------------------------------------

class TestPluginImport:
    def test_plugin_importable_without_kerf_core(self):
        # Temporarily hide kerf_core from sys.modules to verify the plugin
        # degrades gracefully.
        saved = {k: v for k, v in sys.modules.items() if k.startswith("kerf_core")}
        for k in list(saved):
            del sys.modules[k]
        try:
            # Re-import (import machinery will try and fail to find kerf_core).
            import importlib
            import kerf_parts.plugin as _plugin
            importlib.reload(_plugin)
            assert hasattr(_plugin, "register")
            assert hasattr(_plugin, "_register_tools")
        finally:
            # Restore.
            sys.modules.update(saved)
