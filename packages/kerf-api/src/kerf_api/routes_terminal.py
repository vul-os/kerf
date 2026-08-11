"""routes_terminal.py — a real terminal, over a WebSocket, with `kerf` on PATH.

WHAT THIS IS
------------
A PTY running a login shell as the OS user that started the server, bridged to
xterm.js in the browser. Not a restricted console: it runs anything that user
can run. The `kerf` CLI is placed on the session's PATH so an agent driving
Kerf from this terminal — Claude Code, Cursor, a plain script — finds it
without the user configuring anything.

THE SECURITY BOUNDARY, STATED PLAINLY
-------------------------------------
There is no sandbox. A terminal session has the full authority of the server
process: the whole filesystem as that user, the process environment, and
`kerf.toml` — which holds the JWT secret, the database DSN and any provider
API keys. Anyone who can open a terminal here can read all of it.

That is safe by construction in the case Kerf is built for: a node bound to
loopback, running as you, on your own machine. A shell there grants nothing
you did not already have. It is *not* safe on a host reachable by people you
would not hand an SSH key to, and no amount of authentication changes that —
authentication decides who gets the shell, not what the shell can reach.

So the capability is gated on the listen address, not on a role:

  * loopback bind  -> available
  * any other bind -> unavailable unless `[terminal] enabled = true` is set
                      explicitly, and the operator has read what that means

`docs/terminal.md` documents the sandboxing recipes for operators who want to
expose it anyway.

DESIGN NOTES
------------
Sessions outlive their WebSocket. Closing a laptop lid or losing wifi should
not kill a running build, so the PTY is keyed by session id and a reconnecting
client is re-attached to the same process and replayed the scrollback ring
buffer. Several sockets may attach to one session at once — that is what makes
a terminal shareable between two windows.

Wire format:
  * binary frames  — raw PTY bytes, both directions
  * text frames    — JSON control: {"type":"resize","cols":N,"rows":N}

Control is text and data is binary so a resize can never be mistaken for
keystrokes, whatever the payload happens to contain.
"""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import signal
import sys
import uuid
from dataclasses import dataclass, field
from typing import Any, Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from kerf_core.bind import dialable_host, get_bind_host, is_loopback
from kerf_core.config import get_settings

router = APIRouter()

# How much output to keep for replay when a client reconnects. 256 KB is a few
# thousand lines — enough to see what a build printed while the socket was
# down, small enough that idle sessions cost nothing much.
_SCROLLBACK_BYTES = 256 * 1024

# A session with no sockets attached is reaped after this long. It is not a
# safety mechanism (the shell can do anything while it lives); it stops a
# forgotten tab leaving a shell running forever.
_ORPHAN_TTL_SECONDS = 60 * 60


@dataclass
class TerminalCapability:
    """Whether a terminal can be opened here, and if not, why not."""

    available: bool
    reason: str
    platform: str = sys.platform
    sandboxed: bool = False  # always false today; stated so the UI cannot imply otherwise


def capability() -> TerminalCapability:
    settings = get_settings()

    if not _pty_supported():
        return TerminalCapability(
            available=False,
            reason=(
                "This platform has no PTY support available. On Windows the "
                "terminal needs the 'pywinpty' package, which is not installed."
            ),
        )

    host = get_bind_host()
    explicitly_enabled = bool(getattr(settings, "terminal_enabled", False))

    if is_loopback(host):
        return TerminalCapability(
            available=True,
            reason="Bound to loopback — a shell here has the authority you already have.",
        )

    if explicitly_enabled:
        return TerminalCapability(
            available=True,
            reason=(
                "Enabled explicitly on a non-loopback bind. Every user who can "
                "reach this server can run commands as the server's OS user."
            ),
        )

    return TerminalCapability(
        available=False,
        reason=(
            f"This server is bound to {host}, not loopback. A terminal would give "
            "anyone who can reach it a shell as the server's OS user, with access "
            "to kerf.toml and every project on disk. Set [terminal] enabled = true "
            "to allow it anyway — see docs/terminal.md for how to sandbox it first."
        ),
    )


def _pty_supported() -> bool:
    if sys.platform == "win32":
        try:
            import winpty  # noqa: F401  (pywinpty)
            return True
        except Exception:
            return False
    try:
        import pty  # noqa: F401
        return True
    except Exception:
        return False


def _shell_command() -> list[str]:
    """The shell to run, as a login shell so the user's profile is sourced."""
    if sys.platform == "win32":
        return [os.environ.get("COMSPEC") or "cmd.exe"]
    shell = os.environ.get("SHELL") or shutil.which("bash") or "/bin/sh"
    return [shell, "-l"]


def _session_env() -> dict[str, str]:
    """The child's environment, with `kerf` reachable.

    This is the "CLI already integrated" part and it is the whole reason the
    terminal is worth having. In a desktop build the server is a frozen
    one-file binary: `kerf` is not on the user's PATH and may not exist as a
    separate executable at all. In a pip install it lives in the same
    bin/Scripts directory as the interpreter running us, which is on PATH only
    if the user activated that environment.

    Prepending the interpreter's script directory covers both: whatever
    console-script directory this server was launched from comes first, so
    `kerf` resolves to the same install that is serving this page.
    """
    env = dict(os.environ)

    script_dirs: list[str] = []

    # The directory holding this interpreter's console scripts.
    exe_dir = os.path.dirname(os.path.abspath(sys.executable))
    if exe_dir:
        script_dirs.append(exe_dir)
        # Unix venvs put scripts in bin/ beside the interpreter; Windows uses
        # Scripts/ beside python.exe.
        sibling = os.path.join(os.path.dirname(exe_dir), "Scripts" if sys.platform == "win32" else "bin")
        if os.path.isdir(sibling):
            script_dirs.append(sibling)

    # An already-resolvable kerf wins over guesswork.
    found = shutil.which("kerf")
    if found:
        script_dirs.insert(0, os.path.dirname(found))

    existing = env.get("PATH", "")
    ordered = [d for d in dict.fromkeys(script_dirs) if d and os.path.isdir(d)]
    env["PATH"] = os.pathsep.join([*ordered, existing]) if existing else os.pathsep.join(ordered)

    # Marks the session for anything that wants to know it is inside Kerf —
    # a shell prompt, a script, an agent deciding whether `kerf` is available.
    env["KERF_TERMINAL"] = "1"
    env["TERM"] = env.get("TERM") or "xterm-256color"

    # Point the CLI at the node serving this terminal. Without it `kerf tools
    # list` defaults to the hosted endpoint and asks for a token, which is a
    # confusing thing to meet in a terminal that is running *inside* the node
    # you meant. Set only when the operator has not already chosen one.
    if not env.get("KERF_API_URL"):
        settings = get_settings()
        port = str(getattr(settings, "port", "") or "8080")
        # dialable_host() never returns a wildcard: that is a bind instruction,
        # not an address a client can connect to.
        env["KERF_API_URL"] = f"http://{dialable_host()}:{port}"

    return env


class _RingBuffer:
    """Fixed-size tail of the session's output, replayed on reconnect."""

    def __init__(self, limit: int = _SCROLLBACK_BYTES) -> None:
        self._limit = limit
        self._buf = bytearray()

    def append(self, data: bytes) -> None:
        self._buf.extend(data)
        if len(self._buf) > self._limit:
            del self._buf[: len(self._buf) - self._limit]

    def snapshot(self) -> bytes:
        return bytes(self._buf)


@dataclass
class _Session:
    """One PTY and every socket currently watching it."""

    id: str
    pid: int
    fd: int
    scrollback: _RingBuffer = field(default_factory=_RingBuffer)
    sockets: set[WebSocket] = field(default_factory=set)
    closed: bool = False
    _reaper: Optional[asyncio.TimerHandle] = None


_sessions: dict[str, _Session] = {}


def _spawn(cols: int, rows: int) -> _Session:
    """Fork a PTY running the login shell. POSIX only; Windows goes via winpty."""
    import fcntl
    import pty
    import struct
    import termios

    pid, fd = pty.fork()
    if pid == 0:  # child
        try:
            os.execvpe(_shell_command()[0], _shell_command(), _session_env())
        except Exception:  # pragma: no cover — the child cannot report anything useful
            os._exit(127)

    # Set the window size before the shell draws its first prompt, otherwise it
    # wraps at 80 columns until the first resize event arrives.
    try:
        fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
    except Exception:
        pass

    os.set_blocking(fd, False)
    return _Session(id=uuid.uuid4().hex, pid=pid, fd=fd)


def _resize(session: _Session, cols: int, rows: int) -> None:
    import fcntl
    import struct
    import termios

    try:
        fcntl.ioctl(session.fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
    except Exception:
        pass


def _close(session: _Session) -> None:
    if session.closed:
        return
    session.closed = True
    _sessions.pop(session.id, None)
    try:
        os.kill(session.pid, signal.SIGHUP)
    except Exception:
        pass
    try:
        os.close(session.fd)
    except Exception:
        pass


@router.get("/terminal/capability")
async def terminal_capability() -> dict[str, Any]:
    """GET /api/terminal/capability — may a terminal be opened, and why not.

    The UI asks this before offering a terminal at all, so a server where the
    answer is no never renders a control that would fail. `reason` is written
    to be shown to a person verbatim.
    """
    cap = capability()
    return {
        "available": cap.available,
        "reason": cap.reason,
        "platform": cap.platform,
        "sandboxed": cap.sandboxed,
        "sessions": sorted(_sessions.keys()),
    }


@router.websocket("/terminal/session")
async def terminal_session(websocket: WebSocket) -> None:
    """WS /api/terminal/session — bridge a PTY to the browser.

    Query params: `session` to re-attach to an existing one, `cols`/`rows` for
    the initial window size.
    """
    cap = capability()
    if not cap.available:
        # 1008 = policy violation. Closing with the reason means the client can
        # show why rather than a bare "connection failed".
        await websocket.close(code=1008, reason=cap.reason[:120])
        return

    await websocket.accept()

    cols = _int_param(websocket, "cols", 80)
    rows = _int_param(websocket, "rows", 24)

    requested = websocket.query_params.get("session")
    session = _sessions.get(requested) if requested else None
    reattaching = session is not None

    if session is None:
        try:
            session = _spawn(cols, rows)
        except Exception as exc:
            await websocket.close(code=1011, reason=f"could not start a shell: {exc}"[:120])
            return
        _sessions[session.id] = session

    session.sockets.add(websocket)
    if session._reaper is not None:
        session._reaper.cancel()
        session._reaper = None

    await websocket.send_text(json.dumps({
        "type": "session",
        "id": session.id,
        "reattached": reattaching,
    }))
    if reattaching:
        # Replay what was printed while nothing was watching.
        snapshot = session.scrollback.snapshot()
        if snapshot:
            await websocket.send_bytes(snapshot)
        _resize(session, cols, rows)

    reader = asyncio.create_task(_pump_pty_to_socket(session))
    try:
        await _pump_socket_to_pty(websocket, session)
    except WebSocketDisconnect:
        pass
    finally:
        session.sockets.discard(websocket)
        if not session.sockets and not session.closed:
            # Keep the shell alive for a reconnect, but not forever.
            loop = asyncio.get_running_loop()
            session._reaper = loop.call_later(_ORPHAN_TTL_SECONDS, _close, session)
        if session.closed:
            reader.cancel()


def _int_param(websocket: WebSocket, name: str, default: int) -> int:
    raw = websocket.query_params.get(name)
    try:
        value = int(raw) if raw is not None else default
    except (TypeError, ValueError):
        return default
    # A shell asked for zero columns divides by zero somewhere deep in ncurses.
    return max(1, min(value, 1000))


async def _pump_socket_to_pty(websocket: WebSocket, session: _Session) -> None:
    """Browser -> PTY. Binary frames are keystrokes; text frames are control."""
    while True:
        message = await websocket.receive()
        if message.get("type") == "websocket.disconnect":
            raise WebSocketDisconnect(message.get("code", 1000))

        data = message.get("bytes")
        if data is not None:
            try:
                os.write(session.fd, data)
            except OSError:
                _close(session)
                return
            continue

        text = message.get("text")
        if not text:
            continue
        try:
            control = json.loads(text)
        except ValueError:
            continue  # not control; nothing sane to do with it
        if control.get("type") == "resize":
            _resize(session, _clamp(control.get("cols"), 80), _clamp(control.get("rows"), 24))


def _clamp(value: Any, default: int) -> int:
    try:
        return max(1, min(int(value), 1000))
    except (TypeError, ValueError):
        return default


async def _pump_pty_to_socket(session: _Session) -> None:
    """PTY -> every attached browser, plus the scrollback ring."""
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue[bytes] = asyncio.Queue()

    def _on_readable() -> None:
        try:
            chunk = os.read(session.fd, 65536)
        except BlockingIOError:
            return
        except OSError:
            chunk = b""
        if not chunk:  # shell exited
            loop.remove_reader(session.fd)
            queue.put_nowait(b"")
            return
        queue.put_nowait(chunk)

    try:
        loop.add_reader(session.fd, _on_readable)
    except Exception:
        return

    try:
        while True:
            chunk = await queue.get()
            if not chunk:
                _close(session)
                for socket in list(session.sockets):
                    try:
                        await socket.close(code=1000, reason="shell exited")
                    except Exception:
                        pass
                return
            session.scrollback.append(chunk)
            for socket in list(session.sockets):
                try:
                    await socket.send_bytes(chunk)
                except Exception:
                    session.sockets.discard(socket)
    finally:
        try:
            loop.remove_reader(session.fd)
        except Exception:
            pass
