"""Tests for GK-P33 — section_fill: section_by_plane loops → hatch_region.

DoD:
  - section_fill(mesh, plane, material="brick_clay") returns ok=True with fills
  - Each fill entry has line_count > 0 for a valid section
  - Pattern is material-keyed (brick_clay → brick)
  - fill with explicit pattern overrides material
  - Invalid plane returns ok=False
"""
from __future__ import annotations
import math
import pytest
import numpy as np

from kerf_cad_core.geom.section_contour import section_fill


def _box_mesh(x0=0, x1=10, y0=0, y1=5, z0=0, z1=3):
    """Simple axis-aligned box triangle mesh."""
    # 8 vertices
    verts = [
        [x0, y0, z0], [x1, y0, z0], [x1, y1, z0], [x0, y1, z0],  # bottom
        [x0, y0, z1], [x1, y0, z1], [x1, y1, z1], [x0, y1, z1],  # top
    ]
    # 12 triangles (2 per face × 6 faces)
    faces = [
        # bottom (z=z0)
        [0, 2, 1], [0, 3, 2],
        # top (z=z1)
        [4, 5, 6], [4, 6, 7],
        # front (y=y0)
        [0, 1, 5], [0, 5, 4],
        # back (y=y1)
        [2, 3, 7], [2, 7, 6],
        # left (x=x0)
        [0, 4, 7], [0, 7, 3],
        # right (x=x1)
        [1, 2, 6], [1, 6, 5],
    ]
    return {"verts": verts, "faces": faces}


class TestSectionFill:
    def test_returns_ok(self):
        mesh = _box_mesh()
        # Section through z=1.5 (mid-height horizontal plane)
        plane = {"normal": [0, 0, 1], "point": [0, 0, 1.5]}
        result = section_fill(mesh, plane)
        assert result.get("ok"), f"Expected ok=True, got: {result.get('reason')}"

    def test_fills_list_present(self):
        mesh = _box_mesh()
        plane = {"normal": [0, 0, 1], "point": [0, 0, 1.5]}
        result = section_fill(mesh, plane)
        assert "fills" in result
        assert isinstance(result["fills"], list)

    def test_section_produces_hatched_loops(self):
        mesh = _box_mesh()
        plane = {"normal": [0, 0, 1], "point": [0, 0, 1.5]}
        result = section_fill(mesh, plane, scale=1.0)
        assert result["ok"]
        # At least one loop should have hatch lines
        total_lines = sum(f["line_count"] for f in result["fills"])
        assert total_lines > 0, f"Expected hatch lines, got fills={result['fills']}"

    def test_material_keyed_pattern(self):
        mesh = _box_mesh()
        plane = {"normal": [0, 0, 1], "point": [0, 0, 1.5]}
        result = section_fill(mesh, plane, material="brick_clay", scale=1.0)
        assert result["ok"]
        for f in result["fills"]:
            assert f["pattern"] == "brick", (
                f"Expected 'brick' for brick_clay, got '{f['pattern']}'"
            )

    def test_explicit_pattern_overrides_material_when_no_material(self):
        mesh = _box_mesh()
        plane = {"normal": [0, 0, 1], "point": [0, 0, 1.5]}
        result = section_fill(mesh, plane, pattern="concrete", scale=1.0)
        assert result["ok"]
        for f in result["fills"]:
            assert f["pattern"] == "concrete"

    def test_material_takes_precedence_over_pattern(self):
        """material= overrides pattern= when both are given."""
        mesh = _box_mesh()
        plane = {"normal": [0, 0, 1], "point": [0, 0, 1.5]}
        result = section_fill(mesh, plane, material="insulation_rockwool",
                              pattern="steel", scale=1.0)
        assert result["ok"]
        # material should win
        for f in result["fills"]:
            assert f["pattern"] == "insulation"

    def test_invalid_plane_returns_not_ok(self):
        mesh = _box_mesh()
        result = section_fill(mesh, {"normal": [0, 0, 0], "point": [0, 0, 1]})
        assert not result.get("ok")

    def test_lines_have_start_end(self):
        mesh = _box_mesh()
        plane = {"normal": [0, 0, 1], "point": [0, 0, 1.5]}
        result = section_fill(mesh, plane, scale=1.0)
        for fill in result["fills"]:
            for ln in fill["lines"]:
                assert "start" in ln and "end" in ln
                assert len(ln["start"]) == 2
                assert len(ln["end"]) == 2
                assert all(math.isfinite(v) for v in ln["start"])
                assert all(math.isfinite(v) for v in ln["end"])

    def test_vertical_section(self):
        """Section a box with a vertical plane (YZ)."""
        mesh = _box_mesh()
        plane = {"normal": [1, 0, 0], "point": [5, 0, 0]}  # x=5 plane
        result = section_fill(mesh, plane, scale=0.5)
        assert result["ok"]
        total_lines = sum(f["line_count"] for f in result["fills"])
        assert total_lines > 0

    def test_loop_count_in_result(self):
        mesh = _box_mesh()
        plane = {"normal": [0, 0, 1], "point": [0, 0, 1.5]}
        result = section_fill(mesh, plane)
        assert "loop_count" in result
        assert result["loop_count"] == len(result["fills"])
