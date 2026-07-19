"""Unit tests for kerf-cli.

These tests NEVER touch the real database and NEVER run migrations.
They test:
  - CLI argument parsing (--help, subcommand dispatch)
  - fail-fast error path: missing DATABASE_URL
  - fail-fast error path: unreachable DATABASE_URL
  - credentials save/load round-trip
"""

from __future__ import annotations

import os
import sys
import textwrap
from pathlib import Path
from unittest.mock import AsyncMock, patch, MagicMock

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run_main(argv: list[str]) -> tuple[int, str, str]:
    """Invoke main() and return (exit_code, stdout_text, stderr_text)."""
    import io
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


# ---------------------------------------------------------------------------
# Parser / --help smoke tests
# ---------------------------------------------------------------------------

class TestParserSmoke:
    def test_help_exits_zero(self):
        with pytest.raises(SystemExit) as exc_info:
            from kerf_cli.main import _build_parser
            _build_parser().parse_args(["--help"])
        assert exc_info.value.code == 0

    def test_login_help_exits_zero(self):
        with pytest.raises(SystemExit) as exc_info:
            from kerf_cli.main import _build_parser
            _build_parser().parse_args(["login", "--help"])
        assert exc_info.value.code == 0

    def test_serve_help_exits_zero(self):
        with pytest.raises(SystemExit) as exc_info:
            from kerf_cli.main import _build_parser
            _build_parser().parse_args(["serve", "--help"])
        assert exc_info.value.code == 0

    def test_version_exits_zero(self):
        with pytest.raises(SystemExit) as exc_info:
            from kerf_cli.main import _build_parser
            _build_parser().parse_args(["--version"])
        assert exc_info.value.code == 0

    def test_no_subcommand_exits_nonzero(self):
        with pytest.raises(SystemExit) as exc_info:
            from kerf_cli.main import _build_parser
            _build_parser().parse_args([])
        assert exc_info.value.code != 0

    def test_serve_defaults(self):
        from kerf_cli.main import _build_parser
        args = _build_parser().parse_args(["serve"])
        assert args.host == "0.0.0.0"
        assert args.port == 8080
        assert args.reload is False
        assert args.workers == 1
        assert args.skip_migrate is False

    def test_serve_custom_flags(self):
        from kerf_cli.main import _build_parser
        args = _build_parser().parse_args(
            ["serve", "--host", "127.0.0.1", "--port", "9090", "--reload", "--workers", "4"]
        )
        assert args.host == "127.0.0.1"
        assert args.port == 9090
        assert args.reload is True
        assert args.workers == 4

    def test_login_defaults(self):
        from kerf_cli.main import _build_parser
        args = _build_parser().parse_args(["login", "--token", "tok"])
        assert args.token == "tok"
        assert args.api_url == ""

    def test_login_custom_url(self):
        from kerf_cli.main import _build_parser
        args = _build_parser().parse_args(
            ["login", "--token", "tok", "--api-url", "https://self.example.com"]
        )
        assert args.api_url == "https://self.example.com"


# ---------------------------------------------------------------------------
# Default backend: missing DATABASE_URL -> embedded SQLite (zero-dependency)
#
# `kerf serve` no longer fails when DATABASE_URL is unset — it falls back to an
# embedded SQLite database under ~/.kerf/kerf.db so a local install needs no
# external services.  Postgres becomes a one-line opt-in (see the reachability
# tests below, which still guard the Postgres path).
# ---------------------------------------------------------------------------

class TestServeMissingDatabaseUrlUsesSqlite:
    def _run_serve_stubbed(self, monkeypatch):
        """Run run_serve() with migrations + uvicorn stubbed so it returns
        instead of blocking, capturing the DATABASE_URL it selected."""
        monkeypatch.delenv("DATABASE_URL", raising=False)
        import kerf_cli.serve as serve_mod

        seen = {}

        async def _fake_migrate(url):
            seen["migrated_url"] = url

        def _fake_uvicorn_run(*a, **k):
            seen["served"] = True

        monkeypatch.setattr(
            "kerf_core.db.migrations.runner.run_migrations", _fake_migrate)
        import uvicorn
        monkeypatch.setattr(uvicorn, "run", _fake_uvicorn_run)
        serve_mod.run_serve()
        return seen

    def test_missing_url_does_not_exit(self, monkeypatch):
        # No SystemExit — the embedded default just works.
        seen = self._run_serve_stubbed(monkeypatch)
        assert seen.get("served") is True

    def test_missing_url_selects_sqlite(self, monkeypatch):
        seen = self._run_serve_stubbed(monkeypatch)
        assert seen["migrated_url"].startswith("sqlite://")
        # DATABASE_URL is exported for the child app process too.
        assert os.environ.get("DATABASE_URL", "").startswith("sqlite://")

    def test_missing_url_prints_sqlite_notice(self, monkeypatch, capsys):
        self._run_serve_stubbed(monkeypatch)
        out = capsys.readouterr().out
        assert "SQLite" in out
        assert "postgres://" in out  # points users at the scale opt-in


# ---------------------------------------------------------------------------
# Fail-fast: unreachable DATABASE_URL (no real connection)
# ---------------------------------------------------------------------------

class TestServeUnreachableDatabaseUrl:
    def test_unreachable_url_exits_nonzero(self, monkeypatch):
        monkeypatch.setenv("DATABASE_URL", "postgres://nobody:x@127.0.0.1:19999/kerf")
        from kerf_cli import serve as serve_mod

        async def _fake_check(url: str):
            return serve_mod._unreachable_message(url)

        with patch.object(serve_mod, "_check_db", side_effect=_fake_check):
            with pytest.raises(SystemExit) as exc_info:
                serve_mod.run_serve()
        assert exc_info.value.code == 1

    def test_unreachable_url_prints_docker_oneliner(self, monkeypatch, capsys):
        dead_url = "postgres://nobody:x@127.0.0.1:19999/kerf"
        monkeypatch.setenv("DATABASE_URL", dead_url)
        from kerf_cli import serve as serve_mod

        async def _fake_check(url: str):
            return serve_mod._unreachable_message(url)

        with patch.object(serve_mod, "_check_db", side_effect=_fake_check):
            with pytest.raises(SystemExit):
                serve_mod.run_serve()

        err = capsys.readouterr().err
        assert serve_mod.DOCKER_ONE_LINER in err
        assert serve_mod.EXPORT_LINE in err
        assert dead_url in err

    def test_unreachable_message_format(self):
        from kerf_cli.serve import _unreachable_message, DOCKER_ONE_LINER, EXPORT_LINE

        url = "postgres://u:p@dead-host:5432/db"
        msg = _unreachable_message(url)
        assert url in msg
        assert DOCKER_ONE_LINER in msg
        assert EXPORT_LINE in msg
        assert "kerf serve" in msg

    def test_empty_database_url_falls_back_to_sqlite(self, monkeypatch, capsys):
        """A blank DATABASE_URL is treated as unset -> embedded SQLite default,
        NOT a Postgres pre-flight failure."""
        monkeypatch.setenv("DATABASE_URL", "   ")
        import kerf_cli.serve as serve_mod

        async def _fake_migrate(url):
            _fake_migrate.url = url

        monkeypatch.setattr(
            "kerf_core.db.migrations.runner.run_migrations", _fake_migrate)
        import uvicorn
        monkeypatch.setattr(uvicorn, "run", lambda *a, **k: None)

        serve_mod.run_serve()  # no SystemExit
        assert _fake_migrate.url.startswith("sqlite://")
        assert "SQLite" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# Credentials module
# ---------------------------------------------------------------------------

class TestCredentials:
    def test_save_and_load_round_trip(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
        monkeypatch.delenv("KERF_API_TOKEN", raising=False)
        monkeypatch.delenv("KERF_API_URL", raising=False)

        from kerf_cli import credentials
        # Reload to pick up the new XDG env
        import importlib
        importlib.reload(credentials)

        saved_path = credentials.save_credentials(
            api_url="https://self.example.com",
            api_token="kerf_sk_testtoken123",
        )
        assert saved_path.exists()

        loaded = credentials.load_credentials()
        assert loaded["api_url"] == "https://self.example.com"
        assert loaded["api_token"] == "kerf_sk_testtoken123"

    def test_credentials_file_mode_0600(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))

        from kerf_cli import credentials
        import importlib
        importlib.reload(credentials)

        path = credentials.save_credentials(
            api_url="https://app.kerf.io",
            api_token="kerf_sk_secure",
        )
        import stat as stat_mod
        mode = stat_mod.S_IMODE(path.stat().st_mode)
        assert mode == 0o600

    def test_default_url_when_no_credentials(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
        monkeypatch.delenv("KERF_API_URL", raising=False)

        from kerf_cli import credentials
        import importlib
        importlib.reload(credentials)

        url = credentials.get_api_url()
        assert url == "https://app.kerf.io"

    def test_env_var_overrides_saved_url(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
        monkeypatch.setenv("KERF_API_URL", "https://override.example.com/")

        from kerf_cli import credentials
        import importlib
        importlib.reload(credentials)

        url = credentials.get_api_url()
        assert url == "https://override.example.com"  # trailing slash stripped

    def test_token_env_var_overrides_saved(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
        monkeypatch.setenv("KERF_API_TOKEN", "env_token_xyz")

        from kerf_cli import credentials
        import importlib
        importlib.reload(credentials)

        # Even if nothing saved, env var wins
        token = credentials.get_api_token()
        assert token == "env_token_xyz"

    def test_no_token_returns_none(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
        monkeypatch.delenv("KERF_API_TOKEN", raising=False)

        from kerf_cli import credentials
        import importlib
        importlib.reload(credentials)

        token = credentials.get_api_token()
        assert token is None


# ---------------------------------------------------------------------------
# login subcommand
# ---------------------------------------------------------------------------

class TestLoginCommand:
    def test_login_saves_credentials(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))

        from kerf_cli import credentials
        import importlib
        importlib.reload(credentials)

        from kerf_cli.main import _build_parser
        import io

        parser = _build_parser()
        args = parser.parse_args(["login", "--token", "kerf_sk_abc", "--api-url", "https://my.host"])

        old_out = sys.stdout
        sys.stdout = io.StringIO()
        try:
            exit_code = args.func(args)
        finally:
            sys.stdout = old_out

        assert exit_code == 0
        loaded = credentials.load_credentials()
        assert loaded["api_token"] == "kerf_sk_abc"
        assert loaded["api_url"] == "https://my.host"

    def test_login_empty_token_returns_error(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
        # Simulate EOF on interactive prompt (no token supplied)
        with patch("builtins.input", side_effect=EOFError):
            from kerf_cli.main import _build_parser
            import io

            parser = _build_parser()
            args = parser.parse_args(["login"])

            old_err = sys.stderr
            sys.stderr = io.StringIO()
            try:
                exit_code = args.func(args)
            finally:
                sys.stderr = old_err

            assert exit_code == 1
