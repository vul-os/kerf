"""Tests for kerf_cad_core.composites.flat_pattern_export — flat pattern development + DXF."""
from __future__ import annotations

import math
import pytest

from kerf_cad_core.composites.afp_atl_path import CompositePlyDef
from kerf_cad_core.composites.flat_pattern_export import (
    FlatPatternResult,
    develop_ply_to_flat,
    export_flat_pattern_dxf,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _flat_square_ply() -> CompositePlyDef:
    """1 m × 1 m flat ply in the XY plane."""
    return CompositePlyDef(
        ply_id="PLY-FLAT",
        ply_orientation_deg=0.0,
        material="IM7/8552",
        thickness_mm=0.125,
        boundary_3d=[
            (0.0, 0.0, 0.0),
            (1.0, 0.0, 0.0),
            (1.0, 1.0, 0.0),
            (0.0, 1.0, 0.0),
        ],
    )


def _flat_rect_ply() -> CompositePlyDef:
    """2 m × 0.5 m flat rectangular ply, oriented at 45°."""
    return CompositePlyDef(
        ply_id="PLY-RECT",
        ply_orientation_deg=45.0,
        material="T300/5208",
        thickness_mm=0.15,
        boundary_3d=[
            (0.0, 0.0, 0.0),
            (2.0, 0.0, 0.0),
            (2.0, 0.5, 0.0),
            (0.0, 0.5, 0.0),
        ],
    )


def _triangle_ply() -> CompositePlyDef:
    """Triangular flat ply."""
    return CompositePlyDef(
        ply_id="PLY-TRI",
        ply_orientation_deg=90.0,
        material="AS4/3501-6",
        thickness_mm=0.125,
        boundary_3d=[
            (0.0, 0.0, 0.0),
            (1.0, 0.0, 0.0),
            (0.5, 0.866, 0.0),
        ],
    )


# ---------------------------------------------------------------------------
# Test: develop_ply_to_flat returns FlatPatternResult
# ---------------------------------------------------------------------------

def test_develop_returns_flat_pattern_result():
    ply = _flat_square_ply()
    result = develop_ply_to_flat(ply)
    assert isinstance(result, FlatPatternResult)
    assert result.ply_id == "PLY-FLAT"


def test_flat_boundary_has_correct_vertex_count():
    """Flat pattern should have same number of vertices as input boundary."""
    ply = _flat_square_ply()
    result = develop_ply_to_flat(ply)
    assert len(result.flat_boundary_2d) == 4


# ---------------------------------------------------------------------------
# Test: flat ply develops to equal shape (within tolerance)
# ---------------------------------------------------------------------------

def test_flat_ply_develops_to_same_shape():
    """A perfectly flat (planar) ply should develop to its own shape with zero distortion."""
    ply = _flat_square_ply()
    result = develop_ply_to_flat(ply)
    # Distortion should be ~ 0 for a flat ply
    assert result.distortion_max_mm < 1.0, (
        f"Flat ply distortion should be ~0 mm, got {result.distortion_max_mm:.4f} mm"
    )


def test_flat_ply_edge_lengths_preserved():
    """Edge lengths in the flat pattern should match 3-D edge lengths for a flat input."""
    ply = _flat_square_ply()
    result = develop_ply_to_flat(ply)
    flat = result.flat_boundary_2d
    n = len(flat)
    # All edges of the unit square should be ~1 m
    for i in range(n):
        x0, y0 = flat[i]
        x1, y1 = flat[(i + 1) % n]
        edge_len = math.sqrt((x1 - x0) ** 2 + (y1 - y0) ** 2)
        # Unit square has 4 edges of length 1 m
        assert 0.5 < edge_len < 1.5, f"Edge {i}: unexpected length {edge_len:.4f} m"


# ---------------------------------------------------------------------------
# Test: fiber direction
# ---------------------------------------------------------------------------

def test_fiber_direction_unit_vector():
    """fiber_direction_in_flat must be a unit vector."""
    ply = _flat_square_ply()
    result = develop_ply_to_flat(ply)
    fx, fy = result.fiber_direction_in_flat
    mag = math.sqrt(fx ** 2 + fy ** 2)
    assert abs(mag - 1.0) < 1e-6, f"Fiber direction should be unit vector, mag={mag}"


def test_fiber_direction_zero_degrees():
    """0° orientation → fiber direction should have fx ≈ 1, fy ≈ 0."""
    ply = _flat_square_ply()
    result = develop_ply_to_flat(ply)
    fx, fy = result.fiber_direction_in_flat
    assert abs(fx - 1.0) < 1e-6
    assert abs(fy) < 1e-6


def test_fiber_direction_45_degrees():
    """45° orientation → fiber direction fx ≈ fy ≈ 0.707."""
    ply = _flat_rect_ply()
    result = develop_ply_to_flat(ply)
    fx, fy = result.fiber_direction_in_flat
    assert abs(fx - math.cos(math.radians(45.0))) < 1e-6
    assert abs(fy - math.sin(math.radians(45.0))) < 1e-6


# ---------------------------------------------------------------------------
# Test: nesting_efficiency_pct in [0, 100]
# ---------------------------------------------------------------------------

def test_nesting_efficiency_in_range():
    """nesting_efficiency_pct must be in [0, 100]."""
    for ply in [_flat_square_ply(), _flat_rect_ply(), _triangle_ply()]:
        result = develop_ply_to_flat(ply)
        assert 0.0 <= result.nesting_efficiency_pct <= 100.0, (
            f"nesting_efficiency_pct out of range: {result.nesting_efficiency_pct}"
        )


def test_nesting_efficiency_square_high():
    """A square ply (best case) should have nesting efficiency close to 100%."""
    ply = _flat_square_ply()
    result = develop_ply_to_flat(ply)
    # Square fills its bounding box ~100%
    assert result.nesting_efficiency_pct > 90.0, (
        f"Square ply efficiency should be ~100%, got {result.nesting_efficiency_pct:.1f}%"
    )


def test_nesting_efficiency_triangle_lower():
    """A triangle ply should have lower nesting efficiency than a square."""
    sq_result = develop_ply_to_flat(_flat_square_ply())
    tri_result = develop_ply_to_flat(_triangle_ply())
    assert tri_result.nesting_efficiency_pct < sq_result.nesting_efficiency_pct


# ---------------------------------------------------------------------------
# Test: export_flat_pattern_dxf
# ---------------------------------------------------------------------------

def test_dxf_returns_string():
    ply = _flat_square_ply()
    result = develop_ply_to_flat(ply)
    dxf = export_flat_pattern_dxf(result)
    assert isinstance(dxf, str)


def test_dxf_contains_section():
    """DXF must contain SECTION keyword."""
    ply = _flat_square_ply()
    result = develop_ply_to_flat(ply)
    dxf = export_flat_pattern_dxf(result)
    assert "SECTION" in dxf, "DXF must contain SECTION"


def test_dxf_contains_entities():
    """DXF must contain ENTITIES section."""
    ply = _flat_square_ply()
    result = develop_ply_to_flat(ply)
    dxf = export_flat_pattern_dxf(result)
    assert "ENTITIES" in dxf, "DXF must contain ENTITIES section"


def test_dxf_contains_eof():
    """DXF must end with EOF marker."""
    ply = _flat_square_ply()
    result = develop_ply_to_flat(ply)
    dxf = export_flat_pattern_dxf(result)
    assert "EOF" in dxf, "DXF must contain EOF marker"


def test_dxf_contains_line_entities():
    """DXF must contain LINE entities for the boundary."""
    ply = _flat_square_ply()
    result = develop_ply_to_flat(ply)
    dxf = export_flat_pattern_dxf(result)
    assert "LINE" in dxf, "DXF must contain LINE entities"


def test_dxf_r12_version():
    """DXF must declare R12 (AC1009) version."""
    ply = _flat_square_ply()
    result = develop_ply_to_flat(ply)
    dxf = export_flat_pattern_dxf(result)
    assert "AC1009" in dxf, "DXF must declare R12 version (AC1009)"


# ---------------------------------------------------------------------------
# Test: bad input
# ---------------------------------------------------------------------------

def test_too_few_points_raises():
    ply = CompositePlyDef("P", 0.0, "IM7", 0.125, [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0)])
    with pytest.raises(ValueError):
        develop_ply_to_flat(ply)
