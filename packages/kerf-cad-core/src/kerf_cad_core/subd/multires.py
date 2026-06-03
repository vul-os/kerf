"""multires.py
=============
SubD multires displacement maps — per-limit-point scalar displacement
on top of the Catmull-Clark limit surface.

Theory
------
A multires displacement map stores per-vertex scalar offsets d at successive
subdivision levels. Given a smooth base surface S(u,v) with unit normal n̂(u,v),
the displaced surface is:

    P(u,v) = S(u,v) + D(u,v) · n̂(u,v)

where D(u,v) = Σ_{l=0}^{L} bilinear_interp(displacements[l], u, v)
is the sum of displacements at all levels 0..L (linear superposition).

Each displacement level l stores a (2^l + 1) × (2^l + 1) grid of scalar
offsets at the regularly sampled (u,v) grid of the base quad face. Level 0
has a 2×2 grid (the four base corners). Level 1 has a 3×3 grid. Level k has
a (2^k + 1) × (2^k + 1) grid — i.e., the resolution doubles per level.

This follows the approach described in:
  - Cook (1984). "Shade Trees." SIGGRAPH '84. (displacement shading concept)
  - Krishnamurthy & Levoy (1996). "Fitting Smooth Surfaces to Dense Polygon
    Meshes." SIGGRAPH '96, §3. (multires displacement on subdivision surfaces)
  - Pixar OpenSubdiv Far library documentation. (practical implementation)

The "encode → evaluate" workflow:
  1. Sample a high-resolution detailed mesh at (M×M) points over a base face.
  2. Decompose the offsets from the base limit surface into level-0 displacements.
  3. At each subsequent level, store the residual not captured by levels 0..k-1.
  4. Evaluate at any (u,v) by summing bilinearly-interpolated displacements.

Dependencies: numpy only (no scipy). Pure Python + numpy as specified.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import List, Tuple

import numpy as np

# ---------------------------------------------------------------------------
# Type alias (mirrors limit_tangent.py)
# ---------------------------------------------------------------------------

Vec3 = Tuple[float, float, float]


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class DisplacementLevel:
    """Per-vertex scalar displacement at a subdivision level.

    Attributes
    ----------
    level : int
        Subdivision level. 0 = base (4 corner samples), k = 2^k+1 samples/side.
    face_id : int
        Which base face this displacement level belongs to.
    grid_resolution : int
        Number of samples per side: 2^level + 1.
        Level 0 → 2, level 1 → 3, level 2 → 5, level 3 → 9.
    scalars : np.ndarray
        Shape (grid_resolution, grid_resolution) float32 scalar displacements.
        scalars[row, col] is the displacement at (u, v) =
        (col / (grid_resolution-1), row / (grid_resolution-1)).
    """
    level: int
    face_id: int
    grid_resolution: int
    scalars: np.ndarray  # shape (grid_resolution, grid_resolution), float32

    def __post_init__(self) -> None:
        expected_res = (1 << self.level) + 1  # 2^level + 1
        if self.grid_resolution != expected_res:
            raise ValueError(
                f"DisplacementLevel: level={self.level} requires "
                f"grid_resolution={expected_res}, got {self.grid_resolution}"
            )
        if self.scalars.shape != (self.grid_resolution, self.grid_resolution):
            raise ValueError(
                f"DisplacementLevel: scalars must be shape "
                f"({self.grid_resolution}, {self.grid_resolution}), "
                f"got {self.scalars.shape}"
            )


@dataclass
class MultiresPatch:
    """A single base-face quad patch with multilevel displacement data.

    Attributes
    ----------
    base_face_id : int
        Index of the base quad face in the control mesh.
    base_corners : list of Vec3
        Four 3D positions at the corners of the base face, ordered:
        (0,0), (1,0), (1,1), (0,1) in (u,v) space (i.e., CCW from bottom-left).
    base_normals : list of Vec3
        Four unit normals at the base face corners in the same order as
        base_corners. Used for bilinear normal interpolation over the patch.
    displacements : list of DisplacementLevel
        One DisplacementLevel per level (0, 1, 2, ...), in order of increasing
        level. Must be monotonically increasing in .level.
    """
    base_face_id: int
    base_corners: List[Vec3]     # 4 positions at (u,v) ∈ {0,1}²
    base_normals: List[Vec3]     # 4 unit normals at corners
    displacements: List[DisplacementLevel]

    def __post_init__(self) -> None:
        if len(self.base_corners) != 4:
            raise ValueError(f"MultiresPatch: need 4 base_corners, got {len(self.base_corners)}")
        if len(self.base_normals) != 4:
            raise ValueError(f"MultiresPatch: need 4 base_normals, got {len(self.base_normals)}")
        for i, dlev in enumerate(self.displacements):
            if dlev.level != i:
                raise ValueError(
                    f"MultiresPatch: displacements must be levels 0,1,2,...; "
                    f"displacements[{i}].level = {dlev.level}"
                )


@dataclass
class MultiresLimitEval:
    """Result of evaluating a MultiresPatch at a parameter (u,v).

    Attributes
    ----------
    position : Vec3
        Displaced limit position: base_position + displacement * normal.
    normal : Vec3
        Unit normal at (u,v) (bilinear interpolation of corner normals, normalized).
    base_position : Vec3
        Un-displaced bilinear position on the base limit surface quad.
    displacement : float
        Total scalar displacement (sum over all requested levels).
    """
    position: Vec3
    normal: Vec3
    base_position: Vec3
    displacement: float


# ---------------------------------------------------------------------------
# Internal vector utilities (matching style of limit_tangent.py)
# ---------------------------------------------------------------------------

def _v3add(a: Vec3, b: Vec3) -> Vec3:
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def _v3scale(s: float, a: Vec3) -> Vec3:
    return (s * a[0], s * a[1], s * a[2])


def _v3norm(a: Vec3) -> float:
    return math.sqrt(a[0]*a[0] + a[1]*a[1] + a[2]*a[2])


def _v3normalize(a: Vec3) -> Vec3:
    n = _v3norm(a)
    if n < 1e-15:
        return (0.0, 0.0, 0.0)
    return (a[0]/n, a[1]/n, a[2]/n)


def _v3dot(a: Vec3, b: Vec3) -> float:
    return a[0]*b[0] + a[1]*b[1] + a[2]*b[2]


# ---------------------------------------------------------------------------
# Bilinear interpolation helpers
# ---------------------------------------------------------------------------

def _bilinear_vec3(
    c00: Vec3, c10: Vec3, c01: Vec3, c11: Vec3,
    u: float, v: float,
) -> Vec3:
    """Bilinear interpolation of four Vec3 corners.

    Corner layout:
        c00 = corner at (u=0, v=0)
        c10 = corner at (u=1, v=0)
        c01 = corner at (u=0, v=1)
        c11 = corner at (u=1, v=1)

    Formula:
        P(u,v) = (1-u)(1-v)·c00 + u(1-v)·c10 + (1-u)v·c01 + uv·c11

    References: Krishnamurthy-Levoy 1996 §3 (bilinear patch parameterization).
    """
    w00 = (1.0 - u) * (1.0 - v)
    w10 = u * (1.0 - v)
    w01 = (1.0 - u) * v
    w11 = u * v
    x = w00*c00[0] + w10*c10[0] + w01*c01[0] + w11*c11[0]
    y = w00*c00[1] + w10*c10[1] + w01*c01[1] + w11*c11[1]
    z = w00*c00[2] + w10*c10[2] + w01*c01[2] + w11*c11[2]
    return (x, y, z)


def _bilinear_scalar_grid(grid: np.ndarray, u: float, v: float) -> float:
    """Bilinear interpolation of a scalar grid at (u, v) ∈ [0, 1]².

    Grid is shape (R, R) where R = grid_resolution.
    grid[row, col] is at (u, v) = (col/(R-1), row/(R-1)).

    For R == 1 (degenerate), returns grid[0, 0].

    Uses bilinear interpolation between the four surrounding grid samples.

    References:
        - Krishnamurthy & Levoy (1996) §3 — per-level bilinear displacement.
        - Cook (1984) — scalar displacement field concept.
    """
    R = grid.shape[0]
    if R == 1:
        return float(grid[0, 0])

    # Map (u,v) → continuous grid index
    # u → col index in [0, R-1]; v → row index in [0, R-1]
    col_f = u * (R - 1)
    row_f = v * (R - 1)

    # Clamp to grid bounds
    col_f = max(0.0, min(float(R - 1), col_f))
    row_f = max(0.0, min(float(R - 1), row_f))

    col0 = int(math.floor(col_f))
    row0 = int(math.floor(row_f))
    col1 = min(col0 + 1, R - 1)
    row1 = min(row0 + 1, R - 1)

    # Fractional parts
    dc = col_f - col0
    dr = row_f - row0

    # Bilinear interpolation: (row, col) = (v-axis, u-axis)
    d00 = float(grid[row0, col0])
    d10 = float(grid[row0, col1])   # u+1, v same
    d01 = float(grid[row1, col0])   # u same, v+1
    d11 = float(grid[row1, col1])

    return (1.0 - dc) * (1.0 - dr) * d00 \
         + dc * (1.0 - dr) * d10 \
         + (1.0 - dc) * dr * d01 \
         + dc * dr * d11


# ---------------------------------------------------------------------------
# Core evaluation
# ---------------------------------------------------------------------------

def evaluate_multires(
    patch: MultiresPatch,
    u: float,
    v: float,
    level: int,
) -> MultiresLimitEval:
    """Evaluate the displaced limit position at (u,v) using levels 0..level.

    Algorithm (Krishnamurthy-Levoy 1996 §3 / Cook 1984):
    1. Compute base limit surface position S(u,v) via bilinear interpolation
       of the four base-face corner positions.
    2. Compute interpolated unit normal n̂(u,v) via bilinear interpolation of
       the four base-face corner normals, then re-normalized.
    3. Total displacement D = Σ_{l=0}^{level} bilinear_interp(displacements[l], u, v).
    4. Displaced position P = S(u,v) + D · n̂(u,v).

    Parameters
    ----------
    patch : MultiresPatch
        The multires patch to evaluate.
    u, v : float
        Parameter values in [0, 1]².
    level : int
        Maximum displacement level to include (0-indexed).
        level=0 uses only the base-level displacements.
        level=k uses levels 0..k (must be ≤ len(patch.displacements)-1).

    Returns
    -------
    MultiresLimitEval
        position  = S(u,v) + D · n̂(u,v)
        normal    = n̂(u,v)  (unit, bilinearly interpolated then re-normalized)
        base_position = S(u,v)  (un-displaced)
        displacement  = D  (total scalar)
    """
    u = float(max(0.0, min(1.0, u)))
    v = float(max(0.0, min(1.0, v)))
    level = max(0, min(level, len(patch.displacements) - 1))

    # Corner ordering: (u=0,v=0)=c00, (u=1,v=0)=c10, (u=0,v=1)=c01, (u=1,v=1)=c11
    c00, c10, c01, c11 = (
        patch.base_corners[0],
        patch.base_corners[1],
        patch.base_corners[2],
        patch.base_corners[3],
    )
    n00, n10, n01, n11 = (
        patch.base_normals[0],
        patch.base_normals[1],
        patch.base_normals[2],
        patch.base_normals[3],
    )

    # Step 1: base surface position via bilinear interpolation of corners
    base_pos = _bilinear_vec3(c00, c10, c01, c11, u, v)

    # Step 2: interpolated normal (re-normalized after bilinear blend)
    raw_normal = _bilinear_vec3(n00, n10, n01, n11, u, v)
    unit_normal = _v3normalize(raw_normal)

    # Step 3: sum displacements across levels 0..level
    total_d = 0.0
    for dlev in patch.displacements[: level + 1]:
        total_d += _bilinear_scalar_grid(dlev.scalars, u, v)

    # Step 4: displaced position
    disp_vec = _v3scale(total_d, unit_normal)
    displaced_pos = _v3add(base_pos, disp_vec)

    return MultiresLimitEval(
        position=displaced_pos,
        normal=unit_normal,
        base_position=base_pos,
        displacement=total_d,
    )


# ---------------------------------------------------------------------------
# Encoding: decompose high-res samples into per-level displacements
# ---------------------------------------------------------------------------

def encode_displacement(
    high_res_positions: np.ndarray,
    base_corners: List[Vec3],
    base_normals: List[Vec3],
    levels: int = 3,
) -> MultiresPatch:
    """Decompose a high-res sampled patch into base + level displacements.

    The encoding follows Krishnamurthy & Levoy (1996) §3:
    1. Level 0: project each sample (at its (u,v) grid point) onto the local
       base limit surface normal, measuring signed distance from the bilinear
       base plane. Store the 2×2 corner samples as DisplacementLevel(level=0).
    2. Level k (k ≥ 1): build the (2^k+1)×(2^k+1) sample grid. For each grid
       point, compute the residual displacement = actual_projection minus the
       sum of all lower-level bilinear reconstructions.

    Parameters
    ----------
    high_res_positions : np.ndarray
        Shape (M, M, 3): 3D positions sampled on the detailed mesh at a
        regular (u,v) grid with M = 2^levels + 1 samples per side.
        Position [row, col] corresponds to (u, v) = (col/(M-1), row/(M-1)).
    base_corners : list of Vec3
        Four corner positions of the base quad face, ordered (0,0),(1,0),(0,1),(1,1).
    base_normals : list of Vec3
        Four unit normals at the base face corners.
    levels : int
        Number of displacement levels to encode (0..levels-1). Default 3.

    Returns
    -------
    MultiresPatch
        Patch with `levels` DisplacementLevel entries.
    """
    if len(base_corners) != 4:
        raise ValueError(f"encode_displacement: need 4 base_corners, got {len(base_corners)}")
    if len(base_normals) != 4:
        raise ValueError(f"encode_displacement: need 4 base_normals, got {len(base_normals)}")

    M = high_res_positions.shape[0]
    if high_res_positions.shape[1] != M:
        raise ValueError("encode_displacement: high_res_positions must be square (M, M, 3)")

    # Expected sample count: 2^levels + 1
    expected_M = (1 << levels) + 1
    if M != expected_M:
        raise ValueError(
            f"encode_displacement: for levels={levels} need M={expected_M} "
            f"samples per side, got {M}"
        )

    # Precompute per-sample (u,v) coordinates
    # u = col/(M-1), v = row/(M-1)
    us = np.linspace(0.0, 1.0, M)  # col axis → u
    vs = np.linspace(0.0, 1.0, M)  # row axis → v

    # For each (row, col) sample, compute the signed displacement:
    # d(row, col) = (high_res_pos - base_pos) · n̂
    # where base_pos and n̂ are bilinearly interpolated from corners.
    c00 = np.array(base_corners[0], dtype=np.float64)
    c10 = np.array(base_corners[1], dtype=np.float64)
    c01 = np.array(base_corners[2], dtype=np.float64)
    c11 = np.array(base_corners[3], dtype=np.float64)
    n00 = np.array(base_normals[0], dtype=np.float64)
    n10 = np.array(base_normals[1], dtype=np.float64)
    n01 = np.array(base_normals[2], dtype=np.float64)
    n11 = np.array(base_normals[3], dtype=np.float64)

    # Build (M, M) arrays of base positions and normals via bilinear interp
    # Shape: (M, M, 3)
    U = us[np.newaxis, :]   # shape (1, M)  — u varies along cols
    V = vs[:, np.newaxis]   # shape (M, 1)  — v varies along rows

    w00 = (1.0 - U) * (1.0 - V)   # (M, M)
    w10 = U * (1.0 - V)
    w01 = (1.0 - U) * V
    w11 = U * V

    # base_pos_grid[row, col] = bilinear(c00, c10, c01, c11, u, v)
    base_pos_grid = (
        w00[:, :, np.newaxis] * c00
        + w10[:, :, np.newaxis] * c10
        + w01[:, :, np.newaxis] * c01
        + w11[:, :, np.newaxis] * c11
    )  # (M, M, 3)

    # raw_normal_grid (before normalization)
    raw_normal_grid = (
        w00[:, :, np.newaxis] * n00
        + w10[:, :, np.newaxis] * n10
        + w01[:, :, np.newaxis] * n01
        + w11[:, :, np.newaxis] * n11
    )  # (M, M, 3)

    # Normalize per sample
    norms = np.linalg.norm(raw_normal_grid, axis=2, keepdims=True)
    norms = np.where(norms < 1e-15, 1.0, norms)
    unit_normal_grid = raw_normal_grid / norms  # (M, M, 3)

    # Signed displacement at each sample:
    # d = (high_res - base_pos) · n̂
    delta = high_res_positions.astype(np.float64) - base_pos_grid  # (M, M, 3)
    full_d = np.einsum("ijk,ijk->ij", delta, unit_normal_grid)  # (M, M)

    # Now build each DisplacementLevel's residual scalars.
    # Level k has resolution R_k = 2^k + 1.
    # Grid sample indices for level k: spaced every (M-1) / (R_k - 1) = 2^(levels-k) apart.
    # The sub-sampled grid at level k covers exactly the full [0,1]² domain.

    displacement_levels: List[DisplacementLevel] = []
    # Accumulated reconstruction at each sample point (for residual computation)
    accumulated = np.zeros((M, M), dtype=np.float64)

    for lev in range(levels):
        R = (1 << lev) + 1  # grid resolution at this level

        # Stride in the full (M×M) grid corresponding to this level's sample points
        stride = (M - 1) // (R - 1)  # always an integer by construction

        # Extract the sub-sampled displacement residuals at this level's grid points
        row_indices = np.arange(R) * stride  # shape (R,)
        col_indices = np.arange(R) * stride  # shape (R,)

        # Grid of residuals: actual displacement minus what accumulated levels explain
        residuals_at_level = full_d[np.ix_(row_indices, col_indices)] \
                             - accumulated[np.ix_(row_indices, col_indices)]

        scalars = residuals_at_level.astype(np.float32)
        displacement_levels.append(DisplacementLevel(
            level=lev,
            face_id=0,
            grid_resolution=R,
            scalars=scalars,
        ))

        # Update accumulated reconstruction:
        # For each sample in the full (M×M) grid, add the bilinear contribution
        # of this level's scalars.
        full_scalars = scalars.astype(np.float64)
        for row in range(M):
            for col in range(M):
                u_s = col / (M - 1)
                v_s = row / (M - 1)
                accumulated[row, col] += _bilinear_scalar_grid(full_scalars, u_s, v_s)

    return MultiresPatch(
        base_face_id=0,
        base_corners=list(base_corners),
        base_normals=list(base_normals),
        displacements=displacement_levels,
    )
