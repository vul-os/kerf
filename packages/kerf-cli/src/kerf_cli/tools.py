"""kerf tools — list, inspect, and invoke Kerf's registered LLM tools.

Usage
-----
    kerf tools list [--json]
    kerf tools show <name>
    kerf tools call <name> [--args '{...}'] [--args-file f.json] [--project ID]

Talks to ``GET /api/tools`` and ``POST /api/tools/call`` on the Kerf server
(the same 350+-tool registry the web app's LLM assistant uses) — see
``kerf_cli.tools_client`` for the wire format.  Authentication is the same
as `kerf sync` / `kerf export`: ``KERF_API_URL`` / ``KERF_API_TOKEN``, or
credentials saved by `kerf login`.

Exit codes
----------
0 — success.
1 — local error (bad --args JSON, unreadable --args-file, network/timeout).
2 — authentication failure (HTTP 401/403).
3 — server/tool error (unknown tool, tool raised, bad response, etc.).
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from typing import Optional


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _resolve_url_token(args: argparse.Namespace) -> tuple[str, Optional[str]]:
    from kerf_cli.credentials import get_api_url, get_api_token  # noqa: PLC0415

    api_url = get_api_url()
    if getattr(args, "url", None):
        api_url = args.url.rstrip("/")

    token = getattr(args, "token", None) or get_api_token()
    return api_url, token


def _require_token(token: Optional[str], api_url: str) -> Optional[int]:
    if not token:
        print(
            "error: no API token found. Set KERF_API_TOKEN or pass --token.\n"
            f"       (server: {api_url}) Run `kerf login` to store one.",
            file=sys.stderr,
        )
        return 2
    return None


# ---------------------------------------------------------------------------
# list
# ---------------------------------------------------------------------------

def _cmd_tools_list(args: argparse.Namespace) -> int:
    from kerf_cli.tools_client import fetch_tools, ToolsAPIError  # noqa: PLC0415

    api_url, token = _resolve_url_token(args)
    err = _require_token(token, api_url)
    if err is not None:
        return err

    try:
        payload = fetch_tools(api_url, token, use_cache=not args.no_cache)
    except ToolsAPIError as exc:
        print(f"error: {exc.message}", file=sys.stderr)
        return exc.exit_code

    if args.json:
        print(json.dumps(payload, indent=2))
        return 0

    tools = payload.get("tools", [])
    if not tools:
        print("No tools available.", file=sys.stderr)
        return 0

    print(_format_tools_table(tools))
    return 0


def _format_tools_table(tools: list[dict]) -> str:
    """Aligned ``name  description`` listing, truncated to terminal width."""
    term_width = shutil.get_terminal_size(fallback=(100, 24)).columns
    name_width = min(max((len(t.get("name", "")) for t in tools), default=0), 40)

    lines = []
    for tool in sorted(tools, key=lambda t: t.get("name", "")):
        name = tool.get("name", "")
        desc = " ".join((tool.get("description") or "").split())  # collapse whitespace
        prefix = f"{name:<{name_width}}  "
        avail = max(term_width - len(prefix), 10)
        if len(desc) > avail:
            desc = desc[: max(avail - 1, 0)].rstrip() + "…"
        lines.append(prefix + desc)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# show
# ---------------------------------------------------------------------------

def _cmd_tools_show(args: argparse.Namespace) -> int:
    from kerf_cli.tools_client import fetch_tools, ToolsAPIError  # noqa: PLC0415

    api_url, token = _resolve_url_token(args)
    err = _require_token(token, api_url)
    if err is not None:
        return err

    try:
        payload = fetch_tools(api_url, token, use_cache=not args.no_cache)
    except ToolsAPIError as exc:
        print(f"error: {exc.message}", file=sys.stderr)
        return exc.exit_code

    tools = payload.get("tools", [])
    match = next((t for t in tools if t.get("name") == args.name), None)
    if match is None:
        print(f"error: unknown tool: {args.name!r}", file=sys.stderr)
        return 3

    print(json.dumps(match.get("input_schema", {}), indent=2))
    return 0


# ---------------------------------------------------------------------------
# call
# ---------------------------------------------------------------------------

def _load_call_args(args: argparse.Namespace) -> tuple[Optional[dict], Optional[int]]:
    """Return (args_dict, None) on success, or (None, exit_code) on error."""
    if args.args and args.args_file:
        print("error: pass either --args or --args-file, not both.", file=sys.stderr)
        return None, 1

    raw: str
    if args.args_file:
        try:
            with open(args.args_file, "r", encoding="utf-8") as f:
                raw = f.read()
        except OSError as exc:
            print(f"error: could not read --args-file {args.args_file!r}: {exc}", file=sys.stderr)
            return None, 1
    elif args.args:
        raw = args.args
    else:
        return {}, None

    try:
        parsed = json.loads(raw)
    except ValueError as exc:
        src = "--args-file" if args.args_file else "--args"
        print(f"error: {src} is not valid JSON: {exc}", file=sys.stderr)
        return None, 1

    if not isinstance(parsed, dict):
        print("error: tool arguments must be a JSON object.", file=sys.stderr)
        return None, 1

    return parsed, None


def _cmd_tools_call(args: argparse.Namespace) -> int:
    from kerf_cli.tools_client import call_tool, ToolsAPIError  # noqa: PLC0415

    api_url, token = _resolve_url_token(args)
    err = _require_token(token, api_url)
    if err is not None:
        return err

    call_args, err_code = _load_call_args(args)
    if err_code is not None:
        return err_code

    try:
        result = call_tool(api_url, token, args.name, call_args or {}, project_id=args.project or None)
    except ToolsAPIError as exc:
        print(f"error: {exc.message}", file=sys.stderr)
        return exc.exit_code

    print(json.dumps(result, indent=2))
    return 0


# ---------------------------------------------------------------------------
# Parser wiring (called from main.py)
# ---------------------------------------------------------------------------

def add_tools_parser(sub: "argparse._SubParsersAction") -> None:  # type: ignore[type-arg]
    """Register the ``tools`` subcommand group onto *sub*."""
    tools_p = sub.add_parser(
        "tools",
        help="List, inspect, and invoke Kerf's registered LLM tools",
        description=(
            "Drive Kerf's 350+ registered LLM tools from a terminal or a\n"
            "script.  Backed by GET /api/tools and POST /api/tools/call on\n"
            "the Kerf server.\n\n"
            "KERF_API_URL / KERF_API_TOKEN or `kerf login` credentials are\n"
            "used for authentication."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    tools_sub = tools_p.add_subparsers(dest="tools_command", metavar="<tools-command>")
    tools_sub.required = True

    def _add_common(p: argparse.ArgumentParser) -> None:
        p.add_argument(
            "--url", default="", metavar="URL",
            help="Override the API endpoint (default: $KERF_API_URL or https://app.kerf.io).",
        )
        p.add_argument(
            "--token", default="", metavar="TOKEN",
            help="API token (kerf_sk_...). $KERF_API_TOKEN is preferred.",
        )

    # ---- list ----
    list_p = tools_sub.add_parser(
        "list",
        help="List all available tools",
        description="List every tool from GET /api/tools as `name  description`.",
    )
    _add_common(list_p)
    list_p.add_argument("--json", action="store_true", default=False, help="Emit the raw JSON payload.")
    list_p.add_argument(
        "--no-cache", action="store_true", default=False,
        help="Bypass the 5-minute on-disk tools-list cache.",
    )
    list_p.set_defaults(func=_cmd_tools_list)

    # ---- show ----
    show_p = tools_sub.add_parser(
        "show",
        help="Print one tool's input schema",
        description="Print a single tool's input_schema as JSON, so an LLM (or you) can construct valid --args.",
    )
    _add_common(show_p)
    show_p.add_argument("name", metavar="name", help="Tool name (as listed by `kerf tools list`).")
    show_p.add_argument(
        "--no-cache", action="store_true", default=False,
        help="Bypass the 5-minute on-disk tools-list cache.",
    )
    show_p.set_defaults(func=_cmd_tools_show)

    # ---- call ----
    call_p = tools_sub.add_parser(
        "call",
        help="Invoke a tool via POST /api/tools/call",
        description=(
            "Call a tool by name and print its JSON result to stdout.\n"
            "Exits non-zero on error, with the server's message on stderr,\n"
            "so scripts can branch on the exit code (see `kerf tools --help`)."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    _add_common(call_p)
    call_p.add_argument("name", metavar="name", help="Tool name (as listed by `kerf tools list`).")
    call_p.add_argument("--args", default="", metavar="JSON", help="Tool arguments as a JSON object.")
    call_p.add_argument(
        "--args-file", default="", metavar="FILE",
        help="Read tool arguments (JSON object) from a file instead of --args.",
    )
    call_p.add_argument(
        "--project", default="", metavar="ID",
        help="Kerf project UUID to scope the call to (omit for a stateless call).",
    )
    call_p.set_defaults(func=_cmd_tools_call)

    tools_p.set_defaults(func=_cmd_tools)


def _cmd_tools(args: argparse.Namespace) -> int:
    """Fallback dispatcher — reached only if a subcommand didn't set its own func."""
    print(f"Unknown tools command: {getattr(args, 'tools_command', None)}", file=sys.stderr)
    return 1
