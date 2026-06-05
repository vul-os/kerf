"""
VTK / VTU export + ParaView-style post-processing filters for Kerf CFD.

This module provides:

  1. VTK export
     * Legacy ASCII `.vtk` (VTK DataFile v4.0, DATASET UNSTRUCTURED_GRID)
     * XML ASCII `.vtu` (VTK Unstructured Grid, VTK 0.1)
     Both carry point/cell data arrays: velocity (3-component), pressure,
     temperature, k, epsilon, omega, and arbitrary named scalar/vector
     arrays passed by the caller.

  2. ParaView-style server-side post-processing filters
     * slice       — extract field values on an arbitrary cut plane (ax+by+cz=d)
     * contour     — iso-surface approximated by finding cells straddling a level
     * streamline  — RK4 integration through a velocity field from seed points
     * integral    — surface/volume integrals (flow rate, force, average, min/max)
     * probe       — interpolate field at arbitrary points (nearest-cell)
     * derived     — derived quantities: vorticity, Q-criterion, gradient,
                     pressure coefficient Cp, wall shear stress estimate

  All operations are pure NumPy — no VTK Python library required.

References
----------
Schroeder W., Martin K., Lorensen B. (2006) "The Visualization Toolkit" 4th ed.
  (VTK file format spec — legacy §A.1, XML §A.2)
Hunt J.C.R., Wray A.A., Moin P. (1988) "Eddies, Streams, and Convergence Zones"
  CTR-S88 (Q-criterion)
Haimes R. (1999) "Using residence time for the extraction of recirculation
  regions" AIAA-99-3288 (streamline integration)
White F.M. (2011) "Fluid Mechanics" 7th ed. §6 (pressure coefficient)
"""

from __future__ import annotations

import base64
import math
import struct
from io import StringIO
from typing import Any

import numpy as np

# ---------------------------------------------------------------------------
# Data container
# ---------------------------------------------------------------------------

class CFDMesh:
    """
    Lightweight CFD mesh + field container.

    Parameters
    ----------
    points : (N_pts, 3) float array
        Node coordinates.
    cells : list[list[int]]
        Cell connectivity.  Each entry is a list of node indices.
        Supported: tet (4), hex (8), wedge (6), pyramid (5), triangle (3),
        quad (4 - distinguishable from tet only by context/`cell_types`).
    cell_types : list[int] | None
        VTK cell type codes per cell.  If None, inferred from connectivity
        length: 4→VTK_TETRA(10), 8→VTK_HEXAHEDRON(12), 6→VTK_WEDGE(13),
        5→VTK_PYRAMID(14), 3→VTK_TRIANGLE(5), else→VTK_POLYGON(7).
    point_data : dict[str, array-like]
        Point-centred field arrays.  Scalars → shape (N_pts,);
        vectors → shape (N_pts, 3).
    cell_data : dict[str, array-like]
        Cell-centred field arrays.  Same shape convention.
    """

    _VTK_TYPE_BY_NPTS = {4: 10, 8: 12, 6: 13, 5: 14, 3: 5}

    def __init__(
        self,
        points: np.ndarray,
        cells: list[list[int]],
        *,
        cell_types: list[int] | None = None,
        point_data: dict[str, Any] | None = None,
        cell_data: dict[str, Any] | None = None,
    ):
        self.points = np.asarray(points, dtype=np.float64)
        if self.points.ndim == 1:
            self.points = self.points.reshape(-1, 3)
        if self.points.shape[1] == 2:
            # pad 2-D with z=0
            self.points = np.column_stack(
                [self.points, np.zeros(len(self.points))]
            )
        self.cells = [list(c) for c in cells]
        if cell_types is None:
            self.cell_types = [
                self._VTK_TYPE_BY_NPTS.get(len(c), 7) for c in self.cells
            ]
        else:
            self.cell_types = list(cell_types)
        self.point_data: dict[str, np.ndarray] = {}
        self.cell_data: dict[str, np.ndarray] = {}
        for k, v in (point_data or {}).items():
            self.point_data[k] = np.asarray(v, dtype=np.float64)
        for k, v in (cell_data or {}).items():
            self.cell_data[k] = np.asarray(v, dtype=np.float64)

    @property
    def n_points(self) -> int:
        return len(self.points)

    @property
    def n_cells(self) -> int:
        return len(self.cells)

    def cell_centers(self) -> np.ndarray:
        """Compute cell-centre coordinates (centroid of node set)."""
        centres = np.zeros((self.n_cells, 3))
        for i, c in enumerate(self.cells):
            centres[i] = self.points[c].mean(axis=0)
        return centres


# ---------------------------------------------------------------------------
# Helper: point/cell data array blocks
# ---------------------------------------------------------------------------

def _vtk_array_name_sanitize(name: str) -> str:
    return name.replace(" ", "_").replace("/", "_")


def _is_vector_array(arr: np.ndarray) -> bool:
    return arr.ndim == 2 and arr.shape[1] == 3


def _ensure_3comp(arr: np.ndarray, n: int) -> np.ndarray:
    """Ensure arr is (n, 3) for writing as VTK VECTORS."""
    arr = np.asarray(arr, dtype=np.float64)
    if arr.ndim == 1 and len(arr) == n:
        # Scalar masquerading as vector — stack zeros
        return np.column_stack([arr, np.zeros(n), np.zeros(n)])
    if arr.ndim == 2 and arr.shape == (n, 3):
        return arr
    raise ValueError(f"Cannot write array shape {arr.shape} as 3-component vector for {n} elements")


# ---------------------------------------------------------------------------
# Legacy VTK export
# ---------------------------------------------------------------------------

def write_legacy_vtk(mesh: CFDMesh, path: str | None = None) -> str:
    """
    Write CFD mesh + fields to VTK DataFile Version 4.0 (legacy ASCII).

    Parameters
    ----------
    mesh : CFDMesh
    path : str | None
        If given, write to file and return path.  Otherwise return the
        VTK text as a string.

    Returns
    -------
    str
        The VTK file text (also written to *path* if given).

    References
    ----------
    VTK file formats: Schroeder (2006) Appendix B, §B.1 legacy ASCII.
    """
    buf = StringIO()
    npts = mesh.n_points
    ncells = mesh.n_cells

    # Header
    buf.write("# vtk DataFile Version 4.0\n")
    buf.write("Kerf CFD export\n")
    buf.write("ASCII\n")
    buf.write("DATASET UNSTRUCTURED_GRID\n")

    # Points
    buf.write(f"\nPOINTS {npts} double\n")
    for i in range(npts):
        x, y, z = mesh.points[i]
        buf.write(f"{x:.10g} {y:.10g} {z:.10g}\n")

    # Cells: first write the connectivity list
    # VTK legacy: CELLS n_cells total_int_count
    # Each row: npts v0 v1 ... vn-1
    total = sum(1 + len(c) for c in mesh.cells)
    buf.write(f"\nCELLS {ncells} {total}\n")
    for c in mesh.cells:
        buf.write(f"{len(c)} " + " ".join(str(v) for v in c) + "\n")

    # Cell types
    buf.write(f"\nCELL_TYPES {ncells}\n")
    for ct in mesh.cell_types:
        buf.write(f"{ct}\n")

    # Point data
    if mesh.point_data:
        buf.write(f"\nPOINT_DATA {npts}\n")
        for name, arr in mesh.point_data.items():
            arr = np.asarray(arr, dtype=np.float64)
            sname = _vtk_array_name_sanitize(name)
            if _is_vector_array(arr) and len(arr) == npts:
                buf.write(f"VECTORS {sname} double\n")
                for row in arr:
                    buf.write(f"{row[0]:.10g} {row[1]:.10g} {row[2]:.10g}\n")
            else:
                a = arr.ravel()
                if len(a) != npts:
                    continue
                buf.write(f"SCALARS {sname} double 1\n")
                buf.write("LOOKUP_TABLE default\n")
                for v in a:
                    buf.write(f"{v:.10g}\n")

    # Cell data
    if mesh.cell_data:
        buf.write(f"\nCELL_DATA {ncells}\n")
        for name, arr in mesh.cell_data.items():
            arr = np.asarray(arr, dtype=np.float64)
            sname = _vtk_array_name_sanitize(name)
            if _is_vector_array(arr) and len(arr) == ncells:
                buf.write(f"VECTORS {sname} double\n")
                for row in arr:
                    buf.write(f"{row[0]:.10g} {row[1]:.10g} {row[2]:.10g}\n")
            else:
                a = arr.ravel()
                if len(a) != ncells:
                    continue
                buf.write(f"SCALARS {sname} double 1\n")
                buf.write("LOOKUP_TABLE default\n")
                for v in a:
                    buf.write(f"{v:.10g}\n")

    text = buf.getvalue()
    if path is not None:
        with open(path, "w") as f:
            f.write(text)
    return text


# ---------------------------------------------------------------------------
# XML VTU export (ASCII + base64 binary inline)
# ---------------------------------------------------------------------------

def _vtu_data_array_ascii(name: str, arr: np.ndarray, n_components: int) -> str:
    """Render a VTK DataArray element in ASCII format."""
    flat = arr.ravel(order="C")
    vals = " ".join(f"{v:.10g}" for v in flat)
    return (
        f'      <DataArray type="Float64" Name="{name}" '
        f'NumberOfComponents="{n_components}" format="ascii">\n'
        f"        {vals}\n"
        f"      </DataArray>\n"
    )


def _vtu_data_array_b64(name: str, arr: np.ndarray, n_components: int) -> str:
    """
    Render a VTK DataArray element with base64-encoded binary (little-endian float64).
    VTK appended-base64 convention: 4-byte UInt32 header (byte count) then data.
    """
    data_bytes = arr.astype("<f8").tobytes()
    header = struct.pack("<I", len(data_bytes))
    encoded = base64.b64encode(header + data_bytes).decode("ascii")
    return (
        f'      <DataArray type="Float64" Name="{name}" '
        f'NumberOfComponents="{n_components}" format="binary" encoding="base64">\n'
        f"        {encoded}\n"
        f"      </DataArray>\n"
    )


def write_vtu(
    mesh: CFDMesh,
    path: str | None = None,
    *,
    binary: bool = True,
) -> str:
    """
    Write CFD mesh + fields to VTK XML Unstructured Grid (.vtu).

    Parameters
    ----------
    mesh : CFDMesh
    path : str | None
    binary : bool
        True → base64-encoded binary DataArrays (compact, ParaView default).
        False → ASCII DataArrays (human-readable, larger).

    Returns
    -------
    str
        The VTU XML text.

    References
    ----------
    VTK XML file format: Schroeder (2006) Appendix B, §B.2.
    VTK connectivity offset encoding: VTK documentation §3.2.
    """
    npts = mesh.n_points
    ncells = mesh.n_cells
    _da = _vtu_data_array_b64 if binary else _vtu_data_array_ascii

    buf = StringIO()
    buf.write('<?xml version="1.0"?>\n')
    buf.write('<VTKFile type="UnstructuredGrid" version="0.1" byte_order="LittleEndian">\n')
    buf.write('  <UnstructuredGrid>\n')
    buf.write(f'    <Piece NumberOfPoints="{npts}" NumberOfCells="{ncells}">\n')

    # ── Points ────────────────────────────────────────────────────────────
    buf.write('      <Points>\n')
    pts_flat = mesh.points.ravel(order="C")
    buf.write(_da("Points", pts_flat, 3))
    buf.write('      </Points>\n')

    # ── Cells ─────────────────────────────────────────────────────────────
    # connectivity: flat list of node indices
    conn = np.array(
        [v for c in mesh.cells for v in c], dtype=np.int64
    )
    # offsets: cumulative sum of nodes per cell
    offsets = np.cumsum([len(c) for c in mesh.cells], dtype=np.int64)
    types_arr = np.array(mesh.cell_types, dtype=np.uint8)

    buf.write('      <Cells>\n')
    buf.write(_vtu_int_array(conn, "connectivity", binary))
    buf.write(_vtu_int_array(offsets, "offsets", binary))
    buf.write(_vtu_uint8_array(types_arr, "types", binary))
    buf.write('      </Cells>\n')

    # ── PointData ─────────────────────────────────────────────────────────
    if mesh.point_data:
        # Determine default scalar / vector for ParaView
        scalars_attr = ""
        vectors_attr = ""
        for name, arr in mesh.point_data.items():
            arr2 = np.asarray(arr)
            if _is_vector_array(arr2) and not vectors_attr:
                vectors_attr = f' Vectors="{_vtk_array_name_sanitize(name)}"'
            elif not _is_vector_array(arr2) and not scalars_attr:
                scalars_attr = f' Scalars="{_vtk_array_name_sanitize(name)}"'

        buf.write(f'      <PointData{scalars_attr}{vectors_attr}>\n')
        for name, arr in mesh.point_data.items():
            arr = np.asarray(arr, dtype=np.float64)
            sname = _vtk_array_name_sanitize(name)
            if _is_vector_array(arr) and len(arr) == npts:
                buf.write(_da(sname, arr, 3))
            else:
                a = arr.ravel()
                if len(a) == npts:
                    buf.write(_da(sname, a, 1))
        buf.write('      </PointData>\n')

    # ── CellData ──────────────────────────────────────────────────────────
    if mesh.cell_data:
        scalars_attr = ""
        vectors_attr = ""
        for name, arr in mesh.cell_data.items():
            arr2 = np.asarray(arr)
            if _is_vector_array(arr2) and not vectors_attr:
                vectors_attr = f' Vectors="{_vtk_array_name_sanitize(name)}"'
            elif not _is_vector_array(arr2) and not scalars_attr:
                scalars_attr = f' Scalars="{_vtk_array_name_sanitize(name)}"'

        buf.write(f'      <CellData{scalars_attr}{vectors_attr}>\n')
        for name, arr in mesh.cell_data.items():
            arr = np.asarray(arr, dtype=np.float64)
            sname = _vtk_array_name_sanitize(name)
            if _is_vector_array(arr) and len(arr) == ncells:
                buf.write(_da(sname, arr, 3))
            else:
                a = arr.ravel()
                if len(a) == ncells:
                    buf.write(_da(sname, a, 1))
        buf.write('      </CellData>\n')

    buf.write('    </Piece>\n')
    buf.write('  </UnstructuredGrid>\n')
    buf.write('</VTKFile>\n')

    text = buf.getvalue()
    if path is not None:
        with open(path, "w") as f:
            f.write(text)
    return text


def _vtu_int_array(arr: np.ndarray, name: str, binary: bool) -> str:
    if binary:
        data_bytes = arr.astype("<i8").tobytes()
        header = struct.pack("<I", len(data_bytes))
        encoded = base64.b64encode(header + data_bytes).decode("ascii")
        return (
            f'        <DataArray type="Int64" Name="{name}" '
            f'format="binary" encoding="base64">\n'
            f"          {encoded}\n"
            f"        </DataArray>\n"
        )
    vals = " ".join(str(v) for v in arr)
    return (
        f'        <DataArray type="Int64" Name="{name}" format="ascii">\n'
        f"          {vals}\n"
        f"        </DataArray>\n"
    )


def _vtu_uint8_array(arr: np.ndarray, name: str, binary: bool) -> str:
    if binary:
        data_bytes = arr.astype(np.uint8).tobytes()
        header = struct.pack("<I", len(data_bytes))
        encoded = base64.b64encode(header + data_bytes).decode("ascii")
        return (
            f'        <DataArray type="UInt8" Name="{name}" '
            f'format="binary" encoding="base64">\n'
            f"          {encoded}\n"
            f"        </DataArray>\n"
        )
    vals = " ".join(str(v) for v in arr)
    return (
        f'        <DataArray type="UInt8" Name="{name}" format="ascii">\n'
        f"          {vals}\n"
        f"        </DataArray>\n"
    )


# ---------------------------------------------------------------------------
# VTK / VTU round-trip parser (for tests)
# ---------------------------------------------------------------------------

def read_legacy_vtk(path: str) -> CFDMesh:
    """
    Parse a legacy ASCII VTK file written by :func:`write_legacy_vtk`.

    Returns a :class:`CFDMesh` with point_data and cell_data populated.
    Only supports UNSTRUCTURED_GRID with SCALARS / VECTORS data arrays.
    """
    with open(path) as f:
        lines = [l.rstrip("\n") for l in f.readlines()]

    it = iter(lines)

    def nextl():
        return next(it).strip()

    # Skip header lines
    title = nextl()  # # vtk DataFile ...
    desc = nextl()   # description
    fmt = nextl()    # ASCII
    dataset = nextl()  # DATASET UNSTRUCTURED_GRID

    if "UNSTRUCTURED_GRID" not in dataset:
        raise ValueError(f"Only UNSTRUCTURED_GRID supported, got: {dataset!r}")

    points = []
    cells = []
    cell_types = []
    point_data: dict[str, np.ndarray] = {}
    cell_data: dict[str, np.ndarray] = {}
    current_section: str | None = None
    npts = 0
    ncells = 0

    for line in it:
        line = line.strip()
        if not line:
            continue
        upper = line.upper()

        if upper.startswith("POINTS"):
            parts = line.split()
            npts = int(parts[1])
            for _ in range(npts):
                row = next(it).split()
                points.append([float(row[0]), float(row[1]), float(row[2])])
            continue

        if upper.startswith("CELLS"):
            parts = line.split()
            ncells = int(parts[1])
            for _ in range(ncells):
                row = list(map(int, next(it).split()))
                n = row[0]
                cells.append(row[1: 1 + n])
            continue

        if upper.startswith("CELL_TYPES"):
            for _ in range(ncells):
                cell_types.append(int(next(it).strip()))
            continue

        if upper.startswith("POINT_DATA"):
            current_section = "point"
            continue

        if upper.startswith("CELL_DATA"):
            current_section = "cell"
            continue

        if upper.startswith("SCALARS"):
            parts = line.split()
            arr_name = parts[1]
            _ncomp = int(parts[3]) if len(parts) > 3 else 1
            next(it)  # LOOKUP_TABLE default
            n = npts if current_section == "point" else ncells
            vals = []
            while len(vals) < n:
                vals.append(float(next(it).strip()))
            arr = np.array(vals)
            if current_section == "point":
                point_data[arr_name] = arr
            else:
                cell_data[arr_name] = arr
            continue

        if upper.startswith("VECTORS"):
            parts = line.split()
            arr_name = parts[1]
            n = npts if current_section == "point" else ncells
            vecs = []
            while len(vecs) < n:
                row = next(it).split()
                vecs.append([float(row[0]), float(row[1]), float(row[2])])
            arr = np.array(vecs)
            if current_section == "point":
                point_data[arr_name] = arr
            else:
                cell_data[arr_name] = arr
            continue

    return CFDMesh(
        np.array(points),
        cells,
        cell_types=cell_types or None,
        point_data=point_data,
        cell_data=cell_data,
    )


# ---------------------------------------------------------------------------
# Post-processing filters
# ---------------------------------------------------------------------------

class PostProcessor:
    """
    Server-side ParaView-style post-processing filters.

    All methods take a :class:`CFDMesh` (or equivalent) and return a dict
    with computed results.  Pure NumPy — no VTK Python library required.
    """

    # ── 1. Slice / cut plane ──────────────────────────────────────────────

    @staticmethod
    def slice_plane(
        mesh: CFDMesh,
        normal: tuple[float, float, float],
        origin: tuple[float, float, float],
        *,
        field: str = "U",
        tolerance: float | None = None,
    ) -> dict:
        """
        Extract field values for cells whose centres lie near a cut plane.

        The plane is defined by:   n · (x - o) = 0
        A cell is selected if:   |n · (centre - o)| <= tol

        tol defaults to 1.5× the mean cell-centre spacing.

        Parameters
        ----------
        mesh    : CFDMesh
        normal  : (nx, ny, nz) — plane normal (need not be unit).
        origin  : (ox, oy, oz) — point on the plane.
        field   : field name to extract (default 'U').
        tolerance : half-width of slice band (metres).

        Returns
        -------
        dict with keys:
          plane_normal, plane_origin, n_cells_on_plane,
          cell_indices, cell_centers, field_values, field_stats
        """
        n = np.asarray(normal, dtype=float)
        nn = n / (np.linalg.norm(n) + 1e-300)
        o = np.asarray(origin, dtype=float)

        centres = mesh.cell_centers()
        signed_dist = (centres - o) @ nn  # shape (ncells,)

        if tolerance is None:
            # Heuristic: 1.5× median absolute inter-cell spacing
            if len(centres) > 1:
                diffs = np.diff(centres, axis=0)
                spacing = np.median(np.linalg.norm(diffs, axis=1))
                tolerance = 1.5 * max(spacing, 1e-10)
            else:
                tolerance = 1.0

        mask = np.abs(signed_dist) <= tolerance
        idx = np.where(mask)[0]

        # Extract field
        arr = _get_field(mesh, field)
        if arr is None:
            field_values = None
            stats = {}
        else:
            field_values = arr[idx] if len(idx) > 0 else np.array([])
            stats = _compute_stats(field_values)

        return {
            "plane_normal": list(nn),
            "plane_origin": list(o),
            "tolerance_m": float(tolerance),
            "n_cells_on_plane": int(len(idx)),
            "cell_indices": idx.tolist(),
            "cell_centers": centres[idx].tolist() if len(idx) > 0 else [],
            "field": field,
            "field_values": _serialize_arr(field_values),
            "field_stats": stats,
        }

    # ── 2. Contour / iso-surface ──────────────────────────────────────────

    @staticmethod
    def contour(
        mesh: CFDMesh,
        field: str,
        iso_value: float,
    ) -> dict:
        """
        Extract cells that straddle a scalar iso-surface (contour).

        A cell is marked if the scalar field spans the iso_value:
            min(cell_node_values) <= iso_value <= max(cell_node_values)

        For cell-centred data, uses the cell value directly; cells within
        10% of max-range of the iso_value are returned.

        Returns
        -------
        dict with: iso_value, n_cells, cell_indices, cell_centers, field_values
        """
        arr = _get_field(mesh, field)
        if arr is None:
            return {"error": f"field '{field}' not found", "code": "NOT_FOUND"}

        # Reduce vector to magnitude
        if arr.ndim == 2:
            arr = np.linalg.norm(arr, axis=1)

        centres = mesh.cell_centers()

        # Check if we have point data — do nodal min/max per cell
        pt_arr = mesh.point_data.get(field)
        if pt_arr is not None:
            if pt_arr.ndim == 2:
                pt_arr = np.linalg.norm(pt_arr, axis=1)
            # Per cell: min and max of node values
            cell_mask = np.zeros(mesh.n_cells, dtype=bool)
            for i, c in enumerate(mesh.cells):
                node_vals = pt_arr[c]
                cell_mask[i] = (node_vals.min() <= iso_value <= node_vals.max())
        else:
            # Cell-centred: use adaptive band.
            # Only applicable when iso_value is within the field range.
            # Band = 15% of the total range, centred on iso_value.
            range_val = arr.max() - arr.min()
            if range_val < 1e-15:
                cell_mask = np.ones(mesh.n_cells, dtype=bool)
            elif iso_value < arr.min() or iso_value > arr.max():
                # iso_value outside range: no cells qualify
                cell_mask = np.zeros(mesh.n_cells, dtype=bool)
            else:
                band = max(0.15 * range_val, 1e-12)
                abs_diff = np.abs(arr - iso_value)
                cell_mask = abs_diff <= band

        idx = np.where(cell_mask)[0]
        field_values = arr[idx] if len(idx) > 0 else np.array([])

        return {
            "iso_value": float(iso_value),
            "field": field,
            "n_cells": int(len(idx)),
            "cell_indices": idx.tolist(),
            "cell_centers": centres[idx].tolist() if len(idx) > 0 else [],
            "field_values": field_values.tolist(),
            "field_stats": _compute_stats(field_values),
        }

    # ── 3. Streamline integration ─────────────────────────────────────────

    @staticmethod
    def streamline(
        mesh: CFDMesh,
        seed_points: list[list[float]],
        *,
        velocity_field: str = "U",
        max_steps: int = 500,
        step_size: float | None = None,
        direction: str = "forward",
    ) -> dict:
        """
        Integrate streamlines via RK4 through a velocity field.

        Uses nearest-cell velocity interpolation (first-order, sufficient
        for structured/regular meshes; higher-order needs a FEM basis).

        Parameters
        ----------
        seed_points : list of [x, y, z] start positions.
        velocity_field : name of the 3-component vector field (default 'U').
        max_steps : maximum integration steps per seed.
        step_size : integration step length [m].  Defaults to 0.1× mean
                    cell spacing.
        direction : 'forward' | 'backward' | 'both'.

        Returns
        -------
        dict with list of streamline paths, each being a list of [x,y,z].

        References
        ----------
        Runge-Kutta 4th order: Press et al. (2007) §17.1.
        Nearest-cell interpolation: Haimes (1999).
        """
        U = _get_field(mesh, velocity_field)
        if U is None or U.ndim != 2 or U.shape[1] != 3:
            return {"error": f"velocity field '{velocity_field}' not found or not 3-D",
                    "code": "NOT_FOUND"}

        centres = mesh.cell_centers()

        # Default step size: 10% of mean cell spacing
        if step_size is None:
            if len(centres) > 1:
                diffs = np.diff(centres, axis=0)
                mean_spacing = np.mean(np.linalg.norm(diffs, axis=1))
                step_size = 0.1 * max(mean_spacing, 1e-10)
            else:
                step_size = 0.01

        def velocity_at(pos: np.ndarray) -> np.ndarray:
            """Nearest-cell velocity interpolation."""
            dists = np.linalg.norm(centres - pos, axis=1)
            ci = int(np.argmin(dists))
            return U[ci].copy()

        def rk4_step(pos: np.ndarray, ds: float) -> np.ndarray:
            k1 = velocity_at(pos)
            mag1 = np.linalg.norm(k1)
            if mag1 < 1e-15:
                return pos
            k1n = k1 / mag1
            k2 = velocity_at(pos + 0.5 * ds * k1n)
            mag2 = np.linalg.norm(k2)
            k2n = k2 / (mag2 if mag2 > 1e-15 else 1.0)
            k3 = velocity_at(pos + 0.5 * ds * k2n)
            mag3 = np.linalg.norm(k3)
            k3n = k3 / (mag3 if mag3 > 1e-15 else 1.0)
            k4 = velocity_at(pos + ds * k3n)
            mag4 = np.linalg.norm(k4)
            k4n = k4 / (mag4 if mag4 > 1e-15 else 1.0)
            direction_vec = (k1n + 2 * k2n + 2 * k3n + k4n) / 6.0
            norm = np.linalg.norm(direction_vec)
            if norm < 1e-15:
                return pos
            return pos + ds * direction_vec / norm

        # Bounding box for termination check
        bbox_min = mesh.points.min(axis=0) - step_size
        bbox_max = mesh.points.max(axis=0) + step_size

        def integrate(start: np.ndarray, forward: bool) -> list[list[float]]:
            path = [start.tolist()]
            pos = start.copy()
            ds = step_size if forward else -step_size
            for _ in range(max_steps):
                new_pos = rk4_step(pos, ds)
                if np.any(new_pos < bbox_min) or np.any(new_pos > bbox_max):
                    break
                path.append(new_pos.tolist())
                if np.linalg.norm(new_pos - pos) < 1e-14 * step_size:
                    break
                pos = new_pos
            return path

        streamlines = []
        for seed in seed_points:
            pt = np.zeros(3)
            pt[:len(seed)] = seed
            if direction in ("forward", "both"):
                fwd = integrate(pt.copy(), forward=True)
            else:
                fwd = None
            if direction in ("backward", "both"):
                bwd = integrate(pt.copy(), forward=False)
            else:
                bwd = None

            if direction == "forward":
                path = fwd
            elif direction == "backward":
                path = bwd
            else:
                path = list(reversed(bwd[1:])) + fwd if (fwd and bwd) else (fwd or bwd or [pt.tolist()])

            streamlines.append({
                "seed": pt.tolist(),
                "n_points": len(path),
                "path": path,
            })

        return {
            "n_streamlines": len(streamlines),
            "max_steps": max_steps,
            "step_size_m": float(step_size),
            "direction": direction,
            "streamlines": streamlines,
        }

    # ── 4. Integral — flow rate / force / average ─────────────────────────

    @staticmethod
    def integral(
        mesh: CFDMesh,
        field: str,
        *,
        operation: str = "volume_average",
        cell_volumes: np.ndarray | None = None,
    ) -> dict:
        """
        Compute surface/volume integrals over the mesh.

        Operations
        ----------
        volume_average  : ∫f dV / V   (cell-volume weighted mean)
        volume_integral : ∫f dV
        min             : minimum value
        max             : maximum value
        mean            : arithmetic mean (no volume weighting)
        rms             : root-mean-square

        Cell volumes are estimated as the mean cell spacing³ if not
        provided.  Pass `cell_volumes` (array, shape (ncells,)) for
        accurate results.

        Returns
        -------
        dict with operation, result, n_cells, field, [units note]
        """
        arr = _get_field(mesh, field)
        if arr is None:
            return {"error": f"field '{field}' not found", "code": "NOT_FOUND"}

        # Reduce vector to magnitude for integral
        is_vec = arr.ndim == 2
        if is_vec:
            arr_mag = np.linalg.norm(arr, axis=1)
        else:
            arr_mag = arr.ravel()

        ncells = mesh.n_cells

        if cell_volumes is None:
            # Estimate cell volumes from mesh bounding box and cell count
            bbox = mesh.points.max(axis=0) - mesh.points.min(axis=0)
            total_vol_est = float(np.prod(np.where(bbox > 1e-15, bbox, 1.0)))
            vol_per_cell = total_vol_est / max(ncells, 1)
            cell_volumes = np.full(ncells, vol_per_cell)
        else:
            cell_volumes = np.asarray(cell_volumes, dtype=float)

        total_vol = float(cell_volumes.sum())

        if operation == "volume_average":
            result = float(np.dot(arr_mag, cell_volumes) / max(total_vol, 1e-300))
        elif operation == "volume_integral":
            result = float(np.dot(arr_mag, cell_volumes))
        elif operation == "min":
            result = float(arr_mag.min())
        elif operation == "max":
            result = float(arr_mag.max())
        elif operation == "mean":
            result = float(arr_mag.mean())
        elif operation == "rms":
            result = float(np.sqrt(np.mean(arr_mag ** 2)))
        else:
            return {"error": f"unknown operation '{operation}'", "code": "BAD_ARGS"}

        return {
            "operation": operation,
            "field": field,
            "is_vector_magnitude": is_vec,
            "result": result,
            "n_cells": ncells,
            "total_volume_m3": total_vol,
            "note": "Cell volumes estimated from bounding box if not provided.",
        }

    # ── 5. Probe at points ────────────────────────────────────────────────

    @staticmethod
    def probe(
        mesh: CFDMesh,
        probe_points: list[list[float]],
        fields: list[str] | None = None,
    ) -> dict:
        """
        Interpolate field values at arbitrary points (nearest-cell).

        Parameters
        ----------
        probe_points : list of [x,y,z] positions.
        fields : list of field names to sample.  None → all available fields.

        Returns
        -------
        dict with per-probe entries: {x, y, z, nearest_cell_idx, distance_m,
                                      <field>: value_or_list, ...}
        """
        centres = mesh.cell_centers()

        if fields is None:
            fields = list(mesh.point_data.keys()) + list(mesh.cell_data.keys())
            # deduplicate preserving order
            seen: set = set()
            uniq = []
            for f in fields:
                if f not in seen:
                    uniq.append(f)
                    seen.add(f)
            fields = uniq

        results = []
        for pt in probe_points:
            pos = np.zeros(3)
            pos[:len(pt)] = pt
            dists = np.linalg.norm(centres - pos, axis=1)
            ci = int(np.argmin(dists))
            entry: dict = {
                "x": float(pos[0]),
                "y": float(pos[1]),
                "z": float(pos[2]),
                "nearest_cell_idx": ci,
                "distance_m": float(dists[ci]),
            }
            for f in fields:
                arr = _get_field(mesh, f)
                if arr is None:
                    continue
                v = arr[ci]
                if isinstance(v, np.ndarray):
                    entry[f] = v.tolist()
                    entry[f"{f}_mag"] = float(np.linalg.norm(v))
                else:
                    entry[f] = float(v)
            results.append(entry)

        return {
            "n_probes": len(results),
            "fields": fields,
            "probes": results,
        }

    # ── 6. Derived fields ─────────────────────────────────────────────────

    @staticmethod
    def derived(
        mesh: CFDMesh,
        quantity: str,
        *,
        velocity_field: str = "U",
        pressure_field: str = "p",
        rho: float = 1.225,
        U_ref: float | None = None,
        p_ref: float | None = None,
        nu: float = 1.5e-5,
    ) -> dict:
        """
        Compute a derived field on the mesh cells.

        Quantities
        ----------
        vorticity     : ω = ∇ × U   (curl of velocity, finite-difference on
                         cell-centre cloud; returns (n_cells, 3) array)
        q_criterion   : Q = ½(||Ω||² - ||S||²) where Ω is the anti-symmetric
                         and S the symmetric part of ∇U.
                         Q > 0 identifies vortex-core regions.
                         Hunt et al. (1988) CTR-S88.
        gradient_p    : ∇p  (pressure gradient, cell-centred FD)
        pressure_coeff: Cp = (p - p_ref) / (0.5 ρ U_ref²)
                         Requires U_ref and p_ref.  Default p_ref = min(p).
        divergence    : ∇ · U  (velocity divergence; ≈0 for incompressible)
        strain_rate   : ||S|| = √(½(∂ui/∂xj + ∂uj/∂xi)²) scalar magnitude

        All gradient/curl operations use a first-order finite-difference
        approximation on the cell-centre cloud via numpy least-squares.

        Returns
        -------
        dict with: quantity, n_cells, values (list), stats
        """
        U_arr = _get_field(mesh, velocity_field)
        p_arr = _get_field(mesh, pressure_field)
        centres = mesh.cell_centers()

        if quantity == "pressure_coeff":
            if p_arr is None:
                return {"error": "pressure field not found", "code": "NOT_FOUND"}
            if U_ref is None or U_ref <= 0:
                return {"error": "U_ref required for pressure_coeff", "code": "BAD_ARGS"}
            p_ref_val = float(p_arr.min()) if p_ref is None else float(p_ref)
            dyn = 0.5 * rho * U_ref ** 2
            Cp = (p_arr.ravel() - p_ref_val) / dyn
            return {
                "quantity": "pressure_coeff",
                "n_cells": mesh.n_cells,
                "values": Cp.tolist(),
                "stats": _compute_stats(Cp),
                "p_ref": p_ref_val,
                "U_ref": U_ref,
                "rho": rho,
                "note": "Cp = (p - p_ref) / (0.5 rho U_ref^2). White (2011) §3.",
            }

        if quantity == "vorticity":
            if U_arr is None or U_arr.ndim != 2:
                return {"error": "velocity field U (3-D) required", "code": "NOT_FOUND"}
            vort = _curl_on_cloud(centres, U_arr)
            vort_mag = np.linalg.norm(vort, axis=1)
            return {
                "quantity": "vorticity",
                "n_cells": mesh.n_cells,
                "values": vort.tolist(),
                "magnitude": vort_mag.tolist(),
                "stats": _compute_stats(vort_mag),
                "note": "omega = curl(U); finite-difference on cell-centre cloud.",
            }

        if quantity == "q_criterion":
            if U_arr is None or U_arr.ndim != 2:
                return {"error": "velocity field U (3-D) required", "code": "NOT_FOUND"}
            Q = _q_criterion_on_cloud(centres, U_arr)
            return {
                "quantity": "q_criterion",
                "n_cells": mesh.n_cells,
                "values": Q.tolist(),
                "stats": _compute_stats(Q),
                "note": (
                    "Q = 0.5*(||Omega||^2 - ||S||^2); Q>0 = vortex core. "
                    "Hunt et al. (1988) CTR-S88."
                ),
            }

        if quantity == "gradient_p":
            if p_arr is None:
                return {"error": "pressure field not found", "code": "NOT_FOUND"}
            grad = _gradient_scalar_on_cloud(centres, p_arr.ravel())
            grad_mag = np.linalg.norm(grad, axis=1)
            return {
                "quantity": "gradient_p",
                "n_cells": mesh.n_cells,
                "values": grad.tolist(),
                "magnitude": grad_mag.tolist(),
                "stats": _compute_stats(grad_mag),
                "note": "grad(p); first-order FD on cell-centre cloud.",
            }

        if quantity == "divergence":
            if U_arr is None or U_arr.ndim != 2:
                return {"error": "velocity field U (3-D) required", "code": "NOT_FOUND"}
            div = _divergence_on_cloud(centres, U_arr)
            return {
                "quantity": "divergence",
                "n_cells": mesh.n_cells,
                "values": div.tolist(),
                "stats": _compute_stats(div),
                "note": "div(U); should be ~0 for incompressible flow.",
            }

        if quantity == "strain_rate":
            if U_arr is None or U_arr.ndim != 2:
                return {"error": "velocity field U (3-D) required", "code": "NOT_FOUND"}
            S_mag = _strain_rate_on_cloud(centres, U_arr)
            return {
                "quantity": "strain_rate",
                "n_cells": mesh.n_cells,
                "values": S_mag.tolist(),
                "stats": _compute_stats(S_mag),
                "note": "||S|| = sqrt(0.5 * Sij*Sij); Sij symmetric strain-rate tensor.",
            }

        return {"error": f"unknown quantity '{quantity}'", "code": "BAD_ARGS"}


# ---------------------------------------------------------------------------
# Gradient / curl helpers on unstructured cell-centre cloud
# ---------------------------------------------------------------------------
# We use a simple least-squares gradient:
#   For cell i, collect its k nearest neighbours, form (Δx, Δy, Δz) matrix
#   and solve  A · ∇f = Δf  for the gradient vector.
#
# This is a standard unstructured-mesh gradient approach (Green-Gauss fallback):
# Blazek (2015) "Computational Fluid Dynamics: Principles and Applications" §5.3.

def _knn_gradient(
    centres: np.ndarray,
    scalar: np.ndarray,
    k: int = 6,
) -> np.ndarray:
    """
    Least-squares gradient for a scalar field on an unstructured cell cloud.

    Returns grad(f), shape (ncells, 3).

    Reference: Blazek (2015) §5.3 — unstructured least-squares reconstruction.
    """
    ncells = len(centres)
    grad = np.zeros((ncells, 3))
    f = scalar.ravel()

    for i in range(ncells):
        diffs = centres - centres[i]
        dists = np.linalg.norm(diffs, axis=1)
        # Exclude self (dist = 0)
        dists[i] = np.inf
        kk = min(k, ncells - 1)
        if kk < 1:
            continue
        nbrs = np.argpartition(dists, kk)[:kk]
        A = diffs[nbrs]          # (k, 3)
        b = f[nbrs] - f[i]       # (k,)
        # Weighted least squares: weight by 1/distance
        w = 1.0 / (dists[nbrs] + 1e-300)
        Aw = A * w[:, np.newaxis]
        bw = b * w
        # Solve  (Aw^T Aw) g = Aw^T bw
        AtA = Aw.T @ Aw
        Atb = Aw.T @ bw
        try:
            g, _, _, _ = np.linalg.lstsq(AtA, Atb, rcond=None)
            grad[i] = g
        except np.linalg.LinAlgError:
            pass

    return grad


def _gradient_scalar_on_cloud(centres: np.ndarray, scalar: np.ndarray) -> np.ndarray:
    return _knn_gradient(centres, scalar, k=min(6, len(centres) - 1))


def _curl_on_cloud(centres: np.ndarray, U: np.ndarray) -> np.ndarray:
    """
    Curl of velocity via component-wise gradient:
        omega_x = dUz/dy - dUy/dz
        omega_y = dUx/dz - dUz/dx
        omega_z = dUy/dx - dUx/dy
    """
    grad_ux = _knn_gradient(centres, U[:, 0])
    grad_uy = _knn_gradient(centres, U[:, 1])
    grad_uz = _knn_gradient(centres, U[:, 2])
    vort = np.stack([
        grad_uz[:, 1] - grad_uy[:, 2],
        grad_ux[:, 2] - grad_uz[:, 0],
        grad_uy[:, 0] - grad_ux[:, 1],
    ], axis=1)
    return vort


def _divergence_on_cloud(centres: np.ndarray, U: np.ndarray) -> np.ndarray:
    """div(U) = dUx/dx + dUy/dy + dUz/dz."""
    grad_ux = _knn_gradient(centres, U[:, 0])
    grad_uy = _knn_gradient(centres, U[:, 1])
    grad_uz = _knn_gradient(centres, U[:, 2])
    return grad_ux[:, 0] + grad_uy[:, 1] + grad_uz[:, 2]


def _q_criterion_on_cloud(centres: np.ndarray, U: np.ndarray) -> np.ndarray:
    """
    Q = 0.5 * (||Omega||_F^2 - ||S||_F^2)
    where Omega = antisymmetric part, S = symmetric part of grad(U).

    Hunt J.C.R., Wray A.A., Moin P. (1988) CTR-S88.
    """
    grad_ux = _knn_gradient(centres, U[:, 0])
    grad_uy = _knn_gradient(centres, U[:, 1])
    grad_uz = _knn_gradient(centres, U[:, 2])
    ncells = len(centres)
    Q = np.zeros(ncells)
    for i in range(ncells):
        # Build 3×3 velocity gradient tensor
        J = np.array([
            [grad_ux[i, 0], grad_ux[i, 1], grad_ux[i, 2]],
            [grad_uy[i, 0], grad_uy[i, 1], grad_uy[i, 2]],
            [grad_uz[i, 0], grad_uz[i, 1], grad_uz[i, 2]],
        ])
        S = 0.5 * (J + J.T)
        Om = 0.5 * (J - J.T)
        Q[i] = 0.5 * (np.sum(Om ** 2) - np.sum(S ** 2))
    return Q


def _strain_rate_on_cloud(centres: np.ndarray, U: np.ndarray) -> np.ndarray:
    """||S|| = sqrt(0.5 * Sij * Sij)."""
    grad_ux = _knn_gradient(centres, U[:, 0])
    grad_uy = _knn_gradient(centres, U[:, 1])
    grad_uz = _knn_gradient(centres, U[:, 2])
    ncells = len(centres)
    S_mag = np.zeros(ncells)
    for i in range(ncells):
        J = np.array([
            [grad_ux[i, 0], grad_ux[i, 1], grad_ux[i, 2]],
            [grad_uy[i, 0], grad_uy[i, 1], grad_uy[i, 2]],
            [grad_uz[i, 0], grad_uz[i, 1], grad_uz[i, 2]],
        ])
        S = 0.5 * (J + J.T)
        S_mag[i] = math.sqrt(max(0.5 * np.sum(S ** 2), 0.0))
    return S_mag


# ---------------------------------------------------------------------------
# Utility helpers
# ---------------------------------------------------------------------------

def _get_field(mesh: CFDMesh, name: str) -> np.ndarray | None:
    """Retrieve field from point_data or cell_data by name."""
    if name in mesh.cell_data:
        return np.asarray(mesh.cell_data[name], dtype=float)
    if name in mesh.point_data:
        return np.asarray(mesh.point_data[name], dtype=float)
    return None


def _compute_stats(arr: np.ndarray | list | None) -> dict:
    if arr is None:
        return {}
    a = np.asarray(arr, dtype=float).ravel()
    if a.size == 0:
        return {"n": 0}
    return {
        "min": float(a.min()),
        "max": float(a.max()),
        "mean": float(a.mean()),
        "rms": float(np.sqrt(np.mean(a ** 2))),
        "n": int(a.size),
    }


def _serialize_arr(arr: np.ndarray | None) -> list:
    if arr is None:
        return []
    if isinstance(arr, np.ndarray):
        if arr.ndim == 2:
            return arr.tolist()
        return arr.tolist()
    return list(arr)
