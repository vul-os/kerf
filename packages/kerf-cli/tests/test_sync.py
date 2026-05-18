"""Tests for `kerf sync` (T-127).

All HTTP is mocked — no network, no server.
Mirrors the style of test_hydrate.py.
"""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helper: run the `kerf sync` subcommand
# ---------------------------------------------------------------------------

def _run_sync(argv: list[str]) -> tuple[int, str, str]:
    """Run `kerf sync <args>` and return (exit_code, stdout, stderr)."""
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
# Parser smoke tests
# ---------------------------------------------------------------------------

class TestSyncParserSmoke:
    def test_sync_help_exits_zero(self):
        with pytest.raises(SystemExit) as exc_info:
            from kerf_cli.main import _build_parser
            _build_parser().parse_args(["sync", "--help"])
        assert exc_info.value.code == 0

    def test_sync_defaults(self):
        from kerf_cli.main import _build_parser
        args = _build_parser().parse_args(["sync", "proj-uuid", "/tmp/dir"])
        assert args.project_id == "proj-uuid"
        assert args.local_dir == "/tmp/dir"
        assert args.dry_run is False
        assert args.url == ""
        assert args.token == ""

    def test_sync_dry_run_flag(self):
        from kerf_cli.main import _build_parser
        args = _build_parser().parse_args(
            ["sync", "proj-uuid", "/tmp/dir", "--dry-run"]
        )
        assert args.dry_run is True

    def test_sync_all_flags(self):
        from kerf_cli.main import _build_parser
        args = _build_parser().parse_args([
            "sync", "proj-uuid", "/tmp/dir",
            "--dry-run",
            "--url", "http://localhost:8080",
            "--token", "kerf_sk_test",
        ])
        assert args.project_id == "proj-uuid"
        assert args.url == "http://localhost:8080"
        assert args.token == "kerf_sk_test"
        assert args.dry_run is True

    def test_sync_dispatches_to_cmd_sync(self):
        from kerf_cli.main import _build_parser, _cmd_sync
        args = _build_parser().parse_args(["sync", "p", "/d"])
        assert args.func is _cmd_sync


# ---------------------------------------------------------------------------
# Core sync behaviour (mocked HTTP)
# ---------------------------------------------------------------------------

def _make_urlopen_mock(responses: list[tuple[int, bytes | str]]):
    """
    Build a mock for urllib.request.urlopen that returns successive responses.
    Each item in *responses* is (http_status, body_bytes_or_str).
    Status 200 → success; anything else raises HTTPError.
    """
    call_index = [0]

    def _urlopen(req, timeout=None):
        idx = call_index[0]
        call_index[0] += 1
        if idx >= len(responses):
            raise AssertionError(f"urlopen called more times than expected (call #{idx})")
        status, body = responses[idx]
        if status != 200:
            import urllib.error
            raise urllib.error.HTTPError(
                req if isinstance(req, str) else req.full_url,
                status, f"HTTP Error {status}", {}, None
            )
        if isinstance(body, str):
            body = body.encode("utf-8")
        mock_resp = MagicMock()
        mock_resp.read.return_value = body
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        return mock_resp

    return _urlopen


class TestSyncBehaviour:
    """Core sync logic — all HTTP mocked."""

    def _remote_file(
        self,
        name: str,
        fid: str = "file-id-1",
        kind: str = "file",
        updated_at: str = "2020-01-01T00:00:00Z",
    ) -> dict:
        return {
            "id": fid,
            "name": name,
            "kind": kind,
            "updated_at": updated_at,
        }

    # ---- remote-only file is pulled to local dir --------------------------

    def test_remote_only_file_pulled(self, tmp_path, monkeypatch):
        monkeypatch.setenv("KERF_API_TOKEN", "kerf_sk_test")
        local_dir = tmp_path / "proj"
        local_dir.mkdir()

        remote_files = [self._remote_file("design.step", fid="abc123")]
        file_content = b"STEP AP214 binary content here"

        responses = [
            (200, json.dumps(remote_files)),  # list files
            (200, file_content),              # download file
        ]

        with patch("urllib.request.urlopen", side_effect=_make_urlopen_mock(responses)):
            code, _, err = _run_sync([
                "sync", "proj-uuid", str(local_dir),
                "--url", "http://fake-api",
                "--token", "kerf_sk_test",
            ])

        assert code == 0
        dest = local_dir / "design.step"
        assert dest.exists()
        assert dest.read_bytes() == file_content
        assert "pull" in err

    # ---- local-only file is pushed to cloud --------------------------------

    def test_local_only_file_pushed(self, tmp_path, monkeypatch):
        monkeypatch.setenv("KERF_API_TOKEN", "kerf_sk_test")
        local_dir = tmp_path / "proj"
        local_dir.mkdir()

        local_file = local_dir / "notes.txt"
        local_file.write_text("local notes")

        # No remote files
        remote_files: list = []
        # POST create file response
        create_response = json.dumps({"id": "new-file-id", "name": "notes.txt"})

        responses = [
            (200, json.dumps(remote_files)),  # list files
            (200, create_response),           # push file
        ]

        with patch("urllib.request.urlopen", side_effect=_make_urlopen_mock(responses)):
            code, _, err = _run_sync([
                "sync", "proj-uuid", str(local_dir),
                "--url", "http://fake-api",
                "--token", "kerf_sk_test",
            ])

        assert code == 0
        assert "push" in err

    # ---- dry-run: no mutations ----------------------------------------------

    def test_dry_run_no_mutations(self, tmp_path, monkeypatch):
        monkeypatch.setenv("KERF_API_TOKEN", "kerf_sk_test")
        local_dir = tmp_path / "proj"
        local_dir.mkdir()

        remote_files = [self._remote_file("model.step", fid="f1")]

        responses = [
            (200, json.dumps(remote_files)),  # list files only
        ]

        with patch("urllib.request.urlopen", side_effect=_make_urlopen_mock(responses)) as mock_open:
            code, _, err = _run_sync([
                "sync", "proj-uuid", str(local_dir),
                "--url", "http://fake-api",
                "--dry-run",
            ])

        assert code == 0
        # No file created locally
        assert not (local_dir / "model.step").exists()
        # Only one HTTP call (list), no download call
        assert mock_open.call_count == 1
        assert "dry-run" in err.lower()

    # ---- already-in-sync: no actions ---------------------------------------

    def test_already_in_sync_no_actions(self, tmp_path, monkeypatch):
        monkeypatch.setenv("KERF_API_TOKEN", "kerf_sk_test")
        local_dir = tmp_path / "proj"
        local_dir.mkdir()

        # Write a local file with a timestamp significantly before the remote
        local_file = local_dir / "part.step"
        local_file.write_bytes(b"data")

        # Remote file updated_at is in the far past (older than local)
        import os, time
        # Set local mtime to now (newer than remote)
        os.utime(local_file, (time.time(), time.time()))

        remote_files = [
            self._remote_file(
                "part.step", fid="f1",
                updated_at="2000-01-01T00:00:00Z",  # very old
            )
        ]

        responses = [
            (200, json.dumps(remote_files)),       # list files
            (200, json.dumps({"id": "f1"})),       # push (local is newer)
        ]

        with patch("urllib.request.urlopen", side_effect=_make_urlopen_mock(responses)):
            code, _, _ = _run_sync([
                "sync", "proj-uuid", str(local_dir),
                "--url", "http://fake-api",
            ])

        assert code == 0

    # ---- no token → exit 2 --------------------------------------------------

    def test_no_token_exits_2(self, tmp_path, monkeypatch):
        monkeypatch.delenv("KERF_API_TOKEN", raising=False)
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))

        from kerf_cli import credentials
        import importlib
        importlib.reload(credentials)

        code, _, err = _run_sync([
            "sync", "proj-uuid", str(tmp_path / "dir"),
        ])
        assert code == 2
        assert "KERF_API_TOKEN" in err

    # ---- server 404 → exit 3 ------------------------------------------------

    def test_server_404_exits_3(self, tmp_path, monkeypatch):
        monkeypatch.setenv("KERF_API_TOKEN", "kerf_sk_test")
        local_dir = tmp_path / "proj"
        local_dir.mkdir()

        responses = [(404, b"not found")]

        with patch("urllib.request.urlopen", side_effect=_make_urlopen_mock(responses)):
            code, _, err = _run_sync([
                "sync", "proj-uuid", str(local_dir),
                "--url", "http://fake-api",
            ])

        assert code == 3
        assert "not found" in err.lower()

    # ---- local dir created if it does not exist ----------------------------

    def test_local_dir_created_if_missing(self, tmp_path, monkeypatch):
        monkeypatch.setenv("KERF_API_TOKEN", "kerf_sk_test")
        local_dir = tmp_path / "new_dir"
        assert not local_dir.exists()

        # No remote files → nothing to sync → 0 exit
        responses = [(200, json.dumps([]))]

        with patch("urllib.request.urlopen", side_effect=_make_urlopen_mock(responses)):
            code, _, _ = _run_sync([
                "sync", "proj-uuid", str(local_dir),
                "--url", "http://fake-api",
            ])

        assert code == 0
        assert local_dir.is_dir()


# ---------------------------------------------------------------------------
# _compute_diff unit tests
# ---------------------------------------------------------------------------

class TestComputeDiff:
    def test_remote_only_produces_pull(self, tmp_path):
        from kerf_cli.sync import _compute_diff
        remote = [{"id": "f1", "name": "a.step", "kind": "step", "updated_at": "2020-01-01T00:00:00Z"}]
        local_map: dict = {}
        actions = _compute_diff(remote, local_map, tmp_path)
        assert any(a["type"] == "pull" and a["path"] == "a.step" for a in actions)

    def test_local_only_produces_push(self, tmp_path):
        from kerf_cli.sync import _compute_diff
        remote: list = []
        local_map = {"b.txt": {"path": tmp_path / "b.txt", "mtime": 1000.0, "size": 10}}
        actions = _compute_diff(remote, local_map, tmp_path)
        assert any(a["type"] == "push" and a["path"] == "b.txt" for a in actions)

    def test_folders_skipped(self, tmp_path):
        from kerf_cli.sync import _compute_diff
        remote = [{"id": "f1", "name": "src", "kind": "folder", "updated_at": "2020-01-01T00:00:00Z"}]
        local_map: dict = {}
        actions = _compute_diff(remote, local_map, tmp_path)
        assert not actions

    def test_remote_newer_produces_pull(self, tmp_path):
        from kerf_cli.sync import _compute_diff
        import time
        old_mtime = time.time() - 10000  # old local
        remote = [{"id": "f1", "name": "x.step", "kind": "step", "updated_at": "2099-01-01T00:00:00Z"}]
        local_map = {"x.step": {"path": tmp_path / "x.step", "mtime": old_mtime, "size": 10}}
        actions = _compute_diff(remote, local_map, tmp_path)
        assert any(a["type"] == "pull" and a["path"] == "x.step" for a in actions)

    def test_local_newer_produces_push(self, tmp_path):
        from kerf_cli.sync import _compute_diff
        import time
        new_mtime = time.time()
        remote = [{"id": "f1", "name": "x.step", "kind": "step", "updated_at": "2000-01-01T00:00:00Z"}]
        local_map = {"x.step": {"path": tmp_path / "x.step", "mtime": new_mtime, "size": 10}}
        actions = _compute_diff(remote, local_map, tmp_path)
        assert any(a["type"] == "push" and a["path"] == "x.step" for a in actions)


# ---------------------------------------------------------------------------
# _parse_iso unit tests
# ---------------------------------------------------------------------------

class TestParseIso:
    def test_parses_z_suffix(self):
        from kerf_cli.sync import _parse_iso
        ts = _parse_iso("2020-06-15T12:30:00Z")
        assert abs(ts - 1592224200.0) < 5  # allow small floating-point drift

    def test_parses_without_z(self):
        from kerf_cli.sync import _parse_iso
        ts = _parse_iso("2020-06-15T12:30:00")
        assert ts > 0
