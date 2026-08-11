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
from kerf_core import bind  # noqa: E402

_POSIX_ONLY = pytest.mark.skipif(
    sys.platform == "win32", reason="POSIX pty; Windows goes through pywinpty")


@pytest.fixture(autouse=True)
def loopback_bind(monkeypatch):
    """Most tests here are about a terminal that is allowed to exist, and one
    is only allowed on a loopback bind. A TestClient binds nothing at all, so
    the address has to be stated; the gate tests override it."""
    monkeypatch.setattr(bind, "_bind_host", "127.0.0.1")


@pytest.fixture()
def client() -> Generator[TestClient, None, None]:
    app = FastAPI()
    app.include_router(routes_terminal.router, prefix="/api")
    with TestClient(app) as c:
        yield c


# ── the listen-address gate ─────────────────────────────────────────────────

@pytest.mark.parametrize("host", ["127.0.0.1", "localhost", "::1", "127.0.1.1"])
def test_loopback_binds_are_loopback(host):
    assert bind.is_loopback(host) is True


@pytest.mark.parametrize("host", ["0.0.0.0", "::", "", "*", "192.168.1.10", "example.com"])
def test_everything_else_is_not(host):
    """The empty string and '*' mean 'all interfaces' where this value comes
    from, so treating them as loopback would open a shell to the network."""
    assert bind.is_loopback(host) is False


def test_the_gate_reads_the_real_bind_address(monkeypatch):
    """It used to read `settings.host`, a field Settings has never had, and
    fall back to "127.0.0.1" — so a server started with the shipped default of
    --host 0.0.0.0 offered a shell to the whole network while reporting itself
    as loopback-bound. The bind address now comes from the process that binds
    it."""
    monkeypatch.setattr(bind, "_bind_host", "0.0.0.0")
    monkeypatch.setattr(routes_terminal, "get_settings",
                        lambda: _settings(terminal_enabled=False))

    assert routes_terminal.capability().available is False


def test_an_unrecorded_bind_is_treated_as_public(monkeypatch):
    """Nothing recorded a bind address, so nothing knows the server is only
    reachable locally. Assuming it is would hand out shells to anything that
    embeds Kerf without going through our entry points."""
    monkeypatch.setattr(bind, "_bind_host", None)
    monkeypatch.delenv("KERF_HOST", raising=False)
    monkeypatch.setattr(routes_terminal, "get_settings",
                        lambda: _settings(terminal_enabled=False))

    assert routes_terminal.capability().available is False


def test_a_public_bind_refuses_and_says_why(monkeypatch):
    monkeypatch.setattr(bind, "_bind_host", "0.0.0.0")
    monkeypatch.setattr(routes_terminal, "get_settings",
                        lambda: _settings(terminal_enabled=False))

    cap = routes_terminal.capability()

    assert cap.available is False
    # The reason is shown to a person verbatim, so it has to name the specific
    # exposure rather than say "not allowed".
    assert "kerf.toml" in cap.reason
    assert "terminal" in cap.reason.lower()


def test_a_public_bind_can_be_opted_into(monkeypatch):
    monkeypatch.setattr(bind, "_bind_host", "0.0.0.0")
    monkeypatch.setattr(routes_terminal, "get_settings",
                        lambda: _settings(terminal_enabled=True))

    cap = routes_terminal.capability()

    assert cap.available is True
    # Opting in must not read as a blessing — the consequence is restated.
    assert "run commands as the server" in cap.reason


def test_loopback_needs_no_opt_in(monkeypatch):
    monkeypatch.setattr(bind, "_bind_host", "127.0.0.1")
    monkeypatch.setattr(routes_terminal, "get_settings",
                        lambda: _settings(terminal_enabled=False))
    assert routes_terminal.capability().available is True


def test_capability_never_claims_to_be_sandboxed(client):
    """There is no sandbox. The UI reads this field, so it must not be able to
    imply otherwise — if a sandbox is ever added, this test is where the claim
    starts."""
    body = client.get("/api/terminal/capability").json()
    assert body["sandboxed"] is False


def test_a_refused_socket_closes_with_the_reason(monkeypatch):
    monkeypatch.setattr(bind, "_bind_host", "0.0.0.0")
    monkeypatch.setattr(routes_terminal, "get_settings",
                        lambda: _settings(terminal_enabled=False))
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
def test_a_reattached_session_can_still_be_typed_into(client):
    """Replaying the scrollback is half of re-attaching. The other half is that
    the new socket still drives the shell.

    The existing reattach test only asserted the replay, and the replay is sent
    straight from the ring buffer — it arrives whether or not the live PTY is
    still wired to anything. So a reattached terminal could show its history,
    report itself connected, and be deaf, which is exactly what the browser
    suite kept catching.
    """
    with client.websocket_connect("/api/terminal/session") as ws:
        session_id = json.loads(ws.receive_text())["id"]
        ws.send_bytes(b"echo first-command\n")
        for _ in range(80):
            if b"first-command" in (ws.receive().get("bytes") or b""):
                break

    with client.websocket_connect(f"/api/terminal/session?session={session_id}") as ws2:
        assert json.loads(ws2.receive_text())["reattached"] is True
        ws2.receive()  # the replayed scrollback

        ws2.send_bytes(b"echo second-command\n")
        seen = b""
        for _ in range(80):
            chunk = ws2.receive().get("bytes")
            if chunk:
                seen += chunk
                if seen.count(b"second-command") >= 2:  # echo, then output
                    break
        assert b"second-command" in seen, (
            "the reattached socket reached no shell — input went nowhere, or "
            "the PTY's output is no longer routed to this connection"
        )


@_POSIX_ONLY
def test_an_unknown_session_id_starts_a_fresh_one(client):
    """Rather than erroring: a stale id in a reloaded tab is ordinary."""
    with client.websocket_connect("/api/terminal/session?session=does-not-exist") as ws:
        hello = json.loads(ws.receive_text())
        assert hello["reattached"] is False
        assert hello["id"] != "does-not-exist"


def _settings(**overrides):
    class _S:
        # Deliberately no `host`: Settings has never had one, and a stub that
        # invents it is how the gate came to trust a field that is not there.
        terminal_enabled = False
    s = _S()
    for key, value in overrides.items():
        setattr(s, key, value)
    return s
