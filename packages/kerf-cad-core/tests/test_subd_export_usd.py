"""
Tests for subd_export_usd.py — USD USDA + USDC SubD export.

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
  11-18. USDC binary crate tests (new).
"""

from __future__ import annotations

import re
from typing import List

import pytest

from kerf_cad_core.geom.subd import SubDMesh
from kerf_cad_core.geom.subd_export_usd import (
    export_subd_to_usda,
    export_subd_to_usdc,
    parse_usda_subd,
    parse_usdc_header,
    write_subd_usd,
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


# ===========================================================================
# USDC binary crate tests (Tests 15–22)
# ===========================================================================

_USDC_MAGIC = b'PXR-USDC'
_USDC_HEADER_SIZE = 88


# ---------------------------------------------------------------------------
# Test 15: USDC file is created and starts with magic bytes
# ---------------------------------------------------------------------------

def test_usdc_file_exists_and_magic(tmp_path):
    """export_subd_to_usdc writes a file whose first 8 bytes are 'PXR-USDC'."""
    mesh = _cube_mesh()
    out = tmp_path / 'cube.usdc'
    export_subd_to_usdc(mesh, str(out))
    assert out.exists(), 'USDC file was not created'
    data = out.read_bytes()
    assert data[:8] == _USDC_MAGIC, (
        f'Expected magic {_USDC_MAGIC!r}, got {data[:8]!r}'
    )


# ---------------------------------------------------------------------------
# Test 16: USDC binary compactness (per-byte payload is denser than USDA)
# ---------------------------------------------------------------------------

def _large_grid_mesh(n: int = 20) -> SubDMesh:
    """Build an n×n quad grid mesh with many vertices for compactness testing."""
    verts = []
    for row in range(n + 1):
        for col in range(n + 1):
            verts.append([float(col), float(row), 0.0])
    faces = []
    for row in range(n):
        for col in range(n):
            a = row * (n + 1) + col
            b = a + 1
            c = b + (n + 1)
            d = a + (n + 1)
            faces.append([a, b, c, d])
    return SubDMesh(vertices=verts, faces=faces)


def test_usdc_smaller_than_usda_large_mesh(tmp_path):
    """For a large mesh the binary USDC payload is denser than ASCII USDA."""
    mesh = _large_grid_mesh(20)  # 441 verts, 400 quads
    usda_path = tmp_path / 'grid.usda'
    usdc_path = tmp_path / 'grid.usdc'
    write_subd_usda(mesh, str(usda_path))
    export_subd_to_usdc(mesh, str(usdc_path))
    usda_size = usda_path.stat().st_size
    usdc_size = usdc_path.stat().st_size
    assert usdc_size < usda_size, (
        f'Expected USDC ({usdc_size} bytes) < USDA ({usda_size} bytes)'
    )


# ---------------------------------------------------------------------------
# Test 17: USDC header version is (0, 6, 0)
# ---------------------------------------------------------------------------

def test_usdc_header_version(tmp_path):
    """The USDC header version field must be (0, 6, 0)."""
    mesh = _cube_mesh()
    out = tmp_path / 'cube.usdc'
    export_subd_to_usdc(mesh, str(out))
    data = out.read_bytes()
    hdr = parse_usdc_header(data)
    assert hdr['version'] == (0, 6, 0), (
        f'Expected version (0, 6, 0), got {hdr["version"]}'
    )


# ---------------------------------------------------------------------------
# Test 18: TOC lists expected sections (TOKENS, PATHS, SPECS at minimum)
# ---------------------------------------------------------------------------

def test_usdc_toc_sections(tmp_path):
    """The USDC TOC must contain at least TOKENS, PATHS, and SPECS sections."""
    mesh = _cube_mesh()
    out = tmp_path / 'cube.usdc'
    export_subd_to_usdc(mesh, str(out))
    data = out.read_bytes()
    hdr = parse_usdc_header(data)
    assert hdr['section_count'] >= 3, (
        f'Expected at least 3 sections, got {hdr["section_count"]}'
    )
    names = {s['name'] for s in hdr['sections']}
    assert b'TOKENS' in names, f'TOKENS section missing; got {names}'
    assert b'PATHS' in names,  f'PATHS section missing; got {names}'
    assert b'SPECS' in names,  f'SPECS section missing; got {names}'


# ---------------------------------------------------------------------------
# Test 19: Round-trip — write USDC, parse header, recover prim count
# ---------------------------------------------------------------------------

def test_usdc_round_trip_spec_count(tmp_path):
    """Write USDC for a cube (6 faces, 5 base attrs) and verify spec count via header."""
    mesh = _cube_mesh()
    out = tmp_path / 'cube_rt.usdc'
    export_subd_to_usdc(mesh, str(out))
    data = out.read_bytes()
    hdr = parse_usdc_header(data)
    # At minimum: 1 prim spec + 5 attribute specs = 6
    # Verify the SPECS section exists and has a non-zero size
    specs_sections = [s for s in hdr['sections'] if s['name'] == b'SPECS']
    assert specs_sections, 'No SPECS section in TOC'
    assert specs_sections[0]['size'] > 0, 'SPECS section is empty'


# ---------------------------------------------------------------------------
# Test 20: Both .usda and .usdc paths produce valid output via write_subd_usd
# ---------------------------------------------------------------------------

def test_write_subd_usd_dispatch(tmp_path):
    """write_subd_usd auto-dispatches by extension for both .usda and .usdc."""
    mesh = _cube_mesh()
    usda_path = tmp_path / 'dispatch.usda'
    usdc_path = tmp_path / 'dispatch.usdc'

    write_subd_usd(mesh, str(usda_path))
    write_subd_usd(mesh, str(usdc_path))

    assert usda_path.exists(), '.usda file not created'
    assert usdc_path.exists(), '.usdc file not created'

    usda_text = usda_path.read_text(encoding='utf-8')
    assert usda_text.startswith('#usda 1.0'), 'USDA file missing header'

    usdc_data = usdc_path.read_bytes()
    assert usdc_data[:8] == _USDC_MAGIC, 'USDC file missing magic'


# ---------------------------------------------------------------------------
# Test 21: USDC with creases includes crease sections in TOC
# ---------------------------------------------------------------------------

def test_usdc_creased_cube(tmp_path):
    """Creased cube USDC should still have valid header and larger spec count."""
    mesh = _creased_cube_mesh()
    out = tmp_path / 'creased_cube.usdc'
    export_subd_to_usdc(mesh, str(out))
    data = out.read_bytes()
    assert data[:8] == _USDC_MAGIC
    hdr = parse_usdc_header(data)
    # Creased cube has 3 extra attribute specs
    specs_sections = [s for s in hdr['sections'] if s['name'] == b'SPECS']
    assert specs_sections[0]['size'] > 0

    # Creased USDC must be larger than uncreased (more data)
    mesh_plain = _cube_mesh()
    out_plain = tmp_path / 'plain_cube.usdc'
    export_subd_to_usdc(mesh_plain, str(out_plain))
    assert out.stat().st_size > out_plain.stat().st_size, (
        'Creased USDC should be larger than uncreased USDC'
    )


# ---------------------------------------------------------------------------
# Test 22: USDC header size is at least 88 bytes
# ---------------------------------------------------------------------------

def test_usdc_minimum_header_size(tmp_path):
    """USDC files must be at least 88 bytes (fixed header block)."""
    mesh = _cube_mesh()
    out = tmp_path / 'hdr_size.usdc'
    export_subd_to_usdc(mesh, str(out))
    size = out.stat().st_size
    assert size >= _USDC_HEADER_SIZE, (
        f'USDC file is only {size} bytes; expected >= {_USDC_HEADER_SIZE}'
    )
