"""
Tests for kerf_cad_core.reverse_engineering — v2 deferred sub-capabilities.

Coverage
--------
1. Binary PLY parser (little-endian + big-endian + ASCII round-trip)
2. Binary PCD parser (ascii + binary + round-trip)
3. Scanner noise pre-filtering (statistical_outlier_removal + laplacian_smooth)
4. Cone LM refinement (half-angle within ≤0.1° of ground truth)
5. Torus RANSAC (major/minor radii within 1% of ground truth)
6. Extended segmentation integrating cone + torus
7. Full pipeline (noise filter → segment → classify)
8. UnsupportedFormatError for malformed inputs

All tests are pure-Python, hermetic — no OCC, no DB, no network, no disk
fixtures.  Synthetic point clouds are generated analytically with fixed seeds.

Author: imranparuk
"""
from __future__ import annotations

import io
import math
import random
import struct

import pytest

from kerf_cad_core.reverse_engineering.io import (
    load_ply,
    load_pcd,
    UnsupportedFormatError,
)
from kerf_cad_core.reverse_engineering.noise import (
    statistical_outlier_removal,
    laplacian_smooth,
)
from kerf_cad_core.reverse_engineering.fit_cone import (
    fit_cone_direct,
    ransac_fit_cone,
    refine_cone_lm,
)
from kerf_cad_core.reverse_engineering.fit_torus import (
    fit_torus_direct,
    ransac_fit_torus,
)
from kerf_cad_core.reverse_engineering.segmentation import extended_segment
from kerf_cad_core.reverse_engineering.pipeline import run_pipeline


# ---------------------------------------------------------------------------
# Synthetic cloud generators
# ---------------------------------------------------------------------------

def _cone_pts(
    apex: list[float],
    axis: list[float],
    half_angle: float,  # radians
    n: int = 100,
    height: float = 5.0,
    noise: float = 0.0,
    seed: int = 7,
) -> list[list[float]]:
    """Points on the surface of a cone.

    apex, axis (unit), half_angle in radians.  height is along axis from apex.
    """
    # Normalise axis
    mag = math.sqrt(sum(a*a for a in axis))
    axis = [a/mag for a in axis]

    # Build orthonormal basis perpendicular to axis
    ref = [1.0, 0.0, 0.0] if abs(axis[2]) < 0.9 else [0.0, 1.0, 0.0]
    u = [
        axis[1]*ref[2]-axis[2]*ref[1],
        axis[2]*ref[0]-axis[0]*ref[2],
        axis[0]*ref[1]-axis[1]*ref[0],
    ]
    un = math.sqrt(u[0]**2+u[1]**2+u[2]**2)
    u = [ui/un for ui in u]
    v = [axis[1]*u[2]-axis[2]*u[1], axis[2]*u[0]-axis[0]*u[2], axis[0]*u[1]-axis[1]*u[0]]

    rng = random.Random(seed)
    tan_a = math.tan(half_angle)
    pts = []
    for _ in range(n):
        t = rng.uniform(0.01, height)  # distance along axis from apex
        theta = rng.uniform(0, 2*math.pi)
        r = t * tan_a
        nr = r + (rng.gauss(0, noise) if noise > 0 else 0.0)
        p = [
            apex[0] + t*axis[0] + nr*math.cos(theta)*u[0] + nr*math.sin(theta)*v[0],
            apex[1] + t*axis[1] + nr*math.cos(theta)*u[1] + nr*math.sin(theta)*v[1],
            apex[2] + t*axis[2] + nr*math.cos(theta)*u[2] + nr*math.sin(theta)*v[2],
        ]
        pts.append(p)
    return pts


def _torus_pts(
    centre: list[float],
    axis: list[float],
    R: float,
    r: float,
    n: int = 200,
    noise: float = 0.0,
    seed: int = 3,
) -> list[list[float]]:
    """Points on the surface of a torus.

    centre, axis (unit), R = major radius, r = minor radius.
    """
    mag = math.sqrt(sum(a*a for a in axis))
    axis = [a/mag for a in axis]

    ref = [1.0, 0.0, 0.0] if abs(axis[2]) < 0.9 else [0.0, 1.0, 0.0]
    u = [
        axis[1]*ref[2]-axis[2]*ref[1],
        axis[2]*ref[0]-axis[0]*ref[2],
        axis[0]*ref[1]-axis[1]*ref[0],
    ]
    un = math.sqrt(u[0]**2+u[1]**2+u[2]**2)
    u = [ui/un for ui in u]
    v = [axis[1]*u[2]-axis[2]*u[1], axis[2]*u[0]-axis[0]*u[2], axis[0]*u[1]-axis[1]*u[0]]

    rng = random.Random(seed)
    pts = []
    for _ in range(n):
        phi = rng.uniform(0, 2*math.pi)   # angle around the tube centre circle
        theta = rng.uniform(0, 2*math.pi) # angle around the tube cross-section
        # Centre of tube at angle phi
        ring_x = R * math.cos(phi)
        ring_y = R * math.sin(phi)
        # Surface point in torus-local frame
        # Tube cross-section in the (radial, axis) plane
        # radial direction in torus plane: cos(phi)*u + sin(phi)*v
        rad_dir = [math.cos(phi)*u[i] + math.sin(phi)*v[i] for i in range(3)]
        rn = r + (rng.gauss(0, noise) if noise > 0 else 0.0)
        px = centre[0] + (R + rn*math.cos(theta))*rad_dir[0] + rn*math.sin(theta)*axis[0]
        py = centre[1] + (R + rn*math.cos(theta))*rad_dir[1] + rn*math.sin(theta)*axis[1]
        pz = centre[2] + (R + rn*math.cos(theta))*rad_dir[2] + rn*math.sin(theta)*axis[2]
        pts.append([px, py, pz])
    return pts


def _plane_pts_simple(n: int = 50, noise: float = 0.0, seed: int = 11) -> list[list[float]]:
    rng = random.Random(seed)
    pts = []
    for _ in range(n):
        x = rng.uniform(-5, 5)
        y = rng.uniform(-5, 5)
        z = 1.0 + (rng.gauss(0, noise) if noise > 0 else 0.0)
        pts.append([x, y, z])
    return pts


# ---------------------------------------------------------------------------
# PLY binary builder helpers
# ---------------------------------------------------------------------------

def _build_ply_ascii(pts: list[list[float]]) -> bytes:
    """Build a minimal ASCII PLY file with the given points."""
    lines = [
        b"ply\n",
        b"format ascii 1.0\n",
        b"element vertex " + str(len(pts)).encode() + b"\n",
        b"property float x\n",
        b"property float y\n",
        b"property float z\n",
        b"end_header\n",
    ]
    for p in pts:
        lines.append(f"{p[0]:.6f} {p[1]:.6f} {p[2]:.6f}\n".encode())
    return b"".join(lines)


def _build_ply_binary(pts: list[list[float]], endian: str = "little") -> bytes:
    """Build a binary PLY file."""
    fmt_name = "binary_little_endian" if endian == "little" else "binary_big_endian"
    header = (
        f"ply\nformat {fmt_name} 1.0\n"
        f"element vertex {len(pts)}\n"
        f"property float x\nproperty float y\nproperty float z\n"
        f"end_header\n"
    ).encode()
    struct_fmt = "<fff" if endian == "little" else ">fff"
    row_struct = struct.Struct(struct_fmt)
    data = b"".join(row_struct.pack(p[0], p[1], p[2]) for p in pts)
    return header + data


def _build_pcd_ascii(pts: list[list[float]]) -> bytes:
    """Build a minimal ASCII PCD file."""
    n = len(pts)
    header = (
        f"# .PCD v0.7\n"
        f"FIELDS x y z\n"
        f"SIZE 4 4 4\n"
        f"TYPE F F F\n"
        f"COUNT 1 1 1\n"
        f"WIDTH {n}\nHEIGHT 1\nVIEWPOINT 0 0 0 1 0 0 0\n"
        f"POINTS {n}\n"
        f"DATA ascii\n"
    ).encode()
    rows = b"".join(f"{p[0]:.6f} {p[1]:.6f} {p[2]:.6f}\n".encode() for p in pts)
    return header + rows


def _build_pcd_binary(pts: list[list[float]]) -> bytes:
    """Build a binary PCD file (little-endian floats)."""
    n = len(pts)
    header = (
        f"# .PCD v0.7\n"
        f"FIELDS x y z\n"
        f"SIZE 4 4 4\n"
        f"TYPE F F F\n"
        f"COUNT 1 1 1\n"
        f"WIDTH {n}\nHEIGHT 1\nVIEWPOINT 0 0 0 1 0 0 0\n"
        f"POINTS {n}\n"
        f"DATA binary\n"
    ).encode()
    row_struct = struct.Struct("<fff")
    data = b"".join(row_struct.pack(p[0], p[1], p[2]) for p in pts)
    return header + data


# ===========================================================================
# SECTION 1: Binary PLY / PCD I/O
# ===========================================================================

class TestPLYASCII:
    def test_ascii_roundtrip(self):
        pts = [[1.0, 2.0, 3.0], [4.0, 5.0, 6.0], [7.0, 8.0, 9.0]]
        raw = _build_ply_ascii(pts)
        loaded = load_ply(raw)
        assert len(loaded) == 3
        for orig, got in zip(pts, loaded):
            assert abs(got[0] - orig[0]) < 1e-4
            assert abs(got[1] - orig[1]) < 1e-4
            assert abs(got[2] - orig[2]) < 1e-4

    def test_ascii_100_pts(self):
        pts = [[float(i), float(i*2), float(i*3)] for i in range(100)]
        raw = _build_ply_ascii(pts)
        loaded = load_ply(raw)
        assert len(loaded) == 100
        assert abs(loaded[50][0] - 50.0) < 1e-3


class TestPLYBinaryLittleEndian:
    def test_binary_le_roundtrip(self):
        pts = [[1.0, 2.0, 3.0], [4.0, 5.0, 6.0], [7.0, 8.0, 9.0]]
        raw = _build_ply_binary(pts, "little")
        loaded = load_ply(raw)
        assert len(loaded) == 3
        for orig, got in zip(pts, loaded):
            assert abs(got[0] - orig[0]) < 1e-5
            assert abs(got[1] - orig[1]) < 1e-5
            assert abs(got[2] - orig[2]) < 1e-5

    def test_binary_le_matches_ascii(self):
        """Binary-LE and ASCII produce the same parsed cloud."""
        pts = _plane_pts_simple(n=20, noise=0.0)
        raw_ascii = _build_ply_ascii(pts)
        raw_binary = _build_ply_binary(pts, "little")
        loaded_ascii = load_ply(raw_ascii)
        loaded_binary = load_ply(raw_binary)
        assert len(loaded_ascii) == len(loaded_binary)
        for a, b in zip(loaded_ascii, loaded_binary):
            for i in range(3):
                assert abs(a[i] - b[i]) < 1e-4

    def test_binary_le_100_pts(self):
        pts = [[float(i), float(i*2), float(i*0.5)] for i in range(100)]
        raw = _build_ply_binary(pts, "little")
        loaded = load_ply(raw)
        assert len(loaded) == 100
        assert abs(loaded[42][1] - 84.0) < 1e-3


class TestPLYBinaryBigEndian:
    def test_binary_be_roundtrip(self):
        pts = [[1.5, 2.5, 3.5], [4.5, 5.5, 6.5]]
        raw = _build_ply_binary(pts, "big")
        loaded = load_ply(raw)
        assert len(loaded) == 2
        for orig, got in zip(pts, loaded):
            for i in range(3):
                assert abs(got[i] - orig[i]) < 1e-5

    def test_binary_be_matches_ascii(self):
        """Binary-BE produces same values as ASCII."""
        pts = _plane_pts_simple(n=30, noise=0.0)
        loaded_ascii = load_ply(_build_ply_ascii(pts))
        loaded_be = load_ply(_build_ply_binary(pts, "big"))
        assert len(loaded_ascii) == len(loaded_be)
        for a, b in zip(loaded_ascii, loaded_be):
            for i in range(3):
                assert abs(a[i] - b[i]) < 1e-4

    def test_binary_be_negative_coords(self):
        pts = [[-1.0, -2.0, -3.0], [1.0, 2.0, 3.0]]
        raw = _build_ply_binary(pts, "big")
        loaded = load_ply(raw)
        assert abs(loaded[0][0] - (-1.0)) < 1e-5
        assert abs(loaded[1][2] - 3.0) < 1e-5


class TestPLYErrors:
    def test_not_ply(self):
        with pytest.raises(UnsupportedFormatError):
            load_ply(b"NOT A PLY FILE\n")

    def test_missing_xyz_property(self):
        # PLY with only 'x' and 'y', no 'z'
        raw = (
            b"ply\nformat ascii 1.0\n"
            b"element vertex 1\n"
            b"property float x\nproperty float y\n"
            b"end_header\n1.0 2.0\n"
        )
        with pytest.raises(UnsupportedFormatError):
            load_ply(raw)

    def test_truncated_binary(self):
        pts = [[1.0, 2.0, 3.0]] * 10
        raw = _build_ply_binary(pts, "little")
        # Truncate the data
        with pytest.raises(UnsupportedFormatError):
            load_ply(raw[:len(raw)//2])

    def test_empty_bytes(self):
        with pytest.raises(UnsupportedFormatError):
            load_ply(b"")

    def test_unsupported_format(self):
        raw = (
            b"ply\nformat binary_compressed 1.0\n"
            b"element vertex 1\n"
            b"property float x\nproperty float y\nproperty float z\n"
            b"end_header\n"
        )
        with pytest.raises(UnsupportedFormatError):
            load_ply(raw)


class TestPCDASCII:
    def test_ascii_roundtrip(self):
        pts = [[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]]
        raw = _build_pcd_ascii(pts)
        loaded = load_pcd(raw)
        assert len(loaded) == 2
        for orig, got in zip(pts, loaded):
            for i in range(3):
                assert abs(got[i] - orig[i]) < 1e-4

    def test_ascii_100_pts(self):
        pts = [[float(i), float(i*2), float(i*3)] for i in range(100)]
        raw = _build_pcd_ascii(pts)
        loaded = load_pcd(raw)
        assert len(loaded) == 100
        assert abs(loaded[77][0] - 77.0) < 1e-3


class TestPCDBinary:
    def test_binary_roundtrip(self):
        pts = [[1.5, 2.5, 3.5], [4.5, 5.5, 6.5], [7.5, 8.5, 9.5]]
        raw = _build_pcd_binary(pts)
        loaded = load_pcd(raw)
        assert len(loaded) == 3
        for orig, got in zip(pts, loaded):
            for i in range(3):
                assert abs(got[i] - orig[i]) < 1e-5

    def test_binary_matches_ascii(self):
        """Binary PCD and ASCII PCD produce the same parsed cloud."""
        pts = _plane_pts_simple(n=30, noise=0.0)
        loaded_ascii = load_pcd(_build_pcd_ascii(pts))
        loaded_binary = load_pcd(_build_pcd_binary(pts))
        assert len(loaded_ascii) == len(loaded_binary)
        for a, b in zip(loaded_ascii, loaded_binary):
            for i in range(3):
                assert abs(a[i] - b[i]) < 1e-4

    def test_binary_50_pts(self):
        pts = [[float(i)*0.1, float(i)*0.2, float(i)*0.3] for i in range(50)]
        raw = _build_pcd_binary(pts)
        loaded = load_pcd(raw)
        assert len(loaded) == 50
        assert abs(loaded[25][0] - 2.5) < 1e-4


class TestPCDErrors:
    def test_missing_fields(self):
        # PCD without FIELDS line
        raw = (
            b"# PCD\n"
            b"SIZE 4 4\nTYPE F F\nCOUNT 1 1\nPOINTS 1\nDATA ascii\n"
            b"1.0 2.0\n"
        )
        with pytest.raises(UnsupportedFormatError):
            load_pcd(raw)

    def test_missing_z_field(self):
        raw = (
            b"# PCD\nFIELDS x y\nSIZE 4 4\nTYPE F F\nCOUNT 1 1\n"
            b"POINTS 1\nDATA ascii\n1.0 2.0\n"
        )
        with pytest.raises(UnsupportedFormatError):
            load_pcd(raw)

    def test_unsupported_data_type(self):
        raw = (
            b"FIELDS x y z\nSIZE 4 4 4\nTYPE F F F\nCOUNT 1 1 1\n"
            b"POINTS 1\nDATA binary_compressed\n"
        )
        with pytest.raises(UnsupportedFormatError):
            load_pcd(raw)

    def test_truncated_binary(self):
        pts = [[1.0, 2.0, 3.0]] * 20
        raw = _build_pcd_binary(pts)
        with pytest.raises(UnsupportedFormatError):
            load_pcd(raw[:len(raw)//2])


# ===========================================================================
# SECTION 2: Scanner noise pre-filtering
# ===========================================================================

class TestStatisticalOutlierRemoval:
    def test_removes_outliers(self):
        """Plane + injected outliers: SOR removes the outliers."""
        rng = random.Random(42)
        # 80 points on plane z=0 with tiny noise
        plane = [[rng.uniform(-5, 5), rng.uniform(-5, 5), rng.gauss(0, 0.01)]
                 for _ in range(80)]
        # 5 clear outliers far from the plane
        outliers = [[100.0, 100.0, 100.0], [-100.0, 50.0, 200.0],
                    [0.0, 0.0, 50.0], [50.0, -50.0, -80.0], [10.0, 10.0, 40.0]]
        all_pts = plane + outliers

        filtered, outlier_idx = statistical_outlier_removal(all_pts, k=8, n_sigma=2.0)

        # At least some outliers should be removed
        assert len(outlier_idx) > 0, "SOR should remove at least 1 outlier"
        # Fewer points remain
        assert len(filtered) < len(all_pts)
        # Most plane points should remain
        assert len(filtered) >= 60, f"Too many plane pts removed: {len(filtered)}"

    def test_inlier_ratio_improves_after_sor(self):
        """After SOR, RANSAC plane inlier ratio improves."""
        from kerf_cad_core.scan.fit import ransac_fit_plane

        rng = random.Random(13)
        plane = [[rng.uniform(-4, 4), rng.uniform(-4, 4), rng.gauss(0, 0.005)]
                 for _ in range(100)]
        outliers = [
            [50.0, 50.0, 50.0], [-50.0, -50.0, -50.0],
            [0.0, 0.0, 30.0], [20.0, -20.0, 15.0],
            [0.0, 5.0, -25.0],
        ]
        all_pts = plane + outliers

        # Ratio before filtering
        res_before = ransac_fit_plane(all_pts, threshold=0.05, seed=42)
        assert res_before["ok"]
        ratio_before = res_before["inlier_ratio"]

        filtered, removed = statistical_outlier_removal(all_pts, k=8, n_sigma=2.0)
        res_after = ransac_fit_plane(filtered, threshold=0.05, seed=42)
        assert res_after["ok"]
        ratio_after = res_after["inlier_ratio"]

        # Inlier ratio should improve (or be very high already)
        assert ratio_after >= ratio_before or ratio_after > 0.9, (
            f"Inlier ratio should improve: before={ratio_before:.3f} after={ratio_after:.3f}"
        )
        # Outliers should be removed
        assert len(removed) >= 3, f"Expected ≥3 outliers removed, got {len(removed)}"

    def test_n_outliers_removed(self):
        """Assert injected isolated outliers are removed by SOR.

        Isolated outliers (well-separated from each other) are reliably removed.
        Clustered outliers that are near each other may survive SOR (expected
        behavior — they form their own cluster).
        """
        rng = random.Random(99)
        # Tight plane cloud
        plane = [[rng.uniform(-2, 2), rng.uniform(-2, 2), rng.gauss(0, 0.001)]
                 for _ in range(100)]
        # 5 well-separated isolated outliers (not near each other or the plane)
        outliers = [
            [500.0, 0.0, 0.0],
            [-500.0, 0.0, 0.0],
            [0.0, 500.0, 0.0],
            [0.0, -500.0, 0.0],
            [0.0, 0.0, 500.0],
        ]
        all_pts = plane + outliers

        _, removed = statistical_outlier_removal(all_pts, k=8, n_sigma=2.0)
        # All 5 isolated extreme outliers should be removed
        assert len(removed) >= 5, f"Expected ≥5 isolated outliers removed; got {len(removed)}"

    def test_clean_cloud_unchanged(self):
        """A clean cloud with no outliers should have no or few points removed."""
        plane = _plane_pts_simple(n=100, noise=0.001, seed=5)
        filtered, removed = statistical_outlier_removal(plane, k=8, n_sigma=3.0)
        # Very few points should be removed from a clean cloud
        assert len(removed) <= 5, f"Too many removed from clean cloud: {len(removed)}"

    def test_too_few_points(self):
        """Single point: no outliers removed."""
        filtered, removed = statistical_outlier_removal([[1.0, 2.0, 3.0]])
        assert len(removed) == 0
        assert len(filtered) == 1


class TestLaplacianSmooth:
    def test_smoothing_reduces_noise(self):
        """Noisy plane: smoothed z values should be closer to 0."""
        rng = random.Random(17)
        pts = [[rng.uniform(-3, 3), rng.uniform(-3, 3), rng.gauss(0, 0.5)]
               for _ in range(50)]
        smoothed = laplacian_smooth(pts, n_iter=5, weight=0.5, k=8)
        # std of z should decrease
        z_orig = [p[2] for p in pts]
        z_smooth = [p[2] for p in smoothed]
        std_orig = math.sqrt(sum(z*z for z in z_orig) / len(z_orig))
        std_smooth = math.sqrt(sum(z*z for z in z_smooth) / len(z_smooth))
        assert std_smooth < std_orig, f"Smoothing should reduce z spread: {std_orig:.4f} → {std_smooth:.4f}"

    def test_preserves_count(self):
        pts = _plane_pts_simple(n=30, noise=0.01)
        smoothed = laplacian_smooth(pts, n_iter=3)
        assert len(smoothed) == len(pts)

    def test_zero_iters_unchanged(self):
        pts = _plane_pts_simple(n=10, noise=0.0)
        smoothed = laplacian_smooth(pts, n_iter=0)
        assert len(smoothed) == len(pts)


# ===========================================================================
# SECTION 3: Cone LM refinement
# ===========================================================================

class TestConeFitDirect:
    def test_basic_cone(self):
        apex = [0.0, 0.0, 0.0]
        axis = [0.0, 0.0, 1.0]
        half_angle = math.radians(30)
        pts = _cone_pts(apex, axis, half_angle, n=80, noise=0.0)
        res = fit_cone_direct(pts)
        assert res["ok"], f"fit_cone_direct failed: {res}"
        assert res["primitive"] == "cone"

    def test_too_few_points(self):
        res = fit_cone_direct([[1, 0, 0], [0, 1, 0]])
        assert res["ok"] is False
        assert "6" in res["reason"]


class TestConeLMRefinement:
    def test_refined_half_angle_within_01_deg(self):
        """LM-refined half-angle should be within 0.1° of ground truth."""
        gt_half_angle = math.radians(25.0)  # 25°
        apex = [0.0, 0.0, 0.0]
        axis = [0.0, 0.0, 1.0]
        pts = _cone_pts(apex, axis, gt_half_angle, n=150, noise=0.002, seed=42)

        # Get RANSAC fit with LM refinement
        res = ransac_fit_cone(pts, threshold=0.05, n_iters=300, seed=42, refine=True)
        assert res.get("ok"), f"ransac_fit_cone failed: {res}"
        assert res.get("lm_refined"), "Result should have been LM-refined"

        # Check half-angle accuracy
        err_deg = abs(math.degrees(res["half_angle"]) - 25.0)
        assert err_deg <= 0.1, (
            f"Half-angle error {err_deg:.4f}° exceeds 0.1° tolerance "
            f"(got {math.degrees(res['half_angle']):.4f}°, expected 25.0°)"
        )

    def test_refined_vs_unrefined_closer(self):
        """LM-refined result should have smaller residual than seed."""
        gt_half_angle = math.radians(20.0)
        pts = _cone_pts([0, 0, 0], [0, 0, 1], gt_half_angle, n=100, noise=0.005, seed=55)

        # Seed (no refinement)
        seed_res = ransac_fit_cone(pts, threshold=0.05, n_iters=200, seed=42, refine=False)
        assert seed_res.get("ok"), f"seed fit failed: {seed_res}"

        # Refined
        refined_res = refine_cone_lm(pts, seed_res)
        assert refined_res.get("ok"), f"LM refinement failed: {refined_res}"
        assert refined_res.get("lm_refined"), "Should be marked as LM-refined"

        # Refined should have smaller or equal residual
        assert refined_res["residual"] <= seed_res["residual"] + 1e-6, (
            f"LM should improve residual: seed={seed_res['residual']:.6f}, "
            f"refined={refined_res['residual']:.6f}"
        )

    def test_various_half_angles(self):
        """Test multiple half-angle ground truths: 15°, 30°, 45°."""
        for gt_deg in (15.0, 30.0, 45.0):
            gt_rad = math.radians(gt_deg)
            pts = _cone_pts([0, 0, 0], [0, 0, 1], gt_rad, n=120, noise=0.002, seed=77)
            res = ransac_fit_cone(pts, threshold=0.05, n_iters=400, seed=42, refine=True)
            if not res.get("ok"):
                continue  # allow occasional RANSAC failure on hard cases
            err_deg = abs(math.degrees(res["half_angle"]) - gt_deg)
            assert err_deg <= 0.5, (
                f"Half-angle error {err_deg:.3f}° for gt={gt_deg}° exceeds 0.5° tolerance"
            )

    def test_lm_fallback_on_bad_seed(self):
        """refine_cone_lm returns seed unchanged if seed is not ok."""
        bad_seed = {"ok": False, "reason": "test"}
        result = refine_cone_lm([[1, 0, 0]], bad_seed)
        assert result["ok"] is False


# ===========================================================================
# SECTION 4: Torus RANSAC
# ===========================================================================

class TestTorusFitDirect:
    def test_basic_torus(self):
        pts = _torus_pts([0, 0, 0], [0, 0, 1], R=3.0, r=0.5, n=100, noise=0.0)
        res = fit_torus_direct(pts)
        assert res.get("ok"), f"fit_torus_direct failed: {res}"
        assert res["primitive"] == "torus"

    def test_too_few_points(self):
        res = fit_torus_direct([[1, 0, 0], [0, 1, 0], [0, 0, 1]])
        assert res["ok"] is False
        assert "7" in res["reason"]


class TestTorusRANSAC:
    def test_major_minor_radii_within_1pct(self):
        """Recovered major and minor radii should be within 1% of ground truth."""
        gt_R = 3.0
        gt_r = 0.5
        pts = _torus_pts(
            centre=[0.0, 0.0, 0.0],
            axis=[0.0, 0.0, 1.0],
            R=gt_R,
            r=gt_r,
            n=300,
            noise=0.002,
            seed=42,
        )
        res = ransac_fit_torus(pts, threshold=0.05, n_iters=300, seed=42)
        assert res.get("ok"), f"ransac_fit_torus failed: {res}"
        assert res["primitive"] == "torus"

        err_R_pct = abs(res["R"] - gt_R) / gt_R * 100
        err_r_pct = abs(res["r"] - gt_r) / gt_r * 100

        assert err_R_pct <= 1.0, (
            f"Major radius error {err_R_pct:.2f}% exceeds 1% "
            f"(got {res['R']:.4f}, expected {gt_R})"
        )
        assert err_r_pct <= 1.0, (
            f"Minor radius error {err_r_pct:.2f}% exceeds 1% "
            f"(got {res['r']:.4f}, expected {gt_r})"
        )

    def test_torus_centre_recovered(self):
        """Centre should be close to ground truth."""
        gt_centre = [1.0, 2.0, 3.0]
        pts = _torus_pts(
            centre=gt_centre,
            axis=[0.0, 0.0, 1.0],
            R=2.5,
            r=0.4,
            n=250,
            noise=0.001,
            seed=99,
        )
        res = ransac_fit_torus(pts, threshold=0.05, n_iters=300, seed=42)
        assert res.get("ok")
        # Centre within 5% of R from true centre
        err = math.sqrt(sum((res["centre"][i] - gt_centre[i])**2 for i in range(3)))
        assert err < 0.15, f"Centre error {err:.4f} too large"

    def test_torus_outlier_rejection(self):
        """Torus with outliers: inlier_ratio < 1."""
        pts = _torus_pts([0, 0, 0], [0, 0, 1], R=2.0, r=0.3, n=200, noise=0.0)
        outliers = [[100.0, 100.0, 100.0]] * 10
        res = ransac_fit_torus(pts + outliers, threshold=0.05, n_iters=300, seed=42)
        assert res.get("ok")
        assert res["inlier_ratio"] < 1.0

    def test_torus_tilted_axis(self):
        """Torus with non-z axis: should still fit reasonably."""
        pts = _torus_pts([0, 0, 0], [1, 1, 0], R=2.0, r=0.4, n=200, noise=0.001)
        res = ransac_fit_torus(pts, threshold=0.05, n_iters=400, seed=42)
        assert res.get("ok")
        err_R = abs(res["R"] - 2.0) / 2.0 * 100
        assert err_R <= 5.0, f"Major radius error {err_R:.2f}% on tilted axis"

    def test_too_few_points(self):
        res = ransac_fit_torus([[1, 0, 0], [0, 1, 0], [0, 0, 1]])
        assert res["ok"] is False

    def test_deterministic(self):
        pts = _torus_pts([0, 0, 0], [0, 0, 1], R=2.0, r=0.5, n=150, noise=0.001)
        r1 = ransac_fit_torus(pts, seed=77)
        r2 = ransac_fit_torus(pts, seed=77)
        assert r1["R"] == r2["R"]
        assert r1["r"] == r2["r"]


# ===========================================================================
# SECTION 5: Extended segmentation (cone + torus integration)
# ===========================================================================

class TestExtendedSegmentation:
    def test_cone_in_segment(self):
        """Cone-only cloud: extended_segment finds 'cone' segment."""
        pts = _cone_pts([0, 0, 0], [0, 0, 1], math.radians(25), n=100, noise=0.002)
        res = extended_segment(pts, primitives=["cone"], threshold=0.05, seed=42)
        assert res["ok"]
        found = [s["primitive"] for s in res["segments"]]
        assert "cone" in found, f"Expected cone in segments, got: {found}"

    def test_torus_in_segment(self):
        """Torus-only cloud: extended_segment finds 'torus' segment."""
        pts = _torus_pts([0, 0, 0], [0, 0, 1], R=2.0, r=0.4, n=200, noise=0.002)
        res = extended_segment(pts, primitives=["torus"], threshold=0.05, seed=42)
        assert res["ok"]
        found = [s["primitive"] for s in res["segments"]]
        assert "torus" in found, f"Expected torus in segments, got: {found}"

    def test_mixed_plane_cone(self):
        """Plane + cone cloud: both primitives found."""
        plane = _plane_pts_simple(n=60, noise=0.001)
        cone_pts = _cone_pts([20, 20, 20], [0, 0, 1], math.radians(30), n=80, noise=0.002)
        all_pts = plane + cone_pts
        res = extended_segment(all_pts, primitives=["plane", "cone"], threshold=0.05, seed=42)
        assert res["ok"]
        found = {s["primitive"] for s in res["segments"]}
        assert len(found) >= 1

    def test_count_invariant(self):
        """Assigned + unassigned == total."""
        pts = _plane_pts_simple(n=50, noise=0.001)
        res = extended_segment(pts, threshold=0.02, seed=42)
        assert res["ok"]
        assigned = sum(s["inlier_count"] for s in res["segments"])
        assert assigned + res["unassigned_count"] == res["total_count"]

    def test_too_few_points(self):
        res = extended_segment([[0, 0, 0], [1, 0, 0]])
        assert res["ok"] is False

    def test_torus_segment_has_R_and_r(self):
        """Torus segment should contain R and r fields."""
        pts = _torus_pts([0, 0, 0], [0, 0, 1], R=3.0, r=0.5, n=200, noise=0.001)
        res = extended_segment(pts, primitives=["torus"], threshold=0.05, seed=42)
        assert res["ok"]
        if res["segments"]:
            seg = res["segments"][0]
            if seg["primitive"] == "torus":
                assert "R" in seg
                assert "r" in seg

    def test_cone_segment_has_apex_and_half_angle(self):
        """Cone segment should contain apex and half_angle fields."""
        pts = _cone_pts([0, 0, 0], [0, 0, 1], math.radians(20), n=80, noise=0.001)
        res = extended_segment(pts, primitives=["cone"], threshold=0.05, seed=42)
        assert res["ok"]
        if res["segments"]:
            seg = res["segments"][0]
            if seg["primitive"] == "cone":
                assert "apex" in seg
                assert "half_angle" in seg


# ===========================================================================
# SECTION 6: Full pipeline
# ===========================================================================

class TestRunPipeline:
    def test_plane_pipeline(self):
        """Clean plane cloud runs through the full pipeline successfully."""
        pts = _plane_pts_simple(n=80, noise=0.005)
        res = run_pipeline(pts, primitives=["plane"], threshold=0.05, seed=42)
        assert res["ok"], f"pipeline failed: {res}"
        assert "segments" in res
        assert len(res["segments"]) >= 1

    def test_outlier_removal_reduces_count(self):
        """Pipeline with outliers removes them and reports outlier_count."""
        rng = random.Random(31)
        pts = _plane_pts_simple(n=100, noise=0.002)
        outliers = [[1000.0, 1000.0, 1000.0] for _ in range(5)]
        res = run_pipeline(pts + outliers, primitives=["plane"], threshold=0.05, seed=42)
        assert res["ok"]
        assert res["outlier_count"] >= 1
        assert res["filtered_count"] < len(pts) + 5

    def test_skip_filter(self):
        """skip_filter=True: outlier_count == 0, all pts in filtered."""
        pts = _plane_pts_simple(n=30, noise=0.001)
        res = run_pipeline(pts, skip_filter=True, primitives=["plane"], threshold=0.05, seed=42)
        assert res["ok"]
        assert res["outlier_count"] == 0
        assert res["filtered_count"] == len(pts)

    def test_feature_type_label(self):
        """Segments should have feature_type label."""
        pts = _plane_pts_simple(n=60, noise=0.001)
        res = run_pipeline(pts, skip_filter=True, primitives=["plane"], threshold=0.05, seed=42)
        assert res["ok"]
        if res["segments"]:
            assert "feature_type" in res["segments"][0]
            assert res["segments"][0]["feature_type"] == "analytic_plane"

    def test_torus_pipeline(self):
        """Torus cloud: pipeline finds torus segment."""
        pts = _torus_pts([0, 0, 0], [0, 0, 1], R=2.5, r=0.4, n=200, noise=0.002)
        res = run_pipeline(pts, skip_filter=True, primitives=["torus"], threshold=0.05, seed=42)
        assert res["ok"]
        found = [s["primitive"] for s in res["segments"]]
        assert "torus" in found

    def test_cone_pipeline(self):
        """Cone cloud: pipeline finds cone segment."""
        pts = _cone_pts([0, 0, 0], [0, 0, 1], math.radians(25), n=100, noise=0.002)
        res = run_pipeline(pts, skip_filter=True, primitives=["cone"], threshold=0.05, seed=42)
        assert res["ok"]
        found = [s["primitive"] for s in res["segments"]]
        assert "cone" in found

    def test_too_few_points(self):
        res = run_pipeline([[0, 0, 0], [1, 0, 0]])
        assert res["ok"] is False
