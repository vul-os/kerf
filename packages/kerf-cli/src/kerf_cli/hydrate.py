"""kerf hydrate / kerf pull-blobs — resolve LFS pointer stubs to real bytes.

Resolution flow (per file):
  1.  Read first 200 bytes; call lfs_pointer.parse(); skip if not a stub.
  2.  Resolve project-id (--project flag → .kerf/project file → remote URL).
  3.  Check local blob cache (~/.cache/kerf/blobs/<oid>); copy if present.
  4.  Fetch from API:  GET /api/projects/<project-id>/blobs/<oid>
      Authorization: Bearer <token>
      Follows 302 redirect.  Retries up to 3 times with exponential back-off.
  5.  Verify sha256 of downloaded bytes against pointer oid.
  6.  Atomic replace: write to tmp in the same directory, then os.replace().
  7.  Cache write: copy verified bytes to ~/.cache/kerf/blobs/<oid>.

Exit codes:
  0 — all targeted files hydrated (or already real bytes).
  1 — one or more files failed.
  2 — auth failure (no token, 401/403 from server).
  3 — project not found / no blobs endpoint on this server version.
"""

from __future__ import annotations

import concurrent.futures
import fnmatch
import hashlib
import os
import shutil
import sys
import tempfile
import time
import urllib.request
import urllib.error
import urllib.parse
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_BLOB_CACHE_DIR = Path.home() / ".cache" / "kerf" / "blobs"
_MAX_STUB_BYTES = 200          # only need the first 200 bytes to detect a stub
_RETRY_DELAYS = (1, 2, 4)     # seconds; 3 attempts total


# ---------------------------------------------------------------------------
# Public entry point (called from main.py)
# ---------------------------------------------------------------------------

def cmd_hydrate(args) -> int:  # noqa: ANN001
    """Execute `kerf hydrate` / `kerf pull-blobs`.

    Returns an exit code (int).
    """
    from kerf_cli.credentials import get_api_url, get_api_token  # noqa: PLC0415

    # ---- token resolution -----------------------------------------------
    token: Optional[str] = None
    if getattr(args, "token", None):
        token = args.token
    else:
        token = get_api_token()

    if not token:
        print(
            "error: no API token found. Set KERF_API_TOKEN or pass --token.\n"
            "To create a token: https://kerf.sh/w/<workspace>/settings#api-tokens",
            file=sys.stderr,
        )
        return 2

    # ---- api_url ------------------------------------------------------------
    api_url: str = get_api_url()
    if getattr(args, "url", None):
        api_url = args.url.rstrip("/")

    # ---- project-id resolution ---------------------------------------------
    project_id: Optional[str] = getattr(args, "project", None) or None
    if not project_id:
        project_id = _resolve_project_id()

    # Defer project-id failure to per-file processing so --dry-run still lists
    # stubs even when no project is configured.

    # ---- collect paths to scan ---------------------------------------------
    patterns: list[str] = list(args.paths) if args.paths else ["."]
    files_to_check: list[Path] = _collect_files(patterns)

    dry_run: bool = args.dry_run
    force: bool = args.force
    concurrency: int = max(1, args.concurrency)

    # ---- scan for stubs ----------------------------------------------------
    print("Scanning working tree for pointer stubs...", file=sys.stderr)
    stubs: list[tuple[Path, str, int]] = []  # (path, oid, size)
    skipped: list[Path] = []

    for fp in files_to_check:
        result = _detect_stub(fp)
        if result is None:
            skipped.append(fp)
        else:
            oid, size = result
            stubs.append((fp, oid, size))

    if not stubs:
        print("  No pointer stubs found — nothing to do.", file=sys.stderr)
        return 0

    total_bytes = sum(s for _, _, s in stubs)
    print(
        f"  Found {len(stubs)} stub{'s' if len(stubs) != 1 else ''}"
        f"  (total: {_fmt_bytes(total_bytes)})",
        file=sys.stderr,
    )

    if dry_run:
        print("\nDry-run — would fetch:", file=sys.stderr)
        for fp, oid, size in stubs:
            print(f"  {fp}  ({_fmt_bytes(size)})", file=sys.stderr)
        return 0

    # ---- ensure project-id is available ------------------------------------
    if not project_id:
        print(
            "error: cannot determine project-id.\n"
            "Pass --project <id>, or create .kerf/project with the project UUID,\n"
            "or ensure the git remote URL contains a kerf.sh project path.",
            file=sys.stderr,
        )
        return 3

    # ---- hydrate (concurrent) ---------------------------------------------
    failures: list[tuple[Path, str]] = []
    hydrated = 0

    # Filter out already-hydrated files (unless --force)
    to_fetch: list[tuple[Path, str, int]] = []
    for fp, oid, size in stubs:
        if not force and _is_already_hydrated(fp, size):
            # Already real bytes with matching declared size
            hydrated += 1
            continue
        to_fetch.append((fp, oid, size))

    print(f"\nFetching blobs  [0/{len(to_fetch)}]", file=sys.stderr)

    def _fetch_one(item: tuple[Path, str, int]) -> tuple[Path, bool, str]:
        fp, oid, size = item
        ok, msg = _hydrate_file(fp, oid, size, project_id, api_url, token)
        return fp, ok, msg

    with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as pool:
        futures = {pool.submit(_fetch_one, item): item for item in to_fetch}
        done_count = 0
        for fut in concurrent.futures.as_completed(futures):
            fp, ok, msg = fut.result()
            done_count += 1
            if ok:
                hydrated += 1
                print(
                    f"  ✓  {fp}  ({_fmt_bytes(futures[fut][2])})",
                    file=sys.stderr,
                )
            else:
                failures.append((fp, msg))
                print(f"  ✗  {fp}  failed: {msg}", file=sys.stderr)
            # Overwrite the progress line
            total_fetches = len(to_fetch)
            print(
                f"\rFetching blobs  [{done_count}/{total_fetches}]",
                end="",
                file=sys.stderr,
            )

    print(file=sys.stderr)  # newline after progress line

    already_ok = len(stubs) - len(to_fetch)
    summary_parts = [f"{hydrated} hydrated"]
    if already_ok:
        summary_parts.append(f"{already_ok} already hydrated")
    if failures:
        summary_parts.append(f"{len(failures)} failed")

    print(f"\nDone. {', '.join(summary_parts)}.", file=sys.stderr)

    if failures:
        print("\nFailed files:", file=sys.stderr)
        for fp, msg in failures:
            print(f"  {fp}: {msg}", file=sys.stderr)
            print(f"  Re-run: kerf hydrate {fp}", file=sys.stderr)
        return 1

    return 0


# ---------------------------------------------------------------------------
# File collection
# ---------------------------------------------------------------------------

def _collect_files(patterns: list[str]) -> list[Path]:
    """Expand paths/globs to a deduplicated list of regular files."""
    seen: set[Path] = set()
    result: list[Path] = []

    for pat in patterns:
        p = Path(pat)
        # Plain path: directory or file
        if p.exists():
            if p.is_dir():
                for fp in sorted(p.rglob("*")):
                    if fp.is_file() and fp not in seen:
                        seen.add(fp)
                        result.append(fp)
            elif p.is_file() and p not in seen:
                seen.add(p)
                result.append(p)
        else:
            # Treat as glob pattern relative to cwd
            cwd = Path(".")
            for fp in sorted(cwd.rglob(pat)):
                if fp.is_file() and fp not in seen:
                    seen.add(fp)
                    result.append(fp)

    return result


# ---------------------------------------------------------------------------
# Stub detection
# ---------------------------------------------------------------------------

def _detect_stub(path: Path) -> Optional[tuple[str, int]]:
    """Return (oid_hex, declared_size) if *path* is an LFS pointer, else None."""
    try:
        data = path.read_bytes()[:_MAX_STUB_BYTES + 50]  # slight buffer
    except (OSError, PermissionError):
        return None

    try:
        # The lfs_pointer module lives in kerf-core; import lazily so the CLI
        # works as a thin client even without kerf-core installed.
        from kerf_core.storage.lfs_pointer import parse, LfsPointerError  # noqa: PLC0415
    except ImportError:
        # Fallback: inline detection for thin-client installs without kerf-core.
        return _detect_stub_inline(data)

    try:
        result = parse(data)
        return result["oid"], result["size"]  # type: ignore[return-value]
    except Exception:
        return None


def _detect_stub_inline(data: bytes) -> Optional[tuple[str, int]]:
    """Inline LFS pointer detection — used when kerf-core is not installed."""
    import re

    pattern = re.compile(
        rb"^"
        rb"version https://git-lfs\.github\.com/spec/v1\n"
        rb"oid sha256:([0-9a-f]{64})\n"
        rb"size ([0-9]+)\n"
        rb"$",
    )
    m = pattern.fullmatch(data)
    if m is None:
        return None
    return m.group(1).decode(), int(m.group(2))


# ---------------------------------------------------------------------------
# Idempotency check
# ---------------------------------------------------------------------------

def _is_already_hydrated(path: Path, declared_size: int) -> bool:
    """Return True if the file looks like it has already been hydrated.

    A file is considered hydrated if:
    - It exists.
    - Its content does NOT match the LFS pointer format.
    - Its size matches the declared pointer size.
    """
    try:
        stat = path.stat()
    except OSError:
        return False
    if stat.st_size != declared_size:
        return False
    return _detect_stub(path) is None


# ---------------------------------------------------------------------------
# Project-id resolution
# ---------------------------------------------------------------------------

def _resolve_project_id() -> Optional[str]:
    """Try to infer the Kerf project-id from the working tree."""
    # 1. .kerf/project file
    kerf_project = Path(".kerf") / "project"
    if kerf_project.exists():
        pid = kerf_project.read_text(encoding="utf-8").strip()
        if pid:
            return pid

    # 2. git remote URL
    return _project_id_from_git_remote()


def _project_id_from_git_remote() -> Optional[str]:
    """Parse the origin remote URL for a kerf.sh project path."""
    import subprocess  # noqa: PLC0415
    import re  # noqa: PLC0415

    try:
        result = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode != 0:
            return None
        url = result.stdout.strip()
    except Exception:
        return None

    # kerf.sh/<workspace>/<project-slug>  or  https://kerf.sh/<w>/<p>
    m = re.search(r"kerf\.sh/[^/]+/([^/\s]+)", url)
    if m:
        return m.group(1)
    return None


# ---------------------------------------------------------------------------
# Blob fetch + atomic replace
# ---------------------------------------------------------------------------

def _hydrate_file(
    path: Path,
    oid: str,
    declared_size: int,
    project_id: str,
    api_url: str,
    token: str,
) -> tuple[bool, str]:
    """Fetch *oid* from the API and atomically replace *path*.

    Returns (success: bool, message: str).
    """
    # Check local cache first
    cached = _blob_cache_path(oid)
    if cached.exists():
        data = cached.read_bytes()
        actual_oid = hashlib.sha256(data).hexdigest()
        if actual_oid == oid:
            _atomic_replace(path, data)
            return True, "from cache"

    # Fetch from API with retries
    endpoint = f"{api_url}/api/projects/{project_id}/blobs/{oid}"
    last_error = ""
    delays = list(_RETRY_DELAYS)

    for attempt, delay in enumerate([(0, *delays)][0], start=1):
        if delay:
            time.sleep(delay)

        try:
            req = urllib.request.Request(
                endpoint,
                headers={"Authorization": f"Bearer {token}"},
            )
            with urllib.request.urlopen(req, timeout=120) as resp:
                data = resp.read()
        except urllib.error.HTTPError as exc:
            code = exc.code
            if code == 401:
                return False, f"auth failure (HTTP 401) — check KERF_API_TOKEN"
            if code == 403:
                return False, f"access denied (HTTP 403) — token lacks access to project {project_id!r}"
            if code == 404:
                return False, f"oid not found on server (HTTP 404)"
            if code == 410:
                return (
                    False,
                    "blob has been garbage-collected on the server. "
                    "Contact your workspace admin or restore from an earlier git commit.",
                )
            last_error = f"HTTP {code}"
            continue
        except urllib.error.URLError as exc:
            last_error = f"network error: {exc.reason}"
            continue
        except Exception as exc:  # noqa: BLE001
            last_error = str(exc)
            continue

        # Verify sha256
        actual_oid = hashlib.sha256(data).hexdigest()
        if actual_oid != oid:
            last_error = f"sha256 mismatch (got {actual_oid[:12]}…, expected {oid[:12]}…)"
            # Don't retry on checksum mismatch — data corruption, not transient
            return False, last_error

        # Atomic replace
        try:
            _atomic_replace(path, data)
        except OSError as exc:
            return False, f"write failed: {exc}"

        # Cache write
        _write_blob_cache(oid, data)

        return True, "ok"

    return False, last_error or "unknown error after retries"


def _atomic_replace(path: Path, data: bytes) -> None:
    """Write *data* to *path* atomically using a sibling temp file."""
    parent = path.parent
    fd, tmp = tempfile.mkstemp(dir=parent, prefix=".kerf_hydrate_")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


# ---------------------------------------------------------------------------
# Blob cache helpers
# ---------------------------------------------------------------------------

def _blob_cache_path(oid: str) -> Path:
    cache_dir = Path(os.environ.get("KERF_BLOB_CACHE_DIR", str(_BLOB_CACHE_DIR)))
    return cache_dir / oid


def _write_blob_cache(oid: str, data: bytes) -> None:
    cache_path = _blob_cache_path(oid)
    try:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=cache_path.parent, prefix=".kerf_cache_")
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        os.replace(tmp, cache_path)
    except OSError:
        pass  # cache writes are best-effort


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def _fmt_bytes(n: int) -> str:
    """Return a human-readable byte count string."""
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.1f} {unit}" if unit != "B" else f"{n} B"
        n /= 1024  # type: ignore[assignment]
    return f"{n:.1f} TB"
