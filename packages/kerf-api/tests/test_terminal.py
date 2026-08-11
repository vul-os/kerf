"""The terminal: what it refuses, and that `kerf` is reachable inside it.

The terminal is a shell with the server process's full authority — the
filesystem as that user, the environment, and kerf.toml with its secrets. It is
gated on the *listen address* rather than on a role, because authentication
decides who gets the shell and not what the shell can reach, and a loopback
bind is the one case where a shell grants nothing the user did not already
have.

Most of what is worth testing is therefore the refusal, and that the refusal
explains itself: a capability that silently becomes unavailable produces a bug
report, and one that silently becomes *available* produces something worse.
"""
from __future__ import annotations

import json
import pathlib
import sys
from typing import Generator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

_HERE = pathlib.Path(__file__).parent
_PACKAGES_ROOT = _HERE.parent.parent
for _entry in _PACKAGES_ROOT.iterdir():
    if not _entry.name.startswith("kerf-"):
        continue
    _src = _entry / "src"
    if _src.is_dir() and str(_src) not in sys.path:
        sys.path.insert(0, str(_src))

from kerf_api import routes_terminal  # noqa: E402

_POSIX_ONLY = pytest.mark.skipif(
    sys.platform == "win32", reason="POSIX pty; Windows goes through pywinpty")


@pytest.fixture()
def client() -> Generator[TestClient, None, None]:
    app = FastAPI()
    app.include_router(routes_terminal.router, prefix="/api")
    with TestClient(app) as c:
        yield c


# ── the listen-address gate ─────────────────────────────────────────────────

@pytest.mark.parametrize("host", ["127.0.0.1", "localhost", "::1", "127.0.1.1"])
def test_loopback_binds_are_loopback(host):
    assert routes_terminal._is_loopback(host) is True


@pytest.mark.parametrize("host", ["0.0.0.0", "::", "", "*", "192.168.1.10", "example.com"])
def test_everything_else_is_not(host):
    """The empty string and '*' mean 'all interfaces' where this value comes
    from, so treating them as loopback would open a shell to the network."""
    assert routes_terminal._is_loopback(host) is False


def test_a_public_bind_refuses_and_says_why(monkeypatch):
    monkeypatch.setattr(routes_terminal, "get_settings",
                        lambda: _settings(host="0.0.0.0", terminal_enabled=False))

    cap = routes_terminal.capability()

    assert cap.available is False
    # The reason is shown to a person verbatim, so it has to name the specific
    # exposure rather than say "not allowed".
    assert "kerf.toml" in cap.reason
    assert "terminal" in cap.reason.lower()


def test_a_public_bind_can_be_opted_into(monkeypatch):
    monkeypatch.setattr(routes_terminal, "get_settings",
                        lambda: _settings(host="0.0.0.0", terminal_enabled=True))

    cap = routes_terminal.capability()

    assert cap.available is True
    # Opting in must not read as a blessing — the consequence is restated.
    assert "run commands as the server" in cap.reason


def test_loopback_needs_no_opt_in(monkeypatch):
    monkeypatch.setattr(routes_terminal, "get_settings",
                        lambda: _settings(host="127.0.0.1", terminal_enabled=False))
    assert routes_terminal.capability().available is True


def test_capability_never_claims_to_be_sandboxed(client):
    """There is no sandbox. The UI reads this field, so it must not be able to
    imply otherwise — if a sandbox is ever added, this test is where the claim
    starts."""
    body = client.get("/api/terminal/capability").json()
    assert body["sandboxed"] is False


def test_a_refused_socket_closes_with_the_reason(monkeypatch):
    monkeypatch.setattr(routes_terminal, "get_settings",
                        lambda: _settings(host="0.0.0.0", terminal_enabled=False))
    app = FastAPI()
    app.include_router(routes_terminal.router, prefix="/api")

    from starlette.websockets import WebSocketDisconnect
    with TestClient(app) as c:
        with pytest.raises(WebSocketDisconnect) as excinfo:
            with c.websocket_connect("/api/terminal/session") as ws:
                ws.receive_text()
    # 1008 is "policy violation" — a client can distinguish this from a crash.
    assert excinfo.value.code == 1008


# ── the session's environment ───────────────────────────────────────────────

def test_kerf_is_on_the_session_path():
    """The point of the feature. A desktop build's server is a frozen binary and
    a pip install may live in an unactivated venv; in neither case is `kerf` on
    the user's PATH by default."""
    import os
    import shutil

    env = routes_terminal._session_env()
    entries = env["PATH"].split(os.pathsep)

    found = shutil.which("kerf")
    if found:
        assert os.path.dirname(found) in entries
    # The interpreter's own script directory is always offered, which is where
    # a venv install puts the console script.
    assert os.path.dirname(os.path.abspath(sys.executable)) in entries


def test_the_cli_is_pointed_at_this_node():
    """Without this, `kerf tools list` inside the terminal defaults to the
    hosted endpoint and asks for a token — a confusing thing to meet in a
    terminal running inside the node you meant."""
    env = routes_terminal._session_env()
    assert env["KERF_API_URL"].startswith("http://")
    # Never a wildcard: that is a bind address, not something a client dials.
    assert "0.0.0.0" not in env["KERF_API_URL"]


def test_an_operator_chosen_api_url_wins(monkeypatch):
    monkeypatch.setenv("KERF_API_URL", "http://elsewhere.internal:9000")
    assert routes_terminal._session_env()["KERF_API_URL"] == "http://elsewhere.internal:9000"


def test_the_session_is_marked_as_kerfs():
    """Anything inside — a prompt, a script, an agent deciding whether `kerf`
    is available — can detect the context without probing."""
    assert routes_terminal._session_env()["KERF_TERMINAL"] == "1"


def test_the_existing_path_is_kept_not_replaced():
    import os
    env = routes_terminal._session_env()
    for entry in os.environ.get("PATH", "").split(os.pathsep):
        if entry:
            assert entry in env["PATH"].split(os.pathsep)


def test_a_terminal_is_provided():
    """Without TERM a shell assumes a dumb terminal and emits no colour or
    cursor control, which xterm.js renders as a wall of plain text."""
    assert "xterm" in routes_terminal._session_env()["TERM"]


# ── the shell ───────────────────────────────────────────────────────────────

@_POSIX_ONLY
def test_the_shell_is_a_login_shell():
    """-l so the user's profile is sourced: their aliases, their PATH additions,
    their prompt. A terminal that is not the user's terminal is a toy."""
    assert routes_terminal._shell_command()[-1] == "-l"


# ── window size ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("value,expected", [
    ("100", 100), ("0", 1), ("-5", 1), ("99999", 1000), ("abc", 24), (None, 24),
])
def test_window_size_is_clamped(value, expected):
    """A shell handed zero columns divides by zero deep inside ncurses, and a
    huge one allocates accordingly."""
    assert routes_terminal._clamp(value, 24) == expected


# ── the live session ────────────────────────────────────────────────────────

@_POSIX_ONLY
def test_a_session_starts_and_echoes(client):
    with client.websocket_connect("/api/terminal/session?cols=100&rows=30") as ws:
        hello = json.loads(ws.receive_text())
        assert hello["type"] == "session"
        assert hello["reattached"] is False
        assert hello["id"]

        ws.send_bytes(b"echo kerf-terminal-probe\n")
        seen = b""
        for _ in range(80):
            message = ws.receive()
            chunk = message.get("bytes")
            if chunk:
                seen += chunk
                # Skip the echo of the command itself; wait for the output.
                if seen.count(b"kerf-terminal-probe") >= 2:
                    break
        assert b"kerf-terminal-probe" in seen


@_POSIX_ONLY
def test_reattaching_replays_the_scrollback(client):
    """A dropped socket must not kill a running build. The session outlives the
    connection and the client is caught up on what it missed."""
    with client.websocket_connect("/api/terminal/session") as ws:
        session_id = json.loads(ws.receive_text())["id"]
        ws.send_bytes(b"echo remembered-across-reconnects\n")
        for _ in range(80):
            if b"remembered-across-reconnects" in (ws.receive().get("bytes") or b""):
                break

    with client.websocket_connect(f"/api/terminal/session?session={session_id}") as ws2:
        hello = json.loads(ws2.receive_text())
        assert hello["reattached"] is True
        assert hello["id"] == session_id
        replay = ws2.receive().get("bytes") or b""
        assert b"remembered-across-reconnects" in replay


@_POSIX_ONLY
def test_an_unknown_session_id_starts_a_fresh_one(client):
    """Rather than erroring: a stale id in a reloaded tab is ordinary."""
    with client.websocket_connect("/api/terminal/session?session=does-not-exist") as ws:
        hello = json.loads(ws.receive_text())
        assert hello["reattached"] is False
        assert hello["id"] != "does-not-exist"


def _settings(**overrides):
    class _S:
        host = "127.0.0.1"
        terminal_enabled = False
    s = _S()
    for key, value in overrides.items():
        setattr(s, key, value)
    return s
