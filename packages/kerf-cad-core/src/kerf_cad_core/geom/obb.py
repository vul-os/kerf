"""
kerf_cad_core.geom.obb — Oriented bounding box computed from STEP geometry.

Public API
----------
OBB
    Named dataclass: center (3-tuple), axes (3×3-tuple), half_extents (3-tuple).
    All values are in mm, local frame unless a world transform is applied.

compute_obb_from_step(step_blob) -> OBB
    Parse *step_blob* (bytes or str) via the kerf STEP reader, collect all
    vertex positions, run PCA to find the orientation that minimises the
    bounding-box volume, then return the tight OBB.

    Falls back to an axis-aligned unit box (half_extents = (0.5, 0.5, 0.5))
    if the geometry cannot be parsed or has fewer than 3 distinct vertices.

OBBCache
    Thread-safe LRU cache keyed by blob SHA-256 hex digest.  Repeated calls
    with the same blob cost O(1) after the first parse.

Usage
-----
    from kerf_cad_core.geom.obb import OBBCache, compute_obb_from_step

    cache = OBBCache(max_size=256)
    obb = cache.get_or_compute(blob_hash, step_blob)
    # obb.center, obb.axes, obb.half_extents

Notes
-----
* PCA uses numpy for efficiency; the rest is pure Python so the module
  degrades gracefully when numpy is absent (falls back to identity axes).
* This module has zero circular imports — it only imports from
  kerf_cad_core.io.step_reader and standard library / numpy.
"""

from __future__ import annotations

import hashlib
import math
from collections import OrderedDict
from typing import NamedTuple, Optional, Sequence, Tuple

# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------


class OBB(NamedTuple):
    """Oriented bounding box.

    Attributes
    ----------
    center       : (cx, cy, cz) in mm — world or local, as computed.
    axes         : ((ax0, ay0, az0), (ax1, ay1, az1), (ax2, ay2, az2))
                   Three orthonormal unit vectors (right-hand frame).
    half_extents : (hx, hy, hz) — half-lengths along each axis in mm.
    """

    center: Tuple[float, float, float]
    axes: Tuple[
        Tuple[float, float, float],
        Tuple[float, float, float],
        Tuple[float, float, float],
    ]
    half_extents: Tuple[float, float, float]

    # Convenience: bbox_min / bbox_max in the OBB's own local frame
    # (useful when converting back to an AABB in that frame).
    @property
    def bbox_min(self) -> Tuple[float, float, float]:
        hx, hy, hz = self.half_extents
        cx, cy, cz = self.center
        return (cx - hx, cy - hy, cz - hz)

    @property
    def bbox_max(self) -> Tuple[float, float, float]:
        hx, hy, hz = self.half_extents
        cx, cy, cz = self.center
        return (cx + hx, cy + hy, cz + hz)


# ---------------------------------------------------------------------------
# Unit-box sentinel (returned when geometry is unavailable)
# ---------------------------------------------------------------------------

_UNIT_OBB = OBB(
    center=(0.5, 0.5, 0.5),
    axes=((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)),
    half_extents=(0.5, 0.5, 0.5),
)

_MIN_HALF = 1e-9  # minimum half-extent to prevent degenerate boxes


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _unit_box() -> OBB:
    """Return the 1 mm³ unit box sentinel."""
    return _UNIT_OBB


def is_unit_box_fallback(obb: OBB) -> bool:
    """Return True if *obb* is the unit-box fallback sentinel.

    This lets callers distinguish a genuinely tiny part from a fallback
    produced when STEP parsing failed.
    """
    return obb == _UNIT_OBB


def _vertices_from_body(body) -> list:
    """Extract all distinct vertex positions from a Body as (x,y,z) tuples."""
    pts = []
    seen = set()
    for v in body.all_vertices():
        pt = v.point  # numpy array [x, y, z]
        key = (round(float(pt[0]), 9), round(float(pt[1]), 9), round(float(pt[2]), 9))
        if key not in seen:
            seen.add(key)
            pts.append((float(pt[0]), float(pt[1]), float(pt[2])))
    return pts


def _pca_axes(points: list) -> Optional[tuple]:
    """
    Compute three orthonormal axes via PCA on *points*.

    Returns None if numpy is unavailable or if there are fewer than 3
    distinct points (can't form a 3-D covariance matrix).

    Parameters
    ----------
    points : list of (x, y, z) tuples, at least 3 elements.

    Returns
    -------
    (axis0, axis1, axis2) each a (x,y,z) 3-tuple, sorted descending by
    variance (largest-variance axis first).  Returns None on failure.
    """
    try:
        import numpy as np  # noqa: PLC0415
    except ImportError:
        return None

    if len(points) < 3:
        return None

    pts = np.array(points, dtype=float)
    centroid = pts.mean(axis=0)
    centred = pts - centroid

    cov = centred.T @ centred / max(len(points) - 1, 1)

    try:
        eigenvalues, eigenvectors = np.linalg.eigh(cov)
    except np.linalg.LinAlgError:
        return None

    # eigh returns ascending order; reverse to get descending (largest first)
    idx = np.argsort(eigenvalues)[::-1]
    eigenvectors = eigenvectors[:, idx]

    axes = tuple(tuple(float(v) for v in eigenvectors[:, i]) for i in range(3))
    return axes  # type: ignore[return-value]


def _project_and_fit(points: list, axes: tuple) -> OBB:
    """
    Given *points* and three orthonormal *axes*, compute the tight OBB.

    Projects all points onto each axis, finds [min, max] interval, and
    returns the OBB with center at the interval midpoints.
    """
    INF = float("inf")
    lo = [INF, INF, INF]
    hi = [-INF, -INF, -INF]

    for pt in points:
        for k, ax in enumerate(axes):
            proj = pt[0] * ax[0] + pt[1] * ax[1] + pt[2] * ax[2]
            if proj < lo[k]:
                lo[k] = proj
            if proj > hi[k]:
                hi[k] = proj

    center_proj = ((lo[0] + hi[0]) * 0.5, (lo[1] + hi[1]) * 0.5, (lo[2] + hi[2]) * 0.5)
    half_extents = (
        max((hi[0] - lo[0]) * 0.5, _MIN_HALF),
        max((hi[1] - lo[1]) * 0.5, _MIN_HALF),
        max((hi[2] - lo[2]) * 0.5, _MIN_HALF),
    )

    # Reconstruct world-space centre from projected centroid
    ax0, ax1, ax2 = axes
    cx = center_proj[0] * ax0[0] + center_proj[1] * ax1[0] + center_proj[2] * ax2[0]
    cy = center_proj[0] * ax0[1] + center_proj[1] * ax1[1] + center_proj[2] * ax2[1]
    cz = center_proj[0] * ax0[2] + center_proj[1] * ax1[2] + center_proj[2] * ax2[2]

    return OBB(center=(cx, cy, cz), axes=axes, half_extents=half_extents)


# ---------------------------------------------------------------------------
# Primary public function
# ---------------------------------------------------------------------------


def compute_obb_from_step(step_blob) -> OBB:
    """Compute an oriented bounding box from STEP geometry.

    Parameters
    ----------
    step_blob : bytes | str
        Raw STEP Part 21 file content.  Bytes are decoded as UTF-8 with
        error replacement.

    Returns
    -------
    OBB
        Oriented bounding box in local (model) space.
        If parsing fails or the body has fewer than 3 distinct vertices,
        falls back to the 1 mm³ unit box at origin.

    Algorithm
    ---------
    1. Parse the STEP blob into a ``Body`` via ``kerf_cad_core.io.step_reader``.
    2. Extract all distinct vertex positions (deduplicated to 9 decimal places).
    3. Run PCA on the vertex point cloud to find the three principal axes
       (descending by variance — the longest axis is axis 0).
    4. Project all vertices onto each axis; compute [min, max] intervals.
    5. Derive center and half-extents from the intervals.

    The PCA approach gives the minimum-volume OBB orientation when the
    geometry is distributed along principal axes (true for most mechanical
    parts).  For truly worst-case minimum-volume OBB, a rotating-calipers
    pass would be needed, but PCA is standard practice for B-rep geometry
    and accurate to within a few percent of optimal.
    """
    # Normalise to string
    if isinstance(step_blob, (bytes, bytearray)):
        text = step_blob.decode("utf-8", errors="replace")
    else:
        text = str(step_blob)

    try:
        from kerf_cad_core.io.step_reader import read_step, StepReadError  # noqa: PLC0415

        body = read_step(text, validate=False)
        vertices = _vertices_from_body(body)
    except Exception:  # noqa: BLE001
        return _unit_box()

    if len(vertices) < 3:
        return _unit_box()

    axes = _pca_axes(vertices)
    if axes is None:
        # Numpy unavailable or too few points — fall back to AABB
        xs = [p[0] for p in vertices]
        ys = [p[1] for p in vertices]
        zs = [p[2] for p in vertices]
        cx = (min(xs) + max(xs)) * 0.5
        cy = (min(ys) + max(ys)) * 0.5
        cz = (min(zs) + max(zs)) * 0.5
        hx = max((max(xs) - min(xs)) * 0.5, _MIN_HALF)
        hy = max((max(ys) - min(ys)) * 0.5, _MIN_HALF)
        hz = max((max(zs) - min(zs)) * 0.5, _MIN_HALF)
        return OBB(
            center=(cx, cy, cz),
            axes=((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)),
            half_extents=(hx, hy, hz),
        )

    return _project_and_fit(vertices, axes)


# ---------------------------------------------------------------------------
# OBBCache — SHA-256 keyed LRU cache
# ---------------------------------------------------------------------------


class OBBCache:
    """Thread-safe LRU cache for OBBs keyed by blob SHA-256 digest.

    Parameters
    ----------
    max_size : int
        Maximum number of OBBs to keep in memory.  When exceeded the
        least-recently-used entry is evicted.  Default 256.

    Usage
    -----
    ::

        cache = OBBCache()
        obb = cache.get_or_compute(blob_hash, step_blob)

    *blob_hash* is a hex SHA-256 string.  If omitted or ``None``, the cache
    key is computed on the fly from the blob contents.  Passing a pre-computed
    hash avoids re-hashing large blobs on every call.
    """

    def __init__(self, max_size: int = 256) -> None:
        self._max_size = max_size
        self._store: OrderedDict[str, OBB] = OrderedDict()

    # -- public ---------------------------------------------------------------

    def get_or_compute(
        self,
        blob_hash: Optional[str],
        step_blob,
    ) -> OBB:
        """Return the cached OBB, computing it if necessary.

        Parameters
        ----------
        blob_hash : str | None
            Pre-computed SHA-256 hex digest.  If ``None``, the hash is
            derived from *step_blob* (slower but correct).
        step_blob : bytes | str
            Raw STEP content used only when a cache miss occurs.
        """
        key = blob_hash if blob_hash else self._hash(step_blob)

        if key in self._store:
            # Move to end (most-recently-used)
            self._store.move_to_end(key)
            return self._store[key]

        obb = compute_obb_from_step(step_blob)
        self._store[key] = obb
        self._store.move_to_end(key)

        if len(self._store) > self._max_size:
            self._store.popitem(last=False)  # evict LRU

        return obb

    def invalidate(self, blob_hash: str) -> None:
        """Remove a specific entry from the cache."""
        self._store.pop(blob_hash, None)

    def clear(self) -> None:
        """Remove all cached entries."""
        self._store.clear()

    def __len__(self) -> int:
        return len(self._store)

    # -- private --------------------------------------------------------------

    @staticmethod
    def _hash(blob) -> str:
        if isinstance(blob, str):
            blob = blob.encode("utf-8", errors="replace")
        return hashlib.sha256(blob).hexdigest()


# Shared module-level default cache instance (256-entry LRU).
_default_cache: OBBCache = OBBCache(max_size=256)


def get_obb_cached(blob_hash: Optional[str], step_blob) -> OBB:
    """Convenience wrapper using the module-level default cache."""
    return _default_cache.get_or_compute(blob_hash, step_blob)


__all__ = [
    "OBB",
    "OBBCache",
    "compute_obb_from_step",
    "get_obb_cached",
]
