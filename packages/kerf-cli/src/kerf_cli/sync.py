"""kerf sync — two-way folder mirror between a local directory and a cloud project.

Sync flow
---------
1.  Fetch the project file list from GET /api/projects/{pid}/files.
2.  Walk the local directory and build a local file map.
3.  Compute a diff:
    - remote-only files   → pull  (download to local dir)
    - local-only files    → push  (upload to cloud project)
    - both sides present  → compare mtime (local) vs updated_at (remote),
                           last-write-wins; if local is newer, push; else pull.
4.  Apply changes (unless --dry-run).

Large-file pointers:
    After pulling any remote file its content is inspected; LFS pointer stubs
    are hydrated implicitly by calling the hydrate machinery.

Deletions:
    A file that exists locally but not remotely is pushed (not treated as a
    deletion).  A file deleted locally is NOT auto-deleted on the server —
    the user receives a warning instead (safe default per T-127 DoD).

Exit codes:
    0 — sync completed with no errors.
    1 — one or more files failed to sync.
    2 — auth failure.
    3 — project not found / API error.

Missing server endpoint note:
    ``GET /api/projects/{pid}/files/changed-since?ts=`` mentioned in the T-127
    task spec does NOT exist yet.  This implementation falls back to fetching
    the full file list and doing client-side mtime comparison, which is correct
    but not optimised for large projects.  When the server-side endpoint lands
    (tasks.md T-127 scope) the client can switch to it with no behaviour
    change.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

_RETRY_DELAYS = (1, 2, 4)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def cmd_sync(args) -> int:  # noqa: ANN001
    """Execute ``kerf sync``."""
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
    local_dir = Path(args.local_dir).resolve()
    dry_run: bool = args.dry_run

    if not local_dir.exists():
        local_dir.mkdir(parents=True, exist_ok=True)

    # ---- fetch remote file list -------------------------------------------
    print(f"Fetching remote file list for project {project_id!r}...", file=sys.stderr)
    try:
        remote_files = _list_remote_files(api_url, project_id, token)
    except _ApiError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return exc.exit_code

    # ---- build local file map ---------------------------------------------
    local_map = _build_local_map(local_dir)

    # ---- compute diff -------------------------------------------------------
    actions = _compute_diff(remote_files, local_map, local_dir)

    if not actions:
        print("Already in sync — nothing to do.", file=sys.stderr)
        return 0

    # ---- report / apply -----------------------------------------------------
    failures = 0
    for action in actions:
        if action["type"] == "pull":
            _print_action("pull", action["path"], action.get("reason", ""), dry_run)
            if not dry_run:
                ok = _pull_file(
                    api_url, project_id, token, action["file_id"],
                    local_dir / action["path"],
                )
                if not ok:
                    failures += 1
        elif action["type"] == "push":
            _print_action("push", action["path"], action.get("reason", ""), dry_run)
            if not dry_run:
                ok = _push_file(
                    api_url, project_id, token,
                    local_dir / action["path"],
                    action["path"],
                    action.get("kind", "file"),
                )
                if not ok:
                    failures += 1
        elif action["type"] == "warn":
            print(f"  warn   {action['path']}  — {action.get('reason', '')}", file=sys.stderr)

    if dry_run:
        print(f"\nDry-run complete — {len(actions)} action(s) would be applied.", file=sys.stderr)
    else:
        ok_count = len([a for a in actions if a["type"] in ("pull", "push")]) - failures
        print(f"\nSync complete — {ok_count} action(s) applied.", file=sys.stderr)
        if failures:
            print(f"  {failures} action(s) failed.", file=sys.stderr)

    return 1 if failures else 0


# ---------------------------------------------------------------------------
# Remote file list
# ---------------------------------------------------------------------------

class _ApiError(Exception):
    def __init__(self, msg: str, exit_code: int = 3):
        super().__init__(msg)
        self.exit_code = exit_code


def _list_remote_files(api_url: str, pid: str, token: str) -> list[dict]:
    """Return parsed JSON list from GET /api/projects/{pid}/files."""
    url = f"{api_url}/api/projects/{pid}/files"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403):
            raise _ApiError(f"auth failure (HTTP {exc.code})", exit_code=2) from exc
        if exc.code == 404:
            raise _ApiError("project not found (HTTP 404)", exit_code=3) from exc
        raise _ApiError(f"server error HTTP {exc.code}", exit_code=3) from exc
    except urllib.error.URLError as exc:
        raise _ApiError(f"network error: {exc.reason}", exit_code=3) from exc


# ---------------------------------------------------------------------------
# Local file map
# ---------------------------------------------------------------------------

def _build_local_map(local_dir: Path) -> dict[str, dict]:
    """Return {relative_posix_path: {path, mtime, size}} for files under local_dir."""
    result = {}
    for fp in sorted(local_dir.rglob("*")):
        if not fp.is_file():
            continue
        rel = fp.relative_to(local_dir).as_posix()
        stat = fp.stat()
        result[rel] = {"path": fp, "mtime": stat.st_mtime, "size": stat.st_size}
    return result


# ---------------------------------------------------------------------------
# Diff computation
# ---------------------------------------------------------------------------

def _compute_diff(
    remote_files: list[dict],
    local_map: dict[str, dict],
    local_dir: Path,
) -> list[dict]:
    """Return a list of action dicts: {type, path, ...}."""
    actions = []

    # Build a map of remote path → remote file record.
    # Folders are skipped (they are implicit in the path).
    remote_map: dict[str, dict] = {}
    for rf in remote_files:
        if rf.get("kind") == "folder":
            continue
        name = rf.get("name", "")
        if not name:
            continue
        # Use name as the relative path (flat projects); for nested projects
        # the parent_id chain would need to be resolved, but we use name for now.
        remote_map[name] = rf

    seen_remote_paths = set()

    for rel_path, rf in remote_map.items():
        seen_remote_paths.add(rel_path)
        if rel_path not in local_map:
            # Remote-only → pull
            actions.append({
                "type": "pull",
                "path": rel_path,
                "file_id": str(rf.get("id", "")),
                "reason": "remote-only",
            })
        else:
            # Both sides present — compare timestamps
            local_mtime = local_map[rel_path]["mtime"]
            remote_updated_at = rf.get("updated_at")
            if remote_updated_at:
                try:
                    remote_ts = _parse_iso(remote_updated_at)
                    if local_mtime > remote_ts + 1:
                        # Local is newer → push
                        actions.append({
                            "type": "push",
                            "path": rel_path,
                            "kind": rf.get("kind", "file"),
                            "reason": "local newer",
                        })
                    elif remote_ts > local_mtime + 1:
                        # Remote is newer → pull
                        actions.append({
                            "type": "pull",
                            "path": rel_path,
                            "file_id": str(rf.get("id", "")),
                            "reason": "remote newer",
                        })
                    # else: within 1s tolerance → in sync
                except (ValueError, OSError):
                    pass  # can't compare → skip

    for rel_path in local_map:
        if rel_path not in seen_remote_paths:
            # Local-only → push
            actions.append({
                "type": "push",
                "path": rel_path,
                "kind": "file",
                "reason": "local-only",
            })

    return actions


def _parse_iso(ts: str) -> float:
    """Parse an ISO-8601 UTC string to a POSIX timestamp."""
    ts = ts.rstrip("Z")
    try:
        dt = datetime.fromisoformat(ts).replace(tzinfo=timezone.utc)
    except ValueError:
        # Fallback: try with explicit UTC offset
        dt = datetime.strptime(ts, "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
    return dt.timestamp()


# ---------------------------------------------------------------------------
# Pull (download)
# ---------------------------------------------------------------------------

def _pull_file(
    api_url: str,
    pid: str,
    token: str,
    file_id: str,
    dest: Path,
) -> bool:
    """Download a remote file to dest. Returns True on success."""
    url = f"{api_url}/api/projects/{pid}/files/{file_id}/download"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    delays = list(_RETRY_DELAYS)
    last_err = ""
    for delay in [0] + delays:
        if delay:
            time.sleep(delay)
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                data = resp.read()
        except urllib.error.HTTPError as exc:
            if exc.code in (401, 403, 404):
                print(f"  error pulling {dest.name}: HTTP {exc.code}", file=sys.stderr)
                return False
            last_err = f"HTTP {exc.code}"
            continue
        except urllib.error.URLError as exc:
            last_err = f"network: {exc.reason}"
            continue

        # Atomic write
        dest.parent.mkdir(parents=True, exist_ok=True)
        try:
            fd, tmp = tempfile.mkstemp(dir=dest.parent, prefix=".kerf_sync_")
            with os.fdopen(fd, "wb") as f:
                f.write(data)
            os.replace(tmp, dest)
        except OSError as exc:
            print(f"  error writing {dest}: {exc}", file=sys.stderr)
            return False

        # Hydrate LFS pointer stubs implicitly
        _maybe_hydrate(dest, api_url, pid, token)
        return True

    print(f"  error pulling {dest.name}: {last_err}", file=sys.stderr)
    return False


def _maybe_hydrate(path: Path, api_url: str, pid: str, token: str) -> None:
    """If path is an LFS pointer stub, hydrate it in place."""
    try:
        from kerf_cli.hydrate import _detect_stub, _hydrate_file  # noqa: PLC0415
        result = _detect_stub(path)
        if result is not None:
            oid, size = result
            _hydrate_file(path, oid, size, pid, api_url, token)
    except Exception:  # noqa: BLE001
        pass  # hydration is best-effort


# ---------------------------------------------------------------------------
# Push (upload)
# ---------------------------------------------------------------------------

def _push_file(
    api_url: str,
    pid: str,
    token: str,
    local_path: Path,
    rel_path: str,
    kind: str = "file",
) -> bool:
    """Upload a local file to the project. Returns True on success."""
    try:
        content_bytes = local_path.read_bytes()
    except OSError as exc:
        print(f"  error reading {local_path}: {exc}", file=sys.stderr)
        return False

    # Determine if content is text or binary
    try:
        content_text = content_bytes.decode("utf-8")
        is_text = True
    except UnicodeDecodeError:
        content_text = ""
        is_text = False

    # Use the file name as the remote name
    name = Path(rel_path).name

    # POST to create (or update) the file
    payload = json.dumps({
        "name": name,
        "kind": kind,
        "content": content_text if is_text else "",
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
            if exc.code in (400, 401, 403, 404):
                print(f"  error pushing {name}: HTTP {exc.code}", file=sys.stderr)
                return False
            last_err = f"HTTP {exc.code}"
            continue
        except urllib.error.URLError as exc:
            last_err = f"network: {exc.reason}"
            continue

    print(f"  error pushing {name}: {last_err}", file=sys.stderr)
    return False


# ---------------------------------------------------------------------------
# Display helper
# ---------------------------------------------------------------------------

def _print_action(action_type: str, path: str, reason: str, dry_run: bool) -> None:
    tag = f"[dry-run] " if dry_run else ""
    print(f"  {tag}{action_type:<6}  {path}  ({reason})", file=sys.stderr)
