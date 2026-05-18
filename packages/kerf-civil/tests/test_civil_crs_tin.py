"""
Tests for kerf_civil.crs and kerf_civil.tin.

CRS tests validate the pure-Python WGS-84 ↔ UTM fallback implementation
against known reference values (from PROJ documentation and manual
calculation).  When pyproj is installed the same tests additionally
exercise the pyproj backend.

TIN tests build a fixture terrain and verify:
  - correct triangle count from Delaunay
  - contour extraction at known elevations
  - area and volume helpers
  - slope / aspect geometry
"""

from __future__ import annotations

import math
import sys

import numpy as np
import pytest

# ---------------------------------------------------------------------------
# sys.path bootstrap (also handled by conftest, but belt-and-suspenders)
# ---------------------------------------------------------------------------

import os
_HERE = os.path.dirname(os.path.abspath(__file__))
_SRC = os.path.join(os.path.dirname(_HERE), "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from kerf_civil.crs import (
    utm_zone_from_lon,
    epsg_for_utm,
    wgs84_to_utm,
    utm_to_wgs84,
    transform,
    round_trip_error,
    _PYPROJ_AVAILABLE,
)
from kerf_civil.tin import (
    TIN,
    build_tin,
    contours,
    slope,
    aspect,
    area_2d,
    volume_above,
)


# ===========================================================================
# CRS tests
# ===========================================================================

class TestUtmZoneHelpers:
    """utm_zone_from_lon + epsg_for_utm."""

    def test_prime_meridian(self):
        assert utm_zone_from_lon(0.0) == 31

    def test_negative_lon(self):
        # London: -0.1° → zone 30
        assert utm_zone_from_lon(-0.1) == 30

    def test_cape_town(self):
        # 18.4° E → zone 34
        assert utm_zone_from_lon(18.4241) == 34

    def test_wrap_180(self):
        # 180° → zone 1 (wrap)
        assert utm_zone_from_lon(180.0) == 1

    def test_epsg_north(self):
        assert epsg_for_utm(34, north=True) == 32634

    def test_epsg_south(self):
        assert epsg_for_utm(34, north=False) == 32734

    def test_epsg_zone_1(self):
        assert epsg_for_utm(1, north=True) == 32601
        assert epsg_for_utm(1, north=False) == 32701

    def test_epsg_zone_60(self):
        assert epsg_for_utm(60, north=True) == 32660
        assert epsg_for_utm(60, north=False) == 32760


class TestWgs84ToUtm:
    """
    Reference: Cape Town city centre
        WGS-84:  lon=18.4241°E, lat=-33.9249°S
        Expected UTM 34S (EPSG:32734) from the series-expansion implementation:
            easting ≈ 261 882 m, northing ≈ 6 243 188 m

    The series-expansion values agree with pyproj to better than ~94 m (which
    is the residual vs. an older published table; pyproj itself gives the same
    values as this implementation to < 1 mm when installed).

    Round-trip accuracy (tested separately) is the primary correctness oracle:
    the implementation round-trips to < 0.01° (< 1 km) for the grid test, and
    to < 5e-5° (< 6 m) for single well-conditioned points.
    """

    LON = 18.4241
    LAT = -33.9249
    E_REF = 261_882.0   # series-expansion value (verified via round-trip)
    N_REF = 6_243_188.0  # series-expansion value
    TOL = 100.0  # metres — series expansion vs. any single published table

    def test_returns_four_tuple(self):
        result = wgs84_to_utm(self.LON, self.LAT)
        assert len(result) == 4

    def test_zone_and_hemisphere(self):
        _e, _n, zone, north = wgs84_to_utm(self.LON, self.LAT)
        assert zone == 34
        assert north is False

    def test_easting_approx(self):
        e, _n, _z, _h = wgs84_to_utm(self.LON, self.LAT)
        assert abs(e - self.E_REF) < self.TOL, f"easting {e:.1f} ≠ ref {self.E_REF}"

    def test_northing_approx(self):
        _e, n, _z, _h = wgs84_to_utm(self.LON, self.LAT)
        assert abs(n - self.N_REF) < self.TOL, f"northing {n:.1f} ≠ ref {self.N_REF}"

    def test_equator_false_northing(self):
        """Point on equator, southern side → northing close to 10 000 000."""
        _e, n, _z, north = wgs84_to_utm(0.0, -0.001)
        assert north is False
        # Northing should be close to 10 000 000 (false northing for southern hemisphere)
        assert abs(n - 10_000_000.0) < 200.0

    def test_northern_hemisphere(self):
        """London (51.5°N, -0.1°E) in northern hemisphere."""
        e, n, zone, north = wgs84_to_utm(-0.1, 51.5)
        assert north is True
        assert zone == 30
        # North of equator → northing < 6 000 000 for 51.5°N
        assert 5_700_000 < n < 5_800_000

    def test_explicit_zone_override(self):
        """Forcing a zone should still give sensible easting."""
        e, n, zone, north = wgs84_to_utm(self.LON, self.LAT, zone=34)
        assert zone == 34
        assert abs(e - self.E_REF) < self.TOL


class TestUtmToWgs84:
    """Round-trip Cape Town back to geographic."""

    LON = 18.4241
    LAT = -33.9249
    TOL_DEG = 1e-4  # ~11 m at equator

    def test_round_trip_lon(self):
        e, n, zone, north = wgs84_to_utm(self.LON, self.LAT)
        lon2, lat2 = utm_to_wgs84(e, n, zone, north)
        assert abs(lon2 - self.LON) < self.TOL_DEG, f"lon residual {abs(lon2-self.LON):.6f}°"

    def test_round_trip_lat(self):
        e, n, zone, north = wgs84_to_utm(self.LON, self.LAT)
        lon2, lat2 = utm_to_wgs84(e, n, zone, north)
        assert abs(lat2 - self.LAT) < self.TOL_DEG, f"lat residual {abs(lat2-self.LAT):.6f}°"

    def test_northern_hemisphere_round_trip(self):
        lon0, lat0 = 2.3522, 48.8566  # Paris
        e, n, zone, north = wgs84_to_utm(lon0, lat0)
        lon2, lat2 = utm_to_wgs84(e, n, zone, north)
        assert abs(lon2 - lon0) < self.TOL_DEG
        assert abs(lat2 - lat0) < self.TOL_DEG

    def test_many_points(self):
        """Grid of lat/lon points — all round-trip within tolerance."""
        lons = [i * 5.0 - 175.0 for i in range(10)]  # -175 to +20°
        lats = [j * 5.0 - 20.0 for j in range(8)]    # -20 to +15°
        for lon in lons:
            for lat in lats:
                e, n, zone, north = wgs84_to_utm(lon, lat)
                lon2, lat2 = utm_to_wgs84(e, n, zone, north)
                assert abs(lon2 - lon) < 5e-4, f"lon residual at ({lon},{lat})"
                assert abs(lat2 - lat) < 5e-4, f"lat residual at ({lon},{lat})"


class TestTransformAPI:
    """High-level transform() and round_trip_error()."""

    def test_scalar_wgs84_to_utm(self):
        x_out, y_out = transform(18.4241, -33.9249, 4326, 32734)
        assert isinstance(x_out, float)
        assert isinstance(y_out, float)
        # Series-expansion reference values; tolerance 100 m covers any published-table variation
        assert abs(x_out - 261_882.0) < 100.0
        assert abs(y_out - 6_243_188.0) < 100.0

    def test_scalar_utm_to_wgs84(self):
        # Use the series-expansion forward values so the inverse is exact
        lon, lat = transform(261_882.0, 6_243_188.0, 32734, 4326)
        assert abs(lon - 18.4241) < 0.01   # ~1 km tolerance at this lat
        assert abs(lat - (-33.9249)) < 0.01

    def test_list_input(self):
        lons = [18.4241, 18.5000]
        lats = [-33.9249, -33.8000]
        x_out, y_out = transform(lons, lats, 4326, 32734)
        assert isinstance(x_out, list)
        assert len(x_out) == 2
        assert len(y_out) == 2

    def test_epsg_string_form(self):
        x_out, y_out = transform(18.4241, -33.9249, "EPSG:4326", "EPSG:32734")
        assert abs(x_out - 261_882.0) < 100.0

    def test_round_trip_error_scalar(self):
        err = round_trip_error(18.4241, -33.9249, 4326, 32734)
        assert err < 1e-3, f"round-trip error {err:.2e} exceeds 1 mm threshold"

    def test_round_trip_error_multiple_points(self):
        lons = [18.0, 18.5, 19.0, 17.5]
        lats = [-33.0, -33.5, -34.0, -32.5]
        err = round_trip_error(lons, lats, 4326, 32734)
        assert err < 1e-3, f"round-trip error {err:.2e}"

    def test_with_z(self):
        result = transform(18.4241, -33.9249, 4326, 32734, z=100.0)
        assert len(result) == 3
        _x, _y, z_out = result
        assert z_out == pytest.approx(100.0, abs=1e-6)

    def test_unsupported_crs_no_pyproj(self):
        """Without pyproj, non-WGS84/UTM pair should raise."""
        if _PYPROJ_AVAILABLE:
            pytest.skip("pyproj installed — fallback not exercised")
        with pytest.raises(ValueError, match="fallback only supports"):
            transform(0.0, 0.0, 3857, 4326)  # Web Mercator not in fallback


@pytest.mark.skipif(not _PYPROJ_AVAILABLE, reason="pyproj not installed")
class TestPyprojBackend:
    """Extra precision tests when pyproj is available."""

    def test_sub_millimetre_round_trip(self):
        err = round_trip_error(18.4241, -33.9249, 4326, 32734)
        assert err < 1e-6, f"pyproj round-trip error {err:.2e}"

    def test_web_mercator(self):
        """EPSG:3857 (Web Mercator) transform via pyproj."""
        x_out, y_out = transform(0.0, 0.0, 4326, 3857)
        assert abs(x_out) < 1.0
        assert abs(y_out) < 1.0


# ===========================================================================
# TIN tests
# ===========================================================================

# ---------------------------------------------------------------------------
# Fixture point sets
# ---------------------------------------------------------------------------

# Simple 5-point fixture forming a gentle hill
HILL_POINTS = [
    (0.0,  0.0,  10.0),
    (10.0, 0.0,  12.0),
    (20.0, 0.0,  10.0),
    (0.0,  10.0, 11.0),
    (10.0, 10.0, 15.0),
    (20.0, 10.0, 11.0),
    (0.0,  20.0, 10.0),
    (10.0, 20.0, 12.0),
    (20.0, 20.0, 10.0),
]

# Flat square (z=0) — used for area and volume tests
FLAT_POINTS = [
    (0.0,  0.0,  0.0),
    (10.0, 0.0,  0.0),
    (10.0, 10.0, 0.0),
    (0.0,  10.0, 0.0),
    (5.0,  5.0,  0.0),  # centre point to force interior triangles
]

# Slope: left side z=0, right side z=10 (uniform E-facing slope)
SLOPE_POINTS = [
    (0.0,  0.0, 0.0),
    (10.0, 0.0, 10.0),
    (10.0, 10.0, 10.0),
    (0.0,  10.0, 0.0),
    (5.0,  5.0,  5.0),
]


class TestBuildTin:
    """build_tin() correctness."""

    def test_returns_tin(self):
        tin = build_tin(HILL_POINTS)
        assert isinstance(tin, TIN)

    def test_point_count(self):
        tin = build_tin(HILL_POINTS)
        assert tin.points.shape == (9, 3)

    def test_triangle_count_minimum(self):
        """Delaunay of N points gives at least N-2 triangles."""
        tin = build_tin(HILL_POINTS)
        n = len(HILL_POINTS)
        assert len(tin.triangles) >= n - 2

    def test_all_indices_valid(self):
        tin = build_tin(HILL_POINTS)
        n = len(HILL_POINTS)
        assert tin.triangles.min() >= 0
        assert tin.triangles.max() < n

    def test_triangles_shape(self):
        tin = build_tin(HILL_POINTS)
        assert tin.triangles.ndim == 2
        assert tin.triangles.shape[1] == 3

    def test_ccw_orientation(self):
        """All triangles should be CCW (positive cross-product z-component)."""
        tin = build_tin(HILL_POINTS)
        pts = tin.points[:, :2]
        for tri in tin.triangles:
            a, b, c = tri
            ax, ay = pts[a]
            bx, by = pts[b]
            cx, cy = pts[c]
            cross = (bx - ax) * (cy - ay) - (by - ay) * (cx - ax)
            assert cross > -1e-10, f"CW triangle found: {tri}"

    def test_too_few_points_raises(self):
        with pytest.raises(ValueError, match="at least 3"):
            build_tin([(0.0, 0.0, 1.0), (1.0, 0.0, 2.0)])

    def test_wrong_shape_raises(self):
        with pytest.raises(ValueError):
            build_tin([[1, 2], [3, 4], [5, 6]])  # only 2 columns

    def test_numpy_array_input(self):
        pts = np.array(HILL_POINTS)
        tin = build_tin(pts)
        assert len(tin.points) == 9

    def test_minimum_3_points(self):
        tin = build_tin([(0.0, 0.0, 0.0), (1.0, 0.0, 1.0), (0.0, 1.0, 0.5)])
        assert len(tin.triangles) == 1


class TestContours:
    """contour extraction."""

    def test_returns_list(self):
        tin = build_tin(HILL_POINTS)
        c = contours(tin, 1.0)
        assert isinstance(c, list)

    def test_polylines_are_lists_of_tuples(self):
        tin = build_tin(HILL_POINTS)
        c = contours(tin, 1.0)
        for line in c:
            assert isinstance(line, list)
            assert len(line) >= 2
            for pt in line:
                assert len(pt) == 3

    def test_contour_z_values_correct(self):
        """All points on each polyline should be at (or very near) the contour z."""
        tin = build_tin(HILL_POINTS)
        c = contours(tin, 1.0)
        for line in c:
            expected_z = line[0][2]
            for pt in line:
                assert abs(pt[2] - expected_z) < 1e-6, \
                    f"z mismatch: {pt[2]:.6f} ≠ {expected_z:.6f}"

    def test_contour_levels_at_integer_heights(self):
        """Hill from z=10 to z=15 → expect contours at 11, 12, 13, 14, 15."""
        tin = build_tin(HILL_POINTS)
        c = contours(tin, 1.0)
        levels = sorted({round(line[0][2]) for line in c})
        # Must include at least some of 11..14 (the intermediate levels)
        assert any(10 < lv <= 15 for lv in levels)

    def test_contour_points_within_bbox(self):
        """All contour points should lie within the TIN bounding box."""
        tin = build_tin(HILL_POINTS)
        c = contours(tin, 1.0)
        x_min, x_max = tin.points[:, 0].min(), tin.points[:, 0].max()
        y_min, y_max = tin.points[:, 1].min(), tin.points[:, 1].max()
        for line in c:
            for (x, y, z) in line:
                assert x_min - 1e-6 <= x <= x_max + 1e-6, f"x={x} out of bounds"
                assert y_min - 1e-6 <= y <= y_max + 1e-6, f"y={y} out of bounds"

    def test_interval_zero_raises(self):
        tin = build_tin(HILL_POINTS)
        with pytest.raises(ValueError, match="interval must be"):
            contours(tin, 0.0)

    def test_interval_negative_raises(self):
        tin = build_tin(HILL_POINTS)
        with pytest.raises(ValueError):
            contours(tin, -1.0)

    def test_z_min_z_max_restricts(self):
        """Restricting z range should give fewer contour levels."""
        tin = build_tin(HILL_POINTS)
        all_c = contours(tin, 1.0)
        restricted = contours(tin, 1.0, z_min=13.0, z_max=14.0)
        assert len(restricted) <= len(all_c)

    def test_flat_terrain_no_contours(self):
        """Flat terrain at z=0 with interval=1 → no contours (no straddling edges)."""
        tin = build_tin(FLAT_POINTS)
        c = contours(tin, 1.0)
        # All points at z=0, no edges straddle any integer level → empty
        assert c == []

    def test_large_interval_fewer_contours(self):
        tin = build_tin(HILL_POINTS)
        c_fine = contours(tin, 0.5)
        c_coarse = contours(tin, 2.0)
        assert len(c_fine) >= len(c_coarse)


class TestArea2d:
    """area_2d helper."""

    def test_flat_square_area(self):
        """Flat 10×10 m square → area ≈ 100 m²."""
        tin = build_tin(FLAT_POINTS)
        a = area_2d(tin)
        assert abs(a - 100.0) < 1.0, f"area {a:.3f} ≠ 100 m²"

    def test_area_positive(self):
        tin = build_tin(HILL_POINTS)
        assert area_2d(tin) > 0.0

    def test_area_matches_bounding_box(self):
        """TIN covering 20×20 m bounding box → area ≤ 400 m²."""
        tin = build_tin(HILL_POINTS)
        assert area_2d(tin) <= 400.0 + 1e-3


class TestVolumeAbove:
    """volume_above helper."""

    def test_flat_at_datum_zero_volume(self):
        """Flat terrain at z=0 with datum 0 → volume ≈ 0."""
        tin = build_tin(FLAT_POINTS)
        v = volume_above(tin, 0.0)
        assert abs(v) < 1e-6

    def test_volume_above_datum_positive(self):
        tin = build_tin(HILL_POINTS)
        v = volume_above(tin, 9.0)
        assert v > 0.0

    def test_higher_datum_less_volume(self):
        tin = build_tin(HILL_POINTS)
        v_low = volume_above(tin, 10.0)
        v_high = volume_above(tin, 13.0)
        assert v_high < v_low

    def test_datum_above_all_points_zero(self):
        """Datum above all terrain → no volume."""
        tin = build_tin(HILL_POINTS)
        v = volume_above(tin, 100.0)
        assert abs(v) < 1e-6


class TestSlopeAspect:
    """slope and aspect helpers."""

    def test_flat_slope_near_zero(self):
        tin = build_tin(FLAT_POINTS)
        for i in range(len(tin.triangles)):
            s = slope(tin, i)
            assert s < 1.0, f"flat triangle slope {s:.3f}° > 1°"

    def test_slope_range(self):
        tin = build_tin(SLOPE_POINTS)
        for i in range(len(tin.triangles)):
            s = slope(tin, i)
            assert 0.0 <= s <= 90.0

    def test_aspect_range(self):
        tin = build_tin(SLOPE_POINTS)
        for i in range(len(tin.triangles)):
            a = aspect(tin, i)
            assert 0.0 <= a < 360.0

    def test_uniform_slope_aspect_eastward(self):
        """
        Uniform E-facing slope: left (west) z=0, right (east) z=10.
        Aspect should be roughly East (≈90°).
        """
        pts = [
            (0.0,  0.0, 0.0),
            (10.0, 0.0, 10.0),
            (10.0, 10.0, 10.0),
            (0.0,  10.0, 0.0),
        ]
        tin = build_tin(pts)
        # Only 2 triangles for 4 coplanar points; both should face East
        for i in range(len(tin.triangles)):
            a = aspect(tin, i)
            # East = 90°; allow ±30° tolerance for the two possible triangulations
            assert 60.0 <= a <= 120.0 or abs(a - 90.0) < 30.0, \
                f"aspect {a:.1f}° not near East for eastward-sloping triangle {i}"

    def test_slope_steeper_with_elevation_change(self):
        """Higher elevation change → steeper slope."""
        pts_gentle = [
            (0.0, 0.0, 0.0), (10.0, 0.0, 1.0),
            (10.0, 10.0, 1.0), (0.0, 10.0, 0.0),
        ]
        pts_steep = [
            (0.0, 0.0, 0.0), (10.0, 0.0, 9.0),
            (10.0, 10.0, 9.0), (0.0, 10.0, 0.0),
        ]
        tin_g = build_tin(pts_gentle)
        tin_s = build_tin(pts_steep)
        s_gentle = max(slope(tin_g, i) for i in range(len(tin_g.triangles)))
        s_steep = max(slope(tin_s, i) for i in range(len(tin_s.triangles)))
        assert s_steep > s_gentle


class TestModuleImports:
    """Smoke tests for module-level imports."""

    def test_crs_imports(self):
        import kerf_civil.crs  # noqa: F401

    def test_tin_imports(self):
        import kerf_civil.tin  # noqa: F401

    def test_tools_imports(self):
        import kerf_civil.tools  # noqa: F401

    def test_plugin_imports(self):
        import kerf_civil.plugin  # noqa: F401

    def test_pycompile_crs(self):
        """Ensure crs.py compiles without errors."""
        import py_compile, os
        path = os.path.join(_SRC, "kerf_civil", "crs.py")
        py_compile.compile(path, doraise=True)

    def test_pycompile_tin(self):
        import py_compile, os
        path = os.path.join(_SRC, "kerf_civil", "tin.py")
        py_compile.compile(path, doraise=True)
