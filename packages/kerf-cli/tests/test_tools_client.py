"""Tests for kerf_cli.tools_client — the shared HTTP client for GET
/api/tools and POST /api/tools/call.

All HTTP is mocked (no network, no server). Mirrors the
`_make_urlopen_mock` style already used in test_sync.py / test_hydrate.py.
"""

from __future__ import annotations

import json
import urllib.error
from unittest.mock import MagicMock, patch

import pytest


def _mock_response(body: bytes | str) -> MagicMock:
    if isinstance(body, str):
        body = body.encode("utf-8")
    resp = MagicMock()
    resp.read.return_value = body
    resp.__enter__ = MagicMock(return_value=resp)
    resp.__exit__ = MagicMock(return_value=False)
    return resp


def _http_error(code: int, body: bytes | str = b"") -> urllib.error.HTTPError:
    if isinstance(body, str):
        body = body.encode("utf-8")
    exc = urllib.error.HTTPError("http://fake/api/tools", code, f"HTTP {code}", {}, None)
    exc.read = MagicMock(return_value=body)  # type: ignore[method-assign]
    return exc


# ---------------------------------------------------------------------------
# fetch_tools
# ---------------------------------------------------------------------------

class TestFetchTools:
    def test_success_returns_payload(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
        from kerf_cli import tools_client

        payload = {"tools": [{"name": "t1", "description": "d", "input_schema": {}}], "count": 1}
        with patch("urllib.request.urlopen", return_value=_mock_response(json.dumps(payload))) as m:
            out = tools_client.fetch_tools("http://fake-api", "tok", use_cache=False)
        assert out == payload
        # Authorization header was set correctly.
        req = m.call_args[0][0]
        assert req.headers["Authorization"] == "Bearer tok"
        assert req.full_url == "http://fake-api/api/tools"

    def test_auth_failure_maps_to_exit_code_2(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
        from kerf_cli import tools_client

        with patch("urllib.request.urlopen", side_effect=_http_error(401, json.dumps({"detail": "invalid token"}))):
            with pytest.raises(tools_client.ToolsAPIError) as exc_info:
                tools_client.fetch_tools("http://fake-api", "bad-tok", use_cache=False)
        assert exc_info.value.exit_code == 2
        assert "invalid token" in exc_info.value.message

    def test_server_error_maps_to_exit_code_3(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
        from kerf_cli import tools_client

        with patch("urllib.request.urlopen", side_effect=_http_error(503, json.dumps({"detail": "tool registry not ready"}))):
            with pytest.raises(tools_client.ToolsAPIError) as exc_info:
                tools_client.fetch_tools("http://fake-api", "tok", use_cache=False)
        assert exc_info.value.exit_code == 3
        assert "tool registry not ready" in exc_info.value.message

    def test_network_error_maps_to_exit_code_1(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
        from kerf_cli import tools_client

        with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("connection refused")):
            with pytest.raises(tools_client.ToolsAPIError) as exc_info:
                tools_client.fetch_tools("http://fake-api", "tok", use_cache=False)
        assert exc_info.value.exit_code == 1

    def test_invalid_json_response_maps_to_exit_code_3(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
        from kerf_cli import tools_client

        with patch("urllib.request.urlopen", return_value=_mock_response("not json")):
            with pytest.raises(tools_client.ToolsAPIError) as exc_info:
                tools_client.fetch_tools("http://fake-api", "tok", use_cache=False)
        assert exc_info.value.exit_code == 3


# ---------------------------------------------------------------------------
# on-disk cache
# ---------------------------------------------------------------------------

class TestToolsCache:
    def test_second_call_uses_cache_no_network(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
        from kerf_cli import tools_client

        payload = {"tools": [{"name": "t1"}], "count": 1}
        with patch("urllib.request.urlopen", return_value=_mock_response(json.dumps(payload))) as m:
            tools_client.fetch_tools("http://fake-api", "tok", use_cache=True)
            assert m.call_count == 1

        # Second call: cache hit, urlopen must NOT be called again — even
        # with a bogus token, since no request is made at all.
        with patch("urllib.request.urlopen", side_effect=AssertionError("should not hit network")):
            out = tools_client.fetch_tools("http://fake-api", "anything", use_cache=True)
        assert out == payload

    def test_use_cache_false_forces_refetch(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
        from kerf_cli import tools_client

        payload = {"tools": [], "count": 0}
        with patch("urllib.request.urlopen", return_value=_mock_response(json.dumps(payload))) as m:
            tools_client.fetch_tools("http://fake-api", "tok", use_cache=True)

        with patch("urllib.request.urlopen", return_value=_mock_response(json.dumps(payload))) as m2:
            tools_client.fetch_tools("http://fake-api", "tok", use_cache=False)
        assert m2.call_count == 1

    def test_cache_is_keyed_by_api_url(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
        from kerf_cli import tools_client

        payload_a = {"tools": [{"name": "a"}], "count": 1}
        payload_b = {"tools": [{"name": "b"}], "count": 1}
        with patch("urllib.request.urlopen", return_value=_mock_response(json.dumps(payload_a))):
            tools_client.fetch_tools("http://server-a", "tok", use_cache=True)
        with patch("urllib.request.urlopen", return_value=_mock_response(json.dumps(payload_b))):
            out_b = tools_client.fetch_tools("http://server-b", "tok", use_cache=True)
        assert out_b == payload_b

        with patch("urllib.request.urlopen", side_effect=AssertionError("should not hit network")):
            out_a = tools_client.fetch_tools("http://server-a", "tok", use_cache=True)
        assert out_a == payload_a

    def test_expired_cache_is_refetched(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
        from kerf_cli import tools_client

        payload = {"tools": [{"name": "t1"}], "count": 1}
        with patch("urllib.request.urlopen", return_value=_mock_response(json.dumps(payload))):
            tools_client.fetch_tools("http://fake-api", "tok", use_cache=True)

        # Force the cache entry to look stale.
        cache_path = tools_client._cache_path()
        data = json.loads(cache_path.read_text())
        for entry in data.values():
            entry["fetched_at"] = 0
        cache_path.write_text(json.dumps(data))

        payload2 = {"tools": [{"name": "t2"}], "count": 1}
        with patch("urllib.request.urlopen", return_value=_mock_response(json.dumps(payload2))) as m:
            out = tools_client.fetch_tools("http://fake-api", "tok", use_cache=True)
        assert m.call_count == 1
        assert out == payload2

    def test_clear_cache_removes_file(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
        from kerf_cli import tools_client

        payload = {"tools": [], "count": 0}
        with patch("urllib.request.urlopen", return_value=_mock_response(json.dumps(payload))):
            tools_client.fetch_tools("http://fake-api", "tok", use_cache=True)
        assert tools_client._cache_path().exists()

        tools_client.clear_cache()
        assert not tools_client._cache_path().exists()

    def test_corrupt_cache_file_is_ignored(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
        from kerf_cli import tools_client

        cache_path = tools_client._cache_path()
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text("{not valid json")

        payload = {"tools": [{"name": "t1"}], "count": 1}
        with patch("urllib.request.urlopen", return_value=_mock_response(json.dumps(payload))) as m:
            out = tools_client.fetch_tools("http://fake-api", "tok", use_cache=True)
        assert m.call_count == 1
        assert out == payload


# ---------------------------------------------------------------------------
# call_tool
# ---------------------------------------------------------------------------

class TestCallTool:
    def test_call_tool_posts_expected_body(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
        from kerf_cli import tools_client

        result_payload = {"ok": True}
        with patch("urllib.request.urlopen", return_value=_mock_response(json.dumps(result_payload))) as m:
            out = tools_client.call_tool(
                "http://fake-api", "tok", "create_file", {"path": "/a.txt"}, project_id="proj-1"
            )
        assert out == result_payload

        req = m.call_args[0][0]
        assert req.full_url == "http://fake-api/api/tools/call"
        assert req.method == "POST"
        body = json.loads(req.data.decode("utf-8"))
        assert body == {"tool": "create_file", "args": {"path": "/a.txt"}, "project_id": "proj-1"}

    def test_call_tool_omits_project_id_when_absent(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
        from kerf_cli import tools_client

        with patch("urllib.request.urlopen", return_value=_mock_response(json.dumps({}))) as m:
            tools_client.call_tool("http://fake-api", "tok", "search_kerf_docs", {"query": "x"})

        req = m.call_args[0][0]
        body = json.loads(req.data.decode("utf-8"))
        assert "project_id" not in body

    def test_unknown_tool_is_404_exit_code_3(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
        from kerf_cli import tools_client

        with patch(
            "urllib.request.urlopen",
            side_effect=_http_error(404, json.dumps({"detail": "unknown tool: nope"})),
        ):
            with pytest.raises(tools_client.ToolsAPIError) as exc_info:
                tools_client.call_tool("http://fake-api", "tok", "nope", {})
        assert exc_info.value.exit_code == 3
        assert "unknown tool: nope" in exc_info.value.message

    def test_tool_raised_500_surfaces_detail(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
        from kerf_cli import tools_client

        with patch(
            "urllib.request.urlopen",
            side_effect=_http_error(500, json.dumps({"detail": "tool 'x' raised: boom"})),
        ):
            with pytest.raises(tools_client.ToolsAPIError) as exc_info:
                tools_client.call_tool("http://fake-api", "tok", "x", {})
        assert "boom" in exc_info.value.message
