"""kerf mcp — expose Kerf's registered LLM tools over MCP, on stdio.

Usage
-----
    kerf mcp [--url URL] [--token TOKEN] [--project ID]

Maps every tool from ``GET /api/tools`` to an MCP tool (``name``,
``description``, ``inputSchema`` <- ``input_schema``) and routes
``tools/call`` through ``POST /api/tools/call`` (see
``kerf_cli.tools_client``).  Meant to be launched by an MCP client (Claude
Desktop, etc.) as a stdio subprocess — see ``docs/mcp.md`` for the exact
client configuration.

``--project`` sets a default ``project_id`` sent with every call (useful
when the whole MCP session is scoped to one Kerf project).  A caller can
override it per-call by including a ``project_id`` key in that call's
arguments — it is popped off before the remaining arguments are forwarded
as the tool's ``args``.

Requires the optional ``mcp`` dependency: ``pip install 'kerf-cli[mcp]'``.
The helper functions below (``list_mcp_tools``, ``build_call_tool_handler``)
are plain functions/closures so they can be unit-tested without a running
stdio transport or a live Kerf server (both are mocked in tests).
"""

from __future__ import annotations

import json
import sys
from typing import Any, Callable, Optional


def _require_mcp_package() -> None:
    try:
        import mcp  # noqa: F401
    except ImportError as exc:  # pragma: no cover - exercised via monkeypatch in tests
        print(
            "error: the 'mcp' package is not installed.\n"
            "       Install it with: pip install 'kerf-cli[mcp]'\n"
            f"       ({exc})",
            file=sys.stderr,
        )
        raise SystemExit(1) from exc


# ---------------------------------------------------------------------------
# Pure logic (testable without the mcp package's transport layer)
# ---------------------------------------------------------------------------

def tool_entry_to_mcp_tool(entry: dict) -> "Any":
    """Convert one entry of GET /api/tools's ``tools`` list to ``mcp.types.Tool``."""
    import mcp.types as types  # noqa: PLC0415

    return types.Tool(
        name=entry.get("name", ""),
        description=entry.get("description", "") or "",
        inputSchema=entry.get("input_schema") or {"type": "object", "properties": {}},
    )


def list_mcp_tools(api_url: str, token: str) -> list:
    """Fetch GET /api/tools and return it as a list of ``mcp.types.Tool``.

    On a ToolsAPIError, prints the error to stderr and returns an empty
    list (an MCP `tools/list` failure would otherwise kill the session;
    an empty tool set at least keeps the connection alive and visible).
    """
    from kerf_cli.tools_client import ToolsAPIError, fetch_tools  # noqa: PLC0415

    try:
        payload = fetch_tools(api_url, token)
    except ToolsAPIError as exc:
        print(f"error: {exc.message}", file=sys.stderr)
        return []
    return [tool_entry_to_mcp_tool(t) for t in payload.get("tools", [])]


def build_call_tool_handler(
    api_url: str, token: str, default_project_id: Optional[str]
) -> Callable[[str, dict], "Any"]:
    """Return an async handler suitable for ``@server.call_tool()``.

    Pops an optional ``project_id`` out of the call arguments (falling back
    to *default_project_id*), forwards the rest to POST /api/tools/call, and
    returns the result as a single ``mcp.types.TextContent`` block.  Any
    ``ToolsAPIError`` is left to propagate — the ``mcp`` SDK's ``call_tool``
    decorator turns an uncaught exception into an MCP error result
    (``isError=True``) automatically.
    """

    async def _handler(name: str, arguments: dict) -> list:
        import mcp.types as types  # noqa: PLC0415

        from kerf_cli.tools_client import call_tool  # noqa: PLC0415

        call_args = dict(arguments or {})
        project_id = call_args.pop("project_id", None) or default_project_id
        result = call_tool(api_url, token, name, call_args, project_id=project_id)
        return [types.TextContent(type="text", text=json.dumps(result, indent=2))]

    return _handler


# ---------------------------------------------------------------------------
# Entry point (called from main.py's `kerf mcp`)
# ---------------------------------------------------------------------------

def run_mcp_server(
    *,
    api_url: Optional[str] = None,
    api_token: Optional[str] = None,
    project_id: Optional[str] = None,
) -> int:
    """Block, running an MCP server over stdio.  Returns an exit code."""
    _require_mcp_package()

    import anyio  # noqa: PLC0415
    from mcp.server import Server  # noqa: PLC0415
    from mcp.server.stdio import stdio_server  # noqa: PLC0415

    from kerf_cli.credentials import get_api_url, get_api_token  # noqa: PLC0415

    resolved_url = (api_url or get_api_url()).rstrip("/")
    resolved_token = api_token or get_api_token()

    if not resolved_token:
        print(
            "error: no API token found. Set KERF_API_TOKEN, pass --token, or run "
            "`kerf login`.\n"
            f"       (server: {resolved_url})",
            file=sys.stderr,
        )
        return 2

    server: "Server" = Server("kerf-tools")

    @server.list_tools()
    async def _list_tools() -> list:
        return list_mcp_tools(resolved_url, resolved_token)

    server.call_tool(validate_input=False)(
        build_call_tool_handler(resolved_url, resolved_token, project_id)
    )

    async def _run() -> None:
        print(
            f"kerf mcp: serving Kerf tools over stdio (server: {resolved_url})",
            file=sys.stderr,
        )
        async with stdio_server() as (read_stream, write_stream):
            await server.run(read_stream, write_stream, server.create_initialization_options())

    try:
        anyio.run(_run)
    except KeyboardInterrupt:  # pragma: no cover - interactive interrupt
        pass
    return 0
