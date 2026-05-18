"""kerf-render: content-addressed render cache with LRU eviction.

Provides :class:`CyclesCache` — an in-process, content-addressed lookup table
that maps ``sha256(scene_glb + samples_str + resolution_str)`` to a cached
output file path (or signed URL).  Entries are evicted in least-recently-used
(LRU) order once ``max_entries`` is exceeded.

The cache is intentionally decoupled from :mod:`kerf_render.cycles_worker` so
it can be tested, replaced, or extended (e.g. with a Redis backend) without
touching the worker harness.

Quick-start
-----------
::

    from kerf_render.cycles_cache import CyclesCache

    cache = CyclesCache(max_entries=128)

    key = cache.key(scene_glb=b"...", samples=256, resolution=(1920, 1080))
    hit = cache.lookup(key)        # None on miss
    cache.store(key, "/tmp/out.png")
    assert cache.lookup(key) == "/tmp/out.png"
"""

from __future__ import annotations

import hashlib
import threading
from collections import OrderedDict
from typing import Optional


# ---------------------------------------------------------------------------
# Default LRU capacity
# ---------------------------------------------------------------------------

_DEFAULT_MAX_ENTRIES = 256


# ---------------------------------------------------------------------------
# Content-addressed key helper
# ---------------------------------------------------------------------------


def make_cache_key(
    *,
    scene_glb: bytes,
    samples: int,
    resolution: tuple,
    translator_version: str = "T-106a-v1",
) -> str:
    """Return a hex SHA-256 key for the given render inputs.

    Parameters
    ----------
    scene_glb:
        Raw GLB bytes of the scene.
    samples:
        Number of path-tracing samples.
    resolution:
        ``(width, height)`` tuple.
    translator_version:
        Version sentinel from the cycles-translator; bump to invalidate old
        cache entries when the translator output format changes.

    Returns
    -------
    str
        64-character lowercase hex SHA-256 digest.
    """
    h = hashlib.sha256()
    h.update(scene_glb)
    h.update(str(samples).encode())
    h.update(f"{resolution[0]}x{resolution[1]}".encode())
    h.update(translator_version.encode())
    return h.hexdigest()


# ---------------------------------------------------------------------------
# LRU cache
# ---------------------------------------------------------------------------


class CyclesCache:
    """Thread-safe, in-process, content-addressed render cache with LRU eviction.

    Parameters
    ----------
    max_entries:
        Maximum number of entries before the least-recently-used entry is
        evicted.  Defaults to 256.
    """

    def __init__(self, max_entries: int = _DEFAULT_MAX_ENTRIES) -> None:
        if max_entries < 1:
            raise ValueError("max_entries must be >= 1")
        self._max = max_entries
        # OrderedDict preserves insertion/access order for LRU tracking.
        self._store: OrderedDict[str, str] = OrderedDict()
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def key(
        self,
        *,
        scene_glb: bytes,
        samples: int,
        resolution: tuple,
        translator_version: str = "T-106a-v1",
    ) -> str:
        """Compute the content-addressed cache key for render inputs.

        Delegates to the module-level :func:`make_cache_key`; exposed as an
        instance method so callers can sub-class and override the hashing
        strategy without touching module-level state.
        """
        return make_cache_key(
            scene_glb=scene_glb,
            samples=samples,
            resolution=resolution,
            translator_version=translator_version,
        )

    def lookup(self, key: str) -> Optional[str]:
        """Return the cached output path / URL for *key*, or ``None`` on miss.

        Accessing an entry promotes it to most-recently-used.
        """
        with self._lock:
            if key not in self._store:
                return None
            # Move to end (most-recently-used)
            self._store.move_to_end(key)
            return self._store[key]

    def store(self, key: str, value: str) -> None:
        """Insert or update *key* → *value* and evict LRU entry if over capacity.

        Parameters
        ----------
        key:
            Content-addressed cache key (typically the hex SHA-256 digest).
        value:
            Output file path or signed URL to cache.
        """
        with self._lock:
            if key in self._store:
                # Refresh position
                self._store.move_to_end(key)
                self._store[key] = value
            else:
                self._store[key] = value
                # Evict oldest entry when over capacity
                while len(self._store) > self._max:
                    self._store.popitem(last=False)

    def evict(self, key: str) -> bool:
        """Explicitly remove *key* from the cache.

        Returns
        -------
        bool
            ``True`` if the entry was present and removed; ``False`` otherwise.
        """
        with self._lock:
            if key in self._store:
                del self._store[key]
                return True
            return False

    def clear(self) -> None:
        """Remove all entries from the cache."""
        with self._lock:
            self._store.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._store)

    def __contains__(self, key: str) -> bool:
        with self._lock:
            return key in self._store


__all__ = [
    "make_cache_key",
    "CyclesCache",
]
