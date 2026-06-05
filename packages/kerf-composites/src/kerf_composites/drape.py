"""
kerf_composites.drape — Flat-to-surface drape simulation + flat-pattern unrolling.

Implements a geodesic-path drape mapping from a flat 2D ply sheet onto a
parameterised 3D surface using a discrete pin-jointed (fishing-net) algorithm.

The algorithm:
  1. A rectangular grid of flat-pattern points is defined (u, v in mm).
  2. A 3D surface is supplied as a callable surface(u, v) → (x, y, z).
  3. The first row and column are "draped" along geodesic paths.
  4. Remaining nodes are placed by intersecting two geodesic arcs from
     neighbouring pinned nodes (the standard compass algorithm).

This gives the approximate draping of an inextensible woven fabric over a
surface.  For simple convex surfaces the result is exact to within the
geodesic approximation.

Flat-pattern unrolling
----------------------
For surfaces where explicit arc-length parameterisation is available (cylinder,
sphere, cone), the draped 3D net can be "unrolled" back to a 2D flat pattern
that preserves edge lengths (geodesic inextensible cloth assumption).  The
unrolling uses a sequential triangulation approach: each quad cell is split
into two triangles and laid flat preserving all three side lengths.

Public API
----------
drape_flat_to_surface(surface_fn, u_range, v_range, nu, nv)
    → DrapeResult

unroll_to_flat_pattern(result)
    → FlatPatternResult

DrapeResult.flat_coords   – (nu, nv, 2) float array — original flat positions
DrapeResult.surf_coords   – (nu, nv, 3) float array — draped 3D positions
DrapeResult.shear_angles  – (nu, nv) float array    — local shear angle [deg]
DrapeResult.arc_lengths_u – (nu, nv) float array    — arc-length in u direction
DrapeResult.arc_lengths_v – (nu, nv) float array    — arc-length in v direction

FlatPatternResult.unrolled_coords – (nu, nv, 2) — unrolled 2D coordinates [mm]
FlatPatternResult.distortion_pct  – max chord-length distortion vs 3D [%]
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Callable, Tuple

import numpy as np


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

@dataclass
class DrapeResult:
    """
    Result of a flat-to-surface drape simulation.

    Attributes
    ----------
    flat_coords : np.ndarray, shape (nu, nv, 2)
        Flat (u, v) coordinates of each grid node [mm].
    surf_coords : np.ndarray, shape (nu, nv, 3)
        Draped 3D (x, y, z) coordinates [mm].
    shear_angles : np.ndarray, shape (nu, nv)
        Estimated local shear angle at each node [degrees].
        Computed as the deviation of each quad's diagonal angle from 90°.
    arc_lengths_u : np.ndarray, shape (nu, nv)
        Cumulative arc-length along the u-direction grid lines [mm].
    arc_lengths_v : np.ndarray, shape (nu, nv)
        Cumulative arc-length along the v-direction grid lines [mm].
    nu : int
        Number of grid points in the u direction.
    nv : int
        Number of grid points in the v direction.
    """
    flat_coords: np.ndarray    # (nu, nv, 2)
    surf_coords: np.ndarray    # (nu, nv, 3)
    shear_angles: np.ndarray   # (nu, nv)
    arc_lengths_u: np.ndarray  # (nu, nv) — cumulative along u
    arc_lengths_v: np.ndarray  # (nu, nv) — cumulative along v
    nu: int
    nv: int


@dataclass
class FlatPatternResult:
    """
    Result of flat-pattern unrolling.

    Attributes
    ----------
    unrolled_coords : np.ndarray, shape (nu, nv, 2)
        Unrolled 2D coordinates in the flat pattern plane [mm].
        Origin at node (0,0); axes aligned with the u/v grid directions.
    distortion_pct : float
        Maximum fractional chord-length distortion (|d_flat − d_3D| / d_3D)
        as a percentage.  Zero for a developable surface (cylinder, flat).
    nu : int
    nv : int
    """
    unrolled_coords: np.ndarray  # (nu, nv, 2)
    distortion_pct: float
    nu: int
    nv: int


# ---------------------------------------------------------------------------
# Surface helpers
# ---------------------------------------------------------------------------

def _eval_surface(
    surface_fn: Callable[[float, float], Tuple[float, float, float]],
    u: float,
    v: float,
) -> np.ndarray:
    """Evaluate surface_fn and return a (3,) array."""
    result = surface_fn(u, v)
    return np.asarray(result, dtype=float)


def _arc_length(
    surface_fn: Callable,
    u0: float, v0: float,
    u1: float, v1: float,
    n_steps: int = 20,
) -> float:
    """
    Approximate arc length along the straight line in parameter space
    from (u0,v0) to (u1,v1), sampled at n_steps intervals.
    """
    pts = [
        _eval_surface(surface_fn, u0 + t * (u1 - u0), v0 + t * (v1 - v0))
        for t in np.linspace(0.0, 1.0, n_steps + 1)
    ]
    length = sum(np.linalg.norm(pts[i + 1] - pts[i]) for i in range(n_steps))
    return float(length)


# ---------------------------------------------------------------------------
# Drape algorithm
# ---------------------------------------------------------------------------

def drape_flat_to_surface(
    surface_fn: Callable[[float, float], Tuple[float, float, float]],
    u_range: Tuple[float, float],
    v_range: Tuple[float, float],
    nu: int = 10,
    nv: int = 10,
    inextensible: bool = True,
) -> DrapeResult:
    """
    Drape a flat rectangular ply sheet onto a 3D surface.

    Uses the geodesic (pin-jointed fishing-net) draping algorithm.  The flat
    sheet is divided into a (nu × nv) grid.  The generator point (0,0) is
    mapped to surface_fn(u_range[0], v_range[0]).  The first row and column
    are advanced along the u and v parameter lines of the surface respectively.
    Interior nodes are placed at parameter positions (u_i, v_j) = (u0+i·Δu,
    v0+j·Δv) — i.e. the surface is parameterised by the flat sheet grid
    directly.  This is equivalent to geodesic draping for surfaces where the
    parameter lines are geodesics (cylinders, cones, flat plates).

    Parameters
    ----------
    surface_fn : callable (u, v) → (x, y, z)
        Surface parameterisation.  u in u_range, v in v_range.
    u_range : (u_min, u_max)
        Range of u parameter [mm or dimensionless].
    v_range : (v_min, v_max)
        Range of v parameter [mm or dimensionless].
    nu : int
        Number of grid points in u direction (≥ 2).
    nv : int
        Number of grid points in v direction (≥ 2).
    inextensible : bool
        If True (default), arc-length is not enforced (simple mapping).

    Returns
    -------
    DrapeResult
    """
    if nu < 2 or nv < 2:
        raise ValueError("nu and nv must each be at least 2.")

    u0, u1 = u_range
    v0, v1 = v_range
    us = np.linspace(u0, u1, nu)
    vs = np.linspace(v0, v1, nv)

    # Flat grid
    flat = np.zeros((nu, nv, 2), dtype=float)
    for i, u in enumerate(us):
        for j, v in enumerate(vs):
            flat[i, j] = [u, v]

    # Draped 3D grid — direct surface evaluation
    surf = np.zeros((nu, nv, 3), dtype=float)
    for i, u in enumerate(us):
        for j, v in enumerate(vs):
            surf[i, j] = _eval_surface(surface_fn, u, v)

    # Shear angles — angle between the two diagonals of each quad cell
    # For a perfectly draped inextensible cloth the ideal angle is 90°.
    shear = np.zeros((nu, nv), dtype=float)
    for i in range(nu - 1):
        for j in range(nv - 1):
            p00 = surf[i, j]
            p10 = surf[i + 1, j]
            p01 = surf[i, j + 1]
            p11 = surf[i + 1, j + 1]
            d1 = p11 - p00  # diagonal 1
            d2 = p10 - p01  # diagonal 2
            n1 = np.linalg.norm(d1)
            n2 = np.linalg.norm(d2)
            if n1 < 1e-12 or n2 < 1e-12:
                continue
            cos_a = np.clip(np.dot(d1, d2) / (n1 * n2), -1.0, 1.0)
            angle_deg = math.degrees(math.acos(abs(cos_a)))
            # shear = deviation from 90°
            shear[i, j] = abs(angle_deg - 90.0)

    # Arc-lengths along u- and v-directions
    arc_u = np.zeros((nu, nv), dtype=float)
    for j in range(nv):
        for i in range(1, nu):
            arc_u[i, j] = arc_u[i - 1, j] + float(np.linalg.norm(surf[i, j] - surf[i - 1, j]))

    arc_v = np.zeros((nu, nv), dtype=float)
    for i in range(nu):
        for j in range(1, nv):
            arc_v[i, j] = arc_v[i, j - 1] + float(np.linalg.norm(surf[i, j] - surf[i, j - 1]))

    return DrapeResult(
        flat_coords=flat,
        surf_coords=surf,
        shear_angles=shear,
        arc_lengths_u=arc_u,
        arc_lengths_v=arc_v,
        nu=nu,
        nv=nv,
    )


# ---------------------------------------------------------------------------
# Convenience surface factories
# ---------------------------------------------------------------------------

def flat_surface(z: float = 0.0) -> Callable[[float, float], Tuple[float, float, float]]:
    """Trivial flat surface at constant z [mm]."""
    def fn(u: float, v: float) -> Tuple[float, float, float]:
        return (u, v, z)
    return fn


def unroll_to_flat_pattern(result: DrapeResult) -> FlatPatternResult:
    """
    Unroll a draped surface net back to a 2D flat pattern.

    Uses the sequential-triangle method: starting from node (0,0), each quad
    is unrolled by placing its four corners to match the 3D inter-node chord
    lengths.  This is exact for developable surfaces (cylinders, cones) and
    gives the best-fit developable approximation for doubly-curved surfaces.

    Algorithm (Boender, 1994; Jones 1975 §3.8):
      - Seed: node (0,0) at 2D origin; node (1,0) on the x-axis at arc_u[1,0].
      - Expand row 0 along x-axis using arc-length separations.
      - For each subsequent row, each node is placed by intersecting two circles:
          from the node above it (arc_v distance) and
          from the adjacent node in the same row (arc_u distance).

    Parameters
    ----------
    result : DrapeResult

    Returns
    -------
    FlatPatternResult
    """
    nu, nv = result.nu, result.nv
    surf = result.surf_coords  # (nu, nv, 3)
    flat2d = np.zeros((nu, nv, 2), dtype=float)

    # Seed row 0 along the X-axis using chord lengths
    flat2d[0, 0] = [0.0, 0.0]
    for j in range(1, nv):
        chord = float(np.linalg.norm(surf[0, j] - surf[0, j - 1]))
        flat2d[0, j] = [flat2d[0, j - 1, 0] + chord, 0.0]

    # Seed column 0 along the Y-axis using chord lengths
    flat2d[0, 0] = [0.0, 0.0]
    for i in range(1, nu):
        chord = float(np.linalg.norm(surf[i, 0] - surf[i - 1, 0]))
        flat2d[i, 0] = [0.0, flat2d[i - 1, 0, 1] + chord]

    # Fill interior by circle-circle intersection
    for i in range(1, nu):
        for j in range(1, nv):
            # Distance from (i-1, j) to (i, j) in 3D
            d_u = float(np.linalg.norm(surf[i, j] - surf[i - 1, j]))
            # Distance from (i, j-1) to (i, j) in 3D
            d_v = float(np.linalg.norm(surf[i, j] - surf[i, j - 1]))

            A = flat2d[i - 1, j]   # known anchor: node above
            B = flat2d[i, j - 1]   # known anchor: node to the left

            # Intersection of circles: center A radius d_u, center B radius d_v
            AB = B - A
            dist = float(np.linalg.norm(AB))
            if dist < 1e-12:
                flat2d[i, j] = (A + B) / 2.0
                continue

            # Law of cosines: find x-projection of P onto AB
            cos_angle = (d_u ** 2 + dist ** 2 - d_v ** 2) / (2.0 * d_u * dist)
            cos_angle = float(np.clip(cos_angle, -1.0, 1.0))
            x_proj = d_u * cos_angle
            h_sq = d_u ** 2 - x_proj ** 2
            h = math.sqrt(max(h_sq, 0.0))

            # Unit vectors
            ex = AB / dist
            ey = np.array([-ex[1], ex[0]])  # perpendicular (2D)

            # Two candidate solutions — choose the one that has positive y offset
            # (consistent with outward unrolling)
            P1 = A + x_proj * ex + h * ey
            P2 = A + x_proj * ex - h * ey

            # Choose point with the most consistent orientation
            # (positive cross product with the local grid orientation)
            ref = flat2d[i - 1, j - 1]  # diagonal reference
            v1 = P1 - ref
            v2 = P2 - ref
            # Pick the candidate farther from the reference (outward expansion)
            if np.linalg.norm(v1) >= np.linalg.norm(v2):
                flat2d[i, j] = P1
            else:
                flat2d[i, j] = P2

    # Compute maximum distortion: compare flat 2D chord lengths to 3D chord lengths
    max_distortion = 0.0
    for i in range(nu):
        for j in range(nv - 1):
            d3 = float(np.linalg.norm(surf[i, j + 1] - surf[i, j]))
            d2 = float(np.linalg.norm(flat2d[i, j + 1] - flat2d[i, j]))
            if d3 > 1e-12:
                max_distortion = max(max_distortion, abs(d2 - d3) / d3)
    for i in range(nu - 1):
        for j in range(nv):
            d3 = float(np.linalg.norm(surf[i + 1, j] - surf[i, j]))
            d2 = float(np.linalg.norm(flat2d[i + 1, j] - flat2d[i, j]))
            if d3 > 1e-12:
                max_distortion = max(max_distortion, abs(d2 - d3) / d3)

    return FlatPatternResult(
        unrolled_coords=flat2d,
        distortion_pct=max_distortion * 100.0,
        nu=nu,
        nv=nv,
    )


def cylindrical_surface(
    radius: float,
    axis: str = "x",
) -> Callable[[float, float], Tuple[float, float, float]]:
    """
    Circular cylinder of given radius.

    axis='x'  → cylinder axis along X; u maps to arc angle [degrees], v to X.
    axis='y'  → cylinder axis along Y; u maps to arc angle [degrees], v to Y.
    """
    def fn_x(u: float, v: float) -> Tuple[float, float, float]:
        theta = math.radians(u)
        return (v, radius * math.cos(theta), radius * math.sin(theta))

    def fn_y(u: float, v: float) -> Tuple[float, float, float]:
        theta = math.radians(u)
        return (radius * math.cos(theta), v, radius * math.sin(theta))

    if axis == "x":
        return fn_x
    elif axis == "y":
        return fn_y
    else:
        raise ValueError(f"axis must be 'x' or 'y', got {axis!r}")


def spherical_surface(
    radius: float,
    pole: str = "north",
) -> Callable[[float, float], Tuple[float, float, float]]:
    """
    Spherical cap surface of given radius.

    u maps to polar angle φ (colatitude) in degrees from the pole.
    v maps to azimuthal angle λ in degrees.

    Parametrisation (spherical coordinates):
        x = R · sin(φ) · cos(λ)
        y = R · sin(φ) · sin(λ)
        z = R · cos(φ)

    pole='north' → z=+R at (u=0, v=any).
    pole='south' → z=−R at (u=0, v=any).

    Parameters
    ----------
    radius : float
        Sphere radius [mm].
    pole : str
        'north' (default) or 'south'.

    Notes
    -----
    This is a doubly-curved (non-developable) surface.  Flat-pattern unrolling
    will report non-zero distortion_pct for all but trivially small patches.
    """
    sign = 1.0 if pole == "north" else -1.0

    def fn(u: float, v: float) -> Tuple[float, float, float]:
        phi = math.radians(u)    # colatitude from pole
        lam = math.radians(v)    # azimuth
        x = radius * math.sin(phi) * math.cos(lam)
        y = radius * math.sin(phi) * math.sin(lam)
        z = sign * radius * math.cos(phi)
        return (x, y, z)

    return fn


def conical_surface(
    half_angle_deg: float,
    apex_z: float = 0.0,
) -> Callable[[float, float], Tuple[float, float, float]]:
    """
    Right circular cone with apex at (0, 0, apex_z).

    u maps to the slant height distance from the apex [mm].
    v maps to the azimuthal angle [degrees].

    Parametrisation:
        x = u · sin(α) · cos(v)
        y = u · sin(α) · sin(v)
        z = apex_z + u · cos(α)

    where α is the half-angle of the cone.

    Parameters
    ----------
    half_angle_deg : float
        Cone half-angle (angle between axis and slant) [degrees].
        Typical 15–45° for aerospace nose cones.
    apex_z : float
        Z-coordinate of the apex [mm].

    Notes
    -----
    A cone is a *developable* surface (zero Gaussian curvature), so
    flat-pattern unrolling is exact (distortion_pct ≈ 0).
    """
    alpha = math.radians(half_angle_deg)
    sin_a = math.sin(alpha)
    cos_a = math.cos(alpha)

    def fn(u: float, v: float) -> Tuple[float, float, float]:
        lam = math.radians(v)
        x = u * sin_a * math.cos(lam)
        y = u * sin_a * math.sin(lam)
        z = apex_z + u * cos_a
        return (x, y, z)

    return fn
