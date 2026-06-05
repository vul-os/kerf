"""
tests/test_pointcloud_plant.py — Plant/infrastructure point-cloud integration tests.

Tests cover:
  • PLY round-trip (ASCII write + read_ply_ascii, and binary write + read_ply_binary)
  • voxel downsample reduces count deterministically
  • statistical_outlier_removal removes injected noise points
  • ransac_fit_plane recovers a known plane (XY plane z=0, tilted plane)
  • cloud_to_mesh_deviation correct on a synthetic cube-face case
  • LLM tools: pointcloud_import, pointcloud_deviation_check, pointcloud_fit_plane

Oracle rationale
----------------
All oracles use synthetic point clouds where the ground truth is analytically
known (perfect planes, exact meshes) so the tests are deterministic.

References
----------
Fischler & Bolles (1981). RANSAC. Commun. ACM 24(6):381-395.
Eberly (2003). Point-to-triangle distance. Geometric Tools.
Rusu & Cousins (2011). PCL. IEEE ICRA.
"""
from __future__ import annotations

import asyncio
import json
import math
import struct
import tempfile
import os
from pathlib import Path

import numpy as np
import pytest

from kerf_civil.pointcloud import (
    read_xyz,
    read_ply_ascii,
    read_ply_binary,
    read_ply,
    voxel_downsample,
    statistical_outlier_removal,
    point_cloud_aabb,
    cloud_to_mesh_deviation,
    ransac_fit_plane,
)
from kerf_civil.tools_pointcloud_plant import (
    pointcloud_import_spec,
    run_pointcloud_import,
    pointcloud_deviation_check_spec,
    run_pointcloud_deviation_check,
    pointcloud_fit_plane_spec,
    run_pointcloud_fit_plane,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ctx():
    try:
        from kerf_civil._compat import ProjectCtx
    except ImportError:
        from types import SimpleNamespace
        return SimpleNamespace(pool=None)
    return ProjectCtx()


def _call(handler, payload):
    raw = asyncio.run(handler(payload, _ctx()))
    return json.loads(raw)


def _make_flat_grid(nx=10, ny=10, z=0.0) -> np.ndarray:
    """nx * ny points on a flat grid in the XY plane at given z."""
    xs = np.linspace(0, nx - 1, nx)
    ys = np.linspace(0, ny - 1, ny)
    xx, yy = np.meshgrid(xs, ys)
    zz = np.full_like(xx, z)
    return np.column_stack([xx.ravel(), yy.ravel(), zz.ravel()])


def _write_ply_ascii(pts: np.ndarray) -> str:
    """Return an ASCII PLY string for the given (N, 3) array."""
    lines = [
        "ply",
        "format ascii 1.0",
        f"element vertex {len(pts)}",
        "property float x",
        "property float y",
        "property float z",
        "end_header",
    ]
    for p in pts:
        lines.append(f"{p[0]:.6f} {p[1]:.6f} {p[2]:.6f}")
    return "\n".join(lines) + "\n"


def _write_ply_binary_le(pts: np.ndarray) -> bytes:
    """
    Return a binary little-endian PLY blob for the given (N, 3) float32 array.
    """
    n = len(pts)
    header = (
        "ply\r\n"
        "format binary_little_endian 1.0\r\n"
        f"element vertex {n}\r\n"
        "property float x\r\n"
        "property float y\r\n"
        "property float z\r\n"
        "end_header\r\n"
    ).encode("ascii")
    # Pack as float32 (4 bytes each)
    data = struct.pack(f"<{n * 3}f", *pts.astype(np.float32).ravel().tolist())
    return header + data


# ---------------------------------------------------------------------------
# PLY round-trip: ASCII
# ---------------------------------------------------------------------------

class TestPLYAsciiRoundTrip:
    """PLY ASCII write → read_ply_ascii round-trip."""

    def test_round_trip_shape(self):
        pts = _make_flat_grid(5, 5)
        ply_text = _write_ply_ascii(pts)
        recovered = read_ply_ascii(ply_text)
        assert recovered.shape == (25, 3)

    def test_round_trip_values(self):
        pts = np.array([[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]])
        ply_text = _write_ply_ascii(pts)
        recovered = read_ply_ascii(ply_text)
        np.testing.assert_allclose(recovered, pts, atol=1e-5)

    def test_round_trip_via_read_ply(self):
        """read_ply() auto-dispatches to ASCII when format is ascii."""
        pts = _make_flat_grid(3, 4)
        ply_text = _write_ply_ascii(pts)
        recovered = read_ply(ply_text)
        assert recovered.shape == (12, 3)


# ---------------------------------------------------------------------------
# PLY round-trip: Binary
# ---------------------------------------------------------------------------

class TestPLYBinaryRoundTrip:
    """PLY binary write → read_ply_binary round-trip."""

    def test_round_trip_shape(self):
        pts = _make_flat_grid(5, 5)
        blob = _write_ply_binary_le(pts)
        with tempfile.NamedTemporaryFile(suffix=".ply", delete=False) as f:
            f.write(blob)
            fname = f.name
        try:
            recovered = read_ply_binary(fname)
        finally:
            os.unlink(fname)
        assert recovered.shape == (25, 3)

    def test_round_trip_values(self):
        pts = np.array([[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]], dtype=np.float32)
        blob = _write_ply_binary_le(pts)
        with tempfile.NamedTemporaryFile(suffix=".ply", delete=False) as f:
            f.write(blob)
            fname = f.name
        try:
            recovered = read_ply_binary(fname)
        finally:
            os.unlink(fname)
        np.testing.assert_allclose(recovered[:, :3], pts, atol=1e-4)

    def test_ascii_ply_raises(self):
        pts = _make_flat_grid(3, 3)
        ply_text = _write_ply_ascii(pts).encode("ascii")
        with tempfile.NamedTemporaryFile(suffix=".ply", delete=False) as f:
            f.write(ply_text)
            fname = f.name
        try:
            with pytest.raises(ValueError, match="ASCII PLY"):
                read_ply_binary(fname)
        finally:
            os.unlink(fname)

    def test_read_ply_auto_dispatch_binary(self):
        """read_ply() dispatches to binary reader when file format is binary."""
        pts = _make_flat_grid(4, 4)
        blob = _write_ply_binary_le(pts)
        with tempfile.NamedTemporaryFile(suffix=".ply", delete=False) as f:
            f.write(blob)
            fname = f.name
        try:
            recovered = read_ply(fname)
        finally:
            os.unlink(fname)
        assert recovered.shape == (16, 3)


# ---------------------------------------------------------------------------
# Voxel downsample — determinism
# ---------------------------------------------------------------------------

class TestVoxelDownsampleDeterminism:
    """Voxel downsample must reduce count and be deterministic."""

    def test_reduces_count(self):
        pts = _make_flat_grid(10, 10)  # 100 pts, 1 m spacing
        ds = voxel_downsample(pts, cell_size=2.0)
        assert len(ds) < len(pts)

    def test_deterministic(self):
        """Same input → same output on repeated calls."""
        pts = _make_flat_grid(10, 10)
        ds1 = voxel_downsample(pts, cell_size=2.0)
        ds2 = voxel_downsample(pts, cell_size=2.0)
        np.testing.assert_array_equal(ds1, ds2)

    def test_large_cell_collapses_to_one(self):
        pts = _make_flat_grid(10, 10)
        ds = voxel_downsample(pts, cell_size=100.0)
        assert len(ds) == 1

    def test_count_stable_across_shuffles(self):
        """Output count must be the same regardless of input ordering."""
        pts = _make_flat_grid(10, 10)
        rng = np.random.default_rng(42)
        shuffled = pts[rng.permutation(len(pts))]
        ds_orig = voxel_downsample(pts, cell_size=2.0)
        ds_shuf = voxel_downsample(shuffled, cell_size=2.0)
        # Same number of occupied voxels
        assert len(ds_orig) == len(ds_shuf)


# ---------------------------------------------------------------------------
# Statistical outlier removal
# ---------------------------------------------------------------------------

class TestStatisticalOutlierRemoval:
    """SOR filter must remove injected noise points."""

    def _cloud_with_outliers(self) -> np.ndarray:
        """Flat 10x10 grid + 5 random far-away points."""
        grid = _make_flat_grid(10, 10)  # 100 dense points
        outliers = np.array([
            [100.0, 100.0, 100.0],
            [-100.0, 50.0, 200.0],
            [500.0, 0.0, 0.0],
            [0.0, 500.0, 0.0],
            [0.0, 0.0, 500.0],
        ])
        return np.vstack([grid, outliers])

    def test_removes_outliers(self):
        pts = self._cloud_with_outliers()
        n_before = len(pts)  # 105
        clean = statistical_outlier_removal(pts, k=5, std_ratio=1.5)
        assert len(clean) < n_before

    def test_inliers_retained(self):
        """After SOR, the grid points (z=0) should mostly survive."""
        pts = self._cloud_with_outliers()
        clean = statistical_outlier_removal(pts, k=5, std_ratio=1.5)
        # Outlier z-coords are very large; inlier z=0
        z_vals = clean[:, 2]
        assert z_vals.max() < 10.0  # injected outliers (z=100..500) removed

    def test_no_outliers_unchanged(self):
        """Clean cloud of equal-density points — no points removed."""
        pts = _make_flat_grid(10, 10)
        clean = statistical_outlier_removal(pts, k=5, std_ratio=3.0)
        # Very generous threshold — all or nearly all should remain
        assert len(clean) >= len(pts) * 0.9

    def test_output_is_subset(self):
        """All returned points must be a subset of the input."""
        pts = self._cloud_with_outliers()
        clean = statistical_outlier_removal(pts, k=5, std_ratio=1.5)
        # Every row in clean must appear in pts
        for row in clean:
            dists = np.linalg.norm(pts - row, axis=1)
            assert dists.min() < 1e-9, f"Row {row} not found in input"


# ---------------------------------------------------------------------------
# RANSAC plane fit
# ---------------------------------------------------------------------------

class TestRansacFitPlane:
    """RANSAC must recover known planes reliably."""

    def test_horizontal_plane(self):
        """XY plane z=0 — normal must be [0,0,±1], d≈0."""
        pts = _make_flat_grid(10, 10, z=0.0)
        # Add small noise
        rng = np.random.default_rng(0)
        pts += rng.normal(0, 0.001, pts.shape)
        result = ransac_fit_plane(pts, threshold=0.05, max_iterations=200, seed=42)
        assert result["success"] is True
        nx, ny, nz = result["normal"]
        # Normal should be mostly vertical
        assert abs(nz) > 0.95, f"Expected nz≈1, got {nz}"
        # d should be close to 0 for a z=0 plane
        assert abs(result["d"]) < 0.1, f"d={result['d']}"

    def test_inlier_count_high_on_clean_plane(self):
        """Pure plane — all points should be inliers."""
        pts = _make_flat_grid(10, 10, z=5.0)
        result = ransac_fit_plane(pts, threshold=0.05, max_iterations=200, seed=0)
        assert result["success"] is True
        assert result["inlier_fraction"] > 0.9

    def test_tilted_plane_recovery(self):
        """Fit a plane tilted 45° from horizontal."""
        # Plane: x + z = 5, normal (1/√2, 0, 1/√2)
        t = np.linspace(0, 4, 20)
        s = np.linspace(0, 4, 20)
        tt, ss = np.meshgrid(t, s)
        x = tt.ravel()
        y = ss.ravel()
        z = 5.0 - x  # so x + z = 5
        pts = np.column_stack([x, y, z])
        rng = np.random.default_rng(7)
        pts += rng.normal(0, 0.005, pts.shape)

        result = ransac_fit_plane(pts, threshold=0.1, max_iterations=500, seed=7)
        assert result["success"] is True
        nx, ny, nz = result["normal"]
        # Should detect ~45° normal in xz-plane
        assert abs(abs(nz) - abs(nx)) < 0.3, f"normal={result['normal']}"

    def test_noisy_plane_with_outliers(self):
        """Plane with 20% random outliers — must still find the plane."""
        rng = np.random.default_rng(99)
        n_plane = 80
        n_outlier = 20
        plane_pts = _make_flat_grid(int(n_plane ** 0.5) + 1, int(n_plane ** 0.5) + 1)[:n_plane]
        outlier_pts = rng.uniform(-20, 20, (n_outlier, 3))
        outlier_pts[:, 2] = rng.uniform(5, 20, n_outlier)  # clearly off-plane
        pts = np.vstack([plane_pts, outlier_pts])

        result = ransac_fit_plane(pts, threshold=0.1, max_iterations=500, seed=99)
        assert result["success"] is True
        # Inlier fraction should reflect the plane points
        assert result["inlier_fraction"] > 0.5

    def test_deterministic_with_seed(self):
        """Same seed → same result."""
        pts = _make_flat_grid(8, 8)
        r1 = ransac_fit_plane(pts, threshold=0.05, max_iterations=100, seed=42)
        r2 = ransac_fit_plane(pts, threshold=0.05, max_iterations=100, seed=42)
        assert r1["inlier_count"] == r2["inlier_count"]
        assert r1["normal"] == r2["normal"]

    def test_too_few_points_raises(self):
        with pytest.raises(ValueError, match="3 points"):
            ransac_fit_plane(np.array([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0]]),
                             threshold=0.01)


# ---------------------------------------------------------------------------
# Cloud-to-mesh deviation
# ---------------------------------------------------------------------------

class TestCloudToMeshDeviation:
    """cloud_to_mesh_deviation must compute correct distances on synthetic cases."""

    def _unit_square_mesh(self):
        """
        A simple mesh: two triangles forming a 1×1 square in the XY plane (z=0).
        Vertices: (0,0,0), (1,0,0), (1,1,0), (0,1,0)
        Faces:    [0,1,2], [0,2,3]
        """
        verts = np.array([
            [0.0, 0.0, 0.0],
            [1.0, 0.0, 0.0],
            [1.0, 1.0, 0.0],
            [0.0, 1.0, 0.0],
        ])
        tris = np.array([[0, 1, 2], [0, 2, 3]])
        return verts, tris

    def test_zero_deviation_on_surface(self):
        """Points exactly on the mesh surface should have deviation ≈ 0."""
        verts, tris = self._unit_square_mesh()
        # Points on the XY-plane inside the square
        pts = np.array([
            [0.5, 0.5, 0.0],
            [0.25, 0.25, 0.0],
            [0.75, 0.75, 0.0],
        ])
        devs = cloud_to_mesh_deviation(pts, verts, tris)
        np.testing.assert_allclose(np.abs(devs), 0.0, atol=1e-9)

    def test_point_above_surface(self):
        """Point at z=+h above the XY square should have deviation ≈ +h."""
        verts, tris = self._unit_square_mesh()
        h = 0.3
        pts = np.array([[0.5, 0.5, h]])
        devs = cloud_to_mesh_deviation(pts, verts, tris)
        # Positive because above normal direction
        assert devs[0] == pytest.approx(h, abs=1e-9)

    def test_point_below_surface(self):
        """Point at z=-h below the XY square should have deviation ≈ -h."""
        verts, tris = self._unit_square_mesh()
        h = 0.25
        pts = np.array([[0.5, 0.5, -h]])
        devs = cloud_to_mesh_deviation(pts, verts, tris)
        # Negative because on the back-normal side
        assert devs[0] == pytest.approx(-h, abs=1e-9)

    def test_empty_points(self):
        verts, tris = self._unit_square_mesh()
        devs = cloud_to_mesh_deviation(np.zeros((0, 3)), verts, tris)
        assert len(devs) == 0

    def test_multiple_points_mixed_sign(self):
        """Cloud with points above and below mesh — sign must be correct."""
        verts, tris = self._unit_square_mesh()
        pts = np.array([
            [0.5, 0.5, 0.1],   # above → positive
            [0.5, 0.5, -0.1],  # below → negative
            [0.5, 0.5, 0.0],   # on surface → ~0
        ])
        devs = cloud_to_mesh_deviation(pts, verts, tris)
        assert devs[0] > 0, "Above should be positive"
        assert devs[1] < 0, "Below should be negative"
        assert abs(devs[2]) < 1e-9, f"On surface should be ~0, got {devs[2]}"

    def test_rms_correct(self):
        """RMS of [0.3, 0.3] = 0.3."""
        verts, tris = self._unit_square_mesh()
        pts = np.array([
            [0.5, 0.5, 0.3],
            [0.5, 0.5, -0.3],
        ])
        devs = cloud_to_mesh_deviation(pts, verts, tris)
        rms = float(np.sqrt((devs ** 2).mean()))
        assert rms == pytest.approx(0.3, abs=1e-9)


# ---------------------------------------------------------------------------
# AABB
# ---------------------------------------------------------------------------

class TestPointCloudAabb:
    def test_unit_cube(self):
        pts = np.array([
            [0, 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, 1],
            [1, 1, 0], [1, 0, 1], [0, 1, 1], [1, 1, 1],
        ], dtype=float)
        aabb = point_cloud_aabb(pts)
        assert aabb["min_x"] == pytest.approx(0.0)
        assert aabb["max_x"] == pytest.approx(1.0)
        assert aabb["size_z"] == pytest.approx(1.0)
        assert aabb["diagonal_m"] == pytest.approx(math.sqrt(3), abs=1e-6)
        assert aabb["volume_m3"] == pytest.approx(1.0, abs=1e-6)

    def test_empty(self):
        assert point_cloud_aabb(np.zeros((0, 3))) == {}


# ---------------------------------------------------------------------------
# LLM tool: pointcloud_import
# ---------------------------------------------------------------------------

class TestPointcloudImportTool:
    def test_spec_name(self):
        assert pointcloud_import_spec.name == "pointcloud_import"

    def test_spec_required(self):
        req = pointcloud_import_spec.input_schema["required"]
        assert "format" in req
        assert "data" in req

    def test_xyz_import_basic(self):
        xyz_text = "0 0 0\n1 0 0\n2 0 0\n0 1 0\n1 1 0\n"
        result = _call(run_pointcloud_import, {
            "format": "xyz",
            "data": xyz_text,
        })
        assert result.get("ok") is True
        assert result["n_points_raw"] == 5
        assert result["n_points_out"] == 5

    def test_xyz_with_voxel_downsample(self):
        # 100-point 10×10 grid
        lines = [f"{i}.0 {j}.0 0.0" for i in range(10) for j in range(10)]
        xyz_text = "\n".join(lines) + "\n"
        result = _call(run_pointcloud_import, {
            "format": "xyz",
            "data": xyz_text,
            "voxel_cell_size": 2.0,
        })
        assert result.get("ok") is True
        assert result["n_points_out"] < 100

    def test_ply_ascii_import(self):
        pts = np.array([[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]])
        ply_text = _write_ply_ascii(pts)
        result = _call(run_pointcloud_import, {
            "format": "ply_ascii",
            "data": ply_text,
        })
        assert result.get("ok") is True
        assert result["n_points_raw"] == 2

    def test_ply_binary_import(self):
        pts = _make_flat_grid(5, 5)
        blob = _write_ply_binary_le(pts)
        with tempfile.NamedTemporaryFile(suffix=".ply", delete=False) as f:
            f.write(blob)
            fname = f.name
        try:
            result = _call(run_pointcloud_import, {
                "format": "ply_binary",
                "data": fname,
            })
        finally:
            os.unlink(fname)
        assert result.get("ok") is True
        assert result["n_points_raw"] == 25

    def test_aabb_in_result(self):
        xyz_text = "0 0 0\n10 0 0\n0 10 0\n10 10 0\n"
        result = _call(run_pointcloud_import, {
            "format": "xyz",
            "data": xyz_text,
        })
        assert result.get("ok") is True
        aabb = result.get("aabb", {})
        assert aabb.get("size_x") == pytest.approx(10.0, abs=1e-6)

    def test_points_returned_up_to_max(self):
        lines = [f"{i}.0 0.0 0.0" for i in range(100)]
        result = _call(run_pointcloud_import, {
            "format": "xyz",
            "data": "\n".join(lines) + "\n",
            "max_return_pts": 10,
        })
        assert result.get("ok") is True
        assert len(result.get("points", [])) <= 10

    def test_unknown_format_error(self):
        result = _call(run_pointcloud_import, {
            "format": "xyz",
            "data": "# only comments",
        })
        assert "error" in result


# ---------------------------------------------------------------------------
# LLM tool: pointcloud_deviation_check
# ---------------------------------------------------------------------------

class TestPointcloudDeviationCheckTool:
    def test_spec_name(self):
        assert pointcloud_deviation_check_spec.name == "pointcloud_deviation_check"

    def test_deviation_above_mesh(self):
        """Points at z=0.05 above XY plane quad mesh."""
        pts = [[0.5, 0.5, 0.05]]
        verts = [[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0]]
        tris = [[0, 1, 2], [0, 2, 3]]
        result = _call(run_pointcloud_deviation_check, {
            "points": pts,
            "vertices": verts,
            "triangles": tris,
            "tolerance_m": 0.01,
        })
        assert result.get("ok") is True
        assert result["deviation_max_m"] == pytest.approx(0.05, abs=1e-6)
        assert result["n_protrusions"] == 1
        assert result["n_depressions"] == 0

    def test_deviation_within_tolerance(self):
        """Point exactly on mesh — within tolerance."""
        pts = [[0.5, 0.5, 0.0]]
        verts = [[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0]]
        tris = [[0, 1, 2], [0, 2, 3]]
        result = _call(run_pointcloud_deviation_check, {
            "points": pts,
            "vertices": verts,
            "triangles": tris,
            "tolerance_m": 0.01,
        })
        assert result.get("ok") is True
        assert result["n_within_tolerance"] == 1
        assert result["fraction_within_pct"] == pytest.approx(100.0)

    def test_heatmap_colors_length(self):
        """heatmap_colors must have one entry per point."""
        pts = [[0.5, 0.5, 0.1], [0.5, 0.5, -0.1], [0.5, 0.5, 0.0]]
        verts = [[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0]]
        tris = [[0, 1, 2], [0, 2, 3]]
        result = _call(run_pointcloud_deviation_check, {
            "points": pts,
            "vertices": verts,
            "triangles": tris,
        })
        assert result.get("ok") is True
        assert len(result["heatmap_colors"]) == 3

    def test_empty_points_error(self):
        result = _call(run_pointcloud_deviation_check, {
            "points": [],
            "vertices": [[0, 0, 0], [1, 0, 0], [0, 1, 0]],
            "triangles": [[0, 1, 2]],
        })
        assert "error" in result


# ---------------------------------------------------------------------------
# LLM tool: pointcloud_fit_plane
# ---------------------------------------------------------------------------

class TestPointcloudFitPlaneTool:
    def test_spec_name(self):
        assert pointcloud_fit_plane_spec.name == "pointcloud_fit_plane"

    def test_horizontal_plane(self):
        pts = _make_flat_grid(8, 8, z=0.0).tolist()
        result = _call(run_pointcloud_fit_plane, {
            "points": pts,
            "threshold_m": 0.05,
            "max_iterations": 200,
            "seed": 42,
        })
        assert result.get("ok") is True
        assert result["success"] is True
        # Horizontal plane: |nz| should be close to 1
        assert abs(result["normal"][2]) > 0.95

    def test_level_check_pass_for_horizontal(self):
        """A horizontal XY plane should be labelled 'level' (dip_deg≈90 → level_check=PASS)."""
        pts = _make_flat_grid(6, 6, z=0.0).tolist()
        result = _call(run_pointcloud_fit_plane, {
            "points": pts,
            "seed": 0,
        })
        assert result.get("ok") is True
        # Horizontal plane: normal is nearly vertical (nz≈1), dip_deg≈90°.
        # level_check = PASS when dip_deg > 89° (plane is horizontal / level floor)
        assert result["level_check"] == "PASS"

    def test_vertical_plane_check(self):
        """XZ plane (y=0) is vertical — plumb_check PASS (normal is horizontal, surface is vertical)."""
        # Points in the XZ plane: y=0
        pts = []
        for x in np.linspace(0, 5, 10):
            for z in np.linspace(0, 5, 10):
                pts.append([float(x), 0.0, float(z)])
        result = _call(run_pointcloud_fit_plane, {
            "points": pts,
            "seed": 1,
        })
        assert result.get("ok") is True
        # XZ plane normal is [0,1,0] → nz=0 → dip_deg=0° → plumb_check=PASS (surface is vertical/plumb)
        assert result["plumb_check"] == "PASS"

    def test_high_inlier_fraction_on_clean_plane(self):
        pts = _make_flat_grid(10, 10).tolist()
        result = _call(run_pointcloud_fit_plane, {
            "points": pts,
            "threshold_m": 0.05,
            "seed": 5,
        })
        assert result.get("ok") is True
        assert result["inlier_fraction"] > 0.9

    def test_too_few_points_error(self):
        result = _call(run_pointcloud_fit_plane, {
            "points": [[0, 0, 0], [1, 0, 0]],
        })
        assert "error" in result
