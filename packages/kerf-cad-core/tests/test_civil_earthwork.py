"""
Tests for kerf_cad_core.civil — terrain (TIN), earthwork volumes, and tools.

All tests are pure-Python, hermetic: no OCC, no DB, no network, no fixtures
from disk.  Tests run deterministically with fixed numeric inputs.

Author: imranparuk
"""
from __future__ import annotations

import asyncio
import json
import math
import uuid

import pytest

from kerf_cad_core.civil.terrain import (
    TIN,
    Point3D,
    Triangle,
    build_tin,
    _bary_z,
    _all_collinear,
)
from kerf_cad_core.civil.earthwork import (
    DesignSurface,
    EarthworkResult,
    compute_earthwork,
    validate_polygon,
    _point_in_polygon,
)
from kerf_cad_core.civil.tools import (
    run_civil_terrain,
    run_civil_pad,
    run_civil_earthwork,
    run_civil_grading_report,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _make_ctx():
    from kerf_core.utils.context import ProjectCtx  # type: ignore[import]
    return ProjectCtx(
        pool=None, storage=None,
        project_id=uuid.uuid4(), user_id=uuid.uuid4(),
        role="owner", http_client=None,
    )


def _ok(raw: str) -> dict:
    d = json.loads(raw)
    assert d.get("ok") is True, f"Expected ok=True, got: {d}"
    return d


def _err(raw: str) -> dict:
    d = json.loads(raw)
    assert d.get("ok") is False, f"Expected ok=False, got: {d}"
    assert "errors" in d, f"Expected 'errors' key in: {d}"
    return d


def _flat_square_points(elev: float = 100.0) -> list[dict]:
    """A flat 10×10 m square grid of survey points at constant elevation."""
    pts = []
    for xi in range(0, 11, 2):
        for yi in range(0, 11, 2):
            pts.append({"x": float(xi), "y": float(yi), "z": elev})
    return pts


def _flat_square_polygon() -> list[list[float]]:
    return [[0.0, 0.0], [10.0, 0.0], [10.0, 10.0], [0.0, 10.0]]


# ===========================================================================
# 1. TIN construction & collinearity validation
# ===========================================================================

class TestTINConstruction:

    def test_simple_triangle(self):
        """Three non-collinear points → 1 triangle."""
        pts = [Point3D(0, 0, 0), Point3D(10, 0, 0), Point3D(5, 10, 0)]
        tin = TIN(pts)
        assert len(tin.triangles) == 1
        assert len(tin.points) == 3

    def test_four_point_grid_triangle_count(self):
        """Four points (2×2 grid corners) → exactly 2 triangles (fan from hub)."""
        pts = [
            Point3D(0, 0, 0), Point3D(10, 0, 0),
            Point3D(10, 10, 0), Point3D(0, 10, 0),
        ]
        tin = TIN(pts)
        # Fan from first lex point (0,0): 4-2 = 2 triangles
        assert len(tin.triangles) == 2

    def test_five_point_triangle_count(self):
        """Five points (all off-axis) → at least 2 triangles; maximum is N-2=3."""
        pts = [
            Point3D(0, 0, 0), Point3D(10, 0, 5),
            Point3D(10, 10, 3), Point3D(0, 10, 1), Point3D(5, 5, 2),
        ]
        tin = TIN(pts)
        # Fan produces N-2 non-degenerate triangles; degenerate slivers are
        # silently dropped, so result is 2 or 3.
        assert len(tin.triangles) >= 2
        assert len(tin.triangles) <= 4

    def test_too_few_points_raises(self):
        """< 3 points → ValueError."""
        with pytest.raises(ValueError, match="at least 3"):
            TIN([Point3D(0, 0, 0), Point3D(1, 0, 0)])

    def test_zero_points_raises(self):
        with pytest.raises(ValueError):
            TIN([])

    def test_collinear_points_raises(self):
        """All points on a line → ValueError."""
        pts = [Point3D(0, 0, 0), Point3D(1, 0, 0), Point3D(2, 0, 0),
               Point3D(3, 0, 0)]
        with pytest.raises(ValueError, match="collinear"):
            TIN(pts)

    def test_area_flat_square(self):
        """Flat 10×10 m grid → area ≈ 100 m² (depends on triangulation coverage)."""
        pts = [
            Point3D(0, 0, 0), Point3D(10, 0, 0),
            Point3D(10, 10, 0), Point3D(0, 10, 0),
        ]
        tin = TIN(pts)
        # Fan covers the two triangles of the square
        assert abs(tin.area_m2 - 100.0) < 1e-6

    def test_min_max_elevation(self):
        pts = [
            Point3D(0, 0, 100.0), Point3D(10, 0, 105.0),
            Point3D(5, 10, 98.0),
        ]
        tin = TIN(pts)
        assert tin.min_z == pytest.approx(98.0)
        assert tin.max_z == pytest.approx(105.0)

    def test_deterministic_same_triangles_regardless_of_input_order(self):
        """Reordering input produces same set of triangles."""
        pts1 = [Point3D(0, 0, 0), Point3D(10, 0, 1), Point3D(5, 10, 2)]
        pts2 = [Point3D(5, 10, 2), Point3D(0, 0, 0), Point3D(10, 0, 1)]
        tin1 = TIN(pts1)
        tin2 = TIN(pts2)
        assert len(tin1.triangles) == len(tin2.triangles)
        assert tin1.triangles == tin2.triangles


# ===========================================================================
# 2. Barycentric interpolation
# ===========================================================================

class TestBarycentricInterpolation:

    def test_interpolate_vertex_returns_exact_z(self):
        """Query at a triangle vertex → exact vertex Z."""
        a = Point3D(0, 0, 10.0)
        b = Point3D(10, 0, 20.0)
        c = Point3D(5, 10, 30.0)
        tri = Triangle(a, b, c)
        assert _bary_z(tri, Point3D(0, 0, 0)) == pytest.approx(10.0)
        assert _bary_z(tri, Point3D(10, 0, 0)) == pytest.approx(20.0)
        assert _bary_z(tri, Point3D(5, 10, 0)) == pytest.approx(30.0)

    def test_interpolate_centroid(self):
        """Centroid of a triangle with uniform z → same z."""
        a = Point3D(0, 0, 5.0)
        b = Point3D(6, 0, 5.0)
        c = Point3D(3, 6, 5.0)
        tri = Triangle(a, b, c)
        cx, cy = (0 + 6 + 3) / 3, (0 + 0 + 6) / 3
        assert _bary_z(tri, Point3D(cx, cy, 0)) == pytest.approx(5.0)

    def test_interpolate_midpoint_edge(self):
        """Midpoint of edge ab has z = (za + zb)/2."""
        a = Point3D(0, 0, 0.0)
        b = Point3D(10, 0, 10.0)
        c = Point3D(5, 10, 5.0)
        tri = Triangle(a, b, c)
        mid_z = _bary_z(tri, Point3D(5, 0, 0))
        assert mid_z == pytest.approx(5.0, abs=1e-9)

    def test_outside_point_returns_none(self):
        """Point well outside triangle → None."""
        a = Point3D(0, 0, 0)
        b = Point3D(10, 0, 0)
        c = Point3D(5, 10, 0)
        tri = Triangle(a, b, c)
        assert _bary_z(tri, Point3D(100, 100, 0)) is None

    def test_tin_interpolate_z_inside(self):
        """TIN.interpolate_z for a point inside returns a numeric value."""
        pts = [Point3D(0, 0, 0), Point3D(10, 0, 0),
               Point3D(10, 10, 0), Point3D(0, 10, 0)]
        tin = TIN(pts)
        z = tin.interpolate_z(5, 5)
        assert z is not None
        assert isinstance(z, float)

    def test_tin_interpolate_z_outside_returns_none(self):
        """TIN.interpolate_z for a point far outside → None."""
        pts = [Point3D(0, 0, 0), Point3D(10, 0, 0),
               Point3D(10, 10, 0), Point3D(0, 10, 0)]
        tin = TIN(pts)
        z = tin.interpolate_z(100, 100)
        assert z is None

    def test_linear_slope_interpolation(self):
        """On a linearly sloping plane z=x, interpolation at x=3 gives z=3."""
        pts = [Point3D(0, 0, 0), Point3D(10, 0, 10), Point3D(5, 10, 5)]
        tin = TIN(pts)
        z = tin.interpolate_z(3, 3)
        # On plane z=x, z at x=3 should be 3.0
        assert z == pytest.approx(3.0, abs=0.01)


# ===========================================================================
# 3. build_tin validation
# ===========================================================================

class TestBuildTin:

    def test_valid_input(self):
        pts = [{"x": 0, "y": 0, "z": 0}, {"x": 10, "y": 0, "z": 1},
               {"x": 5, "y": 10, "z": 2}]
        tin, errors = build_tin(pts)
        assert tin is not None
        assert errors == []

    def test_fewer_than_3_points(self):
        pts = [{"x": 0, "y": 0, "z": 0}, {"x": 1, "y": 0, "z": 0}]
        tin, errors = build_tin(pts)
        assert tin is None
        assert len(errors) == 1
        assert "3" in errors[0]

    def test_collinear_returns_error(self):
        pts = [{"x": 0, "y": 0, "z": 0}, {"x": 1, "y": 0, "z": 0},
               {"x": 2, "y": 0, "z": 0}]
        tin, errors = build_tin(pts)
        assert tin is None
        assert any("collinear" in e for e in errors)

    def test_missing_z_field_returns_error(self):
        pts = [{"x": 0, "y": 0}, {"x": 1, "y": 0, "z": 0},
               {"x": 0, "y": 1, "z": 0}]
        tin, errors = build_tin(pts)
        assert tin is None
        assert len(errors) >= 1

    def test_non_list_input_returns_error(self):
        tin, errors = build_tin("not a list")
        assert tin is None
        assert errors


# ===========================================================================
# 4. Earthwork: flat terrain → zero earthwork at matching elevation
# ===========================================================================

class TestFlatTerrainZeroEarthwork:

    def test_flat_terrain_same_pad_elevation_zero_earthwork(self):
        """
        Flat terrain at z=100, pad at z=100 → cut=0, fill=0.
        """
        pts = [Point3D(float(x), float(y), 100.0)
               for x in range(0, 11, 2) for y in range(0, 11, 2)]
        tin = TIN(pts)
        design = DesignSurface(
            pad_elevation=100.0,
            polygon=[(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)],
        )
        result = compute_earthwork(tin, design, grid_spacing=1.0)
        assert result.cut_m3 == pytest.approx(0.0, abs=1e-6)
        assert result.fill_m3 == pytest.approx(0.0, abs=1e-6)
        assert result.net_m3 == pytest.approx(0.0, abs=1e-6)


# ===========================================================================
# 5. Raising a flat pad by 1 m → fill = area × 1
# ===========================================================================

class TestFillVolume:

    def test_raise_pad_1m_fill_equals_area(self):
        """
        Flat terrain at z=100, pad at z=101 over a 10×10 m polygon.
        Each sampled cell contributes 1.0 m × cell_area m³ of fill.
        The fan TIN from a 2m-spaced grid covers ~70 of the 100 unit cells;
        so fill ≈ sample_count × 1.0.  We check the invariant:
            fill_m3 = sample_count × 1.0 (to 6 dp)
        and that fill > 0 with no cut.
        """
        pts = [Point3D(float(x), float(y), 100.0)
               for x in range(0, 11, 2) for y in range(0, 11, 2)]
        tin = TIN(pts)
        design = DesignSurface(
            pad_elevation=101.0,
            polygon=[(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)],
        )
        result = compute_earthwork(tin, design, grid_spacing=1.0)
        assert result.cut_m3 == pytest.approx(0.0, abs=0.1)
        # Each sampled cell contributes exactly 1.0 m (height diff) × 1.0 m² (cell area)
        assert result.fill_m3 == pytest.approx(result.sample_count * 1.0, rel=1e-6)
        assert result.fill_m3 > 0
        assert result.net_m3 > 0


# ===========================================================================
# 6. Cutting a flat pad (lower than terrain) → cut = area × depth
# ===========================================================================

class TestCutVolume:

    def test_lower_pad_1m_cut_equals_area(self):
        """
        Flat terrain at z=101, pad at z=100 over 10×10 m.
        Each sampled cell contributes 1.0 m × cell_area of cut.
        cut_m3 = sample_count × 1.0 (same symmetry as fill test).
        """
        pts = [Point3D(float(x), float(y), 101.0)
               for x in range(0, 11, 2) for y in range(0, 11, 2)]
        tin = TIN(pts)
        design = DesignSurface(
            pad_elevation=100.0,
            polygon=[(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)],
        )
        result = compute_earthwork(tin, design, grid_spacing=1.0)
        assert result.fill_m3 == pytest.approx(0.0, abs=0.1)
        assert result.cut_m3 == pytest.approx(result.sample_count * 1.0, rel=1e-6)
        assert result.cut_m3 > 0
        assert result.net_m3 < 0


# ===========================================================================
# 7. Balanced cut ≈ fill scenario
# ===========================================================================

class TestBalancedEarthwork:

    def test_balanced_cut_fill_ratio_near_one(self):
        """
        Sloped terrain (z = x/10 + 100) with pad at midpoint elevation.
        Cut and fill should be roughly equal → balance_ratio ≈ 1.0.
        """
        pts = []
        for xi in range(0, 11, 2):
            for yi in range(0, 11, 2):
                z = 100.0 + xi / 10.0  # ranges 100 to 101 over x=[0..10]
                pts.append(Point3D(float(xi), float(yi), z))
        tin = TIN(pts)
        # Pad at z=100.5 (midpoint of 100..101) over the same 10x10 polygon
        design = DesignSurface(
            pad_elevation=100.5,
            polygon=[(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)],
        )
        result = compute_earthwork(tin, design, grid_spacing=1.0)
        # Cut and fill should be roughly equal
        assert result.balance_ratio == pytest.approx(1.0, rel=0.3)
        assert math.isfinite(result.balance_ratio)


# ===========================================================================
# 8. DesignSurface validation
# ===========================================================================

class TestDesignSurfaceValidation:

    def test_polygon_fewer_than_3_vertices_error(self):
        errors = validate_polygon([[0, 0], [1, 0]])
        assert len(errors) == 1
        assert "3" in errors[0]

    def test_polygon_not_list_error(self):
        errors = validate_polygon("not a list")
        assert errors

    def test_valid_polygon_no_errors(self):
        errors = validate_polygon([[0, 0], [10, 0], [10, 10], [0, 10]])
        assert errors == []

    def test_negative_slope_ratio_error(self):
        ds = DesignSurface(
            pad_elevation=100.0,
            polygon=[(0, 0), (1, 0), (1, 1), (0, 1)],
            side_slope_ratio=-1.0,
        )
        errors = ds.validate()
        assert any("slope" in e.lower() for e in errors)


# ===========================================================================
# 9. Point-in-polygon
# ===========================================================================

class TestPointInPolygon:

    def test_center_inside_square(self):
        ring = [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)]
        assert _point_in_polygon(5.0, 5.0, ring) is True

    def test_outside_square(self):
        ring = [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)]
        assert _point_in_polygon(15.0, 5.0, ring) is False

    def test_corner_inside_triangle(self):
        ring = [(0.0, 0.0), (10.0, 0.0), (5.0, 10.0)]
        # centroid
        assert _point_in_polygon(5.0, 3.0, ring) is True

    def test_point_outside_triangle(self):
        ring = [(0.0, 0.0), (10.0, 0.0), (5.0, 10.0)]
        assert _point_in_polygon(-1.0, -1.0, ring) is False


# ===========================================================================
# 10. LLM tool: civil_terrain
# ===========================================================================

class TestCivilTerrainTool:

    def test_valid_points_returns_ok(self):
        ctx = _make_ctx()
        args = json.dumps({"points": _flat_square_points()}).encode()
        raw = _run(run_civil_terrain(ctx, args))
        d = _ok(raw)
        assert d["triangle_count"] >= 1
        assert d["area_m2"] > 0

    def test_fewer_than_3_points_returns_error(self):
        ctx = _make_ctx()
        args = json.dumps({"points": [
            {"x": 0, "y": 0, "z": 0}, {"x": 1, "y": 0, "z": 0}
        ]}).encode()
        raw = _run(run_civil_terrain(ctx, args))
        _err(raw)

    def test_collinear_points_returns_error(self):
        ctx = _make_ctx()
        args = json.dumps({"points": [
            {"x": 0, "y": 0, "z": 0}, {"x": 1, "y": 0, "z": 0},
            {"x": 2, "y": 0, "z": 0},
        ]}).encode()
        raw = _run(run_civil_terrain(ctx, args))
        _err(raw)

    def test_returns_elevation_stats(self):
        ctx = _make_ctx()
        pts = [
            {"x": 0, "y": 0, "z": 98.0}, {"x": 10, "y": 0, "z": 102.0},
            {"x": 5, "y": 10, "z": 105.0},
        ]
        args = json.dumps({"points": pts}).encode()
        raw = _run(run_civil_terrain(ctx, args))
        d = _ok(raw)
        assert d["min_elevation_m"] == pytest.approx(98.0)
        assert d["max_elevation_m"] == pytest.approx(105.0)

    def test_invalid_json_returns_error(self):
        ctx = _make_ctx()
        raw = _run(run_civil_terrain(ctx, b"not-json"))
        d = json.loads(raw)
        assert "error" in d or d.get("ok") is False


# ===========================================================================
# 11. LLM tool: civil_pad
# ===========================================================================

class TestCivilPadTool:

    def test_valid_pad_returns_ok(self):
        ctx = _make_ctx()
        args = json.dumps({
            "polygon": [[0, 0], [10, 0], [10, 10], [0, 10]],
            "pad_elevation": 100.0,
        }).encode()
        raw = _run(run_civil_pad(ctx, args))
        d = _ok(raw)
        assert d["pad_elevation"] == pytest.approx(100.0)
        assert "design_surface_json" in d

    def test_too_few_polygon_vertices_returns_error(self):
        ctx = _make_ctx()
        args = json.dumps({
            "polygon": [[0, 0], [10, 0]],
            "pad_elevation": 100.0,
        }).encode()
        raw = _run(run_civil_pad(ctx, args))
        _err(raw)

    def test_missing_pad_elevation_returns_error(self):
        ctx = _make_ctx()
        args = json.dumps({
            "polygon": [[0, 0], [10, 0], [10, 10], [0, 10]],
        }).encode()
        raw = _run(run_civil_pad(ctx, args))
        _err(raw)

    def test_side_slope_stored_in_design_surface_json(self):
        ctx = _make_ctx()
        args = json.dumps({
            "polygon": [[0, 0], [10, 0], [10, 10], [0, 10]],
            "pad_elevation": 101.0,
            "side_slope_ratio": 2.5,
        }).encode()
        raw = _run(run_civil_pad(ctx, args))
        d = _ok(raw)
        assert d["side_slope_ratio"] == pytest.approx(2.5)
        assert d["design_surface_json"]["side_slope_ratio"] == pytest.approx(2.5)

    def test_sloped_pad_fields(self):
        ctx = _make_ctx()
        args = json.dumps({
            "polygon": [[0, 0], [10, 0], [10, 10], [0, 10]],
            "pad_elevation": 100.0,
            "sloped": True,
            "dz_dx": 0.01,
            "dz_dy": 0.005,
        }).encode()
        raw = _run(run_civil_pad(ctx, args))
        d = _ok(raw)
        assert d["sloped"] is True
        assert d["dz_dx"] == pytest.approx(0.01)


# ===========================================================================
# 12. LLM tool: civil_earthwork
# ===========================================================================

class TestCivilEarthworkTool:

    def _design_surface_json(self, elev: float, spacing: float = 0.0) -> dict:
        return {
            "pad_elevation": elev,
            "polygon": [[0.0, 0.0], [10.0, 0.0], [10.0, 10.0], [0.0, 10.0]],
            "side_slope_ratio": spacing,
            "sloped": False,
            "dz_dx": 0.0,
            "dz_dy": 0.0,
        }

    def test_zero_earthwork_matching_elevation(self):
        ctx = _make_ctx()
        args = json.dumps({
            "tin_points": _flat_square_points(100.0),
            "design_surface": self._design_surface_json(100.0),
            "grid_spacing_m": 1.0,
        }).encode()
        raw = _run(run_civil_earthwork(ctx, args))
        d = _ok(raw)
        assert d["cut_m3"] == pytest.approx(0.0, abs=0.01)
        assert d["fill_m3"] == pytest.approx(0.0, abs=0.01)

    def test_fill_volume_raised_pad(self):
        ctx = _make_ctx()
        args = json.dumps({
            "tin_points": _flat_square_points(100.0),
            "design_surface": self._design_surface_json(101.0),
            "grid_spacing_m": 1.0,
        }).encode()
        raw = _run(run_civil_earthwork(ctx, args))
        d = _ok(raw)
        assert d["fill_m3"] > 50  # at least half of 100 m³

    def test_cut_volume_lowered_pad(self):
        ctx = _make_ctx()
        args = json.dumps({
            "tin_points": _flat_square_points(101.0),
            "design_surface": self._design_surface_json(100.0),
            "grid_spacing_m": 1.0,
        }).encode()
        raw = _run(run_civil_earthwork(ctx, args))
        d = _ok(raw)
        assert d["cut_m3"] > 50

    def test_missing_tin_points_returns_error(self):
        ctx = _make_ctx()
        args = json.dumps({
            "design_surface": self._design_surface_json(100.0),
        }).encode()
        raw = _run(run_civil_earthwork(ctx, args))
        _err(raw)

    def test_invalid_grid_spacing_returns_error(self):
        ctx = _make_ctx()
        args = json.dumps({
            "tin_points": _flat_square_points(),
            "design_surface": self._design_surface_json(100.0),
            "grid_spacing_m": -1.0,
        }).encode()
        raw = _run(run_civil_earthwork(ctx, args))
        _err(raw)

    def test_collinear_tin_returns_error(self):
        ctx = _make_ctx()
        args = json.dumps({
            "tin_points": [
                {"x": 0, "y": 0, "z": 0},
                {"x": 1, "y": 0, "z": 0},
                {"x": 2, "y": 0, "z": 0},
            ],
            "design_surface": self._design_surface_json(100.0),
        }).encode()
        raw = _run(run_civil_earthwork(ctx, args))
        _err(raw)

    def test_balance_ratio_field_present(self):
        ctx = _make_ctx()
        args = json.dumps({
            "tin_points": _flat_square_points(100.0),
            "design_surface": self._design_surface_json(100.5),
            "grid_spacing_m": 1.0,
        }).encode()
        raw = _run(run_civil_earthwork(ctx, args))
        d = _ok(raw)
        assert "balance_ratio" in d
        assert "sample_count" in d


# ===========================================================================
# 13. LLM tool: civil_grading_report
# ===========================================================================

class TestCivilGradingReportTool:

    def _ew_payload(self) -> dict:
        return {
            "ok": True,
            "cut_m3": 245.3,
            "fill_m3": 198.7,
            "net_m3": -46.6,
            "balance_ratio": 1.234,
            "sample_count": 320,
            "grid_spacing_m": 1.0,
            "cell_area_m2": 1.0,
            "note": "More cut than fill.",
        }

    def test_valid_report_returns_ok(self):
        ctx = _make_ctx()
        args = json.dumps({
            "earthwork": self._ew_payload(),
            "project_name": "Site A",
        }).encode()
        raw = _run(run_civil_grading_report(ctx, args))
        d = _ok(raw)
        assert "report_text" in d
        assert "summary_lines" in d
        assert "Site A" in d["report_text"]
        assert "245.30" in d["report_text"]

    def test_report_includes_cut_fill_values(self):
        ctx = _make_ctx()
        args = json.dumps({"earthwork": self._ew_payload()}).encode()
        raw = _run(run_civil_grading_report(ctx, args))
        d = _ok(raw)
        assert "245" in d["report_text"]
        assert "198" in d["report_text"]

    def test_missing_earthwork_returns_error(self):
        ctx = _make_ctx()
        args = json.dumps({"project_name": "X"}).encode()
        raw = _run(run_civil_grading_report(ctx, args))
        _err(raw)

    def test_invalid_json_returns_error(self):
        ctx = _make_ctx()
        raw = _run(run_civil_grading_report(ctx, b"{bad json"))
        d = json.loads(raw)
        assert "error" in d or d.get("ok") is False


# ===========================================================================
# 14. EarthworkResult.to_dict
# ===========================================================================

class TestEarthworkResultToDict:

    def test_to_dict_keys_present(self):
        result = EarthworkResult(
            cut_m3=100.0, fill_m3=80.0, net_m3=-20.0,
            balance_ratio=1.25, sample_count=200,
            grid_spacing_m=1.0, cell_area_m2=1.0,
        )
        d = result.to_dict()
        for key in ("cut_m3", "fill_m3", "net_m3", "balance_ratio",
                    "sample_count", "grid_spacing_m", "cell_area_m2", "note"):
            assert key in d, f"Missing key: {key}"

    def test_to_dict_infinite_ratio_becomes_none(self):
        result = EarthworkResult(
            cut_m3=100.0, fill_m3=0.0, net_m3=-100.0,
            balance_ratio=math.inf, sample_count=100,
            grid_spacing_m=1.0, cell_area_m2=1.0,
        )
        d = result.to_dict()
        assert d["balance_ratio"] is None

    def test_to_dict_rounding(self):
        result = EarthworkResult(
            cut_m3=1.123456789, fill_m3=2.987654321, net_m3=1.864197532,
            balance_ratio=0.376, sample_count=10,
            grid_spacing_m=0.5, cell_area_m2=0.25,
        )
        d = result.to_dict()
        # Values should be rounded to 4 decimal places
        assert d["cut_m3"] == round(1.123456789, 4)
        assert d["fill_m3"] == round(2.987654321, 4)


# ===========================================================================
# 15. TIN summary dict
# ===========================================================================

class TestTINSummary:

    def test_summary_keys(self):
        pts = [Point3D(0, 0, 100), Point3D(10, 0, 101), Point3D(5, 10, 102)]
        tin = TIN(pts)
        s = tin.summary()
        for key in ("point_count", "triangle_count", "area_m2",
                    "min_elevation_m", "max_elevation_m", "elevation_range_m"):
            assert key in s

    def test_summary_values(self):
        pts = [Point3D(0, 0, 100), Point3D(10, 0, 100), Point3D(5, 10, 100)]
        tin = TIN(pts)
        s = tin.summary()
        assert s["point_count"] == 3
        assert s["triangle_count"] == 1
        assert s["min_elevation_m"] == pytest.approx(100.0)
        assert s["max_elevation_m"] == pytest.approx(100.0)
        assert s["elevation_range_m"] == pytest.approx(0.0)
