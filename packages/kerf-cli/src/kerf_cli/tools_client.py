"""Shared HTTP client for the Kerf tools API.

Both ``kerf tools`` (CLI) and ``kerf mcp`` (MCP stdio server) talk to the
same two endpoints on the Kerf server:

``GET /api/tools``
    Returns ``{"tools": [{"name", "description", "input_schema"}, ...],
    "count": N}`` — the full registry of LLM-callable tools (350+).

``POST /api/tools/call``
    Body ``{"tool": <name>, "args": {...}, "project_id": <uuid?>}``.
    Dispatches to the named tool and returns its JSON result.

This module is the single place that knows those two shapes so the CLI and
the MCP server can't drift apart.  Both endpoints require
``Authorization: Bearer <token>`` (either a JWT or a ``kerf_sk_...`` API
token — see ``kerf_core.dependencies.require_auth``).

Errors are raised as :class:`ToolsAPIError` with an ``exit_code`` that
follows the same convention used elsewhere in kerf-cli (``export.py``,
``sync.py``): ``1`` local/network error, ``2`` auth failure, ``3``
server/tool error.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Optional

_CACHE_TTL_SECONDS = 300  # 5 minutes
_DEFAULT_TIMEOUT = 30.0


class ToolsAPIError(Exception):
    """Raised when a request to /api/tools or /api/tools/call fails.

    ``exit_code`` — 1 (local/network), 2 (auth), or 3 (server/tool error) —
    matches the exit-code convention used by ``export.py`` / ``sync.py`` so
    callers of the CLI can branch on it reliably.
    """

    def __init__(self, message: str, exit_code: int = 3) -> None:
        super().__init__(message)
        self.message = message
        self.exit_code = exit_code


# ---------------------------------------------------------------------------
# On-disk cache (fetch lazily, don't hit the network on every invocation)
# ---------------------------------------------------------------------------

def _cache_path() -> Path:
    xdg = os.environ.get("XDG_CONFIG_HOME", "")
    base = Path(xdg) if xdg else Path.home() / ".config"
    return base / "kerf" / "tools_cache.json"


def _cache_key(api_url: str) -> str:
    return hashlib.sha256(api_url.encode("utf-8")).hexdigest()[:16]


def _load_cache(api_url: str) -> Optional[dict]:
    path = _cache_path()
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    entry = data.get(_cache_key(api_url))
    if not entry:
        return None
    if time.time() - entry.get("fetched_at", 0) > _CACHE_TTL_SECONDS:
        return None
    return entry.get("payload")


def _save_cache(api_url: str, payload: dict) -> None:
    path = _cache_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        data: dict = {}
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                data = {}
        data[_cache_key(api_url)] = {"fetched_at": time.time(), "payload": payload}
        path.write_text(json.dumps(data), encoding="utf-8")
    except OSError:
        pass  # cache is best-effort; never fail the command over it


def clear_cache() -> None:
    """Remove the on-disk tools-list cache (used by tests / `--no-cache`)."""
    try:
        _cache_path().unlink()
    except OSError:
        pass


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------

def _extract_detail(raw_body: bytes) -> str:
    """Best-effort pull of the server's error message out of an error body.

    FastAPI's HTTPException bodies look like ``{"detail": "..."}``.
    """
    try:
        parsed = json.loads(raw_body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return raw_body.decode("utf-8", errors="replace").strip()
    if isinstance(parsed, dict) and "detail" in parsed:
        return str(parsed["detail"])
    return json.dumps(parsed)


def _request(
    api_url: str,
    token: str,
    path: str,
    *,
    method: str = "GET",
    body: Optional[dict] = None,
    timeout: float = _DEFAULT_TIMEOUT,
) -> dict:
    url = f"{api_url}{path}"
    data = None
    headers = {"Authorization": f"Bearer {token}"}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"

    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
    except urllib.error.HTTPError as exc:
        raw_body = exc.read() if hasattr(exc, "read") else b""
        detail = _extract_detail(raw_body) or str(exc.reason)
        if exc.code in (401, 403):
            raise ToolsAPIError(
                f"auth failure (HTTP {exc.code}) talking to {url}: {detail}",
                exit_code=2,
            ) from exc
        raise ToolsAPIError(
            f"HTTP {exc.code} from {url}: {detail}", exit_code=3
        ) from exc
    except urllib.error.URLError as exc:
        raise ToolsAPIError(
            f"could not reach {api_url} ({exc.reason})", exit_code=1
        ) from exc
    except (TimeoutError, OSError) as exc:
        raise ToolsAPIError(
            f"timed out / network error contacting {api_url}: {exc}", exit_code=1
        ) from exc

    if not raw:
        return {}
    try:
        return json.loads(raw.decode("utf-8"))
    except ValueError as exc:
        raise ToolsAPIError(
            f"server at {url} returned invalid JSON: {exc}", exit_code=3
        ) from exc


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def fetch_tools(api_url: str, token: str, *, use_cache: bool = True) -> dict:
    """``GET /api/tools`` → ``{"tools": [...], "count": N}``.

    Cached on disk for 5 minutes (per api_url) so repeated invocations of
    `kerf tools list/show/call` and `kerf mcp` startup don't round-trip the
    full 350+-tool registry every time.  Pass ``use_cache=False`` to force a
    fresh fetch.
    """
    if use_cache:
        cached = _load_cache(api_url)
        if cached is not None:
            return cached

    payload = _request(api_url, token, "/api/tools", method="GET")
    _save_cache(api_url, payload)
    return payload


def call_tool(
    api_url: str,
    token: str,
    name: str,
    args: dict,
    *,
    project_id: Optional[str] = None,
) -> dict:
    """``POST /api/tools/call`` → the tool's JSON result (raw, unwrapped)."""
    body: dict[str, Any] = {"tool": name, "args": args or {}}
    if project_id:
        body["project_id"] = project_id
    return _request(api_url, token, "/api/tools/call", method="POST", body=body)
