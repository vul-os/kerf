"""Tests for kerf_cad_core.composites.laser_projection — laser projection template export."""
from __future__ import annotations

import pytest

from kerf_cad_core.composites.afp_atl_path import CompositePlyDef
from kerf_cad_core.composites.laser_projection import (
    LaserProjectorSpec,
    LaserProjectionFile,
    generate_laser_projection,
    export_virtek_als,
    export_aligned_vision_hfl,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _flat_square_ply(ply_id: str = "PLY-001", orientation: float = 0.0) -> CompositePlyDef:
    return CompositePlyDef(
        ply_id=ply_id,
        ply_orientation_deg=orientation,
        material="AS4/3501-6",
        thickness_mm=0.125,
        boundary_3d=[
            (0.0, 0.0, 0.0),
            (1.0, 0.0, 0.0),
            (1.0, 0.5, 0.0),
            (0.0, 0.5, 0.0),
        ],
    )


def _overhead_projector() -> LaserProjectorSpec:
    """Projector mounted 3 m above the mold, pointing straight down."""
    return LaserProjectorSpec(
        name="Virtek IRIS 5D",
        position=(0.5, 0.25, 3.0),
        aim_direction=(0.0, 0.0, -1.0),
        fov_deg=(30.0, 20.0),
        range_m=4.0,
    )


# ---------------------------------------------------------------------------
# Test: generate_laser_projection basic
# ---------------------------------------------------------------------------

def test_generate_returns_laser_projection_file():
    plies = [_flat_square_ply()]
    projector = _overhead_projector()
    result = generate_laser_projection(plies, projector)
    assert isinstance(result, LaserProjectionFile)


def test_segment_count_matches_boundary():
    """A 4-vertex closed polygon should produce 4 segments."""
    plies = [_flat_square_ply()]
    projector = _overhead_projector()
    result = generate_laser_projection(plies, projector)
    # 4 boundary points → 4 closing segments
    assert len(result.template_segments) == 4


def test_multiple_plies_segment_count():
    """Two 4-vertex plies → 8 segments total."""
    plies = [_flat_square_ply("P1", 0.0), _flat_square_ply("P2", 45.0)]
    projector = _overhead_projector()
    result = generate_laser_projection(plies, projector)
    assert len(result.template_segments) == 8


def test_empty_plies_raises():
    projector = _overhead_projector()
    with pytest.raises(ValueError, match="plies"):
        generate_laser_projection([], projector)


# ---------------------------------------------------------------------------
# Test: Virtek ALS XML output
# ---------------------------------------------------------------------------

def test_virtek_als_starts_with_xml_declaration():
    """Virtek ALS output must start with XML declaration (<?xml ...)."""
    plies = [_flat_square_ply()]
    projector = _overhead_projector()
    proj_file = generate_laser_projection(plies, projector)
    xml_out = export_virtek_als(proj_file)
    assert xml_out.startswith('<?xml version="1.0"'), (
        f"XML should start with declaration, got: {xml_out[:50]}"
    )


def test_virtek_als_contains_laser_template_root():
    """ALS XML must contain LaserTemplate root element."""
    plies = [_flat_square_ply()]
    projector = _overhead_projector()
    proj_file = generate_laser_projection(plies, projector)
    xml_out = export_virtek_als(proj_file)
    assert "LaserTemplate" in xml_out


def test_virtek_als_contains_ply_template():
    """ALS XML must contain PlyTemplate element for each ply."""
    plies = [_flat_square_ply("PLY-007")]
    projector = _overhead_projector()
    proj_file = generate_laser_projection(plies, projector)
    xml_out = export_virtek_als(proj_file)
    assert "PLY-007" in xml_out


def test_virtek_als_contains_segment_element():
    """ALS XML must contain Segment elements."""
    plies = [_flat_square_ply()]
    projector = _overhead_projector()
    proj_file = generate_laser_projection(plies, projector)
    xml_out = export_virtek_als(proj_file)
    assert "Segment" in xml_out


# ---------------------------------------------------------------------------
# Test: Aligned Vision HFL output
# ---------------------------------------------------------------------------

def test_aligned_vision_hfl_is_string():
    plies = [_flat_square_ply()]
    projector = _overhead_projector()
    proj_file = generate_laser_projection(plies, projector)
    hfl = export_aligned_vision_hfl(proj_file)
    assert isinstance(hfl, str)
    assert len(hfl) > 0


def test_aligned_vision_hfl_has_header():
    """HFL output must have Aligned Vision header comment."""
    plies = [_flat_square_ply()]
    projector = _overhead_projector()
    proj_file = generate_laser_projection(plies, projector)
    hfl = export_aligned_vision_hfl(proj_file)
    assert "Aligned Vision" in hfl


def test_aligned_vision_hfl_semicolon_delimited():
    """HFL data lines must be semicolon-delimited."""
    plies = [_flat_square_ply("PLY-A")]
    projector = _overhead_projector()
    proj_file = generate_laser_projection(plies, projector)
    hfl = export_aligned_vision_hfl(proj_file)
    # Non-comment lines should contain semicolons
    data_lines = [l for l in hfl.splitlines() if not l.startswith("#") and l.strip()]
    assert all(";" in line for line in data_lines), (
        "All HFL data lines must be semicolon-delimited"
    )


def test_aligned_vision_hfl_contains_ply_id():
    plies = [_flat_square_ply("WING-PLY-42")]
    projector = _overhead_projector()
    proj_file = generate_laser_projection(plies, projector)
    hfl = export_aligned_vision_hfl(proj_file)
    assert "WING-PLY-42" in hfl


# ---------------------------------------------------------------------------
# Test: projector projections are finite
# ---------------------------------------------------------------------------

def test_segment_3d_coords_are_finite():
    """All segment start/end coordinates must be finite."""
    plies = [_flat_square_ply()]
    projector = _overhead_projector()
    proj_file = generate_laser_projection(plies, projector)
    import math
    for seg in proj_file.template_segments:
        for coord in seg["start_3d"] + seg["end_3d"]:
            assert math.isfinite(coord), f"Non-finite coordinate: {coord}"
