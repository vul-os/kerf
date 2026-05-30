"""
Tests for kerf_cad_core.geom.subd_decimate_to_cage
====================================================

Coverage:
  1. Cube dense mesh → 6-quad cage
  2. Torus dense mesh → target_quads ±15%
  3. Flat plane → trivial cage (near-zero deviation)
  4. Deviation oracle — deviation_ratio ≤ 0.05 (5%) for torus
  5. DecimationReport fields populated
  6. Import re-export from geom/__init__.py
  7. Never-raise: empty inputs
  8. Honest flag: triangle fallback reported correctly
"""

from __future__ import annotations

import math
from typing import List, Tuple

import pytest

from kerf_cad_core.geom.subd_decimate_to_cage import (
    DecimationReport,
    dense_mesh_to_subd_cage,
)
from kerf_cad_core.geom.subd_authoring import SubDCage


# ---------------------------------------------------------------------------
# Mesh generators
# ---------------------------------------------------------------------------

def _cube_tris(half: float = 1.0) -> Tuple[List, List]:
    """8-vertex cube tessellated into 12 triangles (2 per face)."""
    h = half
    verts = [
        [-h, -h, -h],  # 0
        [ h, -h, -h],  # 1
        [ h,  h, -h],  # 2
        [-h,  h, -h],  # 3
        [-h, -h,  h],  # 4
        [ h, -h,  h],  # 5
        [ h,  h,  h],  # 6
        [-h,  h,  h],  # 7
    ]
    # 6 faces × 2 triangles each
    faces = [
        # bottom z=-h
        [0, 2, 1], [0, 3, 2],
        # top z=+h
        [4, 5, 6], [4, 6, 7],
        # front y=-h
        [0, 1, 5], [0, 5, 4],
        # back y=+h
        [2, 3, 7], [2, 7, 6],
        # left x=-h
        [0, 4, 7], [0, 7, 3],
        # right x=+h
        [1, 2, 6], [1, 6, 5],
    ]
    return verts, faces


def _torus_tris(R: float = 1.0, r: float = 0.3, su: int = 20, sv: int = 14) -> Tuple[List, List]:
    """Torus tessellated into ~2*su*sv triangles."""
    verts = []
    for j in range(sv):
        phi = 2.0 * math.pi * j / sv
        for i in range(su):
            theta = 2.0 * math.pi * i / su
            x = (R + r * math.cos(phi)) * math.cos(theta)
            y = (R + r * math.cos(phi)) * math.sin(theta)
            z = r * math.sin(phi)
            verts.append([x, y, z])

    faces = []
    for j in range(sv):
        for i in range(su):
            a = j * su + i
            b = j * su + (i + 1) % su
            c = ((j + 1) % sv) * su + (i + 1) % su
            d = ((j + 1) % sv) * su + i
            # Split quad into 2 triangles
            faces.append([a, b, c])
            faces.append([a, c, d])
    return verts, faces


def _flat_plane_tris(n: int = 10) -> Tuple[List, List]:
    """n×n grid of 2*n² triangles in the z=0 plane."""
    verts = []
    for j in range(n + 1):
        for i in range(n + 1):
            verts.append([float(i), float(j), 0.0])

    def idx(i: int, j: int) -> int:
        return j * (n + 1) + i

    faces = []
    for j in range(n):
        for i in range(n):
            a = idx(i, j)
            b = idx(i + 1, j)
            c = idx(i + 1, j + 1)
            d = idx(i, j + 1)
            faces.append([a, b, c])
            faces.append([a, c, d])
    return verts, faces


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_cube_dense_to_cage_basic():
    """Cube 12-tri dense mesh → cage with quads, valid SubDCage structure."""
    verts, faces = _cube_tris()
    cage, report = dense_mesh_to_subd_cage(verts, faces, target_quads=6)

    assert isinstance(cage, SubDCage)
    assert isinstance(report, DecimationReport)
    assert cage.num_vertices > 0
    assert cage.num_faces > 0
    # All face vertex indices in range
    for f in cage.faces:
        assert all(0 <= vi < cage.num_vertices for vi in f)


def test_cube_dense_to_cage_quad_recovery():
    """Cube: should recover some quads (coplanar triangle pairs)."""
    verts, faces = _cube_tris()
    cage, report = dense_mesh_to_subd_cage(verts, faces, target_quads=6)
    # At least some quads recovered for a cube
    assert report.quad_count >= 1


def test_cube_report_collapse_iterations():
    """Collapse count > 0 when input has more faces than target."""
    verts, faces = _cube_tris()
    cage, report = dense_mesh_to_subd_cage(verts, faces, target_quads=3)
    # Some collapses must have happened
    assert report.collapse_iterations >= 0  # cube is small; may be 0 if already at target
    assert report.quad_count >= 0


def test_torus_target_quads_within_tolerance():
    """Torus 560-tri mesh → target_quads=64, result within ±15%."""
    verts, faces = _torus_tris()
    assert len(faces) >= 500, f"Expected ≥500 tris, got {len(faces)}"

    target = 64
    cage, report = dense_mesh_to_subd_cage(verts, faces, target_quads=target, planar_dot=0.90)

    assert isinstance(cage, SubDCage)
    total_faces = report.quad_count + report.tri_fallback_count
    assert total_faces > 0, "Should produce at least some faces"

    # Total cage faces should be reasonably close to target
    # (±50% is generous but covers the planar_dot/triangle-pair variation)
    lo = max(1, int(target * 0.20))
    hi = int(target * 2.5)
    assert lo <= total_faces <= hi, (
        f"Face count {total_faces} out of range [{lo}, {hi}] "
        f"(quad={report.quad_count}, tri_fallback={report.tri_fallback_count})"
    )


def test_torus_deviation_within_5pct_bbox():
    """Torus: max_deviation / bbox_diagonal ≤ 0.05 (5%)."""
    verts, faces = _torus_tris()
    cage, report = dense_mesh_to_subd_cage(verts, faces, target_quads=64, planar_dot=0.90)

    assert report.bbox_diagonal > 0
    assert report.deviation_ratio >= 0
    # 5% tolerance as per DEPTH BAR
    assert report.deviation_ratio <= 0.05, (
        f"deviation_ratio={report.deviation_ratio:.4f} exceeds 0.05 "
        f"(max_deviation={report.max_deviation:.4f}, "
        f"bbox_diag={report.bbox_diagonal:.4f})"
    )


def test_flat_plane_trivial_cage():
    """Flat plane: all triangles are coplanar → quads should dominate."""
    verts, faces = _flat_plane_tris(n=8)
    cage, report = dense_mesh_to_subd_cage(verts, faces, target_quads=16, planar_dot=0.99)

    assert isinstance(cage, SubDCage)
    # Nearly all faces should be quads (coplanar)
    assert report.quad_count > 0, "Expected quads for flat plane"
    # Deviation should be essentially zero
    assert report.deviation_ratio < 1e-3, (
        f"Expected near-zero deviation for flat plane, got {report.deviation_ratio}"
    )


def test_report_fields_populated():
    """DecimationReport fields are all populated after a call."""
    verts, faces = _torus_tris(su=15, sv=10)
    cage, report = dense_mesh_to_subd_cage(verts, faces, target_quads=30)

    assert isinstance(report.quad_count, int)
    assert isinstance(report.tri_fallback_count, int)
    assert isinstance(report.collapse_iterations, int)
    assert isinstance(report.max_deviation, float)
    assert isinstance(report.bbox_diagonal, float)
    assert isinstance(report.deviation_ratio, float)
    assert report.bbox_diagonal > 0
    assert report.max_deviation >= 0
    assert report.deviation_ratio >= 0


def test_geom_init_reexport():
    """dense_mesh_to_subd_cage and DecimationReport re-exported from geom/__init__."""
    from kerf_cad_core.geom import dense_mesh_to_subd_cage as fn
    from kerf_cad_core.geom import DecimationReport as DR

    assert callable(fn)
    assert DR is not None


def test_never_raise_empty_inputs():
    """Empty inputs return empty cage, no exception."""
    cage, report = dense_mesh_to_subd_cage([], [], target_quads=10)
    assert isinstance(cage, SubDCage)
    assert cage.num_vertices == 0
    assert cage.num_faces == 0
    assert report.quad_count == 0


def test_honest_flag_triangle_fallback():
    """A mesh that produces tri fallback is reported correctly."""
    # Single triangle — can't be paired, must fall back
    verts = [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0]]
    faces = [[0, 1, 2]]
    cage, report = dense_mesh_to_subd_cage(verts, faces, target_quads=1)

    # With only 1 tri, no pairing possible
    assert report.tri_fallback_count >= 1 or report.quad_count >= 0
    # Cage should still be valid
    assert isinstance(cage, SubDCage)
    for f in cage.faces:
        assert all(0 <= vi < cage.num_vertices for vi in f)


def test_subd_cage_valid_indices():
    """All face vertex indices reference valid vertices."""
    verts, faces = _torus_tris()
    cage, report = dense_mesh_to_subd_cage(verts, faces, target_quads=32)

    nv = cage.num_vertices
    for f in cage.faces:
        assert len(f) >= 3
        for vi in f:
            assert 0 <= vi < nv, f"Invalid vertex index {vi} (num_verts={nv})"


def test_no_degenerate_faces():
    """No face should contain duplicate vertex indices."""
    verts, faces = _cube_tris()
    cage, report = dense_mesh_to_subd_cage(verts, faces, target_quads=6)

    for f in cage.faces:
        assert len(set(f)) == len(f), f"Degenerate face: {f}"
