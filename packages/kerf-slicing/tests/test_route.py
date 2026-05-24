"""
tests/test_route.py — hermetic tests for the /run-print-slice FastAPI route.

Uses FastAPI TestClient; stubs out the cura_runner so tests run without
CuraEngine installed.
"""
from __future__ import annotations

import sys
import tempfile
import textwrap
import types
import unittest.mock as mock
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Stub cura_runner before route module is imported
# ---------------------------------------------------------------------------

FAKE_GCODE = textwrap.dedent("""\
    ;FLAVOR:Marlin
    ;TIME:1800
    ;Filament used: 1000.5
    ;LAYER_COUNT:50
    G28
    ;LAYER:0
    G1 X0 Y0 E0.1
""")


def _inject_cura_stub(succeed: bool = True):
    """Inject a stub for cura_runner into sys.modules."""
    stub = types.ModuleType("kerf_slicing.cura_runner")

    class _CuraEngineNotInstalledError(RuntimeError):
        pass

    class _CuraEngineError(RuntimeError):
        pass

    class _SliceResult:
        def __init__(self):
            self.gcode = FAKE_GCODE
            self.layer_count = 50
            self.print_time_s = 1800
            self.filament_mm = 1000.5
            self.gcode_bytes = len(FAKE_GCODE.encode())
            self.warnings = []

    def _run(stl_path, settings=None):
        if not succeed:
            raise _CuraEngineNotInstalledError(
                "CuraEngine not found. Install it and ensure it is on PATH."
            )
        p = Path(stl_path)
        if not p.exists():
            raise FileNotFoundError(stl_path)
        return _SliceResult()

    stub.CuraEngineNotInstalledError = _CuraEngineNotInstalledError
    stub.CuraEngineError = _CuraEngineError
    stub.run_cura_slice = _run
    sys.modules["kerf_slicing.cura_runner"] = stub


_inject_cura_stub()


# ---------------------------------------------------------------------------
# App fixture
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def client():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from kerf_core.dependencies import require_auth

    # Re-inject stub so previous test modules can't strip it
    _inject_cura_stub()
    sys.modules.pop("kerf_slicing.routes", None)

    from kerf_slicing.routes import router
    app = FastAPI()
    app.include_router(router)

    # Override auth: inject a fake authenticated user for all tests
    app.dependency_overrides[require_auth] = lambda: {"sub": "test-user"}

    # Patch storage root to the system temp dir so tmp_path files are allowed
    import kerf_slicing.routes as _routes
    _routes._get_storage_root = lambda: Path(tempfile.gettempdir()).resolve()

    return TestClient(app)


@pytest.fixture()
def stl_file(tmp_path):
    stl = tmp_path / "test.stl"
    stl.write_text("solid test\nendsolid test\n")
    return str(stl)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestRunPrintSliceRoute:
    def test_valid_request_returns_gcode(self, client, stl_file):
        resp = client.post("/run-print-slice", json={
            "stl_path": stl_file,
            "settings": {"layer_height": 0.2},
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["gcode"] is not None
        assert ";LAYER_COUNT:50" in data["gcode"]
        assert data["layer_count"] == 50
        assert data["print_time_s"] == 1800
        assert data["warnings"] == []
        assert data["error"] is None

    def test_empty_stl_path_returns_warning(self, client):
        resp = client.post("/run-print-slice", json={"stl_path": ""})
        assert resp.status_code == 200
        data = resp.json()
        assert data["gcode"] is None
        assert len(data["warnings"]) > 0
        assert data["error"] == "BAD_ARGS"

    def test_missing_stl_path_key_returns_warning(self, client):
        resp = client.post("/run-print-slice", json={})
        assert resp.status_code == 200
        data = resp.json()
        assert data["gcode"] is None
        assert data["error"] == "BAD_ARGS"

    def test_cura_not_installed_returns_graceful_error(self, client, stl_file, monkeypatch):
        """When CuraEngine is missing, route returns CURA_NOT_INSTALLED error."""
        _inject_cura_stub(succeed=False)
        sys.modules.pop("kerf_slicing.routes", None)

        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from kerf_core.dependencies import require_auth
        from kerf_slicing.routes import router

        app = FastAPI()
        app.include_router(router)
        app.dependency_overrides[require_auth] = lambda: {"sub": "test-user"}

        import kerf_slicing.routes as _routes
        _routes._get_storage_root = lambda: Path(tempfile.gettempdir()).resolve()

        c = TestClient(app)

        resp = c.post("/run-print-slice", json={"stl_path": stl_file})
        assert resp.status_code == 200
        data = resp.json()
        assert data["gcode"] is None
        assert data["error"] == "CURA_NOT_INSTALLED"
        assert any("CuraEngine" in w for w in data["warnings"])

        # Restore succeed stub for subsequent tests
        _inject_cura_stub(succeed=True)
        sys.modules.pop("kerf_slicing.routes", None)

    def test_missing_stl_file_returns_stl_not_found(self, client, tmp_path):
        """A nonexistent path inside the storage root returns STL_NOT_FOUND."""
        # Path must be inside storage root (system temp) to pass path confinement
        nonexistent = str(tmp_path / "nonexistent_model.stl")
        resp = client.post("/run-print-slice", json={"stl_path": nonexistent})
        assert resp.status_code == 200
        data = resp.json()
        assert data["gcode"] is None
        assert data["error"] == "STL_NOT_FOUND"

    def test_path_outside_storage_root_returns_400(self, client):
        """A path outside the storage root is rejected with 400."""
        resp = client.post("/run-print-slice", json={
            "stl_path": "/etc/passwd",
        })
        assert resp.status_code == 400

    def test_response_always_has_required_keys(self, client, stl_file):
        resp = client.post("/run-print-slice", json={"stl_path": stl_file})
        data = resp.json()
        for key in ("gcode", "layer_count", "print_time_s", "filament_mm",
                    "gcode_bytes", "warnings", "error"):
            assert key in data, f"missing key: {key}"

    def test_settings_dict_is_optional(self, client, stl_file):
        resp = client.post("/run-print-slice", json={"stl_path": stl_file})
        assert resp.status_code == 200
        assert resp.json()["gcode"] is not None

    def test_non_string_stl_path_returns_bad_args(self, client):
        resp = client.post("/run-print-slice", json={"stl_path": 42})
        assert resp.status_code == 200
        assert resp.json()["error"] == "BAD_ARGS"

    def test_unauthenticated_request_returns_401(self):
        """Without auth override, the route returns 401."""
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        _inject_cura_stub()
        sys.modules.pop("kerf_slicing.routes", None)
        from kerf_slicing.routes import router

        app = FastAPI()
        app.include_router(router)
        # No dependency_overrides — auth is enforced

        c = TestClient(app, raise_server_exceptions=False)
        resp = c.post("/run-print-slice", json={"stl_path": "/tmp/x.stl"})
        assert resp.status_code == 401
