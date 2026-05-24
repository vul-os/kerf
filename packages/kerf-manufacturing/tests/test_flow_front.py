"""Tests for flow_front.py — transient fill, weld-line, and air-trap prediction.

Validation oracles
------------------
1. flow_front_t_shape_weld_line
   T-shaped cavity (crossbar 16 wide × 4 high, stem below).  Gates at each
   end of the crossbar (col 0 and col 15).  Two flow branches race inward
   from each end and meet in the centre of the crossbar → weld line.

2. flow_front_pocket_air_trap
   Rectangular main channel with a dead-end pocket on one side.  Gate is at
   the left end; flow races down the main channel past the pocket, surrounding
   it.  The pocket (no vent) becomes an enclosed air trap.

3. flow_front_basic_fill
   Simple rectangular cavity fills without air traps (single-gate, vent on far
   wall).

4. weld_air_analysis_dict_api
   Exercise the public ``weld_air_analysis`` function through dict inputs
   (LLM-tool code path).

5. cavity_grid_shape_validation
   CavityGrid raises ValueError on mismatched shapes.

6. tool_spec_schema
   The TOOL_SPEC constant is present and has the expected structure.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import pytest

from kerf_manufacturing.moldflow.flow_front import (
    CavityGrid,
    GateSpec,
    VentSpec,
    MaterialProps,
    weld_air_analysis,
    make_t_cavity,
    make_donut_cavity,
    TOOL_SPEC,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_pocket_cavity() -> tuple[CavityGrid, list[GateSpec], list[VentSpec]]:
    """Main channel (12×3) + dead-end pocket (3×4) attached to upper wall.

    Layout (ny=7, nx=12):
      row 0-3: pocket (cols 4-6 only)
      row 3-6: main channel (cols 0-11)

    Gate: left end of main channel (row 4-5, col 0).
    Vent: right end of main channel (row 4-5, col 11).
    Pocket has no direct vent → air trap.
    """
    ny, nx = 7, 12
    cells = np.zeros((ny, nx), dtype=bool)
    # Main channel: rows 3-6, all cols
    cells[3:, :] = True
    # Pocket: rows 0-3, cols 4-6 (open at bottom, connected to main channel row 3)
    cells[:4, 4:7] = True

    grid = CavityGrid(nx=nx, ny=ny, cell_size=0.005, cells=cells)
    gates = [GateSpec(row=4, col=0), GateSpec(row=5, col=0)]
    vents = [VentSpec(row=r, col=nx - 1) for r in range(3, ny)]
    return grid, gates, vents


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def default_mat() -> MaterialProps:
    return MaterialProps(viscosity_pa_s=0.1, thickness_m=2e-3, injection_pressure_pa=1.5e7)


@pytest.fixture(scope="module")
def t_grid() -> CavityGrid:
    """T-shaped cavity: crossbar 16 wide × 4 high, stem 4 wide × 8 tall."""
    return make_t_cavity(stem_height=8, bar_width=16, bar_height=4, stem_width=4)


@pytest.fixture(scope="module")
def t_result(t_grid, default_mat) -> dict[str, Any]:
    """Two gates at each end of the crossbar → weld at centre."""
    ny, nx = t_grid.ny, t_grid.nx
    bar_height = 4
    # Leftmost and rightmost cells of the crossbar (row 2 is interior crossbar)
    gate_left = GateSpec(row=bar_height // 2, col=0)
    gate_right = GateSpec(row=bar_height // 2, col=nx - 1)
    return weld_air_analysis(
        cavity_grid=t_grid,
        gates=[gate_left, gate_right],
        vents=None,
        material_props=default_mat,
        n_steps=2000,
        cfl=0.4,
    )


@pytest.fixture(scope="module")
def donut_grid() -> CavityGrid:
    """Enclosed donut cavity (ring not touching grid boundary).

    outer_r=7, inner_r=3, margin=1 → 17×17 grid, 120 ring cells.
    Gate: leftmost ring cell in middle row.
    No explicit vents → farthest-cell fallback (rightmost ring cell).
    Flow must wrap around both arcs; far side becomes enclosed air trap.
    """
    return make_donut_cavity(outer_r=7, inner_r=3, margin=1)


@pytest.fixture(scope="module")
def donut_result(donut_grid, default_mat) -> dict[str, Any]:
    """Enclosed donut: gate on left, no explicit vents → air trap on right."""
    ny, nx = donut_grid.ny, donut_grid.nx
    mid_row = ny // 2
    # Find leftmost cavity cell in middle row
    for c in range(nx):
        if donut_grid.cells[mid_row, c]:
            gate_col = c
            break
    return weld_air_analysis(
        cavity_grid=donut_grid,
        gates=[GateSpec(row=mid_row, col=gate_col)],
        vents=[],  # no explicit vents; farthest-cell fallback applies
        material_props=default_mat,
        n_steps=5000,
        cfl=0.6,
    )


@pytest.fixture(scope="module")
def pocket_result(default_mat) -> dict[str, Any]:
    """Pocket cavity: flow fills main channel, traps air in dead-end pocket."""
    grid, gates, vents = _make_pocket_cavity()
    return weld_air_analysis(
        cavity_grid=grid,
        gates=gates,
        vents=vents,
        material_props=default_mat,
        n_steps=2000,
        cfl=0.4,
    )


# ---------------------------------------------------------------------------
# Oracle 1: T-shape weld line at crossbar centre
# ---------------------------------------------------------------------------

class TestTShapeWeldLine:
    """Two-gate T-cavity: gates at each end of the crossbar, weld at centre."""

    def test_weld_lines_detected(self, t_result):
        """At least one weld line must be detected."""
        assert len(t_result["weld_lines"]) > 0, (
            "No weld lines detected — expected meeting of two branch fronts "
            "near the centre of the crossbar."
        )

    def test_weld_near_crossbar_centre(self, t_result, t_grid):
        """At least one weld line should lie in the central 80% of bar width."""
        dx = t_grid.cell_size
        bar_width = 16   # cells
        bar_height = 4   # cells
        y_bar_max = bar_height * dx   # crossbar rows have y ≤ y_bar_max

        crossbar_welds = [wl for wl in t_result["weld_lines"] if wl[1] <= y_bar_max]
        assert len(crossbar_welds) > 0, (
            f"No weld lines in crossbar region (y ≤ {y_bar_max:.4f} m). "
            f"All weld lines: {t_result['weld_lines']}"
        )

        x_lo = 0.10 * bar_width * dx
        x_hi = 0.90 * bar_width * dx
        central_welds = [wl for wl in crossbar_welds if x_lo < wl[0] < x_hi]
        assert len(central_welds) > 0, (
            f"Crossbar welds found ({len(crossbar_welds)}) but none in central "
            f"80% of width (x ∈ [{x_lo:.4f}, {x_hi:.4f}] m). "
            f"Crossbar welds: {crossbar_welds}"
        )

    def test_fill_fraction_positive(self, t_result):
        assert t_result["fill_fraction"] > 0.3, (
            f"T-cavity fill too low: {t_result['fill_fraction']:.3f}"
        )

    def test_fill_time_positive(self, t_result):
        assert t_result["fill_time"] > 0.0

    def test_max_pressure_positive(self, t_result):
        assert t_result["max_pressure"] > 0.0


# ---------------------------------------------------------------------------
# Oracle 2: Donut cavity air trap on far side
# ---------------------------------------------------------------------------

class TestDonutAirTrap:
    """Enclosed donut: single gate on left, flow wraps around ring, traps air on far side."""

    def test_air_trap_detected(self, donut_result):
        """At least one air trap must be detected."""
        assert len(donut_result["air_traps"]) > 0, (
            "No air traps detected in donut cavity — expected far-side ring cells "
            "to form an enclosed unfilled region."
        )

    def test_air_trap_on_far_side(self, donut_result, donut_grid):
        """Air trap centroid should be on the right half of the grid (far from gate).

        Gate is at the leftmost ring cell, so far side is x > nx/2 * cell_size.
        """
        nx = donut_grid.nx
        dx = donut_grid.cell_size
        centre_x = (nx // 2) * dx
        far_traps = [t for t in donut_result["air_traps"] if t[0] >= centre_x]
        assert len(far_traps) > 0, (
            f"Air traps found ({len(donut_result['air_traps'])}) but none on far "
            f"side (x >= {centre_x:.4f} m). All traps: {donut_result['air_traps']}"
        )

    def test_fill_fraction_positive(self, donut_result):
        assert donut_result["fill_fraction"] > 0.2, (
            f"Donut fill fraction too low: {donut_result['fill_fraction']:.3f}"
        )

    def test_fill_time_positive(self, donut_result):
        assert donut_result["fill_time"] > 0.0


# ---------------------------------------------------------------------------
# Oracle 3: Simple rectangle — no traps, no welds
# ---------------------------------------------------------------------------

class TestRectangleSingleGate:
    """A simple rectangle with a single gate and no re-entrant geometry
    should fill without air traps and without weld lines (single branch)."""

    def test_rectangle_no_air_traps(self, default_mat):
        ny, nx = 6, 12
        cells = np.ones((ny, nx), dtype=bool)
        grid = CavityGrid(nx=nx, ny=ny, cell_size=0.005, cells=cells)
        gate = GateSpec(row=ny // 2, col=0)
        # Vent at right wall
        vents = [VentSpec(row=r, col=nx - 1) for r in range(ny)]
        result = weld_air_analysis(
            cavity_grid=grid,
            gates=[gate],
            vents=vents,
            material_props=default_mat,
            n_steps=200,
        )
        assert result["fill_fraction"] > 0.3, (
            f"Rectangle did not fill well: {result['fill_fraction']:.3f}"
        )
        assert len(result["air_traps"]) == 0, (
            f"Unexpected air traps in simple rectangle: {result['air_traps']}"
        )

    def test_rectangle_fills_from_left_to_right(self, default_mat):
        """Verify fill produces positive fill time and makes progress."""
        ny, nx = 4, 10
        cells = np.ones((ny, nx), dtype=bool)
        grid = CavityGrid(nx=nx, ny=ny, cell_size=0.005, cells=cells)
        gate = GateSpec(row=ny // 2, col=0)
        result = weld_air_analysis(
            cavity_grid=grid,
            gates=[gate],
            vents=None,
            material_props=default_mat,
            n_steps=500,
        )
        assert result["fill_time"] > 0
        assert result["fill_fraction"] > 0.1


# ---------------------------------------------------------------------------
# Oracle 4: Dict API (LLM tool code path)
# ---------------------------------------------------------------------------

class TestDictAPI:
    """Ensure weld_air_analysis accepts plain dict inputs (LLM tool path)."""

    def test_dict_inputs_work(self):
        ny, nx = 8, 16
        cavity_dict = {
            "nx": nx,
            "ny": ny,
            "cell_size_m": 0.005,
            "cells": np.ones((ny, nx), dtype=bool).tolist(),
        }
        gates_list = [{"row": ny // 2, "col": 0, "pressure_pa": 1.5e7}]
        mat_dict = {
            "viscosity_pa_s": 0.1,
            "thickness_m": 2e-3,
            "injection_pressure_pa": 1.5e7,
        }
        result = weld_air_analysis(
            cavity_grid=cavity_dict,
            gates=gates_list,
            vents=None,
            material_props=mat_dict,
            n_steps=100,
        )
        assert isinstance(result, dict)
        assert "weld_lines" in result
        assert "air_traps" in result
        assert "fill_time" in result
        assert "max_pressure" in result
        assert "fill_fraction" in result
        assert result["fill_time"] > 0
        assert result["max_pressure"] > 0

    def test_vent_dict_input(self):
        ny, nx = 4, 8
        cells = np.ones((ny, nx), dtype=bool).tolist()
        result = weld_air_analysis(
            cavity_grid={"nx": nx, "ny": ny, "cell_size_m": 0.005, "cells": cells},
            gates=[{"row": 2, "col": 0}],
            vents=[{"row": r, "col": nx - 1} for r in range(ny)],
            material_props={"viscosity_pa_s": 0.1, "thickness_m": 2e-3},
            n_steps=100,
        )
        assert isinstance(result["weld_lines"], list)
        assert isinstance(result["air_traps"], list)


# ---------------------------------------------------------------------------
# Oracle 5: CavityGrid validation
# ---------------------------------------------------------------------------

class TestCavityGridValidation:
    def test_shape_mismatch_raises(self):
        with pytest.raises(ValueError, match="does not match"):
            CavityGrid(nx=5, ny=3, cell_size=0.01, cells=np.ones((4, 5), dtype=bool))

    def test_correct_shape_ok(self):
        g = CavityGrid(nx=4, ny=3, cell_size=0.01, cells=np.ones((3, 4), dtype=bool))
        assert g.nx == 4
        assert g.ny == 3

    def test_from_dict(self):
        d = {"nx": 3, "ny": 2, "cell_size_m": 0.01, "cells": [[True, True, True], [True, True, True]]}
        g = CavityGrid.from_dict(d)
        assert g.cells.shape == (2, 3)


# ---------------------------------------------------------------------------
# Oracle 6: TOOL_SPEC schema
# ---------------------------------------------------------------------------

class TestToolSpec:
    def test_tool_spec_present(self):
        assert TOOL_SPEC is not None
        assert isinstance(TOOL_SPEC, dict)

    def test_tool_spec_has_name(self):
        assert TOOL_SPEC.get("name") == "moldflow_weld_air_analysis"

    def test_tool_spec_has_input_schema(self):
        assert "input_schema" in TOOL_SPEC
        schema = TOOL_SPEC["input_schema"]
        assert schema.get("type") == "object"
        assert "cavity_grid" in schema["properties"]
        assert "gates" in schema["properties"]
        assert "material_props" in schema["properties"]

    def test_tool_spec_description_non_empty(self):
        assert len(TOOL_SPEC.get("description", "")) > 20


# ---------------------------------------------------------------------------
# Oracle 7: Direct air-trap detection unit test
# ---------------------------------------------------------------------------

class TestAirTrapDirect:
    """Unit-test _detect_air_traps with manually constructed fill arrays."""

    def test_enclosed_region_is_trap(self):
        """3×3 inner unfilled region surrounded by filled cells = air trap."""
        from kerf_manufacturing.moldflow.flow_front import _detect_air_traps
        ny, nx = 7, 7
        cells = np.ones((ny, nx), dtype=bool)
        phi = np.ones((ny, nx))
        phi[2:5, 2:5] = 0.0   # inner 3×3 unfilled, no vent path

        # Vent on top/left/bottom boundary only
        vent_mask = np.zeros((ny, nx), dtype=bool)
        vent_mask[0, :] = True
        vent_mask[-1, :] = True
        vent_mask[:, 0] = True

        traps = _detect_air_traps(phi, cells, vent_mask, threshold=0.99)
        assert len(traps) == 9, f"Expected 9 trap cells, got {len(traps)}: {traps}"

    def test_boundary_connected_is_not_trap(self):
        """Unfilled cells connected to boundary are not air traps."""
        from kerf_manufacturing.moldflow.flow_front import _detect_air_traps
        ny, nx = 5, 5
        cells = np.ones((ny, nx), dtype=bool)
        phi = np.ones((ny, nx))
        phi[:, 4] = 0.0   # right column unfilled, but IS on boundary

        vent_mask = np.zeros((ny, nx), dtype=bool)
        traps = _detect_air_traps(phi, cells, vent_mask, threshold=0.99)
        # Right column cells are on the grid boundary → not traps
        assert len(traps) == 0, f"Expected 0 traps, got {len(traps)}: {traps}"

    def test_empty_cavity_no_traps(self):
        """All-filled cavity has no air traps."""
        from kerf_manufacturing.moldflow.flow_front import _detect_air_traps
        cells = np.ones((4, 4), dtype=bool)
        phi = np.ones((4, 4))
        vent_mask = np.zeros((4, 4), dtype=bool)
        traps = _detect_air_traps(phi, cells, vent_mask, threshold=0.99)
        assert traps == []


# ---------------------------------------------------------------------------
# Oracle 8: MaterialProps fluidity
# ---------------------------------------------------------------------------

class TestMaterialProps:
    def test_fluidity_positive(self):
        mat = MaterialProps(viscosity_pa_s=0.1, thickness_m=2e-3)
        assert mat.fluidity > 0

    def test_fluidity_formula(self):
        mat = MaterialProps(viscosity_pa_s=0.5, thickness_m=3e-3)
        expected = (3e-3) ** 3 / (12.0 * 0.5)
        assert math.isclose(mat.fluidity, expected, rel_tol=1e-9)

    def test_from_dict(self):
        mat = MaterialProps.from_dict({"viscosity_pa_s": 0.2, "thickness_m": 1e-3})
        assert mat.viscosity_pa_s == pytest.approx(0.2)
        assert mat.thickness_m == pytest.approx(1e-3)
        assert mat.injection_pressure_pa == pytest.approx(1.5e7)
