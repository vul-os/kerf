"""sdf_csg.py — GK-P22: SDF CSG operations + marching-cubes mesh extraction.

Provides smooth-union / subtract / intersect on SDF scalar fields and a
marching-cubes surface extractor.  Closes the implicit-modelling loop
(ZBrush DynaMesh, Blender geometry-nodes SDF parity).

Public API
----------
SdfField
    Wraps a callable ``f(x, y, z) -> float`` as a signed distance field.
    Supports arithmetic operators (|, &, -, +) for CSG composition.

sdf_sphere(cx, cy, cz, r) -> SdfField
    SDF of a sphere centred at (cx, cy, cz) with radius r.

sdf_box(cx, cy, cz, hx, hy, hz) -> SdfField
    SDF of an axis-aligned box centred at (cx, cy, cz) with half-extents.

sdf_cylinder(cx, cy, cz, r, h) -> SdfField
    SDF of an infinite cylinder along Z, capped by half-height h.

sdf_union(a, b, k=0.0) -> SdfField
    Smooth union (k=0 → exact union, k>0 → smooth blend radius).

sdf_subtract(a, b, k=0.0) -> SdfField
    Smooth subtraction of b from a.

sdf_intersect(a, b, k=0.0) -> SdfField
    Smooth intersection of a and b.

marching_cubes(sdf, bounds, resolution, isovalue=0.0)
    -> dict {"vertices": list[list[float]], "faces": list[list[int]]}
    Extract a triangulated iso-surface from an SdfField using the
    Lorensen-Cline marching-cubes algorithm (pure Python + NumPy).

Notes
-----
* Pure Python + NumPy only; no OCCT, no external marching-cubes library.
* Smooth-blend uses the exponential smoothing formula (Inigo Quilez):
      smooth_min(a, b, k) = -k * log(exp(-a/k) + exp(-b/k))
* Marching-cubes uses the standard 256-entry lookup table (compact form).
* Never raises; returns empty mesh on any error.
"""
from __future__ import annotations

import math
from typing import Callable, Dict, List, Optional, Sequence, Tuple

import numpy as np


# ---------------------------------------------------------------------------
# SdfField
# ---------------------------------------------------------------------------


class SdfField:
    """Wraps a Python callable ``f(x, y, z) -> float`` as an SDF.

    Supports arithmetic operators for CSG composition:
        a | b  →  sdf_union(a, b)       (exact)
        a & b  →  sdf_intersect(a, b)   (exact)
        -a     →  negation (flip inside/outside)
        a - b  →  sdf_subtract(a, b)    (exact)
    """

    def __init__(self, fn: Callable[[float, float, float], float]) -> None:
        self._fn = fn

    def __call__(self, x: float, y: float, z: float) -> float:
        return float(self._fn(x, y, z))

    def __or__(self, other: "SdfField") -> "SdfField":
        return sdf_union(self, other)

    def __and__(self, other: "SdfField") -> "SdfField":
        return sdf_intersect(self, other)

    def __sub__(self, other: "SdfField") -> "SdfField":
        return sdf_subtract(self, other)

    def __neg__(self) -> "SdfField":
        return SdfField(lambda x, y, z: -self(x, y, z))

    def sample_grid(
        self,
        bounds: Tuple[float, float, float, float, float, float],
        resolution: int,
    ) -> np.ndarray:
        """Sample this SDF on a regular grid.

        Parameters
        ----------
        bounds : (xmin, ymin, zmin, xmax, ymax, zmax)
        resolution : int
            Number of samples per axis.

        Returns
        -------
        np.ndarray, shape (resolution, resolution, resolution)
        """
        xmin, ymin, zmin, xmax, ymax, zmax = bounds
        xs = np.linspace(xmin, xmax, resolution)
        ys = np.linspace(ymin, ymax, resolution)
        zs = np.linspace(zmin, zmax, resolution)
        grid = np.empty((resolution, resolution, resolution), dtype=float)
        fn = self._fn
        for i, x in enumerate(xs):
            for j, y in enumerate(ys):
                for k, z in enumerate(zs):
                    grid[i, j, k] = fn(x, y, z)
        return grid


# ---------------------------------------------------------------------------
# Primitive SDF factories
# ---------------------------------------------------------------------------


def sdf_sphere(cx: float, cy: float, cz: float, r: float) -> SdfField:
    """SDF of a sphere centred at (cx, cy, cz) with radius r."""
    cx, cy, cz, r = float(cx), float(cy), float(cz), float(r)

    def _fn(x: float, y: float, z: float) -> float:
        return math.sqrt((x - cx) ** 2 + (y - cy) ** 2 + (z - cz) ** 2) - r

    return SdfField(_fn)


def sdf_box(
    cx: float, cy: float, cz: float,
    hx: float, hy: float, hz: float,
) -> SdfField:
    """SDF of an axis-aligned box centred at (cx, cy, cz) with half-extents."""
    cx, cy, cz = float(cx), float(cy), float(cz)
    hx, hy, hz = float(hx), float(hy), float(hz)

    def _fn(x: float, y: float, z: float) -> float:
        dx = abs(x - cx) - hx
        dy = abs(y - cy) - hy
        dz = abs(z - cz) - hz
        outside = math.sqrt(
            max(dx, 0.0) ** 2 + max(dy, 0.0) ** 2 + max(dz, 0.0) ** 2
        )
        inside = min(max(dx, dy, dz), 0.0)
        return outside + inside

    return SdfField(_fn)


def sdf_cylinder(
    cx: float, cy: float, cz: float,
    r: float, h: float,
) -> SdfField:
    """SDF of a finite cylinder along Z, centred at (cx, cy, cz).

    The cylinder has radius r and extends ±h/2 along Z.
    """
    cx, cy, cz = float(cx), float(cy), float(cz)
    r, h = float(r), float(h)
    half_h = h / 2.0

    def _fn(x: float, y: float, z: float) -> float:
        # Radial distance in XY plane
        rho = math.sqrt((x - cx) ** 2 + (y - cy) ** 2)
        # 2D box SDF in (rho, z) space
        dx = rho - r
        dz = abs(z - cz) - half_h
        outside = math.sqrt(max(dx, 0.0) ** 2 + max(dz, 0.0) ** 2)
        inside = min(max(dx, dz), 0.0)
        return outside + inside

    return SdfField(_fn)


# ---------------------------------------------------------------------------
# CSG operations (smooth and exact)
# ---------------------------------------------------------------------------


def _smooth_min(a: float, b: float, k: float) -> float:
    """Inigo Quilez exponential smooth-min.

    k = 0 → exact min.
    k > 0 → smooth blend over radius ~k.
    """
    if k <= 0.0:
        return min(a, b)
    # Clamp to avoid overflow in exp
    res = -k * math.log(
        math.exp(-max(-50.0, min(50.0, a / k))) +
        math.exp(-max(-50.0, min(50.0, b / k)))
    )
    return res


def _smooth_max(a: float, b: float, k: float) -> float:
    """Smooth max (dual of smooth min)."""
    return -_smooth_min(-a, -b, k)


def sdf_union(a: SdfField, b: SdfField, k: float = 0.0) -> SdfField:
    """Smooth union of two SDF fields.

    k=0 → exact union; k>0 → smooth blend of radius k.
    """
    k = float(k)

    def _fn(x: float, y: float, z: float) -> float:
        return _smooth_min(a(x, y, z), b(x, y, z), k)

    return SdfField(_fn)


def sdf_subtract(a: SdfField, b: SdfField, k: float = 0.0) -> SdfField:
    """Smooth subtraction of b from a (a minus b).

    k=0 → exact subtraction; k>0 → smooth blend.
    """
    k = float(k)

    def _fn(x: float, y: float, z: float) -> float:
        return _smooth_max(a(x, y, z), -b(x, y, z), k)

    return SdfField(_fn)


def sdf_intersect(a: SdfField, b: SdfField, k: float = 0.0) -> SdfField:
    """Smooth intersection of two SDF fields.

    k=0 → exact intersection; k>0 → smooth blend.
    """
    k = float(k)

    def _fn(x: float, y: float, z: float) -> float:
        return _smooth_max(a(x, y, z), b(x, y, z), k)

    return SdfField(_fn)


# ---------------------------------------------------------------------------
# Marching cubes
# ---------------------------------------------------------------------------

# Marching-cubes edge table and triangle table.
# These are the standard Lorensen-Cline 1987 tables.
# _MC_EDGE_TABLE[i]: bitmask of which edges are intersected for cube config i.
# _MC_TRI_TABLE[i]:  list of edge index triples (or -1 terminator).

_MC_EDGE_TABLE = [
    0x0,0x109,0x203,0x30a,0x406,0x50f,0x605,0x70c,
    0x80c,0x905,0xa0f,0xb06,0xc0a,0xd03,0xe09,0xf00,
    0x190,0x99,0x393,0x29a,0x596,0x49f,0x795,0x69c,
    0x99c,0x895,0xb9f,0xa96,0xd9a,0xc93,0xf99,0xe90,
    0x230,0x339,0x33,0x13a,0x636,0x73f,0x435,0x53c,
    0xa3c,0xb35,0x83f,0x936,0xe3a,0xf33,0xc39,0xd30,
    0x3a0,0x2a9,0x1a3,0xaa,0x7a6,0x6af,0x5a5,0x4ac,
    0xbac,0xaa5,0x9af,0x8a6,0xfaa,0xea3,0xda9,0xca0,
    0x460,0x569,0x663,0x76a,0x66,0x16f,0x265,0x36c,
    0xc6c,0xd65,0xe6f,0xf66,0x86a,0x963,0xa69,0xb60,
    0x5f0,0x4f9,0x7f3,0x6fa,0x1f6,0xff,0x3f5,0x2fc,
    0xdfc,0xcf5,0xfff,0xef6,0x9fa,0x8f3,0xbf9,0xaf0,
    0x650,0x759,0x453,0x55a,0x256,0x35f,0x55,0x15c,
    0xe5c,0xf55,0xc5f,0xd56,0xa5a,0xb53,0x859,0x950,
    0x7c0,0x6c9,0x5c3,0x4ca,0x3c6,0x2cf,0x1c5,0xcc,
    0xfcc,0xec5,0xdcf,0xcc6,0xbca,0xac3,0x9c9,0x8c0,
    0x8c0,0x9c9,0xac3,0xbca,0xcc6,0xdcf,0xec5,0xfcc,
    0xcc,0x1c5,0x2cf,0x3c6,0x4ca,0x5c3,0x6c9,0x7c0,
    0x950,0x859,0xb53,0xa5a,0xd56,0xc5f,0xf55,0xe5c,
    0x15c,0x55,0x35f,0x256,0x55a,0x453,0x759,0x650,
    0xaf0,0xbf9,0x8f3,0x9fa,0xef6,0xfff,0xcf5,0xdfc,
    0x2fc,0x3f5,0xff,0x1f6,0x6fa,0x7f3,0x4f9,0x5f0,
    0xb60,0xa69,0x963,0x86a,0xf66,0xe6f,0xd65,0xc6c,
    0x36c,0x265,0x16f,0x66,0x76a,0x663,0x569,0x460,
    0xca0,0xda9,0xea3,0xfaa,0x8a6,0x9af,0xaa5,0xbac,
    0x4ac,0x5a5,0x6af,0x7a6,0xaa,0x1a3,0x2a9,0x3a0,
    0xd30,0xc39,0xf33,0xe3a,0x936,0x835,0xb3f,0xa36,  # Fixed: a36 not a3f... kept original
    0x53c,0x435,0x73f,0x636,0x13a,0x33,0x339,0x230,
    0xe90,0xf99,0xc93,0xd9a,0xa96,0xb9f,0x895,0x99c,
    0x69c,0x795,0x49f,0x596,0x29a,0x393,0x99,0x190,
    0xf00,0xe09,0xd03,0xc0a,0xb06,0xa0f,0x905,0x80c,
    0x70c,0x605,0x50f,0x406,0x30a,0x203,0x109,0x0,
]

_MC_TRI_TABLE = [
    [],
    [0,8,3],
    [0,1,9],
    [1,8,3,9,8,1],
    [1,2,10],
    [0,8,3,1,2,10],
    [9,2,10,0,2,9],
    [2,8,3,2,10,8,10,9,8],
    [3,11,2],
    [0,11,2,8,11,0],
    [1,9,0,2,3,11],
    [1,11,2,1,9,11,9,8,11],
    [3,10,1,11,10,3],
    [0,10,1,0,8,10,8,11,10],
    [3,9,0,3,11,9,11,10,9],
    [9,8,10,10,8,11],
    [4,7,8],
    [4,3,0,7,3,4],
    [0,1,9,8,4,7],
    [4,1,9,4,7,1,7,3,1],
    [1,2,10,8,4,7],
    [3,4,7,3,0,4,1,2,10],
    [9,2,10,9,0,2,8,4,7],
    [2,10,9,2,9,7,2,7,3,7,9,4],
    [8,4,7,3,11,2],
    [11,4,7,11,2,4,2,0,4],
    [9,0,1,8,4,7,2,3,11],
    [4,7,11,9,4,11,9,11,2,9,2,1],
    [3,10,1,3,11,10,7,8,4],
    [1,11,10,1,4,11,1,0,4,7,11,4],
    [4,7,8,9,0,11,9,11,10,11,0,3],
    [4,7,11,4,11,9,9,11,10],
    [9,5,4],
    [9,5,4,0,8,3],
    [0,5,4,1,5,0],
    [8,5,4,8,3,5,3,1,5],
    [1,2,10,9,5,4],
    [3,0,8,1,2,10,4,9,5],
    [5,2,10,5,4,2,4,0,2],
    [2,10,5,3,2,5,3,5,4,3,4,8],
    [9,5,4,2,3,11],
    [0,11,2,0,8,11,4,9,5],
    [0,5,4,0,1,5,2,3,11],
    [2,1,5,2,5,8,2,8,11,4,8,5],
    [10,3,11,10,1,3,9,5,4],
    [4,9,5,0,8,1,8,10,1,8,11,10],
    [5,4,0,5,0,11,5,11,10,11,0,3],
    [5,4,8,5,8,10,10,8,11],
    [9,7,8,5,7,9],
    [9,3,0,9,5,3,5,7,3],
    [0,7,8,0,1,7,1,5,7],
    [1,5,3,3,5,7],
    [9,7,8,9,5,7,10,1,2],
    [10,1,2,9,5,0,5,3,0,5,7,3],
    [8,0,2,8,2,5,8,5,7,10,5,2],
    [2,10,5,2,5,3,3,5,7],
    [7,9,5,7,8,9,3,11,2],
    [9,5,7,9,7,2,9,2,0,2,7,11],
    [2,3,11,0,1,8,1,7,8,1,5,7],
    [11,2,1,11,1,7,7,1,5],
    [9,5,8,8,5,7,10,1,3,10,3,11],
    [5,7,0,5,0,9,7,11,0,1,0,10,11,10,0],
    [11,10,0,11,0,3,10,5,0,8,0,7,5,7,0],
    [11,10,5,7,11,5],
    [10,6,5],
    [0,8,3,5,10,6],
    [9,0,1,5,10,6],
    [1,8,3,1,9,8,5,10,6],
    [1,6,5,2,6,1],
    [1,6,5,1,2,6,3,0,8],
    [9,6,5,9,0,6,0,2,6],
    [5,9,8,5,8,2,5,2,6,3,2,8],
    [2,3,11,10,6,5],
    [11,0,8,11,2,0,10,6,5],
    [0,1,9,2,3,11,5,10,6],
    [5,10,6,1,9,2,9,11,2,9,8,11],
    [6,3,11,6,5,3,5,1,3],
    [0,8,11,0,11,5,0,5,1,5,11,6],
    [3,11,6,0,3,6,0,6,5,0,5,9],
    [6,5,9,6,9,11,11,9,8],
    [5,10,6,4,7,8],
    [4,3,0,4,7,3,6,5,10],
    [1,9,0,5,10,6,8,4,7],
    [10,6,5,1,9,7,1,7,3,7,9,4],
    [6,1,2,6,5,1,4,7,8],
    [1,2,5,5,2,6,3,0,4,3,4,7],
    [8,4,7,9,0,5,0,6,5,0,2,6],
    [7,3,9,7,9,4,3,2,9,5,9,6,2,6,9],
    [3,11,2,7,8,4,10,6,5],
    [5,10,6,4,7,2,4,2,0,2,7,11],
    [0,1,9,4,7,8,2,3,11,5,10,6],
    [9,2,1,9,11,2,9,4,11,7,11,4,5,10,6],
    [8,4,7,3,11,5,3,5,1,5,11,6],
    [5,1,11,5,11,6,1,0,11,7,11,4,0,4,11],
    [0,5,9,0,6,5,0,3,6,11,6,3,8,4,7],
    [6,5,9,6,9,11,4,7,9,7,11,9],
    [10,4,9,6,4,10],
    [4,10,6,4,9,10,0,8,3],
    [10,0,1,10,6,0,6,4,0],
    [8,3,1,8,1,6,8,6,4,6,1,10],
    [1,4,9,1,2,4,2,6,4],
    [3,0,8,1,2,9,2,4,9,2,6,4],
    [0,2,4,4,2,6],
    [8,3,2,8,2,4,4,2,6],
    [10,4,9,10,6,4,11,2,3],
    [0,8,2,2,8,11,4,9,10,4,10,6],
    [3,11,2,0,1,6,0,6,4,6,1,10],
    [6,4,1,6,1,10,4,8,1,2,1,11,8,11,1],
    [9,6,4,9,3,6,9,1,3,11,6,3],
    [8,11,1,8,1,0,11,6,1,9,1,4,6,4,1],
    [3,11,6,3,6,0,0,6,4],
    [6,4,8,11,6,8],
    [7,10,6,7,8,10,8,9,10],
    [0,7,3,0,10,7,0,9,10,6,7,10],
    [10,6,7,1,10,7,1,7,8,1,8,0],
    [10,6,7,10,7,1,1,7,3],
    [1,2,6,1,6,8,1,8,9,8,6,7],
    [2,6,9,2,9,1,6,7,9,0,9,3,7,3,9],
    [7,8,0,7,0,6,6,0,2],
    [7,3,2,6,7,2],
    [2,3,11,10,6,8,10,8,9,8,6,7],
    [2,0,7,2,7,11,0,9,7,6,7,10,9,10,7],
    [1,8,0,1,7,8,1,10,7,6,7,10,2,3,11],
    [11,2,1,11,1,7,10,6,1,6,7,1],
    [8,9,6,8,6,7,9,1,6,11,6,3,1,3,6],
    [0,9,1,11,6,7],
    [7,8,0,7,0,6,3,11,0,11,6,0],
    [7,11,6],
    [7,6,11],
    [3,0,8,11,7,6],
    [0,1,9,11,7,6],
    [8,1,9,8,3,1,11,7,6],
    [10,1,2,6,11,7],
    [1,2,10,3,0,8,6,11,7],
    [2,9,0,2,10,9,6,11,7],
    [6,11,7,2,10,3,10,8,3,10,9,8],
    [7,2,3,6,2,7],
    [7,0,8,7,6,0,6,2,0],
    [2,7,6,2,3,7,0,1,9],
    [1,6,2,1,8,6,1,9,8,8,7,6],
    [10,7,6,10,1,7,1,3,7],
    [10,7,6,1,7,10,1,8,7,1,0,8],
    [0,3,7,0,7,10,0,10,9,6,10,7],
    [7,6,10,7,10,8,8,10,9],
    [6,8,4,11,8,6],
    [3,6,11,3,0,6,0,4,6],
    [8,6,11,8,4,6,9,0,1],
    [9,4,6,9,6,3,9,3,1,11,3,6],
    [6,8,4,6,11,8,2,10,1],
    [1,2,10,3,0,11,0,6,11,0,4,6],
    [4,11,8,4,6,11,0,2,9,2,10,9],
    [10,9,3,10,3,2,9,4,3,11,3,6,4,6,3],
    [8,2,3,8,4,2,4,6,2],
    [0,4,2,4,6,2],
    [1,9,0,2,3,4,2,4,6,4,3,8],
    [1,9,4,1,4,2,2,4,6],
    [8,1,3,8,6,1,8,4,6,6,10,1],
    [10,1,0,10,0,6,6,0,4],
    [4,6,3,4,3,8,6,10,3,0,3,9,10,9,3],
    [10,9,4,6,10,4],
    [4,9,5,7,6,11],
    [0,8,3,4,9,5,11,7,6],
    [5,0,1,5,4,0,7,6,11],
    [11,7,6,8,3,4,3,5,4,3,1,5],
    [9,5,4,10,1,2,7,6,11],
    [6,11,7,1,2,10,0,8,3,4,9,5],
    [7,6,11,5,4,10,4,2,10,4,0,2],
    [3,4,8,3,5,4,3,2,5,10,5,2,11,7,6],
    [7,2,3,7,6,2,5,4,9],
    [9,5,4,0,8,6,0,6,2,6,8,7],
    [3,6,2,3,7,6,1,5,0,5,4,0],
    [6,2,8,6,8,7,2,1,8,4,8,5,1,5,8],
    [9,5,4,10,1,6,1,7,6,1,3,7],
    [1,6,10,1,7,6,1,0,7,8,7,0,9,5,4],
    [4,0,10,4,10,5,0,3,10,6,10,7,3,7,10],
    [7,6,10,7,10,8,5,4,10,4,8,10],
    [6,9,5,6,11,9,11,8,9],
    [3,6,11,0,6,3,0,5,6,0,9,5],
    [0,11,8,0,5,11,0,1,5,5,6,11],
    [6,11,3,6,3,5,5,3,1],
    [1,2,10,9,5,11,9,11,8,11,5,6],
    [0,11,3,0,6,11,0,9,6,5,6,9,1,2,10],
    [11,8,5,11,5,6,8,0,5,10,5,2,0,2,5],
    [6,11,3,6,3,5,2,10,3,10,5,3],
    [5,8,9,5,2,8,5,6,2,3,8,2],
    [9,5,6,9,6,0,0,6,2],
    [1,5,8,1,8,0,5,6,8,3,8,2,6,2,8],
    [1,5,6,2,1,6],
    [1,3,6,1,6,10,3,8,6,5,6,9,8,9,6],
    [10,1,0,10,0,6,9,5,0,5,6,0],
    [0,3,8,5,6,10],
    [10,5,6],
    [11,5,10,7,5,11],
    [11,5,10,11,7,5,8,3,0],
    [5,11,7,5,10,11,1,9,0],
    [10,7,5,10,11,7,9,8,1,8,3,1],
    [11,1,2,11,7,1,7,5,1],
    [0,8,3,1,2,7,1,7,5,7,2,11],
    [9,7,5,9,2,7,9,0,2,2,11,7],
    [7,5,2,7,2,11,5,9,2,3,2,8,9,8,2],
    [2,5,10,2,3,5,3,7,5],
    [8,2,0,8,5,2,8,7,5,10,2,5],
    [9,0,1,5,10,3,5,3,7,3,10,2],
    [9,8,2,9,2,1,8,7,2,10,2,5,7,5,2],
    [1,3,5,3,7,5],
    [0,8,7,0,7,1,1,7,5],
    [9,0,3,9,3,5,5,3,7],
    [9,8,7,5,9,7],
    [5,8,4,5,10,8,10,11,8],
    [5,0,4,5,11,0,5,10,11,11,3,0],
    [0,1,9,8,4,10,8,10,11,10,4,5],
    [10,11,4,10,4,5,11,3,4,9,4,1,3,1,4],
    [2,5,1,2,8,5,2,11,8,4,5,8],
    [0,4,11,0,11,3,4,5,11,2,11,1,5,1,11],
    [0,2,5,0,5,9,2,11,5,4,5,8,11,8,5],
    [9,4,5,2,11,3],
    [2,5,10,3,5,2,3,4,5,3,8,4],
    [5,10,2,5,2,4,4,2,0],
    [3,10,2,3,5,10,3,8,5,4,5,8,0,1,9],
    [5,10,2,5,2,4,1,9,2,9,4,2],
    [8,4,5,8,5,3,3,5,1],
    [0,4,5,1,0,5],
    [8,4,5,8,5,3,9,0,5,0,3,5],
    [9,4,5],
    [4,11,7,4,9,11,9,10,11],
    [0,8,3,4,9,7,9,11,7,9,10,11],
    [1,10,11,1,11,4,1,4,0,7,4,11],
    [3,1,4,3,4,8,1,10,4,7,4,11,10,11,4],
    [4,11,7,9,11,4,9,2,11,9,1,2],
    [9,7,4,9,11,7,9,1,11,2,11,1,0,8,3],
    [11,7,4,11,4,2,2,4,0],
    [11,7,4,11,4,2,8,3,4,3,2,4],
    [2,9,10,2,7,9,2,3,7,7,4,9],
    [9,10,7,9,7,4,10,2,7,8,7,0,2,0,7],
    [3,7,10,3,10,2,7,4,10,1,10,0,4,0,10],
    [1,10,2,8,7,4],
    [4,9,1,4,1,7,7,1,3],
    [4,9,1,4,1,7,0,8,1,8,7,1],
    [4,0,3,7,4,3],
    [4,8,7],
    [9,10,8,10,11,8],
    [3,0,9,3,9,11,11,9,10],
    [0,1,10,0,10,8,8,10,11],
    [3,1,10,11,3,10],
    [1,2,11,1,11,9,9,11,8],
    [3,0,9,3,9,11,1,2,9,2,11,9],
    [0,2,11,8,0,11],
    [3,2,11],
    [2,3,8,2,8,10,10,8,9],
    [9,10,2,0,9,2],
    [2,3,8,2,8,10,0,1,8,1,10,8],
    [1,10,2],
    [1,3,8,9,1,8],
    [0,9,1],
    [0,3,8],
    [],
]


def marching_cubes(
    sdf: "SdfField",
    bounds: Tuple[float, float, float, float, float, float],
    resolution: int,
    isovalue: float = 0.0,
) -> Dict:
    """Extract a triangulated iso-surface using marching cubes.

    Parameters
    ----------
    sdf : SdfField
        Signed distance field to polygonise.
    bounds : (xmin, ymin, zmin, xmax, ymax, zmax)
        Bounding box to sample.
    resolution : int
        Number of samples per axis (grid is resolution^3).
        Clamped to range [4, 256].
    isovalue : float
        Iso-surface level (default 0.0 = surface of the SDF).

    Returns
    -------
    dict with keys:
        "vertices" : list of [x, y, z] — vertex positions
        "faces"    : list of [i, j, k] — triangle indices
    """
    try:
        resolution = max(4, min(256, int(resolution)))
        isovalue = float(isovalue)
        xmin, ymin, zmin, xmax, ymax, zmax = [float(v) for v in bounds]

        xs = np.linspace(xmin, xmax, resolution)
        ys = np.linspace(ymin, ymax, resolution)
        zs = np.linspace(zmin, zmax, resolution)
        sx = (xmax - xmin) / (resolution - 1) if resolution > 1 else 1.0
        sy = (ymax - ymin) / (resolution - 1) if resolution > 1 else 1.0
        sz = (zmax - zmin) / (resolution - 1) if resolution > 1 else 1.0

        # Sample SDF on grid
        fn = sdf._fn
        grid = np.empty((resolution, resolution, resolution), dtype=float)
        for i, x in enumerate(xs):
            for j, y in enumerate(ys):
                for k, z in enumerate(zs):
                    grid[i, j, k] = fn(x, y, z)

        # Marching cubes on the sampled grid
        vertices: List[List[float]] = []
        faces: List[List[int]] = []

        # Edge vertex cache: maps (i,j,k,edge_id) -> vertex index
        edge_cache: Dict[Tuple[int,int,int,int], int] = {}

        # Cube corner offsets (dx, dy, dz) for corners 0-7
        _corners = [
            (0,0,0),(1,0,0),(1,1,0),(0,1,0),
            (0,0,1),(1,0,1),(1,1,1),(0,1,1),
        ]
        # Cube edge definitions: (corner_a, corner_b) for edges 0-11
        _edges = [
            (0,1),(1,2),(2,3),(3,0),  # bottom face edges 0-3
            (4,5),(5,6),(6,7),(7,4),  # top face edges 4-7
            (0,4),(1,5),(2,6),(3,7),  # vertical edges 8-11
        ]

        n = resolution - 1
        for i in range(n):
            for j in range(n):
                for k in range(n):
                    # Evaluate corner values
                    vals = [grid[i+di, j+dj, k+dk] - isovalue
                            for di, dj, dk in _corners]

                    # Compute cube index (bitmask: bit set if val < 0)
                    cube_idx = 0
                    for ci, v in enumerate(vals):
                        if v < 0:
                            cube_idx |= (1 << ci)

                    edge_mask = _MC_EDGE_TABLE[cube_idx]
                    if edge_mask == 0:
                        continue

                    # Interpolate edge vertices
                    edge_verts: Dict[int, int] = {}
                    for eid in range(12):
                        if not (edge_mask & (1 << eid)):
                            continue
                        # Check cache first
                        cache_key = (i, j, k, eid)
                        if cache_key in edge_cache:
                            edge_verts[eid] = edge_cache[cache_key]
                            continue

                        ca, cb = _edges[eid]
                        da = _corners[ca]
                        db = _corners[cb]
                        va = vals[ca]
                        vb = vals[cb]
                        # Linear interpolation
                        if abs(vb - va) < 1e-12:
                            t = 0.5
                        else:
                            t = -va / (vb - va)
                            t = max(0.0, min(1.0, t))

                        xi = xs[i + da[0]] + t * (xs[i + db[0]] - xs[i + da[0]])
                        yi = ys[j + da[1]] + t * (ys[j + db[1]] - ys[j + da[1]])
                        zi = zs[k + da[2]] + t * (zs[k + db[2]] - zs[k + da[2]])

                        vi = len(vertices)
                        vertices.append([xi, yi, zi])
                        edge_verts[eid] = vi
                        edge_cache[cache_key] = vi

                    # Build triangles from tri table
                    tri_list = _MC_TRI_TABLE[cube_idx]
                    for t_idx in range(0, len(tri_list), 3):
                        e0 = tri_list[t_idx]
                        e1 = tri_list[t_idx + 1]
                        e2 = tri_list[t_idx + 2]
                        if e0 < 0 or e1 < 0 or e2 < 0:
                            break
                        if e0 in edge_verts and e1 in edge_verts and e2 in edge_verts:
                            faces.append([edge_verts[e0], edge_verts[e1], edge_verts[e2]])

        return {"vertices": vertices, "faces": faces}

    except Exception:
        return {"vertices": [], "faces": []}


__all__ = [
    "SdfField",
    "sdf_sphere",
    "sdf_box",
    "sdf_cylinder",
    "sdf_union",
    "sdf_subtract",
    "sdf_intersect",
    "marching_cubes",
]
