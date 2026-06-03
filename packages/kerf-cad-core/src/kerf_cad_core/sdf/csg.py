"""
kerf_cad_core.sdf.csg
=====================
Signed Distance Field (SDF) primitives, CSG boolean operations, smooth-min
blending, and rigid-body transforms.

Design
------
* Pure Python + numpy only.  No scipy, no OCC.
* SDF convention: negative inside the solid, zero on the surface, positive
  outside.
* All SDF callables have the signature:
      f(points: np.ndarray) -> np.ndarray
  where points.shape == (N, 3) and the return shape is (N,).
* Smooth-min blend: polynomial smooth-min from Inigo Quilez (2008/2022).
  Reference: https://iquilezles.org/articles/smin/
  Formula: h = clamp(0.5 + 0.5*(b-a)/k, 0, 1)
           smin(a, b, k) = mix(b, a, h) - k*h*(1-h)

References
----------
Quilez, I. (2008). "smooth min." https://iquilezles.org/articles/smin/
Quilez, I. (2022). "Signed Distance Functions."
    https://iquilezles.org/articles/distfunctions/
"""
from __future__ import annotations

import math
from typing import Callable

import numpy as np

# ---------------------------------------------------------------------------
# Type alias
# ---------------------------------------------------------------------------

# SDF takes (N, 3) array of sample points and returns (N,) signed distances.
SDF = Callable[[np.ndarray], np.ndarray]

# Small epsilon to avoid division by zero.
_EPS: float = 1e-12


# ===========================================================================
# Helpers
# ===========================================================================

def _to_points(pts: np.ndarray) -> np.ndarray:
    """Ensure pts is a writable float64 (N, 3) array."""
    pts = np.asarray(pts, dtype=np.float64)
    if pts.ndim == 1 and pts.shape[0] == 3:
        pts = pts[np.newaxis, :]
    return pts


# ===========================================================================
# Primitive SDFs
# ===========================================================================

def sdf_sphere(
    center: tuple[float, float, float],
    radius: float,
) -> SDF:
    """Analytic SDF for a sphere.

    sdf(p) = |p - center| - radius

    Parameters
    ----------
    center : (cx, cy, cz) world-space centre.
    radius : sphere radius (must be > 0).
    """
    cx, cy, cz = float(center[0]), float(center[1]), float(center[2])
    r = float(radius)

    def _f(pts: np.ndarray) -> np.ndarray:
        p = _to_points(pts)
        dx = p[:, 0] - cx
        dy = p[:, 1] - cy
        dz = p[:, 2] - cz
        return np.sqrt(dx * dx + dy * dy + dz * dz) - r

    return _f


def sdf_box(
    center: tuple[float, float, float],
    half_extents: tuple[float, float, float],
) -> SDF:
    """Exact SDF for an axis-aligned box.

    Uses the Quilez formula:
      q = |p - center| - half_extents
      sdf = |max(q, 0)| + min(max(qx, qy, qz), 0)

    Parameters
    ----------
    center      : (cx, cy, cz) box centre.
    half_extents: (hx, hy, hz) half-widths along each axis.
    """
    cx, cy, cz = float(center[0]), float(center[1]), float(center[2])
    hx, hy, hz = float(half_extents[0]), float(half_extents[1]), float(half_extents[2])

    def _f(pts: np.ndarray) -> np.ndarray:
        p = _to_points(pts)
        qx = np.abs(p[:, 0] - cx) - hx
        qy = np.abs(p[:, 1] - cy) - hy
        qz = np.abs(p[:, 2] - cz) - hz
        # Outside component: length of max(q, 0)
        outer = np.sqrt(
            np.maximum(qx, 0.0) ** 2
            + np.maximum(qy, 0.0) ** 2
            + np.maximum(qz, 0.0) ** 2
        )
        # Inside component: min(max(qx, qy, qz), 0)
        inner = np.minimum(np.maximum(qx, np.maximum(qy, qz)), 0.0)
        return outer + inner

    return _f


def sdf_cylinder_z(
    center: tuple[float, float, float],
    radius: float,
    half_height: float,
) -> SDF:
    """Exact SDF for a finite cylinder aligned to the Z-axis.

    Uses the Quilez formula in the (r, h) half-space:
      d.x = |sqrt((x-cx)²+(y-cy)²)| - radius
      d.y = |z - cz| - half_height
      sdf = min(max(d.x, d.y), 0) + |max(d, 0)|

    Parameters
    ----------
    center      : (cx, cy, cz) cylinder axis midpoint.
    radius      : cylinder radius.
    half_height : half the total height along Z.
    """
    cx, cy, cz = float(center[0]), float(center[1]), float(center[2])
    r = float(radius)
    hh = float(half_height)

    def _f(pts: np.ndarray) -> np.ndarray:
        p = _to_points(pts)
        dx = p[:, 0] - cx
        dy = p[:, 1] - cy
        dz = p[:, 2] - cz
        dr = np.sqrt(dx * dx + dy * dy) - r
        dh = np.abs(dz) - hh
        outer = np.sqrt(
            np.maximum(dr, 0.0) ** 2 + np.maximum(dh, 0.0) ** 2
        )
        inner = np.minimum(np.maximum(dr, dh), 0.0)
        return outer + inner

    return _f


def sdf_plane(
    point: tuple[float, float, float],
    normal: tuple[float, float, float],
) -> SDF:
    """SDF for a half-space defined by a plane.

    sdf(p) = dot(p - point, n̂)

    Negative on the side opposite to the normal (inside), positive on the
    normal side.

    Parameters
    ----------
    point  : any point on the plane.
    normal : outward-pointing normal (need not be unit length — will be normalised).
    """
    px, py, pz = float(point[0]), float(point[1]), float(point[2])
    nx, ny, nz = float(normal[0]), float(normal[1]), float(normal[2])
    nlen = math.sqrt(nx * nx + ny * ny + nz * nz)
    if nlen < _EPS:
        raise ValueError("sdf_plane: normal vector has near-zero length.")
    nx /= nlen
    ny /= nlen
    nz /= nlen
    # d = -dot(n, point)  so that dot(n, p) + d = dot(n, p - point)
    d = -(nx * px + ny * py + nz * pz)

    def _f(pts: np.ndarray) -> np.ndarray:
        p = _to_points(pts)
        return p[:, 0] * nx + p[:, 1] * ny + p[:, 2] * nz + d

    return _f


# ===========================================================================
# Sharp (hard) CSG operations
# ===========================================================================

def sdf_union(a: SDF, b: SDF) -> SDF:
    """Boolean union: min(a(p), b(p))."""

    def _f(pts: np.ndarray) -> np.ndarray:
        p = _to_points(pts)
        return np.minimum(a(p), b(p))

    return _f


def sdf_intersection(a: SDF, b: SDF) -> SDF:
    """Boolean intersection: max(a(p), b(p))."""

    def _f(pts: np.ndarray) -> np.ndarray:
        p = _to_points(pts)
        return np.maximum(a(p), b(p))

    return _f


def sdf_subtraction(a: SDF, b: SDF) -> SDF:
    """Boolean difference a minus b: max(a(p), -b(p))."""

    def _f(pts: np.ndarray) -> np.ndarray:
        p = _to_points(pts)
        return np.maximum(a(p), -b(p))

    return _f


# ===========================================================================
# Smooth (Quilez 2008) CSG operations
# ===========================================================================

def _smooth_min(a: np.ndarray, b: np.ndarray, k: float) -> np.ndarray:
    """Polynomial smooth-min (Quilez 2008).

    h = clamp(0.5 + 0.5*(b-a)/k, 0, 1)
    smin = mix(b, a, h) - k*h*(1-h)
         = a*(h) + b*(1-h) - k*h*(1-h)     [note: mix(b,a,h) = a*h + b*(1-h)]

    For k → 0 this reduces to min(a, b).
    The blend is active in the zone |a - b| < k.
    """
    k = max(float(k), _EPS)
    h = np.clip(0.5 + 0.5 * (b - a) / k, 0.0, 1.0)
    return a * h + b * (1.0 - h) - k * h * (1.0 - h)


def _smooth_max(a: np.ndarray, b: np.ndarray, k: float) -> np.ndarray:
    """Polynomial smooth-max: dual of smooth-min.

    smax(a, b, k) = -smin(-a, -b, k)
    """
    return -_smooth_min(-a, -b, k)


def sdf_smooth_union(a: SDF, b: SDF, k: float) -> SDF:
    """Smooth boolean union using Quilez polynomial smooth-min.

    Parameters
    ----------
    a, b : SDF functions to blend.
    k    : blend radius in model units.  Larger k → broader, softer blend.

    At the merge region the resulting value is ≤ min(a(p), b(p)), creating
    a smooth bridge between the two shapes.
    """

    def _f(pts: np.ndarray) -> np.ndarray:
        p = _to_points(pts)
        return _smooth_min(a(p), b(p), k)

    return _f


def sdf_smooth_intersection(a: SDF, b: SDF, k: float) -> SDF:
    """Smooth boolean intersection using polynomial smooth-max.

    Parameters
    ----------
    k : blend radius in model units.
    """

    def _f(pts: np.ndarray) -> np.ndarray:
        p = _to_points(pts)
        return _smooth_max(a(p), b(p), k)

    return _f


def sdf_smooth_subtraction(a: SDF, b: SDF, k: float) -> SDF:
    """Smooth boolean difference a minus b: smooth-max(a, -b).

    Parameters
    ----------
    k : blend radius in model units.
    """

    def _f(pts: np.ndarray) -> np.ndarray:
        p = _to_points(pts)
        return _smooth_max(a(p), -b(p), k)

    return _f


# ===========================================================================
# Rigid-body transforms
# ===========================================================================

def sdf_translate(f: SDF, offset: tuple[float, float, float]) -> SDF:
    """Translate the SDF field by *offset*.

    Implemented as inverse-mapping: evaluate f at (p - offset).
    """
    ox, oy, oz = float(offset[0]), float(offset[1]), float(offset[2])

    def _f(pts: np.ndarray) -> np.ndarray:
        p = _to_points(pts).copy()
        p[:, 0] -= ox
        p[:, 1] -= oy
        p[:, 2] -= oz
        return f(p)

    return _f


def sdf_scale(f: SDF, factor: float) -> SDF:
    """Uniform scale by *factor*.

    For an exact SDF, scaling the domain by s and dividing the result by s
    preserves the Lipschitz constant (gradient magnitude ≤ 1).

    sdf_scaled(p) = f(p / factor) * factor
    """
    s = float(factor)
    if abs(s) < _EPS:
        raise ValueError("sdf_scale: factor must be non-zero.")

    def _f(pts: np.ndarray) -> np.ndarray:
        p = _to_points(pts)
        return f(p / s) * s

    return _f


def sdf_rotate(
    f: SDF,
    axis: tuple[float, float, float],
    angle_rad: float,
) -> SDF:
    """Rotate the SDF field by *angle_rad* around *axis* (right-hand rule).

    Implemented as inverse rotation of the sample points: we apply the
    rotation matrix R^T (= R^{-1}) to each query point before evaluating f,
    so the geometry as seen by the caller rotates by +angle_rad.

    The rotation matrix is Rodrigues' formula:
        R = I cos(θ) + (1-cos(θ)) n⊗n + sin(θ) [n]_×

    Parameters
    ----------
    f         : SDF to rotate.
    axis      : rotation axis (need not be unit length).
    angle_rad : rotation angle in radians (right-hand rule).
    """
    ax, ay, az = float(axis[0]), float(axis[1]), float(axis[2])
    alen = math.sqrt(ax * ax + ay * ay + az * az)
    if alen < _EPS:
        raise ValueError("sdf_rotate: axis vector has near-zero length.")
    ax /= alen
    ay /= alen
    az /= alen

    c = math.cos(angle_rad)
    s = math.sin(angle_rad)
    t = 1.0 - c

    # Build R^T (transpose = inverse for rotation matrices).
    # R_{ij} = δ_{ij}*c + (1-c)*n_i*n_j + s*ε_{ijk}*n_k
    # R^T_{ij} = R_{ji}
    r00 = c + t * ax * ax;     r01 = t * ax * ay - s * az;  r02 = t * ax * az + s * ay
    r10 = t * ax * ay + s * az; r11 = c + t * ay * ay;       r12 = t * ay * az - s * ax
    r20 = t * ax * az - s * ay; r21 = t * ay * az + s * ax;  r22 = c + t * az * az

    # R^T (for inverse rotation):
    rt00, rt01, rt02 = r00, r10, r20
    rt10, rt11, rt12 = r01, r11, r21
    rt20, rt21, rt22 = r02, r12, r22

    def _f(pts: np.ndarray) -> np.ndarray:
        p = _to_points(pts)
        x = p[:, 0]; y = p[:, 1]; z = p[:, 2]
        px = rt00 * x + rt01 * y + rt02 * z
        py = rt10 * x + rt11 * y + rt12 * z
        pz = rt20 * x + rt21 * y + rt22 * z
        q = np.stack([px, py, pz], axis=1)
        return f(q)

    return _f
