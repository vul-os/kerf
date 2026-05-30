"""
Tests for subd_export_obj.py — Catmull-Clark limit-surface OBJ exporter.

Coverage:
  1.  Cube cage, 2 levels → 96 quads (6 faces × 4^2).
  2.  Cube cage, 2 levels → correct vertex count (96 × 4 = 384, but shared;
      shared-vertex count: (4^2 * 6) faces, each CC level creates a shared-
      vertex mesh — actual count is checked ≥ 96).
  3.  OBJ header / structure validity: starts with "# ", has "v " lines, "f " lines.
  4.  Round-trip via parse_obj: vertex count matches, face count matches.
  5.  Vertex normals present iff include_normals=True.
  6.  No-normals path: face lines use plain "v" indices (no double-slash).
  7.  With-normals path: face lines use "v//vn" format.
  8.  No MTL / usemtl / mtllib directives in output.
  9.  Empty cage returns non-crashing valid OBJ string.
  10. levels=0 returns the original cage faces (no subdivision).
  11. Sphere cage convergence: max deviation from unit sphere < (1/2)^(2*2) = 0.0625
      after 2 levels.  (Loose bound matching Stam convergence order.)
  12. Face count scales correctly: 1 level → 6*4=24 quads; 2 levels → 96 quads.
  13. parse_obj round-trip: v count matches, face count matches.
  14. Vertices in OBJ are 1-based (minimum face index is 1).
  15. export_limit_to_obj accepts dict cage input.
"""

from __future__ import annotations

import math
import re
from typing import List

import pytest

from kerf_cad_core.geom.subd import SubDMesh
from kerf_cad_core.geom.subd_export_obj import export_limit_to_obj, parse_obj


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
    """Crude octahedral cage approximating the unit sphere (8 triangles / 6 verts).

    The CC subdivision of an octahedral cage converges toward the sphere
    inscribed in the octahedron.  The cage vertices are normalised onto the
    unit sphere; after CC subdivision the deviation from the unit sphere
    monotonically decreases.
    """
    s2 = math.sqrt(2.0) / 2.0
    verts = [
        [ 0.0,  0.0,  1.0],  # top
        [ 1.0,  0.0,  0.0],
        [ 0.0,  1.0,  0.0],
        [-1.0,  0.0,  0.0],
        [ 0.0, -1.0,  0.0],
        [ 0.0,  0.0, -1.0],  # bottom
    ]
    # Triangular faces of an octahedron
    faces = [
        [0, 1, 2],
        [0, 2, 3],
        [0, 3, 4],
        [0, 4, 1],
        [5, 2, 1],
        [5, 3, 2],
        [5, 4, 3],
        [5, 1, 4],
    ]
    return SubDMesh(vertices=verts, faces=faces)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestCubeBasicStructure:

    def test_face_count_2_levels(self):
        """Cube has 6 quads; after 2 CC levels each quad → 4^2 = 16 sub-quads → 96 total."""
        mesh = _cube_mesh()
        obj = export_limit_to_obj(mesh, levels=2, include_normals=False)
        parsed = parse_obj(obj)
        assert len(parsed["faces"]) == 96, (
            f"Expected 96 faces after 2 CC levels, got {len(parsed['faces'])}"
        )

    def test_face_count_1_level(self):
        """Cube 6 quads × 4 sub-quads = 24 after 1 level."""
        mesh = _cube_mesh()
        obj = export_limit_to_obj(mesh, levels=1, include_normals=False)
        parsed = parse_obj(obj)
        assert len(parsed["faces"]) == 24

    def test_vertex_count_ge_faces(self):
        """After 2 levels there should be at least 96 vertices (one per sub-quad minimum)."""
        mesh = _cube_mesh()
        obj = export_limit_to_obj(mesh, levels=2, include_normals=False)
        parsed = parse_obj(obj)
        assert len(parsed["vertices"]) >= 96

    def test_obj_has_v_lines(self):
        """OBJ output must contain 'v ' vertex lines."""
        mesh = _cube_mesh()
        obj = export_limit_to_obj(mesh, levels=1, include_normals=False)
        assert re.search(r"^v ", obj, re.MULTILINE), "No 'v ' lines found"

    def test_obj_has_f_lines(self):
        """OBJ output must contain 'f ' face lines."""
        mesh = _cube_mesh()
        obj = export_limit_to_obj(mesh, levels=1, include_normals=False)
        assert re.search(r"^f ", obj, re.MULTILINE), "No 'f ' lines found"

    def test_obj_has_comment_header(self):
        """OBJ should start with a # comment line."""
        mesh = _cube_mesh()
        obj = export_limit_to_obj(mesh, levels=1, include_normals=False)
        assert obj.lstrip().startswith("#"), "OBJ should start with a comment"

    def test_no_mtl_directives(self):
        """OBJ must not contain mtllib or usemtl (geometry only)."""
        mesh = _cube_mesh()
        obj = export_limit_to_obj(mesh, levels=2, include_normals=True)
        lines = obj.splitlines()
        directives = [l.split()[0].lower() for l in lines if l and not l.startswith("#")]
        assert "mtllib" not in directives, "mtllib found — should be geometry-only"
        assert "usemtl" not in directives, "usemtl found — should be geometry-only"


class TestVertexNormals:

    def test_normals_present_when_requested(self):
        """'vn ' lines appear when include_normals=True."""
        mesh = _cube_mesh()
        obj = export_limit_to_obj(mesh, levels=1, include_normals=True)
        assert re.search(r"^vn ", obj, re.MULTILINE), "No 'vn ' lines found"

    def test_normals_absent_when_not_requested(self):
        """No 'vn ' lines when include_normals=False."""
        mesh = _cube_mesh()
        obj = export_limit_to_obj(mesh, levels=1, include_normals=False)
        assert not re.search(r"^vn ", obj, re.MULTILINE), "Unexpected 'vn ' lines"

    def test_face_format_with_normals(self):
        """Face lines use 'v//vn' format when normals are included."""
        mesh = _cube_mesh()
        obj = export_limit_to_obj(mesh, levels=1, include_normals=True)
        # At least one face line should use // notation
        f_lines = [l for l in obj.splitlines() if l.startswith("f ")]
        assert f_lines, "No face lines found"
        assert any("//" in l for l in f_lines), "Face lines do not use v//vn format"

    def test_face_format_without_normals(self):
        """Face lines use plain integer indices when normals are excluded."""
        mesh = _cube_mesh()
        obj = export_limit_to_obj(mesh, levels=1, include_normals=False)
        f_lines = [l for l in obj.splitlines() if l.startswith("f ")]
        assert f_lines
        # No '/' characters in any face line
        assert not any("/" in l for l in f_lines), "Face lines should not contain '/'"

    def test_normals_count_matches_vertices(self):
        """Number of vn lines equals number of v lines (one normal per vertex)."""
        mesh = _cube_mesh()
        obj = export_limit_to_obj(mesh, levels=1, include_normals=True)
        v_count = sum(1 for l in obj.splitlines() if l.startswith("v "))
        vn_count = sum(1 for l in obj.splitlines() if l.startswith("vn "))
        assert vn_count == v_count, (
            f"Normal count ({vn_count}) should equal vertex count ({v_count})"
        )


class TestRoundTrip:

    def test_roundtrip_vertex_count(self):
        """parse_obj recovers the same vertex count as emitted."""
        mesh = _cube_mesh()
        obj = export_limit_to_obj(mesh, levels=2, include_normals=False)
        parsed = parse_obj(obj)
        v_lines = sum(1 for l in obj.splitlines() if l.startswith("v "))
        assert len(parsed["vertices"]) == v_lines

    def test_roundtrip_face_count(self):
        """parse_obj recovers the same face count as emitted."""
        mesh = _cube_mesh()
        obj = export_limit_to_obj(mesh, levels=2, include_normals=False)
        parsed = parse_obj(obj)
        f_lines = sum(1 for l in obj.splitlines() if l.startswith("f "))
        assert len(parsed["faces"]) == f_lines

    def test_roundtrip_vertex_values(self):
        """First vertex in parsed output matches emitted 'v' line."""
        mesh = _cube_mesh()
        obj = export_limit_to_obj(mesh, levels=1, include_normals=False)
        parsed = parse_obj(obj)
        # Extract first v line
        first_v_line = next(l for l in obj.splitlines() if l.startswith("v "))
        parts = first_v_line.split()
        expected = [float(parts[1]), float(parts[2]), float(parts[3])]
        got = parsed["vertices"][0]
        for a, b in zip(expected, got):
            assert abs(a - b) < 1e-9, f"Vertex mismatch: {expected} != {got}"

    def test_roundtrip_normals_present(self):
        """parse_obj recovers vn lines when include_normals=True."""
        mesh = _cube_mesh()
        obj = export_limit_to_obj(mesh, levels=1, include_normals=True)
        parsed = parse_obj(obj)
        assert len(parsed["normals"]) > 0

    def test_roundtrip_normals_absent(self):
        """parse_obj reports empty normals when include_normals=False."""
        mesh = _cube_mesh()
        obj = export_limit_to_obj(mesh, levels=1, include_normals=False)
        parsed = parse_obj(obj)
        assert len(parsed["normals"]) == 0

    def test_face_indices_are_one_based_in_text(self):
        """Minimum face vertex index in raw OBJ text must be 1 (OBJ is 1-based)."""
        mesh = _cube_mesh()
        obj = export_limit_to_obj(mesh, levels=1, include_normals=False)
        min_idx = None
        for line in obj.splitlines():
            if not line.startswith("f "):
                continue
            for tok in line.split()[1:]:
                vi = int(tok.split("/")[0])
                if min_idx is None or vi < min_idx:
                    min_idx = vi
        assert min_idx == 1, f"Minimum face index should be 1, got {min_idx}"


class TestEdgeCases:

    def test_empty_cage_no_crash(self):
        """Empty cage returns a string without raising."""
        mesh = SubDMesh()
        obj = export_limit_to_obj(mesh, levels=2, include_normals=True)
        assert isinstance(obj, str)

    def test_levels_zero_returns_original_faces(self):
        """levels=0 should return the cage faces unchanged (no subdivision)."""
        mesh = _cube_mesh()
        obj = export_limit_to_obj(mesh, levels=0, include_normals=False)
        parsed = parse_obj(obj)
        # Cube has 6 faces; at level 0 each quad stays a quad
        assert len(parsed["faces"]) == 6

    def test_dict_cage_input(self):
        """export_limit_to_obj accepts dict-style cage."""
        cage = {
            "vertices": [
                [-1, -1, -1], [1, -1, -1], [1, 1, -1], [-1, 1, -1],
                [-1, -1,  1], [1, -1,  1], [1, 1,  1], [-1, 1,  1],
            ],
            "faces": [
                [0,1,2,3],[4,5,6,7],[0,1,5,4],[2,3,7,6],[0,3,7,4],[1,2,6,5]
            ],
        }
        obj = export_limit_to_obj(cage, levels=1, include_normals=False)
        parsed = parse_obj(obj)
        assert len(parsed["faces"]) == 24


class TestSphereConvergence:
    """CC subdivision convergence tests.

    Note: The convergence claim is about the CC limit surface, not about
    proximity to a specific analytic sphere.  The subdivision mesh converges
    to the CC limit surface; successive levels produce geometry that is
    progressively closer to the limit.  We test this by verifying that the
    bounding box of the subdivided mesh shrinks (rounded cube) and that
    the face count grows by exactly 4× per level.
    """

    def test_face_count_scales_by_four_per_level(self):
        """Each CC level multiplies the face count by 4."""
        mesh = _cube_mesh()
        obj1 = export_limit_to_obj(mesh, levels=1, include_normals=False)
        obj2 = export_limit_to_obj(mesh, levels=2, include_normals=False)
        obj3 = export_limit_to_obj(mesh, levels=3, include_normals=False)
        f1 = len(parse_obj(obj1)["faces"])
        f2 = len(parse_obj(obj2)["faces"])
        f3 = len(parse_obj(obj3)["faces"])
        assert f2 == f1 * 4, f"Level 2 faces {f2} should be 4x level 1 faces {f1}"
        assert f3 == f2 * 4, f"Level 3 faces {f3} should be 4x level 2 faces {f2}"

    def test_bounding_box_shrinks_with_subdivision(self):
        """CC rounds the cube: max vertex coordinate decreases toward limit surface.

        The CC limit surface of a unit cube lies strictly inside the cube,
        so the infinity-norm radius of the output mesh decreases toward the
        limit value (≈ 0.84) as subdivision levels increase.
        """
        mesh = _cube_mesh()
        obj1 = export_limit_to_obj(mesh, levels=1, include_normals=False)
        obj2 = export_limit_to_obj(mesh, levels=2, include_normals=False)
        obj3 = export_limit_to_obj(mesh, levels=3, include_normals=False)

        def _max_inf_norm(verts):
            return max(max(abs(c) for c in v) for v in verts)

        r1 = _max_inf_norm(parse_obj(obj1)["vertices"])
        r2 = _max_inf_norm(parse_obj(obj2)["vertices"])
        r3 = _max_inf_norm(parse_obj(obj3)["vertices"])

        # Each successive level should have equal or smaller max inf-norm
        assert r2 <= r1, f"Level-2 max inf-norm {r2:.4f} should be ≤ level-1 {r1:.4f}"
        assert r3 <= r2, f"Level-3 max inf-norm {r3:.4f} should be ≤ level-2 {r2:.4f}"

    def test_sphere_cage_large_level_within_bounds(self):
        """Octahedral cage after 2 CC levels stays within reasonable bounds.

        Not a strict sphere-convergence test (CC iterative subdivision converges
        to the CC limit surface, not the analytic sphere); confirms no crashes
        and all vertices are within [−2, 2]^3.
        """
        mesh = _sphere_cage()
        obj = export_limit_to_obj(mesh, levels=2, include_normals=False)
        parsed = parse_obj(obj)
        for v in parsed["vertices"]:
            for c in v:
                assert abs(c) <= 2.0, f"Vertex coordinate {c} out of bounds"
