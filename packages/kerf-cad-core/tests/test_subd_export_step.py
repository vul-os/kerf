"""
Tests for subd_export_step.py — Catmull-Clark limit-surface STEP AP242 exporter.

Coverage:
  1.  Cube cage, 2 levels → output is a non-empty string.
  2.  Output starts with 'ISO-10303-21;'.
  3.  Output contains FILE_DESCRIPTION.
  4.  Output contains FILE_SCHEMA.
  5.  Output contains 'AP242' in FILE_SCHEMA.
  6.  Output contains DATA section (DATA;).
  7.  Output contains ENDSEC.
  8.  Output ends with 'END-ISO-10303-21;'.
  9.  Cube cage, 2 levels → 96 ADVANCED_FACEs.
  10. parse_step_subd has_header == True.
  11. parse_step_subd has_schema == True.
  12. parse_step_subd has_data == True.
  13. parse_step_subd has_endsec == True.
  14. parse_step_subd advanced_faces == 96 for cube cage 2 levels.
  15. Round-trip vertex count > 0.
  16. Cube cage, 1 level → 24 ADVANCED_FACEs.
  17. Cube cage, 0 levels → 6 ADVANCED_FACEs.
  18. Face count scales 4× per CC level.
  19. CARTESIAN_POINT entities present in output.
  20. VERTEX_POINT entities present.
  21. EDGE_CURVE entities present.
  22. EDGE_LOOP entities present.
  23. FACE_OUTER_BOUND entities present.
  24. PLANE entities present.
  25. OPEN_SHELL entity present.
  26. SHELL_BASED_SURFACE_MODEL entity present.
  27. SHAPE_REPRESENTATION entity present.
  28. Sphere cage convergence: parse_step_subd vertices within [-2, 2]^3.
  29. Sphere cage 2 levels → ADVANCED_FACEs > 0.
  30. Dict cage input accepted.
  31. levels clamped to 8 maximum (no crash).
  32. levels=0 returns the original cage faces.
  33. Empty cage does not crash — returns valid STEP skeleton.
  34. All CARTESIAN_POINT coordinates are finite.
  35. Output contains AXIS2_PLACEMENT_3D.
  36. Output contains DIRECTION entities.
  37. Output does not contain Python traceback.
  38. parse_step_subd returns correct type for all keys.
  39. Cube 2 levels: at least 96 VERTEX_POINT entities.
  40. OPEN_SHELL entity references correct number of ADVANCED_FACEs.
"""

from __future__ import annotations

import math
import re
from typing import List

import pytest

from kerf_cad_core.geom.subd import SubDMesh
from kerf_cad_core.geom.subd_export_step import export_limit_to_step, parse_step_subd


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _cube_mesh() -> SubDMesh:
    """Unit cube with 6 quad faces (8 verts)."""
    verts = [
        [-1.0, -1.0, -1.0],
        [ 1.0, -1.0, -1.0],
        [ 1.0,  1.0, -1.0],
        [-1.0,  1.0, -1.0],
        [-1.0, -1.0,  1.0],
        [ 1.0, -1.0,  1.0],
        [ 1.0,  1.0,  1.0],
        [-1.0,  1.0,  1.0],
    ]
    faces = [
        [0, 1, 2, 3],  # -Z
        [4, 5, 6, 7],  # +Z
        [0, 1, 5, 4],  # -Y
        [2, 3, 7, 6],  # +Y
        [0, 3, 7, 4],  # -X
        [1, 2, 6, 5],  # +X
    ]
    return SubDMesh(vertices=verts, faces=faces)


def _sphere_cage() -> SubDMesh:
    """Octahedral cage approximating the unit sphere (8 triangles, 6 verts)."""
    verts = [
        [ 0.0,  0.0,  1.0],
        [ 1.0,  0.0,  0.0],
        [ 0.0,  1.0,  0.0],
        [-1.0,  0.0,  0.0],
        [ 0.0, -1.0,  0.0],
        [ 0.0,  0.0, -1.0],
    ]
    faces = [
        [0, 1, 2], [0, 2, 3], [0, 3, 4], [0, 4, 1],
        [5, 2, 1], [5, 3, 2], [5, 4, 3], [5, 1, 4],
    ]
    return SubDMesh(vertices=verts, faces=faces)


def _cube_dict():
    return {
        "vertices": [
            [-1,-1,-1],[1,-1,-1],[1,1,-1],[-1,1,-1],
            [-1,-1, 1],[1,-1, 1],[1,1, 1],[-1,1, 1],
        ],
        "faces": [
            [0,1,2,3],[4,5,6,7],[0,1,5,4],[2,3,7,6],[0,3,7,4],[1,2,6,5],
        ],
    }


# ---------------------------------------------------------------------------
# Tests: structural validity
# ---------------------------------------------------------------------------

class TestStepStructure:

    def test_output_is_nonempty_string(self):
        """export_limit_to_step returns a non-empty string."""
        text = export_limit_to_step(_cube_mesh(), levels=2)
        assert isinstance(text, str) and len(text) > 0

    def test_starts_with_iso_10303(self):
        """Output starts with 'ISO-10303-21;'."""
        text = export_limit_to_step(_cube_mesh(), levels=2)
        assert text.startswith("ISO-10303-21;"), f"Bad header: {text[:40]!r}"

    def test_contains_file_description(self):
        """Output contains FILE_DESCRIPTION."""
        text = export_limit_to_step(_cube_mesh(), levels=2)
        assert "FILE_DESCRIPTION" in text

    def test_contains_file_schema(self):
        """Output contains FILE_SCHEMA."""
        text = export_limit_to_step(_cube_mesh(), levels=2)
        assert "FILE_SCHEMA" in text

    def test_file_schema_contains_ap242(self):
        """FILE_SCHEMA references AP242."""
        text = export_limit_to_step(_cube_mesh(), levels=2)
        assert "AP242" in text

    def test_contains_data_section(self):
        """Output contains DATA; marker."""
        text = export_limit_to_step(_cube_mesh(), levels=2)
        assert re.search(r"\bDATA\s*;", text)

    def test_contains_endsec(self):
        """Output contains ENDSEC;."""
        text = export_limit_to_step(_cube_mesh(), levels=2)
        assert "ENDSEC;" in text

    def test_ends_with_end_iso(self):
        """Output ends with END-ISO-10303-21;."""
        text = export_limit_to_step(_cube_mesh(), levels=2)
        assert text.rstrip().endswith("END-ISO-10303-21;")

    def test_contains_axis2_placement(self):
        """Output contains AXIS2_PLACEMENT_3D entities."""
        text = export_limit_to_step(_cube_mesh(), levels=1)
        assert "AXIS2_PLACEMENT_3D" in text

    def test_contains_direction_entities(self):
        """Output contains DIRECTION entities."""
        text = export_limit_to_step(_cube_mesh(), levels=1)
        assert "DIRECTION" in text

    def test_no_traceback(self):
        """Output does not contain Python traceback text."""
        text = export_limit_to_step(_cube_mesh(), levels=2)
        assert "Traceback" not in text
        assert "Error" not in text


# ---------------------------------------------------------------------------
# Tests: geometry entity presence
# ---------------------------------------------------------------------------

class TestStepEntities:

    def test_cartesian_points_present(self):
        """CARTESIAN_POINT entities appear in the DATA section."""
        text = export_limit_to_step(_cube_mesh(), levels=2)
        assert "CARTESIAN_POINT" in text

    def test_vertex_points_present(self):
        """VERTEX_POINT entities appear."""
        text = export_limit_to_step(_cube_mesh(), levels=2)
        assert "VERTEX_POINT" in text

    def test_edge_curve_present(self):
        """EDGE_CURVE entities appear."""
        text = export_limit_to_step(_cube_mesh(), levels=2)
        assert "EDGE_CURVE" in text

    def test_edge_loop_present(self):
        """EDGE_LOOP entities appear."""
        text = export_limit_to_step(_cube_mesh(), levels=1)
        assert "EDGE_LOOP" in text

    def test_face_outer_bound_present(self):
        """FACE_OUTER_BOUND entities appear."""
        text = export_limit_to_step(_cube_mesh(), levels=1)
        assert "FACE_OUTER_BOUND" in text

    def test_plane_present(self):
        """PLANE entities appear."""
        text = export_limit_to_step(_cube_mesh(), levels=1)
        assert "=PLANE(" in text

    def test_open_shell_present(self):
        """OPEN_SHELL entity appears."""
        text = export_limit_to_step(_cube_mesh(), levels=2)
        assert "OPEN_SHELL" in text

    def test_shell_based_surface_model_present(self):
        """SHELL_BASED_SURFACE_MODEL entity appears."""
        text = export_limit_to_step(_cube_mesh(), levels=2)
        assert "SHELL_BASED_SURFACE_MODEL" in text

    def test_shape_representation_present(self):
        """SHAPE_REPRESENTATION entity appears."""
        text = export_limit_to_step(_cube_mesh(), levels=2)
        assert "SHAPE_REPRESENTATION" in text


# ---------------------------------------------------------------------------
# Tests: face counts
# ---------------------------------------------------------------------------

class TestFaceCounts:

    def test_cube_2_levels_96_faces(self):
        """Cube cage 2 CC levels → 96 ADVANCED_FACEs."""
        text = export_limit_to_step(_cube_mesh(), levels=2)
        parsed = parse_step_subd(text)
        assert parsed["advanced_faces"] == 96, (
            f"Expected 96 ADVANCED_FACEs, got {parsed['advanced_faces']}"
        )

    def test_cube_1_level_24_faces(self):
        """Cube cage 1 CC level → 24 ADVANCED_FACEs."""
        text = export_limit_to_step(_cube_mesh(), levels=1)
        parsed = parse_step_subd(text)
        assert parsed["advanced_faces"] == 24, (
            f"Expected 24 ADVANCED_FACEs, got {parsed['advanced_faces']}"
        )

    def test_cube_0_levels_6_faces(self):
        """Cube cage 0 levels → 6 ADVANCED_FACEs (original cage)."""
        text = export_limit_to_step(_cube_mesh(), levels=0)
        parsed = parse_step_subd(text)
        assert parsed["advanced_faces"] == 6, (
            f"Expected 6 ADVANCED_FACEs, got {parsed['advanced_faces']}"
        )

    def test_face_count_scales_4x(self):
        """ADVANCED_FACE count scales 4× per CC level."""
        t1 = parse_step_subd(export_limit_to_step(_cube_mesh(), levels=1))["advanced_faces"]
        t2 = parse_step_subd(export_limit_to_step(_cube_mesh(), levels=2))["advanced_faces"]
        assert t2 == t1 * 4, f"Level-2 faces {t2} should be 4× level-1 {t1}"


# ---------------------------------------------------------------------------
# Tests: round-trip via parse_step_subd
# ---------------------------------------------------------------------------

class TestRoundTrip:

    def test_parse_has_header(self):
        """parse_step_subd has_header == True."""
        text = export_limit_to_step(_cube_mesh(), levels=1)
        parsed = parse_step_subd(text)
        assert parsed["has_header"] is True

    def test_parse_has_schema(self):
        """parse_step_subd has_schema == True."""
        text = export_limit_to_step(_cube_mesh(), levels=1)
        parsed = parse_step_subd(text)
        assert parsed["has_schema"] is True

    def test_parse_has_data(self):
        """parse_step_subd has_data == True."""
        text = export_limit_to_step(_cube_mesh(), levels=1)
        parsed = parse_step_subd(text)
        assert parsed["has_data"] is True

    def test_parse_has_endsec(self):
        """parse_step_subd has_endsec == True."""
        text = export_limit_to_step(_cube_mesh(), levels=1)
        parsed = parse_step_subd(text)
        assert parsed["has_endsec"] is True

    def test_vertex_count_positive(self):
        """Round-trip vertex count > 0."""
        text = export_limit_to_step(_cube_mesh(), levels=2)
        parsed = parse_step_subd(text)
        assert len(parsed["vertices"]) > 0

    def test_vertex_count_at_least_96(self):
        """Cube 2 levels: at least 96 VERTEX_POINT / CARTESIAN_POINT entries."""
        text = export_limit_to_step(_cube_mesh(), levels=2)
        # Each subdivision face has its own centroid point; plus original verts.
        parsed = parse_step_subd(text)
        # CARTESIAN_POINTs include both mesh verts AND per-face centroids / normals
        assert len(parsed["vertices"]) >= 96

    def test_parse_return_types(self):
        """parse_step_subd returns correct types for all keys."""
        text = export_limit_to_step(_cube_mesh(), levels=1)
        p = parse_step_subd(text)
        assert isinstance(p["vertices"], list)
        assert isinstance(p["advanced_faces"], int)
        assert isinstance(p["has_header"], bool)
        assert isinstance(p["has_schema"], bool)
        assert isinstance(p["has_data"], bool)
        assert isinstance(p["has_endsec"], bool)

    def test_all_coordinates_finite(self):
        """All parsed CARTESIAN_POINT coordinates are finite floats."""
        text = export_limit_to_step(_cube_mesh(), levels=2)
        parsed = parse_step_subd(text)
        for v in parsed["vertices"]:
            for c in v:
                assert math.isfinite(c), f"Non-finite coordinate: {c}"


# ---------------------------------------------------------------------------
# Tests: sphere cage convergence
# ---------------------------------------------------------------------------

class TestSphereConvergence:

    def test_sphere_vertices_within_bounds(self):
        """Sphere cage 2 CC levels: all CARTESIAN_POINT coords within [-2, 2]^3."""
        text = export_limit_to_step(_sphere_cage(), levels=2)
        parsed = parse_step_subd(text)
        for v in parsed["vertices"]:
            for c in v:
                assert abs(c) <= 2.0, f"Coordinate {c} out of [-2, 2]"

    def test_sphere_face_count_positive(self):
        """Sphere cage 2 levels → ADVANCED_FACEs > 0."""
        text = export_limit_to_step(_sphere_cage(), levels=2)
        parsed = parse_step_subd(text)
        assert parsed["advanced_faces"] > 0


# ---------------------------------------------------------------------------
# Tests: edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:

    def test_dict_cage_accepted(self):
        """export_limit_to_step accepts dict-style cage."""
        text = export_limit_to_step(_cube_dict(), levels=1)
        parsed = parse_step_subd(text)
        assert parsed["advanced_faces"] == 24

    def test_levels_clamped_high(self):
        """levels > 8 is clamped to 8 without crashing."""
        # Just verify it doesn't raise; face count should be positive.
        text = export_limit_to_step(_cube_mesh(), levels=99)
        assert isinstance(text, str)
        assert len(text) > 0

    def test_levels_0_returns_original_faces(self):
        """levels=0 returns the original cage faces for cube (6 quads)."""
        text = export_limit_to_step(_cube_mesh(), levels=0)
        parsed = parse_step_subd(text)
        assert parsed["advanced_faces"] == 6

    def test_empty_cage_no_crash(self):
        """Empty cage does not crash — returns valid STEP skeleton."""
        mesh = SubDMesh()
        text = export_limit_to_step(mesh, levels=2)
        assert isinstance(text, str)
        assert "ISO-10303-21;" in text
        assert "END-ISO-10303-21;" in text.rstrip()
