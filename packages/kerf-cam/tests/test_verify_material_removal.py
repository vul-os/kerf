"""
Tests for kerf_cam.verify — dexel/Z-map material-removal simulation.

Van Hook (1986) dexel method:
  - Known cube removal: 10×10×5 mm pocket swept by a flat 6mm endmill
    at Z=0 over a 10×10 mm stock area should remove ~500 mm³ (100% of stock).
  - Partial pass: a single line sweep removes a slot-shaped region.
  - Gouge detection: a cutter that goes 2 mm below the part surface is flagged.
  - Ball-nose profile: hemispherical bottom reduces removed volume vs flat.
  - G-code parser: X/Y/Z modal coordinates parse correctly.

Run:
    pytest packages/kerf-cam/tests/test_verify_material_removal.py -v
"""

import math
import pytest

from kerf_cam.verify import (
    ToolGeometry,
    DexelGrid,
    simulate_material_removal,
    _parse_gcode_moves,
    _parse_cl_points,
)


# ---------------------------------------------------------------------------
# ToolGeometry unit tests
# ---------------------------------------------------------------------------

class TestToolGeometry:
    def test_flat_profile_inside(self):
        t = ToolGeometry(diameter_mm=6.0, kind="flat")
        assert t.profile_z(0.0) == 0.0
        assert t.profile_z(2.9) == 0.0

    def test_flat_profile_outside(self):
        t = ToolGeometry(diameter_mm=6.0, kind="flat")
        assert math.isinf(t.profile_z(3.1))

    def test_ball_tip(self):
        t = ToolGeometry(diameter_mm=6.0, kind="ball")
        # At centre (r=0): profile_z = R - sqrt(R²-0) = R - R = 0
        assert t.profile_z(0.0) == pytest.approx(0.0)

    def test_ball_equator(self):
        t = ToolGeometry(diameter_mm=6.0, kind="ball")
        R = 3.0
        # At r = R: profile_z = R - sqrt(R²-R²) = R - 0 = R
        assert t.profile_z(R) == pytest.approx(R, rel=1e-6)

    def test_ball_outside(self):
        t = ToolGeometry(diameter_mm=6.0, kind="ball")
        assert math.isinf(t.profile_z(3.1))

    def test_bull_flat_core(self):
        t = ToolGeometry(diameter_mm=10.0, kind="bull", corner_radius_mm=1.0)
        # r < R - rc (flat core region)
        assert t.profile_z(3.0) == pytest.approx(0.0)

    def test_bull_corner_fillet(self):
        t = ToolGeometry(diameter_mm=10.0, kind="bull", corner_radius_mm=2.0)
        R, rc = 5.0, 2.0
        # At r = R (outermost): profile_z = rc - sqrt(rc² - rc²) = rc
        assert t.profile_z(R) == pytest.approx(rc, rel=1e-5)

    def test_bull_outside(self):
        t = ToolGeometry(diameter_mm=10.0, kind="bull", corner_radius_mm=1.0)
        assert math.isinf(t.profile_z(6.0))


# ---------------------------------------------------------------------------
# DexelGrid unit tests
# ---------------------------------------------------------------------------

class TestDexelGrid:
    def _make_grid(self, nx=20, ny=20, stock_top=0.0, stock_bottom=-10.0):
        return DexelGrid(
            x_min=0.0, x_max=10.0,
            y_min=0.0, y_max=10.0,
            nx=nx, ny=ny,
            stock_top=stock_top,
            stock_bottom=stock_bottom,
        )

    def test_initial_z_is_stock_top(self):
        g = self._make_grid(stock_top=5.0)
        # All cells should start at stock_top
        for ix in range(g.nx):
            for iy in range(g.ny):
                assert g.get_z(ix, iy) == pytest.approx(5.0)

    def test_sweep_flat_tool_lowers_cells(self):
        g = self._make_grid()
        tool = ToolGeometry(diameter_mm=4.0, kind="flat")
        # Sweep at centre, Z=-3 (cuts 3mm into stock)
        g.sweep_cutter(5.0, 5.0, -3.0, tool)
        # Centre cell should now be at -3.0
        cx, cy = g.cell_center(10, 10)
        assert abs(cx - 5.0) < 1.0 and abs(cy - 5.0) < 1.0
        ix, iy = g.xy_to_index(5.0, 5.0)
        assert g.get_z(ix, iy) == pytest.approx(-3.0, abs=0.01)

    def test_sweep_does_not_lower_far_cells(self):
        g = self._make_grid()
        tool = ToolGeometry(diameter_mm=4.0, kind="flat")
        # Sweep at centre, Z=-3
        g.sweep_cutter(5.0, 5.0, -3.0, tool)
        # Corner cells should be untouched (far from centre)
        ix, iy = g.xy_to_index(0.1, 0.1)
        assert g.get_z(ix, iy) == pytest.approx(0.0)

    def test_total_stock_volume(self):
        g = self._make_grid(stock_top=0.0, stock_bottom=-10.0)
        # 10×10×10 mm = 1000 mm³
        assert g.total_stock_volume() == pytest.approx(1000.0, rel=1e-3)

    def test_removed_volume_initially_zero(self):
        g = self._make_grid()
        assert g.removed_volume() == pytest.approx(0.0)

    def test_cell_area(self):
        g = DexelGrid(0, 10, 0, 10, nx=20, ny=20)
        # 10/20 = 0.5 mm per cell edge → 0.25 mm² area
        assert g.cell_area == pytest.approx(0.25, rel=1e-6)


# ---------------------------------------------------------------------------
# Numeric oracle: known cube removal
# ---------------------------------------------------------------------------

class TestKnownCubeRemoval:
    """
    Oracle test: a 10×10×5 mm pocket sweeping a flat 6mm endmill in a
    dense grid over Z=-5 should remove essentially 100% of the stock depth.

    Stock: 10×10×5 mm block (z from -5 to 0).
    Cutter: 6mm flat endmill sweeping a dense raster at Z=-5.
    Expected removed volume: 10×10×5 = 500 mm³ (100% cleared).
    """

    def test_full_pocket_removal(self):
        # Build a raster toolpath: sweep from X=0..10 in Y steps of 2mm at Z=-5
        points = []
        z = -5.0
        step = 2.0
        y = 0.0
        while y <= 10.0:
            # left→right
            for x_frac in range(11):
                points.append((x_frac * 1.0, y, z))
            y += step

        stock_bounds = {
            "x_min": 0.0, "x_max": 10.0,
            "y_min": 0.0, "y_max": 10.0,
            "stock_top": 0.0, "stock_bottom": -5.0,
        }
        tool = ToolGeometry(diameter_mm=6.0, kind="flat")

        result = simulate_material_removal(
            toolpath_points=points,
            tool=tool,
            stock_bounds=stock_bounds,
            resolution_mm=0.25,
        )

        # Dense raster with 6mm tool on 10×10 area — expect >90% cleared
        assert result["percent_cleared"] > 90.0, (
            f"Expected >90% cleared, got {result['percent_cleared']:.1f}%"
        )
        # Removed volume should be close to 500 mm³
        assert result["removed_volume_mm3"] > 400.0, (
            f"Expected >400 mm³ removed, got {result['removed_volume_mm3']:.1f}"
        )
        assert result["method"] == "dexel_zmap_van_hook_1986"

    def test_single_pass_removes_slot(self):
        """A single linear pass removes a strip, not the whole surface."""
        # Single line along X=5, Y varies from 0 to 10 at Z=-2
        points = [(5.0, y * 1.0, -2.0) for y in range(11)]

        stock_bounds = {
            "x_min": 0.0, "x_max": 10.0,
            "y_min": 0.0, "y_max": 10.0,
            "stock_top": 0.0, "stock_bottom": -5.0,
        }
        tool = ToolGeometry(diameter_mm=4.0, kind="flat")

        result = simulate_material_removal(
            toolpath_points=points,
            tool=tool,
            stock_bounds=stock_bounds,
            resolution_mm=0.25,
        )

        # Should remove ~4mm wide × 10mm long × 2mm deep = 80 mm³
        # But total stock = 10×10×5 = 500 mm³ → ~16%
        # Allow generous tolerance for grid quantisation
        assert 5.0 < result["percent_cleared"] < 60.0, (
            f"Single pass percent_cleared={result['percent_cleared']:.1f}% not in expected range"
        )
        assert result["removed_volume_mm3"] > 10.0


# ---------------------------------------------------------------------------
# Gouge detection oracle
# ---------------------------------------------------------------------------

class TestGougeDetection:
    """
    Oracle: a cutter that descends 2mm below the finished part surface
    (Z=0) must produce gouge_points.
    """

    def test_gouge_detected_below_part_surface(self):
        # Cutter goes to Z=-2 (2mm below part surface at Z=0)
        points = [(5.0, 5.0, -2.0)]

        stock_bounds = {
            "x_min": 0.0, "x_max": 10.0,
            "y_min": 0.0, "y_max": 10.0,
            "stock_top": 0.0, "stock_bottom": -5.0,
        }
        tool = ToolGeometry(diameter_mm=4.0, kind="flat")
        part_surface = lambda x, y: 0.0  # part surface at Z=0

        result = simulate_material_removal(
            toolpath_points=points,
            tool=tool,
            stock_bounds=stock_bounds,
            part_surface_z=part_surface,
            resolution_mm=0.5,
        )

        assert len(result["gouge_points"]) > 0, "Expected gouge points but got none"
        # Deepest gouge should be at approximately z=-2 (cutter tip)
        deepest = result["gouge_points"][0]
        assert deepest["depth"] > 1.5, f"Expected depth > 1.5mm, got {deepest['depth']}"
        assert deepest["z_part"] == pytest.approx(0.0, abs=0.01)

    def test_no_gouge_when_cutter_above_surface(self):
        # Cutter at Z=+1 (above part surface) — no gouge
        points = [(5.0, 5.0, 1.0)]

        stock_bounds = {
            "x_min": 0.0, "x_max": 10.0,
            "y_min": 0.0, "y_max": 10.0,
            "stock_top": 2.0, "stock_bottom": -5.0,
        }
        tool = ToolGeometry(diameter_mm=4.0, kind="flat")
        part_surface = lambda x, y: 0.0  # part at Z=0

        result = simulate_material_removal(
            toolpath_points=points,
            tool=tool,
            stock_bounds=stock_bounds,
            part_surface_z=part_surface,
            resolution_mm=0.5,
        )

        assert len(result["gouge_points"]) == 0, (
            f"Expected no gouges but got {len(result['gouge_points'])}"
        )

    def test_gouge_points_sorted_by_depth_descending(self):
        """Multiple gouge points must be sorted worst-first."""
        # Two cutter positions at different depths below part surface
        points = [(3.0, 5.0, -3.0), (7.0, 5.0, -1.0)]

        stock_bounds = {
            "x_min": 0.0, "x_max": 10.0,
            "y_min": 0.0, "y_max": 10.0,
            "stock_top": 0.0, "stock_bottom": -5.0,
        }
        tool = ToolGeometry(diameter_mm=2.0, kind="flat")
        part_surface = lambda x, y: 0.0

        result = simulate_material_removal(
            toolpath_points=points,
            tool=tool,
            stock_bounds=stock_bounds,
            part_surface_z=part_surface,
            resolution_mm=0.5,
        )

        gouges = result["gouge_points"]
        assert len(gouges) >= 2, "Expected at least 2 gouge points"
        for i in range(len(gouges) - 1):
            assert gouges[i]["depth"] >= gouges[i + 1]["depth"], (
                "Gouge points not sorted by depth descending"
            )


# ---------------------------------------------------------------------------
# Ball-nose vs flat endmill comparison
# ---------------------------------------------------------------------------

class TestBallVsFlat:
    """
    Ball-nose removes less material than flat endmill at the same Z level
    (the spherical bottom means material remains at the edges of the swept arc).
    """

    def test_ball_removes_less_than_flat(self):
        points = [(5.0, 5.0, -2.0)]
        stock_bounds = {
            "x_min": 0.0, "x_max": 10.0,
            "y_min": 0.0, "y_max": 10.0,
            "stock_top": 0.0, "stock_bottom": -5.0,
        }

        flat_tool = ToolGeometry(diameter_mm=6.0, kind="flat")
        ball_tool = ToolGeometry(diameter_mm=6.0, kind="ball")

        result_flat = simulate_material_removal(
            toolpath_points=points, tool=flat_tool, stock_bounds=stock_bounds, resolution_mm=0.25
        )
        result_ball = simulate_material_removal(
            toolpath_points=points, tool=ball_tool, stock_bounds=stock_bounds, resolution_mm=0.25
        )

        assert result_flat["removed_volume_mm3"] > result_ball["removed_volume_mm3"], (
            f"Flat {result_flat['removed_volume_mm3']:.2f} should > ball "
            f"{result_ball['removed_volume_mm3']:.2f}"
        )


# ---------------------------------------------------------------------------
# G-code parser
# ---------------------------------------------------------------------------

class TestGcodeParser:
    def test_basic_g0_g1_moves(self):
        gcode = """\
%
G0 X0 Y0 Z5
G1 X10 Y0 Z0 F1000
G1 X10 Y10 Z0
G1 X0 Y10 Z0
G1 X0 Y0 Z0
%"""
        pts = _parse_gcode_moves(gcode)
        # Should have 5+ points
        assert len(pts) >= 5

    def test_modal_coordinates(self):
        gcode = "G1 X5\nG1 Y3\nG1 Z-2"
        pts = _parse_gcode_moves(gcode)
        # After X5: (5,0,0); after Y3: (5,3,0); after Z-2: (5,3,-2)
        last = pts[-1]
        assert last[0] == pytest.approx(5.0)
        assert last[1] == pytest.approx(3.0)
        assert last[2] == pytest.approx(-2.0)

    def test_z_value_parsed(self):
        gcode = "G1 X0 Y0 Z-5.25"
        pts = _parse_gcode_moves(gcode)
        z_vals = [p[2] for p in pts]
        assert -5.25 in z_vals

    def test_comment_lines_skipped(self):
        gcode = "; this is a comment\n(another comment)\nG1 X1 Y1 Z0"
        pts = _parse_gcode_moves(gcode)
        x_vals = [p[0] for p in pts]
        assert 1.0 in x_vals

    def test_percent_line_skipped(self):
        gcode = "%\nG1 X2 Y3 Z-1\n%"
        pts = _parse_gcode_moves(gcode)
        assert any(p[0] == pytest.approx(2.0) for p in pts)

    def test_arc_moves_skipped(self):
        gcode = "G1 X0 Y0 Z0\nG2 X5 Y5 R3\nG1 X10 Y0 Z0"
        pts = _parse_gcode_moves(gcode)
        # G2 arc should be skipped; X should not jump to 5 via arc
        # We end at X=10 after the last G1
        assert pts[-1][0] == pytest.approx(10.0)

    def test_cl_points_conversion(self):
        cl = [{"x": 1.0, "y": 2.0, "z": 3.0}, {"x": 4.0, "y": 5.0, "z": 6.0}]
        pts = _parse_cl_points(cl)
        assert pts[0] == (1.0, 2.0, 3.0)
        assert pts[1] == (4.0, 5.0, 6.0)


# ---------------------------------------------------------------------------
# Result structure / metadata
# ---------------------------------------------------------------------------

class TestResultStructure:
    def test_all_keys_present(self):
        points = [(0.0, 0.0, 0.0), (5.0, 5.0, -1.0)]
        stock_bounds = {"x_min": 0.0, "x_max": 10.0, "y_min": 0.0, "y_max": 10.0,
                        "stock_top": 0.0, "stock_bottom": -5.0}
        tool = ToolGeometry(diameter_mm=4.0, kind="flat")
        result = simulate_material_removal(points, tool, stock_bounds, resolution_mm=1.0)

        required = [
            "removed_volume_mm3", "total_stock_mm3", "percent_cleared",
            "remaining_stock_mm3", "gouge_points", "n_moves",
            "grid_nx", "grid_ny", "method",
        ]
        for key in required:
            assert key in result, f"Missing key: {key}"

    def test_volume_conservation(self):
        """removed + remaining == total."""
        points = [(5.0, 5.0, -2.0)]
        stock_bounds = {"x_min": 0.0, "x_max": 10.0, "y_min": 0.0, "y_max": 10.0,
                        "stock_top": 0.0, "stock_bottom": -5.0}
        tool = ToolGeometry(diameter_mm=4.0, kind="flat")
        result = simulate_material_removal(points, tool, stock_bounds, resolution_mm=0.5)

        total = result["total_stock_mm3"]
        removed = result["removed_volume_mm3"]
        remaining = result["remaining_stock_mm3"]
        assert removed + remaining == pytest.approx(total, rel=1e-4)

    def test_percent_cleared_range(self):
        points = [(5.0, 5.0, 0.0)]
        stock_bounds = {"x_min": 0.0, "x_max": 10.0, "y_min": 0.0, "y_max": 10.0,
                        "stock_top": 0.0, "stock_bottom": -5.0}
        tool = ToolGeometry(diameter_mm=4.0, kind="flat")
        result = simulate_material_removal(points, tool, stock_bounds, resolution_mm=0.5)

        assert 0.0 <= result["percent_cleared"] <= 100.0
