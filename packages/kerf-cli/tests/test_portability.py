"""Tests for `kerf export` and `kerf import` (T-128).

All HTTP is mocked — no network, no server.
Mirrors the style of test_hydrate.py.
"""

from __future__ import annotations

import io
import json
import sys
import zipfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helper: run a kerf subcommand
# ---------------------------------------------------------------------------

def _run_cmd(argv: list[str]) -> tuple[int, str, str]:
    """Run a kerf subcommand and return (exit_code, stdout, stderr)."""
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
# Build a mock urlopen response
# ---------------------------------------------------------------------------

def _mock_resp(body: bytes, status: int = 200, headers: dict | None = None):
    mock = MagicMock()
    mock.read.return_value = body
    mock.getheader = MagicMock(
        side_effect=lambda h, default="": (headers or {}).get(h, default)
    )
    mock.__enter__ = MagicMock(return_value=mock)
    mock.__exit__ = MagicMock(return_value=False)
    return mock


def _make_zip(files: dict[str, bytes], manifest: dict | None = None) -> bytes:
    """Build an in-memory ZIP with optional kerf-manifest.json."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        if manifest is not None:
            zf.writestr("kerf-manifest.json", json.dumps(manifest))
        for name, content in files.items():
            zf.writestr(name, content)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# export — parser smoke tests
# ---------------------------------------------------------------------------

class TestExportParserSmoke:
    def test_export_help_exits_zero(self):
        with pytest.raises(SystemExit) as exc_info:
            from kerf_cli.main import _build_parser
            _build_parser().parse_args(["export", "--help"])
        assert exc_info.value.code == 0

    def test_export_defaults(self):
        from kerf_cli.main import _build_parser
        args = _build_parser().parse_args(["export", "proj-uuid"])
        assert args.project_id == "proj-uuid"
        assert args.output == ""
        assert args.url == ""
        assert args.token == ""

    def test_export_output_flag(self):
        from kerf_cli.main import _build_parser
        args = _build_parser().parse_args(["export", "proj-uuid", "-o", "out.zip"])
        assert args.output == "out.zip"

    def test_export_long_output_flag(self):
        from kerf_cli.main import _build_parser
        args = _build_parser().parse_args(["export", "proj-uuid", "--output", "out.zip"])
        assert args.output == "out.zip"

    def test_export_dispatches_to_cmd_export(self):
        from kerf_cli.main import _build_parser, _cmd_export
        args = _build_parser().parse_args(["export", "p"])
        assert args.func is _cmd_export


# ---------------------------------------------------------------------------
# import — parser smoke tests
# ---------------------------------------------------------------------------

class TestImportParserSmoke:
    def test_import_help_exits_zero(self):
        with pytest.raises(SystemExit) as exc_info:
            from kerf_cli.main import _build_parser
            _build_parser().parse_args(["import", "--help"])
        assert exc_info.value.code == 0

    def test_import_defaults(self):
        from kerf_cli.main import _build_parser
        args = _build_parser().parse_args(["import", "archive.zip"])
        assert args.archive == "archive.zip"
        assert args.name == ""
        assert args.url == ""
        assert args.token == ""

    def test_import_name_flag(self):
        from kerf_cli.main import _build_parser
        args = _build_parser().parse_args(["import", "a.zip", "--name", "My Project"])
        assert args.name == "My Project"

    def test_import_dispatches_to_cmd_import(self):
        from kerf_cli.main import _build_parser, _cmd_import
        args = _build_parser().parse_args(["import", "a.zip"])
        assert args.func is _cmd_import


# ---------------------------------------------------------------------------
# export — behaviour tests
# ---------------------------------------------------------------------------

class TestExportBehaviour:
    def test_export_writes_zip_to_disk(self, tmp_path, monkeypatch):
        monkeypatch.setenv("KERF_API_TOKEN", "kerf_sk_test")

        zip_content = _make_zip({"design.step": b"STEP data"})
        mock = _mock_resp(
            zip_content,
            headers={"Content-Disposition": 'attachment; filename="my-project-abcd1234.zip"'},
        )

        output_path = tmp_path / "out.zip"

        with patch("urllib.request.urlopen", return_value=mock):
            code, _, err = _run_cmd([
                "export", "proj-uuid",
                "-o", str(output_path),
                "--url", "http://fake-api",
                "--token", "kerf_sk_test",
            ])

        assert code == 0
        assert output_path.exists()
        assert output_path.read_bytes() == zip_content
        assert "Exported" in err

    def test_export_uses_content_disposition_filename(self, tmp_path, monkeypatch):
        monkeypatch.setenv("KERF_API_TOKEN", "kerf_sk_test")

        zip_content = _make_zip({"f.txt": b"hello"})
        mock = _mock_resp(
            zip_content,
            headers={"Content-Disposition": 'attachment; filename="slug-00001111.zip"'},
        )

        with patch("urllib.request.urlopen", return_value=mock):
            code, _, err = _run_cmd([
                "export", "00001111-0000-0000-0000-000000000000",
                "--url", "http://fake-api",
            ])

        assert code == 0
        # Should write to the filename from Content-Disposition
        assert (Path.cwd() / "slug-00001111.zip").exists() or "slug-00001111.zip" in err
        # Clean up
        p = Path("slug-00001111.zip")
        if p.exists():
            p.unlink()

    def test_export_no_token_exits_2(self, tmp_path, monkeypatch):
        monkeypatch.delenv("KERF_API_TOKEN", raising=False)
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))

        from kerf_cli import credentials
        import importlib
        importlib.reload(credentials)

        code, _, err = _run_cmd(["export", "proj-uuid"])
        assert code == 2
        assert "KERF_API_TOKEN" in err

    def test_export_404_exits_3(self, tmp_path, monkeypatch):
        monkeypatch.setenv("KERF_API_TOKEN", "kerf_sk_test")

        import urllib.error
        exc = urllib.error.HTTPError("http://fake-api/...", 404, "Not Found", {}, None)

        with patch("urllib.request.urlopen", side_effect=exc):
            code, _, err = _run_cmd([
                "export", "bad-id",
                "--url", "http://fake-api",
            ])

        assert code == 3
        assert "not found" in err.lower()

    def test_export_auth_failure_exits_2(self, tmp_path, monkeypatch):
        monkeypatch.setenv("KERF_API_TOKEN", "bad_token")

        import urllib.error
        exc = urllib.error.HTTPError("http://fake-api/...", 401, "Unauthorized", {}, None)

        with patch("urllib.request.urlopen", side_effect=exc):
            code, _, err = _run_cmd([
                "export", "proj-uuid",
                "--url", "http://fake-api",
                "--token", "bad_token",
            ])

        assert code == 2
        assert "auth" in err.lower()


# ---------------------------------------------------------------------------
# import — behaviour tests
# ---------------------------------------------------------------------------

class TestImportBehaviour:
    def test_import_creates_project_and_uploads_files(self, tmp_path, monkeypatch):
        monkeypatch.setenv("KERF_API_TOKEN", "kerf_sk_test")

        manifest = {
            "name": "Test Project",
            "files": [
                {"path": "design.step", "kind": "step"},
                {"path": "notes.txt", "kind": "file"},
            ],
        }
        zip_path = tmp_path / "export.zip"
        zip_path.write_bytes(_make_zip(
            {
                "design.step": b"STEP AP214",
                "notes.txt": b"some notes",
            },
            manifest=manifest,
        ))

        create_resp = _mock_resp(json.dumps({"id": "new-proj-id"}).encode())
        upload_resp1 = _mock_resp(json.dumps({"id": "f1"}).encode())
        upload_resp2 = _mock_resp(json.dumps({"id": "f2"}).encode())

        call_index = [0]
        resps = [create_resp, upload_resp1, upload_resp2]

        def _urlopen(req, timeout=None):
            idx = call_index[0]
            call_index[0] += 1
            return resps[idx]

        with patch("urllib.request.urlopen", side_effect=_urlopen):
            code, _, err = _run_cmd([
                "import", str(zip_path),
                "--url", "http://fake-api",
                "--token", "kerf_sk_test",
            ])

        assert code == 0
        assert "new-proj-id" in err
        assert "2/2" in err

    def test_import_uses_manifest_name(self, tmp_path, monkeypatch):
        monkeypatch.setenv("KERF_API_TOKEN", "kerf_sk_test")

        manifest = {"name": "From Manifest", "files": [{"path": "a.txt", "kind": "file"}]}
        zip_path = tmp_path / "proj.zip"
        zip_path.write_bytes(_make_zip({"a.txt": b"hello"}, manifest=manifest))

        captured_name = []

        def _urlopen(req, timeout=None):
            # First call: POST /api/projects — capture payload
            if hasattr(req, "data") and req.data:
                body = json.loads(req.data.decode())
                if "name" in body and "content" not in body:
                    captured_name.append(body["name"])
            return _mock_resp(json.dumps({"id": "pid-xyz"}).encode())

        with patch("urllib.request.urlopen", side_effect=_urlopen):
            code, _, _ = _run_cmd([
                "import", str(zip_path),
                "--url", "http://fake-api",
            ])

        assert code == 0
        assert "From Manifest" in captured_name

    def test_import_custom_name_overrides_manifest(self, tmp_path, monkeypatch):
        monkeypatch.setenv("KERF_API_TOKEN", "kerf_sk_test")

        manifest = {"name": "Old Name", "files": []}
        zip_path = tmp_path / "proj.zip"
        zip_path.write_bytes(_make_zip({}, manifest=manifest))

        captured_name = []

        def _urlopen(req, timeout=None):
            if hasattr(req, "data") and req.data:
                body = json.loads(req.data.decode())
                if "name" in body and "content" not in body:
                    captured_name.append(body["name"])
            return _mock_resp(json.dumps({"id": "pid-yyy"}).encode())

        with patch("urllib.request.urlopen", side_effect=_urlopen):
            _run_cmd([
                "import", str(zip_path),
                "--name", "Custom Name",
                "--url", "http://fake-api",
            ])

        assert "Custom Name" in captured_name

    def test_import_no_token_exits_2(self, tmp_path, monkeypatch):
        monkeypatch.delenv("KERF_API_TOKEN", raising=False)
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))

        from kerf_cli import credentials
        import importlib
        importlib.reload(credentials)

        zip_path = tmp_path / "x.zip"
        zip_path.write_bytes(_make_zip({}))

        code, _, err = _run_cmd(["import", str(zip_path)])
        assert code == 2
        assert "KERF_API_TOKEN" in err

    def test_import_missing_archive_exits_1(self, tmp_path, monkeypatch):
        monkeypatch.setenv("KERF_API_TOKEN", "kerf_sk_test")

        code, _, err = _run_cmd([
            "import", str(tmp_path / "nonexistent.zip"),
            "--url", "http://fake-api",
        ])
        assert code == 1
        assert "not found" in err.lower() or "archive" in err.lower()

    def test_import_bad_zip_exits_1(self, tmp_path, monkeypatch):
        monkeypatch.setenv("KERF_API_TOKEN", "kerf_sk_test")

        bad_zip = tmp_path / "bad.zip"
        bad_zip.write_bytes(b"this is not a zip file")

        code, _, err = _run_cmd([
            "import", str(bad_zip),
            "--url", "http://fake-api",
        ])
        assert code == 1
        assert "zip" in err.lower() or "archive" in err.lower()

    def test_import_round_trip(self, tmp_path, monkeypatch):
        """Round-trip: content uploaded matches content in the archive."""
        monkeypatch.setenv("KERF_API_TOKEN", "kerf_sk_test")

        original_content = b"This is the source of truth."
        manifest = {"name": "RT", "files": [{"path": "src.txt", "kind": "file"}]}
        zip_path = tmp_path / "rt.zip"
        zip_path.write_bytes(_make_zip({"src.txt": original_content}, manifest=manifest))

        uploaded_content = []

        def _urlopen(req, timeout=None):
            if hasattr(req, "data") and req.data:
                body = json.loads(req.data.decode())
                if "content" in body:
                    uploaded_content.append(body["content"])
            return _mock_resp(json.dumps({"id": "pid-rt"}).encode())

        with patch("urllib.request.urlopen", side_effect=_urlopen):
            code, _, _ = _run_cmd([
                "import", str(zip_path),
                "--url", "http://fake-api",
            ])

        assert code == 0
        assert original_content.decode() in uploaded_content


# ---------------------------------------------------------------------------
# _create_project unit tests
# ---------------------------------------------------------------------------

class TestCreateProject:
    def test_returns_project_id(self):
        from kerf_cli.portability import _create_project

        resp = _mock_resp(json.dumps({"id": "the-new-pid"}).encode())
        with patch("urllib.request.urlopen", return_value=resp):
            pid = _create_project("http://api", "tok", "My Project")
        assert pid == "the-new-pid"

    def test_auth_failure_raises_api_error(self):
        from kerf_cli.portability import _create_project, _ApiError
        import urllib.error

        exc = urllib.error.HTTPError("u", 401, "Unauthorized", {}, None)
        with patch("urllib.request.urlopen", side_effect=exc):
            with pytest.raises(_ApiError) as exc_info:
                _create_project("http://api", "bad", "Proj")
        assert exc_info.value.exit_code == 2
