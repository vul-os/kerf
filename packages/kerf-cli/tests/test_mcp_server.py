"""Tests for kerf_cli.mcp_server — the `kerf mcp` stdio MCP server.

The pure helpers (tool_entry_to_mcp_tool, list_mcp_tools,
build_call_tool_handler) are tested directly against a mocked
kerf_cli.tools_client, so these tests need the real `mcp` package (declared
in the `mcp`/`dev` extras) but never a running Kerf server or a real stdio
transport.

If the `mcp` package is not installed, this whole module is skipped —
`kerf mcp` itself degrades the same way (see test_cli_help_does_not_need_mcp
in test_tools_cli-adjacent coverage / main.py's lazy import).
"""

from __future__ import annotations

import asyncio
import json
from unittest.mock import patch

import pytest

mcp = pytest.importorskip("mcp")


_SAMPLE_PAYLOAD = {
    "tools": [
        {
            "name": "create_file",
            "description": "Create a new file.",
            "input_schema": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]},
        },
        {
            "name": "no_schema_tool",
            "description": None,
            "input_schema": None,
        },
    ],
    "count": 2,
}


def _run(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# tool_entry_to_mcp_tool
# ---------------------------------------------------------------------------

class TestToolEntryConversion:
    def test_maps_name_description_schema(self):
        from kerf_cli.mcp_server import tool_entry_to_mcp_tool

        t = tool_entry_to_mcp_tool(_SAMPLE_PAYLOAD["tools"][0])
        assert t.name == "create_file"
        assert t.description == "Create a new file."
        assert t.inputSchema == _SAMPLE_PAYLOAD["tools"][0]["input_schema"]

    def test_defaults_missing_description_and_schema(self):
        from kerf_cli.mcp_server import tool_entry_to_mcp_tool

        t = tool_entry_to_mcp_tool(_SAMPLE_PAYLOAD["tools"][1])
        assert t.name == "no_schema_tool"
        assert t.description == ""
        assert t.inputSchema == {"type": "object", "properties": {}}


# ---------------------------------------------------------------------------
# list_mcp_tools
# ---------------------------------------------------------------------------

class TestListMcpTools:
    def test_lists_all_tools(self):
        from kerf_cli.mcp_server import list_mcp_tools

        with patch("kerf_cli.tools_client.fetch_tools", return_value=_SAMPLE_PAYLOAD):
            tools = list_mcp_tools("http://fake-api", "tok")
        assert len(tools) == 2
        assert {t.name for t in tools} == {"create_file", "no_schema_tool"}

    def test_api_error_returns_empty_list_not_raise(self, capsys):
        from kerf_cli.mcp_server import list_mcp_tools
        from kerf_cli.tools_client import ToolsAPIError

        with patch("kerf_cli.tools_client.fetch_tools", side_effect=ToolsAPIError("unreachable", exit_code=1)):
            tools = list_mcp_tools("http://fake-api", "tok")
        assert tools == []
        assert "unreachable" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# build_call_tool_handler
# ---------------------------------------------------------------------------

class TestCallToolHandler:
    def test_forwards_args_and_returns_text_content(self):
        from kerf_cli.mcp_server import build_call_tool_handler

        handler = build_call_tool_handler("http://fake-api", "tok", default_project_id=None)
        with patch("kerf_cli.tools_client.call_tool", return_value={"id": "f1"}) as m:
            result = _run(handler("create_file", {"path": "/a.txt"}))

        m.assert_called_once_with("http://fake-api", "tok", "create_file", {"path": "/a.txt"}, project_id=None)
        assert len(result) == 1
        assert json.loads(result[0].text) == {"id": "f1"}

    def test_per_call_project_id_overrides_default_and_is_stripped_from_args(self):
        from kerf_cli.mcp_server import build_call_tool_handler

        handler = build_call_tool_handler("http://fake-api", "tok", default_project_id="default-proj")
        with patch("kerf_cli.tools_client.call_tool", return_value={}) as m:
            _run(handler("create_file", {"path": "/a.txt", "project_id": "override-proj"}))

        m.assert_called_once_with(
            "http://fake-api", "tok", "create_file", {"path": "/a.txt"}, project_id="override-proj"
        )

    def test_default_project_id_used_when_not_overridden(self):
        from kerf_cli.mcp_server import build_call_tool_handler

        handler = build_call_tool_handler("http://fake-api", "tok", default_project_id="default-proj")
        with patch("kerf_cli.tools_client.call_tool", return_value={}) as m:
            _run(handler("create_file", {"path": "/a.txt"}))

        assert m.call_args.kwargs["project_id"] == "default-proj"

    def test_none_arguments_treated_as_empty_dict(self):
        from kerf_cli.mcp_server import build_call_tool_handler

        handler = build_call_tool_handler("http://fake-api", "tok", default_project_id=None)
        with patch("kerf_cli.tools_client.call_tool", return_value={}) as m:
            _run(handler("search_kerf_docs", None))

        assert m.call_args[0][3] == {}

    def test_tools_api_error_propagates(self):
        """An uncaught exception here is what makes the mcp SDK's call_tool
        decorator turn the response into isError=True — so this handler must
        NOT swallow ToolsAPIError itself."""
        from kerf_cli.mcp_server import build_call_tool_handler
        from kerf_cli.tools_client import ToolsAPIError

        handler = build_call_tool_handler("http://fake-api", "tok", default_project_id=None)
        with patch("kerf_cli.tools_client.call_tool", side_effect=ToolsAPIError("unknown tool: nope", exit_code=3)):
            with pytest.raises(ToolsAPIError):
                _run(handler("nope", {}))


# ---------------------------------------------------------------------------
# run_mcp_server — argument resolution / fail-fast paths only (no real
# stdio transport is started in these tests).
# ---------------------------------------------------------------------------

class TestRequireMcpPackage:
    def test_prints_install_hint_when_mcp_missing(self, monkeypatch, capsys):
        """Exercise the real ImportError branch of _require_mcp_package by
        making `import mcp` fail, regardless of whether the real `mcp`
        package happens to be installed in this test environment."""
        import builtins

        from kerf_cli import mcp_server

        real_import = builtins.__import__

        def _fake_import(name, *args, **kwargs):
            if name == "mcp":
                raise ImportError("No module named 'mcp'")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", _fake_import)
        with pytest.raises(SystemExit) as exc_info:
            mcp_server._require_mcp_package()
        assert exc_info.value.code == 1
        assert "pip install 'kerf-cli[mcp]'" in capsys.readouterr().err


class TestRunMcpServer:
    def test_missing_token_returns_exit_code_2(self, monkeypatch, tmp_path, capsys):
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
        monkeypatch.delenv("KERF_API_TOKEN", raising=False)
        from kerf_cli.mcp_server import run_mcp_server

        code = run_mcp_server(api_url="http://fake-api", api_token=None)
        assert code == 2
        assert "no API token" in capsys.readouterr().err

    def test_missing_mcp_package_exits_cleanly(self, monkeypatch, capsys):
        from kerf_cli import mcp_server

        def _raise_import_error():
            print("error: the 'mcp' package is not installed.", file=__import__("sys").stderr)
            raise SystemExit(1)

        monkeypatch.setattr(mcp_server, "_require_mcp_package", _raise_import_error)
        with pytest.raises(SystemExit) as exc_info:
            mcp_server.run_mcp_server(api_url="http://fake-api", api_token="tok")
        assert exc_info.value.code == 1
        assert "mcp" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# Parser wiring (no mcp package needed — argparse only)
# ---------------------------------------------------------------------------

class TestMcpParser:
    def test_mcp_help_exits_zero(self):
        with pytest.raises(SystemExit) as exc_info:
            from kerf_cli.main import _build_parser
            _build_parser().parse_args(["mcp", "--help"])
        assert exc_info.value.code == 0

    def test_mcp_flags_parsed(self):
        from kerf_cli.main import _build_parser
        args = _build_parser().parse_args(
            ["mcp", "--url", "http://x", "--token", "tok", "--project", "proj-1"]
        )
        assert args.url == "http://x"
        assert args.token == "tok"
        assert args.project == "proj-1"
