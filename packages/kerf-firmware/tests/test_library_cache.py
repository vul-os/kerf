"""
test_library_cache.py
---------------------
Pytest suite for kerf_firmware.library_cache.

Covers:
  - Cache hit on second download (no real HTTP — uses store() API)
  - SHA-256 verification: mismatch raises Sha256Mismatch
  - Dedup across projects: same content → same physical path
  - LRU eviction removes least-recently-used objects
  - Symlink lookup via (name, version)
  - Dangling symlink cleanup
"""

from __future__ import annotations

import hashlib
import os
import time
import urllib.error
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from kerf_firmware.library_cache import LibraryCache, Sha256Mismatch


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def cache(tmp_path) -> LibraryCache:
    """A LibraryCache backed by a temporary directory."""
    return LibraryCache(cache_dir=tmp_path / "cache")


# ---------------------------------------------------------------------------
# store() — in-process store without network I/O
# ---------------------------------------------------------------------------

class TestStore:
    def test_store_returns_path(self, cache):
        data = b"hello world"
        path = cache.store(data)
        assert path.exists()
        assert path.read_bytes() == data

    def test_store_content_addressed(self, cache):
        data = b"same bytes"
        path1 = cache.store(data)
        path2 = cache.store(data)
        assert path1 == path2  # identical object, same path

    def test_store_sha256_correct_passes(self, cache):
        data = b"verify me"
        path = cache.store(data, sha256_expected=_sha256(data))
        assert path.exists()

    def test_store_sha256_mismatch_raises(self, cache):
        data = b"real data"
        with pytest.raises(Sha256Mismatch):
            cache.store(data, sha256_expected="0" * 64)

    def test_store_with_name_version_creates_index_link(self, cache):
        data = b"lib content"
        path = cache.store(data, name="FastLED", version="3.6.0")
        link = cache._index_path("FastLED", "3.6.0")
        assert link.is_symlink()
        assert link.resolve() == path.resolve()


# ---------------------------------------------------------------------------
# lookup()
# ---------------------------------------------------------------------------

class TestLookup:
    def test_lookup_miss_returns_none(self, cache):
        assert cache.lookup("Unknown", "0.0.0") is None

    def test_lookup_hit_after_store(self, cache):
        data = b"lib bytes"
        stored = cache.store(data, name="ArduinoJson", version="6.21.3")
        found = cache.lookup("ArduinoJson", "6.21.3")
        assert found is not None
        assert found.resolve() == stored.resolve()

    def test_lookup_dangling_symlink_returns_none(self, cache, tmp_path):
        # Create a symlink pointing at a non-existent file
        link = cache._index_path("Ghost", "1.0.0")
        link.parent.mkdir(parents=True, exist_ok=True)
        link.symlink_to("/nonexistent/path/xyz")
        assert cache.lookup("Ghost", "1.0.0") is None
        # Dangling link should have been cleaned up
        assert not link.exists()


# ---------------------------------------------------------------------------
# download() — mocked HTTP
# ---------------------------------------------------------------------------

class TestDownload:
    """Tests for download() using a mocked urllib.request.urlopen."""

    def _make_mock_response(self, data: bytes):
        """Return a context-manager mock that yields bytes."""
        import io
        mock_resp = MagicMock()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_resp.read = MagicMock(side_effect=lambda n=-1: data if n == -1 else data[:n])
        # Make it work with shutil.copyfileobj (reads in chunks)
        mock_resp.read = MagicMock(return_value=data)
        # Provide an iterable for shutil.copyfileobj
        buf = io.BytesIO(data)
        mock_resp.read = buf.read
        return mock_resp

    @patch("urllib.request.urlopen")
    def test_download_stores_content(self, mock_urlopen, cache):
        data = b"firmware library bytes"
        mock_urlopen.return_value = self._make_mock_response(data)
        path = cache.download("https://example.com/lib.zip")
        assert path.exists()
        assert path.read_bytes() == data

    @patch("urllib.request.urlopen")
    def test_download_second_call_is_cached_no_network(self, mock_urlopen, cache):
        """Second download with the same sha256 must NOT hit the network."""
        data = b"cached content"
        mock_urlopen.return_value = self._make_mock_response(data)
        sha = _sha256(data)

        path1 = cache.download("https://example.com/lib.zip", sha256_expected=sha)
        assert mock_urlopen.call_count == 1

        # Second call: sha256 is known; object already on disk → skip HTTP
        path2 = cache.download("https://example.com/lib.zip", sha256_expected=sha)
        assert mock_urlopen.call_count == 1  # no additional call
        assert path1 == path2

    @patch("urllib.request.urlopen")
    def test_download_sha256_mismatch_raises(self, mock_urlopen, cache):
        data = b"real bytes"
        mock_urlopen.return_value = self._make_mock_response(data)
        with pytest.raises(Sha256Mismatch):
            cache.download("https://example.com/bad.zip", sha256_expected="0" * 64)

    @patch("urllib.request.urlopen")
    def test_download_creates_index_symlink(self, mock_urlopen, cache):
        data = b"named lib"
        mock_urlopen.return_value = self._make_mock_response(data)
        path = cache.download(
            "https://example.com/fastled.zip",
            name="FastLED",
            version="3.6.0",
        )
        found = cache.lookup("FastLED", "3.6.0")
        assert found is not None
        assert found.resolve() == path.resolve()


# ---------------------------------------------------------------------------
# Dedup test
# ---------------------------------------------------------------------------

class TestDedup:
    def test_two_projects_same_content_share_one_file(self, cache):
        """
        Simulates two projects storing the same library bytes.
        Both should resolve to the identical on-disk path.
        """
        data = b"FastLED 3.6.0 archive bytes"
        sha = _sha256(data)

        path_proj_a = cache.store(data, sha256_expected=sha, name="FastLED", version="3.6.0")
        path_proj_b = cache.store(data, sha256_expected=sha, name="FastLED", version="3.6.0")

        # Both must be the same physical file
        assert path_proj_a == path_proj_b
        # Only one object file on disk
        objects = list(cache._objects_dir.iterdir())
        assert len([f for f in objects if not f.name.startswith(".")]) == 1


# ---------------------------------------------------------------------------
# LRU eviction
# ---------------------------------------------------------------------------

class TestLruEviction:
    def test_evict_removes_oldest_when_over_limit(self, cache):
        # Store two objects with different mtimes
        older_data = b"older library content"
        newer_data = b"newer library content"

        older_path = cache.store(older_data)
        time.sleep(0.01)  # ensure distinct atime
        newer_path = cache.store(newer_data)

        # Force older to have an earlier atime
        old_atime = older_path.stat().st_atime - 10
        os.utime(older_path, (old_atime, older_path.stat().st_mtime))

        total = older_path.stat().st_size + newer_path.stat().st_size
        # Set limit just above the newer object so eviction removes the older one
        limit = newer_path.stat().st_size + 1

        removed = cache.evict_lru(limit)
        assert _sha256(older_data) in removed
        assert not older_path.exists()
        assert newer_path.exists()

    def test_evict_does_nothing_when_under_limit(self, cache):
        data = b"small content"
        path = cache.store(data)
        removed = cache.evict_lru(10 * 1024 * 1024)  # 10 MB limit
        assert removed == []
        assert path.exists()

    def test_evict_removes_index_links(self, cache):
        data = b"evictable library"
        path = cache.store(data, name="OldLib", version="1.0.0")
        sha = _sha256(data)

        # Force atime to the past
        os.utime(path, (0, path.stat().st_mtime))

        cache.evict_lru(0)  # evict everything
        assert not path.exists()
        # Index symlink should also be gone (or dangling)
        assert cache.lookup("OldLib", "1.0.0") is None


# ---------------------------------------------------------------------------
# Default cache dir
# ---------------------------------------------------------------------------

class TestDefaultCacheDir:
    def test_default_cache_dir_uses_home(self, monkeypatch, tmp_path):
        monkeypatch.setenv("HOME", str(tmp_path))
        # Patch Path.home() to use our tmp dir
        monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))
        c = LibraryCache()
        assert str(c.cache_dir).startswith(str(tmp_path))
