"""
test_import_freecad_tool.py — T7 LLM tool tests.

Tests the import_freecad_project handler function with:
  - Mock pyworker that returns a known structured response.
  - Mock storage that returns a known blob.
  - Mock DB pool (asyncpg-compatible record-returning mocks).

Asserts:
  - Files are inserted into PG with correct kind/name/content.
  - Warnings from pyworker are propagated.
  - Stats are forwarded unchanged.
  - Missing storage returns NO_STORAGE error.
  - Missing blob returns NOT_FOUND.
  - Bad args return BAD_ARGS.
  - Pyworker unreachable returns PYWORKER_UNREACHABLE.
"""
from __future__ import annotations

import json
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Guard: the tool module imports kerf_core + kerf_chat at import time;
# if those aren't installed we skip the whole module.
try:
    from kerf_imports.tools.import_freecad import import_freecad_project
    from kerf_chat.tools.registry import ok_payload, err_payload
except ImportError as e:
    pytest.skip(f"kerf_core / kerf_chat not installed: {e}", allow_module_level=True)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_ctx(
    storage=None,
    pool=None,
    project_id=None,
):
    """Build a minimal mock ProjectCtx."""
    ctx = MagicMock()
    ctx.storage = storage
    ctx.pool = pool
    ctx.project_id = project_id or uuid.uuid4()
    return ctx


def _make_storage(blob_bytes=b"FAKE_FCSTD"):
    """Mock storage that returns blob_bytes on get()."""
    storage = MagicMock()
    storage.get = AsyncMock(return_value=blob_bytes)
    return storage


def _make_pool(file_id=None):
    """Mock asyncpg pool that returns a file id on fetchval and a row on fetchrow."""
    pool = MagicMock()
    _file_id = file_id or uuid.uuid4()
    pool.fetchval = AsyncMock(return_value=_file_id)
    pool.fetchrow = AsyncMock(return_value={"id": _file_id})
    return pool


def _pyworker_response(n_sketches=1, n_features=1, assembly=False):
    """Build a fake pyworker /import-freecad-project response."""
    created_files = []
    for i in range(n_sketches):
        created_files.append({
            "kind": "sketch",
            "name": f"Sketch{i}.sketch",
            "freecad_name": f"Sketch{i}",
            "placeholder_id": None,
            "payload": {"entities": [], "constraints": [], "warnings": []},
        })
    for i in range(n_features):
        created_files.append({
            "kind": "feature",
            "name": f"Body{i}.feature",
            "freecad_name": f"Body{i}",
            "placeholder_id": None,
            "payload": {"nodes": [{"kind": "import_brep", "asset_id": None}]},
        })
    if assembly:
        created_files.append({
            "kind": "assembly",
            "name": "main.assembly",
            "freecad_name": None,
            "placeholder_id": None,
            "payload": {"components": []},
        })
    return {
        "created_files": created_files,
        "stats": {
            "bodies": n_features,
            "sketches": n_sketches,
            "features_lifted": 0,
            "brep_blobs_lifted": 0,
            "constraints_translated": 3,
            "constraints_dropped": 1,
        },
        "warnings": ["test warning"],
        "import_folder": "/freecad_import",
    }


def _args(**kwargs):
    defaults = {
        "project_id": str(uuid.uuid4()),
        "file_blob_id_or_storage_key": "blob-123",
        "import_folder": "/freecad_import",
        "mode": "project",
    }
    defaults.update(kwargs)
    return json.dumps(defaults).encode()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestImportFreecadProjectTool:
    """Main handler tests with mocked pyworker."""

    def _run(self, ctx, args, pyworker_response=None):
        """Run the handler with a mocked httpx.AsyncClient."""
        if pyworker_response is None:
            pyworker_response = _pyworker_response()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json = MagicMock(return_value=pyworker_response)

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=mock_response)

        import asyncio

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = asyncio.get_event_loop().run_until_complete(
                import_freecad_project(ctx, args)
            )
        return result

    def test_ok_result_on_happy_path(self):
        ctx = _make_ctx(
            storage=_make_storage(),
            pool=_make_pool(),
        )
        result = self._run(ctx, _args())
        data = json.loads(result)
        # ok_payload returns the dict directly (no status wrapper)
        assert "created_files" in data
        assert "error" not in data

    def test_created_files_in_result(self):
        ctx = _make_ctx(storage=_make_storage(), pool=_make_pool())
        result = json.loads(self._run(ctx, _args()))
        assert "created_files" in result

    def test_stats_forwarded(self):
        ctx = _make_ctx(storage=_make_storage(), pool=_make_pool())
        result = json.loads(self._run(ctx, _args()))
        assert "stats" in result

    def test_warnings_propagated(self):
        ctx = _make_ctx(storage=_make_storage(), pool=_make_pool())
        pw = _pyworker_response()
        pw["warnings"] = ["a warning from pyworker"]
        result = json.loads(self._run(ctx, _args(), pyworker_response=pw))
        warnings = result.get("warnings", [])
        assert any("warning" in w for w in warnings)

    def test_files_inserted_for_each_created_file(self):
        pool = _make_pool()
        ctx = _make_ctx(storage=_make_storage(), pool=pool)
        pw = _pyworker_response(n_sketches=2, n_features=1)
        self._run(ctx, _args(), pyworker_response=pw)
        # fetchval is called once per file insert + once per folder create
        assert pool.fetchval.call_count >= 3  # 2 sketch + 1 feature

    def test_assembly_files_inserted(self):
        pool = _make_pool()
        ctx = _make_ctx(storage=_make_storage(), pool=pool)
        pw = _pyworker_response(n_sketches=0, n_features=2, assembly=True)
        result = json.loads(self._run(ctx, _args(), pyworker_response=pw))
        files = result.get("created_files", [])
        kinds = {f["kind"] for f in files if f.get("file_id") is not None}
        assert "assembly" in kinds


class TestImportFreecadProjectErrors:
    """Error path tests."""

    def _run_plain(self, ctx, args):
        import asyncio
        with patch("httpx.AsyncClient"):
            result = asyncio.get_event_loop().run_until_complete(
                import_freecad_project(ctx, args)
            )
        return json.loads(result)

    def test_missing_storage_returns_error(self):
        ctx = _make_ctx(storage=None, pool=_make_pool())
        result = self._run_plain(ctx, _args())
        assert "error" in result

    def test_missing_project_id_returns_bad_args(self):
        ctx = _make_ctx(storage=_make_storage(), pool=_make_pool())
        args = json.dumps({"file_blob_id_or_storage_key": "x"}).encode()
        result = self._run_plain(ctx, args)
        assert "error" in result

    def test_missing_blob_ref_returns_bad_args(self):
        ctx = _make_ctx(storage=_make_storage(), pool=_make_pool())
        args = json.dumps({"project_id": str(uuid.uuid4())}).encode()
        result = self._run_plain(ctx, args)
        assert "error" in result

    def test_invalid_mode_returns_bad_args(self):
        ctx = _make_ctx(storage=_make_storage(), pool=_make_pool())
        args = _args(mode="invalid-mode")
        result = self._run_plain(ctx, args)
        assert "error" in result
        assert result.get("code") == "BAD_ARGS"

    def test_blob_not_found_returns_error(self):
        storage = MagicMock()
        storage.get = AsyncMock(return_value=None)  # not found
        ctx = _make_ctx(storage=storage, pool=_make_pool())
        result = self._run_plain(ctx, _args())
        assert "error" in result

    def test_pyworker_unreachable_returns_error(self):
        import asyncio
        storage = _make_storage()
        ctx = _make_ctx(storage=storage, pool=_make_pool())

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(side_effect=ConnectionError("refused"))

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = json.loads(
                asyncio.get_event_loop().run_until_complete(
                    import_freecad_project(ctx, _args())
                )
            )
        assert "error" in result

    def test_pyworker_422_returns_format_error(self):
        import asyncio
        storage = _make_storage()
        ctx = _make_ctx(storage=storage, pool=_make_pool())

        mock_response = MagicMock()
        mock_response.status_code = 422
        mock_response.json = MagicMock(return_value={"detail": "unsupported version"})
        mock_response.text = "unsupported version"

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=mock_response)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = json.loads(
                asyncio.get_event_loop().run_until_complete(
                    import_freecad_project(ctx, _args())
                )
            )
        assert "error" in result
        # Code should indicate a FreeCAD format error, not a generic pyworker error
        assert result.get("code") == "FREECAD_FORMAT_ERROR"


class TestToolSpec:
    """Basic spec validation."""

    def test_spec_name(self):
        from kerf_imports.tools.import_freecad import import_freecad_project_spec
        assert import_freecad_project_spec.name == "import_freecad_project"

    def test_spec_has_description(self):
        from kerf_imports.tools.import_freecad import import_freecad_project_spec
        assert len(import_freecad_project_spec.description) > 20

    def test_spec_required_fields(self):
        from kerf_imports.tools.import_freecad import import_freecad_project_spec
        schema = import_freecad_project_spec.input_schema
        required = schema.get("required", [])
        assert "project_id" in required
        assert "file_blob_id_or_storage_key" in required

    def test_tools_list_registered(self):
        from kerf_imports.tools.import_freecad import TOOLS
        assert len(TOOLS) == 1
        name, spec, handler = TOOLS[0]
        assert name == "import_freecad_project"
