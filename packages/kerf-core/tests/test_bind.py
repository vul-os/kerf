"""The recorded bind address, and why it fails closed.

Two things read this — whether a terminal may be opened, and whether an
unclaimed node may be claimed from a browser — and both answer "no" when the
server is reachable from the network. They were reading `settings.host`, a
field `Settings` does not define, and falling back to "127.0.0.1"; the shipped
default is `--host 0.0.0.0`. So the default install reported itself as
loopback-only while listening on every interface, and both gates opened.

What follows pins the two halves of the fix: the address comes from whoever
binds it, and an unrecorded address is assumed public.
"""
from __future__ import annotations

import pytest

from kerf_core import bind


@pytest.fixture(autouse=True)
def clean_state(monkeypatch):
    monkeypatch.setattr(bind, "_bind_host", None)
    monkeypatch.delenv("KERF_HOST", raising=False)


@pytest.mark.parametrize("host", ["127.0.0.1", "localhost", "::1", "[::1]", "127.0.1.1", "LOCALHOST"])
def test_loopback_addresses(host):
    assert bind.is_loopback(host) is True


@pytest.mark.parametrize("host", ["0.0.0.0", "::", "[::]", "*", "", "  ", "192.168.1.10", "kerf.example"])
def test_everything_reachable_from_elsewhere(host):
    """'', '*' and the wildcards mean "every interface" in the places this
    value comes from. Reading them as loopback is the bug this module exists
    to prevent."""
    assert bind.is_loopback(host) is False


def test_the_recorded_address_is_what_is_read_back():
    bind.set_bind_host("127.0.0.1")
    assert bind.get_bind_host() == "127.0.0.1"
    assert bind.is_loopback_bind() is True


def test_nothing_recorded_means_public():
    """An embedded host, a WSGI container, a test client: none of them call
    set_bind_host. Assuming loopback there hands a shell to whoever can reach
    the process."""
    assert bind.get_bind_host() == "0.0.0.0"
    assert bind.is_loopback_bind() is False


def test_kerf_host_is_honoured_when_nothing_recorded(monkeypatch):
    """The entry points already default --host from KERF_HOST, so a deployment
    that sets only the variable gets the same answer here."""
    monkeypatch.setenv("KERF_HOST", "127.0.0.1")
    assert bind.is_loopback_bind() is True


def test_a_recorded_address_beats_the_variable(monkeypatch):
    """`--host 0.0.0.0 KERF_HOST=127.0.0.1` is a real way to get this wrong.
    What the process actually bound wins over what an environment suggests."""
    monkeypatch.setenv("KERF_HOST", "127.0.0.1")
    bind.set_bind_host("0.0.0.0")
    assert bind.is_loopback_bind() is False


def test_an_empty_recorded_address_is_still_a_recording(monkeypatch):
    """uvicorn treats "" as every interface. It must not fall through to the
    environment and be reinterpreted as loopback."""
    monkeypatch.setenv("KERF_HOST", "127.0.0.1")
    bind.set_bind_host("")
    assert bind.is_loopback_bind() is False


@pytest.mark.parametrize("host,expected", [
    ("0.0.0.0", "127.0.0.1"),
    ("::", "127.0.0.1"),
    ("192.168.1.10", "127.0.0.1"),
    ("127.0.0.1", "127.0.0.1"),
    ("localhost", "localhost"),
])
def test_a_dialable_host_is_never_a_wildcard(host, expected):
    """0.0.0.0 is an instruction to listen, not an address to connect to. It
    is handed to an HTTP client when the terminal points the CLI at its own
    node, and some stacks refuse it outright."""
    bind.set_bind_host(host)
    assert bind.dialable_host() == expected


# ── every entry point has to record it ──────────────────────────────────────

def test_every_uvicorn_entry_point_records_its_bind_address():
    """The fail-closed default only works if the processes that *do* know their
    bind address say so.

    kerf-desktop is why this test exists: it builds its own uvicorn.Config with
    host="127.0.0.1" and, for one commit, did not call set_bind_host — which
    would have refused a terminal and first-run setup on the single most
    loopback-only deployment Kerf has. A source check rather than a runtime one
    because these are process entry points; running them means starting servers.
    """
    import pathlib as _pathlib

    packages = _pathlib.Path(__file__).resolve().parents[2]
    entry_points = [
        packages / "kerf-core" / "src" / "kerf_core" / "__main__.py",
        packages / "kerf-cli" / "src" / "kerf_cli" / "serve.py",
        packages / "kerf-desktop" / "src" / "kerf_desktop" / "main.py",
    ]

    for path in entry_points:
        if not path.exists():
            continue  # a package not installed in this tier
        source = path.read_text()
        if "uvicorn.run(" not in source and "uvicorn.Config(" not in source:
            continue
        assert "set_bind_host(" in source, (
            f"{path.name} starts uvicorn without recording its bind address. "
            f"kerf_core.bind assumes the worst when nobody says, so this "
            f"silently disables the terminal and first-run setup."
        )


def test_the_entry_point_list_is_not_empty():
    """A guard whose list of things to guard went stale reads exactly like one
    that passes."""
    import pathlib as _pathlib

    packages = _pathlib.Path(__file__).resolve().parents[2]
    found = [
        p for p in [
            packages / "kerf-core" / "src" / "kerf_core" / "__main__.py",
            packages / "kerf-cli" / "src" / "kerf_cli" / "serve.py",
            packages / "kerf-desktop" / "src" / "kerf_desktop" / "main.py",
        ] if p.exists()
    ]
    assert len(found) >= 2, f"expected to find the server entry points, found {found}"
