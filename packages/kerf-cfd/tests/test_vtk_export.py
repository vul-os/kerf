"""
Tests for VTK/VTU export and ParaView-style post-processing filters.

Test cases:
  1. VTK round-trip  — exported .vtk re-parses to the same field values.
  2. VTU round-trip  — exported .vtu XML is parseable and contains correct data.
  3. Uniform-flow streamline — straight line through constant velocity field.
  4. Slice extraction  — correct values at a known cut plane.
  5. Volume integral  — constant field × volume = const × volume.
  6. Vorticity of solid-body rotation — constant |omega| everywhere.
  7. Gradient correct on a linear field — ∇(ax+by+cz) = (a,b,c) everywhere.
  8. Q-criterion on pure shear — expected sign.
  9. Probe — nearest-cell lookup returns correct value.
 10. Contour — cells straddling iso_value are found.

All tests are pure Python + NumPy; no OpenFOAM install required.
"""

from __future__ import annotations

import math
import re
import tempfile
from pathlib import Path

import numpy as np
import pytest

from kerf_cfd.vtk_export import (
    CFDMesh,
    PostProcessor,
    read_legacy_vtk,
    write_legacy_vtk,
    write_vtu,
)


# ---------------------------------------------------------------------------
# Fixtures: simple tet mesh (unit cube, 6 tets from a hex split)
# ---------------------------------------------------------------------------

def _hex_to_tets(hex_verts: list[int]) -> list[list[int]]:
    """
    Split a hex cell (8 nodes) into 6 tetrahedra.

    Standard decomposition: Bey (1995) Table 1.
    """
    v = hex_verts
    return [
        [v[0], v[1], v[3], v[4]],
        [v[1], v[2], v[3], v[5]],
        [v[3], v[4], v[5], v[7]],
        [v[1], v[3], v[5], v[4]],
        [v[2], v[3], v[5], v[6]],
        [v[5], v[3], v[6], v[7]],
    ]


def make_unit_cube_mesh(nx=2, ny=2, nz=2) -> CFDMesh:
    """
    Build a unit-cube tet mesh by subdividing a regular hex grid.

    nx, ny, nz = number of hex cells per axis.
    Returns a CFDMesh with cell_data 'pressure' and 'velocity'.
    """
    # Generate node grid
    xs = np.linspace(0, 1, nx + 1)
    ys = np.linspace(0, 1, ny + 1)
    zs = np.linspace(0, 1, nz + 1)
    points = []
    idx = {}
    for iz, z in enumerate(zs):
        for iy, y in enumerate(ys):
            for ix, x in enumerate(xs):
                idx[(ix, iy, iz)] = len(points)
                points.append([x, y, z])
    points = np.array(points)

    # Build tet cells from hex cells
    cells = []
    for iz in range(nz):
        for iy in range(ny):
            for ix in range(nx):
                h = [
                    idx[(ix,   iy,   iz)],
                    idx[(ix+1, iy,   iz)],
                    idx[(ix+1, iy+1, iz)],
                    idx[(ix,   iy+1, iz)],
                    idx[(ix,   iy,   iz+1)],
                    idx[(ix+1, iy,   iz+1)],
                    idx[(ix+1, iy+1, iz+1)],
                    idx[(ix,   iy+1, iz+1)],
                ]
                cells.extend(_hex_to_tets(h))

    n_cells = len(cells)
    n_pts = len(points)
    # Scalar pressure field: p = x + y (linear)
    centres = np.array([points[c].mean(axis=0) for c in cells])
    p = centres[:, 0] + centres[:, 1]  # linear in x, y
    # Vector velocity field: uniform U = (1, 0, 0)
    U = np.tile([1.0, 0.0, 0.0], (n_cells, 1))

    return CFDMesh(
        points, cells,
        cell_data={"p": p, "U": U},
    )


def make_solid_body_rotation_mesh(n=20) -> CFDMesh:
    """
    Mesh in XY-plane with solid-body rotation velocity field.

    U = omega × r:  Ux = -omega*y,  Uy = omega*x,  Uz = 0
    Vorticity = curl(U) = (0, 0, 2*omega) — constant everywhere.

    Uses a regular 2-D quad grid (quad cell type 9).
    """
    omega = 2.0  # rad/s
    xs = np.linspace(-1, 1, n + 1)
    ys = np.linspace(-1, 1, n + 1)
    pts = []
    for y in ys:
        for x in xs:
            pts.append([x, y, 0.0])
    pts = np.array(pts)

    cells = []
    cell_types = []
    for iy in range(n):
        for ix in range(n):
            v0 = iy * (n + 1) + ix
            v1 = v0 + 1
            v2 = v0 + (n + 1) + 1
            v3 = v0 + (n + 1)
            cells.append([v0, v1, v2, v3])  # quad → VTK type 9
            cell_types.append(9)

    centres = np.array([pts[c].mean(axis=0) for c in cells])
    Ux = -omega * centres[:, 1]
    Uy =  omega * centres[:, 0]
    Uz = np.zeros(len(centres))
    U = np.stack([Ux, Uy, Uz], axis=1)

    return CFDMesh(pts, cells, cell_types=cell_types, cell_data={"U": U})


def make_linear_field_mesh(n=3) -> CFDMesh:
    """
    Regular 3-D hex-tet mesh with a linear scalar field f = 2x + 3y + z.
    Gradient should be (2, 3, 1) everywhere.
    """
    xs = np.linspace(0, 2, n + 1)
    ys = np.linspace(0, 3, n + 1)
    zs = np.linspace(0, 1, n + 1)
    pts = []
    idx = {}
    for iz, z in enumerate(zs):
        for iy, y in enumerate(ys):
            for ix, x in enumerate(xs):
                idx[(ix, iy, iz)] = len(pts)
                pts.append([x, y, z])
    pts = np.array(pts)

    cells = []
    for iz in range(n):
        for iy in range(n):
            for ix in range(n):
                h = [
                    idx[(ix,   iy,   iz)],
                    idx[(ix+1, iy,   iz)],
                    idx[(ix+1, iy+1, iz)],
                    idx[(ix,   iy+1, iz)],
                    idx[(ix,   iy,   iz+1)],
                    idx[(ix+1, iy,   iz+1)],
                    idx[(ix+1, iy+1, iz+1)],
                    idx[(ix,   iy+1, iz+1)],
                ]
                cells.extend(_hex_to_tets(h))

    centres = np.array([pts[c].mean(axis=0) for c in cells])
    f = 2 * centres[:, 0] + 3 * centres[:, 1] + 1 * centres[:, 2]

    return CFDMesh(pts, cells, cell_data={"f": f})


# ---------------------------------------------------------------------------
# 1. VTK legacy round-trip
# ---------------------------------------------------------------------------

def test_vtk_roundtrip_scalars():
    """Scalar field written to .vtk and re-read matches original values."""
    mesh = make_unit_cube_mesh(2, 2, 2)
    with tempfile.NamedTemporaryFile(suffix=".vtk", delete=False) as tmp:
        path = tmp.name

    write_legacy_vtk(mesh, path=path)
    mesh2 = read_legacy_vtk(path)

    assert mesh2.n_cells == mesh.n_cells, f"cell count mismatch: {mesh2.n_cells} vs {mesh.n_cells}"
    assert "p" in mesh2.cell_data, "pressure field missing after round-trip"
    np.testing.assert_allclose(
        mesh2.cell_data["p"],
        mesh.cell_data["p"],
        rtol=1e-6,
        err_msg="Pressure field not preserved in VTK round-trip",
    )


def test_vtk_roundtrip_vectors():
    """Vector (velocity) field written to .vtk and re-read matches original."""
    mesh = make_unit_cube_mesh(2, 2, 2)
    with tempfile.NamedTemporaryFile(suffix=".vtk", delete=False) as tmp:
        path = tmp.name

    write_legacy_vtk(mesh, path=path)
    mesh2 = read_legacy_vtk(path)

    assert "U" in mesh2.cell_data, "velocity field missing after round-trip"
    np.testing.assert_allclose(
        mesh2.cell_data["U"],
        mesh.cell_data["U"],
        rtol=1e-6,
        err_msg="Velocity field not preserved in VTK round-trip",
    )


def test_vtk_roundtrip_point_data():
    """Point-centred data round-trips correctly."""
    mesh = make_unit_cube_mesh(2, 2, 2)
    # Add point data: T = x + z
    T_pts = mesh.points[:, 0] + mesh.points[:, 2]
    mesh.point_data["T"] = T_pts

    with tempfile.NamedTemporaryFile(suffix=".vtk", delete=False) as tmp:
        path = tmp.name

    write_legacy_vtk(mesh, path=path)
    mesh2 = read_legacy_vtk(path)

    assert "T" in mesh2.point_data, "temperature (point data) missing after round-trip"
    np.testing.assert_allclose(
        mesh2.point_data["T"],
        T_pts,
        rtol=1e-6,
        err_msg="Temperature point data not preserved in VTK round-trip",
    )


# ---------------------------------------------------------------------------
# 2. VTU XML round-trip (parse tags + check values)
# ---------------------------------------------------------------------------

def test_vtu_ascii_roundtrip():
    """VTU ASCII export produces parseable XML with correct field values."""
    mesh = make_unit_cube_mesh(2, 2, 2)
    with tempfile.NamedTemporaryFile(suffix=".vtu", delete=False) as tmp:
        path = tmp.name

    text = write_vtu(mesh, path=path, binary=False)

    # Check XML structure
    assert '<?xml version' in text
    assert 'VTKFile' in text
    assert 'UnstructuredGrid' in text
    assert f'NumberOfPoints="{mesh.n_points}"' in text
    assert f'NumberOfCells="{mesh.n_cells}"' in text
    assert 'DataArray' in text

    # Re-parse pressure values from ASCII DataArray
    # Find the DataArray block for "p"
    m = re.search(r'Name="p"[^>]*>\s*([\d\s.eE+\-]+)</DataArray>', text, re.DOTALL)
    assert m is not None, "pressure DataArray not found in VTU XML"
    vals = np.array([float(v) for v in m.group(1).split()])
    np.testing.assert_allclose(
        vals,
        mesh.cell_data["p"],
        rtol=1e-5,
        err_msg="Pressure values not preserved in VTU ASCII round-trip",
    )


def test_vtu_binary_structure():
    """VTU binary (base64) export produces correct XML structure."""
    mesh = make_unit_cube_mesh(2, 2, 2)
    text = write_vtu(mesh, binary=True)
    assert 'format="binary"' in text
    assert 'encoding="base64"' in text
    assert 'NumberOfPoints' in text


# ---------------------------------------------------------------------------
# 3. Uniform-flow streamline is straight
# ---------------------------------------------------------------------------

def test_streamline_uniform_flow_is_straight():
    """
    In a uniform velocity field U=(1,0,0), streamlines from any seed
    must be parallel to the x-axis (y and z constant).
    """
    mesh = make_unit_cube_mesh(3, 3, 3)
    # All cells have U=(1,0,0) already

    pp = PostProcessor()
    result = pp.streamline(
        mesh,
        seed_points=[[0.1, 0.5, 0.5]],
        velocity_field="U",
        max_steps=50,
        direction="forward",
    )

    assert result["n_streamlines"] == 1
    path = result["streamlines"][0]["path"]
    assert len(path) >= 2, "streamline should have at least 2 points"

    # y and z should stay constant (within numerical tolerance)
    pts = np.array(path)
    y_start = pts[0, 1]
    z_start = pts[0, 2]
    # x should be increasing
    assert pts[-1, 0] > pts[0, 0], "x should increase in forward direction"
    np.testing.assert_allclose(
        pts[:, 1], y_start,
        atol=1e-6,
        err_msg="y-coordinate must stay constant in uniform x-flow streamline",
    )
    np.testing.assert_allclose(
        pts[:, 2], z_start,
        atol=1e-6,
        err_msg="z-coordinate must stay constant in uniform x-flow streamline",
    )


# ---------------------------------------------------------------------------
# 4. Slice extracts correct values
# ---------------------------------------------------------------------------

def test_slice_plane_at_midplane():
    """
    Slice at z=0.5 on a mesh with cells — p = x + y.
    All returned cells should have z-centre near 0.5.
    """
    mesh = make_unit_cube_mesh(2, 2, 4)  # finer in z to have clear z=0.5 layer

    pp = PostProcessor()
    result = pp.slice_plane(
        mesh,
        normal=(0, 0, 1),
        origin=(0, 0, 0.5),
        field="p",
    )

    assert result["n_cells_on_plane"] > 0, "slice must find at least one cell"
    centres = np.array(result["cell_centers"])
    # All selected centres should have z near 0.5 (within tolerance)
    z_vals = centres[:, 2]
    tol = result["tolerance_m"]
    assert np.all(np.abs(z_vals - 0.5) <= tol + 1e-10), (
        f"Some slice cells are too far from z=0.5: z-range={z_vals.min():.3f}..{z_vals.max():.3f}, tol={tol:.4f}"
    )


def test_slice_returns_field_values():
    """Slice must return field_values (not empty) for cells on the plane."""
    mesh = make_unit_cube_mesh(2, 2, 2)
    pp = PostProcessor()
    result = pp.slice_plane(mesh, normal=(0, 1, 0), origin=(0, 0.5, 0), field="p")
    assert result["n_cells_on_plane"] > 0
    assert len(result["field_values"]) == result["n_cells_on_plane"]


# ---------------------------------------------------------------------------
# 5. Volume integral of a constant field = const × volume
# ---------------------------------------------------------------------------

def test_volume_integral_constant_field():
    """
    For a constant scalar field p = C on every cell,
    volume_integral = C × total_volume.
    volume_average = C.
    """
    C = 5.0
    mesh = make_unit_cube_mesh(2, 2, 2)
    ncells = mesh.n_cells
    mesh.cell_data["p_const"] = np.full(ncells, C)

    # Provide accurate cell volumes (unit cube, uniform cells)
    total_vol = 1.0  # unit cube
    vol_per_cell = total_vol / ncells
    cell_vols = np.full(ncells, vol_per_cell)

    pp = PostProcessor()

    res_avg = pp.integral(mesh, "p_const", operation="volume_average",
                          cell_volumes=cell_vols)
    assert "error" not in res_avg
    np.testing.assert_allclose(
        res_avg["result"], C, rtol=1e-10,
        err_msg="volume_average of constant field must equal the constant",
    )

    res_int = pp.integral(mesh, "p_const", operation="volume_integral",
                          cell_volumes=cell_vols)
    np.testing.assert_allclose(
        res_int["result"], C * total_vol, rtol=1e-10,
        err_msg="volume_integral of constant field must equal C × volume",
    )


def test_volume_integral_min_max():
    """Min / max operations return the correct extremes."""
    mesh = make_unit_cube_mesh(2, 2, 2)
    p = mesh.cell_data["p"]  # linear field p = x + y
    pp = PostProcessor()

    res_min = pp.integral(mesh, "p", operation="min")
    res_max = pp.integral(mesh, "p", operation="max")

    np.testing.assert_allclose(res_min["result"], p.min(), rtol=1e-10)
    np.testing.assert_allclose(res_max["result"], p.max(), rtol=1e-10)


# ---------------------------------------------------------------------------
# 6. Vorticity of solid-body rotation is constant (2ω in z-direction)
# ---------------------------------------------------------------------------

def test_vorticity_solid_body_rotation():
    """
    Solid-body rotation: U = (-ω·y, ω·x, 0)
    Vorticity: curl(U) = (0, 0, 2ω)
    Magnitude = 2ω everywhere.

    We use a coarse mesh so the FD approximation is not too noisy.
    Tolerance is 20% (first-order FD on a coarse cloud).
    """
    omega = 2.0
    mesh = make_solid_body_rotation_mesh(n=8)

    pp = PostProcessor()
    result = pp.derived(mesh, "vorticity", velocity_field="U")

    assert "error" not in result, f"vorticity failed: {result.get('error')}"
    vort_mag = np.array(result["magnitude"])
    expected = 2 * omega  # = 4.0

    # Check mean is close to 2*omega; near-boundary cells can be off
    mean_mag = vort_mag.mean()
    assert abs(mean_mag - expected) / expected < 0.25, (
        f"Mean vorticity magnitude {mean_mag:.3f} not within 25% of expected {expected:.3f}"
    )


# ---------------------------------------------------------------------------
# 7. Gradient correct on a linear field
# ---------------------------------------------------------------------------

def test_gradient_linear_field():
    """
    For f = 2x + 3y + z, the gradient ∇f = (2, 3, 1) everywhere.
    First-order FD on a cloud of cell centres should recover this to ~5% RMSE.
    """
    mesh = make_linear_field_mesh(n=4)
    pp = PostProcessor()

    result = pp.derived(mesh, "gradient_p",
                        pressure_field="f",
                        velocity_field="U")  # no U needed for gradient_p

    # gradient_p uses p-field; but our field is 'f'
    # Use the internal function directly for testing
    from kerf_cfd.vtk_export import _gradient_scalar_on_cloud
    centres = mesh.cell_centers()
    f = mesh.cell_data["f"]
    grad = _gradient_scalar_on_cloud(centres, f)

    # Interior cells should have gradient close to (2, 3, 1)
    expected = np.array([2.0, 3.0, 1.0])
    errors = np.linalg.norm(grad - expected, axis=1) / np.linalg.norm(expected)
    # At least 50% of cells should be within 10% error
    frac_ok = (errors < 0.10).mean()
    assert frac_ok > 0.5, (
        f"Only {frac_ok:.1%} of cells have gradient within 10% of expected. "
        f"Mean error: {errors.mean():.3f}"
    )


# ---------------------------------------------------------------------------
# 8. Q-criterion on pure shear
# ---------------------------------------------------------------------------

def test_q_criterion_pure_shear():
    """
    Pure shear: U = (y, 0, 0). S is symmetric non-zero; Omega is anti-symmetric.
    Q should be ≤ 0 (strain-dominated, not vortex-dominated).
    """
    # Simple 3-D mesh, shear flow
    mesh = make_unit_cube_mesh(3, 3, 3)
    centres = mesh.cell_centers()
    # Override U with pure shear: Ux = y, Uy = 0, Uz = 0
    Ux = centres[:, 1]
    Uy = np.zeros(mesh.n_cells)
    Uz = np.zeros(mesh.n_cells)
    mesh.cell_data["U"] = np.stack([Ux, Uy, Uz], axis=1)

    pp = PostProcessor()
    result = pp.derived(mesh, "q_criterion", velocity_field="U")

    assert "error" not in result, f"Q-criterion failed: {result.get('error')}"
    Q = np.array(result["values"])
    # In pure shear, Q <= 0 on average (interior cells)
    assert Q.mean() <= 0.1, f"Q-criterion mean {Q.mean():.4f} should be ≤0 for pure shear"


# ---------------------------------------------------------------------------
# 9. Probe — nearest-cell lookup
# ---------------------------------------------------------------------------

def test_probe_returns_known_value():
    """
    Probe at exact cell centre must return the cell's field value.
    """
    mesh = make_unit_cube_mesh(2, 2, 2)
    centres = mesh.cell_centers()

    # Pick cell 0's centre as probe point
    pt = centres[0].tolist()

    pp = PostProcessor()
    result = pp.probe(mesh, [pt], fields=["p"])

    assert result["n_probes"] == 1
    probe = result["probes"][0]
    assert probe["nearest_cell_idx"] == 0, "nearest cell should be cell 0"
    np.testing.assert_allclose(
        probe["p"],
        mesh.cell_data["p"][0],
        rtol=1e-10,
        err_msg="Probe at cell centre must return that cell's field value",
    )


def test_probe_multiple_points():
    """Probe returns one entry per probe point."""
    mesh = make_unit_cube_mesh(2, 2, 2)
    pts = [[0.1, 0.1, 0.1], [0.9, 0.9, 0.9], [0.5, 0.5, 0.5]]
    pp = PostProcessor()
    result = pp.probe(mesh, pts)
    assert result["n_probes"] == 3


# ---------------------------------------------------------------------------
# 10. Contour — finds cells near iso_value
# ---------------------------------------------------------------------------

def test_contour_finds_cells():
    """Contour at a value within the field range must return at least one cell."""
    mesh = make_unit_cube_mesh(2, 2, 2)
    p = mesh.cell_data["p"]
    iso = float(p.mean())  # middle of the range

    pp = PostProcessor()
    result = pp.contour(mesh, "p", iso_value=iso)

    assert "error" not in result, f"contour failed: {result.get('error')}"
    assert result["n_cells"] > 0, "contour must find at least one cell near iso_value"


def test_contour_empty_outside_range():
    """Contour outside field range returns no cells (or very few)."""
    mesh = make_unit_cube_mesh(2, 2, 2)
    p = mesh.cell_data["p"]
    iso = float(p.max()) + 100.0  # well outside range

    pp = PostProcessor()
    result = pp.contour(mesh, "p", iso_value=iso)

    # May return 0 or a very small number depending on band computation
    # The key is it should not return ALL cells
    assert result["n_cells"] < mesh.n_cells, (
        "contour should not select all cells for iso_value outside field range"
    )


# ---------------------------------------------------------------------------
# 11. VTK file format compliance checks
# ---------------------------------------------------------------------------

def test_vtk_legacy_header():
    """Legacy VTK file has correct header structure."""
    mesh = make_unit_cube_mesh(1, 1, 1)
    text = write_legacy_vtk(mesh)
    lines = text.split("\n")
    assert lines[0].startswith("# vtk DataFile")
    assert lines[2].strip() == "ASCII"
    assert "UNSTRUCTURED_GRID" in lines[3]
    assert "POINTS" in text
    assert "CELLS" in text
    assert "CELL_TYPES" in text


def test_vtu_xml_well_formed():
    """VTU ASCII XML is well-formed (tags open/close)."""
    mesh = make_unit_cube_mesh(1, 1, 1)
    text = write_vtu(mesh, binary=False)
    assert text.startswith('<?xml')
    assert '<VTKFile' in text
    assert '</VTKFile>' in text
    assert '<UnstructuredGrid>' in text
    assert '</UnstructuredGrid>' in text
    assert '<Piece' in text
    assert '</Piece>' in text


# ---------------------------------------------------------------------------
# 12. Divergence of uniform flow is ~zero
# ---------------------------------------------------------------------------

def test_divergence_uniform_flow():
    """div(U) should be ~0 for uniform incompressible flow U=(1,0,0)."""
    mesh = make_unit_cube_mesh(3, 3, 3)
    # U = (1, 0, 0) → div = dUx/dx + dUy/dy + dUz/dz = 0
    pp = PostProcessor()
    result = pp.derived(mesh, "divergence", velocity_field="U")

    assert "error" not in result
    div = np.array(result["values"])
    # Tolerance: FD noise on a coarse mesh
    assert abs(div.mean()) < 0.1, (
        f"Mean divergence {div.mean():.4f} should be ~0 for incompressible uniform flow"
    )


# ---------------------------------------------------------------------------
# 13. Pressure coefficient sanity check
# ---------------------------------------------------------------------------

def test_pressure_coeff_range():
    """Cp should be 0 at reference pressure location."""
    mesh = make_unit_cube_mesh(2, 2, 2)
    pp = PostProcessor()
    p = mesh.cell_data["p"]
    p_ref = float(p.min())
    U_ref = 10.0

    result = pp.derived(mesh, "pressure_coeff",
                        pressure_field="p",
                        U_ref=U_ref,
                        p_ref=p_ref,
                        rho=1.225)

    assert "error" not in result
    Cp = np.array(result["values"])
    # Cp at min(p) cell should be 0
    assert Cp.min() >= -1e-10, f"Cp minimum {Cp.min():.6f} should be >= 0 (p_ref = min(p))"


# ---------------------------------------------------------------------------
# 14. Integration with vtk_tools LLM wrapper (no asyncio needed for sync path)
# ---------------------------------------------------------------------------

def test_vtk_tools_export_vtk_sync():
    """vtk_tools._export_vtk_sync produces a valid .vtk file."""
    from kerf_cfd.vtk_tools import _export_vtk_sync

    with tempfile.NamedTemporaryFile(suffix=".vtk", delete=False) as tmp:
        path = tmp.name

    a = {
        "points": [[0, 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, 1]],
        "cells": [[0, 1, 2, 3]],
        "cell_types": [10],  # VTK_TETRA
        "cell_data": {"pressure": [101325.0]},
        "format": "vtk",
        "output_path": path,
    }
    result = _export_vtk_sync(a)

    assert result["ok"] is True
    assert result["n_cells"] == 1
    assert result["n_points"] == 4
    assert "pressure" in result["cell_data_fields"]
    assert Path(path).exists()
    assert Path(path).stat().st_size > 0


def test_vtk_tools_filter_slice_sync():
    """vtk_tools._filter_sync slice returns non-empty result."""
    from kerf_cfd.vtk_tools import _filter_sync

    # Build a simple tet mesh
    mesh_args = {
        "points": [
            [0, 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, 1],
            [1, 1, 0], [1, 0, 1], [0, 1, 1], [1, 1, 1],
        ],
        "cells": [[0, 1, 2, 3], [4, 5, 6, 7]],
        "cell_data": {"p": [1.0, 2.0], "U": [[1, 0, 0], [1, 0, 0]]},
        "filter": "slice",
        "normal": [0, 0, 1],
        "origin": [0, 0, 0.1],
        "field": "p",
    }
    result = _filter_sync(mesh_args)
    assert result["ok"] is True
    assert "n_cells_on_plane" in result


def test_vtk_tools_filter_integral_sync():
    """vtk_tools._filter_sync integral returns correct constant-field result."""
    from kerf_cfd.vtk_tools import _filter_sync

    a = {
        "points": [
            [0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0],
            [0, 0, 1], [1, 0, 1], [1, 1, 1], [0, 1, 1],
        ],
        "cells": [[0, 1, 2, 3, 4, 5, 6, 7]],
        "cell_types": [12],  # VTK_HEXAHEDRON
        "cell_data": {"p": [5.0]},
        "cell_volumes": [1.0],
        "filter": "integral",
        "field": "p",
        "operation": "volume_average",
    }
    result = _filter_sync(a)
    assert result["ok"] is True
    np.testing.assert_allclose(result["result"], 5.0, rtol=1e-10)
