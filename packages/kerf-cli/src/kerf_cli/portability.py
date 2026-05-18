"""kerf export / kerf import — zip archive portability.

export
------
Calls ``GET /api/projects/{pid}/export`` which returns the ZIP archive
produced by ``materialize_project_tree`` (T-123).  The ZIP contains all
project files plus a ``kerf-manifest.json`` entry.

import
------
Reads a ZIP archive (previously produced by ``kerf export``), parses
``kerf-manifest.json``, creates a new project via
``POST /api/projects``, then uploads each file via
``POST /api/projects/{pid}/files``.

Missing server endpoint:
    ``POST /api/projects/import`` (bulk-archive upload) mentioned in T-128
    does NOT exist yet.  This implementation reconstructs the project
    file-by-file using the existing ``POST /api/projects`` +
    ``POST /api/projects/{pid}/files`` endpoints, which is correct and
    complete for text-content files.  When a bulk import endpoint lands the
    client can be updated to a single POST with no behaviour change for the
    caller.

Exit codes:
    0 — success.
    1 — partial failure (some files failed).
    2 — auth failure.
    3 — project/server error.
"""

from __future__ import annotations

import io
import json
import os
import sys
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from typing import Optional

_RETRY_DELAYS = (1, 2, 4)


# ---------------------------------------------------------------------------
# export
# ---------------------------------------------------------------------------

def cmd_export(args) -> int:  # noqa: ANN001
    """Execute ``kerf export``."""
    from kerf_cli.credentials import get_api_url, get_api_token  # noqa: PLC0415

    token: Optional[str] = getattr(args, "token", None) or get_api_token()
    if not token:
        print(
            "error: no API token found. Set KERF_API_TOKEN or pass --token.\n"
            "To create a token: https://kerf.sh/w/<workspace>/settings#api-tokens",
            file=sys.stderr,
        )
        return 2

    api_url: str = get_api_url()
    if getattr(args, "url", None):
        api_url = args.url.rstrip("/")

    project_id: str = args.project_id
    output: Optional[str] = getattr(args, "output", None) or None

    print(f"Exporting project {project_id!r}...", file=sys.stderr)

    url = f"{api_url}/api/projects/{project_id}/export"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})

    try:
        with urllib.request.urlopen(req, timeout=300) as resp:
            zip_bytes = resp.read()
            # Try to infer filename from Content-Disposition
            if not output:
                cd = resp.getheader("Content-Disposition", "")
                if "filename=" in cd:
                    fn = cd.split("filename=")[-1].strip().strip('"')
                    output = fn
                else:
                    output = f"{project_id[:8]}.zip"
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403):
            print(f"error: auth failure (HTTP {exc.code})", file=sys.stderr)
            return 2
        if exc.code == 404:
            print("error: project not found (HTTP 404)", file=sys.stderr)
            return 3
        print(f"error: server error HTTP {exc.code}", file=sys.stderr)
        return 3
    except urllib.error.URLError as exc:
        print(f"error: network error: {exc.reason}", file=sys.stderr)
        return 3

    dest = Path(output)
    try:
        dest.write_bytes(zip_bytes)
    except OSError as exc:
        print(f"error: could not write {dest}: {exc}", file=sys.stderr)
        return 1

    print(f"Exported {len(zip_bytes):,} bytes → {dest}", file=sys.stderr)
    return 0


# ---------------------------------------------------------------------------
# import
# ---------------------------------------------------------------------------

def cmd_import(args) -> int:  # noqa: ANN001
    """Execute ``kerf import``."""
    from kerf_cli.credentials import get_api_url, get_api_token  # noqa: PLC0415

    token: Optional[str] = getattr(args, "token", None) or get_api_token()
    if not token:
        print(
            "error: no API token found. Set KERF_API_TOKEN or pass --token.\n"
            "To create a token: https://kerf.sh/w/<workspace>/settings#api-tokens",
            file=sys.stderr,
        )
        return 2

    api_url: str = get_api_url()
    if getattr(args, "url", None):
        api_url = args.url.rstrip("/")

    archive_path = Path(args.archive)
    project_name: Optional[str] = getattr(args, "name", None) or None

    if not archive_path.exists():
        print(f"error: archive not found: {archive_path}", file=sys.stderr)
        return 1

    # ---- read archive -------------------------------------------------------
    try:
        zip_bytes = archive_path.read_bytes()
    except OSError as exc:
        print(f"error: could not read archive: {exc}", file=sys.stderr)
        return 1

    try:
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            # Parse manifest if present
            manifest: dict = {}
            if "kerf-manifest.json" in zf.namelist():
                manifest = json.loads(zf.read("kerf-manifest.json").decode("utf-8"))

            # Resolve project name
            if not project_name:
                project_name = manifest.get("name") or archive_path.stem

            # Collect file entries (everything except the manifest itself)
            entries: list[tuple[str, bytes]] = []
            for entry in zf.infolist():
                if entry.filename == "kerf-manifest.json":
                    continue
                if entry.filename.endswith("/"):
                    continue  # directory entry
                entries.append((entry.filename, zf.read(entry.filename)))

    except zipfile.BadZipFile as exc:
        print(f"error: not a valid ZIP archive: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:  # noqa: BLE001
        print(f"error: failed to read archive: {exc}", file=sys.stderr)
        return 1

    # ---- create project -----------------------------------------------------
    print(f"Creating project {project_name!r}...", file=sys.stderr)
    try:
        pid = _create_project(api_url, token, project_name)
    except _ApiError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return exc.exit_code

    print(f"  Created project ID: {pid}", file=sys.stderr)

    # Build manifest lookup for kind metadata
    manifest_files: dict[str, dict] = {}
    for mf in manifest.get("files", []):
        manifest_files[mf.get("path", "")] = mf

    # ---- upload files -------------------------------------------------------
    failures = 0
    for rel_path, content_bytes in entries:
        kind = manifest_files.get(rel_path, {}).get("kind", "file")
        name = Path(rel_path).name

        print(f"  Uploading {rel_path}...", file=sys.stderr)
        ok = _upload_file(api_url, pid, token, name, kind, content_bytes)
        if not ok:
            failures += 1

    total = len(entries)
    ok_count = total - failures
    print(
        f"\nImport complete — {ok_count}/{total} file(s) uploaded to project {pid}.",
        file=sys.stderr,
    )
    if failures:
        print(f"  {failures} file(s) failed.", file=sys.stderr)

    return 1 if failures else 0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class _ApiError(Exception):
    def __init__(self, msg: str, exit_code: int = 3):
        super().__init__(msg)
        self.exit_code = exit_code


def _create_project(api_url: str, token: str, name: str) -> str:
    """POST /api/projects and return the new project ID."""
    payload = json.dumps({"name": name}).encode("utf-8")
    url = f"{api_url}/api/projects"
    req = urllib.request.Request(
        url,
        data=payload,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read().decode())
            pid = data.get("id") or data.get("project_id")
            if not pid:
                raise _ApiError("server did not return a project ID", exit_code=3)
            return str(pid)
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403):
            raise _ApiError(f"auth failure (HTTP {exc.code})", exit_code=2) from exc
        raise _ApiError(f"failed to create project: HTTP {exc.code}", exit_code=3) from exc
    except urllib.error.URLError as exc:
        raise _ApiError(f"network error: {exc.reason}", exit_code=3) from exc


def _upload_file(
    api_url: str,
    pid: str,
    token: str,
    name: str,
    kind: str,
    content_bytes: bytes,
) -> bool:
    """POST a single file to /api/projects/{pid}/files. Returns True on success."""
    # Determine text vs binary
    try:
        content_text = content_bytes.decode("utf-8")
    except UnicodeDecodeError:
        content_text = ""

    payload = json.dumps({
        "name": name,
        "kind": kind,
        "content": content_text,
    }).encode("utf-8")

    url = f"{api_url}/api/projects/{pid}/files"
    req = urllib.request.Request(
        url,
        data=payload,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    delays = list(_RETRY_DELAYS)
    last_err = ""
    for delay in [0] + delays:
        if delay:
            time.sleep(delay)
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                resp.read()
                return True
        except urllib.error.HTTPError as exc:
            if exc.code in (400, 401, 403):
                print(f"  error uploading {name}: HTTP {exc.code}", file=sys.stderr)
                return False
            last_err = f"HTTP {exc.code}"
            continue
        except urllib.error.URLError as exc:
            last_err = f"network: {exc.reason}"
            continue

    print(f"  error uploading {name}: {last_err}", file=sys.stderr)
    return False
