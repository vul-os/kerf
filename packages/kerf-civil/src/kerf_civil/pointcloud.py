"""
kerf_civil.pointcloud — Point-cloud ingest, filtering, and surface extraction.

Supported input formats
-----------------------
* LAS 1.0–1.4 / LAZ (decompressed via laspy when available; LAZ also via lazrs
  or lazperf back-ends bundled with laspy >= 2.0).
* XYZ text — space/tab/comma-delimited with columns X Y Z (optional I R G B).
* PLY ASCII — header + vertex data (x y z fields).

Pipeline
--------
1. Ingest → raw (N, 3+) numpy array of [x, y, z, …].
2. Voxel grid downsample (Zhang et al. 2003) — centroid-of-cell.
3. Progressive Morphological Filter (PMF) ground classification
   (Zhang et al. 2003, IEEE TGRS 41(4):872-882).
4. Ground return → TIN handoff via kerf_civil.tin.build_tin.

References
----------
Zhang, K., Chen, S.-C., Whitman, D., Shyu, M.-L., Yan, J. & Zhang, C. (2003).
  "A Progressive Morphological Filter for Removing Nonground Measurements from
  Airborne LIDAR Data." IEEE Trans. Geosci. Remote Sens. 41(4):872-882.

ASPRS (2019). LAS Specification 1.4-R15.

Public API
----------
read_xyz(path_or_text, *, delimiter=None) -> np.ndarray   shape (N, 3+)
read_ply_ascii(path_or_text) -> np.ndarray                shape (N, 3+)
read_las(path) -> np.ndarray                              shape (N, 3)   (laspy req.)
voxel_downsample(pts, cell_size) -> np.ndarray
pmf_ground_classify(pts, *, cell_size, ...) -> np.ndarray (ground subset)
surface_from_points(pts, *, cell_size, ...) -> TIN
"""

from __future__ import annotations

import io
import math
from pathlib import Path
from typing import Sequence

import numpy as np

from kerf_civil.tin import TIN, build_tin


# ---------------------------------------------------------------------------
# I/O: XYZ ASCII
# ---------------------------------------------------------------------------

def read_xyz(
    source: str | Path | bytes,
    *,
    delimiter: str | None = None,
    skip_header: int = 0,
) -> np.ndarray:
    """
    Parse an XYZ point-cloud text file (space/tab/comma-separated).

    Each data row must contain at least 3 numeric columns (X Y Z).
    Additional columns (Intensity, RGB, …) are retained in the output array.

    Parameters
    ----------
    source    : file path, raw UTF-8 bytes, or multi-line string
    delimiter : column separator (auto-detected when None)
    skip_header : number of header lines to skip

    Returns
    -------
    np.ndarray of shape (N, C) where C >= 3, dtype float64.
    """
    if isinstance(source, (str, bytes)):
        if isinstance(source, bytes):
            text = source.decode("utf-8", errors="replace")
        else:
            text = source
        # Check if it looks like a file path
        if len(text) < 4096 and "\n" not in text and Path(text).exists():
            text = Path(text).read_text()
    else:
        text = Path(source).read_text()

    lines = text.splitlines()
    rows = []
    for line in lines[skip_header:]:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if delimiter is None:
            # Auto-detect: try comma then whitespace
            parts = line.replace(",", " ").split()
        else:
            parts = line.split(delimiter)
        try:
            vals = [float(p) for p in parts]
            if len(vals) >= 3:
                rows.append(vals[:])
        except ValueError:
            continue  # header / comment row

    if not rows:
        raise ValueError("No numeric rows found in XYZ data")

    # Pad to uniform width
    width = max(len(r) for r in rows)
    padded = [r + [0.0] * (width - len(r)) for r in rows]
    return np.array(padded, dtype=np.float64)


# ---------------------------------------------------------------------------
# I/O: PLY ASCII
# ---------------------------------------------------------------------------

def read_ply_ascii(source: str | Path | bytes) -> np.ndarray:
    """
    Parse an ASCII PLY point-cloud file.

    Reads the header to discover x/y/z property column indices, then
    extracts those columns from the vertex element data.

    Parameters
    ----------
    source : file path or raw text/bytes

    Returns
    -------
    np.ndarray of shape (N, 3), dtype float64, columns = [x, y, z].

    Raises
    ------
    ValueError if the PLY is binary-format (not supported) or has no x/y/z.
    """
    if isinstance(source, bytes):
        text = source.decode("utf-8", errors="replace")
    elif isinstance(source, Path):
        text = source.read_text()
    else:
        text = str(source)

    lines = text.splitlines()
    if not lines or lines[0].strip() != "ply":
        raise ValueError("Not a PLY file (missing 'ply' magic header)")

    # --- parse header ---
    n_vertices = 0
    properties: list[str] = []
    in_vertex_element = False
    header_end = 0

    for i, line in enumerate(lines):
        tok = line.strip().split()
        if not tok:
            continue
        if tok[0] == "format":
            if tok[1] != "ascii":
                raise ValueError("Only ASCII PLY supported; got binary format")
        elif tok[0] == "element":
            if tok[1] == "vertex":
                n_vertices = int(tok[2])
                in_vertex_element = True
            else:
                in_vertex_element = False
        elif tok[0] == "property" and in_vertex_element:
            properties.append(tok[-1])
        elif tok[0] == "end_header":
            header_end = i + 1
            break

    try:
        xi = properties.index("x")
        yi = properties.index("y")
        zi = properties.index("z")
    except ValueError as e:
        raise ValueError(f"PLY vertex data missing x/y/z property: {e}") from e

    data_lines = lines[header_end: header_end + n_vertices]
    pts = np.zeros((n_vertices, 3), dtype=np.float64)
    for k, dline in enumerate(data_lines):
        vals = dline.strip().split()
        pts[k, 0] = float(vals[xi])
        pts[k, 1] = float(vals[yi])
        pts[k, 2] = float(vals[zi])

    return pts


# ---------------------------------------------------------------------------
# I/O: LAS / LAZ (requires laspy >= 2.0)
# ---------------------------------------------------------------------------

def read_las(path: str | Path) -> np.ndarray:
    """
    Read a LAS or LAZ file and return (N, 3) float64 array of [X, Y, Z].

    Requires the ``laspy`` package (>= 2.0).  LAZ decompression requires
    either ``lazrs`` or ``lazperf`` (installed automatically with
    ``pip install laspy[lazrs]``).

    Parameters
    ----------
    path : LAS/LAZ file path

    Returns
    -------
    np.ndarray of shape (N, 3), columns = [X, Y, Z] in metres.

    Raises
    ------
    ImportError if laspy is not installed.
    """
    try:
        import laspy
    except ImportError as e:
        raise ImportError(
            "laspy >= 2.0 is required for LAS/LAZ ingest.  "
            "Install with: pip install laspy[lazrs]"
        ) from e

    las = laspy.read(str(path))
    x = np.array(las.x, dtype=np.float64)
    y = np.array(las.y, dtype=np.float64)
    z = np.array(las.z, dtype=np.float64)
    return np.column_stack([x, y, z])


# ---------------------------------------------------------------------------
# Voxel downsample
# ---------------------------------------------------------------------------

def voxel_downsample(pts: np.ndarray, cell_size: float) -> np.ndarray:
    """
    Reduce point density by replacing every voxel cell with the centroid
    of all points falling in that cell.

    Method: Zhang et al. (2003) grid-based decimation; equivalent to the
    VoxelGrid filter in PCL (Rusu & Cousins 2011, ICRA).

    Parameters
    ----------
    pts       : (N, 3+) array — xyz [+ extra columns retained as-is by averaging]
    cell_size : float — voxel edge length in model units (metres)

    Returns
    -------
    np.ndarray of shape (M, C), M <= N — one centroid per occupied voxel.

    Notes
    -----
    For very large point clouds (>10M points) consider chunked processing;
    this implementation loads all grid keys into a Python dict, which uses
    ~200 B per unique voxel.
    """
    if cell_size <= 0:
        raise ValueError(f"cell_size must be > 0, got {cell_size!r}")
    if len(pts) == 0:
        return pts.copy()

    xyz = pts[:, :3]
    ix = np.floor(xyz[:, 0] / cell_size).astype(np.int64)
    iy = np.floor(xyz[:, 1] / cell_size).astype(np.int64)
    iz = np.floor(xyz[:, 2] / cell_size).astype(np.int64)

    # Pack voxel keys into a structured array for fast grouping
    keys = np.column_stack([ix, iy, iz])
    # Lexsort: sort by (iz, iy, ix)
    order = np.lexsort((ix, iy, iz))
    sorted_keys = keys[order]
    sorted_pts = pts[order]

    # Find group boundaries
    diff = np.any(sorted_keys[1:] != sorted_keys[:-1], axis=1)
    boundaries = np.concatenate([[0], np.where(diff)[0] + 1, [len(sorted_pts)]])

    centroids = []
    for start, end in zip(boundaries[:-1], boundaries[1:]):
        centroids.append(sorted_pts[start:end].mean(axis=0))

    return np.array(centroids, dtype=np.float64)


# ---------------------------------------------------------------------------
# Progressive Morphological Filter (PMF) ground classification
# ---------------------------------------------------------------------------

def pmf_ground_classify(
    pts: np.ndarray,
    *,
    cell_size: float = 1.0,
    max_window_size: float = 33.0,
    slope_threshold: float = 0.3,
    initial_distance: float = 0.5,
    max_distance: float = 3.0,
    exponential: bool = True,
) -> np.ndarray:
    """
    Classify ground points using the Progressive Morphological Filter (PMF).

    Method: Zhang et al. (2003) IEEE TGRS 41(4):872-882.

    The algorithm:
    1. Create a minimum-elevation raster at *cell_size* resolution.
    2. Iteratively apply morphological opening (erode then dilate) with
       increasing window sizes W_k.
    3. At each iteration, a point's elevation is compared to the opened
       (lowered) surface.  Points above the adaptive threshold are labelled
       non-ground.
    4. Remaining points are returned as ground.

    Parameters
    ----------
    pts              : (N, 3) array — xyz point cloud
    cell_size        : float — raster cell size (m); recommended 0.5–2.0 m
    max_window_size  : float — maximum morphological window half-size (m); stops iterations
    slope_threshold  : float — terrain slope threshold S (m/m); typical 0.3
    initial_distance : float — initial height threshold d_0 (m); typical 0.5
    max_distance     : float — maximum height threshold d_max (m); typical 3.0
    exponential      : bool  — use exponential window growth (b=2); if False use
                               linear (b=1) per paper §III-A

    Returns
    -------
    np.ndarray of shape (M, 3), M <= N — ground-classified point subset.

    References
    ----------
    Zhang, K., et al. (2003). IEEE TGRS 41(4):872-882. §III Algorithm.
    ASPRS Lidar Committee (2019). LAS Spec 1.4-R15, Class 2 = Ground.
    """
    if len(pts) == 0:
        return pts.copy()

    xy = pts[:, :2]
    z = pts[:, 2]

    # ---- Build minimum-elevation grid ----
    xmin, ymin = xy.min(axis=0)
    xmax, ymax = xy.max(axis=0)

    nx = max(int(math.ceil((xmax - xmin) / cell_size)), 1)
    ny = max(int(math.ceil((ymax - ymin) / cell_size)), 1)

    # Grid of minimum z-values (NaN where no points)
    grid = np.full((ny, nx), np.nan, dtype=np.float64)

    col = ((xy[:, 0] - xmin) / cell_size).astype(int).clip(0, nx - 1)
    row_idx = ((xy[:, 1] - ymin) / cell_size).astype(int).clip(0, ny - 1)

    for i in range(len(pts)):
        r, c = row_idx[i], col[i]
        if np.isnan(grid[r, c]) or z[i] < grid[r, c]:
            grid[r, c] = z[i]

    # Fill NaN gaps via nearest-cell minimum (simple propagation)
    # Iterate once with a 3×3 minimum kernel for any empty cells
    nans = np.isnan(grid)
    if nans.any():
        from numpy.lib.stride_tricks import sliding_window_view  # noqa: F401
        for ri in range(ny):
            for ci in range(nx):
                if np.isnan(grid[ri, ci]):
                    r0, r1 = max(0, ri - 1), min(ny, ri + 2)
                    c0, c1 = max(0, ci - 1), min(nx, ci + 2)
                    patch = grid[r0:r1, c0:c1]
                    valid = patch[~np.isnan(patch)]
                    if valid.size:
                        grid[ri, ci] = valid.min()

    # Still-NaN cells: fill with global minimum
    global_min = np.nanmin(z)
    grid = np.where(np.isnan(grid), global_min, grid)

    # ---- Progressive iterations ----
    b = 2.0 if exponential else 1.0
    k = 1
    w_prev = cell_size
    is_ground = np.ones(len(pts), dtype=bool)

    while True:
        if exponential:
            w_k = cell_size * (2 * b ** k + 1)
        else:
            w_k = cell_size * (2 * k * b + 1)

        if w_k > max_window_size:
            break

        # Morphological opening with window half-size wh (in grid cells)
        wh = max(1, int(round((w_k - cell_size) / (2 * cell_size))))
        opened = _morph_open(grid, wh)

        # Height threshold at this iteration
        if exponential:
            d_k = slope_threshold * (w_k - w_prev) * cell_size + initial_distance
        else:
            d_k = slope_threshold * (w_k - w_prev) * cell_size + initial_distance
        d_k = min(d_k, max_distance)

        # Classify — compare each point's z against opened surface at its cell
        for i in range(len(pts)):
            if not is_ground[i]:
                continue
            r, c = row_idx[i], col[i]
            if z[i] - opened[r, c] > d_k:
                is_ground[i] = False

        w_prev = w_k
        k += 1

    return pts[is_ground].copy()


def _morph_open(grid: np.ndarray, wh: int) -> np.ndarray:
    """
    2-D morphological opening (erosion then dilation) with a flat
    square structuring element of half-size *wh* cells.

    Erosion = minimum filter; Dilation = maximum filter.
    """
    ny, nx = grid.shape

    # Erosion
    eroded = np.empty_like(grid)
    for r in range(ny):
        for c in range(nx):
            r0, r1 = max(0, r - wh), min(ny, r + wh + 1)
            c0, c1 = max(0, c - wh), min(nx, c + wh + 1)
            eroded[r, c] = grid[r0:r1, c0:c1].min()

    # Dilation
    dilated = np.empty_like(eroded)
    for r in range(ny):
        for c in range(nx):
            r0, r1 = max(0, r - wh), min(ny, r + wh + 1)
            c0, c1 = max(0, c - wh), min(nx, c + wh + 1)
            dilated[r, c] = eroded[r0:r1, c0:c1].max()

    return dilated


# ---------------------------------------------------------------------------
# Surface from point cloud → TIN
# ---------------------------------------------------------------------------

def surface_from_points(
    pts: np.ndarray,
    *,
    downsample_cell_size: float | None = 1.0,
    classify_ground: bool = True,
    pmf_kwargs: dict | None = None,
    boundary: list[tuple[float, float]] | None = None,
) -> TIN:
    """
    Full pipeline: voxel downsample → ground classify (PMF) → build TIN.

    Parameters
    ----------
    pts                  : (N, 3) raw point cloud
    downsample_cell_size : voxel cell size (m) for decimation; None = skip
    classify_ground      : run PMF ground filter before building TIN
    pmf_kwargs           : dict of keyword args forwarded to pmf_ground_classify
    boundary             : optional outer boundary polygon [[x, y], …]

    Returns
    -------
    TIN — Delaunay surface ready for contours / volume calculations.
    """
    work = pts[:, :3].copy()

    if downsample_cell_size and downsample_cell_size > 0:
        work = voxel_downsample(work, downsample_cell_size)

    if classify_ground and len(work) > 3:
        kw = pmf_kwargs or {}
        work = pmf_ground_classify(work, **kw)

    if len(work) < 3:
        raise ValueError(
            f"Insufficient ground points ({len(work)}) to build TIN; "
            "reduce cell_size or disable classify_ground"
        )

    return build_tin(work, boundary=boundary)


# ---------------------------------------------------------------------------
# Statistics helpers
# ---------------------------------------------------------------------------

def point_cloud_stats(pts: np.ndarray) -> dict:
    """
    Return summary statistics for a point cloud array.

    Returns dict with n_points, x/y/z min/max/mean, density_per_m2.
    """
    if len(pts) == 0:
        return {"n_points": 0}

    xyz = pts[:, :3]
    xmin, ymin, zmin = xyz.min(axis=0)
    xmax, ymax, zmax = xyz.max(axis=0)
    area = max((xmax - xmin) * (ymax - ymin), 1e-9)

    return {
        "n_points": int(len(pts)),
        "x_min": float(xmin), "x_max": float(xmax),
        "y_min": float(ymin), "y_max": float(ymax),
        "z_min": float(zmin), "z_max": float(zmax),
        "x_range_m": float(xmax - xmin),
        "y_range_m": float(ymax - ymin),
        "z_range_m": float(zmax - zmin),
        "density_per_m2": round(float(len(pts)) / area, 4),
    }
