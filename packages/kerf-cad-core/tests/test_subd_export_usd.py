"""
Tests for subd_export_usd.py — USD USDA SubD export.

Coverage:
  1. Cube cage emits correct subdivisionScheme + interpolateBoundary tags.
  2. faceVertexCounts shape matches input faces.
  3. faceVertexIndices total matches sum of faceVertexCounts.
  4. points array has correct vertex count.
  5. Creased edge produces creaseIndices + creaseSharpnesses in output.
  6. Round-trip: emit USDA -> parse_usda_subd -> identical vertices + faces.
  7. Round-trip with creases preserves crease sharpness.
  8. #usda 1.0 header present.
  9. catmullClark tag present.
  10. Empty cage returns structurally valid USDA (no crash).
"""

from __future__ import annotations

import re
from typing import List

import pytest

from kerf_cad_core.geom.subd import SubDMesh
from kerf_cad_core.geom.subd_export_usd import (
    export_subd_to_usda,
    parse_usda_subd,
    write_subd_usda,
)


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
        [0, 1, 2, 3],
        [4, 5, 6, 7],
        [0, 1, 5, 4],
        [1, 2, 6, 5],
        [2, 3, 7, 6],
        [3, 0, 4, 7],
    ]
    return SubDMesh(vertices=verts, faces=faces)


def _creased_cube_mesh() -> SubDMesh:
    """Cube with one edge (0-1) sharpened to 3.5."""
    mesh = _cube_mesh()
    mesh.set_crease(0, 1, 3.5)
    return mesh


# ---------------------------------------------------------------------------
# Test 1: subdivisionScheme tag
# ---------------------------------------------------------------------------

def test_subdivision_scheme_tag():
    mesh = _cube_mesh()
    usda = export_subd_to_usda(mesh)
    assert 'subdivisionScheme = "catmullClark"' in usda, (
        'USDA must contain subdivisionScheme = "catmullClark"'
    )


# ---------------------------------------------------------------------------
# Test 2: interpolateBoundary tag
# ---------------------------------------------------------------------------

def test_interpolate_boundary_tag():
    mesh = _cube_mesh()
    usda = export_subd_to_usda(mesh)
    assert 'interpolateBoundary = "edgeAndCorner"' in usda, (
        'USDA must contain interpolateBoundary = "edgeAndCorner"'
    )


# ---------------------------------------------------------------------------
# Test 3: faceVertexCounts shape matches
# ---------------------------------------------------------------------------

def test_face_vertex_counts_shape():
    mesh = _cube_mesh()
    usda = export_subd_to_usda(mesh)
    m = re.search(r'int\[\]\s+faceVertexCounts\s*=\s*\[([^\]]*)\]', usda)
    assert m, 'faceVertexCounts array not found in USDA'
    counts = [int(x.strip()) for x in m.group(1).split(',') if x.strip()]
    assert len(counts) == 6, f'Expected 6 face entries, got {len(counts)}'
    assert all(c == 4 for c in counts), f'All faces should be quads, got {counts}'


# ---------------------------------------------------------------------------
# Test 4: faceVertexIndices total matches sum of faceVertexCounts
# ---------------------------------------------------------------------------

def test_face_vertex_indices_total():
    mesh = _cube_mesh()
    usda = export_subd_to_usda(mesh)
    fvc_m = re.search(r'int\[\]\s+faceVertexCounts\s*=\s*\[([^\]]*)\]', usda)
    fvi_m = re.search(r'int\[\]\s+faceVertexIndices\s*=\s*\[([^\]]*)\]', usda)
    assert fvc_m and fvi_m
    counts = [int(x.strip()) for x in fvc_m.group(1).split(',') if x.strip()]
    indices = [int(x.strip()) for x in fvi_m.group(1).split(',') if x.strip()]
    assert len(indices) == sum(counts), (
        f'faceVertexIndices length {len(indices)} != sum(faceVertexCounts) {sum(counts)}'
    )


# ---------------------------------------------------------------------------
# Test 5: points array has correct vertex count
# ---------------------------------------------------------------------------

def test_points_array_vertex_count():
    mesh = _cube_mesh()
    usda = export_subd_to_usda(mesh)
    pts_m = re.search(
        r'(?:float3|point3f)\[\]\s+points\s*=\s*\[(.*?)\]', usda, re.DOTALL
    )
    assert pts_m, 'points array not found in USDA'
    matches = re.findall(r'\([^)]+\)', pts_m.group(1))
    assert len(matches) == 8, f'Expected 8 vertices, got {len(matches)}'


# ---------------------------------------------------------------------------
# Test 6: creased edge produces creaseIndices + creaseSharpnesses
# ---------------------------------------------------------------------------

def test_crease_arrays_present():
    mesh = _creased_cube_mesh()
    usda = export_subd_to_usda(mesh)
    assert 'creaseIndices' in usda, 'creaseIndices missing from USDA'
    assert 'creaseLengths' in usda, 'creaseLengths missing from USDA'
    assert 'creaseSharpnesses' in usda, 'creaseSharpnesses missing from USDA'


def test_crease_indices_values():
    mesh = _creased_cube_mesh()
    usda = export_subd_to_usda(mesh)
    ci_m = re.search(r'int\[\]\s+creaseIndices\s*=\s*\[([^\]]*)\]', usda)
    assert ci_m
    ci = [int(x.strip()) for x in ci_m.group(1).split(',') if x.strip()]
    # Edge (0,1) — stored canonically as (0,1)
    assert 0 in ci and 1 in ci, f'Expected vertices 0 and 1 in creaseIndices, got {ci}'


def test_crease_sharpness_value():
    mesh = _creased_cube_mesh()
    usda = export_subd_to_usda(mesh)
    cs_m = re.search(r'float\[\]\s+creaseSharpnesses\s*=\s*\[([^\]]*)\]', usda)
    assert cs_m
    cs = [float(x.strip()) for x in cs_m.group(1).split(',') if x.strip()]
    assert len(cs) >= 1
    assert abs(cs[0] - 3.5) < 1e-4, f'Expected sharpness 3.5, got {cs[0]}'


# ---------------------------------------------------------------------------
# Test 7: no crease arrays when no creases present
# ---------------------------------------------------------------------------

def test_no_crease_arrays_when_no_creases():
    mesh = _cube_mesh()
    usda = export_subd_to_usda(mesh)
    assert 'creaseIndices' not in usda
    assert 'creaseSharpnesses' not in usda


# ---------------------------------------------------------------------------
# Test 8: USDA header
# ---------------------------------------------------------------------------

def test_usda_header():
    mesh = _cube_mesh()
    usda = export_subd_to_usda(mesh)
    assert usda.startswith('#usda 1.0'), 'USDA must start with #usda 1.0'


# ---------------------------------------------------------------------------
# Test 9: round-trip cage identity (vertices + faces)
# ---------------------------------------------------------------------------

def test_round_trip_vertices_and_faces():
    mesh = _cube_mesh()
    usda = export_subd_to_usda(mesh)
    rt = parse_usda_subd(usda)
    assert len(rt.vertices) == len(mesh.vertices), (
        f'Round-trip vertex count mismatch: {len(rt.vertices)} vs {len(mesh.vertices)}'
    )
    assert len(rt.faces) == len(mesh.faces), (
        f'Round-trip face count mismatch: {len(rt.faces)} vs {len(mesh.faces)}'
    )
    # Vertex positions
    for i, (orig, rt_v) in enumerate(zip(mesh.vertices, rt.vertices)):
        for j in range(3):
            assert abs(orig[j] - rt_v[j]) < 1e-4, (
                f'Vertex {i} component {j}: {orig[j]} vs {rt_v[j]}'
            )
    # Face topology
    for i, (orig_f, rt_f) in enumerate(zip(mesh.faces, rt.faces)):
        assert list(orig_f) == list(rt_f), (
            f'Face {i} mismatch: {orig_f} vs {rt_f}'
        )


# ---------------------------------------------------------------------------
# Test 10: round-trip with creases preserves sharpness
# ---------------------------------------------------------------------------

def test_round_trip_creases():
    mesh = _creased_cube_mesh()
    usda = export_subd_to_usda(mesh)
    rt = parse_usda_subd(usda)
    # Edge (0,1) should be present
    key = (0, 1)
    assert key in rt.creases, f'Crease edge (0,1) missing from round-trip; keys: {list(rt.creases)}'
    assert abs(rt.creases[key] - 3.5) < 1e-4, (
        f'Round-trip sharpness {rt.creases[key]} != 3.5'
    )


# ---------------------------------------------------------------------------
# Test 11: empty cage does not crash
# ---------------------------------------------------------------------------

def test_empty_cage_no_crash():
    mesh = SubDMesh()
    usda = export_subd_to_usda(mesh)
    assert '#usda 1.0' in usda
    rt = parse_usda_subd(usda)
    assert rt.num_vertices == 0
    assert rt.num_faces == 0


# ---------------------------------------------------------------------------
# Test 12: sharpness clamped to 10.0
# ---------------------------------------------------------------------------

def test_sharpness_clamped_to_max():
    mesh = _cube_mesh()
    mesh.set_crease(0, 1, 50.0)
    usda = export_subd_to_usda(mesh)
    cs_m = re.search(r'float\[\]\s+creaseSharpnesses\s*=\s*\[([^\]]*)\]', usda)
    assert cs_m
    cs = [float(x.strip()) for x in cs_m.group(1).split(',') if x.strip()]
    assert cs[0] <= 10.0, f'Sharpness {cs[0]} not clamped to 10.0'


# ---------------------------------------------------------------------------
# Test 13: write_subd_usda writes a file with correct content
# ---------------------------------------------------------------------------

def test_write_subd_usda_file(tmp_path):
    mesh = _cube_mesh()
    out = tmp_path / 'test_cube.usda'
    write_subd_usda(mesh, str(out))
    assert out.exists()
    content = out.read_text(encoding='utf-8')
    assert '#usda 1.0' in content
    assert 'catmullClark' in content


# ---------------------------------------------------------------------------
# Test 14: catmullClark present
# ---------------------------------------------------------------------------

def test_catmull_clark_tag():
    mesh = _cube_mesh()
    usda = export_subd_to_usda(mesh)
    assert 'catmullClark' in usda
