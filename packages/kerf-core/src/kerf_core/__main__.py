"""CLI entry-point — boots the Kerf FastAPI app with uvicorn.

Usage::

    python -m kerf_core [--config kerf.toml] [--host 0.0.0.0] [--port 8080] [--reload]
    kerf-server [--config kerf.toml] [--host 0.0.0.0] [--port 8080] [--reload]
"""
from __future__ import annotations

import argparse
import os
import sys


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="kerf-server",
        description="Boot the Kerf backend (FastAPI + plugin loader).",
    )
    parser.add_argument("--config", default=os.environ.get("KERF_CONFIG", ""))
    parser.add_argument("--host", default=os.environ.get("KERF_HOST", "0.0.0.0"))
    # No default here (unlike --host/--config above): we need to be able to
    # tell "not given on the CLI or via KERF_PORT" apart from "given" so
    # main() can fall through to kerf.toml's [server].port. Resolved below.
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument("--reload", action="store_true", default=False)
    parser.add_argument(
        "--reload-dir",
        action="append",
        default=None,
        help="Directory to watch when --reload is set (repeatable). Defaults to 'packages'.",
    )
    parser.add_argument("--workers", type=int, default=1)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = _parse_args(argv)

    try:
        import uvicorn
    except ImportError:
        print("uvicorn is required. Install with: pip install uvicorn[standard]", file=sys.stderr)
        sys.exit(1)

    if args.config:
        os.environ["KERF_CONFIG"] = args.config

    # Bind port resolution: --port > KERF_PORT env > kerf.toml [server].port
    # > 8080. uvicorn's port used to come from --port/KERF_PORT alone,
    # bypassing Settings/kerf.toml entirely — a value set in
    # [server].port there had no effect on what the server actually bound
    # to. Settings.load() applies its own env-beats-toml-beats-default
    # precedence for the `port` field (so a plain PORT env var still wins
    # here too); this only fills the "neither flag nor KERF_PORT given"
    # gap so kerf.toml's port is honoured end to end.
    port = args.port
    if port is None:
        kerf_port = os.environ.get("KERF_PORT", "")
        if kerf_port:
            port = int(kerf_port)
        else:
            from kerf_core.config import Settings  # noqa: PLC0415 — deferred: keep argparse import-light

            port = int(Settings.load(args.config).port)

    reload_kwargs: dict = {}
    if args.reload:
        reload_kwargs["reload_dirs"] = args.reload_dir or ["packages"]
        reload_kwargs["reload_excludes"] = [
            ".claude/*",
            "node_modules/*",
            ".git/*",
            "dist/*",
            "public/*",
        ]

    # Record it before serving: the terminal and first-run setup gates decide
    # what they allow from the *actual* bind address, and this is the only
    # place that knows it.
    from kerf_core.bind import set_bind_host  # noqa: PLC0415

    set_bind_host(args.host)

    uvicorn.run(
        "kerf_core.app:create_app",
        host=args.host,
        port=port,
        reload=args.reload,
        workers=args.workers if not args.reload else 1,
        factory=True,
        log_level="info",
        **reload_kwargs,
    )


if __name__ == "__main__":
    main()
