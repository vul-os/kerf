"""Tests for `kerf tools list/show/call`.

All HTTP is mocked via kerf_cli.tools_client (no network, no server).
"""

from __future__ import annotations

import io
import json
import sys
from unittest.mock import patch

import pytest


def _run_main(argv: list[str]) -> tuple[int, str, str]:
    """Invoke main() and return (exit_code, stdout_text, stderr_text)."""
    from kerf_cli.main import _build_parser

    parser = _build_parser()
    captured_out = io.StringIO()
    captured_err = io.StringIO()

    old_out, old_err = sys.stdout, sys.stderr
    sys.stdout, sys.stderr = captured_out, captured_err

    exit_code = 0
    try:
        args = parser.parse_args(argv)
        exit_code = args.func(args)
    except SystemExit as exc:
        exit_code = int(exc.code) if exc.code is not None else 0
    finally:
        sys.stdout, sys.stderr = old_out, old_err

    return exit_code, captured_out.getvalue(), captured_err.getvalue()


_SAMPLE_PAYLOAD = {
    "tools": [
        {"name": "create_file", "description": "Create a new file, folder, assembly, or drawing.", "input_schema": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}},
        {"name": "z_tool", "description": "Zzz " * 60, "input_schema": {"type": "object"}},
    ],
    "count": 2,
}


# ---------------------------------------------------------------------------
# Parser wiring
# ---------------------------------------------------------------------------

class TestParserSmoke:
    def test_tools_help_exits_zero(self):
        with pytest.raises(SystemExit) as exc_info:
            from kerf_cli.main import _build_parser
            _build_parser().parse_args(["tools", "--help"])
        assert exc_info.value.code == 0

    def test_tools_list_dispatches(self):
        from kerf_cli.main import _build_parser
        from kerf_cli.tools import _cmd_tools_list
        args = _build_parser().parse_args(["tools", "list"])
        assert args.func is _cmd_tools_list

    def test_tools_show_dispatches(self):
        from kerf_cli.main import _build_parser
        from kerf_cli.tools import _cmd_tools_show
        args = _build_parser().parse_args(["tools", "show", "create_file"])
        assert args.func is _cmd_tools_show
        assert args.name == "create_file"

    def test_tools_call_dispatches(self):
        from kerf_cli.main import _build_parser
        from kerf_cli.tools import _cmd_tools_call
        args = _build_parser().parse_args(["tools", "call", "create_file", "--args", "{}"])
        assert args.func is _cmd_tools_call

    def test_tools_call_rejects_missing_subcommand(self):
        from kerf_cli.main import _build_parser
        with pytest.raises(SystemExit):
            _build_parser().parse_args(["tools"])

    def test_mcp_dispatches(self):
        from kerf_cli.main import _build_parser, _cmd_mcp
        args = _build_parser().parse_args(["mcp"])
        assert args.func is _cmd_mcp


# ---------------------------------------------------------------------------
# tools list
# ---------------------------------------------------------------------------

class TestToolsList:
    def test_list_human_output(self, monkeypatch):
        with patch("kerf_cli.tools_client.fetch_tools", return_value=_SAMPLE_PAYLOAD):
            code, out, err = _run_main(
                ["tools", "list", "--url", "http://fake-api", "--token", "tok"]
            )
        assert code == 0
        assert "create_file" in out
        assert "z_tool" in out
        # Sorted alphabetically.
        assert out.index("create_file") < out.index("z_tool")

    def test_list_truncates_long_description_to_terminal_width(self, monkeypatch):
        monkeypatch.setattr("shutil.get_terminal_size", lambda fallback=None: __import__("os").terminal_size((60, 24)))
        with patch("kerf_cli.tools_client.fetch_tools", return_value=_SAMPLE_PAYLOAD):
            code, out, err = _run_main(
                ["tools", "list", "--url", "http://fake-api", "--token", "tok"]
            )
        assert code == 0
        for line in out.splitlines():
            assert len(line) <= 60

    def test_list_json_emits_raw_payload(self):
        with patch("kerf_cli.tools_client.fetch_tools", return_value=_SAMPLE_PAYLOAD):
            code, out, err = _run_main(
                ["tools", "list", "--json", "--url", "http://fake-api", "--token", "tok"]
            )
        assert code == 0
        assert json.loads(out) == _SAMPLE_PAYLOAD

    def test_list_no_token_exits_2(self, monkeypatch, tmp_path):
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
        monkeypatch.delenv("KERF_API_TOKEN", raising=False)
        code, out, err = _run_main(["tools", "list", "--url", "http://fake-api"])
        assert code == 2
        assert "no API token" in err

    def test_list_propagates_tools_api_error_exit_code(self):
        from kerf_cli.tools_client import ToolsAPIError
        with patch("kerf_cli.tools_client.fetch_tools", side_effect=ToolsAPIError("boom", exit_code=1)):
            code, out, err = _run_main(
                ["tools", "list", "--url", "http://fake-api", "--token", "tok"]
            )
        assert code == 1
        assert "boom" in err

    def test_list_no_cache_flag_passed_through(self):
        with patch("kerf_cli.tools_client.fetch_tools", return_value=_SAMPLE_PAYLOAD) as m:
            _run_main(["tools", "list", "--no-cache", "--url", "http://fake-api", "--token", "tok"])
        assert m.call_args.kwargs["use_cache"] is False


# ---------------------------------------------------------------------------
# tools show
# ---------------------------------------------------------------------------

class TestToolsShow:
    def test_show_prints_input_schema(self):
        with patch("kerf_cli.tools_client.fetch_tools", return_value=_SAMPLE_PAYLOAD):
            code, out, err = _run_main(
                ["tools", "show", "create_file", "--url", "http://fake-api", "--token", "tok"]
            )
        assert code == 0
        assert json.loads(out) == _SAMPLE_PAYLOAD["tools"][0]["input_schema"]

    def test_show_unknown_tool_exits_3(self):
        with patch("kerf_cli.tools_client.fetch_tools", return_value=_SAMPLE_PAYLOAD):
            code, out, err = _run_main(
                ["tools", "show", "does_not_exist", "--url", "http://fake-api", "--token", "tok"]
            )
        assert code == 3
        assert "does_not_exist" in err


# ---------------------------------------------------------------------------
# tools call
# ---------------------------------------------------------------------------

class TestToolsCall:
    def test_call_with_inline_args(self):
        with patch("kerf_cli.tools_client.call_tool", return_value={"id": "f1"}) as m:
            code, out, err = _run_main(
                [
                    "tools", "call", "create_file",
                    "--args", '{"path": "/a.txt"}',
                    "--url", "http://fake-api", "--token", "tok",
                ]
            )
        assert code == 0
        assert json.loads(out) == {"id": "f1"}
        _, kwargs = m.call_args
        assert m.call_args[0][2] == "create_file"
        assert m.call_args[0][3] == {"path": "/a.txt"}

    def test_call_with_args_file(self, tmp_path):
        args_file = tmp_path / "args.json"
        args_file.write_text(json.dumps({"path": "/b.txt"}))
        with patch("kerf_cli.tools_client.call_tool", return_value={"id": "f2"}) as m:
            code, out, err = _run_main(
                [
                    "tools", "call", "create_file",
                    "--args-file", str(args_file),
                    "--url", "http://fake-api", "--token", "tok",
                ]
            )
        assert code == 0
        assert m.call_args[0][3] == {"path": "/b.txt"}

    def test_call_with_project_id(self):
        with patch("kerf_cli.tools_client.call_tool", return_value={}) as m:
            _run_main(
                [
                    "tools", "call", "create_file",
                    "--args", "{}", "--project", "proj-123",
                    "--url", "http://fake-api", "--token", "tok",
                ]
            )
        assert m.call_args.kwargs["project_id"] == "proj-123"

    def test_call_both_args_and_args_file_is_error(self, tmp_path):
        args_file = tmp_path / "args.json"
        args_file.write_text("{}")
        code, out, err = _run_main(
            [
                "tools", "call", "create_file",
                "--args", "{}", "--args-file", str(args_file),
                "--url", "http://fake-api", "--token", "tok",
            ]
        )
        assert code == 1
        assert "not both" in err

    def test_call_invalid_json_args_exits_1(self):
        code, out, err = _run_main(
            [
                "tools", "call", "create_file",
                "--args", "{not json",
                "--url", "http://fake-api", "--token", "tok",
            ]
        )
        assert code == 1
        assert "not valid JSON" in err

    def test_call_non_object_args_exits_1(self):
        code, out, err = _run_main(
            [
                "tools", "call", "create_file",
                "--args", "[1, 2, 3]",
                "--url", "http://fake-api", "--token", "tok",
            ]
        )
        assert code == 1
        assert "JSON object" in err

    def test_call_missing_args_file_exits_1(self, tmp_path):
        missing = tmp_path / "nope.json"
        code, out, err = _run_main(
            [
                "tools", "call", "create_file",
                "--args-file", str(missing),
                "--url", "http://fake-api", "--token", "tok",
            ]
        )
        assert code == 1
        assert "could not read" in err

    def test_call_server_error_exits_with_server_message_on_stderr(self):
        from kerf_cli.tools_client import ToolsAPIError
        with patch(
            "kerf_cli.tools_client.call_tool",
            side_effect=ToolsAPIError("HTTP 404 from http://fake-api/api/tools/call: unknown tool: nope", exit_code=3),
        ):
            code, out, err = _run_main(
                [
                    "tools", "call", "nope",
                    "--args", "{}",
                    "--url", "http://fake-api", "--token", "tok",
                ]
            )
        assert code == 3
        assert out == ""
        assert "unknown tool: nope" in err

    def test_call_auth_failure_exits_2(self):
        from kerf_cli.tools_client import ToolsAPIError
        with patch("kerf_cli.tools_client.call_tool", side_effect=ToolsAPIError("auth failure", exit_code=2)):
            code, out, err = _run_main(
                [
                    "tools", "call", "create_file",
                    "--args", "{}",
                    "--url", "http://fake-api", "--token", "bad",
                ]
            )
        assert code == 2

    def test_call_no_args_defaults_to_empty_object(self):
        with patch("kerf_cli.tools_client.call_tool", return_value={}) as m:
            _run_main(
                ["tools", "call", "search_kerf_docs", "--url", "http://fake-api", "--token", "tok"]
            )
        assert m.call_args[0][3] == {}
