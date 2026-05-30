"""
Tests for subd_opensubdiv_export.py

Coverage (per DoD):
  1. OBJ round-trip: cage -> export OBJ -> re-import -> identical topology + crease tags
  2. JSON format validity: cage -> JSON -> valid JSON; topology table has expected schema
  3. Compatibility check: cage with crease=15 -> flags as out-of-OSD-range
  4. Pyramid level count: max_level=3 -> returns dict with 4 entries (levels 0,1,2,3)

All tests are hermetic: no network, no database, no OCC, temp files only.
"""

from __future__ import annotations

import json
import math
import os
import tempfile
from typing import Dict, List, Tuple

import pytest

from kerf_cad_core.geom.subd import SubDMesh
from kerf_cad_core.geom.subd_opensubdiv_export import (
    CompatibilityReport,
    export_to_opensubdiv,
    generate_subdivision_pyramid,
    import_from_opensubdiv,
    opensubdiv_compatibility_check,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _unit_cube_mesh() -> SubDMesh:
    """Unit cube SubDMesh with one edge sharpened to 2.5 (OSD-valid)."""
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
        [0, 1, 2, 3],
        [4, 5, 6, 7],
        [0, 1, 5, 4],
        [2, 3, 7, 6],
        [0, 3, 7, 4],
        [1, 2, 6, 5],
    ]
    mesh = SubDMesh(vertices=verts, faces=faces)
    mesh.set_crease(0, 1, 2.5)  # valid OSD sharpness
    return mesh


def _mesh_with_out_of_range_crease() -> SubDMesh:
    """Simple quad with a crease=15 — out of OSD [0,10] range."""
    verts = [
        [0.0, 0.0, 0.0],
        [1.0, 0.0, 0.0],
        [1.0, 1.0, 0.0],
        [0.0, 1.0, 0.0],
    ]
    faces = [[0, 1, 2, 3]]
    mesh = SubDMesh(vertices=verts, faces=faces)
    mesh.set_crease(0, 1, 15.0)  # deliberately out of range
    return mesh


def _creases_identical(m1: SubDMesh, m2: SubDMesh, tol: float = 1e-5) -> bool:
    """Check that two meshes have the same crease keys and values (within tol)."""
    keys1 = set(k for k, v in m1.creases.items() if v > 0)
    keys2 = set(k for k, v in m2.creases.items() if v > 0)
    if keys1 != keys2:
        return False
    for k in keys1:
        if abs(m1.creases[k] - m2.creases[k]) > tol:
            return False
    return True


def _topology_identical(m1: SubDMesh, m2: SubDMesh) -> bool:
    """Check vertex count, face count, and face structure are identical."""
    if m1.num_vertices != m2.num_vertices:
        return False
    if m1.num_faces != m2.num_faces:
        return False
    for f1, f2 in zip(m1.faces, m2.faces):
        if list(f1) != list(f2):
            return False
    return True


def _verts_close(m1: SubDMesh, m2: SubDMesh, tol: float = 1e-5) -> bool:
    if len(m1.vertices) != len(m2.vertices):
        return False
    for v1, v2 in zip(m1.vertices, m2.vertices):
        for a, b in zip(v1, v2):
            if abs(a - b) > tol:
                return False
    return True


# ---------------------------------------------------------------------------
# Test 1: OBJ round-trip
# ---------------------------------------------------------------------------

class TestObjRoundTrip:
    """OBJ export -> re-import produces identical topology and crease tags."""

    def test_vertex_count_preserved(self) -> None:
        mesh = _unit_cube_mesh()
        with tempfile.NamedTemporaryFile(suffix=".obj", delete=False) as f:
            path = f.name
        try:
            export_to_opensubdiv(mesh, path, format="obj")
            reloaded = import_from_opensubdiv(path, format="obj")
            assert reloaded.num_vertices == mesh.num_vertices
        finally:
            os.unlink(path)

    def test_face_topology_preserved(self) -> None:
        mesh = _unit_cube_mesh()
        with tempfile.NamedTemporaryFile(suffix=".obj", delete=False) as f:
            path = f.name
        try:
            export_to_opensubdiv(mesh, path, format="obj")
            reloaded = import_from_opensubdiv(path, format="obj")
            assert _topology_identical(mesh, reloaded), (
                f"Face topology mismatch: orig={mesh.faces} re={reloaded.faces}"
            )
        finally:
            os.unlink(path)

    def test_vertex_positions_preserved(self) -> None:
        mesh = _unit_cube_mesh()
        with tempfile.NamedTemporaryFile(suffix=".obj", delete=False) as f:
            path = f.name
        try:
            export_to_opensubdiv(mesh, path, format="obj")
            reloaded = import_from_opensubdiv(path, format="obj")
            assert _verts_close(mesh, reloaded), "Vertex positions differ after OBJ round-trip"
        finally:
            os.unlink(path)

    def test_crease_tags_preserved(self) -> None:
        """OBJ round-trip must preserve crease sharpness via osd:crease lines."""
        mesh = _unit_cube_mesh()
        with tempfile.NamedTemporaryFile(suffix=".obj", delete=False) as f:
            path = f.name
        try:
            export_to_opensubdiv(mesh, path, format="obj")
            reloaded = import_from_opensubdiv(path, format="obj")
            assert _creases_identical(mesh, reloaded), (
                f"Crease mismatch: orig={mesh.creases} re={reloaded.creases}"
            )
        finally:
            os.unlink(path)

    def test_obj_extension_comments_present(self) -> None:
        """OBJ file must contain '# osd:crease' lines for creased edges."""
        mesh = _unit_cube_mesh()
        with tempfile.NamedTemporaryFile(suffix=".obj", delete=False, mode="w") as f:
            path = f.name
        try:
            export_to_opensubdiv(mesh, path, format="obj")
            content = open(path).read()
            assert "# osd:crease" in content, "OBJ file missing '# osd:crease' extension line"
        finally:
            os.unlink(path)

    def test_obj_disclaimer_present(self) -> None:
        """OBJ file must carry the Pixar non-certification disclaimer."""
        mesh = _unit_cube_mesh()
        with tempfile.NamedTemporaryFile(suffix=".obj", delete=False, mode="w") as f:
            path = f.name
        try:
            export_to_opensubdiv(mesh, path, format="obj")
            content = open(path).read()
            assert "NOT OpenSubdiv-certified by Pixar" in content
        finally:
            os.unlink(path)


# ---------------------------------------------------------------------------
# Test 2: JSON format validity
# ---------------------------------------------------------------------------

class TestJsonFormatValidity:
    """JSON export produces valid JSON with the expected OpenSubdiv schema."""

    def test_is_valid_json(self) -> None:
        mesh = _unit_cube_mesh()
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = f.name
        try:
            export_to_opensubdiv(mesh, path, format="json")
            with open(path) as fh:
                doc = json.load(fh)  # must not raise
            assert isinstance(doc, dict)
        finally:
            os.unlink(path)

    def test_schema_fields_present(self) -> None:
        """JSON document must have all required TopologyDescriptor fields."""
        required = {
            "opensubdiv", "disclaimer", "scheme",
            "vertices", "faceVertexCounts", "faceVertexIndices",
            "creaseVertexIndexPairs", "creaseWeights",
        }
        mesh = _unit_cube_mesh()
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = f.name
        try:
            export_to_opensubdiv(mesh, path, format="json")
            with open(path) as fh:
                doc = json.load(fh)
            missing = required - set(doc.keys())
            assert not missing, f"Missing JSON schema fields: {missing}"
        finally:
            os.unlink(path)

    def test_scheme_is_catmull_clark(self) -> None:
        mesh = _unit_cube_mesh()
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = f.name
        try:
            export_to_opensubdiv(mesh, path, format="json")
            with open(path) as fh:
                doc = json.load(fh)
            assert doc["scheme"] == "catmull_clark"
        finally:
            os.unlink(path)

    def test_face_vertex_counts_correct(self) -> None:
        """faceVertexCounts must match the face valence of the input cage."""
        mesh = _unit_cube_mesh()
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = f.name
        try:
            export_to_opensubdiv(mesh, path, format="json")
            with open(path) as fh:
                doc = json.load(fh)
            expected_counts = [len(f) for f in mesh.faces]
            assert doc["faceVertexCounts"] == expected_counts
        finally:
            os.unlink(path)

    def test_crease_arrays_length_match(self) -> None:
        """creaseVertexIndexPairs and creaseWeights must have the same length."""
        mesh = _unit_cube_mesh()
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = f.name
        try:
            export_to_opensubdiv(mesh, path, format="json")
            with open(path) as fh:
                doc = json.load(fh)
            assert len(doc["creaseVertexIndexPairs"]) == len(doc["creaseWeights"])
        finally:
            os.unlink(path)

    def test_opensubdiv_version_field(self) -> None:
        mesh = _unit_cube_mesh()
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = f.name
        try:
            export_to_opensubdiv(mesh, path, format="json")
            with open(path) as fh:
                doc = json.load(fh)
            assert doc["opensubdiv"] == "3.5"
        finally:
            os.unlink(path)

    def test_json_round_trip(self) -> None:
        """JSON round-trip preserves topology and creases."""
        mesh = _unit_cube_mesh()
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = f.name
        try:
            export_to_opensubdiv(mesh, path, format="json")
            reloaded = import_from_opensubdiv(path, format="json")
            assert _topology_identical(mesh, reloaded)
            assert _verts_close(mesh, reloaded)
            assert _creases_identical(mesh, reloaded)
        finally:
            os.unlink(path)

    def test_json_disclaimer_present(self) -> None:
        mesh = _unit_cube_mesh()
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = f.name
        try:
            export_to_opensubdiv(mesh, path, format="json")
            with open(path) as fh:
                doc = json.load(fh)
            assert "NOT OpenSubdiv-certified by Pixar" in doc.get("disclaimer", "")
        finally:
            os.unlink(path)


# ---------------------------------------------------------------------------
# Test 3: Compatibility check — crease=15 flagged
# ---------------------------------------------------------------------------

class TestCompatibilityCheck:
    """opensubdiv_compatibility_check correctly identifies incompatibilities."""

    def test_out_of_range_crease_flagged(self) -> None:
        """A cage with crease=15 must produce an issue about sharpness > 10."""
        mesh = _mesh_with_out_of_range_crease()
        report = opensubdiv_compatibility_check(mesh)
        assert not report.ok, "Expected compatibility check to fail for crease=15"
        assert any("15" in issue or "10" in issue for issue in report.issues), (
            f"Expected issue mentioning crease=15 or max=10; got: {report.issues}"
        )

    def test_valid_cage_passes(self) -> None:
        """A well-formed cube cage with valid creases should pass compatibility."""
        mesh = _unit_cube_mesh()
        report = opensubdiv_compatibility_check(mesh)
        assert report.ok, f"Expected valid cube to pass; issues: {report.issues}"
        assert report.issues == []

    def test_non_manifold_edge_flagged(self) -> None:
        """An edge shared by 3 faces must be flagged as non-manifold."""
        # Build a mesh where edge 0-1 is shared by 3 faces (invalid for OSD)
        verts = [
            [0.0, 0.0, 0.0],  # 0
            [1.0, 0.0, 0.0],  # 1
            [0.5, 1.0, 0.0],  # 2
            [0.5, -1.0, 0.0], # 3
            [0.5, 0.0, 1.0],  # 4
        ]
        # Three faces sharing edge 0-1
        faces = [
            [0, 1, 2],
            [0, 1, 3],
            [0, 1, 4],
        ]
        mesh = SubDMesh(vertices=verts, faces=faces)
        report = opensubdiv_compatibility_check(mesh)
        assert not report.ok
        assert any("non-manifold" in issue.lower() or "3 face" in issue.lower()
                   for issue in report.issues), (
            f"Expected non-manifold issue; got: {report.issues}"
        )

    def test_out_of_bounds_vertex_index_flagged(self) -> None:
        """A face referencing a vertex index beyond len(vertices) must be flagged."""
        verts = [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.5, 1.0, 0.0]]
        faces = [[0, 1, 99]]  # index 99 is out of bounds
        mesh = SubDMesh(vertices=verts, faces=faces)
        report = opensubdiv_compatibility_check(mesh)
        assert not report.ok
        assert any("99" in issue or "out of range" in issue.lower()
                   for issue in report.issues)

    def test_negative_crease_flagged(self) -> None:
        """Negative crease sharpness must be flagged."""
        verts = [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [1.0, 1.0, 0.0], [0.0, 1.0, 0.0]]
        faces = [[0, 1, 2, 3]]
        mesh = SubDMesh(vertices=verts, faces=faces)
        # Force a negative crease directly (bypass the clamp in set_crease)
        mesh.creases[(0, 1)] = -1.0
        report = opensubdiv_compatibility_check(mesh)
        assert not report.ok
        assert any("negative" in issue.lower() for issue in report.issues)

    def test_report_type(self) -> None:
        """Return type is always CompatibilityReport."""
        mesh = _unit_cube_mesh()
        report = opensubdiv_compatibility_check(mesh)
        assert isinstance(report, CompatibilityReport)


# ---------------------------------------------------------------------------
# Test 4: Pyramid level count
# ---------------------------------------------------------------------------

class TestSubdivisionPyramid:
    """generate_subdivision_pyramid produces exactly max_level+1 entries."""

    def test_level_count_3(self) -> None:
        """max_level=3 -> dict with keys 0,1,2,3 (4 entries)."""
        mesh = _unit_cube_mesh()
        pyramid = generate_subdivision_pyramid(mesh, max_level=3)
        assert len(pyramid) == 4, f"Expected 4 levels (0..3), got {len(pyramid)}"
        assert set(pyramid.keys()) == {0, 1, 2, 3}

    def test_level_count_default(self) -> None:
        """Default max_level=5 -> 6 entries."""
        mesh = _unit_cube_mesh()
        pyramid = generate_subdivision_pyramid(mesh, max_level=5)
        assert len(pyramid) == 6
        assert set(pyramid.keys()) == {0, 1, 2, 3, 4, 5}

    def test_level_0_is_input_cage(self) -> None:
        """Level 0 must have the same vertex count as the input cage."""
        mesh = _unit_cube_mesh()
        pyramid = generate_subdivision_pyramid(mesh, max_level=2)
        assert pyramid[0].num_vertices == mesh.num_vertices

    def test_vertex_count_grows_with_level(self) -> None:
        """Each successive level must have strictly more vertices than the previous."""
        mesh = _unit_cube_mesh()
        pyramid = generate_subdivision_pyramid(mesh, max_level=3)
        for level in range(1, 4):
            assert pyramid[level].num_vertices > pyramid[level - 1].num_vertices, (
                f"Level {level} vertex count {pyramid[level].num_vertices} "
                f"<= level {level-1} vertex count {pyramid[level-1].num_vertices}"
            )

    def test_returns_subd_mesh(self) -> None:
        """All values must be SubDMesh instances."""
        mesh = _unit_cube_mesh()
        pyramid = generate_subdivision_pyramid(mesh, max_level=2)
        for level, subd in pyramid.items():
            assert isinstance(subd, SubDMesh), (
                f"Level {level} value is {type(subd)}, expected SubDMesh"
            )

    def test_max_level_0(self) -> None:
        """max_level=0 -> single entry {0: cage}."""
        mesh = _unit_cube_mesh()
        pyramid = generate_subdivision_pyramid(mesh, max_level=0)
        assert len(pyramid) == 1
        assert 0 in pyramid

    def test_face_count_grows_with_level(self) -> None:
        """Catmull-Clark splits each N-face into N quads so face count grows."""
        mesh = _unit_cube_mesh()
        pyramid = generate_subdivision_pyramid(mesh, max_level=2)
        for level in range(1, 3):
            assert pyramid[level].num_faces > pyramid[level - 1].num_faces


# ---------------------------------------------------------------------------
# Test 5: Binary round-trip
# ---------------------------------------------------------------------------

class TestBinaryRoundTrip:
    """Binary export -> re-import preserves topology and creases."""

    def test_binary_round_trip(self) -> None:
        mesh = _unit_cube_mesh()
        with tempfile.NamedTemporaryFile(suffix=".kosd", delete=False) as f:
            path = f.name
        try:
            export_to_opensubdiv(mesh, path, format="binary")
            reloaded = import_from_opensubdiv(path, format="binary")
            assert _topology_identical(mesh, reloaded)
            assert _verts_close(mesh, reloaded, tol=1e-4)  # float32 precision
            assert _creases_identical(mesh, reloaded, tol=1e-4)
        finally:
            os.unlink(path)

    def test_binary_magic_header(self) -> None:
        """Binary file must start with KOSD magic bytes."""
        mesh = _unit_cube_mesh()
        with tempfile.NamedTemporaryFile(suffix=".kosd", delete=False) as f:
            path = f.name
        try:
            export_to_opensubdiv(mesh, path, format="binary")
            with open(path, "rb") as fh:
                magic = fh.read(4)
            assert magic == b"KOSD"
        finally:
            os.unlink(path)


# ---------------------------------------------------------------------------
# Test 6: Never-raise guards
# ---------------------------------------------------------------------------

class TestNeverRaise:
    """All public functions must never raise on bad input."""

    def test_export_invalid_format(self) -> None:
        mesh = _unit_cube_mesh()
        # Should silently return, not raise
        export_to_opensubdiv(mesh, "/tmp/_kerf_osd_test.xyz", format="bogus")

    def test_import_missing_file(self) -> None:
        result = import_from_opensubdiv("/tmp/nonexistent_kerf_osd.obj", format="obj")
        assert isinstance(result, SubDMesh)

    def test_compatibility_check_empty_mesh(self) -> None:
        report = opensubdiv_compatibility_check(SubDMesh())
        assert isinstance(report, CompatibilityReport)

    def test_pyramid_negative_level(self) -> None:
        mesh = _unit_cube_mesh()
        pyramid = generate_subdivision_pyramid(mesh, max_level=-1)
        # Should clamp to 0 and return {0: cage}
        assert len(pyramid) >= 1
