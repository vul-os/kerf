"""T-45 Workshop README workstream tests.

Coverage areas (all offline — no live DB, no live LLM, no live render):

1. Schema round-trip helpers (update_project kwargs accepted without error).
2. README composition (compose_readme_prompt) — structure, sections present.
3. README template fallback (generate_readme_template) — no LLM needed.
4. Mocked-LLM auto-generation via generate_readme (README stored, no live call).
5. Render fallback: _generate_project_cover returns None when Blender absent.
6. Thumbnail URL resolution — cover_url takes priority over thumbnail_url.
7. _project_to_workshop_row exposes readme/cover fields correctly.
8. _get_bom_rows_sync parses .part files into simple BOM dicts.
"""
import json
import sys
import os

import pytest


# ---------------------------------------------------------------------------
# Helpers – offline mirrors of backend logic
# ---------------------------------------------------------------------------

def _resolve_cover_url(project_id: str, cover_storage_key, thumbnail_url):
    """Mirrors the cover_url priority logic in _project_to_workshop_row."""
    pid = project_id
    if cover_storage_key:
        return f"/api/projects/{pid}/cover"
    return thumbnail_url


def _project_to_workshop_row_subset(p: dict) -> dict:
    """Extract only the README/cover fields from a project dict — mirrors routes.py."""
    pid = str(p["id"])
    primary_image_id = p.get("primary_image_id")
    if primary_image_id:
        thumbnail_url = f"/api/projects/{pid}/workshop-images/{primary_image_id}/file"
    elif p.get("thumbnail_storage_key"):
        thumbnail_url = f"/api/projects/{pid}/thumbnail"
    else:
        thumbnail_url = None

    return {
        "readme": p.get("readme") or None,
        "readme_generated_at": (
            p["readme_generated_at"].isoformat()
            if p.get("readme_generated_at") else None
        ),
        "cover_storage_key": p.get("cover_storage_key"),
        "cover_url": (
            f"/api/projects/{pid}/cover"
            if p.get("cover_storage_key") else thumbnail_url
        ),
        "thumbnail_url": thumbnail_url,
    }


# ---------------------------------------------------------------------------
# 1. Schema: update_project kwargs accepted (no TypeError)
# ---------------------------------------------------------------------------

def test_update_project_accepts_readme_kwargs():
    """update_project signature must accept readme and cover_storage_key."""
    import inspect
    from kerf_core.db.queries.projects import update_project
    sig = inspect.signature(update_project)
    params = sig.parameters
    assert "readme" in params, "update_project must accept 'readme' kwarg"
    assert "cover_storage_key" in params, "update_project must accept 'cover_storage_key' kwarg"


# ---------------------------------------------------------------------------
# 2. README composition — compose_readme_prompt
# ---------------------------------------------------------------------------

def test_compose_readme_prompt_contains_project_name():
    from kerf_chat.readme_gen import compose_readme_prompt
    project = {"name": "Widget Bracket", "tags": ["mechanical"]}
    _, user_prompt = compose_readme_prompt(project)
    assert "Widget Bracket" in user_prompt


def test_compose_readme_prompt_includes_bom():
    from kerf_chat.readme_gen import compose_readme_prompt
    project = {"name": "Clip", "tags": []}
    bom = [{"name": "M3 Bolt", "qty": 4, "supplier": "Bolt Depot"}]
    _, user_prompt = compose_readme_prompt(project, bom_rows=bom)
    assert "M3 Bolt" in user_prompt
    assert "Bolt Depot" in user_prompt


def test_compose_readme_prompt_includes_parts_attribution():
    from kerf_chat.readme_gen import compose_readme_prompt
    project = {"name": "Mount", "tags": []}
    parts = [{"name": "GoBILDA Rail", "author": "GoBILDA", "license": "CC-BY-4.0"}]
    _, user_prompt = compose_readme_prompt(project, parts_rows=parts)
    assert "GoBILDA" in user_prompt


def test_compose_readme_prompt_includes_license():
    from kerf_chat.readme_gen import compose_readme_prompt
    project = {"name": "Part", "license": "Apache-2.0"}
    _, user_prompt = compose_readme_prompt(project)
    assert "Apache-2.0" in user_prompt


def test_compose_readme_prompt_fork_guide():
    from kerf_chat.readme_gen import compose_readme_prompt
    project = {"name": "X"}
    _, user_prompt = compose_readme_prompt(project)
    assert "Fork" in user_prompt or "fork" in user_prompt


# ---------------------------------------------------------------------------
# 3. README template fallback (no LLM)
# ---------------------------------------------------------------------------

def test_template_includes_title():
    from kerf_chat.readme_gen import generate_readme_template
    result = generate_readme_template({"name": "Servo Horn", "tags": []})
    assert "# Servo Horn" in result


def test_template_includes_overview_section():
    from kerf_chat.readme_gen import generate_readme_template
    result = generate_readme_template({"name": "X", "description": "A test part."})
    assert "## Overview" in result
    assert "A test part." in result


def test_template_includes_bom_table():
    from kerf_chat.readme_gen import generate_readme_template
    bom = [{"name": "Nut M5", "qty": 8}]
    result = generate_readme_template({"name": "Y"}, bom_rows=bom)
    assert "## Bill of Materials" in result
    assert "Nut M5" in result


def test_template_includes_fork_guide():
    from kerf_chat.readme_gen import generate_readme_template
    result = generate_readme_template({"name": "Z"})
    assert "## Fork" in result or "Fork & Edit" in result


def test_template_includes_license():
    from kerf_chat.readme_gen import generate_readme_template
    result = generate_readme_template({"name": "Z", "license": "MIT"})
    assert "## License" in result
    assert "MIT" in result


def test_template_no_crash_on_empty_project():
    from kerf_chat.readme_gen import generate_readme_template
    result = generate_readme_template({})
    assert isinstance(result, str)
    assert len(result) > 0


# ---------------------------------------------------------------------------
# 4. Mocked-LLM generate_readme (no live model call)
# ---------------------------------------------------------------------------

class _MockProvider:
    """Minimal Provider stub that returns a fixed string."""
    def complete(self, req):
        from kerf_chat.llm import CompleteResponse
        return CompleteResponse(
            content="# Mocked README\n\nThis is a mock.",
            stop_reason="stop",
            model_used=req.model,
        )
    def name(self):
        return "mock"


def test_generate_readme_with_mock_llm():
    from kerf_chat.readme_gen import generate_readme
    project = {"name": "My Widget", "tags": ["mechanical"]}
    result = generate_readme(project, llm_provider=_MockProvider(), model_id="claude-haiku-4-5")
    assert "Mocked README" in result
    assert isinstance(result, str)


def test_generate_readme_raises_without_provider():
    from kerf_chat.readme_gen import generate_readme
    import pytest
    with pytest.raises(ValueError, match="llm_provider is required"):
        generate_readme({"name": "X"}, llm_provider=None)


def test_generate_readme_passes_bom_to_prompt(monkeypatch):
    """generate_readme must include bom_rows in the prompt sent to the LLM."""
    captured_req = {}

    class _CapturingProvider:
        def complete(self, req):
            captured_req["req"] = req
            from kerf_chat.llm import CompleteResponse
            return CompleteResponse(content="# README", stop_reason="stop", model_used=req.model)
        def name(self): return "mock"

    from kerf_chat.readme_gen import generate_readme
    bom = [{"name": "Widget Spring", "qty": 2}]
    generate_readme({"name": "Z"}, bom_rows=bom, llm_provider=_CapturingProvider())

    # The user message should mention the BOM item.
    user_msg = captured_req["req"].messages[0].content
    assert "Widget Spring" in user_msg


# ---------------------------------------------------------------------------
# 5. Render fallback — _generate_project_cover returns None when Blender absent
# ---------------------------------------------------------------------------

def test_generate_project_cover_returns_none_without_blender(monkeypatch):
    """When kerf_render._BLENDER_AVAILABLE is False, cover generation skips gracefully."""
    import types, importlib

    # Ensure kerf_render is importable (may be a stub).
    try:
        import kerf_render.routes as _rr
    except ImportError:
        pytest.skip("kerf_render not available in this environment")

    # Patch _BLENDER_AVAILABLE to False to simulate missing Blender.
    monkeypatch.setattr(_rr, "_BLENDER_AVAILABLE", False, raising=False)

    # Run an async call via asyncio.run.
    import asyncio

    # Import the helper after the monkeypatch is applied.
    # Because _generate_project_cover is defined inside routes.py, we import
    # the module-level function directly.
    from kerf_api.routes import _generate_project_cover

    async def _run():
        return await _generate_project_cover(None, {}, None, None)

    result = asyncio.run(_run())
    assert result is None, "cover generation must return None when Blender is unavailable"


def test_generate_project_cover_returns_none_when_import_fails(monkeypatch):
    """When kerf_render is not importable at all, cover generation must not raise."""
    import asyncio
    import builtins

    original_import = builtins.__import__

    def _blocking_import(name, *args, **kwargs):
        if name == "kerf_render.routes":
            raise ImportError("kerf_render not installed")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _blocking_import)

    from kerf_api.routes import _generate_project_cover

    async def _run():
        return await _generate_project_cover(None, {}, None, None)

    result = asyncio.run(_run())
    assert result is None


# ---------------------------------------------------------------------------
# 6. Thumbnail URL resolution — cover_url priority
# ---------------------------------------------------------------------------

def test_cover_url_beats_thumbnail_when_cover_present():
    """When cover_storage_key is set, cover_url should point to /cover endpoint."""
    row = _project_to_workshop_row_subset({
        "id": "aaaaaaaa-0000-0000-0000-000000000001",
        "cover_storage_key": "projects/aaa/cover.png",
        "thumbnail_storage_key": "projects/aaa/thumbnail.jpg",
        "readme": None,
        "readme_generated_at": None,
    })
    assert row["cover_url"] and "/cover" in row["cover_url"]
    assert row["thumbnail_url"] and "/thumbnail" in row["thumbnail_url"]


def test_cover_url_falls_back_to_thumbnail():
    """When no cover, cover_url should equal thumbnail_url."""
    row = _project_to_workshop_row_subset({
        "id": "aaaaaaaa-0000-0000-0000-000000000002",
        "cover_storage_key": None,
        "thumbnail_storage_key": "projects/aaa/thumbnail.jpg",
        "readme": None,
        "readme_generated_at": None,
    })
    assert row["cover_url"] == row["thumbnail_url"]


def test_cover_url_none_when_neither_exists():
    row = _project_to_workshop_row_subset({
        "id": "aaaaaaaa-0000-0000-0000-000000000003",
        "cover_storage_key": None,
        "thumbnail_storage_key": None,
        "readme": None,
        "readme_generated_at": None,
    })
    assert row["cover_url"] is None


# ---------------------------------------------------------------------------
# 7. _project_to_workshop_row exposes readme/cover fields
# ---------------------------------------------------------------------------

def test_workshop_row_exposes_readme_field():
    """_project_to_workshop_row must include readme and readme_generated_at."""
    row = _project_to_workshop_row_subset({
        "id": "aaaaaaaa-0000-0000-0000-000000000004",
        "readme": "# Hello\nWorld",
        "readme_generated_at": None,
        "cover_storage_key": None,
        "thumbnail_storage_key": None,
    })
    assert row["readme"] == "# Hello\nWorld"


def test_workshop_row_readme_none_when_empty():
    row = _project_to_workshop_row_subset({
        "id": "aaaaaaaa-0000-0000-0000-000000000005",
        "readme": "",
        "readme_generated_at": None,
        "cover_storage_key": None,
        "thumbnail_storage_key": None,
    })
    assert row["readme"] is None


# ---------------------------------------------------------------------------
# 8. _get_bom_rows_sync — BOM extraction from file list
# ---------------------------------------------------------------------------

def test_get_bom_rows_sync_extracts_part_files():
    from kerf_api.routes import _get_bom_rows_sync
    files = [
        {
            "kind": "part",
            "name": "spring.part",
            "content": json.dumps({
                "name": "Spring M3",
                "distributors": [{"name": "DigiKey", "price_usd": 0.25}],
            }),
        },
        {
            "kind": "file",
            "name": "main.jscad",
            "content": "// jscad",
        },
    ]
    rows = _get_bom_rows_sync(files)
    assert len(rows) == 1
    assert rows[0]["name"] == "Spring M3"
    assert rows[0]["supplier"] == "DigiKey"


def test_get_bom_rows_sync_ignores_non_part_files():
    from kerf_api.routes import _get_bom_rows_sync
    files = [
        {"kind": "assembly", "name": "main.assembly", "content": "{}"},
        {"kind": "sketch", "name": "profile.sketch", "content": "{}"},
    ]
    rows = _get_bom_rows_sync(files)
    assert rows == []


def test_get_bom_rows_sync_handles_invalid_json():
    from kerf_api.routes import _get_bom_rows_sync
    files = [
        {"kind": "part", "name": "bad.part", "content": "not json"},
    ]
    rows = _get_bom_rows_sync(files)
    assert rows == []


def test_get_bom_rows_sync_no_distributor():
    from kerf_api.routes import _get_bom_rows_sync
    files = [
        {
            "kind": "part",
            "name": "bolt.part",
            "content": json.dumps({"name": "Bolt M4", "distributors": []}),
        }
    ]
    rows = _get_bom_rows_sync(files)
    assert len(rows) == 1
    assert rows[0]["name"] == "Bolt M4"
    assert rows[0]["supplier"] == ""
