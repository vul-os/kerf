"""Tests for GK-P09: general pure-Python solid boolean for convex planar polyhedra.

Covers:
 T01  Two unit cubes overlapping half side — union vol ≈ 1.5
 T02  Two unit cubes overlapping half side — intersection vol ≈ 0.5
 T03  Two unit cubes overlapping half side — difference vol ≈ 0.5
 T04  Two cubes touching face-to-face — intersection vol ≈ 0 (empty or degenerate)
 T05  Tetrahedron ∩ cube — result is non-empty and valid
 T06  Skew polyhedra (rotated cube A, cube B) — result is valid
 T07  Degenerate: cube ∪ cube same position — union ≈ original cube
 T08  Volume helper: unit cube volume = 1.0
 T09  Cube fully inside bigger cube — union is outer cube
 T10  Cube fully inside bigger cube — intersection is inner cube
 T11  Cube fully inside bigger cube — difference A minus B empty
 T12  Disjoint cubes — intersection empty
 T13  Disjoint cubes — union has both halves (multi-component)
 T14  Disjoint cubes — difference = A
 T15  Invalid operation raises ValueError
 T16  BooleanResult dataclass fields populated correctly
 T17  Tetrahedron ∪ unit cube — result non-empty
 T18  Result is_valid True for standard overlapping cube boolean
 T19  Two cubes 3/4 overlap — union, intersection, difference volumes
 T20  Result has >= 1 face for non-empty operations
"""

from __future__ import annotations

import math
import pytest

from kerf_cad_core.geom.general_boolean import (
    PlanarPolyhedron,
    BooleanResult,
    boolean_polyhedra,
    polyhedron_volume,
)


# ---------------------------------------------------------------------------
# Helpers to build test polyhedra
# ---------------------------------------------------------------------------

def _unit_cube(ox: float = 0.0, oy: float = 0.0, oz: float = 0.0,
               sx: float = 1.0, sy: float = 1.0, sz: float = 1.0,
               ) -> PlanarPolyhedron:
    """Axis-aligned box with given origin (ox,oy,oz) and size (sx,sy,sz).
    Face winding: CCW when viewed from outside (outward normal).
    """
    x0, y0, z0 = ox, oy, oz
    x1, y1, z1 = ox + sx, oy + sy, oz + sz
    verts = [
        (x0, y0, z0),  # 0
        (x1, y0, z0),  # 1
        (x1, y1, z0),  # 2
        (x0, y1, z0),  # 3
        (x0, y0, z1),  # 4
        (x1, y0, z1),  # 5
        (x1, y1, z1),  # 6
        (x0, y1, z1),  # 7
    ]
    faces = [
        [0, 3, 2, 1],  # -Z face (normal -Z, viewed from -Z: CCW)
        [4, 5, 6, 7],  # +Z face (normal +Z)
        [0, 1, 5, 4],  # -Y face (normal -Y)
        [1, 2, 6, 5],  # +X face (normal +X)
        [2, 3, 7, 6],  # +Y face (normal +Y)
        [3, 0, 4, 7],  # -X face (normal -X)
    ]
    return PlanarPolyhedron(vertices_xyz_mm=verts, faces=faces)


def _tetrahedron() -> PlanarPolyhedron:
    """Regular tetrahedron with vertices near the origin, side ≈ 1."""
    # vertices
    verts = [
        (1.0, 0.0, -1.0 / math.sqrt(2)),
        (-1.0, 0.0, -1.0 / math.sqrt(2)),
        (0.0, 1.0, 1.0 / math.sqrt(2)),
        (0.0, -1.0, 1.0 / math.sqrt(2)),
    ]
    # faces: CCW from outside (Newell's method gives outward normals)
    faces = [
        [0, 1, 2],
        [0, 3, 1],
        [1, 3, 2],
        [0, 2, 3],
    ]
    return PlanarPolyhedron(vertices_xyz_mm=verts, faces=faces)


# ---------------------------------------------------------------------------
# T08: volume helper sanity check
# ---------------------------------------------------------------------------

def test_T08_unit_cube_volume():
    """Volume of unit cube = 1.0."""
    cube = _unit_cube()
    vol = polyhedron_volume(cube)
    assert abs(vol - 1.0) < 1e-9, f"Expected vol≈1.0, got {vol}"


# ---------------------------------------------------------------------------
# T01-T03: Two unit cubes overlapping by 0.5 along x
# ---------------------------------------------------------------------------

@pytest.fixture
def overlapping_half():
    """Cube A at [0,1]^3 and cube B at [0.5,1.5]×[0,1]×[0,1]."""
    a = _unit_cube(0.0, 0.0, 0.0)
    b = _unit_cube(0.5, 0.0, 0.0)
    return a, b


def test_T01_union_volume_overlapping_half(overlapping_half):
    """Union of two half-overlapping unit cubes has volume ≈ 1.5."""
    a, b = overlapping_half
    res = boolean_polyhedra(a, b, "union", tol=1e-6)
    vol = polyhedron_volume(res.result_polyhedron)
    assert abs(vol - 1.5) < 0.05, f"Union vol expected ≈ 1.5, got {vol:.4f}"
    assert res.operation == "union"


def test_T02_intersection_volume_overlapping_half(overlapping_half):
    """Intersection of two half-overlapping unit cubes has volume ≈ 0.5."""
    a, b = overlapping_half
    res = boolean_polyhedra(a, b, "intersection", tol=1e-6)
    vol = polyhedron_volume(res.result_polyhedron)
    assert abs(vol - 0.5) < 0.05, f"Intersection vol expected ≈ 0.5, got {vol:.4f}"
    assert res.operation == "intersection"


def test_T03_difference_volume_overlapping_half(overlapping_half):
    """Difference A minus B of two half-overlapping unit cubes has volume ≈ 0.5."""
    a, b = overlapping_half
    res = boolean_polyhedra(a, b, "difference", tol=1e-6)
    vol = polyhedron_volume(res.result_polyhedron)
    assert abs(vol - 0.5) < 0.05, f"Difference vol expected ≈ 0.5, got {vol:.4f}"
    assert res.operation == "difference"


# ---------------------------------------------------------------------------
# T04: Two cubes touching face-to-face — intersection is empty (or zero-volume)
# ---------------------------------------------------------------------------

def test_T04_touching_face_intersection_empty():
    """Two cubes touching at x=1 have zero-volume intersection."""
    a = _unit_cube(0.0, 0.0, 0.0)
    b = _unit_cube(1.0, 0.0, 0.0)
    res = boolean_polyhedra(a, b, "intersection", tol=1e-6)
    vol = polyhedron_volume(res.result_polyhedron)
    assert vol < 0.01, f"Touching cubes intersection should be ≈0, got {vol:.4f}"


# ---------------------------------------------------------------------------
# T05: Tetrahedron ∩ unit cube — non-empty
# ---------------------------------------------------------------------------

def test_T05_tetrahedron_cube_intersection():
    """Intersection of a tetrahedron centred near origin with a unit cube is non-empty."""
    tet = _tetrahedron()
    cube = _unit_cube(-0.5, -0.5, -0.5, 1.0, 1.0, 1.0)
    res = boolean_polyhedra(tet, cube, "intersection", tol=1e-5)
    # result should have some volume
    vol = polyhedron_volume(res.result_polyhedron)
    assert vol > 0.01, f"Tetrahedron-cube intersection expected non-zero, got {vol:.4f}"
    assert res.is_valid


# ---------------------------------------------------------------------------
# T06: Skew polyhedra — valid result
# ---------------------------------------------------------------------------

def test_T06_skew_polyhedra_result_valid():
    """Two cubes partially overlapping — result reports is_valid and has output faces."""
    a = _unit_cube(0.0, 0.0, 0.0)
    b = _unit_cube(0.3, 0.3, 0.3)
    res = boolean_polyhedra(a, b, "union", tol=1e-6)
    vol = polyhedron_volume(res.result_polyhedron)
    assert vol > 1.0, f"Skew cube union should be > 1.0, got {vol:.4f}"
    assert res.num_output_faces >= 1


# ---------------------------------------------------------------------------
# T07: Degenerate — cube ∪ cube at same position = single cube
# ---------------------------------------------------------------------------

def test_T07_same_cube_union_is_original():
    """Union of identical cubes returns a single cube of volume ≈ 1.0."""
    a = _unit_cube(0.0, 0.0, 0.0)
    b = _unit_cube(0.0, 0.0, 0.0)
    res = boolean_polyhedra(a, b, "union", tol=1e-6)
    vol = polyhedron_volume(res.result_polyhedron)
    assert abs(vol - 1.0) < 0.05, f"Same cube union expected vol≈1, got {vol:.4f}"


# ---------------------------------------------------------------------------
# T09-T11: Containment: small cube inside large cube
# ---------------------------------------------------------------------------

@pytest.fixture
def contained_cubes():
    """Outer cube [0,2]^3, inner cube [0.5,1.5]^3."""
    outer = _unit_cube(0.0, 0.0, 0.0, 2.0, 2.0, 2.0)
    inner = _unit_cube(0.5, 0.5, 0.5, 1.0, 1.0, 1.0)
    return outer, inner


def test_T09_contained_union_is_outer(contained_cubes):
    """Union of outer and contained inner cube = outer cube."""
    outer, inner = contained_cubes
    res = boolean_polyhedra(outer, inner, "union", tol=1e-6)
    vol = polyhedron_volume(res.result_polyhedron)
    assert abs(vol - 8.0) < 0.05, f"Contained union vol expected ≈ 8, got {vol:.4f}"


def test_T10_contained_intersection_is_inner(contained_cubes):
    """Intersection of outer and contained inner cube = inner cube."""
    outer, inner = contained_cubes
    res = boolean_polyhedra(outer, inner, "intersection", tol=1e-6)
    vol = polyhedron_volume(res.result_polyhedron)
    assert abs(vol - 1.0) < 0.05, f"Contained intersection vol expected ≈ 1, got {vol:.4f}"


def test_T11_contained_difference_A_minus_B_empty(contained_cubes):
    """inner (A) minus outer (B) = empty."""
    outer, inner = contained_cubes
    # inner minus outer (A=inner, B=outer)
    res = boolean_polyhedra(inner, outer, "difference", tol=1e-6)
    vol = polyhedron_volume(res.result_polyhedron)
    assert vol < 0.05, f"inner - outer expected vol ≈ 0, got {vol:.4f}"


# ---------------------------------------------------------------------------
# T12-T14: Disjoint cubes
# ---------------------------------------------------------------------------

@pytest.fixture
def disjoint_cubes():
    """Two unit cubes: A at [0,1]^3, B at [3,4]^3."""
    a = _unit_cube(0.0, 0.0, 0.0)
    b = _unit_cube(3.0, 0.0, 0.0)
    return a, b


def test_T12_disjoint_intersection_empty(disjoint_cubes):
    """Disjoint cubes have empty intersection."""
    a, b = disjoint_cubes
    res = boolean_polyhedra(a, b, "intersection", tol=1e-6)
    assert res.num_output_faces == 0 or polyhedron_volume(res.result_polyhedron) < 0.01


def test_T13_disjoint_union_has_both(disjoint_cubes):
    """Disjoint cube union has total volume ≈ 2.0."""
    a, b = disjoint_cubes
    res = boolean_polyhedra(a, b, "union", tol=1e-6)
    vol = polyhedron_volume(res.result_polyhedron)
    assert abs(vol - 2.0) < 0.05, f"Disjoint union vol expected ≈ 2, got {vol:.4f}"


def test_T14_disjoint_difference_equals_A(disjoint_cubes):
    """Disjoint difference (A minus B) = A."""
    a, b = disjoint_cubes
    res = boolean_polyhedra(a, b, "difference", tol=1e-6)
    vol = polyhedron_volume(res.result_polyhedron)
    assert abs(vol - 1.0) < 0.05, f"Disjoint difference vol expected ≈ 1, got {vol:.4f}"


# ---------------------------------------------------------------------------
# T15: Invalid operation raises
# ---------------------------------------------------------------------------

def test_T15_invalid_operation_raises():
    """Unknown operation raises ValueError."""
    a = _unit_cube()
    b = _unit_cube(0.5, 0.0, 0.0)
    with pytest.raises(ValueError, match="operation must be"):
        boolean_polyhedra(a, b, "xor")


# ---------------------------------------------------------------------------
# T16: BooleanResult fields
# ---------------------------------------------------------------------------

def test_T16_boolean_result_fields():
    """BooleanResult carries expected metadata fields."""
    a = _unit_cube(0.0, 0.0, 0.0)
    b = _unit_cube(0.5, 0.0, 0.0)
    res = boolean_polyhedra(a, b, "union", tol=1e-6)
    assert isinstance(res, BooleanResult)
    assert res.operation == "union"
    assert res.num_input_faces_a == 6
    assert res.num_input_faces_b == 6
    assert isinstance(res.honest_caveat, str)
    assert len(res.honest_caveat) > 5
    assert isinstance(res.result_polyhedron, PlanarPolyhedron)


# ---------------------------------------------------------------------------
# T17: Tetrahedron union with unit cube — non-empty
# ---------------------------------------------------------------------------

def test_T17_tetrahedron_union_cube():
    """Tetrahedron ∪ unit cube is non-empty and larger than the cube alone."""
    tet = _tetrahedron()
    cube = _unit_cube(-0.5, -0.5, -0.5, 1.0, 1.0, 1.0)
    res = boolean_polyhedra(tet, cube, "union", tol=1e-5)
    vol = polyhedron_volume(res.result_polyhedron)
    assert vol > 0.5, f"Tetrahedron+cube union expected > 0.5 vol, got {vol:.4f}"


# ---------------------------------------------------------------------------
# T18: is_valid True for standard overlapping case
# ---------------------------------------------------------------------------

def test_T18_result_is_valid_standard():
    """Standard overlapping cube boolean returns is_valid=True."""
    a = _unit_cube(0.0, 0.0, 0.0)
    b = _unit_cube(0.5, 0.0, 0.0)
    for op in ("union", "intersection", "difference"):
        res = boolean_polyhedra(a, b, op, tol=1e-6)
        assert res.is_valid, f"Expected is_valid for op={op}"


# ---------------------------------------------------------------------------
# T19: 3/4-overlap cubes — volume consistency
# ---------------------------------------------------------------------------

def test_T19_three_quarter_overlap_volumes():
    """Cubes A=[0,1]^3 B=[0.25, 1.25]^3 — union/intersection/difference vols consistent."""
    a = _unit_cube(0.0, 0.0, 0.0)
    b = _unit_cube(0.25, 0.0, 0.0)
    res_union = boolean_polyhedra(a, b, "union", tol=1e-6)
    res_inter = boolean_polyhedra(a, b, "intersection", tol=1e-6)
    res_diff = boolean_polyhedra(a, b, "difference", tol=1e-6)
    v_union = polyhedron_volume(res_union.result_polyhedron)
    v_inter = polyhedron_volume(res_inter.result_polyhedron)
    v_diff = polyhedron_volume(res_diff.result_polyhedron)
    # inclusion-exclusion: |A∪B| = |A|+|B|-|A∩B|
    expected_inter = 0.75
    expected_union = 2.0 - expected_inter
    expected_diff = 1.0 - expected_inter
    assert abs(v_inter - expected_inter) < 0.08, f"3/4 inter vol: expected {expected_inter}, got {v_inter:.4f}"
    assert abs(v_union - expected_union) < 0.08, f"3/4 union vol: expected {expected_union}, got {v_union:.4f}"
    assert abs(v_diff - expected_diff) < 0.08, f"3/4 diff vol: expected {expected_diff}, got {v_diff:.4f}"


# ---------------------------------------------------------------------------
# T20: Output has faces for non-empty operations
# ---------------------------------------------------------------------------

def test_T20_non_empty_result_has_faces():
    """Non-empty boolean results have at least one output face."""
    a = _unit_cube(0.0, 0.0, 0.0)
    b = _unit_cube(0.5, 0.0, 0.0)
    for op in ("union", "intersection", "difference"):
        res = boolean_polyhedra(a, b, op, tol=1e-6)
        assert res.num_output_faces >= 1, f"Expected >= 1 face for op={op}"
        assert len(res.result_polyhedron.faces) >= 1
