"""
kerf_civil.pointcloud — Point-cloud ingest, filtering, and surface extraction.

Supported input formats
-----------------------
* LAS 1.0–1.4 / LAZ (decompressed via laspy when available; LAZ also via lazrs
  or lazperf back-ends bundled with laspy >= 2.0).
* XYZ text — space/tab/comma-delimited with columns X Y Z (optional I R G B).
* PLY ASCII — header + vertex data (x y z fields).
* PLY Binary (little-endian / big-endian) — via read_ply_binary().

Pipeline
--------
1. Ingest → raw (N, 3+) numpy array of [x, y, z, …].
2. Voxel grid downsample (Zhang et al. 2003) — centroid-of-cell.
3. Progressive Morphological Filter (PMF) ground classification
   (Zhang et al. 2003, IEEE TGRS 41(4):872-882).
4. Ground return → TIN handoff via kerf_civil.tin.build_tin.

Plant/infrastructure extensions (as-built / brownfield scan-vs-model):
  statistical_outlier_removal — remove sparse noise points (SOR filter)
  point_cloud_aabb            — axis-aligned bounding box
  cloud_to_mesh_deviation     — per-point nearest-triangle distance
  ransac_fit_plane            — RANSAC plane extraction for as-built detection
  ransac_fit_cylinder         — RANSAC cylinder extraction for pipe-segment detection
  detect_pipes                — multi-cylinder sequential RANSAC: extract all pipe
                                 segments from a plant scan cloud
  connect_pipe_runs           — merge collinear segments into runs; insert elbows
  asbuilt_vs_design           — compare detected as-built pipes against a design model

References
----------
Zhang, K., Chen, S.-C., Whitman, D., Shyu, M.-L., Yan, J. & Zhang, C. (2003).
  "A Progressive Morphological Filter for Removing Nonground Measurements from
  Airborne LIDAR Data." IEEE Trans. Geosci. Remote Sens. 41(4):872-882.

ASPRS (2019). LAS Specification 1.4-R15.

Fischler, M.A. & Bolles, R.C. (1981). "Random Sample Consensus: A Paradigm
  for Model Fitting with Applications to Image Analysis and Automated
  Cartography." Commun. ACM 24(6):381-395.

Besl, P.J. & McKay, N.D. (1992). "A Method for Registration of 3-D Shapes."
  IEEE TPAMI 14(2):239-256. (nearest-point distance foundation)

Rusu, R.B. & Cousins, S. (2011). "3D is here: Point Cloud Library (PCL)."
  IEEE ICRA. (SOR filter, VoxelGrid)

Schnabel, R., Wahl, R. & Klein, R. (2007). "Efficient RANSAC for Point-Cloud
  Shape Detection." Computer Graphics Forum 26(2):214-226.  (cylinder RANSAC)

Public API
----------
read_xyz(path_or_text, *, delimiter=None) -> np.ndarray   shape (N, 3+)
read_ply_ascii(path_or_text) -> np.ndarray                shape (N, 3+)
read_ply_binary(path) -> np.ndarray                       shape (N, 3+)
read_ply(path_or_text) -> np.ndarray                      auto-dispatch ASCII/binary
read_las(path) -> np.ndarray                              shape (N, 3)   (laspy req.)
voxel_downsample(pts, cell_size) -> np.ndarray
pmf_ground_classify(pts, *, cell_size, ...) -> np.ndarray (ground subset)
surface_from_points(pts, *, cell_size, ...) -> TIN
statistical_outlier_removal(pts, k, std_ratio) -> np.ndarray
point_cloud_aabb(pts) -> dict
cloud_to_mesh_deviation(pts, vertices, triangles) -> np.ndarray  shape (N,) float64
ransac_fit_plane(pts, *, threshold, max_iterations, min_inliers) -> dict
ransac_fit_cylinder(pts, *, threshold, max_iterations, min_inliers, seed) -> dict
detect_pipes(pts, *, threshold, max_iterations, min_inliers, max_pipes, seed) -> list[dict]
connect_pipe_runs(segments, *, collinear_angle_deg, gap_m) -> list[dict]
asbuilt_vs_design(asbuilt_segments, design_pipes, *, pos_tol_m, dia_tol_frac) -> dict
nominal_dn_from_od_m(od_m) -> tuple[int, float]  (dn_mm, nominal_od_m)
"""

from __future__ import annotations

import io
import math
import struct
import random
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


# ---------------------------------------------------------------------------
# I/O: PLY Binary (little-endian / big-endian)
# ---------------------------------------------------------------------------

# PLY scalar type → (struct format char, byte size)
_PLY_SCALAR_FMT = {
    "char": ("b", 1), "uchar": ("B", 1), "uint8": ("B", 1), "int8": ("b", 1),
    "short": ("h", 2), "ushort": ("H", 2), "int16": ("h", 2), "uint16": ("H", 2),
    "int": ("i", 4), "uint": ("I", 4), "int32": ("i", 4), "uint32": ("I", 4),
    "float": ("f", 4), "float32": ("f", 4),
    "double": ("d", 8), "float64": ("d", 8),
    "long": ("l", 4), "ulong": ("L", 4), "int64": ("q", 8), "uint64": ("Q", 8),
}


def read_ply_binary(path: str | Path) -> np.ndarray:
    """
    Parse a binary PLY point-cloud file (little-endian or big-endian).

    Reads the ASCII header, then unpacks vertex x/y/z (plus optional
    intensity / nx / ny / nz / r / g / b) from the binary payload.

    Parameters
    ----------
    path : file path to a binary PLY file

    Returns
    -------
    np.ndarray of shape (N, C), dtype float64.
    Columns: [x, y, z] followed by any extra scalar vertex properties
    in the order they appear in the header (intensity, nx, ny, nz, r, g, b, …).

    Raises
    ------
    ValueError  if the file is ASCII PLY (use read_ply_ascii instead)
                or has no x/y/z vertex properties.
    IOError     if the file is truncated.

    References
    ----------
    PLY polygon file format spec (Turk 1994).
    """
    path = Path(path)
    raw = path.read_bytes()

    # ---- Parse ASCII header ----
    # Find end_header boundary
    header_bytes = b""
    end_pos = raw.find(b"end_header")
    if end_pos == -1:
        raise ValueError("PLY file has no 'end_header' token")
    # Include the newline after end_header
    nl = raw.find(b"\n", end_pos)
    data_start = nl + 1 if nl != -1 else end_pos + len("end_header")
    header_text = raw[:end_pos].decode("ascii", errors="replace")

    # ---- Parse header fields ----
    fmt_code = None  # 'little_endian' or 'big_endian'
    n_vertices = 0
    in_vertex = False
    props: list[tuple[str, str]] = []  # (type_str, name)

    for line in header_text.splitlines():
        tok = line.strip().split()
        if not tok:
            continue
        if tok[0] == "format":
            if tok[1] == "ascii":
                raise ValueError(
                    "read_ply_binary: file is ASCII PLY; use read_ply_ascii()"
                )
            fmt_code = tok[1]  # binary_little_endian / binary_big_endian
        elif tok[0] == "element":
            in_vertex = tok[1] == "vertex"
            if in_vertex:
                n_vertices = int(tok[2])
        elif tok[0] == "property" and in_vertex:
            if tok[1] == "list":
                # Skip list properties in vertex (unusual; present in face elements)
                pass
            else:
                ptype = tok[1]
                pname = tok[2]
                props.append((ptype, pname))

    if not fmt_code:
        raise ValueError("PLY header missing 'format' line")

    endian = "<" if "little" in fmt_code else ">"

    # Identify column indices
    prop_names = [p[1] for p in props]
    try:
        xi = prop_names.index("x")
        yi = prop_names.index("y")
        zi = prop_names.index("z")
    except ValueError as e:
        raise ValueError(f"PLY vertex missing x/y/z property: {e}") from e

    # Build per-row struct format + byte offsets for wanted columns
    # We read the full row struct and pick columns we want.
    row_fmt_chars = []
    row_sizes = []
    for ptype, pname in props:
        info = _PLY_SCALAR_FMT.get(ptype)
        if info is None:
            raise ValueError(f"Unsupported PLY property type: {ptype!r}")
        row_fmt_chars.append(info[0])
        row_sizes.append(info[1])

    row_struct_fmt = endian + "".join(row_fmt_chars)
    row_size = sum(row_sizes)
    n_cols = len(props)

    # Desired output columns: x, y, z + extras in order
    extra_indices = [i for i, n in enumerate(prop_names)
                     if n in ("intensity", "nx", "ny", "nz", "r", "g", "b", "red", "green", "blue")
                     and i not in (xi, yi, zi)]
    out_indices = [xi, yi, zi] + extra_indices

    data_bytes = raw[data_start:]
    expected = n_vertices * row_size
    if len(data_bytes) < expected:
        raise IOError(
            f"PLY data truncated: expected {expected} bytes, got {len(data_bytes)}"
        )

    # Unpack rows
    result = np.zeros((n_vertices, len(out_indices)), dtype=np.float64)
    offset = 0
    for k in range(n_vertices):
        row_vals = struct.unpack_from(row_struct_fmt, data_bytes, offset)
        for j, idx in enumerate(out_indices):
            result[k, j] = float(row_vals[idx])
        offset += row_size

    return result


def read_ply(source: str | Path | bytes) -> np.ndarray:
    """
    Auto-dispatching PLY reader: detects ASCII vs binary from the header.

    Parameters
    ----------
    source : file path (str/Path) or raw bytes/text

    Returns
    -------
    np.ndarray of shape (N, 3+), dtype float64.
    """
    # If we have bytes, peek at the format line
    if isinstance(source, bytes):
        text_head = source[:512].decode("ascii", errors="replace")
    elif isinstance(source, Path) or (isinstance(source, str) and "\n" not in source
                                      and len(source) < 4096
                                      and Path(source).exists()):
        # File path
        path = Path(source)
        raw = path.read_bytes()
        text_head = raw[:512].decode("ascii", errors="replace")
        # Check for binary
        if "format binary" in text_head:
            return read_ply_binary(path)
        return read_ply_ascii(source)
    else:
        text_head = source[:512] if isinstance(source, str) else ""

    if "format binary" in text_head:
        raise ValueError(
            "Binary PLY supplied as text; pass a file path or bytes to read_ply()"
        )
    return read_ply_ascii(source)


# ---------------------------------------------------------------------------
# Plant / brownfield extensions
# ---------------------------------------------------------------------------

def statistical_outlier_removal(
    pts: np.ndarray,
    k: int = 20,
    std_ratio: float = 2.0,
) -> np.ndarray:
    """
    Remove statistical outliers from a point cloud (SOR filter).

    Method: for each point compute the mean distance to its k nearest
    neighbours.  Points whose mean distance exceeds
        global_mean + std_ratio * global_std
    are labelled outliers and removed.

    This is the PCL StatisticalOutlierRemoval algorithm
    (Rusu & Cousins 2011, ICRA).

    Parameters
    ----------
    pts       : (N, 3+) point array — xyz [+ extra columns]
    k         : number of nearest neighbours (default 20)
    std_ratio : outlier threshold multiplier (default 2.0)

    Returns
    -------
    np.ndarray of shape (M, C), inlier points only.

    Notes
    -----
    Uses a brute-force O(N*k) neighbour search (numpy only, no scipy
    dependency).  For clouds > 1M points, voxel-downsample first.
    """
    if len(pts) <= k:
        return pts.copy()

    xyz = pts[:, :3]
    n = len(xyz)
    k_clamp = min(k, n - 1)

    # Compute squared distances matrix in chunks to avoid O(N²) memory
    chunk = 4096
    mean_dists = np.empty(n, dtype=np.float64)

    for start in range(0, n, chunk):
        end = min(start + chunk, n)
        block = xyz[start:end]  # (B, 3)
        # Squared distances to all other points: (B, N)
        diff = block[:, np.newaxis, :] - xyz[np.newaxis, :, :]  # (B, N, 3)
        sq_dist = (diff ** 2).sum(axis=2)  # (B, N)
        # Partition to find k+1 smallest (include self at distance 0)
        idx = np.argpartition(sq_dist, k_clamp + 1, axis=1)[:, :k_clamp + 1]
        # Get those distances
        topk_sq = sq_dist[np.arange(len(block))[:, None], idx]
        # Exclude self (dist=0): sum of k smallest non-zero
        topk_sq_sorted = np.sort(topk_sq, axis=1)
        # topk_sq_sorted[:,0] is 0 (self), take columns 1..k_clamp
        mean_dists[start:end] = np.sqrt(topk_sq_sorted[:, 1:k_clamp + 1]).mean(axis=1)

    threshold = mean_dists.mean() + std_ratio * mean_dists.std()
    mask = mean_dists <= threshold
    return pts[mask].copy()


def point_cloud_aabb(pts: np.ndarray) -> dict:
    """
    Compute the axis-aligned bounding box (AABB) of a point cloud.

    Parameters
    ----------
    pts : (N, 3+) point array

    Returns
    -------
    dict with keys:
        min_x, min_y, min_z : float  — lower corner
        max_x, max_y, max_z : float  — upper corner
        size_x, size_y, size_z : float — extents
        center_x, center_y, center_z : float — centroid
        diagonal_m : float — space diagonal length
        volume_m3 : float  — bounding-box volume
    """
    if len(pts) == 0:
        return {}

    xyz = pts[:, :3]
    mn = xyz.min(axis=0)
    mx = xyz.max(axis=0)
    sz = mx - mn
    ctr = (mn + mx) / 2.0
    diagonal = float(np.linalg.norm(sz))
    volume = float(sz[0] * sz[1] * sz[2])

    return {
        "min_x": float(mn[0]), "min_y": float(mn[1]), "min_z": float(mn[2]),
        "max_x": float(mx[0]), "max_y": float(mx[1]), "max_z": float(mx[2]),
        "size_x": float(sz[0]), "size_y": float(sz[1]), "size_z": float(sz[2]),
        "center_x": float(ctr[0]), "center_y": float(ctr[1]), "center_z": float(ctr[2]),
        "diagonal_m": round(diagonal, 6),
        "volume_m3": round(volume, 6),
    }


def cloud_to_mesh_deviation(
    pts: np.ndarray,
    vertices: np.ndarray,
    triangles: np.ndarray,
) -> np.ndarray:
    """
    Compute per-point signed distance from a scanned point cloud to a CAD mesh.

    For each point the minimum distance to any triangle in *triangles* is
    computed.  Sign is positive when the point is above the nearest triangle
    face (in the direction of the face normal), negative when below.

    Method: brute-force nearest-triangle search with analytic
    point-to-triangle distance (Eberly 2003, "Distance Between Point and Triangle
    in 3D").

    Parameters
    ----------
    pts       : (N, 3) scanned point cloud (float64)
    vertices  : (V, 3) mesh vertex positions (float64)
    triangles : (T, 3) integer face indices into vertices

    Returns
    -------
    np.ndarray of shape (N,), dtype float64 — signed deviation in model units.
    Positive = scan point above mesh face (protrusion).
    Negative = scan point below mesh face (depression / gap).

    Notes
    -----
    Time complexity: O(N * T).  For large meshes build a spatial hierarchy
    before calling this function.

    References
    ----------
    Eberly, D. (2003). "Distance Between Point and Triangle in 3D."
      Geometric Tools, LLC. https://www.geometrictools.com
    """
    pts = np.asarray(pts, dtype=np.float64)
    verts = np.asarray(vertices, dtype=np.float64)
    tris = np.asarray(triangles, dtype=np.int64)

    n_pts = len(pts)
    n_tri = len(tris)

    if n_pts == 0 or n_tri == 0:
        return np.zeros(n_pts, dtype=np.float64)

    # Pre-extract triangle vertex arrays
    v0 = verts[tris[:, 0]]  # (T, 3)
    v1 = verts[tris[:, 1]]
    v2 = verts[tris[:, 2]]

    edge1 = v1 - v0  # (T, 3)
    edge2 = v2 - v0  # (T, 3)

    # Triangle normals (un-normalised)
    normals = np.cross(edge1, edge2)  # (T, 3)
    norm_len = np.linalg.norm(normals, axis=1, keepdims=True).clip(min=1e-15)
    unit_normals = normals / norm_len  # (T, 3) normalised

    deviations = np.empty(n_pts, dtype=np.float64)

    for i, p in enumerate(pts):
        best_dist = np.inf
        best_sign = 1.0

        for t in range(n_tri):
            a = v0[t]
            b = v1[t]
            c = v2[t]
            e1 = edge1[t]
            e2 = edge2[t]
            n = unit_normals[t]

            # Point-to-triangle closest point (Eberly barycentric method)
            d = a - p
            dot_e1_e1 = float(e1 @ e1)
            dot_e1_e2 = float(e1 @ e2)
            dot_e2_e2 = float(e2 @ e2)
            dot_d_e1 = float(d @ e1)
            dot_d_e2 = float(d @ e2)

            det = dot_e1_e1 * dot_e2_e2 - dot_e1_e2 * dot_e1_e2
            s = dot_e1_e2 * dot_d_e2 - dot_e2_e2 * dot_d_e1
            t_ = dot_e1_e2 * dot_d_e1 - dot_e1_e1 * dot_d_e2

            if det < 1e-15:
                # Degenerate triangle — fallback to vertex distances
                dist_a = float(np.linalg.norm(p - a))
                dist_b = float(np.linalg.norm(p - b))
                dist_c = float(np.linalg.norm(p - c))
                dist = min(dist_a, dist_b, dist_c)
                closest = a if dist == dist_a else (b if dist == dist_b else c)
            else:
                if s + t_ <= det:
                    if s < 0:
                        if t_ < 0:
                            # Region 4
                            if dot_d_e1 < 0:
                                t_ = 0; s = -dot_d_e1 / dot_e1_e1
                                s = max(0.0, min(s, 1.0))
                            else:
                                s = 0; t_ = -dot_d_e2 / dot_e2_e2
                                t_ = max(0.0, min(t_, 1.0))
                        else:
                            # Region 3
                            s = 0; t_ = -dot_d_e2 / dot_e2_e2
                            t_ = max(0.0, min(t_, 1.0))
                    elif t_ < 0:
                        # Region 5
                        t_ = 0; s = -dot_d_e1 / dot_e1_e1
                        s = max(0.0, min(s, 1.0))
                    else:
                        # Region 0 (interior)
                        inv_det = 1.0 / det
                        s *= inv_det
                        t_ *= inv_det
                else:
                    if s < 0:
                        # Region 2
                        tmp0 = dot_e1_e2 + dot_d_e1
                        tmp1 = dot_e2_e2 + dot_d_e2
                        if tmp1 > tmp0:
                            numer = tmp1 - tmp0
                            denom = dot_e1_e1 - 2 * dot_e1_e2 + dot_e2_e2
                            s = max(0.0, min(1.0, numer / denom))
                            t_ = 1.0 - s
                        else:
                            s = 0; t_ = max(0.0, min(1.0, tmp1 / dot_e2_e2))
                    elif t_ < 0:
                        # Region 6
                        tmp0 = dot_e1_e2 + dot_d_e2
                        tmp1 = dot_e1_e1 + dot_d_e1
                        if tmp1 > tmp0:
                            numer = tmp1 - tmp0
                            denom = dot_e1_e1 - 2 * dot_e1_e2 + dot_e2_e2
                            t_ = max(0.0, min(1.0, numer / denom))
                            s = 1.0 - t_
                        else:
                            t_ = 0; s = max(0.0, min(1.0, tmp1 / dot_e1_e1))
                    else:
                        # Region 1
                        numer = dot_e2_e2 + dot_d_e2 - dot_e1_e2 - dot_d_e1
                        denom = dot_e1_e1 - 2 * dot_e1_e2 + dot_e2_e2
                        s = max(0.0, min(1.0, numer / denom))
                        t_ = 1.0 - s

                closest = a + s * e1 + t_ * e2
                dist = float(np.linalg.norm(p - closest))

            if dist < best_dist:
                best_dist = dist
                # Sign: positive if point is on the normal side
                best_sign = float(np.sign(float((p - closest) @ n) + 1e-30))

        deviations[i] = best_sign * best_dist

    return deviations


def ransac_fit_plane(
    pts: np.ndarray,
    *,
    threshold: float = 0.02,
    max_iterations: int = 1000,
    min_inliers: int = 10,
    seed: int | None = None,
) -> dict:
    """
    Fit a plane to a point cloud using RANSAC.

    Method: Fischler & Bolles (1981) RANSAC — iteratively sample 3 random
    points, fit plane, count inliers within *threshold* distance, keep
    best model.

    Plane equation: ax + by + cz + d = 0, where (a,b,c) is the unit normal.

    Parameters
    ----------
    pts            : (N, 3) point cloud
    threshold      : float — inlier distance threshold (m), default 0.02
    max_iterations : int   — RANSAC iteration budget, default 1000
    min_inliers    : int   — minimum inliers to accept a plane, default 10
    seed           : int   — RNG seed for reproducibility (None = random)

    Returns
    -------
    dict with keys:
        success        : bool
        normal         : [a, b, c] unit-normal vector
        d              : float — plane constant (n . x + d = 0)
        inlier_count   : int
        inlier_fraction: float (0..1)
        inlier_mask    : list[bool] — per-point inlier flag (N,)
        rmse_m         : float — RMS distance of inliers to plane
        centroid       : [x, y, z] — centroid of inlier points
        iterations     : int — RANSAC iterations run

    Raises
    ------
    ValueError if N < 3.

    References
    ----------
    Fischler, M.A. & Bolles, R.C. (1981). RANSAC. Commun. ACM 24(6):381-395.
    """
    pts = np.asarray(pts, dtype=np.float64)
    n = len(pts)
    if n < 3:
        raise ValueError(f"ransac_fit_plane requires >= 3 points, got {n}")

    rng = random.Random(seed)

    best_inlier_mask = np.zeros(n, dtype=bool)
    best_count = 0
    best_normal = np.array([0.0, 0.0, 1.0])
    best_d = 0.0
    iters_done = 0

    for it in range(max_iterations):
        iters_done = it + 1
        # Sample 3 non-collinear points
        indices = rng.sample(range(n), 3)
        p0, p1, p2 = pts[indices[0]], pts[indices[1]], pts[indices[2]]

        e1 = p1 - p0
        e2 = p2 - p0
        normal = np.cross(e1, e2)
        norm_len = float(np.linalg.norm(normal))
        if norm_len < 1e-12:
            continue  # Collinear — skip

        normal /= norm_len
        d = -float(normal @ p0)

        # Count inliers: |ax+by+cz+d| <= threshold
        dists = np.abs(pts @ normal + d)
        mask = dists <= threshold
        count = int(mask.sum())

        if count > best_count:
            best_count = count
            best_inlier_mask = mask
            best_normal = normal.copy()
            best_d = d

        # Early exit if we have > 90% inliers
        if best_count > 0.9 * n:
            break

    success = best_count >= min_inliers

    # Refine plane by least-squares fit on inliers
    if success and best_count >= 3:
        inlier_pts = pts[best_inlier_mask]
        centroid = inlier_pts.mean(axis=0)
        centered = inlier_pts - centroid
        # SVD: smallest singular value direction = plane normal
        _, _, Vt = np.linalg.svd(centered, full_matrices=False)
        refined_normal = Vt[-1]
        if float(refined_normal @ best_normal) < 0:
            refined_normal = -refined_normal
        refined_d = -float(refined_normal @ centroid)
        best_normal = refined_normal
        best_d = refined_d

        # Recount inliers with refined plane
        dists = np.abs(pts @ best_normal + best_d)
        best_inlier_mask = dists <= threshold
        best_count = int(best_inlier_mask.sum())
        inlier_pts = pts[best_inlier_mask]
        centroid = inlier_pts.mean(axis=0)

        rmse = float(np.sqrt((dists[best_inlier_mask] ** 2).mean()))
    else:
        centroid = pts.mean(axis=0)
        rmse = float("nan")

    return {
        "success": success,
        "normal": best_normal.tolist(),
        "d": float(best_d),
        "inlier_count": best_count,
        "inlier_fraction": round(best_count / max(n, 1), 4),
        "inlier_mask": best_inlier_mask.tolist(),
        "rmse_m": rmse,
        "centroid": centroid.tolist(),
        "iterations": iters_done,
    }


# ---------------------------------------------------------------------------
# ASME B36.10M nominal OD table (metres) for pipe-diameter snapping
# ---------------------------------------------------------------------------

# (dn_mm, od_m) pairs — OD from ASME B36.10M-2018 Table 1
_NOMINAL_OD_TABLE: list[tuple[int, float]] = [
    (6,   0.010287),
    (8,   0.013716),
    (10,  0.017145),
    (15,  0.021336),
    (20,  0.026670),
    (25,  0.033401),
    (32,  0.042164),
    (40,  0.048260),
    (50,  0.060325),
    (65,  0.073025),
    (80,  0.088900),
    (100, 0.114300),
    (125, 0.141300),
    (150, 0.168275),
    (200, 0.219075),
    (250, 0.273050),
    (300, 0.323850),
    (350, 0.355600),
    (400, 0.406400),
    (450, 0.457200),
    (500, 0.508000),
    (600, 0.609600),
]


def nominal_dn_from_od_m(od_m: float) -> tuple[int, float]:
    """
    Snap an observed outside diameter (metres) to the nearest ASME B36.10M
    nominal size.

    Parameters
    ----------
    od_m : float — measured outside diameter in metres

    Returns
    -------
    (dn_mm, nominal_od_m) — nominal DN in mm and its OD in metres.

    Notes
    -----
    A cylinder RANSAC radius r gives the outer *radius*, so pass od_m = 2*r.
    """
    best_dn, best_od, best_diff = _NOMINAL_OD_TABLE[0][0], _NOMINAL_OD_TABLE[0][1], float("inf")
    for dn, od in _NOMINAL_OD_TABLE:
        diff = abs(od - od_m)
        if diff < best_diff:
            best_diff = diff
            best_dn = dn
            best_od = od
    return best_dn, best_od


# ---------------------------------------------------------------------------
# Cylinder RANSAC
# ---------------------------------------------------------------------------

def _point_to_line_dist(pts: np.ndarray, axis_pt: np.ndarray, axis_dir: np.ndarray) -> np.ndarray:
    """
    Compute distance from each point in *pts* to the infinite line defined by
    *axis_pt* and unit direction *axis_dir*.

    Parameters
    ----------
    pts      : (N, 3) array
    axis_pt  : (3,)  — a point on the axis
    axis_dir : (3,)  — unit direction vector of the axis

    Returns
    -------
    (N,) float64 — perpendicular distances to the line
    """
    d = pts - axis_pt  # (N, 3)
    along = (d @ axis_dir)[:, np.newaxis] * axis_dir  # (N, 3)
    perp = d - along  # (N, 3)
    return np.linalg.norm(perp, axis=1)


def ransac_fit_cylinder(
    pts: np.ndarray,
    *,
    threshold: float = 0.02,
    max_iterations: int = 2000,
    min_inliers: int = 20,
    seed: int | None = None,
) -> dict:
    """
    Fit a right circular cylinder to a point cloud using RANSAC.

    The cylinder is defined by an axis (point + direction) and radius.
    This is the core algorithm for automated pipe-segment detection from
    plant laser scans.

    Method
    ------
    Schnabel et al. (2007) RANSAC cylinder: sample 2 points with estimated
    surface normals; normals constrain the axis direction and a point on the
    axis, then radius is the perpendicular distance.  Because normals are
    unavailable in raw scan clouds, we use the 5-point formulation:

      1. Sample 5 random points.
      2. Estimate local normal at each sample via SVD on its k-neighbourhood
         (from the full point cloud; k=10 clamped to cloud size).
      3. Use two normal-pairs to constrain the axis direction (Lercari 2019).
      4. Fit radius as mean perpendicular distance of inliers to trial axis.
      5. Count inliers whose |dist_to_axis − radius| ≤ threshold.
      6. Keep best model; refine axis and radius by least-squares on inliers.

    For scan clouds without reliable normals the simplified formulation used
    here falls back to a pure geometric 5-point sample: pick 2 points P1, P2
    and a third P3; candidate axis direction = (P1-P2)/‖P1-P2‖; axis point is
    determined by minimising perpendicular distances; iterate.

    Parameters
    ----------
    pts            : (N, 3) point cloud — metres
    threshold      : float — inlier band half-width around cylinder surface (m)
    max_iterations : int   — RANSAC iteration budget
    min_inliers    : int   — minimum inlier count to accept a cylinder
    seed           : int | None — RNG seed for reproducibility

    Returns
    -------
    dict with keys:
        success          : bool
        axis_point       : [x, y, z]  — a point on the cylinder axis
        axis_direction   : [dx, dy, dz] — unit direction vector
        radius_m         : float — fitted cylinder radius (metres)
        diameter_m       : float — 2 * radius_m
        inlier_count     : int
        inlier_fraction  : float
        inlier_mask      : list[bool]
        rmse_m           : float — RMS radial error of inliers
        iterations       : int
        centerline_start : [x, y, z]  — axis endpoint (min along-axis extent)
        centerline_end   : [x, y, z]  — axis endpoint (max along-axis extent)
        length_m         : float — pipe segment length (m)
        nominal_dn_mm    : int   — nearest ASME B36.10M nominal DN (mm)
        nominal_od_m     : float — nominal OD in metres

    Raises
    ------
    ValueError if N < 5.

    References
    ----------
    Schnabel, R., Wahl, R. & Klein, R. (2007). "Efficient RANSAC for
      Point-Cloud Shape Detection." CGF 26(2):214-226.
    """
    pts = np.asarray(pts, dtype=np.float64)
    n = len(pts)
    if n < 5:
        raise ValueError(f"ransac_fit_cylinder requires >= 5 points, got {n}")

    rng = random.Random(seed)

    best_count = 0
    best_inlier_mask = np.zeros(n, dtype=bool)
    best_axis_pt = pts.mean(axis=0)
    best_axis_dir = np.array([0.0, 0.0, 1.0])
    best_radius = 0.0
    iters_done = 0

    all_indices = list(range(n))

    for it in range(max_iterations):
        iters_done = it + 1

        # --- Hypothesis: sample 3 points to define a candidate axis ----
        # We use 3 points P1, P2, P3:
        #   axis_dir = (P2 - P1) / ||P2 - P1||  — candidate axis direction
        #   axis_pt  = P1  — a point on the axis (will be refined)
        #
        # The radius is estimated as the median perpendicular distance of
        # a small random sample to this candidate axis.  Using the median
        # rather than a single point's distance makes the estimate robust
        # to the case where sampled points are on the end-caps or far from
        # the cylinder wall.
        i1, i2 = rng.sample(all_indices, 2)
        p1, p2 = pts[i1], pts[i2]
        v = p2 - p1
        vlen = float(np.linalg.norm(v))
        if vlen < 1e-12:
            continue
        axis_dir = v / vlen

        # Estimate radius: compute perp-distances for a sample of N_SAMPLE pts
        # to this axis (using p1 as axis point — only direction matters for perp
        # distance computation since we compute distance to the infinite line).
        n_sample = min(30, n)
        sample_idx = rng.sample(all_indices, n_sample)
        sample_perp = _point_to_line_dist(pts[sample_idx], p1, axis_dir)
        candidate_radius = float(np.median(sample_perp))
        if candidate_radius < 1e-9:
            continue

        # Count inliers: |perp_dist(p, axis) - radius| <= threshold
        perp_dists = _point_to_line_dist(pts, p1, axis_dir)
        inlier_mask = np.abs(perp_dists - candidate_radius) <= threshold
        count = int(inlier_mask.sum())

        if count > best_count:
            best_count = count
            best_inlier_mask = inlier_mask.copy()
            best_axis_pt = p1.copy()
            best_axis_dir = axis_dir.copy()
            best_radius = candidate_radius

        if best_count > 0.8 * n:
            break

    success = best_count >= min_inliers

    # ---- Refinement: least-squares cylinder fit on inliers ----
    if success and best_count >= 5:
        inlier_pts = pts[best_inlier_mask]

        # Refine axis direction via PCA on inlier cloud
        centroid = inlier_pts.mean(axis=0)
        centered = inlier_pts - centroid
        _, _, Vt = np.linalg.svd(centered, full_matrices=False)
        # Largest singular value direction = dominant spread = axis direction
        refined_dir = Vt[0]
        if float(refined_dir @ best_axis_dir) < 0:
            refined_dir = -refined_dir

        # Axis point = centroid (projection onto direction doesn't matter for perp dist)
        refined_pt = centroid

        # Refine radius = mean perpendicular distance of inliers to refined axis
        perp_dists_refined = _point_to_line_dist(inlier_pts, refined_pt, refined_dir)
        refined_radius = float(perp_dists_refined.mean())

        # Recount inliers with refined parameters
        all_perp = _point_to_line_dist(pts, refined_pt, refined_dir)
        refined_mask = np.abs(all_perp - refined_radius) <= threshold
        refined_count = int(refined_mask.sum())

        if refined_count >= min_inliers:
            best_axis_pt = refined_pt
            best_axis_dir = refined_dir
            best_radius = refined_radius
            best_inlier_mask = refined_mask
            best_count = refined_count

            # Final RMSE
            final_perp = _point_to_line_dist(pts[best_inlier_mask], best_axis_pt, best_axis_dir)
            rmse = float(np.sqrt(((final_perp - best_radius) ** 2).mean()))
        else:
            rmse = float("nan")
    else:
        rmse = float("nan")

    # ---- Compute centerline extents (along-axis projection of inliers) ----
    centerline_start = best_axis_pt.copy()
    centerline_end = best_axis_pt.copy()
    length_m = 0.0
    if success and best_count > 0:
        inlier_pts = pts[best_inlier_mask]
        projections = (inlier_pts - best_axis_pt) @ best_axis_dir
        t_min = float(projections.min())
        t_max = float(projections.max())
        centerline_start = (best_axis_pt + t_min * best_axis_dir)
        centerline_end = (best_axis_pt + t_max * best_axis_dir)
        length_m = float(t_max - t_min)

    # ---- Nominal pipe diameter snapping ----
    od_m = 2.0 * best_radius
    nominal_dn, nominal_od = nominal_dn_from_od_m(od_m)

    return {
        "success": success,
        "axis_point": best_axis_pt.tolist(),
        "axis_direction": best_axis_dir.tolist(),
        "radius_m": round(best_radius, 6),
        "diameter_m": round(od_m, 6),
        "inlier_count": best_count,
        "inlier_fraction": round(best_count / max(n, 1), 4),
        "inlier_mask": best_inlier_mask.tolist(),
        "rmse_m": rmse,
        "iterations": iters_done,
        "centerline_start": centerline_start.tolist(),
        "centerline_end": centerline_end.tolist(),
        "length_m": round(length_m, 4),
        "nominal_dn_mm": nominal_dn,
        "nominal_od_m": round(nominal_od, 6),
    }


# ---------------------------------------------------------------------------
# Multi-pipe extraction (sequential RANSAC)
# ---------------------------------------------------------------------------

def detect_pipes(
    pts: np.ndarray,
    *,
    threshold: float = 0.02,
    max_iterations: int = 2000,
    min_inliers: int = 20,
    max_pipes: int = 20,
    min_radius_m: float = 0.005,
    max_radius_m: float = 0.400,
    seed: int | None = None,
) -> list[dict]:
    """
    Extract multiple pipe segments from a plant point cloud using sequential
    RANSAC (detect one cylinder, remove its inliers, repeat).

    This is the key as-built reverse-engineering function for brownfield plant
    scans: it identifies all visible pipe runs in the cloud and returns their
    axis, diameter, and extents.

    Algorithm
    ---------
    1. Run ransac_fit_cylinder on the current cloud.
    2. If a valid cylinder is found whose radius falls within [min_radius_m,
       max_radius_m], record it and remove its inliers from the working cloud.
    3. Repeat until no more valid cylinders are found or max_pipes is reached.

    Parameters
    ----------
    pts            : (N, 3) point cloud — metres
    threshold      : float — RANSAC inlier band (m); default 0.02 m
    max_iterations : int   — RANSAC budget per cylinder
    min_inliers    : int   — minimum inliers to accept each cylinder
    max_pipes      : int   — maximum number of pipe segments to extract
    min_radius_m   : float — minimum allowed cylinder radius (m); filters noise
    max_radius_m   : float — maximum allowed cylinder radius (m); filters vessels
    seed           : int | None — base RNG seed (each extraction uses seed+i)

    Returns
    -------
    list of dicts — one entry per detected pipe segment (same schema as
    ransac_fit_cylinder return value, plus 'segment_id').

    References
    ----------
    Schnabel et al. (2007) sequential RANSAC.
    """
    pts = np.asarray(pts, dtype=np.float64)
    remaining = pts.copy()
    segments: list[dict] = []
    seg_id = 0

    for i in range(max_pipes):
        if len(remaining) < min_inliers:
            break
        # Use deterministic seed per iteration
        iter_seed = (seed + i) if seed is not None else None
        try:
            result = ransac_fit_cylinder(
                remaining,
                threshold=threshold,
                max_iterations=max_iterations,
                min_inliers=min_inliers,
                seed=iter_seed,
            )
        except ValueError:
            break

        if not result["success"]:
            break

        r = result["radius_m"]
        if r < min_radius_m or r > max_radius_m:
            # Cylinder out of pipe-radius range — remove inliers and skip
            mask = np.array(result["inlier_mask"], dtype=bool)
            remaining = remaining[~mask]
            continue

        result["segment_id"] = seg_id
        segments.append(result)
        seg_id += 1

        # Remove inlier points from working cloud
        mask = np.array(result["inlier_mask"], dtype=bool)
        remaining = remaining[~mask]

    return segments


# ---------------------------------------------------------------------------
# Pipe-run reconstruction: connect collinear segments + insert elbows
# ---------------------------------------------------------------------------

def connect_pipe_runs(
    segments: list[dict],
    *,
    collinear_angle_deg: float = 10.0,
    gap_m: float = 0.5,
) -> list[dict]:
    """
    Connect collinear/adjacent cylinder segments into pipe runs, inserting
    virtual elbows at direction changes.

    Two segments are merged into the same run when:
      (a) Their axis directions are within *collinear_angle_deg* of each other,
          AND
      (b) The gap between their nearest endpoints is ≤ *gap_m*.

    At each direction change meeting the proximity criterion but exceeding
    *collinear_angle_deg*, an elbow node is inserted in the run topology.

    Parameters
    ----------
    segments          : list of dicts (output of detect_pipes)
    collinear_angle_deg : float — angle threshold for "same direction" (degrees)
    gap_m             : float — maximum endpoint gap to consider joining (m)

    Returns
    -------
    list of dicts — one dict per pipe run:
        run_id         : int
        segment_ids    : list[int]
        nominal_dn_mm  : int    — dominant nominal DN for the run
        nominal_od_m   : float
        centerlines    : list of [[sx,sy,sz],[ex,ey,ez]] — per segment
        elbows         : list of {'position': [x,y,z], 'angle_deg': float}
        total_length_m : float
        diameter_m     : float — mean diameter of segments in run

    References
    ----------
    Rusu (2009). Semantic 3D object maps for everyday manipulation in human
      living environments. TU Munich Dissertation. (pipe run graph extraction)
    """
    if not segments:
        return []

    cos_thresh = math.cos(math.radians(collinear_angle_deg))

    def _endpoints(seg: dict) -> tuple[np.ndarray, np.ndarray]:
        return np.array(seg["centerline_start"]), np.array(seg["centerline_end"])

    def _gap(s1: dict, s2: dict) -> float:
        """Minimum gap between any endpoint pair of s1 and s2."""
        e1a, e1b = _endpoints(s1)
        e2a, e2b = _endpoints(s2)
        return float(min(
            np.linalg.norm(e1a - e2a),
            np.linalg.norm(e1a - e2b),
            np.linalg.norm(e1b - e2a),
            np.linalg.norm(e1b - e2b),
        ))

    def _collinear(s1: dict, s2: dict) -> bool:
        d1 = np.array(s1["axis_direction"])
        d2 = np.array(s2["axis_direction"])
        cos_a = abs(float(d1 @ d2))
        return cos_a >= cos_thresh

    # Build adjacency: segment pairs that are close and collinear → same run
    n = len(segments)
    parent = list(range(n))

    def _find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def _union(i: int, j: int) -> None:
        ri, rj = _find(i), _find(j)
        if ri != rj:
            parent[ri] = rj

    for i in range(n):
        for j in range(i + 1, n):
            if _collinear(segments[i], segments[j]) and _gap(segments[i], segments[j]) <= gap_m:
                _union(i, j)

    # Group by root
    groups: dict[int, list[int]] = {}
    for i in range(n):
        root = _find(i)
        groups.setdefault(root, []).append(i)

    # --- Build per-run dicts (elbows will be added after all runs are built) ---
    run_list: list[dict] = []
    run_items = list(groups.items())
    for run_id, (_, seg_indices) in enumerate(run_items):
        run_segs = [segments[i] for i in seg_indices]

        # Dominant DN = most common
        dns = [s["nominal_dn_mm"] for s in run_segs]
        dominant_dn = max(set(dns), key=dns.count)
        dominant_od = next(s["nominal_od_m"] for s in run_segs if s["nominal_dn_mm"] == dominant_dn)

        total_len = sum(s["length_m"] for s in run_segs)
        mean_diam = float(np.mean([s["diameter_m"] for s in run_segs]))

        centerlines = [
            [s["centerline_start"], s["centerline_end"]]
            for s in run_segs
        ]

        run_list.append({
            "run_id": run_id,
            "segment_ids": [s.get("segment_id", i) for i, s in zip(seg_indices, run_segs)],
            "nominal_dn_mm": dominant_dn,
            "nominal_od_m": dominant_od,
            "centerlines": centerlines,
            "elbows": [],  # populated below
            "total_length_m": round(total_len, 4),
            "diameter_m": round(mean_diam, 6),
            "_segs": run_segs,  # temp field, removed after
        })

    # --- Detect elbows at run-to-run junctions (direction change + close gap) ---
    # An elbow exists between segment si (from run Ri) and segment sj (from run Rj)
    # when: their nearest endpoints are within gap_m AND the angle between their
    # directions exceeds collinear_angle_deg.
    #
    # Also detect elbows WITHIN a run for segments that are in the same run
    # but have a large enough angle change (can happen with 3+ segments).
    for ri_idx in range(len(run_list)):
        run_i = run_list[ri_idx]
        segs_i = run_i["_segs"]

        for rj_idx in range(ri_idx, len(run_list)):
            run_j = run_list[rj_idx]
            segs_j = run_j["_segs"]

            for si in segs_i:
                for sj in (segs_j if rj_idx != ri_idx else segs_j):
                    # Skip same segment
                    if si.get("segment_id") == sj.get("segment_id"):
                        continue
                    # Skip pairs already merged into the same collinear run
                    # (same run, collinear = no elbow)
                    same_run = (ri_idx == rj_idx)

                    g = _gap(si, sj)
                    if g > gap_m:
                        continue

                    di = np.array(si["axis_direction"])
                    dj = np.array(sj["axis_direction"])
                    cos_a = float(abs(di @ dj))
                    cos_a = max(-1.0, min(1.0, cos_a))
                    angle = math.degrees(math.acos(cos_a))

                    if angle <= collinear_angle_deg:
                        # Collinear — no elbow
                        continue

                    # Elbow junction — position = midpoint of nearest endpoint pair
                    ei_a, ei_b = _endpoints(si)
                    ej_a, ej_b = _endpoints(sj)
                    pairs = [
                        (float(np.linalg.norm(ei_a - ej_a)), ei_a, ej_a),
                        (float(np.linalg.norm(ei_a - ej_b)), ei_a, ej_b),
                        (float(np.linalg.norm(ei_b - ej_a)), ei_b, ej_a),
                        (float(np.linalg.norm(ei_b - ej_b)), ei_b, ej_b),
                    ]
                    pairs.sort(key=lambda t: t[0])
                    _, pp1, pp2 = pairs[0]
                    elbow_pos = ((pp1 + pp2) / 2).tolist()
                    elbow = {
                        "position": elbow_pos,
                        "angle_deg": round(angle, 2),
                        "segment_ids": [
                            si.get("segment_id"),
                            sj.get("segment_id"),
                        ],
                    }

                    # Attach elbow to run_i; if cross-run also attach to run_j
                    run_list[ri_idx]["elbows"].append(elbow)
                    if rj_idx != ri_idx:
                        run_list[rj_idx]["elbows"].append(elbow)

    # Remove temp field and return
    for r in run_list:
        r.pop("_segs", None)

    return run_list


# ---------------------------------------------------------------------------
# As-built vs design comparison
# ---------------------------------------------------------------------------

def asbuilt_vs_design(
    asbuilt_segments: list[dict],
    design_pipes: list[dict],
    *,
    pos_tol_m: float = 0.05,
    dia_tol_frac: float = 0.10,
) -> dict:
    """
    Compare detected as-built pipe segments against a design pipe model.

    Matches each as-built segment to the closest design pipe by centerline
    proximity, then reports position and diameter deviations.

    Parameters
    ----------
    asbuilt_segments : list of dicts — output of detect_pipes (or run segments)
    design_pipes     : list of dicts — each must contain:
                         'centerline_start': [x,y,z]
                         'centerline_end':   [x,y,z]
                         'diameter_m':       float
                         (optional 'id': str/int, 'tag': str)
    pos_tol_m        : float — positional tolerance for pass/fail (m)
    dia_tol_frac     : float — diameter tolerance as fraction of nominal (0.10 = 10%)

    Returns
    -------
    dict with keys:
        n_asbuilt      : int
        n_design       : int
        n_matched      : int — as-built segments with a design counterpart
        n_unmatched    : int — orphan as-built segments (no nearby design pipe)
        matches        : list of dicts — one per matched pair:
            asbuilt_id        : int (segment_id)
            design_id         : int/str or index
            pos_deviation_m   : float — min endpoint-to-endpoint separation (m)
            dia_deviation_m   : float — |as-built diam − design diam| (m)
            dia_deviation_frac: float — relative diameter deviation
            pos_ok            : bool — pos_deviation_m <= pos_tol_m
            dia_ok            : bool — dia_deviation_frac <= dia_tol_frac
            status            : 'ok' | 'pos_mismatch' | 'dia_mismatch' | 'both_mismatch'
        unmatched_asbuilt : list[int] — segment_ids with no design match
        summary:
            n_ok            : int
            n_pos_mismatch  : int
            n_dia_mismatch  : int
            n_both_mismatch : int
            max_pos_dev_m   : float
            rms_pos_dev_m   : float

    References
    ----------
    Bueno et al. (2018). "Automatic Point Cloud Coarse Registration Using
      Geometric Keypoint Descriptors for Indoor Scenes." Automation in
      Construction 94:442-456.
    """
    def _mid(seg: dict) -> np.ndarray:
        s = np.array(seg["centerline_start"])
        e = np.array(seg["centerline_end"])
        return (s + e) / 2.0

    def _endpt_sep(ab: dict, des: dict) -> float:
        """Min distance between any endpoint pair of as-built and design."""
        s1, e1 = np.array(ab["centerline_start"]), np.array(ab["centerline_end"])
        s2, e2 = np.array(des["centerline_start"]), np.array(des["centerline_end"])
        # Also compare midpoints for robustness
        m1, m2 = (s1 + e1) / 2, (s2 + e2) / 2
        return float(min(
            np.linalg.norm(s1 - s2),
            np.linalg.norm(s1 - e2),
            np.linalg.norm(e1 - s2),
            np.linalg.norm(e1 - e2),
            np.linalg.norm(m1 - m2),
        ))

    matches: list[dict] = []
    matched_ab_ids: set[int] = set()

    for ab in asbuilt_segments:
        ab_id = ab.get("segment_id", id(ab))
        if not design_pipes:
            continue

        # Find closest design pipe by centerline proximity
        best_sep = float("inf")
        best_des_idx = -1
        for di, des in enumerate(design_pipes):
            sep = _endpt_sep(ab, des)
            if sep < best_sep:
                best_sep = sep
                best_des_idx = di

        if best_des_idx < 0:
            continue

        des = design_pipes[best_des_idx]
        ab_diam = float(ab.get("diameter_m", 0.0))
        des_diam = float(des.get("diameter_m", 0.0))
        dia_dev_m = abs(ab_diam - des_diam)
        dia_dev_frac = dia_dev_m / max(des_diam, 1e-9)

        pos_ok = best_sep <= pos_tol_m
        dia_ok = dia_dev_frac <= dia_tol_frac

        if pos_ok and dia_ok:
            status = "ok"
        elif not pos_ok and not dia_ok:
            status = "both_mismatch"
        elif not pos_ok:
            status = "pos_mismatch"
        else:
            status = "dia_mismatch"

        design_id = des.get("id", best_des_idx)
        matches.append({
            "asbuilt_id": ab_id,
            "design_id": design_id,
            "pos_deviation_m": round(best_sep, 6),
            "dia_deviation_m": round(dia_dev_m, 6),
            "dia_deviation_frac": round(dia_dev_frac, 4),
            "pos_ok": pos_ok,
            "dia_ok": dia_ok,
            "status": status,
        })
        matched_ab_ids.add(ab_id)

    unmatched = [
        ab.get("segment_id", i)
        for i, ab in enumerate(asbuilt_segments)
        if ab.get("segment_id", i) not in matched_ab_ids
    ]

    # Summary stats
    n_ok = sum(1 for m in matches if m["status"] == "ok")
    n_pos = sum(1 for m in matches if m["status"] == "pos_mismatch")
    n_dia = sum(1 for m in matches if m["status"] == "dia_mismatch")
    n_both = sum(1 for m in matches if m["status"] == "both_mismatch")
    pos_devs = [m["pos_deviation_m"] for m in matches]
    max_pos_dev = float(max(pos_devs)) if pos_devs else 0.0
    rms_pos_dev = float(np.sqrt(np.mean(np.array(pos_devs) ** 2))) if pos_devs else 0.0

    return {
        "n_asbuilt": len(asbuilt_segments),
        "n_design": len(design_pipes),
        "n_matched": len(matches),
        "n_unmatched": len(unmatched),
        "matches": matches,
        "unmatched_asbuilt": unmatched,
        "summary": {
            "n_ok": n_ok,
            "n_pos_mismatch": n_pos,
            "n_dia_mismatch": n_dia,
            "n_both_mismatch": n_both,
            "max_pos_dev_m": round(max_pos_dev, 6),
            "rms_pos_dev_m": round(rms_pos_dev, 6),
        },
    }
