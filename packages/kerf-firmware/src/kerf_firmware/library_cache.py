"""
library_cache.py
----------------
Content-addressed local library cache for kerf-firmware.

Layout on disk::

    <cache_dir>/
        objects/
            <sha256>/
                <file_or_archive>          # single physical copy
        index/
            <name>/<version>               # symlink → ../objects/<sha256>/…

Design principles
-----------------
* **Content-addressed** — the key for the objects store is the SHA-256 of the
  downloaded bytes.  Two user projects pinning an identical version of a
  library share one physical file on disk.
* **Atomic downloads** — bytes are written to a temp file in the same directory
  and renamed into place so a partial download never corrupts the store.
* **SHA-256 verification** — when the caller supplies ``sha256_expected``, the
  downloaded content is rejected if it does not match.
* **Symlink dedup** — the ``index/<name>/<version>`` symlink tree lets callers
  look up by human-readable coordinates without re-downloading.
* **LRU eviction** — ``evict_lru(max_bytes)`` removes the least-recently-used
  objects until the cache fits within ``max_bytes``.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import tempfile
import time
import urllib.request
from pathlib import Path
from typing import Optional


class Sha256Mismatch(Exception):
    """Raised when a downloaded file's SHA-256 does not match the expected value."""


class LibraryCache:
    """
    Content-addressed local library cache.

    Parameters
    ----------
    cache_dir:
        Root directory for the cache.  Defaults to ``~/.kerf/firmware-libs``.
        Created automatically if it does not exist.
    """

    def __init__(self, cache_dir: Optional[str | Path] = None) -> None:
        if cache_dir is None:
            cache_dir = Path.home() / ".kerf" / "firmware-libs"
        self.cache_dir = Path(cache_dir)
        self._objects_dir = self.cache_dir / "objects"
        self._index_dir = self.cache_dir / "index"
        self._objects_dir.mkdir(parents=True, exist_ok=True)
        self._index_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _object_path(self, sha256: str) -> Path:
        """Return the on-disk path for a given SHA-256 hash."""
        return self._objects_dir / sha256

    def _index_path(self, name: str, version: str) -> Path:
        """Return the index symlink path for a (name, version) pair."""
        return self._index_dir / name / version

    @staticmethod
    def _sha256_of_file(path: Path) -> str:
        h = hashlib.sha256()
        with path.open("rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 16), b""):
                h.update(chunk)
        return h.hexdigest()

    @staticmethod
    def _sha256_of_bytes(data: bytes) -> str:
        return hashlib.sha256(data).hexdigest()

    # ------------------------------------------------------------------
    # Core operations
    # ------------------------------------------------------------------

    def download(
        self,
        url: str,
        sha256_expected: Optional[str] = None,
        name: Optional[str] = None,
        version: Optional[str] = None,
    ) -> Path:
        """
        Download *url* into the content-addressed store.

        If the content is already present (keyed by SHA-256), the download is
        skipped and the existing path is returned immediately.

        Parameters
        ----------
        url:
            HTTP/HTTPS URL to fetch.
        sha256_expected:
            Optional expected SHA-256 hex digest.  When supplied, the
            downloaded bytes must match; a :class:`Sha256Mismatch` is raised
            otherwise.
        name / version:
            When both are supplied a ``index/<name>/<version>`` symlink is
            created pointing at the object.

        Returns
        -------
        Path
            Absolute path to the cached file.
        """
        # If sha256_expected is known we can short-circuit before downloading.
        if sha256_expected:
            existing = self._object_path(sha256_expected)
            if existing.exists():
                _touch(existing)
                if name and version:
                    self._make_index_link(name, version, existing)
                return existing

        # Download to a temp file in the objects dir so the rename is atomic.
        tmp_fd, tmp_name = tempfile.mkstemp(dir=self._objects_dir, prefix=".dl-")
        tmp_path = Path(tmp_name)
        try:
            with os.fdopen(tmp_fd, "wb") as fh:
                with urllib.request.urlopen(url) as resp:  # noqa: S310
                    shutil.copyfileobj(resp, fh)

            actual_sha256 = self._sha256_of_file(tmp_path)

            if sha256_expected and actual_sha256 != sha256_expected:
                tmp_path.unlink(missing_ok=True)
                raise Sha256Mismatch(
                    f"SHA-256 mismatch for {url!r}: "
                    f"expected {sha256_expected!r}, got {actual_sha256!r}"
                )

            dest = self._object_path(actual_sha256)
            if dest.exists():
                # Another concurrent download beat us here; discard ours.
                tmp_path.unlink(missing_ok=True)
                _touch(dest)
            else:
                tmp_path.rename(dest)

            if name and version:
                self._make_index_link(name, version, dest)
            return dest

        except Exception:
            tmp_path.unlink(missing_ok=True)
            raise

    def lookup(self, name: str, version: str) -> Optional[Path]:
        """
        Return the cached path for a (name, version) pair, or ``None``.

        Parameters
        ----------
        name:
            Library name.
        version:
            Library version string.

        Returns
        -------
        Path | None
        """
        link = self._index_path(name, version)
        if not link.exists():
            return None
        # Resolve symlink to real object path
        try:
            resolved = link.resolve()
        except OSError:
            return None
        if resolved.exists():
            _touch(resolved)
            return resolved
        # Dangling symlink — clean up
        try:
            link.unlink()
        except OSError:
            pass
        return None

    def store(self, data: bytes, sha256_expected: Optional[str] = None,
              name: Optional[str] = None, version: Optional[str] = None) -> Path:
        """
        Store raw bytes directly (without downloading from a URL).

        Useful in tests and when the caller has already retrieved the data.
        Returns the path to the stored object.
        """
        actual_sha256 = self._sha256_of_bytes(data)
        if sha256_expected and actual_sha256 != sha256_expected:
            raise Sha256Mismatch(
                f"SHA-256 mismatch: expected {sha256_expected!r}, got {actual_sha256!r}"
            )
        dest = self._object_path(actual_sha256)
        if not dest.exists():
            # Atomic write
            tmp_fd, tmp_name = tempfile.mkstemp(dir=self._objects_dir, prefix=".store-")
            tmp_path = Path(tmp_name)
            try:
                with os.fdopen(tmp_fd, "wb") as fh:
                    fh.write(data)
                tmp_path.rename(dest)
            except Exception:
                tmp_path.unlink(missing_ok=True)
                raise
        else:
            _touch(dest)

        if name and version:
            self._make_index_link(name, version, dest)
        return dest

    # ------------------------------------------------------------------
    # Index / symlink helpers
    # ------------------------------------------------------------------

    def _make_index_link(self, name: str, version: str, target: Path) -> None:
        link = self._index_path(name, version)
        link.parent.mkdir(parents=True, exist_ok=True)
        if link.is_symlink() or link.exists():
            # Already points somewhere — leave it if it resolves to the same target
            try:
                if link.resolve() == target.resolve():
                    return
                link.unlink()
            except OSError:
                return
        # Use a relative symlink so the cache dir is relocatable
        try:
            rel = os.path.relpath(target, link.parent)
            link.symlink_to(rel)
        except OSError:
            # Fall back to absolute symlink (e.g. on Windows without symlink privilege)
            link.symlink_to(target)

    # ------------------------------------------------------------------
    # LRU eviction
    # ------------------------------------------------------------------

    def evict_lru(self, max_bytes: int) -> list[str]:
        """
        Remove least-recently-used objects until the objects store is at most
        ``max_bytes`` in total size.

        Returns a list of removed SHA-256 hashes.
        """
        objects = sorted(
            self._objects_dir.iterdir(),
            key=lambda p: p.stat().st_atime,
        )
        total_bytes = sum(p.stat().st_size for p in objects if p.is_file())
        removed: list[str] = []

        for obj in objects:
            if total_bytes <= max_bytes:
                break
            if obj.is_file() and not obj.name.startswith("."):
                size = obj.stat().st_size
                sha256 = obj.name
                obj.unlink()
                total_bytes -= size
                removed.append(sha256)
                # Remove dangling index symlinks that pointed to this object
                self._purge_index_links(sha256)

        return removed

    def _purge_index_links(self, sha256: str) -> None:
        """Remove any index symlinks whose target was the given object."""
        for name_dir in self._index_dir.iterdir():
            if not name_dir.is_dir():
                continue
            for ver_link in name_dir.iterdir():
                if ver_link.is_symlink():
                    try:
                        if sha256 in str(ver_link.resolve()):
                            ver_link.unlink()
                    except OSError:
                        pass


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------

def _touch(path: Path) -> None:
    """Update the access time of *path* (LRU tracking)."""
    try:
        now = time.time()
        os.utime(path, (now, path.stat().st_mtime))
    except OSError:
        pass
