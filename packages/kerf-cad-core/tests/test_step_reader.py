"""Tests for the pure-Python STEP AP203/214 B-rep reader (T-156).

Oracle: read the synthetic AP214 unit-cube fixture, validate topology,
and verify F=6 E=12 V=8 and volume=1.0 ± 1e-9.
"""

import math
import pathlib

import numpy as np
import pytest

FIXTURES = pathlib.Path(__file__).parent / "fixtures"

from kerf_cad_core.io.step_reader import StepReadError, body_volume, read_step
from kerf_cad_core.geom.brep import validate_body


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _cube_path() -> pathlib.Path:
    p = FIXTURES / "cube_ap214.step"
    assert p.exists(), f"Fixture not found: {p}"
    return p


# ---------------------------------------------------------------------------
# Core oracle tests
# ---------------------------------------------------------------------------


def test_read_cube_validate_body_passes():
    """validate_body must return ok=True for the parsed cube."""
    body = read_step(_cube_path())
    result = validate_body(body)
    assert result["ok"], f"validate_body errors: {result['errors']}"


def test_read_cube_face_count():
    """A unit cube has exactly 6 faces."""
    body = read_step(_cube_path())
    assert len(body.all_faces()) == 6


def test_read_cube_edge_count():
    """A unit cube has exactly 12 edges."""
    body = read_step(_cube_path())
    assert len(body.all_edges()) == 12


def test_read_cube_vertex_count():
    """A unit cube has exactly 8 vertices."""
    body = read_step(_cube_path())
    assert len(body.all_vertices()) == 8


def test_read_cube_volume():
    """Volume of the [0,1]^3 unit cube must be 1.0 ± 1e-9."""
    body = read_step(_cube_path())
    vol = body_volume(body)
    assert abs(vol - 1.0) < 1e-9, f"Volume {vol!r} != 1.0"


def test_read_cube_euler_poincare():
    """Euler-Poincare residual must be zero (V-E+F-H-2(S-G)=0)."""
    body = read_step(_cube_path())
    assert body.euler_poincare_residual() == 0


def test_read_cube_solid_count():
    """There is exactly one solid in the parsed body."""
    body = read_step(_cube_path())
    assert len(body.solids) == 1


# ---------------------------------------------------------------------------
# Structural integrity checks
# ---------------------------------------------------------------------------


def test_read_cube_shell_is_closed():
    """The outer shell must be flagged as closed."""
    body = read_step(_cube_path())
    sh = body.solids[0].outer_shell
    assert sh is not None
    assert sh.is_closed


def test_read_cube_all_faces_have_surfaces():
    """Every face in the parsed body must have a surface attached."""
    body = read_step(_cube_path())
    for face in body.all_faces():
        assert face.surface is not None


def test_read_cube_all_edges_have_valid_geometry():
    """Every edge must have a curve with an evaluate() method."""
    body = read_step(_cube_path())
    for edge in body.all_edges():
        assert hasattr(edge.curve, "evaluate"), (
            f"Edge curve {edge.curve!r} missing evaluate()"
        )
        pt = np.asarray(edge.curve.evaluate(0.5), dtype=float)
        assert pt.shape == (3,)
        assert not np.any(np.isnan(pt))


def test_read_cube_vertex_positions_in_unit_range():
    """All vertex coordinates must be in [0, 1] for the unit cube."""
    body = read_step(_cube_path())
    for v in body.all_vertices():
        for coord in v.point:
            assert -1e-9 <= coord <= 1.0 + 1e-9, (
                f"Vertex coordinate {coord!r} out of [0,1] range"
            )


def test_read_cube_loops_closed():
    """Every loop must be closed (end of last coedge meets start of first)."""
    body = read_step(_cube_path())
    tol = 1e-6
    for lp in body.all_loops():
        if not lp.coedges:
            continue
        n = len(lp.coedges)
        for i, ce in enumerate(lp.coedges):
            nxt = lp.coedges[(i + 1) % n]
            gap = float(np.linalg.norm(
                np.asarray(ce.end_point(), dtype=float) -
                np.asarray(nxt.start_point(), dtype=float)
            ))
            assert gap < tol, (
                f"Loop {lp.id} open at coedge {ce.id}: gap={gap:.3e}"
            )


# ---------------------------------------------------------------------------
# Inline / string API tests
# ---------------------------------------------------------------------------


def test_read_from_string():
    """read_step must accept raw STEP text as a string."""
    text = _cube_path().read_text(encoding="utf-8")
    body = read_step(text)
    assert len(body.all_faces()) == 6


def test_read_from_path_object():
    """read_step must accept a pathlib.Path argument."""
    body = read_step(_cube_path())
    assert len(body.all_faces()) == 6


def test_read_from_str_path():
    """read_step must accept a plain string path."""
    body = read_step(str(_cube_path()))
    assert len(body.all_faces()) == 6


# ---------------------------------------------------------------------------
# Error-path tests
# ---------------------------------------------------------------------------


def test_empty_data_raises():
    """A STEP file with an empty DATA section should raise StepReadError."""
    step_text = (
        "ISO-10303-21;\nHEADER;\nENDSEC;\n"
        "DATA;\nENDSEC;\nEND-ISO-10303-21;\n"
    )
    with pytest.raises(StepReadError):
        read_step(step_text)


def test_no_data_section_raises():
    """Text without a DATA; marker must raise StepReadError."""
    with pytest.raises(StepReadError):
        read_step("not a step file at all")


def test_validate_false_skips_validation():
    """With validate=False a body is returned even for minimal STEP text."""
    # Build minimal valid-enough STEP with one face — may fail validate
    # but should not raise with validate=False.
    body = read_step(_cube_path(), validate=False)
    assert body is not None
    assert len(body.all_faces()) > 0


# ---------------------------------------------------------------------------
# STEP comment + continuation tolerance
# ---------------------------------------------------------------------------


def test_tolerates_comments_in_data():
    """Parser must silently skip /* ... */ comments inside DATA section."""
    text = _cube_path().read_text(encoding="utf-8")
    # Insert comments in random places
    patched = text.replace(
        "#30 = VERTEX_POINT",
        "/* inline comment */ #30 = VERTEX_POINT",
    )
    body = read_step(patched)
    assert len(body.all_faces()) == 6


def test_tolerates_multiline_entity():
    """Parser must handle entities split across multiple physical lines."""
    text = _cube_path().read_text(encoding="utf-8")
    # Split one line to ensure multi-line handling works
    patched = text.replace(
        "#100 = ADVANCED_FACE",
        "#100 =\n  ADVANCED_FACE",
    )
    body = read_step(patched)
    assert len(body.all_faces()) == 6
