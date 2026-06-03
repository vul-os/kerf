"""Tests for kerf_cad_core.composites.afp_atl_path — AFP/ATL path generation."""
from __future__ import annotations

import math
import pytest

from kerf_cad_core.composites.afp_atl_path import (
    CompositePlyDef,
    AfpAtlMachineSpec,
    AfpAtlProgram,
    FiberPath,
    generate_afp_paths,
    export_apt_cl_file,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _unit_square_ply(orientation_deg: float = 0.0) -> CompositePlyDef:
    """1 m × 1 m square flat ply."""
    return CompositePlyDef(
        ply_id="PLY-001",
        ply_orientation_deg=orientation_deg,
        material="IM7/8552",
        thickness_mm=0.125,
        boundary_3d=[
            (0.0, 0.0, 0.0),
            (1.0, 0.0, 0.0),
            (1.0, 1.0, 0.0),
            (0.0, 1.0, 0.0),
        ],
    )


def _half_inch_machine() -> AfpAtlMachineSpec:
    """Standard half-inch (12.7 mm) single-head AFP machine."""
    return AfpAtlMachineSpec(
        name="Coriolis C1",
        tape_width_mm=12.7,
        head_count=1,
        max_lay_rate_m_per_min=30.0,
    )


def _std_machine() -> AfpAtlMachineSpec:
    """12.7 mm tape, 1 head."""
    return AfpAtlMachineSpec(
        name="Electroimpact AFP",
        tape_width_mm=12.7,
        head_count=1,
        max_lay_rate_m_per_min=40.0,
    )


# ---------------------------------------------------------------------------
# Test: path count on 1 m² ply with 12.7 mm tape
# ---------------------------------------------------------------------------

def test_path_count_approx_79():
    """A 1 m × 1 m ply with 12.7 mm tape should produce ~79 parallel paths
    (1000 mm / 12.7 mm ≈ 78.7, rounded up to 79)."""
    ply = _unit_square_ply(orientation_deg=0.0)
    machine = _std_machine()
    program = generate_afp_paths(ply, machine)
    # Allow ±2 paths tolerance for boundary clipping alignment
    assert 77 <= len(program.paths) <= 81, (
        f"Expected ~79 paths, got {len(program.paths)}"
    )


# ---------------------------------------------------------------------------
# Test: total_length scales with ply area / tape width
# ---------------------------------------------------------------------------

def test_total_length_scales_with_area():
    """total_length_m should scale roughly as ply_area / tape_width × mean_path_length."""
    machine = _std_machine()

    ply_1x1 = CompositePlyDef(
        ply_id="P1",
        ply_orientation_deg=0.0,
        material="IM7/8552",
        thickness_mm=0.125,
        boundary_3d=[(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (1.0, 1.0, 0.0), (0.0, 1.0, 0.0)],
    )
    ply_2x1 = CompositePlyDef(
        ply_id="P2",
        ply_orientation_deg=0.0,
        material="IM7/8552",
        thickness_mm=0.125,
        boundary_3d=[(0.0, 0.0, 0.0), (2.0, 0.0, 0.0), (2.0, 1.0, 0.0), (0.0, 1.0, 0.0)],
    )

    prog1 = generate_afp_paths(ply_1x1, machine)
    prog2 = generate_afp_paths(ply_2x1, machine)

    # 2x width ply should have roughly 2× total length
    ratio = prog2.total_length_m / prog1.total_length_m
    assert 1.7 < ratio < 2.3, f"Length ratio expected ~2, got {ratio:.3f}"


# ---------------------------------------------------------------------------
# Test: path orientation matches ply orientation
# ---------------------------------------------------------------------------

def test_path_orientation_matches_ply():
    """Each FiberPath's orientation_at_points should align with ply_orientation_deg."""
    ply = _unit_square_ply(orientation_deg=45.0)
    machine = _half_inch_machine()
    program = generate_afp_paths(ply, machine)

    expected_dx = math.cos(math.radians(45.0))
    expected_dy = math.sin(math.radians(45.0))

    for path in program.paths[:5]:  # check first 5
        for (ox, oy, oz) in path.orientation_at_points:
            assert abs(ox - expected_dx) < 1e-6, f"ox mismatch: {ox}"
            assert abs(oy - expected_dy) < 1e-6, f"oy mismatch: {oy}"
            assert abs(oz) < 1e-6, f"oz should be 0, got {oz}"


def test_path_orientation_zero_degrees():
    """0° orientation → tape tangent = (1, 0, 0)."""
    ply = _unit_square_ply(orientation_deg=0.0)
    machine = _half_inch_machine()
    program = generate_afp_paths(ply, machine)
    assert program.paths, "Should have at least one path"
    for (ox, oy, oz) in program.paths[0].orientation_at_points:
        assert abs(ox - 1.0) < 1e-6
        assert abs(oy) < 1e-6


def test_path_orientation_90_degrees():
    """90° orientation → tape tangent = (0, 1, 0)."""
    ply = _unit_square_ply(orientation_deg=90.0)
    machine = _half_inch_machine()
    program = generate_afp_paths(ply, machine)
    assert program.paths, "Should have at least one path"
    for (ox, oy, oz) in program.paths[0].orientation_at_points:
        assert abs(ox) < 1e-6
        assert abs(oy - 1.0) < 1e-6


# ---------------------------------------------------------------------------
# Test: coverage and waste percentages
# ---------------------------------------------------------------------------

def test_coverage_pct_reasonable():
    """Coverage should be between 50% and 100% for a solid ply."""
    ply = _unit_square_ply()
    machine = _half_inch_machine()
    program = generate_afp_paths(ply, machine)
    assert 50.0 <= program.coverage_pct <= 100.0, (
        f"coverage_pct out of range: {program.coverage_pct}"
    )


def test_waste_pct_non_negative():
    """Waste percentage must be >= 0."""
    ply = _unit_square_ply()
    machine = _half_inch_machine()
    program = generate_afp_paths(ply, machine)
    assert program.waste_pct >= 0.0


# ---------------------------------------------------------------------------
# Test: estimated_time_min is positive
# ---------------------------------------------------------------------------

def test_estimated_time_positive():
    ply = _unit_square_ply()
    machine = _half_inch_machine()
    program = generate_afp_paths(ply, machine)
    assert program.estimated_time_min > 0.0


# ---------------------------------------------------------------------------
# Test: export_apt_cl_file contains GOTO commands
# ---------------------------------------------------------------------------

def test_apt_cl_contains_goto():
    """APT CL output must contain GOTO commands (AIA NAS 9300 standard)."""
    ply = _unit_square_ply()
    machine = _half_inch_machine()
    program = generate_afp_paths(ply, machine)
    cl_text = export_apt_cl_file(program)
    assert "GOTO" in cl_text, "APT CL file must contain GOTO statements"


def test_apt_cl_contains_fini():
    """APT CL file must end with FINI statement."""
    ply = _unit_square_ply()
    machine = _half_inch_machine()
    program = generate_afp_paths(ply, machine)
    cl_text = export_apt_cl_file(program)
    assert cl_text.strip().endswith("FINI"), "APT CL file must end with FINI"


def test_apt_cl_contains_partno():
    """APT CL file must contain PARTNO header line."""
    ply = _unit_square_ply()
    machine = _half_inch_machine()
    program = generate_afp_paths(ply, machine)
    cl_text = export_apt_cl_file(program)
    assert "PARTNO" in cl_text


def test_apt_cl_contains_spindl():
    """APT CL file must contain SPINDL commands for head control."""
    ply = _unit_square_ply()
    machine = _half_inch_machine()
    program = generate_afp_paths(ply, machine)
    cl_text = export_apt_cl_file(program)
    assert "SPINDL" in cl_text


# ---------------------------------------------------------------------------
# Test: bad input raises ValueError
# ---------------------------------------------------------------------------

def test_invalid_tape_width_raises():
    ply = _unit_square_ply()
    bad_machine = AfpAtlMachineSpec("Test", tape_width_mm=0.0, head_count=1, max_lay_rate_m_per_min=30.0)
    with pytest.raises(ValueError, match="tape_width_mm"):
        generate_afp_paths(ply, bad_machine)


def test_invalid_boundary_raises():
    ply = CompositePlyDef("P", 0.0, "IM7", 0.125, [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0)])
    machine = _half_inch_machine()
    with pytest.raises(ValueError):
        generate_afp_paths(ply, machine)
