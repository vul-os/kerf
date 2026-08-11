"""The address this process is actually listening on.

Two gates depend on it — whether a terminal may be opened, and whether an
unclaimed node may be claimed through the browser — and both were asking a
``Settings`` object for a ``host`` field that does not exist on it, then
falling back to ``"127.0.0.1"``.

The server's own default is ``--host 0.0.0.0``. So on a default install both
gates believed the node was loopback-only while it was in fact answering every
interface: the terminal offered a shell to anyone who could reach the port, and
an unclaimed node could be claimed by whoever got there first. The gates were
written to be conservative and were, through that one fallback, the opposite.

The bind address is known in exactly one place — the process that calls
``uvicorn.run`` — so it is recorded there and read from here.

WHEN NOTHING RECORDED IT, THE ANSWER IS "NOT LOOPBACK"
-----------------------------------------------------
An embedded app, a test client, a process manager we do not control: any of
these can serve Kerf without going through our entry points. Guessing
"loopback" in that case is guessing in the direction that opens a shell to
strangers, so the guess goes the other way. A loopback-bound server that has
not told us so loses its terminal — visible, and fixed with ``KERF_HOST``. The
inverse failure is not visible at all.
"""
from __future__ import annotations

import os
from typing import Optional

# Set by whoever calls uvicorn. None means nobody did.
_bind_host: Optional[str] = None


def set_bind_host(host: str) -> None:
    """Record the address the server is binding to. Call before serving."""
    global _bind_host
    _bind_host = str(host or "")


def get_bind_host() -> str:
    """The bind address, as the server understands it.

    Falls back to ``KERF_HOST`` (the same variable the entry points read) and
    then to a wildcard, which is treated as not-loopback everywhere.
    """
    if _bind_host is not None:
        return _bind_host
    return os.environ.get("KERF_HOST", "") or "0.0.0.0"


def is_loopback(host: str) -> bool:
    """Whether *host* is an address only this machine can reach.

    The empty string and ``*`` mean "every interface" in the places this value
    comes from, so they are emphatically not loopback. The whole 127/8 block
    is, which matters because Debian puts the hostname on 127.0.1.1.
    """
    host = (host or "").strip().lower()
    if not host or host in ("*", "0.0.0.0", "::", "[::]"):
        return False
    return host in ("localhost", "127.0.0.1", "::1", "[::1]") or host.startswith("127.")


def is_loopback_bind() -> bool:
    """Whether this server can only be reached from the machine it runs on."""
    return is_loopback(get_bind_host())


def dialable_host() -> str:
    """An address a client on this machine can actually connect to.

    A wildcard bind is a listening instruction, not a destination: handing
    ``0.0.0.0`` to an HTTP client is a bug on some stacks and a surprise on the
    rest. Loopback is always reachable when the server is listening on it or on
    a wildcard, which covers every case this is used for.
    """
    host = get_bind_host()
    return host if is_loopback(host) else "127.0.0.1"
