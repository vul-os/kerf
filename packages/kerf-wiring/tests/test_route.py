"""
tests/test_route.py — hermetic tests for the /run-wireviz FastAPI route.

Uses httpx AsyncClient + FastAPI's TestClient; stubs out WireViz so the
tests run without the optional dependency installed.
"""
from __future__ import annotations

import sys
import types

import pytest

# ---------------------------------------------------------------------------
# Stub WireViz before the route module is imported
# ---------------------------------------------------------------------------

_STUB_SVG = "<svg xmlns='http://www.w3.org/2000/svg'><text>stub</text></svg>"


def _inject_wireviz_stub():
    """Put a minimal wireviz stub into sys.modules."""
    stub = types.ModuleType("wireviz")

    class _FakeHarness:
        def create_graph(self): pass
        def svg(self): return _STUB_SVG

    from pathlib import Path

    def _parse_file(path):
        if not Path(path).exists():
            raise FileNotFoundError(path)
        return _FakeHarness()

    stub.parse_file = _parse_file
    stub.Harness = _FakeHarness
    sys.modules["wireviz"] = stub


_inject_wireviz_stub()


# ---------------------------------------------------------------------------
# App fixture
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def client():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    # Reload route module so it picks up the stub
    sys.modules.pop("kerf_wiring.routes", None)
    sys.modules.pop("kerf_wiring.wireviz_runner", None)

    from kerf_wiring.routes import router

    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

MINIMAL_YAML = """\
connectors:
  X1:
    pincount: 1
    pins: [1]
cables:
  W1:
    wirecount: 1
    length: 0.3
connections:
  -
    - X1: [1]
    - W1: [1]
"""


class TestRunWirevizRoute:
    def test_valid_yaml_returns_svg(self, client):
        resp = client.post("/run-wireviz", json={"source": MINIMAL_YAML})
        assert resp.status_code == 200
        data = resp.json()
        assert data["svg"] is not None
        assert "<svg" in data["svg"]
        assert data["warnings"] == []

    def test_empty_source_returns_warning_not_500(self, client):
        resp = client.post("/run-wireviz", json={"source": ""})
        assert resp.status_code == 200
        data = resp.json()
        assert data["svg"] is None
        assert len(data["warnings"]) > 0

    def test_missing_wireviz_returns_graceful_warning(self, client, monkeypatch):
        """Block wireviz import mid-request."""
        monkeypatch.setitem(sys.modules, "wireviz", None)
        sys.modules.pop("kerf_wiring.wireviz_runner", None)

        resp = client.post("/run-wireviz", json={"source": MINIMAL_YAML})
        assert resp.status_code == 200
        data = resp.json()
        assert data["svg"] is None
        assert any("WireViz not installed" in w for w in data["warnings"])

        # Restore stub for subsequent tests
        _inject_wireviz_stub()
        sys.modules.pop("kerf_wiring.wireviz_runner", None)

    def test_non_string_source_returns_warning(self, client):
        resp = client.post("/run-wireviz", json={"source": 12345})
        assert resp.status_code == 200
        data = resp.json()
        assert data["svg"] is None
        assert len(data["warnings"]) > 0

    def test_missing_source_key_uses_empty_string(self, client):
        resp = client.post("/run-wireviz", json={})
        assert resp.status_code == 200
        data = resp.json()
        # Empty source → warning, not crash
        assert data["svg"] is None

    def test_response_shape(self, client):
        """Response always has 'svg' and 'warnings' keys."""
        resp = client.post("/run-wireviz", json={"source": MINIMAL_YAML})
        data = resp.json()
        assert "svg" in data
        assert "warnings" in data
        assert isinstance(data["warnings"], list)
