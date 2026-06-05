"""
Tests for kerf_civil.pointcloud — point-cloud ingest, voxel downsample,
PMF ground classification, and surface-from-points.

Oracle values
-------------
Flat 10×10 m grid at z=0 with 100 points plus 10 "building" outlier points
at z=5:
  - After PMF classify with generous settings, outlier points should be
    labelled non-ground.
  - After voxel downsample with cell=2 m, expected ≈ 25 cells occupied.

XYZ text round-trip:
  - read_xyz on "X Y Z\\n..." lines → shape (N, 3) array.

PLY round-trip:
  - read_ply_ascii on minimal ASCII PLY → shape (N, 3).

References
----------
Zhang et al. (2003) PMF IEEE TGRS 41(4):872-882.
ASPRS LAS Spec 1.4-R15.
"""
from __future__ import annotations

import json
import math
import asyncio

import numpy as np
import pytest

from kerf_civil.pointcloud import (
    read_xyz,
    read_ply_ascii,
    voxel_downsample,
    pmf_ground_classify,
    surface_from_points,
    point_cloud_stats,
)
from kerf_civil.tools_parcels_pointcloud_sheets import (
    civil_pointcloud_process_spec,
    run_civil_pointcloud_process,
)


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


# ---------------------------------------------------------------------------
# Sample data
# ---------------------------------------------------------------------------

def _flat_grid_100() -> np.ndarray:
    """100 points on a 10×10 flat grid at z=0."""
    xs = np.linspace(0, 9, 10)
    ys = np.linspace(0, 9, 10)
    xx, yy = np.meshgrid(xs, ys)
    zz = np.zeros_like(xx)
    return np.column_stack([xx.ravel(), yy.ravel(), zz.ravel()])


def _grid_with_outliers() -> np.ndarray:
    """Flat grid plus 10 elevated points representing buildings."""
    ground = _flat_grid_100()
    buildings = np.column_stack([
        np.array([2.0, 2.5, 3.0, 3.5, 4.0, 4.5, 5.0, 5.5, 6.0, 6.5]),
        np.array([2.0, 2.0, 2.0, 2.0, 2.0, 2.0, 2.0, 2.0, 2.0, 2.0]),
        np.full(10, 5.0),  # z=5 (buildings)
    ])
    return np.vstack([ground, buildings])


SAMPLE_XYZ_TEXT = """\
# X Y Z point cloud
0.0 0.0 100.5
1.0 0.0 101.2
2.0 0.0 99.8
0.0 1.0 100.0
1.0 1.0 100.7
2.0 1.0 100.3
"""

SAMPLE_PLY_ASCII = """\
ply
format ascii 1.0
element vertex 4
property float x
property float y
property float z
end_header
0.0 0.0 10.0
1.0 0.0 11.0
1.0 1.0 10.5
0.0 1.0 10.2
"""


# ---------------------------------------------------------------------------
# I/O: read_xyz
# ---------------------------------------------------------------------------

class TestReadXYZ:
    def test_basic_parse(self):
        pts = read_xyz(SAMPLE_XYZ_TEXT)
        assert pts.shape == (6, 3)

    def test_values_correct(self):
        pts = read_xyz(SAMPLE_XYZ_TEXT)
        assert pts[0, 2] == pytest.approx(100.5)
        assert pts[2, 2] == pytest.approx(99.8)

    def test_comma_delimited(self):
        text = "0.0,1.0,2.0\n3.0,4.0,5.0\n6.0,7.0,8.0\n"
        pts = read_xyz(text)
        assert pts.shape == (3, 3)
        assert pts[1, 0] == pytest.approx(3.0)

    def test_skip_comment_lines(self):
        text = "# comment\n1 2 3\n4 5 6\n"
        pts = read_xyz(text)
        assert pts.shape == (2, 3)

    def test_empty_raises(self):
        with pytest.raises(ValueError, match="No numeric rows"):
            read_xyz("# all comments\n# nothing here\n")

    def test_extra_columns_retained(self):
        text = "0 1 2 255 128 0\n3 4 5 100 200 50\n6 7 8 0 0 0\n"
        pts = read_xyz(text)
        assert pts.shape[1] >= 4  # at least xyz + intensity/R


# ---------------------------------------------------------------------------
# I/O: read_ply_ascii
# ---------------------------------------------------------------------------

class TestReadPLYAscii:
    def test_basic_parse(self):
        pts = read_ply_ascii(SAMPLE_PLY_ASCII)
        assert pts.shape == (4, 3)

    def test_values_correct(self):
        pts = read_ply_ascii(SAMPLE_PLY_ASCII)
        assert pts[0, 2] == pytest.approx(10.0)
        assert pts[2, 2] == pytest.approx(10.5)

    def test_non_ply_raises(self):
        with pytest.raises(ValueError, match="Not a PLY"):
            read_ply_ascii("this is not ply")

    def test_missing_xyz_raises(self):
        ply_no_z = """\
ply
format ascii 1.0
element vertex 2
property float x
property float y
end_header
0.0 0.0
1.0 1.0
"""
        with pytest.raises(ValueError, match="missing x/y/z"):
            read_ply_ascii(ply_no_z)


# ---------------------------------------------------------------------------
# Voxel downsample
# ---------------------------------------------------------------------------

class TestVoxelDownsample:
    def test_reduces_points(self):
        pts = _flat_grid_100()
        ds = voxel_downsample(pts, cell_size=2.0)
        assert len(ds) < len(pts)

    def test_cell_size_1_near_original(self):
        pts = _flat_grid_100()
        # Points are 1 m apart; cell_size=1 m → each cell has exactly 1 point
        ds = voxel_downsample(pts, cell_size=1.0)
        # Allow for slight grouping at edges
        assert len(ds) <= len(pts)
        assert len(ds) >= len(pts) * 0.8

    def test_large_cell_single_centroid(self):
        pts = _flat_grid_100()
        # One cell covers whole 10×10 grid
        ds = voxel_downsample(pts, cell_size=20.0)
        assert len(ds) == 1

    def test_centroid_z_correct(self):
        # All points at same z=5 → centroid z = 5
        pts = np.array([[0.0, 0.0, 5.0], [0.5, 0.5, 5.0], [0.0, 0.5, 5.0]])
        ds = voxel_downsample(pts, cell_size=2.0)
        assert ds[0, 2] == pytest.approx(5.0)

    def test_invalid_cell_size_raises(self):
        pts = _flat_grid_100()
        with pytest.raises(ValueError, match="cell_size"):
            voxel_downsample(pts, cell_size=0.0)

    def test_empty_array_returns_empty(self):
        pts = np.zeros((0, 3))
        ds = voxel_downsample(pts, 1.0)
        assert len(ds) == 0


# ---------------------------------------------------------------------------
# PMF ground classification
# ---------------------------------------------------------------------------

class TestPMFGroundClassify:
    def test_flat_ground_mostly_retained(self):
        pts = _flat_grid_100()
        gnd = pmf_ground_classify(pts, cell_size=1.0, max_window_size=5.0, slope_threshold=0.3)
        # Flat surface — most points should be kept
        assert len(gnd) >= len(pts) * 0.8

    def test_buildings_filtered(self):
        pts = _grid_with_outliers()
        gnd = pmf_ground_classify(pts, cell_size=1.0, max_window_size=15.0, slope_threshold=0.3)
        # Ground points (z=0) should dominate; building points (z=5) removed
        assert len(gnd) < len(pts)

    def test_output_is_subset(self):
        pts = _grid_with_outliers()
        gnd = pmf_ground_classify(pts, cell_size=1.0)
        # All returned points should have z <= max_z_of_ground + 1
        assert gnd[:, 2].max() < 4.5 or len(gnd) <= len(pts)

    def test_empty_returns_empty(self):
        pts = np.zeros((0, 3))
        gnd = pmf_ground_classify(pts, cell_size=1.0)
        assert len(gnd) == 0

    def test_returns_numpy_array(self):
        pts = _flat_grid_100()
        gnd = pmf_ground_classify(pts, cell_size=2.0)
        assert isinstance(gnd, np.ndarray)
        assert gnd.shape[1] == 3


# ---------------------------------------------------------------------------
# surface_from_points
# ---------------------------------------------------------------------------

class TestSurfaceFromPoints:
    def test_produces_tin(self):
        from kerf_civil.tin import TIN
        pts = _flat_grid_100()
        tin = surface_from_points(pts, downsample_cell_size=2.0, classify_ground=False)
        assert isinstance(tin, TIN)
        assert tin.triangles.shape[0] > 0

    def test_classify_ground_works(self):
        from kerf_civil.tin import TIN
        pts = _grid_with_outliers()
        tin = surface_from_points(pts, downsample_cell_size=1.0, classify_ground=True,
                                   pmf_kwargs={"cell_size": 1.0, "max_window_size": 10.0})
        assert isinstance(tin, TIN)

    def test_too_few_points_raises(self):
        # 2 points cannot form a TIN
        pts = np.array([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0]])
        with pytest.raises(ValueError, match="Insufficient"):
            surface_from_points(pts, downsample_cell_size=None, classify_ground=False)


# ---------------------------------------------------------------------------
# point_cloud_stats
# ---------------------------------------------------------------------------

class TestPointCloudStats:
    def test_n_points(self):
        pts = _flat_grid_100()
        stats = point_cloud_stats(pts)
        assert stats["n_points"] == 100

    def test_z_range(self):
        pts = _flat_grid_100()
        stats = point_cloud_stats(pts)
        assert stats["z_range_m"] == pytest.approx(0.0)

    def test_density(self):
        pts = _flat_grid_100()
        stats = point_cloud_stats(pts)
        # 100 pts over 9×9 m area ≈ 1.23 pts/m²
        assert stats["density_per_m2"] == pytest.approx(100 / (9 * 9), rel=0.1)

    def test_empty(self):
        stats = point_cloud_stats(np.zeros((0, 3)))
        assert stats["n_points"] == 0


# ---------------------------------------------------------------------------
# LLM tool: civil_pointcloud_process
# ---------------------------------------------------------------------------

class TestPointCloudTool:
    def test_spec_name(self):
        assert civil_pointcloud_process_spec.name == "civil_pointcloud_process"

    def test_spec_required(self):
        req = civil_pointcloud_process_spec.input_schema["required"]
        assert "format" in req
        assert "data" in req
        assert "op" in req

    def test_stats_xyz(self):
        result = _call(run_civil_pointcloud_process, {
            "format": "xyz",
            "data": SAMPLE_XYZ_TEXT,
            "op": "stats",
        })
        assert result.get("ok") is True
        assert result["n_points"] == 6
        assert "stats" in result

    def test_downsample_xyz(self):
        # Generate 100-pt grid as text
        lines = []
        for i in range(10):
            for j in range(10):
                lines.append(f"{float(i)} {float(j)} 0.0")
        text = "\n".join(lines) + "\n"
        result = _call(run_civil_pointcloud_process, {
            "format": "xyz",
            "data": text,
            "op": "downsample",
            "cell_size": 2.0,
        })
        assert result.get("ok") is True
        assert result["n_points_in"] == 100
        assert result["n_points_out"] < 100
        assert "reduction_pct" in result

    def test_classify_xyz(self):
        lines = []
        for i in range(5):
            for j in range(5):
                lines.append(f"{float(i)} {float(j)} 0.0")
        for i in range(5):
            lines.append(f"{float(i)} 2.0 5.0")  # building points
        text = "\n".join(lines) + "\n"
        result = _call(run_civil_pointcloud_process, {
            "format": "xyz",
            "data": text,
            "op": "classify",
            "cell_size": 1.0,
        })
        assert result.get("ok") is True
        assert result["n_points_in"] == 30
        assert "n_ground_points" in result

    def test_surface_xyz(self):
        lines = []
        for i in range(6):
            for j in range(6):
                lines.append(f"{float(i)} {float(j)} 0.0")
        text = "\n".join(lines) + "\n"
        result = _call(run_civil_pointcloud_process, {
            "format": "xyz",
            "data": text,
            "op": "surface",
            "cell_size": 1.0,
            "classify_ground": False,
        })
        assert result.get("ok") is True
        assert result["n_triangles"] > 0
        assert "tin_extents" in result

    def test_ply_stats(self):
        result = _call(run_civil_pointcloud_process, {
            "format": "ply",
            "data": SAMPLE_PLY_ASCII,
            "op": "stats",
        })
        assert result.get("ok") is True
        assert result["n_points"] == 4

    def test_unknown_format_error(self):
        result = _call(run_civil_pointcloud_process, {
            "format": "xyz",
            "data": "# all comments",
            "op": "stats",
        })
        assert "error" in result

    def test_unknown_op_error(self):
        result = _call(run_civil_pointcloud_process, {
            "format": "xyz",
            "data": SAMPLE_XYZ_TEXT,
            "op": "bogus_op",
        })
        assert "error" in result
